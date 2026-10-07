# SPDX-License-Identifier: GPL-3.0-only

import re
from dataclasses import dataclass, field
from typing import Literal

import phonenumbers
from phonenumbers import carrier, geocoder
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from publisher.errors import PublisherError
from publisher.gateway_clients import mcc_mnc
from publisher.models import audit_event
from publisher.models import gateway_client as gateway_clients
from publisher.models.audit_event import AuditAction
from publisher.models.credential import Credential
from publisher.models.gateway_client import GatewayClient

MSISDN_PATTERN = re.compile(r"^\+[1-9]\d{6,14}$")
OPERATOR_CODE_PATTERN = re.compile(r"^\d{5,6}$")
_FIELDS = ("country", "operator", "operator_code", "protocols")


class GatewayClientError(PublisherError):
    pass


class GatewayClientExistsError(GatewayClientError):
    pass


class GatewayClientConflictError(GatewayClientError):
    pass


@dataclass(frozen=True)
class Candidate:
    operator_code: str
    network: str


@dataclass(frozen=True)
class Suggestion:
    """Details for an MSISDN, for an administrator to confirm before creating."""

    msisdn: str
    country: str | None = None
    iso: str | None = None
    country_code: str | None = None
    operator: str | None = None
    operator_code: str | None = None
    match: Literal["carrier", "region", "none"] = "none"
    candidates: list[Candidate] = field(default_factory=list)


def _candidates(rows: list[dict]) -> list[Candidate]:
    return list(
        dict.fromkeys(Candidate(r["mcc"] + r["mnc"], r["network"]) for r in rows)
    )


def suggest(msisdn: str) -> Suggestion:
    """Best-effort details for an MSISDN; operator_code only when unambiguous."""
    msisdn = msisdn.strip()
    try:
        number = phonenumbers.parse(msisdn, None)
    except phonenumbers.NumberParseException:
        return Suggestion(msisdn=msisdn)

    code = number.country_code or 0
    region = phonenumbers.region_code_for_number(number)
    iso = region.lower() if region and region != "001" else None
    country_code = str(code)
    operator = carrier.name_for_number(number, "en") or None
    rows = mcc_mnc.region_operators(iso, code)
    if not rows:
        return Suggestion(msisdn=msisdn, iso=iso, country_code=country_code)

    matched = mcc_mnc.match_carrier(operator, rows) if operator else []
    candidates = _candidates(matched or sorted(rows, key=lambda r: r["network"]))
    codes = {c.operator_code for c in candidates}
    return Suggestion(
        msisdn=msisdn,
        country=geocoder.country_name_for_number(number, "en") or rows[0]["country"],
        iso=iso,
        country_code=country_code,
        operator=operator,
        operator_code=codes.pop() if matched and len(codes) == 1 else None,
        match="carrier" if matched else "region",
        candidates=candidates,
    )


def check_msisdn(msisdn: str) -> str:
    """Return it stripped, or raise if it isn't in E.164 format."""
    msisdn = msisdn.strip()
    if not MSISDN_PATTERN.match(msisdn):
        raise GatewayClientError(f"MSISDN {msisdn!r} isn't in E.164 format")
    return msisdn


def _check(
    *,
    operator_code: str | None = None,
    protocols: list[str] | None = None,
) -> None:
    if operator_code is not None and not OPERATOR_CODE_PATTERN.match(operator_code):
        raise GatewayClientError(
            f"Operator code {operator_code!r} isn't an MCC + MNC of 5 or 6 digits"
        )
    if protocols is not None and not protocols:
        raise GatewayClientError("At least one protocol is required")


def _flush(session: Session, client: GatewayClient) -> None:
    # Read before flushing: a failed flush expires the client's attributes.
    msisdn = client.msisdn
    try:
        session.flush()
    except IntegrityError:
        raise GatewayClientExistsError(
            f"Gateway client {msisdn!r} is already registered"
        ) from None
    except StaleDataError:
        raise GatewayClientConflictError(
            f"Gateway client {msisdn!r} was changed concurrently; retry"
        ) from None


def get_or_raise(session: Session, msisdn: str) -> GatewayClient:
    client = gateway_clients.get_by_msisdn(session, msisdn)
    if client is None:
        raise GatewayClientError(f"No gateway client found with MSISDN {msisdn!r}")
    return client


def create(
    session: Session,
    msisdn: str,
    protocols: list[str],
    *,
    country: str | None = None,
    operator: str | None = None,
    operator_code: str | None = None,
    actor: Credential | None = None,
) -> GatewayClient:
    """Register a gateway client, filling omitted details from suggest."""
    msisdn = check_msisdn(msisdn)
    _check(operator_code=operator_code, protocols=protocols)
    if gateway_clients.get_by_msisdn(session, msisdn):
        raise GatewayClientExistsError(
            f"Gateway client {msisdn!r} is already registered"
        )

    suggestion = suggest(msisdn)
    country = country or suggestion.country
    operator = operator or suggestion.operator
    operator_code = operator_code or suggestion.operator_code

    details = {"country": country, "operator": operator, "operator_code": operator_code}
    if missing := [name for name, value in details.items() if not value]:
        message = f"Could not resolve {', '.join(missing)} for this MSISDN."
        if not operator_code and suggestion.match == "carrier":
            codes = ", ".join(sorted({c.operator_code for c in suggestion.candidates}))
            message = f"Multiple PLMNs match operator {operator!r}: {codes}."
        raise GatewayClientError(
            f"{message} Supply the missing details; suggest lists the candidates."
        )

    client = GatewayClient(
        msisdn=msisdn,
        country=country,
        operator=operator,
        operator_code=operator_code,
        protocols=list(protocols),
        created_by=actor.id if actor else None,
        updated_by=actor.id if actor else None,
    )
    session.add(client)
    _flush(session, client)
    audit_event.record(
        session,
        AuditAction.GATEWAY_CLIENTS_CREATE,
        actor=actor,
        target=client,
        details={field: getattr(client, field) for field in _FIELDS},
    )
    return client


def update(
    session: Session,
    client: GatewayClient,
    *,
    country: str | None = None,
    operator: str | None = None,
    operator_code: str | None = None,
    protocols: list[str] | None = None,
    actor: Credential | None = None,
) -> None:
    """Change the given fields; None leaves a field as it is."""
    _check(operator_code=operator_code, protocols=protocols)
    new = {
        "country": country,
        "operator": operator,
        "operator_code": operator_code,
        "protocols": list(protocols) if protocols is not None else None,
    }
    changes = {
        field: {"from": getattr(client, field), "to": value}
        for field, value in new.items()
        if value is not None and value != getattr(client, field)
    }
    if not changes:
        return
    for name, change in changes.items():
        setattr(client, name, change["to"])
    client.updated_by = actor.id if actor else None
    _flush(session, client)
    audit_event.record(
        session,
        AuditAction.GATEWAY_CLIENTS_UPDATE,
        actor=actor,
        target=client,
        details=changes,
    )


def set_enabled(
    session: Session,
    client: GatewayClient,
    enabled: bool,
    actor: Credential | None = None,
) -> None:
    if client.is_enabled == enabled:
        return
    client.is_enabled = enabled
    client.updated_by = actor.id if actor else None
    _flush(session, client)
    action = (
        AuditAction.GATEWAY_CLIENTS_ENABLE
        if enabled
        else AuditAction.GATEWAY_CLIENTS_DISABLE
    )
    audit_event.record(session, action, actor=actor, target=client)


def delete(
    session: Session, client: GatewayClient, actor: Credential | None = None
) -> None:
    audit_event.record(
        session,
        AuditAction.GATEWAY_CLIENTS_DELETE,
        actor=actor,
        target=client,
        details={field: getattr(client, field) for field in _FIELDS},
    )
    session.delete(client)
    _flush(session, client)
