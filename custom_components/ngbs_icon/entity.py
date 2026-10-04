"""Base classes of the NGBS iCON entities and dynamic entity creation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial

from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._lib import pyngbsicon
from .const import DOMAIN, MANUFACTURER, MODEL_THERMOSTAT
from .coordinator import IconConfigEntry, IconCoordinator

type EntityCandidates = Iterable[tuple[str, Callable[[], Entity]]]
"""Entities that should exist, as (unique ID, factory) pairs."""


def controller_identifier(
    sysid: str, address: int, master_address: int
) -> tuple[str, str]:
    """Device registry identifier of a controller (the master is the system device)."""
    if address == master_address:
        return (DOMAIN, sysid)
    return (DOMAIN, f"{sysid}-controller-{address}")


def thermostat_identifier(sysid: str, thermostat_id: str) -> tuple[str, str]:
    """Device registry identifier of a thermostat."""
    return (DOMAIN, f"{sysid}-{thermostat_id}")


def master_address(system: pyngbsicon.IconSystem) -> int:
    """Address of the master controller (1 unless the configuration says otherwise)."""
    master = system.master
    return master.address if master else 1


@callback
def async_add_dynamic_entities(
    entry: IconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    candidates: Callable[[IconCoordinator], EntityCandidates],
) -> None:
    """Add the entities that should exist now, and those that appear later.

    A thermostat installed in the controller, or a sensor connected later, gets its
    entities at the next poll without reloading the integration.
    """
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def add_new() -> None:
        new: list[Entity] = []
        for unique_id, factory in candidates(coordinator):
            if unique_id not in known:
                known.add(unique_id)
                new.append(factory())
        if new:
            async_add_entities(new)

    add_new()
    entry.async_on_unload(coordinator.async_add_listener(add_new))


def thermostat_candidates(
    coordinator: IconCoordinator,
    keys: Iterable[str],
    factory: Callable[[IconCoordinator, str, str], Entity],
) -> EntityCandidates:
    """Candidates for one entity per key on every configured thermostat."""
    sysid = coordinator.data.sysid
    keys = tuple(keys)
    for thermostat_id in coordinator.data.configured_thermostats:
        for key in keys:
            yield (
                f"{sysid}_{thermostat_id}_{key}",
                partial(factory, coordinator, thermostat_id, key),
            )


class IconEntity(CoordinatorEntity[IconCoordinator]):
    """An entity backed by the system coordinator."""

    _attr_has_entity_name = True

    @property
    def system(self) -> pyngbsicon.IconSystem:
        """The current state of the whole system."""
        return self.coordinator.data


class IconSystemEntity(IconEntity):
    """An entity of the system; it belongs to the master controller's device."""

    def __init__(
        self, coordinator: IconCoordinator, description: EntityDescription
    ) -> None:
        """Bind the entity to the system device."""
        super().__init__(coordinator)
        self.entity_description = description
        sysid = coordinator.data.sysid
        self._attr_unique_id = f"{sysid}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, sysid)})


class IconControllerEntity(IconEntity):
    """An entity of one controller (relays, mixing valve, supply voltages)."""

    def __init__(
        self,
        coordinator: IconCoordinator,
        address: int,
        description: EntityDescription,
        key: str | None = None,
    ) -> None:
        """Bind the entity to a controller's device."""
        super().__init__(coordinator)
        self.entity_description = description
        self.address = address
        system = coordinator.data
        self._attr_unique_id = (
            f"{system.sysid}_controller_{address}_{key or description.key}"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={
                controller_identifier(system.sysid, address, master_address(system))
            }
        )

    @property
    def controller(self) -> pyngbsicon.IconController | None:
        """The current state of the controller."""
        return self.coordinator.data.controllers.get(self.address)

    @property
    def available(self) -> bool:
        """Available while the controller is part of the answer."""
        return super().available and self.controller is not None


class IconThermostatEntity(IconEntity):
    """An entity of one thermostat; it has its own device."""

    _requires_live = True
    """Unavailable while the thermostat does not communicate (except its link state)."""

    def __init__(
        self,
        coordinator: IconCoordinator,
        thermostat_id: str,
        key: str,
        description: EntityDescription | None = None,
    ) -> None:
        """Bind the entity to a thermostat."""
        super().__init__(coordinator)
        if description is not None:
            self.entity_description = description
        system = coordinator.data
        thermostat = system.thermostats[thermostat_id]
        self.thermostat_id = thermostat_id
        self._thermostat = thermostat
        self._attr_unique_id = f"{system.sysid}_{thermostat_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={thermostat_identifier(system.sysid, thermostat_id)},
            name=thermostat.name,
            manufacturer=MANUFACTURER,
            model=MODEL_THERMOSTAT,
            via_device_id=dr.async_get_device_id_by_identifier(
                coordinator.hass,
                controller_identifier(
                    system.sysid, thermostat.controller, master_address(system)
                ),
                config_entry_id=coordinator.config_entry.entry_id,
            ),
        )

    @property
    def thermostat(self) -> pyngbsicon.IconThermostat:
        """The latest known state of the thermostat.

        Kept when the thermostat disappears from the answer, because Home Assistant
        reads the capability attributes of unavailable entities too.
        """
        if (
            current := self.coordinator.data.thermostats.get(self.thermostat_id)
        ) is not None:
            self._thermostat = current
        return self._thermostat

    @property
    def available(self) -> bool:
        """Available while the controller answers and the thermostat communicates."""
        current = self.coordinator.data.thermostats.get(self.thermostat_id)
        if not super().available or current is None or not current.configured:
            return False
        return current.live or not self._requires_live
