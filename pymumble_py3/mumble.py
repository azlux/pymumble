# -*- coding: utf-8 -*-

import threading
import logging
import time
import select
import socket
import ssl
import struct

from .crypto import CryptStateOCB2
from .errors import *
from .constants import *
from . import users
from . import channels
from . import blobs
from . import commands
from . import callbacks
from . import tools
from . import soundoutput

from . import mumble_pb2


class Mumble(threading.Thread):
    """
    Mumble client library main object.
    basically a thread
    """

    def __init__(self, host, user, port=64738, password='', certfile=None, keyfile=None, reconnect=False, tokens=None, stereo=False, debug=False):
        """
        host=mumble server hostname or address
        port=mumble server port
        user=user to use for the connection
        password=password for the connection
        certfile=client certificate to authenticate the connection
        keyfile=private key associated with the client certificate
        reconnect=if True, try to reconnect if disconnected
        tokens=channel access tokens as a list of strings
        stereo=enable stereo transmission
        debug=if True, send debugging messages (lot of...) to the stdout
        """
        threading.Thread.__init__(self)

        if tokens is None:
            tokens = []
        self.Log = logging.getLogger("PyMumble")  # logging object for errors and debugging
        if debug:
            self.Log.setLevel(logging.DEBUG)
        else:
            self.Log.setLevel(logging.ERROR)

        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s-%(name)s-%(levelname)s-%(message)s')
        ch.setFormatter(formatter)
        self.Log.addHandler(ch)

        self.parent_thread = threading.current_thread()  # main thread of the calling application
        self.mumble_thread = None  # thread of the mumble client library

        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.certfile = certfile
        self.keyfile = keyfile
        self.reconnect = reconnect
        self.tokens = tokens
        self.__opus_profile = PYMUMBLE_AUDIO_TYPE_OPUS_PROFILE
        self.stereo = stereo

        if stereo:
            self.Log.debug("Working in STEREO mode.")
        else:
            self.Log.debug("Working in MONO mode.")

        self.receive_sound = False  # set to True to treat incoming audio, otherwise it is simply ignored

        self.loop_rate = PYMUMBLE_LOOP_RATE

        self.application = PYMUMBLE_VERSION_STRING

        self.callbacks = callbacks.CallBacks()  # callbacks management

        self.ready_lock = threading.Lock()  # released when the connection is fully established with the server
        self.ready_lock.acquire()

        self.positional = None

        # Init all parameters for init_connection()
        self.connected = None
        self.control_socket = None
        self.media_socket = None
        self.ocb = None
        self.bandwidth = None
        self.server_max_bandwidth = None
        self.udp_active = None
        self.server_allow_html = None
        self.server_max_message_length = None
        self.server_max_image_message_length = None
        self.users = None
        self.channels = None
        self.blobs = None
        self.sound_output = None
        self.commands = None
        self.receive_buffer = None
        self.ping_stats = None
        self.exit = None

    def init_connection(self):
        """Initialize variables that are local to a connection, (needed if the client automatically reconnect)"""
        self.ready_lock.acquire(False)  # reacquire the ready-lock in case of reconnection

        self.connected = PYMUMBLE_CONN_STATE_NOT_CONNECTED
        self.control_socket = None
        self.media_socket = None  # Not implemented - for UDP media
        self.ocb = CryptStateOCB2()

        self.bandwidth = PYMUMBLE_BANDWIDTH  # reset the outgoing bandwidth to it's default before connecting
        self.server_max_bandwidth = None
        self.udp_active = False

        # defaults according to https://wiki.mumble.info/wiki/Murmur.ini
        self.server_allow_html = True
        self.server_max_message_length = 5000
        self.server_max_image_message_length = 131072

        self.users = users.Users(self, self.callbacks)  # contains the server's connected users information
        self.channels = channels.Channels(self, self.callbacks)  # contains the server's channels information
        self.blobs = blobs.Blobs(self)  # manage the blob objects
        self.sound_output = soundoutput.SoundOutput(self, PYMUMBLE_AUDIO_PER_PACKET, self.bandwidth, stereo=self.stereo, opus_profile=self.__opus_profile)  # manage the outgoing sounds
        self.commands = commands.Commands()  # manage commands sent between the main and the mumble threads

        self.receive_buffer = bytes()  # initialize the control connection input buffer
        self.ping_stats = {"last_rcv": 0, "time_send": 0, "nb": 0, "avg": 40.0, "var": 0.0}  # Set / reset ping stats
        self.exit = False

    def run(self):
        """Connect to the server and start the loop in its thread.  Retry if requested"""
        self.mumble_thread = threading.current_thread()

        # loop if auto-reconnect is requested
        while True:
            self.init_connection()  # reset the connection-specific object members

            if self.connect() >= PYMUMBLE_CONN_STATE_FAILED:  # some error occurred, exit here
                self.ready_lock.release()
                if not self.reconnect or not self.parent_thread.is_alive():
                    raise ConnectionRejectedError("Connection error with the Mumble (murmur) Server")
                else:
                    time.sleep(PYMUMBLE_CONNECTION_RETRY_INTERVAL)
                    continue

            try:
                self.loop()
            except socket.error:
                self.connected = PYMUMBLE_CONN_STATE_NOT_CONNECTED

            if not self.reconnect or not self.parent_thread.is_alive():
                self.callbacks(PYMUMBLE_CLBK_DISCONNECTED)
                break

            self.callbacks(PYMUMBLE_CLBK_DISCONNECTED)
            time.sleep(PYMUMBLE_CONNECTION_RETRY_INTERVAL)

    def connect(self):
        """Connect to the server"""
        # Get IPv4/IPv6 server address
        server_info = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)

        # Connect the SSL tunnel
        self.Log.debug("connecting to %s (%s) on port %i.", self.host, server_info[0][1], self.port)
        std_sock = socket.socket(server_info[0][0], socket.SOCK_STREAM)
        std_sock.settimeout(10)

        try:
            self.control_socket = ssl.wrap_socket(std_sock, certfile=self.certfile, keyfile=self.keyfile, ssl_version=ssl.PROTOCOL_TLS)
        except AttributeError:
            self.control_socket = ssl.wrap_socket(std_sock, certfile=self.certfile, keyfile=self.keyfile, ssl_version=ssl.PROTOCOL_TLSv1)
        try:
            self.control_socket.connect((self.host, self.port))
            self.control_socket.setblocking(False)

            # Perform the Mumble authentication
            version = mumble_pb2.Version()
            version.version = (PYMUMBLE_PROTOCOL_VERSION[0] << 16) + (PYMUMBLE_PROTOCOL_VERSION[1] << 8) + PYMUMBLE_PROTOCOL_VERSION[2]
            version.release = self.application
            version.os = PYMUMBLE_OS_STRING
            version.os_version = PYMUMBLE_OS_VERSION_STRING
            self.Log.debug("sending: version: %s", version)
            self.send_message(PYMUMBLE_MSG_TYPES_VERSION, version)

            authenticate = mumble_pb2.Authenticate()
            authenticate.username = self.user
            authenticate.password = self.password
            authenticate.tokens.extend(self.tokens)
            authenticate.opus = True
            self.Log.debug("sending: authenticate: %s", authenticate)
            self.send_message(PYMUMBLE_MSG_TYPES_AUTHENTICATE, authenticate)
        except socket.error:
            self.connected = PYMUMBLE_CONN_STATE_FAILED
            return self.connected

        self.connected = PYMUMBLE_CONN_STATE_AUTHENTICATING
        self.media_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # Perpare UDP socket
        return self.connected

    def crypt_setup(self, mess):
        if mess.key and mess.client_nonce and mess.server_nonce:
            self.media_socket.settimeout(6)
            self.ocb.set_key(bytes(mess.key), encrypt_iv=bytearray(mess.client_nonce), decrypt_iv=bytearray(mess.server_nonce))
        else:
            raise ConnectionError

        self.ping(udp=True)

        try:
            response, sender = self.media_socket.recvfrom(2048)
        except socket.timeout:
            self.media_socket.close()
            self.Log.warning("Timed out waiting for UDP ping response from server. Using TCP for audio traffic.")
            self.udp_active = False
            return False
        self.ocb.decrypt(response)

        self.media_socket.settimeout(None)
        self.udp_active = True  # UDP is active only if I receive an answer

    def send_packet_udp(self, msg):
        pk_encrypt = self.ocb.encrypt(msg)
        try:
            self.media_socket.sendto(pk_encrypt, (self.host, self.port))
            self.Log.debug("Sending UDP PING")
        except (socket.gaierror, socket.timeout) as e:
            self.Log.error(e)

    def loop(self):
        """
        Main loop
        waiting for a message from the server for maximum self.loop_rate time
        take care of sending the ping
        take care of sending the queued commands to the server
        check on every iteration for outgoing sound
        check for disconnection
        """
        self.Log.debug("entering loop")

        last_ping = time.time()  # keep track of the last ping time

        # loop as long as the connection and the parent thread are alive
        while self.connected not in (PYMUMBLE_CONN_STATE_NOT_CONNECTED, PYMUMBLE_CONN_STATE_FAILED) and self.parent_thread.is_alive() and not self.exit:
            if last_ping + PYMUMBLE_PING_DELAY <= time.time():  # when it is time, send the ping
                self.ping()
                last_ping = time.time()

            if self.connected == PYMUMBLE_CONN_STATE_CONNECTED:
                while self.commands.is_cmd():
                    self.treat_command(self.commands.pop_cmd())  # send the commands coming from the application to the server

                self.sound_output.send_audio()  # send outgoing audio if available

            if self.udp_active:
                (rlist, wlist, xlist) = select.select([self.control_socket, self.media_socket], [], [self.control_socket, self.media_socket], self.loop_rate)  # wait for a socket activity
            else:
                (rlist, wlist, xlist) = select.select([self.control_socket], [], [self.control_socket], self.loop_rate)  # wait for a socket activity

            if self.control_socket in rlist:  # something to be read on the control socket
                self.read_control_messages()
            elif self.control_socket in xlist:  # socket was closed
                self.control_socket.close()
                self.connected = PYMUMBLE_CONN_STATE_NOT_CONNECTED

            if self.media_socket in rlist:
                self.media_socket.recvfrom(2048)
                self.Log.debug("received UDP message")
                self.read_udp_packet()
            elif self.media_socket in xlist:  # socket was closed
                self.media_socket.close()
                self.udp_active = False

    def ping(self, udp=False):
        """Send the keepalive through available channels"""
        if udp:
            udp_ping_packet = b'\x20' + tools.VarInt(int(time.time())).encode()
            self.send_packet_udp(udp_ping_packet)
        else:
            ping = mumble_pb2.Ping()
            ping.timestamp = int(time.time())
            ping.tcp_ping_avg = self.ping_stats['avg']
            ping.tcp_ping_var = self.ping_stats['var']
            ping.tcp_packets = self.ping_stats['nb']

            self.Log.debug("sending: ping: %s", ping)
            self.send_message(PYMUMBLE_MSG_TYPES_PING, ping)
            self.ping_stats['time_send'] = int(time.time() * 1000)
            self.Log.debug(self.ping_stats['last_rcv'])
            if self.ping_stats['last_rcv'] != 0 and int(time.time() * 1000) > self.ping_stats['last_rcv'] + (60 * 1000):
                self.Log.debug("Ping too long ! Disconnected ?")
                self.connected = PYMUMBLE_CONN_STATE_NOT_CONNECTED

    def ping_response(self, mess):
        self.ping_stats['last_rcv'] = int(time.time() * 1000)
        ping = int(time.time() * 1000) - self.ping_stats['time_send']
        old_avg = self.ping_stats['avg']
        nb = self.ping_stats['nb']
        new_avg = ((self.ping_stats['avg'] * nb) + ping) / (nb + 1)

        try:
            self.ping_stats['var'] = self.ping_stats['var'] + pow(old_avg - new_avg, 2) + (1 / nb) * pow(ping - new_avg, 2)
        except ZeroDivisionError:
            pass

        self.ping_stats['avg'] = new_avg
        self.ping_stats['nb'] += 1

    def send_message(self, msg_type, message):
        """Send a control message to the server"""
        packet = struct.pack("!HL", msg_type, message.ByteSize()) + message.SerializeToString()

        while len(packet) > 0:
            self.Log.debug("sending message")
            sent = self.control_socket.send(packet)
            if sent < 0:
                raise socket.error("Server socket error")
            packet = packet[sent:]

    def read_udp_packet(self):
        encrypted_buffer = None
        try:
            encrypted_buffer = self.media_socket.recv(PYMUMBLE_READ_BUFFER_SIZE)
        except socket.error:
            pass

        receive_buffer = self.ocb.decrypt(encrypted_buffer)

        while len(receive_buffer) >= 6:  # header is present (type + length)
            self.Log.debug("read control connection")
            header = receive_buffer[0:6]

            if len(header) < 6:
                break

            (msg_type, size) = struct.unpack("!HL", header)  # decode header

            if len(receive_buffer) < size + 6:  # if not length data, read further
                break

            # self.Log.debug("message received : " + tohex(self.receive_buffer[0:size+6]))  # for debugging

            message = receive_buffer[6:size + 6]  # get the control message
            receive_buffer = receive_buffer[size + 6:]  # remove from the buffer the read part

            if msg_type == PYMUMBLE_MSG_TYPES_UDPTUNNEL:  # audio encapsulated in control message
                self.sound_received(message)

    def read_control_messages(self):
        """Read control messages coming from the server"""
        # from tools import tohex  # for debugging

        try:
            buffer = self.control_socket.recv(PYMUMBLE_READ_BUFFER_SIZE)
            self.receive_buffer += buffer
        except socket.error:
            pass

        while len(self.receive_buffer) >= 6:  # header is present (type + length)
            self.Log.debug("read control connection")
            header = self.receive_buffer[0:6]

            if len(header) < 6:
                break

            (msg_type, size) = struct.unpack("!HL", header)  # decode header

            if len(self.receive_buffer) < size + 6:  # if not length data, read further
                break

            # self.Log.debug("message received : " + tohex(self.receive_buffer[0:size+6]))  # for debugging

            message = self.receive_buffer[6:size + 6]  # get the control message
            self.receive_buffer = self.receive_buffer[size + 6:]  # remove from the buffer the read part

            self.dispatch_control_message(msg_type, message)

    def dispatch_control_message(self, msg_type, message):
        """Dispatch control messages based on their type"""
        self.Log.debug("dispatch control message")
        if msg_type == PYMUMBLE_MSG_TYPES_UDPTUNNEL:  # audio encapsulated in control message
            self.sound_received(message)

        elif msg_type == PYMUMBLE_MSG_TYPES_VERSION:
            mess = mumble_pb2.Version()
            mess.ParseFromString(message)
            self.Log.debug("message: Version : %s", mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_AUTHENTICATE:
            mess = mumble_pb2.Authenticate()
            mess.ParseFromString(message)
            self.Log.debug("message: Authenticate : %s", mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_PING:
            mess = mumble_pb2.Ping()
            mess.ParseFromString(message)
            self.Log.debug("message: Ping : %s", mess)
            self.ping_response(mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_REJECT:
            mess = mumble_pb2.Reject()
            mess.ParseFromString(message)
            self.Log.debug("message: reject : %s", mess)
            self.connected = PYMUMBLE_CONN_STATE_FAILED
            self.ready_lock.release()
            raise ConnectionRejectedError(mess.reason)

        elif msg_type == PYMUMBLE_MSG_TYPES_SERVERSYNC:  # this message finish the connection process
            mess = mumble_pb2.ServerSync()
            mess.ParseFromString(message)
            self.Log.debug("message: serversync : %s", mess)
            self.users.set_myself(mess.session)
            self.server_max_bandwidth = mess.max_bandwidth
            self.set_bandwidth(mess.max_bandwidth)

            if self.connected == PYMUMBLE_CONN_STATE_AUTHENTICATING:
                self.connected = PYMUMBLE_CONN_STATE_CONNECTED
                self.ready_lock.release()  # release the ready-lock
                self.callbacks(PYMUMBLE_CLBK_CONNECTED)

        elif msg_type == PYMUMBLE_MSG_TYPES_CHANNELREMOVE:
            mess = mumble_pb2.ChannelRemove()
            mess.ParseFromString(message)
            self.Log.debug("message: ChannelRemove : %s", mess)

            self.channels.remove(mess.channel_id)

        elif msg_type == PYMUMBLE_MSG_TYPES_CHANNELSTATE:
            mess = mumble_pb2.ChannelState()
            mess.ParseFromString(message)
            self.Log.debug("message: channelstate : %s", mess)

            self.channels.update(mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_USERREMOVE:
            mess = mumble_pb2.UserRemove()
            mess.ParseFromString(message)
            self.Log.debug("message: UserRemove : %s", mess)

            self.users.remove(mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_USERSTATE:
            mess = mumble_pb2.UserState()
            mess.ParseFromString(message)
            self.Log.debug("message: userstate : %s", mess)

            self.users.update(mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_BANLIST:
            mess = mumble_pb2.BanList()
            mess.ParseFromString(message)
            self.Log.debug("message: BanList : %s", mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_TEXTMESSAGE:
            mess = mumble_pb2.TextMessage()
            mess.ParseFromString(message)
            self.Log.debug("message: TextMessage : %s", mess)

            self.callbacks(PYMUMBLE_CLBK_TEXTMESSAGERECEIVED, mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_PERMISSIONDENIED:
            mess = mumble_pb2.PermissionDenied()
            mess.ParseFromString(message)
            self.Log.debug("message: PermissionDenied : %s", mess)

            self.callbacks(PYMUMBLE_CLBK_PERMISSIONDENIED, mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_ACL:
            mess = mumble_pb2.ACL()
            mess.ParseFromString(message)
            self.Log.debug("message: ACL : %s", mess)
            self.channels[mess.channel_id].update_acl(mess)
            self.callbacks(PYMUMBLE_CLBK_ACLRECEIVED, mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_QUERYUSERS:
            mess = mumble_pb2.QueryUsers()
            mess.ParseFromString(message)
            self.Log.debug("message: QueryUsers : %s", mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_CRYPTSETUP:
            mess = mumble_pb2.CryptSetup()
            mess.ParseFromString(message)
            self.Log.debug("message: CryptSetup : %s", mess)
            self.crypt_setup(mess)
            self.ping()

        elif msg_type == PYMUMBLE_MSG_TYPES_CONTEXTACTIONMODIFY:
            mess = mumble_pb2.ContextActionModify()
            mess.ParseFromString(message)
            self.Log.debug("message: ContextActionModify : %s", mess)

            self.callbacks(PYMUMBLE_CLBK_CONTEXTACTIONRECEIVED, mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_CONTEXTACTION:
            mess = mumble_pb2.ContextAction()
            mess.ParseFromString(message)
            self.Log.debug("message: ContextAction : %s", mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_USERLIST:
            mess = mumble_pb2.UserList()
            mess.ParseFromString(message)
            self.Log.debug("message: UserList : %s", mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_VOICETARGET:
            mess = mumble_pb2.VoiceTarget()
            mess.ParseFromString(message)
            self.Log.debug("message: VoiceTarget : %s", mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_PERMISSIONQUERY:
            mess = mumble_pb2.PermissionQuery()
            mess.ParseFromString(message)
            self.Log.debug("message: PermissionQuery : %s", mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_CODECVERSION:
            mess = mumble_pb2.CodecVersion()
            mess.ParseFromString(message)
            self.Log.debug("message: CodecVersion : %s", mess)

            self.sound_output.set_default_codec(mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_USERSTATS:
            mess = mumble_pb2.UserStats()
            mess.ParseFromString(message)
            self.Log.debug("message: UserStats : %s", mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_REQUESTBLOB:
            mess = mumble_pb2.RequestBlob()
            mess.ParseFromString(message)
            self.Log.debug("message: RequestBlob : %s", mess)

        elif msg_type == PYMUMBLE_MSG_TYPES_SERVERCONFIG:
            mess = mumble_pb2.ServerConfig()
            mess.ParseFromString(message)
            self.Log.debug("message: ServerConfig : %s", mess)
            for line in str(mess).split('\n'):
                items = line.split(':')
                if len(items) != 2:
                    continue
                if items[0] == 'allow_html':
                    self.server_allow_html = items[1].strip() == 'true'
                elif items[0] == 'message_length':
                    self.server_max_message_length = int(items[1].strip())
                elif items[0] == 'image_message_length':
                    self.server_max_image_message_length = int(items[1].strip())

    def set_bandwidth(self, bandwidth):
        """Set the total allowed outgoing bandwidth"""
        if self.server_max_bandwidth is not None and bandwidth > self.server_max_bandwidth:
            self.bandwidth = self.server_max_bandwidth
        else:
            self.bandwidth = bandwidth

        self.sound_output.set_bandwidth(self.bandwidth)  # communicate the update to the outgoing audio manager

    def sound_received(self, message):
        """Manage a received sound message"""
        # from tools import tohex  # for debugging

        pos = 0

        # self.Log.debug("sound packet : " + tohex(message))  # for debugging
        (header,) = struct.unpack("!B", bytes([message[pos]]))  # extract the header
        audio_type = (header & 0b11100000) >> 5
        target = header & 0b00011111
        pos += 1

        if audio_type == PYMUMBLE_AUDIO_TYPE_PING:
            self.Log.debug("UDP PING RECEIVED")
            return

        session = tools.VarInt()  # decode session id
        pos += session.decode(message[pos:pos + 10])

        sequence = tools.VarInt()  # decode sequence number
        pos += sequence.decode(message[pos:pos + 10])

        self.Log.debug("audio packet received from %i, sequence %i, type:%i, target:%i, length:%i", session.value, sequence.value, audio_type, target, len(message))

        terminator = False  # set to true if it's the last 10 ms audio frame for the packet (used with CELT codec)
        while (pos < len(message)) and not terminator:  # get the audio frames one by one
            if audio_type == PYMUMBLE_AUDIO_TYPE_OPUS:
                size = tools.VarInt()  # OPUS use varint for the frame length

                pos += size.decode(message[pos:pos + 10])
                size = size.value

                if not (size & 0x2000):  # terminator is 0x2000 in the resulting int.
                    terminator = True  # should actually always be 0 as OPUS can use variable length audio frames

                size &= 0x1fff  # isolate the size from the terminator
            else:
                (header,) = struct.unpack("!B", message[pos:pos + 1])  # CELT length and terminator is encoded in a 1 byte int
                if not (header & 0b10000000):
                    terminator = True
                size = header & 0b01111111
                pos += 1

            self.Log.debug("Audio frame : time:%f, last:%s, size:%i, type:%i, target:%i, pos:%i", time.time(), str(terminator), size, audio_type, target, pos - 1)

            if size > 0 and self.receive_sound:  # if audio must be treated
                try:
                    newsound = self.users[session.value].sound.add(message[pos:pos + size],
                                                                   sequence.value,
                                                                   audio_type,
                                                                   target)  # add the sound to the user's sound queue

                    if newsound is None:  # In case audio have been disable for specific users
                        return

                    self.callbacks(PYMUMBLE_CLBK_SOUNDRECEIVED, self.users[session.value], newsound)

                    sequence.value += int(round(newsound.duration / 1000 * 10))  # add 1 sequence per 10ms of audio

                    self.Log.debug("Audio frame : time:%f last:%s, size:%i, uncompressed:%i, type:%i, target:%i", time.time(), str(terminator), size, newsound.size, audio_type, target)
                except CodecNotSupportedError as msg:
                    print(msg)
                except KeyError:  # sound received after user removed
                    pass

                #            if len(message) - pos < size:
                #                raise InvalidFormatError("Invalid audio frame size")

            pos += size  # go further in the packet, after the audio frame
        # TODO: get position info

    def set_application_string(self, string):
        """Set the application name, that can be viewed by other clients on the server"""
        self.application = string

    def set_loop_rate(self, rate):
        """Set the current main loop rate (pause per iteration)"""
        self.loop_rate = rate

    def get_loop_rate(self):
        """Get the current main loop rate (pause per iteration)"""
        return self.loop_rate

    def set_codec_profile(self, profile):
        """set the audio profile"""
        if profile in ["audio", "voip", "restricted_lowdelay"]:
            self.__opus_profile = profile
        else:
            raise ValueError("Unknown profile: " + str(profile))

    def get_codec_profile(self):
        """return the audio profile string"""
        return self.__opus_profile

    def set_receive_sound(self, value):
        """Enable or disable the management of incoming sounds"""
        if value:
            self.receive_sound = True
        else:
            self.receive_sound = False

    def is_ready(self):
        """Wait for the connection to be fully completed.  To be used in the main thread"""
        self.ready_lock.acquire()
        self.ready_lock.release()

    def execute_command(self, cmd, blocking=True):
        """Create a command to be sent to the server.  To be used in the main thread"""
        self.is_ready()

        lock = self.commands.new_cmd(cmd)
        if blocking and self.mumble_thread is not threading.current_thread():
            lock.acquire()
            lock.release()

        return lock

    # TODO: manage a timeout for blocking commands.  Currently, no command actually waits for the server to execute
    # The result of these commands should actually be checked against incoming server updates

    def treat_command(self, cmd):
        """Send the awaiting commands to the server.  Used in the pymumble thread."""
        if cmd.cmd == PYMUMBLE_CMD_MOVE:
            userstate = mumble_pb2.UserState()
            userstate.session = cmd.parameters["session"]
            userstate.channel_id = cmd.parameters["channel_id"]
            self.Log.debug("Moving to channel")
            self.send_message(PYMUMBLE_MSG_TYPES_USERSTATE, userstate)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_CMD_TEXTMESSAGE:
            textmessage = mumble_pb2.TextMessage()
            textmessage.session.append(cmd.parameters["session"])
            textmessage.channel_id.append(cmd.parameters["channel_id"])
            textmessage.message = cmd.parameters["message"]
            self.send_message(PYMUMBLE_MSG_TYPES_TEXTMESSAGE, textmessage)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_CMD_TEXTPRIVATEMESSAGE:
            textprivatemessage = mumble_pb2.TextMessage()
            textprivatemessage.session.append(cmd.parameters["session"])
            textprivatemessage.message = cmd.parameters["message"]
            self.send_message(PYMUMBLE_MSG_TYPES_TEXTMESSAGE, textprivatemessage)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_MSG_TYPES_CHANNELSTATE:
            channelstate = mumble_pb2.ChannelState()
            channelstate.parent = cmd.parameters["parent"]
            channelstate.name = cmd.parameters["name"]
            channelstate.temporary = cmd.parameters["temporary"]
            self.send_message(PYMUMBLE_MSG_TYPES_CHANNELSTATE, channelstate)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_MSG_TYPES_CHANNELREMOVE:
            channelremove = mumble_pb2.ChannelRemove()
            channelremove.channel_id = cmd.parameters["channel_id"]
            self.send_message(PYMUMBLE_MSG_TYPES_CHANNELREMOVE, channelremove)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_CMD_UPDATECHANNEL:
            channelstate = mumble_pb2.ChannelState()
            for key, value in cmd.parameters.items():
                setattr(channelstate, key, value)
            self.send_message(PYMUMBLE_MSG_TYPES_CHANNELSTATE, channelstate)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_CMD_LINKCHANNEL:
            channelstate = mumble_pb2.ChannelState()
            channelstate.channel_id = cmd.parameters["channel_id"]
            channelstate.links_add.append(cmd.parameters["add_id"])
            self.send_message(PYMUMBLE_MSG_TYPES_CHANNELSTATE, channelstate)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_CMD_UNLINKCHANNEL:
            channelstate = mumble_pb2.ChannelState()
            channelstate.channel_id = cmd.parameters["channel_id"]
            for remove_id in cmd.parameters["remove_ids"]:
                channelstate.links_remove.append(remove_id)
            self.send_message(PYMUMBLE_MSG_TYPES_CHANNELSTATE, channelstate)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_MSG_TYPES_VOICETARGET:
            textvoicetarget = mumble_pb2.VoiceTarget()
            textvoicetarget.id = cmd.parameters["id"]
            targets = []
            if cmd.parameters["id"] == 1:
                voicetarget = mumble_pb2.VoiceTarget.Target()
                voicetarget.channel_id = cmd.parameters["targets"][0]
                targets.append(voicetarget)
            else:
                for target in cmd.parameters["targets"]:
                    voicetarget = mumble_pb2.VoiceTarget.Target()
                    voicetarget.session.append(target)
                    targets.append(voicetarget)
            textvoicetarget.targets.extend(targets)
            self.send_message(PYMUMBLE_MSG_TYPES_VOICETARGET, textvoicetarget)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_CMD_MODUSERSTATE:
            userstate = mumble_pb2.UserState()
            userstate.session = cmd.parameters["session"]

            if "mute" in cmd.parameters:
                userstate.mute = cmd.parameters["mute"]
            if "self_mute" in cmd.parameters:
                userstate.self_mute = cmd.parameters["self_mute"]
            if "deaf" in cmd.parameters:
                userstate.deaf = cmd.parameters["deaf"]
            if "self_deaf" in cmd.parameters:
                userstate.self_deaf = cmd.parameters["self_deaf"]
            if "suppress" in cmd.parameters:
                userstate.suppress = cmd.parameters["suppress"]
            if "recording" in cmd.parameters:
                userstate.recording = cmd.parameters["recording"]
            if "comment" in cmd.parameters:
                userstate.comment = cmd.parameters["comment"]
            if "texture" in cmd.parameters:
                userstate.texture = cmd.parameters["texture"]
            if "user_id" in cmd.parameters:
                userstate.user_id = cmd.parameters["user_id"]
            if "plugin_context" in cmd.parameters:
                userstate.plugin_context = cmd.parameters["plugin_context"]

            self.send_message(PYMUMBLE_MSG_TYPES_USERSTATE, userstate)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_CMD_REMOVEUSER:
            userremove = mumble_pb2.UserRemove()
            userremove.session = cmd.parameters["session"]
            userremove.reason = cmd.parameters["reason"]
            userremove.ban = cmd.parameters["ban"]
            self.send_message(PYMUMBLE_MSG_TYPES_USERREMOVE, userremove)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_CMD_QUERYACL:
            acl = mumble_pb2.ACL()
            acl.channel_id = cmd.parameters["channel_id"]
            acl.query = True
            self.send_message(PYMUMBLE_MSG_TYPES_ACL, acl)
            cmd.response = True
            self.commands.answer(cmd)
        elif cmd.cmd == PYMUMBLE_CMD_UPDATEACL:
            acl = mumble_pb2.ACL()
            acl.channel_id = cmd.parameters["channel_id"]
            acl.inherit_acls = cmd.parameters["inherit_acls"]

            for msg_group in cmd.parameters["chan_group"]:
                chan_group = mumble_pb2.ACL.ChanGroup()
                chan_group.name = msg_group['name']
                if msg_group['inherited'] is not None:
                    chan_group.inherited = msg_group['inherited']
                if msg_group['inherit'] is not None:
                    chan_group.inherit = msg_group['inherit']
                if msg_group['inheritable'] is not None:
                    chan_group.inheritable = msg_group['inheritable']
                for add_id in msg_group['add']:
                    chan_group.add.append(add_id)
                for remove_id in msg_group['remove']:
                    chan_group.remove.append(remove_id)
                acl.groups.append(chan_group)

            for msg_acl in cmd.parameters["chan_acl"]:
                chan_acl = mumble_pb2.ACL.ChanACL()
                if msg_acl['apply_here'] is not None:
                    chan_acl.apply_here = msg_acl['apply_here']
                if msg_acl['apply_subs'] is not None:
                    chan_acl.apply_subs = msg_acl['apply_subs']
                if msg_acl['inherited'] is not None:
                    chan_acl.inherited = msg_acl['inherited']
                if msg_acl['user_id'] is not None:
                    chan_acl.user_id = msg_acl['user_id']
                if msg_acl['group'] is not None:
                    chan_acl.group = msg_acl['group']
                if msg_acl['grant'] is not None:
                    chan_acl.grant = msg_acl['grant']
                if msg_acl['deny'] is not None:
                    chan_acl.deny = msg_acl['deny']

                if not chan_acl.inherited:
                    acl.acls.append(chan_acl)

            acl.query = False
            self.send_message(PYMUMBLE_MSG_TYPES_ACL, acl)
            cmd.response = True
            self.commands.answer(cmd)

    def get_max_message_length(self):
        return self.server_max_message_length

    def get_max_image_length(self):
        return self.server_max_image_message_length

    def my_channel(self):
        return self.channels[self.users.myself["channel_id"]]

    @staticmethod
    def denial_type(n):
        return mumble_pb2.PermissionDenied.DenyType.Name(n)

    def stop(self):
        self.reconnect = None
        self.exit = True
        self.control_socket.close()
