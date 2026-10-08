"""Binary sensor entities: system signals, relays and thermostat states."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._lib import pyngbsicon
from .coordinator import IconConfigEntry, IconCoordinator
from .entity import (
    EntityCandidates,
    IconControllerEntity,
    IconSystemEntity,
    IconThermostatEntity,
    async_add_dynamic_entities,
    thermostat_candidates,
)

PARALLEL_UPDATES = 0  # read-only; the coordinator polls


@dataclass(frozen=True, kw_only=True)
class IconSystemBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor of the system."""

    value_fn: Callable[[pyngbsicon.IconSystem], bool]


@dataclass(frozen=True, kw_only=True)
class IconThermostatBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor of one thermostat."""

    value_fn: Callable[[pyngbsicon.IconThermostat], bool]
    requires_live: bool = True


SYSTEM_BINARY_SENSORS: tuple[IconSystemBinarySensorDescription, ...] = (
    IconSystemBinarySensorDescription(
        key="pump",
        translation_key="pump",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda system: system.pump,
    ),
    IconSystemBinarySensorDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda system: system.fault,
    ),
    IconSystemBinarySensorDescription(
        key="overheat",
        translation_key="overheat",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda system: system.overheat,
    ),
    IconSystemBinarySensorDescription(
        key="frost_warning",
        translation_key="frost_warning",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda system: system.frost_warning,
    ),
    IconSystemBinarySensorDescription(
        key="regulation",
        translation_key="regulation",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda system: system.regulation_on,
    ),
    IconSystemBinarySensorDescription(
        key="cloud_connection",
        translation_key="cloud_connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda system: system.cloud_connected,
    ),
)

THERMOSTAT_BINARY_SENSORS: dict[str, IconThermostatBinarySensorDescription] = {
    description.key: description
    for description in (
        IconThermostatBinarySensorDescription(
            key="output",
            translation_key="output",
            device_class=BinarySensorDeviceClass.RUNNING,
            value_fn=lambda thermostat: thermostat.output_on,
        ),
        IconThermostatBinarySensorDescription(
            key="connected",
            translation_key="connected",
            device_class=BinarySensorDeviceClass.CONNECTIVITY,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=lambda thermostat: thermostat.live,
            requires_live=False,
        ),
        IconThermostatBinarySensorDescription(
            key="dew_protection",
            translation_key="dew_protection",
            device_class=BinarySensorDeviceClass.PROBLEM,
            value_fn=lambda thermostat: thermostat.dew_protection,
        ),
        IconThermostatBinarySensorDescription(
            key="frost_protection",
            translation_key="frost_protection",
            device_class=BinarySensorDeviceClass.PROBLEM,
            value_fn=lambda thermostat: thermostat.frost_protection,
        ),
        IconThermostatBinarySensorDescription(
            key="window",
            device_class=BinarySensorDeviceClass.WINDOW,
            entity_registry_enabled_default=False,
            value_fn=lambda thermostat: thermostat.digital_input,
        ),
        IconThermostatBinarySensorDescription(
            key="time_program",
            translation_key="time_program",
            entity_registry_enabled_default=False,
            value_fn=lambda thermostat: thermostat.time_program,
        ),
        IconThermostatBinarySensorDescription(
            key="eco_follows_master",
            translation_key="eco_follows_master",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=lambda thermostat: thermostat.eco_follows_master,
        ),
    )
}

_RELAY_TRANSLATION_KEYS = {
    pyngbsicon.RelayKind.HEATING_CHANGEOVER: "heating_relay",
    pyngbsicon.RelayKind.COOLING_CHANGEOVER: "cooling_relay",
    pyngbsicon.RelayKind.PUMP: "pump_relay",
    pyngbsicon.RelayKind.SWITCHED_OUTPUT: "switched_output_relay",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the binary sensors; new ones are added when they appear."""
    async_add_dynamic_entities(entry, async_add_entities, _candidates)


def _candidates(coordinator: IconCoordinator) -> EntityCandidates:
    system = coordinator.data
    sysid = system.sysid
    for description in SYSTEM_BINARY_SENSORS:
        yield (
            f"{sysid}_{description.key}",
            partial(IconSystemBinarySensor, coordinator, description),
        )
    for address, controller in system.controllers.items():
        for relay in controller.relays.values():
            if relay_in_use(system, relay):
                yield (
                    f"{sysid}_controller_{address}_relay_{relay.index}",
                    partial(IconRelayBinarySensor, coordinator, relay),
                )
    yield from thermostat_candidates(
        coordinator, THERMOSTAT_BINARY_SENSORS, IconThermostatBinarySensor
    )


def relay_in_use(system: pyngbsicon.IconSystem, relay: pyngbsicon.Relay) -> bool:
    """Whether a relay output does anything in this installation.

    The factory configuration assigns a valve output to every thermostat slot; the
    valves of thermostats that are not installed (and are switched by nothing else)
    are left out.
    """
    if relay.kind is not pyngbsicon.RelayKind.VALVE:
        return True
    configured = system.configured_thermostats
    return any(
        ref.thermostat_id is None or ref.thermostat_id in configured
        for ref in relay.driven_by
    )


class IconSystemBinarySensor(IconSystemEntity, BinarySensorEntity):
    """A binary sensor of the system."""

    entity_description: IconSystemBinarySensorDescription

    @property
    def is_on(self) -> bool:
        """The current state."""
        return self.entity_description.value_fn(self.system)


class IconRelayBinarySensor(IconControllerEntity, BinarySensorEntity):
    """The physical state of a relay output."""

    def __init__(self, coordinator: IconCoordinator, relay: pyngbsicon.Relay) -> None:
        """Create the sensor of a relay."""
        super().__init__(
            coordinator,
            relay.controller,
            BinarySensorEntityDescription(
                key=f"relay_{relay.index}",
                device_class=BinarySensorDeviceClass.RUNNING,
            ),
        )
        self.relay_key = relay.key
        if relay.custom_name:
            self._attr_name = relay.name  # named by the installer
        elif relay.kind is pyngbsicon.RelayKind.VALVE:
            rooms = [
                coordinator.data.thermostats[thermostat_id].name
                for thermostat_id in relay.thermostat_ids
                if thermostat_id in coordinator.data.configured_thermostats
            ]
            placeholders = {"number": str(relay.index)}
            if len(rooms) == 1:
                placeholders["room"] = rooms[0]
            self._attr_translation_key = "valve_room" if len(rooms) == 1 else "valve"
            self._attr_translation_placeholders = placeholders
        else:
            self._attr_translation_key = _RELAY_TRANSLATION_KEYS[relay.kind]

    @property
    def is_on(self) -> bool | None:
        """Whether the relay output is switched on."""
        controller = self.controller
        if (
            controller is None
            or (relay := controller.relays.get(self.relay_key)) is None
        ):
            return None
        return relay.on


class IconThermostatBinarySensor(IconThermostatEntity, BinarySensorEntity):
    """A binary sensor of one thermostat."""

    entity_description: IconThermostatBinarySensorDescription

    def __init__(
        self, coordinator: IconCoordinator, thermostat_id: str, key: str
    ) -> None:
        """Create the sensor."""
        description = THERMOSTAT_BINARY_SENSORS[key]
        super().__init__(coordinator, thermostat_id, key, description)
        self._requires_live = description.requires_live

    @property
    def is_on(self) -> bool:
        """The current state."""
        return self.entity_description.value_fn(self.thermostat)
