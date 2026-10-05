# SPDX-License-Identifier: GPL-3.0-only
"""Settings read from the environment and checked before they are used.

Each module calls get on the section class it needs. A section is loaded and
checked once per process. Run python -m config to check every section.
"""

import datetime
import logging
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Literal, Self, overload
from urllib.parse import urlsplit

from dotenv import load_dotenv

# logutils imports this module, so importing logutils here would be circular.

ROOT = Path(__file__).resolve().parent
DATABASE_DIALECTS = ("sqlite", "mysql", "postgres")
CELERY_BROKERS = ("sqlite", "redis", "rabbitmq")
GITHUB_ORG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$")

# Fill unset variables from .env. Values already in the environment win.
# Tests turn this off with LOAD_DOTENV.
if os.environ.get("LOAD_DOTENV", "").strip().lower() != "false":
    # References to other variables are not expanded, the same as systemd.
    load_dotenv(ROOT / ".env", override=False, interpolate=False)


class ConfigError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("Invalid configuration:\n  " + "\n  ".join(errors))
        self.errors = errors


class _Reader:
    """Reads environment values and collects every error to report them together."""

    def __init__(self, env: Mapping[str, str]):
        self.env = env
        self.errors: list[str] = []

    def fail(self, name: str, message: str) -> None:
        self.errors.append(f"{name}: {message}")

    @overload
    def get_str(self, name: str, default: str) -> str: ...
    @overload
    def get_str(self, name: str, default: None = None) -> str | None: ...
    def get_str(self, name: str, default: str | None = None) -> str | None:
        value = self.env.get(name, "").strip()
        # Drop one pair of surrounding quotes, since docker run --env-file keeps them.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].strip()
        # An empty value counts as unset, since template.env leaves options blank.
        return value or default

    def get_required(self, name: str, required: bool) -> str | None:
        value = self.get_str(name)
        if required and value is None:
            self.fail(name, "is required")
        return value

    def get_int(self, name: str, default: int, minimum: int | None = None) -> int:
        raw = self.get_str(name)
        if raw is None:
            return default
        try:
            value = int(raw)
        except ValueError:
            self.fail(name, f"expected an integer, got {raw!r}")
            return default
        if minimum is not None and value < minimum:
            self.fail(name, f"must be at least {minimum}, got {value}")
        return value

    def get_bool(self, name: str, default: bool) -> bool:
        raw = self.get_str(name)
        if raw is None:
            return default
        if raw.lower() not in ("true", "false"):
            self.fail(name, f"expected true or false, got {raw!r}")
            return default
        return raw.lower() == "true"

    def get_list(self, name: str, default: list[str] | None = None) -> list[str]:
        values = [item.strip() for item in (self.get_str(name) or "").split(",")]
        return [item for item in values if item] or list(default or [])

    def get_url(self, name: str) -> str | None:
        url = self.get_str(name)
        if url:
            self._check_url(name, url)
        return url

    def get_urls(self, name: str) -> list[str]:
        urls = self.get_list(name)
        for url in urls:
            self._check_url(name, url)
        return urls

    def _check_url(self, name: str, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            self.fail(name, f"expected an http(s) URL, got {url!r}")

    def get_choice(self, name: str, choices: tuple[str, ...], default: str) -> str:
        value = self.get_str(name, default).lower()
        if value not in choices:
            self.fail(name, f"expected one of {', '.join(choices)}, got {value!r}")
            return default
        return value

    @overload
    def get_key(self, name: str, required: Literal[True]) -> bytes: ...
    @overload
    def get_key(self, name: str, required: bool) -> bytes | None: ...
    def get_key(self, name: str, required: bool) -> bytes | None:
        raw = self.get_str(name)
        if raw is None:
            if required:
                self.fail(name, "is required. Generate: openssl rand -hex 32")
            return None
        try:
            key = bytes.fromhex(raw)
        except ValueError:
            self.fail(name, "must be a hex string")
            return None
        if len(key) != 32:
            self.fail(name, "must be 32 bytes, which is 64 hex characters")
            return None
        return key

    def get_secret(self, name: str) -> str | None:
        """Check the secret is a valid key, but return it as text to compare."""
        return self.get_str(name) if self.get_key(name, required=False) else None

    def get_path(self, name: str, default: Path) -> Path:
        return Path(self.get_str(name) or default)

    def get_cron(self, name: str, default: str) -> str:
        value = self.get_str(name, default)
        if len(value.split()) != 5:
            self.fail(name, f"expected a 5-field cron expression, got {value!r}")
            return default
        return value

    def require_pair(self, first: str, second: str) -> None:
        if bool(self.get_str(first)) != bool(self.get_str(second)):
            self.fail(first, f"must be set together with {second}")


class Section:
    """Base class for a section. Each section reads its own variables in load."""

    @classmethod
    def load(cls, read: _Reader) -> Self:
        raise NotImplementedError

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Self:
        """Read this section from the given environment.

        Raises:
            ConfigError: When any variable is missing or invalid.
        """
        read = _Reader(env)
        section = cls.load(read)
        if read.errors:
            raise ConfigError(read.errors)
        return section

    @classmethod
    @cache
    def get(cls) -> Self:
        """Return this section for the process, loading and checking it on first call.

        Raises:
            ConfigError: When the section is invalid.
        """
        return cls.from_env(os.environ)


@dataclass(frozen=True)
class LoggingConfig(Section):
    log_level: str

    @classmethod
    def load(cls, read: _Reader) -> Self:
        level = read.get_str("LOG_LEVEL", "INFO").upper()
        if level not in logging.getLevelNamesMapping():
            read.fail("LOG_LEVEL", f"unknown level {level!r}")
        return cls(log_level=level)


@dataclass(frozen=True)
class ServerDatabaseConfig:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    database: str

    @property
    def complete(self) -> bool:
        return all((self.host, self.user, self.password, self.database))


def _server_database(read: _Reader, prefix: str, port: int) -> ServerDatabaseConfig:
    return ServerDatabaseConfig(
        host=read.get_str(f"{prefix}_HOST", "localhost"),
        port=read.get_int(f"{prefix}_PORT", port, minimum=1),
        user=read.get_str(f"{prefix}_USER", ""),
        password=read.get_str(f"{prefix}_PASSWORD", ""),
        database=read.get_str(f"{prefix}_DATABASE", ""),
    )


@dataclass(frozen=True)
class DatabaseConfig(Section):
    dialect: str
    sqlite_path: str
    mysql: ServerDatabaseConfig
    postgres: ServerDatabaseConfig
    # SQLCipher encrypts SQLite. MySQL and Postgres rely on server encryption.
    encryption_enabled: bool
    encryption_key: bytes | None = field(repr=False)
    field_encryption_enabled: bool
    field_encryption_key: bytes | None = field(repr=False)
    # Always encrypts stored private keys, whatever the flags above say.
    data_encryption_key: bytes = field(repr=False)

    @classmethod
    def load(cls, read: _Reader) -> Self:
        dialect = read.get_choice("DATABASE_DIALECT", DATABASE_DIALECTS, "sqlite")
        mysql = _server_database(read, "MYSQL", 3306)
        postgres = _server_database(read, "POSTGRES", 5432)

        server = {"mysql": mysql, "postgres": postgres}.get(dialect)
        if server and not server.complete:
            prefix = dialect.upper()
            read.fail(
                "DATABASE_DIALECT",
                f"{dialect} needs {prefix}_HOST, {prefix}_USER, {prefix}_PASSWORD "
                f"and {prefix}_DATABASE",
            )

        encryption_enabled = read.get_bool("DATABASE_ENCRYPTION_ENABLED", False)
        field_encryption_enabled = read.get_bool(
            "DATABASE_FIELD_ENCRYPTION_ENABLED", False
        )

        return cls(
            dialect=dialect,
            sqlite_path=read.get_str("SQLITE_DATABASE_PATH", "data/relaysms.db"),
            mysql=mysql,
            postgres=postgres,
            encryption_enabled=encryption_enabled,
            encryption_key=read.get_key(
                "DATABASE_ENCRYPTION_KEY",
                required=encryption_enabled and dialect == "sqlite",
            ),
            field_encryption_enabled=field_encryption_enabled,
            field_encryption_key=read.get_key(
                "DATABASE_FIELD_ENCRYPTION_KEY", required=field_encryption_enabled
            ),
            data_encryption_key=read.get_key("DATA_ENCRYPTION_KEY", required=True),
        )


@dataclass(frozen=True)
class GrpcConfig(Section):
    host: str
    port: int
    # Leave TLS off behind a reverse proxy that terminates TLS itself.
    tls_enabled: bool
    tls_cert_file: str | None
    tls_key_file: str | None
    max_workers: int
    nonce_ttl_seconds: int

    @classmethod
    def load(cls, read: _Reader) -> Self:
        tls_enabled = read.get_bool("GRPC_TLS_ENABLED", False)
        # The old names would otherwise be ignored and TLS would turn off quietly.
        for old, new in (
            ("SSL_CERTIFICATE", "GRPC_TLS_CERT_FILE"),
            ("SSL_KEY", "GRPC_TLS_KEY_FILE"),
        ):
            if read.get_str(old):
                read.fail(old, f"renamed to {new}, with GRPC_TLS_ENABLED=true")
        return cls(
            host=read.get_str("GRPC_HOST", "127.0.0.1"),
            port=read.get_int("GRPC_PORT", 6000, minimum=1),
            tls_enabled=tls_enabled,
            tls_cert_file=read.get_required("GRPC_TLS_CERT_FILE", tls_enabled),
            tls_key_file=read.get_required("GRPC_TLS_KEY_FILE", tls_enabled),
            max_workers=read.get_int("GRPC_MAX_WORKERS", 10, minimum=1),
            nonce_ttl_seconds=read.get_int("NONCE_TTL_SECONDS", 600, minimum=1),
        )


@dataclass(frozen=True)
class TwilioConfig(Section):
    sms_transport_enabled: bool
    auth_token: str | None = field(repr=False)

    @classmethod
    def load(cls, read: _Reader) -> Self:
        enabled = read.get_bool("TWILIO_SMS_TRANSPORT_ENABLED", False)
        return cls(
            sms_transport_enabled=enabled,
            auth_token=read.get_required("TWILIO_AUTH_TOKEN", enabled),
        )


@dataclass(frozen=True)
class TwilioForwardConfig(Section):
    urls_raw: list[str]
    urls_json: list[str]
    timeout: int

    @classmethod
    def load(cls, read: _Reader) -> Self:
        return cls(
            urls_raw=read.get_urls("TWILIO_FORWARD_URLS_RAW"),
            urls_json=read.get_urls("TWILIO_FORWARD_URLS_JSON"),
            timeout=read.get_int("TWILIO_FORWARD_TIMEOUT", 10, minimum=1),
        )


@dataclass(frozen=True)
class SmtpConfig(Section):
    transport_enabled: bool
    imap_server: str | None
    imap_port: int
    imap_username: str | None
    imap_password: str | None = field(repr=False)
    mail_folders: list[str]
    tls_client_certificate: str | None
    tls_client_key: str | None
    # Lowercase addresses and bare domains.
    allowed_senders: frozenset[str]
    trusted_authserv_id: str | None
    require_dkim: bool
    require_spf: bool
    verify_dkim_independently: bool
    heartbeat_url: str | None

    @classmethod
    def load(cls, read: _Reader) -> Self:
        enabled = read.get_bool("SMTP_TRANSPORT_ENABLED", False)
        read.require_pair("SMTP_TLS_CLIENT_CERTIFICATE", "SMTP_TLS_CLIENT_KEY")
        return cls(
            transport_enabled=enabled,
            imap_server=read.get_required("SMTP_IMAP_SERVER", enabled),
            imap_port=read.get_int("SMTP_IMAP_PORT", 993, minimum=1),
            imap_username=read.get_required("SMTP_IMAP_USERNAME", enabled),
            imap_password=read.get_required("SMTP_IMAP_PASSWORD", enabled),
            mail_folders=read.get_list("SMTP_IMAP_MAIL_FOLDER", ["INBOX"]),
            tls_client_certificate=read.get_str("SMTP_TLS_CLIENT_CERTIFICATE"),
            tls_client_key=read.get_str("SMTP_TLS_CLIENT_KEY"),
            allowed_senders=frozenset(
                entry.lower().lstrip("@")
                for entry in read.get_list("SMTP_ALLOWED_SENDERS")
            ),
            trusted_authserv_id=read.get_required("SMTP_TRUSTED_AUTHSERV_ID", enabled),
            require_dkim=read.get_bool("SMTP_REQUIRE_DKIM", True),
            require_spf=read.get_bool("SMTP_REQUIRE_SPF", True),
            verify_dkim_independently=read.get_bool(
                "SMTP_VERIFY_DKIM_INDEPENDENTLY", False
            ),
            heartbeat_url=read.get_url("UPTIME_KUMA_SMTP_PUSH_URL"),
        )


@dataclass(frozen=True)
class OfflinePublishConfig(Section):
    # An empty list allows every protocol.
    allowed_protocols: list[str]
    shared_secret: str | None = field(repr=False)

    @classmethod
    def load(cls, read: _Reader) -> Self:
        return cls(
            allowed_protocols=read.get_list("OFFLINE_PUBLISH_ALLOWED_PROTOCOLS"),
            shared_secret=read.get_secret("OFFLINE_PUBLISH_SHARED_SECRET"),
        )


@dataclass(frozen=True)
class CeleryConfig(Section):
    broker_type: str
    broker_db_path: str
    result_db_path: str
    redis_url: str = field(repr=False)
    rabbitmq_url: str = field(repr=False)
    worker_concurrency: int
    beat_schedule_path: str
    cleanup_cron: str
    token_cleanup_cron: str
    worker_heartbeat_url: str | None

    @classmethod
    def load(cls, read: _Reader) -> Self:
        broker_type = read.get_choice("CELERY_BROKER_TYPE", CELERY_BROKERS, "sqlite")
        default_concurrency = 1 if broker_type == "sqlite" else 4
        return cls(
            broker_type=broker_type,
            broker_db_path=read.get_str(
                "CELERY_BROKER_DB_PATH", "data/celery_broker.db"
            ),
            result_db_path=read.get_str(
                "CELERY_RESULT_DB_PATH", "data/celery_results.db"
            ),
            redis_url=read.get_str("CELERY_REDIS_URL", "redis://localhost:6379/0"),
            rabbitmq_url=read.get_str(
                "CELERY_RABBITMQ_URL", "amqp://guest:guest@localhost:5672//"
            ),
            worker_concurrency=read.get_int(
                "CELERY_WORKER_CONCURRENCY", default_concurrency, minimum=1
            ),
            beat_schedule_path=read.get_str(
                "CELERY_BEAT_SCHEDULE_PATH", "data/celerybeat-schedule"
            ),
            cleanup_cron=read.get_cron("CELERY_CLEANUP_CRON", "0 */3 * * *"),
            token_cleanup_cron=read.get_cron("CELERY_TOKEN_CLEANUP_CRON", "0 3 * * *"),
            worker_heartbeat_url=read.get_url("UPTIME_KUMA_WORKER_PUSH_URL"),
        )


@dataclass(frozen=True)
class CleanupConfig(Section):
    payload_session_max_age: datetime.timedelta
    token_idle_max_age: datetime.timedelta

    @classmethod
    def load(cls, read: _Reader) -> Self:
        return cls(
            payload_session_max_age=datetime.timedelta(
                hours=read.get_int("PAYLOAD_SESSION_MAX_AGE_HOURS", 3, minimum=1)
            ),
            token_idle_max_age=datetime.timedelta(
                days=read.get_int("TOKEN_IDLE_MAX_AGE_DAYS", 90, minimum=1)
            ),
        )


@dataclass(frozen=True)
class PlatformsConfig(Section):
    adapters_dir: Path
    adapters_venv_dir: Path
    adapters_assets_dir: Path
    registry_file: Path
    github_orgs: list[str]

    @classmethod
    def load(cls, read: _Reader) -> Self:
        base = ROOT / "platforms"
        github_orgs = [org.lower() for org in read.get_list("PLATFORMS_GITHUB_ORGS")]
        for org in github_orgs:
            if not GITHUB_ORG_PATTERN.match(org):
                read.fail("PLATFORMS_GITHUB_ORGS", f"invalid GitHub org {org!r}")
        return cls(
            adapters_dir=read.get_path("PLATFORMS_ADAPTERS_DIR", base / "adapters"),
            adapters_venv_dir=read.get_path(
                "PLATFORMS_ADAPTERS_VENV_DIR", base / "adapters_venv"
            ),
            adapters_assets_dir=read.get_path(
                "PLATFORMS_ADAPTERS_ASSETS_DIR", base / "adapters_assets"
            ),
            registry_file=read.get_path(
                "PLATFORMS_REGISTRY_FILE", base / "registry.json"
            ),
            github_orgs=github_orgs,
        )


@dataclass(frozen=True)
class GatewayClientsConfig(Section):
    registry_file: Path

    @classmethod
    def load(cls, read: _Reader) -> Self:
        return cls(
            registry_file=read.get_path(
                "GATEWAY_CLIENTS_REGISTRY_FILE",
                ROOT / "gateway_clients" / "registry.json",
            )
        )


@dataclass(frozen=True)
class AuthConfig(Section):
    idle_timeout: datetime.timedelta
    max_age: datetime.timedelta
    web_origins: list[str]
    cookie_secure: bool

    @classmethod
    def load(cls, read: _Reader) -> Self:
        web_origins = [
            origin.rstrip("/") for origin in read.get_list("AUTH_WEB_ORIGINS")
        ]
        if "*" in web_origins:
            read.fail(
                "AUTH_WEB_ORIGINS",
                "must list exact origins; '*' can't carry credentials",
            )
        return cls(
            idle_timeout=datetime.timedelta(
                minutes=read.get_int("AUTH_SESSION_IDLE_MINUTES", 30, minimum=1)
            ),
            max_age=datetime.timedelta(
                hours=read.get_int("AUTH_SESSION_MAX_HOURS", 12, minimum=1)
            ),
            web_origins=web_origins,
            cookie_secure=read.get_bool("AUTH_SESSION_COOKIE_SECURE", True),
        )


@dataclass(frozen=True)
class ApiDocsConfig(Section):
    enabled: bool

    @classmethod
    def load(cls, read: _Reader) -> Self:
        return cls(enabled=read.get_bool("API_DOCS_ENABLED", False))


def check(env: Mapping[str, str] | None = None) -> list[str]:
    """Return every configuration error across all sections."""
    errors = []
    for cls in Section.__subclasses__():
        try:
            cls.from_env(os.environ if env is None else env)
        except ConfigError as e:
            errors += e.errors
    return errors


def main() -> int:
    """Print every configuration error and return 1, or print OK and return 0."""
    errors = check()
    if errors:
        print(ConfigError(errors), file=sys.stderr)
        return 1
    print("Configuration OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
