# SPDX-License-Identifier: GPL-3.0-only

import os
import stat
import subprocess

import pytest


@pytest.fixture
def build(install, tmp_path):
    """Run build-book.sh with stub curl and uname that download nothing."""
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


@pytest.fixture
def cached_tools(install):
    """Cached mdbook and mdbook-mermaid, whose stub writes a bundled mermaid.min.js."""
    tools = install / ".mdbook"
    for tool, version, body in (
        ("mdbook", "0.5.3", ""),
        ("mdbook-mermaid", "0.17.1", 'echo bundled >"$2/mermaid.min.js"'),
    ):
        exe = tools / f"{tool}-{version}" / tool
        exe.parent.mkdir(parents=True)
        exe.write_text(f"#!/usr/bin/env bash\n{body}\n")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return tools


class TestBuildBook:
    def test_refuses_an_mdbook_download_that_fails_its_checksum(self, install, build):
        result = build("x86_64")
        assert result.returncode != 0
        assert "mdbook v0.5.3 download doesn't match its sha256" in result.stderr
        assert not (install / ".mdbook" / "mdbook-0.5.3" / "mdbook").exists()

    def test_refuses_a_mermaid_download_that_fails_its_checksum(
        self, cached_tools, build
    ):
        result = build("x86_64")

        assert result.returncode != 0
        assert "mermaid.min.js v12.2.0 download doesn't match" in result.stderr
        assert not list(cached_tools.glob("mermaid-12.2.0.min.js*"))

    def test_uses_the_cached_pinned_mermaid_over_the_bundled_one(
        self, install, cached_tools, build
    ):
        (cached_tools / "mermaid-12.2.0.min.js").write_text("pinned\n")

        result = build("x86_64")

        assert result.returncode == 0, result.stderr
        assert (install / "mermaid.min.js").read_text() == "pinned\n"

    def test_refuses_an_architecture_without_a_release(self, tmp_path, build):
        result = build("riscv64")
        assert result.returncode != 0
        assert "No mdbook release for riscv64" in result.stderr
        assert not (tmp_path / "curl-called").exists()
