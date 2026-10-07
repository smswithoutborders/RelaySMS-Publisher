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


def test_every_error_response_documents_the_error_body():
    spec = app_module.app.openapi()

    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            for status, response in operation["responses"].items():
                if not status.startswith(("4", "5")):
                    continue
                schema = response["content"]["application/json"]["schema"]
                assert schema == {"$ref": "#/components/schemas/ErrorResponse"}, (
                    f"{method.upper()} {path} {status}: add it with error_responses()"
                )
