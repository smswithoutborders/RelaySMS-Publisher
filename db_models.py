"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import datetime
from peewee import Model, CharField, DateTimeField, IntegerField
from db import database  
import logging

logging.basicConfig(level=logging.INFO)

class Publications(Model):
    """Model representing the Publications Table."""

    id = IntegerField(primary_key=True) 
    country_code = CharField() 
    platform_name = CharField() 
    source = CharField()  
    status = CharField() 
    gateway_client = CharField()  
    date_time = DateTimeField(default=datetime.datetime.now) 

    class Meta:
        """Meta class to define database connection and table name."""
        database = database
        table_name = "publications"

def init_db():
    """Create the database and the publications table if they don't exist."""
    database.create_tables([Publications], safe=True)
    logging.info("Database and table initialized.")
