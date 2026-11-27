"""Password, token, CSRF, credential encryption, and login protection helpers."""

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

from app.core.config import settings

password_hasher = PasswordHasher(type=Type.ID)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters")
    if not any(char.isupper() for char in password):
        raise ValueError("Password must contain an uppercase letter")
    if not any(char.islower() for char in password):
        raise ValueError("Password must contain a lowercase letter")
    if not any(char.isdigit() for char in password):
        raise ValueError("Password must contain a digit")


def new_token() -> str:
    return secrets.token_urlsafe(48)


def token_digest(token: str) -> str:
    return hmac.new(settings.secret_key.encode(), token.encode(), hashlib.sha512).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def expires_in(minutes: int) -> datetime:
    return utcnow() + timedelta(minutes=minutes)


def is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= utcnow()


def _derive_encryption_keys() -> tuple[bytes, bytes]:
    master = settings.secret_key.encode("utf-8")
    enc_key = hmac.new(master, b"jobhunter-enc-key-v1", hashlib.sha256).digest()
    mac_key = hmac.new(master, b"jobhunter-mac-key-v1", hashlib.sha256).digest()
    return enc_key, mac_key


def encrypt_secret(plaintext: str) -> str:
    """Encrypt third-party credentials using authenticated Encrypt-then-MAC (v1)."""
    enc_key, mac_key = _derive_encryption_keys()
    nonce = os.urandom(16)
    data = plaintext.encode("utf-8")
    out = bytearray(len(data))
    counter = 0
    pos = 0
    while pos < len(data):
        block = hashlib.sha256(enc_key + nonce + counter.to_bytes(4, "big")).digest()
        chunk = data[pos : pos + len(block)]
        for i, byte in enumerate(chunk):
            out[pos + i] = byte ^ block[i]
        pos += len(block)
        counter += 1
    ciphertext = bytes(out)
    tag = hmac.new(mac_key, b"v1:" + nonce + ciphertext, hashlib.sha256).digest()
    return "v1:" + base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")


def decrypt_secret(token: str) -> str:
    """Decrypt and authenticate third-party credentials encrypted with encrypt_secret."""
    if not token.startswith("v1:"):
        raise ValueError("Unsupported encrypted secret version")
    raw = base64.urlsafe_b64decode(token[3:].encode("ascii"))
    if len(raw) < 48:
        raise ValueError("Invalid encrypted secret payload")
    nonce, tag, ciphertext = raw[:16], raw[16:48], raw[48:]
    enc_key, mac_key = _derive_encryption_keys()
    expected = hmac.new(mac_key, b"v1:" + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("Encrypted secret authentication failed")
    out = bytearray(len(ciphertext))
    counter = 0
    pos = 0
    while pos < len(ciphertext):
        block = hashlib.sha256(enc_key + nonce + counter.to_bytes(4, "big")).digest()
        chunk = ciphertext[pos : pos + len(block)]
        for i, byte in enumerate(chunk):
            out[pos + i] = byte ^ block[i]
        pos += len(block)
        counter += 1
    return bytes(out).decode("utf-8")
