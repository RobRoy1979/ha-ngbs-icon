# Test fixtures

Responses of a real NGBS iCON controller (iCON-1, firmware 1079, one controller with
five live thermostats, cooling + ECO mode, no outdoor sensor), recorded with
`scripts/record_fixtures.py` and anonymised: the SYSID/KEY is `123456789012`, the MAC
address `02:00:00:00:00:01`, IP addresses come from the documentation ranges
(RFC 5737), the e-mail address is empty and room names are generic. Apart from that
the text is byte-for-byte what the controller sent, including its formatting quirks.

| File | Request |
|---|---|
| `sysid.json` | `{"RELOAD": 6}` — SYSID discovery, no SYSID needed (firmware ≥ 1079) |
| `state_poll.json` | `{"SYSID": "…"}` — regular poll, without configuration |
| `state_full.json` | `{"SYSID": "…", "RELOAD": ""}` — state plus `KEY`, `CFG`, `EVENTLOG` |
| `error.json` | any request with a wrong SYSID |

The unredacted originals are written to `raw/`, which is git-ignored.
