# SPDX-License-Identifier: GPL-3.0-only

import os
from pathlib import Path

from celery import Celery
from celery.schedules import crontab

from utils import get_configs

_UNDER_JOURNALD = bool(os.getenv("JOURNAL_STREAM"))
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


def _ensure_db_dir(path: str) -> None:
    Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def _sqlite_urls() -> tuple[str, str]:
    broker_path = get_configs(
        "CELERY_BROKER_DB_PATH", default_value="data/celery_broker.db"
    )
    result_path = get_configs(
        "CELERY_RESULT_DB_PATH", default_value="data/celery_results.db"
    )
    _ensure_db_dir(broker_path)
    _ensure_db_dir(result_path)
    return f"sqla+sqlite:///{broker_path}", f"db+sqlite:///{result_path}"


def _redis_urls() -> tuple[str, str]:
    url = get_configs("CELERY_REDIS_URL", default_value="redis://localhost:6379/0")
    return url, url


def _rabbitmq_urls() -> tuple[str, str | None]:
    broker = get_configs(
        "CELERY_RABBITMQ_URL", default_value="amqp://guest:guest@localhost:5672//"
    )
    return broker, None


_BROKER_BUILDERS = {
    "sqlite": _sqlite_urls,
    "redis": _redis_urls,
    "rabbitmq": _rabbitmq_urls,
}
_DEFAULT_CONCURRENCY = {"sqlite": 1, "redis": 4, "rabbitmq": 4}


def make_celery() -> Celery:
    """Create and configure the Celery application."""
    broker_type = get_configs("CELERY_BROKER_TYPE", default_value="sqlite").lower()
    try:
        build_urls = _BROKER_BUILDERS[broker_type]
    except KeyError:
        raise ValueError(
            f"Unknown CELERY_BROKER_TYPE '{broker_type}'. "
            f"Choose one of: {', '.join(_BROKER_BUILDERS)}"
        ) from None

    broker_url, result_backend = build_urls()
    concurrency = int(
        get_configs(
            "CELERY_WORKER_CONCURRENCY",
            default_value=str(_DEFAULT_CONCURRENCY[broker_type]),
        )
    )
    schedule_path = get_configs(
        "CELERY_BEAT_SCHEDULE_PATH", default_value="data/celerybeat-schedule"
    )
    _ensure_db_dir(schedule_path)

    cleanup_cron = get_configs("CELERY_CLEANUP_CRON", default_value="0 */3 * * *")
    try:
        cleanup_schedule = crontab.from_string(cleanup_cron)
    except ValueError as e:
        raise ValueError(f"Invalid CELERY_CLEANUP_CRON '{cleanup_cron}': {e}") from None

    app = Celery(
        "relaysms_publisher", include=["tasks.publication_task", "tasks.cleanup_task"]
    )
    app.conf.update(
        broker_url=broker_url,
        result_backend=result_backend,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        worker_enable_remote_control=False,
        worker_concurrency=concurrency,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_ignore_result=True,
        worker_log_format=_WORKER_LOG_FORMAT,
        worker_task_log_format=_WORKER_TASK_LOG_FORMAT,
        beat_schedule_filename=schedule_path,
        beat_schedule={
            "cleanup-stale-payload-sessions": {
                "task": "tasks.cleanup_task.cleanup_stale_payload_sessions",
                "schedule": cleanup_schedule,
            },
        },
    )
    return app


celery_app = make_celery()
