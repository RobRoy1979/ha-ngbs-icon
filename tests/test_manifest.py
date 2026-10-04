"""Home Assistant picks up the manifest's discovery matchers."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_dhcp

from custom_components.ngbs_icon.const import DOMAIN
from pyngbsicon.discovery import MAC_PREFIXES


async def test_dhcp_matchers_are_loaded(hass: HomeAssistant) -> None:
    matchers = [m for m in await async_get_dhcp(hass) if m["domain"] == DOMAIN]
    prefixes = {m["macaddress"] for m in matchers if "macaddress" in m}
    # The same ranges the library's network scan accepts.
    assert prefixes == {f"{prefix.upper()}*" for prefix in MAC_PREFIXES}
    assert {"domain": DOMAIN, "registered_devices": True} in matchers
