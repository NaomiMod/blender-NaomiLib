bl_info = {
    "name" : "NaomiLib importer for Blender",
    "author" : "zocker_160",
    "description" : "addon for importing NaomiLib bin files",
    "blender" : (2, 90, 1),
    "version" : (0, 12),
    "location" : "File > Import",
    "warning" : "",
    "category" : "Import",
    "tracker_url": "https://github.com/zocker-160/blender-NaomiLib"
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


# Only needed if you want to add into a dynamic menu
def menu_func_import(self, context):
    self.layout.operator(ImportNL.bl_idname, text="NaomiLib (.bin / .raw)") #.bin or raw supported by SMB

def register():
    bpy.utils.register_class(ImportNL)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    #bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

def unregister():
    bpy.utils.unregister_class(ImportNL)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    #bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)

if __name__ == "__main__":
    register()
