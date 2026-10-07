# SPDX-License-Identifier: GPL-3.0-only


from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

ERROR_RESPONSE_REF = "#/components/schemas/ErrorResponse"


class ApiError(HTTPException):
    """An HTTP error with a client-facing message and extra detail for the log."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        log: str | None = None,
    ):
        super().__init__(status_code=status_code, detail=message)
        self.log = log


class ErrorResponse(BaseModel):
    """The body of every error response."""

    error: str = Field(..., description="What went wrong, safe to show to users.")


def error_responses(*groups: dict[int, str]) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses` for status code to description pairs."""
    return {
        code: {"model": ErrorResponse, "description": description}
        for group in groups
        for code, description in group.items()
    }


def error_response_spec(description: str) -> dict[str, Any]:
    """An error response as it appears in the generated spec."""
    return {
        "description": description,
        "content": {"application/json": {"schema": {"$ref": ERROR_RESPONSE_REF}}},
    }


IF_MATCH_ERRORS = {
    412: "If-Match isn't the current ETag: it changed since you loaded it. Reload "
    "and try again.",
    428: "No If-Match header. Send the ETag from the last GET.",
}
PAGE_QUERY_ERRORS = {400: "An invalid cursor, or 'since' not before 'until'."}
CONCURRENT_CHANGE = {
    409: "Changed by another request at the same moment. Reload and try again."
}
