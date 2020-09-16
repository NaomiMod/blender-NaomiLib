import bpy

from bpy.types import Operator
from bpy.props import FloatVectorProperty
from bpy_extras.object_utils import AddObjectHelper, object_data_add

import os
import sys
import struct

from io import BytesIO
from math import radians
from mathutils import Vector, Matrix

#############################
# original code
#############################

magic_naomilib = b'\x01\x00\x00\x00\x01\x00\x00\x00'

empty_size = 0.08

scale_x = 1
scale_y = 1
scale_z = 1

xVal = 0
yVal = 1    
zVal = 2

def parse_nl(nl_bytes: bytes) -> list:
    nlfile = BytesIO(nl_bytes)

    read_float_buff = lambda: struct.unpack("<f", nlfile.read(4))[0]
    read_uint32_buff = lambda: struct.unpack("<I", nlfile.read(4))[0]

    if nlfile.read(8) != magic_naomilib:
        raise TypeError("ERROR: This is not a NaomiLib file!")
        return {'CANCELLED'}        

    nlfile.seek(0x68)

    meshes = list()
    faces = list()
    numMeshes = 5 # this is always 5 (?)

    for n in range(numMeshes):
    
        nlfile.read(4) # unused
        n_total_vertex = read_uint32_buff()

        print(n_total_vertex)

        vertex = list()
        normal = list()
        texture_uv = list()
        
        tmp = list()
        for _ in range(n_total_vertex):
            vertex.append( Vector( struct.unpack("<fff", nlfile.read(12)) ) )
            normal.append( Vector( struct.unpack("<fff", nlfile.read(12)) ) )
            texture_uv.append( Vector( struct.unpack("<ff", nlfile.read(8)) ) )

        #print(vertex)
        #print(normal)
        #print(texture_uv)

        print("current position:", nlfile.tell())
        
        meshes.append( {
            'vertex': vertex,
            'normal': normal,
            'texture': texture_uv
        } )

        faces.append(list())
        for i in range(n_total_vertex-2):
            x = i

            if (i % 2 == 1):
                y = i + 1
                z = i + 2
            else:
                y = i + 2
                z = i + 1
            
            faces[n].append( [x, y, z] )

    #print(meshes[4]['vertex'][-1])

    ### structure
    # meshes[mesh_index][vertex|normal|texure][index][xVal|yVal|zVal]
    # faces[mesh_index][index][xVal|yVal|zVal]

    return meshes, faces


########################
# blender specific code
########################

def add_object(mesh_name: str, object_name: str, verts: list(), faces: list()):
    scale_x = 1
    scale_y = 1
    
    #verts = [
    #    Vector((-1 * scale_x, 1 * scale_y, 0)),
    #    Vector((1 * scale_x, 1 * scale_y, 0)),
    #    Vector((1 * scale_x, -1 * scale_y, 0)),
    #    Vector((-1 * scale_x, -1 * scale_y, 0)),
    #]
    #faces = [[0, 1, 2, 3]]
    edges = []


    mesh = bpy.data.meshes.new(name=mesh_name)
    mesh.from_pydata(verts, edges, faces)
    mesh.validate(verbose=True)


    new_object = bpy.data.objects.new(object_name, mesh)
    bpy.context.collection.objects.link(new_object)

def cleanup():
    for item in bpy.data.objects:
        bpy.data.objects.remove(item)

    for col in bpy.data.collections:
        bpy.data.collections.remove(col)
    
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)

def redraw():
    for area in bpy.context.screen.areas:
        if area.type in ['IMAGE_EDITOR', 'VIEW_3D']:
            area.tag_redraw()

### MAIN function
def main_function_import_file(self, filename: str):

    with open(filename, "rb") as f:
        NL = f.read(-1)

    print(filename)

    try:
        meshes, faces = parse_nl(NL)
    except TypeError as e:
        self.report({'ERROR'}, str(e))

    print("meshes", len(meshes))

    for i, mesh in enumerate(meshes):
        print("mesh", i, mesh['vertex'])
        print("uv", i, mesh['texture'])
        new_mesh = bpy.data.meshes.new(name=f"mesh_{i}")
        new_mesh.uv_layers.new(do_init=True)
        
        new_mesh.from_pydata(mesh['vertex'], list(), faces[i])
        new_mesh.validate(verbose=True)

        ### add UV coords
        for p, polygon in enumerate(new_mesh.polygons):
            for l, index in enumerate(polygon.loop_indices):
                #new_mesh.uv_layers[0].data[index].uv = Vector( (mesh['texture'][polygon.index][xVal], 1 - mesh['texture'][polygon.index][yVal]) )
                new_mesh.uv_layers[0].data[index].uv = Vector( (mesh['texture'][faces[i][p][l]][xVal], 1 - mesh['texture'][faces[i][p][l]][yVal]) )

        # this is nonsense
        #for j, uv in enumerate(mesh['texture']):
        #    print("uv", uv)
        #    new_mesh.uv_layers[0].data[j].uv = Vector( (uv[xVal], 1 - uv[yVal]) )

        # create object out of mesh
        new_object = bpy.data.objects.new(f"object_{i}", new_mesh)
        #print("new object", new_object.name)

        # link object to world collection
        bpy.context.collection.objects.link(new_object)

    return True
