"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import base64
import struct
from collections import namedtuple

FormatSpec = namedtuple("FormatSpec", ["key", "fmt", "decoding"])


def parse_payload(payload: bytes, format_spec: list) -> dict:
    """
    Parses a binary payload based on the provided format specification.

    Args:
        payload (bytes): The binary data to parse.
        format_spec (list[FormatSpec]): List of FormatSpec named tuples defining parsing rules.

    Returns:
        dict: Parsed key-value pairs from the payload.
    """
    result, offset = {}, 0
    total_len = len(payload)

    for spec in format_spec:
        fmt = spec.fmt(result) if callable(spec.fmt) else spec.fmt
        if isinstance(fmt, int):
            fmt = f"{fmt}s"

        size = struct.calcsize(fmt)
        if offset + size > total_len:
            break

        (value,) = struct.unpack_from(fmt, payload, offset)
        offset += size

        if spec.decoding and isinstance(value, (bytes, bytearray)):
            value = value.decode(spec.decoding)

        result[spec.key] = value

    for spec in format_spec:
        if spec.key not in result:
            default = "" if spec.decoding else b""
            result[spec.key] = default

    return result


def decode_v0(payload: bytes) -> tuple:
    """Decodes version 0 content.

    Args:
        payload (bytes): The binary data to decode.

    Returns:
        tuple: A dictionary of parsed values and an optional error.
    """
    parsers = [
        FormatSpec(key="len_ciphertext", fmt="<i", decoding=None),
        FormatSpec(key="platform_shortcode", fmt=1, decoding="ascii"),
        FormatSpec(key="ciphertext", fmt=lambda d: d["len_ciphertext"], decoding=None),
        FormatSpec(
            key="device_id",
            fmt=lambda d: len(payload) - (5 + d["len_ciphertext"]),
            decoding=None,
        ),
    ]

    try:
        result = parse_payload(payload, parsers)
        return result, None
    except Exception as e:
        return None, e


def decode_v1(payload: bytes) -> tuple:
    """Decodes version 1 content.

    Args:
        payload (bytes): The binary data to decode.

    Returns:
        tuple: A dictionary of parsed values and an optional error.
    """
    version = f"v{payload[0]}"
    parsers = [
        FormatSpec(key="len_ciphertext", fmt="<H", decoding=None),
        FormatSpec(key="len_device_id", fmt="<B", decoding=None),
        FormatSpec(key="platform_shortcode", fmt=1, decoding="ascii"),
        FormatSpec(key="ciphertext", fmt=lambda d: d["len_ciphertext"], decoding=None),
        FormatSpec(key="device_id", fmt=lambda d: d["len_device_id"], decoding=None),
        FormatSpec(key="language", fmt=2, decoding="ascii"),
    ]

    try:
        result = parse_payload(payload[1:], parsers)
        result["version"] = version
        return result, None
    except Exception as e:
        return None, e


def decode_content(content: str) -> tuple:
    """Decodes a base64-encoded content payload.

    Args:
        content (str): The base64-encoded string to decode.

    Returns:
        tuple: A dictionary of parsed values and an optional error.
    """
    try:
        payload = base64.b64decode(content)
        if is_v0_payload(payload):
            return decode_v0(payload)
        return decode_v1(payload)
    except Exception as e:
        return None, e


def extract_content_v0(service_type: str, content: str) -> tuple:
    """
    Extracts components based on the specified service_type for v0 format.

    Args:
        service_type (str): The type of the platform (email, text, message).
        content (str): The content string to extract from.

    Returns:
        tuple: A tuple containing:
            - parts (tuple): A tuple with the parsed components based on the service_type.
            - error (str): An error message if extraction fails, otherwise None.
    """
    if service_type == "email":
        # Email format: 'from:to:cc:bcc:subject:body[:access_token:refresh_token]'
        parts = content.split(":", 7)
        if len(parts) < 6:
            return None, "Email content must have at least 6 parts."
        from_email, to_email, cc_email, bcc_email, subject, body = parts[:6]
        access_token = parts[6] if len(parts) > 6 else None
        refresh_token = parts[7] if len(parts) > 7 else None
        return (
            from_email,
            to_email,
            cc_email,
            bcc_email,
            subject,
            body,
            access_token,
            refresh_token,
        ), None

    if service_type == "text":
        # Text format: 'sender:text[:access_token:refresh_token]'
        parts = content.split(":", 3)
        if len(parts) < 2:
            return None, "Text content must have at least 2 parts."
        sender, text = parts[:2]
        access_token = parts[2] if len(parts) > 2 else None
        refresh_token = parts[3] if len(parts) > 3 else None
        return (sender, text, access_token, refresh_token), None

    if service_type == "message":
        # Message format: 'sender:receiver:message'
        parts = content.split(":", 2)
        if len(parts) != 3:
            return None, "Message content must have exactly 3 parts."
        sender, receiver, message = parts
        return (sender, receiver, message), None

    if service_type == "test":
        # Test format: 'test_id'
        return (content,), None

    return None, "Invalid service_type. Must be 'email', 'text', 'message', or 'test'."


def extract_content_v1(service_type: str, content: bytes) -> tuple:
    """
    Extracts components from the packed content for v1 format based on the specified service_type.

    Args:
        service_type (str): The type of the platform (email, text, message).
        content (bytes): The packed binary content to extract.

    Returns:
        tuple: A tuple containing:
            - parts (tuple): A tuple with the parsed components based on the service_type.
            - error (str): An error message if extraction fails, otherwise None.
    """
    parsers = [
        FormatSpec(key="length_from", fmt="<B", decoding=None),
        FormatSpec(key="length_to", fmt="<H", decoding=None),
        FormatSpec(key="length_cc", fmt="<H", decoding=None),
        FormatSpec(key="length_bcc", fmt="<H", decoding=None),
        FormatSpec(key="length_subject", fmt="<B", decoding=None),
        FormatSpec(key="length_body", fmt="<H", decoding=None),
        FormatSpec(key="length_access_token", fmt="<B", decoding=None),
        FormatSpec(key="length_refresh_token", fmt="<B", decoding=None),
        FormatSpec(key="from", fmt=lambda d: d["length_from"], decoding="utf-8"),
        FormatSpec(key="to", fmt=lambda d: d["length_to"], decoding="utf-8"),
        FormatSpec(key="cc", fmt=lambda d: d["length_cc"], decoding="utf-8"),
        FormatSpec(key="bcc", fmt=lambda d: d["length_bcc"], decoding="utf-8"),
        FormatSpec(key="subject", fmt=lambda d: d["length_subject"], decoding="utf-8"),
        FormatSpec(key="body", fmt=lambda d: d["length_body"], decoding="utf-8"),
        FormatSpec(
            key="access_token", fmt=lambda d: d["length_access_token"], decoding="utf-8"
        ),
        FormatSpec(
            key="refresh_token",
            fmt=lambda d: d["length_refresh_token"],
            decoding="utf-8",
        ),
    ]

    try:
        result = parse_payload(content, parsers)

        if service_type == "email":
            return (
                result["from"],
                result["to"],
                result["cc"],
                result["bcc"],
                result["subject"],
                result["body"],
                result.get("access_token"),
                result.get("refresh_token"),
            ), None

        if service_type == "text":
            return (
                result["from"],
                result["body"],
                result.get("access_token"),
                result.get("refresh_token"),
            ), None

        if service_type == "message":
            return (
                result["from"],
                result["to"],
                result["body"],
                result.get("access_token"),
                result.get("refresh_token"),
            ), None

        if service_type == "test":
            return (result["from"],), None

        return (
            None,
            "Invalid service_type. Must be 'email', 'text', 'message', or 'test'.",
        )
    except Exception as e:
        return None, e


def extract_content_v2(service_type: str, content: bytes) -> tuple:
    """
    Extracts components from the packed content for v2 format based on the specified service_type.

    Args:
        service_type (str): The type of the platform (email, text, message).
        content (bytes): The packed binary content to extract.

    Returns:
        tuple: A tuple containing:
            - parts (tuple): A tuple with the parsed components based on the service_type.
            - error (str): An error message if extraction fails, otherwise None.
    """
    parsers = [
        FormatSpec(key="length_from", fmt="<B", decoding=None),
        FormatSpec(key="length_to", fmt="<H", decoding=None),
        FormatSpec(key="length_cc", fmt="<H", decoding=None),
        FormatSpec(key="length_bcc", fmt="<H", decoding=None),
        FormatSpec(key="length_subject", fmt="<B", decoding=None),
        FormatSpec(key="length_body", fmt="<H", decoding=None),
        FormatSpec(key="length_access_token", fmt="<H", decoding=None),
        FormatSpec(key="length_refresh_token", fmt="<H", decoding=None),
        FormatSpec(key="from", fmt=lambda d: d["length_from"], decoding="utf-8"),
        FormatSpec(key="to", fmt=lambda d: d["length_to"], decoding="utf-8"),
        FormatSpec(key="cc", fmt=lambda d: d["length_cc"], decoding="utf-8"),
        FormatSpec(key="bcc", fmt=lambda d: d["length_bcc"], decoding="utf-8"),
        FormatSpec(key="subject", fmt=lambda d: d["length_subject"], decoding="utf-8"),
        FormatSpec(key="body", fmt=lambda d: d["length_body"], decoding="utf-8"),
        FormatSpec(
            key="access_token", fmt=lambda d: d["length_access_token"], decoding="utf-8"
        ),
        FormatSpec(
            key="refresh_token",
            fmt=lambda d: d["length_refresh_token"],
            decoding="utf-8",
        ),
    ]

    try:
        result = parse_payload(content, parsers)

        if service_type == "email":
            return (
                result["from"],
                result["to"],
                result["cc"],
                result["bcc"],
                result["subject"],
                result["body"],
                result.get("access_token"),
                result.get("refresh_token"),
            ), None

        if service_type == "text":
            return (
                result["from"],
                result["body"],
                result.get("access_token"),
                result.get("refresh_token"),
            ), None

        if service_type == "message":
            return (
                result["from"],
                result["to"],
                result["body"],
                result.get("access_token"),
                result.get("refresh_token"),
            ), None

        if service_type == "test":
            return (result["from"],), None

        return (
            None,
            "Invalid service_type. Must be 'email', 'text', 'message', or 'test'.",
        )
    except Exception as e:
        return None, e


def is_v0_payload(payload):
    """Determines if the given payload follows v0 format."""
    try:
        # Ensure at least 5 bytes exist (4 for length + 1 for platform_shortcode)
        if len(payload) < 5:
            return False

        # Extract the first 4 bytes as a little-endian integer (ciphertext length)
        ciphertext_length = struct.unpack("<i", payload[:4])[0]

        # Ensure ciphertext_length is non-negative
        if ciphertext_length < 0:
            return False

        # Ensure the payload has enough bytes for ciphertext + device_id
        if len(payload) >= (4 + 1 + ciphertext_length):
            return True

        return False
    except Exception:
        return False
