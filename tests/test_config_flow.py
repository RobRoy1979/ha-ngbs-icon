"""Config flow: scan, confirm, manual entry, DHCP discovery, reconfigure, reauth, options."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ngbs_icon.const import CONF_SYSID, DOMAIN
import pyngbsicon

from .conftest import (
    DHCP_MAC,
    HOST,
    MAC,
    OTHER_SYSID,
    SYSID,
    WRONG_SYSID,
    found,
    make_state,
)

pytestmark = pytest.mark.usefixtures("mock_client", "mock_setup_entry")

DHCP = DhcpServiceInfo(ip=HOST, hostname="icon", macaddress=DHCP_MAC)


async def _scan(hass: HomeAssistant) -> dict:
    """Start the user flow and let the scan finish."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "scanning"
    await hass.async_block_till_done()
    return await hass.config_entries.flow.async_configure(result["flow_id"])


def _created(result: dict, host: str = HOST) -> None:
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "NGBS iCON (Home)"
    assert result["data"] == {CONF_HOST: host, CONF_SYSID: SYSID, CONF_MAC: MAC}
    assert result["options"] == {CONF_SCAN_INTERVAL: 30}
    assert result["result"].unique_id == SYSID


async def test_one_controller_found(
    hass: HomeAssistant, mock_discover: AsyncMock
) -> None:
    mock_discover.return_value = [found()]
    result = await _scan(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"] == {
        "host": HOST,
        "name": "Home",
        "thermostats": "5",
        "firmware": "1079",
    }
    _created(await hass.config_entries.flow.async_configure(result["flow_id"], {}))


async def test_confirm_shows_errors(
    hass: HomeAssistant, mock_discover: AsyncMock, mock_client: MagicMock
) -> None:
    mock_discover.return_value = [found()]
    mock_client.return_value.get_state.side_effect = pyngbsicon.IconConnectionError(
        "gone"
    )
    result = await _scan(hass)
    assert result["errors"] == {"base": "cannot_connect"}
    assert result["description_placeholders"]["thermostats"] == "?"
    assert result["description_placeholders"]["name"] == "NGBS iCON"

    mock_client.return_value.get_state.side_effect = None
    _created(await hass.config_entries.flow.async_configure(result["flow_id"], {}))


async def test_several_controllers_found(
    hass: HomeAssistant, mock_discover: AsyncMock
) -> None:
    mock_discover.return_value = [
        found("192.0.2.20", OTHER_SYSID),
        found(),
        found("192.0.2.30", needs_sysid=True),
    ]
    result = await _scan(hass)
    assert result["step_id"] == "select"
    options = result["data_schema"].schema[CONF_HOST].config["options"]
    assert [option["value"] for option in options] == [
        "192.0.2.20",
        HOST,
        "192.0.2.30",
        "manual",
    ]
    assert options[1]["label"] == f"{HOST} — SYSID …9012, firmware 1079"
    assert options[2]["label"] == "192.0.2.30 (SYSID required)"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: HOST}
    )
    assert result["step_id"] == "confirm"
    _created(await hass.config_entries.flow.async_configure(result["flow_id"], {}))


async def test_select_manual(hass: HomeAssistant, mock_discover: AsyncMock) -> None:
    mock_discover.return_value = [found(), found("192.0.2.20", OTHER_SYSID)]
    result = await _scan(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "manual"}
    )
    assert result["step_id"] == "manual"


async def test_configured_systems_are_not_offered(
    hass: HomeAssistant, mock_discover: AsyncMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    mock_discover.return_value = [found()]
    result = await _scan(hass)
    assert result["step_id"] == "manual"


async def test_old_firmware_asks_for_sysid(
    hass: HomeAssistant, mock_discover: AsyncMock, mock_client: MagicMock
) -> None:
    mock_discover.return_value = [found(needs_sysid=True)]
    result = await _scan(hass)
    assert result["step_id"] == "confirm"
    assert CONF_SYSID in result["data_schema"].schema
    mock_client.assert_not_called()  # nothing to read without the SYSID

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SYSID: "12ab"}
    )
    assert result["errors"] == {CONF_SYSID: "invalid_sysid"}

    mock_client.return_value.get_state.side_effect = pyngbsicon.IconAuthenticationError(
        "no"
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SYSID: WRONG_SYSID}
    )
    assert result["errors"] == {CONF_SYSID: "invalid_sysid"}

    mock_client.return_value.get_state.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SYSID: f" {SYSID} "}
    )
    _created(result)
    mock_client.assert_called_with(HOST, SYSID)


async def test_nothing_found_manual_entry(
    hass: HomeAssistant, mock_discover: AsyncMock
) -> None:
    result = await _scan(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    assert result["errors"] == {}
    _created(
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: f" {HOST} "}
        )
    )


@pytest.mark.parametrize(
    ("error", "sysid", "expected"),
    [
        (pyngbsicon.IconConnectionError("x"), "", {"base": "cannot_connect"}),
        (pyngbsicon.IconProtocolError("x"), "", {"base": "not_icon"}),
        (pyngbsicon.IconUnsupportedError("x"), "", {"base": "sysid_required"}),
        (pyngbsicon.IconAuthenticationError("x"), "", {"base": "invalid_sysid"}),
        (pyngbsicon.IconAuthenticationError("x"), SYSID, {CONF_SYSID: "invalid_sysid"}),
        (RuntimeError("boom"), "", {"base": "unknown"}),
    ],
)
async def test_manual_errors(
    hass: HomeAssistant,
    mock_discover: AsyncMock,
    mock_client: MagicMock,
    error: Exception,
    sysid: str,
    expected: dict[str, str],
) -> None:
    result = await _scan(hass)
    mock_client.return_value.get_state.side_effect = error
    user_input = {CONF_HOST: HOST} | ({CONF_SYSID: sysid} if sysid else {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == expected

    mock_client.return_value.get_state.side_effect = None
    _created(
        await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    )


async def test_manual_entry_of_a_configured_system_aborts(
    hass: HomeAssistant, mock_discover: AsyncMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    result = await _scan(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.99"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert (
        config_entry.data[CONF_HOST] == "192.0.2.99"
    )  # the address follows the controller


async def test_dhcp_new_controller(hass: HomeAssistant, mock_probe: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    flows = hass.config_entries.flow.async_progress()
    assert flows[0]["context"]["title_placeholders"] == {"host": HOST}
    _created(await hass.config_entries.flow.async_configure(result["flow_id"], {}))


async def test_dhcp_old_firmware(
    hass: HomeAssistant, mock_probe: AsyncMock, mock_client: MagicMock
) -> None:
    mock_probe.return_value = found(needs_sysid=True)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP
    )
    assert result["step_id"] == "confirm"
    assert CONF_SYSID in result["data_schema"].schema
    _created(
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SYSID: SYSID}
        )
    )


async def test_dhcp_not_an_icon(hass: HomeAssistant, mock_probe: AsyncMock) -> None:
    mock_probe.return_value = None
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_icon"


async def test_dhcp_known_system_at_a_new_address(
    hass: HomeAssistant, mock_probe: AsyncMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_MAC: None}
    )
    mock_probe.return_value = found("192.0.2.77")
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_DHCP},
        data=DhcpServiceInfo(ip="192.0.2.77", hostname="icon", macaddress=DHCP_MAC),
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == "192.0.2.77"
    assert config_entry.data[CONF_MAC] == MAC


async def test_dhcp_known_mac_updates_without_probing(
    hass: HomeAssistant, mock_probe: AsyncMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    for ip in ("192.0.2.88", "192.0.2.88"):  # second time: address already current
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_DHCP},
            data=DhcpServiceInfo(ip=ip, hostname="icon", macaddress=DHCP_MAC),
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == "192.0.2.88"
    mock_probe.assert_not_called()


async def test_reconfigure(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    mock_client.return_value.get_state.side_effect = pyngbsicon.IconConnectionError("x")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.50"}
    )
    assert result["errors"] == {"base": "cannot_connect"}

    mock_client.return_value.get_state.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.50"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_HOST] == "192.0.2.50"
    mock_client.assert_called_with("192.0.2.50", None)  # asked for its own SYSID


async def test_reconfigure_sets_sysid_of_migrated_entry(hass: HomeAssistant) -> None:
    """A migrated entry without a SYSID is repaired by reconfigure too, not only reauth."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=None,
        data={CONF_HOST: HOST, CONF_SYSID: "", CONF_MAC: None},
        options={CONF_SCAN_INTERVAL: 30},
        version=2,
    )
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.50"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.unique_id == SYSID
    assert entry.data == {CONF_HOST: "192.0.2.50", CONF_SYSID: SYSID, CONF_MAC: MAC}


async def test_reconfigure_old_firmware_uses_stored_sysid(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    mock_client.return_value.get_state.side_effect = [
        pyngbsicon.IconUnsupportedError("old"),
        make_state(),
    ]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.51"}
    )
    assert result["reason"] == "reconfigure_successful"
    mock_client.assert_called_with("192.0.2.51", SYSID)


async def test_reconfigure_to_another_system(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)
    mock_client.return_value.get_state.return_value = make_state(SYSID=OTHER_SYSID)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.0.2.60"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_system"
    assert config_entry.data[CONF_HOST] == HOST


async def test_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["host"] == HOST

    mock_client.return_value.get_state.side_effect = pyngbsicon.IconAuthenticationError(
        "no"
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SYSID: SYSID}
    )
    assert result["errors"] == {CONF_SYSID: "invalid_sysid"}

    mock_client.return_value.get_state.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SYSID: SYSID}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"


async def test_reauth_of_another_system(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reauth_flow(hass)
    mock_client.return_value.get_state.return_value = make_state(SYSID=OTHER_SYSID)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SYSID: OTHER_SYSID}
    )
    assert result["reason"] == "wrong_system"


async def test_reauth_sets_sysid_of_migrated_entry(hass: HomeAssistant) -> None:
    """An entry migrated without a SYSID has a host-based unique ID; reauth fixes it."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"host:{HOST}",
        data={CONF_HOST: HOST, CONF_SYSID: "", CONF_MAC: None},
        options={CONF_SCAN_INTERVAL: 30},
        version=2,
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SYSID: SYSID}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.unique_id == SYSID
    assert entry.data[CONF_SYSID] == SYSID and entry.data[CONF_MAC] == MAC


async def test_options(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_SCAN_INTERVAL: 60}


async def test_scan_failure_falls_back_to_manual(
    hass: HomeAssistant, mock_discover: AsyncMock, caplog: pytest.LogCaptureFixture
) -> None:
    mock_discover.side_effect = OSError("no network")
    result = await _scan(hass)
    assert result["step_id"] == "manual"
    assert "Scanning the network for iCON controllers failed" in caplog.text


async def test_progress_is_shown_while_scanning(
    hass: HomeAssistant, mock_discover: AsyncMock
) -> None:
    release = asyncio.Event()

    async def slow_scan(_hass: HomeAssistant) -> list[pyngbsicon.DiscoveredIcon]:
        await release.wait()
        return [found()]

    mock_discover.side_effect = slow_scan
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.SHOW_PROGRESS  # still scanning

    release.set()
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["step_id"] == "confirm"
