# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path
from typing import Dict, List, Optional

import msgspec
import phonenumbers
from phonenumbers import carrier, geocoder

from gateway_clients import mcc_mnc
from logutils import get_logger
from utils import get_configs

BASE_DIR = Path(__file__).resolve().parent

REGISTRY_FILE = Path(
    get_configs(
        "GATEWAY_CLIENTS_REGISTRY_FILE", default_value=str(BASE_DIR / "registry.json")
    )
)
logger = get_logger(__name__)


class GatewayClientManifest(msgspec.Struct, forbid_unknown_fields=False):
    msisdn: str
    country: str
    operator: str
    operator_code: str
    protocols: List[str]


class GatewayClientManager:
    """Manages gateway client lifecycle operations using a JSON registry."""

    def __init__(self, registry_file: Path = REGISTRY_FILE):
        self.registry_file = registry_file
        self._registry: Dict[str, GatewayClientManifest] = {}
        self._last_modified: float = 0.0

    def _load_registry(self) -> Dict[str, GatewayClientManifest]:
        try:
            current_mtime = os.stat(self.registry_file).st_mtime
        except FileNotFoundError:
            return {}

        if current_mtime == self._last_modified:
            return self._registry

        try:
            with open(self.registry_file, "rb") as f:
                registry = msgspec.json.decode(
                    f.read(), type=Dict[str, GatewayClientManifest]
                )
            self._registry = registry
            self._last_modified = current_mtime
            return self._registry
        except Exception as e:
            logger.error("Failed to read registry: %s", e)
            return self._registry

    def _save_registry(self, data: Dict[str, GatewayClientManifest]):
        try:
            self.registry_file.parent.mkdir(parents=True, exist_ok=True)
            self.registry_file.write_bytes(msgspec.json.encode(data))
            self._last_modified = os.stat(self.registry_file).st_mtime
            self._registry = data
        except (OSError, msgspec.ValidationError) as e:
            logger.error("Failed to write registry: %s", e)

    @staticmethod
    def resolve_operator_info(msisdn: str):
        """Best-effort (country, operator, operator_code, candidates) for an
        MSISDN. operator_code is only set when exactly one PLMN matches;
        otherwise candidates lists the ambiguous options. Any field may be
        None."""
        try:
            number = phonenumbers.parse(msisdn, None)
        except phonenumbers.NumberParseException as e:
            logger.error("Failed to parse MSISDN '%s': %s", msisdn, e)
            return None, None, None, []

        country = geocoder.description_for_number(number, "en") or None
        country_code = str(number.country_code)
        region = phonenumbers.region_code_for_number(number)
        operator = carrier.name_for_number(number, "en") or None

        operator_code = None
        candidates: List[str] = []
        if operator:
            network = operator.split()[0].lower()
            matches = mcc_mnc.find_matches(
                country_code=country_code,
                network=network,
                iso=region.lower() if region else None,
            )
            candidates = sorted({f"{m['mcc']}{m['mnc']}" for m in matches})
            if len(candidates) == 1:
                operator_code = candidates[0]

        return country, operator, operator_code, candidates

    def create_client(
        self,
        msisdn: str,
        protocols: List[str],
        country: Optional[str] = None,
        operator: Optional[str] = None,
        operator_code: Optional[str] = None,
    ) -> GatewayClientManifest:
        """Register a gateway client. country/operator/operator_code are
        resolved from the MSISDN unless given explicitly."""
        registry = self._load_registry()
        if msisdn in registry:
            raise ValueError(f"Gateway client '{msisdn}' is already registered.")

        resolved_country, resolved_operator, resolved_operator_code, candidates = (
            self.resolve_operator_info(msisdn)
        )
        country = country or resolved_country
        operator = operator or resolved_operator
        operator_code = operator_code or resolved_operator_code

        if not all((country, operator, operator_code)):
            if candidates:
                raise ValueError(
                    f"Multiple PLMNs match operator '{operator}': "
                    f"{', '.join(candidates)}. Specify one with --operator-code."
                )

            missing = [
                label
                for label, value in (
                    ("country", country),
                    ("operator", operator),
                    ("operator_code", operator_code),
                )
                if not value
            ]
            raise ValueError(
                "Could not resolve "
                + ", ".join(missing)
                + " for this MSISDN. Supply it directly with --country/"
                "--operator/--operator-code, or if the operator is known but "
                "its PLMN is missing, add it with 'mcc-mnc add-override'."
            )

        manifest = GatewayClientManifest(
            msisdn=msisdn,
            country=country,
            operator=operator,
            operator_code=operator_code,
            protocols=list(protocols),
        )
        registry[msisdn] = manifest
        self._save_registry(registry)
        logger.info("Registered gateway client: %s", msisdn)
        return manifest

    def list_clients(
        self,
        msisdn: Optional[str] = None,
        country: Optional[str] = None,
        operator: Optional[str] = None,
    ) -> List[GatewayClientManifest]:
        """Return manifests matching any combination of optional filters."""
        registry = self._load_registry()
        if not registry:
            return []

        m_term = msisdn.strip() if msisdn else None
        c_term = country.strip().lower() if country else None
        o_term = operator.strip().lower() if operator else None

        return [
            manifest
            for manifest in registry.values()
            if not (m_term and manifest.msisdn != m_term)
            and not (c_term and manifest.country.strip().lower() != c_term)
            and not (o_term and manifest.operator.strip().lower() != o_term)
        ]

    def update_client(
        self,
        msisdn: str,
        country: Optional[str] = None,
        operator: Optional[str] = None,
        operator_code: Optional[str] = None,
        protocols: Optional[List[str]] = None,
    ) -> GatewayClientManifest:
        """Update an existing gateway client's fields."""
        registry = self._load_registry()
        manifest = registry.get(msisdn)
        if not manifest:
            raise ValueError(f"No gateway client found with MSISDN: {msisdn}")

        updated = GatewayClientManifest(
            msisdn=manifest.msisdn,
            country=country or manifest.country,
            operator=operator or manifest.operator,
            operator_code=operator_code or manifest.operator_code,
            protocols=list(protocols) if protocols else manifest.protocols,
        )
        registry[msisdn] = updated
        self._save_registry(registry)
        logger.info("Updated gateway client: %s", msisdn)
        return updated

    def delete_client(self, msisdn: str):
        """Remove a gateway client from the registry."""
        registry = self._load_registry()
        if msisdn not in registry:
            raise ValueError(f"No gateway client found with MSISDN: {msisdn}")

        del registry[msisdn]
        self._save_registry(registry)
        logger.info("Removed gateway client: %s", msisdn)

    def list_countries(self) -> List[str]:
        """Return all unique countries present in the registry."""
        registry = self._load_registry()
        return sorted({manifest.country for manifest in registry.values()})

    def list_operators(self, country: str) -> List[str]:
        """Return all unique operators for a given country."""
        registry = self._load_registry()
        c_term = country.strip().lower()
        return sorted(
            {
                manifest.operator
                for manifest in registry.values()
                if manifest.country.strip().lower() == c_term
            }
        )
