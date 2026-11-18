# Deye Inverter Integration for Home Assistant

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Quality: Silver](https://img.shields.io/badge/Quality-Silver-silver)
![Tests](https://github.com/jperozoa/DeyeInverterHA/actions/workflows/python-app.yml/badge.svg)
![Coverage](https://codecov.io/gh/jperozoa/DeyeInverterHA/branch/main/graph/badge.svg)

## Overview

This custom integration allows Home Assistant to read **real-time data** from **Deye hybrid inverters** over Modbus TCP, using a mapping file based on `DYRealTime.txt` and powered by [`PySolarmanV5`](https://github.com/jmccrohan/pysolarmanv5) and `pymodbus`.

It creates **one sensor entity per inverter metric** (40+ entities), all grouped under a single inverter device, with proper device classes and state classes — so energy metrics work with the **Energy dashboard** and get long-term statistics.

---

## Features

- 📡 Real-time data from Deye hybrid inverters
- 🧠 Based on `PySolarmanV5` and `pymodbus`
- 🧩 UI-based configuration (no YAML needed)
- 📊 One entity per metric (40+ sensors) with device/state classes and statistics
- ⚡ Energy dashboard support (kWh sensors with `total_increasing`)
- 💡 Works offline — no cloud dependency
- 🎛️ Controls for the work mode and the time-of-use program

---

## Installation

This integration is **not yet in HACS**. You can install it manually for now:

### Requirements

- Home Assistant 2021.12 or newer
- Network access to your inverter's Modbus TCP interface

### Manual Steps

1. Download or clone this repository:

   ```bash
   git clone https://github.com/jperozoa/DeyeInverterHA.git
   ```

2. Copy the folder `custom_components/deye_inverter` into your Home Assistant config directory:

   ```
   config/custom_components/deye_inverter
   ```

3. Restart Home Assistant.

4. In the UI, go to Settings > Devices & Services > Add Integration, search for Deye Inverter, and follow the setup steps.

## Configuration
Once installed, the integration can be configured entirely through the Home Assistant UI.

You will be asked for:

- Host: The IP address of your inverter
- Port: Modbus TCP port (default: 8899)
- Serial Number: The datalogger’s serial number (something like 17XXXXXX)
- Installed Power (kW): Used for the *Production* (%) sensor
- Power scaling variant: See [Power scaling variant](#power-scaling-variant) below — leave it on *Detect automatically*

The connection is tested before the entry is created — if the inverter is not
reachable (wrong host/port/serial, or another client is holding the datalogger's
single TCP slot) the form shows an error instead of creating a broken entry.

### Power scaling variant

The single-phase hybrid family shares one register map, but not every
generation reports the same units. The protocol documentation describes power
in watts and battery current in 0.01 A steps, which is what the smaller
inverters do — but the 10–12 kW models report load, grid and CT power in units
of **10 W**, and some of them battery current in **0.1 A**. Nothing in the
protocol identifies which behaviour a given unit has, so you select it:

| Variant | Load / grid / CT power | Battery current | Typical models |
|---------|------------------------|-----------------|----------------|
| **0** (default) | as documented (× 1) | 0.01 A | single-phase hybrids up to ~8 kW |
| **1** | × 10 | 0.01 A | some 10 kW+ units |
| **2** | × 10 | 0.1 A | SUN-10K/12K-SG02LP1 and similar |

Every other metric — PV, inverter and total power, voltages, energy counters,
temperatures — is identical across variants.

**Detection.** The default choice, *Detect automatically*, reads the rated
power the inverter reports (registers `0x0010`–`0x0011`) when the entry is
created: 10 kW or more selects variant 2, anything less keeps variant 0. What
gets stored is always the concrete variant, so you can see and change it
afterwards. Inverters that do not expose that register keep variant 0, and the
detected properties also appear as diagnostic entities (*Device Rated Power*,
*Device MPPTs*, *Device Phases*).

The threshold is inferred from hardware, not from the protocol documentation,
so verify it once — and note that variant 1 is never auto-selected, since
nothing in the device distinguishes it from variant 2.

**How to tell which one you need.** With the inverter running and a known load
on, check that the instantaneous balance adds up:

```
PV output ≈ Total Load Power + Total Grid Power + Battery Power
```

On the wrong variant the load and grid figures are off by exactly 10×, so the
balance misses by roughly 90 % and *Total Load Power* reads far below what your
meter says. On variant 2 you can also verify that *Battery Voltage* ×
*Battery Current* reproduces *Battery Power*.

Change it any time under **Settings → Devices & Services → Deye Inverter →
Configure**; the integration reloads and applies the new scaling immediately.
Energy-dashboard statistics already recorded with the wrong variant are not
rewritten — remove the affected statistics if the history matters to you.

## Entities

All entities are grouped under one **Deye Inverter** device.

### Aggregate Sensor
*Power* — total inverter PV production across every string, kept for backward
compatibility. Its unique ID is unchanged, so installations created before the
per-metric entities keep their original `sensor.deye_inverter` entity ID and
history; new installations name it `sensor.deye_inverter_<serial>_power`.

> **Changed:** this used to sum PV1 + PV2 only, so inverters with a third or
> fourth MPPT under-reported their array. It now covers every string the
> inverter reports, which means the value steps up on those models.

### PV Strings
PV1 and PV2 are always present. *PV3* and *PV4* voltage, current and power
appear only when the inverter reports that many MPPTs (see *Device MPPTs*), so
a two-string inverter gets no entities stuck at zero. If the inverter does not
expose its MPPT count, all strings are created.

### Production Sensor
*Production* — current PV output as a percentage of the installed power you configured (e.g. 800 W of 5 kW → 16 %). Uses the same all-string total as the aggregate sensor.

> **Breaking change:** this sensor no longer exposes the inverter metrics as
> `extra_state_attributes`. Templates reading attributes from it must switch to
> the dedicated per-metric sensors below. Status values are now plain strings
> (e.g. `Discharge` instead of `Discharge (12)`) and Total Grid Production is
> numeric.

### Per-Metric Sensors
One sensor per metric, named after the metric (e.g. *PV1 Power*, *Battery SOC*, *Total Grid Production*). Units, device classes, and state classes are derived automatically, so:

- Power/voltage/current/temperature sensors record statistics (`measurement`)
- Energy sensors (kWh) use `total_increasing` and can be used in the **Energy dashboard**
- Status sensors (Battery Status, Grid Status, Running Status, Alert, …) are text sensors in the *Diagnostic* category

Available metrics:

- PV: PV1/PV2 Voltage, Current, Power; Daily/Total Production; Micro-inverter Power
- Battery: Voltage, Current, Power, SOC, Temperature, Status, Daily/Total Charge and Discharge
- Grid: Grid Voltage L1/L2, Grid Current L1/L2, Grid Frequency, Grid Status, Grid-connected Status, Total Grid Power, Total Grid Production, Daily/Total Energy Bought and Sold, Internal/External CT L1/L2 Power
- Load: Load L1/L2 Power, Load Voltage, Load Frequency, Total Load Power, Daily/Total Load Consumption, SmartLoad Enable Status
- Inverter: Running Status, Total Power, Current L1/L2, Inverter L1/L2 Power, AC/DC Temperature, Gen Power, Gen-connected Status, Inverter ID, Board versions, Work Mode
- Alert (bitfield, hex string)

The battery Daily/Total Charge and Discharge sensors can be used in the Energy
dashboard's battery section.

## Controls

Two settings can be changed from Home Assistant. Both appear in the
*Configuration* section of the device page and write straight to the inverter
over the same Modbus connection the sensors use.

| Entity | Type | Registers | What it does |
|---|---|---|---|
| *Work Mode* | select | `0x00F4`, `0x00F7` | Selling First, or one of the four zero-export modes (to load / to home, with or without solar sell) |
| *Time of Use* | switch | `0x00F8` bit 0 | Enables or disables the inverter's time-of-use program |
| *Time of Use N Start* | time | `0x00FA`+N | When slot N begins (it lasts until the next slot starts; slot 6 wraps to slot 1) |
| *Time of Use N SOC* | number | `0x010C`+N | Battery level held during the slot: charged up to it, never discharged below it |
| *Time of Use N Power* | number | `0x0100`+N | Charge/discharge power limit during the slot, in W |
| *Time of Use N Grid Charge* | switch | `0x0112`+N bit 0 | Whether the grid may charge the battery up to the slot's SOC |
| *Time of Use N Generator Charge* | switch | `0x0112`+N bit 1 | Same for a generator; disabled by default in the entity registry |

Every write is read back and compared, and the entity only changes state once
the next poll confirms the inverter took the new value. A refused or ignored
write raises an error in the UI instead of pretending it worked. Values the
inverter adjusts count as written: slot start times, for instance, are
rounded to five-minute steps, and the entity shows what was stored.
The *Time of Use* switch touches only the enable bit, so the weekday bits that
share the register keep their values.

Notes:

- These change the inverter's persistent configuration, exactly as the Solarman
  app does. They are not simulations; check the effect on your system before
  wiring them into automations.
- The datalogger accepts one TCP client at a time, so a write fails while the
  Solarman app or cloud holds the connection.
- The six slots always cover the whole day: a slot ends where the next one
  begins, and slot 6 runs until slot 1 starts again. Keep the start times in
  order; the inverter does not sort them for you.
- The per-slot voltage targets (`0x0106`–`0x010B`) only apply to lead-acid
  batteries in voltage mode and are not exposed.

## Energy Dashboard

The integration exposes everything Home Assistant's Energy dashboard needs for a
hybrid PV + battery installation. Go to **Settings → Dashboards → Energy** and
configure:

| Energy dashboard section | Field | Sensor to select |
|---|---|---|
| **Electricity grid** | Grid consumption | `Total Energy Bought` |
| **Electricity grid** | Return to grid | `Total Energy Sold` |
| **Solar panels** | Solar production | `Total Production` |
| **Home battery storage** | Energy going in to the battery | `Total Battery Charge` |
| **Home battery storage** | Energy coming out of the battery | `Total Battery Discharge` |

Notes:

- Always pick the **Total** counters, not the Daily ones — Home Assistant
  computes hourly/daily deltas from long-term statistics itself, and the
  lifetime counters are the most robust source for that.
- Entity names above are as shown in the picker; the entity ids follow the
  pattern `sensor.deye_inverter_<serial>_total_energy_bought`, etc.
- After configuring, the dashboard needs up to **an hour** to show the first
  data: statistics are compiled every 5 minutes, but the energy panel
  aggregates them per hour.
- Optionally add your grid price in the *Grid consumption* entry to get cost
  tracking.

## Troubleshooting

🔌 No data / Sensor unavailable:

Check inverter IP and port (default is usually 8899)
Verify that the inverter is online and responding to Modbus TCP
Check if the serial number is correct

⚙️ Integration not showing up:

Make sure files are correctly placed under `config/custom_components/deye_inverter`

Restart Home Assistant

### Reporting a wrong value

Register maps differ between models in ways the protocol documentation does not
describe, so "what does this inverter actually put in that register" is usually
the only question that matters. Answer it in one file:

**Settings → Devices & Services → Deye Inverter → ⋮ → Download diagnostics**

The download contains every register block exactly as read — address by
address, plus a hex dump — next to the values parsed from them, along with the
scaling variant in use and which blocks the inverter refused. Host, serial
number and *Inverter ID* are redacted, so it is safe to attach to an issue.

If a metric is missing entirely rather than wrong, check the `blocks` section:
a block with `"ok": false` means the inverter rejected that range, and every
metric living in it is dropped for that cycle.

## Contributing
This integration is under active development and contributions are welcome. If you encounter issues or have suggestions:

Open an issue

Submit a pull request with improvements or fixes

## License
This project is licensed under the MIT License. See the LICENSE file for details.
