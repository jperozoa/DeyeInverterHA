import pytest
from unittest.mock import AsyncMock, MagicMock

from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.deye_inverter.const import (
    REG_TIME_OF_USE,
    TIME_OF_USE_ENABLE_MASK,
    TIME_OF_USE_SLOTS,
)
from custom_components.deye_inverter.switch import (
    DeyeTimeOfUseSwitch,
    async_setup_entry,
)


@pytest.fixture
def mock_coordinator():
    coordinator = MagicMock(spec=DataUpdateCoordinator)
    coordinator.data = {"Time of use": "Enable"}
    coordinator.serial = "ABC123"
    coordinator.last_update_success = True
    coordinator.async_update_register = AsyncMock()
    return coordinator


def test_switch_properties(mock_coordinator):
    switch = DeyeTimeOfUseSwitch(mock_coordinator)

    assert switch.unique_id == "ABC123_time_of_use"
    assert switch.is_on is True
    assert switch.entity_category is EntityCategory.CONFIG
    assert switch.available is True
    assert switch.device_info["identifiers"] == {("deye_inverter", "ABC123")}


def test_switch_off_state(mock_coordinator):
    mock_coordinator.data = {"Time of use": "Disable"}
    assert DeyeTimeOfUseSwitch(mock_coordinator).is_on is False


def test_switch_unavailable_without_metric(mock_coordinator):
    mock_coordinator.data = {}
    switch = DeyeTimeOfUseSwitch(mock_coordinator)

    assert switch.available is False
    assert switch.is_on is None


async def test_turn_on_sets_only_the_enable_bit(mock_coordinator):
    switch = DeyeTimeOfUseSwitch(mock_coordinator)

    await switch.async_turn_on()

    mock_coordinator.async_update_register.assert_awaited_once_with(
        REG_TIME_OF_USE, TIME_OF_USE_ENABLE_MASK, TIME_OF_USE_ENABLE_MASK
    )


async def test_turn_off_clears_only_the_enable_bit(mock_coordinator):
    switch = DeyeTimeOfUseSwitch(mock_coordinator)

    await switch.async_turn_off()

    mock_coordinator.async_update_register.assert_awaited_once_with(
        REG_TIME_OF_USE, TIME_OF_USE_ENABLE_MASK, 0
    )


async def test_async_setup_entry_adds_switch(mock_coordinator):
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    hass.data = {"deye_inverter": {"test_entry": mock_coordinator}}
    added = []

    await async_setup_entry(hass, entry, lambda ents, **kw: added.extend(ents))

    # Program enable, global grid charge, then grid and generator charge per slot
    assert isinstance(added[0], DeyeTimeOfUseSwitch)
    assert len(added) == 2 + 2 * TIME_OF_USE_SLOTS
