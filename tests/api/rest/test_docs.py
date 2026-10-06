# SPDX-License-Identifier: GPL-3.0-only

import pytest
from fastapi.testclient import TestClient

from publisher.api.rest import app as app_module
from publisher.api.rest import openapi


@pytest.mark.parametrize("url", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_off_by_default(url):
    assert TestClient(app_module.app).get(url).status_code == 404


def test_committed_spec_is_current():
    committed = openapi.SPEC_FILE.read_text(encoding="utf-8")

    assert committed == openapi.render(), "docs/openapi.json is stale: run make docs"
