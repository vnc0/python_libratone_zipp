# Libratone Zipp controller library in Python

This aims to control one or multiple Libratone Zipp speaker with a Python library, potentially usable in [Home Assistant](https://www.home-assistant.io/) with [this module](https://github.com/Chouffy/home_assistant_libratone_zipp).

Install it with `pip install python-libratone-zipp` - [pip page](https://pypi.org/project/python-libratone-zipp/)

Tested with Libratone Zipp 1, firmware 809, 879 and Libratone Zipp 2, firmware 1536.


## Usage

See example in `CLI.py`. You have to be able to listen to `3333/udp` and `7778/udp`!

Other files:

* `Test_SendCommandReceiveMessage.py` is used to shoot one command for tests purposes.
* `Test_LibratoneMessage.py` is to check LibratoneMessage class against a real message
* `Test_Sockethub.py` is to check if you can recieve information from multiple speakers at once

## Functionality coverage

Besides the original coverage, version 4.2.0 adds the values and commands marked below. They were found by decompiling the Android app
and checked on a Libratone Zipp 2 (firmware 1536). Pass `data` strings as UTF-8; the speaker reads station names with umlauts.

* Module
    * [x] Clean text variables, declare variable on top instead of using text like "play"
    * [x] Create a Command Line Interface - CLI client
    * [x] Publish on PyPi
    * [x] Handle exit properly - but need max _KEEPALIVE_CHECK_PERIOD seconds to exit
    * [x] Make the module usable with multiple speaker
    * [ ] Use discovery method instead of fixed IP
    * [ ] Make the module compatible with async from Home Assistant
* Playback status with Spotify & Radio
    * [x] Retrieve basic playback status: play, pause, stop
    * [x] Retrieve volume
    * [x] Retrieve current playback source
    * [x] Retrieve current title
    * [x] Retrieve mute status - but no logic implemented!
* Playback with Bluetooth or USB
    * [ ] Retrieve basic playback status: play, pause, stop
    * [x] Retrieve media type: Bluetooth, aux, radio, ... (`source_type`)
    * [x] Retrieve and set extended playback status: shuffle, repeat (not tested with a source that supports it)
* Playback control
    * [x] Set basic playback status: play, pause, stop, next, prev
    * [x] Set volume, mute and unmute (`mute()`, `unmute()`, `is_muted`)
* Standby
    * [x] Retrieve actual speaker state
    * [x] Calculate actual speaker state: UNKOWN, SLEEPING, ON, PLAYING, PAUSED, STOPPED
    * [x] Set to immediate standby and wakeup
    * [x] Set a standby timer
    * [x] Retrieve the defined duration of the standby timer
    * [ ] Calculate the actual standby timer
* Voicing & Room Setting
    * [x] Set a Voicing
    * [x] Retrieve active Voicing
    * [x] Retrieve all Voicing
    * [x] Set Room Setting
    * [x] Retrieve current Room Setting
    * [x] Retrieve all Room
* Favorites
    * [x] Play a Favorite
    * [x] List the configured favorites (`favorites`, `favorite_name()`, `favorite_slot_by_name()`)
    * [x] Set a Favorite (`favorite_set()`, needs the vTuner station id)
* Extended current playback info
    * [x] Retrieve current source and media type (`source_code`, `source_type`)
    * [x] Set and retrieve shuffle and repeat (`play_mode_set()`, `shuffle`, `repeat`; only while `supports_play_mode`)
    * [ ] Set Source (see "Input source")
* Speaker configuration
    * [x] Retrieve current firmware
    * [x] Retrieve the firmware update state the speaker reports (`firmware_update`)
    * [x] Retrieve speaker name
    * [x] Retrieve speaker color
    * [x] Set speaker name
    * [ ] Map out color codes + Set speaker color
    * [x] Retrieve current serial number
    * [x] Retrieve current battery level and charging state (`battery_percent`, `is_charging`)
    * [x] Set and retrieve the maximum volume, LED level and voice prompts
    * [x] Set and retrieve the speaker channel: stereo, left, right (`stereo_type_set()`)
    * [ ] Retrieve AC information
* Network
    * [ ] Retrieve current IP
    * [ ] Retrieve current Wi-Fi configuration
    * [x] Retrieve current Wi-Fi information
    * [ ] Set Wi-Fi configuration
* Multi-room
    * [x] Implement SoundSpace Link

### Unimplemented commands

Commands that were identified but are not implemented or not understood well enough. The list is not exhaustive.

From Android application, `com.libratone.v3.model.LSSDPNode`:
command|function|notes
-|-|-
103 | fetchDeviceState
121 | setSwitch_Source | accepted (status 1) on a Zipp 2 but no effect on the active source was seen (see "Input source" below)
122 | setOutputSource | works on a Zipp 2, see "Input source" below; not wrapped yet
123 / 128 | available / current output source | the Zipp 2 answers a bit mask (`0x01` Bluetooth, `0x02` speaker, `0x04` AUX), the app parses characters
152 | fetchSource | the Zipp 2 answered 8 binary bytes, not the characters the app parses
281 | fetchMusicServiceCapability | Answer a JSON
304 | fetchLimitedFunctionList | Answer 3 bytes
530 | fetchOtaAutoDownLoadStatus
537 | fetchWifiLinein / setWifiLinein | accepted on a Zipp 2 without a visible effect
65 / 66 | firmware update commands | only the state is read (66); installing is not implemented
1285| fetchPrivateMode
1536| fetchUsbCurrentPlayId
1537| fetchUsbPlayMode
1538| fetchUsbSongInfo

### Input source

Looked at on a Zipp 2 (firmware 1536) while a preset station played. `SET 537` (line in) and `SET 121 = 0` (Bluetooth) are answered
with status 1 like a successful command, but the active source (`SourceInfo`, command 10) did not change and nothing was heard.
That may depend on a cable or a paired device being present. `SET 122 = 0 / 1 / 2` changes the *output* instead (command 128 then reads
`0x01`, `0x02`, `0x04`; the original value was `0x02`, the speaker itself) and was reverted after the test. Selecting an input is
therefore not offered.

## Tests

`python -m pytest tests` runs offline tests of the parsing and packet building. They need no speaker and no open ports.

## Acknowledgment

This work is based on the following:

* The Libratone command list is [coming from this work from Benjamin Hanke](https://www.loxwiki.eu/display/LOX/Libratone+Zipp+WLan+Lautsprecher)
* A lot of further work is based on APK decompilation
* Entity to use: [Media Player](https://developers.home-assistant.io/docs/core/entity/media-player)
* Example of [integrations](https://www.home-assistant.io/integrations/#media-player):
    * Simple: [Harman Kardon AVR integration](https://www.home-assistant.io/integrations/harman_kardon_avr/) which use [this module](https://github.com/Devqon/hkavr)
    * Simple: [Clementine Music Player integration](https://github.com/home-assistant/core/blob/dev/homeassistant/components/clementine/media_player.py)
    * Async: [Frontier Silicon integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/frontier_silicon) with [this module](https://github.com/zhelev/python-afsapi/tree/master/afsapi)
    * Async with extended features: [Yamaha integration](https://github.com/home-assistant/core/blob/dev/homeassistant/components/yamaha/) with [this module](https://github.com/wuub/rxv)
    * Async and simple: [anthemav integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/anthemav) with [this module](https://github.com/nugget/python-anthemav/tree/master/anthemav)

## License

See LICENSE file
