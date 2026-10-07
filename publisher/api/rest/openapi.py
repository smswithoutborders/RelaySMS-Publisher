# SPDX-License-Identifier: GPL-3.0-only
"""Writes the REST API's OpenAPI spec to docs/openapi.json, the committed reference."""

import json
from pathlib import Path

from publisher.api.rest.app import app

SPEC_FILE = Path(__file__).resolve().parents[3] / "docs" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    SPEC_FILE.write_text(render(), encoding="utf-8")
    print(f"Wrote {SPEC_FILE}")
