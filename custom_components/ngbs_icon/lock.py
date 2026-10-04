"""Lock entity: the keypad (child) lock of each thermostat."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import IconConfigEntry, IconCoordinator
from .entity import (
    EntityCandidates,
    IconThermostatEntity,
    async_add_dynamic_entities,
    thermostat_candidates,
)

PARALLEL_UPDATES = 1  # the controller serves one request at a time


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a keypad lock for every thermostat."""
    async_add_dynamic_entities(entry, async_add_entities, _candidates)


def _candidates(coordinator: IconCoordinator) -> EntityCandidates:
    return thermostat_candidates(coordinator, ["keypad_lock"], IconKeypadLock)


class IconKeypadLock(IconThermostatEntity, LockEntity):
    """Locks the thermostat's buttons."""

    _attr_translation_key = "keypad_lock"

    @property
    def is_locked(self) -> bool:
        """Whether the keypad is locked."""
        return self.thermostat.locked

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the keypad."""
        await self._async_set(locked=True)

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the keypad."""
        await self._async_set(locked=False)

    async def _async_set(self, *, locked: bool) -> None:
        await self.coordinator.async_write(
            lambda client: client.set_lock(self.thermostat_id, locked)
        )
