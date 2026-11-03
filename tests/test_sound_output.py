import os
import socket
import struct
import subprocess
import sys
import unittest

from pymumble_py3 import Mumble
from pymumble_py3 import mumble_pb2
from pymumble_py3.constants import (
    PYMUMBLE_AUDIO_TYPE_OPUS,
    PYMUMBLE_MSG_TYPES_CODECVERSION,
    PYMUMBLE_MSG_TYPES_UDPTUNNEL,
    PYMUMBLE_SAMPLERATE,
)
from pymumble_py3.tools import VarInt


class SoundOutputTest(unittest.TestCase):
    def test_send_without_receiving(self):
        self.check_send(stereo=False, receive_sound=False)

    def test_send_with_receiving(self):
        self.check_send(stereo=False, receive_sound=True)

    def test_send_stereo_without_receiving(self):
        self.check_send(stereo=True, receive_sound=False)

    def check_send(self, stereo, receive_sound):
        import opuslib

        client = Mumble('localhost', 'test', stereo=stereo)
        client.set_receive_sound(receive_sound)
        client.init_connection()
        self.assertIsNotNone(client.sound_output)
        client.dispatch_control_message(
            PYMUMBLE_MSG_TYPES_CODECVERSION,
            mumble_pb2.CodecVersion(alpha=0, beta=0, prefer_alpha=True, opus=True).SerializeToString(),
        )
        self.assertIsNone(client.sound_output.encoder)
        client.set_bandwidth(64000)
        channels = 2 if stereo else 1
        pcm = bytes(1920 * channels)
        client.sound_output.add_sound(pcm)
        sender, receiver = socket.socketpair()
        self.addCleanup(sender.close)
        self.addCleanup(receiver.close)
        receiver.settimeout(1)
        client.control_socket = sender
        client.sound_output.send_audio()
        packet = receiver.recv(4096)
        message_type, length = struct.unpack('!HL', packet[:6])
        self.assertEqual(message_type, PYMUMBLE_MSG_TYPES_UDPTUNNEL)
        payload = packet[6:]
        self.assertEqual(len(payload), length)
        self.assertEqual(payload[0] >> 5, PYMUMBLE_AUDIO_TYPE_OPUS)
        sequence = VarInt()
        offset = 1 + sequence.decode(payload[1:])
        frame_length = VarInt()
        offset += frame_length.decode(payload[offset:])
        encoded = payload[offset:offset + (frame_length.value & 0x1FFF)]
        decoded = opuslib.Decoder(PYMUMBLE_SAMPLERATE, channels).decode(encoded, 960)
        self.assertEqual(len(decoded), len(pcm))
        self.assertEqual(client.sound_output.get_buffer_size(), 0)

    def test_reconnection_resets_outgoing_audio(self):
        client = Mumble('localhost', 'test')
        client.init_connection()
        original_output = client.sound_output
        client.dispatch_control_message(
            PYMUMBLE_MSG_TYPES_CODECVERSION,
            mumble_pb2.CodecVersion(alpha=0, beta=0, prefer_alpha=True, opus=True).SerializeToString(),
        )
        original_output.add_sound(bytes(1920))
        client.init_connection()
        self.assertIsNot(client.sound_output, original_output)
        self.assertEqual(client.sound_output.get_buffer_size(), 0)
        self.assertIsNone(client.sound_output.encoder)

    def test_text_only_does_not_import_opus(self):
        code = '''
import importlib.abc
import sys

class NoOpus(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'opuslib' or fullname.startswith('opuslib.'):
            raise ImportError('opuslib is unavailable for this test')

sys.meta_path.insert(0, NoOpus())
from pymumble_py3 import Mumble, mumble_pb2
from pymumble_py3.constants import PYMUMBLE_MSG_TYPES_CODECVERSION, PYMUMBLE_MSG_TYPES_UDPTUNNEL
client = Mumble('localhost', 'test')
client.init_connection()
client.dispatch_control_message(PYMUMBLE_MSG_TYPES_CODECVERSION,
                                mumble_pb2.CodecVersion(alpha=0, beta=0, prefer_alpha=True, opus=True).SerializeToString())
client.set_bandwidth(64000)
client.dispatch_control_message(PYMUMBLE_MSG_TYPES_UDPTUNNEL, b'')
assert not client.receive_sound
assert 'opuslib' not in sys.modules
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
