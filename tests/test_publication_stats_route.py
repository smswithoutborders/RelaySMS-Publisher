# SPDX-License-Identifier: GPL-3.0-only

import datetime

import pytest

from db import get_session
from db_types import utc_now
from models.publication_stats import PublicationStats, encode_cursor
from tests.admin_fixtures import *  # noqa: F401,F403
from tests.admin_fixtures import ADMIN_EMAIL, basic_auth, login

BASE_TIME = datetime.datetime(2026, 9, 1, 12, 0, 0)


def _seed(rows):
    with get_session() as db:
        db.add_all(PublicationStats(**row) for row in rows)


@pytest.fixture
def seeded():
    # Pairs share a timestamp to exercise the id tie-breaker.
    rows = []
    for n in range(25):
        failed = n % 3 == 0
        rows.append(
            dict(
                platform_name="gmail" if n % 2 else "telegram",
                protocol="sms" if n % 2 else "https",
                status="failed" if failed else "published",
                country_code="CM" if n % 4 else "NG",
                failure_reason="token_expired" if failed else None,
                created_at=BASE_TIME + datetime.timedelta(minutes=n // 2),
            )
        )
    _seed(rows)
    return rows


def _follow(client, url, direction, **kwargs):
    pages = []
    while url:
        response = client.get(url, **kwargs)
        assert response.status_code == 200, response.text
        pages.append(response.json())
        url = pages[-1][direction]
    return pages


def test_public_list_hides_failure_reason(client, seeded):
    response = client.get("/v1/stats/publications")

    assert response.status_code == 200
    items = response.json()["data"]
    assert items
    assert all("failure_reason" not in item for item in items)
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.headers["vary"] == "Authorization, Cookie"


@pytest.mark.parametrize("auth", ["basic", "session"])
def test_admin_list_includes_failure_reason(client, seeded, admin_password, auth):
    headers = {}
    if auth == "basic":
        headers = basic_auth(ADMIN_EMAIL, admin_password)
    else:
        login(client, admin_password)

    response = client.get(
        "/v1/stats/publications", params={"status": "failed"}, headers=headers
    )

    assert response.status_code == 200
    items = response.json()["data"]
    assert items and all(item["failure_reason"] == "token_expired" for item in items)
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "headers",
    [basic_auth(ADMIN_EMAIL, "wrong-password"), {"Authorization": "Bearer abc"}],
    ids=["wrong-password", "bearer"],
)
def test_bad_credentials_are_rejected_not_downgraded(client, seeded, headers):
    response = client.get("/v1/stats/publications", headers=headers)

    assert response.status_code == 401
    assert "data" not in response.json()


def test_invalid_session_cookie_is_rejected_and_cleared(client, seeded):
    response = client.get(
        "/v1/stats/publications", headers={"Cookie": "relaysms_admin_session=bogus"}
    )

    assert response.status_code == 401
    assert "relaysms_admin_session=" in response.headers["set-cookie"]


def test_forward_paging_visits_every_row_once_in_order(client, seeded):
    pages = _follow(client, "/v1/stats/publications?limit=4", "next")

    ids = [item["id"] for page in pages for item in page["data"]]
    assert len(ids) == len(seeded) == len(set(ids))
    keys = [(item["created_at"], item["id"]) for page in pages for item in page["data"]]
    assert keys == sorted(keys, reverse=True)
    assert pages[0]["prev"] is None
    assert pages[-1]["next"] is None


def test_backward_paging_returns_the_same_pages(client, seeded):
    forward = _follow(client, "/v1/stats/publications?limit=4", "next")
    backward = _follow(client, forward[-1]["prev"], "prev")

    as_ids = lambda pages: [[item["id"] for item in p["data"]] for p in pages]
    assert as_ids(reversed(backward)) == as_ids(forward[:-1])
    assert all(page["next"] for page in backward)


def test_links_keep_filters_and_limit(client, seeded):
    url = "/v1/stats/publications?status=failed&platform_name=telegram&limit=2"
    pages = _follow(client, url, "next")

    assert len(pages) > 1
    assert all(len(page["data"]) <= 2 for page in pages)
    assert all(
        item["status"] == "failed" and item["platform_name"] == "telegram"
        for page in pages
        for item in page["data"]
    )
    assert pages[0]["next"].startswith("https://testserver/v1/stats/publications?")


def test_filters_and_time_range(client, seeded):
    response = client.get(
        "/v1/stats/publications",
        params={
            "platform_name": "gmail",
            "protocol": "sms",
            "country_code": "CM",
            "since": "2026-09-01T12:02:00Z",
            "until": "2026-09-01T13:08:00+01:00",
            "limit": 200,
        },
    )

    assert response.status_code == 200
    expected = {
        n
        for n, row in enumerate(seeded, start=1)
        if row["platform_name"] == "gmail"
        and row["protocol"] == "sms"
        and row["country_code"] == "CM"
        and BASE_TIME + datetime.timedelta(minutes=2)
        <= row["created_at"]
        < BASE_TIME + datetime.timedelta(minutes=8)
    }
    assert expected
    assert {item["id"] for item in response.json()["data"]} == expected


@pytest.mark.parametrize(
    "params, status",
    [
        ({"cursor": encode_cursor(BASE_TIME, 1, "next")[:-3] + "!!!"}, 400),
        ({"since": "2026-09-02T00:00:00Z", "until": "2026-09-01T00:00:00Z"}, 400),
    ],
)
def test_invalid_params(client, seeded, params, status):
    assert client.get("/v1/stats/publications", params=params).status_code == status


def test_summary_counts_by_status(client, seeded):
    response = client.get(
        "/v1/stats/publications/summary",
        params={"since": "2026-09-01T00:00:00Z", "until": "2026-09-02T00:00:00Z"},
    )

    assert response.status_code == 200
    body = response.json()
    failed = sum(1 for row in seeded if row["status"] == "failed")
    assert body["total"] == len(seeded)
    assert {g["status"]: g["count"] for g in body["groups"]} == {
        "failed": failed,
        "published": len(seeded) - failed,
    }
    assert body["interval"] is None
    assert all("period" not in group for group in body["groups"])


def test_summary_failure_reason_requires_auth(client, seeded, admin_password):
    params = {
        "group_by": "failure_reason",
        "since": "2026-09-01T00:00:00Z",
        "until": "2026-09-02T00:00:00Z",
    }

    assert (
        client.get("/v1/stats/publications/summary", params=params).status_code == 403
    )

    response = client.get(
        "/v1/stats/publications/summary",
        params=params,
        headers=basic_auth(ADMIN_EMAIL, admin_password),
    )
    assert response.status_code == 200
    assert {g["failure_reason"] for g in response.json()["groups"]} == {
        "token_expired",
        None,
    }


def test_summary_defaults_to_last_30_days(client):
    now = utc_now()
    _seed(
        [
            dict(status="published", created_at=now - datetime.timedelta(days=1)),
            dict(status="published", created_at=now - datetime.timedelta(days=45)),
        ],
    )

    body = client.get("/v1/stats/publications/summary").json()

    assert body["total"] == 1
    since = datetime.datetime.fromisoformat(body["since"])
    until = datetime.datetime.fromisoformat(body["until"])
    assert until - since == datetime.timedelta(days=30)


def test_summary_window_is_capped_for_public_only(client, admin_password):
    _seed(
        [
            dict(status="published", created_at=datetime.datetime(2016, 3, 1)),
            dict(status="published", created_at=datetime.datetime(2026, 3, 1)),
        ]
    )
    params = {"since": "2016-01-01T00:00:00Z", "until": "2026-06-01T00:00:00Z"}
    url = "/v1/stats/publications/summary"

    assert client.get(url, params=params).status_code == 400
    admin = client.get(
        url, params=params, headers=basic_auth(ADMIN_EMAIL, admin_password)
    )
    assert admin.status_code == 200
    assert admin.json()["total"] == 2


def test_summary_interval_buckets_by_week(client):
    _seed(
        [
            dict(status="published", created_at=datetime.datetime(2026, 9, 6, 23)),
            dict(status="published", created_at=datetime.datetime(2026, 9, 7, 1)),
            dict(status="failed", created_at=datetime.datetime(2026, 9, 9, 12)),
            dict(status="published", created_at=datetime.datetime(2026, 9, 13, 9)),
        ]
    )

    response = client.get(
        "/v1/stats/publications/summary",
        params={
            "interval": "week",
            "since": "2026-09-01T00:00:00Z",
            "until": "2026-09-20T00:00:00Z",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["interval"] == "week"
    assert body["total"] == 4
    assert body["groups"] == [
        {"period": "2026-08-31T00:00:00Z", "status": "published", "count": 1},
        {"period": "2026-09-07T00:00:00Z", "status": "published", "count": 2},
        {"period": "2026-09-07T00:00:00Z", "status": "failed", "count": 1},
    ]


def test_summary_interval_with_multiple_group_by(client):
    _seed(
        [
            dict(
                status="published",
                country_code="CM",
                created_at=datetime.datetime(2026, 7, 3),
            ),
            dict(
                status="published",
                country_code="CM",
                created_at=datetime.datetime(2026, 8, 3),
            ),
            dict(
                status="published",
                country_code="NG",
                created_at=datetime.datetime(2026, 8, 4),
            ),
        ]
    )

    response = client.get(
        "/v1/stats/publications/summary",
        params={
            "interval": "month",
            "group_by": ["country_code"],
            "since": "2026-07-01T00:00:00Z",
            "until": "2026-09-01T00:00:00Z",
        },
    )

    groups = response.json()["groups"]
    assert [(g["period"], g["country_code"], g["count"]) for g in groups] == [
        ("2026-07-01T00:00:00Z", "CM", 1),
        ("2026-08-01T00:00:00Z", "CM", 1),
        ("2026-08-01T00:00:00Z", "NG", 1),
    ]
