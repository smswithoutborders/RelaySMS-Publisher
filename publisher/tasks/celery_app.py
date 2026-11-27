# SPDX-License-Identifier: GPL-3.0-only

import logging
import os
import sys
from pathlib import Path
from typing import Any

from celery import Celery
from celery.schedules import crontab

from publisher.config import CeleryConfig

_UNDER_JOURNALD = bool(os.getenv("JOURNAL_STREAM")) and not sys.stderr.isatty()
_WORKER_LOG_FORMAT = (
    "%(levelname)s - %(processName)s - %(message)s"
    if _UNDER_JOURNALD
    else "%(asctime)s - %(levelname)s - %(processName)s - %(message)s"
)
_WORKER_TASK_LOG_FORMAT = (
    "%(levelname)s - %(processName)s - %(task_name)s[%(task_id)s] - %(message)s"
    if _UNDER_JOURNALD
    else "%(asctime)s - %(levelname)s - %(processName)s - "
    "%(task_name)s[%(task_id)s] - %(message)s"
)


def _drop_task_arguments(record: logging.LogRecord) -> bool:
    # Celery attaches the task arguments, such as the payload and sender hash, to
    # these records as a `data` extra.
    record.__dict__.pop("data", None)
    return True


for _name in ("celery.worker.strategy", "celery.app.trace"):
    logging.getLogger(_name).addFilter(_drop_task_arguments)


def _ensure_db_dir(path: str) -> None:
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _broker_settings(celery: CeleryConfig) -> dict[str, Any]:
    if celery.broker_type == "redis":
        return {"broker_url": celery.redis_url, "result_backend": celery.redis_url}
    if celery.broker_type == "rabbitmq":
        return {"broker_url": celery.rabbitmq_url}
    _ensure_db_dir(celery.broker_db_path)
    _ensure_db_dir(celery.result_db_path)
    return {
        "broker_url": f"sqlite:///{celery.broker_db_path}",
        "broker_transport": "publisher.tasks.broker:Transport",
        "broker_transport_options": {"hide_parameters": True},
        "result_backend": f"db+sqlite:///{celery.result_db_path}",
    }


def _parse_cron(name: str, expression: str) -> crontab:
    try:
        return crontab.from_string(expression)
    except ValueError as e:
        raise ValueError(f"Invalid {name} {expression!r}: {e}") from None


def make_celery() -> Celery:
    celery = CeleryConfig.get()
    _ensure_db_dir(celery.beat_schedule_path)

    cleanup_schedule = _parse_cron("CELERY_CLEANUP_CRON", celery.cleanup_cron)
    token_cleanup_schedule = _parse_cron(
        "CELERY_TOKEN_CLEANUP_CRON", celery.token_cleanup_cron
    )

    beat_schedule = {
        "cleanup-stale-payload-sessions": {
            "task": "tasks.cleanup_task.cleanup_stale_payload_sessions",
            "schedule": cleanup_schedule,
        },
        "cleanup-idle-tokens": {
            "task": "tasks.cleanup_task.cleanup_idle_tokens",
            "schedule": token_cleanup_schedule,
        },
        "cleanup-expired-credential-sessions": {
            "task": "tasks.cleanup_task.cleanup_expired_credential_sessions",
            "schedule": cleanup_schedule,
        },
        "cleanup-old-audit-events": {
            "task": "tasks.cleanup_task.cleanup_old_audit_events",
            "schedule": cleanup_schedule,
        },
        "cleanup-adapter-jobs": {
            "task": "tasks.cleanup_task.cleanup_adapter_jobs",
            "schedule": cleanup_schedule,
        },
    }
    if celery.worker_heartbeat_url:
        beat_schedule["worker-heartbeat"] = {
            "task": "tasks.heartbeat_task.ping_worker_heartbeat",
            "schedule": 60.0,
        }

    app = Celery(
        "relaysms_publisher",
        include=[
            "publisher.tasks.publication_task",
            "publisher.tasks.cleanup_task",
            "publisher.tasks.heartbeat_task",
            "publisher.tasks.platform_task",
        ],
    )
    app.conf.update(
        **_broker_settings(celery),
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        worker_enable_remote_control=False,
        worker_concurrency=celery.worker_concurrency,
        worker_hijack_root_logger=False,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_ignore_result=True,
        worker_log_format=_WORKER_LOG_FORMAT,
        worker_task_log_format=_WORKER_TASK_LOG_FORMAT,
        beat_schedule_filename=celery.beat_schedule_path,
        beat_schedule=beat_schedule,
    )
    return app


celery_app = make_celery()
