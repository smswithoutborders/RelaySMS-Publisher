# SPDX-License-Identifier: GPL-3.0-only

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from publisher import keys
from publisher.config import ApiDocsConfig, AuthConfig
from publisher.db import dispose_engine, get_session
from publisher.gateway_clients.manager import GatewayClientManager
from publisher.log import setup_logging
from publisher.platforms.manager import AdapterManager
from rest_services.v1.routes import router as v1_router

logger = logging.getLogger(__name__)

# Query and path values are already in the URL; body values can be secrets.
ECHOED_INPUT_LOCATIONS = frozenset({"query", "path"})
MAX_ECHOED_INPUT_LENGTH = 50

API_DOCS_PAGE = Path(__file__).parent / "docs" / "api.html"
API_DOCS_CSP = (
    "default-src 'none'; script-src https://cdn.jsdelivr.net; "
    "style-src 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; "
    "connect-src 'self'"
)


def _validation_message(error: dict) -> str:
    message = f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
    if error["loc"][0] in ECHOED_INPUT_LOCATIONS and error["type"] != "missing":
        value = str(error["input"])
        if len(value) > MAX_ECHOED_INPUT_LENGTH:
            value = value[:MAX_ECHOED_INPUT_LENGTH] + "..."
        # repr quotes and escapes control characters, so logs stay one line.
        message += f", got {value!r}"
    return message


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    with get_session() as db:
        keys.initialize_server_identity_keys(db)

    app.state.adapter_manager = AdapterManager()
    app.state.gateway_client_manager = GatewayClientManager()
    yield
    dispose_engine()


def configure_cors(app: FastAPI, settings: AuthConfig) -> None:
    if not settings.web_origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "If-Match"],
        expose_headers=["ETag", "Location"],
        max_age=600,
    )


setup_logging()
api_docs_enabled = ApiDocsConfig.get().enabled
app = FastAPI(
    title="RelaySMS Publisher",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json" if api_docs_enabled else None,
)
app.include_router(v1_router, prefix="/v1")
configure_cors(app, AuthConfig.get())


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Apply baseline security headers to every response."""
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", "default-src 'none'")
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


if api_docs_enabled:

    @app.get("/docs", include_in_schema=False)
    def api_docs():
        return FileResponse(
            API_DOCS_PAGE, headers={"Content-Security-Policy": API_DOCS_CSP}
        )


@app.get("/health", tags=["Health"], summary="Health check")
def health():
    """Liveness and readiness for uptime monitoring."""
    with get_session() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}


def _bad_request_handler(request: Request, exc: Exception):
    logger.error("request: %s, error: %s", request.url.path, str(exc))
    return JSONResponse(status_code=400, content={"error": str(exc)})


app.add_exception_handler(ValueError, _bad_request_handler)
app.add_exception_handler(NotImplementedError, _bad_request_handler)


@app.exception_handler(StarletteHTTPException)
def http_error_handler(request: Request, exc: StarletteHTTPException):
    log = getattr(exc, "log", None)
    logger.error(
        "request: %s, error: %s%s",
        request.url.path,
        exc.detail,
        f" ({log})" if log else "",
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
def validation_error_handler(request: Request, exc: RequestValidationError):
    error = "; ".join(_validation_message(e) for e in exc.errors())
    logger.error("request: %s, error: %s", request.url.path, error)
    return JSONResponse(status_code=422, content={"error": error})


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Something went wrong. Please try again later."},
    )
