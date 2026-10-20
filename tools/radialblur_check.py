#!/usr/bin/env python3
"""Cross-check radialblur.c against the retail image, run in mipsemu.

The model is the image: GetPlayerView (0x0010f0d0), the view's on and off
(0x0010f128, 0x0010f1a8), RadialBlurOn and Off (0x0010f178, 0x0010f1b0),
RadialBlurOnOff on a view (0x0010f1e0, the replay screen's),
RadialBlurAlpha (0x0010f238), DisplayRadialBlur (0x0010f280) and
DisplayBlendPrevious (0x0010f4f0) run as shipped, with eGetView, the ePoly
constructor and GetTextureInfo under them. ePoly::Render (0x0010fa68) is
stubbed to print the poly it is given, AttachSolidPolys (0x0010bb20) to
print "attach", and the ePoly destructor to do nothing. The harness
(tools/src/radialblur_test.c) runs radialblur.c's functions and prints the
polys radialblur_mask_polys and radialblur_previous_poly build, which
trackview.c draws.

The script:

    F p                     both alpha pairs filled with the byte p
    C s r p                 the race coordinator: none when s < 0, else in
                            state s, with a replay screen (r) for player p
    V i id act b rta x y w h z
                            view i: its ID, Active, blend texture (0 none,
                            1 RADIALBLUR, 2 another), and its render
                            target's Active, scissor and MaxZ (bits)
    G p                     GetPlayerView(p): the view's index, or null
    ON p, OFF p             RadialBlurOn / Off(p)
    VON i, VOFF i           0x0010f128 / 0x0010f1a8 on view i
    OO on i                 0x0010f1e0(on, view i)
    R on                    the replay screen's: 0x0010f1e0(on, view 1)
    A p from to             RadialBlurAlpha(p, from, to), floats as bits
    D i                     DisplayRadialBlur(view i): each poly drawn
    P i                     DisplayBlendPrevious(view i): the poly drawn

After each change both alpha pairs and every view's blend texture print.

Not run on both sides: RadialBlurOnOff(bool, int) (0x0010f1f8) has no
caller in the image; the facts below check that. DisplayBlendPrevious first
marks the last frame's TextureInfo semitransparent (byte 79) so Render
blends it; the 3DS's last frame is trackview.c's copy, and the fact checks
the store. The view-on's alphas are indexed by the view's ID less one with
no check, and RadialBlurAlpha's by the player: the script keeps to the
player views, 1 and 2, and players 0 and 1, which is all the game calls.

    python tools/radialblur_check.py
    python tools/radialblur_check.py --mutate [--only a,b]
    python tools/radialblur_check.py --dump out/radialblur
"""
import argparse
import os
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import physicscar_check as pcc
import retail_model

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/radialblur_test.c"
RBC = "3DS Files/source/radialblur.c"
SOURCES = [HARNESS, RBC, "3DS Files/source/epoly.c"]
HARNESS_TIMEOUT = 30

# ================================================================ the image

GP = 0x003358f0
GET_PLAYER_VIEW = 0x0010f0d0    # GetPlayerView__Fi
VIEW_ON = 0x0010f128            # RadialBlurOn(eView *), inlined name lost
BLUR_ON = 0x0010f178            # RadialBlurOn__Fi
VIEW_OFF = 0x0010f1a8           # RadialBlurOff(eView *)
BLUR_OFF = 0x0010f1b0           # RadialBlurOff__Fi
ONOFF_VIEW = 0x0010f1e0         # RadialBlurOnOff(bool, eView *)
ONOFF_PLAYER = 0x0010f1f8       # RadialBlurOnOff__Fbi, no caller
ALPHA = 0x0010f238              # RadialBlurAlpha__Fiff
DISPLAY = 0x0010f280            # DisplayRadialBlur__FP5eViewP9eDmaChainT1
PREVIOUS = 0x0010f4f0           # DisplayBlendPrevious__FP5eViewP9eDmaChainT1
RENDER = 0x0010fa68             # Render__5ePolyP11TextureInfoi
ATTACH = 0x0010bb20             # AttachSolidPolys__FP9eDmaChainT0
POLY_DTOR = 0x00114db8          # _$_5ePoly
DISPLAY_FRAME = 0x00113a54      # eDisplayFrame's call of DisplayRadialBlur
VIEWS = 0x002c95b0              # eGetView's table, 128 bytes a view
TEXINFOS = 0x002c8690           # GetTextureInfo's, 164 bytes a target
FROM = GP - 24712               # the two from-alphas, by player
TO = GP - 24704                 # the two to-alphas
BLUR_TEX = GP - 25124           # pTextureInfoRadialBlur
PREV_RT = GP - 24920            # the last frame's render target

NVIEWS = 5
RT_BASE = 0x01000000            # view i's render target at + i * 0x100
COORD = 0x01001000
REPLAY = 0x01001100
BLUR_TI = 0x01002000
OTHER_TI = 0x01002100
PREV = 0x01003000               # the last frame's target, ID PREV_ID
PREV_ID = 2
CHAIN0, CHAIN1 = 0x01004000, 0x01004100


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def s32(v):
    v &= 0xffffffff
    return v - (1 << 32) if v & 0x80000000 else v


def script():
    rng = random.Random(0xb102)
    ops = ["F 5a", "C -1 0 0"]
    # The player views, the flailer's (0), the mirror's (3) and one more.
    ops += ["V 0 0 1 0 1 0 0 512 448 %08x" % fbits(65535.0),
            "V 1 1 1 0 1 0 0 512 448 %08x" % fbits(65535.0),
            "V 2 2 1 0 1 0 224 512 224 %08x" % fbits(16777215.0),
            "V 3 3 1 0 1 192 16 128 64 %08x" % fbits(1.5),
            "V 4 4 1 0 1 7 9 101 33 %08x" % fbits(-2.0)]
    players = [-1, 0, 1, 2, 3]
    # GetPlayerView in each coordinator state.
    for c in ("C -1 0 0", "C 0 0 0", "C 3 0 0", "C 4 0 0", "C 4 1 0",
              "C 4 1 1", "C 4 1 3", "C 5 1 0", "C 7 0 0", "C 7 1 1"):
        ops.append(c)
        ops += ["G %d" % p for p in players]
    # On and off by player, out of a replay and in one.
    ops += ["C 3 0 0", "ON 0", "ON 1", "OFF 0", "ON 0", "OFF 1",
            "C 4 1 1", "OFF 0", "ON 1", "OFF 1", "ON 0",
            "C 4 1 0", "OFF 1", "OFF 0", "ON 0",
            "C 7 0 0", "OFF 0", "ON 0", "ON 1", "VON 1", "VON 2",
            "C -1 0 0", "ON 1", "OFF 1", "ON 1",
            "VOFF 1", "VON 1", "VOFF 2", "VON 2", "VOFF 1",
            "OO 1 1", "OO 0 1", "OO 5 2", "OO 0 2", "OO -1 1",
            "R 1", "R 0", "R 1", "C 7 1 0", "R 0", "R 1", "C 3 0 0", "R 1",
            "OO 1 2"]
    # The alphas: the nitro's (0, 0.8), the edges, past 1 and below 0.
    for p, a, b in ((0, 0.0, 0.8), (1, 0.25, 1.0), (0, 1.0, 0.0),
                    (1, 0.5, 0.627451), (0, 0.003, 0.997), (1, 1.2, 2.0),
                    (0, -0.1, -1.5), (1, 0.0, 0.0), (0, 1.0 / 255, 254.5 / 255),
                    (1, 100.0, 1e-30), (0, 0.8, 0.0)):
        ops.append("A %d %08x %08x" % (p, fbits(a), fbits(b)))
        ops.append("D %d" % (1 + p))
    ops += ["VON 1", "D 1", "VON 2", "D 2", "P 1", "P 2"]
    # Every view drawn, and the cases that draw nothing.
    for i in range(NVIEWS):
        ops += ["D %d" % i, "P %d" % i]
    ops += ["V 1 1 0 1 1 0 0 512 448 %08x" % fbits(65535.0), "D 1", "P 1",
            "V 1 1 1 1 0 0 0 512 448 %08x" % fbits(65535.0), "D 1", "P 1",
            "V 1 1 1 0 1 0 0 512 448 %08x" % fbits(65535.0), "D 1", "P 1",
            "V 1 1 1 2 1 0 0 512 448 %08x" % fbits(65535.0), "D 1", "P 1",
            "V 4 2 1 1 1 0 0 512 448 %08x" % fbits(1.0), "D 4", "P 4",
            "V 3 1 1 1 1 3 5 99 77 %08x" % fbits(2.0), "D 3", "P 3",
            "V 0 2 1 2 1 -8 -6 31 -7 %08x" % fbits(0.5), "D 0", "P 0",
            # A blur on the flailer's, the mirror's and an unknown ID: the
            # quads only for 1 and 2, the last frame for any.
            "V 0 0 1 1 1 0 0 512 448 %08x" % fbits(65535.0), "D 0", "P 0",
            "V 3 3 1 1 1 192 16 128 64 %08x" % fbits(1.5), "D 3", "P 3",
            "V 4 9 1 2 1 7 9 101 33 %08x" % fbits(-2.0), "D 4", "P 4",
            "V 4 -1 1 1 1 7 9 101 33 %08x" % fbits(3.0), "D 4", "P 4"]
    # Scissors at random: odd and even, off the origin, now and then
    # negative, with alphas between.
    for _ in range(40):
        i = rng.choice((1, 2))
        ident = rng.choice((1, 2))
        x = rng.choice((0, rng.randint(-64, 640)))
        y = rng.choice((0, rng.randint(-64, 480)))
        w = rng.choice((512, 640, rng.randint(1, 700), -rng.randint(1, 9)))
        h = rng.choice((448, 224, rng.randint(1, 500), -rng.randint(1, 9)))
        z = rng.choice((65535.0, 16777215.0, rng.uniform(0, 1e7), 0.0))
        ops.append("V %d %d 1 %d 1 %d %d %d %d %08x" % (
            i, ident, rng.choice((1, 1, 2)), x, y, w, h, fbits(z)))
        if rng.random() < 0.5:
            ops.append("A %d %08x %08x" % (
                ident - 1, fbits(rng.random()), fbits(rng.random())))
        ops += ["D %d" % i, "P %d" % i]
    return ops


def encode(ops):
    return NL.join(ops) + NL


class Model(object):
    def __init__(self):
        self.e = retail_model.emu(retail=True, ieee=True)
        e = self.e
        e.stub(RENDER, self.s_render)
        e.stub(ATTACH, self.s_attach)
        e.stub(POLY_DTOR, lambda em: None)
        e.put32(BLUR_TEX, BLUR_TI)
        e.put32(PREV_RT, PREV)
        e.put32(PREV, PREV_ID)
        e.put32(COORD, 0)
        e.put32(COORD + 44, 0)
        self.out = []
        self.prev79 = []
        for i in range(NVIEWS):
            e.write(view_at(i), bytes(128))
            e.put32(view_at(i) + 48, rt_at(i))
            e.write(rt_at(i), bytes(176))

    def emit(self, s):
        self.out.append(s)

    def tex_name(self, a):
        return {0: "null", BLUR_TI: "blur", OTHER_TI: "other",
                TEXINFOS + PREV_ID * 164: "prev"}.get(a & 0xffffffff, "?")

    def s_render(self, em):
        p = em.reg[4] & 0xffffffff
        e = self.e
        self.emit("  poly %s %d" % (self.tex_name(em.reg[5]),
                                    s32(em.reg[6])))
        for i in range(4):
            self.emit("    v %08x %08x %08x %08x"
                      % struct.unpack("<4I", e.read(p + 16 + 16 * i, 16)))
        for i in range(4):
            self.emit("    uv %08x %08x %08x"
                      % struct.unpack("<3I", e.read(p + 80 + 12 * i, 12)))
        for i in range(4):
            self.emit("    c %02x %02x %02x %02x"
                      % tuple(e.read(p + 128 + 4 * i, 4)))
        b = e.read(p + 144, 9)
        self.emit("    a %s %d" % (" ".join("%d" % x for x in b),
                                   e.u32(p + 156) != 0))
        if self.tex_name(em.reg[5]) == "prev":
            self.prev79.append(e.u8(TEXINFOS + PREV_ID * 164 + 79))

    def s_attach(self, em):
        self.emit("  attach")

    def state(self):
        e = self.e
        f = e.read(FROM, 2)
        t = e.read(TO, 2)
        blends = [self.tex_name(e.u32(view_at(i) + 108))
                  for i in range(NVIEWS)]
        self.emit("S %02x %02x %02x %02x | %s"
                  % (f[0], f[1], t[0], t[1], " ".join(blends)))

    def run(self, ops):
        e = self.e
        for op in ops:
            w = op.split()
            o, a = w[0], [dec(x) for x in w[1:]]
            if o == "F":
                p = int(w[1], 16)
                e.write(FROM, bytes([p, p]))
                e.write(TO, bytes([p, p]))
                self.emit("F %02x" % p)
                self.state()
            elif o == "C":
                s, r, pl = a
                if s < 0:
                    e.put32(GP - 22216, 0)
                else:
                    e.put32(GP - 22216, COORD)
                    e.put32(COORD, s)
                    e.put32(COORD + 44, REPLAY if r else 0)
                    e.put32(REPLAY + 20, pl)
                self.emit("C %d %d %d" % (s, r, pl))
            elif o == "V":
                i, ident, act, b, rta, x, y, ww, h = a[:9]
                z = int(w[10], 16)
                v = view_at(i)
                rt = rt_at(i)
                e.put32(v, ident)
                e.write(v + 4, bytes([act]))
                e.put32(v + 108, (0, BLUR_TI, OTHER_TI)[b])
                e.put32(rt + 8, rta)
                for k, val in enumerate((x, y, ww, h)):
                    e.put32(rt + 20 + 4 * k, val)
                e.put32(rt + 116, z)
                self.emit("V %d %d %d %d %d %d %d %d %d %08x"
                          % (i, ident, act, b, rta, x, y, ww, h, z))
                self.state()
            elif o == "G":
                v = e.call(GET_PLAYER_VIEW, a[0]) & 0xffffffff
                self.emit("G %d -> %s" % (a[0], "null" if v == 0 else
                                          "%d" % ((v - VIEWS) // 128)))
            elif o in ("ON", "OFF"):
                e.call(BLUR_ON if o == "ON" else BLUR_OFF, a[0])
                self.emit("%s %d" % (o, a[0]))
                self.state()
            elif o in ("VON", "VOFF"):
                e.call(VIEW_ON if o == "VON" else VIEW_OFF, view_at(a[0]))
                self.emit("%s %d" % (o, a[0]))
                self.state()
            elif o == "OO":
                e.call(ONOFF_VIEW, a[0], view_at(a[1]))
                self.emit("OO %d %d" % (a[0], a[1]))
                self.state()
            elif o == "R":
                e.call(ONOFF_VIEW, a[0], view_at(1))
                self.emit("R %d" % a[0])
                self.state()
            elif o == "A":
                fr, to = int(w[2], 16), int(w[3], 16)
                e.fpr[12] = fr
                e.fpr[13] = to
                e.call(ALPHA, a[0])
                self.emit("A %d %08x %08x" % (a[0], fr, to))
                self.state()
            elif o == "D":
                self.emit("D %d" % a[0])
                e.call(DISPLAY, view_at(a[0]), CHAIN0, CHAIN1)
            elif o == "P":
                self.emit("P %d" % a[0])
                e.write(TEXINFOS + PREV_ID * 164 + 79, b"\0")
                e.call(PREVIOUS, view_at(a[0]), CHAIN0, CHAIN1)
        return self.out


def dec(x):
    try:
        return int(x)
    except ValueError:
        return None


def view_at(i):
    return VIEWS + 128 * i


def rt_at(i):
    return RT_BASE + 0x100 * i


def image_facts(m):
    """What the port takes from the image without running it."""
    e = m.e
    out = []
    jal = lambda t: 0x0c000000 | (t >> 2)
    out.append((e.u32(DISPLAY_FRAME) == jal(DISPLAY)
                and e.u32(DISPLAY_FRAME + 16) == jal(PREVIOUS),
                "eDisplayFrame: DisplayRadialBlur at %08x, then "
                "DisplayBlendPrevious" % DISPLAY_FRAME))
    callers = []
    for a in range(0x00100000, 0x00300000, 4):
        try:
            if e.u32(a) == jal(ONOFF_PLAYER):
                callers.append(a)
        except struct.error:
            break
    out.append((not callers, "RadialBlurOnOff__Fbi called from: %s"
                % (", ".join("%08x" % a for a in callers) or "nowhere")))
    out.append((m.prev79 and all(b == 1 for b in m.prev79),
                "DisplayBlendPrevious marked the last frame's TextureInfo "
                "semitransparent: %s" % sorted(set(m.prev79))))
    # The edge alpha, the 255 and the 1/512.
    out.append((e.u32(0x0010f158) == 0x240400a0,
                "the view-on's alpha: %08x" % e.u32(0x0010f158)))
    out.append((e.u32(0x0010f238) == 0x3c01437f,
                "RadialBlurAlpha's scale: %08x" % e.u32(0x0010f238)))
    out.append((e.u32(0x0010f5c4) == 0x3c013b00,
                "DisplayBlendPrevious's texel: %08x" % e.u32(0x0010f5c4)))
    return out


def model(ops):
    m = Model()
    lines = m.run(ops)
    return m, lines


# ============================================================== the harness

def build_harness(tmp, name="radialblur_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return pcc.HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


diff = pcc.diff

# ============================================================ the mutations

MUTATIONS = [
    ("replay-any-player", RBC,
     "        if (((ReplayScreen *)rc->pReplayScreen)->PlayerNumber != player)\n"
     "            return NULL;\n", ""),
    ("replay-own-view", RBC,
     "        return eGetView(EVIEW_ID_PLAYER1);\n    }",
     "        return eGetView(player + 1);\n    }"),
    ("replay-needs-no-screen", RBC,
     "        && rc->pReplayScreen != NULL) {",
     "        ) {\n        if (rc->pReplayScreen == NULL) return NULL;"),
    ("replay-state-5", RBC,
     "rc->CurrentRCState == RCSTATE_INSTANT_REPLAY",
     "rc->CurrentRCState == (RCState)5"),
    ("player-view-same", RBC,
     "    return eGetView(player + 1);\n}", "    return eGetView(player);\n}"),
    ("on-in-postrace", RBC,
     "        && pRaceCoordinator->CurrentRCState == RCSTATE_POSTRACE)\n"
     "        return;",
     "        && pRaceCoordinator->CurrentRCState == (RCState)8)\n"
     "        return;"),
    ("on-alpha-128", RBC,
     "#define BLUR_TO_ALPHA 160", "#define BLUR_TO_ALPHA 128"),
    ("on-keeps-from", RBC,
     "        RadialBlurFromAlpha[i] = 0;\n", ""),
    ("on-index-by-id", RBC,
     "    i = (uint32_t)(view->ID - 1);", "    i = (uint32_t)(view->ID);"),
    ("off-keeps-mask", RBC,
     "    view->pBlendMask = NULL;\n}", "    (void)view;\n}"),
    ("onoff-inverted", RBC,
     "    if (on)\n        radialblur_view_on(view);",
     "    if (!on)\n        radialblur_view_on(view);\n    else if (0)\n"
     "        radialblur_view_on(view);"),
    ("alpha-swapped", RBC,
     "    RadialBlurFromAlpha[player] = (uint8_t)ee_trunc_w(ee_mul(from, 255.0f));",
     "    RadialBlurFromAlpha[player] = (uint8_t)ee_trunc_w(ee_mul(to, 255.0f));"),
    ("alpha-256", RBC,
     "    RadialBlurToAlpha[player]   = (uint8_t)ee_trunc_w(ee_mul(to, 255.0f));",
     "    RadialBlurToAlpha[player]   = (uint8_t)ee_trunc_w(ee_mul(to, 256.0f));"),
    ("alpha-rounded", RBC,
     "    RadialBlurToAlpha[player]   = (uint8_t)ee_trunc_w(ee_mul(to, 255.0f));",
     "    RadialBlurToAlpha[player]   = (uint8_t)ee_trunc_w(ee_mul(to, 255.0f) + 0.5f);"),
    ("alpha-clamped", RBC,
     "    RadialBlurFromAlpha[player] = (uint8_t)ee_trunc_w(ee_mul(from, 255.0f));",
     "    RadialBlurFromAlpha[player] = (uint8_t)(from > 1.0f ? 255 : from < 0.0f ? 0 : ee_trunc_w(ee_mul(from, 255.0f)));"),
    ("replay-view-2", RBC,
     "    radialblur_on_off_view(on, eGetView(EVIEW_ID_PLAYER1));",
     "    radialblur_on_off_view(on, eGetView(2));"),
    ("mask-any-id", RBC,
     "    else\n        return 0;\n    rt = view->pRenderTarget0;",
     "    else\n        k = 0;\n    rt = view->pRenderTarget0;"),
    ("mask-k-swapped", RBC,
     "    if (view->ID == EVIEW_ID_PLAYER1)\n        k = 0;",
     "    if (view->ID == EVIEW_ID_PLAYER1)\n        k = 1;"),
    ("mask-rt-inactive", RBC,
     "    if (rt == NULL || rt->Active == 0)\n        return 0;",
     "    if (rt == NULL)\n        return 0;"),
    ("mask-z-zero", RBC,
     "    z                  = rt->MaxZ;", "    z                  = 0.0f;"),
    ("mask-aspect-kept", RBC,
     "    p.ApplyAspectRatio = 0;\n    p.SunPoly          = 1;\n    p.AlphaA",
     "    p.SunPoly          = 1;\n    p.AlphaA"),
    ("mask-not-sun", RBC,
     "    p.SunPoly          = 1;\n    p.AlphaA           = EPOLY_ALPHA_CS;\n"
     "    p.AlphaB           = EPOLY_ALPHA_CS;",
     "    p.AlphaA           = EPOLY_ALPHA_CS;\n"
     "    p.AlphaB           = EPOLY_ALPHA_CS;"),
    ("mask-b-cd", RBC,
     "    p.AlphaB           = EPOLY_ALPHA_CS;",
     "    p.AlphaB           = EPOLY_ALPHA_CD;"),
    ("mask-c-ad", RBC,
     "    p.AlphaC           = EPOLY_ALPHA_AS;",
     "    p.AlphaC           = EPOLY_ALPHA_AD;"),
    ("mask-middle-to", RBC,
     "    p.Colours[2][3] = from;", "    p.Colours[2][3] = to;"),
    ("mask-corner-from", RBC,
     "    p.Colours[0][3] = to;", "    p.Colours[0][3] = from;"),
    ("mask-cx-rounded", RBC,
     "    cx   = x0 + rt->ScissorW / 2;", "    cx   = x0 + (rt->ScissorW + 1) / 2;"),
    ("mask-cy-shifted", RBC,
     "    cy   = y0 + rt->ScissorH / 2;", "    cy   = y0 + (rt->ScissorH >> 1);"),
    ("mask-quarter2-v3-kept", RBC,
     "    p.Vertices[3].x = (float)x1;\n", ""),
    ("mask-quarter3-v1-kept", RBC,
     "    p.Vertices[0].y = (float)y1;\n    p.Vertices[1].y = (float)y1;",
     "    p.Vertices[0].y = (float)y1;"),
    ("mask-quarter4-v0-kept", RBC,
     "    p.Vertices[0].x = (float)x0;\n    p.Vertices[3].x = (float)x0;\n"
     "    polys[3] = p;",
     "    p.Vertices[3].x = (float)x0;\n    polys[3] = p;"),
    ("mask-w-set", RBC,
     "    p.Vertices[3].z = z;\n    p.Colours[2][3] = from;",
     "    p.Vertices[3].z = z;\n    p.Vertices[3].w = 1.0f;\n"
     "    p.Colours[2][3] = from;"),
    ("prev-inactive-view", RBC,
     "    if (!view->Active || view->pBlendMask == NULL)",
     "    if (view->pBlendMask == NULL)"),
    ("prev-no-mask", RBC,
     "    if (!view->Active || view->pBlendMask == NULL)",
     "    if (!view->Active)"),
    ("prev-c-as", RBC,
     "    poly->AlphaC           = EPOLY_ALPHA_AD;",
     "    poly->AlphaC           = EPOLY_ALPHA_AS;"),
    ("prev-u1-from-x0", RBC,
     "    u1 = ee_mul(w - 0.5f, BLUR_TEXEL);",
     "    u1 = ee_mul(x0 + w - 0.5f, BLUR_TEXEL);"),
    ("prev-v0-no-half", RBC,
     "    v0 = ee_mul(y0 + 0.5f, BLUR_TEXEL);", "    v0 = ee_mul(y0, BLUR_TEXEL);"),
    ("prev-texel-256", RBC,
     "#define BLUR_TEXEL (1.0f / 512.0f)", "#define BLUR_TEXEL (1.0f / 256.0f)"),
    ("prev-uv-flipped", RBC,
     "    poly->UVs[2][1] = v1;\n    poly->UVs[3][0] = u0;\n    poly->UVs[3][1] = v1;",
     "    poly->UVs[2][1] = v0;\n    poly->UVs[3][0] = u0;\n    poly->UVs[3][1] = v0;"),
    ("prev-z-zero", RBC,
     "    z = rt->MaxZ;\n    poly->AlphaD", "    z = 0.0f;\n    poly->AlphaD"),
    ("prev-rt-inactive", RBC,
     "    if (rt == NULL || rt->Active == 0)\n        return false;",
     "    if (rt == NULL)\n        return false;"),
]

EQUIVALENT = set()


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    _m, base = model(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "script.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-44s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    scdir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        print("  listed as equivalent but %s: %s"
              % ("caught" if name in ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

    sc = script()
    m, lines = model(sc)
    facts = image_facts(m)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "script.txt"
        scp.write_text(encode(sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)
        d.with_suffix(".image").write_text(
            NL.join(("   " if ok else "BAD") + " " + l for ok, l in facts) + NL)

    bad = [l for ok, l in facts if not ok]
    for l in bad:
        print("image: " + l)
    n = diff(lines, harness)
    print("image: %d facts, %d wrong" % (len(facts), len(bad)))
    print("%d steps, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc or bad) else 0)


if __name__ == "__main__":
    main()
