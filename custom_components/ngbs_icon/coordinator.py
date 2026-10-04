"""Data update coordinator: one poll of the whole system per interval."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from ._lib import pyngbsicon
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

type IconConfigEntry = ConfigEntry[IconCoordinator]
type IconWrite = Callable[[pyngbsicon.IconClient], Awaitable[pyngbsicon.IconSystem]]


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

    async def _async_update_data(self) -> pyngbsicon.IconSystem:
        try:
            return await self.client.get_state(include_config=True)
        except pyngbsicon.IconAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except pyngbsicon.IconError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_write(self, write: IconWrite) -> None:
        """Run a write and publish the state the controller confirmed."""
        try:
            state = await write(self.client)
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
        self.async_set_updated_data(state)
