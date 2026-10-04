"""IconClient against a simulated controller on a local TCP server."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from icon_test_support import SYSID, WRONG_SYSID, FakeIconServer, SimulatedController
import pytest

from pyngbsicon import (
    HeatCool,
    IconAuthenticationError,
    IconClient,
    IconConnectionError,
    IconProtocolError,
    IconRejectedError,
    IconUnsupportedError,
    SetpointKind,
)
from pyngbsicon.client import _same


def make_client(
    server: FakeIconServer, sysid: str | None = SYSID, **kwargs: Any
) -> IconClient:
    options: dict[str, Any] = {
        "timeout": 1.0,
        "settle_min": 0.0,
        "settle_poll_interval": 0.01,
        "settle_timeout": 1.0,
    }
    options.update(kwargs)
    return IconClient("127.0.0.1", sysid, port=server.port, **options)


def kinds(server: FakeIconServer) -> list[str]:
    """Summarise the requests: sysid / config / poll / write."""
    result = []
    for request in server.requests:
        if request.get("RELOAD") == 6:
            result.append("sysid")
        elif request.get("RELOAD") == "":
            result.append("config")
        elif set(request) == {"SYSID"}:
            result.append("poll")
        else:
            result.append("write")
    return result


async def test_get_state_discovers_sysid_and_caches_config(
    server: FakeIconServer,
) -> None:
    client = make_client(server, sysid=None)
    assert (client.host, client.port, client.sysid) == ("127.0.0.1", server.port, None)
    state = await client.get_state()
    assert client.sysid == SYSID
    assert state.has_config and state.controllers[1].relays["R9"].on

    polled = await client.get_state(include_config=False)
    assert polled.has_config and polled.name == "Home"
    assert kinds(server) == ["sysid", "config", "poll"]


async def test_first_poll_without_config_reads_it(server: FakeIconServer) -> None:
    state = await make_client(server).get_state(include_config=False)
    assert state.has_config
    assert kinds(server) == ["config"]


async def test_discover_sysid(server: FakeIconServer) -> None:
    info = await make_client(server, sysid=None).discover_sysid()
    assert info.sysid == SYSID and info.firmware == {1: 1079}


async def test_old_firmware_does_not_reveal_sysid(
    server: FakeIconServer, controller: SimulatedController
) -> None:
    controller.firmware_reveals_sysid = False
    with pytest.raises(IconUnsupportedError):
        await make_client(server, sysid=None).get_state()


async def test_wrong_sysid(server: FakeIconServer) -> None:
    with pytest.raises(IconAuthenticationError, match="…0000"):
        await make_client(server, sysid=WRONG_SYSID).get_state()


async def test_unreachable() -> None:
    probe_server = FakeIconServer(lambda request: None)
    await probe_server.start()
    port = probe_server.port
    await probe_server.stop()  # nothing listens on the port any more
    client = IconClient("127.0.0.1", SYSID, port=port, timeout=0.5)
    with pytest.raises(IconConnectionError, match="cannot connect"):
        await client.get_state()


async def test_no_answer_times_out() -> None:
    async def never(request: dict[str, Any]) -> None:
        await asyncio.sleep(5)

    slow = FakeIconServer(never)
    await slow.start()
    try:
        client = IconClient("127.0.0.1", SYSID, port=slow.port, timeout=0.2, retries=0)
        with pytest.raises(IconConnectionError, match="did not answer"):
            await client.get_state()
    finally:
        await slow.stop()


async def test_connection_failure_is_retried_once(server: FakeIconServer) -> None:
    server.drop_next = 1
    state = await make_client(server).get_state()
    assert state.sysid == SYSID
    assert server.connections == 2

    server.drop_next = 2
    with pytest.raises(IconProtocolError, match="without answering"):
        await make_client(server).get_state()


async def test_empty_answer(server: FakeIconServer) -> None:
    server.drop_next = 5
    client = make_client(server, retries=0)
    with pytest.raises(IconProtocolError, match="without answering"):
        await client.get_state()
    assert await client.raw_request({"SYSID": SYSID}) == {}


async def test_set_setpoint_waits_for_the_thermostat(server: FakeIconServer) -> None:
    client = make_client(server)
    state = await client.set_setpoints("1.2", heat=21.0, eco_heat=18.5)
    thermostat = state.thermostats["1.2"]
    assert (thermostat.setpoints.heat, thermostat.setpoints.eco_heat) == (21.0, 18.5)
    assert state.has_config
    # before-read, one write with both fields, then polls until stable
    assert kinds(server)[:2] == ["config", "write"]
    assert server.requests[1] == {
        "SYSID": SYSID,
        "DP": {"1.2": {"XAH": 21.0, "ECOH": 18.5}},
    }
    assert set(kinds(server)[2:]) == {"poll"}
    assert len(kinds(server)) >= 5  # old value (bounce), new value, new value again


async def test_clamped_setpoint_is_returned_as_adopted(server: FakeIconServer) -> None:
    client = make_client(server)
    state = await client.set_setpoint("1.2", SetpointKind.HEAT, 35.0)
    assert state.thermostats["1.2"].setpoints.heat == 30.0
    state = await client.set_setpoint("1.2", SetpointKind.HEAT, 6.0)
    assert state.thermostats["1.2"].setpoints.heat == 10.0


async def test_rejected_setpoint(server: FakeIconServer) -> None:
    with pytest.raises(IconRejectedError) as err:
        await make_client(server).set_setpoint("1.2", SetpointKind.HEAT, 5.0)
    assert (
        err.value.target,
        err.value.field,
        err.value.requested,
        err.value.actual,
    ) == (
        "thermostat 1.2",
        "XAH",
        5.0,
        20.5,
    )


async def test_unchanged_value_is_fine(server: FakeIconServer) -> None:
    state = await make_client(server).set_setpoints("1.2", heat=20.5)
    assert state.thermostats["1.2"].setpoints.heat == 20.5


async def test_write_without_confirmation(server: FakeIconServer) -> None:
    state = await make_client(server).set_setpoints("1.2", heat=21.5, confirm=False)
    assert state.thermostats["1.2"].setpoints.heat == 21.5
    assert kinds(server) == ["write"]
    assert not state.has_config  # nothing was read before


async def test_write_validation(server: FakeIconServer) -> None:
    client = make_client(server)
    with pytest.raises(ValueError, match="invalid thermostat id"):
        await client.set_setpoints("living", heat=21.0)
    with pytest.raises(ValueError, match="no thermostat 3.1"):
        await client.set_setpoints("3.1", heat=21.0)
    with pytest.raises(ValueError, match="multiple of 0.5"):
        await client.set_setpoints("1.1", heat=21.3)
    with pytest.raises(ValueError, match="outside"):
        await client.set_setpoints("1.1", heat=40.0)
    with pytest.raises(TypeError):
        await client.set_setpoints("1.1", heat="21.5")  # type: ignore[arg-type]  # deliberately wrong type
    with pytest.raises(TypeError):
        await client.set_setpoints("1.1", heat=float("nan"))
    with pytest.raises(ValueError, match="no setpoint"):
        await client.set_setpoints("1.1")
    with pytest.raises(TypeError, match="must be a number"):
        await client.set_thermostat("1.1", LIM="5")  # type: ignore[arg-type]  # deliberately wrong type
    assert "write" not in kinds(server)


async def test_raw_thermostat_field(server: FakeIconServer) -> None:
    state = await make_client(server).set_thermostat("1.3", LIM=5)
    assert state.thermostats["1.3"].limit == 5.0


async def test_eco_lock_and_system_writes(
    server: FakeIconServer, controller: SimulatedController
) -> None:
    client = make_client(server)
    state = await client.set_eco(False, "1.5")
    assert not state.thermostats["1.5"].eco and state.thermostats["1.4"].eco

    state = await client.set_lock("1.5", True)
    assert state.thermostats["1.5"].locked

    state = await client.set_eco(False)
    assert not state.eco
    assert (
        server.requests[-4:][1] == {"SYSID": SYSID, "CE": 0}
        or {"SYSID": SYSID, "CE": 0} in server.requests
    )

    state = await client.set_hc_mode(HeatCool.HEATING)
    assert state.hc_mode is HeatCool.HEATING

    state = await client.set_switched_output(True)
    assert state.switched_output


async def test_ignored_system_write_is_rejected(
    server: FakeIconServer, controller: SimulatedController
) -> None:
    controller.ignored_system_fields.add("HC")  # heating/cooling switched by an input
    with pytest.raises(IconRejectedError, match="system: HC=0"):
        await make_client(server).set_hc_mode(HeatCool.HEATING)


async def test_settle_gives_up_after_timeout(
    server: FakeIconServer, controller: SimulatedController
) -> None:
    """A value that never settles stops the wait at the timeout, not forever."""
    flip = {"value": 0}
    original = controller.handle

    def flapping(request: dict[str, Any]) -> Any:
        answer = original(request)
        if isinstance(answer, dict) and set(request) == {"SYSID"}:
            flip["value"] ^= 1
            answer["DP"]["1.5"]["PL"] = flip["value"]
        return answer

    server.handler = flapping
    client = make_client(server, settle_timeout=0.2, settle_poll_interval=0.02)
    loop = asyncio.get_running_loop()
    started = loop.time()
    with contextlib.suppress(
        IconRejectedError
    ):  # the last sample may show either value
        await client.set_lock("1.5", True)
    assert 0.2 <= loop.time() - started < 1.0
    assert kinds(server).count("poll") >= 5  # kept polling until the timeout


async def test_writes_are_serialised(server: FakeIconServer) -> None:
    client = make_client(server)
    await client.get_state()
    server.requests.clear()
    await asyncio.gather(
        client.set_setpoints("1.2", heat=21.0),
        client.set_setpoints("1.3", heat=21.5),
    )
    writes = [index for index, kind in enumerate(kinds(server)) if kind == "write"]
    assert len(writes) == 2
    between = kinds(server)[writes[0] + 1 : writes[1]]
    assert (
        between.count("poll") >= 3
    )  # the first write settled before the second started


async def test_restart(server: FakeIconServer) -> None:
    await make_client(server).restart()
    assert server.requests[-1] == {"SYSID": SYSID, "RELOAD": 8}
    assert server.connections == 1


async def test_raw_request(server: FakeIconServer) -> None:
    answer = await make_client(server).raw_request({"SYSID": SYSID, "RELOAD": ""})
    assert "CFG" in answer


async def test_quirky_answer_is_read_until_close() -> None:
    quirky = FakeIconServer(
        lambda request: (
            b'{"SYSID":"123456789012","DOWNLOAD":0000,"ICON1":{"FIRMWARE":1079}}\n'
        )
    )
    await quirky.start()
    try:
        info = await IconClient("127.0.0.1", port=quirky.port).discover_sysid()
        assert info.download == 0
    finally:
        await quirky.stop()


async def test_answer_without_closing_is_not_waited_for() -> None:
    """A complete answer ends the request even if the controller keeps the connection."""
    hold_open = asyncio.Event()

    async def answer_and_linger(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.read(4096)
        writer.write(b'{"SYSID":"123456789012","ICON1":{"FIRMWARE":1079}}\n')
        await writer.drain()
        await asyncio.wait_for(hold_open.wait(), 2)
        writer.close()

    lingering = await asyncio.start_server(answer_and_linger, "127.0.0.1", 0)
    port = int(lingering.sockets[0].getsockname()[1])
    try:
        client = IconClient("127.0.0.1", port=port)
        info = await asyncio.wait_for(client.discover_sysid(), 1)
        assert info.sysid == SYSID
    finally:
        hold_open.set()
        lingering.close()
        await lingering.wait_closed()


def test_value_comparison() -> None:
    assert _same(21, 21.0)
    assert not _same(21, 21.5)
    assert _same(None, None)
    assert not _same(None, 0)
