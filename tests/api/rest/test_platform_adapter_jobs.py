# SPDX-License-Identifier: GPL-3.0-only

import pytest

from publisher import db
from publisher.models import platform_adapter_job as jobs
from publisher.models.platform_adapter import OAUTH2
from publisher.platforms import manager
from publisher.tasks import platform_task
from tests.helpers import (
    USERNAME,
    adapter_repo,
    add_adapter,
    basic_auth,
    commit_manifest,
    create_credential,
)

URL = "/v1/platforms/adapters"

pytestmark = pytest.mark.usefixtures(
    "test_db", "fast_hasher", "platforms_config", "fake_adapter_build"
)


@pytest.fixture(autouse=True)
def worker(monkeypatch):
    """Runs queued jobs inline, and treats local repos as allowed GitHub repos."""
    monkeypatch.setattr(
        platform_task.run_adapter_job, "delay", platform_task.run_adapter_job
    )
    monkeypatch.setattr(manager, "is_allowed_github_url", lambda url: "/" in url)


@pytest.fixture
def repo(tmp_path):
    return adapter_repo(tmp_path / "src" / "mastodon", "mastodon", OAUTH2)


def _install(client, headers, repo, **body):
    return client.post(
        URL, json={"source_url": str(repo.working_tree_dir), **body}, headers=headers
    )


def test_installs_need_an_administrator(client, repo):
    writer = basic_auth(
        "writer",
        create_credential("writer", ["platforms:read", "platforms:write"]),
    )

    response = _install(client, writer, repo)

    assert response.status_code == 403
    assert "administrator" in response.json()["error"]


def test_only_allowed_repos_install(client, admin, monkeypatch):
    monkeypatch.setattr(manager, "is_allowed_github_url", lambda url: False)

    response = client.post(
        URL, json={"source_url": "https://example.org/x/y"}, headers=admin
    )

    assert response.status_code == 400
    assert "PLATFORMS_GITHUB_ORGS" in response.json()["error"]


def test_install_runs_as_a_job(client, admin, repo):
    response = _install(client, admin, repo)

    assert response.status_code == 202
    job = client.get(response.headers["location"], headers=admin).json()
    assert (job["action"], job["state"], job["tag"]) == (
        "install",
        "succeeded",
        "v1.0.0",
    )
    [adapter] = client.get(URL, headers=admin).json()
    assert (adapter["name"], adapter["tag"]) == ("mastodon", "v1.0.0")
    assert adapter["created_by"] == USERNAME
    assert _install(client, admin, repo).status_code == 409


def test_update_runs_as_a_job_and_is_listed(client, admin, repo):
    adapter_id = _install(client, admin, repo).json()["adapter_id"]
    commit_manifest(repo, "mastodon", OAUTH2, tag="v1.1.0")

    response = client.post(f"{URL}/{adapter_id}/update", json={}, headers=admin)

    assert response.status_code == 202
    history = client.get(f"{URL}/{adapter_id}/jobs", headers=admin).json()
    assert [(j["action"], j["state"], j["tag"]) for j in history] == [
        ("update", "succeeded", "v1.1.0"),
        ("install", "succeeded", "v1.0.0"),
    ]


def test_a_failed_job_keeps_its_reason(client, admin, tmp_path):
    untagged = adapter_repo(tmp_path / "src" / "plain", "plain", OAUTH2, tag=None)

    response = _install(client, admin, untagged)

    job = client.get(response.headers["location"], headers=admin).json()
    assert job["state"] == "failed"
    assert "no version tags" in job["log"]
    assert client.get(URL, headers=admin).json() == []


def test_one_job_per_adapter_at_a_time(client, admin):
    adapter = add_adapter("gmail", OAUTH2)
    with db.get_session() as session:
        jobs.create(session, adapter_id=adapter.id, action="update", source_url="x")

    response = client.post(f"{URL}/{adapter.id}/update", json={}, headers=admin)

    assert response.status_code == 409
    assert "is running" in response.json()["error"]


def test_an_unavailable_queue_fails_the_job_at_once(client, admin, monkeypatch):
    adapter = add_adapter("gmail", OAUTH2)

    def unavailable(job_id):
        raise ConnectionError("broker down")

    monkeypatch.setattr(platform_task.run_adapter_job, "delay", unavailable)
    response = client.post(f"{URL}/{adapter.id}/update", json={}, headers=admin)

    assert response.status_code == 503
    [job] = client.get(f"{URL}/{adapter.id}/jobs", headers=admin).json()
    assert (job["state"], job["log"]) == ("failed", "Queueing failed: broker down")


def test_jobs_need_platforms_write(client):
    reader = basic_auth("reader", create_credential("reader", ["platforms:read"]))

    response = client.get(f"{URL}/gmail-0/jobs", headers=reader)

    assert response.status_code == 403
