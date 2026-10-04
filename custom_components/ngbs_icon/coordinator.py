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
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            always_update=False,
        )
        self.client = client
        self.statistics = PollStatistics()
        self.offline_since: dict[str, datetime] = {}
        """Configured thermostats that do not communicate, and since when."""
        self._poll_listeners: list[Callable[[pyngbsicon.IconSystem], None]] = []

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
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        self.statistics.last_duration_ms = round((time.monotonic() - start) * 1000)
        self._track_offline(state)
        for listener in self._poll_listeners:
            listener(state)
        return state

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
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="value_rejected",
                translation_placeholders={"value": str(err.requested)},
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
