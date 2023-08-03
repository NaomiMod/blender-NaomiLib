import bpy

from bpy.types import Operator
from bpy.props import FloatVectorProperty
from bpy_extras.object_utils import AddObjectHelper, object_data_add

import struct
import os

from io import BytesIO
from math import radians
from mathutils import Vector

# static magic numbers and headers , updated as per official naming

magic_naomilib = [
    b'\x01\x00\x00\x00\x01\x00\x00\x00',  # Super index , always true
    b'\x00\x00\x00\x00\x01\x00\x00\x00',  # Pure beta , always true
    b'\x01\x00\x00\x00\x02\x00\x00\x00',  # Super index , skip 1st light source
    b'\x01\x00\x00\x00\x03\x00\x00\x00',  # Super index , always true , skip 1st light source
    b'\x01\x00\x00\x00\x05\x00\x00\x00',  # Super index , always true , Environment mapping
    b'\x00\x00\x00\x00\x05\x00\x00\x00',  # Pure Beta , always true , Environment mapping
]

magic_naomilib_big = [
    b'\x00\x00\x00\x01\x00\x00\x00\x01',  # Super index , always true
    b'\x00\x00\x00\x00\x00\x00\x00\x01',  # Pure beta , always true
    b'\x00\x00\x00\x01\x00\x00\x00\x02',  # Super index , skip 1st light source
    b'\x00\x00\x00\x01\x00\x00\x00\x03',  # Super index , always true , skip 1st light source
    b'\x00\x00\x00\x01\x00\x00\x00\x05',  # Super index , always true , Environment mapping
    b'\x00\x00\x00\x00\x00\x00\x00\x05',  # Pure Beta , always true , Environment mapping
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

def parse_nl(nl_bytes: bytes, orientation, NegScale_X: bool, debug=False) -> list:
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
        type_b_vertex = type_b_vertex_little
    else:
        read_uint32_buff = lambda: struct.unpack(">I", nlfile.read(0x4))[0]
        read_sint32_buff = lambda: struct.unpack(">i", nlfile.read(0x4))[0]
        read_float_buff = lambda: struct.unpack(">f", nlfile.read(0x4))[0]

        read_point3_buff = lambda: struct.unpack(">fff", nlfile.read(0xC))
        read_point2_buff = lambda: struct.unpack(">ff", nlfile.read(0x8))

        # convert all magics to big endian
        type_b_vertex = [b[::-1] for b in type_b_vertex_little]

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
        print("#---------------------------#")
        print("#    Naomi_Library_Model    #")
        print("#---------------------------#")
        print("-----Global_Flag0-----" + "\n")

        if gflag0 == b'\x00':
            print('Pure_Beta')
        elif gflag0 == b'\x01':
            print('Super_Index')
        elif gflag0 == b'\xFF':
            print('NULL')
        else:
            print("ERROR!")
        print("\n")

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

        print("-----Global_Flag1-----" + "\n")
        print("bit0     | Always true          :[" + str(gflag1_bit0) + "] " + bit_ny[(gflag1_bit0)])
        print("bit1     | Skip 1st lgt src op. :[" + str(gflag1_bit1) + "] " + bit_ny[(gflag1_bit1)])
        print("bit2     | Environment mapping  :[" + str(gflag1_bit2) + "] " + bit_ny[(gflag1_bit2)])
        print("bit3     | Palette texture      :[" + str(gflag1_bit3) + "] " + bit_ny[(gflag1_bit3)])
        print("bit4     | Bump map available   :[" + str(gflag1_bit4) + "] " + bit_ny[(gflag1_bit4)])
        print("bit5     | Reserved 1           :[" + str(gflag1_bit5) + "] " + bit_ny[(gflag1_bit5)])
        print("bit6     | Reserved 2           :[" + str(gflag1_bit6) + "] " + bit_ny[(gflag1_bit6)])
        print("bit7     | Reserved 3           :[" + str(gflag1_bit7) + "] " + bit_ny[(gflag1_bit7)])
        print("bit8     | Reserved 4           :[" + str(gflag1_bit8) + "] " + bit_ny[(gflag1_bit8)])

    # Model Header Object Centroid: x,y,z,bounding radius
    nlfile.seek(0x8)
    obj_centr_x = read_float_buff()
    obj_centr_y = read_float_buff()
    obj_centr_z = read_float_buff()
    obj_bound_radius = read_float_buff()

    if debug:
        print("-----")
        print("obj_centroid: x = " + (str(obj_centr_x)))
        print("obj_centroid: y = " + (str(obj_centr_y)))
        print("obj_centroid: z = " + (str(obj_centr_z)))
        print("obj_bnd_radius: = " + (str(obj_bound_radius)))

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

            print("\n" + "-----------------------------")
            print(f"     Mesh {m} Header        ")
            print("-----------------------------")
            print("\n" + "-----Mesh_Param_Flags-----" + "\n")
            print("bit0     | 16/bit U/V   :[" + str(m_pflag_bit0) + "] " + bit_par0[(m_pflag_bit0)])
            print("bit1     | Gouraud      :[" + str(m_pflag_bit1) + "] " + bit_par1[(m_pflag_bit1)])
            print("bit2     | Color Offset :[" + str(m_pflag_bit2) + "] " + bit_ny[(m_pflag_bit2)])
            print("bit3     | Texture      :[" + str(m_pflag_bit3) + "] " + bit_ny[(m_pflag_bit3)])
            print("bit4-5   | Color Type   :[" + str(m_pflag_bit4_5) + "] " + bit_par4_5[(m_pflag_bit4_5)])
            print("bit6     | Use Volume   :[" + str(m_pflag_bit6) + "] " + bit_ny[(m_pflag_bit6)])
            print("bit7     | Use Shadow   :[" + str(m_pflag_bit7) + "] " + bit_ny[(m_pflag_bit7)])
            print("bit4-5   | List Type    :[" + str(m_pflag_bit24_26) + "] " + bit_par24_26[(m_pflag_bit24_26)])
            print("bit29-31 | Para Type    :[" + str(m_pflag_bit29_31) + "] " + bit_par29_31[(m_pflag_bit29_31)])

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

            print("\n" + "-----Mesh_ISP_TSP-----" + "\n")
            print("bit20    | DcalcCtrl        :[" + str(m_isptspflag_bit20) + "] " + bit_par20[(m_isptspflag_bit20)])
            print("bit21    | CacheBypass      :[" + str(m_isptspflag_bit21) + "] " + bit_ny[(m_isptspflag_bit21)])
            print("bit22    | 16bit_UV2        :[" + str(m_isptspflag_bit22) + "] " + bit_par22[(m_isptspflag_bit22)])
            print("bit23    | Gouraud2         :[" + str(m_isptspflag_bit23) + "] " + bit_par23[(m_isptspflag_bit23)])
            print("bit24    | Offset2          :[" + str(m_isptspflag_bit24) + "] " + bit_ny[(m_isptspflag_bit24)])
            print("bit25    | Texture2         :[" + str(m_isptspflag_bit25) + "] " + bit_ny[(m_isptspflag_bit25)])
            print("bit26    | ZWriteDisable    :[" + str(m_isptspflag_bit26) + "] " + bit_ny[(m_isptspflag_bit26)])
            print("bit27-28 | CullingMode      :[" + str(m_isptspflag_bit27_28) + "] " + bit_par27_28[
                (m_isptspflag_bit27_28)])
            print("bit29-31 | DepthCompareMode :[" + str(m_isptspflag_bit29_31) + "] " + bit_par29_31[
                (m_isptspflag_bit29_31)])

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

            print("\n" + "-----Mesh_TSP-----" + "\n")
            print("bit0-2    | Texture V Size (Height) :[" + str(m_tspflag_bit0_2) + "] " + bit_par_px_size[
                (m_tspflag_bit0_2)])
            print("bit3-5    | Texture U Size (Width)  :[" + str(m_tspflag_bit3_5) + "] " + bit_par_px_size[
                (m_tspflag_bit3_5)])
            print("bit6-7    | Texture / Shading       :[" + str(m_tspflag_bit6_7) + "] " + bit_par6_7[
                (m_tspflag_bit6_7)])
            print("bit8-11   | Mipmap D Adjust         :[" + str(m_tspflag_bit8_11) + "] " + bit_par8_11[
                (m_tspflag_bit8_11)])
            print("bit12     | Super Sampling          :[" + str(m_tspflag_bit12) + "] " + bit_ny[(m_tspflag_bit12)])
            print("bit13-14  | Filter                  :[" + str(m_tspflag_bit13_14) + "] " + bit_par13_14[
                (m_tspflag_bit13_14)])
            print("bit15-16  | Clamp UV                :[" + str(m_tspflag_bit15_16) + "] " + bit_par15_16[
                (m_tspflag_bit15_16)])
            print("bit17-18  | Flip UV                 :[" + str(m_tspflag_bit17_18) + "] " + bit_par17_18[
                (m_tspflag_bit17_18)])
            print("bit19     | Ignore Tex.Alpha        :[" + str(m_tspflag_bit19) + "] " + bit_ny[(m_tspflag_bit19)])
            print("bit20     | Use Alpha               :[" + str(m_tspflag_bit20) + "] " + bit_par20[(m_tspflag_bit20)])
            print("bit21     | Color Clamp             :[" + str(m_tspflag_bit21) + "] " + bit_par21[(m_tspflag_bit21)])
            print("bit22-23  | Fog Control             :[" + str(m_tspflag_bit22_23) + "] " + bit_par22_23[
                (m_tspflag_bit22_23)])
            print("bit24     | DST Select              :[" + str(m_tspflag_bit24) + "] " + bit_par24[(m_tspflag_bit24)])
            print("bit25     | SRC Select              :[" + str(m_tspflag_bit25) + "] " + bit_par25[(m_tspflag_bit25)])
            print("bit26-28  | DST Alpha               :[" + str(m_tspflag_bit26_28) + "] " + bit_par_src_dst[
                (m_tspflag_bit26_28)])
            print("bit29-31  | SRC Alpha               :[" + str(m_tspflag_bit29_31) + "] " + bit_par_src_dst[
                (m_tspflag_bit29_31)])

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

            print("\n" + "-----Mesh_Texture_Control_Flags-----" + "\n")
            print("bit0-24  | Texture Address   :[" + str(m_tctflag_bit0_24) + "] " + tctflag_par_bit0_24[
                (m_tctflag_bit0_24)])
            print(
                "bit25    | StrideSelect      :[" + str(m_tctflag_bit25) + "] " + tctflag_par_bit25[(m_tctflag_bit25)])
            print(
                "bit26    | Scan Order        :[" + str(m_tctflag_bit26) + "] " + tctflag_par_bit26[(m_tctflag_bit26)])
            print("bit27_29 | Pixel Format      :[" + str(m_tctflag_bit27_29) + "] " + tctflag_par_bit27_29[
                (m_tctflag_bit27_29)])
            print("bit30    | VQ Compressed     :[" + str(m_tctflag_bit30) + "] " + bit_ny[(m_tctflag_bit30)])
            print("bit31    | Mip Mapped        :[" + str(m_tctflag_bit31) + "] " + bit_ny[(m_tctflag_bit31)])

        # 5. mesh centroid x,y,z, bound radius

        m_centr_x = read_float_buff()
        m_centr_y = read_float_buff()
        m_centr_z = read_float_buff()
        m_bound_radius = read_float_buff()

        if debug:
            print("\n" + "-----Mesh_Centroid_&_Bound_Radius-----" + "\n")
            print("mesh_centroid: x = " + (str(m_centr_x)))
            print("mesh_centroid: y = " + (str(m_centr_y)))
            print("mesh_centroid: z = " + (str(m_centr_z)))
            print("mesh_bnd_radius: = " + (str(m_bound_radius)))

        # 6. texture ID

        m_texID = read_sint32_buff()

        if debug:

            if m_texID == -1:
                t_var = ("No Texture!")
            else:
                t_var = str(m_texID)

            print("\n" + "-----Mesh_Texture_ID-----" + "\n")
            print("Texture ID: " + str(t_var))

        # 7. texture shading
        global m_tex_shading,spec_int
        m_tex_shading = read_sint32_buff()
        # spec_int = m_tex_shading / 10     Original, but currently not giving accurate results
        spec_int = spec_to_float(m_tex_shading) # WIP


        if debug:

            if m_tex_shading == -3:
                t_var2 = ("Vertex Colors Mode")
            elif m_tex_shading == -2:
                t_var2 = ("Constant Mode")
            elif m_tex_shading == 0:
                t_var2 = ("Lambert Mode")
            else:
                t_var2 = (f"Specular Intensity: {spec_int}")

            print("\n" + "-----Mesh_Texture_Shading-----" + "\n")
            print(f"[{m_tex_shading}] {t_var2}")

        # 8. texture ambient lighting

        m_tex_amb = read_float_buff()

        if debug:
            print(f"Texture Ambient Light: {m_tex_amb}")

        # 9. base color ARGB

        m_col_base_A = read_float_buff()
        m_col_base_R = read_float_buff()
        m_col_base_G = read_float_buff()
        m_col_base_B = read_float_buff()
        mesh_colors.append((m_col_base_R, m_col_base_G, m_col_base_B, m_col_base_A))    # Blender surface color is RGBA

        if debug:
            print("\n" + "-----Mesh_Base_Colors_ARGB-----" + "\n")
            print(f"Alpha: {m_col_base_A}")
            print(f"Red  : {m_col_base_R}")
            print(f"Green: {m_col_base_G}")
            print(f"Blue : {m_col_base_B}")

        # 10. offset color ARGB

        m_col_offs_A = read_float_buff()
        m_col_offs_R = read_float_buff()
        m_col_offs_G = read_float_buff()
        m_col_offs_B = read_float_buff()

        if debug:
            print("\n" + "-----Mesh_Offset_Colors_ARGB-----" + "\n")
            print(f"Alpha: {m_col_offs_A}")
            print(f"Red  : {m_col_offs_R}")
            print(f"Green: {m_col_offs_G}")
            print(f"Blue : {m_col_offs_B}")

        # 11. mesh size

        mesh_end_offset = read_uint32_buff()

        if debug:
            print("\n" + "-----Mesh_Size-----" + "\n")
            print(f"Mesh Data Size: {hex(mesh_end_offset)}")

        m_Headers = (l_Parameter_Header, l_ISP_TSP_Header, l_TSP_Header, l_texCtrl_Header, m_texID)
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

        vtx_col1_A = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col1_R = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col1_G = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col1_B = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col2_A = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col2_R = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col2_G = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))
        vtx_col2_B = col_hex_to_float(int.from_bytes(nlfile.read(0x1), "little"))

        normal.append((norm_sint8_x, norm_sint8_y, norm_sint8_z))
        vert_col.append((vtx_col1_R, vtx_col1_G, vtx_col1_B, vtx_col2_A))

        if debug: print(
            f"(normals: x,y,z: {normal}\nvtx_col1: ARGB:{vtx_col1_A} {vtx_col1_R} {vtx_col1_G} {vtx_col1_B}\n"
            f"vtx_col2: ARGB:{vtx_col2_A} {vtx_col2_R} {vtx_col2_G} {vtx_col2_B}")



    ######################################
    #  Zocker_160 code, do not change it!       /  I love your code buddy, it's awesome, really.
    ######################################

    meshes = list()
    mesh_faces = list()
    mesh_colors = list()
    m_headr_grps = list()

    nlfile.seek(0x64)   # size of mesh
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
            m_headr_grps.append(mesh_param())      # read mesh header parameters
            nlfile.seek(-0x4, 0x1)                 # Continue to read file

            if debug: print(nlfile.tell())

            mesh_end_offset = read_uint32_buff() + nlfile.tell()

            if debug: print("MESH END offset m > 0:", mesh_end_offset)

        faces_vertex = list()
        faces_index = list()

        f = 0
        vertex_index_last = 0
        while nlfile.tell() < mesh_end_offset:
            mult = False

            face_type = nlfile.read(0x4)  # some game internal value

            if debug:
                print(face_type)
                poly_flags()  # prints all poly bit flags

            if (((int.from_bytes(face_type,"little")) >> 3) & 1) == 1:  # check face type, if bit3 flag is set to 1, it's triangles!
                mult = True
            else:
                mult = False

            n_face = read_uint32_buff()  # number of faces for this chunk (depending on the type it needs either one or three vertices / face)
            if mult:
                n_vertex = n_face * 3
                if debug: print("triple number of vertices")
            else:
                n_vertex = n_face

            if debug: print(n_vertex)
            # print()
            vertex = list()
            normal = list()
            texture_uv = list()
            vert_col = list()

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
                vertex.append(read_point3_buff())


                if m_tex_shading == -3:     # It's TypeC vertex format, get sint8 normals and vert colors
                    type_c()
                else:
                    normal.append(read_point3_buff())
                    

                texture_uv.append(read_point2_buff())

                if type_b: nlfile.seek(entry_pos, 0x0)

            # print(vertex)
            # print(normal)
            # print(texture_uv)

            # if debug: print("current position:", nlfile.tell())

            strip_counter = -1        # Reset start of strip

            faces_vertex.append({
                'point': vertex,
                'normal': normal,
                'texture': texture_uv
            })

            if mult:
                for j in range(n_face):
                    i = vertex_index_last + j * 3

                    x = i
                    y = i + 1
                    z = i + 2

                    faces_index.append([x, y, z])
                    strip_counter += 1
            else:
                for j in range(n_vertex - 2):
                    i = vertex_index_last + j

                    if (strip_counter % 2 == 1):
                        x = i
                        y = i + 1
                        z = i + 2
                    else:
                        x = i + 1
                        y = i
                        z = i + 2

                    faces_index.append([x, y, z])
                    strip_counter += 1



            f += 1
            vertex_index_last += n_vertex

            if debug: print("-----")

        # print(meshes[4]['vertex'][-1])
        if debug: print("number of faces found:", f)

        meshes.append({
            'face_vertex': faces_vertex,
            'face_index': faces_index
        })

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
        # print(f"vertex_color list: {vert_col}")

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

    return mesh_vertices, mesh_uvs, mesh_faces, meshes, mesh_colors, m_headr_grps, gflag_headers


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

def data2blender(mesh_vertex: list, mesh_uvs: list, faces: list, meshes: list, meshColors: list, mesh_headers: list,
                 parent_col: bpy.types.Collection, scale: float, p_filepath: str, debug=False):
    if debug: print("meshes:", len(meshes))

    for i, mesh in enumerate(meshes):
        # print("mesh", i, mesh['vertex'])
        # print("uv", i, mesh['texture'])
        new_mesh = bpy.data.meshes.new(name=f"mesh_{i}")
        new_mesh.uv_layers.new(do_init=True)

        # print("MESH:", mesh['face_vertex'])

        new_mesh.from_pydata(mesh_vertex[i], list(), faces[i])
        new_mesh.validate(verbose=True)

        #### add UV coords
        for p, polygon in enumerate(new_mesh.polygons):
            for l, index in enumerate(polygon.loop_indices):
                new_mesh.uv_layers[0].data[index].uv.x = mesh_uvs[i][faces[i][p][l]][xVal]
                new_mesh.uv_layers[0].data[index].uv.y = 1 - mesh_uvs[i][faces[i][p][l]][yVal]

        # create object out of mesh
        new_object = bpy.data.objects.new(f"object_{i}", new_mesh)
        new_object.scale = [scale] * 3
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

        new_object.naomi_isp_tsp.depthCompare = str(mesh_headers[i][1][0])
        new_object.naomi_isp_tsp.culling = str(mesh_headers[i][1][1])
        new_object.naomi_isp_tsp.zWrite = str(mesh_headers[i][1][2])
        new_object.naomi_isp_tsp.textureUsage = str(mesh_headers[i][1][3])
        new_object.naomi_isp_tsp.offsColorUsage = str(mesh_headers[i][1][4])
        new_object.naomi_isp_tsp.gouraudShdUsage = str(mesh_headers[i][1][5])
        new_object.naomi_isp_tsp.uvDataSize = str(mesh_headers[i][1][6])
        new_object.naomi_isp_tsp.cacheBypass = str(mesh_headers[i][1][7])
        new_object.naomi_isp_tsp.dCalcCtrl = str(mesh_headers[i][1][8])

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

        new_object.naomi_texCtrl.mipMapped = mesh_headers[i][3][0]
        new_object.naomi_texCtrl.vqCompressed = mesh_headers[i][3][1]
        new_object.naomi_texCtrl.pixelFormat = str(mesh_headers[i][3][2])
        new_object.naomi_texCtrl.scanOrder = str(mesh_headers[i][3][3])
        new_object.naomi_texCtrl.texCtrlUstride = str(mesh_headers[i][3][4])
        mh_texID = mesh_headers[i][4]

        print("new object", new_object.name, '; has tex ID: TexID_0x{0:02X}'.format(mh_texID))

        # print(texPath)
        # add viewport color to object
        new_mat = bpy.data.materials.new(f"object_{i}_mat")
        new_mat.diffuse_color = meshColors[i]
        
        # Ensure the material has a node tree
        if new_mat.use_nodes is False:
            new_mat.use_nodes = True
        if mh_texID >= 0:
            texFileName = 'TexID_0x{0:02X}'.format(mh_texID)
            texFilenameExt = texFileName + '.tga'
            filename = p_filepath.split(os.sep)[-1]
            lengthFilename = len(filename)
            texDir = p_filepath[:-lengthFilename] + 'Textures\\'
            texPath = texDir + texFilenameExt
            material_node_tree = new_mat.node_tree

            new_texture = bpy.data.textures.new(name=texFileName, type='IMAGE')
            new_texture.image = bpy.data.images.load(texPath)

            texture_node = material_node_tree.nodes.new('ShaderNodeTexImage')
            texture_node.image = new_texture.image

            # Connect the texture node to the desired input node (e.g., Principled BSDF)
            input_node = material_node_tree.nodes.get('Principled BSDF')
            material_node_tree.links.new(texture_node.outputs['Color'], input_node.inputs['Base Color'])
            material_node_tree.links.new(texture_node.outputs['Alpha'], input_node.inputs['Alpha'])
            # print(new_object.naomi_param.listType)
            if (new_object.naomi_param.listType == '0'):
                texture_node.image.alpha_mode = "NONE"
                new_mat.blend_method = "OPAQUE"
            else:
                texture_node.image.alpha_mode = "CHANNEL_PACKED"
                new_mat.blend_method = "HASHED"
        # print(f"new_mat.diffuse_color: {new_mat.diffuse_color} , mesh_colors: {meshColors}")
        new_mat.roughness = spec_int
        new_mat.metallic = 0.5

        new_object.data.materials.append(new_mat)

        # link object to parent collection
        parent_col.objects.link(new_object)
        # bpy.context.collection.objects.link(new_object)

    return True


########################
# MAIN functions
########################

def main_function_import_file(self, filepath: str, scaling: float, debug: bool, orientation, NegScale_X: bool):
    with open(filepath, "rb") as f:
        NL = f.read(-1)

    print(filepath)
    filename = filepath.split(os.sep)[-1]
    print('\n\n' + filename + '\n\n')

    mesh_vertex, mesh_uvs, faces, meshes, mesh_colors, mesh_header_s, g_headers = parse_nl(NL, orientation, NegScale_X, debug=debug)

    # create own collection for each imported file
    obj_col = bpy.data.collections.new(filename)

    obj_col.gp0.objFormat = str(g_headers[0])
    obj_col.gp1.skp1stSrcOp = g_headers[1]
    obj_col.gp1.envMap = g_headers[2]
    obj_col.gp1.pltTex = g_headers[3]
    obj_col.gp1.bumpMap = g_headers[4]

    bpy.context.scene.collection.children.link(obj_col)

    return data2blender(mesh_vertex, mesh_uvs, faces, meshes, meshColors=mesh_colors, mesh_headers=mesh_header_s,
                        parent_col=obj_col, scale=scaling, p_filepath=filepath,
                        debug=debug)


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
            mesh_vertex, mesh_uvs, faces, meshes, mesh_colors, mesh_header_s = parse_nl(
                f.read(end_offset - start_offset), debug=debug)

            sub_col = bpy.data.collections.new(f"child_{i}")
            obj_col.children.link(sub_col)

            if not data2blender(mesh_vertex, mesh_uvs, faces, meshes, meshColors=mesh_colors,
                                mesh_headers=mesh_header_s, parent_col=sub_col,
                                scale=scaling, p_filepath=filepath, debug=debug): return False
            f.seek(st_p)
            start_offset = end_offset

    if debug: print("NUMBER OF CHILDREN:", num_child_models)


    return True
