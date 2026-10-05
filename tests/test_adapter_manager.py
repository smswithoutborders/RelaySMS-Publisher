# SPDX-License-Identifier: GPL-3.0-only

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
