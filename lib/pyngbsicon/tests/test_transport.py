"""Failure modes of the one-request-per-connection transport."""

from __future__ import annotations

import asyncio
import socket
import struct
from typing import Any

import pytest

from pyngbsicon import IconConnectionError
from pyngbsicon.transport import exchange


async def _server(handler: Any) -> tuple[asyncio.Server, int]:
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    return server, int(server.sockets[0].getsockname()[1])


def _abort(writer: asyncio.StreamWriter) -> None:
    """Close with a TCP reset instead of an orderly shutdown."""
    sock = writer.get_extra_info("socket")
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    writer.transport.abort()


async def test_reset_before_answer_is_a_connection_error() -> None:
    async def handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.read(100)
        _abort(writer)

    server, port = await _server(handler)
    try:
        with pytest.raises(IconConnectionError, match="failed"):
            await exchange("127.0.0.1", port, b'{"RELOAD":6}', timeout=1)
    finally:
        server.close()
        await server.wait_closed()


async def test_reset_after_partial_answer_returns_what_arrived() -> None:
    async def handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.read(100)
        writer.write(b'{"SYSID":')
        await writer.drain()
        await asyncio.sleep(0.05)
        _abort(writer)

    server, port = await _server(handler)
    try:
        assert (
            await exchange("127.0.0.1", port, b'{"RELOAD":6}', timeout=1)
            == b'{"SYSID":'
        )
    finally:
        server.close()
        await server.wait_closed()


async def test_connect_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def never_connects(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(5)

    monkeypatch.setattr(asyncio, "open_connection", never_connects)
    with pytest.raises(
        IconConnectionError, match="did not accept a connection within 0.1 s"
    ):
        await exchange("192.0.2.1", 7992, b"{}", timeout=1, connect_timeout=0.1)
