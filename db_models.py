"""Peewee Database ORM Models."""

import datetime
from peewee import (
    Model,
    CharField,
    DateTimeField,
    IntegerField,
    SqliteDatabase,
)
from playhouse.migrate import SqliteMigrator, migrate

# Database connection
DATABASE_PATH = "./metrics.db"  # SQLite database file
database = SqliteDatabase(DATABASE_PATH)


class Metrics(Model):
    """Model representing the Metrics Table."""

    id = IntegerField(primary_key=True)  # Auto-incrementing ID
    country_code = CharField()  # Country code
    platform_name = CharField()  # Platform name
    source = CharField()  # Source (bridge or platform)
    status = CharField()  # Status (failed or published)
    gateway_client = CharField()  # Gateway client
    date_time = DateTimeField(default=datetime.datetime.now)  # Date & time

    class Meta:
        """Meta class to define database connection and table name."""
        database = database
        table_name = "metrics"


# Function to initialize the database
def init_db():
    """Create the database and the metrics table if they don't exist."""
    database.connect()
    database.create_tables([Metrics], safe=True)
    print("Database and table initialized.")


# Example migration logic (if needed in the future)
def migrate_db():
    """Perform migrations if the schema changes."""
    migrator = SqliteMigrator(database)
    # Example: Add a new column if needed
    # migrate(migrator.add_column('metrics', 'new_column', CharField(null=True)))
    print("Database migration completed.")


# Initialize the database when the script is run
if __name__ == "__main__":
    init_db()
