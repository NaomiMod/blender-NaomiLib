import bpy

from bpy.types import Operator
from bpy.props import FloatVectorProperty
from bpy_extras.object_utils import AddObjectHelper, object_data_add

import struct
import os

from io import BytesIO
from math import radians
from mathutils import Vector

# static magic numbers and headers

magic_naomilib = [ 
    b'\x01\x00\x00\x00\x01\x00\x00\x00', # Objects Model 1
    b'\x00\x00\x00\x00\x01\x00\x00\x00', # Objects Model 1 Used by DOA2
    b'\x01\x00\x00\x00\x02\x00\x00\x00', # Unknown Objects Model 2
    b'\x01\x00\x00\x00\x03\x00\x00\x00', # Objects Model 3 - Generally Levels
    b'\x01\x00\x00\x00\x05\x00\x00\x00', # Objects Model 5
    b'\x00\x00\x00\x00\x05\x00\x00\x00', # Objects Model 5 Type B - used by F355 Challenge
]

magic_naomilib_big = [
   	b'\x00\x00\x00\x01\x00\x00\x00\x01', # Objects Model 1 - used by Super Monkey Ball / GameCube
	b'\x00\x00\x00\x01\x00\x00\x00\x02', # Unknown Objects Model 2 - used by Super Monkey Ball / GameCube
	b'\x00\x00\x00\x01\x00\x00\x00\x03', # Objects Model 3 - used by Super Monkey Ball / GameCube
	b'\x00\x00\x00\x01\x00\x00\x00\x05', # Objects Model 5 - used by Super Monkey Ball / GameCube
	b'\x00\x00\x00\x00\x00\x00\x00\x05', # Objects Model 5 Type B - used by Super Monkey Ball / GameCube
	b'\x00\x00\x00\x00\x00\x00\x00\x01', # Objects Model 1 ?

]

triple_face_types_little = [    # special face types

    b'\x08\x00\x00\x00',        # 08
    b'\x09\x00\x00\x00',        # 09
    b'\x0A\x00\x00\x00',        # 0A
    b'\x18\x00\x00\x00',        # 18
    b'\x19\x00\x00\x00',        # 19
    b'\x1A\x00\x00\x00',        # 1A
    b'\x28\x00\x00\x00',        # 28
    b'\x29\x00\x00\x00',        # 29
    b'\x2A\x00\x00\x00',        # 2A
    b'\x38\x00\x00\x00',        # 38
    b'\x39\x00\x00\x00',        # 39
    b'\x3A\x00\x00\x00',        # 3A
    b'\x48\x00\x00\x00',        # 48
    b'\x49\x00\x00\x00',        # 49
    b'\x4A\x00\x00\x00',        # 4A
    b'\x58\x00\x00\x00',        # 58
    b'\x59\x00\x00\x00',        # 59
    b'\x5A\x00\x00\x00',        # 5A
    b'\x68\x00\x00\x00',        # 68
    b'\x69\x00\x00\x00',        # 69
    b'\x6A\x00\x00\x00',        # 6A
    b'\x78\x00\x00\x00',        # 78
    b'\x79\x00\x00\x00',        # 79
    b'\x7A\x00\x00\x00',        # 7A
    b'\x88\x00\x00\x00',        # 88
    b'\x89\x00\x00\x00',        # 89
    b'\x8A\x00\x00\x00',        # 8A
    b'\x98\x00\x00\x00',        # 98
    b'\x99\x00\x00\x00',        # 99
    b'\x9A\x00\x00\x00',        # 9A
    b'\xA8\x00\x00\x00',        # A8
    b'\xA9\x00\x00\x00',        # A9
    b'\xAA\x00\x00\x00',        # AA
    b'\xB8\x00\x00\x00',        # B8
    b'\xB9\x00\x00\x00',        # B9
    b'\xBA\x00\x00\x00',        # BA
    b'\xC8\x00\x00\x00',        # C8
    b'\xC9\x00\x00\x00',        # C9
    b'\xCA\x00\x00\x00',        # CA
    b'\xD8\x00\x00\x00',        # D8
    b'\xD9\x00\x00\x00',        # D9
    b'\xDA\x00\x00\x00',        # DA
    b'\xE8\x00\x00\x00',        # E8
    b'\xE9\x00\x00\x00',        # E9
    b'\xEA\x00\x00\x00',        # EA
    b'\xF8\x00\x00\x00',        # F8
    b'\xF9\x00\x00\x00',        # F9
    b'\xFA\x00\x00\x00',        # FA

    b'\x6A\x01\x00\x00',        # 6A 01
    b'\x69\x01\x00\x00',        # 69 01
    b'\x49\x01\x00\x00',        # 69 01
    b'\x0A\x01\x00\x00',        # 0A 01
    b'\x08\x01\x00\x00',        # 08 01
    b'\x09\x01\x00\x00',        # 09 01
    b'\x2A\x01\x00\x00',        # 2A 01
    b'\x29\x01\x00\x00',        # 29 01
    b'\x4A\x01\x00\x00',        # 4A 01
    b'\xEA\x01\x00\x00',        # EA 01
]

type_b_vertex_little = [
    b'\xFF\x5F',
    b'\xFE\x5F',
    b'\xFD\x5F',
    b'\xFC\x5F',
    b'\xFB\x5F',
    b'\xFA\x5F',
    b'\xF9\x5F',
    b'\xF8\x5F',
    b'\xF7\x5F',
    b'\xF6\x5F',
    b'\xF5\x5F',
    b'\xF4\x5F',
    b'\xF3\x5F',
    b'\xF2\x5F',
    b'\xF1\x5F',
    b'\xF0\x5F',
]

xVal = 0
yVal = 1
zVal = 2

#############################
# main parse function
#############################

def parse_nl(nl_bytes: bytes, debug=False) -> list:
    big_endian = False
    nlfile = BytesIO(nl_bytes)

    _magic = nlfile.read(0x8)
    if _magic in magic_naomilib_big:
        big_endian = True
    elif _magic not in magic_naomilib:
        raise TypeError("ERROR: This is not a supported NaomiLib file!")
        return {'CANCELLED'}

    if not big_endian:
        read_uint32_buff = lambda: struct.unpack("<I", nlfile.read(0x4))[0]
        read_sint32_buff = lambda: struct.unpack("<i", nlfile.read(0x4))[0]
        read_float_buff = lambda: struct.unpack("<f", nlfile.read(0x4))[0]

        read_point3_buff = lambda: struct.unpack("<fff", nlfile.read(0xC))
        read_point2_buff = lambda: struct.unpack("<ff", nlfile.read(0x8))

        # assign magics
        triple_face_types = triple_face_types_little
        type_b_vertex = type_b_vertex_little
    else:
        read_uint32_buff = lambda: struct.unpack(">I", nlfile.read(0x4))[0]
        read_sint32_buff = lambda: struct.unpack(">i", nlfile.read(0x4))[0]
        read_float_buff = lambda: struct.unpack(">f", nlfile.read(0x4))[0]

        read_point3_buff = lambda: struct.unpack(">fff", nlfile.read(0xC))
        read_point2_buff = lambda: struct.unpack(">ff", nlfile.read(0x8))

        # convert all magics to big endian
        triple_face_types = [ b[::-1] for b in triple_face_types_little ]
        type_b_vertex = [ b[::-1] for b in type_b_vertex_little ]
    

    meshes = list()
    mesh_faces = list()
    mesh_colors = list()

    #nlfile.seek(0x68)
    #nlfile.seek(0x64)
    nlfile.seek(0x48)

    # RGB color of the first mesh
    mesh_colors.append( (read_float_buff(), read_float_buff(), read_float_buff()) )

    # skip 0x10 unknown values
    nlfile.seek(0x10, 0x1)

    mesh_end_offset = read_uint32_buff() + 0x64
    if debug: print("MESH END offset START:", mesh_end_offset)

    m = 0
    # while not EOF
    while nlfile.read(0x4) != b'\x00\x00\x00\x00':

        if m == 0: # first loop needs special treatment
            nlfile.seek(nlfile.tell()-0x4, 0x0)
        else:
            if debug: print(nlfile.tell())

            # read RGB color
            nlfile.seek(0x4C-0x20, 0x1)
            mesh_colors.append( (read_float_buff(), read_float_buff(), read_float_buff()) )
            nlfile.seek(0x10, 0x1)
            #nlfile.seek(0x4C-0x4, 0x1)

            if debug: print(nlfile.tell())

            mesh_end_offset = read_uint32_buff() + nlfile.tell()

            if debug: print("MESH END offset m > 0:", mesh_end_offset)

        faces_vertex = list()
        faces_index = list()

        f = 0
        vertex_index_last = 0
        while nlfile.tell() < mesh_end_offset:
            mult = False

            face_type = nlfile.read(0x4) # some game internal value
            if debug: print(face_type)
            if face_type in triple_face_types: # check for triple vertex faces
                mult = True
            else:
                mult = False

            n_face = read_uint32_buff() # number of faces for this chunk (depending on the type it needs either one or three vertices / face)
            if mult:
                n_vertex = n_face * 3                
                if debug: print("triple number of vertices")
            else:
                n_vertex = n_face
            if debug: print(n_vertex)
            

            vertex = list()
            normal = list()
            texture_uv = list()
            
            for _ in range(n_vertex):
                # check if Type A or Type B vertex
                entry_pos = nlfile.tell()
                if not big_endian: nlfile.seek(0x2, 0x1)
                if nlfile.read(0x2) in type_b_vertex:
                    type_b = True
                    if big_endian: nlfile.seek(0x2, 0x1)
                    pointer_offset = read_sint32_buff()
                    entry_pos = nlfile.tell()
                    nlfile.seek(pointer_offset, 0x1)
                else:
                    type_b = False
                    nlfile.seek(entry_pos, 0x0)
            
                vertex.append( read_point3_buff() )
                normal.append( read_point3_buff() )
                texture_uv.append( read_point2_buff() )

                if type_b: nlfile.seek(entry_pos, 0x0)

            #print(vertex)
            #print(normal)
            #print(texture_uv)

            if debug: print("current position:", nlfile.tell())
            
            faces_vertex.append( {
                'point': vertex,
                'normal': normal,
                'texture': texture_uv
            } )
            
            if mult:
                for j in range(n_face):
                    i = vertex_index_last + j*3

                    x = i
                    y = i + 1
                    z = i + 2

                    faces_index.append( [x, y, z] )
            else:
                for j in range(n_vertex-2):
                    i = vertex_index_last + j

                    x = i
                    y = i + 1
                    z = i + 2
                
                    faces_index.append( [x, y, z] )

            f += 1
            vertex_index_last += n_vertex

            if debug: print("-----")

        #print(meshes[4]['vertex'][-1])
        if debug: print("number of faces found:", f)

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

    
    if debug: print("number of meshes found:", m)
    #print(meshes[0]['face_vertex'][0]['point'][1])
    #print(mesh_vertices)
    if debug: print(faces_index)
    #print(mesh_uvs)
    #print(mesh_colors)

    #### data structure
    # meshes[index][face_vertex|face_index]
    # meshes[index][face_vertex][index][point|normal|texture][index][xVal|yVal|zVal]
    # meshes[index][face_index][index][vertex_selection]
    #
    # mesh_vertices[mesh_index][vertex_index][xVal|yVal|zVal]
    # mesh_uvs[mesh_index][uv_index][xVal|yVal]
    # mesh_faces[mesh_index][face_index][0|1|2]
    ####

    return mesh_vertices, mesh_uvs, mesh_faces, meshes, mesh_colors


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

def data2blender(mesh_vertex: list, mesh_uvs: list, faces: list, meshes: list, meshColors: list, parent_col: bpy.types.Collection, scale: float, debug=False):
    if debug: print("meshes:", len(meshes))

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
        new_object.scale = [scale]*3

        #print("new object", new_object.name)

        # add viewport color to object
        new_mat = bpy.data.materials.new(f"object_{i}_mat")
        new_mat.diffuse_color = meshColors[i] + (1,)
        new_mat.roughness = 1
        new_mat.metallic = 0.5

        new_object.data.materials.append(new_mat)

        # link object to parent collection
        parent_col.objects.link(new_object)
        #bpy.context.collection.objects.link(new_object)

    return True

########################
# MAIN functions
########################

def main_function_import_file(self, filepath: str, scaling: float, debug: bool):

    with open(filepath, "rb") as f:
        NL = f.read(-1)

    print(filepath)
    filename = filepath.split(os.sep)[-1]
    print(filename)

    mesh_vertex, mesh_uvs, faces, meshes, mesh_colors = parse_nl(NL, debug=debug)

    # create own collection for each imported file
    obj_col = bpy.data.collections.new(filename)
    bpy.context.scene.collection.children.link(obj_col)

    return data2blender(mesh_vertex, mesh_uvs, faces, meshes, meshColors=mesh_colors, parent_col=obj_col, scale=scaling, debug=debug)


def main_function_import_archive(self, filepath: str, scaling: float, debug: bool):
    filename = filepath.split(os.sep)[-1]

    # create own collection for each imported file
    obj_col = bpy.data.collections.new(filename)
    bpy.context.scene.collection.children.link(obj_col)

    with open(filepath, "rb") as f:
        read_uint32_buff = lambda: struct.unpack("<I", f.read(0x4))[0]
        read_uint16_buff = lambda: struct.unpack("<H", f.read(0x2))[0]

        # check for little or big endian
        t1 = f.read(0x2)
        t2 = read_uint16_buff()
        f.seek(0x0)
        if t1 == b'\x00\x00' and t2 > 1000:
            read_uint32_buff = lambda: struct.unpack(">I", f.read(0x4))[0]

        header_length = read_uint32_buff()
        num_child_models = ( header_length - 0x8 ) // 0x4

        start_offset = read_uint32_buff()

        for i in range(num_child_models):
            end_offset = read_uint32_buff()
            st_p = f.tell()

            if end_offset == 0:
                f.seek( header_length + 0x8 ) # this is not always true, for some models the offset is only 0x4 (**)
                end_offset = read_uint32_buff()
                if end_offset < start_offset: # (**)so we need to check for that
                    f.seek ( header_length + 0x4 ) # (**)and apply a dirty solution, I mean who the fuck cares anyway
                    end_offset = read_uint32_buff()

            f.seek(start_offset)
            if debug: print("NEW child start offset:", start_offset)
            if debug: print("NEW child end offset:", end_offset)
            mesh_vertex, mesh_uvs, faces, meshes, mesh_colors = parse_nl( f.read(end_offset-start_offset), debug=debug )

            sub_col = bpy.data.collections.new(f"child_{i}")
            obj_col.children.link(sub_col)

            if not data2blender(mesh_vertex, mesh_uvs, faces, meshes, meshColors=mesh_colors, parent_col=sub_col, scale=scaling, debug=debug): return False
            f.seek(st_p)
            start_offset = end_offset


    if debug: print("NUMBER OF CHILDREN:", num_child_models)

    return True
