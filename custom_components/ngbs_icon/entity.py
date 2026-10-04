"""Base classes of the NGBS iCON entities."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._lib import pyngbsicon
from .const import DOMAIN, MANUFACTURER, MODEL_THERMOSTAT
from .coordinator import IconCoordinator


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


class IconEntity(CoordinatorEntity[IconCoordinator]):
    """An entity backed by the system coordinator."""

    _attr_has_entity_name = True


class IconThermostatEntity(IconEntity):
    """An entity of one thermostat; it has its own device."""

    def __init__(
        self, coordinator: IconCoordinator, thermostat_id: str, key: str
    ) -> None:
        """Bind the entity to a thermostat."""
        super().__init__(coordinator)
        state = coordinator.data
        thermostat = state.thermostats[thermostat_id]
        master = state.master
        self.thermostat_id = thermostat_id
        self._thermostat = thermostat
        self._attr_unique_id = f"{state.sysid}_{thermostat_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={thermostat_identifier(state.sysid, thermostat_id)},
            name=thermostat.name,
            manufacturer=MANUFACTURER,
            model=MODEL_THERMOSTAT,
            via_device_id=dr.async_get_device_id_by_identifier(
                coordinator.hass,
                controller_identifier(
                    state.sysid, thermostat.controller, master.address if master else 1
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
        return super().available and current is not None and current.available
