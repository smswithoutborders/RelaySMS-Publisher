# SPDX-License-Identifier: GPL-3.0-only

import re
from pathlib import Path

import pytest
from dotenv import dotenv_values

from publisher import config, db
from publisher.config import (
    AuthConfig,
    CeleryConfig,
    DatabaseConfig,
    GrpcConfig,
    LoggingConfig,
    OfflinePublishConfig,
    PlatformsConfig,
    SmtpConfig,
)

KEY = "ab" * 32
BASE_ENV = {"DATA_ENCRYPTION_KEY": KEY, "OFFLINE_PUBLISH_ALLOWED_PROTOCOLS": "smtp"}


def load(section, **env):
    return section.from_env({**BASE_ENV, **env})


def errors(**env):
    return "\n".join(config.check({**BASE_ENV, **env}))


def test_defaults():
    assert load(LoggingConfig).log_level == "INFO"
    assert not load(GrpcConfig).tls_enabled
    database = load(DatabaseConfig)
    assert database.dialect == "sqlite"
    assert database.data_encryption_key == bytes.fromhex(KEY)
    assert not database.encryption_enabled
    assert config.check(BASE_ENV) == []


def test_get_loads_each_section_once():
    assert LoggingConfig.get() is LoggingConfig.get()


def test_invalid_section_raises_on_load():
    with pytest.raises(config.ConfigError, match="SMTP_IMAP_SERVER"):
        load(SmtpConfig, SMTP_TRANSPORT_ENABLED="true")


def test_check_reports_every_section_together():
    message = "\n".join(config.check({"LOG_LEVEL": "loud", "MYSQL_PORT": "abc"}))

    assert "LOG_LEVEL" in message
    assert "MYSQL_PORT" in message
    assert "DATA_ENCRYPTION_KEY" in message


@pytest.mark.parametrize("value", ["zz" * 32, "ab" * 16])
def test_invalid_key_is_rejected(value):
    assert "DATA_ENCRYPTION_KEY" in errors(DATA_ENCRYPTION_KEY=value)


def test_encryption_key_required_only_when_enabled():
    assert "DATABASE_ENCRYPTION_KEY" in errors(DATABASE_ENCRYPTION_ENABLED="true")
    assert not errors(DATABASE_ENCRYPTION_ENABLED="true", DATABASE_ENCRYPTION_KEY=KEY)


def test_server_dialect_requires_complete_settings():
    assert "MYSQL_USER" in errors(DATABASE_DIALECT="mysql")


def test_grpc_tls_requires_cert_and_key():
    message = errors(GRPC_TLS_ENABLED="true")

    assert "GRPC_TLS_CERT_FILE" in message
    assert "GRPC_TLS_KEY_FILE" in message


def test_grpc_tls_files_alone_do_not_enable_tls():
    grpc = load(GrpcConfig, GRPC_TLS_CERT_FILE="cert.pem", GRPC_TLS_KEY_FILE="k.pem")

    assert not grpc.tls_enabled


def test_enabled_smtp_requires_credentials():
    message = errors(SMTP_TRANSPORT_ENABLED="true")

    for name in (
        "SMTP_IMAP_SERVER",
        "SMTP_IMAP_USERNAME",
        "SMTP_IMAP_PASSWORD",
        "SMTP_TRUSTED_AUTHSERV_ID",
    ):
        assert name in message


def test_smtp_tls_client_certificate_needs_key():
    assert "SMTP_TLS_CLIENT_KEY" in errors(SMTP_TLS_CLIENT_CERTIFICATE="client.pem")


def test_wildcard_web_origin_is_rejected():
    assert "AUTH_WEB_ORIGINS" in errors(AUTH_WEB_ORIGINS="*")


def test_platforms_github_orgs_are_normalized_and_checked():
    platforms = load(PlatformsConfig, PLATFORMS_GITHUB_ORGS="SMSWithoutBorders, acme")

    assert platforms.github_orgs == ["smswithoutborders", "acme"]
    assert "PLATFORMS_GITHUB_ORGS" in errors(PLATFORMS_GITHUB_ORGS="evil/org")


def test_allowed_senders_are_normalized():
    smtp = load(SmtpConfig, SMTP_ALLOWED_SENDERS="@Example.com, User@Other.org")

    assert smtp.allowed_senders == {"example.com", "user@other.org"}


def test_push_urls_must_be_http():
    assert "UPTIME_KUMA_SMTP_PUSH_URL" in errors(
        UPTIME_KUMA_SMTP_PUSH_URL="ftp://bad.example.com"
    )


def test_adapter_paths_resolve_against_the_install_dir():
    platforms = load(
        PlatformsConfig,
        PLATFORMS_ADAPTERS_VENV_DIR="data/platforms/venvs",
        PLATFORMS_ADAPTERS_STATE_DIR="/srv/state",
    )

    assert platforms.adapters_venv_dir == config.ROOT / "data/platforms/venvs"
    assert platforms.adapters_state_dir == Path("/srv/state")


def test_sqlite_url_uses_the_configured_path():
    database = load(DatabaseConfig, SQLITE_DATABASE_PATH="data/test dir/app.db")

    assert db.build_url(database) == "sqlite:///data/test%20dir/app.db"


def test_server_url_escapes_credentials():
    database = load(
        DatabaseConfig,
        DATABASE_DIALECT="mysql",
        MYSQL_USER="relay",
        MYSQL_PASSWORD="p@ss/word",
        MYSQL_DATABASE="relaysms",
    )

    assert (
        db.build_url(database)
        == "mysql+pymysql://relay:p%40ss%2Fword@localhost:3306/relaysms"
    )


def test_secrets_are_hidden_from_repr():
    database = load(DatabaseConfig, MYSQL_PASSWORD="hunter2")
    smtp = load(SmtpConfig, SMTP_IMAP_PASSWORD="imap-secret")

    assert "hunter2" not in repr(database)
    assert repr(bytes.fromhex(KEY)) not in repr(database)
    assert "imap-secret" not in repr(smtp)


def test_celery_concurrency_defaults_by_broker():
    assert load(CeleryConfig).worker_concurrency == 1
    assert load(CeleryConfig, CELERY_BROKER_TYPE="redis").worker_concurrency == 4
    assert load(CeleryConfig, CELERY_WORKER_CONCURRENCY="8").worker_concurrency == 8


def test_surrounding_quotes_are_removed():
    celery = load(CeleryConfig, CELERY_CLEANUP_CRON='"0 */3 * * *"')

    assert celery.cleanup_cron == "0 */3 * * *"
    assert load(SmtpConfig, SMTP_IMAP_SERVER="'imap.example.org'").imap_server == (
        "imap.example.org"
    )


def test_invalid_cron_is_rejected():
    assert "CELERY_CLEANUP_CRON" in errors(CELERY_CLEANUP_CRON="every 3 hours")


def test_offline_shared_secret_must_be_a_key():
    assert "OFFLINE_PUBLISH_SHARED_SECRET" in errors(
        OFFLINE_PUBLISH_SHARED_SECRET="s3cret"
    )

    offline = load(OfflinePublishConfig, OFFLINE_PUBLISH_SHARED_SECRET=KEY)
    assert offline.shared_secret == KEY


@pytest.mark.parametrize("protocols", ["https", "smtp,https", ""])
def test_offline_https_requires_shared_secret(protocols):
    allowed = {"OFFLINE_PUBLISH_ALLOWED_PROTOCOLS": protocols}

    assert "OFFLINE_PUBLISH_SHARED_SECRET" in errors(**allowed)
    assert not errors(**allowed, OFFLINE_PUBLISH_SHARED_SECRET=KEY)


def test_template_env_paths_match_defaults():
    # scripts/lib.sh falls back to template.env for paths unset in .env.
    template = dotenv_values(config.ROOT / "template.env")
    database, celery = load(DatabaseConfig), load(CeleryConfig)
    platforms = load(PlatformsConfig)
    defaults = {
        "SQLITE_DATABASE_PATH": database.sqlite_path,
        "CELERY_BROKER_DB_PATH": celery.broker_db_path,
        "CELERY_RESULT_DB_PATH": celery.result_db_path,
        "CELERY_BEAT_SCHEDULE_PATH": celery.beat_schedule_path,
        "PLATFORMS_ADAPTERS_DIR": platforms.adapters_dir,
        "PLATFORMS_ADAPTERS_VENV_DIR": platforms.adapters_venv_dir,
        "PLATFORMS_ADAPTERS_CONFIG_DIR": platforms.adapters_config_dir,
        "PLATFORMS_ADAPTERS_STATE_DIR": platforms.adapters_state_dir,
    }

    for key, default in defaults.items():
        assert config.ROOT / str(template[key]) == config.ROOT / default, key


class RecordingEnv(dict):
    """An empty environment that records every name config asks for."""

    def __init__(self):
        super().__init__()
        self.names = set()

    def get(self, key, default=None):
        self.names.add(key)
        return default


def test_template_env_lists_every_variable_config_reads():
    # sync-env.sh --prune drops what the template lacks, so a variable config
    # reads must be in it, if only commented out.
    text = (config.ROOT / "template.env").read_text()
    template = set(re.findall(r"^\s*(?:#\s*)?([A-Za-z_]\w*)=", text, re.M))
    env = RecordingEnv()

    # Only catches the names config reads when nothing is set.
    config.check(env)

    assert env.names - template == set(), "missing from template.env"
    # Read outside config: by scripts/run.sh, Docker and the systemd units, and
    # OTEL_* by OpenTelemetry.
    external = {"HOST", "PORT", "WORKERS"}
    unused = {n for n in template - env.names - external if not n.startswith("OTEL_")}
    assert unused == set(), "in template.env but unused"


def test_auth_session_defaults():
    auth = load(AuthConfig)

    assert auth.web_origins == []
    assert auth.cookie_secure
