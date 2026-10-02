"""Offline tests: no speaker, no sockets. Replies are fed to process_zipp_message() as packets."""
import json

import pytest

from python_libratone_zipp import LibratoneMessage, LibratoneZipp
from python_libratone_zipp.LibratoneZipp import (
    FW_UPDATE_STATES,
    PLAY_MODE_IDS,
    PLAY_MODES,
    SOURCE_TYPES,
)


@pytest.fixture
def zipp(monkeypatch):
    """A client without sockets or threads; read-back timers are disabled."""
    z = LibratoneZipp.__new__(LibratoneZipp)
    z.host = "192.0.2.1"
    z.state = None
    z._cleanup_variables()
    z.sent = []
    monkeypatch.setattr(z, "set_control_command", lambda command, data=None: z.sent.append((command, data)) or True)
    monkeypatch.setattr(z, "_get_later", lambda getter: None)
    return z


def feed(zipp, command, data):
    """Deliver a reply as the speaker would send it."""
    packet = LibratoneMessage.LibratoneMessage(command=command).get_packet()
    packet = bytearray(packet[:8]) + len(data).to_bytes(2, "big") + bytearray(data)
    zipp.process_zipp_message(packet, 7778)


def test_message_length_counts_bytes_not_characters():
    message = LibratoneMessage.LibratoneMessage(command=276, data='{"channel_name": "Märchen"}')
    packet = message.get_packet()
    payload = bytes(packet[10:])
    assert int.from_bytes(packet[8:10], "big") == len(payload)
    assert payload.decode("utf-8") == '{"channel_name": "Märchen"}'


def test_set_command_status_is_one_byte():
    message = LibratoneMessage.LibratoneMessage(command=1, commandStatus=1)
    assert len(message.get_packet()) == 10


def test_empty_player_reply_does_not_raise(zipp):
    feed(zipp, 278, b"")
    assert zipp.play_title is None
    assert zipp._player_json is None


def test_player_reply_is_parsed(zipp):
    feed(zipp, 278, json.dumps({"play_title": "Mozart", "play_subtitle": "Klassik", "play_identity": "4"}).encode())
    assert (zipp.play_title, zipp.play_subtitle, zipp.play_identity) == ("Mozart", "Klassik", "4")


def test_numeric_settings(zipp):
    feed(zipp, 300, b"66")
    feed(zipp, 296, b"1")
    feed(zipp, 293, b"0")
    feed(zipp, 515, b"2")
    assert (zipp.max_volume, zipp.led_level, zipp.voice_prompt, zipp.stereo_type) == ("66", "1", "0", "2")


def test_battery_charging_wifi(zipp):
    feed(zipp, 257, b"100")
    feed(zipp, 1284, b"2")
    feed(zipp, 529, b" ,-45,65/70")
    assert zipp.battery_percent == 100
    assert zipp.is_charging is False
    assert zipp.wifi_rssi == -45
    assert zipp.wifi_quality_percent == 93
    feed(zipp, 1284, b"1")
    assert zipp.is_charging is True


def test_values_are_none_before_the_speaker_answered(zipp):
    assert zipp.battery_percent is None
    assert zipp.is_charging is None
    assert zipp.wifi_rssi is None
    assert zipp.wifi_quality_percent is None
    assert zipp.is_muted is None
    assert zipp.source_type is None
    assert zipp.shuffle is None
    assert zipp.firmware_update is None
    assert zipp.favorites == []


def test_mute_status(zipp):
    feed(zipp, 520, b"MUTE,14")
    assert zipp.is_muted is True
    feed(zipp, 520, b"UNMUTE")
    assert zipp.is_muted is False


def test_mute_and_unmute_send_play_control(zipp):
    zipp.mute()
    zipp.unmute()
    assert zipp.sent == [(40, "MUTE"), (40, "UNMUTE")]


@pytest.mark.parametrize("raw, expected", [
    (b'{"state" : 0, "err" : 0}', ("none", 0)),
    (b'{"state" : 1, "err" : 0}', ("available", 0)),
    (b'{"state" : 6, "err" : 3}', ("mandatory", 3)),
    (b'{"state" : 99, "err" : 0}', ("unknown", 0)),
])
def test_firmware_update_state(zipp, raw, expected):
    feed(zipp, 66, raw)
    assert zipp.firmware_update == expected


def test_firmware_update_garbage_is_none(zipp):
    feed(zipp, 66, b"not json")
    assert zipp.firmware_update is None


def test_source_info_preset_while_playing(zipp):
    feed(zipp, 10, b"?\x11\x00E\x03\x00\x00")   # captured from a Zipp 2 while a preset played
    assert zipp.source_code == 63
    assert zipp.source_type == "preset"
    assert zipp.supports_play_mode is False


def test_source_info_idle(zipp):
    feed(zipp, 10, b"0\x00\x00\x00\x00\x00\x00")
    assert zipp.source_type == "none"


def test_source_info_ability_flag_enables_play_mode(zipp):
    ability = (1 | 262144).to_bytes(4, "little")
    feed(zipp, 10, bytes([65, 0, 0]) + ability)
    assert zipp.source_type == "bluetooth"
    assert zipp.supports_play_mode is True


def test_unknown_source_code_is_other(zipp):
    feed(zipp, 10, bytes([200, 0, 0, 0, 0, 0, 0]))
    assert zipp.source_type == "other"


def test_source_types_use_ascii_codes():
    assert SOURCE_TYPES[ord("?")] == "preset"
    assert SOURCE_TYPES[ord("0")] == "none"
    assert SOURCE_TYPES[ord("A")] == "bluetooth"


@pytest.mark.parametrize("mode_id, shuffle, repeat", [
    ("0", False, "off"), ("1", True, "all"), ("2", False, "one"),
    ("3", False, "all"), ("6", True, "off"), ("7", True, "one"),
])
def test_play_mode_round_trip(zipp, mode_id, shuffle, repeat):
    feed(zipp, 1541, mode_id.encode())
    assert (zipp.shuffle, zipp.repeat) == (shuffle, repeat)
    zipp.play_mode_set(shuffle, repeat)
    assert zipp.sent[-1] == (1541, mode_id)


def test_play_mode_tables_are_inverse():
    assert len(PLAY_MODE_IDS) == len(PLAY_MODES)


def test_favorites(zipp):
    channels = [
        {"channel_id": 1, "channel_identity": "77320", "channel_name": "Klassik Radio Classic Dreams", "channel_type": "vtuner"},
        {"channel_id": 2, "channel_identity": "78933", "channel_name": "Klassik Radio Healing Spirit", "channel_type": "vtuner"},
    ]
    feed(zipp, 275, json.dumps(channels).encode())
    assert [c["channel_id"] for c in zipp.favorites] == [1, 2]
    assert zipp.favorite_name(2) == "Klassik Radio Healing Spirit"
    assert zipp.favorite_name(5) is None
    assert zipp.favorite_slot_by_name("Klassik Radio Classic Dreams") == 1
    assert zipp.favorite_slot_by_name("nope") is None


def test_favorite_set_sends_the_channel_json(zipp):
    zipp.favorite_set(5, 77317, "Märchen & Öl")
    command, data = zipp.sent[-1]
    assert command == 276
    assert json.loads(data) == {
        "channel_id": 5, "channel_identity": "77317", "channel_name": "Märchen & Öl", "channel_type": "vtuner",
    }


def test_setters_clamp_and_remember(zipp):
    zipp.max_volume_set(150)
    zipp.led_level_set(-3)
    zipp.voice_prompt_set(True)
    zipp.stereo_type_set("left")
    assert zipp.sent == [(300, "100"), (296, "0"), (293, "1"), (512, "1")]
    assert (zipp.max_volume, zipp.led_level, zipp.voice_prompt, zipp.stereo_type) == ("100", "0", "1", "1")


def test_unknown_stereo_type_is_rejected(zipp):
    with pytest.raises(KeyError):
        zipp.stereo_type_set("centre")


def test_firmware_states_cover_the_apps_values():
    assert sorted(FW_UPDATE_STATES) == [0, 1, 2, 3, 4, 5, 6]
