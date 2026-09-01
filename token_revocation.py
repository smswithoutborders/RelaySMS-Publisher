# SPDX-License-Identifier: GPL-3.0-only

from models.token import Token
from platforms.adapter_ipc_handler import AdapterIPCHandler
from platforms.adapter_manager import AdapterManager


def revoke_oauth2_token_upstream(
    token: Token, adapter_manager: AdapterManager
) -> str | None:
    """Revokes an OAuth2 token."""
    adapter = adapter_manager.get_oauth2_adapter(token.platform)
    pipe = AdapterIPCHandler.invoke(
        adapter_path=adapter.path,
        venv_path=adapter.venv_path,
        method="revoke_token",
        params={
            "token": token.token_data["token"],
            "base_path": adapter.assets_path,
        },
    )
    return pipe.get("error")


def revoke_pnba_token_upstream(
    token: Token, adapter_manager: AdapterManager
) -> str | None:
    """Invalidates a PNBA session."""
    adapter = adapter_manager.get_pnba_adapter(token.platform)
    pipe = AdapterIPCHandler.invoke(
        adapter_path=adapter.path,
        venv_path=adapter.venv_path,
        method="invalidate_session",
        params={
            "phone_number": token.token_data["account_id"],
            "session": token.token_data["token"],
            "base_path": adapter.assets_path,
        },
    )
    return pipe.get("error")
