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

magic_naomilib = [ 
    b'\x01\x00\x00\x00\x01\x00\x00\x00', 
    b'\x01\x00\x00\x00\x03\x00\x00\x00',
]

xVal = 0
yVal = 1
zVal = 2

def parse_nl(nl_bytes: bytes) -> (list, list, list):
    nlfile = BytesIO(nl_bytes)

    read_float_buff = lambda: struct.unpack("<f", nlfile.read(0x4))[0]
    read_uint32_buff = lambda: struct.unpack("<I", nlfile.read(0x4))[0]
    read_sint32_buff = lambda: struct.unpack("<i", nlfile.read(0x4))[0]

    if nlfile.read(0x8) not in magic_naomilib:
        raise TypeError("ERROR: This is not a NaomiLib file!")
        return {'CANCELLED'}        

    #nlfile.seek(0x68)
    nlfile.seek(0x64)
    mesh_end_offset = read_uint32_buff() + 0x64
    print("MESH END offset START:", mesh_end_offset)

    meshes = list()
    mesh_faces = list()

    m = 0
    # while not EOF
    while nlfile.read(0x4) != b'\x00\x00\x00\x00':

        if m > 0: # execute only after first loop
            print(nlfile.tell())
            nlfile.seek(0x4C-0x4, 0x1)
            print(nlfile.tell())
            m_length = read_uint32_buff()
            mesh_end_offset = m_length + nlfile.tell()
            print("MESH END offset m > 0:", mesh_end_offset)

        faces_vertex = list()
        faces_index = list()

        f = 0
        vertex_index_last = 0
        while nlfile.tell() < mesh_end_offset:
            mult = False

            if f > 0 or (f == 0 and m > 0): # execute this only after the first loop and during the first loop when m > 0
                face_type = nlfile.read(0x4) # some game internal value
                print(face_type)
                if face_type in [ b'\x6A\x00\x00\x00', b'\x69\x00\x00\x00' ]: # check for 6A and 69 types
                    mult = True
                else:
                    mult = False
            n_face = read_uint32_buff() # number of faces for this chunk (depending on the type it needs either one or three vertices / face)
            if mult:
                n_vertex = n_face * 3                
                print("triple number of vertices")
            else:
                n_vertex = n_face
            print(n_vertex)
            

            vertex = list()
            normal = list()
            texture_uv = list()
            
            for _ in range(n_vertex):
                # check if Type A or Type B vertex
                entry_pos = nlfile.tell()
                nlfile.seek(0x2, 0x1)
                if nlfile.read(0x2) == b'\xFF\x5F':
                    type_b = True
                    pointer_offset = read_sint32_buff()
                    entry_pos = nlfile.tell()
                    nlfile.seek(pointer_offset, 0x1)
                else:
                    type_b = False
                    nlfile.seek(entry_pos, 0x0)
            
                vertex.append( struct.unpack("<fff", nlfile.read(0xC)) )
                normal.append( struct.unpack("<fff", nlfile.read(0xC)) )
                texture_uv.append( struct.unpack("<ff", nlfile.read(0x8)) )

                if type_b: nlfile.seek(entry_pos, 0x0)

            #print(vertex)
            #print(normal)
            #print(texture_uv)

            print("current position:", nlfile.tell())
            
            faces_vertex.append( {
                'point': vertex,
                'normal': normal,
                'texture': texture_uv
            } )

            ## this idea doesn't work at all :(
            #faces_index.append( [*range(vertex_index_last, n_vertex_face+vertex_index_last)] )
            
            if mult:
                for j in range(n_face):
                    
                    x = vertex_index_last + j*3
                    y = vertex_index_last + j*3 + 1
                    z = vertex_index_last + j*3 + 2

                    faces_index.append( [x, y, z] )
            else:
                for j in range(n_vertex-2):
                    i = j + vertex_index_last
                    x = i
                
                    y = i + 1
                    z = i + 2

                    #if (i % 2 == 1):
                    #    y = i + 1
                    #    z = i + 2
                    #else:
                    #    y = i + 2
                    #    z = i + 1
                
                    faces_index.append( [x, y, z] )

            f += 1
            vertex_index_last += n_vertex

        #print(meshes[4]['vertex'][-1])
        print("number of faces found:", f)

        meshes.append( {
            'face_vertex': faces_vertex,
            'face_index': faces_index
        } )

        mesh_faces.append(faces_index)

        m += 1

    # reorganize vertices into one array
    mesh_vertices = list()
    mesh_uvs = list()
    for mesh in meshes:
        points = list()
        textures = list()

        for face in mesh['face_vertex']:
            for point in face['point']:
                # swap Y and Z axis
                points.append( Vector((point[xVal], point[zVal], point[yVal])) )
            for texture in face['texture']:
                textures.append( Vector(texture) )

        mesh_vertices.append(points)
        mesh_uvs.append(textures)

    
    print("number of meshes found:", m)
    #print(meshes[0]['face_vertex'][0]['point'][1])
    #print(mesh_vertices)
    print(faces_index)
    #print(mesh_uvs)


    #### data structure
    # meshes[index][face_vertex|face_index]
    # meshes[index][face_vertex][index][point|normal|texture][index][xVal|yVal|zVal]
    # meshes[index][face_index][index][vertex_selection]
    #
    # mesh_vertices[mesh_index][vertex_index][xVal|yVal|zVal]
    # mesh_uvs[mesh_index][uv_index][xVal|yVal]
    # mesh_faces[mesh_index][face_index][0|1|2]
    ####

    return mesh_vertices, mesh_uvs, mesh_faces, meshes


########################
# blender specific code
########################

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

    #try:
    mesh_vertex, mesh_uvs, faces, meshes = parse_nl(NL)
    #except TypeError as e:
    #    self.report({'ERROR'}, str(e))

    print("meshes", len(meshes))

    for i, mesh in enumerate(meshes):
        #print("mesh", i, mesh['vertex'])
        #print("uv", i, mesh['texture'])
        new_mesh = bpy.data.meshes.new(name=f"mesh_{i}")
        new_mesh.uv_layers.new(do_init=True) 
        
        #print("MESH:", mesh['face_vertex'])

        new_mesh.from_pydata(mesh_vertex[i], list(), faces[i])
        new_mesh.validate(verbose=True)

        #### add UV coords
        for p, polygon in enumerate(new_mesh.polygons):
            for l, index in enumerate(polygon.loop_indices):
                new_mesh.uv_layers[0].data[index].uv.x = mesh_uvs[i][ faces[i][p][l] ][xVal]
                new_mesh.uv_layers[0].data[index].uv.y = 1 - mesh_uvs[i][ faces[i][p][l] ][yVal]

        # create object out of mesh
        new_object = bpy.data.objects.new(f"object_{i}", new_mesh)

        #print("new object", new_object.name)

        # link object to world collection
        bpy.context.collection.objects.link(new_object)

    return True
