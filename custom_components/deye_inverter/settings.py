"""Shared base for the entities that edit one global setting."""

from __future__ import annotations

from typing import Any, Optional

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import DeyeDataUpdateCoordinator
from .InverterDataParser import SETTINGS, SETTING_REGISTERS
from .sensor import _inverter_device_info


class DeyeSettingEntity(CoordinatorEntity[DeyeDataUpdateCoordinator]):
    """One global setting, read from the Settings dict and written to its register.

    Subclasses add the platform mixin and set ``_field`` (a key of
    ``SETTING_REGISTERS``) and ``_attr_name``.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _field = ""

    def __init__(self, coordinator: DeyeDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        serial = getattr(coordinator, "serial", "unknown")
        self._attr_unique_id = f"{serial}_{self._field}"

    @property
    def register(self) -> int:
        return SETTING_REGISTERS[self._field]

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for the Deye inverter."""
        return _inverter_device_info(self.coordinator)

    @property
    def setting(self) -> Optional[int]:
        """The current value, or None if its register was not read."""
        data = self.coordinator.data or {}
        settings = data.get(SETTINGS)
        if not isinstance(settings, dict):
            return None
        value: Any = settings.get(self._field)
        return value if isinstance(value, int) else None

    @property
    def available(self) -> bool:
        """Available only while the inverter reports the setting."""
        return super().available and self.setting is not None

    async def async_write(self, value: int) -> None:
        await self.coordinator.async_write_registers(self.register, [value])
