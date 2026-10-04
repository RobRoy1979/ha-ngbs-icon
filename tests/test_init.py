"""Setting up, unloading and migrating config entries."""

from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_IP_ADDRESS, CONF_MAC, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ngbs_icon.const import CONF_SYSID, DOMAIN
import pyngbsicon

from .conftest import HOST, MAC, SYSID, make_state, setup_integration


@pytest.mark.usefixtures("mock_client")
async def test_setup_and_unload(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    controller = device_registry.async_get_device_by_identifier(
        (DOMAIN, SYSID), config_entry.entry_id
    )
    assert controller is not None
    assert controller.name == "Home"
    assert controller.serial_number == SYSID
    assert controller.sw_version == "1079"
    assert controller.connections == {(dr.CONNECTION_NETWORK_MAC, MAC)}
    assert controller.configuration_url == f"http://{HOST}/"

    room = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSID}-1.1"), config_entry.entry_id
    )
    assert room is not None
    assert room.name == "Living room"
    assert room.via_device_id == controller.id
    # Only configured thermostats get a device.
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, f"{SYSID}-1.6"), config_entry.entry_id
        )
        is None
    )

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_slave_controllers_get_devices(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    device_registry: dr.DeviceRegistry,
) -> None:
    state = make_state()
    slave = dataclasses.replace(state.controllers[1], address=2, is_master=False)
    state = dataclasses.replace(state, controllers={1: state.controllers[1], 2: slave})
    mock_client.return_value.get_state.return_value = state
    await setup_integration(hass, config_entry)

    master = device_registry.async_get_device_by_identifier(
        (DOMAIN, SYSID), config_entry.entry_id
    )
    device = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSID}-controller-2"), config_entry.entry_id
    )
    assert master is not None and device is not None
    assert device.name == "Home 2"
    assert device.via_device_id == master.id


async def test_mac_is_stored(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_client: MagicMock
) -> None:
    hass_entry_data = {**config_entry.data, CONF_MAC: None}
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=SYSID, data=hass_entry_data, version=2, options={}
    )
    await setup_integration(hass, entry)
    assert entry.data[CONF_MAC] == MAC


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (pyngbsicon.IconConnectionError("down"), ConfigEntryState.SETUP_RETRY),
        (pyngbsicon.IconProtocolError("garbage"), ConfigEntryState.SETUP_RETRY),
        (pyngbsicon.IconAuthenticationError("no"), ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_setup_failures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    error: Exception,
    state: ConfigEntryState,
) -> None:
    mock_client.return_value.get_state.side_effect = error
    await setup_integration(hass, config_entry)
    assert config_entry.state is state
    reauth = [
        f
        for f in hass.config_entries.flow.async_progress()
        if f["context"]["source"] == SOURCE_REAUTH
    ]
    assert bool(reauth) == (state is ConfigEntryState.SETUP_ERROR)


@pytest.mark.usefixtures("mock_client")
async def test_setup_without_sysid_starts_reauth(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"host:{HOST}",
        data={CONF_HOST: HOST, CONF_SYSID: "", CONF_MAC: None},
        version=2,
    )
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


def _v1_entry(
    data: dict[str, object], *, title: str = HOST, unique_id: str | None = None
) -> MockConfigEntry:
    """An entry as the earlier integration of the same domain created it."""
    return MockConfigEntry(
        domain=DOMAIN, title=title, unique_id=unique_id, data=data, version=1
    )


# The shape found on a real installation, and the shape of later versions.
V1_HOST_PORT = {CONF_HOST: HOST, "port": 502, "scan_interval": 10, "slave": 1}
V1_WITH_ID = {CONF_IP_ADDRESS: HOST, "id": SYSID, "scan_interval": 60, "inventory": {}}


async def test_migrate_v1(
    hass: HomeAssistant,
    mock_client: MagicMock,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    entry = _v1_entry(V1_HOST_PORT)
    entry.add_to_hass(hass)
    old_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "old-room")}
    )
    old_entity = entity_registry.async_get_or_create(
        "climate",
        DOMAIN,
        "old_room_climate",
        config_entry=entry,
        device_id=old_device.id,
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 2
    assert entry.minor_version == 1
    assert entry.unique_id == SYSID
    assert entry.title == "NGBS iCON (Home)"
    assert entry.data == {CONF_HOST: HOST, CONF_SYSID: SYSID, CONF_MAC: MAC}
    assert entry.options == {CONF_SCAN_INTERVAL: 10}
    assert entity_registry.async_get(old_entity.entity_id) is None
    assert device_registry.async_get(old_device.id) is None
    mock_client.assert_any_call(HOST, None)  # the SYSID was discovered
    assert len(hass.states.async_entity_ids("climate")) == 5


async def test_migrate_v1_with_stored_sysid(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    entry = _v1_entry(V1_WITH_ID, title="Upstairs", unique_id=SYSID)
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.title == "Upstairs"  # chosen by the user: kept
    assert entry.options == {CONF_SCAN_INTERVAL: 60}
    mock_client.assert_any_call(HOST, SYSID)


@pytest.mark.parametrize(
    ("interval", "expected"), [(3, 10), (900, 300), ("bogus", 30), (None, 30)]
)
@pytest.mark.usefixtures("mock_client")
async def test_migrate_v1_interval(
    hass: HomeAssistant, interval: object, expected: int
) -> None:
    entry = _v1_entry({**V1_HOST_PORT, "scan_interval": interval})
    await setup_integration(hass, entry)
    assert entry.options == {CONF_SCAN_INTERVAL: expected}


async def test_migrate_v1_without_reachable_controller(
    hass: HomeAssistant, mock_client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    mock_client.return_value.get_state.side_effect = pyngbsicon.IconConnectionError(
        "down"
    )
    entry = _v1_entry(V1_HOST_PORT)
    await setup_integration(hass, entry)
    assert entry.version == 2
    assert entry.unique_id is None
    assert entry.title == "NGBS iCON"
    assert entry.data == {CONF_HOST: HOST, CONF_SYSID: "", CONF_MAC: None}
    assert entry.state is ConfigEntryState.SETUP_ERROR  # reauth asks for the SYSID
    assert "Could not read the NGBS iCON system" in caplog.text


async def test_migrate_v1_unreachable_keeps_stored_sysid(
    hass: HomeAssistant, mock_client: MagicMock
) -> None:
    mock_client.return_value.get_state.side_effect = pyngbsicon.IconConnectionError(
        "down"
    )
    entry = _v1_entry(V1_WITH_ID, title="NGBS iCON")
    await setup_integration(hass, entry)
    assert entry.unique_id == SYSID
    assert entry.data[CONF_SYSID] == SYSID
    assert entry.title == "NGBS iCON"
    assert entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.usefixtures("mock_client")
async def test_migrate_v1_when_the_system_is_set_up_twice(
    hass: HomeAssistant, config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    config_entry.add_to_hass(hass)
    entry = _v1_entry(V1_HOST_PORT)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.version == 2
    assert entry.unique_id is None  # the new entry keeps the SYSID
    assert "is also set up as NGBS iCON (Home)" in caplog.text


@pytest.mark.usefixtures("mock_client")
async def test_migrate_v1_without_host(hass: HomeAssistant) -> None:
    entry = _v1_entry({"scan_interval": 30}, title="NGBS iCON")
    await setup_integration(hass, entry)
    assert entry.version == 2
    assert entry.data == {CONF_HOST: "", CONF_SYSID: "", CONF_MAC: None}


@pytest.mark.usefixtures("mock_client")
async def test_migrate_from_the_future_fails(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={}, version=3)
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


@pytest.mark.usefixtures("mock_client")
async def test_current_version_is_not_changed(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """An older minor version of the current major version needs no migration."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SYSID,
        data=dict(config_entry.data),
        options=dict(config_entry.options),
        version=2,
        minor_version=0,
    )
    await setup_integration(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data == config_entry.data
