"""Sensor entities: temperatures, humidity, the mixing valve and diagnostics."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

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

SYSTEM_MODE_OPTIONS = ["heating", "cooling"]


@dataclass(frozen=True, kw_only=True)
class IconSystemSensorDescription(SensorEntityDescription):
    """A sensor of the system."""

    value_fn: Callable[[pyngbsicon.IconSystem], StateType]
    exists_fn: Callable[[pyngbsicon.IconSystem], bool] = lambda _: True


@dataclass(frozen=True, kw_only=True)
class IconControllerSensorDescription(SensorEntityDescription):
    """A sensor of one controller."""

    value_fn: Callable[[pyngbsicon.IconController], StateType]


@dataclass(frozen=True, kw_only=True)
class IconThermostatSensorDescription(SensorEntityDescription):
    """A sensor of one thermostat."""

    value_fn: Callable[[pyngbsicon.IconThermostat], StateType]


def _default_setpoint(kind: pyngbsicon.SetpointKind) -> IconSystemSensorDescription:
    return IconSystemSensorDescription(
        key=f"default_{kind.value}_setpoint",
        translation_key=f"default_{kind.value}_setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda system: system.default_setpoints.get(kind),
    )


SYSTEM_SENSORS: tuple[IconSystemSensorDescription, ...] = (
    IconSystemSensorDescription(
        key="water_temperature",
        translation_key="water_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda system: system.water_temp,
    ),
    IconSystemSensorDescription(
        key="outdoor_temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda system: system.outdoor_temp,
        # Created once a sensor reports; without one the controller sends an error
        # value and no fault signal.
        exists_fn=lambda system: (
            system.outdoor_temp is not None
            or pyngbsicon.Signal.OUTDOOR_SENSOR_FAULT in system.signals
        ),
    ),
    IconSystemSensorDescription(
        key="system_mode",
        translation_key="system_mode",
        device_class=SensorDeviceClass.ENUM,
        options=SYSTEM_MODE_OPTIONS,
        value_fn=lambda system: SYSTEM_MODE_OPTIONS[system.hc_mode],
        # Switched by an input or centrally: Home Assistant can only show the mode.
        exists_fn=lambda system: (
            system.has_config and system.hc_master_thermostat is None
        ),
    ),
    IconSystemSensorDescription(
        key="config_version",
        translation_key="config_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda system: system.config_version,
    ),
    IconSystemSensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda system: system.uptime,
        exists_fn=lambda system: system.uptime is not None,
    ),
    *(_default_setpoint(kind) for kind in pyngbsicon.SetpointKind),
)


CONTROLLER_SENSORS: tuple[IconControllerSensorDescription, ...] = (
    IconControllerSensorDescription(
        key="mixing_valve",
        translation_key="mixing_valve",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda controller: controller.mixing_valve,
    ),
    IconControllerSensorDescription(
        key="supply_voltage",
        translation_key="supply_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda controller: controller.supply_voltage,
    ),
    IconControllerSensorDescription(
        key="thermostat_bus_voltage",
        translation_key="thermostat_bus_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda controller: controller.thermostat_bus_voltage,
    ),
)

THERMOSTAT_SENSORS: dict[str, IconThermostatSensorDescription] = {
    description.key: description
    for description in (
        IconThermostatSensorDescription(
            key="temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=lambda thermostat: thermostat.temperature,
        ),
        IconThermostatSensorDescription(
            key="humidity",
            device_class=SensorDeviceClass.HUMIDITY,
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=lambda thermostat: thermostat.humidity,
        ),
        IconThermostatSensorDescription(
            key="dew_point",
            translation_key="dew_point",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=lambda thermostat: thermostat.dew_point,
        ),
    )
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the sensors; new ones are added when they appear."""
    async_add_dynamic_entities(entry, async_add_entities, _candidates)


def _candidates(coordinator: IconCoordinator) -> EntityCandidates:
    system = coordinator.data
    sysid = system.sysid
    for description in SYSTEM_SENSORS:
        if description.exists_fn(system):
            yield (
                f"{sysid}_{description.key}",
                partial(IconSystemSensor, coordinator, description),
            )
    for address, controller in system.controllers.items():
        for controller_description in CONTROLLER_SENSORS:
            if controller_description.value_fn(controller) is not None:
                yield (
                    f"{sysid}_controller_{address}_{controller_description.key}",
                    partial(
                        IconControllerSensor,
                        coordinator,
                        address,
                        controller_description,
                    ),
                )
    yield from thermostat_candidates(
        coordinator, THERMOSTAT_SENSORS, IconThermostatSensor
    )


class IconSystemSensor(IconSystemEntity, SensorEntity):
    """A sensor of the system."""

    entity_description: IconSystemSensorDescription

    @property
    def native_value(self) -> StateType:
        """The current value."""
        return self.entity_description.value_fn(self.system)


class IconControllerSensor(IconControllerEntity, SensorEntity):
    """A sensor of one controller."""

    entity_description: IconControllerSensorDescription

    @property
    def native_value(self) -> StateType:
        """The current value."""
        controller = self.controller
        return (
            None if controller is None else self.entity_description.value_fn(controller)
        )


class IconThermostatSensor(IconThermostatEntity, SensorEntity):
    """A sensor of one thermostat."""

    entity_description: IconThermostatSensorDescription

    def __init__(
        self, coordinator: IconCoordinator, thermostat_id: str, key: str
    ) -> None:
        """Create the sensor."""
        super().__init__(coordinator, thermostat_id, key, THERMOSTAT_SENSORS[key])

    @property
    def native_value(self) -> StateType:
        """The current value."""
        return self.entity_description.value_fn(self.thermostat)
