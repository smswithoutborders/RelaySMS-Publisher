# SPDX-License-Identifier: GPL-3.0-only


class PlatformAwareError(Exception):
    """Base for exceptions that may know which platform they occurred on."""

    def __init__(self, message: str, *, platform_name: str | None = None):
        super().__init__(message)
        self.platform_name = platform_name
