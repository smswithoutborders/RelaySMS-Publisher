# SPDX-License-Identifier: GPL-3.0-only

import pytest
from fastapi.testclient import TestClient

import app as app_module


@pytest.mark.parametrize("url", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_off_by_default(url):
    assert TestClient(app_module.app).get(url).status_code == 404
