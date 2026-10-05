# SPDX-License-Identifier: GPL-3.0-only
"""Publisher v3 servicer."""

from grpc_services.interceptors import request_payload
from grpc_services.v3.exchange_oauth2_code import exchange_oauth2_code_and_store
from grpc_services.v3.exchange_pnba_code import exchange_pnba_code_and_store
from grpc_services.v3.get_oauth2_auth_url import get_oauth2_authorization_url
from grpc_services.v3.get_pnba_code import get_pnba_code
from grpc_services.v3.revoke_oauth2_token import revoke_oauth2_token
from grpc_services.v3.revoke_pnba_token import revoke_pnba_token
from grpc_services.v3.sync_keys import sync_keys
from platforms.adapter_manager import AdapterManager
from protos.v3 import publisher_pb2_grpc


class PublisherServicerV3(publisher_pb2_grpc.PublisherServicer):
    def __init__(self, adapter_manager: AdapterManager):
        self.adapter_manager = adapter_manager

    def GetOAuth2AuthorizationUrl(self, request, context):
        return get_oauth2_authorization_url(request, self.adapter_manager)

    def ExchangeOAuth2CodeAndStore(self, request, context):
        return exchange_oauth2_code_and_store(request, self.adapter_manager)

    def RevokeOAuth2Token(self, request, context):
        return revoke_oauth2_token(request, request_payload(), self.adapter_manager)

    def GetPNBACode(self, request, context):
        return get_pnba_code(request, self.adapter_manager)

    def ExchangePNBACodeAndStore(self, request, context):
        return exchange_pnba_code_and_store(request, self.adapter_manager)

    def RevokePNBAToken(self, request, context):
        return revoke_pnba_token(request, request_payload(), self.adapter_manager)

    def SyncKeys(self, request, context):
        return sync_keys(request, request_payload())
