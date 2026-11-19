"""
Field-level encryption for client personal details (Kenya Data Protection Act 2019:
security safeguards and data minimisation).

Names, phone numbers, villages and dates of birth are encrypted with Fernet
(AES-128 + HMAC) before they reach the database, and decrypted only inside the
application. Anyone who opens the database directly (pgAdmin, a backup file)
sees unreadable text such as "gAAAAABn...".
"""
from datetime import date

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from .config import ENCRYPTION_KEY

_fernet: Fernet | None = None


def get_fernet() -> Fernet:
    """Builds the cipher once. Fails with a clear message if the key is missing or invalid."""
    global _fernet
    if _fernet is None:
        if not ENCRYPTION_KEY:
            raise RuntimeError(
                "ENCRYPTION_KEY is not set in backend/.env. Generate one with:\n"
                '  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"')
        try:
            _fernet = Fernet(ENCRYPTION_KEY.encode())
        except ValueError as exc:
            raise RuntimeError("ENCRYPTION_KEY in backend/.env is not a valid Fernet key.") from exc
    return _fernet


def encrypt(text: str) -> str:
    return get_fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Client details cannot be decrypted: ENCRYPTION_KEY has changed.") from exc


class EncryptedString(TypeDecorator):
    """A text column that is stored encrypted and read back as plain text."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(value)

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt(value)


class EncryptedDate(TypeDecorator):
    """A date column that is stored encrypted (as text) and read back as a date."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(value.isoformat())

    def process_result_value(self, value, dialect):
        return None if value is None else date.fromisoformat(decrypt(value))


def mask_name(full_name: str | None) -> str | None:
    """Initials only, for users who may not see the full name: "Mary Wanjiru" -> "M. W." """
    if not full_name:
        return None
    return " ".join(f"{part[0].upper()}." for part in full_name.split())