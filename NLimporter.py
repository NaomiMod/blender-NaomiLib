import bpy
import struct
import os
import zlib
from io import BytesIO
from mathutils import Vector, Matrix
from .bl_pypvr import decode as pvrdecode


xVal = 0
yVal = 1
zVal = 2

# File header (8 bytes):
#   bytes 0-3: objFormat  (0 = Pure Beta, 1 = Super Index)
#   bytes 4-7: all_global_flag  (NLmagic bitmask; bit 0 = valid-model marker)
#
# NLmagic bits: 0=valid, 1=no_light, 2=envmap, 3=palette, 4=bump

NLMAGIC_BITS   = 0x1F   # bits 0-4 only
VALID_FORMATS = {0, 1}  # Pure Beta=0, Super Index=1


def _is_valid_naomilib_magic(magic: bytes) -> bool:
    if len(magic) < 8:
        return False
    obj_fmt  = int.from_bytes(magic[0:4], 'little')
    gflag    = int.from_bytes(magic[4:8], 'little')
    if obj_fmt not in VALID_FORMATS:
        return False
    if gflag & ~NLMAGIC_BITS:
        return False
    # bit 0 must be set — flag=0 means empty/null header
    if not (gflag & 0x01):
        return False
    return True


#############################
# main parse function
#############################

def parse_nl(nl_bytes: bytes, orientation, NegScale_X: bool, debug=False) -> list:
    global model_log
    nlfile = BytesIO(nl_bytes)

    _magic = nlfile.read(0x8)
    if not _is_valid_naomilib_magic(_magic):
        raise TypeError(
            f"ERROR: This is not a supported NaomiLib file! "
            f"(header: {_magic.hex()})"
        )

    def _safe_read(n):
        data = nlfile.read(n)
        if len(data) < n:
            raise EOFError(f"Unexpected end of file at offset 0x{nlfile.tell():X} "
                           f"(needed {n}, got {len(data)} bytes)")
        return data

    read_uint32_buff = lambda: struct.unpack("<I", _safe_read(0x4))[0]
    read_sint32_buff = lambda: struct.unpack("<i", _safe_read(0x4))[0]

    # Clamp f32 denormals to ±0.0 — Naomi/SH-4 runs FTZ so denormals are zero at runtime.
    # Count hits per bit-pattern and print a summary at the end.
    _denorm_counts = {}   # bits -> count

    def _clamp_denorm(v: float) -> float:
        bits = struct.unpack('<I', struct.pack('<f', v))[0]
        if (bits >> 23) & 0xFF == 0 and bits & 0x7FFFFF != 0:
            import math as _m
            _denorm_counts[bits] = _denorm_counts.get(bits, 0) + 1
            return _m.copysign(0.0, v)
        return v

    read_float_buff  = lambda: _clamp_denorm(struct.unpack("<f", _safe_read(0x4))[0])

    def read_point3_buff():
        x, y, z = struct.unpack("<fff", _safe_read(0xC))
        return (_clamp_denorm(x), _clamp_denorm(y), _clamp_denorm(z))

    read_point2_buff = lambda: struct.unpack("<ff",  _safe_read(0x8))

    # sint8 to float, code by Zocker!
    def sint8_to_float(num: int) -> float:
        min, max = 0x7f, 0x80
        if num > 0x7f:
            num -= 0x100
            return num / max
        else:
            return num / min

    # specular to float (WIP)
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

    obj_centroid_header = list()
    obj_centroid_header.append(obj_centr_x)
    obj_centroid_header.append(obj_centr_y)
    obj_centroid_header.append(obj_centr_z)
    obj_centroid_header.append(obj_bound_radius)

    if debug:
        model_log += (
            f"-----\n"
            f"obj_centroid: x = {obj_centr_x}\nobj_centroid: y = {obj_centr_y}\n"
            f"obj_centroid: z = {obj_centr_z}\nobj_bnd_radius: = {obj_bound_radius}\n"
        )

    ###################
    # mesh parameters #
    ###################

    # mesh parameters layout:
    # [mesh_param][mesh_isp_tsp][tsp][texture_ctrl]  — 4x uint32 bitflags
    # [mesh_centroid x,y,z,bound_r]                  — 4x float
    # [Texture No][tex_shading][tex_ambient]          — sint32, sint32, float
    # [Base ARGB][Offset ARGB]                        — 4x float each
    # [mesh_size]                                     — uint32

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
            bit_par0 = ["32/bit U/V ", "16/bit U/V "]
            bit_par1 = ["Flat ", "Gouraud "]
            bit_par4_5 = ["Packed Color", "Floating Color", "Intensity Mode 1", "Intensity Mode 2"]
            bit_par24_26 = ["Opaque", "Opaque Modifier Volume", "Translucent", "Translucent Modifier Volume",
                            "Punch Through", "Reserved", "Reserved", "Reserved"]
            bit_par29_31 = ["Control Parameter End Of List", "Control Parameter User Tile Clip",
                            "Control Parameter Object List Set", "Reserved",
                            "Global Parameter Polygon or Modifier Volume", "Global Parameter Sprite",
                            "Global Parameter Reserved", "Vertex Parameter"]

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
                f"bit24-26 | List Type    :[{m_pflag_bit24_26}] {bit_par24_26[m_pflag_bit24_26]}\n"
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
            bit_par20 = ["No", "Use D Calc for small polys"]
            bit_par22 = ["32/bit U/V ", "16/bit U/V "]
            bit_par23 = ["Flat ", "Gouraud "]
            bit_par27_28 = ["No Culling", "Cull if Small", "Cull if Negative", "Cull if Positive"]
            bit_par29_31 = ["NEVER", "LESS", "EQUAL", "LESS OR EQUAL", "GREATER", "NOT_EQUAL", "GREATER OR EQUAL",
                            "ALWAYS"]

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

        # 3. mesh tsp parameters bit0-31

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
            bit_par_src_dst = ["Zero (0, 0, 0, 0)", "One (1, 1, 1, 1)", "'Other' Color (OR, OG, OB, OA)",
                               "Inverse 'Other' Color (1-OR, 1-OG, 1-OB, 1-OA)", "SRC Alpha (SA, SA, SA, SA)",
                               "Inverse SRC Alpha (1-SA, 1-SA, 1-SA, 1-SA)", "DST Alpha (DA, DA, DA, DA)",
                               "Inverse DST Alpha (1-DA, 1-DA, 1-DA, 1-DA)"]

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

        # 4. texture control bit0-31

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
            tctflag_par_bit0_24 = [" "]
            tctflag_par_bit25 = ["No", "Use Texture Control for U Stride"]
            tctflag_par_bit26 = ["Twiddled", "Non-Twiddled"]
            tctflag_par_bit27_29 = ["ARGB1555", "RGB565", "ARGB4444", "YUV422", "Bump Map",
                                    "4 BPP Palette", "8 BPP Palette", "Reserved"]

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
        m_centroid.append((m_centr_x, m_centr_y, m_centr_z, m_bound_radius))

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
        spec_int = m_tex_shading  # already the exponent index in NAOMI1 NLB format

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
            model_log += (f"Texture Ambient Light: {m_tex_amb}\n")

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

        m_Headers = (
            l_Parameter_Header, l_ISP_TSP_Header, l_TSP_Header, l_texCtrl_Header, m_texID, m_tex_shading, m_tex_amb)
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
            bit_ppar0_1 = ["clockwise", "counter-clock", "single-side (clockwise)", "double-sided (counter-clockwise)"]
            bit_ppar6 = ["No (Flat)", "Yes"]
            bit_ppar7 = ["Send global params", "Don't send global params"]
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

    # Type C vertex (m_tex_shading == -3):
    # [x,y,z], [sint8 nx,ny,nz], [0x00], [vtx_color1 BGRA8888], [vtx_color2 BGRA8888], [U], [V]
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

    # Type D vertex (m_tex_shading == -2):
    # [x,y,z], [nx,ny,nz], [bump0 nx,ny,nz], [bump1 nx,ny,nz], [U], [V]
    def type_d():

        # Bump map
        normal.append(read_point3_buff())
        nlfile.seek(nlfile.tell() + 0x18)  # WIP temporary skip bumpmap1-2 norms

    # Zocker_160 code — do not change

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

        # print(m_headr_grps[0][5])
        m_tex_shading = m_headr_grps[-1][5]
        # print(m_tex_shading)
        faces_vertex = list()
        faces_index = list()
        vert_col = list()
        vertex = list()
        normal = list()
        texture_uv = list()
        f_idx = list()
        f = 0
        u = 0  # last unique point

        reg_verts_offs = dict()

        vertex_index_last = 0

        if debug:
            model_log += (
                f"\n#---------------------------#\n"
                f"#   Naomi1 Mesh {m}           #\n"
                f"#---------------------------#\n"
                f"m_tex_shading = {m_tex_shading}\n"
            )

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
                    ptr_off = entry_pos + pointer_offset

                    found_index = None
                    for u_key, offs in reg_verts_offs.items():  # Loop through reg_verts_offs to find the current offset
                        if offs == ptr_off:
                            found_index = u_key
                            break
                    if debug: print('TypeB ptr:', 'vertID #:', found_index, 'off:', hex(nlfile.tell()))
                    f_idx.append(found_index)

                else:
                    if debug: print('vertID #:', u, 'off:', hex(entry_pos))

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
                        _uv = read_point2_buff()
                        texture_uv.append(_uv)

                    elif m_tex_shading == -2:  # It's TypeD vertex format, bumpmap
                        type_d()
                        _uv = read_point2_buff()
                        texture_uv.append(_uv)

                    else:
                        normal.append(read_point3_buff())
                        _uv = read_point2_buff()
                        texture_uv.append(_uv)

            if debug: print(f_idx, '\n--------------')
            f += 1
            strip_counter = -1  # Reset start of strip

            faces_vertex.append({
                'point': vertex,
                'normal': normal,
                'texture': texture_uv
            })

            # Debug: raw verts for this strip
            # Build a flat global coord lookup (unique verts accumulated so far)
            # used by both the raw-vert listing and the per-triangle coord output.
            # TypeB verts reference an earlier unique vert; f_idx[slot] is the
            # global unique-vert id, which indexes directly into _global_verts.
            _global_verts = []
            for _fv in faces_vertex:   # all strips including current
                _global_verts.extend(_fv['point'])

            if debug:
                _strip_idx = f - 1
                _cull_tag  = culling
                _mode_tag  = "triangles" if all_triangles else "strip"
                model_log += (
                    f"\n  ── raw_verts  (mesh={m}  strip={_strip_idx}"
                    f"  n_vertex={n_vertex}  mode={_mode_tag}"
                    f"  cull_mode={_cull_tag}) ──\n"
                )

                for _si in range(n_vertex):
                    _slot  = vertex_index_last + _si
                    _vidx  = f_idx[_slot] if _slot < len(f_idx) else None
                    if _vidx is not None and _vidx < len(_global_verts):
                        _co = _global_verts[_vidx]
                        _co_str = f"xyz=({_co[0]:>10.4f}, {_co[1]:>10.4f}, {_co[2]:>10.4f})"
                    else:
                        _co_str = "xyz=(?)"
                    _is_tb = "(TypeB ref)" if (_slot < len(f_idx) and
                                               _vidx is not None and
                                               _vidx < vertex_index_last) else ""
                    model_log += (
                        f"    [{_si:>3}]  f_idx[{_slot}]={_vidx}  {_co_str}  {_is_tb}\n"
                    )

                # Debug: strip summary
                if all_triangles:
                    model_log += (
                        f"\n  ── strip[{_strip_idx}]  {n_face} triangle(s)"
                        f"  vtx_base={vertex_index_last}  cull_mode={_cull_tag} ──\n"
                    )
                else:
                    model_log += (
                        f"\n  ── strip[{_strip_idx}]  {n_vertex} verts --> {n_vertex - 2} tri(s)"
                        f"  vtx_base={vertex_index_last}  cull_mode={_cull_tag} ──\n"
                    )

            if all_triangles:
                for j in range(n_face):
                    i = vertex_index_last + j * 3
                    if culling == 2:  # clockwise
                        x = f_idx[i + 1]
                        y = f_idx[i]
                        z = f_idx[i + 2]
                    else:  # counter-clockwise
                        x = f_idx[i]
                        y = f_idx[i + 1]
                        z = f_idx[i + 2]

                    faces_index.append([x, y, z])
                    strip_counter += 1

                    if debug:
                        _wind_reason = (
                            "triangles cull=2 --> swap    (i+1, i, i+2)"
                            if culling == 2 else
                            "triangles cull≠2 --> normal  (i, i+1, i+2)"
                        )
                        def _co_str_nl1(vidx):
                            if vidx is not None and vidx < len(_global_verts):
                                _c = _global_verts[vidx]
                                return f"({_c[0]:>9.4f}, {_c[1]:>9.4f}, {_c[2]:>9.4f})"
                            return "(?)"
                        model_log += (
                            f"    tri[{strip_counter:>3}]  j={j:<3}  [{x},{y},{z}]  {_wind_reason}\n"
                            f"           A=[{x}] xyz={_co_str_nl1(x)}\n"
                            f"           B=[{y}] xyz={_co_str_nl1(y)}\n"
                            f"           C=[{z}] xyz={_co_str_nl1(z)}\n"
                        )
            else:
                for j in range(n_vertex - 2):
                    i = vertex_index_last + j

                    if (strip_counter % 2 == 1):
                        if culling == 2:  # clockwise
                            x = f_idx[i + 1]
                            y = f_idx[i]
                            z = f_idx[i + 2]
                            _wind_reason = "strip odd  cull=2 --> swap    (i+1, i, i+2)"
                        else:  # counter-clockwise
                            x = f_idx[i]
                            y = f_idx[i + 1]
                            z = f_idx[i + 2]
                            _wind_reason = "strip odd  cull≠2 --> normal  (i, i+1, i+2)"
                    else:
                        if culling == 2:  # clockwise
                            x = f_idx[i]
                            y = f_idx[i + 1]
                            z = f_idx[i + 2]
                            _wind_reason = "strip even cull=2 --> normal  (i, i+1, i+2)"
                        else:  # counter-clockwise
                            x = f_idx[i + 1]
                            y = f_idx[i]
                            z = f_idx[i + 2]
                            _wind_reason = "strip even cull≠2 --> swap    (i+1, i, i+2)"

                    faces_index.append([x, y, z])
                    strip_counter += 1

                    if debug:
                        def _co_str_nl1(vidx):
                            if vidx is not None and vidx < len(_global_verts):
                                _c = _global_verts[vidx]
                                return f"({_c[0]:>9.4f}, {_c[1]:>9.4f}, {_c[2]:>9.4f})"
                            return "(?)"
                        model_log += (
                            f"    tri[{strip_counter:>3}]  j={j:<3}  sc={strip_counter:<3}"
                            f"  [{x},{y},{z}]  {_wind_reason}\n"
                            f"           A=[{x}] xyz={_co_str_nl1(x)}\n"
                            f"           B=[{y}] xyz={_co_str_nl1(y)}\n"
                            f"           C=[{z}] xyz={_co_str_nl1(z)}\n"
                        )

            vertex_index_last += n_vertex

            if debug: print("-----")

        if culling == 0 or culling == 1:
            backface_flag = False
            if debug: print('backface: disabled (double-side')
        else:
            backface_flag = True
            if debug: print('backface: enabled(front or back)')

        if debug:
            print("number of faces found:", f)
            model_log += f"\nNL1 mesh {m}: {f} strip(s) parsed, {len(faces_index)} triangle(s) total.\n"
        m_backface.append(backface_flag)

        meshes.append({
            'face_vertex': faces_vertex,
            'face_index': faces_index
        })

        mesh_faces.append(faces_index)
        mesh_vertcol.append(vert_col)
        m += 1

    # reorganize vertices into one array
    mesh_vertices = list()
    mesh_uvs = list()
    for mesh in meshes:
        points = list()
        textures = list()

        for face in mesh['face_vertex']:
            for point in face['point']:

                if orientation == 'X_UP':
                    # points.append(Vector((updatedPoint_Y, updatedPoint_X, updatedPoint_Z)))
                    # Swap X & Y
                    updatedPoint_X = point[yVal]
                    updatedPoint_Y = point[xVal]
                    updatedPoint_Z = point[zVal]
                elif orientation == 'Y_UP':
                    # points.append(Vector((updatedPoint_X, updatedPoint_Y, updatedPoint_Z)))
                    # No Swaps
                    updatedPoint_X = point[xVal]
                    updatedPoint_Y = point[yVal]
                    updatedPoint_Z = point[zVal]
                elif orientation == 'Z_UP':
                    # points.append(Vector((updatedPoint_X, updatedPoint_Z, updatedPoint_Y)))
                    # Swap Y & Z
                    updatedPoint_X = point[xVal]
                    updatedPoint_Y = point[zVal]
                    updatedPoint_Z = point[yVal]
                else:
                    print("Something went wrong./n [!] Doing No Swaps!")
                    # No Swaps
                    updatedPoint_X = point[xVal]
                    updatedPoint_Y = point[yVal]
                    updatedPoint_Z = point[zVal]

                if NegScale_X:
                    # FIX (Bug 2): +0.0 * -1.0 produces IEEE-754 -0.0 (0x80000000).
                    # Denormals are already clamped by _clamp_denorm inside
                    # read_point3_buff, so this multiply cannot produce 0x80000001
                    # any longer.  But it can still produce -0.0 from +0.0.
                    updatedPoint_X = updatedPoint_X * -1.0
                    if updatedPoint_X == 0.0:
                        updatedPoint_X = 0.0  # strips the negative sign bit

                points.append(Vector((updatedPoint_X, updatedPoint_Y, updatedPoint_Z)))

            for texture in face['texture']:
                textures.append(Vector(texture))

        mesh_vertices.append(points)
        mesh_uvs.append(textures)

    if debug: print("number of meshes found:", m)
    if debug: print(faces_index)

    return mesh_vertices, mesh_uvs, mesh_faces, meshes, mesh_colors, mesh_offcolors, mesh_vertcol, m_headr_grps, gflag_headers, obj_centroid_header, m_backface, m_env, m_centroid


########################
# blender specific code
########################


# NAOMI2 (NL2) binary importer
#
# Object-tag layout:
#  [  0..95]  96-byte object-tag header
#  [ 96..159] 64-byte GMP block  (params + NULL/tex/pal)
#  [160..183] 24-byte PVR header (PCW + ISP_TSP + TSP + TexCtrl × 2)
#  [184..187] MODEL_DATA_FLAGS
#  [188..191] vertex_count
#  [192..   ] vertex data: vertex_count × 24 bytes
#             flag(u32) + x(f32) + y(f32) + z(f32) + u(f32) + v(f32)
#
# Vertex flag word bits[31:24] = topology:
#   0x00=BaseTriangle0, 0x60=BaseTriangle1, 0x20=Strip, 0x40=Fan
#   0x80 OR'd for V_END (last vertex of strip)

def _is_naomi2_bin(nl_bytes: bytes) -> bool:
    """Return True if format_flag == 0x100 (NAOMI2 object-tag)."""
    if len(nl_bytes) < 8:
        return False
    fmt = int.from_bytes(nl_bytes[0:4], 'little')
    return fmt == 0x100


def parse_nl2(nl_bytes: bytes, orientation: str, NegScale_X: bool,
              debug: bool = False) -> list:
    """Parse a NAOMI2 object-tag binary (format_flag=0x100).
    Returns the same tuple as parse_nl()."""
    global model_log
    f = BytesIO(nl_bytes)

    def ru32():
        return struct.unpack_from('<I', f.read(4))[0]
    def rs32():
        return struct.unpack_from('<i', f.read(4))[0]
    def rf32():
        return struct.unpack_from('<f', f.read(4))[0]

    # Object-tag header (96 bytes)
    f.seek(0)
    format_flag  = ru32()   # 0x00000100
    global_sta   = ru32()   # global status flags (PSTA bits)
    cx, cy, cz   = rf32(), rf32(), rf32()   # bounding sphere center
    cr           = rf32()   # bounding sphere radius
    all_size     = ru32()   # total byte size
    _tag_ver     = ru32()   # tag version (0)
    poly_count   = ru32()   # total polygon count
    vtx_count    = ru32()   # total vertex count
    gmp_count    = ru32()   # GMP block count
    pvr_count    = ru32()   # PVR header count
    _res0        = ru32()
    _res1        = ru32()
    _res2        = ru32()
    _alloc       = ru32()
    opq_off      = ru32()   # offset from word[16] to opaque list start
    opq_sz       = ru32()   # opaque list byte size
    trs_off      = ru32()
    trs_sz       = ru32()
    pch_off      = ru32()
    pch_sz       = ru32()
    _res4        = ru32()
    _res5        = ru32()

    if debug:
        model_log += (
            "#---------------------------#\n"
            "#   Naomi2 Object Tag       #\n"
            "#---------------------------#\n"
            f"format_flag  = 0x{format_flag:08X}\n"
            f"global_sta   = 0x{global_sta:08X}\n"
            f"center       = ({cx:.4f}, {cy:.4f}, {cz:.4f})  r={cr:.4f}\n"
            f"all_size     = {all_size}\n"
            f"poly_count   = {poly_count}\n"
            f"vtx_count    = {vtx_count}\n"
            f"gmp_count    = {gmp_count}  pvr_count = {pvr_count}\n"
            f"opq off={opq_off} sz={opq_sz}\n"
            f"trs off={trs_off} sz={trs_sz}\n"
            f"pch off={pch_off} sz={pch_sz}\n"
        )

    obj_centroid_header = [cx, cy, cz, cr]
    # global_sta bit1 = env-map, bit4 = bump — replicate gflag_headers shape
    gflag_headers = [
        0,                          # [0] obj_fmt  (0=pure_beta-like, N/A for NL2)
        (global_sta >> 1) & 1,      # [1] skip 1st lgt src
        (global_sta >> 2) & 1,      # [2] env-map
        (global_sta >> 3) & 1,      # [3] palette tex
        (global_sta >> 4) & 1,      # [4] bump map
    ]

    HEADER_END = 96   # bytes 0..95

    # Each list segment contains GMP blocks followed by PVR+MDF+vtx_count+vertex_data chunks.
    # Offsets are self-relative: stored at byte N, points to byte N+off.
    # opq_off at byte 64, trs_off at byte 72, pch_off at byte 80
    list_segments = []
    if opq_sz > 0:
        list_segments.append((64 + opq_off, opq_sz))
    if trs_sz > 0:
        list_segments.append((72 + trs_off, trs_sz))
    if pch_sz > 0:
        list_segments.append((80 + pch_off, pch_sz))

    meshes        = []
    mesh_faces    = []
    mesh_colors   = []
    mesh_offcolors = []
    mesh_vertcol  = []
    m_headr_grps  = []
    m_centroid    = []
    m_backface    = []
    m_env         = []

    # Accumulate all strips from all list segments into a single flat list
    # of meshes (one mesh per GMP/PVR pair, which corresponds to one material
    # group in the original Blender scene).

    TOPO_BT0    = 0x00
    TOPO_BT1    = 0x60
    TOPO_STRIP  = 0x20
    TOPO_FAN    = 0x40
    TOPO_V_END  = 0x80

    for seg_abs_off, seg_sz in list_segments:
        seg_end = seg_abs_off + seg_sz
        f.seek(seg_abs_off)

        # Per-segment state — current GMP data (shared across all PVRs in this GMP)
        cur_gloss = cur_select = cur_d0 = cur_s0 = cur_d1 = cur_s1 = 0
        cur_tex_id = -1
        cur_gmp_valid = False

        while f.tell() < seg_end:
            seg_pos = f.tell()

            # Peek at next word to decide: GMP or PVR?
            if seg_pos + 4 > seg_end:
                break
            peek_bytes = nl_bytes[seg_pos:seg_pos+4]
            peek = struct.unpack_from('<I', peek_bytes)[0]

            # GMP block (64 bytes)
            if peek == 0x08000500:
                if seg_pos + 64 > seg_end:
                    break
                ru32()  # consume PCW_GMP

                cur_gloss       = ru32()
                cur_select      = ru32()
                cur_d0          = ru32()   # diffuse0
                cur_s0          = ru32()   # specular0
                cur_d1          = ru32()   # diffuse1
                cur_s1          = ru32()   # specular1
                _gmp_res        = ru32()
                # NULL block: PCW_NULL + tex_id + PCW_NULL + pal_id  × 2
                _null0      = ru32()
                cur_tex_id  = rs32()
                _null1      = ru32()
                _pal_id0    = rs32()
                _null2      = ru32()
                _tex_id1    = rs32()
                _null3      = ru32()
                _pal_id1    = rs32()
                cur_gmp_valid = True

                gloss       = cur_gloss
                select_word = cur_select
                diffuse0    = cur_d0
                specular0   = cur_s0
                tex_id0     = cur_tex_id

                if debug:
                    model_log += (
                        f"\nGMP: pcw=0x08000500  tex_id={tex_id0}"
                        f"  diffuse=0x{diffuse0:08X}  select=0x{select_word:08X}\n"
                    )
                continue   # next iteration will read the PVR

            # PVR block (must follow a GMP)
            if not cur_gmp_valid or not ((peek >> 31) & 1):
                ru32()
                continue

            if seg_pos + 32 > seg_end:
                break

            # Restore GMP locals for this PVR
            gloss       = cur_gloss
            select_word = cur_select
            diffuse0    = cur_d0
            specular0   = cur_s0
            tex_id0     = cur_tex_id

            s0 = (select_word >> 28) & 0xF
            env_flag = (select_word >> 2) & 1

            # ARGB uint32 --> (R,G,B,A) floats
            def argb_to_rgba(w):
                a = ((w >> 24) & 0xFF) / 255.0
                r = ((w >> 16) & 0xFF) / 255.0
                g = ((w >>  8) & 0xFF) / 255.0
                b = ((w      ) & 0xFF) / 255.0
                return (r, g, b, a)

            base_col   = argb_to_rgba(diffuse0)
            offset_col = argb_to_rgba(specular0)

            if f.tell() + 32 > seg_end:
                break

            pvr_pcw     = ru32()
            pvr_isp_tsp = ru32()
            pvr_tsp     = ru32()
            pvr_texctrl = ru32()
            _pvr_tsp2   = ru32()   # para1 duplicate / vol2para
            _pvr_tc2    = ru32()

            mdf             = ru32()   # MODEL_DATA_FLAGS
            strip_vtx_count = ru32()   # vertex count for this strip group

            # Build m_headr_grps entry (same 7-tuple as mesh_param())
            _pvr_lt   = (pvr_pcw >> 24) & 0x3
            _pvr_ct   = (pvr_pcw >>  4) & 0x3
            _pvr_tex  = (pvr_pcw >>  3) & 1
            _pvr_ofs  = (pvr_pcw >>  2) & 1
            _pvr_gr   = (pvr_pcw >>  1) & 1
            _pvr_16   = (pvr_pcw >>  0) & 1

            _isp_dep  = (pvr_isp_tsp >> 29) & 7
            _isp_cul  = (pvr_isp_tsp >> 27) & 3
            _isp_zw   = (pvr_isp_tsp >> 26) & 1
            _isp_tex2 = (pvr_isp_tsp >> 25) & 1
            _isp_ofs2 = (pvr_isp_tsp >> 24) & 1
            _isp_gr2  = (pvr_isp_tsp >> 23) & 1
            _isp_16b2 = (pvr_isp_tsp >> 22) & 1
            _isp_cch  = (pvr_isp_tsp >> 21) & 1
            _isp_dc   = (pvr_isp_tsp >> 20) & 1

            l_param = [4, 0, _pvr_lt, 0, 0, 0, 0, 0, _pvr_ct, _pvr_tex, _pvr_ofs, _pvr_gr, _pvr_16]
            l_isp   = [_isp_dep, _isp_cul, _isp_zw, _isp_tex2, _isp_ofs2, _isp_gr2, _isp_16b2, _isp_cch, _isp_dc]
            l_tsp   = [
                (pvr_tsp >> 29) & 7,   # SA
                (pvr_tsp >> 26) & 7,   # DA
                (pvr_tsp >> 25) & 1,   # src_select
                (pvr_tsp >> 24) & 1,   # dst_select
                (pvr_tsp >> 22) & 3,   # fog
                (pvr_tsp >> 21) & 1,   # color_clamp
                (pvr_tsp >> 20) & 1,   # use_alpha
                (pvr_tsp >> 19) & 1,   # ignore_tex_alpha
                (pvr_tsp >> 17) & 3,   # flip_uv
                (pvr_tsp >> 15) & 3,   # clamp_uv
                (pvr_tsp >> 13) & 3,   # filter_mode
                (pvr_tsp >> 12) & 1,   # super_sample
                (pvr_tsp >>  8) & 0xF, # mipmap_d_adj
                (pvr_tsp >>  6) & 3,   # tex_shading_instr
                (pvr_tsp >>  3) & 7,   # tex_size_u
                (pvr_tsp >>  0) & 7,   # tex_size_v
            ]
            l_texctrl = [
                (pvr_texctrl >> 31) & 1,          # mip_mapped
                (pvr_texctrl >> 30) & 1,          # vq_compressed
                (pvr_texctrl >> 27) & 7,          # pixel_format
                (pvr_texctrl >> 26) & 1,          # scan_order
                (pvr_texctrl >> 25) & 1,          # stride_select
                (pvr_texctrl >>  0) & 0x1FFFFFF,  # tex_address
            ]

            # select_word bits: [31:28]=s0, [27:24]=s1, [22]=b0 (bypass alpha), [21]=b1
            s0_nibble = (select_word >> 28) & 0xF
            b0_bit    = (select_word >> 22) & 1

            env_flag = (global_sta >> 2) & 1   # PSTA_USE_ENVMAP

            # PIX_BUMP_MAP = 4 — bump map pixel format in TexCtrl
            pix_fmt = l_texctrl[2]
            if pix_fmt == 4:
                m_tex_shading = -2          # bump
            elif s0_nibble == 0 and b0_bit == 1:
                m_tex_shading = -3          # vertex colour (bypass both diff + alpha)
            elif s0_nibble == 1 and b0_bit == 1:
                m_tex_shading = -1          # constant (use material colour, no lighting)
            elif s0_nibble == 1 and b0_bit == 0:
                # lambert or specular — gloss para0 distinguishes them
                g0 = gloss & 0xFF
                if g0 > 0:
                    # reverse-map raw gloss byte back to hogehoge_gloss exponent index
                    from .nlstrip import hogehoge_gloss_reverse
                    m_tex_shading = hogehoge_gloss_reverse.get(g0, g0)
                else:
                    m_tex_shading = 0       # lambert
            else:
                m_tex_shading = 0           # default lambert

            cull_mode = _isp_cul

            m_hdr = (l_param, l_isp, l_tsp, l_texctrl, tex_id0, m_tex_shading, 1.0)

            if debug:
                model_log += (
                    f"PVR: pcw=0x{pvr_pcw:08X}  list_type={_pvr_lt}"
                    f"  tex={_pvr_tex}  gouraud={_pvr_gr}  cull={cull_mode}\n"
                    f"MDF=0x{mdf:08X}  strip_vtx_count={strip_vtx_count}\n"
                )
            # MDF bit3 (UV): 1 --> 6 words/24 bytes (flag+x+y+z+u+v), 0 --> 4 words/16 bytes
            # flag_word bits[23:0] = packed normal f2i255(nx,ny,nz); bits[31:24] = topology
            # has_rgb adds 2 words (8 bytes): base_vtx_color + offset_vtx_color
            has_uv  = bool((mdf >> 3) & 1)
            has_rgb = bool((mdf >> 6) & 1)
            bytes_per_vtx = (24 if has_uv else 16) + (8 if has_rgb else 0)

            def _unpack_flag_normal(flag_word):
                def _b(byte_val):
                    signed = byte_val if byte_val < 128 else byte_val - 256
                    return signed / 128.0
                nx_ = _b( flag_word        & 0xFF)
                ny_ = _b((flag_word >>  8) & 0xFF)
                nz_ = _b((flag_word >> 16) & 0xFF)
                return (nx_, ny_, nz_)

            if f.tell() + strip_vtx_count * bytes_per_vtx > seg_end + 4:
                # Corrupt or misaligned — stop
                break

            raw_verts = []   # (x, y, z, u, v, topo_byte, base_col_rgba, normal_or_None)

            for _ in range(strip_vtx_count):
                flag_word = ru32()
                x  = rf32()
                y  = rf32()
                z  = rf32()
                if has_uv:
                    u_ = rf32()
                    v_ = rf32()   # negated by exporter (v = -pi.v)
                else:
                    u_ = 0.0
                    v_ = 0.0
                if has_rgb:
                    vtcl  = ru32()   # base colour: packed ARGB uint32
                    vtcl2 = ru32()   # offset colour: packed ARGB uint32 (consumed, not used)
                    base_col = (
                        ((vtcl >> 16) & 0xFF) / 255.0,  # R
                        ((vtcl >>  8) & 0xFF) / 255.0,  # G
                        ( vtcl        & 0xFF) / 255.0,  # B
                        ((vtcl >> 24) & 0xFF) / 255.0,  # A
                    )
                else:
                    base_col = (1.0, 1.0, 1.0, 1.0)
                packed_normal = _unpack_flag_normal(flag_word)
                topo = (flag_word >> 24) & 0xFF
                raw_verts.append((x, y, z, u_, v_, topo, base_col, packed_normal))

            if debug:
                _TOPO_NAMES = {
                    0x00: 'BT0',   0x20: 'Strip', 0x40: 'Fan',  0x60: 'BT1',
                    0x80: 'BT0|END', 0xA0: 'Strip|END', 0xC0: 'Fan|END', 0xE0: 'BT1|END',
                }
                model_log += (
                    f"\n  ── raw_verts  (mesh={len(meshes)}  strip_vtx_count={strip_vtx_count}"
                    f"  cull_mode={cull_mode}  has_uv={has_uv}  has_rgb={has_rgb}) ──\n"
                )
                for _ri, _rv in enumerate(raw_verts):
                    _tname = _TOPO_NAMES.get(_rv[5], f'0x{_rv[5]:02X}')
                    _col_str = f"  col=({_rv[6][0]:.3f},{_rv[6][1]:.3f},{_rv[6][2]:.3f},{_rv[6][3]:.3f})" if has_rgb else ""
                    model_log += (
                        f"    [{_ri:>3}]  topo=0x{_rv[5]:02X} ({_tname:<10})"
                        f"  xyz=({_rv[0]:>10.4f}, {_rv[1]:>10.4f}, {_rv[2]:>10.4f})"
                        f"  uv=({_rv[3]:.4f}, {_rv[4]:.4f}){_col_str}\n"
                    )

            # Split into sub-strips on V_END (topo & 0x80)
            # cull_mode: 2=backface culled (CCW front), 3=frontface culled, 0/1=double-sided
            strips = []
            current = []
            for v in raw_verts:
                current.append(v)
                if v[5] & TOPO_V_END:
                    if current:
                        strips.append(current)
                    current = []
            if current:
                strips.append(current)

            if debug:
                model_log += f"\n  ── strip splits --> {len(strips)} strip(s) ──\n"
                _flat_idx = 0
                for _si, _sv in enumerate(strips):
                    _end_topos = [f'0x{_v[5]:02X}' for _v in _sv]
                    model_log += (
                        f"    strip[{_si}]: {len(_sv)} verts"
                        f"  flat[{_flat_idx}..{_flat_idx + len(_sv) - 1}]"
                        f"  topo_seq=[{', '.join(_end_topos)}]\n"
                    )
                    _flat_idx += len(_sv)

            faces_vertex  = []
            faces_index   = []
            vtx_base      = 0
            strip_vcols   = []   # per-strip flat list of (R,G,B,A) tuples, None if no rgb

            # Backface from cull_mode: both 2 and 3 are single-sided (just different facing)
            backface = cull_mode in (2, 3)

            for strip in strips:
                n = len(strip)
                pts  = [(v[0], v[1], v[2]) for v in strip]
                uvs  = [(v[3], 1.0 + v[4]) for v in strip]  # U as-is; V: 1+v_stored so data2blender's 1-y = v_original
                cols = [v[6] for v in strip] if has_rgb else None
                # Always use the packed normal from flag_word.
                nrms = [v[7] for v in strip]

                # Always add this strip's vertices so vtx_base offsets stay in sync
                # even for strips shorter than 3 vertices (which produce no triangles).
                faces_vertex.append({
                    'point':   pts,
                    'normal':  nrms,
                    'texture': uvs,
                    'colour':  cols,
                })
                strip_vcols.append(cols)

                if n >= 3:
                    # Detect fan: any vertex has topo Fan byte (0x40)
                    is_fan = any((v[5] & ~0x80) == TOPO_FAN for v in strip)

                    if debug:
                        _strip_label = f"strip[{len(faces_vertex)-1}]"
                        model_log += (
                            f"\n  ── face winding  {_strip_label}"
                            f"  n={n}  is_fan={is_fan}"
                            f"  vtx_base={vtx_base}  cull_mode={cull_mode} ──\n"
                        )

                    p = vtx_base   # pivot for fan, or base index for strip

                    strip_counter = -1   # matches NAOMI1: strip_counter starts at -1 per strip
                    for j in range(n - 2):
                        i = vtx_base + j
                        if is_fan:
                            # Fan winding mirrors the strip convention:
                            # cull_mode==2 (backface culled, CCW front) --> swap fan order.
                            # cull_mode==3 (frontface culled, CW front) --> normal fan order.
                            if cull_mode == 2:
                                a, b, c = p, i + 2, i + 1
                                _wind_reason = "fan  cull=2 --> reversed  (p, i+2, i+1)"
                            else:
                                a, b, c = p, i + 1, i + 2
                                _wind_reason = "fan  cull≠2 --> normal    (p, i+1, i+2)"
                        else:
                            if strip_counter % 2 == 1:   # odd
                                if cull_mode == 2:
                                    a, b, c = i + 1, i, i + 2
                                    _wind_reason = "strip odd  cull=2 --> swap    (i+1, i, i+2)"
                                else:
                                    a, b, c = i, i + 1, i + 2
                                    _wind_reason = "strip odd  cull≠2 --> normal  (i, i+1, i+2)"
                            else:                         # even
                                if cull_mode == 2:
                                    a, b, c = i, i + 1, i + 2
                                    _wind_reason = "strip even cull=2 --> normal  (i, i+1, i+2)"
                                else:
                                    a, b, c = i + 1, i, i + 2
                                    _wind_reason = "strip even cull≠2 --> swap    (i+1, i, i+2)"
                        strip_counter += 1

                        if debug:
                            # All vertices are still in the pre-orientation raw pts list
                            # relative to vtx_base.  Map global indices back to strip-local.
                            _la = a - vtx_base
                            _lb = b - vtx_base
                            _lc = c - vtx_base
                            _pa = pts[_la] if 0 <= _la < n else ('?','?','?')
                            _pb = pts[_lb] if 0 <= _lb < n else ('?','?','?')
                            _pc = pts[_lc] if 0 <= _lc < n else ('?','?','?')
                            model_log += (
                                f"    tri[{strip_counter:>3}]  j={j:<3}  sc={strip_counter:<3}"
                                f"  [{a},{b},{c}]  {_wind_reason}\n"
                                f"           A=[{a}] xyz=({_pa[0]:>9.4f}, {_pa[1]:>9.4f}, {_pa[2]:>9.4f})\n"
                                f"           B=[{b}] xyz=({_pb[0]:>9.4f}, {_pb[1]:>9.4f}, {_pb[2]:>9.4f})\n"
                                f"           C=[{c}] xyz=({_pc[0]:>9.4f}, {_pc[1]:>9.4f}, {_pc[2]:>9.4f})\n"
                            )

                        faces_index.append([a, b, c])

                vtx_base += n

            meshes.append({'face_vertex': faces_vertex, 'face_index': faces_index})
            mesh_faces.append(faces_index)
            mesh_colors.append(argb_to_rgba(diffuse0))
            mesh_offcolors.append(argb_to_rgba(specular0))

            # Build flat per-vertex colour list across all strips.
            if has_rgb and any(c is not None for c in strip_vcols):
                _flat_vcol = []
                for _sc in strip_vcols:
                    if _sc is not None:
                        _flat_vcol.extend(_sc)
                    else:
                        # strip has no colour (shouldn't happen within same mesh, but guard)
                        _flat_vcol.extend([(1.0, 1.0, 1.0, 1.0)])
                mesh_vertcol.append(_flat_vcol)

            else:
                mesh_vertcol.append([])


            m_headr_grps.append(m_hdr)
            m_centroid.append([cx, cy, cz, cr])
            m_backface.append(backface)
            if env_flag:
                m_env.append(len(meshes) - 1)

    # Apply orientation / NegScale_X 
    xVal, yVal, zVal = 0, 1, 2
    mesh_vertices = []
    mesh_uvs_out  = []

    for mi, mesh in enumerate(meshes):
        points   = []
        textures = []
        for face in mesh['face_vertex']:
            for pt in face['point']:
                if orientation == 'X_UP':
                    px, py, pz = pt[yVal], pt[xVal], pt[zVal]
                elif orientation == 'Y_UP':
                    px, py, pz = pt[xVal], pt[yVal], pt[zVal]
                elif orientation == 'Z_UP':
                    px, py, pz = pt[xVal], pt[zVal], pt[yVal]
                else:
                    px, py, pz = pt[xVal], pt[yVal], pt[zVal]

                if NegScale_X:
                    px = px * -1.0
                    if px == 0.0:
                        px = 0.0

                points.append(Vector((px, py, pz)))

            for uv in face['texture']:
                textures.append(Vector(uv))

        mesh_vertices.append(points)
        mesh_uvs_out.append(textures)

    if debug:
        model_log += f"\nNL2 import: {len(meshes)} mesh(es) parsed.\n"

    return (mesh_vertices, mesh_uvs_out, mesh_faces, meshes,
            mesh_colors, mesh_offcolors, mesh_vertcol,
            m_headr_grps, gflag_headers,
            obj_centroid_header, m_backface, m_env, m_centroid)


def calculate_crc32(filepath):
    crc = 0
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            crc = zlib.crc32(chunk, crc)
    return f"{crc & 0xffffffff:08x}"
    

def cleanup():
    try:
        # Reset to an empty scene
        bpy.ops.wm.read_homefile(use_empty=True)

        # Ensure context is valid afterward
        bpy.context.view_layer.update()
    except Exception as e:
        print(f"Error during cleanup: {e}")

    print("Scene cleanup completed")


def redraw():
    for area in bpy.context.screen.areas:
        if area.type in ['IMAGE_EDITOR', 'VIEW_3D']:
            area.tag_redraw()


def find_existing_material(naomi_params_id):
    for mat in bpy.data.materials:
        if mat.get('naomi_params_id') == str(naomi_params_id):
            return mat
    return None


def data2blender(mesh_vertex: list, mesh_uvs: list, faces: list, meshes: list, meshColors: list, meshOffColors: list,
                 vertexColors: list, mesh_headers: list,
                 meshBackface: list, mesh_Centroid: list, parent_col: bpy.types.Collection, scale: float,
                 p_filepath: str, mesh_Env: list, orientation, NegScale_X: bool, col_index: int = 0, debug=False, weld: bool = False, import_normals: bool = True):
    if debug: print("meshes:", len(meshes))

    # Bump-mapped surfaces come in pairs: pass1 (base, PIX_BUMP_MAP or shading==-2)
    # followed by pass2 (overlay). Detect both orderings (forward and reverse).
    _bump_base_indices    = set()
    _bump_overlay_indices = set()
    _bump_overlay_by_base  = {}

    for _bi in range(len(mesh_headers)):
        _pix  = mesh_headers[_bi][3][2]   # pixelFormat
        _shad = mesh_headers[_bi][5]       # m_tex_shading
        _is_bump_base = (_pix == 4 or _shad == -2)
        if _is_bump_base:
            _bump_base_indices.add(_bi)

            # Check forward first, then backward as fallback
            def _looks_like_overlay(_idx):
                if _idx < 0 or _idx >= len(mesh_headers):
                    return False
                _p = mesh_headers[_idx][3][2]
                _s = mesh_headers[_idx][5]
                return not (_p == 4 or _s == -2)

            _partner = None
            if _looks_like_overlay(_bi + 1):
                _partner = _bi + 1
            elif _looks_like_overlay(_bi - 1):
                _partner = _bi - 1

            if _partner is not None:
                _bump_overlay_indices.add(_partner)
                _bump_overlay_by_base[_bi] = _partner

    if debug and (_bump_base_indices or _bump_overlay_indices):
        print(f"[NaomiLib] bump-map pairs detected — "
              f"base: {sorted(_bump_base_indices)}  "
              f"overlay: {sorted(_bump_overlay_indices)}")
    # Map mesh index --> created Blender object, used to wire bump_partner_name links.
    _obj_by_index = {}

    for i, mesh in enumerate(meshes):

        vertex_color_node = None
        texture_node = None
        input_node = None

        # Build hardware normals in Blender space (same axis remap as positions)
        import math as _math

        _vert_normals = []
        for _face in meshes[i]['face_vertex']:
            for _n in _face['normal']:
                if orientation == 'X_UP':
                    _nx, _ny, _nz = _n[1], _n[0], _n[2]
                elif orientation == 'Y_UP':
                    _nx, _ny, _nz = _n[0], _n[1], _n[2]
                elif orientation == 'Z_UP':
                    _nx, _ny, _nz = _n[0], _n[2], _n[1]
                else:
                    _nx, _ny, _nz = _n[0], _n[1], _n[2]
                if NegScale_X:
                    _nx = -_nx
                    if _nx == 0.0: _nx = 0.0
                _mag = _math.sqrt(_nx*_nx + _ny*_ny + _nz*_nz)
                if _mag > 1e-6:
                    _nx, _ny, _nz = _nx/_mag, _ny/_mag, _nz/_mag
                else:
                    _nx, _ny, _nz = 0.0, 0.0, 1.0
                _vert_normals.append((_nx, _ny, _nz))

        # Fix winding for double-sided meshes: reverse faces where geom normal
        # disagrees with hardware normal (dot product < 0).
        if not meshBackface[i]:  # False --> double-sided (culling 0 or 1)
            verts = mesh_vertex[i]
            for fi, face in enumerate(faces[i]):
                # Average hardware normal for this face
                _ax = _ay = _az = 0.0
                for _vi in face:
                    if _vi < len(_vert_normals):
                        _ax += _vert_normals[_vi][0]
                        _ay += _vert_normals[_vi][1]
                        _az += _vert_normals[_vi][2]
                _n = len(face)
                _ax /= _n; _ay /= _n; _az /= _n
                v0, v1, v2 = verts[face[0]], verts[face[1]], verts[face[2]]
                ex1, ey1, ez1 = v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2]
                ex2, ey2, ez2 = v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2]
                cx = ey1*ez2 - ez1*ey2
                cy = ez1*ex2 - ex1*ez2
                cz = ex1*ey2 - ey1*ex2
                if (cx*_ax + cy*_ay + cz*_az) < 0.0:
                    faces[i][fi] = list(reversed(face))

        # Create new mesh
        new_mesh = bpy.data.meshes.new(name=f"mesh_{i}")
        new_mesh.uv_layers.new(do_init=True)
        new_mesh.from_pydata(mesh_vertex[i], list(), faces[i])
        # new_mesh.validate(verbose=True)

        # UV: hardware V is stored negated by exporter; blender_v = 1 - raw_v = uv[1]
        _nl_uv_map = {}
        for p, polygon in enumerate(new_mesh.polygons):
            for l, index in enumerate(polygon.loop_indices):
                slot = faces[i][p][l]   # pre-merge binary slot index
                u_hw = mesh_uvs[i][slot][xVal]
                v_hw = mesh_uvs[i][slot][yVal]   # hardware V, converted below for Blender
                _nl_uv_map[slot] = (u_hw, v_hw)  # store in hardware UV space for export
                new_mesh.uv_layers[0].data[index].uv.x = u_hw
                new_mesh.uv_layers[0].data[index].uv.y = 1 - v_hw

        # Smooth shading for Gouraud meshes (l_param[11] = gouraud flag)
        _is_gouraud = mesh_headers[i][0][11]
        if _is_gouraud:
            for _poly in new_mesh.polygons:
                _poly.use_smooth = True

        _n_unique = len(new_mesh.vertices)
        if len(_vert_normals) < _n_unique:
            _vert_normals.extend([(0.0, 0.0, 1.0)] * (_n_unique - len(_vert_normals)))

        # Smooth shading must be on for custom split normals to render.
        for _poly in new_mesh.polygons:
            _poly.use_smooth = True

        new_mesh.update()

        # Assign hardware normals as custom split normals.
        # Dot-product check flips any per-loop discrepancies.
        if import_normals:
            _n_loops = len(new_mesh.loops)
            _loop_normals = [(0.0, 0.0, 1.0)] * _n_loops
            for _poly in new_mesh.polygons:
                _gn = _poly.normal
                for _loop_idx in _poly.loop_indices:
                    _vi = new_mesh.loops[_loop_idx].vertex_index
                    _vn = _vert_normals[_vi] if _vi < len(_vert_normals) else (0.0, 0.0, 1.0)
                    if (_gn.x*_vn[0] + _gn.y*_vn[1] + _gn.z*_vn[2]) < 0.0:
                        _vn = (-_vn[0], -_vn[1], -_vn[2])
                    _loop_normals[_loop_idx] = _vn

            # Blender 4.2+ / 5.x: use_auto_smooth and normals_split_custom_set
            # were removed. Custom normals are now stored as a 'custom_normal'
            # FLOAT_VECTOR CORNER attribute.
            if hasattr(new_mesh, 'use_auto_smooth'):
                # Blender < 4.2 legacy path
                new_mesh.use_auto_smooth = True
                new_mesh.normals_split_custom_set(_loop_normals)
            else:
                # Blender 4.2+ / 5.x path
                if "custom_normal" in new_mesh.attributes:
                    new_mesh.attributes.remove(new_mesh.attributes["custom_normal"])
                attr = new_mesh.attributes.new(
                    name="custom_normal", type='FLOAT_VECTOR', domain='CORNER')
                flat = [c for n in _loop_normals for c in n]
                attr.data.foreach_set("vector", flat)
        else:
            # Recalculate normals automatically (hardware normals discarded)
            import bmesh as _bmesh_n
            _bm_n = _bmesh_n.new()
            _bm_n.from_mesh(new_mesh)
            _bmesh_n.ops.recalc_face_normals(_bm_n, faces=_bm_n.faces)
            _bm_n.to_mesh(new_mesh)
            _bm_n.free()
            new_mesh.update()

        # Weld runs after custom normals are set (they survive the bmesh round-trip).
        import bmesh as _bmesh

        _pre_positions = [v.co.copy() for v in new_mesh.vertices]

        if weld:
            _bm = _bmesh.new()
            _bm.from_mesh(new_mesh)
            _bmesh.ops.remove_doubles(_bm, verts=_bm.verts, dist=0.0)
            _bm.to_mesh(new_mesh)
            _bm.free()
            new_mesh.update()

            def _co_key(co):
                return (round(co.x, 6), round(co.y, 6), round(co.z, 6))

            _post_lookup = {_co_key(v.co): v.index for v in new_mesh.vertices}

            def _nearest_post(co):
                best_idx, best_d2 = 0, float('inf')
                for _idx, _pco in enumerate(new_mesh.vertices):
                    _d2 = (co.x - _pco.co.x)**2 + (co.y - _pco.co.y)**2 + (co.z - _pco.co.z)**2
                    if _d2 < best_d2:
                        best_d2, best_idx = _d2, _idx
                return best_idx

            _merge_map = []
            for _co in _pre_positions:
                _key = _co_key(_co)
                _merge_map.append(_post_lookup[_key] if _key in _post_lookup
                                  else _nearest_post(_co))
        else:
            _merge_map = list(range(len(_pre_positions)))

        # Vertex colours: indexed by pre-merge vertex ID via faces[i][p][l]
        if vertexColors[i]:
            _vcol_name = 'NaomiCol'
            if hasattr(new_mesh, 'color_attributes'):
                color_layer = new_mesh.color_attributes.new(
                    name=_vcol_name, type='BYTE_COLOR', domain='CORNER')
            else:
                color_layer = new_mesh.vertex_colors.new(name=_vcol_name)
            for _p, _polygon in enumerate(new_mesh.polygons):
                for _l, _index in enumerate(_polygon.loop_indices):
                    color_layer.data[_index].color = vertexColors[i][faces[i][_p][_l]]

        new_object = bpy.data.objects.new(f"Obj{col_index}_{i}", new_mesh)
        _obj_by_index[i] = new_object
        new_object.scale = [scale] * 3

        new_object["nl_slot_index"] = i   # binary mesh slot order for export sorting
        new_object["nl_merge_map"] = _merge_map
        # Per-slot UV map stored as flat list [u0,v0,u1,v1,...]
        _nl_uv_flat = []
        for _si in range(len(_pre_positions)):
            _uv = _nl_uv_map.get(_si, (0.0, 0.0))
            _nl_uv_flat.extend([_uv[0], _uv[1]])
        new_object["nl_uv_map"] = _nl_uv_flat

        # Store vertex-colour layer name so _full_rebuild can find it later
        if vertexColors[i]:
            new_object.naomi_param.vcol_layer_name = _vcol_name

        # ---------------
        # Naomi Parameters
        # ----------------

        mesh_centr_x, mesh_centr_y, mesh_centr_z, mesh_bound_radius = mesh_Centroid[i]

        if orientation == 'X_UP':
            mesh_centr_x, mesh_centr_y, mesh_centr_z = mesh_centr_y, mesh_centr_x, mesh_centr_z
        elif orientation == 'Z_UP':
            mesh_centr_x, mesh_centr_y, mesh_centr_z = mesh_centr_x, mesh_centr_z, mesh_centr_y

        if NegScale_X:
            mesh_centr_x *= -1.0

        new_object.naomi_param.centroid_x = mesh_centr_x
        new_object.naomi_param.centroid_x = mesh_centr_x
        new_object.naomi_param.centroid_y = mesh_centr_y
        new_object.naomi_param.centroid_z = mesh_centr_z
        new_object.naomi_param.bound_radius = mesh_bound_radius

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

        # Shading params assigned before TSP so update callbacks see correct values
        new_object.naomi_param.m_tex_shading = mesh_headers[i][5]
        new_object.naomi_param.spec_int = mesh_headers[i][5]
        # Low-level RNA write to preserve -1 without the min=0 clamp
        new_object.naomi_param["mh_texID"] = mesh_headers[i][4]
        new_object.naomi_param.meshColor = meshColors[i]
        new_object.naomi_param.meshOffsetColor = meshOffColors[i]
        new_object.naomi_param.m_shad_type = '0' if mesh_headers[i][5] >= 0 else str(mesh_headers[i][5])
        new_object.naomi_param.m_ambient_light = mesh_headers[i][6]

        new_object.naomi_param.naomi_assigned = True

        _pix_fmt   = mesh_headers[i][3][2]   # pixelFormat from TexCtrl
        _tex_shad  = mesh_headers[i][5]       # m_tex_shading
        new_object.naomi_param.naomi_flag_bump    = (_pix_fmt == 4 or _tex_shad == -2)
        new_object.naomi_param.naomi_flag_env_map = (i in mesh_Env)
        new_object.naomi_param.naomi_flag_palette = (_pix_fmt in (5, 6))
        # Low-level RNA to bypass update callback (handles culling + material elsewhere)
        new_object.naomi_param["naomi_flag_two_sided"] = not meshBackface[i]

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

        mh_texID  = mesh_headers[i][4]
        spec_int  = mesh_headers[i][5]
        # tex_shading: >=0 = TSP enum (0=Decal,1=Modulate,2=DecalAlpha,3=ModulateAlpha)
        #              -1  = Constant/Flat, -2 = Bump, -3 = Vertex Colors
        # -3 always wins; if texture present use TSP enum; otherwise use m_tex_shading.
        m_tex_shading_raw = mesh_headers[i][5]
        if m_tex_shading_raw == -3:
            tex_shading = -3                                  # vertex color — never overridden
        elif mh_texID >= 0:
            tex_shading = mesh_headers[i][2][13]              # 0-3 from TSP register
        else:
            tex_shading = m_tex_shading_raw                   # -1 / -2 special modes

        if debug:
            print(f"[NaomiLib] mesh {i}: m_tex_shading_raw={m_tex_shading_raw}, "
                  f"mh_texID={mh_texID}, tex_shading={tex_shading}, "
                  f"vertexColors present={bool(vertexColors[i])}")
        m_tex_amb = mesh_headers[i][6]  # placeholder
        FlipUV = mesh_headers[i][2][8]
        Clamp = mesh_headers[i][2][9]
        tsp_dstAlpha = mesh_headers[i][2][1]
        tsp_srcAlpha = mesh_headers[i][2][0]
        listType = mesh_headers[i][0][2]

        if debug: print("new object", new_object.name, '; has tex ID: TexID_{0:03d}'.format(mh_texID))

        # ---------------
        # CREATE MATERIAL
        # ---------------

        naomi_params_id = (
            str(mesh_headers[i]),
            str(meshColors[i]),
            str(meshOffColors[i]),
            os.path.normpath(f"{os.path.join(os.path.dirname(p_filepath), 'Textures', f'TexID_{mh_texID:03d}')}")
        )

        if debug: print(naomi_params_id)

        # Check if material with same naomi_params_id exists
        existing_material = find_existing_material(str(naomi_params_id))

        # if same and Vertex Colors not used
        if existing_material and vertexColors[i] == []:
            if debug: print('same!')
            new_mat = existing_material
        else:
            # add viewport color to object
            new_mat = bpy.data.materials.new(f"Naomi_Mat")
            new_mat.diffuse_color = meshColors[i]
            new_mat['naomi_params_id'] = str(naomi_params_id)

            if debug: print("vertex colors:", vertexColors[i])

            # Resolve texture image (file I/O stays in the importer)
            tex_image = None
            if mh_texID >= 0:
                texFileName = f'TexID_{mh_texID:03d}'
                texDir = os.path.join(os.path.dirname(p_filepath), 'Textures')
                textureFileFormats = ('png', 'bmp')

                # Decode PVR if no converted image exists; bump map --> .png, rest --> .bmp
                pvr_path = os.path.normpath(f"{os.path.join(texDir, texFileName)}.PVR")
                if os.path.exists(pvr_path):
                    bmp_path = os.path.join(texDir, f"{texFileName}.bmp")
                    png_path = os.path.join(texDir, f"{texFileName}.png")
                    if not os.path.exists(bmp_path) and not os.path.exists(png_path):
                        if _is_bump_map_pvr(pvr_path):
                            out_fmt = 'png'
                        else:
                            out_fmt = 'bmp'  # covers both normal and palettized
                        pvrdecode([pvr_path], out_fmt, texDir, '')

                for fmt in textureFileFormats:
                    potential_tex_path = os.path.normpath(f"{os.path.join(texDir, texFileName)}.{fmt}")
                    if os.path.exists(potential_tex_path):
                        if debug: print(f"Texture file found: {potential_tex_path}")
                        texPath = potential_tex_path
                        texture_loaded = False
                        for image in bpy.data.images:
                            if texPath in image.filepath:
                                if debug: print(f"Image already loaded: {texPath}")
                                tex_image = image
                                texture_loaded = True
                                break
                        if not texture_loaded:
                            tex_image = bpy.data.images.load(texPath)
                            if debug: print(f"New Image loaded: {texPath}")
                        break  # use first format found

            # Pre-load overlay partner's texture for bump base mesh
            base_tex_image = None
            if i in _bump_base_indices:
                _partner_idx = _bump_overlay_by_base.get(i)
                if _partner_idx is not None:
                    _base_tex_id = mesh_headers[_partner_idx][4]
                    if _base_tex_id >= 0:
                        _base_fname = f'TexID_{_base_tex_id:03d}'
                        _base_dir   = os.path.join(os.path.dirname(p_filepath), 'Textures')
                        for _fmt in ('png', 'bmp'):
                            _base_path = os.path.normpath(
                                os.path.join(_base_dir, f'{_base_fname}.{_fmt}'))
                            if os.path.exists(_base_path):
                                for _img in bpy.data.images:
                                    if _base_path in _img.filepath:
                                        base_tex_image = _img
                                        break
                                if base_tex_image is None:
                                    base_tex_image = bpy.data.images.load(_base_path)
                                break

            # Delegate all node setup to NLmaterial
            from . import build_naomi_material as _build_naomi_material
            _build_naomi_material(
                mat                 = new_mat,
                mesh_color          = meshColors[i],
                mesh_offset_color   = meshOffColors[i],
                tex_shading         = tex_shading,
                tsp_src_alpha       = tsp_srcAlpha,
                tsp_dst_alpha       = tsp_dstAlpha,
                list_type           = listType,
                flip_uv             = FlipUV,
                clamp               = Clamp,
                alpha_tex_op        = new_object.naomi_tsp.alphaTexOp,
                use_backface_culling= meshBackface[i],
                mh_tex_id           = mh_texID,
                tex_image           = tex_image,
                is_env_map          = i in mesh_Env,
                vertex_col_layer    = 'NaomiCol' if tex_shading == -3 else None,
                m_tex_amb           = mesh_headers[i][6],
                tsp_filter          = new_object.naomi_tsp.filter,
                is_bump_base        = (i in _bump_base_indices),
                is_bump_overlay     = (i in _bump_overlay_indices),
                base_tex_image      = base_tex_image,
            )

        new_object.data.materials.append(new_mat)

        # link object to parent collection
        parent_col.objects.link(new_object)

        # Manually set the origin to the exact centroid coordinates
        new_object.data.transform(Matrix.Translation((-mesh_centr_x, -mesh_centr_y, -mesh_centr_z)))
        new_object.location = (mesh_centr_x * scale, mesh_centr_y * scale, mesh_centr_z * scale)

    # Wire bump_partner_name between base and overlay; rename base to '<overlay>_bump'
    import re as _re
    for _bi in _bump_base_indices:
        _oi = _bump_overlay_by_base.get(_bi)
        if _oi is not None:
            base_obj    = _obj_by_index.get(_bi)
            overlay_obj = _obj_by_index.get(_oi)
            if base_obj is not None and overlay_obj is not None:
                # Skip renaming if name already ends in '_bump'
                _current_trimmed = _re.sub(r'\.\d+$', '', base_obj.name)
                if not _current_trimmed.endswith('_bump'):
                    _raw_name = _re.sub(r'\.\d+$', '', overlay_obj.name)
                    base_obj.name = f"{_raw_name}_bump"

                base_obj.naomi_param.bump_partner_name    = overlay_obj.name
                overlay_obj.naomi_param.bump_partner_name = base_obj.name
                # Backfill PointerProperty so UI picker reflects link immediately
                base_obj.naomi_param.bump_partner_obj    = overlay_obj
                overlay_obj.naomi_param.bump_partner_obj = base_obj
                if debug:
                    print(f"[NaomiLib] bump pair linked: {base_obj.name} ↔ {overlay_obj.name}")

    return True


########################
# MAIN functions
########################

def main_function_import_file(self, filepath: str, scaling: float, debug: bool, orientation, NegScale_X: bool, weld: bool = False, import_normals: bool = True, forward_axis: str = '-Y', up_axis: str = '+Z'):
    global model_log

    with open(filepath, "rb") as f:
        NL = f.read(-1)
        size = len(NL)

    if size >= 0xd8:
        if debug: print(filepath)
        filename = filepath.split(os.sep)[-1]

        if debug:
            model_log = ''

        try:
            # Detect NAOMI2 format (format_flag == 0x100 at offset 0)
            if _is_naomi2_bin(NL):
                parse_result = parse_nl2(NL, orientation, NegScale_X, debug=debug)
            else:
                parse_result = parse_nl(NL, orientation, NegScale_X, debug=debug)
            (mesh_vertex, mesh_uvs, faces, meshes, mesh_colors, mesh_offcolors,
             mesh_vertcol, mesh_header_s, g_headers, obj_centroid_header,
             m_backface, m_env, m_centroid) = parse_result
        except EOFError as e:
            print(f"[NaomiLib] EOF error parsing {filename}: {e}")
            self.report({'ERROR'}, f"File '{filename}' appears truncated or unsupported: {e}")
            return False
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
        obj_col.naomi_import_meta.source_filepath    = filepath
        obj_col.naomi_import_meta.source_crc32       = calculate_crc32(filepath)
        obj_col.naomi_import_meta.import_forward_axis = forward_axis
        obj_col.naomi_import_meta.import_up_axis      = up_axis

        obj_col.gp0.objFormat = str(g_headers[0])
        obj_col.gp1.skp1stSrcOp = g_headers[1]
        obj_col.gp1.envMap = g_headers[2]
        obj_col.gp1.pltTex = g_headers[3]
        obj_col.gp1.bumpMap = g_headers[4]

        # Apply axis remap to centroid (same as for vertices)
        updatedPoint_X = obj_centroid_header[0]
        updatedPoint_Y = obj_centroid_header[1]
        updatedPoint_Z = obj_centroid_header[2]

        if orientation == 'X_UP':
            updatedPoint_X = obj_centroid_header[yVal]
            updatedPoint_Y = obj_centroid_header[xVal]
            updatedPoint_Z = obj_centroid_header[zVal]
        elif orientation == 'Y_UP':
            updatedPoint_X = obj_centroid_header[xVal]
            updatedPoint_Y = obj_centroid_header[yVal]
            updatedPoint_Z = obj_centroid_header[zVal]
        elif orientation == 'Z_UP':
            updatedPoint_X = obj_centroid_header[xVal]
            updatedPoint_Y = obj_centroid_header[zVal]
            updatedPoint_Z = obj_centroid_header[yVal]

        if NegScale_X:
            # FIX (Bug 2): +0.0 * -1.0 = IEEE-754 -0.0. Strip the sign bit.
            updatedPoint_X = updatedPoint_X * -1.0
            if updatedPoint_X == 0.0:
                updatedPoint_X = 0.0

        # Snap ULP-noise centroid components to 0.0 (4-ULP threshold, same as exporter)
        _col_r = obj_centroid_header[3]
        _snap_thresh_col = 4.0 * (2.0 ** -23) * max(abs(_col_r), 1e-6)
        _cx_raw, _cy_raw, _cz_raw = updatedPoint_X, updatedPoint_Y, updatedPoint_Z
        updatedPoint_X = 0.0 if abs(_cx_raw) < _snap_thresh_col else _cx_raw
        updatedPoint_Y = 0.0 if abs(_cy_raw) < _snap_thresh_col else _cy_raw
        updatedPoint_Z = 0.0 if abs(_cz_raw) < _snap_thresh_col else _cz_raw
        if updatedPoint_X != _cx_raw or updatedPoint_Y != _cy_raw or updatedPoint_Z != _cz_raw:
            pass  # snap applied silently

        obj_col.naomi_centroidData.centroid_x = updatedPoint_X
        obj_col.naomi_centroidData.centroid_y = updatedPoint_Y
        obj_col.naomi_centroidData.centroid_z = updatedPoint_Z
        obj_col.naomi_centroidData.collection_bound_radius = _col_r

        obj_col.naomi_centroidData.naomi_assigned = True

        bpy.context.scene.collection.children.link(obj_col)

        tex_dir = os.path.join(os.path.dirname(filepath), 'Textures')
        if os.path.isdir(tex_dir):
            _decode_all_pvrs_in_folder(tex_dir)
            obj_col.naomi_tm.tex_folder = tex_dir
            # draw() cannot do RNA writes, so populate list here in operator context
            from . import _rebuild_tex_list
            _rebuild_tex_list(obj_col.naomi_tm, tex_dir)

        # 0-based collection index (excludes root Scene Collection)
        scene_col = bpy.context.scene.collection
        col_index = sum(
            1 for c in bpy.data.collections
            if c is not scene_col and c.naomi_centroidData.naomi_assigned
        ) - 1

        return data2blender(mesh_vertex, mesh_uvs, faces, meshes, meshColors=mesh_colors, meshOffColors=mesh_offcolors,
                            vertexColors=mesh_vertcol, mesh_headers=mesh_header_s, meshBackface=m_backface,
                            mesh_Env=m_env, mesh_Centroid=m_centroid,
                            parent_col=obj_col, scale=scaling, p_filepath=filepath,
                            orientation=orientation, NegScale_X=NegScale_X, col_index=col_index, debug=debug, weld=weld, import_normals=import_normals)


def main_function_import_archive(self, filepath: str, scaling: float, debug: bool, orientation, NegScale_X: bool, weld: bool = False, import_normals: bool = True, forward_axis: str = '-Y', up_axis: str = '+Z'):
    global model_log

    def swap_endianness(data: bytes) -> bytes:
        swapped_data = bytearray(len(data))
        for i in range(0, len(data), 4):
            if i + 3 < len(data):
                swapped_data[i], swapped_data[i + 1], swapped_data[i + 2], swapped_data[i + 3] = data[i + 3], data[
                    i + 2], data[i + 1], data[i]
            else:
                # If leftover chunk that's less than 4 bytes, just copy it as is
                for j in range(len(data) - i):
                    swapped_data[i + j] = data[i + j]
        return bytes(swapped_data)

    filename = filepath.split(os.sep)[-1]

    with open(filepath, "rb") as f:
        read_uint32_buff = lambda: struct.unpack("<I", f.read(0x4))[0]
        read_uint16_buff = lambda: struct.unpack("<H", f.read(0x2))[0]

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
                f.seek(header_length + 0x8)
                end_offset = read_uint32_buff()
                if end_offset < start_offset:
                    f.seek(header_length + 0x4)
                    end_offset = read_uint32_buff()

            f.seek(start_offset)
            if debug: print("NEW child start offset:", start_offset)
            if debug: print("NEW child end offset:", end_offset)

            p = BytesIO(f.read(end_offset - start_offset))

            p.seek(0)
            swapped_data = swap_endianness(p.read())
            p.seek(0)
            p.write(swapped_data)
            p.seek(0)

            if debug:
                model_log = ''

            _nl_bytes = p.read()
            if _is_naomi2_bin(_nl_bytes):
                _parse_result = parse_nl2(_nl_bytes, orientation, NegScale_X, debug=debug)
            else:
                _parse_result = parse_nl(_nl_bytes, orientation, NegScale_X, debug=debug)
            (mesh_vertex, mesh_uvs, faces, meshes, mesh_colors, mesh_offcolors,
             mesh_vertcol, mesh_header_s, g_headers, obj_centroid_header,
             m_backface, m_env, m_centroid) = _parse_result

            if debug:
                print(model_log)
                log_dir = os.path.join(os.path.dirname(filepath), 'Log')
                if not os.path.exists(log_dir):
                    os.makedirs(log_dir)
                log_file = os.path.join(log_dir, filename + f'_{i}.txt')
                with open(log_file, 'w') as l:
                    l.write(model_log)
                print(f'Model log saved to {log_file}')

            obj_col = bpy.data.collections.new(filename)

            obj_col.gp0.objFormat = str(g_headers[0])
            obj_col.gp1.skp1stSrcOp = g_headers[1]
            obj_col.gp1.envMap = g_headers[2]
            obj_col.gp1.pltTex = g_headers[3]
            obj_col.gp1.bumpMap = g_headers[4]

            obj_col.naomi_centroidData.naomi_assigned = True

            bpy.context.scene.collection.children.link(obj_col)

            tex_dir = os.path.join(os.path.dirname(filepath), 'Textures')
            if os.path.isdir(tex_dir):
                _decode_all_pvrs_in_folder(tex_dir)
                obj_col.naomi_tm.tex_folder = tex_dir
                # draw() cannot do RNA writes, so populate list here in operator context
                from . import _rebuild_tex_list
                _rebuild_tex_list(obj_col.naomi_tm, tex_dir)

            # 0-based collection index (excludes root Scene Collection)
            scene_col = bpy.context.scene.collection
            col_index = sum(
                1 for c in bpy.data.collections
                if c is not scene_col and c.naomi_centroidData.naomi_assigned
            ) - 1

            if not data2blender(mesh_vertex, mesh_uvs, faces, meshes, meshColors=mesh_colors,
                                meshOffColors=mesh_offcolors,
                                vertexColors=mesh_vertcol, mesh_headers=mesh_header_s, meshBackface=m_backface,
                                mesh_Env=m_env, mesh_Centroid=m_centroid,
                                parent_col=obj_col, scale=scaling, p_filepath=filepath,
                                orientation=orientation, NegScale_X=NegScale_X,
                                col_index=col_index, debug=debug, weld=weld, import_normals=import_normals): return False
            f.seek(st_p)
            start_offset = end_offset

    if debug: print("NUMBER OF CHILDREN:", num_child_models)

    return True


def _is_bump_map_pvr(pvr_path):
    """Return True if the PVR file has the bump-map pixel format (px_byte == 4)."""
    try:
        with open(pvr_path, 'rb') as f:
            data = f.read(0x20)
        offset = data.find(b"PVRT")
        if offset == -1:
            return False
        px_byte = data[offset + 0x8]
        return px_byte == 4  # 4 == Bump Map pixel format
    except Exception:
        return False


def _is_palettized_pvr(pvr_path):
    """Return True if PVR uses palettized pixel format (px_byte 8=PAL-4, 9=PAL-8)."""
    try:
        with open(pvr_path, 'rb') as f:
            data = f.read(0x20)
        offset = data.find(b"PVRT")
        if offset == -1:
            return False
        px_byte = data[offset + 0x8]
        return px_byte in (8, 9)  # 8 = PAL-4, 9 = PAL-8
    except Exception:
        return False


def _find_palette_file(pvr_path):
    """Return companion .pvp or .pal path for pvr_path, or None."""
    base = pvr_path[:-4]  # strip .PVR / .pvr
    for ext in ('.pvp', '.PVP', '.pal', '.PAL'):
        candidate = base + ext
        if os.path.exists(candidate):
            return candidate
    return None


def _decode_all_pvrs_in_folder(tex_dir):
    """Decode all TexID_XXX.PVRs in tex_dir that have no converted image yet.
    Bump --> .png, palettized --> .bmp (bl_pypvr auto-applies companion palette), rest --> .bmp.
    """
    if not tex_dir or not os.path.isdir(tex_dir):
        return

    pvr_normal     = []
    pvr_bump       = []
    pvr_palettized = []
    for fname in sorted(os.listdir(tex_dir)):
        base, ext = os.path.splitext(fname)
        if ext.upper() != '.PVR':
            continue
        if not (base.startswith('TexID_') and len(base) == 9):
            continue
        bmp_path = os.path.join(tex_dir, base + '.bmp')
        png_path = os.path.join(tex_dir, base + '.png')
        if not os.path.exists(bmp_path) and not os.path.exists(png_path):
            pvr_full = os.path.normpath(os.path.join(tex_dir, fname))
            if _is_bump_map_pvr(pvr_full):
                pvr_bump.append(pvr_full)
            elif _is_palettized_pvr(pvr_full):
                pvr_palettized.append(pvr_full)
            else:
                pvr_normal.append(pvr_full)

    if not pvr_normal and not pvr_bump and not pvr_palettized:
        return

    try:
        if pvr_normal:
            pvrdecode(pvr_normal, 'bmp', tex_dir, '-log')
        if pvr_bump:
            pvrdecode(pvr_bump, 'png', tex_dir, '-log')
        if pvr_palettized:
            pvrdecode(pvr_palettized, 'bmp', tex_dir, '-log')
    except Exception as _e:
        print(f"[NaomiLib] _decode_all_pvrs_in_folder: decode error: {_e}")