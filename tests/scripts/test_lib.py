# SPDX-License-Identifier: GPL-3.0-only

import getpass
import re

import pytest


def unit_values(text: str, key: str) -> list[str]:
    return re.findall(rf"^{key}=(.*)$", text, re.MULTILINE)


def app_directories(bash, **env) -> list[str]:
    result = bash("app_directories", **env)
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


class TestReadEnvVar:
    @pytest.mark.parametrize(
        ("line", "value"),
        [
            ("KEY=plain", "plain"),
            ('KEY="double quoted"', "double quoted"),
            ("KEY='single quoted'", "single quoted"),
            ("export KEY=exported", "exported"),
            ("KEY = padded ", "padded"),
            ("KEY=amqp://u:p@host/vhost?a=b", "amqp://u:p@host/vhost?a=b"),
        ],
    )
    def test_parses_value(self, install, bash, line, value):
        (install / ".env").write_text(f"OTHER_KEY=x\n{line}\n")
        assert bash("read_env_var KEY .env").stdout == f"{value}\n"

    def test_last_assignment_wins(self, install, bash):
        (install / ".env").write_text("KEY=first\nKEY=second\n")
        assert bash("read_env_var KEY .env").stdout == "second\n"

    def test_missing_key_or_file_is_empty(self, bash):
        assert bash("read_env_var KEY .env").stdout == "\n"
        assert bash("read_env_var KEY missing.env").stdout == "\n"


class TestAppDirectories:
    def test_unset_vars_use_template_defaults(self, install, bash):
        assert app_directories(bash) == [
            f"{install}/data",
            f"{install}/data/platforms/adapters",
            f"{install}/data/platforms/venvs",
            f"{install}/data/platforms/assets",
            f"{install}/data/platforms",
            f"{install}/data/gateway_clients",
        ]

    def test_env_values_are_resolved_against_install_dir(self, install, bash):
        (install / ".env").write_text(
            "SQLITE_DATABASE_PATH=:memory:\n"
            "CELERY_BROKER_DB_PATH=state/broker.db\n"
            "PLATFORMS_ADAPTERS_DIR=/srv/adapters/\n"
            "PLATFORMS_ADAPTERS_ASSETS_DIR='/srv/assets'\n"
        )
        dirs = app_directories(bash)
        assert f"{install}/state" in dirs
        assert "/srv/adapters" in dirs
        assert "/srv/assets" in dirs
        assert f"{install}/data/platforms/adapters" not in dirs

    def test_database_in_install_root_lists_install_dir(self, install, bash):
        (install / ".env").write_text("SQLITE_DATABASE_PATH=relaysms.db\n")
        assert str(install) in app_directories(bash)


class TestEnsureAppDirectories:
    def test_creates_directories_for_service_user(self, install, bash):
        (install / ".env").write_text("SQLITE_DATABASE_PATH=relaysms.db\n")
        install.chmod(0o755)

        result = bash(f"ensure_app_directories {getpass.getuser()}")

        assert result.returncode == 0, result.stderr
        for path in app_directories(bash):
            if path != str(install):
                assert (install / path).stat().st_mode & 0o777 == 0o750
        assert install.stat().st_mode & 0o777 == 0o755

    def test_skips_paths_through_a_symlink(self, install, bash, tmp_path):
        target = tmp_path / "elsewhere"
        target.mkdir(mode=0o755)
        (install / "data").mkdir()
        (install / "data/platforms").symlink_to(target)

        result = bash(f"ensure_app_directories {getpass.getuser()}")

        assert result.returncode == 0, result.stderr
        assert "goes through a symlink" in result.stderr
        assert list(target.iterdir()) == []
        assert target.stat().st_mode & 0o777 == 0o755


class TestRenderUnits:
    def render(self, install, bash, **env):
        result = bash(
            'SYSTEMD_DIR="$PWD/units" && mkdir -p "$SYSTEMD_DIR" && render_units relay',
            **env,
        )
        assert result.returncode == 0, result.stderr
        return {path.name: path.read_text() for path in (install / "units").iterdir()}

    def test_renders_every_unit_for_this_install(self, install, bash):
        units = self.render(install, bash)

        assert sorted(units) == sorted(
            ["relaysms-publisher.target"]
            + [
                f"relaysms-publisher-{s}.service"
                for s in ("rest", "grpc", "worker", "beat", "smtp")
            ]
        )
        rest = units["relaysms-publisher-rest.service"]
        assert unit_values(rest, "User") == ["relay"]
        assert unit_values(rest, "WorkingDirectory") == [str(install)]
        assert unit_values(rest, "ReadWritePaths") == [" ".join(app_directories(bash))]
        assert "/opt/relaysms" not in "".join(units.values())

    def test_named_instance_renames_units_and_references(self, bash, install):
        units = self.render(install, bash, INSTANCE_NAME="acme")

        assert "relaysms-publisher-acme.target" in units
        rest = units["relaysms-publisher-acme-rest.service"]
        assert unit_values(rest, "PartOf") == ["relaysms-publisher-acme.target"]
        assert unit_values(rest, "SyslogIdentifier") == ["relaysms-publisher-acme-rest"]
        assert unit_values(rest, "Description") == ["RelaySMS Publisher REST API"]
        target = units["relaysms-publisher-acme.target"]
        assert "relaysms-publisher-acme-smtp.service" in target
        assert "relaysms-publisher-smtp.service" not in target


class TestServiceUser:
    def test_installed_unit_user_wins(self, bash):
        result = bash(
            'SYSTEMD_DIR="$PWD/units" && mkdir -p "$SYSTEMD_DIR" && render_units relay '
            "&& ENV_FILE=.env detect_service_user && installed_service_user"
        )
        assert result.stdout.splitlines() == ["relay", "relay"]

    def test_without_units_falls_back_to_env_owner(self, bash):
        result = bash(
            'SYSTEMD_DIR="$PWD/none" && ENV_FILE=.env detect_service_user '
            "&& installed_service_user"
        )
        assert result.stdout.splitlines() == [getpass.getuser()]


class TestValidators:
    @pytest.mark.parametrize(
        ("validator", "value", "valid"),
        [
            ("validate_hostname", "publisher.example.com", True),
            ("validate_hostname", "localhost", False),
            ("validate_hostname", "../etc/passwd", False),
            ("validate_hostname", "-d.example.com", False),
            ("validate_identifier", "relaysms_db", True),
            ("validate_identifier", "relaysms;drop", False),
            ("validate_identifier", "1starts_with_digit", False),
            ("validate_secret", "s3cret-pass_word", True),
            ("validate_secret", "it's", False),
            ("validate_secret", "a/b", False),
        ],
    )
    def test_rejects_unsafe_values(self, bash, validator, value, valid):
        result = bash(f'{validator} NAME "$VALUE"', VALUE=value)
        assert (result.returncode == 0) is valid, result.stderr
