"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class OAuthAdapterInterface(ABC):
    """Abstract base class for all oauth adapters."""

    @abstractmethod
    def get_authorization_url(self, **kwargs) -> Dict[str, Any]:
        """
        Get the authorization URL for the OAuth flow.

        This method should generate a dictionary containing the authorization URL
        and additional metadata required for the OAuth flow.

        Args:
            kwargs: Additional parameters required for the OAuth flow.

        Returns:
            Dict[str, Any]: A dictionary containing the following keys:
                - authorization_url (str): The generated authorization URL.
                - state (str): The state parameter for CSRF protection.
                - code_verifier (str or None): The generated code verifier for PKCE if
                  applicable, otherwise None.
                - client_id (str): The client ID for the OAuth2 application.
                - scope (str): The scope of the authorization request, as a
                  comma-separated string.
                - redirect_uri (str): The redirect URI for the OAuth2 application.
        """

    @abstractmethod
    def get_access_token(self, code: str, **kwargs) -> Dict[str, Any]:
        """
        Exchange the authorization code for an access token.

        Args:
            code (str): The authorization code received from the OAuth provider.
            kwargs: Additional parameters required for the token exchange.

        Returns:
            Dict[str, Any]: A dictionary containing the following keys:
                - access_token (str): The access token for the user.
                - refresh_token (str): The refresh token for the user.
                - id_token (str): The ID token for the user, if applicable.
        """

    @abstractmethod
    def get_user_info(self, **kwargs) -> Dict[str, Any]:
        """
        Retrieve user information using the access token.

        Args:
            kwargs: Additional parameters required for retrieving user information.

        Returns:
            Dict[str, Any]: A dictionary containing the following keys:
            - account_identifier (str): A unique identifier for the user, such as
              an email address or username.
            - name (str, optional): The full name of the user, if available.
        """

    @abstractmethod
    def revoke_token(self, **kwargs) -> bool:
        """
        Revoke the access token.

        This method should invalidate the access token, ensuring it can no longer
        be used for authentication.

        Args:
            kwargs: Additional parameters required for token revocation.

        Returns:
            bool: True if the token was successfully revoked, False otherwise.
        """

    @abstractmethod
    def send_message(self, message: str, **kwargs) -> bool:
        """
        Send a message to the specified recipient.

        Args:
            message (str): The content of the message to be sent.
            kwargs: Additional parameters required for sending the message.

        Returns:
            bool: True if the message was sent successfully, False otherwise.
        """
