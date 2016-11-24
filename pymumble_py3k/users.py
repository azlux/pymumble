# -*- coding: utf-8 -*-
from .constants import *
from threading import Lock
from . import soundqueue
from . import messages


class Users(dict):
    """Object that stores and update all connected users"""

    def __init__(self, mumble_object, callbacks):
        self.mumble_object = mumble_object
        self.callbacks = callbacks

        self.myself = None  # user object of the pymumble thread itself
        self.myself_session = None  # session number of the pymumble thread itself
        self.lock = Lock()

    def update(self, message):
        """Update a user informations, based in an incoming message"""
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

    def remove(self, message):
        """Remove a user object based on server info"""
        self.lock.acquire()

        if message.session in self:
            user = self[message.session]
            del self[message.session]
            self.callbacks(PYMUMBLE_CLBK_USERREMOVED, user, message)

        self.lock.release()

    def set_myself(self, session):
        """Set the "myself" user"""
        self.myself_session = session
        if session in self:
            self.myself = self[session]

    def count(self):
        """Return the count of connected users"""
        return len(self)


class User(dict):
    """Object that store one user"""

    def __init__(self, mumble_object, message):
        self.mumble_object = mumble_object
        self["session"] = message.session
        self.update(message)

        self.sound = soundqueue.SoundQueue(self.mumble_object)  # will hold this user incoming audio

    def update(self, message):
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

    def update_field(self, name, field):
        """Update one state value for a user"""
        actions = dict()
        if name not in self or self[name] != field:
            self[name] = field
            actions[name] = field

        return actions

    def get_property(self, property):
        if property in self:
            return self[property]
        else:
            return None

    def mute(self):
        """Mute a user"""
        params = {"session": self["session"]}

        if self["session"] == self.mumble_object.users.myself_session:
            params["self_mute"] = True
        else:
            params["mute"] = True

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def unmute(self):
        """Unmute a user"""
        params = {"session": self["session"]}

        if self["session"] == self.mumble_object.users.myself_session:
            params["self_mute"] = False
        else:
            params["mute"] = False

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def deafen(self):
        """Deafen a user"""
        params = {"session": self["session"]}

        if self["session"] == self.mumble_object.users.myself_session:
            params["self_deaf"] = True
        else:
            params["deaf"] = True

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def undeafen(self):
        """Undeafen a user"""
        params = {"session": self["session"]}

        if self["session"] == self.mumble_object.users.myself_session:
            params["self_deaf"] = False
        else:
            params["deaf"] = False

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def suppress(self):
        """Disable a user"""
        params = {"session": self["session"],
                  "suppress": True}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def unsuppress(self):
        """Enable a user"""
        params = {"session": self["session"],
                  "suppress": False}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def recording(self):
        """Set the user as recording"""
        params = {"session": self["session"],
                  "recording": True}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def unrecording(self):
        """Set the user as not recording"""
        params = {"session": self["session"],
                  "recording": False}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def comment(self, comment):
        """Set the user comment"""
        params = {"session": self["session"],
                  "comment": comment}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def texture(self, texture):
        """Set the user texture"""
        params = {"session": self["session"],
                  "texture": texture}

        cmd = messages.ModUserState(self.mumble_object.users.myself_session, params)
        self.mumble_object.execute_command(cmd)

    def move_in(self, channel_id):
        session = self.mumble_object.users.myself_session
        cmd = messages.MoveCmd(session, channel_id)
        self.mumble_object.execute_command(cmd)

    def send_message(self, message):
        """Send a text message to the user."""
        cmd = messages.TextPrivateMessage(self["session"], message)
        self.mumble_object.execute_command(cmd)
