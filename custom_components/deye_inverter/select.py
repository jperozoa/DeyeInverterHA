"""Select entities: settings with a fixed list of options."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, REG_SOLAR_SELL, REG_WORK_MODE
from .coordinator import DeyeDataUpdateCoordinator
from .InverterDataParser import work_mode_registers
from .profiles import Profile, get_profile
from .sensor import _inverter_device_info

_LOGGER = logging.getLogger(__name__)

WORK_MODE_TITLE = "Work Mode"


def work_mode_options(profile: Any) -> Dict[int, str]:
    """The Work Mode option labels by key, from the register definitions."""
    if not isinstance(profile, Profile):
        profile = get_profile()
    return dict(profile.enum_mappings.get((REG_WORK_MODE, WORK_MODE_TITLE), {}))


async def async_setup_entry(
    hass: Any, entry: Any, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the select platform."""
    coordinator: DeyeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DeyeWorkModeSelect(coordinator)], update_before_add=False)


class DeyeWorkModeSelect(CoordinatorEntity[DeyeDataUpdateCoordinator], SelectEntity):
    """The inverter's work mode: selling first, or one of the zero-export modes.

    Shows the same value as the Work Mode diagnostic sensor, and writes the
    0x00F4 / 0x00F7 register pair it is parsed from.
    """

    _attr_has_entity_name = True
    _attr_name = "Work Mode"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator: DeyeDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        serial = getattr(coordinator, "serial", "unknown")
        self._attr_unique_id = f"{serial}_work_mode"
        self._labels = work_mode_options(getattr(coordinator, "profile", None))
        self._attr_options = [self._labels[key] for key in sorted(self._labels)]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the Deye inverter."""
        return _inverter_device_info(self.coordinator)

    @property
    def available(self) -> bool:
        """Available only while the inverter reports its work mode."""
        if not super().available:
            return False
        data = self.coordinator.data or {}
        return WORK_MODE_TITLE in data

    @property
    def current_option(self) -> Optional[str]:
        """The parsed work mode, or None if it is not one of the options."""
        data = self.coordinator.data or {}
        value = data.get(WORK_MODE_TITLE)
        return value if value in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        """Write the mode and, where it matters, the solar sell flag."""
        keys = [key for key, label in self._labels.items() if label == option]
        if not keys:
            raise ValueError(f"Unknown work mode: {option}")
        mode, solar_sell = work_mode_registers(keys[0])
        # The flag first: a zero-export mode with the wrong flag would
        # briefly sell or not sell energy unintentionally.
        if solar_sell is not None:
            await self.coordinator.async_write_registers(REG_SOLAR_SELL, [solar_sell])
        await self.coordinator.async_write_registers(REG_WORK_MODE, [mode])
