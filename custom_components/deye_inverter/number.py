"""Number entities: the SOC target and power limit of each time-of-use slot."""

from __future__ import annotations

from typing import Any, Optional

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, UnitOfElectricCurrent, UnitOfPower
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    MAX_BATTERY_CURRENT,
    REG_TOU_POWER,
    REG_TOU_SOC,
    TOU_POWER_FALLBACK_MAX,
)
from .coordinator import DeyeDataUpdateCoordinator
from .settings import DeyeSettingEntity
from .time_of_use import DeyeTimeOfUseSlotEntity, slot_numbers


@dataclass(frozen=True)
class SettingNumber:
    """How one numeric global setting is presented."""

    field: str
    name: str
    unit: str
    device_class: NumberDeviceClass
    icon: str
    max_value: float
    step: float = 1


_AMPS = UnitOfElectricCurrent.AMPERE
SETTING_NUMBERS: tuple[SettingNumber, ...] = (
    SettingNumber(
        "max_charge_current",
        "Max Charge Current",
        _AMPS,
        NumberDeviceClass.CURRENT,
        "mdi:battery-arrow-up",
        MAX_BATTERY_CURRENT,
    ),
    SettingNumber(
        "max_discharge_current",
        "Max Discharge Current",
        _AMPS,
        NumberDeviceClass.CURRENT,
        "mdi:battery-arrow-down",
        MAX_BATTERY_CURRENT,
    ),
    SettingNumber(
        "battery_low_soc",
        "Battery Low SOC",
        PERCENTAGE,
        NumberDeviceClass.BATTERY,
        "mdi:battery-low",
        100,
    ),
    SettingNumber(
        "battery_shutdown_soc",
        "Battery Shutdown SOC",
        PERCENTAGE,
        NumberDeviceClass.BATTERY,
        "mdi:battery-off",
        100,
    ),
    SettingNumber(
        "battery_restart_soc",
        "Battery Restart SOC",
        PERCENTAGE,
        NumberDeviceClass.BATTERY,
        "mdi:battery-sync",
        100,
    ),
    SettingNumber(
        "grid_charge_current",
        "Grid Charge Current",
        _AMPS,
        NumberDeviceClass.CURRENT,
        "mdi:transmission-tower-import",
        MAX_BATTERY_CURRENT,
    ),
    SettingNumber(
        "grid_charge_start_soc",
        "Grid Charge Start SOC",
        PERCENTAGE,
        NumberDeviceClass.BATTERY,
        "mdi:battery-charging-low",
        100,
    ),
    SettingNumber(
        "max_sell_power",
        "Max Sell Power",
        UnitOfPower.WATT,
        NumberDeviceClass.POWER,
        "mdi:transmission-tower-export",
        TOU_POWER_FALLBACK_MAX,
        10,
    ),
)


async def async_setup_entry(
    hass: Any, entry: Any, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the number platform."""
    coordinator: DeyeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = []
    for n in slot_numbers():
        entities.append(DeyeTimeOfUseSoc(coordinator, n))
        entities.append(DeyeTimeOfUsePower(coordinator, n))
    entities.extend(DeyeSettingNumber(coordinator, s) for s in SETTING_NUMBERS)
    async_add_entities(entities, update_before_add=False)


class DeyeSettingNumber(DeyeSettingEntity, NumberEntity):
    """A numeric global setting: a current limit, an SOC threshold, a power cap."""

    _attr_native_min_value = 0
    _attr_mode = NumberMode.BOX

    def __init__(
        self, coordinator: DeyeDataUpdateCoordinator, setting: SettingNumber
    ) -> None:
        self._field = setting.field
        super().__init__(coordinator)
        self._setting = setting
        self._attr_name = setting.name
        self._attr_native_unit_of_measurement = setting.unit
        self._attr_device_class = setting.device_class
        self._attr_icon = setting.icon
        self._attr_native_step = setting.step

    @property
    def native_max_value(self) -> float:
        """A power cap follows the rated power when the inverter reports it."""
        if self._setting.device_class is not NumberDeviceClass.POWER:
            return self._setting.max_value
        data = self.coordinator.data or {}
        rated = data.get("Device Rated Power")
        if rated is None:
            return self._setting.max_value
        try:
            rated_w = float(rated)
        except (TypeError, ValueError):
            return self._setting.max_value
        return rated_w if rated_w > 0 else self._setting.max_value

    @property
    def native_value(self) -> Optional[float]:
        value = self.setting
        return None if value is None else float(value)

    async def async_set_native_value(self, value: float) -> None:
        await self.async_write(int(round(value)))


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
