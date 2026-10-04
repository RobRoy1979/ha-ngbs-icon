"""Shared helpers for the development scripts: repository paths and the local .env file."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Return the KEY=VALUE pairs of a .env file (empty dict when it does not exist).

    Only the simple subset used by this repository is supported: one assignment per
    line, ``#`` comments, optional surrounding quotes. No variable expansion.
    """
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def require(env: dict[str, str], *keys: str) -> list[str]:
    """Return the values of ``keys`` or exit with a message naming the missing ones."""
    missing = [key for key in keys if not env.get(key)]
    if missing:
        raise SystemExit(
            f"Missing {', '.join(missing)} in {ENV_FILE.name} (see .env.example)."
        )
    return [env[key] for key in keys]
