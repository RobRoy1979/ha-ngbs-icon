"""Encoding, decoding and parsing of the JSON service protocol (no I/O here)."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any

from .const import SENSOR_FAULT
from .exceptions import IconProtocolError
from .models import (
    HeatCool,
    IconController,
    IconSystem,
    IconThermostat,
    Relay,
    RelayKind,
    Setpoints,
    Signal,
    SignalRef,
    SysidInfo,
)

# Some firmware versions emit numbers with leading zeros (``"X": 0000``), which is not
# valid JSON. An unescaped quote followed by a colon can only end an object key, so the
# substitution never touches string contents.
_LEADING_ZEROS_RE = re.compile(r'(?<!\\)"(\s*:\s*)(-?)0+(?=\d)')
_THERMOSTAT_ID_RE = re.compile(r"(\d+)\.(\d+)")
_DEFAULT_RELAY_NAME_RE = re.compile(r"R\d+\.(?:\d+|HEAT|COOL)")
_SWITCHED_OUTPUT_NAME_RE = re.compile(r"S\d+\.\d+")
_SECRET_KEYS = frozenset({"KEY"})


def encode(payload: Mapping[str, Any]) -> bytes:
    """Encode a request."""
    return json.dumps(payload, separators=(",", ":")).encode("ascii")


def decode(data: bytes) -> dict[str, Any]:
    """Decode an answer into a dictionary.

    Raises :class:`IconProtocolError` when the data is not a JSON object.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    text = _LEADING_ZEROS_RE.sub(r'"\1\2', text).strip()
    if not text:
        raise IconProtocolError("empty answer")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as err:
        raise IconProtocolError(
            f"answer is not valid JSON ({err}): {text[:80]!r}"
        ) from err
    if not isinstance(value, dict):
        raise IconProtocolError(f"answer is not a JSON object: {text[:80]!r}")
    return value


def is_auth_error(answer: Mapping[str, Any]) -> bool:
    """Tell whether an answer is the "wrong SYSID" error.

    ``ERR`` is also the collective fault flag of a normal state answer, so only an
    answer without any state (no ``SYSID``, no ``DP``) counts as the error.
    """
    return answer.get("ERR") == 1 and "SYSID" not in answer and "DP" not in answer


def redact(answer: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy without secrets (the web interface password ``KEY``)."""
    return {key: value for key, value in answer.items() if key not in _SECRET_KEYS}


def parse_sysid_info(answer: Mapping[str, Any]) -> SysidInfo:
    """Parse the answer to ``{"RELOAD": 6}``."""
    sysid = answer.get("SYSID")
    if not isinstance(sysid, str) or not sysid:
        raise IconProtocolError(f"no SYSID in the answer (keys: {sorted(answer)})")
    firmware: dict[int, int] = {}
    for key, value in answer.items():
        match = re.fullmatch(r"ICON(\d+)", key)
        if match and isinstance(value, Mapping):
            version = _int(value.get("FIRMWARE"))
            if version is not None:
                firmware[int(match[1])] = version
    return SysidInfo(
        sysid=sysid, firmware=firmware, download=_int(answer.get("DOWNLOAD"))
    )


def parse_state(
    answer: Mapping[str, Any], *, config: Mapping[str, Any] | None = None
) -> IconSystem:
    """Build the model from a state answer.

    ``config`` is the ``CFG`` object of an earlier ``RELOAD`` answer; it is used when
    ``answer`` itself carries no configuration (regular polls and write answers).
    Without any configuration the thermostats are still complete, but names of the
    building, relay states and the H/C and ECO masters are unknown.
    """
    sysid = answer.get("SYSID")
    if not isinstance(sysid, str) or "DP" not in answer:
        raise IconProtocolError(f"not a state answer (keys: {sorted(answer)})")
    cfg = answer.get("CFG")
    if not isinstance(cfg, Mapping):
        cfg = config if isinstance(config, Mapping) else None
    info = _mapping(answer.get("INFO"))
    netl = _mapping(info.get("NETL"))

    hc_master = SignalRef.parse(str(cfg.get("HCMASTER", ""))) if cfg else None
    eco_master = SignalRef.parse(str(cfg.get("CEMASTER", ""))) if cfg else None
    master_address = _int(cfg.get("ADDR")) if cfg else None
    master_address = master_address or 1

    thermostats = {
        key: _parse_thermostat(key, value, hc_master, eco_master)
        for key, value in _mapping(answer.get("DP")).items()
        if _THERMOSTAT_ID_RE.fullmatch(key) and isinstance(value, Mapping)
    }

    addresses = {th.controller for th in thermostats.values()}
    if cfg:
        addresses |= {
            int(match[1])
            for key in cfg
            if (match := re.fullmatch(r"ICON(\d+)", key))
            and isinstance(cfg[key], Mapping)
        }
    controllers = {
        address: _parse_controller(
            address,
            _mapping(cfg.get(f"ICON{address}")) if cfg else {},
            is_master=address == master_address,
            firmware=_int(info.get("FIRMWARE")) if address == master_address else None,
            pump_relay=str(cfg.get("PUMP", "")) if cfg else "",
        )
        for address in sorted(addresses)
    }

    return IconSystem(
        sysid=sysid,
        name=_str(cfg.get("NAME")) if cfg else None,
        firmware=_int(info.get("FIRMWARE")),
        config_version=_str(answer.get("VER")),
        timezone=_str(answer.get("TZ")),
        uptime=_int(info.get("UPTIME")),
        mac=(_str(netl.get("MAC")) or "").lower() or None,
        ip=_str(netl.get("eth0")),
        cloud_connected=any(str(name).startswith("tun") for name in netl),
        hc_mode=_hc(answer.get("HC")),
        eco=_flag(answer.get("CE")),
        regulation_on=_flag(answer.get("ON")),
        water_temp=_temperature(answer.get("WTEMP")),
        outdoor_temp=_temperature(answer.get("ETEMP")),
        pump=_flag(answer.get("PUMP")),
        fault=_flag(answer.get("ERR")),
        overheat=_flag(answer.get("OVERHEAT")),
        frost_warning=_flag(answer.get("WFROST")),
        signals=Signal(_int(answer.get("SIG")) or 0),
        switched_output=_flag(answer.get("SW")),
        default_setpoints=Setpoints(
            heat=_num(answer.get("XAH")),
            cool=_num(answer.get("XAC")),
            eco_heat=_num(answer.get("ECOH")),
            eco_cool=_num(answer.get("ECOC")),
        ),
        hc_master=hc_master,
        eco_master=eco_master,
        hysteresis=_num(cfg.get("THH")) if cfg else None,
        modbus_enabled=_flag(_mapping(cfg.get("MBTCP")).get("EN")) if cfg else None,
        controllers=controllers,
        thermostats=thermostats,
        has_config=cfg is not None,
        raw=redact(answer),
    )


def _parse_thermostat(
    key: str,
    data: Mapping[str, Any],
    hc_master: SignalRef | None,
    eco_master: SignalRef | None,
) -> IconThermostat:
    match = _THERMOSTAT_ID_RE.fullmatch(key)
    assert match is not None  # filtered by the caller
    configured = _flag(data.get("ON"))
    live = configured and _flag(data.get("LIVE"))

    def measured(name: str) -> float | None:
        return _temperature(data.get(name)) if live else None

    def setting(name: str) -> float | None:
        return _num(data.get(name)) if configured else None

    return IconThermostat(
        id=key,
        controller=int(match[1]),
        address=int(match[2]),
        name=_str(data.get("NAME")) or f"Thermostat {key}",
        configured=configured,
        live=live,
        temperature=measured("TEMP"),
        humidity=measured("RH"),
        dew_point=measured("DEW"),
        setpoints=Setpoints(
            heat=setting("XAH"),
            cool=setting("XAC"),
            eco_heat=setting("ECOH"),
            eco_cool=setting("ECOC"),
        ),
        eco=_flag(data.get("CE")),
        hc_mode=_hc(data.get("HC")),
        output_on=_flag(data.get("OUT")),
        dew_protection=_flag(data.get("DWP")),
        frost_protection=_flag(data.get("FROST")),
        locked=_flag(data.get("PL")),
        time_program=_flag(data.get("TPR")),
        limit=setting("LIM"),
        loop_b_offset_heat=setting("DXH"),
        loop_b_offset_cool=setting("DXC"),
        digital_input=_flag(data.get("DI")),
        eco_follows_master=_flag(data.get("CEF")),
        comfort_follows_master=_flag(data.get("CEC")),
        is_hc_master=hc_master is not None
        and hc_master.function.value == "H"
        and hc_master.thermostat_id == key,
        is_eco_master=eco_master is not None
        and eco_master.function.value == "E"
        and eco_master.thermostat_id == key,
        raw=dict(data),
    )


def _parse_controller(
    address: int,
    data: Mapping[str, Any],
    *,
    is_master: bool,
    firmware: int | None,
    pump_relay: str,
) -> IconController:
    status = _mapping(data.get("STATUS"))
    relays: dict[str, Relay] = {}
    for key, relay_data in _mapping(data.get("RELAY")).items():
        match = re.fullmatch(r"R(\d)", key)
        if match and isinstance(relay_data, Mapping):
            relay = _parse_relay(address, int(match[1]), relay_data, status, pump_relay)
            relays[relay.key] = relay
    battery = _int(status.get("BATT"))
    return IconController(
        address=address,
        is_master=is_master,
        firmware=firmware,
        water_temp=_temperature(status.get("WTEMP")),
        outdoor_temp=_temperature(status.get("ETEMP")),
        mixing_valve=_num(status.get("AO")),
        supply_voltage=_num(status.get("POWER")),
        thermostat_bus_voltage=_num(status.get("THPWR")),
        battery_ok=None if battery is None else battery == 0,
        relays=dict(sorted(relays.items(), key=lambda item: int(item[0][1:]))),
    )


def _parse_relay(
    controller: int,
    index: int,
    data: Mapping[str, Any],
    status: Mapping[str, Any],
    pump_relay: str,
) -> Relay:
    name = _str(data.get("FUNC")) or f"R{controller}.{index}"
    default_name = _DEFAULT_RELAY_NAME_RE.fullmatch(name) is not None
    if pump_relay == f"R{controller}.{index}":
        kind = RelayKind.PUMP
    elif name.endswith(".HEAT") and default_name:
        kind = RelayKind.HEATING_CHANGEOVER
    elif name.endswith(".COOL") and default_name:
        kind = RelayKind.COOLING_CHANGEOVER
    elif _SWITCHED_OUTPUT_NAME_RE.fullmatch(name):
        kind = RelayKind.SWITCHED_OUTPUT
    elif default_name:
        kind = RelayKind.VALVE
    else:
        kind = RelayKind.CUSTOM
    state = status.get(f"R{index}")
    driven_by = tuple(
        ref
        for item in data.get("OR") or ()
        if (ref := SignalRef.parse(str(item))) is not None
    )
    return Relay(
        controller=controller,
        index=index,
        name=name,
        kind=kind,
        custom_name=not default_name and kind is not RelayKind.SWITCHED_OUTPUT,
        on=None if state is None else _flag(state),
        heating=_flag(data.get("HEAT")),
        cooling=_flag(data.get("COOL")),
        inverted=_flag(data.get("NEG")),
        on_delay=_int(data.get("Ton")) or 0,
        off_delay=_int(data.get("Toff")) or 0,
        driven_by=driven_by,
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else int(number)


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _flag(value: Any) -> bool:
    return _num(value) == 1


def _temperature(value: Any) -> float | None:
    number = _num(value)
    return None if number is None or number == SENSOR_FAULT else number


def _hc(value: Any) -> HeatCool:
    return HeatCool.COOLING if _flag(value) else HeatCool.HEATING
