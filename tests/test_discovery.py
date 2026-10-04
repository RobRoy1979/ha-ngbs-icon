"""Scanning the networks Home Assistant is connected to."""

from __future__ import annotations

import ipaddress
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant

from custom_components.ngbs_icon.discovery import async_scan

from .conftest import found

LINK_LOCAL = "169.254.3.4"  # allow-secret: skipped like loopback


def _adapter(*addresses: tuple[str, int], enabled: bool = True) -> dict[str, Any]:
    return {
        "name": "eth0",
        "index": 1,
        "enabled": enabled,
        "auto": True,
        "default": True,
        "ipv6": [],
        "ipv4": [{"address": a, "network_prefix": p} for a, p in addresses],
    }


async def test_scan_networks(hass: HomeAssistant) -> None:
    adapters = [
        _adapter(("192.0.2.5", 24), ("127.0.0.1", 8), (LINK_LOCAL, 16)),
        _adapter(("198.51.100.7", 16)),  # narrowed to the /24 around the address
        _adapter(("203.0.113.9", 24), enabled=False),
    ]
    with (
        patch(
            "homeassistant.components.network.async_get_adapters",
            AsyncMock(return_value=adapters),
        ),
        patch("pyngbsicon.discover", AsyncMock(return_value=[found()])) as discover,
    ):
        assert await async_scan(hass) == [found()]
    discover.assert_awaited_once_with(
        [
            ipaddress.IPv4Network("192.0.2.0/24"),
            ipaddress.IPv4Network("198.51.100.0/24"),
        ]
    )


async def test_scan_without_networks(hass: HomeAssistant) -> None:
    with (
        patch(
            "homeassistant.components.network.async_get_adapters",
            AsyncMock(return_value=[_adapter(("127.0.0.1", 8))]),
        ),
        patch("pyngbsicon.discover", AsyncMock()) as discover,
    ):
        assert await async_scan(hass) == []
    discover.assert_not_called()
