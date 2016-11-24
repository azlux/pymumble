# -*- coding: utf-8 -*-


class CodecNotSupportedError(Exception):
    """Throwned when receiving an audio packet from an unsupported codec"""
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class ConnectionRejectedError(Exception):
    """Throwned when server reject the connection"""
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class InvalidFormatError(Exception):
    """Throwned when receiving a packet not understood"""
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class UnknownCallbackError(Exception):
    """Throwned when asked for an unknown callback"""
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class UnknownChannelError(Exception):
    """Throwned when using an unknown channel"""
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)
    

class InvalidSoundDataError(Exception):
    """Throwned when trying to send an invalid audio pcm data"""
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)
    

class InvalidVarInt(Exception):
    """Throwned when trying to decode an invalid varint"""
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)
