# -*- coding: utf-8 -*-


class CodecNotSupportedError(Exception):
    """Thrown when receiving an audio packet from an unsupported codec"""

    def __init__(self, value: str):
        self.value = value

    def __str__(self) -> str:
        return repr(self.value)


class ConnectionRejectedError(Exception):
    """Thrown when server reject the connection"""

    def __init__(self, value: str):
        self.value = value

    def __str__(self) -> str:
        return repr(self.value)


class InvalidFormatError(Exception):
    """Thrown when receiving a packet not understood"""

    def __init__(self, value: str):
        self.value = value

    def __str__(self) -> str:
        return repr(self.value)


class UnknownCallbackError(Exception):
    """Thrown when asked for an unknown callback"""

    def __init__(self, value: str):
        self.value = value

    def __str__(self) -> str:
        return repr(self.value)


class UnknownChannelError(Exception):
    """Thrown when using an unknown channel"""

    def __init__(self, value: str):
        self.value = value

    def __str__(self) -> str:
        return repr(self.value)


class InvalidSoundDataError(Exception):
    """Thrown when trying to send an invalid audio pcm data"""

    def __init__(self, value: str):
        self.value = value

    def __str__(self) -> str:
        return repr(self.value)


class InvalidVarInt(Exception):
    """Thrown when trying to decode an invalid varint"""

    def __init__(self, value: str):
        self.value = value

    def __str__(self) -> str:
        return repr(self.value)


class TextTooLongError(Exception):
    """Thrown when trying to send a message which is longer than allowed"""

    def __init__(self, value: int):
        self.value = value

    def __str__(self) -> str:
        return "Maximum Text allowed length: {}".format(self.value)


class ImageTooBigError(Exception):
    """Thrown when trying to send a message or image which is longer than allowed"""

    def __init__(self, value: int):
        self.value = value

    def __str__(self) -> str:
        return "Maximum Text/Image allowed length: {}".format(self.value)
