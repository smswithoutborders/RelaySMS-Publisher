"""gRPC Publisher Service"""

import datetime
import base64
import traceback
import json
import grpc

import sentry_sdk

import publisher_pb2
import publisher_pb2_grpc

from utils import get_configs
from content_parser import (
    decode_content,
    extract_content_v0,
    extract_content_v1,
    extract_content_v2,
)
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
from translations import Localization
from platforms.adapter_manager import AdapterManager
from platforms.adapter_ipc_handler import AdapterIPCHandler

MOCK_DELIVERY_SMS = (
    get_configs("MOCK_DELIVERY_SMS", default_value="true") or ""
).lower() == "true"

logger = get_logger(__name__)
loc = Localization()
t = loc.translate


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
        skip_token_update = kwargs["skip_token_update"]

        def handle_token_update(token, **kwargs):
            """
            Handles updating the stored token for the specified device and account.

            Args:
                token (dict or object): The token information containing access and refresh tokens.
            """
            logger.debug(kwargs)
            if skip_token_update:
                logger.debug("Skipping token update for %s on %s", account_id, platform)
                return True

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

        try:
            invalid_fields_response = validate_fields()
            if invalid_fields_response:
                return invalid_fields_response

            adapter = AdapterManager.get_adapter_path(
                name=request.platform.lower(), protocol="oauth2"
            )
            if not adapter:
                raise NotImplementedError(
                    f"The platform '{request.platform.lower()}' with "
                    "protocol 'oauth2' is currently not supported. "
                    "Please contact the developers for more information on when "
                    "this platform will be implemented."
                )

            params = {
                "state": getattr(request, "state") or None,
                "code_verifier": getattr(request, "code_verifier") or None,
                "autogenerate_code_verifier": getattr(
                    request, "autogenerate_code_verifier"
                ),
                "redirect_url": getattr(request, "redirect_url") or None,
                "request_identifier": getattr(request, "request_identifier") or None,
                "base_path": adapter["assets_path"],
            }

            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="get_authorization_url",
                params=params,
            )

            if pipe.get("error"):
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    pipe.get("error"),
                    grpc.StatusCode.INVALID_ARGUMENT,
                    error_type="UNKNOWN",
                )

            result = pipe.get("result")

            return response(
                authorization_url=result.get("authorization_url"),
                state=result.get("state"),
                code_verifier=result.get("code_verifier"),
                client_id=result.get("client_id"),
                scope=result.get("scope"),
                redirect_url=result.get("redirect_url"),
                message="Successfully generated authorization url",
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

        def store_token(token, userinfo):
            local_tokens = {}

            if request.store_on_device:
                local_tokens = {
                    "access_token": token.pop("access_token"),
                    "refresh_token": token.pop("refresh_token"),
                    "id_token": token.pop("id_token", ""),
                }

            store_response, store_error = store_entity_token(
                long_lived_token=request.long_lived_token,
                platform=request.platform,
                account_identifier=userinfo.get("account_identifier"),
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
                success=True,
                message="Successfully fetched and stored token",
                tokens=local_tokens,
            )

        try:
            invalid_fields_response = validate_fields()
            if invalid_fields_response:
                return invalid_fields_response

            adapter = AdapterManager.get_adapter_path(
                name=request.platform.lower(), protocol="oauth2"
            )
            if not adapter:
                raise NotImplementedError(
                    f"The platform '{request.platform.lower()}' with "
                    "protocol 'oauth2' is currently not supported. "
                    "Please contact the developers for more information on when "
                    "this platform will be implemented."
                )

            _, token_list_error = list_tokens()
            if token_list_error:
                return token_list_error

            params = {
                "code": request.authorization_code,
                "code_verifier": getattr(request, "code_verifier") or None,
                "redirect_url": getattr(request, "redirect_url") or None,
                "request_identifier": getattr(request, "request_identifier") or None,
                "base_path": adapter["assets_path"],
            }

            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="exchange_code_and_fetch_user_info",
                params=params,
            )

            if pipe.get("error"):
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    pipe.get("error"),
                    grpc.StatusCode.INVALID_ARGUMENT,
                    error_type="UNKNOWN",
                )

            result = pipe.get("result")

            return store_token(
                token=result.get("token"), userinfo=result.get("userinfo")
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

            adapter = AdapterManager.get_adapter_path(
                name=request.platform.lower(), protocol="oauth2"
            )
            if not adapter:
                raise NotImplementedError(
                    f"The platform '{request.platform.lower()}' with "
                    "protocol 'oauth2' is currently not supported. "
                    "Please contact the developers for more information on when "
                    "this platform will be implemented."
                )

            access_token, access_token_error = get_access_token()
            if access_token_error:
                return access_token_error

            params = {"token": json.loads(access_token)}

            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="revoke_token",
                params=params,
            )

            if pipe.get("error"):
                logger.error(pipe.get("error"))

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
            decoded_result, decode_error = decode_content(request.content)
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
            return decoded_result, None

        def get_platform_info(platform_letter):
            adapter = AdapterManager.get_adapter(platform_letter)
            if not adapter:
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    f"No platform found for shortcode '{platform_letter}'.",
                    grpc.StatusCode.INVALID_ARGUMENT,
                    send_to_sentry=True,
                )
            return adapter, None

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
                return None, self.handle_create_grpc_error_response(
                    context,
                    response,
                    decrypt_payload_error.details(),
                    decrypt_payload_error.code(),
                    error_prefix="Error Decrypting Platform Payload",
                    send_to_sentry=True,
                )

            if not decrypt_payload_response.success:
                return None, response(
                    message=decrypt_payload_response.message,
                    success=decrypt_payload_response.success,
                )

            result = {
                "payload_plaintext": base64.b64decode(
                    decrypt_payload_response.payload_plaintext
                ),
                "country_code": decrypt_payload_response.country_code,
            }
            return result, None

        def handle_token_update(
            token, device_id, phone_number, account_identifier, platform
        ):
            update_response, update_error = update_entity_token(
                device_id=device_id,
                phone_number=phone_number,
                token=json.dumps(token),
                account_identifier=account_identifier,
                platform=platform,
            )

            if update_error:
                logger.error(
                    "Failed to update token: %s - %s",
                    update_error.code(),
                    update_error.details(),
                )
                return False

            if not update_response.success:
                logger.error("Failed to update token: %s", update_response.message)
                return False

            return True

        def handle_oauth2_publication(
            service_type, platform_name, content_parts, **kwargs
        ):
            service_handlers = {
                "email": lambda parts: {
                    "sender_id": parts[0],
                    "from_email": parts[0],
                    "to_email": parts[1],
                    "cc_email": parts[2],
                    "bcc_email": parts[3],
                    "subject": parts[4],
                    "message": parts[5],
                    "access_token": parts[6],
                    "refresh_token": parts[7],
                },
                "text": lambda parts: {
                    "sender_id": parts[0],
                    "message": parts[1],
                    "access_token": parts[2],
                    "refresh_token": parts[3],
                },
            }

            if service_type not in service_handlers:
                raise NotImplementedError(
                    f"The service type '{service_type}' for '{platform_name}' "
                    "is not supported. Please contact the developers for more information."
                )

            data = service_handlers[service_type](content_parts)
            user_sent_tokens = bool(data["access_token"] and data["refresh_token"])

            adapter = AdapterManager.get_adapter_path(
                name=platform_name.lower(), protocol="oauth2"
            )
            if not adapter:
                raise NotImplementedError(
                    f"The platform '{platform_name.lower()}' with "
                    "protocol 'oauth2' is currently not supported. "
                    "Please contact the developers for more information on when "
                    "this platform will be implemented."
                )

            token, token_error = get_access_token(
                device_id=kwargs.get("device_id"),
                phone_number=request.metadata["From"],
                platform_name=platform_info["name"],
                account_identifier=data["sender_id"],
            )
            if token_error:
                return {"response": token_error, "error": None, "message": None}

            token_data = json.loads(token)
            if user_sent_tokens:
                token_data.update(
                    {
                        "access_token": data["access_token"],
                        "refresh_token": data["refresh_token"],
                    }
                )
            params = {"token": token_data}
            params.update(
                {
                    k: v
                    for k, v in data.items()
                    if k not in ["access_token", "refresh_token"]
                }
            )

            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="send_message",
                params=params,
            )

            if error := pipe.get("error"):
                return {"response": None, "error": error, "message": None}

            result = pipe.get("result", {})
            refreshed_token = result.get("refreshed_token", {})
            new_refresh_token = refreshed_token.get("refresh_token")
            old_refresh_token = data.get("refresh_token")
            is_refresh_token_updated = new_refresh_token != old_refresh_token

            refresh_alert = None
            if is_refresh_token_updated and user_sent_tokens:
                refresh_token_msg = f"{data['sender_id']}:{new_refresh_token}"
                refresh_alert = (
                    "\n\nPlease paste this message in your RelaySMS app\n"
                    f"{base64.b64encode(refresh_token_msg.encode()).decode('utf-8')}"
                )

            if not user_sent_tokens:
                handle_token_update(
                    token=refreshed_token,
                    device_id=kwargs.get("device_id"),
                    phone_number=request.metadata["From"],
                    account_identifier=data["sender_id"],
                    platform=platform_name.lower(),
                )

            return {
                "response": None,
                "error": result.get("message") if not result.get("success") else None,
                "message": "Successfully sent message",
                "refresh_alert": refresh_alert,
            }

        def handle_pnba_publication(
            service_type, platform_name, content_parts, **kwargs
        ):
            service_handlers = {
                "message": lambda parts: {
                    "sender_id": parts[0],
                    "recipient": parts[1],
                    "message": parts[2],
                }
            }

            if service_type not in service_handlers:
                raise NotImplementedError(
                    f"The service type '{service_type}' for '{platform_name}' "
                    "is not supported. Please contact the developers for more information."
                )

            data = service_handlers[service_type](content_parts)

            adapter = AdapterManager.get_adapter_path(
                name=platform_name.lower(), protocol="pnba"
            )
            if not adapter:
                raise NotImplementedError(
                    f"The platform '{platform_name.lower()}' with "
                    "protocol 'pnba' is currently not supported. "
                    "Please contact the developers for more information on when "
                    "this platform will be implemented."
                )

            token, token_error = get_access_token(
                device_id=kwargs.get("device_id"),
                phone_number=request.metadata["From"],
                platform_name=platform_info["name"],
                account_identifier=data["sender_id"],
            )
            if token_error:
                return {"response": token_error, "error": None, "message": None}

            params = {
                "phone_number": json.loads(token),
                "recipient": data["recipient"],
                "message": data["message"],
                "base_path": adapter["assets_path"],
            }

            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="send_message",
                params=params,
            )

            if pipe.get("error"):
                return {"response": None, "error": pipe.get("error"), "message": None}

            return {
                "response": None,
                "error": None,
                "message": "Successfully sent message",
            }

        def handle_test_publication(service_type, platform_name, content_parts):
            service_handlers = {"test": lambda parts: {"test_id": parts[0]}}

            if service_type not in service_handlers:
                raise NotImplementedError(
                    f"The service type '{service_type}' for '{platform_name}' "
                    "is not supported. Please contact the developers for more information."
                )

            data = service_handlers[service_type](content_parts)

            adapter = AdapterManager.get_adapter_path(
                name=platform_name.lower(), protocol="event"
            )
            if not adapter:
                raise NotImplementedError(
                    f"The platform '{platform_name.lower()}' with "
                    "protocol 'event' is currently not supported. "
                    "Please contact the developers for more information on when "
                    "this platform will be implemented."
                )

            params = {
                "resource_id": data["test_id"],
                "sms_sent_timestamp": request.metadata.get("Date_sent"),
                "sms_received_timestamp": request.metadata.get("Date"),
            }

            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="update",
                params=params,
            )

            if pipe.get("error"):
                return {"response": None, "error": pipe.get("error"), "message": None}

            result = pipe.get("result")

            if not result.get("success"):
                return {
                    "response": self.handle_create_grpc_error_response(
                        context,
                        response,
                        result.get("message"),
                        grpc.StatusCode.INVALID_ARGUMENT,
                    ),
                    "error": None,
                    "message": None,
                }

            return {
                "response": response(
                    message=f"Successfully published {platform_name.lower()} message",
                    publisher_response=result.get("message"),
                    success=True,
                ),
                "error": None,
                "message": None,
            }

        def handle_publication_notifications(
            platform_name, status="failed", country_code=None, **kwargs
        ):
            try:
                loc.set_locale(kwargs.get("language") or "en")
            except ValueError as e:
                logger.error(e)

            timestamp = datetime.datetime.now(tz=datetime.timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S (%Z)"
            )
            message = (
                t("sms_delivery_message")
                .format(
                    additional_data=kwargs.get("additional_data") or "",
                    platform_name=platform_name,
                    delivery_status=(
                        t("delivery_status_failed")
                        if status == "failed"
                        else t("delivery_status_success")
                    ),
                    timestamp=timestamp,
                )
                .replace("\\n", "\n")
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

            platform_info, platform_info_error = get_platform_info(
                decoded_payload.get("platform_shortcode")
            )
            if platform_info_error:
                return platform_info_error

            device_id_hex = (
                decoded_payload.get("device_id").hex()
                if decoded_payload.get("device_id")
                else None
            )
            decrypted_result, decrypt_error = decrypt_message(
                device_id=device_id_hex,
                phone_number=request.metadata["From"],
                encrypted_content=decoded_payload.get("ciphertext"),
            )

            if decrypt_error:
                return decrypt_error

            extraction_error = None
            content_parts = None
            if "version" in decoded_payload:
                if decoded_payload.get("version") == "v1":
                    content_parts, extraction_error = extract_content_v1(
                        platform_info["service_type"],
                        decrypted_result.get("payload_plaintext"),
                    )
                elif decoded_payload.get("version") == "v2":
                    content_parts, extraction_error = extract_content_v2(
                        platform_info["service_type"],
                        decrypted_result.get("payload_plaintext"),
                    )
            else:
                content_parts, extraction_error = extract_content_v0(
                    platform_info["service_type"],
                    decrypted_result.get("payload_plaintext").decode("utf-8"),
                )

            if extraction_error:
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    extraction_error,
                    grpc.StatusCode.INVALID_ARGUMENT,
                    send_to_sentry=True,
                )

            content_parts = list(content_parts)
            content_parts[0] = content_parts[0].replace("\n", "")
            content_parts = tuple(content_parts)

            publication_response = None

            if platform_info["protocol_type"] == "oauth2":
                publication_response = handle_oauth2_publication(
                    service_type=platform_info["service_type"],
                    platform_name=platform_info["name"],
                    content_parts=content_parts,
                    device_id=device_id_hex,
                )
            elif platform_info["protocol_type"] == "pnba":
                publication_response = handle_pnba_publication(
                    service_type=platform_info["service_type"],
                    platform_name=platform_info["name"],
                    content_parts=content_parts,
                    device_id=device_id_hex,
                )
            elif platform_info["protocol_type"] == "event":
                publication_response = handle_test_publication(
                    service_type=platform_info["service_type"],
                    platform_name=platform_info["name"],
                    content_parts=content_parts,
                )

            if publication_response["response"]:
                return publication_response["response"]

            if publication_response["error"]:
                handle_publication_notifications(
                    platform_info["name"],
                    status="failed",
                    country_code=decrypted_result.get("country_code"),
                    language=decoded_payload.get("language"),
                    additional_data=publication_response.get("refresh_alert"),
                )
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    publication_response["error"],
                    grpc.StatusCode.INVALID_ARGUMENT,
                    send_to_sentry=True,
                )

            handle_publication_notifications(
                platform_info["name"],
                status="published",
                country_code=decrypted_result.get("country_code"),
                language=decoded_payload.get("language"),
                additional_data=publication_response.get("refresh_alert"),
            )
            return response(
                message=f"Successfully published {platform_info['name']} message",
                publisher_response=publication_response["message"],
                success=True,
            )

        except NotImplementedError as e:
            return self.handle_create_grpc_error_response(
                context,
                response,
                str(e),
                grpc.StatusCode.UNIMPLEMENTED,
            )

        except Exception as exc:
            handle_publication_notifications(
                platform_info["name"],
                status="failed",
                country_code=decrypted_result.get("country_code"),
                language=decoded_payload.get("language"),
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

            adapter = AdapterManager.get_adapter_path(
                name=request.platform.lower(), protocol="pnba"
            )
            if not adapter:
                raise NotImplementedError(
                    f"The platform '{request.platform.lower()}' with "
                    "protocol 'pnba' is currently not supported. "
                    "Please contact the developers for more information on when "
                    "this platform will be implemented."
                )

            params = {
                "phone_number": request.phone_number,
                "base_path": adapter["assets_path"],
                "request_identifier": getattr(request, "request_identifier") or None,
            }

            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="send_authorization_code",
                params=params,
            )

            if pipe.get("error"):
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    pipe.get("error"),
                    grpc.StatusCode.INVALID_ARGUMENT,
                    error_type="UNKNOWN",
                )

            result = pipe.get("result")

            if not result.get("success"):
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    result.get("message"),
                    grpc.StatusCode.INVALID_ARGUMENT,
                )

            return response(success=True, message=result.get("message"))

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

        def store_token(userinfo):
            store_response, store_error = store_entity_token(
                long_lived_token=request.long_lived_token,
                platform=request.platform,
                account_identifier=userinfo.get("account_identifier"),
                token=json.dumps(userinfo.get("account_identifier")),
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

            adapter = AdapterManager.get_adapter_path(
                name=request.platform.lower(), protocol="pnba"
            )
            if not adapter:
                raise NotImplementedError(
                    f"The platform '{request.platform.lower()}' with "
                    "protocol 'pnba' is currently not supported. "
                    "Please contact the developers for more information on when "
                    "this platform will be implemented."
                )

            _, token_list_error = list_tokens()
            if token_list_error:
                return token_list_error

            params = {
                "code": request.authorization_code,
                "phone_number": request.phone_number,
                "base_path": adapter["assets_path"],
                "password": getattr(request, "password") or None,
                "request_identifier": getattr(request, "request_identifier") or None,
            }

            if params.get("password"):
                pipe = AdapterIPCHandler.invoke(
                    adapter_path=adapter["path"],
                    venv_path=adapter["venv_path"],
                    method="validate_password_and_fetch_user_info",
                    params=params,
                )
            else:
                pipe = AdapterIPCHandler.invoke(
                    adapter_path=adapter["path"],
                    venv_path=adapter["venv_path"],
                    method="validate_code_and_fetch_user_info",
                    params=params,
                )

            if pipe.get("error"):
                return self.handle_create_grpc_error_response(
                    context,
                    response,
                    pipe.get("error"),
                    grpc.StatusCode.INVALID_ARGUMENT,
                    error_type="UNKNOWN",
                )

            result = pipe.get("result")
            if result.get("two_step_verification_enabled"):
                return response(
                    success=True,
                    two_step_verification_enabled=True,
                    message="two-steps verification is enabled and a password is required",
                )

            return store_token(userinfo=result.get("userinfo"))

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

            adapter = AdapterManager.get_adapter_path(
                name=request.platform.lower(), protocol="pnba"
            )
            if not adapter:
                raise NotImplementedError(
                    f"The platform '{request.platform.lower()}' with "
                    "protocol 'pnba' is currently not supported. "
                    "Please contact the developers for more information on when "
                    "this platform will be implemented."
                )

            access_token, access_token_error = get_access_token()
            if access_token_error:
                return access_token_error

            params = {
                "phone_number": json.loads(access_token),
                "base_path": adapter["assets_path"],
            }

            pipe = AdapterIPCHandler.invoke(
                adapter_path=adapter["path"],
                venv_path=adapter["venv_path"],
                method="invalidate_session",
                params=params,
            )

            if pipe.get("error"):
                logger.error(pipe.get("error"))

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
