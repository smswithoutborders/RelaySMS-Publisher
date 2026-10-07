# SPDX-License-Identifier: GPL-3.0-only
"""Base error for the publisher's domain code."""


class PublisherError(Exception):
    """Base for domain errors; platform_name is set when the platform is known."""

    def __init__(self, message: str, *, platform_name: str | None = None):
        super().__init__(message)
        self.platform_name = platform_name
