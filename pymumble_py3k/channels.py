# -*- coding: utf-8 -*-
from .constants import *
from threading import Lock
from .errors import UnknownChannelError
from . import messages


class Channels(dict):
    """
    Object that Stores all channels and their properties.
    """
    def __init__(self, mumble_object, callbacks):
        self.mumble_object = mumble_object
        self.callbacks = callbacks
        
        self.lock = Lock()
        
    def update(self, message):
        """Update the channel informations based on an incoming message"""
        self.lock.acquire()

        if message.channel_id not in self:  # create the channel
            self[message.channel_id] = Channel(self.mumble_object, message)
            self.callbacks(PYMUMBLE_CLBK_CHANNELCREATED, self[message.channel_id])
        else:  # update the channel
            actions = self[message.channel_id].update(message)
            self.callbacks(PYMUMBLE_CLBK_CHANNELUPDATED, self[message.channel_id], actions)

        self.lock.release()
             
    def remove(self, id):  
        """Delete a channel when server signal the channel is removed"""
        self.lock.acquire()

        if id in self:
            channel = self[id]
            del self[id]
            self.callbacks(PYMUMBLE_CLBK_CHANNELREMOVED, channel)

        self.lock.release()
    
    def find_by_tree(self, tree):
        """Find a channel by its full path (a list with an element for each leaf)"""
        if not getattr(tree, '__iter__', False):
            tree = tree  # function use argument as a list

        current = self[0]
        
        for name in tree:  # going up the tree
            found = False
            for subchannel in self.get_childs(current).values():
                if subchannel["name"] == name:
                    current = subchannel
                    found = True
                    break
            
            if not found:  # channel not found
                err = "Cannot find channel %s" % str(tree)
                raise UnknownChannelError(err)
               
        return current
    
    def get_childs(self, channel):
        """Get the childs of a channel in a list"""
        childs = list()
        
        for item in self.values():
            if item["parent"] == channel["channel_id"]:
                childs.append(item)
                
        return childs
    
    def get_descendants(self, channel):
        """Get all the descendant of a channel, in nested lists"""
        descendants = list()
        
        for subchannel in channel.get_childs():
            descendants.append(subchannel.get_childs())
            
        return descendants
    
    def get_tree(self, channel):
        """Get the whole list of channels, in a multidimensionnal list""" 
        tree = list()
        
        current = channel
        
        while current["channel_id"] != 0:
            tree.insert(0, current)
            current = self[current["channel_id"]]
            
        tree.insert(0, self[0])
        
        return tree
    
    def find_by_name(self, name):
        """Find a channel by name.  Stop on the first that match"""
        if name == "":
            return self[0]
        
        for obj in list(self.values()):
            if obj["name"] == name:
                return obj
        
        err = "Channel %s does not exists" % name
        raise UnknownChannelError(err)
        

class Channel(dict):
    """
    Stores informations about one specific channel
    """
    def __init__(self, mumble_object, message):
        self.mumble_object = mumble_object
        self["channel_id"] = message.channel_id
        self.update(message)
    
    def update(self, message):
        """Update a channel based on an incoming message"""
        actions = dict()
        
        for (field, value) in message.ListFields():
            if field.name in ("session", "actor", "description_hash"):
                continue
            actions.update(self.update_field(field.name, value))

        if message.HasField("description_hash"):
            actions.update(self.update_field("description_hash", message.description_hash))
            if message.HasField("description"):
                self.mumble_object.blobs[message.description_hash] = message.description
            else:
                self.mumble_object.blobs.get_channel_description(message.description_hash)
        
        return actions  # return a dict with updates performed, useful for the callback functions

    def update_field(self, name, field):
        """Update one value"""
        actions = dict()
        if name not in self or self[name] != field:
            self[name] = field
            actions[name] = field
            
        return actions  # return a dict with updates performed, useful for the callback functions
    
    def get_property(self, property):
        if property in self:
            return self[property]
        else:
            return None
        
    def move_in(self, session=None):
        """Ask to move a session in a specific channel.  By default move pymumble own session"""
        if session is None:
            session = self.mumble_object.users.myself_session
        
        cmd = messages.MoveCmd(session, self["channel_id"])
        self.mumble_object.execute_command(cmd)
    

    def send_text_message(self, message):
        """Send a text message to the channel."""
        session = self.mumble_object.users.myself_session

        cmd = messages.TextMessage(session, self["channel_id"], message)
        self.mumble_object.execute_command(cmd)
