import logging
from datetime import timedelta
from typing import Any, Dict, Sequence

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from pysolarmanv5.pysolarmanv5 import NoSocketAvailableError

from .const import CONF_MOD, DEFAULT_MOD, DOMAIN, DEFAULT_SCAN_INTERVAL
from .InverterData import InverterData
from .profiles import Profile, get_profile, normalize_mod

_LOGGER = logging.getLogger(__name__)


class DeyeDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """
    Asynchronous coordinator for inverter data.
    Uses InverterData which requires host, port, and serial.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        installed_power: float,
    ) -> None:
        assert config_entry is not None  # ✅ for mypy

        self.hass = hass
        self.config_entry = config_entry
        self.installed_power = installed_power
        self._host = config_entry.data["host"]
        self._port = config_entry.data.get("port", 8899)
        self.serial = config_entry.data["serial"]
        # Options win over data: the variant can be changed after setup
        options = getattr(config_entry, "options", None) or {}
        self.mod = normalize_mod(
            options.get(CONF_MOD, config_entry.data.get(CONF_MOD, DEFAULT_MOD))
        )
        self.profile: Profile = get_profile(self.mod)
        self._last_known_data: Dict[str, Any] = {}
        # Created lazily in _async_update_data: the constructor opens a
        # socket, which must not run in the event loop.
        self.inverter: InverterData | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        # The base class may reset config_entry from context; keep ours.
        self.config_entry = config_entry

    def _create_inverter(self) -> InverterData:
        """Create the InverterData client (blocking: opens a socket)."""
        return InverterData(
            host=self._host,
            port=self._port,
            serial=self.serial,
            hass=self.hass,
            config_entry=self.config_entry,
            mod=self.mod,
        )

    async def _async_get_inverter(self) -> InverterData:
        """Return the client, creating it on first use (off the event loop)."""
        if self.inverter is None:
            self.inverter = await self.hass.async_add_executor_job(
                self._create_inverter
            )
        return self.inverter

    async def _async_update_data(self) -> Dict[str, Any]:
        """
        Periodic call: fetch data and handle errors.
        Returns last known data on failure to avoid sensor 'unavailable'.
        """
        try:
            inverter = await self._async_get_inverter()
        except NoSocketAvailableError as e:
            _LOGGER.warning("Inverter unreachable: %s", e)
            if self._last_known_data:
                return self._last_known_data
            raise UpdateFailed(f"Inverter unreachable: {e}")

        try:
            data = await inverter.fetch_data()
            self._last_known_data = data
            return data
        except Exception as err:
            _LOGGER.warning("Modbus read failed, using last known data: %s", err)
            if self._last_known_data:
                return self._last_known_data
            raise UpdateFailed("Initial Modbus read failed with no backup: %s" % err)

    async def async_write_registers(self, addr: int, values: Sequence[int]) -> None:
        """Write registers, then poll so entities show what the inverter has."""
        try:
            inverter = await self._async_get_inverter()
            await inverter.write_registers(addr, values)
        except Exception as err:
            raise HomeAssistantError(
                f"Could not write register 0x{addr:04X}: {err}"
            ) from err
        await self.async_request_refresh()

    async def async_update_register(self, addr: int, mask: int, value: int) -> None:
        """Change the masked bits of one register, then poll."""
        try:
            inverter = await self._async_get_inverter()
            await inverter.update_register(addr, mask, value)
        except Exception as err:
            raise HomeAssistantError(
                f"Could not update register 0x{addr:04X}: {err}"
            ) from err
        await self.async_request_refresh()
