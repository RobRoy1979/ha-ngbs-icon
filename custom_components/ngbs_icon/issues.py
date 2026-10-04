"""Repair issues: conditions the user should know about and can act on."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from ._lib import pyngbsicon
from .const import DOMAIN
from .coordinator import IconConfigEntry

# The firmware that reveals the SYSID without it (needed for automatic discovery).
SYSID_DISCOVERY_FIRMWARE = 1079
THERMOSTAT_OFFLINE_AFTER = timedelta(hours=1)


def _issue_id(entry: IconConfigEntry, name: str, detail: str | None = None) -> str:
    return f"{name}_{entry.entry_id}" + ("" if detail is None else f"_{detail}")


@callback
def async_update_issues(
    hass: HomeAssistant, entry: IconConfigEntry, system: pyngbsicon.IconSystem
) -> None:
    """Create or remove the issues that follow from a polled state."""
    coordinator = entry.runtime_data

    firmware_issue = _issue_id(entry, "old_firmware")
    if system.firmware is not None and system.firmware < SYSID_DISCOVERY_FIRMWARE:
        ir.async_create_issue(
            hass,
            DOMAIN,
            firmware_issue,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="old_firmware",
            translation_placeholders={
                "title": entry.title,
                "firmware": str(system.firmware),
                "required": str(SYSID_DISCOVERY_FIRMWARE),
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, firmware_issue)

    if system.hc_master_thermostat is not None:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry, "hc_switch_external"))

    now = dt_util.utcnow()
    offline: set[str] = set()
    for thermostat_id, since in coordinator.offline_since.items():
        if now - since < THERMOSTAT_OFFLINE_AFTER:
            continue
        offline.add(thermostat_id)
        ir.async_create_issue(
            hass,
            DOMAIN,
            _issue_id(entry, "thermostat_offline", thermostat_id),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="thermostat_offline",
            translation_placeholders={
                "name": system.thermostats[thermostat_id].name,
                "id": thermostat_id,
                "title": entry.title,
            },
        )
    prefix = _issue_id(entry, "thermostat_offline", "")
    for issue_id in _entry_issue_ids(hass, entry):
        if issue_id.startswith(prefix) and issue_id[len(prefix) :] not in offline:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def async_create_hc_switch_external_issue(
    hass: HomeAssistant, entry: IconConfigEntry
) -> None:
    """Explain that heating/cooling is switched outside the thermostats.

    Raised when the user asks for a change the controller would ignore; it goes away
    when the configuration makes a thermostat the H/C master.
    """
    hc_master = entry.runtime_data.data.hc_master
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry, "hc_switch_external"),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="hc_switch_external",
        translation_placeholders={
            "title": entry.title,
            "source": str(hc_master) if hc_master else "?",
        },
    )


@callback
def async_create_duplicate_issue(
    hass: HomeAssistant, entry: IconConfigEntry, other: ConfigEntry[Any]
) -> None:
    """Point out that a migrated entry controls a system that is set up again."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry, "duplicate_system"),
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="duplicate_system",
        translation_placeholders={"title": entry.title, "other": other.title},
    )


@callback
def async_delete_issues(hass: HomeAssistant, entry: IconConfigEntry) -> None:
    """Remove every issue of a config entry (when it is removed)."""
    for issue_id in _entry_issue_ids(hass, entry):
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _entry_issue_ids(hass: HomeAssistant, entry: IconConfigEntry) -> list[str]:
    marker = f"_{entry.entry_id}"
    return [
        issue_id
        for domain, issue_id in ir.async_get(hass).issues
        if domain == DOMAIN and marker in issue_id
    ]
