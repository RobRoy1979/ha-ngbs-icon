<p align="center">
  <img src="custom_components/ngbs_icon/brand/logo@2x.png" alt="NGBS iCON" width="420">
</p>

# NGBS iCON for Home Assistant

[![CI](https://github.com/robroy1979/ha-ngbs-icon/actions/workflows/ci.yml/badge.svg)](https://github.com/robroy1979/ha-ngbs-icon/actions/workflows/ci.yml)
[![License: BUSL-1.1](https://img.shields.io/badge/license-BUSL--1.1-blue)](LICENSE)

> **Work in progress.** The integration is being built; nothing is released yet.

A Home Assistant integration for **NGBS iCON** surface heating/cooling controllers
(iCON-1, iCON-2 with iCON 100/200 room thermostats). It talks to the controller
directly on your local network — no cloud account — finds it automatically, and
exposes every room as a climate entity with its temperature, humidity, dew point,
four setpoints, ECO mode and child lock, plus the system's heating/cooling mode,
water temperature, pump, relays and protection states.

* Local only, using the controller's own JSON service protocol ([protocol notes](docs/protocol.md)).
* Automatic discovery: Home Assistant offers the controller as soon as it sees it
  on the network; adding it takes one click.
* Installable with HACS or by copying one folder.

## Status

| Phase | |
|---|---|
| 0 — project scaffolding | in progress |
| 1 — protocol library (`pyngbsicon`) | planned |
| 2 — integration core, discovery, climate | planned |
| 3 — all entities, actions, diagnostics | planned |
| 4 — polishing on real installations | planned |
| 5 — documentation and first release | planned |

## License

This project is **source-available** under the [Business Source License 1.1](LICENSE):

* **Free for end users.** Anyone may use it, with all features, to monitor and control
  the heating/cooling system they own or operate — at home or in their business
  premises — and may modify it for that purpose.
* **Commercial distribution needs a license.** Offering it to third parties as part of
  a product or service — for example bundling it with controllers, thermostats,
  installation or support services — requires a separate commercial license from the
  author.
* Each version becomes open source under the Apache License 2.0 four years after its
  release.

## Disclaimer

This is an independent project. It is not made, endorsed or supported by NGBS
Hungary Kft. NGBS and iCON are trademarks of their respective owners. You are
responsible for how you operate your own heating and cooling system.
