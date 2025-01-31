"""Peewee Database ORM Models."""

import datetime
from peewee import (
    Model,
    CharField,
    DateTimeField,
    IntegerField,
    SqliteDatabase,
)
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DATABASE_PATH = "./metrics.db" 
database = SqliteDatabase(DATABASE_PATH)

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
    database.connect()
    database.create_tables([Publications], safe=True)
    logging.info("Database and table initialized.")


if __name__ == "__main__":
    init_db()
