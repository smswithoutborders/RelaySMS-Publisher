# SPDX-License-Identifier: GPL-3.0-only
"""Publish Content gRPC Service Implementation"""

import base64
import datetime
import json

import grpc

from content_parser import (
    decode_content,
    extract_content_v0,
    extract_content_v1,
    extract_content_v2,
)
from logutils import get_logger
from notification_dispatcher import dispatch_notifications
from platforms.adapter_ipc_handler import AdapterIPCHandler
from platforms.adapter_manager import AdapterManager
from protos.v1 import publisher_pb2
from translations import Localization
from utils import get_configs
from vault_clients.v1.grpc_client import get_entity_access_token, update_entity_token
from vault_clients.v2.grpc_client import decrypt_payload

MOCK_DELIVERY_SMS = (
    get_configs("MOCK_DELIVERY_SMS", default_value="true") or ""
).lower() == "true"

logger = get_logger(__name__)
loc = Localization()
t = loc.translate


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

    def get_access_token(device_id, phone_number, platform_name, account_identifier):
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

    def handle_oauth2_publication(service_type, platform_name, content_parts, **kwargs):
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
            "message": lambda parts: {
                "sender_id": parts[0],
                "recipient": parts[1],
                "message": parts[2],
                "access_token": parts[3],
                "refresh_token": parts[4],
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

    def handle_pnba_publication(service_type, platform_name, content_parts, **kwargs):
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
