"""Pytest fixtures for the pyngbsicon tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
import contextlib
import threading

from icon_test_support import FakeIconServer, SimulatedController
import pytest


@pytest.fixture(autouse=True)
def _allow_local_sockets(request: pytest.FixtureRequest) -> None:
    """Allow sockets: these tests talk to fake controllers on 127.0.0.1.

    The Home Assistant test plugin blocks sockets (through pytest-socket) when the
    library tests run together with the integration tests; standalone runs have no
    such plugin.
    """
    with contextlib.suppress(pytest.FixtureLookupError):
        request.getfixturevalue("socket_enabled")


@pytest.fixture
def controller() -> SimulatedController:
    """A simulated controller with the recorded state."""
    return SimulatedController()


@pytest.fixture
async def server(controller: SimulatedController) -> AsyncIterator[FakeIconServer]:
    """A running fake server backed by the simulated controller."""
    fake = FakeIconServer(controller.handle)
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
def threaded_server(controller: SimulatedController) -> Iterator[FakeIconServer]:
    """A fake server running in its own thread, for synchronous code (the CLI)."""
    loop = asyncio.new_event_loop()
    fake = FakeIconServer(controller.handle)
    ready = threading.Event()

    def run() -> None:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(fake.start())
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(5)
    yield fake
    asyncio.run_coroutine_threadsafe(fake.stop(), loop).result(5)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)
    loop.close()
