"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import base64
import struct
import types
from collections import namedtuple

FormatSpec = namedtuple("FormatSpec", ["key", "fmt", "decoding", "use_chr"])


def parse_payload(payload: bytes, format_spec: list) -> dict:
    """
    Parses a binary payload based on the provided format specification.

    Args:
        payload (bytes): The binary data to parse.
        format_spec (list[FormatSpec]): List of FormatSpec named tuples defining parsing rules.

    Returns:
        dict: Parsed key-value pairs from the payload.
    """
    result = {}
    offset = 0

    for spec in format_spec:
        fmt = spec.fmt
        if isinstance(fmt, types.FunctionType):
            fmt = fmt(result)

        if isinstance(fmt, int):
            value = payload[offset] if fmt == 1 else payload[offset : offset + fmt]
            offset += fmt
            if fmt == 1 and spec.use_chr:
                value = chr(value)
        else:
            size = struct.calcsize(fmt)
            value = struct.unpack(fmt, payload[offset : offset + size])[0]
            offset += size

        if spec.decoding:
            value = value.decode(spec.decoding)

        result[spec.key] = value

    return result


def decode_v0(payload: bytes) -> tuple:
    """Decodes version 0 content.

    Args:
        payload (bytes): The binary data to decode.

    Returns:
        tuple: A dictionary of parsed values and an optional error.
    """
    parsers = [
        FormatSpec(key="len_ciphertext", fmt="<i", decoding=None, use_chr=False),
        FormatSpec(key="platform_shortcode", fmt=1, decoding=None, use_chr=True),
        FormatSpec(
            key="ciphertext",
            fmt=lambda d: d["len_ciphertext"],
            decoding=None,
            use_chr=False,
        ),
        FormatSpec(
            key="device_id",
            fmt=lambda d: len(payload) - (5 + d["len_ciphertext"]),
            decoding=None,
            use_chr=False,
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
        FormatSpec(key="len_ciphertext", fmt="<H", decoding=None, use_chr=False),
        FormatSpec(key="len_device_id", fmt=1, decoding=None, use_chr=False),
        FormatSpec(key="platform_shortcode", fmt=1, decoding=None, use_chr=True),
        FormatSpec(
            key="ciphertext",
            fmt=lambda d: d["len_ciphertext"],
            decoding=None,
            use_chr=False,
        ),
        FormatSpec(
            key="device_id",
            fmt=lambda d: d["len_device_id"],
            decoding=None,
            use_chr=False,
        ),
        FormatSpec(
            key="language",
            fmt=2,
            decoding="utf-8",
            use_chr=False,
        ),
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


def extract_content(service_type: str, content: str) -> tuple:
    """
    Extracts components based on the specified service_type.

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

    return None, "Invalid service_type. Must be 'email', 'text', or 'message'."


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
