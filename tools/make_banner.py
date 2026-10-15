#!/usr/bin/env python3
r"""Build the CIA's HOME Menu banner, banner sound and icon from retail data.

The banner is a CGFX model: the letters of `NFS_LOGO_ALPHA` (GLOBALB.BUN) are
cut out of the logo, extruded into a chrome badge that spins on the top
screen, in front of an oval of night lit by the logo's light bar. The
sound is one rising wail of the game's `CopSiren01` (SOUND/INGAME). The icon
is the logo over the same blue and red. Nothing here goes into the game's
romfs -- bannertool packs the CGFX and the WAV into banner.bnr and the icon
into the SMDH, and only the HOME Menu reads them.

The CGFX is written by hand. The struct layouts are the ones skyfloogle's
pycgfx writes (github.com/skyfloogle/pycgfx), which is the reference for what
the HOME Menu's NintendoWare runtime accepts; values the runtime fills in
itself are left zero, as pycgfx leaves them. Constraints from the same
source: the model and the animation are both named COMMON, RGBA8 textures do
not show (both textures here are RGBA5551, dithered), the whole CGFX must stay under
0x80000 bytes, and the camera sits at (0, 1, 44.786) with a 30 degree
vertical field of view, so the z = 0 plane shows 40 x 24 units.

    letters    mask = bright or (in the band) blue pixels below the siren
               glow, cleaned of specks and pin holes; upscaled smoothly into
               a 512x112 atlas region, so the GPU's filtered alpha test cuts
               the same outline the walls follow
    walls      marching squares on that alpha, Douglas-Peucker, one quad per
               edge from z = +T/2 to -T/2; normals from the blurred alpha's
               gradient, the shading baked into the UVs of a gradient strip
    caps       one alpha-tested quad per face: the chrome logo in front, a
               dark copy behind
    background an oval plate (a 96-sided fan) with a steel rim: gradient,
               the light bar's blue and red, speed streaks and the logo's
               glow with its letters inpainted, far enough back to clear
               the spin, on a YAxial billboard bone so it keeps facing the
               camera
    spin       none authored: the HOME Menu turns every banner model about
               Y by itself (about once in 10 s on a 3DS)

What a 3DS showed of the first version (Session 110), and what changed for
it: every texture upside down (stored bottom row first; the HOME Menu wants
the top row first), the background turning with the badge (now the
billboard), nothing outside a screen-sized oval (the plate stays inside
it), and the default chime instead of the siren (the WAV was mono).

Writes banner.cgfx, banner.wav and icon.png into --out, by default
"3DS Files/meta/hp2", where the Makefile looks for them; tools/build_cia.ps1
runs this first. Being retail-derived, they are ignored by git.

Usage:
    python tools/make_banner.py [--retail extracted-retail] [--out "3DS Files/meta/hp2"]
"""
import argparse
import math
import struct
import sys
import wave
import zlib
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio_convert  # noqa: E402
import texture_convert  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

CAMERA_Z = 44.786        # HOME Menu banner camera: (0, 1, 44.786), yfov 30
CAMERA_Y = 1.0
CGFX_LIMIT = 0x80000

# --------------------------------------------------------------------------
# CGFX writer
#
# A Node is one struct in the DATA block, a list of (kind, value) fields:
#   i I f h H b B ?   scalars          x       n bytes of padding
#   vec               floats           sig     4-byte signature
#   str               string pointer   ptr     pointer to a Node laid out here
#   ref               pointer to a Node owned somewhere else
#   list / ilist      (count, pointer to a table of Node pointers / of ints)
#   dict              (count, pointer to a DICT of (name, Node))
#   blob              (size, pointer into IMAG)
# Every pointer is self-relative. Nodes are laid out as the template banner
# has them: a node's owned children together in field order, then each
# child's own children the same way; the strings after the last node, then
# the IMAG block with the vertex, index and texel data.


class Blob:
    def __init__(self, data, align=16):
        self.data = bytes(data)
        self.align = align


class Node:
    def __init__(self, fields, tag=""):
        self.tag = tag
        self.off = None
        self.fields = []
        for kind, val in fields:
            if kind == "list":
                val = (len(val), Node([("ptr", n) for n in val], tag + "[]") if val else None)
            elif kind == "ilist":
                val = (len(val), Node([("i", v) for v in val], tag + "[]") if val else None)
            elif kind == "dict":
                val = (len(val), make_dict(val) if val else None)
            self.fields.append((kind, val))
        self.size = sum(field_size(k, v) for k, v in self.fields)
        assert self.size % 4 == 0, (tag, self.size)


FIXED = {"i": 4, "I": 4, "f": 4, "h": 2, "H": 2, "b": 1, "B": 1, "?": 1,
         "sig": 4, "str": 4, "ptr": 4, "ref": 4,
         "list": 8, "ilist": 8, "dict": 8, "blob": 8}


def field_size(kind, val):
    if kind == "x":
        return val
    if kind == "vec":
        return 4 * len(val)
    return FIXED[kind]


def owned(kind, val):
    if kind == "ptr":
        return val
    if kind in ("list", "ilist", "dict"):
        return val[1]
    return None


# The DICT is a Patricia tree over the names, as NintendoWare builds it; this
# is pycgfx's translation of Gericom's PatriciaTreeGenerator.

class _PNode:
    pass


def _bit(name, bit):
    return (ord(name[bit // 8]) >> (bit & 7)) & 1


def _lookup(root, length, name, minbit=-1):
    name = name.ljust(length, "\0")
    cur = root
    left = cur.left
    while cur.refbit > left.refbit and left.refbit > minbit:
        cur = left
        left = cur.right if _bit(name, cur.refbit) else cur.left
    return left, cur


def patricia(names):
    """Return (refbit, left, right) for the root entry and for each name."""
    length = max(len(n) for n in names)
    root = _PNode()
    root.refbit, root.left, root.right, root.idx = length * 8 - 1, root, root, 0
    root.name = "\0" * length
    for idx, name in sorted(enumerate(names), key=lambda k: -len(k[1])):
        name = name.ljust(length, "\0")
        node = _PNode()
        node.name, node.idx = name, idx
        left = _lookup(root, length, name)[0]
        bit = length * 8 - 1
        while _bit(left.name, bit) == _bit(name, bit):
            bit -= 1
        left, cur = _lookup(root, length, name, bit)
        node.refbit = bit
        node.left = left if _bit(name, bit) else node
        node.right = node if _bit(name, bit) else left
        if _bit(name, cur.refbit):
            cur.right = node
        else:
            cur.left = node
    root.idx = -1
    out = []
    for i, name in enumerate([""] + list(names)):
        p = _lookup(root, length, name)[0]
        assert p.name == name.ljust(length, "\0"), name
        out.append((-1 if i == 0 else p.refbit, p.left.idx + 1, p.right.idx + 1))
    return out


def make_dict(entries):
    names = [n for n, _ in entries]
    assert len(set(names)) == len(names), names
    tree = patricia(names)
    fields = [("sig", b"DICT"), ("i", 12 + 16 * (len(entries) + 1)), ("i", len(entries))]
    rb, lf, rt = tree[0]
    fields += [("i", rb), ("h", lf), ("h", rt), ("str", None), ("ptr", None)]
    for (name, node), (rb, lf, rt) in zip(entries, tree[1:]):
        fields += [("i", rb), ("h", lf), ("h", rt), ("str", name), ("ptr", node)]
    return Node(fields, "DICT")


def write_cgfx(data_node):
    order = []

    def layout(node, pos):              # a node's children together, then theirs
        kids = [owned(k, v) for k, v in node.fields if owned(k, v) is not None]
        for child in kids:
            child.off = pos
            order.append(child)
            pos += child.size
        for child in kids:
            pos = layout(child, pos)
        return pos

    data_node.off = 0x14
    order.append(data_node)
    end = layout(data_node, 0x14 + data_node.size)

    strings, blobs = {}, []
    pool = bytearray()
    for node in order:
        for kind, val in node.fields:
            if kind == "str" and val is not None and val not in strings:
                strings[val] = end + len(pool)
                pool += val.encode("ascii") + b"\0"
            elif kind == "blob" and val is not None:
                blobs.append(val)
    str_end = end + len(pool)
    imag = (str_end + 8 + 127) // 128 * 128 - 8       # IMAG data 128-aligned
    blob_at = {}
    pos = imag + 8
    for b in blobs:
        pos = (pos + b.align - 1) // b.align * b.align
        blob_at[id(b)] = pos
        pos += len(b.data)
    total = (pos + 15) // 16 * 16

    kind0, _ = data_node.fields[1]
    data_node.fields[1] = (kind0, imag - 0x14)        # DATA section size

    buf = bytearray(total)
    struct.pack_into("<4sHHIII", buf, 0, b"CGFX", 0xFEFF, 0x14, 0x5000000, total, 2)

    def rel(p, target):
        struct.pack_into("<i", buf, p, 0 if target is None else target - p)

    for node in order:
        p = node.off
        for kind, val in node.fields:
            if kind in ("i", "I", "f", "h", "H", "b", "B", "?"):
                struct.pack_into("<" + kind, buf, p, val)
            elif kind == "vec":
                struct.pack_into("<%df" % len(val), buf, p, *val)
            elif kind == "sig":
                buf[p:p + 4] = val
            elif kind == "str":
                rel(p, None if val is None else strings[val])
            elif kind in ("ptr", "ref"):
                rel(p, None if val is None else val.off)
            elif kind in ("list", "ilist", "dict"):
                struct.pack_into("<i", buf, p, val[0])
                rel(p + 4, None if val[1] is None else val[1].off)
            elif kind == "blob":
                if val is not None:
                    struct.pack_into("<i", buf, p, len(val.data))
                    rel(p + 4, blob_at[id(val)])
            p += field_size(kind, val)
        assert p == node.off + node.size
    buf[end:str_end] = pool
    struct.pack_into("<4sI", buf, imag, b"IMAG", total - imag)
    for b in blobs:
        o = blob_at[id(b)]
        buf[o:o + len(b.data)] = b.data
    return bytes(buf)


# --------------------------------------------------------------------------
# CGFX objects


IDENTITY34 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]

TEX_RGBA5551, TEX_RGBA4 = 2, 4
GL_FORMAT = {TEX_RGBA5551: (0x6752, 0x8034), TEX_RGBA4: (0x6752, 0x8033)}

# bone flags
B_IDENTITY, B_T0, B_R0, B_S1, B_UNIFORM = 1, 2, 4, 8, 16
B_RENDER, B_LOCAL, B_WORLD = 64, 128, 256


def morton8():
    m = np.zeros(64, int)
    for y in range(8):
        for x in range(8):
            v = 0
            for b in range(3):
                v |= ((x >> b) & 1) << (2 * b) | ((y >> b) & 1) << (2 * b + 1)
            m[y * 8 + x] = v
    return m


BAYER4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]])


def dither(rgba, bits):
    """Ordered dither of the colour channels ahead of truncation to `bits`."""
    h, w = rgba.shape[:2]
    step = 256 >> bits
    off = (np.tile(BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w] + 0.5) / 16 * step
    out = rgba.astype(np.float64)
    out[..., :3] += off[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)


def swizzle(rgba, fmt):
    """RGBA uint8 (h, w, 4), top row first -> PICA tiled texels, top first.

    The HOME Menu samples the first stored row at t = 1, so the image is
    stored as it is and the UVs run from v = 0 at its bottom to 1 at its
    top. That is how bannertool's own banner.cgfx stores its picture; a
    3DS show of the banner with the rows flipped had every picture upside
    down."""
    rgba = dither(rgba, 5 if fmt == TEX_RGBA5551 else 4)
    img = rgba.astype(np.uint32)
    h, w = img.shape[:2]
    r, g, b, a = img[..., 0], img[..., 1], img[..., 2], img[..., 3]
    if fmt == TEX_RGBA5551:
        px = (a >> 7) | ((b & 0xF8) >> 2) | ((g & 0xF8) << 3) | ((r & 0xF8) << 8)
    else:
        px = (a >> 4) | (b & 0xF0) | ((g >> 4) << 8) | ((r & 0xF0) << 8)
    tiles = px.reshape(h // 8, 8, w // 8, 8).transpose(0, 2, 1, 3).reshape(-1, 64)
    out = np.zeros_like(tiles)
    out[:, morton8()] = tiles
    return out.astype("<u2").tobytes()


def image_texture(name, rgba, fmt):
    h, w = rgba.shape[:2]
    image = Node([("i", h), ("i", w), ("blob", Blob(swizzle(rgba, fmt), 128)),
                  ("i", 0), ("i", 16), ("i", 0), ("i", 0)], "IMAGE")
    glf, glt = GL_FORMAT[fmt]
    return Node([("I", 0x20000011), ("sig", b"TXOB"), ("i", 0x5000000), ("str", name),
                 ("dict", []), ("i", h), ("i", w), ("i", glf), ("i", glt), ("i", 1),
                 ("x", 4), ("i", 0), ("i", fmt), ("ptr", image)], "TXOB")


def color_bytes(c):
    return [("B", min(255, int(round(v * 255)))) for v in c]


def material(name, txob, cutout, translucent=False):
    """A one-texture unlit material: TEV stage 0 replaces with texture 0.
    `cutout` alpha-tests at 128; `translucent` blends instead of writing depth."""
    cmds = [0, 0x1008E, 0xFF000000, 0x809F0081, 0, 0x2206] + [0] * 8
    texinfo = Node([], "TEXI")
    reftex = Node([("I", 0x20000004), ("sig", b"TXOB"), ("i", 0x5000000), ("str", ""),
                   ("dict", []), ("str", txob_name(txob)), ("ref", txob)], "REFTEX")
    sampler = Node([("I", 0x80000000), ("ref", texinfo), ("i", 1),
                    ("vec", [0, 0, 0, 1])], "SAMPLER")
    texinfo.__init__([("I", 0x80000000), ("i", 0), ("ptr", reftex), ("ptr", sampler)]
                     + [("I", c) for c in cmds] + [("i", 0x38)], "TEXI")

    shader = Node([("I", 0x80000001), ("sig", b"SHDR"), ("i", 0x5000000), ("str", ""),
                   ("dict", []), ("str", "DefaultShader"), ("x", 4)], "SHDR")
    light_table = Node([("i", 0)] * 6, "LIGHTTABLE")
    tev = []
    for i in range(6):
        src = 0xFF3 if i == 0 else 0xFFF          # stage 0: texture 0; then pass
        tev += [("i", 0), ("h", src), ("h", src),
                ("I", 0x804F0000 | ((0xC0 if i < 4 else 0xD0) + i * 8)),
                ("i", 0), ("h", 0), ("h", 0), ("x", 4), ("h", 0), ("h", 0)]
    alpha_test = (1 | 7 << 4 | 128 << 8) if cutout else 0x10      # GEQUAL 128 / off
    fshader = Node([("vec", [0, 0, 0, 0])] + [("i", 0)] * 6 + [("ptr", light_table)] + tev
                   + [("I", alpha_test), ("I", 0xF0104),
                      ("I", 0xFF000000), ("I", 0xF00FD), ("I", 0), ("I", 0x200E0),
                      ("I", 0x400), ("I", 0x201C3)], "FSHADER")

    colors = [(0, 0, 0, 0), (0, 0, 0, 1), (1, 1, 1, 1), (1, 1, 1, 0), (0, 0, 0, 0)] \
        + [(0, 0, 0, 0)] * 6
    if translucent:     # SrcAlpha, InvSrcAlpha for colour and alpha
        blend = 0 | 0 << 8 | 6 << 16 | 7 << 20 | 6 << 24 | 7 << 28
    else:               # One, Zero
        blend = 0 | 0 << 8 | 1 << 16 | 0 << 20 | 1 << 24 | 0 << 28
    coord = [("i", 0)] * 4 + [("f", 1.0), ("f", 1.0), ("f", 0.0), ("f", 0.0), ("f", 0.0),
                              ("?", False), ("x", 3), ("vec", IDENTITY34)]
    sampler_hash = zlib.crc32(name.encode() + struct.pack("<14I", *cmds))
    fields = [("I", 0x8000000), ("sig", b"MTOB"), ("i", 0x6000000), ("str", name),
              ("dict", []), ("i", 0), ("i", 0), ("i", 1 if translucent else 0)]
    fields += [("vec", list(c)) for c in colors]
    for c in colors:
        fields += color_bytes(c)
    fields += [("i", 0)]                                       # command cache
    fields += [("i", 0), ("i", 0), ("f", 0.0), ("I", 0), ("I", 0x10040)]   # no culling
    fields += [("i", 1 if translucent else 3),                 # depth test (+ write)
               ("I", 0x41), ("I", 0x10107), ("I", 0x3000000), ("I", 0x80126)]
    fields += [("i", 1), ("vec", [0, 0, 0, 1]), ("I", 0xE40100), ("I", 0x803F0100),
               ("I", blend), ("I", 0), ("I", 0xFF000000), ("I", 0)]
    fields += [("I", 0), ("I", 0xD0105), ("I", 0), ("I", 0xF0106)]          # stencil
    fields += [("i", 1)] + coord * 3
    fields += [("ptr", texinfo), ("ptr", None), ("ptr", None), ("ptr", None),
               ("ptr", shader), ("ptr", fshader)] + [("i", 0)] * 5
    # The runtime compares these to skip resending state between materials,
    # so every one is set and differs per material.
    hashes = [zlib.crc32(b"%s/%d" % (name.encode(), i)) or 1 for i in range(13)]
    hashes[3] = sampler_hash
    fields += [("I", h) for h in hashes] + [("x", 4)]
    return Node(fields, "MTOB")


_TXOB_NAMES = {}


def txob_name(txob):
    return _TXOB_NAMES[id(txob)]


def material_members(name):
    """The MaterialAnimation group's bindable members for one material."""
    out = []

    def member(path, typ, blend, off, size, unk, ft, vidx, fidx):
        out.append((path, Node([("I", typ), ("str", path), ("str", name), ("str", blend),
                                ("i", off), ("i", size), ("i", unk), ("i", ft), ("i", vidx),
                                ("x", 4), ("str", name), ("i", fidx)], "MEMBER")))

    m = 'Materials["%s"].' % name
    for i, c in enumerate(["Emission", "Ambient", "Diffuse", "Specular0", "Specular1",
                           "Constant0", "Constant1", "Constant2", "Constant3",
                           "Constant4", "Constant5"]):
        member(m + "MaterialColor." + c, 0x8000000, "MaterialColor", 16 * i, 16, 0, 1, i, 1)
    member(m + "TextureMappers[0].Texture", 0x20000000, "TextureMappers[0]", 8, 4, 1, 3, 0, 0)
    member(m + "FragmentOperation.BlendOperation.BlendColor", 0x4000000,
           "FragmentOperation.BlendOperation", 4, 16, 0, 4, 0, 4)
    for vidx, (what, off, size, unk) in enumerate([("Scale", 16, 8, 2), ("Rotate", 24, 4, 3),
                                                   ("Translate", 28, 8, 2)]):
        member(m + "TextureCoordinators[0]." + what, 0x80000000, "TextureCoordinators[0]",
               off, size, unk, 5, vidx, 0)
    return out


def shape(name, verts, indices, bone):
    """Positions (n, 3) and UVs (n, 2) interleaved, ushort triangle list."""
    v = np.concatenate([verts[0], verts[1]], 1).astype("<f4")
    lo, hi = verts[0].min(0), verts[0].max(0)
    obb = Node([("I", 0x80000000), ("vec", list((lo + hi) / 2)),
                ("vec", [1, 0, 0, 0, 1, 0, 0, 0, 1]), ("vec", list(hi - lo))], "OBB")
    pos = Node([("I", 0x40000001), ("i", 0), ("i", 0), ("i", 0), ("i", 0), ("blob", None),
                ("i", 0), ("i", 0), ("i", 0x1406), ("i", 3), ("f", 1.0), ("i", 0)], "VS")
    uv = Node([("I", 0x40000001), ("i", 4), ("i", 0), ("i", 0), ("i", 0), ("blob", None),
               ("i", 0), ("i", 0), ("i", 0x1406), ("i", 2), ("f", 1.0), ("i", 12)], "VS")
    ivs = Node([("I", 0x40000002), ("i", 21), ("i", 2), ("x", 4), ("i", 0),
                ("blob", Blob(v.tobytes(), 16)), ("i", 0), ("i", 0), ("i", 20),
                ("list", [pos, uv])], "IVS")
    idx = Node([("i", 0x1403), ("b", 0), ("?", True), ("x", 2),
                ("blob", Blob(np.asarray(indices, "<u2").tobytes(), 16))] + [("i", 0)] * 7,
               "INDEX")
    prim = Node([("list", [idx]), ("ilist", [0]), ("i", 0), ("i", 0)], "PRIM")
    pset = Node([("ilist", [bone]), ("i", 0), ("list", [prim])], "PSET")
    return Node([("I", 0x10000001), ("sig", b"SOBJ"), ("i", 0), ("str", name), ("dict", []),
                 ("i", 0), ("ptr", obb), ("vec", [0, 0, 0]), ("list", [pset]), ("i", 0),
                 ("list", [ivs]), ("i", 0)], "SHAPE")


def bone_node(name, flags, joint, parent):
    return Node([("str", name), ("I", flags), ("i", joint), ("i", parent)], "BONE")


BILLBOARD_OFF, BILLBOARD_Y = 0, 5          # 5: YAxial, turned about Y to face the camera


def finish_bone(node, parent, child, prev, nxt, billboard):
    node.__init__(node.fields + [("ref", parent), ("ref", child), ("ref", prev), ("ref", nxt),
                                 ("vec", [1, 1, 1]), ("vec", [0, 0, 0]), ("vec", [0, 0, 0]),
                                 ("vec", IDENTITY34), ("vec", IDENTITY34),
                                 ("vec", IDENTITY34), ("i", billboard), ("x", 8)], "BONE")


def build_cgfx(scene):
    textures = []
    for name, rgba, fmt in scene["textures"]:
        tx = image_texture(name, rgba, fmt)
        _TXOB_NAMES[id(tx)] = name
        textures.append((name, tx))
    tex = dict(textures)

    cmdl = Node([], "CMDL")
    mats, meshes, shapes = [], [], []
    for i, m in enumerate(scene["meshes"]):
        mats.append((m["material"], material(m["material"], tex[m["texture"]], m["cutout"])))
        shapes.append(shape(m["name"], (m["pos"], m["uv"]), m["indices"], m["bone"]))
        bone_name = scene["bones"][m["bone"]][0]          # the mesh node it hangs from
        meshes.append(Node([("I", 0x1000000), ("sig", b"SOBJ"), ("i", 0), ("str", m["name"]),
                            ("dict", []), ("i", i), ("i", i), ("ref", cmdl), ("?", True),
                            ("B", 0), ("H", 65535), ("x", 72), ("str", bone_name)], "MESH"))

    bones = [bone_node(n, f, j, p) for j, (n, f, p, _) in enumerate(scene["bones"])]
    bb = [b for _, _, _, b in scene["bones"]]
    root = bones[0]
    kids = bones[1:]
    finish_bone(root, None, kids[0], None, None, bb[0])
    for k, b in enumerate(kids):
        finish_bone(b, root, None, kids[k - 1] if k else None,
                    kids[k + 1] if k + 1 < len(kids) else None, bb[k + 1])
    skeleton = Node([("I", 0x2000000), ("sig", b"SOBJ"), ("i", 0), ("str", ""), ("dict", []),
                     ("dict", [(n, b) for (n, _, _, _), b in zip(scene["bones"], bones)]),
                     ("ref", root), ("i", 0), ("i", 2)], "SKELETON")   # flags as the template's

    def group(name, flags, mtype, members, blendops, timing):
        return (name, Node([("I", 0x80000000), ("i", flags), ("str", name), ("i", mtype),
                            ("dict", members), ("ilist", blendops), ("i", timing)], "ANIMGROUP"))

    skel_members = [(n, Node([("I", 0x40000000), ("str", n), ("str", n), ("str", None),
                              ("i", 0), ("i", 0), ("i", 0), ("i", 0), ("i", 0), ("x", 4),
                              ("str", n), ("i", 0)], "MEMBER")) for n, _, _, _ in scene["bones"]]
    vis_members = [("IsVisible", Node([("I", 0x10000000), ("str", "IsVisible"), ("str", None),
                                       ("str", None), ("i", 212), ("i", 1), ("i", 0), ("i", 6),
                                       ("i", 1), ("x", 4), ("i", 0)], "MEMBER"))]
    for i in range(len(meshes)):
        p = "Meshes[%d].IsVisible" % i
        vis_members.append((p, Node([("I", 0x1000000), ("str", p), ("str", str(i)),
                                     ("str", None), ("i", 36), ("i", 1), ("i", 0), ("i", 7),
                                     ("i", 0), ("x", 4), ("i", i)], "MEMBER")))
    mat_members = [mm for name, _ in mats for mm in material_members(name)]
    groups = [group("SkeletalAnimation", 1, 1, skel_members, [8], 1),
              group("VisibilityAnimation", 0, 3, vis_members, [0], 0),
              group("MaterialAnimation", 0, 2, mat_members, [3, 7, 5, 2], 1)]

    cmdl.__init__([("I", 0x40000012 | 0x80), ("sig", b"CMDL"), ("i", 0x7000000),
                   ("str", "COMMON"), ("dict", []), ("i", 1), ("i", 1), ("i", 0), ("x", 4),
                   ("dict", groups), ("vec", [1, 1, 1]), ("vec", [0, 0, 0]), ("vec", [0, 0, 0]),
                   ("vec", IDENTITY34), ("vec", IDENTITY34),
                   ("list", meshes), ("dict", mats), ("list", shapes), ("dict", []),
                   ("i", 1), ("i", 0), ("i", 0), ("ptr", skeleton)], "CMDL")

    # No animation: the HOME Menu turns every banner model about Y on its own
    # (seen on a 3DS), which spins the badge, and the background bone's
    # billboard keeps the background facing the camera through it.
    dicts = [[("COMMON", cmdl)], textures] + [[]] * 13
    data = Node([("sig", b"DATA"), ("i", 0)] + [("dict", d) for d in dicts], "DATA")
    return write_cgfx(data)


# --------------------------------------------------------------------------
# Image helpers (numpy only)


def gauss_blur(img, sigma):
    r = max(1, int(sigma * 3))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    out = img.astype(np.float64)
    for axis in (0, 1):
        pad = [(0, 0)] * out.ndim
        pad[axis] = (r, r)
        p = np.pad(out, pad, mode="edge")
        acc = np.zeros_like(out)
        for i, w in enumerate(k):
            sl = [slice(None)] * out.ndim
            sl[axis] = slice(i, i + out.shape[axis])
            acc += w * p[tuple(sl)]
        out = acc
    return out


def resize(img, w, h, filt=Image.BICUBIC):
    """Resize a float (H, W) or (H, W, C) array."""
    if img.ndim == 2:
        return np.asarray(Image.fromarray(img.astype(np.float32), "F").resize((w, h), filt),
                          np.float64)
    return np.stack([resize(img[..., c], w, h, filt) for c in range(img.shape[2])], -1)


def components(mask):
    h, w = mask.shape
    lab = np.zeros((h, w), int)
    comps = []
    for y, x in zip(*np.nonzero(mask)):
        if lab[y, x]:
            continue
        n = len(comps) + 1
        lab[y, x] = n
        q, pts = deque([(y, x)]), []
        while q:
            cy, cx = q.popleft()
            pts.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not lab[ny, nx]:
                    lab[ny, nx] = n
                    q.append((ny, nx))
        comps.append(np.array(pts))
    return comps


def grow_colors(rgb, inside, steps):
    """Spread the colours of `inside` pixels outwards, `steps` pixels far."""
    rgb = rgb.astype(np.float64).copy()
    have = inside.copy()
    for _ in range(steps):
        acc = np.zeros_like(rgb)
        cnt = np.zeros(have.shape)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            acc += np.roll(rgb * have[..., None], (dy, dx), (0, 1))
            cnt += np.roll(have, (dy, dx), (0, 1))
        new = ~have & (cnt > 0)
        rgb[new] = acc[new] / cnt[new][:, None]
        have |= new
    return rgb


def inpaint(rgba, hole, iters=400):
    """Fill `hole` by diffusing premultiplied RGBA in from its border."""
    pm = rgba.astype(np.float64).copy()
    pm[..., :3] *= pm[..., 3:4] / 255.0
    pm[hole] = 0
    for _ in range(iters):
        avg = (np.roll(pm, 1, 0) + np.roll(pm, -1, 0) + np.roll(pm, 1, 1) + np.roll(pm, -1, 1)) / 4
        pm[hole] = avg[hole]
    a = pm[..., 3:4]
    out = pm.copy()
    out[..., :3] = np.where(a > 1e-3, pm[..., :3] * 255.0 / np.maximum(a, 1e-3), 0)
    return np.clip(out, 0, 255)


# --------------------------------------------------------------------------
# Logo -> geometry


def load_logo(retail):
    path = Path(retail) / "GLOBAL" / "GLOBALB.BUN"
    buf = path.read_bytes()
    for off, size in texture_convert.find_packs(buf):
        _, info, data = texture_convert.parse_pack(buf, off, size)
        for t in texture_convert.textures(info):
            if t["name"] == "NFS_LOGO_ALPHA":
                w, h, rgba = texture_convert.decode(t, data, "auto")
                return np.frombuffer(rgba, np.uint8).reshape(h, w, 4).copy()
    raise SystemExit("NFS_LOGO_ALPHA not found in %s" % path)


def letter_mask(logo):
    """The chrome letters and the blue HOT PURSUIT 2 band, without the glow."""
    r, g, b, a = (logo[..., i].astype(int) for i in range(4))
    lum = (r * 299 + g * 587 + b * 114) // 1000
    rows = np.arange(logo.shape[0])[:, None]
    m = (a >= 200) & (rows >= 29) & ((lum >= 75) | ((rows >= 55) & (b >= 65) & (b >= r + 25)))
    m &= ~(r > b + 30)                       # the orange flare between the words
    for pts in components(m):
        if len(pts) < 25:
            m[pts[:, 0], pts[:, 1]] = False
    h, w = m.shape
    for pts in components(~m):
        edge = (pts[:, 0] == 0).any() or (pts[:, 0] == h - 1).any() or \
            (pts[:, 1] == 0).any() or (pts[:, 1] == w - 1).any()
        if not edge and len(pts) < 15:
            m[pts[:, 0], pts[:, 1]] = True
    return m


def march(field):
    """Closed iso-0.5 loops of a sampled field, in (x, y) sample coordinates.

    Every loop runs with the inside on the side of (-dy, dx), x right and y
    down, so outer outlines and holes both come out oriented."""
    h, w = field.shape
    f = np.pad(field, 1)                    # zero border closes every loop
    ins = f >= 0.5
    pts, nxt = {}, {}

    def edge_point(ya, xa, yb, xb):
        key = (min(ya, yb), min(xa, xb), ya != yb)
        if key not in pts:
            va, vb = f[ya, xa], f[yb, xb]
            t = (0.5 - va) / (vb - va)
            pts[key] = (xa + (xb - xa) * t - 1, ya + (yb - ya) * t - 1)
        return key

    def link(p, q, inside):
        """Segment p-q, directed so the mean of the `inside` corners is on its left."""
        cy = sum(c[0] for c in inside) / len(inside) - 1
        cx = sum(c[1] for c in inside) / len(inside) - 1
        (px, py), (qx, qy) = pts[p], pts[q]
        if (qx - px) * (cy - py) - (qy - py) * (cx - px) < 0:
            p, q = q, p
        assert p not in nxt
        nxt[p] = q

    for y in range(h + 1):
        for x in range(w + 1):
            corner = ((y, x), (y, x + 1), (y + 1, x + 1), (y + 1, x))
            c = [ins[k] for k in corner]
            if sum(c) in (0, 4):
                continue
            e = {}                           # crossed edges: top right bottom left
            if c[0] != c[1]:
                e["t"] = edge_point(y, x, y, x + 1)
            if c[1] != c[2]:
                e["r"] = edge_point(y, x + 1, y + 1, x + 1)
            if c[3] != c[2]:
                e["b"] = edge_point(y + 1, x, y + 1, x + 1)
            if c[0] != c[3]:
                e["l"] = edge_point(y, x, y + 1, x)
            if len(e) == 2:
                a, b = e.values()
                link(a, b, [k for k, i in zip(corner, c) if i])
            elif c[0]:                       # saddle: keep the inside corners apart
                link(e["t"], e["l"], [corner[0]])
                link(e["r"], e["b"], [corner[2]])
            else:
                link(e["t"], e["r"], [corner[1]])
                link(e["b"], e["l"], [corner[3]])
    loops, seen = [], set()
    for start in nxt:
        if start in seen:
            continue
        loop, cur = [], start
        while cur not in seen:
            seen.add(cur)
            loop.append(pts[cur])
            cur = nxt[cur]
        assert cur == start
        loops.append(np.array(loop))
    return loops


def simplify(loop, tol):
    """Douglas-Peucker on a closed polyline."""
    def dp(p):
        if len(p) < 3:
            return [0, len(p) - 1]
        a, b = p[0], p[-1]
        d = b - a
        n = math.hypot(*d)
        if n < 1e-9:
            dist = np.hypot(*(p - a).T)
        else:
            dist = np.abs(d[0] * (p[:, 1] - a[1]) - d[1] * (p[:, 0] - a[0])) / n
        i = int(np.argmax(dist))
        if dist[i] <= tol:
            return [0, len(p) - 1]
        left = dp(p[:i + 1])
        right = dp(p[i:])
        return left[:-1] + [i + k for k in right]
    far = int(np.argmax(np.hypot(*(loop - loop[0]).T)))
    first = dp(np.concatenate([loop[:far + 1]]))
    second = dp(np.concatenate([loop[far:], loop[:1]]))
    keep = first[:-1] + [far + k for k in second[:-1]]
    return loop[keep]


def sample(field, x, y):
    """Bilinear sample of a field at sample coordinates (x, y)."""
    h, w = field.shape
    x0, y0 = int(math.floor(x)), int(math.floor(y))
    fx, fy = x - x0, y - y0
    def at(yy, xx):
        return field[yy, xx] if 0 <= yy < h and 0 <= xx < w else 0.0
    return (at(y0, x0) * (1 - fx) * (1 - fy) + at(y0, x0 + 1) * fx * (1 - fy)
            + at(y0 + 1, x0) * (1 - fx) * fy + at(y0 + 1, x0 + 1) * fx * fy)


# --------------------------------------------------------------------------
# The scene

ATLAS_W, ATLAS_H = 512, 256
CAP_H = 112                  # front cap rows 0..111, back cap 112..223
STRIP_Y = 224                # wall gradient strip rows 224..255
BACK_W, BACK_H = 256, 128

LETTER_WIDTH = 26.0          # world units across the letters (~260 px on screen)
THICK = 1.0                  # badge depth
LETTER_Y = CAMERA_Y          # world y of the letters' centre: mid-screen
BACK_Z = -16.0               # behind the circle the turning letters sweep
# The background is an oval plate with a steel rim. On a 3DS the HOME Menu
# showed nothing of the banner outside an oval about 93% x 81% of the top
# screen, so the plate stays well inside that: half-axes in z = 0 units (the
# screen is 40 x 24), centred mid-screen.
OVAL_A, OVAL_B = 16.0, 7.4   # 80% x 62% of the screen
OVAL_RIM = 0.45              # the steel rim's width
OVAL_SIDES = 96
LIGHT = np.array([-0.4, 0.7, 0.6]) / np.linalg.norm([-0.4, 0.7, 0.6])


def steel(u, t):
    """The wall strip: u = lit fraction, t = depth from the front face (0..1)."""
    dark = np.array([22, 28, 44.0])
    mid = np.array([96, 112, 140.0])
    hi = np.array([236, 242, 252.0])
    u = np.clip(u, 0, 1)[..., None]
    c = np.where(u < 0.5, dark + (mid - dark) * (u / 0.5), mid + (hi - mid) * ((u - 0.5) / 0.5))
    c = c * (1.0 - 0.35 * np.asarray(t)[..., None])
    return c


def build_scene(logo):
    mask = letter_mask(logo)
    ys, xs = np.nonzero(mask)
    bx0, bx1, by0, by1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    bw, bh = bx1 - bx0, by1 - by0
    sc = min((ATLAS_W - 10) / bw, (CAP_H - 8) / bh)        # source px -> atlas texels
    big_w, big_h = int(round(logo.shape[1] * sc)), int(round(logo.shape[0] * sc))
    scx, scy = big_w / logo.shape[1], big_h / logo.shape[0]
    ox = int(round((ATLAS_W - bw * scx) / 2 - bx0 * scx))  # texel ax = ox + u * scx
    oy = int(round((CAP_H - bh * scy) / 2 - by0 * scy))
    k = LETTER_WIDTH / bw                                 # world units per source px
    ucx, ucy = (bx0 + bx1) / 2, (by0 + by1) / 2

    def src_to_world(u, v):
        return (u - ucx) * k, (ucy - v) * k + LETTER_Y

    def region_to_world(ax, ay):                          # front-region texel coords
        return src_to_world((ax - ox) / scx, (ay - oy) / scy)

    # cap texture: colours grown past the edge, alpha from the smoothed mask
    rgb = grow_colors(logo[..., :3], mask, 6)
    big = resize(rgb, big_w, big_h, Image.LANCZOS)
    soft = resize(gauss_blur(mask.astype(float), 0.6), big_w, big_h)
    region_rgb = np.zeros((CAP_H, ATLAS_W, 3))
    region_a = np.zeros((CAP_H, ATLAS_W))
    for ry in range(CAP_H):
        by = ry - oy
        if 0 <= by < big_h:
            lo, hi = max(0, ox), min(ATLAS_W, ox + big_w)
            region_rgb[ry, lo:hi] = big[by, lo - ox:hi - ox]
            region_a[ry, lo:hi] = soft[by, lo - ox:hi - ox]
    alpha = (region_a >= 0.5).astype(float)
    alpha[[0, -1], :] = 0
    alpha[:, [0, -1]] = 0
    region_rgb = grow_colors(np.clip(region_rgb, 0, 255), alpha > 0, 3)

    atlas = np.zeros((ATLAS_H, ATLAS_W, 4))
    atlas[:CAP_H, :, :3] = region_rgb
    atlas[:CAP_H, :, 3] = alpha * 255
    lum = region_rgb @ [0.3, 0.59, 0.11]
    back = np.stack([lum * 0.22 + 14, lum * 0.24 + 18, lum * 0.28 + 30], -1)
    atlas[CAP_H:2 * CAP_H, :, :3] = back
    atlas[CAP_H:2 * CAP_H, :, 3] = alpha * 255
    su, st = np.meshgrid((np.arange(ATLAS_W) + 0.5) / ATLAS_W,
                         (np.arange(ATLAS_H - STRIP_Y) + 0.5) / (ATLAS_H - STRIP_Y))
    atlas[STRIP_Y:, :, :3] = steel(su, st)
    atlas[STRIP_Y:, :, 3] = 255
    atlas = np.clip(np.round(atlas), 0, 255).astype(np.uint8)

    def uv(ax, ay):                                       # absolute atlas texel coords
        return ax / ATLAS_W, 1.0 - ay / ATLAS_H

    # walls: one quad per outline edge, the loop's points shared between
    # neighbouring quads; normals from the gradient of the blurred alpha, so
    # the baked shading runs smoothly round each letter
    loops = march(alpha)
    blurred = gauss_blur(alpha, 1.5)
    grad_y, grad_x = np.gradient(blurred)
    pos, uvs, idx = [], [], []
    strip_v = (uv(0, STRIP_Y + 1.5)[1], uv(0, ATLAS_H - 1.5)[1])
    nsegs = bad_normals = 0
    light = LIGHT[:2] / np.hypot(*LIGHT[:2])
    for loop in loops:
        loop = simplify(loop + 0.5, 0.35)                # sample (i, j) sits at i + 0.5
        if len(loop) < 3:
            continue
        n = len(loop)
        base = len(pos)
        for x, y in loop:
            gx = sample(grad_x, x - 0.5, y - 0.5)
            gy = sample(grad_y, x - 0.5, y - 0.5)
            nrm = np.array([-gx, gy])                    # downhill, y flipped to world
            nrm /= max(np.linalg.norm(nrm), 1e-9)
            shade = 0.5 + 0.45 * float(np.dot(nrm, light))
            u = (0.5 + shade * (ATLAS_W - 1)) / ATLAS_W
            wx, wy = region_to_world(x, y)
            pos += [(wx, wy, THICK / 2), (wx, wy, -THICK / 2)]
            uvs += [(u, strip_v[0]), (u, strip_v[1])]
        for i in range(n):
            j = (i + 1) % n
            a, b = base + 2 * i, base + 2 * j            # front; +1 is the back
            idx += [a, a + 1, b + 1, a, b + 1, b]
            nsegs += 1
            # march() keeps the inside on the left in y-down texels: check it
            (x0, y0), (x1, y1) = loop[i], loop[j]
            dx, dy = x1 - x0, y1 - y0
            ln = math.hypot(dx, dy)
            mx, my = (x0 + x1) / 2 - 0.5, (y0 + y1) / 2 - 0.5
            inside = sample(alpha, mx - dy / ln, my + dx / ln) >= 0.5
            outside = sample(alpha, mx + dy / ln, my - dx / ln) < 0.5
            bad_normals += not (inside and outside)

    # caps: one quad each, edges at the centres of the transparent border texels
    corners = [(0.5, 0.5), (ATLAS_W - 0.5, 0.5), (ATLAS_W - 0.5, CAP_H - 0.5), (0.5, CAP_H - 0.5)]
    for z, row0 in ((THICK / 2, 0), (-THICK / 2, CAP_H)):
        base = len(pos)
        for ax, ay in corners:
            x, y = region_to_world(ax, ay)
            pos.append((x, y, z))
            uvs.append(uv(ax, ay + row0))
        idx += [base, base + 3, base + 2, base, base + 2, base + 1]

    logo_mesh = {"name": "logo", "material": "mt_logo", "texture": "COMMON1",
                 "cutout": True, "bone": 1,
                 "pos": np.array(pos), "uv": np.array(uvs), "indices": idx}

    back, back_mesh = build_background(logo, mask, src_to_world)

    # The HOME Menu turns the whole model about Y (once every ~10 s on a 3DS),
    # which is the badge's spin. The background's bone is a YAxial billboard
    # at identity, so it keeps facing the camera behind the turning letters.
    ident = B_RENDER | B_LOCAL | B_WORLD | B_T0 | B_R0 | B_S1 | B_UNIFORM | B_IDENTITY
    return {
        "textures": [("COMMON1", atlas, TEX_RGBA5551), ("COMMON2", back, TEX_RGBA5551)],
        "meshes": [logo_mesh, back_mesh],
        "bones": [("root", B_IDENTITY | B_RENDER, -1, BILLBOARD_OFF),
                  ("logo", ident, 0, BILLBOARD_OFF),
                  ("back", ident, 0, BILLBOARD_Y)],
        "stats": {"loops": len(loops), "wall_quads": nsegs, "verts": len(pos),
                  "bad_normals": bad_normals},
        "mask": mask,
    }


def build_background(logo, mask, src_to_world):
    """The plate behind the badge: an oval of night lit by the light bar's
    blue and red, faint speed streaks and the logo's own glow (its letters
    inpainted away, blurred to a soft light the letters turn in front of),
    ringed with a steel rim. The oval is a polygon at BACK_Z, scaled to show
    the size it would at z = 0; the texture covers its bounding box."""
    hole = gauss_blur(mask.astype(float), 1.0) > 0.05
    glow = inpaint(logo.astype(float), hole)
    bright = glow[..., :3].max(-1)
    glow[..., 3] *= np.clip((bright - 20) / 150.0, 0, 1) ** 0.8 * 0.9
    glow = gauss_blur(glow, 1.5)

    # texel centres -> the z = 0 plane, the oval with 1.5 texels to spare
    hx = OVAL_A * (1 + 3.0 / BACK_W)
    hy = OVAL_B * (1 + 3.0 / BACK_H)
    X = -hx + (np.arange(BACK_W) + 0.5) / BACK_W * 2 * hx
    Y = CAMERA_Y + hy - (np.arange(BACK_H) + 0.5) / BACK_H * 2 * hy
    X, Y = np.meshgrid(X, Y)
    t = (Y - (CAMERA_Y - hy)) / (2 * hy)                   # 0 bottom .. 1 top
    img = np.stack([4 + 8 * t, 6 + 10 * t, 14 + 24 * t], -1)

    # where the light bar sits: map two logo pixels through the same transform
    def wash(u, v, rgb, radius, gain):
        cx, cy = src_to_world(u, v)
        d2 = ((X - cx) / radius) ** 2 + ((Y - cy) / (radius * 0.7)) ** 2
        return np.exp(-d2)[..., None] * np.array(rgb) * gain
    img += wash(118, 20, (40, 80, 230), 11.0, 0.42)        # blue, left
    img += wash(204, 20, (230, 40, 34), 11.0, 0.42)        # red, right

    rng = np.random.default_rng(2)                          # fixed: same banner each build
    for _ in range(14):
        y0 = rng.uniform(CAMERA_Y - hy * 0.8, CAMERA_Y + hy * 0.8)
        x0 = rng.uniform(-hx, hx)
        length = rng.uniform(6, 16)
        col = np.array((70, 120, 255) if rng.random() < 0.5 else (255, 70, 60))
        gain = rng.uniform(0.10, 0.22)
        across = np.exp(-((Y - y0) / 0.16) ** 2)
        along = np.clip(1 - np.abs(X - x0) / (length / 2), 0, 1) ** 1.5
        img += (across * along)[..., None] * col * gain

    # distance to the oval's edge (negative inside) and the outward normal
    dx, dy = X, Y - CAMERA_Y
    re = np.hypot(dx / OVAL_A, dy / OVAL_B)
    gx, gy = dx / OVAL_A ** 2, dy / OVAL_B ** 2
    gn = np.maximum(np.hypot(gx, gy), 1e-9)
    dist = (re - 1) * re / gn
    nx, ny = gx / gn, gy / gn
    img *= np.clip(1.12 - 0.5 * re ** 2, 0.4, 1)[..., None]

    # composite the glow, premultiplied, bilinear from the logo's pixels
    x0w, y0w = src_to_world(0, 0)
    x1w, y1w = src_to_world(1, 1)
    u = (X - x0w) / (x1w - x0w) - 0.5
    v = (Y - y0w) / (y1w - y0w) - 0.5
    pm = glow.copy()
    pm[..., :3] *= pm[..., 3:4] / 255.0
    pm = np.pad(pm, ((1, 1), (1, 1), (0, 0)))
    u = np.clip(u + 1, 0, pm.shape[1] - 1.001)
    v = np.clip(v + 1, 0, pm.shape[0] - 1.001)
    u0, v0 = u.astype(int), v.astype(int)
    fu, fv = (u - u0)[..., None], (v - v0)[..., None]
    g = (pm[v0, u0] * (1 - fu) * (1 - fv) + pm[v0, u0 + 1] * fu * (1 - fv)
         + pm[v0 + 1, u0] * (1 - fu) * fv + pm[v0 + 1, u0 + 1] * fu * fv)
    img = img * (1 - g[..., 3:4] / 255.0) + g[..., :3]

    # the rim's shadow on the plate, then the rim: a rounded steel bead lit
    # from the top left, its outer half facing out and its inner half in,
    # with a dark seam where it meets the plate. Texels past the edge take
    # the rim's colour, so filtering at the cut does not pull in black.
    shadow = np.clip((-dist - OVAL_RIM) / 0.7, 0, 1)
    img *= (0.55 + 0.45 * shadow)[..., None]
    s = np.clip(-dist / OVAL_RIM, 0, 1)                     # 0 outer edge .. 1 inner
    light = np.array([-0.55, 0.83])
    facing = np.cos(math.pi * s) * (nx * light[0] + ny * light[1])
    lit = 0.52 + 0.42 * facing + 0.12 * np.sin(math.pi * s)
    rim = steel(lit, np.zeros_like(lit)) * np.where(s > 0.82, 0.5, 1.0)[..., None]
    img = np.where((dist > -OVAL_RIM)[..., None], rim, img)

    back = np.zeros((BACK_H, BACK_W, 4), np.uint8)
    back[..., :3] = np.clip(np.round(img), 0, 255)
    back[..., 3] = 255

    # the oval itself is geometry, a fan of OVAL_SIDES: a 1-bit alpha cut
    # left texel steps on its flat top and bottom
    f = (CAMERA_Z - BACK_Z) / CAMERA_Z                     # same size on screen at depth
    ring = [(OVAL_A * math.cos(a), OVAL_B * math.sin(a))
            for a in np.arange(OVAL_SIDES) * 2 * math.pi / OVAL_SIDES]
    pts = [(0.0, 0.0)] + ring
    pos = [(x * f, CAMERA_Y + y * f, BACK_Z) for x, y in pts]
    uvs = [((x / hx + 1) / 2, (y / hy + 1) / 2) for x, y in pts]
    idx = []
    for i in range(OVAL_SIDES):                            # counter-clockwise from the front
        idx += [0, 1 + i, 1 + (i + 1) % OVAL_SIDES]
    mesh = {"name": "back", "material": "mt_back", "texture": "COMMON2",
            "cutout": False, "bone": 2,
            "pos": np.array(pos), "uv": np.array(uvs), "indices": idx}
    return back, mesh


# --------------------------------------------------------------------------
# Icon


def build_icon(logo, mask, size=48, ss=4):
    """The banner at rest, squared: the light bar's blue and red over the
    night gradient, the logo (with its own glow) across the lower half.
    Drawn at `ss` times the size and box-filtered down."""
    n = size * ss
    yy, xx = np.mgrid[0:n, 0:n] / n
    img = np.stack([4 + 10 * (1 - yy), 6 + 12 * (1 - yy), 14 + 30 * (1 - yy)], -1)
    for cx, rgb in ((0.28, (40, 80, 230)), (0.72, (230, 40, 34))):
        d2 = ((xx - cx) / 0.30) ** 2 + ((yy - 0.30) / 0.24) ** 2
        img += np.exp(-d2)[..., None] * np.array(rgb) * 0.55

    ys, xs = np.nonzero(mask)
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    scale = n * 0.97 / (x1 - x0)                           # letters across the width
    pm = logo.astype(float)
    pm[..., :3] *= pm[..., 3:4] / 255.0                    # premultiplied, then scaled
    pm = np.clip(resize(pm, int(round(logo.shape[1] * scale)),
                        int(round(logo.shape[0] * scale)), Image.LANCZOS), 0, 255)
    left = int(round(n / 2 - (x0 + x1) / 2 * scale))
    top = int(round(n * 0.62 - (y0 + y1) / 2 * scale))
    letters = resize(mask.astype(float), pm.shape[1], pm.shape[0])
    shadow = np.zeros((n, n))
    for y in range(n):
        by = y - top
        if 0 <= by < pm.shape[0]:
            lo, hi = max(0, left), min(n, left + pm.shape[1])
            shadow[y, lo:hi] = letters[by, lo - left:hi - left]
    shadow = np.clip(gauss_blur(shadow, ss * 0.8) * 2.0, 0, 1)
    img *= 1 - 0.75 * shadow[..., None]                    # a dark rim off the glow
    for y in range(n):
        by = y - top
        if 0 <= by < pm.shape[0]:
            lo, hi = max(0, left), min(n, left + pm.shape[1])
            src = pm[by, lo - left:hi - left]
            img[y, lo:hi] = img[y, lo:hi] * (1 - src[:, 3:4] / 255.0) + src[:, :3]
    img = np.clip(img, 0, 255).astype(np.uint8)
    return np.asarray(Image.fromarray(img).resize((size, size), Image.BOX))


# --------------------------------------------------------------------------
# Sound

SIREN = "CopSiren01"         # INGAME bank: the pursuit wail, a 5.3 s loop
SIREN_FROM = 5.0             # its lowest pitch (~620 Hz), just before the loop point
SIREN_SECONDS = 2.9          # the HOME Menu plays at most ~3 s
SIREN_FADE = 0.45            # out as the wail tips over its top (~1440 Hz)
# The HOME Menu plays a mono banner sound as its default chime instead (seen
# on a 3DS); stereo 16-bit at 32 kHz is the format of a banner sound that
# plays on the user's 3DS.
SOUND_RATE = 32000


def resample(x, n_out):
    """Band-limited resample by zero-padding the spectrum. The clip starts and
    ends faded to silence, so treating it as periodic adds no click."""
    spec = np.fft.rfft(x)
    out = np.zeros(n_out // 2 + 1, complex)
    k = min(len(spec), len(out))
    out[:k] = spec[:k]
    return np.fft.irfft(out, n_out) * (n_out / len(x))


def build_sound(retail):
    """One rising wail of the game's own siren: from the bottom of the loop,
    through the loop point, up to the top, faded as it starts to fall.
    Returns the rate and (n, 2) int16 frames, the same in both channels."""
    bank = audio_convert.read_bank(Path(retail) / "SOUND" / "INGAME.MSH")
    patch = next(p for p in bank if p["name"] == SIREN)
    pcm, loop_start, loop_end = audio_convert.decode_adpcm(patch["data"])
    rate = patch["pitch"]
    x = np.array(pcm, np.float64)
    wail = np.concatenate([x[int(SIREN_FROM * rate):loop_end], x[loop_start:loop_end]])
    clip = wail[:int(SIREN_SECONDS * rate)]
    n = len(clip)
    env = np.ones(n)
    fin = int(0.02 * rate)
    fout = int(SIREN_FADE * rate)
    env[:fin] = np.linspace(0, 1, fin)
    env[n - fout:] = 0.5 + 0.5 * np.cos(np.linspace(0, math.pi, fout))
    clip = resample(clip * env, int(round(n * SOUND_RATE / rate)))
    clip *= 0.8 * 32767 / np.abs(clip).max()
    mono = np.round(clip).astype("<i2")
    return SOUND_RATE, np.stack([mono, mono], 1)


def write_wav(path, rate, frames):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(frames.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.ascontiguousarray(frames, "<i2").tobytes())


# --------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--retail", default=str(ROOT / "extracted-retail"))
    ap.add_argument("--out", default=str(ROOT / "3DS Files" / "meta" / "hp2"))
    args = ap.parse_args()

    logo = load_logo(args.retail)
    scene = build_scene(logo)
    cgfx = build_cgfx(scene)
    assert len(cgfx) < CGFX_LIMIT, "CGFX is %d bytes, over the HOME Menu's limit" % len(cgfx)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "banner.cgfx").write_bytes(cgfx)
    Image.fromarray(build_icon(logo, scene["mask"])).save(out / "icon.png")
    rate, pcm = build_sound(args.retail)
    write_wav(out / "banner.wav", rate, pcm)
    st = scene["stats"]
    print("banner.cgfx %d bytes: %d outlines, %d wall quads, %d logo vertices, "
          "%d edges failing the inside check" % (len(cgfx), st["loops"], st["wall_quads"], st["verts"],
                                  st["bad_normals"]))
    print("icon.png 48x48")
    print("banner.wav %.2f s of %s at %d Hz, %d channels" % (len(pcm) / rate, SIREN, rate,
                                                              pcm.shape[1]))


if __name__ == "__main__":
    main()
