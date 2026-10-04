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
