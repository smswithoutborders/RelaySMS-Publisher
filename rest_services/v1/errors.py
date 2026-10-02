# SPDX-License-Identifier: GPL-3.0-only

from typing import Optional

from fastapi import HTTPException


class ApiError(HTTPException):
    """An HTTP error with a client-facing message and extra detail for the log."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        log: Optional[str] = None,
    ):
        super().__init__(status_code=status_code, detail=message)
        self.log = log
