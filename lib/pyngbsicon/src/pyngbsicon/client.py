"""Asynchronous client for one iCON system."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import logging
import math
import re
from typing import Any

from .const import (
    DEFAULT_PORT,
    DEFAULT_TIMEOUT,
    RELOAD_CONFIG,
    RELOAD_RESTART,
    RELOAD_SYSID,
    SETPOINT_MAX,
    SETPOINT_MIN,
    SETPOINT_STEP,
    SETTLE_MIN,
    SETTLE_POLL_INTERVAL,
    SETTLE_TIMEOUT,
)
from .exceptions import (
    IconAuthenticationError,
    IconConnectionError,
    IconProtocolError,
    IconRejectedError,
    IconUnsupportedError,
)
from .models import HeatCool, IconSystem, SetpointKind, SysidInfo
from .protocol import decode, encode, is_auth_error, parse_state, parse_sysid_info
from .transport import exchange

_LOGGER = logging.getLogger(__name__)
_THERMOSTAT_ID_RE = re.compile(r"\d+\.\d+")

type _Extractor = Callable[[Mapping[str, Any]], Any]


class IconClient:
    """Client for the JSON service protocol of an iCON master controller.

    Requests are serialised: the controller serves one connection at a time, and a
    write is only finished when the thermostat has taken over the new value (see
    :meth:`set_setpoints`). The client keeps the configuration from the last full
    read, so every state it returns is complete.

    The SYSID is discovered automatically on first use when it is not given
    (firmware 1079 and later).
    """

    def __init__(
        self,
        host: str,
        sysid: str | None = None,
        *,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = 1,
        settle_min: float = SETTLE_MIN,
        settle_poll_interval: float = SETTLE_POLL_INTERVAL,
        settle_timeout: float = SETTLE_TIMEOUT,
    ) -> None:
        """Create a client; no connection is made until the first request."""
        self._host = host
        self._port = port
        self._sysid = sysid or None
        self._timeout = timeout
        self._retries = max(0, retries)
        self._settle_min = settle_min
        self._settle_poll_interval = settle_poll_interval
        self._settle_timeout = settle_timeout
        self._lock = asyncio.Lock()
        self._config: Mapping[str, Any] | None = None

    @property
    def host(self) -> str:
        """Host name or address of the controller."""
        return self._host

    @property
    def port(self) -> int:
        """TCP port of the service protocol."""
        return self._port

    @property
    def sysid(self) -> str | None:
        """The system ID, once known."""
        return self._sysid

    # -- reading -----------------------------------------------------------

    async def discover_sysid(self) -> SysidInfo:
        """Ask the controller for its SYSID (and firmware versions).

        Raises :class:`IconUnsupportedError` on firmware older than 1079, which does
        not reveal the SYSID. The discovered SYSID is used by later requests.
        """
        async with self._lock:
            answer = await self._request({"RELOAD": RELOAD_SYSID}, discovery=True)
        info = parse_sysid_info(answer)
        self._sysid = info.sysid
        return info

    async def get_state(self, *, include_config: bool = True) -> IconSystem:
        """Read the complete state.

        With ``include_config`` the configuration is read as well - as fast as a plain
        poll, and the only source of relay states, the mixing valve position and supply
        voltages. Without it, the configuration of the last full read is used (and is
        read now if there is none yet).
        """
        sysid = await self._ensure_sysid()
        async with self._lock:
            answer = await self._read_locked(
                sysid, include_config or self._config is None
            )
        return parse_state(answer, config=self._config)

    # -- writing -----------------------------------------------------------

    async def set_setpoints(
        self,
        thermostat_id: str,
        *,
        heat: float | None = None,
        cool: float | None = None,
        eco_heat: float | None = None,
        eco_cool: float | None = None,
        confirm: bool = True,
    ) -> IconSystem:
        """Change one or more setpoints of a thermostat in a single request.

        With ``confirm`` (default) the call returns once the thermostat has taken over
        the values, which takes about two seconds: the controller applies a write at
        once, then the thermostat reports its previous state for a moment before it
        adopts - and possibly rounds or clamps - the new values. A value the
        thermostat does not adopt at all raises :class:`IconRejectedError`; a clamped
        or rounded value is returned as the thermostat reports it.
        """
        changes = {
            kind.field: _setpoint(value)
            for kind, value in (
                (SetpointKind.HEAT, heat),
                (SetpointKind.COOL, cool),
                (SetpointKind.ECO_HEAT, eco_heat),
                (SetpointKind.ECO_COOL, eco_cool),
            )
            if value is not None
        }
        if not changes:
            raise ValueError("no setpoint given")
        return await self._write_thermostat(thermostat_id, changes, confirm=confirm)

    async def set_setpoint(
        self,
        thermostat_id: str,
        kind: SetpointKind,
        value: float,
        *,
        confirm: bool = True,
    ) -> IconSystem:
        """Change one setpoint of a thermostat (see :meth:`set_setpoints`)."""
        return await self._write_thermostat(
            thermostat_id, {SetpointKind(kind).field: _setpoint(value)}, confirm=confirm
        )

    async def set_eco(
        self, on: bool, thermostat_id: str | None = None, *, confirm: bool = True
    ) -> IconSystem:
        """Switch ECO mode of one thermostat, or of the system when no thermostat is given.

        The system-wide switch writes the top-level ``CE`` field; thermostats follow it
        according to their "follow" settings.
        """
        if thermostat_id is None:
            return await self._write_system({"CE": int(on)}, confirm=confirm)
        return await self._write_thermostat(
            thermostat_id, {"CE": int(on)}, confirm=confirm
        )

    async def set_lock(
        self, thermostat_id: str, locked: bool, *, confirm: bool = True
    ) -> IconSystem:
        """Lock or unlock the keypad of a thermostat (child lock)."""
        return await self._write_thermostat(
            thermostat_id, {"PL": int(locked)}, confirm=confirm
        )

    async def set_hc_mode(self, mode: HeatCool, *, confirm: bool = True) -> IconSystem:
        """Switch the system between heating and cooling.

        The controller switches its changeover relays minutes later. When heating and
        cooling are switched by an external input, the write has no effect and
        :class:`IconRejectedError` is raised (with ``confirm``).
        """
        return await self._write_system({"HC": int(HeatCool(mode))}, confirm=confirm)

    async def set_switched_output(
        self, on: bool, *, confirm: bool = True
    ) -> IconSystem:
        """Switch the controllable output ("TAP", top-level ``SW`` field)."""
        return await self._write_system({"SW": int(on)}, confirm=confirm)

    async def set_thermostat(
        self, thermostat_id: str, *, confirm: bool = True, **fields: float
    ) -> IconSystem:
        """Write raw thermostat fields, e.g. ``set_thermostat("1.2", LIM=5)``.

        Values must be numbers: the controller stores 0 for anything else.
        """
        for name, value in fields.items():
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise TypeError(f"{name} must be a number, not {type(value).__name__}")
        return await self._write_thermostat(
            thermostat_id, dict(fields), confirm=confirm
        )

    # -- other -------------------------------------------------------------

    async def restart(self) -> None:
        """Restart the controller software (regulation pauses for a moment)."""
        sysid = await self._ensure_sysid()
        async with self._lock:
            await self._request(
                {"SYSID": sysid, "RELOAD": RELOAD_RESTART},
                retry=False,
                allow_empty=True,
            )

    async def raw_request(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Send a request as is and return the decoded answer (for diagnostics)."""
        async with self._lock:
            return await self._request(dict(payload), allow_empty=True)

    # -- internals ---------------------------------------------------------

    async def _ensure_sysid(self) -> str:
        if self._sysid is None:
            await self.discover_sysid()
        assert self._sysid is not None
        return self._sysid

    async def _read_locked(self, sysid: str, include_config: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {"SYSID": sysid}
        if include_config:
            payload["RELOAD"] = RELOAD_CONFIG
        answer = await self._request(payload)
        if isinstance(answer.get("CFG"), Mapping):
            self._config = answer["CFG"]
        return answer

    async def _write_thermostat(
        self, thermostat_id: str, changes: dict[str, Any], *, confirm: bool
    ) -> IconSystem:
        if not _THERMOSTAT_ID_RE.fullmatch(thermostat_id):
            raise ValueError(
                f"invalid thermostat id {thermostat_id!r} (expected e.g. '1.3')"
            )

        def extractor(field: str) -> _Extractor:
            return lambda state: state["DP"][thermostat_id].get(field)

        return await self._write(
            {"DP": {thermostat_id: changes}},
            {field: (extractor(field), value) for field, value in changes.items()},
            target=f"thermostat {thermostat_id}",
            confirm=confirm,
            thermostat_id=thermostat_id,
        )

    async def _write_system(
        self, changes: dict[str, Any], *, confirm: bool
    ) -> IconSystem:
        def extractor(field: str) -> _Extractor:
            return lambda state: state.get(field)

        return await self._write(
            changes,
            {field: (extractor(field), value) for field, value in changes.items()},
            target="system",
            confirm=confirm,
        )

    async def _write(
        self,
        changes: dict[str, Any],
        targets: dict[str, tuple[_Extractor, Any]],
        *,
        target: str,
        confirm: bool,
        thermostat_id: str | None = None,
    ) -> IconSystem:
        sysid = await self._ensure_sysid()
        async with self._lock:
            before: dict[str, Any] | None = None
            if confirm:
                before = await self._read_locked(
                    sysid, include_config=self._config is None
                )
                if thermostat_id is not None and thermostat_id not in before.get(
                    "DP", {}
                ):
                    raise ValueError(f"the system has no thermostat {thermostat_id}")
            answer = await self._request({"SYSID": sysid, **changes})
            if not confirm:
                return parse_state(answer, config=self._config)
            assert before is not None
            final = await self._settle(
                sysid, [extract for extract, _ in targets.values()]
            )

        for field, (extract, requested) in targets.items():
            actual, previous = extract(final), extract(before)
            if _same(actual, requested) or _same(requested, previous):
                continue
            if _same(actual, previous):
                raise IconRejectedError(target, field, requested, actual)
            _LOGGER.debug(
                "%s: %s=%r was adjusted to %r", target, field, requested, actual
            )
        return parse_state(final, config=self._config)

    async def _settle(self, sysid: str, extractors: list[_Extractor]) -> dict[str, Any]:
        """Poll until the written values are stable (see :meth:`set_setpoints`)."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        previous: tuple[Any, ...] | None = None
        while True:
            await asyncio.sleep(self._settle_poll_interval)
            state = await self._request({"SYSID": sysid})
            values = tuple(extract(state) for extract in extractors)
            elapsed = loop.time() - start
            if values == previous and elapsed >= self._settle_min:
                return state
            if elapsed >= self._settle_timeout:
                _LOGGER.debug("values still changing after %.1f s: %r", elapsed, values)
                return state
            previous = values

    async def _request(
        self,
        payload: dict[str, Any],
        *,
        retry: bool = True,
        allow_empty: bool = False,
        discovery: bool = False,
    ) -> dict[str, Any]:
        data = encode(payload)
        attempts = 1 + (self._retries if retry else 0)
        attempt = 0
        while True:
            attempt += 1
            try:
                raw = await exchange(
                    self._host, self._port, data, timeout=self._timeout
                )
            except IconConnectionError as err:
                if attempt >= attempts:
                    raise
                _LOGGER.debug("request failed (%s), retrying", err)
                continue
            # Closing the connection without an answer is a failed attempt as well.
            if raw or allow_empty or attempt >= attempts:
                break
            _LOGGER.debug("connection closed without an answer, retrying")
        if not raw:
            if allow_empty:
                return {}
            raise IconProtocolError(
                f"{self._host}:{self._port} closed the connection without answering"
            )
        answer = decode(raw)
        if is_auth_error(answer):
            if discovery:
                raise IconUnsupportedError(
                    "the controller does not reveal its SYSID (firmware older than 1079); "
                    "the SYSID printed on the controller has to be given"
                )
            raise IconAuthenticationError(
                f"the controller rejected SYSID {_masked(self._sysid)}"
            )
        return answer


def _setpoint(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
    ):
        raise TypeError(f"setpoint must be a number, not {value!r}")
    if not SETPOINT_MIN <= value <= SETPOINT_MAX:
        raise ValueError(
            f"setpoint {value} is outside {SETPOINT_MIN}-{SETPOINT_MAX} °C"
        )
    rounded = round(value / SETPOINT_STEP) * SETPOINT_STEP
    if abs(rounded - value) > 1e-9:
        raise ValueError(f"setpoint {value} is not a multiple of {SETPOINT_STEP} °C")
    return float(rounded)


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, int | float) and isinstance(right, int | float):
        return math.isclose(float(left), float(right), abs_tol=1e-6)
    return bool(left == right)


def _masked(sysid: str | None) -> str:
    return f"…{sysid[-4:]}" if sysid else "(none)"
