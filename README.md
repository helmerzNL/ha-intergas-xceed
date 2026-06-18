# HeatCon

<p align="center">
  <img src="./icon.png" alt="heatapp! logo" width="180">
</p>

[![Open your Home Assistant instance and add this repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=helmerzNL&repository=ha-heatcon&category=integration)

## Supported devices

This integration works with heat sources built around the **EBV HeatCon!**
controller and reached through the **heatapp!** local gateway:

- **Intergas XCeed** – all-electric heat pump

Other HeatCon!-based systems that expose the same local heatapp! API are
expected to work as well.

## Installation

1. Make sure HACS is installed in Home Assistant.
2. Use the **Add to HACS** button above, or add this repository as a custom integration repository in HACS manually.
3. Install **HeatCon** from HACS.
4. Restart Home Assistant.
5. Add the integration from **Settings -> Devices & Services**.

## Background: HeatCon! controller and heatapp! software

This integration is named **HeatCon** after the **EBV HeatCon!** system
controller (EBV GmbH) it talks to. HeatCon! is an OEM control platform for
heat pumps and other heat sources that several manufacturers ship under their
own branding. The **Intergas XCeed** is one such boiler: it is built around a
HeatCon! controller, so this integration works with it directly, as well as
with other HeatCon!-based systems that expose the same local API.

The controller is operated through the **heatapp!** app and web interface,
which talk to a local gateway/server on your network. Whenever you change a
setting in the manufacturer app or web UI, you are really talking to that
heatapp! / HeatCon! server.

This integration communicates with the same local API. That is why it can
expose far more than the handful of temperatures available over MQTT, including
the configurable settings that the app/web interface offers.

## Goal

The current MQTT setup only exposes a small subset of telemetry, mostly temperatures.  
The target is a real Home Assistant integration that exposes both read-only status and the settings that are configurable in the Intergas app/web UI.

## Configuration

Add the integration from **Settings -> Devices & Services -> Add Integration ->
HeatCon** and provide:

- **Host** - the IP address or hostname of the local heatapp! server/gateway.
- **Username** and **Password** - the same credentials you use in the heatapp!
  app or web interface.
- **Polling interval** - how often Home Assistant refreshes the data, in seconds
  (default `30`, range `10`-`3600`). You can change it later via the
  integration's **Configure** button.

All communication stays on your local network.

## Entities

The integration creates a single **HeatCon** device. The exact set of entities
depends on how many heating zones and which operating modes your installation
exposes; the lists below describe everything it can create.

### Climate - heating zones

One `climate` entity per heating zone:

- Read the current room temperature and adjust the target temperature
  (0.5 °C steps).
- Shows whether the zone is currently heating or cooling.
- Extra attributes expose the day, day 2 and night setpoints, comfort mode,
  cooling-enabled flag, window-open flag, raw status and the weekly schedule.
- Supports the `heatcon.set_schedule` service (see below).

### Water heater - domestic hot water

The domestic hot water (DHW) circuit is exposed as **two** `water_heater`
entities so both setpoints can be read and changed independently:

- **... Day** - the comfort (day) setpoint. Also carries the weekly comfort
  schedule as an attribute.
- **... Night** - the reduced (night) setpoint.

Both report the measured water temperature and whether the circuit is currently
in its **comfort** or **reduced** window. The setpoints, their limits and step
come straight from the boiler's expert (XpertOnly) menu, so they match the
controller one-to-one.

### Number - writable setpoints

Plain numeric setpoints, handy for dashboards and automations:

- Per heating zone: **Day setpoint**, **Day 2 setpoint** and **Night setpoint**
  (only those your zone actually uses).
- Domestic hot water: **Day setpoint** and **Night setpoint** (the same
  wizard-backed values as the water heater entities).

### Time - schedule pickers

Native `time` entities for the switching schedule, one picker per weekday:

- **Domestic hot water** comfort window **start** and **end** per weekday
  (10-minute granularity, matching the controller).
- Per heating zone: **day start** and **night start** per weekday (whole-hour
  granularity, matching the boiler menu).

Set them straight from a dashboard; values are snapped to the granularity the
controller supports before being written. If you prefer time‑picker helpers for
your dashboard, see [`examples/`](./examples) for an optional package that mirrors
these `time` entities to `input_datetime` helpers and keeps them in two‑way sync.

### Sensors

- **Per room** (when reported): actual temperature and desired temperature, plus
  the configured day, day 2 and night temperatures as diagnostic sensors.
- **Outdoor temperature** - the outside temperature reported by the device (with
  daily min/max and location attributes).
- **System status** - `OK` or the first active error message (error count and
  full error list as attributes).
- **Active modes** - a comma-separated list of the operating modes that are
  currently active.

#### Heat pump telemetry (Information menu)

The same read-only values the heatapp! app shows under its **Information**
menus are exposed as sensors. They are read through the device's local
parameter wizard at most once every two minutes, independently of the main
polling cycle, and a sensor is only created when its value is present in your
installation. Values that the controller reports as `--` (not available) become
unavailable rather than wrong. The more installer-oriented readings (individual
refrigerant-circuit temperatures, voltages/currents, start counters and
runtimes, per-day COP history) are marked as diagnostic.

- **Energy & efficiency**: thermal energy produced, energy this month, energy
  this year, thermal output, COP total and COP today (plus COP yesterday as
  diagnostic).
- **Heat generator**: status, pump, volume flow, supply and return flow
  temperatures, ambient temperature, compressor frequency, fan speed and power
  consumption.
- **Refrigerant circuit** (diagnostic): high/low refrigerant pressure, the T1-T4
  circuit temperatures, high/low pressure temperatures and inverter temperature.
- **Electrical** (diagnostic): AC input voltage, heat pump input voltage and
  currents, compressor input current and EEV opening step.
- **Runtime** (diagnostic): compressor total and stage 2 start counts and
  runtimes.
- **System sensors**: heating buffer temperature, outdoor sensor temperature
  (AF), DHW storage sensor temperature, room 1 sensor temperature (diagnostic)
  and the CV system water pressure.

### Binary sensors

- **System error** - on when the controller reports any fault.
- **Per heating zone**: **Cooling**, **Window** and **Comfort mode**.

### Switches - operating modes

One `switch` per heatapp! scene / operating mode. Turning it on activates the
mode for its default duration; turning it off cancels it:

- **Party**, **Boost**, **Holiday**, **Shower**, **Leave**, **Standby** and
  **Towel**.

## Service

**`heatcon.set_schedule`** writes a heating zone's full weekly switching schedule
in one call. Target a zone's `climate` entity and pass `switchingtimes`, a flat
21-slot list (7 days x 3 slots) where each slot is either `null` or
`{ "from": <hour>, "to": <hour>, "type": "H" }`.

## Diagnostics

The integration supports Home Assistant's **Download diagnostics** button on the
device page, which exports the API version and the latest (redacted) payload for
troubleshooting.

## Examples

The [`examples/`](./examples) folder contains optional, copy‑paste Home Assistant
configuration that builds on top of the integration:

- **`examples/packages/heatcon_schedule.yaml`** - recreates 28 `input_datetime`
  time‑picker helpers (one per schedule `time` entity) plus two automations that
  keep the helpers and the native `time` entities in two‑way sync. Handy for
  dashboards. See [`examples/README.md`](./examples/README.md) for setup and the
  prefixes you need to adjust for your install.
