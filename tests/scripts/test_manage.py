# SPDX-License-Identifier: GPL-3.0-only

import os
import shutil
import subprocess

import pytest

from tests.scripts import REPO


@pytest.fixture
def logs(install, tmp_path):
    """Run `manage.sh logs` in the install directory, with journalctl faked."""
    shutil.copy(REPO / "manage.sh", install)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    journalctl = bin_dir / "journalctl"
    journalctl.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n')
    journalctl.chmod(0o755)

    def run(*args: str, instance: str = "") -> subprocess.CompletedProcess[str]:
        if instance:
            (install / ".instance-name").write_text(instance)
        return subprocess.run(
            ["bash", "manage.sh", "logs", "--no-follow", *args],
            cwd=install,
            env={
                **os.environ,
                "NO_COLOR": "1",
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
            },
            capture_output=True,
            text=True,
            check=False,
        )

    return run


def journal_units(result: subprocess.CompletedProcess[str]) -> list[str]:
    assert result.returncode == 0, result.stderr
    args = result.stdout.splitlines()
    return [args[i + 1] for i, arg in enumerate(args) if arg == "-u"]


class TestLogsUnit:
    def test_short_name_selects_the_unit(self, logs):
        assert journal_units(logs("--unit", "rest")) == [
            "relaysms-publisher-rest.service"
        ]

    def test_short_name_selects_the_named_instance_unit(self, logs):
        result = logs("--unit", "rest", "-u", "worker", "--unit=beat", instance="acme")

        assert journal_units(result) == [
            "relaysms-publisher-acme-rest.service",
            "relaysms-publisher-acme-worker.service",
            "relaysms-publisher-acme-beat.service",
        ]

    def test_full_name_selects_the_named_instance_unit(self, logs):
        result = logs("--unit=relaysms-publisher-acme-grpc.service", instance="acme")

        assert journal_units(result) == ["relaysms-publisher-acme-grpc.service"]

    def test_unknown_name_on_a_named_instance_fails(self, logs):
        result = logs("--unit", "nope", instance="acme")

        assert result.returncode != 0
        assert "Unknown service unit: nope" in result.stderr

    def test_unit_of_another_instance_fails(self, logs):
        result = logs("--unit", "relaysms-publisher-rest.service", instance="acme")

        assert result.returncode != 0
        assert "Unknown service unit: relaysms-publisher-rest.service" in result.stderr
