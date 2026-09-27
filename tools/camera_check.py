"""Cross-check 3DS Files/source/camera.c and cammover.c against a model.

Camera.obj (0x00153a20) and the CM_ORBIT_CAR half of CameraMover.obj
(0x00154380) are the first thing in the port that carries state from frame to
frame: PreviousKey is last frame's CurrentKey and VelocityKey is the
difference, so a rule that is wrong by one frame produces plausible numbers
for ever. Hence a transcript over runs of frames rather than call by call.

The model is written from the disassembly -- the register traces are quoted
next to each rule -- and not from the C. Its matrix layer is imported from
emath_check, which is itself a model of eMathE.obj written from the ELF and
diffed against emath.c, so the chain of custody for every line here still
runs back to an address rather than to another port.

Everything is float32. The EE has no double, and the velocity record is a
difference of differences, so a model computing in 53 bits disagrees in the
last digit almost everywhere.

    python tools/camera_check.py
    python tools/camera_check.py --mutate       # break the C and re-diff
    python tools/camera_check.py --dump out/camera
"""
import argparse
import difflib
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
from emath_check import (emul_matrix, emul_vector3, erotate_x, erotate_y,
                         erotate_z, etranslate, etranspose, f32, mat_identity)

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

SOURCES = [
    "tools/src/camera_test.c",
    "3DS Files/source/camera.c",
    "3DS Files/source/cammover.c",
    "3DS Files/source/eview.c",
    "3DS Files/source/emath.c",
    "3DS Files/source/bmatrix.c",
    "3DS Files/source/bvector.c",
    "3DS Files/source/bmath.c",
    "3DS Files/source/bmathtab.c",
]


def g9(x):
    return "%.9g" % x


# --------------------------------------------------------- the disc's statics
#
# Read out of the ELF at the addresses the listings load from, not guessed:
# 0x3234f8..0x323510 for the orbit mover's eight tweakables plus the unnamed
# TweakOrbitFOV, and 0x321110 for the far plane the base constructor writes.

STOP_UPDATING = [0]                 # 0x3234b8 _6Camera$StopUpdating
USE_TWEAKABLES = [0]                # 0x3234f8
TWEAK_RADIUS = [5.0]                # 0x3234fc
TWEAK_ANGLE_H = [26000]             # 0x323500
TWEAK_ANGLE_V = [62000]             # 0x323502
LOOK_HEIGHT = [0.0]                 # 0x323504
IN_GAME_FOV = [13020]               # 0x323508
FRONT_END_FOV = [6000]              # 0x32350a
TARGET_HEIGHT = [f32(0.3)]          # 0x32350c
TWEAK_ORBIT_FOV = [8000]            # 0x323510
BOOM = [0.0, 0.0, 0.0, 0.0]         # 0x326f10 OrbitCarTranslation
MOVER_FAR_Z = 5000.0                # 0x321110, written by the base ctor
ENABLE_NEAR_Z = 0.5                 # 0x3f000000, written by Enable

MOVER_NAMES = [
    "CM_NONE", "CM_DRIVE", "CM_DEBUG_WORLD", "CM_TRACK_ROUTE_EDITOR",
    "CM_ORBIT_CAR", "CM_BUMPER", "CM_REAR_VIEW_MIRROR", "CM_TRACK_CAR",
    "CM_GARAGE", "CM_TRACK_FLY", "CM_MAX", "CM_SELECT_CAR", "CM_STILL",
    "CM_ZONE_FREEZE", "CM_ZONE_PREVIEW", "CM_ZONE_JUMPER", "CM_ZONE_JUMPER2",
    "CM_CUBIC_DAMPER",
]
CM_ORBIT_CAR = 4
CM_DRIVE = 1
CM_STILL = 12

ORBIT_JOY_SPEED = 500
ZOOM_IN = f32(0.99)                 # 0x321120
ZOOM_OUT = f32(1.01)                # 0x321124


def mover_type_name(t):
    """0x00154380: eighteen compares and a fall-through back to CM_NONE."""
    if t < 0 or t >= len(MOVER_NAMES):
        return MOVER_NAMES[0]
    return MOVER_NAMES[t]


# ------------------------------------------------------------------ the data


class Params(object):
    """The 144-byte CameraParams. `matrix` is sixteen floats row-major;
    pos/dir/tgt are four each, because bVector3 is a padded quadword and
    every instruction that touches them in SetCameraMatrix is .xyzw."""

    def __init__(self):
        self.matrix = [0.0] * 16
        self.pos = [0.0] * 4
        self.dir = [0.0] * 4
        self.tgt = [0.0] * 4
        self.td = 0.0
        self.fd = 0.0
        self.dof = 0.0
        self.nearz = 0.0
        self.farz = 0.0
        self.fov = 0

    def copy(self):
        p = Params()
        p.matrix = list(self.matrix)
        p.pos = list(self.pos)
        p.dir = list(self.dir)
        p.tgt = list(self.tgt)
        p.td, p.fd, p.dof = self.td, self.fd, self.dof
        p.nearz, p.farz, p.fov = self.nearz, self.farz, self.fov
        return p


class Camera(object):
    """448 bytes. cur at 0, prev at 144, vel at 288.

    vel.matrix is deliberately absent from the transcript: nothing on the
    disc writes it, so on the PS2 it is whatever the allocation held."""

    def __init__(self):
        self.cur = Params()
        self.prev = Params()
        self.vel = Params()
        self.elapsed = 0.0
        self.last = 0
        self.carnot = False
        self.dash = 0


def camera_init(c):
    """0x00153a20. Writes six of CurrentKey's scalars and then lets
    SetCameraMatrix fill the rest, twice with the same matrix -- so the
    second call differences a key against itself and the velocity record
    settles at zero whatever the allocation held.

        f5 = -1.0   f4 = 1200.0   f3 = 100.0   f1 = 10.0   f2 = 0.5
        [432]=1.0 [440]=0 [444]=0 [116]=0 [120]=0 [436]=0x80000000
        [112]=10.0 [132]=14075 [124]=0.5 [128]=5000.0
    """
    c.elapsed = 1.0
    c.carnot = False
    c.dash = 0
    c.last = 0x80000000
    c.cur.fd = 0.0
    c.cur.dof = 0.0
    c.cur.td = 10.0
    c.cur.fov = 14075
    c.cur.nearz = 0.5
    c.cur.farz = 5000.0

    m = [0.0] * 16
    m[0] = 1.0
    m[5] = -1.0
    m[10] = -1.0
    m[11] = 100.0
    m[14] = 1200.0
    m[15] = 1.0
    set_camera_matrix(c, m, 1.0)
    set_camera_matrix(c, m, 1.0)


def camera_copy(dst, src):
    """0x00153b10. LastUpdateTime forced back to 0x80000000, the four scalars
    moved by hand, then three 144-byte bMemCpy."""
    dst.last = 0x80000000
    dst.elapsed = src.elapsed
    dst.carnot = src.carnot
    dst.dash = src.dash
    dst.cur = src.cur.copy()
    dst.prev = src.prev.copy()
    dst.vel = src.vel.copy()


def trunc_w(x):
    """cvt.w.s with the EE's rounding mode, which the SDK leaves at chop."""
    if x != x:
        return 0
    if x >= 2147483648.0:
        return 0x7fffffff
    if x <= -2147483649.0:
        return -0x80000000
    return int(x)


def set_camera_matrix(c, m, elapsed):
    """0x00153ba0.

        00153bc0  bne v0,zero,end            StopUpdating
        00153bd0  bMemCpy(this+144, this, 144)
        00153bdc  swc1 f20,432(s0)           ElapsedTime
        00153c74  sqc2 vf1..vf4 -> 0(s0)     CurrentKey.Matrix = *m
        00153c88  eTransposeMatrix(sp, s0)
        00153c90  sw zero,12/28/44(sp)       t[0][3] = t[1][3] = t[2][3] = 0
        00153ca4  eMulVector(s0+64, sp, s0+48)
        00153cb8  vsub.xyzw vf02,vf00,vf02   vf00 is (0,0,0,1): pad -> 1 - pad
        00153cb4  vmul.xyz / vaddy.x / vaddz.x   d = (x*x + y*y) + z*z
        00153cd0  vrsqrt Q,vf00w,vf01x       k = 1 / sqrt(d)
        00153ce4  vmulx.xyzw vf03,vf03,vf01x direction, all four lanes
        00153cf8  vmulx.xyzw with [112]      target = dir * TargetDistance
        00153d08  vadd.xyzw                  target += position
        00153d1c  div.s f4,f4,f0             inv = 1 / elapsed
        00153dc0  subu / andi 0xffff         the FOV difference wraps as u16
        00153dec  mul.s f4,f4,f3 / cvt.w.s / sh
    """
    if STOP_UPDATING[0]:
        return

    c.prev = c.cur.copy()
    c.elapsed = f32(elapsed)
    cur, prev, vel = c.cur, c.prev, c.vel
    cur.matrix = list(m)

    t = etranspose(cur.matrix)
    t[3] = t[7] = t[11] = 0.0

    # vf00 minus the product, lane by lane: a +0 lane stays +0 (the image
    # says so, through tools/eview_check.py's static constructor).
    p = emul_vector3(t, cur.matrix[12:15])
    cur.pos = [f32(0.0 - p[0]), f32(0.0 - p[1]), f32(0.0 - p[2]),
               f32(1.0 - p[3])]

    d = f32(t[8] * t[8])
    d = f32(d + f32(t[9] * t[9]))
    d = f32(d + f32(t[10] * t[10]))
    # A true reciprocal square root where VU0 uses its RSQRT unit, the same
    # deliberate divergence bQuaternion's bNormalize carries.
    k = f32(1.0 / f32(math.sqrt(d))) if d > 0.0 else float("inf")
    cur.dir = [f32(t[8] * k), f32(t[9] * k), f32(t[10] * k), f32(t[11] * k)]
    cur.tgt = [f32(cur.pos[i] + f32(cur.dir[i] * cur.td)) for i in range(4)]

    inv = f32(1.0 / c.elapsed) if c.elapsed != 0.0 else float("inf")

    vel.pos = [f32(f32(cur.pos[i] - prev.pos[i]) * inv) for i in range(4)]
    vel.dir = [f32(f32(cur.dir[i] - prev.dir[i]) * inv) for i in range(4)]
    vel.tgt = [f32(f32(cur.tgt[i] - prev.tgt[i]) * inv) for i in range(4)]
    vel.td = f32(f32(cur.td - prev.td) * inv)
    vel.fd = f32(f32(cur.fd - prev.fd) * inv)
    vel.dof = f32(f32(cur.dof - prev.dof) * inv)
    vel.nearz = f32(f32(cur.nearz - prev.nearz) * inv)
    vel.farz = f32(f32(cur.farz - prev.farz) * inv)

    dfov = (cur.fov - prev.fov) & 0xffff
    vel.fov = trunc_w(f32(inv * f32(float(dfov)))) & 0xffff


# ------------------------------------------------------------- the movers


# The views, as far as a mover reaches them: each one's Camera ([56]) and
# its list of movers, head first. eView::AttachCameraMover (0x00106b18)
# links a mover in at the head and UnattachCameraMover (0x00106b38) unlinks
# it from wherever it is. use_view starts a view over with a camera, which
# is what the harness does before each constructor.
VIEW_CAM = {}
VIEW_MOVERS = {}


def use_view(viewid, cam):
    VIEW_CAM[viewid] = cam
    VIEW_MOVERS[viewid] = []


class Mover(object):
    """CameraMover, 44 bytes. The vtable at [40] is left out."""

    def __init__(self):
        self.type = 0
        self.viewid = 0
        self.enabled = 0
        self.view = None
        self.cam = None
        self.carnot = False
        self.dash = 0


def mover_init(m, viewid, type_):
    """0x001544f0. A ViewID of -1 leaves it detached and disabled, [20] pView
    and [24] pCamera both 0; anything else is v = eGetView(id) into [20],
    v's Camera ([56]) into [24], the far plane forced, and Enable."""
    m.type = type_
    m.viewid = viewid
    m.enabled = 0
    if viewid == -1:
        m.view = None
        m.cam = None
        m.carnot = False
        m.dash = 0
        return
    cam = VIEW_CAM[viewid]
    m.view = viewid
    cam.cur.farz = MOVER_FAR_Z
    m.carnot = cam.carnot
    m.dash = cam.dash
    m.cam = cam
    mover_enable(m)


def mover_enable(m):
    """0x001545e0. Early-out when already enabled. The two render flags are
    behind StopUpdating; the near plane is not."""
    if m.enabled:
        return
    m.enabled = 1
    if not STOP_UPDATING[0]:
        m.cam.carnot = m.carnot
        m.cam.dash = m.dash
    VIEW_MOVERS[m.view].insert(0, m)        # AttachCameraMover([20], m)
    m.cam.cur.nearz = ENABLE_NEAR_Z


def mover_disable(m):
    """0x00154658. Early-out when already disabled -- which is what keeps a
    detached mover from dereferencing a null camera -- and the flags travel
    the other way, off the camera and into the mover. StopUpdating is not
    consulted at all."""
    if not m.enabled:
        return
    m.enabled = 0
    m.carnot = m.cam.carnot
    m.dash = m.cam.dash
    VIEW_MOVERS[m.view].remove(m)           # UnattachCameraMover([20], m)


class Orbit(object):
    """OrbitCarCameraMover, 208 bytes. TM at 112 is never written and never
    read; HandlersAdded at 192 stays 0 in the port (see the divergence note
    in cammover.c) where the disc's AddJoyHandlers sets it at 0x00154ac0."""

    def __init__(self):
        self.base = Mover()


def orbit_init(o, viewid, car, joyport):
    """0x00154728.

        f2 = 5.0   f0 = 1000.0   f3 = 1.0   f1 = [gp-31452] = 0.4
        a3 = 0xf230   v1 = 26000   a0 = 0xc738   a1 = 0xf8f4   a2 = 24
    """
    mover_init(o.base, viewid, CM_ORBIT_CAR)

    o.radius = 5.0
    o.angleh = 26000
    o.anglev = 0xf230
    o.desired_anglev = 0xf230
    o.hspeed = 0
    o.vspeed = 0
    o.dhspeed = 0
    o.dvspeed = 0
    o.desired_radius = 5.0
    o.max_radius = 1000.0
    o.min_radius = 1.0
    o.min_anglev = 0xc738
    o.max_anglev = 0xf8f4
    o.radius_mult = 1.0
    o.max_radius_vel = f32(0.4)
    o.accel = 24
    o.femode = 0
    o.approach_v = 0
    o.car = car
    o.follow_chopper = 0
    o.joyport = joyport
    o.handlers_added = 0

    if not STOP_UPDATING[0]:
        o.base.cam.carnot = False
        o.base.cam.dash = 0
        o.base.cam.cur.fov = IN_GAME_FOV[0]


def approach(cur, want, accel):
    """0x00154db8. Two arms around an unsigned compare and a movz, so the
    step is computed first and thrown away when the gap is small enough: a
    gap of exactly `accel` lands on `want` rather than overshooting."""
    if cur < want:
        diff = want - cur
        stepped = cur + accel
    else:
        diff = cur - want
        stepped = cur - accel
    return stepped if accel < diff else want


def orbit_update(o, elapsed):
    """0x00154b78. IsGameFlowPaused is the caller's business in the port.

        00154ba8  eIdentity(sp)
        00154bb0  lw v0,180 FollowChopper   -- the chopper arm, not ported
        00154cb4  trans.row3 = -GeometryPosition, z also -= LookHeight
        00154ce8  eTransposeMatrix(sp+128, car+144)
        00154cf8  eMulMatrix(sp+64, sp, sp+128)
        00154d0c  vadd.xyzw with 0x326f10   m.row3 += OrbitCarTranslation
        00154d1c  carless: eIdentity, m[3][2] = -OrbitTargetHeight
        00154d40  c.eq.s f1,1.0             multiplier applied only when != 1
        00154d64  the two radius clamps, Radius first and DesiredRadius after
        00154e20  AngleV += low halfword of VRotationSpeed
        00154e54  slti v0,v0,81             the approach snaps inside 81
        00154e88  clamp to MaxAngleV then MinAngleV, in that order
        00154ec0  UseTweakables swaps in TweakAngleH/V and TweakRadius
        00154f5c  eRotateX(16384) then eRotateY(0xc000)
        00154f80  lhu a0,-22240(gp)         TweakOrbitFOV, not InGameFOV
        00154fc8  SetCameraMatrix(cam, m, RealTimeElapsed)
    """
    cam = o.base.cam
    trans = mat_identity()

    if o.car is not None:
        p = o.car.geopos
        trans[12] = f32(-p[0])
        trans[13] = f32(-p[1])
        trans[14] = f32(f32(-p[2]) - LOOK_HEIGHT[0])
        inv = etranspose(o.car.body)
        m = emul_matrix(trans, inv)
        for i in range(4):
            m[12 + i] = f32(m[12 + i] + BOOM[i])
    else:
        m = mat_identity()
        m[14] = f32(-TARGET_HEIGHT[0])

    if o.radius_mult != 1.0:
        o.desired_radius = f32(o.desired_radius * o.radius_mult)

    o.radius = o.desired_radius
    if o.desired_radius < o.min_radius:
        o.radius = o.min_radius
    if o.max_radius < o.radius:
        o.radius = o.max_radius
    if o.desired_radius < o.min_radius:
        o.desired_radius = o.min_radius
    if o.max_radius < o.desired_radius:
        o.desired_radius = o.max_radius

    o.hspeed = approach(o.hspeed, o.dhspeed, o.accel)
    o.vspeed = approach(o.vspeed, o.dvspeed, o.accel)

    o.anglev = (o.anglev + o.vspeed) & 0xffff

    if o.approach_v:
        # The compare is unsigned on the raw u16s, so this does not take the
        # short way round the circle.
        if o.anglev < o.desired_anglev:
            if o.desired_anglev - o.anglev < 81:
                o.anglev = o.desired_anglev
            else:
                o.anglev = (o.anglev + 80) & 0xffff
        else:
            if o.anglev - o.desired_anglev < 81:
                o.anglev = o.desired_anglev
            else:
                o.anglev = (o.anglev - 80) & 0xffff

    if o.max_anglev < o.anglev:
        o.anglev = o.max_anglev
    if o.anglev < o.min_anglev:
        o.anglev = o.min_anglev

    o.angleh = (o.angleh + o.hspeed) & 0xffff

    if USE_TWEAKABLES[0]:
        angleh, anglev, radius = (TWEAK_ANGLE_H[0], TWEAK_ANGLE_V[0],
                                  TWEAK_RADIUS[0])
    else:
        angleh, anglev, radius = o.angleh, o.anglev, o.radius

    m = erotate_z(m, angleh)
    m = erotate_y(m, anglev)
    m = etranslate(m, [radius, 0.0, 0.0])
    m = erotate_x(m, 16384)
    m = erotate_y(m, 0xc000)

    if not STOP_UPDATING[0]:
        cam.cur.fov = TWEAK_ORBIT_FOV[0]
        cam.cur.td = o.radius
        cam.cur.fd = o.radius
        cam.cur.dof = 8.0

    set_camera_matrix(cam, m, elapsed)


def orbit_target(o):
    """0x001549c0. The car's physics Position at +96, or the camera's own
    CurrentKey.Target -- which is also at +96."""
    if o.car is not None:
        return o.car.pos
    return o.base.cam.cur.tgt


# ------------------------------------------------------------------ the rng


class Rng(object):
    def __init__(self):
        self.state = 0

    def seed(self, s):
        self.state = s & 0xffffffff

    def frand(self, scale):
        self.state = (self.state * 1103515245 + 12345) & 0xffffffff
        u = f32(f32(float(self.state >> 8)) * f32(1.0 / 8388608.0))
        u = f32(u - 1.0)
        return f32(u * scale)


class Car(object):
    def __init__(self):
        self.geopos = [0.0] * 4
        self.pos = [0.0] * 4
        self.body = mat_identity()


def rcar(rng, car, yaw, pitch, scale):
    car.geopos = [rng.frand(scale), rng.frand(scale), rng.frand(scale), 0.0]
    car.pos = [f32(car.geopos[i] + rng.frand(1.0)) for i in range(3)] + [0.0]
    car.body = erotate_y(erotate_z(mat_identity(), yaw), pitch)


# --------------------------------------------------------------- the output


class Out(object):
    def __init__(self):
        self.lines = []

    def __call__(self, s):
        self.lines.append(s)

    def v3(self, tag, v):
        self("  %s %s %s %s %s" % (tag, g9(v[0]), g9(v[1]), g9(v[2]),
                                   g9(v[3])))

    def mat(self, m):
        for r in range(4):
            self("    %s %s %s %s" % (g9(m[r * 4]), g9(m[r * 4 + 1]),
                                      g9(m[r * 4 + 2]), g9(m[r * 4 + 3])))

    def key(self, tag, k, with_matrix=True):
        self("  key %s" % tag)
        if with_matrix:
            self.mat(k.matrix)
        self.v3("pos", k.pos)
        self.v3("dir", k.dir)
        self.v3("tgt", k.tgt)
        self("  scal %s %s %s %s %s fov %u"
             % (g9(k.td), g9(k.fd), g9(k.dof), g9(k.nearz), g9(k.farz),
                k.fov))

    def cam(self, c):
        self.key("cur", c.cur)
        self.key("prev", c.prev)
        self.key("vel", c.vel, False)
        self("  cam elapsed %s last %08x dash %d car %d"
             % (g9(c.elapsed), c.last, c.dash, 1 if c.carnot else 0))

    def orbit(self, o):
        self("  orb r %s dr %s h %u v %u dv %u hs %d vs %d dhs %d dvs %d"
             % (g9(o.radius), g9(o.desired_radius), o.angleh, o.anglev,
                o.desired_anglev, o.hspeed, o.vspeed, o.dhspeed, o.dvspeed))
        self("  orb minr %s maxr %s minv %u maxv %u mult %s accel %d"
             " appr %d fe %d en %d"
             % (g9(o.min_radius), g9(o.max_radius), o.min_anglev,
                o.max_anglev, g9(o.radius_mult), o.accel, o.approach_v,
                o.femode, o.base.enabled))


# ---------------------------------------------------------------- scenarios


def s_ctor(o):
    o("scenario ctor")
    c = Camera()
    camera_init(c)
    o.cam(c)

    d = Camera()
    c.last = 0x12345678
    camera_copy(d, c)
    o("  copied")
    o.cam(d)


def s_setmatrix(o):
    o("scenario setmatrix")
    c = Camera()
    camera_init(c)
    rng = Rng()
    rng.seed(0x5a5a1234)

    m = mat_identity()
    for i in range(10):
        m = erotate_z(mat_identity(), (i * 4000 + 137) & 0xffff)
        m = erotate_x(m, (i * 9001) & 0xffff)
        m[12] = rng.frand(100.0)
        m[13] = rng.frand(100.0)
        m[14] = rng.frand(100.0)
        set_camera_matrix(c, m, f32(1.0 / 60.0))
        o("  frame %d" % i)
        o.cam(c)

    c.cur.td = 25.0
    c.cur.fd = 7.5
    c.cur.dof = 3.25
    c.cur.nearz = 0.125
    c.cur.farz = 9000.0
    c.cur.fov = 200
    set_camera_matrix(c, m, 0.5)
    o("  scalars moved")
    o.cam(c)

    c.cur.fov = 65500
    set_camera_matrix(c, m, 0.5)
    o("  fov wrapped")
    o.cam(c)
    c.cur.fov = 200
    set_camera_matrix(c, m, 0.25)
    o("  fov wrapped back")
    o.cam(c)

    c.cur.fov = 65500
    set_camera_matrix(c, m, 2.0)
    o("  fov half step")
    o.cam(c)
    c.cur.fov = 201
    set_camera_matrix(c, m, 2.0)
    o("  fov half step odd")
    o.cam(c)

    m = mat_identity()
    m[11] = 100.0
    m[14] = 1200.0
    set_camera_matrix(c, m, 1.0)
    o("  fourth column")
    o.cam(c)

    STOP_UPDATING[0] = 1
    m = mat_identity()
    m[12] = 999.0
    set_camera_matrix(c, m, 1.0)
    o("  frozen")
    o.cam(c)
    STOP_UPDATING[0] = 0


def s_orbitinit(o):
    o("scenario orbitinit")
    rng = Rng()
    rng.seed(0x0c0ffee1)
    car = Car()
    rcar(rng, car, 1000, 2000, 30.0)

    c = Camera()
    camera_init(c)
    orb = Orbit()
    use_view(0, c)
    orbit_init(orb, 0, car, 2)
    o.orbit(orb)
    o.cam(c)
    o("  type %s" % mover_type_name(orb.base.type))
    o.v3("target", orbit_target(orb))

    b = Mover()
    mover_init(b, -1, CM_DRIVE)
    o("  detached type %s view %d enabled %d camera %d pview %d"
      % (mover_type_name(b.type), b.viewid, b.enabled,
         1 if b.cam is not None else 0, 1 if b.view is not None else 0))

    camera_init(c)
    d = Orbit()
    use_view(3, c)
    orbit_init(d, 3, None, 0)
    o("  carless")
    o.orbit(d)
    o.v3("target", orbit_target(d))
    o("  carless listed %d first %d" % listed(d.base))

    for i in range(-1, 19):
        o("  name %2d %s" % (i, mover_type_name(i)))


def listed(m):
    """How many movers m's view holds, and whether m is the first."""
    ms = VIEW_MOVERS[m.viewid]
    return len(ms), 1 if ms and ms[0] is m else 0


def s_enable(o):
    o("scenario enable")

    def pmover(tag, m, c):
        o("  %s en %d movercar %d moverdash %d camcar %d camdash %d"
          " near %s far %s listed %d first %d"
          % ((tag, m.enabled, 1 if m.carnot else 0, m.dash,
              1 if c.carnot else 0, c.dash, g9(c.cur.nearz), g9(c.cur.farz))
             + listed(m)))

    c = Camera()
    camera_init(c)
    c.carnot = True
    c.dash = 7
    m = Mover()
    use_view(0, c)
    mover_init(m, 0, CM_STILL)
    pmover("constructed", m, c)

    c.carnot = False
    c.dash = 9
    mover_disable(m)
    pmover("disabled", m, c)

    c.dash = 11
    mover_disable(m)
    pmover("disabled twice", m, c)

    c.cur.nearz = 123.0
    mover_enable(m)
    pmover("re-enabled", m, c)

    c.cur.nearz = 456.0
    mover_enable(m)
    pmover("enabled twice", m, c)

    mover_disable(m)
    m.carnot = True
    m.dash = 33
    c.carnot = False
    c.dash = 0
    c.cur.nearz = 789.0
    STOP_UPDATING[0] = 1
    mover_enable(m)
    pmover("frozen enable", m, c)
    c.dash = 44
    mover_disable(m)
    pmover("frozen disable", m, c)
    STOP_UPDATING[0] = 0

    orb = Orbit()
    camera_init(c)
    c.carnot = True
    c.dash = 5
    use_view(0, c)
    orbit_init(orb, 0, None, 0)
    o("  orbit ctor camcar %d camdash %d fov %u handlers %d"
      % (1 if c.carnot else 0, c.dash, c.cur.fov, orb.handlers_added))

    camera_init(c)
    c.carnot = True
    c.dash = 5
    STOP_UPDATING[0] = 1
    use_view(0, c)
    orbit_init(orb, 0, None, 0)
    o("  orbit ctor frozen camcar %d camdash %d fov %u"
      % (1 if c.carnot else 0, c.dash, c.cur.fov))
    STOP_UPDATING[0] = 0


def s_orbitspin(o):
    o("scenario orbitspin")
    rng = Rng()
    rng.seed(0x1eaf00d)
    car = Car()
    rcar(rng, car, 0, 0, 10.0)
    c = Camera()
    camera_init(c)
    orb = Orbit()
    use_view(0, c)
    orbit_init(orb, 0, car, 0)

    for i in range(24):
        if i == 0:
            orb.dhspeed = ORBIT_JOY_SPEED
        if i == 8:
            orb.dhspeed = -ORBIT_JOY_SPEED
        if i == 16:
            orb.dhspeed = 0
        if i == 4:
            orb.dvspeed = 100
        if i == 12:
            orb.dvspeed = -100

        rcar(rng, car, (i * 2731) & 0xffff, (i * 512) & 0xffff, 0.0)
        car.geopos[0] = f32(float(i) * 1.5)
        car.geopos[1] = f32(float(i) * -0.25)
        car.geopos[2] = 0.5

        orbit_update(orb, f32(1.0 / 60.0))
        o("  spin %d" % i)
        o.orbit(orb)
        o.key("cur", c.cur)
        o.key("vel", c.vel, False)


def s_orbitlimits(o):
    o("scenario orbitlimits")
    rng = Rng()
    rng.seed(0xfeed5eed)
    car = Car()
    rcar(rng, car, 12345, 54321, 5.0)

    c = Camera()
    camera_init(c)
    orb = Orbit()
    use_view(0, c)
    orbit_init(orb, 0, car, 0)
    orb.max_radius = 12.0
    orb.min_radius = 2.0
    for i in range(40):
        orb.radius_mult = ZOOM_OUT if i < 20 else ZOOM_IN
        orbit_update(orb, f32(1.0 / 60.0))
        o("  zoom %d r %s dr %s td %s fd %s"
          % (i, g9(orb.radius), g9(orb.desired_radius), g9(c.cur.td),
             g9(c.cur.fd)))

    orb.radius_mult = 1.0
    orb.desired_radius = 6.0
    orbit_update(orb, f32(1.0 / 60.0))
    o("  held r %s dr %s" % (g9(orb.radius), g9(orb.desired_radius)))

    camera_init(c)
    use_view(0, c)
    orbit_init(orb, 0, car, 0)
    orb.dvspeed = 400
    orb.vspeed = 400
    for i in range(20):
        orbit_update(orb, f32(1.0 / 60.0))
        o("  up %d v %u" % (i, orb.anglev))
    orb.dvspeed = -400
    orb.vspeed = -400
    for i in range(20):
        orbit_update(orb, f32(1.0 / 60.0))
        o("  down %d v %u" % (i, orb.anglev))

    camera_init(c)
    use_view(0, c)
    orbit_init(orb, 0, car, 0)
    orb.min_anglev = 0
    orb.max_anglev = 65535
    orb.approach_v = 1
    orb.angleh = 0
    orb.anglev = 1000
    orb.desired_anglev = 1500
    for i in range(10):
        orbit_update(orb, f32(1.0 / 60.0))
        o("  appr up %d v %u" % (i, orb.anglev))
    orb.desired_anglev = 900
    for i in range(10):
        orbit_update(orb, f32(1.0 / 60.0))
        o("  appr down %d v %u" % (i, orb.anglev))

    orb.anglev = 1000
    orb.desired_anglev = 1080
    orbit_update(orb, f32(1.0 / 60.0))
    o("  appr exact80 %u" % orb.anglev)
    orb.anglev = 1000
    orb.desired_anglev = 1081
    orbit_update(orb, f32(1.0 / 60.0))
    o("  appr exact81 %u" % orb.anglev)

    orb.approach_v = 0
    orb.min_anglev = 60000
    orb.max_anglev = 1000
    orb.anglev = 30000
    orbit_update(orb, f32(1.0 / 60.0))
    o("  inverted window v %u" % orb.anglev)

    accel = orb.accel
    for gap in (accel - 1, accel, accel + 1):
        orb.hspeed = 0
        orb.dhspeed = gap
        orbit_update(orb, f32(1.0 / 60.0))
        o("  accel +%d -> %d" % (gap, orb.hspeed))
        orb.hspeed = 0
        orb.dhspeed = -gap
        orbit_update(orb, f32(1.0 / 60.0))
        o("  accel -%d -> %d" % (gap, orb.hspeed))


def s_tweakables(o):
    o("scenario tweakables")
    rng = Rng()
    rng.seed(0xabcdef01)
    car = Car()
    rcar(rng, car, 20000, 3000, 8.0)

    c = Camera()
    camera_init(c)
    orb = Orbit()
    use_view(0, c)
    orbit_init(orb, 0, car, 0)
    orb.dhspeed = 500
    orb.desired_radius = 3.0
    USE_TWEAKABLES[0] = 1
    for i in range(4):
        orbit_update(orb, f32(1.0 / 60.0))
        o("  tweak %d" % i)
        o.orbit(orb)
        o.key("cur", c.cur)
    USE_TWEAKABLES[0] = 0
    for i in range(4):
        orbit_update(orb, f32(1.0 / 60.0))
        o("  live %d" % i)
        o.orbit(orb)
        o.key("cur", c.cur)

    c.cur.fov = IN_GAME_FOV[0]
    o("  fov before %u" % c.cur.fov)
    orbit_update(orb, f32(1.0 / 60.0))
    o("  fov after %u (InGameFOV %u, TweakOrbitFOV %u)"
      % (c.cur.fov, IN_GAME_FOV[0], TWEAK_ORBIT_FOV[0]))

    STOP_UPDATING[0] = 1
    c.cur.fov = 111
    for _ in range(3):
        orbit_update(orb, f32(1.0 / 60.0))
    o("  frozen fov %u h %u" % (c.cur.fov, orb.angleh))
    STOP_UPDATING[0] = 0

    camera_init(c)
    use_view(0, c)
    orbit_init(orb, 0, None, 0)
    for i in range(3):
        orbit_update(orb, f32(1.0 / 60.0))
        o("  carless %d" % i)
        o.key("cur", c.cur)

    BOOM[0], BOOM[1], BOOM[2] = 1.0, 2.0, 3.0
    camera_init(c)
    use_view(0, c)
    orbit_init(orb, 0, car, 0)
    orbit_update(orb, f32(1.0 / 60.0))
    o("  offset")
    o.key("cur", c.cur)
    BOOM[0], BOOM[1], BOOM[2] = 0.0, 0.0, 0.0


SCENARIOS = [("ctor", s_ctor), ("setmatrix", s_setmatrix),
             ("orbitinit", s_orbitinit), ("enable", s_enable),
             ("orbitspin", s_orbitspin), ("orbitlimits", s_orbitlimits),
             ("tweakables", s_tweakables)]


def model():
    o = Out()
    for _name, fn in SCENARIOS:
        fn(o)
    return o.lines


# A mutation can turn a loop into one with no exit. With no deadline here
# that mutant runs until something kills it and stalls the whole pass; the
# harness itself runs in well under a second.
HARNESS_TIMEOUT = 60


def run_c(exe):
    # No pipe: a runaway harness cannot be drained and cannot be killed
    # reliably from Windows, which is how geometry_check deadlocked.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.txt"
        with open(path, "w", newline=NL) as fh:
            try:
                rc = subprocess.run([str(exe)], stdout=fh,
                                    stderr=subprocess.DEVNULL,
                                    timeout=HARNESS_TIMEOUT).returncode
            except subprocess.TimeoutExpired:
                sys.exit("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        if rc != 0:
            sys.exit("harness exited %d" % rc)
        with open(path, "r", newline=NL) as fh:
            return fh.read().split(NL)[:-1]


def diff(a, b, limit=40):
    bad = 0
    shown = 0
    for line in difflib.unified_diff(a, b, "port", "model", n=0, lineterm=""):
        if line[:1] in ("-", "+") and line[:3] not in ("---", "+++"):
            bad += 1
            if shown < limit:
                print(line)
                shown += 1
    return shown, bad // 2 if bad else 0


# ---------------------------------------------------------------- mutations
#
# One per behavioural claim the two modules make. A mutation that does not
# move a line is either an untested rule or an equivalent mutant, and the
# difference has to be worked out rather than assumed -- see CONTINUE.md.

CAM = "3DS Files/source/camera.c"
MOV = "3DS Files/source/cammover.c"

MUTATIONS = [
    ("prev-not-copied", CAM,
     "    c->PreviousKey = c->CurrentKey;", "    (void)prev;"),
    ("no-freeze-check", CAM,
     "    if (CameraStopUpdating)\n        return;", "    (void)0;"),
    ("transpose-column-kept", CAM,
     "    t.v2.w = 0.0f;", "    t.v2.w = t.v2.w;"),
    ("position-not-negated", CAM,
     "    cur->Position.x = 0.0f - cur->Position.x;",
     "    cur->Position.x = cur->Position.x;"),
    ("position-plain-negate", CAM,
     "    cur->Position.y = 0.0f - cur->Position.y;",
     "    cur->Position.y = -cur->Position.y;"),
    ("position-pad-plain-negate", CAM,
     "    cur->Position.pad = 1.0f - cur->Position.pad;",
     "    cur->Position.pad = -cur->Position.pad;"),
    ("direction-2d-length", CAM,
     "    d = d + t.v2.z * t.v2.z;", "    d = d + 0.0f;"),
    ("direction-unnormalised", CAM,
     "    k = 1.0f / sqrtf(d);", "    k = 1.0f;"),
    ("target-uses-focal", CAM,
     "cur->Direction.x * cur->TargetDistance;",
     "cur->Direction.x * cur->FocalDistance;"),
    ("velocity-not-per-second", CAM,
     "    inv = 1.0f / elapsed;", "    inv = 1.0f;"),
    ("velocity-times-elapsed", CAM,
     "    inv = 1.0f / elapsed;", "    inv = elapsed;"),
    ("fov-delta-signed", CAM,
     "uint16_t dfov = (uint16_t)(cur->FieldOfView - prev->FieldOfView);",
     "int dfov = (int)cur->FieldOfView - (int)prev->FieldOfView;"),
    ("fov-velocity-rounds", CAM,
     "(uint16_t)(int)((float)(int)dfov * inv)",
     "(uint16_t)(int)((float)(int)dfov * inv + 0.5f)"),
    ("fov-delta-reversed", CAM,
     "(uint16_t)(cur->FieldOfView - prev->FieldOfView)",
     "(uint16_t)(prev->FieldOfView - cur->FieldOfView)"),
    ("ctor-fov", CAM,
     "c->CurrentKey.FieldOfView = 14075;",
     "c->CurrentKey.FieldOfView = 14076;"),
    ("ctor-fourth-column", CAM,
     "m.v2.z = -1.0f;  m.v2.w = 100.0f;", "m.v2.z = -1.0f;  m.v2.w = 0.0f;"),
    ("ctor-one-setmatrix", CAM,
     "    camera_set_matrix(c, &m, 1.0f);\n    camera_set_matrix(c, &m, 1.0f);",
     "    camera_set_matrix(c, &m, 1.0f);"),
    ("ctor-target-distance", CAM,
     "c->CurrentKey.TargetDistance = 10.0f;",
     "c->CurrentKey.TargetDistance = 9.0f;"),
    ("ctor-near-z", CAM,
     "c->CurrentKey.NearZ = 0.5f;", "c->CurrentKey.NearZ = 0.25f;"),
    ("copy-keeps-last-time", CAM,
     "    dst->LastUpdateTime = 0x80000000u;",
     "    dst->LastUpdateTime = src->LastUpdateTime;"),

    ("approach-inclusive", MOV,
     "    return accel < diff ? stepped : want;",
     "    return accel <= diff ? stepped : want;"),
    ("approach-never-snaps", MOV,
     "    return accel < diff ? stepped : want;", "    return stepped;"),
    ("anglev-clamp-order", MOV,
     "    if (o->MaxAngleV < o->AngleV)\n        o->AngleV = o->MaxAngleV;\n"
     "    if (o->AngleV < o->MinAngleV)\n        o->AngleV = o->MinAngleV;",
     "    if (o->AngleV < o->MinAngleV)\n        o->AngleV = o->MinAngleV;\n"
     "    if (o->MaxAngleV < o->AngleV)\n        o->AngleV = o->MaxAngleV;"),
    ("approach-step-60", MOV,
     "o->AngleV = (uint16_t)(o->AngleV + 80);",
     "o->AngleV = (uint16_t)(o->AngleV + 60);"),
    ("approach-threshold-80", MOV,
     "if ((int)(o->DesiredAngleV - o->AngleV) < 81)",
     "if ((int)(o->DesiredAngleV - o->AngleV) < 80)"),
    ("radius-clamped-before-copy", MOV,
     "    o->Radius = o->DesiredRadius;\n"
     "    if (o->DesiredRadius < o->MinRadius)\n"
     "        o->Radius = o->MinRadius;",
     "    if (o->DesiredRadius < o->MinRadius)\n"
     "        o->DesiredRadius = o->MinRadius;\n"
     "    o->Radius = o->DesiredRadius;"),
    ("multiplier-on-radius", MOV,
     "        o->DesiredRadius = o->DesiredRadius * o->RadiusMultiplier;",
     "        o->Radius = o->Radius * o->RadiusMultiplier;"),
    ("rotate-order-swapped", MOV,
     "    eRotateZ(&m, &m, angleH);\n    eRotateY(&m, &m, angleV);",
     "    eRotateY(&m, &m, angleV);\n    eRotateZ(&m, &m, angleH);"),
    ("final-x-rotation", MOV,
     "    eRotateX(&m, &m, 16384);", "    eRotateX(&m, &m, 49152);"),
    ("final-y-rotation", MOV,
     "    eRotateY(&m, &m, 0xc000);", "    eRotateY(&m, &m, 0x4000);"),
    ("fov-is-ingame", MOV,
     "cam->CurrentKey.FieldOfView = OrbitTweakOrbitFOV;",
     "cam->CurrentKey.FieldOfView = OrbitInGameFOV;"),
    ("depth-of-field", MOV,
     "cam->CurrentKey.DepthOfField = 8.0f;",
     "cam->CurrentKey.DepthOfField = 4.0f;"),
    ("target-distance-desired", MOV,
     "cam->CurrentKey.TargetDistance = o->Radius;",
     "cam->CurrentKey.TargetDistance = o->DesiredRadius;"),
    ("boom-along-y", MOV,
     "    boom.x = radius;\n    boom.y = 0.0f;",
     "    boom.x = 0.0f;\n    boom.y = radius;"),
    ("carless-height-sign", MOV,
     "        m.v3.z = -OrbitTargetHeight;",
     "        m.v3.z = OrbitTargetHeight;"),
    ("car-translation-sign", MOV,
     "        trans.v3.x = -p->x;", "        trans.v3.x = p->x;"),
    ("mulmatrix-order", MOV,
     "        eMulMatrix(&m, &trans, &inv);",
     "        eMulMatrix(&m, &inv, &trans);"),
    ("tweakables-live-radius", MOV,
     "        radius = OrbitTweakRadius;", "        radius = o->Radius;"),
    ("ctor-anglev", MOV,
     "    o->AngleV = 0xf230;", "    o->AngleV = 0xf231;"),
    ("ctor-anglev-limits-swapped", MOV,
     "    o->MinAngleV = 0xc738;          /* 51000 */\n"
     "    o->MaxAngleV = 0xf8f4;          /* 63732 */",
     "    o->MinAngleV = 0xf8f4;\n    o->MaxAngleV = 0xc738;"),
    ("ctor-accel", MOV,
     "    o->MaxRotationAccel = 24;", "    o->MaxRotationAccel = 20;"),
    ("ctor-fov-ignores-freeze", MOV,
     "    if (!CameraStopUpdating) {\n"
     "        o->base.pCamera->CarNotToRender = 0;",
     "    if (1) {\n        o->base.pCamera->CarNotToRender = 0;"),
    ("disable-no-writeback", MOV,
     "    m->CarNotToRender = m->pCamera->CarNotToRender;\n"
     "    m->RenderDash = m->pCamera->RenderDash;",
     "    (void)m;"),
    ("disable-no-early-out", MOV,
     "    if (!m->Enabled)\n        return;\n    m->Enabled = 0;",
     "    m->Enabled = 0;"),
    ("enable-no-early-out", MOV,
     "    if (m->Enabled)\n        return;\n    m->Enabled = 1;",
     "    m->Enabled = 1;"),
    ("enable-near-behind-freeze", MOV,
     "    m->pCamera->CurrentKey.NearZ = 0.5f;",
     "    if (!CameraStopUpdating) m->pCamera->CurrentKey.NearZ = 0.5f;"),
    ("enable-no-attach", MOV,
     "    eview_attach_camera_mover(m->pView, &m->Node);", "    (void)0;"),
    ("disable-no-unattach", MOV,
     "    eview_unattach_camera_mover(m->pView, &m->Node);", "    (void)0;"),
    ("mover-view-zero", MOV,
     "    v = eGetView(viewID);", "    v = eGetView(0);"),
    ("mover-pview-zero", MOV,
     "    m->pView = v;", "    m->pView = eGetView(0);"),
    ("detached-pview-kept", MOV,
     "        m->pView = 0;", "        (void)0;"),
    ("mover-far-plane", MOV,
     "    cam->CurrentKey.FarZ = 5000.0f;",
     "    cam->CurrentKey.FarZ = 1000.0f;"),
    ("type-name-out-of-range", MOV,
     "    if ((unsigned)t >= sizeof MOVER_NAMES / sizeof MOVER_NAMES[0])\n"
     "        return MOVER_NAMES[0];",
     "    if ((unsigned)t >= sizeof MOVER_NAMES / sizeof MOVER_NAMES[0])\n"
     "        return MOVER_NAMES[4];"),
]


# Seven rules cannot be mutated into a different transcript by any scenario,
# and each one is an argument rather than a gap. They are listed here because
# a reader who works out the same thing next session should not have to do it
# twice, and because a survivor that is not on this list is a real hole.
#
#   the three FOV-difference mutations
#                                 VelocityKey's six scalars are identically
#                                 zero on the disc and cannot be anything
#                                 else. SetCameraMatrix copies CurrentKey
#                                 over PreviousKey as its first act and then
#                                 recomputes only Matrix, Position,
#                                 Direction and Target -- so by the time it
#                                 differences TargetDistance, FocalDistance,
#                                 DepthOfField, NearZ, FarZ and FieldOfView,
#                                 the two copies of each are the same word.
#                                 Every writer of those six (the movers, the
#                                 setters) writes before the call, never
#                                 between the copy and the subtraction. The
#                                 measurement is in the transcript: all 44
#                                 `key vel` records print
#                                 `scal 0 0 0 0 0 fov 0`. The u16 wrap and
#                                 the truncation are ported because they are
#                                 what the instructions say, not because
#                                 anything can reach them.
#
#   approach `<` -> `<=`          at a gap of exactly `accel` the step lands
#                                 exactly on `want`, so both arms agree. The
#                                 scenario walks gaps of accel-1, accel and
#                                 accel+1 and all three match by arithmetic.
#   approach-angle `< 81` -> 80   same argument one layer up: a gap of
#                                 exactly 80 is either snapped to or stepped
#                                 onto, and 1000 + 80 == 1080 either way.
#   clamp DesiredRadius first     Radius is a copy of DesiredRadius put
#                                 through the same two compares in the same
#                                 order, so clamping either one first gives
#                                 the same pair.
#   TargetDistance = Radius ->    and for the same reason the two are equal
#     DesiredRadius               by the time Update reads them. The zoom
#                                 transcript prints both on every frame and
#                                 they never disagree, which is the
#                                 measurement, not the claim.
EQUIVALENT = [
    "approach-inclusive", "approach-threshold-80",
    "radius-clamped-before-copy", "target-distance-desired",
    "fov-delta-signed", "fov-velocity-rounds", "fov-delta-reversed",
]


# The write, its OneDrive retry, and the journal that lets a killed pass be
# recovered from are all hostbuild's.
write_source = hostbuild.write_source


def mutate_pass(py_lines):
    survived = []
    skipped = []
    originals = {}
    paths = {}
    for _n, rel, _o, _r in MUTATIONS:
        if rel not in originals:
            paths[rel] = ROOT / rel
            # newline="" so the CRLF the ported sources carry survives the
            # round trip. write_source writes with newline="" too, so a
            # universal-newlines read here would quietly rewrite every
            # mutated file to LF and leave it that way after the restore.
            originals[rel] = paths[rel].read_text(encoding="utf-8",
                                                  newline="")
    try:
        for name, rel, old, new in MUTATIONS:
            src = paths[rel]
            text = originals[rel]

            # A multi-line pattern written with bare newlines misses every
            # time against a CRLF source -- and here that reads as "hits 0
            # times, skipped", which counts as a survivor rather than as a
            # mutation that never ran.
            crlf = (chr(13) + NL) in text
            old = old.replace(NL, chr(13) + NL) if crlf else old
            new = new.replace(NL, chr(13) + NL) if crlf else new

            if text.count(old) != 1:
                print("  %-34s pattern hits %d times, skipped"
                      % (name, text.count(old)))
                skipped.append(name)
                continue
            write_source(src, text.replace(old, new, 1))
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, SOURCES, name="camera_test")
                except SystemExit:
                    print("  %-34s did not compile (counts as caught)" % name)
                    write_source(src, text)
                    continue
                try:
                    got = run_c(exe)
                except SystemExit:
                    print("  %-34s crashed the harness (caught)" % name)
                    write_source(src, text)
                    continue
            write_source(src, text)
            _d, bad = diff(got, py_lines, limit=0)
            if bad:
                print("  %-34s caught, %d lines" % (name, bad))
            elif name in EQUIVALENT:
                print("  %-34s survived, equivalent by construction" % name)
                survived.append(name)
            else:
                print("  %-34s SURVIVED" % name)
                survived.append(name)
    finally:
        for rel, text in originals.items():
            try:
                write_source(paths[rel], text)
            except OSError:
                sys.exit("could not restore %s -- it still holds a mutation. "
                         "Put the original line back before trusting "
                         "anything printed above." % rel)
    return survived, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mutate", action="store_true",
                    help="break the C a rule at a time and re-diff")
    ap.add_argument("--dump", help="write both transcripts next to this path")
    a = ap.parse_args()

    ours = model()
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="camera_test")
        port = run_c(exe)

    if a.dump:
        for tag, lines in (("port", port), ("model", ours)):
            with open("%s.%s.txt" % (a.dump, tag), "w", newline=NL) as fh:
                fh.write(NL.join(lines) + NL)

    _d, bad = diff(port, ours)
    print("%d scenarios, %d lines, %d differ"
          % (len(SCENARIOS), len(port), bad))
    rc = 1 if bad else 0

    if a.mutate:
        if bad:
            print("not mutating while the baseline differs")
            return rc
        print("mutations:")
        survived, skipped = mutate_pass(ours)
        holes = [s for s in survived if s not in EQUIVALENT]
        # An entry whose mutant was caught is a wrong reason, not a spare
        # one. A skipped pattern never ran, so it is neither.
        stale = [n for n in EQUIVALENT
                 if n not in survived and n not in skipped]
        ran = len(MUTATIONS) - len(skipped)
        if skipped:
            print("%d PATTERNS SKIPPED -- the tally below is over %d of %d"
                  % (len(skipped), ran, len(MUTATIONS)))
        print("%d mutations, %d caught, %d equivalent, %d unexplained"
              % (ran, ran - len(survived),
                 len(survived) - len(holes), len(holes)))
        for s in holes:
            print("  SURVIVED: %s" % s)
        for name in stale:
            known = any(m[0] == name for m in MUTATIONS)
            print("  listed as equivalent but %s: %s"
                  % ("caught" if known else "names no mutation", name))
        rc |= 1 if (holes or skipped or stale) else 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
