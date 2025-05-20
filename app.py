"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

from fastapi import FastAPI
from api_v1 import router
from platforms.adapter_manager import AdapterManager

app = FastAPI()

app.include_router(router, prefix="/v1")

AdapterManager._populate_registry()
