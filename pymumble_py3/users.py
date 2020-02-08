# -*- coding: utf-8 -*-
import typing
from threading import Lock

from . import messages, mumble_pb2, soundqueue
from .callbacks import CallBacks
from .constants import *
from .errors import ImageTooBigError, TextTooLongError

if typing.TYPE_CHECKING:
    from .mumble import Mumble

ProtoMessage = typing.Any


class Users(typing.Dict[int, "User"]):
    """Object that stores and update all connected users"""

    def __init__(self, mumble_object: "Mumble", callbacks: CallBacks):
        self.mumble_object = mumble_object
        self.callbacks = callbacks

        self.myself: typing.Optional[
            "User"
        ] = None  # user object of the pymumble thread itself
        self.myself_session: typing.Optional[
            int
        ] = None  # session number of the pymumble thread itself
        self.lock = Lock()

    def update(self, message: ProtoMessage) -> None:  # type: ignore
        """Update a user information, based on the incoming message"""
        self.lock.acquire()

        if message.session not in self:
            self[message.session] = User(self.mumble_object, message)
            self.callbacks(PYMUMBLE_CLBK_USERCREATED, self[message.session])
            if message.session == self.myself_session:
                self.myself = self[message.session]
        else:
            actions = self[message.session].update(message)
            self.callbacks(PYMUMBLE_CLBK_USERUPDATED, self[message.session], actions)

        self.lock.release()

    def remove(self, message: ProtoMessage) -> None:
        """Remove a user object based on server info"""
        self.lock.acquire()

        if message.session in self:
            user = self[message.session]
            del self[message.session]
            self.callbacks(PYMUMBLE_CLBK_USERREMOVED, user, message)

        self.lock.release()

    def set_myself(self, session: int) -> None:
        """Set the "myself" user"""
        self.myself_session = session
        if session in self:
            self.myself = self[session]

    def count(self) -> int:
        """Return the count of connected users"""
        return len(self)


class User(typing.Dict[str, typing.Any]):
    """Object that store one user"""

    def __init__(self, mumble_object: "Mumble", message: ProtoMessage):
        self.mumble_object = mumble_object
        self["session"] = message.session
        self["channel_id"] = 0
        self.update(message)

        self.sound = soundqueue.SoundQueue(
            self.mumble_object
        )  # will hold this user incoming audio

    def update(self, message: ProtoMessage) -> typing.Dict[str, typing.Any]:  # type: ignore
        """Update user state, based on an incoming message"""
        actions = dict()

        if message.HasField("actor"):
            actions["actor"] = message.actor

        for (field, value) in message.ListFields():
            if field.name in ("session", "actor", "comment", "texture"):
                continue
            actions.update(self.update_field(field.name, value))

        if message.HasField("comment_hash"):
            if message.HasField("comment"):
                self.mumble_object.blobs[message.comment_hash] = message.comment
            else:
                self.mumble_object.blobs.get_user_comment(message.comment_hash)
        if message.HasField("texture_hash"):
            if message.HasField("texture"):
                self.mumble_object.blobs[message.texture_hash] = message.texture
            else:
                self.mumble_object.blobs.get_user_texture(message.texture_hash)

        return actions  # return a dict, useful for the callback functions

    def update_field(
        self, name: str, field: typing.Any
    ) -> typing.Dict[str, typing.Any]:
        """Update one state value for a user"""
        actions = dict()
        if name not in self or self[name] != field:
            self[name] = field
            actions[name] = field

        return actions

    def get_property(self, property: str) -> typing.Any:
        if property in self:
            return self[property]
        else:
            return None

    def mute(self) -> None:
        """Mute a user"""
        assert self.mumble_object.users.myself_session is not None

        params = {"session": self["session"]}

        if self["session"] == self.mumble_object.users.myself_session:
            params["self_mute"] = True
        else:
            params["mute"] = True

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def unmute(self) -> None:
        """Unmute a user"""
        assert self.mumble_object.users.myself_session is not None

        params = {"session": self["session"]}

        if self["session"] == self.mumble_object.users.myself_session:
            params["self_mute"] = False
        else:
            params["mute"] = False

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def deafen(self) -> None:
        """Deafen a user"""
        assert self.mumble_object.users.myself_session is not None

        params = {"session": self["session"]}

        if self["session"] == self.mumble_object.users.myself_session:
            params["self_deaf"] = True
        else:
            params["deaf"] = True

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def undeafen(self) -> None:
        """Undeafen a user"""
        assert self.mumble_object.users.myself_session is not None

        params = {"session": self["session"]}

        if self["session"] == self.mumble_object.users.myself_session:
            params["self_deaf"] = False
        else:
            params["deaf"] = False

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def suppress(self) -> None:
        """Disable a user"""
        assert self.mumble_object.users.myself_session is not None

        params = {"session": self["session"], "suppress": True}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def unsuppress(self) -> None:
        """Enable a user"""
        assert self.mumble_object.users.myself_session is not None

        params = {"session": self["session"], "suppress": False}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def recording(self) -> None:
        """Set the user as recording"""
        assert self.mumble_object.users.myself_session is not None

        params = {"session": self["session"], "recording": True}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def unrecording(self) -> None:
        """Set the user as not recording"""
        assert self.mumble_object.users.myself_session is not None

        params = {"session": self["session"], "recording": False}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def comment(self, comment: str) -> None:
        """Set the user comment"""
        assert self.mumble_object.users.myself_session is not None

        params = {"session": self["session"], "comment": comment}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def texture(self, texture: bytes) -> None:
        """Set the user texture"""
        assert self.mumble_object.users.myself_session is not None

        params = {"session": self["session"], "texture": texture}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def register(self) -> None:
        """Register the user (mostly for myself)"""
        assert self.mumble_object.users.myself_session is not None

        params = {"session": self["session"], "user_id": 0}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def move_in(self, channel_id: int, token: typing.Optional[str] = None) -> None:
        if token:
            authenticate = mumble_pb2.Authenticate()
            authenticate.username = self.mumble_object.user
            authenticate.password = self.mumble_object.password
            authenticate.tokens.extend(self.mumble_object.tokens)
            authenticate.tokens.extend([token])
            authenticate.opus = True
            self.mumble_object.Log.debug("sending: authenticate: %s", authenticate)
            self.mumble_object.send_message(
                PYMUMBLE_MSG_TYPES_AUTHENTICATE, authenticate
            )

        session = self.mumble_object.users.myself_session
        assert session is not None
        cmd = messages.MoveCmd(session, channel_id)
        self.mumble_object.execute_command(cmd)

    def send_text_message(self, message: str) -> None:
        """Send a text message to the user."""

        # TODO: This check should be done inside execute_command()
        # However, this is currently not possible because execute_command() does
        # not actually execute the command.
        if len(message) > self.mumble_object.get_max_image_length() != 0:
            raise ImageTooBigError(self.mumble_object.get_max_image_length())

        if not ("<img" in message and "src" in message):
            if len(message) > self.mumble_object.get_max_message_length():
                raise TextTooLongError(self.mumble_object.get_max_message_length())

        cmd = messages.TextPrivateMessage(self["session"], message)
        self.mumble_object.execute_command(cmd)
