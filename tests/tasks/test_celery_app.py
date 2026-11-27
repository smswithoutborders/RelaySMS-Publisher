# SPDX-License-Identifier: GPL-3.0-only

import logging
from contextlib import contextmanager

import pytest
from kombu.transport import sqlalchemy

from publisher.tasks import broker, celery_app


@pytest.mark.parametrize("name", ["celery.worker.strategy", "celery.app.trace"])
def test_the_task_arguments_extra_is_dropped(caplog, name):
    caplog.set_level(logging.INFO, logger=name)

    logging.getLogger(name).info("Task received", extra={"data": {"args": "payload"}})

    [record] = caplog.records
    assert not hasattr(record, "data")


def test_the_sqlite_broker_uses_the_publisher_transport():
    app = celery_app.celery_app

    with app.connection_for_read() as conn:
        assert isinstance(conn.transport, broker.Transport)
        assert conn.hostname == app.conf.broker_url


def test_the_sqlite_broker_leaves_query_parameters_out_of_errors():
    with celery_app.celery_app.connection_for_read() as conn:
        channel = conn.channel()
        assert channel._engine_from_config().hide_parameters


def test_broker_polls_run_with_instrumentation_suppressed(monkeypatch):
    calls = []

    @contextmanager
    def suppress():
        calls.append("enter")
        yield
        calls.append("exit")

    monkeypatch.setattr(broker, "suppress_instrumentation", suppress)
    monkeypatch.setattr(
        sqlalchemy.Channel, "_get", lambda self, queue: calls.append(f"get {queue}")
    )

    broker.Channel._get(object.__new__(broker.Channel), "celery")

    assert calls == ["enter", "get celery", "exit"]
