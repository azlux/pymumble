# -*- coding: utf-8 -*-
from .constants import *
from threading import Lock


class Cmd:
    """
    Define a command object, used to ask an action from the pymumble thread,
    usually to forward to the murmur server
    """
    def __init__(self):
        self.cmd_id = None
        self.lock = Lock()
        
        self.cmd = None
        self.parameters = None
        self.response = None


class MoveCmd(Cmd):
    """Command to move a user from channel"""
    def __init__(self, session, channel_id):
        Cmd.__init__(self)
        
        self.cmd = PYMUMBLE_CMD_MOVE
        self.parameters = {"session": session,
                           "channel_id": channel_id}

class TextMessage(Cmd):
    """Command to send a text message"""
    def __init__(self, session, channel_id, message):
        Cmd.__init__(self)

        self.cmd = PYMUMBLE_CMD_TEXTMESSAGE
        self.parameters = {"session": session,
                           "channel_id": channel_id,
                           "message": message}

class TextPrivateMessage(Cmd):
    """Command to send a private text message"""
    def __init__(self, session, message):
        Cmd.__init__(self)

        self.cmd = PYMUMBLE_CMD_TEXTPRIVATEMESSAGE
        self.parameters = {"session": session,
                           "message": message}

class ModUserState(Cmd):
    """Command to change a user state"""
    def __init__(self, session, params):
        Cmd.__init__(self)
        
        self.cmd = PYMUMBLE_CMD_MODUSERSTATE
        self.parameters = params
