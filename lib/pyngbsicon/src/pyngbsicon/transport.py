"""One request over one TCP connection - the controller's framing."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json

from .exceptions import IconConnectionError

_READ_CHUNK = 65536


async def exchange(
    host: str,
    port: int,
    data: bytes,
    *,
    timeout: float,
    connect_timeout: float | None = None,
) -> bytes:
    """Send ``data`` on a fresh connection and return the raw answer.

    The controller answers with one JSON object followed by a newline and then closes
    the connection; reading stops as soon as a complete object has arrived, so a slow
    connection close does not add latency. An empty result means the controller
    closed the connection without answering.
    """
    try:
        async with asyncio.timeout(connect_timeout or timeout):
            reader, writer = await asyncio.open_connection(host, port)
    except TimeoutError as err:
        raise IconConnectionError(
            f"{host}:{port} did not accept a connection within {connect_timeout or timeout:g} s"
        ) from err
    except OSError as err:
        raise IconConnectionError(
            f"cannot connect to {host}:{port}: {err.strerror or err}"
        ) from err

    try:
        async with asyncio.timeout(timeout):
            writer.write(data)
            await writer.drain()
            return await _read_answer(reader)
    except TimeoutError as err:
        raise IconConnectionError(
            f"{host}:{port} did not answer within {timeout:g} s"
        ) from err
    except OSError as err:
        raise IconConnectionError(
            f"connection to {host}:{port} failed: {err.strerror or err}"
        ) from err
    finally:
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()


async def _read_answer(reader: asyncio.StreamReader) -> bytes:
    buffer = bytearray()
    while True:
        try:
            chunk = await reader.read(_READ_CHUNK)
        except ConnectionResetError:
            if buffer:
                break
            raise
        if not chunk:
            break
        buffer += chunk
        if buffer.rstrip().endswith(b"}") and _is_complete(buffer):
            break
    return bytes(buffer)


def _is_complete(buffer: bytearray) -> bool:
    """Tell whether the buffer holds a complete JSON document (quirks tolerated)."""
    try:
        json.loads(buffer)
    except ValueError:
        # Firmware quirks (e.g. leading zeros) make strict parsing fail; such answers
        # are read until the controller closes the connection instead.
        return False
    return True
