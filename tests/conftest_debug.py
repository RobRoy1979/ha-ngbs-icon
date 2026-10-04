"""Temporary: show where syrupy looks for snapshots on the CI runner."""

import os

import syrupy.extensions.base as base

_orig = base.AbstractSyrupyExtension.get_location.__func__


def _patched(cls, *, test_location, index):  # type: ignore[no-untyped-def]
    loc = _orig(cls, test_location=test_location, index=index)
    name = cls.get_snapshot_name(test_location=test_location, index=index)
    print(f"DEBUGSNAP file={test_location.filepath} loc={loc} exists={os.path.exists(loc)} name={name!r}", flush=True)
    return loc


base.AbstractSyrupyExtension.get_location = classmethod(_patched)
