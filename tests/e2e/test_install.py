# SPDX-License-Identifier: GPL-3.0-only
"""Install, update and uninstall in a systemd container, as on a server.

The tests share one container and run in order.
"""

import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SUBMODULE = "lib_relaysms_payload_specs"
# The distros install.sh supports. CI picks one with -k.
BASES = {
    "ubuntu": "docker.io/library/ubuntu:24.04",
    "debian": "docker.io/library/debian:13",
}
D = "/opt/relaysms/relaysms-publisher"
UNITS = "/etc/systemd/system/relaysms-publisher-*.service"
# smtp exits cleanly while SMTP_TRANSPORT_ENABLED is off, so it isn't checked.
SERVICES = " ".join(
    f"relaysms-publisher-{name}.service" for name in ("rest", "grpc", "worker", "beat")
)
DATA_DIRS = [
    "data",
    "data/platforms/adapters",
    "data/platforms/venvs",
    "data/platforms/assets",
    "data/platforms",
    "data/gateway_clients",
]
DATA_RW_PATHS = "ReadWritePaths=" + " ".join(f"{D}/{path}" for path in DATA_DIRS)
# Env var, then the path before and after scripts/migrate-runtime-data.sh.
LEGACY = {
    "PLATFORMS_ADAPTERS_DIR": ("platforms/adapters", "data/platforms/adapters"),
    "PLATFORMS_ADAPTERS_VENV_DIR": ("platforms/adapters_venv", "data/platforms/venvs"),
    "PLATFORMS_ADAPTERS_ASSETS_DIR": (
        "platforms/adapters_assets",
        "data/platforms/assets",
    ),
}


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        pytest.fail(f"{' '.join(args)}\n{result.stderr}")
    return result.stdout


def sh(container: str, script: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["podman", "exec", container, "bash", "-c", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def ok(container: str, script: str, timeout: int = 600) -> str:
    """Run the script and fail with its output and the service logs if it fails."""
    result = sh(container, script, timeout)
    if result.returncode != 0:
        logs = sh(container, "journalctl -u 'relaysms-publisher*' -n 80", 60).stdout
        pytest.fail("\n".join([result.stdout[-3000:], result.stderr[-3000:], logs]))
    return result.stdout


def wait_until(container: str, check: str) -> None:
    ok(container, f"for _ in $(seq 60); do {check} && exit; sleep 1; done; exit 1")


def read_write_paths(container: str) -> set[str]:
    return set(ok(container, f"grep -h ^ReadWritePaths= {UNITS}").splitlines())


def assert_serving(container: str) -> None:
    ok(container, f"systemctl is-active {SERVICES}")
    wait_until(container, "curl -fsS 127.0.0.1:16000/health")


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    """The working tree, uncommitted changes included, as a repo to clone."""
    repo = tmp_path_factory.mktemp("source")
    files = run("git", "-C", str(REPO), "ls-files", "-z", "-co", "--exclude-standard")
    for name in filter(None, files.split("\0")):
        if (REPO / name).is_file():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / name, repo / name)

    def git(*args: str) -> str:
        return run("git", "-C", str(repo), *args)

    sha = run("git", "-C", str(REPO), "rev-parse", f"HEAD:{SUBMODULE}").strip()
    git("init", "-q", "-b", "e2e")
    git("config", "commit.gpgsign", "false")
    git("add", "-A")
    git("update-index", "--add", "--cacheinfo", f"160000,{sha},{SUBMODULE}")
    git("-c", "user.name=e2e", "-c", "user.email=e2e@localhost", "commit", "-qm", "e2e")
    return repo


@pytest.fixture(scope="module", params=list(BASES))
def container(request, source):
    if not shutil.which("podman"):
        pytest.skip("podman is not installed")
    rootless = run("podman", "info", "--format", "{{.Host.Security.Rootless}}")
    if rootless.strip() != "true":
        pytest.skip("needs rootless podman")

    image = f"relaysms-publisher-e2e-{request.param}"
    base = f"BASE={BASES[request.param]}"
    run("podman", "build", "-q", "--build-arg", base, "-t", image, str(HERE))
    name = f"relaysms-e2e-{request.param}-{uuid.uuid4().hex[:8]}"
    run(
        "podman", "run", "-d", "--name", name, "--systemd=always",
        # systemd needs it to sandbox the units. Rootless, it stays inside the
        # container's user namespace.
        "--cap-add", "SYS_ADMIN",
        "-v", f"{source}:/src:ro",
        "-v", "relaysms-e2e-pip:/root/.cache/pip",
        "-v", "relaysms-e2e-cargo:/root/.cargo/registry",
        image,
    )  # fmt: skip
    try:
        sh(name, "systemctl is-system-running --wait", timeout=120)
        yield name
    finally:
        run("podman", "rm", "-f", name)


def test_piped_install_starts_services(container):
    ok(
        container,
        "cat /src/install.sh | REPO_URL=file:///src BRANCH=e2e bash -s -- "
        f"--install-dir {D} --skip-nginx",
        timeout=1800,
    )

    assert_serving(container)


def test_services_write_only_to_data_dirs(container):
    assert read_write_paths(container) == {DATA_RW_PATHS}
    # beat writes its schedule from inside the sandbox.
    wait_until(container, f"ls {D}/data/celerybeat-schedule*")
    owners = ok(container, f"stat -c %U {D}/data/relaysms.db {D}/data/celerybeat-*")
    assert set(owners.split()) == {"relaysms"}


def test_cli_credential_signs_in_to_api(container):
    create = "creds create --username ops --administrator"
    output = ok(container, f"{D}/publisher.sh {create}")
    password = re.search(r"^Password : (\S+)$", output, re.MULTILINE)
    assert password, output

    ok(container, f"curl -fsS -u 'ops:{password[1]}' 127.0.0.1:16000/v1/auth/me")


def test_update_moves_legacy_layout_and_refreshes_units(container):
    moves = "\n".join(
        f"mv {new} {old} && sed -i 's#^{var}=.*#{var}={old}#' .env"
        for var, (old, new) in LEGACY.items()
    )
    legacy_paths = " ".join(f"{D}/{old}" for old, _ in LEGACY.values())
    ok(
        container,
        f"""set -e
        cd {D}
        ./manage.sh stop
        {moves}
        mkdir platforms/adapters/demo
        touch platforms/adapters/demo/main.py
        sed -i 's#^ReadWritePaths=.*#ReadWritePaths={D}/data {legacy_paths}#' {UNITS}
        systemctl daemon-reload""",
    )

    ok(container, f"{D}/manage.sh update", timeout=1800)

    ok(container, f"test -f {D}/data/platforms/adapters/demo/main.py")
    for var, (_, new) in LEGACY.items():
        assert ok(container, f"grep ^{var}= {D}/.env") == f"{var}={new}\n"
    assert read_write_paths(container) == {DATA_RW_PATHS}
    assert_serving(container)


def test_uninstall_removes_units_and_install_dir(container):
    ok(container, f"echo yes | {D}/manage.sh uninstall")

    ok(container, f"! ls {UNITS} && test ! -e {D}")
