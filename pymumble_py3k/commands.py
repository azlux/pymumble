# -*- coding: utf-8 -*-
from threading import Lock
from collections import deque


class Commands:
    """
    Store to commands to be sent to the murmur server,
    from whatever tread.
    Each command has it's own lock semaphore to signal is received an answer
    """
    def __init__(self):
        self.id = 0
        
        self.queue = deque() 
        
        self.lock = Lock()
    
    def new_cmd(self, cmd):
        """Add a command to the queue"""
        self.lock.acquire()

        self.id += 1
        cmd.msg_id = self.id
        self.queue.appendleft(cmd)
        cmd.lock.acquire()

        self.lock.release()
        return cmd.lock
    
    def is_cmd(self):
        """Check if there is a command waiting in the queue"""
        if len(self.queue) > 0:
            return True
        else:
            return False
        
    def pop_cmd(self):
        """Return the next command and remove it from the queue"""
        self.lock.acquire()

        if len(self.queue) > 0:
            question = self.queue.pop()
            self.lock.release()
            return question
        else:
            self.lock.release()
            return None
    
    def answer(self, cmd):
        """Unlock the command to signal it's completion"""
        cmd.lock.release()
    

