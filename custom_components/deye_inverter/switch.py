"""Switch entities: on/off settings."""

from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, REG_TIME_OF_USE, TIME_OF_USE_ENABLE_MASK
from .coordinator import DeyeDataUpdateCoordinator
from .sensor import _inverter_device_info

_LOGGER = logging.getLogger(__name__)

TIME_OF_USE_TITLE = "Time of use"
TIME_OF_USE_ON = "Enable"


async def async_setup_entry(
    hass: Any, entry: Any, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the switch platform."""
    coordinator: DeyeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DeyeTimeOfUseSwitch(coordinator)], update_before_add=False)


class DeyeTimeOfUseSwitch(CoordinatorEntity[DeyeDataUpdateCoordinator], SwitchEntity):
    """Enables the inverter's time-of-use program.

    Only bit 0 of register 0x00F8 is touched; the weekday bits that share
    the register keep whatever the inverter has.
    """

    _attr_has_entity_name = True
    _attr_name = "Time of Use"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:clock-time-four-outline"

    def __init__(self, coordinator: DeyeDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        serial = getattr(coordinator, "serial", "unknown")
        self._attr_unique_id = f"{serial}_time_of_use"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the Deye inverter."""
        return _inverter_device_info(self.coordinator)

    @property
    def available(self) -> bool:
        """Available only while the inverter reports the setting."""
        if not super().available:
            return False
        data = self.coordinator.data or {}
        return TIME_OF_USE_TITLE in data

    @property
    def is_on(self) -> Optional[bool]:
        """True when the parsed value says the program is enabled."""
        data = self.coordinator.data or {}
        value = data.get(TIME_OF_USE_TITLE)
        if value is None:
            return None
        return value == TIME_OF_USE_ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set the enable bit."""
        await self.coordinator.async_update_register(
            REG_TIME_OF_USE, TIME_OF_USE_ENABLE_MASK, TIME_OF_USE_ENABLE_MASK
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Clear the enable bit."""
        await self.coordinator.async_update_register(
            REG_TIME_OF_USE, TIME_OF_USE_ENABLE_MASK, 0
        )
