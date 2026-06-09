# SPDX-License-Identifier: GPL-3.0-only
"""Shared utilities for V3 gRPC service handlers."""

from platforms.adapter_manager import AdapterManager


def get_oauth2_adapter(platform: str) -> dict:
    """Resolve the OAuth2 adapter for a platform, raising NotImplementedError if unsupported."""
    adapter = AdapterManager.get_adapter_path(name=platform.lower(), protocol="oauth2")
    if not adapter:
        raise NotImplementedError(
            f"Platform '{platform.lower()}' with protocol 'oauth2' is not supported. "
            "Contact the developers for implementation status."
        )
    return adapter
