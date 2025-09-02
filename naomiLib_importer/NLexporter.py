import bpy
from bpy.types import Operator
from bpy.props import FloatVectorProperty
from bpy_extras.object_utils import AddObjectHelper, object_data_add
import struct
import sys
import os
from io import BytesIO
from math import radians
from mathutils import Vector
import zlib

xVal = 0
yVal = 1
zVal = 2


def calculate_crc32(filepath):
    crc = 0
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            crc = zlib.crc32(chunk, crc)
    return f"{crc & 0xffffffff:08x}"


def reverse_axis_transformation(vertex, orientation, neg_scale_x):

    x, y, z = vertex

    # Reverse orientation transformation (exact opposite of import)
    if orientation == 'X_UP':
        x, y, z = y, x, z
    elif orientation == 'Y_UP':
        pass
    elif orientation == 'Z_UP':
        x, y, z = x, z, y

    # Reverse negative scaling (if applied during import)
    if neg_scale_x:
        x *= -1.0

    return (x, y, z)


def force_mesh_data_update(collection):
    # mesh data update AND apply transformations for all objects in collection

    print("=== STARTING FORCE_MESH_DATA_UPDATE ===")

    original_active = bpy.context.view_layer.objects.active
    original_selected = [obj for obj in bpy.context.selected_objects]

    print(f"Collection has {len(collection.objects)} objects")
    mesh_objects = [obj for obj in collection.objects if obj.type == 'MESH']
    print(f"Found {len(mesh_objects)} mesh objects")

    try:

        print("\n--- APPLYING TRANSFORMS TO ALL OBJECTS IN COLLECTION ---")
        for obj in collection.objects:
            print(f"Processing object: {obj.name} (type: {obj.type})")

            # object active and selected
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            # exit any mode
            if bpy.context.mode != 'OBJECT':
                print("  Switching to OBJECT mode...")
                bpy.ops.object.mode_set(mode='OBJECT')

            # Apply all transformations
            print(f"  Before transforms - Location: {obj.location}, Rotation: {obj.rotation_euler}, Scale: {obj.scale}")

            print("  Applying transforms (forced)...")
            try:
                bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
                print("  Transform apply completed")
            except Exception as e:
                print(f"  Transform apply FAILED: {e}")


            print(f"  After transforms - Location: {obj.location}, Rotation: {obj.rotation_euler}, Scale: {obj.scale}")

            # clear selection for next object
            obj.select_set(False)

        # Process mesh objects for data updates
        print("\n--- UPDATING MESH DATA ---")
        for obj in mesh_objects:
            print(f"Updating mesh data for: {obj.name}")

            # Make object active and selected
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)

            # Force all update methods
            if obj.type == 'MESH':
                obj.data.calc_loop_triangles()
                obj.data.update()
                obj.update_from_editmode()
                bpy.context.view_layer.update()

            # clear selection for next object
            obj.select_set(False)

        # Final updates
        bpy.context.view_layer.update()
        bpy.context.evaluated_depsgraph_get().update()

        print("=== FORCE_MESH_DATA_UPDATE COMPLETED ===")

    finally:
        # restore original context
        bpy.ops.object.select_all(action='DESELECT')
        for obj in original_selected:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = original_active


def update_naomi_bin(filepath, collection):
    """Update existing NaomiLib .bin file with current mesh data"""

    print("=== STARTING UPDATE_NAOMI_BIN ===")

    force_mesh_data_update(collection)
    bpy.context.view_layer.update()

    if not collection.naomi_import_meta.source_filepath:
        raise ValueError("No import metadata found. Collection was not imported from NaomiLib file.")

    # Check filename match
    original_filename = os.path.basename(collection.naomi_import_meta.source_filepath)
    target_filename = os.path.basename(filepath)
    if original_filename != target_filename:
        raise ValueError(f"Filename mismatch: {original_filename} vs {target_filename}")

    # CRC32 if target exists
    if os.path.exists(filepath):
        target_crc32 = calculate_crc32(filepath)
        if target_crc32 != collection.naomi_import_meta.source_crc32:
            raise ValueError(
                f"CRC32 mismatch: expected {collection.naomi_import_meta.source_crc32}, got {target_crc32}")

    # Store original file in memory
    with open(filepath, 'rb') as f:
        file_data = bytearray(f.read())

    # Import settings for reverse transformation
    orientation = collection.naomi_import_meta.import_orientation
    neg_scale_x = collection.naomi_import_meta.import_neg_scale_x

    def write_float_at(offset, value):
        struct.pack_into("<f", file_data, offset, value)

    def write_float_x_aligned(offset, value):     # Write X vertex float with bit 0 forced to 1
        struct.pack_into('<I', file_data, offset, struct.unpack('<I', struct.pack('<f', value))[0] | 1)

    def write_uint32_at(offset, value):
        struct.pack_into("<I", file_data, offset, value)

    def write_sint32_at(offset, value):
        struct.pack_into("<i", file_data, offset, value)

    # Global parameters from collection
    gp0 = collection.gp0
    gp1 = collection.gp1

    # Update Global Flag 0
    if gp0.objFormat == '0':
        file_data[0x0] = 0x00  # Beta Index
    elif gp0.objFormat == '1':
        file_data[0x0] = 0x01  # Super Index

    # Update Global Flag 1
    gflag1 = 0x0001  # bit0 is always true (1)

    if gp1.skp1stSrcOp:
        gflag1 |= (1 << 1)  # bit1
    if gp1.envMap:
        gflag1 |= (1 << 2)  # bit2
    if gp1.pltTex:
        gflag1 |= (1 << 3)  # bit3
    if gp1.bumpMap:
        gflag1 |= (1 << 4)  # bit4

    file_data[0x4:0x6] = struct.pack('<H', gflag1)

    # Object centroid (reverse transform)
    centroid = (
        collection.naomi_centroidData.centroid_x,
        collection.naomi_centroidData.centroid_y,
        collection.naomi_centroidData.centroid_z
    )
    reversed_centroid = reverse_axis_transformation(centroid, orientation, neg_scale_x)

    write_float_at(0x8, reversed_centroid[0])
    write_float_at(0xC, reversed_centroid[1])
    write_float_at(0x10, reversed_centroid[2])
    write_float_at(0x14, collection.naomi_centroidData.collection_bound_radius)

    # Get mesh objects in order
    mesh_objects = [obj for obj in collection.objects if obj.type == 'MESH']

    # Track current position in file for reading offsets
    current_pos = 0x18  # Start of first mesh params
    mesh_index = 0

    # Process each mesh
    while mesh_index < len(mesh_objects) and current_pos < len(file_data) - 4:
        # Check for end marker
        end_check = struct.unpack_from("<I", file_data, current_pos)[0]
        if end_check == 0:
            break

        current_obj = mesh_objects[mesh_index]

        # Update mesh parameters at current_pos
        param_type = int(current_obj.naomi_param.paramType)
        end_of_strip = int(current_obj.naomi_param.endOfStrip)
        list_type = int(current_obj.naomi_param.listType)
        grp_en = int(current_obj.naomi_param.grpEn)
        strip_len = int(current_obj.naomi_param.stripLen)
        usr_clip = int(current_obj.naomi_param.usrClip)
        shadow = int(current_obj.naomi_param.shadow)
        volume = int(current_obj.naomi_param.volume)
        col_type = int(current_obj.naomi_param.colType)
        texture_usage = int(current_obj.naomi_param.textureUsage)
        offs_color_usage = int(current_obj.naomi_param.offsColorUsage)
        gouraud_shd_usage = int(current_obj.naomi_param.gouraudShdUsage)
        uv_data_size = int(current_obj.naomi_param.uvDataSize)

        new_params = (
                (param_type << 29) | (end_of_strip << 28) | (list_type << 24) |
                (grp_en << 23) | (strip_len << 18) | (usr_clip << 16) |
                (shadow << 7) | (volume << 6) | (col_type << 4) |
                (texture_usage << 3) | (offs_color_usage << 2) |
                (gouraud_shd_usage << 1) | uv_data_size
        )

        write_uint32_at(current_pos, new_params)
        current_pos += 16  # Skip to mesh centroid (4 uint32s = 16 bytes)

        # Update mesh centroid
        mesh_centroid = (
            current_obj.naomi_param.centroid_x,
            current_obj.naomi_param.centroid_y,
            current_obj.naomi_param.centroid_z
        )
        reversed_mesh_centroid = reverse_axis_transformation(mesh_centroid, orientation, neg_scale_x)

        write_float_at(current_pos, reversed_mesh_centroid[0])
        write_float_at(current_pos + 4, reversed_mesh_centroid[1])
        write_float_at(current_pos + 8, reversed_mesh_centroid[2])
        write_float_at(current_pos + 12, current_obj.naomi_param.bound_radius)
        current_pos += 16  # 4 floats = 16 bytes

        # Update texture ID, shading, ambient light
        write_sint32_at(current_pos, current_obj.naomi_param.mh_texID)
        current_pos += 4

        write_sint32_at(current_pos, current_obj.naomi_param.m_tex_shading)
        current_pos += 4

        write_float_at(current_pos, current_obj.naomi_param.texture_ambient_light)
        current_pos += 4

        # Update base color
        base_color = current_obj.naomi_param.meshColor
        write_float_at(current_pos, base_color[3])  # A
        write_float_at(current_pos + 4, base_color[0])  # R
        write_float_at(current_pos + 8, base_color[1])  # G
        write_float_at(current_pos + 12, base_color[2])  # B
        current_pos += 16

        # Update offset color
        offset_color = current_obj.naomi_param.meshOffsetColor
        write_float_at(current_pos, offset_color[3])  # A
        write_float_at(current_pos + 4, offset_color[0])  # R
        write_float_at(current_pos + 8, offset_color[1])  # G
        write_float_at(current_pos + 12, offset_color[2])  # B
        current_pos += 16

        # Get mesh data size and calculate mesh end
        mesh_data_size = struct.unpack_from("<I", file_data, current_pos)[0]
        current_pos += 4  # Skip mesh size field
        mesh_end = current_pos + mesh_data_size

        # Update vertex positions only
        current_mesh = current_obj.data
        vertex_positions = [v.co for v in current_mesh.vertices]
        vertex_index = 0

        # Process vertex data within this mesh
        while current_pos < mesh_end and current_pos < len(file_data) - 8:
            # Read face type and vertex count
            face_type = struct.unpack_from("<I", file_data, current_pos)[0]
            current_pos += 4

            is_triangles = (face_type >> 3) & 1
            n_faces = struct.unpack_from("<I", file_data, current_pos)[0]
            current_pos += 4

            n_vertices = n_faces * 3 if is_triangles else n_faces

            # Process each vertex
            for v in range(n_vertices):
                if current_pos >= mesh_end:
                    break

                # Check if Type B vertex
                vertex_value = struct.unpack_from("<I", file_data, current_pos)[0]

                if 0x5FF00000 <= vertex_value <= 0x5FFFFFFF:
                    # Type B vertex - skip 8 bytes (vertex ID + pointer)
                    current_pos += 8
                else:
                    # Type A vertex - update position and skip rest
                    if vertex_index < len(vertex_positions):
                        vertex_co = vertex_positions[vertex_index]
                        reversed_pos = reverse_axis_transformation(vertex_co, orientation, neg_scale_x)

                        # Update vertex position (first 12 bytes)
                        write_float_x_aligned(current_pos, reversed_pos[0])
                        write_float_at(current_pos + 4, reversed_pos[1])
                        write_float_at(current_pos + 8, reversed_pos[2])

                        vertex_index += 1

                    # Placeholder, skip entire vertex data (position + normal + UV = 32 bytes minimum)
                    current_pos += 32

        # Move to next mesh start
        current_pos = mesh_end
        mesh_index += 1

    with open(filepath, 'wb') as f:
        f.write(file_data)

    print("=== UPDATE_NAOMI_BIN COMPLETED ===")

def write_naomi_bin(filepath, obj):
    """Selected mesh PLACEHOLDER!"""

    # Enter Object mode before doing anything
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

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
        f.write(b'\x00' * 4 + struct.pack('<I', len(vertices)))

    print(f"Successfully exported mesh '{obj.name}' to {filepath}")
