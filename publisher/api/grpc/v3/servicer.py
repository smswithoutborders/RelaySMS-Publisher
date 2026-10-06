# SPDX-License-Identifier: GPL-3.0-only
"""Publisher v3 servicer."""

from typing import override

from protos.v3 import publisher_pb2_grpc
from publisher.api.grpc.interceptors import request_payload
from publisher.api.grpc.v3.exchange_oauth2_code import exchange_oauth2_code_and_store
from publisher.api.grpc.v3.exchange_pnba_code import exchange_pnba_code_and_store
from publisher.api.grpc.v3.get_oauth2_auth_url import get_oauth2_authorization_url
from publisher.api.grpc.v3.get_pnba_code import get_pnba_code
from publisher.api.grpc.v3.revoke_oauth2_token import revoke_oauth2_token
from publisher.api.grpc.v3.revoke_pnba_token import revoke_pnba_token
from publisher.api.grpc.v3.sync_keys import sync_keys


class PublisherServicerV3(publisher_pb2_grpc.PublisherServicer):
    @override
    def GetOAuth2AuthorizationUrl(self, request, context):
        return get_oauth2_authorization_url(request)

    @override
    def ExchangeOAuth2CodeAndStore(self, request, context):
        return exchange_oauth2_code_and_store(request)

    @override
    def RevokeOAuth2Token(self, request, context):
        return revoke_oauth2_token(request, request_payload())

    @override
    def GetPNBACode(self, request, context):
        return get_pnba_code(request)

    @override
    def ExchangePNBACodeAndStore(self, request, context):
        return exchange_pnba_code_and_store(request)

    @override
    def RevokePNBAToken(self, request, context):
        return revoke_pnba_token(request, request_payload())

    @override
    def SyncKeys(self, request, context):
        return sync_keys(request, request_payload())
