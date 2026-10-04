# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The protocol library `pyngbsicon` is
versioned separately (tags `lib-v*`).

## [1.0.0] - 2026-10-04

First release.

### Added
- Documentation: installation with and without HACS, setup, entities, actions,
  automation examples, known limitations, troubleshooting; issue templates and the
  release procedure (`docs/RELEASING.md`).
- Protocol notes for the NGBS iCON local JSON service protocol (`docs/protocol.md`).
- Anonymised controller responses as test fixtures.
- Integration icon and logo.
- Home Assistant integration: setup by network scan, DHCP discovery or address,
  reconfigure, reauthentication, options, migration of entries of the earlier
  community integration with the same domain.
- Devices for the master controller, slave controllers and every installed thermostat.
- Entities: climate per thermostat; system mode (select, or a sensor when an input
  switches heating/cooling), system ECO and switched output (switches); water and
  outdoor temperature, mixing valve, supply voltages, uptime, configuration version,
  default setpoints (sensors); pump, fault, overheat, frost warning, regulation, cloud
  connection and relay outputs (binary sensors); per thermostat temperature,
  humidity, dew point, the four setpoints, setpoint limit, B-loop offsets, output,
  connection, dew point and frost protection, window, time program, ECO follow, child
  lock; a restart button.
- Thermostats installed later get their entities without a reload; thermostats
  uninstalled in the controller are removed.
- Actions `set_setpoints`, `set_system_mode`, `restart_controller`.
- Repair issues: outdated firmware, thermostat offline for over an hour, heating/
  cooling switched outside Home Assistant.
- Diagnostics with secrets, network details and the building name redacted.
- English and Hungarian translations.
- Answers of a controller whose software is starting are skipped (they briefly report
  the heating mode and a water temperature of 0 °C); a single failed poll keeps the
  previous state instead of making every entity unavailable.
- Device and relay names follow rooms renamed in the controller; slave controllers
  show their firmware version.

### pyngbsicon 0.1.0 (protocol library)
- `IconClient`: complete state with cached configuration, SYSID discovery, confirmed
  writes (setpoints, ECO, child lock, heating/cooling mode, switched output), restart,
  raw requests; requests are serialised and retried once on connection failures.
- Writes wait until the thermostat has adopted the value and report clamped values,
  rejected values (`IconRejectedError`) and ignored system writes.
- Typed, immutable model (`IconSystem`, `IconController`, `IconThermostat`, `Relay`,
  `SignalRef`) including the relay matrix, H/C and ECO masters and signal bits.
- Network scan and probe (`discover`, `probe`, `is_icon_mac`).
- `pyngbsicon` command line tool.
- `IconSystem.uptime` is documented in hours (operating system uptime).
- `IconSystem.starting` flags answers of a controller whose software is starting; a
  supply water temperature of exactly 0 is reported as not measured.
