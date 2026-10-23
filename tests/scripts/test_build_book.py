# SPDX-License-Identifier: GPL-3.0-only

import os
import stat
import subprocess

import pytest


@pytest.fixture
def build(install, tmp_path):
    """Run build-book.sh with stub curl and uname, so nothing is downloaded."""
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, body in {
        # Called as: curl -fsSL -o FILE URL
        "curl": 'touch "$CURL_CALLED"; echo junk >"$3"',
        "uname": 'echo "$ARCH"',
    }.items():
        stub = stubs / name
        stub.write_text(f"#!/usr/bin/env bash\n{body}\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    def run(arch: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "scripts/build-book.sh"],
            cwd=install,
            env={
                **os.environ,
                "NO_COLOR": "1",
                "PATH": f"{stubs}:{os.environ['PATH']}",
                "ARCH": arch,
                "CURL_CALLED": str(tmp_path / "curl-called"),
            },
            capture_output=True,
            text=True,
            check=False,
        )

    return run


class TestBuildBook:
    def test_refuses_a_download_that_fails_its_checksum(self, install, build):
        result = build("x86_64")
        assert result.returncode != 0
        assert "doesn't match its sha256" in result.stderr
        assert not (install / ".mdbook" / "mdbook-0.5.3" / "mdbook").exists()

    def test_refuses_an_architecture_without_a_release(self, tmp_path, build):
        result = build("riscv64")
        assert result.returncode != 0
        assert "No mdbook release for riscv64" in result.stderr
        assert not (tmp_path / "curl-called").exists()
