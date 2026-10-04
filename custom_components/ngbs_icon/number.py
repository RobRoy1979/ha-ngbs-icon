"""Number entities: the four setpoints and the service settings of each thermostat."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._lib import pyngbsicon
from .coordinator import IconConfigEntry, IconCoordinator, IconWrite
from .entity import (
    EntityCandidates,
    IconThermostatEntity,
    async_add_dynamic_entities,
    thermostat_candidates,
)
from .util import setpoint_range

PARALLEL_UPDATES = 1  # the controller serves one request at a time


@dataclass(frozen=True, kw_only=True)
class IconNumberDescription(NumberEntityDescription):
    """A number setting of a thermostat."""

    value_fn: Callable[[pyngbsicon.IconThermostat], float | None]
    write_fn: Callable[[str, float], IconWrite]
    setpoint: pyngbsicon.SetpointKind | None = None
    """For setpoints: the range follows the system default ± the thermostat's limit."""


def _setpoint(kind: pyngbsicon.SetpointKind) -> IconNumberDescription:
    return IconNumberDescription(
        key=f"{kind.value}_setpoint",
        translation_key=f"{kind.value}_setpoint",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_step=0.5,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        setpoint=kind,
        value_fn=lambda thermostat: thermostat.setpoints.get(kind),
        write_fn=lambda thermostat_id, value: (
            lambda client: client.set_setpoint(thermostat_id, kind, value)
        ),
    )


def _write_limit(thermostat_id: str, value: float) -> IconWrite:
    return lambda client: client.set_thermostat(thermostat_id, LIM=value)


def _write_offset_heat(thermostat_id: str, value: float) -> IconWrite:
    return lambda client: client.set_thermostat(thermostat_id, DXH=value)


def _write_offset_cool(thermostat_id: str, value: float) -> IconWrite:
    return lambda client: client.set_thermostat(thermostat_id, DXC=value)


NUMBERS: dict[str, IconNumberDescription] = {
    description.key: description
    for description in (
        *(_setpoint(kind) for kind in pyngbsicon.SetpointKind),
        IconNumberDescription(
            key="setpoint_limit",
            translation_key="setpoint_limit",
            device_class=NumberDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            native_min_value=0,
            native_max_value=15,
            native_step=0.5,
            mode=NumberMode.BOX,
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
            value_fn=lambda thermostat: thermostat.limit,
            write_fn=_write_limit,
        ),
        IconNumberDescription(
            key="loop_b_offset_heat",
            translation_key="loop_b_offset_heat",
            device_class=NumberDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            native_min_value=0,
            native_max_value=10,
            native_step=0.5,
            mode=NumberMode.BOX,
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
            value_fn=lambda thermostat: thermostat.loop_b_offset_heat,
            write_fn=_write_offset_heat,
        ),
        IconNumberDescription(
            key="loop_b_offset_cool",
            translation_key="loop_b_offset_cool",
            device_class=NumberDeviceClass.TEMPERATURE_DELTA,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            native_min_value=0,
            native_max_value=10,
            native_step=0.5,
            mode=NumberMode.BOX,
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
            value_fn=lambda thermostat: thermostat.loop_b_offset_cool,
            write_fn=_write_offset_cool,
        ),
    )
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the number settings of every thermostat."""
    async_add_dynamic_entities(entry, async_add_entities, _candidates)


def _candidates(coordinator: IconCoordinator) -> EntityCandidates:
    return thermostat_candidates(coordinator, NUMBERS, IconNumber)


class IconNumber(IconThermostatEntity, NumberEntity):
    """A number setting of a thermostat."""

    entity_description: IconNumberDescription

    def __init__(
        self, coordinator: IconCoordinator, thermostat_id: str, key: str
    ) -> None:
        """Create the setting."""
        super().__init__(coordinator, thermostat_id, key, NUMBERS[key])

    @property
    def native_value(self) -> float | None:
        """The current value."""
        return self.entity_description.value_fn(self.thermostat)

    @property
    def native_min_value(self) -> float:
        """Lowest value the thermostat accepts."""
        if (kind := self.entity_description.setpoint) is None:
            return super().native_min_value
        return setpoint_range(self.system, self.thermostat, kind)[0]

    @property
    def native_max_value(self) -> float:
        """Highest value the thermostat accepts."""
        if (kind := self.entity_description.setpoint) is None:
            return super().native_max_value
        return setpoint_range(self.system, self.thermostat, kind)[1]

    async def async_set_native_value(self, value: float) -> None:
        """Write the value; the thermostat confirms it (about two seconds)."""
        await self.coordinator.async_write(
            self.entity_description.write_fn(self.thermostat_id, value)
        )
