"""Helpers shared by the config flow, the setup and the platforms."""

from __future__ import annotations

from ._lib import pyngbsicon
from .const import DEFAULT_NAME

# Absolute setpoint limits; a thermostat narrows them to the default setpoint ± LIM.
SETPOINT_MIN = 5.0
SETPOINT_MAX = 35.0


def entry_title(building: str | None) -> str:
    """Title of a config entry: the building name configured in the controller."""
    return f"{DEFAULT_NAME} ({building})" if building else DEFAULT_NAME


def setpoint_range(
    system: pyngbsicon.IconSystem,
    thermostat: pyngbsicon.IconThermostat,
    kind: pyngbsicon.SetpointKind,
) -> tuple[float, float]:
    """Return the range a thermostat accepts for one of its setpoints.

    The thermostat clamps a setpoint to the system default of the same kind ± its
    limit (``LIM``); outside the absolute range it may discard the value.
    """
    centre = system.default_setpoints.get(kind)
    if centre is None or thermostat.limit is None:
        return SETPOINT_MIN, SETPOINT_MAX
    return (
        max(SETPOINT_MIN, centre - thermostat.limit),
        min(SETPOINT_MAX, centre + thermostat.limit),
    )
