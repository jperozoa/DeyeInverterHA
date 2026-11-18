"""Time entities: the start time of each time-of-use slot."""

from __future__ import annotations

from datetime import time
from typing import Any, Optional

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, REG_TOU_START
from .coordinator import DeyeDataUpdateCoordinator
from .InverterDataParser import encode_tou_time
from .time_of_use import DeyeTimeOfUseSlotEntity, slot_numbers


async def async_setup_entry(
    hass: Any, entry: Any, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the time platform."""
    coordinator: DeyeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [DeyeTimeOfUseStart(coordinator, n) for n in slot_numbers()],
        update_before_add=False,
    )


class DeyeTimeOfUseStart(DeyeTimeOfUseSlotEntity, TimeEntity):
    """When a slot begins. It lasts until the next slot's start time."""

    _kind = "start"
    _label = "Start"
    _attr_icon = "mdi:clock-start"

    @property
    def native_value(self) -> Optional[time]:
        """The slot start as a time of day, or None if the register is junk."""
        slot = self.slot_data or {}
        value = slot.get("start")
        if not isinstance(value, str):
            return None
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None

    async def async_set_value(self, value: time) -> None:
        """Write the start time as HHMM."""
        await self.coordinator.async_write_registers(
            REG_TOU_START + self.register_offset,
            [encode_tou_time(value.hour, value.minute)],
        )
