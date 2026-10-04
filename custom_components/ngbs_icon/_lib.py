"""Access to the pyngbsicon protocol library.

The integration prefers an installed pyngbsicon (from PyPI, declared in the manifest
once it is published). Release packages also bundle a copy in ``_vendor`` so the
integration works on installations that cannot install packages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pyngbsicon
else:
    try:
        import pyngbsicon
    except ImportError:  # pragma: no cover - only in the packaged integration
        from ._vendor import pyngbsicon

__all__ = ["pyngbsicon"]
