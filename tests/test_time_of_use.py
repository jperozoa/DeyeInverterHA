"""The time-of-use program: parsing and the per-slot entities."""

from datetime import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.deye_inverter.const import (
    REG_TOU_CHARGE,
    REG_TOU_POWER,
    REG_TOU_SOC,
    REG_TOU_START,
    REGISTER_BLOCKS,
    TIME_OF_USE_SLOTS,
    TOU_GEN_CHARGE_MASK,
    TOU_GRID_CHARGE_MASK,
    TOU_POWER_FALLBACK_MAX,
)
from custom_components.deye_inverter.InverterDataParser import (
    TIME_OF_USE_PROGRAM,
    decode_tou_time,
    encode_tou_time,
    parse_raw,
    parse_time_of_use,
    register_index,
)
from custom_components.deye_inverter.number import (
    DeyeTimeOfUsePower,
    DeyeTimeOfUseSoc,
)
from custom_components.deye_inverter.number import (
    async_setup_entry as number_setup,
)
from custom_components.deye_inverter.switch import (
    DeyeTimeOfUseGenCharge,
    DeyeTimeOfUseGridCharge,
)
from custom_components.deye_inverter.switch import (
    async_setup_entry as switch_setup,
)
from custom_components.deye_inverter.time import DeyeTimeOfUseStart
from custom_components.deye_inverter.time import async_setup_entry as time_setup

RAW_LEN = sum(end - start + 1 for start, end in REGISTER_BLOCKS)


def raw_with_program():
    """A raw list whose slot n has start n:30, power n*1000, soc n*10."""
    raw = [0] * RAW_LEN
    for n in range(TIME_OF_USE_SLOTS):
        raw[register_index(REG_TOU_START + n)] = (n + 1) * 100 + 30
        raw[register_index(REG_TOU_POWER + n)] = (n + 1) * 1000
        raw[register_index(REG_TOU_SOC + n)] = (n + 1) * 10
        raw[register_index(REG_TOU_CHARGE + n)] = n % 4  # cycles the two bits
    return raw


# === Parsing ===


@pytest.mark.parametrize(
    "value, expected",
    [(0, "00:00"), (130, "01:30"), (2359, "23:59"), (1800, "18:00")],
)
def test_decode_tou_time(value, expected):
    assert decode_tou_time(value) == expected


@pytest.mark.parametrize("value", [2400, 1260, 9999, 65535])
def test_decode_tou_time_rejects_junk(value):
    assert decode_tou_time(value) is None


def test_encode_tou_time_round_trip():
    for hh in (0, 7, 23):
        for mm in (0, 15, 59):
            assert decode_tou_time(encode_tou_time(hh, mm)) == f"{hh:02d}:{mm:02d}"


def test_encode_tou_time_rejects_junk():
    with pytest.raises(ValueError):
        encode_tou_time(24, 0)


def test_parse_time_of_use_slots():
    program = parse_time_of_use(raw_with_program())

    assert len(program) == TIME_OF_USE_SLOTS
    assert program[0] == {
        "start": "01:30",
        "power": 1000,
        "soc": 10,
        "grid_charge": False,
        "gen_charge": False,
    }
    assert program[1]["grid_charge"] is True and program[1]["gen_charge"] is False
    assert program[2]["grid_charge"] is False and program[2]["gen_charge"] is True
    assert program[3]["grid_charge"] is True and program[3]["gen_charge"] is True
    assert program[5]["start"] == "06:30"


def test_parse_time_of_use_missing_block():
    """An unread optional block (None padding) or a short list yields None."""
    raw = raw_with_program()
    raw[register_index(REG_TOU_SOC + 2)] = None
    assert parse_time_of_use(raw) is None

    assert parse_time_of_use([0] * register_index(REG_TOU_START)) is None


def test_parse_raw_includes_program():
    result = parse_raw(raw_with_program())

    assert TIME_OF_USE_PROGRAM in result
    assert result[TIME_OF_USE_PROGRAM][4]["soc"] == 50


def test_parse_raw_omits_program_when_unread():
    assert TIME_OF_USE_PROGRAM not in parse_raw([0] * register_index(REG_TOU_START))


# === Entities ===


@pytest.fixture
def mock_coordinator():
    coordinator = MagicMock(spec=DataUpdateCoordinator)
    coordinator.data = parse_raw(raw_with_program())
    coordinator.data["Device Rated Power"] = 10000.0
    coordinator.serial = "ABC123"
    coordinator.last_update_success = True
    coordinator.async_write_registers = AsyncMock()
    coordinator.async_update_register = AsyncMock()
    return coordinator


def test_slot_entity_identity(mock_coordinator):
    start = DeyeTimeOfUseStart(mock_coordinator, 3)

    assert start.unique_id == "ABC123_time_of_use_3_start"
    assert start.name == "Time of Use 3 Start"
    assert start.entity_category is EntityCategory.CONFIG
    assert start.available is True
    assert start.device_info["identifiers"] == {("deye_inverter", "ABC123")}


def test_slot_entities_unavailable_without_program(mock_coordinator):
    mock_coordinator.data = {"PV1 Power": 1}
    for cls in (DeyeTimeOfUseStart, DeyeTimeOfUseSoc, DeyeTimeOfUsePower):
        entity = cls(mock_coordinator, 1)
        assert entity.available is False
        assert entity.native_value is None
    assert DeyeTimeOfUseGridCharge(mock_coordinator, 1).is_on is None


def test_start_value_and_write(mock_coordinator):
    start = DeyeTimeOfUseStart(mock_coordinator, 2)
    assert start.native_value == time(2, 30)


async def test_start_write_encodes_hhmm(mock_coordinator):
    start = DeyeTimeOfUseStart(mock_coordinator, 2)

    await start.async_set_value(time(18, 45))

    mock_coordinator.async_write_registers.assert_awaited_once_with(
        REG_TOU_START + 1, [1845]
    )


def test_start_junk_register_reads_none(mock_coordinator):
    mock_coordinator.data[TIME_OF_USE_PROGRAM][0]["start"] = None
    assert DeyeTimeOfUseStart(mock_coordinator, 1).native_value is None


def test_soc_value_bounds_and_write(mock_coordinator):
    soc = DeyeTimeOfUseSoc(mock_coordinator, 4)

    assert soc.native_value == 40.0
    assert soc.native_min_value == 0
    assert soc.native_max_value == 100
    assert soc.native_unit_of_measurement == "%"


async def test_soc_write_rounds_to_int(mock_coordinator):
    soc = DeyeTimeOfUseSoc(mock_coordinator, 4)

    await soc.async_set_native_value(35.6)

    mock_coordinator.async_write_registers.assert_awaited_once_with(
        REG_TOU_SOC + 3, [36]
    )


def test_power_value_and_max_from_rated_power(mock_coordinator):
    power = DeyeTimeOfUsePower(mock_coordinator, 6)

    assert power.native_value == 6000.0
    assert power.native_max_value == 10000.0
    assert power.native_unit_of_measurement == "W"


def test_power_max_falls_back_without_rated_power(mock_coordinator):
    del mock_coordinator.data["Device Rated Power"]
    assert DeyeTimeOfUsePower(mock_coordinator, 1).native_max_value == (
        TOU_POWER_FALLBACK_MAX
    )

    mock_coordinator.data["Device Rated Power"] = 0
    assert DeyeTimeOfUsePower(mock_coordinator, 1).native_max_value == (
        TOU_POWER_FALLBACK_MAX
    )


async def test_power_write(mock_coordinator):
    power = DeyeTimeOfUsePower(mock_coordinator, 1)

    await power.async_set_native_value(2500)

    mock_coordinator.async_write_registers.assert_awaited_once_with(
        REG_TOU_POWER, [2500]
    )


def test_charge_flags_read(mock_coordinator):
    assert DeyeTimeOfUseGridCharge(mock_coordinator, 2).is_on is True
    assert DeyeTimeOfUseGenCharge(mock_coordinator, 2).is_on is False
    assert DeyeTimeOfUseGridCharge(mock_coordinator, 3).is_on is False
    assert DeyeTimeOfUseGenCharge(mock_coordinator, 3).is_on is True


async def test_grid_charge_write_touches_only_its_bit(mock_coordinator):
    grid = DeyeTimeOfUseGridCharge(mock_coordinator, 5)

    await grid.async_turn_on()
    await grid.async_turn_off()

    assert mock_coordinator.async_update_register.await_args_list == [
        ((REG_TOU_CHARGE + 4, TOU_GRID_CHARGE_MASK, TOU_GRID_CHARGE_MASK),),
        ((REG_TOU_CHARGE + 4, TOU_GRID_CHARGE_MASK, 0),),
    ]


async def test_gen_charge_write_and_disabled_by_default(mock_coordinator):
    gen = DeyeTimeOfUseGenCharge(mock_coordinator, 1)
    assert gen.entity_registry_enabled_default is False

    await gen.async_turn_on()

    mock_coordinator.async_update_register.assert_awaited_once_with(
        REG_TOU_CHARGE, TOU_GEN_CHARGE_MASK, TOU_GEN_CHARGE_MASK
    )


# === Platform setup ===


@pytest.mark.parametrize(
    "setup, expected",
    [
        (time_setup, TIME_OF_USE_SLOTS),
        (number_setup, 2 * TIME_OF_USE_SLOTS),
        # the program enable switch plus two flags per slot
        (switch_setup, 1 + 2 * TIME_OF_USE_SLOTS),
    ],
)
async def test_platform_setup_creates_slot_entities(mock_coordinator, setup, expected):
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    hass.data = {"deye_inverter": {"test_entry": mock_coordinator}}
    added = []

    await setup(hass, entry, lambda ents, **kw: added.extend(ents))

    assert len(added) == expected
    assert len({e.unique_id for e in added}) == expected
