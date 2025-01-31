import datetime
import logging
from peewee import Model, CharField, DateTimeField, IntegerField, SqliteDatabase
from db_models import Publications, database


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
    logging.info("Publications table initialized.")
    

def store_publication(country_code, platform_name, source, gateway_client, status, date_time=None):
    """
    Store a new publication entry with correct status.

    Args:
        country_code (str): Country code.
        platform_name (str): Platform name.
        source (str): Source of publication.
        gateway_client (str): Gateway client.
        status (str): "published" if successful, "failed" if not.
        date_time (datetime, optional): Timestamp. Defaults to now.
    """
    publication = Publications.create(
        country_code=country_code,
        platform_name=platform_name,
        source=source,
        status=status,
        gateway_client=gateway_client,
        date_time=date_time or datetime.datetime.now(),
    )

    if status == "published":
        logging.info("Successfully stored published message: %s", publication.__data__)
    else:
        logging.error("Failed to store message: %s", publication.__data__)

    return publication

def create_publication_entry(country_code, platform_name, source, status, gateway_client, date_time=None):
    """Create a new metric entry in the database."""
    with database.atomic():
        metric_data = {
            "country_code": country_code,
            "platform_name": platform_name,
            "source": source,
            "status": status,
            "gateway_client": gateway_client,
            "date_time": date_time or datetime.datetime.now(),
        }
        try:
            metric = Publications.create(**metric_data)
            logging.info("Metric entry created successfully: %s", metric)
            return metric
        except Exception as e:
            logging.error("Error creating metric entry: %s", e)
            raise

def get_publication(start_date, end_date, filters=None):
    """Retrieve Publications with optional filters."""
    query = Publications.select()
    
    start_datetime = datetime.datetime.combine(start_date, datetime.time.min)
    end_datetime = datetime.datetime.combine(end_date, datetime.time.max)
    
    query = query.where(Publications.date_time >= start_datetime, Publications.date_time <= end_datetime)

    if filters:
        for field, value in filters.items():
            if value is not None:
                query = query.where(getattr(Publications, field) == value)
    
    publications = list(query)
    logging.info("Retrieved %d publications from %s to %s", len(publications), start_date, end_date)
    return publications

    
if __name__ == "__main__":
    init_db()
    logging.info("Database initialization complete.")
    