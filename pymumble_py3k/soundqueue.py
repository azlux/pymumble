# -*- coding: utf-8 -*-
import time
from threading import Lock
from collections import deque

import opuslib

from .constants import *


class SoundQueue:
    """
    Per user storage of received audio frames
    Takes care of the decoding of the received audio
    """
    def __init__(self, mumble_object):
        self.mumble_object = mumble_object
        
        self.queue = deque()
        self.start_sequence = None
        self.start_time = None

        self.receive_sound = True
        
        self.lock = Lock()
        
        # to be sure, create every supported decoders for all users
        # sometime, clients still use a codec for a while after server request another...
        self.decoders = {
                    PYMUMBLE_AUDIO_TYPE_OPUS: opuslib.Decoder(PYMUMBLE_SAMPLERATE, 1)
        }

    def set_receive_sound(self, value):
        """Define if received sounds must be kept or discarded in this specific queue (user)"""
        if value:
            self.receive_sound = True
        else:
            self.receive_sound = False

    def add(self, audio, sequence, type, target):
        """Add a new audio frame to the queue, after decoding"""
        if not self.receive_sound:
            return None
        
        self.lock.acquire()
        
        try:
            pcm = self.decoders[type].decode(audio, PYMUMBLE_READ_BUFFER_SIZE)

            if not self.start_sequence or sequence <= self.start_sequence:
                # New sequence started
                self.start_time = time.time()
                self.start_sequence = sequence
                calculated_time = self.start_time
            else:
                # calculating position in current sequence
                calculated_time = self.start_time + (sequence - self.start_sequence) * PYMUMBLE_SEQUENCE_DURATION

            newsound = SoundChunk(pcm, sequence, len(pcm), calculated_time, type, target)
            self.queue.appendleft(newsound)

            if len(self.queue) > 1 and self.queue[0].time < self.queue[1].time:
                # sort the audio chunk if it came out of order
                cpt = 0
                while cpt < len(self.queue) - 1 and self.queue[cpt].time < self.queue[cpt+1].time:
                    tmp = self.queue[cpt+1]
                    self.queue[cpt+1] = self.queue[cpt]
                    self.queue[cpt] = tmp

            self.lock.release()
            return newsound
        except KeyError:
            self.lock.release()
            self.mumble_object.Log.error("Codec not supported (audio packet type {0})".format(type))
        except Exception as e:
            self.lock.release()
            self.mumble_object.Log.error("error while decoding audio. sequence:{seq}, type:{type}. {error}".format(seq=sequence, type=type, error=str(e)))

    def is_sound(self):
        """Boolean to check if there is a sound frame in the queue"""
        if len(self.queue) > 0:
            return True
        else:
            return False
        
    def get_sound(self, duration=None):
        """Return the first sound of the queue and discard it"""
        self.lock.acquire()

        if len(self.queue) > 0:
            if duration is None or self.first_sound().duration <= duration:
                result = self.queue.pop() 
            else:
                result = self.first_sound().extract_sound(duration)
        else:
            result = None

        self.lock.release()
        return result
    
    def first_sound(self):
        """Return the first sound of the queue, but keep it"""
        if len(self.queue) > 0:
            return self.queue[-1]
        else:
            return None
        

class SoundChunk:
    """
    Object that contains the actual audio frame, in PCM format"""    
    def __init__(self, pcm, sequence, size, calculated_time, type, target, timestamp=time.time()):
        self.timestamp = timestamp  # measured time of arrival of the sound 
        self.time = calculated_time  # calculated time of arrival of the sound (based on sequence)
        self.pcm = pcm  # audio data
        self.sequence = sequence  # sequence of the packet
        self.size = size  # size
        self.duration = float(size) / 2 / PYMUMBLE_SAMPLERATE  # duration in sec
        self.type = type  # type of the audio (codec)
        self.target = target  # target of the audio
        
    def extract_sound(self, duration):
        """Extract part of the chunk, leaving a vilid chunk for the remaining part"""
        size = int(duration*2*PYMUMBLE_SAMPLERATE)
        result = SoundChunk(
                        self.pcm[:size],
                        self.sequence,
                        size,
                        self.time,
                        self.type,
                        self.target,
                        self.timestamp
                        )
        
        self.pcm = self.pcm[size:]
        self.duration -= duration
        self.time += duration
        self.size -= size
        
        return result
