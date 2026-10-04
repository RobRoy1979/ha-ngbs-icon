"""Parsing state answers into the model."""

from __future__ import annotations

import copy
from typing import Any

from icon_test_support import load
import pytest

from pyngbsicon import (
    HeatCool,
    IconProtocolError,
    RelayKind,
    SetpointKind,
    Setpoints,
    Signal,
    SignalFunction,
    SignalRef,
    parse_state,
)


@pytest.fixture
def full() -> dict[str, Any]:
    return load("state_full")


def test_system_fields(full: dict[str, Any]) -> None:
    state = parse_state(full)
    assert state.sysid == "123456789012"
    assert state.name == "Home"
    assert state.firmware == 1079
    assert state.config_version == "20250606231543"
    assert state.timezone == "Europe/Budapest"
    assert state.uptime == 792
    assert state.mac == "02:00:00:00:00:01"
    assert state.ip == "192.0.2.10"
    assert state.cloud_connected
    assert state.hc_mode is HeatCool.COOLING
    assert state.eco
    assert state.regulation_on
    assert state.water_temp == 26.0
    assert state.outdoor_temp is None  # 222 = no sensor
    assert not state.pump
    assert not state.fault
    assert not state.overheat
    assert not state.frost_warning
    assert state.signals == Signal(0)
    assert not state.switched_output
    assert state.default_setpoints == Setpoints(
        heat=20.0, cool=26.0, eco_heat=17.0, eco_cool=30.0
    )
    assert state.hc_master == SignalRef(SignalFunction.HEAT_COOL, 1, 1)
    assert state.hc_master_thermostat == "1.1"
    assert state.eco_master_thermostat == "1.1"
    assert state.hysteresis == 0.2
    assert state.modbus_enabled is True
    assert state.has_config
    assert "KEY" not in state.raw


def test_thermostats(full: dict[str, Any]) -> None:
    state = parse_state(full)
    assert list(state.thermostats) == [f"1.{n}" for n in range(1, 9)]
    assert list(state.configured_thermostats) == [f"1.{n}" for n in range(1, 6)]

    living = state.thermostats["1.1"]
    assert (living.controller, living.address, living.name) == (1, 1, "Living room")
    assert living.available
    assert (living.temperature, living.humidity, living.dew_point) == (24.8, 36.6, 8.9)
    assert living.setpoints == Setpoints(
        heat=22.5, cool=25.0, eco_heat=22.5, eco_cool=30.0
    )
    assert living.eco and living.hc_mode is HeatCool.COOLING
    assert living.active_setpoint_kind is SetpointKind.ECO_COOL
    assert living.active_setpoint == 30.0
    assert living.limit == 10.0
    assert (living.loop_b_offset_heat, living.loop_b_offset_cool) == (1.0, 0.0)
    assert living.eco_follows_master and living.comfort_follows_master
    assert living.is_hc_master and living.is_eco_master
    assert not (
        living.output_on
        or living.locked
        or living.dew_protection
        or living.frost_protection
    )
    assert not (living.time_program or living.digital_input)
    assert living.raw["NAME"] == "Living room"
    assert not state.thermostats["1.2"].is_hc_master

    empty = state.thermostats["1.6"]
    assert not empty.configured and not empty.available
    assert empty.temperature is None
    assert empty.setpoints == Setpoints(None, None, None, None)
    assert empty.limit is None


def test_controller_and_relays(full: dict[str, Any]) -> None:
    state = parse_state(full)
    assert list(state.controllers) == [1]
    master = state.master
    assert master is not None and master.is_master and master.address == 1
    assert master.firmware == 1079
    assert master.water_temp == 26.0
    assert master.outdoor_temp is None
    assert master.mixing_valve == 0.0
    assert master.supply_voltage == 14.588
    assert master.thermostat_bus_voltage == 14.554
    assert master.battery_ok is True

    relays = master.relays
    assert list(relays) == [f"R{n}" for n in range(10)]
    assert (
        relays["R0"].kind is RelayKind.HEATING_CHANGEOVER
        and relays["R0"].heating
        and not relays["R0"].cooling
    )
    assert relays["R9"].kind is RelayKind.COOLING_CHANGEOVER and relays["R9"].on is True
    assert relays["R8"].kind is RelayKind.PUMP
    assert relays["R8"].thermostat_ids == ("1.1", "1.2", "1.3", "1.4", "1.5")
    assert relays["R3"].kind is RelayKind.VALVE
    assert relays["R3"].thermostat_ids == ("1.3",)
    assert (
        relays["R3"].key == "R3"
        and relays["R3"].name == "R1.3"
        and not relays["R3"].custom_name
    )
    assert relays["R0"].driven_by == (SignalRef(SignalFunction.INPUT, 1, 5),)
    assert relays["R0"].thermostat_ids == ()
    assert (
        relays["R1"].on is False
        and relays["R1"].on_delay == 0
        and not relays["R1"].inverted
    )


def test_poll_without_and_with_cached_config(full: dict[str, Any]) -> None:
    poll = load("state_poll")
    bare = parse_state(poll)
    assert not bare.has_config
    assert bare.name is None and bare.hc_master is None and bare.modbus_enabled is None
    assert bare.hc_master_thermostat is None
    assert list(bare.controllers) == [1]
    assert bare.controllers[1].relays == {} and bare.controllers[1].firmware == 1079
    assert not any(th.is_hc_master for th in bare.thermostats.values())

    merged = parse_state(poll, config=full["CFG"])
    assert merged.has_config and merged.name == "Home"
    assert merged.controllers[1].relays["R9"].on is True


def test_equality_ignores_raw(full: dict[str, Any]) -> None:
    assert parse_state(full) == parse_state(copy.deepcopy(full))
    changed = copy.deepcopy(full)
    changed["DP"]["1.1"]["TEMP"] = 25.0
    assert parse_state(full) != parse_state(changed)


def test_slave_controller_custom_relays_and_external_masters(
    full: dict[str, Any],
) -> None:
    data = copy.deepcopy(full)
    cfg = data["CFG"]
    cfg["ICONS"] = 2
    cfg["HCMASTER"] = "I1.4"
    cfg["CEMASTER"] = ""
    cfg["PUMP"] = "R2.8"
    slave = copy.deepcopy(cfg["ICON1"])
    slave["RELAY"]["R1"]["FUNC"] = "Floor"
    slave["RELAY"]["R2"]["FUNC"] = "S2.8"
    del slave["RELAY"]["R3"]["FUNC"]
    slave["RELAY"]["RX"] = {"FUNC": "bogus"}
    slave["RELAY"]["R4"] = "not a mapping"
    del slave["STATUS"]["R5"]
    slave["STATUS"]["BATT"] = 1
    cfg["ICON2"] = slave
    cfg["ICON3"] = "not a mapping"
    data["DP"]["2.1"] = dict(data["DP"]["1.1"], NAME="Office 2", TEMP=222)
    data["DP"]["2.2"] = dict(data["DP"]["1.2"], LIVE=0)
    data["DP"]["x"] = {}
    data["DP"]["2.3"] = "not a mapping"

    state = parse_state(data)
    assert list(state.controllers) == [1, 2]
    second = state.controllers[2]
    assert (
        not second.is_master and second.firmware is None and second.battery_ok is False
    )
    assert (
        second.relays["R1"].kind is RelayKind.CUSTOM and second.relays["R1"].custom_name
    )
    assert (
        second.relays["R2"].kind is RelayKind.SWITCHED_OUTPUT
        and not second.relays["R2"].custom_name
    )
    assert (
        second.relays["R3"].name == "R2.3"
        and second.relays["R3"].kind is RelayKind.VALVE
    )
    assert second.relays["R5"].on is None
    assert second.relays["R8"].kind is RelayKind.PUMP
    assert state.controllers[1].relays["R8"].kind is RelayKind.VALVE
    assert "RX" not in second.relays and "R4" not in second.relays

    assert state.hc_master == SignalRef(SignalFunction.INPUT, 1, 4)
    assert state.hc_master_thermostat is None
    assert state.eco_master is None and state.eco_master_thermostat is None
    assert not any(
        th.is_hc_master or th.is_eco_master for th in state.thermostats.values()
    )

    assert set(state.thermostats) == {*(f"1.{n}" for n in range(1, 9)), "2.1", "2.2"}
    assert state.thermostats["2.1"].temperature is None  # sensor fault
    assert state.thermostats["2.1"].available
    offline = state.thermostats["2.2"]
    assert not offline.available and offline.temperature is None
    assert offline.setpoints.heat == 20.5  # settings stay known while offline


def test_signals_faults_and_odd_values(full: dict[str, Any]) -> None:
    data = copy.deepcopy(full)
    data.update(
        SIG=2 | 8,
        ERR=1,
        OVERHEAT=1,
        WFROST=1,
        PUMP=1,
        SW=1,
        WTEMP="27.5",
        ETEMP=True,
        CE="x",
    )
    data["DP"]["1.1"]["NAME"] = ""
    del data["INFO"]
    data["CFG"]["MBTCP"] = "broken"
    state = parse_state(data)
    assert state.signals == Signal.OVERHEAT | Signal.OUTDOOR_SENSOR_FAULT
    assert (
        state.fault
        and state.overheat
        and state.frost_warning
        and state.pump
        and state.switched_output
    )
    assert state.water_temp == 27.5
    assert state.outdoor_temp is None
    assert not state.eco
    assert (
        state.firmware is None
        and state.mac is None
        and state.ip is None
        and state.uptime is None
    )
    assert not state.cloud_connected
    assert state.modbus_enabled is False
    assert state.thermostats["1.1"].name == "Thermostat 1.1"


@pytest.mark.parametrize("answer", [{}, {"SYSID": "1"}, {"DP": {}}, load("error")])
def test_not_a_state(answer: dict[str, Any]) -> None:
    with pytest.raises(IconProtocolError):
        parse_state(answer)


@pytest.mark.parametrize(
    ("mode", "eco", "kind", "field"),
    [
        (HeatCool.HEATING, False, SetpointKind.HEAT, "XAH"),
        (HeatCool.COOLING, False, SetpointKind.COOL, "XAC"),
        (HeatCool.HEATING, True, SetpointKind.ECO_HEAT, "ECOH"),
        (HeatCool.COOLING, True, SetpointKind.ECO_COOL, "ECOC"),
    ],
)
def test_active_setpoint(
    mode: HeatCool, eco: bool, kind: SetpointKind, field: str
) -> None:
    assert SetpointKind.active(mode, eco) is kind
    assert kind.field == field
    assert (
        Setpoints(1.0, 2.0, 3.0, 4.0).get(kind)
        == {"XAH": 1.0, "XAC": 2.0, "ECOH": 3.0, "ECOC": 4.0}[field]
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("A1.3", SignalRef(SignalFunction.LOOP_A, 1, 3)),
        (" H2.10 ", SignalRef(SignalFunction.HEAT_COOL, 2, 10)),
        ("", None),
        ("A1", None),
        ("X1.2", None),
        ("a1.2", None),
    ],
)
def test_signal_ref_parse(text: str, expected: SignalRef | None) -> None:
    assert SignalRef.parse(text) == expected


def test_signal_ref_properties() -> None:
    ref = SignalRef(SignalFunction.LOOP_B, 2, 4)
    assert str(ref) == "B2.4" and ref.thermostat_id == "2.4"
    assert SignalRef(SignalFunction.INPUT, 1, 5).thermostat_id is None
    assert SignalRef(SignalFunction.RELAY, 1, 2).thermostat_id is None
