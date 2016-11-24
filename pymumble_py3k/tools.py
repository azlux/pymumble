# -*- coding: utf-8 -*-
import struct
import builtins


class InvalidVarInt(Exception):
    pass


class VarInt:
    """Implement the varint type used in mumble"""
    def __init__(self, value=0):
        self.value = value
        
    def encode(self):
        """Encode an integer in the VarInt format, returning a binary string"""
        result = bytearray()
        value = abs(self.value)
        
        
        if self.value < 0:
            if self.value >= -3:
                return struct.pack("!B", (0b11111100 | value))
            else:
                result = struct.pack("!B", 0b11111000)
            
        if value <= 0x7f:
            return result + struct.pack("!B",  value)
        elif value <= 0x3fff:
            return result + struct.pack("!H", 0x8000 | value)
        elif value <= 0x1fffff:
            return result + struct.pack("!BH", 0xc0 | (value >> 16), 0xffff & value)
        elif value <= 0xfffffff:
            return result + struct.pack("!L", 0xe0000000 | value)
        elif value <= 0xffffffff:
            return result + struct.pack("!BL", 0b11110000, value)
        else:
            return result + struct.pack("!BQ", 0b11110100, value)

    def decode(self, value):
        """Decode a VarInt contained in a binary string, returning an integer"""
        varint = value
        is_negative = False
        result = None
        size = 0
        
        if len(varint) <= 0:
            raise InvalidVarInt("length can't be 0")
        
        (first, ) = struct.unpack("!B", varint[0:1])
        
        if first & 0b11111100 == 0b11111000:
            is_negative = True
            size += 1
            if len(varint) < 2:
                raise InvalidVarInt("Too short negative varint")
            varint = varint[1:]
            (first, ) = struct.unpack("!B", varint[0:1])

        if first & 0b10000000 == 0b00000000:
            (result, ) = struct.unpack("!B", varint[0:1])
            size += 1
        elif first & 0b11111100 == 0b11111100:
            (result, ) = struct.unpack("!B", varint[0:1])
            result &= 0b00000011
            is_negative = True
            size += 1
        elif first & 0b11000000 == 0b10000000:
            if len(varint) < 2:
                raise InvalidVarInt("Too short 2 bytes varint")
            (result, ) = struct.unpack("!H", varint[:2])
            result &= 0b0011111111111111
            size += 2
        elif first & 0b11100000 == 0b11000000:
            if len(varint) < 3:
                raise InvalidVarInt("Too short 3 bytes varint")
            (result, ) = struct.unpack("!B", varint[0:1])
            result &= 0b00011111
            (tmp, ) = struct.unpack("!H", varint[1:3])
            result = (result << 16) + tmp
            size += 3
        elif first & 0b11110000 == 0b11100000:
            if len(varint) < 4:
                raise InvalidVarInt("Too short 4 bytes varint")
            (result, ) = struct.unpack("!L", varint[:4])
            result &= 0x0fffffff
            size += 4
        elif first & 0b11111100 == 0b11110000:
            if len(varint) < 5:
                raise InvalidVarInt("Too short 5 bytes varint")
            (result, ) = struct.unpack("!L", varint[1:5])
            size += 5
        elif first & 0b11111100 == 0b11110100:
            if len(varint) < 9:
                raise InvalidVarInt("Too short 9 bytes varint")
            (result, ) = struct.unpack("!Q", varint[1:9])
            size += 9

        if is_negative:
            self.value = - result
        else:
            self.value = result
            
        return size


def tohex(buffer):
    """Used for debugging.  Output a sting in hex format"""
    result = "\n"
    cpt1 = 0
    cpt2 = 0
    
    for byte in buffer:
        result += hex(ord(byte))[2:].zfill(2)
        cpt1 += 1
        
        if cpt1 >= 4:
            result += " "
            cpt1 = 0
            cpt2 += 1
                        
        if cpt2 >= 10:
            result += "\n"
            cpt2 = 0
    
    return result
        



