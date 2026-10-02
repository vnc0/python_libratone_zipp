#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Control Library for Libratone speakers like Libratone Zipp.
License: see LICENSE file
"""

import logging
import json
import sys
import time
import socket
import threading
import re

from . import LibratoneMessage

from .socket_hub import SocketHub

USE_SOCKET_HUB = True  # set to True to use the shared sockets (3333/7778)

_hub_singleton = None
_hub_lock = threading.Lock()

def _get_hub():
    """Thread-safe lazy init of the shared SocketHub."""
    global _hub_singleton
    if _hub_singleton is None:
        with _hub_lock:
            if _hub_singleton is None:
                from .socket_hub import SocketHub
                _hub_singleton = SocketHub()
    return _hub_singleton

_GET_LIFECYCLE_VALUES = 1       # 3 seconds wait between asking lifecycle values (like all voicing) and asking current values(like voicing)

_LOG_ALL_PACKET = False         # Log all packet
_LOG_UNKNOWN_PACKET = False     # Log unknown packet
_LOGGER_PRINT = False           # Redirect logger to stdout, otherwise standard Home Assistant logger

if _LOGGER_PRINT:
    _log_level=logging.DEBUG 
    _log_format = logging.Formatter('[%(asctime)s] [%(levelname)s] - %(message)s')
    _LOGGER = logging.getLogger(__name__)                                  
    _LOGGER.setLevel(_log_level)                                       

    # writing to stdout                                                     
    handler = logging.StreamHandler(sys.stdout)                             
    handler.setLevel(_log_level)                                        
    handler.setFormatter(_log_format)                                        
    _LOGGER.addHandler(handler)                                            

    _LOGGER.debug("Logging has been setup")                                                   
else:
    _LOGGER = logging.getLogger("LibratoneZipp")

# Define fixed variables
STATE_UNKNOWN = "UNKNOWN"
STATE_SLEEP = "SLEEPING"
STATE_ON = "ON"
STATE_PLAY = "PLAYING"
STATE_PAUSE = "PAUSED"
STATE_STOP = "STOPPED"

POWERMODE_AWAKE = "AWAKE"
POWERMODE_SLEEP = "SLEEP"

PLAYSTATUS_PLAY = STATE_PLAY
PLAYSTATUS_PAUSE = STATE_PAUSE
PLAYSTATUS_STOP = STATE_STOP

# Define network variables
_UDP_CONTROL_PORT = 7777                 # Port to send a command
_UDP_RESULT_PORT = 7778                  # Port to receive the result of a command??
_UDP_NOTIFICATION_SEND_PORT = 3334       # Port to send ack to the speaker after a notification
_UDP_NOTIFICATION_RECEIVE_PORT = 3333    # Port to receive notification from the speaker

_UDP_BUFFER_SIZE = 4096                 # 4096 in order to receive Channel data
_KEEPALIVE_CHECK_PERIOD = 60            # Time in second between each keep-alive check 

_GET_SPACING = 0.3                      # Seconds between two GET requests of a get_all() cycle (the speaker drops bursts)
_CONFIRM_DELAY = 0.8                    # Seconds to wait after a SET before reading the value back

# Define Zipp commands ID
_COMMAND_TABLE = {
    # com.libratone.model.LSSDPNode , fetchAllForWifi contain all useful fonctions 
    'Version': {
        '_get': 5,      # from com.libratone.model.LSSDPNode, fetchVersion
    },
    'CurrPowerMode': {
        '_get': 14,     # from com.libratone.model.LSSDPNode, fetchCurrPowerMode - reply in dec, not ASCII - see _currpowermode_parsing 
        'awake': 48,    # from observation
        'sleeping': 50, # from observation
    },
    'Timer': {
        # Used for sleep timer
        '_get': 15,     # from com.libratone.model.LSSDPNode, setOffTime - format for timer data is "2" + j, j being seconds      
        '_set': 15,     # from com.libratone.model.LSSDPNode, setPowerMode - see _timer_parse for parsing 
    },
    'PlayControl': {
        '_set': 40,     # # from com.libratone.model.LSSDPNode, setPlayControl - see below for data
        # from com.libratone.luci.PlayControlCommand
        'play': 'PLAY',
        'stop': 'STOP',
        'pause': 'PAUSE',
        'next': 'NEXT',
        'prev': 'PREV',
        'mute': 'MUTE',
        'unmute': 'UNMUTE',
    },
    'PlayStatus': {
        '_get': 51,     # from com.libratone.model.LSSDPNode, fetchPlayStatus - see below for data
        # from com.libratone.luci.PlayControlCommand - more state are defined
        'play': b'0',
        'stop': b'1',
        'pause': b'2',
    },
    'Volume': {
        '_get': 64,     # from com.libratone.model.LSSDPNode, fetchVolume
        '_set': 64,     # from com.libratone.model.LSSDPNode, setVolume - expect data with volume 0...100
    },
    'Name': {
        '_get': 90,     # from com.libratone.model.LSSDPNode, fetchDeviceName
        '_set': 90,     # from com.libratone.model.LSSDPNode, setName - expect data with wished device name
    },
    'BatteryLevel': {
        '_get': 256,     # from com.libratone.model.LSSDPNode, fetchBatteryLevel - answer "" on _get, true vale on _get2
        '_get2': 257,    # Received when BatteryLevel_get is sent - answer "59" for instance
    },
    'Channel': {
        '_get': 275,     # from com.libratone.model.LSSDPNode, fetchChannel - answer JSON like [{"channel_id" : 1,"channel_identity" : "31375","channel_name" : "Radio Meuh","channel_type" : "vtuner","isPlaying" : false,"play_token" : ""}, ...]
    },
    'Player': {
        '_get': 278,    # from com.libratone.model.LSSDPNode, fetchPlayer
        '_set': 277,    # from com.libratone.model.LSSDPNode, setPlayer - see below for data
        # Favorites, captured:
        # TODO check play_identity 
        'favorite': {
            '1': '{"isFromChannel":false,"play_identity":"1","play_subtitle":"1","play_title":"channel","play_type":"channel","token":""}',
            '2': '{"isFromChannel":false,"play_identity":"2","play_subtitle":"2","play_title":"channel","play_type":"channel","token":""}',
            '3': '{"isFromChannel":false,"play_identity":"3","play_subtitle":"3","play_title":"channel","play_type":"channel","token":""}',
            '4': '{"isFromChannel":false,"play_identity":"4","play_subtitle":"4","play_title":"channel","play_type":"channel","token":""}',
            '5': '{"isFromChannel":false,"play_identity":"5","play_subtitle":"5","play_title":"channel","play_type":"channel","token":""}',
        },
    },
    'Voicing': {
        '_get': 516,    # from com.libratone.model.LSSDPNode, fetchVoicing - you'll get a V100-like code
        '_set': 518,    # from com.libratone.model.LSSDPNode, setVoicing - see below for data in '_data' like V100
        '_getAll': 524, # from com.libratone.model.LSSDPNode, fetchAllVoicing - you'll get a JSON like [{"description":"Basic neutral setting","name":"Neutral","voicingId":"V100"}, ...]
    },
    'Room': {
        '_get': 517,    # from com.libratone.model.LSSDPNode, fetchFullroom - will return a voicingId defined in getAll like "neutral"
        '_set': 519,    # from com.libratone.model.LSSDPNode, setFullRoom - expect a voicingId defined in getAll like "neutral"
        '_getAll': 525, # from com.libratone.model.LSSDPNode, fetchAllFullRoom - will return a JSON like [{"description":"Basic neutral setting","name":"Neutral","voicingId":"neutral"}, ...]
    },
    'MuteStatus': {
        '_get': 520     # from com.libratone.model.LSSDPNode, fetchMuteStatus - answer "UNMUTE" for instance
    },
    'SignalStrength': {
        '_get': 529     # from com.libratone.model.LSSDPNode, fetchSignalStrength - answer "-86,-42,5/5" for instance
    },
    'SerialNumber': {
        '_get': 769     # from com.libratone.model.LSSDPNode, fetchSerialNum - answer "1234-A1234567-12-12345" for instance
    },
    'DeviceColor': {
        '_get': 770,     # from com.libratone.model.LSSDPNode, fetchDeviceColor - answer "1001" for instance for Pepper Black and "2005" for Sangria
        '_set': 771     # from com.libratone.model.LSSDPNode, setDeviceColor - answer "1001" for instance for Pepper Black and "2005" for Sangria
    },
    'ChargingStatus': {
        # Used for trigger
        '_get': 1284,   # from com.libratone.model.LSSDPNode, fetchChargingStatus
    },
    'MaxVolume': {
        '_get': 300,    # from com.libratone.model.LSSDPNode, fetchMaxVolume
        '_set': 300,    # setMaxVolume - data "0".."100"
    },
    'LedLevel': {
        '_get': 296,    # from com.libratone.model.LSSDPNode, fetchCurrentLedDisplayLevel
        '_set': 296,    # setCurrentLedDisplayLevel - data "0".."2"
    },
    'VoicePrompt': {
        '_get': 293,    # from com.libratone.model.LSSDPNode, fetch(293)
        '_set': 293,    # data "1" on, "0" off
    },
    'StereoType': {
        '_get': 515,    # from com.libratone.model.LSSDPNode, fetchSpeakerStereoType
        '_set': 512,    # setSpeakerStereoType - data "0" stereo, "1" left, "2" right
    },
    'FavoriteSet': {
        '_set': 276,    # from com.libratone.model.LSSDPNode, setChannel - data is the JSON of one channel
    },
    'FirmwareUpdate': {
        '_get': 66,     # fetchDeltaNFirmwareUpdateStatus - GET with data "0" answers {"state": n, "err": n}
    },
    'SourceInfo': {
        '_get': 10,     # fetchSourceInfo - bytes: source code, sn, status, ability flags (4 bytes, little endian)
    },
    'PlayMode': {
        '_get': 1541,   # fetch/set play mode, see PLAY_MODES
        '_set': 1541,
    },
    'Group': {
        '_notif': 103,   # UDP 3333: e.g. 'MASTER,LINK ...', 'SLAVE,LINK ...'
        '_join':  502,   # 0x01F6: control write with 'LINK <link_id>'  (join)
        '_leave': 503,   # 0x01F7: control write with 'LINK <link_id>'  (leave)
   },
}

# Values of the additional commands - see the section at the end of the class
STEREO_TYPES = {"0": "stereo", "1": "left", "2": "right"}
STEREO_TYPE_IDS = {name: type_id for type_id, name in STEREO_TYPES.items()}

# Firmware update state (command 66, GET with data "0"); names from the Android app's log texts
FW_UPDATE_STATES = {
    0: "none",            # no valid update package
    1: "available",       # valid package found, not downloaded yet
    2: "downloading",
    3: "ready",           # downloaded, can be installed
    4: "updating",        # installing, the speaker restarts
    5: "updated",         # finished after the reboot
    6: "mandatory",       # mandatory package ready
}

# Active source (command 10, byte 0): the ASCII value of the Android app's SourceInfo constants
SOURCE_TYPES = {
    48: "none",
    49: "airplay",
    50: "dlna",
    51: "dlna",
    52: "spotify",
    53: "usb",
    54: "sd_card",
    57: "tunein",
    59: "group",           # follower in a multi-room group
    60: "line_in",
    62: "url",
    63: "preset",          # favorite / preset station
    65: "bluetooth",
    66: "aux",
    68: "usb",
    85: "bluetooth",
    88: "voice",
    89: "voice",
    93: "voice",
    105: "bluetooth",
}
SOURCE_TYPE_OPTIONS = sorted(set(SOURCE_TYPES.values()) | {"other"})
_ABILITY_SET_PLAY_MODE = 262144    # bit 18 of the source's ability flags: shuffle / repeat can be set

# Play mode (command 1541) as in the Android app's PlayMode enum: value -> (shuffle, repeat)
PLAY_MODES = {
    "0": (False, "off"),
    "1": (True, "all"),
    "2": (False, "one"),
    "3": (False, "all"),
    "6": (True, "off"),
    "7": (True, "one"),
}
PLAY_MODE_IDS = {mode: mode_id for mode_id, mode in PLAY_MODES.items()}

# Check if host is up
def host_up(host, port=80):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, port))
    except socket.error:
        return False
    sock.close()
    del sock
    return True

class LibratoneZipp:
    """Representing a Libratone Zipp device."""

    # host is IP of Zipp
    def __init__(self, host):

        # Configuration set by class client
        self.host = host
        
        # after self.host = host and normal state initialization

        if USE_SOCKET_HUB:
            # Use shared sockets; do NOT bind per device
            _get_hub().register(self)
            self._listening_notification_flag = False
            self._listening_notification_thread = None
            self._listening_notification_socket = None
            self._listening_result_flag = False
            self._listening_result_thread = None
            self._listening_result_socket = None
        else:
            # ORIGINAL per-device sockets (unchanged)
            self._listening_notification_flag = True
            (self._listening_notification_socket,
                self._listening_notification_thread) = self._get_new_socket(
                receive_port=_UDP_NOTIFICATION_RECEIVE_PORT,
                trigger_port=_UDP_CONTROL_PORT,
                ack_port=_UDP_NOTIFICATION_SEND_PORT,
            )
            self._listening_result_flag = True
            (self._listening_result_socket,
                self._listening_result_thread) = self._get_new_socket(
                receive_port=_UDP_RESULT_PORT
            )            
        # TODO Update all variables to be set to Null when disconnect

        # Variables fixed for the lifecycle
        self.version = None
        self.name = None
        self.serialnumber = None
        
        # Active variables
        self._currpowermode = None
        self._playstatus = None
        self.volume = None
        self.batterylevel = None
        self.chargingstatus = None
        self.timer = None           # Timer in seconds, None if no timers active
        self.signalstrenght = None
        self.devicecolor = None
        self.mutestatus = None

        # Additional values - see the section at the end of the class
        self.max_volume = None             # Volume cap in %, str
        self.led_level = None              # "0".."2"
        self.voice_prompt = None           # "1" on, "0" off
        self.stereo_type = None            # "0" stereo, "1" left, "2" right
        self.firmware_update_raw = None    # JSON text {"state": n, "err": n}
        self.source_info = None            # bytes, see source_code / source_type
        self.play_mode = None              # see PLAY_MODES

        # Active variables as JSON list - see command table
        self._voicing_list_json = None   
        self._room_list_json = None      
        self._player_json = None
        self._channel_json = None

        # Calculated variables
        self.state = None               # STATE_OFF in self.state_refresh() or STATE_PLAY/STOP/PAUSE in process_zipp_message() initiated from 
        self.room = None                # voicingId converted to Name for Room
        self.voicing = None             # voicingId converted to Name for Voicing
        self.room_list = None           # List of Room "name"
        self.voicing_list = None        # List of Voicing "name"
        # Variables from Player
        self.isFromChannel = None
        self.play_identity = None
        self.play_preset_available = None
        self.play_subtitle = None
        self.play_title = None
        self.play_token = None
        self.play_type = None

        # Grouping
        self.group_status = None      # "GROUPED" / "UNGROUPED" / None
        self.group_link_id = None     
        self.group_last_notifier = None
        self.group_role = None        # "MASTER" | "SLAVE" | None

        # Network

        ## Setup 3rd thread to make regular call to Zipp in order to update status in case of desync
        self._keepalive_flag = True
        self._keepalive_thread = threading.Thread(target=self._keepalive_check, name="Zipp_keepalive", args=[])
        self._keepalive_thread.start()


    # Clean up all defined variables
    def _cleanup_variables(self):
        self.version = None
        self.name = None
        self.serialnumber = None
        self._currpowermode = None
        self._playstatus = None
        self.volume = None
        self.batterylevel = None
        self.chargingstatus = None
        self.timer = None           
        self.signalstrenght = None
        self.devicecolor = None
        self.mutestatus = None
        self._voicing_list_json = None   
        self._room_list_json = None      
        self._player_json = None
        self._channel_json = None
        self.room = None
        self.voicing = None
        self.room_list = None
        self.voicing_list = None
        self.isFromChannel = None
        self.play_identity = None
        self.play_preset_available = None
        self.play_subtitle = None
        self.play_title = None
        self.play_token = None
        self.play_type = None
        self.group_status = None     
        self.group_link_id = None     
        self.group_last_notifier = None
        self.group_role = None
        self.max_volume = None
        self.led_level = None
        self.voice_prompt = None
        self.stereo_type = None
        self.firmware_update_raw = None
        self.source_info = None
        self.play_mode = None

    # Close the two socket thread by changing the flag and sending two packet to receive two answer on 2 ports
    def exit(self):
        self._listening_notification_flag = False
        self.set_control_command(command=_COMMAND_TABLE['Volume']['_set'], data=self.volume)
        self._listening_result_flag = False
        self.get_control_command(command=_COMMAND_TABLE['Version']['_get'])
        self._keepalive_flag = False
        self._cleanup_variables()
        _LOGGER.info("Disconnected from Libratone Zipp, waiting for last packets and keepalive thread.")
        if USE_SOCKET_HUB:
            try:
                _get_hub().unregister(self)
            except Exception:
                pass

    # Do a state_refresh every _KEEPALIVE_CHECK_PERIOD seconds to update self.state
    def _keepalive_check(self):
        _LOGGER.info("Keep-alive thread started.")
        while(self._keepalive_flag):
            self.state_refresh()
            time.sleep(_KEEPALIVE_CHECK_PERIOD)
        _LOGGER.info("Keep-alive thread closed.")

    # Log messgaes in a pretty way
    def log_zipp_messages(self, command, data, port):
        try: pretty_data = data.decode()
        except: pretty_data = data
        _LOGGER.info("Port:" + str(port) + " Command:" + str(command) + "\tData:" + str(pretty_data))

    # Interpret message from Zipp
    def process_zipp_message(self, packet: bytearray, receive_port):
        
        zipp_message = LibratoneMessage.LibratoneMessage(packet=packet)
        command = zipp_message.get_command_int()
        data = zipp_message.data

        if _LOG_ALL_PACKET: self.log_zipp_messages(command=command, data=data, port=receive_port)

        if data == "": pass # Skip everything which do not have any data in it
        elif command == _COMMAND_TABLE['PlayStatus']['_get']:
            if data == _COMMAND_TABLE['PlayStatus']['play']: self._playstatus = PLAYSTATUS_PLAY
            elif data == _COMMAND_TABLE['PlayStatus']['stop']: self._playstatus = PLAYSTATUS_STOP
            elif data == _COMMAND_TABLE['PlayStatus']['pause']: self._playstatus = PLAYSTATUS_PAUSE
            self._state_calculate()
        elif command == _COMMAND_TABLE['CurrPowerMode']['_get']:
            if data[0] == _COMMAND_TABLE['CurrPowerMode']['awake']: self._currpowermode = POWERMODE_AWAKE
            elif data[0] == _COMMAND_TABLE['CurrPowerMode']['sleeping']: self._currpowermode = POWERMODE_SLEEP
            self._state_calculate()
        elif command == _COMMAND_TABLE['Channel']['_get']:
            try: self._channel_json = json.loads(data.decode())
            except: self._channel_json = None
        elif command == _COMMAND_TABLE['Voicing']['_get'] or command == _COMMAND_TABLE['Voicing']['_set']: self.voicing = self._voicingid_to_name(voicingid=data.decode(), json_list=self._voicing_list_json)
        elif command == _COMMAND_TABLE['Room']['_get'] or command == _COMMAND_TABLE['Room']['_set']: self.room = self._voicingid_to_name(voicingid=data.decode(), json_list=self._room_list_json)
        elif command == _COMMAND_TABLE['Voicing']['_getAll']: self._voicing_list_update_from_raw(data.decode())
        elif command == _COMMAND_TABLE['Room']['_getAll']: self._room_list_update_from_raw(data.decode())
        elif command == _COMMAND_TABLE['Player']['_get']: self._player_parse(player_data=data.decode())
        elif command == _COMMAND_TABLE['Timer']['_get']: self.timer = self._timer_parse(data)
        elif command == _COMMAND_TABLE['Name']['_get']: self.name = data.decode()
        elif command == _COMMAND_TABLE['Version']['_get']: self.version = data.decode()
        elif command == _COMMAND_TABLE['Volume']['_get']: self.volume = data.decode()
        elif command == _COMMAND_TABLE['ChargingStatus']['_get']: self.chargingstatus = data.decode()
        elif command == _COMMAND_TABLE['SignalStrength']['_get']: self.signalstrenght = data.decode()
        elif command == _COMMAND_TABLE['SerialNumber']['_get']: self.serialnumber = data.decode()
        elif command == _COMMAND_TABLE['MuteStatus']['_get']: self.mutestatus = data.decode()
        elif command == _COMMAND_TABLE['DeviceColor']['_get'] or command == _COMMAND_TABLE['DeviceColor']['_set']: self.devicecolor = data.decode()
        elif command == _COMMAND_TABLE['BatteryLevel']['_get'] or command == _COMMAND_TABLE['BatteryLevel']['_get2']: self.batterylevel = data.decode()
        elif command == _COMMAND_TABLE['MaxVolume']['_get']: self.max_volume = self._text(data)
        elif command == _COMMAND_TABLE['LedLevel']['_get']: self.led_level = self._text(data)
        elif command == _COMMAND_TABLE['VoicePrompt']['_get']: self.voice_prompt = self._text(data)
        elif command == _COMMAND_TABLE['StereoType']['_get'] or command == _COMMAND_TABLE['StereoType']['_set']: self.stereo_type = self._text(data)
        elif command == _COMMAND_TABLE['FirmwareUpdate']['_get']: self.firmware_update_raw = self._text(data)
        elif command == _COMMAND_TABLE['SourceInfo']['_get']: self.source_info = bytes(data)
        elif command == _COMMAND_TABLE['PlayMode']['_get']: self.play_mode = self._text(data)

        elif command == _COMMAND_TABLE['Group']['_notif']:
            try:
                s = data.decode(errors="ignore").strip()
            except Exception:
                s = ""
            # Defensive: some captures showed a leading ':' or '=' — strip non-alnum at start
            while s and not s[0].isalnum():
                s = s[1:]
            su = s.upper()
            # Accept: "GROUPED,LINK ...", "MASTER,LINK ...", "SLAVE,LINK ..."
            m = re.match(r'^(GROUPED|MASTER|SLAVE),LINK\s+(.+)$', su)
            if m:
                self.group_status = "GROUPED"
                self.group_role = m.group(1)  # keep original role
                # Use the original-cased string for link_id if possible
                try:
                    self.group_link_id = s.split(" ", 1)[1].strip()
                except Exception:
                    self.group_link_id = None
            elif "UNGROUP" in su or "UNLINK" in su:               
                self.group_status = "UNGROUPED"
                self.group_link_id = None
                self.group_role = None
            else:
                # Unknown group message; record raw for debugging
                self.group_status = f"UNKNOWN({s})"
                self.group_role = None

        else:
            if _LOG_UNKNOWN_PACKET: self.log_zipp_messages(command=command, data=data, port=receive_port)
            else: pass

    # Wait for a message from the Zipp, start a thread to process it and send an ACK to _UDP_NOTIFICATION_SEND_PORT = 3334
    def listen_incoming_zipp_notification(self, socket, receive_port, ack_port=None):
        _LOGGER.info("Listening incoming Zipp messages on %s", str(receive_port))
        while(self._listening_notification_flag):
            # Wait for new packet; address is the originating IP:port
            try:
                message, address = socket.recvfrom(_UDP_BUFFER_SIZE)
                thread = threading.Thread(target=self.process_zipp_message, name="Process_Zipp_Message", args=[message, receive_port])
                thread.start()

                # Send the ack
                if ack_port != None: socket.sendto(LibratoneMessage.LibratoneMessage(command=0).get_packet(), (self.host, _UDP_NOTIFICATION_SEND_PORT))
            except:
                _LOGGER.info("Connection closed! Port %s", str(receive_port))
                self.state = STATE_UNKNOWN
                while(self.state == STATE_UNKNOWN):
                    time.sleep(_KEEPALIVE_CHECK_PERIOD)
        _LOGGER.info("Stopped listening Zipp messages on %s", str(receive_port))

    # Create a socket, start a thread to manage incoming messages from receive_port and send a trigger to trigger_port
    
    def _get_new_socket(self, receive_port, trigger_port=None, ack_port=None):
        """Create one UDP socket bound to receive_port, start its recv thread, and optionally send a trigger."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Optional: on some OSes this helps quick restarts; does NOT allow two binds simultaneously.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            print(f"[LZ] binding receive_port {receive_port}")
            s.bind(("", receive_port))

            # Start the listener thread AFTER bind
            t = threading.Thread(
                target=self.listen_incoming_zipp_notification,
                name=f"Listen_incoming_{receive_port}",
                args=[s, receive_port, ack_port],
                daemon=True,
            )
            t.start()

            # Optional trigger to kick traffic (same as your original intent)
            if trigger_port is not None:
                try:
                    pkt = LibratoneMessage.LibratoneMessage(
                        command=_COMMAND_TABLE["ChargingStatus"]["_get"]
                    ).get_packet()
                    s.sendto(pkt, (self.host, trigger_port))
                except Exception as e:
                    _LOGGER.warning("Trigger send failed on port %s: %s", trigger_port, e)

            return s, t

        except socket.gaierror as e:
            _LOGGER.warning("Address-related error: %s", e)
            return None
        except ConnectionError as e:
            _LOGGER.warning("Connection error: %s", e)
            return None
        except OSError as e:
            _LOGGER.warning("Socket error binding %s: %s", receive_port, e)
            return None
           
    def send_command(self, port, command, commandType=None, data=None):
        """Send a command packet. In hub mode, use shared sockets; otherwise, legacy per-device socket.
        Returns True on successful send, False on failure.
        """
        # Build the exact same packet as before
        message = LibratoneMessage.LibratoneMessage(
            command=command, data=data, commandType=commandType
        ).get_packet()

        # --- Hub path: bypass per-device sockets entirely ---
        if 'USE_SOCKET_HUB' in globals() and USE_SOCKET_HUB:
            try:
                _get_hub().send_control(self.host, message)  # always goes to host:7777
                return True
            except Exception as e:
                try:
                    _LOGGER.error("Hub send_control failed: %s", e)
                except Exception:
                    pass
                return False

        # --- Legacy path: original per-device socket logic ---
        if self._listening_notification_socket is None:
            self._listening_notification_socket, _ = self._get_new_socket(receive_port=_UDP_NOTIFICATION_RECEIVE_PORT)
            if self._listening_notification_socket is None:
                try:
                    _LOGGER.warning("Failed to create notification socket")
                except Exception:
                    pass
                return False

        try:
            # Send and store the answer in resp
            resp = self._listening_notification_socket.sendto(message, (self.host, port))

            if resp == 0:
                try:
                    _LOGGER.warning("Send fail, disconnecting socket")
                except Exception:
                    pass
                try:
                    self._listening_notification_socket.close()
                except Exception:
                    pass
                self._listening_notification_socket = None
                return False
            return True

        except (BrokenPipeError, ConnectionError) as connect_error:
            try:
                _LOGGER.warning("Connection error, retrying. %s", connect_error)
            except Exception:
                pass
            self._listening_notification_socket = None
            self._listening_notification_socket = self._get_new_socket(self.host, port)
            if self._listening_notification_socket is not None:
                try:
                    # retrying after broken pipe error
                    self._listening_notification_socket.sendto(message, (self.host, port))
                    return True
                except Exception as e2:
                    try:
                        _LOGGER.error("Retry send failed: %s", e2)
                    except Exception:
                        pass
            return False

        # Send a control message to set something (port _UDP_CONTROL_PORT = 7777) - Use the send_command function
    def set_control_command(self, command, data = None):
        return self.send_command(port=_UDP_CONTROL_PORT, command=command, data=data)

    # Send a control message to get something - same than above
    def get_control_command(self, command, data = None):
        return self.send_command(port=_UDP_CONTROL_PORT, command=command, data=data, commandType=1)

    # Get functions to get status - assuming that the speaker will answer it
    def version_get(self): return self.get_control_command(command=_COMMAND_TABLE['Version']['_get'])
    def name_get(self): return self.get_control_command(command=_COMMAND_TABLE['Name']['_get'])
    def volume_get(self): return self.get_control_command(command=_COMMAND_TABLE['Volume']['_get'])
    def voicing_get(self): return self.get_control_command(command=_COMMAND_TABLE['Voicing']['_get'])
    def chargingstatus_get(self): return self.get_control_command(command=_COMMAND_TABLE['ChargingStatus']['_get'])
    def playstatus_get(self): return self.get_control_command(command=_COMMAND_TABLE['PlayStatus']['_get'])
    def room_getall(self): return self.get_control_command(command=_COMMAND_TABLE['Room']['_getAll'])
    def voicing_getall(self): return self.get_control_command(command=_COMMAND_TABLE['Voicing']['_getAll'])
    def room_get(self): return self.get_control_command(command=_COMMAND_TABLE['Room']['_get'])
    def player_get(self): return self.get_control_command(command=_COMMAND_TABLE['Player']['_get'])
    def signalstrenght_get(self): return self.get_control_command(command=_COMMAND_TABLE['SignalStrength']['_get'])
    def devicecolor_get(self): return self.get_control_command(command=_COMMAND_TABLE['DeviceColor']['_get'])
    def serialnumber_get(self): return self.get_control_command(command=_COMMAND_TABLE['SerialNumber']['_get'])
    def mutestatus_get(self): return self.get_control_command(command=_COMMAND_TABLE['MuteStatus']['_get'])
    def batterylevel_get(self): return self.get_control_command(command=_COMMAND_TABLE['BatteryLevel']['_get'])
    def channel_get(self): return self.get_control_command(command=_COMMAND_TABLE['Channel']['_get'])
    def timer_get(self): return self.get_control_command(command=_COMMAND_TABLE['Timer']['_get'])
    def currpowermode_get(self): return self.get_control_command(command=_COMMAND_TABLE['CurrPowerMode']['_get'])
    
    # Call all *get* functions above, except fixed values
    def get_all(self):
        """Ask for every value that changes at runtime.

        The speaker answers GETs one at a time and silently drops packets that arrive in a burst, so the
        requests are spaced out by _GET_SPACING seconds (a call takes about 5 seconds).
        """
        getters = (
            self.currpowermode_get,
            self.chargingstatus_get,
            self.volume_get,
            self.voicing_get,
            self.room_get,
            self.player_get,
            self.signalstrenght_get,
            self.mutestatus_get,
            self.batterylevel_get,
            self.timer_get,
            self.playstatus_get,
            self.maxvolume_get,
            self.ledlevel_get,
            self.voiceprompt_get,
            self.stereotype_get,
            self.firmwareupdate_get,
            self.channel_get,
            self.sourceinfo_get,
            self.playmode_get,
        )
        for getter in getters:
            getter()
            time.sleep(_GET_SPACING)

    # Call all *get* for values that are fixed for the lifecycle 
    def get_all_fixed_for_lifecycle(self):
        self.currpowermode_get()
        self.version_get()
        self.name_get()
        self.room_getall()
        self.voicing_getall()
        self.devicecolor_get()
        self.serialnumber_get()
        self.channel_get()

    # Calculate Zipp state based on _currpowermode and _playstatus
    def _state_calculate(self):
        # If the Zipp sleeps, set this status
        if self._currpowermode == POWERMODE_SLEEP:
            self.state = STATE_SLEEP
            return True
        elif self._currpowermode == POWERMODE_AWAKE:
            if self._playstatus == PLAYSTATUS_PLAY: self.state = STATE_PLAY
            elif self._playstatus == PLAYSTATUS_PAUSE: self.state = STATE_PAUSE
            elif self._playstatus == PLAYSTATUS_STOP: self.state = STATE_STOP
            else:
                self.state = STATE_ON
                return True
        else:
            self.state = STATE_UNKNOWN
            return False

    # Refresh the state of the Zipp
    def state_refresh(self):
        if host_up(self.host):
            # If the Zipp was not in a "controlled" state, refresh also lifecycle variables
            if self.state != STATE_PLAY and self.state != STATE_PAUSE and self.state != STATE_STOP:
                self.get_all_fixed_for_lifecycle()
                time.sleep(_GET_LIFECYCLE_VALUES)
            self.get_all()
        else:
            self._cleanup_variables()
            self.state = STATE_UNKNOWN

    # Send PlayControl commands
    def _playcontrol_set(self, action):
        # Possible actions are defined in _COMMAND_TABLE['PlayControl']
        try:
            self.set_control_command(_COMMAND_TABLE['PlayControl']['_set'], _COMMAND_TABLE['PlayControl'][action])
            return True
        except:
            _LOGGER.warning("Error: %s command not sent.", action)
            return False
    def play(self): return self._playcontrol_set('play')
    def pause(self): return self._playcontrol_set('pause')
    def stop(self): return self._playcontrol_set('stop')
    def next(self): return self._playcontrol_set('next')
    def prev(self): return self._playcontrol_set('prev')

    # Define a name
    def name_set(self, name:str): return self.set_control_command(command=_COMMAND_TABLE['Name']['_set'], data=str(name))


    # Send Player-Favorite command
    def favorite_play(self, favourite_id):
        if int(favourite_id) < 1 or int(favourite_id) > 5:
            _LOGGER.warning("Error: favorite command must be within 1 and 5.")
            return False
        try:
            if not isinstance(favourite_id, str): favourite_id = str(favourite_id)
            self.set_control_command(_COMMAND_TABLE['Player']['_set'], _COMMAND_TABLE['Player']['favorite'][favourite_id])
            return True
        except:
            _LOGGER.warning("Error: favorite command not sent.")
            return False

    # Send a voicingid, either for type="Voicing" or type="Room"
    def _voicingid_set(self, voicing_name, type):

        if type == "Voicing":
            json_list = self._voicing_list_json
        elif type == "Room":
            json_list = self._room_list_json
        else:
            _LOGGER.warning("voicingid_set: type must be either 'Voicing' or 'Room'")
            return False
        
        try:
            for item in json_list:
                if voicing_name == item['name']:
                    self.set_control_command(command=_COMMAND_TABLE[type]['_set'], data=item['voicingId'])
                    break
            return True
        except:
            _LOGGER.warning("Error: voicing command not sent.")
            return False

    # Send Voicing command
    def voicing_set(self, voicing_name:str): return self._voicingid_set(voicing_name=voicing_name, type="Voicing")
    def room_set(self, room_name:str): return self._voicingid_set(voicing_name=room_name, type="Room")


    # Transform raw all room/voicing list (JSON) into a list with only room names
    def _name_list_from_json(self, json_list):
        name_list = []
        for item in json_list:
            name_list.append(item['name'])
        return name_list

    # Parse raw voicing list, update the name list
    def _voicing_list_update_from_raw(self, raw_list):
        try:
            self._voicing_list_json = json.loads(raw_list)
            self.voicing_list = self._name_list_from_json(self._voicing_list_json)
        except:
            self._voicing_list_json = None
            self.voicing_list = None

    # Parse raw room list, update the name list
    def _room_list_update_from_raw(self, raw_list):
        try:
            self._room_list_json = json.loads(raw_list)
            self.room_list = self._name_list_from_json(self._room_list_json)
        except:
            self._room_list_json = None
            self.room_list = None

    # Transform a raw voicingId (used by both Voicing and Room) into Name
    def _voicingid_to_name(self, voicingid, json_list):
        if json_list == None:
            _LOGGER.error("Cannot parse " + voicingid + " as JSON list is empty.")
            return None
        try:
            for item in json_list:
                if voicingid == item['voicingId']:
                    return item['name']
        except:
            return None

    # Send Volume command
    def volume_set(self, volume):
        if int(volume) < 0 or int(volume) > 100:
            _LOGGER.warning("Error: volume command must be within 0 and 100.")
            return False
        try:
            # if volume is a string
            if isinstance(volume, str): self.set_control_command(_COMMAND_TABLE['Volume']['_set'], volume)
            else: self.set_control_command(_COMMAND_TABLE['Volume']['_set'], str(volume))
            return True
        except:
            _LOGGER.warning("Error: volume command not sent.")
            return False

    # Parse Player data: populate all play_* variables
    def _player_parse(self, player_data):

        # Initialize to none
        self._player_json = None
        self.isFromChannel = None
        self.play_identity = None
        self.play_preset_available = None
        self.play_subtitle = None
        self.play_title = None
        self.play_token = None
        self.play_type = None

        try:
            self._player_json = json.loads(player_data)
        except Exception:
            pass

        # An empty or invalid reply leaves everything at None
        if not isinstance(self._player_json, dict):
            self._player_json = None
            return

        self.isFromChannel = self._player_json.get('isFromChannel', '')
        self.play_identity = self._player_json.get('play_identity', '')
        self.play_preset_available = self._player_json.get('play_preset_available', '')
        self.play_subtitle = self._player_json.get('play_subtitle', '')
        self.play_title = self._player_json.get('play_title', '')
        self.play_token = self._player_json.get('play_token', '')
        self.play_type = self._player_json.get('play_type', '')

    # Parse Timer, return *DEFINED* timer in second, not the actual one which is running!
    def _timer_parse(self, timer_data):
        if timer_data == b'': return None
        elif timer_data[0] == 255: return None  # Always the case when no timer is defined
        elif timer_data[0] == 50:   # Always when there's an active timer
            return timer_data[1] + timer_data[2]*256
        else:
            return None

    # Send timer commands - timer is in seconds
    def timer_set(self, timer): return self.set_control_command(command=_COMMAND_TABLE['Timer']['_set'], data="2"+str(timer))
    def timer_cancel(self): return self.set_control_command(command=_COMMAND_TABLE['Timer']['_set'], data="F0")
    def sleep(self): return self.timer_set(0)
    def wakeup(self): return self.set_control_command(command=_COMMAND_TABLE['Timer']['_set'], data="00")

    def group_join(self, link_id: str) -> bool:
        # 0x01F6 / 502 with payload "LINK <link_id>"
        if not link_id:
            return False
        return self.set_control_command(_COMMAND_TABLE['Group']['_join'], f"LINK {link_id}")

    def group_leave(self, link_id: str = None) -> bool:
        # 0x01F7 / 503 also carried "LINK <link_id>" in your capture
        lid = link_id or self.group_link_id
        if not lid:
            return False
        return self.set_control_command(_COMMAND_TABLE['Group']['_leave'], f"LINK {lid}")



    # ------------------------------------------------------------------------------------------------------
    # Additional values and commands, found by decompiling the official Android app
    # (com.libratone.v3.model.LSSDPNode, com.libratone.v3.luci.MIDCONST) and verified on a Zipp 2.
    # ------------------------------------------------------------------------------------------------------

    @staticmethod
    def _text(data):
        """Reply payload as text, tolerating binary bytes."""
        return bytes(data).decode(errors="ignore").strip()

    def _get_later(self, getter):
        """Read a value back shortly after a SET (the speaker applies it a moment later) without blocking the caller."""
        timer = threading.Timer(_CONFIRM_DELAY, getter)
        timer.daemon = True
        timer.start()

    def maxvolume_get(self): return self.get_control_command(command=_COMMAND_TABLE['MaxVolume']['_get'])
    def ledlevel_get(self): return self.get_control_command(command=_COMMAND_TABLE['LedLevel']['_get'])
    def voiceprompt_get(self): return self.get_control_command(command=_COMMAND_TABLE['VoicePrompt']['_get'])
    def stereotype_get(self): return self.get_control_command(command=_COMMAND_TABLE['StereoType']['_get'])
    def firmwareupdate_get(self): return self.get_control_command(command=_COMMAND_TABLE['FirmwareUpdate']['_get'], data="0")
    def sourceinfo_get(self): return self.get_control_command(command=_COMMAND_TABLE['SourceInfo']['_get'])
    def playmode_get(self): return self.get_control_command(command=_COMMAND_TABLE['PlayMode']['_get'])

    # Mute: part of the play control commands. mutestatus is "UNMUTE" or "MUTE,<volume before muting>"
    def mute(self):
        self.mutestatus = "MUTE"
        ok = self._playcontrol_set('mute')
        self._get_later(self.mutestatus_get)
        return ok

    def unmute(self):
        self.mutestatus = "UNMUTE"
        ok = self._playcontrol_set('unmute')
        self._get_later(self.mutestatus_get)
        return ok

    @property
    def is_muted(self):
        if not self.mutestatus:
            return None
        return self.mutestatus.upper().startswith("MUTE")

    # Settings
    def max_volume_set(self, value):
        """Volume cap enforced by the speaker itself, 0-100."""
        value = max(0, min(int(value), 100))
        self.max_volume = str(value)
        ok = self.set_control_command(_COMMAND_TABLE['MaxVolume']['_set'], str(value))
        self._get_later(self.maxvolume_get)
        return ok

    def led_level_set(self, value):
        """LED brightness level, 0-2."""
        value = max(0, min(int(value), 2))
        self.led_level = str(value)
        ok = self.set_control_command(_COMMAND_TABLE['LedLevel']['_set'], str(value))
        self._get_later(self.ledlevel_get)
        return ok

    def voice_prompt_set(self, enabled):
        """Spoken status messages on or off."""
        self.voice_prompt = "1" if enabled else "0"
        ok = self.set_control_command(_COMMAND_TABLE['VoicePrompt']['_set'], self.voice_prompt)
        self._get_later(self.voiceprompt_get)
        return ok

    def stereo_type_set(self, name):
        """Which channel this speaker plays when two are paired: 'stereo', 'left' or 'right'."""
        type_id = STEREO_TYPE_IDS[name]
        self.stereo_type = type_id
        ok = self.set_control_command(_COMMAND_TABLE['StereoType']['_set'], type_id)
        self._get_later(self.stereotype_get)
        return ok

    # Values derived from the raw replies
    @property
    def battery_percent(self):
        try:
            return int(str(self.batterylevel).strip())
        except (TypeError, ValueError):
            return None

    @property
    def is_charging(self):
        """The Android app treats charging status 1 as charging (2 was seen at 100 % battery)."""
        status = self.chargingstatus
        if status is None or str(status).strip() == "":
            return None
        return str(status).strip() == "1"

    @property
    def wifi_rssi(self):
        """signalstrenght looks like ' ,-45,65/70' (ssid, rssi in dBm, quality/max)."""
        parts = str(self.signalstrenght or "").split(",")
        if len(parts) < 2:
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

    @property
    def wifi_quality_percent(self):
        match = re.search(r"(\d+)\s*/\s*(\d+)", str(self.signalstrenght or ""))
        if not match or int(match.group(2)) == 0:
            return None
        return round(100 * int(match.group(1)) / int(match.group(2)))

    # Favorites (the five preset stations)
    @property
    def favorites(self):
        """List of dicts with channel_id, channel_name, channel_identity and channel_type."""
        if not isinstance(self._channel_json, list):
            return []
        return [c for c in self._channel_json if isinstance(c, dict) and c.get("channel_id") is not None]

    def favorite_name(self, slot):
        for channel in self.favorites:
            if str(channel.get("channel_id")) == str(slot):
                return channel.get("channel_name")
        return None

    def favorite_slot_by_name(self, name):
        for channel in self.favorites:
            if channel.get("channel_name") == name:
                return int(channel["channel_id"])
        return None

    def favorite_set(self, slot, station_id, name, channel_type="vtuner"):
        """Store a station in preset `slot` (1-5). station_id is the vTuner id for channel_type 'vtuner'."""
        entry = {
            "channel_id": int(slot),
            "channel_identity": str(station_id),
            "channel_name": name,
            "channel_type": channel_type,
        }
        ok = self.set_control_command(_COMMAND_TABLE['FavoriteSet']['_set'], json.dumps(entry, ensure_ascii=False))
        self._get_later(self.channel_get)
        return ok

    # Firmware: the speaker checks for updates on its own; this is its report
    @property
    def firmware_update(self):
        """(state name, error code) e.g. ('none', 0); None until the speaker answered. See FW_UPDATE_STATES."""
        if not self.firmware_update_raw:
            return None
        try:
            data = json.loads(self.firmware_update_raw)
            return FW_UPDATE_STATES.get(int(data["state"]), "unknown"), data.get("err")
        except (ValueError, KeyError, TypeError):
            return None

    # Active source (command 10): byte 0 = source code, bytes 3-6 = ability flags (little endian)
    @property
    def source_code(self):
        return self.source_info[0] if self.source_info else None

    @property
    def source_type(self):
        """Name of the active source, see SOURCE_TYPES; None until the speaker answered."""
        code = self.source_code
        return None if code is None else SOURCE_TYPES.get(code, "other")

    @property
    def supports_play_mode(self):
        """True while the active source accepts shuffle / repeat (ability bit 18)."""
        if not self.source_info or len(self.source_info) < 7:
            return False
        return bool(int.from_bytes(self.source_info[3:7], "little") & _ABILITY_SET_PLAY_MODE)

    # Shuffle / repeat (command 1541)
    @property
    def shuffle(self):
        mode = PLAY_MODES.get(self.play_mode or "")
        return None if mode is None else mode[0]

    @property
    def repeat(self):
        """'off', 'one' or 'all'."""
        mode = PLAY_MODES.get(self.play_mode or "")
        return None if mode is None else mode[1]

    def play_mode_set(self, shuffle, repeat):
        mode_id = PLAY_MODE_IDS[(bool(shuffle), repeat)]
        self.play_mode = mode_id
        ok = self.set_control_command(_COMMAND_TABLE['PlayMode']['_set'], mode_id)
        self._get_later(self.playmode_get)
        return ok
