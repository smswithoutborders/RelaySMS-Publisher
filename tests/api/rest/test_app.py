# SPDX-License-Identifier: GPL-3.0-only

import logging

import pytest
from fastapi import HTTPException

import publisher.api.rest.app  # noqa: F401  (adds the access log filter)


def access_record(path, status):
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:50000", "GET", path, "1.1", status),
        None,
    )


@pytest.mark.parametrize(
    ("path", "status", "logged"),
    [("/health", 200, False), ("/health", 500, True), ("/v1/platforms", 200, True)],
)
def test_access_log_leaves_out_only_passing_health_checks(path, status, logged):
    access_log = logging.getLogger("uvicorn.access")

    assert bool(access_log.filter(access_record(path, status))) is logged


@pytest.mark.parametrize(
    ("status", "level"), [(404, logging.WARNING), (500, logging.ERROR)]
)
def test_http_errors_log_4xx_as_warnings_and_5xx_as_errors(
    app, client, caplog, status, level
):
    @app.get("/fail")
    def fail():
        raise HTTPException(status_code=status, detail="nope")

    assert client.get("/fail").status_code == status

    [record] = [
        r for r in caplog.records if r.getMessage().startswith("request: /fail")
    ]
    assert record.levelno == level


@pytest.mark.parametrize(
    ("params", "status"), [({"cursor": "bad"}, 400), ({"limit": "x"}, 422)]
)
@pytest.mark.usefixtures("test_db", "fast_hasher")
def test_invalid_requests_log_as_warnings(client, admin, caplog, params, status):
    response = client.get("/v1/stats/publications", params=params, headers=admin)

    assert response.status_code == status
    [record] = [r for r in caplog.records if r.getMessage().startswith("request: ")]
    assert record.levelno == logging.WARNING
