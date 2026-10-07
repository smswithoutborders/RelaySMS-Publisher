# SPDX-License-Identifier: GPL-3.0-only

import os
import shutil
import subprocess

import pytest

from tests.scripts import REPO


@pytest.fixture
def install(tmp_path):
    """An install directory with the scripts, unit templates and template.env."""
    root = tmp_path / "relaysms-publisher"
    shutil.copytree(REPO / "scripts", root / "scripts")
    shutil.copytree(REPO / "deploy" / "systemd", root / "deploy" / "systemd")
    shutil.copy(REPO / "template.env", root)
    (root / ".env").touch()
    return root


@pytest.fixture
def bash(install):
    """Run bash code in the install directory with lib.sh sourced, as the scripts do."""

    def run(code: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", f"set -Eeuo pipefail; source scripts/lib.sh; {code}"],
            cwd=install,
            env={**os.environ, "NO_COLOR": "1", "INSTALL_DIR": str(install), **env},
            capture_output=True,
            text=True,
            check=False,
        )

    return run
