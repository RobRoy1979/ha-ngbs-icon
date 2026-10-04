"""Select entity: the system's heating/cooling mode."""

from __future__ import annotations

from functools import partial

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._lib import pyngbsicon
from .coordinator import IconConfigEntry, IconCoordinator
from .entity import EntityCandidates, IconSystemEntity, async_add_dynamic_entities

PARALLEL_UPDATES = 1  # the controller serves one request at a time

SYSTEM_MODE = SelectEntityDescription(
    key="system_mode",
    translation_key="system_mode",
    options=["heating", "cooling"],
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the system mode select when a thermostat switches the mode."""
    async_add_dynamic_entities(entry, async_add_entities, _candidates)


def _candidates(coordinator: IconCoordinator) -> EntityCandidates:
    system = coordinator.data
    # With an input or central changeover the mode is a sensor (see sensor.py).
    if system.hc_master_thermostat is not None:
        yield (
            f"{system.sysid}_{SYSTEM_MODE.key}",
            partial(IconSystemModeSelect, coordinator, SYSTEM_MODE),
        )


class IconSystemModeSelect(IconSystemEntity, SelectEntity):
    """Heating or cooling for the whole system.

    The controller switches its changeover relays minutes after the change.
    """

    @property
    def available(self) -> bool:
        """Unavailable if the configuration moved the changeover to an input."""
        return super().available and self.system.hc_master_thermostat is not None

    @property
    def current_option(self) -> str:
        """The current mode."""
        return self.options[self.system.hc_mode]

    async def async_select_option(self, option: str) -> None:
        """Switch the mode."""
        mode = pyngbsicon.HeatCool(self.options.index(option))
        await self.coordinator.async_write(lambda client: client.set_hc_mode(mode))
