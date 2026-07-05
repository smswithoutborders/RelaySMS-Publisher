# SPDX-License-Identifier: GPL-3.0-only

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from db import dispose_engine
from keys import initialize_server_identity_keys
from platforms.adapter_manager import AdapterManager
from rest_services.v1.routes import router as v1_router
from utils import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    initialize_server_identity_keys()
    app.state.adapter_manager = AdapterManager()
    yield
    dispose_engine()


app = FastAPI(lifespan=lifespan)
app.include_router(v1_router, prefix="/v1")


def _bad_request_handler(request: Request, exc: Exception):
    logger.error("request: %s, error: %s", request.url.path, str(exc))
    return JSONResponse(status_code=400, content={"error": str(exc)})


app.add_exception_handler(ValueError, _bad_request_handler)
app.add_exception_handler(NotImplementedError, _bad_request_handler)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception(exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Something went wrong. Please try again later."},
    )
