"""Scanning the networks Home Assistant is connected to for iCON controllers."""

from __future__ import annotations

import ipaddress

from homeassistant.components import network
from homeassistant.core import HomeAssistant

from ._lib import pyngbsicon
from .const import LOGGER

# Larger networks are narrowed to the /24 around Home Assistant's own address, which
# keeps a scan to a few seconds; controllers elsewhere can be added by address.
_SMALLEST_PREFIX = 24


async def async_scan(hass: HomeAssistant) -> list[pyngbsicon.DiscoveredIcon]:
    """Return the controllers found on the enabled IPv4 networks."""
    networks: set[ipaddress.IPv4Network] = set()
    for adapter in await network.async_get_adapters(hass):
        if not adapter["enabled"]:
            continue
        for address in adapter["ipv4"]:
            ip = ipaddress.IPv4Address(address["address"])
            if ip.is_loopback or ip.is_link_local:
                continue
            prefix = max(address["network_prefix"], _SMALLEST_PREFIX)
            networks.add(ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False))
    if not networks:
        return []
    LOGGER.debug(
        "Scanning %s for iCON controllers", ", ".join(map(str, sorted(networks)))
    )
    return await pyngbsicon.discover(sorted(networks))
