# SPDX-License-Identifier: GPL-3.0-only

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

import admin_auth_config
from db import dispose_engine, get_session
from gateway_clients.gateway_client_manager import GatewayClientManager
from keys import KeyManager
from platforms.adapter_manager import AdapterManager
from rest_services.v1 import auth as admin_auth
from rest_services.v1.routes import router as v1_router
from utils import get_logger

logger = get_logger(__name__)

# Query and path values are already in the URL; body values can be secrets.
ECHOED_INPUT_LOCATIONS = frozenset({"query", "path"})
MAX_ECHOED_INPUT_LENGTH = 50


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
        key_manager = KeyManager(session=db)
        key_manager.initialize_server_identity_keys()

    app.state.adapter_manager = AdapterManager()
    app.state.gateway_client_manager = GatewayClientManager()
    yield
    dispose_engine()


def configure_cors(app: FastAPI, settings: admin_auth_config.AdminAuthSettings) -> None:
    if not settings.web_origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", admin_auth.CSRF_HEADER_NAME],
        max_age=600,
    )


app = FastAPI(lifespan=lifespan)
app.include_router(v1_router, prefix="/v1")
configure_cors(app, admin_auth_config.settings)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Apply baseline security headers to every response."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/health")
def health():
    """Liveness/readiness check for uptime monitoring."""
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
    logger.error("request: %s, error: %s", request.url.path, exc.detail)
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
    logger.exception(exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Something went wrong. Please try again later."},
    )
