"""Asynchronous client for NGBS iCON heating/cooling controllers.

The library speaks the controller's local JSON-over-TCP service protocol (port 7992)
and has no runtime dependencies outside the Python standard library. It is written
for Home Assistant but is usable from any asyncio application and from the bundled
``pyngbsicon`` command line tool.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .client import IconClient
from .discovery import discover, is_icon_mac, probe
from .exceptions import (
    IconAuthenticationError,
    IconConnectionError,
    IconError,
    IconProtocolError,
    IconRejectedError,
    IconUnsupportedError,
)
from .models import (
    DiscoveredIcon,
    HeatCool,
    IconController,
    IconSystem,
    IconThermostat,
    Relay,
    RelayKind,
    SetpointKind,
    Setpoints,
    Signal,
    SignalFunction,
    SignalRef,
    SysidInfo,
)
from .protocol import parse_state

__all__ = [
    "DiscoveredIcon",
    "HeatCool",
    "IconAuthenticationError",
    "IconClient",
    "IconConnectionError",
    "IconController",
    "IconError",
    "IconProtocolError",
    "IconRejectedError",
    "IconSystem",
    "IconThermostat",
    "IconUnsupportedError",
    "Relay",
    "RelayKind",
    "SetpointKind",
    "Setpoints",
    "Signal",
    "SignalFunction",
    "SignalRef",
    "SysidInfo",
    "__version__",
    "discover",
    "is_icon_mac",
    "parse_state",
    "probe",
]
