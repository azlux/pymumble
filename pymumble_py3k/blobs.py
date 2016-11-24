# -*- coding: utf-8 -*-
import struct

from .constants import *
from .mumble_pb2 import RequestBlob


class Blobs(dict):
    """
    Manage the Blob library
    """
    def __init__(self, mumble_object):
        self.mumble_object = mumble_object
        
    def get_user_comment(self, hash):
        """Request the comment of a user"""
        if hash in self:
            return
        request = RequestBlob()
        request.session_comment.extend(struct.unpack("!5I", hash))
        
        self.mumble_object.send_message(PYMUMBLE_MSG_TYPES_REQUESTBLOB, request)
    
    def get_user_texture(self, hash):
        """Request the image of a user"""
        if hash in self:
            return

        request = RequestBlob()
        request.session_texture.extend(struct.unpack("!5I", hash))
        
        self.mumble_object.send_message(PYMUMBLE_MSG_TYPES_REQUESTBLOB, request)
    
    def get_channel_description(self, hash):
        """Request the description/comment of a channel"""
        if hash in self:
            return

        request = RequestBlob()
        request.channel_description.extend(struct.unpack("!5I", hash))
        
        self.mumble_object.send_message(PYMUMBLE_MSG_TYPES_REQUESTBLOB, request)
