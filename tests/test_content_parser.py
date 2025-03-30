"""
This program is free software: you can redistribute it under the terms
of the GNU General Public License, v. 3.0. If a copy of the GNU General
Public License was not distributed with this file, see <https://www.gnu.org/licenses/>.
"""

import base64
import struct
import pytest
from content_parser import (
    decode_v0,
    decode_v1,
    decode_content,
    extract_content,
)


@pytest.mark.parametrize(
    "payload, expected",
    [
        (
            struct.pack("<i", 4) + b"key1",
            {
                "len_ciphertext": 4,
                "platform_shortcode": "k",
                "ciphertext": b"ey1",
                "device_id": b"",
            },
        ),
        (
            struct.pack("<i", 5) + b"key123extra",
            {
                "len_ciphertext": 5,
                "platform_shortcode": "k",
                "ciphertext": b"ey123",
                "device_id": b"extra",
            },
        ),
    ],
)
def test_decode_v0_valid(payload, expected):
    result, error = decode_v0(payload)
    assert error is None
    assert result == expected


@pytest.mark.parametrize(
    "payload, expected",
    [
        (
            b"\x0a\x00" + struct.pack("<H", 5) + b"\x00\x00\x00eabcde",
            {
                "version": "v1",
                "len_ciphertext": 5,
                "len_device_id": 0,
                "len_access_token": 0,
                "len_refresh_token": 0,
                "platform_shortcode": "e",
                "ciphertext": b"abcde",
                "device_id": b"",
                "access_token": b"",
                "refresh_token": b"",
                "language": "",
            },
        ),
        (
            b"\x0a\x00" + struct.pack("<H", 3) + b"\x05\x05\x05txyz11223a1122b2233fr",
            {
                "version": "v1",
                "len_ciphertext": 3,
                "len_device_id": 5,
                "len_access_token": 5,
                "len_refresh_token": 5,
                "platform_shortcode": "t",
                "ciphertext": b"xyz",
                "device_id": b"11223",
                "access_token": b"a1122",
                "refresh_token": b"b2233",
                "language": "fr",
            },
        ),
    ],
)
def test_decode_v1_valid(payload, expected):
    result, error = decode_v1(payload)
    assert error is None
    assert result == expected


@pytest.mark.parametrize("payload", [b"\x0a\x05invalid"])
def test_decode_v1_invalid(payload):
    result, error = decode_v1(payload)
    assert result is None
    assert isinstance(error, ValueError)


@pytest.mark.parametrize(
    "content, expected",
    [
        (
            base64.b64encode(struct.pack("<i", 3) + b"xyz").decode(),
            {
                "len_ciphertext": 3,
                "platform_shortcode": "x",
                "ciphertext": b"yz",
                "device_id": b"",
            },
        ),
        (
            base64.b64encode(
                b"\x0a\x00" + struct.pack("<H", 4) + b"\x00\x00\x00edatafr"
            ).decode(),
            {
                "version": "v1",
                "len_ciphertext": 4,
                "len_device_id": 0,
                "len_access_token": 0,
                "len_refresh_token": 0,
                "platform_shortcode": "e",
                "ciphertext": b"data",
                "device_id": b"",
                "access_token": b"",
                "refresh_token": b"",
                "language": "fr",
            },
        ),
    ],
)
def test_decode_content_valid(content, expected):
    result, error = decode_content(content)
    assert error is None
    assert result == expected


@pytest.mark.parametrize("content", ["invalidbase64=="])
def test_decode_content_invalid(content):
    result, error = decode_content(content)
    assert result is None
    assert isinstance(error, Exception)


@pytest.mark.parametrize(
    "service_type, content, expected",
    [
        (
            "email",
            "from:to:cc:bcc:subject:body",
            ("from", "to", "cc", "bcc", "subject", "body"),
        ),
        (
            "text",
            "sender:text",
            ("sender", "text"),
        ),
        (
            "message",
            "sender:receiver:message",
            ("sender", "receiver", "message"),
        ),
    ],
)
def test_extract_content_valid(service_type, content, expected):
    result, error = extract_content(service_type, content)
    assert error is None
    assert result == expected


@pytest.mark.parametrize(
    "service_type, content",
    [
        ("email", "from:to:cc:bcc:subject"),  # Missing body
        ("text", "sender"),  # Missing text
        ("message", "sender:receiver"),  # Missing message
        ("unknown", "data"),  # Invalid service type
    ],
)
def test_extract_content_invalid(service_type, content):
    result, error = extract_content(service_type, content)
    assert result is None
    assert isinstance(error, str)
