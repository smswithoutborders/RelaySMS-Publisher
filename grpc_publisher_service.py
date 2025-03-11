"""gRPC Publisher Service"""

import datetime
import base64
import traceback
import json
import grpc

from authlib.integrations.base_client import OAuthError
import sentry_sdk

import publisher_pb2
import publisher_pb2_grpc

from utils import (
    create_email_message,
    parse_content,
    check_platform_supported,
    get_platform_details_by_shortcode,
    get_configs,
)
from oauth2 import OAuth2Client
import telegram_client
from pnba import PNBAClient
from relaysms_payload import decode_relay_sms_payload
from grpc_vault_entity_client import (
    list_entity_stored_tokens,
    store_entity_token,
    get_entity_access_token,
    decrypt_payload,
    update_entity_token,
    delete_entity_token,
)
from notification_dispatcher import dispatch_notifications
from logutils import get_logger

MOCK_DELIVERY_SMS = (
    get_configs("MOCK_DELIVERY_SMS", default_value="true") or ""
).lower() == "true"

logger = get_logger(__name__)


class PublisherService(publisher_pb2_grpc.PublisherServicer):
    """Publisher Service Descriptor"""

    def handle_create_grpc_error_response(
        self,
        context,
        response,
        error,
        status_code,
        send_to_sentry=False,
        user_msg=None,
        error_type="ERROR",
        error_prefix=None,
    ):
        """
        Handles the creation of a gRPC error response.

        Args:
            context (grpc.ServicerContext): The gRPC context object.
            response (callable): The gRPC response object.
            error (Exception or str): The exception instance or error message.
            status_code (grpc.StatusCode): The gRPC status code to be set for the response
                (e.g., grpc.StatusCode.INTERNAL).
            send_to_sentry (bool): If set to True, the error will be sent to Sentry for tracking.
            user_msg (str, optional): A user-friendly error message to be returned to the client.
                If not provided, the `error` message will be used.
            error_type (str, optional): A string identifying the type of error. Defaults to "ERROR".
                When set to "UNKNOWN", it triggers the logging of a full exception traceback
                for debugging purposes.
            error_prefix (str, optional): An optional prefix to prepend to the error message
                for additional context (e.g., indicating the specific operation or subsystem
                that caused the error).

        Returns:
            An instance of the specified response with the error set.
        """
        user_msg = user_msg or str(error)

        if error_type == "UNKNOWN" and isinstance(error, Exception):
            traceback.print_exception(type(error), error, error.__traceback__)
            if send_to_sentry:
                sentry_sdk.capture_exception(error)
        elif send_to_sentry:
            sentry_sdk.capture_message(user_msg, level="error")

        context.set_details(f"{error_prefix}: {user_msg}" if error_prefix else user_msg)
        context.set_code(status_code)

        return response()

    def handle_request_field_validation(
        self, context, request, response, required_fields
    ):
        """
        Validates the fields in the gRPC request.

        Args:
            context: gRPC context.
            request: gRPC request object.
            response: gRPC response object.
            required_fields (list): List of required fields, can include tuples.

        Returns:
            None or response: None if no missing fields,
                error response otherwise.
        """

        def validate_field(field):
            if not getattr(request, field, None):
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    f"Missing required field: {field}",
                    grpc.StatusCode.INVALID_ARGUMENT,
                )

            return None

        for field in required_fields:
            validation_error = validate_field(field)
            if validation_error:
                return validation_error

        return None

    def create_token_update_handler(self, response_cls, grpc_context, **kwargs):
        """
        Creates a function to handle updating the token for a specific device and account.

        Args:
            device_id (str): The unique identifier of the device.
            account_id (str): The identifier for the account (e.g., email or username).
            platform (str): The name of the platform (e.g., 'gmail').
            response_cls (protobuf message class): The response class for the gRPC method.
            grpc_context (grpc.ServicerContext): The gRPC context for the current method call.

        Returns:
            function: A function `handle_token_update(token)` that updates the token information.
        """
        device_id = kwargs.get("device_id")
        phone_number = kwargs.get("phone_number")
        account_id = kwargs["account_id"]
        platform = kwargs["platform"]

        def handle_token_update(token, **kwargs):
            """
            Handles updating the stored token for the specified device and account.

            Args:
                token (dict or object): The token information containing access and refresh tokens.
            """
            logger.debug(kwargs)

            update_response, update_error = update_entity_token(
                device_id=device_id,
                phone_number=phone_number,
                token=json.dumps(token),
                account_identifier=account_id,
                platform=platform,
            )

            if update_error:
                return self.handle_create_grpc_error_response(
                    grpc_context,
                    response_cls,
                    update_error.details(),
                    update_error.code(),
                )

            if not update_response.success:
                return response_cls(
                    message=update_response.message,
                    success=update_response.success,
                )

            return True

        return handle_token_update

    def GetOAuth2AuthorizationUrl(self, request, context):
        """Handles generating OAuth2 authorization URL"""

        response = publisher_pb2.GetOAuth2AuthorizationUrlResponse

        def validate_fields():
            return self.handle_request_field_validation(
                context,
                request,
                response,
                ["platform"],
            )

        def handle_authorization(oauth2_client):
            extra_params = {
                "state": getattr(request, "state") or None,
                "code_verifier": getattr(request, "code_verifier") or None,
                "autogenerate_code_verifier": getattr(
                    request, "autogenerate_code_verifier"
                ),
            }

            authorization_url, state, code_verifier, client_id, scope, redirect_uri = (
                oauth2_client.get_authorization_url(**extra_params)
            )

            return response(
                authorization_url=authorization_url,
                state=state,
                code_verifier=code_verifier,
                client_id=client_id,
                scope=scope,
                redirect_url=redirect_uri,
                message="Successfully generated authorization url",
            )

        try:
            invalid_fields_response = validate_fields()
            if invalid_fields_response:
                return invalid_fields_response

            check_platform_supported(request.platform.lower(), "oauth2")

            oauth2_client = OAuth2Client(request.platform)

            if request.redirect_url:
                oauth2_client.session.redirect_uri = request.redirect_url

            return handle_authorization(oauth2_client)

        except NotImplementedError as e:
            return self.handle_create_grpc_error_response(
                context,
                response,
                str(e),
                grpc.StatusCode.UNIMPLEMENTED,
            )

        except Exception as exc:
            return self.handle_create_grpc_error_response(
                context,
                response,
                exc,
                grpc.StatusCode.INTERNAL,
                user_msg="Oops! Something went wrong. Please try again later.",
                error_type="UNKNOWN",
            )

    def ExchangeOAuth2CodeAndStore(self, request, context):
        """Handles exchanging OAuth2 authorization code for a token"""

        response = publisher_pb2.ExchangeOAuth2CodeAndStoreResponse

        def validate_fields():
            return self.handle_request_field_validation(
                context,
                request,
                response,
                ["long_lived_token", "platform", "authorization_code"],
            )

        def list_tokens():
            list_response, list_error = list_entity_stored_tokens(
                long_lived_token=request.long_lived_token
            )
            if list_error:
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    list_error.details(),
                    list_error.code(),
                    error_type="UNKNOWN",
                )
            return list_response, None

        def fetch_token_and_profile():
            oauth2_client = OAuth2Client(request.platform)

            if request.redirect_url:
                oauth2_client.session.redirect_uri = request.redirect_url

            extra_params = {"code_verifier": getattr(request, "code_verifier") or None}
            token, scope = oauth2_client.fetch_token(
                code=request.authorization_code, **extra_params
            )

            if not token.get("refresh_token"):
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    "invalid token: No refresh token present.",
                    grpc.StatusCode.INVALID_ARGUMENT,
                )

            fetched_scopes = set(token.get("scope", "").split())
            expected_scopes = set(scope)

            if not expected_scopes.issubset(fetched_scopes):
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    "invalid token: Scopes do not match. Expected: "
                    f"{expected_scopes}, Received: {fetched_scopes}",
                    grpc.StatusCode.INVALID_ARGUMENT,
                )

            profile = oauth2_client.fetch_userinfo()
            return (token, profile), None

        def store_token(token, profile):
            store_response, store_error = store_entity_token(
                long_lived_token=request.long_lived_token,
                platform=request.platform,
                account_identifier=profile.get("email")
                or profile.get("username")
                or profile.get("data", {}).get("username"),
                token=json.dumps(token),
            )

            if store_error:
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    store_error.details(),
                    store_error.code(),
                    error_type="UNKNOWN",
                )

            if not store_response.success:
                return response(
                    message=store_response.message, success=store_response.success
                )

            return response(
                success=True, message="Successfully fetched and stored token"
            )

        try:
            invalid_fields_response = validate_fields()
            if invalid_fields_response:
                return invalid_fields_response

            check_platform_supported(request.platform.lower(), "oauth2")

            _, token_list_error = list_tokens()
            if token_list_error:
                return token_list_error

            fetched_data, fetch_token_error = fetch_token_and_profile()

            if fetch_token_error:
                return fetch_token_error

            return store_token(*fetched_data)

        except OAuthError as e:
            return self.handle_create_grpc_error_response(
                context,
                response,
                str(e),
                grpc.StatusCode.INVALID_ARGUMENT,
                error_type="UNKNOWN",
            )

        except NotImplementedError as e:
            return self.handle_create_grpc_error_response(
                context,
                response,
                str(e),
                grpc.StatusCode.UNIMPLEMENTED,
            )

        except Exception as exc:
            return self.handle_create_grpc_error_response(
                context,
                response,
                exc,
                grpc.StatusCode.INTERNAL,
                user_msg="Oops! Something went wrong. Please try again later.",
                error_type="UNKNOWN",
            )

    def RevokeAndDeleteOAuth2Token(self, request, context):
        """Handles revoking and deleting OAuth2 access tokens"""

        response = publisher_pb2.RevokeAndDeleteOAuth2TokenResponse

        def validate_fields():
            return self.handle_request_field_validation(
                context,
                request,
                response,
                ["long_lived_token", "platform", "account_identifier"],
            )

        def get_access_token():
            get_access_token_response, get_access_token_error = get_entity_access_token(
                platform=request.platform,
                account_identifier=request.account_identifier,
                long_lived_token=request.long_lived_token,
            )
            if get_access_token_error:
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    get_access_token_error.details(),
                    get_access_token_error.code(),
                )
            if not get_access_token_response.success:
                return None, response(
                    message=get_access_token_response.message,
                    success=get_access_token_response.success,
                )
            return get_access_token_response.token, None

        def revoke_token(token):
            oauth2_client = OAuth2Client(request.platform, json.loads(token))
            revoke_response = oauth2_client.revoke_token()
            return revoke_response

        def delete_token():
            delete_token_response, delete_token_error = delete_entity_token(
                request.long_lived_token, request.platform, request.account_identifier
            )

            if delete_token_error:
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    delete_token_error.details(),
                    delete_token_error.code(),
                )

            if not delete_token_response.success:
                return response(
                    message=delete_token_response.message,
                    success=delete_token_response.success,
                )

            return response(success=True, message="Successfully deleted token")

        try:
            invalid_fields_response = validate_fields()
            if invalid_fields_response:
                return invalid_fields_response

            check_platform_supported(request.platform.lower(), "oauth2")

            access_token, access_token_error = get_access_token()
            if access_token_error:
                return access_token_error

            revoke_token(access_token)
            return delete_token()

        except NotImplementedError as e:
            return self.handle_create_grpc_error_response(
                context,
                response,
                str(e),
                grpc.StatusCode.UNIMPLEMENTED,
            )

        except Exception as exc:
            return self.handle_create_grpc_error_response(
                context,
                response,
                exc,
                grpc.StatusCode.INTERNAL,
                user_msg="Oops! Something went wrong. Please try again later.",
                error_type="UNKNOWN",
            )

    def PublishContent(self, request, context):
        """Handles publishing relaysms payload"""

        response = publisher_pb2.PublishContentResponse

        def validate_fields():
            return self.handle_request_field_validation(
                context, request, response, ["content"]
            )

        def decode_payload():
            platform_letter, encrypted_content, device_id, decode_error = (
                decode_relay_sms_payload(request.content)
            )
            if decode_error:
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    decode_error,
                    grpc.StatusCode.INVALID_ARGUMENT,
                    error_prefix="Error Decoding Platform Payload",
                    error_type="UNKNOWN",
                    send_to_sentry=True,
                )
            return (platform_letter, encrypted_content, device_id), None

        def get_platform_info(platform_letter):
            platform_info, platform_err = get_platform_details_by_shortcode(
                platform_letter
            )
            if platform_info is None:
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    platform_err,
                    grpc.StatusCode.INVALID_ARGUMENT,
                    send_to_sentry=True,
                )
            return platform_info, None

        def get_access_token(
            device_id, phone_number, platform_name, account_identifier
        ):
            get_access_token_response, get_access_token_error = get_entity_access_token(
                device_id=device_id,
                phone_number=phone_number,
                platform=platform_name,
                account_identifier=account_identifier,
            )
            if get_access_token_error:
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    get_access_token_error.details(),
                    get_access_token_error.code(),
                    error_prefix="Error Fetching Access Token",
                    send_to_sentry=True,
                )
            if not get_access_token_response.success:
                return None, response(
                    message=get_access_token_response.message,
                    success=get_access_token_response.success,
                )
            return get_access_token_response.token, None

        def decrypt_message(device_id, phone_number, encrypted_content):
            decrypt_payload_response, decrypt_payload_error = decrypt_payload(
                device_id=device_id,
                phone_number=phone_number,
                payload_ciphertext=base64.b64encode(encrypted_content).decode("utf-8"),
            )
            if decrypt_payload_error:
                return (
                    None,
                    None,
                    self.handle_create_grpc_error_response(
                        context,
                        response,
                        decrypt_payload_error.details(),
                        decrypt_payload_error.code(),
                        error_prefix="Error Decrypting Platform Payload",
                        send_to_sentry=True,
                    ),
                )
            if not decrypt_payload_response.success:
                return None, response(
                    message=decrypt_payload_response.message,
                    success=decrypt_payload_response.success,
                )

            country_code = decrypt_payload_response.country_code
            return decrypt_payload_response.payload_plaintext, country_code, None

        # def encrypt_message(device_id, plaintext):
        #     encrypt_payload_response, encrypt_payload_error = encrypt_payload(
        #         device_id.hex(), plaintext
        #     )
        #     if encrypt_payload_error:
        #         return None, self.handle_create_grpc_error_response(
        #             context,
        #             response,
        #             encrypt_payload_error.details(),
        #             encrypt_payload_error.code(),
        #         )
        #     if not encrypt_payload_response.success:
        #         return None, response(
        #             message=encrypt_payload_response.message,
        #             success=encrypt_payload_response.success,
        #         )
        #     return encrypt_payload_response.payload_ciphertext, None

        def handle_oauth2_email(platform_name, content_parts, token, **kwargs):
            from_email, to_email, cc_email, bcc_email, subject, body = content_parts
            email_message = create_email_message(
                from_email,
                to_email,
                subject,
                body,
                cc_email=cc_email,
                bcc_email=bcc_email,
            )
            oauth2_client = OAuth2Client(
                platform_name,
                json.loads(token),
                self.create_token_update_handler(
                    device_id=kwargs.get("device_id"),
                    phone_number=kwargs.get("phone_number"),
                    account_id=from_email,
                    platform=platform_name,
                    response_cls=response,
                    grpc_context=context,
                ),
            )
            return oauth2_client.send_message(email_message, from_email)

        def handle_oauth2_text(platform_name, content_parts, token, **kwargs):
            sender, text = content_parts
            oauth2_client = OAuth2Client(
                platform_name,
                json.loads(token),
                self.create_token_update_handler(
                    device_id=kwargs.get("device_id"),
                    phone_number=kwargs.get("phone_number"),
                    account_id=sender,
                    platform=platform_name,
                    response_cls=response,
                    grpc_context=context,
                ),
            )
            return oauth2_client.send_message(text)

        def handle_pnba_message(platform_name, content_parts, token):
            _, receiver, message = content_parts
            pnba_client = PNBAClient(platform_name, json.loads(token))
            return pnba_client.send_message(message=message, recipient=receiver)

        def handle_publication_notifications(
            platform_name, message, status="failed", country_code=None
        ):
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"RelaySMS Delivery: "
                f"{'Failed to send' if status == 'failed' else 'Successfully sent'} "
                f"message to {platform_name} at {timestamp}. "
                f"{f'\n{message}' if message else ''}"
            )
            notifications = [
                {
                    "notification_type": "event",
                    "target": "publication",
                    "details": {
                        "platform_name": platform_name,
                        "source": "platforms",
                        "status": status,
                        "country_code": country_code,
                    },
                },
            ]
            if MOCK_DELIVERY_SMS:
                notifications.append(
                    {
                        "notification_type": "event",
                        "target": "sentry",
                        "message": message,
                        "details": {"level": "info", "capture_type": "message"},
                    }
                )
            else:
                notifications.append(
                    {
                        "notification_type": "sms",
                        "target": request.metadata["From"],
                        "message": message,
                    }
                )
            dispatch_notifications(notifications)

        try:
            invalid_fields_response = validate_fields()
            if invalid_fields_response:
                return invalid_fields_response

            decoded_payload, decoding_error = decode_payload()
            if decoding_error:
                return decoding_error

            platform_letter, encrypted_content, device_id = decoded_payload

            platform_info, platform_info_error = get_platform_info(platform_letter)
            if platform_info_error:
                return platform_info_error

            device_id_hex = device_id.hex() if device_id else None
            decrypted_content, country_code, decrypt_error = decrypt_message(
                device_id=device_id_hex,
                phone_number=request.metadata["From"],
                encrypted_content=encrypted_content,
            )

            if decrypt_error:
                return decrypt_error

            content_parts, parse_error = parse_content(
                platform_info["service_type"], decrypted_content
            )

            if parse_error:
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    parse_error,
                    grpc.StatusCode.INVALID_ARGUMENT,
                    send_to_sentry=True,
                )

            content_parts = list(content_parts)
            content_parts[0] = content_parts[0].replace("\n", "")
            content_parts = tuple(content_parts)

            access_token, access_token_error = get_access_token(
                device_id=device_id_hex,
                phone_number=request.metadata["From"],
                platform_name=platform_info["name"],
                account_identifier=content_parts[0],
            )
            if access_token_error:
                return access_token_error

            publication_response = None
            publication_error = None
            message_body = None

            if platform_info["service_type"] == "email":
                publication_response, publication_error = handle_oauth2_email(
                    device_id=device_id_hex,
                    phone_number=request.metadata["From"],
                    platform_name=platform_info["name"],
                    content_parts=content_parts,
                    token=access_token,
                )
            elif platform_info["service_type"] == "text":
                publication_response, publication_error = handle_oauth2_text(
                    device_id=device_id_hex,
                    phone_number=request.metadata["From"],
                    platform_name=platform_info["name"],
                    content_parts=content_parts,
                    token=access_token,
                )
            elif platform_info["service_type"] == "message":
                publication_response, publication_error = handle_pnba_message(
                    platform_name=platform_info["name"],
                    content_parts=content_parts,
                    token=access_token,
                )

            if publication_error:
                handle_publication_notifications(
                    platform_info["name"],
                    message_body,
                    status="failed",
                    country_code=country_code,
                )
                return response(
                    message=f"Failed to publish {platform_info['name']} message",
                    publisher_response=publication_error,
                    success=False,
                )

            # payload_ciphertext, encrypt_payload_error = encrypt_message(
            #     device_id, message_response
            # )
            # if encrypt_payload_error:
            #     return encrypt_payload_error
            handle_publication_notifications(
                platform_info["name"],
                message_body,
                status="published",
                country_code=country_code,
            )
            return response(
                message=f"Successfully published {platform_info['name']} message",
                publisher_response=publication_response,
                success=True,
            )

        except telegram_client.Errors.RPCError as exc:
            handle_publication_notifications(
                platform_info["name"],
                message_body,
                status="failed",
                country_code=country_code,
            )
            return self.handle_create_grpc_error_response(
                context,
                response,
                exc,
                grpc.StatusCode.INVALID_ARGUMENT,
                error_type="UNKNOWN",
                send_to_sentry=True,
            )

        except OAuthError as exc:
            handle_publication_notifications(
                platform_info["name"],
                message_body,
                status="failed",
                country_code=country_code,
            )
            return self.handle_create_grpc_error_response(
                context,
                response,
                exc,
                grpc.StatusCode.INVALID_ARGUMENT,
                error_type="UNKNOWN",
                send_to_sentry=True,
            )

        except Exception as exc:
            handle_publication_notifications(
                platform_info["name"],
                message_body,
                status="failed",
                country_code=country_code,
            )
            return self.handle_create_grpc_error_response(
                context,
                response,
                exc,
                grpc.StatusCode.INTERNAL,
                user_msg="Oops! Something went wrong. Please try again later.",
                error_type="UNKNOWN",
                send_to_sentry=True,
            )

    def GetPNBACode(self, request, context):
        """Handles Requesting Phone number-based Authentication."""

        response = publisher_pb2.GetPNBACodeResponse

        def validate_fields():
            return self.handle_request_field_validation(
                context,
                request,
                response,
                ["phone_number", "platform"],
            )

        try:
            invalid_fields_response = validate_fields()
            if invalid_fields_response:
                return invalid_fields_response

            check_platform_supported(request.platform.lower(), "pnba")

            pnba_client = PNBAClient(request.platform, request.phone_number)

            pnba_response = pnba_client.authorization()

            if pnba_response.get("error"):
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    pnba_response["error"],
                    grpc.StatusCode.INVALID_ARGUMENT,
                    error_type="UNKNOWN",
                )

            return response(success=True, message=pnba_response["response"])

        except NotImplementedError as e:
            return self.handle_create_grpc_error_response(
                context,
                response,
                str(e),
                grpc.StatusCode.UNIMPLEMENTED,
            )

        except Exception as exc:
            return self.handle_create_grpc_error_response(
                context,
                response,
                exc,
                grpc.StatusCode.INTERNAL,
                user_msg="Oops! Something went wrong. Please try again later.",
                error_type="UNKNOWN",
            )

    def ExchangePNBACodeAndStore(self, request, context):
        """Handles Exchanging Phone number-based Authentication code for access."""

        response = publisher_pb2.ExchangePNBACodeAndStoreResponse

        def validate_fields():
            return self.handle_request_field_validation(
                context,
                request,
                response,
                ["long_lived_token", "phone_number", "platform", "authorization_code"],
            )

        def list_tokens():
            list_response, list_error = list_entity_stored_tokens(
                long_lived_token=request.long_lived_token
            )
            if list_error:
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    list_error.details(),
                    list_error.code(),
                    error_type="UNKNOWN",
                )
            return list_response, None

        def fetch_token_and_profile():
            pnba_client = PNBAClient(request.platform, request.phone_number)

            if request.password:
                pnba_response = pnba_client.password_validation(request.password)
            else:
                pnba_response = pnba_client.validation(request.authorization_code)

            if pnba_response.get("two_step_verification_enabled"):
                return None, response(
                    success=True,
                    two_step_verification_enabled=True,
                    message="two-steps verification is enabled and a password is required",
                )

            if pnba_response.get("error"):
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    pnba_response["error"],
                    grpc.StatusCode.INVALID_ARGUMENT,
                    error_type="UNKNOWN",
                )

            token = pnba_response["response"]["token"]
            profile = pnba_response["response"]["profile"]

            return (token, profile), None

        def store_token(token, profile):
            store_response, store_error = store_entity_token(
                long_lived_token=request.long_lived_token,
                platform=request.platform,
                account_identifier=profile.get("unique_id"),
                token=json.dumps(token),
            )

            if store_error:
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    store_error.details(),
                    store_error.code(),
                    error_type="UNKNOWN",
                )

            if not store_response.success:
                return response(
                    message=store_response.message, success=store_response.success
                )

            return response(
                success=True, message="Successfully fetched and stored token"
            )

        try:
            invalid_fields_response = validate_fields()
            if invalid_fields_response:
                return invalid_fields_response

            check_platform_supported(request.platform.lower(), "pnba")

            _, token_list_error = list_tokens()
            if token_list_error:
                return token_list_error

            fetched_data, fetch_token_error = fetch_token_and_profile()

            if fetch_token_error:
                return fetch_token_error

            return store_token(*fetched_data)

        except NotImplementedError as e:
            return self.handle_create_grpc_error_response(
                context,
                response,
                str(e),
                grpc.StatusCode.UNIMPLEMENTED,
            )

        except Exception as exc:
            return self.handle_create_grpc_error_response(
                context,
                response,
                exc,
                grpc.StatusCode.INTERNAL,
                user_msg="Oops! Something went wrong. Please try again later.",
                error_type="UNKNOWN",
            )

    def RevokeAndDeletePNBAToken(self, request, context):
        """Handles revoking and deleting PNBA access tokens"""

        response = publisher_pb2.RevokeAndDeletePNBATokenResponse

        def validate_fields():
            return self.handle_request_field_validation(
                context,
                request,
                response,
                ["long_lived_token", "platform", "account_identifier"],
            )

        def get_access_token():
            get_access_token_response, get_access_token_error = get_entity_access_token(
                platform=request.platform,
                account_identifier=request.account_identifier,
                long_lived_token=request.long_lived_token,
            )
            if get_access_token_error:
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    get_access_token_error.details(),
                    get_access_token_error.code(),
                )
            if not get_access_token_response.success:
                return None, response(
                    message=get_access_token_response.message,
                    success=get_access_token_response.success,
                )
            return get_access_token_response.token, None

        def revoke_token(token):
            pnba_client = PNBAClient(request.platform, json.loads(token))
            revoke_response = pnba_client.invalidation()
            return revoke_response

        def delete_token():
            delete_token_response, delete_token_error = delete_entity_token(
                request.long_lived_token, request.platform, request.account_identifier
            )

            if delete_token_error:
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    delete_token_error.details(),
                    delete_token_error.code(),
                )

            if not delete_token_response.success:
                return response(
                    message=delete_token_response.message,
                    success=delete_token_response.success,
                )

            return response(success=True, message="Successfully deleted token")

        try:
            invalid_fields_response = validate_fields()
            if invalid_fields_response:
                return invalid_fields_response

            check_platform_supported(request.platform.lower(), "pnba")

            access_token, access_token_error = get_access_token()
            if access_token_error:
                return access_token_error

            revoke_token(access_token)
            return delete_token()

        except NotImplementedError as e:
            return self.handle_create_grpc_error_response(
                context,
                response,
                str(e),
                grpc.StatusCode.UNIMPLEMENTED,
            )

        except Exception as exc:
            return self.handle_create_grpc_error_response(
                context,
                response,
                exc,
                grpc.StatusCode.INTERNAL,
                user_msg="Oops! Something went wrong. Please try again later.",
                error_type="UNKNOWN",
            )
