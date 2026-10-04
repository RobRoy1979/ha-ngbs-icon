"""Data update coordinator: one poll of the whole system per interval."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from ._lib import pyngbsicon
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

_SETPOINT_FIELDS = frozenset(kind.field for kind in pyngbsicon.SetpointKind)

STARTING_GRACE = timedelta(seconds=60)
RETRY_SOON = timedelta(seconds=10)

type IconConfigEntry = ConfigEntry[IconCoordinator]
type IconWrite = Callable[[pyngbsicon.IconClient], Awaitable[pyngbsicon.IconSystem]]


@dataclass(slots=True)
class PollStatistics:
    """Counters shown in the diagnostics."""

    polls: int = 0
    failures: int = 0
    last_duration_ms: int | None = None
    last_error: str | None = None


class IconCoordinator(DataUpdateCoordinator[pyngbsicon.IconSystem]):
    """Polls the controller and applies writes.

    Every poll reads the configuration as well: it is as fast as a plain poll and the
    only source of relay states, the mixing valve position and supply voltages.
    """

    config_entry: IconConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: IconConfigEntry,
        client: pyngbsicon.IconClient,
    ) -> None:
        """Create the coordinator for one config entry."""
        interval = timedelta(
            seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=interval,
            always_update=False,
        )
        self._interval = interval
        self._failure_tolerated = False
        self.client = client
        self.statistics = PollStatistics()
        self.offline_since: dict[str, datetime] = {}
        """Configured thermostats that do not communicate, and since when."""
        self._poll_listeners: list[Callable[[pyngbsicon.IconSystem], None]] = []
        self.firmware: dict[int, int] = {}
        """Firmware version by controller address (slaves report it only here)."""
        self._starting_since: datetime | None = None

    async def async_read_firmware(self) -> None:
        """Read the firmware versions of all controllers (SYSID discovery answer)."""
        try:
            info = await self.client.discover_sysid()
        except pyngbsicon.IconError as err:
            # Firmware older than 1079 does not answer; the versions are cosmetic.
            LOGGER.debug("Could not read the controllers' firmware versions: %s", err)
            return
        self.firmware = dict(info.firmware)

    async def _async_update_data(self) -> pyngbsicon.IconSystem:
        self.statistics.polls += 1
        start = time.monotonic()
        try:
            state = await self.client.get_state(include_config=True)
        except pyngbsicon.IconError as err:
            self.statistics.failures += 1
            self.statistics.last_error = f"{type(err).__name__}: {err}"
            if isinstance(err, pyngbsicon.IconAuthenticationError):
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN, translation_key="auth_failed"
                ) from err
            if self._tolerate_failure(err):
                return self.data
            self.update_interval = self._interval
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.statistics.last_duration_ms = round((time.monotonic() - start) * 1000)
        self._failure_tolerated = False
        self.update_interval = self._interval
        if self._keep_previous(state):
            return self.data
        self._track_offline(state)
        for listener in self._poll_listeners:
            listener(state)
        return state

    def _tolerate_failure(self, err: pyngbsicon.IconError) -> bool:
        """Ride out a single failed poll after a successful one.

        A controller that misses one request (observed: a few seconds without
        accepting connections) should not make every entity unavailable and log an
        error. The previous state stays; the next attempt comes sooner.
        """
        if self._failure_tolerated or self.data is None or not self.last_update_success:
            return False
        self._failure_tolerated = True
        self.update_interval = min(self._interval, RETRY_SOON)
        LOGGER.debug("Poll failed once, keeping the previous state: %s", err)
        return True

    def _keep_previous(self, state: pyngbsicon.IconSystem) -> bool:
        """Skip the answers of a controller whose software is starting.

        They hold placeholder values (for a moment the heating mode) that would
        show up in the history and could trigger automations. The previous state is
        kept for at most a minute, so a firmware that never reports the task list
        is not frozen.
        """
        if not state.starting or self.data is None:
            self._starting_since = None
            return False
        now = dt_util.utcnow()
        if self._starting_since is None:
            self._starting_since = now
        if now - self._starting_since > STARTING_GRACE:
            return False
        LOGGER.debug("The controller is starting; keeping the previous state")
        return True

    @callback
    def async_add_poll_listener(
        self, listener: Callable[[pyngbsicon.IconSystem], None]
    ) -> CALLBACK_TYPE:
        """Call ``listener`` after every successful poll, changed or not.

        Coordinator listeners only run when the data changes; conditions that depend
        on how long a state lasts need every poll.
        """
        self._poll_listeners.append(listener)
        return lambda: self._poll_listeners.remove(listener)

    def _track_offline(self, state: pyngbsicon.IconSystem) -> None:
        now = dt_util.utcnow()
        offline = {
            thermostat_id
            for thermostat_id, thermostat in state.configured_thermostats.items()
            if not thermostat.live
        }
        self.offline_since = {
            thermostat_id: self.offline_since.get(thermostat_id, now)
            for thermostat_id in offline
        }

    async def async_write(self, write: IconWrite) -> None:
        """Run a write and publish the state the controller confirmed."""
        state = await self.async_command(write)
        self.async_set_updated_data(state)

    async def async_command[T](
        self, command: Callable[[pyngbsicon.IconClient], Awaitable[T]]
    ) -> T:
        """Run a request on the controller; errors become translated exceptions."""
        try:
            return await command(self.client)
        except ValueError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_value",
                translation_placeholders={"error": str(err)},
            ) from err
        except pyngbsicon.IconRejectedError as err:
            # A setpoint is rejected by the thermostat (range); anything else (system
            # mode, ECO, a service setting) by the controller.
            if err.field in _SETPOINT_FIELDS:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="value_rejected",
                    translation_placeholders={"value": str(err.requested)},
                ) from err
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_rejected",
                translation_placeholders={
                    "field": str(err.field),
                    "value": str(err.requested),
                },
            ) from err
        except pyngbsicon.IconAuthenticationError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except pyngbsicon.IconError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
