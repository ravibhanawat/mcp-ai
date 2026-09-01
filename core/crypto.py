"""
Encryption at rest for AI provider credentials.

Provider API keys are the only secrets this application stores that a third
party can spend money with, so they never touch disk in plaintext and never
leave the process in either form.

`SecretBox` is an interface rather than a function so a Vault or KMS backend can
replace `EnvKeyBox` later without touching a single call site. Only `EnvKeyBox`
is implemented; adding others before there is a deployment that needs one would
be speculative.

A missing or wrong key is deliberately NOT fatal at import or construction time.
The application must still boot and serve conversational traffic; only the
credentialed providers degrade, reporting `credential_unavailable`.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod

from cryptography.fernet import Fernet, InvalidToken

#: Bumped only when the encryption scheme changes, not when the key rotates.
#: The column exists so a rotation pass can decrypt old rows while writing new.
CURRENT_KEY_VERSION = 1

_ENV_VAR = "AI_CONFIG_KEY"


class MissingKeyError(RuntimeError):
    """Raised when the encryption key is absent, malformed, or does not match."""


class SecretBox(ABC):
    """Encrypts and decrypts provider credentials."""

    @abstractmethod
    def encrypt(self, plaintext: str) -> tuple[bytes, int]:
        """Return (ciphertext, key_version)."""

    @abstractmethod
    def decrypt(self, ciphertext: bytes, key_version: int) -> str:
        """Return the plaintext, or raise MissingKeyError."""


class EnvKeyBox(SecretBox):
    """Fernet encryption with the key supplied via the AI_CONFIG_KEY env var.

    Generate one with:
        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """

    def _fernet(self) -> Fernet:
        raw = os.environ.get(_ENV_VAR, "").strip()
        if not raw:
            raise MissingKeyError(
                f"{_ENV_VAR} is not set. AI provider credentials cannot be read or "
                "written until it is. Generate one with: python -c "
                '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        try:
            return Fernet(raw.encode())
        except Exception as exc:
            raise MissingKeyError(f"{_ENV_VAR} is not a valid Fernet key.") from exc

    def encrypt(self, plaintext: str) -> tuple[bytes, int]:
        return self._fernet().encrypt(plaintext.encode()), CURRENT_KEY_VERSION

    def decrypt(self, ciphertext: bytes, key_version: int) -> str:
        if key_version != CURRENT_KEY_VERSION:
            raise MissingKeyError(
                f"Credential was encrypted with key version {key_version}; "
                f"this build understands version {CURRENT_KEY_VERSION}."
            )
        try:
            return self._fernet().decrypt(ciphertext).decode()
        except InvalidToken as exc:
            raise MissingKeyError(
                f"Credential could not be decrypted. {_ENV_VAR} may have changed "
                "since it was stored; re-enter the provider's API key."
            ) from exc


def get_secret_box() -> SecretBox:
    """Return the configured SecretBox implementation."""
    return EnvKeyBox()


def last4(plaintext: str) -> str:
    """Return the last four characters, used for display only."""
    return plaintext[-4:] if len(plaintext) >= 4 else ""


def mask_secret(plaintext: str) -> str:
    """Render a secret for display: 'sk-****wxyz'. Never reveals more than 4 chars."""
    if not plaintext:
        return ""
    tail = last4(plaintext)
    if not tail:
        return "****"
    prefix = plaintext[:3] if plaintext.startswith("sk-") else ""
    return f"{prefix}****{tail}"
