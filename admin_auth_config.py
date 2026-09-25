# SPDX-License-Identifier: GPL-3.0-only
"""Admin auth settings."""

import datetime
from dataclasses import dataclass
from typing import List, Literal, Optional

from utils import get_config_bool, get_config_list, get_configs

SameSite = Literal["strict", "lax", "none"]


@dataclass(frozen=True)
class AdminAuthSettings:
    idle_timeout: datetime.timedelta
    max_age: datetime.timedelta
    web_origins: List[str]
    cookie_samesite: SameSite
    cookie_secure: bool
    cookie_domain: Optional[str]


def load_settings() -> AdminAuthSettings:
    samesite = get_configs(
        "ADMIN_SESSION_COOKIE_SAMESITE", default_value="strict"
    ).lower()
    if samesite not in ("strict", "lax", "none"):
        raise ValueError(
            "ADMIN_SESSION_COOKIE_SAMESITE must be one of: strict, lax, none"
        )

    web_origins = [
        origin.rstrip("/") for origin in get_config_list("ADMIN_WEB_ORIGINS")
    ]
    if "*" in web_origins:
        raise ValueError(
            "ADMIN_WEB_ORIGINS must list exact origins; '*' can't carry credentials"
        )

    return AdminAuthSettings(
        idle_timeout=datetime.timedelta(
            minutes=int(get_configs("ADMIN_SESSION_IDLE_MINUTES", default_value="30"))
        ),
        max_age=datetime.timedelta(
            hours=int(get_configs("ADMIN_SESSION_MAX_HOURS", default_value="12"))
        ),
        web_origins=web_origins,
        cookie_samesite=samesite,
        # Browsers drop SameSite=None cookies that aren't Secure.
        cookie_secure=(
            get_config_bool("ADMIN_SESSION_COOKIE_SECURE", True) or samesite == "none"
        ),
        cookie_domain=get_configs("ADMIN_SESSION_COOKIE_DOMAIN") or None,
    )


settings = load_settings()
