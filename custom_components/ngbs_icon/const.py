"""Constants of the NGBS iCON integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "ngbs_icon"
LOGGER = logging.getLogger(__package__)

CONF_SYSID: Final = "sysid"

DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 300

MANUFACTURER: Final = "NGBS Hungary"
MODEL_CONTROLLER: Final = "iCON controller"
MODEL_THERMOSTAT: Final = "iCON thermostat"

DEFAULT_NAME: Final = "NGBS iCON"


def entry_title(building: str | None) -> str:
    """Title of a config entry: the building name configured in the controller."""
    return f"{DEFAULT_NAME} ({building})" if building else DEFAULT_NAME
