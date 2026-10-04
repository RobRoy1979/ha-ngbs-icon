"""Encoding and decoding of protocol messages, including firmware quirks."""

from __future__ import annotations

from icon_test_support import load, load_text
import pytest

from pyngbsicon import IconProtocolError
from pyngbsicon.protocol import decode, encode, is_auth_error, parse_sysid_info, redact


def test_encode_is_compact_ascii() -> None:
    assert (
        encode({"SYSID": "1", "DP": {"1.1": {"XAH": 21.5}}})
        == b'{"SYSID":"1","DP":{"1.1":{"XAH":21.5}}}'
    )


def test_decode_recorded_answer_with_quirks() -> None:
    """The discovery answer has a multi-line layout and the "VER:" key."""
    data = decode(load_text("sysid").encode())
    assert data["SYSID"] == "123456789012"
    assert data["ICON1"]["VER:"] == "606231543"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b'{"A": 0000}', 0),
        (b'{"A": 0012, "B": 5}', 12),
        (b'{"A": -05}', -5),
        (b'{"A": 0.5}', 0.5),
        (b'{"A": 00.5}', 0.5),
        (b'{"A":0}\n', 0),
    ],
)
def test_decode_leading_zeros(raw: bytes, expected: float) -> None:
    assert decode(raw)["A"] == expected


def test_decode_does_not_touch_strings() -> None:
    assert decode(b'{"NAME": "0000", "X": "a\\": 007"}') == {
        "NAME": "0000",
        "X": 'a": 007',
    }


def test_decode_latin1_fallback() -> None:
    assert decode(b'{"NAME": "Szob\xe1"}')["NAME"] == "Szobá"


@pytest.mark.parametrize("raw", [b"", b"  \n", b"not json", b"[1, 2]", b'{"A": '])
def test_decode_rejects_invalid(raw: bytes) -> None:
    with pytest.raises(IconProtocolError):
        decode(raw)


def test_auth_error_is_not_a_fault_state() -> None:
    assert is_auth_error(load("error"))
    faulty = load("state_poll") | {"ERR": 1}
    assert not is_auth_error(faulty)
    assert not is_auth_error({"ERR": 0})


def test_redact_removes_the_web_password() -> None:
    redacted = redact(load("state_full"))
    assert "KEY" not in redacted
    assert redacted["SYSID"] == "123456789012"


def test_parse_sysid_info() -> None:
    info = parse_sysid_info(load("sysid"))
    assert info.sysid == "123456789012"
    assert info.firmware == {1: 1079}
    assert info.download == 0


def test_parse_sysid_info_with_slaves_and_noise() -> None:
    info = parse_sysid_info(
        {
            "SYSID": "123456789012",
            "ICON1": {"FIRMWARE": 1079},
            "ICON2": {"FIRMWARE": 1070},
            "ICON3": {},
            "ICONX": {},
            "ICON4": 5,
        }
    )
    assert info.firmware == {1: 1079, 2: 1070}
    assert info.download is None


@pytest.mark.parametrize("answer", [{}, {"SYSID": ""}, {"SYSID": 5}])
def test_parse_sysid_info_without_sysid(answer: dict) -> None:
    with pytest.raises(IconProtocolError):
        parse_sysid_info(answer)
