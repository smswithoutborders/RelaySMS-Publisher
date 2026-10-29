# SPDX-License-Identifier: GPL-3.0-only

import io
import json
import logging

import pytest

from relaysms_adapter_sdk import config_dir, log, read_config, state_dir, write_config
from relaysms_adapter_sdk.paths import CONFIG_DIR_ENV, STATE_DIR_ENV


@pytest.fixture
def stream():
    stream = io.StringIO()
    yield stream
    logging.basicConfig(force=True)
    for name in ("relaysms_adapter_sdk", "adapter"):
        logging.getLogger(name).setLevel(logging.NOTSET)


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

    @pytest.mark.parametrize(
        ("level", "shown"),
        [("info", ["own", "warning"]), ("debug", ["own", "routine", "warning"])],
    )
    def test_other_libraries_send_only_warnings_unless_debugging(
        self, stream, monkeypatch, level, shown
    ):
        monkeypatch.setenv("LOG_LEVEL", level)
        log.configure(stream, package="adapter")
        logging.getLogger("adapter.client").info("own")
        logging.getLogger("library").info("routine")
        logging.getLogger("library").warning("warning")
        assert [entry["message"] for entry in lines(stream)] == shown

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

    def test_config_keys_are_read_in_lowercase(self, tmp_path, monkeypatch):
        monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
        (tmp_path / "credentials.json").write_text(
            '{"SMTP_HOST": "h", "web": {"Client_ID": "c"}}'
        )
        assert read_config() == {"smtp_host": "h", "web": {"client_id": "c"}}

    @pytest.mark.parametrize(
        ("content", "error"),
        [
            ('{"SMTP_HOST": "a", "smtp_host": "b"}', "set twice"),
            ("[]", "JSON object"),
            ("{", "invalid"),
        ],
    )
    def test_invalid_config(self, tmp_path, monkeypatch, content, error):
        monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
        (tmp_path / "credentials.json").write_text(content)
        with pytest.raises(ValueError, match=error):
            read_config()

    def test_write_config_replaces_the_file_for_its_owner_only(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path / "config"))
        write_config({"a": 1})
        path = write_config({"b": 2})

        assert read_config() == {"b": 2}
        assert path.stat().st_mode & 0o777 == 0o600
        assert (tmp_path / "config").stat().st_mode & 0o777 == 0o700
        assert [p.name for p in (tmp_path / "config").iterdir()] == ["credentials.json"]

    def test_config_dir_needs_its_env_var(self, monkeypatch):
        monkeypatch.delenv(CONFIG_DIR_ENV, raising=False)
        with pytest.raises(RuntimeError, match=CONFIG_DIR_ENV):
            config_dir()
