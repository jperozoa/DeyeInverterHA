import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union

import importlib.resources as pkg_resources

from .const import (
    DEFAULT_MOD,
    REG_BATTERY_LOW_SOC,
    REG_BATTERY_RESTART_SOC,
    REG_BATTERY_SHUTDOWN_SOC,
    REG_CLOCK,
    REG_GRID_CHARGE_CURRENT,
    REG_GRID_CHARGE_START_SOC,
    REG_MAX_CHARGE_CURRENT,
    REG_MAX_DISCHARGE_CURRENT,
    REG_MAX_SELL_POWER,
    REG_PRIORITY_MODE,
    REG_TOU_CHARGE,
    REG_TOU_POWER,
    REG_TOU_SOC,
    REG_TOU_START,
    REGISTER_BLOCKS,
    TIME_OF_USE_SLOTS,
    TOU_GEN_CHARGE_MASK,
    TOU_GRID_CHARGE_MASK,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle only exists for typing
    from .profiles import Profile

_LOGGER = logging.getLogger(__name__)

# Definition keys whose value may be a per-variant list instead of a scalar
_VARIANT_KEYS = ("ratio", "offset")


def _load_definitions() -> Union[Dict[str, Any], List[Any]]:
    try:
        data = (pkg_resources.files(__package__) / "DYRealTime.txt").read_text()
    except Exception:
        fp = Path(__file__).parent / "DYRealTime.txt"
        try:
            data = fp.read_text()
        except Exception as e:
            _LOGGER.error("Could not read DYRealTime.txt: %s", e)
            return {}
    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        _LOGGER.error("Error parsing DYRealTime.txt: %s", e)
        return {}


def iter_sections(
    definitions: Union[Dict[str, Any], List[Any], Any],
) -> Sequence[Dict[str, Any]]:
    """Return the sections of a definitions document, whatever shape it has."""
    if isinstance(definitions, dict):
        return list(definitions.values())
    if isinstance(definitions, list):
        return definitions
    _LOGGER.error("Invalid definitions type: %s", type(definitions))
    return []


def _as_int(value: Any) -> int:
    """Accept either 4096 or "0x1000", as the register lists do."""
    if isinstance(value, str):
        return int(value, 16)
    return int(value)


def select_variant(value: Any, mod: int) -> Any:
    """Pick the entry a scaling variant uses from a per-variant list.

    Scalars are returned unchanged, so only the items that actually differ
    between inverter generations need a list. A variant beyond the end of the
    list reuses the last entry, matching the community profiles this borrows
    the convention from.
    """
    if not isinstance(value, list) or not value:
        return value
    return value[mod] if 0 <= mod < len(value) else value[-1]


def resolve_variant(
    definitions: Union[Dict[str, Any], List[Any]], mod: int
) -> Union[Dict[str, Any], List[Any]]:
    """Collapse the per-variant lists in the definitions down to scalars.

    Done once per variant at load time, so the polling path keeps reading
    plain numbers and stays unaware that variants exist.
    """
    resolved = deepcopy(definitions)
    for section in iter_sections(resolved):
        if not isinstance(section, dict):
            continue
        for item in section.get("items", []):
            for key in _VARIANT_KEYS:
                if key in item:
                    item[key] = select_variant(item[key], mod)
    return resolved


def register_index(reg: int) -> Optional[int]:
    """Map a register address to its index in the flat register list."""
    offset = 0
    for start, end in REGISTER_BLOCKS:
        if start <= reg <= end:
            return offset + (reg - start)
        offset += end - start + 1
    return None


# Definitions exactly as shipped, per-variant lists included
_RAW_DEFINITIONS = _load_definitions()
# ...and resolved for the default variant, which every module-level consumer
# (and every caller that passes no profile) uses.
_DEFINITIONS = resolve_variant(_RAW_DEFINITIONS, DEFAULT_MOD)


def _build_enum_mappings(
    definitions: Union[Dict[str, Any], List[Any]],
) -> Dict[Tuple[int, str], Dict[int, str]]:
    """Build (register, title) -> {key: label} from optionRanges."""
    mappings: Dict[Tuple[int, str], Dict[int, str]] = {}

    # Only build enums if valid optionRanges exist AND interactionType == 2
    for section in iter_sections(definitions):
        for item in section.get("items", []):
            option_ranges = item.get("optionRanges")
            if (
                isinstance(option_ranges, list)
                and option_ranges
                and item.get("interactionType") == 2
            ):
                title = item.get("titleEN")
                if not title:
                    continue

                mapping: Dict[int, str] = {}
                for opt in option_ranges:
                    key = opt.get("key")
                    # Some items label their options "value" instead of
                    # "valueEN" (e.g. Work Mode, Time of use)
                    val = opt.get("valueEN") or opt.get("value")
                    if isinstance(key, int) and isinstance(val, str):
                        mapping[key] = val

                for reg_hex in item.get("registers", []):
                    try:
                        reg = int(reg_hex, 16)
                        mappings[(reg, title)] = mapping
                    except (ValueError, TypeError):
                        continue
    return mappings


_ENUM_MAPPINGS = _build_enum_mappings(_DEFINITIONS)


def combine_registers(
    registers: List[int], signed: bool = True, reverse: bool = False
) -> int:
    if reverse and len(registers) == 2:
        registers = list(reversed(registers))
    value = 0
    for reg in registers:
        value = (value << 16) | (reg & 0xFFFF)
    if signed:
        bits = 16 * len(registers)
        if value & (1 << (bits - 1)):
            value -= 1 << bits
    return value


def parse_battery_status(value: int) -> str:
    if value > 0:
        return "Discharge"
    elif value < 0:
        return "Charge"
    else:
        return "Stand-by"


def parse_grid_status(value: int) -> str:
    if value > 0:
        return "BUY"
    elif value < 0:
        return "SELL"
    else:
        return "Stand-by"


def parse_smartload_status(value: int) -> str:
    if value == 1:
        return "ON"
    elif value == 0:
        return "OFF"
    else:
        return f"Unknown ({value})"


def parse_grid_connected_status(value: int) -> str:
    return "On-Grid" if value == 1 else "Off-Grid"


def parse_gen_connected_status(value: int) -> str:
    return "On" if value == 1 else "Off"


# Work Mode is one setting spread over two registers: 0x00F4 holds the mode
# (0 selling first, 1 zero-export to load, 2 zero-export to home/CT) and
# 0x00F7 the solar sell flag. The optionRanges keys encode the pair: with
# solar sell the mode keeps its key, without it the key is shifted by 2.
# Selling first always sells, so the flag plays no part in it.
def work_mode_key(mode: int, solar_sell: int) -> int:
    """Map the (mode, solar sell) register pair onto a Work Mode option key."""
    return 0 if mode == 0 else (mode if solar_sell else mode + 2)


def work_mode_registers(key: int) -> Tuple[int, Optional[int]]:
    """Map a Work Mode option key back onto (mode, solar sell).

    The inverse of :func:`work_mode_key`. Selling first returns ``None`` for
    the flag, since it is irrelevant there and better left untouched.
    """
    if key == 0:
        return 0, None
    if key in (1, 2):
        return key, 1
    if key in (3, 4):
        return key - 2, 0
    raise ValueError(f"Unknown Work Mode option key: {key}")


# Key under which parse_raw reports the time-of-use program: a list with one
# dict per slot, so the controls and the diagnostics share one parse.
TIME_OF_USE_PROGRAM = "Time of Use Program"


def decode_tou_time(value: int) -> Optional[str]:
    """Turn the HHMM register value into "HH:MM", or None if nonsensical."""
    hours, minutes = divmod(int(value), 100)
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        return None
    return f"{hours:02d}:{minutes:02d}"


def encode_tou_time(hours: int, minutes: int) -> int:
    """Turn a time of day into the HHMM register value."""
    if not (0 <= hours <= 23 and 0 <= minutes <= 59):
        raise ValueError(f"Not a time of day: {hours}:{minutes}")
    return hours * 100 + minutes


def parse_time_of_use(
    raw: Sequence[Optional[int]],
) -> Optional[List[Dict[str, Any]]]:
    """Parse the six time-of-use slots, or None if their block is missing."""
    slots: List[Dict[str, Any]] = []
    for n in range(TIME_OF_USE_SLOTS):
        values: Dict[str, int] = {}
        for name, base in (
            ("start", REG_TOU_START),
            ("power", REG_TOU_POWER),
            ("soc", REG_TOU_SOC),
            ("charge", REG_TOU_CHARGE),
        ):
            idx = register_index(base + n)
            if idx is None or not 0 <= idx < len(raw):
                return None
            value = raw[idx]
            if value is None:
                return None
            values[name] = int(value)
        slots.append(
            {
                "start": decode_tou_time(values["start"]),
                "power": values["power"],
                "soc": values["soc"],
                "grid_charge": bool(values["charge"] & TOU_GRID_CHARGE_MASK),
                "gen_charge": bool(values["charge"] & TOU_GEN_CHARGE_MASK),
            }
        )
    return slots


# Key under which parse_raw reports the global settings, as {field: value}.
SETTINGS = "Settings"
# field -> register, for the settings that are one plain number each
SETTING_REGISTERS: Dict[str, int] = {
    "max_sell_power": REG_MAX_SELL_POWER,
    "max_charge_current": REG_MAX_CHARGE_CURRENT,
    "max_discharge_current": REG_MAX_DISCHARGE_CURRENT,
    "battery_shutdown_soc": REG_BATTERY_SHUTDOWN_SOC,
    "battery_restart_soc": REG_BATTERY_RESTART_SOC,
    "battery_low_soc": REG_BATTERY_LOW_SOC,
    "grid_charge_start_soc": REG_GRID_CHARGE_START_SOC,
    "grid_charge_current": REG_GRID_CHARGE_CURRENT,
    "priority_mode": REG_PRIORITY_MODE,
}
# Key under which parse_raw reports the inverter's clock, as "YYYY-MM-DD HH:MM:SS"
INVERTER_TIME = "Inverter Time"


def _register_value(raw: Sequence[Optional[int]], reg: int) -> Optional[int]:
    """One register's value, or None if it was not read."""
    idx = register_index(reg)
    if idx is None or not 0 <= idx < len(raw):
        return None
    value = raw[idx]
    return None if value is None else int(value)


def parse_settings(raw: Sequence[Optional[int]]) -> Dict[str, int]:
    """The global settings that were read, by field. Unread ones are absent."""
    settings: Dict[str, int] = {}
    for field, reg in SETTING_REGISTERS.items():
        value = _register_value(raw, reg)
        if value is not None:
            settings[field] = value
    return settings


def decode_clock(regs: Sequence[int]) -> Optional[str]:
    """Turn the three clock registers into "YYYY-MM-DD HH:MM:SS"."""
    if len(regs) != 3:
        return None
    year, month = regs[0] >> 8, regs[0] & 0xFF
    day, hour = regs[1] >> 8, regs[1] & 0xFF
    minute, second = regs[2] >> 8, regs[2] & 0xFF
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    if not (hour <= 23 and minute <= 59 and second <= 59):
        return None
    return f"20{year:02d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"


def encode_clock(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> List[int]:
    """The three clock registers for a date and time."""
    return [
        ((year - 2000) & 0xFF) << 8 | month,
        day << 8 | hour,
        minute << 8 | second,
    ]


def parse_clock(raw: Sequence[Optional[int]]) -> Optional[str]:
    """The inverter's clock, or None if its block was not read."""
    regs = [_register_value(raw, REG_CLOCK + i) for i in range(3)]
    if any(r is None for r in regs):
        return None
    return decode_clock([r for r in regs if r is not None])


def parse_raw(
    raw: Sequence[Optional[int]], profile: Optional["Profile"] = None
) -> Dict[str, Any]:
    """Parse a flat register list into {metric title: value}.

    Without a profile the default scaling variant is used, so existing
    callers and tests keep the documented behaviour.
    """
    result: Dict[str, Any] = {}

    REVERSED_FIELDS = {
        "Total Production",
        "Total Load Consumption",
        "Total Energy Sold",
        "Total Energy Bought",
        "Total Grid Production",
        "Total Battery Charge",
        "Total Battery Discharge",
        "Device Rated Power",
    }

    definitions = _DEFINITIONS if profile is None else profile.definitions
    enum_mappings = _ENUM_MAPPINGS if profile is None else profile.enum_mappings

    for section in iter_sections(definitions):
        for item in section.get("items", []):
            title = item.get("titleEN")
            if not title:
                continue

            try:
                ratio = float(item.get("ratio", 1))
                offset = float(item.get("offset", 0))
                signed = bool(item.get("signed", True))
                parser_rule = item.get("parserRule")
                registers = item.get("registers", [])

                if not registers:
                    continue

                indices = []
                for reg_hex in registers:
                    idx = register_index(int(reg_hex, 16))
                    if idx is not None:
                        indices.append(idx)

                # A register missing from the list (short read, or a block the
                # caller never read) must drop the metric: combining only part
                # of a multi-register value would report a plausible wrong
                # number instead of nothing.
                if len(indices) != len(registers):
                    continue
                values = [raw[i] for i in indices if 0 <= i < len(raw)]
                # None marks an optional block that could not be read
                block = [v for v in values if v is not None]
                if not block or len(block) != len(indices):
                    continue

                # Rule 5: ASCII string
                if parser_rule == 5:
                    chars = []
                    for word in block:
                        chars.append((word >> 8) & 0xFF)
                        chars.append(word & 0xFF)
                    ascii_string = (
                        bytearray(chars)
                        .decode("ascii", errors="ignore")
                        .strip("\x00")
                        .strip()
                    )
                    if not ascii_string or any(ord(c) < 32 for c in ascii_string):
                        value = "0x" + "".join(f"{b:02X}" for b in chars)
                    else:
                        value = ascii_string
                    result[title] = value or None
                    continue

                reverse = title in REVERSED_FIELDS
                raw_int = combine_registers(block, signed=signed, reverse=reverse)

                # Some registers pack several values into one word (0x0012
                # carries the MPPT count and the phase count)
                mask = item.get("mask")
                if mask is not None:
                    raw_int &= _as_int(mask)
                shift = item.get("shift")
                if shift:
                    raw_int >>= _as_int(shift)

                # Custom logic overrides
                reg_key = int(registers[0], 16)
                if reg_key == 0x00F4 and title == "Work Mode" and len(block) == 2:
                    mode, solar_sell = block
                    key = work_mode_key(mode, solar_sell)
                    wm_mapping = enum_mappings.get((reg_key, title), {})
                    result[title] = wm_mapping.get(
                        key, f"Unknown ({mode}/{solar_sell})"
                    )
                    continue
                if reg_key == 0x00BE and title == "Battery Status":
                    result[title] = parse_battery_status(raw_int)
                    continue
                if reg_key == 0x00A9 and title == "Grid Status":
                    result[title] = parse_grid_status(raw_int)
                    continue
                if reg_key == 0x00C3 and title == "SmartLoad Enable Status":
                    result[title] = f"{parse_smartload_status(raw_int)}"
                    continue
                if reg_key == 0x00C2 and title == "Grid-connected Status":
                    result[title] = f"{parse_grid_connected_status(raw_int)}"
                    continue
                if reg_key == 0x00A6 and title == "Gen-connected Status":
                    result[title] = f"{parse_gen_connected_status(raw_int)}"
                    continue

                # Enum mapping by (register, title)
                mapping = enum_mappings.get((reg_key, title))
                if mapping and raw_int in mapping:
                    result[title] = mapping[raw_int]
                    continue
                elif mapping:
                    result[title] = f"Unknown ({raw_int})"
                    continue

                # Alert/bitfields: store as hex string to stay JSON-serializable
                if parser_rule == 6:
                    result[title] = "0x" + "".join(f"{w:04X}" for w in block)
                    continue

                # Default: numeric
                if "Temperature" in title:
                    val = raw_int * ratio - 100 + offset
                else:
                    val = raw_int * ratio + offset
                result[title] = float(round(val, 2))

            except Exception as e:
                _LOGGER.debug("Error parsing %s: %s", title, e)
                continue

    program = parse_time_of_use(raw)
    if program is not None:
        result[TIME_OF_USE_PROGRAM] = program
    settings = parse_settings(raw)
    if settings:
        result[SETTINGS] = settings
    clock = parse_clock(raw)
    if clock is not None:
        result[INVERTER_TIME] = clock

    return result
