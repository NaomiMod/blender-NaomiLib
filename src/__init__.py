bl_info = {
    "name" : "NaomiLib for Blender",
    "author" : "zocker_160",
    "description" : "addon for importing and exporting NaomiLib bin files",
    "blender" : (2, 90, 0),
    "version" : (0, 1),
    "location" : "File > Import",
    "warning" : "only import is supported for now",
    "category" : "Import",
    "tracker_url": ""
}

import bpy
import importlib

from . import NLimporter as NLi

from bpy.props import StringProperty, BoolProperty
# ImportHelper is a helper class, defines filename and
# invoke() function which calls the file selector.
from bpy_extras.io_utils import ImportHelper, path_reference_mode

importlib.reload(NLimporter)


def import_nl(self, context, filepath: str, bCleanup: bool):
    if bCleanup:
        print("CLEANING UP")
        NLi.cleanup()

    ret = False
    #try:
    ret = NLi.main_function_import_file(self, filename=filepath)
    #except TypeError as e:
    #    self.report({'ERROR'}, str(e))
    #finally:
    return ret

class ImportNL(bpy.types.Operator, ImportHelper):
    """Import a NaomiLib file"""
    None

    bl_idname = "import_scene.naomilib"
    bl_label = "Import NaomiLib"

    filename_ext = ".bin"

    filter_glob: StringProperty(
        default="*.bin",
        options={'HIDDEN'},
        maxlen=255,  # Max internal buffer length, longer would be clamped.
    )

    setting_cleanup: BoolProperty(
        name="clean whole scene (!)",
        description="removes all objects and collections before import",
        default=False,
    )

    def execute(self, context):
        if import_nl(self, context, filepath=self.filepath, bCleanup=self.setting_cleanup):
            return {'FINISHED'}
        else:
            return {'CANCELLED'}


# Only needed if you want to add into a dynamic menu
def menu_func_import(self, context):
    self.layout.operator(ImportNL.bl_idname, text="NaomiLib (.bin)")

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
