# SPDX-License-Identifier: GPL-3.0-only

import pytest

LEGACY_ENV = (
    "PLATFORMS_ADAPTERS_DIR=platforms/adapters\n"
    "PLATFORMS_ADAPTERS_VENV_DIR={install}/platforms/adapters_venv\n"
    "PLATFORMS_ADAPTERS_ASSETS_DIR=platforms/adapters_assets\n"
    "GATEWAY_CLIENTS_REGISTRY_FILE=gateway_clients/registry.json\n"
)


@pytest.fixture
def migrate(bash):
    def run() -> str:
        result = bash("bash scripts/migrate-runtime-data.sh")
        assert result.returncode == 0, result.stderr
        return result.stdout

    return run


@pytest.fixture
def legacy(install):
    """An install laid out the way it was before runtime data moved to data/."""
    (install / "platforms/adapters/demo").mkdir(parents=True)
    (install / "platforms/adapters/demo/main.py").touch()
    (install / "platforms/adapters_venv/demo/bin").mkdir(parents=True)
    (install / "platforms/adapters_assets").mkdir()
    (install / "gateway_clients").mkdir()
    (install / "gateway_clients/registry.json").write_text("{}")
    (install / ".env").write_text(LEGACY_ENV.format(install=install))
    return install


def env_value(install, key):
    lines = (install / ".env").read_text().splitlines()
    return next(line.split("=", 1)[1] for line in lines if line.startswith(f"{key}="))


class TestMigrateRuntimeData:
    def test_moves_legacy_layout_into_data(self, legacy, migrate):
        migrate()

        assert (legacy / "data/platforms/adapters/demo/main.py").is_file()
        assert (legacy / "data/platforms/venvs/demo").is_dir()
        assert (legacy / "data/platforms/assets").is_dir()
        assert (legacy / "data/gateway_clients/registry.json").is_file()
        assert not (legacy / "platforms/adapters").exists()

    def test_rewrites_env_keeping_relative_or_absolute_form(self, legacy, migrate):
        migrate()

        assert env_value(legacy, "PLATFORMS_ADAPTERS_DIR") == "data/platforms/adapters"
        assert (
            env_value(legacy, "PLATFORMS_ADAPTERS_VENV_DIR")
            == f"{legacy}/data/platforms/venvs"
        )

    def test_moves_default_dirs_when_env_leaves_them_unset(self, legacy, migrate):
        (legacy / ".env").write_text("")

        migrate()

        assert (legacy / "data/platforms/adapters/demo").is_dir()
        assert (legacy / ".env").read_text() == ""

    def test_leaves_custom_locations_alone(self, legacy, migrate):
        (legacy / ".env").write_text("PLATFORMS_ADAPTERS_DIR=/srv/adapters\n")

        migrate()

        assert (legacy / "platforms/adapters/demo").is_dir()
        assert env_value(legacy, "PLATFORMS_ADAPTERS_DIR") == "/srv/adapters"

    def test_rerun_changes_nothing(self, legacy, migrate):
        migrate()
        env = (legacy / ".env").read_text()

        assert "Moved" not in migrate()
        assert (legacy / ".env").read_text() == env

    def test_points_venv_scripts_at_new_paths(self, legacy, migrate):
        old_venv = legacy / "platforms/adapters_venv/demo"
        (old_venv / "bin/pip").write_text(f"#!{old_venv}/bin/python\n")

        migrate()

        pip = (legacy / "data/platforms/venvs/demo/bin/pip").read_text()
        assert pip == f"#!{legacy}/data/platforms/venvs/demo/bin/python\n"

    @pytest.mark.parametrize(
        ("overrides", "copied"), [('[{"mcc": "624"}]', True), ("[]", False)]
    )
    def test_copies_only_local_mcc_mnc_overrides(
        self, legacy, migrate, overrides, copied
    ):
        (legacy / "gateway_clients/mcc_mnc_overrides.json").write_text(overrides)

        migrate()

        assert (
            legacy / "data/gateway_clients/mcc_mnc_overrides.json"
        ).exists() is copied
