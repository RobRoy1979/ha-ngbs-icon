"""Protocol constants."""

from __future__ import annotations

from typing import Final

DEFAULT_PORT: Final = 7992
"""TCP port of the controller's JSON service protocol."""

DEFAULT_TIMEOUT: Final = 3.0
"""Seconds allowed for connecting, sending a request and receiving its answer."""

SENSOR_FAULT: Final = 222
"""Temperature value the controller reports for a missing or faulty sensor."""

SETPOINT_MIN: Final = 5.0
SETPOINT_MAX: Final = 35.0
SETPOINT_STEP: Final = 0.5
"""Setpoint limits accepted by this library; thermostats may restrict them further."""

MAX_CONTROLLERS: Final = 8
"""One master and up to seven slave controllers form a system."""

MAX_THERMOSTATS: Final = 8
"""Thermostats per controller."""

SYSID_DISCOVERY_FIRMWARE: Final = 1079
"""First firmware version that reveals its SYSID without being given one."""

# A write is applied by the controller at once, but the thermostat first reports its
# previous state (for about a second) before it takes over - and possibly clamps or
# rounds - the new value. Writes are therefore confirmed by reading the state until
# it is stable after SETTLE_MIN seconds.
SETTLE_MIN: Final = 2.0
SETTLE_POLL_INTERVAL: Final = 0.5
SETTLE_TIMEOUT: Final = 8.0

# Request codes of the "RELOAD" field.
RELOAD_CONFIG: Final = ""
"""Full state including the configuration (``CFG``)."""
RELOAD_FIRMWARE_UPDATE: Final = 7
RELOAD_SYSID: Final = 6
RELOAD_RESTART: Final = 8
