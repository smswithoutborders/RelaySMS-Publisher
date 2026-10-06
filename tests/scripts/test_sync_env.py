# SPDX-License-Identifier: GPL-3.0-only

import pytest

from tests.scripts import REPO

TEMPLATE = """\
# Server
HOST=127.0.0.1
PORT=16000

# Database
DATABASE_DIALECT=sqlite
"""


@pytest.fixture
def sync(install, bash):
    """Sync install/.env from a small template."""
    (install / "template.env").write_text(TEMPLATE)
    return lambda: bash(f'bash "{REPO}/sync-env.sh" .env template.env')


class TestSyncEnv:
    def test_adds_missing_vars_after_their_neighbours(self, install, sync):
        env = install / ".env"
        env.write_text("# Server\nHOST=0.0.0.0\n\n# Database\nDATABASE_DIALECT=mysql\n")

        assert sync().returncode == 0

        assert env.read_text() == (
            "# Server\nHOST=0.0.0.0\nPORT=16000\n\n# Database\nDATABASE_DIALECT=mysql\n"
        )

    def test_missing_section_is_appended_as_a_block(self, install, sync):
        env = install / ".env"
        env.write_text("# Server\nHOST=0.0.0.0\nPORT=1\n")

        sync()

        assert env.read_text() == (
            "# Server\nHOST=0.0.0.0\nPORT=1\n\n# Database\nDATABASE_DIALECT=sqlite\n"
        )

    def test_backs_up_the_previous_file(self, install, sync):
        (install / ".env").write_text("HOST=0.0.0.0\n")

        sync()

        assert (install / ".env.bak").read_text() == "HOST=0.0.0.0\n"

    def test_complete_env_is_left_untouched(self, install, sync):
        (install / ".env").write_text(TEMPLATE)

        assert "Nothing to add" in sync().stdout

        assert (install / ".env").read_text() == TEMPLATE
        assert not (install / ".env.bak").exists()

    def test_creates_missing_env(self, install, sync):
        (install / ".env").unlink()

        sync()

        assert "DATABASE_DIALECT=sqlite" in (install / ".env").read_text()

    def test_missing_template_fails(self, install, sync):
        (install / "template.env").unlink()

        result = sync()

        assert result.returncode == 1
        assert "Template not found" in result.stderr
