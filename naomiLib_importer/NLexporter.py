import bpy
from bpy.types import Operator
from bpy.props import FloatVectorProperty
from bpy_extras.object_utils import AddObjectHelper, object_data_add
import struct
import os
from io import BytesIO
from mathutils import Vector
import zlib
import bmesh
import numpy as np

xVal = 0
yVal = 1
zVal = 2


# -------------------------
# Common functions
# -------------------------

def calculate_crc32(filepath):
    crc = 0
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            crc = zlib.crc32(chunk, crc)
    return f"{crc & 0xffffffff:08x}"


def reverse_axis_transformation(vertex, orientation, neg_scale_x):
    x, y, z = vertex

    if orientation == 'X_UP':
        x, y, z = y, x, z
    elif orientation == 'Y_UP':
        pass
    elif orientation == 'Z_UP':
        x, y, z = x, z, y

    if neg_scale_x:
        x *= -1.0

    return (x, y, z)


# -------------------------
# Material parameter comparison
# -------------------------

def get_material_parameters(obj):
    p = obj.naomi_param
    return {
        'paramType': p.paramType,
        'endOfStrip': p.endOfStrip,
        'listType': p.listType,
        'grpEn': p.grpEn,
        'stripLen': p.stripLen,
        'usrClip': p.usrClip,
        'shadow': p.shadow,
        'volume': p.volume,
        'textureUsage': p.textureUsage,
        'offsColorUsage': p.offsColorUsage,
        'gouraudShdUsage': p.gouraudShdUsage,
        'uvDataSize': p.uvDataSize,
        'mh_texID': p.mh_texID,
        'm_tex_shading': p.m_tex_shading,
        'm_ambient_light': p.m_ambient_light,
        'meshColor': tuple(p.meshColor),
        'meshOffsetColor': tuple(p.meshOffsetColor)
    }


def parameters_match(params1, params2, ambient_tolerance=1e-6):
    if len(params1) != len(params2):
        return False

    for key, val1 in params1.items():
        val2 = params2.get(key)
        if val2 is None:
            return False

        # Special handling for ambient light only
        if key == 'm_ambient_light':
            if abs(val1 - val2) > ambient_tolerance:
                return False
        else:
            # Exact comparison for everything else
            if val1 != val2:
                return False

    return True


def adjust_color_type_intensity(mesh_objects):
    if not mesh_objects:
        return

    previous_params = None

    for i, obj in enumerate(mesh_objects):
        if obj.naomi_param.colType not in ['2', '3']:
            continue

        current_params = get_material_parameters(obj)

        # Intensity 1 if no previous or different params
        if obj.naomi_param.colType == '3' and (
                not previous_params or not parameters_match(current_params, previous_params)):
            obj.naomi_param.colType = '2'

        # If it's Intensity 1, set matching consecutive meshes to Intensity 2
        if obj.naomi_param.colType == '2':
            for j in range(i + 1, len(mesh_objects)):
                next_obj = mesh_objects[j]
                if next_obj.naomi_param.colType not in ['2', '3']:
                    break
                if parameters_match(current_params, get_material_parameters(next_obj)):
                    next_obj.naomi_param.colType = '3'
                else:
                    break
            previous_params = current_params


# -------------------------
# Binary writes
# -------------------------

def write_float_at(file_data, offset, value):
    struct.pack_into("<f", file_data, offset, value)


def write_float_x_aligned(file_data, offset, value):
    struct.pack_into('<I', file_data, offset,
                     struct.unpack('<I', struct.pack('<f', value))[0] | 1)


def write_uint32_at(file_data, offset, value):
    struct.pack_into("<I", file_data, offset, value)


def write_sint32_at(file_data, offset, value):
    struct.pack_into("<i", file_data, offset, value)


def write_uint8_at(file_data, offset, value):
    struct.pack_into("<B", file_data, offset, value)


# -------------------------
# Vertex color extraction
# -------------------------

def get_vertex_colors(obj):
    original_mode = bpy.context.object.mode if bpy.context.object else 'OBJECT'
    was_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = obj
    vertex_colors_data = {}

    try:
        if original_mode == 'EDIT' and obj == bpy.context.view_layer.objects.active:
            bm = bmesh.from_edit_mesh(obj.data)
            if obj.data.vertex_colors.active:
                color_layer_name = obj.data.vertex_colors.active.name
                if color_layer_name in bm.loops.layers.color:
                    color_layer = bm.loops.layers.color[color_layer_name]
                    for face in bm.faces:
                        for loop in face.loops:
                            vertex_index = loop.vert.index
                            color = loop[color_layer]
                            vertex_colors_data[vertex_index] = (
                                color[0], color[1], color[2], color[3]
                            )
        else:
            if obj.data.vertex_colors.active:
                vertex_colors = obj.data.vertex_colors.active
                for loop in obj.data.loops:
                    vertex_index = loop.vertex_index
                    color = vertex_colors.data[loop.index].color
                    vertex_colors_data[vertex_index] = (
                        color[0], color[1], color[2], color[3]
                    )
    finally:
        bpy.context.view_layer.objects.active = was_active

    return vertex_colors_data


# -------------------------
# UV coordinate extraction
# -------------------------

def get_vertex_uvs(obj):
    # extract UV coordinates for each vertex from the active UV map
    original_mode = bpy.context.object.mode if bpy.context.object else 'OBJECT'
    was_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = obj
    vertex_uv_data = {}

    try:
        if original_mode == 'EDIT' and obj == bpy.context.view_layer.objects.active:
            bm = bmesh.from_edit_mesh(obj.data)
            if bm.loops.layers.uv.active:
                uv_layer = bm.loops.layers.uv.active
                for face in bm.faces:
                    for loop in face.loops:
                        vertex_index = loop.vert.index
                        if vertex_index not in vertex_uv_data:
                            uv = loop[uv_layer]
                            # Keep U as is, flip V coordinate (1.0 - V)
                            vertex_uv_data[vertex_index] = (uv.uv[0], 1.0 - uv.uv[1])
        else:
            if obj.data.uv_layers.active:
                uv_layer = obj.data.uv_layers.active
                for loop in obj.data.loops:
                    vertex_index = loop.vertex_index
                    if vertex_index not in vertex_uv_data:
                        uv = uv_layer.data[loop.index].uv
                        # Keep U as is, flip V coordinate (1.0 - V)
                        vertex_uv_data[vertex_index] = (uv[0], 1.0 - uv[1])
    finally:
        bpy.context.view_layer.objects.active = was_active

    return vertex_uv_data


# ------------
# Mesh update
# ------------

def mesh_data_update(collection):
    original_active = bpy.context.view_layer.objects.active
    original_selected = bpy.context.selected_objects.copy()
    original_mode = bpy.context.object.mode if bpy.context.object else 'OBJECT'

    mesh_objects = [obj for obj in collection.objects if obj.type == 'MESH']

    try:
        for obj in bpy.context.selected_objects:
            obj.select_set(False)

        for obj in mesh_objects:
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            was_in_edit_mode = bpy.context.object.mode == 'EDIT'

            if was_in_edit_mode:
                bpy.ops.object.editmode_toggle()
            elif bpy.context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

            mesh = obj.data
            mesh.update()
            bpy.context.view_layer.update()

            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

            mesh.update()
            mesh.calc_loop_triangles()

            if hasattr(obj.naomi_param, "m_tex_shading") and obj.naomi_param.m_tex_shading == -3:
                if mesh.vertex_colors:
                    vertex_colors = mesh.vertex_colors.active
                    vertex_to_loop_map = {loop.vertex_index: loop.index for loop in mesh.loops}
                    for loop_idx in vertex_to_loop_map.values():
                        if loop_idx < len(vertex_colors.data):
                            color = vertex_colors.data[loop_idx].color
                            vertex_colors.data[loop_idx].color = color

            mesh.update()
            obj.select_set(False)

        bpy.context.view_layer.update()

    finally:
        for obj in bpy.context.selected_objects:
            obj.select_set(False)
        for obj in original_selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = original_active

        if original_active and original_mode == 'EDIT':
            try:
                bpy.context.view_layer.objects.active = original_active
                bpy.ops.object.editmode_toggle()
            except:
                pass
        elif original_active and original_mode != 'OBJECT':
            try:
                bpy.context.view_layer.objects.active = original_active
                bpy.ops.object.mode_set(mode=original_mode)
            except:
                pass


def recalc_centroids(collection, recalc_individual=True, recalc_collection=True):
    # recalculate per-mesh and collection centroids/radii

    ctx = bpy.context
    orig_active = ctx.view_layer.objects.active
    orig_selected = ctx.selected_objects.copy()
    orig_mode = ctx.object.mode if ctx.object else 'OBJECT'

    mesh_objects = [o for o in collection.objects if o.type == 'MESH' and o.data.vertices]
    # print(f"Centroid calculation for '{collection.name}' with {len(mesh_objects)} meshes...")

    coll_vertices = []

    try:
        for o in ctx.selected_objects:
            o.select_set(False)

        for obj in mesh_objects:
            obj.select_set(True)
            ctx.view_layer.objects.active = obj

            if ctx.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

            mesh = obj.data
            mesh.update()
            mesh.calc_loop_triangles()

            verts = np.array([v.co[:] for v in mesh.vertices], dtype=np.float32)
            if not verts.size:
                obj.select_set(False)
                continue

            # per-object centroid
            if recalc_individual:
                minc, maxc = np.min(verts, 0), np.max(verts, 0)
                centroid = (minc + maxc) / 2
                radius = float(np.sqrt(((verts - centroid) ** 2).sum(1).max()))
                if hasattr(obj, "naomi_param"):
                    obj.naomi_param.centroid_x, obj.naomi_param.centroid_y, obj.naomi_param.centroid_z = map(float,
                                                                                                             centroid)
                    obj.naomi_param.bound_radius = radius
                    print(f"Updated '{obj.name}': centroid=({centroid[0]:.6f},{centroid[1]:.6f},{centroid[2]:.6f}), r={radius:.6f}")
                else:
                    print(f"Warning: {obj.name} has no naomi_param")

            # prepare for collection calc
            if recalc_collection and hasattr(obj, "naomi_param"):
                coll_vertices.append(verts)

            obj.select_set(False)

        # collection centroid
        if recalc_collection:
            if not coll_vertices:
                if hasattr(collection, "naomi_centroidData"):
                    collection.naomi_centroidData.centroid_x = \
                        collection.naomi_centroidData.centroid_y = \
                        collection.naomi_centroidData.centroid_z = 0.0
                    collection.naomi_centroidData.collection_bound_radius = 0.0
                print("No valid vertices for collection centroid.")
            else:
                allv = np.vstack(coll_vertices).astype(np.float32)
                minc, maxc = np.min(allv, 0), np.max(allv, 0)
                centroid = (minc + maxc) / 2
                radius = float(np.sqrt(((allv - centroid) ** 2).sum(1).max()))
                if hasattr(collection, "naomi_centroidData"):
                    collection.naomi_centroidData.centroid_x, collection.naomi_centroidData.centroid_y, collection.naomi_centroidData.centroid_z = map(
                        float, centroid)
                    collection.naomi_centroidData.collection_bound_radius = radius
                    print(f"Updated collection '{collection.name}': centroid=({centroid[0]:.6f},{centroid[1]:.6f},{centroid[2]:.6f}), r={radius:.6f}")

    finally:
        for o in ctx.selected_objects: o.select_set(False)
        for o in orig_selected: o.select_set(True)
        ctx.view_layer.objects.active = orig_active
        if orig_active and orig_mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode=orig_mode)
            except:
                pass


# ---------------------------
# NL file update (NO REMESH!)
# ---------------------------

def update_naomi_bin(filepath, collection, update_centroids=False):
    if not collection.naomi_import_meta.source_filepath:
        raise ValueError("No import metadata found. Collection was not imported from NaomiLib file.")

    original_filename = os.path.basename(collection.naomi_import_meta.source_filepath)
    target_filename = os.path.basename(filepath)
    if original_filename != target_filename:
        raise ValueError(f"Filename mismatch: {original_filename} vs {target_filename}")

    if os.path.exists(filepath):
        target_crc32 = calculate_crc32(filepath)
        if target_crc32 != collection.naomi_import_meta.source_crc32:
            raise ValueError(
                f"CRC32 mismatch: expected {collection.naomi_import_meta.source_crc32}, got {target_crc32}"
            )

    with open(filepath, 'rb') as f:
        file_data = bytearray(f.read())

    orientation = collection.naomi_import_meta.import_orientation
    neg_scale_x = collection.naomi_import_meta.import_neg_scale_x

    mesh_data_update(collection)
    bpy.context.view_layer.update()

    if update_centroids:
        recalc_centroids(collection)

    mesh_objects = [obj for obj in collection.objects if obj.type == 'MESH']
    adjust_color_type_intensity(mesh_objects)

    # -----------------------------
    # Write GP0/GP1 and centroid info
    # -----------------------------
    gp0 = collection.gp0
    gp1 = collection.gp1
    file_data[0x0] = 0x00 if gp0.objFormat == '0' else 0x01

    gflag1 = 0x0001
    if gp1.skp1stSrcOp: gflag1 |= (1 << 1)
    if gp1.envMap: gflag1 |= (1 << 2)
    if gp1.pltTex: gflag1 |= (1 << 3)
    if gp1.bumpMap: gflag1 |= (1 << 4)
    file_data[0x4:0x6] = struct.pack('<H', gflag1)

    # write updated collection centroid & radius
    centroid = (
        collection.naomi_centroidData.centroid_x,
        collection.naomi_centroidData.centroid_y,
        collection.naomi_centroidData.centroid_z
    )
    rev_centroid = reverse_axis_transformation(centroid, orientation, neg_scale_x)
    write_float_at(file_data, 0x8, rev_centroid[0])
    write_float_at(file_data, 0xC, rev_centroid[1])
    write_float_at(file_data, 0x10, rev_centroid[2])
    write_float_at(file_data, 0x14, collection.naomi_centroidData.collection_bound_radius)

    current_pos = 0x18
    mesh_index = 0

    while mesh_index < len(mesh_objects) and current_pos < len(file_data) - 4:
        if struct.unpack_from("<I", file_data, current_pos)[0] == 0:
            break

        current_obj = mesh_objects[mesh_index]
        current_mesh = current_obj.data
        p = current_obj.naomi_param

        new_params = (
                (int(p.paramType) << 29) | (int(p.endOfStrip) << 28) | (int(p.listType) << 24) |
                (int(p.grpEn) << 23) | (int(p.stripLen) << 18) | (int(p.usrClip) << 16) |
                (int(p.shadow) << 7) | (int(p.volume) << 6) | (int(p.colType) << 4) |
                (int(p.textureUsage) << 3) | (int(p.offsColorUsage) << 2) |
                (int(p.gouraudShdUsage) << 1) | int(p.uvDataSize)
        )
        write_uint32_at(file_data, current_pos, new_params)
        current_pos += 16

        mesh_centroid = (p.centroid_x, p.centroid_y, p.centroid_z)
        rev_mesh_centroid = reverse_axis_transformation(mesh_centroid, orientation, neg_scale_x)
        write_float_at(file_data, current_pos, rev_mesh_centroid[0])
        write_float_at(file_data, current_pos + 4, rev_mesh_centroid[1])
        write_float_at(file_data, current_pos + 8, rev_mesh_centroid[2])
        write_float_at(file_data, current_pos + 12, p.bound_radius)
        current_pos += 16

        write_sint32_at(file_data, current_pos, p.mh_texID)
        current_pos += 4
        write_sint32_at(file_data, current_pos, p.m_tex_shading)
        current_pos += 4
        write_float_at(file_data, current_pos, p.m_ambient_light)
        current_pos += 4

        bc = p.meshColor

        # print(current_obj, 'Mesh_color', hex(current_pos), bc[3], bc[0], bc[1], bc[2])
        write_float_at(file_data, current_pos, bc[3])
        write_float_at(file_data, current_pos + 4, bc[0])
        write_float_at(file_data, current_pos + 8, bc[1])
        write_float_at(file_data, current_pos + 12, bc[2])
        current_pos += 16

        oc = p.meshOffsetColor
        write_float_at(file_data, current_pos, oc[3])
        write_float_at(file_data, current_pos + 4, oc[0])
        write_float_at(file_data, current_pos + 8, oc[1])
        write_float_at(file_data, current_pos + 12, oc[2])
        current_pos += 16

        mesh_data_size = struct.unpack_from("<I", file_data, current_pos)[0]
        current_pos += 4
        mesh_end = current_pos + mesh_data_size

        vertex_positions = [v.co for v in current_mesh.vertices]
        vertex_index = 0

        # get vertex colors and UV data
        vertex_colors_data = {}
        vertex_uv_data = {}

        if hasattr(current_obj.naomi_param, "m_tex_shading") and current_obj.naomi_param.m_tex_shading == -3:
            vertex_colors_data = get_vertex_colors(current_obj)

        vertex_uv_data = get_vertex_uvs(current_obj)

        while current_pos < mesh_end and current_pos < len(file_data) - 8:
            face_type = struct.unpack_from("<I", file_data, current_pos)[0]
            current_pos += 4
            is_triangles = (face_type >> 3) & 1
            n_faces = struct.unpack_from("<I", file_data, current_pos)[0]
            current_pos += 4
            n_vertices = n_faces * 3 if is_triangles else n_faces

            for _ in range(n_vertices):
                if current_pos >= mesh_end:
                    break

                vertex_value = struct.unpack_from("<I", file_data, current_pos)[0]

                # skip Type B
                if 0x5FF00000 <= vertex_value <= 0x5FFFFFFF:
                    current_pos += 8
                else:
                    if vertex_index < len(vertex_positions):
                        co = vertex_positions[vertex_index]
                        rev_pos = reverse_axis_transformation(co, orientation, neg_scale_x)

                        # write position data
                        write_float_x_aligned(file_data, current_pos, rev_pos[0])
                        write_float_at(file_data, current_pos + 4, rev_pos[1])
                        write_float_at(file_data, current_pos + 8, rev_pos[2])
                        current_pos += 12

                        # vertex types based on m_tex_shading
                        tex_shading = getattr(current_obj.naomi_param, 'm_tex_shading', 0)

                        if tex_shading == -3:  # Type C
                            # skip normal data (3 bytes + 1 padding byte)
                            current_pos += 4

                            # write vertex colors
                            if vertex_colors_data and vertex_index in vertex_colors_data:
                                color_data = vertex_colors_data[vertex_index]
                                b = int(max(0, min(255, color_data[2] * 255)))
                                g = int(max(0, min(255, color_data[1] * 255)))
                                r = int(max(0, min(255, color_data[0] * 255)))
                                a = int(max(0, min(255, color_data[3] * 255)))
                                for i, val in enumerate([b, g, r, a, b, g, r, a]):
                                    write_uint8_at(file_data, current_pos + i, val)
                            current_pos += 8

                            # write UV data - check for texture ID
                            if p.mh_texID == -1:
                                # dummy values: U=0 (as uint), V=1 (as uint)
                                write_uint32_at(file_data, current_pos, 0)
                                write_uint32_at(file_data, current_pos + 4, 1)
                            else:
                                # write UV data floats
                                if vertex_index in vertex_uv_data:
                                    u, v = vertex_uv_data[vertex_index]
                                    write_float_at(file_data, current_pos, u)
                                    write_float_at(file_data, current_pos + 4, v)
                            current_pos += 8

                        elif tex_shading == -2:  # Type D
                            # skip normal data (3 bytes + 1 padding)
                            current_pos += 4
                            # skip bump0 normal data (3 bytes + 1 padding)
                            current_pos += 4
                            # skip bump1 normal data (3 bytes + 1 padding)
                            current_pos += 4

                            # write UV data - check for texture ID
                            if p.mh_texID == -1:
                                # write dummy values: U=0 (as uint), V=1 (as uint)
                                write_uint32_at(file_data, current_pos, 0)
                                write_uint32_at(file_data, current_pos + 4, 1)
                            else:
                                # write actual UV data floats
                                if vertex_index in vertex_uv_data:
                                    u, v = vertex_uv_data[vertex_index]
                                    write_float_at(file_data, current_pos, u)
                                    write_float_at(file_data, current_pos + 4, v)
                            current_pos += 8

                        else:  # Type A (regular)
                            # skip normal data (12 bytes for 3 floats)
                            current_pos += 12

                            # write UV data - check for texture ID
                            if p.mh_texID == -1:
                                # write dummy values: U=0 (as uint), V=1 (as uint)
                                write_uint32_at(file_data, current_pos, 0)
                                write_uint32_at(file_data, current_pos + 4, 1)
                            else:
                                # write UV data floats
                                if vertex_index in vertex_uv_data:
                                    u, v = vertex_uv_data[vertex_index]
                                    write_float_at(file_data, current_pos, u)
                                    write_float_at(file_data, current_pos + 4, v)
                            current_pos += 8

                        vertex_index += 1
                    else:
                        current_pos += 32

        current_pos = mesh_end
        mesh_index += 1

    with open(filepath, 'wb') as f:
        f.write(file_data)


def write_naomi_bin(filepath, obj):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    if not obj or obj.type != 'MESH':
        raise ValueError("Selected object is not a mesh.")

    mesh = obj.data
    vertices = mesh.vertices

    with open(filepath, 'wb') as f:
        f.write(b'\x01\x00\x00\x00\x01\x00\x00\x00')
        for vertex in vertices:
            f.write(struct.pack('<fff', vertex.co.x, vertex.co.y, vertex.co.z))
        f.write(b'\x00' * 4 + struct.pack('<I', len(vertices)))
