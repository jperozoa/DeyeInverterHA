"""Shared base for the entities that edit one time-of-use slot."""

from __future__ import annotations

from typing import Any, Dict, Optional

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import TIME_OF_USE_SLOTS
from .coordinator import DeyeDataUpdateCoordinator
from .InverterDataParser import TIME_OF_USE_PROGRAM
from .sensor import _inverter_device_info


def slot_numbers() -> range:
    """The 1-based slot numbers, as shown to the user."""
    return range(1, TIME_OF_USE_SLOTS + 1)


class DeyeTimeOfUseSlotEntity(CoordinatorEntity[DeyeDataUpdateCoordinator]):
    """One setting of one time-of-use slot.

    Subclasses add the platform mixin and set ``_kind`` (unique ID suffix)
    and ``_label`` (name suffix).
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _kind = ""
    _label = ""

    def __init__(self, coordinator: DeyeDataUpdateCoordinator, slot: int) -> None:
        super().__init__(coordinator)
        self._slot = slot
        serial = getattr(coordinator, "serial", "unknown")
        self._attr_unique_id = f"{serial}_time_of_use_{slot}_{self._kind}"
        self._attr_name = f"Time of Use {slot} {self._label}"

    @property
    def slot(self) -> int:
        """The 1-based slot number."""
        return self._slot

    @property
    def register_offset(self) -> int:
        """The slot's offset from each setting's base register."""
        return self._slot - 1

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the Deye inverter."""
        return _inverter_device_info(self.coordinator)

    @property
    def slot_data(self) -> Optional[Dict[str, Any]]:
        """The parsed values of this slot, or None if the block was not read."""
        data = self.coordinator.data or {}
        program = data.get(TIME_OF_USE_PROGRAM)
        if not isinstance(program, list) or len(program) < self._slot:
            return None
        entry = program[self._slot - 1]
        return entry if isinstance(entry, dict) else None

    @property
    def available(self) -> bool:
        """Available only while the inverter reports the program."""
        return super().available and self.slot_data is not None
