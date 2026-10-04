"""Install the integration on a Home Assistant OS instance through its FTP add-on.

Steps: log in to Home Assistant (HA_URL / HA_USER / HA_PASSWORD from .env), read the
FTP add-on's port and user from the Supervisor API, build the package
(scripts/package.py), download the currently installed ``custom_components/ngbs_icon``
into ``.backups/ngbs_icon.bak-<timestamp>.zip``, replace it, restart Home Assistant
Core and report the integration's state, entity count and log messages afterwards.

    python scripts/deploy_ha.py            # deploy
    python scripts/deploy_ha.py --dry-run  # log in, inspect, list; change nothing
    python scripts/deploy_ha.py --no-restart

Runs inside the toolchain container (``make deploy``), which provides aiohttp.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import ftplib
import io
from pathlib import Path, PurePosixPath
import sys
import time
from typing import Any
from urllib.parse import urlparse
import zipfile

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devenv import REPO_ROOT, load_env, require
from package import build

DOMAIN = "ngbs_icon"
BACKUPS = REPO_ROOT / ".backups"
CONFIG_DIR_CANDIDATES = ("homeassistant", "config")


class HomeAssistant:
    """Minimal REST + WebSocket client for the few calls the deployment needs."""

    def __init__(self, session: aiohttp.ClientSession, url: str) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._token = ""
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._next_id = 0

    async def login(self, user: str, password: str) -> None:
        """Obtain an access token through the regular login flow."""
        client_id = self._url + "/"
        async with self._session.post(
            self._url + "/auth/login_flow",
            json={
                "client_id": client_id,
                "handler": ["homeassistant", None],
                "redirect_uri": client_id,
            },
        ) as response:
            flow = await response.json()
        async with self._session.post(
            f"{self._url}/auth/login_flow/{flow['flow_id']}",
            json={"client_id": client_id, "username": user, "password": password},
        ) as response:
            result = await response.json()
        if result.get("type") != "create_entry":
            raise SystemExit(
                f"Home Assistant login failed: {result.get('errors') or result}"
            )
        async with self._session.post(
            self._url + "/auth/token",
            data={
                "grant_type": "authorization_code",
                "code": result["result"],
                "client_id": client_id,
            },
        ) as response:
            self._token = (await response.json())["access_token"]

    async def connect(self) -> None:
        """Open and authenticate the WebSocket connection."""
        ws_url = self._url.replace("http", "ws", 1) + "/api/websocket"
        self._ws = await self._session.ws_connect(ws_url, max_msg_size=64 * 1024 * 1024)
        await self._ws.receive_json()
        await self._ws.send_json({"type": "auth", "access_token": self._token})
        reply = await self._ws.receive_json()
        if reply.get("type") != "auth_ok":
            raise SystemExit(f"WebSocket authentication failed: {reply}")

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def call(self, message: dict[str, Any]) -> Any:
        """Send a WebSocket command and return its result."""
        assert self._ws is not None
        self._next_id += 1
        await self._ws.send_json({"id": self._next_id, **message})
        while True:
            reply = await self._ws.receive_json()
            if reply.get("id") == self._next_id:
                break
        if not reply.get("success"):
            raise RuntimeError(f"{message.get('type')} failed: {reply.get('error')}")
        return reply.get("result")

    async def supervisor(self, endpoint: str, method: str = "get") -> Any:
        """Call a Supervisor API endpoint through the WebSocket proxy."""
        return await self.call(
            {"type": "supervisor/api", "endpoint": endpoint, "method": method}
        )

    async def wait_until_running(self, timeout: float = 300) -> None:
        """Wait until the REST API answers again after a restart."""
        deadline = time.monotonic() + timeout
        await asyncio.sleep(10)
        while time.monotonic() < deadline:
            try:
                async with self._session.get(
                    self._url + "/api/config",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as response:
                    if (
                        response.status == 200
                        and (await response.json()).get("state") == "RUNNING"
                    ):
                        return
            except aiohttp.ClientError, TimeoutError:
                pass
            await asyncio.sleep(3)
        raise SystemExit("Home Assistant did not come back within 5 minutes")


def _ftp_settings(addon: dict[str, Any], host: str) -> tuple[str, int, str, str]:
    """Return (host, port, user, password) of the first add-on user with config access."""
    options = addon.get("options", {})
    network = addon.get("network") or {}
    port = int(network.get("21/tcp") or options.get("port") or 21)
    for user in options.get("users", []):
        if user.get("enabled", True) and user.get("homeassistant", True):
            return host, port, user["username"], user["password"]
    raise SystemExit(
        "The FTP add-on has no enabled user with access to the configuration folder"
    )


def _ftp_open(host: str, port: int, user: str, password: str) -> ftplib.FTP:
    ftp = ftplib.FTP()
    ftp.connect(host, port, timeout=30)
    ftp.login(user, password)
    ftp.set_pasv(True)
    return ftp


def _ftp_config_dir(ftp: ftplib.FTP) -> str:
    """Find the Home Assistant configuration folder in the add-on's FTP root."""
    entries = {PurePosixPath(name).name for name in ftp.nlst()}
    for candidate in CONFIG_DIR_CANDIDATES:
        if candidate in entries:
            return "/" + candidate
    raise SystemExit(
        f"No configuration folder in the FTP root (found: {sorted(entries)})"
    )


def _ftp_is_dir(ftp: ftplib.FTP, path: str) -> bool:
    current = ftp.pwd()
    try:
        ftp.cwd(path)
    except ftplib.error_perm:
        return False
    ftp.cwd(current)
    return True


def _ftp_walk(ftp: ftplib.FTP, path: str) -> list[str]:
    """Return every file below ``path`` (recursive)."""
    files: list[str] = []
    for name in ftp.nlst(path):
        full = name if name.startswith("/") else f"{path}/{PurePosixPath(name).name}"
        if PurePosixPath(full).name in {".", ".."}:
            continue
        if _ftp_is_dir(ftp, full):
            files.extend(_ftp_walk(ftp, full))
        else:
            files.append(full)
    return files


def _ftp_remove_tree(ftp: ftplib.FTP, path: str) -> None:
    for name in ftp.nlst(path):
        full = name if name.startswith("/") else f"{path}/{PurePosixPath(name).name}"
        if PurePosixPath(full).name in {".", ".."}:
            continue
        if _ftp_is_dir(ftp, full):
            _ftp_remove_tree(ftp, full)
        else:
            ftp.delete(full)
    ftp.rmd(path)


def _ftp_upload_tree(ftp: ftplib.FTP, local: Path, remote: str) -> int:
    ftp.mkd(remote)
    count = 0
    for path in sorted(local.iterdir()):
        target = f"{remote}/{path.name}"
        if path.is_dir():
            count += _ftp_upload_tree(ftp, path, target)
        else:
            with path.open("rb") as handle:
                ftp.storbinary(f"STOR {target}", handle)
            count += 1
    return count


def ftp_deploy(
    settings: tuple[str, int, str, str], staging: Path, dry_run: bool
) -> None:
    """Back up and replace custom_components/ngbs_icon over FTP."""
    ftp = _ftp_open(*settings)
    try:
        config_dir = _ftp_config_dir(ftp)
        components = f"{config_dir}/custom_components"
        target = f"{components}/{DOMAIN}"
        installed = _ftp_is_dir(ftp, target)
        print(
            f"FTP: {config_dir} found; {target} {'exists' if installed else 'does not exist'}"
        )

        if installed:
            files = _ftp_walk(ftp, target)
            print(f"  installed integration: {len(files)} files")
            if not dry_run:
                BACKUPS.mkdir(exist_ok=True)
                backup = BACKUPS / f"{DOMAIN}.bak-{datetime.now():%Y%m%d-%H%M%S}.zip"
                with zipfile.ZipFile(backup, "w", zipfile.ZIP_DEFLATED) as archive:
                    for remote in files:
                        buffer = io.BytesIO()
                        ftp.retrbinary(f"RETR {remote}", buffer.write)
                        archive.writestr(remote[len(target) + 1 :], buffer.getvalue())
                print(f"  backup: {backup.relative_to(REPO_ROOT)}")
        if dry_run:
            print("Dry run: nothing was changed.")
            return
        if installed:
            _ftp_remove_tree(ftp, target)
        if not _ftp_is_dir(ftp, components):
            ftp.mkd(components)
        uploaded = _ftp_upload_tree(ftp, staging, target)
        print(f"  uploaded {uploaded} files to {target}")
    finally:
        ftp.quit()


async def report(ha: HomeAssistant) -> int:
    """Print the integration's state after the restart; return a process exit code."""
    entries = await ha.call({"type": "config_entries/get", "domain": DOMAIN})
    entities = [
        e
        for e in await ha.call({"type": "config/entity_registry/list"})
        if e["platform"] == DOMAIN
    ]
    devices = [
        d
        for d in await ha.call({"type": "config/device_registry/list"})
        if any(identifier[0] == DOMAIN for identifier in d["identifiers"])
    ]
    print(f"Config entries: {[(e['title'], e['state']) for e in entries] or 'none'}")
    print(f"Devices: {len(devices)}  entities: {len(entities)}")
    messages = [
        m
        for m in await ha.call({"type": "system_log/list"})
        if DOMAIN in m.get("name", "") or "pyngbsicon" in m.get("name", "")
    ]
    for message in messages:
        print(f"  log {message['level']}: {message['message'][0][:200]}")
    failed = [e for e in entries if e["state"] not in {"loaded", "not_loaded"}]
    return 1 if failed else 0


async def main() -> int:
    """Run the deployment."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="inspect only, change nothing"
    )
    parser.add_argument(
        "--no-restart", action="store_true", help="do not restart Home Assistant"
    )
    args = parser.parse_args()

    env = load_env()
    url, user, password = require(env, "HA_URL", "HA_USER", "HA_PASSWORD")
    addon_slug = env.get("HA_FTP_ADDON", "a0d7b954_ftp")
    host = urlparse(url).hostname or ""

    staging = build(vendor=True)
    print(f"Package: {staging.relative_to(REPO_ROOT)}")

    async with aiohttp.ClientSession() as session:
        ha = HomeAssistant(session, url)
        await ha.login(user, password)
        await ha.connect()
        addon = await ha.supervisor(f"/addons/{addon_slug}/info")
        if addon.get("state") != "started":
            raise SystemExit(f"The FTP add-on ({addon_slug}) is not running")
        settings = _ftp_settings(addon, host)
        await asyncio.to_thread(ftp_deploy, settings, staging, args.dry_run)

        if args.dry_run or args.no_restart:
            code = await report(ha)
            await ha.close()
            return code

        print("Restarting Home Assistant Core ...")
        await ha.supervisor("/core/restart", method="post")
        await ha.close()
        await ha.wait_until_running()
        await ha.connect()
        await asyncio.sleep(5)  # let config entries finish setting up
        code = await report(ha)
        await ha.close()
        return code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
