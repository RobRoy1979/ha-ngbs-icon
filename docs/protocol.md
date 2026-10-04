# NGBS iCON local protocol

This document describes how an NGBS iCON heating/cooling controller can be read and
controlled over the local network, as implemented by
[`pyngbsicon`](../lib/pyngbsicon) and the Home Assistant integration in this
repository. It is based on the manufacturer's public documentation, on earlier
community work (credited at the end) and on measurements against a real controller
(iCON-1, firmware 1079). Fields marked *unconfirmed* have not been verified yet.

Example values below come from the anonymised fixtures in
[`tests/fixtures`](../tests/fixtures).

## 1. The system

* An **iCON controller** (iCON-1, newer units iCON-2; the hardware is built by
  Bucher Automation Budapest) drives up to **8 room thermostats** (iCON 100 / iCON 200)
  over RS-485 and switches the valve actuators of a surface heating/cooling system.
* Up to **7 slave controllers** can be chained to a **master** controller over RS-485,
  for at most 64 thermostats. Only the master is on the Ethernet network; it answers for
  the whole system.
* A system is identified by its **SYSID**, a 12-digit serial number printed on the
  controller and on the *iCON PASS* card shipped with it. The SYSID is also the default
  user name and password of the controller's web interface — treat it as a secret.
* Thermostats are addressed as `"<controller>.<address>"`, e.g. `"1.3"` is thermostat 3
  of controller 1 (the master). Thermostat `1.1` is the system's master thermostat.
* The whole system is either in **heating** or in **cooling** mode. Switching is done on
  the H/C master thermostat (`CFG.HCMASTER`, normally `1.1`) or by an external contact /
  building management system; the other thermostats follow.
* Every thermostat has **four setpoints**: heating, cooling, ECO heating and ECO
  cooling. Which one is active depends on the heating/cooling mode and on the
  comfort/ECO state.
* The controller works fully without internet. When connected, it keeps a VPN tunnel
  to the manufacturer's server, which the NGBS web portal and app use.

## 2. Network services

| Port | Service | Use |
|---|---|---|
| TCP 7992 | **JSON service protocol** | Complete state, configuration and control. Used by this project. |
| TCP 502 | Modbus-TCP (if enabled in the configuration) | Subset of the state; see the appendix. |
| TCP 80 | Web interface (login with SYSID and password) | Not used. Its `tab=datapoll` request returns the same JSON as port 7992. |

The controller does not announce itself via mDNS/Zeroconf or SSDP and has no reverse
DNS entry. It obtains its address by DHCP by default.

### MAC address ranges

The controllers seen so far use these OUI-36 / IAB blocks (registered to Bucher
Automation Budapest) and an IEEE MA-S block:

| Prefix | Notes |
|---|---|
| `E4:95:6E:5x:xx:xx` | current units |
| `00:50:C2:FD:Ax:xx`, `00:50:C2:F2:7x:xx`, `00:50:C2:DE:7x:xx` | IAB blocks, older units |
| `40:D8:55:0D:2x:xx` | IAB block |
| `66:55:44:00:0x:xx` | locally administered, very old units |

Home Assistant matches these in its DHCP discovery (`manifest.json` → `dhcp`).

## 3. JSON service protocol (TCP 7992)

### 3.1 Framing

* **One request per TCP connection.** Connect, send one JSON object (no length prefix
  or delimiter is needed — the controller parses the object as it arrives), read the
  answer until the controller closes the connection. The answer is a single JSON object
  followed by `\n`. A second request on the same connection is answered with a reset.
* The controller accepts several connections at once but serves them one after the
  other. Clients should serialise their own requests.
* Typical timing (firmware 1079, one controller): full state with configuration
  ~3.9 kB in 26–30 ms, state without configuration ~2.4 kB in ~40 ms, a write and its
  answer ~60 ms.
* An unknown or wrong SYSID is answered with `{"ERR":1}`.

### 3.2 Requests

| Request | Answer | Notes |
|---|---|---|
| `{"RELOAD": 6}` | `{"SYSID": "123456789012", "DOWNLOAD": 0, "ICON1": {"VER:": "606231543", "FIRMWARE": 1079}}` | **SYSID discovery**, works without a SYSID on firmware ≥ 1079 (January 2023). Older firmware answers `{"ERR":1}` and the SYSID has to be entered by the user. Note the key `"VER:"` with a trailing colon. Slave controllers are expected to appear as `ICON2`… (*unconfirmed*). |
| `{"SYSID": s}` | full state without configuration | regular polling |
| `{"SYSID": s, "RELOAD": ""}` (or `"RELOAD": 3`) | full state **plus** `KEY`, `CFG`, `EVENTLOG` | names, relay matrix, H/C master, Modbus settings |
| `{"SYSID": s, "DP": {"1.3": {"XAH": 21.5}}}` | full state without configuration, after the change | write thermostat fields; several thermostats and fields may be combined in one request |
| `{"SYSID": s, "CE": 1}` | state | system-wide ECO on/off |
| `{"SYSID": s, "HC": 1}` | state | system-wide heating (0) / cooling (1). The answer already shows the new mode, but the controller switches its relays with a delay (3–10 minutes by default). Without effect when switching is done by an external contact. |
| `{"SYSID": s, "SW": 1}` | state | switched output ("TAP"), if a relay is configured for it (*unconfirmed*) |
| `{"SYSID": s, "RELOAD": 8}` | — | restart the controller software |
| `{"SYSID": s, "RELOAD": 7}` | — | start a firmware update from the network (not used) |

Writable thermostat fields: `XAH`, `XAC`, `ECOH`, `ECOC` (the four setpoints, °C, 0.5
steps), `SP` (the currently active setpoint — the controller decides which of the four),
`CE`, `HC` (only on thermostats that may switch), `PL` (keypad lock), `LIM`, `DXH`,
`DXC`. The integration writes the explicit setpoint field rather than `SP`, so the
result does not depend on a mode change racing the write.

### 3.3 State fields

#### System (top level)

| Field | Meaning |
|---|---|
| `SYSID` | system ID |
| `KEY` | web interface password (default: the SYSID). Only with `RELOAD`. **Never log it.** |
| `SERVICE` | 1 = service protocol active |
| `VER` | configuration version, `YYYYMMDDhhmmss` |
| `HC` | 0 heating, 1 cooling |
| `CE` | 0 comfort, 1 ECO (system / master state) |
| `ON` | 1 = regulation enabled |
| `ETEMP` | outdoor temperature, °C; **222 means no sensor / sensor fault** |
| `WTEMP` | flow water temperature, °C; 222 = fault |
| `PUMP` | circulation pump running (0/1) |
| `ERR` | collective fault input / system error (0/1) |
| `OVERHEAT` | overheat protection active (0/1) |
| `WFROST` | frost danger (0/1) |
| `XAH`, `XAC`, `ECOH`, `ECOC` | system default setpoints, inherited by new thermostats (not the active setpoints) |
| `SIG` | signal bits, same as the Modbus `Signal` register (see appendix) |
| `SW` | switched output state |
| `EMAIL` | notification address |
| `TZ` | IANA time zone |
| `INFO.FIRMWARE` | firmware version, e.g. 1079 |
| `INFO.UPTIME` | seconds since start |
| `INFO.TASK` | running tasks, e.g. `["reg", "wdr"]` |
| `INFO.NETL` | `MAC`, interface addresses (`eth0`, `eth0:1`, `tun0`; `tun0` present = cloud tunnel up) |

#### Thermostat (`DP["<controller>.<address>"]`)

| Field | Meaning |
|---|---|
| `ON` | 1 = configured/installed. Unconfigured slots are present with `ON: 0`. |
| `LIVE` | 1 = communicating |
| `NAME` | room name (default `Room 1.3`) |
| `TEMP`, `RH`, `DEW` | temperature °C, relative humidity %, dew point °C |
| `XAH`, `XAC`, `ECOH`, `ECOC` | heating, cooling, ECO heating, ECO cooling setpoint |
| `CE`, `HC` | the thermostat's ECO and heating/cooling state |
| `OUT` | 1 = demand / valve output on |
| `DWP` | dew point protection active (cooling blocked) |
| `FROST` | frost protection active |
| `PL` | keypad (child) lock |
| `TPR` | time program active |
| `LIM` | ± adjustment limit on the thermostat, °C |
| `DXH`, `DXC` | floor heating / cooling offset, °C |
| `DI` | digital input (window contact, if wired) |
| `IHC` | individual heating/cooling switching: 0 heat, 1 cool, 2 follow the system (observed: 2) |
| `CEF` | ECO follows the master |
| `CEC`, `WP`, `MV` | *unconfirmed* (observed: 1) |

#### Configuration (`CFG`, only with `RELOAD`)

| Field | Meaning |
|---|---|
| `NAME` | building / system name |
| `NET` | `DHCP`, `IP`, `MASK`, `GW`, `DNS1`, `SERVER` (cloud server), `REGION` |
| `ADDR` | address of this controller (the master is 1) |
| `ICONS` | number of controllers in the system |
| `PUMP` | relay used for the pump, e.g. `R1.8` |
| `OVSTOP`, `FROST`, `THH`, `HCT`, `TBOILER` | overheat limit, frost limit, thermostat hysteresis, H/C switching parameters |
| `HCMASTER` | H/C master: `H1.1` = thermostat 1.1; other forms = external switching |
| `CEMASTER` | ECO master, e.g. `E1.1` |
| `BACNET`, `MBTCP` | BACnet and Modbus-TCP settings (`EN`, `PORT`, `TOUT`) |
| `ICON<n>` | per controller: `WATER` (flow temperature curve), `COND` (condensation control), `DHU` (dehumidifier), `WEATHER`, `RELAY`, `STATUS` |
| `ICON<n>.RELAY.R0…R9` | relay matrix: `FUNC` (name, e.g. `R1.HEAT`, `R1.COOL`, `R1.3`, `S1.8`), `Ton`/`Toff`, `NEG`, `HEAT`/`COOL` participation, `OR` (thermostats `A1.x` or inputs `I1.x` that switch it on) |
| `ICON<n>.STATUS` | `WTEMP`, `ETEMP`, `HC`, `CE`, `ON` (digital inputs), `POWER` (supply V), `THPWR` (thermostat bus V), `AO` (mixing valve %), `R0…R9` (**physical** relay states) |

In the factory configuration `R0` is the heating changeover relay (`R<c>.HEAT`), `R9`
the cooling changeover relay (`R<c>.COOL`) and `R1…R8` the valve outputs, relay *n*
following thermostat *n* (`R<c>.<n>`). Installers may change this freely in the
relay matrix, so always read the role from `FUNC`.

`TPR` holds the weekly time programs (`HEAT` / `COOL` → per thermostat `{"EN": 0/1, …}`),
`EVENTLOG` the controller's event log (`LEVEL`, `LOG`).

### 3.4 Known quirks

* `222` (JSON) / `2220` (Modbus) is a sensor fault value, not a temperature.
* The `"VER:"` key in the discovery answer has a trailing colon.
* Some older firmware versions emit numbers such as `0000`, which is invalid JSON; a
  parser should normalise them before decoding.
* After a heating/cooling switch the relays change minutes later; valve outputs
  (`OUT`) follow setpoint changes only when the room temperature crosses the
  hysteresis.
* Changed settings are written to EEPROM 3–5 minutes after the last change.

## 4. Discovery

1. **DHCP:** Home Assistant watches DHCP and ARP traffic and matches the MAC ranges
   above; the integration then asks the address for its SYSID with `{"RELOAD": 6}`.
   A known system whose address changed is updated automatically.
2. **Active scan:** connect to TCP 7992 on every address of the local IPv4 networks
   (short timeout, limited concurrency) and send `{"RELOAD": 6}`. A JSON answer with a
   `SYSID` is an iCON controller; `{"ERR":1}` is an iCON with old firmware that needs
   the SYSID entered manually; anything else is ignored.
3. **Manual:** host name or address, optionally the SYSID.

## Appendix A: Modbus-TCP (TCP 502)

Not used by the integration (a possible fallback), documented for completeness.
Measured behaviour: the controller **closes every Modbus-TCP connection about 35
seconds after it was opened**, even while it is in use; function codes 3 (read) and
16 (write); at most **125** registers per read; unit IDs 0 and 1 both answer. Values
match the JSON protocol.

Register blocks: master `0x0100`, slaves `0x0200`…`0x0800` (offsets below are added to
the block base); extended functions `0x2000` (master), `0x2100`… (absolute).

| Offset | Content |
|---|---|
| `0x00`–`0x0F` | status bit registers (bit *n* = thermostat *n*+1): regA, regB, Cond, Drying, ECO, Frost, HC, Window, NoConn, Lock, Relay, Di, Signal, Tpr, Live, Forced |
| `0x10` | mixing valve output (×100 mV) |
| `0x11`–`0x18` | water temperature, outdoor temperature (×0.1 °C, 2220 = fault), analogue inputs, supply voltages (mV) |
| `0x19`–`0x20` | thermostat temperatures (×0.1 °C) |
| `0x21`–`0x28` | relative humidity (×0.1 %) |
| `0x29`–`0x30` | dew points (×0.1 °C) |
| `0x31`–`0x50` | active setpoints, four per thermostat (heat, cool, ECO heat, ECO cool) |
| `0x51` | H/C mode (0 heat, 1 cool, >1 switching) |
| `0x52`–`0x57` | effective outdoor temperature, mixing setpoint, firmware version, configuration version, effective outputs |
| `0x62` | system H/C command (master) |
| `0x63`–`0x82` | per-thermostat ECO, lock, time program, fan-coil commands |
| `0x83`–`0xA2` | setpoint write registers, four per thermostat (5.0–35.0 °C) |
| `0xB0`–`0xFF` | BMS extensions; `0xF0`–`0xF9` read back the physical relay states R0–R9 |
| `0x2000`, `0x2001` | cycle counter; status flags (bit 0 = master) |

Signal bits (`SIG` / register `0x0C`): 1 internal, 2 overheat, 4 frost danger,
8 outdoor sensor fault, 16 water sensor fault, 32 mixing valve opening, 64 BMS fault,
128 heating energy sensor missing, 256 switched output active.

## Credits

* [molnarg/ngbs-icon](https://github.com/molnarg/ngbs-icon) (MIT) first documented the
  JSON service protocol, the SYSID discovery and the MAC ranges.
* [csutorasa/icon-metrics](https://github.com/csutorasa/icon-metrics) (MIT) documented
  the web interface's data poll.
* The NGBS *iCON automatika* system description and the iCON Modbus register
  documentation published by NGBS Hungary Kft.

NGBS and iCON are trademarks of their respective owners. This project is independent
and not affiliated with or endorsed by NGBS Hungary Kft.
