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

## Recommended direction

Build a **local custom integration** that talks to the heater directly over its HTTP API instead of relying only on MQTT.

Why:
- MQTT is useful for a few live values, but it does not cover the full control surface.
- The reverse-engineered login and signed `/admin/*` calls already give a stable base for authenticated access.
- A custom integration can expose entities, services, diagnostics, and future automation hooks in a native HA way.

## Architecture

1. **API client**
   - Challenge/response login
   - Session token handling
   - Signature generation for `/admin/*`
   - Token refresh / reconnect logic

2. **Coordinator**
   - Polls runtime state on an interval
   - Normalizes API responses into a single device model
   - Keeps write operations separate from refresh polling

3. **Entities**
   - Climate: one entity per heating zone with a writable target temperature
   - Water heater: the domestic hot water (DHW) circuit, split into a Day
     (comfort) and a Night (reduced) entity. Each exposes its own writable
     setpoint that mirrors the boiler menu exactly; the day entity also
     carries the weekly comfort schedule as an attribute. Both report whether
     the circuit is currently in its comfort or reduced window
   - Number: writable day/day2/night comfort setpoints per heating zone. For
     the DHW circuit it also exposes the day and night water setpoints that
     mirror the boiler's own menu exactly
   - Time: per-weekday domestic hot water comfort window start/end pickers
     (HH:MM, snapped to the 10-minute grid the controller supports), plus
     per-weekday day-start/night-start pickers for each heating zone's comfort
     schedule (whole-hour granularity, matching the boiler menu)
   - Sensors: per-room actual/desired/day/night temperatures, outdoor temperature, system status, active modes
   - Binary sensors: cooling, window, comfort mode, and a system problem indicator
   - Switches: one per heatapp! scene (Party, Boost, Holiday, Shower, Leave, Standby, Towel)
   - Service: `heatcon.set_schedule` to write a zone's weekly switching times

4. **Diagnostics**
   - API version and device information
   - Last aggregated payload (redacted)

## Practical implementation order

1. Confirm the runtime data endpoint that powers the app/web UI.
2. Build a read-only integration first.
3. Add native write entities for the most important settings.
4. Add service-based writes for advanced or grouped configuration.
5. Keep MQTT as an optional fallback, not the primary interface.

## Suggested first milestones

- Inventory all app/web configurable fields and group them by HA platform type.
- Map each field to one of: sensor, number, select, switch, or service.
- Verify which values can be read from the runtime endpoint versus admin config endpoints.
- Implement one end-to-end path: login -> poll -> expose entities -> change one setting.

## Current status

- The login, signature flow, and the live runtime `/api/*` endpoints used by the heatapp! app/web UI are confirmed against a real device.
- Reads (rooms, scenes, system state, weather, schedules) and writes (zone/DHW target temperature, day/day2/night setpoints, weekly schedules, scene activation) are implemented and verified.
- The domestic hot water circuit requires `change_mode=1` on a temperature write; heating zones use `change_mode=0`. Both are handled automatically.
- The domestic hot water day/night setpoints and 7-day schedule that are only
  reachable through the boiler's expert menu are read and written through the
  heatapp! XpertOnly parameter wizard, so they match the controller menu values
  one-to-one. The comfort window start/end are exposed as `time` entities with
  10-minute granularity (the controller's switching-time encoding is HH.MM with
  literal minutes, not decimal hours). The heating-zone day-start/night-start
  schedule is exposed as whole-hour `time` entities, matching its own
  `/api/room` switching-time API.

## Repository status

This repository contains a **HACS-publishable custom integration** in `custom_components/heatcon`.

Included:
- HACS metadata (`hacs.json`)
- Home Assistant manifest and config flow
- API client with the confirmed login/signature flow and AES device-token decryption
- Polling data update coordinator with a typed device model
- Climate, water heater, number, time, sensor, binary sensor, and switch platforms backed by the live API
- A `set_schedule` service for writing weekly switching times, plus per-weekday
  day-start/night-start `time` pickers for the comfort schedule
- Diagnostics export
- English and Dutch translations

## Releases and update notes

HACS reads update information from the **GitHub release body**. To make those
notes useful in Home Assistant:

1. Update the integration version in `custom_components/heatcon/manifest.json`
   (the value without the leading `v`).
2. Create a GitHub release whose tag matches that version (for example `v0.4.1`)
   and target the default branch (`main`).
3. Keep the release title and notes in **English**.
4. Apply the matching PR label so the notes are grouped automatically:
   `enhancement` (New Features), `bug`/`fix` (Fixes), `breaking-change`
   (Breaking Changes), `documentation`/`chore`/`ci`/`refactor`/`dependencies`
   (Maintenance), or `skip-release-notes` to leave a PR out.

### Where Home Assistant shows the notes

The release body is shown when you **update** an already-installed integration,
not on the first download:

- **Settings → System → Updates** → open the HeatCon update to read the
  release notes in the dialog.
- **Developer Tools → States** → the `update.*` entity exposes the same text in
  its `release_summary` attribute.

The HACS "… will be downloaded …" confirmation shown on a fresh install or
redownload intentionally does **not** include a changelog, so check the update
dialog above instead.

This repository includes:
- `.github/release.yml` to group autogenerated GitHub release notes
- `.github/pull_request_template.md` to keep PR summaries and release notes consistent

## Short-term roadmap

1. Map any remaining app/web configurable fields to `number`/`select`/`button` platforms.
2. Add tests and CI.
