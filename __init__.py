bl_info = {
    "name" : "NaomiLib for Blender",
    "author" : "zocker_160, VincentNL, TVIndustries",
    "description" : "Addon for importing / exporting NaomiLib .bin files",
    "blender" : (5, 1, 0),
    "version" : (1, 0, 2),
    "location" : "File > Import / Export",
    "warning" : "",
    "category": "Import-Export",
    "tracker_url": "https://github.com/NaomiMod/blender-NaomiLib"
}

import bpy
import importlib
import json
import os
import time
import shutil

try:
    import bl_previews as _previews_mod  # Blender 5.x+
except ImportError:
    import bpy.utils.previews as _previews_mod  # Blender 4.x
from . import NLimporter as NLi
from . import NLexporter as NLe
from . import bl_pypvr as pypvr
from bpy.props import StringProperty, BoolProperty, FloatProperty, FloatVectorProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper


# -------------------------
# Naomi material building
# -------------------------
# Naomi material building and shading node module

# Hardware formula: Output = SRC_mode × SRC_image + DST_mode × DST_image
# Index matches naomi_tsp.srcAlpha / naomi_tsp.dstAlpha (0-7).

NAOMI_BLEND_MODES = [
    (0, 'ZERO',                "ZERO",               "( 0, 0, 0, 0 )",             "All coefficients zero — do not display (black)"),
    (1, 'ONE',                 "ONE",                "( 1, 1, 1, 1 )",             "All coefficients one — display as-is"),
    (2, 'OTHER_COLOR',         "OTHER COLOR",        "( Oa, Or, Og, Ob )",         "Multiply by ARGB brightness of the other side"),
    (3, 'INVERSE_OTHER_COLOR', "INVERSE OTHER COLOR","( 1-Oa, 1-Or, 1-Og, 1-Ob )", "Multiply by one minus ARGB of the other side"),
    (4, 'SRC_ALPHA',           "SRC ALPHA",          "( Sa, Sa, Sa, Sa )",         "Multiply by the SRC alpha value"),
    (5, 'INVERSE_SRC_ALPHA',   "INVERSE SRC ALPHA",  "( 1-Sa, 1-Sa, 1-Sa, 1-Sa )", "Multiply by one minus the SRC alpha"),
    (6, 'DST_ALPHA',           "DST ALPHA",          "( Da, Da, Da, Da )",         "Multiply by the DST alpha value"),
    (7, 'INVERSE_DST_ALPHA',   "INVERSE DST ALPHA",  "( 1-Da, 1-Da, 1-Da, 1-Da )", "Multiply by one minus the DST alpha"),
]

_BLEND_METHOD_MAP = {
    (1, 0): 'OPAQUE',
    (4, 5): 'BLEND',
    (1, 4): 'BLEND',
    (1, 5): 'BLEND',
    (4, 1): 'BLEND',
    (5, 1): 'BLEND',
    (0, 1): 'BLEND',
    (2, 3): 'BLEND',
}


def _blend_method_for(src_idx: int, dst_idx: int, list_type: int = -1) -> str:
    key = (src_idx, dst_idx)
    if key in _BLEND_METHOD_MAP:
        return _BLEND_METHOD_MAP[key]
    if list_type == 4:
        return 'CLIP'
    if src_idx in (4, 5, 6, 7) or dst_idx in (4, 5, 6, 7):
        return 'BLEND'
    if dst_idx != 0:
        return 'BLEND'
    return 'OPAQUE'


def _apply_blend_method(mat, method: str):
    # Blender 4.2+ renamed blend_method -> surface_render_method with new value strings
    new_method = 'BLENDED' if method in ('BLEND', 'CLIP') else 'DITHERED'
    if hasattr(mat, 'surface_render_method'):
        mat.surface_render_method = new_method
    else:
        mat.blend_method = method


def _rebuild_blend_nodes(mat, src_idx: int, dst_idx: int):
    if not (mat and mat.use_nodes and mat.node_tree):
        return

    tree  = mat.node_tree
    nodes = tree.nodes
    links = tree.links

    bsdf    = nodes.get('Principled BSDF')
    mat_out = nodes.get('Material Output')
    if bsdf is None or mat_out is None:
        return

    surface_input = mat_out.inputs['Surface']

    # Remove previously-built naomi-blend nodes
    nodes_to_remove = set()
    for node in list(nodes):
        if node.get('_naomi_blend'):
            nodes_to_remove.add(node)

    # Also catch untagged Add Shader + Transparent BSDF pairs left
    for node in list(nodes):
        if node.bl_idname == 'ShaderNodeAddShader':
            goes_to_surface = any(
                lk.from_node == node and lk.to_socket == surface_input
                for lk in links
            )
            if not goes_to_surface:
                continue
            for lk in links:
                if lk.to_node == node and lk.from_node.bl_idname == 'ShaderNodeBsdfTransparent':
                    nodes_to_remove.add(node)
                    nodes_to_remove.add(lk.from_node)

    links_to_remove = [
        lk for lk in links
        if lk.from_node in nodes_to_remove or lk.to_node in nodes_to_remove
    ]
    for lk in links_to_remove:
        links.remove(lk)
    for node in nodes_to_remove:
        nodes.remove(node)

    # Restore direct BSDF -> Surface as baseline
    has_direct = any(
        lk.from_node == bsdf and lk.to_socket == surface_input
        for lk in links
    )
    if not has_direct:
        links.new(bsdf.outputs['BSDF'], surface_input)

    x0 = bsdf.location.x + 320
    y0 = bsdf.location.y

    def new_node(bl_idname, dx=0, dy=0):
        n = nodes.new(bl_idname)
        n.location = (x0 + dx, y0 + dy)
        n['_naomi_blend'] = True
        return n

    def make_transparent(color=(1.0, 1.0, 1.0, 1.0), dx=0, dy=120):
        t = new_node('ShaderNodeBsdfTransparent', dx, dy)
        t.inputs['Color'].default_value = color
        return t

    def splice_via_add(shader_a, shader_b, dx_add=220):
        for lk in [l for l in links if l.to_socket == surface_input]:
            links.remove(lk)
        add = new_node('ShaderNodeAddShader', dx_add, 0)
        links.new(shader_a, add.inputs[0])
        links.new(shader_b, add.inputs[1])
        links.new(add.outputs['Shader'], surface_input)

    def splice_via_mix(fac, shader_a, shader_b, dx_mix=220):
        for lk in [l for l in links if l.to_socket == surface_input]:
            links.remove(lk)
        mix = new_node('ShaderNodeMixShader', dx_mix, 0)
        if hasattr(fac, 'node'):
            links.new(fac, mix.inputs['Fac'])
        else:
            mix.inputs['Fac'].default_value = float(fac)
        links.new(shader_a, mix.inputs[1])
        links.new(shader_b, mix.inputs[2])
        links.new(mix.outputs['Shader'], surface_input)

    key = (src_idx, dst_idx)

    if key == (1, 0):
        pass  # OPAQUE: direct BSDF -> Output already restored

    elif key == (4, 5):
        pass  # Standard alpha-blend: surface_render_method handles it

    elif key == (4, 1):
        t = make_transparent(color=(1.0, 1.0, 1.0, 1.0))
        splice_via_add(bsdf.outputs['BSDF'], t.outputs['BSDF'])

    elif key == (5, 1):
        alpha = bsdf.inputs['Alpha'].default_value
        inv_alpha = max(0.0, min(1.0, 1.0 - alpha))
        t = make_transparent(color=(1.0, 1.0, 1.0, 1.0))
        splice_via_mix(inv_alpha, t.outputs['BSDF'], bsdf.outputs['BSDF'])

    elif key == (0, 1):
        t = make_transparent(color=(0.0, 0.0, 0.0, 1.0))
        for lk in [l for l in links if l.to_socket == surface_input]:
            links.remove(lk)
        links.new(t.outputs['BSDF'], surface_input)

    elif key == (1, 1):
        t = make_transparent(color=(1.0, 1.0, 1.0, 1.0))
        splice_via_add(bsdf.outputs['BSDF'], t.outputs['BSDF'])

    elif key == (1, 4):
        t = make_transparent(color=(1.0, 1.0, 1.0, 1.0))
        splice_via_add(bsdf.outputs['BSDF'], t.outputs['BSDF'])

    elif key == (1, 5):
        t = make_transparent(color=(1.0, 1.0, 1.0, 1.0))
        splice_via_mix(0.5, bsdf.outputs['BSDF'], t.outputs['BSDF'])

    elif key == (2, 3):
        pass  # blend_method=BLENDED sufficient

    else:
        pass  # Fallback: BSDF -> Output; blend_method already set


def _rebuild_tex_shading_nodes(mat, tex_shading_idx: int, alpha_tex_op: str = '0'):
    """
    Rewire shader nodes to implement the NAOMI Texture/Shading formula:
      0  Decal          PIXrgb = TEXrgb + OFFSETrgb            PIXa = TEXa
      1  Modulate       PIXrgb = COLrgb * TEXrgb + OFFSETrgb   PIXa = TEXa
      2  Decal Alpha    PIXrgb = lerp(COLrgb, TEXrgb, TEXa)    PIXa = COLa
      3  Modulate Alpha PIXrgb = COLrgb * TEXrgb + OFFSETrgb   PIXa = COLa * TEXa
    alpha_tex_op '1' = Ignore Texture Alpha.
    """
    if not (mat and mat.use_nodes and mat.node_tree):
        return

    tree  = mat.node_tree
    nodes = tree.nodes
    links = tree.links

    bsdf = nodes.get('Principled BSDF')
    if bsdf is None:
        return

    tex_node = next(
        (n for n in nodes if n.bl_idname == 'ShaderNodeTexImage'),
        None,
    )

    # Remove previously-built tex-shading nodes
    nodes_to_remove = [n for n in list(nodes) if n.get('_naomi_tex_shading')]
    links_to_remove = [
        lk for lk in links
        if lk.from_node in nodes_to_remove or lk.to_node in nodes_to_remove
    ]
    for lk in links_to_remove:
        links.remove(lk)
    for n in nodes_to_remove:
        nodes.remove(n)

    # Restore direct Texture -> Base Color as baseline
    if tex_node is not None:
        has_direct = any(
            lk.from_node == tex_node and lk.to_socket == bsdf.inputs['Base Color']
            for lk in links
        )
        if not has_direct:
            links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])

    if tex_node is None:
        return

    bx = bsdf.location.x
    by = bsdf.location.y

    def new_node(bl_idname, dx=0, dy=0):
        n = nodes.new(bl_idname)
        n.location = (bx - 220 + dx, by + dy)
        n['_naomi_tex_shading'] = True
        return n

    col_rgb = tuple(bsdf.inputs['Base Color'].default_value)[:3] + (1.0,)
    col_a   = bsdf.inputs['Alpha'].default_value
    _use_alpha = (alpha_tex_op != '1')

    if tex_shading_idx == 0:
        # Decal: PIXrgb = TEXrgb, PIXa = TEXa (or COLa when ignored)
        for lk in [l for l in links if l.to_socket == bsdf.inputs['Alpha']]:
            links.remove(lk)
        if _use_alpha:
            links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])

    elif tex_shading_idx == 1:
        # Modulate: PIXrgb = COLrgb * TEXrgb, PIXa = TEXa (or COLa)
        for lk in [l for l in links if l.to_socket == bsdf.inputs['Base Color']]:
            links.remove(lk)
        mul = new_node('ShaderNodeMixRGB', dx=-10, dy=60)
        mul.blend_type  = 'MULTIPLY'
        mul.use_clamp   = True
        mul.inputs[0].default_value = 1.0
        mul.inputs[1].default_value = col_rgb
        links.new(tex_node.outputs['Color'], mul.inputs[2])
        links.new(mul.outputs['Color'], bsdf.inputs['Base Color'])
        for lk in [l for l in links if l.to_socket == bsdf.inputs['Alpha']]:
            links.remove(lk)
        if _use_alpha:
            links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])

    elif tex_shading_idx == 2:
        # Decal Alpha: PIXrgb = lerp(COLrgb, TEXrgb, TEXa), PIXa = COLa
        # TEXa is always used as mix factor regardless of alpha_tex_op
        for lk in [l for l in links if l.to_socket == bsdf.inputs['Base Color']]:
            links.remove(lk)
        mix = new_node('ShaderNodeMixRGB', dx=-10, dy=60)
        mix.blend_type  = 'MIX'
        mix.use_clamp   = True
        links.new(tex_node.outputs['Alpha'], mix.inputs[0])
        mix.inputs[1].default_value = col_rgb
        links.new(tex_node.outputs['Color'], mix.inputs[2])
        links.new(mix.outputs['Color'], bsdf.inputs['Base Color'])
        for lk in [l for l in links if l.to_socket == bsdf.inputs['Alpha']]:
            links.remove(lk)
        bsdf.inputs['Alpha'].default_value = col_a

    elif tex_shading_idx == 3:
        # Modulate Alpha: PIXrgb = COLrgb * TEXrgb, PIXa = COLa * TEXa
        # When Ignore Texture Alpha: PIXa = COLa
        for lk in [l for l in links if l.to_socket == bsdf.inputs['Base Color']]:
            links.remove(lk)
        mul = new_node('ShaderNodeMixRGB', dx=-10, dy=80)
        mul.blend_type  = 'MULTIPLY'
        mul.use_clamp   = True
        mul.inputs[0].default_value = 1.0
        mul.inputs[1].default_value = col_rgb
        links.new(tex_node.outputs['Color'], mul.inputs[2])
        links.new(mul.outputs['Color'], bsdf.inputs['Base Color'])
        for lk in [l for l in links if l.to_socket == bsdf.inputs['Alpha']]:
            links.remove(lk)
        if _use_alpha:
            math_a = new_node('ShaderNodeMath', dx=-10, dy=-60)
            math_a.operation = 'MULTIPLY'
            math_a.use_clamp = True
            math_a.inputs[0].default_value = col_a
            links.new(tex_node.outputs['Alpha'], math_a.inputs[1])
            links.new(math_a.outputs['Value'], bsdf.inputs['Alpha'])


def build_naomi_material(
    mat,
    mesh_color,
    mesh_offset_color,
    tex_shading: int,
    tsp_src_alpha: int,
    tsp_dst_alpha: int,
    list_type: int,
    flip_uv: int,
    clamp: int,
    alpha_tex_op: str,
    use_backface_culling: bool,
    mh_tex_id: int,
    tex_image,
    is_env_map: bool,
    vertex_col_layer,
    m_tex_amb,
    tsp_filter: str = '0',
    is_bump_base: bool = False,
    is_bump_overlay: bool = False,
    base_tex_image = None,
):
    """
    Configure all shader nodes on mat to represent the given NAOMI hardware
    parameters. Single source of truth — both the importer and all live
    property-update callbacks must call this.

    Bump-map pair (NAOMI PVR pixel format 4, two polygon passes):
      is_bump_base    — pass 1: flat colour polygon, bump alpha written to frame buffer
      is_bump_overlay — pass 2: semi-transparent textured polygon composited on top
    Neither flag → legacy NormalMap wiring (backwards compat).

    Returns the ShaderNodeTexImage node, or None.
    """
    if mat is None:
        return None

    mat.use_nodes = True
    mat.use_backface_culling = use_backface_culling

    tree  = mat.node_tree
    nodes = tree.nodes
    links = tree.links

    bsdf = nodes.get('Principled BSDF')
    if bsdf is None:
        return None

    # Full node tree teardown — always start from a clean slate
    keep = {bsdf, nodes.get('Material Output')}
    for node in list(nodes):
        if node not in keep:
            nodes.remove(node)
    for link in list(links):
        links.remove(link)

    bsdf.inputs['Base Color'].default_value   = mesh_color
    bsdf.inputs['Alpha'].default_value        = mesh_color[3]
    if 'Specular Tint' in bsdf.inputs:
        bsdf.inputs['Specular Tint'].default_value = mesh_offset_color
    bsdf.inputs['IOR'].default_value          = 1.0

    spec_int = tex_shading
    if spec_int > -1:
        spec_val = (1.0 if spec_int == 0
                    else 1.0 / spec_int if spec_int <= 5
                    else 1.0 / spec_int + 0.02)
    else:
        spec_val = 0.0
    mat.roughness = spec_val
    mat.metallic   = 0.0

    # Bump base wires its own blend nodes later; skip early override here
    _blend_src = tsp_src_alpha
    if tex_shading == -2 and not is_bump_base:
        _blend_dst = 1 if not is_bump_overlay else tsp_dst_alpha
    else:
        _blend_dst = tsp_dst_alpha

    _apply_blend_method(mat, _blend_method_for(_blend_src, _blend_dst, list_type))
    _rebuild_blend_nodes(mat, _blend_src, _blend_dst)

    texture_node      = None
    vertex_color_node = None

    if tex_shading == -3 and vertex_col_layer is not None:
        # Blender 4.0+ replaced ShaderNodeVertexColor with ShaderNodeAttribute
        if bpy.app.version >= (4, 0, 0):
            vertex_color_node = nodes.new('ShaderNodeAttribute')
            vertex_color_node.attribute_type = 'GEOMETRY'
            vertex_color_node.attribute_name = vertex_col_layer
        else:
            vertex_color_node = nodes.new('ShaderNodeVertexColor')
            vertex_color_node.layer_name = vertex_col_layer

    if mh_tex_id >= 0 and tex_image is not None:

        texture_node = nodes.new('ShaderNodeTexImage')
        texture_node.image = tex_image
        # Point sampled ('0') → Closest; bilinear etc. → Linear
        texture_node.interpolation = "Closest" if tsp_filter == '0' else "Linear"

        if is_env_map:
            tex_coord_node  = nodes.new('ShaderNodeTexCoord')
            xform_node      = nodes.new('ShaderNodeVectorTransform')
            mapping_node    = nodes.new('ShaderNodeMapping')

            xform_node.vector_type  = 'NORMAL'
            xform_node.convert_from = 'OBJECT'
            xform_node.convert_to   = 'CAMERA'

            mapping_node.inputs['Location'].default_value = (0.5, 0.5, 0.0)
            mapping_node.inputs['Scale'].default_value    = (0.5, -0.5, 1.0)

            texture_node.extension = 'EXTEND'

            links.new(tex_coord_node.outputs['Normal'], xform_node.inputs['Vector'])
            links.new(xform_node.outputs['Vector'],     mapping_node.inputs['Vector'])
            links.new(mapping_node.outputs['Vector'],   texture_node.inputs['Vector'])

        tex_image.alpha_mode = "CHANNEL_PACKED"

        if list_type in (2, 4):
            if alpha_tex_op == '0':
                links.new(texture_node.outputs['Alpha'], bsdf.inputs['Alpha'])

        if not is_env_map:

            if clamp == 0:
                texture_node.extension = "REPEAT"
            else:
                texture_node.extension = "EXTEND"

            if not (flip_uv == 0 and clamp == 0) and clamp != 3:
                uv_node           = nodes.new('ShaderNodeUVMap')
                separate_xyz_node = nodes.new('ShaderNodeSeparateXYZ')
                combine_xyz_node  = nodes.new('ShaderNodeCombineXYZ')
                math_node         = nodes.new('ShaderNodeMath')

                links.new(uv_node.outputs['UV'], separate_xyz_node.inputs['Vector'])

                if flip_uv == 1 and clamp == 0:
                    math_node.operation = 'PINGPONG'
                    links.new(separate_xyz_node.outputs['X'], combine_xyz_node.inputs['X'])
                    links.new(separate_xyz_node.outputs['Y'], math_node.inputs[0])
                    links.new(math_node.outputs[0],           combine_xyz_node.inputs['Y'])

                elif flip_uv == 2 and clamp == 0:
                    math_node.operation = 'PINGPONG'
                    links.new(separate_xyz_node.outputs['Y'], combine_xyz_node.inputs['Y'])
                    links.new(separate_xyz_node.outputs['X'], math_node.inputs[0])
                    links.new(math_node.outputs[0],           combine_xyz_node.inputs['X'])

                elif flip_uv == 3 and clamp == 0:
                    math_node.operation  = 'PINGPONG'
                    math_node2           = nodes.new('ShaderNodeMath')
                    math_node2.operation = 'PINGPONG'
                    math_node2.inputs[1].default_value = 1.0
                    links.new(separate_xyz_node.outputs['Y'], math_node2.inputs[0])
                    links.new(separate_xyz_node.outputs['X'], math_node.inputs[0])
                    links.new(math_node2.outputs[0],          combine_xyz_node.inputs['Y'])
                    links.new(math_node.outputs[0],           combine_xyz_node.inputs['X'])

                elif flip_uv in (0, 1) and clamp == 1:
                    math_node.operation = 'WRAP'
                    math_node.inputs[2].default_value = 0.0
                    texture_node.interpolation = "Cubic"
                    links.new(separate_xyz_node.outputs['Y'], combine_xyz_node.inputs['Y'])
                    links.new(separate_xyz_node.outputs['X'], math_node.inputs[0])
                    links.new(math_node.outputs[0],           combine_xyz_node.inputs['X'])

                elif flip_uv in (0, 2) and clamp == 2:
                    math_node.operation = 'WRAP'
                    math_node.inputs[2].default_value = 0.0
                    texture_node.interpolation = "Cubic"
                    links.new(separate_xyz_node.outputs['X'], combine_xyz_node.inputs['X'])
                    links.new(separate_xyz_node.outputs['Y'], math_node.inputs[0])
                    links.new(math_node.outputs[0],           combine_xyz_node.inputs['Y'])

                elif flip_uv in (1, 3) and clamp == 2:
                    math_node.operation = 'PINGPONG'
                    links.new(separate_xyz_node.outputs['X'], combine_xyz_node.inputs['X'])
                    links.new(separate_xyz_node.outputs['Y'], math_node.inputs[0])
                    links.new(math_node.outputs[0],           combine_xyz_node.inputs['Y'])

                elif flip_uv in (2, 3) and clamp == 1:
                    math_node.operation = 'PINGPONG'
                    links.new(separate_xyz_node.outputs['Y'], combine_xyz_node.inputs['Y'])
                    links.new(separate_xyz_node.outputs['X'], math_node.inputs[0])
                    links.new(math_node.outputs[0],           combine_xyz_node.inputs['X'])

                math_node.inputs[1].default_value = 1.0
                links.new(combine_xyz_node.outputs['Vector'], texture_node.inputs['Vector'])

        if tex_shading == -3 and vertex_color_node is not None:
            mix_color_node = nodes.new('ShaderNodeMixRGB')
            if tsp_dst_alpha == 1 or (tsp_src_alpha == 1 and tsp_dst_alpha == 4):
                mix_color_node.blend_type = 'LINEAR_LIGHT'
                mix_color_node.use_clamp  = True
            else:
                mix_color_node.blend_type = 'MULTIPLY'
            mix_color_node.inputs[0].default_value = 1.0
            mix_color_node.use_alpha               = False
            links.new(vertex_color_node.outputs['Color'], mix_color_node.inputs[1])
            links.new(texture_node.outputs['Color'],      mix_color_node.inputs[2])
            links.new(mix_color_node.outputs['Color'],    bsdf.inputs['Base Color'])

        elif tex_shading == -3:
            # No vertex-colour layer — fall back to texture only
            links.new(texture_node.outputs['Color'], bsdf.inputs['Base Color'])

        elif tex_shading == -1:
            # Flat/constant shading: texture drives both Base Color and Emission
            links.new(texture_node.outputs['Color'], bsdf.inputs['Emission Color']
                      if 'Emission Color' in bsdf.inputs else bsdf.inputs['Emission'])
            links.new(texture_node.outputs['Color'], bsdf.inputs['Base Color'])
            bsdf.inputs['Sheen Tint'].default_value = (1.0, 1.0, 1.0, 1.0)
            bsdf.inputs['Roughness'].default_value  = 1.0
            if 'Transmission' in bsdf.inputs:
                bsdf.inputs['Transmission'].default_value = 1.0

        elif tex_shading == -2 or is_bump_base or is_bump_overlay:
            # Bump map branch — entered whenever mesh is part of a bump pair,
            # regardless of TSP tex_shading enum (often 1/Modulate on real imports)
            if is_bump_base:
                tex_image.colorspace_settings.name = 'Non-Color'
                tex_image.alpha_mode = 'CHANNEL_PACKED'
                texture_node.label = 'Normal Map Texture'

                normal_map_node = nodes.new('ShaderNodeNormalMap')
                normal_map_node.space = 'TANGENT'
                normal_map_node.inputs['Strength'].default_value = 1.0

                links.new(texture_node.outputs['Color'],
                          normal_map_node.inputs['Color'])
                links.new(normal_map_node.outputs['Normal'],
                          bsdf.inputs['Normal'])

                if base_tex_image is not None:
                    base_tex_node = nodes.new('ShaderNodeTexImage')
                    base_tex_node.image = base_tex_image
                    base_tex_node.interpolation = \
                        "Closest" if tsp_filter == '0' else "Linear"
                    base_tex_node.label = 'Base Color Texture (Emission)'

                    if clamp == 0:
                        base_tex_node.extension = "REPEAT"
                    else:
                        base_tex_node.extension = "EXTEND"

                    if not (flip_uv == 0 and clamp == 0) and clamp != 3:
                        uv_node           = nodes.new('ShaderNodeUVMap')
                        separate_xyz_node = nodes.new('ShaderNodeSeparateXYZ')
                        combine_xyz_node  = nodes.new('ShaderNodeCombineXYZ')
                        math_node         = nodes.new('ShaderNodeMath')

                        links.new(uv_node.outputs['UV'],
                                  separate_xyz_node.inputs['Vector'])

                        if flip_uv == 1 and clamp == 0:
                            math_node.operation = 'PINGPONG'
                            links.new(separate_xyz_node.outputs['X'],
                                      combine_xyz_node.inputs['X'])
                            links.new(separate_xyz_node.outputs['Y'],
                                      math_node.inputs[0])
                            links.new(math_node.outputs[0],
                                      combine_xyz_node.inputs['Y'])
                        elif flip_uv == 2 and clamp == 0:
                            math_node.operation = 'PINGPONG'
                            links.new(separate_xyz_node.outputs['Y'],
                                      combine_xyz_node.inputs['Y'])
                            links.new(separate_xyz_node.outputs['X'],
                                      math_node.inputs[0])
                            links.new(math_node.outputs[0],
                                      combine_xyz_node.inputs['X'])
                        elif flip_uv == 3 and clamp == 0:
                            math_node.operation  = 'PINGPONG'
                            math_node2           = nodes.new('ShaderNodeMath')
                            math_node2.operation = 'PINGPONG'
                            math_node2.inputs[1].default_value = 1.0
                            links.new(separate_xyz_node.outputs['Y'],
                                      math_node2.inputs[0])
                            links.new(separate_xyz_node.outputs['X'],
                                      math_node.inputs[0])
                            links.new(math_node2.outputs[0],
                                      combine_xyz_node.inputs['Y'])
                            links.new(math_node.outputs[0],
                                      combine_xyz_node.inputs['X'])
                        elif flip_uv in (0, 1) and clamp == 1:
                            math_node.operation = 'WRAP'
                            math_node.inputs[2].default_value = 0.0
                            base_tex_node.interpolation = "Cubic"
                            links.new(separate_xyz_node.outputs['Y'],
                                      combine_xyz_node.inputs['Y'])
                            links.new(separate_xyz_node.outputs['X'],
                                      math_node.inputs[0])
                            links.new(math_node.outputs[0],
                                      combine_xyz_node.inputs['X'])
                        elif flip_uv in (0, 2) and clamp == 2:
                            math_node.operation = 'WRAP'
                            math_node.inputs[2].default_value = 0.0
                            base_tex_node.interpolation = "Cubic"
                            links.new(separate_xyz_node.outputs['X'],
                                      combine_xyz_node.inputs['X'])
                            links.new(separate_xyz_node.outputs['Y'],
                                      math_node.inputs[0])
                            links.new(math_node.outputs[0],
                                      combine_xyz_node.inputs['Y'])
                        elif flip_uv in (1, 3) and clamp == 2:
                            math_node.operation = 'PINGPONG'
                            links.new(separate_xyz_node.outputs['X'],
                                      combine_xyz_node.inputs['X'])
                            links.new(separate_xyz_node.outputs['Y'],
                                      math_node.inputs[0])
                            links.new(math_node.outputs[0],
                                      combine_xyz_node.inputs['Y'])
                        elif flip_uv in (2, 3) and clamp == 1:
                            math_node.operation = 'PINGPONG'
                            links.new(separate_xyz_node.outputs['Y'],
                                      combine_xyz_node.inputs['Y'])
                            links.new(separate_xyz_node.outputs['X'],
                                      math_node.inputs[0])
                            links.new(math_node.outputs[0],
                                      combine_xyz_node.inputs['X'])

                        math_node.inputs[1].default_value = 1.0
                        links.new(combine_xyz_node.outputs['Vector'],
                                  base_tex_node.inputs['Vector'])

                    # Base texture → Emission so it reads through the bump pass
                    # independent of scene lighting; Base Color stays on mesh colour
                    # so bump alpha composites correctly against the frame buffer.
                    emission_target = (bsdf.inputs['Emission Color']
                                       if 'Emission Color' in bsdf.inputs
                                       else bsdf.inputs.get('Emission'))
                    if emission_target is not None:
                        links.new(base_tex_node.outputs['Color'],
                                  emission_target)
                    if 'Emission Strength' in bsdf.inputs:
                        bsdf.inputs['Emission Strength'].default_value = 1.0
                    bsdf.inputs['Base Color'].default_value = mesh_color
                else:
                    bsdf.inputs['Base Color'].default_value = mesh_color

                _apply_blend_method(mat, 'BLEND')
                _rebuild_blend_nodes(mat, 4, 1)

            elif is_bump_overlay:
                # Pass 2: standard Modulate wiring; blend set by caller
                links.new(texture_node.outputs['Color'],
                          bsdf.inputs['Base Color'])
                for lk in [l for l in links
                           if l.to_socket == bsdf.inputs['Alpha']]:
                    links.remove(lk)
                links.new(texture_node.outputs['Alpha'],
                          bsdf.inputs['Alpha'])
                texture_node.label = 'Bump Texture (overlay pass)'

            else:
                # Legacy fallback — NormalMap wiring for pre-existing scenes
                normal_map_node    = nodes.new('ShaderNodeNormalMap')
                shader_to_rgb_node = nodes.new('ShaderNodeShaderToRGB')
                transparent_node   = nodes.new('ShaderNodeBsdfTransparent')

                links.new(texture_node.outputs['Color'],
                          normal_map_node.inputs['Color'])
                normal_map_node.inputs[0].default_value = 2.0
                links.new(normal_map_node.outputs['Normal'],
                          bsdf.inputs['Normal'])
                links.new(bsdf.outputs['BSDF'],
                          shader_to_rgb_node.inputs[0])
                links.new(shader_to_rgb_node.outputs['Color'],
                          transparent_node.inputs['Color'])
                links.new(transparent_node.outputs[0],
                          nodes['Material Output'].inputs['Surface'])
                bsdf.inputs[27].default_value = 0.2
                tex_image.colorspace_settings.name = 'Non-Color'

        else:
            links.new(texture_node.outputs['Color'], bsdf.inputs['Base Color'])

    elif mh_tex_id == -1:

        if tex_shading == -3 and vertex_color_node is not None:
            links.new(vertex_color_node.outputs['Color'], bsdf.inputs['Base Color'])

        elif tex_shading == -1:
            bsdf.inputs['Base Color'].default_value = mesh_color
            target_emission = (bsdf.inputs['Emission Color']
                               if 'Emission Color' in bsdf.inputs
                               else bsdf.inputs.get('Emission'))
            if target_emission is not None:
                target_emission.default_value = mesh_color
            if 'Emission Strength' in bsdf.inputs:
                bsdf.inputs['Emission Strength'].default_value = 1.0

        else:
            bsdf.inputs['Base Color'].default_value = mesh_color

    # Tex-shading modes 0-3 only; negative sentinels and bump pairs handled above
    if tex_shading >= 0 and not is_bump_base and not is_bump_overlay:
        _rebuild_tex_shading_nodes(mat, tex_shading, alpha_tex_op=alpha_tex_op)

    ambient_factor = float(m_tex_amb) if m_tex_amb is not None else 0.333329975605011
    ambient_factor = max(0.0, min(1.0, ambient_factor))

    # Bump base already wired base-mesh texture into Emission; don't overwrite
    if ambient_factor > 0.0 and not is_bump_base:
        base_color_input   = bsdf.inputs['Base Color']
        current_connection = next(
            (lk.from_socket for lk in tree.links if lk.to_socket == base_color_input),
            None
        )
        if current_connection is not None:
            target = (bsdf.inputs['Emission Color']
                      if 'Emission Color' in bsdf.inputs
                      else bsdf.inputs.get('Emission'))
            if target is not None:
                links.new(current_connection, target)
        else:
            target = (bsdf.inputs['Emission Color']
                      if 'Emission Color' in bsdf.inputs
                      else bsdf.inputs.get('Emission'))
            if target is not None:
                target.default_value = mesh_color

        if 'Emission Strength' in bsdf.inputs:
            bsdf.inputs['Emission Strength'].default_value = ambient_factor

    return texture_node


def _build_kwargs_from_object(obj):
    """Build kwargs for build_naomi_material() from obj's Naomi property groups.
    Infers tex_image and is_env_map from existing nodes.  Returns None if props missing."""
    p   = getattr(obj, 'naomi_param', None)
    tsp = getattr(obj, 'naomi_tsp',   None)
    if p is None or tsp is None:
        return None

    try:
        src_alpha   = int(tsp.srcAlpha)
        dst_alpha   = int(tsp.dstAlpha)
        list_type   = int(p.listType) if p.listType else 0
        mh_tex_id   = int(p.mh_texID)
        m_shad      = int(p.m_tex_shading)
        if m_shad == -3:
            tex_shading = -3          # vertex color — never overridden by texShading
        elif mh_tex_id >= 0:
            tex_shading = int(tsp.texShading)
        else:
            tex_shading = m_shad
        flip_uv     = int(tsp.uvFlip)
        clamp       = int(tsp.uvClamp)
    except (ValueError, TypeError):
        return None

    mesh_color        = tuple(p.meshColor)
    mesh_offset_color = tuple(p.meshOffsetColor)
    alpha_tex_op      = tsp.alphaTexOp
    m_tex_amb         = float(p.m_ambient_light)

    # Infer backface culling from the current material (preserve whatever is set)
    mat = obj.material_slots[0].material if obj.material_slots else None
    use_backface_culling = mat.use_backface_culling if mat else True

    # is_env_map read directly from property so toggling the flag rebuilds immediately
    tex_image  = None
    is_env_map = bool(p.naomi_flag_env_map)
    if mat and mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.bl_idname == 'ShaderNodeTexImage':
                tex_image = node.image
                break

    vcol_layer = p.vcol_layer_name if p.vcol_layer_name else None

    # Bump-pair flags
    is_bump_base    = _is_bump_mesh(obj)
    is_bump_overlay = _is_bump_partner(obj)

    # For the bump mesh, resolve the base mesh's color texture so the node
    # builder can add it alongside the normal map texture.
    base_tex_image = None
    if is_bump_base:
        base_obj = _get_bump_partner(obj)
        if base_obj is not None:
            base_tex_image = _snapshot_tex_image(base_obj)

    return dict(
        mesh_color           = mesh_color,
        mesh_offset_color    = mesh_offset_color,
        tex_shading          = tex_shading,
        tsp_src_alpha        = src_alpha,
        tsp_dst_alpha        = dst_alpha,
        list_type            = list_type,
        flip_uv              = flip_uv,
        clamp                = clamp,
        alpha_tex_op         = alpha_tex_op,
        use_backface_culling = use_backface_culling,
        mh_tex_id            = mh_tex_id,
        tex_image            = tex_image,
        is_env_map           = is_env_map,
        vertex_col_layer     = vcol_layer,
        m_tex_amb            = m_tex_amb,
        tsp_filter           = tsp.filter,
        is_bump_base         = is_bump_base,
        is_bump_overlay      = is_bump_overlay,
        base_tex_image       = base_tex_image,
    )


# ---------------------------------------------------------------------------
# Property-update callbacks — all funnel through build_naomi_material
# ---------------------------------------------------------------------------

def _update_blend_mode(self, context): _full_rebuild(getattr(bpy.context, "active_object", None))
def _update_tex_shading(self, context):  _full_rebuild(getattr(bpy.context, "active_object", None))
def _update_uv(self, context):           _full_rebuild(getattr(bpy.context, "active_object", None))


def _update_filter(self, context):
    """Point Sampled ('0') → Closest; anything else → Linear."""
    obj = getattr(bpy.context, "active_object", None)
    if obj is None:
        return
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None or not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.bl_idname == 'ShaderNodeTexImage':
                node.interpolation = "Closest" if self.filter == '0' else "Linear"


importlib.reload(NLi)
importlib.reload(NLe)


_ADDON_DIR = os.path.dirname(os.path.abspath(__file__))

_NlcvOptions = NLe.NlcvOptions
_NlcvError   = NLe.NlcvError

_NLCV_ERR_CONVERT  = -3  # touch_count overflow / strip failure
_NLCV_ERR_OUTPUT   = -4  # binary output failure
_NLCV_ERR_INTERNAL = -5  # unexpected internal error
def import_nl(self, context, filepath: str, bCleanup: bool, bArchive: bool, fScaling: float, bDebug: bool, bOrientation, bNegScale_X: bool, bWeld: bool = False, bImportNormals: bool = True, bForwardAxis: str = '-Y', bUpAxis: str = '+Z'):

    ret = False

    if bArchive:
        ret = NLi.main_function_import_archive(self, filepath=filepath, scaling=fScaling, debug=bDebug, orientation=bOrientation, NegScale_X=bNegScale_X, weld=bWeld, import_normals=bImportNormals, forward_axis=bForwardAxis, up_axis=bUpAxis)
    else:
        ret = NLi.main_function_import_file(self, filepath=filepath, scaling=fScaling, debug=bDebug, orientation=bOrientation, NegScale_X=bNegScale_X, weld=bWeld, import_normals=bImportNormals, forward_axis=bForwardAxis, up_axis=bUpAxis)

    return ret

class ImportNL(bpy.types.Operator, ImportHelper):
    """Import a NaomiLib file"""

    bl_idname = "import_scene.naomilib"
    bl_label = "Import NaomiLib"

    filename_ext = ".bin"

    load_directory: bpy.props.BoolProperty(
        name="Import directory",
        description="Import all .bin files in the same folder",
        default=False,
    )

    filter_glob: StringProperty(
        default="*.bin;*.lz_p",
        options={'HIDDEN'},
        maxlen=255,
    )

    files: bpy.props.CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    setting_cleanup: BoolProperty(
        name="Clear scene",
        description="Remove all objects and collections before import",
        default=True,
    )

    setting_scaling: FloatProperty(
        name="Scale",
        description="Uniform scale applied to imported objects",
        default=1,
        min=0,
        max=1000,
    )

    setting_weld: BoolProperty(
        name="Weld vertices",
        description="Merge strip-boundary duplicate vertices. Forces normal recalculation",
        default=False,
    )

    setting_import_normals: BoolProperty(
        name="Import normals",
        description="Store hardware normals from the binary. When off, normals are recalculated automatically by Blender",
        default=True,
    )

    setting_debug: BoolProperty(
        name="Debug output",
        description="Print strip and vertex info to the log",
        default=False,
    )

    forward_axis: bpy.props.EnumProperty(
        name="Forward",
        description="Axis pointing into the screen (-Z in Naomi space)",
        items=[
            ('+X', "X Forward",  ""),
            ('-X', "-X Forward", ""),
            ('+Y', "Y Forward",  ""),
            ('-Y', "-Y Forward", "(default — matches standard NaomiLib export)"),
            ('+Z', "Z Forward",  ""),
            ('-Z', "-Z Forward", ""),
        ],
        default='-Y',
    )
    up_axis: bpy.props.EnumProperty(
        name="Up",
        description="Axis pointing up (+Y in Naomi space)",
        items=[
            ('+X', "X Up",  ""),
            ('-X', "-X Up", ""),
            ('+Y', "Y Up",  ""),
            ('-Y', "-Y Up", ""),
            ('+Z', "Z Up",  "(default — matches standard NaomiLib export)"),
            ('-Z', "-Z Up", ""),
        ],
        default='+Z',
    )
    # Legacy: kept so saved presets don't error
    orientation: bpy.props.EnumProperty(
        name="Orientation (legacy)", options={'HIDDEN'},
        items=[('X_UP',"X-Up",""),('Y_UP',"Y-Up",""),('Z_UP',"Z-Up","")],
        default='Z_UP')
    negative_x_scale_enabled: BoolProperty(
        name="Enable Negative X Scale (legacy)", default=True, options={'HIDDEN'})

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.separator()
        layout.prop(self, "setting_scaling")
        layout.prop(self, "forward_axis")
        layout.prop(self, "up_axis")

        layout.separator()

        header, body = layout.panel("options", default_closed=False)
        header.label(text="Options")
        if body:
            body.use_property_split = True
            body.use_property_decorate = False
            body.prop(self, "setting_cleanup")
            body.prop(self, "load_directory")
            body.prop(self, "setting_weld")
            body.prop(self, "setting_import_normals")
            body.separator()
            body.prop(self, "setting_debug")

    def execute(self, context):
        _do_weld   = self.setting_weld
        _do_normals = self.setting_import_normals

        # Map (forward_axis, up_axis) → legacy (orientation, NegScale_X) for parse_nl.
        _IMPORT_MAP = {
            ('-Y', '+Z'): ('Z_UP', True),
            ('-Z', '-X'): ('X_UP', True),
            ('-Z', '+Y'): ('Y_UP', False),
        }
        _fwd = self.forward_axis
        _up  = self.up_axis
        _pair = _IMPORT_MAP.get((_fwd, _up))
        if _pair is None:
            self.report({'WARNING'},
                f"Axis combination {_fwd} Forward / {_up} Up has no exact "
                f"importer equivalent. Using default (-Y Forward / Z Up).")
            _orient, _neg_x = 'Z_UP', True
        else:
            _orient, _neg_x = _pair

        if self.load_directory:
            if self.setting_cleanup:
                NLi.cleanup()
            folder_path = os.path.dirname(self.filepath)
            for filename in os.listdir(folder_path):
                if filename.endswith(".bin") or filename.lower().endswith(".lz_p"):
                    file_path = os.path.join(folder_path, filename)
                    _is_archive = filename.lower().endswith('.lz_p')
                    import_nl(self, context, filepath=file_path, bCleanup=self.setting_cleanup,
                              bArchive=_is_archive, fScaling=self.setting_scaling, bDebug=self.setting_debug,
                              bOrientation=_orient, bNegScale_X=_neg_x, bWeld=_do_weld,
                              bImportNormals=_do_normals, bForwardAxis=_fwd, bUpAxis=_up)
        else:
            # Build file list — multi-select or single file
            folder = os.path.dirname(self.filepath)
            if self.files:
                file_paths = [os.path.join(folder, f.name) for f in self.files
                              if f.name.lower().endswith(('.bin', '.lz_p'))]
            else:
                file_paths = [self.filepath] if os.path.isfile(self.filepath) else []

            if not file_paths:
                self.report({'ERROR'}, "No valid .bin or .lz_p files selected")
                return {'CANCELLED'}

            if self.setting_cleanup:
                NLi.cleanup()

            _last_col = None
            for file_path in file_paths:
                _cols_before = set(bpy.data.collections)
                _is_archive = file_path.lower().endswith('.lz_p')
                import_nl(self, context, filepath=file_path, bCleanup=False,
                          bArchive=_is_archive, fScaling=self.setting_scaling, bDebug=self.setting_debug,
                          bOrientation=_orient, bNegScale_X=_neg_x, bWeld=_do_weld,
                          bImportNormals=_do_normals, bForwardAxis=_fwd, bUpAxis=_up)
                _new_cols = [c for c in bpy.data.collections if c not in _cols_before]
                if _new_cols:
                    _last_col = _new_cols[-1]

            # Set active collection to the last imported one
            if _last_col is not None:
                for lc in context.view_layer.layer_collection.children:
                    if lc.collection is _last_col:
                        context.view_layer.active_layer_collection = lc
                        break

        return {'FINISHED'}


class Naomi_GlobalParam_0(bpy.types.PropertyGroup):
    objFormat : bpy.props.EnumProperty(
        description="Object mode",
        name = "Index Mode",
        items = [('0', "Beta Index",""),
                 ('1', "Super Index",""),
        ],
        default = '1',
    )

class Naomi_GlobalParam_1(bpy.types.PropertyGroup):
    skp1stSrcOp : bpy.props.BoolProperty(
        description="Skip first light calc",
        name = "Skip 1st Light Source",
    )
    envMap : bpy.props.BoolProperty(
        description="Spherical env map",
        name = "Environment Mapping",
    )
    pltTex : bpy.props.BoolProperty(
        description="Palettized texture",
        name = "Palette Texture",
    )
    bumpMap : bpy.props.BoolProperty(
        description="Bump map",
        name = "Bump Map",
    )

class Naomi_Centroid_Data(bpy.types.PropertyGroup):
    # Sentinel: True if this collection has Naomi data assigned (via import or manually)
    naomi_assigned: bpy.props.BoolProperty(name="Naomi Data Assigned", default=False)
    centroid_x: bpy.props.FloatProperty(name="Centroid X", default=0.0)
    centroid_y: bpy.props.FloatProperty(name="Centroid Y", default=0.0)
    centroid_z: bpy.props.FloatProperty(name="Centroid Z", default=0.0)
    collection_bound_radius: bpy.props.FloatProperty(name="Bound Radius", default=1.0, min=0.0)
    source_filepath: bpy.props.StringProperty(name="Source File Path")
    source_crc32: bpy.props.StringProperty(name="Source CRC32")
    import_forward_axis: bpy.props.StringProperty(name="Import Forward Axis", default="-Y")
    import_up_axis: bpy.props.StringProperty(name="Import Up Axis", default="+Z")

class Naomi_Import_Meta(bpy.types.PropertyGroup):
    source_filepath: bpy.props.StringProperty(name="Source File Path")
    source_crc32: bpy.props.StringProperty(name="Source CRC32")
    import_forward_axis: bpy.props.StringProperty(name="Import Forward Axis", default="-Y")
    import_up_axis: bpy.props.StringProperty(name="Import Up Axis", default="+Z")



# ---------------------------------------------------------------------------
# Quick-Settings override helpers
# ---------------------------------------------------------------------------

# Maps each quick-setting property name to the corresponding naomi_tsp field name
_QS_TSP_MAP = {
    'qs_fog':          'fogOp',
    'qs_tex_alpha':    'alphaTexOp',
    'qs_color_clamp':  'colorClamp',
    'qs_uv_clamp':     'uvClamp',
    'qs_filter':       'filter',
    'qs_src_alpha':    'srcAlpha',
    'qs_dst_alpha':    'dstAlpha',
    'qs_tex_shading':  'texShading',
}

def _qs_update(qs_prop_name):
    """Return an update callback for a quick-setting override property."""
    tsp_field = _QS_TSP_MAP[qs_prop_name]
    def _cb(self, context):
        obj = getattr(bpy.context, 'active_object', None)
        if obj is None:
            return
        tsp = getattr(obj, 'naomi_tsp', None)
        if tsp is None:
            return
        val = getattr(self, qs_prop_name)
        if val != '-1':
            # Forced: write chosen value straight into the TSP field so both
            # Quick Settings and Advanced always show the same value.
            setattr(tsp, tsp_field, val)
            _full_rebuild(obj)
        else:
            # AUTO: restore the TSP field to the preset default, then rebuild.
            _qs_reset_to_preset_default(obj, tsp_field)
            _full_rebuild(obj)
    return _cb

def _qs_reset_to_preset_default(obj, tsp_field):
    """Reset a single TSP field to what the active preset would set it to."""
    p   = getattr(obj, 'naomi_param', None)
    tsp = getattr(obj, 'naomi_tsp',   None)
    if p is None or tsp is None:
        return

    has_tex = int(p.mh_texID) >= 0

    # Derive the active preset bucket from m_shad_type / flags
    shad = p.m_shad_type
    if p.naomi_flag_bump:
        preset = 'bump'
    elif shad == '-3':
        preset = 'vertex'
    elif shad == '-1':
        preset = 'flat'
    else:
        preset = 'lambert'   # covers env_map and palette (same TSP defaults as lambert)

    # Preset default tables for our 8 fields.
    # lambert / env_map / palette / bump / flat / vertex  — all share most values.
    DEFAULTS = {
        #            lambert/env/pal  flat     vertex   (bump same as lambert)
        'fogOp':      {'lambert': '2', 'flat': '2', 'vertex': '2', 'bump': '2'},
        'alphaTexOp': {'lambert': '1', 'flat': '1', 'vertex': '1', 'bump': '1'},
        'colorClamp': {'lambert': '0', 'flat': '0', 'vertex': '0', 'bump': '0'},
        'uvClamp':    {'lambert': '0', 'flat': '0', 'vertex': '0', 'bump': '0'},
        'filter':     {'lambert': '1' if has_tex else '0',
                       'flat':    '1' if has_tex else '0',
                       'vertex':  '1' if has_tex else '0',
                       'bump':    '1' if has_tex else '0'},
        'srcAlpha':   {'lambert': '1', 'flat': '1', 'vertex': '1', 'bump': '1'},
        'dstAlpha':   {'lambert': '0', 'flat': '0', 'vertex': '0', 'bump': '0'},
        'texShading': {'lambert': '1', 'flat': '1', 'vertex': '1', 'bump': '1'},
    }
    default_val = DEFAULTS.get(tsp_field, {}).get(preset, '0')
    setattr(tsp, tsp_field, default_val)


def _full_rebuild(obj):
    """Rebuild all material nodes on obj from its Naomi properties."""
    if obj is None or obj.type != 'MESH' or not obj.material_slots:
        return
    kwargs = _build_kwargs_from_object(obj)
    if kwargs is None:
        return
    global _material_rebuild_in_progress
    _material_rebuild_in_progress = True
    try:
        for slot in obj.material_slots:
            mat = slot.material
            if mat:
                build_naomi_material(mat=mat, **kwargs)
    finally:
        _material_rebuild_in_progress = False
    area = getattr(bpy.context, "area", None)
    if area:
        area.tag_redraw()


def update_mesh_ambient(self, context): _full_rebuild(getattr(bpy.context, "active_object", None))


def update_mesh_color(self, context):
    obj = getattr(bpy.context, "active_object", None)
    # Also keep the viewport / material diffuse color in sync (cheap, no node work).
    if obj is not None and obj.material_slots:
        mat = obj.material_slots[0].material
        if mat:
            mat.diffuse_color = self.meshColor
        if hasattr(obj, "color") and len(obj.color) >= 4:
            obj.color = self.meshColor
    _full_rebuild(obj)


def update_mesh_offsetcolor(self, context): _full_rebuild(getattr(bpy.context, "active_object", None))


def _sync_collection_flags(obj):
    """Drive gp1.bumpMap / gp1.envMap from mesh flags across the collection."""
    col = _get_col_for_obj(obj)
    if col is None:
        return
    gp1 = col.gp1
    any_bump = False
    any_env  = False
    for o in col.objects:
        if not hasattr(o, "naomi_param"):
            continue
        p = o.naomi_param
        if not p.naomi_assigned:
            continue
        if p.naomi_flag_bump:
            any_bump = True
        if p.naomi_flag_env_map:
            any_env = True
    gp1.bumpMap = any_bump
    gp1.envMap  = any_env


def _update_flag_bump(self, context):
    obj = getattr(bpy.context, "active_object", None)
    if obj:
        _sync_collection_flags(obj)


def _update_flag_env_map(self, context):
    # Also triggers full rebuild so env-map UV wiring applies immediately
    obj = getattr(bpy.context, "active_object", None)
    if obj:
        _sync_collection_flags(obj)
        _full_rebuild(obj)


def _update_flag_two_sided(self, context):
    # 1 = Cull if Small (two-sided), 2 = Cull if Negative (one-sided)
    obj = getattr(bpy.context, "active_object", None)
    if obj is None:
        return
    it = getattr(obj, "naomi_isp_tsp", None)
    if it is None:
        return
    p  = getattr(obj, "naomi_param", None)
    two_sided = p.naomi_flag_two_sided if p else False
    # 1 = Cull if Small (NAOMI two-sided), 2 = Cull if Negative (one-sided)
    it.culling = '1' if two_sided else '2'
    # Mirror to Blender material so the viewport shows it
    if obj.data and obj.data.materials:
        blmat = obj.data.materials[0]
        if blmat:
            blmat.use_backface_culling = not two_sided


def _apply_texture_params(obj, has_texture: bool):
    """Apply Naomi parameter changes when a texture is added or removed."""
    if obj is None:
        return
    p   = getattr(obj, "naomi_param",   None)
    it  = getattr(obj, "naomi_isp_tsp", None)
    t   = getattr(obj, "naomi_tsp",     None)
    tc  = getattr(obj, "naomi_texCtrl", None)
    if p is None or it is None or t is None:
        return

    if has_texture:
        # Step 2 — uvDataSize must switch to 32-bit
        p.uvDataSize  = '0'
        it.uvDataSize = '0'
        # Ensure textureUsage is enabled on both groups
        p.textureUsage  = '1'
        it.textureUsage = '1'
        # Filter: promote from Point-only to Bilinear as a sensible default
        if t.filter == '0':
            t.filter = '1'
        # texShading: if currently Modulate (1) keep it; translucent materials
        # (listType==2) should use Modulate Alpha (3).
        if int(p.listType) == 2 and t.texShading == '1':
            t.texShading  = '3'
            t.alphaTexOp  = '0'
        # Opaque texture default: alphaTexOp=Ignore, texShading=Modulate
        elif int(p.listType) == 0 or int(p.listType) == 4:
            if t.texShading not in ('0', '1'):
                t.texShading = '1'
    else:
        # Step 2 reversed — back to no-texture defaults
        p.uvDataSize    = '1'
        it.uvDataSize   = '1'
        p.textureUsage  = '1'   # white-tex substitution
        it.textureUsage = '1'
        t.filter        = '0'   # Point (hardware ignores filter without tex)
        t.texShading    = '1'   # Modulate


_PX_KEY_TO_PIXEL_FORMAT = {
    '1555':   '0',   # ARGB1555 — 1-bit cutout alpha
    '565':    '1',   # RGB565   — fully opaque
    '4444':   '2',   # ARGB4444 — 4-bit smooth alpha
    'yuv422': '3',   # YUV422   — video
    'bump':   '4',   # Bump Map
    'p4bpp':  '5',   # 4-BPP Palette
    'p8bpp':  '6',   # 8-BPP Palette
}

# tex_mode keys that require Twiddled scan order (scanOrder='0')
_TWIDDLED_TEX_MODES = {'tw', 'vq', 'svq', 'twal', 'pal4', 'pal8'}
# tex_mode keys that are VQ-compressed
_VQ_TEX_MODES       = {'vq', 'svq'}
# tex_mode keys that include built-in mipmaps
_MM_TEX_MODES       = {'twal'}


def _apply_texctrl_from_slot(obj, item):
    """Sync naomi_texCtrl and alpha/list-type params from a TextureSlotItem after encoding."""
    if obj is None or item is None or item.is_empty:
        return

    tc = getattr(obj, 'naomi_texCtrl', None)
    p  = getattr(obj, 'naomi_param',   None)
    it = getattr(obj, 'naomi_isp_tsp', None)
    t  = getattr(obj, 'naomi_tsp',     None)
    if tc is None or p is None or it is None or t is None:
        return

    px  = item.px_mode
    tex = item.tex_mode

    # Bump mesh: pixelFormat fixed at PIX_BUMP_MAP (4), not overwritten by slot px_mode
    if not _is_bump_mesh(obj):
        pf = _PX_KEY_TO_PIXEL_FORMAT.get(px)
        if pf is not None:
            tc.pixelFormat = pf

    tc.scanOrder    = '0' if tex in _TWIDDLED_TEX_MODES else '1'
    tc.vqCompressed = tex in _VQ_TEX_MODES
    tc.mipMapped    = item.use_mips or (tex in _MM_TEX_MODES)

    # texUSize / texVSize from PVR dimensions: enum index = log2(dim) - 3
    import math as _math

    w, h = item.tex_width, item.tex_height

    # Cache miss: dims not stored yet — try PVR file first, then source image.
    if w == 0 or h == 0:
        col, tm = _get_col_tm(obj)
        folder = bpy.path.abspath(tm.tex_folder) if (tm and tm.tex_folder) else None
        if folder:
            pvr_path = os.path.join(folder, f"TexID_{item.tex_id:03d}.PVR")
            if os.path.isfile(pvr_path):
                try:
                    with open(pvr_path, 'rb') as _f:
                        _pvr_data = _f.read(0x20)
                    w, h = _pvr_dims_from_bytes(_pvr_data)
                except Exception:
                    pass
        if (w == 0 or h == 0) and item.filepath:
            fp = bpy.path.abspath(item.filepath)
            if os.path.isfile(fp):
                try:
                    _tmp_name = "__nl_dims_tmp__"
                    if _tmp_name in bpy.data.images:
                        bpy.data.images.remove(bpy.data.images[_tmp_name])
                    _img = bpy.data.images.load(fp, check_existing=False)
                    _img.name = _tmp_name
                    w, h = _img.size[0], _img.size[1]
                    bpy.data.images.remove(_img)
                except Exception:
                    pass
        # Cache for future calls
        if w > 0:
            item.tex_width  = w
        if h > 0:
            item.tex_height = h

    for dim_attr, size_val in (('texUSize', w), ('texVSize', h)):
        if size_val > 0:
            try:
                idx = int(_math.log2(size_val)) - 3
                if 0 <= idx <= 7:
                    setattr(t, dim_attr, str(idx))
            except (ValueError, TypeError):
                pass

    # uvDataSize: textured meshes always use 32-bit UV
    if int(getattr(p, 'mh_texID', -1)) >= 0 or item.tex_id >= 0:
        p.uvDataSize  = '0'
        it.uvDataSize = '0'

    # Only cascade alpha params when this texture is actually assigned
    if int(getattr(p, 'mh_texID', -1)) != item.tex_id:
        return

    # Alpha/transparency cascade — skip bump pairs (preset already fixed params).
    if _is_bump_mesh(obj) or _is_bump_partner(obj):
        return

    if px == '4444':
        # Semi-transparent — ARGB4444
        p.listType      = '2'
        t.alphaOp       = '1'
        t.alphaTexOp    = '0'   # Use alpha channel
        t.texShading    = '3'   # Modulate Alpha
        t.srcAlpha      = '4'   # SRC Alpha
        t.dstAlpha      = '5'   # Inv SRC Alpha
    elif px == '1555':
        # Punch-through — ARGB1555, 1-bit cutout
        p.listType      = '4'
        t.alphaOp       = '0'
        t.alphaTexOp    = '0'   # Use alpha channel
        t.texShading    = '1'   # Modulate
        t.srcAlpha      = '1'   # One
        t.dstAlpha      = '0'   # Zero
    else:
        # Opaque (565, yuv422, palette …)
        p.listType      = '0'
        t.alphaOp       = '0'
        t.alphaTexOp    = '1'   # Ignore
        t.texShading    = '1'   # Modulate
        t.srcAlpha      = '1'   # One
        t.dstAlpha      = '0'   # Zero


def update_texture(self, context):
    """Full rebuild on texture-ID change — resolves image from disk then rebuilds nodes."""
    global _material_rebuild_in_progress

    # Guard: caller holds the flag for atomic multi-step assignment
    if _material_rebuild_in_progress:
        return

    # Use id_data to target the object whose naomi_param was modified,
    # not bpy.context.active_object (may differ during programmatic assignment)
    obj = getattr(self, "id_data", None)
    if obj is None:
        obj = getattr(bpy.context, "active_object", None)
    if obj is None or obj.type != 'MESH' or not obj.material_slots:
        return

    mh_tex_id = int(self.mh_texID)

    # Sync alpha/listType params BEFORE snapshotting kwargs so build gets correct values
    if mh_tex_id >= 0:
        _, tm_pre = _get_col_tm(obj)
        if tm_pre is not None:
            for _item in tm_pre.tex_list:
                if _item.tex_id == mh_tex_id and not _item.is_empty:
                    _apply_texctrl_from_slot(obj, _item)
                    break

    kwargs = _build_kwargs_from_object(obj)
    if kwargs is None:
        return

    kwargs['mh_tex_id'] = mh_tex_id

    # Resolve the texture image when a valid ID is requested.
    if mh_tex_id >= 0:
        tex_image = None
        texFileName = f'TexID_{mh_tex_id:03d}'
        textureFileFormats = tuple(e.lstrip('.') for e in _TEX_IMAGE_EXTS)

        texDir = _get_tex_folder(obj) or None

        if texDir:
            for fmt in textureFileFormats:
                candidate = os.path.normpath(os.path.join(texDir, f'{texFileName}.{fmt}'))
                if os.path.exists(candidate):
                    for img in bpy.data.images:
                        if os.path.normcase(bpy.path.abspath(img.filepath)) == os.path.normcase(candidate):
                            tex_image = img
                            break
                    if tex_image is None:
                        try:
                            tex_image = bpy.data.images.load(candidate, check_existing=True)
                        except Exception as e:
                            print(f"[NaomiLib] Failed to load texture {candidate}: {e}")
                    break

        kwargs['tex_image'] = tex_image
    else:
        # mh_tex_id == -1 → no texture; clear the image reference too.
        kwargs['tex_image'] = None

    _material_rebuild_in_progress = True
    try:
        for slot in obj.material_slots:
            mat = slot.material
            if mat:
                build_naomi_material(mat=mat, **kwargs)

        # Rebuild bump partner so both sides stay in sync
        partner = _get_bump_partner(obj)
        if partner is not None and partner.type == 'MESH' and partner.material_slots:
            partner_kwargs = _build_kwargs_from_object(partner)
            if partner_kwargs is not None:
                for pslot in partner.material_slots:
                    pmat = pslot.material
                    if pmat:
                        build_naomi_material(mat=pmat, **partner_kwargs)
    finally:
        _material_rebuild_in_progress = False

    area = getattr(bpy.context, "area", None)
    if area:
        area.tag_redraw()


_TEX_MODE_ITEMS = [
    ('tw',   'TW',   'Twiddled'),
    ('twre', 'TWRE', 'Twiddled Rectangle'),
    ('vq',   'VQ',   'VQ (Vector Quantised)'),
    ('pal4', 'PAL4', 'Palette 4bpp'),
    ('pal8', 'PAL8', 'Palette 8bpp'),
    ('re',   'RE',   'Rectangle'),
    ('st',   'ST',   'Stride'),
    ('bmp',  'BMP',  'Bitmap'),
    ('svq',  'SVQ',  'Small VQ'),
    ('twal', 'TWAL', 'Twiddled Alias + Mips'),
]

_PX_MODE_ITEMS = [
    ('1555',   '1555',   'ARGB 1-5-5-5'),
    ('565',    '565',    'RGB 5-6-5'),
    ('4444',   '4444',   'ARGB 4-4-4-4'),
    ('yuv422', 'YUV422', 'YUV 4:2:2'),
    ('bump',   'BUMP',   'Bump map'),
    ('555',    '555',    'RGB 5-5-5'),
    ('yuv420', 'YUV420', 'YUV 4:2:0'),
    ('8888',   '8888',   'ARGB 8-8-8-8'),
    ('p4bpp',  'PAL4',   'Palette 4bpp index'),
    ('p8bpp',  'PAL8',   'Palette 8bpp index'),
]

#              1555 565 4444 yuv422 bump 555 yuv420 8888 p4bpp p8bpp
_COMPAT_MATRIX = {
    'tw':   [1, 1, 1, 1, 1, 0, 0, 0, 0, 0],
    'twre': [1, 1, 1, 1, 1, 0, 0, 0, 0, 0],
    'vq':   [1, 1, 1, 1, 1, 0, 0, 0, 0, 0],
    'pal4': [1, 1, 1, 0, 0, 0, 0, 1, 1, 0],
    'pal8': [1, 1, 1, 0, 0, 0, 0, 1, 0, 1],
    're':   [1, 1, 1, 1, 0, 0, 1, 0, 0, 0],
    'st':   [1, 1, 1, 1, 0, 0, 0, 0, 0, 0],
    'bmp':  [0, 0, 0, 0, 0, 0, 0, 1, 0, 0],
    'svq':  [1, 1, 1, 1, 1, 0, 0, 0, 0, 0],
    'twal': [1, 1, 1, 1, 1, 0, 0, 0, 0, 0],
}

# PVR header byte → enum key
_PVR_TEX_BYTE_TO_KEY = {
    1: 'tw',   2: 'tw',    3: 'vq',   4: 'vq',
    5: 'pal4', 6: 'pal4',  7: 'pal8', 8: 'pal8',
    9: 're',  10: 're',   11: 'st',  12: 'st',
    13: 'twre', 14: 'bmp', 15: 'bmp',
    16: 'svq', 17: 'svq', 18: 'twal',
}
_PVR_PX_BYTE_TO_KEY = {
    0: '1555', 1: '565',    2: '4444',   3: 'yuv422',
    4: 'bump', 5: '555',    6: 'yuv420', 7: '8888',
    8: 'p4bpp', 9: 'p8bpp',
}
# tex_bytes whose value means the texture includes mipmaps (even-numbered entries
# in _PVR_TEX_BYTE_TO_KEY share the key with the mip variant)
_MM_TEX_BYTES = {2, 4, 6, 8, 10, 12, 15, 17, 18}


def _valid_px_items_for(tex_key):
    row = _COMPAT_MATRIX.get(tex_key, [1] * 10)
    return [item for item, valid in zip(_PX_MODE_ITEMS, row) if valid]


def _on_tex_mode_update(self, context):
    """When tex_mode changes, if current px_mode is invalid, snap to first valid one."""
    valid = _valid_px_items_for(self.tex_mode)
    valid_keys = [item[0] for item in valid]
    if self.px_mode not in valid_keys:
        self.px_mode = valid_keys[0]


def _px_items_callback(self, context):
    """Dynamic EnumProperty items — filters px_mode to valid combos for tex_mode."""
    return _valid_px_items_for(self.tex_mode)


def _infer_format_from_image(filepath):
    """Infer (tex_key, px_key) from image analysis, mirroring PyPVR auto_format logic.
    Returns (tex_key, px_key) or None on failure."""
    if not filepath or not os.path.isfile(filepath):
        return None
    try:
        import numpy as _np
        name = "__pvr_infer_tmp__"
        if name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[name])
        img = bpy.data.images.load(os.path.realpath(filepath))
        img.name = name
        try:
            img.colorspace_settings.name = 'Non-Color'
        except TypeError:
            pass
        w, h = img.size
        if w == 0 or h == 0:
            bpy.data.images.remove(img)
            return None
        px = _np.empty(w * h * 4, dtype=_np.float32)
        img.pixels.foreach_get(px)
        bpy.data.images.remove(img)
        # alpha channel is index 3 in each RGBA group
        alpha = px[3::4]

        def _is_pow2(n):
            return n > 0 and (n & (n - 1)) == 0

        is_square    = _is_pow2(w) and _is_pow2(h) and w == h
        is_rectangle = _is_pow2(w) and _is_pow2(h) and w != h

        # tex_mode — prefer twiddled, never stride/palette/yuv420
        tex_key = 'tw' if (is_square or not is_rectangle) else 'twre'

        # px_mode — inspect alpha channel
        min_a = float(alpha.min())
        if min_a >= (254.5 / 255.0):   # fully opaque
            px_key = '565'
        else:
            unique_a = set(_np.round(alpha * 255).astype(_np.uint8).tolist())
            px_key = '1555' if unique_a <= {0, 255} else '4444'

        return (tex_key, px_key)
    except Exception:
        return None


def _read_pvr_header(folder, tex_id):
    """Return (tex_key, px_key, has_mips) by reading TexID_NNN.PVR header, or None."""
    import struct, io as _io
    pvr_path = os.path.join(folder, f"TexID_{tex_id:03d}.PVR")
    if not os.path.isfile(pvr_path):
        return None
    try:
        with open(pvr_path, 'rb') as f:
            data = f.read(0x20)
        offset = data.find(b"PVRT")
        if offset == -1:
            return None
        buf = _io.BytesIO(data)
        buf.seek(offset + 0x8)
        px_byte  = struct.unpack('B', buf.read(1))[0]
        tex_byte = struct.unpack('B', buf.read(1))[0]
        tex_key = _PVR_TEX_BYTE_TO_KEY.get(tex_byte)
        px_key  = _PVR_PX_BYTE_TO_KEY.get(px_byte)
        has_mips = tex_byte in _MM_TEX_BYTES
        if tex_key and px_key:
            return (tex_key, px_key, has_mips)
    except Exception:
        pass
    return None


class Naomi_TextureSlotItem(bpy.types.PropertyGroup):
    tex_id:       bpy.props.IntProperty(name="Texture ID", default=-1)
    filepath:     bpy.props.StringProperty(name="File Path", default="")
    is_empty:     bpy.props.BoolProperty(name="Empty Slot", default=False)
    pvr_detected: bpy.props.BoolProperty(name="From PVR", default=False,
                      description="Auto-read from .PVR header")
    tex_mode: bpy.props.EnumProperty(
        name="Tex Mode",
        description="Texture format",
        items=_TEX_MODE_ITEMS,
        default='tw',
        update=_on_tex_mode_update,
    )
    px_mode: bpy.props.EnumProperty(
        name="Px Mode",
        description="Pixel format",
        items=_px_items_callback,
    )
    use_mips: bpy.props.BoolProperty(
        name="Mipmaps",
        description="Generate mipmaps on encode",
        default=False,
    )
    tex_width:  bpy.props.IntProperty(name="Tex Width",  default=0, min=0)
    tex_height: bpy.props.IntProperty(name="Tex Height", default=0, min=0)


class Naomi_Collection_TM(bpy.types.PropertyGroup):
    """Texture Manager state stored at collection level — shared by all objects in the collection."""
    tex_folder:     bpy.props.StringProperty(
        name="Texture Folder",
        description="Texture folder",
        subtype='DIR_PATH', default="",
    )
    tex_list:       bpy.props.CollectionProperty(type=Naomi_TextureSlotItem)
    tex_list_index: bpy.props.IntProperty(name="Selected Texture", default=0)
    tex_scroll:     bpy.props.IntProperty(name="List Scroll Offset", default=0, min=0, max=256)


def _tex_items_for_obj(obj):
    """Return list of (identifier, label, description) for all TM textures."""
    col, tm = _get_col_tm(obj)
    items = [('-1', '(None)', 'No texture assigned')]
    if tm is not None:
        for item in tm.tex_list:
            if not item.is_empty:
                items.append((str(item.tex_id),
                              f"TexID {item.tex_id:03d}",
                              item.filepath or ''))
    return items


class Naomi_Param_Properties(bpy.types.PropertyGroup):
    # Sentinel: True if this object has Naomi data assigned (via import or manually)
    naomi_assigned: bpy.props.BoolProperty(name="Naomi Material Assigned", default=False)

    paramType : bpy.props.EnumProperty(
        description="Parameter type", name= "Parameter Type",
        items = [('0', "CtrlParam End of List",""), ('1', "CtrlParam User Tile Clip",""),
                 ('2', "CtrlParam Object List Set",""), ('4', "GlobalParam Poly/ModifierVol",""),
                 ('5', "GlobalParam Sprite",""), ('7', "VertexParam","")],
    )
    endOfStrip : bpy.props.EnumProperty(
        description="End of strip", name = "End of Strip",
        items = [('0', "No",""), ('1', "Yes","")],
    )
    listType : bpy.props.EnumProperty(
        description="List type", name= "List Type",
        items = [('0', "Opaque",""), ('1', "Opaque ModifierVol",""), ('2', "Translucent",""),
                 ('3', "Translucent ModifierVol",""), ('4', "Punch Through","")],
    )
    grpEn : bpy.props.EnumProperty(
        description="Group enable", name = "Group En",
        items = [('0', "No",""), ('1', "Update Strip_Len + User_Clip settings","")],
    )
    stripLen : bpy.props.EnumProperty(
        description="Strip length", name = "Strip Length",
        items = [('0', "1 Strip",""), ('1', "2 Strips",""), ('2', "4 Strips",""), ('3', "6 Strips","")],
    )
    usrClip : bpy.props.EnumProperty(
        description="User clip", name = "User Clip",
        items = [('0', "Disable",""), ('2', "Inside Enable",""), ('3', "Outside Enable","")],
    )
    shadow : bpy.props.EnumProperty(
        description="Shadow", name = "Shadow",
        items = [('0', "Disabled",""), ('1', "Enabled","")],
    )
    volume : bpy.props.EnumProperty(
        description="Volume", name = "Volume",
        items = [('0', "Disabled",""), ('1', "Enabled","")],
    )
    colType : bpy.props.EnumProperty(
        description="Color type", name = "Color Type",
        items = [('0', "Packed Color",""), ('1', "Floating Color",""),
                 ('2', "Intensity Mode 1",""), ('3', "Intensity Mode 2","")],
    )
    textureUsage : bpy.props.EnumProperty(
        description="Use texture", name = "Use Texture",
        items = [('0', "Disabled",""), ('1', "Enabled","")],
    )
    offsColorUsage : bpy.props.EnumProperty(
        description="Use offset color", name = "Use OffsetColor",
        items = [('0', "Disabled",""), ('1', "Enabled","")],
    )
    gouraudShdUsage : bpy.props.EnumProperty(
        description="Gouraud shading", name = "Gouraud Shading",
        items = [('0', "Disabled",""), ('1', "Enabled","")],
    )
    uvDataSize : bpy.props.EnumProperty(
        description="UV float size", name = "UV Float Size",
        items = [('0', "32-bit UV",""), ('1', "16-bit UV","")],
    )
    meshColor: FloatVectorProperty(
        name="Mesh Base Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(1.0, 1.0, 1.0, 1.0), update=update_mesh_color,
    )
    meshOffsetColor: FloatVectorProperty(
        name="Mesh Offset Color", subtype='COLOR', size=4, min=0.0, max=1.0,
        default=(0.0, 0.0, 0.0, 1.0), update=update_mesh_offsetcolor,
    )
    centroid_x: bpy.props.FloatProperty(name="Centroid X", default=0.0)
    centroid_y: bpy.props.FloatProperty(name="Centroid Y", default=0.0)
    centroid_z: bpy.props.FloatProperty(name="Centroid Z", default=0.0)
    bound_radius: bpy.props.FloatProperty(name="Bound Radius", default=1.0, min=0.0)
    mh_texID: bpy.props.IntProperty(
        description="Texture ID (-1 = none)", name="Texture ID", default=-1, min=-1, soft_min=0, max=1000, update=update_texture,
    )
    tex_folder: bpy.props.StringProperty(
        name="Texture Folder",
        description="Texture folder for this object",
        default="",
        subtype='DIR_PATH',
    )
    tex_list: bpy.props.CollectionProperty(type=Naomi_TextureSlotItem)
    tex_list_index: bpy.props.IntProperty(name="Selected Texture", default=0)
    m_shad_type: bpy.props.EnumProperty(
        name="Shading", description="Type of shading",
        items=[('0', "Lambert", ""), ('-1', "Constant (Flat)", ""),
               ('-2', "Bump", ""), ('-3', "Vertex Colors", "")],
    )
    m_tex_shading: bpy.props.IntProperty(name="Shading Type", description="Type of shading", default=0)
    spec_int: bpy.props.IntProperty(description="Specular Intensity", name="Specular Intensity", default=0, min=0, max=100)
    m_ambient_light: bpy.props.FloatProperty(
        description="Ambient", name="Ambient Light", default=0.333329975605011, min=0.0, max=1.0, update=update_mesh_ambient,
    )
    vcol_layer_name: bpy.props.StringProperty(
        name="Vertex Color Layer",
        description="Vertex color attribute name",
        default="",
    )

    # Per-mesh flags — auto-set on import, can also be toggled manually
    naomi_flag_bump: bpy.props.BoolProperty(
        name="Bump",
        description="Bump-map shading (auto-set on import)",
        default=False,
        update=_update_flag_bump,
    )
    naomi_flag_env_map: bpy.props.BoolProperty(
        name="EnvMap",
        description="Env map (auto-set on import)",
        default=False,
        update=_update_flag_env_map,
    )
    naomi_flag_palette: bpy.props.BoolProperty(
        name="Palette",
        description="Palettized texture (auto-set on import)",
        default=False,
    )
    naomi_pal_id: bpy.props.IntProperty(
        name="Palette ID",
        description="Palette file index (PalID_XXX)",
        default=0,
        min=0,
    )
    naomi_flag_two_sided: bpy.props.BoolProperty(
        name="2-Side",
        description="Disable back-face culling. Sets ISP/TSP CullingMode=0 on export",
        default=False,
        update=lambda self, ctx: _update_flag_two_sided(self, ctx),
    )

    # bump_partner_obj is the authoritative link; bump_partner_name kept in sync for importer/exporter
    def _poll_bump_partner(self, candidate):
        if candidate.type != 'MESH':
            return False
        owner = next(
            (o for o in bpy.data.objects if o.naomi_param is self),
            None,
        )
        if owner is None or candidate == owner:
            return False
        owner_cols = set(c.name for c in bpy.data.collections if owner.name in c.objects)
        cand_cols  = set(c.name for c in bpy.data.collections if candidate.name in c.objects)
        return bool(owner_cols & cand_cols)

    def _update_bump_partner_obj(self, context):
        new_obj = self.bump_partner_obj
        self.bump_partner_name = new_obj.name if new_obj is not None else ""

    bump_partner_obj: bpy.props.PointerProperty(
        name="Partner Object",
        description="Paired base mesh for this _bump mesh",
        type=bpy.types.Object,
        poll=_poll_bump_partner,
        update=_update_bump_partner_obj,
    )
    # Quick-Setting override properties ('-1' = AUTO / use preset default)
    qs_fog: bpy.props.EnumProperty(
        name="Fog", description="Override fog mode (AUTO = use preset default)",
        items=[('-1', "AUTO", "Use the preset default"), ('0', "LUT", ""), ('1', "Per Vertex", ""),
               ('2', "No Fog", ""), ('3', "LUT M2", "")],
        default='-1',
        update=_qs_update('qs_fog'),
    )
    qs_tex_alpha: bpy.props.EnumProperty(
        name="Texture Alpha", description="Override texture alpha usage (AUTO = use preset default)",
        items=[('-1', "AUTO", "Use the preset default"), ('0', "Use Texture Alpha", ""), ('1', "Ignore Texture Alpha", "")],
        default='-1',
        update=_qs_update('qs_tex_alpha'),
    )
    qs_color_clamp: bpy.props.EnumProperty(
        name="Color Clamp", description="Override color clamp (AUTO = use preset default)",
        items=[('-1', "AUTO", "Use the preset default"), ('0', "Underflow", ""), ('1', "Overflow", "")],
        default='-1',
        update=_qs_update('qs_color_clamp'),
    )
    qs_uv_clamp: bpy.props.EnumProperty(
        name="U/V Clamp", description="Override UV clamping (AUTO = use preset default)",
        items=[('-1', "AUTO", "Use the preset default"), ('0', "No Clamping", ""), ('1', "Clamp Y", ""),
               ('2', "Clamp X", ""), ('3', "Clamp X,Y", "")],
        default='-1',
        update=_qs_update('qs_uv_clamp'),
    )
    qs_filter: bpy.props.EnumProperty(
        name="Filter Mode", description="Override texture filter (AUTO = use preset default)",
        items=[('-1', "AUTO", "Use the preset default"), ('0', "Point Sampled", ""), ('1', "Bilinear Filter", ""),
               ('2', "Tri-linear Pass A", ""), ('3', "Tri-linear Pass B", "")],
        default='-1',
        update=_qs_update('qs_filter'),
    )
    qs_src_alpha: bpy.props.EnumProperty(
        name="SRC Alpha", description="Override SRC alpha blend factor (AUTO = use preset default)",
        items=[('-1', "AUTO", "Use the preset default"),
               ('0', "Zero", ""), ('1', "One", ""), ('2', "Other Color", ""), ('3', "Inv Other Color", ""),
               ('4', "SRC Alpha", ""), ('5', "Inv SRC Alpha", ""), ('6', "DST Alpha", ""), ('7', "Inv DST Alpha", "")],
        default='-1',
        update=_qs_update('qs_src_alpha'),
    )
    qs_dst_alpha: bpy.props.EnumProperty(
        name="DST Alpha", description="Override DST alpha blend factor (AUTO = use preset default)",
        items=[('-1', "AUTO", "Use the preset default"),
               ('0', "Zero", ""), ('1', "One", ""), ('2', "Other Color", ""), ('3', "Inv Other Color", ""),
               ('4', "SRC Alpha", ""), ('5', "Inv SRC Alpha", ""), ('6', "DST Alpha", ""), ('7', "Inv DST Alpha", "")],
        default='-1',
        update=_qs_update('qs_dst_alpha'),
    )
    qs_tex_shading: bpy.props.EnumProperty(
        name="Texture Shading", description="Override texture/shading mode (AUTO = use preset default)",
        items=[('-1', "AUTO", "Use the preset default"),
               ('0', "Decal", ""), ('1', "Modulate", ""), ('2', "Decal Alpha", ""), ('3', "Modulate Alpha", "")],
        default='-1',
        update=_qs_update('qs_tex_shading'),
    )

    bump_partner_name: bpy.props.StringProperty(
        name="Bump Partner Name",
        description="Paired partner object name",
        default="",
    )


class Naomi_ISP_TSP_Properties(bpy.types.PropertyGroup):
    depthCompare : bpy.props.EnumProperty(
        description="Depth compare mode", name = "Depth Compare",
        items = [('0', "Never",""), ('1', "Less",""), ('2', "Equal",""), ('3', "Less or Equal",""),
                 ('4', "Greater",""), ('5', "Not Equal",""), ('6', "Greater or Equal",""), ('7', "Always","")],
    )
    culling : bpy.props.EnumProperty(
        description="Culling mode", name = "Culling Mode",
        items = [('0', "No Culling",""), ('1', "Cull if Small",""),
                 ('2', "Cull if Negative",""), ('3', "Cull if Positive","")],
    )
    zWrite : bpy.props.EnumProperty(
        description="Z-write", name = "Z-Write",
        items = [('0', "Enabled",""), ('1', "Disabled","")],
    )
    textureUsage : bpy.props.EnumProperty(
        description="Use texture", name = "Use Texture",
        items = [('0', "Disabled",""), ('1', "Enabled","")],
    )
    offsColorUsage : bpy.props.EnumProperty(
        description="Use offset color", name = "Use OffsetColor",
        items = [('0', "Disabled",""), ('1', "Enabled","")],
    )
    gouraudShdUsage : bpy.props.EnumProperty(
        description="Gouraud shading", name = "Gouraud Shading",
        items = [('0', "Disabled",""), ('1', "Enabled","")],
    )
    uvDataSize : bpy.props.EnumProperty(
        description="UV float size", name = "UV Float Size",
        items = [('0', "32-bit UV",""), ('1', "16-bit UV","")],
    )
    cacheBypass : bpy.props.EnumProperty(
        description="Cache bypass", name = "Cache Bypass",
        items = [('0', "Disabled",""), ('1', "Enabled","")],
    )
    dCalcCtrl : bpy.props.EnumProperty(
        description="D-calc control", name = "D-Calc Ctrl",
        items = [('0', "Disabled",""), ('1', "Use on Small Polys","")],
    )

class Naomi_TSP_Properties(bpy.types.PropertyGroup):
    srcAlpha : bpy.props.EnumProperty(
        description="Alpha source", name= "Alpha Source",
        items = [('0', "Zero (0, 0, 0, 0)",""), ('1', "One (1, 1, 1, 1)",""),
                 ('2', "\'Other\' Color (OR, OG, OB, OA)",""), ('3', "Inverse \'Other\' Color (1-OR, 1-OG, 1-OB, 1-OA)",""),
                 ('4', "SRC Alpha (SA, SA, SA, SA)",""), ('5', "Inverse SRC Alpha (1-SA, 1-SA, 1-SA, 1-SA)",""),
                 ('6', "DST Alpha (DA, DA, DA, DA)",""), ('7', "Inverse DST Alpha (1-DA, 1-DA, 1-DA, 1-DA)","")],
        update=_update_blend_mode,
    )
    dstAlpha : bpy.props.EnumProperty(
        description="Alpha destination", name= "Alpha Destination",
        items = [('0', "Zero (0, 0, 0, 0)",""), ('1', "One (1, 1, 1, 1)",""),
                 ('2', "\'Other\' Color (OR, OG, OB, OA)",""), ('3', "Inverse \'Other\' Color (1-OR, 1-OG, 1-OB, 1-OA)",""),
                 ('4', "SRC Alpha (SA, SA, SA, SA)",""), ('5', "Inverse SRC Alpha (1-SA, 1-SA, 1-SA, 1-SA)",""),
                 ('6', "DST Alpha (DA, DA, DA, DA)",""), ('7', "Inverse DST Alpha (1-DA, 1-DA, 1-DA, 1-DA)","")],
        update=_update_blend_mode,
    )
    srcSelect : bpy.props.EnumProperty(
        description="Source buffer", name = "SRC Buffer Select",
        items = [('0', "Primary Accumulation Buffer SRC",""), ('1', "Secondary Accumulation Buffer SRC","")],
    )
    dstSelect : bpy.props.EnumProperty(
        description="Destination buffer", name = "DST Buffer Select",
        items = [('0', "Primary Accumulation Buffer DST",""), ('1', "Secondary Accumulation Buffer DST","")],
    )
    fogOp : bpy.props.EnumProperty(
        description="Fog", name= "Fog Setting",
        items = [('0', "LUT (Look Up Table)",""), ('1', "Per Vertex",""),
                 ('2', "No Fog",""), ('3', "LUT M2 (Look Up Table, Mode 2)","")],
    )
    colorClamp : bpy.props.EnumProperty(
        description="Color clamp", name = "Color Clamp",
        items = [('0', "Underflow",""), ('1', "Overflow","")],
    )
    alphaOp : bpy.props.EnumProperty(
        description="Alpha mode", name = "Alpha Mode",
        items = [('0', "Opaque",""), ('1', "Translucent","")],
    )
    alphaTexOp : bpy.props.EnumProperty(
        description="Texture alpha", name = "Texture Alpha Usage",
        items = [('0', "Use Texture Alpha",""), ('1', "Ignore Texture Alpha","")],
        update=_update_uv,
    )
    uvFlip : bpy.props.EnumProperty(
        description="UV flip", name = "UV Flip Mode",
        items = [('0', "No Flipping",""), ('1', "Flip Y",""), ('2', "Flip X",""), ('3', "Flip X,Y","")],
        update=_update_uv,
    )
    uvClamp : bpy.props.EnumProperty(
        description="UV clamp", name = "UV Clamp Mode",
        items = [('0', "No Clamping",""), ('1', "Clamp Y",""), ('2', "Clamp X",""), ('3', "Clamp X,Y","")],
        update=_update_uv,
    )
    filter : bpy.props.EnumProperty(
        description="Texture filter", name = "Texture Filter",
        items = [('0', "Point Sampled",""), ('1', "Bilinear Filter",""),
                 ('2', "Tri-linear Pass A",""), ('3', "Tri-linear Pass B","")],
        update=_update_filter,
    )
    supSample : bpy.props.EnumProperty(
        description="Super-sample", name = "Texture Super-Sample",
        items = [('0', "Disabled",""), ('1', "Enabled","")],
    )
    mipmapDAdj : bpy.props.EnumProperty(
        description="Mipmap D adjust", name = "Mipmap D Adjust",
        items = [('1',"0.25",""),('2',"0.50",""),('3',"0.75",""),('4',"1.00",""),('5',"1.25",""),
                 ('6',"1.50",""),('7',"1.75",""),('8',"2.00",""),('9',"2.25",""),('10',"2.50",""),
                 ('11',"2.75",""),('12',"3.00",""),('13',"3.25",""),('14',"3.50",""),('15',"3.75",""),
                 ('0',"Illegal","")],
    )
    texShading : bpy.props.EnumProperty(
        description="Tex/shading mode", name = "Texture/Shading",
        items = [('0', "Decal [PIXrgb = TEXrgb + OFFSETrgb]  [PIXa = TEXa]",""),
                 ('1', "Modulate [PIXrgb = COLrgb * TEXrgb + OFFSETrgb]  [PIXa = TEXa]",""),
                 ('2', "Decal Alpha [PIXrgb = (TEXrgb + TEXa) + (COLrgb * (1-TEXa)) + OFFSETrgb]  [PIXa = COLa]",""),
                 ('3', "Modulate Alpha [PIXrgb = COLrgb * TEXrgb + OFFSETrgb]  [PIXa = COLa * TEXa]","")],
        update=_update_tex_shading,
    )
    texUSize : bpy.props.EnumProperty(
        description="U size (width)", name= "U Size (Width)",
        items = [('0',"Width:    8 px",""),('1',"Width:   16 px",""),('2',"Width:   32 px",""),
                 ('3',"Width:   64 px",""),('4',"Width:  128 px",""),('5',"Width:  256 px",""),
                 ('6',"Width:  512 px",""),('7',"Width: 1024 px","")],
    )
    texVSize : bpy.props.EnumProperty(
        description="V size (height)", name= "V Size (Height)",
        items = [('0',"Height:    8 px",""),('1',"Height:   16 px",""),('2',"Height:   32 px",""),
                 ('3',"Height:   64 px",""),('4',"Height:  128 px",""),('5',"Height:  256 px",""),
                 ('6',"Height:  512 px",""),('7',"Height: 1024 px","")],
    )

class Naomi_TexCtrl_Properties(bpy.types.PropertyGroup):
    mipMapped : bpy.props.BoolProperty(description="Mipmapped", name = "Mipmapped")
    vqCompressed : bpy.props.BoolProperty(description="VQ compressed", name = "VQ Compressed")
    pixelFormat : bpy.props.EnumProperty(
        description="Pixel format", name = "Pixel Format",
        items = [('0',"ARGB1555",""),('1',"RGB565",""),('2',"ARGB4444",""),('3',"YUV422",""),
                 ('4',"Bump Map",""),('5',"4 BPP Palette",""),('6',"8 BPP Palette","")],
    )
    scanOrder : bpy.props.EnumProperty(
        description="Scan order", name = "Scan Order",
        items = [('0', "Twiddled",""), ('1', "Non-Twiddled","")],
    )
    texCtrlUstride : bpy.props.EnumProperty(
        description="U stride", name = "TexCtrl U-Stride",
        items = [('0', "Disabled",""), ('1', "Enabled","")],
    )


def _object_props_to_dict(obj):
    p  = obj.naomi_param
    it = obj.naomi_isp_tsp
    t  = obj.naomi_tsp
    tc = obj.naomi_texCtrl
    return {
        "naomi_param": {
            "centroid_x": p.centroid_x, "centroid_y": p.centroid_y, "centroid_z": p.centroid_z,
            "bound_radius": p.bound_radius,
            "meshColor": list(p.meshColor), "meshOffsetColor": list(p.meshOffsetColor),
            "mh_texID": p.mh_texID, "m_shad_type": p.m_shad_type,
            "m_tex_shading": p.m_tex_shading, "spec_int": p.spec_int,
            "m_ambient_light": p.m_ambient_light,
            "paramType": p.paramType, "endOfStrip": p.endOfStrip, "listType": p.listType,
            "grpEn": p.grpEn, "stripLen": p.stripLen, "usrClip": p.usrClip,
            "shadow": p.shadow, "volume": p.volume, "colType": p.colType,
            "textureUsage": p.textureUsage, "offsColorUsage": p.offsColorUsage,
            "gouraudShdUsage": p.gouraudShdUsage, "uvDataSize": p.uvDataSize,
            "naomi_flag_bump": p.naomi_flag_bump, "naomi_flag_env_map": p.naomi_flag_env_map,
            "naomi_flag_palette": p.naomi_flag_palette, "naomi_flag_two_sided": p.naomi_flag_two_sided,
        },
        "naomi_isp_tsp": {
            "depthCompare": it.depthCompare, "culling": it.culling, "zWrite": it.zWrite,
            "textureUsage": it.textureUsage, "offsColorUsage": it.offsColorUsage,
            "gouraudShdUsage": it.gouraudShdUsage, "uvDataSize": it.uvDataSize,
            "cacheBypass": it.cacheBypass, "dCalcCtrl": it.dCalcCtrl,
        },
        "naomi_tsp": {
            "srcAlpha": t.srcAlpha, "dstAlpha": t.dstAlpha, "srcSelect": t.srcSelect,
            "dstSelect": t.dstSelect, "fogOp": t.fogOp, "colorClamp": t.colorClamp,
            "alphaOp": t.alphaOp, "alphaTexOp": t.alphaTexOp, "uvFlip": t.uvFlip,
            "uvClamp": t.uvClamp, "filter": t.filter, "supSample": t.supSample,
            "mipmapDAdj": t.mipmapDAdj, "texShading": t.texShading,
            "texUSize": t.texUSize, "texVSize": t.texVSize,
        },
        "naomi_texCtrl": {
            "mipMapped": tc.mipMapped, "vqCompressed": tc.vqCompressed,
            "pixelFormat": tc.pixelFormat, "scanOrder": tc.scanOrder,
            "texCtrlUstride": tc.texCtrlUstride,
        },
    }

def _dict_to_object_props(obj, data):
    p  = obj.naomi_param
    it = obj.naomi_isp_tsp
    t  = obj.naomi_tsp
    tc = obj.naomi_texCtrl

    np_ = data.get("naomi_param", {})
    for key in ("centroid_x","centroid_y","centroid_z","bound_radius","mh_texID",
                "m_tex_shading","spec_int","m_ambient_light","paramType","endOfStrip",
                "listType","grpEn","stripLen","usrClip","shadow","volume","colType",
                "textureUsage","offsColorUsage","gouraudShdUsage","uvDataSize","m_shad_type",
                "naomi_flag_bump","naomi_flag_env_map","naomi_flag_palette","naomi_flag_two_sided"):
        if key in np_:
            setattr(p, key, np_[key])
    if "meshColor" in np_:
        p.meshColor = np_["meshColor"]
    if "meshOffsetColor" in np_:
        p.meshOffsetColor = np_["meshOffsetColor"]

    ni = data.get("naomi_isp_tsp", {})
    for key in ("depthCompare","culling","zWrite","textureUsage","offsColorUsage",
                "gouraudShdUsage","uvDataSize","cacheBypass","dCalcCtrl"):
        if key in ni:
            setattr(it, key, ni[key])

    nt = data.get("naomi_tsp", {})
    for key in ("srcAlpha","dstAlpha","srcSelect","dstSelect","fogOp","colorClamp",
                "alphaOp","alphaTexOp","uvFlip","uvClamp","filter","supSample",
                "mipmapDAdj","texShading","texUSize","texVSize"):
        if key in nt:
            setattr(t, key, nt[key])

    ntc = data.get("naomi_texCtrl", {})
    for key in ("mipMapped","vqCompressed","pixelFormat","scanOrder","texCtrlUstride"):
        if key in ntc:
            setattr(tc, key, ntc[key])

    p.naomi_assigned = True


def _reset_object_props(obj):
    """Reset all Naomi object properties to defaults."""
    p  = obj.naomi_param
    it = obj.naomi_isp_tsp
    t  = obj.naomi_tsp
    tc = obj.naomi_texCtrl

    p.naomi_assigned    = False
    p.centroid_x        = 0.0
    p.centroid_y        = 0.0
    p.centroid_z        = 0.0
    p.bound_radius      = 1.0
    p.meshColor         = (1.0, 1.0, 1.0, 1.0)
    p.meshOffsetColor   = (0.0, 0.0, 0.0, 1.0)
    p.mh_texID          = -1
    p.m_shad_type       = '0'
    p.m_tex_shading     = 0
    p.spec_int          = 0
    p.m_ambient_light   = 0.333329975605011  # 0x3eaaaa3a — NAOMI hardware default tex_ambient
    p.paramType         = '0'
    p.endOfStrip        = '0'
    p.listType          = '0'
    p.grpEn             = '0'
    p.stripLen          = '0'
    p.usrClip           = '0'
    p.shadow            = '0'
    p.volume            = '0'
    p.colType           = '0'
    p.textureUsage      = '0'
    p.offsColorUsage    = '0'
    p.gouraudShdUsage   = '0'
    p.uvDataSize        = '0'

    it.depthCompare     = '0'
    it.culling          = '0'
    it.zWrite           = '0'
    it.textureUsage     = '0'
    it.offsColorUsage   = '0'
    it.gouraudShdUsage  = '0'
    it.uvDataSize       = '0'
    it.cacheBypass      = '0'
    it.dCalcCtrl        = '0'

    t.srcAlpha          = '0'
    t.dstAlpha          = '0'
    t.srcSelect         = '0'
    t.dstSelect         = '0'
    t.fogOp             = '0'
    t.colorClamp        = '0'
    t.alphaOp           = '0'
    t.alphaTexOp        = '0'
    t.uvFlip            = '0'
    t.uvClamp           = '0'
    t.filter            = '0'
    t.supSample         = '0'
    t.mipmapDAdj        = '4'   # 1.00 is the default
    t.texShading        = '0'
    t.texUSize          = '0'
    t.texVSize          = '0'

    tc.mipMapped        = False
    tc.vqCompressed     = False
    tc.pixelFormat      = '0'
    tc.scanOrder        = '0'
    tc.texCtrlUstride   = '0'
    p.vcol_layer_name   = ''


def _reset_collection_props(col):
    """Reset all Naomi collection properties to defaults and unassign."""
    col.gp0.objFormat                              = '1'
    col.gp1.skp1stSrcOp                            = False
    col.gp1.envMap                                 = False
    col.gp1.pltTex                                 = False
    col.gp1.bumpMap                                = False
    col.naomi_centroidData.naomi_assigned          = False
    col.naomi_centroidData.centroid_x              = 0.0
    col.naomi_centroidData.centroid_y              = 0.0
    col.naomi_centroidData.centroid_z              = 0.0
    col.naomi_centroidData.collection_bound_radius = 1.0


def _ensure_material(obj, name_suffix):
    """Ensure obj has an exclusive material on slot 0 with use_nodes=True."""
    if not obj.data.materials:
        mat = bpy.data.materials.new(name=f"{obj.name}_{name_suffix}")
        mat.use_nodes = True
        mat.use_backface_culling = True
        obj.data.materials.append(mat)
    else:
        mat = obj.data.materials[0]
        if mat is None:
            mat = bpy.data.materials.new(name=f"{obj.name}_{name_suffix}")
            mat.use_nodes = True
            mat.use_backface_culling = True
            obj.data.materials[0] = mat
        elif mat.users > 1:
            # Material is shared — make an exclusive copy for this object.
            mat = mat.copy()
            mat.name = f"{obj.name}_{name_suffix}"
            obj.data.materials[0] = mat
        if not mat.use_nodes:
            mat.use_nodes = True
    return mat


def _snapshot_tex_image(obj):
    """Return the bpy.data.Image currently wired in obj's first material, or None."""
    if not obj or not obj.material_slots:
        return None
    mat = obj.material_slots[0].material
    if not (mat and mat.use_nodes and mat.node_tree):
        return None
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    for node in nodes:
        if node.bl_idname == 'ShaderNodeTexImage' and node.image:
            return node.image
    for node in nodes:
        if node.bl_idname == 'ShaderNodeBsdfPrincipled':
            base_color_input = node.inputs.get('Base Color')
            if base_color_input and base_color_input.is_linked:
                for link in links:
                    if (link.to_node == node and
                            link.to_socket == base_color_input and
                            link.from_node.bl_idname == 'ShaderNodeTexImage' and
                            link.from_node.image):
                        return link.from_node.image
    return None


def _apply_lambert_preset(obj, tex_image=None):
    """Set naomi_param defaults for Lambert shading matching C++ converter output."""
    p  = obj.naomi_param
    it = obj.naomi_isp_tsp
    t  = obj.naomi_tsp

    has_tex = tex_image is not None or int(p.mh_texID) >= 0

    p.naomi_assigned   = True
    p.m_shad_type      = '0'
    p.m_tex_shading    = 0
    p.m_ambient_light  = 0.333329975605011  # 0x3eaaaa3a

    p.paramType        = '4'
    p.endOfStrip       = '0'
    p.listType         = '0'
    p.grpEn            = '0'
    p.stripLen         = '0'
    p.usrClip          = '0'
    p.shadow           = '0'
    p.volume           = '0'
    p.colType          = '2'   # Intensity Mode 1
    p.textureUsage     = '1'
    p.offsColorUsage   = '1'
    p.gouraudShdUsage  = '0'
    p.uvDataSize       = '0' if has_tex else '1'

    it.depthCompare    = '4'
    it.culling         = '0'
    it.zWrite          = '0'
    it.textureUsage    = '1'
    it.offsColorUsage  = '1'
    it.gouraudShdUsage = '0'
    it.uvDataSize      = '0' if has_tex else '1'
    it.cacheBypass     = '0'
    it.dCalcCtrl       = '0'

    t.srcAlpha         = '1'
    t.dstAlpha         = '0'
    t.srcSelect        = '0'
    t.dstSelect        = '0'
    t.fogOp            = '2'   # No Fog
    t.colorClamp       = '0'
    t.alphaOp          = '0'
    t.alphaTexOp       = '1'   # Ignore Texture Alpha
    t.uvFlip           = '0'
    t.uvClamp          = '0'
    t.filter           = '1' if has_tex else '0'
    t.supSample        = '0'
    t.mipmapDAdj       = '4'
    t.texShading       = '1'   # Modulate
    t.texUSize         = '0'
    t.texVSize         = '0'

    mat = _ensure_material(obj, 'Naomi')
    build_naomi_material(
        mat                  = mat,
        mesh_color           = tuple(p.meshColor),
        mesh_offset_color    = tuple(p.meshOffsetColor),
        tex_shading          = int(p.m_tex_shading),
        tsp_src_alpha        = int(t.srcAlpha),
        tsp_dst_alpha        = int(t.dstAlpha),
        list_type            = int(p.listType) if p.listType else 0,
        flip_uv              = int(t.uvFlip),
        clamp                = int(t.uvClamp),
        alpha_tex_op         = t.alphaTexOp,
        use_backface_culling = True,
        mh_tex_id            = int(p.mh_texID),
        tex_image            = tex_image,
        is_env_map           = False,
        vertex_col_layer     = None,
        m_tex_amb            = float(p.m_ambient_light),
        tsp_filter           = t.filter,
    )

    if obj.type == 'MESH' and obj.data:
        for poly in obj.data.polygons:
            poly.use_smooth = True


def _apply_env_map_preset(obj, tex_image=None):
    """Lambert + spherical env-map (reflection UV)."""
    _apply_lambert_preset(obj, tex_image=tex_image)
    obj.naomi_param.naomi_flag_env_map = False
    obj.naomi_param.naomi_flag_env_map = True

def _apply_flat_preset(obj, tex_image=None):
    """Set naomi_param defaults for Flat (Constant) shading."""
    p  = obj.naomi_param
    it = obj.naomi_isp_tsp
    t  = obj.naomi_tsp

    has_tex = tex_image is not None or int(p.mh_texID) >= 0

    p.naomi_assigned   = True
    p.m_shad_type      = '-1'
    p.m_tex_shading    = -1
    p.paramType        = '4'
    p.listType         = '0'
    p.gouraudShdUsage  = '0'
    p.colType          = '0'   # Packed Color
    p.offsColorUsage   = '1'
    p.textureUsage     = '1'
    p.uvDataSize       = '0' if has_tex else '1'
    p.m_ambient_light  = 0.333329975605011

    # ISP/TSP
    it.depthCompare    = '4'
    it.culling         = '0'
    it.zWrite          = '0'
    it.textureUsage    = '1'
    it.offsColorUsage  = '1'
    it.gouraudShdUsage = '0'
    it.uvDataSize      = '0' if has_tex else '1'
    it.cacheBypass     = '0'
    it.dCalcCtrl       = '0'

    # TSP
    t.srcAlpha         = '1'
    t.dstAlpha         = '0'
    t.srcSelect        = '0'
    t.dstSelect        = '0'
    t.fogOp            = '2'
    t.colorClamp       = '0'
    t.alphaOp          = '0'
    t.alphaTexOp       = '1'
    t.uvFlip           = '0'
    t.uvClamp          = '0'
    t.filter           = '1' if has_tex else '0'
    t.supSample        = '0'
    t.mipmapDAdj       = '4'
    t.texShading       = '1'
    t.texUSize         = '0'
    t.texVSize         = '0'

    mat = _ensure_material(obj, 'Naomi')
    build_naomi_material(
        mat                  = mat,
        mesh_color           = tuple(p.meshColor),
        mesh_offset_color    = tuple(p.meshOffsetColor),
        tex_shading          = int(p.m_tex_shading),
        tsp_src_alpha        = int(t.srcAlpha),
        tsp_dst_alpha        = int(t.dstAlpha),
        list_type            = int(p.listType) if p.listType else 0,
        flip_uv              = int(t.uvFlip),
        clamp                = int(t.uvClamp),
        alpha_tex_op         = t.alphaTexOp,
        use_backface_culling = True,
        mh_tex_id            = int(p.mh_texID),
        tex_image            = tex_image,
        is_env_map           = False,
        vertex_col_layer     = None,
        m_tex_amb            = float(p.m_ambient_light),
        tsp_filter           = t.filter,
    )


def _apply_vertex_color_preset(obj, tex_image=None):
    """Set naomi_param defaults for Vertex Color shading and create the color layer."""
    p  = obj.naomi_param
    it = obj.naomi_isp_tsp
    t  = obj.naomi_tsp

    has_tex = tex_image is not None or int(p.mh_texID) >= 0

    p.naomi_assigned   = True
    p.m_shad_type      = '-3'
    p.m_tex_shading    = -3
    p.paramType        = '4'
    p.listType         = '0'
    p.gouraudShdUsage  = '1'
    p.colType          = '1'   # Floating Color
    p.offsColorUsage   = '1'
    # Preserve an existing texture: only clear the slot when no image was present.
    if tex_image is None:
        p.mh_texID     = -1
        p.textureUsage = '0'
        has_tex        = False
    else:
        p.textureUsage = '1'
    p.uvDataSize       = '0' if has_tex else '1'
    p.m_ambient_light  = 0.333329975605011  # 0x3eaaaa3a — NAOMI hardware default tex_ambient

    # ISP/TSP
    it.depthCompare    = '4'
    it.culling         = '0'
    it.zWrite          = '0'
    it.textureUsage    = '1'
    it.offsColorUsage  = '1'
    it.gouraudShdUsage = '1'
    it.uvDataSize      = '0' if has_tex else '1'
    it.cacheBypass     = '0'
    it.dCalcCtrl       = '0'

    # TSP
    t.srcAlpha         = '1'
    t.dstAlpha         = '0'
    t.srcSelect        = '0'
    t.dstSelect        = '0'
    t.fogOp            = '2'
    t.colorClamp       = '0'
    t.alphaOp          = '0'
    t.alphaTexOp       = '1'
    t.uvFlip           = '0'
    t.uvClamp          = '0'
    t.filter           = '1' if has_tex else '0'
    t.supSample        = '0'
    t.mipmapDAdj       = '4'
    t.texShading       = '1'
    t.texUSize         = '0'
    t.texVSize         = '0'

    LAYER_NAME = 'NaomiCol'
    mesh = obj.data

    if hasattr(mesh, 'color_attributes'):
        color_layer = mesh.color_attributes.get(LAYER_NAME)
        if color_layer is None:
            color_layer = mesh.color_attributes.new(
                name=LAYER_NAME,
                type='BYTE_COLOR',
                domain='CORNER',
            )
            if color_layer is not None:
                for data in color_layer.data:
                    data.color = (1.0, 1.0, 1.0, 1.0)
        if color_layer is not None:
            try:
                mesh.color_attributes.active_color = color_layer
            except Exception:
                for i, attr in enumerate(mesh.color_attributes):
                    if attr.name == LAYER_NAME:
                        mesh.color_attributes.active_color_index = i
                        break
    else:
        color_layer = mesh.vertex_colors.get(LAYER_NAME)
        if color_layer is None:
            color_layer = mesh.vertex_colors.new(name=LAYER_NAME)
            if color_layer is not None:
                for loop_color in color_layer.data:
                    loop_color.color = (1.0, 1.0, 1.0, 1.0)
        if color_layer is not None:
            mesh.vertex_colors.active = color_layer

    p.vcol_layer_name = LAYER_NAME

    for _poly in obj.data.polygons:
        _poly.use_smooth = True

    mat = _ensure_material(obj, 'NaomiVCol')
    build_naomi_material(
        mat                  = mat,
        mesh_color           = tuple(p.meshColor),
        mesh_offset_color    = tuple(p.meshOffsetColor),
        tex_shading          = int(p.m_tex_shading),
        tsp_src_alpha        = int(t.srcAlpha),
        tsp_dst_alpha        = int(t.dstAlpha),
        list_type            = int(p.listType) if p.listType else 0,
        flip_uv              = int(t.uvFlip),
        clamp                = int(t.uvClamp),
        alpha_tex_op         = t.alphaTexOp,
        use_backface_culling = True,
        mh_tex_id            = int(p.mh_texID),
        tex_image            = tex_image,
        is_env_map           = False,
        vertex_col_layer     = LAYER_NAME,
        m_tex_amb            = float(p.m_ambient_light),
        tsp_filter           = t.filter,
    )

# ---------------------------------------------------------------------------
# Bump-map helpers
# ---------------------------------------------------------------------------

def _get_bump_partner(obj):
    """Return the bump-map partner object (prefers PointerProperty, falls back to name string), or None."""
    if obj is None:
        return None
    p = getattr(obj, 'naomi_param', None)
    if p is None:
        return None
    ptr = getattr(p, 'bump_partner_obj', None)
    if ptr is not None:
        return ptr
    name = getattr(p, 'bump_partner_name', '')
    if not name:
        return None
    # Prefer objects in the same collection to avoid name collisions.
    partner = None
    for col in bpy.data.collections:
        if obj.name in col.objects and name in col.objects:
            partner = col.objects[name]
            break
    if partner is None:
        partner = bpy.data.objects.get(name)
    if partner is not None:
        try:
            p.bump_partner_obj = partner
        except Exception:
            pass
    return partner


def _is_bump_mesh(obj):
    """True when obj is the _bump mesh (naomi_flag_bump=True, normal-map texture)."""
    p = getattr(obj, 'naomi_param', None)
    return p is not None and p.naomi_assigned and p.naomi_flag_bump


def _is_bump_partner(obj):
    """True when obj is the plain Lambert partner of a _bump mesh."""
    partner = _get_bump_partner(obj)
    return partner is not None and _is_bump_mesh(partner) and not _is_bump_mesh(obj)


# ---------------------------------------------------------------------------
# Bump preset helpers
# ---------------------------------------------------------------------------

def _apply_bump_mesh_params(bump_obj, tex_image=None):
    """_bump mesh: translucent, Packed Color, fog=LUT, sa=SRC, da=Inv SRC."""
    p  = bump_obj.naomi_param
    it = bump_obj.naomi_isp_tsp
    t  = bump_obj.naomi_tsp
    tc = bump_obj.naomi_texCtrl

    p.naomi_assigned   = True
    p.naomi_flag_bump  = True
    p.m_shad_type      = '-2'    # Bump
    p.m_tex_shading    = -2
    p.m_ambient_light  = 0.333329975605011

    p.paramType        = '4'
    p.endOfStrip       = '0'
    p.listType         = '2'     # Translucent
    p.grpEn            = '0'
    p.stripLen         = '0'
    p.usrClip          = '0'
    p.shadow           = '0'
    p.volume           = '0'
    p.colType          = '0'     # Packed Color
    p.textureUsage     = '1'
    p.offsColorUsage   = '1'
    p.gouraudShdUsage  = '0'
    p.uvDataSize       = '0'

    it.depthCompare    = '4'
    it.culling         = '0'
    it.zWrite          = '0'
    it.textureUsage    = '1'
    it.offsColorUsage  = '1'
    it.gouraudShdUsage = '0'
    it.uvDataSize      = '0'
    it.cacheBypass     = '0'
    it.dCalcCtrl       = '0'

    t.srcAlpha         = '4'     # SRC Alpha
    t.dstAlpha         = '5'     # Inverse SRC
    t.srcSelect        = '0'
    t.dstSelect        = '0'
    t.fogOp            = '0'     # Lookup Table fog
    t.colorClamp       = '0'
    t.alphaOp          = '1'
    t.alphaTexOp       = '0'
    t.uvFlip           = '0'
    t.uvClamp          = '0'
    t.filter           = '1'
    t.supSample        = '0'
    t.mipmapDAdj       = '4'
    t.texShading       = '1'
    t.texUSize         = '0'
    t.texVSize         = '0'

    tc.pixelFormat     = '4'     # PIX_BUMP_MAP
    tc.scanOrder       = '1'
    tc.vqCompressed    = False
    tc.mipMapped       = False

    try:
        mc = list(p.meshColor)
        mc[3] = 1.0
        p.meshColor = mc
        p.meshOffsetColor = (0.0, 1.0, 0.0, 1.0)
    except Exception:
        pass

    mat = _ensure_material(bump_obj, 'Naomi_Bump')
    build_naomi_material(
        mat                  = mat,
        mesh_color           = tuple(p.meshColor),
        mesh_offset_color    = tuple(p.meshOffsetColor),
        tex_shading          = -2,
        tsp_src_alpha        = 4,
        tsp_dst_alpha        = 5,
        list_type            = 2,
        flip_uv              = 0,
        clamp                = 0,
        alpha_tex_op         = '0',
        use_backface_culling = True,
        mh_tex_id            = int(p.mh_texID) if p.mh_texID >= 0 else -1,
        tex_image            = tex_image,
        is_env_map           = False,
        vertex_col_layer     = None,
        m_tex_amb            = float(p.m_ambient_light),
        tsp_filter           = '1',
        is_bump_base         = True,
        is_bump_overlay      = False,
        base_tex_image       = None,
    )


def _apply_plain_mesh_params(obj, tex_image=None):
    """Plain Lambert mesh paired with _bump: opaque, Intensity Mode 1, standard."""
    p  = obj.naomi_param
    it = obj.naomi_isp_tsp
    t  = obj.naomi_tsp

    has_tex = tex_image is not None or int(p.mh_texID) >= 0

    p.naomi_assigned   = True
    p.naomi_flag_bump  = False
    p.m_tex_shading    = 0
    p.m_ambient_light  = 0.333329975605011

    p.paramType        = '4'
    p.endOfStrip       = '0'
    p.listType         = '0'     # Opaque
    p.grpEn            = '0'
    p.stripLen         = '0'
    p.usrClip          = '0'
    p.shadow           = '0'
    p.volume           = '0'
    p.colType          = '2'     # Intensity Mode 1
    p.textureUsage     = '1'
    p.offsColorUsage   = '1'
    p.gouraudShdUsage  = '0'
    p.uvDataSize       = '0' if has_tex else '1'

    it.depthCompare    = '4'
    it.culling         = '0'
    it.zWrite          = '0'
    it.textureUsage    = '1'
    it.offsColorUsage  = '1'
    it.gouraudShdUsage = '0'
    it.uvDataSize      = '0' if has_tex else '1'
    it.cacheBypass     = '0'
    it.dCalcCtrl       = '0'

    t.srcAlpha         = '1'     # One
    t.dstAlpha         = '0'     # Zero
    t.srcSelect        = '0'
    t.dstSelect        = '0'
    t.fogOp            = '0'     # Lookup Table fog
    t.colorClamp       = '0'
    t.alphaOp          = '0'
    t.alphaTexOp       = '1'     # Ignore
    t.uvFlip           = '0'
    t.uvClamp          = '0'
    t.filter           = '1' if has_tex else '0'
    t.supSample        = '0'
    t.mipmapDAdj       = '4'
    t.texShading       = '1'
    t.texUSize         = '0'
    t.texVSize         = '0'

    try:
        mc = list(p.meshColor)
        mc[3] = 1.0
        p.meshColor = mc
    except Exception:
        pass

    mat = _ensure_material(obj, 'Naomi_BumpPlain')
    build_naomi_material(
        mat                  = mat,
        mesh_color           = tuple(p.meshColor),
        mesh_offset_color    = tuple(p.meshOffsetColor),
        tex_shading          = 0,
        tsp_src_alpha        = 1,
        tsp_dst_alpha        = 0,
        list_type            = 0,
        flip_uv              = 0,
        clamp                = 0,
        alpha_tex_op         = '1',
        use_backface_culling = True,
        mh_tex_id            = int(p.mh_texID) if p.mh_texID >= 0 else -1,
        tex_image            = tex_image,
        is_env_map           = False,
        vertex_col_layer     = None,
        m_tex_amb            = float(p.m_ambient_light),
        tsp_filter           = '1',
        is_bump_base         = False,
        is_bump_overlay      = False,
    )


# ---------------------------------------------------------------------------
# Bump preset operator
# ---------------------------------------------------------------------------

class NAOMI_OT_assign_preset_bump(bpy.types.Operator):
    """Bump Map preset.
Duplicates the selected object, names the copy '<n>_bump' and assigns
pass-1 bump parameters (naomi_flag_bump=True, pixelFormat=4, listType=OPQ).
The original becomes the overlay pass with pass-2 parameters (listType=TRS,
sa=4, da=5).  Both objects use the same _bump.pvr texture (assigned later)."""
    bl_idname  = "naomi.assign_preset_bump"
    bl_label   = "Bump Map"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        base_obj = context.active_object
        if base_obj is None:
            return {'CANCELLED'}

        # Guard: don't create a second bump pair
        if _is_bump_mesh(base_obj) or _is_bump_partner(base_obj):
            self.report({'WARNING'},
                        f"'{base_obj.name}' is already part of a bump pair.")
            return {'CANCELLED'}

        for col in base_obj.users_collection:
            for o in col.objects:
                if o is base_obj:
                    continue
                if _is_bump_mesh(o) and _get_bump_partner(o) is not None:
                    self.report({'WARNING'},
                                f"Collection '{col.name}' already has a bump pair.")
                    return {'CANCELLED'}

        # Duplicate → becomes the BUMP object (pass 1)
        bump_mesh = base_obj.data.copy()
        import re as _re
        raw_name  = _re.sub(r'\.\d+$', '', base_obj.name)
        bump_name = raw_name + "_bump"
        bump_obj  = bpy.data.objects.new(bump_name, bump_mesh)
        bump_obj.matrix_world = base_obj.matrix_world.copy()
        bump_obj.scale        = base_obj.scale.copy()
        for col in base_obj.users_collection:
            col.objects.link(bump_obj)

        # Detach materials so both objects are independent
        bump_obj.data.materials.clear()
        if base_obj.data.materials:
            orig_mat = base_obj.data.materials[0]
            if orig_mat is not None and orig_mat.users > 1:
                base_copy = orig_mat.copy()
                base_copy.name = f"{base_obj.name}_Naomi"
                base_obj.data.materials[0] = base_copy

        # Apply pass-1 params to bump_obj
        _apply_bump_mesh_params(bump_obj, tex_image=None)
        bump_obj.naomi_param.mh_texID = -1

        # Apply pass-2 params to base_obj (overlay)
        base_tex_image = _snapshot_tex_image(base_obj)
        old_tex_id = int(base_obj.naomi_param.mh_texID)             if base_obj.naomi_param.naomi_assigned else -1
        _apply_plain_mesh_params(base_obj, tex_image=base_tex_image)
        if old_tex_id >= 0:
            base_obj.naomi_param.mh_texID = old_tex_id
            _apply_texture_params(base_obj, has_texture=True)

        # Wire partner links
        bump_obj.naomi_param.bump_partner_name = base_obj.name
        base_obj.naomi_param.bump_partner_name = bump_obj.name
        bump_obj.naomi_param.bump_partner_obj  = base_obj
        base_obj.naomi_param.bump_partner_obj  = bump_obj

        # Select the new bump object
        for o in list(context.selected_objects):
            o.select_set(False)
        bump_obj.select_set(True)
        context.view_layer.objects.active = bump_obj

        for col in bump_obj.users_collection:
            if hasattr(col, 'naomi_centroidData') and                not col.naomi_centroidData.naomi_assigned:
                col.naomi_centroidData.naomi_assigned = True
        _sync_collection_flags(bump_obj)

        self.report({'INFO'},
                    f"Bump pair: '{bump_obj.name}' (pass1/OPQ) <-> '{base_obj.name}' (pass2/TRS)")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Re-link operator — lets user pick/fix the base mesh partner
# ---------------------------------------------------------------------------

class NAOMI_OT_bump_set_partner(bpy.types.Operator):
    """Set or repair the base mesh link for this bump object."""
    bl_idname  = "naomi.bump_set_partner"
    bl_label   = "Set Partner Mesh"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and _is_bump_mesh(obj)

    def execute(self, context):
        obj         = context.active_object
        new_partner = obj.naomi_param.bump_partner_obj   # set by the dialog picker
        if new_partner is None:
            self.report({'ERROR'}, "No base object selected.")
            return {'CANCELLED'}
        if new_partner == obj:
            self.report({'ERROR'}, "Cannot link an object to itself.")
            return {'CANCELLED'}
        # Clear old partner link if any
        old = _get_bump_partner(obj)
        if old is not None and old != new_partner:
            old.naomi_param.bump_partner_name = ""
            old.naomi_param.bump_partner_obj  = None
        # Wire — pointer update callback keeps the name string in sync
        obj.naomi_param.bump_partner_obj          = new_partner   # triggers _update_bump_partner_obj
        new_partner.naomi_param.bump_partner_name = obj.name
        new_partner.naomi_param.bump_partner_obj  = obj
        _apply_plain_mesh_params(new_partner)
        _sync_collection_flags(obj)
        self.report({'INFO'}, f"Linked: '{obj.name}' ↔ '{new_partner.name}'")
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        obj = context.active_object
        self.layout.prop(obj.naomi_param, "bump_partner_obj", text="Base Mesh")


# ---------------------------------------------------------------------------
# Generate normal map operator
# ---------------------------------------------------------------------------

class NAOMI_OT_bump_generate_normal_map(bpy.types.Operator):
    """Generate a bump-map normal texture from the base texture (Sobel height→normal)
and add it to the Texture Manager.  Skips if identical content already exists."""
    bl_idname  = "naomi.bump_generate_normal_map"
    bl_label   = "Generate"
    bl_options = {'REGISTER', 'UNDO'}

    strength: bpy.props.FloatProperty(
        name="Strength", default=2.0, min=0.1, max=20.0,
        description="Height-field scale factor for normal derivation")

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        # bump_obj  = mesh with naomi_flag_bump=True (holds the normal map)
        # regular_obj = the regular texture mesh (no bump flag)
        bump_obj    = obj if _is_bump_mesh(obj) else _get_bump_partner(obj)
        if bump_obj is None:
            return False
        regular_obj = _get_bump_partner(bump_obj)
        if regular_obj is None:
            return False
        # Active as long as the regular texture mesh has a texture assigned
        return int(regular_obj.naomi_param.mh_texID) >= 0

    def execute(self, context):
        import hashlib, math
        obj      = context.active_object
        bump_obj = obj if _is_bump_mesh(obj) else _get_bump_partner(obj)
        base = bump_obj  # alias kept for rest of function
        if base is None:
            return {'CANCELLED'}

        folder = _get_tex_folder(base)
        if not folder:
            self.report({'ERROR'}, "No texture folder set on this collection.")
            return {'CANCELLED'}

        # Source image: from the BASE/COLORED mesh (no bump flag)
        base_obj_for_gen = _get_bump_partner(bump_obj)
        if base_obj_for_gen is None:
            self.report({'ERROR'}, "No base mesh partner found.")
            return {'CANCELLED'}
        base_tex_id = int(base_obj_for_gen.naomi_param.mh_texID)
        if base_tex_id < 0:
            self.report({'ERROR'}, "Base mesh has no texture assigned.")
            return {'CANCELLED'}
        base_img    = None

        # Try by filepath basename first
        for img in bpy.data.images:
            if img.filepath:
                bn = os.path.splitext(os.path.basename(
                    bpy.path.abspath(img.filepath)))[0]
                if bn == f"TexID_{base_tex_id:03d}":
                    base_img = img
                    break

        # Fallback: try loading from folder
        if base_img is None:
            for ext in ('.png', '.bmp', '.jpg', '.jpeg'):
                candidate = os.path.join(folder, f"TexID_{base_tex_id:03d}{ext}")
                if os.path.exists(candidate):
                    base_img = bpy.data.images.load(candidate, check_existing=True)
                    break

        if base_img is None:
            self.report({'ERROR'},
                        f"Base texture TexID_{base_tex_id:03d} not found.")
            return {'CANCELLED'}

        # Force-load pixels
        base_img.pixels[0]          # triggers pixel buffer load
        W, H = base_img.size
        if W == 0 or H == 0:
            self.report({'ERROR'}, "Base texture has zero size.")
            return {'CANCELLED'}

        # Build greyscale height map from base texture pixels.
        raw = list(base_img.pixels)

        def lum(idx):
            """Luminance of pixel at flat RGBA index idx (already *4)."""
            r = raw[idx];  g = raw[idx+1];  b = raw[idx+2]
            # Rec.709 luminance
            return 0.2126*r + 0.7152*g + 0.0722*b

        # Sobel height→normal conversion.
        scale = self.strength
        out   = [0.0] * (W * H * 4)

        for y in range(H):
            for x in range(W):
                # Clamp-to-edge neighbours
                xm = max(x-1, 0);   xp = min(x+1, W-1)
                ym = max(y-1, 0);   yp = min(y+1, H-1)

                # Sample height values (8 neighbours + centre unused in Sobel)
                tl = lum((ym*W + xm)*4);  tc = lum((ym*W + x )*4);  tr = lum((ym*W + xp)*4)
                ml = lum(( y*W + xm)*4);                              mr = lum(( y*W + xp)*4)
                bl = lum((yp*W + xm)*4);  bc = lum((yp*W + x )*4);  br = lum((yp*W + xp)*4)

                # Sobel kernels
                dx = (tr + 2*mr + br) - (tl + 2*ml + bl)
                dy = (bl + 2*bc + br) - (tl + 2*tc + tr)

                # Surface normal (unnormalised)
                nx = -dx * scale
                ny = -dy * scale
                nz = 1.0

                # Normalise
                length = math.sqrt(nx*nx + ny*ny + nz*nz)
                if length > 0:
                    nx /= length;  ny /= length;  nz /= length

                # Encode to 0-1 range (normal map convention)
                base_i = (y*W + x)*4
                out[base_i  ] = nx * 0.5 + 0.5   # R
                out[base_i+1] = ny * 0.5 + 0.5   # G
                out[base_i+2] = nz * 0.5 + 0.5   # B
                out[base_i+3] = 1.0               # A

        # Deduplication: compare MD5 against existing folder images
        raw_bytes = bytes(min(255, max(0, int(v * 255))) for v in out)
        new_hash  = hashlib.md5(raw_bytes).hexdigest()

        existing_id = None
        for fname in os.listdir(folder):
            bname, ext = os.path.splitext(fname)
            if ext.lower() not in {'.bmp', '.png', '.jpg', '.jpeg'} or not bname.startswith('TexID_'):
                continue
            try:
                candidate_id = int(bname[6:])
            except ValueError:
                continue
            try:
                cand_img = bpy.data.images.load(
                    os.path.join(folder, fname), check_existing=True)
                cand_img.pixels[0]  # force load
                cand_bytes = bytes(
                    min(255, max(0, int(v * 255))) for v in cand_img.pixels)
                if hashlib.md5(cand_bytes).hexdigest() == new_hash:
                    existing_id = candidate_id
                    break
            except Exception:
                continue

        if existing_id is not None:
            # Assign duplicate to the bump object
            if base is not None:
                base.naomi_param.mh_texID = existing_id
                _apply_texture_params(base, has_texture=True)
                update_texture(base.naomi_param, context)
            # Ensure the reused slot is marked as BUMP in the TM
            col, tm = _get_col_tm(base)
            if tm is not None:
                for _item in tm.tex_list:
                    if _item.tex_id == existing_id:
                        _item.px_mode = 'bump'  # PIX_BUMP_MAP
                        break
            self.report({'INFO'},
                        f"Duplicate found — assigned existing TexID_{existing_id:03d}.")
            return {'FINISHED'}

        # Save new image
        new_id   = _next_tex_id(folder)
        new_path = os.path.join(folder, f"TexID_{new_id:03d}.bmp")

        new_img = bpy.data.images.new(
            f"TexID_{new_id:03d}", width=W, height=H, alpha=True, float_buffer=False)
        new_img.pixels = out
        new_img.filepath_raw = new_path
        new_img.file_format  = 'BMP'
        new_img.save()

        # Rebuild TM list
        col, tm = _get_col_tm(base)
        if tm is not None:
            _rebuild_tex_list(tm, folder, col=col)
            # Force the newly generated bump texture slot to PIX_BUMP_MAP pixel format
            for _item in tm.tex_list:
                if _item.tex_id == new_id:
                    _item.px_mode = 'bump'  # PIX_BUMP_MAP
                    break

        # Assign the new normal map to the BUMP object (naomi_flag_bump=True)
        if base is not None:
            base.naomi_param.mh_texID = new_id
            _apply_texture_params(base, has_texture=True)
            update_texture(base.naomi_param, context)

        self.report({'INFO'}, f"Normal map generated: TexID_{new_id:03d}.png ({W}×{H})")
        return {'FINISHED'}


class NAOMI_OT_assign_object_material(bpy.types.Operator):
    """Assign Naomi preset — opens preset chooser"""
    bl_idname = "naomi.assign_object_material"
    bl_label = "Assign Naomi Preset"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = [o for o in context.selected_objects if o.type == 'MESH'] \
                  or ([context.active_object] if context.active_object else [])
        for obj in targets:
            tex_image = _snapshot_tex_image(obj)
            _apply_lambert_preset(obj, tex_image=tex_image)   # default: Lambert
            for col in bpy.data.collections:
                if obj.name in col.objects and not col.naomi_centroidData.naomi_assigned:
                    col.naomi_centroidData.naomi_assigned = True
                    break
            _sync_collection_flags(obj)
        return {'FINISHED'}


class NAOMI_OT_assign_preset_lambert(bpy.types.Operator):
    """Lambert (Gouraud) shading — smooth lighting, no vertex colors"""
    bl_idname = "naomi.assign_preset_lambert"
    bl_label = "Lambert"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = [o for o in context.selected_objects if o.type == 'MESH'] \
                  or ([context.active_object] if context.active_object else [])
        for obj in targets:
            tex_image = _snapshot_tex_image(obj)
            _apply_lambert_preset(obj, tex_image=tex_image)
            for col in bpy.data.collections:
                if obj.name in col.objects and not col.naomi_centroidData.naomi_assigned:
                    col.naomi_centroidData.naomi_assigned = True
                    break
            _sync_collection_flags(obj)
        return {'FINISHED'}


class NAOMI_OT_assign_preset_flat(bpy.types.Operator):
    """Flat (Constant) shading — uniform face color, no lighting"""
    bl_idname = "naomi.assign_preset_flat"
    bl_label = "Flat"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = [o for o in context.selected_objects if o.type == 'MESH'] \
                  or ([context.active_object] if context.active_object else [])
        for obj in targets:
            tex_image = _snapshot_tex_image(obj)
            _apply_flat_preset(obj, tex_image=tex_image)
            for col in bpy.data.collections:
                if obj.name in col.objects and not col.naomi_centroidData.naomi_assigned:
                    col.naomi_centroidData.naomi_assigned = True
                    break
            _sync_collection_flags(obj)
        return {'FINISHED'}


class NAOMI_OT_assign_preset_vertex_colors(bpy.types.Operator):
    """Vertex Colors shading — creates a 'Col' vertex color layer ready to paint"""
    bl_idname = "naomi.assign_preset_vertex_colors"
    bl_label = "Vertex Colors"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = [o for o in context.selected_objects if o.type == 'MESH'] \
                  or ([context.active_object] if context.active_object else [])
        for obj in targets:
            tex_image = _snapshot_tex_image(obj)
            _apply_vertex_color_preset(obj, tex_image=tex_image)
            for col in bpy.data.collections:
                if obj.name in col.objects and not col.naomi_centroidData.naomi_assigned:
                    col.naomi_centroidData.naomi_assigned = True
                    break
            _sync_collection_flags(obj)
        return {'FINISHED'}


class NAOMI_OT_assign_preset_env_map(bpy.types.Operator):
    """Environment Map — spherical reflection mapping (Lambert + env-map UV).
Preserves any texture already assigned via the Texture Manager."""
    bl_idname = "naomi.assign_preset_env_map"
    bl_label  = "Env Map"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = [o for o in context.selected_objects if o.type == 'MESH'] \
                  or ([context.active_object] if context.active_object else [])
        for obj in targets:
            tex_image = _snapshot_tex_image(obj)
            _apply_env_map_preset(obj, tex_image=tex_image)
            for col in bpy.data.collections:
                if obj.name in col.objects and not col.naomi_centroidData.naomi_assigned:
                    col.naomi_centroidData.naomi_assigned = True
                    break
            _sync_collection_flags(obj)
        return {'FINISHED'}


def _apply_palette_preset(obj, tex_image=None):
    """Lambert shading with palettized 8-BPP texture."""
    _apply_lambert_preset(obj, tex_image=tex_image)
    p  = obj.naomi_param
    tc = obj.naomi_texCtrl
    tc.pixelFormat               = '6'   # PIX_8_PAL  (8 BPP, 256 colours)
    tc.scanOrder                 = '0'   # always twiddled for palette
    p.offsColorUsage             = '1'   # slot repurposed as palette bank reference
    p.naomi_flag_palette         = True


class NAOMI_OT_assign_preset_palette(bpy.types.Operator):
    """Palette preset — Lambert + palettized texture (8 BPP / 256-colour)."""
    bl_idname  = "naomi.assign_preset_palette"
    bl_label   = "Palette"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        targets = [o for o in context.selected_objects if o.type == 'MESH'] \
                  or ([context.active_object] if context.active_object else [])
        for obj in targets:
            tex_image = _snapshot_tex_image(obj)
            _apply_palette_preset(obj, tex_image=tex_image)
            for col in bpy.data.collections:
                if obj.name in col.objects and not col.naomi_centroidData.naomi_assigned:
                    col.naomi_centroidData.naomi_assigned = True
                    break
            _sync_collection_flags(obj)
        return {'FINISHED'}


class NAOMI_OT_remove_object_material(bpy.types.Operator):
    """Remove all Naomi properties from this object and reset to defaults"""
    bl_idname = "naomi.remove_object_material"
    bl_label = "Remove Naomi Properties"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj:
            _reset_object_props(obj)
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)


class NAOMI_OT_export_object_props(bpy.types.Operator, ExportHelper):
    """Export Naomi object properties to a JSON file"""
    bl_idname = "naomi.export_object_props"
    bl_label = "Export Naomi Object Props (.json)"
    bl_options = {'REGISTER'}
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "No active object.")
            return {'CANCELLED'}
        data = _object_props_to_dict(obj)
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            self.report({'INFO'}, f"Exported to {self.filepath}")
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class NAOMI_OT_import_object_props(bpy.types.Operator, ImportHelper):
    """Import Naomi object properties from a JSON file"""
    bl_idname = "naomi.import_object_props"
    bl_label = "Import Naomi Object Props (.json)"
    bl_options = {'REGISTER', 'UNDO'}
    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "No active object.")
            return {'CANCELLED'}
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _dict_to_object_props(obj, data)
            self.report({'INFO'}, f"Imported from {self.filepath}")
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Operators — COPY / PASTE OBJECT PROPS
# ---------------------------------------------------------------------------

_naomi_props_clipboard: dict = {}


class NAOMI_OT_copy_object_props(bpy.types.Operator):
    """Copy all Naomi properties from the active object to the clipboard"""
    bl_idname = "naomi.copy_object_props"
    bl_label = "Copy Naomi Properties"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        global _naomi_props_clipboard
        obj = context.active_object
        if not obj:
            self.report({'ERROR'}, "No active object.")
            return {'CANCELLED'}
        _naomi_props_clipboard = _object_props_to_dict(obj)
        self.report({'INFO'}, f"Copied Naomi properties from \"{obj.name}\".")
        return {'FINISHED'}


class NAOMI_OT_paste_object_props(bpy.types.Operator):
    """Paste copied Naomi properties to all selected objects"""
    bl_idname = "naomi.paste_object_props"
    bl_label = "Paste Naomi Properties"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(_naomi_props_clipboard) and any(
            obj for obj in context.selected_objects if obj.type == 'MESH'
        )

    def execute(self, context):
        global _naomi_props_clipboard
        if not _naomi_props_clipboard:
            self.report({'ERROR'}, "Clipboard is empty — copy first.")
            return {'CANCELLED'}
        targets = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not targets:
            self.report({'ERROR'}, "No mesh objects selected.")
            return {'CANCELLED'}

        np_ = _naomi_props_clipboard.get("naomi_param", {})
        shad   = np_.get("m_shad_type", "0")
        new_id = np_.get("mh_texID", -1)

        if shad == '-3':
            preset_fn = _apply_vertex_color_preset
        elif shad == '-1':
            preset_fn = _apply_flat_preset
        elif shad == '-2':
            preset_fn = _apply_bump_mesh_params
        else:
            preset_fn = _apply_lambert_preset

        global _material_rebuild_in_progress
        _material_rebuild_in_progress = True
        try:
            for obj in targets:
                preset_fn(obj)
                _dict_to_object_props(obj, _naomi_props_clipboard)
                if new_id >= 0:
                    _, tm = _get_col_tm(obj)
                    if tm is not None:
                        for item in tm.tex_list:
                            if item.tex_id == new_id and not item.is_empty:
                                _apply_texctrl_from_slot(obj, item)
                                break
        finally:
            _material_rebuild_in_progress = False

        for obj in targets:
            update_texture(obj.naomi_param, context)

        self.report({'INFO'}, f"Pasted Naomi properties to {len(targets)} object(s).")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Operators — COLLECTION
# ---------------------------------------------------------------------------

class NAOMI_OT_assign_collection_material(bpy.types.Operator):
    """Assign Naomi material properties to this collection"""
    bl_idname = "naomi.assign_collection_material"
    bl_label = "Assign Naomi Preset"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        col = context.view_layer.active_layer_collection.collection
        if col:
            col.naomi_centroidData.naomi_assigned = True
        return {'FINISHED'}


class NAOMI_OT_remove_collection_material(bpy.types.Operator):
    """Remove Naomi properties from this collection and reset all values to defaults"""
    bl_idname = "naomi.remove_collection_material"
    bl_label = "Remove Naomi Properties"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        col = context.view_layer.active_layer_collection.collection
        if col:
            _reset_collection_props(col)
        return {'FINISHED'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)


def _split_nonmanifold_edges(obj) -> int:
    """Split edges shared by >2 faces so each face pair gets its own edge copy. Returns split count."""
    import bmesh as _bmesh

    bm = _bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    bad_edges = [e for e in bm.edges if len(e.link_faces) > 2]

    n_splits = 0
    for edge in bad_edges:
        faces = list(edge.link_faces)
        # Keep faces[0]/[1] on original verts; reroute extras to new copies.
        for face in faces[2:]:
            new_verts = []
            for v in (edge.verts[0], edge.verts[1]):
                # Duplicate vertex — same position, same normal weight
                nv = bm.verts.new(v.co.copy())
                nv.normal = v.normal.copy()
                new_verts.append(nv)

            # Rebuild the face with the new vertices substituting the old ones
            old_v0, old_v1 = edge.verts[0], edge.verts[1]
            new_v0, new_v1 = new_verts[0], new_verts[1]

            # Map old vert → new vert for this face's loop
            remap = {old_v0: new_v0, old_v1: new_v1}
            new_face_verts = [remap.get(lv, lv) for lv in face.verts]

            # Copy loop UV / colour data before destroying the old face
            old_loops = list(face.loops)

            try:
                new_face = bm.faces.new(new_face_verts)
                new_face.smooth = face.smooth
                new_face.normal_update()

                # Copy layer data (UVs, vertex colours) loop-by-loop
                for layer in bm.loops.layers.uv.values():
                    for old_lp, new_lp in zip(old_loops, new_face.loops):
                        new_lp[layer].uv = old_lp[layer].uv.copy()
                for layer in bm.loops.layers.color.values():
                    for old_lp, new_lp in zip(old_loops, new_face.loops):
                        new_lp[layer] = old_lp[layer]

                bm.faces.remove(face)
                n_splits += 1
            except ValueError:
                # Face already exists with those verts (degenerate geometry);
                # remove the orphan verts just created and move on.
                bm.verts.remove(new_v0)
                bm.verts.remove(new_v1)

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return n_splits


# ---------------------------------------------------------------------------
# Collection panel
# ---------------------------------------------------------------------------

class COL_PT_collection_gps(bpy.types.Panel):
    _context_path = "collection"
    _property_type = bpy.types.Collection
    bl_label = "Naomi Global Parameters"
    bl_idname = "COL_PT_collection_gps"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "collection"

    @classmethod
    def poll(self, context):
        return context.view_layer.active_layer_collection is not None

    def draw(self, context):
        active = context.view_layer.active_layer_collection.collection
        layout = self.layout
        naomi_centroidData_p = active.naomi_centroidData

        # ---- Unassigned state: assign button + quick-import icon ----
        if not naomi_centroidData_p.naomi_assigned:
            layout.operator("naomi.assign_collection_material", icon='MATERIAL')
            return

        # ---- Header row: remove ----
        layout.operator("naomi.remove_collection_material", text="Reset", icon='FILE_REFRESH')
        layout.separator()

        layout.label(text="Global Parameters 0")
        gp_0 = active.gp0
        box = layout.box()
        box.prop(gp_0, "objFormat")

        layout.label(text="Global Parameters 1")
        gp_1 = active.gp1
        box = layout.box()
        row = box.row()
        row.prop(gp_1, "skp1stSrcOp")
        row.prop(gp_1, "envMap")
        row = box.row()
        row.prop(gp_1, "pltTex")
        row.prop(gp_1, "bumpMap")

        layout.label(text="OBJ Centroid Data")
        box = layout.box()
        row = box.row()
        row.label(text="Centroid X:")
        row.prop(naomi_centroidData_p, "centroid_x", text="")
        row = box.row()
        row.label(text="Centroid Y:")
        row.prop(naomi_centroidData_p, "centroid_y", text="")
        row = box.row()
        row.label(text="Centroid Z:")
        row.prop(naomi_centroidData_p, "centroid_z", text="")
        row = box.row()
        row.label(text="Bound Radius:")
        row.prop(naomi_centroidData_p, "collection_bound_radius", text="")

        # ---- Update Model File (only for imported collections) ----
        meta = active.naomi_import_meta
        if meta.source_filepath:
            layout.separator()
            box = layout.box()
            box.label(text="Source: " + os.path.basename(meta.source_filepath),
                      icon='FILE_TICK')
            op = box.operator("naomi.update_model_file", icon='EXPORT')
            op.recalculate_centroid = True
            box.prop(op, "recalculate_centroid")


# ---------------------------------------------------------------------------
# Object panel
# ---------------------------------------------------------------------------

class OBJECT_PT_Naomi_Properties(bpy.types.Panel):
    bl_label = "Naomi Properties"
    bl_idname = "OBJECT_PT_Naomi_Properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'
    bl_category = "NLTex"

    @classmethod
    def poll(self, context):
        return context.active_object is not None

    def draw(self, context):
        active = context.active_object
        layout = self.layout
        naomi_param_p = active.naomi_param
        naomi_tsp_p   = active.naomi_tsp

        # ---- Header row: remove | copy / paste | export / import — always visible ----
        header = layout.row(align=True)
        header.operator("naomi.remove_object_material", text="Remove", icon='X')
        header.separator()
        header.operator("naomi.copy_object_props", text="Copy", icon='COPYDOWN')
        header.operator("naomi.paste_object_props", text="Paste", icon='PASTEDOWN')
        header.separator()
        header.operator("naomi.export_object_props", text="", icon='EXPORT')
        header.operator("naomi.import_object_props", text="", icon='IMPORT')

        layout.separator()

        # ---- Preset chooser — 3 per row, 2 rows, uniform spacing ----
        layout.label(text="Assign Naomi Preset:", icon='MATERIAL')
        row1 = layout.row(align=True)
        row1.operator("naomi.assign_preset_lambert",       icon='LIGHT_SUN')
        row1.operator("naomi.assign_preset_flat",          icon='SHADING_SOLID')
        row1.operator("naomi.assign_preset_vertex_colors", icon='VPAINT_HLT')
        row2 = layout.row(align=True)
        row2.operator("naomi.assign_preset_env_map",       icon='WORLD')
        row2.operator("naomi.assign_preset_bump",          icon='NORMALS_FACE')
        row2.operator("naomi.assign_preset_palette",       icon='COLOR')

        if not naomi_param_p.naomi_assigned:
            return

        layout.separator()

        # ---- Per-mesh special-mode flags ----
        flags_box = layout.box()
        flags_box.label(text="Mesh Flags", icon='BOOKMARKS')
        flags_row = flags_box.row(align=True)
        flags_row.prop(naomi_param_p, "naomi_flag_two_sided")
        flags_row.prop(naomi_param_p, "naomi_flag_env_map")
        flags_row.prop(naomi_param_p, "naomi_flag_bump")
        flags_row.prop(naomi_param_p, "naomi_flag_palette")

        # =========================================================
        # NAOMI PARAMETERS — main (visible) section
        # =========================================================
        layout.label(text="Naomi Parameters")
        box = layout.box()

        # Centroid + Bound Radius
        row = box.row()
        row.label(text="Centroid X:")
        row.prop(naomi_param_p, "centroid_x", text="")
        row = box.row()
        row.label(text="Centroid Y:")
        row.prop(naomi_param_p, "centroid_y", text="")
        row = box.row()
        row.label(text="Centroid Z:")
        row.prop(naomi_param_p, "centroid_z", text="")
        row = box.row()
        row.label(text="Bound Radius:")
        row.prop(naomi_param_p, "bound_radius", text="")

        # Colors
        row = box.row()
        row.label(text="Base Color:")
        row.prop(naomi_param_p, "meshColor", text="")
        row = box.row()
        row.label(text="Offset Color:")
        row.prop(naomi_param_p, "meshOffsetColor", text="")

        # Texture
        row = box.row()
        row.label(text="Texture ID")
        if naomi_param_p.mh_texID < 0:
            row.label(text="No Texture")
            box.operator("naomi.add_texture", text="Add Texture", icon='ADD')
        else:
            row.prop(naomi_param_p, "mh_texID", text="")
            box.operator("naomi.remove_texture", text="Remove Texture", icon='REMOVE')

        # Bump Map Options — only on the mesh with naomi_flag_bump=True
        if naomi_param_p.naomi_flag_bump:
            regular_obj = _get_bump_partner(active)

            bmp_box = box.box()
            bmp_box.label(text="Bump Map Options", icon='NORMALS_FACE')

            bmp_box.label(text="Regular Mesh:")
            bmp_box.prop(active.naomi_param, "bump_partner_obj", text="", icon='OBJECT_DATA')
            if regular_obj is None:
                bmp_box.label(text="No regular mesh linked.", icon='ERROR')

            r_id = int(regular_obj.naomi_param.mh_texID) if regular_obj else -1
            if r_id >= 0:
                bmp_box.operator("naomi.bump_generate_normal_map",
                                 text="Generate Bump Texture", icon='SHADERFX')

        # Palette Options — only when naomi_flag_palette=True
        if naomi_param_p.naomi_flag_palette:
            pal_box = box.box()
            pal_box.label(text="Palette Options", icon='COLOR')
            row = pal_box.row()
            row.label(text="Palette ID:")
            row.prop(naomi_param_p, "naomi_pal_id", text="")

        # Select a Texture — opens thumbnail picker popup
        box.separator()
        box.operator("naomi.select_texture_popup", text="Select a Texture", icon='IMAGE_DATA')

        row = box.row()
        row.label(text="Shading Type")
        row.prop(naomi_param_p, "m_shad_type", text="")

        row = box.row()
        row.label(text="Specular Intensity:")
        if naomi_param_p.m_tex_shading >= 0:
            row.prop(naomi_param_p, "spec_int", text="")
        else:
            row.label(text="Not Specified")

        row = box.row()
        row.label(text="Ambient Light:")
        row.prop(naomi_param_p, "m_ambient_light", text="")

        # Quick Settings
        # Each dropdown has AUTO as the default. Choosing a specific value writes
        # it into the corresponding TSP field immediately (visible in Advanced too).
        # Switching back to AUTO restores the TSP field to the preset default and
        # triggers a material rebuild.
        box.separator()
        box.label(text="Quick Settings:", icon='SETTINGS')

        row = box.row()
        row.label(text="Fog:")
        row.prop(naomi_param_p, "qs_fog", text="")

        row = box.row()
        row.label(text="Texture Alpha:")
        row.prop(naomi_param_p, "qs_tex_alpha", text="")

        row = box.row()
        row.label(text="Color Clamp:")
        row.prop(naomi_param_p, "qs_color_clamp", text="")

        row = box.row()
        row.label(text="U/V Clamp:")
        row.prop(naomi_param_p, "qs_uv_clamp", text="")

        row = box.row()
        row.label(text="Filter Mode:")
        row.prop(naomi_param_p, "qs_filter", text="")

        row = box.row()
        row.label(text="SRC Alpha:")
        row.prop(naomi_param_p, "qs_src_alpha", text="")

        row = box.row()
        row.label(text="DST Alpha:")
        row.prop(naomi_param_p, "qs_dst_alpha", text="")

        row = box.row()
        row.label(text="Texture Shading:")
        row.prop(naomi_param_p, "qs_tex_shading", text="")

        # =========================================================
        # ADVANCED — collapsed sub-panel
        # =========================================================
        adv_header, adv_body = layout.panel(
            "naomi_advanced_params", default_closed=True
        )
        adv_header.label(text="Advanced Parameters", icon='PREFERENCES')

        if adv_body is not None:
            # Object Parameters
            adv_body.label(text="Parameters")
            adv_box = adv_body.box()

            adv_box.prop(naomi_param_p, "paramType")
            adv_box.prop(naomi_param_p, "endOfStrip")
            adv_box.prop(naomi_param_p, "listType")
            adv_box.prop(naomi_param_p, "grpEn")
            adv_box.prop(naomi_param_p, "stripLen")
            adv_box.prop(naomi_param_p, "usrClip")
            adv_box.prop(naomi_param_p, "shadow")
            adv_box.prop(naomi_param_p, "volume")
            adv_box.prop(naomi_param_p, "colType")
            adv_box.prop(naomi_param_p, "textureUsage")
            adv_box.prop(naomi_param_p, "offsColorUsage")
            adv_box.prop(naomi_param_p, "gouraudShdUsage")
            adv_box.prop(naomi_param_p, "uvDataSize")

            # ISP/TSP
            adv_body.label(text="ISP/TSP")
            naomi_isp_tsp_p = active.naomi_isp_tsp
            adv_box = adv_body.box()
            adv_box.prop(naomi_isp_tsp_p, "depthCompare")
            adv_box.prop(naomi_isp_tsp_p, "culling")
            adv_box.prop(naomi_isp_tsp_p, "zWrite")
            adv_box.prop(naomi_isp_tsp_p, "textureUsage")
            adv_box.prop(naomi_isp_tsp_p, "offsColorUsage")
            adv_box.prop(naomi_isp_tsp_p, "gouraudShdUsage")
            adv_box.prop(naomi_isp_tsp_p, "uvDataSize")
            adv_box.prop(naomi_isp_tsp_p, "cacheBypass")
            adv_box.prop(naomi_isp_tsp_p, "dCalcCtrl")

            # TSP
            adv_body.label(text="TSP")
            adv_box = adv_body.box()
            adv_box.prop(naomi_tsp_p, "srcAlpha")
            adv_box.prop(naomi_tsp_p, "dstAlpha")
            adv_box.prop(naomi_tsp_p, "srcSelect")
            adv_box.prop(naomi_tsp_p, "dstSelect")
            adv_box.prop(naomi_tsp_p, "fogOp")
            adv_box.prop(naomi_tsp_p, "colorClamp")
            adv_box.prop(naomi_tsp_p, "alphaOp")
            adv_box.prop(naomi_tsp_p, "alphaTexOp")
            adv_box.prop(naomi_tsp_p, "uvFlip")
            adv_box.prop(naomi_tsp_p, "uvClamp")
            adv_box.prop(naomi_tsp_p, "filter")
            adv_box.prop(naomi_tsp_p, "supSample")
            adv_box.prop(naomi_tsp_p, "mipmapDAdj")
            adv_box.prop(naomi_tsp_p, "texShading")
            adv_box.prop(naomi_tsp_p, "texUSize")
            adv_box.prop(naomi_tsp_p, "texVSize")

            # Texture Control
            adv_body.label(text="Texture Control")
            naomi_tex_ctrl = active.naomi_texCtrl
            adv_box = adv_body.box()
            row = adv_box.row()
            row.prop(naomi_tex_ctrl, "mipMapped")
            row.prop(naomi_tex_ctrl, "vqCompressed")
            adv_box.prop(naomi_tex_ctrl, "pixelFormat")
            adv_box.prop(naomi_tex_ctrl, "scanOrder")
            adv_box.prop(naomi_tex_ctrl, "texCtrlUstride")

# ---------------------------------------------------------------------------
# Operator — open the Texture Manager panel in the Properties area
# ---------------------------------------------------------------------------

class NAOMI_OT_open_texture_manager(bpy.types.Operator):
    """Select the active object's parent Naomi collection and open Collection Properties"""
    bl_idname  = "naomi.open_texture_manager"
    bl_label   = "Texture Manager"
    bl_options = {'REGISTER', 'INTERNAL'}

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            self.report({'WARNING'}, "No active object.")
            return {'CANCELLED'}

        # Find the parent Naomi collection for this object
        target_col = _get_col_for_obj(obj)
        if target_col is None:
            self.report({'WARNING'}, "Object is not in a Naomi collection.")
            return {'CANCELLED'}

        # Walk the view-layer tree to find and activate the matching LayerCollection.
        def _find_layer_col(layer_col, collection):
            if layer_col.collection == collection:
                return layer_col
            for child in layer_col.children:
                found = _find_layer_col(child, collection)
                if found is not None:
                    return found
            return None

        root = context.view_layer.layer_collection
        lc   = _find_layer_col(root, target_col)
        if lc is not None:
            context.view_layer.active_layer_collection = lc

        # Switch every Properties area to the Collection context.
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                for space in area.spaces:
                    if space.type == 'PROPERTIES':
                        try:
                            space.context = 'COLLECTION'
                        except Exception:
                            pass
                        break

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Naomi Texture Manager — dedicated collection panel
# ---------------------------------------------------------------------------

def _draw_texture_manager(layout, context):
    """Draw the full Texture Manager UI into layout."""
    obj = context.active_object
    if obj is None:
        layout.label(text="No active object.", icon='INFO')
        return

    col_obj = _get_col_for_obj(obj)
    tm      = col_obj.naomi_tm if col_obj is not None else None

    if tm is None:
        layout.label(text="Active object is not in a Naomi collection.", icon='ERROR')
        return

    folder = _get_tex_folder(obj)

    # Folder picker
    layout.operator("naomi.tm_set_folder", text="Set 'Textures' Folder", icon='FILE_FOLDER')

    # Controls row: Apply | Refresh
    ctrl_row = layout.row(align=True)
    ctrl_row.operator("naomi.tm_apply_selection", text="Apply",   icon='CHECKMARK')
    ctrl_row.operator("naomi.tm_refresh",         text="Refresh", icon='FILE_REFRESH')

    if not folder:
        layout.label(text="No folder set — click above to choose.", icon='ERROR')
        return

    n_items    = len(tm.tex_list)
    rows_vis   = 16         # must match template_list maxrows= below
    has_scroll = n_items > rows_vis
    hdr_outer = layout.row(align=False)
    hdr_outer.enabled = False

    if has_scroll:
        f_thumb, f_id, f_fmts = 0.08, 0.14, 0.81
        hdr = hdr_outer.split(factor=0.93)
    else:
        f_thumb, f_id, f_fmts = 0.08, 0.14, 0.84
        hdr = hdr_outer.split(factor=1.0)
    hs1 = hdr.split(factor=f_thumb)
    hs1.label(text="")
    hs2 = hs1.split(factor=f_id)
    r2 = hs2.row(); r2.alignment = 'CENTER'; r2.label(text="ID", translate=False)
    hs3 = hs2.split(factor=f_fmts)

    hs_fmt = hs3.split(factor=0.50)
    fl = hs_fmt.row(); fl.alignment = 'CENTER'; fl.label(text="TexFmt", translate=False)
    fr = hs_fmt.row(); fr.alignment = 'CENTER'; fr.label(text="PixFmt", translate=False)
    r5 = hs3.row(); r5.alignment = 'CENTER'; r5.label(text="Mips", translate=False)

    global _naomi_tm_has_scroll
    _naomi_tm_has_scroll = has_scroll
    # List
    layout.template_list(
        "NAOMI_UL_texture_list", "",
        tm, "tex_list",
        tm, "tex_list_index",
        rows=8, maxrows=16,
        type='DEFAULT',
    )

    # Action buttons
    act_row = layout.row(align=True)
    act_row.operator("naomi.tm_add",     text="Add",     icon='ADD')
    act_row.operator("naomi.tm_replace", text="Replace", icon='FILE_REFRESH')
    act_row.operator("naomi.tm_delete",  text="Delete",  icon='TRASH')
    layout.operator("naomi.tm_encode_all", text="Encode PVR", icon='EXPORT')


class VIEW3D_PT_Naomi_Texture_Manager(bpy.types.Panel):
    """Naomi Texture Manager — 3D Viewport N-panel sidebar."""
    bl_label       = "Naomi Textures"
    bl_idname      = "VIEW3D_PT_Naomi_Texture_Manager"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "NLTex"
    bl_options     = set()  # expanded by default

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        col = _get_col_for_obj(obj)
        if col is None:
            return False
        return getattr(col, 'naomi_centroidData', None) is not None and \
               col.naomi_centroidData.naomi_assigned

    def draw(self, context):
        _draw_texture_manager(self.layout, context)


# ---------------------------------------------------------------------------
# Bump Map Options subpanel
# ---------------------------------------------------------------------------

class OBJECT_PT_Naomi_Bump(bpy.types.Panel):
    """Bump Map Options — compact panel, visible only when Bump flag is set."""
    bl_label       = "Bump Map Options"
    bl_idname      = "OBJECT_PT_Naomi_Bump"
    bl_space_type  = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context     = 'object'
    bl_parent_id   = "OBJECT_PT_Naomi_Properties"
    bl_options     = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            return False
        p = getattr(obj, 'naomi_param', None)
        if p is None or not p.naomi_assigned:
            return False
        return _is_bump_mesh(obj)

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        # Only the bump-flag mesh gets these options
        if not _is_bump_mesh(obj):
            return

        regular_obj = _get_bump_partner(obj)  # the regular texture mesh

        # Partner link picker
        layout.label(text="Regular Mesh:")
        layout.prop(obj.naomi_param, "bump_partner_obj", text="", icon='OBJECT_DATA')
        if regular_obj is None:
            layout.label(text="No regular mesh linked.", icon='ERROR')

        layout.separator(factor=0.5)

        # Generate button — active whenever the regular texture mesh has a texture
        r_id = int(regular_obj.naomi_param.mh_texID) if regular_obj else -1
        if r_id >= 0:
            layout.operator("naomi.bump_generate_normal_map",
                            text="Generate Bump Texture", icon='SHADERFX')
        else:
            layout.label(text="Assign texture to regular mesh first.", icon='INFO')


# ---------------------------------------------------------------------------
# Operators — set / clear palette ID
# ---------------------------------------------------------------------------

class NAOMI_OT_palette_id_set(bpy.types.Operator):
    """Set the Palette ID for this mesh (index into PalID_XXX.pvp/.pal files)"""
    bl_idname  = "naomi.palette_id_set"
    bl_label   = "Set Palette ID"
    bl_options = {'REGISTER', 'UNDO'}

    pal_id: bpy.props.IntProperty(name="Palette ID", default=0, min=0)

    def invoke(self, context, event):
        obj = context.active_object
        if obj and hasattr(obj, 'naomi_param'):
            self.pal_id = obj.naomi_param.naomi_pal_id
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "pal_id")

    def execute(self, context):
        obj = context.active_object
        if obj and hasattr(obj, 'naomi_param'):
            obj.naomi_param.naomi_pal_id = self.pal_id
        return {'FINISHED'}


class NAOMI_OT_palette_id_clear(bpy.types.Operator):
    """Reset the Palette ID to 0 (default — PalID_000.pvp/.pal)"""
    bl_idname  = "naomi.palette_id_clear"
    bl_label   = "Reset Palette ID"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and hasattr(obj, 'naomi_param'):
            obj.naomi_param.naomi_pal_id = 0
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Operator — Update Model File (collection panel button)
# ---------------------------------------------------------------------------

class NAOMI_OT_update_model_file(bpy.types.Operator):
    """Overwrite the original imported .bin file with current mesh edits.
Only available for collections imported via the NaomiLib importer."""
    bl_idname  = "naomi.update_model_file"
    bl_label   = "Update Model File"
    bl_options = {'REGISTER', 'UNDO'}

    recalculate_centroid: bpy.props.BoolProperty(
        name="Recalculate Centroid",
        description="Recalculate centroids before export",
        default=True,
    )

    def execute(self, context):
        import traceback

        # Resolve collection: prefer active layer collection, fall back to active object.
        alc = context.view_layer.active_layer_collection
        selected_collection = alc.collection if alc else None

        if selected_collection is None or selected_collection == context.scene.collection:
            active_obj = context.active_object
            if active_obj and active_obj.users_collection:
                for c in active_obj.users_collection:
                    if c != context.scene.collection:
                        selected_collection = c
                        break
                else:
                    self.report({'ERROR'},
                        "Cannot determine target collection. "
                        "Select a specific imported collection or an object within it.")
                    return {'CANCELLED'}
            else:
                self.report({'ERROR'},
                    "No object or collection selected. "
                    "Select an imported collection or an object within it.")
                return {'CANCELLED'}

        if not hasattr(selected_collection, 'naomi_import_meta') or                 not selected_collection.naomi_import_meta.source_filepath:
            self.report({'ERROR'},
                f"Collection '{selected_collection.name}' was not imported "
                f"from a NaomiLib file.")
            return {'CANCELLED'}

        filepath = selected_collection.naomi_import_meta.source_filepath
        try:
            NLe.update_naomi_bin(filepath, selected_collection,
                                 update_centroids=self.recalculate_centroid)
            selected_collection.naomi_import_meta.source_crc32 = NLe.calculate_crc32(filepath)
            self.report({'INFO'}, f"Updated {filepath}")
        except Exception as e:
            self.report({'ERROR'}, str(e))
            traceback.print_exc()
            return {'CANCELLED'}
        return {'FINISHED'}

# ---------------------------------------------------------------------------
# UIList — one row per TexID slot
# ---------------------------------------------------------------------------

class NAOMI_UL_texture_list(bpy.types.UIList):
    bl_idname = "NAOMI_UL_texture_list"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        label = f"{item.tex_id:03d}"
        if item.is_empty:
            row = layout.row(align=False)
            row.label(text=label + "  — empty —", icon='X')
            return

        abs_fp = item.filepath
        key    = os.path.normcase(abs_fp) if abs_fp else ""

        icon_id = 0
        if _TM_PREVIEWS is not None and key:
            if key in _TM_PREVIEWS:
                icon_id = _TM_PREVIEWS[key].icon_id
            elif abs_fp and os.path.isfile(abs_fp):
                icon_id = _tm_previews_load(abs_fp)
                if context and context.area:
                    context.area.tag_redraw()

        row = layout.row(align=False)

        has_scroll = _naomi_tm_has_scroll
        if has_scroll:
            f_thumb, f_id, f_fmts = 0.08, 0.14, 0.81
        else:
            f_thumb, f_id, f_fmts = 0.08, 0.14, 0.84
        sp1 = row.split(factor=f_thumb)
        if icon_id:
            sp1.label(text="", icon_value=icon_id)
        else:
            sp1.label(text="", icon="IMAGE_DATA")
        sp2 = sp1.split(factor=f_id)
        id_row = sp2.row(); id_row.alignment = 'CENTER'; id_row.label(text=label)
        sp3 = sp2.split(factor=f_fmts)
        fmt_row = sp3.row(align=True)
        fmt_row.prop(item, "tex_mode", text="")
        fmt_row.prop(item, "px_mode", text="")
        mips_row = sp3.row()
        mips_row.alignment = 'CENTER'
        mips_row.prop(item, "use_mips", text="")

    def filter_items(self, context, data, propname):
        return [], []


# ---------------------------------------------------------------------------
# Refresh operator — rescans folder → rebuilds tex_list collection
# ---------------------------------------------------------------------------

class NAOMI_OT_tm_select(bpy.types.Operator):
    """Select a texture slot by index"""
    bl_idname = "naomi.tm_select"
    bl_label = "Select Texture"
    bl_options = {'REGISTER', 'INTERNAL'}
    index: bpy.props.IntProperty()

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        _, tm = _get_col_tm(obj)
        if tm is None:
            return {'CANCELLED'}
        tm.tex_list_index = self.index
        return {'FINISHED'}


class NAOMI_OT_tm_drag_scroll(bpy.types.Operator):
    """Click and drag to scroll the texture list"""
    bl_idname = "naomi.tm_drag_scroll"
    bl_label  = "Drag Scroll"
    bl_options = {'INTERNAL'}

    track_units: bpy.props.IntProperty(default=8)

    def invoke(self, context, event):
        self._start_y   = event.mouse_y
        self._start_scr = self._get_scroll(context)
        self._n         = self._get_n(context)
        self._dragging  = True          # mouse is down right now
        context.window.cursor_modal_set('SCROLL_Y')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self._finish(context)
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            obj = context.active_object
            if obj:
                _, tm = _get_col_tm(obj)
                if tm:
                    tm.tex_scroll = self._start_scr
            self._finish(context)
            return {'CANCELLED'}

        if event.type == 'MOUSEMOVE' and self._dragging:
            obj = context.active_object
            if not obj:
                self._finish(context)
                return {'CANCELLED'}
            _, tm = _get_col_tm(obj)
            if tm is None:
                self._finish(context)
                return {'CANCELLED'}

            n           = self._n
            MAX_VISIBLE = 10
            max_scroll  = max(1, n - MAX_VISIBLE)
            track_units = max(1, self.track_units)

            TOTAL_UNITS = 100
            thumb_u  = max(5, round(TOTAL_UNITS * MAX_VISIBLE / n)) if n > MAX_VISIBLE else TOTAL_UNITS
            usable_u = max(1, TOTAL_UNITS - thumb_u)

            ROW_PX   = 22
            usable_px = usable_u * track_units * ROW_PX / TOTAL_UNITS
            if usable_px < 1:
                return {'RUNNING_MODAL'}

            dy    = self._start_y - event.mouse_y   # positive = dragged down
            delta = round(dy / usable_px * max_scroll)
            tm.tex_scroll = max(0, min(self._start_scr + delta, max_scroll))
            for area in context.screen.areas:
                area.tag_redraw()

        return {'RUNNING_MODAL'}

    def _finish(self, context):
        context.window.cursor_modal_restore()

    @staticmethod
    def _get_scroll(context):
        obj = context.active_object
        if not obj:
            return 0
        _, tm = _get_col_tm(obj)
        return tm.tex_scroll if tm else 0

    @staticmethod
    def _get_n(context):
        obj = context.active_object
        if not obj:
            return 0
        _, tm = _get_col_tm(obj)
        return len(tm.tex_list) if tm else 0


class NAOMI_OT_tm_scroll(bpy.types.Operator):
    """Scroll the texture list up or down by one step"""
    bl_idname = "naomi.tm_scroll"
    bl_label = "Scroll Texture List"
    bl_options = {'INTERNAL'}
    delta: bpy.props.IntProperty()

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        _, tm = _get_col_tm(obj)
        if tm is None:
            return {'CANCELLED'}
        n = len(tm.tex_list)
        if n == 0:
            return {'CANCELLED'}
        tm.tex_list_index = max(0, min(tm.tex_list_index + self.delta, n - 1))
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


class NAOMI_OT_tm_scroll_to(bpy.types.Operator):
    """Jump the texture list to an absolute scroll position"""
    bl_idname  = "naomi.tm_scroll_to"
    bl_label   = "Scroll To"
    bl_options = {'INTERNAL'}
    position: bpy.props.IntProperty()

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        _, tm = _get_col_tm(obj)
        if tm is None:
            return {'CANCELLED'}
        n = len(tm.tex_list)
        MAX_VISIBLE = 10
        tm.tex_scroll = max(0, min(self.position, max(0, n - MAX_VISIBLE)))
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


class NAOMI_OT_tm_refresh(bpy.types.Operator):
    """Rescan the texture folder and rebuild the list"""
    bl_idname = "naomi.tm_refresh"
    bl_label = "Refresh"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or not hasattr(obj, "naomi_param"):
            return {'CANCELLED'}
        col, tm = _get_col_tm(obj)
        if tm is None:
            self.report({'WARNING'}, "Object is not in a Naomi collection.")
            return {'CANCELLED'}
        folder = _get_tex_folder(obj)
        if not folder:
            self.report({'WARNING'}, "No texture folder set.")
            return {'CANCELLED'}

        decoded, errors = _decode_all_pvrs_in_folder(folder, skip_existing=True)
        if decoded:
            self.report({'INFO'}, f"[NaomiLib] Decoded {decoded} PVR(s)")
        for err in errors:
            self.report({'WARNING'}, f"[NaomiLib] {err}")

        _update_pvr_log_from_folder(folder)
        _refresh_shared_folder_objects(obj, folder)

        n = len(tm.tex_list)
        MAX_VISIBLE = 10
        tm.tex_scroll = max(0, min(tm.tex_scroll, max(0, n - MAX_VISIBLE)))
        return {'FINISHED'}


def _get_col_for_obj(obj):
    """Return the first Naomi-assigned collection that contains obj, or None."""
    for col in bpy.data.collections:
        if obj.name in col.objects and col.naomi_centroidData.naomi_assigned:
            return col
    return None


def _get_col_tm(obj):
    """Return (collection, naomi_tm) for obj, or (None, None)."""
    col = _get_col_for_obj(obj)
    if col is not None:
        return col, col.naomi_tm
    return None, None


def _get_tex_folder(obj):
    """Return the texture folder from obj's parent Naomi collection.
    Falls back to inferring from loaded images if no folder is set on the collection."""
    col, tm = _get_col_tm(obj)
    if tm is not None:
        folder = tm.tex_folder
        if folder and os.path.isdir(bpy.path.abspath(folder)):
            return bpy.path.abspath(folder)
    # Legacy / inference fallback — scan object's material slots
    for ms in obj.material_slots:
        mat = ms.material
        if not (mat and mat.use_nodes and mat.node_tree):
            continue
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image and node.image.filepath:
                d = os.path.dirname(bpy.path.abspath(node.image.filepath))
                if d:
                    return d
    return ""


# Image formats Blender can load — all are valid as decoded PVR companions.
_TEX_IMAGE_EXTS = frozenset({
    '.bmp', '.png', '.jpg', '.jpeg', '.gif', '.tga', '.tif', '.tiff',
    '.exr', '.hdr', '.webp', '.rgb', '.sgi',
})
_FILTER_GLOB_IMAGES = "*.bmp;*.png;*.jpg;*.jpeg;*.gif;*.tga;*.tif;*.tiff;*.exr;*.hdr;*.webp"


def _scan_tex_folder(folder):
    """Return list of (tex_id, filepath_or_None) for every TexID_NNN image in folder."""
    if not folder or not os.path.isdir(folder):
        return []
    pattern_map = {}
    for fname in os.listdir(folder):
        base, ext = os.path.splitext(fname)
        if ext.lower() not in _TEX_IMAGE_EXTS:
            continue
        if base.startswith('TexID_') and len(base) == 9:
            try:
                idx = int(base[6:])
                pattern_map[idx] = os.path.join(folder, fname)
            except ValueError:
                pass
    if not pattern_map:
        return []
    max_id = max(pattern_map.keys())
    return [(i, pattern_map.get(i)) for i in range(max_id + 1)]


def _next_tex_id(folder):
    """Return the next available TexID number (max existing + 1, or 0)."""
    slots = _scan_tex_folder(folder)
    filled = [tid for tid, fp in slots if fp is not None]
    return (max(filled) + 1) if filled else 0


def _rebuild_tex_list(tm, folder, col=None):
    """Rebuild tm.tex_list from folder scan, populate previews, and read PVR headers."""
    bump_ids = set()
    if col is None:
        # Fallback: match by folder path when caller doesn't pass col
        for _col in bpy.data.collections:
            if not (getattr(_col, 'naomi_centroidData', None)
                    and _col.naomi_centroidData.naomi_assigned):
                continue
            if _col.naomi_tm.tex_folder and _col.naomi_tm.tex_folder == tm.tex_folder:
                col = _col
                break
    if col is not None:
        for obj in col.objects:
            p = getattr(obj, 'naomi_param', None)
            if (p is not None
                    and getattr(p, 'naomi_assigned', False)
                    and getattr(p, 'naomi_flag_bump', False)):
                tex_id = int(getattr(p, 'mh_texID', -1))
                if tex_id >= 0:
                    bump_ids.add(tex_id)
    _tm_previews_clear()
    tm.tex_list.clear()
    abs_folder = bpy.path.abspath(folder) if folder else folder
    for tex_id, filepath in _scan_tex_folder(folder):
        item = tm.tex_list.add()
        item.tex_id = tex_id
        item.filepath = filepath or ""
        item.is_empty = (filepath is None)
        # Auto-read .PVR header for tex_mode / px_mode; fall back to image analysis
        pvr_info = _read_pvr_header(abs_folder, tex_id) if abs_folder else None
        if pvr_info:
            item.tex_mode = pvr_info[0]
            item.px_mode  = pvr_info[1]
            item.use_mips = pvr_info[2]
            item.pvr_detected = True
            # Read dimensions from PVR file directly (bl_pypvr writes them at PVRT+0x0A/C)
            pvr_path = os.path.join(abs_folder, f"TexID_{tex_id:03d}.PVR")
            try:
                with open(pvr_path, 'rb') as _f:
                    _pvr_data = _f.read(0x20)
                _w, _h = _pvr_dims_from_bytes(_pvr_data)
                if _w > 0 and _h > 0:
                    item.tex_width  = _w
                    item.tex_height = _h
            except Exception:
                pass
        else:
            # No .PVR — infer best format from image content (PyPVR auto_format logic)
            inferred = _infer_format_from_image(bpy.path.abspath(filepath)) if filepath else None
            if inferred:
                item.tex_mode = inferred[0]
                item.px_mode  = inferred[1]
            else:
                item.tex_mode = 'tw'
            item.use_mips = False
            item.pvr_detected = False
        # Restore bump pixel format if this slot was marked as bump before the rebuild
        if tex_id in bump_ids:
            item.px_mode = 'bump'
        if filepath:
            abs_fp = bpy.path.abspath(filepath)
            _tm_previews_load(abs_fp)  # load into PreviewCollection now


def _refresh_shared_folder_objects(changed_obj, folder):
    """Rebuild tex_list on every Naomi collection whose folder matches."""
    norm = os.path.normcase(os.path.normpath(folder))
    for col in bpy.data.collections:
        if not col.naomi_centroidData.naomi_assigned:
            continue
        tm = col.naomi_tm
        col_folder = tm.tex_folder
        if not col_folder:
            continue
        abs_col = bpy.path.abspath(col_folder)
        if not abs_col:
            continue
        if os.path.normcase(os.path.normpath(abs_col)) == norm:
            _rebuild_tex_list(tm, folder, col=col)
            if tm.tex_list_index >= len(tm.tex_list):
                tm.tex_list_index = max(0, len(tm.tex_list) - 1)


class NAOMI_OT_add_texture(bpy.types.Operator):
    """Set Texture ID to the first available slot in the Texture Manager (enable texture)"""
    bl_idname = "naomi.add_texture"
    bl_label = "Add Texture"
    bl_options = {'REGISTER', 'UNDO'}

    @staticmethod
    def _first_tex_id(obj):
        """Return the tex_id of the first non-empty slot in the TM, or 0 as fallback."""
        col, tm = _get_col_tm(obj)
        if tm is not None:
            for item in tm.tex_list:
                if not item.is_empty and item.filepath:
                    return item.tex_id
        return 0

    def execute(self, context):
        obj = context.active_object
        if not (obj and hasattr(obj, "naomi_param")):
            return {'CANCELLED'}
        new_id = self._first_tex_id(obj)
        obj.naomi_param.mh_texID = new_id
        _apply_texture_params(obj, has_texture=True)
        return {'FINISHED'}

    def invoke(self, context, event):
        obj = context.active_object
        if not (obj and hasattr(obj, "naomi_param")):
            return {'CANCELLED'}

        if not _get_tex_folder(obj):
            bpy.ops.naomi.tm_set_folder('INVOKE_DEFAULT', from_add_texture=True)
            return {'FINISHED'}
        new_id = self._first_tex_id(obj)
        obj.naomi_param.mh_texID = new_id
        _apply_texture_params(obj, has_texture=True)
        return {'FINISHED'}


class NAOMI_OT_remove_texture(bpy.types.Operator):
    """Set Texture ID to -1 (disable texture)"""
    bl_idname = "naomi.remove_texture"
    bl_label = "Remove Texture"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and hasattr(obj, "naomi_param"):
            obj.naomi_param.mh_texID = -1
            _apply_texture_params(obj, has_texture=False)
            update_texture(obj.naomi_param, context)
        return {'FINISHED'}


class NAOMI_OT_tm_add(bpy.types.Operator, ImportHelper):
    """Add one or more images as the next TexID slots"""
    bl_idname = "naomi.tm_add"
    bl_label = "Add Image"
    bl_options = {'REGISTER', 'UNDO'}
    filter_glob: StringProperty(default=_FILTER_GLOB_IMAGES, options={'HIDDEN'})
    directory: bpy.props.StringProperty(subtype='DIR_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    files: bpy.props.CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        col, tm = _get_col_tm(obj)
        if tm is None:
            self.report({'ERROR'}, "Object is not in a Naomi collection.")
            return {'CANCELLED'}
        folder = _get_tex_folder(obj)
        if not folder:
            self.report({'ERROR'}, "No texture folder set.")
            return {'CANCELLED'}

        base_dir = self.directory or os.path.dirname(self.filepath)

        if self.files and any(f.name for f in self.files):
            src_paths = [os.path.join(base_dir, f.name) for f in self.files if f.name]
        else:
            src_paths = [self.filepath]

        last_new_id = None
        added = []
        for src in src_paths:
            new_id = _next_tex_id(folder)
            ext = os.path.splitext(src)[1].lower()
            dst_name = f"TexID_{new_id:03d}{ext}"
            dst_path = os.path.join(folder, dst_name)
            try:
                shutil.copy(src, dst_path)
                unique_time = time.time() + new_id * 0.01
                os.utime(dst_path, (unique_time, unique_time))
            except Exception as e:
                self.report({'ERROR'}, f"Copy failed for {os.path.basename(src)}: {e}")
                continue
            added.append(dst_name)
            last_new_id = new_id

        if not added:
            return {'CANCELLED'}

        _refresh_shared_folder_objects(obj, folder)
        if last_new_id is not None:
            tm.tex_list_index = min(last_new_id, len(tm.tex_list) - 1)
        if obj.naomi_param.mh_texID < 0 and last_new_id is not None:
            obj.naomi_param["mh_texID"] = last_new_id

        if len(added) == 1:
            self.report({'INFO'}, f"Added {added[0]}")
        else:
            self.report({'INFO'}, f"Added {len(added)} textures ({added[0]} … {added[-1]})")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class NAOMI_OT_tm_replace(bpy.types.Operator, ImportHelper):
    """Replace the selected TexID slot with a new image (keeps same ID)"""
    bl_idname = "naomi.tm_replace"
    bl_label = "Replace Image"
    bl_options = {'REGISTER', 'UNDO'}
    filter_glob: StringProperty(default=_FILTER_GLOB_IMAGES, options={'HIDDEN'})

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'WARNING'}, "No slot selected.")
            return {'CANCELLED'}
        col, tm = _get_col_tm(obj)
        if tm is None:
            self.report({'ERROR'}, "Object is not in a Naomi collection.")
            return {'CANCELLED'}
        if not (0 <= tm.tex_list_index < len(tm.tex_list)):
            self.report({'WARNING'}, "No slot selected.")
            return {'CANCELLED'}
        folder = _get_tex_folder(obj)
        if not folder:
            self.report({'ERROR'}, "No texture folder set.")
            return {'CANCELLED'}
        item = tm.tex_list[tm.tex_list_index]
        tid = item.tex_id
        ext = os.path.splitext(self.filepath)[1].lower()
        for old_ext in ('.bmp', '.png'):
            old = os.path.join(folder, f"TexID_{tid:03d}{old_ext}")
            if os.path.exists(old):
                os.remove(old)
        dst_name = f"TexID_{tid:03d}{ext}"
        dst_path = os.path.join(folder, dst_name)
        try:
            import shutil
            shutil.copy2(self.filepath, dst_path)
            for img in bpy.data.images:
                if os.path.normcase(bpy.path.abspath(img.filepath)) == os.path.normcase(dst_path):
                    img.reload()
                    break
        except Exception as e:
            self.report({'ERROR'}, f"Replace failed: {e}")
            return {'CANCELLED'}
        _refresh_shared_folder_objects(obj, folder)
        self.report({'INFO'}, f"Replaced TexID_{tid:03d}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class NAOMI_OT_tm_delete(bpy.types.Operator):
    """Delete the selected TexID image and its companion .PVR/.PVP (slot kept as empty).
Removing the .PVR prevents it from being re-decoded on the next Refresh."""
    bl_idname = "naomi.tm_delete"
    bl_label = "Delete Image"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            self.report({'WARNING'}, "No slot selected.")
            return {'CANCELLED'}
        col, tm = _get_col_tm(obj)
        if tm is None:
            self.report({'ERROR'}, "Object is not in a Naomi collection.")
            return {'CANCELLED'}
        if not (0 <= tm.tex_list_index < len(tm.tex_list)):
            self.report({'WARNING'}, "No slot selected.")
            return {'CANCELLED'}
        folder = _get_tex_folder(obj)
        if not folder:
            self.report({'ERROR'}, "No texture folder set.")
            return {'CANCELLED'}
        item = tm.tex_list[tm.tex_list_index]
        tid = item.tex_id
        stem = f"TexID_{tid:03d}"
        deleted = False
        # Delete the image file (any format)
        for ext in _TEX_IMAGE_EXTS:
            path = os.path.join(folder, stem + ext)
            if os.path.exists(path):
                os.remove(path)
                deleted = True
        # Delete the companion .PVR and .PVP so Refresh won't re-decode them
        for ext in ('.PVR', '.PVP'):
            path = os.path.join(folder, stem + ext)
            if os.path.exists(path):
                os.remove(path)
        if deleted:
            self.report({'INFO'}, f"Deleted {stem} (image + PVR)")
            _refresh_shared_folder_objects(obj, folder)
        else:
            self.report({'WARNING'}, "Slot was already empty.")
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# PVR encode helpers
# ---------------------------------------------------------------------------


# pvr_log.txt helpers

def _pvr_log_path(folder):
    """Return the path to pvr_log.txt inside *folder*."""
    return os.path.join(folder, 'pvr_log.txt')


def _pvr_crc32(filepath):
    """Return the CRC32 of *filepath* as an uppercase hex string (no 0x prefix)."""
    import zlib as _zlib
    with open(filepath, 'rb') as _f:
        return hex(_zlib.crc32(_f.read()))[2:].upper()


def _pvr_log_read(folder):
    """Parse pvr_log.txt and return a dict keyed by stem (e.g. 'TexID_000') with enc_params/crc32/_raw."""
    log_path = _pvr_log_path(folder)
    result   = {}
    if not os.path.isfile(log_path):
        return result
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as _f:
            raw = _f.read()
        for entry_raw in raw.strip().split('---------------'):
            entry_raw = entry_raw.strip()
            if not entry_raw:
                continue
            d = {}
            for line in entry_raw.splitlines():
                if ':' not in line:
                    continue
                key, _, val = line.partition(':')
                key = key.strip()
                val = val.strip()
                if   key == 'IMAGE FILE': d['image_file'] = val
                elif key == 'ENC PARAMS': d['enc_params']  = val
                elif key == 'DATA CRC32': d['crc32']        = val
            if 'image_file' not in d or 'enc_params' not in d or 'crc32' not in d:
                continue
            stem = os.path.splitext(os.path.basename(d['image_file']))[0]
            result[stem] = {
                'enc_params': d['enc_params'],
                'crc32':      d['crc32'],
                '_raw':       entry_raw,
            }
    except Exception as _e:
        print(f"[NaomiLib] pvr_log read error: {_e}")
    return result


def _pvr_log_enc_params(item):
    """Build the ENC PARAMS string for item (e.g. '-tw -mm -565')."""
    tex = item.tex_mode   # e.g. 'tw', 'vq', ...
    px  = item.px_mode    # e.g. '565', '1555', ...
    parts = [f'-{t}' for t in tex.split()]
    if item.use_mips:
        parts.append('-mm')
    parts.append(f'-{px}')
    return ' '.join(parts)


def _pvr_log_save(folder, entries):
    """Write entries dict to pvr_log.txt; removes stale file when entries is empty."""
    if not entries:
        # Nothing to write — remove a stale log if present
        log_path = _pvr_log_path(folder)
        if os.path.isfile(log_path):
            try:
                os.remove(log_path)
            except Exception as _e:
                print(f"[NaomiLib] pvr_log remove error: {_e}")
        return
    lines = []
    for e in entries.values():
        lines.append(e['_raw'])
        lines.append('---------------')
    try:
        with open(_pvr_log_path(folder), 'w', encoding='utf-8') as _f:
            _f.write('\n'.join(lines) + '\n')
    except Exception as _e:
        print(f"[NaomiLib] pvr_log write error: {_e}")


def _pvr_log_make_entry(img_path, item):
    """Build a single log entry dict for item/img_path; returns None on CRC failure."""
    try:
        crc = _pvr_crc32(img_path)
    except Exception as _e:
        print(f"[NaomiLib] pvr_log: could not CRC {img_path}: {_e}")
        return None
    enc_params = _pvr_log_enc_params(item)
    raw = (
        f"IMAGE FILE : {os.path.normpath(img_path)}\n"
        f"ENC PARAMS : {enc_params}\n"
        f"DATA CRC32 : {crc}"
    )
    return {'enc_params': enc_params, 'crc32': crc, '_raw': raw}


# unified decode: process ALL TexID_NNN.PVR files in a folder

def _decode_all_pvrs_in_folder(folder, skip_existing=True):
    """Decode every TexID_NNN.PVR in folder to a companion image (.bmp or .png for bump).
    Returns (decoded_count, error_list)."""
    if not folder or not os.path.isdir(folder):
        return 0, []

    pvr_list = []
    errors   = []

    for fname in sorted(os.listdir(folder)):
        base, ext = os.path.splitext(fname)
        if ext.upper() != '.PVR':
            continue
        if not (base.startswith('TexID_') and len(base) == 9):
            continue
        pvr_full = os.path.normpath(os.path.join(folder, fname))
        if skip_existing:
            if any(os.path.exists(os.path.join(folder, base + e)) for e in _TEX_IMAGE_EXTS):
                continue
        pvr_list.append(pvr_full)

    decoded = 0
    for pvr_path in pvr_list:
        try:
            pypvr.decode([pvr_path], 'bmp', folder, '-log')
            decoded += 1
        except Exception as e:
            fname = os.path.basename(pvr_path)
            errors.append(f"{fname}: {e}")
            print(f"[NaomiLib] PVR decode failed for {fname}: {e}")

    return decoded, errors


def _update_pvr_log_from_folder(folder):
    """Rebuild pvr_log.txt from current folder state; prunes stale entries. Returns log dict."""
    if not folder or not os.path.isdir(folder):
        return {}

    try:
        log_entries  = _pvr_log_read(folder)
        active_stems = set()

        for fname in sorted(os.listdir(folder)):
            base, ext = os.path.splitext(fname)
            if ext.upper() != '.PVR':
                continue
            if not (base.startswith('TexID_') and len(base) == 9):
                continue
            active_stems.add(base)

            # Find companion image in any Blender-loadable format
            img_path = next(
                (os.path.join(folder, base + e) for e in _TEX_IMAGE_EXTS
                 if os.path.isfile(os.path.join(folder, base + e))),
                None
            )
            if img_path is None:
                continue  # no image yet — decode first

            # Add/update entry only when the CRC has actually changed
            try:
                tid = int(base[6:])
            except ValueError:
                continue

            if base not in log_entries:
                pvr_info = _read_pvr_header(folder, tid)
                if pvr_info:
                    class _FakeItem:
                        pass
                    _fi          = _FakeItem()
                    _fi.tex_mode = pvr_info[0]
                    _fi.px_mode  = pvr_info[1]
                    _fi.use_mips = pvr_info[2]
                    entry = _pvr_log_make_entry(img_path, _fi)
                    if entry is not None:
                        log_entries[base] = entry
                        print(f"[NaomiLib] pvr_log: added '{base}'")
            # (existing entries are kept as-is; _encode_pvr_if_changed updates
            #  them when a re-encode happens)

        # Prune stale entries
        for stale in [s for s in list(log_entries) if s not in active_stems]:
            print(f"[NaomiLib] pvr_log: removing stale entry '{stale}'")
            del log_entries[stale]

        _pvr_log_save(folder, log_entries)
        return log_entries

    except Exception as e:
        print(f"[NaomiLib] pvr_log update error: {e}")
        return {}


# main encode entry point

def _pvr_dims_from_bytes(pvr_bytes):
    """Extract (width, height) from PVR bytes via PVRT tag; returns (0,0) on failure."""
    import struct
    offset = pvr_bytes.find(b"PVRT")
    if offset == -1 or offset + 0x10 > len(pvr_bytes):
        return (0, 0)
    try:
        w = struct.unpack_from('<H', pvr_bytes, offset + 0x0A)[0]
        h = struct.unpack_from('<H', pvr_bytes, offset + 0x0C)[0]
        return (w, h)
    except struct.error:
        return (0, 0)


def _encode_pvr_if_changed(item, abs_folder, log_entries):
    """Encode one slot to .PVR/.PVP if CRC32 or enc_params changed; updates log_entries in-place.
    Returns ('skipped'|'encoded'|'error', message)."""
    if item.is_empty or not item.filepath:
        return 'skipped', "empty slot"

    img_path = bpy.path.abspath(item.filepath)
    if not os.path.isfile(img_path):
        return 'error', f"image not found: {img_path}"

    stem    = f"TexID_{item.tex_id:03d}"
    pvr_out = os.path.join(abs_folder, stem + ".PVR")
    pvp_out = os.path.join(abs_folder, stem + ".PVP")

    # log-based skip check
    current_params = _pvr_log_enc_params(item)

    if os.path.isfile(pvr_out) and stem in log_entries:
        entry = log_entries[stem]
        try:
            current_crc = _pvr_crc32(img_path)
        except Exception as _e:
            print(f"[NaomiLib] pvr_log: CRC failed for {img_path}: {_e}")
            current_crc = None

        if (current_crc is not None
                and current_crc    == entry['crc32']
                and current_params == entry['enc_params']):
            print(f"[NaomiLib] {stem}: skip (CRC32 + enc_params unchanged)")
            return 'skipped', f"{stem}: unchanged (CRC32 + format match)"

        print(f"[NaomiLib] {stem}: encode needed —"
              f" crc_match={current_crc == entry.get('crc32')}"
              f" params_match={current_params == entry.get('enc_params')}")
    else:
        print(f"[NaomiLib] {stem}: encode needed — no log entry or no .PVR yet")

    # encode
    try:
        enc = pypvr.encode()
        pvr_bytes, pvp_bytes = enc.from_file(
            img_path,
            tex_mode     = item.tex_mode,
            px_mode      = item.px_mode,
            with_mipmaps = item.use_mips,
        )
        with open(pvr_out, 'wb') as _f:
            _f.write(pvr_bytes)
        if pvp_bytes is not None:
            with open(pvp_out, 'wb') as _f:
                _f.write(pvp_bytes)

        entry = _pvr_log_make_entry(img_path, item)
        if entry is not None:
            log_entries[stem] = entry

        # Store texture dimensions from the in-memory PVR bytes.
        _w, _h = _pvr_dims_from_bytes(pvr_bytes)
        if _w > 0 and _h > 0:
            item.tex_width  = _w
            item.tex_height = _h

        return 'encoded', f"{stem}: encoded ({item.tex_mode} / {item.px_mode})"
    except Exception as _e:
        return 'error', f"{stem}: encode failed — {_e}"


class NAOMI_OT_tm_encode_all(bpy.types.Operator):
    """Encode ALL slots in the texture folder to .PVR (skipping unchanged images)
and update pvr_log.txt.  Slots whose texfmt/pixfmt or image content have not
changed since the last encode are skipped automatically."""
    bl_idname  = "naomi.tm_encode_all"
    bl_label   = "Encode PVR"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        col, tm = _get_col_tm(obj)
        if tm is None:
            self.report({'ERROR'}, "Object is not in a Naomi collection.")
            return {'CANCELLED'}

        folder = _get_tex_folder(obj)
        if not folder:
            self.report({'ERROR'}, "No texture folder set.")
            return {'CANCELLED'}

        abs_folder = bpy.path.abspath(folder) if folder else folder

        log_entries  = _pvr_log_read(abs_folder)
        active_stems = set()
        encoded = skipped = errors = 0

        for item in tm.tex_list:
            if item.is_empty or not item.filepath:
                continue
            stem = f"TexID_{item.tex_id:03d}"
            active_stems.add(stem)
            status, msg = _encode_pvr_if_changed(item, abs_folder, log_entries)
            print(f"[NaomiLib] Encode PVR: {msg}")
            if status == 'encoded':
                encoded += 1
            elif status == 'skipped':
                skipped += 1
            else:
                errors += 1
            if status in ('encoded', 'skipped'):
                _apply_texctrl_from_slot(obj, item)

        for stale in [s for s in list(log_entries) if s not in active_stems]:
            del log_entries[stale]
        _pvr_log_save(abs_folder, log_entries)

        summary = f"Encode PVR: {encoded} encoded, {skipped} skipped (unchanged)"
        if errors:
            summary += f", {errors} error(s) — see console"
            self.report({'WARNING'}, summary)
        else:
            self.report({'INFO'}, summary)
        return {'FINISHED'}


class NAOMI_OT_tm_apply_selection(bpy.types.Operator):
    """Assign the selected slot's Texture ID to this object and track its settings.
No encoding is performed here — use 'Encode PVR' or enable 'Encode .PVR' on export."""
    bl_idname = "naomi.tm_apply_selection"
    bl_label = "Apply Selected Texture ID"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if not obj or not hasattr(obj, "naomi_param"):
            return {'CANCELLED'}
        col, tm = _get_col_tm(obj)
        if tm is not None and 0 <= tm.tex_list_index < len(tm.tex_list):
            item = tm.tex_list[tm.tex_list_index]
            new_id = item.tex_id

            # Collect all selected objects that belong to the same Naomi collection.
            if col is not None:
                targets = [o for o in context.selected_objects
                           if o.type == 'MESH' and o.name in col.objects]
            else:
                targets = [obj]
            if not targets:
                targets = [obj]

            global _material_rebuild_in_progress
            _material_rebuild_in_progress = True
            try:
                for target in targets:
                    had_texture = target.naomi_param.mh_texID >= 0
                    target.naomi_param.mh_texID = new_id
                    if not had_texture:
                        _apply_texture_params(target, has_texture=True)
                    _apply_texctrl_from_slot(target, item)
            finally:
                _material_rebuild_in_progress = False

            for target in targets:
                update_texture(target.naomi_param, context)
        return {'FINISHED'}


class NAOMI_OT_tm_set_folder(bpy.types.Operator):
    """Choose the texture folder for this object"""
    bl_idname = "naomi.tm_set_folder"
    bl_label = "Change Image Folder"
    bl_options = {'REGISTER', 'UNDO'}
    directory: StringProperty(subtype='DIR_PATH')
    # Set to True by NAOMI_OT_add_texture when it opens this picker because no
    # folder existed yet — causes the first real tex_id to be applied afterwards.
    from_add_texture: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        obj = context.active_object
        if not (obj and hasattr(obj, "naomi_param")):
            return {'CANCELLED'}
        col, tm = _get_col_tm(obj)
        if tm is None:
            self.report({'ERROR'}, "Object is not in a Naomi collection.")
            return {'CANCELLED'}
        folder = bpy.path.abspath(self.directory)
        tm.tex_folder = self.directory

        decoded, errors = _decode_all_pvrs_in_folder(folder, skip_existing=True)
        if decoded:
            self.report({'INFO'}, f"[NaomiLib] Decoded {decoded} PVR(s) in {folder}")
        for err in errors:
            self.report({'WARNING'}, f"[NaomiLib] {err}")
        _update_pvr_log_from_folder(folder)

        _refresh_shared_folder_objects(obj, folder)
        tm.tex_list_index = 0

        # If we were called from "Add Texture" with no prior folder, finish the
        # assignment now that the TM list has been populated.
        if self.from_add_texture:
            first_id = 0
            if tm.tex_list:
                for item in tm.tex_list:
                    if not item.is_empty and item.filepath:
                        first_id = item.tex_id
                        break
            global _material_rebuild_in_progress
            _material_rebuild_in_progress = True
            try:
                obj.naomi_param.mh_texID = first_id
                _apply_texture_params(obj, has_texture=True)
                if tm.tex_list:
                    for item in tm.tex_list:
                        if item.tex_id == first_id and not item.is_empty:
                            _apply_texctrl_from_slot(obj, item)
                            break
            finally:
                _material_rebuild_in_progress = False
            update_texture(obj.naomi_param, context)

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class NAOMI_OT_select_texture_popup(bpy.types.Operator):
    """Popup texture picker — big thumbnails, click to assign"""
    bl_idname  = "naomi.select_texture_popup"
    bl_label   = "Select a Texture"
    bl_options = {'REGISTER', 'INTERNAL'}

    def invoke(self, context, event):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        self.__class__.bl_label = obj.name

        # Build image cache once at invoke so draw() never calls load/preview_ensure.
        folder = _get_tex_folder(obj)
        # _slot_cache: list of (tex_id, bpy.types.Image or None)
        self._slot_cache = []
        if folder:
            for tex_id, filepath in _scan_tex_folder(folder):
                if not filepath or not os.path.exists(filepath):
                    continue
                img = None
                for bpy_img in bpy.data.images:
                    if os.path.normcase(bpy.path.abspath(bpy_img.filepath)) == \
                            os.path.normcase(filepath):
                        img = bpy_img
                        break
                if img is None:
                    try:
                        img = bpy.data.images.load(filepath, check_existing=True)
                    except Exception:
                        img = None
                # Ensure the preview is generated now (async, but only once).
                if img is not None:
                    img.preview_ensure()
                self._slot_cache.append((tex_id, img))

        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        layout = self.layout

        # Manual header (invoke_popup has no title bar)
        row = layout.row()
        row.label(text=self.__class__.bl_label, icon='OBJECT_DATA')
        layout.separator()

        slots = getattr(self, '_slot_cache', None)
        if slots is None:
            layout.label(text="No texture folder set.", icon='ERROR')
            return
        if not slots:
            layout.label(text="No images found in folder.", icon='INFO')
            return

        # 4-column grid
        grid = layout.grid_flow(
            row_major=True, columns=4,
            even_columns=True, even_rows=True, align=True,
        )
        for tex_id, img in slots:
            cell = grid.box()
            if img and img.preview:
                cell.template_icon(icon_value=img.preview.icon_id, scale=5.0)
            else:
                cell.label(text="(loading…)", icon='IMAGE_DATA')

            op = cell.operator("naomi.select_texture_apply",
                               text=f"TexID_{tex_id:03d}", emboss=True)
            op.tex_id = tex_id

    def execute(self, context):
        return {'FINISHED'}


class NAOMI_OT_select_texture_apply(bpy.types.Operator):
    """Assign this texture to the active object"""
    bl_idname  = "naomi.select_texture_apply"
    bl_label   = "Assign Texture"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    tex_id: bpy.props.IntProperty()

    def execute(self, context):
        obj = context.active_object
        if not obj or not hasattr(obj, "naomi_param"):
            return {'CANCELLED'}
        col, tm = _get_col_tm(obj)
        if tm is None:
            self.report({'WARNING'}, "Object is not in a Naomi collection.")
            return {'CANCELLED'}

        item = None
        for i, slot in enumerate(tm.tex_list):
            if slot.tex_id == self.tex_id:
                tm.tex_list_index = i
                item = slot
                break

        if item is None:
            self.report({'WARNING'}, f"TexID_{self.tex_id:03d} not found.")
            return {'CANCELLED'}

        # Apply to all selected objects in the same Naomi collection.
        if col is not None:
            targets = [o for o in context.selected_objects
                       if o.type == 'MESH' and o.name in col.objects]
        else:
            targets = [obj]
        if not targets:
            targets = [obj]

        global _material_rebuild_in_progress
        _material_rebuild_in_progress = True
        try:
            for target in targets:
                had_texture = target.naomi_param.mh_texID >= 0
                target.naomi_param.mh_texID = self.tex_id
                if not had_texture:
                    _apply_texture_params(target, has_texture=True)
                _apply_texctrl_from_slot(target, item)
        finally:
            _material_rebuild_in_progress = False

        for target in targets:
            update_texture(target.naomi_param, context)
        names = ", ".join(t.name for t in targets)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
class NAOMI_OT_tm_view_images(bpy.types.Operator):
    """Popup image viewer — shows all non-empty TexID images in the folder"""
    bl_idname = "naomi.tm_view_images"
    bl_label = "Image Viewer"
    bl_options = {'REGISTER', 'INTERNAL'}

    def invoke(self, context, event):
        obj = context.active_object
        if not obj:
            return {'CANCELLED'}
        col = _get_col_for_obj(obj)
        label = col.name if col else obj.name
        self.__class__.bl_label = f"{label} — Image Viewer"
        return context.window_manager.invoke_popup(self, width=480)

    def draw(self, context):
        layout = self.layout
        obj = context.active_object

        # Draw header title manually (invoke_popup has no built-in header)
        header = layout.row()
        header.label(text=self.__class__.bl_label, icon='IMAGE_DATA')
        layout.separator()

        if not obj:
            return

        folder = _get_tex_folder(obj)
        if not folder:
            layout.label(text="No texture folder set.", icon='ERROR')
            return

        slots = [(tid, fp) for tid, fp in _scan_tex_folder(folder) if fp and os.path.exists(fp)]

        if not slots:
            layout.label(text="No images found in folder.", icon='INFO')
            return

        # 4-column grid
        grid = layout.grid_flow(
            row_major=True, columns=4,
            even_columns=True, even_rows=True, align=True,
        )
        for tex_id, filepath in slots:
            cell = grid.box()
            # Load / find image
            img = None
            for bpy_img in bpy.data.images:
                if os.path.normcase(bpy.path.abspath(bpy_img.filepath)) == os.path.normcase(filepath):
                    img = bpy_img
                    break
            if img is None:
                try:
                    img = bpy.data.images.load(filepath, check_existing=True)
                except Exception:
                    img = None

            if img:
                cell.template_icon(icon_value=img.preview_ensure().icon_id, scale=5.0)
            else:
                cell.label(text="(error)", icon='ERROR')
            cell.label(text=f"TexID_{tex_id:03d}")

    def execute(self, context):
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Export presets — stored as JSON files in <addon>/export_presets/
# ---------------------------------------------------------------------------

_PRESETS_DIR = os.path.join(_ADDON_DIR, "export_presets")
_REBUILD_SCRIPTS_DIR = os.path.join(_ADDON_DIR, "rebuild_scripts")

# Keys that are saved/loaded in presets (all operator bool/enum/float opts)
_PRESET_KEYS = [
    "opt_super_index_override", "opt_srch_level", "opt_allScale",
    "opt_merge0", "opt_merge1",
    "opt_not_triangle", "opt_all_triangle",
    "opt_div_polygons",
    "opt_adjust_uv",
    "opt_rebuild_script",
    "opt_remesh",
    "opt_naomi2",
]


def _preset_path(name):
    return os.path.join(_PRESETS_DIR, name + ".json")


def _list_presets():
    if not os.path.isdir(_PRESETS_DIR):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(_PRESETS_DIR)
        if f.endswith(".json")
    )


def _list_rebuild_scripts():
    if not os.path.isdir(_REBUILD_SCRIPTS_DIR):
        return []
    return sorted(
        f for f in os.listdir(_REBUILD_SCRIPTS_DIR)
        if f.endswith(".py")
    )


def _preset_items_cb(self, context):
    items = [('__NONE__', "— Select preset —", "")]
    for name in _list_presets():
        items.append((name, name, ""))
    return items


def _rebuild_script_items_cb(self, context):
    items = [('__NONE__', "None", "Do not run any post-export script")]
    for fname in _list_rebuild_scripts():
        label = os.path.splitext(fname)[0]
        items.append((fname, label, f"Run {fname} after export"))
    return items


class NAOMI_OT_export_preset_save(bpy.types.Operator):
    """Save current export settings as a named preset"""
    bl_idname = "naomi.export_preset_save"
    bl_label  = "Save Preset"

    preset_name: bpy.props.StringProperty(name="Preset Name", default="my_preset")
    # Serialised settings passed in by the draw() call
    settings_json: bpy.props.StringProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "preset_name")

    def execute(self, context):
        name = self.preset_name.strip()
        if not name:
            self.report({'ERROR'}, "Preset name cannot be empty.")
            return {'CANCELLED'}
        if not self.settings_json:
            self.report({'ERROR'}, "No settings received — use the button inside the exporter dialog.")
            return {'CANCELLED'}
        try:
            data = json.loads(self.settings_json)
        except Exception as e:
            self.report({'ERROR'}, f"Settings parse error: {e}")
            return {'CANCELLED'}
        os.makedirs(_PRESETS_DIR, exist_ok=True)
        with open(_preset_path(name), 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        self.report({'INFO'}, f"Preset '{name}' saved.")
        if _live_export_op is not None:
            try:
                _live_export_op.preset_selector = name
            except Exception:
                pass
        return {'FINISHED'}


class NAOMI_OT_export_preset_delete(bpy.types.Operator):
    """Delete the selected preset"""
    bl_idname = "naomi.export_preset_delete"
    bl_label  = "Delete Preset"

    preset_name: bpy.props.StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        if not self.preset_name or self.preset_name == '__NONE__':
            return {'CANCELLED'}
        path = _preset_path(self.preset_name)
        if os.path.isfile(path):
            os.remove(path)
            self.report({'INFO'}, f"Preset '{self.preset_name}' deleted.")
        else:
            self.report({'WARNING'}, "Preset file not found.")
        if _live_export_op is not None:
            try:
                _live_export_op.preset_selector = '__NONE__'
                _reset_op_to_defaults(_live_export_op)
            except Exception:
                pass
        return {'FINISHED'}


class NAOMI_OT_export_preset_export(bpy.types.Operator):
    """Open the presets folder in the OS file explorer (export from there)"""
    bl_idname  = "naomi.export_preset_export"
    bl_label   = "Open Presets Folder"
    bl_options = {'REGISTER'}

    preset_name: bpy.props.StringProperty(options={'HIDDEN'})

    def execute(self, context):
        os.makedirs(_PRESETS_DIR, exist_ok=True)
        bpy.ops.wm.path_open(filepath=_PRESETS_DIR)
        return {'FINISHED'}


class NAOMI_OT_export_preset_import(bpy.types.Operator):
    """Open the presets folder in the OS file explorer (drop JSON files here)"""
    bl_idname  = "naomi.export_preset_import"
    bl_label   = "Open Presets Folder"
    bl_options = {'REGISTER'}

    def execute(self, context):
        os.makedirs(_PRESETS_DIR, exist_ok=True)
        bpy.ops.wm.path_open(filepath=_PRESETS_DIR)
        return {'FINISHED'}


class NAOMI_OT_open_rebuild_scripts_folder(bpy.types.Operator):
    """Open the rebuild_scripts folder in the OS file explorer"""
    bl_idname  = "naomi.open_rebuild_scripts_folder"
    bl_label   = "Open Rebuild Scripts Folder"
    bl_options = {'REGISTER'}

    def execute(self, context):
        os.makedirs(_REBUILD_SCRIPTS_DIR, exist_ok=True)
        bpy.ops.wm.path_open(filepath=_REBUILD_SCRIPTS_DIR)
        return {'FINISHED'}


classes = [
    Naomi_TextureSlotItem,
    Naomi_Collection_TM,
    Naomi_GlobalParam_0,
    Naomi_GlobalParam_1,
    Naomi_Centroid_Data,
    Naomi_Import_Meta,
    Naomi_Param_Properties,
    Naomi_ISP_TSP_Properties,
    Naomi_TSP_Properties,
    Naomi_TexCtrl_Properties,
    # Object operators
    NAOMI_OT_assign_object_material,
    NAOMI_OT_assign_preset_lambert,
    NAOMI_OT_assign_preset_flat,
    NAOMI_OT_assign_preset_vertex_colors,
    NAOMI_OT_assign_preset_env_map,
    NAOMI_OT_assign_preset_bump,
    NAOMI_OT_assign_preset_palette,
    NAOMI_OT_bump_set_partner,
    NAOMI_OT_bump_generate_normal_map,
    NAOMI_OT_palette_id_set,
    NAOMI_OT_palette_id_clear,
    NAOMI_OT_remove_object_material,
    NAOMI_OT_copy_object_props,
    NAOMI_OT_paste_object_props,
    NAOMI_OT_export_object_props,
    NAOMI_OT_import_object_props,
    # Texture operators
    NAOMI_OT_add_texture,
    NAOMI_OT_remove_texture,
    NAOMI_OT_tm_select,
    NAOMI_OT_tm_drag_scroll,
    NAOMI_OT_tm_scroll,
    NAOMI_OT_tm_scroll_to,
    NAOMI_OT_tm_encode_all,
    NAOMI_OT_tm_refresh,
    NAOMI_OT_tm_add,
    NAOMI_OT_tm_replace,
    NAOMI_OT_tm_delete,
    NAOMI_OT_tm_apply_selection,
    NAOMI_OT_tm_set_folder,
    NAOMI_OT_select_texture_popup,
    NAOMI_OT_select_texture_apply,
    NAOMI_OT_tm_view_images,
    # Collection operators
    NAOMI_OT_assign_collection_material,
    NAOMI_OT_remove_collection_material,
    # Collection update operator
    NAOMI_OT_update_model_file,
    # Export preset operators
    NAOMI_OT_export_preset_save,
    NAOMI_OT_export_preset_delete,
    NAOMI_OT_export_preset_export,
    NAOMI_OT_export_preset_import,
    NAOMI_OT_open_rebuild_scripts_folder,
    # UIList
    NAOMI_UL_texture_list,
    # Panels (must come after all operators they reference)
    COL_PT_collection_gps,
    VIEW3D_PT_Naomi_Texture_Manager,
    OBJECT_PT_Naomi_Properties,
    OBJECT_PT_Naomi_Bump,
    # Texture Manager opener
    NAOMI_OT_open_texture_manager,
]


_PRESET_DEFAULTS = {
    "opt_super_index_override": 'AUTO',
    "opt_srch_level":           '2',
    "opt_allScale":             1.0,
    "opt_merge0":               False,
    "opt_merge1":               False,
    "opt_not_triangle":         False,
    "opt_all_triangle":         False,
    "opt_forward_axis":         '-Y',
    "opt_up_axis":              '+Z',
    "opt_div_polygons":         False,

    "opt_adjust_uv":            False,
    "opt_rebuild_script":       '__NONE__',
    "opt_remesh":               True,
}

_live_export_op = None

def _reset_op_to_defaults(op):
    for k, v in _PRESET_DEFAULTS.items():
        try:
            setattr(op, k, v)
        except Exception:
            pass

def _apply_preset_to_op(self, context):
    """Update callback for preset_selector — auto-loads the chosen preset."""
    global _live_export_op
    _live_export_op = self
    name = self.preset_selector
    if not name or name == '__NONE__':
        _reset_op_to_defaults(self)
        return
    path = _preset_path(name)
    if not os.path.isfile(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for k, v in data.items():
            if k in _PRESET_KEYS and hasattr(self, k):
                try:
                    setattr(self, k, v)
                except Exception:
                    pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Export operator — direct Blender → .bin  (File > Export menu)
# ---------------------------------------------------------------------------

class ExportNaomiHrb(bpy.types.Operator, ExportHelper):
    """Export the active NaomiLib collection directly to .bin format"""
    bl_idname    = "export_scene.naomi_bin"
    bl_label     = "Export"
    filename_ext = ".bin"

    filter_glob: bpy.props.StringProperty(default="*.bin", options={'HIDDEN'})

    # Preset selector (UI only — not saved in preset files)
    preset_selector: bpy.props.EnumProperty(
        name="Preset",
        description="Load a saved preset",
        items=_preset_items_cb,
        update=_apply_preset_to_op,
    )

    # Post-export rebuild script
    opt_rebuild_script: bpy.props.EnumProperty(
        name="Rebuild Script",
        description="Script to run after export (from rebuild_scripts/ folder)",
        items=_rebuild_script_items_cb,
        default=0,
    )

    # nlcv conversion options

    opt_super_index_override: bpy.props.EnumProperty(
        name="Index",
        description="Index format (Auto uses GP0)",
        items=[
            ('AUTO',  "Auto",  "Use collection Global Parameters 0 setting"),
            ('SUPER', "Super", "Force super-index"),
            ('BETA',  "Beta",  "Force beta-index"),
        ],
        default='AUTO',
    )
    opt_srch_level: bpy.props.EnumProperty(
        name="Search",
        description="Strip-search level",
        items=[('0', "0 - Speed",   "Fastest, lowest quality"),
               ('1', "1 - Fast",    ""),
               ('2', "2 - Default", "Balanced (default)"),
               ('3', "3 - Smart",   ""),
               ('4', "4 - Deep",    "Slowest, highest quality")],
        default='2',
    )
    opt_allScale: bpy.props.FloatProperty(
        name="Scale",
        description="Scale",
        default=1.0, min=0.001, max=1000.0, soft_max=1000.0,
    )
    opt_merge0: bpy.props.BoolProperty(
        name="Merge (model)",
        description="Merge identical materials",
        default=False,
    )
    opt_merge1: bpy.props.BoolProperty(
        name="Merge (nearby)",
        description="Merge nearby materials",
        default=False,
    )
    opt_not_triangle: bpy.props.BoolProperty(
        name="No Indep. Tri",
        description="No triangle tables",
        default=False,
    )
    opt_all_triangle: bpy.props.BoolProperty(
        name="All Tri",
        description="Force triangles",
        default=False,
    )
    opt_forward_axis: bpy.props.EnumProperty(
        name="Forward",
        description="Axis pointing into screen (-Z in Naomi space)",
        items=[
            ('+X', "X Forward",  "Blender +X axis is forward"),
            ('-X', "-X Forward", "Blender -X axis is forward"),
            ('+Y', "Y Forward",  "Blender +Y axis is forward (default)"),
            ('-Y', "-Y Forward", "Blender -Y axis is forward"),
            ('+Z', "Z Forward",  "Blender +Z axis is forward"),
            ('-Z', "-Z Forward", "Blender -Z axis is forward"),
        ],
        default='-Y',
    )
    opt_up_axis: bpy.props.EnumProperty(
        name="Up",
        description="Axis pointing up (+Y in Naomi space)",
        items=[
            ('+X', "X Up",  "Blender +X axis is up"),
            ('-X', "-X Up", "Blender -X axis is up"),
            ('+Y', "Y Up",  "Blender +Y axis is up"),
            ('-Y', "-Y Up", "Blender -Y axis is up"),
            ('+Z', "Z Up",  "Blender +Z axis is up (default for Z-up scenes)"),
            ('-Z', "-Z Up", "Blender -Z axis is up"),
        ],
        default='+Z',
    )
    opt_div_polygons: bpy.props.BoolProperty(
        name="Split Polygons",
        description="Triangulate n-gons",
        default=False,
    )
    opt_adjust_uv: bpy.props.BoolProperty(
        name="Adjust UV",
        description="Shrink oversized UV values",
        default=False,
    )
    opt_encode_pvrs: bpy.props.BoolProperty(
        name="Encode .PVRs",
        description="Before exporting, encode all Texture Manager images to .PVR "
                    "using their assigned TexFmt / PixFmt. Skips textures whose "
                    "pixel data is already identical to the existing .PVR on disk",
        default=True,
    )
    opt_remesh: bpy.props.BoolProperty(
        name="Optimize Geometry",
        description="Merge duplicate vertices, triangulate, and fix non-manifold edges "
                    "before exporting. Done entirely in memory — source mesh is never altered",
        default=True,
    )
    opt_export_all: bpy.props.BoolProperty(
        name="Export All",
        description="Export every NaomiLib collection in the scene to the selected folder. "
                    "Each collection is saved as <collection_name>.bin, ignoring the filename "
                    "in the file browser",
        default=False,
    )
    opt_naomi2: bpy.props.BoolProperty(
        name="Naomi2",
        description="Export in NAOMI2 (NL2) format. "
                    "Implies: No Independent Triangles, Output After All, no Super Index, no Div Transparent",
        default=False,
    )
    def draw(self, context):
        global _live_export_op
        _live_export_op = self
        layout = self.layout

        # Presets
        box = layout.box()
        box.label(text="Presets", icon='PRESET')

        # Dropdown — selecting auto-loads the preset
        box.prop(self, "preset_selector", text="")

        # + / − / open folder
        row2 = box.row(align=True)
        save_op = row2.operator("naomi.export_preset_save", text="", icon='ADD')
        save_op.settings_json = json.dumps(
            {k: getattr(self, k) for k in _PRESET_KEYS if hasattr(self, k)}
        )
        del_op = row2.operator("naomi.export_preset_delete", text="", icon='REMOVE')
        del_op.preset_name = (
            self.preset_selector
            if self.preset_selector and self.preset_selector != '__NONE__'
            else ""
        )
        row2.operator("naomi.export_preset_export", text="", icon='FILE_FOLDER')

        # General
        box = layout.box()
        box.label(text="General", icon='SETTINGS')
        box.prop(self, "opt_super_index_override")
        box.prop(self, "opt_srch_level")
        box.prop(self, "opt_rebuild_script", text="Rebuild", icon='SCRIPT')
        row = box.row(align=True)
        row.operator("naomi.open_rebuild_scripts_folder", text="", icon='FILE_FOLDER')
        # Geometry
        box = layout.box()
        box.label(text="Geometry", icon='ORIENTATION_GLOBAL')
        split = box.split(factor=0.4)
        split.label(text="Forward")
        split.prop(self, "opt_forward_axis", text="")
        split = box.split(factor=0.4)
        split.label(text="Up")
        split.prop(self, "opt_up_axis", text="")
        row = box.row()
        box.label(text="Scale:")
        box.prop(self, "opt_allScale", slider=True, text="")
        box.prop(self, "opt_remesh")

        # Polygons 
        box = layout.box()
        box.label(text="Polygons", icon='MESH_DATA')
        row = box.row()
        row.prop(self, "opt_not_triangle")
        row.prop(self, "opt_all_triangle")
        row = box.row()
        row.prop(self, "opt_div_polygons")

        # Material 
        box = layout.box()
        box.label(text="Material", icon='MATERIAL')
        row = box.row()
        row.prop(self, "opt_merge0")
        row.prop(self, "opt_merge1")
        row = box.row()
        row.prop(self, "opt_adjust_uv")

        # Output 
        box = layout.box()
        box.label(text="Output", icon='FILE_NEW')
        row = box.row()
        row = box.row()
        row.prop(self, "opt_encode_pvrs")
        row.prop(self, "opt_export_all")
        box.prop(self, "opt_naomi2")

    def _resolve_collection(self, context):
        """Resolve target collection from active layer collection or active object."""
        alc = context.view_layer.active_layer_collection
        col = alc.collection if alc else None

        if col is None or col == context.scene.collection:
            active_obj = context.active_object
            if active_obj and active_obj.users_collection:
                for c in active_obj.users_collection:
                    if c != context.scene.collection:
                        return c
            return None

        return col

    def _build_opts(self, col, col_super_index: bool, base_name: str,
                    col_env_map: bool = False) -> object:
        """Populate an NlcvOptions instance from operator properties."""
        opts = _NlcvOptions.defaults()

        if self.opt_super_index_override == 'AUTO':
            super_index = col_super_index
        elif self.opt_super_index_override == 'SUPER':
            super_index = True
        else:
            super_index = False
        opts.super_index_format   = super_index
        opts.input_file_name_base = base_name

        opts.srch_level         = int(self.opt_srch_level)
        opts.all_scale          = self.opt_allScale
        opts.no_trs             = False
        opts.no_alp             = False
        opts.all_flat           = False
        opts.merge0             = bool(self.opt_merge0)
        opts.merge1             = bool(self.opt_merge1)
        opts.not_triangle       = bool(self.opt_not_triangle)
        opts.all_triangle       = bool(self.opt_all_triangle)
        opts.forward_axis = self.opt_forward_axis
        opts.up_axis      = self.opt_up_axis
        opts.neg_x        = False
        opts.div_convex         = bool(self.opt_div_polygons)
        opts.div_concave        = bool(self.opt_div_polygons)
        opts.sort_sidx_cache    = True
        opts.adjust_uv          = bool(self.opt_adjust_uv)

        opts.flat_not_normal_calc = False

        opts.sph_envmap = bool(col_env_map)

        opts.remesh = bool(self.opt_remesh)

        opts.naomi2hg = bool(self.opt_naomi2)
        if opts.naomi2hg:
            opts.not_triangle       = True
            opts.output_after_all   = True
            opts.div_trnsl          = False
            opts.super_index_format = False

        _tm = getattr(col, 'naomi_tm', None)
        if _tm and _tm.tex_folder:
            _folder = bpy.path.abspath(_tm.tex_folder)
            if os.path.isdir(_folder):
                _ps = _folder + os.sep
                opts.palpath       = [_ps]
                opts.palpath_count = 1
                opts.texpath       = [_ps]
                opts.texpath_count = 1
                opts.texoutpath    = _folder + os.sep

        return opts

    def _export_one_collection(self, context, col, out_path):
        """Export a single collection to *out_path*.
        Returns True on success, False on failure (errors reported via self.report)."""
        import traceback

        mesh_objects = [o for o in col.objects if o.type == 'MESH']
        if not mesh_objects:
            self.report({'WARNING'},
                f"Collection '{col.name}' has no mesh objects — skipped.")
            return False

        # Validate that every mesh has a Naomi preset assigned.
        unassigned = [
            o.name for o in mesh_objects
            if not getattr(getattr(o, 'naomi_param', None), 'naomi_assigned', False)
        ]
        if unassigned:
            names = ", ".join(unassigned)
            self.report({'ERROR'},
                f"Assign a Naomi preset to: {names}")
            return False

        super_index = (col.gp0.objFormat == '1')

        if self.opt_encode_pvrs:
            tm = col.naomi_tm
            folder = bpy.path.abspath(tm.tex_folder) if tm.tex_folder else None
            if not folder or not os.path.isdir(folder):
                self.report({'WARNING'},
                    f"Encode .PVRs: no valid texture folder on '{col.name}' — skipped.")
            else:
                enc_count = skp_count = err_count = 0
                log_entries  = _pvr_log_read(folder)
                active_stems = set()
                for item in tm.tex_list:
                    if item.is_empty or not item.filepath:
                        continue
                    stem = f"TexID_{item.tex_id:03d}"
                    active_stems.add(stem)
                    status, msg = _encode_pvr_if_changed(item, folder, log_entries)
                    print(f"[NaomiLib] Export encode: {msg}")
                    if status == 'encoded':
                        enc_count += 1
                    elif status == 'skipped':
                        skp_count += 1
                    else:
                        err_count += 1
                for stale in [s for s in list(log_entries) if s not in active_stems]:
                    del log_entries[stale]
                _pvr_log_save(folder, log_entries)
                summary = f"Encode .PVRs ({col.name}): {enc_count} encoded, {skp_count} skipped"
                if err_count:
                    summary += f", {err_count} error(s) — see console"
                    self.report({'WARNING'}, summary)
                else:
                    self.report({'INFO'}, summary)

        _NLdirect = NLe
        base_name = os.path.splitext(os.path.basename(out_path))[0]
        _TOUCH_COUNT_START = 3
        _TOUCH_COUNT_MAX   = 32
        try:
            col_env_map = any(
                o.type == 'MESH' and
                getattr(o, 'naomi_param', None) is not None and
                o.naomi_param.naomi_assigned and
                o.naomi_param.naomi_flag_env_map
                for o in col.objects
            )
            col.gp1.envMap = col_env_map
            opts = self._build_opts(col, super_index, base_name,
                                    col_env_map=col_env_map)

            touch_limit = _TOUCH_COUNT_START
            bin_bytes   = None

            while touch_limit <= _TOUCH_COUNT_MAX:
                opts.touch_count_max = touch_limit
                try:
                    bin_bytes = _NLdirect.convert_collection(col, opts)
                    if touch_limit > _TOUCH_COUNT_START:
                        self.report(
                            {'WARNING'},
                            f"'{col.name}': touch_count overflow — retried with "
                            f"touch_count_max={touch_limit}.")
                    break
                except _NlcvError as exc:
                    if exc.code == _NLCV_ERR_CONVERT:
                        next_limit = 5 if touch_limit == 3 else touch_limit + 1
                        touch_limit = next_limit
                        continue
                    self.report({'ERROR'}, f"Export error ({col.name}): {exc}")
                    return False

            if bin_bytes is None:
                self.report({'ERROR'},
                    f"'{col.name}': touch_count overflow persists at max={_TOUCH_COUNT_MAX}.")
                return False

        except Exception as e:
            self.report({'ERROR'}, f"Unexpected error ({col.name}): {e}")
            traceback.print_exc()
            return False

        try:
            with open(out_path, 'wb') as f:
                f.write(bin_bytes)
        except Exception as e:
            self.report({'ERROR'}, f"Could not write '{out_path}': {e}")
            return False

        idx_mode = "Super Index" if super_index else "Beta Index"
        self.report({'INFO'},
            f"Exported {len(bin_bytes)} bytes → {out_path} "
            f"[{idx_mode}] ({len(mesh_objects)} mesh(es))")
        return True

    def execute(self, context):
        if self.opt_export_all:
            out_dir = os.path.dirname(self.filepath)
            if not os.path.isdir(out_dir):
                self.report({'ERROR'}, f"Output folder does not exist: {out_dir}")
                return {'CANCELLED'}

            # Find all NaomiLib collections in the scene
            naomi_cols = [
                c for c in bpy.data.collections
                if (hasattr(c, 'naomi_centroidData')
                    and c.naomi_centroidData.naomi_assigned
                    and any(o.type == 'MESH' for o in c.objects))
            ]
            if not naomi_cols:
                self.report({'ERROR'},
                    "No NaomiLib collections found in the scene.")
                return {'CANCELLED'}

            ok_count = 0
            fail_count = 0
            for col in naomi_cols:
                col_name = col.name
                if col_name.lower().endswith(".bin"):
                    col_path = os.path.join(out_dir, col_name)
                else:
                    col_path = os.path.join(out_dir, col_name + ".bin")
                if self._export_one_collection(context, col, col_path):
                    ok_count += 1
                else:
                    fail_count += 1

            # Run rebuild script once at the end (if selected)
            self._run_rebuild_script(context)

            summary = f"Export All: {ok_count} exported"
            if fail_count:
                summary += f", {fail_count} failed"
                self.report({'WARNING'}, summary)
            else:
                self.report({'INFO'}, summary)
            return {'FINISHED'}

        col = self._resolve_collection(context)
        if col is None:
            self.report({'ERROR'},
                "Please select a NaomiLib collection in the Outliner.")
            return {'CANCELLED'}

        if not self._export_one_collection(context, col, self.filepath):
            return {'CANCELLED'}

        self._run_rebuild_script(context)
        return {'FINISHED'}

    def _run_rebuild_script(self, context):
        """Run post-export rebuild script (if selected)."""
        script_file = getattr(self, "opt_rebuild_script", '__NONE__')
        if script_file and script_file != '__NONE__':
            script_path = os.path.join(_REBUILD_SCRIPTS_DIR, script_file)
            if os.path.isfile(script_path):
                try:
                    script_globals = {
                        "__file__":    script_path,
                        "export_path": self.filepath,
                        "context":     context,
                    }
                    with open(script_path, 'r', encoding='utf-8') as _sf:
                        exec(compile(_sf.read(), script_path, 'exec'), script_globals)
                    self.report({'INFO'}, f"Rebuild script '{script_file}' executed.")
                except Exception as _se:
                    self.report({'WARNING'},
                        f"Rebuild script '{script_file}' raised an error: {_se}")
                    import traceback as _tb
                    _tb.print_exc()
            else:
                self.report({'WARNING'},
                    f"Rebuild script not found: {script_path}")

        return {'FINISHED'}


def menu_func_import(self, context):
    self.layout.operator(ImportNL.bl_idname, text="NaomiLib (.bin)")

def menu_func_export(self, context):
    self.layout.operator(ExportNaomiHrb.bl_idname, text="Export NaomiLib (.bin)")


def _refresh_tex_list(obj):
    """Rebuild tex_list for obj from its texture folder, skipping if already up-to-date."""
    if not hasattr(obj, "naomi_param"):
        return
    p = obj.naomi_param
    if not p.naomi_assigned:
        return
    # Auto-infer folder if not stored
    if not p.tex_folder:
        inferred = _get_tex_folder(obj)
        if inferred:
            p.tex_folder = inferred
    folder = _get_tex_folder(obj)
    if not folder:
        return

    disk_slots = _scan_tex_folder(folder)

    col = _get_col_for_obj(obj)
    canonical_list = col.naomi_tm.tex_list if col is not None else p.tex_list

    if len(disk_slots) == len(canonical_list):
        match = True
        for (d_id, d_fp), item in zip(disk_slots, canonical_list):
            d_fp_norm = os.path.normcase(d_fp) if d_fp else ""
            i_fp_norm = os.path.normcase(item.filepath) if item.filepath else ""
            if item.tex_id != d_id or i_fp_norm != d_fp_norm:
                match = False
                break
        if match:
            return

    if col is not None:
        _rebuild_tex_list(col.naomi_tm, folder, col=col)
        p = col.naomi_tm  # use the canonical tm, not the per-object p
        if p.tex_list_index >= len(p.tex_list):
            p.tex_list_index = max(0, len(p.tex_list) - 1)
        return
    if p.tex_list_index >= len(p.tex_list):
        p.tex_list_index = max(0, len(p.tex_list) - 1)


@bpy.app.handlers.persistent
def _on_depsgraph_update(scene, depsgraph):
    """Refresh texture list and sync TM selection when the active object changes."""
    if _material_rebuild_in_progress:
        return
    ctx = bpy.context
    obj = getattr(ctx, "active_object", None)
    if obj is None:
        return
    if obj.name == _on_depsgraph_update._last_obj:
        return
    _on_depsgraph_update._last_obj = obj.name
    _refresh_tex_list(obj)

    # Auto-highlight the TM row matching the object's assigned texture ID.
    col = _get_col_for_obj(obj)
    if col is not None:
        tm = col.naomi_tm
        p  = getattr(obj, "naomi_param", None)
        if p is not None and len(tm.tex_list) > 0:
            assigned_id = int(getattr(p, "mh_texID", -1))
            if assigned_id >= 0:
                for idx, _item in enumerate(tm.tex_list):
                    if _item.tex_id == assigned_id:
                        tm.tex_list_index = idx
                        break

    # Rebuild collection tex_list if folder is set but list is still empty (post-import).
    col = _get_col_for_obj(obj)
    if col is not None:
        tm = col.naomi_tm
        if tm.tex_folder and len(tm.tex_list) == 0:
            folder = bpy.path.abspath(tm.tex_folder)
            if folder and os.path.isdir(folder):
                _rebuild_tex_list(tm, folder, col=col)
                if tm.tex_list_index >= len(tm.tex_list):
                    tm.tex_list_index = max(0, len(tm.tex_list) - 1)

_on_depsgraph_update._last_obj = ""
# True while update_texture/_full_rebuild execute; suppresses depsgraph re-entry.
_material_rebuild_in_progress = False
# Set by _draw_texture_manager, read by NAOMI_UL_texture_list.draw_item.
_naomi_tm_has_scroll = False

# PreviewCollection owned by this addon; keys are normcase(abspath).
_TM_PREVIEWS = None  # initialised in register()


def _tm_previews_load(abs_fp):
    """Load abs_fp into _TM_PREVIEWS if not already present. Returns icon_id."""
    key = os.path.normcase(abs_fp)
    if key in _TM_PREVIEWS:
        return _TM_PREVIEWS[key].icon_id
    if os.path.exists(abs_fp):
        try:
            thumb = _TM_PREVIEWS.load(key, abs_fp, 'IMAGE')
            return thumb.icon_id
        except Exception:
            pass
    return 0


def _tm_previews_clear():
    """Remove all entries — called only by _rebuild_tex_list."""
    _TM_PREVIEWS.clear()


def register():
    global _TM_PREVIEWS
    _TM_PREVIEWS = _previews_mod.new()
    bpy.utils.register_class(ImportNL)
    bpy.utils.register_class(ExportNaomiHrb)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Object.naomi_param     = bpy.props.PointerProperty(type=Naomi_Param_Properties)
    bpy.types.Object.naomi_isp_tsp   = bpy.props.PointerProperty(type=Naomi_ISP_TSP_Properties)
    bpy.types.Object.naomi_tsp       = bpy.props.PointerProperty(type=Naomi_TSP_Properties)
    bpy.types.Object.naomi_texCtrl   = bpy.props.PointerProperty(type=Naomi_TexCtrl_Properties)
    bpy.types.Collection.gp0                = bpy.props.PointerProperty(type=Naomi_GlobalParam_0)
    bpy.types.Collection.gp1                = bpy.props.PointerProperty(type=Naomi_GlobalParam_1)
    bpy.types.Collection.naomi_centroidData = bpy.props.PointerProperty(type=Naomi_Centroid_Data)
    bpy.types.Collection.naomi_import_meta  = bpy.props.PointerProperty(type=Naomi_Import_Meta)
    bpy.types.Collection.naomi_tm           = bpy.props.PointerProperty(type=Naomi_Collection_TM)

    bpy.app.handlers.depsgraph_update_post.append(_on_depsgraph_update)


def unregister():
    global _TM_PREVIEWS
    if _TM_PREVIEWS is not None:
        _previews_mod.remove(_TM_PREVIEWS)
        _TM_PREVIEWS = None
    if _on_depsgraph_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_on_depsgraph_update)

    bpy.utils.unregister_class(ImportNL)
    bpy.utils.unregister_class(ExportNaomiHrb)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)

    for cls in classes:
        bpy.utils.unregister_class(cls)

    for attr in ("naomi_param", "naomi_isp_tsp", "naomi_tsp", "naomi_texCtrl"):
        delattr(bpy.types.Object, attr)
    for attr in ("gp0", "gp1", "naomi_centroidData", "naomi_import_meta", "naomi_tm"):
        delattr(bpy.types.Collection, attr)


if __name__ == "__main__":
    register()
