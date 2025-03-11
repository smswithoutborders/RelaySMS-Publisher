"""Telegram Client"""

import os
import shutil
import json
import hashlib

from telethon import TelegramClient, functions

from telethon.errors import (
    PhoneNumberUnoccupiedError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    SessionPasswordNeededError,
    FloodWaitError,
    PasswordHashInvalidError,
    RPCError,
)
from logutils import get_logger

logger = get_logger(__name__)


class Errors:
    """
    Custom exceptions.
    """

    PhoneNumberUnoccupiedError = PhoneNumberUnoccupiedError
    PhoneCodeInvalidError = PhoneCodeInvalidError
    PhoneCodeExpiredError = PhoneCodeExpiredError
    SessionPasswordNeededError = SessionPasswordNeededError
    FloodWaitError = FloodWaitError
    PasswordHashInvalidError = PasswordHashInvalidError
    RPCError = RPCError

    class SessionExistError(Exception):
        """
        Exception raised when a duplicate session is detected.

        Args:
            message (str): An optional message to include in the exception.
                Defaults to "Duplicate sessions".

        Attributes:
            message (str): The message included in the exception.

        Methods:
            __init__(self, message="Duplicate sessions"): Initializes the S
                essionExistError object with the given message.
        """

        def __init__(self, message="Duplicate sessions"):
            self.message = message
            super().__init__(self.message)


def md5hash(data: str) -> str:
    """
    Hashes the given string using the MD5 algorithm.

    Args:
        data (str): The string to be hashed.

    Returns:
        str: The resulting MD5 hash in hexadecimal format.

    """
    try:
        return hashlib.md5(data.encode("utf-8")).hexdigest()
    except Exception as error:
        raise error


class Methods:
    """
    A collection of methods for interacting with the Telegram API.

    Args:
        identifier (str): The identifier associated with the Telegram account.

    Attributes:
        api_id (str): The API ID for the Telegram account.
        api_hash (str): The API hash for the Telegram account.
        phone_number (str): The phone number associated with the Telegram account.
        record_filepath (str): The file path for the record of the Telegram account.
        record_db_filepath (str): The file path for the database record of the Telegram account.

    Raises:
        KeyError: If the required environment variables are not set.
    """

    def __init__(self, identifier: str) -> None:
        """
        Initializes a new instance of the Methods class.

        Args:
            identifier (str): The identifier associated with the Telegram account.
        """
        credentials_path = os.environ.get("TELEGRAM_CREDENTIALS")
        records_path = os.environ.get("TELEGRAM_RECORDS")

        if not credentials_path:
            raise KeyError("TELEGRAM_CREDENTIALS environment variable not set.")
        if not records_path:
            raise KeyError("TELEGRAM_RECORDS environment variable not set.")

        if not os.path.exists(credentials_path):
            logger.warning(
                "Telegram credentials file not found at %s", credentials_path
            )

        with open(credentials_path, "r", encoding="utf-8") as file_:
            creds = json.load(file_)
            self.api_id = creds["api_id"]
            self.api_hash = creds["api_hash"]

        self.phone_number = identifier

        phone_number_hash = md5hash(data=identifier)
        self.record_filepath = os.path.join(records_path, phone_number_hash)
        self.record_db_filepath = os.path.join(self.record_filepath, phone_number_hash)

    def __write_registry__(self, phone_code_hash: str, code: str = None) -> bool:
        """
        Write phone code hash and code to registry file in JSON format.

        Args:
            phone_code_hash (str): Phone code hash to write to registry.
            code (str, optional): Code to write to registry. Defaults to None.

        Raises:
            Exception: If an error occurs while writing to registry file.

        Returns:
            bool: True if data was written successfully, False otherwise.
        """
        try:
            # Create dictionary with data to write to registry
            data = {"code": code, "phone_code_hash": phone_code_hash}

            # Convert dictionary to JSON format
            json_data = json.dumps(data)

            # Write JSON data to registry file
            registry_filepath = os.path.join(self.record_filepath, "registry.json")
            with open(registry_filepath, "w", encoding="utf-8") as outfile:
                outfile.write(json_data)

            return True

        except Exception as error:
            logger.error("An error occurred while writting registry file.")
            raise error

    def __read_registry__(self) -> dict:
        """Read the user registry file and return the contents as a dictionary."""

        try:
            registry_filepath = os.path.join(self.record_filepath, "registry.json")

            with open(registry_filepath, "r", encoding="utf-8") as file_:
                json_content = json.load(file_)

            os.remove(registry_filepath)
            logger.debug("- removed user registry file: %s", registry_filepath)

            return json_content

        except Exception as error:
            logger.error("An error occurred while reading registry file.")
            raise error

    async def authorize(self) -> None:
        """Connects to the Telegram API, creates a user file, and sends an
        authorization code request to the specified phone number.

        Args:
            self: An instance of the Methods class.

        Returns:
            None.
        """

        # Check if user file already exists and create it if not
        if not os.path.exists(self.record_filepath):
            logger.debug("- creating user file: %s", self.record_filepath)
            os.makedirs(self.record_filepath)

        else:
            logger.debug(
                "deleting draft record '%s' and deps ...", self.record_filepath
            )
            shutil.rmtree(self.record_filepath)

            logger.debug("- creating user file: %s", self.record_filepath)
            os.makedirs(self.record_filepath)

        # Initialize Telethon client and connect to API
        client = TelegramClient(
            self.record_db_filepath, api_id=self.api_id, api_hash=self.api_hash
        )

        try:
            # open telethon connection
            await client.connect()

            # Check if session already exists
            if await client.is_user_authorized():
                logger.error("Session already exists")
                raise Errors.SessionExistError()

            # Send authorization code request and write phone_code_hash to registry
            result = await client.send_code_request(phone=self.phone_number)
            self.__write_registry__(phone_code_hash=result.phone_code_hash)
            logger.info("- authentication code sent successfully.")

        except FloodWaitError as error:
            raise error

        except Exception as error:
            logger.error("An error occurred while authorizing.")
            raise error

        finally:
            # close telethon connection
            await client.disconnect()

    async def validate(self, code: str) -> dict:
        """Validate the given phone number confirmation code.

        Args:
            code (str): The phone number confirmation code to validate.

        Returns:
            dict: A dictionary containing the user's token and profile information.
        """
        # Check if user file already exists and create it if not
        if not os.path.exists(self.record_filepath):
            logger.debug("- creating user file: %s", self.record_filepath)
            os.makedirs(self.record_filepath)

        # Initialize Telethon client and connect to API
        client = TelegramClient(
            self.record_db_filepath, api_id=self.api_id, api_hash=self.api_hash
        )

        try:
            # open telethon connection
            await client.connect()

            registry_data = self.__read_registry__()

            # validate code
            await client.sign_in(
                self.phone_number,
                code=code,
                phone_code_hash=registry_data["phone_code_hash"],
            )
            logger.info("- Code validation successful")

            # get user profile info
            logger.debug("Fetching user's info ...")
            user_data = await client.get_me()

            return {
                "token": self.phone_number,
                "profile": {
                    "name": user_data.first_name,
                    "unique_id": self.phone_number,
                },
            }

        except PhoneNumberUnoccupiedError as error:
            logger.error("%s has no account", self.phone_number)
            raise error

        except PhoneCodeInvalidError as error:
            logger.error("The phone code entered was invalid")
            self.__write_registry__(phone_code_hash=registry_data["phone_code_hash"])
            raise error

        except PhoneCodeExpiredError as error:
            logger.error("The confirmation code has expired")
            raise error

        except SessionPasswordNeededError as error:
            logger.error("two-steps verification is enabled and a password is required")
            self.__write_registry__(
                code=code, phone_code_hash=registry_data["phone_code_hash"]
            )
            raise error

        except FloodWaitError as error:
            wait_time = error.seconds
            logger.error(
                "Flood wait error occurred. Please try again in %s seconds.", wait_time
            )
            raise error

        except Exception as error:
            logger.error("An error occurred while validating.")
            raise error

        finally:
            # close telethon connection
            await client.disconnect()

    async def message(self, recipient: str, text: str) -> bool:
        """
        Sends a message to a recipient using the Telegram API.

        Args:
            recipient (str): The username or phone number of the recipient.
            text (str): The text of the message to send.

        Returns:
            bool: True if the message was sent successfully, False otherwise.
        """
        # Initialize Telethon client and connect to API
        client = TelegramClient(
            self.record_db_filepath, api_id=self.api_id, api_hash=self.api_hash
        )

        try:
            # open telethon connection
            await client.connect()

            # sent message
            logger.debug("sending message to: %s...", recipient)
            await client.send_message(recipient, text)

        except Exception as error:
            logger.error("An error occurred while sending a telegram message.")
            raise error

        finally:
            # close telethon connection
            await client.disconnect()

    async def invalidate(self, token: str) -> bool:
        """
        Revokes access for a Telegram user by logging them out and deleting their local data.

        Args:
            token (str): The user's access token.

        Returns:
            bool: True if access was revoked successfully, False otherwise.
        """
        phone_number_hash = md5hash(data=token)
        self.record_filepath = os.path.join(
            os.environ["TELEGRAM_RECORDS"], phone_number_hash
        )
        self.record_db_filepath = os.path.join(self.record_filepath, phone_number_hash)

        # Initialize Telethon client and connect to API
        client = TelegramClient(
            self.record_db_filepath, api_id=self.api_id, api_hash=self.api_hash
        )

        try:
            # open telethon connection
            await client.connect()

            # revoke access
            logger.debug("revoking %s access ...", self.phone_number)
            await client.log_out()

            # delete files
            logger.debug("deleting files ...")
            shutil.rmtree(self.record_filepath)

            logger.info("- Successfully revoked access")
            return True

        except Exception as error:
            logger.error("An error occurred while invalidating.\n\n%s", str(error))
            return False

        finally:
            # close telethon connection
            await client.disconnect()

    async def validate_with_password(self, password: str) -> dict:
        """Validate the given phone number confirmation code with password.

        Args:
            password (str): The user's password.

        Returns:
            dict: A dictionary containing the user's token and profile information.
        """
        # Initialize Telethon client and connect to API
        client = TelegramClient(
            self.record_db_filepath, api_id=self.api_id, api_hash=self.api_hash
        )

        try:
            # open telethon connection
            await client.connect()

            registry_data = self.__read_registry__()

            # validate code with password
            await client.sign_in(
                password=password,
                phone_code_hash=registry_data["phone_code_hash"],
            )

            logger.info("- Code validation with password successful")

            # get user profile info
            logger.debug("Fetching user's info ...")
            user_data = await client.get_me()

            # Return user profile info and token
            return {
                "token": self.phone_number,
                "profile": {
                    "name": user_data.first_name,
                    "unique_id": self.phone_number,
                },
            }

        except PhoneNumberUnoccupiedError as error:
            logger.error("%s has no account", self.phone_number)
            raise error

        except PasswordHashInvalidError as error:
            logger.error("The password (and thus its hash value) entered is invalid")
            self.__write_registry__(phone_code_hash=registry_data["phone_code_hash"])
            raise error

        except FloodWaitError as error:
            wait_time = error.seconds
            logger.error(
                "Flood wait error occurred. Please try again in %s seconds.", wait_time
            )
            raise error

        except Exception as error:
            logger.error("An error occurred while validating with password")
            raise error

        finally:
            # close telethon connection
            await client.disconnect()

    async def contacts(self) -> list:
        """Fetches all telegram contacts.

        Returns:
            A list of dictionaries containing the following keys:
            - id (int): The unique identifier of the contact
            - phone (str): The phone number of the contact
            - username (str): The username of the contact (if available)
            - first_name (str): The first name of the contact
            - last_name (str): The last name of the contact (if available)
        """
        # Initialize Telethon client and connect to API
        client = TelegramClient(
            self.record_db_filepath, api_id=self.api_id, api_hash=self.api_hash
        )

        try:
            # open telethon connection
            await client.connect()

            # fetch telegram contacts
            contacts = []

            logger.debug("Fetching telegram contacts for %s ...", self.phone_number)
            result = await client(functions.contacts.GetContactsRequest(hash=0))
            for user in result.users:
                contacts.append(
                    {
                        "id": user.id,
                        "phone": user.phone,
                        "username": user.username,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                    }
                )

            logger.info("- Successfully fetched all telegram contacts")

            return contacts

        except Exception as error:
            logger.error("An error occurred while fetching contacts.")
            raise error

        finally:
            # close telethon connection
            await client.disconnect()
