"""Switch entities: system ECO mode and the switched output."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._lib import pyngbsicon
from .coordinator import IconConfigEntry, IconCoordinator, IconWrite
from .entity import EntityCandidates, IconSystemEntity, async_add_dynamic_entities

PARALLEL_UPDATES = 1  # the controller serves one request at a time


@dataclass(frozen=True, kw_only=True)
class IconSwitchDescription(SwitchEntityDescription):
    """A switch of the system."""

    value_fn: Callable[[pyngbsicon.IconSystem], bool]
    write_fn: Callable[[bool], IconWrite]
    exists_fn: Callable[[pyngbsicon.IconSystem], bool] = lambda _: True


def _has_switched_output(system: pyngbsicon.IconSystem) -> bool:
    return any(
        relay.kind is pyngbsicon.RelayKind.SWITCHED_OUTPUT
        for controller in system.controllers.values()
        for relay in controller.relays.values()
    )


SWITCHES: tuple[IconSwitchDescription, ...] = (
    IconSwitchDescription(
        key="eco",
        translation_key="eco",
        value_fn=lambda system: system.eco,
        write_fn=lambda on: lambda client: client.set_eco(on),
    ),
    IconSwitchDescription(
        key="switched_output",
        translation_key="switched_output",
        value_fn=lambda system: system.switched_output,
        write_fn=lambda on: lambda client: client.set_switched_output(on),
        exists_fn=_has_switched_output,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the switches."""
    async_add_dynamic_entities(entry, async_add_entities, _candidates)


def _candidates(coordinator: IconCoordinator) -> EntityCandidates:
    system = coordinator.data
    for description in SWITCHES:
        if description.exists_fn(system):
            yield (
                f"{system.sysid}_{description.key}",
                partial(IconSwitch, coordinator, description),
            )


class IconSwitch(IconSystemEntity, SwitchEntity):
    """A switch of the system."""

    entity_description: IconSwitchDescription

    @property
    def is_on(self) -> bool:
        """The current state."""
        return self.entity_description.value_fn(self.system)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch on."""
        await self.coordinator.async_write(self.entity_description.write_fn(True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch off."""
        await self.coordinator.async_write(self.entity_description.write_fn(False))
