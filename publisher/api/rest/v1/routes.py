# SPDX-License-Identifier: GPL-3.0-only

from fastapi import APIRouter

from publisher.api.rest.v1 import (
    auth,
    creds,
    gateway_clients,
    platforms,
    publications,
    server_keys,
    stats,
)

router = APIRouter()
# The docs sidebar lists tags in this order.
for module in (
    auth,
    creds,
    stats,
    publications,
    platforms,
    gateway_clients,
    server_keys,
):
    router.include_router(module.router)
