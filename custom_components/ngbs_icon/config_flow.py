"""Config flow: automatic discovery first, manual entry as the fallback."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
import probatio

from ._lib import pyngbsicon
from .const import (
    CONF_SYSID,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import IconConfigEntry
from .discovery import async_scan
from .util import entry_title

_MANUAL = "manual"
_SYSID_RE = re.compile(r"\d{6,20}")


class NgbsIconConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up an iCON system with as little typing as possible."""

    VERSION = 2
    MINOR_VERSION = 1

    def __init__(self) -> None:
        """Start a flow."""
        self._scan_task: asyncio.Task[list[pyngbsicon.DiscoveredIcon]] | None = None
        self._found: dict[str, pyngbsicon.DiscoveredIcon] = {}
        self._host = ""
        self._sysid: str | None = None
        self._state: pyngbsicon.IconSystem | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: IconConfigEntry) -> NgbsIconOptionsFlow:
        """Options of an entry."""
        return NgbsIconOptionsFlow()

    # -- user: scan, then pick, confirm or enter manually -------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Scan the local networks for controllers."""
        # The progress screen is always shown first, even if the scan is quick.
        if self._scan_task is None or not self._scan_task.done():
            if self._scan_task is None:
                self._scan_task = self.hass.async_create_task(async_scan(self.hass))
            return self.async_show_progress(
                step_id="user",
                progress_action="scanning",
                progress_task=self._scan_task,
            )
        try:
            results = self._scan_task.result()
        except Exception:  # noqa: BLE001 - the user can still enter the address
            LOGGER.exception("Scanning the network for iCON controllers failed")
            results = []
        configured = self._async_current_ids(include_ignore=False)
        self._found = {
            item.host: item
            for item in results
            if item.sysid is None or item.sysid not in configured
        }
        return self.async_show_progress_done(next_step_id="pick")

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Continue according to how many controllers were found."""
        if not self._found:
            return await self.async_step_manual()
        if len(self._found) == 1:
            self._use(next(iter(self._found.values())))
            return await self.async_step_confirm()
        return await self.async_step_select()

    async def async_step_select(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose one of several controllers found."""
        if user_input is not None:
            if user_input[CONF_HOST] == _MANUAL:
                return await self.async_step_manual()
            self._use(self._found[user_input[CONF_HOST]])
            return await self.async_step_confirm()
        options = [
            SelectOptionDict(value=item.host, label=_describe(item))
            for item in self._found.values()
        ]
        options.append(SelectOptionDict(value=_MANUAL, label=_MANUAL))
        return self.async_show_form(
            step_id="select",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_HOST): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                            translation_key="controller",
                        )
                    )
                }
            ),
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a found controller; ask for the SYSID only when it cannot be read."""
        errors: dict[str, str] = {}
        if user_input is not None or (self._sysid and self._state is None):
            sysid = (user_input or {}).get(CONF_SYSID, self._sysid)
            self._state = await self._async_connect(self._host, sysid, errors)
            if self._state is not None and user_input is not None:
                return await self._async_create_entry(self._state)
        schema = (
            probatio.Schema({probatio.Required(CONF_SYSID): TextSelector()})
            if self._sysid is None
            else probatio.Schema({})
        )
        state = self._state
        return self.async_show_form(
            step_id="confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "host": self._host,
                "name": (state.name if state else None) or DEFAULT_NAME,
                "thermostats": str(len(state.configured_thermostats)) if state else "?",
                "firmware": str(state.firmware) if state and state.firmware else "?",
            },
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter the controller's address (and the SYSID for old firmware)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            state = await self._async_connect(
                self._host, user_input.get(CONF_SYSID), errors
            )
            if state is not None:
                return await self._async_create_entry(state)
        return self.async_show_form(
            step_id="manual",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_HOST): TextSelector(),
                        probatio.Optional(CONF_SYSID): TextSelector(),
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    # -- discovery ---------------------------------------------------------

    async def async_step_dhcp(
        self, discovery_info: DhcpServiceInfo
    ) -> ConfigFlowResult:
        """Handle a controller seen on the network (new, or a known one at a new address)."""
        host = discovery_info.ip
        mac = format_mac(discovery_info.macaddress)
        for entry in self._async_current_entries(include_ignore=False):
            if entry.data.get(CONF_MAC) == mac:
                if entry.data.get(CONF_HOST) != host:
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_HOST: host}
                    )
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_abort(reason="already_configured")

        found = await pyngbsicon.probe(host)
        if found is None:
            return self.async_abort(reason="not_icon")
        # Old firmware does not reveal the SYSID; the MAC address identifies the flow
        # until the user has entered it.
        await self.async_set_unique_id(found.sysid or mac)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_MAC: mac})
        self._use(found)
        self.context["title_placeholders"] = {"host": host}
        return await self.async_step_confirm()

    # -- maintenance -------------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the controller's address; the system must stay the same."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            # Ask the address for its own SYSID first, so another system is recognised.
            state = await self._async_connect(host, None, errors)
            if errors.get("base") == "sysid_required":
                errors.clear()
                state = await self._async_connect(
                    host, entry.data.get(CONF_SYSID), errors
                )
            if state is not None:
                return await self._async_adopt(entry, state, {CONF_HOST: host})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema({probatio.Required(CONF_HOST): TextSelector()}),
                user_input or {CONF_HOST: entry.data.get(CONF_HOST, "")},
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle a SYSID the controller rejected (or one that is not known)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the SYSID."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            state = await self._async_connect(
                entry.data[CONF_HOST], user_input[CONF_SYSID], errors
            )
            if state is not None:
                return await self._async_adopt(entry, state, {})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=probatio.Schema(
                {probatio.Required(CONF_SYSID): TextSelector()}
            ),
            errors=errors,
            description_placeholders={"host": entry.data.get(CONF_HOST, "")},
        )

    # -- helpers -----------------------------------------------------------

    async def _async_adopt(
        self,
        entry: IconConfigEntry,
        state: pyngbsicon.IconSystem,
        updates: dict[str, Any],
    ) -> ConfigFlowResult:
        """Finish reauth/reconfigure with the system that answered.

        An entry migrated without a SYSID has no system-based unique ID yet; it
        adopts the one read now. An entry that has one must stay the same system.
        """
        if entry.unique_id and _SYSID_RE.fullmatch(entry.unique_id):
            await self.async_set_unique_id(state.sysid)
            self._abort_if_unique_id_mismatch(reason="wrong_system")
        return self.async_update_reload_and_abort(
            entry,
            unique_id=state.sysid,
            data_updates={**updates, CONF_SYSID: state.sysid, CONF_MAC: state.mac},
        )

    def _use(self, found: pyngbsicon.DiscoveredIcon) -> None:
        self._host = found.host
        self._sysid = found.sysid
        self._state = None

    async def _async_connect(
        self, host: str, sysid: str | None, errors: dict[str, str]
    ) -> pyngbsicon.IconSystem | None:
        """Read the system; fill ``errors`` with what went wrong."""
        sysid = (sysid or "").strip() or None
        if sysid is not None and not _SYSID_RE.fullmatch(sysid):
            errors[CONF_SYSID] = "invalid_sysid"
            return None
        client = pyngbsicon.IconClient(host, sysid)
        try:
            return await client.get_state()
        except pyngbsicon.IconUnsupportedError:
            errors["base"] = "sysid_required"
        except pyngbsicon.IconAuthenticationError:
            errors[CONF_SYSID if sysid else "base"] = "invalid_sysid"
        except pyngbsicon.IconConnectionError:
            errors["base"] = "cannot_connect"
        except pyngbsicon.IconError:
            errors["base"] = "not_icon"
        except Exception:  # noqa: BLE001 - shown as "unknown", logged in full
            LOGGER.exception("Unexpected error while connecting to %s", host)
            errors["base"] = "unknown"
        return None

    async def _async_create_entry(
        self, state: pyngbsicon.IconSystem
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(state.sysid, raise_on_progress=False)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: self._host, CONF_MAC: state.mac}
        )
        return self.async_create_entry(
            title=entry_title(state.name),
            data={CONF_HOST: self._host, CONF_SYSID: state.sysid, CONF_MAC: state.mac},
            options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
        )


class NgbsIconOptionsFlow(OptionsFlowWithReload):
    """How often the controller is polled."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])}
            )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                probatio.Schema(
                    {
                        probatio.Required(CONF_SCAN_INTERVAL): NumberSelector(
                            NumberSelectorConfig(
                                min=MIN_SCAN_INTERVAL,
                                max=MAX_SCAN_INTERVAL,
                                step=1,
                                unit_of_measurement="s",
                                mode=NumberSelectorMode.BOX,
                            )
                        )
                    }
                ),
                {
                    CONF_SCAN_INTERVAL: self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    )
                },
            ),
        )


def _describe(item: pyngbsicon.DiscoveredIcon) -> str:
    """Label of a found controller, without words (the step description explains it).

    Dynamic select labels cannot be translated.
    """
    if item.needs_sysid:
        return f"{item.host} · SYSID ?"
    sysid = item.sysid or ""
    return f"{item.host} · SYSID …{sysid[-4:]} · v{item.firmware}"
