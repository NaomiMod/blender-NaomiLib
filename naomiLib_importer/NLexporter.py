import bpy
from bpy.types import Operator
from bpy.props import FloatVectorProperty
from bpy_extras.object_utils import AddObjectHelper, object_data_add
import struct
import os
from io import BytesIO
from math import radians
from mathutils import Vector

xVal = 0
yVal = 1
zVal = 2

import bpy
import struct


def write_naomi_bin(filepath, obj):
    """Selected mesh PLACEHOLDER!"""
    if not obj or obj.type != 'MESH':
        raise ValueError("Selected object is not a mesh.")

    mesh = obj.data
    vertices = mesh.vertices
    faces = mesh.polygons

    with open(filepath, 'wb') as f:
        # placeholder header
        f.write(b'\x01\x00\x00\x00\x01\x00\x00\x00')


        # vertex data
        for vertex in vertices:
            f.write(struct.pack('<fff', vertex.co.x, vertex.co.y, vertex.co.z))


        # footer
        f.write (b'\x00'*4 + struct.pack('<I', len(vertices)))

    print(f"Successfully exported mesh '{obj.name}' to {filepath}")


