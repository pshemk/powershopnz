"""PowerShop NZ persistent storage."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store


STORAGE_VERSION = 1

import logging
_LOGGER = logging.getLogger(__name__)


class PowershopStore:
    """Persistent storage for one Powershop account."""

    def __init__(
        self,
        hass: HomeAssistant,
        account_id: str,
    ) -> None:
        """Initialize the storage."""

        self._store = Store[dict[str, Any]](
            hass,
            STORAGE_VERSION,
            f"powershopnz_{account_id}",
        )

        self.data: dict[str, Any] = {}

    async def async_load(self) -> dict[str, Any]:
        """Load persisted data."""

        data = await self._store.async_load()

        if data is not None:
            self.data = data

    async def async_save(
        self,
        data: dict[str, Any],
    ) -> None:
        """Save data to persistent storage."""

        self.data = data
        await self._store.async_save(self.data)