#!/usr/bin/python3
# This bot reads standard input and converts them to speech via espeak and
# sends them to server(of course after converting the wave format to s32le)
# A blank line to exit.
import pymumble_py3
import subprocess as sp
try:
    import readline # optional
except ImportError:
    pass

server = "localhost"
nick = "Alice"
passwd = "All people are idiots. Many are standard ones but most of them are plain ones."


mumble = pymumble_py3.Mumble(server, nick, password=passwd)
mumble.start()
s = " "
while s:
    s = input(") ")
    command = ["espeak","--stdout", s]
    wave_file = sp.Popen(command, stdout=sp.PIPE).stdout
    command = ["ffmpeg", "-i", "-", "-ac", "1", "-f", "s32le","-"]
    sound = sp.Popen(command, stdout=sp.PIPE, stderr=sp.DEVNULL,
    stdin=wave_file).stdout.read()
    mumble.sound_output.add_sound(sound)

    
