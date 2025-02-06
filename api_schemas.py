"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

from pydantic import BaseModel
import datetime
from typing import Optional

class PublicationsCreate(BaseModel):
    country_code: str
    platform_name: str
    source: str
    status: str
    gateway_client: str
    date_time: Optional[datetime.datetime] = None

class PublicationsRead(PublicationsCreate):
    id: int
