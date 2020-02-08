#!/usr/bin/python3
# This bot sends any sound it receives back to where it has come from.
# WARNING! Don't put two bots in the same place!

import time
import typing

import pymumble_py3
from pymumble_py3.constants import PYMUMBLE_CLBK_SOUNDRECEIVED as PCS

if typing.TYPE_CHECKING:
    from pymumble.pymumble_py3.users import User
    from pymumble.pymumble_py3.soundqueue import SoundChunk

pwd = ""  # password
server = "localhost"
nick = "Bob"


def sound_received_handler(user: "User", soundchunk: "SoundChunk") -> None:
    # sending the received sound back to server
    mumble.sound_output.add_sound(soundchunk.pcm)


mumble = pymumble_py3.Mumble(server, nick, password=pwd)
mumble.callbacks.set_callback(PCS, sound_received_handler)
mumble.set_receive_sound(True)  # we want to receive sound
mumble.start()

while 1:
    time.sleep(1)
