"""Finding iCON controllers on the local network."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
import ipaddress
import re

from .const import DEFAULT_PORT, RELOAD_SYSID
from .exceptions import IconError
from .models import DiscoveredIcon
from .protocol import decode, encode, is_auth_error
from .transport import exchange

DEFAULT_CONCURRENCY = 64
DEFAULT_CONNECT_TIMEOUT = 0.4
DEFAULT_REQUEST_TIMEOUT = 1.5
DEFAULT_MAX_HOSTS = 1024

# Address blocks of iCON controllers (IEEE IAB / MA-S blocks of the hardware maker and
# a locally administered block of very old units), as lower-case hex prefixes.
MAC_PREFIXES = (
    "e4956e5",
    "0050c2fda",
    "0050c2f27",
    "0050c2de7",
    "40d8550d2",
    "6655440",
)


def is_icon_mac(mac: str) -> bool:
    """Tell whether a MAC address (any common notation) belongs to an iCON controller."""
    digits = re.sub(r"[^0-9a-f]", "", mac.lower())
    return len(digits) == 12 and digits.startswith(MAC_PREFIXES)


async def probe(
    host: str,
    *,
    port: int = DEFAULT_PORT,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> DiscoveredIcon | None:
    """Ask ``host`` for its SYSID; return ``None`` unless it is an iCON controller.

    A controller with firmware older than 1079 answers with an error instead of its
    SYSID; it is still reported, with ``needs_sysid`` set.
    """
    try:
        raw = await exchange(
            host,
            port,
            encode({"RELOAD": RELOAD_SYSID}),
            timeout=request_timeout,
            connect_timeout=connect_timeout,
        )
        answer = decode(raw)
    except IconError:
        return None
    if is_auth_error(answer):
        return DiscoveredIcon(
            host=host, sysid=None, firmware=None, controllers=0, needs_sysid=True
        )
    sysid = answer.get("SYSID")
    if not isinstance(sysid, str) or not re.fullmatch(r"\d{6,20}", sysid):
        return None
    controllers = sorted(
        (int(match[1]), value)
        for key, value in answer.items()
        if (match := re.fullmatch(r"ICON(\d+)", key)) and isinstance(value, dict)
    )
    firmware = controllers[0][1].get("FIRMWARE") if controllers else None
    return DiscoveredIcon(
        host=host,
        sysid=sysid,
        firmware=firmware if isinstance(firmware, int) else None,
        controllers=len(controllers),
        needs_sysid=False,
    )


def hosts_of(
    networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv4Address | str],
    *,
    max_hosts: int = DEFAULT_MAX_HOSTS,
) -> list[str]:
    """Expand networks and addresses into a de-duplicated list of host addresses.

    Raises ``ValueError`` when the networks contain more than ``max_hosts`` hosts, so a
    mistyped ``/8`` does not start a scan of millions of addresses.
    """
    hosts: dict[str, None] = {}
    for item in networks:
        network = ipaddress.IPv4Network(item, strict=False)
        addresses = (
            [network.network_address] if network.num_addresses == 1 else network.hosts()
        )
        for address in addresses:
            hosts[str(address)] = None
            if len(hosts) > max_hosts:
                raise ValueError(f"more than {max_hosts} addresses to scan")
    return list(hosts)


async def discover(
    networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv4Address | str],
    *,
    port: int = DEFAULT_PORT,
    concurrency: int = DEFAULT_CONCURRENCY,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    max_hosts: int = DEFAULT_MAX_HOSTS,
) -> list[DiscoveredIcon]:
    """Scan networks for iCON controllers; results are sorted by address."""
    hosts = hosts_of(networks, max_hosts=max_hosts)
    semaphore = asyncio.Semaphore(concurrency)

    async def limited(host: str) -> DiscoveredIcon | None:
        async with semaphore:
            return await probe(
                host,
                port=port,
                connect_timeout=connect_timeout,
                request_timeout=request_timeout,
            )

    results = await asyncio.gather(*(limited(host) for host in hosts))
    found = [result for result in results if result is not None]
    return sorted(found, key=lambda item: ipaddress.IPv4Address(item.host))
