import logging
from typing import Any, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DOMAIN,
    CONF_HOST,
    CONF_PORT,
    CONF_SERIAL,
    CONF_INSTALLED_POWER,
    CONF_MOD,
    CONF_MPPTS,
    DEFAULT_MOD,
    DEFAULT_PV_STRINGS,
    MAX_PV_INPUTS,
    MOD_VARIANTS,
)
from .InverterData import DeviceCapabilities, test_connection
from .profiles import normalize_mod, suggest_mod

_LOGGER = logging.getLogger(__name__)

# Resolved from the inverter's rated power when the entry is created, so what
# gets stored is always a concrete variant
MOD_AUTO = "auto"


def _mod_selector(include_auto: bool) -> SelectSelector:
    options = [str(mod) for mod in MOD_VARIANTS]
    return SelectSelector(
        SelectSelectorConfig(
            options=([MOD_AUTO] + options) if include_auto else options,
            mode=SelectSelectorMode.DROPDOWN,
            translation_key=CONF_MOD,
        )
    )


DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=8899): int,
        vol.Required(CONF_SERIAL): str,
        vol.Required(CONF_INSTALLED_POWER): int,
        vol.Optional(CONF_MOD, default=MOD_AUTO): _mod_selector(include_auto=True),
    }
)


def _detected_strings(capabilities: Any) -> Optional[int]:
    """The MPPT count to start from, if the inverter reports a usable one."""
    mppts = capabilities.mppts if isinstance(capabilities, DeviceCapabilities) else None
    if isinstance(mppts, int) and 1 <= mppts <= MAX_PV_INPUTS:
        return mppts
    return None


def _resolve_mod(selected: Any, capabilities: Any) -> int:
    """Turn the selector value into the variant to store.

    Anything explicit wins; "auto" is derived from the rated power the
    inverter reports, and falls back to the documented scaling when the
    device does not expose it.
    """
    if selected != MOD_AUTO:
        return normalize_mod(selected)
    rated_power = (
        capabilities.rated_power
        if isinstance(capabilities, DeviceCapabilities)
        else None
    )
    mod = suggest_mod(rated_power)
    _LOGGER.info(
        "Detected rated power %s W, using power scaling variant %s",
        rated_power,
        mod,
    )
    return mod


class DeyeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Deye Inverter."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "DeyeOptionsFlow":
        """Return the options flow, which can change the scaling variant."""
        return DeyeOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}

        if user_input is not None:
            # Prevent duplicate entries by serial number
            await self.async_set_unique_id(user_input[CONF_SERIAL])
            self._abort_if_unique_id_configured()

            if not user_input[CONF_SERIAL].strip().isdigit():
                errors[CONF_SERIAL] = "invalid_serial"
            else:
                try:
                    capabilities = await self.hass.async_add_executor_job(
                        test_connection,
                        user_input[CONF_HOST],
                        user_input[CONF_PORT],
                        user_input[CONF_SERIAL],
                    )
                except Exception as err:
                    _LOGGER.warning("Cannot connect to inverter: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    # The selector hands back strings; store a concrete variant
                    data = dict(user_input)
                    data[CONF_MOD] = _resolve_mod(
                        data.get(CONF_MOD, MOD_AUTO), capabilities
                    )
                    detected = _detected_strings(capabilities)
                    if detected is not None:
                        data[CONF_MPPTS] = detected
                    return self.async_create_entry(
                        title=user_input[CONF_SERIAL],
                        data=data,
                    )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    # YAML import (async_setup) funnels through the same validation
    async_step_import = async_step_user


class DeyeOptionsFlow(config_entries.OptionsFlow):
    """Change the scaling variant of an existing inverter."""

    async def async_step_init(self, user_input=None):
        entry = self.config_entry
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_MOD: normalize_mod(user_input.get(CONF_MOD, DEFAULT_MOD)),
                    CONF_MPPTS: int(
                        user_input.get(CONF_MPPTS, self._current_strings())
                    ),
                }
            )

        current = normalize_mod(
            entry.options.get(CONF_MOD, entry.data.get(CONF_MOD, DEFAULT_MOD))
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_MOD, default=str(current)): _mod_selector(
                        include_auto=False
                    ),
                    vol.Optional(CONF_MPPTS, default=self._current_strings()): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=MAX_PV_INPUTS)
                    ),
                }
            ),
        )

    def _current_strings(self) -> int:
        """The configured string count, else the inverter's MPPT count.

        Entries created before this setting existed have nothing stored, so
        fall back to what the running coordinator detected rather than to an
        arbitrary number.
        """
        entry = self.config_entry
        for value in (
            entry.options.get(CONF_MPPTS, entry.data.get(CONF_MPPTS)),
            self._detected_strings_from_coordinator(),
        ):
            try:
                strings = int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if 1 <= strings <= MAX_PV_INPUTS:
                return strings
        return DEFAULT_PV_STRINGS

    def _detected_strings_from_coordinator(self) -> Any:
        """The MPPT count from the last refresh, if the entry is loaded."""
        try:
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]
            return (coordinator.data or {}).get("Device MPPTs")
        except (AttributeError, KeyError, TypeError):
            return None
