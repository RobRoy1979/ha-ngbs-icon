"""Shared test helpers: recorded fixtures, a simulated controller and a fake TCP server."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
import copy
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"
SYSID = "123456789012"
WRONG_SYSID = "999999990000"  # deliberately wrong; allow-secret

type Answer = bytes | dict[str, Any] | None
type Handler = Callable[[dict[str, Any]], Answer | Awaitable[Answer]]


def load(name: str) -> dict[str, Any]:
    """Load a recorded controller answer."""
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def load_text(name: str) -> str:
    """Load a recorded controller answer as the original text."""
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


class SimulatedController:
    """Answers requests like a real iCON controller, starting from the recorded state.

    Writes behave as measured on real hardware: the controller applies them at once
    (the write answer shows the new value), the next poll shows the thermostat's
    previous value, and from then on the value the thermostat adopted - rounded to
    0.5 °C and clamped into ``min_setpoint``-``max_setpoint``, except that values at
    or below ``discard_below`` are discarded (the previous value stays).
    Top-level default setpoints are not writable.
    """

    SETPOINTS = ("XAH", "XAC", "ECOH", "ECOC")

    def __init__(self) -> None:
        """Start from the recorded full state."""
        self.full = load("state_full")
        self.sysid_answer = load("sysid")
        self.firmware_reveals_sysid = True
        self.min_setpoint = 10.0
        self.discard_below = 5.0
        self.max_setpoint = 30.0
        self.ignored_system_fields: set[str] = {"XAH", "XAC", "ECOH", "ECOC"}
        self._bounce: list[tuple[str | None, str, Any]] = []

    def handle(self, request: dict[str, Any]) -> Answer:
        """Answer one request."""
        if request.get("RELOAD") == 6 and "SYSID" not in request:
            return self.sysid_answer if self.firmware_reveals_sysid else {"ERR": 1}
        if request.get("SYSID") != SYSID:
            return {"ERR": 1}
        if request.get("RELOAD") == 8:
            return None
        writes = {
            key: value
            for key, value in request.items()
            if key not in {"SYSID", "RELOAD"}
        }
        if writes:
            self._apply(writes)
            return self.poll_answer()
        if request.get("RELOAD") in ("", 3):
            return self._with_bounce(self.full)
        return self._with_bounce(self.poll_answer(bounce=False))

    def poll_answer(self, *, bounce: bool = False) -> dict[str, Any]:
        """The state without configuration, as answered to polls and writes."""
        answer = {
            key: value
            for key, value in self.full.items()
            if key not in {"KEY", "CFG", "EVENTLOG", "RELOAD"}
        }
        return self._with_bounce(answer) if bounce else copy.deepcopy(answer)

    def _apply(self, writes: dict[str, Any]) -> None:
        for key, value in writes.items():
            if key == "DP":
                for thermostat_id, fields in value.items():
                    thermostat = self.full["DP"][thermostat_id]
                    for field, new in fields.items():
                        old = thermostat[field]
                        thermostat[field] = (
                            new  # the controller takes the value at once
                        )
                        self._bounce.append((thermostat_id, field, old))
            elif key in self.ignored_system_fields:
                continue
            else:
                self.full[key] = value

    def _with_bounce(self, state: dict[str, Any]) -> dict[str, Any]:
        """Show the thermostat's previous values once, then the values it adopted."""
        state = copy.deepcopy(state)
        for thermostat_id, field, old in self._bounce:
            target = self.full["DP"][thermostat_id] if thermostat_id else self.full
            state_target = state["DP"][thermostat_id] if thermostat_id else state
            state_target[field] = old
            target[field] = self._adopted(field, target[field], old)
        self._bounce.clear()
        return state

    def _adopted(self, field: str, requested: Any, previous: Any) -> Any:
        if field not in self.SETPOINTS:
            return requested
        if not isinstance(requested, int | float) or isinstance(requested, bool):
            return 0  # the controller stores 0 for strings
        if requested <= self.discard_below:
            return previous
        clamped = max(self.min_setpoint, min(requested, self.max_setpoint))
        rounded = round(clamped * 2) / 2
        return int(rounded) if rounded.is_integer() else rounded


class FakeIconServer:
    """A TCP server on 127.0.0.1 that answers like an iCON controller."""

    def __init__(self, handler: Handler) -> None:
        """Serve requests with ``handler``; see :class:`SimulatedController`."""
        self.handler = handler
        self.requests: list[dict[str, Any]] = []
        self.connections = 0
        self.drop_next = 0
        """Close this many connections without answering (connection failures)."""
        self._server: asyncio.Server | None = None

    @property
    def port(self) -> int:
        """The port the server listens on."""
        assert self._server is not None
        return int(self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        """Start listening."""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)

    async def stop(self) -> None:
        """Stop listening."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.connections += 1
        try:
            buffer = b""
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    return
                buffer += chunk
                try:
                    request = json.loads(buffer)
                    break
                except ValueError:
                    continue
            self.requests.append(request)
            if self.drop_next:
                self.drop_next -= 1
                return  # close without answering
            answer = self.handler(request)
            if asyncio.iscoroutine(answer):
                answer = await answer
            if isinstance(answer, dict):
                answer = json.dumps(answer, separators=(",", ":")).encode() + b"\n"
            if answer:
                writer.write(answer)
                await writer.drain()
        finally:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
