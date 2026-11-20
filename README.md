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
- 🎛️ Controls: work mode, the full time-of-use program, battery and grid-charge limits, clock sync

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

Besides reading, the integration can change the inverter's settings. Every
control lives in the *Configuration* section of the device page (the
*Diagnostic* section holds the read-only sensors) and writes straight to the
inverter over the same Modbus connection the sensors use, exactly as the
Solarman app would. They are not simulations: a change takes effect on the
inverter within a minute and survives a power cycle. Read this section once
before wiring any of them into an automation.

### How a write works

Each change is one register write. The integration reads the register, writes
the new value, and reads it back:

- **Stored as asked**: the entity shows the new value on the next poll.
- **Stored adjusted**: some values are rounded or clamped by the inverter, for
  example slot start times go to five-minute steps. That counts as written,
  and the entity shows what the inverter actually kept.
- **Ignored**: if the register still holds the old value a second later, the
  write raises an error in the UI instead of pretending it worked.

Writes that pack several settings into one register (the switches) change
only their own bit. Writes are serialised with the polling, so a change
never interleaves with a read.

### The three layers of battery control

The settings interact, and the picture is simpler once you see them as
three layers. **The inverter always applies the tightest limit that
applies.**

1. **Hard limits**, always in force: *Max Charge Current*, *Max Discharge
   Current*, *Battery Shutdown SOC*. Nothing below can exceed these.
2. **The time-of-use program**, when its switch is on: six slots, each with
   its own SOC target, discharge power limit and grid-charge flag. The active
   slot decides what the battery does right now.
3. **The global grid-charge settings**: the *Grid Charge* switch, its current
   and its start SOC. The switch is a master enable: with it off the inverter
   never charges from the grid, whatever a slot says.

Current limits are in amps, so the power they allow depends on battery
voltage: 60 A at 52 V is about 3.1 kW.

### Global settings

| Entity | What it means | Notes |
|---|---|---|
| **Max Charge Current** (A) | The most current the inverter will ever push into the battery, from PV, grid or generator. | The ceiling on every kind of charging. Set it from the battery's datasheet, not from how fast you would like to charge. |
| **Max Discharge Current** (A) | The most current the battery will ever supply. | Caps how much of the house load the battery can cover. |
| **Battery Low SOC** (%) | The level the battery is not discharged below in normal operation when the time-of-use program is off. | With the program on, the active slot's SOC takes this role. |
| **Battery Shutdown SOC** (%) | Hard stop: below this the inverter stops discharging regardless of anything else. | Protects the battery. Keep it below *Low SOC*. |
| **Battery Restart SOC** (%) | After a shutdown, discharging resumes once the battery has recharged to this level. | Keep it above *Low SOC*; the three are not cross-checked. |
| **Grid Charge** (switch) | Master enable for charging the battery from the grid. | Off: the grid never charges the battery, even if a slot asks for it. On: the slots (or, with the program off, *Grid Charge Start SOC*) decide when. |
| **Grid Charge Current** (A) | The rate used when charging from the grid. | Still capped by *Max Charge Current*. This is the knob for a gentle overnight charge, e.g. 28 A for about 1.5 kW. |
| **Grid Charge Start SOC** (%) | With the program off and *Grid Charge* on, the grid starts charging when the battery drops below this. | Ignored while a slot controls grid charging. |
| **Max Sell Power** (W) | Export cap at the grid connection. | Only matters in a work mode that sells. |
| **Priority Mode** | Where PV surplus goes first once the house is served: *Battery First* or *Load First*. | *Load First* is the usual choice for self-consumption. |
| **Work Mode** | *Selling First* exports any surplus. The four *Zero-Export* modes never export: *to Load* measures at the inverter's load port, *to Home* at the CT clamp on the grid connection. The *& Solar Sell* variants still export genuine PV surplus. | Writes two registers, the mode and the solar-sell flag. |
| **Sync Clock** (button) | Sets the inverter's clock to Home Assistant's local time. | The time-of-use program runs on the inverter's clock, which drifts and is corrected by nothing else. *Inverter Time* shows it; a slot switching early or late is usually this. |

### The time-of-use program

The program splits the day into six slots. Each slot starts at its own time
and runs until the next slot starts; slot 6 runs past midnight until slot 1
begins, so the six always cover the full 24 hours with no gaps. Keep the start
times in ascending order: the inverter does not sort them.

| Entity (per slot N) | What it means |
|---|---|
| **Time of Use** (switch, global) | Turns the whole program on or off. Only the enable bit is touched; the weekday bits in the same register keep their values. With the program off the inverter falls back to *Priority Mode* and the global SOC thresholds. |
| **Time of Use N Start** | When the slot begins. Stored in five-minute steps. |
| **Time of Use N SOC** (%) | The battery level the inverter holds during the slot. Below it, the battery is charged up to it (from the grid only if the slot's *Grid Charge* is on and the global *Grid Charge* switch is on). Above it, the battery may discharge down to it, and no further. |
| **Time of Use N Power** (W) | The battery **discharge** limit during the slot: the most the battery contributes to the house load. It does not limit grid charging, which follows *Grid Charge Current*. 0 parks the battery for the slot. |
| **Time of Use N Grid Charge** | Whether the grid may charge the battery up to the slot's SOC during this slot. Needs the global *Grid Charge* switch on to have any effect. |
| **Time of Use N Generator Charge** | Same for a generator on the gen port. Disabled by default in the entity registry; enable it only if you have one. |

So the slot SOC is both a floor and a goal, and the pair *(SOC, Grid Charge)*
is what you set per slot:

| Slot SOC | Grid charge | Behaviour |
|---|---|---|
| 100 % | on | Fill the battery from the grid (cheap tariff window) |
| 20 % | off | Use the battery freely down to 20 % (expensive window) |
| 50 % | off | Use the battery, but keep half for later |
| current SOC | off, power 0 | Hold: neither charge nor discharge |

### Recipes

**Charge from the grid right now.** Find the active slot (the one whose start
time is the latest before now) and set, in this order: its *SOC* to the
target, its *Grid Charge* on, and the global *Grid Charge* on. The rate is
*Grid Charge Current*, capped by *Max Charge Current*. Charging stops at the
target or when the next slot starts, whichever comes first; give the next slot
the same two settings to continue. Put the slot back afterwards, or it repeats
every day at that time. As a script, with the slot and target as parameters:

```yaml
script:
  battery_grid_charge_start:
    fields:
      slot: { default: 5 }
      soc: { default: 80 }
    sequence:
      - action: number.set_value
        target: { entity_id: "number.deye_inverter_<serial>_time_of_use_{{ slot }}_soc" }
        data: { value: "{{ soc }}" }
      - action: switch.turn_on
        target: { entity_id: "switch.deye_inverter_<serial>_time_of_use_{{ slot }}_grid_charge" }
      - action: switch.turn_on
        target: { entity_id: switch.deye_inverter_<serial>_grid_charge }

  battery_grid_charge_stop:
    fields:
      slot: { default: 5 }
      soc: { default: 25 }
    sequence:
      - action: switch.turn_off
        target: { entity_id: switch.deye_inverter_<serial>_grid_charge }
      - action: switch.turn_off
        target: { entity_id: "switch.deye_inverter_<serial>_time_of_use_{{ slot }}_grid_charge" }
      - action: number.set_value
        target: { entity_id: "number.deye_inverter_<serial>_time_of_use_{{ slot }}_soc" }
        data: { value: "{{ soc }}" }
```

**Cheap night tariff.** Give the night slot SOC 100 % with grid charge on,
the morning and midday slots a low SOC with grid charge off so PV does the
work, and the evening slot the lowest SOC you are comfortable with. Leave the
global *Grid Charge* on permanently and set *Grid Charge Current* to the rate
you want overnight.

**Keep a reserve for the evening peak.** Set the afternoon slot's SOC to,
say, 60 % with grid charge off: the battery still discharges, but stops at
60 %, and the evening slot with SOC 20 % then releases the rest.

**Stretch the battery through the night.** Lower the night slot's *Power* to
roughly the house's base load: the battery covers that much and the grid
takes the peaks, so the stored energy lasts until morning instead of being
drained by the first big appliance.

**Keep the inverter's clock right.** An automation that presses *Sync Clock*
once a day:

```yaml
automation:
  - alias: Sync inverter clock
    triggers:
      - trigger: time
        at: "03:00:00"
    actions:
      - action: button.press
        target: { entity_id: button.deye_inverter_<serial>_sync_clock }
```

### Caveats

- **Several writes in a row**: each one is a Modbus round trip of a second or
  so, and the inverter may need a moment to store a value. The integration
  waits for that, but do not fire dozens of writes at once.
- **The datalogger accepts one TCP client at a time.** A write fails while
  the Solarman app holds a local connection, and the app may rewrite settings
  you changed here when it syncs. Close it while testing.
- **Changes made here show in the app** on its next refresh, and vice versa,
  since both write the same registers.
- **Not exposed on purpose**: battery voltage thresholds (for lead-acid in
  voltage mode), grid voltage and frequency protection limits, and remote
  power-off. A wrong value there can stop the system or damage the battery.
- The register addresses follow the single-phase hybrid family (SUN-3K to
  SUN-12K-SG0xLP1) and were verified on a SUN-10K-SG02LP1. Three-phase
  models use a different map and these controls will not work on them.

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
