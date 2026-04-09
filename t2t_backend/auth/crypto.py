"""
auth/crypto.py — Ed25519 cryptographic signing and verification.

Used for non-repudiation: every T2T message is signed by the sender's
private key, and verified by the router using the sender's public key.

Keys are generated using PyNaCl (libsodium bindings).
"""
from __future__ import annotations

import base64
import logging

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey

logger = logging.getLogger(__name__)


def generate_keypair() -> tuple[str, str]:
    """
    Generate an Ed25519 keypair.

    Returns:
        (private_key_b64, public_key_b64) — both base64-encoded.
    """
    signing_key = SigningKey.generate()
    private_b64 = base64.b64encode(signing_key.encode()).decode()
    public_b64 = base64.b64encode(signing_key.verify_key.encode()).decode()
    return private_b64, public_b64


def sign_message(private_key_b64: str, message_bytes: bytes) -> str:
    """
    Sign arbitrary bytes with an Ed25519 private key.

    Args:
        private_key_b64: Base64-encoded 32-byte seed.
        message_bytes:   The canonical bytes to sign.

    Returns:
        Base64-encoded signature string.
    """
    seed = base64.b64decode(private_key_b64)
    signing_key = SigningKey(seed)
    signed = signing_key.sign(message_bytes)
    return base64.b64encode(signed.signature).decode()


def verify_signature(
    public_key_b64: str,
    message_bytes: bytes,
    signature_b64: str,
) -> bool:
    """
    Verify an Ed25519 signature against a public key.

    Args:
        public_key_b64: Base64-encoded 32-byte public key.
        message_bytes:  The canonical bytes that were signed.
        signature_b64:  Base64-encoded 64-byte signature.

    Returns:
        True if valid, False if invalid or malformed.
    """
    try:
        pub_bytes = base64.b64decode(public_key_b64)
        sig_bytes = base64.b64decode(signature_b64)
        verify_key = VerifyKey(pub_bytes)
        verify_key.verify(message_bytes, sig_bytes)
        return True
    except (BadSignatureError, Exception) as exc:
        logger.warning("Signature verification failed: %s", exc)
        return False
