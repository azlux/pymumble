# -*- coding: utf-8 -*-

import socket
import struct
import threading
import typing
from time import time

import opuslib

from .constants import *
from .errors import CodecNotSupportedError
from .messages import VoiceTarget
from .tools import VarInt

if typing.TYPE_CHECKING:
    from .mumble import Mumble

ProtoMessage = typing.Any


class SoundOutput:
    """
    Class managing the sounds that must be sent to the server (best sent in a multiple of audio_per_packet samples)
    The buffering is the responsibility of the caller, any partial sound will be sent without delay
    """

    def __init__(
        self,
        mumble_object: "Mumble",
        audio_per_packet: float,
        bandwidth: int,
        opus_profile: str = PYMUMBLE_AUDIO_TYPE_OPUS_PROFILE,
    ):
        """
        audio_per_packet=packet audio duration in sec
        bandwidth=maximum total outgoing bandwidth
        """
        self.mumble_object = mumble_object

        self.Log = self.mumble_object.Log

        self.pcm: typing.List[bytes] = []
        self.lock = threading.Lock()

        self.codec: typing.Optional[
            ProtoMessage
        ] = None  # codec currently requested by the server
        self.encoder: typing.Optional[
            opuslib.Encoder
        ] = None  # codec instance currently used to encode
        self.encoder_framesize: typing.Optional[
            float
        ] = None  # size of an audio frame for the current codec (OPUS=audio_per_packet, CELT=0.01s)
        self.opus_profile = opus_profile

        self.set_audio_per_packet(audio_per_packet)
        self.set_bandwidth(bandwidth)

        self.codec_type: typing.Optional[
            int
        ] = None  # codec type number to be used in audio packets
        self.target = 0  # target is not implemented yet, so always 0

        self.sequence_start_time = 0.0  # time of sequence 1
        self.sequence_last_time = 0.0  # time of the last emitted packet
        self.sequence = 0  # current sequence

    def send_audio(self) -> None:
        """send the available audio to the server, taking care of the timing"""
        if (
            not self.encoder or len(self.pcm) == 0
        ):  # no codec configured or no audio sent
            return

        assert self.encoder_framesize is not None
        assert self.codec_type is not None
        assert self.mumble_object.control_socket is not None

        samples = int(
            self.encoder_framesize * PYMUMBLE_SAMPLERATE * 2
        )  # number of samples in an encoder frame

        while (
            len(self.pcm) > 0
            and self.sequence_last_time + self.audio_per_packet <= time()
        ):  # audio to send and time to send it (since last packet)
            current_time = time()
            if (
                self.sequence_last_time + PYMUMBLE_SEQUENCE_RESET_INTERVAL
                <= current_time
            ):  # waited enough, resetting sequence to 0
                self.sequence = 0
                self.sequence_start_time = current_time
                self.sequence_last_time = current_time
            elif (
                self.sequence_last_time + (self.audio_per_packet * 2) <= current_time
            ):  # give some slack (2*audio_per_frame) before interrupting a continuous sequence
                # calculating sequence after a pause
                self.sequence = int(
                    (current_time - self.sequence_start_time)
                    / PYMUMBLE_SEQUENCE_DURATION
                )
                self.sequence_last_time = self.sequence_start_time + (
                    self.sequence * PYMUMBLE_SEQUENCE_DURATION
                )
            else:  # continuous sound
                self.sequence += int(self.audio_per_packet / PYMUMBLE_SEQUENCE_DURATION)
                self.sequence_last_time = self.sequence_start_time + (
                    self.sequence * PYMUMBLE_SEQUENCE_DURATION
                )

            payload = (
                bytearray()
            )  # content of the whole packet, without tcptunnel header
            audio_encoded = 0.0  # audio time already in the packet

            while (
                len(self.pcm) > 0 and audio_encoded < self.audio_per_packet
            ):  # more audio to be sent and packet not full
                self.lock.acquire()
                to_encode = self.pcm.pop(0)
                self.lock.release()

                if (
                    len(to_encode) != samples
                ):  # pad to_encode if needed to match sample length
                    to_encode += b"\x00" * (samples - len(to_encode))

                try:
                    encoded = self.encoder.encode(to_encode, len(to_encode) // 2)
                except opuslib.exceptions.OpusError:
                    encoded = b""

                audio_encoded += self.encoder_framesize

                # create the audio frame header
                if self.codec_type == PYMUMBLE_AUDIO_TYPE_OPUS:
                    frameheader = VarInt(len(encoded)).encode()
                else:
                    encoded_len = len(encoded)
                    if (
                        audio_encoded < self.audio_per_packet and len(self.pcm) > 0
                    ):  # if not last frame for the packet, set the terminator bit
                        encoded_len += 1 << 7
                    frameheader = bytearray(struct.pack("!B", encoded_len))

                payload += frameheader + encoded  # add the frame to the packet

            header = self.codec_type << 5  # encapsulate in audio packet
            sequence = VarInt(self.sequence).encode()

            udppacket = struct.pack("!B", header | self.target) + sequence + payload

            self.Log.debug(
                "audio packet to send: sequence:{sequence}, type:{type}, length:{len}".format(
                    sequence=self.sequence, type=self.codec_type, len=len(udppacket)
                )
            )

            tcppacket = (
                struct.pack("!HL", PYMUMBLE_MSG_TYPES_UDPTUNNEL, len(udppacket))
                + udppacket
            )  # encapsulate in tcp tunnel

            while len(tcppacket) > 0:
                sent = self.mumble_object.control_socket.send(tcppacket)
                if sent < 0:
                    raise socket.error("Server socket error")
                tcppacket = tcppacket[sent:]

    def get_audio_per_packet(self) -> float:
        """return the configured length of a audio packet (in ms)"""
        return self.audio_per_packet

    def set_audio_per_packet(self, audio_per_packet: float) -> None:
        """set the length of an audio packet (in ms)"""
        self.audio_per_packet = audio_per_packet
        self.create_encoder()

    def get_bandwidth(self) -> int:
        """get the configured bandwidth for the audio output"""
        return self.bandwidth

    def set_bandwidth(self, bandwidth: int) -> None:
        """set the bandwidth for the audio output"""
        self.bandwidth = bandwidth
        self._set_bandwidth()

    def _set_bandwidth(self) -> None:
        """do the calculation of the overhead and configure the actual bitrate for the codec"""
        if self.encoder:
            assert self.encoder_framesize is not None

            overhead_per_packet = 20  # IP header in bytes
            overhead_per_packet += 3 * int(
                self.audio_per_packet / self.encoder_framesize
            )  # overhead per frame
            if self.mumble_object.udp_active:
                overhead_per_packet += 12  # UDP header
            else:
                overhead_per_packet += 20  # TCP header
                overhead_per_packet += 6  # TCPTunnel encapsulation

            overhead_per_second = int(
                overhead_per_packet * 8 / self.audio_per_packet
            )  # in bits

            self.Log.debug(
                "Bandwidth is {bandwidth}, downgrading to {bitrate} due to the protocol overhead".format(
                    bandwidth=self.bandwidth,
                    bitrate=self.bandwidth - overhead_per_second,
                )
            )

            self.encoder.bitrate = self.bandwidth - overhead_per_second

    def add_sound(self, pcm: bytes) -> None:
        """add sound to be sent (in PCM mono 16 bits signed format)"""
        if len(pcm) % 2 != 0:  # check that the data is align on 16 bits
            raise Exception("pcm data must be mono 16 bits")

        if self.encoder_framesize is None:
            raise Exception("encoder not initialized")

        samples = int(
            self.encoder_framesize * PYMUMBLE_SAMPLERATE * 2
        )  # number of samples in an encoder frame

        self.lock.acquire()
        if len(self.pcm) and len(self.pcm[-1]) < samples:
            initial_offset = samples - len(self.pcm[-1])
            self.pcm[-1] += pcm[:initial_offset]
        else:
            initial_offset = 0
        for i in range(initial_offset, len(pcm), samples):
            self.pcm.append(pcm[i : i + samples])
        self.lock.release()

    def clear_buffer(self) -> None:
        self.lock.acquire()
        self.pcm = []
        self.lock.release()

    def get_buffer_size(self) -> float:
        """return the size of the unsent buffer in sec"""
        return sum(len(chunk) for chunk in self.pcm) / 2.0 / PYMUMBLE_SAMPLERATE

    def set_default_codec(self, codecversion: ProtoMessage) -> None:
        """Set the default codec to be used to send packets"""
        self.codec = codecversion
        self.create_encoder()

    def create_encoder(self) -> None:
        """create the encoder instance, and set related constants"""
        if not self.codec:
            return

        if self.codec.opus:
            self.encoder = opuslib.Encoder(
                PYMUMBLE_SAMPLERATE, PYMUMBLE_CHANNELS, self.opus_profile
            )
            self.encoder_framesize = self.audio_per_packet
            self.codec_type = PYMUMBLE_AUDIO_TYPE_OPUS
        else:
            raise CodecNotSupportedError("")

        self._set_bandwidth()

    def set_whisper(
        self, target_id: typing.Union[typing.List[int], int], channel: bool = False
    ) -> None:
        if not target_id:
            return
        if isinstance(target_id, int):
            target_id = [target_id]
        self.target = 2
        if channel:
            self.target = 1
        cmd = VoiceTarget(self.target, target_id)
        self.mumble_object.execute_command(cmd)

    def remove_whisper(self) -> None:
        self.target = 0
        cmd = VoiceTarget(self.target, [])
        self.mumble_object.execute_command(cmd)
