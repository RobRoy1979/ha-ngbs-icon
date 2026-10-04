# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The protocol library `pyngbsicon` is
versioned separately (tags `lib-v*`).

## [Unreleased]

### Added
- Project scaffolding: tooling (ruff, mypy, pytest with the Home Assistant test
  harness), Docker-based development environment, CI and release workflows.
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

### pyngbsicon (protocol library, unreleased)
- `IconClient`: complete state with cached configuration, SYSID discovery, confirmed
  writes (setpoints, ECO, child lock, heating/cooling mode, switched output), restart,
  raw requests; requests are serialised and retried once on connection failures.
- Writes wait until the thermostat has adopted the value and report clamped values,
  rejected values (`IconRejectedError`) and ignored system writes.
- Typed, immutable model (`IconSystem`, `IconController`, `IconThermostat`, `Relay`,
  `SignalRef`) including the relay matrix, H/C and ECO masters and signal bits.
- Network scan and probe (`discover`, `probe`, `is_icon_mac`).
- `pyngbsicon` command line tool.
- `IconSystem.uptime` is documented in hours, as the controller reports it.
