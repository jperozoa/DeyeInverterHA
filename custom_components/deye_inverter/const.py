"""Constantes de la integración Deye Inverter."""

DOMAIN = "deye_inverter"
DEFAULT_SCAN_INTERVAL = 30  # segundos
DEFAULT_MODBUS_TIMEOUT = 15  # segundos de timeout en lecturas Modbus
DEFAULT_MODBUS_RETRIES = 2  # reintentos al leer registros

CONF_HOST = "host"
CONF_PORT = "port"
CONF_SERIAL = "serial"
CONF_INSTALLED_POWER = "installed_power"
CONF_MOD = "mod"

# Scaling variant of the inverter ("mod"), used as the index into the
# per-variant ratio lists in DYRealTime.txt. The protocol documentation only
# describes variant 0; the higher-power generations of the single-phase hybrid
# family report power in units of 10 W (and, from variant 2, battery current
# in 0.1 A). Naming and indices follow the community Solarman profile for the
# SG0*LP1 family so values can be cross-referenced.
MOD_VARIANTS = (0, 1, 2)
DEFAULT_MOD = 0

# Holding-register blocks read on every update, as (first, last) inclusive.
# Core blocks must succeed or the whole read fails; optional blocks are read
# best-effort (some devices may not expose them). Order defines the layout of
# the flat register list passed to the parser, so only append new blocks.
CORE_REGISTER_BLOCKS = [
    (0x003B, 0x0074),  # counters, temperatures, alerts, PV1-PV4 voltage/current
    (0x0096, 0x00C3),  # grid, battery, load, PV real-time values
]
OPTIONAL_REGISTER_BLOCKS = [
    (0x0003, 0x000E),  # device info: inverter id, board versions
    (0x00F4, 0x00F8),  # work mode, time of use
    (0x0010, 0x0012),  # rated power, MPPT and phase counts
    (0x00FA, 0x0117),  # time-of-use program, six slots
    (0x0016, 0x0018),  # inverter clock
    (0x008F, 0x008F),  # max sell power
    (0x00D2, 0x00F3),  # battery, grid charge and priority settings
]
# Rated power at or above this (W) means the inverter reports power in 10 W
# units, i.e. scaling variant 2. Inferred from hardware, not documented, so
# it only preselects the variant — the user always has the final say.
TEN_WATT_UNITS_FROM_RATED_POWER = 10000
REGISTER_BLOCKS = CORE_REGISTER_BLOCKS + OPTIONAL_REGISTER_BLOCKS

# Settings the integration writes. All live in the 0x00F4-0x00F8 optional
# block, so the sensors read back whatever a write changed on the next poll.
REG_WORK_MODE = 0x00F4  # 0 selling first, 1 zero-export to load, 2 to CT
REG_SOLAR_SELL = 0x00F7  # 0 off, 1 on; only meaningful in a zero-export mode
REG_TIME_OF_USE = 0x00F8  # bit 0 enables the time-of-use program
TIME_OF_USE_ENABLE_MASK = 0x0001

# The time-of-use program: six slots, each one register per setting, slot n
# at base + n. A slot runs from its start time to the next slot's; slot 6
# wraps around to slot 1. The target SOC is held during the slot: charged
# up to (from the grid only if the flag is set) and not discharged below.
TIME_OF_USE_SLOTS = 6
REG_TOU_START = 0x00FA  # HHMM as a decimal, e.g. 1830
REG_TOU_POWER = 0x0100  # W, charge/discharge limit for the slot
REG_TOU_VOLTAGE = 0x0106  # lead-acid voltage targets, not exposed
REG_TOU_SOC = 0x010C  # %
REG_TOU_CHARGE = 0x0112  # bit 0 grid charge, bit 1 generator charge
TOU_GRID_CHARGE_MASK = 0x0001
TOU_GEN_CHARGE_MASK = 0x0002
# Upper bound for the slot power limit when the inverter does not report
# its rated power; the largest single-phase hybrid in the family.
TOU_POWER_FALLBACK_MAX = 12000

# Global settings, from the Battery and Grid pages of the app. Currents in A,
# SOC in %, power in W; priority 0 battery first, 1 load first. The max
# charge and discharge currents cap everything the time-of-use slots ask for.
REG_MAX_SELL_POWER = 0x008F
REG_MAX_CHARGE_CURRENT = 0x00D2
REG_MAX_DISCHARGE_CURRENT = 0x00D3
REG_BATTERY_SHUTDOWN_SOC = 0x00D9
REG_BATTERY_RESTART_SOC = 0x00DA
REG_BATTERY_LOW_SOC = 0x00DB
REG_GRID_CHARGE_START_SOC = 0x00E5
REG_GRID_CHARGE_CURRENT = 0x00E6
REG_GRID_CHARGE_ENABLE = 0x00E8  # bit 0; the per-slot flags need this on too
GRID_CHARGE_ENABLE_MASK = 0x0001
REG_PRIORITY_MODE = 0x00F3
PRIORITY_MODES = {0: "Battery First", 1: "Load First"}
# Upper bound for the current limits; the largest charger in the family.
MAX_BATTERY_CURRENT = 250

# Inverter clock: (year-2000, month), (day, hour), (minute, second), one
# byte each, high byte first.
REG_CLOCK = 0x0016

PLATFORMS = ["sensor", "select", "switch", "number", "time", "button"]
