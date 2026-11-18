"""Number entities: the SOC target and power limit of each time-of-use slot."""

from __future__ import annotations

from typing import Any, Optional

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, REG_TOU_POWER, REG_TOU_SOC, TOU_POWER_FALLBACK_MAX
from .coordinator import DeyeDataUpdateCoordinator
from .time_of_use import DeyeTimeOfUseSlotEntity, slot_numbers


async def async_setup_entry(
    hass: Any, entry: Any, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the number platform."""
    coordinator: DeyeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = []
    for n in slot_numbers():
        entities.append(DeyeTimeOfUseSoc(coordinator, n))
        entities.append(DeyeTimeOfUsePower(coordinator, n))
    async_add_entities(entities, update_before_add=False)


class DeyeTimeOfUseSoc(DeyeTimeOfUseSlotEntity, NumberEntity):
    """The battery level the inverter holds during the slot.

    Charged up to it (from the grid only with the slot's grid charge on)
    and never discharged below it.
    """

    _kind = "soc"
    _label = "SOC"
    _attr_icon = "mdi:battery-charging-60"
    _attr_device_class = NumberDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> Optional[float]:
        slot = self.slot_data or {}
        value = slot.get("soc")
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write_registers(
            REG_TOU_SOC + self.register_offset, [int(round(value))]
        )


class DeyeTimeOfUsePower(DeyeTimeOfUseSlotEntity, NumberEntity):
    """The charge and discharge power limit during the slot, in watts."""

    _kind = "power"
    _label = "Power"
    _attr_icon = "mdi:flash"
    _attr_device_class = NumberDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_native_min_value = 0
    _attr_native_step = 10
    _attr_mode = NumberMode.BOX

    @property
    def native_max_value(self) -> float:
        """The inverter's rated power when it reports one."""
        data = self.coordinator.data or {}
        rated = data.get("Device Rated Power")
        if rated is None:
            return TOU_POWER_FALLBACK_MAX
        try:
            rated_w = float(rated)
        except (TypeError, ValueError):
            return TOU_POWER_FALLBACK_MAX
        return rated_w if rated_w > 0 else TOU_POWER_FALLBACK_MAX

    @property
    def native_value(self) -> Optional[float]:
        slot = self.slot_data or {}
        value = slot.get("power")
        return float(value) if isinstance(value, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write_registers(
            REG_TOU_POWER + self.register_offset, [int(round(value))]
        )
