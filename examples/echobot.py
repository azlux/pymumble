#!/usr/bin/python3
# This bot sends any sound it receives back to where it has come from.
# WARNING! Don't put two bots in the same place!

import pymumble_py3
import time
from pymumble_py3.callbacks import PYMUMBLE_CLBK_SOUNDRECEIVED as PCS

pwd =""
server = "localhost"
nick = "Bob"

def sound_received_handler(user, soundchunk):
    mumble.sound_output.add_sound(soundchunk.pcm)

mumble = pymumble_py3.Mumble(server, nick, password=pwd)
mumble.callbacks.set_callback(PCS, sound_received_handler)
mumble.set_receive_sound(1)
mumble.start()

while 1:
    time.sleep(1)
