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
    """Sync install/.env from a small template, passing any extra options."""
    (install / "template.env").write_text(TEMPLATE)
    return lambda *options: bash(
        f'bash "{REPO}/sync-env.sh" --yes {" ".join(options)} .env template.env'
    )


class TestSyncEnv:
    def test_adds_missing_vars_after_their_neighbours(self, install, sync):
        env = install / ".env"
        env.write_text("# Server\nHOST=0.0.0.0\n\n# Database\nDATABASE_DIALECT=mysql\n")

        assert sync().returncode == 0

        assert env.read_text() == (
            "# Server\nHOST=0.0.0.0\nPORT=16000\n\n# Database\nDATABASE_DIALECT=mysql\n"
        )

    def test_keeps_multi_line_comments_next_to_their_variable(self, install, sync):
        (install / "template.env").write_text(
            "# gRPC\nGRPC_PORT=6000\n"
            "# Leave off behind a proxy.\n# When on, serves TLS.\n"
            "GRPC_TLS_ENABLED=false\nGRPC_TLS_CERT_FILE=\n\n# Other\nOTHER=1\n"
        )
        env = install / ".env"
        env.write_text("# gRPC\nGRPC_PORT=7000\n\n# Other\nOTHER=2\n")

        sync()

        assert env.read_text() == (
            "# gRPC\nGRPC_PORT=7000\n"
            "# Leave off behind a proxy.\n# When on, serves TLS.\n"
            "GRPC_TLS_ENABLED=false\nGRPC_TLS_CERT_FILE=\n\n# Other\nOTHER=2\n"
        )

    def test_repeated_comment_anchors_to_its_own_section(self, install, sync):
        hint = "# Generate: openssl rand -hex 32"
        (install / "template.env").write_text(
            f"# A\nA_ON=true\n{hint}\nA_KEY=\n\n# B\nB_ON=true\n{hint}\nB_KEY=\n"
        )
        env = install / ".env"
        env.write_text(f"# A\nA_ON=true\n{hint}\nA_KEY=x\n\n# B\nB_ON=true\n")

        sync()

        assert env.read_text() == (
            f"# A\nA_ON=true\n{hint}\nA_KEY=x\n\n# B\nB_ON=true\n{hint}\nB_KEY=\n"
        )

    def test_prints_the_changes_as_a_unified_diff(self, install, sync):
        (install / ".env").write_text("# Server\nHOST=0.0.0.0\n")

        out = sync().stdout

        assert "--- a/.env\n+++ b/.env\n" in out
        assert " HOST=0.0.0.0\n+PORT=16000\n" in out
        assert "+DATABASE_DIALECT=sqlite\n" in out

    def test_missing_section_is_appended_as_a_block(self, install, sync):
        env = install / ".env"
        env.write_text("# Server\nHOST=0.0.0.0\nPORT=1\n")

        sync()

        assert env.read_text() == (
            "# Server\nHOST=0.0.0.0\nPORT=1\n\n# Database\nDATABASE_DIALECT=sqlite\n"
        )

    def test_dry_run_prints_the_diff_without_writing(self, install, sync):
        env = install / ".env"
        env.write_text("# Server\nHOST=0.0.0.0\n")

        result = sync("--dry-run")

        assert "+PORT=16000\n" in result.stdout
        assert env.read_text() == "# Server\nHOST=0.0.0.0\n"
        assert not (install / ".env.bak").exists()

        env.unlink()
        sync("--dry-run")

        assert not env.exists()

    def test_without_yes_and_no_terminal_nothing_is_written(self, install, bash):
        (install / "template.env").write_text(TEMPLATE)
        env = install / ".env"
        env.write_text("# Server\nHOST=0.0.0.0\n")
        # setsid drops the controlling terminal, so the prompt gets no answer.
        run = 'setsid -w bash "{}/sync-env.sh" {} template.env </dev/null'

        result = bash(run.format(REPO, ".env"))
        bash(run.format(REPO, "missing.env"))

        assert "+PORT=16000\n" in result.stdout
        assert "Aborted" in result.stdout
        assert env.read_text() == "# Server\nHOST=0.0.0.0\n"
        assert not (install / ".env.bak").exists()
        assert not (install / "missing.env").exists()

    def test_prune_removes_variables_the_template_lacks(self, install, sync):
        env = install / ".env"
        env.write_text(
            "# Server\nOLD=1\nHOST=0.0.0.0\nPORT=1\n\n"
            "# Sentry\n# Error reporting.\nSENTRY_DSN=x\nSENTRY_RATE=1\n\n"
            "# Database\nDATABASE_DIALECT=mysql\nOLD2=2\n\n"
            "# Legacy\nLEGACY=1\n"
        )

        assert "0 variable(s) added, 5 removed" in sync("--prune").stdout

        assert env.read_text() == (
            "# Server\nHOST=0.0.0.0\nPORT=1\n\n# Database\nDATABASE_DIALECT=mysql\n"
        )

    def test_prune_keeps_variables_commented_out_in_the_template(self, install, sync):
        (install / "template.env").write_text("# Broker\n# BROKER_URL=amqp://\nA=1\n")
        env = install / ".env"
        env.write_text("# Broker\nBROKER_URL=amqp://prod\nA=1\n")

        assert "Nothing to change" in sync("--prune").stdout

        assert env.read_text() == "# Broker\nBROKER_URL=amqp://prod\nA=1\n"

    def test_unknown_option_fails(self, bash):
        result = bash(f'bash "{REPO}/sync-env.sh" --nope')

        assert result.returncode == 1
        assert "Unknown option: --nope" in result.stderr

    def test_backs_up_the_previous_file(self, install, sync):
        (install / ".env").write_text("HOST=0.0.0.0\n")

        sync()

        assert (install / ".env.bak").read_text() == "HOST=0.0.0.0\n"

    def test_complete_env_is_left_untouched(self, install, sync):
        # Without --prune, variables the template lacks stay too.
        (install / ".env").write_text(TEMPLATE + "OLD=1\n")

        assert "Nothing to change" in sync().stdout

        assert (install / ".env").read_text() == TEMPLATE + "OLD=1\n"
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
