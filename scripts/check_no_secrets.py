"""Fail if a file contains identifiers of a real installation.

The repository is public, so it must never contain a real controller's SYSID (which is
also the default password of its web interface), a real MAC address, a LAN address or a
Home Assistant login. Checked:

* every value of the local, git-ignored ``.env`` (controller host and SYSID, Home
  Assistant URL host and passwords) - so this file itself names no secret;
* full six-byte MAC addresses outside the anonymised ``02:00:00:...`` range;
* twelve-digit numbers (SYSID shape) other than the anonymised ``123456789012``;
* private IPv4 addresses (RFC 1918); documentation ranges (RFC 5737) are fine.

A line can opt out with an ``allow-secret`` marker when a match is intentional.

Usage::

    python3 scripts/check_no_secrets.py FILE...   # pre-commit passes the staged files
    python3 scripts/check_no_secrets.py --all     # every tracked or untracked, not ignored file
"""

from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devenv import REPO_ROOT, load_env

ANONYMOUS_SYSID = "123456789012"
EXCLUDED_PREFIXES = ("docs/reference/", "lib/pyngbsicon/tests/fixtures/raw/", ".git/")
EXCLUDED_FILES = {".env"}
ALLOW_MARKER = "allow-secret"

MAC_RE = re.compile(
    r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])"
)
SYSID_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")
URL_RE = re.compile(r"https?://\S+")
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
SECRET_ENV_SUFFIXES = ("_HOST", "_SYSID", "_PASSWORD")


def _env_secrets() -> list[str]:
    """Collect the literal values from .env that must not appear anywhere."""
    secrets: set[str] = set()
    for key, value in load_env().items():
        if not value:
            continue
        if key.endswith(SECRET_ENV_SUFFIXES):
            secrets.add(value)
        elif key.endswith("_URL"):
            host = urlparse(value).hostname
            if host and host not in {"localhost", "127.0.0.1", "homeassistant.local"}:
                secrets.add(host)
    # Very short values (e.g. a user called "dev") would match ordinary words.
    return sorted(secret for secret in secrets if len(secret) >= 5)


def _is_private_ip(text: str) -> bool:
    try:
        address = ipaddress.IPv4Address(text)
    except ipaddress.AddressValueError:
        return False
    return (
        address.is_private
        and not address.is_loopback
        and not any(
            address in ipaddress.IPv4Network(net)
            for net in (
                "192.0.2.0/24",
                "198.51.100.0/24",
                "203.0.113.0/24",
                "0.0.0.0/8",
            )
        )
    )


def check_text(text: str, secrets: list[str]) -> list[tuple[int, str]]:
    """Return (line number, reason) for every finding in ``text``."""
    findings: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        lowered = line.lower()
        findings.extend(
            (number, "value from .env")
            for secret in secrets
            if secret.lower() in lowered
        )
        findings.extend(
            (number, f"MAC address {match}")
            for match in MAC_RE.findall(line)
            if not match.lower().replace("-", ":").startswith("02:00:00:")
        )
        findings.extend(
            (number, "12-digit number (SYSID shape)")
            # Long numbers inside URLs (article ids, commit hashes) are not SYSIDs.
            for match in SYSID_RE.findall(URL_RE.sub("", line))
            if match != ANONYMOUS_SYSID
        )
        findings.extend(
            (number, f"private IPv4 address {match}")
            for match in IPV4_RE.findall(line)
            if _is_private_ip(match)
        )
    return findings


def _all_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def main(argv: list[str] | None = None) -> int:
    """Check the given files (or all files) and report findings."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*")
    parser.add_argument(
        "--all", action="store_true", help="check every file of the repository"
    )
    args = parser.parse_args(argv)

    files = _all_files() if args.all else args.files
    secrets = _env_secrets()
    failed = False
    for name in files:
        relative = (
            Path(name).resolve().relative_to(REPO_ROOT).as_posix()
            if Path(name).is_absolute()
            else Path(name).as_posix()
        )
        if relative in EXCLUDED_FILES or relative.startswith(EXCLUDED_PREFIXES):
            continue
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary file (images, PDFs)
        for line, reason in check_text(text, secrets):
            print(f"{relative}:{line}: {reason}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
