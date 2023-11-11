bl_info = {
    "name" : "NaomiLib Importer for Blender",
    "author" : "zocker_160, VincentNL, TVIndustries",
    "description" : "Addon for importing NaomiLib .bin/.raw files",
    "blender" : (3, 4, 1),
    "version" : (0, 14, 4),
    "location" : "File > Import",
    "warning" : "",
    "category" : "Import",
    "tracker_url": "https://github.com/NaomiMod/blender-NaomiLib"
}

import bpy
import importlib
import os
from . import NLimporter as NLi
from bpy.props import FloatVectorProperty
from bpy.props import StringProperty, BoolProperty, FloatProperty
from bpy_extras.io_utils import ImportHelper, path_reference_mode
import tempfile
import subprocess


importlib.reload(NLi)


def import_nl(self, context, filepath: str, bCleanup: bool, bArchive: bool, fScaling: float, bDebug: bool, bOrientation, bNegScale_X: bool):

    ret = False

    if bArchive:
        ret = NLi.main_function_import_archive(self, filepath=filepath, scaling=fScaling, debug=bDebug)
    else:
        ret = NLi.main_function_import_file(self, filepath=filepath, scaling=fScaling, debug=bDebug, orientation=bOrientation, NegScale_X=bNegScale_X)

    return ret

class ImportNL(bpy.types.Operator, ImportHelper):
    """Import a NaomiLib file"""

    bl_idname = "import_scene.naomilib"
    bl_label = "Import NaomiLib"

    filename_ext = ".bin",".raw" #.bin or raw supported by SMB

    load_directory: bpy.props.BoolProperty(
        name="Load Directory",
        description="Import all files in the same directory as the selected file",
        default=False,
    )

    filter_glob: StringProperty(
        default="*.bin;*.raw",
        options={'HIDDEN'},
        maxlen=255,  # Max internal buffer length, longer would be clamped.
    )

    setting_cleanup: BoolProperty(
        name="clean whole scene (!)",
        description="removes all objects and collections before import",
        default=False,
    )

    setting_archive: BoolProperty(
        name="File is LZ_P archive",
        description="3D model archive used by Super Monkey Ball (GameCube)",
        default=False,
    )

    setting_scaling: FloatProperty(
        name="Scale",
        description="scaling factor for all objects to make huge objects smaller",
        default=1,
        min=0,
        max=1,
    )

    setting_debug: BoolProperty(
        name="enable debugging",
        description="enables debugging mode and prints useful information into log",
        default=False,
    )

    orientation: bpy.props.EnumProperty(
        name="Orientation",
        items=[('X_UP', "X-Up", "X-Up Orientation"),
               ('Y_UP', "Y-Up", "Y-Up Orientation"),
               ('Z_UP', "Z-Up", "Z-Up Orientation")],
        default='Z_UP'
    )

    negative_x_scale_enabled: BoolProperty(
        name="Enable Negative X Scale",
        description="Applies a -1 scale transformation on x axis",
        default=True
    )

    def execute(self, context):
        if self.load_directory:
            if self.setting_cleanup:
                NLi.cleanup()
            folder_path = os.path.dirname(self.filepath)
            for filename in os.listdir(folder_path):
                if filename.endswith(".bin") or filename.endswith(".raw"):
                    file_path = os.path.join(folder_path, filename)
                    import_nl(self, context, filepath=file_path, bCleanup=self.setting_cleanup,
                              bArchive=self.setting_archive, fScaling=self.setting_scaling, bDebug=self.setting_debug,
                              bOrientation=self.orientation, bNegScale_X=self.negative_x_scale_enabled)

        else:
            if self.setting_cleanup:
                NLi.cleanup()
            import_nl(self, context, filepath=self.filepath, bCleanup=self.setting_cleanup,
                      bArchive=self.setting_archive, fScaling=self.setting_scaling, bDebug=self.setting_debug,
                      bOrientation=self.orientation, bNegScale_X=self.negative_x_scale_enabled)

        return {'FINISHED'}

class Naomi_GlobalParam_0(bpy.types.PropertyGroup):
    objFormat : bpy.props.EnumProperty(
        description= "Describes Object Mode",
        name = "Index Mode",
        items = [('0', "Beta Index",""),
                 ('1', "Super Index",""),
        ],
    )
class Naomi_GlobalParam_1(bpy.types.PropertyGroup):
    skp1stSrcOp : bpy.props.BoolProperty(
        description= "Skip 1st legitimate source option",
        name = "Skip 1st Lgt Src Op",
    )
    envMap : bpy.props.BoolProperty(
        description= "Apply Environment Mapping",
        name = "Environment Mapping",
    )
    pltTex : bpy.props.BoolProperty(
        description= "Palette is used on texture",
        name = "Paletted Texture",
    )
    bumpMap : bpy.props.BoolProperty(
        description= "BumpMap is used/available",
        name = "Bump Map Available",
    )
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

        layout.label(text= "Global Parameters 0")
        gp_0 = active.gp0
        box = layout.box()
        box.prop(gp_0, "objFormat")

        layout.label(text= "Global Parameters 1")
        gp_1 = active.gp1
        box = layout.box()
        row = box.row()
        row.prop(gp_1, "skp1stSrcOp")
        row.prop(gp_1, "envMap")
        row = box.row()
        row.prop(gp_1, "pltTex")
        row.prop(gp_1, "bumpMap")

def update_mesh_color(self, context):
    active_object = bpy.context.active_object
    if active_object:
        # Check if the object has a material
        if active_object.material_slots:
            material = active_object.material_slots[0].material
            if material.use_nodes and material.node_tree:
                # Find the Principled BSDF shader node
                principled_node = None
                for node in material.node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        principled_node = node
                        break

                if principled_node:
                    # Update the base color of the Principled BSDF shader
                    base_color = self.meshColor
                    principled_node.inputs['Base Color'].default_value = (
                    *base_color[:3], base_color[3])  # Convert to tuple (R, G, B, A)

def update_mesh_offsetcolor(self, context):
    active_object = bpy.context.active_object
    if active_object:
        # Check if the object has a material
        if active_object.material_slots:
            material = active_object.material_slots[0].material
            if material.use_nodes and material.node_tree:
                # Find the Principled BSDF shader node
                principled_node = None
                for node in material.node_tree.nodes:
                    if node.type == 'BSDF_PRINCIPLED':
                        principled_node = node
                        break

                if principled_node:
                    # Update the base color of the Principled BSDF shader
                    base_color = self.meshOffsetColor
                    principled_node.inputs['Subsurface Color'].default_value = (
                    *base_color[:3], base_color[3])  # Convert to tuple (R, G, B, A)


def update_texture(self, context):
    active_obj = bpy.context.active_object

    if active_obj and active_obj.type == 'MESH':
        texture_filepaths = set()  # Use a set for faster membership checking

        mh_texID = self.mh_texID
        textureFileFormats = ('png', 'tga')

        for material_slot in active_obj.material_slots:
            material = material_slot.material
            for node in material.node_tree.nodes:
                if node.type == 'TEX_IMAGE':
                    tex_node = node
                    image = tex_node.image
                    if image:
                        texFileName = 'TexID_{0:03d}'.format(mh_texID)
                        texDir, filename = os.path.split(image.filepath)
                        texPath = os.path.join(texDir, texFileName)

                        for format in textureFileFormats:
                            potential_tex_path = texPath + '.' + format
                            if os.path.exists(potential_tex_path):
                                texPath = potential_tex_path
                                break

                        for img in bpy.data.images:
                            if img.filepath == texPath:
                                tex_node.image = img
                                break
                        else:
                            if os.path.exists(texPath):
                                loaded_image = bpy.data.images.load(texPath)
                                tex_node.image = loaded_image
                                texture_filepaths.add(texPath)

                # Prevent edit box to assign Negative values
                if self.mh_texID < 0:
                    self.mh_texID = 0  # Set the value to 0 if it's negative
                    bpy.context.area.tag_redraw()
    else:
        if debug:print("No active mesh object with materials found.")



class Naomi_Param_Properties(bpy.types.PropertyGroup):
    paramType : bpy.props.EnumProperty(
        description= "Type of Parameters",
        name= "Parameter Type",
        items = [('0', "CtrlParam End of List",""),
                 ('1', "CtrlParam User Tile Clip",""),
                 ('2', "CtrlParam Object List Set",""),
#                 ('3', "Reserved",""),
                 ('4', "GlobalParam Poly/ModifierVol",""),
                 ('5', "GlobalParam Sprite",""),
#                 ('6', "GlobalParam Reserved",""),
                 ('7', "VertexParam",""),
        ],
    )
    endOfStrip : bpy.props.EnumProperty(
        description= "End of Strip Flag",
        name = "End of Strip",
        items = [('0', "No",""),
                 ('1', "Yes",""),
        ],
    )
    listType : bpy.props.EnumProperty(
        description= "List Type",
        name= "List Type",
        items = [('0', "Opaque",""),
                 ('1', "Opaque ModifierVol",""),
                 ('2', "Translucent",""),
                 ('3', "Translucent ModifierVol",""),
                 ('4', "Punch Through",""),
#                 ('5', "Reserved",""),
#                 ('6', "Reserved",""),
#                 ('7', "Reserved",""),
        ],
    )
    grpEn : bpy.props.EnumProperty(
        description= "Group En",
        name = "Group En",
        items = [('0', "No",""),
                 ('1', "Update Strip_Len + User_Clip settings",""),
        ],
    )
    stripLen : bpy.props.EnumProperty(
        description= "Strip Length",
        name = "Strip Length",
        items = [('0', "1 Strip",""),
                 ('1', "2 Strips",""),
                 ('2', "4 Strips",""),
                 ('3', "6 Strips",""),
        ],
    )
    usrClip : bpy.props.EnumProperty(
        description= "User Clip",
        name = "User Clip",
        items = [('0', "Disable",""),
#                 ('1', "Reserved",""),
                 ('2', "Inside Enable",""),
                 ('3', "Outside Enable",""),
        ],
    )
    shadow : bpy.props.EnumProperty(
        description= "Shadow",
        name = "Shadow",
        items = [('0', "Disabled",""),
                 ('1', "Enabled",""),
        ],
    )
    volume : bpy.props.EnumProperty(
        description= "Volume",
        name = "Volume",
        items = [('0', "Disabled",""),
                 ('1', "Enabled",""),
        ],
    )
    colType : bpy.props.EnumProperty(
        description= "Color Type Usage",
        name = "Color Type",
        items = [('0', "Packed Color",""),
                 ('1', "Floating Color",""),
                 ('2', "Intensity Mode 1",""),
                 ('3', "Intensity Mode 2",""),
        ],
    )
    textureUsage : bpy.props.EnumProperty(
        description= "Texture Usage",
        name = "Use Texture",
        items = [('0', "Disabled",""),
                 ('1', "Enabled",""),
        ],
    )
    offsColorUsage : bpy.props.EnumProperty(
        description= "OffsetColor Usage",
        name = "Use OffsetColor",
        items = [('0', "Disabled",""),
                 ('1', "Enabled",""),
                ],
    )
    gouraudShdUsage : bpy.props.EnumProperty(
        description= "Gouraud Shading Usage",
        name = "Gouraud Shading",
        items = [('0', "Disabled",""),
                 ('1', "Enabled",""),
                ],
    )
    uvDataSize : bpy.props.EnumProperty(
        description= "Data Size of UV Floats",
        name = "UV Float Size",
        items = [('0', "32-bit UV",""),
                 ('1', "16-bit UV",""),
                ],
    )

    meshColor: FloatVectorProperty(
        name="Mesh Base Color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 1.0, 1.0, 1.0),
        update=update_mesh_color,
    )

    meshOffsetColor: FloatVectorProperty(
        name="Mesh Offset Color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(0.0, 0.0, 0.0, 1.0),
        update=update_mesh_offsetcolor,

    )

    # Add Centroid parameters
    centroid_x: bpy.props.FloatProperty(
        name="Centroid X",
        default=0.0,
    )

    centroid_y: bpy.props.FloatProperty(
        name="Centroid Y",
        default=0.0,
    )

    centroid_z: bpy.props.FloatProperty(
        name="Centroid Z",
        default=0.0,
    )

    bound_radius: bpy.props.FloatProperty(
        name="Bound Radius",
        default=1.0,
        min=0.0,
    )

    mh_texID: bpy.props.IntProperty(
        description="Texture ID",
        name="Texture ID",
        default=-1,  # Set the default value to -1
        min=-1,  # Update the minimum value to -1
        max = 1000,
        update=update_texture,
    )

    stripLen : bpy.props.EnumProperty(
        description= "Strip Length",
        name = "Strip Length",
        items = [('0', "1 Strip",""),
                 ('1', "2 Strips",""),
                 ('2', "4 Strips",""),
                 ('3', "6 Strips",""),
        ],
    )

    m_shad_type: bpy.props.EnumProperty(
        name="Shading",
        description="Type of shading",
        items=[('0', "Lambert", ""),
               ('-1', "Constant (Flat)", ""),
               ('-2', "Bump", ""),
               ('-3', "Vertex Colors", ""),
               ],
    )

    m_tex_shading: bpy.props.IntProperty(
        name="Shading Type",
        description="Type of shading",
        default=0,

    )


    spec_int: bpy.props.IntProperty(
        description="Specular Intensity",
        name="Specular Intensity",
        default=0,
        min=0,
        max = 100,

    )

    texture_ambient_light: bpy.props.FloatProperty(
        description="Texture Ambient Light",
        name="Texture Ambient Light",
        default=0.0,
        min=0.0,
        max=1.0,
    )


class Naomi_ISP_TSP_Properties(bpy.types.PropertyGroup):
    depthCompare : bpy.props.EnumProperty(
        description= "Depth Comparison Mode",
        name = "Depth Compare",
        items = [('0', "Never",""),
                 ('1', "Less",""),
                 ('2', "Equal",""),
                 ('3', "Less or Equal",""),
                 ('4', "Greater",""),
                 ('5', "Not Equal",""),
                 ('6', "Greater or Equal",""),
                 ('7', "Always",""),
                ],
    )
    culling : bpy.props.EnumProperty(
        description= "Culling Mode",
        name = "Culling Mode",
        items = [('0', "No Culling",""),
                 ('1', "Cull if Small",""),
                 ('2', "Cull if Negative",""),
                 ('3', "Cull if Positive",""),
        ],
    )
    zWrite : bpy.props.EnumProperty(
        description= "Z-Write",
        name = "Z-Write",
        items = [('0', "Enabled",""),
                 ('1', "Disabled",""),
                ],
    )
    textureUsage : bpy.props.EnumProperty(
        description= "Texture Usage",
        name = "Use Texture",
        items = [('0', "Disabled",""),
                 ('1', "Enabled",""),
        ],
    )
    offsColorUsage : bpy.props.EnumProperty(
        description= "OffsetColor Usage",
        name = "Use OffsetColor",
        items = [('0', "Disabled",""),
                 ('1', "Enabled",""),
                ],
    )
    gouraudShdUsage : bpy.props.EnumProperty(
        description= "Gouraud Shading Usage",
        name = "Gouraud Shading",
        items = [('0', "Disabled",""),
                 ('1', "Enabled",""),
                ],
    )
    uvDataSize : bpy.props.EnumProperty(
        description= "Data Size of UV Floats",
        name = "UV Float Size",
        items = [('0', "32-bit UV",""),
                 ('1', "16-bit UV",""),
                ],
    )
    cacheBypass : bpy.props.EnumProperty(
        description= "Cache Bypass Usage",
        name = "Cache Bypass",
        items = [('0', "Disabled",""),
                 ('1', "Enabled",""),
                ],
    )
    dCalcCtrl : bpy.props.EnumProperty(
        description= "D Calculation Control",
        name = "D-Calc Ctrl",
        items = [('0', "Disabled",""),
                 ('1', "Use on Small Polys",""),
                ],
    )
class Naomi_TSP_Properties(bpy.types.PropertyGroup):
    srcAlpha : bpy.props.EnumProperty(
        description= "Sets Alpha Source",
        name= "Alpha Source",
        items = [('0', "Zero (0, 0, 0, 0)",""),
                 ('1', "One (1, 1, 1, 1)",""),
                 ('2', "\'Other\' Color (OR, OG, OB, OA)",""),
                 ('3', "Inverse \'Other\' Color (1-OR, 1-OG, 1-OB, 1-OA)",""),
                 ('4', "SRC Alpha (SA, SA, SA, SA)",""),
                 ('5', "Inverse SRC Alpha (1-SA, 1-SA, 1-SA, 1-SA)",""),
                 ('6', "DST Alpha (DA, DA, DA, DA)",""),
                 ('7', "Inverse DST Alpha (1-DA, 1-DA, 1-DA, 1-DA)",""),
        ],
    )
    dstAlpha : bpy.props.EnumProperty(
        description= "Sets Alpha Destination",
        name= "Alpha Destination",
        items = [('0', "Zero (0, 0, 0, 0)",""),
                 ('1', "One (1, 1, 1, 1)",""),
                 ('2', "\'Other\' Color (OR, OG, OB, OA)",""),
                 ('3', "Inverse \'Other\' Color (1-OR, 1-OG, 1-OB, 1-OA)",""),
                 ('4', "SRC Alpha (SA, SA, SA, SA)",""),
                 ('5', "Inverse SRC Alpha (1-SA, 1-SA, 1-SA, 1-SA)",""),
                 ('6', "DST Alpha (DA, DA, DA, DA)",""),
                 ('7', "Inverse DST Alpha (1-DA, 1-DA, 1-DA, 1-DA)",""),
        ],
    )
    srcSelect : bpy.props.EnumProperty(
        description= "Selects the SRC Buffer",
        name = "SRC Buffer Select",
        items = [('0', "Primary Accumulation Buffer SRC",""),
                 ('1', "Secondary Accumulation Buffer SRC",""),
        ],
    )
    dstSelect : bpy.props.EnumProperty(
        description= "Selects the DST Buffer",
        name = "DST Buffer Select",
        items = [('0', "Primary Accumulation Buffer DST",""),
                 ('1', "Secondary Accumulation Buffer DST",""),
        ],
    )
    fogOp : bpy.props.EnumProperty(
        description= "Fog Setting",
        name= "Fog Setting",
        items = [('0', "LUT (Look Up Table)",""),
                 ('1', "Per Vertex",""),
                 ('2', "No Fog",""),
                 ('3', "LUT M2 (Look Up Table, Mode 2)",""),
        ],
    )
    colorClamp : bpy.props.EnumProperty(
        description= "Sets color clamp mode",
        name = "Color Clamp",
        items = [('0', "Underflow",""),
                 ('1', "Overflow",""),
        ],
    )
    alphaOp : bpy.props.EnumProperty(
        description= "Sets alpha mode",
        name = "Alpha Mode",
        items = [('0', "Opaque",""),
                 ('1', "Translucent",""),
        ],
    )
    alphaTexOp : bpy.props.EnumProperty(
        description= "Sets usage of texture alpha",
        name = "Texture Alpha Usage",
        items = [('0', "Use Texture Alpha",""),
                 ('1', "Ignore Texture Alpha",""),
        ],
    )
    uvFlip : bpy.props.EnumProperty(
        description= "Sets UV flipping",
        name = "UV Flip Mode",
        items = [('0', "No Flipping",""),
                 ('1', "Flip Y",""),
                 ('2', "Flip X",""),
                 ('3', "Flip X,Y",""),
        ],
    )
    uvClamp : bpy.props.EnumProperty(
        description= "Sets UV clamping",
        name = "UV Clamp Mode",
        items = [('0', "No Clamping",""),
                 ('1', "Clamp Y",""),
                 ('2', "Clamp X",""),
                 ('3', "Clamp X,Y",""),
        ],
    )
    filter : bpy.props.EnumProperty(
        description= "Sets texture filtering",
        name = "Texture Filter",
        items = [('0', "Point Sampled",""),
                 ('1', "Bilinear Filter",""),
                 ('2', "Tri-linear Pass A",""),
                 ('3', "Tri-linear Pass B",""),
        ],
    )
    supSample : bpy.props.EnumProperty(
        description= "Sets super-sampling of texture",
        name = "Texture Super-Sample",
        items = [('0', "Disabled",""),
                 ('1', "Enabled",""),
        ],
    )
    mipmapDAdj : bpy.props.EnumProperty(
        description= "Mipmap D Adjust Setting",
        name = "Mipmap D Adjust",
        items = [( '1', "0.25",""),
                 ('2', "0.50", ""),
                 ('3', "0.75", ""),
                 ('4', "1.00",""),
                 ('5', "1.25", ""),
                 ('6', "1.50", ""),
                 ('7', "1.75", ""),
                 ('8', "2.00", ""),
                 ('9', "2.25", ""),
                 ('10', "2.50", ""),
                 ('11', "2.75", ""),
                 ('12', "3.00", ""),
                 ('13', "3.25", ""),
                 ('14', "3.50", ""),
                 ('15', "3.75", ""),
                 ( '0', "Illegal",""),
        ],
    )
    texShading : bpy.props.EnumProperty(
        description= "Texture/Shading",
        name = "Texture/Shading",
        items = [('0', "Decal [PIXrgb = TEXrgb + OFFSETrgb]  [PIXa = TEXa]",""),
                 ('1', "Modulate [PIXrgb = COLrgb * TEXrgb + OFFSETrgb]  [PIXa = TEXa]",""),
                 ('2', "Decal Alpha [PIXrgb = (TEXrgb + TEXa) + (COLrgb * (1-TEXa)) + OFFSETrgb]  [PIXa = COLa]",""),
                 ('3', "Modulate Alpha [PIXrgb = COLrgb * TEXrgb + OFFSETrgb]  [PIXa = COLa * TEXa]",""),
        ],
    )
    texUSize : bpy.props.EnumProperty(
        description= "Sets U Size (Width)",
        name= "U Size (Width)",
        items = [('0', "Width:    8 px",""),
                 ('1', "Width:   16 px",""),
                 ('2', "Width:   32 px",""),
                 ('3', "Width:   64 px",""),
                 ('4', "Width:  128 px",""),
                 ('5', "Width:  256 px",""),
                 ('6', "Width:  512 px",""),
                 ('7', "Width: 1024 px",""),
        ],
    )
    texVSize : bpy.props.EnumProperty(
        description= "Sets V Size (Height)",
        name= "V Size (Height)",
        items = [('0', "Height:    8 px",""),
                 ('1', "Height:   16 px",""),
                 ('2', "Height:   32 px",""),
                 ('3', "Height:   64 px",""),
                 ('4', "Height:  128 px",""),
                 ('5', "Height:  256 px",""),
                 ('6', "Height:  512 px",""),
                 ('7', "Height: 1024 px",""),
        ],
    )

class Naomi_TexCtrl_Properties(bpy.types.PropertyGroup):
    mipMapped : bpy.props.BoolProperty(
        description= "Is texture mipmapped?",
        name = "Mipmapped",
    )
    vqCompressed : bpy.props.BoolProperty(
        description= "Is texture VQ Compressed?",
        name = "VQ Compressed",
    )
    pixelFormat : bpy.props.EnumProperty(
        description= "Texture Pixel Format",
        name = "Pixel Format",
        items = [('0', "ARGB1555",""),
                    ('1', "RGB565",""),
                    ('2', "ARGB4444",""),
                    ('3', "YUV422",""),
                    ('4', "Bump Map",""),
                    ('5', "4 BPP Palette",""),
                    ('6', "8 BPP Palette",""),
#                 ('7', "ARGB1555",""),
                    ],
    )
    scanOrder : bpy.props.EnumProperty(
        description= "Texture Pixel Scan Order",
        name = "Scan Order",
        items = [('0', "Twiddled",""),
                 ('1', "Non-Twiddled",""),
                ],
    )
    texCtrlUstride : bpy.props.EnumProperty(
        description= "Use Texture Control for U Stride",
        name = "TexCtrl U-Stride",
        items = [('0', "Disabled",""),
                 ('1', "Enabled",""),
            ],
    )




class OBJECT_PT_Naomi_Properties(bpy.types.Panel):
    bl_label = "Naomi Properties"
    bl_idname = "OBJECT_PT_Naomi_Properties"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_category = "Naomi"



    @classmethod
    def poll(self, context):
        return context.active_object is not None

    def draw(self, context):
        active = context.active_object
        layout = self.layout

        layout.label(text= "Parameters")
        naomi_param_p = active.naomi_param
        box = layout.box()

        # Add Centroid parameters
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

        # Add mesh color properties
        row = box.row()
        row.label(text="Base Color:")
        row.prop(naomi_param_p, "meshColor",text="")

        row = box.row()
        row.label(text="Offset Color:")
        row.prop(naomi_param_p, "meshOffsetColor",text="")

        # Texture ID
        row = box.row()
        row.label(text="Texture ID")
        if naomi_param_p.mh_texID < 0:
            row.label(text="No Texture")  # -1
        else:
            row.prop(naomi_param_p,"mh_texID", text="")

        # Shading Type
        row = box.row()
        row.label(text="Shading Type")
        #row.label(text=str(naomi_param_p.m_tex_shading))
        row.prop(naomi_param_p,"m_shad_type", text="")

        # Specular Intensity
        row = box.row()
        row.label(text="Specular Intensity:")
        if naomi_param_p.m_tex_shading >= 0:
            row.prop(naomi_param_p, "spec_int", text="")
        else:
            row.label(text="Not Specified")

        # Texture Ambient Light
        row = box.row()
        row.label(text="Texture Ambient Light:")
        row.prop(naomi_param_p, "texture_ambient_light", text="")

        # Other params
        box.prop(naomi_param_p, "paramType")        # 31-29
        box.prop(naomi_param_p, "endOfStrip")       # 28
        box.prop(naomi_param_p, "listType")         # 26-24
        box.prop(naomi_param_p, "grpEn")            # 23
        box.prop(naomi_param_p, "stripLen")         # 19-18
        box.prop(naomi_param_p, "usrClip")          # 17-16
        box.prop(naomi_param_p, "shadow")           # 7
        box.prop(naomi_param_p, "volume")           # 6
        box.prop(naomi_param_p, "colType")          # 5-4
        box.prop(naomi_param_p, "textureUsage")     # 3
        box.prop(naomi_param_p, "offsColorUsage")   # 2
        box.prop(naomi_param_p, "gouraudShdUsage")  # 1
        box.prop(naomi_param_p, "uvDataSize")       # 0

        layout.label(text= "ISP/TSP")
        naomi_isp_tsp_p = active.naomi_isp_tsp
        box = layout.box()
        box.prop(naomi_isp_tsp_p, "depthCompare")
        box.prop(naomi_isp_tsp_p, "culling")
        box.prop(naomi_isp_tsp_p, "zWrite")
        box.prop(naomi_isp_tsp_p, "textureUsage")
        box.prop(naomi_isp_tsp_p, "offsColorUsage")
        box.prop(naomi_isp_tsp_p, "gouraudShdUsage")
        box.prop(naomi_isp_tsp_p, "uvDataSize")
        box.prop(naomi_isp_tsp_p, "cacheBypass")
        box.prop(naomi_isp_tsp_p, "dCalcCtrl")

        layout.label(text= "TSP")
        naomi_tsp_p = active.naomi_tsp
        box = layout.box()
        box.prop(naomi_tsp_p, "srcAlpha")
        box.prop(naomi_tsp_p, "dstAlpha")
        box.prop(naomi_tsp_p, "srcSelect")
        box.prop(naomi_tsp_p, "dstSelect")
        box.prop(naomi_tsp_p, "fogOp")
        box.prop(naomi_tsp_p, "colorClamp")
        box.prop(naomi_tsp_p, "alphaOp")
        box.prop(naomi_tsp_p, "alphaTexOp")
        box.prop(naomi_tsp_p, "uvFlip")
        box.prop(naomi_tsp_p, "uvClamp")
        box.prop(naomi_tsp_p, "filter")
        box.prop(naomi_tsp_p, "supSample")
        box.prop(naomi_tsp_p, "mipmapDAdj")
        box.prop(naomi_tsp_p, "texShading")
        box.prop(naomi_tsp_p, "texUSize")
        box.prop(naomi_tsp_p, "texVSize")

        layout.label(text= "Texture Control")
        naomi_tex_ctrl = active.naomi_texCtrl
        box = layout.box()
        row = box.row()
        row.prop(naomi_tex_ctrl, "mipMapped")
        row.prop(naomi_tex_ctrl, "vqCompressed")
        box.prop(naomi_tex_ctrl, "pixelFormat")
        box.prop(naomi_tex_ctrl, "scanOrder")
        box.prop(naomi_tex_ctrl, "texCtrlUstride")


classes = [Naomi_GlobalParam_0, Naomi_GlobalParam_1, COL_PT_collection_gps, Naomi_Param_Properties, Naomi_ISP_TSP_Properties, Naomi_TSP_Properties, Naomi_TexCtrl_Properties, OBJECT_PT_Naomi_Properties]

# Only needed if you want to add into a dynamic menu
def menu_func_import(self, context):
    self.layout.operator(ImportNL.bl_idname, text="NaomiLib (.bin / .raw)") #.bin or raw supported by SMB

def register():
    bpy.utils.register_class(ImportNL)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    #bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Object.naomi_param = bpy.props.PointerProperty(type= Naomi_Param_Properties)
    bpy.types.Object.naomi_isp_tsp = bpy.props.PointerProperty(type= Naomi_ISP_TSP_Properties)
    bpy.types.Object.naomi_tsp = bpy.props.PointerProperty(type= Naomi_TSP_Properties)
    bpy.types.Object.naomi_texCtrl = bpy.props.PointerProperty(type= Naomi_TexCtrl_Properties)
    bpy.types.Collection.gp0 = bpy.props.PointerProperty(type= Naomi_GlobalParam_0)
    bpy.types.Collection.gp1 = bpy.props.PointerProperty(type= Naomi_GlobalParam_1)

def unregister():
    bpy.utils.unregister_class(ImportNL)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    #bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    for cls in classes:
        bpy.utils.unregister_class(cls)
    del bpy.types.Object.naomi_param
    del bpy.types.Object.naomi_isp_tsp
    del bpy.types.Object.naomi_tsp
    del bpy.types.Object.naomi_texCtrl
    del bpy.types.Collection.gp0
    del bpy.types.Collection.gp1

if __name__ == "__main__":
    register()
