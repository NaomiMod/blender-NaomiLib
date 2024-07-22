import bpy
from . pvr2image import decode as pvrdecode
from bpy.types import Operator
from bpy.props import FloatVectorProperty
from bpy_extras.object_utils import AddObjectHelper, object_data_add
import struct
import os
from io import BytesIO
from math import radians
from mathutils import Vector

xVal = 0
yVal = 1
zVal = 2

# static magic numbers and headers , updated as per official naming

magic_naomilib = [
    b'\x01\x00\x00\x00\x01\x00\x00\x00',  # Super index , always true
    b'\x00\x00\x00\x00\x01\x00\x00\x00',  # Pure beta , always true
    b'\x01\x00\x00\x00\x02\x00\x00\x00',  # Super index , skip 1st light source
    b'\x00\x00\x00\x00\x02\x00\x00\x00',  # Pure beta , skip 1st light source
    b'\x01\x00\x00\x00\x03\x00\x00\x00',  # Super index , always true , skip 1st light source
    b'\x00\x00\x00\x00\x03\x00\x00\x00',  # Pure beta , always true , skip 1st light source
    b'\x01\x00\x00\x00\x05\x00\x00\x00',  # Super index , always true , Environment mapping
    b'\x00\x00\x00\x00\x05\x00\x00\x00',  # Pure Beta , always true , Environment mapping
    b'\x01\x00\x00\x00\x07\x00\x00\x00',  # Super index , always true , Environment mapping, skip 1st light source
    b'\x00\x00\x00\x00\x07\x00\x00\x00',  # Pure Beta , always true , Environment mapping, skip 1st light source
    b'\x01\x00\x00\x00\x11\x00\x00\x00',  # Super index , always true , Bump mapping
    b'\x00\x00\x00\x00\x11\x00\x00\x00',  # Pure Beta , always true , Bump mapping
    b'\x01\x00\x00\x00\x19\x00\x00\x00',  # Super index , always true , Bump mapping, palette texture
    b'\x00\x00\x00\x00\x19\x00\x00\x00',  # Pure Beta , always true , Bump mapping, palette texture
    b'\x01\x00\x00\x00\x15\x00\x00\x00',  # Super index , always true , Environment mapping, Bump mapping
    b'\x00\x00\x00\x00\x15\x00\x00\x00',  # Pure Beta , always true , Environment mapping, Bump mapping
]

#############################
# main parse function
#############################

def parse_nl(nl_bytes: bytes, orientation, NegScale_X: bool, debug=False) -> list:
    global model_log
    nlfile = BytesIO(nl_bytes)

    _magic = nlfile.read(0x8)
    if _magic not in magic_naomilib:
        raise TypeError("ERROR: This is not a supported NaomiLib file!")
        return {'CANCELLED'}

    read_uint32_buff = lambda: struct.unpack("<I", nlfile.read(0x4))[0]
    read_sint32_buff = lambda: struct.unpack("<i", nlfile.read(0x4))[0]
    read_float_buff = lambda: struct.unpack("<f", nlfile.read(0x4))[0]

    read_point3_buff = lambda: struct.unpack("<fff", nlfile.read(0xC))
    read_point2_buff = lambda: struct.unpack("<ff", nlfile.read(0x8))


    # sint8 to float, code by Zocker!                / need to verify accuracy
    def sint8_to_float(num: int) -> float:
        min, max = 0x7f, 0x80
        if num > 0x7f:
            num -= 0x100
            return num / max
        else:
            return num / min

    # specular to float   # WIP
    def spec_to_float(num: int) -> float:

        if num == 0x0:
            return (1)
        elif num <= 0x5:
            return (1 / num)
        elif num > 0x5:
            return ((1 / num) + (0.02))

    # convert vertex hex color to blender float
    def col_hex_to_float(num: int) -> float:
        max = 0xFF
        return num / max

    #############################
    # model header function
    #############################

    # Read Model Header Global_Flag0, to determine model format

    gflag_headers = list()

    nlfile.seek(0x0)
    gflag0 = (nlfile.read(0x1))
    g_flag0 = int.from_bytes(gflag0, 'little')
    gflag_headers.append(g_flag0)

    if debug:
        model_log += (
            "#---------------------------#\n"
            "#    Naomi_Library_Model    #\n"
            "#---------------------------#\n"
            "-----Global_Flag0-----\n"
        )

        if gflag0 == b'\x00':
            model_log += 'Pure_Beta\n'
        elif gflag0 == b'\x01':
            model_log += 'Super_Index\n'
        elif gflag0 == b'\xFF':
            model_log += 'NULL\n'
        else:
            model_log += "ERROR!\n\n"

    # Read Model Header Global_Flag1, to determine model format

    nlfile.seek(0x4)
    gflag1 = (nlfile.read(0x2))
    gflag1 = int.from_bytes(gflag1, "little")
    gflag1_bit0 = (gflag1 >> 0) & 1
    gflag1_bit1 = (gflag1 >> 1) & 1
    gflag1_bit2 = (gflag1 >> 2) & 1
    gflag1_bit3 = (gflag1 >> 3) & 1
    gflag1_bit4 = (gflag1 >> 4) & 1
    gflag1_bit5 = (gflag1 >> 5) & 1
    gflag1_bit6 = (gflag1 >> 6) & 1
    gflag1_bit7 = (gflag1 >> 7) & 1
    gflag1_bit8 = (gflag1 >> 8) & 1

    gflag_headers.append(gflag1_bit1)
    gflag_headers.append(gflag1_bit2)
    gflag_headers.append(gflag1_bit3)
    gflag_headers.append(gflag1_bit4)
    if debug:
        bit_ny = ["No ", "Yes"]  # It's just a list to show No or Yes, based on bit value 0 or 1

        model_log += (
            "-----Global_Flag1-----\n"
            f"bit0     | Always true          :[{gflag1_bit0}] {bit_ny[gflag1_bit0]}\n"
            f"bit1     | Skip 1st lgt src op. :[{gflag1_bit1}] {bit_ny[gflag1_bit1]}\n"
            f"bit2     | Environment mapping  :[{gflag1_bit2}] {bit_ny[gflag1_bit2]}\n"
            f"bit3     | Palette texture      :[{gflag1_bit3}] {bit_ny[gflag1_bit3]}\n"
            f"bit4     | Bump map available   :[{gflag1_bit4}] {bit_ny[gflag1_bit4]}\n"
            f"bit5     | Reserved 1           :[{gflag1_bit5}] {bit_ny[gflag1_bit5]}\n"
            f"bit6     | Reserved 2           :[{gflag1_bit6}] {bit_ny[gflag1_bit6]}\n"
            f"bit7     | Reserved 3           :[{gflag1_bit7}] {bit_ny[gflag1_bit7]}\n"
            f"bit8     | Reserved 4           :[{gflag1_bit8}] {bit_ny[gflag1_bit8]}\n"
        )

    # Model Header Object Centroid: x,y,z,bounding radius
    nlfile.seek(0x8)
    obj_centr_x = read_float_buff()
    obj_centr_y = read_float_buff()
    obj_centr_z = read_float_buff()
    obj_bound_radius = read_float_buff()

    if debug:
        model_log += (
            f"-----\n"
            f"obj_centroid: x = {obj_centr_x}\nobj_centroid: y = {obj_centr_y}\n"
            f"obj_centroid: z = {obj_centr_z}\nobj_bnd_radius: = {obj_bound_radius}\n"
        )

    ###################
    # mesh parameters #
    ###################

    #### mesh parameters data structure
    # 1.[mesh_param]--> 2.[mesh_isp_tsp]--> 3.[tsp]--> 4.[texture_ctrl]         # tot.4 unit32 storing bitflags
    # 5.[mesh_centroid[xVal|yVal|zVal|bound_radious]                            # tot.4 floats (x,y,z,b.radius)
    # 6.[Texture No]--> 7.[tex_shading]--> 8.[tex_ambient]                      # sint32,sint32,float
    # 9.[Base_Alpha|Red|Green|Blue]                                             # tot.4 floats (base ARGB)
    # 10.[Offset_Alpha|Red|Green|Blue]                                          # tot.4 floats (offset ARGB)
    # 11.[mesh_size]                                                            # uint32 (mesh size)
    # ###

    def mesh_param():
        global model_log

        # print(f"current position: {hex(nlfile.tell())}")

        # 1. mesh parameters bit0-31

        m_pflag = read_uint32_buff()
        m_pflag_bit0 = (m_pflag >> 0) & 1
        m_pflag_bit1 = (m_pflag >> 1) & 1
        m_pflag_bit2 = (m_pflag >> 2) & 1
        m_pflag_bit3 = (m_pflag >> 3) & 1
        m_pflag_bit4_5 = (m_pflag >> 4) & 3
        m_pflag_bit6 = (m_pflag >> 6) & 1
        m_pflag_bit7 = (m_pflag >> 7) & 1
        m_pflag_bit17_16 = (m_pflag >> 16) & 3
        m_pflag_bit19_18 = (m_pflag >> 18) & 3
        m_pflag_bit23 = (m_pflag >> 23) & 1
        m_pflag_bit24_26 = (m_pflag >> 24) & 7
        m_pflag_bit28 = (m_pflag >> 28) & 1
        m_pflag_bit29_31 = (m_pflag >> 29) & 7

        l_Parameter_Header = list()
        l_Parameter_Header.append(m_pflag_bit29_31)  # 0
        l_Parameter_Header.append(m_pflag_bit28)  # 1
        l_Parameter_Header.append(m_pflag_bit24_26)  # 2
        l_Parameter_Header.append(m_pflag_bit23)  # 3
        l_Parameter_Header.append(m_pflag_bit19_18)  # 4
        l_Parameter_Header.append(m_pflag_bit17_16)  # 5
        l_Parameter_Header.append(m_pflag_bit7)  # 6
        l_Parameter_Header.append(m_pflag_bit6)  # 7
        l_Parameter_Header.append(m_pflag_bit4_5)  # 8
        l_Parameter_Header.append(m_pflag_bit3)  # 9
        l_Parameter_Header.append(m_pflag_bit2)  # 10
        l_Parameter_Header.append(m_pflag_bit1)  # 11
        l_Parameter_Header.append(m_pflag_bit0)  # 12

        if debug:
            # lists of mesh parameters options! Debug only!

            bit_par0 = ["32/bit U/V ", "16/bit U/V "]
            bit_par1 = ["Flat ", "Gouraud "]
            bit_par4_5 = ["Packed Color", "Floating Color", "Intensity Mode 1", "Intensity Mode 2"]
            bit_par24_26 = ["Opaque", "Opaque Modifier Volume", "Translucent", "Translucent Modifier Volume",
                            "Punch Through", "Reserved", "Reserved", "Reserved"]
            bit_par29_31 = ["Control Parameter End Of List", "Control Parameter User Tile Clip",
                            "Control Parameter Object List Set", "Reserved",
                            "Global Parameter Polygon or Modifier Volume", "Global Parameter Sprite",
                            "Global Parameter Reserved", "Vertex Parameter"]

            # Debug printout

            model_log += (
               f"\n-----------------------------\n"
               f"     Mesh {m} Header        \n"
               f"-----------------------------\n\n-----Mesh_Param_Flags-----\n"
                f"bit0     | 16/bit U/V   :[{m_pflag_bit0}] {bit_par0[m_pflag_bit0]}\n"
                f"bit1     | Gouraud      :[{m_pflag_bit1}] {bit_par1[m_pflag_bit1]}\n"
                f"bit2     | Color Offset :[{m_pflag_bit2}] {bit_ny[m_pflag_bit2]}\n"
                f"bit3     | Texture      :[{m_pflag_bit3}] {bit_ny[m_pflag_bit3]}\n"
                f"bit4-5   | Color Type   :[{m_pflag_bit4_5}] {bit_par4_5[m_pflag_bit4_5]}\n"
                f"bit6     | Use Volume   :[{m_pflag_bit6}] {bit_ny[m_pflag_bit6]}\n"
                f"bit7     | Use Shadow   :[{m_pflag_bit7}] {bit_ny[m_pflag_bit7]}\n"
                f"bit24-26   | List Type    :[{m_pflag_bit24_26}] {bit_par24_26[m_pflag_bit24_26]}\n"
                f"bit29-31 | Para Type    :[{m_pflag_bit29_31}] {bit_par29_31[m_pflag_bit29_31]}\n"
            )

        # 2. mesh parameters bit20-31         / 0-19 it's unused

        m_isptspflag = read_uint32_buff()
        m_isptspflag_bit20 = (m_isptspflag >> 20) & 1
        m_isptspflag_bit21 = (m_isptspflag >> 21) & 1
        m_isptspflag_bit22 = (m_isptspflag >> 22) & 1
        m_isptspflag_bit23 = (m_isptspflag >> 23) & 1
        m_isptspflag_bit24 = (m_isptspflag >> 24) & 1
        m_isptspflag_bit25 = (m_isptspflag >> 25) & 1
        m_isptspflag_bit26 = (m_isptspflag >> 26) & 1
        m_isptspflag_bit27_28 = (m_isptspflag >> 27) & 3
        m_isptspflag_bit29_31 = (m_isptspflag >> 29) & 7

        l_ISP_TSP_Header = list()
        l_ISP_TSP_Header.append(m_isptspflag_bit29_31)
        l_ISP_TSP_Header.append(m_isptspflag_bit27_28)
        l_ISP_TSP_Header.append(m_isptspflag_bit26)
        l_ISP_TSP_Header.append(m_isptspflag_bit25)
        l_ISP_TSP_Header.append(m_isptspflag_bit24)
        l_ISP_TSP_Header.append(m_isptspflag_bit23)
        l_ISP_TSP_Header.append(m_isptspflag_bit22)
        l_ISP_TSP_Header.append(m_isptspflag_bit21)
        l_ISP_TSP_Header.append(m_isptspflag_bit20)

        if debug:
            # lists of mesh parameters options! Debug only!

            bit_par20 = ["No", "Use D Calc for small polys"]
            bit_par22 = ["32/bit U/V ", "16/bit U/V "]
            bit_par23 = ["Flat ", "Gouraud "]
            bit_par27_28 = ["No Culling", "Cull if Small", "Cull if Negative", "Cull if Positive"]
            bit_par29_31 = ["NEVER", "LESS", "EQUAL", "LESS OR EQUAL", "GREATER", "NOT_EQUAL", "GREATER OR EQUAL",
                            "ALWAYS"]

            # Debug printout

            model_log += (
                "\n-----Mesh_ISP_TSP-----\n"
                f"bit20    | DcalcCtrl        :[{m_isptspflag_bit20}] {bit_par20[m_isptspflag_bit20]}\n"
                f"bit21    | CacheBypass      :[{m_isptspflag_bit21}] {bit_ny[m_isptspflag_bit21]}\n"
                f"bit22    | 16bit_UV2        :[{m_isptspflag_bit22}] {bit_par22[m_isptspflag_bit22]}\n"
                f"bit23    | Gouraud2         :[{m_isptspflag_bit23}] {bit_par23[m_isptspflag_bit23]}\n"
                f"bit24    | Offset2          :[{m_isptspflag_bit24}] {bit_ny[m_isptspflag_bit24]}\n"
                f"bit25    | Texture2         :[{m_isptspflag_bit25}] {bit_ny[m_isptspflag_bit25]}\n"
                f"bit26    | ZWriteDisable    :[{m_isptspflag_bit26}] {bit_ny[m_isptspflag_bit26]}\n"
                f"bit27-28 | CullingMode      :[{m_isptspflag_bit27_28}] {bit_par27_28[m_isptspflag_bit27_28]}\n"
                f"bit29-31 | DepthCompareMode :[{m_isptspflag_bit29_31}] {bit_par29_31[m_isptspflag_bit29_31]}\n"
            )

        # 3. mesh tsp parameters bit0-31       /  OMG SEGA, I love ya.

        m_tspflag = read_uint32_buff()
        m_tspflag_bit0_2 = (m_tspflag >> 0) & 7
        m_tspflag_bit3_5 = (m_tspflag >> 3) & 7
        m_tspflag_bit6_7 = (m_tspflag >> 6) & 3
        m_tspflag_bit8_11 = (m_tspflag >> 8) & 15
        m_tspflag_bit12 = (m_tspflag >> 12) & 1
        m_tspflag_bit13_14 = (m_tspflag >> 13) & 3
        m_tspflag_bit15_16 = (m_tspflag >> 15) & 3
        m_tspflag_bit17_18 = (m_tspflag >> 17) & 3
        m_tspflag_bit19 = (m_tspflag >> 19) & 1
        m_tspflag_bit20 = (m_tspflag >> 20) & 1
        m_tspflag_bit21 = (m_tspflag >> 21) & 1
        m_tspflag_bit22_23 = (m_tspflag >> 22) & 3
        m_tspflag_bit24 = (m_tspflag >> 24) & 1
        m_tspflag_bit25 = (m_tspflag >> 25) & 1
        m_tspflag_bit26_28 = (m_tspflag >> 26) & 7
        m_tspflag_bit29_31 = (m_tspflag >> 29) & 7

        l_TSP_Header = list()
        l_TSP_Header.append(m_tspflag_bit29_31)
        l_TSP_Header.append(m_tspflag_bit26_28)
        l_TSP_Header.append(m_tspflag_bit25)
        l_TSP_Header.append(m_tspflag_bit24)
        l_TSP_Header.append(m_tspflag_bit22_23)
        l_TSP_Header.append(m_tspflag_bit21)
        l_TSP_Header.append(m_tspflag_bit20)
        l_TSP_Header.append(m_tspflag_bit19)
        l_TSP_Header.append(m_tspflag_bit17_18)
        l_TSP_Header.append(m_tspflag_bit15_16)
        l_TSP_Header.append(m_tspflag_bit13_14)
        l_TSP_Header.append(m_tspflag_bit12)
        l_TSP_Header.append(m_tspflag_bit8_11)
        l_TSP_Header.append(m_tspflag_bit6_7)
        l_TSP_Header.append(m_tspflag_bit3_5)
        l_TSP_Header.append(m_tspflag_bit0_2)

        if debug:
            # lists of mesh parameters options! Debug only!

            bit_par_px_size = ["8 px", "16 px", "32 px", "64 px", "128 px", "256 px", "512 px", "1024 px"]
            bit_par6_7 = ["Decal [PIXrgb = TEXrgb + OFFSETrgb]  [PIXa = TEXa]",
                          "Modulate [PIXrgb = COLrgb * TEXrgb + OFFSETrgb]  [PIXa = TEXa]",
                          "Decal Alpha [PIXrgb = (TEXrgb + TEXa) + (COLrgb * (1-TEXa)) + OFFSETrgb]  [PIXa = COLa]",
                          "Modulate Alpha [PIXrgb = COLrgb * TEXrgb + OFFSETrgb]  [PIXa = COLa * TEXa]"]
            bit_par8_11 = ["Illegal", "0,25", "0,50", "0,75", "1,00", "1,25", "1,50", "1,75", "2,00",
                           "2,25", "2,50", "2,75", "3,00", "3,25", "3,50", "3,75"]
            bit_par13_14 = ["Point Sampled", "Bilinear Filter", "Tri-linear Pass A", "Tri-linear Pass B"]
            bit_par15_16 = ["No", "Clamp Y", "Clamp X", "Clamp XY"]
            bit_par17_18 = ["No", "Flip Y", "Flip X", "Flip X, Y"]
            bit_par20 = ["Opaque", "Use Alpha"]
            bit_par21 = ["Underflow", "Overflow"]
            bit_par22_23 = ["Look Up Table", "Per Vertex", "No Fog", "Look Up Table Mode 2"]
            bit_par24 = ["No", "Use secondary accumulation buffer as destination"]
            bit_par25 = ["No", "Use secondary accumulation buffer as source"]
            bit_par_src_dst = ["Zero (0, 0, 0, 0)", "One (1, 1, 1, 1)", "‘Other’ Color (OR, OG, OB, OA)",
                               "Inverse ‘Other’ Color (1-OR, 1-OG, 1-OB, 1-OA)", "SRC Alpha (SA, SA, SA, SA)",
                               "Inverse SRC Alpha (1-SA, 1-SA, 1-SA, 1-SA)", "DST Alpha (DA, DA, DA, DA)",
                               "Inverse DST Alpha (1-DA, 1-DA, 1-DA, 1-DA)"]

            # Debug printout

            model_log += (
                "\n-----Mesh_TSP-----\n"
                f"bit0-2    | Texture V Size (Height) :[{m_tspflag_bit0_2}] {bit_par_px_size[m_tspflag_bit0_2]}\n"
                f"bit3-5    | Texture U Size (Width)  :[{m_tspflag_bit3_5}] {bit_par_px_size[m_tspflag_bit3_5]}\n"
                f"bit6-7    | Texture / Shading       :[{m_tspflag_bit6_7}] {bit_par6_7[m_tspflag_bit6_7]}\n"
                f"bit8-11   | Mipmap D Adjust         :[{m_tspflag_bit8_11}] {bit_par8_11[m_tspflag_bit8_11]}\n"
                f"bit12     | Super Sampling          :[{m_tspflag_bit12}] {bit_ny[m_tspflag_bit12]}\n"
                f"bit13-14  | Filter                  :[{m_tspflag_bit13_14}] {bit_par13_14[m_tspflag_bit13_14]}\n"
                f"bit15-16  | Clamp UV                :[{m_tspflag_bit15_16}] {bit_par15_16[m_tspflag_bit15_16]}\n"
                f"bit17-18  | Flip UV                 :[{m_tspflag_bit17_18}] {bit_par17_18[m_tspflag_bit17_18]}\n"
                f"bit19     | Ignore Tex.Alpha        :[{m_tspflag_bit19}] {bit_ny[m_tspflag_bit19]}\n"
                f"bit20     | Use Alpha               :[{m_tspflag_bit20}] {bit_par20[m_tspflag_bit20]}\n"
                f"bit21     | Color Clamp             :[{m_tspflag_bit21}] {bit_par21[m_tspflag_bit21]}\n"
                f"bit22-23  | Fog Control             :[{m_tspflag_bit22_23}] {bit_par22_23[m_tspflag_bit22_23]}\n"
                f"bit24     | DST Select              :[{m_tspflag_bit24}] {bit_par24[m_tspflag_bit24]}\n"
                f"bit25     | SRC Select              :[{m_tspflag_bit25}] {bit_par25[m_tspflag_bit25]}\n"
                f"bit26-28  | DST Alpha               :[{m_tspflag_bit26_28}] {bit_par_src_dst[m_tspflag_bit26_28]}\n"
                f"bit29-31  | SRC Alpha               :[{m_tspflag_bit29_31}] {bit_par_src_dst[m_tspflag_bit29_31]}\n"
            )

        # 4. texture control bit0-31         / 0-24 texture address , always 0

        m_tctflag = read_uint32_buff()
        m_tctflag_bit0_24 = (m_tctflag >> 0) & 23
        m_tctflag_bit25 = (m_tctflag >> 25) & 1
        m_tctflag_bit26 = (m_tctflag >> 26) & 1
        m_tctflag_bit27_29 = (m_tctflag >> 27) & 7
        m_tctflag_bit30 = (m_tctflag >> 30) & 1
        m_tctflag_bit31 = (m_tctflag >> 31) & 1

        l_texCtrl_Header = list()
        l_texCtrl_Header.append(m_tctflag_bit31)
        l_texCtrl_Header.append(m_tctflag_bit30)
        l_texCtrl_Header.append(m_tctflag_bit27_29)
        l_texCtrl_Header.append(m_tctflag_bit26)
        l_texCtrl_Header.append(m_tctflag_bit25)
        l_texCtrl_Header.append(m_tctflag_bit0_24)

        if debug:
            # lists of mesh parameters options! Debug only!

            tctflag_par_bit0_24 = [" "]
            tctflag_par_bit25 = ["No", "Use Texture Control for U Stride"]
            tctflag_par_bit26 = ["Twiddled", "Non-Twiddled"]
            tctflag_par_bit27_29 = ["ARGB1555", "RGB565", "ARGB4444", "YUV422", "Bump Map",
                                    "4 BPP Palette", "8 BPP Palette", "Reserved"]

            # Debug printout

            model_log += (
                "\n-----Mesh_Texture_Control_Flags-----\n"
                f"bit0-24  | Texture Address   :[{m_tctflag_bit0_24}] {tctflag_par_bit0_24[m_tctflag_bit0_24]}\n"
                f"bit25    | StrideSelect      :[{m_tctflag_bit25}] {tctflag_par_bit25[m_tctflag_bit25]}\n"
                f"bit26    | Scan Order        :[{m_tctflag_bit26}] {tctflag_par_bit26[m_tctflag_bit26]}\n"
                f"bit27-29 | Pixel Format      :[{m_tctflag_bit27_29}] {tctflag_par_bit27_29[m_tctflag_bit27_29]}\n"
                f"bit30    | VQ Compressed     :[{m_tctflag_bit30}] {bit_ny[m_tctflag_bit30]}\n"
                f"bit31    | Mip Mapped        :[{m_tctflag_bit31}] {bit_ny[m_tctflag_bit31]}\n"
            )

        # 5. mesh centroid x,y,z, bound radius

        m_centr_x = read_float_buff()
        m_centr_y = read_float_buff()
        m_centr_z = read_float_buff()
        m_bound_radius = read_float_buff()
        m_centroid.append((m_centr_x,m_centr_y,m_centr_z,m_bound_radius))

        if debug:
            model_log += (
                "\n-----Mesh_Centroid_&_Bound_Radius-----\n"
                f"mesh_centroid: x = {m_centr_x}\n"
                f"mesh_centroid: y = {m_centr_y}\n"
                f"mesh_centroid: z = {m_centr_z}\n"
                f"mesh_bnd_radius: = {m_bound_radius}\n"
            )


        # 6. texture ID

        m_texID = read_sint32_buff()

        if debug:

            if m_texID == -1:
                t_var = ("No Texture!")
            else:
                t_var = str(m_texID)

            model_log += (
                "\n-----Mesh_Texture_ID-----\n"
                f"Texture ID: {t_var}\n"
            )

        # 7. texture shading

        m_tex_shading = read_sint32_buff()
        # spec_int = m_tex_shading / 10     Original, but currently not giving accurate results
        spec_int= m_tex_shading

        if debug:

            if m_tex_shading == -3:
                t_var2 = ("Vertex Colors Mode")
            elif m_tex_shading == -2:
                t_var2 = ("Bump Mode")
            elif m_tex_shading == -1:
                t_var2 = ("Constant Mode")
            else:
                t_var2 = (f"Lambert Mode - Specular Intensity: {spec_int}")

            model_log += (
                "\n-----Mesh_Texture_Shading-----\n"
                f"[{m_tex_shading}] {t_var2}\n"
            )

        # 8. texture ambient lighting

        m_tex_amb = read_float_buff()

        if debug:
            model_log +=(f"Texture Ambient Light: {m_tex_amb}\n")

        # 9. base color ARGB

        m_col_base_A = read_float_buff()
        m_col_base_R = read_float_buff()
        m_col_base_G = read_float_buff()
        m_col_base_B = read_float_buff()
        mesh_colors.append((m_col_base_R, m_col_base_G, m_col_base_B, m_col_base_A))  # Blender surface color is RGBA

        if debug:
            model_log += (
                "\n-----Mesh_Base_Colors_ARGB-----\n"
                f"Alpha: {m_col_base_A}\n"
                f"Red  : {m_col_base_R}\n"
                f"Green: {m_col_base_G}\n"
                f"Blue : {m_col_base_B}\n"
            )

        # 10. offset color ARGB

        m_col_offs_A = read_float_buff()
        m_col_offs_R = read_float_buff()
        m_col_offs_G = read_float_buff()
        m_col_offs_B = read_float_buff()

        if debug:
            model_log += (
                "\n-----Mesh_Offset_Colors_ARGB-----\n"
                f"Alpha: {m_col_offs_A}\n"
                f"Red  : {m_col_offs_R}\n"
                f"Green: {m_col_offs_G}\n"
                f"Blue : {m_col_offs_B}\n"
            )

        mesh_offcolors.append((m_col_offs_R, m_col_offs_G, m_col_offs_B, m_col_offs_A))  # Blender surface color is RGBA



        # 11. mesh size

        mesh_end_offset = read_uint32_buff()

        if debug:
            print("\n" + "-----Mesh_Size-----" + "\n")
            print(f"Mesh Data Size: {hex(mesh_end_offset)}")

        m_Headers = (l_Parameter_Header, l_ISP_TSP_Header, l_TSP_Header, l_texCtrl_Header, m_texID,m_tex_shading)
        return m_Headers

    ##############################
    # Parse polygon bitflags     #
    ##############################

    def poly_flags():

        # 1. polygon parameters bit0-8
        f_type = int.from_bytes(face_type, "little")

        p_flag_bit0_1 = (f_type >> 0) & 3
        p_flag_bit2 = (f_type >> 2) & 1
        p_flag_bit3 = (f_type >> 3) & 1
        p_flag_bit4 = (f_type >> 4) & 1
        p_flag_bit5 = (f_type >> 5) & 1
        p_flag_bit6 = (f_type >> 6) & 1
        p_flag_bit7 = (f_type >> 7) & 1
        p_flag_bit8 = (f_type >> 8) & 1

        if debug:
            # lists of mesh parameters options! Debug only!

            bit_ppar0_1 = ["clockwise", "counter-clock", "single-side (clockwise)", "double-sided (counter-clockwise)"]
            bit_ppar6 = ["No (Flat)", "Yes"]
            bit_ppar7 = ["Send global params", "Don't send global params"]

            # Debug printout

            print("\n" + "-----------------------------")
            print(f"     Poly {f} Flags        ")
            print("-----------------------------")
            print("bit0-1   | Culling      :[" + str(p_flag_bit0_1) + "] " + bit_ppar0_1[(p_flag_bit0_1)])
            print("bit2     | Sprite(Quad) :[" + str(p_flag_bit2) + "] " + bit_ny[(p_flag_bit2)])
            print("bit3     | Triangles    :[" + str(p_flag_bit3) + "] " + bit_ny[(p_flag_bit3)])
            print("bit4     | Strip        :[" + str(p_flag_bit4) + "] " + bit_ny[(p_flag_bit4)])
            print("bit5     | Super Index  :[" + str(p_flag_bit5) + "] " + bit_ny[(p_flag_bit5)])
            print("bit6     | Gouraud      :[" + str(p_flag_bit6) + "] " + bit_ppar6[(p_flag_bit6)])
            print("bit7     | NOT Send GP  :[" + str(p_flag_bit7) + "] " + bit_ppar7[(p_flag_bit7)])
            print("bit8     | Env.Mapping  :[" + str(p_flag_bit8) + "] " + bit_ny[(p_flag_bit8)])

    ##############################
    # Parse Type C Vertex        #
    ##############################

    ###########################
    #
    # if m_tex_shading == -3, it is Type C:
    # [xVal|yVal|zVal],[sint8 nx,ny,nz],[0x00],[vtx_color1],[vtx color2],[U],[V]
    #
    # note, vtx_color2 is always the same of vtx_color1. Color format is Hex: BGRA8888
    #
    ###########################

    def type_c():
        norm_sint8_x = sint8_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        norm_sint8_y = sint8_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        norm_sint8_z = sint8_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        nlfile.read(0x1)  # zero byte

        vtx_col1_B = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col1_G = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col1_R = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col1_A = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col2_B = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col2_G = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col2_R = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col2_A = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))

        normal.append((norm_sint8_x, norm_sint8_y, norm_sint8_z))
        vert_col.append((vtx_col1_R, vtx_col1_G, vtx_col1_B, vtx_col1_A))

        if debug: print(
            f"(normals: x,y,z: {normal}\nvtx_col1: ARGB:{vtx_col1_A} {vtx_col1_R} {vtx_col1_G} {vtx_col1_B}\n"
            f"vtx_col2: ARGB:{vtx_col2_A} {vtx_col2_R} {vtx_col2_G} {vtx_col2_B}")

    ##############################
    # Parse Type D Vertex        #
    ##############################

    ###########################
    #
    # if m_tex_shading == -2, it is Type D:
    # [xVal|yVal|zVal],[nxVal|nyVal|nzVal],
    # [bump0nxVal|bump0nyVal|bump0nzVal],
    # [bump1nxVal|bump1nyVal|bump1nzVal],
    # [U],[V]
    #
    ###########################
    def type_d():

        # Bump map
        normal.append(read_point3_buff())
        nlfile.seek(nlfile.tell()+0x18)  # WIP temporary skip bumpmap1-2 norms

    ######################################
    #  Zocker_160 code, do not change it!       /  I love your code buddy, it's awesome, really.
    ######################################

    meshes = list()
    mesh_faces = list()
    mesh_colors = list()
    mesh_offcolors = list()
    mesh_vertcol = list()
    m_headr_grps = list()
    m_centroid = list()
    m_backface = list()
    m_env = list()

    nlfile.seek(0x64)  # size of mesh
    mesh_end_offset = read_uint32_buff() + 0x64
    if debug: print("MESH END offset START:", mesh_end_offset)
    m = 0

    # while not EOF
    while nlfile.read(0x4) != b'\x00\x00\x00\x00':

        if m == 0:  # first loop needs special treatment

            nlfile.seek(0x18)  # first mesh parameters always start at 0x18
            m_headr_grps.append(mesh_param())
        else:
            if debug:
                print(nlfile.tell())

            nlfile.seek(nlfile.tell() - 0x4, 0x0)  # Get ready to read mesh params
            m_headr_grps.append(mesh_param())  # read mesh header parameters
            nlfile.seek(-0x4, 0x1)  # Continue to read file

            if debug: print(nlfile.tell())

            mesh_end_offset = read_uint32_buff() + nlfile.tell()

            if debug: print("MESH END offset m > 0:", mesh_end_offset)

        #print(m_headr_grps[0][5])
        m_tex_shading=m_headr_grps[-1][-1]
        faces_vertex = list()
        faces_index = list()
        vert_col = list()
        vertex = list()
        normal = list()
        texture_uv = list()
        f_idx = list()
        f = 0
        u = 0 # last unique point

        reg_verts_offs = dict()

        vertex_index_last = 0

        while nlfile.tell() < mesh_end_offset:
            face_type = nlfile.read(0x4)
            culling = (((int.from_bytes(face_type, "little")) >> 0) & 3)
            if (((int.from_bytes(face_type, "little")) >> 8) & 1) == 1 and m not in m_env:
                m_env.append(m)

            if debug:
                culling_dbg = ["[0] no culling / unused", "[1] no culling /* double side */",
                               "[2] backface   /* clock */", "[3] frontface  /* rclock */"]
                print('mesh:', m, 'strip:', f, 'culling_value:', culling_dbg[culling])

            if debug:
                print(face_type)
                poly_flags()  # prints all poly bit flags

            if (((int.from_bytes(face_type,
                                 "little")) >> 3) & 1) == 1:  # check face type, if bit3 flag is set to 1, it's triangles!
                all_triangles = True
            else:
                all_triangles = False

            n_face = read_uint32_buff()  # number of faces for this chunk (depending on the type it needs either one or three vertices / face)
            if all_triangles:
                n_vertex = n_face * 3
                if debug: print("triple number of vertices")
            else:
                n_vertex = n_face

            if debug: print(n_vertex)

            vertex = []
            normal = []
            texture_uv = []

            for _ in range(n_vertex):

                # Check if Type A or Type B vertex
                entry_pos = nlfile.tell()
                read_vert = int.from_bytes(nlfile.read(0x4), byteorder='little')

                # Check if the value falls within the specified range for TypeB
                if 0x5FF00000 <= read_vert <= 0x5FFFFFFF:
                    type_b = True
                    pointer_offset = read_sint32_buff()
                    entry_pos = nlfile.tell()
                    ptr_off = entry_pos+pointer_offset

                    found_index = None
                    for u_key, offs in reg_verts_offs.items():  # Loop through reg_verts_offs to find the current offset
                        if offs == ptr_off:
                            found_index = u_key
                            break
                    if debug:print('TypeB ptr:', 'vertID #:', found_index,'off:',hex(nlfile.tell()))
                    f_idx.append(found_index)

                else:
                    if debug:print('vertID #:',u,'off:', hex(entry_pos))

                    type_b = False
                    nlfile.seek(entry_pos, 0x0)
                    current_offset = nlfile.tell()
                    reg_verts_offs[u] = current_offset  # Store u as key and current_offset as value
                    f_idx.append(u)
                    u += 1
                    vertex.append(read_point3_buff())

                if not type_b:
                    if m_tex_shading == -3:  # It's TypeC vertex format, get sint8 normals and vert colors
                        type_c()
                        texture_uv.append(read_point2_buff())

                    elif m_tex_shading == -2:  # It's TypeD vertex format, bumpmap
                        type_d()
                        texture_uv.append(read_point2_buff())

                    else:
                        normal.append(read_point3_buff())
                        texture_uv.append(read_point2_buff())

            if debug:print(f_idx,'\n--------------')
            f += 1
            strip_counter = -1  # Reset start of strip

            faces_vertex.append({
                'point': vertex,
                'normal': normal,
                'texture': texture_uv
            })

            if all_triangles:
                for j in range(n_face):
                    i = vertex_index_last + j * 3
                    if culling == 2: # clockwise
                        x = f_idx[i + 1]
                        y = f_idx[i]
                        z = f_idx[i + 2]
                    else: # counter-clockwise
                        x = f_idx[i]
                        y = f_idx[i + 1]
                        z = f_idx[i + 2]

                    faces_index.append([x, y, z])
                    strip_counter += 1
            else:
                for j in range(n_vertex - 2):
                    i = vertex_index_last + j

                    if (strip_counter % 2 == 1):
                        if culling == 2:  # clockwise
                            x = f_idx[i + 1]
                            y = f_idx[i]
                            z = f_idx[i + 2]
                        else:   # counter-clockwise
                            x = f_idx[i]
                            y = f_idx[i + 1]
                            z = f_idx[i + 2]

                    else:
                        if culling == 2:  # clockwise
                            x = f_idx[i]
                            y = f_idx[i + 1]
                            z = f_idx[i + 2]
                        else:   # counter-clockwise
                            x = f_idx[i + 1]
                            y = f_idx[i]
                            z = f_idx[i + 2]

                    faces_index.append([x, y, z])
                    strip_counter += 1

            vertex_index_last += n_vertex

            if debug: print("-----")

        if culling == 0 or culling == 1:
            backface_flag = False
            if debug:print('backface: disabled (double-side')
        else:
            backface_flag = True
            if debug:print('backface: enabled(front or back)')

        if debug: print("number of faces found:", f)
        m_backface.append(backface_flag)

        meshes.append({
            'face_vertex': faces_vertex,
            'face_index': faces_index
        })

        mesh_faces.append(faces_index)
        mesh_vertcol.append (vert_col)
        m += 1

    # reorganize vertices into one array
    mesh_vertices = list()
    mesh_uvs = list()
    for mesh in meshes:
        points = list()
        textures = list()

        for face in mesh['face_vertex']:
            for point in face['point']:

                updatedPoint_Y = point[yVal]
                updatedPoint_Z = point[zVal]
                if NegScale_X:
                    # Trying to apply neg X scale: [i]
                    updatedPoint_X = point[xVal] * -1.0
                else:
                    updatedPoint_X = point[xVal]
                # swap Y and Z axis
                if orientation == 'X_UP':
                    points.append(Vector((updatedPoint_Y, updatedPoint_X, updatedPoint_Z)))
                elif orientation == 'Y_UP':
                    points.append(Vector((updatedPoint_X, updatedPoint_Y, updatedPoint_Z)))
                elif orientation == 'Z_UP':
                    points.append(Vector((updatedPoint_X, updatedPoint_Z, updatedPoint_Y)))
                else:
                    print("Something wrong")

            for texture in face['texture']:
                textures.append(Vector(texture))

        mesh_vertices.append(points)
        mesh_uvs.append(textures)
        #print(f"vertex_color list: {vert_col}")

    if debug: print("number of meshes found:", m)
    # print(meshes[0]['face_vertex'][0]['point'][1])
    # print(mesh_vertices)
    if debug: print(faces_index)
    # print(mesh_uvs)
    # print(mesh_colors)

    #### data structure
    # meshes[index][face_vertex|face_index]
    # meshes[index][face_vertex][index][point|normal|texture][index][xVal|yVal|zVal]
    # meshes[index][face_index][index][vertex_selection]
    #
    # mesh_vertices[mesh_index][vertex_index][xVal|yVal|zVal]
    # mesh_uvs[mesh_index][uv_index][xVal|yVal]
    # mesh_faces[mesh_index][face_index][0|1|2]
    ####


    return mesh_vertices, mesh_uvs, mesh_faces, meshes, mesh_colors,mesh_offcolors,mesh_vertcol, m_headr_grps, gflag_headers,m_backface,m_env,m_centroid


########################
# blender specific code
########################

def cleanup():
    # Deselect all objects
    bpy.ops.object.select_all(action='DESELECT')

    # Delete all objects
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    # Remove all materials
    for material in list(bpy.data.materials):
        # If no users, remove the material
        if material.users == 0:
            bpy.data.materials.remove(material)

    # Remove all collections
    for collection in bpy.data.collections:
        if len(collection.objects) == 0:
            bpy.data.collections.remove(collection)

    # Remove unused meshes
    for mesh in bpy.data.meshes:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)

    # Remove unused images
    for image in bpy.data.images:
        if image.users == 0:
            bpy.data.images.remove(image)


def redraw():
    for area in bpy.context.screen.areas:
        if area.type in ['IMAGE_EDITOR', 'VIEW_3D']:
            area.tag_redraw()

def find_existing_material(naomi_params_id):
    for mat in bpy.data.materials:
        if mat.get('naomi_params_id') == str(naomi_params_id):
            return mat
    return None

def data2blender(mesh_vertex: list, mesh_uvs: list, faces: list, meshes: list, meshColors: list, meshOffColors:list,vertexColors:list, mesh_headers: list,
                 meshBackface: list,mesh_Centroid: list,parent_col: bpy.types.Collection, scale: float, p_filepath: str, mesh_Env:list, debug=False):

    if debug: print("meshes:", len(meshes))


    for i, mesh in enumerate(meshes):

        # Create new mesh
        new_mesh = bpy.data.meshes.new(name=f"mesh_{i}")
        new_mesh.uv_layers.new(do_init=True)
        new_mesh.from_pydata(mesh_vertex[i], list(), faces[i])
        #new_mesh.validate(verbose=True)

        # Create UV
        for p, polygon in enumerate(new_mesh.polygons):
            for l, index in enumerate(polygon.loop_indices):
                new_mesh.uv_layers[0].data[index].uv.x = mesh_uvs[i][faces[i][p][l]][xVal]
                new_mesh.uv_layers[0].data[index].uv.y = 1 - mesh_uvs[i][faces[i][p][l]][yVal]

        # Create Vertex Colors layer
        if vertexColors[i]:
            # Create a new vertex colors layer
            color_layer = new_mesh.vertex_colors.new(name=f"VCol_mesh_{i}")

            # Assign vertex colors to the new layer
            for p, polygon in enumerate(new_mesh.polygons):
                for l, index in enumerate(polygon.loop_indices):
                    vertex_color = vertexColors[i][faces[i][p][l]]
                    color_layer.data[index].color = vertex_color

        new_object = bpy.data.objects.new(f"object_{i}", new_mesh)
        new_object.scale = [scale] * 3

        # ---------------
        # Naomi Parameters
        # ----------------
        # Mesh header bound radius
        new_object.naomi_param.centroid_x = mesh_Centroid[i][0]
        new_object.naomi_param.centroid_y = mesh_Centroid[i][1]
        new_object.naomi_param.centroid_z = mesh_Centroid[i][2]
        new_object.naomi_param.bound_radius = mesh_Centroid[i][3]

        # Mesh header params
        new_object.naomi_param.paramType = str(mesh_headers[i][0][0])
        new_object.naomi_param.endOfStrip = str(mesh_headers[i][0][1])
        new_object.naomi_param.listType = str(mesh_headers[i][0][2])
        new_object.naomi_param.grpEn = str(mesh_headers[i][0][3])
        new_object.naomi_param.stripLen = str(mesh_headers[i][0][4])
        new_object.naomi_param.usrClip = str(mesh_headers[i][0][5])
        new_object.naomi_param.shadow = str(mesh_headers[i][0][6])
        new_object.naomi_param.volume = str(mesh_headers[i][0][7])
        new_object.naomi_param.colType = str(mesh_headers[i][0][8])
        new_object.naomi_param.textureUsage = str(mesh_headers[i][0][9])
        new_object.naomi_param.offsColorUsage = str(mesh_headers[i][0][10])
        new_object.naomi_param.gouraudShdUsage = str(mesh_headers[i][0][11])
        new_object.naomi_param.uvDataSize = str(mesh_headers[i][0][12])

        # Mesh header ISP params
        new_object.naomi_isp_tsp.depthCompare = str(mesh_headers[i][1][0])
        new_object.naomi_isp_tsp.culling = str(mesh_headers[i][1][1])
        new_object.naomi_isp_tsp.zWrite = str(mesh_headers[i][1][2])
        new_object.naomi_isp_tsp.textureUsage = str(mesh_headers[i][1][3])
        new_object.naomi_isp_tsp.offsColorUsage = str(mesh_headers[i][1][4])
        new_object.naomi_isp_tsp.gouraudShdUsage = str(mesh_headers[i][1][5])
        new_object.naomi_isp_tsp.uvDataSize = str(mesh_headers[i][1][6])
        new_object.naomi_isp_tsp.cacheBypass = str(mesh_headers[i][1][7])
        new_object.naomi_isp_tsp.dCalcCtrl = str(mesh_headers[i][1][8])

        # Mesh header TSP params
        new_object.naomi_tsp.srcAlpha = str(mesh_headers[i][2][0])
        new_object.naomi_tsp.dstAlpha = str(mesh_headers[i][2][1])
        new_object.naomi_tsp.srcSelect = str(mesh_headers[i][2][2])
        new_object.naomi_tsp.dstSelect = str(mesh_headers[i][2][3])
        new_object.naomi_tsp.fogOp = str(mesh_headers[i][2][4])
        new_object.naomi_tsp.colorClamp = str(mesh_headers[i][2][5])
        new_object.naomi_tsp.alphaOp = str(mesh_headers[i][2][6])
        new_object.naomi_tsp.alphaTexOp = str(mesh_headers[i][2][7])
        new_object.naomi_tsp.uvFlip = str(mesh_headers[i][2][8])
        new_object.naomi_tsp.uvClamp = str(mesh_headers[i][2][9])
        new_object.naomi_tsp.filter = str(mesh_headers[i][2][10])
        new_object.naomi_tsp.supSample = str(mesh_headers[i][2][11])
        new_object.naomi_tsp.mipmapDAdj = str(mesh_headers[i][2][12])
        new_object.naomi_tsp.texShading = str(mesh_headers[i][2][13])
        new_object.naomi_tsp.texUSize = str(mesh_headers[i][2][14])
        new_object.naomi_tsp.texVSize = str(mesh_headers[i][2][15])

        # Mesh header Texture Control params
        new_object.naomi_texCtrl.mipMapped = mesh_headers[i][3][0]
        new_object.naomi_texCtrl.vqCompressed = mesh_headers[i][3][1]
        new_object.naomi_texCtrl.pixelFormat = str(mesh_headers[i][3][2])
        new_object.naomi_texCtrl.scanOrder = str(mesh_headers[i][3][3])
        new_object.naomi_texCtrl.texCtrlUstride = str(mesh_headers[i][3][4])

        # Mesh header Shading params
        new_object.naomi_param.m_tex_shading = mesh_headers[i][5]
        new_object.naomi_param.spec_int = mesh_headers[i][5]
        new_object.naomi_param.mh_texID = mesh_headers[i][4]
        new_object.naomi_param.meshColor = meshColors[i]
        new_object.naomi_param.meshOffsetColor = meshOffColors[i]
        new_object.naomi_param.m_shad_type = '0' if mesh_headers[i][5] >= 0 else str(mesh_headers[i][5])

        # Assign variables
        mh_texID = mesh_headers[i][4]
        spec_int,tex_shading = mesh_headers[i][5],mesh_headers[i][5]
        FlipUV=mesh_headers[i][2][8]
        Clamp=mesh_headers[i][2][9]
        tsp_dstAlpha = mesh_headers[i][2][1]
        tsp_srcAlpha = mesh_headers[i][2][0]
        listType =mesh_headers[i][0][2]

        if debug:print("new object", new_object.name, '; has tex ID: TexID_{0:03d}'.format(mh_texID))

        # ---------------
        # CREATE MATERIAL
        # ---------------

        naomi_params_id = (
            str(mesh_headers[i]),
            str(meshColors[i]),
            str(meshOffColors[i]),
            os.path.normpath(f"{os.path.join(os.path.dirname(p_filepath), 'Textures',f'TexID_{mh_texID:03d}')}")
        )

        if debug:print(naomi_params_id)

        # Check if material with same naomi_params_id exists
        existing_material = find_existing_material(str(naomi_params_id))

        # if same and Vertex Colors not used
        if existing_material and vertexColors[i] == []:
            if debug:print('same!')
            new_mat = existing_material
        else:
            # add viewport color to object
            new_mat = bpy.data.materials.new(f"Naomi_Mat")
            new_mat.diffuse_color = meshColors[i]
            new_mat['naomi_params_id'] = str(naomi_params_id)

            # Ensure the material has a node tree
            if new_mat.use_nodes is False:
                new_mat.use_nodes = True

            material_node_tree = new_mat.node_tree

            # Disable backface culling for double-sided mesh
            new_mat.use_backface_culling = meshBackface[i]

            color_input = new_mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color']
            alpha_input = new_mat.node_tree.nodes.get('Principled BSDF').inputs['Alpha']
            coloroff_input = new_mat.node_tree.nodes.get('Principled BSDF').inputs[
                'Specular Tint']  # Mesh Offset Colors?
            specular_input = new_mat.node_tree.nodes.get('Principled BSDF').inputs[
                'Specular Tint']  # Specular intensity?
            color_input.default_value = meshColors[i]
            alpha_input.default_value = meshColors[i][3]
            coloroff_input.default_value = meshOffColors[i]
            specular_input.default_value = (255, 255, 255, 255)
            new_mat.node_tree.nodes.get('Principled BSDF').inputs[
                'IOR'].default_value = 1.0
            texture_node = None
            vertex_color_node = None

            # Setup Alpha Blend of material
            if listType in (2, 4):
                if tex_shading == -2:  # Bump
                    new_mat.blend_method = "BLEND"
                elif tsp_dstAlpha == 1 or (
                                    tsp_srcAlpha == 1 and tsp_dstAlpha == 4):
                    new_mat.blend_method = "BLEND"
                else:
                    new_mat.blend_method = "CLIP"
            else:
                new_mat.blend_method = "OPAQUE"

            # Connect the texture node to the desired input node (e.g., Principled BSDF)
            input_node = material_node_tree.nodes.get('Principled BSDF')

            # Create Vertex Colors Layer
            if tex_shading == -3:
                # Create a Vertex Color Attribute node
                vertex_color_node = material_node_tree.nodes.new('ShaderNodeVertexColor')
                vertex_color_node.layer_name = f"VCol_mesh_{i}"

            if debug: print("vertex colors:", vertexColors[i])

            if mh_texID >= 0:

                # Generate the texture file name
                texFileName = f'TexID_{mh_texID:03d}'
                texDir = os.path.join(os.path.dirname(p_filepath), 'Textures')
                textureFileFormats = ('png', 'bmp')

                # Check if a .PVR file exists
                if os.path.exists(os.path.normpath(f"{os.path.join(texDir, texFileName)}.PVR")):

                    # Check if .bmp or .png files exist
                    bmp_path = os.path.join(texDir, f"{texFileName}.bmp")
                    png_path = os.path.join(texDir, f"{texFileName}.png")

                    if not os.path.exists(bmp_path) and not os.path.exists(png_path):
                        pvrdecode([os.path.normpath(f"{os.path.join(texDir, texFileName)}.PVR")], 'bmp', texDir,
                                  '')

                # Check if texture file uses one of the specified formats
                for fmt in textureFileFormats:
                    potential_tex_path = os.path.normpath(f"{os.path.join(texDir, texFileName)}.{fmt}")
                    if os.path.exists(potential_tex_path):
                        if debug:print(f"Texture file found: {potential_tex_path}")

                    # If Texture file exists
                    if os.path.exists(potential_tex_path):
                        texPath = potential_tex_path

                        # Check if the texture is already loaded
                        texture_loaded = False
                        for image in bpy.data.images:
                            if texPath in image.filepath:
                                if debug:print(f"Image already loaded: {texPath}")
                                new_texture = image
                                texture_loaded = True
                                break

                        # If texture is not already loaded, load it
                        if not texture_loaded:
                            new_texture = bpy.data.images.load(texPath)
                            if debug:print(f"New Image loaded: {texPath}")

                        # --------
                        # Texture
                        # --------

                        if i not in mesh_Env:
                            texture_node = material_node_tree.nodes.new('ShaderNodeTexImage')
                        # Env mapping
                        else:
                            texture_node = material_node_tree.nodes.new('ShaderNodeTexEnvironment')

                        texture_node.image = new_texture

                        # Connect the texture node to the desired input node (Principled BSDF)
                        input_node = material_node_tree.nodes.get('Principled BSDF')

                        if listType in (2, 4):
                            texture_node.image.alpha_mode = "CHANNEL_PACKED"
                            if new_object.naomi_tsp.alphaTexOp == '0': # Use texture alpha
                                material_node_tree.links.new(texture_node.outputs['Alpha'], input_node.inputs['Alpha'])
                        else:
                            texture_node.image.alpha_mode = "CHANNEL_PACKED"


                        # Env map texture node does not support extend method
                        if i not in mesh_Env:
                            # ----------------------
                            # Texture Flip / Tiling
                            # -----------------------
                            # FlipUV = U/V Flip [0:No Flip,  1:Flip Y, 2:Flip X, 3:Flip XY)
                            # Clamp = Clamp    [0:No Clamp, 1:X,      2:Y,      3:XY)

                            if Clamp == 0:
                                texture_node.extension = "REPEAT"
                            else:
                                texture_node.extension = "EXTEND"

                            if FlipUV == 0 and Clamp == 0:  # NoFlip,NoClamp //Group 0
                                pass

                            elif Clamp == 3:  # ClampXY //Group 8
                                pass

                            else:
                                # Create a UV Map node
                                uv_node = material_node_tree.nodes.new('ShaderNodeUVMap')

                                # Create a Separate XYZ node
                                separate_xyz_node = material_node_tree.nodes.new('ShaderNodeSeparateXYZ')

                                # Link the UV output of the UV Map node to the Vector input of the Separate XYZ node
                                material_node_tree.links.new(uv_node.outputs['UV'], separate_xyz_node.inputs['Vector'])

                                # Create a Combine XYZ node
                                combine_xyz_node = material_node_tree.nodes.new('ShaderNodeCombineXYZ')

                                # Create a Math node
                                math_node = material_node_tree.nodes.new('ShaderNodeMath')

                                if FlipUV == 1 and Clamp == 0:  # FlipY, NoClamp // Group 1

                                    # Math node set to 'PingPong'
                                    math_node.operation = 'PINGPONG'

                                    # Link the Separate XYZ node outputs to the Combine XYZ node inputs
                                    material_node_tree.links.new(separate_xyz_node.outputs['X'],
                                                                 combine_xyz_node.inputs['X'])
                                    material_node_tree.links.new(separate_xyz_node.outputs['Y'], math_node.inputs[0])
                                    material_node_tree.links.new(math_node.outputs[0], combine_xyz_node.inputs['Y'])


                                elif FlipUV == 2 and Clamp == 0:  # FlipX, NoClamp // Group 2

                                    # Math node set to 'PingPong'
                                    math_node.operation = 'PINGPONG'

                                    # Link the Separate XYZ node outputs to the Combine XYZ node inputs
                                    material_node_tree.links.new(separate_xyz_node.outputs['Y'],
                                                                 combine_xyz_node.inputs['Y'])
                                    material_node_tree.links.new(separate_xyz_node.outputs['X'], math_node.inputs[0])
                                    material_node_tree.links.new(math_node.outputs[0], combine_xyz_node.inputs['X'])


                                elif FlipUV == 3 and Clamp == 0:  # FlipXY, NoClamp // Group 3

                                    # Math node set to 'PingPong'
                                    math_node.operation = 'PINGPONG'

                                    # Math node set to 'PingPong2'
                                    math_node2 = material_node_tree.nodes.new('ShaderNodeMath')
                                    math_node2.operation = 'PINGPONG'
                                    math_node2.inputs[1].default_value = 1.0

                                    # Link the Separate XYZ node outputs to the Combine XYZ node inputs
                                    material_node_tree.links.new(separate_xyz_node.outputs['Y'], math_node2.inputs[0])
                                    material_node_tree.links.new(separate_xyz_node.outputs['X'], math_node.inputs[0])
                                    material_node_tree.links.new(math_node2.outputs[0], combine_xyz_node.inputs['Y'])
                                    material_node_tree.links.new(math_node.outputs[0], combine_xyz_node.inputs['X'])

                                elif (FlipUV == 0 and Clamp == 1) or (
                                        FlipUV == 1 and Clamp == 1):  # // NoFlip-FlipY ClampY Group 4

                                    # Math node set to 'WRAP'
                                    math_node.operation = 'WRAP'
                                    math_node.inputs[2].default_value = 0.0
                                    texture_node.interpolation = "Cubic"  # Get around Blender 3.4.1 bug "Linear+Wrap+Extend"

                                    # Link the Separate XYZ node outputs to the Combine XYZ node inputs
                                    material_node_tree.links.new(separate_xyz_node.outputs['Y'],
                                                                 combine_xyz_node.inputs['Y'])
                                    material_node_tree.links.new(separate_xyz_node.outputs['X'], math_node.inputs[0])
                                    material_node_tree.links.new(math_node.outputs[0], combine_xyz_node.inputs['X'])


                                elif (FlipUV == 0 and Clamp == 2) or (
                                        FlipUV == 2 and Clamp == 2):  # // NoFlip-FlipX ClampX Group 5

                                    # Math node set to 'WRAP'
                                    math_node.operation = 'WRAP'
                                    math_node.inputs[2].default_value = 0.0
                                    texture_node.interpolation = "Cubic"  # Get around Blender 3.4.1 bug "Linear+Wrap+Extend"

                                    # Link the Separate XYZ node outputs to the Combine XYZ node inputs
                                    material_node_tree.links.new(separate_xyz_node.outputs['X'],
                                                                 combine_xyz_node.inputs['X'])
                                    material_node_tree.links.new(separate_xyz_node.outputs['Y'], math_node.inputs[0])
                                    material_node_tree.links.new(math_node.outputs[0], combine_xyz_node.inputs['Y'])


                                elif (FlipUV == 1 and Clamp == 2) or (
                                        FlipUV == 3 and Clamp == 2):  # // FlipY-FlipXY ClampX Group 6

                                    # Math node set to 'PINGPONG'
                                    math_node.operation = 'PINGPONG'

                                    # Link the Separate XYZ node outputs to the Combine XYZ node inputs
                                    material_node_tree.links.new(separate_xyz_node.outputs['X'],
                                                                 combine_xyz_node.inputs['X'])
                                    material_node_tree.links.new(separate_xyz_node.outputs['Y'], math_node.inputs[0])
                                    material_node_tree.links.new(math_node.outputs[0], combine_xyz_node.inputs['Y'])


                                elif (FlipUV == 2 and Clamp == 1) or (
                                        FlipUV == 3 and Clamp == 1):  # // FlipX-FlipXY ClampY Group 7

                                    # Math node set to 'PINGPONG'
                                    math_node.operation = 'PINGPONG'

                                    # Link the Separate XYZ node outputs to the Combine XYZ node inputs
                                    material_node_tree.links.new(separate_xyz_node.outputs['Y'],
                                                                 combine_xyz_node.inputs['Y'])
                                    material_node_tree.links.new(separate_xyz_node.outputs['X'], math_node.inputs[0])
                                    material_node_tree.links.new(math_node.outputs[0], combine_xyz_node.inputs['X'])

                                math_node.inputs[1].default_value = 1.0
                                material_node_tree.links.new(combine_xyz_node.outputs['Vector'],
                                                             texture_node.inputs['Vector'])

                        # If Vertex Colors
                        if tex_shading == -3:

                            # Create a Mix Color node
                            mix_color_node = material_node_tree.nodes.new('ShaderNodeMixRGB')

                            if tsp_dstAlpha == 1 or (
                                    tsp_srcAlpha == 1 and tsp_dstAlpha == 4):  # DST ALPHA = 1 or SRCA = 1 and DSTA = SA
                                mix_color_node.blend_type = 'LINEAR_LIGHT'
                                mix_color_node.use_clamp = True

                                # Create a Shader Node for Transparent BSDF
                                DST_Alpha_node = material_node_tree.nodes.new('ShaderNodeBsdfTransparent')
                                DST_Alpha_node.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)

                                # Create a Shader Add node
                                shader_add_node = material_node_tree.nodes.new('ShaderNodeAddShader')

                                # Connect Transparent BSDF to Shader Add node
                                material_node_tree.links.new(DST_Alpha_node.outputs['BSDF'], shader_add_node.inputs[0])

                                # Connect Principled BSFD node to Shader Add node
                                material_node_tree.links.new(input_node.outputs['BSDF'], shader_add_node.inputs[1])

                                # Connect Shader Add node to Surface Material Output
                                material_node_tree.links.new(shader_add_node.outputs['Shader'],
                                                             material_node_tree.nodes['Material Output'].inputs[
                                                                 'Surface'])

                            else:
                                mix_color_node.blend_type = 'MULTIPLY'

                            mix_color_node.inputs[0].default_value = 1.0
                            mix_color_node.use_alpha = False

                            # Connect the Vertex Attribute node to Mix Color node A input
                            material_node_tree.links.new(vertex_color_node.outputs['Color'], mix_color_node.inputs[1])

                            # Connect the Texture node to Mix Color node B input
                            material_node_tree.links.new(texture_node.outputs['Color'], mix_color_node.inputs[2])

                            # Connect the Mix Color's Result output node to Principled BSDF Base Color input node
                            material_node_tree.links.new(mix_color_node.outputs['Color'],
                                                         input_node.inputs['Base Color'])

                        # Constant mode (Flat shading)
                        elif tex_shading == -1:

                            # Transmission intensity i.e. for light sources
                            material_node_tree.links.new(texture_node.outputs['Color'],
                                                         input_node.inputs['Emission Color'])
                            material_node_tree.links.new(texture_node.outputs['Color'], input_node.inputs['Base Color'])
                            new_mat.node_tree.nodes.get('Principled BSDF').inputs[27].default_value = 1.0
                            new_mat.node_tree.nodes.get('Principled BSDF').inputs[2].default_value = 1.0 # Roughness
                            new_mat.node_tree.nodes.get('Principled BSDF').inputs[17].default_value = 1.0  # Transmission Weight

                            # No Vertex Colors but special blending
                            if tsp_dstAlpha == 1 or (
                                    tsp_srcAlpha == 1 and tsp_dstAlpha == 4):  # DST ALPHA = 1 or SRCA = 1 and DSTA = SA

                                # Create a Shader Node for Transparent BSDF
                                DST_Alpha_node = material_node_tree.nodes.new('ShaderNodeBsdfTransparent')
                                DST_Alpha_node.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)

                                # Create a Shader Add node
                                shader_add_node = material_node_tree.nodes.new('ShaderNodeAddShader')

                                # Connect Transparent BSDF to Shader Add node
                                material_node_tree.links.new(DST_Alpha_node.outputs['BSDF'], shader_add_node.inputs[0])

                                # Connect Principled BSFD node to Shader Add node
                                material_node_tree.links.new(input_node.outputs['BSDF'], shader_add_node.inputs[1])

                                # Connect Shader Add node to Surface Material Output
                                material_node_tree.links.new(shader_add_node.outputs['Shader'],
                                                             material_node_tree.nodes['Material Output'].inputs[
                                                                 'Surface'])

                                material_node_tree.links.new(texture_node.outputs['Color'],
                                                             input_node.inputs['Base Color'])

                        else:

                            # No Vertex Colors but special blending
                            if tsp_dstAlpha == 1 or (
                                    tsp_srcAlpha == 1 and tsp_dstAlpha == 4):  # DST ALPHA = 1 or SRCA = 1 and DSTA = SA

                                # Create a Shader Node for Transparent BSDF
                                DST_Alpha_node = material_node_tree.nodes.new('ShaderNodeBsdfTransparent')
                                DST_Alpha_node.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)

                                # Create a Shader Add node
                                shader_add_node = material_node_tree.nodes.new('ShaderNodeAddShader')

                                # Connect Transparent BSDF to Shader Add node
                                material_node_tree.links.new(DST_Alpha_node.outputs['BSDF'], shader_add_node.inputs[0])

                                # Connect Principled BSFD node to Shader Add node
                                material_node_tree.links.new(input_node.outputs['BSDF'], shader_add_node.inputs[1])

                                # Connect Shader Add node to Surface Material Output
                                material_node_tree.links.new(shader_add_node.outputs['Shader'],
                                                             material_node_tree.nodes['Material Output'].inputs[
                                                                 'Surface'])

                                material_node_tree.links.new(texture_node.outputs['Color'],
                                                             input_node.inputs['Base Color'])

                            # ----------
                            # Bump Map
                            # ----------
                            elif tex_shading == -2:
                                normal_map_node = material_node_tree.nodes.new('ShaderNodeNormalMap')
                                shader_to_rgb_node = material_node_tree.nodes.new('ShaderNodeShaderToRGB')
                                transparent_node = material_node_tree.nodes.new('ShaderNodeBsdfTransparent')

                                material_node_tree.links.new(texture_node.outputs['Color'],
                                                             normal_map_node.inputs['Color'])
                                # Strenght to 2.0
                                normal_map_node.inputs[0].default_value = 2.0
                                material_node_tree.links.new(normal_map_node.outputs['Normal'],
                                                             input_node.inputs['Normal'])
                                material_node_tree.links.new(input_node.outputs['BSDF'], shader_to_rgb_node.inputs[0])
                                material_node_tree.links.new(shader_to_rgb_node.outputs['Color'],
                                                             transparent_node.inputs['Color'])
                                material_node_tree.links.new(transparent_node.outputs[0],
                                                             material_node_tree.nodes['Material Output'].inputs[
                                                                 'Surface'])
                                # To compensate for luminosity decrease
                                new_mat.node_tree.nodes.get('Principled BSDF').inputs[27].default_value = 0.2
                                # Normal map as non-color data
                                texture_node.image.colorspace_settings.name = 'Non-Color'

                            else:
                                material_node_tree.links.new(texture_node.outputs['Color'],
                                                             input_node.inputs['Base Color'])

            # ----------
            # No Texture
            # ----------
            elif mh_texID == -1:

                # If Vertex Colors
                if tex_shading == -3:
                    material_node_tree.links.new(vertex_color_node.outputs['Color'], input_node.inputs['Base Color'])

                # If Constant mode (Flat shading)
                elif tex_shading == -1:
                    # Set the Base Color
                    new_mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = meshColors[i]  # Default color

                    # Set the Emission Color to the same value as Base Color
                    new_mat.node_tree.nodes.get('Principled BSDF').inputs[26].default_value = meshColors[i]

                    # Set Emission Strength
                    new_mat.node_tree.nodes.get('Principled BSDF').inputs[27].default_value = 1.0  # Emission Strength
                else:
                    # Set the Base Color
                    new_mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = meshColors[i]  # Default color

            # Convert specular intensity WIP
            if spec_int > -1:
                spec_val = 1.0 if spec_int == 0 else 1.0 / spec_int if spec_int <= 5 else 1.0 / spec_int + 0.02
            else:
                spec_val = 0.0

            new_mat.roughness = spec_val
            new_mat.metallic = 0.0


        new_object.data.materials.append(new_mat)
        # link object to parent collection
        parent_col.objects.link(new_object)

    return True


########################
# MAIN functions
########################

def main_function_import_file(self, filepath: str, scaling: float, debug: bool, orientation, NegScale_X: bool):
    global model_log

    with open(filepath, "rb") as f:
        NL = f.read(-1)
        size=len(NL)

    if size >= 0xd8:
        if debug:print(filepath)
        filename = filepath.split(os.sep)[-1]
        print(filename + '\n')

        if debug:
            model_log = ''

        mesh_vertex, mesh_uvs, faces, meshes, mesh_colors, mesh_offcolors, mesh_vertcol, mesh_header_s, g_headers,m_backface,m_env,m_centroid= parse_nl(
            NL, orientation, NegScale_X,debug=debug)
        if debug:
            print(model_log)
            log_dir = os.path.join(os.path.dirname(filepath), 'Log')
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            log_file = os.path.join(log_dir, filename + '.txt')
            with open(log_file, 'w') as f:
                f.write(model_log)
            print(f'Model log saved to {log_file}')

        # create own collection for each imported file
        obj_col = bpy.data.collections.new(filename)

        obj_col.gp0.objFormat = str(g_headers[0])
        obj_col.gp1.skp1stSrcOp = g_headers[1]
        obj_col.gp1.envMap = g_headers[2]
        obj_col.gp1.pltTex = g_headers[3]
        obj_col.gp1.bumpMap = g_headers[4]

        bpy.context.scene.collection.children.link(obj_col)

        return data2blender(mesh_vertex, mesh_uvs, faces, meshes, meshColors=mesh_colors, meshOffColors=mesh_offcolors,
                            vertexColors=mesh_vertcol, mesh_headers=mesh_header_s,meshBackface=m_backface,mesh_Env=m_env,mesh_Centroid=m_centroid,
                            parent_col=obj_col, scale=scaling, p_filepath=filepath,
                            debug=debug)

def main_function_import_archive(self, filepath: str, scaling: float, debug: bool, orientation, NegScale_X: bool):
    global model_log

    def swap_endianness(data: bytes) -> bytes:
        swapped_data = bytearray(len(data))
        for i in range(0, len(data), 4):
            if i + 3 < len(data):
                swapped_data[i], swapped_data[i + 1], swapped_data[i + 2], swapped_data[i + 3] = data[i + 3], data[
                    i + 2], data[i + 1], data[i]
            else:
                # If we have a leftover chunk that's less than 4 bytes, just copy it as is
                for j in range(len(data) - i):
                    swapped_data[i + j] = data[i + j]
        return bytes(swapped_data)

    filename = filepath.split(os.sep)[-1]


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
        num_child_models = (header_length - 0x8) // 0x4

        start_offset = read_uint32_buff()

        for i in range(num_child_models):
            end_offset = read_uint32_buff()
            st_p = f.tell()

            if end_offset == 0:
                f.seek(header_length + 0x8)  # this is not always true, for some models the offset is only 0x4 (**)
                end_offset = read_uint32_buff()
                if end_offset < start_offset:  # (**)so we need to check for that
                    f.seek(header_length + 0x4)  # (**)and apply a dirty solution, I mean who the fuck cares anyway
                    end_offset = read_uint32_buff()

            f.seek(start_offset)
            if debug: print("NEW child start offset:", start_offset)
            if debug: print("NEW child end offset:", end_offset)

            p = BytesIO(f.read(end_offset - start_offset))

            # Read data from the BytesIO object, swap endianness, and write it back
            p.seek(0)
            swapped_data = swap_endianness(p.read())
            p.seek(0)
            p.write(swapped_data)
            p.seek(0)

            if debug:
                model_log = ''

            mesh_vertex, mesh_uvs, faces, meshes, mesh_colors, mesh_offcolors, mesh_vertcol, mesh_header_s, g_headers, m_backface, m_env, m_centroid = parse_nl(
                p.read(), orientation, NegScale_X, debug=debug)

            if debug:
                print(model_log)
                log_dir = os.path.join(os.path.dirname(filepath), 'Log')
                if not os.path.exists(log_dir):
                    os.makedirs(log_dir)
                log_file = os.path.join(log_dir, filename + f'_{i}.txt')
                with open(log_file, 'w') as l:
                    l.write(model_log)
                print(f'Model log saved to {log_file}')

            # create own collection for each imported file
            obj_col = bpy.data.collections.new(filename)

            obj_col.gp0.objFormat = str(g_headers[0])
            obj_col.gp1.skp1stSrcOp = g_headers[1]
            obj_col.gp1.envMap = g_headers[2]
            obj_col.gp1.pltTex = g_headers[3]
            obj_col.gp1.bumpMap = g_headers[4]

            bpy.context.scene.collection.children.link(obj_col)

            if not data2blender(mesh_vertex, mesh_uvs, faces, meshes, meshColors=mesh_colors, meshOffColors=mesh_offcolors,
                            vertexColors=mesh_vertcol, mesh_headers=mesh_header_s,meshBackface=m_backface,mesh_Env=m_env,mesh_Centroid=m_centroid,
                            parent_col=obj_col, scale=scaling, p_filepath=filepath,
                            debug=debug): return False
            f.seek(st_p)
            start_offset = end_offset

    if debug: print("NUMBER OF CHILDREN:", num_child_models)

    return True
