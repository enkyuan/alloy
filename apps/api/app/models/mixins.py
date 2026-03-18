"""Shared model mixins."""

from typing import Optional

from sqlalchemy.orm import Mapped


class MetadataJsonMixin:
    """Mixin providing a ``metadata_json`` property alias for ``meta_data``.

    SQLAlchemy reserves the ``metadata`` attribute on mapped classes, so the
    underlying column is named ``meta_data``.  This mixin adds a cleaner
    ``metadata_json`` property so callers don't have to remember the
    workaround.

    The concrete model must declare::

        meta_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    """

    meta_data: Mapped[Optional[dict]]

    @property
    def metadata_json(self) -> Optional[dict]:
        return self.meta_data

    @metadata_json.setter
    def metadata_json(self, value: Optional[dict]) -> None:
        self.meta_data = value
