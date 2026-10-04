"""Climate entities: one per thermostat."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    PRESET_COMFORT,
    PRESET_ECO,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from ._lib import pyngbsicon
from .const import DOMAIN
from .coordinator import IconConfigEntry, IconCoordinator
from .entity import (
    EntityCandidates,
    IconThermostatEntity,
    async_add_dynamic_entities,
    thermostat_candidates,
)
from .issues import async_create_hc_switch_external_issue
from .util import setpoint_range

PARALLEL_UPDATES = 1  # the controller serves one request at a time

_HVAC_MODES = {
    pyngbsicon.HeatCool.HEATING: HVACMode.HEAT,
    pyngbsicon.HeatCool.COOLING: HVACMode.COOL,
}

# Service field names of ngbs_icon.set_setpoints.
SETPOINT_FIELDS: Mapping[str, pyngbsicon.SetpointKind] = {
    "heating": pyngbsicon.SetpointKind.HEAT,
    "cooling": pyngbsicon.SetpointKind.COOL,
    "eco_heating": pyngbsicon.SetpointKind.ECO_HEAT,
    "eco_cooling": pyngbsicon.SetpointKind.ECO_COOL,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: IconConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a climate entity for every configured thermostat."""
    async_add_dynamic_entities(entry, async_add_entities, _candidates)


def _candidates(coordinator: IconCoordinator) -> EntityCandidates:
    return thermostat_candidates(coordinator, ["climate"], IconClimate)


class IconClimate(IconThermostatEntity, ClimateEntity):
    """A room thermostat.

    Only the system's H/C master thermostat can switch between heating and cooling;
    the others show the system's current mode as their only mode.
    """

    _attr_name = None
    _attr_translation_key = "thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS
    _attr_target_temperature_step = 0.5
    _attr_preset_modes = [PRESET_COMFORT, PRESET_ECO]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )

    def __init__(
        self, coordinator: IconCoordinator, thermostat_id: str, key: str = "climate"
    ) -> None:
        """Create the entity."""
        super().__init__(coordinator, thermostat_id, key)

    @property
    def current_temperature(self) -> float | None:
        """Measured room temperature."""
        return self.thermostat.temperature

    @property
    def current_humidity(self) -> float | None:
        """Measured relative humidity."""
        return self.thermostat.humidity

    @property
    def target_temperature(self) -> float | None:
        """The setpoint in effect (heating/cooling, comfort/ECO)."""
        return self.thermostat.active_setpoint

    @property
    def min_temp(self) -> float:
        """Lowest setpoint the thermostat accepts in the current mode."""
        return self._range()[0]

    @property
    def max_temp(self) -> float:
        """Highest setpoint the thermostat accepts in the current mode."""
        return self._range()[1]

    @property
    def hvac_mode(self) -> HVACMode:
        """Heating or cooling."""
        return _HVAC_MODES[self.thermostat.hc_mode]

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Both modes on the H/C master thermostat, otherwise the current one."""
        if self.thermostat.is_hc_master:
            return [HVACMode.HEAT, HVACMode.COOL]
        return [self.hvac_mode]

    @property
    def hvac_action(self) -> HVACAction:
        """Heating or cooling while the thermostat demands energy, otherwise idle."""
        thermostat = self.thermostat
        if not thermostat.output_on:
            return HVACAction.IDLE
        if thermostat.hc_mode is pyngbsicon.HeatCool.COOLING:
            return HVACAction.COOLING
        return HVACAction.HEATING

    @property
    def preset_mode(self) -> str:
        """Comfort or ECO."""
        return PRESET_ECO if self.thermostat.eco else PRESET_COMFORT

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The dew point and the thermostat's address in the system."""
        return {
            "dew_point": self.thermostat.dew_point,
            "thermostat_id": self.thermostat_id,
        }

    def _range(self) -> tuple[float, float]:
        thermostat = self.thermostat
        return setpoint_range(self.system, thermostat, thermostat.active_setpoint_kind)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Change the setpoint in effect (and the mode first, when one is given)."""
        if (mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(mode)
        # The service schema guarantees a temperature (no range support is declared).
        kind = self.thermostat.active_setpoint_kind
        value = round(float(kwargs[ATTR_TEMPERATURE]) * 2) / 2
        await self.coordinator.async_write(
            lambda client: client.set_setpoint(self.thermostat_id, kind, value)
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Switch between comfort and ECO."""
        eco = preset_mode == PRESET_ECO
        await self.coordinator.async_write(
            lambda client: client.set_eco(eco, self.thermostat_id)
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Switch the system between heating and cooling (H/C master only)."""
        if hvac_mode == self.hvac_mode:
            return
        if hvac_mode not in self.hvac_modes:
            master = self.system.hc_master_thermostat
            if master is None:
                async_create_hc_switch_external_issue(
                    self.hass, self.coordinator.config_entry
                )
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="hc_switch_external"
                )
            thermostat = self.system.thermostats.get(master)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="hc_switch_not_allowed",
                translation_placeholders={
                    "master": thermostat.name if thermostat else master
                },
            )
        mode = (
            pyngbsicon.HeatCool.COOLING
            if hvac_mode == HVACMode.COOL
            else pyngbsicon.HeatCool.HEATING
        )
        await self.coordinator.async_write(lambda client: client.set_hc_mode(mode))

    async def async_set_setpoints(self, **fields: float) -> None:
        """Write several setpoints in one request (ngbs_icon.set_setpoints)."""
        values: dict[pyngbsicon.SetpointKind, float] = {}
        for name, kind in SETPOINT_FIELDS.items():
            if (value := fields.get(name)) is None:
                continue
            low, high = setpoint_range(self.system, self.thermostat, kind)
            if not low <= value <= high:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="setpoint_out_of_range",
                    translation_placeholders={
                        "field": name,
                        "value": str(value),
                        "min": str(low),
                        "max": str(high),
                        "entity": self.entity_id,
                    },
                )
            values[kind] = round(value * 2) / 2
        if not values:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_setpoint"
            )
        await self.coordinator.async_write(
            lambda client: client.set_setpoints(
                self.thermostat_id,
                heat=values.get(pyngbsicon.SetpointKind.HEAT),
                cool=values.get(pyngbsicon.SetpointKind.COOL),
                eco_heat=values.get(pyngbsicon.SetpointKind.ECO_HEAT),
                eco_cool=values.get(pyngbsicon.SetpointKind.ECO_COOL),
            )
        )
