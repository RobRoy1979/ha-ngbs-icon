"""Asynchronous client for NGBS iCON heating/cooling controllers.

The library speaks the controller's local JSON-over-TCP service protocol (port 7992)
and has no runtime dependencies outside the Python standard library. It is written
for Home Assistant but is usable from any asyncio application and from the bundled
``pyngbsicon`` command line tool.
"""

from __future__ import annotations

__version__ = "0.1.0.dev0"

__all__ = ["__version__"]
