# SPDX-License-Identifier: GPL-3.0-only
"""An OAuth2 adapter whose authorization URL redirects straight back with a code."""

from urllib.parse import urlencode

from relaysms_adapter_sdk import (
    Account,
    AuthorizationRequest,
    AuthorizationUrl,
    CodeExchangeRequest,
    OAuth2Adapter,
    RevokeRequest,
    SendRequest,
    SendResult,
)


class FakeOAuth2Adapter(OAuth2Adapter):
    def create_authorization_url(self, request: AuthorizationRequest):
        redirect_url = request.redirect_url or "https://example.com/cb"
        query = urlencode({"code": "the-code", "state": "s1"})
        return AuthorizationUrl(
            url=f"{redirect_url}?{query}",
            state="s1",
            code_verifier="v1",
            redirect_url=redirect_url,
        )

    def exchange_code(self, request: CodeExchangeRequest):
        return Account(
            identifier=f"{request.code}/{request.code_verifier}",
            token={"n": 1},
        )

    def send_message(self, request: SendRequest):
        return SendResult(token={"n": 2})

    def revoke(self, request: RevokeRequest):
        return None
