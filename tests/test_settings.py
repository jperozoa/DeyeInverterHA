"""Global settings and the inverter clock: parsing and entities."""

from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.deye_inverter.button import (
    DeyeSyncClockButton,
    async_setup_entry as button_setup,
)
from custom_components.deye_inverter.const import (
    REG_CLOCK,
    REG_MAX_CHARGE_CURRENT,
    REG_PRIORITY_MODE,
    REGISTER_BLOCKS,
)
from custom_components.deye_inverter.InverterDataParser import (
    INVERTER_TIME,
    SETTING_REGISTERS,
    SETTINGS,
    decode_clock,
    encode_clock,
    parse_clock,
    parse_raw,
    parse_settings,
    register_index,
)
from custom_components.deye_inverter.number import (
    SETTING_NUMBERS,
    DeyeSettingNumber,
    async_setup_entry as number_setup,
)
from custom_components.deye_inverter.select import (
    DeyePriorityModeSelect,
    async_setup_entry as select_setup,
)
from custom_components.deye_inverter.sensor import DeyeInverterTimeSensor
from custom_components.deye_inverter.switch import DeyeGridChargeSwitch
from custom_components.deye_inverter.const import (
    GRID_CHARGE_ENABLE_MASK,
    REG_GRID_CHARGE_ENABLE,
)

RAW_LEN = sum(end - start + 1 for start, end in REGISTER_BLOCKS)

VALUES = {
    "max_sell_power": 8000,
    "max_charge_current": 60,
    "max_discharge_current": 60,
    "battery_shutdown_soc": 15,
    "battery_restart_soc": 35,
    "battery_low_soc": 25,
    "grid_charge_start_soc": 30,
    "grid_charge_current": 110,
    "grid_charge_enable": 0,
    "priority_mode": 1,
}


def raw_with_settings():
    raw = [0] * RAW_LEN
    for field, value in VALUES.items():
        raw[register_index(SETTING_REGISTERS[field])] = value
    for i, v in enumerate(encode_clock(2026, 11, 19, 0, 40, 5)):
        raw[register_index(REG_CLOCK + i)] = v
    return raw


# === Parsing ===


def test_parse_settings_reads_every_field():
    assert parse_settings(raw_with_settings()) == VALUES


def test_parse_settings_skips_unread_registers():
    raw = raw_with_settings()
    raw[register_index(REG_PRIORITY_MODE)] = None
    settings = parse_settings(raw)

    assert "priority_mode" not in settings
    assert settings["max_charge_current"] == 60

    # Nothing from the clock block onwards: no setting register was read
    assert parse_settings([0] * register_index(REG_CLOCK)) == {}


def test_clock_round_trip():
    regs = encode_clock(2026, 11, 19, 23, 59, 58)
    assert regs == [(26 << 8) | 11, (19 << 8) | 23, (59 << 8) | 58]
    assert decode_clock(regs) == "2026-11-19 23:59:58"


@pytest.mark.parametrize(
    "regs",
    [[0, 0, 0], [(26 << 8) | 13, 1 << 8, 0], [(26 << 8) | 1, (1 << 8) | 24, 0], [1, 2]],
)
def test_decode_clock_rejects_junk(regs):
    assert decode_clock(regs) is None


def test_parse_raw_includes_settings_and_clock():
    result = parse_raw(raw_with_settings())

    assert result[SETTINGS] == VALUES
    assert result[INVERTER_TIME] == "2026-11-19 00:40:05"


def test_parse_raw_omits_unread_settings_and_clock():
    result = parse_raw([0] * register_index(REG_CLOCK))
    assert SETTINGS not in result
    assert INVERTER_TIME not in result

    assert parse_clock([0] * register_index(REG_CLOCK)) is None


# === Entities ===


@pytest.fixture
def mock_coordinator():
    coordinator = MagicMock(spec=DataUpdateCoordinator)
    coordinator.data = parse_raw(raw_with_settings())
    coordinator.data["Device Rated Power"] = 10000.0
    coordinator.serial = "ABC123"
    coordinator.last_update_success = True
    coordinator.async_write_registers = AsyncMock()
    return coordinator


def _number(coordinator, field):
    setting = next(s for s in SETTING_NUMBERS if s.field == field)
    return DeyeSettingNumber(coordinator, setting)


def test_setting_number_identity_and_value(mock_coordinator):
    number = _number(mock_coordinator, "max_charge_current")

    assert number.unique_id == "ABC123_max_charge_current"
    assert number.name == "Max Charge Current"
    assert number.entity_category is EntityCategory.CONFIG
    assert number.native_value == 60.0
    assert number.native_unit_of_measurement == "A"
    assert number.native_min_value == 0
    assert number.native_max_value == 250
    assert number.available is True
    assert number.device_info["identifiers"] == {("deye_inverter", "ABC123")}


def test_every_setting_number_reads_its_field(mock_coordinator):
    for setting in SETTING_NUMBERS:
        number = DeyeSettingNumber(mock_coordinator, setting)
        assert number.native_value == float(VALUES[setting.field]), setting.field


def test_sell_power_max_follows_rated_power(mock_coordinator):
    assert _number(mock_coordinator, "max_sell_power").native_max_value == 10000.0

    del mock_coordinator.data["Device Rated Power"]
    assert _number(mock_coordinator, "max_sell_power").native_max_value == 12000


async def test_setting_number_write(mock_coordinator):
    await _number(mock_coordinator, "max_charge_current").async_set_native_value(80.4)

    mock_coordinator.async_write_registers.assert_awaited_once_with(
        REG_MAX_CHARGE_CURRENT, [80]
    )


def test_setting_unavailable_when_unread(mock_coordinator):
    mock_coordinator.data = {"PV1 Power": 1}

    number = _number(mock_coordinator, "battery_low_soc")
    assert number.available is False
    assert number.native_value is None

    select = DeyePriorityModeSelect(mock_coordinator)
    assert select.available is False
    assert select.current_option is None


def test_priority_select(mock_coordinator):
    select = DeyePriorityModeSelect(mock_coordinator)

    assert select.unique_id == "ABC123_priority_mode"
    assert select.options == ["Battery First", "Load First"]
    assert select.current_option == "Load First"


async def test_priority_select_write(mock_coordinator):
    select = DeyePriorityModeSelect(mock_coordinator)

    await select.async_select_option("Battery First")

    mock_coordinator.async_write_registers.assert_awaited_once_with(
        REG_PRIORITY_MODE, [0]
    )
    with pytest.raises(ValueError):
        await select.async_select_option("Nope")


def test_grid_charge_switch_reads_bit_zero(mock_coordinator):
    switch = DeyeGridChargeSwitch(mock_coordinator)

    assert switch.unique_id == "ABC123_grid_charge_enable"
    assert switch.entity_category is EntityCategory.CONFIG
    assert switch.is_on is False

    mock_coordinator.data[SETTINGS]["grid_charge_enable"] = 1
    assert switch.is_on is True
    mock_coordinator.data = {}
    assert switch.is_on is None
    assert switch.available is False


async def test_grid_charge_switch_writes_only_bit_zero(mock_coordinator):
    mock_coordinator.async_update_register = AsyncMock()
    switch = DeyeGridChargeSwitch(mock_coordinator)

    await switch.async_turn_on()
    await switch.async_turn_off()

    assert mock_coordinator.async_update_register.await_args_list == [
        ((REG_GRID_CHARGE_ENABLE, GRID_CHARGE_ENABLE_MASK, GRID_CHARGE_ENABLE_MASK),),
        ((REG_GRID_CHARGE_ENABLE, GRID_CHARGE_ENABLE_MASK, 0),),
    ]


def test_inverter_time_sensor(mock_coordinator):
    sensor = DeyeInverterTimeSensor(mock_coordinator)

    assert sensor.unique_id == "ABC123_inverter_time"
    assert sensor.native_value == "2026-11-19 00:40:05"
    assert sensor.entity_category is EntityCategory.DIAGNOSTIC
    assert sensor.available is True

    mock_coordinator.data = {}
    assert sensor.available is False
    assert sensor.native_value is None


async def test_sync_clock_button_writes_local_time(mock_coordinator):
    button = DeyeSyncClockButton(mock_coordinator)
    assert button.unique_id == "ABC123_sync_clock"
    assert button.entity_category is EntityCategory.CONFIG

    now = datetime(2026, 11, 19, 1, 2, 3)
    with patch("custom_components.deye_inverter.button.dt_util.now", return_value=now):
        await button.async_press()

    mock_coordinator.async_write_registers.assert_awaited_once_with(
        REG_CLOCK, encode_clock(2026, 11, 19, 1, 2, 3)
    )


# === Platform setup ===


@pytest.mark.parametrize(
    "setup, cls, count",
    [
        (number_setup, DeyeSettingNumber, len(SETTING_NUMBERS)),
        (select_setup, DeyePriorityModeSelect, 1),
        (button_setup, DeyeSyncClockButton, 1),
    ],
)
async def test_platform_setup_adds_setting_entities(
    mock_coordinator, setup, cls, count
):
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    hass.data = {"deye_inverter": {"test_entry": mock_coordinator}}
    added = []

    await setup(hass, entry, lambda ents, **kw: added.extend(ents))

    assert sum(isinstance(e, cls) for e in added) == count
    assert len({e.unique_id for e in added}) == len(added)
