bl_info = {
    "name" : "NaomiLib Importer for Blender",
    "author" : "zocker_160, VincentNL, TVIndustries",
    "description" : "Addon for importing NaomiLib .bin/.raw files",
    "blender" : (2, 90, 1),
    "version" : (0, 13, 1),
    "location" : "File > Import",
    "warning" : "",
    "category" : "Import",
    "tracker_url": "https://github.com/NaomiMod/blender-NaomiLib"
}

import bpy
import importlib

from . import NLimporter as NLi

from bpy.props import StringProperty, BoolProperty, FloatProperty
# ImportHelper is a helper class, defines filename and extention
from bpy_extras.io_utils import ImportHelper, path_reference_mode

importlib.reload(NLimporter)


def import_nl(self, context, filepath: str, bCleanup: bool, bArchive: bool, fScaling: float, bDebug: bool):
    if bCleanup:
        print("CLEANING UP")
        NLi.cleanup()

    ret = False

    if bArchive:
        ret = NLi.main_function_import_archive(self, filepath=filepath, scaling=fScaling, debug=bDebug)
    else:
        ret = NLi.main_function_import_file(self, filepath=filepath, scaling=fScaling, debug=bDebug)
    return ret

class ImportNL(bpy.types.Operator, ImportHelper):
    """Import a NaomiLib file"""    

    bl_idname = "import_scene.naomilib"
    bl_label = "Import NaomiLib"

    filename_ext = ".bin",".raw" #.bin or raw supported by SMB

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

    def execute(self, context):
        if import_nl(self, context, filepath=self.filepath, bCleanup=self.setting_cleanup, bArchive=self.setting_archive, fScaling=self.setting_scaling, bDebug=self.setting_debug):
            return {'FINISHED'}
        else:
            return {'CANCELLED'}
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
                 ('2', "Intesity Mode 1",""),
                 ('3', "Intesity Mode 2",""),
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
        
    
class Naomi_TexCtrl_Properties(bpy.types.PropertyGroup):
    mipMapped : bpy.props.EnumProperty(
        description= "Is texture mipmapped?",
        name = "Mipmapped", 
        items = [('0', "False",""),
                 ('1', "True",""),
            ],
    ) 
    vqCompressed : bpy.props.EnumProperty(
        description= "Is texture VQ Compressed?",
        name = "VQ Compressed", 
        items = [('0', "False",""),
                 ('1', "True",""),
            ],
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
        box.prop(naomi_param_p, "paramType")
        box.prop(naomi_param_p, "endOfStrip")
        box.prop(naomi_param_p, "listType")
        box.prop(naomi_param_p, "grpEn")   
        box.prop(naomi_param_p, "stripLen")  
        box.prop(naomi_param_p, "usrClip")
        box.prop(naomi_param_p, "shadow")   
        box.prop(naomi_param_p, "volume") 
        box.prop(naomi_param_p, "colType")
        box.prop(naomi_param_p, "textureUsage")   
        box.prop(naomi_param_p, "offsColorUsage")  
        box.prop(naomi_param_p, "gouraudShdUsage")
        box.prop(naomi_param_p, "uvDataSize")
        
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
        
        
        layout.label(text= "Texture Control")
        naomi_tex_ctrl = active.naomi_texCtrl
        box = layout.box()
        box.prop(naomi_tex_ctrl, "mipMapped")
        box.prop(naomi_tex_ctrl, "vqCompressed")
        box.prop(naomi_tex_ctrl, "pixelFormat")
        box.prop(naomi_tex_ctrl, "scanOrder")
        box.prop(naomi_tex_ctrl, "texCtrlUstride")
  
        
classes = [Naomi_Param_Properties, Naomi_ISP_TSP_Properties, Naomi_TexCtrl_Properties, OBJECT_PT_Naomi_Properties]

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
    bpy.types.Object.naomi_texCtrl = bpy.props.PointerProperty(type= Naomi_TexCtrl_Properties)

def unregister():
    bpy.utils.unregister_class(ImportNL)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    #bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    for cls in classes:
        bpy.utils.unregister_class(cls)
    del bpy.types.Object.naomi_param   
    del bpy.types.Object.naomi_isp_tsp
    del bpy.types.Object.naomi_texCtrl 

if __name__ == "__main__":
    register()
