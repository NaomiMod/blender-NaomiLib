#! /usr/bin/env python3

"""
Created 16.09.2020 18:34 CEST

@author zocker_160
@comment script for analysing NaomiLib 3D files

this is an implementation of the NaomiLib documentation created by Vincent
without that, this implementation would be impossible, all credits go to him
"""

import os
import sys
import struct

from io import BytesIO

file = "../docs/foot.bin"

magic_naomilib = b'\x01\x00\x00\x00\x01\x00\x00\x00'


with open(file, "rb") as nlfile:
    read_float_buff = lambda: struct.unpack("<f", nlfile.read(4))[0]
    read_uint32_buff = lambda: struct.unpack("<I", nlfile.read(4))[0]

    if nlfile.read(8) != magic_naomilib:
        print("ERROR: This is not a NaomiLib file!")
        sys.exit()

    nlfile.seek(0x68)

    meshes = list()
    numChunks = 5 # this is always 5 (?)

    for _ in range(numChunks):
    
        nlfile.read(4) # unused
        n_total_vertex = read_uint32_buff()

        print(n_total_vertex)

        vertex = list()
        normal = list()
        texture_uv = list()
        
        tmp = list()
        for _ in range(n_total_vertex):
            vertex.append( struct.unpack("<fff", nlfile.read(12)) )
            normal.append( struct.unpack("<fff", nlfile.read(12)) )
            texture_uv.append( struct.unpack("<ff", nlfile.read(8)) )

        print(vertex)
        print(normal)
        print(texture_uv)

        print("current position:", nlfile.tell())

        meshes.append( [vertex, normal, texture_uv] )

    