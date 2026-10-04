"""Button entity: restart the controller software."""

from __future__ import annotations

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import IconConfigEntry
from .entity import IconSystemEntity

PARALLEL_UPDATES = 1  # the controller serves one request at a time

RESTART = ButtonEntityDescription(
    key="restart",
    device_class=ButtonDeviceClass.RESTART,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the restart button."""
    async_add_entities([IconRestartButton(entry.runtime_data, RESTART)])


class IconRestartButton(IconSystemEntity, ButtonEntity):
    """Restarts the controller software; regulation pauses for a moment."""

    async def async_press(self) -> None:
        """Restart the controller; the next regular poll reads it again."""
        await self.coordinator.async_command(lambda client: client.restart())
