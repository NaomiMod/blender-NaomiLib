from __future__ import annotations

import bpy
import struct
import os
import zlib
import bmesh
import math
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional
import io
import subprocess
import sys


# Global flag word bit-field positions
NL_PF_ENVMAP    = 8     # 1bit  0 = no env map
NL_PF_NOT_GP    = 7     # 1bit  0 = send global param, 1 = skip (reuse prev)
NL_PF_GOURAUD   = 6     # 1bit  Gouraud shading on (true)
NL_PF_S_INDEX   = 5     # 1bit  1 = super-index format
NL_PF_STRIP     = 4     # 1bit  triangle strip
NL_PF_TRIANGLE  = 3     # 1bit  triangle list
NL_PF_SPRITE    = 2     # 1bit  sprite
NL_PF_CULLING   = 0     # 2bit  culling mode


class NL_PF_GloblFlag:
    """
    NL_PF_GloblFlag (packed into one uint32).

    Bit layout (LSB = 0):
      [1:0]  culling   (2 bits)
      [2]    sprite    (1 bit)
      [3]    triangle  (1 bit)
      [4]    strip     (1 bit)
      [5]    s_index   (1 bit)
      [6]    gouraud   (1 bit)
      [7]    not_gp    (1 bit)
      [8]    envmap    (1 bit)
      [31:9] dummy     (23 bits, always 0)
    """

    __slots__ = ("_word",)

    def __init__(self, word: int = 0):
        self._word = word & 0xFFFFFFFF

    def to_uint32(self) -> int:
        return self._word

    @classmethod
    def from_uint32(cls, word: int) -> "NL_PF_GloblFlag":
        return cls(word)

    @property
    def culling(self) -> int:             # 2 bits at [1:0]
        return (self._word >> 0) & 0x3

    @culling.setter
    def culling(self, v: int):
        self._word = (self._word & ~(0x3 << 0)) | ((v & 0x3) << 0)

    @property
    def sprite(self) -> int:              # 1 bit at [2]
        return (self._word >> 2) & 0x1

    @sprite.setter
    def sprite(self, v: int):
        self._word = (self._word & ~(0x1 << 2)) | ((v & 0x1) << 2)

    @property
    def triangle(self) -> int:            # 1 bit at [3]
        return (self._word >> 3) & 0x1

    @triangle.setter
    def triangle(self, v: int):
        self._word = (self._word & ~(0x1 << 3)) | ((v & 0x1) << 3)

    @property
    def strip(self) -> int:               # 1 bit at [4]
        return (self._word >> 4) & 0x1

    @strip.setter
    def strip(self, v: int):
        self._word = (self._word & ~(0x1 << 4)) | ((v & 0x1) << 4)

    @property
    def s_index(self) -> int:             # 1 bit at [5]
        return (self._word >> 5) & 0x1

    @s_index.setter
    def s_index(self, v: int):
        self._word = (self._word & ~(0x1 << 5)) | ((v & 0x1) << 5)

    @property
    def gouraud(self) -> int:             # 1 bit at [6]
        return (self._word >> 6) & 0x1

    @gouraud.setter
    def gouraud(self, v: int):
        self._word = (self._word & ~(0x1 << 6)) | ((v & 0x1) << 6)

    @property
    def not_gp(self) -> int:              # 1 bit at [7]
        return (self._word >> 7) & 0x1

    @not_gp.setter
    def not_gp(self, v: int):
        self._word = (self._word & ~(0x1 << 7)) | ((v & 0x1) << 7)

    @property
    def envmap(self) -> int:              # 1 bit at [8]
        return (self._word >> 8) & 0x1

    @envmap.setter
    def envmap(self, v: int):
        self._word = (self._word & ~(0x1 << 8)) | ((v & 0x1) << 8)

    def __repr__(self):
        return (f"NL_PF_GloblFlag(envmap={self.envmap}, not_gp={self.not_gp}, "
                f"gouraud={self.gouraud}, s_index={self.s_index}, "
                f"strip={self.strip}, triangle={self.triangle}, "
                f"sprite={self.sprite}, culling={self.culling})")


# Polygon vertex formats

@dataclass
class NL_PF_PolygonFormat0:
    """Textured with UV."""
    x: float = 0.0;  y: float = 0.0;  z: float = 0.0
    nx: float = 0.0; ny: float = 0.0; nz: float = 0.0
    u: float = 0.0;  v: float = 0.0


@dataclass
class NL_PF_PolygonFormat1:
    """Flat / no texture."""
    x: float = 0.0;  y: float = 0.0;  z: float = 0.0
    nx: float = 0.0; ny: float = 0.0; nz: float = 0.0


@dataclass
class NL_PF_PolygonFormat2:
    """Textured with UV (same layout as Format0)."""
    x: float = 0.0;  y: float = 0.0;  z: float = 0.0
    nx: float = 0.0; ny: float = 0.0; nz: float = 0.0
    u: float = 0.0;  v: float = 0.0


@dataclass
class NL_PF_PolygonFormat3:
    """No texture."""
    x: float = 0.0;  y: float = 0.0;  z: float = 0.0
    nx: float = 0.0; ny: float = 0.0; nz: float = 0.0


@dataclass
class NL_PF_PolygonFormat4:
    """Bump-mapped with tangent basis vectors."""
    x: float = 0.0;  y: float = 0.0;  z: float = 0.0
    nx: float = 0.0; ny: float = 0.0; nz: float = 0.0
    tex_nx0: float = 0.0; tex_ny0: float = 0.0; tex_nz0: float = 0.0
    tex_nx1: float = 0.0; tex_ny1: float = 0.0; tex_nz1: float = 0.0
    u: float = 0.0;  v: float = 0.0


# HOLLY / CLX Parameter Control Word bit positions
NL_PF_ListType   = 24     # 2bit
NL_PF_Volume     = 6
NL_PF_Col_Type   = 4
NL_PF_Texture    = 3
NL_PF_Offset     = 2
NL_PF_Gouraud    = 1
NL_PF_16bit_UV   = 0

# ISP_TSP Instruction bit positions
NL_PF_DepthCompareMode = 29
NL_PF_CullingMode      = 27
NL_PF_ZWriteDisable    = 26
NL_PF_Texture2         = 25
NL_PF_Offset2          = 24
NL_PF_Gouraud2         = 23
NL_PF_16bit_UV2        = 22
NL_PF_CacheBypass      = 21
NL_PF_DcalcCtrl        = 20

# TSP Instruction bit positions
NL_PF_SRC_AlphaInstr       = 29
NL_PF_DST_AlphaInstr       = 26
NL_PF_SRC_Select           = 25
NL_PF_DST_Select           = 24
NL_PF_FogControl           = 22     # 2bit, 2 = no fog
NL_PF_ColorClamp           = 21
NL_PF_UseAlpha             = 20
NL_PF_IgnoreTexAlpha       = 19
NL_PF_FlipUV               = 17
NL_PF_ClampUV              = 15
NL_PF_FilterMode           = 13
NL_PF_SuperSampleTexture   = 12
NL_PF_MipMapD_adjust       = 8      # 4bit, 0b0100 = 1.0
NL_PF_TextureShadingInstr  = 6
NL_PF_TextureSize_U        = 3
NL_PF_TextureSize_V        = 0

# Texture Control Word bit positions
NL_PF_MIP_Mapped      = 31
NL_PF_VQ_Compressed   = 30
NL_PF_PixelFormat     = 27     # 3bit
NL_PF_ScanOrder       = 26
NL_PF_StrideSelect    = 25
NL_PF_TextureAddress  = 0      # 21bit, 64-byte aligned
NL_PF_PaletteSelector = 21     # 6bit, palette index


# Global parameter block: type 2 (textured)

class NL_PF_GloblParamType2:
    """
    'data' is a list of ints (vertex data that follows the header).
    """

    def __init__(self):
        self.paramerter_control: int = 0
        self.ISP_TSP_instruction: int = 0
        self.TSP_instruction: int = 0
        self.texture_control: int = 0
        self.cx: float = 0.0
        self.cy: float = 0.0
        self.cz: float = 0.0
        self.cr: float = 0.0            # bounding sphere center + radius
        self.tex_pvf_index: int = 0
        self.specular: int = 0          # shading mode / specular exponent
        self.tex_ambient: float = 0.0
        self.dummy0: int = 0
        self.dummy1: int = 0
        self.data_size_for_sort_DMA: int = 0
        self.next_address_for_sort_DMA: int = 0
        self.face_color_alpha: int = 0
        self.face_color_R: int = 0
        self.face_color_G: int = 0
        self.face_color_B: int = 0
        self.face_offset_color_alpha: int = 0
        self.face_offset_color_R: int = 0
        self.face_offset_color_G: int = 0
        self.face_offset_color_B: int = 0
        self.skip_byte: int = 0         # byte offset from &gflag to next global param
        self.gflag: NL_PF_GloblFlag = NL_PF_GloblFlag()
        self.polygon_num: int = 0       # number of vertices in strip or triangle list
        self.data: List[int] = []       # vertex data follows


# Global parameter block: type 1 (untextured)

class NL_PF_GloblParamType1:

    def __init__(self):
        self.paramerter_control: int = 0
        self.cx: float = 0.0
        self.cy: float = 0.0
        self.cz: float = 0.0
        self.cr: float = 0.0
        self.ISP_TSP_instruction: int = 0
        self.TSP_instruction: int = 0
        self.texture_control: int = 0
        self.face_color_alpha: int = 0
        self.face_color_R: int = 0
        self.face_color_G: int = 0
        self.face_color_B: int = 0
        self.skip_byte: int = 0
        self.gflag: NL_PF_GloblFlag = NL_PF_GloblFlag()
        self.polygon_num: int = 0
        self.data: List[int] = []


# String-buffer length constants
MODEL_NAME_LEN = 128
MAT_NAME_LEN   = 64
TEX_NAME_LEN   = 512
PAL_NAME_LEN   = 512
CLST_NAME_LEN  = 512

class VOL2_TEX_FLAG:
    __slots__ = ("v0", "v1")

    def __init__(self, v0: bool = False, v1: bool = False):
        self.v0 = v0
        self.v1 = v1

def same_float0(a: float, b: float) -> bool:
    return abs(a - b) < 0.00001

def same_float_cmnvtx_pos(a: float, b: float) -> bool:
    return abs(a - b) < 0.001

def same_float_cmnvtx_pos2(a: float, b: float) -> bool:
    return abs(a - b) < 0.001

def same_float_cmnvtx_nrm(a: float, b: float) -> bool:
    return abs(a - b) < 0.05

_f32_struct = struct.Struct('<f')
_f32_pack   = _f32_struct.pack
_f32_unpack = _f32_struct.unpack

_math_copysign = __import__('math').copysign

def _f32(v: float) -> float:
    # Short-circuit +0.0; must NOT short-circuit -0.0 (sign bit differs).
    if v == 0.0 and _math_copysign(1.0, v) > 0:
        return 0.0
    return _f32_unpack(_f32_pack(v))[0]

class Std_Float:
    """Wraps a 32-bit float value. All arithmetic is kept in single precision"""

    __slots__ = ("_data",)

    def __init__(self, value: float = 0.0):
        if value == 0.0 and _math_copysign(1.0, value) > 0:
            self._data = 0.0
        else:
            self._data: float = _f32(float(value))

    @property
    def data(self) -> float:
        return self._data

    @data.setter
    def data(self, v: float):
        self._data = _f32(float(v))

    def __float__(self) -> float:
        return self._data

    def __index__(self) -> int:
        return int(self._data)

    def __repr__(self) -> str:
        return f"Std_Float({self._data!r})"

    def hex(self) -> int:
        """Return the IEEE-754 single-precision bit pattern as uint32."""
        return struct.unpack("<I", struct.pack("<f", self._data))[0]

    @classmethod
    def from_hex(cls, bits: int) -> "Std_Float":
        val = struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]
        return cls(val)

    def assign(self, value: float) -> float:
        self._data = _f32(float(value))
        return self._data

    def __iadd__(self, other) -> "Std_Float":
        self._data = _f32(self._data + float(other))
        return self

    def __isub__(self, other) -> "Std_Float":
        self._data = _f32(self._data - float(other))
        return self

    def __imul__(self, other) -> "Std_Float":
        self._data = _f32(self._data * float(other))
        return self

    def __itruediv__(self, other) -> "Std_Float":
        self._data = _f32(self._data / float(other))
        return self

    def __add__(self, other) -> float:
        return _f32(self._data + float(other))

    def __radd__(self, other) -> float:
        return _f32(float(other) + self._data)

    def __sub__(self, other) -> float:
        return _f32(self._data - float(other))

    def __rsub__(self, other) -> float:
        return _f32(float(other) - self._data)

    def __mul__(self, other) -> float:
        return _f32(self._data * float(other))

    def __rmul__(self, other) -> float:
        return _f32(float(other) * self._data)

    def __truediv__(self, other) -> float:
        return _f32(self._data / float(other))

    def __neg__(self) -> float:
        return _f32(-self._data)

    def __eq__(self, other) -> bool:
        if isinstance(other, Std_Float):
            return self._data == other._data
        return self._data == _f32(float(other))

    def __ne__(self, other) -> bool:
        return not self.__eq__(other)

    def __lt__(self, other) -> bool:
        return self._data < _f32(float(other))

    def __le__(self, other) -> bool:
        return self._data <= _f32(float(other))

    def __gt__(self, other) -> bool:
        return self._data > _f32(float(other))

    def __ge__(self, other) -> bool:
        return self._data >= _f32(float(other))

    def __hash__(self):
        return hash(self._data)

class Std_Cluster:

    def __init__(self):
        self.clst_name: str = ""
        self.point_relation_count: int = 0
        self.point_relation: Optional[List[int]] = None

class Std_Material:

    def __init__(self):
        self.same_flag: bool = False
        self.same_flag2: bool = False
        self.shadow_effect: bool = False
        self.double_side: bool = False
        self.fog: bool = False
        self.fog_mode: int = 2
        self.fade: bool = False
        self.ignore_tex_alpha: int = 1

        self.mat_name: str = ""
        self.pic_name: str = ""
        self.fullpath_pic_name: str = ""
        self.tex_id: int = -1
        self.pal_name: str = ""
        self.fullpath_pal_name: str = ""

        self.shading_type: int = 0
        self.tex_size_u: int = 0
        self.tex_size_v: int = 0
        self.blend: float = 0.0

        self.uAlternate: int = 0
        self.vAlternate: int = 0

        self.g_amb: float = 0.0

        self.effect: int = 0
        self.transpFct: float = 0.0

        self.amb_R: Std_Float = Std_Float(0.0)
        self.amb_G: Std_Float = Std_Float(0.0)
        self.amb_B: Std_Float = Std_Float(0.0)

        self.dif_R: Std_Float = Std_Float(0.0)
        self.dif_G: Std_Float = Std_Float(0.0)
        self.dif_B: Std_Float = Std_Float(0.0)

        self.spc_R: Std_Float = Std_Float(0.0)
        self.spc_G: Std_Float = Std_Float(0.0)
        self.spc_B: Std_Float = Std_Float(0.0)

        self.exp: Std_Float = Std_Float(0.0)
        self.trs: Std_Float = Std_Float(0.0)
        self.tex_amb: Std_Float = Std_Float(0.0)

        self.filter_mode: int = 0

        self.env_map: bool = False
        self.clamp_u: bool = False
        self.clamp_v: bool = False
        self.super_sample_tex: bool = False
        self.mipmap_d_adjust: int = 4
        self.mip_mapped: int = 0
        self.vq_compressed: bool = False
        self.bump_map: bool = False
        self.auto_bump_map_generate: bool = False
        self.pixel_format: int = -1
        self.tsi_parameter: int = -1
        self.roughness: float = 0.0

        self.tex_cropp_min_u: float = 0.0
        self.tex_cropp_max_u: float = 0.0
        self.tex_cropp_min_v: float = 0.0
        self.tex_cropp_max_v: float = 0.0

        self.src_alpha_instr: int = -1
        self.dst_alpha_instr: int = -1

        self.scan_order: bool = False
        self.punch_through: bool = False
        self.color_clamp: bool = False

        self.Vol2para: Optional["Std_Material"] = None

class Std_Point:

    __slots__ = ("x", "y", "z", "tag_flag")

    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0):
        self.x: Std_Float = Std_Float(x)
        self.y: Std_Float = Std_Float(y)
        self.z: Std_Float = Std_Float(z)
        self.tag_flag: int = 0

    @staticmethod
    def _make(xd: float, yd: float, zd: float) -> "Std_Point":
        p = object.__new__(Std_Point)
        xf = object.__new__(Std_Float); xf._data = xd
        yf = object.__new__(Std_Float); yf._data = yd
        zf = object.__new__(Std_Float); zf._data = zd
        p.x = xf; p.y = yf; p.z = zf; p.tag_flag = 0
        return p

    def __eq__(self, other: "Std_Point") -> bool:
        return self.x == other.x and self.y == other.y and self.z == other.z

    def __add__(self, other: "Std_Point") -> "Std_Point":
        tmp = Std_Point()
        tmp.x.assign(_f32(float(self.x) + float(other.x)))
        tmp.y.assign(_f32(float(self.y) + float(other.y)))
        tmp.z.assign(_f32(float(self.z) + float(other.z)))
        return tmp

    def __sub__(self, other: "Std_Point") -> "Std_Point":
        tmp = Std_Point()
        tmp.x.assign(_f32(float(self.x) - float(other.x)))
        tmp.y.assign(_f32(float(self.y) - float(other.y)))
        tmp.z.assign(_f32(float(self.z) - float(other.z)))
        return tmp

    def __iadd__(self, other: "Std_Point") -> "Std_Point":
        self.x += float(other.x)
        self.y += float(other.y)
        self.z += float(other.z)
        return self

    def __itruediv__(self, n: int) -> "Std_Point":
        self.x /= n
        self.y /= n
        self.z /= n
        return self

    def __truediv__(self, n: int) -> "Std_Point":
        tmp = Std_Point()
        tmp.x.assign(_f32(float(self.x) / n))
        tmp.y.assign(_f32(float(self.y) / n))
        tmp.z.assign(_f32(float(self.z) / n))
        return tmp

    def assign_scalar(self, num: float):
        self.x.assign(num)
        self.y.assign(num)
        self.z.assign(num)

    def len(self) -> float:
        fx = float(self.x); fy = float(self.y); fz = float(self.z)
        return math.sqrt(_f32(_f32(_f32(fx * fx) + _f32(fy * fy)) + _f32(fz * fz)))

    def normalize(self):
        l = _f32(self.len())
        if l != 0.0:
            self.x /= l
            self.y /= l
            self.z /= l
        else:
            self.x.assign(0.0)
            self.y.assign(0.0)
            self.z.assign(0.0)

    def __repr__(self) -> str:
        return f"Std_Point({float(self.x)}, {float(self.y)}, {float(self.z)})"

# Free vector functions

class Std_PointInfo:

    __slots__ = (
        'poly', 'point_index', 'nx', 'ny', 'nz', 'u', 'v',
        'vtx_color_A', 'vtx_color_R', 'vtx_color_G', 'vtx_color_B',
        'normal_diff', 'nx0', 'ny0', 'nz0', '_eq_key',
    )

    def __init__(self):
        self.poly: Optional["Std_Polygon"] = None
        self.point_index: int = 0
        self.nx: Std_Float = Std_Float(0.0)
        self.ny: Std_Float = Std_Float(0.0)
        self.nz: Std_Float = Std_Float(0.0)
        self.u: Std_Float = Std_Float(0.0)
        self.v: Std_Float = Std_Float(0.0)

        self.vtx_color_A: int = 0xFF
        self.vtx_color_R: int = 0xFF
        self.vtx_color_G: int = 0xFF
        self.vtx_color_B: int = 0xFF

        self.normal_diff: int = 0
        self.nx0: float = 0.0
        self.ny0: float = 0.0
        self.nz0: float = 0.0

        # Precomputed equality key — set by seal() once all fields are final.
        # For shading_type==7: (point_index, u_bits, v_bits, A, R, G, B).
        # Otherwise: (point_index, u_bits, v_bits).
        self._eq_key: tuple = ()

    def seal(self) -> None:
        """Compute and cache _eq_key. Call once, after all fields are set."""
        u_bits = struct.unpack("<I", struct.pack("<f", self.u._data))[0]
        v_bits = struct.unpack("<I", struct.pack("<f", self.v._data))[0]
        shading_type = 0
        if self.poly is not None and self.poly.model is not None:
            mat_idx = self.poly.material_index
            shading_type = self.poly.model.material[mat_idx].shading_type
        if shading_type == 7:
            self._eq_key = (self.point_index, u_bits, v_bits,
                            self.vtx_color_A, self.vtx_color_R,
                            self.vtx_color_G, self.vtx_color_B)
        else:
            self._eq_key = (self.point_index, u_bits, v_bits)

    def __eq__(self, other: "Std_PointInfo") -> bool:
        sk = self._eq_key
        if sk:
            return sk == other._eq_key

        # Slow fallback — seal() not yet called.
        if self.point_index != other.point_index:
            return False
        if self.u._data != other.u._data or self.v._data != other.v._data:
            return False
        shading_type = 0
        if self.poly is not None and self.poly.model is not None:
            mat_idx = self.poly.material_index
            shading_type = self.poly.model.material[mat_idx].shading_type
        if shading_type != 7:
            return True
        return (self.vtx_color_A == other.vtx_color_A and
                self.vtx_color_R == other.vtx_color_R and
                self.vtx_color_G == other.vtx_color_G and
                self.vtx_color_B == other.vtx_color_B)

class Std_Polygon:

    __slots__ = (
        'poly_ID', 'more_set_gr', 'gr', 'srch_index',
        'model', 'material_index', 'info_list_num', 'info_list',
        'normal', 'tex_normal0', 'tex_normal1', '_cos_disc_angle',
        'hole_polygon', 'grp_no',
        'next', 'opt_next', 'offset', 'skip_count',
        'sort_flag0', 'sort_flag_byte_diff', 'flag', 'pi',
        '_NL_PF_STRIP', '_NL_PF_TRIANGLE', '_NL_PF_SPRITE',
        '_NL_PF_NOT_GP', '_NL_PF_S_INDEX',
    )

    def __init__(self):
        self.poly_ID: int = 0
        self.more_set_gr: int = 0
        self.gr: bool = False
        self.srch_index: int = 0

        self.model: Optional["Std_Model"] = None
        self.material_index: int = 0
        self.info_list_num: int = 0
        self.info_list: Optional[List[Std_PointInfo]] = None

        self.normal: Std_Point = Std_Point()
        self.tex_normal0: Std_Point = Std_Point()
        self.tex_normal1: Std_Point = Std_Point()
        # Cached cos(model.discAngle) — set once during strip-point setup.
        self._cos_disc_angle: float = 1.0

    def copy_from(self, src: "Std_Polygon"):
        self.model          = src.model
        self.material_index = src.material_index
        self.info_list_num  = src.info_list_num
        self.normal         = src.normal
        self.gr             = src.gr
        self.tex_normal0    = src.tex_normal0
        self.tex_normal1    = src.tex_normal1

        if self.info_list_num != 0:
            self.info_list = []
            for i in range(self.info_list_num):
                pi = Std_PointInfo()
                s = src.info_list[i]
                pi.point_index = s.point_index
                pi.nx = Std_Float(float(s.nx))
                pi.ny = Std_Float(float(s.ny))
                pi.nz = Std_Float(float(s.nz))
                pi.u = Std_Float(float(s.u))
                pi.v = Std_Float(float(s.v))
                pi.vtx_color_A = s.vtx_color_A
                pi.vtx_color_R = s.vtx_color_R
                pi.vtx_color_G = s.vtx_color_G
                pi.vtx_color_B = s.vtx_color_B
                pi.normal_diff = s.normal_diff
                pi.nx0 = s.nx0
                pi.ny0 = s.ny0
                pi.nz0 = s.nz0
                pi.poly = self
                self.info_list.append(pi)
        else:
            self.info_list = None

class TouchSide:

    __slots__ = ("my_a", "my_b", "t_index", "cm_a", "cm_b")

    def __init__(self):
        self.my_a: int = 0
        self.my_b: int = 0
        self.t_index: int = 0
        self.cm_a: int = 0
        self.cm_b: int = 0

class PolySrch:

    __slots__ = (
        'use_flag', 'pl_index', 'touch_count', 'r_touch_count',
        'touch_side', 'touch_side_bkup', 'srch_start', 'dec_count',
        'dec_count_bkup', 'before_strip_count', 'dirty_idx',
        'self_srch_index', 'touch_side_map_k', 'touch_side_map_v',
        'touch_side_map_n', 'touch_side_map_bkup_k',
        'touch_side_map_bkup_v', 'touch_side_map_bkup_n',
    )

    def __init__(self):
        self.use_flag: int = 0
        self.pl_index: int = 0
        self.touch_count: int = 0
        self.r_touch_count: int = 0
        self.touch_side: Optional[List[TouchSide]] = None
        self.touch_side_bkup: Optional[List[TouchSide]] = None
        self.srch_start: int = 0
        self.dec_count: int = 0
        self.dec_count_bkup: int = 0
        self.before_strip_count: int = -1
        self.dirty_idx: int = -1
        self.self_srch_index: int = 0
        # Micro-map for touch_side_map (max 3 entries): parallel key/value arrays
        self.touch_side_map_k: List[int] = [-1, -1, -1]
        self.touch_side_map_v: List[int] = [ 0,  0,  0]
        self.touch_side_map_n: int = 0
        self.touch_side_map_bkup_k: List[int] = [-1, -1, -1]
        self.touch_side_map_bkup_v: List[int] = [ 0,  0,  0]
        self.touch_side_map_bkup_n: int = 0

class lt_short:

    __slots__ = ("_raw",)

    def __init__(self, raw: int = 0):
        self._raw = raw & 0xFFFF

    def __int__(self) -> int:
        d = self._raw
        return ((d >> 8) & 0xFF) | (((d << 8) & 0xFF00))

    def __repr__(self) -> str:
        return f"lt_short(raw={self._raw:  # 06x}, value={int(self)})"

    @classmethod
    def from_bytes(cls, b: bytes) -> "lt_short":
        return cls(struct.unpack(">H", b)[0])

class lt_int:

    __slots__ = ("_raw",)

    def __init__(self, raw: int = 0):
        self._raw = raw & 0xFFFFFFFF

    def __int__(self) -> int:
        d = self._raw
        return (((d >> 24) & 0xFF) |
                (((d >> 8)  & 0x0000FF00)) |
                (((d << 8)  & 0x00FF0000)) |
                (((d << 24) & 0xFF000000)))

    def __repr__(self) -> str:
        return f"lt_int(raw={self._raw:  # 010x}, value={int(self)})"

    @classmethod
    def from_bytes(cls, b: bytes) -> "lt_int":
        return cls(struct.unpack(">I", b)[0])

class IdxList:

    def __init__(self, pl_idx: int, next_node: Optional["IdxList"] = None):
        self.pl_idx: int = pl_idx
        self.next: Optional["IdxList"] = next_node

    @staticmethod
    def destroy(node: Optional["IdxList"]):
        while node is not None:
            nxt = node.next
            node.next = None
            node = nxt

class StripData:

    class POINT_INDEX:
        __slots__ = ("sp_idx", "flag", "pol_idx", "inf_idx", "flag2")

        def __init__(self):
            self.sp_idx: int = 0
            self.flag: int = 0
            self.pol_idx: int = 0
            self.inf_idx: int = 0
            self.flag2: int = 0

    def __init__(self):
        self._NL_PF_S_INDEX: int = 0
        self._NL_PF_NOT_GP: int = 0
        self._NL_PF_GOURAUD: int = 0
        self._NL_PF_CULLING: int = 0
        self._NL_PF_STRIP: int = 0
        self._NL_PF_TRIANGLE: int = 0
        self._NL_PF_SPRITE: int = 0

        self.tex: VOL2_TEX_FLAG = VOL2_TEX_FLAG()

        self.strip_num: int = 0

        self.next: Optional["StripData"] = None
        self.opt_next: Optional["StripData"] = None

        self.pi: Optional[List[StripData.POINT_INDEX]] = None
        self.grp_no: int = 0
        self.sort_flag0: int = 0
        self.sort_flag_byte_diff: int = 0

class SAME_POINT:

    __slots__ = (
        "point_index",
        "nx", "ny", "nz",
        "u", "v",
        "DMA_ADRS", "RAM_ADRS",
        "vtx_color_A", "vtx_color_R", "vtx_color_G", "vtx_color_B",
        "grp_no",
    )

    def __init__(self):
        self.point_index: int = 0
        self.nx: Std_Float = Std_Float()
        self.ny: Std_Float = Std_Float()
        self.nz: Std_Float = Std_Float()
        self.u: Std_Float = Std_Float()
        self.v: Std_Float = Std_Float()
        self.DMA_ADRS: int = 0
        self.RAM_ADRS: int = 0
        self.vtx_color_A: int = 0
        self.vtx_color_R: int = 0
        self.vtx_color_G: int = 0
        self.vtx_color_B: int = 0
        self.grp_no: int = 0

class CMN_VTX:

    __slots__ = (
        "flag", "offset", "point_index",
        "child_name", "clst_name",
        "px", "py", "pz",
        "nx", "ny", "nz",
        "px2", "py2", "pz2",
        "nx2", "ny2", "nz2",
    )

    def __init__(self):
        self.flag: int = 0
        self.offset: int = 0
        self.point_index: int = 0
        self.child_name: str = ""
        self.clst_name: str = ""
        self.px: float = 0.0;  self.py: float = 0.0;  self.pz: float = 0.0
        self.nx: float = 0.0;  self.ny: float = 0.0;  self.nz: float = 0.0
        self.px2: float = 0.0; self.py2: float = 0.0; self.pz2: float = 0.0
        self.nx2: float = 0.0; self.ny2: float = 0.0; self.nz2: float = 0.0

# KM_TEXTURE — Texture format constants
KM_TEXTURE_TWIDDLED              = 0x0100
KM_TEXTURE_TWIDDLED_MM           = 0x0200
KM_TEXTURE_VQ                    = 0x0300
KM_TEXTURE_VQ_MM                 = 0x0400
KM_TEXTURE_PALETTIZE4            = 0x0500
KM_TEXTURE_PALETTIZE4_MM         = 0x0600
KM_TEXTURE_PALETTIZE8            = 0x0700
KM_TEXTURE_PALETTIZE8_MM         = 0x0800
KM_TEXTURE_RECTANGLE             = 0x0900
KM_TEXTURE_RECTANGLE_MM          = 0x0A00
KM_TEXTURE_STRIDE                = 0x0B00
KM_TEXTURE_STRIDE_MM             = 0x0C00
KM_TEXTURE_TWIDDLED_RECTANGLE    = 0x0D00
KM_TEXTURE_BMP                   = 0x0E00
KM_TEXTURE_BMP_MM                = 0x0F00

KM_TEXTURE_ARGB1555 = 0x00
KM_TEXTURE_RGB565   = 0x01
KM_TEXTURE_ARGB4444 = 0x02
KM_TEXTURE_YUV422   = 0x03
KM_TEXTURE_BUMP     = 0x04
KM_TEXTURE_RGB555   = 0x05
KM_TEXTURE_YUV420   = 0x06


class PIXEL_FORMAT:
    PIX_1555    = 0
    PIX_565     = 1
    PIX_4444    = 2
    PIX_YUV422  = 3
    PIX_BUMP_MAP= 4
    PIX_4_PAL   = 5
    PIX_8_PAL   = 6
    PIX_AUTO    = 7

PSTA_ZERO_MODEL  = 0
PSTA_NOT_LIGHT   = 1
PSTA_USE_ENVMAP  = 2
PSTA_USE_PALETTO = 3
PSTA_USE_BUMP    = 4

class MAT_CONTEXT:

    def __init__(self):
        self._NL_PF_ListType: int = 0
        self._NL_PF_Volume: int = 0
        self._NL_PF_Col_Type: int = 0
        self._NL_PF_Texture: int = 0
        self._NL_PF_Offset: int = 0
        self._NL_PF_Gouraud: int = 0
        self._NL_PF_16bit_UV: int = 0

        # ISP_TSP_instruction
        self._NL_PF_DepthCompareMode: int = 0
        self._NL_PF_CullingMode: int = 0
        self._NL_PF_ZWriteDisable: int = 0
        self._NL_PF_Texture2: int = 0
        self._NL_PF_Offset2: int = 0
        self._NL_PF_Gouraud2: int = 0
        self._NL_PF_16bit_UV2: int = 0
        self._NL_PF_CacheBypass: int = 0
        self._NL_PF_DcalcCtrl: int = 0

        # TSP_instruction
        self._NL_PF_SRC_AlphaInstr: int = 0
        self._NL_PF_DST_AlphaInstr: int = 0
        self._NL_PF_SRC_Select: int = 0
        self._NL_PF_DST_Select: int = 0
        self._NL_PF_FogControl: int = 0
        self._NL_PF_ColorClamp: int = 0
        self._NL_PF_UseAlpha: int = 0
        self._NL_PF_IgnoreTexAlpha: int = 0
        self._NL_PF_FlipUV: int = 0
        self._NL_PF_ClampUV: int = 0
        self._NL_PF_FilterMode: int = 0
        self._NL_PF_SuperSampleTexture: int = 0
        self._NL_PF_MipMapD_adjust: int = 0
        self._NL_PF_TextureShadingInstr: int = 0
        self._NL_PF_TextureSize_U: int = 0
        self._NL_PF_TextureSize_V: int = 0

        self._NL_PF_MIP_Mapped: int = 0
        self._NL_PF_VQ_Compressed: int = 0
        self._NL_PF_PixelFormat: int = 0
        self._NL_PF_ScanOrder: int = 0
        self._NL_PF_StrideSelect: int = 0
        self._NL_PF_TextureAddress: int = 0

        self.cx: Std_Float = Std_Float()
        self.cy: Std_Float = Std_Float()
        self.cz: Std_Float = Std_Float()
        self.cr: Std_Float = Std_Float()

        self.texture_flag: int = 0
        self.pic_name: Optional[str] = None
        self.tex_id: int = -1
        self.tex_amb: Std_Float = Std_Float()

        self.face_color_alpha: Std_Float = Std_Float()
        self.face_color_R: Std_Float = Std_Float()
        self.face_color_G: Std_Float = Std_Float()
        self.face_color_B: Std_Float = Std_Float()
        self.face_offset_color_alpha: Std_Float = Std_Float()
        self.face_offset_color_R: Std_Float = Std_Float()
        self.face_offset_color_G: Std_Float = Std_Float()
        self.face_offset_color_B: Std_Float = Std_Float()

        self.palette_flag: int = 0
        self.pal_name: Optional[str] = None
        self.pal_direct_num: int = 0
        self.pal_direct_name: Optional[str] = None

        self.gouraud: int = 0
        self.strip_ct: int = 0
        self.all_point_count: int = 0
        self.once_ct: int = 0

class SAVE_ALL_STRIP:

    def __init__(self):
        self.list_type: int = 0
        self.use2para: bool = False

        self.mc: List[MAT_CONTEXT] = [MAT_CONTEXT(), MAT_CONTEXT()]

        self.mat_disp_count: int = 0
        self.mat_disp_buff: bytearray = bytearray(4096)
        self.mat_disp_end_count: int = 0
        self.mat_disp_end_buff: bytearray = bytearray(1024)

        self.skip_count: int = 0

        self.model: Optional["Std_Model"] = None
        self.mat_index: int = 0
        self.bump_polygon: bool = False
        self.bump_polygon_dup: bool = False
        self.bump_polygon_trs: bool = False
        self.env_map_polygon: bool = False
        self.super_index_format: bool = False

        self.add_count: int = 0
        self.add_count0: int = 0
        self.add_count2: int = 0

        self.all_strip_ct: int = 0
        self.all_once_ct: int = 0
        self.all_fan_ct: int = 0
        self.file_all_point_count: int = 0
        self.file_all_polygon_count: int = 0

        self.stripdata: Optional[StripData] = None

        self.next: Optional["SAVE_ALL_STRIP"] = None

# Global SAVE_ALL_STRIP list heads
save_all_strip_opq: Optional[SAVE_ALL_STRIP] = None
save_all_strip_trs: Optional[SAVE_ALL_STRIP] = None
save_all_strip_pch: Optional[SAVE_ALL_STRIP] = None

# Global address counter
naomi2hg_all_address: int = 0

class Std_Model:

    # ROT enum
    clock  = 0
    rclock = 1
    open_  = 0
    close_ = 1

    def __init__(self):
        self.outcalc: bool = False

        self.model_name: str = ""

        self.cx: float = 0.0
        self.cy: float = 0.0
        self.cz: float = 0.0
        self.cr: float = 0.0

        self.gouraud: bool = False
        self.discAngle: float = 0.0

        self.material_num: int = 0
        self.material: Optional[List[Std_Material]] = None

        self.cluster_num: int = 0
        self.cluster: Optional[List[Std_Cluster]] = None

        self.point_num: int = 0
        self.point_list: Optional[List[Std_Point]] = None

        self.polygon_num: int = 0
        self.polygon: Optional[List[Std_Polygon]] = None

        self.stripdata: Optional[StripData] = None
        self.model_all_strip_point_count: int = 0

        self.index_to_dma_address: Optional[List[int]] = None
        self.index_to_ram_address: Optional[List[int]] = None

        self.skip_count: int = 0

        self.DMA_ADRS: int = 0
        self.RAM_ADRS: int = 0

        self.smp: Optional[List[SAME_POINT]] = None
        self.add_count: int = 0
        self.add_count0: int = 0
        self.add_count2: int = 0

        self.point_normal_list: Optional[List[Std_Point]] = None


bump_polygon: bool = False

class Associate:
    """String-keyed associative map."""

    def __init__(self) -> None:
        self._data: dict = {}

    @staticmethod
    def _resolve_key(raw: str) -> str:
        if bump_polygon:
            return raw + "_bump"
        return raw

    def __getitem__(self, key: str):
        return self._data[self._resolve_key(key)]

    def __setitem__(self, key: str, value) -> None:
        self._data[self._resolve_key(key)] = value

    def __delitem__(self, key: str) -> None:
        del self._data[self._resolve_key(key)]

    def __contains__(self, key: str) -> bool:
        return self._resolve_key(key) in self._data

    def get(self, key: str, default=None):
        return self._data.get(self._resolve_key(key), default)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"Associate({self._data!r})"

# file_io

class FileRead:
    """Line-oriented binary file reader."""

    def __init__(self) -> None:
        self._fp = None
        self._buf: str = ""
        self._endflg: bool = False

    def open(self, filename: str) -> None:
        try:
            self._fp = open(filename, "rb")
        except OSError:
            raise RuntimeError(f"nlcv : file open error <{filename}>")
        self._buf = ""
        self._endflg = False

    def close(self) -> None:
        if self._fp is not None:
            self._fp.close()
            self._fp = None

    def readline(self) -> str:
        raw: bytes = self._fp.readline()
        if raw == b"":
            self._endflg = True
            self._buf = ""
        else:
            self._endflg = False
            self._buf = raw.decode("latin-1")
        return self._buf

    def line(self) -> str:
        return self._buf

    def end(self) -> bool:
        return self._endflg

    def delCR(self) -> None:
        if not self._endflg and self._buf:
            self._buf = self._buf.rstrip("\r\n")

    def __enter__(self) -> "FileRead":
        return self

    def __exit__(self, *_) -> None:
        self.close()

class FileWrite:
    """Line-oriented binary file writer."""

    def __init__(self) -> None:
        self._fp = None

    def open(self, filename: str) -> None:
        try:
            self._fp = open(filename, "wb")
        except OSError:
            raise RuntimeError(f"nlcv : file open error <{filename}>")

    def close(self) -> None:
        if self._fp is not None:
            self._fp.close()
            self._fp = None

    def writeline(self, w: str) -> int:
        data: bytes = w.encode("latin-1")
        self._fp.write(data)
        return len(data)

    def __enter__(self) -> "FileWrite":
        return self

    def __exit__(self, *_) -> None:
        self.close()


def strchk(p0: str, p1: str) -> int:
    """Return 0 if p0 starts with p1 (null-terminated style), else -1."""
    p1c = p1.rstrip('\x00')
    return 0 if p0.startswith(p1c) else -1

def srch_chrs(p: str, chrs: str) -> int:
    """Return index of first char in p that appears in chrs, or len(p)."""
    for i, c in enumerate(p):
        if c in chrs: return i
    return len(p)

def file_exist(fn: str) -> int:
    """Return 1 if the file exists and is readable, 0 otherwise."""
    try:
        with open(fn, "rb"):
            pass
        return 1
    except OSError:
        return 0

def file_size_name(fn: str) -> int:
    """Return the size in bytes of file fn."""
    try:
        return os.path.getsize(fn)
    except OSError:
        raise FileNotFoundError(f"'{fn}' file open error")

def _file_size(fp) -> int:
    """Return the size of an already-open binary file by seeking."""
    pos = fp.tell()
    fp.seek(0, 2)
    size = fp.tell()
    fp.seek(0, 0)
    return size

def auto_size_fread(fn: str) -> bytes:
    try:
        with open(fn, "rb") as fp:
            return fp.read()
    except OSError:
        raise FileNotFoundError(
            f"\nfile: '{fn}' not found. process aborted...\n"
        )

# Boolean-style int constants  (NMT_ON / NMT_OFF / NMT_TRUE / NMT_FALSE)
NMT_ON    = 1
NMT_OFF   = 0
NMT_TRUE  = 1
NMT_FALSE = 0

# Texture format codes  (bits 15-8 of the combined format word)
NM_TWIDDLED                  = 0x00000100
NM_TWIDDLED_MIPMAP           = 0x00000200
NM_TWIDDLED_VQ               = 0x00000300
NM_TWIDDLED_VQ_MIPMAP        = 0x00000400
NM_TWIDDLED_PALETTIZE4       = 0x00000500
NM_TWIDDLED_PALETTIZE4_MIPMAP = 0x00000600
NM_TWIDDLED_PALETTIZE8       = 0x00000700
NM_TWIDDLED_PALETTIZE8_MIPMAP = 0x00000800
NM_SCANORDER_RECTANGLE       = 0x00000900
NM_SCANORDER_RECTANGLE_MIPMAP = 0x00000A00    
NM_SCANORDER_STRIDE          = 0x00000B00
NM_SCANORDER_STRIDE_MIPMAP   = 0x00000C00     
NM_TWIDDLED_RECTANGLE        = 0x00000D00     
NM_TEXTURE_BMP               = 0x00000E00    
NM_TEXTURE_BMP_MIPMAP        = 0x00000F00     
NM_TWIDDLED_SMALLVQ          = 0x00001000
NM_TWIDDLED_SMALLVQ_MIPMAP   = 0x00001100

# Pixel format codes  (bits 7-0 of the combined format word)
NM_TEXTURE_ARGB1555 = 0x00000000
NM_TEXTURE_RGB565   = 0x00000001
NM_TEXTURE_ARGB4444 = 0x00000002
NM_TEXTURE_YUV422   = 0x00000003
NM_TEXTURE_BUMP     = 0x00000004
NM_TEXTURE_RGB555   = 0x00000005   
NM_TEXTURE_YUV420   = 0x00000006    
NM_TEXTURE_ARGB8888 = 0x00000007
# soft2naomi local definitions
NM_TEXTURE_4_PAL    = 0x00000008
NM_TEXTURE_8_PAL    = 0x00000009
NM_TEXTURE_AUTO     = 0x0000000a

# Format word masks
NM_TEXTURE_FORMATMASK = 0x0000ff00     # texture-format bits
NM_TEXTURE_PIXELMASK  = 0x000000ff     # pixel-format bits

# Chunk identifiers  (stored as 4-byte ASCII in PVR files)
NM_CHUNK_PVRT = b'PVRT'     # Kamui PVR texture chunk
NM_CHUNK_GBIX = b'GBIX'     # Global-index chunk

# Miscellaneous limits / tags
NM_TEX_STRING_MAX   = 512
TEXTURE_MAX_SIZE    = 1024             # maximum texture dimension
TEXTURE_HEADER_CHR  = "PVRT"          # texture header string (4 chars)

# Twiddle increment / mask constants
# Two variants in the original; the non-BUG_FIX variant is the
# production build used by this port.
INCREMENT_X_TWIDDLE = 0x55556
INCREMENT_Y_TWIDDLE = 0xAAAAB
X_TWIDDLE_MASK      = 0xAAAAA
Y_TWIDDLE_MASK      = 0x55555

# EXTMapOffset — mip-map level offsets for twiddled square textures.
# Index into this table by mip level (0 = 1×1 ... 10 = 1024×1024).
# Offsets are in units of unsigned short (2 bytes).
EXTMapOffset = (
    0x00001, 0x00002, 0x00006,
    0x00016, 0x00056, 0x00156,
    0x00556, 0x01556, 0x05556,
    0x15556, 0x55556,
)

# Byte-swap helpers
# These replace the L_SWAP / S_SWAP / FL_SWAP / FL_SWAP_RV
# and their *_UX aliases.  All operate on Python int values and
# return the swapped result (rather than writing through a pointer).

def l_swap(src: int) -> int:
    """Byte-swap a 32-bit unsigned integer."""
    src &= 0xFFFFFFFF
    return (
        ((src & 0x000000FF) << 24) |
        ((src & 0x0000FF00) <<  8) |
        ((src & 0x00FF0000) >>  8) |
        ((src & 0xFF000000) >> 24)
    )

def s_swap(src: int) -> int:
    """Byte-swap a 16-bit unsigned integer."""
    src &= 0xFFFF
    return ((src & 0x00FF) << 8) | ((src & 0xFF00) >> 8)

def fl_swap(src: float) -> int:
    """Byte-swap float bits → uint32."""
    raw, = struct.unpack('>I', struct.pack('>f', src))
    return l_swap(raw)

def fl_swap_rv(src: int) -> float:
    """Byte-swap uint32 bits → float."""
    swapped = l_swap(src)
    result, = struct.unpack('>f', struct.pack('>I', swapped))
    return result

# *_UX aliases — identical behaviour in this (non-big-endian) build


@dataclass
class TexPixel:
    """
    All channels are unsigned bytes (0–255).
    """
    alpha: int = 0
    red:   int = 0
    green: int = 0
    blue:  int = 0


@dataclass
class NmTexture:
    """
    `pixels` is a list of TexPixel rather than a raw pointer.
    """
    texture_type: int = 0             # kamui category code
    x_dim:        int = 0             # width  in pixels
    y_dim:        int = 0             # height in pixels
    pixels: list = field(default_factory=list)     # List[TexPixel]


@dataclass
class NmPvrHeader:
    """

    Layout on disk (all little-endian in the file; the C code reads
    individual bytes and reassembles in little-endian order):

        [0..3]   chunkname        — 'GBIX'
        [4..7]   chunksize        — uint32 LE  (always 4)
        [8..11]  global_index     — uint32 LE
        [12..15] kamui_identifier — 'PVRT'
        [16..19] pixel_size       — uint32 LE  (texture data size in bytes)
        [20..23] texture_type     — uint32 LE  (kamui category code)
        [24..25] width            — uint16 LE
        [26..27] height           — uint16 LE
    """
    chunkname:        bytes = b'\x00\x00\x00\x00'     # 4 chars, e.g. b'GBIX'
    chunksize:        int   = 0                         # uint32
    global_index:     int   = 0                         # uint32
    kamui_identifier: bytes = b'\x00\x00\x00\x00'     # 4 chars, e.g. b'PVRT'
    pixel_size:       int   = 0                         # uint32
    texture_type:     int   = 0                         # uint32
    width:            int   = 0                         # uint16
    height:           int   = 0                         # uint16


@dataclass
class NmPalHeader:
    """

        [0..3]   chunkname     — 'PALT'
        [4..7]   palette_size  — uint32 LE
        [8..11]  palette_color — uint32 LE
        [12..15] pixel_format  — uint32 LE
    """
    chunkname:     bytes = b'\x00\x00\x00\x00'
    palette_size:  int   = 0
    palette_color: int   = 0
    pixel_format:  int   = 0


@dataclass
class NmPalInfo:
    """
    `pixels` is a list of uint32 palette entries.
    """
    info:   NmPalHeader = field(default_factory=NmPalHeader)
    pixels: list = field(default_factory=list)     # List[int]


@dataclass
class NmPvrconvInfo:
    """
    """
    texture_format: int = 0
    pixel_format:   int = 0
    width:          int = 0
    height:         int = 0
    global_index:   int = 0
    mipmap:         int = NMT_OFF
    in_filename:    str = ""      # max NM_TEX_STRING_MAX chars
    out_filename:   str = ""      # path + filename

# Private I/O helpers
# Instead of writing through a pointer they return (success, value).

def _fread_1byte(fp) -> "tuple[bool, int]":
    """Read 1 byte from fp.  Returns (ok, value)."""
    data = fp.read(1)
    if len(data) < 1:
        return False, 0
    return True, data[0]

def _fread_2byte(fp) -> "tuple[bool, int]":
    """Read 2 LE bytes from fp → (ok, uint16)."""
    d = fp.read(2)
    if len(d) < 2: return False, 0
    return True, d[0] | (d[1] << 8)

def _fread_4byte(fp) -> "tuple[bool, int]":
    """Read 4 LE bytes from fp → (ok, uint32)."""
    d = fp.read(4)
    if len(d) < 4: return False, 0
    return True, d[0] | (d[1] << 8) | (d[2] << 16) | (d[3] << 24)


def pvr_information(filename: str, texinfo: NmPvrHeader) -> int:
    """Read PVR file header from *filename* into *texinfo*. Returns NMT_TRUE on success."""
    try:
        fp = open(filename, "rb")
    except OSError:
        return NMT_FALSE

    with fp:
        raw = fp.read(28)
        if len(raw) < 28:
            return NMT_FALSE
        # Layout: 4s I I 4s I I H H  (all little-endian)
        (texinfo.chunkname, texinfo.chunksize, texinfo.global_index,
         texinfo.kamui_identifier, texinfo.pixel_size, texinfo.texture_type,
         texinfo.width, texinfo.height) = struct.unpack_from('<4sII4sIIHH', raw)

    return NMT_TRUE

# Correctly-spelled public alias


def read_palette_header(filename: str, pal_p: NmPalInfo) -> int:
    """Read palette chunk header from *filename* into *pal_p*. Returns NMT_TRUE on success."""
    try:
        fp = open(filename, "rb")
    except OSError:
        return NMT_FALSE

    with fp:
        raw = fp.read(16)
        if len(raw) < 16:
            return NMT_FALSE
        # Layout: 4s I I I  (all little-endian)
        (pal_p.info.chunkname, pal_p.info.palette_size,
         pal_p.info.palette_color, pal_p.info.pixel_format) = struct.unpack_from('<4sIII', raw)

    return NMT_TRUE


DK_MAT_CONSTANT = 1
DK_MAT_FLAT     = 2
DK_MAT_LAMBERT  = 3
DK_MAT_PHONG    = 4
DK_MAT_BLINN    = 5
DK_MAT_SHADOW   = 6

# Texture effect constants
DK_TXT_ALPHA     = 1
DK_TXT_INTENSITY = 2
DK_TXT_NO_MASK   = 3

# Pixel-format constants
PIX_1555   = 0
PIX_565    = 1
PIX_4444   = 2
PIX_YUV422 = 3
PIX_BUMP_MAP = 4
PIX_4_PAL  = 5
PIX_8_PAL  = 6
PIX_AUTO   = 7


LIST_NON    = -1
LIST_OPQ    = 0
LIST_OPQ_MOD = 1
LIST_TRS    = 2
LIST_TRS_MOD = 3
LIST_PUNCH  = 4


TRI_LINER_NON      = 0
TRI_LINER_PASS_A   = 1
TRI_LINER_PASS_B   = 2
TRI_LINER_TRS_LAST = 3


# Strip accumulator lists
save_all_strip_opq: Optional[SAVE_ALL_STRIP] = None
save_all_strip_trs: Optional[SAVE_ALL_STRIP] = None
save_all_strip_pch: Optional[SAVE_ALL_STRIP] = None

# Per-material polygon-index cache  (built once per model)
g_matidx_model: Optional[Std_Model] = None
g_matidx_flat:  List[int] = []
g_matidx_off:   List[int] = []
g_matidx_cnt:   List[int] = []
g_matidx_matnum: int = 0

# Texture size globals  (set inside naomi_format_type_2_7_main_setmat)
tex_size_u: float = 0.0
tex_size_v: float = 0.0

# Bump-map state flags
bump_polygon:     bool = False
bump_polygon_dup: bool = False
bump_polygon_trs: bool = False

# Env-map flag
env_map_polygon: bool = False

# Tri-liner (bilinear) mode
tri_liner_mode: int = TRI_LINER_NON

# Model bounding-sphere  (whole scene)
mcx: Std_Float = Std_Float(0.0)
mcy: Std_Float = Std_Float(0.0)
mcz: Std_Float = Std_Float(0.0)
mcr: Std_Float = Std_Float(0.0)

# The loaded model array
StdModel: List[Std_Model] = []
StdModelCount: int = 0

# Previous-strip colour state  (used for same_color optimisation)
before_List_Type: int = LIST_NON

before_face_A: float = -1.0
before_face_R: float = -1.0
before_face_G: float = -1.0
before_face_B: float = -1.0

before_offset_A: float = -1.0
before_offset_R: float = -1.0
before_offset_G: float = -1.0
before_offset_B: float = -1.0

send_gp_count:      int = 0
object_all_address: int = 0

# mat_printf destination mode
#   0 = direct stdout,  1 = before-buffer,  2 = end-buffer
mat_disp_mode: int = 0
mat_disp_target: Optional[SAVE_ALL_STRIP] = None

# after_output_* state  (written by naomi_format_type_2_7 when
# output_after_all is True, consumed by all_put_strip_point)
after_output_sta:               int = 0
after_output_nullmodel:         bool = False
after_output_super_index_format: bool = False
after_output_mcx: Std_Float = Std_Float(0.0)
after_output_mcy: Std_Float = Std_Float(0.0)
after_output_mcz: Std_Float = Std_Float(0.0)
after_output_mcr: Std_Float = Std_Float(0.0)
after_output_name: str = ""

# We keep copies here initialised to 0; the caller is responsible for
# module that owns them).
all_strip_ct:          int = 0
all_fan_ct:            int = 0
all_once_ct:           int = 0
before_srch_point_count: int = 0
file_all_point_count:  int = 0
file_all_polygon_count: int = 0
max_s_index_ct:        int = 0
put_point_all:         int = 0
put_repoint_all:       int = 0

# Option globals

# output control
output_after_all:  bool = False
naomi2hg:          bool = False
super_index_format: bool = False

# geometry
allScale:          float = 1.0

# material / colour
all_flat:          bool = False
bump_offset:       float = -1.0
bump_white_keisuu: float = -1.0

# texture / path
texpath:    List[str] = []
texpath_count: int = 0
palpath:    List[str] = []
palpath_count: int = 0
texoutpath: str = ""
adjust_uv:  bool = False

# geometry processing
merge_rate:       float = 0.1
uncond_merge_rad: float = 3.0
div_convex:       bool = False
div_concave:      bool = False

# file name
input_file_name_base: str = ""

def _apply_options_ro(opts) -> None:
    global output_after_all
    global naomi2hg, super_index_format
    global allScale
    global all_flat
    global bump_offset, bump_white_keisuu
    global palpath, palpath_count, texoutpath
    global adjust_uv
    global merge_rate, uncond_merge_rad
    global div_convex
    global div_concave
    global input_file_name_base

    output_after_all     = getattr(opts, "output_after_all",     False)
    naomi2hg             = getattr(opts, "naomi2hg",              False)
    super_index_format   = getattr(opts, "super_index_format",   False)
    allScale             = getattr(opts, "all_scale",             1.0)
    all_flat             = getattr(opts, "all_flat",              False)
    bump_offset          = getattr(opts, "bump_offset",          -1.0)
    bump_white_keisuu    = getattr(opts, "bump_white_keisuu",    -1.0)
    texpath              = list(getattr(opts, "texpath",          []))
    texpath_count        = getattr(opts, "texpath_count",         0)
    palpath              = list(getattr(opts, "palpath",          []))
    palpath_count        = getattr(opts, "palpath_count",         0)
    texoutpath           = getattr(opts, "texoutpath",            "")
    adjust_uv            = getattr(opts, "adjust_uv",             False)
    merge_rate           = getattr(opts, "merge_rate",             0.1)
    uncond_merge_rad     = getattr(opts, "uncond_merge_rad",       3.0)
    div_convex           = getattr(opts, "div_convex",             False)
    div_concave          = getattr(opts, "div_concave",            False)
    input_file_name_base = getattr(opts, "input_file_name_base",   "")


# Binary output channel  — write one little-endian 32-bit word
_binary_out: Optional[io.RawIOBase] = None

def write_le32(value: int) -> None:
    if _binary_out is not None:
        _binary_out.write(struct.pack("<I", value & 0xFFFFFFFF))

def set_binary_output(stream: Optional[io.RawIOBase]) -> None:
    global _binary_out
    _binary_out = stream


def debug_std_disp() -> None:
    """Dump the loaded model/material/polygon hierarchy to stdout."""
    for i in range(StdModelCount):
        m = StdModel[i]

        for j in range(m.material_num):
            mat = m.material[j]

        for j in range(m.point_num):
            pt = m.point_list[j]

        for j in range(m.polygon_num):
            poly = m.polygon[j]
            for k in range(poly.info_list_num):
                inf = poly.info_list[k]


def get_model_culling_all(
    cx_out=None, cy_out=None, cz_out=None, cr_out=None
) -> None:
    """Compute the bounding sphere of the entire scene and write the"""
    global mcx, mcy, mcz, mcr
    import math

    if StdModelCount == 0:
        mcx = Std_Float(0.0); mcy = Std_Float(0.0)
        mcz = Std_Float(0.0); mcr = Std_Float(0.0)
        return

    found = False
    max_x = max_y = max_z = 0.0
    min_x = min_y = min_z = 0.0

    for i in range(StdModelCount):
        if StdModel[i].point_num != 0:
            pt0 = StdModel[i].point_list[0]
            max_x = min_x = float(pt0.x)
            max_y = min_y = float(pt0.y)
            max_z = min_z = float(pt0.z)
            found = True
            break

    if not found:
        cx_out[0] = cy_out[0] = cz_out[0] = cr_out[0] = 0.0
        return

    for i in range(StdModelCount):
        for j in range(StdModel[i].point_num):
            pt = StdModel[i].point_list[j]
            x, y, z = float(pt.x), float(pt.y), float(pt.z)
            if max_x < x: max_x = x
            if max_y < y: max_y = y
            if max_z < z: max_z = z
            if min_x > x: min_x = x
            if min_y > y: min_y = y
            if min_z > z: min_z = z

    ccx = (max_x + min_x) * 0.5
    ccy = (max_y + min_y) * 0.5
    ccz = (max_z + min_z) * 0.5

    ccr2 = 0.0
    for i in range(StdModelCount):
        for j in range(StdModel[i].point_num):
            pt = StdModel[i].point_list[j]
            x, y, z = float(pt.x), float(pt.y), float(pt.z)
            rr2 = (x - ccx)**2 + (y - ccy)**2 + (z - ccz)**2
            if rr2 > ccr2:
                ccr2 = rr2

    ccr = math.sqrt(ccr2)

    # Coordinate-system adjustments

    mcx = Std_Float(ccx)
    mcy = Std_Float(ccy)
    mcz = Std_Float(ccz)
    mcr = Std_Float(ccr)


def get_model_culling() -> None:
    """Compute individual bounding spheres for each model and store"""
    import math

    for i in range(StdModelCount):
        m = StdModel[i]
        if m.point_num == 0:
            continue

        pt0 = m.point_list[0]
        max_x = min_x = float(pt0.x)
        max_y = min_y = float(pt0.y)
        max_z = min_z = float(pt0.z)

        for j in range(m.point_num):
            pt = m.point_list[j]
            x, y, z = float(pt.x), float(pt.y), float(pt.z)
            if max_x < x: max_x = x
            if max_y < y: max_y = y
            if max_z < z: max_z = z
            if min_x > x: min_x = x
            if min_y > y: min_y = y
            if min_z > z: min_z = z

        ccx = (max_x + min_x) * 0.5
        ccy = (max_y + min_y) * 0.5
        ccz = (max_z + min_z) * 0.5

        m.cx = ccx
        m.cy = ccy
        m.cz = ccz

        ccr2 = 0.0
        for j in range(m.point_num):
            pt = m.point_list[j]
            x, y, z = float(pt.x), float(pt.y), float(pt.z)
            rr2 = (x - ccx)**2 + (y - ccy)**2 + (z - ccz)**2
            if rr2 > ccr2:
                ccr2 = rr2

        m.cr = math.sqrt(ccr2)


def get_color(i: int, j: int):
    mat = StdModel[i].material[j]
    tex = 1 if mat.pic_name else 0

    oa = 0.0
    fa = 1.0 - mat.trs

    if tex == 1 and mat.blend == 1.0:
        fr = fg = fb = 1.0
    else:
        fr = float(mat.dif_R)
        fg = float(mat.dif_G)
        fb = float(mat.dif_B)

    if True:
        or_ = float(mat.spc_R)
        og  = float(mat.spc_G)
        ob  = float(mat.spc_B)
    else:
        or_ = og = ob = 0.0

    return fa, fr, fg, fb, oa, or_, og, ob


def mat_printf(fmt: str, *args) -> int:
    """Formatted diagnostic/comment writer."""
    text = (fmt % args) if args else fmt
    v = len(text)

    if not output_after_all:
        return 0

    if mat_disp_mode == 0:
        return 0

    if mat_disp_mode == 1:
        if mat_disp_target is not None:
            if not hasattr(mat_disp_target, "_mat_disp_strs"):
                mat_disp_target._mat_disp_strs = []
            mat_disp_target._mat_disp_strs.append(text)
            mat_disp_target.mat_disp_count += v
        return v

    if mat_disp_mode == 2:
        if mat_disp_target is not None:
            if not hasattr(mat_disp_target, "_mat_disp_end_strs"):
                mat_disp_target._mat_disp_end_strs = []
            mat_disp_target._mat_disp_end_strs.append(text)
            mat_disp_target.mat_disp_end_count += v
        return v

    return 0


_TEX_SIZE_MAP = {8: 0, 16: 1, 32: 2, 64: 3, 128: 4, 256: 5,
                 512: 6, 1024: 7}

def _encode_tex_size(dim: int, axis: str, pic_name: str) -> int:
    """Map a texture dimension (pixels) to the 3-bit hardware code."""
    code = _TEX_SIZE_MAP.get(dim)
    if code is None:
        return 0
    return code


def naomi_format_type_2_7_main_setmat(
    stdmdl: Std_Model,
    stdmat: Std_Material,
    v0mat_index: int,
    v2para: int,
    tex0_out: list,
    mat_poly_num_out: list,   # one-element list  pnum
    sas0_out: list,
) -> None:
    """Set up material parameters for one polygon group and emit the"""
    global mat_disp_mode, mat_disp_target
    global before_face_A, before_face_R, before_face_G, before_face_B
    global before_offset_A, before_offset_R, before_offset_G, before_offset_B
    global before_List_Type
    global tex_size_u, tex_size_v
    global object_all_address

    mat_disp_mode = 0

    # Count polygons belonging to this material
    pnum0 = 0
    pnum  = 0

    if g_matidx_model is stdmdl and v0mat_index < g_matidx_matnum:
        # Fast path: use pre-built index
        cnt  = g_matidx_cnt[v0mat_index]
        base = g_matidx_off[v0mat_index]
        for k in range(cnt):
            jj = g_matidx_flat[base + k]
            pnum0 += 1
            s = stdmdl.polygon[jj]
            if   s.info_list_num == 4: pnum += 2
            elif s.info_list_num == 3: pnum += 1
    else:
        # Fallback O(polygon_num) scan
        for jj in range(stdmdl.polygon_num):
            if stdmdl.polygon[jj].material_index == v0mat_index:
                pnum0 += 1
                s = stdmdl.polygon[jj]
                if   s.info_list_num >= 5: pass
                elif s.info_list_num == 4: pnum += 2
                elif s.info_list_num == 3: pnum += 1

    if pnum == 0:
        return

    # Allocate / reuse SAVE_ALL_STRIP
    sas: Optional[SAVE_ALL_STRIP] = None
    if v2para == 0:
        if output_after_all:
            sas = SAVE_ALL_STRIP()
            if stdmat.Vol2para is not None:
                sas.use2para = True
    else:
        sas = sas0_out[0]

    mat_disp_mode   = 1
    mat_disp_target = sas

    if v2para == 0:
        mat_printf("/*---- model start %d : <%s> ----*/\n",
                   v0mat_index, stdmdl.model_name)

    # Determine texture presence, validate THD entry
    tex_err = False

    if not stdmat.pic_name and stdmat.tex_id < 0:
        tex = 0
    else:
        tex = 1

    # Determine list type (opaque / transparent / punch-through)
    trs: int
    if stdmat.trs == 0:
        trs = LIST_OPQ
    else:
        trs = LIST_TRS

    if stdmat.punch_through:
        trs = LIST_PUNCH

    vtx_trs = False

    # Vertex-colour alpha transparency check
    if stdmat.shading_type == 7 and trs != LIST_TRS:
        if g_matidx_model is stdmdl and v0mat_index < g_matidx_matnum:
            cnt2  = g_matidx_cnt[v0mat_index]
            base2 = g_matidx_off[v0mat_index]
            for k2 in range(cnt2):
                if vtx_trs:
                    break
                k = g_matidx_flat[base2 + k2]
                for l in range(stdmdl.polygon[k].info_list_num):
                    if stdmdl.polygon[k].info_list[l].vtx_color_A != 0xFF:
                        trs = LIST_TRS
                        vtx_trs = True
                        break
        else:
            found_vtx_trs = False
            for k in range(stdmdl.polygon_num):
                if found_vtx_trs:
                    break
                for l in range(stdmdl.polygon[k].info_list_num):
                    if stdmdl.polygon[k].material_index == v0mat_index:
                        if stdmdl.polygon[k].info_list[l].vtx_color_A != 0xFF:
                            trs = LIST_TRS
                            vtx_trs = True
                            found_vtx_trs = True
                            break

    if bump_polygon_trs:
        trs = LIST_TRS

    if (stdmat.effect == DK_TXT_ALPHA and
            stdmat.transpFct == -1.0):
        trs = LIST_TRS
        if stdmat.punch_through:
            trs = LIST_PUNCH

    if not (stdmat.src_alpha_instr == -1 and stdmat.dst_alpha_instr == -1):
        if not (stdmat.src_alpha_instr == 1 and stdmat.dst_alpha_instr == 0):
            trs = LIST_TRS

    tex2 = tex
    if tex == 0:
        tex2 = 1

    # TSP / ISP defaults
    sa      = 1
    da      = 0
    tsi     = tex
    alp     = 0
    uvFlip  = 0
    ignAlp  = getattr(stdmat, 'ignore_tex_alpha', 1)
    fog     = getattr(stdmat, 'fog_mode', 2)
    ofsColor = 1

    if tex == 0:
        tsi = 1

    if stdmat.shading_type == DK_MAT_LAMBERT:
        tsi = 1

    if stdmat.trs > 0 or vtx_trs:
        sa  = 4; da = 5; tsi = 3; alp = 1

    if stdmat.effect == DK_TXT_ALPHA and stdmat.transpFct == -1.0:
        sa = 4; da = 5; ignAlp = 0

    if (stdmat.shading_type == DK_MAT_CONSTANT and
            tex == 1 and stdmat.blend == 1.0 and stdmat.trs == 0):
        tsi = 1

    if not stdmat.fade:
        tsi = 0

    if stdmat.uAlternate != 0:
        uvFlip |= 1 << 1
    if stdmat.vAlternate != 0:
        uvFlip |= 1 << 0

    # Face and offset colours
    offset_A = Std_Float(0.0)

    face_A = Std_Float(1.0 - stdmat.trs)
    if bump_polygon_trs:
        face_A = Std_Float((1.0 - stdmat.trs) / 2.0)
        if naomi2hg:
            face_A = Std_Float(1.0)

    if tex == 1 and stdmat.blend == 1.0:
        face_R = Std_Float(1.0)
        face_G = Std_Float(1.0)
        face_B = Std_Float(1.0)
    else:
        face_R = Std_Float(float(stdmat.dif_R))
        face_G = Std_Float(float(stdmat.dif_G))
        face_B = Std_Float(float(stdmat.dif_B))

    if bump_polygon and stdmat.tsi_parameter == 2:
        face_R = Std_Float(0.0)
        face_G = Std_Float(0.0)
        face_B = Std_Float(0.0)

    if True:
        offset_A = Std_Float(0.0)
        offset_R = Std_Float(float(stdmat.spc_R))
        offset_G = Std_Float(float(stdmat.spc_G))
        offset_B = Std_Float(float(stdmat.spc_B))
    else:
        offset_R = Std_Float(0.0)
        offset_G = Std_Float(0.0)
        offset_B = Std_Float(0.0)

        if float(face_G)   > 1.0: face_G   = Std_Float(1.0)
        if float(face_B)   > 1.0: face_B   = Std_Float(1.0)
        if float(offset_R) > 1.0: offset_R = Std_Float(1.0)
        if float(offset_G) > 1.0: offset_G = Std_Float(1.0)
        if float(offset_B) > 1.0: offset_B = Std_Float(1.0)

    same_color = (
        float(face_A)   == before_face_A and
        float(face_R)   == before_face_R and
        float(face_G)   == before_face_G and
        float(face_B)   == before_face_B and
        float(offset_A) == before_offset_A and
        float(offset_R) == before_offset_R and
        float(offset_G) == before_offset_G and
        float(offset_B) == before_offset_B
    )

    if same_color:
        if before_List_Type != trs:
            same_color = False

    if not bump_polygon and stdmat.shading_type != 7:
        before_face_A   = float(face_A)
        before_face_R   = float(face_R)
        before_face_G   = float(face_G)
        before_face_B   = float(face_B)
        before_offset_A = float(offset_A)
        before_offset_R = float(offset_R)
        before_offset_G = float(offset_G)
        before_offset_B = float(offset_B)
        before_List_Type = trs
    else:
        same_color = False

    # Col_Type
    Col_Type = 2
    if same_color:
        Col_Type = 3
    if stdmat.shading_type == 7:
        Col_Type = 1
    if bump_polygon:
        Col_Type = 0
        offset_A = Std_Float(1.0)
        offset_R = Std_Float(bump_offset if bump_offset >= 0 else 0.0)
        offset_G = Std_Float(bump_white_keisuu if bump_white_keisuu >= 0
                              else 1.0)
        offset_B = Std_Float(0.0)

    _16bitUV = 0
    if tex == 0:
        _16bitUV = 1

    list_type = trs

    if trs == LIST_OPQ:
        if tri_liner_mode == TRI_LINER_PASS_B:
            Col_Type   = 2
            same_color = False
            list_type  = 2

    volume = 0
    if stdmat.shadow_effect:
        volume = 2

    cp_1v_0v = 0

    if output_after_all:
        if v2para == 0:
            sas.list_type = list_type
        else:
            if list_type == 0:
                pass
            elif list_type == 2:
                sas.list_type = list_type
                cp_1v_0v = 1
            else:
                if sas.list_type == 0:
                    sas.list_type = list_type
                    cp_1v_0v = 1

    # Emit parameter_control word
    if v2para == 0 and not output_after_all:
        mat_printf(
            "  (0x80000000)|\t/* global parameter && material continue */\n"
            "   (%d<<NL_PF_ListType)|(%d<<NL_PF_Volume)|(%d<<NL_PF_Col_Type)"
            "|(%d<<NL_PF_Texture)|\n"
            "    (%d<<NL_PF_Offset)|(%d<<NL_PF_Gouraud)|(%d<<NL_PF_16bit_UV),"
            " /* paramerter_control */\n\n",
            list_type, volume, Col_Type, tex2,
            ofsColor, 0, _16bitUV,
        )
        write_le32(
            0x80000000 |
            (list_type << NL_PF_ListType) |
            (volume    << NL_PF_Volume   ) |
            (Col_Type  << NL_PF_Col_Type ) |
            (tex2      << NL_PF_Texture  ) |
            (ofsColor  << NL_PF_Offset   ) |
            (0         << NL_PF_Gouraud  ) |
            (_16bitUV  << NL_PF_16bit_UV )
        )

    if output_after_all:
        if cp_1v_0v == 0:
            sas.mc[v2para]._NL_PF_ListType = list_type
        else:
            sas.mc[0]._NL_PF_ListType      = list_type
            sas.mc[v2para]._NL_PF_ListType = list_type
        sas.mc[v2para]._NL_PF_Volume    = volume
        sas.mc[v2para]._NL_PF_Col_Type  = Col_Type
        sas.mc[v2para]._NL_PF_Texture   = tex2
        sas.mc[v2para]._NL_PF_Offset    = ofsColor
        sas.mc[v2para]._NL_PF_Gouraud   = 0
        sas.mc[v2para]._NL_PF_16bit_UV  = _16bitUV

    # Emit ISP_TSP_instruction word
    depth = 4

    # CullingMode in the ISP/TSP material header is always 0

    if v2para == 0 and not output_after_all:
        mat_printf(
            "  (%d<<NL_PF_DepthCompareMode)|(%d<<NL_PF_CullingMode)"
            "|(%d<<NL_PF_ZWriteDisable)|\n"
            "   (%d<<NL_PF_Texture2)|(%d<<NL_PF_Offset2)"
            "|(%d<<NL_PF_Gouraud2)|(%d<<NL_PF_16bit_UV2)|\n"
            "    (%d<<NL_PF_CacheBypass)|(%d<<NL_PF_DcalcCtrl),"
            "\t/* ISP_TSP_instruction */\n\n",
            depth, 0, 0, tex2, ofsColor, 0, _16bitUV, 0, 0,
        )
        write_le32(
            (depth    << NL_PF_DepthCompareMode) |
            (0        << NL_PF_CullingMode      ) |
            (0        << NL_PF_ZWriteDisable    ) |
            (tex2     << NL_PF_Texture2         ) |
            (ofsColor << NL_PF_Offset2          ) |
            (0        << NL_PF_Gouraud2         ) |
            (_16bitUV << NL_PF_16bit_UV2        ) |
            (0        << NL_PF_CacheBypass      ) |
            (0        << NL_PF_DcalcCtrl        )
        )

    if output_after_all:
        if cp_1v_0v == 0:
            sas.mc[v2para]._NL_PF_DepthCompareMode = depth
        else:
            sas.mc[0]._NL_PF_DepthCompareMode      = depth
            sas.mc[v2para]._NL_PF_DepthCompareMode = depth
        sas.mc[v2para]._NL_PF_CullingMode   = 0
        sas.mc[v2para]._NL_PF_ZWriteDisable = 0
        sas.mc[v2para]._NL_PF_Texture2      = tex2
        sas.mc[v2para]._NL_PF_Offset2       = ofsColor
        sas.mc[v2para]._NL_PF_Gouraud2      = 0
        sas.mc[v2para]._NL_PF_16bit_UV2     = _16bitUV
        sas.mc[v2para]._NL_PF_CacheBypass   = 0
        sas.mc[v2para]._NL_PF_DcalcCtrl     = 0

    # Texture parameters (tu, tv, mipmap, scanOrder, vqCompressed, pixel)
    tu = tv = 0
    mipmap      = 0
    scanOrder   = 1
    vqCompressed = 0
    pixel       = 0

    _MM_TYPES = frozenset([
        KM_TEXTURE_TWIDDLED_MM, KM_TEXTURE_VQ_MM,
        KM_TEXTURE_PALETTIZE4_MM, KM_TEXTURE_PALETTIZE8_MM,
        KM_TEXTURE_RECTANGLE_MM, KM_TEXTURE_STRIDE_MM, KM_TEXTURE_BMP_MM,
    ])
    _TWIDDLE_TYPES = frozenset([
        KM_TEXTURE_TWIDDLED_MM, KM_TEXTURE_TWIDDLED,
        KM_TEXTURE_TWIDDLED_RECTANGLE,
    ])
    _VQ_TYPES = frozenset([KM_TEXTURE_VQ, KM_TEXTURE_VQ_MM])

    def _apply_thd_type(t_type: int, t_width: int, t_height: int,
                        vq_halve: bool = False) -> None:
        nonlocal tu, tv, mipmap, scanOrder, vqCompressed, pixel
        fmt = t_type & 0x0000FF00
        pix = t_type & 0x000000FF
        if fmt in _MM_TYPES:      mipmap = 1
        if fmt in _TWIDDLE_TYPES: scanOrder = 0
        if fmt in _VQ_TYPES:      vqCompressed = 1
        pixel = pix
        w = t_width
        h = t_height
        if vq_halve and vqCompressed:
            w = w // 2
            h = h // 2
        global tex_size_u, tex_size_v
        tex_size_u = float(t_width)
        tex_size_v = float(t_height)
        tu = _encode_tex_size(w, "u", stdmat.pic_name)
        tv = _encode_tex_size(h, "v", stdmat.pic_name)

    if tex == 1 and not tex_err:
        if bump_polygon:
            pixel = PIX_BUMP_MAP
        elif stdmat.pixel_format >= 0:
            pixel = stdmat.pixel_format

        if stdmat.mip_mapped > 0:
            mipmap = 1

        if stdmat.vq_compressed:
            vqCompressed = 1

        # 1=linear (stride/rectangle).  naomi_texCtrl.scanOrder is '0'
        scanOrder = int(bool(stdmat.scan_order))

        _tw = stdmat.tex_size_u
        _th = stdmat.tex_size_v
        if _tw > 0 and _th > 0:
            tex_size_u = float(_tw)
            tex_size_v = float(_th)
            _vq_halve = bool(vqCompressed)
            _enc_w = _tw // 2 if _vq_halve else _tw
            _enc_h = _th // 2 if _vq_halve else _th
            tu = _encode_tex_size(_enc_w, "u", stdmat.pic_name)
            tv = _encode_tex_size(_enc_h, "v", stdmat.pic_name)

    # Filter mode
    filter_mode: int = stdmat.filter_mode

    if tex == 0:
        filter_mode = 0

    src_select = 0
    dst_select = 0

    if trs == LIST_OPQ:
        if tri_liner_mode == TRI_LINER_PASS_A:
            sa = 1; da = 0; filter_mode = 2
        elif tri_liner_mode == TRI_LINER_PASS_B:
            sa = 1; da = 1; filter_mode = 3
    else:
        if tri_liner_mode == TRI_LINER_PASS_A:
            sa = 1; da = 0; filter_mode = 2
            src_select = 0; dst_select = 1
        elif tri_liner_mode == TRI_LINER_PASS_B:
            sa = 1; da = 1; filter_mode = 3
            src_select = 0; dst_select = 1
        elif tri_liner_mode == TRI_LINER_TRS_LAST:
            sa = 4; da = 5; filter_mode = 3
            src_select = 1; dst_select = 0

    if bump_polygon:
        ignAlp = 0
        sa = 4
        if bump_polygon_trs:
            da = 5; alp = 1; tsi = 1
            if naomi2hg:
                alp = 0; sa = 0; da = 4

    if (stdmat.tsi_parameter != -1 and not bump_polygon_dup):
        tsi = stdmat.tsi_parameter

    clamp          = (stdmat.clamp_u << 1) | stdmat.clamp_v
    super_sample_t = stdmat.super_sample_tex
    mipmap_d_adj   = stdmat.mipmap_d_adjust
    color_clamp    = 0

    if stdmat.color_clamp:
        color_clamp = 1

    if stdmat.src_alpha_instr >= 0: sa = stdmat.src_alpha_instr
    if stdmat.dst_alpha_instr >= 0: da = stdmat.dst_alpha_instr

    # Emit TSP_instruction word
    if v2para == 0 and not output_after_all:
        mat_printf(
            "  (%d<<NL_PF_SRC_AlphaInstr)|(%d<<NL_PF_DST_AlphaInstr)"
            "|(%d<<NL_PF_SRC_Select)|\n"
            "   (%d<<NL_PF_DST_Select)|(%d<<NL_PF_FogControl)"
            "|(%d<<NL_PF_ColorClamp)|(%d<<NL_PF_UseAlpha)|\n"
            "    (%d<<NL_PF_IgnoreTexAlpha)|(%d<<NL_PF_FlipUV)"
            "|(%d<<NL_PF_ClampUV)|(%d<<NL_PF_FilterMode)|\n"
            "     (%d<<NL_PF_SuperSampleTexture)|(%d<<NL_PF_MipMapD_adjust)"
            "|(%d<<NL_PF_TextureShadingInstr)|\n"
            "      (%d<<NL_PF_TextureSize_U)|(%d<<NL_PF_TextureSize_V),"
            " /* TSP_instruction */\n\n",
            sa, da, src_select, dst_select, fog, color_clamp,
            alp, ignAlp, uvFlip, clamp, filter_mode,
            super_sample_t, mipmap_d_adj, tsi, tu, tv,
        )
        write_le32(
            (sa           << NL_PF_SRC_AlphaInstr    ) |
            (da           << NL_PF_DST_AlphaInstr    ) |
            (src_select   << NL_PF_SRC_Select        ) |
            (dst_select   << NL_PF_DST_Select        ) |
            (fog          << NL_PF_FogControl        ) |
            (color_clamp  << NL_PF_ColorClamp        ) |
            (alp          << NL_PF_UseAlpha          ) |
            (ignAlp       << NL_PF_IgnoreTexAlpha    ) |
            (uvFlip       << NL_PF_FlipUV            ) |
            (clamp        << NL_PF_ClampUV           ) |
            (filter_mode  << NL_PF_FilterMode        ) |
            (super_sample_t << NL_PF_SuperSampleTexture) |
            (mipmap_d_adj << NL_PF_MipMapD_adjust    ) |
            (tsi          << NL_PF_TextureShadingInstr) |
            (tu           << NL_PF_TextureSize_U     ) |
            (tv           << NL_PF_TextureSize_V     )
        )

    if output_after_all:
        mc = sas.mc[v2para]
        mc._NL_PF_SRC_AlphaInstr     = sa
        mc._NL_PF_DST_AlphaInstr     = da
        mc._NL_PF_SRC_Select         = src_select
        mc._NL_PF_DST_Select         = dst_select
        mc._NL_PF_FogControl         = fog
        mc._NL_PF_ColorClamp         = color_clamp
        mc._NL_PF_UseAlpha           = alp
        mc._NL_PF_IgnoreTexAlpha     = ignAlp
        mc._NL_PF_FlipUV             = uvFlip
        mc._NL_PF_ClampUV            = clamp
        mc._NL_PF_FilterMode         = filter_mode
        mc._NL_PF_SuperSampleTexture = super_sample_t
        mc._NL_PF_MipMapD_adjust     = mipmap_d_adj
        mc._NL_PF_TextureShadingInstr = tsi
        mc._NL_PF_TextureSize_U      = tu
        mc._NL_PF_TextureSize_V      = tv

    if stdmat.scan_order:
        scanOrder = stdmat.scan_order

    # Emit texture_control word
    if v2para == 0 and not output_after_all:
        mat_printf(
            "  (%d<<NL_PF_MIP_Mapped)|(%d<<NL_PF_VQ_Compressed)"
            "|(%d<<NL_PF_PixelFormat)|\n"
            "   (%d<<NL_PF_ScanOrder)|(%d<<NL_PF_StrideSelect)"
            "|(%d<<NL_PF_TextureAddress), /* texture_control */\n\n",
            mipmap, vqCompressed, pixel, scanOrder, 0, 0,
        )
        write_le32(
            (mipmap       << NL_PF_MIP_Mapped    ) |
            (vqCompressed << NL_PF_VQ_Compressed ) |
            (pixel        << NL_PF_PixelFormat   ) |
            (scanOrder    << NL_PF_ScanOrder     ) |
            (0            << NL_PF_StrideSelect  ) |
            (0            << NL_PF_TextureAddress)
        )

    if output_after_all:
        mc = sas.mc[v2para]
        mc._NL_PF_MIP_Mapped     = mipmap
        mc._NL_PF_VQ_Compressed  = vqCompressed
        mc._NL_PF_PixelFormat    = pixel
        mc._NL_PF_ScanOrder      = scanOrder
        mc._NL_PF_StrideSelect   = 0
        mc._NL_PF_TextureAddress = 0

    # Bounding sphere for this material group
    cx_l = Std_Float(0.0); cy_l = Std_Float(0.0); cz_l = Std_Float(0.0); cr_l = Std_Float(0.0)
    stdmdl.get_center_pos_R(v0mat_index, cx_l, cy_l, cz_l, cr_l)
    cx = Std_Float(float(cx_l) * allScale)
    cy = Std_Float(float(cy_l) * allScale)
    cz = Std_Float(float(cz_l) * allScale)
    cr = Std_Float(float(cr_l) * allScale)

    if v2para == 0 and not output_after_all:
        mat_printf(
            "  0x%08x,0x%08x,0x%08x,0x%08x,"
            "\t/* center(%f,%f,%f) and radius(%f) */\n\n",
            cx.hex(), cy.hex(), cz.hex(), cr.hex(),
            float(cx), float(cy), float(cz), float(cr),
        )
        write_le32(cx.hex())
        write_le32(cy.hex())
        write_le32(cz.hex())
        write_le32(cr.hex())

    if output_after_all:
        mc = sas.mc[v2para]
        mc.cx = cx; mc.cy = cy; mc.cz = cz; mc.cr = cr
        mc.pic_name = stdmat.pic_name
        mc.tex_amb  = stdmat.tex_amb

    if stdmat.tex_id >= 0 or (tex == 1 and not tex_err):
        if output_after_all:
            sas.mc[v2para].texture_flag = 1
            sas.mc[v2para].tex_id = stdmat.tex_id

        if v2para == 0 and not output_after_all:
            mat_printf("  TexID_%03d,\t/* tex_pvf_index */\n\n",
                       stdmat.tex_id)
            write_le32(stdmat.tex_id)

        if not bump_polygon:
            if   stdmat.shading_type == 7:
                shading_word = -3
                if v2para == 0:
                    mat_printf("  %d,\t\t/* vertex color */\n\n", -3)
            elif stdmat.shading_type == DK_MAT_PHONG:
                shading_word = int(stdmat.exp)
                if v2para == 0:
                    mat_printf("  %d,\t\t/* specular counter */\n\n",
                               shading_word)
            elif stdmat.shading_type == DK_MAT_CONSTANT:
                shading_word = -1
                if v2para == 0:
                    mat_printf("  %d,\t\t/* constant */\n\n", -1)
            else:
                shading_word = 0
                if v2para == 0:
                    mat_printf("  %d,\t\t/* lambert */\n\n", 0)
            if v2para == 0 and not output_after_all:
                write_le32(shading_word & 0xFFFFFFFF)
        else:
            if v2para == 0 and not output_after_all:
                mat_printf("  %d,\t\t/* bump shading */\n\n", -2)
                write_le32((-2) & 0xFFFFFFFF)

        if same_color:
            tex_amb_word = stdmat.tex_amb.hex() | 1
            if v2para == 0:
                mat_printf("  0x%08x,\t\t/* tex ambient (%f) && same_color */\n\n",
                           tex_amb_word, float(stdmat.tex_amb))
        else:
            tex_amb_word = stdmat.tex_amb.hex() & ~1
            if v2para == 0:
                mat_printf("  0x%08x,\t\t/* tex ambient (%f) && new_color */\n\n",
                           tex_amb_word, float(stdmat.tex_amb))
        if v2para == 0 and not output_after_all:
            write_le32(tex_amb_word & 0xFFFFFFFF)

    else:
        if output_after_all:
            sas.mc[v2para].texture_flag = 0

        if v2para == 0 and not output_after_all:
            if stdmat.tex_id >= 0:
                mat_printf("  TexID_%03d,\t/* tex_pvf_index */\n\n", stdmat.tex_id)
                write_le32(stdmat.tex_id)
            else:
                mat_printf("  -1,\t\t/* tex_pvf_index non tex dummy */\n\n")
                write_le32(0xFFFFFFFF)

        if not bump_polygon:
            if   stdmat.shading_type == 7:
                sw2 = -3
                if v2para == 0: mat_printf("  %d,\t\t/* vertex color */\n\n", -3)
            elif stdmat.shading_type == DK_MAT_PHONG:
                sw2 = int(stdmat.exp)
                if v2para == 0:
                    mat_printf("  %d,\t\t/* specular counter */\n\n", sw2)
            elif stdmat.shading_type == DK_MAT_CONSTANT:
                sw2 = -1
                if v2para == 0: mat_printf("  %d,\t\t/* constant */\n\n", -1)
            else:
                sw2 = 0
                if v2para == 0: mat_printf("  %d,\t\t/* lambert */\n\n", 0)
            if v2para == 0 and not output_after_all:
                write_le32(sw2 & 0xFFFFFFFF)
        else:
            if v2para == 0 and not output_after_all:
                mat_printf("  %d,\t\t/* bump shading */\n\n", -2)
                write_le32((-2) & 0xFFFFFFFF)

        if same_color:
            tab2 = stdmat.tex_amb.hex() | 1
            if v2para == 0:
                mat_printf("  0x%08x,\t\t/* tex ambient (%f) && same_color */\n\n",
                           tab2, float(stdmat.tex_amb))
        else:
            tab2 = stdmat.tex_amb.hex() & ~1
            if v2para == 0:
                mat_printf("  0x%08x,\t\t/* tex ambient (%f) && new_color */\n\n",
                           tab2, float(stdmat.tex_amb))
        if v2para == 0 and not output_after_all:
            write_le32(tab2 & 0xFFFFFFFF)

    if output_after_all:
        mc = sas.mc[v2para]
        mc.face_color_alpha        = face_A
        mc.face_color_R            = face_R
        mc.face_color_G            = face_G
        mc.face_color_B            = face_B

    if v2para == 0 and not output_after_all:
        mat_printf("  /*-1,-1,*/\t\t/* ignored */\n")
        mat_printf("  /*0x%08x,*/\t/* data_size_for_sort_DMA */\n", 0)
        mat_printf("  /*0x%08x,*/\t/* next_address_for_sort_DMA */\n", 0)
        mat_printf("  0x%08x,\t/* (%f) face_color_alpha */",
                   face_A.hex(), float(face_A))
        mat_printf("\n")
        mat_printf("  0x%08x,\t/* (%f) face_color_R */\n",
                   face_R.hex(), float(face_R))
        mat_printf("  0x%08x,\t/* (%f) face_color_G */\n",
                   face_G.hex(), float(face_G))
        mat_printf("  0x%08x,\t/* (%f) face_color_B */\n",
                   face_B.hex(), float(face_B))
        write_le32(face_A.hex())
        write_le32(face_R.hex())
        write_le32(face_G.hex())
        write_le32(face_B.hex())

    if output_after_all:
        sas.mc[v2para].palette_flag = 0

    if (not bump_polygon and
            stdmat.pixel_format in (PIX_4_PAL, PIX_8_PAL)):
        pl = stdmat.pal_name
        # Detect direct-mode palette spec  "N,name"
        mode = 0
        if pl and pl[0].isdigit() and "," in pl:
            mode = 1

        if mode == 0:
            if v2para == 0 and not output_after_all:
                mat_printf("  NL_PAL_NAME( %s ),\t/* palette index */\n",
                           stdmat.pal_name)
                write_le32(0)
            if output_after_all:
                sas.mc[v2para].pal_name    = stdmat.pal_name
                sas.mc[v2para].palette_flag = 1
        else:
            comma_pos = pl.index(",")
            num = int(pl[:comma_pos])
            pl_tail = pl[comma_pos + 1:]
            if v2para == 0 and not output_after_all:
                mat_printf("  %d,\t/* direct palette mode (%s)*/\n",
                           num, pl_tail)
                write_le32(num & 0xFFFFFFFF)
            if output_after_all:
                sas.mc[v2para].pal_direct_num  = num
                sas.mc[v2para].pal_direct_name = pl_tail
                sas.mc[v2para].palette_flag    = 2
    else:
        if v2para == 0 and not output_after_all:
            mat_printf("  0x%08x,\t/* (%f) face_offset_color_alpha */\n",
                       offset_A.hex(), float(offset_A))
            write_le32(offset_A.hex())

    if v2para == 0 and not output_after_all:
        mat_printf("  0x%08x,\t/* (%f) face_offset_color_R */\n",
                   offset_R.hex(), float(offset_R))
        mat_printf("  0x%08x,\t/* (%f) face_offset_color_G */\n",
                   offset_G.hex(), float(offset_G))
        mat_printf("  0x%08x,\t/* (%f) face_offset_color_B */\n",
                   offset_B.hex(), float(offset_B))
        mat_printf("  /* (%d) all polygon num */\n\n", pnum0)
        write_le32(offset_R.hex())
        write_le32(offset_G.hex())
        write_le32(offset_B.hex())

    if output_after_all:
        mc = sas.mc[v2para]
        mc.face_offset_color_alpha = offset_A
        mc.face_offset_color_R     = offset_R
        mc.face_offset_color_G     = offset_G
        mc.face_offset_color_B     = offset_B

    # Write-back out parameters
    tex0_out[0]         = tex
    mat_poly_num_out[0] = pnum
    sas0_out[0]         = sas


def naomi_format_type_2_7_main(i: int, j: int) -> None:
    global bump_polygon, bump_polygon_dup, bump_polygon_trs
    global super_index_format, tri_liner_mode

    if StdModel[i].material[j].same_flag:
        return

    tex  = VOL2_TEX_FLAG()
    tex.v0 = tex.v1 = 0
    pnum = [0]
    sas  = [None]

    tex0_out = [tex.v0]
    naomi_format_type_2_7_main_setmat(
        StdModel[i], StdModel[i].material[j],
        j, 0,
        tex0_out, pnum, sas,
    )
    tex.v0 = tex0_out[0]

    if pnum[0] == 0:
        return

    if StdModel[i].material[j].Vol2para is not None:
        tex1_out = [tex.v1]
        naomi_format_type_2_7_main_setmat(
            StdModel[i],
            StdModel[i].material[j].Vol2para,
            j, 1,
            tex1_out, pnum, sas,
        )
        tex.v1 = tex1_out[0]

    StdModel[i].set_strip_point(j, pnum[0], tex)
    StdModel[i].put_strip_point(j, sas[0])

    mat_disp_mode   = 2
    mat_disp_target = sas[0]

    mat_printf("/*---- model end %d : <%s> ----*/\n",
               j, StdModel[i].model_name)


def chk_polygon_status() -> int:
    """Scan all models and return a bitmask of polygon-status flags."""
    pol_zero  = False
    not_light = True
    env_map   = False
    palette   = False
    bump_map  = False
    n         = 0

    for i in range(StdModelCount):
        for j in range(StdModel[i].material_num):
            n += StdModel[i].polygon_num
            sd = StdModel[i].material[j].shading_type
            if sd not in (0, 1, 7):
                not_light = False

            bump = (StdModel[i].material[j].bump_map |
                    StdModel[i].material[j].auto_bump_map_generate)
            if bump:
                not_light = False
                bump_map  = True

            if StdModel[i].material[j].env_map:
                env_map = True

            pix = StdModel[i].material[j].pixel_format
            if pix in (PIX_4_PAL, PIX_8_PAL):
                palette = True

    if n == 0:
        pol_zero = True

    ret  = 0
    ret |= int(pol_zero)  << PSTA_ZERO_MODEL
    ret |= int(not_light) << PSTA_NOT_LIGHT
    ret |= int(env_map)   << PSTA_USE_ENVMAP
    ret |= int(palette)   << PSTA_USE_PALETTO
    ret |= int(bump_map)  << PSTA_USE_BUMP
    return ret


def naomi_format_type_2_7(name: Optional[str], nullmodel: bool) -> None:
    global save_all_strip_opq, save_all_strip_trs, save_all_strip_pch
    global before_List_Type
    global before_face_A, before_face_R, before_face_G, before_face_B
    global before_offset_A, before_offset_R, before_offset_G, before_offset_B
    global send_gp_count
    global mcx, mcy, mcz, mcr
    global after_output_sta, after_output_nullmodel
    global after_output_super_index_format
    global after_output_mcx, after_output_mcy, after_output_mcz, after_output_mcr
    global after_output_name
    global g_matidx_model, g_matidx_flat, g_matidx_off
    global g_matidx_cnt, g_matidx_matnum
    global super_index_format
    global bump_polygon, bump_polygon_dup, bump_polygon_trs
    global env_map_polygon, tri_liner_mode

    save_all_strip_opq = None
    save_all_strip_trs = None
    save_all_strip_pch = None

    before_List_Type  = LIST_NON
    before_face_A = before_face_R = before_face_G = before_face_B = -1.0
    before_offset_A = before_offset_R = before_offset_G = before_offset_B = -1.0

    send_gp_count = 0

    base_name = name_operate(input_file_name_base)
    sta = chk_polygon_status()

    if not output_after_all:
        if (sta & (1 << PSTA_ZERO_MODEL)) or nullmodel:
            format_flag = -1
        elif super_index_format:
            format_flag = 1
        else:
            format_flag = 0

        write_le32(format_flag & 0xFFFFFFFF)
        write_le32(sta | 1)
    else:
        after_output_name = name if name is not None else ""
        after_output_sta  = sta
        after_output_nullmodel = nullmodel
        after_output_super_index_format = super_index_format

    # Scale the model bounding sphere
    mcx = Std_Float(float(mcx) * allScale)
    mcy = Std_Float(float(mcy) * allScale)
    mcz = Std_Float(float(mcz) * allScale)
    mcr = Std_Float(float(mcr) * allScale)

    if not output_after_all:
        write_le32(mcx.hex())
        write_le32(mcy.hex())
        write_le32(mcz.hex())
        write_le32(mcr.hex())
    else:
        after_output_mcx = mcx
        after_output_mcy = mcy
        after_output_mcz = mcz
        after_output_mcr = mcr

    # Per-model processing loop
    for i in range(StdModelCount):
        md = StdModel[i]

        # Build per-material polygon index lists (O(N) instead of O(N*M))
        mat_poly_idx_flat = [0] * max(md.polygon_num, 1)
        mat_poly_off      = [0] * (md.material_num + 1)
        mat_poly_cnt      = [0] * max(md.material_num, 1)

        # Count pass
        for _p in range(md.polygon_num):
            mi = md.polygon[_p].material_index
            if 0 <= mi < md.material_num:
                mat_poly_cnt[mi] += 1

        # Prefix-sum
        mat_poly_off[0] = 0
        for _m in range(md.material_num):
            mat_poly_off[_m + 1] = mat_poly_off[_m] + mat_poly_cnt[_m]

        # Fill pass
        fill_pos = [0] * max(md.material_num, 1)
        for _p in range(md.polygon_num):
            mi = md.polygon[_p].material_index
            if 0 <= mi < md.material_num:
                mat_poly_idx_flat[mat_poly_off[mi] + fill_pos[mi]] = _p
                fill_pos[mi] += 1

        # Publish to global cache
        g_matidx_model  = md
        g_matidx_flat   = mat_poly_idx_flat
        g_matidx_off    = mat_poly_off
        g_matidx_cnt    = mat_poly_cnt
        g_matidx_matnum = md.material_num

        for j in range(md.material_num):
            mfa, mfr, mfg, mfb, moa, mor, mog, mob = get_color(i, j)

            for ii in range(i, StdModelCount):
                mat_bump_srch = False
                mmd = StdModel[ii]

                for jj in range(mmd.material_num):
                    if mmd.material[jj].bump_map:
                        mat_bump_srch = True
                        break

                for jj in range(mmd.material_num):
                    mm = mmd.material[jj]

                    if mm.same_flag2:
                        continue

                    mmfa, mmfr, mmfg, mmfb, mmoa, mmor, mmog, mmob = \
                        get_color(ii, jj)

                    if (mfa != mmfa or mfr != mmfr or
                            mfg != mmfg or mfb != mmfb):
                        continue
                    if (moa != mmoa or mor != mmor or
                            mog != mmog or mob != mmob):
                        continue

                    bump_polygon     = False
                    bump_polygon_dup = False
                    bump_polygon_trs = False
                    env_map_polygon  = False

                    if mmd.material[jj].bump_map:
                        bump_polygon = True
                    if mmd.material[jj].env_map:
                        env_map_polygon = True

                    # Mirror into render_types module globals so that
                    # see the correct per-material values in the non-deferred
                    bump_polygon     = bump_polygon
                    bump_polygon_dup = bump_polygon_dup
                    bump_polygon_trs = bump_polygon_trs
                    env_map_polygon  = env_map_polygon

                    mm.same_flag2 = True

                    if not StdModel[ii].outcalc:
                        if True:
                            StdModel[ii].set_gr(0)
                            StdModel[ii].calc_point_normal()
                            if mat_bump_srch:
                                StdModel[ii].set_bump_normal()
                            StdModel[ii].reset_triangle(0)
                            if g_matidx_model is StdModel[ii]:
                                g_matidx_model = None
                            if div_convex:
                                StdModel[ii].set_gr(1)
                        else:
                            StdModel[ii].reset_triangle(0)
                            if g_matidx_model is StdModel[ii]:
                                g_matidx_model = None
                            StdModel[ii].set_gr(0)
                            StdModel[ii].calc_point_normal()
                            if mat_bump_srch:
                                StdModel[ii].set_bump_normal()

                        StdModel[ii].outcalc = True

                    tri_liner_mode = TRI_LINER_NON

                    tmp_s_index_flag = super_index_format
                    flt = StdModel[ii].material[jj].filter_mode
                    if not StdModel[ii].material[jj].pic_name:
                        flt = 0

                    tmp_bump_polygon = bump_polygon
                    if bump_polygon:
                        super_index_format = False

                    if (bump_polygon and
                            StdModel[ii].material[jj].auto_bump_map_generate):
                        bump_polygon     = False
                        bump_polygon_dup = True
                        super_index_format = tmp_s_index_flag
                        bump_polygon     = bump_polygon
                        bump_polygon_dup = bump_polygon_dup

                    if flt >= 2:
                        trs_mode = LIST_OPQ
                        if StdModel[ii].material[jj].trs != 0:
                            trs_mode = LIST_TRS
                        if (StdModel[ii].material[jj].effect == DK_TXT_ALPHA and
                                StdModel[ii].material[jj].transpFct == -1.0):
                            trs_mode = LIST_TRS

                        tri_liner_mode = TRI_LINER_PASS_A
                        naomi_format_type_2_7_main(ii, jj)
                        tri_liner_mode = TRI_LINER_PASS_B
                        naomi_format_type_2_7_main(ii, jj)
                        if trs_mode == LIST_TRS:
                            tri_liner_mode = TRI_LINER_TRS_LAST
                            naomi_format_type_2_7_main(ii, jj)
                    else:
                        naomi_format_type_2_7_main(ii, jj)

                    if tmp_bump_polygon and not bump_polygon:
                        bump_polygon_dup = False
                        bump_polygon     = True
                        bump_polygon_trs = True
                        super_index_format = False
                        bump_polygon     = bump_polygon
                        bump_polygon_dup = bump_polygon_dup
                        bump_polygon_trs = bump_polygon_trs
                        naomi_format_type_2_7_main(ii, jj)

                    super_index_format = tmp_s_index_flag

        # End per-material loop
        # (mat_poly_* lists go out of scope — GC handles them)

    if output_after_all:
        all_put_strip_point()

    if not naomi2hg:
        write_le32(0)
        write_le32((file_all_point_count + all_once_ct * 3) & 0xFFFFFFFF)


def put_triangle(s: Std_Polygon, pl: List[Std_Point], tex: int) -> None:
    if s.info_list_num >= 5:
        return
    elif s.info_list_num == 4:
        put_triangle0(s, pl, tex, 0)
        put_triangle0(s, pl, tex, 1)
        put_triangle0(s, pl, tex, 2)
        put_triangle0(s, pl, tex, 0)
        put_triangle0(s, pl, tex, 2)
        put_triangle0(s, pl, tex, 3)
    elif s.info_list_num == 3:
        put_triangle0(s, pl, tex, 0)
        put_triangle0(s, pl, tex, 1)
        put_triangle0(s, pl, tex, 2)

def put_triangle0(s: Std_Polygon, pl: List[Std_Point],
                  tex: int, k: int) -> None:
    write_le32(0)

    idx = s.info_list[k].point_index
    if idx < 0:
        idx = 0

    x = float(pl[idx].x)
    y = float(pl[idx].y)
    z = float(pl[idx].z)

    write_le32(pl[idx].x.hex())
    write_le32(pl[idx].y.hex())
    write_le32(pl[idx].z.hex())

    write_le32(s.info_list[k].nx.hex())
    write_le32(s.info_list[k].ny.hex())
    write_le32(s.info_list[k].nz.hex())

    if tex == 1:
        write_le32(s.info_list[k].u.hex())
        write_le32(s.info_list[k].v.hex())


def file_name_base(pathname: str) -> str:
    # Strip leading directory component
    p = pathname
    last_sep = max(p.rfind("/"), p.rfind("\\"))
    if last_sep != -1:
        p = p[last_sep + 1:]

    # Strip trailing extension
    dot = p.rfind(".")
    if dot != -1:
        p = p[:dot]

    return p


def chk_same_material0() -> None:
    """Within each model, find materials that are identical and mark"""
    for i in range(StdModelCount):
        md = StdModel[i]
        for j in range(md.material_num):
            m = md.material[j]
            for jj in range(j + 1, md.material_num):
                mm = md.material[jj]
                if not m.same_flag and m == mm:
                    mm.same_flag = True
                    for k in range(md.polygon_num):
                        if md.polygon[k].material_index == jj:
                            md.polygon[k].material_index = j


def chk_same_material1() -> None:
    """Merge identical materials across models when they are close"""
    import math

    get_model_culling()

    for i in range(StdModelCount):
        md = StdModel[i]
        copy_mdl_no = i
        old_p_count = 0

        for j in range(md.material_num):
            m = md.material[j]

            for ii in range(i, StdModelCount):
                mmd = StdModel[ii]

                if md.discAngle != mmd.discAngle:
                    continue

                for jj in range(mmd.material_num):
                    mm = mmd.material[jj]

                    if m.same_flag or mm.same_flag:
                        continue
                    if not (m == mm) or (ii == i and jj == j):
                        continue

                    # Proximity check
                    if uncond_merge_rad < float(mcr):
                        dx = float(md.cx) - float(mmd.cx)
                        dy = float(md.cy) - float(mmd.cy)
                        dz = float(md.cz) - float(mmd.cz)
                        l = math.sqrt(dx*dx + dy*dy + dz*dz)
                        rr = max(float(md.cr), float(mmd.cr))
                        if l != 0 and rr / l < merge_rate:
                            continue

                    mm.same_flag = True

                    if copy_mdl_no != ii:
                        copy_mdl_no = ii

                        # Merge point lists
                        new_pts = md.point_list[:] + mmd.point_list[:]
                        old_p_count = md.point_num
                        md.point_list = new_pts
                        md.point_num  = md.point_num + mmd.point_num

                    if i == ii:
                        # Same model — just remap polygon material index
                        for k in range(mmd.polygon_num):
                            if mmd.polygon[k].material_index == jj:
                                mmd.polygon[k].material_index = j
                    else:
                        # Cross-model — copy matching polygons into md
                        p_count = sum(
                            1 for k in range(mmd.polygon_num)
                            if mmd.polygon[k].material_index == jj
                        )

                        new_polys = md.polygon[:]
                        p_add = md.polygon_num

                        for k in range(mmd.polygon_num):
                            if mmd.polygon[k].material_index == jj:
                                import copy as _copy
                                np_ = _copy.deepcopy(mmd.polygon[k])
                                np_.material_index = j
                                np_.model = md
                                for kk in range(np_.info_list_num):
                                    if np_.info_list[kk].point_index >= 0:
                                        np_.info_list[kk].point_index += \
                                            old_p_count
                                new_polys.append(np_)
                                p_add += 1

                        md.polygon_num = md.polygon_num + p_count
                        md.polygon     = new_polys


def get_tex_file(texname_out: list,
                 fullname: str,
                 basename: str) -> bool:
    """Resolve a .pic texture file.  On success write the path (without"""
    t_name = fullname + ".pic"
    if file_exist(t_name):
        texname_out[0] = fullname
        return True

    for i in range(texpath_count):
        t_name = texpath[i] + basename + ".pic"
        if file_exist(t_name):
            texname_out[0] = texpath[i] + basename
            return True

    return False

def get_pal_file(palname_out: list,
                 fullname: str,
                 basename: str) -> bool:
    """Resolve a .pal palette file.  On success write the path (without"""
    # Handle "N,name" direct-mode specs by skipping the numeric prefix
    if fullname and fullname[0].isdigit() and "," in fullname:
        fullname = fullname[fullname.index(",") + 1:]
    if basename and basename[0].isdigit() and "," in basename:
        basename = basename[basename.index(",") + 1:]

    p_name = fullname + ".pal"
    if file_exist(p_name):
        palname_out[0] = fullname
        return True

    for i in range(palpath_count):
        p_name = palpath[i] + basename + ".pal"
        if file_exist(p_name):
            palname_out[0] = palpath[i] + basename
            return True

    return False


def mem_all_clear() -> None:
    """Reset all per-object counters before starting a new model."""
    global object_all_address
    global before_face_A, before_face_R, before_face_G, before_face_B
    global before_offset_A, before_offset_R, before_offset_G, before_offset_B
    global send_gp_count
    global all_strip_ct, all_fan_ct, all_once_ct
    global before_srch_point_count, file_all_point_count, file_all_polygon_count
    global max_s_index_ct, put_point_all, put_repoint_all

    object_all_address = 6 * 4

    before_face_A = before_face_R = before_face_G = before_face_B = -1.0
    before_offset_A = before_offset_R = before_offset_G = before_offset_B = -1.0

    send_gp_count = 0

    all_strip_ct   = 0
    all_fan_ct     = 0
    all_once_ct    = 0

    before_srch_point_count = 0
    file_all_point_count    = 0
    file_all_polygon_count  = 0

    max_s_index_ct = 0

    put_point_all   = 0
    put_repoint_all = 0


def make_texname_res() -> None:
    res_name.clear()


def name_operate(name0: str) -> str:
    """Strip the directory part of *name0* and replace '-' and '.' with"""
    # Find the last path separator (forward or back slash)
    last_fwd = name0.rfind("/")
    last_bwd = name0.rfind("\\")

    if last_fwd == -1 and last_bwd == -1:
        name = name0
    elif last_fwd != -1 and last_bwd == -1:
        name = name0[last_fwd + 1:]
    elif last_fwd == -1 and last_bwd != -1:
        name = name0[last_bwd + 1:]
    else:
        sep = max(last_fwd, last_bwd)
        name = name0[sep + 1:]

    if not name:
        name = name0

    name = name.replace("-", "_").replace(".", "_")
    return name


_MM_SUFFIXES = ("_mm8", "_mm16", "_mm32", "_mm64",
                "_mm128", "_mm256", "_mm512", "_mm1024")

def cut_mip_map_name(name: str) -> str:
    if "_mm" not in name:
        return name
    for suffix in _MM_SUFFIXES:
        pos = name.find(suffix)
        if pos != -1:
            return name[:pos]
    return name


def chk_file_name_rule(name0: str, rule: str) -> Optional[str]:
    """Strip path and extension from *name0* then search for *rule*"""
    name = file_name_base(name0)
    idx  = name.find(rule)
    return name[idx:] if idx != -1 else None


def all_put_strip_point() -> None:
    """Full implementation lives in Part 2 (naomi_format_type_2_7 calls"""
    raise NotImplementedError(
        "all_put_strip_point() is implemented in render_output Part 2"
    )


# Dirty-list pool statics and helpers
# The dirty list tracks which PolySrch entries have had their
# dirty_idx stamp set to the current generation.  Bumping
# g_dirty_gen invalidates all stamps in O(1) without clearing
# the array

_g_dirty_list: List[int] = []
_g_dirty_count: int = 0
_g_dirty_cap: int = 0
_g_dirty_gen: int = 1

def _dirty_list_ensure(cap: int) -> None:
    global _g_dirty_list, _g_dirty_cap
    if cap > _g_dirty_cap:
        _g_dirty_cap = cap + 64
        # Extend the list to the new capacity (fill with 0)
        _g_dirty_list = _g_dirty_list[:_g_dirty_count] + [0] * (_g_dirty_cap - _g_dirty_count)

def _dirty_list_reset() -> None:
    global _g_dirty_gen, _g_dirty_count
    _g_dirty_gen += 1
    _g_dirty_count = 0

def _dirty_mark(ps: List[PolySrch], idx: int) -> None:
    global _g_dirty_count
    if ps[idx].dirty_idx != _g_dirty_gen:
        ps[idx].dirty_idx = _g_dirty_gen
        _g_dirty_list[_g_dirty_count] = idx
        _g_dirty_count += 1

# IdxList pool statics and helpers
# A simple bump-allocator over a pre-grown list of IdxList
# objects.  _idxlist_pool_reset() rewinds the high-water mark
# to zero; _idxlist_alloc() hands out the next free slot.

_idxlist_pool: List[IdxList] = []
_idxlist_pool_cap: int = 0
_idxlist_pool_used: int = 0

def _idxlist_pool_reset() -> None:
    global _idxlist_pool_used
    _idxlist_pool_used = 0

def _idxlist_pool_ensure(n: int) -> None:
    """Ensure the pool has room for at least *n* nodes total."""
    global _idxlist_pool, _idxlist_pool_cap
    if n > _idxlist_pool_cap:
        # Grow: append fresh IdxList objects
        extra = (n + 1024) - _idxlist_pool_cap
        _idxlist_pool.extend(IdxList(0) for _ in range(extra))
        _idxlist_pool_cap = len(_idxlist_pool)

def _idxlist_alloc(pl_idx: int, next_node: Optional[IdxList]) -> IdxList:
    global _idxlist_pool_used
    node = _idxlist_pool[_idxlist_pool_used]
    _idxlist_pool_used += 1
    node.pl_idx = pl_idx
    node.next = next_node
    return node


# Counts the number of "hole" polygons encountered during
# concave-polygon processing (> 0 means a hole was found).
hole_polygon: int = 0

# Bump-normal accumulation state used by chk_before_bump_nrm_*
# helpers (per-face normals averaged across strip steps).
chk_before_bump_nrm_ct: int = 0
chk_before_bump_nrm_x:  float = 0.0
chk_before_bump_nrm_y:  float = 0.0
chk_before_bump_nrm_z:  float = 0.0
chk_before_bump_nrm0_x: float = 0.0
chk_before_bump_nrm0_y: float = 0.0
chk_before_bump_nrm0_z: float = 0.0
chk_before_bump_nrm1_x: float = 0.0
chk_before_bump_nrm1_y: float = 0.0
chk_before_bump_nrm1_z: float = 0.0

# Maximum S-index count seen across all materials (used by the
# super-index-format path).
max_s_index_ct: int = 0

# Running byte-address counter for the NAOMI "naomi2hg" (NL2)
# output stream;
naomi2hg_all_address: int = 0

def same_float(a: float, b: float) -> bool:
    """Coarse float equality (tolerance 0.001)."""
    return abs(a - b) < 0.001

# Option globals
# Defaults mirror NlcvOptions in options.  The main driver
# must call apply_options() to push an NlcvOptions instance into
# these names before any conversion work begins.

# Strip / triangle mode switches
not_triangle:       bool = False
all_triangle:       bool = False

# Search / performance
srch_level:       int  = 2
touch_count_max:  int  = 3

# Bump-polygon state
bump_polygon:     bool = False
bump_polygon_dup: bool = False
bump_polygon_trs: bool = False
env_map_polygon:  bool = False


def _PolySrch_dec_touch_count(
        self: PolySrch,
        num: int,
        pl:  List[Std_Polygon],
        ps:  List[PolySrch],
) -> None:
    global _g_dirty_count, _g_dirty_gen
    my_idx = self.self_srch_index
    if ps[my_idx].dirty_idx != _g_dirty_gen:
        ps[my_idx].dirty_idx = _g_dirty_gen
        _g_dirty_list[_g_dirty_count] = my_idx
        _g_dirty_count += 1
    aite_srch_index = pl[self.touch_side[num].t_index].srch_index
    if ps[aite_srch_index].dirty_idx != _g_dirty_gen:
        ps[aite_srch_index].dirty_idx = _g_dirty_gen
        _g_dirty_list[_g_dirty_count] = aite_srch_index
        _g_dirty_count += 1

    aite: PolySrch = ps[aite_srch_index]

    _mk = aite.touch_side_map_k; _mv = aite.touch_side_map_v
    _self_pl_index = self.pl_index
    if _mk[0] == _self_pl_index: kx = _mv[0]
    elif _mk[1] == _self_pl_index: kx = _mv[1]
    else: kx = _mv[2]

    atmp: TouchSide = aite.touch_side[kx]

    # Shift aite.touch_side[kx..touch_count-2] left by one
    aite_tc = aite.touch_count
    _amk = aite.touch_side_map_k; _amv = aite.touch_side_map_v
    for i in range(kx, aite_tc - 1):
        moved = aite.touch_side[i + 1]
        aite.touch_side[i] = moved
        _mt = moved.t_index
        if _amk[0] == _mt: _amv[0] = i
        elif _amk[1] == _mt: _amv[1] = i
        else: _amv[2] = i

    # Park the removed entry at the tail (sentinel)
    aite.touch_side[aite_tc - 1] = atmp
    if _amk[0] == _self_pl_index: _amk[0] = -1
    elif _amk[1] == _self_pl_index: _amk[1] = -1
    else: _amk[2] = -1
    aite.touch_side_map_n -= 1

    # Adjust aite.srch_start if it fell in the shifted range
    if kx <= aite.srch_start < aite_tc:
        aite.srch_start -= 1
        if aite.srch_start < kx:
            aite.srch_start += aite_tc - kx

    aite.touch_count    -= 1
    aite.r_touch_count  += 1
    aite.dec_count      += 1


    tmp: TouchSide = self.touch_side[num]
    self_tc = self.touch_count
    _smk = self.touch_side_map_k; _smv = self.touch_side_map_v

    for i in range(num, self_tc - 1):
        moved = self.touch_side[i + 1]
        self.touch_side[i] = moved
        _mt = moved.t_index
        if _smk[0] == _mt: _smv[0] = i
        elif _smk[1] == _mt: _smv[1] = i
        else: _smv[2] = i

    self.touch_side[self_tc - 1] = tmp
    _tmp_ti = tmp.t_index
    if _smk[0] == _tmp_ti: _smk[0] = -1
    elif _smk[1] == _tmp_ti: _smk[1] = -1
    else: _smk[2] = -1
    self.touch_side_map_n -= 1

    if num <= self.srch_start < self_tc:
        self.srch_start -= 1
        if self.srch_start < num:
            self.srch_start += self_tc - num

    self.touch_count   -= 1
    self.r_touch_count += 1

def _PolySrch_dec_touch_count_0(
        self: PolySrch,
        pl:  List[Std_Polygon],
        ps:  List[PolySrch],
) -> None:
    global _g_dirty_count, _g_dirty_gen

    my_idx = self.self_srch_index
    if ps[my_idx].dirty_idx != _g_dirty_gen:
        ps[my_idx].dirty_idx = _g_dirty_gen
        _g_dirty_list[_g_dirty_count] = my_idx
        _g_dirty_count += 1

    aite_srch_index = pl[self.touch_side[0].t_index].srch_index
    if ps[aite_srch_index].dirty_idx != _g_dirty_gen:
        ps[aite_srch_index].dirty_idx = _g_dirty_gen
        _g_dirty_list[_g_dirty_count] = aite_srch_index
        _g_dirty_count += 1

    aite: PolySrch = ps[aite_srch_index]
    _self_pl_index = self.pl_index
    _amk = aite.touch_side_map_k; _amv = aite.touch_side_map_v
    if _amk[0] == _self_pl_index: kx = _amv[0]
    elif _amk[1] == _self_pl_index: kx = _amv[1]
    else: kx = _amv[2]
    atmp: TouchSide = aite.touch_side[kx]
    aite_tc = aite.touch_count

    for i in range(kx, aite_tc - 1):
        moved = aite.touch_side[i + 1]
        aite.touch_side[i] = moved
        _mt = moved.t_index
        if _amk[0] == _mt: _amv[0] = i
        elif _amk[1] == _mt: _amv[1] = i
        else: _amv[2] = i

    aite.touch_side[aite_tc - 1] = atmp
    if _amk[0] == _self_pl_index: _amk[0] = -1
    elif _amk[1] == _self_pl_index: _amk[1] = -1
    else: _amk[2] = -1
    aite.touch_side_map_n -= 1

    if kx <= aite.srch_start < aite_tc:
        aite.srch_start -= 1
        if aite.srch_start < kx:
            aite.srch_start += aite_tc - kx

    aite.touch_count   -= 1
    aite.r_touch_count += 1
    aite.dec_count     += 1

    tmp: TouchSide = self.touch_side[0]
    self_tc = self.touch_count
    _smk = self.touch_side_map_k; _smv = self.touch_side_map_v

    for i in range(self_tc - 1):
        moved = self.touch_side[i + 1]
        self.touch_side[i] = moved
        _mt = moved.t_index
        if _smk[0] == _mt: _smv[0] = i
        elif _smk[1] == _mt: _smv[1] = i
        else: _smv[2] = i

    self.touch_side[self_tc - 1] = tmp
    _tmp_ti = tmp.t_index
    if _smk[0] == _tmp_ti: _smk[0] = -1
    elif _smk[1] == _tmp_ti: _smk[1] = -1
    else: _smk[2] = -1
    self.touch_side_map_n -= 1

    if self.srch_start < self_tc:
        self.srch_start -= 1
        if self.srch_start < 0:
            self.srch_start += self_tc

    self.touch_count   -= 1
    self.r_touch_count += 1


def _dec_touch_count_0_inline(self_ps, pl, ps):
    """Standalone inlined dec_touch_count_0.  Fully unrolled shift loops"""
    global _g_dirty_count, _g_dirty_gen

    my_idx = self_ps.self_srch_index
    _pmy = ps[my_idx]
    _gen = _g_dirty_gen
    _dc  = _g_dirty_count
    _dl  = _g_dirty_list
    if _pmy.dirty_idx != _gen:
        _pmy.dirty_idx = _gen
        _dl[_dc] = my_idx
        _dc += 1

    aite_srch_index = pl[self_ps.touch_side[0].t_index].srch_index
    aite = ps[aite_srch_index]
    if aite.dirty_idx != _gen:
        aite.dirty_idx = _gen
        _dl[_dc] = aite_srch_index
        _dc += 1
    _g_dirty_count = _dc

    _self_pl_index = self_ps.pl_index
    _amk = aite.touch_side_map_k; _amv = aite.touch_side_map_v
    if _amk[0] == _self_pl_index: kx = _amv[0]
    elif _amk[1] == _self_pl_index: kx = _amv[1]
    else: kx = _amv[2]

    _ats    = aite.touch_side
    atmp    = _ats[kx]
    aite_tc = aite.touch_count
    _tail   = aite_tc - 1

    # Unrolled shift: move _ats[kx+1..aite_tc-1] left by 1, updating map
    if kx < _tail:
        _m = _ats[kx + 1]; _ats[kx] = _m; _mt = _m.t_index
        if _amk[0] == _mt: _amv[0] = kx
        elif _amk[1] == _mt: _amv[1] = kx
        else: _amv[2] = kx
        if kx + 1 < _tail:
            _m = _ats[kx + 2]; _ats[kx + 1] = _m; _mt = _m.t_index
            if _amk[0] == _mt: _amv[0] = kx + 1
            elif _amk[1] == _mt: _amv[1] = kx + 1
            else: _amv[2] = kx + 1

    _ats[_tail] = atmp
    if _amk[0] == _self_pl_index: _amk[0] = -1
    elif _amk[1] == _self_pl_index: _amk[1] = -1
    else: _amk[2] = -1
    aite.touch_side_map_n -= 1

    _ass = aite.srch_start
    if kx <= _ass < aite_tc:
        _ass -= 1
        if _ass < kx:
            _ass += aite_tc - kx
        aite.srch_start = _ass

    aite.touch_count   = _tail
    aite.r_touch_count += 1
    aite.dec_count     += 1

    _sts    = self_ps.touch_side
    tmp     = _sts[0]
    self_tc = self_ps.touch_count
    _smk    = self_ps.touch_side_map_k; _smv = self_ps.touch_side_map_v
    _stail  = self_tc - 1

    if 0 < _stail:
        _m = _sts[1]; _sts[0] = _m; _mt = _m.t_index
        if _smk[0] == _mt: _smv[0] = 0
        elif _smk[1] == _mt: _smv[1] = 0
        else: _smv[2] = 0
        if 1 < _stail:
            _m = _sts[2]; _sts[1] = _m; _mt = _m.t_index
            if _smk[0] == _mt: _smv[0] = 1
            elif _smk[1] == _mt: _smv[1] = 1
            else: _smv[2] = 1

    _sts[_stail] = tmp
    _tmp_ti = tmp.t_index
    if _smk[0] == _tmp_ti: _smk[0] = -1
    elif _smk[1] == _tmp_ti: _smk[1] = -1
    else: _smk[2] = -1
    self_ps.touch_side_map_n -= 1

    _sss = self_ps.srch_start
    if _sss < self_tc:
        _sss -= 1
        if _sss < 0:
            _sss += self_tc
        self_ps.srch_start = _sss

    self_ps.touch_count   = _stail
    self_ps.r_touch_count += 1


def _PolySrch_srch_even_polygon(
        self:              PolySrch,
        before_set_point:  int,
        pl:                List[Std_Polygon],
        ps:                List[PolySrch],
        gr_off:            int,
) -> int:
    """Search for the next polygon to add on an *even* strip step."""
    _tc = self.touch_count
    if _tc <= 0:
        if _tc < 0:
            print("touch_count minus , algorithm error !!", flush=True)
            raise SystemExit(-1)
        return -1

    _self_pl      = pl[self.pl_index]
    _self_gr      = _self_pl.gr
    _cos_disc     = _self_pl._cos_disc_angle
    _sn           = _self_pl.normal
    _snx = _sn.x._data; _sny = _sn.y._data; _snz = _sn.z._data
    _snl2         = _snx*_snx + _sny*_sny + _snz*_snz
    _self_poly_id = _self_pl.poly_ID
    _self_pl_idx  = self.pl_index
    _self_ts      = self.touch_side
    _bp           = bump_polygon
    _self_il      = _self_pl.info_list
    _math_sqrt    = math.sqrt

    for i in range(_tc):
        aite_srch_index = pl[_self_ts[i].t_index].srch_index
        aite            = ps[aite_srch_index]

        _amk = aite.touch_side_map_k
        if _amk[0] == _self_pl_idx: kx = aite.touch_side_map_v[0]
        elif _amk[1] == _self_pl_idx: kx = aite.touch_side_map_v[1]
        elif _amk[2] == _self_pl_idx: kx = aite.touch_side_map_v[2]
        else: continue

        if aite.touch_side[kx].cm_b != before_set_point:
            continue

        if aite.use_flag:
            print("no use polygon connect , algorithm error !!", file=sys.stderr)
            raise SystemExit(-1)

        if gr_off:
            return aite_srch_index

        _aite_pl = pl[aite.pl_index]
        if _self_poly_id == _aite_pl.poly_ID:
            return aite_srch_index

        if _self_gr:
            _an  = _aite_pl.normal
            _anx = _an.x._data; _any = _an.y._data; _anz = _an.z._data
            _l2b = _anx*_anx + _any*_any + _anz*_anz
            _cp  = 1.0 if (_snl2 == 0.0 or _l2b == 0.0) else                    (_snx*_anx + _sny*_any + _snz*_anz) / _math_sqrt(_snl2 * _l2b)
            if _cos_disc < _cp:
                if _aite_pl.gr:
                    return aite_srch_index
                return -1

        if not _self_gr:
            if not _aite_pl.gr:
                return aite_srch_index
            return -1

        return -1

    return -1


def _PolySrch_srch_odd_polygon(
        self:              PolySrch,
        before_set_point:  int,
        pl:                List[Std_Polygon],
        ps:                List[PolySrch],
        gr_off:            int,
) -> int:
    """Search for the next polygon to add on an *odd* strip step."""
    _tc = self.touch_count
    if _tc <= 0:
        if _tc < 0:
            print("touch_count minus , algorithm error !!", flush=True)
            raise SystemExit(-1)
        return -1

    _self_pl      = pl[self.pl_index]
    _self_gr      = _self_pl.gr
    _cos_disc     = _self_pl._cos_disc_angle
    _sn           = _self_pl.normal
    _snx = _sn.x._data; _sny = _sn.y._data; _snz = _sn.z._data
    _snl2         = _snx*_snx + _sny*_sny + _snz*_snz
    _self_poly_id = _self_pl.poly_ID
    _self_pl_idx  = self.pl_index
    _self_ts      = self.touch_side
    _bp           = bump_polygon
    _self_il      = _self_pl.info_list
    _math_sqrt    = math.sqrt

    for i in range(_tc):
        aite_srch_index = pl[_self_ts[i].t_index].srch_index
        aite            = ps[aite_srch_index]

        _amk = aite.touch_side_map_k
        if _amk[0] == _self_pl_idx: kx = aite.touch_side_map_v[0]
        elif _amk[1] == _self_pl_idx: kx = aite.touch_side_map_v[1]
        elif _amk[2] == _self_pl_idx: kx = aite.touch_side_map_v[2]
        else: continue

        if aite.touch_side[kx].cm_a != before_set_point:
            continue

        if aite.use_flag:
            print("no use polygon connect , algorithm error !!", file=sys.stderr)
            raise SystemExit(-1)

        if gr_off:
            return aite_srch_index

        _aite_pl = pl[aite.pl_index]
        if _self_poly_id == _aite_pl.poly_ID:
            return aite_srch_index

        if _self_gr:
            _an  = _aite_pl.normal
            _anx = _an.x._data; _any = _an.y._data; _anz = _an.z._data
            _l2b = _anx*_anx + _any*_any + _anz*_anz
            _cp  = 1.0 if (_snl2 == 0.0 or _l2b == 0.0) else                    (_snx*_anx + _sny*_any + _snz*_anz) / _math_sqrt(_snl2 * _l2b)
            if _cos_disc < _cp:
                if _aite_pl.gr:
                    return aite_srch_index
                return -1

        if not _self_gr:
            if not _aite_pl.gr:
                return aite_srch_index
            return -1

        return -1

    return -1


# Internal helper used by the two srch_* methods above.
# cos_p is defined later in this file (or will be injected by
# render_types_defs stubs); we reference it via the module
# name so it resolves at call time.
def _cos_p(v0: Std_Point, v1: Std_Point) -> float:
    return cos_p(v0, v1)


# Accumulated strip/fan/once counts across the whole file.
all_strip_ct:   int = 0
all_fan_ct:     int = 0
all_once_ct:    int = 0

# Snapshot counts used for per-model reporting.
before_srch_point_count: int = 0
before_best_dec_count:   int = 0

# Total vertex / polygon counts written to the output file.
file_all_point_count:   int = 0
file_all_polygon_count: int = 0

# Optimised duplicate-check: O(1) via generation-stamp array.
_dup_flags:      List[int] = []
_dup_flags_size: int = 0
_dup_gen:        int = 0

# Kept for compatibility: callers use dup_chk_buf_ct as a
# "reset" trigger (they check it and call dup_ensure_size when
# it exceeds a threshold).
dup_chk_buf_ct: int = 0


def dup_ensure_size(n: int) -> None:
    global _dup_flags, _dup_flags_size
    if n > _dup_flags_size:
        new_size = n + 64
        _dup_flags.extend([0] * (new_size - _dup_flags_size))
        _dup_flags_size = new_size


def add_index(idx: int) -> None:
    global dup_chk_buf_ct
    dup_ensure_size(idx + 1)
    _dup_flags[idx] = _dup_gen
    dup_chk_buf_ct += 1


def chk_dup_index(idx: int) -> bool:
    if idx < 0 or idx >= _dup_flags_size:
        return False
    return _dup_flags[idx] == _dup_gen

# Option globals (continued)

def mat_printf(fmt: str, *args) -> None:
    """Conditional stderr printf used for diagnostic output."""
    pass


def reset_touch_count(ps: List[PolySrch], ps_num: int) -> None:
    _dl = _g_dirty_list
    _dc = _g_dirty_count
    for _d in range(_dc):
        p = ps[_dl[_d]]
        rtc = p.r_touch_count
        if rtc > 0:
            p.use_flag = False
            tc = p.touch_count + rtc
            p.touch_count = tc
            p.r_touch_count = 0
            _ts = p.touch_side; _bk = p.touch_side_bkup
            _ts[0] = _bk[0]
            if tc > 1:
                _ts[1] = _bk[1]
                if tc > 2:
                    _ts[2] = _bk[2]
            _bmk = p.touch_side_map_bkup_k
            _bmv = p.touch_side_map_bkup_v
            _mk  = p.touch_side_map_k
            _mv  = p.touch_side_map_v
            _mk[0] = _bmk[0]; _mk[1] = _bmk[1]; _mk[2] = _bmk[2]
            _mv[0] = _bmv[0]; _mv[1] = _bmv[1]; _mv[2] = _bmv[2]
            p.touch_side_map_n = p.touch_side_map_bkup_n
            p.srch_start = 0
            p.dec_count = p.dec_count_bkup
        elif p.use_flag:
            p.use_flag = False
        p.dirty_idx = 0
    # Caller must call _dirty_list_reset() before the next probe.

def clear_touch_count(ps: List[PolySrch], ps_num: int) -> None:
    _dl = _g_dirty_list
    _dc = _g_dirty_count
    for _d in range(_dc):
        p = ps[_dl[_d]]
        if p.r_touch_count > 0:
            tc = p.touch_count
            _ts = p.touch_side; _bk = p.touch_side_bkup
            _bk[0] = _ts[0]
            if tc > 1:
                _bk[1] = _ts[1]
                if tc > 2:
                    _bk[2] = _ts[2]
            _mk  = p.touch_side_map_k
            _mv  = p.touch_side_map_v
            _bmk = p.touch_side_map_bkup_k
            _bmv = p.touch_side_map_bkup_v
            _bmk[0] = _mk[0]; _bmk[1] = _mk[1]; _bmk[2] = _mk[2]
            _bmv[0] = _mv[0]; _bmv[1] = _mv[1]; _bmv[2] = _mv[2]
            p.touch_side_map_bkup_n = p.touch_side_map_n
            p.dec_count_bkup = p.dec_count
        p.r_touch_count = 0
        p.srch_start    = 0
        p.dirty_idx     = 0


def _Std_Model_set_strip_point(
        self:             Std_Model,
        mat_index:        int,
        mat_same_polynum: int,
        tex:              VOL2_TEX_FLAG,
        div:              int = 0,
) -> None:
    _reset_tc = reset_touch_count
    _srch_strip0 = self.srch_polygon_strip0
    _srch_fan0   = self.srch_polygon_fan0


    now_double_side: bool = self.material[mat_index].double_side

    if div == 0:
        # First material for this model: clear strip list and counter.
        self.stripdata = None
        self.model_all_strip_point_count = 0
    else:
        # Subsequent material: advance grp_no on every existing strip.
        s = self.stripdata
        while s is not None:
            s.grp_no += 1
            s = s.next

    # Aliases that match the local names.
    j:    int = mat_index
    pnum: int = mat_same_polynum

    # Bring often-used model arrays into locals for speed / clarity.
    spol      = self.polygon
    point_num = self.point_num

    # (~1.5M times); reading a cached float attribute is ~10x faster.
    _cd = math.cos(self.discAngle)
    for _pi in range(self.polygon_num):
        spol[_pi]._cos_disc_angle = _cd


    pn_calc: List[Optional[IdxList]] = [None] * point_num

    _idxlist_pool_ensure(self.polygon_num * 3 + 16)
    _idxlist_pool_reset()

    for i in range(point_num):
        pn_calc[i] = None

    for i in range(self.polygon_num):
        sp = spol[i]
        for jj_inner in range(sp.info_list_num):
            inf = sp.info_list[jj_inner]
            if inf.point_index >= 0:
                pn_calc[inf.point_index] = _idxlist_alloc(
                    i, pn_calc[inf.point_index]
                )

    # Snapshot thresholds for the early-exit heuristic.
    self.before_srch_point_count = 0x7FFFFFFF
    self.before_best_dec_count   = -1

    # Running counters.
    all_point_count: int = 0
    strip_ct:        int = 0
    fan_ct:          int = 0
    once_ct:         int = 0


    ps0: List[PolySrch] = [PolySrch() for _ in range(pnum)]
    _dirty_list_ensure(pnum * 2 + 16)
    _dirty_list_reset()

    # Bulk-allocate touch_side / touch_side_bkup arrays to avoid
    ts_bulk:      List[List[TouchSide]] = [
        [TouchSide() for _ in range(touch_count_max)] for _ in range(pnum)
    ]
    ts_bkup_bulk: List[List[TouchSide]] = [
        [TouchSide() for _ in range(touch_count_max)] for _ in range(pnum)
    ]

    ps_ct:       int = 0
    ts_bulk_idx: int = 0

    for jj in range(self.polygon_num):
        if spol[jj].material_index != j:
            continue

        ps = ps0[ps_ct]
        ps.pl_index       = jj
        ps.touch_side      = ts_bulk[ts_bulk_idx]
        ps.touch_side_bkup = ts_bkup_bulk[ts_bulk_idx]
        ts_bulk_idx += 1

        # Reset dup-check for this polygon's neighbourhood scan.
        global dup_chk_buf_ct, _dup_gen
        dup_chk_buf_ct = 0
        _dup_gen += 1

        for ll in range(spol[jj].info_list_num):
            if spol[jj].info_list[ll].point_index >= 0:
                l = pn_calc[spol[jj].info_list[ll].point_index]
            else:
                l = None

            while l is not None and not all_triangle:
                kk = l.pl_idx

                if (kk != jj
                        and spol[kk].material_index == j
                        and not chk_dup_index(kk)):

                    # A shared edge (ma,mb) on jj matches (cb,ca) on kk when
                    _il_j = spol[jj].info_list
                    _il_k = spol[kk].info_list
                    _ps_tc = ps.touch_count

                    if _il_j[0] == _il_k[1] and _il_j[1] == _il_k[0]:
                        if _ps_tc < touch_count_max:
                            _s = ps.touch_side[_ps_tc]
                            _s.my_a = 0; _s.my_b = 1; _s.t_index = kk; _s.cm_a = 0; _s.cm_b = 1
                        add_index(kk); ps.touch_count += 1; _ps_tc += 1
                    elif _il_j[0] == _il_k[2] and _il_j[1] == _il_k[1]:
                        if _ps_tc < touch_count_max:
                            _s = ps.touch_side[_ps_tc]
                            _s.my_a = 0; _s.my_b = 1; _s.t_index = kk; _s.cm_a = 1; _s.cm_b = 2
                        add_index(kk); ps.touch_count += 1; _ps_tc += 1
                    elif _il_j[0] == _il_k[0] and _il_j[1] == _il_k[2]:
                        if _ps_tc < touch_count_max:
                            _s = ps.touch_side[_ps_tc]
                            _s.my_a = 0; _s.my_b = 1; _s.t_index = kk; _s.cm_a = 2; _s.cm_b = 0
                        add_index(kk); ps.touch_count += 1; _ps_tc += 1

                    if _il_j[1] == _il_k[1] and _il_j[2] == _il_k[0]:
                        if _ps_tc < touch_count_max:
                            _s = ps.touch_side[_ps_tc]
                            _s.my_a = 1; _s.my_b = 2; _s.t_index = kk; _s.cm_a = 0; _s.cm_b = 1
                        add_index(kk); ps.touch_count += 1; _ps_tc += 1
                    elif _il_j[1] == _il_k[2] and _il_j[2] == _il_k[1]:
                        if _ps_tc < touch_count_max:
                            _s = ps.touch_side[_ps_tc]
                            _s.my_a = 1; _s.my_b = 2; _s.t_index = kk; _s.cm_a = 1; _s.cm_b = 2
                        add_index(kk); ps.touch_count += 1; _ps_tc += 1
                    elif _il_j[1] == _il_k[0] and _il_j[2] == _il_k[2]:
                        if _ps_tc < touch_count_max:
                            _s = ps.touch_side[_ps_tc]
                            _s.my_a = 1; _s.my_b = 2; _s.t_index = kk; _s.cm_a = 2; _s.cm_b = 0
                        add_index(kk); ps.touch_count += 1; _ps_tc += 1

                    if _il_j[2] == _il_k[1] and _il_j[0] == _il_k[0]:
                        if _ps_tc < touch_count_max:
                            _s = ps.touch_side[_ps_tc]
                            _s.my_a = 2; _s.my_b = 0; _s.t_index = kk; _s.cm_a = 0; _s.cm_b = 1
                        add_index(kk); ps.touch_count += 1; _ps_tc += 1
                    elif _il_j[2] == _il_k[2] and _il_j[0] == _il_k[1]:
                        if _ps_tc < touch_count_max:
                            _s = ps.touch_side[_ps_tc]
                            _s.my_a = 2; _s.my_b = 0; _s.t_index = kk; _s.cm_a = 1; _s.cm_b = 2
                        add_index(kk); ps.touch_count += 1; _ps_tc += 1
                    elif _il_j[2] == _il_k[0] and _il_j[0] == _il_k[2]:
                        if _ps_tc < touch_count_max:
                            _s = ps.touch_side[_ps_tc]
                            _s.my_a = 2; _s.my_b = 0; _s.t_index = kk; _s.cm_a = 2; _s.cm_b = 0
                        add_index(kk); ps.touch_count += 1

                l = l.next

        if ps.touch_count > touch_count_max:
            raise SystemExit(-2)


        if ps.touch_count == 2:
            if ps.touch_side[0].t_index > ps.touch_side[1].t_index:
                ps.touch_side[0], ps.touch_side[1] = (
                    ps.touch_side[1], ps.touch_side[0]
                )
        elif ps.touch_count == 3:
            # 3-element insertion sort on t_index (ascending)
            if ps.touch_side[0].t_index > ps.touch_side[1].t_index:
                ps.touch_side[0], ps.touch_side[1] = (
                    ps.touch_side[1], ps.touch_side[0]
                )
            if ps.touch_side[1].t_index > ps.touch_side[2].t_index:
                ps.touch_side[1], ps.touch_side[2] = (
                    ps.touch_side[2], ps.touch_side[1]
                )
                if ps.touch_side[0].t_index > ps.touch_side[1].t_index:
                    ps.touch_side[0], ps.touch_side[1] = (
                        ps.touch_side[1], ps.touch_side[0]
                    )

        spol[jj].srch_index = ps_ct
        ps0[ps_ct].self_srch_index = ps_ct
        _tc = ps0[ps_ct].touch_count
        _mk = ps0[ps_ct].touch_side_map_k
        _mv = ps0[ps_ct].touch_side_map_v
        _mk[0] = _mk[1] = _mk[2] = -1
        for _i in range(_tc):
            _mk[_i] = ps0[ps_ct].touch_side[_i].t_index
            _mv[_i] = _i
        ps0[ps_ct].touch_side_map_n = _tc
        _bk = ps0[ps_ct]
        _bk.touch_side_map_bkup_k[0] = _mk[0]
        _bk.touch_side_map_bkup_k[1] = _mk[1]
        _bk.touch_side_map_bkup_k[2] = _mk[2]
        _bk.touch_side_map_bkup_v[0] = _mv[0]
        _bk.touch_side_map_bkup_v[1] = _mv[1]
        _bk.touch_side_map_bkup_v[2] = _mv[2]
        _bk.touch_side_map_bkup_n    = _tc
        ps_ct += 1

    # Back up touch_side to touch_side_bkup for all filled entries.
    for jj in range(pnum):
        for ii in range(ps0[jj].touch_count):
            ps0[jj].touch_side_bkup[ii] = ps0[jj].touch_side[ii]

    # Pool no longer needed — reset and clear adjacency pointers.
    _idxlist_pool_reset()
    for i in range(point_num):
        pn_calc[i] = None


    poly_t0: List[int] = [0] * pnum
    poly_t1: List[int] = [0] * pnum
    poly_t2: List[int] = [0] * pnum
    poly_t3: List[int] = [0] * pnum

    before_strip_num: int = 0
    _srch_loop_ct:    int = 0
    _srch_call_ct:    int = 0

    _ps0 = ps0
    _remaining: List[int] = list(range(pnum))

    while True:
        _srch_loop_ct += 1

        dec_ct:       list = [0]
        point_ct:     int = 0
        point_ct_fan: int = 0

        poly_t_x:    Optional[List[int]] = None
        poly_t_x_ct: int = 0

        poly_t0_ct: int = 0
        poly_t1_ct: int = 0
        poly_t2_ct: int = 0
        poly_t3_ct: int = 0

        t0_list: List[int] = []
        t2_list: List[int] = []
        t3_list: List[int] = []
        _wr  = 0
        _rem = _remaining
        _t0a = t0_list.append
        _t2a = t2_list.append
        _t3a = t3_list.append
        for _rd in range(len(_rem)):
            jj = _rem[_rd]
            ps = _ps0[jj]
            if ps.use_flag: continue
            _rem[_wr] = jj; _wr += 1
            tc = ps.touch_count
            if tc == 0:   _t0a(jj)
            elif tc <= 2: _t2a(jj)
            else:         _t3a(jj)
        del _rem[_wr:]

        poly_t0_ct = len(t0_list)
        poly_t0[:poly_t0_ct] = t0_list

        if t2_list:
            t2_list.sort(key=lambda j: -999999 if _ps0[j].before_strip_count == -1 else -_ps0[j].before_strip_count)
            poly_t2_ct = len(t2_list)
            poly_t2[:poly_t2_ct] = t2_list

        if t3_list:
            t3_list.sort(key=lambda j: -999999 if _ps0[j].before_strip_count == -1 else -_ps0[j].before_strip_count)
            poly_t3_ct = len(t3_list)
            poly_t3[:poly_t3_ct] = t3_list

        if poly_t1_ct != 0:
            poly_t_x    = poly_t1
            poly_t_x_ct = poly_t1_ct
        elif poly_t2_ct != 0:
            poly_t_x    = poly_t2
            poly_t_x_ct = poly_t2_ct
        elif poly_t3_ct != 0:
            poly_t_x    = poly_t3
            poly_t_x_ct = poly_t3_ct
        else:

            if (poly_t0_ct != 0 and poly_t0_ct < 5) \
                    or not_triangle:
                # Small count: emit one StripData per isolated polygon.

                for i in range(poly_t0_ct):
                    jj = poly_t0[i]
                    _dirty_mark(ps0, jj)
                    ps0[jj].use_flag = True

                    g = StripData()
                    g.next      = self.stripdata
                    self.stripdata = g

                    g.pi = [StripData.POINT_INDEX() for _ in range(3)]
                    g._NL_PF_S_INDEX    = False
                    g._NL_PF_GOURAUD    = int(spol[ps0[jj].pl_index].gr)
                    if bump_polygon:
                        g._NL_PF_GOURAUD = 0
                    g._NL_PF_CULLING    = 1 if now_double_side else 2
                    g._NL_PF_STRIP      = 1
                    g._NL_PF_TRIANGLE   = 0
                    g._NL_PF_SPRITE     = 0
                    g.tex               = tex
                    g.strip_num         = 3

                    self.put_point_info2(0, ps0[jj].pl_index, 1)
                    self.put_point_info2(1, ps0[jj].pl_index, 0)
                    self.put_point_info2(2, ps0[jj].pl_index, 2)

                    all_point_count += 3
                    strip_ct        += 1

                    # Move newly-prepended strip to tail.
                    s = self.stripdata
                    if s.next is not None:
                        s0 = s
                        self.stripdata = s.next
                        while s.next is not None:
                            s = s.next
                        s.next  = s0
                        s0.next = None

            elif poly_t0_ct != 0:
                # Large count: split into Gouraud and flat batches.

                gr_num  = sum(1 for ii in range(poly_t0_ct)
                              if spol[ps0[poly_t0[ii]].pl_index].gr)
                frt_num = poly_t0_ct - gr_num

                if gr_num > 0:
                    g = StripData()
                    g.next         = self.stripdata
                    self.stripdata = g

                    g.pi = [StripData.POINT_INDEX() for _ in range((gr_num * 3))]
                    g._NL_PF_S_INDEX  = False
                    g._NL_PF_GOURAUD  = 1
                    if bump_polygon:
                        g._NL_PF_GOURAUD = 0
                    g._NL_PF_CULLING  = 1 if now_double_side else 2
                    if gr_num > 1 or all_triangle:
                        g._NL_PF_STRIP    = 0
                        g._NL_PF_TRIANGLE = 1
                    else:
                        g._NL_PF_STRIP    = 1
                        g._NL_PF_TRIANGLE = 0
                    g._NL_PF_SPRITE = 0
                    g.tex           = tex
                    g.strip_num     = gr_num * 3

                    tct = 0
                    for jj in range(poly_t0_ct):
                        kk = poly_t0[jj]
                        if spol[ps0[kk].pl_index].gr:
                            _dirty_mark(ps0, kk)
                            ps0[kk].use_flag = True
                            self.put_point_info2(tct,     ps0[kk].pl_index, 1)
                            self.put_point_info2(tct + 1, ps0[kk].pl_index, 0)
                            self.put_point_info2(tct + 2, ps0[kk].pl_index, 2)
                            tct += 3
                            if gr_num > 1:
                                once_ct += 1
                            else:
                                all_point_count += 3
                                strip_ct        += 1

                    # Tail insertion.
                    s = self.stripdata
                    if s.next is not None:
                        s0 = s
                        self.stripdata = s.next
                        while s.next is not None:
                            s = s.next
                        s.next  = s0
                        s0.next = None

                if frt_num > 0:
                    f = StripData()
                    f.next         = self.stripdata
                    self.stripdata = f

                    f.pi = [StripData.POINT_INDEX() for _ in range((frt_num * 3))]
                    f._NL_PF_S_INDEX  = False
                    f._NL_PF_GOURAUD  = 0
                    f._NL_PF_CULLING  = 1 if now_double_side else 2
                    if frt_num > 1 or all_triangle:
                        f._NL_PF_STRIP    = 0
                        f._NL_PF_TRIANGLE = 1
                    else:
                        f._NL_PF_STRIP    = 1
                        f._NL_PF_TRIANGLE = 0
                    f._NL_PF_SPRITE = 0
                    f.tex           = tex
                    f.strip_num     = frt_num * 3

                    tct = 0
                    for jj in range(poly_t0_ct):
                        kk = poly_t0[jj]
                        if not spol[ps0[kk].pl_index].gr:
                            _dirty_mark(ps0, kk)
                            ps0[kk].use_flag = True
                            self.put_point_info2(tct,     ps0[kk].pl_index, 1)
                            self.put_point_info2(tct + 1, ps0[kk].pl_index, 0)
                            self.put_point_info2(tct + 2, ps0[kk].pl_index, 2)
                            tct += 3
                            if frt_num > 1:
                                once_ct += 1
                            else:
                                all_point_count += 3
                                strip_ct        += 1

                    s = self.stripdata
                    if s.next is not None:
                        s0 = s
                        self.stripdata = s.next
                        while s.next is not None:
                            s = s.next
                        s.next  = s0
                        s0.next = None


            for _pi in range(ps_ct):
                ps0[_pi].touch_side      = None      # type: ignore[assignment]
                ps0[_pi].touch_side_bkup = None      # type: ignore[assignment]

            _srch_loop_ct = 0
            _srch_call_ct = 0

            global all_strip_ct, all_fan_ct, all_once_ct
            global file_all_point_count, file_all_polygon_count
            global before_srch_point_count, before_best_dec_count

            all_strip_ct            += strip_ct
            all_fan_ct              += fan_ct
            all_once_ct             += once_ct
            file_all_point_count    += all_point_count
            file_all_polygon_count  += pnum

            all_strip_ct           += strip_ct
            all_fan_ct             += fan_ct
            all_once_ct            += once_ct
            file_all_point_count   += all_point_count
            file_all_polygon_count += pnum

            self.model_all_strip_point_count += all_point_count + once_ct * 3

            return

        # Blocks 7 & 8 — clockwise + counter-clockwise search passes

        max_ct:         int  = -1
        max_idx:        int  = 0
        best_dec_count: int  = 0
        max_no:         int  = 0
        rot:            int  = Std_Model.clock
        fan:            bool = False

        _dec_ct_is_list = isinstance(dec_ct, list)

        if poly_t_x_ct > 0:

            _left_srch_done = False
            for i in range(poly_t_x_ct):
                chk_max      = False
                _pxi         = poly_t_x[i]
                _ps_pxi      = ps0[_pxi]
                tmp_strip_count = _ps_pxi.before_strip_count
                _ps_pxi.before_strip_count = 0

                _goto_srch_end = False

                for k in range(_ps_pxi.touch_count):
                    _srch_call_ct += 1
                    _dirty_list_reset()
                    point_ct = self.srch_polygon_strip0(
                        dec_ct, k, _pxi, pnum, ps0,
                        Std_Model.clock, tex, now_double_side,
                    )
                    if _dec_ct_is_list:
                        dec_ct_val = dec_ct[0]
                    else:
                        dec_ct_val = 0

                    _reset_tc(ps0, pnum)

                    # Compare point_ct with max_ct.
                    if fan:
                        if point_ct >= max_ct:
                            fan           = False
                            max_ct        = point_ct
                            max_idx       = i
                            max_no        = k
                            best_dec_count = dec_ct_val
                            chk_max       = True
                    else:
                        if point_ct > max_ct:
                            fan           = False
                            max_ct        = point_ct
                            max_idx       = i
                            max_no        = k
                            best_dec_count = dec_ct_val
                            chk_max       = True
                        elif point_ct == max_ct:
                            if dec_ct_val > best_dec_count:
                                fan           = False
                                max_ct        = point_ct
                                max_idx       = i
                                max_no        = k
                                best_dec_count = dec_ct_val
                                chk_max       = True

                    # Early-exit: beat prior best strip
                    if (point_ct >= self.before_srch_point_count
                            and best_dec_count > self.before_best_dec_count):
                        self.before_srch_point_count = point_ct
                        if not fan:
                            _goto_srch_end = True
                            break

                    # Early-exit: remaining polygons all covered
                    if (all_point_count + point_ct - ((strip_ct + 1) * 2)
                            + poly_t0_ct == pnum):
                        if not fan:
                            _goto_srch_end = True
                            break

                if _goto_srch_end:
                    _left_srch_done = True
                    break

                # Heuristic early-accept (srch_level 1 or 3)
                if ((srch_level == 1 or srch_level == 3)
                        and self.before_srch_point_count != 0x7FFFFFFF
                        and tmp_strip_count != -1
                        and self.before_srch_point_count > tmp_strip_count
                        and chk_max
                        and max_ct >= tmp_strip_count):
                    _left_srch_done = True
                    break

            if not _left_srch_done:
                _goto_srch_end2 = False
                for i in range(poly_t_x_ct):
                    chk_max = False
                    _pxi_i = poly_t_x[i]
                    tmp_strip_count = ps0[_pxi_i].before_strip_count
                    ps0[_pxi_i].before_strip_count = 0

                    for k in range(ps0[_pxi_i].touch_count):
                        _dirty_list_reset()
                        point_ct = self.srch_polygon_strip0(
                            dec_ct, k, poly_t_x[i], pnum, ps0,
                            Std_Model.rclock, tex, now_double_side,
                        )
                        if _dec_ct_is_list:
                            dec_ct_val = dec_ct[0]
                        else:
                            dec_ct_val = 0

                        _reset_tc(ps0, pnum)

                        if fan:
                            if point_ct >= max_ct:
                                fan           = False
                                rot           = Std_Model.rclock
                                max_ct        = point_ct
                                max_idx       = i
                                max_no        = k
                                best_dec_count = dec_ct_val
                                chk_max       = True
                        else:
                            if point_ct > max_ct:
                                fan           = False
                                rot           = Std_Model.rclock
                                max_ct        = point_ct
                                max_idx       = i
                                max_no        = k
                                best_dec_count = dec_ct_val
                                chk_max       = True
                            elif point_ct == max_ct:
                                if dec_ct_val > best_dec_count:
                                    fan           = False
                                    rot           = Std_Model.rclock
                                    max_ct        = point_ct
                                    max_idx       = i
                                    max_no        = k
                                    best_dec_count = dec_ct_val
                                    chk_max       = True

                        if (point_ct >= self.before_srch_point_count
                                and best_dec_count > self.before_best_dec_count):
                            self.before_srch_point_count = point_ct
                            _goto_srch_end2 = True
                            break

                        if (all_point_count + point_ct - ((strip_ct + 1) * 2)
                                + poly_t0_ct == pnum):
                            _goto_srch_end2 = True
                            break

                    if _goto_srch_end2:
                        break

                    # Heuristic accept (counter-CW mirror)
                    if ((srch_level == 1 or srch_level == 3)
                            and self.before_srch_point_count != 0x7FFFFFFF
                            and tmp_strip_count != -1
                            and self.before_srch_point_count > tmp_strip_count
                            and chk_max
                            and max_ct >= tmp_strip_count):
                        break


        if (max_ct == 3 and not not_triangle):
            # Degenerate: only 3 points — undo and retry without committing.
            self.srch_polygon_strip0(
                None, max_no, poly_t_x[max_idx], pnum, ps0,
                rot, tex, now_double_side, False,
            )
            _dirty_mark(ps0, poly_t_x[max_idx])
            ps0[poly_t_x[max_idx]].use_flag = False
            clear_touch_count(ps0, pnum)
            continue

        # Commit the best strip or fan found.
        if not fan:
            point_ct = self.srch_polygon_strip0(
                None, max_no, poly_t_x[max_idx], pnum, ps0,
                rot, tex, now_double_side, True,
            )
        else:
            point_ct = self.srch_polygon_fan0(
                None, max_no, poly_t_x[max_idx], pnum, ps0,
                rot, tex, now_double_side, True,
            )

        self.before_srch_point_count = point_ct
        self.before_best_dec_count   = best_dec_count
        if srch_level <= 2:
            self.before_best_dec_count = -1

        all_point_count += point_ct

        if poly_t_x_ct > 1 and point_ct != max_ct:
            print(
                f"output count henda , algorithm error <{max_ct},{point_ct}>!!",
                file=sys.stderr,
            )
            raise SystemExit(-1)

        clear_touch_count(ps0, pnum)

        strip_ct += 1
        if fan:
            fan_ct += 1

        continue


# Std_Model.srch_polygon_strip0
# Greedy triangle-strip search starting from polygon ps0[kk],
# using edge srch_start_no as the first shared edge.
# dec_count0 — if not None, receives the total dec_count tally.
# stripDisp  — if True, commit the strip to self.stripdata and
#              call put_point_info2; if False, only count points.

_strip0_point_buf: list = []
_strip0_point_buf_cap: int = 0

def _Std_Model_srch_polygon_strip0(
        self:            Std_Model,
        dec_count0,
        srch_start_no:  int,
        kk:             int,
        pnum:           int,
        ps0:            List[PolySrch],
        rot:            int,
        tex:            VOL2_TEX_FLAG,
        now_double_side: bool,
        stripDisp:      bool = False,
) -> int:
    """Greedy triangle-strip search starting at ps0[kk], entering via"""
    global _strip0_point_buf, _strip0_point_buf_cap
    global gouraud
    global _g_dirty_list, _g_dirty_count, _g_dirty_gen

    _dec_inline  = _dec_touch_count_0_inline
    _srch_even   = _PolySrch_srch_even_polygon
    _srch_odd    = _PolySrch_srch_odd_polygon

    kk0        = kk
    dec_count  = 0
    gouraud_delay = False
    gouraud    = False

    spol = self.polygon

    needed = pnum * 4 + 4
    if needed > _strip0_point_buf_cap:
        _strip0_point_buf_cap = needed + 64
        _strip0_point_buf = [[0, 0] for _ in range(_strip0_point_buf_cap)]
    point = _strip0_point_buf

    point_ct = 0

    first_rot        = 0
    before_set_point = 0

    # Seed triangle: all 3 vertices from the starting polygon.
    point[0][0] = ps0[kk].pl_index;  point[0][1] = 0
    point[1][0] = ps0[kk].pl_index;  point[1][1] = 1
    point[2][0] = ps0[kk].pl_index;  point[2][1] = 2
    point_ct = 3

    if ps0[kk].dirty_idx != _g_dirty_gen:
        ps0[kk].dirty_idx = _g_dirty_gen
        _g_dirty_list[_g_dirty_count] = kk
        _g_dirty_count += 1
    ps0[kk].use_flag = True

    before_touch_count = ps0[kk].touch_count
    before_kk          = kk

    # Step to the first neighbour.
    tc_idx = ps0[before_kk].touch_side[srch_start_no].t_index
    kk     = spol[tc_idx].srch_index

    if ps0[kk].use_flag:
        print(
            f"no use polygon connect , algorithm error 2 <{before_kk},{kk}>!!",
            file=sys.stderr,
        )
        raise SystemExit(-1)

    # Initialise gouraud flag from the seed polygon.
    gouraud = spol[ps0[before_kk].pl_index].gr

    _brk0 = False
    if spol[ps0[before_kk].pl_index].poly_ID == spol[ps0[kk].pl_index].poly_ID:
        pass
    elif gouraud:
        pass
    else:
        vv0 = spol[ps0[before_kk].pl_index].normal
        vv1 = spol[ps0[kk].pl_index].normal
        if _cos_p(vv0, vv1) > math.cos(self.discAngle):
            pass
        else:
            _brk0 = True

    _clock = Std_Model.clock
    if not _brk0:
        _is_clock = (rot == _clock)
        while True:
            _pkk = ps0[kk]
            _kmk = _pkk.touch_side_map_k; _bkpi = ps0[before_kk].pl_index
            if _kmk[0] == _bkpi: kx = _pkk.touch_side_map_v[0]
            elif _kmk[1] == _bkpi: kx = _pkk.touch_side_map_v[1]
            else: kx = _pkk.touch_side_map_v[2]

            my_a = _pkk.touch_side[kx].my_a
            if my_a == 0:
                before_set_point = 2
            elif my_a == 1:
                before_set_point = 0
            else:
                before_set_point = 1

            if point_ct == 3:
                first_rot = _pkk.touch_side[kx].cm_a

            point[point_ct][0] = _pkk.pl_index
            point[point_ct][1] = before_set_point
            point_ct += 1

            _pbk = ps0[before_kk]
            dec_count += _pbk.dec_count
            for _ii in range(before_touch_count): _dec_inline(_pbk, spol, ps0)

            _gen = _g_dirty_gen; _dc = _g_dirty_count
            if _pkk.dirty_idx != _gen:
                _pkk.dirty_idx = _gen
                _g_dirty_list[_dc] = kk; _dc += 1
                _g_dirty_count = _dc
            _pkk.use_flag = True

            before_touch_count = _pkk.touch_count
            before_kk          = kk

            if _is_clock:
                kk = _srch_even(_pkk, before_set_point, spol, ps0, gouraud_delay)
            else:
                kk = _srch_odd(_pkk, before_set_point, spol, ps0, gouraud_delay)
            if kk < 0:
                break

            _pkk = ps0[kk]
            _kmk = _pkk.touch_side_map_k; _bkpi = ps0[before_kk].pl_index
            if _kmk[0] == _bkpi: kx = _pkk.touch_side_map_v[0]
            elif _kmk[1] == _bkpi: kx = _pkk.touch_side_map_v[1]
            else: kx = _pkk.touch_side_map_v[2]
            my_a = _pkk.touch_side[kx].my_a
            if my_a == 0:
                before_set_point = 2
            elif my_a == 1:
                before_set_point = 0
            else:
                before_set_point = 1

            point[point_ct][0] = _pkk.pl_index
            point[point_ct][1] = before_set_point
            point_ct += 1

            _pbk = ps0[before_kk]
            dec_count += _pbk.dec_count
            for _ii in range(before_touch_count): _dec_inline(_pbk, spol, ps0)

            _gen = _g_dirty_gen; _dc = _g_dirty_count
            if _pkk.dirty_idx != _gen:
                _pkk.dirty_idx = _gen
                _g_dirty_list[_dc] = kk; _dc += 1
                _g_dirty_count = _dc
            _pkk.use_flag = True

            before_touch_count = _pkk.touch_count
            before_kk          = kk

            if _is_clock:
                kk = _srch_odd(_pkk, before_set_point, spol, ps0, gouraud_delay)
            else:
                kk = _srch_even(_pkk, before_set_point, spol, ps0, gouraud_delay)
            if kk < 0:
                break

    _pbk = ps0[before_kk]
    dec_count += _pbk.dec_count
    for _ii in range(before_touch_count): _dec_inline(_pbk, spol, ps0)

    if stripDisp:
        # Reorder the first 3 vertices according to first_rot and rot
        # so that winding is correct for the hardware.
        if rot == Std_Model.clock:
            if first_rot == 0:
                point[0], point[2] = point[2][:], point[0][:]
            elif first_rot == 1:
                point[1], point[2] = point[2][:], point[1][:]
            elif first_rot == 2:
                point[0], point[1] = point[1][:], point[0][:]
        else:
            if first_rot == 0:
                tmp0, tmp1, tmp2 = point[0][:], point[1][:], point[2][:]
                point[0] = tmp2; point[1] = tmp0; point[2] = tmp1
            elif first_rot == 1:
                pass
            elif first_rot == 2:
                tmp0, tmp1, tmp2 = point[0][:], point[1][:], point[2][:]
                point[0] = tmp1; point[1] = tmp2; point[2] = tmp0

        n = StripData()
        n.pi = [StripData.POINT_INDEX() for _ in range(point_ct)]
        n.next          = self.stripdata
        n._NL_PF_S_INDEX  = False
        n._NL_PF_GOURAUD  = int(gouraud)
        if bump_polygon:
            n._NL_PF_GOURAUD = 0
        n._NL_PF_CULLING  = 1 if now_double_side else rot + 2
        n._NL_PF_STRIP    = 1
        n._NL_PF_TRIANGLE = 0
        n._NL_PF_SPRITE   = 0
        n.tex             = tex
        n.strip_num       = point_ct
        self.stripdata    = n

        for ii in range(point_ct):
            self.put_point_info2(ii, point[ii][0], point[ii][1])

    # Write back dec_count and update before_strip_count.
    if dec_count0 is not None:
        if isinstance(dec_count0, list):
            dec_count0[0] = dec_count
        # (if it's a plain int there is no write-back — caller ignores it)

    if ps0[kk0].before_strip_count < point_ct:
        ps0[kk0].before_strip_count = point_ct

    return point_ct


# Std_Model.srch_polygon_fan0
# Greedy triangle-fan search starting from polygon ps0[kk],
# using touch_side[srch_start_no] as the first fan edge.
# All polygons share the vertex at cen_index (the hub).
# srch_polygon_strip0).

_fan0_point_buf:     list = []
_fan0_point_buf_cap: int  = 0

def _Std_Model_srch_polygon_fan0(
        self:            Std_Model,
        dec_count0,
        srch_start_no:  int,
        kk:             int,
        pnum:           int,
        ps0:            List[PolySrch],
        rot:            int,
        tex:            VOL2_TEX_FLAG,
        now_double_side: bool,
        stripDisp:      bool = False,
) -> int:
    """Greedy triangle-fan search starting at ps0[kk]."""
    global _fan0_point_buf, _fan0_point_buf_cap
    global gouraud
    global _g_dirty_list, _g_dirty_count, _g_dirty_gen

    dec_count   = 0
    spol        = self.polygon

    needed = pnum * 4 + 4
    if needed > _fan0_point_buf_cap:
        _fan0_point_buf_cap = needed + 64
        _fan0_point_buf = [[0, 0] for _ in range(_fan0_point_buf_cap)]
    point = _fan0_point_buf

    first_polygon      = kk
    before_touch_count = ps0[first_polygon].touch_count
    fan_ct             = 1

    now_poly = spol[ps0[kk].touch_side[srch_start_no].t_index].srch_index
    old_poly = kk

    if ps0[kk].dirty_idx != _g_dirty_gen:
        ps0[kk].dirty_idx = _g_dirty_gen
        _g_dirty_list[_g_dirty_count] = kk
        _g_dirty_count += 1
    ps0[kk].use_flag = True

    point_ct = 3
    point[0][0] = ps0[kk].pl_index
    point[1][0] = ps0[kk].pl_index
    point[2][0] = ps0[kk].pl_index

    # Hub vertex index and initial inf_idx assignments depend on rot.
    if rot == Std_Model.clock:
        cen_index = spol[ps0[kk].pl_index].info_list[
            ps0[kk].touch_side[srch_start_no].my_a
        ].point_index
        point[0][1] = ps0[kk].touch_side[srch_start_no].my_a
        point[1][1] = (point[0][1] + 2) % 3
        point[2][1] = (point[0][1] + 1) % 3
    else:
        cen_index = spol[ps0[kk].pl_index].info_list[
            ps0[kk].touch_side[srch_start_no].my_b
        ].point_index
        point[0][1] = ps0[kk].touch_side[srch_start_no].my_b
        point[1][1] = (point[0][1] + 1) % 3
        point[2][1] = (point[0][1] + 2) % 3

    gouraud = spol[ps0[old_poly].pl_index].gr
    before_inf_index = srch_start_no

    _brk0 = False

    while True:
        if spol[ps0[old_poly].pl_index].poly_ID == spol[ps0[now_poly].pl_index].poly_ID:
            pass
        elif gouraud:
            pass
        else:
            if spol[ps0[now_poly].pl_index].gr:
                _brk0 = True

        if _brk0:
            break

        # Accept now_poly into the fan.
        if ps0[now_poly].dirty_idx != _g_dirty_gen:
            ps0[now_poly].dirty_idx = _g_dirty_gen
            _g_dirty_list[_g_dirty_count] = now_poly
            _g_dirty_count += 1
        ps0[now_poly].use_flag = True

        dec_count += ps0[old_poly].dec_count
        for _ii in range(before_touch_count): _dec_touch_count_0_inline(ps0[old_poly], spol, ps0)

        fan_ct += 1

        _nmk = ps0[now_poly].touch_side_map_k; _opi = ps0[old_poly].pl_index
        if _nmk[0] == _opi: kx = ps0[now_poly].touch_side_map_v[0]
        elif _nmk[1] == _opi: kx = ps0[now_poly].touch_side_map_v[1]
        else: kx = ps0[now_poly].touch_side_map_v[2]
        # New vertex index for this fan step.
        point[point_ct][0] = ps0[now_poly].pl_index
        if rot == Std_Model.clock:
            inf = (ps0[now_poly].touch_side[kx].my_b + 1) % 3
        else:
            inf = (ps0[now_poly].touch_side[kx].my_a + 2) % 3
        point[point_ct][1] = inf
        point_ct += 1

        # Bug-check: verify cen_index is still the hub.
        if rot == Std_Model.clock:
            cen2 = spol[ps0[now_poly].touch_side[kx].t_index].info_list[
                ps0[now_poly].touch_side[kx].cm_a
            ].point_index
            if cen_index != cen2:
                print(f"clock hen hen!! {cen_index},{cen2}", file=sys.stderr)
        else:
            cen2 = spol[ps0[now_poly].touch_side[kx].t_index].info_list[
                ps0[now_poly].touch_side[kx].cm_b
            ].point_index
            if cen_index != cen2:
                print(f"rclock hen hen!! {cen_index},{cen2}", file=sys.stderr)

        # Find the next fan edge (kxx): a touch_side of now_poly whose
        kxx = -1
        for i in range(ps0[now_poly].touch_count):
            t = ps0[now_poly].touch_side[i]
            if rot == Std_Model.clock:
                cen3 = spol[t.t_index].info_list[t.cm_b].point_index
            else:
                cen3 = spol[t.t_index].info_list[t.cm_a].point_index
            if cen_index == cen3:
                kxx = i
                break

        old_poly           = now_poly
        before_touch_count = ps0[old_poly].touch_count

        if kxx == -1:
            break

        before_inf_index = kxx
        now_poly = spol[ps0[now_poly].touch_side[kxx].t_index].srch_index

        if now_poly == first_polygon:
            break

    dec_count += ps0[old_poly].dec_count
    for _ii in range(before_touch_count): _dec_touch_count_0_inline(ps0[old_poly], spol, ps0)

    if stripDisp:

        n = StripData()
        n.pi = [StripData.POINT_INDEX() for _ in range(point_ct)]
        n.next           = self.stripdata
        n._NL_PF_S_INDEX = False
        n._NL_PF_GOURAUD = int(gouraud)
        if bump_polygon:
            n._NL_PF_GOURAUD = 0
        n._NL_PF_CULLING  = 1 if now_double_side else rot + 2
        n._NL_PF_STRIP    = 0
        n._NL_PF_TRIANGLE = 0
        n._NL_PF_SPRITE   = 0
        n.tex             = tex
        n.strip_num       = point_ct
        self.stripdata    = n

        for ii in range(point_ct):
            self.put_point_info2(ii, point[ii][0], point[ii][1])

    if dec_count0 is not None:
        if isinstance(dec_count0, list):
            dec_count0[0] = dec_count

    return point_ct


def _Std_Model_init_same_point(self: Std_Model) -> None:
    """Allocate the SAME_POINT array for this model."""
    self.add_count = 0
    self.smp = [SAME_POINT() for _ in range(self.model_all_strip_point_count)]

def _Std_Model_clear_same_point(self: Std_Model) -> None:
    """Free the SAME_POINT array."""
    self.smp = None


# Std_Model.chk_same_point
# Search smp[0..add_count-1] for a matching entry.
# Returns -(i+1) if found (duplicate); otherwise appends a new
# entry and returns i+1 (new, 1-based index).

def _Std_Model_chk_same_point(
        self:         Std_Model,
        point_index:  int,
        nx, ny, nz,
        u,  v,
        vtx_color_A:  int,
        vtx_color_R:  int,
        vtx_color_G:  int,
        vtx_color_B:  int,
        grp_no:       int,
) -> int:
    """Duplicate-vertex check using the smp array."""
    smp = self.smp
    for i in range(self.add_count):
        if (point_index == smp[i].point_index
                and nx.hex() == smp[i].nx.hex()
                and ny.hex() == smp[i].ny.hex()
                and nz.hex() == smp[i].nz.hex()
                and u.hex()  == smp[i].u.hex()
                and v.hex()  == smp[i].v.hex()
                and vtx_color_A == smp[i].vtx_color_A
                and vtx_color_R == smp[i].vtx_color_R
                and vtx_color_G == smp[i].vtx_color_G
                and vtx_color_B == smp[i].vtx_color_B
                and grp_no == smp[i].grp_no):
            return -(i + 1)

    i = self.add_count
    smp[i].point_index = point_index
    smp[i].nx = nx;  smp[i].ny = ny;  smp[i].nz = nz
    smp[i].u  = u;   smp[i].v  = v
    smp[i].vtx_color_A = vtx_color_A
    smp[i].vtx_color_R = vtx_color_R
    smp[i].vtx_color_G = vtx_color_G
    smp[i].vtx_color_B = vtx_color_B
    smp[i].grp_no = grp_no
    self.add_count = i + 1
    return i + 1


# Std_Model.chk_same_point2
# Like chk_same_point but with slot recycling: when flag==1 the
# matching entry's point_index is set to -1 (freed); freed slots
# are reused before appending.

def _Std_Model_chk_same_point2(
        self:         Std_Model,
        point_index:  int,
        nx, ny, nz,
        u,  v,
        vtx_color_A:  int,
        vtx_color_R:  int,
        vtx_color_G:  int,
        vtx_color_B:  int,
        grp_no:       int,
        flag:         int,
) -> int:
    """Duplicate-vertex check with optional slot invalidation."""
    smp = self.smp

    # Pass 1: search for exact match.
    for i in range(self.add_count2):
        if (point_index == smp[i].point_index
                and nx.hex() == smp[i].nx.hex()
                and ny.hex() == smp[i].ny.hex()
                and nz.hex() == smp[i].nz.hex()
                and u.hex()  == smp[i].u.hex()
                and v.hex()  == smp[i].v.hex()
                and vtx_color_A == smp[i].vtx_color_A
                and vtx_color_R == smp[i].vtx_color_R
                and vtx_color_G == smp[i].vtx_color_G
                and vtx_color_B == smp[i].vtx_color_B
                and grp_no == smp[i].grp_no):
            if flag == 1:
                smp[i].point_index = -1
            return -(i + 1)

    # Pass 2: try to reuse a freed slot (point_index == -1).
    for i in range(self.add_count2):
        if smp[i].point_index == -1:
            smp[i].point_index = point_index
            smp[i].nx = nx;  smp[i].ny = ny;  smp[i].nz = nz
            smp[i].u  = u;   smp[i].v  = v
            smp[i].vtx_color_A = vtx_color_A
            smp[i].vtx_color_R = vtx_color_R
            smp[i].vtx_color_G = vtx_color_G
            smp[i].vtx_color_B = vtx_color_B
            smp[i].grp_no = grp_no
            return i + 1

    # Append at the end.
    i = self.add_count2
    smp[i].point_index = point_index
    smp[i].nx = nx;  smp[i].ny = ny;  smp[i].nz = nz
    smp[i].u  = u;   smp[i].v  = v
    smp[i].vtx_color_A = vtx_color_A
    smp[i].vtx_color_R = vtx_color_R
    smp[i].vtx_color_G = vtx_color_G
    smp[i].vtx_color_B = vtx_color_B
    smp[i].grp_no = grp_no
    self.add_count2 = i + 1
    return i + 1


def _Std_Model_init_same_point_sort_sidx(self: Std_Model) -> None:
    self.add_count = 0
    self.smp = [SAME_POINT() for _ in range(self.model_all_strip_point_count)]

def _Std_Model_clear_same_point_sort_sidx(self: Std_Model) -> None:
    self.smp = None


# Std_Model.chk_same_point_sort_sidx
# Read-only existence check: returns True if the entry already
# exists in smp[0..add_count-1], False otherwise.

def _Std_Model_chk_same_point_sort_sidx(
        self:         Std_Model,
        point_index:  int,
        nx, ny, nz,
        u,  v,
        vtx_color_A:  int,
        vtx_color_R:  int,
        vtx_color_G:  int,
        vtx_color_B:  int,
        grp_no:       int,
) -> bool:
    smp = self.smp
    for i in range(self.add_count):
        if (point_index == smp[i].point_index
                and nx.hex() == smp[i].nx.hex()
                and ny.hex() == smp[i].ny.hex()
                and nz.hex() == smp[i].nz.hex()
                and u.hex()  == smp[i].u.hex()
                and v.hex()  == smp[i].v.hex()
                and vtx_color_A == smp[i].vtx_color_A
                and vtx_color_R == smp[i].vtx_color_R
                and vtx_color_G == smp[i].vtx_color_G
                and vtx_color_B == smp[i].vtx_color_B
                and grp_no == smp[i].grp_no):
            return True
    return False


# Std_Model.set_same_point_sort_sidx
# Write-or-skip: if the entry already exists, return immediately;
# otherwise append it to smp and increment add_count.

def _Std_Model_set_same_point_sort_sidx(
        self:         Std_Model,
        point_index:  int,
        nx, ny, nz,
        u,  v,
        vtx_color_A:  int,
        vtx_color_R:  int,
        vtx_color_G:  int,
        vtx_color_B:  int,
        grp_no:       int,
) -> None:
    smp = self.smp
    for i in range(self.add_count):
        if (point_index == smp[i].point_index
                and nx.hex() == smp[i].nx.hex()
                and ny.hex() == smp[i].ny.hex()
                and nz.hex() == smp[i].nz.hex()
                and u.hex()  == smp[i].u.hex()
                and v.hex()  == smp[i].v.hex()
                and vtx_color_A == smp[i].vtx_color_A
                and vtx_color_R == smp[i].vtx_color_R
                and vtx_color_G == smp[i].vtx_color_G
                and vtx_color_B == smp[i].vtx_color_B
                and grp_no == smp[i].grp_no):
            return

    i = self.add_count
    smp[i].point_index = point_index
    smp[i].nx = nx;  smp[i].ny = ny;  smp[i].nz = nz
    smp[i].u  = u;   smp[i].v  = v
    smp[i].vtx_color_A = vtx_color_A
    smp[i].vtx_color_R = vtx_color_R
    smp[i].vtx_color_G = vtx_color_G
    smp[i].vtx_color_B = vtx_color_B
    smp[i].grp_no = grp_no
    self.add_count = i + 1


gouraud: bool = False

# Std_Model.srch_polygon_strip
# Python stub that delegate to strip0
# with dec_count0=None, srch_start_no=0.

def _Std_Model_srch_polygon_strip(
        self:            Std_Model,
        kk:             int,
        pnum:           int,
        ps0:            List[PolySrch],
        rot:            int,
        tex:            VOL2_TEX_FLAG,
        now_double_side: bool,
        stripDisp:      bool = False,
) -> int:
    return self.srch_polygon_strip0(
        None, 0, kk, pnum, ps0, rot, tex, now_double_side, stripDisp
    )


# Option globals needed by put_point_info
# These are module-level names so that put_point_info can access
# them without importing NlcvOptions.  apply_options() (called by
# the main driver) overwrites them from the live NlcvOptions.

flat_not_normal_calc: bool = False
super_index_format:  bool  = False
allScale:            float = 1.0

# NAOMI polygon vertex format sizes (bytes):
#   Format2 = pos(3) + normal(3) + uv(2)  = 8 floats = 32 bytes
#   Format3 = pos(3) + normal(3)           = 6 floats = 24 bytes
#   Format4 = pos(3) + normal(3) + tn0(3) + tn1(3) + uv(2) = 14 floats = 56 bytes
_NL_PF_PolygonFormat2_size: int = 32
_NL_PF_PolygonFormat3_size: int = 24
_NL_PF_PolygonFormat4_size: int = 56
_NL_PF_PolygonFormat0_size: int = 32
_NL_PF_PolygonFormat1_size: int = 24

# get_dk9

def get_dk9(
        va: int, vr: int, vg: int, vb: int
) -> tuple:
    """Compute the dk9 dual vertex-colour split."""
    def _u8(x: int) -> int:
        return x & 0xFF

    va2 = _u8(va);  vr2 = _u8(vr);  vg2 = _u8(vg);  vb2 = _u8(vb)

    va2 = 0 if (_u8(va2) - 0x80) & 0x100 else _u8(va2 - 0x80)
    vr2 = 0 if (_u8(vr2) - 0x80) & 0x100 else _u8(vr2 - 0x80)
    vg2 = 0 if (_u8(vg2) - 0x80) & 0x100 else _u8(vg2 - 0x80)
    vb2 = 0 if (_u8(vb2) - 0x80) & 0x100 else _u8(vb2 - 0x80)

    # Signed comparison (int)va2 - 0x80 < 0:
    def _below80(x):
        return (x - 0x80) & 0x80 != 0

    va2 = 0 if _below80(va) else _u8(va - 0x80)
    vr2 = 0 if _below80(vr) else _u8(vr - 0x80)
    vg2 = 0 if _below80(vg) else _u8(vg - 0x80)
    vb2 = 0 if _below80(vb) else _u8(vb - 0x80)

    va2 = _u8(va2 << 1);  vr2 = _u8(vr2 << 1)
    vg2 = _u8(vg2 << 1);  vb2 = _u8(vb2 << 1)
    vtcl2 = (va2 << 24) | (vr2 << 16) | (vg2 << 8) | vb2

    def _clamp(x):
        return 0xFF if not _below80(x) else _u8(x - 0x80)

    va_c = _clamp(va);  vr_c = _clamp(vr)
    vg_c = _clamp(vg);  vb_c = _clamp(vb)

    va_c = _u8(va_c << 1);  vr_c = _u8(vr_c << 1)
    vg_c = _u8(vg_c << 1);  vb_c = _u8(vb_c << 1)
    vtcl = (va_c << 24) | (vr_c << 16) | (vg_c << 8) | vb_c

    return vtcl, vtcl2

def f2i255(x: float) -> int:
    """Map float → signed 8-bit value clamped to [-128, 127], returned as"""
    xx = int(x * 128)
    if xx > 127:
        xx = 127
    elif xx < -128:
        xx = -128
    return xx & 0xFF

def f2u255(x: float) -> int:
    """Map float → unsigned 8-bit value clamped to [0, 255]."""
    xx = int(x * 255)
    if xx > 255:
        xx = 255
    elif xx < 0:
        xx = 0
    return xx & 0xFF


put_point_all:    int = 0
put_repoint_all:  int = 0


# Std_Model.put_point_info
# Emits one vertex record to the binary output stream.
# Block structure
# A. Normal selection (gouraud vs flat, use_direct_normal branch)
# B. Texture UV selection (tex==1 with optional crop, else 0,0)
# C. Super-index-format path (reused-point back-reference or new)
# D. Position emit + directy cluster match
# E. Normal / vertex-colour emit
#        with optional dk9 split or vtx_dummy_zero
# F. Bump tex-normal emit (tnx0/tny0/tnz0 + tnx1/tny1/tnz1)
# G. UV emit (32-bit or 16-bit packed)

def _Std_Model_put_point_info(
        self:      Std_Model,
        _no:       int,
        pol_idx:   int,
        inf_idx:   int,
        tex:       bool,
        sp_idx:    int,
        flag:      int,
) -> None:

    global put_point_all, put_repoint_all, object_all_address

    spnt = self.point_list
    spol = self.polygon

    point_index = spol[pol_idx].info_list[inf_idx].point_index

    # A. Normal selection
    if spol[pol_idx].gr and not bump_polygon:
        # Gouraud: per-vertex normal (use_direct_normal always True)
        nx = spol[pol_idx].info_list[inf_idx].nx
        ny = spol[pol_idx].info_list[inf_idx].ny
        nz = spol[pol_idx].info_list[inf_idx].nz
    else:
        # Flat: face normal
        if not flat_not_normal_calc:
            nx = spol[pol_idx].normal.x
            ny = spol[pol_idx].normal.y
            nz = spol[pol_idx].normal.z
        else:
            nx = spol[pol_idx].info_list[inf_idx].nx
            ny = spol[pol_idx].info_list[inf_idx].ny
            nz = spol[pol_idx].info_list[inf_idx].nz

    nx2 = nx;  ny2 = ny;  nz2 = nz

    # B. UV selection  (use_cropping branch is dead — `if(1 || ...)`)
    if tex:
        u = Std_Float(float(spol[pol_idx].info_list[inf_idx].u))
        v = Std_Float(-float(spol[pol_idx].info_list[inf_idx].v))
    else:
        u = Std_Float(0.0);  v = Std_Float(0.0)

    # C. Super-index-format path
    if super_index_format:
        idx = -sp_idx
        put_point_all += 1

        if idx <= 0:
            # New point — record its address.
            self.index_to_dma_address[-idx] = self.DMA_ADRS
            self.index_to_ram_address[-idx] = self.RAM_ADRS
            self.DMA_ADRS += 32
        else:
            # Reused point — emit back-reference pair.
            put_repoint_all += 1

            dif_dma = self.DMA_ADRS - self.index_to_dma_address[idx]
            dif_ram = self.RAM_ADRS - self.index_to_ram_address[idx]

            e_dif_dma = dif_dma | 0xA0000000
            r_dif_ram = -(dif_ram + 8)

            # Mask to 32-bit unsigned so %08x formats correctly (no "0x-..." output)
            _dma_u32 = (-e_dif_dma) & 0xFFFFFFFF
            _ram_u32 = r_dif_ram    & 0xFFFFFFFF

            write_le32((-e_dif_dma) & 0xFFFFFFFF)
            write_le32(r_dif_ram & 0xFFFFFFFF)

            self.RAM_ADRS += 8
            object_all_address += 8
            self.DMA_ADRS += 32
            return

    # D. Position emit + directy cluster comment
    xp = Std_Float(float(spnt[point_index].x))
    yp = Std_Float(float(spnt[point_index].y))
    zp = Std_Float(float(spnt[point_index].z))

    # Apply coordinate-system flips.

    xp = Std_Float(float(xp) * allScale)
    yp = Std_Float(float(yp) * allScale)
    zp = Std_Float(float(zp) * allScale)

    # Emit position words.
    write_le32(xp.hex() | 1)
    write_le32(yp.hex())
    write_le32(zp.hex())

    # Advance address counters.
    if True:
        if not bump_polygon:
            self.RAM_ADRS          += _NL_PF_PolygonFormat2_size
            object_all_address += _NL_PF_PolygonFormat2_size
        else:
            self.RAM_ADRS          += _NL_PF_PolygonFormat4_size
            object_all_address += _NL_PF_PolygonFormat4_size
    else:
        self.RAM_ADRS          += _NL_PF_PolygonFormat3_size
        object_all_address += _NL_PF_PolygonFormat3_size

    # E. Normal / vertex-colour emit
    mat = self.material[spol[pol_idx].material_index]

    # Declare tnx0/tnx1 etc. here so they're in scope for block F.
    tnx0 = tny0 = tnz0 = tnx1 = tny1 = tnz1 = Std_Float(0.0)

    if mat.shading_type != 7 or bump_polygon:
        # E1 — float normal words
        if bump_polygon:
            # E1a — bump path: same_bump optimisation
            same_bump = 0

            tnx0 = spol[pol_idx].tex_normal0.x
            tny0 = spol[pol_idx].tex_normal0.y
            tnz0 = spol[pol_idx].tex_normal0.z

            tnx1 = Std_Float(-float(spol[pol_idx].tex_normal1.x))
            tny1 = Std_Float(-float(spol[pol_idx].tex_normal1.y))
            tnz1 = Std_Float(-float(spol[pol_idx].tex_normal1.z))

            global chk_before_bump_nrm_ct
            global chk_before_bump_nrm_x, chk_before_bump_nrm_y, chk_before_bump_nrm_z
            global chk_before_bump_nrm0_x, chk_before_bump_nrm0_y, chk_before_bump_nrm0_z
            global chk_before_bump_nrm1_x, chk_before_bump_nrm1_y, chk_before_bump_nrm1_z

            if (nx == chk_before_bump_nrm_x and
                    ny == chk_before_bump_nrm_y and
                    nz == chk_before_bump_nrm_z and
                    tnx0 == chk_before_bump_nrm0_x and
                    tny0 == chk_before_bump_nrm0_y and
                    tnz0 == chk_before_bump_nrm0_z and
                    tnx1 == chk_before_bump_nrm1_x and
                    tny1 == chk_before_bump_nrm1_y and
                    tnz1 == chk_before_bump_nrm1_z):
                chk_before_bump_nrm_ct += 1
                same_bump = 1

            chk_before_bump_nrm_x  = nx;   chk_before_bump_nrm_y  = ny
            chk_before_bump_nrm_z  = nz
            chk_before_bump_nrm0_x = tnx0; chk_before_bump_nrm0_y = tny0
            chk_before_bump_nrm0_z = tnz0
            chk_before_bump_nrm1_x = tnx1; chk_before_bump_nrm1_y = tny1
            chk_before_bump_nrm1_z = tnz1

            nrml_word = (nx.hex() & ~1) | same_bump
            write_le32(nrml_word & 0xFFFFFFFF)
            write_le32(ny.hex())
            write_le32(nz.hex())

        else:
            # E1b — plain flat/gouraud normal
            write_le32(nx.hex())
            write_le32(ny.hex())
            write_le32(nz.hex())

    else:
        # E2 — shading_type == 7, not bump: packed nrml + vertex colour
        # NL1 (naomi2hg=False): write packed normal + colour pair
        # NL2 (naomi2hg=True):  packed_nrml + base_float + offset_float
        nrml = (
            (f2i255(float(nx)) << 16) |
            (f2i255(float(ny)) << 8)  |
            f2i255(float(nz))
        ) & 0xFFFFFFFF

        va = spol[pol_idx].info_list[inf_idx].vtx_color_A & 0xFF
        vr = spol[pol_idx].info_list[inf_idx].vtx_color_R & 0xFF
        vg = spol[pol_idx].info_list[inf_idx].vtx_color_G & 0xFF
        vb = spol[pol_idx].info_list[inf_idx].vtx_color_B & 0xFF

        if naomi2hg:
            # NL2: packed ARGB uint32 colour pair via get_dk9
            vtcl = (va << 24) | (vr << 16) | (vg << 8) | vb
            vtcl_out, vtcl2 = vtcl, vtcl

            write_le32(nrml)
            write_le32(vtcl_out & 0xFFFFFFFF)
            write_le32(vtcl2   & 0xFFFFFFFF)
        else:
            # NL1: write packed normal + colour pair
            vtcl = (va << 24) | (vr << 16) | (vg << 8) | vb

            write_le32(nrml);  write_le32(vtcl);  write_le32(vtcl)

    # F. Bump tex-normal emit (only when bump_polygon)
    if bump_polygon:
        write_le32(tnx0.hex()); write_le32(tny0.hex()); write_le32(tnz0.hex())
        write_le32(tnx1.hex()); write_le32(tny1.hex()); write_le32(tnz1.hex())

    # G. UV emit
    if True:
        write_le32(u.hex())
        write_le32(v.hex() | 1)

# naomi2hg_put_point_info
# NAOMI2 / "naomi2hg" variant of put_point_info.
# Controlled by the compile-time flag naomi2hg; in Python we gate
# on the module-level bool opts.naomi2hg (set by -naomi2hg/-naomi2).
# When opts.naomi2hg is False the function returns immediately,
# mirroring the empty #ifdef naomi2hg … #endif body.
# Block structure
# A. Normal selection (gouraud vs flat, use_direct_normal branch)
# B. Texture UV selection (tex==1 / non_tex_set_white_tex fallback)
# C. Super-index-format path (new-point or reused-point back-ref)
# D. Position emit + directy cluster matching + tag comment
# E. Normal / vertex-colour emit
#        E1b. plain gouraud/flat
#        (naomi2hg and non-naomi2hg paths differ)
# F. Bump tex-normal emit (tnx0/1 + tny0/1 + tnz0/1)
# G. UV emit (32-bit floats, naomi2hg path; skipped for env_map ES2)


def _Std_Model_naomi2hg_put_point_info(
        self:    "Std_Model",
        no:      int,
        pol_idx: int,
        inf_idx: int,
        tex:     bool,
        sp_idx:  int,
        flag:    int,
        v_type:  int,
        v_end:   int,
        sas:     "SAVE_ALL_STRIP",
) -> None:
    if not naomi2hg:
        return

    global naomi2hg_all_address, object_all_address
    global chk_before_bump_nrm_ct
    global chk_before_bump_nrm_x,  chk_before_bump_nrm_y,  chk_before_bump_nrm_z
    global chk_before_bump_nrm0_x, chk_before_bump_nrm0_y, chk_before_bump_nrm0_z
    global chk_before_bump_nrm1_x, chk_before_bump_nrm1_y, chk_before_bump_nrm1_z
    global bump_polygon, env_map_polygon
    global super_index_format
    global allScale
    global flat_not_normal_calc

    spnt = self.point_list
    spol = self.polygon

    point_index = spol[pol_idx].info_list[inf_idx].point_index

    # A. Normal selection
    if spol[pol_idx].gr and not bump_polygon:
        # Gouraud shading — per-vertex normal (use_direct_normal always True)
        nx = Std_Float(spol[pol_idx].info_list[inf_idx].nx)
        ny = Std_Float(spol[pol_idx].info_list[inf_idx].ny)
        nz = Std_Float(spol[pol_idx].info_list[inf_idx].nz)
    else:
        # Flat shading — per-polygon normal
        if not flat_not_normal_calc:
            nx = Std_Float(spol[pol_idx].normal.x)
            ny = Std_Float(spol[pol_idx].normal.y)
            nz = Std_Float(spol[pol_idx].normal.z)
        else:
            nx = Std_Float(spol[pol_idx].info_list[inf_idx].nx)
            ny = Std_Float(spol[pol_idx].info_list[inf_idx].ny)
            nz = Std_Float(spol[pol_idx].info_list[inf_idx].nz)

    # Keep unmodified copies for directy matching and same_bump check
    nx2 = Std_Float(float(nx))
    ny2 = Std_Float(float(ny))
    nz2 = Std_Float(float(nz))

    # B. UV selection
    if tex:
        u = Std_Float(float(spol[pol_idx].info_list[inf_idx].u))
        v = Std_Float(-float(spol[pol_idx].info_list[inf_idx].v))
    else:
        u = Std_Float(0.0)
        v = Std_Float(0.0)

    # C. Super-index-format path
    if super_index_format:
        idx = -sp_idx

        self.put_point_all += 1

        if idx <= 0:
            # New point: record its addresses
            self.index_to_dma_address[-idx] = self.DMA_ADRS
            self.index_to_ram_address[-idx] = self.RAM_ADRS

            # Both tex and no-tex use the same DMA stride here
            self.DMA_ADRS += 32

        else:
            # Reused point: emit back-reference offsets
            self.put_repoint_all += 1

            dif_dma = self.DMA_ADRS - self.index_to_dma_address[idx]
            dif_ram = self.RAM_ADRS - self.index_to_ram_address[idx]

            # OR with 0xa0000000 to flag as DMA back-reference
            e_dif_dma = dif_dma | 0xa0000000
            # Negative RAM delta: accounts for `mov @R_poly+,r0; add R_poly,r0`
            r_dif_ram = -(dif_ram + 8)

            if flag == 0:
                write_le32((-e_dif_dma) & 0xFFFFFFFF)
                write_le32(r_dif_ram    & 0xFFFFFFFF)
            else:
                write_le32((-e_dif_dma) & 0xFFFFFFFF)
                write_le32(r_dif_ram    & 0xFFFFFFFF)

            self.RAM_ADRS        += 8
            object_all_address += 8

            self.DMA_ADRS += 32
            return

    # D. Position emit + directy cluster matching
    xp = Std_Float(spnt[point_index].x)
    yp = Std_Float(spnt[point_index].y)
    zp = Std_Float(spnt[point_index].z)

    # Coordinate-system flips

    # Global scale
    xp = Std_Float(float(xp) * allScale)
    yp = Std_Float(float(yp) * allScale)
    zp = Std_Float(float(zp) * allScale)

    nrml = (
        (f2i255(float(nx)) << 0)  |
        (f2i255(float(ny)) << 8)  |
        (f2i255(float(nz)) << 16)
    )

    # Topology byte (bits[31:24] of flag_word) 
    # Encoding (from NL2 SDK / importer):
    #   no==0,1        → 0x00  BT0  (base triangle vertices 0 and 1)
    #   no==2          → 0x60  BT1  (base triangle vertex 2)
    #   no>=3, strip   → 0x20  Strip continuation (v_type==0)
    #   no>=3, fan     → 0x40  Fan continuation   (v_type==1)
    #   v_end != 0     → OR 0x80  (last vertex of strip)
    if no <= 1:
        topo_byte = 0x00
    elif no == 2:
        topo_byte = 0x60
    else:
        topo_byte = 0x20 if v_type == 0 else 0x40
    if v_end:
        topo_byte |= 0x80

    flag_word = (topo_byte << 24) | (nrml & 0x00FFFFFF)
    write_le32(flag_word)

    write_le32(xp.hex())
    write_le32(yp.hex())
    write_le32(zp.hex())

    # Address accounting (RAM / object / naomi2hg)
    # E. Normal / vertex-colour emit
    mat = self.material[spol[pol_idx].material_index]

    if True:
        if not bump_polygon:
            self.RAM_ADRS          += _NL_PF_PolygonFormat2_size
            object_all_address += _NL_PF_PolygonFormat2_size
        else:
            self.RAM_ADRS          += _NL_PF_PolygonFormat4_size
            object_all_address += _NL_PF_PolygonFormat4_size
    else:
        self.RAM_ADRS          += _NL_PF_PolygonFormat3_size
        object_all_address += _NL_PF_PolygonFormat3_size

    # naomi2hg_all_address advances: each vertex is always 24 bytes (6 words):
    # The shading type and bump do not change per-vertex size in the binary output.
    if not bump_polygon:
        naomi2hg_all_address += 24

        # ES2 env-map (es1_5 == False): UV slot absent
        if env_map_polygon:
            naomi2hg_all_address -= 8
    else:
        naomi2hg_all_address += 40

    # G. UV emit — naomi2hg path
    # Binary: words 4-5 — u (f32) and v (f32, already negated in section B)

    if not env_map_polygon:
        if True:
            write_le32(u.hex())
            write_le32(v.hex())

    _DK_MAT_PHONG    = 4
    _DK_MAT_CONSTANT = 1

    if mat.shading_type != 7 or bump_polygon:
        # E1 — float normal words
        if bump_polygon:
            # E1a — bump: compute tex_normals; same_bump optimisation
            same_bump = 0

            tnx0 = Std_Float( spol[pol_idx].tex_normal0.x)
            tny0 = Std_Float( spol[pol_idx].tex_normal0.y)
            tnz0 = Std_Float( spol[pol_idx].tex_normal0.z)
            tnx1 = Std_Float(-spol[pol_idx].tex_normal1.x)
            tny1 = Std_Float(-spol[pol_idx].tex_normal1.y)
            tnz1 = Std_Float(-spol[pol_idx].tex_normal1.z)

            if (
                float(nx)   == chk_before_bump_nrm_x  and
                float(ny)   == chk_before_bump_nrm_y  and
                float(nz)   == chk_before_bump_nrm_z  and
                float(tnx0) == chk_before_bump_nrm0_x and
                float(tny0) == chk_before_bump_nrm0_y and
                float(tnz0) == chk_before_bump_nrm0_z and
                float(tnx1) == chk_before_bump_nrm1_x and
                float(tny1) == chk_before_bump_nrm1_y and
                float(tnz1) == chk_before_bump_nrm1_z
            ):
                chk_before_bump_nrm_ct += 1
                same_bump = 1

            # Update accumulators
            chk_before_bump_nrm_x  = float(nx)
            chk_before_bump_nrm_y  = float(ny)
            chk_before_bump_nrm_z  = float(nz)
            chk_before_bump_nrm0_x = float(tnx0)
            chk_before_bump_nrm0_y = float(tny0)
            chk_before_bump_nrm0_z = float(tnz0)
            chk_before_bump_nrm1_x = float(tnx1)
            chk_before_bump_nrm1_y = float(tny1)
            chk_before_bump_nrm1_z = float(tnz1)

        else:
            # E1b — flat/gouraud, naomi2hg path: no nx/ny/nz printf here
            #   (the normal is already baked into the SetVertex nrml word above)
            pass

    else:
        # E2 — shading_type == 7, not bump_polygon: packed ARGB uint32 colour pair.
        # NL2 naomi2hg path emits two colour words only (nrml already in SetVertex).

        va = spol[pol_idx].info_list[inf_idx].vtx_color_A & 0xFF
        vr = spol[pol_idx].info_list[inf_idx].vtx_color_R & 0xFF
        vg = spol[pol_idx].info_list[inf_idx].vtx_color_G & 0xFF
        vb = spol[pol_idx].info_list[inf_idx].vtx_color_B & 0xFF

        vtcl = (va << 24) | (vr << 16) | (vg << 8) | vb

        # Colour words written after UV — matches order: flag+xyz+uv+vtcl+vtcl2
        write_le32(vtcl & 0xFFFFFFFF)
        write_le32(vtcl & 0xFFFFFFFF)
    # F. Bump tex-normal emit (naomi2hg path)
    if bump_polygon:
        mc0 = sas.mc[0]
        offset_scale = (
            (f2u255(mc0.face_offset_color_R)     << 8) |
             f2u255(mc0.face_offset_color_alpha)
        )
        tx0nrml = (
            (f2i255(float(tnx0)) << 0)  |
            (f2i255(float(tny0)) << 8)  |
            (f2i255(float(tnz0)) << 16)
        )
        tx1nrml = (
            (f2i255(float(tnx1)) << 0)  |
            (f2i255(float(tny1)) << 8)  |
            (f2i255(float(tnz1)) << 16)
        )
        write_le32(offset_scale & 0xFFFFFFFF)
        write_le32(tx0nrml     & 0xFFFFFFFF)
        write_le32(tx1nrml     & 0xFFFFFFFF)
        write_le32(0)


# Std_Model.chk_si_rate
# "Super-index rate check": called once per vertex slot before
# the actual vertex write in put_point_info / naomi2hg_put_point_info.
# Two branches depending on the sign of sp_idx:
#   idx = -sp_idx
#               Record the current RAM address in index_to_ram_address
#               and advance RAM_ADRS by the appropriate polygon-format
#               size.  Returns -1 (caller proceeds to write the full
#               vertex record).
#               vertex.  Compute the byte distance from the stored RAM
#               address to the current one, decide cache-on (1) or
#               cache-off (0), and potentially update
#               s.sort_flag_byte_diff if the distance is smaller.
#               Advance RAM_ADRS by 8 bytes (the repoint stub size).
#               Returns 1 (cache on) or 0 (cache off).
# When super_index_format is False the function is a no-op that
# returns -1 unconditionally.

def _Std_Model_chk_si_rate(
        self:   Std_Model,
        s:      "StripData",
        sp_idx: int,
) -> int:
    """Check super-index reuse rate for the vertex encoded by *sp_idx*."""
    if not super_index_format:
        return -1

    idx = -sp_idx

    if idx <= 0:
        # Defining occurrence: store current RAM address and advance.
        self.index_to_ram_address[-idx] = self.RAM_ADRS

        if True:
            self.RAM_ADRS += _NL_PF_PolygonFormat2_size
        else:
            self.RAM_ADRS += _NL_PF_PolygonFormat3_size

        return -1

    else:
        # Back-reference: measure distance to the original definition.
        dif_ram = self.RAM_ADRS - self.index_to_ram_address[idx]

        if dif_ram < 16 * 1024:
            ret = 1
        else:
            ret = 0

        if dif_ram < s.sort_flag_byte_diff:
            s.sort_flag_byte_diff = dif_ram

        self.RAM_ADRS += 8

        return ret


# Std_Model.put_point_info2
# Simple helper: store (pol_idx, inf_idx) into the strip-data
# point-index table at slot *no*.  No output, no address tracking.

def _Std_Model_put_point_info2(
        self:    Std_Model,
        no:      int,
        pol_idx: int,
        inf_idx: int,
) -> None:
    self.stripdata.pi[no].pol_idx = pol_idx
    self.stripdata.pi[no].inf_idx = inf_idx


# Std_Model.chk_sprite

def _Std_Model_chk_sprite(self: Std_Model) -> None:
    """Sets _NL_PF_SPRITE = 1 on every StripData node when the whole"""
    DK_MAT_CONSTANT = 1

    s = self.stripdata
    polygon  = self.polygon
    material = self.material

    # Pass 1 — quick-reject + normal-equality check across all nodes
    while s is not None:

        if s._NL_PF_S_INDEX != 0:
            return
        if s._NL_PF_CULLING != 2:
            return
        if s._NL_PF_TRIANGLE != 0:
            return
        if s.strip_num != 4:
            return

        # Reference vertex: use pi[0] for gouraud, pi[2] for flat
        pol_idx0 = s.pi[0].pol_idx
        inf_idx0 = s.pi[0].inf_idx
        i_start  = 1

        if not polygon[s.pi[0].pol_idx].gr:
            pol_idx0 = s.pi[2].pol_idx
            inf_idx0 = s.pi[2].inf_idx
            i_start  = 3

        pol_id0 = polygon[s.pi[0].pol_idx].poly_ID

        # Reference normals (per-vertex and face)
        nx0  = polygon[pol_idx0].info_list[inf_idx0].nx0
        ny0  = polygon[pol_idx0].info_list[inf_idx0].ny0
        nz0  = polygon[pol_idx0].info_list[inf_idx0].nz0

        nx0f = polygon[pol_idx0].normal.x
        ny0f = polygon[pol_idx0].normal.y
        nz0f = polygon[pol_idx0].normal.z

        for i in range(i_start, s.strip_num):
            pol_idx = s.pi[i].pol_idx
            inf_idx = s.pi[i].inf_idx
            pol_id  = polygon[pol_idx].poly_ID

            if not polygon[pol_idx].gr:
                if pol_id == pol_id0:
                    continue

            # Constant-shading same-polygon: skip
            if material[polygon[pol_idx].material_index].shading_type == DK_MAT_CONSTANT:
                if pol_id == pol_id0:
                    continue

            # Normal equality test
            if not polygon[pol_idx].gr:
                # Flat polygon: compare face normals
                if not same_float(nx0f, polygon[pol_idx].normal.x):
                    return
                if not same_float(ny0f, polygon[pol_idx].normal.y):
                    return
                if not same_float(nz0f, polygon[pol_idx].normal.z):
                    return
            else:
                # Gouraud polygon: compare per-vertex normals (nx0/ny0/nz0)
                if not same_float(nx0, polygon[pol_idx].info_list[inf_idx].nx0):
                    return
                if not same_float(ny0, polygon[pol_idx].info_list[inf_idx].ny0):
                    return
                if not same_float(nz0, polygon[pol_idx].info_list[inf_idx].nz0):
                    return

        s = s.next

    # Pass 2 — all nodes passed: flag every strip as a sprite
    s = self.stripdata
    while s is not None:
        s._NL_PF_SPRITE = 1
        s = s.next


# cmp_gflag  (module-level comparator)
# Compare the "geometry flags" of two StripData nodes to decide
# whether they can be grouped into the same polygon-format pass.
# Two comparison modes, selected by the combination of
# all_point_light_model and bump_polygon:
#   all_point_light_model==False  OR  bump_polygon==True
#   else (all_point_light_model==True AND bump_polygon==False)
#       naomi2hg path skips STRIP/TRIANGLE/SPRITE
# In all cases CULLING must match.

def cmp_gflag(g0: "StripData", g1: "StripData") -> bool:

    # GOURAUD must match in addition to CULLING
    if naomi2hg:
        return (g0._NL_PF_GOURAUD == g1._NL_PF_GOURAUD and
                g0._NL_PF_CULLING  == g1._NL_PF_CULLING)
    else:
        return (g0._NL_PF_GOURAUD  == g1._NL_PF_GOURAUD  and
                g0._NL_PF_CULLING  == g1._NL_PF_CULLING   and
                g0._NL_PF_STRIP    == g1._NL_PF_STRIP     and
                g0._NL_PF_TRIANGLE == g1._NL_PF_TRIANGLE  and
                g0._NL_PF_SPRITE   == g1._NL_PF_SPRITE)

# Std_Model.sort_gflag

def _Std_Model_sort_gflag(self: Std_Model) -> None:
    """Sort the stripdata list by geometry-flag groups."""
    self.skip_count = 0

    new_pt: "StripData | None" = None

    while self.stripdata is not None:

        # Snapshot the first node's flags as the group key for this pass
        start    = self.stripdata
        not_gp   = 0
        first    = True
        before: "StripData | None" = None
        s        = self.stripdata

        while s is not None:

            if cmp_gflag(start, s) and start.grp_no == s.grp_no:

                # Mark group membership flag
                s._NL_PF_NOT_GP = not_gp
                not_gp = 1

                # Accumulate skip_count with this strip's byte contribution
                if True:
                    if not bump_polygon:
                        self.skip_count += (4 + 4 +
                            s.strip_num * _NL_PF_PolygonFormat0_size)
                    else:
                        self.skip_count += (4 + 4 +
                            s.strip_num * _NL_PF_PolygonFormat4_size)
                else:
                    self.skip_count += (4 + 4 +
                        s.strip_num * _NL_PF_PolygonFormat1_size)

                # Unlink *s* from the original list
                if first:
                    self.stripdata = s.next
                else:
                    before.next = s.next

                next_tmp = s.next

                # Append *s* to the tail of new_pt
                if new_pt is None:
                    new_pt = s
                else:
                    p = new_pt
                    while p.next is not None:
                        p = p.next
                    p.next = s

                s.next = None
                s = next_tmp

            else:
                before = s
                s      = s.next
                first  = False

    # Replace stripdata with the sorted list
    self.stripdata = new_pt


# Std_Model.chk_repoint

def _Std_Model_chk_repoint(self: Std_Model) -> None:
    """Compute shared-point back-reference indices for all strips."""

    self.skip_count = 0
    self.add_count2 = 0
    self.add_count0 = 0

    spol     = self.polygon
    material = self.material

    # Pass 1 — assign sp_idx via chk_same_point
    s = self.stripdata
    while s is not None:
        for i in range(s.strip_num):
            pol_idx     = s.pi[i].pol_idx
            inf_idx     = s.pi[i].inf_idx
            point_index = spol[pol_idx].info_list[inf_idx].point_index

            # Normal selection (use_direct_normal always True)
            nx: Std_Float
            ny: Std_Float
            nz: Std_Float
            if spol[pol_idx].gr:
                nx = Std_Float(spol[pol_idx].info_list[inf_idx].nx)
                ny = Std_Float(spol[pol_idx].info_list[inf_idx].ny)
                nz = Std_Float(spol[pol_idx].info_list[inf_idx].nz)
            else:
                nx = Std_Float(spol[pol_idx].normal.x)
                ny = Std_Float(spol[pol_idx].normal.y)
                nz = Std_Float(spol[pol_idx].normal.z)
            # UV selection
            u: Std_Float
            v: Std_Float
            if s.tex.v0 == 1:
                u = Std_Float(float(spol[pol_idx].info_list[inf_idx].u))
                v = Std_Float(float(spol[pol_idx].info_list[inf_idx].v) - 1.0)
            else:
                u = Std_Float(0.0)
                v = Std_Float(0.0)

            va = spol[pol_idx].info_list[inf_idx].vtx_color_A & 0xFF
            vr = spol[pol_idx].info_list[inf_idx].vtx_color_R & 0xFF
            vg = spol[pol_idx].info_list[inf_idx].vtx_color_G & 0xFF
            vb = spol[pol_idx].info_list[inf_idx].vtx_color_B & 0xFF

            idx = self.chk_same_point(
                point_index, nx, ny, nz, u, v, va, vr, vg, vb,
                s.grp_no,
            )
            s.pi[i].sp_idx = idx

        s = s.next

    s = self.stripdata
    while s is not None:
        for i in range(s.strip_num):
            s.pi[i].flag = 0

            spidx = s.pi[i].sp_idx
            if spidx > 0:
                spidx = -spidx

            # Search the rest of this strip
            found = False
            t = s
            for j in range(i + 1, t.strip_num):
                if t.pi[j].sp_idx == spidx:
                    found = True
                    break

            # Search subsequent strips
            if not found:
                t = s.next
                while t is not None:
                    for j in range(t.strip_num):
                        if t.pi[j].sp_idx == spidx:
                            found = True
                            break
                    if found:
                        break
                    t = t.next

            if not found:
                s.pi[i].flag = 1

        s = s.next

    # Pass 3 — skip_count accumulation + final sp_idx fixup
    self.skip_count = 0
    self.add_count2 = 0
    self.add_count0 = 0

    beta = True

    s = self.stripdata
    while s is not None:
        self.skip_count += 4 + 4

        for i in range(s.strip_num):

            if s.pi[i].sp_idx > 0 and s.pi[i].flag == 1:
                # Force full-record emit (cancel repoint)
                s.pi[i].sp_idx = 0
                self.add_count0 += 1

                if True:
                    if not bump_polygon:
                        self.skip_count += _NL_PF_PolygonFormat2_size
                    else:
                        self.skip_count += _NL_PF_PolygonFormat4_size
                else:
                    self.skip_count += _NL_PF_PolygonFormat3_size

            else:
                # Normal path: re-check via chk_same_point2
                pol_idx     = s.pi[i].pol_idx
                inf_idx     = s.pi[i].inf_idx
                point_index = spol[pol_idx].info_list[inf_idx].point_index

                nx2: Std_Float
                ny2: Std_Float
                nz2: Std_Float
                if spol[pol_idx].gr:
                    nx2 = Std_Float(spol[pol_idx].info_list[inf_idx].nx)
                    ny2 = Std_Float(spol[pol_idx].info_list[inf_idx].ny)
                    nz2 = Std_Float(spol[pol_idx].info_list[inf_idx].nz)
                else:
                    nx2 = Std_Float(spol[pol_idx].normal.x)
                    ny2 = Std_Float(spol[pol_idx].normal.y)
                    nz2 = Std_Float(spol[pol_idx].normal.z)
                u2: Std_Float
                v2: Std_Float
                if s.tex.v0 == 1:
                    u2 = Std_Float(float(spol[pol_idx].info_list[inf_idx].u))
                    v2 = Std_Float(float(spol[pol_idx].info_list[inf_idx].v) - 1.0)
                else:
                    u2 = Std_Float(0.0)
                    v2 = Std_Float(0.0)

                va2 = spol[pol_idx].info_list[inf_idx].vtx_color_A & 0xFF
                vr2 = spol[pol_idx].info_list[inf_idx].vtx_color_R & 0xFF
                vg2 = spol[pol_idx].info_list[inf_idx].vtx_color_G & 0xFF
                vb2 = spol[pol_idx].info_list[inf_idx].vtx_color_B & 0xFF

                idx2 = self.chk_same_point2(
                    point_index, nx2, ny2, nz2, u2, v2,
                    va2, vr2, vg2, vb2,
                    s.grp_no, s.pi[i].flag,
                )
                s.pi[i].sp_idx = idx2

                if idx2 > 0:
                    # Full vertex record
                    if True:
                        if not bump_polygon:
                            self.skip_count += _NL_PF_PolygonFormat2_size
                        else:
                            self.skip_count += _NL_PF_PolygonFormat4_size
                    else:
                        self.skip_count += _NL_PF_PolygonFormat3_size
                else:
                    # Back-reference repoint stub (2 words = 8 bytes)
                    beta = False
                    self.skip_count += 4 * 2

        s = s.next

    # _NL_PF_S_INDEX decision
    # First pass: clear all flags
    s = self.stripdata
    while s is not None:
        s._NL_PF_S_INDEX = False
        s = s.next

    if not beta:
        s = self.stripdata
        while s is not None:
            s._NL_PF_S_INDEX = True
            s = s.next


# Std_Model.get_si_rate
# Runs init_same_point / chk_repoint then walks the strip list, calling
# chk_si_rate for every vertex to count super-index-able (si) and
# non-super-index-able (nsi) vertices.  Also sets sort_flag0 on each
# strip that has at least one nsi vertex.
# Returns (all_count, si_count, nsi_count).

def _Std_Model_get_si_rate(self: "Std_Model"):
    self.DMA_ADRS = 0
    self.RAM_ADRS = 0

    self.init_same_point()
    self.chk_repoint()

    self.index_to_ram_address = [0] * (self.add_count2 + 1)

    all_count  = 0
    si_count   = 0
    nsi_count  = 0

    s = self.stripdata
    while s is not None:
        s.sort_flag0 = 0
        s.sort_flag_byte_diff = 0

        self.RAM_ADRS += 4 * 2

        strip_nsi = 0
        for i in range(s.strip_num):
            r = self.chk_si_rate(s, s.pi[i].sp_idx)
            all_count += 1
            if r == -1:
                pass
            elif r == 0:
                nsi_count += 1
                strip_nsi += 1
            elif r == 1:
                si_count += 1

        if strip_nsi != 0:
            s.sort_flag0 = 1

        s = s.next

    self.index_to_ram_address = None
    self.clear_same_point()

    return all_count, si_count, nsi_count


# Std_Model.sort_sidx
# Reorders the stripdata linked list so that strips with reusable vertices
# (super-index hits) are placed earlier, improving cache locality.
# method 0/1: move the first profitable strip forward to just after
#             all_srch_max position (method 0 additionally skips strips
#             whose strip_num would be bigger).
# method 2:   choose the globally best strip and move it.

def _Std_Model_sort_sidx(self: "Std_Model", method: int) -> None:

    # Count total strips
    i_max_max = 0
    s = self.stripdata
    while s is not None:
        i_max_max += 1
        s = s.next

    all_srch_max = 1

    while True:
        max_repoint_count = 0
        max_repoint       = 0
        more_add          = 0

        for i_max in range(all_srch_max, i_max_max):
            self.init_same_point_sort_sidx()
            repoint_count = 0

            # Walk to strip at position (all_srch_max-1), feeding vertices in
            s = self.stripdata
            for _i in range(all_srch_max - 1):
                s = s.next

            # Feed the strip at all_srch_max-1 into the same-point table
            for _i in range(all_srch_max - 1, all_srch_max):
                for j in range(s.strip_num):
                    il = self.polygon[s.pi[j].pol_idx].info_list[s.pi[j].inf_idx]
                    self.set_same_point_sort_sidx(
                        il.point_index,
                        il.nx, il.ny, il.nz,
                        il.u, il.v,
                        il.vtx_color_A, il.vtx_color_R,
                        il.vtx_color_G, il.vtx_color_B,
                        s.grp_no,
                    )
                s = s.next

            # Advance to strip at position i_max
            for _i in range(all_srch_max, i_max):
                s = s.next

            # Count repoints for strip at i_max
            for j in range(s.strip_num):
                il = self.polygon[s.pi[j].pol_idx].info_list[s.pi[j].inf_idx]
                flag = self.chk_same_point_sort_sidx(
                    il.point_index,
                    il.nx, il.ny, il.nz,
                    il.u, il.v,
                    il.vtx_color_A, il.vtx_color_R,
                    il.vtx_color_G, il.vtx_color_B,
                    s.grp_no,
                )
                if flag:
                    repoint_count += 1

            if repoint_count > max_repoint_count:
                max_repoint_count = repoint_count
                max_repoint       = i_max

            if method in (0, 1):
                if repoint_count > 0:
                    more_add += 1

                    # Find strip at i_max and its predecessor
                    b = None
                    s = self.stripdata
                    for _i in range(i_max):
                        b = s
                        s = s.next

                    # Find strip at all_srch_max and its predecessor
                    ss = self.stripdata
                    bb = None
                    for _i in range(all_srch_max):
                        bb = ss
                        ss = ss.next

                    if method == 0:
                        # Skip forward while ss.strip_num <= s.strip_num
                        for _k in range(1, more_add):
                            if ss is None:
                                break
                            if ss.strip_num > s.strip_num:
                                break
                            bb = ss
                            ss = ss.next

                    # Splice: remove s from position i_max,
                    b.next  = s.next
                    s.next  = bb.next
                    bb.next = s

            self.clear_same_point_sort_sidx()

        if method == 2:
            if max_repoint > 1:
                b = None
                s = self.stripdata
                for _i in range(max_repoint):
                    b = s
                    s = s.next

                ss = self.stripdata
                bb = None
                for _i in range(all_srch_max):
                    bb = ss
                    ss = ss.next

                b.next  = s.next
                s.next  = bb.next
                bb.next = s

        all_srch_max += 1
        if all_srch_max >= i_max_max:
            break
        # (the second goto more_sort with += 1 + more_add is dead code
        #  because the first break already exits; omitted faithfully)


# Std_Model.sort_sidx2
# Shuffles strips that still have sort_flag0==1 (non-super-indexable) by
# finding one such strip and moving it to a different position determined
# by `sub`, trying to break up bad orderings.

def _Std_Model_sort_sidx2(self: "Std_Model", sub: int) -> None:
    # Count strips with sort_flag0 != 0
    ct = 0
    s = self.stripdata
    while s is not None:
        if s.sort_flag0 != 0:
            ct += 1
        s = s.next

    i_max_max = 0
    s = self.stripdata
    while s is not None:
        i_max_max += 1
        s = s.next

    while ct > 0:
        r0 = 0
        s = self.stripdata
        for i in range(i_max_max):
            r0 += 1
            s = s.next
            if s is None:
                break
            if s.sort_flag0 != 0:
                break

        r1 = i_max_max - (sub % i_max_max)
        r1 = r0 - r1
        if r1 >= i_max_max:
            r1 = i_max_max - 1
        if r1 <= 0:
            r1 = 1

        # Find node at r0 and its predecessor
        b = None
        s = self.stripdata
        for i in range(r0):
            b = s
            s = s.next

        # Find node at r1 and its predecessor
        ss = self.stripdata
        bb = None
        for i in range(r1):
            bb = ss
            ss = ss.next

        if (b is not None and s is not None and
                bb is not None and bb is not s and
                bb.grp_no == s.grp_no):
            if s.sort_flag0 != 0:
                s.sort_flag0 = 0

                b.next  = s.next
                s.next  = bb.next
                bb.next = s

            ct -= 1
        else:
            # No valid swap found: break to avoid infinite loop
            break


# Std_Model.all_sort_sidx
# Iteratively calls sort_sidx / sort_sidx2 until no non-super-indexable
# vertices remain or the iteration budget is exhausted.  Restores the
# best-seen ordering via opt_next links.

def _Std_Model_all_sort_sidx(self: "Std_Model") -> None:
    import sys

    # Snapshot baseline si-rate
    all_count, si_count, nsi_count = self.get_si_rate()

    sys.stderr.write(
        f"\ndefault si rate\nall_count : {all_count}\n"
        f"all_si_count : {si_count + nsi_count}\n"
        f"si_count : {si_count}\n"
        f"nsi_count : {nsi_count}\n"
    )

    if nsi_count == 0:
        return

    opt_count = nsi_count

    # Save current order as opt_next
    s = self.stripdata
    while s is not None:
        s.opt_next = s.next
        s = s.next

    sort_count     = 0
    sort_count_max = 100

    sort_sidx_count = 3
    down_sinai_count = sort_sidx_count
    sort_call_ct     = 0
    sort_call_ct0    = sort_sidx_count + 1
    if sort_call_ct0 > 6:
        sort_call_ct0 = 6

    while True:
        if (sort_call_ct % sort_call_ct0) == 0:
            self.sort_sidx(0)
        sort_call_ct += 1

        all_count, si_count, nsi_count = self.get_si_rate()

        sys.stderr.write(
            f"\nall_count : {all_count}\n"
            f"all_si_count : {si_count + nsi_count}\n"
            f"si_count : {si_count}\n"
            f"nsi_count : {nsi_count}\n"
        )

        if opt_count > nsi_count:
            sort_count += 1
            opt_count   = nsi_count

            # Save improved order
            s = self.stripdata
            while s is not None:
                s.opt_next = s.next
                s = s.next

            down_sinai_count += sort_sidx_count
            sys.stderr.write(
                f"good!! down count : {sort_count},{sort_count_max},"
                f"{down_sinai_count}\n"
            )
        else:
            down_sinai_count -= 1
            sys.stderr.write(
                f"best is {opt_count} , down count : {sort_count},"
                f"{sort_count_max},{down_sinai_count}\n"
            )

        if opt_count <= 0 or sort_count_max <= 0 or down_sinai_count <= 0:
            break
        sort_count_max -= 1

        import random
        random.seed(1234 + nsi_count + sort_count_max)
        self.sort_sidx2(sort_call_ct + 1)

    # Restore best-seen order through opt_next links
    s = self.stripdata
    while s is not None:
        s.next = s.opt_next
        s = s.opt_next


# Std_Model.all_sort_sidx_grp
# Runs all_sort_sidx separately for each group number so that strips from
# different groups are never interleaved during optimisation.  After all
# groups are processed it recomputes _NL_PF_NOT_GP for the full merged list.

def _Std_Model_all_sort_sidx_grp(self: "Std_Model") -> None:
    # Find max grp_no
    max_grp_no = 0
    s = self.stripdata
    while s is not None:
        if s.grp_no > max_grp_no:
            max_grp_no = s.grp_no
        s = s.next

    for chk_grp_no in range(max_grp_no + 1):
        tmp0 = self.stripdata

        # Find first strip with this grp_no and its predecessor
        b    = None
        s    = self.stripdata
        tmp  = self.stripdata
        btmp = None
        while s is not None:
            if s.grp_no == chk_grp_no:
                tmp  = s
                btmp = b
                break
            b = s
            s = s.next

        # Detach the group sub-list
        self.stripdata = tmp

        # Find the last strip of this group
        b = None
        s = self.stripdata
        while s is not None and s.grp_no == chk_grp_no:
            b = s
            s = s.next

        ntmp    = b.next
        b.next  = None

        self.all_sort_sidx()

        # Re-attach: if there was a predecessor, link it to the (now
        if btmp is not None:
            btmp.next = self.stripdata

        # Walk to end of this group's sub-list and re-attach tail
        s = self.stripdata
        while s is not None and s.grp_no == chk_grp_no:
            b = s
            s = s.next
        b.next = ntmp

        # Restore full list head
        self.stripdata = tmp0

    # Recompute _NL_PF_NOT_GP for the merged list
    s = self.stripdata
    if s is not None:
        first  = True
        before = s
        while s is not None:
            if first:
                s._NL_PF_NOT_GP = 0
                first = False
            elif cmp_gflag(before, s):
                s._NL_PF_NOT_GP = 1
            else:
                s._NL_PF_NOT_GP = 0
            before = s
            s = s.next


# Std_Model.put_strip_point
# Entry point called per-material.  When output_after_all is False it
# immediately calls put_strip_point2; when True it saves the SAVE_ALL_STRIP
# into the appropriate list for deferred emission by all_put_strip_point.

def _Std_Model_put_strip_point(
        self: "Std_Model",
        mat_index: int,
        sas: "SAVE_ALL_STRIP",
) -> None:

    global save_all_strip_opq, save_all_strip_trs, save_all_strip_pch

    self.add_count2 = 0

    self.add_count2 = 0
    self.DMA_ADRS   = 0
    self.RAM_ADRS   = 0

    self.sort_gflag()

    sort_sidx_cache = getattr(sys.modules[__name__], "sort_sidx_cache", False)
    if (sort_sidx_cache and
            super_index_format and
            self.skip_count > 16 * 1024 and
            self.stripdata is not None and
            self.stripdata.next is not None):
        self.all_sort_sidx_grp()

    self.DMA_ADRS = 0
    self.RAM_ADRS = 0

    if not output_after_all:
        if super_index_format:
            self.init_same_point()
            self.chk_repoint()
            mat_printf(
                "  %d,\t/* skip_byte ( + &gflag) */\n", self.skip_count
            )
            write_le32(self.skip_count & 0xFFFFFFFF)
        else:
            mat_printf(
                "  %d,\t/* skip_byte ( + &gflag) */\n", self.skip_count
            )
            write_le32(self.skip_count & 0xFFFFFFFF)

    self.chk_sprite()

    if not output_after_all and super_index_format:
        self.clear_same_point()

    if output_after_all:
        # Select the right deferred list
        if sas.list_type == 0:
            last = save_all_strip_opq
        elif sas.list_type == 2:
            last = save_all_strip_trs
        elif sas.list_type == 4:
            last = save_all_strip_pch
        else:
            last = None

        if last is None:
            if sas.list_type == 0:
                save_all_strip_opq = sas
            elif sas.list_type == 2:
                save_all_strip_trs = sas
            elif sas.list_type == 4:
                save_all_strip_pch = sas
        else:
            while last.next is not None:
                last = last.next
            last.next = sas

        sas.model              = self
        sas.mat_index          = mat_index
        sas.bump_polygon       = bump_polygon
        sas.bump_polygon_dup   = bump_polygon_dup
        sas.bump_polygon_trs   = bump_polygon_trs
        sas.env_map_polygon    = env_map_polygon
        sas.super_index_format = super_index_format
        sas.skip_count         = self.skip_count

        sas.add_count          = self.add_count
        sas.add_count0         = self.add_count0
        sas.add_count2         = self.add_count2

        sas.all_strip_ct           = all_strip_ct
        sas.all_once_ct            = all_once_ct
        sas.all_fan_ct             = all_fan_ct
        sas.file_all_point_count   = file_all_point_count
        sas.file_all_polygon_count = file_all_polygon_count

        sas.stripdata = self.stripdata
        sas.next      = None
        return

    self.put_strip_point2(mat_index, None)


# global_info_disp
# Writes the 6-word binary model header (format flag, global status flags,
# bounding sphere centre x/y/z and radius).

def global_info_disp(null_flag: int) -> None:

    if ((after_output_sta & (1 << PSTA_ZERO_MODEL)) or
            after_output_nullmodel or
            null_flag):
        format_flag = -1
    elif after_output_super_index_format:
        format_flag = 1
    else:
        format_flag = 0

    write_le32(format_flag & 0xFFFFFFFF)
    write_le32((after_output_sta | 1) & 0xFFFFFFFF)
    write_le32(after_output_mcx.hex())
    write_le32(after_output_mcy.hex())
    write_le32(after_output_mcz.hex())
    write_le32(after_output_mcr.hex())


class MODEL_ALL_INFO:
    def __init__(self) -> None:
        self.allsize    : int = 0
        self.allvtxnum  : int = 0
        self.allsendpvr : int = 0
        self.allsendgmp : int = 0

# Constant: size of the NAOMI2 object-tag header (bytes).
_naomi2hg_OBJTAG_SIZE: int = 96

# naomi2hg_global_info_disp
# Writes the 24-word NAOMI2 object-tag header containing bounding sphere,
# total sizes, per-list offsets, etc.  The body is compiled only when
# naomi2hg is defined; in our Python port the flag is runtime `naomi2hg`.

def naomi2hg_global_info_disp(
        opq: MODEL_ALL_INFO,
        trs: MODEL_ALL_INFO,
        pch: MODEL_ALL_INFO,
) -> None:
    """Writes the 24-word (96-byte) NAOMI2 object-tag header to the binary stream,"""

    global naomi2hg_all_address

    # Guard — only active in naomi2hg (NAOMI2) mode
    if not naomi2hg:
        return

    naomi2hg_all_address += _naomi2hg_OBJTAG_SIZE

    null_model = ((after_output_sta & (1 << PSTA_ZERO_MODEL)) or
                  after_output_nullmodel)

    # Word 0: format flag (0x100 = naomi2hg, -1 = null model)
    if null_model:
        write_le32(0xFFFFFFFF)
    else:
        write_le32(0x100)

    # Word 1: global status flags
    write_le32((after_output_sta | 1) & 0xFFFFFFFF)

    if null_model:
        # Null model — pad remaining 22 words with zero so the header
        for _ in range(22):
            write_le32(0)
        return

    # Words 2-5: bounding sphere (cx, cy, cz, radius) as IEEE 754 floats
    write_le32(after_output_mcx.hex())
    write_le32(after_output_mcy.hex())
    write_le32(after_output_mcz.hex())
    write_le32(after_output_mcr.hex())

    # Word 6: total byte size of all strip data + this header
    all_size = (opq.allsize + trs.allsize + pch.allsize
                + _naomi2hg_OBJTAG_SIZE)
    write_le32(all_size & 0xFFFFFFFF)

    # Word 7: tag version (always 0)
    write_le32(0)

    # Word 8: total polygon count
    write_le32(file_all_polygon_count & 0xFFFFFFFF)

    # Word 9: total vertex count
    all_vtx = opq.allvtxnum + trs.allvtxnum + pch.allvtxnum
    write_le32(all_vtx & 0xFFFFFFFF)

    # Word 10: total global-parameter sends
    all_gmp = opq.allsendgmp + trs.allsendgmp + pch.allsendgmp
    write_le32(all_gmp & 0xFFFFFFFF)

    # Word 11: total PVR-header sends
    all_pvr = opq.allsendpvr + trs.allsendpvr + pch.allsendpvr
    write_le32(all_pvr & 0xFFFFFFFF)

    # Words 12-14: reserved
    write_le32(0)
    write_le32(0)
    write_le32(0)

    # Word 15: alloc size (always 0 — filled in by runtime loader)
    write_le32(0)

    # Words 16-17: opaque list offset + size
    if opq.allsize > 0:
        opq_offset = _naomi2hg_OBJTAG_SIZE - 16 * 4
        write_le32(opq_offset & 0xFFFFFFFF)
        write_le32(opq.allsize & 0xFFFFFFFF)
    else:
        write_le32(0)
        write_le32(0)

    # Words 18-19: translucent list offset + size
    if trs.allsize > 0:
        trs_offset = opq.allsize + _naomi2hg_OBJTAG_SIZE - 18 * 4
        write_le32(trs_offset & 0xFFFFFFFF)
        write_le32(trs.allsize & 0xFFFFFFFF)
    else:
        write_le32(0)
        write_le32(0)

    # Words 20-21: punch-through list offset + size
    if pch.allsize > 0:
        pch_offset = opq.allsize + trs.allsize + _naomi2hg_OBJTAG_SIZE - 20 * 4
        write_le32(pch_offset & 0xFFFFFFFF)
        write_le32(pch.allsize & 0xFFFFFFFF)
    else:
        write_le32(0)
        write_le32(0)

    # Words 22-23: reserved
    write_le32(0)
    write_le32(0)

# get_info_stripdata
# Calculates the total byte footprint and vertex count for one strip chain,
# as well as how many gflag (GMP-style parameter) headers it will generate.
# Returns (byte_size, vertex_num, send_gflag_count).

def get_info_stripdata(
        strp,
        shading_type: int,
        bump_polygon_flag: bool,
        env: bool,
) -> tuple:

    byte_size        = 0
    vertex_num       = 0
    send_gflag_count = 0

    s = strp
    while s is not None:
        if s._NL_PF_NOT_GP == 0:
            send_gflag_count += 1

        vertex_num += s.strip_num

        nrm = 0

        if bump_polygon_flag:
            byte_size += s.strip_num * (40 + nrm)
        else:
            _env = env
            if _env:
                if shading_type == 7:
                    byte_size += s.strip_num * (32 - 8 + nrm)
                else:
                    byte_size += s.strip_num * (24 - 8 + nrm)
            else:
                if shading_type == 7:
                    byte_size += s.strip_num * (32 + nrm)
                else:
                    byte_size += s.strip_num * (24 + nrm)

        s = s.next

    if strp is not None:
        byte_size += 32 + 32
        byte_size += send_gflag_count * 32

    return byte_size, vertex_num, send_gflag_count

# all_put_scan_list_info
# Accumulates byte-size, vertex count, GMP count and PVR count for every
# SAVE_ALL_STRIP entry in a list.
# Returns (allsize, allvtxnum, allsendgmp, allsendpvr).

def all_put_scan_list_info(sas) -> tuple:
    allsize    = 0
    allvtxnum  = 0
    allsendpvr = 0
    allsendgmp = 0

    while sas is not None:
        allsendgmp += 1

        size, vtx_num, sendpvr = get_info_stripdata(
            sas.stripdata,
            sas.model.material[sas.mat_index].shading_type,
            sas.bump_polygon,
            sas.env_map_polygon,
        )

        allsize    += size
        allvtxnum  += vtx_num
        allsendpvr += sendpvr

        sas = sas.next

    return allsize, allvtxnum, allsendgmp, allsendpvr

# naomi2hg_gloss  lookup table
# 300-entry table mapping an integer exponent [0..300] to an 8-bit packed
# gloss value used by the NAOMI2 GMP header.

naomi2hg_gloss: list = [
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x07, 0x0d, 0x14, 0x1a, 0x20,
    0x24, 0x27, 0x2a, 0x2d, 0x30, 0x34, 0x37, 0x3a, 0x3d, 0x40,
    0x42, 0x44, 0x45, 0x47, 0x48, 0x4a, 0x4c, 0x4d, 0x4f, 0x50,
    0x52, 0x54, 0x55, 0x57, 0x58, 0x5a, 0x5c, 0x5d, 0x5f, 0x60,
    0x61, 0x62, 0x63, 0x64, 0x64, 0x65, 0x66, 0x67, 0x68, 0x68,
    0x69, 0x6a, 0x6b, 0x6c, 0x6c, 0x6d, 0x6e, 0x6f, 0x70, 0x70,
    0x71, 0x72, 0x73, 0x74, 0x74, 0x75, 0x76, 0x77, 0x78, 0x78,
    0x79, 0x7a, 0x7b, 0x7c, 0x7c, 0x7d, 0x7e, 0x7f, 0x80, 0x80,
    0x81, 0x81, 0x82, 0x82, 0x82, 0x83, 0x83, 0x84, 0x84, 0x84,
    0x85, 0x85, 0x86, 0x86, 0x86, 0x87, 0x87, 0x88, 0x88, 0x88,
    0x89, 0x89, 0x8a, 0x8a, 0x8a, 0x8b, 0x8b, 0x8c, 0x8c, 0x8c,
    0x8d, 0x8d, 0x8e, 0x8e, 0x8e, 0x8f, 0x8f, 0x90, 0x90, 0x90,
    0x91, 0x91, 0x92, 0x92, 0x92, 0x93, 0x93, 0x94, 0x94, 0x94,
    0x95, 0x95, 0x96, 0x96, 0x96, 0x97, 0x97, 0x98, 0x98, 0x98,
    0x99, 0x99, 0x9a, 0x9a, 0x9a, 0x9b, 0x9b, 0x9c, 0x9c, 0x9c,
    0x9d, 0x9d, 0x9e, 0x9e, 0x9e, 0x9f, 0x9f, 0xa0, 0xa0, 0xa0,
    0xa1, 0xa1, 0xa1, 0xa1, 0xa1, 0xa2, 0xa2, 0xa2, 0xa2, 0xa2,
    0xa3, 0xa3, 0xa3, 0xa3, 0xa3, 0xa4, 0xa4, 0xa4, 0xa4, 0xa4,
    0xa5, 0xa5, 0xa5, 0xa5, 0xa5, 0xa6, 0xa6, 0xa6, 0xa6, 0xa6,
    0xa7, 0xa7, 0xa7, 0xa7, 0xa7, 0xa8, 0xa8, 0xa8, 0xa8, 0xa8,
    0xa9, 0xa9, 0xa9, 0xa9, 0xa9, 0xaa, 0xaa, 0xaa, 0xaa, 0xaa,
    0xab, 0xab, 0xab, 0xab, 0xab, 0xac, 0xac, 0xac, 0xac, 0xac,
    0xad, 0xad, 0xad, 0xad, 0xad, 0xae, 0xae, 0xae, 0xae, 0xae,
    0xaf, 0xaf, 0xaf, 0xaf, 0xaf, 0xb0, 0xb0, 0xb0, 0xb0, 0xb0,
    0xb1, 0xb1, 0xb1, 0xb1, 0xb1, 0xb2, 0xb2, 0xb2, 0xb2, 0xb2,
    0xb3, 0xb3, 0xb3, 0xb3, 0xb3, 0xb4, 0xb4, 0xb4, 0xb4, 0xb4,
    0xb5, 0xb5, 0xb5, 0xb5, 0xb5, 0xb6, 0xb6, 0xb6, 0xb6, 0xb6,
    0xb7, 0xb7, 0xb7, 0xb7, 0xb7, 0xb8, 0xb8, 0xb8, 0xb8, 0xb8,
    0xb9, 0xb9, 0xb9, 0xb9, 0xb9, 0xba, 0xba, 0xba, 0xba, 0xba,
    0xbb, 0xbb, 0xbb, 0xbb, 0xbb, 0xbc, 0xbc, 0xbc, 0xbc,
]

# Reverse lookup: packed gloss byte -> first matching exponent index in
# naomi2hg_gloss.  Used by the importer to convert the raw g0 byte read from
# a binary back into the exponent index that the exporter expects in mat.exp.
naomi2hg_gloss_reverse: dict = {}
for _i, _v in enumerate(naomi2hg_gloss):
    if _v not in naomi2hg_gloss_reverse:
        naomi2hg_gloss_reverse[_v] = _i

# naomi2hg_packed
# Packs four float colour channels [0.0, 1.0] into one 32-bit ARGB word.
# Each channel is clamped to [0, 255] before packing.

def naomi2hg_packed(a: float, r: float, g: float, b: float) -> int:
    if not naomi2hg:
        return 0

    def _clamp(x: float) -> int:
        v = int(x * 255)
        if v < 0:   v = 0
        if v > 255: v = 255
        return v

    ret  = _clamp(a) << 24
    ret |= _clamp(r) << 16
    ret |= _clamp(g) <<  8
    ret |= _clamp(b)
    return ret

# naomi2hg_put_gmp

def naomi2hg_put_gmp(sas: "SAVE_ALL_STRIP") -> None:
    """Emits the 64-byte GMP block (Global Material Parameter) for NAOMI2:"""
    if not naomi2hg:
        return

    global naomi2hg_all_address

    naomi2hg_all_address += 32 + 32

    mat = sas.model.material[sas.mat_index]

    # Hardcoded NL2 constant
    # NOT derived from NL_PF_ fields — the GMP uses its own parameter control word.
    PCW_GMP = 0x08000500
    write_le32(PCW_GMP)

    # Layout: byte[0]=para0_gloss, byte[1]=para1_gloss, byte[2]=0, byte[3]=0
    if sas.use2para == 0:
        exp = max(0, min(300, mat.exp))
        g0 = naomi2hg_gloss[exp]
        g1 = g0
    else:
        exp0 = max(0, min(300, mat.exp))
        exp1 = max(0, min(300, mat.Vol2para.exp))
        g0 = naomi2hg_gloss[exp0]
        g1 = naomi2hg_gloss[exp1]
    gloss_val = (g1 << 8) | g0
    write_le32(gloss_val & 0xFFFFFFFF)

    env = sas.env_map_polygon

    if sas.use2para == 0:
        diffuse_color = naomi2hg_packed(
            float(sas.mc[0].face_color_alpha),
            float(sas.mc[0].face_color_R),
            float(sas.mc[0].face_color_G),
            float(sas.mc[0].face_color_B),
        )
        specular_color = naomi2hg_packed(
            float(sas.mc[0].face_offset_color_alpha),
            float(sas.mc[0].face_offset_color_R),
            float(sas.mc[0].face_offset_color_G),
            float(sas.mc[0].face_offset_color_B),
        )

        # Bit layout (from NL2):
        def _make_select_word(s0, s1, b0, b1, env_flag):
            return (
                (s0 << 31) | (s0 << 30) | (s0 << 29) | (s0 << 28) |
                (s1 << 27) | (s1 << 26) | (s1 << 25) | (s1 << 24) |
                (b0 << 22) | (b1 << 21) |
                (env_flag << 2) | (env_flag << 1)
            )

        if not sas.bump_polygon:
            st = mat.shading_type
            if st == 7:
                select_word = _make_select_word(0, 0, 1, 1, env)
                diff0, spec0 = diffuse_color, specular_color
                diff1, spec1 = diffuse_color, specular_color
            elif st == DK_MAT_PHONG:
                select_word = _make_select_word(1, 1, 0, 0, env)
                diff0, spec0 = diffuse_color, specular_color
                diff1, spec1 = diffuse_color, specular_color
            elif st == DK_MAT_CONSTANT:
                select_word = _make_select_word(1, 1, 1, 1, env)
                diff0, spec0 = diffuse_color, 0
                diff1, spec1 = diffuse_color, 0
            else:
                select_word = _make_select_word(1, 1, 0, 0, env)
                diff0, spec0 = diffuse_color, 0
                diff1, spec1 = diffuse_color, 0
        else:
            select_word = _make_select_word(1, 1, 0, 0, 0)
            if sas.bump_polygon_trs:
                dc = diffuse_color & 0xFF000000
                diff0, spec0 = dc, 0
                diff1, spec1 = dc, 0
            else:
                diff0, spec0 = diffuse_color, 0
                diff1, spec1 = diffuse_color, 0

        write_le32(select_word & 0xFFFFFFFF)
        write_le32(diff0 & 0xFFFFFFFF)
        write_le32(spec0 & 0xFFFFFFFF)
        write_le32(diff1 & 0xFFFFFFFF)
        write_le32(spec1 & 0xFFFFFFFF)

    else:
        def _pack_mc(mc):
            return naomi2hg_packed(
                float(mc.face_color_alpha),
                float(mc.face_color_R),
                float(mc.face_color_G),
                float(mc.face_color_B),
            )
        def _pack_mc_spec(mc):
            return naomi2hg_packed(
                float(mc.face_offset_color_alpha),
                float(mc.face_offset_color_R),
                float(mc.face_offset_color_G),
                float(mc.face_offset_color_B),
            )

        diffuse_color0  = _pack_mc(sas.mc[0])
        specular_color0 = _pack_mc_spec(sas.mc[0])
        diffuse_color1  = _pack_mc(sas.mc[1])
        specular_color1 = _pack_mc_spec(sas.mc[1])

        s0, b0 = 0, 0
        s1, b1 = 0, 0

        if not sas.bump_polygon:
            st0 = mat.shading_type
            if st0 == 7:
                b0 = 1
            elif st0 == DK_MAT_PHONG:
                s0 = 1
            elif st0 == DK_MAT_CONSTANT:
                s0 = 1; b0 = 1; specular_color0 = 0
            else:
                s0 = 1; specular_color0 = 0
        else:
            s0 = 1
            diffuse_color0 &= 0xFF000000; specular_color0 = 0

        if not sas.bump_polygon:
            st1 = mat.Vol2para.shading_type
            if st1 == 7:
                b1 = 1
            elif st1 == DK_MAT_PHONG:
                s1 = 1
            elif st1 == DK_MAT_CONSTANT:
                s1 = 1; b1 = 1; specular_color1 = 0
            else:
                s1 = 1; specular_color1 = 0
        else:
            s1 = 1
            diffuse_color1 &= 0xFF000000; specular_color1 = 0

        select_word = (
            (s0 << 31) | (s0 << 30) | (s0 << 29) | (s0 << 28) |
            (s1 << 27) | (s1 << 26) | (s1 << 25) | (s1 << 24) |
            (b0 << 22) | (b1 << 21) |
            (env << 2) | (env << 1)
        )
        write_le32(select_word & 0xFFFFFFFF)
        write_le32(diffuse_color0  & 0xFFFFFFFF)
        write_le32(specular_color0 & 0xFFFFFFFF)
        write_le32(diffuse_color1  & 0xFFFFFFFF)
        write_le32(specular_color1 & 0xFFFFFFFF)

    write_le32(0)

    # PCW_NULL = end-of-list sentinel = 0x00000000
    PCW_NULL = 0x08000000

    def _emit_tex_pal(mc, mat_ref, is_bump):
        write_le32(PCW_NULL)
        if mc.texture_flag:
            tex_id = mc.tex_id if mc.tex_id >= 0 else -1
            write_le32(tex_id & 0xFFFFFFFF)
        else:
            write_le32(0xFFFFFFFF)

        write_le32(PCW_NULL)
        if mc.palette_flag >= 1:
            pal_id = mc.pal_direct_num if mc.palette_flag == 2 else -1
            write_le32(pal_id & 0xFFFFFFFF)
        else:
            write_le32(0xFFFFFFFF)

    _emit_tex_pal(sas.mc[0], mat, sas.bump_polygon)

    if sas.use2para == 0:
        # Duplicate para-0 for para-1
        _emit_tex_pal(sas.mc[0], mat, sas.bump_polygon)
    else:
        mat2 = mat.Vol2para
        _emit_tex_pal(sas.mc[1], mat2, sas.bump_polygon)

# all_put_strip_point0
# Drains one SAVE_ALL_STRIP list: for each entry it restores globals,
# emits the GMP block (or mat_disp_buff), calls put_strip_point2, emits
# the end-marker buffer, and frees the node.

def all_put_strip_point0(sas: "SAVE_ALL_STRIP") -> None:
    global bump_polygon, bump_polygon_dup, bump_polygon_trs, env_map_polygon

    while sas is not None:
        # Restore per-material globals from the saved snapshot
        bump_polygon       = sas.bump_polygon
        bump_polygon_trs   = sas.bump_polygon_trs
        bump_polygon_dup   = sas.bump_polygon_dup
        env_map_polygon    = sas.env_map_polygon
        super_index_format = sas.super_index_format

        sas.model.add_count  = sas.add_count
        sas.model.add_count0 = sas.add_count0
        sas.model.add_count2 = sas.add_count2

        all_strip_ct           = sas.all_strip_ct
        all_once_ct            = sas.all_once_ct
        all_fan_ct             = sas.all_fan_ct
        file_all_point_count   = sas.file_all_point_count
        file_all_polygon_count = sas.file_all_polygon_count

        sas.model.stripdata = sas.stripdata

        if naomi2hg:
            naomi2hg_put_gmp(sas)
        sas.model.put_strip_point2(sas.mat_index, sas)

        nxt = sas.next
        sas = nxt

# get_vertex_count_until_not_gp
# Returns the total vertex count of the consecutive run of strips beginning
# at `s` that share the same GMP parameter header (all have _NL_PF_NOT_GP==1
# except the first which must be 0).

def get_vertex_count_until_not_gp(s: "StripData") -> int:
    import sys

    if s is None:
        return 0

    if s._NL_PF_NOT_GP != 0:
        sys.stderr.write("sonnnabakana  get_vertex_count_until_not_gp!!\n")
        raise SystemExit(-1)

    total = s.strip_num

    while True:
        s = s.next
        if s is None:
            break
        if s._NL_PF_NOT_GP == 0:
            break
        total += s.strip_num

    return total

# naomi2hg_put_pvr
# Emits the 32-byte PVR parameter header for one strip (or strip group)
# in NAOMI2 format, together with the MODEL_DATA_FLAGS word and vertex
# count.  Only called when naomi2hg is True.

def naomi2hg_put_pvr(
        sas: "SAVE_ALL_STRIP",
        s:   "StripData",
        gr:  int,
        cul: int,
) -> None:
    """Emits the 32-byte PVR header (8 words: PCW, ISP_TSP, TSP, TexCtrl,"""
    if not naomi2hg:
        return

    if s._NL_PF_NOT_GP != 0:
        return

    global naomi2hg_all_address
    naomi2hg_all_address += 32

    mat = sas.model.material[sas.mat_index]

    if sas.mc[0].texture_flag == 0:
        if (mat.shading_type == 7 or
                mat.shading_type == DK_MAT_CONSTANT):
            if sas.use2para == 0:
                sas.mc[0]._NL_PF_Texture  = 0
                sas.mc[0]._NL_PF_Texture2 = 0
            else:
                v2 = mat.Vol2para
                if (v2.shading_type == 7 or
                        v2.shading_type == DK_MAT_CONSTANT):
                    sas.mc[0]._NL_PF_Texture  = 0
                    sas.mc[0]._NL_PF_Texture2 = 0

    mc = sas.mc[0]

    # Word 0: parameter_control (PCW) 
    pcw = (
        0x80000000 |
        (mc._NL_PF_ListType << NL_PF_ListType) |
        (mc._NL_PF_Volume   << NL_PF_Volume  ) |
        (mc._NL_PF_Col_Type << NL_PF_Col_Type) |
        (mc._NL_PF_Texture  << NL_PF_Texture ) |
        (mc._NL_PF_Offset   << NL_PF_Offset  ) |
        (gr                 << NL_PF_Gouraud  ) |
        (mc._NL_PF_16bit_UV << NL_PF_16bit_UV)
    )
    write_le32(pcw & 0xFFFFFFFF)

    # Word 1: ISP_TSP_instruction 
    isp_tsp = (
        (mc._NL_PF_DepthCompareMode << NL_PF_DepthCompareMode) |
        (cul                        << NL_PF_CullingMode      ) |
        (mc._NL_PF_ZWriteDisable    << NL_PF_ZWriteDisable    ) |
        (mc._NL_PF_Texture2         << NL_PF_Texture2         ) |
        (mc._NL_PF_Offset2          << NL_PF_Offset2          ) |
        (gr                         << NL_PF_Gouraud2         ) |
        (mc._NL_PF_16bit_UV2        << NL_PF_16bit_UV2        ) |
        (mc._NL_PF_CacheBypass      << NL_PF_CacheBypass      ) |
        (mc._NL_PF_DcalcCtrl        << NL_PF_DcalcCtrl        )
    )
    write_le32(isp_tsp & 0xFFFFFFFF)

    # Word 2: TSP_instruction 
    tsp = (
        (mc._NL_PF_SRC_AlphaInstr      << NL_PF_SRC_AlphaInstr     ) |
        (mc._NL_PF_DST_AlphaInstr      << NL_PF_DST_AlphaInstr     ) |
        (mc._NL_PF_SRC_Select          << NL_PF_SRC_Select         ) |
        (mc._NL_PF_DST_Select          << NL_PF_DST_Select         ) |
        (mc._NL_PF_FogControl          << NL_PF_FogControl         ) |
        (mc._NL_PF_ColorClamp          << NL_PF_ColorClamp         ) |
        (mc._NL_PF_UseAlpha            << NL_PF_UseAlpha           ) |
        (mc._NL_PF_IgnoreTexAlpha      << NL_PF_IgnoreTexAlpha     ) |
        (mc._NL_PF_FlipUV              << NL_PF_FlipUV             ) |
        (mc._NL_PF_ClampUV             << NL_PF_ClampUV            ) |
        (mc._NL_PF_FilterMode          << NL_PF_FilterMode         ) |
        (mc._NL_PF_SuperSampleTexture  << NL_PF_SuperSampleTexture ) |
        (mc._NL_PF_MipMapD_adjust      << NL_PF_MipMapD_adjust     ) |
        (mc._NL_PF_TextureShadingInstr << NL_PF_TextureShadingInstr) |
        (mc._NL_PF_TextureSize_U       << NL_PF_TextureSize_U      ) |
        (mc._NL_PF_TextureSize_V       << NL_PF_TextureSize_V      )
    )
    write_le32(tsp & 0xFFFFFFFF)

    # Word 3: texture_control 
    tex_ctrl = (
        (mc._NL_PF_MIP_Mapped       << NL_PF_MIP_Mapped      ) |
        (mc._NL_PF_VQ_Compressed    << NL_PF_VQ_Compressed   ) |
        (mc._NL_PF_PixelFormat      << NL_PF_PixelFormat      ) |
        (mc._NL_PF_ScanOrder        << NL_PF_ScanOrder        ) |
        (mc._NL_PF_StrideSelect     << NL_PF_StrideSelect     ) |
        (mc._NL_PF_TextureAddress   << NL_PF_TextureAddress   )
    )
    write_le32(tex_ctrl & 0xFFFFFFFF)

    # Words 4-5: TSP2 + TexCtrl2 
    # Always written for both single-para and vol2para.
    # Single-para: duplicate mc[0] TSP+TexCtrl. Vol2para: use mc[1] values.
    if sas.use2para != 0:
        mc1 = sas.mc[1]
        tsp2 = (
            (mc1._NL_PF_SRC_AlphaInstr      << NL_PF_SRC_AlphaInstr     ) |
            (mc1._NL_PF_DST_AlphaInstr      << NL_PF_DST_AlphaInstr     ) |
            (mc1._NL_PF_SRC_Select          << NL_PF_SRC_Select         ) |
            (mc1._NL_PF_DST_Select          << NL_PF_DST_Select         ) |
            (mc1._NL_PF_FogControl          << NL_PF_FogControl         ) |
            (mc1._NL_PF_ColorClamp          << NL_PF_ColorClamp         ) |
            (mc1._NL_PF_UseAlpha            << NL_PF_UseAlpha           ) |
            (mc1._NL_PF_IgnoreTexAlpha      << NL_PF_IgnoreTexAlpha     ) |
            (mc1._NL_PF_FlipUV              << NL_PF_FlipUV             ) |
            (mc1._NL_PF_ClampUV             << NL_PF_ClampUV            ) |
            (mc1._NL_PF_FilterMode          << NL_PF_FilterMode         ) |
            (mc1._NL_PF_SuperSampleTexture  << NL_PF_SuperSampleTexture ) |
            (mc1._NL_PF_MipMapD_adjust      << NL_PF_MipMapD_adjust     ) |
            (mc1._NL_PF_TextureShadingInstr << NL_PF_TextureShadingInstr) |
            (mc1._NL_PF_TextureSize_U       << NL_PF_TextureSize_U      ) |
            (mc1._NL_PF_TextureSize_V       << NL_PF_TextureSize_V      )
        )
        tex_ctrl2 = (
            (mc1._NL_PF_MIP_Mapped     << NL_PF_MIP_Mapped    ) |
            (mc1._NL_PF_VQ_Compressed  << NL_PF_VQ_Compressed ) |
            (mc1._NL_PF_PixelFormat    << NL_PF_PixelFormat    ) |
            (mc1._NL_PF_ScanOrder      << NL_PF_ScanOrder      ) |
            (mc1._NL_PF_StrideSelect   << NL_PF_StrideSelect   ) |
            (mc1._NL_PF_TextureAddress << NL_PF_TextureAddress )
        )
        write_le32(tsp2 & 0xFFFFFFFF)
        write_le32(tex_ctrl2 & 0xFFFFFFFF)
    else:
        # Single-para: duplicate para0 TSP+TexCtrl into para1 slot
        write_le32(tsp & 0xFFFFFFFF)
        write_le32(tex_ctrl & 0xFFFFFFFF)

    # Derived from reference binary (0x0000000A for textured lambert with normals):
    #   bit0 = ??? (0 in reference — not used for "vertex present", XYZ always written)
    #   bit1 = Normal present (always 1 — naomi2hg vertex always includes packed normal)
    env_flag = int(sas.env_map_polygon if sas is not None else env_map_polygon)
    Normal   = 1
    UV       = 1
    UV1      = 0
    _16bitUV = 0
    RGB      = 0
    RGB1     = 0
    Bump     = 0
    Bump1    = 0

    if not sas.bump_polygon:
        if env_flag:
            UV = 0
        if mat.shading_type == 7:
            RGB = 1
    else:
        Bump = 1

    model_data_flags = (
        (Normal   << 1) |
        (UV       << 3) |
        (_16bitUV << 4) |
        (RGB      << 6) |
        (RGB1     << 7) |
        (Bump     << 7) |
        (Bump1    << 8)
    )

    flags_parts = []
    if Normal:   flags_parts.append(" naomi2hg_Normal")
    if UV:       flags_parts.append(" | naomi2hg_UV")
    if UV1:      flags_parts.append(" | naomi2hg_UV1")
    if _16bitUV: flags_parts.append(" | naomi2hg_16bitUV")
    if RGB:      flags_parts.append(" | naomi2hg_RGB")
    if RGB1:     flags_parts.append(" | naomi2hg_RGB1")
    if Bump:     flags_parts.append(" | naomi2hg_Bump")
    if Bump1:    flags_parts.append(" | naomi2hg_Bump1")

    write_le32(model_data_flags & 0xFFFFFFFF)

    vtx_ct = get_vertex_count_until_not_gp(s)
    write_le32(vtx_ct & 0xFFFFFFFF)
# Std_Model.put_strip_point2
# The inner loop that actually emits every gflag header + vertex record for
# a single material's strip list.  This is the true workhorse called by both
# put_strip_point (non-deferred) and all_put_strip_point0 (deferred).

def _Std_Model_put_strip_point2(
        self: "Std_Model",
        mat_index: int,
        sas: "SAVE_ALL_STRIP",
) -> None:

    global object_all_address, send_gp_count
    global chk_before_bump_nrm_x, chk_before_bump_nrm_y, chk_before_bump_nrm_z
    global chk_before_bump_nrm0_x, chk_before_bump_nrm0_y, chk_before_bump_nrm0_z
    global chk_before_bump_nrm1_x, chk_before_bump_nrm1_y, chk_before_bump_nrm1_z

    object_all_address += 20 * 4

    self.DMA_ADRS = 0
    self.RAM_ADRS = 0

    s = self.stripdata

    # Reset bump-normal accumulation state (module-level globals used by put_point_info)
    chk_before_bump_nrm_x  = 0.0
    chk_before_bump_nrm_y  = 0.0
    chk_before_bump_nrm_z  = 0.0
    chk_before_bump_nrm0_x = 0.0
    chk_before_bump_nrm0_y = 0.0
    chk_before_bump_nrm0_z = 0.0
    chk_before_bump_nrm1_x = 0.0
    chk_before_bump_nrm1_y = 0.0
    chk_before_bump_nrm1_z = 0.0

    self.index_to_dma_address = [0] * (self.add_count2 + 1)
    self.index_to_ram_address = [0] * (self.add_count2 + 1)

    while s is not None:
        cul = s._NL_PF_CULLING

        if s._NL_PF_NOT_GP == 0:
            self.DMA_ADRS += 8 * 4
            send_gp_count += 1

        # RAM_ADRS is a Std_Model member. RAM_ADRS += 4*2
        self.RAM_ADRS          += 4 * 2
        object_all_address += 4 * 2

        gr = s._NL_PF_GOURAUD
        # In the deferred path sas carries the per-material snapshot.
        _bump = sas.bump_polygon     if sas is not None else bump_polygon
        _env  = sas.env_map_polygon  if sas is not None else env_map_polygon
        if (self.material[mat_index].shading_type == 7 and not _bump):
            gr = True

        if naomi2hg:
            naomi2hg_put_pvr(sas, s, int(gr), cul)
        else:
            env_val = int(_env)
            gflag_word = (
                (env_val              << NL_PF_ENVMAP   ) |
                (s._NL_PF_S_INDEX     << NL_PF_S_INDEX  ) |
                (s._NL_PF_NOT_GP      << NL_PF_NOT_GP   ) |
                (int(gr)              << NL_PF_GOURAUD   ) |
                (cul                  << NL_PF_CULLING   ) |
                (s._NL_PF_STRIP       << NL_PF_STRIP    ) |
                (s._NL_PF_TRIANGLE    << NL_PF_TRIANGLE ) |
                (s._NL_PF_SPRITE      << NL_PF_SPRITE   )
            )

            write_le32(gflag_word & 0xFFFFFFFF)

            if s._NL_PF_TRIANGLE == 1:
                cnt = s.strip_num // 3
                write_le32(cnt & 0xFFFFFFFF)
            else:
                cnt = s.strip_num
                write_le32(cnt & 0xFFFFFFFF)

        for i in range(s.strip_num):
            if naomi2hg:
                v_end = 0
                if s._NL_PF_TRIANGLE == 1:
                    if (i % 3) == 2:
                        v_end = 1
                    self.naomi2hg_put_point_info(
                        i % 3,
                        s.pi[i].pol_idx, s.pi[i].inf_idx,
                        s.tex.v0, s.pi[i].sp_idx, s.pi[i].flag,
                        0, v_end, sas,
                    )
                else:
                    if i == s.strip_num - 1:
                        v_end = 1
                    fan_flag = 0 if s._NL_PF_STRIP == 1 else 1
                    self.naomi2hg_put_point_info(
                        i,
                        s.pi[i].pol_idx, s.pi[i].inf_idx,
                        s.tex.v0, s.pi[i].sp_idx, s.pi[i].flag,
                        fan_flag, v_end, sas,
                    )
            else:
                self.put_point_info(
                    i,
                    s.pi[i].pol_idx, s.pi[i].inf_idx,
                    s.tex.v0, s.pi[i].sp_idx, s.pi[i].flag,
                )

        # Free the PointInfo array and advance
        s.pi = None
        s = s.next

    # (no trailing output in binary mode)

    if super_index_format and self.stripdata is not None:
        a = self.add_count0 + self.add_count2
        global put_point_all, put_repoint_all, max_s_index_ct
        if max_s_index_ct < self.add_count2:
            max_s_index_ct = self.add_count2

    self.index_to_dma_address = None
    self.index_to_ram_address = None


# all_put_strip_point  — REAL IMPLEMENTATION
# Scans all three deferred lists to collect size/count metrics, prints
# punch-through strips (with global_info_disp / div_trnsl branching for
# the standard path).

def all_put_strip_point() -> None:

    opq = MODEL_ALL_INFO()
    (opq.allsize, opq.allvtxnum,
     opq.allsendgmp, opq.allsendpvr) = all_put_scan_list_info(save_all_strip_opq)

    trs = MODEL_ALL_INFO()
    (trs.allsize, trs.allvtxnum,
     trs.allsendgmp, trs.allsendpvr) = all_put_scan_list_info(save_all_strip_trs)

    pch = MODEL_ALL_INFO()
    (pch.allsize, pch.allvtxnum,
     pch.allsendgmp, pch.allsendpvr) = all_put_scan_list_info(save_all_strip_pch)

    if naomi2hg:
        global naomi2hg_all_address
        naomi2hg_all_address = 0

        naomi2hg_global_info_disp(opq, trs, pch)

        all_put_strip_point0(save_all_strip_opq)
        all_put_strip_point0(save_all_strip_trs)
        all_put_strip_point0(save_all_strip_pch)

    else:
        div_trnsl = getattr(sys.modules[__name__], "div_trnsl",
                            getattr(sys.modules[__name__], "_opts_div_trnsl", False))

        if div_trnsl:
            # Separate opaque + punch-through from translucent
            if opq.allvtxnum + pch.allvtxnum == 0:
                nf = 1
            else:
                nf = 0

            global_info_disp(nf)

            all_put_strip_point0(save_all_strip_opq)
            all_put_strip_point0(save_all_strip_pch)

            # End-of-object footer for the opaque sub-object
            write_le32(0)
            write_le32((opq.allvtxnum + pch.allvtxnum) & 0xFFFFFFFF)

            # Open translucent array

            nf = 1 if trs.allvtxnum == 0 else 0
            global_info_disp(nf)

            all_put_strip_point0(save_all_strip_trs)

            file_all_point_count = trs.allvtxnum
            all_once_ct          = 0

        else:
            global_info_disp(0)

            all_put_strip_point0(save_all_strip_opq)
            all_put_strip_point0(save_all_strip_trs)
            all_put_strip_point0(save_all_strip_pch)


# Module globals: diffct
# Diagnostic counter incremented by chk_touch_and_gr_set when
# it detects a Gouraud edge whose shared-vertex normals differ.

diffct: int = 0

# Std_Model.chk_touch_and_gr_set
# Called once per candidate edge pair (jj, kk) by set_gr.
#   • Always marks jj as a gr-candidate (more_set_gr = 1) and
#       – Computes cos_p between the two polygon face normals.
#       – If csp > cos(discAngle) and discAngle ≥ 0 and not
#         all_flat and shading_type ≠ DK_MAT_CONSTANT:
#           · Sets spol[jj].gr = True.
#           · If the per-vertex smooth normals (nx/ny/nz) differ
#             between the two shared vertices, copies the "winner"
#             (normal_diff side wins) into the other vertex and
#             marks both normal_diff = True.  Increments diffct.
# Returns True if the edge pair matched, False otherwise.

def _Std_Model_chk_touch_and_gr_set(
        self:  "Std_Model",
        jj:    int,
        kk:    int,
        ma:    int,
        mb:    int,
        ca:    int,
        cb:    int,
) -> bool:
    """Test edge (jj[ma]→jj[mb]) against reverse edge (kk[cb]→kk[ca])."""
    global diffct

    spol = self.polygon

    # Mark jj as a gr-candidate regardless of the match outcome.
    spol[jj].more_set_gr = 1

    if (spol[jj].info_list[ma].point_index != spol[kk].info_list[cb].point_index or
            spol[jj].info_list[mb].point_index != spol[kk].info_list[ca].point_index):
        return False


    DK_MAT_CONSTANT = 1

    csp: float = cos_p(spol[jj].normal, spol[kk].normal)

    mat = self.material[spol[jj].material_index]

    if (csp > spol[jj]._cos_disc_angle and
            spol[jj].model.discAngle >= 0 and
            not all_flat and
            mat.shading_type != DK_MAT_CONSTANT):

        spol[jj].gr = True

        # Vertex ma (jj) vs vertex cb (kk)
        if (spol[jj].info_list[ma].nx != spol[kk].info_list[cb].nx or
                spol[jj].info_list[ma].ny != spol[kk].info_list[cb].ny or
                spol[jj].info_list[ma].nz != spol[kk].info_list[cb].nz):

            diffct += 1

            if (spol[jj].info_list[ma].nx != spol[kk].info_list[cb].nx or
                    spol[jj].info_list[ma].ny != spol[kk].info_list[cb].ny or
                    spol[jj].info_list[ma].nz != spol[kk].info_list[cb].nz):
                if spol[jj].info_list[ma].normal_diff:
                    spol[kk].info_list[cb].nx = spol[jj].info_list[ma].nx
                    spol[kk].info_list[cb].ny = spol[jj].info_list[ma].ny
                    spol[kk].info_list[cb].nz = spol[jj].info_list[ma].nz
                else:
                    spol[jj].info_list[ma].nx = spol[kk].info_list[cb].nx
                    spol[jj].info_list[ma].ny = spol[kk].info_list[cb].ny
                    spol[jj].info_list[ma].nz = spol[kk].info_list[cb].nz
                spol[jj].info_list[ma].normal_diff = True
                spol[kk].info_list[cb].normal_diff = True

            if (spol[jj].info_list[mb].nx != spol[kk].info_list[ca].nx or
                    spol[jj].info_list[mb].ny != spol[kk].info_list[ca].ny or
                    spol[jj].info_list[mb].nz != spol[kk].info_list[ca].nz):
                if spol[jj].info_list[mb].normal_diff:
                    spol[kk].info_list[ca].nx = spol[jj].info_list[mb].nx
                    spol[kk].info_list[ca].ny = spol[jj].info_list[mb].ny
                    spol[kk].info_list[ca].nz = spol[jj].info_list[mb].nz
                else:
                    spol[jj].info_list[mb].nx = spol[kk].info_list[ca].nx
                    spol[jj].info_list[mb].ny = spol[kk].info_list[ca].ny
                    spol[jj].info_list[mb].nz = spol[kk].info_list[ca].nz
                spol[jj].info_list[mb].normal_diff = True
                spol[kk].info_list[ca].normal_diff = True

    add_index(kk)
    return True


# _chk_touch_dispatch  (internal helper)
# This helper encodes that dispatch table for all four
# (njj, nkk) combinations of 3 and 4 once so both set_gr
# overloads can share it.

# Pre-built edge tables: list of (ma, mb, ca, cb) tuples to try
# in sequence for each (njj, nkk) combination.
_EDGE_PAIRS_3_3 = [
    (0,1,0,1),(0,1,1,2),(0,1,2,0),
    (1,2,0,1),(1,2,1,2),(1,2,2,0),
    (2,0,0,1),(2,0,1,2),(2,0,2,0),
]
_EDGE_PAIRS_3_4 = [
    (0,1,0,1),(0,1,1,2),(0,1,2,3),(0,1,3,0),
    (1,2,0,1),(1,2,1,2),(1,2,2,3),(1,2,3,0),
    (2,0,0,1),(2,0,1,2),(2,0,2,3),(2,0,3,0),
]
_EDGE_PAIRS_4_3 = [
    (0,1,0,1),(0,1,1,2),(0,1,2,0),
    (1,2,0,1),(1,2,1,2),(1,2,2,0),
    (2,3,0,1),(2,3,1,2),(2,3,2,0),
    (3,0,0,1),(3,0,1,2),(3,0,2,0),
]
_EDGE_PAIRS_4_4 = [
    (0,1,0,1),(0,1,1,2),(0,1,2,3),(0,1,3,0),
    (1,2,0,1),(1,2,1,2),(1,2,2,3),(1,2,3,0),
    (2,3,0,1),(2,3,1,2),(2,3,2,3),(2,3,3,0),
    (3,0,0,1),(3,0,1,2),(3,0,2,3),(3,0,3,0),
]

# candidates for a fixed (ma,mb).  We flatten to a single sequence
# and rely on chk_touch_and_gr_set returning True on first match
# to reproduce the `if ... else if ...` chain exactly.
_EDGE_TABLE = {
    (3, 3): _EDGE_PAIRS_3_3,
    (3, 4): _EDGE_PAIRS_3_4,
    (4, 3): _EDGE_PAIRS_4_3,
    (4, 4): _EDGE_PAIRS_4_4,
}

def _group_edge_table(flat):
    rows = []; cur_row = []; prev = None
    for entry in flat:
        key = (entry[0], entry[1])
        if key != prev:
            if cur_row: rows.append(cur_row)
            cur_row = [entry]; prev = key
        else:
            cur_row.append(entry)
    if cur_row: rows.append(cur_row)
    return rows

_EDGE_TABLE_GROUPED = {
    (3, 3): _group_edge_table(_EDGE_PAIRS_3_3),
    (3, 4): _group_edge_table(_EDGE_PAIRS_3_4),
    (4, 3): _group_edge_table(_EDGE_PAIRS_4_3),
    (4, 4): _group_edge_table(_EDGE_PAIRS_4_4),
}

def _dispatch_chk_touch(model, jj, kk, spol):
    rows = _EDGE_TABLE_GROUPED.get((spol[jj].info_list_num, spol[kk].info_list_num))
    if rows is None:
        return
    chk = model.chk_touch_and_gr_set
    for row in rows:
        for (ma, mb, ca, cb) in row:
            if chk(jj, kk, ma, mb, ca, cb):
                break

# Std_Model.set_gr  (the commented-out no-arg overload)

def _Std_Model_set_gr_noarg(self: "Std_Model") -> None:
    """Commented-out no-arg overload of set_gr."""
    pass

# Std_Model.set_gr  (the active flag_more overload)

def _Std_Model_set_gr(self: "Std_Model", flag_more: int = 0) -> None:
    """Set Gouraud flags on all polygons in the model."""
    global dup_chk_buf_ct, _dup_gen

    _idxlist_pool_ensure(self.polygon_num * 3 + 16)
    _idxlist_pool_reset()

    pn_calc: List[Optional["IdxList"]] = [None] * self.point_num

    for i in range(self.polygon_num):
        sp = self.polygon[i]
        for j in range(sp.info_list_num):
            inf = sp.info_list[j]
            if inf.point_index >= 0:
                pn_calc[inf.point_index] = _idxlist_alloc(
                    i, pn_calc[inf.point_index]
                )

    spol    = self.polygon
    stdpnum = self.polygon_num

    _cd = math.cos(self.discAngle)
    for _pi in range(stdpnum):
        spol[_pi]._cos_disc_angle = _cd

    for jj in range(stdpnum):

        if spol[jj].info_list_num not in (3, 4):
            continue

        dup_chk_buf_ct = 0
        _dup_gen += 1

        for ll in range(spol[jj].info_list_num):
            pi = spol[jj].info_list[ll].point_index
            l = pn_calc[pi] if pi >= 0 else None

            while l is not None:
                kk = l.pl_idx

                if ((flag_more == 0 or spol[jj].more_set_gr < 2) and
                        kk != jj and
                        spol[kk].info_list_num in (3, 4) and
                        not chk_dup_index(kk)):
                    _dispatch_chk_touch(self, jj, kk, spol)

                l = l.next

    _idxlist_pool_reset()

    for jj in range(stdpnum):
        if spol[jj].more_set_gr == 1:
            spol[jj].more_set_gr = 2


# Std_Polygon.set_normal

def _Std_Polygon_set_normal(self: "Std_Polygon") -> None:
    """Recompute self.normal from the first three vertices."""
    import sys
    if self.info_list_num < 3:
        sys.stderr.write(
            f"normal calc error info_list_num is too few <{self.info_list_num}>\n"
        )
        sys.stderr.write(
            f"model name is {self.info_list[0].poly.model.model_name}\n"
        )
        raise SystemExit(-1)

    p0 = self.info_list[0].point_index
    p1 = self.info_list[1].point_index
    p2 = self.info_list[2].point_index

    self.normal = vec_pro(
        self.model.point_list[p0],
        self.model.point_list[p1],
        self.model.point_list[p2],
    )


# Std_Polygon.chk_convex
# Returns True if the polygon is convex (or a triangle), False
# if any interior angle is concave (≤ 0 dot product).
# For each triple of consecutive vertices (i, i+1, i+2) that all
# have valid point_index values (≥ 0), computes the cross product
# of their positions via vec_pro and dots it with the smooth
# normal of the middle vertex.  A non-positive dot product means

def _Std_Polygon_chk_convex(self: "Std_Polygon") -> bool:
    if self.info_list_num <= 3:
        return True

    n = self.info_list_num
    for i in range(n):
        i0 = i % n
        i1 = (i + 1) % n
        i2 = (i + 2) % n

        if (self.info_list[i0].point_index >= 0 and
                self.info_list[i1].point_index >= 0 and
                self.info_list[i2].point_index >= 0):

            tmp = vec_pro(
                self.model.point_list[self.info_list[i0].point_index],
                self.model.point_list[self.info_list[i1].point_index],
                self.model.point_list[self.info_list[i2].point_index],
            )

            ntmp = Std_Point()
            ntmp.x.assign(float(self.info_list[i1].nx))
            ntmp.y.assign(float(self.info_list[i1].ny))
            ntmp.z.assign(float(self.info_list[i1].nz))

            chk = sca_pro(tmp, ntmp)
            if chk <= 0:
                return False

    return True


# Std_Polygon.chk_convex3

def _Std_Polygon_chk_convex3(self: "Std_Polygon") -> bool:
    """Stricter convexity test (threshold 0.0001)."""
    n = self.info_list_num
    for i in range(n):
        i0 = i % n
        i1 = (i + 1) % n
        i2 = (i + 2) % n

        if (self.info_list[i0].point_index >= 0 and
                self.info_list[i1].point_index >= 0 and
                self.info_list[i2].point_index >= 0):

            tmp = vec_pro(
                self.model.point_list[self.info_list[i0].point_index],
                self.model.point_list[self.info_list[i1].point_index],
                self.model.point_list[self.info_list[i2].point_index],
            )

            ntmp = Std_Point()
            ntmp.x.assign(float(self.info_list[i1].nx))
            ntmp.y.assign(float(self.info_list[i1].ny))
            ntmp.z.assign(float(self.info_list[i1].nz))

            chk = sca_pro(tmp, ntmp)
            if chk <= 0.0001:
                return False

    return True


# vec_pro
# Cross product of (v0 − v1) × (v1 − v2), normalised.
# Used to compute polygon face normals.
# Note: both vec_pro and its non-normalised twin vec_pro0 are
# all callers pick up the real implementation.

def _gd(f):
    return f._data if type(f) is Std_Float else float(f)

def vec_pro(v0, v1, v2):
    _f32l = _f32; _gdl = _gd
    v0x=_gdl(v0.x); v0y=_gdl(v0.y); v0z=_gdl(v0.z)
    v1x=_gdl(v1.x); v1y=_gdl(v1.y); v1z=_gdl(v1.z)
    v2x=_gdl(v2.x); v2y=_gdl(v2.y); v2z=_gdl(v2.z)
    V1x=_f32l(v0x-v1x); V1y=_f32l(v0y-v1y); V1z=_f32l(v0z-v1z)
    V2x=_f32l(v1x-v2x); V2y=_f32l(v1y-v2y); V2z=_f32l(v1z-v2z)
    cx=_f32l(_f32l(V1y*V2z)-_f32l(V1z*V2y))
    cy=_f32l(_f32l(V1z*V2x)-_f32l(V1x*V2z))
    cz=_f32l(_f32l(V1x*V2y)-_f32l(V1y*V2x))
    l=_f32(math.sqrt(_f32(_f32(_f32(cx*cx)+_f32(cy*cy))+_f32(cz*cz))))
    if l!=0.0: cx=_f32l(cx/l); cy=_f32l(cy/l); cz=_f32l(cz/l)
    else: cx=cy=cz=0.0
    return Std_Point._make(cx, cy, cz)

def vec_pro0(v0, v1, v2):
    _f32l=_f32; _gdl=_gd
    v0x=_gdl(v0.x); v0y=_gdl(v0.y); v0z=_gdl(v0.z)
    v1x=_gdl(v1.x); v1y=_gdl(v1.y); v1z=_gdl(v1.z)
    v2x=_gdl(v2.x); v2y=_gdl(v2.y); v2z=_gdl(v2.z)
    V1x=_f32l(v0x-v1x); V1y=_f32l(v0y-v1y); V1z=_f32l(v0z-v1z)
    V2x=_f32l(v1x-v2x); V2y=_f32l(v1y-v2y); V2z=_f32l(v1z-v2z)
    return Std_Point._make(
        _f32l(_f32l(V1y*V2z)-_f32l(V1z*V2y)),
        _f32l(_f32l(V1z*V2x)-_f32l(V1x*V2z)),
        _f32l(_f32l(V1x*V2y)-_f32l(V1y*V2x)),
    )

def sca_pro(v0: "Std_Point", v1: "Std_Point") -> float:
    return v0.x._data*v1.x._data + v0.y._data*v1.y._data + v0.z._data*v1.z._data

# cos_p
# Cosine of the angle between two vectors.  Returns 1.0 if
# either vector is zero-length (degenerate triangles behave as
# parallel / smooth by convention).

def cos_p(v0: "Std_Point", v1: "Std_Point") -> float:
    x0 = v0.x._data; y0 = v0.y._data; z0 = v0.z._data
    x1 = v1.x._data; y1 = v1.y._data; z1 = v1.z._data
    v0l2 = x0*x0 + y0*y0 + z0*z0
    v1l2 = x1*x1 + y1*y1 + z1*z1
    if v0l2 == 0.0 or v1l2 == 0.0:
        return 1.0
    return (x0*x1 + y0*y1 + z0*z1) / math.sqrt(v0l2 * v1l2)


# Std_Model.calc_point_normal

def _Std_Model_calc_point_normal(self: "Std_Model") -> None:
    """Compute smoothed per-point normals and store in"""
    return


# Std_Model.get_center_pos_R
# Computes the axis-aligned bounding-box centre (cx, cy, cz) and
# the bounding-sphere radius r for all polygons belonging to
# material mat_no.
# Uses the g_matidx_* cache
# is valid for this model (O(pnum) instead of O(polygon_num)).
# we return a 4-tuple (x, y, z, r) and also write into the
# Std_Float boxes passed by the caller (caller convention in the
# Python port uses mutable Std_Float objects).
# left_hand and z_reverse both negate *z when True.

def _Std_Model_get_center_pos_R(
        self:   "Std_Model",
        mat_no: int,
        x:      "Std_Float",
        y:      "Std_Float",
        z:      "Std_Float",
        r:      "Std_Float",
) -> None:
    """Write bounding-sphere centre and radius for material mat_no"""

    # Import the g_matidx cache from render_output at call time
    # (avoids a circular import at module load; the cache is
    try:
        _g_matidx_model  = g_matidx_model
        _g_matidx_matnum = g_matidx_matnum
        _g_matidx_cnt    = g_matidx_cnt
        _g_matidx_flat   = g_matidx_flat
        _g_matidx_off    = g_matidx_off
    except Exception:
        _g_matidx_model  = None
        _g_matidx_matnum = 0
        _g_matidx_cnt    = []
        _g_matidx_flat   = []
        _g_matidx_off    = []

    if self.polygon_num == 0:
        x.assign(0.0); y.assign(0.0); z.assign(0.0); r.assign(0.0)
        return

    # Seed bounding box from the first valid vertex
    idx0 = self.polygon[0].info_list[0].point_index
    if idx0 < 0:
        idx0 = 0
    max_x = min_x = float(self.point_list[idx0].x)
    max_y = min_y = float(self.point_list[idx0].y)
    max_z = min_z = float(self.point_list[idx0].z)

    use_cache: bool = (
        _g_matidx_model is self and mat_no < _g_matidx_matnum
    )
    pcnt: int = _g_matidx_cnt[mat_no] if use_cache else self.polygon_num
    first: bool = True

    for _pi in range(pcnt):
        i: int = _g_matidx_flat[_g_matidx_off[mat_no] + _pi] if use_cache else _pi
        if not use_cache and self.polygon[i].material_index != mat_no:
            continue
        p = self.polygon[i]
        for j in range(p.info_list_num):
            idx = p.info_list[j].point_index
            if idx < 0:
                idx = 0
            px = float(self.point_list[idx].x)
            py = float(self.point_list[idx].y)
            pz = float(self.point_list[idx].z)
            if first:
                first = False
                max_x = min_x = px
                max_y = min_y = py
                max_z = min_z = pz
            else:
                if px > max_x: max_x = px
                if px < min_x: min_x = px
                if py > max_y: max_y = py
                if py < min_y: min_y = py
                if pz > max_z: max_z = pz
                if pz < min_z: min_z = pz

    # Snap any component whose magnitude is below 4 ULPs at the bound radius.
    # The bound radius is estimated conservatively as half the bbox diagonal;
    # a real geometric offset is always >> 4 ULPs so snapping is safe.
    # NOTE: the snap is applied to cx/cy/cz BEFORE the radius second pass so
    # — only the four f32 centroid/radius words in the output stream.
    _half_diag = math.sqrt(
        ((max_x - min_x) / 2.0) ** 2 +
        ((max_y - min_y) / 2.0) ** 2 +
        ((max_z - min_z) / 2.0) ** 2
    )
    _snap_thresh = 4.0 * (2.0 ** -23) * _half_diag

    _raw_cx = (max_x + min_x) / 2.0
    _raw_cy = (max_y + min_y) / 2.0
    _raw_cz = (max_z + min_z) / 2.0
    _snap_cx = 0.0 if abs(_raw_cx) < _snap_thresh else _raw_cx
    _snap_cy = 0.0 if abs(_raw_cy) < _snap_thresh else _raw_cy
    _snap_cz = 0.0 if abs(_raw_cz) < _snap_thresh else _raw_cz

    x.assign(_snap_cx)
    y.assign(_snap_cy)
    z.assign(_snap_cz)
    cx: float = float(x)
    cy: float = float(y)
    cz: float = float(z)

    cr2: float = 0.0
    for _pi in range(pcnt):
        i = _g_matidx_flat[_g_matidx_off[mat_no] + _pi] if use_cache else _pi
        if not use_cache and self.polygon[i].material_index != mat_no:
            continue
        p = self.polygon[i]
        for j in range(p.info_list_num):
            idx = p.info_list[j].point_index
            if idx < 0:
                idx = 0
            dx = _f32(float(self.point_list[idx].x) - cx)
            dy = _f32(float(self.point_list[idx].y) - cy)
            dz = _f32(float(self.point_list[idx].z) - cz)
            d2 = _f32(_f32(_f32(dx*dx) + _f32(dy*dy)) + _f32(dz*dz))
            if d2 > cr2:
                cr2 = d2
    r.assign(_f32(math.sqrt(cr2)))

    # Coordinate-system flips (applied to *z only)


# Std_Material.__eq__   (operator==)
# Field-by-field equality test used to detect duplicate materials
# so their polygon data can be merged.
#   • blend: if *both* blend values are < 1.0 they compare equal
#     even when the float values differ — only one sub-1 entry is
#     allocated per material slot.
#   • Colour channels (amb/dif) are only compared when blend < 1
#     or pic_name is empty.
#   • Specular channels (spc) only when shading_type == DK_MAT_PHONG.
#   • Cropping fields only when use_cropping == True (module global).
#     __eq__ on the nested Std_Material.
#   • Several fields are checked twice in the original (clamp_u,
#     clamp_v, super_sample_tex, mipmap_d_adjust, mip_mapped,
#     vq_compressed, bump_map).  The duplicate checks are reproduced
#     here for faithful translation; they are no-ops at runtime.

def _Std_Material_eq(self: "Std_Material", other: "Std_Material") -> bool:
    DK_MAT_PHONG = 4

    if self.pic_name != other.pic_name:
        return False
    if self.shadow_effect != other.shadow_effect:
        return False
    if self.double_side != other.double_side:
        return False
    if self.fog != other.fog:
        return False
    if self.fade != other.fade:
        return False
    if self.shading_type != other.shading_type:
        return False
    if self.tex_size_u != other.tex_size_u:
        return False
    if self.tex_size_v != other.tex_size_v:
        return False

    if self.blend != other.blend:
        if self.blend < 1.0 and other.blend < 1.0:
            pass
        else:
            return False

    if self.uAlternate != other.uAlternate:
        return False
    if self.vAlternate != other.vAlternate:
        return False
    if self.g_amb != other.g_amb:
        return False
    if self.effect != other.effect:
        return False
    if self.transpFct != other.transpFct:
        return False

    # Colour channels — only compared for non-textured / translucent mats
    if self.blend < 1.0 or self.pic_name == "":
        if self.amb_R != other.amb_R: return False
        if self.amb_G != other.amb_G: return False
        if self.amb_B != other.amb_B: return False
        if self.dif_R != other.dif_R: return False
        if self.dif_G != other.dif_G: return False
        if self.dif_B != other.dif_B: return False

    # Specular channels — only for Phong shading
    if self.shading_type == DK_MAT_PHONG:
        if self.spc_R != other.spc_R: return False
        if self.spc_G != other.spc_G: return False
        if self.spc_B != other.spc_B: return False

    if self.exp  != other.exp:  return False
    if self.trs  != other.trs:  return False
    if self.tex_amb != other.tex_amb: return False

    if self.clamp_u           != other.clamp_u:           return False
    if self.clamp_v           != other.clamp_v:           return False
    if self.super_sample_tex  != other.super_sample_tex:  return False
    if self.mipmap_d_adjust   != other.mipmap_d_adjust:   return False
    if self.mip_mapped        != other.mip_mapped:        return False
    if self.vq_compressed     != other.vq_compressed:     return False
    if self.bump_map          != other.bump_map:          return False
    if self.filter_mode       != other.filter_mode:       return False

    # Cropping fields — only when use_cropping is enabled

    if self.env_map != other.env_map: return False

    if self.clamp_u           != other.clamp_u:           return False
    if self.clamp_v           != other.clamp_v:           return False
    if self.super_sample_tex  != other.super_sample_tex:  return False
    if self.mipmap_d_adjust   != other.mipmap_d_adjust:   return False
    if self.mip_mapped        != other.mip_mapped:        return False
    if self.vq_compressed     != other.vq_compressed:     return False
    if self.bump_map          != other.bump_map:          return False

    if self.auto_bump_map_generate != other.auto_bump_map_generate: return False
    if self.pixel_format           != other.pixel_format:           return False
    if self.tsi_parameter          != other.tsi_parameter:          return False
    if self.roughness              != other.roughness:               return False

    if self.src_alpha_instr != other.src_alpha_instr: return False
    if self.dst_alpha_instr != other.dst_alpha_instr: return False

    if self.scan_order    != other.scan_order:    return False
    if self.punch_through != other.punch_through: return False
    if self.color_clamp   != other.color_clamp:   return False

    # Vol2para (nested Std_Material)
    if self.Vol2para is not None and other.Vol2para is None:
        return False
    if self.Vol2para is None and other.Vol2para is not None:
        return False
    if self.Vol2para is not None and other.Vol2para is not None:
        if not (self.Vol2para == other.Vol2para):
            return False

    return True


class MATRIX:
    __slots__ = (
        "r00", "r01", "r02",
        "r10", "r11", "r12",
        "r20", "r21", "r22",
        "psx", "psy", "psz",
    )

    def __init__(self):
        self.r00 = 1.0; self.r01 = 0.0; self.r02 = 0.0
        self.r10 = 0.0; self.r11 = 1.0; self.r12 = 0.0
        self.r20 = 0.0; self.r21 = 0.0; self.r22 = 1.0
        self.psx = 0.0; self.psy = 0.0; self.psz = 0.0

    def copy_from(self, src: "MATRIX"):
        self.r00 = src.r00; self.r01 = src.r01; self.r02 = src.r02
        self.r10 = src.r10; self.r11 = src.r11; self.r12 = src.r12
        self.r20 = src.r20; self.r21 = src.r21; self.r22 = src.r22
        self.psx = src.psx; self.psy = src.psy; self.psz = src.psz

    def clone(self) -> "MATRIX":
        m = MATRIX.__new__(MATRIX)
        m.r00 = self.r00; m.r01 = self.r01; m.r02 = self.r02
        m.r10 = self.r10; m.r11 = self.r11; m.r12 = self.r12
        m.r20 = self.r20; m.r21 = self.r21; m.r22 = self.r22
        m.psx = self.psx; m.psy = self.psy; m.psz = self.psz
        return m

_MTX_STACK_SIZE = 256
_MTX_WARN_DEPTH = 24
mtx_stack: list = [MATRIX() for _ in range(_MTX_STACK_SIZE)]
mtx_count: int = 0

def _mtx_top() -> MATRIX:
    return mtx_stack[mtx_count]

def m_flush() -> None:
    global mtx_count
    mtx_count = 0

def m_base() -> None:
    mtx = _mtx_top()
    mtx.r00 = 1.0; mtx.r01 = 0.0; mtx.r02 = 0.0
    mtx.r10 = 0.0; mtx.r11 = 1.0; mtx.r12 = 0.0
    mtx.r20 = 0.0; mtx.r21 = 0.0; mtx.r22 = 1.0
    mtx.psx = 0.0; mtx.psy = 0.0; mtx.psz = 0.0

def m_base_point() -> None:
    mtx = _mtx_top()
    mtx.psx = 0.0; mtx.psy = 0.0; mtx.psz = 0.0

def m_push() -> None:
    global mtx_count
    inc = (mtx_count + 1) & 255
    if inc >= 255:
        raise RuntimeError(f"matrix stack overflow at depth {inc}")
    mtx_stack[inc].copy_from(mtx_stack[mtx_count])
    mtx_count = inc

def m_pop() -> None:
    global mtx_count
    mtx_count = (mtx_count - 1) & 255

def m_inc() -> None:
    global mtx_count
    mtx_count = (mtx_count + 1) & 255

def m_multi(mtx2: MATRIX) -> None:
    tmp = _mtx_top().clone()
    mtx = _mtx_top()
    mtx.r00 = _f32(_f32(_f32(mtx2.r00*tmp.r00) + _f32(mtx2.r01*tmp.r10)) + _f32(mtx2.r02*tmp.r20))
    mtx.r01 = _f32(_f32(_f32(mtx2.r00*tmp.r01) + _f32(mtx2.r01*tmp.r11)) + _f32(mtx2.r02*tmp.r21))
    mtx.r02 = _f32(_f32(_f32(mtx2.r00*tmp.r02) + _f32(mtx2.r01*tmp.r12)) + _f32(mtx2.r02*tmp.r22))
    mtx.r10 = _f32(_f32(_f32(mtx2.r10*tmp.r00) + _f32(mtx2.r11*tmp.r10)) + _f32(mtx2.r12*tmp.r20))
    mtx.r11 = _f32(_f32(_f32(mtx2.r10*tmp.r01) + _f32(mtx2.r11*tmp.r11)) + _f32(mtx2.r12*tmp.r21))
    mtx.r12 = _f32(_f32(_f32(mtx2.r10*tmp.r02) + _f32(mtx2.r11*tmp.r12)) + _f32(mtx2.r12*tmp.r22))
    mtx.r20 = _f32(_f32(_f32(mtx2.r20*tmp.r00) + _f32(mtx2.r21*tmp.r10)) + _f32(mtx2.r22*tmp.r20))
    mtx.r21 = _f32(_f32(_f32(mtx2.r20*tmp.r01) + _f32(mtx2.r21*tmp.r11)) + _f32(mtx2.r22*tmp.r21))
    mtx.r22 = _f32(_f32(_f32(mtx2.r20*tmp.r02) + _f32(mtx2.r21*tmp.r12)) + _f32(mtx2.r22*tmp.r22))
    mtx.psx = _f32(_f32(_f32(_f32(mtx2.psx*tmp.r00) + _f32(mtx2.psy*tmp.r10)) + _f32(mtx2.psz*tmp.r20)) + tmp.psx)
    mtx.psy = _f32(_f32(_f32(_f32(mtx2.psx*tmp.r01) + _f32(mtx2.psy*tmp.r11)) + _f32(mtx2.psz*tmp.r21)) + tmp.psy)
    mtx.psz = _f32(_f32(_f32(_f32(mtx2.psx*tmp.r02) + _f32(mtx2.psy*tmp.r12)) + _f32(mtx2.psz*tmp.r22)) + tmp.psz)

def m_multi2(
        r00: float, r01: float, r02: float,
        r10: float, r11: float, r12: float,
        r20: float, r21: float, r22: float,
        psx: float, psy: float, psz: float,
) -> None:
    tmp = _mtx_top().clone()
    mtx = _mtx_top()
    mtx.r00 = _f32(_f32(_f32(r00*tmp.r00) + _f32(r01*tmp.r10)) + _f32(r02*tmp.r20))
    mtx.r01 = _f32(_f32(_f32(r00*tmp.r01) + _f32(r01*tmp.r11)) + _f32(r02*tmp.r21))
    mtx.r02 = _f32(_f32(_f32(r00*tmp.r02) + _f32(r01*tmp.r12)) + _f32(r02*tmp.r22))
    mtx.r10 = _f32(_f32(_f32(r10*tmp.r00) + _f32(r11*tmp.r10)) + _f32(r12*tmp.r20))
    mtx.r11 = _f32(_f32(_f32(r10*tmp.r01) + _f32(r11*tmp.r11)) + _f32(r12*tmp.r21))
    mtx.r12 = _f32(_f32(_f32(r10*tmp.r02) + _f32(r11*tmp.r12)) + _f32(r12*tmp.r22))
    mtx.r20 = _f32(_f32(_f32(r20*tmp.r00) + _f32(r21*tmp.r10)) + _f32(r22*tmp.r20))
    mtx.r21 = _f32(_f32(_f32(r20*tmp.r01) + _f32(r21*tmp.r11)) + _f32(r22*tmp.r21))
    mtx.r22 = _f32(_f32(_f32(r20*tmp.r02) + _f32(r21*tmp.r12)) + _f32(r22*tmp.r22))
    mtx.psx = _f32(_f32(_f32(_f32(psx*tmp.r00) + _f32(psy*tmp.r10)) + _f32(psz*tmp.r20)) + tmp.psx)
    mtx.psy = _f32(_f32(_f32(_f32(psx*tmp.r01) + _f32(psy*tmp.r11)) + _f32(psz*tmp.r21)) + tmp.psy)
    mtx.psz = _f32(_f32(_f32(_f32(psx*tmp.r02) + _f32(psy*tmp.r12)) + _f32(psz*tmp.r22)) + tmp.psz)

def m_multi_right(mtx2: MATRIX) -> None:
    tmp = _mtx_top().clone()
    mtx = _mtx_top()
    mtx.r00 = tmp.r00*mtx2.r00 + tmp.r01*mtx2.r10 + tmp.r02*mtx2.r20
    mtx.r01 = tmp.r00*mtx2.r01 + tmp.r01*mtx2.r11 + tmp.r02*mtx2.r21
    mtx.r02 = tmp.r00*mtx2.r02 + tmp.r01*mtx2.r12 + tmp.r02*mtx2.r22
    mtx.r10 = tmp.r10*mtx2.r00 + tmp.r11*mtx2.r10 + tmp.r12*mtx2.r20
    mtx.r11 = tmp.r10*mtx2.r01 + tmp.r11*mtx2.r11 + tmp.r12*mtx2.r21
    mtx.r12 = tmp.r10*mtx2.r02 + tmp.r11*mtx2.r12 + tmp.r12*mtx2.r22
    mtx.r20 = tmp.r20*mtx2.r00 + tmp.r21*mtx2.r10 + tmp.r22*mtx2.r20
    mtx.r21 = tmp.r20*mtx2.r01 + tmp.r21*mtx2.r11 + tmp.r22*mtx2.r21
    mtx.r22 = tmp.r20*mtx2.r02 + tmp.r21*mtx2.r12 + tmp.r22*mtx2.r22
    mtx.psx = tmp.psx*mtx2.r00 + tmp.psy*mtx2.r10 + tmp.psz*mtx2.r20 + mtx2.psx
    mtx.psy = tmp.psx*mtx2.r01 + tmp.psy*mtx2.r11 + tmp.psz*mtx2.r21 + mtx2.psy
    mtx.psz = tmp.psx*mtx2.r02 + tmp.psy*mtx2.r12 + tmp.psz*mtx2.r22 + mtx2.psz

def m_multi2_right(
        r00: float, r01: float, r02: float,
        r10: float, r11: float, r12: float,
        r20: float, r21: float, r22: float,
        psx: float, psy: float, psz: float,
) -> None:
    tmp = _mtx_top().clone()
    mtx = _mtx_top()
    mtx.r00 = tmp.r00*r00 + tmp.r01*r10 + tmp.r02*r20
    mtx.r01 = tmp.r00*r01 + tmp.r01*r11 + tmp.r02*r21
    mtx.r02 = tmp.r00*r02 + tmp.r01*r12 + tmp.r02*r22
    mtx.r10 = tmp.r10*r00 + tmp.r11*r10 + tmp.r12*r20
    mtx.r11 = tmp.r10*r01 + tmp.r11*r11 + tmp.r12*r21
    mtx.r12 = tmp.r10*r02 + tmp.r11*r12 + tmp.r12*r22
    mtx.r20 = tmp.r20*r00 + tmp.r21*r10 + tmp.r22*r20
    mtx.r21 = tmp.r20*r01 + tmp.r21*r11 + tmp.r22*r21
    mtx.r22 = tmp.r20*r02 + tmp.r21*r12 + tmp.r22*r22
    mtx.psx = tmp.psx*r00 + tmp.psy*r10 + tmp.psz*r20 + psx
    mtx.psy = tmp.psx*r01 + tmp.psy*r11 + tmp.psz*r21 + psy
    mtx.psz = tmp.psx*r02 + tmp.psy*r12 + tmp.psz*r22 + psz

def m_trans(x: float, y: float, z: float) -> None:
    m_multi2(1, 0, 0, 0, 1, 0, 0, 0, 1, x, y, z)

def m_xrot(xr: float) -> None:
    c = _f32(math.cos(xr)); s = _f32(math.sin(xr))
    m_multi2(1, 0, 0, 0, c, s, 0, -s, c, 0, 0, 0)

def m_yrot(yr: float) -> None:
    c = _f32(math.cos(yr)); s = _f32(math.sin(yr))
    m_multi2(c, 0, -s, 0, 1, 0, s, 0, c, 0, 0, 0)

def m_zrot(zr: float) -> None:
    c = _f32(math.cos(zr)); s = _f32(math.sin(zr))
    m_multi2(c, s, 0, -s, c, 0, 0, 0, 1, 0, 0, 0)

def m_scale(sx: float, sy: float, sz: float) -> None:
    mtx = _mtx_top()
    mtx.r00 = _f32(mtx.r00*sx); mtx.r01 = _f32(mtx.r01*sx); mtx.r02 = _f32(mtx.r02*sx)
    mtx.r10 = _f32(mtx.r10*sy); mtx.r11 = _f32(mtx.r11*sy); mtx.r12 = _f32(mtx.r12*sy)
    mtx.r20 = _f32(mtx.r20*sz); mtx.r21 = _f32(mtx.r21*sz); mtx.r22 = _f32(mtx.r22*sz)

def m_get(mtx_out: MATRIX) -> None:
    mtx_out.copy_from(_mtx_top())

def m_point_trans(x: float, y: float, z: float):
    mtx = _mtx_top()
    xp = _f32(_f32(_f32(_f32(x*mtx.r00) + _f32(y*mtx.r10)) + _f32(z*mtx.r20)) + mtx.psx)
    yp = _f32(_f32(_f32(_f32(x*mtx.r01) + _f32(y*mtx.r11)) + _f32(z*mtx.r21)) + mtx.psy)
    zp = _f32(_f32(_f32(_f32(x*mtx.r02) + _f32(y*mtx.r12)) + _f32(z*mtx.r22)) + mtx.psz)
    return xp, yp, zp

def m_point_trans_3x3(x: float, y: float, z: float):
    mtx = _mtx_top()
    xp = _f32(_f32(_f32(x*mtx.r00) + _f32(y*mtx.r10)) + _f32(z*mtx.r20))
    yp = _f32(_f32(_f32(x*mtx.r01) + _f32(y*mtx.r11)) + _f32(z*mtx.r21))
    zp = _f32(_f32(_f32(x*mtx.r02) + _f32(y*mtx.r12)) + _f32(z*mtx.r22))
    return xp, yp, zp

def m_inv_point_trans_3x3(x: float, y: float, z: float):
    mtx = _mtx_top()
    xp = _f32(_f32(_f32(x*mtx.r00) + _f32(y*mtx.r01)) + _f32(z*mtx.r02))
    yp = _f32(_f32(_f32(x*mtx.r10) + _f32(y*mtx.r11)) + _f32(z*mtx.r12))
    zp = _f32(_f32(_f32(x*mtx.r20) + _f32(y*mtx.r21)) + _f32(z*mtx.r22))
    return xp, yp, zp

def m_get_point():
    mtx = _mtx_top()
    return mtx.psx, mtx.psy, mtx.psz

def m_rot_axe_sin_cos(vx: float, vy: float, vz: float, s: float, c: float) -> None:
    c2 = 1.0 - c
    x = vx; y = vy; z = vz
    xyc = x*y*c2; yzc = y*z*c2; zxc = z*x*c2
    xs = x*s; ys = y*s; zs = z*s
    x2 = x*x; y2 = y*y; z2 = z*z
    tmp = MATRIX()
    tmp.r00 = x2+(1-x2)*c;  tmp.r01 = xyc+zs;         tmp.r02 = zxc-ys
    tmp.r10 = xyc-zs;        tmp.r11 = y2+(1-y2)*c;    tmp.r12 = yzc+xs
    tmp.r20 = zxc+ys;        tmp.r21 = yzc-xs;         tmp.r22 = z2+(1-z2)*c
    tmp.psx = 0.0; tmp.psy = 0.0; tmp.psz = 0.0
    m_multi(tmp)

def m_rot_axe(vx: float, vy: float, vz: float, ang: float) -> None:
    m_rot_axe_sin_cos(vx, vy, vz, math.sin(ang), math.cos(ang))

def _get_angle_yx(dx, dy, dz):
    ay = math.atan2(dx, dz)
    a = int(ay * 0x8000 / math.pi) & 0xffff
    c = dz / math.cos(ay) if ((a + 0x2000) & 0x4000) == 0 else dx / math.sin(ay)
    return -math.atan2(dy, c), ay

def _get_angle_xy(dx, dy, dz):
    ax = math.atan2(-dy, dz)
    a = int(ax * 0x8000 / math.pi) & 0xffff
    c = dz / math.cos(ax) if ((a + 0x2000) & 0x4000) == 0 else -dy / math.sin(ax)
    return ax, math.atan2(dx, c)

def _get_angle_yz(dx, dy, dz):
    ay = math.atan2(-dz, dx)
    a = int(ay * 0x8000 / math.pi) & 0xffff
    c = dx / math.cos(ay) if ((a + 0x2000) & 0x4000) == 0 else -dz / math.sin(ay)
    return ay, math.atan2(dy, c)

def _get_angle_zy(dx, dy, dz):
    az = math.atan2(dy, dx)
    a = int(az * 0x8000 / math.pi) & 0xffff
    c = dx / math.cos(az) if ((a + 0x2000) & 0x4000) == 0 else dy / math.sin(az)
    return -math.atan2(dz, c), az

def _get_angle_xz(dx, dy, dz):
    ax = math.atan2(dz, dy)
    a = int(ax * 0x8000 / math.pi) & 0xffff
    c = dy / math.cos(ax) if ((a + 0x2000) & 0x4000) == 0 else dz / math.sin(ax)
    return ax, -math.atan2(dx, c)

def _get_angle_zx(dx, dy, dz):
    az = math.atan2(-dx, dy)
    a = int(az * 0x8000 / math.pi) & 0xffff
    c = dy / math.cos(az) if ((a + 0x2000) & 0x4000) == 0 else -dx / math.sin(az)
    return math.atan2(dz, c), az

def m_get_rot_zyx():
    m_push()
    m_base_point()
    px, py, pz = m_point_trans(1.0, 0.0, 0.0)
    ya, za = _get_angle_zy(px, py, pz)
    px, py, pz = m_point_trans(0.0, 1.0, 0.0)
    m_base(); m_yrot(-ya); m_zrot(-za)
    px, py, pz = m_point_trans(px, py, pz)
    xa = math.atan2(pz, py)
    m_pop()
    return xa, ya, za

def _get_rot_yxz():
    m_push()
    m_base_point()
    px, py, pz = m_point_trans(0.0, 0.0, 1.0)
    xa, ya = _get_angle_yx(px, py, pz)
    px, py, pz = m_point_trans(1.0, 0.0, 0.0)
    m_base(); m_xrot(-xa); m_yrot(-ya)
    px, py, pz = m_point_trans(px, py, pz)
    za = math.atan2(py, px)
    m_pop()
    return xa, ya, za

def _get_rot_xyz():
    m_push()
    m_base_point()
    px, py, pz = m_point_trans(0.0, 0.0, 1.0)
    xa, ya = _get_angle_xy(px, py, pz)
    px, py, pz = m_point_trans(0.0, 1.0, 0.0)
    m_base(); m_yrot(-ya); m_xrot(-xa)
    px, py, pz = m_point_trans(px, py, pz)
    za = math.atan2(-px, py)
    m_pop()
    return xa, ya, za

def _get_rot_yzx():
    m_push()
    m_base_point()
    px, py, pz = m_point_trans(1.0, 0.0, 0.0)
    ya, za = _get_angle_yz(px, py, pz)
    px, py, pz = m_point_trans(0.0, 0.0, 1.0)
    m_base(); m_zrot(-za); m_yrot(-ya)
    px, py, pz = m_point_trans(px, py, pz)
    xa = math.atan2(-py, pz)
    m_pop()
    return xa, ya, za

def _get_rot_xzy():
    m_push()
    m_base_point()
    px, py, pz = m_point_trans(0.0, 1.0, 0.0)
    xa, za = _get_angle_xz(px, py, pz)
    px, py, pz = m_point_trans(0.0, 0.0, 1.0)
    m_base(); m_zrot(-za); m_xrot(-xa)
    px, py, pz = m_point_trans(px, py, pz)
    ya = math.atan2(px, pz)
    m_pop()
    return xa, ya, za

def _get_rot_zxy():
    m_push()
    m_base_point()
    px, py, pz = m_point_trans(0.0, 1.0, 0.0)
    xa, za = _get_angle_zx(px, py, pz)
    px, py, pz = m_point_trans(1.0, 0.0, 0.0)
    m_base(); m_xrot(-xa); m_zrot(-za)
    px, py, pz = m_point_trans(px, py, pz)
    ya = math.atan2(-pz, px)
    m_pop()
    return xa, ya, za

# Std_Model.set_bump_normal

def _Std_Model_set_bump_normal(self: "Std_Model") -> None:
    """Compute UV-space tangent-basis vectors for all polygons."""

    _PI = math.pi

    for i in range(self.polygon_num):
        s = self.polygon[i]

        if s.info_list_num < 3:
            continue

        p0_idx = s.info_list[0].point_index
        p1_idx = s.info_list[1].point_index

        Xv0 = float(self.point_list[p1_idx].x) - float(self.point_list[p0_idx].x)
        Yv0 = float(self.point_list[p1_idx].y) - float(self.point_list[p0_idx].y)
        Zv0 = float(self.point_list[p1_idx].z) - float(self.point_list[p0_idx].z)

        Uv0 = float(s.info_list[1].u) - float(s.info_list[0].u)
        Vv0 = float(s.info_list[1].v) - float(s.info_list[0].v)

        Uv1 = float(s.info_list[2].u) - float(s.info_list[0].u)
        Vv1 = float(s.info_list[2].v) - float(s.info_list[0].v)

        A0: float  = -math.atan2(Vv0, Uv0)
        add: float = _PI / 2.0

        tf: float = Uv0 * Vv1 - Vv0 * Uv1
        if tf > 0.0:
            add = -_PI / 2.0

        nx = float(s.normal.x)
        ny = float(s.normal.y)
        nz = float(s.normal.z)

        m_push()
        m_base()
        m_rot_axe(nx, ny, nz, A0)
        tx, ty, tz = m_point_trans(Xv0, Yv0, Zv0)
        m_pop()

        t1 = Std_Point()
        t1.x.assign(tx); t1.y.assign(ty); t1.z.assign(tz)
        t1.normalize()
        s.tex_normal0 = t1

        m_push()
        m_base()
        m_rot_axe(nx, ny, nz, A0 + add)
        tx, ty, tz = m_point_trans(Xv0, Yv0, Zv0)
        m_pop()

        t2 = Std_Point()
        t2.x.assign(tx); t2.y.assign(ty); t2.z.assign(tz)
        t2.normalize()
        s.tex_normal1 = t2


# open / close constants  (Std_Model::enum { open, close })
_CHK_OPEN  = 0
_CHK_CLOSE = 1


def _vec_pro_pts(v0: "Std_Point", v1: "Std_Point", v2: "Std_Point") -> "Std_Point":
    ax = float(v1.x) - float(v0.x)
    ay = float(v1.y) - float(v0.y)
    az = float(v1.z) - float(v0.z)
    bx = float(v2.x) - float(v0.x)
    by = float(v2.y) - float(v0.y)
    bz = float(v2.z) - float(v0.z)
    r = Std_Point()
    r.x.assign(ay * bz - az * by)
    r.y.assign(az * bx - ax * bz)
    r.z.assign(ax * by - ay * bx)
    return r

def _sca_pro_pts(a: "Std_Point", b: "Std_Point") -> float:
    return float(a.x)*float(b.x) + float(a.y)*float(b.y) + float(a.z)*float(b.z)

def _cos_p_pts(a: "Std_Point", b: "Std_Point") -> float:
    la = math.sqrt(_sca_pro_pts(a, a))
    lb = math.sqrt(_sca_pro_pts(b, b))
    if la == 0.0 or lb == 0.0:
        return 0.0
    return _sca_pro_pts(a, b) / (la * lb)

def _pt_sub(a: "Std_Point", b: "Std_Point") -> "Std_Point":
    r = Std_Point(); r.x.assign(float(a.x)-float(b.x)); r.y.assign(float(a.y)-float(b.y)); r.z.assign(float(a.z)-float(b.z)); return r

def _pt_len(p: "Std_Point") -> float:
    return math.sqrt(float(p.x)**2 + float(p.y)**2 + float(p.z)**2)

def _get_max_angle02(v0: "Std_Point", v1: "Std_Point", v2: "Std_Point") -> float:
    ang0 = -_cos_p_pts(_pt_sub(v1, v0), _pt_sub(v2, v0))
    ang2 = -_cos_p_pts(_pt_sub(v0, v2), _pt_sub(v1, v2))
    best = max(ang0, ang2)
    return math.acos(max(-1.0, min(1.0, -best)))

def _get_min_angle(v0: "Std_Point", v1: "Std_Point", v2: "Std_Point") -> float:
    ang0 = -_cos_p_pts(_pt_sub(v1, v0), _pt_sub(v2, v0))
    ang1 = -_cos_p_pts(_pt_sub(v0, v1), _pt_sub(v2, v1))
    ang2 = -_cos_p_pts(_pt_sub(v0, v2), _pt_sub(v1, v2))
    best = min(ang0, ang1, ang2)
    return math.acos(max(-1.0, min(1.0, -best)))

def _chk_kousa(p0: "Std_Point", p1: "Std_Point",
               t0: "Std_Point", t1: "Std_Point") -> bool:
    """Return True if segment (p0,p1) and segment (t0,t1) intersect."""
    a = _vec_pro_pts(t0, p0, p1)
    b = _vec_pro_pts(t1, p0, p1)
    c = _sca_pro_pts(a, b)
    if c <= 0.0:
        a = _vec_pro_pts(p0, t0, t1)
        b = _vec_pro_pts(p1, t0, t1)
        c = _sca_pro_pts(a, b)
        if c <= 0.0:
            return True
    return False

def _cut_list(cut_num0: int, cut_num1: int, cut_num2: int,
              max_len: int, info_concave: List[int]) -> None:
    length = 0
    for i in range(max_len):
        if info_concave[i] < 0:
            break
        length += 1

    found = length
    for i in range(length):
        if (info_concave[i % length] == cut_num0 and
                info_concave[(i + 1) % length] == cut_num1 and
                info_concave[(i + 2) % length] == cut_num2):
            found = i
            break

    if found == length:
        return

    remove_at = (found + 1) % length
    for i in range(remove_at, max_len - 1):
        info_concave[i] = info_concave[i + 1]
    info_concave[max_len - 1] = -2


def _Std_Polygon_chk_valid_polygon(self: "Std_Polygon") -> bool:
    """Validate the polygon: no two adjacent (or skip-one) vertices share"""
    self.hole_polygon = 0
    n = self.info_list_num
    for i in range(n):
        if self.info_list[i].point_index < 0:
            self.hole_polygon += 1
        a = self.info_list[i].point_index
        b = self.info_list[(i + 1) % n].point_index
        c = self.info_list[(i + 2) % n].point_index
        if a == b or a == c:
            return False
    return True


def _Std_Polygon_get_concave_triangle(
        self:              "Std_Polygon",
        info_concave:      List[int],
        t0_out:            List[int],
        t1_out:            List[int],
        t2_out:            List[int],
        o0_point_index:    int = -1,
        o1_point_index:    int = -1,
        o2_point_index:    int = -1,
) -> bool:
    """Pick the best ear-triangle from the concave-polygon index buffer"""

    # Immediately ignores the hint arguments (the #if 1 block).
    o0_point_index = -1
    o1_point_index = -1
    o2_point_index = -1

    while True:
        info_list_num_all = self.info_list_num + self.hole_polygon

        # Count active entries in info_concave
        length = 0
        for i in range(info_list_num_all):
            if info_concave[i] < 0:
                break
            length += 1

        if length == 3:
            t0_out[0] = info_concave[0]
            t1_out[0] = info_concave[1]
            t2_out[0] = info_concave[2]
            return True

        first     = False
        t0_out[0] = 0; t1_out[0] = 1; t2_out[0] = 2
        max_min_angle  = 0.0
        max_min_cutlen = 0.0
        old_p0 = old_p1 = old_p2 = 0

        for i in range(length):
            ic0 = info_concave[i % length]
            ic1 = info_concave[(i + 1) % length]
            ic2 = info_concave[(i + 2) % length]

            # Normal of this vertex
            ntmp = Std_Point()
            ntmp.x.assign(float(self.info_list[ic0].nx))
            ntmp.y.assign(float(self.info_list[ic0].ny))
            ntmp.z.assign(float(self.info_list[ic0].nz))
            ntmp.normalize()

            # Cross-product of the three candidates
            v0 = self.model.point_list[self.info_list[ic0].point_index]
            v1 = self.model.point_list[self.info_list[ic1].point_index]
            v2 = self.model.point_list[self.info_list[ic2].point_index]
            tmp = _vec_pro_pts(v0, v1, v2)

            chk = _sca_pro_pts(tmp, ntmp)
            if chk <= 0.0:
                continue

            # Check that no other polygon vertex lies inside this triangle
            inside_found = False
            for j in range(self.info_list_num):
                if self.info_list[j].point_index < 0:
                    continue
                if j == ic0 or j == ic1 or j == ic2:
                    continue
                vj = self.model.point_list[self.info_list[j].point_index]
                tmp2 = _vec_pro_pts(vj, v0, v1)
                if _sca_pro_pts(tmp2, ntmp) < 0:
                    continue
                tmp2 = _vec_pro_pts(vj, v1, v2)
                if _sca_pro_pts(tmp2, ntmp) < 0:
                    continue
                tmp2 = _vec_pro_pts(vj, v2, v0)
                if _sca_pro_pts(tmp2, ntmp) < 0:
                    continue
                inside_found = True
                break
            if inside_found:
                continue

            nt0p = self.info_list[ic0].point_index
            nt1p = self.info_list[ic1].point_index
            nt2p = self.info_list[ic2].point_index

            new_angle  = _get_max_angle02(v0, v1, v2)
            new_cutlen = _pt_len(_pt_sub(v0, v2))

            if not first:
                first = True
                t0_out[0] = ic0; t1_out[0] = ic1; t2_out[0] = ic2
                max_min_angle  = new_angle
                max_min_cutlen = new_cutlen
                old_p0 = nt0p; old_p1 = nt1p; old_p2 = nt2p
            else:
                # Adjacent-edge tie-breaker: prefer shorter diagonal
                if ((old_p0 == nt1p and old_p1 == nt2p) or
                        (old_p1 == nt0p and old_p2 == nt1p)):
                    if abs(max_min_angle - new_angle) < 0.5:
                        if new_cutlen < max_min_cutlen:
                            t0_out[0] = ic0; t1_out[0] = ic1; t2_out[0] = ic2
                            max_min_angle  = new_angle
                            max_min_cutlen = new_cutlen
                            old_p0 = nt0p; old_p1 = nt1p; old_p2 = nt2p
                        continue
                if new_angle > max_min_angle:
                    t0_out[0] = ic0; t1_out[0] = ic1; t2_out[0] = ic2
                    max_min_angle  = new_angle
                    max_min_cutlen = new_cutlen
                    old_p0 = nt0p; old_p1 = nt1p; old_p2 = nt2p

        if not first:
            _sys.stderr.write(
                "invalid polygon ??? in model:<%s>\n" % self.model.model_name)
            return False

        # o-hint check (always re-searched because if 1 block forces
        if o0_point_index != -1 and length > 3:
            new_tri_ang = _get_min_angle(
                self.model.point_list[self.info_list[t0_out[0]].point_index],
                self.model.point_list[self.info_list[t1_out[0]].point_index],
                self.model.point_list[self.info_list[t2_out[0]].point_index])
            old_tri_ang = _get_min_angle(
                self.model.point_list[o0_point_index],
                self.model.point_list[o1_point_index],
                self.model.point_list[o2_point_index])
            # Always restart
            o0_point_index = -1; o1_point_index = -1; o2_point_index = -1
            continue

        # Consume the chosen ear vertex from info_concave
        _cut_list(t0_out[0], t1_out[0], t2_out[0],
                  info_list_num_all, info_concave)

        return True

# Wrap with the simple positional signature used by callers:
# valid = s.get_concave_triangle(info_concave, &t0, &t1, &t2, o0, o1, o2)
# In Python we pass single-element lists as out-params.
def _Std_Polygon_get_concave_triangle_wrap(
        self, info_concave, t0_out, t1_out, t2_out,
        o0=-1, o1=-1, o2=-1):
    return _Std_Polygon_get_concave_triangle(
        self, info_concave, t0_out, t1_out, t2_out, o0, o1, o2)


def _Std_Polygon_cut_hole_polygon(
        self:         "Std_Polygon",
        hole_polygon: int,
        info_concave: List[int],
) -> None:
    """Merge inner hole rings into the outer ring of info_concave by"""

    info_list_num_all = self.info_list_num + hole_polygon
    group_new = [0] * info_list_num_all

    while True:

        # Measure group 0 (entries before first negative sentinel)
        group_0_len   = 0
        group_0_start = 0
        found_hole = False
        for i in range(info_list_num_all):
            if info_concave[i] < 0:
                found_hole = True
                break
            group_0_len += 1

        if not found_hole:
            return

        # Measure group 1 (entries after the sentinel)
        group_1_start = i + 1
        group_1_len   = 0
        for j in range(group_1_start, info_list_num_all):
            if info_concave[j] < 0:
                break
            group_1_len += 1

        cut_p0 = -1; cut_p1 = -1
        first  = False
        chk_len = 0.0

        for ii in range(group_0_len):
            for jj in range(group_1_len):
                p0_idx = info_concave[group_0_start + ii]
                p1_idx = info_concave[group_1_start + jj]
                new_len = _pt_len(_pt_sub(
                    self.model.point_list[self.info_list[p0_idx].point_index],
                    self.model.point_list[self.info_list[p1_idx].point_index]))

                if first and new_len >= chk_len:
                    continue

                # Check for crossing against group-0 edges
                ok = True
                for iii in range(group_0_len):
                    e0i = group_0_start + iii
                    e1i = group_0_start + (iii + 1) % group_0_len
                    if e0i == group_0_start + ii or e1i == group_0_start + ii:
                        continue
                    if _chk_kousa(
                            self.model.point_list[self.info_list[info_concave[e0i]].point_index],
                            self.model.point_list[self.info_list[info_concave[e1i]].point_index],
                            self.model.point_list[self.info_list[p0_idx].point_index],
                            self.model.point_list[self.info_list[p1_idx].point_index]):
                        ok = False; break
                if not ok:
                    continue

                # Check for crossing against group-1 edges
                for iii in range(group_1_len):
                    e0i = group_1_start + iii
                    e1i = group_1_start + (iii + 1) % group_1_len
                    if e0i == group_1_start + jj or e1i == group_1_start + jj:
                        continue
                    if _chk_kousa(
                            self.model.point_list[self.info_list[info_concave[e0i]].point_index],
                            self.model.point_list[self.info_list[info_concave[e1i]].point_index],
                            self.model.point_list[self.info_list[p0_idx].point_index],
                            self.model.point_list[self.info_list[p1_idx].point_index]):
                        ok = False; break
                if not ok:
                    continue

                first   = True
                cut_p0  = p0_idx
                cut_p1  = p1_idx
                chk_len = new_len

        if cut_p0 == -1:
            _sys.stderr.write("invalid data for divided polygons ???\n")

        # Build merged ring into group_new
        group_new_count = 0
        ii = 0
        while ii < group_0_len:
            group_new[group_new_count] = info_concave[group_0_start + ii]
            group_new_count += 1
            if info_concave[group_0_start + ii] == cut_p0:
                jj = 0
                while jj < group_1_len:
                    if info_concave[group_1_start + jj] == cut_p1:
                        break
                    jj += 1
                for kk in range(group_1_len):
                    group_new[group_new_count] = info_concave[
                        group_1_start + (jj + kk) % group_1_len]
                    group_new_count += 1
                group_new[group_new_count]     = cut_p1
                group_new_count += 1
                group_new[group_new_count]     = cut_p0
                group_new_count += 1
                ii += 1
                break
            ii += 1

        while ii < group_0_len:
            group_new[group_new_count] = info_concave[group_0_start + ii]
            group_new_count += 1
            ii += 1

        tail_start = group_1_start + group_1_len
        kk = 0
        while group_new_count < info_list_num_all:
            group_new[group_new_count] = info_concave[tail_start + kk]
            group_new_count += 1
            kk += 1

        for ii in range(info_list_num_all):
            info_concave[ii] = group_new[ii]


def _Std_Model_chk_open_close(self: "Std_Model") -> int:
    """_CHK_CLOSE (1)."""
    flag_hole = 0

    pn_calc: List[Optional["IdxList"]] = [None] * self.point_num

    _idxlist_pool_ensure(self.polygon_num * 3 + 16)
    _idxlist_pool_reset()

    for i in range(self.polygon_num):
        sp = self.polygon[i]
        for j in range(sp.info_list_num):
            inf = sp.info_list[j]
            if inf.point_index >= 0:
                pn_calc[inf.point_index] = _idxlist_alloc(
                    i, pn_calc[inf.point_index])
            else:
                flag_hole = 1

    spol  = self.polygon
    stdpnum = self.polygon_num

    for jj in range(stdpnum):
        n = spol[jj].info_list_num
        if n != 3 and n != 4:
            continue

        tc = 0
        global _dup_gen
        _dup_gen += 1
        _dup_chk_buf_ct = 0

        for ll in range(n):
            pi = spol[jj].info_list[ll].point_index
            node = pn_calc[pi]
            while node is not None:
                kk = node.pl_idx
                if (kk != jj and
                        (spol[kk].info_list_num == 3 or spol[kk].info_list_num == 4) and
                        not chk_dup_index(kk)):

                    nk = spol[kk].info_list_num

                    def _touch(ma, mb, ca, cb):
                        nonlocal tc
                        if (spol[jj].info_list[ma] == spol[kk].info_list[cb] and
                                spol[jj].info_list[mb] == spol[kk].info_list[ca]):
                            add_index(kk)
                            tc += 1

                    if n == 4 and nk == 4:
                        _touch(0,1,0,1); _touch(0,1,1,2); _touch(0,1,2,3); _touch(0,1,3,0)
                        _touch(1,2,0,1); _touch(1,2,1,2); _touch(1,2,2,3); _touch(1,2,3,0)
                        _touch(2,3,0,1); _touch(2,3,1,2); _touch(2,3,2,3); _touch(2,3,3,0)
                        _touch(3,0,0,1); _touch(3,0,1,2); _touch(3,0,2,3); _touch(3,0,3,0)

                node = node.next

        if tc != n:
            _idxlist_pool_reset()
            return _CHK_OPEN

    _idxlist_pool_reset()
    return _CHK_CLOSE if flag_hole == 0 else _CHK_OPEN


def _Std_Model_reset_triangle(self: "Std_Model", force_concave: int) -> None:
    """Decompose all polygons with ≥ 4 vertices into triangles."""

    _DIV_POLY_CHK_COLORS = [
        0xff808080, 0xffff0000, 0xff00ff00, 0xff0000ff,
        0xffffff00, 0xffff00ff, 0xff00ffff,
    ]

    def _apply_div_chk_color(pol):
        div_poly_chk_ct[0] = (div_poly_chk_ct[0] + 1) % 7
        c = _DIV_POLY_CHK_COLORS[div_poly_chk_ct[0]]
        for vi in range(3):
            pol.info_list[vi].vtx_color_A = (c >> 24) & 0xff
            pol.info_list[vi].vtx_color_R = (c >> 16) & 0xff
            pol.info_list[vi].vtx_color_G = (c >>  8) & 0xff
            pol.info_list[vi].vtx_color_B = (c >>  0) & 0xff

    pnum = 0
    ocf  = self.chk_open_close()

    for i in range(self.polygon_num):
        s = self.polygon[i]
        if self.material[s.material_index].same_flag:
            pass
        elif not s.chk_valid_polygon():
            _sys.stderr.write(
                "invalid polygon edge in model:[%s] , ignored\n" % self.model_name)
        elif s.info_list_num >= 5:
            if div_convex:
                if not s.chk_convex():
                    if div_concave:
                        pnum += s.info_list_num - 2 + self.hole_polygon
                        if self.hole_polygon > 0:
                            _sys.stderr.write(
                                "model<%s>: %d (hole)\n" % (self.model_name, s.info_list_num + self.hole_polygon))
                        elif force_concave == 0:
                            _sys.stderr.write(
                                "model<%s>: %d (concave)\n" % (self.model_name, s.info_list_num + self.hole_polygon))
                    else:
                        _sys.stderr.write(
                            "warning , model<%s>: There is concave polygon(%d). Sorry ignore...\n" % (self.model_name, s.info_list_num))
                else:
                    if force_concave == 0:
                        _sys.stderr.write(
                            "model<%s>: %d (convex)\n" % (self.model_name, s.info_list_num))
                    pnum += s.info_list_num - 2
            else:
                _sys.stderr.write(
                    "warning , model<%s>: %d polygon\n" % (self.model_name, s.info_list_num))
        elif s.info_list_num == 4:
            pnum += 2
        elif s.info_list_num == 3:
            pnum += 1
        else:
            _sys.stderr.write(
                "warning , model<%s>: %d\n" % (self.model_name, s.info_list_num))

    if pnum == 0:
        self.polygon_num = 0
        self.polygon = []
        return

    new_polygons: List[Std_Polygon] = []
    first_4kaku = True
    pid = 1

    for i in range(self.polygon_num):
        s = self.polygon[i]

        if self.material[s.material_index].same_flag:
            continue
        elif not s.chk_valid_polygon():
            continue
        elif s.info_list_num >= 5:
            if div_convex:
                do_concave = force_concave or not s.chk_convex()

                if do_concave:
                    if div_concave:
                        info_concave = []
                        for j in range(s.info_list_num):
                            info_concave.append(j if s.info_list[j].point_index >= 0 else -1)
                        if self.hole_polygon > 0:
                            for _ in range(self.hole_polygon):
                                info_concave.append(-2)
                            s.cut_hole_polygon(self.hole_polygon, info_concave)

                        o0 = o1 = o2 = -1
                        t0_buf = [0]; t1_buf = [0]; t2_buf = [0]
                        for j in range(s.info_list_num - 2 + self.hole_polygon):
                            pol = Std_Polygon()
                            pol.model          = self
                            pol.material_index = s.material_index
                            pol.info_list_num  = 3
                            pol.more_set_gr    = s.more_set_gr
                            pol.gr             = s.gr

                            valid = s.get_concave_triangle(
                                info_concave, t0_buf, t1_buf, t2_buf, o0, o1, o2)
                            if not valid:
                                pnum -= 1
                                continue
                            t0 = t0_buf[0]; t1 = t1_buf[0]; t2 = t2_buf[0]

                            from copy import copy
                            pol.info_list = [
                                copy(s.info_list[t0]),
                                copy(s.info_list[t1]),
                                copy(s.info_list[t2]),
                            ]
                            for pi in pol.info_list:
                                pi.poly = pol

                            o0 = s.info_list[t0].point_index
                            o1 = s.info_list[t1].point_index
                            o2 = s.info_list[t2].point_index

                            pol.normal      = s.normal
                            pol.tex_normal0 = s.tex_normal0
                            pol.tex_normal1 = s.tex_normal1
                            pol.poly_ID     = pid
                            pol.set_normal()

                            if new_polygons:
                                prev = new_polygons[-1]
                                if (not same_float(float(pol.normal.x), float(prev.normal.x)) or
                                        not same_float(float(pol.normal.y), float(prev.normal.y)) or
                                        not same_float(float(pol.normal.z), float(prev.normal.z))):
                                    pol.poly_ID = pid + 1; pid += 1

                            new_polygons.append(pol)
                        pid += 1
                else:
                    from copy import copy
                    for j in range(s.info_list_num - 2):
                        pol = Std_Polygon()
                        pol.model = self; pol.material_index = s.material_index
                        pol.info_list_num = 3; pol.more_set_gr = s.more_set_gr; pol.gr = s.gr
                        pol.info_list = [copy(s.info_list[0]), copy(s.info_list[j+1]), copy(s.info_list[j+2])]
                        for pi in pol.info_list: pi.poly = pol
                        pol.normal = s.normal; pol.tex_normal0 = s.tex_normal0; pol.tex_normal1 = s.tex_normal1
                        pol.poly_ID = pid; pol.set_normal()
                        if new_polygons:
                            prev = new_polygons[-1]
                            if (not same_float(float(pol.normal.x), float(prev.normal.x)) or
                                    not same_float(float(pol.normal.y), float(prev.normal.y)) or
                                    not same_float(float(pol.normal.z), float(prev.normal.z))):
                                pol.poly_ID = pid + 1; pid += 1
                        new_polygons.append(pol)
                    pid += 1

        elif s.info_list_num == 4:
            if force_concave != 0:
                from copy import copy
                info_concave = [0, 1, 2, 3]
                t0_buf = [0]; t1_buf = [0]; t2_buf = [0]
                for j in range(2):
                    pol = Std_Polygon()
                    pol.model = self; pol.material_index = s.material_index
                    pol.info_list_num = 3; pol.more_set_gr = s.more_set_gr; pol.gr = s.gr
                    valid = s.get_concave_triangle(info_concave, t0_buf, t1_buf, t2_buf)
                    if not valid: pnum -= 1; continue
                    t0 = t0_buf[0]; t1 = t1_buf[0]; t2 = t2_buf[0]
                    pol.info_list = [copy(s.info_list[t0]), copy(s.info_list[t1]), copy(s.info_list[t2])]
                    for pi in pol.info_list: pi.poly = pol
                    pol.normal = s.normal; pol.tex_normal0 = s.tex_normal0; pol.tex_normal1 = s.tex_normal1
                    pol.poly_ID = pid; pol.set_normal()
                    if new_polygons:
                        prev = new_polygons[-1]
                        if (not same_float(float(pol.normal.x), float(prev.normal.x)) or
                                not same_float(float(pol.normal.y), float(prev.normal.y)) or
                                not same_float(float(pol.normal.z), float(prev.normal.z))):
                            pol.poly_ID = pid + 1; pid += 1
                    new_polygons.append(pol)
                pid += 1
            elif div_concave and not s.chk_convex():
                from copy import copy
                info_concave = [0, 1, 2, 3]
                t0_buf = [0]; t1_buf = [0]; t2_buf = [0]
                for j in range(2):
                    pol = Std_Polygon()
                    pol.model = self; pol.material_index = s.material_index
                    pol.info_list_num = 3; pol.more_set_gr = s.more_set_gr; pol.gr = s.gr
                    valid = s.get_concave_triangle(info_concave, t0_buf, t1_buf, t2_buf)
                    if not valid: pnum -= 1; continue
                    t0 = t0_buf[0]; t1 = t1_buf[0]; t2 = t2_buf[0]
                    pol.info_list = [copy(s.info_list[t0]), copy(s.info_list[t1]), copy(s.info_list[t2])]
                    for pi in pol.info_list: pi.poly = pol
                    pol.normal = s.normal; pol.tex_normal0 = s.tex_normal0; pol.tex_normal1 = s.tex_normal1
                    pol.poly_ID = pid; pol.set_normal()
                    if new_polygons:
                        prev = new_polygons[-1]
                        if (not same_float(float(pol.normal.x), float(prev.normal.x)) or
                                not same_float(float(pol.normal.y), float(prev.normal.y)) or
                                not same_float(float(pol.normal.z), float(prev.normal.z))):
                            pol.poly_ID = pid + 1; pid += 1
                    new_polygons.append(pol)
                pid += 1
            elif ocf == _CHK_OPEN or not first_4kaku:
                from copy import copy
                pol0 = Std_Polygon()
                pol0.model = self; pol0.material_index = s.material_index
                pol0.info_list_num = 3; pol0.more_set_gr = s.more_set_gr; pol0.gr = s.gr
                pol0.info_list = [copy(s.info_list[0]), copy(s.info_list[1]), copy(s.info_list[2])]
                for pi in pol0.info_list: pi.poly = pol0
                pol0.normal = s.normal; pol0.tex_normal0 = s.tex_normal0; pol0.tex_normal1 = s.tex_normal1
                pol0.poly_ID = pid; pol0.set_normal()
                new_polygons.append(pol0)

                pol1 = Std_Polygon()
                pol1.model = self; pol1.material_index = s.material_index
                pol1.info_list_num = 3; pol1.more_set_gr = s.more_set_gr; pol1.gr = s.gr
                pol1.info_list = [copy(s.info_list[0]), copy(s.info_list[2]), copy(s.info_list[3])]
                for pi in pol1.info_list: pi.poly = pol1
                pol1.normal = s.normal; pol1.tex_normal0 = s.tex_normal0; pol1.tex_normal1 = s.tex_normal1
                pol1.poly_ID = pid; pid += 1; pol1.set_normal()
                if (not same_float(float(pol1.normal.x), float(pol0.normal.x)) or
                        not same_float(float(pol1.normal.y), float(pol0.normal.y)) or
                        not same_float(float(pol1.normal.z), float(pol0.normal.z))):
                    pol1.poly_ID = pid; pid += 1
                new_polygons.append(pol1)
            else:
                first_4kaku = False
                from copy import copy
                pol0 = Std_Polygon()
                pol0.model = self; pol0.material_index = s.material_index
                pol0.info_list_num = 3; pol0.more_set_gr = s.more_set_gr; pol0.gr = s.gr
                pol0.info_list = [copy(s.info_list[0]), copy(s.info_list[1]), copy(s.info_list[3])]
                for pi in pol0.info_list: pi.poly = pol0
                pol0.normal = s.normal; pol0.tex_normal0 = s.tex_normal0; pol0.tex_normal1 = s.tex_normal1
                pol0.poly_ID = pid; pol0.set_normal()
                new_polygons.append(pol0)

                pol1 = Std_Polygon()
                pol1.model = self; pol1.material_index = s.material_index
                pol1.info_list_num = 3; pol1.more_set_gr = s.more_set_gr; pol1.gr = s.gr
                pol1.info_list = [copy(s.info_list[1]), copy(s.info_list[2]), copy(s.info_list[3])]
                for pi in pol1.info_list: pi.poly = pol1
                pol1.normal = s.normal; pol1.tex_normal0 = s.tex_normal0; pol1.tex_normal1 = s.tex_normal1
                pol1.poly_ID = pid; pid += 1; pol1.set_normal()
                if (not same_float(float(pol1.normal.x), float(pol0.normal.x)) or
                        not same_float(float(pol1.normal.y), float(pol0.normal.y)) or
                        not same_float(float(pol1.normal.z), float(pol0.normal.z))):
                    pol1.poly_ID = pid; pid += 1
                new_polygons.append(pol1)

        elif s.info_list_num == 3:
            from copy import copy as _cp
            pol = _cp(s)
            pol.model   = self
            pol.poly_ID = pid; pid += 1
            new_polygons.append(pol)

    self.polygon     = new_polygons
    self.polygon_num = len(new_polygons)


def _Std_Model_clean_up_point(self: "Std_Model") -> None:
    """Merge duplicate point_list entries and remap polygon indices."""
    chg = list(range(self.point_num))
    chk = [0] * self.point_num

    chg_ct0 = 0
    for i in range(self.point_num - 1):
        t = self.point_list[i]
        if chk[i] == 0:
            for j in range(i + 1, self.point_num):
                if chk[j] == 0 and t == self.point_list[j]:
                    chg_ct0 += 1
                    chg[j]   = i
                    chk[j]   = 1

    if chg_ct0 == 0:
        return

    chg_ct = 0
    for i in range(self.polygon_num):
        p = self.polygon[i]
        for j in range(p.info_list_num):
            idx = p.info_list[j].point_index
            if idx >= 0 and chg[idx] != idx:
                p.info_list[j].point_index = chg[idx]
                chg_ct += 1

    if chg_ct > 0:
        _sys.stderr.write(
            "clean up point <%d> in model<%s>\n" % (chg_ct, self.model_name))


def _Std_Model_add_point_list(
        self: "Std_Model",
        v:    "Std_Point",
        diff: float,
) -> int:
    for i in range(self.point_num):
        l = _pt_len(_pt_sub(v, self.point_list[i]))
        if l < 0:
            l = -l
        if l <= diff:
            return i

    self.point_list.append(v)
    self.point_num += 1
    return -1


def _Std_Polygon_naomi2hg_modify_uv(
        self:  "Std_Polygon",
        pic_u: float,
        pic_v: float,
) -> None:
    """Scale UVs by pic_u/pic_v and wrap them into [0, MAX_K)."""
    MAX_K = 4096.0

    n = self.info_list_num
    if n == 0:
        return

    # Scale and shift
    for i in range(n):
        self.info_list[i].u = float(self.info_list[i].u) * pic_u + MAX_K / 2.0
        self.info_list[i].v = float(self.info_list[i].v) * pic_v + MAX_K / 2.0

    max_u = max(float(self.info_list[i].u) for i in range(n))
    min_u = min(float(self.info_list[i].u) for i in range(n))
    max_v = max(float(self.info_list[i].v) for i in range(n))
    min_v = min(float(self.info_list[i].v) for i in range(n))

    # Coarse wrap: bring the whole polygon inside [0, MAX_K)
    if min_u > MAX_K:
        loop_u = int(min_u / MAX_K) * MAX_K
        for i in range(n): self.info_list[i].u = float(self.info_list[i].u) - loop_u
        min_u -= loop_u; max_u -= loop_u
    elif max_u < 0.0:
        loop_u = (int(-max_u / MAX_K) + 1) * MAX_K
        for i in range(n): self.info_list[i].u = float(self.info_list[i].u) + loop_u
        min_u += loop_u; max_u += loop_u

    if min_v > MAX_K:
        loop_v = int(min_v / MAX_K) * MAX_K
        for i in range(n): self.info_list[i].v = float(self.info_list[i].v) - loop_v
        min_v -= loop_v; max_v -= loop_v
    elif max_v < 0.0:
        loop_v = (int(-max_v / MAX_K) + 1) * MAX_K
        for i in range(n): self.info_list[i].v = float(self.info_list[i].v) + loop_v
        min_v += loop_v; max_v += loop_v

    # Fine correction per-channel
    chk_u = sum(1 if float(self.info_list[i].u) >= MAX_K else
                (-1 if float(self.info_list[i].u) < 0.0 else 0)
                for i in range(n))
    chk_v = sum(1 if float(self.info_list[i].v) >= MAX_K else
                (-1 if float(self.info_list[i].v) < 0.0 else 0)
                for i in range(n))

    if chk_u == 0 and chk_v == 0:
        pass
    else:
        if chk_u != 0:
            if chk_u > 0:
                if n == chk_u:
                    off = int(max_u / MAX_K) * MAX_K
                    for i in range(n): self.info_list[i].u = float(self.info_list[i].u) - off
                else:
                    off = int(min_u / pic_u) * pic_u
                    for i in range(n): self.info_list[i].u = float(self.info_list[i].u) - off
            else:
                if n == -chk_u:
                    off = (int(-min_u / MAX_K) + 1) * MAX_K
                    for i in range(n): self.info_list[i].u = float(self.info_list[i].u) + off
                else:
                    off = (int(-min_u / pic_u) + 1) * pic_u
                    for i in range(n): self.info_list[i].u = float(self.info_list[i].u) + off

        if chk_v != 0:
            if chk_v > 0:
                if n == chk_v:
                    off = int(max_v / MAX_K) * MAX_K
                    for i in range(n): self.info_list[i].v = float(self.info_list[i].v) - off
                else:
                    off = int(min_v / pic_v) * pic_v
                    for i in range(n): self.info_list[i].v = float(self.info_list[i].v) - off
            else:
                if n == -chk_v:
                    off = (int(-min_v / MAX_K) + 1) * MAX_K
                    for i in range(n): self.info_list[i].v = float(self.info_list[i].v) + off
                else:
                    off = (int(-min_v / pic_v) + 1) * pic_v
                    for i in range(n): self.info_list[i].v = float(self.info_list[i].v) + off

    # Restore: undo the shift and scale
    for i in range(n):
        self.info_list[i].u = (float(self.info_list[i].u) - MAX_K / 2.0) / pic_u
        self.info_list[i].v = (float(self.info_list[i].v) - MAX_K / 2.0) / pic_v


def _Std_Model_naomi2hg_modify_uv(
        self:              "Std_Model",
        pic_u:             float,
        pic_v:             float,
        target_mat_index:  int,
) -> None:
    """Apply UV wrapping correction to all polygons of the given material."""
    for i in range(self.polygon_num):
        if self.polygon[i].material_index == target_mat_index:
            self.polygon[i].naomi2hg_modify_uv(pic_u, pic_v)


# NlcvOptions

@dataclass
class NlcvOptions:
    """All nlcv conversion options."""

    input_file_name: str = ""
    input_file_name_base: str = ""

    texpath: _List[str] = field(default_factory=list)
    texpath_count: int = 0
    palpath: _List[str] = field(default_factory=list)
    palpath_count: int = 0
    texoutpath: str = ""

    super_index_format: bool = False
    touch_count_max: int = 3
    no_trs: bool = False
    no_alp: bool = False
    all_flat: bool = False
    merge0: bool = False
    merge1: bool = False
    not_triangle: bool = False
    all_triangle: bool = False
    all_scale: float = 1.0
    sort_sidx_cache: bool = False
    flat_not_normal_calc: bool = False
    srch_level: int = 2

    output_after_all: bool = False
    naomi2hg: bool = False
    sph_envmap: bool = False
    div_convex: bool = False
    div_concave: bool = False
    div_trnsl: bool = False
    adjust_uv: bool = False

    @classmethod
    def defaults(cls) -> "NlcvOptions":
        opts = cls()
        opts.texpath = []
        opts.palpath = []
        return opts


# NlcvError

NLCV_OK              =  0
NLCV_ERR_INVALID_ARG = -1
NLCV_ERR_CONVERT     = -3
NLCV_ERR_OUTPUT      = -4
NLCV_ERR_INTERNAL    = -5


class NlcvError(RuntimeError):
    """Raised by the conversion pipeline when it fails."""

    def __init__(self, message: str, code: int = NLCV_ERR_CONVERT):
        super().__init__(message)
        self.code = code

# Converter-local globals
input_file_name:      str  = ""
input_file_name_base: str  = "model"
sph_envmap:           bool = False
merge0:               bool = False
merge1:               bool = False
allScale:             float = 1.0
no_trs:               bool = False
no_alp:               bool = False


def apply_options(opts: NlcvOptions) -> None:

    _apply_options_ro(opts)

    global not_triangle, all_triangle, srch_level, touch_count_max
    global flat_not_normal_calc, super_index_format, allScale
    not_triangle          = opts.not_triangle
    all_triangle          = opts.all_triangle
    srch_level            = opts.srch_level
    touch_count_max       = max(3, opts.touch_count_max)
    flat_not_normal_calc  = opts.flat_not_normal_calc
    super_index_format    = opts.super_index_format
    allScale              = opts.all_scale

    global sph_envmap
    global merge0, merge1
    global no_trs, no_alp
    global input_file_name_base

    sph_envmap   = opts.sph_envmap
    merge0        = opts.merge0
    merge1        = opts.merge1
    allScale      = opts.all_scale
    no_trs        = opts.no_trs
    no_alp        = opts.no_alp
    input_file_name_base = getattr(opts, "input_file_name_base",
                                   _strip_ext_base(opts.input_file_name))

def reset_globals() -> None:
    """
    Restore all converter-local globals to safe defaults so that a
    second conversion call works correctly.
    """
    global input_file_name, input_file_name_base
    global sph_envmap
    global merge0, merge1
    global allScale
    global no_trs, no_alp

    input_file_name       = ""
    input_file_name_base  = "model"
    sph_envmap = False
    merge0 = merge1 = False
    allScale = 1.0
    no_trs = no_alp = False


def _strip_ext_base(path: str) -> str:
    """Return the filename component of path without extension."""
    base = os.path.basename(path)
    root, _ = os.path.splitext(base)
    return root or "model"


__all__ = ['NlcvOptions', 'NlcvError']

# Initialise self-referential module aliases now that all names are defined.

PolySrch.dec_touch_count = _PolySrch_dec_touch_count
PolySrch.dec_touch_count_0 = _PolySrch_dec_touch_count_0
PolySrch.srch_even_polygon = _PolySrch_srch_even_polygon
PolySrch.srch_odd_polygon = _PolySrch_srch_odd_polygon
Std_Model.set_strip_point = _Std_Model_set_strip_point
Std_Model.srch_polygon_strip0 = _Std_Model_srch_polygon_strip0
Std_Model.srch_polygon_fan0 = _Std_Model_srch_polygon_fan0
Std_Model.init_same_point = _Std_Model_init_same_point
Std_Model.clear_same_point = _Std_Model_clear_same_point
Std_Model.chk_same_point = _Std_Model_chk_same_point
Std_Model.chk_same_point2 = _Std_Model_chk_same_point2
Std_Model.init_same_point_sort_sidx = _Std_Model_init_same_point_sort_sidx
Std_Model.clear_same_point_sort_sidx = _Std_Model_clear_same_point_sort_sidx
Std_Model.chk_same_point_sort_sidx = _Std_Model_chk_same_point_sort_sidx
Std_Model.set_same_point_sort_sidx = _Std_Model_set_same_point_sort_sidx
Std_Model.srch_polygon_strip = _Std_Model_srch_polygon_strip
Std_Model.put_point_info = _Std_Model_put_point_info
Std_Model.naomi2hg_put_point_info = _Std_Model_naomi2hg_put_point_info
Std_Model.chk_si_rate = _Std_Model_chk_si_rate
Std_Model.put_point_info2 = _Std_Model_put_point_info2
Std_Model.chk_sprite = _Std_Model_chk_sprite
Std_Model.sort_gflag = _Std_Model_sort_gflag
Std_Model.chk_repoint = _Std_Model_chk_repoint
Std_Model.get_si_rate = _Std_Model_get_si_rate
Std_Model.sort_sidx = _Std_Model_sort_sidx
Std_Model.sort_sidx2 = _Std_Model_sort_sidx2
Std_Model.all_sort_sidx = _Std_Model_all_sort_sidx
Std_Model.all_sort_sidx_grp = _Std_Model_all_sort_sidx_grp
Std_Model.put_strip_point = _Std_Model_put_strip_point
Std_Model.put_strip_point2 = _Std_Model_put_strip_point2
Std_Model.chk_touch_and_gr_set = _Std_Model_chk_touch_and_gr_set
Std_Model.set_gr = _Std_Model_set_gr
Std_Model.calc_point_normal = _Std_Model_calc_point_normal
Std_Model.get_center_pos_R = _Std_Model_get_center_pos_R
Std_Model.set_bump_normal = _Std_Model_set_bump_normal
Std_Model.chk_open_close = _Std_Model_chk_open_close
Std_Model.reset_triangle = _Std_Model_reset_triangle
Std_Model.clean_up_point = _Std_Model_clean_up_point
Std_Model.add_point_list = _Std_Model_add_point_list
Std_Model.naomi2hg_modify_uv = _Std_Model_naomi2hg_modify_uv
Std_Polygon.set_normal = _Std_Polygon_set_normal
Std_Polygon.chk_convex = _Std_Polygon_chk_convex
Std_Polygon.chk_convex3 = _Std_Polygon_chk_convex3
Std_Polygon.chk_valid_polygon = _Std_Polygon_chk_valid_polygon
Std_Polygon.get_concave_triangle = _Std_Polygon_get_concave_triangle_wrap
Std_Polygon.cut_hole_polygon = _Std_Polygon_cut_hole_polygon
Std_Polygon.naomi2hg_modify_uv = _Std_Polygon_naomi2hg_modify_uv
Std_Material.__eq__ = _Std_Material_eq
# end of nlstrip inline


xVal = 0
yVal = 1
zVal = 2

# Naomi hardware coordinate system:
#   +X = right,  +Y = up,  -Z = into screen  (right-handed)

_AXIS_TABLE: dict = {
    ('+X', '+Y'): (2,+1, 1,+1, 0,-1),
    ('+X', '+Z'): (1,-1, 2,+1, 0,-1),
    ('+X', '-Y'): (2,-1, 1,-1, 0,-1),
    ('+X', '-Z'): (1,+1, 2,-1, 0,-1),
    ('+Y', '+X'): (2,-1, 0,+1, 1,-1),
    ('+Y', '+Z'): (0,+1, 2,+1, 1,-1),
    ('+Y', '-X'): (2,+1, 0,-1, 1,-1),
    ('+Y', '-Z'): (0,-1, 2,-1, 1,-1),
    ('+Z', '+X'): (1,+1, 0,+1, 2,-1),
    ('+Z', '+Y'): (0,-1, 1,+1, 2,-1),
    ('+Z', '-X'): (1,-1, 0,-1, 2,-1),
    ('+Z', '-Y'): (0,+1, 1,-1, 2,-1),
    ('-X', '+Y'): (2,-1, 1,+1, 0,+1),
    ('-X', '+Z'): (1,+1, 2,+1, 0,+1),
    ('-X', '-Y'): (2,+1, 1,-1, 0,+1),
    ('-X', '-Z'): (1,-1, 2,-1, 0,+1),
    ('-Y', '+X'): (2,+1, 0,+1, 1,+1),
    ('-Y', '+Z'): (0,-1, 2,+1, 1,+1),
    ('-Y', '-X'): (2,-1, 0,-1, 1,+1),
    ('-Y', '-Z'): (0,+1, 2,-1, 1,+1),
    ('-Z', '+X'): (1,-1, 0,+1, 2,+1),
    ('-Z', '+Y'): (0,+1, 1,+1, 2,+1),
    ('-Z', '-X'): (1,+1, 0,-1, 2,+1),
    ('-Z', '-Y'): (0,-1, 1,-1, 2,+1),
}

# Default for NaomiLib: Blender -Y forward, Blender +Z up, neg_x=False
_DEFAULT_FORWARD = '-Y'
_DEFAULT_UP      = '+Z'
_DEFAULT_NEG_X   = False


def make_remap(forward: str = _DEFAULT_FORWARD,
               up: str = _DEFAULT_UP,
               neg_x: bool = _DEFAULT_NEG_X):
    """Return a fast remap closure: (bx, by, bz) → (nx, ny, nz) as f32.

    Parameters
    forward
        Which Blender axis maps to Naomi -Z (into screen).
        One of: '+X','-X','+Y','-Y','+Z','-Z'.  Default '-Y'.
    up
        Which Blender axis maps to Naomi +Y (up).
        One of: '+X','-X','+Y','-Y','+Z','-Z'.  Default '+Z'.
    neg_x
        If True, negate the Naomi X output (mirror left-right).
        Default False.
    """
    import struct as _st
    _pack_f = _st.Struct('<f').pack
    _unpack_f = _st.Struct('<f').unpack

    def _f32(v):
        return _unpack_f(_pack_f(v))[0]

    key = (forward, up)
    if key not in _AXIS_TABLE:
        raise ValueError(
            f"Invalid axis combination forward={forward!r} up={up!r}. "
            f"Axes must be orthogonal and from: +X -X +Y -Y +Z -Z.")

    xi, xs, yi, ys, zi, zs = _AXIS_TABLE[key]
    if neg_x:
        xs = -xs

    def _remap(bx: float, by: float, bz: float):
        v = (bx, by, bz)
        return _f32(v[xi] * xs), _f32(v[yi] * ys), _f32(v[zi] * zs)

    return _remap


def calculate_crc32(filepath):
    crc = 0
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            crc = zlib.crc32(chunk, crc)
    return f"{crc & 0xffffffff:08x}"


def get_material_parameters(obj):
    p = obj.naomi_param
    return {
        'paramType': p.paramType,
        'endOfStrip': p.endOfStrip,
        'listType': p.listType,
        'grpEn': p.grpEn,
        'stripLen': p.stripLen,
        'usrClip': p.usrClip,
        'shadow': p.shadow,
        'volume': p.volume,
        'textureUsage': p.textureUsage,
        'offsColorUsage': p.offsColorUsage,
        'gouraudShdUsage': p.gouraudShdUsage,
        'uvDataSize': p.uvDataSize,
        'mh_texID': p.mh_texID,
        'm_tex_shading': p.m_tex_shading,
        'm_ambient_light': p.m_ambient_light,
        'meshColor': tuple(p.meshColor),
        'meshOffsetColor': tuple(p.meshOffsetColor)
    }


def parameters_match(params1, params2, ambient_tolerance=1e-6):
    if len(params1) != len(params2):
        return False

    for key, val1 in params1.items():
        val2 = params2.get(key)
        if val2 is None:
            return False

        if key == 'm_ambient_light':
            if abs(val1 - val2) > ambient_tolerance:
                return False
        else:
            if val1 != val2:
                return False

    return True


def adjust_color_type_intensity(mesh_objects):
    if not mesh_objects:
        return

    previous_params = None

    for i, obj in enumerate(mesh_objects):
        if obj.naomi_param.colType not in ['2', '3']:
            continue

        current_params = get_material_parameters(obj)

        if obj.naomi_param.colType == '3' and (
                not previous_params or not parameters_match(current_params, previous_params)):
            obj.naomi_param.colType = '2'

        if obj.naomi_param.colType == '2':
            for j in range(i + 1, len(mesh_objects)):
                next_obj = mesh_objects[j]
                if next_obj.naomi_param.colType not in ['2', '3']:
                    break
                if parameters_match(current_params, get_material_parameters(next_obj)):
                    next_obj.naomi_param.colType = '3'
                else:
                    break
            previous_params = current_params


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


def get_vertex_colors(obj, merge_map=None):
    original_mode = bpy.context.object.mode if bpy.context.object else 'OBJECT'
    was_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = obj
    vertex_colors_data = {}

    _vcols = (obj.data.color_attributes
              if hasattr(obj.data, 'color_attributes')
              else obj.data.vertex_colors)

    try:
        if original_mode == 'EDIT' and obj == bpy.context.view_layer.objects.active:
            bm = bmesh.from_edit_mesh(obj.data)
            active = _vcols.active if _vcols else None
            if active:
                color_layer_name = active.name
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
            active = _vcols.active if _vcols else None
            if active:
                for loop in obj.data.loops:
                    vertex_index = loop.vertex_index
                    color = active.data[loop.index].color
                    vertex_colors_data[vertex_index] = (
                        color[0], color[1], color[2], color[3]
                    )
    finally:
        bpy.context.view_layer.objects.active = was_active

    if merge_map is not None:
        return {orig_i: vertex_colors_data[merge_map[orig_i]]
                for orig_i in range(len(merge_map))
                if merge_map[orig_i] in vertex_colors_data}

    return vertex_colors_data


def get_vertex_uvs(obj, merge_map=None):
    # Prefer nl_uv_map (import-stored, hardware UV space); fall back to Blender UV layer
    _nl_uv_flat = obj.get("nl_uv_map")
    if _nl_uv_flat is not None:
        n = len(_nl_uv_flat) // 2
        return {i: (_nl_uv_flat[i * 2], _nl_uv_flat[i * 2 + 1]) for i in range(n)}

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
                            vertex_uv_data[vertex_index] = (uv.uv[0], uv.uv[1])
        else:
            if obj.data.uv_layers.active:
                uv_layer = obj.data.uv_layers.active
                for loop in obj.data.loops:
                    vertex_index = loop.vertex_index
                    if vertex_index not in vertex_uv_data:
                        uv = uv_layer.data[loop.index].uv
                        vertex_uv_data[vertex_index] = (uv[0], uv[1])
    finally:
        bpy.context.view_layer.objects.active = was_active

    if merge_map is not None:
        return {orig_i: vertex_uv_data[merge_map[orig_i]]
                for orig_i in range(len(merge_map))
                if merge_map[orig_i] in vertex_uv_data}

    return vertex_uv_data


def mesh_data_update(collection):
    # Update depsgraph without baking transforms — world-space positions are
    # obtained via matrix_world at export time.
    original_active = bpy.context.view_layer.objects.active
    original_mode = original_active.mode if original_active else 'OBJECT'

    mesh_objects = [obj for obj in collection.objects if obj.type == 'MESH']

    try:
        for obj in mesh_objects:
            bpy.context.view_layer.objects.active = obj

            was_in_edit_mode = obj.mode == 'EDIT'
            if was_in_edit_mode:
                bpy.ops.object.editmode_toggle()
            elif obj.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

        bpy.context.view_layer.update()

    finally:
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


def recalc_centroids(collection, recalc_individual=True, recalc_collection=True):
    ctx = bpy.context
    orig_active = ctx.view_layer.objects.active
    orig_selected = ctx.selected_objects.copy()
    orig_mode = ctx.object.mode if ctx.object else 'OBJECT'

    mesh_objects = [o for o in collection.objects if o.type == 'MESH' and o.data.vertices]

    coll_vertices = []

    try:
        for o in ctx.selected_objects:
            o.select_set(False)

        for obj in mesh_objects:
            obj.select_set(True)
            ctx.view_layer.objects.active = obj

            if obj.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')

            mesh = obj.data
            mesh.update()
            mesh.calc_loop_triangles()

            mw = obj.matrix_world
            verts = np.array([(mw @ v.co)[:] for v in mesh.vertices], dtype=np.float32)
            if not verts.size:
                obj.select_set(False)
                continue

            if recalc_individual:
                minc, maxc = np.min(verts, 0), np.max(verts, 0)
                centroid = ((minc + maxc) / 2).astype(np.float32)
                radius   = float(np.sqrt(((verts - centroid) ** 2).sum(1).max()))

                _snap_thresh = 4.0 * (2.0 ** -23) * radius
                cx_raw = float(centroid[0])
                cy_raw = float(centroid[1])
                cz_raw = float(centroid[2])
                cx = 0.0 if abs(cx_raw) < _snap_thresh else cx_raw
                cy = 0.0 if abs(cy_raw) < _snap_thresh else cy_raw
                cz = 0.0 if abs(cz_raw) < _snap_thresh else cz_raw
                if hasattr(obj, "naomi_param"):
                    obj.naomi_param.centroid_x   = cx
                    obj.naomi_param.centroid_y   = cy
                    obj.naomi_param.centroid_z   = cz
                    obj.naomi_param.bound_radius = radius

            if recalc_collection and hasattr(obj, "naomi_param"):
                coll_vertices.append(verts)

            obj.select_set(False)

        if recalc_collection:
            if not coll_vertices:
                if hasattr(collection, "naomi_centroidData"):
                    collection.naomi_centroidData.centroid_x = \
                        collection.naomi_centroidData.centroid_y = \
                        collection.naomi_centroidData.centroid_z = 0.0
                    collection.naomi_centroidData.collection_bound_radius = 0.0
            else:
                allv     = np.vstack(coll_vertices).astype(np.float32)
                minc, maxc = np.min(allv, 0), np.max(allv, 0)
                centroid = ((minc + maxc) / 2).astype(np.float32)
                radius   = float(np.sqrt(((allv - centroid) ** 2).sum(1).max()))
                _snap_thresh = 4.0 * (2.0 ** -23) * radius
                cx_raw = float(centroid[0])
                cy_raw = float(centroid[1])
                cz_raw = float(centroid[2])
                cx = 0.0 if abs(cx_raw) < _snap_thresh else cx_raw
                cy = 0.0 if abs(cy_raw) < _snap_thresh else cy_raw
                cz = 0.0 if abs(cz_raw) < _snap_thresh else cz_raw
                if hasattr(collection, "naomi_centroidData"):
                    collection.naomi_centroidData.centroid_x              = cx
                    collection.naomi_centroidData.centroid_y              = cy
                    collection.naomi_centroidData.centroid_z              = cz
                    collection.naomi_centroidData.collection_bound_radius = radius

    finally:
        for o in ctx.selected_objects: o.select_set(False)
        for o in orig_selected: o.select_set(True)
        ctx.view_layer.objects.active = orig_active
        if orig_active and orig_mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode=orig_mode)
            except:
                pass


def _sort_mesh_objects_for_export(mesh_objects):
    """Reorder mesh objects so each bump-map base mesh is immediately followed
    by its _bump partner, matching the binary slot order."""
    bump_objs  = [o for o in mesh_objects
                  if getattr(getattr(o, 'naomi_param', None), 'naomi_flag_bump', False)]
    other_objs = [o for o in mesh_objects if o not in bump_objs]

    pmap = {}
    for bm in bump_objs:
        pname = getattr(getattr(bm, 'naomi_param', None), 'bump_partner_name', '')
        if pname:
            pmap[pname] = bm

    ordered = []
    for o in other_objs:
        ordered.append(o)
        if o.name in pmap:
            ordered.append(pmap[o.name])

    placed = set(id(o) for o in ordered)
    for bm in bump_objs:
        if id(bm) not in placed:
            ordered.append(bm)

    return ordered


def update_naomi_bin(filepath, collection, update_centroids=False):
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

    _fwd      = collection.naomi_import_meta.import_forward_axis or _DEFAULT_FORWARD
    _up       = collection.naomi_import_meta.import_up_axis      or _DEFAULT_UP
    _remap_fn = make_remap(_fwd, _up)

    mesh_data_update(collection)
    bpy.context.view_layer.update()

    if update_centroids:
        recalc_centroids(collection)

    import re as _re
    def _slot_key(o):
        """Sort by stored binary slot index; fall back to natural name sort."""
        idx = o.get("nl_slot_index")
        if idx is not None:
            return (0, int(idx), [])
        return (1, 0, [int(t) if t.isdigit() else t.lower()
                       for t in _re.split(r'(\d+)', o.name)])

    all_mesh = [obj for obj in collection.objects if obj.type == 'MESH']
    mesh_objects = sorted(
        [obj for obj in all_mesh
         if hasattr(obj, 'naomi_param') and obj.naomi_param.naomi_assigned],
        key=_slot_key
    )
    if not mesh_objects:
        mesh_objects = sorted(all_mesh, key=_slot_key)
    mesh_objects = _sort_mesh_objects_for_export(mesh_objects)
    adjust_color_type_intensity(mesh_objects)

    gp0 = collection.gp0
    gp1 = collection.gp1
    file_data[0x0] = 0x00 if gp0.objFormat == '0' else 0x01

    gflag1 = 0x0001
    if gp1.skp1stSrcOp: gflag1 |= (1 << 1)
    if gp1.envMap: gflag1 |= (1 << 2)
    if gp1.pltTex: gflag1 |= (1 << 3)
    if gp1.bumpMap: gflag1 |= (1 << 4)
    file_data[0x4:0x6] = struct.pack('<H', gflag1)

    def _snap_centroid_component(v: float, radius: float) -> float:
        """Snap near-zero f32 noise to 0.0; clamp denormals to ±0.0."""
        import math as _m
        bits = struct.unpack('<I', struct.pack('<f', v))[0]
        exp  = (bits >> 23) & 0xFF
        mant = bits & 0x7FFFFF
        if exp == 0 and mant != 0:            # denormal
            return _m.copysign(0.0, v)
        thresh = 4.0 * (2.0 ** -23) * max(abs(radius), 1e-6)
        return 0.0 if abs(v) < thresh else v

    _col_r = collection.naomi_centroidData.collection_bound_radius
    _raw_cx = collection.naomi_centroidData.centroid_x
    _raw_cy = collection.naomi_centroidData.centroid_y
    _raw_cz = collection.naomi_centroidData.centroid_z
    _col_cx = _snap_centroid_component(_raw_cx, _col_r)
    _col_cy = _snap_centroid_component(_raw_cy, _col_r)
    _col_cz = _snap_centroid_component(_raw_cz, _col_r)
    if _col_cx != _raw_cx or _col_cy != _raw_cy or _col_cz != _raw_cz:
        pass    # snap applied silently

    rev_cx, rev_cy, rev_cz = _remap_fn(_col_cx, _col_cy, _col_cz)
    write_float_at(file_data, 0x8,  rev_cx)
    write_float_at(file_data, 0xC,  rev_cy)
    write_float_at(file_data, 0x10, rev_cz)
    write_float_at(file_data, 0x14, _col_r)

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

        _mesh_r   = p.bound_radius
        _mesh_cx  = _snap_centroid_component(p.centroid_x, _mesh_r)
        _mesh_cy  = _snap_centroid_component(p.centroid_y, _mesh_r)
        _mesh_cz  = _snap_centroid_component(p.centroid_z, _mesh_r)

        rev_mx, rev_my, rev_mz = _remap_fn(_mesh_cx, _mesh_cy, _mesh_cz)
        write_float_at(file_data, current_pos,      rev_mx)
        write_float_at(file_data, current_pos + 4,  rev_my)
        write_float_at(file_data, current_pos + 8,  rev_mz)
        write_float_at(file_data, current_pos + 12, _mesh_r)
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

        mw = current_obj.matrix_world
        _merged_verts = [mw @ v.co for v in current_mesh.vertices]

        _raw_merge_map = current_obj.get("nl_merge_map")
        if _raw_merge_map is not None:
            vertex_positions = [_merged_verts[int(idx)] for idx in _raw_merge_map]
        else:
            vertex_positions = _merged_verts

        vertex_index = 0

        vertex_colors_data = {}
        vertex_uv_data = {}

        if hasattr(current_obj.naomi_param, "m_tex_shading") and current_obj.naomi_param.m_tex_shading == -3:
            vertex_colors_data = get_vertex_colors(current_obj, _raw_merge_map)

        vertex_uv_data = get_vertex_uvs(current_obj, _raw_merge_map)

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
                        rev_x, rev_y, rev_z = _remap_fn(co[0], co[1], co[2])

                        write_float_x_aligned(file_data, current_pos,     rev_x)
                        write_float_at(file_data, current_pos + 4,        rev_y)
                        write_float_at(file_data, current_pos + 8,        rev_z)
                        current_pos += 12

                        tex_shading = getattr(current_obj.naomi_param, 'm_tex_shading', 0)

                        if tex_shading == -3:    # Type C
                            current_pos += 4    # skip normal (3 bytes + padding)

                            if vertex_colors_data and vertex_index in vertex_colors_data:
                                color_data = vertex_colors_data[vertex_index]
                                b = int(max(0, min(255, color_data[2] * 255)))
                                g = int(max(0, min(255, color_data[1] * 255)))
                                r = int(max(0, min(255, color_data[0] * 255)))
                                a = int(max(0, min(255, color_data[3] * 255)))
                                for i, val in enumerate([b, g, r, a, b, g, r, a]):
                                    write_uint8_at(file_data, current_pos + i, val)
                            current_pos += 8

                            if p.mh_texID == -1:
                                write_uint32_at(file_data, current_pos, 0)
                                write_uint32_at(file_data, current_pos + 4, 1)
                            else:
                                if vertex_index in vertex_uv_data:
                                    u, v = vertex_uv_data[vertex_index]
                                    write_float_at(file_data, current_pos, u)
                                    write_float_at(file_data, current_pos + 4, v)
                            current_pos += 8

                        elif tex_shading == -2:    # Type D
                            current_pos += 4    # skip normal
                            current_pos += 4    # skip bump0 normal
                            current_pos += 4    # skip bump1 normal

                            if p.mh_texID == -1:
                                write_uint32_at(file_data, current_pos, 0)
                                write_uint32_at(file_data, current_pos + 4, 1)
                            else:
                                if vertex_index in vertex_uv_data:
                                    u, v = vertex_uv_data[vertex_index]
                                    write_float_at(file_data, current_pos, u)
                                    write_float_at(file_data, current_pos + 4, v)
                            current_pos += 8

                        else:    # Type A
                            current_pos += 12    # skip normals (3 floats)

                            if p.mh_texID == -1:
                                write_uint32_at(file_data, current_pos, 0)
                                write_uint32_at(file_data, current_pos + 4, 1)
                            else:
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


DK_TXT_ALPHA     = 1
DK_TXT_INTENSITY = 2
DK_TXT_NO_MASK   = 3


def _write_pal_from_pvp(pvp_path: str, pal_path: str) -> None:
    """Convert a PVPL palette file (.pvp) to a PALT .pal file beside the PVR.
    nlstrip's get_pal_file() only searches for '.pal'; this converts .pvp on demand."""
    import struct as _struct
    _MODE_TO_NM = {565: 1, 4444: 2, 8888: 7}

    try:
        with open(pvp_path, 'rb') as f:
            raw = f.read()
    except OSError:
        return

    if len(raw) < 0x10 or raw[:4] != b'PVPL':
        return

    pixel_type  = raw[0x08]
    if pixel_type == 1:
        mode = 565
    elif pixel_type == 2:
        mode = 4444
    elif pixel_type == 6:
        mode = 8888
    else:
        mode = 555

    nm_fmt      = _MODE_TO_NM.get(mode, 0)
    ttl_entries = _struct.unpack_from('<H', raw, 0x0e)[0]
    bytes_each  = 4 if mode == 8888 else 2

    entries_raw = raw[0x10: 0x10 + ttl_entries * bytes_each]
    if len(entries_raw) < ttl_entries * bytes_each:
        return

    pal_entries = bytearray()
    for i in range(ttl_entries):
        off = i * bytes_each
        val = _struct.unpack_from('<H' if bytes_each == 2 else '<I',
                                   entries_raw, off)[0]
        pal_entries += _struct.pack('<I', val)

    palette_size = len(pal_entries)    # = ttl_entries * 4
    header = (b'PALT'
              + _struct.pack('<I', palette_size)
              + _struct.pack('<I', ttl_entries)
              + _struct.pack('<I', nm_fmt))

    try:
        with open(pal_path, 'wb') as f:
            f.write(header + pal_entries)
    except OSError:
        pass


def _tm_tex_size(obj, tex_id: int):
    """Return (tex_width, tex_height) from the Texture Manager slot, or (0, 0)."""
    if tex_id < 0:
        return (0, 0)
    try:
        for col in bpy.data.collections:
            if obj.name not in col.objects:
                continue
            cd = getattr(col, 'naomi_centroidData', None)
            if cd is None or not cd.naomi_assigned:
                continue
            tm = getattr(col, 'naomi_tm', None)
            if tm is None:
                continue
            for item in tm.tex_list:
                if item.tex_id == tex_id and not item.is_empty:
                    return (item.tex_width, item.tex_height)
    except Exception:
        pass
    return (0, 0)


# Material builder

def _build_std_material(obj, opts) -> Std_Material:
    """Build a Std_Material from a mesh object's Naomi custom properties."""

    mat = Std_Material()

    p  = obj.naomi_param
    t  = obj.naomi_tsp
    tc = obj.naomi_texCtrl
    it = obj.naomi_isp_tsp

    has_tex    = (int(p.textureUsage) == 1) and (p.mh_texID >= 0)
    is_bump    = bool(getattr(p, 'naomi_flag_bump', False))
    is_palette = bool(getattr(p, 'naomi_flag_palette', False))

    shad = p.m_tex_shading
    if shad == -3:
        raw_shading = 7
    elif shad == -2 or is_bump:
        raw_shading = 5
    elif shad == -1:
        raw_shading = 1
    elif shad > 0:
        raw_shading = 4
    else:
        raw_shading = 3
    mat.shading_type = raw_shading

    mat.mat_name = obj.name

    mc = p.meshColor
    oc = p.meshOffsetColor

    amb_scale = 1.0 if has_tex else float(p.m_ambient_light)
    amb_scale = max(0.0, min(1.0, amb_scale))

    mat.amb_R.assign(_f32(float(mc[0]) * amb_scale))
    mat.amb_G.assign(_f32(float(mc[1]) * amb_scale))
    mat.amb_B.assign(_f32(float(mc[2]) * amb_scale))
    mat.dif_R.assign(_f32(float(mc[0])))
    mat.dif_G.assign(_f32(float(mc[1])))
    mat.dif_B.assign(_f32(float(mc[2])))
    mat.spc_R.assign(_f32(float(oc[0])))
    mat.spc_G.assign(_f32(float(oc[1])))
    mat.spc_B.assign(_f32(float(oc[2])))

    if mat.shading_type == 7:
        mat.exp.assign(25.0)
    elif getattr(p, 'spec_int', 0) > 0:
        mat.exp.assign(float(p.spec_int))
    else:
        mat.exp.assign(10.0)

    _lt = int(getattr(p, 'listType', 2))
    if _lt in (0, 4):
        mat_transp = 0.0
    else:
        mat_transp = max(0.0, 1.0 - float(mc[3]))
    mat.trs.assign(0.0 if no_trs else mat_transp)

    culling_val = int(it.culling)
    two_sided = bool(getattr(p, 'naomi_flag_two_sided', False))
    if two_sided:
        mat.double_side = True
    else:
        blender_mat = obj.data.materials[0] if obj.data.materials else None
        if blender_mat is not None:
            mat.double_side = not blender_mat.use_backface_culling
        else:
            mat.double_side = (culling_val <= 1)

    mat.fog_mode = int(t.fogOp)
    mat.fog      = (mat.fog_mode != 2)
    mat.fade = True

    list_type = int(p.listType)
    mat.env_map         = bool(getattr(p, 'naomi_flag_env_map', False))
    mat.punch_through   = (list_type == 4)
    mat.color_clamp     = bool(int(t.colorClamp))
    mat.scan_order      = 0 if is_palette else int(tc.scanOrder)
    mat.shadow_effect   = bool(int(p.shadow))
    _sa = int(t.srcAlpha)
    _da = int(t.dstAlpha)
    if _sa == 1 and _da == 0:
        mat.src_alpha_instr = -1
        mat.dst_alpha_instr = -1
    else:
        mat.src_alpha_instr = _sa
        mat.dst_alpha_instr = _da

    if has_tex:
        tex_id_str = str(p.mh_texID)
        raw_pic = cut_mip_map_name(tex_id_str)
        mat.fullpath_pic_name = raw_pic
        mat.pic_name          = file_name_base(raw_pic)
        try:
            mat.tex_id = int(mat.pic_name)
        except (ValueError, TypeError):
            mat.tex_id = p.mh_texID
        mat.pal_name          = ''
        mat.fullpath_pal_name = ''

        if is_palette and mat.tex_id >= 0:
            _tex_stem = f"TexID_{mat.tex_id:03d}"
            mat.pal_name = _tex_stem
            try:
                import bpy as _bpy, os as _os
                _folder = ''
                for _col in _bpy.data.collections:
                    if obj.name in _col.objects:
                        _tm = getattr(_col, 'naomi_tm', None)
                        if _tm and _tm.tex_folder:
                            _folder = _bpy.path.abspath(_tm.tex_folder)
                            break
                if _folder:
                    _pal_path = _os.path.join(_folder, _tex_stem + '.pal')
                    _pvp_path = _os.path.join(_folder, _tex_stem + '.pvp')
                    if _os.path.exists(_pal_path):
                        mat.fullpath_pal_name = _os.path.join(_folder, _tex_stem)
                    elif _os.path.exists(_pvp_path):
                        _write_pal_from_pvp(_pvp_path, _pal_path)
                        mat.fullpath_pal_name = _os.path.join(_folder, _tex_stem)
            except Exception:
                pass

        _tw, _th = _tm_tex_size(obj, mat.tex_id)
        if _tw == 0 and _th == 0:
            _scale = 2 if bool(tc.vqCompressed) else 1
            _tw = (8 << int(t.texUSize)) * _scale
            _th = (8 << int(t.texVSize)) * _scale
        mat.tex_size_u = _tw
        mat.tex_size_v = _th

        mat.ignore_tex_alpha = int(t.alphaTexOp)    # 0=UseTexAlpha, 1=Ignore

        mat.uAlternate = int(t.uvFlip) >> 1 & 1
        mat.vAlternate = int(t.uvFlip) & 1
        mat.clamp_u    = int(t.uvClamp) >> 1 & 1
        mat.clamp_v    = int(t.uvClamp) & 1

        mat.blend = 1.0
        mat.tex_amb.assign(_f32(float(p.m_ambient_light)))

        mat.effect    = 0
        mat.transpFct = -1.0

        mat.filter_mode = int(t.filter)
        mat.super_sample_tex = bool(int(t.supSample))
        mat.mipmap_d_adjust  = int(t.mipmapDAdj)

        mat.mip_mapped    = int(tc.mipMapped)
        mat.vq_compressed = bool(tc.vqCompressed)

        if is_bump:
            _pix_fmt = PIX_BUMP_MAP
        else:
            _pix_fmt = int(tc.pixelFormat)
            if is_palette and _pix_fmt not in (5, 6):
                _pix_fmt = 6
        mat.pixel_format = _pix_fmt

        mat.tsi_parameter = -1

        mat.bump_map               = (mat.pixel_format == PIX_BUMP_MAP)
        mat.auto_bump_map_generate = False

        mat.roughness = 10.0

    else:
        mat.pic_name          = ''
        mat.fullpath_pic_name = ''
        mat.blend             = 0.0
        mat.uAlternate        = 0
        mat.vAlternate        = 0

        dif_int = (float(mc[0]) + float(mc[1]) + float(mc[2])) / 3.0
        amb_int = dif_int * amb_scale
        mat.tex_amb.assign(_f32(min(1.0, amb_int / dif_int) if dif_int > 0 else 1.0))
        mat.effect    = DK_TXT_INTENSITY
        mat.transpFct = 0.0

    if is_bump:
        mat.pixel_format       = PIX_BUMP_MAP
        mat.bump_map           = True
        mat.auto_bump_map_generate = False

    if no_alp:
        mat.effect = DK_TXT_INTENSITY

    return mat

def blender_collection_to_std_models(
        collection,
        opts,
        forward_axis: str = '+Y',
        up_axis: str = '+Z',
        neg_x: bool = False,
) -> None:
    
    global StdModelCount
    remap_fn = make_remap(forward_axis, up_axis, neg_x)

    import re as _re
    def _slot_key(o):
        """Sort by stored binary slot index; fall back to natural name sort."""
        idx = o.get("nl_slot_index")
        if idx is not None:
            return (0, int(idx), [])
        return (1, 0, [int(t) if t.isdigit() else t.lower()
                       for t in _re.split(r'(\d+)', o.name)])

    _raw = sorted(
        [o for o in collection.objects if o.type == 'MESH'
         and getattr(o, 'naomi_param', None) is not None
         and o.naomi_param.naomi_assigned],
        key=_slot_key
    )
    _bump_objs  = [o for o in _raw if getattr(o.naomi_param, 'naomi_flag_bump', False)]
    _other_objs = [o for o in _raw if o not in _bump_objs]

    _pmap = {}
    for _bm in _bump_objs:
        _np = _bm.naomi_param
        _partner_obj = getattr(_np, 'bump_partner_obj', None)
        if _partner_obj is None:
            _pname = getattr(_np, 'bump_partner_name', '')
            if _pname:
                _partner_obj = bpy.data.objects.get(_pname)
        if _partner_obj is not None and _partner_obj in _other_objs:
            _pmap[_partner_obj] = _bm

    _ordered = []
    for _o in _other_objs:
        _ordered.append(_o)
        if _o in _pmap:
            _ordered.append(_pmap[_o])
    _placed = set(_ordered)
    for _bm in _bump_objs:
        if _bm not in _placed:
            _ordered.append(_bm)
    mesh_objects = _ordered

    if not mesh_objects:
        return

    depsgraph = bpy.context.evaluated_depsgraph_get()

    needed = StdModelCount + len(mesh_objects)
    while len(StdModel) < needed:
        StdModel.append(Std_Model())

    for slot_idx, obj in enumerate(mesh_objects):
        STM = StdModel[StdModelCount]
        _fill_std_model(STM, obj, opts, remap_fn, depsgraph)
        StdModelCount += 1


def _fix_nonmanifold_inplace(mesh) -> int:
    """
    Split every edge shared by more than 2 faces directly on a Mesh datablock
    that lives only in memory (never written back to obj.data).
    Returns the number of edges that were split.
    """
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    bad_edges = [e for e in bm.edges if len(e.link_faces) > 2]
    n_splits = 0

    for edge in bad_edges:
        faces = list(edge.link_faces)
        for face in faces[2:]:
            new_verts = []
            for v in (edge.verts[0], edge.verts[1]):
                nv = bm.verts.new(v.co.copy())
                nv.normal = v.normal.copy()
                new_verts.append(nv)
            old_v0, old_v1 = edge.verts[0], edge.verts[1]
            new_v0, new_v1 = new_verts[0], new_verts[1]
            remap = {old_v0: new_v0, old_v1: new_v1}
            new_face_verts = [remap.get(lv, lv) for lv in face.verts]
            old_loops = list(face.loops)
            try:
                new_face = bm.faces.new(new_face_verts)
                new_face.smooth = face.smooth
                new_face.normal_update()
                for layer in bm.loops.layers.uv.values():
                    for old_lp, new_lp in zip(old_loops, new_face.loops):
                        new_lp[layer].uv = old_lp[layer].uv.copy()
                for layer in bm.loops.layers.color.values():
                    for old_lp, new_lp in zip(old_loops, new_face.loops):
                        new_lp[layer] = old_lp[layer]
                bm.faces.remove(face)
                n_splits += 1
            except ValueError:
                bm.verts.remove(new_v0)
                bm.verts.remove(new_v1)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return n_splits


_WELD_MERGE_THRESHOLD = 1.175494e-38    # smallest positive float32


def _fill_std_model(
        STM: 'Std_Model',
        obj,
        opts,
        remap_fn,
        depsgraph=None,
) -> None:
    """Populate a single Std_Model from one Blender mesh object.

    When opts.remesh is True: applies WELD + TRIANGULATE modifiers in-memory
    (obj.data is never modified), then fixes non-manifold edges on the evaluated mesh.
    """
    p = obj.naomi_param

    STM.model_name = obj.name

    smooth_angle = math.radians(60.0)
    if hasattr(obj.data, 'auto_smooth_angle'):
        smooth_angle = obj.data.auto_smooth_angle
    STM.discAngle = smooth_angle

    mat = _build_std_material(obj, opts)
    STM.material_num = 1
    STM.material     = [mat]

    do_remesh     = getattr(opts, 'remesh', False)
    tmp_mod_names = []
    if do_remesh:
        weld = obj.modifiers.new(name='_nl_export_weld', type='WELD')
        weld.merge_threshold = _WELD_MERGE_THRESHOLD
        tmp_mod_names.append(weld.name)

        tri = obj.modifiers.new(name='_nl_export_tri', type='TRIANGULATE')
        tri.quad_method = 'BEAUTY'
        tri.ngon_method = 'BEAUTY'
        tmp_mod_names.append(tri.name)

    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()

    if do_remesh:
        depsgraph.update()

    eval_obj  = obj.evaluated_get(depsgraph)
    eval_mesh = eval_obj.to_mesh()

    try:
        if do_remesh:
            _fix_nonmanifold_inplace(eval_mesh)

        if hasattr(eval_mesh, 'calc_normals_split'):
            eval_mesh.calc_normals_split()
        eval_mesh.calc_loop_triangles()

        mw = obj.matrix_world
        _fill_points(STM, obj, eval_mesh, remap_fn, mw)
        _fill_polygons(STM, obj, eval_mesh, remap_fn, mat, mw)

    finally:
        if hasattr(eval_mesh, 'free_normals_split'):
            eval_mesh.free_normals_split()
        eval_obj.to_mesh_clear()
        for name in tmp_mod_names:
            mod = obj.modifiers.get(name)
            if mod is not None:
                obj.modifiers.remove(mod)

    STM.gouraud = any(sp.gr for sp in STM.polygon) if STM.polygon else False

    if not STM.gouraud:
        STM.discAngle = -1.0


def _fill_points(STM, obj, eval_mesh, remap_fn, matrix_world) -> None:
    """Build STM.point_list from evaluated mesh vertices with axis remapping.

    Quantises coords to f32, clamps subnormals to ±0.0, and snaps near-zero
    components to 0.0 within 4 ULPs of the mesh's bounding radius.
    """
    import struct as _st
    import math   as _ma

    _pack_f   = _st.Struct('<f').pack
    _unpack_I = _st.Struct('<I').unpack

    def _q(v: float) -> float:
        """Round-trip through IEEE-754 single precision."""
        if v == 0.0 and _ma.copysign(1.0, v) > 0.0:
            return 0.0
        return _st.unpack('<f', _pack_f(v))[0]

    def _is_subnormal(f32v: float) -> bool:
        b = _unpack_I(_pack_f(f32v))[0]
        return (b >> 23) & 0xFF == 0 and b & 0x7FFFFF != 0

    mw = matrix_world
    n = len(eval_mesh.vertices)
    STM.point_num  = n
    STM.point_list = [Std_Point() for _ in range(n)]

    coords = []

    for v in eval_mesh.vertices:
        wp = mw @ v.co
        rx64, ry64, rz64 = remap_fn(wp.x, wp.y, wp.z)
        rx = _q(rx64); ry = _q(ry64); rz = _q(rz64)

        if _is_subnormal(rx): rx = _ma.copysign(0.0, rx)
        if _is_subnormal(ry): ry = _ma.copysign(0.0, ry)
        if _is_subnormal(rz): rz = _ma.copysign(0.0, rz)

        coords.append((rx, ry, rz))

    if coords:
        max_x = max(c[0] for c in coords)
        min_x = min(c[0] for c in coords)
        max_y = max(c[1] for c in coords)
        min_y = min(c[1] for c in coords)
        max_z = max(c[2] for c in coords)
        min_z = min(c[2] for c in coords)
        half_diag = _ma.sqrt(
            ((max_x - min_x) / 2) ** 2 +
            ((max_y - min_y) / 2) ** 2 +
            ((max_z - min_z) / 2) ** 2
        )
        snap_thresh = 4.0 * (2.0 ** -23) * half_diag
    else:
        snap_thresh = 0.0

    if snap_thresh > 0.0:
        coords = [
            (0.0 if abs(rx) < snap_thresh else rx,
             0.0 if abs(ry) < snap_thresh else ry,
             0.0 if abs(rz) < snap_thresh else rz)
            for rx, ry, rz in coords
        ]

    for i, (rx, ry, rz) in enumerate(coords):
        pt = STM.point_list[i]
        pt.x._data  = rx
        pt.y._data  = ry
        pt.z._data  = rz
        pt.tag_flag = 0


def _fill_polygons(STM, obj, eval_mesh, remap_fn,
                   mat: Std_Material, matrix_world) -> None:
    """Build STM.polygon[] from evaluated mesh triangles."""
    import struct as _struct
    _pack   = _struct.pack
    _unpack = _struct.unpack
    _SF     = Std_Float
    _f32l   = _f32

    try:
        nm = matrix_world.to_3x3().inverted().transposed()
    except ValueError:
        nm = matrix_world.to_3x3()

    def _transform_normal(nx, ny, nz):
        """Apply normal matrix and normalise."""
        tx = nm[0][0]*nx + nm[0][1]*ny + nm[0][2]*nz
        ty = nm[1][0]*nx + nm[1][1]*ny + nm[1][2]*nz
        tz = nm[2][0]*nx + nm[2][1]*ny + nm[2][2]*nz
        l2 = tx*tx + ty*ty + tz*tz
        if l2 > 1e-20:
            inv = l2 ** -0.5
            return tx*inv, ty*inv, tz*inv
        return 0.0, 0.0, 1.0

    uv_layer  = eval_mesh.uv_layers.active
    loops_ref = eval_mesh.loops
    tris      = eval_mesh.loop_triangles
    n_tris    = len(tris)

    has_tex   = (int(obj.naomi_param.textureUsage) == 1 and
                 obj.naomi_param.mh_texID >= 0)
    is_type_c = (obj.naomi_param.m_tex_shading == -3)
    uv_data   = uv_layer.data if (has_tex and uv_layer) else None

    remap = remap_fn

    loop_colors = None
    if is_type_c:
        vcol_name = getattr(obj.naomi_param, 'vcol_layer_name', '') or 'NaomiCol'
        _vcols = (eval_mesh.color_attributes
                  if hasattr(eval_mesh, 'color_attributes')
                  else eval_mesh.vertex_colors)
        col_layer = (_vcols.get(vcol_name)
                     or _vcols.get('NaomiCol')
                     or (_vcols.active if _vcols else None))

        if col_layer is not None:
            cd = col_layer.data
            loop_colors = {}
            for li in range(len(eval_mesh.loops)):
                c = cd[li].color
                loop_colors[li] = (int(c[0]*255), int(c[1]*255),
                                   int(c[2]*255), int(c[3]*255))

    blender_mat = obj.data.materials[0] if obj.data.materials else None
    if blender_mat is not None:
        backface_on = blender_mat.use_backface_culling
    else:
        backface_on = (int(obj.naomi_isp_tsp.culling) >= 2)

    if backface_on:
        order = (0, 1, 2)
    else:
        order = (2, 1, 0)

    shading_7 = (mat.shading_type == 7)

    polygons = [Std_Polygon() for _ in range(n_tris)]
    STM.polygon_num = n_tris
    STM.polygon     = polygons
    pt_list         = STM.point_list

    for tri_idx in range(n_tris):
        tri = tris[tri_idx]
        sp  = polygons[tri_idx]
        sp.model          = STM
        sp.material_index = 0
        sp.info_list_num  = 3

        tri_loops    = tri.loops
        tri_vertices = tri.vertices

        pi0 = Std_PointInfo()
        pi1 = Std_PointInfo()
        pi2 = Std_PointInfo()
        info = [pi0, pi1, pi2]
        sp.info_list = info

        for out_idx in range(3):
            in_idx   = order[out_idx]
            loop_idx = tri_loops[in_idx]
            vi       = tri_vertices[in_idx]
            pi       = info[out_idx]

            ln = loops_ref[loop_idx].normal
            lx, ly, lz = _transform_normal(ln.x, ln.y, ln.z)
            l2 = lx*lx + ly*ly + lz*lz
            if l2 > 1e-20:
                inv = l2 ** -0.5
                bnx = lx*inv; bny = ly*inv; bnz = lz*inv
            else:
                bnx = 0.0; bny = 0.0; bnz = 1.0

            rnx, rny, rnz = remap(bnx, bny, bnz)

            pi.poly        = sp
            pi.point_index = vi

            pi.nx._data = rnx
            pi.ny._data = rny
            pi.nz._data = rnz
            pi.nx0 = bnx; pi.ny0 = bny; pi.nz0 = bnz

            if uv_data is not None:
                uv = uv_data[loop_idx].uv
                u_val = _f32l(uv[0])
                v_val = _f32l(uv[1] - 1.0)
                pi.u._data = u_val
                pi.v._data = v_val

            # Vertex color
            if loop_colors is not None:
                col = loop_colors.get(loop_idx, (255, 255, 255, 255))
                pi.vtx_color_R = col[0]
                pi.vtx_color_G = col[1]
                pi.vtx_color_B = col[2]
                pi.vtx_color_A = col[3]

            u_bits = _unpack('<I', _pack('<f', pi.u._data))[0]
            v_bits = _unpack('<I', _pack('<f', pi.v._data))[0]
            if shading_7:
                pi._eq_key = (vi, u_bits, v_bits,
                              pi.vtx_color_A, pi.vtx_color_R,
                              pi.vtx_color_G, pi.vtx_color_B)
            else:
                pi._eq_key = (vi, u_bits, v_bits)

        tn = tri.normal
        tnx, tny, tnz = _transform_normal(tn.x, tn.y, tn.z)
        fnx, fny, fnz = remap(tnx, tny, tnz)
        sp.normal = Std_Point._make(fnx, fny, fnz)
        sp.gr = tri.use_smooth


def convert_collection(
        collection,
        opts,
) -> bytes:
    """Convert a Blender collection directly to a NAOMI .bin blob. Returns bytes."""
    global StdModel, StdModelCount, mcx, mcy, mcz, mcr
    global output_after_all, naomi2hg, bump_polygon, bump_polygon_dup, bump_polygon_trs, env_map_polygon
    import io

    def _reset_render_output() -> None:
        """Reset render_output module state between export runs."""
        global StdModel, StdModelCount, mcx, mcy, mcz, mcr
        global output_after_all, naomi2hg, bump_polygon
        global bump_polygon_dup, bump_polygon_trs, env_map_polygon
        set_binary_output(None)
        StdModel      = []
        StdModelCount = 0
        mcx = Std_Float(0.0)
        mcy = Std_Float(0.0)
        mcz = Std_Float(0.0)
        mcr = Std_Float(0.0)
        output_after_all = False
        naomi2hg         = False
        bump_polygon     = False
        bump_polygon_dup = False
        bump_polygon_trs = False
        env_map_polygon  = False

    bin_buf = io.BytesIO()

    try:
        reset_globals()
        _reset_render_output()

        apply_options(opts)
        set_binary_output(bin_buf)

        _fwd = getattr(opts, 'forward_axis', '+Y')
        _up  = getattr(opts, 'up_axis',      '+Z')
        _nx  = getattr(opts, 'neg_x',        False)
        blender_collection_to_std_models(
            collection, opts, _fwd, _up, _nx)

        if StdModelCount == 0:
            raise NlcvError("No mesh objects found in collection",
                            NLCV_ERR_CONVERT)

        try:
            mem_all_clear()
            get_model_culling_all(
                mcx, mcy, mcz, mcr)

            if merge1:
                chk_same_material1()
            elif merge0:
                chk_same_material0()

            get_model_culling()
            naomi_format_type_2_7(None, False)

        except SystemExit as exc:
            code = int(exc.code) if exc.code is not None else -1
            if code == -2:
                raise NlcvError(
                    f"touch_count overflow (increase touch_count_max)", NLCV_ERR_CONVERT)
            else:
                raise NlcvError(
                    f"Strip-building failed (exit {code})", NLCV_ERR_INTERNAL)
        except Exception as exc:
            raise NlcvError(
                f"Unexpected error in strip-building: {exc}",
                NLCV_ERR_INTERNAL) from exc

        result = bin_buf.getvalue()
        if not result:
            raise NlcvError("Conversion produced no output bytes.",
                            NLCV_ERR_OUTPUT)
        return result

    finally:
        reset_globals()
        _reset_render_output()
