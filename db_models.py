"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import datetime
from peewee import Model, CharField, DateTimeField, IntegerField
from db import connect
from utils import create_tables

database = connect()


class Publications(Model):
    """Model representing the Publications Table."""

    country_code = CharField(null=True)
    platform_name = CharField()
    source = CharField()
    status = CharField()
    gateway_client = CharField(null=True)
    date_created = DateTimeField(default=datetime.datetime.now)

    class Meta:
        """Meta class to define database connection and table name."""

        database = database
        table_name = "publications"


create_tables([Publications])
