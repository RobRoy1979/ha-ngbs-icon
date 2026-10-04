"""Immutable data model of an iCON system.

All classes are frozen dataclasses that compare by value, so a consumer can cheaply
tell whether anything changed between two polls. The unparsed controller data is
kept in ``raw`` (excluded from comparison) for diagnostics and fields this library
does not model yet; the web interface password (``KEY``) is never kept.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum, IntFlag, StrEnum
import re
from typing import Any


class HeatCool(IntEnum):
    """Heating or cooling mode (``HC``)."""

    HEATING = 0
    COOLING = 1


class SetpointKind(StrEnum):
    """The four setpoints of a thermostat."""

    HEAT = "heat"
    COOL = "cool"
    ECO_HEAT = "eco_heat"
    ECO_COOL = "eco_cool"

    @property
    def field(self) -> str:
        """Protocol field name of the setpoint."""
        return _SETPOINT_FIELDS[self]

    @classmethod
    def active(cls, hc_mode: HeatCool, eco: bool) -> SetpointKind:
        """Return the setpoint that is in effect for a mode and ECO state."""
        if hc_mode is HeatCool.COOLING:
            return cls.ECO_COOL if eco else cls.COOL
        return cls.ECO_HEAT if eco else cls.HEAT


_SETPOINT_FIELDS = {
    SetpointKind.HEAT: "XAH",
    SetpointKind.COOL: "XAC",
    SetpointKind.ECO_HEAT: "ECOH",
    SetpointKind.ECO_COOL: "ECOC",
}


class Signal(IntFlag):
    """System signal bits (``SIG``)."""

    INTERNAL = 1
    OVERHEAT = 2
    FROST_DANGER = 4
    OUTDOOR_SENSOR_FAULT = 8
    WATER_SENSOR_FAULT = 16
    MIXING_VALVE_OPENING = 32
    BMS_FAULT = 64
    ENERGY_SENSOR_MISSING = 128
    SWITCHED_OUTPUT = 256


class SignalFunction(StrEnum):
    """Source type of a signal reference such as ``A1.3`` (see :class:`SignalRef`)."""

    LOOP_A = "A"
    """Thermostat demand, A loop."""
    LOOP_B = "B"
    """Thermostat demand, B loop (sequenced second output)."""
    CONDENSATION = "C"
    DRYING = "D"
    ECO = "E"
    """Thermostat ECO button."""
    HEAT_COOL = "H"
    """Thermostat heating/cooling button."""
    INPUT = "I"
    """Controller input."""
    CONNECTED = "N"
    """Thermostat connection state."""
    RELAY = "R"
    SIGNAL = "S"
    DIGITAL_INPUT = "W"
    """Thermostat digital input (e.g. a window contact)."""


_THERMOSTAT_FUNCTIONS = frozenset(
    {
        SignalFunction.LOOP_A,
        SignalFunction.LOOP_B,
        SignalFunction.CONDENSATION,
        SignalFunction.DRYING,
        SignalFunction.ECO,
        SignalFunction.HEAT_COOL,
        SignalFunction.CONNECTED,
        SignalFunction.DIGITAL_INPUT,
    }
)
_SIGNAL_REF_RE = re.compile(r"([A-Z])(\d+)\.(\d+)")


@dataclass(frozen=True, slots=True)
class SignalRef:
    """A reference to a signal: ``<function><controller>.<index>``, e.g. ``A1.3``.

    Used by the relay matrix (which signals switch a relay on) and by the H/C and ECO
    master settings. ``A1.3`` is the A-loop demand of thermostat 1.3, ``H1.1`` the
    heating/cooling button of thermostat 1.1 and ``I1.5`` input 5 of controller 1.
    """

    function: SignalFunction
    controller: int
    index: int

    @classmethod
    def parse(cls, text: str) -> SignalRef | None:
        """Parse a reference; ``None`` when it is empty or not understood."""
        match = _SIGNAL_REF_RE.fullmatch(text.strip())
        if match is None:
            return None
        try:
            function = SignalFunction(match[1])
        except ValueError:
            return None
        return cls(function, int(match[2]), int(match[3]))

    @property
    def thermostat_id(self) -> str | None:
        """The thermostat the signal belongs to, if it is a thermostat signal."""
        if self.function in _THERMOSTAT_FUNCTIONS:
            return f"{self.controller}.{self.index}"
        return None

    def __str__(self) -> str:
        """Return the reference in protocol notation."""
        return f"{self.function.value}{self.controller}.{self.index}"


class RelayKind(StrEnum):
    """Role of a relay output, derived from its name and the system configuration."""

    HEATING_CHANGEOVER = "heating_changeover"
    COOLING_CHANGEOVER = "cooling_changeover"
    VALVE = "valve"
    PUMP = "pump"
    SWITCHED_OUTPUT = "switched_output"
    CUSTOM = "custom"
    """Renamed by the installer; the role is not known."""


@dataclass(frozen=True, slots=True)
class Setpoints:
    """The four setpoints of a thermostat (°C)."""

    heat: float | None
    cool: float | None
    eco_heat: float | None
    eco_cool: float | None

    def get(self, kind: SetpointKind) -> float | None:
        """Return one setpoint."""
        return {
            SetpointKind.HEAT: self.heat,
            SetpointKind.COOL: self.cool,
            SetpointKind.ECO_HEAT: self.eco_heat,
            SetpointKind.ECO_COOL: self.eco_cool,
        }[kind]


@dataclass(frozen=True, slots=True)
class Relay:
    """One relay output of a controller (``CFG.ICON<n>.RELAY.R<k>``)."""

    controller: int
    index: int
    """0-9; in the factory configuration 0 is the heating changeover output, 9 the
    cooling one and 1-8 the valve outputs - see ``kind`` for the actual role."""
    name: str
    """The name configured in the controller (``FUNC``), e.g. ``R1.3`` or ``R1.HEAT``."""
    kind: RelayKind
    custom_name: bool
    """``True`` when the installer renamed the relay; ``name`` is then meaningful."""
    on: bool | None
    """Physical output state; ``None`` when the configuration was not read."""
    heating: bool
    """The relay takes part in heating."""
    cooling: bool
    """The relay takes part in cooling."""
    inverted: bool
    on_delay: int
    """Seconds."""
    off_delay: int
    """Seconds."""
    driven_by: tuple[SignalRef, ...]
    """Signals that switch the relay on (OR-ed)."""

    @property
    def key(self) -> str:
        """Protocol key of the relay, e.g. ``R3``."""
        return f"R{self.index}"

    @property
    def thermostat_ids(self) -> tuple[str, ...]:
        """Thermostats whose demand switches this relay."""
        return tuple(
            ref.thermostat_id
            for ref in self.driven_by
            if ref.thermostat_id is not None
            and ref.function in {SignalFunction.LOOP_A, SignalFunction.LOOP_B}
        )


@dataclass(frozen=True, slots=True)
class IconController:
    """One iCON controller of the system (the master or a slave)."""

    address: int
    is_master: bool
    firmware: int | None
    """Only known for the master from the state; slaves report it to SYSID discovery."""
    water_temp: float | None
    outdoor_temp: float | None
    mixing_valve: float | None
    """Mixing valve output, %."""
    supply_voltage: float | None
    """V."""
    thermostat_bus_voltage: float | None
    """V."""
    battery_ok: bool | None
    relays: Mapping[str, Relay]
    """By protocol key (``R0`` ... ``R9``); empty when the configuration was not read."""


@dataclass(frozen=True, slots=True)
class IconThermostat:
    """One room thermostat (``DP["<controller>.<address>"]``)."""

    id: str
    controller: int
    address: int
    name: str
    configured: bool
    """Installed in the controller's configuration (``ON``)."""
    live: bool
    """Communicating with the controller (``LIVE``)."""
    temperature: float | None
    humidity: float | None
    dew_point: float | None
    setpoints: Setpoints
    eco: bool
    hc_mode: HeatCool
    output_on: bool
    """Demand: the thermostat's valve output is on (``OUT``)."""
    dew_protection: bool
    """Condensation protection is blocking cooling (``DWP``)."""
    frost_protection: bool
    locked: bool
    """Keypad (child) lock (``PL``)."""
    time_program: bool
    """A weekly time program is active (``TPR``)."""
    limit: float | None
    """± adjustment range allowed on the thermostat itself, °C (``LIM``)."""
    loop_b_offset_heat: float | None
    """Offset of the sequenced B-loop output in heating, °C (``DXH``)."""
    loop_b_offset_cool: float | None
    """Offset of the sequenced B-loop output in cooling, °C (``DXC``)."""
    digital_input: bool
    """The thermostat's digital input (e.g. a window contact) is active (``DI``)."""
    eco_follows_master: bool
    """Switches to ECO when the ECO master does (``CEF``)."""
    comfort_follows_master: bool
    """Switches back to comfort when the ECO master does (``CEC``)."""
    is_hc_master: bool
    """This thermostat switches the system between heating and cooling."""
    is_eco_master: bool
    """This thermostat's ECO button switches the system's ECO state."""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def available(self) -> bool:
        """Configured and communicating."""
        return self.configured and self.live

    @property
    def active_setpoint_kind(self) -> SetpointKind:
        """The setpoint currently in effect."""
        return SetpointKind.active(self.hc_mode, self.eco)

    @property
    def active_setpoint(self) -> float | None:
        """The value of the setpoint currently in effect, °C."""
        return self.setpoints.get(self.active_setpoint_kind)


@dataclass(frozen=True, slots=True)
class IconSystem:
    """A complete iCON system: a master controller, its slaves and their thermostats."""

    sysid: str
    name: str | None
    """Building name (``CFG.NAME``); ``None`` when the configuration was not read."""
    firmware: int | None
    config_version: str | None
    timezone: str | None
    uptime: int | None
    """Seconds since the controller software started."""
    mac: str | None
    ip: str | None
    cloud_connected: bool
    """The VPN tunnel to the manufacturer's server is up."""
    hc_mode: HeatCool
    eco: bool
    regulation_on: bool
    water_temp: float | None
    outdoor_temp: float | None
    pump: bool
    fault: bool
    """Collective fault input / system error (``ERR``)."""
    overheat: bool
    frost_warning: bool
    signals: Signal
    switched_output: bool
    default_setpoints: Setpoints
    """Defaults for new thermostats (read-only through this protocol)."""
    hc_master: SignalRef | None
    """What switches heating/cooling; ``None`` when the configuration was not read."""
    eco_master: SignalRef | None
    hysteresis: float | None
    """Thermostat hysteresis, °C (``CFG.THH``)."""
    modbus_enabled: bool | None
    controllers: Mapping[int, IconController]
    thermostats: Mapping[str, IconThermostat]
    """Every thermostat slot, configured or not; see :attr:`configured_thermostats`."""
    has_config: bool
    """The configuration (names, relays, masters) was read."""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def configured_thermostats(self) -> dict[str, IconThermostat]:
        """Thermostats installed in the configuration."""
        return {key: th for key, th in self.thermostats.items() if th.configured}

    @property
    def hc_master_thermostat(self) -> str | None:
        """The thermostat that switches heating/cooling, or ``None`` when an input does."""
        return _master_thermostat(self.hc_master, "H")

    @property
    def eco_master_thermostat(self) -> str | None:
        """The thermostat that switches the system ECO state, if any."""
        return _master_thermostat(self.eco_master, "E")

    @property
    def master(self) -> IconController | None:
        """The master controller."""
        return next((c for c in self.controllers.values() if c.is_master), None)


def _master_thermostat(ref: SignalRef | None, function: str) -> str | None:
    if ref is None or ref.function.value != function:
        return None
    return ref.thermostat_id


@dataclass(frozen=True, slots=True)
class SysidInfo:
    """Answer to SYSID discovery (``{"RELOAD": 6}``)."""

    sysid: str
    firmware: Mapping[int, int]
    """Firmware version by controller address."""
    download: int | None
    """``DOWNLOAD`` field; meaning not confirmed (firmware download state)."""


@dataclass(frozen=True, slots=True)
class DiscoveredIcon:
    """A controller found on the network."""

    host: str
    sysid: str | None
    """``None`` when the firmware is too old to reveal it (``needs_sysid``)."""
    firmware: int | None
    controllers: int
    needs_sysid: bool
