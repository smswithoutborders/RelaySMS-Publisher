"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import os
import logging
from peewee import MySQLDatabase, SqliteDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

DB_TYPE = os.getenv("DB_TYPE", "sqlite").lower()

if DB_TYPE == "mysql":
    DATABASE_CONFIG = {
        "database": os.getenv("MYSQL_DB", "your_database"),
        "user": os.getenv("MYSQL_USER", "your_user"),
        "password": os.getenv("MYSQL_PASSWORD", "your_password"),
        "host": os.getenv("MYSQL_HOST", "localhost"),
        "port": int(os.getenv("MYSQL_PORT", 3306)),
    }
    database = MySQLDatabase(**DATABASE_CONFIG)
    logging.info("Using MySQL Database.")
else:
    DATABASE_PATH = os.getenv("SQLITE_PATH", "./metrics.db")
    database = SqliteDatabase(DATABASE_PATH)
    logging.info(f"Using SQLite Database at {DATABASE_PATH}.")
