# SPDX-License-Identifier: GPL-3.0-only
"""The JSON-over-stdio contract with adapter processes, using a real subprocess."""

import logging
import sys
from types import SimpleNamespace

import pytest

from publisher.platforms import ipc

ADAPTER = """
import json, sys

request = json.load(sys.stdin)
method, params = request["method"], request["params"]
if method == "echo":
    print(json.dumps({"result": params}))
elif method == "reject":
    print(json.dumps({"error": "rejected"}))
elif method == "crash":
    print("boom", file=sys.stderr)
    sys.exit(3)
elif method == "garbage":
    print("not json")
elif method == "warn":
    print("2026-01-01 00:00:00,000 - adapter - WARNING - careful", file=sys.stderr)
    print(json.dumps({"result": True}))
"""


@pytest.fixture
def adapter(tmp_path):
    """Paths to an adapter whose venv python is this interpreter."""
    (tmp_path / "adapter").mkdir()
    (tmp_path / "adapter" / "main.py").write_text(ADAPTER)
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    (tmp_path / "venv" / "bin" / "python3").symlink_to(sys.executable)
    return SimpleNamespace(path=str(tmp_path / "adapter"), venv=str(tmp_path / "venv"))


def test_params_reach_the_adapter_and_its_result_comes_back(adapter):
    assert ipc.invoke(adapter.path, adapter.venv, "echo", {"to": "a@b.c"}) == {
        "result": {"to": "a@b.c"},
        "error": None,
    }


def test_adapter_errors_are_passed_through(adapter):
    assert ipc.invoke(adapter.path, adapter.venv, "reject") == {
        "result": None,
        "error": "rejected",
    }


def test_a_crashing_adapter_raises_with_its_stderr(adapter):
    with pytest.raises(RuntimeError, match="boom"):
        ipc.invoke(adapter.path, adapter.venv, "crash")


def test_output_that_is_not_json_becomes_an_error(adapter):
    assert (
        ipc.invoke(adapter.path, adapter.venv, "garbage")["error"]
        == "Invalid JSON response payload."
    )


def test_adapter_log_lines_keep_their_severity(adapter, caplog):
    caplog.set_level(logging.DEBUG, logger=ipc.__name__)

    ipc.invoke(adapter.path, adapter.venv, "warn")

    [record] = [r for r in caplog.records if "careful" in r.getMessage()]
    assert record.levelno == logging.WARNING


def test_an_adapter_without_main_py_is_rejected(adapter, tmp_path):
    (tmp_path / "adapter" / "main.py").unlink()

    with pytest.raises(FileNotFoundError, match="entry point"):
        ipc.invoke(adapter.path, adapter.venv, "echo")
