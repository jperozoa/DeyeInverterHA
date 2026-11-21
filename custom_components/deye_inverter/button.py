"""Button entities: one-shot actions."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, REG_CLOCK
from .coordinator import DeyeDataUpdateCoordinator
from .InverterDataParser import encode_clock
from .sensor import _inverter_device_info


async def async_setup_entry(
    hass: Any, entry: Any, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the button platform."""
    coordinator: DeyeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DeyeSyncClockButton(coordinator)], update_before_add=False)


class DeyeSyncClockButton(CoordinatorEntity[DeyeDataUpdateCoordinator], ButtonEntity):
    """Set the inverter's clock to Home Assistant's local time.

    The time-of-use program runs on the inverter's own clock, which drifts
    and is never corrected unless the app does it.
    """

    _attr_has_entity_name = True
    _attr_name = "Sync Clock"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator: DeyeDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        serial = getattr(coordinator, "serial", "unknown")
        self._attr_unique_id = f"{serial}_sync_clock"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the Deye inverter."""
        return _inverter_device_info(self.coordinator)

    async def async_press(self) -> None:
        """Write the current local time into the three clock registers."""
        now = dt_util.now()
        await self.coordinator.async_write_registers(
            REG_CLOCK,
            encode_clock(
                now.year, now.month, now.day, now.hour, now.minute, now.second
            ),
        )
