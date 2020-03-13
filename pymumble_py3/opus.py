import array
import ctypes
import typing
from ctypes.util import find_library  # type: ignore

lib_location = find_library('opus')

if lib_location is None:
    raise Exception(
        'Could not find Opus library. Make sure it is installed.')

libopus = ctypes.CDLL(lib_location)

c_int_pointer = ctypes.POINTER(ctypes.c_int)
c_int16_pointer = ctypes.POINTER(ctypes.c_int16)
c_float_pointer = ctypes.POINTER(ctypes.c_float)

strerror = libopus.opus_strerror
strerror.argtypes = (ctypes.c_int,)  # must be sequence (,) of types!
strerror.restype = ctypes.c_char_p
strerror.__doc__ = 'Converts an opus error code into a human readable string'


class OpusError(Exception):

    """
    Generic handler for OpusLib errors from C library.
    """

    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__()

    # FIXME: Remove typing.Any once we have a stub for ctypes
    def __str__(self) -> typing.Union[str, typing.Any]:
        return str(strerror(self.code))

class DecoderStruct(ctypes.Structure):
    """Opus decoder state.
    This contains the complete state of an Opus decoder.
    """
    pass

DecoderPointer = ctypes.POINTER(DecoderStruct)

libopus_decode = libopus.opus_decode
libopus_decode.argtypes = (
    DecoderPointer,
    ctypes.c_char_p,
    ctypes.c_int32,
    c_int16_pointer,
    ctypes.c_int,
    ctypes.c_int
)
libopus_decode.restype = ctypes.c_int

pcm_buffer = None

def decode(  # pylint: disable=too-many-arguments
        decoder_state: ctypes.Structure,
        opus_data: bytes,
        length: int,
        frame_size: int,
        decode_fec: bool,
        channels: int = 2
) -> typing.Union[bytes, typing.Any]:
    """
    Decode an Opus Frame to PCM.

    Unlike the `opus_decode` function , this function takes an additional
    parameter `channels`, which indicates the number of channels in the frame.
    """
    global pcm_buffer
    _decode_fec = int(decode_fec)
    result = 0

    pcm_size = frame_size * channels * ctypes.sizeof(ctypes.c_int16)
    if pcm_buffer is None:
        pcm_buffer = (ctypes.c_int16 * pcm_size)()

    pcm_pointer = ctypes.cast(pcm_buffer, c_int16_pointer)

    result = libopus_decode(
        decoder_state,
        opus_data,
        length,
        pcm_pointer,
        frame_size,
        _decode_fec
    )

    if result < 0:
        raise OpusError(result)
    arr = array.array('h', pcm_pointer[:result * channels])
    ret = arr.tobytes()
    return ret


libopus_create = libopus.opus_decoder_create
libopus_create.argtypes = (
    ctypes.c_int,
    ctypes.c_int,
    c_int_pointer
)
libopus_create.restype = DecoderPointer

def create_state(fs: int, channels: int) -> ctypes.Structure:
    """
    Allocates and initializes a decoder state.
    Wrapper for C opus_decoder_create()

    `fs` must be one of 8000, 12000, 16000, 24000, or 48000.

    Internally Opus stores data at 48000 Hz, so that should be the default
    value for Fs. However, the decoder can efficiently decode to buffers
    at 8, 12, 16, and 24 kHz so if for some reason the caller cannot use data
    at the full sample rate, or knows the compressed data doesn't use the full
    frequency range, it can request decoding at a reduced rate. Likewise, the
    decoder is capable of filling in either mono or interleaved stereo pcm
    buffers, at the caller's request.

    :param fs: Sample rate to decode at (Hz).
    :param int: Number of channels (1 or 2) to decode.
    """
    result_code = ctypes.c_int()

    decoder_state = libopus_create(
        fs,
        channels,
        ctypes.byref(result_code)
    )

    if result_code.value is not 0:
        raise OpusError(result_code.value)

    return decoder_state

destroy = libopus.opus_decoder_destroy
destroy.argtypes = (DecoderPointer,)
destroy.restype = None
destroy.__doc__ = 'Frees an OpusDecoder allocated by opus_decoder_create()'

class Decoder(object):

    """High-Level Decoder Object."""

    def __init__(self, fs: int, channels: int) -> None:
        """
        :param fs: Sample Rate.
        :param channels: Number of channels.
        """
        self._fs = fs
        self._channels = channels
        self.decoder_state = create_state(fs, channels)

    def __del__(self) -> None:
        if hasattr(self, 'decoder_state'):
            # Destroying state only if __init__ completed successfully
            destroy(self.decoder_state)


    # FIXME: Remove typing.Any once we have a stub for ctypes
    def decode(
            self,
            opus_data: bytes,
            frame_size: int,
            decode_fec: bool = False
    ) -> typing.Union[bytes, typing.Any]:
        """
        Decodes given Opus data to PCM.
        """
        return decode(
            self.decoder_state,
            opus_data,
            len(opus_data),
            frame_size,
            decode_fec,
            channels=self._channels
        )
