# SPDX-License-Identifier: GPL-3.0-only
"""AES-256-GCM for encrypted database fields. The nonce prefixes the ciphertext."""

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12


def encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(NONCE_SIZE)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt(key: bytes, data: bytes) -> bytes:
    nonce, ciphertext = data[:NONCE_SIZE], data[NONCE_SIZE:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)
