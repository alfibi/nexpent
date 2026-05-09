import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from config import JWT_SECRET_KEY, TOKEN_ENCRYPTION_KEY


def _derive_key() -> bytes:
    raw_key = TOKEN_ENCRYPTION_KEY or JWT_SECRET_KEY
    if raw_key.startswith("fernet:"):
        return raw_key.replace("fernet:", "", 1).encode()
    digest = hashlib.sha256(raw_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_key())


def encrypt_value(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


def decrypt_value(value: str) -> str:
    try:
        return _fernet.decrypt(value.encode()).decode()
    except InvalidToken:
        return ""

