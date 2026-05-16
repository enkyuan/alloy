"""Custom SQLAlchemy column types."""

from __future__ import annotations

from typing import Optional

from sqlalchemy.types import Text, TypeDecorator

from sdk.core.crypto import decrypt_secret, encrypt_secret


class EncryptedText(TypeDecorator[str]):
    """Text column that encrypts on write and decrypts on read."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Optional[str], dialect) -> Optional[str]:
        if value is None:
            return None
        return encrypt_secret(str(value))

    def process_result_value(self, value: Optional[str], dialect) -> Optional[str]:
        if value is None:
            return None
        return decrypt_secret(str(value))
