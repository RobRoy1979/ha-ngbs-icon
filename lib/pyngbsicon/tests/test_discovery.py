"""Finding controllers on the network."""

from __future__ import annotations

import ipaddress

from icon_test_support import SYSID, FakeIconServer, SimulatedController
import pytest

from pyngbsicon import DiscoveredIcon, discover, is_icon_mac, probe
from pyngbsicon.discovery import hosts_of


async def test_probe_finds_controller(server: FakeIconServer) -> None:
    found = await probe("127.0.0.1", port=server.port)
    assert found == DiscoveredIcon(
        host="127.0.0.1", sysid=SYSID, firmware=1079, controllers=1, needs_sysid=False
    )


async def test_probe_old_firmware(
    server: FakeIconServer, controller: SimulatedController
) -> None:
    controller.firmware_reveals_sysid = False
    found = await probe("127.0.0.1", port=server.port)
    assert found is not None and found.needs_sysid and found.sysid is None


@pytest.mark.parametrize(
    "answer",
    [
        b"HTTP/1.1 400 Bad Request\r\n\r\n",
        b'{"SYSID": "not-a-number"}\n',
        b'{"hello": "world"}\n',
        b"[1, 2, 3]\n",
        None,
    ],
)
async def test_probe_ignores_other_services(answer: bytes | None) -> None:
    other = FakeIconServer(lambda request: answer)
    await other.start()
    try:
        assert await probe("127.0.0.1", port=other.port, request_timeout=0.5) is None
    finally:
        await other.stop()


async def test_probe_closed_port() -> None:
    gone = FakeIconServer(lambda request: None)
    await gone.start()
    port = gone.port
    await gone.stop()
    assert await probe("127.0.0.1", port=port) is None


async def test_discover(server: FakeIconServer) -> None:
    found = await discover(
        ["127.0.0.1/32", ipaddress.IPv4Address("127.0.0.1")], port=server.port
    )
    assert [item.sysid for item in found] == [SYSID]  # de-duplicated


def test_hosts_of() -> None:
    assert hosts_of(["192.0.2.0/30"]) == ["192.0.2.1", "192.0.2.2"]
    assert hosts_of(
        ["192.0.2.5", "192.0.2.5/32", ipaddress.IPv4Network("192.0.2.4/31")]
    ) == [
        "192.0.2.5",
        "192.0.2.4",
    ]
    with pytest.raises(ValueError, match="more than 1024"):
        hosts_of(["10.0.0.0/16"])  # synthetic; allow-secret
    with pytest.raises(ValueError):
        hosts_of(["not an address"])


@pytest.mark.parametrize(
    ("mac", "expected"),
    [
        ("E4:95:6E:50:00:01", True),  # synthetic; allow-secret
        ("e4-95-6e-5a-bc-de", True),  # synthetic; allow-secret
        ("0050C2FDA123", True),
        ("40:d8:55:0d:2f:00", True),  # synthetic; allow-secret
        ("66:55:44:00:01:02", True),  # synthetic; allow-secret
        ("E4:95:6E:40:00:01", False),  # synthetic; allow-secret
        ("02:00:00:00:00:01", False),
        ("E4:95:6E", False),
    ],
)
def test_is_icon_mac(mac: str, expected: bool) -> None:
    assert is_icon_mac(mac) is expected
