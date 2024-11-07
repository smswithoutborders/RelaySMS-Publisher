"""
OAuth2 Client Module.
"""

import os
import logging
import base64
import math
import textwrap
import json
import datetime
from authlib.integrations.requests_client import OAuth2Session
from authlib.integrations.base_client import OAuthError
import sentry_sdk

from utils import get_configs

OAUTH2_CONFIGURATIONS = {
    "gmail": {
        "urls": {
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "userinfo_uri": "https://www.googleapis.com/oauth2/v3/userinfo",
            "send_message_uri": "https://www.googleapis.com/gmail/v1/users/{}/messages/send",
            "revoke_uri": "https://oauth2.googleapis.com/revoke",
        },
        "default_params": {
            "scope": [
                "openid",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/userinfo.profile",
                "https://www.googleapis.com/auth/userinfo.email",
            ],
            "access_type": "offline",
            "prompt": "consent",
        },
    },
    "twitter": {
        "urls": {
            "auth_uri": "https://twitter.com/i/oauth2/authorize",
            "token_uri": "https://api.twitter.com/2/oauth2/token",
            "userinfo_uri": "https://api.twitter.com/2/users/me",
            "send_message_uri": "https://api.twitter.com/2/tweets",
            "revoke_uri": "https://api.twitter.com/2/oauth2/revoke",
        },
        "default_params": {
            "scope": ["tweet.write", "users.read", "tweet.read", "offline.access"]
        },
    },
}

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_credentials(platform_name):
    """
    Load client credentials from a JSON file specified in environment variables.

    Args:
        platform_name (str): The name of the platform (e.g., 'gmail').

    Returns:
        dict: A dictionary containing client_id, client_secret, and redirect_uri.
    """
    creds_file = get_configs(f"{platform_name.upper()}_CREDENTIALS")

    if not creds_file:
        raise ValueError(
            f"Missing environment variable for {platform_name.upper()}_CREDENTIALS"
        )

    with open(creds_file, "r", encoding="utf-8") as file:
        creds = json.load(file)

    def find_nested_credentials(data):
        for key, value in data.items():
            if isinstance(value, dict):
                nested_creds = find_nested_credentials(value)
                if nested_creds:
                    return nested_creds
            elif key in ["client_id", "client_secret", "redirect_uri", "redirect_uris"]:
                return data
        return None

    creds_data = find_nested_credentials(creds)
    if not creds_data:
        raise ValueError(
            f"Credentials not found in the JSON file for platform: {platform_name}"
        )

    required_fields = {
        "client_id": creds_data.get("client_id"),
        "client_secret": creds_data.get("client_secret"),
        "redirect_uris": creds_data.get("redirect_uris", []),
    }

    redirect_uri = required_fields["redirect_uris"][0]

    return {
        "client_id": required_fields["client_id"],
        "client_secret": required_fields["client_secret"],
        "redirect_uri": redirect_uri,
    }


class OAuth2Client:
    """
    OAuth2 client implementation using Authlib.
    """

    def __init__(self, platform_name, token=None, update_token=None):
        """
        Initialize the OAuth2Client.

        Args:
            platform_name (str): The name of the platform (e.g., 'gmail', 'twitter').
            token (dict, optional): The OAuth 2.0 token containing 'access_token',
                'refresh_token', 'expires_at', and other relevant token information.
                Default is None.
            update_token (callable, optional): A callable function that updates the
                OAuth 2.0 token. Used when refreshing tokens. Default is None.
        """
        oauth2_config = OAUTH2_CONFIGURATIONS.get(platform_name.lower())

        if not oauth2_config:
            raise ValueError(f"Configuration for platform '{platform_name}' not found.")

        if token and not self._is_token_format_correct(token):
            logger.info("Token format is incorrect. Converting token format...")
            token = self._convert_token_format(token)

        self.platform = platform_name
        self.creds = load_credentials(self.platform)
        self.urls = oauth2_config["urls"]
        self.default_params = oauth2_config["default_params"]
        self.session = OAuth2Session(
            client_id=self.creds["client_id"],
            client_secret=self.creds["client_secret"],
            redirect_uri=self.creds["redirect_uri"],
            token_endpoint=self.urls["token_uri"],
            token=token,
            update_token=update_token,
        )

    def _is_token_format_correct(self, token):
        """
        Check if the token is already in the correct format.

        Args:
            token (dict): The token credentials.

        Returns:
            bool: True if the token is in the correct format, False otherwise.
        """
        required_keys = {"access_token", "token_type", "expires_at", "refresh_token"}
        return required_keys.issubset(token.keys())

    def _convert_token_format(self, old_format_token):
        """
        Convert token credentials from one format to another.

        Args:
            old_format_token (dict): The original token credentials.

        Returns:
            dict: The converted token credentials in the new format.
        """
        access_token = old_format_token.get("token")
        refresh_token = old_format_token.get("refresh_token")
        scope = " ".join(old_format_token.get("scopes", []))
        expiry_time = old_format_token.get("expiry")

        if expiry_time:
            expiry_datetime = datetime.datetime.fromisoformat(
                expiry_time.replace("Z", "+00:00")
            )
            expires_at = int(expiry_datetime.timestamp())
        else:
            expires_at = None

        new_format_token = {
            "access_token": access_token,
            "expires_in": 3599,
            "scope": scope,
            "token_type": "Bearer",
            "id_token": "",
            "expires_at": expires_at,
            "refresh_token": refresh_token,
        }

        return new_format_token

    @staticmethod
    def generate_code_verifier(length=128):
        """
        Generate a code verifier for PKCE.

        Args:
            length (int, optional): Length of the code verifier. Default is 128.

        Returns:
            str: The generated code verifier.
        """
        code_verifier = base64.urlsafe_b64encode(os.urandom(length)).decode("utf-8")
        return "".join(c for c in code_verifier if c.isalnum())

    def get_authorization_url(self, autogenerate_code_verifier=False, **kwargs):
        """
        Get the authorization URL.

        Args:
            autogenerate_code_verifier (bool, optional): Whether to auto-generate
                a code verifier for PKCE. Default is False.
            **kwargs: Additional parameters to include in the authorization URL.

        Returns:
            tuple: A tuple containing:
                - authorization_url (str): The generated authorization URL.
                - state (str): The state parameter for CSRF protection.
                - code_verifier (str or None): The generated code verifier for PKCE if
                applicable, otherwise None.
                - client_id (str): The client ID for the OAuth2 application.
                - scope (str): The scope of the authorization request, as a
                    comma-separated string.
                - redirect_uri (str): The redirect URI for the OAuth2 application.
        """
        code_verifier = kwargs.get("code_verifier")

        if autogenerate_code_verifier and not code_verifier:
            code_verifier = self.generate_code_verifier(48)
            kwargs["code_verifier"] = code_verifier
            self.session.code_challenge_method = "S256"

        if code_verifier:
            kwargs["code_verifier"] = code_verifier
            self.session.code_challenge_method = "S256"

        params = {**self.default_params, **kwargs}

        authorization_url, state = self.session.create_authorization_url(
            self.urls["auth_uri"], **params
        )

        logger.info("Authorization URL generated: %s", authorization_url)
        return (
            authorization_url,
            state,
            code_verifier,
            self.creds["client_id"],
            ",".join(self.default_params["scope"]),
            self.session.redirect_uri,
        )

    def fetch_token(self, code, **kwargs):
        """
        Fetch the access token using the authorization code.

        Args:
            code (str): The authorization code.
            **kwargs: Additional parameters for fetching the token.

        Returns:
            tuple: A tuple containing:
                - The token response.
                - scope (list): The scope of the authorization request.
        """
        logger.debug("Fetching access token...")
        token_response = self.session.fetch_token(
            self.urls["token_uri"], code=code, **kwargs
        )
        logger.info("Access token fetched successfully.")
        return token_response, self.default_params["scope"]

    def fetch_userinfo(self):
        """
        Fetch user information using the access token.

        Returns:
            dict: User information response.
        """
        logger.debug("Fetching user information...")
        userinfo = self.session.get(self.urls["userinfo_uri"]).json()
        logger.info("User information fetched successfully.")
        return userinfo

    def revoke_token(self):
        """
        Revoke the given OAuth2 token.

        Returns:
            dict: The response from the revocation endpoint.
        """
        try:
            refreshed_tokens = self.session.refresh_token(self.urls.get("token_uri"))
            self.session.token = refreshed_tokens
            response = self.session.revoke_token(
                self.urls.get("revoke_uri"), token_type_hint="refresh_token"
            )

            if not response.ok:
                response_data = response.text
                logger.error(
                    "Failed to revoke tokens for %s: %s", self.platform, response_data
                )
                return response_data

            response_data = response.json()
            logger.info("Token revoked successfully.")
            return response_data
        except OAuthError as e:
            logger.error("Error revoking OAuth2 token: %s", e)
            return e

    def send_message(self, message, user_id=None):
        """
        Send a message.

        Args:
            message (dict): The message payload to be sent. The payload should be a
                properly formatted dictionary according to the platform's specifications.
            user_id (str, optional): The ID of the user to send the message on behalf of.

        Returns:
            dict: The response from the platform.
        """
        url = (
            self.urls["send_message_uri"].format(user_id)
            if user_id
            else self.urls["send_message_uri"]
        )

        if self.platform == "twitter":
            return self._send_twitter_message(message, url)

        return self._send_generic_message(message, url)

    def _send_twitter_message(self, message, url):
        def chunk_tweet(tweet, max_length=280):
            tweet_length = len(tweet)
            if tweet_length <= max_length:
                return [tweet]
            tweet_threads_required = math.ceil(tweet_length / max_length)
            tweet_per_thread = math.ceil(tweet_length / tweet_threads_required)
            return textwrap.wrap(tweet, tweet_per_thread, break_long_words=False)

        def create_tweet_payload(text, in_reply_to_tweet_id=None):
            payload = {"text": text}
            if in_reply_to_tweet_id is not None:
                payload["reply"] = {"in_reply_to_tweet_id": str(in_reply_to_tweet_id)}
            return payload

        tweets = chunk_tweet(message)
        tweet_id = None

        for chunk in tweets:
            payload = create_tweet_payload(chunk, tweet_id)
            response = self.session.post(url, json=payload)

            if not response.ok:
                response_data = response.text
                logger.error(
                    "Failed to send message for %s: %s",
                    self.platform,
                    response_data,
                )
                return response_data

            tweet_id = response.json()["data"]["id"]

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        publish_alert = (
            f"Successfully sent message for '{self.platform}' at {timestamp}"
        )
        sentry_sdk.capture_message(
            publish_alert,
            level="info",
        )
        logger.info(publish_alert)
        return f"Successfully sent message to '{self.platform}' on your behalf at {timestamp}."

    def _send_generic_message(self, message, url):
        response = self.session.post(url, json=message)

        if not response.ok:
            response_data = response.text
            logger.error(
                "Failed to send message for %s: %s", self.platform, response_data
            )
            return response_data

        response_data = response.json()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        publish_alert = (
            f"Successfully sent message for '{self.platform}' at {timestamp}"
        )
        sentry_sdk.capture_message(
            publish_alert,
            level="info",
        )
        logger.info(publish_alert)
        return f"Successfully sent message to '{self.platform}' on your behalf at {timestamp}."
