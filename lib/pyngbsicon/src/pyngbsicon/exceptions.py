"""Exceptions raised by pyngbsicon."""

from __future__ import annotations


class IconError(Exception):
    """Base class of every error raised by this library."""


class IconConnectionError(IconError):
    """The controller could not be reached, or it did not answer in time."""


class IconProtocolError(IconError):
    """The controller answered with something that is not a valid protocol message."""


class IconAuthenticationError(IconError):
    """The controller rejected the request because the SYSID is wrong (``{"ERR": 1}``)."""


class IconUnsupportedError(IconError):
    """The controller does not support the request.

    Raised by SYSID discovery on firmware older than 1079, which only answers requests
    that already carry the SYSID; the SYSID then has to be supplied by the user.
    """


class IconRejectedError(IconError):
    """A write was not applied: the controller or thermostat kept the previous value.

    Thermostats reject setpoints outside their allowed range (values above it are
    clamped instead), and system-wide writes have no effect when the corresponding
    function is controlled from an external input.
    """

    def __init__(
        self, target: str, field: str, requested: object, actual: object
    ) -> None:
        """Describe which value was rejected."""
        super().__init__(
            f"{target}: {field}={requested!r} was not applied (still {actual!r})"
        )
        self.target = target
        self.field = field
        self.requested = requested
        self.actual = actual
