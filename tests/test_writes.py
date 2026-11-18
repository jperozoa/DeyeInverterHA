"""Register writes: the client's write path and the coordinator wrapper."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import HomeAssistantError

from custom_components.deye_inverter.coordinator import DeyeDataUpdateCoordinator
from custom_components.deye_inverter.InverterData import (
    InverterData,
    ModbusWriteError,
)
from custom_components.deye_inverter.InverterDataParser import (
    parse_raw,
    register_index,
    work_mode_key,
    work_mode_registers,
)


@pytest.fixture
def modbus():
    with patch(
        "custom_components.deye_inverter.InverterData.PySolarmanV5"
    ) as mock_class:
        instance = MagicMock()
        mock_class.return_value = instance
        yield instance


@pytest.fixture
def inverter(modbus):
    return InverterData(host="localhost", port=8899, serial="1")


# === InverterData.write_registers ===


async def test_write_single_register_uses_function_16(inverter, modbus):
    """Deye refuses function 6, so even one register goes as write-multiple."""
    modbus.read_holding_registers.return_value = [1]

    await inverter.write_registers(0x00F4, [1])

    modbus.write_multiple_holding_registers.assert_called_once_with(
        register_addr=0x00F4, values=[1]
    )
    modbus.read_holding_registers.assert_called_once_with(
        register_addr=0x00F4, quantity=1
    )


async def test_write_multiple_registers_and_verify(inverter, modbus):
    modbus.read_holding_registers.return_value = [5, 6, 7]

    await inverter.write_registers(0x00FA, [5, 6, 7])

    modbus.write_multiple_holding_registers.assert_called_once_with(
        register_addr=0x00FA, values=[5, 6, 7]
    )


async def test_write_readback_mismatch_raises(inverter, modbus):
    modbus.read_holding_registers.return_value = [0]

    with pytest.raises(ModbusWriteError, match="inverter reports"):
        await inverter.write_registers(0x00F4, [2])


async def test_write_library_error_is_wrapped(inverter, modbus):
    modbus.write_multiple_holding_registers.side_effect = RuntimeError("timeout")

    with pytest.raises(ModbusWriteError, match="write failed"):
        await inverter.write_registers(0x00F4, [2])
    modbus.read_holding_registers.assert_not_called()


async def test_write_readback_error_is_wrapped(inverter, modbus):
    modbus.read_holding_registers.side_effect = RuntimeError("timeout")

    with pytest.raises(ModbusWriteError, match="could not be read back"):
        await inverter.write_registers(0x00F4, [2])


@pytest.mark.parametrize("values", [[], [-1], [0x10000], [1, 70000]])
async def test_write_rejects_bad_values_before_touching_the_inverter(
    inverter, modbus, values
):
    with pytest.raises(ModbusWriteError):
        await inverter.write_registers(0x00F4, values)
    modbus.write_multiple_holding_registers.assert_not_called()


# === InverterData.update_register ===


async def test_update_register_changes_only_masked_bits(inverter, modbus):
    # Weekday bits set, enable bit clear; reads: current, then readback
    modbus.read_holding_registers.side_effect = [[0x00FE], [0x00FF]]

    written = await inverter.update_register(0x00F8, 0x0001, 0x0001)

    assert written == 0x00FF
    modbus.write_multiple_holding_registers.assert_called_once_with(
        register_addr=0x00F8, values=[0x00FF]
    )


async def test_update_register_clears_masked_bits(inverter, modbus):
    modbus.read_holding_registers.side_effect = [[0x00FF], [0x00FE]]

    written = await inverter.update_register(0x00F8, 0x0001, 0)

    assert written == 0x00FE
    modbus.write_multiple_holding_registers.assert_called_once_with(
        register_addr=0x00F8, values=[0x00FE]
    )


async def test_update_register_skips_write_when_unchanged(inverter, modbus):
    modbus.read_holding_registers.return_value = [0x0001]

    await inverter.update_register(0x00F8, 0x0001, 0x0001)

    modbus.write_multiple_holding_registers.assert_not_called()


async def test_update_register_read_error_is_wrapped(inverter, modbus):
    modbus.read_holding_registers.side_effect = RuntimeError("timeout")

    with pytest.raises(ModbusWriteError, match="read failed"):
        await inverter.update_register(0x00F8, 0x0001, 0x0001)
    modbus.write_multiple_holding_registers.assert_not_called()


async def test_update_register_short_read_is_an_error(inverter, modbus):
    modbus.read_holding_registers.return_value = []

    with pytest.raises(ModbusWriteError, match="got 0"):
        await inverter.update_register(0x00F8, 0x0001, 0x0001)


async def test_fetch_data_holds_the_lock(inverter, modbus):
    """A poll runs under the same lock as the writes, so they never interleave."""
    seen = []

    async def fake_read_all():
        seen.append(inverter._lock.locked())
        return {"ok": True}

    inverter._read_all = fake_read_all

    assert await inverter.fetch_data() == {"ok": True}
    assert seen == [True]
    assert not inverter._lock.locked()


# === Coordinator wrappers ===


class MockConfigEntry:
    def __init__(self):
        self.domain = "deye_inverter"
        self.data = {"host": "1.2.3.4", "port": 8899, "serial": "ABC123"}
        self.entry_id = "test_entry"


@pytest.fixture
def coordinator():
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f, *a: f(*a))
    with patch("custom_components.deye_inverter.coordinator.InverterData") as cls:
        client = AsyncMock()
        cls.return_value = client
        coordinator = DeyeDataUpdateCoordinator(
            hass=hass, config_entry=MockConfigEntry(), installed_power=5
        )
        coordinator.async_request_refresh = AsyncMock()
        coordinator._client = client
        yield coordinator


async def test_coordinator_write_creates_client_writes_and_refreshes(coordinator):
    assert coordinator.inverter is None

    await coordinator.async_write_registers(0x00F4, [1])

    coordinator._client.write_registers.assert_awaited_once_with(0x00F4, [1])
    coordinator.async_request_refresh.assert_awaited_once()
    assert coordinator.inverter is coordinator._client


async def test_coordinator_update_register_and_refresh(coordinator):
    await coordinator.async_update_register(0x00F8, 0x0001, 0)

    coordinator._client.update_register.assert_awaited_once_with(0x00F8, 0x0001, 0)
    coordinator.async_request_refresh.assert_awaited_once()


async def test_coordinator_write_error_becomes_homeassistant_error(coordinator):
    coordinator._client.write_registers.side_effect = ModbusWriteError("nope")

    with pytest.raises(HomeAssistantError, match="0x00F4"):
        await coordinator.async_write_registers(0x00F4, [1])
    coordinator.async_request_refresh.assert_not_awaited()


async def test_coordinator_update_error_becomes_homeassistant_error(coordinator):
    coordinator._client.update_register.side_effect = ModbusWriteError("nope")

    with pytest.raises(HomeAssistantError, match="0x00F8"):
        await coordinator.async_update_register(0x00F8, 1, 1)
    coordinator.async_request_refresh.assert_not_awaited()


# === Work mode encoding ===


@pytest.mark.parametrize("key", [0, 1, 2, 3, 4])
def test_work_mode_round_trip(key):
    mode, solar_sell = work_mode_registers(key)
    # Selling first does not care about the flag
    assert work_mode_key(mode, 1 if solar_sell is None else solar_sell) == key


def test_work_mode_registers_unknown_key():
    with pytest.raises(ValueError):
        work_mode_registers(9)


def test_time_of_use_ignores_weekday_bits():
    """0x00F8 packs weekday bits above the enable bit; only bit 0 matters."""
    length = register_index(0x00F8) + 1
    raw = [0] * length

    raw[register_index(0x00F8)] = 0x00FF
    assert parse_raw(raw)["Time of use"] == "Enable"

    raw[register_index(0x00F8)] = 0x00FE
    assert parse_raw(raw)["Time of use"] == "Disable"
