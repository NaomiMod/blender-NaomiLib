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
    """Extract UV coordinates for each vertex from the active UV map"""
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


def recalc_individual_mesh_centroids(collection):

    original_active = bpy.context.view_layer.objects.active
    original_selected = bpy.context.selected_objects.copy()
    original_mode = bpy.context.object.mode if bpy.context.object else 'OBJECT'

    mesh_objects = [obj for obj in collection.objects if obj.type == 'MESH' and obj.data.vertices]

    print(f"Starting individual mesh centroid calculation for {len(mesh_objects)} objects...")

    try:
        # Clear current selection
        for obj in bpy.context.selected_objects:
            obj.select_set(False)

        for obj in mesh_objects:
            if obj.type != 'MESH' or not obj.data.vertices:
                print(f"Skipping {obj.name}: Not a mesh or no vertices")
                continue

            # Select and activate object
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj

            was_in_edit_mode = bpy.context.object.mode == 'EDIT'

            if was_in_edit_mode:
                bpy.ops.object.editmode_toggle()
            elif bpy.context.object.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

            # Update mesh data without transforms
            mesh = obj.data
            mesh.update()
            mesh.calc_loop_triangles()
            bpy.context.view_layer.update()

            # Calculate centroid
            world_matrix = obj.matrix_world
            vertices = mesh.vertices

            # Transform all vertices to world space
            world_vertices = [world_matrix @ v.co for v in vertices]

            # Calculate centroid in world space
            centroid_x = sum(v.x for v in world_vertices) / len(world_vertices)
            centroid_y = sum(v.y for v in world_vertices) / len(world_vertices)
            centroid_z = sum(v.z for v in world_vertices) / len(world_vertices)
            centroid = Vector((centroid_x, centroid_y, centroid_z))

            # Calculate bound radius (max distance from centroid to any world vertex)
            bound_radius = max((v - centroid).length for v in world_vertices) if world_vertices else 0.0

            # Ensure naomi_param exists and update it
            if not hasattr(obj, 'naomi_param'):
                print(f"Warning: {obj.name} has no naomi_param property!")
                obj.select_set(False)
                continue

            obj.naomi_param.centroid_x = centroid_x
            obj.naomi_param.centroid_y = centroid_y
            obj.naomi_param.centroid_z = centroid_z
            obj.naomi_param.bound_radius = bound_radius

            print(
                f"Updated mesh '{obj.name}': world centroid=({centroid_x:.3f}, {centroid_y:.3f}, {centroid_z:.3f}), radius={bound_radius:.3f}")

            obj.select_set(False)

        bpy.context.view_layer.update()

    finally:
        # Restore original selection and mode
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

    print("Individual mesh centroid calculation completed.")


def recalc_collection_centroid_and_radius(collection):
    print(f"Starting collection centroid calculation for '{collection.name}'...")

    mesh_objects = [obj for obj in collection.objects if obj.type == 'MESH' and obj.data.vertices]

    if not mesh_objects:
        print("No mesh objects found in collection, setting default values")
        if hasattr(collection, 'naomi_centroidData'):
            collection.naomi_centroidData.centroid_x = 0.0
            collection.naomi_centroidData.centroid_y = 0.0
            collection.naomi_centroidData.centroid_z = 0.0
            collection.naomi_centroidData.collection_bound_radius = 0.0
        return

    valid_objects = []
    for obj in mesh_objects:
        if hasattr(obj, 'naomi_param'):
            valid_objects.append(obj)
        else:
            print(f"Warning: Object {obj.name} has no naomi_param, skipping from collection calculation")

    if not valid_objects:
        print("No valid objects with naomi_param found")
        return

    # calculate collection centroid as average of all mesh centroids
    total_centroid_x = sum(obj.naomi_param.centroid_x for obj in valid_objects)
    total_centroid_y = sum(obj.naomi_param.centroid_y for obj in valid_objects)
    total_centroid_z = sum(obj.naomi_param.centroid_z for obj in valid_objects)

    collection_centroid_x = total_centroid_x / len(valid_objects)
    collection_centroid_y = total_centroid_y / len(valid_objects)
    collection_centroid_z = total_centroid_z / len(valid_objects)

    # calculate collection bound radius using the same world-space method
    collection_centroid = Vector((collection_centroid_x, collection_centroid_y, collection_centroid_z))
    max_distance = 0.0

    for obj in valid_objects:
        # world coordinate calculation as individual mesh function
        world_matrix = obj.matrix_world
        for vertex in obj.data.vertices:
            world_vertex = world_matrix @ vertex.co
            distance = (world_vertex - collection_centroid).length
            if distance > max_distance:
                max_distance = distance

    # update collection naomi parameters
    if not hasattr(collection, 'naomi_centroidData'):
        print(f"Warning: Collection {collection.name} has no naomi_centroidData property!")
        return

    collection.naomi_centroidData.centroid_x = collection_centroid_x
    collection.naomi_centroidData.centroid_y = collection_centroid_y
    collection.naomi_centroidData.centroid_z = collection_centroid_z
    collection.naomi_centroidData.collection_bound_radius = max_distance

    print(
        f"Updated collection '{collection.name}': centroid=({collection_centroid_x:.3f}, {collection_centroid_y:.3f}, {collection_centroid_z:.3f}), radius={max_distance:.3f}")
    print("Collection centroid calculation completed.")

# ---------------------------
# NL file update (NO REMESH!)
# ---------------------------

def update_naomi_bin(filepath, collection):

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

    # apply transforms ONLY during export
    mesh_data_update(collection)
    bpy.context.view_layer.update()

    # Recalculate centroids
    #recalc_individual_mesh_centroids(collection)
    #recalc_collection_centroid_and_radius(collection)


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

    # Write updated collection centroid & radius
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

    mesh_objects = [obj for obj in collection.objects if obj.type == 'MESH']
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

        # Get vertex colors and UV data
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

                if 0x5FF00000 <= vertex_value <= 0x5FFFFFFF:
                    current_pos += 8
                else:
                    if vertex_index < len(vertex_positions):
                        co = vertex_positions[vertex_index]
                        rev_pos = reverse_axis_transformation(co, orientation, neg_scale_x)

                        # Write position data
                        write_float_x_aligned(file_data, current_pos, rev_pos[0])
                        write_float_at(file_data, current_pos + 4, rev_pos[1])
                        write_float_at(file_data, current_pos + 8, rev_pos[2])
                        current_pos += 12

                        # Handle different vertex types based on m_tex_shading
                        tex_shading = getattr(current_obj.naomi_param, 'm_tex_shading', 0)

                        if tex_shading == -3:  # Type C
                            # Skip normal data (3 bytes + 1 padding byte)
                            current_pos += 4

                            # Write vertex colors
                            if vertex_colors_data and vertex_index in vertex_colors_data:
                                color_data = vertex_colors_data[vertex_index]
                                b = int(max(0, min(255, color_data[2] * 255)))
                                g = int(max(0, min(255, color_data[1] * 255)))
                                r = int(max(0, min(255, color_data[0] * 255)))
                                a = int(max(0, min(255, color_data[3] * 255)))
                                for i, val in enumerate([b, g, r, a, b, g, r, a]):
                                    write_uint8_at(file_data, current_pos + i, val)
                            current_pos += 8

                            # Write UV data
                            if vertex_index in vertex_uv_data:
                                u, v = vertex_uv_data[vertex_index]
                                write_float_at(file_data, current_pos, u)
                                write_float_at(file_data, current_pos + 4, v)
                            current_pos += 8

                        elif tex_shading == -2:  # Type D
                            # Skip normal data (3 bytes + 1 padding)
                            current_pos += 4
                            # Skip bump0 normal data (3 bytes + 1 padding)
                            current_pos += 4
                            # Skip bump1 normal data (3 bytes + 1 padding)
                            current_pos += 4

                            # Write UV data
                            if vertex_index in vertex_uv_data:
                                u, v = vertex_uv_data[vertex_index]
                                write_float_at(file_data, current_pos, u)
                                write_float_at(file_data, current_pos + 4, v)
                            current_pos += 8

                        else:  # Type A (regular)
                            # Skip normal data (12 bytes for 3 floats)
                            current_pos += 12

                            # Write UV data
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
