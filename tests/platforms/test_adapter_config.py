# SPDX-License-Identifier: GPL-3.0-only

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from publisher import db
from publisher.models.audit_event import AuditEvent
from publisher.models.platform_adapter import PNBA, PlatformAdapter
from publisher.platforms import adapter_config
from publisher.platforms.manager import (
    AdapterConflictError,
    AdapterError,
    AdapterFaultError,
    InvalidConfigError,
)
from relaysms_adapter_sdk import InvalidParamsError, UpstreamError
from tests.helpers import add_adapter_with_manifest

pytestmark = pytest.mark.usefixtures("test_db", "platforms_config")

MANIFEST = """
entry = "rmail:Adapter"
name = "rmail"
display_name = "RelaySMS Mail"
protocol = "pnba"
category = "email"

[config.smtp_host]
required = true

[config.smtp_port]
type = "integer"

[config.smtp_password]
required = true
secret = true

[setup.api_key]
required = true
secret = true
"""


@pytest.fixture
def adapter():
    return add_adapter_with_manifest("rmail", PNBA, MANIFEST)


def credentials(adapter):
    return Path(adapter.config_path) / "credentials.json"


def stored(adapter):
    return json.loads(credentials(adapter).read_text())


def write(adapter, settings):
    credentials(adapter).parent.mkdir(parents=True, exist_ok=True)
    credentials(adapter).write_text(json.dumps(settings))


def update(adapter, values):
    with db.get_session() as session:
        adapter_config.update(session, session.get(PlatformAdapter, adapter.id), values)


def setup(adapter, inputs):
    with db.get_session() as session:
        adapter_config.setup(session, session.get(PlatformAdapter, adapter.id), inputs)


def audit_details():
    with db.get_session() as session:
        return [
            (event.action, event.details)
            for event in session.scalars(select(AuditEvent).order_by(AuditEvent.id))
        ]


def test_show_leaves_out_secret_values(adapter):
    write(adapter, {"SMTP_HOST": "smtp.example", "smtp_password": "hunter2"})

    shown = {s.field.name: (s.value, s.is_set) for s in adapter_config.show(adapter)}

    assert shown == {
        "smtp_host": ("smtp.example", True),
        "smtp_port": (None, False),
        "smtp_password": (None, True),
    }


def test_missing_names_unset_required_settings(adapter):
    assert adapter_config.missing(adapter) == ["smtp_host", "smtp_password"]
    write(adapter, {"smtp_host": "h", "smtp_password": "p"})
    assert adapter_config.missing(adapter) == []


def test_update_changes_only_the_keys_given(adapter):
    # An uppercase key and one the manifest doesn't declare, as an old file has.
    write(adapter, {"SMTP_HOST": "old", "alias_prefix": "x", "smtp_port": 25})

    update(adapter, {"SMTP_HOST": "new", "smtp_port": None})

    assert stored(adapter) == {"smtp_host": "new", "alias_prefix": "x"}
    assert credentials(adapter).stat().st_mode & 0o777 == 0o600
    assert [p.name for p in credentials(adapter).parent.iterdir()] == [
        "credentials.json"
    ]


def test_update_records_the_keys_but_not_the_values(adapter):
    update(adapter, {"smtp_password": "hunter2"})

    assert audit_details() == [("platforms.configure", {"keys": ["smtp_password"]})]


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ({"smtp_hots": "h"}, "smtp_hots isn't a setting"),
        ({"smtp_port": "25"}, "smtp_port"),
    ],
)
def test_update_refuses_invalid_values_and_leaves_the_file(adapter, values, error):
    write(adapter, {"smtp_host": "h"})

    with pytest.raises(InvalidConfigError, match=error):
        update(adapter, values)

    assert stored(adapter) == {"smtp_host": "h"}
    assert audit_details() == []


def test_a_concurrent_change_conflicts_and_leaves_the_file(adapter):
    write(adapter, {"smtp_host": "h"})
    with pytest.raises(AdapterConflictError), db.get_session() as session:
        stale = session.get(PlatformAdapter, adapter.id)
        update(adapter, {"smtp_port": 25})
        adapter_config.update(session, stale, {"smtp_host": "other"})

    assert stored(adapter) == {"smtp_host": "h", "smtp_port": 25}


def test_setup_replaces_the_file_with_what_setup_returns(adapter, adapter_calls):
    write(adapter, {"web": {"client_id": "old"}})
    adapter_calls.results["setup"] = {
        "settings": {"smtp_host": "h", "smtp_password": "p"}
    }

    setup(adapter, {"API_KEY": "k"})

    [(_, method, request)] = adapter_calls.calls
    assert (method, request.inputs) == ("setup", {"api_key": "k"})
    assert stored(adapter) == {"smtp_host": "h", "smtp_password": "p"}
    assert audit_details() == [
        ("platforms.setup", {"keys": ["smtp_host", "smtp_password"]})
    ]


@pytest.mark.parametrize(
    ("inputs", "result", "error", "message"),
    [
        ({}, {}, InvalidConfigError, "api_key is required"),
        (
            {"api_key": "k"},
            InvalidParamsError("bad key"),
            InvalidConfigError,
            "bad key",
        ),
        (
            {"api_key": "k"},
            {"settings": {"smtp_host": "h"}},
            AdapterFaultError,
            "smtp_password is required",
        ),
        (
            {"api_key": "k"},
            UpstreamError("server down"),
            AdapterFaultError,
            "setup failed: server down",
        ),
    ],
)
def test_setup_failures_leave_the_file(
    adapter, adapter_calls, inputs, result, error, message
):
    write(adapter, {"smtp_host": "old"})
    adapter_calls.results["setup"] = result

    with pytest.raises(error, match=message):
        setup(adapter, inputs)

    assert stored(adapter) == {"smtp_host": "old"}


def test_setup_needs_an_adapter_with_setup(adapter):
    (Path(adapter.path) / "adapter.toml").write_text(MANIFEST.split("[setup")[0])
    with pytest.raises(AdapterError, match="has no setup"):
        setup(adapter, {})


def test_a_broken_file_is_the_servers_fault(adapter):
    write(adapter, {})
    credentials(adapter).write_text("{")
    with pytest.raises(AdapterFaultError, match="invalid"):
        adapter_config.show(adapter)
