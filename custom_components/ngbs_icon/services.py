"""Actions (services) of the integration, registered once in async_setup."""

from __future__ import annotations

from typing import cast

from homeassistant.components.climate.const import DOMAIN as CLIMATE_DOMAIN
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.typing import VolDictType
import voluptuous as vol

from ._lib import pyngbsicon
from .climate import SETPOINT_FIELDS
from .const import DOMAIN
from .coordinator import IconConfigEntry
from .issues import async_create_hc_switch_external_issue

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_MODE = "mode"

SERVICE_SET_SETPOINTS = "set_setpoints"
SERVICE_SET_SYSTEM_MODE = "set_system_mode"
SERVICE_RESTART_CONTROLLER = "restart_controller"

_MODES = {
    "heating": pyngbsicon.HeatCool.HEATING,
    "cooling": pyngbsicon.HeatCool.COOLING,
}

_ENTRY_SCHEMA: VolDictType = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}
_SETPOINTS_SCHEMA: VolDictType = {
    vol.Optional(name): vol.Coerce(float) for name in SETPOINT_FIELDS
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_SETPOINTS,
        entity_domain=CLIMATE_DOMAIN,
        schema=_SETPOINTS_SCHEMA,
        func="async_set_setpoints",
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SYSTEM_MODE,
        _async_set_system_mode,
        schema=vol.Schema({**_ENTRY_SCHEMA, vol.Required(ATTR_MODE): vol.In(_MODES)}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESTART_CONTROLLER,
        _async_restart_controller,
        schema=vol.Schema(_ENTRY_SCHEMA),
    )


def _entry(call: ServiceCall) -> IconConfigEntry:
    """Return the targeted system; it may be omitted when only one is set up."""
    return cast(
        IconConfigEntry,
        service.async_get_config_entry(
            call.hass, DOMAIN, call.data.get(ATTR_CONFIG_ENTRY_ID)
        ),
    )


async def _async_set_system_mode(call: ServiceCall) -> None:
    entry = _entry(call)
    coordinator = entry.runtime_data
    if coordinator.data.hc_master_thermostat is None:
        async_create_hc_switch_external_issue(call.hass, entry)
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="hc_switch_external"
        )
    mode = _MODES[call.data[ATTR_MODE]]
    await coordinator.async_write(lambda client: client.set_hc_mode(mode))


async def _async_restart_controller(call: ServiceCall) -> None:
    coordinator = _entry(call).runtime_data
    await coordinator.async_command(lambda client: client.restart())
