# SPDX-License-Identifier: GPL-3.0-only

import logging

import pytest

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
