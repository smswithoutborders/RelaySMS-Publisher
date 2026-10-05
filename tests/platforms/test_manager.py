# SPDX-License-Identifier: GPL-3.0-only

import os
import time

import msgspec
import pytest

from publisher.platforms import manager


@pytest.fixture(autouse=True)
def allowed_orgs(set_config):
    set_config(manager, "platforms_config", github_orgs=["smswithoutborders"])


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/smswithoutborders/gmail-oauth2-adapter",
        "https://github.com/SMSWithoutBorders/gmail-oauth2-adapter.git",
        "https://github.com/smswithoutborders/gmail-oauth2-adapter/",
    ],
)
def test_allowed_github_urls(url):
    assert manager.is_allowed_github_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/someone-else/gmail-oauth2-adapter",
        "http://github.com/smswithoutborders/gmail-oauth2-adapter",
        "https://gitlab.com/smswithoutborders/gmail-oauth2-adapter",
        "https://github.com.evil.example/smswithoutborders/repo",
        "https://user@github.com/smswithoutborders/repo",
        "https://github.com:8443/smswithoutborders/repo",
        "https://github.com/smswithoutborders/repo/tree/main",
        "https://github.com/smswithoutborders/..",
        "https://github.com/smswithoutborders/repo?ref=x",
        "git@github.com:smswithoutborders/repo.git",
        "file:///etc/passwd",
    ],
)
def test_rejected_github_urls(url):
    assert not manager.is_allowed_github_url(url)


def test_empty_allowlist_rejects_everything(set_config):
    set_config(manager, "platforms_config", github_orgs=[])

    assert not manager.is_allowed_github_url(
        "https://github.com/smswithoutborders/gmail-oauth2-adapter"
    )


def _manifest(name, proto_id):
    return manager.PlatformManifest(
        id=f"{name}-{proto_id}",
        display_name=name.title(),
        name=name,
        path=f"/adapters/{name}",
        venv_path=f"/venvs/{name}",
        assets_path=f"/assets/{name}",
        cat_id=0,
        proto_id=proto_id,
    )


@pytest.fixture
def registry(tmp_path):
    path = tmp_path / "registry.json"
    adapters = [_manifest("gmail", 0), _manifest("telegram", 1)]
    path.write_bytes(msgspec.json.encode({a.id: a for a in adapters}))
    return path


def test_adapters_resolve_by_platform_and_protocol(registry):
    adapters = manager.AdapterManager(registry_file=registry)

    assert adapters.get_oauth2_adapter("Gmail").name == "gmail"
    assert adapters.get_pnba_adapter("telegram").name == "telegram"


@pytest.mark.parametrize(
    "lookup, platform",
    [("get_pnba_adapter", "gmail"), ("get_oauth2_adapter", "unknown")],
)
def test_platform_without_a_matching_adapter_is_unimplemented(
    registry, lookup, platform
):
    adapters = manager.AdapterManager(registry_file=registry)

    with pytest.raises(NotImplementedError):
        getattr(adapters, lookup)(platform)


def test_registry_edits_are_picked_up_without_a_restart(registry):
    adapters = manager.AdapterManager(registry_file=registry)
    assert [a.name for a in adapters.list_adapters()] == ["gmail", "telegram"]

    registry.write_bytes(msgspec.json.encode({"x": _manifest("mastodon", 0)}))
    os.utime(registry, (time.time() + 10, time.time() + 10))

    assert [a.name for a in adapters.list_adapters()] == ["mastodon"]


def test_missing_registry_means_no_adapters(tmp_path):
    adapters = manager.AdapterManager(registry_file=tmp_path / "absent.json")

    assert adapters.list_adapters() == []
