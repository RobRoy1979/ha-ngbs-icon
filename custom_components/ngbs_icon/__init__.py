"""The NGBS iCON integration: local control of NGBS iCON heating/cooling systems."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.const import (
    CONF_HOST,
    CONF_IP_ADDRESS,
    CONF_MAC,
    CONF_SCAN_INTERVAL,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType

from ._lib import pyngbsicon
from .const import (
    CONF_SYSID,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MANUFACTURER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    MODEL_CONTROLLER,
)
from .coordinator import IconConfigEntry, IconCoordinator
from .entity import controller_identifier, master_address, thermostat_identifier
from .issues import (
    async_create_duplicate_issue,
    async_delete_issues,
    async_update_issues,
)
from .services import async_setup_services
from .util import entry_title

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_SYSID_RE = re.compile(r"\d{6,20}")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions (they work with every config entry of the domain)."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: IconConfigEntry) -> bool:
    """Connect to the controller and set up the platforms."""
    sysid = entry.data.get(CONF_SYSID)
    if not sysid:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="sysid_missing"
        )
    client = pyngbsicon.IconClient(entry.data[CONF_HOST], sysid)
    coordinator = IconCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    state = coordinator.data
    if state.mac and entry.data.get(CONF_MAC) != state.mac:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_MAC: state.mac}
        )

    @callback
    def on_update() -> None:
        # Devices first: a slave controller added later needs one for its entities.
        _register_controllers(hass, entry, coordinator.data)
        _remove_uninstalled_thermostats(hass, entry)

    on_update()
    entry.async_on_unload(coordinator.async_add_listener(on_update))
    async_update_issues(hass, entry, state)
    entry.async_on_unload(
        coordinator.async_add_poll_listener(
            lambda polled: async_update_issues(hass, entry, polled)
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IconConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: IconConfigEntry) -> None:
    """Remove the repair issues of a deleted config entry."""
    async_delete_issues(hass, entry)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: IconConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a device that is no longer part of the system."""
    return not device.identifiers & _current_identifiers(entry.runtime_data.data)


def _current_identifiers(system: pyngbsicon.IconSystem) -> set[tuple[str, str]]:
    master = master_address(system)
    identifiers = {controller_identifier(system.sysid, master, master)}
    identifiers.update(
        controller_identifier(system.sysid, address, master)
        for address in system.controllers
    )
    identifiers.update(
        thermostat_identifier(system.sysid, thermostat_id)
        for thermostat_id in system.configured_thermostats
    )
    return identifiers


@callback
def _remove_uninstalled_thermostats(
    hass: HomeAssistant, entry: IconConfigEntry
) -> None:
    """Remove the devices of thermostats the controller reports as not installed.

    A thermostat that is merely missing from an answer (for example behind a slave
    controller that does not respond) keeps its device and entity history.
    """
    system = entry.runtime_data.data
    registry = dr.async_get(hass)
    removed = False
    for thermostat_id, thermostat in system.thermostats.items():
        if thermostat.configured:
            continue
        device = registry.async_get_device_by_identifier(
            thermostat_identifier(system.sysid, thermostat_id), entry.entry_id
        )
        if device is not None:
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )
            removed = True
    if removed:
        # Start over, so the thermostat gets its entities again if it is reinstalled.
        hass.config_entries.async_schedule_reload(entry.entry_id)


def _register_controllers(
    hass: HomeAssistant, entry: IconConfigEntry, state: pyngbsicon.IconSystem
) -> None:
    """Register the controllers first, so thermostat devices can refer to them."""
    registry = dr.async_get(hass)
    master = master_address(state)
    master_device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={controller_identifier(state.sysid, master, master)},
        connections={(dr.CONNECTION_NETWORK_MAC, state.mac)} if state.mac else set(),
        manufacturer=MANUFACTURER,
        model=MODEL_CONTROLLER,
        name=state.name or DEFAULT_NAME,
        serial_number=state.sysid,
        sw_version=str(state.firmware) if state.firmware else None,
        configuration_url=f"http://{entry.data[CONF_HOST]}/",
    )
    for controller in state.controllers.values():
        if controller.is_master:
            continue
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={
                controller_identifier(state.sysid, controller.address, master)
            },
            manufacturer=MANUFACTURER,
            model=MODEL_CONTROLLER,
            name=f"{state.name or DEFAULT_NAME} {controller.address}",
            via_device_id=master_device.id,
        )


async def async_migrate_entry(hass: HomeAssistant, entry: IconConfigEntry) -> bool:
    """Migrate entries of older versions.

    Version 1 entries were created by an earlier community integration that used the
    same domain. Its host and SYSID are kept; its entities and devices are removed
    because this integration identifies them differently. (Home Assistant itself
    refuses entries of a newer version than this integration knows.)
    """
    if entry.version == 1:
        data: dict[str, Any] = dict(entry.data)
        host = str(data.get(CONF_IP_ADDRESS) or data.get(CONF_HOST) or "")
        stored = str(data.get("id") or "")
        sysid = stored if _SYSID_RE.fullmatch(stored) else ""
        title = entry.title
        mac: str | None = None
        if (state := await _async_read_system(host, sysid)) is not None:
            sysid, mac = state.sysid, state.mac
            if title in {host, DEFAULT_NAME}:
                title = entry_title(state.name)
        unique_id = entry.unique_id
        duplicate_of = None
        if sysid:
            other = hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, sysid)
            if other is None or other.entry_id == entry.entry_id:
                unique_id = sysid
            else:
                LOGGER.warning(
                    "The NGBS iCON system at %s is also set up as %s; remove one of them",
                    host,
                    other.title,
                )
                duplicate_of = other
        interval = entry.options.get(
            CONF_SCAN_INTERVAL, data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        try:
            interval = int(interval)
        except TypeError, ValueError:
            interval = DEFAULT_SCAN_INTERVAL
        interval = max(MIN_SCAN_INTERVAL, min(MAX_SCAN_INTERVAL, interval))

        _remove_entities_and_devices(hass, entry)
        hass.config_entries.async_update_entry(
            entry,
            data={CONF_HOST: host, CONF_SYSID: sysid, CONF_MAC: mac},
            options={CONF_SCAN_INTERVAL: interval},
            unique_id=unique_id,
            title=DEFAULT_NAME if title == host else title,
            version=2,
            minor_version=1,
        )
        if duplicate_of is not None:
            async_create_duplicate_issue(hass, entry, duplicate_of)
        LOGGER.info(
            "Migrated the NGBS iCON entry for %s from version 1%s",
            host,
            "" if sysid else "; the SYSID has to be entered",
        )
    return True


async def _async_read_system(host: str, sysid: str) -> pyngbsicon.IconSystem | None:
    """Read the system (the client discovers the SYSID when it is not known)."""
    if not host:
        return None
    try:
        return await pyngbsicon.IconClient(host, sysid or None).get_state()
    except pyngbsicon.IconError as err:
        LOGGER.warning(
            "Could not read the NGBS iCON system at %s during migration: %s", host, err
        )
        return None


def _remove_entities_and_devices(hass: HomeAssistant, entry: IconConfigEntry) -> None:
    entities = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entities, entry.entry_id):
        entities.async_remove(entity.entity_id)
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        devices.async_update_device(device.id, remove_config_entry_id=entry.entry_id)
