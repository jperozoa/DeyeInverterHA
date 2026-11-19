import pytest
from unittest.mock import AsyncMock, MagicMock, call

from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.deye_inverter.const import REG_SOLAR_SELL, REG_WORK_MODE
from custom_components.deye_inverter.select import (
    DeyeWorkModeSelect,
    async_setup_entry,
    work_mode_options,
)

OPTIONS = [
    "Selling First",
    "Zero-Export to Load&Solar Sell",
    "Zero-Export to Home&Solar Sell",
    "Zero-Export to Load",
    "Zero-Export to Home",
]


@pytest.fixture
def mock_coordinator():
    coordinator = MagicMock(spec=DataUpdateCoordinator)
    coordinator.data = {"Work Mode": "Zero-Export to Load"}
    coordinator.serial = "ABC123"
    coordinator.last_update_success = True
    coordinator.async_write_registers = AsyncMock()
    return coordinator


def test_options_come_from_definitions():
    """The option labels are the Work Mode enum of DYRealTime.txt, in key order."""
    labels = work_mode_options(None)
    assert [labels[k] for k in sorted(labels)] == OPTIONS


def test_select_properties(mock_coordinator):
    select = DeyeWorkModeSelect(mock_coordinator)

    assert select.unique_id == "ABC123_work_mode"
    assert select.options == OPTIONS
    assert select.current_option == "Zero-Export to Load"
    assert select.entity_category is EntityCategory.CONFIG
    assert select.available is True
    assert select.device_info["identifiers"] == {("deye_inverter", "ABC123")}


def test_select_unavailable_without_metric(mock_coordinator):
    mock_coordinator.data = {"PV1 Power": 1}
    select = DeyeWorkModeSelect(mock_coordinator)

    assert select.available is False
    assert select.current_option is None


def test_select_unknown_value_has_no_current_option(mock_coordinator):
    mock_coordinator.data = {"Work Mode": "Unknown (9/0)"}
    select = DeyeWorkModeSelect(mock_coordinator)

    assert select.available is True
    assert select.current_option is None


@pytest.mark.parametrize(
    "option, expected_writes",
    [
        # Selling first leaves the solar sell flag alone
        ("Selling First", [call(REG_WORK_MODE, [0])]),
        (
            "Zero-Export to Load&Solar Sell",
            [call(REG_SOLAR_SELL, [1]), call(REG_WORK_MODE, [1])],
        ),
        (
            "Zero-Export to Home&Solar Sell",
            [call(REG_SOLAR_SELL, [1]), call(REG_WORK_MODE, [2])],
        ),
        ("Zero-Export to Load", [call(REG_SOLAR_SELL, [0]), call(REG_WORK_MODE, [1])]),
        ("Zero-Export to Home", [call(REG_SOLAR_SELL, [0]), call(REG_WORK_MODE, [2])]),
    ],
)
async def test_select_option_writes_register_pair(
    mock_coordinator, option, expected_writes
):
    select = DeyeWorkModeSelect(mock_coordinator)

    await select.async_select_option(option)

    assert mock_coordinator.async_write_registers.await_args_list == expected_writes


async def test_select_rejects_unknown_option(mock_coordinator):
    select = DeyeWorkModeSelect(mock_coordinator)

    with pytest.raises(ValueError):
        await select.async_select_option("Nope")
    mock_coordinator.async_write_registers.assert_not_awaited()


async def test_async_setup_entry_adds_select(mock_coordinator):
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    hass.data = {"deye_inverter": {"test_entry": mock_coordinator}}
    added = []

    await async_setup_entry(hass, entry, lambda ents, **kw: added.extend(ents))

    # Work mode first, then the priority mode setting
    assert len(added) == 2
    assert isinstance(added[0], DeyeWorkModeSelect)
