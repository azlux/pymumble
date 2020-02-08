# -*- coding: utf-8 -*-
import typing
from threading import Lock

from .constants import *


class Cmd:
    """
    Define a command object, used to ask an action from the pymumble thread,
    usually to forward to the murmur server
    """

    def __init__(self) -> None:
        self.cmd_id: typing.Optional[int] = None
        self.lock = Lock()

        self.cmd: typing.Union[str, int, None] = None
        self.parameters: typing.Optional[typing.Mapping[str, typing.Any]] = None
        self.response: typing.Optional[bool] = None


class MoveCmd(Cmd):
    """Command to move a user from channel"""

    def __init__(self, session: int, channel_id: int) -> None:
        Cmd.__init__(self)

        self.cmd = PYMUMBLE_CMD_MOVE
        self.parameters = {"session": session, "channel_id": channel_id}


class TextMessage(Cmd):
    """Command to send a text message"""

    def __init__(self, session: int, channel_id: int, message: str) -> None:
        Cmd.__init__(self)

        self.cmd = PYMUMBLE_CMD_TEXTMESSAGE
        self.parameters = {
            "session": session,
            "channel_id": channel_id,
            "message": message,
        }


class TextPrivateMessage(Cmd):
    """Command to send a private text message"""

    def __init__(self, session: int, message: str) -> None:
        Cmd.__init__(self)

        self.cmd = PYMUMBLE_CMD_TEXTPRIVATEMESSAGE
        self.parameters = {"session": session, "message": message}


class ModUserState(Cmd):
    """Command to change a user state"""

    def __init__(self, session: int, params: typing.Mapping[str, typing.Any]) -> None:
        self.cmd = PYMUMBLE_CMD_MODUSERSTATE
        self.parameters = params


class CreateChannel(Cmd):
    """Command to create channel"""

    def __init__(self, parent: int, name: str, temporary: bool) -> None:
        Cmd.__init__(self)

        self.cmd = PYMUMBLE_MSG_TYPES_CHANNELSTATE
        self.parameters = {"parent": parent, "name": name, "temporary": temporary}


class RemoveChannel(Cmd):
    """Command to create channel"""

    def __init__(self, channel_id: int) -> None:
        Cmd.__init__(self)

        self.cmd = PYMUMBLE_MSG_TYPES_CHANNELREMOVE
        self.parameters = {"channel_id": channel_id}


class VoiceTarget(Cmd):
    """Command to create a whisper"""

    def __init__(self, voice_id: int, targets: typing.Sequence[int]) -> None:
        Cmd.__init__(self)

        self.cmd = PYMUMBLE_MSG_TYPES_VOICETARGET
        self.parameters = {"id": voice_id, "targets": targets}
