"""Record responses of a real iCON controller and turn them into anonymised test fixtures.

Reads ICON_HOST (and optionally ICON_SYSID) from .env, sends the protocol's main
requests, stores the untouched responses in lib/pyngbsicon/tests/fixtures/raw/ (git-ignored)
and writes anonymised copies to lib/pyngbsicon/tests/fixtures/:

    sysid.json        response to {"RELOAD": 6}                 (SYSID discovery)
    state_poll.json   response to {"SYSID": s}                  (regular poll)
    state_full.json   response to {"SYSID": s, "RELOAD": ""}    (state + configuration)
    error.json        response to a request with a wrong SYSID

Anonymisation replaces identifiers in the raw text, so the controller's exact
formatting (spacing, line breaks, key quirks such as "VER:") is preserved:
SYSID and KEY become 123456789012, the MAC address 02:00:00:00:00:01, IPv4
addresses documentation addresses (RFC 5737), the e-mail address is emptied, and
room / building names become generic English names.

Only reads from the controller; nothing is written to it.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_no_secrets import _env_secrets, check_text
from devenv import REPO_ROOT, load_env, require

PORT = 7992
TIMEOUT = 5.0
FIXTURES = REPO_ROOT / "lib" / "pyngbsicon" / "tests" / "fixtures"
RAW = FIXTURES / "raw"

ANON_SYSID = "123456789012"
ANON_MAC = "02:00:00:00:00:01"
ANON_BUILDING = "Home"
ANON_ROOMS = [
    "Living room",
    "Kitchen",
    "Bedroom",
    "Bathroom",
    "Office",
    "Kids room",
    "Guest room",
    "Hall",
]
WRONG_SYSID = "000000000000"  # deliberately invalid; allow-secret


def request(host: str, payload: dict[str, object]) -> str:
    """Send one request on a fresh connection and return the raw response text."""
    with socket.create_connection((host, PORT), timeout=TIMEOUT) as sock:
        sock.sendall(json.dumps(payload).encode())
        chunks: list[bytes] = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


def _ip_replacements(full: dict[str, object]) -> dict[str, str]:
    """Map every IPv4 address in the state to a documentation address (RFC 5737).

    LAN addresses go to 192.0.2.0/24, the cloud VPN tunnel to 198.51.100.0/24 and the
    manufacturer's server to 203.0.113.0/24, so the fixtures stay self-explanatory.
    """
    found: list[tuple[str, str]] = []
    info = full.get("INFO")
    netl = info.get("NETL") if isinstance(info, dict) else None
    if isinstance(netl, dict):
        for name, value in netl.items():
            if name != "MAC":
                found.append(
                    ("tunnel" if name.startswith("tun") else "lan", str(value))
                )
    cfg = full.get("CFG")
    net = cfg.get("NET") if isinstance(cfg, dict) else None
    if isinstance(net, dict):
        found.extend(("lan", str(net.get(name, ""))) for name in ("IP", "GW", "DNS1"))
        found.append(("server", str(net.get("SERVER", ""))))

    pools = {
        "lan": ("192.0.2.", 10),
        "tunnel": ("198.51.100.", 2),
        "server": ("203.0.113.", 1),
    }
    mapping: dict[str, str] = {}
    for kind, address in found:
        if (
            not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", address)
            or address.startswith("127.")
            or address in mapping
        ):
            continue
        prefix, next_host = pools[kind]
        mapping[address] = f"{prefix}{next_host}"
        pools[kind] = (prefix, next_host + 1)
    return mapping


def anonymise(text: str, full: dict[str, object], sysid: str) -> str:
    """Replace every identifier of the real installation in ``text``."""
    replacements: dict[str, str] = {sysid: ANON_SYSID}
    key = full.get("KEY")
    if isinstance(key, str) and key:
        replacements[key] = ANON_SYSID
    info = full.get("INFO")
    mac = info.get("NETL", {}).get("MAC") if isinstance(info, dict) else None
    if isinstance(mac, str) and mac:
        replacements[mac.lower()] = ANON_MAC
        replacements[mac.upper()] = ANON_MAC.upper()
    for real, fake in replacements.items():
        text = text.replace(real, fake)

    for real, fake in _ip_replacements(full).items():
        text = re.sub(rf"(?<![\d.]){re.escape(real)}(?![\d.])", fake, text)

    text = re.sub(r'("EMAIL"\s*:\s*)"[^"]*"', r'\1""', text)

    cfg = full.get("CFG")
    if isinstance(cfg, dict) and isinstance(cfg.get("NAME"), str):
        text = re.sub(
            r'("CFG"\s*:\s*\{\s*"NAME"\s*:\s*)"(?:[^"\\]|\\.)*"',
            rf'\1"{ANON_BUILDING}"',
            text,
        )

    thermostats = full.get("DP")
    if isinstance(thermostats, dict):
        for thermostat_id in thermostats:
            controller, _, address = thermostat_id.partition(".")
            index = (int(controller) - 1) * 8 + int(address) - 1
            name = ANON_ROOMS[index % len(ANON_ROOMS)]
            if index >= len(ANON_ROOMS):
                name = f"{name} {int(controller)}"
            # Thermostat objects are flat, so the name is found before the closing brace.
            text = re.sub(
                rf'("{re.escape(thermostat_id)}"\s*:\s*\{{[^{{}}]*?"NAME"\s*:\s*)"(?:[^"\\]|\\.)*"',
                rf'\1"{name}"',
                text,
            )
    return text


def main() -> int:
    """Record, anonymise and verify the fixtures."""
    env = load_env()
    (host,) = require(env, "ICON_HOST")

    sysid_raw = request(host, {"RELOAD": 6})
    discovered = json.loads(sysid_raw).get("SYSID")
    sysid = env.get("ICON_SYSID") or discovered
    if not sysid:
        raise SystemExit(
            "The controller did not reveal its SYSID; set ICON_SYSID in .env."
        )

    raw = {
        "sysid": sysid_raw,
        "state_poll": request(host, {"SYSID": sysid}),
        "state_full": request(host, {"SYSID": sysid, "RELOAD": ""}),
        "error": request(host, {"SYSID": WRONG_SYSID, "RELOAD": ""}),
    }
    full = json.loads(raw["state_full"])

    RAW.mkdir(parents=True, exist_ok=True)
    secrets = [*_env_secrets(), sysid]
    for name, text in raw.items():
        (RAW / f"{name}.json").write_text(text, encoding="utf-8")
        clean = anonymise(text, full, sysid)
        json.loads(clean)  # still valid JSON
        findings = check_text(clean, secrets)
        if findings:
            raise SystemExit(
                f"{name}: anonymisation left identifiers behind: {findings}"
            )
        (FIXTURES / f"{name}.json").write_text(clean, encoding="utf-8")
        print(f"{(FIXTURES / name).relative_to(REPO_ROOT)}.json  ({len(clean)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
