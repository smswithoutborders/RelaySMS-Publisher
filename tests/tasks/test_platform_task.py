# SPDX-License-Identifier: GPL-3.0-only

import datetime

import pytest

from publisher import db
from publisher.models import platform_adapter_job as jobs
from publisher.models.platform_adapter_job import PlatformAdapterJob
from publisher.tasks import cleanup_task, platform_task

pytestmark = pytest.mark.usefixtures("test_db", "platforms_config")

LONG_AGO = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=400)


def _job(adapter_id="gmail-0"):
    with db.get_session() as session:
        return jobs.create(
            session, adapter_id=adapter_id, action="update", source_url="/nowhere"
        ).id


def _get(job_id):
    with db.get_session() as session:
        return session.get(PlatformAdapterJob, job_id)


def test_a_job_runs_once():
    job_id = _job()

    platform_task.run_adapter_job(str(job_id))
    finished = _get(job_id)
    platform_task.run_adapter_job(str(job_id))

    assert finished.state == "failed"
    assert "removed" in finished.log
    assert finished.lock is None
    assert _get(job_id).finished_at == finished.finished_at


def test_cleanup_fails_abandoned_jobs_and_deletes_old_ones():
    abandoned, old = _job("gmail-0"), _job("telegram-1")
    platform_task.run_adapter_job(str(old))
    with db.get_session() as session:
        session.get(PlatformAdapterJob, abandoned).created_at = LONG_AGO
        session.get(PlatformAdapterJob, old).finished_at = LONG_AGO

    cleanup_task.cleanup_adapter_jobs()

    assert _get(old) is None
    job = _get(abandoned)
    assert (job.state, job.lock) == ("failed", None)
    assert "Abandoned" in job.log
