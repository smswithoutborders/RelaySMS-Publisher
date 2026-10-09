# SPDX-License-Identifier: GPL-3.0-only

import json
import logging
from typing import override

from relaysms_adapter_sdk import (
    Account,
    AuthenticationError,
    CodeRequest,
    CodeSent,
    CodeVerificationRequest,
    InvalidParamsError,
    PNBAAdapter,
    RevokeRequest,
    SendRequest,
    SendResult,
    config_dir,
    state_dir,
)

logger = logging.getLogger(__name__)


class EchoAdapter(PNBAAdapter):
    def __init__(self) -> None:
        settings = json.loads((config_dir() / "credentials.json").read_text())
        self.code = settings["code"]

    @override
    def send_code(self, request: CodeRequest) -> CodeSent:
        logger.info("Code for %s is %s", request.phone_number, self.code)
        return CodeSent(message="Code sent.")

    @override
    def verify_code(self, request: CodeVerificationRequest) -> Account:
        if request.code != self.code:
            raise AuthenticationError("Wrong code.")
        return Account(
            identifier=request.phone_number, token={"number": request.phone_number}
        )

    @override
    def send_message(self, request: SendRequest) -> SendResult:
        if request.account is None:
            raise InvalidParamsError("Echo sends only from a linked account.")
        with (state_dir() / "outbox.jsonl").open("a", encoding="utf-8") as outbox:
            entry = {"from": request.account.identifier, "body": request.message.body}
            outbox.write(json.dumps(entry) + "\n")
        return SendResult()

    @override
    def revoke(self, request: RevokeRequest) -> None:
        logger.info("Unlinked %s", request.account.identifier)
