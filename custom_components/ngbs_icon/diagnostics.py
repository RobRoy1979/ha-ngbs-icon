"""Diagnostics: the controller's answer and the integration's state, without secrets."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import HomeAssistant

from ._lib import pyngbsicon
from .const import CONF_SYSID
from .coordinator import IconConfigEntry

# The SYSID is the web interface's default password; network details and the
# e-mail address identify the installation. The controller's answer never contains
# the password field itself (the library drops it).
TO_REDACT_ENTRY = {CONF_HOST, CONF_MAC, CONF_SYSID, "unique_id", "title"}
TO_REDACT_STATE = {
    "SYSID",
    "KEY",
    "EMAIL",
    "MAC",
    "NET",
    "NETL",
    "eth0",
    "eth0:1",
    "tun0",
    "IP",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: IconConfigEntry
) -> dict[str, Any]:
    """Return the diagnostics of a config entry."""
    coordinator = entry.runtime_data
    # The last state may come from a write, which does not repeat the configuration
    # (relay matrix, names); ask for a complete one.
    try:
        system = await coordinator.client.get_state(include_config=True)
        fresh_error = None
    except pyngbsicon.IconError as err:
        system = coordinator.data
        fresh_error = f"{type(err).__name__}: {err}"
    state = async_redact_data(dict(system.raw), TO_REDACT_STATE)
    if isinstance(state.get("CFG"), dict) and "NAME" in state["CFG"]:
        # The building name may be a family name.
        state["CFG"] = {**state["CFG"], "NAME": "**REDACTED**"}
    return {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "version": entry.version,
                "minor_version": entry.minor_version,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT_ENTRY,
        ),
        "library_version": pyngbsicon.__version__,
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "statistics": _scrub(
                {
                    **asdict(coordinator.statistics),
                    "diagnostics_read_error": fresh_error,
                },
                [entry.data.get(CONF_HOST), entry.data.get(CONF_SYSID)],
            ),
            "offline_thermostats": {
                thermostat_id: since.isoformat()
                for thermostat_id, since in coordinator.offline_since.items()
            },
        },
        "system": {
            "firmware": system.firmware,
            "controllers": sorted(system.controllers),
            "thermostats": sorted(system.configured_thermostats),
            "hc_master": str(system.hc_master) if system.hc_master else None,
            "eco_master": str(system.eco_master) if system.eco_master else None,
        },
        "state": state,
    }


def _scrub(data: dict[str, Any], secrets: list[str | None]) -> dict[str, Any]:
    """Hide the address and the SYSID that error messages may quote."""
    result = dict(data)
    for key in ("last_error", "diagnostics_read_error"):
        if isinstance(message := result.get(key), str):
            for secret in filter(None, secrets):
                message = message.replace(secret, "**REDACTED**")
            result[key] = message
    return result
