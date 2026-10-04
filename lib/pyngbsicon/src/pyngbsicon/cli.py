"""Command line tool: ``pyngbsicon scan | status | set | eco | lock | mode | raw | restart``."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
import dataclasses
from enum import Enum
import ipaddress
import json
import logging
import socket
import sys
from typing import Any

from . import __version__
from .client import IconClient
from .const import DEFAULT_PORT, DEFAULT_TIMEOUT
from .discovery import discover
from .exceptions import IconError
from .models import HeatCool, IconSystem, SignalRef
from .protocol import redact


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line tool; returns the process exit code."""
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return int(asyncio.run(args.handler(args)))
    except IconError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except (ValueError, TypeError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyngbsicon", description="Talk to NGBS iCON heating/cooling controllers."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument("--debug", action="store_true", help="log every request")
    commands = parser.add_subparsers(required=True, metavar="COMMAND")

    def command(
        name: str, handler: Any, help_text: str, host: bool = True
    ) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text, description=help_text)
        sub.set_defaults(handler=handler)
        if host:
            sub.add_argument("host", help="controller address")
            sub.add_argument("--sysid", help="system ID (discovered when omitted)")
            sub.add_argument("--port", type=int, default=DEFAULT_PORT)
            sub.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
        return sub

    scan = command("scan", _scan, "find controllers on the local network", host=False)
    scan.add_argument(
        "networks",
        nargs="*",
        help="networks to scan, e.g. 192.0.2.0/24 (default: the local /24)",
    )
    scan.add_argument("--port", type=int, default=DEFAULT_PORT)
    scan.add_argument("--json", action="store_true", help="print JSON")

    status = command("status", _status, "show the complete state")
    status.add_argument("--json", action="store_true", help="print JSON")

    setpoint = command("set", _set, "change setpoints of a thermostat")
    setpoint.add_argument("thermostat", help="thermostat id, e.g. 1.3")
    for flag in ("heat", "cool", "eco-heat", "eco-cool"):
        setpoint.add_argument(f"--{flag}", type=float, metavar="°C")
    setpoint.add_argument(
        "--no-confirm", action="store_true", help="do not wait for the thermostat"
    )

    eco = command("eco", _eco, "switch ECO mode (system, or one thermostat)")
    eco.add_argument("state", choices=["on", "off"])
    eco.add_argument("--thermostat", help="only this thermostat")

    lock = command("lock", _lock, "lock or unlock a thermostat's keypad")
    lock.add_argument("thermostat")
    lock.add_argument("state", choices=["on", "off"])

    mode = command("mode", _mode, "switch the system between heating and cooling")
    mode.add_argument("mode", choices=["heating", "cooling"])

    raw = command(
        "raw", _raw, "send a raw JSON request (SYSID is added; KEY is hidden)"
    )
    raw.add_argument("payload", help='e.g. \'{"RELOAD": ""}\'')

    restart = command("restart", _restart, "restart the controller software")
    restart.add_argument("--yes", action="store_true", help="really restart")
    return parser


def _client(args: argparse.Namespace) -> IconClient:
    return IconClient(args.host, args.sysid, port=args.port, timeout=args.timeout)


async def _scan(args: argparse.Namespace) -> int:
    networks = args.networks or [_local_network()]
    found = await discover(networks, port=args.port)
    if args.json:
        print(json.dumps([_jsonable(item) for item in found], indent=2))
    elif not found:
        print(f"No iCON controller found in {', '.join(map(str, networks))}.")
    for item in [] if args.json else found:
        detail = (
            "firmware too old to reveal the SYSID"
            if item.needs_sysid
            else (
                f"SYSID {item.sysid}, firmware {item.firmware}, {item.controllers} controller(s)"
            )
        )
        print(f"{item.host}  {detail}")
    return 0


async def _status(args: argparse.Namespace) -> int:
    state = await _client(args).get_state()
    print(
        json.dumps(_jsonable(state), indent=2, ensure_ascii=False)
        if args.json
        else _describe(state)
    )
    return 0


async def _set(args: argparse.Namespace) -> int:
    state = await _client(args).set_setpoints(
        args.thermostat,
        heat=args.heat,
        cool=args.cool,
        eco_heat=args.eco_heat,
        eco_cool=args.eco_cool,
        confirm=not args.no_confirm,
    )
    print(_describe_thermostat(state, args.thermostat))
    return 0


async def _eco(args: argparse.Namespace) -> int:
    state = await _client(args).set_eco(args.state == "on", args.thermostat)
    print(
        _describe_thermostat(state, args.thermostat)
        if args.thermostat
        else _describe(state)
    )
    return 0


async def _lock(args: argparse.Namespace) -> int:
    state = await _client(args).set_lock(args.thermostat, args.state == "on")
    print(_describe_thermostat(state, args.thermostat))
    return 0


async def _mode(args: argparse.Namespace) -> int:
    mode = HeatCool.COOLING if args.mode == "cooling" else HeatCool.HEATING
    print(_describe(await _client(args).set_hc_mode(mode)))
    return 0


async def _raw(args: argparse.Namespace) -> int:
    payload = json.loads(args.payload)
    if not isinstance(payload, dict):
        raise TypeError("the payload must be a JSON object")
    client = _client(args)
    if "SYSID" not in payload and payload.get("RELOAD") != 6:
        if client.sysid is None:
            await client.discover_sysid()
        payload = {"SYSID": client.sysid, **payload}
    answer = await client.raw_request(payload)
    print(json.dumps(redact(answer), indent=2, ensure_ascii=False))
    return 0


async def _restart(args: argparse.Namespace) -> int:
    if not args.yes:
        print("This restarts the controller software. Repeat with --yes to do it.")
        return 2
    await _client(args).restart()
    print("Restart requested.")
    return 0


def _local_network() -> ipaddress.IPv4Network:
    """Return the /24 of the address used to reach other hosts (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 9))
        address = sock.getsockname()[0]
    return ipaddress.IPv4Network(f"{address}/24", strict=False)


def _fmt(value: float | None, unit: str = "", digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}{unit}"


def _describe(state: IconSystem) -> str:
    lines = [
        (
            f"{state.name or 'iCON system'} — SYSID {state.sysid}, firmware {state.firmware}, "
            f"{state.hc_mode.name.lower()}, ECO {'on' if state.eco else 'off'}"
        ),
        (
            f"  water {_fmt(state.water_temp, ' °C')}, outdoor {_fmt(state.outdoor_temp, ' °C')}, "
            f"pump {'on' if state.pump else 'off'}, "
            f"cloud {'connected' if state.cloud_connected else 'not connected'}"
        ),
    ]
    problems = [
        name
        for name, active in (
            ("FAULT", state.fault),
            ("OVERHEAT", state.overheat),
            ("FROST", state.frost_warning),
        )
        if active
    ]
    if problems:
        lines.append("  ! " + ", ".join(problems))
    if state.has_config:
        lines.append(
            f"  heating/cooling switched by {state.hc_master_thermostat or state.hc_master or 'unknown'}, "
            f"ECO by {state.eco_master_thermostat or state.eco_master or 'unknown'}"
        )
    lines.append("Thermostats:")
    lines.extend(
        "  " + _describe_thermostat(state, key) for key in state.configured_thermostats
    )
    for controller in state.controllers.values():
        if not controller.relays:
            continue
        role = "master" if controller.is_master else "slave"
        lines.append(
            f"Controller {controller.address} ({role}): mixing valve {_fmt(controller.mixing_valve, ' %', 0)}, "
            f"supply {_fmt(controller.supply_voltage, ' V', 2)}"
        )
        lines.extend(
            f"  {relay.key} {relay.name:<10} {relay.kind.value:<19} {'ON' if relay.on else 'off'}"
            for relay in controller.relays.values()
        )
    return "\n".join(lines)


def _describe_thermostat(state: IconSystem, key: str) -> str:
    th = state.thermostats[key]
    if not th.live:
        return f"{th.id} {th.name:<14} offline"
    flags = [
        label
        for label, active in (
            ("ECO", th.eco),
            ("demand", th.output_on),
            ("locked", th.locked),
            ("condensation", th.dew_protection),
            ("frost", th.frost_protection),
            ("H/C master", th.is_hc_master),
        )
        if active
    ]
    return (
        f"{th.id} {th.name:<14} {_fmt(th.temperature, ' °C'):>8} {_fmt(th.humidity, ' %'):>7} "
        f"dew {_fmt(th.dew_point, ' °C'):>7}  setpoint {_fmt(th.active_setpoint, ' °C')} "
        f"({th.active_setpoint_kind.value})  "
        f"[heat {_fmt(th.setpoints.heat)} cool {_fmt(th.setpoints.cool)} "
        f"eco {_fmt(th.setpoints.eco_heat)}/{_fmt(th.setpoints.eco_cool)}]"
        + (f"  {' '.join(flags)}" if flags else "")
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, SignalRef):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _jsonable(getattr(value, item.name))
            for item in dataclasses.fields(value)
            if item.name != "raw"
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
