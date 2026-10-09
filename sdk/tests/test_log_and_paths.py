# SPDX-License-Identifier: GPL-3.0-only

import io
import json
import logging

import pytest

from relaysms_adapter_sdk import config_dir, log, state_dir
from relaysms_adapter_sdk.paths import CONFIG_DIR_ENV, STATE_DIR_ENV


@pytest.fixture
def stream():
    stream = io.StringIO()
    yield stream
    logging.basicConfig(force=True)


def lines(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


class TestLog:
    def test_json_lines(self, stream, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "debug")
        log.configure(stream)
        logging.getLogger("adapter").debug("hello %s", "there")
        (line,) = stream.getvalue().splitlines()
        assert log.parse(line) == {
            "level": "DEBUG",
            "logger": "adapter",
            "message": "hello there",
        }

    def test_traceback(self, stream):
        log.configure(stream)
        try:
            raise ValueError("bad")
        except ValueError:
            logging.getLogger("adapter").exception("failed")
        (entry,) = lines(stream)
        assert entry["level"] == "ERROR"
        assert "ValueError: bad" in entry["traceback"]

    def test_unknown_level(self, stream, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "loud")
        log.configure(stream)
        logging.getLogger("adapter").debug("hidden")
        (entry,) = lines(stream)
        assert entry["level"] == "WARNING"
        assert "LOUD" in entry["message"]


@pytest.mark.parametrize("line", ["not json", "[1]", '{"level": "INFO"}'])
def test_parse_ignores_other_lines(line):
    assert log.parse(line) is None


class TestPaths:
    def test_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path / "config"))
        monkeypatch.setenv(STATE_DIR_ENV, str(tmp_path / "state"))
        assert config_dir() == tmp_path / "config"
        assert state_dir() == tmp_path / "state"
        assert (tmp_path / "state").is_dir()

    def test_unset(self, monkeypatch):
        monkeypatch.delenv(CONFIG_DIR_ENV, raising=False)
        with pytest.raises(RuntimeError, match=CONFIG_DIR_ENV):
            config_dir()
