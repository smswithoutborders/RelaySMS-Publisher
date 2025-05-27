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
    extract_content_v0,
    extract_content_v1,
)


@pytest.mark.parametrize(
    "payload, expected",
    [
        (
            struct.pack("<i", 3) + b"key1",
            {
                "len_ciphertext": 3,
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
            b"\x01" + struct.pack("<H", 5) + b"\x00eabcde",
            {
                "version": "v1",
                "len_ciphertext": 5,
                "len_device_id": 0,
                "platform_shortcode": "e",
                "ciphertext": b"abcde",
                "device_id": b"",
                "language": "",
            },
        ),
        (
            b"\x01" + struct.pack("<H", 3) + b"\x05txyz11223fr",
            {
                "version": "v1",
                "len_ciphertext": 3,
                "len_device_id": 5,
                "platform_shortcode": "t",
                "ciphertext": b"xyz",
                "device_id": b"11223",
                "language": "fr",
            },
        ),
    ],
)
def test_decode_v1_valid(payload, expected):
    result, error = decode_v1(payload)
    assert error is None
    assert result == expected


@pytest.mark.parametrize(
    "content, expected",
    [
        (
            base64.b64encode(struct.pack("<i", 3) + b"xyza").decode(),
            {
                "len_ciphertext": 3,
                "platform_shortcode": "x",
                "ciphertext": b"yza",
                "device_id": b"",
            },
        ),
        (
            base64.b64encode(b"\x01" + struct.pack("<H", 4) + b"\x00edatafr").decode(),
            {
                "version": "v1",
                "len_ciphertext": 4,
                "len_device_id": 0,
                "platform_shortcode": "e",
                "ciphertext": b"data",
                "device_id": b"",
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
            ("from", "to", "cc", "bcc", "subject", "body", None, None),
        ),
        (
            "email",
            "from:to:cc:bcc:subject:body:access_token:refresh_token",
            (
                "from",
                "to",
                "cc",
                "bcc",
                "subject",
                "body",
                "access_token",
                "refresh_token",
            ),
        ),
        (
            "text",
            "sender:text",
            ("sender", "text", None, None),
        ),
        (
            "text",
            "sender:text:access_token:refresh_token",
            ("sender", "text", "access_token", "refresh_token"),
        ),
        (
            "message",
            "sender:receiver:message",
            ("sender", "receiver", "message"),
        ),
    ],
)
def test_extract_content_v0_valid(service_type, content, expected):
    result, error = extract_content_v0(service_type, content)
    assert error is None
    assert result == expected


@pytest.mark.parametrize(
    "content, service_type, expected",
    [
        (
            struct.pack("<BHHHBHBB", 4, 2, 2, 3, 7, 4, 12, 13)
            + b"fromtoccbccsubjectbodyaccess_tokenrefresh_token",
            "email",
            (
                "from",
                "to",
                "cc",
                "bcc",
                "subject",
                "body",
                "access_token",
                "refresh_token",
            ),
        ),
        (
            struct.pack("<BHHHBHBB", 4, 0, 0, 0, 7, 4, 0, 0) + b"fromsubjectbody",
            "email",
            (
                "from",
                "",
                "",
                "",
                "subject",
                "body",
                "",
                "",
            ),
        ),
        (
            struct.pack("<BHHHBHBB", 4, 0, 0, 0, 0, 4, 5, 7) + b"frombodytokenrefresh",
            "text",
            (
                "from",
                "body",
                "token",
                "refresh",
            ),
        ),
        (
            struct.pack("<BHHHBHBB", 4, 2, 0, 0, 0, 4, 0, 0)
            + b"fromtobodytokenrefresh",
            "message",
            (
                "from",
                "to",
                "body",
            ),
        ),
    ],
)
def test_extract_content_v1_valid(content, service_type, expected):
    result, error = extract_content_v1(service_type, content)
    assert error is None
    assert result == expected
