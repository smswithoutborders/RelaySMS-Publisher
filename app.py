# SPDX-License-Identifier: GPL-3.0-only

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api_v1 import router
from db import dispose_engine
from platforms.adapter_manager import AdapterManager
from server_identity_keys import initialize_server_identity_keys


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    initialize_server_identity_keys()
    AdapterManager._populate_registry()
    yield
    dispose_engine()


app = FastAPI(lifespan=lifespan)
app.include_router(router, prefix="/v1")
