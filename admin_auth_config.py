# SPDX-License-Identifier: GPL-3.0-only
"""Admin auth settings."""

import datetime
from dataclasses import dataclass
from typing import List

from utils import get_config_bool, get_config_list, get_configs


@dataclass(frozen=True)
class AdminAuthSettings:
    idle_timeout: datetime.timedelta
    max_age: datetime.timedelta
    web_origins: List[str]
    cookie_secure: bool


def load_settings() -> AdminAuthSettings:
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
        cookie_secure=get_config_bool("ADMIN_SESSION_COOKIE_SECURE", True),
    )


settings = load_settings()
