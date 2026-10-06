# SPDX-License-Identifier: GPL-3.0-only

import datetime

import pytest

from publisher import db
from publisher.models import audit_event
from publisher.models.audit_event import AREA_SCOPES, AuditAction, AuditEvent
from tests.helpers import USERNAME, basic_auth, create_credential, get_etag, login

pytestmark = pytest.mark.usefixtures("test_db", "fast_hasher")

URL = "/v1/audit-events"
NOW = datetime.datetime.now(datetime.UTC)


def _events(client, headers, **params):
    response = client.get(URL, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_requires_audit_read(client):
    assert client.get(URL).status_code == 401

    headers = basic_auth("reader", create_credential("reader", ["creds:read"]))
    response = client.get(URL, headers=headers)

    assert response.status_code == 403
    assert response.json()["error"] == "Missing scope: audit:read."


def test_records_credential_changes_newest_first(client, admin):
    client.post(
        "/v1/creds",
        json={"username": "analyst", "scopes": ["gc:read"]},
        headers=admin,
    )
    client.patch(
        "/v1/creds/analyst",
        json={"scopes": ["stats:publications:read"], "active": False},
        headers={**admin, "If-Match": get_etag(client, admin, "analyst")},
    )
    client.delete(
        "/v1/creds/analyst",
        headers={**admin, "If-Match": get_etag(client, admin, "analyst")},
    )

    data = _events(client, admin, target="analyst")["data"]

    assert [e["action"] for e in data] == [
        "creds.delete",
        "creds.update",
        "creds.create",
    ]
    assert all(e["actor"] == USERNAME and e["outcome"] == "success" for e in data)
    assert data[1]["details"] == {
        "scopes": {"added": ["stats:publications:read"], "removed": ["gc:read"]},
        "active": False,
    }
    assert data[2]["details"] == {"scopes": ["gc:read"]}
    assert "actor_id" not in data[0] and "target_id" not in data[0]


def test_cli_changes_have_no_actor(client, admin):
    create_credential("analyst", ["gc:read"])

    (event,) = _events(client, admin, action="creds.create", target="analyst")["data"]

    assert event["actor"] is None


def test_denied_change_is_recorded_and_rolled_back(client, admin):
    manager = basic_auth(
        "manager", create_credential("manager", ["creds:read", "creds:write"])
    )

    response = client.post(
        "/v1/creds",
        json={"username": "sneaky", "scopes": ["gc:read"]},
        headers=manager,
    )

    assert response.status_code == 403
    assert client.get("/v1/creds/sneaky", headers=admin).status_code == 404
    (event,) = _events(client, admin, actor="manager")["data"]
    assert event["action"] == "creds.create"
    assert event["outcome"] == "denied"
    assert event["details"]["username"] == "sneaky"
    assert "gc:read" in event["details"]["reason"]


def test_logins_and_logouts(client, admin, password):
    assert login(client, "wrong", username=USERNAME).status_code == 401
    assert login(client, "wrong", username="nobody").status_code == 401
    assert (
        client.get("/v1/auth/me", headers=basic_auth(USERNAME, "wrong")).status_code
        == 401
    )
    assert login(client, password).status_code == 200
    assert client.post("/v1/auth/logout").status_code == 204

    *data, created = _events(client, admin, target=USERNAME)["data"]

    assert created["action"] == "creds.create"
    assert [(e["action"], e["outcome"], e["actor"], e["details"]) for e in data] == [
        ("auth.logout", "success", USERNAME, None),
        ("auth.login", "success", USERNAME, {"method": "session"}),
        ("auth.login", "failed", None, {"method": "basic"}),
        ("auth.login", "failed", None, {"method": "session"}),
    ]
    assert _events(client, admin, target="nobody")["data"] == []


def test_events_need_the_area_read_scope(client, admin):
    create_credential("analyst", ["gc:read"])
    auditor = basic_auth("auditor", create_credential("auditor", ["audit:read"]))

    assert _events(client, auditor)["data"] == []
    assert _events(client, admin)["data"]


def test_pages_link_both_ways(client, admin):
    for name in ("one", "two", "three"):
        create_credential(name, ["gc:read"])

    first = _events(client, admin, action="creds.create", limit=2)
    second = client.get(first["next"], headers=admin).json()
    back = client.get(second["prev"], headers=admin).json()

    names = [e["target"] for e in first["data"] + second["data"]]
    assert names == ["three", "two", "one", USERNAME]
    assert first["prev"] is None
    assert second["next"] is None
    assert back["data"] == first["data"]
    assert "limit=2" in first["next"] and "action=creds.create" in first["next"]


def test_same_time_events_page_by_id(client, admin):
    for name in ("one", "two", "three"):
        create_credential(name, ["gc:read"])
    with db.get_session() as session:
        session.query(AuditEvent).update({"occurred_at": NOW})

    first = _events(client, admin, limit=2)
    second = client.get(first["next"], headers=admin).json()

    ids = [e["id"] for e in first["data"] + second["data"]]
    assert ids == sorted(ids, reverse=True)
    assert len(set(ids)) == 4


def test_filters_by_time(client, admin):
    create_credential("analyst", ["gc:read"])
    with db.get_session() as session:
        session.query(AuditEvent).filter_by(target_label=USERNAME).update(
            {"occurred_at": NOW - datetime.timedelta(days=10)}
        )

    since = (NOW - datetime.timedelta(days=1)).isoformat()
    until = (NOW - datetime.timedelta(days=5)).isoformat()

    assert [e["target"] for e in _events(client, admin, since=since)["data"]] == [
        "analyst"
    ]
    assert [e["target"] for e in _events(client, admin, until=until)["data"]] == [
        USERNAME
    ]


@pytest.mark.parametrize(
    "params, status",
    [
        ({"action": "creds.nope"}, 422),
        ({"cursor": "!!!"}, 400),
        ({"since": "2026-10-02T00:00:00", "until": "2026-10-01T00:00:00"}, 400),
    ],
)
def test_rejects_bad_query(client, admin, params, status):
    response = client.get(URL, headers=admin, params=params)

    assert response.status_code == status


def test_delete_older_than():
    create_credential("analyst", ["gc:read"])
    with db.get_session() as session:
        old = session.query(AuditEvent).filter_by(target_label="analyst").one()
        old.occurred_at = NOW - datetime.timedelta(days=400)
        session.flush()
        deleted = audit_event.delete_older_than(
            session, NOW - datetime.timedelta(days=365)
        )

    with db.get_session() as session:
        remaining = session.query(AuditEvent).count()

    assert deleted == 1
    assert remaining == 0


def test_every_action_has_a_read_scope():
    areas = {action.split(".")[0] for action in AuditAction}

    assert areas == set(AREA_SCOPES)
