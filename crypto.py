# SPDX-License-Identifier: GPL-3.0-only
"""Cryptographic functions for database field encryption."""

import os
from typing import Callable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def aes_256_gcm_encrypt(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt data using AES-256-GCM.

    Args:
        key: 32-byte encryption key
        plaintext: Data to encrypt

    Returns:
        Nonce (12 bytes) + ciphertext
    """
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def aes_256_gcm_decrypt(key: bytes, ciphertext_with_nonce: bytes) -> bytes:
    """Decrypt data using AES-256-GCM.

    Args:
        key: 32-byte encryption key
        ciphertext_with_nonce: Nonce (12 bytes) + ciphertext

    Returns:
        Decrypted plaintext
    """
    nonce = ciphertext_with_nonce[:12]
    ciphertext = ciphertext_with_nonce[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def get_encryption_algorithm(
    algorithm: str = "aes-256-gcm",
) -> tuple[Callable[[bytes, bytes], bytes], Callable[[bytes, bytes], bytes]]:
    """Get encryption and decryption functions for the specified algorithm.

    Args:
        algorithm: Encryption algorithm name (default: "aes-256-gcm")

    Returns:
        Tuple of (encrypt_func, decrypt_func)

    Raises:
        ValueError: If algorithm is not supported
    """
    algorithms = {
        "aes-256-gcm": (aes_256_gcm_encrypt, aes_256_gcm_decrypt),
    }

    if algorithm not in algorithms:
        raise ValueError(
            f"Unsupported encryption algorithm: {algorithm}. "
            f"Supported: {', '.join(algorithms.keys())}"
        )

    return algorithms[algorithm]
