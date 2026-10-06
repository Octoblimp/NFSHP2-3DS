#!/usr/bin/env python3
"""Cross-check 3DS Files/source/drivingchoice.c, the choices an AI car
makes about where to drive and the walk along the route that fills its
drive target (step 11b-2), and Race::GracePeriodIsActive in racecore.c,
against the retail image itself, run in mipsemu.

The model is the image. DrivingChoice's GetChoiceType (0x00241c00),
GetDrivingLine (0x00241c20), SetChoice with a type (0x00241cf8), with a
location (0x001cacc8) and with a choice (0x00245370), Clear (0x002453e0),
IsValid (0x00241d40), IsEqualTo (0x00241e30), IsEnoughRoom (0x00242b08),
FixupCarToExcludeFromCollisionPrediction (0x00243160),
GetPreferredSideOfCar (0x002432e8), FillUpDriveTarget (0x00243568),
AddToDriveTarget (0x002437e8), GetSpeedBackToLine (0x002438b0) and
ReduceCurrentL (0x00243988), the walk's AdvancePoint (0x00244588),
FuturePointList::Add (0x00244768), GetRoutePointsToUse (0x002447c0) and
the road-block list (0x00244c88), and Race::GracePeriodIsActive
(0x001492b0) run as shipped, over retail's own NearbyCarList::GetNearbyCar,
DrivingLocation's IsClear and AreWeInARelaxedSwitch,
GetCurrentCurvatureOfDrivingLine, TrackRoute::FindClosestPointAhead,
TrackRoutePoint's GetPosition and GetSignpost, Signpost's GetNewRoute and
GetNewRoutePoint, CalculateLookAheadDistance and DriveTarget's
AddPointToTarget and GetRouteAndRoutePoint. The harness
(tools/src/drivingchoice_test.c) runs the port over the same script, and
the two transcripts are diffed.

Later steps check more in the same way. Step 11b-3 adds BuildDriveTarget
and the way round a car. Step 11b-4a adds CarCollisionPredict
(carcollisionpredict.c). Step 11b-4b adds IsDriveable, TryChoice,
MakeNewChoice and TryToDriveAroundCar, over retail's own EstimateScore.
EstimateScore's distances are carried from one call to the next, as the
port's static array keeps them (EST_ENTRY). Step 11d-1 adds the five
small AI actions of aiactions.c (JustDrive, Draft, NudgeCar, Block and
AccidentRecovery) over retail's own AIAction base. They are run one at a
time in a slot at AB, through retail's vptrs, over a DrivingInformation
at INFO copied from the script's list, location and choice (the "@"
ops). Four more stubs serve them: the slot pool (bNewSlotPool,
bDeleteSlotPool, bOMalloc and bFree), DestoryTargetMarkers,
TopologyCoordinate::GetElevation (0x00152070), which answers the
script's normal under the car, and Car::PleaseResetMeLater (0x00133070).
Step 11d-2 adds Pass and AvoidCars, with one more stub: the
GetDriverNumber of a test CarDriver table at DVT, which every car's driver
has, answering the car's DriverNumber. Step 11d-3a adds PullOver and
IJustGotHit. CalculateMaxAcceleration (0x001cce50) and
CalculateMaxDeceleration run as shipped over each car's type info (its
mass, grip, downforce, drag and limiter), a ride info of car type 0 and
a two-entry acceleration table for that type. PullOver's score reads the
chopper (World+24), the cop manager's cops and the players, and both
walk my car's collisions through three more stubs:
CollisionBody::GetCollision (0x001d6f38), Collision::IsTwoCarCollision
(0x0021eb20) and Collision::GetCollidingCars (0x0021eb48), which answer
the script's collisions for the car whose body it is.

Three stubs, each of which prints a line, so the two sides must ask them
the same questions in the same order:
  AICarController::SignPostDecision (0x00191de0), which the port reaches
    through gAISignPostDecisionFn until step 11e, answers the script's
    take-or-not for the sign, and writes the script's line, if any, to the
    line it is handed;
  Car::GetRoutePoint (0x001332d8) answers the script's point for the car;
  Car::GetAmountOutOfBounds (0x00133308) answers the script's amount.
The port reaches the last two through the controller's vtable.

The cars are retail's at retail's offsets: the driver number, the car
class (CarTypeInfo 230), the driver's type (DriverInfo 8), the control
mode, the position, the body's x axis and the speed, and each car's
controller with its own location, its choice and its current action's
type (AIAction 588) or none. The routes are filed in TheTrackRouteManager
under their numbers, and the signs in SignpostArray.

A float prints as its bits, a NaN as "nan", and a pointer by what it is:
c3 a car, k3 its controller, L3 its location, ch3 its choice, e5 the
list's sixth entry, R1 a route, R1:17 a point, S4 the fifth sign, loc the
location, pat the 0xa5 fill.

    python tools/drivingchoice_check.py
    python tools/drivingchoice_check.py --mutate [--only a,b]
    python tools/drivingchoice_check.py --dump out/drivingchoice
"""
import argparse
import math
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild
import mutpar
import physicscar_check as pcc
import retail_model
from mipsemu import M32, f_to_bits, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/drivingchoice_test.c"
DCC = "3DS Files/source/drivingchoice.c"
RCC = "3DS Files/source/racecore.c"
CCP = "3DS Files/source/carcollisionpredict.c"
DT = "3DS Files/source/drivetarget.c"
AIA = "3DS Files/source/aiaction.c"
AAS = "3DS Files/source/aiactions.c"
SOURCES = [HARNESS, DCC, RCC, CCP, AIA, AAS] + ["3DS Files/source/" + f for f in (
    "nearbycar.c", "drivinglocation.c", "drivetarget.c", "obb.c", "car.c",
    "carstate.c", "carinfo.c", "cartypeinfo.c", "langtab.c", "drivetrain.c",
    "engine.c", "wheel.c", "suspension.c", "steering.c", "rigidbody.c",
    "table.c", "trackroute.c", "trackpath.c", "quickspline.c", "bchunk.c",
    "world.c", "graph.c", "race.c", "copmanager.c", "replay.c", "p32.c",
    "bmem.c", "vtable.c", "emath.c", "bmatrix.c", "bvector.c", "bmath.c",
    "bmathtab.c")]

HARNESS_TIMEOUT = 120

# ================================================================ the image

GP = 0x003358f0
GET_CHOICE_TYPE = 0x00241c00
GET_DRIVING_LINE = 0x00241c20
SET_CHOICE = 0x00241cf8
SET_CHOICE_LOC = 0x001cacc8
SET_CHOICE_CHOICE = 0x00245370
CLEAR = 0x002453e0
IS_VALID = 0x00241d40
IS_EQUAL = 0x00241e30
ENOUGH_ROOM = 0x00242b08
FIXUP = 0x00243160
PREFERRED = 0x002432e8
FILL_UP = 0x00243568
ADD_TO_TARGET = 0x002437e8
SPEED_BACK = 0x002438b0
REDUCE = 0x00243988
ADVANCE = 0x00244588
FPL_ADD = 0x00244768
POINTS_TO_USE = 0x002447c0
UP_TO = 0x00244c88
GRACE = 0x001492b0
BUILD = 0x00241ea0
AROUND = 0x00243aa8
PARALLEL = 0x00243f70
CLEARANCE = 0x002442c0
SEARCH = 0x00244d80
SMOOTH = 0x00244ea0
# DoSmoothOffsetChange's slope, the one divide the script takes by zero:
# the model runs with the EE's divide, and no other site may take it.
SMOOTH_DIV = 0x00245050

# CarCollisionPredict (step 11b-4a).
WHO = 0x001e5e60
WILL = 0x001e60a0
STOPPED = 0x001e6010
MAKE_OBBS = 0x001e6860
WHEN_2D = 0x001e72f8
TISA = 0x001e7238
OVERLAP = 0x001e6ac0
# WillIHitThisCar's steps along each car's leg, which divide by a leg of 0
# when a car is at its next point.
WILL_DIVS = {0x001e65ec, 0x001e65f4}

# Choosing a new choice (step 11b-4b).
IS_DRIVEABLE = 0x00241ff8
TRY_CHOICE = 0x002428d0
MAKE_NEW = 0x00242170
AROUND_CAR = 0x00242c20
# A choice made among many cars runs the walk and the prediction a few
# dozen times over.
CHOOSE_LIMIT = 400000000
# EstimateScore's two, which a car at rest takes and drivetarget.c spells
# ee_div (tools/drivetarget_image_check.py).
EST_DIVS = {0x0021d204, 0x00258914}
# SetDesiredSpeedSlowerThanThisCar's, for a car keeping pace (aiaction.c
# spells it ee_div; nearbycar_check's s_ai covers it). AvoidCars reaches
# it behind a car level with mine.
SLOWER_DIV = 0x001c6520
# EstimateScore's entry and its one jr ra. Its 20 distances are a stack
# array written only from the first point on, and IsDriveable's scratch
# target, rebuilt choice after choice in one frame, keeps the first choice's
# cached pick: a shorter target then scores off the distance the last call
# left. drivetarget.c keeps the array static. The model leaves retail's own
# stack alone from one call to the next at the same depth inside one op, so
# anything there that overwrote the words would show, and carries the last
# call's 80 bytes into a frame anywhere else.
EST_ENTRY = 0x0021c920
EST_RET = 0x0021cf2c
EST_FRAME = 304
# MakeNewChoice's current choice, at sp+1696 in its 1984-byte frame, which
# retail never clears: a location whose line gives no choice (a negative
# odd line) leaves it as the stack had it. drivingchoice.c clears it, and
# the model clears it on the way in.
MAKE_NEW_CURRENT = 1696 - 1984

# DriveTarget's MinDistanceToPoint and its square, which the image's
# start-up code (0x0020ab48) works out and the emulator does not run.
MIN_DIST = 0x00331a48
MIN_DIST_SQ = 0x003324d4

SIGN_DECISION = 0x00191de0
GET_ROUTE_POINT = 0x001332d8
GET_OOB = 0x00133308

ROUTE_TABLE = 0x00314438 + 16     # TheTrackRouteManager.pTrackRoutes
NUM_ROUTE_SLOTS = 100

GLOBALS = {
    "TIMER": GP - 19576,          # WorldTimer
    "RACE": GP - 22272,           # pCurrentRace
    "GRACE": GP - 22256,          # StartOfRaceGracePeriod
    "GAP": GP - 22252,            # TimeBetweenCarsForGracePeriodExit
    "WILLIAMS": GP - 15128,       # WilliamsAITuningMode
    "SECS": GP - 20328,           # AIDriverSecondsToLookAhead
    "DEF": GP - 20324,            # AIDriverDefaultLookAhead
    "SIGNS": GP - 18376,          # SignpostArray
    "NSIGNS": GP - 18372,         # NumSignposts
    "TRAFFIC": GP - 15152,        # AITrafficTuningMode
    "SLOWCAR": GP - 15120,        # AISlowCarSpeed
    "SLOWTRAFFIC": GP - 15116,    # AISlowTrafficSpeed
    "WORLD": GP - 22120,          # pCurrentWorld
    "MINSPEED": GP - 15136,       # TryToDriveAroundCarMinSpeedForDrivingLine
    "NLINES": GP - 20136,         # AICarControllerNumDrivingLinesToConsider
    "POOL": GP - 18288,           # AIActionSlotPool
    "AVOID": GP - 18168,          # AIDriverAvoidCarsImpactTimeThreshold
    "PASS": GP - 18164,           # AIActionPassMaxTimeAheadToMakeAttempt
    "CAM": GP - 21528,            # CameraFollowThisCarInstead
    "HROUTE": GP - 18316,         # HighlightDrivingLineInRouteNumber
    "HLINE": GP - 18312,          # HighlightDrivingLineNumber
    "COPM": GP - 15620,           # pCopManager
    "PLAYERS": GP - 20928,        # PlayerPlayersByIndex, two words
    "NPLAYERS": GP - 20920,       # PlayerNumPlayers
}

CARS = 0x01010000
CAR_STRIDE = 0x1000
NCARS = 16
CTRLS = 0x01020000
CTRL_STRIDE = 0x400
CHOICES = 0x01030000
ACTIONS = 0x01031000
ACTION_STRIDE = 608
LOCS = 0x01034000
CTIS = 0x01040000
CTI_STRIDE = 0x400
DRIVERS = 0x01048000
DRIVER_STRIDE = 32
CDRIVERS = 0x01060000             # each car's CarDriver, its target first
CDRIVER_STRIDE = 0x400
PLAYERS = 0x01070000              # a player, never read
PLAYER_STRIDE = 16
VEC = 0x01091a00
LIST = 0x01090000
LOC = 0x01090c00
CHOICE = 0x01091000
OTHER = 0x01091010
FPL = 0x01091400
LPTR = 0x01091800
WALK = 0x01091900
TARGET = 0x01092000
RACE = 0x01093000
SIGNS = 0x01094000
NSIGNS = 32
SIGN_SIZE = 12
OBBS = 0x01095000                 # MakeOBBsForDriveTarget's twenty boxes
OBB_A = 0x01096000
OBB_B = 0x01096100
VEC_D = 0x01096200
VEC_V = 0x01096210
OUT = 0x01096300                  # the out floats
BEST_CH = 0x01091020               # TryChoice's best and its way round
ROUND_CH = 0x01091030
TARGET2 = 0x01097000
TARGET3 = 0x01097400
# The words the choosing writes through: found, its out, the best score,
# the way round's time, the car hit and when, IsDriveable's score and
# MakeNewChoice's and TryToDriveAroundCar's out.
O_FOUND = 0x01096320
O_BOUT = O_FOUND + 4
O_BSCORE = O_FOUND + 8
O_RTIME = O_FOUND + 12
O_HCAR = O_FOUND + 16
O_HTIME = O_FOUND + 20
O_SCORE = O_FOUND + 24
O_OUT = O_FOUND + 28
WORLD = 0x01098000
BODIES = 0x010a0000               # each car's collision body
BODY_STRIDE = 0x200
ROUTES = 0x01100000
ROUTE_STRIDE = 0x20000
NROUTES = 6

# Step 11d-1's: the five actions' constructors and static CalculateScores,
# AIAction::UpdateStatus, AccidentRecovery's SortOfParallelToTrack, and the
# three they reach that are stubbed.
ACT_CTORS = {"jd": 0x001c73c0, "dr": 0x001c7690, "nc": 0x001c8028,
             "bl": 0x001c8160, "ar": 0x001ca1f0, "pa": 0x001c78f8,
             "ac": 0x001c6ba0, "po": 0x001c8298, "ij": 0x001c9c68}
ACT_SCORES = {"jd": 0x001c7458, "dr": 0x001c7720, "nc": 0x001c80d8,
              "bl": 0x001c8210, "ar": 0x001ca2a8, "pa": 0x001c79d8,
              "ac": 0x001c6cf8, "po": 0x001c8400, "ij": 0x001c9d20}
UPDATE_STATUS = 0x001c6a98
AR_PARALLEL = 0x001ca2f0
GET_ELEVATION = 0x00152070        # TopologyCoordinate::GetElevation
RESET_LATER = 0x00133070          # Car::PleaseResetMeLater
POOL_FREE = 0x00257ca0            # bSlotFree, which AIAction's delete reaches
# Step 11d-2's: Pass's SideOfCarIsOkay, AvoidCars' GetCarToAvoid, the test
# CarDriver table with its stubbed GetDriverNumber, and where the two
# scores' outs go: the car, the choice (+16), the seconds (+32), okay (+36)
# and the side used (+40).
SIDE_OK = 0x001c7e28
GET_CAR_TO_AVOID = 0x001ca9e8
DVT = 0x010b3000
DVT_BYTES = 0x100
DVT_DNUM = 80                     # GetDriverNumber's entry
STUB_DNUM = 0x010b3100
SC_OUT = 0x010b3200
SC_OUT_BYTES = 44
CD_VPTR = 556                     # a CarDriver's vptr
C_BLINK = 2144                    # BlinkTimer, and BlinkDuration after it
# Their tables and AIAction's and AIPlan's, by the names the harness gives
# the demo's.
ACT_VTABLES = {0x002b7b10: "vJD", 0x002b7bd0: "vDR", 0x002b7b90: "vNC",
               0x002b7b50: "vBL", 0x002b79d0: "vAR", 0x002b7c90: "vAA",
               0x002b7cd0: "vPL", 0x002b7c10: "vPA", 0x002b7c50: "vAC",
               0x002b7ad0: "vPO", 0x002b7a10: "vIJ"}
AB = 0x010b0000                   # the action, in a slot of the pool's size
AB_BYTES = 640
INFO = 0x010b1000                 # its DrivingInformation
INFO_BYTES = 492
POOL = 0x010b2000                 # what AIActionSlotPool holds
# The action's fields the script pokes.
ACT_FIELDS = {"can": 0, "exp": 4, "dt": 8, "st": 12, "pt": 560, "ds": 564,
              "tt": 568, "tol": 572, "udl": 576, "tb": 580, "bo": 584,
              "t608": 608, "r612": 612, "o616": 616, "o620": 620,
              "o624": 624, "o628": 628, "o632": 632}

# Step 11d-3a's. The three Collision calls, stubbed, and each car's
# collisions they answer from: whether two cars', and its two cars.
GET_COLLISION = 0x001d6f38        # CollisionBody::GetCollision
IS_TWO_CAR = 0x0021eb20           # Collision::IsTwoCarCollision
COLLIDING_CARS = 0x0021eb48       # Collision::GetCollidingCars
COLLS = 0x010b5000
NCOLLS = 4
COLL_STRIDE = 16
B_NCOLL = 18                      # CollisionBody's NumCollisions, a byte
# PullOver's CalculatePointsToDrive, whose choice at sp+0 of its 720-byte
# frame retail never clears past the timeout: a location whose line gives
# no choice leaves it as the stack had it. aiactions.c clears it, and the
# model clears it on the way in.
PO_CPTD = 0x001c86a8
PO_CHOICE = -720
# What PullOver's score reads: the chopper, at World+24 (its Plan and
# CurrentPos), the cop manager (gp-15620: its count of AI cops at 4 and
# Cops[7] at 16; a cop's car at 4 and DesiredLogicState at 16), and the
# players (gp-20928, two of them, each car at 4; their count gp-20920).
W_CHOPPER = 24
CHOPPER = 0x010b4000
CH_PLAN = 728
CH_POS = 832
COPM = 0x010b4400
COPS = 0x010b4500
COP_STRIDE = 32
NCOPS = 7
PLOBJ = 0x010b4800
PLOBJ_STRIDE = 64
# Every car's ride info (car type 0), and type 0's acceleration table in
# TheCarTypeAccelerationTable: two entries, {0, 1} over 0 to 100.
RIDE = 0x010b4c00
ACCEL = 0x0030daf0
ACCEL_TABLE = 128
BELT_COEF = GP - 16600            # BeltMover's fBeltAccelCoef
C_RIDE = 16
C_BOOST = 992
C_LIGHTS = 2056                   # the cop lights' word
DRV_SKILL = 3                     # DriverInfo's SkillLevel, a byte
# CarTypeInfo's: the body's mass, the two tyres' grip, the drag, the two
# downforces and the speed limiter, and what set_car gives each car.
CTI_FIELDS = (("mass", 480), ("drag", 752), ("limiter", 800),
              ("mu0", 428), ("mu1", 460), ("fdown", 756), ("rdown", 760))
CTI_DEFAULT = {"mass": 1500.0, "drag": 0.0, "limiter": 150.0, "mu0": 1.0,
               "mu1": 1.0, "fdown": 0.0, "rdown": 0.0}

# The car, at retail's offsets.
C_DN = 10
C_CTI = 12
C_DRIVER = 20
C_PLAYER = 24
C_CTL = 32
C_CTRL = 40
C_CDRIVER = 44
C_POS = 96
C_VEL = 112
C_BM = 144
C_NW = 956
C_UP = 176                        # BodyMatrix's z axis
C_TC = 1312                       # TheTopologyCoordinate, retail's
C_FS = 960
C_VMAG = 964
C_BODY = 52
C_ACC = 128
C_ANGLE = 932
B_MIN = 224
B_MAX = 240
W_ID = 408
W_PDT_ID = 412
OBB_SIZE = 80
NOBBS = 20
CTI_CLASS = 230
DRV_TYPE = 8
K_LOC = 504
K_CHOICE = 508
K_EXCLUDE = 516
K_ACTION = 532
A_TYPE = 588
RACE_START = 12

NC_SIZE = 28
LIST_ARRAY = 8
LIST_MAX = 16
LIST_HL = 456
LIST_HD = 460
FP_SIZE = 20
FPL_MAX = 20
FPL_BYTES = 4 + FP_SIZE * FPL_MAX
TARGET_BYTES = 528

RT_HEADER = 1064
RT_POINT = 112
LINES = 21

PATTERN = 0xa5
PAT32 = 0xa5a5a5a5

TRAFFIC_DRIVER = 3
RACER = 2
TRAFFIC_CONTROL = 3


def fb(v):
    if isinstance(v, int):
        return v & M32
    return f_to_bits(v)


def h(v):
    return "%08x" % fb(v)


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def fx(w):
    """A float's bits, with every NaN the one "nan"."""
    w &= M32
    if (w & 0x7f800000) == 0x7f800000 and (w & 0x7fffff):
        return "nan"
    return "%08x" % w


def s8(v):
    v &= 0xff
    return v - 0x100 if v & 0x80 else v


def s16(v):
    v &= 0xffff
    return v - 0x10000 if v & 0x8000 else v


def car_at(k):
    return CARS + CAR_STRIDE * k


def route_at(k):
    return ROUTES + ROUTE_STRIDE * k


# ============================================================ the scenarios
#
# Set up, and not echoed:
# U k n rn type f0..f20  route k's header: n points, number rn, its Type and
#                        the 21 lines' flags; filed under rn if 0 <= rn < 100
# P w0 .. w27            the route's next point
# K i rn j               sign i: the route numbered rn, its point j
# C k w0 .. w16          car k (CAR_FIELDS), its controller, choice and
#                        action; the car it excludes is set to the fill
#
# Echoed:
# G name word            a global (GLOBALS)
# Q i take line          SignPostDecision for sign i: its answer, and the
#                        line it writes (-1 none)
# R t                    the race's StartTime
# N me n hl hd           the list's car (-1 none), count and half sizes
# E i px py vx vy L D k  the list's entry i
# D r j line t           the location set by hand (r, j -1 for NULL)
# T tt len               the target emptied: TType tt, Length len,
#                        LastPointToScore -1, the rest 0
# Y x y z rn j line sp   a point put on the target by hand
# X type k extra         the choice by hand (k -1 NULL)
# O type k extra         the other choice by hand
# W r j pn line off x    the walker: route r's point j, its number pn, the
#                        line, the offset and the crossed flag
# F                      the future point list filled with 0xa5, count 0
# H k tt len pk ct pt    car k's own target emptied: TType tt, Length len,
#                        LastPointToScore -1, the picked point pk and its
#                        two times, the rest 0
# I k x y z rn j line sp a point put on car k's target by hand
#
# The calls:
# a line                 GetChoiceType
# b type k               GetDrivingLine for car k
# c type k extra         SetChoice
# d                      SetChoice from the location
# e                      SetChoice from the other choice
# f                      Clear
# g                      IsValid, with the location and the list
# h                      IsEqualTo the other choice
# i e                    IsEnoughRoom beside entry e
# j k check              FixupCarToExcludeFromCollisionPrediction, car k
# k e                    GetPreferredSideOfCar of entry e
# m rn j line off x      FuturePointList::Add
# n                      AdvancePoint of the walker, for the list's car
# o                      GetRoutePointsToUse, *L filled with 0xa5 first
# p r j                  the road-block list, up to route r's point j
# q m                    GetSpeedBackToLine
# r l m r j line a hw in ReduceCurrentL
# s l e                  AddToDriveTarget of the list's point e
# t m in [z]             FillUpDriveTarget; z's bits make the location,
#                        the target and the list NULL (1, 2, 4)
# u k                    GracePeriodIsActive for car k
# v m                    BuildDriveTarget
# w                      BuildDriveTargetAroundCar
# x px py start          the future point list's closest point ahead
# y e idx                the clearance beside entry e (-1 NULL)
# z idx from to in       DoSmoothOffsetChange
# M side                 MakeDriveTargetParallelToCar
#
# CarCollisionPredict's (step 11b-4a). Set up, and echoed:
# A k ax ay vz ang mn mx car k's acceleration, its velocity's z, its angle
#                        and its collision body's box (three words each)
# Z k c                  car k's controller leaves out car c (-1 NULL)
# S n                    the target's NumPoints by hand
# The calls:
# 1 a0 a1 b0 b1          IntervalOverlap
# 2 v d r                TimeIntervalForSeparatingAxis
# 3 a b dx dy vx vy      WhenWillOverlapOccur2D; each box is six words:
#                        A0's and A1's x and y, a0 and a1
# 4 t c scale z          MakeOBBsForDriveTarget of the target (t -1) or car
#                        t's own, for car c (-1 NULL); z's bits make the
#                        target and the boxes NULL (1, 2)
# 5 e                    IsThisCarStoppedDirectlyInFrontOfMe, entry e
# 6 k max                WillIHitThisCar: the list's car on the target,
#                        and car k
# 7 max z                WhoWillThisDriveTargetHit; z's 1 makes the
#                        location NULL
#
# Choosing a new choice (step 11b-4b), each dumping what it leaves after
# it: the car the list's car leaves out, and the world's
# CollisionPredictionID and PotentialDriveTargetID.
# 8 pref m max           IsDriveable of the choice into the target
# 9 pref max found best round way
#                        TryChoice of the choice, into the target: *found,
#                        the best score and the way round's time as
#                        given, car `way` (-1 NULL) in the way; the best
#                        and the way round, their targets, the best's out
#                        and the hit filled with 0xa5 first
# 0 max try out          MakeNewChoice, *out as given
# V e max try out        TryToDriveAroundCar of entry e, *out as given
#
# What the image would read from wherever a NULL or a stray pointer lands
# is not scripted: a side-of-car choice always has a car, IsEnoughRoom's
# entry and a fix-up's car are on the list or out of bounds by no less than
# -0.001, a walk's routes are filed under their own numbers, the signs only
# lead on to a later route, so no walk goes round for ever, a road-block
# list ends on the location's route, and the walks start from a location
# that is set and a line from 0 to 20 (drivingchoice.c names each of the
# image's ways the other side of these).

CAR_FIELDS = (
    "px", "py", "pz", "bx", "by", "vmag", "dn", "cls", "dtype", "ctl",
    "oob", "rpr", "rpj", "ct", "cc", "cx", "act", "pl", "nw", "vx", "vy",
    "fs")
CAR_FLOATS = ("px", "py", "pz", "bx", "by", "vmag", "oob", "vx", "vy",
              "fs")


def car_op(k, v):
    out = []
    for f in CAR_FIELDS:
        if f in CAR_FLOATS:
            out.append(h(f32(v[f])))
        else:
            out.append("%d" % int(v[f]))
    return "C %d %s" % (k, " ".join(out))


def lay(rnd, k, n, rn, rtype=0, signs=None, x=None, y=None, hd=None,
        turn=None, flags=None, smooth=False):
    """Route k: its header, its points and, for placing things beside it,
    each point's position, direction, widths and line offsets. A smooth
    route's points are 10 m apart, it turns by exactly `turn` at each and
    every line is on its centre, so its curvature is sin(6 turn)."""
    signs = signs or {}
    if x is None:
        x = rnd.uniform(-200.0, 200.0)
    if y is None:
        y = rnd.uniform(-200.0, 200.0)
    if hd is None:
        hd = rnd.uniform(-math.pi, math.pi)
    if turn is None:
        turn = rnd.choice((0.0, 0.03, -0.03, 0.15, -0.15,
                           rnd.uniform(-0.3, 0.3)))
    if flags is None:
        flags = [rnd.choice((0, 1, 2, 3, 0, 1, 4, 0x101))
                 for _ in range(LINES)]
    pos = []
    for i in range(n):
        pos.append((f32(x), f32(y)))
        if smooth:
            s = 10.0
            hd += turn
        else:
            s = rnd.uniform(6.0, 18.0)
            hd += turn + rnd.uniform(-0.04, 0.04)
        x += s * math.cos(hd)
        y += s * math.sin(hd)
    out = ["U %d %d %d %d %s" % (k, n, rn, rtype,
                                 " ".join("%x" % f for f in flags))]
    pts = []
    for i in range(n):
        px, py = pos[i]
        if i + 1 < n:
            nx, ny = pos[i + 1]
        else:
            nx = px + (px - pos[i - 1][0])
            ny = py + (py - pos[i - 1][1])
        dx, dy = nx - px, ny - py
        ln = math.hypot(dx, dy) or 1.0
        offs = [0] * LINES if smooth else [
            rnd.choice((0, rnd.randint(-1024, 1024), rnd.randint(-300, 300)))
            for _ in range(LINES)]
        if smooth:
            lw = rw = f32(25.0)
        else:
            lw = f32(rnd.uniform(4.0, 16.0))
            rw = f32(rnd.uniform(4.0, 16.0))
        bits = (rnd.getrandbits(32) & ~0xff) | signs.get(i, 0xff)
        raw = struct.pack("<12f", px, py, rnd.uniform(-5.0, 5.0),
                          f32(dx / ln), f32(dy / ln), f32(ln), lw, rw,
                          0.0, 0.0, rnd.uniform(0.0, 3000.0), 0.0)[:44]
        raw += struct.pack("<I", bits)
        raw += struct.pack("<21h", *offs)
        raw += bytes(rnd.randrange(256) for _ in range(LINES)) + bytes([k])
        assert len(raw) == RT_POINT
        out.append("P " + " ".join("%08x" % v for v in
                                   struct.unpack("<28I", raw)))
        pts.append(dict(x=px, y=py, dx=f32(dx / ln), dy=f32(dy / ln),
                        lw=lw, rw=rw, offs=offs, rn=rn))
    return out, pts


def off_of(p, line):
    return p["offs"][line] / 256.0


def beside(p, lat, along=0.0):
    """Where `lat` to the right of point p and `along` past it is."""
    return (p["x"] + lat * p["dy"] + along * p["dx"],
            p["y"] - lat * p["dx"] + along * p["dy"])


class World(object):
    """A scenario's routes, signs and cars, as ops."""

    def __init__(self, rnd):
        self.rnd = rnd
        self.ops = []
        self.pts = {}
        self.rn = {}
        self.cars = {}
        self.nsign = 0
        self.sign_points = []
        self.sign_to = []

    def route(self, k, n, rn, rtype=0, signs=None, **kw):
        ops, pts = lay(self.rnd, k, n, rn, rtype, signs, **kw)
        self.ops += ops
        self.pts[k] = pts
        self.rn[k] = rn
        return pts

    def sign(self, k2, j2):
        i = self.nsign
        self.nsign += 1
        self.ops.append("K %d %d %d" % (i, self.rn[k2], j2))
        self.sign_to.append((k2, j2))
        return i

    def car(self, k, **kw):
        rnd = self.rnd
        a = rnd.uniform(-math.pi, math.pi)
        v = dict(px=rnd.uniform(-150.0, 150.0),
                 py=rnd.uniform(-150.0, 150.0),
                 pz=rnd.uniform(-3.0, 3.0), bx=math.cos(a), by=math.sin(a),
                 vmag=rnd.choice((0.0, 10.0, 26.8, rnd.uniform(0.0, 60.0),
                                  rnd.uniform(20.0, 40.0))),
                 dn=rnd.choice((0, 1, 5, 100, 101, 120, 149, 150, -3)),
                 cls=rnd.randint(0, 8),
                 dtype=rnd.choice((0, 1, 2, 2, 3, 3, 4)),
                 ctl=rnd.choice((0, 1, 2, 3, 3, 4)),
                 oob=rnd.choice((0.0, -0.001, -0.0011, -0.5, -4.0, 1.0)),
                 rpr=-1, rpj=-1, ct=0, cc=-1, cx=0,
                 act=rnd.choice((-1, 0, 5, 6, 6, 11)))
        # Drawn from nothing, so the scenarios before these were added
        # draw what they drew.
        v.update(pl=0, nw=4, vx=math.cos(a), vy=math.sin(a), fs=0.0)
        v.update(kw)
        self.cars[k] = v
        self.ops.append(car_op(k, v))
        return v


def tgt_point(w, k, j, lat, line, sp=0.0, along=0.0):
    p = w.pts[k][j]
    x, y = beside(p, lat, along)
    return "Y %s %s %s %d %d %d %s" % (h(f32(x)), h(f32(y)),
                                        h(f32(w.rnd.uniform(-2.0, 2.0))),
                                        w.rn[k], j, line, h(f32(sp)))


def s_small(rnd):
    """The small methods, on every type and line worth trying."""
    w = World(rnd)
    ops = w.ops
    for k in range(4):
        w.car(k, cls=rnd.choice((0, 3, 8, -1, 127, -128)))
    for line in list(range(-5, 25)) + [0x7fffffff, -0x80000000, -7, 41]:
        ops.append("a %d" % line)
    for t in range(-2, 9):
        for k in range(4):
            ops.append("b %d %d" % (t, k))
    for t in list(range(-1, 9)) + [0x7fffffff]:
        for k in (-1, 0, 2):
            for x in (0, 1, 2):
                ops.append("X %d %d %d" % (rnd.choice((0, 1, 5, 6, 9)),
                                           rnd.choice((-1, 1, 3)),
                                           rnd.choice((0, 1, 7))))
                ops.append("c %d %d %d" % (t, k, x))
    for line in (0, 1, 2, 3, 19, 20, -1, -2, -3, 7, 0x7fffffff, -0x80000000):
        ops.append("X %d %d %d" % (rnd.choice((0, 1, 5, 6)), rnd.choice((-1,
                                                                         1)),
                                   rnd.choice((0, 1))))
        ops.append("D -1 -1 %d 00000000" % line)
        ops.append("d")
    for _ in range(40):
        ops.append("X %d %d %d" % (rnd.choice((0, 1, 2, 5, 6)),
                                   rnd.choice((-1, 0, 1)), rnd.choice((0, 1))))
        ops.append("O %d %d %d" % (rnd.randrange(-1, 9),
                                   rnd.choice((-1, 0, 1, 2)),
                                   rnd.choice((0, 1, 3))))
        ops.append(rnd.choice(("e", "f", "h", "h")))
    for t in range(-1, 9):
        for t2 in (t, t + 1, 5, 6):
            for k, k2 in ((0, 0), (0, 1), (-1, -1), (1, -1)):
                ops.append("X %d %d 0" % (t, k))
                ops.append("O %d %d 1" % (t2, k2))
                ops.append("h")
    return ops


def s_valid(rnd):
    """IsValid on a line, on a side and on neither, over routes of every
    kind of number."""
    w = World(rnd)
    ops = w.ops
    rns = (rnd.randrange(0, 50), rnd.choice((0, 49)),
           rnd.randrange(50, 70), rnd.choice((50, 69)),
           rnd.choice((70, rnd.randrange(70, 100))),
           rnd.choice((-3, 100, 120)))
    for k in range(NROUTES):
        w.route(k, 8, rns[k], rtype=rnd.choice((0, 1)))
    for k in range(8):
        w.car(k)
    ops.append("N 0 5 %s %s" % (h(f32(2.2)), h(f32(0.9))))
    for i in range(5):
        ops.append("E %d %s %s 0 0 %s %s %d" % (
            i, h(f32(rnd.uniform(-5.0, 5.0))), h(f32(rnd.uniform(-60, 60))),
            h(f32(2.0)), h(f32(1.0)), i + 1))
    for _ in range(120):
        r = rnd.choice((0, 1, 2, 3, 4, 5, -1))
        ops.append("D %d %d %d 00000000" % (r, 0 if r >= 0 else -1,
                                            rnd.randrange(LINES)))
        me = rnd.randrange(8)
        ops.append("N %d %d %s %s" % (me, rnd.choice((5, 3, 0)),
                                      h(f32(2.2)), h(f32(0.9))))
        t = rnd.choice((0, 1, 2, 3, 4, 5, 6, 7, -1, 1, 2))
        k = rnd.choice((-1, 0, 1, 3, 5, 6, 7))
        if t in (5, 6) and k < 0:
            k = 1
        ops.append("X %d %d 0" % (t, k))
        ops.append("g")
    return ops


def place_list(w, me, others, ys=None):
    """The list: car me, and an entry for each of `others`."""
    rnd = w.rnd
    ops = ["N %d %d %s %s" % (me, len(others),
                              h(f32(rnd.choice((2.2, 2.5, rnd.uniform(1.5,
                                                                     3.0))))),
                              h(f32(rnd.uniform(0.8, 1.2))))]
    for i, k in enumerate(others):
        y = ys[i] if ys else rnd.choice((rnd.uniform(-40.0, 40.0), 55.0,
                                         rnd.uniform(50.0, 90.0)))
        ops.append("E %d %s %s %s %s %s %s %d" % (
            i, h(f32(rnd.uniform(-6.0, 6.0))), h(f32(y)),
            h(f32(rnd.uniform(-5.0, 5.0))), h(f32(rnd.uniform(-5.0, 5.0))),
            h(f32(rnd.uniform(1.0, 3.0))), h(f32(rnd.uniform(0.8, 1.5))), k))
    return ops


def s_room(rnd):
    """IsEnoughRoom, the fix-up and the preferred side, beside cars on and
    off the road, facing either way, wanting either side."""
    w = World(rnd)
    ops = w.ops
    n0 = 40
    pts = w.route(0, n0, rnd.randrange(50),
                  turn=rnd.choice((0.0, 0.2, -0.2, 0.08, -0.25)))
    w.route(1, 20, rnd.randrange(50, 70), rtype=1)
    ncar = 8
    j0 = rnd.randrange(0, 10)
    line = rnd.randrange(LINES)
    me_lat = off_of(pts[j0], line) + rnd.choice((0.0, 0.5, -0.9, 3.0))
    hd = math.atan2(pts[j0]["dy"], pts[j0]["dx"])
    mx, my = beside(pts[j0], me_lat, 0.5)
    w.car(0, px=mx, py=my, bx=math.cos(hd), by=math.sin(hd),
          dtype=rnd.choice((2, 3, 0)), rpr=0, rpj=j0)
    for k in range(1, ncar):
        j = min(n0 - 2, j0 + rnd.randrange(0, 20))
        lat = rnd.choice((off_of(pts[j], line), off_of(pts[j], line) + 0.6,
                          rnd.uniform(-12.0, 12.0), pts[j]["rw"] - 2.0,
                          -pts[j]["lw"] + 2.0))
        x, y = beside(pts[j], lat, -0.5)
        back = rnd.random() < 0.4
        a = hd + (math.pi if back else 0.0) + rnd.uniform(-0.3, 0.3)
        w.car(k, px=x, py=y, bx=math.cos(a), by=math.sin(a),
              rpr=0, rpj=rnd.choice((j, j, max(0, j - 1))),
              dtype=rnd.choice((3, 3, 2, 0)),
              ct=rnd.choice((5, 6, 1, 0)), cc=rnd.choice((0, 0, 2, -1)),
              act=rnd.choice((6, 6, 5, -1, 11)))
        v = w.cars[k]
        if v["ct"] in (5, 6) and v["cc"] < 0:
            v["cc"] = 0
            ops[-1] = car_op(k, v)
    others = list(range(1, ncar))
    rnd.shuffle(others)
    ops += place_list(w, 0, others[:6])
    ops.append("D 0 %d %d 00000000" % (j0, line))
    for _ in range(50):
        e = rnd.randrange(6)
        k = others[e]
        t = rnd.choice((5, 6, 5, 6, 1, 2, 0, 7))
        ops.append("X %d %d %d" % (t, k, rnd.choice((0, 1))))
        ops.append("i %d" % e)
        ops.append("k %d" % e)
        ops.append("j 0 %d" % rnd.choice((1, 1, 0, 2)))
        if rnd.random() < 0.3:
            # Off the list: only where its amount out of bounds stops the
            # question before the entry is read.
            ok = others[6]
            v = w.cars[ok]
            v["oob"] = rnd.choice((0.0, -0.001, 1.0))
            ops.append(car_op(ok, v))
            ops.append("X %d %d 0" % (rnd.choice((5, 6)), ok))
            ops.append("j 0 1")
        if rnd.random() < 0.3:
            v = dict(w.cars[k])
            v["oob"] = rnd.choice((0.0, -0.001, -0.0011, -0.5, -4.0, 1.0))
            v["ct"] = rnd.choice((5, 6))
            v["cc"] = 0
            v["act"] = rnd.choice((6, 5, -1))
            v["dtype"] = rnd.choice((3, 2))
            w.cars[k] = v
            ops.append(car_op(k, v))
    # The bend: both on the line, the other well ahead.
    for _ in range(12):
        j = min(n0 - 2, j0 + rnd.randrange(3, 15))
        k = others[0]
        x, y = beside(pts[j], off_of(pts[j], line)
                      + rnd.choice((0.0, 0.9, -0.5, 1.1)), -0.5)
        v = dict(w.cars[k], px=x, py=y, oob=0.0)
        w.cars[k] = v
        ops.append(car_op(k, v))
        ops.append("E 0 %s %s 0 0 %s %s %d" % (
            h(f32(0.0)), h(f32(rnd.choice((49.0, 50.0, 51.0, 80.0)))),
            h(f32(2.0)), h(f32(1.0)), k))
        me = dict(w.cars[0], dtype=rnd.choice((2, 2, 3)))
        w.cars[0] = me
        ops.append(car_op(0, me))
        ops.append("X 5 %d 0" % k)
        ops.append("k 0")
    return ops


def walk_world(rnd, w, nsigns=4):
    """Five routes, three racing and two traffic, each starting near the
    others, and the signs leading only on to a route later in `order`."""
    rns = rnd.sample(range(0, 50), 3) + rnd.sample(range(50, 70), 2)
    sizes = (40, 30, 30, 25, 20)
    order = [0, 3, 1, 4, 2]
    plan = {}
    for _ in range(nsigns):
        a = rnd.randrange(4)
        k = order[a]
        plan[(k, rnd.randrange(1, sizes[k] - 2))] = order[
            rnd.randrange(a + 1, 5)]
    plan = sorted(plan.items())
    signs = {}
    for i, ((k, j), b) in enumerate(plan):
        signs.setdefault(k, {})[j] = i
    x = rnd.uniform(-100.0, 100.0)
    y = rnd.uniform(-100.0, 100.0)
    for k in range(5):
        w.route(k, sizes[k], rns[k], rtype=0 if k < 3 else 1,
                signs=signs.get(k), x=x + rnd.uniform(-30.0, 30.0),
                y=y + rnd.uniform(-30.0, 30.0))
    w.sign_points = [kj for kj, b in plan]
    for i, ((k, j), b) in enumerate(plan):
        got = w.sign(b, rnd.randrange(0, sizes[b] - 5))
        if got != i:
            raise SystemExit("sign %d filed as %d" % (i, got))
    return sizes


def near_sign(rnd, w, sizes):
    """A route and a point on it: half the time a few points short of a
    sign, so the walk from there crosses it."""
    if w.sign_points and rnd.random() < 0.6:
        k, j = rnd.choice(w.sign_points)
        return k, max(0, j - rnd.randrange(0, 4))
    k = rnd.randrange(5)
    return k, rnd.randrange(sizes[k] - 1)


def decide(rnd, w):
    ops = []
    for i in range(w.nsign):
        ops.append("Q %d %d %d" % (i, rnd.choice((0, 1, 1)),
                                   rnd.choice((-1, -1, rnd.randrange(LINES)))))
    return ops


def target_on(rnd, w, sizes, k, j, n, line):
    """A target of n points along route k up to its point j."""
    ops = ["T %d %s" % (rnd.randrange(64), h(f32(rnd.uniform(0.0, 80.0))))]
    for i in range(n):
        jj = max(0, j - (n - 1 - i))
        ops.append(tgt_point(w, k, jj, rnd.uniform(-4.0, 4.0), line,
                             sp=rnd.uniform(0.0, 40.0),
                             along=rnd.uniform(-2.0, 2.0)))
    return ops


def s_walk(rnd):
    """AdvancePoint, GetRoutePointsToUse and the road-block list, across
    signs taken and not, for racers and the rest."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=rnd.randint(4, 10))
    j0 = rnd.randrange(0, 12)
    line = rnd.randrange(LINES)
    p = w.pts[0][j0]
    mx, my = beside(p, off_of(p, line) + rnd.uniform(-3.0, 3.0), 1.0)
    w.car(0, px=mx, py=my, dtype=rnd.choice((2, 2, 3, 0)),
          vmag=rnd.choice((0.0, 15.0, 30.0, 45.0)))
    for k in range(1, 4):
        w.car(k)
    ops += place_list(w, 0, [1, 2, 3])
    ops += decide(rnd, w)
    ops.append("D 0 %d %d 00000000" % (j0, line))
    # The walker, step by step.
    for _ in range(16):
        k, j = near_sign(rnd, w, sizes)
        ops.append("W %d %d %d %d %s %d" % (
            k, j, rnd.choice((j, j, j - 1, sizes[k] - 1)),
            rnd.randrange(LINES), h(f32(rnd.uniform(-2.0, 2.0))),
            rnd.choice((0, 1))))
        for _ in range(rnd.randint(1, 8)):
            ops.append("n")
        if rnd.random() < 0.3:
            ops += decide(rnd, w)
    # The walk to use, from an empty target and from targets ending on
    # every route.
    for _ in range(14):
        if rnd.random() < 0.3:
            ops.append("T 0 00000000")
        else:
            k, j = near_sign(rnd, w, sizes)
            ops += target_on(rnd, w, sizes, k, j, rnd.randint(1, 6),
                             rnd.randrange(LINES))
        dtype = rnd.choice((2, 2, 3, 0))
        if ops[-1].startswith("Y") and rnd.random() < 0.25:
            # A racer's target ending on a traffic route, its last point
            # with no number: the walk is from the location, and where the
            # target ends is measured across the location's point.
            kt = rnd.choice((3, 4))
            f = tgt_point(w, kt, rnd.randrange(sizes[kt]),
                          rnd.uniform(-4.0, 4.0), rnd.randrange(LINES),
                          sp=rnd.uniform(0.0, 40.0)).split()
            f[5] = "-1"
            ops.append(" ".join(f))
            dtype = 2
        v = dict(w.cars[0], dtype=dtype,
                 vmag=rnd.choice((0.0, 5.0, 15.0, 30.0, 60.0)))
        w.cars[0] = v
        ops.append(car_op(0, v))
        ops.append("G SECS %s" % h(f32(rnd.choice((2.0, 0.5, 4.0, 10.0)))))
        ops.append("G DEF %s" % h(f32(rnd.choice((20.0, 5.0, 60.0,
                                                   400.0)))))
        kl, jl = near_sign(rnd, w, sizes)
        ops.append("D %d %d %d 00000000" % (kl, jl, rnd.randrange(LINES)))
        ops.append("o")
        if rnd.random() < 0.4:
            ops += decide(rnd, w)
    # From a location on another route.
    for _ in range(6):
        k = rnd.randrange(5)
        jl = rnd.randrange(sizes[k] - 1)
        ops.append("D %d %d %d 00000000" % (k, jl, rnd.randrange(LINES)))
        ops.append("T 0 00000000")
        ops.append("o")
        for jj in (jl, jl + 1, jl - 1, sizes[k] - 1, min(sizes[k] - 1,
                                                         jl + 25)):
            if 0 <= jj < sizes[k]:
                ops.append("p %d %d" % (k, jj))
    # No location: no point, nothing walked, *L as it was.
    ops.append("D -1 -1 3 00000000")
    ops.append("T 0 00000000")
    ops.append("o")
    # The list by hand.
    ops.append("F")
    for _ in range(rnd.randint(1, 6)):
        ops.append("m %d %d %d %s %d" % (
            rnd.randrange(100), rnd.randrange(30), rnd.randrange(LINES),
            h(f32(rnd.uniform(-3.0, 3.0))), rnd.choice((0, 1, 2))))
    return ops


def s_fill(rnd):
    """FillUpDriveTarget, for each way of moving with respect to the line,
    inside the edges or not, the tuning mode on and off."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=rnd.randint(3, 8))
    j0 = rnd.randrange(0, 15)
    line = rnd.randrange(LINES)
    p = w.pts[0][j0]
    mx, my = beside(p, off_of(p, line) + rnd.uniform(-4.0, 4.0), 1.0)
    w.car(0, px=mx, py=my, dtype=rnd.choice((2, 3, 0)),
          vmag=rnd.choice((10.0, 28.0, 35.0)), dn=rnd.choice((0, 101, 120)),
          ctl=rnd.choice((0, 3, 1)))
    for k in range(1, 4):
        w.car(k)
    ops += place_list(w, 0, [1, 2, 3])
    ops += decide(rnd, w)
    ops.append("R %08x" % rnd.choice((0, 40000, 100000)))
    for _ in range(16):
        ops.append("G TIMER %08x" % rnd.choice((0, 30000, 48000, 60000,
                                                 200000)))
        ops.append("G WILLIAMS %08x" % rnd.choice((0, 0, 0, 1)))
        jl = rnd.randrange(sizes[0] - 2)
        ops.append("D 0 %d %d %08x" % (jl, rnd.randrange(LINES),
                                       rnd.choice((0, 30000, 50000))))
        if rnd.random() < 0.3:
            ops.append("T %d 00000000" % rnd.randrange(64))
        else:
            k, j = near_sign(rnd, w, sizes)
            if rnd.random() < 0.4:
                k, j = 0, min(sizes[0] - 2, jl + rnd.randrange(0, 4))
            ops += target_on(rnd, w, sizes, k, j,
                             rnd.choice((1, 2, 4, 8, 19, 20)),
                             rnd.randrange(LINES))
        v = dict(w.cars[0], dtype=rnd.choice((2, 3, 0)),
                 vmag=rnd.choice((10.0, 28.0, 35.0, 60.0)),
                 ctl=rnd.choice((0, 0, 3)))
        w.cars[0] = v
        ops.append(car_op(0, v))
        ops.append("t %d %d" % (rnd.choice((0, 0, 1, 2, 3, 4)),
                                rnd.choice((0, 1))))
        if rnd.random() < 0.3:
            ops += decide(rnd, w)
    # Towards the line at no speed, the tuning mode off and every sign
    # taken: past a sign the speed is 0.25 at the most, and no less.
    ops.append("G WILLIAMS 00000000")
    ops.append("G TIMER %08x" % 200000)
    for i in range(w.nsign):
        ops.append("Q %d 1 -1" % i)
    for _ in range(10):
        ops.append("D 0 %d %d 00000000" % (rnd.randrange(sizes[0] - 2),
                                           rnd.randrange(LINES)))
        k, j = near_sign(rnd, w, sizes)
        ops += target_on(rnd, w, sizes, k, j, rnd.choice((1, 2, 4)),
                         rnd.randrange(LINES))
        v = dict(w.cars[0], dtype=rnd.choice((2, 0)), vmag=10.0, ctl=0)
        w.cars[0] = v
        ops.append(car_op(0, v))
        ops.append("t 0 %d" % rnd.randrange(2))
    # No location, no target, no list: nothing done.
    ops.append("D -1 -1 3 00000000")
    ops.append("T 7 00000000")
    ops.append("t 0 0")
    # A NULL location, target or list: nothing done either.
    ops.append("D 0 2 %d 00000000" % line)
    ops.append(car_op(0, w.cars[0]))
    for z in (1, 2, 4, 3, 6, 5, 7):
        ops.append("t 0 %d %d" % (rnd.randrange(2), z))
    # AddToDriveTarget on its own, of what the walk found.
    ops.append("D 0 2 %d 00000000" % line)
    ops.append("T 0 00000000")
    ops.append("o")
    for _ in range(6):
        ops.append("s %s %d" % (h(f32(rnd.uniform(-5.0, 5.0))),
                                rnd.randrange(2)))
    return ops


def s_bend(rnd, c, sgn):
    """GetPreferredSideOfCar on a smooth bend of curvature c (0.12 is the
    bend's), turning sgn's way and wide
    enough that no side is ever blocked: each car either side of 1 m off
    the line, a traffic car either side of 5 m, and the other car past the
    route's last point, where no point is ahead of it."""
    w = World(rnd)
    ops = w.ops
    n0 = 40
    pts = w.route(0, n0, rnd.randrange(50), turn=sgn * math.asin(c) / 6.0,
                  smooth=True)
    j0 = rnd.randrange(0, 8)
    line = rnd.randrange(LINES)
    w.car(0, oob=0.0)
    w.car(1, oob=0.0)
    ops += place_list(w, 0, [1])
    for _ in range(60):
        case = rnd.choice(("bend", "bend", "traffic", "end"))
        if case == "end":
            # The location two or three short of the end: what is measured
            # across its point and across the next differ.
            jl = n0 - rnd.choice((2, 3))
            my_lat = rnd.choice((0.0, 0.5, -0.5, 2.0, -2.0))
            ox, oy = beside(pts[n0 - 1], rnd.uniform(-6.0, 6.0),
                            rnd.uniform(1.0, 6.0))
            dtype = rnd.choice((2, 3))
        else:
            jl = j0
            j = min(n0 - 2, j0 + rnd.randrange(2, 15))
            if case == "bend":
                my_lat = rnd.choice((0.0, 0.5, -0.5, 0.9, -0.9, 1.5, -1.5))
                o_lat = rnd.choice((0.0, 0.6, -0.6, 0.95, -0.95, 1.2, -1.2))
                dtype = rnd.choice((2, 0))
            else:
                my_lat = rnd.choice((0.0, 2.0, -3.0, -7.0))
                o_lat = rnd.choice((0.0, 4.5, 5.5, 5.9, 6.5, -5.5, -6.5))
                dtype = 3
            ox, oy = beside(pts[j], o_lat, -0.5)
        ops.append("D 0 %d %d 00000000" % (jl, line))
        mx, my = beside(pts[jl], my_lat, 0.5)
        me = dict(w.cars[0], px=mx, py=my, dtype=dtype)
        other = dict(w.cars[1], px=ox, py=oy)
        w.cars[0], w.cars[1] = me, other
        ops.append(car_op(0, me))
        ops.append(car_op(1, other))
        ops.append("E 0 %s %s 0 0 %s %s 1" % (
            h(f32(rnd.uniform(-2.0, 2.0))),
            h(f32(rnd.choice((45.0, 49.9, 50.5, 80.0)))),
            h(f32(rnd.choice((1.0, 2.0)))), h(f32(1.0))))
        ops.append("k 0")
    return ops


def s_speed(rnd):
    """GetSpeedBackToLine either side of 60 and 66 mph, in the grace period
    and out, relaxed or not; and the grace period on its own."""
    w = World(rnd)
    ops = w.ops
    w.route(0, 20, 3)
    for k in range(4):
        w.car(k)
    ops.append("R %08x" % 1000)
    for _ in range(60):
        v = dict(w.cars[0],
                 vmag=rnd.choice((26.8216362, f32(26.8216362) + 1e-5, 27.0,
                                  29.5038013, 29.51, 40.0, 0.0, 10.0)),
                 ctl=rnd.choice((0, 1, 3, 4)),
                 dn=rnd.choice((0, 100, 101, 102, 125, 149, 150, -5)))
        w.cars[0] = v
        ops.append(car_op(0, v))
        ops.append("N 0 0 00000000 00000000")
        ops.append("G TIMER %08x" % rnd.choice((
            1000, 49000, 49001, 49004, 61000, 1000 + 4 * 12000 - 4,
            rnd.randrange(0, 300000), 0x7fffffff, 0x80000000, 0)))
        ops.append("D 0 %d %d %08x" % (rnd.randrange(20), rnd.randrange(LINES),
                                       rnd.choice((0, 30000, 45000, 48000))))
        for m in (0, 1, 2, 3, 4, -1, 7):
            ops.append("q %d" % m)
        ops.append("u 0")
    for g, gap in ((12.0, 0.5), (0.0, 0.0), (5.0, -1.0)):
        ops.append("G GRACE %s" % h(f32(g)))
        ops.append("G GAP %s" % h(f32(gap)))
        for dn in (100, 101, 149, 150, 0, 99, 102):
            v = dict(w.cars[1], dn=dn)
            ops.append(car_op(1, v))
            for t in (1000, 1000 + 4 * 12000, 1000 + 4 * 12000 + 1,
                      1000 + 4 * 11500, 1000 + 4 * 12500, 0):
                ops.append("G TIMER %08x" % t)
                ops.append("u 1")
    return ops


def s_reduce(rnd):
    """ReduceCurrentL, each way and to each edge."""
    w = World(rnd)
    ops = w.ops
    w.route(0, 10, 7)
    for _ in range(150):
        ops.append("r %s %d 0 %d %d %s %s %d" % (
            h(f32(rnd.choice((0.0, -0.0, rnd.uniform(-15.0, 15.0), 0.25,
                              -0.25, 0.1, 30.0, -30.0)))),
            rnd.choice((0, 1, 2, 3, 4, 7)), rnd.randrange(10),
            rnd.randrange(LINES),
            h(f32(rnd.choice((0.25, 0.5, 0.0, rnd.uniform(0.0, 3.0))))),
            h(f32(rnd.choice((1.0, 2.2, 0.0, 9.0)))),
            rnd.choice((0, 1, 1, 0x100))))
    return ops


def heading_of(p):
    return math.atan2(p["dy"], p["dx"])


def lateral_of(p, x, y):
    return (x - p["x"]) * p["dy"] - (y - p["y"]) * p["dx"]


def its_target(rnd, w, sizes, k, kr, j, reverse=False,
               picks=(0, 0, 1, 2, 7, -1)):
    """Car k's own target: up to eight points along route kr from about
    its point j, forwards or back, now and then jumping to another route,
    and sometimes with a point that has no route or no number. A cached
    pick of -1 is no state the game reaches (GetFirstPoint answers 0 to
    NumPoints - 1 and a new target has 0); where it is read before a
    point, the port and the image read the same bytes of the record."""
    ops = ["H %d %d %s %d %d %d" % (
        k, rnd.randrange(64), h(f32(rnd.uniform(0.0, 80.0))),
        rnd.choice(picks), rnd.choice((0, 1000, 5000)),
        rnd.choice((0, 1000)))]
    jj = max(0, min(sizes[kr] - 1, j))
    for i in range(rnd.choice((0, 1, 2, 4, 6, 8, 8))):
        if i and rnd.random() < 0.12:
            kr = rnd.randrange(5)
            jj = rnd.randrange(sizes[kr])
        f = tgt_point(w, kr, jj, rnd.uniform(-5.0, 5.0),
                      rnd.randrange(LINES), sp=rnd.uniform(0.0, 40.0),
                      along=rnd.uniform(-2.0, 2.0)).split()
        if rnd.random() < 0.06:
            f[4 if rnd.random() < 0.5 else 5] = "-1"
        ops.append("I %d %s" % (k, " ".join(f[1:])))
        jj = max(0, min(sizes[kr] - 1, jj + (-1 if reverse else 1)))
    return ops


def car_at_point(rnd, w, k, kr, j, lat, near, its=None, **kw):
    """Car k at route kr's point j, lat across it, heading along it or
    across or back and sliding a little, at speeds either side of the
    ones that matter."""
    p = w.pts[kr][j]
    x, y = beside(p, lat, rnd.uniform(-3.0, 3.0))
    if near:
        turn = rnd.choice((0.0, 0.2, -0.2, 0.7, -0.7))
        speed = rnd.choice((4.9, 5.0, 5.01, 12.0, 20.0, 30.0, 30.0))
        nw = rnd.choice((2, 3, 4, 4, 4))
    else:
        turn = rnd.choice((0.0, 0.0, 0.3, -0.3, 0.78, -0.78, 0.8, -0.8,
                           math.pi, 1.6))
        speed = rnd.choice((4.9, 5.0, 5.01, 9.99, 10.0, 10.01, 10.5, 19.99,
                            20.0, 20.01, 20.5, 30.0, -15.0, -25.0, 0.0))
        nw = rnd.choice((2, 3, 4, 4))
    a = heading_of(p) + turn
    slip = a + rnd.choice((0.0, 0.0, 0.3, -0.5, 0.9))
    vel = max(abs(speed), 1.0)
    args = dict(px=x, py=y, bx=math.cos(a), by=math.sin(a), vmag=speed,
                vx=vel * math.cos(slip), vy=vel * math.sin(slip), nw=nw,
                pl=rnd.choice((0, 1)), dtype=rnd.choice((1, 2, 3, 3, 4, 4)),
                fs=rnd.choice((0.0, 25.0, 35.0)), oob=0.0)
    args.update(kw)
    return w.car(k, **args)


def place_other(rnd, w, sizes, k, kr, j0, near=False, reverse=None,
                span=18, picks=(0, 0, 1, 2, 7, -1)):
    """Car k up to `span` points ahead of j0 on route kr: on its line,
    near an edge or off the road; and its own target."""
    j = min(sizes[kr] - 2, j0 + rnd.randrange(1, span))
    p = w.pts[kr][j]
    lat = rnd.choice((off_of(p, 0), rnd.uniform(-3.0, 3.0),
                      rnd.uniform(-p["lw"], p["rw"]), p["rw"] - 1.0,
                      -p["lw"] + 1.0, p["rw"] + 4.9, p["rw"] + 5.1,
                      -p["lw"] - 4.9, -p["lw"] - 5.1, p["rw"] + 9.0))
    v = car_at_point(rnd, w, k, kr, j, lat, near)
    if reverse is None:
        reverse = rnd.random() < 0.2
    kt = rnd.choice((kr, kr, kr, 3, 4, 1))
    jt = j if kt == kr else rnd.randrange(sizes[kt])
    w.ops += its_target(rnd, w, sizes, k, kt, jt, reverse, picks)
    return v


def place_me(rnd, w, k, kr, j0, line, **kw):
    p = w.pts[kr][j0]
    hd = heading_of(p) + rnd.choice((0.0, 0.0, 0.1, -0.1))
    slip = hd + rnd.choice((0.0, 0.0, 0.2, -0.3))
    x, y = beside(p, off_of(p, line) + rnd.uniform(-2.0, 2.0), 1.0)
    sp = rnd.choice((4.9, 5.0, 5.01, 20.0, 35.0))
    args = dict(px=x, py=y, bx=math.cos(hd), by=math.sin(hd), vmag=sp,
                vx=sp * math.cos(slip), vy=sp * math.sin(slip),
                dtype=rnd.choice((2, 2, 3, 3, 4, 0)), oob=0.0)
    args.update(kw)
    return w.car(k, **args)


def s_around(rnd):
    """BuildDriveTarget, and BuildDriveTargetAroundCar under it, for a
    line, a side and neither, beside cars of every kind, on the road and
    off it and past a sign, the traffic tuning mode on and off."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=rnd.randint(0, 6))
    # The walk starts on route 0, or a few points short of a sign so that
    # it crosses it.
    if w.sign_points and rnd.random() < 0.6:
        si = rnd.randrange(len(w.sign_points))
        kl, js = w.sign_points[si]
        jl = max(0, js - rnd.randrange(1, 6))
    else:
        si = None
        kl, jl = 0, rnd.randrange(0, 8)
    line = rnd.randrange(LINES)
    place_me(rnd, w, 0, kl, jl, line)
    others = [1, 2, 3, 4]

    def place(k, near):
        if si is not None and rnd.random() < 0.5:
            # Past the sign, where the walk's points carry an offset.
            b, j2 = w.sign_to[si]
            place_other(rnd, w, sizes, k, b, max(0, j2 - 1), near, span=4)
        else:
            # Mostly within the walk's look-ahead, about five points.
            place_other(rnd, w, sizes, k, kl, jl, near,
                        span=rnd.choice((7, 7, 18)))

    for k in others:
        place(k, rnd.random() < 0.6)
    # Not on the list.
    place_other(rnd, w, sizes, 5, kl, jl)
    ops += place_list(w, 0, others)
    for i in range(w.nsign):
        ops.append("Q %d %d %d" % (i, rnd.choice((0, 1, 1, 1)),
                                   rnd.choice((-1, -1, rnd.randrange(LINES)))))
    for _ in range(40):
        if rnd.random() < 0.5:
            place(rnd.choice(others), rnd.random() < 0.6)
        if rnd.random() < 0.25:
            place_me(rnd, w, 0, kl, jl, line)
        if rnd.random() < 0.2:
            ops += place_list(w, 0, others)
        ops.append("G TIMER %08x" % rnd.choice((0, 1000, 5000, 77777)))
        if rnd.random() < 0.3:
            ops.append("G TRAFFIC %08x" % rnd.choice((0, 1)))
        if rnd.random() < 0.1:
            ops.append("G SLOWCAR %s" % h(f32(rnd.choice((20.0, 9.0,
                                                            30.0)))))
            ops.append("G SLOWTRAFFIC %s" % h(f32(rnd.choice((10.0, 4.0,
                                                               25.0)))))
        if rnd.random() < 0.15:
            ops.append("G SECS %s" % h(f32(rnd.choice((2.0, 0.5, 6.0)))))
            ops.append("G DEF %s" % h(f32(rnd.choice((20.0, 60.0, 150.0)))))
        if rnd.random() < 0.05:
            ops.append("D -1 -1 %d 00000000" % line)
        else:
            ops.append("D %d %d %d 00000000" % (
                kl, max(0, jl + rnd.choice((0, 0, 1, -1))),
                line if rnd.random() < 0.8 else rnd.randrange(LINES)))
        t = rnd.choice((5, 6, 5, 6, 5, 6, 1, 2, 3, 4, 0, 7))
        k = rnd.choice(others)
        if rnd.random() < 0.5:
            if rnd.random() < 0.1:
                k = rnd.choice((5, -1))
            ops.append("X %d %d %d" % (t, k, rnd.choice((0, 1))))
            ops += its_target(rnd, w, sizes, 0, kl, jl)
            ops.append("v %d" % rnd.choice((0, 1, 2)))
        else:
            ops.append("X %d %d %d" % (rnd.choice((5, 6)), k,
                                       rnd.choice((0, 1))))
            if rnd.random() < 0.4:
                ops.append("T %d 00000000" % rnd.randrange(64))
            else:
                kk, jj = near_sign(rnd, w, sizes)
                if rnd.random() < 0.5:
                    kk, jj = kl, min(sizes[kl] - 2, jl + rnd.randrange(0, 3))
                ops += target_on(rnd, w, sizes, kk, jj,
                                 rnd.choice((1, 2, 4, 8)),
                                 rnd.randrange(LINES))
            ops.append("w")
        if rnd.random() < 0.3:
            ops += decide(rnd, w)
    return ops


def s_sign_pass(rnd):
    """Round a car just past a sign onto a route that carries straight on
    a metre or two to one side, so the walk's points there carry a small
    offset that the passing point keeps."""
    w = World(rnd)
    ops = w.ops
    sizes = [40, 30, 30, 25, 20]
    js = rnd.randrange(8, 20)
    rns = rnd.sample(range(0, 50), 3)
    pts0 = w.route(0, sizes[0], rns[0], signs={js: 0})
    p = pts0[js + 1]
    x, y = beside(p, rnd.uniform(-3.0, 3.0))
    w.route(1, sizes[1], rns[1], x=x, y=y, hd=heading_of(p), turn=0.0)
    w.route(2, sizes[2], rns[2])
    w.route(3, sizes[3], rnd.randrange(50, 60), rtype=1)
    w.route(4, sizes[4], rnd.randrange(60, 70), rtype=1)
    w.sign(1, 0)
    w.sign_points = [(0, js)]
    line = rnd.randrange(LINES)
    jl = js - rnd.randrange(1, 4)
    place_me(rnd, w, 0, 0, jl, line, dtype=rnd.choice((2, 2, 0, 3)))
    others = [1, 2, 3, 4]
    for k in others:
        place_other(rnd, w, sizes, k, 1, -1, rnd.random() < 0.6, span=5)
    ops += place_list(w, 0, others)
    for _ in range(30):
        ops.append("Q 0 %d -1" % rnd.choice((1, 1, 1, 0)))
        # A look-ahead long enough to reach well past the sign.
        ops.append("G SECS %s" % h(f32(rnd.choice((2.0, 6.0, 10.0)))))
        ops.append("G DEF %s" % h(f32(rnd.choice((20.0, 150.0)))))
        if rnd.random() < 0.5:
            place_other(rnd, w, sizes, rnd.choice(others), 1, -1,
                        rnd.random() < 0.6, span=5)
        if rnd.random() < 0.3:
            place_me(rnd, w, 0, 0, jl, line, dtype=rnd.choice((2, 2, 0, 3)))
        ops.append("G TIMER %08x" % rnd.choice((0, 1000, 77777)))
        ops.append("D 0 %d %d 00000000" % (jl, line))
        k = rnd.choice(others)
        ops.append("X %d %d %d" % (rnd.choice((5, 6)), k, rnd.choice((0, 1))))
        if rnd.random() < 0.5:
            ops += its_target(rnd, w, sizes, 0, 0, jl)
            ops.append("v %d" % rnd.choice((0, 1, 2)))
        else:
            ops.append("T %d 00000000" % rnd.randrange(64))
            ops.append("w")
    return ops


def s_pieces(rnd):
    """The pieces on their own, over lists made by hand on racing and
    traffic routes: the closest point ahead from anywhere, the clearance
    beside cars either side of each speed that matters, the smooth way out
    to every index either way, and the target alongside a car level with
    this one, its own target running either way."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=0)
    j0 = rnd.randrange(0, 6)
    line = rnd.randrange(LINES)
    me = place_me(rnd, w, 0, 0, j0, line)
    others = [1, 2, 3, 4]
    for k in others:
        place_other(rnd, w, sizes, k, 0, j0, near=True)
    ops += place_list(w, 0, others)
    for _ in range(12):
        kf = rnd.choice((0, 0, 0, 3, 4))
        pts = w.pts[kf]
        ops.append("F")
        n = rnd.choice((0, 1, 2, 3, 4, 5, 8, 12, 20))
        js = rnd.randrange(0, sizes[kf] - max(n, 1))
        fl = []
        for i in range(n):
            ln = line if rnd.random() < 0.8 else rnd.randrange(LINES)
            # Now and then the same point twice, for a tie.
            jj = js + i - 1 if i and rnd.random() < 0.15 else js + i
            fo = rnd.choice((0.0, 0.0, rnd.uniform(-2.0, 2.0)))
            fl.append((jj, ln, f32(fo)))
            ops.append("m %d %d %d %s 0" % (w.rn[kf], jj, ln, h(f32(fo))))
        for _ in range(6):
            p = pts[max(0, min(sizes[kf] - 1, js + rnd.randrange(-2, n + 3)))]
            if rnd.random() < 0.15:
                x, y = p["x"], p["y"]       # on the point: not ahead
            else:
                x, y = beside(p, rnd.uniform(-8.0, 8.0),
                              rnd.choice((0.0, -0.01, 0.01,
                                          rnd.uniform(-20.0, 20.0))))
            ops.append("x %s %s %d" % (h(f32(x)), h(f32(y)),
                                       rnd.choice((-3, -1, 0, 0, 1, 2, n - 1,
                                                   n, n + 2))))
        # The clearance: the car close beside where this one would be,
        # at each speed either side of the slow ones.
        for _ in range(8 if n else 2):
            e = rnd.randrange(4)
            k = others[e]
            if n:
                i = rnd.randrange(n)
                jj, ln, fo = fl[i]
                p0 = pts[fl[0][0]]
                mine = (lateral_of(p0, me["px"], me["py"])
                        - off_of(p0, fl[0][1]) + fl[0][2])
                lat = (mine + off_of(pts[jj], ln) - fo
                       + rnd.choice((0.0, 2.0, -3.5, 5.0, -7.0,
                                     rnd.uniform(-9.0, 9.0))))
                car_at_point(rnd, w, k, kf, jj, lat, False,
                             vmag=rnd.choice((
                                 9.99, 10.0, 10.01, 10.5, 19.99, 20.0, 20.01,
                                 20.5, 25.0, -10.0, -10.5, -15.0, -20.0,
                                 -20.5, -25.0, 0.0)),
                             dtype=rnd.choice((3, 3, 2, 1, 4)))
            me = dict(me, dtype=rnd.choice((3, 2, 2, 0)))
            w.cars[0] = me
            ops.append(car_op(0, me))
            ops.append("y %d %d" % (rnd.choice((e, e, e, -1)),
                                    rnd.choice((-1,) + tuple(range(n)))))
        for _ in range(4):
            if rnd.random() < 0.5:
                ops.append("T %d 00000000" % rnd.randrange(64))
            else:
                ops += target_on(rnd, w, sizes, kf, max(0, js - 1),
                                 rnd.choice((1, 2, 5, 18, 19, 20)), line)
            fr = rnd.choice((0.0, 1.5, -2.0, rnd.uniform(-6.0, 6.0)))
            to = rnd.choice((fr, 0.0, 3.0, -3.0, rnd.uniform(-8.0, 8.0)))
            ops.append("z %d %s %s %d" % (rnd.randrange(0, n + 2),
                                          h(f32(fr)), h(f32(to)),
                                          rnd.choice((0, 1))))
        # Alongside: the car level with this one, its target along the
        # list's route either way, cached or not.
        for _ in range(4):
            k = rnd.choice(others)
            if rnd.random() < 0.6:
                jo = js + rnd.randrange(0, max(1, n))
                car_at_point(rnd, w, k, kf, min(sizes[kf] - 1, jo),
                             rnd.uniform(-4.0, 4.0), True)
                rev = rnd.random() < 0.5
                ops.extend(its_target(rnd, w, sizes, k,
                                      rnd.choice((kf, kf, 3, 4)),
                                      jo + (rnd.randrange(2, 8) if rev
                                            else 0), rev))
            if rnd.random() < 0.3:
                me = place_me(rnd, w, 0, 0, j0, line)
            ops.append("G TIMER %08x" % rnd.choice((0, 1000, 5000, 77777)))
            ops.append("X %d %d 0" % (rnd.choice((5, 6)), k))
            if rnd.random() < 0.5:
                ops.append("T %d 00000000" % rnd.randrange(64))
            else:
                ops += target_on(rnd, w, sizes, kf, max(0, js - 1),
                                 rnd.choice((1, 2, 5, 18, 19, 20)), line)
            ops.append("M %s" % h(f32(rnd.choice((0.0, 3.5, -3.5,
                                                  rnd.uniform(-9.0, 9.0))))))
    return ops


def s_back(rnd):
    """Lists and targets that run back on themselves: the smooth way out
    over a list that doubles back, so a point before the last is further
    from the first than the last is, and the target alongside a car on a
    traffic route whose own target runs back down the list, so that each
    point's search for the road starts where the last one's ended."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=0)
    kf = rnd.choice((3, 4, 3, 4, 0))
    pts = w.pts[kf]
    line = rnd.randrange(LINES)

    def along(k, j, lat, sp, **kw):
        p = pts[j]
        hd = heading_of(p) + rnd.choice((0.0, 0.0, 0.1, -0.2))
        x, y = beside(p, lat, rnd.uniform(-2.0, 2.0))
        args = dict(px=x, py=y, bx=math.cos(hd), by=math.sin(hd), vmag=sp,
                    vx=sp * math.cos(hd), vy=sp * math.sin(hd), nw=4,
                    fs=rnd.choice((0.0, 25.0, 35.0)), oob=0.0)
        args.update(kw)
        return w.car(k, **args)

    js = rnd.randrange(0, 4)
    along(0, js, off_of(pts[js], line), rnd.choice((20.0, 35.0)),
          dtype=rnd.choice((2, 3, 0)))
    others = [1, 2, 3, 4]
    for k in others:
        along(k, js + rnd.randrange(0, 8), rnd.uniform(-4.0, 4.0),
              rnd.choice((12.0, 30.0)), pl=rnd.choice((0, 1)),
              dtype=rnd.choice((1, 2, 3, 4)))
    ops += place_list(w, 0, others)
    for _ in range(30):
        n = rnd.randrange(8, 14)
        back = rnd.random() < 0.5
        ops.append("F")
        jj = js
        for i in range(n):
            if back and i and rnd.random() < 0.3:
                # Two or three points on, then back to where it was.
                jx = min(sizes[kf] - 1, jj + rnd.randrange(2, 4))
            else:
                jx = jj
                jj = min(sizes[kf] - 1, jj + 1)
            ln = line if rnd.random() < 0.8 else rnd.randrange(LINES)
            fo = rnd.choice((0.0, 0.0, rnd.uniform(-1.0, 1.0)))
            ops.append("m %d %d %d %s 0" % (w.rn[kf], jx, ln, h(f32(fo))))
        ops.append("T %d 00000000" % rnd.randrange(64))
        if back or rnd.random() < 0.3:
            # Out by a little, on a road wide enough not to stop it.
            fr = rnd.choice((0.0, -1.5, 1.0))
            to = fr + rnd.choice((1.0, 2.5, 4.0, -1.0, -2.5))
            for _ in range(3):
                ops.append("z %d %s %s %d" % (rnd.randrange(3, n + 2),
                                              h(f32(fr)), h(f32(to)),
                                              rnd.choice((0, 0, 1))))
            continue
        k = rnd.choice(others)
        jo = js + rnd.randrange(0, n - 2)
        along(k, jo, rnd.uniform(-4.0, 4.0), rnd.choice((12.0, 30.0)),
              pl=rnd.choice((0, 1)), dtype=rnd.choice((1, 2, 3, 4)))
        kt = kf if kf != 0 else rnd.choice((3, 4))
        rev = rnd.random() < 0.7
        jt = jo + rnd.randrange(2, 9) if rev else jo
        ops += its_target(rnd, w, sizes, k, kt, jt, rev)
        ops.append("G TIMER %08x" % rnd.choice((0, 1000, 77777)))
        ops.append("X %d %d 0" % (rnd.choice((5, 6)), k))
        ops.append("M %s" % h(f32(rnd.choice((3.5, -3.5, 6.0, -6.0, 9.0,
                                               -9.0,
                                               rnd.uniform(-12.0, 12.0))))))
    return ops


# ------------------------------------------- CarCollisionPredict (11b-4a)


def bam_of(a):
    return int(round(a / (2.0 * math.pi) * 65536.0)) & 0xffff


def extras(rnd, k, hd, flip=None):
    """Car k's acceleration, velocity z, angle (about its heading, now and
    then anything) and box: mostly a car's, now and then lopsided, inside
    out on an axis or flat; inside out on axis `flip` when it is given."""
    if rnd.random() < 0.1:
        ang = rnd.randrange(65536)
    else:
        ang = bam_of(hd + rnd.choice((0.0, 0.0, 0.0, 0.05, -0.3)))
    acc = rnd.choice(((0.0, 0.0), (0.0, 0.0),
                      (rnd.uniform(-3.0, 3.0), rnd.uniform(-3.0, 3.0)),
                      (rnd.uniform(-15.0, 15.0), rnd.uniform(-15.0, 15.0))))
    hl = rnd.choice((2.3, 2.5, rnd.uniform(1.6, 3.2)))
    hw = rnd.choice((0.9, 1.0, rnd.uniform(0.6, 1.4)))
    hz = rnd.choice((0.7, rnd.uniform(0.4, 1.0)))
    off = rnd.choice((0.0, 0.0, rnd.uniform(-0.5, 0.5)))
    mn = [-hl + off, -hw, -hz]
    mx = [hl + off, hw, hz]
    r = rnd.random()
    if flip is not None:
        mn[flip], mx[flip] = mx[flip], mn[flip]
    elif r < 0.06:
        i = rnd.randrange(3)
        mn[i], mx[i] = mx[i], mn[i]
    elif r < 0.09:
        mx[2] = mn[2]
    vz = rnd.choice((0.0, 0.0, rnd.uniform(-2.0, 2.0)))
    return "A %d %s %s %s %d %s" % (
        k, h(f32(acc[0])), h(f32(acc[1])), h(f32(vz)), ang,
        " ".join(h(f32(x)) for x in mn + mx))


def mover(rnd, w, k, x, y, hd, speed, back=False, flip=None, **kw):
    """Car k at (x, y) heading hd at `speed`, sliding a little; backing up
    when `back`. A car at 1 m/s or more has a velocity to go by."""
    slip = hd + rnd.choice((0.0, 0.0, 0.0, 0.1, -0.15))
    vel = abs(speed)
    if vel < 1.0 and rnd.random() < 0.5:
        vel = 0.0
    vd = slip + (math.pi if back else 0.0)
    fs = -vel if back else vel * rnd.choice((1.0, 1.0, 0.98))
    args = dict(px=x, py=y, bx=math.cos(hd), by=math.sin(hd), vmag=speed,
                vx=max(vel, 1e-3) * math.cos(vd),
                vy=max(vel, 1e-3) * math.sin(vd), fs=fs,
                nw=rnd.choice((4, 4, 3)),
                pl=rnd.choice((0, 0, 0, 1)),
                dtype=rnd.choice((1, 2, 2, 3, 3, 4, 5)),
                ctl=rnd.choice((1, 2, 2, 3, 3, 4)),
                act=rnd.choice((-1, 5, 5, 7, 10, 11, 0, 6)),
                oob=rnd.choice((0.0, -0.25, -0.2499, -0.2501, -1.0, 0.5,
                                -0.3)))
    args.update(kw)
    v = w.car(k, **args)
    w.ops.append(extras(rnd, k, hd, flip))
    return v


def lane_target(rnd, w, k, kr, j0, n, lat, rev=False):
    """Car k's own target (k -1: the target): n points along route kr from
    j0, forwards or back, lat across, now and then changing lane or
    doubling a point."""
    if k < 0:
        ops = ["T %d %s" % (rnd.randrange(64), h(f32(rnd.uniform(0, 80))))]
    else:
        ops = ["H %d %d %s %d %d %d" % (
            k, rnd.randrange(64), h(f32(rnd.uniform(0.0, 80.0))),
            rnd.choice((0, 0, 1, 2, 7)), rnd.choice((0, 1000, 5000)),
            rnd.choice((0, 1000)))]
    pts = w.pts[kr]
    j = j0
    last = None
    for i in range(n):
        if rnd.random() < 0.1:
            lat += rnd.choice((-3.5, 3.5, -1.0, 1.0))
        if last is not None and rnd.random() < 0.06:
            x, y = last
        else:
            j = max(0, min(len(pts) - 1, j))
            x, y = beside(pts[j], lat * (-1.0 if rev else 1.0),
                          rnd.uniform(-1.0, 1.0))
        last = (x, y)
        f = "%s %s %s %d %d %d %s" % (
            h(f32(x)), h(f32(y)), h(f32(rnd.uniform(-2.0, 2.0))), w.rn[kr],
            j, rnd.randrange(LINES), h(f32(rnd.uniform(0.0, 40.0))))
        ops.append(("Y " if k < 0 else "I %d " % k) + f)
        j += -1 if rev else 1
    return ops


def frame(me, x, y):
    """Where (x, y) is from car `me`: across (right) and ahead."""
    dx, dy = x - me["px"], y - me["py"]
    return (dx * me["by"] - dy * me["bx"], dx * me["bx"] + dy * me["by"])


SPEEDS_ME = (0.0, 0.0005, 0.001, 0.0011, 1.5, 1.999, 2.0, 2.001, 10.0, 20.0,
             30.0, 45.0, -3.0)


def s_predict(rnd):
    """WillIHitThisCar and WhoWillThisDriveTargetHit: my car along a route
    on a target of its points, and cars ahead going my way more slowly,
    coming the other way, crossing on a second route, alongside, stopped,
    behind and backing up, in every mode and action either side of each
    test, the traffic tuning mode on and off."""
    w = World(rnd)
    ops = w.ops
    turn = rnd.choice((0.0, 0.0, 0.02, -0.02, 0.05))
    pts = w.route(0, 40, rnd.randrange(50), smooth=True, turn=turn)
    jc = rnd.randrange(14, 26)
    pc = pts[jc]
    hd1 = heading_of(pc) + rnd.choice((math.pi / 2, -math.pi / 2, 0.7,
                                       2.4))
    w.route(1, 30, rnd.randrange(50, 70), smooth=True, turn=0.0,
            x=pc["x"] - 150.0 * math.cos(hd1),
            y=pc["y"] - 150.0 * math.sin(hd1), hd=hd1 - 0.0)
    lanes = (-3.5, 0.0, 3.5)
    others = [1, 2, 3, 4, 5, 6]

    def place_me():
        j0 = rnd.randrange(2, 8)
        lat = rnd.choice(lanes) + rnd.uniform(-0.5, 0.5)
        p = pts[j0]
        x, y = beside(p, lat, rnd.uniform(-3.0, 3.0))
        hd = heading_of(p) + rnd.choice((0.0, 0.0, 0.05, -0.08))
        sp = rnd.choice(SPEEDS_ME)
        back = rnd.random() < 0.12
        me = mover(rnd, w, 0, x, y, hd, sp, back=back,
                   ctl=rnd.choice((2, 2, 3, 3, 1)),
                   dtype=rnd.choice((2, 2, 3, 3, 4)))
        n = rnd.choice((0, 1, 2, 4, 8, 12, 20, 20))
        ops.extend(lane_target(rnd, w, -1, 0, j0 + rnd.choice((0, 1, 1, 2)),
                               n, lat))
        if n and rnd.random() < 0.08:
            # The first point on the car: a first leg of 0.
            ops.append("T 0 00000000")
            ops.append("Y %s %s 00000000 %d %d 0 00000000" % (
                h(f32(x)), h(f32(y)), w.rn[0], j0))
            ops.extend(lane_target(rnd, w, -1, 0, j0 + 1, n, lat)[1:])
        return me, j0, lat

    def place(k, me, j0):
        kind = rnd.choice(("follow", "follow", "oncoming", "oncoming",
                           "cross", "beside", "stopped", "behind", "back"))
        sp = rnd.choice((0.0, 0.5, 4.9, 5.0, 5.01, 8.0, 15.0, 25.0, 35.0,
                         -4.0))
        lat = rnd.choice(lanes) + rnd.uniform(-0.6, 0.6)
        rev = False
        back = False
        kr = 0
        if kind == "follow":
            j = j0 + rnd.randrange(1, 8)
        elif kind == "oncoming":
            j = j0 + rnd.randrange(3, 16)
            rev = True
        elif kind == "cross":
            kr = 1
            j = rnd.randrange(6, 14)
        elif kind == "beside":
            j = j0
            lat = rnd.choice((lat + 3.5, lat - 3.5, lat + 2.0))
        elif kind == "stopped":
            j = j0 + rnd.randrange(1, 4)
            sp = rnd.choice((0.0, 0.0, 2.0, 4.99, 5.0, 5.001, -2.0))
        elif kind == "behind":
            j = max(0, j0 - rnd.randrange(1, 3))
        else:
            j = j0 + rnd.randrange(1, 6)
            back = True
        p = w.pts[kr][min(j, len(w.pts[kr]) - 1)]
        x, y = beside(p, lat * (-1.0 if rev else 1.0),
                      rnd.uniform(-4.0, 4.0))
        hd = heading_of(p) + (math.pi if rev else 0.0) + rnd.choice(
            (0.0, 0.0, 0.1, -0.1))
        mover(rnd, w, k, x, y, hd, sp, back=back)
        ops.extend(lane_target(rnd, w, k, kr, j + (-1 if rev else 1),
                               rnd.choice((0, 1, 3, 6, 10, 20)), lat,
                               rev=rev))

    def put_list(me):
        cars = list(others)
        rnd.shuffle(cars)
        cars = cars[:rnd.choice((0, 1, 3, 6, 6))]
        ops.append("N 0 %d %s %s" % (len(cars),
                                     h(f32(rnd.uniform(0.8, 1.2))),
                                     h(f32(rnd.uniform(2.0, 2.6)))))
        for i, k in enumerate(cars):
            v = w.cars[k]
            lx, ly = frame(me, v["px"], v["py"])
            if rnd.random() < 0.1:
                lx, ly = rnd.uniform(-3.0, 3.0), rnd.uniform(-5.0, 30.0)
            ops.append("E %d %s %s %s %s %s %s %d" % (
                i, h(f32(lx)), h(f32(ly)), h(f32(rnd.uniform(-5.0, 5.0))),
                h(f32(rnd.uniform(-5.0, 5.0))),
                h(f32(rnd.uniform(0.8, 1.3))),
                h(f32(rnd.uniform(2.0, 2.8))), k))
        return len(cars)

    me, j0, lat0 = place_me()
    for k in others:
        place(k, me, j0)
    nl = put_list(me)
    ops.append("D 0 %d 0 00000000" % j0)
    for _ in range(30):
        r = rnd.random()
        if r < 0.15:
            me, j0, lat0 = place_me()
            nl = put_list(me)
        elif r < 0.45:
            place(rnd.choice(others), me, j0)
            if rnd.random() < 0.5:
                nl = put_list(me)
        if rnd.random() < 0.3:
            ops.append("G TIMER %08x" % rnd.choice((0, 1000, 5000)))
        if rnd.random() < 0.15:
            ops.append("G TRAFFIC %08x" % rnd.choice((0, 1)))
        if rnd.random() < 0.15:
            ops.append("G SECS %s" % h(f32(rnd.choice((2.0, 0.5, 4.0)))))
            ops.append("G DEF %s" % h(f32(rnd.choice((20.0, 8.0, 60.0)))))
        if rnd.random() < 0.2:
            ops.append("Z 0 %d" % rnd.choice([-1] + others))
        for e in range(nl):
            if rnd.random() < 0.3:
                ops.append("5 %d" % e)
        for _ in range(rnd.choice((1, 2, 3))):
            ops.append("6 %d %s" % (rnd.choice(others), h(f32(rnd.choice((
                0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 5.0, 10.0, -1.0))))))
        if rnd.random() < 0.08:
            # Who's bounds on the count. Past 20 the target overflows, so
            # only Who sees it, and then my car is placed again.
            ops.append("S %d" % rnd.choice((0, -1, 21, 20, 100)))
            ops.append("7 %s 0" % h(f32(5.0)))
            me, j0, lat0 = place_me()
            nl = put_list(me)
        if rnd.random() < 0.06:
            ops.append("D -1 -1 0 00000000")
        elif rnd.random() < 0.1:
            ops.append("D 0 %d 0 00000000" % j0)
        ops.append("7 %s %d" % (h(f32(rnd.choice((0.5, 2.0, 3.0, 5.0,
                                                   10.0)))),
                                1 if rnd.random() < 0.05 else 0))
    return ops


def s_parts(rnd):
    """IntervalOverlap, TimeIntervalForSeparatingAxis and
    WhenWillOverlapOccur2D on their own, at every edge, and
    MakeOBBsForDriveTarget over targets of every length and none."""
    w = World(rnd)
    ops = w.ops

    def fv(*c):
        return h(f32(rnd.choice(c)))

    ends = (-9999.0, -5.0, -1.0, -0.5, 0.0, 0.0, 0.5, 1.0, 2.0, 5.0, 9999.0,
            99999.0)
    for _ in range(150):
        e = [rnd.choice(ends + (rnd.uniform(-10.0, 10.0),)) for _ in range(4)]
        if rnd.random() < 0.6:
            e[0], e[1] = min(e[0], e[1]), max(e[0], e[1])
            e[2], e[3] = min(e[2], e[3]), max(e[2], e[3])
        ops.append("1 " + " ".join(h(f32(x)) for x in e))
    still = 9.99999975e-05
    for _ in range(150):
        v = rnd.choice((0.0, still, -still, f32(still * 1.0000001),
                        f32(still * 0.9999999), -f32(still * 1.0000001),
                        rnd.uniform(-30.0, 30.0), rnd.uniform(-0.01, 0.01)))
        d = rnd.choice((0.0, 2.0, -2.0, rnd.uniform(-50.0, 50.0)))
        r = rnd.choice((abs(d), 2.0, rnd.uniform(0.0, 8.0), 0.0))
        ops.append("2 %s %s %s" % (h(f32(v)), h(f32(d)), h(f32(r))))
    for _ in range(250):
        boxes = []
        for _b in range(2):
            a = rnd.uniform(-math.pi, math.pi)
            ax = [math.cos(a), math.sin(a), -math.sin(a), math.cos(a)]
            if rnd.random() < 0.25:
                # Axes no turn makes. A box from MakeOBBs is turned, and
                # then each cosine across is the other's size.
                b = rnd.uniform(-math.pi, math.pi)
                ax[2:] = [math.cos(b), math.sin(b)]
            boxes += ax + [
                      rnd.choice((2.3, rnd.uniform(0.5, 4.0), -2.0)),
                      rnd.choice((1.0, rnd.uniform(0.3, 2.0)))]
        dx, dy = rnd.uniform(-30.0, 30.0), rnd.uniform(-30.0, 30.0)
        if rnd.random() < 0.2:
            dx, dy = rnd.uniform(-2.0, 2.0), rnd.uniform(-2.0, 2.0)
        sp = rnd.choice((0.0, 1e-5, rnd.uniform(0.0, 40.0)))
        if rnd.random() < 0.7:
            # Mostly closing on each other.
            ln = math.hypot(dx, dy) or 1.0
            vx, vy = -dx / ln * sp, -dy / ln * sp
            vx += rnd.uniform(-3.0, 3.0)
            vy += rnd.uniform(-3.0, 3.0)
        else:
            vx, vy = rnd.uniform(-30.0, 30.0), rnd.uniform(-30.0, 30.0)
        if rnd.random() < 0.1:
            vx = 0.0
        ops.append("3 " + " ".join(h(f32(x)) for x in
                                   boxes + [dx, dy, vx, vy]))
    # The edges no draw lands on: ends that touch, -0 against 0, and two
    # square boxes 2 m apart on x, closing or parting at 1 m/s, which touch
    # at -0 and at 0.
    ops += ["1 00000000 3f800000 80000000 40000000",
            "1 00000000 3f800000 3f800000 40000000",
            "1 3f800000 40000000 00000000 3f800000",
            "1 80000000 00000000 00000000 3f800000",
            "1 00000000 3f800000 80000000 80000000",
            "1 bf800000 3f800000 80000000 00000000"]
    sq = "3f800000 00000000 00000000 3f800000 3f800000 3f800000"
    for v in ("bf800000", "3f800000"):
        ops.append("3 %s %s 40000000 00000000 %s 00000000" % (sq, sq, v))
    pts = w.route(0, 30, rnd.randrange(50), turn=rnd.choice((0.0, 0.1)))
    for k in range(3):
        p = pts[rnd.randrange(5)]
        mover(rnd, w, k, p["x"], p["y"], heading_of(p), 10.0)
    for _ in range(40):
        if rnd.random() < 0.3:
            k = rnd.randrange(3)
            p = pts[rnd.randrange(5)]
            mover(rnd, w, k, p["x"], p["y"], rnd.uniform(-3.2, 3.2), 10.0)
        t = rnd.choice((-1, -1, 0, 1, 2))
        n = rnd.choice((0, 1, 2, 5, 12, 20))
        ops.extend(lane_target(rnd, w, t, 0, rnd.randrange(8), n,
                               rnd.uniform(-4.0, 4.0),
                               rev=rnd.random() < 0.2))
        z = rnd.choice((0, 0, 0, 0, 1, 2))
        ops.append("4 %d %d %s %d" % (t, rnd.choice((0, 1, 2, 2, -1)),
                                      fv(1.0, 1.3, 1000.0, 0.0, -1.0),
                                      z))
    # A box inside out on each axis in turn, so the half sizes' fabsf
    # shows.
    for ax in (0, 1, 2):
        p = pts[rnd.randrange(5)]
        mover(rnd, w, 0, p["x"], p["y"], heading_of(p), 10.0, flip=ax)
        ops.extend(lane_target(rnd, w, -1, 0, rnd.randrange(8), 3, 0.0))
        for sc_ in ("3f800000", "bf800000"):
            ops.append("4 -1 0 %s 0" % sc_)
    return ops


def exact_target(w, k, kr, j, n, lat, rev=False, picked=True):
    """Car k's own target (k -1: the target): n points on route kr's own
    points from j, `lat` across in the route's frame, nothing jittered.
    With `picked`, the first point is cached as the one picked at time 0
    and the blend's time is 0, so at WorldTimer 0 neither GetFirstPoint
    nor the blend touches it."""
    pts = w.pts[kr]
    if k < 0:
        ops = ["T 0 00000000"]
    else:
        ops = ["H %d 0 00000000 0 0 0" % k if picked
               else "H %d 0 00000000 0 1000 1000" % k]
    for i in range(n):
        jj = j - i if rev else j + i
        if not 0 <= jj < len(pts):
            break
        x, y = beside(pts[jj], lat)
        f = "%s %s 00000000 %d %d 0 00000000" % (h(f32(x)), h(f32(y)),
                                                 w.rn[kr], jj)
        ops.append(("Y " if k < 0 else "I %d " % k) + f)
    return ops


# A backing car's actions, accident recovery twice.
BACK_ACTS = (-1, 5, 7, 10, 10, 11, 0, 6)


def s_meet(rnd):
    """WillIHitThisCar where the two cars do meet, a second or more on:
    head on, catching one up, at a crossing, one backing into the other,
    both at one speed on the route's own points (so their legs end
    together), and both crawling apart, where a step runs past 99999.
    Who over the same two, either side of the hit."""
    w = World(rnd)
    ops = w.ops
    pts = w.route(0, 40, rnd.randrange(50), smooth=True,
                  turn=rnd.choice((0.0, 0.0, 0.02, -0.02)))
    jc = rnd.randrange(18, 26)
    pc = pts[jc]
    hd1 = heading_of(pc) + rnd.choice((math.pi / 2, -math.pi / 2, 0.8,
                                       2.3))
    # Straight, so the crossing is its point 15.
    w.route(1, 30, rnd.randrange(50, 70), smooth=True, turn=0.0,
            x=pc["x"] - 150.0 * math.cos(hd1),
            y=pc["y"] - 150.0 * math.sin(hd1), hd=hd1)

    def flip():
        return rnd.choice((None,) * 8 + (0, 1, 2))

    def place(k, kr, j, lat, along, rev, sp, back=False, **kw):
        p = w.pts[kr][max(0, min(len(w.pts[kr]) - 1, j))]
        x, y = beside(p, lat, along)
        hd = heading_of(p) + (math.pi if rev else 0.0)
        return mover(rnd, w, k, x, y, hd, sp, back=back, flip=flip(), **kw)

    for _ in range(18):
        kind = rnd.choice(("headon", "catch", "cross", "cross", "back_me",
                           "back_me", "back_it", "back_it", "even", "slow"))
        timer = rnd.choice((7000, 7000, 7000, 0))
        lat = rnd.choice((-3.5, 0.0, 3.5))
        vm = rnd.choice((5.0, 10.0, 15.0, 20.0, 30.0))
        vi = rnd.choice((0.0, 4.0, 8.0, 12.0, 20.0, 28.0))
        when = rnd.uniform(0.6, 4.0)
        j0 = rnd.randrange(3, 8)
        kr, rev, back_me, back_it = 0, False, False, False
        lat_i = lat + rnd.uniform(-0.8, 0.8)
        along_i = rnd.uniform(-3.0, 3.0)
        mine = its = None
        kw_me, kw_it = {}, {}
        if kind == "cross":
            j0 = max(1, jc - max(1, int(round(vm * when / 10.0))))
            arrive = (jc - j0) * 10.0 / vm
            vi = rnd.choice((8.0, 12.0, 20.0, 28.0))
            dist = vi * arrive + rnd.uniform(-4.0, 4.0)
            n10 = int(dist // 10.0)
            kr, ji = 1, max(0, 15 - n10)
            along_i = -(dist - 10.0 * n10)
            lat_i = rnd.uniform(-2.0, 2.0)
        elif kind == "headon":
            ji = j0 + max(2, int(round((vm + vi) * when / 10.0)))
            rev = True
        elif kind == "catch":
            vi = min(vi, vm * 0.6)
            ji = j0 + 1 + max(1, int(round((vm - vi) * when / 10.0)))
        elif kind == "back_me":
            ji = j0 - rnd.choice((1, 2, 3))
            vm = rnd.choice((3.0, 6.0, 10.0, 15.0))
            vi = rnd.choice((0.0, 0.0, 4.0, 10.0))
            rev = rnd.random() < 0.3
            back_me = True
            kw_me["act"] = rnd.choice(BACK_ACTS)
            if rnd.random() < 0.3:
                # Under 1 m/s, so predicted along my body, away from it:
                # it catches mine up sooner or later by my speed.
                kw_me["vmag"] = -vm
                vi = rnd.choice((4.0, 10.0))
                rev = False
        elif kind == "back_it":
            ji = j0 + rnd.choice((1, 2, 3))
            vm = rnd.choice((0.0, 0.0005, 5.0, 10.0))
            vi = rnd.choice((3.0, 6.0, 10.0, 15.0))
            back_it = True
            kw_it["ctl"] = rnd.choice((1, 2, 2, 3, 3, 4))
            kw_it["act"] = rnd.choice(BACK_ACTS)
            if rnd.random() < 0.4:
                # Under 1 m/s, so predicted along its body, away from me:
                # mine catches it up, or not, by its speed.
                kw_it["vmag"] = -vi
                vm = rnd.choice((5.0, 10.0))
        elif kind == "even":
            vm = vi = rnd.choice((10.0, 20.0))
            ji = j0 + rnd.choice((2, 3, 4, 6))
            rev = rnd.random() < 0.6
            lat_i, along_i = lat, 0.0
            timer = 0
            kw_me.update(dtype=2, pl=0)
            kw_it.update(dtype=2, pl=0)
            mine = exact_target(w, -1, 0, j0 + 1, rnd.choice((4, 8, 12)),
                                lat)
            its = exact_target(w, 1, 0, ji - 1 if rev else ji + 1,
                               rnd.choice((4, 8, 12)), lat, rev=rev)
        else:
            # Both crawl, 0.001 m/s, apart: my first leg is 3 mm, so 3 s,
            # and the next two legs are 150 m, so the second step is past
            # 99999, never overlapping.
            ji = j0 - 2
            vm, vi = 0.0005, 0.0
            rev = True
            lat_i, along_i = lat, 0.0
            timer = 0
            kw_me.update(dtype=2, ctl=2, pl=0)
            kw_it.update(dtype=2, ctl=2, pl=0)
            p = pts[j0]
            a = beside(p, lat, 0.003)
            b = beside(p, lat, 150.003)
            mine = ["T 0 00000000"] + [
                "Y %s %s 00000000 %d %d 0 00000000" % (
                    h(f32(q[0])), h(f32(q[1])), w.rn[0], j0) for q in (a, b)]
            c = beside(pts[ji], lat, -150.0)
            its = ["H 1 0 00000000 0 0 0",
                   "I 1 %s %s 00000000 %d %d 0 00000000" % (
                       h(f32(c[0])), h(f32(c[1])), w.rn[0], ji)]
        if kind in ("headon", "catch", "cross") and rnd.random() < 0.4:
            # Traffic off the road, its target blended unless it is just
            # driving.
            kw_it.update(dtype=3, pl=0,
                         oob=rnd.choice((-0.25, -0.2501, -0.3, -1.0, 0.0)),
                         act=rnd.choice((5, 5, 5, 7, 10, -1, 0, 6)))
        ops.append("G TIMER %08x" % timer)
        ops.append("G TRAFFIC %08x" % (1 if rnd.random() < 0.1 else 0))
        me = place(0, 0, j0, lat, rnd.uniform(-1.0, 1.0)
                   if kind not in ("even", "slow") else 0.0, False, vm,
                   back=back_me, **kw_me)
        place(1, kr, ji, lat_i, along_i, rev, vi, back=back_it, **kw_it)
        if mine is None:
            n = rnd.choice((0, 3, 6, 10, 20))
            mine = lane_target(rnd, w, -1, 0, j0 + 1, n, lat)
        if its is None:
            n = rnd.choice((0, 3, 6, 10, 20))
            step = -1 if rev else 1
            its = lane_target(rnd, w, 1, kr, ji + step, n,
                              -lat_i if rev else lat_i, rev=rev)
        ops.extend(mine)
        ops.extend(its)
        lx, ly = frame(me, w.cars[1]["px"], w.cars[1]["py"])
        ops.append("N 0 1 %s %s" % (h(f32(rnd.uniform(0.8, 1.2))),
                                    h(f32(rnd.uniform(2.0, 2.6)))))
        ops.append("E 0 %s %s 00000000 00000000 %s %s 1" % (
            h(f32(lx)), h(f32(ly)), h(f32(rnd.uniform(0.8, 1.3))),
            h(f32(rnd.uniform(2.0, 2.8)))))
        ops.append("D 0 %d 0 00000000" % j0)
        for _w in range(2):
            ops.append("6 1 %s" % h(f32(rnd.choice((0.5, 1.0, 2.0, 3.0, 5.0,
                                                    10.0)))))
        ops.append("7 %s 0" % h(f32(rnd.choice((0.5, 1.0, 1.5, 2.0, 3.0,
                                                5.0)))))
    return ops


def s_stopped(rnd):
    """IsThisCarStoppedDirectlyInFrontOfMe either side of each bound:
    speeds either side of 5 m/s both ways, entries either side of the box
    across and of the 23 m ahead, and far behind."""
    w = World(rnd)
    ops = w.ops
    speeds = (0.0, 4.99, 5.0, 5.01, 8.0, -2.0, -4.99, -5.0, -5.01, -8.0)
    for k in range(7):
        w.car(k, vmag=rnd.choice(speeds))
    for _ in range(10):
        hl, hd = rnd.uniform(0.8, 1.2), rnd.uniform(2.0, 2.6)
        ops.append("N 0 6 %s %s" % (h(f32(hl)), h(f32(hd))))
        for i in range(6):
            L, D = rnd.uniform(0.8, 1.3), rnd.uniform(2.0, 2.8)
            lx = rnd.uniform(-1.3, 1.3) * (hl + L)
            r = rnd.random()
            if r < 0.45:
                ly = (hd + D) + 23.0 + rnd.uniform(-4.0, 1.0)
            elif r < 0.65:
                ly = -rnd.uniform(25.0, 60.0)
            else:
                ly = rnd.uniform(-10.0, 35.0)
            ops.append("E %d %s %s 00000000 00000000 %s %s %d" % (
                i, h(f32(lx)), h(f32(ly)), h(f32(L)), h(f32(D)),
                rnd.randrange(1, 7)))
        for i in range(6):
            ops.append("5 %d" % i)
        if rnd.random() < 0.5:
            w.car(rnd.randrange(1, 7), vmag=rnd.choice(speeds))
    return ops


# ---------------------------------------- choosing a new choice (11b-4b)


def boxed(rnd, w, k):
    """Car k's box, angle and acceleration, about its heading."""
    v = w.cars[k]
    w.ops.append(extras(rnd, k, math.atan2(v["by"], v["bx"])))


def seen_list(rnd, w, cars):
    """The list: my car (0) and an entry for each of `cars`, where my car
    sees it, now and then anywhere."""
    me = w.cars[0]
    ops = ["N 0 %d %s %s" % (len(cars), h(f32(rnd.uniform(0.8, 1.2))),
                             h(f32(rnd.uniform(2.0, 2.6))))]
    for i, k in enumerate(cars):
        v = w.cars[k]
        lx, ly = frame(me, v["px"], v["py"])
        if rnd.random() < 0.1:
            lx, ly = rnd.uniform(-3.0, 3.0), rnd.uniform(-5.0, 30.0)
        ops.append("E %d %s %s %s %s %s %s %d" % (
            i, h(f32(lx)), h(f32(ly)), h(f32(rnd.uniform(-5.0, 5.0))),
            h(f32(rnd.uniform(-5.0, 5.0))), h(f32(rnd.uniform(0.8, 1.3))),
            h(f32(rnd.uniform(2.0, 2.8))), k))
    return ops


# A hundred, for the oncoming car whose sides both fail and whose wider
# way round then wins (mn-opp-side, mn-opp-extra, mn-opp-pref): 24 never
# made one.
N_CHOOSE = 100
# Its own targets' cached picks. -1 would have WillIHitThisCar read the
# box before its array, on retail's stack and in the port's static.
PICKS = (0, 0, 1, 2, 7, 19)
OUTS = ("00000000", "00000001", "a5a5a5a5")
MAX_TIMES = (0.5, 1.0, 2.0, 3.0, 5.0)


def s_choose(rnd):
    """MakeNewChoice, TryToDriveAroundCar, TryChoice and IsDriveable: my
    car among four others on walk_world's routes, ahead on the line,
    oncoming, alongside, stopped and off the road, each with a box and a
    target of its own; from every choice, with the current one tried
    first and not, the lines to consider and the speed for them either
    side of what matters, the traffic tuning mode on and off."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=rnd.randint(0, 4))
    if w.sign_points and rnd.random() < 0.4:
        kl, js = rnd.choice(w.sign_points)
        jl = max(0, js - rnd.randrange(1, 6))
    else:
        kl, jl = 0, rnd.randrange(0, 10)
    line = rnd.randrange(LINES)
    others = [1, 2, 3, 4]

    def me():
        place_me(rnd, w, 0, kl, jl, line,
                 ctl=rnd.choice((0, 1, 2, 3, 3)),
                 act=rnd.choice((-1, 0, 5, 6)))
        boxed(rnd, w, 0)
        ops.extend(its_target(rnd, w, sizes, 0, kl, jl, picks=PICKS))

    def other(k):
        place_other(rnd, w, sizes, k, kl, jl, rnd.random() < 0.6,
                    span=rnd.choice((4, 7, 7, 12)), picks=PICKS)
        boxed(rnd, w, k)

    me()
    for k in others + [5]:
        other(k)
    ops += seen_list(rnd, w, others)
    ops += decide(rnd, w)
    # The scratch target starts empty and then keeps whatever the last op
    # built in it, as the controller's own does from frame to frame.
    scratch = "T %d %s" % (rnd.choice((0, 9, 40)), h(f32(rnd.uniform(0.0, 60.0))))
    ops.append(scratch)
    for _ in range(14):
        if rnd.random() < 0.1:
            ops.append(scratch)
        r = rnd.random()
        if r < 0.3:
            other(rnd.choice(others))
            ops += seen_list(rnd, w, others)
        elif r < 0.4:
            me()
            ops += seen_list(rnd, w, others)
        if rnd.random() < 0.3:
            ops.append("G TIMER %08x" % rnd.choice((0, 1000, 5000, 77777)))
        if rnd.random() < 0.25:
            ops.append("G TRAFFIC %08x" % rnd.choice((0, 1)))
        if rnd.random() < 0.3:
            ops.append("G MINSPEED %s" % h(f32(rnd.choice((
                20.0, 0.0, 4.95, 5.0, 25.0, 100.0)))))
        if rnd.random() < 0.3:
            ops.append("G NLINES %08x" % rnd.choice((0, 1, 2, 4)))
        if rnd.random() < 0.1:
            ops.append("G SECS %s" % h(f32(rnd.choice((2.0, 0.5, 6.0)))))
            ops.append("G DEF %s" % h(f32(rnd.choice((20.0, 60.0)))))
        ops.append("D %d %d %d 00000000" % (
            kl, max(0, jl + rnd.choice((0, 0, 1, -1))),
            line if rnd.random() < 0.8 else rnd.randrange(LINES)))
        t = rnd.choice((0, 1, 2, 3, 4, 5, 6, 5, 6, 7))
        if t in (5, 6):
            k = rnd.choice(others + [5])
        else:
            k = rnd.choice((-1, -1, -1, 1))
        ops.append("X %d %d %d" % (t, k, rnd.choice((0, 0, 1))))
        mx = h(f32(rnd.choice(MAX_TIMES)))
        what = rnd.choice(("8", "9", "0", "0", "0", "V", "V"))
        if what == "8":
            ops.append("8 %d %d %s" % (rnd.choice((0, 1)),
                                       rnd.choice((0, 0, 1, 2, 3)), mx))
        elif what == "9":
            ops.append("9 %d %s %d %s %s %d" % (
                rnd.choice((0, 1)), mx, rnd.choice((0, 0, 1)),
                h(f32(rnd.choice((-1.0, -1.0, 0.0, 0.5, 2.0)))),
                h(f32(rnd.choice((99999.0, 1.0, 0.0)))),
                rnd.choice([-1, k, k] + others)))
        elif what == "0":
            ops.append("0 %s %d %s" % (mx, rnd.choice((0, 1, 1)),
                                       rnd.choice(OUTS)))
        else:
            ops.append("V %d %s %d %s" % (rnd.randrange(len(others)), mx,
                                          rnd.choice((0, 1, 1)),
                                          rnd.choice(OUTS)))
        if rnd.random() < 0.2:
            ops += decide(rnd, w)
    return ops


N_JAM = 24
# 0, so that a hit at once is not driveable by a hair; 99999, which a
# target that hits nothing gives too.
JAM_MAX_TIMES = (0.0, 0.0, 1.0, 3.0, 5.0, 99999.0)
# Backing at under 1 m/s scores a target between -1 and -1/1.2: a
# preferred one then scores below -1.
JAM_BACKING = (-0.85, -0.9, -0.95, -0.99)


def s_jam(rnd, max_times=JAM_MAX_TIMES):
    """MakeNewChoice and TryToDriveAroundCar in a jam: a car in my lane just
    ahead, under 5 m/s or not, so that every target hits it at once when it
    is; a car coming the other way in the next lane; two more about. The
    current choice is mostly a side of the car ahead and is tried first, so
    that its preferred side is kept as the way round when nothing will do.
    Now and then my car backs at under 1 m/s, and the longest times asked
    take in 0 and 99999."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=rnd.randint(0, 2))
    kl, jl = 0, rnd.randrange(0, 12)
    line = rnd.randrange(LINES)
    others = [1, 2, 3, 4]

    def me():
        p = w.pts[kl][jl]
        if rnd.random() < 0.35:
            x, y = beside(p, off_of(p, line) + rnd.uniform(-1.0, 1.0), 1.0)
            mover(rnd, w, 0, x, y, heading_of(p), rnd.choice(JAM_BACKING),
                  back=True, ctl=rnd.choice((0, 1, 2, 3, 3)),
                  dtype=rnd.choice((2, 2, 3, 3, 4, 0)),
                  act=rnd.choice((-1, 0, 5, 6)), oob=0.0, rpr=kl, rpj=jl)
        else:
            place_me(rnd, w, 0, kl, jl, line,
                     ctl=rnd.choice((0, 1, 2, 3, 3)),
                     act=rnd.choice((-1, 0, 5, 6)))
            boxed(rnd, w, 0)
        ops.extend(its_target(rnd, w, sizes, 0, kl, jl, picks=PICKS))

    def ahead():
        j = min(sizes[kl] - 2, jl + rnd.choice((1, 1, 2, 3)))
        p = w.pts[kl][j]
        x, y = beside(p, off_of(p, line) + rnd.uniform(-1.0, 1.0),
                      rnd.uniform(-3.0, 3.0))
        mover(rnd, w, 1, x, y,
              heading_of(p) + rnd.choice((0.0, 0.0, 0.1, -0.1)),
              rnd.choice((0.0, 2.0, 4.99, 5.0, 5.01, 8.0, 15.0)),
              oob=rnd.choice((0.0, 0.0, -0.3)), rpr=kl, rpj=j)
        ops.extend(its_target(rnd, w, sizes, 1, kl, j, picks=PICKS))

    def oncoming():
        j = min(sizes[kl] - 2, jl + rnd.randrange(1, 6))
        p = w.pts[kl][j]
        x, y = beside(p, off_of(p, line) + rnd.choice((-3.5, 3.5))
                      + rnd.uniform(-1.0, 1.0), rnd.uniform(-3.0, 3.0))
        mover(rnd, w, 2, x, y,
              heading_of(p) + math.pi + rnd.choice((0.0, 0.0, 0.1, -0.1)),
              rnd.choice((8.0, 15.0, 25.0, 35.0)),
              oob=rnd.choice((0.0, 0.0, -0.3)), rpr=kl, rpj=j)
        ops.extend(its_target(rnd, w, sizes, 2, kl, j, reverse=True,
                              picks=PICKS))

    def other(k):
        place_other(rnd, w, sizes, k, kl, jl, rnd.random() < 0.6,
                    span=rnd.choice((4, 7, 7, 12)), picks=PICKS)
        boxed(rnd, w, k)

    me()
    ahead()
    oncoming()
    other(3)
    other(4)
    ops += seen_list(rnd, w, others)
    ops += decide(rnd, w)
    ops.append("T %d %s" % (rnd.choice((0, 9, 40)),
                            h(f32(rnd.uniform(0.0, 60.0)))))
    for _ in range(12):
        r = rnd.random()
        if r < 0.45:
            rnd.choice((me, ahead, ahead, oncoming,
                        lambda: other(rnd.choice((3, 4)))))()
            ops += seen_list(rnd, w, others)
        if rnd.random() < 0.3:
            ops.append("G TIMER %08x" % rnd.choice((0, 1000, 5000, 77777)))
        if rnd.random() < 0.15:
            ops.append("G TRAFFIC %08x" % rnd.choice((0, 1)))
        if rnd.random() < 0.2:
            ops.append("G NLINES %08x" % rnd.choice((0, 1, 2)))
        ops.append("D %d %d %d 00000000" % (
            kl, max(0, jl + rnd.choice((0, 0, 1, -1))),
            line if rnd.random() < 0.8 else rnd.randrange(LINES)))
        t = rnd.choice((5, 6, 5, 6, 5, 6, 1, 0))
        k = rnd.choice((1, 1, 1, 2, 3)) if t in (5, 6) else -1
        ops.append("X %d %d %d" % (t, k, rnd.choice((0, 0, 0, 1))))
        mx = h(f32(rnd.choice(max_times)))
        what = rnd.choice(("0", "0", "0", "V", "V", "8"))
        if what == "8":
            ops.append("8 %d %d %s" % (rnd.choice((0, 1)),
                                       rnd.choice((0, 0, 1)), mx))
        elif what == "0":
            ops.append("0 %s %d %s" % (mx, rnd.choice((1, 1, 1, 0)),
                                       rnd.choice(OUTS)))
        else:
            ops.append("V %d %s %d %s" % (rnd.choice((0, 0, 1, 2, 3)), mx,
                                          rnd.choice((1, 1, 1, 0)),
                                          rnd.choice(OUTS)))
    return ops




N_PASS = 8


def s_pass(rnd):
    """MakeNewChoice going past cars coming the other way at speed: my car
    at 15 to 50 m/s on its line, one oncoming car up to 3 m either side of
    it and three more anywhere across the road, so that a swerve one way
    fits its corners and the other way does not, and a car whose left side
    scores and right side does not is not tried a third time."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=0)
    kl, jl = 0, rnd.randrange(0, 12)
    line = rnd.randrange(LINES)
    others = [1, 2, 3, 4]

    def me():
        p = w.pts[kl][jl]
        x, y = beside(p, off_of(p, line) + rnd.uniform(-0.5, 0.5), 1.0)
        mover(rnd, w, 0, x, y, heading_of(p),
              rnd.choice((15.0, 20.0, 25.0, 30.0, 40.0, 50.0)),
              ctl=rnd.choice((0, 1, 2, 3, 3)), dtype=rnd.choice((2, 2, 3, 0)),
              act=rnd.choice((-1, 0, 5, 6)), oob=0.0, rpr=kl, rpj=jl)
        ops.extend(its_target(rnd, w, sizes, 0, kl, jl, picks=PICKS))

    def oncoming(k, near):
        j = min(sizes[kl] - 2, jl + rnd.randrange(1, 4))
        p = w.pts[kl][j]
        lat = off_of(p, line) + (rnd.uniform(0.3, 3.0) * rnd.choice((1, -1))
                                 if near else rnd.uniform(-8.0, 8.0))
        x, y = beside(p, lat, rnd.uniform(-3.0, 3.0))
        mover(rnd, w, k, x, y,
              heading_of(p) + math.pi + rnd.choice((0.0, 0.0, 0.1, -0.1)),
              rnd.choice((5.01, 8.0, 15.0, 25.0, 35.0)),
              oob=0.0, rpr=kl, rpj=j)
        ops.extend(its_target(rnd, w, sizes, k, kl, j, reverse=True,
                              picks=PICKS))

    me()
    for k in others:
        oncoming(k, k == 1)
    ops += seen_list(rnd, w, others)
    ops += decide(rnd, w)
    ops.append("T %d %s" % (rnd.choice((0, 9, 40)),
                            h(f32(rnd.uniform(0.0, 60.0)))))
    for _ in range(12):
        if rnd.random() < 0.5:
            rnd.choice((me, lambda: oncoming(1, True),
                        lambda: oncoming(rnd.choice((2, 3, 4)), False)))()
            ops += seen_list(rnd, w, others)
        if rnd.random() < 0.3:
            ops.append("G TIMER %08x" % rnd.choice((0, 1000, 5000, 77777)))
        ops.append("D %d %d %d 00000000" % (kl, jl, line))
        t = rnd.choice((0, 1, 2, 5, 6))
        k = rnd.choice((2, 3)) if t in (5, 6) else -1
        ops.append("X %d %d %d" % (t, k, 0))
        ops.append("0 %s %d %s" % (h(f32(rnd.choice((0.5, 1.0, 3.0)))),
                                   rnd.choice((0, 1)), rnd.choice(OUTS)))
    return ops

# mn-rle's tie. With nothing found, MakeNewChoice goes round the car in the
# way when the current choice's hit, less 0.1, is no later than the way
# round's, and `<=` and `<` part only where the two are one float. s_jam's
# 59th scenario from TIE_SEED, its longest times all 99999 so that nothing
# is driveable, has its third MakeNewChoice's current choice hit the
# oncoming car 0.083 s on and the way round hit at once. Car 2's speed,
# found by bisection over its floats, makes the current choice's hit 0.1f
# exactly; 0x40cab903 does too, and the floats either side do not.
TIE_SEED = 11
TIE_INDEX = 58
TIE_CALL = 3
TIE_SPEED = 0x40cab904


def s_tie():
    rnd = random.Random(TIE_SEED)
    for _ in range(TIE_INDEX + 1):
        ops = s_jam(rnd, max_times=(99999.0,))
    calls = [i for i, op in enumerate(ops) if op.startswith("0 ")]
    ops = ops[:calls[TIE_CALL - 1] + 1]
    k = max(i for i, op in enumerate(ops) if op.startswith("C 2 "))
    f = ops[k].split()
    f[7] = "%08x" % TIE_SPEED
    ops[k] = " ".join(f)
    return ops

# Step 11d-1's.
N_ACTIONS = 120
ACT_KINDS = ("jd", "jd", "dr", "dr", "nc", "bl", "ar", "ar")
# WorldTimer's ticks after the last time stored, either side of the edges:
# a second is 4000, so JustDrive's three seconds are 12000 and
# AccidentRecovery's five 20000.
ACT_DELTAS = (0, 1, 2000, 3999, 4000, 4001, 11999, 12000, 12001, 19999,
              20000, 20001, 40000, -1, -12000)
ACT_TIMEOUTS = (0.0, -0.0, 1.0, 1.0, 3.0, 5.0, -1.0, 0.5)
UPRIGHT = 0.707000017
NAN = 0x7fc00000


def fstep(v, n):
    """The float n ulps above v, a positive float (below for n < 0)."""
    return struct.unpack("<f", struct.pack("<I", fb(f32(v)) + n))[0]


def act_list(rnd, w, others):
    """The list as Think builds it, in order down the road, with my car (0)
    among the rest at its own origin. The car just ahead of mine sits at
    Draft's edges: across, either side of the two half widths together;
    on, either side of 6 m. Answers the ops, and that car and its y."""
    me = w.cars[0]
    hl = f32(rnd.uniform(0.8, 1.2))
    order = list(others)
    rnd.shuffle(order)
    mine = rnd.choice((0, 1, 1, 2, len(order)))
    order.insert(mine, 0)
    ops = ["N 0 %d %s %s" % (len(order), h(hl),
                             h(f32(rnd.uniform(2.0, 2.6))))]
    ahead = None
    for i, k in enumerate(order):
        if k == 0:
            lx = ly = vx = vy = 0.0
            hl2, hd2 = hl, f32(rnd.uniform(2.0, 2.6))
        else:
            v = w.cars[k]
            lx, ly = frame(me, v["px"], v["py"])
            vx, vy = rnd.uniform(-5.0, 5.0), rnd.uniform(-5.0, 5.0)
            hl2 = f32(rnd.uniform(0.8, 1.3))
            hd2 = f32(rnd.uniform(2.0, 2.8))
            if i == mine - 1:
                edge = f32(hl + hl2)
                lx = rnd.choice((0.0, edge, -edge, fstep(edge, -1),
                                 -fstep(edge, -1), fstep(edge, 1),
                                 rnd.uniform(-edge, edge),
                                 rnd.uniform(-4.0, 4.0), lx))
                ly = f32(rnd.choice((6.0, fstep(6.0, -1), fstep(6.0, 1), 0.0,
                                     -2.0, 3.0, 5.5, rnd.uniform(0.0, 6.0),
                                     12.0, ly)))
                ahead = (k, ly)
        ops.append("E %d %s %s %s %s %s %s %d" % (
            i, h(f32(lx)), h(f32(ly)), h(f32(vx)), h(f32(vy)), h(hl2),
            h(hd2), k))
    return ops, ahead


def s_actions(rnd):
    """The five actions as AIDriver drives them, on s_choose's world: each
    made, asked for its points (JustDrive's IsDriveable and
    BuildDriveTarget, Draft's and AccidentRecovery's BuildDriveTarget), its
    status and its three tests, its name and its score, and destroyed; the
    clock either side of each edge after the last time stored; the car
    just ahead of mine at Draft's edges, and its speed at the gap's; and my
    car's wheels, up axis and the ground's normal under it at
    AccidentRecovery's."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=rnd.randint(0, 4))
    if w.sign_points and rnd.random() < 0.4:
        kl, js = rnd.choice(w.sign_points)
        jl = max(0, js - rnd.randrange(1, 6))
    else:
        kl, jl = 0, rnd.randrange(0, 10)
    line = rnd.randrange(LINES)
    others = [1, 2, 3, 4]
    clock = [rnd.choice((0, 0, 5000, 0x7ffff000))]

    def me():
        place_me(rnd, w, 0, kl, jl, line,
                 ctl=rnd.choice((0, 1, 2, 3, 3)),
                 act=rnd.choice((-1, 0, 5, 6)))
        boxed(rnd, w, 0)
        ops.extend(its_target(rnd, w, sizes, 0, kl, jl, picks=PICKS))

    def other(k):
        place_other(rnd, w, sizes, k, kl, jl, rnd.random() < 0.6,
                    span=rnd.choice((4, 7, 7, 12)), picks=PICKS)
        boxed(rnd, w, k)

    def tilt():
        """My car's up axis and the ground's normal under it: straight up
        with the normal's z either side of 0.707, or both anywhere."""
        s = rnd.choice((1.0, 1.0, 2.0, 0.5, -1.0))
        if rnd.random() < 0.5:
            up = (0.0, 0.0, s, rnd.choice((0.0, 1.0)))
            nz = rnd.choice((UPRIGHT, fstep(UPRIGHT, 1), fstep(UPRIGHT, -1),
                             1.0, 0.0, 0.5, -0.9))
            nx = math.sqrt(1.0 - nz * nz) * rnd.choice((1.0, -1.0))
            nrm = (nx, 0.0, nz, 0.0)
        else:
            def unit():
                a = rnd.uniform(-math.pi, math.pi)
                b = rnd.uniform(0.0, math.pi)
                return (math.sin(b) * math.cos(a), math.sin(b) * math.sin(a),
                        math.cos(b))
            u = unit()
            up = (s * u[0], s * u[1], s * u[2], rnd.uniform(-1.0, 1.0))
            nrm = unit() + (0.0,)
            if rnd.random() < 0.6:
                # Near 45 degrees from the axis.
                c = rnd.choice((0.78, 0.785, 0.79, 0.3))
                t = unit()
                d = sum(x * y for x, y in zip(t, u))
                p = [x - d * y for x, y in zip(t, u)]
                n = math.sqrt(sum(x * x for x in p)) or 1.0
                nrm = tuple(math.cos(c) * y + math.sin(c) * x / n
                            for x, y in zip(p, u)) + (0.0,)
        ops.append("@up 0 %s" % " ".join(h(f32(x)) for x in up))
        ops.append("@nr 0 %s" % " ".join(h(f32(x)) for x in nrm))

    def info():
        lops, ahead = act_list(rnd, w, others)
        ops.extend(lops)
        if ahead is not None and rnd.random() < 0.7:
            k, ly = ahead
            gap = f32(20.0 - ly)
            v = dict(w.cars[k])
            v["vmag"] = rnd.choice((gap, fstep(gap, -1), fstep(gap, 1), 0.0,
                                    30.0, 10.0))
            w.car(k, **v)
        ops.append("D %d %d %d %s" % (
            kl, max(0, jl + rnd.choice((0, 0, 1, -1))),
            line if rnd.random() < 0.8 else rnd.randrange(LINES),
            rnd.choice(("00000000", "00000000", "00001388"))))
        t = rnd.choice((0, 1, 1, 2, 3, 4, 5, 6, 7))
        k = rnd.choice(others) if t in (5, 6) else rnd.choice((-1, -1, 1))
        ops.append("X %d %d %d" % (t, k, rnd.choice((0, 0, 1))))
        ops.append("@J")

    def tick(base=None):
        if base is not None:
            clock[0] = base
        clock[0] = (clock[0] + rnd.choice(ACT_DELTAS)) & M32
        ops.append("G TIMER %08x" % clock[0])

    me()
    for k in others + [5]:
        other(k)
    tilt()
    ops += decide(rnd, w)
    ops.append("G TIMER %08x" % clock[0])
    info()
    for _ in range(5):
        kind = rnd.choice(ACT_KINDS)
        if rnd.random() < 0.5:
            tick()
        made = clock[0]
        # JustDrive's last re-evaluation, as near as the script can tell.
        last = [0]
        ops.append("@n %s %d %s %d" % (
            kind, rnd.choice((0, 100, 500, -1)),
            h(f32(rnd.choice(ACT_TIMEOUTS))), rnd.choice((-1, 0, 1, 2))))
        for _ in range(rnd.randint(4, 10)):
            r = rnd.random()
            if r < 0.3:
                # From the action's own times: the timeout's, the
                # re-evaluation's and the reset's, or onwards.
                tick(rnd.choice((None, made, made,
                                 last[0] if kind == "jd" else made)))
            elif r < 0.36:
                tilt()
            elif r < 0.42:
                ops.append("@w 0 %d" % rnd.choice((0, 1, 2, 3, 4, 4, 5)))
            elif r < 0.48:
                info()
            elif r < 0.51:
                me()
                info()
            elif r < 0.6:
                f = rnd.choice(("can", "dt", "pt", "ds", "ds", "exp", "tt",
                                "tol", "udl", "tb", "bo")
                               + (("t608",) if kind in ("jd", "ar") else ())
                               + (("r612",) * 2 if kind == "ar" else ()))
                if f in ("can", "pt", "r612", "udl", "tb", "bo"):
                    v = rnd.choice((0, 1, 2))
                elif f in ("exp", "t608"):
                    v = (clock[0] - rnd.choice(ACT_DELTAS)) & M32
                else:
                    v = fb(f32(rnd.choice((0.0, -1.0, 1.0, 3.0, 5.0, 30.0))))
                    if rnd.random() < 0.1:
                        v = NAN
                if f == "t608":
                    last[0] = v
                ops.append("@f %s %08x" % (f, v))
            elif r < 0.66:
                k = rnd.choice(("jd", "dr", "nc", "bl", "ar"))
                if k == "dr":
                    ops.append("@sc dr %d" % rnd.choice((0, 0, 1, 2, 5)))
                else:
                    ops.append("@sc %s" % k)
            elif r < 0.69:
                ops.append("@par 0 %s" % h(f32(rnd.choice(
                    (UPRIGHT, UPRIGHT, 0.0, -0.5, 0.99)))))
            elif r < 0.72:
                ops.append("G AVOID %s" % h(f32(rnd.choice(
                    (2.0, 0.5, 5.0, 0.0)))))
            else:
                op = rnd.choice(("@cp", "@cp", "@cp", "@cp", "@us", "@us",
                                 "@t", "@t", "@nm"))
                if op == "@cp":
                    if kind == "dr" and rnd.random() < 0.6:
                        info()
                    if kind == "jd" and s32(clock[0] - last[0]) >= 12000:
                        last[0] = clock[0]
                ops.append(op)
        if rnd.random() < 0.3:
            ops += decide(rnd, w)
        if rnd.random() < 0.6:
            ops.append("@d %d" % rnd.choice((0, 1, 1, 3)))
    return ops


def s_act_edges(rnd):
    """The exact cases the random actions miss. NudgeCar's and Block's
    HasExpired, each asked before any points: at a timeout that cannot
    expire (-1), at exactly the timeout (4000 ticks for 1 s, from a clock
    SetTimeout keeps exactly) and just past it, and with a NaN poked over a
    timeout that can expire. PointsToDriveWillExecuteAction is poked to 0
    first: the constructors leave it as the slot was. AccidentRecovery's score and accomplishment
    with the ground's normal between 0.5 and 0.707 of the car's up, and
    about both."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=0)
    line = rnd.randrange(LINES)
    others = [1, 2, 3, 4]
    place_me(rnd, w, 0, 0, 3, line, ctl=2, act=-1)
    boxed(rnd, w, 0)
    ops.extend(its_target(rnd, w, sizes, 0, 0, 3, picks=PICKS))
    for k in others + [5]:
        place_other(rnd, w, sizes, k, 0, 3, True, span=7, picks=PICKS)
        boxed(rnd, w, k)
    lops, _ = act_list(rnd, w, others)
    ops.extend(lops)
    ops.append("D 0 3 %d 00000000" % line)
    ops.append("X 1 -1 0")
    ops.append("@J")
    base = 5000
    for kind in ("nc", "bl"):
        for timeout, poke, delta in ((-1.0, None, 0), (-1.0, None, 4001),
                                     (-1.0, None, -1), (1.0, None, 4000),
                                     (1.0, None, 3999), (1.0, None, 4001),
                                     (1.0, NAN, 4001), (1.0, NAN, 0),
                                     (0.0, NAN, 1)):
            ops.append("G TIMER %08x" % base)
            ops.append("@n %s 300 %s 1" % (kind, h(f32(timeout))))
            if poke is not None:
                ops.append("@f dt %08x" % poke)
            # The slot's own fill would answer the points test first.
            ops.append("@f pt 00000000")
            ops.append("G TIMER %08x" % ((base + delta) & M32))
            ops += ["@t", "@us", "@cp", "@t", "@d 1"]
    ops.append("G TIMER %08x" % base)
    ops.append("@up 0 %s" % " ".join(h(f32(x)) for x in (0.0, 0.0, 1.0, 0.0)))
    for nz in (0.6, 0.69, 0.51, 0.5, fstep(0.5, 1), 0.45, 0.75,
               fstep(UPRIGHT, 1)):
        nx = math.sqrt(1.0 - nz * nz)
        ops.append("@nr 0 %s" % " ".join(h(f32(x))
                                         for x in (nx, 0.0, nz, 0.0)))
        ops += ["@w 0 0", "@sc ar", "@w 0 1", "@sc ar",
                "@n ar 500 %s 0" % h(f32(5.0)), "@w 0 4", "@t", "@us",
                "@cp", "@d 1"]
    return ops


# Step 11d-2's.
N_PASS_AVOID = 50
# WorldTimer's ticks after a time the action stored, either side of its
# edges: AvoidCars' re-evaluation every 0.3 s (1200), its least lifetime of
# the seconds it was made with and 2 more (8000, 9000, 10000 and 12000 for
# 0, 0.25, 0.5 and 1), and Pass's 3 s (12000).
PA_DELTAS = (0, 1, 600, 1199, 1200, 1201, 2000, 4000, 7999, 8000, 8001,
             8999, 9000, 9001, 9999, 10000, 10001, 11999, 12000, 12001,
             40000, -1, -1200)
AC_SECS = (0.0, 0.25, 0.5, 1.0, 1.0, 1.5, 2.0, -2.0, 99999.0)
# The race's start before the clock: the grace period's 12 s (48000) and
# a driver numbered 120's 2 s (8000), either side.
GRACE_AGO = (0, 1000, 7999, 8000, 8001, 47999, 48000, 48001, 100000, -4000)


def s_pass_avoid(rnd, kind):
    """Pass or AvoidCars as AIDriver drives them, on s_actions' world: made
    for each car (AvoidCars always for one), asked for its points, its
    status, its tests, its name and its score, and destroyed; the clock
    either side of each edge after the times it stored, and of the grace
    period's end; my car and the rest either side of the slow speeds and
    the speed for the line, blinking or not, the camera on my car or not,
    and the look-ahead times moved."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=rnd.randint(0, 4))
    if w.sign_points and rnd.random() < 0.4:
        kl, js = rnd.choice(w.sign_points)
        jl = max(0, js - rnd.randrange(1, 6))
    else:
        kl, jl = 0, rnd.randrange(0, 10)
    line = rnd.randrange(LINES)
    others = [1, 2, 3, 4]
    clock = [rnd.choice((0, 5000, 100000, 0x7ffff000))]
    dn0 = rnd.choice((0, 0, 3, 101, 120))
    nlist = [0]

    def me():
        kw = {}
        if rnd.random() < 0.3:
            kw["vmag"] = rnd.choice((9.99, 10.0, 10.01, 0.0))
        place_me(rnd, w, 0, kl, jl, line,
                 ctl=rnd.choice((0, 1, 2, 3, 3)),
                 act=rnd.choice((-1, 0, 5, 6)), dn=dn0, **kw)
        boxed(rnd, w, 0)
        ops.extend(its_target(rnd, w, sizes, 0, kl, jl, picks=PICKS))

    def other(k):
        place_other(rnd, w, sizes, k, kl, jl, rnd.random() < 0.6,
                    span=rnd.choice((4, 7, 7, 12)), picks=PICKS)
        boxed(rnd, w, k)

    def info():
        if rnd.random() < 0.85:
            lops, _ = act_list(rnd, w, others)
            nlist[0] = len(others) + 1
        else:
            lops = seen_list(rnd, w, others)
            nlist[0] = len(others)
        ops.extend(lops)
        ops.append("D %d %d %d %s" % (
            kl, max(0, jl + rnd.choice((0, 0, 1, -1))),
            line if rnd.random() < 0.8 else rnd.randrange(LINES),
            rnd.choice(("00000000", "00000000", "00001388"))))
        t = rnd.choice((0, 1, 1, 2, 3, 4, 5, 6, 7))
        k = rnd.choice(others) if t in (5, 6) else rnd.choice((-1, -1, 1))
        ops.append("X %d %d %d" % (t, k, rnd.choice((0, 0, 1))))
        ops.append("@J")

    def tick(base=None):
        if base is not None:
            clock[0] = base
        clock[0] = (clock[0] + rnd.choice(PA_DELTAS)) & M32
        ops.append("G TIMER %08x" % clock[0])

    def race():
        ops.append("R %08x" % ((clock[0] - rnd.choice(GRACE_AGO)) & M32))

    me()
    for k in others + [5]:
        other(k)
    ops += decide(rnd, w)
    ops.append("G TIMER %08x" % clock[0])
    if rnd.random() < 0.5:
        ops.append("G CAM %08x" % dn0)
    race()
    info()
    for _ in range(4):
        if rnd.random() < 0.5:
            tick()
        made = clock[0]
        last = [made]
        score = rnd.choice((0, 300, 400, -1))
        timeout = h(f32(rnd.choice(ACT_TIMEOUTS)))
        if kind == "pa":
            ops.append("@n pa %d %s %d %s" % (
                score, timeout, rnd.choice((-1, 1, 2, 3, 4, 5)),
                h(f32(rnd.uniform(0.0, 3.0)))))
        else:
            secs = fb(f32(rnd.choice(AC_SECS)))
            if rnd.random() < 0.05:
                secs = NAN
            # Never no car: the grace period reads it.
            ops.append("@n ac %d %s %d %08x %d %d" % (
                score, timeout, rnd.choice((0, 1, 2, 3, 4, 5)), secs,
                rnd.choice((0, 1)), rnd.choice((0, 1))))
        for _ in range(rnd.randint(5, 12)):
            r = rnd.random()
            if r < 0.25:
                tick(rnd.choice((None, made, made, last[0])))
            elif r < 0.29:
                race()
            elif r < 0.37:
                info()
            elif r < 0.4:
                me()
                info()
            elif r < 0.44:
                other(rnd.choice(others))
                info()
            elif r < 0.49:
                k = rnd.choice(others + [0, 5])
                d = rnd.choice((0.0, 0.25, 1.0, 2.0))
                ops.append("@bk %d %08x %s" % (k, rnd.choice((
                    0, 0x7fffffff, clock[0], (clock[0] - 1000) & M32,
                    (clock[0] - 3999) & M32, (clock[0] - 4000) & M32,
                    (clock[0] - 4001) & M32, (clock[0] + 1000) & M32)),
                    h(f32(d))))
            elif r < 0.57:
                fs = ["can", "dt", "pt", "ds", "exp", "tt", "tol", "udl",
                      "tb", "bo"]
                fs += ["o616"] * 2 if kind == "pa" else [
                    "o616", "o620", "o620", "o624", "o624", "o628", "o632"]
                f = rnd.choice(fs)
                if f in ("can", "pt", "udl", "tb", "bo") or (
                        kind == "ac" and f in ("o616", "o632")):
                    v = rnd.choice((0, 1, 2))
                elif f in ("exp", "o620", "o624") or (
                        kind == "pa" and f == "o616"):
                    v = (clock[0] - rnd.choice(PA_DELTAS)) & M32
                    if f == "o620":
                        last[0] = v
                else:
                    v = fb(f32(rnd.choice((0.0, -1.0, 1.0, 2.0, 3.0, 5.0,
                                           30.0))))
                    if rnd.random() < 0.1:
                        v = NAN
                ops.append("@f %s %08x" % (f, v))
            elif r < 0.65:
                ops.append("@sc %s" % rnd.choice((kind, kind, "pa", "ac")))
            elif r < 0.69:
                ops.append("@so %d %d" % (rnd.randrange(nlist[0]),
                                          rnd.choice((0, 1, 1, 2))))
            elif r < 0.75:
                g = rnd.choice(("AVOID", "PASS", "MINSPEED", "CAM", "CAM",
                                "GRACE"))
                if g == "AVOID":
                    v = h(f32(rnd.choice((2.0, 0.5, 5.0, 0.0, 99999.0))))
                elif g == "PASS":
                    v = h(f32(rnd.choice((3.0, 0.5, 1.0, 6.0, 0.0))))
                elif g == "MINSPEED":
                    v = h(f32(rnd.choice((20.0, 0.0, 4.95, 5.0, 25.0))))
                elif g == "CAM":
                    v = "%08x" % (rnd.choice((-1, dn0, dn0, 0, 5)) & M32)
                else:
                    v = h(f32(rnd.choice((12.0, 0.0, 2.0))))
                ops.append("G %s %s" % (g, v))
            else:
                op = rnd.choice(("@cp", "@cp", "@cp", "@cp", "@us", "@us",
                                 "@t", "@t", "@nm", "@ga"))
                if op == "@cp" and s32(clock[0] - last[0]) > 1200:
                    last[0] = clock[0]
                ops.append(op)
        if rnd.random() < 0.3:
            ops += decide(rnd, w)
        if rnd.random() < 0.6:
            ops.append("@d %d" % rnd.choice((0, 1, 1, 3)))
    return ops


# The edges s_pass_avoid's random draws miss, one kind of scenario each.
PA_EDGE_KINDS = ("pa-score", "pa-hba", "pa-hf", "pa-cp", "ac-time",
                 "ac-null", "ac-close", "ac-care", "ac-stand", "ac-side")
N_PA_EDGES = 8
# A car stopped just ahead: IsThisCarStoppedDirectlyInFrontOfMe answers a
# hit at 0 for it, so nothing is driveable and IsMyDrivingChoiceOkay is 0.
BLOCKER = 4


def zero_box(rnd, w, k):
    """Car k's box, as boxed() makes it, with no acceleration."""
    v = w.cars[k]
    f = extras(rnd, k, math.atan2(v["by"], v["bx"])).split()
    f[2] = f[3] = h(0.0)
    w.ops.append(" ".join(f))


def s_pa_edge(rnd, kind):
    """Pass and AvoidCars at the edges of their tests, on s_pass_avoid's
    world with the list set by hand.

    pa-score: the car to pass ahead of mine in the list with x at y, 2y
    and -2y and either side, closing fast, the choice a line or either
    side of it, at speeds either side of the speed for the line.
    pa-hba: three seconds on, the car to pass behind at exactly 10 m past
    the two half lengths, either side, and between the half length's and
    the half width's sums and the 9 m and 10 m. pa-hf: inside the three
    seconds, the car level with mine (y 0), no car accelerating, so it
    cannot be caught. pa-cp: the points with the car at y 0 and behind,
    my car off its line out of the grace period, and a line choice that
    names a car.
    ac-time: AvoidCars' times far from Pass's, so hits between them count
    for one and not the other. ac-null: AvoidCars' time past 99999, with
    no car cared about. ac-close: a car stopped just ahead, and the car to
    avoid at the close test's edges (half my length, a tenth of a second
    on, across) or blinking, my car at the slow speed and either side.
    ac-care: the car to avoid behind, closing fast, and the choice's car
    cared about or not, made again or not. ac-stand: no location, no line
    and an empty target of my own, made again. ac-side: a slow car to the
    side, my car slow on a line, made again."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=0)
    jl = rnd.randrange(2, 12)
    line = rnd.randrange(LINES)
    p = w.pts[0][jl]
    clock = rnd.choice((100000, 200000))
    hl = f32(rnd.uniform(0.8, 1.2))
    hd = f32(rnd.uniform(2.0, 2.6))
    secs = h(f32(rnd.choice((0.0, 1.0, 2.0))))
    tout = h(f32(5.0))

    kw = dict(ctl=rnd.choice((1, 2, 2, 3)), act=-1, dn=0)
    sp = {"pa-score": (20.0, 25.0, 35.0, 10.0),
          "pa-cp": (10.0, 20.0, 30.0, 35.0),
          "ac-close": (20.0, 20.0, 10.0, 11.0, 5.0, 9.99, 12.0),
          "ac-care": (20.0, 35.0, 60.0),
          "ac-stand": (20.0, 35.0),
          "ac-side": (5.0, 8.0, 9.99)}.get(kind)
    if sp:
        kw["vmag"] = rnd.choice(sp)
    if kind == "pa-cp":
        kw["ctl"] = rnd.choice((1, 2))
        kw["px"], kw["py"] = beside(p, off_of(p, line) + rnd.choice(
            (-3.0, 3.0, 2.0, -1.5)), 1.0)
    place_me(rnd, w, 0, 0, jl, line, **kw)
    if kind == "pa-hf":
        zero_box(rnd, w, 0)
    else:
        boxed(rnd, w, 0)
    if kind == "ac-stand" and rnd.random() < 0.5:
        ops.append("H 0 %d %s 0 0 0" % (rnd.randrange(64), h(f32(20.0))))
    else:
        ops.extend(its_target(rnd, w, sizes, 0, 0, jl, picks=PICKS))
    for k in (1, 2, 3, 4, 5):
        place_other(rnd, w, sizes, k, 0, jl, True,
                    span=rnd.choice((4, 7)), picks=PICKS)
        if kind == "pa-hf" and k == 1:
            zero_box(rnd, w, k)
        else:
            boxed(rnd, w, k)

    def recar(k, **kw):
        v = dict(w.cars[k])
        v.update(kw)
        w.car(k, **v)

    def row(k, **kw):
        if k == 0:
            r = dict(lx=0.0, ly=0.0, vx=0.0, vy=0.0, hl2=hl, hd2=hd)
        else:
            v = w.cars[k]
            lx, ly = frame(w.cars[0], v["px"], v["py"])
            r = dict(lx=lx, ly=ly, vx=rnd.uniform(-5.0, 5.0),
                     vy=rnd.uniform(-5.0, 5.0),
                     hl2=f32(rnd.uniform(0.8, 1.3)),
                     hd2=f32(rnd.uniform(2.0, 2.8)))
        r.update(kw)
        r["k"] = k
        return r

    def behind(ks):
        return [row(k, ly=-15.0 - 4.0 * i) for i, k in enumerate(ks)]

    def info(rows, x, loc=None):
        ops.append("N 0 %d %s %s" % (len(rows), h(hl), h(hd)))
        for i, r in enumerate(rows):
            ops.append("E %d %s %s %s %s %s %s %d" % (
                i, h(f32(r["lx"])), h(f32(r["ly"])), h(f32(r["vx"])),
                h(f32(r["vy"])), h(f32(r["hl2"])), h(f32(r["hd2"])),
                r["k"]))
        ops.append(loc or "D 0 %d %d 00000000" % (jl, line))
        ops.append(x)
        ops.append("@J")

    def at(t):
        ops.append("G TIMER %08x" % (t & M32))

    def lines():
        return "X %d -1 0" % rnd.choice((1, 2, 3))

    ops += decide(rnd, w)
    at(clock)
    ops.append("R %08x" % ((clock - rnd.choice((100000, 100000, 0)))
                           & M32))
    if kind == "pa-score":
        recar(1, vmag=rnd.choice((30.0, 25.0, 20.5, 10.0)),
              ctl=rnd.choice((1, 2, 4, 4, 3)), pl=rnd.choice((0, 0, 1)))
        if rnd.random() < 0.3:
            ops.append("G MINSPEED %s" % h(f32(rnd.choice((0.0, 5.0)))))
        for _ in range(4):
            y = f32(rnd.uniform(3.0, 20.0))
            x = rnd.choice((f32(1.5 * y), y + y, -(y + y), f32(-3.0 * y),
                            f32(0.5 * y), fstep(y + y, -1), fstep(y + y, 1),
                            f32(1.99 * y), -fstep(y + y, -1)))
            rest = [2, 3, 4, 5]
            rows = [row(1, lx=x, ly=y, vx=rnd.uniform(-3.0, 3.0),
                        vy=rnd.choice((-60.0, -40.0, 60.0))), row(0)]
            rows += behind(rest) if rnd.random() < 0.5 else [
                row(k) for k in rest]
            info(rows, rnd.choice((lines(), "X 5 1 0", "X 6 1 0",
                                   "X 5 1 1", "X 6 1 0")))
            ops.append("@sc pa")
        ops += ["@n pa 300 %s 1 %s" % (tout, h(f32(1.0))), "@cp", "@t",
                "@d 1"]
    elif kind == "pa-hba":
        for _ in range(5):
            hd2 = f32(rnd.uniform(2.0, 2.8))
            s = f32(f32(hd + hd2) + 10.0)
            y = rnd.choice((-s, -s, -fstep(s, 1), -fstep(s, -1),
                            -f32(f32(hd + hd2) + 9.5), f32(-s + 0.4),
                            f32(-s + 0.2)))
            rows = [row(1, lx=rnd.uniform(-3.0, 3.0), ly=y, hd2=hd2),
                    row(0)] + [row(k) for k in (2, 3, 4, 5)]
            info(rows, rnd.choice((lines(), "X 5 1 0")))
            at(clock)
            ops.append("@n pa 300 %s 1 %s" % (tout, h(f32(1.0))))
            at(clock + rnd.choice((12000, 12001, 40000)))
            ops += ["@t", "@us", "@d 1"]
    elif kind == "pa-hf":
        for _ in range(4):
            rows = [row(1, lx=rnd.choice((0.0, 2.0, -4.0)),
                        ly=rnd.choice((0.0, 0.0, 0.001)), vx=0.0, vy=0.0),
                    row(0)] + [row(k) for k in (2, 3, 4, 5)]
            info(rows, lines())
            at(clock)
            ops.append("@n pa 300 %s 1 %s" % (tout, h(f32(1.0))))
            at(clock + rnd.choice((0, 1, 4000, 11999)))
            ops += ["@t", "@d 1"]
    elif kind == "pa-cp":
        for _ in range(4):
            y = rnd.choice((0.0, 0.0, -3.0, -0.5, 5.0, -10.0))
            rows = [row(1, ly=y), row(0)] + [row(k) for k in (2, 3, 4, 5)]
            if rnd.random() < 0.5:
                rows[0], rows[1] = rows[1], rows[0]
            info(rows, rnd.choice(("X 1 1 0", "X 2 1 0", "X 2 3 0",
                                   lines(), "X 5 1 0", "X 6 1 0")))
            ops += ["@n pa 300 %s 1 %s" % (tout, h(f32(1.0))), "@cp", "@t",
                    "@d 1"]
    elif kind == "ac-time":
        # My car and car 1 a few points on in one lane, each with a target
        # down it, car 1 slower: a hit a second or two on.
        ops.append("G AVOID %s" % h(f32(rnd.choice((5.0, 4.0)))))
        ops.append("G PASS %s" % h(f32(rnd.choice((0.0, 0.25, 0.5)))))
        lat = off_of(p, line) + rnd.uniform(-1.0, 1.0)
        x, y = beside(p, lat, 1.0)
        a = heading_of(p)
        recar(0, px=x, py=y, bx=math.cos(a), by=math.sin(a), vmag=20.0,
              vx=20.0 * math.cos(a), vy=20.0 * math.sin(a), fs=20.0)
        j = min(sizes[0] - 8, jl + rnd.choice((1, 2, 3)))
        pj = w.pts[0][j]
        v = rnd.choice((6.0, 8.0, 10.0, 15.0))
        x, y = beside(pj, lat + rnd.uniform(-0.5, 0.5))
        a = heading_of(pj)
        recar(1, px=x, py=y, bx=math.cos(a), by=math.sin(a), vmag=v,
              vx=v * math.cos(a), vy=v * math.sin(a), fs=v, oob=0.0,
              ctl=rnd.choice((1, 2, 4)), act=-1, nw=4)
        for k, j0 in ((0, jl + 1), (1, j + 1)):
            ops.append("H %d %d %s 0 0 0" % (k, rnd.randrange(64),
                                             h(f32(40.0))))
            for i in range(6):
                jj = min(sizes[0] - 1, j0 + i)
                f = tgt_point(w, 0, jj, lat, line, sp=20.0).split()
                ops.append("I %d %s" % (k, " ".join(f[1:])))
        for _ in range(3):
            rows = [row(1), row(0)] + behind([2, 3, 4, 5])
            info(rows, rnd.choice((lines(), "X 5 1 0", "X 6 1 0")))
            ops.append("@sc ac")
        at(clock)
        ops += ["@n ac 400 %s %d %s 0 0" % (tout, rnd.randint(1, 4), secs),
                "@cp"]
        at(clock + 1201)
        ops.append("@cp")
        at(clock + 2402)
        ops += ["@cp", "@t", "@d 1"]
    elif kind == "ac-null":
        ops.append("G AVOID %s" % h(f32(rnd.choice((200000.0, 1.0e6)))))
        for _ in range(3):
            rows = [row(0)] + behind([1, 2, 3, 4, 5])
            info(rows, rnd.choice((lines(), "X 5 1 0")),
                 rnd.choice((None, None, "D -1 -1 %d 00000000" % line)))
            ops.append("@sc ac")
    elif kind == "ac-close":
        recar(BLOCKER, vmag=0.0, pl=0)
        for case in ("half", "half-l", "half-k", "look-k", "look-x", "real",
                     "across", "blink", "slow", "slow"):
            hl2 = f32(rnd.uniform(0.8, 1.3))
            ctl = 1 if case in ("half", "half-l", "half-k", "look-k",
                                "look-x") else rnd.choice((1, 2, 3, 4))
            recar(1, vmag=rnd.choice((0.0, 3.0, 4.99) if case == "slow"
                                     else (20.0, 5.01, 0.0)),
                  ctl=ctl, pl=0, dtype=rnd.choice((1, 2, 3, 4)))
            x, y, vx, vy = {
                "half": (0.0, f32(hd * 0.5), 0.0, 0.0),
                "half-l": (0.0, f32((hl + hd) * 0.25), 0.0, 0.0),
                "half-k": (0.0, f32(hd * 0.55), 0.0, 0.0),
                "look-k": (0.0, f32(hd * 0.5 - 2.0), 0.0, 15.0),
                "look-x": (0.0, f32(hd * 0.5 - 1.0), 0.0, 20.0),
                "real": (0.0, 0.5, 0.0, 0.0),
                "across": (rnd.choice((1.0, -1.0))
                           * f32(f32(hl + hl2) + 1.0), 3.0, 0.0, 0.0),
                "blink": (0.0, 3.0, 0.0, 0.0),
                "slow": (0.0, 3.0, 0.0, 0.0)}[case]
            rows = [row(BLOCKER, lx=0.0, ly=3.0, vx=0.0, vy=0.0, hl2=1.0,
                        hd2=2.0),
                    row(1, lx=x, ly=y, vx=vx, vy=vy, hl2=hl2), row(0)]
            rows += [row(k) for k in (2, 3, 5)]
            info(rows, rnd.choice((lines(), lines(), "X 5 4 0")))
            if case == "blink":
                ops.append("@bk 1 %08x %s" % ((clock - 1000) & M32,
                                              h(f32(2.0))))
            at(clock)
            ops += ["@n ac 400 %s 1 %s 0 0" % (tout, secs), "@cp", "@t",
                    "@d 1"]
            ops.append("@bk 1 00000000 %s" % h(0.0))
    elif kind == "ac-care":
        recar(BLOCKER, vmag=0.0, pl=0)
        recar(1, vmag=20.0, ctl=1, pl=0)
        for _ in range(3):
            rows = [row(BLOCKER, lx=0.0, ly=3.0, vx=0.0, vy=0.0, hl2=1.0,
                        hd2=2.0),
                    row(1, lx=0.0, ly=-12.0, vx=0.0, vy=150.0), row(0)]
            rows += [row(k) for k in (2, 3, 5)]
            x = rnd.choice(("X 5 4 0", "X 6 4 0", lines(), lines(),
                            "X 1 4 0", "X 2 4 0", "X 5 2 0"))
            info(rows, x)
            at(clock)
            ops += ["@n ac 400 %s 1 %s 0 0" % (tout, secs), "@cp"]
            info(rows, x)
            at(clock + 1201)
            ops += ["@cp", "@t", "@d 1"]
    elif kind == "ac-stand":
        for _ in range(3):
            rows = [row(0)] + behind([1, 2, 3, 4, 5])
            x = rnd.choice(("X 0 -1 0", "X 0 -1 0", lines()))
            ln = rnd.choice((line, -1, -1, 3))
            info(rows, x, "D -1 -1 %d 00000000" % ln)
            at(clock)
            ops.append("@n ac 400 %s 1 %s 0 0" % (tout, secs))
            # With no line, MakeNewChoice's current choice is what its
            # stack held, which the model clears (MAKE_NEW_CURRENT).
            at(clock + 1201)
            ops += ["@cp", "@t", "@d 1"]
    else:
        # ac-side
        ops.append("G AVOID %s" % h(f32(rnd.choice((0.0, 0.25, 0.5, 2.0)))))
        j = min(sizes[0] - 2, jl + rnd.randrange(1, 4))
        pj = w.pts[0][j]
        car_at_point(rnd, w, 1, 0, j, off_of(pj, line)
                     + rnd.choice((1.0, -1.0)) * rnd.uniform(3.0, 6.0), True,
                     vmag=rnd.choice((0.0, 3.0, 4.9)),
                     oob=rnd.choice((0.0, -0.5, -0.5)), rpr=0, rpj=j, pl=0,
                     ctl=rnd.choice((1, 2, 3)))
        boxed(rnd, w, 1)
        for _ in range(3):
            # Beside my lane, so not stopped in front of me.
            rows = [row(1, lx=rnd.choice((1.0, -1.0))
                        * rnd.uniform(3.0, 5.0)), row(0)]
            rows += behind([2, 3, 4, 5])
            info(rows, lines())
            at(clock)
            ops.append("@n ac 400 %s 1 %s 0 0" % (tout, secs))
            at(clock + 1201)
            ops += ["@cp", "@t", "@d 1"]
    return ops


# Step 11d-3a's.
N_PULL_HIT = 40
# WorldTimer's ticks after a time the action stored, either side of its
# edges: IJustGotHit's re-evaluation every 0.2 s (800), PullOver's every
# 0.3 s (1200), and the pull-over timeouts' 1, 2 and 5 s.
PH_DELTAS = (0, 1, 799, 800, 801, 1199, 1200, 1201, 2000, 3999, 4000, 4001,
             7999, 8000, 8001, 19999, 20000, 20001, 40000, -1, -800)
# PullOver's own timeout: none (-999, or within 0.001 of it, which is 16
# ulps either way where 17 is past it), or seconds from when it was made.
PO_TIMEOUTS = (-999.0, -999.0, -fstep(999.0, 16), -fstep(999.0, -16),
               -fstep(999.0, 17), -fstep(999.0, -17), 0.0, 1.0, 2.0, 5.0,
               5.0, -1.0)
# My car's speeds, either side of PullOver's 15, and where braking comes
# to about its 0.5.
PH_SPEEDS = (0.0, 0.5, 1.5, 2.0, 2.5, 3.0, 10.0, 14.0, fstep(15.0, -1), 15.0,
             fstep(15.0, 1), 20.0, 30.0)
# A cop's speeds either side of the 100 m it is seen from at 3.5 s.
LIGHTS_SPEED = f32(100.0 / 3.5)
COP_SPEEDS = (0.0, 20.0, LIGHTS_SPEED, fstep(LIGHTS_SPEED, 1),
              fstep(LIGHTS_SPEED, -1), 30.0, 40.0, 60.0)
# CopLights and the three bytes after it, which retail reads as a word.
LIGHTS = (0, 0, 1, 0x100, 0x10000, 0x1000000, 0xff00ff00)
GRAVITY = f32(9.80000019)


def max_decel(mass=1500.0):
    """CalculateMaxDeceleration with no downforce and both tyres' mu 1."""
    weight = f32(GRAVITY * f32(mass))
    return -f32(weight / f32(mass))


def speed_to(target, t, d=None):
    """The speed v nearest the one where v + d * t (d, braking, or a
    car's speed less t when d is None) comes to exactly `target`."""
    c = -f32(t) if d is None else f32(f32(d) * f32(t))
    v = f32(target - c)
    for n in (0, 1, -1, 2, -2, 3, -3):
        u = fstep(v, n)
        if f32(u + c) == target:
            return u
    raise SystemExit("no speed to %r" % target)


def s_pull_hit(rnd, kind):
    """PullOver or IJustGotHit as AIDriver drives them, on s_pass_avoid's
    world: made, asked for its points, its status, its tests, its name and
    its score, and destroyed. Between, my car's collisions (two cars' or
    not, with cars on the list, off it, mine and none), its skill and its
    type info; the chopper, the AI cops, the players and each car's cop
    lights; my car near the road's right edge and past it, drifting out;
    PullOver's location clear; and the clock either side of each edge
    after the times the action stored."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=rnd.randint(0, 4))
    if w.sign_points and rnd.random() < 0.4:
        kl, js = rnd.choice(w.sign_points)
        jl = max(0, js - rnd.randrange(1, 6))
    else:
        kl, jl = 0, rnd.randrange(0, 10)
    line = rnd.randrange(LINES)
    others = [1, 2, 3, 4]
    cars = others + [0, 5]
    clock = [rnd.choice((0, 5000, 100000, 0x7ffff000))]
    every = 1200 if kind == "po" else 800
    clear = [False]

    def colls():
        n = rnd.choice((0, 0, 1, 1, 2, 2, 3, 4))
        f = []
        for _ in range(n):
            a = 0 if rnd.random() < 0.85 else rnd.choice(others + [5])
            b = rnd.choice(others + others + [0, 5, -1])
            if rnd.random() < 0.5:
                a, b = b, a
            f.append(" %d %d %d" % (rnd.choice((1, 1, 1, 0)), a, b))
        ops.append("@col 0 %d%s" % (n, "".join(f)))

    def ti():
        v = (rnd.choice((1500.0, 1200.0, 2000.0, 900.0)),
             rnd.choice((0.0, 0.3, 0.5, 1.0)),
             rnd.choice((150.0, 60.0, 30.0, 10.0)),
             rnd.choice((1.0, 0.8, 1.2, 0.95)),
             rnd.choice((1.0, 0.8, 1.2, 0.95)),
             rnd.choice((0.0, 0.5, 2.0, 10.0)),
             rnd.choice((0.0, 0.5, 2.0, 10.0)))
        ops.append("@ti 0 %s" % " ".join(h(f32(x)) for x in v))

    def me():
        kw = dict(ctl=rnd.choice((3, 3, 3, 1, 2)) if kind == "po"
                  else rnd.choice((0, 1, 2, 3, 3)),
                  act=rnd.choice((-1, 0, 5, 6)), dn=rnd.choice((0, 3, 120)))
        if rnd.random() < 0.5:
            kw["vmag"] = rnd.choice(PH_SPEEDS)
        if rnd.random() < 0.25:
            # Near the right edge or past it, drifting out.
            p = w.pts[kl][jl]
            x, y = beside(p, p["rw"] + rnd.choice((-2.0, -0.5, -0.1, 0.5,
                                                   3.0)), 1.0)
            a = heading_of(p) + rnd.choice((-0.3, -0.1, 0.0, 0.2))
            sp = rnd.choice((0.5, 1.0, 5.0, 10.0, 20.0))
            kw.update(px=x, py=y, bx=math.cos(a), by=math.sin(a), vmag=sp,
                      vx=sp * math.cos(a), vy=sp * math.sin(a),
                      fs=rnd.choice((sp, sp, -sp, 0.0)))
        place_me(rnd, w, 0, kl, jl, line, **kw)
        boxed(rnd, w, 0)
        ops.extend(its_target(rnd, w, sizes, 0, kl, jl, picks=PICKS))
        colls()
        if rnd.random() < 0.6:
            ops.append("@sk 0 %d" % rnd.choice((-2, -2, -1, 0, 1, -3)))
        if rnd.random() < 0.4:
            ti()

    def other(k):
        place_other(rnd, w, sizes, k, kl, jl, rnd.random() < 0.6,
                    span=rnd.choice((4, 7, 7, 12)), picks=PICKS)
        boxed(rnd, w, k)
        if rnd.random() < 0.4:
            ops.append("@cl %d %08x" % (k, rnd.choice(LIGHTS)))

    def chopper():
        if rnd.random() < 0.3:
            ops.append("@ch none")
            return
        v = w.cars[0]
        d = rnd.choice((50.0, 149.0, 150.0, 151.0, 300.0))
        a = rnd.uniform(-math.pi, math.pi)
        ops.append("@ch %d %s %s" % (rnd.randrange(-1, 7),
                                     h(f32(v["px"] + d * math.cos(a))),
                                     h(f32(v["py"] + d * math.sin(a)))))

    def cops():
        if rnd.random() < 0.25:
            ops.append("@cm none")
            return
        es = ["-" if rnd.random() < 0.15 else "%d:%d" % (
            rnd.choice(cars), rnd.choice((0, 1, 2, 2, 3)))
            for _ in range(7)]
        ops.append("@cm %d %s" % (rnd.choice((0, 1, 2, 3, 4, 7)),
                                  " ".join(es)))

    def players():
        ops.append("@pl %d %d %d" % (rnd.choice((0, 0, 1, 2)),
                                     rnd.choice(cars), rnd.choice(cars)))

    def info():
        if rnd.random() < 0.85:
            lops, _ = act_list(rnd, w, others)
        else:
            lops = seen_list(rnd, w, others)
        ops.extend(lops)
        # IJustGotHit's heading reads the location's point, so only
        # PullOver's is ever clear.
        clear[0] = kind == "po" and rnd.random() < 0.12
        if clear[0]:
            ops.append("D -1 -1 %d 00000000" % line)
        else:
            ops.append("D %d %d %d %s" % (
                kl, max(0, jl + rnd.choice((0, 0, 1, -1))),
                line if rnd.random() < 0.8 else rnd.randrange(LINES),
                rnd.choice(("00000000", "00000000", "00001388"))))
        t = rnd.choice((0, 1, 1, 2, 3, 4, 5, 6, 7))
        k = rnd.choice(others) if t in (5, 6) else rnd.choice((-1, -1, 1))
        ops.append("X %d %d %d" % (t, k, rnd.choice((0, 0, 1))))
        ops.append("@J")

    def tick(base=None):
        if base is not None:
            clock[0] = base
        clock[0] = (clock[0] + rnd.choice(PH_DELTAS)) & M32
        ops.append("G TIMER %08x" % clock[0])

    me()
    for k in others + [5]:
        other(k)
    ops += decide(rnd, w)
    ops.append("G TIMER %08x" % clock[0])
    chopper()
    cops()
    players()
    info()
    for _ in range(4):
        if rnd.random() < 0.5:
            tick()
        made = clock[0]
        last = [made]
        score = rnd.choice((0, 400, 600, -1))
        timeout = h(f32(rnd.choice(ACT_TIMEOUTS)))
        if kind == "po":
            # The constructor reads the location's point unless the list
            # or the location is left out.
            z = rnd.choice((2, 3, 1)) if clear[0] else rnd.choice(
                (0, 0, 0, 1, 2, 3))
            pot = fb(f32(rnd.choice(PO_TIMEOUTS)))
            if rnd.random() < 0.05:
                pot = NAN
            ops.append("@n po %d %s -1 %08x %d" % (score, timeout, pot, z))
        else:
            ops.append("@n ij %d %s %d" % (
                score, timeout, rnd.choice(others + others + [0, 5, -1])))
        for _ in range(rnd.randint(5, 12)):
            r = rnd.random()
            if r < 0.22:
                tick(rnd.choice((None, made, made, last[0])))
            elif r < 0.3:
                info()
            elif r < 0.33:
                me()
                info()
            elif r < 0.37:
                other(rnd.choice(others))
                info()
            elif r < 0.43:
                colls()
            elif r < 0.47:
                rnd.choice((chopper, cops, players))()
            elif r < 0.5:
                ops.append("@cl %d %08x" % (rnd.choice(cars),
                                            rnd.choice(LIGHTS)))
            elif r < 0.53:
                ops.append("@sk 0 %d" % rnd.choice((-2, -2, -1, 0, 1)))
            elif r < 0.55:
                ti()
            elif r < 0.62:
                fs = ["can", "dt", "pt", "ds", "exp", "tt", "tol", "udl",
                      "tb", "bo", "r612", "r612"]
                if kind == "po":
                    fs += ["t608", "o616", "o616", "o620", "o620", "o624"]
                f = rnd.choice(fs)
                if f in ("can", "pt", "udl", "tb", "bo", "o616", "o620"):
                    v = rnd.choice((0, 1, 2))
                elif f in ("exp", "t608", "r612"):
                    v = (clock[0] - rnd.choice(PH_DELTAS)) & M32
                    if f == "r612":
                        last[0] = v
                elif f == "o624":
                    v = fb(f32(rnd.choice(PO_TIMEOUTS)))
                else:
                    v = fb(f32(rnd.choice((0.0, -1.0, 1.0, 2.0, 3.0, 5.0,
                                           30.0))))
                    if rnd.random() < 0.1:
                        v = NAN
                ops.append("@f %s %08x" % (f, v))
            elif r < 0.68:
                ops.append("@sc %s" % rnd.choice((kind, kind, "po", "ij")))
            elif r < 0.71:
                ops.append("G AVOID %s" % h(f32(rnd.choice(
                    (2.0, 0.5, 5.0, 0.0, 99999.0)))))
            else:
                op = rnd.choice(("@cp", "@cp", "@cp", "@cp", "@us", "@us",
                                 "@t", "@t", "@nm"))
                if op == "@cp" and s32(clock[0] - last[0]) > every:
                    last[0] = clock[0]
                ops.append(op)
        if rnd.random() < 0.3:
            ops += decide(rnd, w)
        if rnd.random() < 0.6:
            ops.append("@d %d" % rnd.choice((0, 1, 1, 3)))
    return ops


# The edges s_pull_hit's random draws miss, one kind of scenario each.
PH_EDGE_KINDS = ("po-chopper", "po-lights", "po-pot", "po-room", "po-hit",
                 "ij-score", "ij-cp", "ij-head")
N_PH_EDGES = 6


def s_ph_edge(rnd, kind):
    """PullOver and IJustGotHit at the edges of their tests.

    po-chopper: my car at the origin, the chopper in each plan at exactly
    150 m along an axis and an ulp either side. po-lights: the AI cops'
    and the players' cars at exactly the range their speed gives them
    (3.5 s, and no less than 100 m) and an ulp either side, lights on or
    off, cops none or disabled. po-pot: PullOver's own timeout 16 and 17
    ulps either side of -999, and its seconds exactly up and either side.
    po-room: a straight road along x, my car exactly 2 and 4 m of room
    from its right edge and an ulp either side, at 15 m/s and either
    side, and at the speeds where braking comes to exactly 0.5, careful
    or not. po-hit: a car stopped just ahead, or slower in my lane a
    second or so on, careful or not.
    ij-score: the collisions' cars at y either side of 0 and level, a car
    off the list, and an entry with no car. ij-cp: the car I hit at the
    player's two overlap edges, at y 0, head on or square to me, and at
    the speeds that come to exactly 20. ij-head: my car drifting out over
    the right edge, forwards and back."""
    w = World(rnd)
    ops = w.ops
    hl = f32(rnd.uniform(0.8, 1.2))
    hd = f32(rnd.uniform(2.0, 2.6))
    clock = rnd.choice((100000, 200000))
    tout = h(f32(5.0))
    line = rnd.randrange(LINES)

    def at(t):
        ops.append("G TIMER %08x" % (t & M32))

    def recar(k, **kw):
        v = dict(w.cars[k])
        v.update(kw)
        w.car(k, **v)

    def none_near():
        ops.extend(["@ch none", "@cm none", "@pl 0 0 0"])

    if kind == "po-room":
        # A straight road along x at y 0, 25 m each side, my car the only
        # one: room is 24 less my car's distance right of the line.
        jl = rnd.randrange(5, 20)
        pts = w.route(0, 40, rnd.randrange(50), x=-200.0, y=0.0, hd=0.0,
                      turn=0.0, smooth=True)
        p = pts[jl]
        hl = 1.0

        def mine(lat, v, ctl=3):
            w.car(0, px=p["x"] + 1.0, py=-lat, pz=0.0, bx=1.0, by=0.0,
                  vmag=v, dn=0, cls=0, dtype=3, ctl=ctl, oob=0.0, rpr=0,
                  rpj=jl, ct=0, cc=-1, cx=0, act=-1, pl=0, nw=4, vx=v,
                  vy=0.0, fs=v)
            boxed(rnd, w, 0)
            ops.append("H 0 %d %s 0 0 0" % (rnd.randrange(64), h(f32(20.0))))
            for i in range(6):
                f = tgt_point(w, 0, jl + 1 + i, lat, line, sp=14.0).split()
                ops.append("I 0 %s" % " ".join(f[1:]))
            ops.append("@col 0 %d%s" % rnd.choice(((0, ""), (0, ""),
                                                   (1, " 1 0 -1"),
                                                   (1, " 0 0 -1"))))
            ops.append("N 0 1 %s %s" % (h(hl), h(hd)))
            ops.append("E 0 0 0 0 0 %s %s 0" % (h(hl), h(hd)))
            ops.append("D 0 %d %d 00000000" % (jl, line))
            ops.append("X %d -1 0" % rnd.choice((1, 2, 3)))
            ops.append("@J")

        at(clock)
        none_near()
        gentle = speed_to(0.5, f32(0.12), max_decel())
        firm = speed_to(0.5, f32(0.2), max_decel())
        cases = []
        for lat in (22.0, fstep(22.0, 1), fstep(22.0, -1), 20.0,
                    fstep(20.0, 1), fstep(20.0, -1), 21.0, 23.0, 10.0):
            cases.append((lat, rnd.choice((10.0, 14.0, 15.0, 5.0)), 0))
        for v in (15.0, fstep(15.0, 1), fstep(15.0, -1)):
            cases.append((rnd.choice((21.0, 23.0, 10.0)), v, 0))
        for v in (firm, fstep(firm, 1), fstep(firm, -1)):
            cases.append((rnd.choice((21.0, 23.0)), v, 0))
        for v in (gentle, fstep(gentle, 1), fstep(gentle, -1), firm,
                  fstep(firm, 1), fstep(firm, -1)):
            cases.append((rnd.uniform(-5.0, 5.0), v, -2))
        for lat, v, sk in cases:
            mine(f32(lat), f32(v))
            ops.append("@sk 0 %d" % (sk if sk else rnd.choice((0, -1, -3))))
            at(clock)
            ops.append("@n po 600 %s -1 %s %d" % (
                tout, h(-999.0), rnd.choice((0, 0, 1))))
            if rnd.random() < 0.4:
                ops.append("@f o620 %08x" % rnd.choice((0, 1)))
            ops.append("@cp")
            # Inside the 0.3 s: no re-evaluation, so a poked choice holds.
            at(clock + rnd.choice((1, 1199)))
            if rnd.random() < 0.5:
                ops.append("@f o616 00000000")
            ops += ["@cp", "@t", "@d 1"]
        ops.append("@sk 0 0")
        mine(f32(21.0), f32(10.0), ctl=rnd.choice((1, 2)))
        ops += ["@sc po", "@n po 600 %s -1 %s 0" % (tout, h(-999.0)), "@t",
                "@us", "@cp", "@d 1"]
        return ops

    sizes = walk_world(rnd, w, nsigns=0)
    jl = rnd.randrange(2, 12)
    p = w.pts[0][jl]
    kw = dict(ctl=3 if kind.startswith("po") else rnd.choice((1, 2, 3)),
              act=-1, dn=0)
    if kind in ("ij-cp", "po-hit"):
        # Along the road, so not heading out of it.
        a = heading_of(p)
        v = rnd.choice((10.0, 20.0, 25.0))
        kw.update(bx=1.0 if kind == "ij-cp" else math.cos(a),
                  by=0.0 if kind == "ij-cp" else math.sin(a), vmag=v,
                  vx=v * math.cos(a), vy=v * math.sin(a), fs=v)
    place_me(rnd, w, 0, 0, jl, line, **kw)
    boxed(rnd, w, 0)
    ops.extend(its_target(rnd, w, sizes, 0, 0, jl, picks=PICKS))
    ops.append("@col 0 0")
    for k in (1, 2, 3, 4, 5):
        place_other(rnd, w, sizes, k, 0, jl, True,
                    span=rnd.choice((4, 7)), picks=PICKS)
        boxed(rnd, w, k)

    def row(k, **kw):
        if k == 0:
            r = dict(lx=0.0, ly=0.0, vx=0.0, vy=0.0, hl2=hl, hd2=hd)
        else:
            v = w.cars[k]
            lx, ly = frame(w.cars[0], v["px"], v["py"])
            r = dict(lx=lx, ly=ly, vx=rnd.uniform(-5.0, 5.0),
                     vy=rnd.uniform(-5.0, 5.0),
                     hl2=f32(rnd.uniform(0.8, 1.3)),
                     hd2=f32(rnd.uniform(2.0, 2.8)))
        r.update(kw)
        r["k"] = k
        return r

    def behind(ks):
        return [row(k, ly=-15.0 - 4.0 * i) for i, k in enumerate(ks)]

    def info(rows, x=None, loc=None):
        ops.append("N 0 %d %s %s" % (len(rows), h(hl), h(hd)))
        for i, r in enumerate(rows):
            ops.append("E %d %s %s %s %s %s %s %d" % (
                i, h(f32(r["lx"])), h(f32(r["ly"])), h(f32(r["vx"])),
                h(f32(r["vy"])), h(f32(r["hl2"])), h(f32(r["hd2"])),
                r["k"]))
        ops.append(loc or "D 0 %d %d 00000000" % (jl, line))
        ops.append(x or "X %d -1 0" % rnd.choice((1, 2, 3)))
        ops.append("@J")

    ops += decide(rnd, w)
    at(clock)
    if kind in ("po-chopper", "po-lights"):
        # Only the distances matter: my car at the origin, each other
        # thing along an axis from it.
        recar(0, px=0.0, py=0.0)
        info([row(0)] + behind([1, 2, 3, 4, 5]))
        axes = ((1, 0), (-1, 0), (0, 1), (0, -1))
    if kind == "po-chopper":
        ops += ["@cm none", "@pl 0 0 0"]
        for plan in range(-1, 8):
            for d in (150.0, fstep(150.0, 1), fstep(150.0, -1),
                      rnd.choice((0.0, 100.0, 200.0))):
                ax, ay = rnd.choice(axes)
                ops.append("@ch %d %s %s" % (plan, h(f32(ax * d)),
                                             h(f32(ay * d))))
                ops.append("@sc po")
        ops.append("@ch 0 %s %s" % (h(150.0), h(0.0)))
        for ctl in (3, 1, 2, 4, 0):
            recar(0, ctl=ctl)
            ops += ["@sc po", "@n po 600 %s -1 %s 0" % (tout, h(-999.0)),
                    "@t", "@us", "@d 1"]
    elif kind == "po-lights":
        ops.append("@ch none")
        for _ in range(14):
            for k in (1, 2, 3, 4, 5):
                v = f32(rnd.choice(COP_SPEEDS))
                rng = max(f32(v * 3.5), 100.0)
                d = rnd.choice((rng, rng, fstep(rng, 1), fstep(rng, -1),
                                50.0, 300.0))
                ax, ay = rnd.choice(axes)
                recar(k, px=f32(ax * d), py=f32(ay * d), vmag=v)
                ops.append("@cl %d %08x" % (k, rnd.choice(
                    (1, 1, 1, 0, 0x100, 0x1000000))))
            es = []
            for i in range(7):
                r = rnd.random()
                es.append("-" if r < 0.2 else "%d:%d" % (
                    rnd.choice((1, 2, 3, 4, 5)),
                    2 if r < 0.45 else rnd.choice((0, 1, 3))))
            if rnd.random() < 0.15:
                ops.append("@cm none")
            else:
                ops.append("@cm %d %s" % (rnd.randint(0, 7), " ".join(es)))
            ops.append("@pl %d %d %d" % (rnd.choice((0, 1, 2, 2)),
                                         rnd.randint(1, 5),
                                         rnd.randint(1, 5)))
            ops.append("@sc po")
            if rnd.random() < 0.3:
                ops += ["@n po 600 %s -1 %s 0" % (tout, h(-999.0)), "@t",
                        "@d 1"]
    elif kind == "po-pot":
        none_near()
        info([row(0)] + behind([1, 2, 3, 4, 5]))
        ops.append("@sk 0 %d" % rnd.choice((0, -2)))
        for pot, delta in ((-999.0, 40000), (-fstep(999.0, 16), 40000),
                           (-fstep(999.0, 17), 40000),
                           (-fstep(999.0, -16), 40000),
                           (-fstep(999.0, -17), 40000), (1.0, 3999),
                           (1.0, 4000), (1.0, 4001), (2.0, 8000),
                           (0.0, 0), (0.0, -1), (NAN, 0), (-1.0, 0)):
            at(clock)
            ops.append("@n po 600 %s -1 %08x %d" % (tout, fb(f32(pot))
                                                    if pot != NAN else NAN,
                                                    rnd.choice((0, 1))))
            at(clock + delta)
            ops += ["@cp", "@d 1"]
    elif kind == "po-hit":
        none_near()
        ops.append("G AVOID %s" % h(f32(rnd.choice((5.0, 4.0)))))
        recar(BLOCKER, vmag=0.0, pl=0)
        for _ in range(6):
            ops.append("@sk 0 %d" % rnd.choice((0, -2)))
            if rnd.random() < 0.5:
                rows = [row(BLOCKER, lx=rnd.choice((0.0, 0.5, -0.5)),
                            ly=rnd.choice((3.0, 6.0)), vx=0.0, vy=0.0,
                            hl2=1.0, hd2=2.0), row(0)]
                rows += behind([1, 2, 3, 5])
            else:
                rows = [row(1, lx=rnd.uniform(-1.0, 1.0),
                            ly=rnd.uniform(10.0, 40.0), vx=0.0,
                            vy=-rnd.choice((5.0, 10.0, 15.0, 20.0))),
                        row(0)] + behind([2, 3, 4, 5])
            info(rows, rnd.choice((None, "X 5 1 0", "X 6 1 0")))
            at(clock)
            ops += ["@n po 600 %s -1 %s 0" % (tout, h(-999.0)), "@cp",
                    "@t"]
            at(clock + 1201)
            ops += ["@cp", "@d 1"]
    elif kind == "ij-score":
        for _ in range(8):
            ys = [f32(rnd.choice((0.0, -0.0, 3.0, -3.0, 5.0, -5.0, 0.5,
                                  -0.5))) for _ in range(4)]
            rows = [row(k, ly=y) for k, y in zip((1, 2, 3, 4), ys)]
            rows.append(row(0))
            # An entry with no car answers a collision with none, when
            # nothing reads the list's cars after.
            nocar = rnd.random() < 0.3
            if nocar:
                rows.append(dict(row(5), k=-1))
            rnd.shuffle(rows)
            info(rows)
            n = rnd.randint(1, 4)
            f = []
            for _ in range(n):
                b = rnd.choice((1, 2, 3, 4, 1, 2, 5, 0) + ((-1,) * 2
                                                           if nocar else ()))
                a, b = (0, b) if rnd.random() < 0.6 else (b, 0)
                f.append(" %d %d %d" % (rnd.choice((1, 1, 1, 0)), a, b))
            ops.append("@col 0 %d%s" % (n, "".join(f)))
            ops.append("@sc ij")
            if not nocar:
                ops += ["@n ij 400 %s %d" % (tout, rnd.choice((1, 5, -1))),
                        "@t", "@us", "@nm", "@d 1"]
    elif kind == "ij-cp":
        none_near()
        hd2 = f32(rnd.uniform(2.0, 2.8))
        ahead = f32(f32(hd + hd2) - f32(2.8))
        back = f32(f32(-hd - hd2) + f32(2.8))
        for _ in range(10):
            case = rnd.choice(("ahead", "back", "zero", "square", "head",
                               "min", "min"))
            v1 = rnd.choice((10.0, 20.0, 30.0))
            if case == "ahead":
                y = rnd.choice((ahead, fstep(ahead, 1), fstep(ahead, -1)))
            elif case == "back":
                y = rnd.choice((back, fstep(-back, 1) * -1.0,
                                fstep(-back, -1) * -1.0))
            elif case == "zero":
                y = rnd.choice((0.0, -0.0, 1e-30, -1e-30))
            else:
                y = rnd.choice((3.0, 6.0, 10.0))
            pl = rnd.choice((0, 1)) if case in ("ahead", "back") else 0
            if case == "min":
                pl = rnd.choice((0, 1))
                v1 = speed_to(20.0, 6.0) if pl else speed_to(20.0, f32(0.1))
                v1 = fstep(v1, rnd.choice((0, 0, 1, -1)))
            bx, by = rnd.choice(((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0),
                                 (-0.0, -1.0), (-1e-30, 1.0),
                                 (1e-30, 1.0), (-0.6, 0.8)))
            if case == "square":
                bx, by = rnd.choice(((0.0, 1.0), (-0.0, 1.0), (0.0, -1.0)))
            elif case == "head":
                bx, by = rnd.choice(((-1.0, 0.0), (-1e-30, 1.0),
                                     (-0.6, -0.8)))
            recar(1, vmag=v1, pl=pl, bx=bx, by=by, ctl=rnd.choice((1, 2, 4)))
            recar(0, dtype=rnd.choice((3, 3, 2, 4)),
                  vmag=rnd.choice((10.0, 19.0, 20.0, 25.0)))
            ops.append("@col 0 0")
            rows = [row(1, lx=rnd.choice((0.0, 1.5, -1.5)), ly=y, hd2=hd2,
                        vy=rnd.choice((0.0, -5.0, 5.0))), row(0)]
            rows += behind([2, 3, 4, 5])
            info(rows)
            at(clock)
            ops += ["@n ij 400 %s 1" % tout, "@cp"]
            at(clock + rnd.choice((1, 801)))
            ops += ["@cp", "@t", "@d 1"]
        # The car I hit off the list, and none.
        info([row(0)] + behind([2, 3, 4, 5]))
        for k in (1, -1):
            ops += ["@n ij 400 %s %d" % (tout, k), "@cp", "@t", "@us",
                    "@d 1"]
    else:
        # ij-head
        none_near()
        for _ in range(8):
            lat = p["rw"] + rnd.choice((-0.5, -0.2, 0.3, 1.5, -3.0))
            x, y = beside(p, lat, 1.0)
            a = heading_of(p) + rnd.choice((-0.3, -0.6, 0.0, 0.3))
            sp = rnd.choice((0.5, 5.0, 10.0, 20.0))
            fs = rnd.choice((sp, -sp, 0.0))
            recar(0, px=x, py=y, bx=math.cos(a), by=math.sin(a), vmag=sp,
                  vx=sp * math.cos(a), vy=sp * math.sin(a), fs=fs,
                  dtype=rnd.choice((2, 3)))
            ops.append("@col 0 0")
            rows = [row(1, ly=rnd.choice((5.0, -5.0)), lx=0.0), row(0)]
            rows += behind([2, 3, 4, 5])
            info(rows)
            at(clock)
            ops += ["@n ij 400 %s 1" % tout, "@cp", "@t", "@d 1"]
    return ops


# The cases the first mutation pass showed s_pull_hit and s_ph_edge lack,
# after them so that theirs draw what they drew.
PH_GAP_KINDS = ("po-soon", "po-assoc", "ij-null", "ij-back", "ij-tts",
                "po-mnc")
N_PH_GAPS = 2
# PullOver's hit, my car at 16 m/s closing on car 1 at 8 along the road:
# the gap, then AvoidCars' and Pass's times. The hit comes (gap - 4.5) / 8
# s on: 1.9375, exactly 2 at 20.5, and 2.0625 to 2.4375, under 2.5.
PO_SOON_CASES = ((20.5, 5.0, 3.0), (20.5, 2.5, 3.0), (21.0, 5.0, 3.0),
                 (22.0, 5.0, 3.0), (24.0, 5.0, 3.0), (20.0, 5.0, 0.25),
                 (20.0, 0.25, 5.0), (20.0, 2.0, 3.0))


def room_straddle(rnd, k, gt):
    """A half width and a distance right of the line, on s_ph_gap's road
    (its right edge 25 m out), whose room (25 - hl) - lat and the room
    summed the other way, 25 - (hl + lat), fall either side of k for
    `k < room` (gt) or `room < k`."""
    while True:
        hl = f32(rnd.uniform(0.8, 1.3))
        lat0 = f32(25.0 - k - hl)
        for n in rnd.sample(range(-4, 5), 9):
            lat = fstep(lat0, n)
            a = f32(f32(25.0 - hl) - lat)
            b = f32(25.0 - f32(hl + lat))
            if ((k < a) != (k < b)) if gt else ((a < k) != (b < k)):
                return hl, lat


def s_ph_gap(rnd, kind):
    """PullOver and IJustGotHit on a straight road along x, 25 m each
    side, every car square to it.

    po-soon: PullOver careful, its hit exactly 2 s on and either side
    (PO_SOON_CASES), AvoidCars' time and Pass's apart; then, inside the
    0.3 s, the choice not okay, so the firm braking, with downforce or
    not. po-assoc: my car where its room to the edge, summed retail's
    way and the other, falls either side of 2 or 4 (room_straddle), for
    the constructor's test and both of the speed's. po-mnc: car 1 hit
    1.9375 s on and car 2 beside it, slower than me, so that going round
    car 1 hits car 2 between Pass's time and AvoidCars', or not; the
    first two layouts are ones that do. ij-null: a collision
    with the list's entry with no car taken first, then one with a car
    either side of it; and the car I hit none with that entry on the
    list. ij-back: a player's car I hit exactly at the back overlap edge
    and an ulp either side. ij-tts: traffic hit head on with its time to
    the speed poked first."""
    w = World(rnd)
    ops = w.ops
    clock = rnd.choice((100000, 200000))
    tout = h(f32(5.0))
    line = 0
    jl = 10
    pts = w.route(0, 40, rnd.randrange(50), x=-200.0, y=0.0, hd=0.0,
                  turn=0.0, smooth=True)
    p = pts[jl]
    rn = w.rn[0]
    hd = f32(2.25)

    def at(t):
        ops.append("G TIMER %08x" % (t & M32))

    def car(k, x, lat, v, **kw):
        args = dict(px=f32(x), py=f32(-lat), pz=0.0, bx=1.0, by=0.0,
                    vmag=f32(v), dn=0, cls=0, dtype=3, ctl=1, oob=-1.0,
                    rpr=0, rpj=jl, ct=0, cc=-1, cx=0, act=-1, pl=0, nw=4,
                    vx=f32(v), vy=0.0, fs=f32(v))
        args.update(kw)
        w.car(k, **args)
        ops.append("A %d %s %s %s 0 %s" % (
            k, h(0.0), h(0.0), h(0.0),
            " ".join(h(f32(b)) for b in (-2.25, -1.0, -0.7, 2.25, 1.0, 0.7))))

    def lane(k, x, lat, v, n, j0):
        ops.append("H %d 5 %s 0 0 0" % (k, h(f32(40.0))))
        for i in range(n):
            ops.append("I %d %s %s %s %d %d %d %s" % (
                k, h(f32(x + 10.0 * (i + 1))), h(f32(-lat)), h(0.0), rn,
                j0 + i, line, h(f32(v))))

    def info(hl, rows):
        """The list: my car's half sizes, then each entry as (across,
        ahead, closing, half length, half depth, car)."""
        ops.append("N 0 %d %s %s" % (len(rows), h(hl), h(hd)))
        for i, (lx, ly, vy, hl2, hd2, k) in enumerate(rows):
            ops.append("E %d %s %s %s %s %s %s %d" % (
                i, h(f32(lx)), h(f32(ly)), h(0.0), h(f32(vy)), h(f32(hl2)),
                h(f32(hd2)), k))
        ops.append("D 0 %d %d 00000000" % (jl, line))
        ops.append("X 1 -1 0")
        ops.append("@J")

    ops += ["@ch none", "@cm none", "@pl 0 0 0"]
    for k in (2, 3, 4, 5):
        car(k, -500.0 - 10.0 * k, 0.0, 0.0, dtype=2)
    me = [(0.0, 0.0, 0.0, 1.0, hd, 0)]
    if kind == "po-soon":
        x0 = p["x"] + 1.0
        for gap, avoid, pas in PO_SOON_CASES:
            lat = rnd.choice((5.0, 21.0))
            car(0, x0, lat, 16.0)
            lane(0, p["x"], lat, 16.0, 6, jl + 1)
            ops.append("@col 0 0")
            car(1, x0 + gap, lat, 8.0, dtype=2, oob=0.0, rpj=jl + 2)
            lane(1, x0 + gap, lat, 8.0, 8, jl + 3)
            # Car 1 is listed well ahead, so not stopped in front of me.
            info(f32(1.0), [(0.0, 40.0, -8.0, 1.0, hd, 1)] + me)
            ops.append("G AVOID %s" % h(f32(avoid)))
            ops.append("G PASS %s" % h(f32(pas)))
            down = rnd.choice((0.0, 2.0, 10.0))
            ops.append("@ti 0 %s" % " ".join(h(f32(x)) for x in (
                1500.0, 0.0, 150.0, 1.0, 1.0, down, down)))
            ops.append("@sk 0 -2")
            at(clock)
            ops += ["@n po 600 %s -1 %s 0" % (tout, h(-999.0)), "@cp"]
            at(clock + 1)
            ops += ["@f o616 00000000", "@cp", "@t", "@d 1"]
    elif kind == "po-assoc":
        for k, gt, poke in ((2.0, True, None), (2.0, False, 1),
                            (4.0, True, 0)):
            hl, lat = room_straddle(rnd, k, gt)
            v = rnd.choice((5.0, 10.0, 14.0))
            car(0, p["x"] + 1.0, lat, v, ctl=3, oob=0.0)
            lane(0, p["x"], lat, v, 6, jl + 1)
            ops.append("@col 0 0")
            car(1, -400.0, 0.0, 0.0, dtype=2)
            info(hl, [(0.0, 0.0, 0.0, hl, hd, 0)])
            ops.append("@sk 0 0")
            at(clock)
            ops.append("@n po 600 %s -1 %s 0" % (tout, h(-999.0)))
            if poke is not None:
                ops.append("@f o620 %08x" % poke)
            ops += ["@cp", "@d 1"]
    elif kind == "ij-null":
        car(0, p["x"] + 1.0, 5.0, 20.0, dtype=1)
        lane(0, p["x"], 5.0, 20.0, 6, jl + 1)
        car(1, -400.0, 0.0, 0.0, dtype=2)
        for yn, y2 in ((-5.0, -3.0), (3.0, 5.0), (-5.0, 3.0), (5.0, 3.0)):
            info(f32(1.0), [(0.0, yn, 0.0, 1.0, 2.5, -1),
                            (1.5, y2, 0.0, 1.0, 2.5, 2)] + me)
            ops += ["@col 0 2 1 0 -1 1 0 2", "@sc ij"]
        ops += ["@col 0 1 1 0 -1", "@sc ij"]
        at(clock)
        ops += ["@n ij 400 %s -1" % tout, "@t", "@us", "@d 1"]
    elif kind == "ij-back":
        for _ in range(6):
            hd2 = f32(rnd.uniform(2.0, 2.8))
            back = f32(f32(-hd - hd2) + f32(2.8))
            y = rnd.choice((back, back, -fstep(-back, 1), -fstep(-back, -1)))
            car(0, p["x"] + 1.0, 5.0, rnd.choice((10.0, 25.0)),
                dtype=rnd.choice((1, 2, 4)))
            lane(0, p["x"], 5.0, 20.0, 6, jl + 1)
            ops.append("@col 0 0")
            car(1, p["x"] + 1.0 + y, 5.0, 20.0, dtype=2, pl=1)
            info(f32(1.0), [(0.0, y, 0.0, 1.0, hd2, 1)] + me)
            at(clock)
            ops += ["@n ij 400 %s 1" % tout, "@cp", "@d 1"]
    elif kind == "po-mnc":
        x0 = p["x"] + 1.0
        cases = [(5.0, -3.5, 8.0, 8.0, 5.0, 0.25, -2),
                 (10.0, 3.5, 10.0, 8.0, 5.0, 0.25, 0)]
        for _ in range(4):
            cases.append((rnd.choice((5.0, 10.0, 21.0)),
                          rnd.choice((-4.0, -3.5, -3.0, 2.5, 3.5)),
                          rnd.choice((8.0, 10.0, 12.0, 15.0)),
                          rnd.choice((6.0, 8.0, 12.0)),
                          rnd.choice((2.5, 3.0, 5.0)),
                          rnd.choice((0.25, 0.5, 1.0, 1.5)),
                          rnd.choice((0, -2))))
        for lat, dx2, y2, v2, avoid, pas, sk in cases:
            car(0, x0, lat, 16.0)
            lane(0, p["x"], lat, 16.0, 6, jl + 1)
            ops.append("@col 0 0")
            car(1, x0 + 20.0, lat, 8.0, dtype=2, oob=0.0, rpj=jl + 2)
            lane(1, x0 + 20.0, lat, 8.0, 8, jl + 3)
            car(2, x0 + y2, lat + dx2, v2, dtype=2, oob=0.0, rpj=jl + 1)
            lane(2, x0 + y2, lat + dx2, v2, 8, jl + 2)
            info(f32(1.0), [(0.0, 40.0, -8.0, 1.0, hd, 1),
                            (dx2, y2, v2 - 16.0, 1.0, hd, 2)] + me)
            ops.append("G AVOID %s" % h(f32(avoid)))
            ops.append("G PASS %s" % h(f32(pas)))
            ops.append("@sk 0 %d" % sk)
            at(clock)
            ops += ["@n po 600 %s -1 %s 0" % (tout, h(-999.0)), "@cp",
                    "@d 1"]
    else:
        # ij-tts
        for _ in range(4):
            car(0, p["x"] + 1.0, 5.0, rnd.choice((10.0, 25.0)), dtype=3)
            lane(0, p["x"], 5.0, 20.0, 6, jl + 1)
            ops.append("@col 0 0")
            car(1, p["x"] + 7.0, 5.0, 20.0, dtype=2, bx=-1.0, vx=-20.0)
            info(f32(1.0), [(0.0, 6.0, -40.0, 1.0, 2.5, 1)] + me)
            at(clock)
            ops += ["@n ij 400 %s 1" % tout,
                    "@f tt %08x" % fb(f32(rnd.choice((1.0, 0.5, 3.0)))),
                    "@cp", "@d 1"]
    return ops


def script():
    rnd = random.Random(0x11b2dc)
    sc = [s_small(rnd), s_valid(rnd), s_room(rnd), s_walk(rnd), s_fill(rnd),
          s_speed(rnd), s_reduce(rnd)]
    for _ in range(6):
        sc.append(s_room(rnd))
        sc.append(s_walk(rnd))
        sc.append(s_fill(rnd))
    for _ in range(2):
        sc.append(s_valid(rnd))
        sc.append(s_speed(rnd))
        sc.append(s_reduce(rnd))
    for c in (0.09, 0.105, 0.11, 0.115, 0.125, 0.13, 0.3):
        for sgn in (1, -1):
            sc.append(s_bend(rnd, c, sgn))
    # Step 11b-3's, after the rest so that theirs draw what they drew.
    for _ in range(8):
        sc.append(s_around(rnd))
        sc.append(s_pieces(rnd))
    for _ in range(4):
        sc.append(s_sign_pass(rnd))
    for _ in range(6):
        sc.append(s_back(rnd))
    # Step 11b-4a's.
    for _ in range(10):
        sc.append(s_predict(rnd))
    for _ in range(3):
        sc.append(s_parts(rnd))
    for _ in range(12):
        sc.append(s_meet(rnd))
    for _ in range(2):
        sc.append(s_stopped(rnd))
    # Step 11b-4b's.
    for _ in range(N_CHOOSE):
        sc.append(s_choose(rnd))
    for _ in range(N_JAM):
        sc.append(s_jam(rnd))
    for _ in range(N_PASS):
        sc.append(s_pass(rnd))
    sc.append(s_tie())
    # Step 11d-1's.
    for _ in range(N_ACTIONS):
        sc.append(s_actions(rnd))
    sc.append(s_act_edges(rnd))
    # Step 11d-2's.
    for _ in range(N_PASS_AVOID):
        sc.append(s_pass_avoid(rnd, "pa"))
        sc.append(s_pass_avoid(rnd, "ac"))
    for _ in range(N_PA_EDGES):
        for kind in PA_EDGE_KINDS:
            sc.append(s_pa_edge(rnd, kind))
    # Step 11d-3a's.
    for _ in range(N_PULL_HIT):
        sc.append(s_pull_hit(rnd, "po"))
        sc.append(s_pull_hit(rnd, "ij"))
    for _ in range(N_PH_EDGES):
        for kind in PH_EDGE_KINDS:
            sc.append(s_ph_edge(rnd, kind))
    for _ in range(N_PH_GAPS):
        for kind in PH_GAP_KINDS:
            sc.append(s_ph_gap(rnd, kind))
    return sc


def encode(scenarios):
    lines = []
    for i, s in enumerate(scenarios):
        lines.append("B %d" % i)
        lines += s
    return NL.join(lines) + NL


# ================================================================ the model


class Model(object):
    def __init__(self):
        self.out = []
        self.e = retail_model.RetailEmu(ieee=True, eediv=True)
        self.e.stub(SIGN_DECISION, self.s_sign)
        self.e.stub(GET_ROUTE_POINT, self.s_rp)
        self.e.stub(GET_OOB, self.s_oob)
        self.e.stub(GET_ELEVATION, self.s_elev)
        self.e.stub(RESET_LATER, self.s_reset_later)
        self.e.stub(POOL_FREE, self.s_pool_free)
        self.e.stub(STUB_DNUM, self.s_dnum)
        self.e.stub(GET_COLLISION, self.s_get_collision)
        self.e.stub(IS_TWO_CAR, self.s_is_two_car)
        self.e.stub(COLLIDING_CARS, self.s_colliding_cars)
        self.w = self.e.u32
        self.grace0 = self.w(GLOBALS["GRACE"])
        self.gap0 = self.w(GLOBALS["GAP"])
        self.traffic0 = self.w(GLOBALS["TRAFFIC"])
        self.slowcar0 = self.w(GLOBALS["SLOWCAR"])
        self.slowtraffic0 = self.w(GLOBALS["SLOWTRAFFIC"])
        self.minspeed0 = self.w(GLOBALS["MINSPEED"])
        self.nlines0 = self.w(GLOBALS["NLINES"])
        self.avoid0 = self.w(GLOBALS["AVOID"])
        self.pass0 = self.w(GLOBALS["PASS"])
        self.normal = {}
        self.kind = ""
        d = struct.unpack("<f", struct.pack("<I", self.w(MIN_DIST)))[0]
        self.e.put32(MIN_DIST_SQ, fb(f32(d * d)))
        # nearbycar.c's fBeltAccelCoef is a constant 1.
        if self.w(BELT_COEF) != fb(1.0):
            raise SystemExit("fBeltAccelCoef is %08x" % self.w(BELT_COEF))
        self.dec = {}
        self.rp = {}
        self.oob = {}
        self.dist = bytes(80)
        self.calls = 0
        self.est_at = None
        self.e.hooks[EST_ENTRY] = self.h_est_in
        self.e.hooks[EST_RET] = self.h_est_out
        self.e.hooks[MAKE_NEW] = self.h_make_new_in
        self.e.hooks[PO_CPTD] = self.h_po_cptd_in
        self.colls = {}

    def h_make_new_in(self, em):
        a = (em.reg[29] + MAKE_NEW_CURRENT) & M32
        em.mem[a:a + 12] = bytes(12)

    def h_po_cptd_in(self, em):
        a = (em.reg[29] + PO_CHOICE) & M32
        em.mem[a:a + 12] = bytes(12)

    def h_est_in(self, em):
        sp = (em.reg[29] - EST_FRAME) & M32
        if (sp, self.calls) != self.est_at:
            em.mem[sp:sp + 80] = self.dist
        self.est_at = (sp, self.calls)

    def h_est_out(self, em):
        sp = em.reg[29] & M32
        self.dist = bytes(em.mem[sp:sp + 80])

    def emit(self, s):
        self.out.append(s)

    def fill(self, a, n):
        self.e.mem[a:a + n] = bytes([PATTERN]) * n

    # ---- names -----------------------------------------------------------

    def name(self, a):
        a &= M32
        if a == 0:
            return "null"
        if a == PAT32:
            return "pat"
        for base, stride, n, tag in (
                (CARS, CAR_STRIDE, NCARS, "c"),
                (CTRLS, CTRL_STRIDE, NCARS, "k"),
                (LOCS, 16, NCARS, "L"),
                (CHOICES, 16, NCARS, "ch"),
                (ACTIONS, ACTION_STRIDE, NCARS, "a"),
                (SIGNS, SIGN_SIZE, NSIGNS, "S"),
                (LIST + LIST_ARRAY, NC_SIZE, LIST_MAX, "e"),
                (BODIES, BODY_STRIDE, NCARS, "b")):
            if base <= a < base + stride * n and (a - base) % stride == 0:
                return "%s%d" % (tag, (a - base) // stride)
        if (COLLS <= a < COLLS + COLL_STRIDE * NCOLLS * NCARS
                and (a - COLLS) % COLL_STRIDE == 0):
            return "col%d:%d" % divmod((a - COLLS) // COLL_STRIDE, NCOLLS)
        if a == LOC:
            return "loc"
        if a == CHOICE:
            return "CH"
        if a == OTHER:
            return "OT"
        if a == AB:
            return "ab"
        if a == INFO:
            return "info"
        if a == INFO + 464:
            return "iloc"
        if a == INFO + 480:
            return "ich"
        if a == POOL:
            return "pool"
        if (INFO + LIST_ARRAY <= a < INFO + LIST_ARRAY + NC_SIZE * LIST_MAX
                and (a - INFO - LIST_ARRAY) % NC_SIZE == 0):
            return "ie%d" % ((a - INFO - LIST_ARRAY) // NC_SIZE)
        if CARS <= a < CARS + CAR_STRIDE * NCARS:
            k, off = divmod(a - CARS, CAR_STRIDE)
            if off == C_TC:
                return "tc%d" % k
            if off == C_POS:
                return "pos%d" % k
        if ROUTES <= a < ROUTES + ROUTE_STRIDE * NROUTES:
            k, off = divmod(a - ROUTES, ROUTE_STRIDE)
            if off == 0:
                return "R%d" % k
            if off >= RT_HEADER and (off - RT_HEADER) % RT_POINT == 0:
                return "R%d:%d" % (k, (off - RT_HEADER) // RT_POINT)
        return "?%08x" % a

    def car_index(self, a):
        return (a - CARS) // CAR_STRIDE

    # ---- the stubs -------------------------------------------------------

    def s_sign(self, em):
        ctrl, sign, linep, loc = (em.reg[r] & M32 for r in (4, 5, 6, 7))
        i = (sign - SIGNS) // SIGN_SIZE
        take, nl = self.dec.get(i, (0, -1))
        self.emit("  sign %s %s %d %s" % (self.name(ctrl), self.name(sign),
                                          s32(self.w(linep)),
                                          self.name(loc)))
        if nl >= 0:
            self.e.put32(linep, nl)
        return take

    def s_rp(self, em):
        car = em.reg[4] & M32
        self.emit("  rp %s" % self.name(car))
        return self.rp[self.car_index(car)]

    def s_oob(self, em):
        car = em.reg[4] & M32
        self.emit("  oob %s" % self.name(car))
        em.fpr[0] = self.oob[self.car_index(car)]

    def s_elev(self, em):
        """GetElevation: the script's normal for the car whose coordinate
        it is. The height and the terrain are not read."""
        r = em.reg
        tc = r[4] & M32
        self.emit("  elev %s %s %d %d %d" % (
            self.name(tc), self.name(r[5]), (r[6] & M32) != 0,
            (r[7] & M32) != 0, (r[8] & M32) != 0))
        k, off = divmod(tc - CARS, CAR_STRIDE)
        if off == C_TC:
            for i, v in enumerate(self.normal.get(k, (0, 0, 0, 0))):
                self.e.put32((r[7] & M32) + 4 * i, v)
        em.fpr[0] = 0

    def s_reset_later(self, em):
        self.emit("  reset %s" % self.name(em.reg[4]))

    def s_pool_free(self, em):
        self.emit("  slotfree %s %s" % (self.name(em.reg[4]),
                                        self.name(em.reg[5])))

    def s_get_collision(self, em):
        """CollisionBody::GetCollision: the body's car's collision i."""
        b, i = em.reg[4] & M32, s32(em.reg[5])
        k, off = divmod(b - BODIES, BODY_STRIDE)
        self.emit("  getcol %s %d" % (self.name(b), i))
        if off or not 0 <= k < NCARS or not 0 <= i < NCOLLS:
            raise SystemExit("a collision that is not one of ours: %08x %d"
                             % (b, i))
        return COLLS + COLL_STRIDE * (NCOLLS * k + i)

    def s_is_two_car(self, em):
        c = em.reg[4] & M32
        self.emit("  two %s" % self.name(c))
        return self.colls[c][0]

    def s_colliding_cars(self, em):
        r = em.reg
        c = r[4] & M32
        self.emit("  colliding %s" % self.name(c))
        _, c1, c2 = self.colls[c]
        self.e.put32(r[5] & M32, c1)
        self.e.put32(r[6] & M32, c2)

    def s_dnum(self, em):
        """The test CarDriver's GetDriverNumber: its car's DriverNumber."""
        k, off = divmod((em.reg[4] & M32) - CDRIVERS, CDRIVER_STRIDE)
        if off or not 0 <= k < NCARS:
            raise SystemExit("a driver that is not one of ours: %08x"
                             % (em.reg[4] & M32))
        car = car_at(k)
        self.emit("  dnum %s" % self.name(car))
        return struct.unpack_from("<h", em.mem, car + C_DN)[0]

    # ---- the dumps -------------------------------------------------------

    def dump_choice(self, a, tag):
        w = self.w
        self.emit("  %s %d %s %d" % (tag, s32(w(a)), self.name(w(a + 4)),
                                     s32(w(a + 8))))

    def dump_its(self):
        """What the choice's car's own target picked, if it has a car."""
        car = self.w(CHOICE + 4)
        if CARS <= car < CARS + CAR_STRIDE * NCARS:
            t = self.w(car + C_CDRIVER)
            self.emit("  its pk %d %d %d" % (s8(self.e.mem[t + 500]),
                                             s32(self.w(t + 504)),
                                             s32(self.w(t + 508))))

    def dump_target(self, t=TARGET):
        w, m = self.w, self.e.mem
        n = s8(m[t])
        self.emit("  target n %d tt %d len %s last %d pk %d %d %d" % (
            n, s32(w(t + 496)), fx(w(t + 512)), s8(m[t + 516]),
            s8(m[t + 500]), s32(w(t + 504)), s32(w(t + 508))))
        for i in range(max(0, min(n, 20))):
            p = t + 16 + 16 * i
            self.emit("    %d %s %s %s r %d p %d l %d sp %s" % (
                i, fx(w(p)), fx(w(p + 4)), fx(w(p + 8)), s8(m[t + 416 + i]),
                s16(self.e.u16(t + 436 + 2 * i)), s8(m[t + 476 + i]),
                fx(w(t + 336 + 4 * i))))

    def dump_fpl(self):
        w = self.w
        n = s32(w(FPL))
        self.emit("  fpl %d" % n)
        for i in range(max(0, min(n, FPL_MAX))):
            p = FPL + 4 + FP_SIZE * i
            self.emit("    %d r %d p %d l %d o %s x %d" % (
                i, s32(w(p)), s32(w(p + 4)), s32(w(p + 8)), fx(w(p + 12)),
                s32(w(p + 16))))

    def dump_obbs(self):
        """The boxes written: up to the first whose a0 is still the fill.
        A position's w is the target point's, which a STACK-W point leaves
        to the stack, so only its x, y and z."""
        w = self.w
        n = 0
        while n < NOBBS and w(OBBS + OBB_SIZE * n + 64) != PAT32:
            n += 1
        self.emit("  obbs %d" % n)
        for i in range(n):
            o = OBBS + OBB_SIZE * i
            self.emit("    %d %s | %s | %s | %s | %s" % (
                i, " ".join(fx(w(o + 4 * j)) for j in range(3)),
                " ".join(fx(w(o + 16 + 4 * j)) for j in range(4)),
                " ".join(fx(w(o + 32 + 4 * j)) for j in range(4)),
                " ".join(fx(w(o + 48 + 4 * j)) for j in range(4)),
                " ".join(fx(w(o + 64 + 4 * j)) for j in range(3))))

    def put_obb(self, a, v):
        """A0's and A1's x and y, a0 and a1; the rest 0."""
        e = self.e
        e.mem[a:a + OBB_SIZE] = bytes(OBB_SIZE)
        for off, x in zip((16, 20, 32, 36, 64, 68), v):
            e.put32(a + off, int(x, 16))

    def dump_walk(self, got):
        w = self.w
        self.emit("  adv %d %s %s n %d o %s x %d l %d" % (
            got, self.name(w(WALK)), self.name(w(WALK + 4)),
            s32(w(WALK + 8)), fx(w(WALK + 12)), s32(w(WALK + 16)),
            s32(w(WALK + 20))))

    # ---- the world -------------------------------------------------------

    def reset(self):
        e = self.e
        e.mem[CARS:CARS + CAR_STRIDE * NCARS] = bytes(CAR_STRIDE * NCARS)
        e.mem[CTRLS:CTRLS + CTRL_STRIDE * NCARS] = bytes(CTRL_STRIDE * NCARS)
        e.mem[CHOICES:LOCS + 16 * NCARS] = bytes(LOCS + 16 * NCARS - CHOICES)
        e.mem[CTIS:DRIVERS + DRIVER_STRIDE * NCARS] = bytes(
            DRIVERS + DRIVER_STRIDE * NCARS - CTIS)
        e.mem[CDRIVERS:CDRIVERS + CDRIVER_STRIDE * NCARS] = bytes(
            CDRIVER_STRIDE * NCARS)
        e.mem[ROUTE_TABLE:ROUTE_TABLE + 4 * NUM_ROUTE_SLOTS] = bytes(
            4 * NUM_ROUTE_SLOTS)
        e.mem[SIGNS:SIGNS + SIGN_SIZE * NSIGNS] = bytes(SIGN_SIZE * NSIGNS)
        e.mem[RACE:RACE + 64] = bytes(64)
        self.fill(LIST, 464)
        self.fill(LOC, 16)
        self.fill(CHOICE, 12)
        self.fill(OTHER, 12)
        self.fill(FPL, FPL_BYTES)
        self.fill(LPTR, 4)
        self.fill(WALK, 24)
        self.fill(TARGET, TARGET_BYTES)
        self.fill(AB, AB_BYTES)
        self.fill(INFO, INFO_BYTES)
        e.mem[BODIES:BODIES + BODY_STRIDE * NCARS] = bytes(
            BODY_STRIDE * NCARS)
        e.put32(WORLD + W_ID, 0)
        e.put32(WORLD + W_PDT_ID, 0)
        for name, v in (("TIMER", 0), ("RACE", RACE), ("WORLD", WORLD),
                        ("GRACE", self.grace0), ("GAP", self.gap0),
                        ("WILLIAMS", 0),
                        ("SECS", 0x40000000), ("DEF", 0x41a00000),
                        ("SIGNS", SIGNS), ("NSIGNS", NSIGNS),
                        ("TRAFFIC", self.traffic0),
                        ("SLOWCAR", self.slowcar0),
                        ("SLOWTRAFFIC", self.slowtraffic0),
                        ("MINSPEED", self.minspeed0),
                        ("NLINES", self.nlines0),
                        ("POOL", POOL), ("AVOID", self.avoid0),
                        ("PASS", self.pass0), ("CAM", M32), ("HROUTE", M32),
                        ("HLINE", M32)):
            e.put32(GLOBALS[name], v)
        e.mem[DVT:DVT + DVT_BYTES] = bytes(DVT_BYTES)
        e.put32(DVT + DVT_DNUM + 4, STUB_DNUM)
        # Step 11d-3a's: no chopper, cop manager, players or collisions;
        # car type 0's table.
        e.put32(WORLD + W_CHOPPER, 0)
        e.put32(GLOBALS["COPM"], 0)
        e.put32(GLOBALS["NPLAYERS"], 0)
        e.put32(GLOBALS["PLAYERS"], 0)
        e.put32(GLOBALS["PLAYERS"] + 4, 0)
        e.mem[RIDE:RIDE + 16] = bytes(16)
        e.mem[ACCEL:ACCEL + ACCEL_TABLE + 20] = bytes(ACCEL_TABLE + 20)
        e.put32(ACCEL + 4, fb(1.0))
        for i, v in enumerate((ACCEL, 2, fb(0.0), fb(100.0), fb(f32(0.01)))):
            e.put32(ACCEL + ACCEL_TABLE + 4 * i, v)
        self.colls = {}
        self.dec = {}
        self.rp = {}
        self.oob = {}
        self.normal = {}
        self.kind = ""

    def set_car(self, t):
        e = self.e
        k = int(t[1])
        v = {}
        for f, x in zip(CAR_FIELDS, t[2:]):
            v[f] = int(x, 16) if f in CAR_FLOATS else int(x)
        a = car_at(k)
        ctrl = CTRLS + CTRL_STRIDE * k
        cti = CTIS + CTI_STRIDE * k
        drv = DRIVERS + DRIVER_STRIDE * k
        ch = CHOICES + 16 * k
        act = ACTIONS + ACTION_STRIDE * k
        struct.pack_into("<h", e.mem, a + C_DN, v["dn"])
        e.put32(a + C_CTI, cti)
        e.mem[cti + CTI_CLASS] = v["cls"] & 0xff
        e.put32(a + C_DRIVER, drv)
        e.put32(drv + DRV_TYPE, v["dtype"])
        e.put32(a + C_CTL, v["ctl"])
        e.put32(a + C_CTRL, ctrl)
        for i, f in enumerate(("px", "py", "pz")):
            e.put32(a + C_POS + 4 * i, v[f])
        e.put32(a + C_BM, v["bx"])
        e.put32(a + C_BM + 4, v["by"])
        e.put32(a + C_VMAG, v["vmag"])
        e.put32(a + C_PLAYER, PLAYERS + PLAYER_STRIDE * k if v["pl"] else 0)
        e.put32(a + C_CDRIVER, CDRIVERS + CDRIVER_STRIDE * k)
        e.put32(CDRIVERS + CDRIVER_STRIDE * k + CD_VPTR, DVT)
        e.put32(a + C_VEL, v["vx"])
        e.put32(a + C_VEL + 4, v["vy"])
        e.put32(a + C_NW, v["nw"])
        e.put32(a + C_FS, v["fs"])
        e.put32(ctrl + K_LOC, LOCS + 16 * k)
        e.put32(ctrl + K_CHOICE, ch)
        e.put32(ctrl + K_EXCLUDE, PAT32)
        e.put32(ctrl + K_ACTION, act if v["act"] >= 0 else 0)
        e.put32(act + A_TYPE, v["act"])
        e.put32(ch, v["ct"])
        e.put32(ch + 4, self.car_ptr(v["cc"]))
        e.put32(ch + 8, v["cx"])
        self.oob[k] = v["oob"]
        self.rp[k] = self.point_of(v["rpr"], v["rpj"])
        # What CalculateMaxAcceleration and CalculateMaxDeceleration read,
        # until the script's "@ti".
        e.put32(a + C_RIDE, RIDE)
        e.put32(a + C_BOOST, fb(1.0))
        for f, off in CTI_FIELDS:
            e.put32(cti + off, fb(CTI_DEFAULT[f]))

    def set_route(self, t):
        e = self.e
        k, n, rn, ty = int(t[1]), int(t[2]), int(t[3]), int(t[4])
        a = route_at(k)
        e.mem[a:a + RT_HEADER] = bytes(RT_HEADER)
        struct.pack_into("<hh", e.mem, a + 8, 1, rn)
        e.put32(a + 12, ty)
        e.put32(a + 16, n)
        e.put32(a + 20, n)
        for i in range(LINES):
            e.put32(a + 40 + 48 * i, int(t[5 + i], 16))
        if 0 <= rn < NUM_ROUTE_SLOTS:
            e.put32(ROUTE_TABLE + 4 * rn, a)
        self.cur_route = a
        self.cur_n = 0

    def route_of(self, k):
        k = int(k)
        return route_at(k) if k >= 0 else 0

    def point_of(self, k, j):
        k, j = int(k), int(j)
        if k < 0 or j < 0:
            return 0
        return route_at(k) + RT_HEADER + RT_POINT * j

    def car_ptr(self, s):
        k = int(s)
        return car_at(k) if k >= 0 else 0

    def entry(self, s):
        return LIST + LIST_ARRAY + NC_SIZE * int(s)

    def set_choice(self, a, t):
        e = self.e
        e.put32(a, int(t[1]))
        e.put32(a + 4, self.car_ptr(t[2]))
        e.put32(a + 8, int(t[3]))

    def car_target(self, s):
        return CDRIVERS + CDRIVER_STRIDE * int(s)

    def put_point(self, t, v):
        """x y z rn j line sp, at the end of the target at t."""
        e = self.e
        n = e.mem[t]
        p = t + 16 + 16 * n
        for i in range(3):
            e.put32(p + 4 * i, int(v[i], 16))
        e.put32(p + 12, 0)
        e.mem[t + 416 + n] = int(v[3]) & 0xff
        struct.pack_into("<h", e.mem, t + 436 + 2 * n, int(v[4]))
        e.mem[t + 476 + n] = int(v[5]) & 0xff
        e.put32(t + 336 + 4 * n, int(v[6], 16))
        e.mem[t] = n + 1

    # ---- the ops ---------------------------------------------------------

    def call(self, fn, *args, **f):
        """fn(args), the floats given as f12=bits and so on, and the words
        past the eighth as stack=[...], each in its 8-byte slot."""
        e = self.e
        self.calls += 1
        for i, v in enumerate(f.pop("stack", ())):
            e.put32((e.reg[29] & M32) + 8 * i, v)
        limit = f.pop("limit", 4000000)
        for i, v in f.items():
            e.fpr[int(i[1:])] = v & M32
        return e.call(fn, *args, limit=limit)

    # ---- step 11d-1's ----------------------------------------------------

    def cstr(self, a):
        mem = self.e.mem
        end = mem.index(0, a)
        return mem[a:end].decode("latin-1")

    def vt_name(self, v):
        return ACT_VTABLES.get(v, "%08x" % v)

    def dump_act(self):
        """The action's fields, and the kind's own."""
        w, a = self.w, AB
        self.emit("  act can %d exp %08x dt %s st %d vt %s pt %d ds %s tt %s "
                  "tol %s udl %d tb %d bo %d type %d score %d" % (
                      s32(w(a)), w(a + 4), fx(w(a + 8)), s32(w(a + 12)),
                      self.vt_name(w(a + 16)), s32(w(a + 560)),
                      fx(w(a + 564)), fx(w(a + 568)), fx(w(a + 572)),
                      s32(w(a + 576)), s32(w(a + 580)), s32(w(a + 584)),
                      s32(w(a + 588)), s32(w(a + 592))))
        if self.kind == "jd":
            self.emit("  jd last %08x" % w(a + 608))
        elif self.kind in ("nc", "bl"):
            self.emit("  car %s" % self.name(w(a + 608)))
        elif self.kind == "ar":
            self.emit("  ar made %08x reset %d" % (w(a + 608),
                                                   s32(w(a + 612))))
        elif self.kind == "pa":
            self.emit("  pa car %s amt %s made %08x" % (
                self.name(w(a + 608)), fx(w(a + 612)), w(a + 616)))
        elif self.kind == "ac":
            self.emit("  ac car %s secs %s ok %d last %08x made %08x min %s "
                      "used %d" % (self.name(w(a + 608)), fx(w(a + 612)),
                                   s32(w(a + 616)), w(a + 620), w(a + 624),
                                   fx(w(a + 628)), s32(w(a + 632))))
        elif self.kind == "po":
            self.emit("  po made %08x last %08x ok %d room %d pot %s" % (
                w(a + 608), w(a + 612), s32(w(a + 616)), s32(w(a + 620)),
                fx(w(a + 624))))
        elif self.kind == "ij":
            self.emit("  ij car %s last %08x" % (self.name(w(a + 608)),
                                                  w(a + 612)))

    def dump_info(self):
        """After CalculatePointsToDrive: the information's choice and
        location, and what IsDriveable leaves behind."""
        w = self.w
        self.dump_choice(INFO + 480, "ich")
        self.emit("  iloc %s %s %d %08x" % (
            self.name(w(INFO + 464)), self.name(w(INFO + 468)),
            s32(w(INFO + 472)), w(INFO + 476)))
        self.emit("  exclude %s" % self.name(
            w(w(w(INFO) + C_CTRL) + K_EXCLUDE)))
        self.emit("  ids %d %d" % (w(WORLD + W_ID), w(WORLD + W_PDT_ID)))

    def vcall(self, slot, *args):
        """The action's virtual in `slot`, as g++ calls it: the entry's
        delta added to this."""
        vt = self.w(AB + 16)
        delta = struct.unpack_from("<h", self.e.mem, vt + slot)[0]
        return self.call(self.w(vt + slot + 4), (AB + delta) & M32, *args,
                         limit=CHOOSE_LIMIT)

    def act_op(self, t):
        e, w = self.e, self.w
        c = t[0][1:]
        if c == "J":
            e.mem[INFO:INFO + 464] = e.mem[LIST:LIST + 464]
            e.mem[INFO + 464:INFO + 480] = e.mem[LOC:LOC + 16]
            e.mem[INFO + 480:INFO + 492] = e.mem[CHOICE:CHOICE + 12]
        elif c == "n":
            self.kind = t[1]
            self.fill(AB, AB_BYTES)
            if t[1] == "pa":
                self.call(ACT_CTORS["pa"], AB, int(t[2]), self.car_ptr(t[4]),
                          f12=int(t[3], 16), f13=int(t[5], 16))
            elif t[1] == "ac":
                self.call(ACT_CTORS["ac"], AB, int(t[2]), self.car_ptr(t[4]),
                          int(t[6]), int(t[7]), f12=int(t[3], 16),
                          f13=int(t[5], 16))
            elif t[1] == "po":
                # The last bit leaves out the list, the next the location.
                z = int(t[6])
                self.call(ACT_CTORS["po"], AB, int(t[2]),
                          0 if z & 1 else INFO, 0 if z & 2 else INFO + 464,
                          f12=int(t[3], 16), f13=int(t[5], 16))
            else:
                self.call(ACT_CTORS[t[1]], AB, int(t[2]),
                          self.car_ptr(t[4]), f12=int(t[3], 16))
            self.dump_act()
            self.dump_target(AB + 32)
        elif c == "cp":
            self.vcall(24, INFO)
            self.dump_act()
            self.dump_target(AB + 32)
            self.dump_info()
            if self.kind == "ac":
                self.emit("  highlight %d %d" % (s32(w(GLOBALS["HROUTE"])),
                                                 s32(w(GLOBALS["HLINE"]))))
        elif c == "us":
            self.call(UPDATE_STATUS, AB, INFO, limit=CHOOSE_LIMIT)
            self.emit("  status %d" % s32(w(AB + 12)))
        elif c == "t":
            got = [self.vcall(slot, INFO) for slot in (40, 48, 56)]
            self.emit("  tests %d %d %d" % tuple(got))
        elif c == "nm":
            self.emit("  name %s" % self.cstr(self.vcall(32)))
        elif c == "d":
            self.vcall(8, int(t[1]))
            self.emit("  vt %s" % self.vt_name(w(AB + 16)))
        elif c == "sc":
            k = t[1]
            if k == "dr":
                got = self.call(ACT_SCORES[k], INFO, self.car_ptr(t[2]))
            elif k in ("nc", "bl", "ij"):
                e.put32(OUT, PAT32)
                got = self.call(ACT_SCORES[k], INFO, OUT)
                self.emit("  out %s" % self.name(w(OUT)))
            elif k in ("pa", "ac"):
                # Each out filled first, so what is not written shows.
                self.fill(SC_OUT, SC_OUT_BYTES)
                outs = (SC_OUT, SC_OUT + 16, SC_OUT + 32)
                if k == "ac":
                    outs += (SC_OUT + 36, SC_OUT + 40)
                got = self.call(ACT_SCORES[k], INFO, *outs,
                                limit=CHOOSE_LIMIT)
                self.emit("  out %s" % self.name(w(SC_OUT)))
                self.dump_choice(SC_OUT + 16, "sch")
                self.emit("  secs %s ok %d used %d" % (
                    fx(w(SC_OUT + 32)), s32(w(SC_OUT + 36)),
                    s32(w(SC_OUT + 40))))
                self.dump_info()
            else:
                got = self.call(ACT_SCORES[k], INFO)
            self.emit("  score %d" % s32(got))
        elif c == "so":
            got = self.call(SIDE_OK, INFO + LIST_ARRAY + NC_SIZE * int(t[1]),
                            INFO + 480, int(t[2]))
            self.emit("  sok %d" % got)
        elif c == "ga":
            self.emit("  ga %s" % self.name(self.call(GET_CAR_TO_AVOID, AB)))
        elif c == "bk":
            a = self.car_ptr(t[1]) + C_BLINK
            e.put32(a, int(t[2], 16))
            e.put32(a + 4, int(t[3], 16))
        elif c == "par":
            got = self.call(AR_PARALLEL, self.car_ptr(t[1]),
                            f12=int(t[2], 16))
            self.emit("  par %d" % got)
        elif c == "up":
            a = self.car_ptr(t[1]) + C_UP
            for i in range(4):
                e.put32(a + 4 * i, int(t[2 + i], 16))
        elif c == "nr":
            self.normal[int(t[1])] = [int(x, 16) for x in t[2:6]]
        elif c == "w":
            e.put32(self.car_ptr(t[1]) + C_NW, int(t[2]))
        elif c == "f":
            e.put32(AB + ACT_FIELDS[t[1]], int(t[2], 16))
        elif c == "ti":
            # 11d-3a's from here: a car's type info, as the maximum
            # acceleration and deceleration read it.
            cti = CTIS + CTI_STRIDE * int(t[1])
            for (f, off), x in zip(CTI_FIELDS, t[2:]):
                e.put32(cti + off, int(x, 16))
        elif c == "col":
            # A car's body and its collisions: each whether two cars' and
            # which.
            k, n = int(t[1]), int(t[2])
            body = BODIES + BODY_STRIDE * k
            e.put32(car_at(k) + C_BODY, body)
            e.mem[body + B_NCOLL] = n & 0xff
            for i in range(n):
                two, c1, c2 = t[3 + 3 * i:6 + 3 * i]
                self.colls[COLLS + COLL_STRIDE * (NCOLLS * k + i)] = (
                    int(two), self.car_ptr(c1), self.car_ptr(c2))
        elif c == "ch":
            if t[1] == "none":
                e.put32(WORLD + W_CHOPPER, 0)
            else:
                e.put32(WORLD + W_CHOPPER, CHOPPER)
                e.put32(CHOPPER + CH_PLAN, int(t[1]))
                e.put32(CHOPPER + CH_POS, int(t[2], 16))
                e.put32(CHOPPER + CH_POS + 4, int(t[3], 16))
        elif c == "cm":
            # The AI cops' count, then each cop: "-" for none, else its car
            # and its DesiredLogicState.
            if t[1] == "none":
                e.put32(GLOBALS["COPM"], 0)
            else:
                e.mem[COPM:COPM + 64] = bytes(64)
                e.mem[COPS:COPS + COP_STRIDE * NCOPS] = bytes(
                    COP_STRIDE * NCOPS)
                e.put32(COPM + 4, int(t[1]))
                for i, s in enumerate(t[2:2 + NCOPS]):
                    if s == "-":
                        continue
                    cop = COPS + COP_STRIDE * i
                    k, st = s.split(":")
                    e.put32(COPM + 16 + 4 * i, cop)
                    e.put32(cop + 4, self.car_ptr(k))
                    e.put32(cop + 16, int(st))
                e.put32(GLOBALS["COPM"], COPM)
        elif c == "pl":
            e.put32(GLOBALS["NPLAYERS"], int(t[1]))
            for i in range(2):
                p = PLOBJ + PLOBJ_STRIDE * i
                e.put32(GLOBALS["PLAYERS"] + 4 * i, p)
                e.put32(p + 4, self.car_ptr(t[2 + i]))
        elif c == "cl":
            e.put32(self.car_ptr(t[1]) + C_LIGHTS, int(t[2], 16))
        elif c == "sk":
            e.mem[DRIVERS + DRIVER_STRIDE * int(t[1]) + DRV_SKILL] = (
                int(t[2]) & 0xff)
        else:
            raise SystemExit("bad op %r" % (t,))

    def dump_after(self):
        """The car the list's car leaves out, and the world's two counts."""
        w = self.w
        self.emit("  exclude %s" % self.name(
            w(w(w(LIST) + C_CTRL) + K_EXCLUDE)))
        self.emit("  ids %d %d" % (w(WORLD + W_ID), w(WORLD + W_PDT_ID)))

    def op(self, t):
        e, w = self.e, self.w
        c = t[0]
        if c == "U":
            self.set_route(t)
        elif c == "P":
            a = self.cur_route + RT_HEADER + RT_POINT * self.cur_n
            for i in range(28):
                e.put32(a + 4 * i, int(t[1 + i], 16))
            self.cur_n += 1
        elif c == "K":
            a = SIGNS + SIGN_SIZE * int(t[1])
            e.mem[a] = int(t[2]) & 0xff
            struct.pack_into("<H", e.mem, a + 2, int(t[3]) & 0xffff)
        elif c == "C":
            self.set_car(t)
        elif c == "G":
            e.put32(GLOBALS[t[1]], int(t[2], 16))
        elif c == "Q":
            self.dec[int(t[1])] = (int(t[2]), int(t[3]))
        elif c == "R":
            e.put32(RACE + RACE_START, int(t[1], 16))
        elif c == "N":
            e.put32(LIST, self.car_ptr(t[1]))
            e.put32(LIST + 4, int(t[2]))
            e.put32(LIST + LIST_HL, int(t[3], 16))
            e.put32(LIST + LIST_HD, int(t[4], 16))
        elif c == "E":
            a = self.entry(t[1])
            for i in range(6):
                e.put32(a + 4 * i, int(t[2 + i], 16))
            e.put32(a + 24, self.car_ptr(t[8]))
        elif c == "D":
            e.put32(LOC, self.route_of(t[1]))
            e.put32(LOC + 4, self.point_of(t[1], t[2]))
            e.put32(LOC + 8, int(t[3]))
            e.put32(LOC + 12, int(t[4], 16))
        elif c == "T":
            e.mem[TARGET:TARGET + TARGET_BYTES] = bytes(TARGET_BYTES)
            e.put32(TARGET + 496, int(t[1]))
            e.put32(TARGET + 512, int(t[2], 16))
            e.mem[TARGET + 516] = 0xff
        elif c == "Y":
            self.put_point(TARGET, t[1:])
        elif c == "H":
            a = self.car_target(t[1])
            e.mem[a:a + TARGET_BYTES] = bytes(TARGET_BYTES)
            e.put32(a + 496, int(t[2]))
            e.put32(a + 512, int(t[3], 16))
            e.mem[a + 516] = 0xff
            e.mem[a + 500] = int(t[4]) & 0xff
            e.put32(a + 504, int(t[5]))
            e.put32(a + 508, int(t[6]))
        elif c == "I":
            self.put_point(self.car_target(t[1]), t[2:])
        elif c == "X":
            self.set_choice(CHOICE, t)
        elif c == "O":
            self.set_choice(OTHER, t)
        elif c == "W":
            e.put32(WALK, self.route_of(t[1]))
            e.put32(WALK + 4, self.point_of(t[1], t[2]))
            e.put32(WALK + 8, int(t[3]))
            e.put32(WALK + 20, int(t[4]))
            e.put32(WALK + 12, int(t[5], 16))
            e.put32(WALK + 16, int(t[6]))
        elif c == "F":
            self.fill(FPL, FPL_BYTES)
            e.put32(FPL, 0)
        elif c == "a":
            self.emit("  ctype %d" % self.call(GET_CHOICE_TYPE, int(t[1])))
        elif c == "b":
            self.emit("  dline %d" % self.call(GET_DRIVING_LINE, int(t[1]),
                                               self.car_ptr(t[2])))
        elif c == "c":
            self.call(SET_CHOICE, CHOICE, int(t[1]), self.car_ptr(t[2]),
                      int(t[3]))
            self.dump_choice(CHOICE, "choice")
        elif c == "d":
            self.call(SET_CHOICE_LOC, CHOICE, LOC)
            self.dump_choice(CHOICE, "choice")
        elif c == "e":
            self.call(SET_CHOICE_CHOICE, CHOICE, OTHER)
            self.dump_choice(CHOICE, "choice")
        elif c == "f":
            self.call(CLEAR, CHOICE)
            self.dump_choice(CHOICE, "choice")
        elif c == "g":
            self.emit("  valid %d" % self.call(IS_VALID, CHOICE, LOC, LIST))
        elif c == "h":
            self.emit("  equal %d" % self.call(IS_EQUAL, CHOICE, OTHER))
        elif c == "i":
            got = self.call(ENOUGH_ROOM, CHOICE, self.entry(t[1]), LIST)
            self.emit("  room %d" % got)
        elif c == "j":
            car = self.car_ptr(t[1])
            self.call(FIXUP, CHOICE, car, int(t[2]), LIST)
            self.emit("  exclude %s" % self.name(
                w(w(car + C_CTRL) + K_EXCLUDE)))
        elif c == "k":
            got = self.call(PREFERRED, CHOICE, self.entry(t[1]), LIST, LOC)
            self.emit("  side %d" % got)
        elif c == "m":
            self.call(FPL_ADD, FPL, int(t[1]), int(t[2]), int(t[3]),
                      int(t[5]), f12=int(t[4], 16))
            self.dump_fpl()
        elif c == "n":
            me = w(LIST)
            got = self.call(ADVANCE, FPL, WALK, WALK + 4, WALK + 8,
                            WALK + 12, WALK + 16, WALK + 20, w(me + C_CTRL))
            self.dump_walk(got)
        elif c == "o":
            self.fill(LPTR, 4)
            self.call(POINTS_TO_USE, FPL, TARGET, LOC, LIST, LPTR)
            self.dump_fpl()
            self.emit("  L %s" % fx(w(LPTR)))
        elif c == "p":
            self.call(UP_TO, FPL, LOC, self.point_of(t[1], t[2]))
            self.dump_fpl()
        elif c == "q":
            self.call(SPEED_BACK, LIST, LOC, int(t[1]))
            self.emit("  speed %s" % fx(e.fpr[0]))
        elif c == "r":
            e.put32(LPTR, int(t[1], 16))
            self.call(REDUCE, LPTR, int(t[2]), self.point_of(t[3], t[4]),
                      int(t[5]), int(t[8]), f12=int(t[6], 16),
                      f13=int(t[7], 16))
            self.emit("  l %s" % fx(w(LPTR)))
        elif c == "s":
            self.call(ADD_TO_TARGET, LOC, FPL + 4 + FP_SIZE * int(t[2]),
                      TARGET, f12=int(t[1], 16))
            self.dump_target()
        elif c == "t":
            z = int(t[3]) if len(t) > 3 else 0
            self.call(FILL_UP, 0 if z & 2 else TARGET, 0 if z & 1 else LOC,
                      0 if z & 4 else LIST, int(t[1]), int(t[2]))
            self.dump_target()
            me = w(LIST)
            self.emit("  exclude %s" % self.name(
                w(w(me + C_CTRL) + K_EXCLUDE)))
        elif c == "u":
            got = self.call(GRACE, w(GLOBALS["RACE"]), self.car_ptr(t[1]))
            self.emit("  grace %d" % got)
        elif c in "vw":
            if c == "v":
                got = self.call(BUILD, CHOICE, TARGET, LOC, LIST, int(t[1]),
                                f12=0x3f800000, f13=0x40000000)
            else:
                got = self.call(AROUND, CHOICE, TARGET, LIST, LOC,
                                f12=0x3f800000)
            self.emit("  built %d" % got)
            self.dump_target()
            self.emit("  exclude %s" % self.name(
                w(w(w(LIST) + C_CTRL) + K_EXCLUDE)))
            self.dump_its()
        elif c == "x":
            e.put32(VEC, int(t[1], 16))
            e.put32(VEC + 4, int(t[2], 16))
            self.emit("  ahead %d" % s32(self.call(SEARCH, FPL, VEC,
                                                    int(t[3]))))
        elif c == "y":
            nc = self.entry(t[1]) if int(t[1]) >= 0 else 0
            self.call(CLEARANCE, CHOICE, LIST, nc, FPL, int(t[2]))
            self.emit("  clear %s" % fx(e.fpr[0]))
        elif c == "z":
            self.call(SMOOTH, FPL, TARGET, LIST, int(t[1]), int(t[4]),
                      f12=int(t[2], 16), f13=int(t[3], 16))
            self.dump_target()
        elif c == "M":
            self.call(PARALLEL, CHOICE, TARGET, LIST, FPL, f12=int(t[1], 16))
            self.dump_target()
            self.dump_its()
        elif c == "A":
            k = int(t[1])
            a = car_at(k)
            b = BODIES + BODY_STRIDE * k
            e.put32(a + C_ACC, int(t[2], 16))
            e.put32(a + C_ACC + 4, int(t[3], 16))
            e.put32(a + C_VEL + 8, int(t[4], 16))
            struct.pack_into("<H", e.mem, a + C_ANGLE, int(t[5]) & 0xffff)
            e.put32(a + C_BODY, b)
            for i in range(3):
                e.put32(b + B_MIN + 4 * i, int(t[6 + i], 16))
                e.put32(b + B_MAX + 4 * i, int(t[9 + i], 16))
        elif c == "Z":
            e.put32(w(self.car_ptr(t[1]) + C_CTRL) + K_EXCLUDE,
                    self.car_ptr(t[2]))
        elif c == "S":
            e.mem[TARGET] = int(t[1]) & 0xff
        elif c == "1":
            e.put32(OUT, PAT32)
            e.put32(OUT + 4, PAT32)
            got = self.call(OVERLAP, OUT, OUT + 4, f12=int(t[1], 16),
                            f13=int(t[2], 16), f14=int(t[3], 16),
                            f15=int(t[4], 16))
            self.emit("  ovl %d %s %s" % (got, fx(w(OUT)), fx(w(OUT + 4))))
        elif c == "2":
            e.put32(OUT, PAT32)
            e.put32(OUT + 4, PAT32)
            self.call(TISA, OUT, OUT + 4, f12=int(t[1], 16),
                      f13=int(t[2], 16), f14=int(t[3], 16))
            self.emit("  tisa %s %s" % (fx(w(OUT)), fx(w(OUT + 4))))
        elif c == "3":
            self.put_obb(OBB_A, t[1:7])
            self.put_obb(OBB_B, t[7:13])
            for i in range(4):
                e.put32(VEC_D + 4 * i, int(t[13 + i], 16) if i < 2 else 0)
                e.put32(VEC_V + 4 * i, int(t[15 + i], 16) if i < 2 else 0)
            self.call(WHEN_2D, OBB_A, OBB_B, VEC_D, VEC_V)
            self.emit("  when %s" % fx(e.fpr[0]))
        elif c == "4":
            z = int(t[4])
            tgt = TARGET if int(t[1]) < 0 else self.car_target(t[1])
            self.fill(OBBS, OBB_SIZE * NOBBS)
            self.call(MAKE_OBBS, 0, 0 if z & 1 else tgt,
                      0 if z & 2 else OBBS, self.car_ptr(t[2]),
                      f12=int(t[3], 16))
            self.dump_obbs()
        elif c == "5":
            got = self.call(STOPPED, 0, self.entry(t[1]), LIST)
            self.emit("  stopped %d" % got)
        elif c == "6":
            e.put32(OUT, PAT32)
            got = self.call(WILL, 0, TARGET, LOC, w(LIST), self.car_ptr(t[1]),
                            OUT, f12=int(t[2], 16))
            self.emit("  will %d %s" % (got, fx(w(OUT))))
        elif c == "7":
            e.put32(OUT, PAT32)
            got = self.call(WHO, 0, TARGET, LIST, 0 if int(t[2]) & 1 else LOC,
                            OUT, f12=int(t[1], 16))
            self.emit("  who %s %s id %d" % (self.name(got), fx(w(OUT)),
                                             w(WORLD + W_ID)))
        elif c == "8":
            for a in (O_SCORE, O_HCAR, O_HTIME):
                e.put32(a, PAT32)
            got = self.call(IS_DRIVEABLE, CHOICE, TARGET, int(t[1]), O_SCORE,
                            O_HCAR, O_HTIME, LOC, LIST, f12=0x3f800000,
                            f13=int(t[3], 16), f14=0x40000000,
                            stack=[int(t[2])], limit=CHOOSE_LIMIT)
            self.emit("  drive %d %s %s %s" % (got, fx(w(O_SCORE)),
                                               self.name(w(O_HCAR)),
                                               fx(w(O_HTIME))))
            self.dump_target()
            self.dump_after()
        elif c == "9":
            e.put32(O_FOUND, int(t[3]))
            e.put32(O_BSCORE, int(t[4], 16))
            e.put32(O_RTIME, int(t[5], 16))
            for a in (O_BOUT, O_HCAR, O_HTIME):
                e.put32(a, PAT32)
            self.fill(BEST_CH, 12)
            self.fill(ROUND_CH, 12)
            self.fill(TARGET2, TARGET_BYTES)
            self.fill(TARGET3, TARGET_BYTES)
            got = self.call(TRY_CHOICE, CHOICE, int(t[1]), LOC, LIST, O_FOUND,
                            TARGET, BEST_CH, TARGET2, f12=int(t[2], 16),
                            f13=0x40400000,
                            stack=[O_BOUT, O_BSCORE, ROUND_CH, TARGET3,
                                   O_RTIME, O_HCAR, O_HTIME,
                                   self.car_ptr(t[6])],
                            limit=CHOOSE_LIMIT)
            self.emit("  try %d found %d bout %08x score %s round %s hit %s %s"
                      % (got, s32(w(O_FOUND)), w(O_BOUT), fx(w(O_BSCORE)),
                         fx(w(O_RTIME)), self.name(w(O_HCAR)),
                         fx(w(O_HTIME))))
            self.dump_choice(BEST_CH, "best")
            self.dump_choice(ROUND_CH, "round")
            self.dump_target()
            self.dump_target(TARGET2)
            self.dump_target(TARGET3)
            self.dump_after()
        elif c == "0":
            e.put32(O_OUT, int(t[3], 16))
            got = self.call(MAKE_NEW, CHOICE, TARGET, LOC, LIST, O_OUT,
                            int(t[2]), f12=int(t[1], 16), f13=0x40400000,
                            limit=CHOOSE_LIMIT)
            self.emit("  new %d out %08x" % (got, w(O_OUT)))
            self.dump_choice(CHOICE, "choice")
            self.dump_target()
            self.dump_after()
        elif c == "V":
            e.put32(O_OUT, int(t[4], 16))
            got = self.call(AROUND_CAR, CHOICE, TARGET, O_OUT,
                            self.entry(t[1]), LOC, LIST, int(t[3]),
                            f12=0x3f800000, f13=int(t[2], 16),
                            f14=0x40400000, limit=CHOOSE_LIMIT)
            self.emit("  around %d out %08x" % (got, w(O_OUT)))
            self.dump_choice(CHOICE, "choice")
            self.dump_target()
            self.dump_after()
        elif c.startswith("@"):
            self.act_op(t)
        else:
            raise SystemExit("bad op %r" % (t,))

    def run(self, scenarios):
        for i, sc in enumerate(scenarios):
            self.emit("B %d" % i)
            self.reset()
            for ln in sc:
                if ln[0] not in "CKPU":
                    self.emit("> " + ln[:48])
                self.op(ln.split())
        stray = (self.e.eediv_pcs - {SMOOTH_DIV, SLOWER_DIV} - WILL_DIVS
                 - EST_DIVS)
        if stray:
            raise SystemExit("the EE's divide by zero at %s, which the port "
                             "divides as IEEE does"
                             % ", ".join("0x%08x" % pc for pc in sorted(stray)))
        return self.out


# ================================================================ the build


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


def build_harness(tmp, name="drivingchoice_test"):
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


def M(name, before, after, rel=DCC):
    return (name, rel, before, after)


def AM(name, before, after):
    return (name, AAS, before, after)


MUTATIONS = [
    # -- the literal pool ----------------------------------------------
    M("k-on-road", "#define DC_ON_ROAD          -0.00100000005f",
      "#define DC_ON_ROAD          0.0f"),
    M("k-room-margin", "#define DC_ROOM_MARGIN       5.0f",
      "#define DC_ROOM_MARGIN       4.0f"),
    M("k-traffic-near", "#define DC_TRAFFIC_NEAR      5.0f",
      "#define DC_TRAFFIC_NEAR      6.0f"),
    M("k-near-line", "#define DC_NEAR_LINE         1.0f",
      "#define DC_NEAR_LINE         1.5f"),
    M("k-far-ahead", "#define DC_FAR_AHEAD         50.0f",
      "#define DC_FAR_AHEAD         40.0f"),
    M("k-bending", "#define DC_BENDING           0.119999997f",
      "#define DC_BENDING           0.100000001f"),
    M("k-slow", "#define DC_SLOW              26.8216362f",
      "#define DC_SLOW              25.0f"),
    M("k-fast", "#define DC_FAST              29.5038013f",
      "#define DC_FAST              31.0f"),
    M("k-slow-back", "#define DC_SPEED_SLOW_BACK   0.25f",
      "#define DC_SPEED_SLOW_BACK   0.3f"),
    M("k-fast-back", "#define DC_SPEED_FAST_BACK   0.5f",
      "#define DC_SPEED_FAST_BACK   0.6f"),
    M("k-past-target", "#define DC_PAST_TARGET      -10.0f",
      "#define DC_PAST_TARGET      -5.0f"),
    M("k-min-points", "#define DC_MIN_POINTS        5",
      "#define DC_MIN_POINTS        4"),
    M("k-edge", "#define DC_EDGE              1.0f",
      "#define DC_EDGE              0.5f"),
    # -- the helpers ---------------------------------------------------
    M("min-s-max", "    return ft < fs ? ft : fs;",
      "    return ft < fs ? fs : ft;"),
    M("max-s-min", "    return fs < ft ? ft : fs;",
      "    return fs < ft ? fs : ft;"),
    M("lat-sign", "           - (y - p->Position.y) * p->Direction.x;",
      "           + (y - p->Position.y) * p->Direction.x;"),
    M("lat-dir", "    return (x - p->Position.x) * p->Direction.y",
      "    return (x - p->Position.x) * p->Direction.x"),
    # -- GetChoiceType, GetDrivingLine ---------------------------------
    M("ct-plus", "return line % 2 + 1;", "return line % 2;"),
    M("ct-and", "return line % 2 + 1;", "return (line & 1) + 1;"),
    M("dl-type",
      "return (int32_t)car->pCarTypeInfo->CarClass * 2 + (type - 1);",
      "return (int32_t)car->pCarTypeInfo->CarClass * 2 + type;"),
    M("dl-class",
      "return (int32_t)car->pCarTypeInfo->CarClass * 2 + (type - 1);",
      "return (int32_t)car->pCarTypeInfo->CarClass * 3 + (type - 1);"),
    # -- SetChoice and its two callers, Clear --------------------------
    M("sc-line-car", "        ok = car == NULL;", "        ok = 1;"),
    M("sc-side-car",
      "ok = drivingchoice_type_is_side_of_car(type) && car != NULL;",
      "ok = drivingchoice_type_is_side_of_car(type);"),
    M("sc-side-type",
      "ok = drivingchoice_type_is_side_of_car(type) && car != NULL;",
      "ok = car != NULL;"),
    M("sc-ok", "    if (ok) {", "    if (!ok) {"),
    M("sc-extra", "d->UseExtraLateralDistance = extra;",
      "d->UseExtraLateralDistance = 0;"),
    M("sc-type", "        d->Type = type;\n", ""),
    M("sc-car", "d->pCar = car;", "d->pCar = NULL;"),
    M("scl-line", "drivingchoice_get_choice_type(loc->DrivingLine),",
      "drivingchoice_get_choice_type(loc->DrivingLine + 1),"),
    M("scc-car", "drivingchoice_set_choice(d, other->Type, other->pCar,",
      "drivingchoice_set_choice(d, other->Type, NULL,"),
    M("scc-extra", "                             other->UseExtraLateralDistance);",
      "                             0);"),
    M("cl-extra", "    d->UseExtraLateralDistance = 0;",
      "    d->UseExtraLateralDistance = 1;"),
    M("cl-type", "    d->Type = CHOICE_NONE;",
      "    d->Type = CHOICE_DRIVING_LINE_0;"),
    M("cl-car", "    d->pCar = NULL;\n}", "}"),
    # -- IsValid, IsEqualTo --------------------------------------------
    M("iv-clear-rn", "? -1 : (int32_t)loc->pRoute->RouteNumber;",
      "? 0 : (int32_t)loc->pRoute->RouteNumber;"),
    M("iv-racing-signed", "if ((uint32_t)rn < 50u) {", "if (rn < 50) {"),
    M("iv-racing-bound", "if ((uint32_t)rn < 50u) {",
      "if ((uint32_t)rn < 49u) {"),
    M("iv-line-index",
      "drivingchoice_get_driving_line(d->Type, list->MyCar)].Flags;",
      "drivingchoice_get_driving_line(d->Type, list->MyCar) + 1].Flags;"),
    M("iv-flag-valid",
      "return (flags & DLI_IS_VALID) != 0 || ((flags >> 1) & 1u) != 0;",
      "return ((flags >> 1) & 1u) != 0;"),
    M("iv-flag-two",
      "return (flags & DLI_IS_VALID) != 0 || ((flags >> 1) & 1u) != 0;",
      "return (flags & DLI_IS_VALID) != 0;"),
    M("iv-flag-and",
      "return (flags & DLI_IS_VALID) != 0 || ((flags >> 1) & 1u) != 0;",
      "return (flags & DLI_IS_VALID) != 0 && ((flags >> 1) & 1u) != 0;"),
    M("iv-traffic-lo", "if ((uint32_t)(rn - 50) < 20u)",
      "if ((uint32_t)(rn - 51) < 19u)"),
    M("iv-traffic-hi", "if ((uint32_t)(rn - 50) < 20u)",
      "if ((uint32_t)(rn - 50) < 21u)"),
    M("iv-traffic-line", "return d->Type == CHOICE_DRIVING_LINE_0;",
      "return 1;"),
    M("iv-other-route",
      "            return d->Type == CHOICE_DRIVING_LINE_0;\n        return 0;",
      "            return d->Type == CHOICE_DRIVING_LINE_0;\n        return 1;"),
    M("iv-side", "return nearbycarlist_get_nearby_car(list, d->pCar) != NULL;",
      "return 1;"),
    M("iv-none", "    return 0;\n}\n\nint drivingchoice_is_equal_to",
      "    return 1;\n}\n\nint drivingchoice_is_equal_to"),
    M("eq-side-car",
      "return d->pCar == other->pCar && d->Type == other->Type;",
      "return d->Type == other->Type;"),
    M("eq-side-type",
      "return d->pCar == other->pCar && d->Type == other->Type;",
      "return d->pCar == other->pCar;"),
    M("eq-line-car", "    return d->Type == other->Type;\n}",
      "    return d->Type == other->Type && d->pCar == other->pCar;\n}"),
    # -- IsEnoughRoom --------------------------------------------------
    M("er-line",
      "        return 1;\n    if (!drivingchoice_type_is_side_of_car(d->Type))\n"
      "        return 0;\n    if (!(car_get",
      "        return 0;\n    if (!drivingchoice_type_is_side_of_car(d->Type))\n"
      "        return 0;\n    if (!(car_get"),
    M("er-none",
      "        return 0;\n    if (!(car_get_amount_out_of_bounds",
      "        return 1;\n    if (!(car_get_amount_out_of_bounds"),
    M("er-on-road",
      "if (!(car_get_amount_out_of_bounds(d->pCar) < DC_ON_ROAD))\n"
      "        return 1;",
      "if (!(car_get_amount_out_of_bounds(d->pCar) < DC_ON_ROAD))\n"
      "        return 0;"),
    M("er-on-road-me",
      "if (!(car_get_amount_out_of_bounds(d->pCar) < DC_ON_ROAD))",
      "if (!(car_get_amount_out_of_bounds(list->MyCar) < DC_ON_ROAD))"),
    M("er-rp-me", "    rp = car_get_route_point(d->pCar);",
      "    rp = car_get_route_point(list->MyCar);"),
    M("er-room-mine",
      "    rp = car_get_route_point(d->pCar);\n"
      "    room = (nc->ApparentHalfSizeL + list->MyHalfSizeL) + DC_ROOM_MARGIN;",
      "    rp = car_get_route_point(d->pCar);\n"
      "    room = nc->ApparentHalfSizeL + DC_ROOM_MARGIN;"),
    M("er-room-its",
      "    rp = car_get_route_point(d->pCar);\n"
      "    room = (nc->ApparentHalfSizeL + list->MyHalfSizeL) + DC_ROOM_MARGIN;",
      "    rp = car_get_route_point(d->pCar);\n"
      "    room = list->MyHalfSizeL + DC_ROOM_MARGIN;"),
    M("er-lat-xy",
      "lat = lateral(rp, d->pCar->State.Position.x, d->pCar->State.Position.y);",
      "lat = lateral(rp, d->pCar->State.Position.y, d->pCar->State.Position.x);"),
    M("er-left-type",
      "if (d->Type == CHOICE_LEFT_SIDE_OF_CAR)\n        return -rp",
      "if (d->Type == CHOICE_RIGHT_SIDE_OF_CAR)\n        return -rp"),
    M("er-left-room", "return -rp->LeftWidth < lat - room;",
      "return -rp->LeftWidth < lat + room;"),
    M("er-left-width", "return -rp->LeftWidth < lat - room;",
      "return -rp->RightWidth < lat - room;"),
    M("er-right-room", "return lat + room < rp->RightWidth;",
      "return lat - room < rp->RightWidth;"),
    M("er-right-width", "return lat + room < rp->RightWidth;",
      "return lat + room < rp->LeftWidth;"),
    # -- FixupCarToExcludeFromCollisionPrediction ----------------------
    M("fx-line-null",
      "    if (drivingchoice_type_is_driving_line(d->Type)) {\n"
      "        car_ai_controller(car)->CarToExcludeFromCollisionPrediction = NULL;\n",
      "    if (drivingchoice_type_is_driving_line(d->Type)) {\n"),
    M("fx-unchecked-null",
      "    if (!check) {\n"
      "        car_ai_controller(car)->CarToExcludeFromCollisionPrediction = NULL;\n",
      "    if (!check) {\n"),
    M("fx-check", "    if (!check) {", "    if (check) {"),
    M("fx-traffic",
      "    if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && other->State",
      "    if (other->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && other->State"),
    M("fx-traffic-me",
      "    if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && other->State",
      "    if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && other->State"),
    M("fx-dot-sign", "           < 0.0f) {", "           > 0.0f) {"),
    M("fx-dot-x",
      "&& other->State.BodyMatrix.v0.x * car->State.BodyMatrix.v0.x",
      "&& other->State.BodyMatrix.v0.y * car->State.BodyMatrix.v0.x"),
    M("fx-dot-y",
      "+ other->State.BodyMatrix.v0.y * car->State.BodyMatrix.v0.y",
      "- other->State.BodyMatrix.v0.y * car->State.BodyMatrix.v0.y"),
    M("fx-its-car", "            && its->pCar == car) {",
      "            && its->pCar != car) {"),
    M("fx-its-side",
      "        if (drivingchoice_type_is_side_of_car(its->Type)\n"
      "            && its->pCar == car) {",
      "        if (its->pCar == car) {"),
    M("fx-its-left",
      "                if (d->Type == CHOICE_RIGHT_SIDE_OF_CAR)\n"
      "                    ok = 0;",
      "                if (d->Type == CHOICE_LEFT_SIDE_OF_CAR)\n"
      "                    ok = 0;"),
    M("fx-its-right", "} else if (its->Type == CHOICE_RIGHT_SIDE_OF_CAR",
      "} else if (its->Type == CHOICE_LEFT_SIDE_OF_CAR"),
    M("fx-its-right-mine",
      "                       && d->Type == CHOICE_LEFT_SIDE_OF_CAR) {",
      "                       && d->Type == CHOICE_RIGHT_SIDE_OF_CAR) {"),
    M("fx-pull-over",
      "if (act == AIACTION_PULL_OVER && d->Type == CHOICE_LEFT_SIDE_OF_CAR)",
      "if (act != AIACTION_PULL_OVER && d->Type == CHOICE_LEFT_SIDE_OF_CAR)"),
    M("fx-pull-over-side",
      "if (act == AIACTION_PULL_OVER && d->Type == CHOICE_LEFT_SIDE_OF_CAR)",
      "if (act == AIACTION_PULL_OVER && d->Type == CHOICE_RIGHT_SIDE_OF_CAR)"),
    M("fx-no-action", "? oc->CurrentAction->Type : AIACTION_NONE;",
      "? oc->CurrentAction->Type : AIACTION_PULL_OVER;"),
    M("fx-ok", "    if (!ok)\n        return;", "    if (0)\n        return;"),
    M("fx-room", "    if (!drivingchoice_is_enough_room(",
      "    if (0 && !drivingchoice_is_enough_room("),
    M("fx-room-entry",
      "            d, nearbycarlist_get_nearby_car(list, d->pCar), list))",
      "            d, nearbycarlist_get_nearby_car(list, list->MyCar), list))"),
    M("fx-store",
      "car_ai_controller(car)->CarToExcludeFromCollisionPrediction = d->pCar;",
      "car_ai_controller(car)->CarToExcludeFromCollisionPrediction = NULL;"),
    # -- GetPreferredSideOfCar -----------------------------------------
    M("ps-closest-null", "    if (cp == NULL)\n        cp = p;\n", ""),
    M("ps-closest-loc", "    if (cp == NULL)\n        cp = p;",
      "    if (cp == NULL)\n        cp = p + 1;"),
    M("ps-closest-from",
      "loc->pRoute, (const bVector2 *)&other->State.Position, p);",
      "loc->pRoute, (const bVector2 *)&me->State.Position, p);"),
    M("ps-other-lat",
      "otherLat = lateral(cp, other->State.Position.x, other->State.Position.y);",
      "otherLat = lateral(p, other->State.Position.x, other->State.Position.y);"),
    M("ps-other-off",
      "otherOff = otherLat - trpoint_get_driving_line_offset(cp, line);",
      "otherOff = otherLat;"),
    M("ps-other-off-p",
      "otherOff = otherLat - trpoint_get_driving_line_offset(cp, line);",
      "otherOff = otherLat - trpoint_get_driving_line_offset(p, line);"),
    M("ps-my-off",
      "    myOff = lateral(p, me->State.Position.x, me->State.Position.y)\n"
      "            - trpoint_get_driving_line_offset(p, line);",
      "    myOff = lateral(p, me->State.Position.x, me->State.Position.y);"),
    M("ps-traffic",
      "if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && otherOff",
      "if (me->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && otherOff"),
    M("ps-traffic-near", "        && otherOff < DC_TRAFFIC_NEAR) {",
      "        && fabsf(otherOff) < DC_TRAFFIC_NEAR) {"),
    M("ps-traffic-side", "        decided = 1;\n        left = 0;",
      "        decided = 1;\n        left = 1;"),
    M("ps-traffic-open", "        decided = 1;\n        left = 0;",
      "        left = 0;"),
    M("ps-my-abs", "if (!decided && fabsf(myOff) <= DC_NEAR_LINE",
      "if (!decided && myOff <= DC_NEAR_LINE"),
    M("ps-other-abs", "        && fabsf(otherOff) <= DC_NEAR_LINE",
      "        && otherOff <= DC_NEAR_LINE"),
    M("ps-far-y", "DC_FAR_AHEAD < nc->Position.y",
      "DC_FAR_AHEAD < nc->Position.x"),
    M("ps-bend-abs", "        && DC_BENDING <= fabsf(curv)) {",
      "        && DC_BENDING <= curv) {"),
    M("ps-bend-side", "left = 0.0f < curv ? 0 : 1;",
      "left = 0.0f < curv ? 1 : 0;"),
    M("ps-bend-open", "        left = 0.0f < curv ? 0 : 1;\n        decided = 1;",
      "        left = 0.0f < curv ? 0 : 1;"),
    M("ps-away", "left = otherOff < myOff ? 0 : 1;",
      "left = otherOff < myOff ? 1 : 0;"),
    M("ps-room-mine",
      "\n    room = (nc->ApparentHalfSizeL + list->MyHalfSizeL) + DC_ROOM_MARGIN;\n"
      "    if (left)",
      "\n    room = nc->ApparentHalfSizeL + DC_ROOM_MARGIN;\n    if (left)"),
    M("ps-room-its",
      "\n    room = (nc->ApparentHalfSizeL + list->MyHalfSizeL) + DC_ROOM_MARGIN;\n"
      "    if (left)",
      "\n    room = list->MyHalfSizeL + DC_ROOM_MARGIN;\n    if (left)"),
    M("ps-left-room", "blocked = otherLat - room < -cp->LeftWidth;",
      "blocked = otherLat + room < -cp->LeftWidth;"),
    M("ps-left-width", "blocked = otherLat - room < -cp->LeftWidth;",
      "blocked = otherLat - room < -cp->RightWidth;"),
    M("ps-right-room", "blocked = cp->RightWidth < otherLat + room;",
      "blocked = cp->RightWidth < otherLat - room;"),
    M("ps-right-width", "blocked = cp->RightWidth < otherLat + room;",
      "blocked = cp->LeftWidth < otherLat + room;"),
    M("ps-blocked", "return blocked ? !left : left;", "return left;"),
    # -- FuturePointList::Add ------------------------------------------
    M("fa-route", "p->nRouteNumber = route;", "p->nRouteNumber = route + 1;"),
    M("fa-point", "p->nPointNumber = point;", "p->nPointNumber = point + 1;"),
    M("fa-line", "p->nLine = line;", "p->nLine = 0;"),
    M("fa-count", "    l->NumPoints++;\n", ""),
    M("fa-crossed", "p->bCrossedSignpost = crossed;",
      "p->bCrossedSignpost = 0;"),
    M("fa-offset", "p->fOffset = offset;", "p->fOffset = 0.0f;"),
    # -- AdvancePoint --------------------------------------------------
    M("ap-no-sign", "    if (trpoint_has_signpost(*point)) {", "    if (0) {"),
    M("ap-off-zero",
      "float off = trpoint_get_driving_line_offset(*point, *line);",
      "float off = 0.0f;"),
    M("ap-off-after", "trpoint_get_position3(*point, &pos, 0.0f, off);",
      "trpoint_get_position3(*point, &pos, 0.0f,\n"
      "                                  trpoint_get_driving_line_offset("
      "*point, *line));"),
    M("ap-decision", "            && gAISignPostDecisionFn(ctrl, s, line,",
      "            && !gAISignPostDecisionFn(ctrl, s, line,"),
    M("ap-decision-ctrl", "            && gAISignPostDecisionFn(ctrl, s, line,",
      "            && gAISignPostDecisionFn(NULL, s, line,"),
    M("ap-decision-loc", "                                     ctrl->CurrentDrivingLocation)) {",
      "                                     NULL)) {"),
    M("ap-pos-ahead", "trpoint_get_position3(*point, &pos, 0.0f, off);",
      "trpoint_get_position3(*point, &pos, 1.0f, off);"),
    M("ap-route", "            *route = signpost_get_new_route(s);\n", ""),
    M("ap-point", "            *point = np;\n", ""),
    M("ap-pn", "*pointNumber = troute_get_point_number(*route, np);",
      "*pointNumber = troute_get_point_number(*route, np) + 1;"),
    M("ap-crossed", "*crossed = 1;", "*crossed = 0;"),
    M("ap-offset-line",
      "            *offset = lateral(np, pos.x, pos.y)\n"
      "                      - trpoint_get_driving_line_offset(np, *line);",
      "            *offset = lateral(np, pos.x, pos.y);"),
    M("ap-offset-np", "            *offset = lateral(np, pos.x, pos.y)",
      "            *offset = lateral(np, pos.y, pos.x)"),
    M("ap-sign-result",
      "            return 1;\n        }\n    }\n\n    n = ++*pointNumber;",
      "            return 0;\n        }\n    }\n\n    n = ++*pointNumber;"),
    M("ap-store-pn", "    n = ++*pointNumber;", "    n = *pointNumber + 1;"),
    M("ap-end", "    if (!(n < (*route)->NumPoints))",
      "    if (!(n < (*route)->NumPoints - 1))"),
    M("ap-end-result",
      "    if (!(n < (*route)->NumPoints))\n        return 0;",
      "    if (!(n < (*route)->NumPoints))\n        return 1;"),
    M("ap-offset-kept", "    *offset = 0.0f;\n    *crossed = 0;\n",
      "    *crossed = 0;\n"),
    M("ap-crossed-kept", "    *crossed = 0;\n    *point = troute_get_point(*route, n);",
      "    *point = troute_get_point(*route, n);"),
    M("ap-next", "    *point = troute_get_point(*route, n);",
      "    *point = troute_get_point(*route, n - 1);"),
    # -- GetRoutePointsToUse -------------------------------------------
    M("rp-count",
      "    l->NumPoints = 0;\n    ptnum = drivinglocation_is_clear(loc)",
      "    ptnum = drivinglocation_is_clear(loc)"),
    M("rp-ptnum-loc",
      "? -1 : troute_get_point_number(loc->pRoute, loc->pRoutePoint);",
      "? -1 : troute_get_point_number(loc->pRoute, loc->pRoutePoint) + 1;"),
    M("rp-last", "    i = t->NumPoints - 1;\n    if (i >= 0) {",
      "    i = t->NumPoints - 2;\n    if (i >= 0) {"),
    M("rp-racer", "if (me->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER",
      "if (me->MyDriver->TheDriverType != DRIVER_TYPE_AI_RACER"),
    M("rp-racer-traffic", "            && route->Type == TRACK_ROUTE_TRAFFIC) {",
      "            && route->Type != TRACK_ROUTE_TRAFFIC) {"),
    M("rp-own-route", "            route = loc->pRoute;\n", ""),
    M("rp-ptnum-t", "ptnum = t->RoutePointNumber[i];",
      "ptnum = t->RoutePointNumber[i] + 1;"),
    M("rp-line-t", "line = t->DrivingLine[i];", "line = loc->DrivingLine;"),
    M("rp-point-t", "point = troute_get_point(route, ptnum);",
      "point = troute_get_point(route, ptnum + 1);"),
    M("rp-past", "} while (DC_PAST_TARGET < (last->x - point->Position.x)",
      "} while (DC_PAST_TARGET > (last->x - point->Position.x)"),
    M("rp-past-dx",
      "                                      * point->Direction.x\n"
      "                                  + (last->y",
      "                                      * point->Direction.y\n"
      "                                  + (last->y"),
    M("rp-past-dy", "                                  + (last->y - point->Position.y)",
      "                                  - (last->y - point->Position.y)"),
    M("rp-empty-xy",
      "*currentL = lateral(point, me->State.Position.x, me->State.Position.y);",
      "*currentL = lateral(point, me->State.Position.y, me->State.Position.x);"),
    M("rp-empty-test", "    if (t->NumPoints == 0) {",
      "    if (t->NumPoints <= 1) {"),
    M("rp-p2", "            *currentL = lateral(p2, t->Points",
      "            *currentL = lateral(point, t->Points"),
    M("rp-p2-test",
      "        if (drivetarget_get_route_and_route_point(t, t->NumPoints - 1, &r2,",
      "        if (0 && drivetarget_get_route_and_route_point(t, t->NumPoints - 1, &r2,"),
    M("rp-else-last",
      "            *currentL = lateral(point, t->Points[t->NumPoints - 1].x,\n"
      "                                t->Points[t->NumPoints - 1].y);",
      "            *currentL = lateral(point, t->Points[0].x,\n"
      "                                t->Points[0].y);"),
    M("rp-l-line", "    *currentL = *currentL - trpoint_get_driving_line_offset(point,\n"
      "                                                            loc->DrivingLine);",
      "    *currentL = *currentL - trpoint_get_driving_line_offset(point,\n"
      "                                                            line);"),
    M("rp-l-no-line", "    *currentL = *currentL - trpoint_get_driving_line_offset(point,\n"
      "                                                            loc->DrivingLine);",
      ""),
    M("rp-first-crossed",
      "                        troute_get_point_number(route, point), line, offset, 0);",
      "                        troute_get_point_number(route, point), line, offset, crossed);"),
    M("rp-first-offset",
      "                        troute_get_point_number(route, point), line, offset, 0);",
      "                        troute_get_point_number(route, point), line, 0.0f, 0);"),
    M("rp-second", "    if (l->NumPoints == 1) {", "    if (l->NumPoints == 2) {"),
    M("rp-second-crossed",
      "                            offset, 0);\n    }",
      "                            offset, crossed);\n    }"),
    M("rp-dist-sqrt", "    dist = sqrtf((me->State.Position.x - point->Position.x)",
      "    dist = ((me->State.Position.x - point->Position.x)"),
    M("rp-dist-y",
      "                 + (me->State.Position.y - point->Position.y)\n",
      "                 - (me->State.Position.y - point->Position.y)\n"),
    M("rp-look-or",
      "if (!(dist <= lookAhead) && !(l->NumPoints < DC_MIN_POINTS))",
      "if (!(dist <= lookAhead) || !(l->NumPoints < DC_MIN_POINTS))"),
    M("rp-look-min",
      "if (!(dist <= lookAhead) && !(l->NumPoints < DC_MIN_POINTS))",
      "if (!(dist <= lookAhead))"),
    M("rp-look-dist",
      "if (!(dist <= lookAhead) && !(l->NumPoints < DC_MIN_POINTS))",
      "if (!(l->NumPoints < DC_MIN_POINTS))"),
    M("rp-max", "more = l->NumPoints < FUTUREPOINTLIST_MAX;",
      "more = l->NumPoints < FUTUREPOINTLIST_MAX - 1;"),
    M("rp-dist-len", "dist = dist + point->Length;",
      "dist = dist + point->Length * 0.5f;"),
    M("rp-loop-crossed",
      "                            offset, crossed);\n    }\n}",
      "                            offset, 0);\n    }\n}"),
    # -- the road-block list -------------------------------------------
    M("ut-count",
      "    l->NumPoints = 0;\n    if (drivinglocation_is_clear(loc))\n"
      "        return;\n    rn",
      "    if (drivinglocation_is_clear(loc))\n        return;\n    rn"),
    M("ut-line", "    line = loc->DrivingLine;\n    i = troute",
      "    line = 0;\n    i = troute"),
    M("ut-start",
      "    i = troute_get_point_number(loc->pRoute, loc->pRoutePoint);",
      "    i = troute_get_point_number(loc->pRoute, loc->pRoutePoint) + 1;"),
    M("ut-end", "last = troute_get_point_number(loc->pRoute, end);",
      "last = troute_get_point_number(loc->pRoute, end) - 1;"),
    M("ut-le", "for (; !(last < i) && l->NumPoints < FUTUREPOINTLIST_MAX; i++)",
      "for (; !(last <= i) && l->NumPoints < FUTUREPOINTLIST_MAX; i++)"),
    M("ut-max", "for (; !(last < i) && l->NumPoints < FUTUREPOINTLIST_MAX; i++)",
      "for (; !(last < i) && l->NumPoints < FUTUREPOINTLIST_MAX - 1; i++)"),
    M("ut-offset", "futurepointlist_add(l, rn, i, line, 0.0f, 0);",
      "futurepointlist_add(l, rn, i, line, 1.0f, 0);"),
    # -- GetSpeedBackToLine, the grace period --------------------------
    M("sb-parallel",
      "    if (m == MOVEMENT_PARALLEL_TO_LINE)\n        return 0.0f;",
      "    if (m == MOVEMENT_PARALLEL_TO_LINE)\n        return DC_SPEED_FAST_BACK;"),
    M("sb-sides", "if ((uint32_t)(m - MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) < 2u",
      "if ((uint32_t)(m - MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) < 1u"),
    M("sb-sides-none",
      "if ((uint32_t)(m - MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) < 2u",
      "if ((uint32_t)(m - MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) < 3u"),
    M("sb-traffic",
      "        || list->MyCar->TheControlMode == TRAFFIC_CONTROL)",
      "        || list->MyCar->TheControlMode != TRAFFIC_CONTROL)"),
    M("sb-grace",
      "    if (race_grace_period_is_active(pCurrentRace, list->MyCar))\n"
      "        return 0.0f;",
      "    if (race_grace_period_is_active(pCurrentRace, list->MyCar))\n"
      "        return DC_SPEED_SLOW_BACK;"),
    M("sb-vmag", "v = list->MyCar->State.VelocityMagnitude;",
      "v = list->MyCar->State.VelocityMagnitude * 0.5f;"),
    M("sb-slow", "    if (v <= DC_SLOW)\n        return 0.0f;",
      "    if (v <= DC_SLOW)\n        return DC_SPEED_SLOW_BACK;"),
    M("sb-fast", "    if (v <= DC_FAST)\n        return DC_SPEED_SLOW_BACK;",
      "    if (v <= DC_FAST)\n        return DC_SPEED_FAST_BACK;"),
    M("sb-relaxed", "? DC_SPEED_SLOW_BACK : DC_SPEED_FAST_BACK;",
      "? DC_SPEED_FAST_BACK : DC_SPEED_SLOW_BACK;"),
    M("gr-start", "float StartOfRaceGracePeriod = 12.0f;",
      "float StartOfRaceGracePeriod = 10.0f;", rel=RCC),
    M("gr-between", "float TimeBetweenCarsForGracePeriodExit = 0.5f;",
      "float TimeBetweenCarsForGracePeriodExit = 0.25f;", rel=RCC),
    M("gr-lo", "if ((uint32_t)(car->DriverNumber - 101) < 49u)",
      "if ((uint32_t)(car->DriverNumber - 102) < 48u)", rel=RCC),
    M("gr-hi", "if ((uint32_t)(car->DriverNumber - 101) < 49u)",
      "if ((uint32_t)(car->DriverNumber - 101) < 50u)", rel=RCC),
    M("gr-signed", "if ((uint32_t)(car->DriverNumber - 101) < 49u)",
      "if (car->DriverNumber - 101 < 49)", rel=RCC),
    M("gr-order", "grace = grace + (float)(100 - car->DriverNumber)",
      "grace = grace + (float)(car->DriverNumber - 100)", rel=RCC),
    M("gr-ticks", "               * 0.000250000012f",
      "               * 0.000500000024f", rel=RCC),
    M("gr-started",
      "((uint32_t)WorldTimer - r->StartTime.PackedTime)",
      "((uint32_t)WorldTimer)", rel=RCC),
    M("gr-test", "           <= grace;", "           >= grace;", rel=RCC),
    # -- ReduceCurrentL ------------------------------------------------
    M("rl-right", "        *l = *l + amount;", "        *l = *l - amount;"),
    M("rl-left", "        *l = *l - amount;", "        *l = *l + amount;"),
    M("rl-right-type",
      "    if (m == MOVEMENT_TOWARDS_RIGHT_SIDE_OF_TRACK) {",
      "    if (m == MOVEMENT_TOWARDS_LINE) {"),
    M("rl-left-type",
      "} else if (m == MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) {",
      "} else if (m == MOVEMENT_PARALLEL_TO_LINE) {"),
    M("rl-neg-add", "*l = amount < -cur ? cur + amount : 0.0f;",
      "*l = amount < -cur ? cur - amount : 0.0f;"),
    M("rl-neg-test", "*l = amount < -cur ? cur + amount : 0.0f;",
      "*l = amount < cur ? cur + amount : 0.0f;"),
    M("rl-neg-zero", "*l = amount < -cur ? cur + amount : 0.0f;",
      "*l = amount < -cur ? cur + amount : cur;"),
    M("rl-pos-sub", "*l = amount < cur ? cur - amount : 0.0f;",
      "*l = amount < cur ? cur + amount : 0.0f;"),
    M("rl-pos-zero", "*l = amount < cur ? cur - amount : 0.0f;",
      "*l = amount < cur ? cur - amount : cur;"),
    M("rl-sign", "        if (cur < 0.0f)", "        if (cur > 0.0f)"),
    M("rl-off", "    off = trpoint_get_driving_line_offset(point, line);",
      "    off = 0.0f;"),
    M("rl-inside", "    if (inside) {\n        hi = (point->",
      "    if (!inside) {\n        hi = (point->"),
    M("rl-hi-half", "hi = (point->RightWidth - DC_EDGE) - halfWidth;",
      "hi = (point->RightWidth - DC_EDGE) + halfWidth;"),
    M("rl-lo-half", "lo = (DC_EDGE - point->LeftWidth) + halfWidth;",
      "lo = (DC_EDGE - point->LeftWidth) - halfWidth;"),
    M("rl-hi-edge", "hi = (point->RightWidth - DC_EDGE) - halfWidth;",
      "hi = point->RightWidth - halfWidth;"),
    M("rl-lo-edge", "lo = (DC_EDGE - point->LeftWidth) + halfWidth;",
      "lo = -point->LeftWidth + halfWidth;"),
    M("rl-hi", "        hi = point->RightWidth;", "        hi = point->LeftWidth;"),
    M("rl-lo", "        lo = -point->LeftWidth;", "        lo = -point->RightWidth;"),
    M("rl-clamp-hi", "*l = min_s(hi - off, max_s(*l, lo - off));",
      "*l = max_s(*l, lo - off);"),
    M("rl-clamp-lo", "*l = min_s(hi - off, max_s(*l, lo - off));",
      "*l = min_s(hi - off, *l);"),
    M("rl-clamp-off", "*l = min_s(hi - off, max_s(*l, lo - off));",
      "*l = min_s(hi, max_s(*l, lo));"),
    M("rl-clamp-order", "*l = min_s(hi - off, max_s(*l, lo - off));",
      "*l = max_s(lo - off, min_s(*l, hi - off));"),
    # -- AddToDriveTarget ----------------------------------------------
    M("at-point", "                                           p->nPointNumber);\n"
      "    bVector3 pos;",
      "                                           p->nPointNumber + 1);\n"
      "    bVector3 pos;"),
    M("at-ahead", "    trpoint_get_position3(pt, &pos, 0.0f,",
      "    trpoint_get_position3(pt, &pos, 1.0f,"),
    M("at-l", "l + trpoint_get_driving_line_offset(pt, p->nLine));",
      "trpoint_get_driving_line_offset(pt, p->nLine));"),
    M("at-line", "l + trpoint_get_driving_line_offset(pt, p->nLine));",
      "l + trpoint_get_driving_line_offset(pt, 0));"),
    M("at-rn", "drivetarget_add_point3(t, &pos, (int8_t)p->nRouteNumber,",
      "drivetarget_add_point3(t, &pos, (int8_t)(p->nRouteNumber + 1),"),
    M("at-pn", "(int16_t)p->nPointNumber, (int8_t)p->nLine, 1,",
      "(int16_t)(p->nPointNumber + 1), (int8_t)p->nLine, 1,"),
    M("at-dl", "(int16_t)p->nPointNumber, (int8_t)p->nLine, 1,",
      "(int16_t)p->nPointNumber, (int8_t)(p->nLine + 1), 1,"),
    M("at-check", "(int16_t)p->nPointNumber, (int8_t)p->nLine, 1,",
      "(int16_t)p->nPointNumber, (int8_t)p->nLine, 0,"),
    # -- FillUpDriveTarget ---------------------------------------------
    M("fu-null-loc", "    if (loc == NULL || t == NULL || list == NULL)",
      "    if (t == NULL || list == NULL)"),
    M("fu-null-target", "    if (loc == NULL || t == NULL || list == NULL)",
      "    if (loc == NULL || list == NULL)"),
    M("fu-null-list", "    if (loc == NULL || t == NULL || list == NULL)",
      "    if (loc == NULL || t == NULL)"),
    M("fu-clear",
      "    if (drivinglocation_is_clear(loc))\n        return;\n    // The terrain",
      "    if (0)\n        return;\n    // The terrain"),
    M("fu-ttype", "t->TType = (int32_t)trpoint_terrain_type(loc->pRoutePoint);",
      "t->TType = 0;"),
    M("fu-ttype-late",
      "    t->TType = (int32_t)trpoint_terrain_type(loc->pRoutePoint);\n"
      "    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS))\n        return;",
      "    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS))\n        return;\n"
      "    t->TType = (int32_t)trpoint_terrain_type(loc->pRoutePoint);"),
    M("fu-full", "loc->pRoutePoint);\n    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS))",
      "loc->pRoutePoint);\n    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS - 1))"),
    M("fu-speed-m", "speed = drivingchoice_get_speed_back_to_line(list, loc, m);",
      "speed = drivingchoice_get_speed_back_to_line(list, loc,\n"
      "                                                 MOVEMENT_TOWARDS_LINE);"),
    M("fu-crossed-m",
      "if (m == MOVEMENT_TOWARDS_LINE && fp->bCrossedSignpost)",
      "if (fp->bCrossedSignpost)"),
    M("fu-crossed-only",
      "if (m == MOVEMENT_TOWARDS_LINE && fp->bCrossedSignpost)",
      "if (m == MOVEMENT_TOWARDS_LINE)"),
    M("fu-crossed-min", "speed = min_s(speed, DC_SPEED_SLOW_BACK);",
      "speed = DC_SPEED_SLOW_BACK;"),
    M("fu-reduce-line",
      "drivingchoice_reduce_current_l(&l, m, pt, loc->DrivingLine, speed,",
      "drivingchoice_reduce_current_l(&l, m, pt, fp->nLine, speed,"),
    M("fu-reduce-half", "                                       list->MyHalfSizeL, inside);",
      "                                       0.0f, inside);"),
    M("fu-reduce-inside", "                                       list->MyHalfSizeL, inside);",
      "                                       list->MyHalfSizeL, !inside);"),
    M("fu-offset", "        l = l + fp->fOffset;", "        l = l - fp->fOffset;"),
    M("fu-tuning-m",
      "if (WilliamsAITuningMode != 0 && m == MOVEMENT_TOWARDS_LINE)",
      "if (WilliamsAITuningMode != 0)"),
    M("fu-tuning-off",
      "if (WilliamsAITuningMode != 0 && m == MOVEMENT_TOWARDS_LINE)",
      "if (m == MOVEMENT_TOWARDS_LINE)"),
    M("fu-add-l",
      "drivingchoice_add_to_drive_target(ls[i], loc, &fl.Points[i], t);",
      "drivingchoice_add_to_drive_target(ls[0], loc, &fl.Points[i], t);"),
    M("fu-no-fixup",
      "    drivingchoice_fixup_car_to_exclude_from_collision_prediction(\n"
      "        &dc, list->MyCar, 0, list);",
      ""),
    M("fu-no-choice", "    drivingchoice_set_choice_location(&dc, loc);\n", ""),
    # -- 11b-3's literals and globals ----------------------------------
    M("k-extra-lateral", "#define DC_EXTRA_LATERAL     4.0f",
      "#define DC_EXTRA_LATERAL     3.0f"),
    M("k-far-off-road", "#define DC_FAR_OFF_ROAD      5.0f",
      "#define DC_FAR_OFF_ROAD      4.0f"),
    M("k-parallel-speed", "#define DC_PARALLEL_SPEED    5.0f",
      "#define DC_PARALLEL_SPEED    6.0f"),
    M("k-parallel-wheels", "#define DC_PARALLEL_WHEELS   3",
      "#define DC_PARALLEL_WHEELS   4"),
    M("k-parallel-wheels-lo", "#define DC_PARALLEL_WHEELS   3",
      "#define DC_PARALLEL_WHEELS   2"),
    M("k-same-heading", "#define DC_SAME_HEADING      0.707099974f",
      "#define DC_SAME_HEADING      0.75f"),
    M("k-no-edge", "#define DC_NO_EDGE           999999.0f",
      "#define DC_NO_EDGE           5.0f"),
    M("k-far-away", "#define DC_FAR_AWAY          1.0e14f",
      "#define DC_FAR_AWAY          10.0f"),
    M("k-search-step", "#define DC_SEARCH_STEP       0.0416666679f",
      "#define DC_SEARCH_STEP       0.0833333358f"),
    M("k-gap", "#define DC_GAP               2.0f",
      "#define DC_GAP               2.5f"),
    M("k-gap-player", "#define DC_GAP_PLAYER        1.5f",
      "#define DC_GAP_PLAYER        1.0f"),
    M("k-gap-slow", "#define DC_GAP_SLOW          6.0f",
      "#define DC_GAP_SLOW          5.0f"),
    M("g-traffic", "int32_t AITrafficTuningMode;",
      "int32_t AITrafficTuningMode = 1;"),
    M("g-slow-car", "float   AISlowCarSpeed = 20.0f;",
      "float   AISlowCarSpeed = 21.0f;"),
    M("g-slow-traffic", "float   AISlowTrafficSpeed = 10.0f;",
      "float   AISlowTrafficSpeed = 11.0f;"),
    M("oob-right", "        return l - p->RightWidth;",
      "        return l - p->LeftWidth;"),
    M("oob-left", "    return -(l + p->LeftWidth);",
      "    return -(l + p->RightWidth);"),
    # -- the closest point ahead ---------------------------------------
    M("se-start", "    int32_t i = start < 0 ? 0 : start;",
      "    int32_t i = start < 0 ? 1 : start;"),
    M("se-best", "    int32_t best = -1;\n    float bestDist",
      "    int32_t best = 0;\n    float bestDist"),
    M("se-dy", "        float dy = p->Position.y - pos->y;",
      "        float dy = p->Position.y - pos->x;"),
    M("se-ahead-sign", "        float ahead = -((pos->x - p->Position.x)",
      "        float ahead = ((pos->x - p->Position.x)"),
    M("se-ahead-dir", "                        + (pos->y - p->Position.y) * p->Direction.y);",
      "                        + (pos->y - p->Position.y) * p->Direction.x);"),
    M("se-ahead-strict", "        if (0.0f < ahead && d < bestDist) {",
      "        if (0.0f <= ahead && d < bestDist) {"),
    M("se-ahead-off", "        if (0.0f < ahead && d < bestDist) {",
      "        if (d < bestDist) {"),
    M("se-tie", "        if (0.0f < ahead && d < bestDist) {",
      "        if (0.0f < ahead && d <= bestDist) {"),
    M("se-skip-two", "        skip = ee_trunc_w(d * DC_SEARCH_STEP) - 2;",
      "        skip = ee_trunc_w(d * DC_SEARCH_STEP) - 1;"),
    M("se-skip-off", "        skip = ee_trunc_w(d * DC_SEARCH_STEP) - 2;",
      "        skip = 0;"),
    M("se-skip-floor", "(uint32_t)(0 < skip ? skip : 0) + 1u);",
      "(uint32_t)(0 < skip ? skip : 1) + 1u);"),
    # -- the smooth way out --------------------------------------------
    M("sm-last", "    int32_t last = index - 2, i;",
      "    int32_t last = index - 1, i;"),
    M("sm-guard", "    if (last + 1 < 2)\n        return;",
      "    if (last + 1 < 3)\n        return;"),
    M("sm-a-line", "                                                          l->Points[0].nLine));",
      "                                                          0));"),
    M("sm-b-point", "    pe = fp_point(&l->Points[last]);",
      "    pe = fp_point(&l->Points[last - 1]);"),
    M("sm-slope", "    slope = ee_div(toL - fromL,", "    slope = ee_div(fromL - toL,"),
    M("sm-ieee-div", "    slope = ee_div(toL - fromL,\n                   sqrtf(",
      "    slope = (toL - fromL) / (\n                   sqrtf("),
    M("sm-full", "    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS))\n        return;\n\n    i = 0;",
      "    i = 0;"),
    M("sm-from", "        cur = fromL + sqrtf((a.x - c.x) * (a.x - c.x)",
      "        cur = sqrtf((a.x - c.x) * (a.x - c.x)"),
    M("sm-cap-up", "            if (toL < cur)\n                cur = toL;",
      "            if (0)\n                cur = toL;"),
    M("sm-cap-down", "            if (cur < toL)\n                cur = toL;",
      "            if (0)\n                cur = toL;"),
    M("sm-line-off", "        cur = (cur + trpoint_get_driving_line_offset(p, fp->nLine))",
      "        cur = (cur)"),
    M("sm-offset", "              + fp->fOffset;\n        if (inside) {",
      "              - fp->fOffset;\n        if (inside) {"),
    M("sm-inside", "        if (inside) {", "        if (!inside) {"),
    M("sm-inside-lo", "            lo = (DC_EDGE - p->LeftWidth) + list->MyHalfSizeL;",
      "            lo = (DC_EDGE - p->LeftWidth);"),
    M("sm-inside-hi", "            hi = (p->RightWidth - DC_EDGE) - list->MyHalfSizeL;",
      "            hi = p->RightWidth - list->MyHalfSizeL;"),
    M("sm-outside-lo",
      "            lo = -p->LeftWidth;\n            hi = p->RightWidth;\n        }\n        // STACK-W, as",
      "            lo = -p->RightWidth;\n            hi = p->RightWidth;\n        }\n        // STACK-W, as"),
    M("sm-outside-hi",
      "            lo = -p->LeftWidth;\n            hi = p->RightWidth;\n        }\n        // STACK-W, as",
      "            lo = -p->LeftWidth;\n            hi = p->LeftWidth;\n        }\n        // STACK-W, as"),
    M("sm-clamp", "min_s(hi, max_s(cur, lo))", "cur"),
    M("sm-rn", "drivetarget_add_point3(t, &pos, (int8_t)fp->nRouteNumber,",
      "drivetarget_add_point3(t, &pos, (int8_t)(fp->nRouteNumber + 1),"),
    M("sm-pn", "(int16_t)fp->nPointNumber, (int8_t)fp->nLine,",
      "(int16_t)(fp->nPointNumber + 1), (int8_t)fp->nLine,"),
    M("sm-dl", "(int16_t)fp->nPointNumber, (int8_t)fp->nLine,",
      "(int16_t)fp->nPointNumber, (int8_t)(fp->nLine + 1),"),
    M("sm-check", "                               1, NULL);\n        i++;",
      "                               0, NULL);\n        i++;"),
    M("sm-end", "    } while (!(last < i) && t->NumPoints",
      "    } while (!(last <= i) && t->NumPoints"),
    # -- the clearance -------------------------------------------------
    M("cl-null", "    if (nc == NULL)\n        return 0.0f;",
      "    if (nc == NULL)\n        return 1.0f;"),
    M("cl-search", "        if (index == -1)\n            index = futurepointlist",
      "        if (index == -2)\n            index = futurepointlist"),
    M("cl-search-car", "                l, (const bVector2 *)&other->State.Position, 0);",
      "                l, (const bVector2 *)&me->State.Position, 0);"),
    M("cl-mine-line", "                    - trpoint_get_driving_line_offset(p0, f0->nLine))",
      "                    + trpoint_get_driving_line_offset(p0, f0->nLine))"),
    M("cl-mine-off", "                   + f0->fOffset;", "                   - f0->fOffset;"),
    M("cl-its-line", "                   - trpoint_get_driving_line_offset(pi, fi->nLine))",
      "                   - trpoint_get_driving_line_offset(pi, f0->nLine))"),
    M("cl-its-off", "                  + fi->fOffset;", "                  - fi->fOffset;"),
    M("cl-abs", "            gap = (fabsf(mine - its) - list->MyHalfSizeL)",
      "            gap = ((mine - its) - list->MyHalfSizeL)"),
    M("cl-my-half", "            gap = (fabsf(mine - its) - list->MyHalfSizeL)",
      "            gap = (fabsf(mine - its))"),
    M("cl-its-half", "                  - nc->ApparentHalfSizeL;\n        }",
      "                  - nc->ApparentHalfSizeD;\n        }"),
    M("cl-v-abs", "    v = fabsf(other->State.VelocityMagnitude);",
      "    v = other->State.VelocityMagnitude;"),
    M("cl-v-mine", "    v = fabsf(other->State.VelocityMagnitude);",
      "    v = fabsf(me->State.VelocityMagnitude);"),
    M("cl-me-traffic", "    if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)\n        least = DC_GAP;",
      "    if (0)\n        least = DC_GAP;"),
    M("cl-other-traffic", "    else if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR",
      "    else if (other->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR"),
    M("cl-le-traffic", "? v <= AISlowTrafficSpeed : v <= AISlowCarSpeed)",
      "? v < AISlowTrafficSpeed : v <= AISlowCarSpeed)"),
    M("cl-le-car", "? v <= AISlowTrafficSpeed : v <= AISlowCarSpeed)",
      "? v <= AISlowTrafficSpeed : v < AISlowCarSpeed)"),
    M("cl-player", "        least = other->pPlayer != NULL ? DC_GAP_PLAYER : DC_GAP;",
      "        least = DC_GAP;"),
    M("cl-max-gap", "    return max_s(gap, least);", "    return gap;"),
    M("cl-max-least", "    return max_s(gap, least);", "    return least;"),
    # -- alongside another car's target --------------------------------
    M("mp-other-speed", "    if (!(DC_PARALLEL_SPEED < other->State.VelocityMagnitude))",
      "    if (!(DC_PARALLEL_SPEED <= other->State.VelocityMagnitude))"),
    M("mp-other-speed-off", "    if (!(DC_PARALLEL_SPEED < other->State.VelocityMagnitude))\n        return;",
      "    if (0)\n        return;"),
    M("mp-me-speed", "    if (!(DC_PARALLEL_SPEED < me->State.VelocityMagnitude))",
      "    if (!(DC_PARALLEL_SPEED <= me->State.VelocityMagnitude))"),
    M("mp-me-speed-off", "    if (!(DC_PARALLEL_SPEED < me->State.VelocityMagnitude))\n        return;",
      "    if (0)\n        return;"),
    M("mp-wheels", "    if (other->State.nWheelsTouchingGround < DC_PARALLEL_WHEELS)",
      "    if (other->State.nWheelsTouchingGround <= DC_PARALLEL_WHEELS)"),
    M("mp-heading", "    if (!(DC_SAME_HEADING < mine.x * theirs.x + mine.y * theirs.y))",
      "    if (!(0.0f < mine.x * theirs.x + mine.y * theirs.y))"),
    M("mp-heading-y", "    if (!(DC_SAME_HEADING < mine.x * theirs.x + mine.y * theirs.y))",
      "    if (!(DC_SAME_HEADING < mine.x * theirs.x + mine.x * theirs.y))"),
    M("mp-theirs", "    bNormalize2(&theirs, (const bVector2 *)&other->State.Velocity);",
      "    bNormalize2(&theirs, (const bVector2 *)&other->State.BodyMatrix.v0);"),
    M("mp-first", "    j = drivetarget_get_first_point(its, &other->State);",
      "    j = 0;"),
    M("mp-first-mine", "    j = drivetarget_get_first_point(its, &other->State);",
      "    j = drivetarget_get_first_point(its, &me->State);"),
    M("mp-want-side", "        float want = lateral(p, q->x, q->y) + side;",
      "        float want = lateral(p, q->x, q->y) - side;"),
    M("mp-want-q", "        float want = lateral(p, q->x, q->y) + side;",
      "        float want = side;"),
    M("mp-type", "        if (r->Type != TRACK_ROUTE_TRAFFIC) {",
      "        if (r->Type == TRACK_ROUTE_TRAFFIC) {"),
    M("mp-racing-lo",
      "            lo = -p->LeftWidth;\n            hi = p->RightWidth;\n        } else {",
      "            lo = -p->RightWidth;\n            hi = p->RightWidth;\n        } else {"),
    M("mp-racing-hi",
      "            lo = -p->LeftWidth;\n            hi = p->RightWidth;\n        } else {",
      "            lo = -p->LeftWidth;\n            hi = p->LeftWidth;\n        } else {"),
    M("mp-from", "                l, (const bVector2 *)&p->Position, from);",
      "                l, (const bVector2 *)&p->Position, 0);"),
    M("mp-from-none", "            if (from != -1) {", "            if (0) {"),
    M("mp-edge-l", "trpoint_get_position2(e, &le, 0.0f, -e->LeftWidth);",
      "trpoint_get_position2(e, &le, 0.0f, e->LeftWidth);"),
    M("mp-edge-r", "trpoint_get_position2(e, &re, 0.0f, e->RightWidth);",
      "trpoint_get_position2(e, &re, 0.0f, -e->RightWidth);"),
    M("mp-order", "                if (ll < rl) {", "                if (rl < ll) {"),
    M("mp-margin", "        m = list->MyHalfSizeL + DC_EDGE;", "        m = DC_EDGE;"),
    M("mp-lo", "        lo = lo + m;", "        lo = lo - m;"),
    M("mp-hi", "        hi = hi - m;", "        hi = hi + m;"),
    M("mp-clamp", "min_s(hi, max_s(want, lo))", "want"),
    M("mp-rn", "        drivetarget_add_point3(t, &pos, its->Route[j],",
      "        drivetarget_add_point3(t, &pos, its->Route[0],"),
    M("mp-pn", "                               its->RoutePointNumber[j], its->DrivingLine[j],",
      "                               its->RoutePointNumber[0], its->DrivingLine[j],"),
    M("mp-dl", "                               its->RoutePointNumber[j], its->DrivingLine[j],",
      "                               its->RoutePointNumber[j], its->DrivingLine[0],"),
    M("mp-car", "                               1, me);", "                               1, NULL);"),
    M("mp-check", "                               1, me);", "                               0, me);"),
    # -- round a car ---------------------------------------------------
    M("ar-search-car", "                &fl, (const bVector2 *)&nc->TheCar->State.Position, 0))",
      "                &fl, (const bVector2 *)&list->MyCar->State.Position, 0))"),
    M("ar-extra", "        if (d->UseExtraLateralDistance)", "        if (!d->UseExtraLateralDistance)"),
    M("ar-oob", "        if (amount_out_of_bounds(p, lat) < DC_FAR_OFF_ROAD) {",
      "        if (amount_out_of_bounds(p, lat) < 1000.0f) {"),
    M("ar-lat", "        lat = lateral(p, other->State.Position.x, other->State.Position.y);",
      "        lat = lateral(p, other->State.Position.y, other->State.Position.x);"),
    M("ar-side", "            side = d->Type == CHOICE_LEFT_SIDE_OF_CAR ? -1.0f : 1.0f;",
      "            side = d->Type == CHOICE_LEFT_SIDE_OF_CAR ? 1.0f : -1.0f;"),
    M("ar-traffic-me", "            if (list->MyCar->MyDriver->TheDriverType\n                    == DRIVER_TYPE_TRAFFIC_CAR\n                && AITrafficTuningMode != 0)",
      "            if (AITrafficTuningMode != 0)"),
    M("ar-traffic-mode", "            if (list->MyCar->MyDriver->TheDriverType\n                    == DRIVER_TYPE_TRAFFIC_CAR\n                && AITrafficTuningMode != 0)",
      "            if (list->MyCar->MyDriver->TheDriverType\n                    == DRIVER_TYPE_TRAFFIC_CAR)"),
    M("ar-room-half", "            room = side * ((list->MyHalfSizeL + nc->ApparentHalfSizeL)",
      "            room = side * ((list->MyHalfSizeL)"),
    M("ar-room-clear", "                           + clearance);", "                           );"),
    M("ar-along", "            along = (other->State.Position.x - p->Position.x)",
      "            along = (list->MyCar->State.Position.x - p->Position.x)"),
    M("ar-pass-hi", "            passL = min_s((p->RightWidth - DC_EDGE) - list->MyHalfSizeL,",
      "            passL = min_s(p->RightWidth,"),
    M("ar-pass-lo", "                                list->MyHalfSizeL\n                                    - (p->LeftWidth - DC_EDGE)));",
      "                                -p->LeftWidth));"),
    M("ar-pass-offset", "                          max_s((lat + room) + fp->fOffset,",
      "                          max_s((lat + room),"),
    M("ar-pass-room", "                          max_s((lat + room) + fp->fOffset,",
      "                          max_s((lat - room) + fp->fOffset,"),
    M("ar-pos-along", "            trpoint_get_position3(p, &pos, along, passL);",
      "            trpoint_get_position3(p, &pos, 0.0f, passL);"),
    M("ar-from", "                &fl, t, list, idx, currentL,",
      "                &fl, t, list, idx, 0.0f,"),
    M("ar-to", "                passL - trpoint_get_driving_line_offset(p, line), 1);",
      "                passL, 1);"),
    M("ar-inside", "                passL - trpoint_get_driving_line_offset(p, line), 1);",
      "                passL - trpoint_get_driving_line_offset(p, line), 0);"),
    M("ar-no-smooth", "            drivingchoice_do_smooth_offset_change(\n"
      "                &fl, t, list, idx, currentL,\n"
      "                passL - trpoint_get_driving_line_offset(p, line), 1);\n", ""),
    M("ar-add-rn", "            drivetarget_add_point3(t, &pos, (int8_t)r->RouteNumber,",
      "            drivetarget_add_point3(t, &pos, (int8_t)(r->RouteNumber + 1),"),
    M("ar-add-pn", "                                   (int16_t)troute_get_point_number(r, p),",
      "                                   (int16_t)(troute_get_point_number(r, p) + 1),"),
    M("ar-add-line", "                                   (int8_t)line, 1, NULL);",
      "                                   (int8_t)(line + 1), 1, NULL);"),
    M("ar-add-check", "                                   (int8_t)line, 1, NULL);",
      "                                   (int8_t)line, 0, NULL);"),
    M("ar-last", "            t->LastPointToScore = (int8_t)(t->NumPoints - 1);",
      "            t->LastPointToScore = (int8_t)t->NumPoints;"),
    M("ar-player", "            if (it->pPlayer != NULL", "            if (it->pPlayer == NULL"),
    M("ar-cop", "                    ? its != DRIVER_TYPE_COP", "                    ? 1"),
    M("ar-its-traffic", "                    : its == DRIVER_TYPE_TRAFFIC_CAR\n                          && list",
      "                    : 1\n                          && list"),
    M("ar-me-traffic", "                          && list->MyCar->MyDriver->TheDriverType\n                                 != DRIVER_TYPE_TRAFFIC_CAR)",
      "                          && 1)"),
    M("ar-parallel-room", "                                                                &fl, room);",
      "                                                                &fl, -room);"),
    M("ar-fill-m", "                                               MOVEMENT_PARALLEL_TO_LINE, 1);\n            done = 1;",
      "                                               MOVEMENT_TOWARDS_LINE, 1);\n            done = 1;"),
    M("ar-fill-inside", "                                               MOVEMENT_PARALLEL_TO_LINE, 1);\n            done = 1;",
      "                                               MOVEMENT_PARALLEL_TO_LINE, 0);\n            done = 1;"),
    M("ar-done", "MOVEMENT_PARALLEL_TO_LINE, 1);\n            done = 1;",
      "MOVEMENT_PARALLEL_TO_LINE, 1);\n            done = 0;"),
    M("ar-fail-m", "    if (!done)\n        drivingchoice_fill_up_drive_target(t, loc, list,\n"
      "                                           MOVEMENT_PARALLEL_TO_LINE, 1);",
      "    if (!done)\n        drivingchoice_fill_up_drive_target(t, loc, list,\n"
      "                                           MOVEMENT_TOWARDS_LINE, 1);"),
    M("ar-fail-inside", "    if (!done)\n        drivingchoice_fill_up_drive_target(t, loc, list,\n"
      "                                           MOVEMENT_PARALLEL_TO_LINE, 1);",
      "    if (!done)\n        drivingchoice_fill_up_drive_target(t, loc, list,\n"
      "                                           MOVEMENT_PARALLEL_TO_LINE, 0);"),
    # -- BuildDriveTarget ----------------------------------------------
    M("bd-assign", "    drivetarget_assign(t, &list->MyCar->pCarDriver->MyDriveTarget);\n", ""),
    M("bd-clear", "    drivetarget_clear(t, list->MyCar, 0.0f);\n", ""),
    M("bd-valid", "    if (!drivingchoice_is_valid(d, loc, list)) {", "    if (0) {"),
    M("bd-invalid-m", "        drivingchoice_fill_up_drive_target(t, loc, list, m, 1);",
      "        drivingchoice_fill_up_drive_target(t, loc, list,\n"
      "                                           MOVEMENT_PARALLEL_TO_LINE, 1);"),
    M("bd-invalid-inside", "        drivingchoice_fill_up_drive_target(t, loc, list, m, 1);",
      "        drivingchoice_fill_up_drive_target(t, loc, list, m, 0);"),
    M("bd-line-loc", "        drivingchoice_fill_up_drive_target(t, &onLine, list, m, 1);",
      "        drivingchoice_fill_up_drive_target(t, loc, list, m, 1);"),
    M("bd-line-inside", "        drivingchoice_fill_up_drive_target(t, &onLine, list, m, 1);",
      "        drivingchoice_fill_up_drive_target(t, &onLine, list, m, 0);"),
    M("bd-line-which", "            &onLine, drivingchoice_get_driving_line(d->Type, list->MyCar), 0);",
      "            &onLine, loc->DrivingLine, 0);"),
    M("bd-line-built", "        built = 1;\n    } else {", "        built = 0;\n    } else {"),
    M("bd-around-built", "        built = drivingchoice_build_drive_target_around_car(d, t, list, 0.0f,",
      "        drivingchoice_build_drive_target_around_car(d, t, list, 0.0f,"),
    M("bd-fixup", "    drivingchoice_fixup_car_to_exclude_from_collision_prediction(\n"
      "        d, list->MyCar, 0, list);\n    return built;", "    return built;"),
    M("bd-fixup-check", "        d, list->MyCar, 0, list);\n    return built;",
      "        d, list->MyCar, 1, list);\n    return built;"),
    # -- CarCollisionPredict (11b-4a): the constants -------------------
    M("ck-no-hit", "#define CCP_NO_HIT          99999.0f",
      "#define CCP_NO_HIT          9999.0f", rel=CCP),
    M("ck-still", "#define CCP_STILL           0.00100000005f",
      "#define CCP_STILL           0.5f", rel=CCP),
    M("ck-traffic-scale", "#define CCP_TRAFFIC_SCALE   1.29999995f",
      "#define CCP_TRAFFIC_SCALE   1.5f", rel=CCP),
    M("ck-backing-scale", "#define CCP_BACKING_SCALE   1.29999995f",
      "#define CCP_BACKING_SCALE   1.5f", rel=CCP),
    M("ck-leg-done", "#define CCP_LEG_DONE        0.00100000005f",
      "#define CCP_LEG_DONE        0.100000001f", rel=CCP),
    M("ck-same", "#define CCP_SAME            0.00100000005f",
      "#define CCP_SAME            99990.0f", rel=CCP),
    M("ck-axis-still", "#define CCP_AXIS_STILL      9.99999975e-05f",
      "#define CCP_AXIS_STILL      0.100000001f", rel=CCP),
    M("ck-never", "#define CCP_NEVER           9999.0f",
      "#define CCP_NEVER           999.0f", rel=CCP),
    M("ck-always", "#define CCP_ALWAYS         -9999.0f",
      "#define CCP_ALWAYS         -999.0f", rel=CCP),
    M("ck-no-overlap", "#define CCP_NO_OVERLAP      99999.0f",
      "#define CCP_NO_OVERLAP      9999.0f", rel=CCP),
    M("ck-stopped-speed", "#define CCP_STOPPED_SPEED   5.0f",
      "#define CCP_STOPPED_SPEED   4.0f", rel=CCP),
    M("ck-stopped-ahead", "#define CCP_STOPPED_AHEAD   23.0f",
      "#define CCP_STOPPED_AHEAD   20.0f", rel=CCP),
    M("ck-on-road", "#define CCP_ON_ROAD        -0.25f",
      "#define CCP_ON_ROAD        0.0f", rel=CCP),
    M("ck-slow", "#define CCP_SLOW            2.0f",
      "#define CCP_SLOW            3.0f", rel=CCP),
    M("ck-tuning", "#define CCP_TUNING_SCALE    1000.0f",
      "#define CCP_TUNING_SCALE    100.0f", rel=CCP),
    M("ck-max-s", "return fs < ft ? ft : fs;", "return fs < ft ? fs : ft;",
      rel=CCP),
    M("ck-no-action", "return a == NULL ? AIACTION_NONE : a->Type;",
      "return a == NULL ? AIACTION_JUST_DRIVE : a->Type;", rel=CCP),
    M("ck-blind-unstuck",
      "return type == AIACTION_GET_UNSTUCK || type == AIACTION_NONE",
      "return type == AIACTION_NONE", rel=CCP),
    M("ck-blind-none",
      "return type == AIACTION_GET_UNSTUCK || type == AIACTION_NONE",
      "return type == AIACTION_GET_UNSTUCK", rel=CCP),
    M("ck-blind-accident",
      "|| type == AIACTION_ACCIDENT_RECOVERY || t->NumPoints == 0;",
      "|| t->NumPoints == 0;", rel=CCP),
    M("ck-blind-empty",
      "|| type == AIACTION_ACCIDENT_RECOVERY || t->NumPoints == 0;",
      "|| type == AIACTION_ACCIDENT_RECOVERY;", rel=CCP),
    # -- WhoWillThisDriveTargetHit ---------------------------------------
    M("cw-clear", "if (loc == NULL || drivinglocation_is_clear(loc))",
      "if (loc == NULL)", rel=CCP),
    M("cw-np-lo", "if (t->NumPoints <= 0 ||", "if (t->NumPoints < 0 ||",
      rel=CCP),
    M("cw-np-hi", "!(t->NumPoints < CCP_MAX_POINTS + 1))",
      "!(t->NumPoints < CCP_MAX_POINTS))", rel=CCP),
    M("cw-care", "if (!ai_do_we_care_about_this_car(nc, list))\n"
      "            continue;", "", rel=CCP),
    M("cw-stopped-its", "its = 0.0f;\n            r = 1;",
      "its = 1.0f;\n            r = 1;", rel=CCP),
    M("cw-stopped-r", "its = 0.0f;\n            r = 1;",
      "its = 0.0f;\n            r = 0;", rel=CCP),
    M("cw-still-fabs",
      "fabsf(list->MyCar->State.VelocityMagnitude) <= CCP_STILL",
      "list->MyCar->State.VelocityMagnitude <= CCP_STILL", rel=CCP),
    M("cw-still", "fabsf(list->MyCar->State.VelocityMagnitude) <= CCP_STILL",
      "fabsf(list->MyCar->State.VelocityMagnitude) <= CCP_SLOW", rel=CCP),
    M("cw-exclude", "                   || nc->TheCar == exclude) {",
      "                   ) {", rel=CCP),
    M("cw-cars", "r = ccp_will_i_hit_this_car(t, loc, list->MyCar, nc->TheCar,",
      "r = ccp_will_i_hit_this_car(t, loc, nc->TheCar, list->MyCar,",
      rel=CCP),
    M("cw-max-time", "maxTime, &its);", "maxTime + 1.0f, &its);", rel=CCP),
    M("cw-best", "if (r && its < best) {", "if (r && its <= best) {", rel=CCP),
    M("cw-r", "if (r && its < best) {", "if (its < best) {", rel=CCP),
    M("cw-best-init", "float best = CCP_NO_HIT;", "float best = 50.0f;",
      rel=CCP),
    M("cw-keep", "            best = its;\n", "", rel=CCP),
    M("cw-id", "        pCurrentWorld->CollisionPredictionID++;\n", "",
      rel=CCP),
    M("cw-when", "    *when = best;\n    return hit;", "    return hit;",
      rel=CCP),
    # -- IsThisCarStoppedDirectlyInFrontOfMe -----------------------------
    M("cs-fabs",
      "if (!(fabsf(nc->TheCar->State.VelocityMagnitude) <= CCP_STOPPED_SPEED))",
      "if (!(nc->TheCar->State.VelocityMagnitude <= CCP_STOPPED_SPEED))",
      rel=CCP),
    M("cs-speed", "<= CCP_STOPPED_SPEED))", "< CCP_STOPPED_SPEED))", rel=CCP),
    M("cs-x-fabs", "return fabsf(nc->Position.x) <", "return nc->Position.x <",
      rel=CCP),
    M("cs-x-its", "< list->MyHalfSizeL + nc->ApparentHalfSizeL",
      "< list->MyHalfSizeL", rel=CCP),
    M("cs-x-mine", "< list->MyHalfSizeL + nc->ApparentHalfSizeL",
      "< nc->ApparentHalfSizeL", rel=CCP),
    M("cs-y-its", "(list->MyHalfSizeD + nc->ApparentHalfSizeD)",
      "(list->MyHalfSizeD)", rel=CCP),
    M("cs-y-mine", "(list->MyHalfSizeD + nc->ApparentHalfSizeD)",
      "(nc->ApparentHalfSizeD)", rel=CCP),
    M("cs-y-abs", "&& nc->Position.y <", "&& fabsf(nc->Position.y) <",
      rel=CCP),
    # -- WillIHitThisCar -------------------------------------------------
    M("cl-its-target",
      "drivetarget_copy(&s_its, &other->pCarDriver->MyDriveTarget);",
      "drivetarget_copy(&s_its, t);", rel=CCP),
    M("cl-my-traffic",
      "if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && CCP_ON_ROAD < car_get_amount_out_of_bounds(me))",
      "if (CCP_ON_ROAD < car_get_amount_out_of_bounds(me))", rel=CCP),
    M("cl-my-oob", "&& CCP_ON_ROAD < car_get_amount_out_of_bounds(me))",
      "&& CCP_ON_ROAD <= car_get_amount_out_of_bounds(me))", rel=CCP),
    M("cl-my-fill", "drivetarget_fill_with_current_acceleration(&s_mine, me);",
      "drivetarget_blend_with_current_acceleration(&s_mine, me);", rel=CCP),
    M("cl-my-blend",
      "    else\n        drivetarget_blend_with_current_acceleration(&s_mine, me);",
      "    else\n        ;", rel=CCP),
    M("cl-its-traffic",
      "if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR) {",
      "if (other->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR) {",
      rel=CCP),
    M("cl-its-oob", "if (CCP_ON_ROAD < car_get_amount_out_of_bounds(other))",
      "if (CCP_ON_ROAD <= car_get_amount_out_of_bounds(other))", rel=CCP),
    M("cl-its-fill",
      "drivetarget_fill_with_current_acceleration(&s_its, other);",
      "drivetarget_blend_with_current_acceleration(&s_its, other);",
      rel=CCP),
    M("cl-its-just", "else if (action_type(other) != AIACTION_JUST_DRIVE)",
      "else", rel=CCP),
    M("cl-its-blend",
      "            drivetarget_blend_with_current_acceleration(&s_its, other);",
      "            ;", rel=CCP),
    M("cl-my-scale", "if (me->TheControlMode == TRAFFIC_CONTROL)",
      "if (me->TheControlMode == AI_CONTROL)", rel=CCP),
    M("cl-its-scale", "if (other->TheControlMode == TRAFFIC_CONTROL)\n",
      "if (other->TheControlMode == AI_CONTROL)\n", rel=CCP),
    M("cl-my-speed", "myV0 = mySpeed = me->State.VelocityMagnitude;",
      "myV0 = mySpeed = me->State.ForwardSpeed;", rel=CCP),
    M("cl-its-speed", "itsV0 = itsSpeed = other->State.VelocityMagnitude;",
      "itsV0 = itsSpeed = other->State.ForwardSpeed;", rel=CCP),
    M("cl-my-back",
      "if (me->State.ForwardSpeed < 0.0f && backing_blind(me, &s_mine)) {",
      "if (backing_blind(me, &s_mine)) {", rel=CCP),
    M("cl-my-blind",
      "if (me->State.ForwardSpeed < 0.0f && backing_blind(me, &s_mine)) {",
      "if (me->State.ForwardSpeed < 0.0f) {", rel=CCP),
    M("cl-my-predict", "        ai_straight_line_predict(me, &s_mine);\n", "",
      rel=CCP),
    M("cl-my-fabs", "mySpeed = fabsf(myV0);", "mySpeed = myV0;", rel=CCP),
    M("cl-my-bscale", "myScale = CCP_BACKING_SCALE;", "myScale = 1.0f;",
      rel=CCP),
    M("cl-its-back", "if (other->State.ForwardSpeed < 0.0f\n",
      "if (other->State.ForwardSpeed <= 0.0f\n", rel=CCP),
    M("cl-its-ai", "&& (other->TheControlMode == AI_CONTROL\n",
      "&& (other->TheControlMode == COP_CONTROL\n", rel=CCP),
    M("cl-its-mode",
      "            || other->TheControlMode == TRAFFIC_CONTROL)\n",
      "            || other->TheControlMode == REAL_CONTROL)\n", rel=CCP),
    M("cl-its-blind", "\n        && backing_blind(other, &s_its)) {", ") {",
      rel=CCP),
    M("cl-its-predict", "        ai_straight_line_predict(other, &s_its);\n",
      "", rel=CCP),
    M("cl-its-fabs", "itsSpeed = fabsf(itsV0);", "itsSpeed = itsV0;",
      rel=CCP),
    M("cl-its-bscale", "itsScale = CCP_BACKING_SCALE;", "itsScale = 1.0f;",
      rel=CCP),
    M("cl-my-floor", "    mySpeed = max_s(mySpeed, CCP_STILL);\n", "",
      rel=CCP),
    M("cl-its-floor", "    itsSpeed = max_s(itsSpeed, CCP_STILL);\n", "",
      rel=CCP),
    M("cl-my-slow", "if (mySpeed < CCP_SLOW)\n        myScale = 1.0f;", "",
      rel=CCP),
    M("cl-its-slow", "if (itsSpeed < CCP_SLOW)\n        itsScale = 1.0f;", "",
      rel=CCP),
    M("cl-tuning-type",
      "if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n"
      "        && AITrafficTuningMode != 0)",
      "if (AITrafficTuningMode != 0)", rel=CCP),
    M("cl-tuning-on", "&& AITrafficTuningMode != 0)",
      "&& AITrafficTuningMode == 0)", rel=CCP),
    M("cl-my-first", "i = drivetarget_get_first_point(&s_mine, &me->State);",
      "i = 0;", rel=CCP),
    M("cl-its-first",
      "j = drivetarget_get_first_point(&s_its, &other->State);", "j = 0;",
      rel=CCP),
    M("cl-my-start", "myPos.y = me->State.Position.y;",
      "myPos.y = me->State.Position.x;", rel=CCP),
    M("cl-its-start", "itsPos.x = other->State.Position.x;",
      "itsPos.x = me->State.Position.x;", rel=CCP),
    M("cl-loop-i", "while (i < s_mine.NumPoints && j < s_its.NumPoints",
      "while (i < s_mine.NumPoints - 1 && j < s_its.NumPoints", rel=CCP),
    M("cl-loop-j", "&& j < s_its.NumPoints\n",
      "&& j < s_its.NumPoints - 1\n", rel=CCP),
    M("cl-loop-time", "&& elapsed <= maxTime) {", "&& elapsed < maxTime) {",
      rel=CCP),
    M("cl-loop-no-time", "\n           && elapsed <= maxTime) {", ") {",
      rel=CCP),
    M("cl-my-leg", "myLeg.y = myTo->y - myPos.y;",
      "myLeg.y = myTo->y - itsPos.y;", rel=CCP),
    M("cl-its-leg", "itsLeg.x = itsTo->x - itsPos.x;",
      "itsLeg.x = itsTo->x - myPos.x;", rel=CCP),
    M("cl-its-len", "itsLen = sqrtf(itsLeg.x * itsLeg.x + itsLeg.y * itsLeg.y);",
      "itsLen = sqrtf(itsLeg.x * itsLeg.x + itsLeg.x * itsLeg.y);", rel=CCP),
    M("cl-its-time", "itsTime = itsLen / itsSpeed;",
      "itsTime = itsLen / mySpeed;", rel=CCP),
    M("cl-my-time", "myTime = myLen / mySpeed;", "myTime = myLen / itsSpeed;",
      rel=CCP),
    M("cl-step", "step = myTime < itsTime ? myTime : itsTime;",
      "step = myTime < itsTime ? itsTime : myTime;", rel=CCP),
    M("cl-dx", "d.x = itsPos.x - myPos.x;", "d.x = myPos.x - itsPos.x;",
      rel=CCP),
    M("cl-dy", "d.y = itsPos.y - myPos.y;", "d.y = itsPos.y + myPos.y;",
      rel=CCP),
    M("cl-vx", "v.x = itsVel.x - myVel.x;", "v.x = myVel.x - itsVel.x;",
      rel=CCP),
    M("cl-vy", "v.y = itsVel.y - myVel.y;", "v.y = itsVel.y + myVel.y;",
      rel=CCP),
    M("cl-my-vel", "bNormalize2To(&myVel, &myVel, mySpeed);",
      "bNormalize2To(&myVel, &myVel, itsSpeed);", rel=CCP),
    M("cl-its-vel", "bNormalize2To(&itsVel, &itsVel, itsSpeed);",
      "bNormalize2(&itsVel, &itsVel);", rel=CCP),
    M("cl-boxes",
      "at = ccp_when_will_overlap_occur_2d(&s_my_obbs[i], &s_its_obbs[j],",
      "at = ccp_when_will_overlap_occur_2d(&s_my_obbs[i], &s_its_obbs[i],",
      rel=CCP),
    M("cl-at", "if (at <= step) {", "if (at < step) {", rel=CCP),
    M("cl-hit", "hit = elapsed + at;", "hit = at;", rel=CCP),
    M("cl-fm", "fm = ee_div(step * mySpeed, myLen);",
      "fm = ee_div(step * itsSpeed, myLen);", rel=CCP),
    M("cl-fi", "fi = ee_div(step * itsSpeed, itsLen);",
      "fi = ee_div(step * itsSpeed, myLen);", rel=CCP),
    M("cl-fm-ieee", "fm = ee_div(step * mySpeed, myLen);",
      "fm = step * mySpeed / myLen;", rel=CCP),
    M("cl-fi-ieee", "fi = ee_div(step * itsSpeed, itsLen);",
      "fi = step * itsSpeed / itsLen;", rel=CCP),
    M("cl-my-x", "myPos.x = myPos.x + (myTo->x - myPos.x) * fm;",
      "myPos.x = myTo->x;", rel=CCP),
    M("cl-its-y", "itsPos.y = itsPos.y + (itsTo->y - itsPos.y) * fi;",
      "itsPos.y = itsPos.y + (itsTo->y - itsPos.y) * fm;", rel=CCP),
    M("cl-its-x", "itsPos.x = itsPos.x + (itsTo->x - itsPos.x) * fi;",
      "itsPos.x = itsTo->x;", rel=CCP),
    M("cl-my-y", "myPos.y = myPos.y + (myTo->y - myPos.y) * fm;",
      "myPos.y = myPos.y + (myTo->y - myPos.y) * fi;", rel=CCP),
    M("cl-leg-done",
      "if (fabsf(myTime - step) <= CCP_LEG_DONE)\n            i++;\n"
      "        else\n            j++;",
      "if (fabsf(itsTime - step) <= CCP_LEG_DONE)\n            j++;\n"
      "        else\n            i++;", rel=CCP),
    M("cl-both", "            i++;\n        else\n            j++;",
      "            i++;\n        j++;", rel=CCP),
    M("cl-elapsed", "elapsed = elapsed + step;", "elapsed = step;", rel=CCP),
    M("cl-when", "    *when = hit;\n", "", rel=CCP),
    M("cl-r-lt", "r = hit < CCP_NO_HIT && !(", "r = !(", rel=CCP),
    # -- MakeOBBsForDriveTarget ------------------------------------------
    M("co-np", "if (t == NULL || t->NumPoints <= 0 ||",
      "if (t == NULL || t->NumPoints < 0 ||", rel=CCP),
    M("co-obbs", "|| obbs == NULL || car == NULL)", "|| car == NULL)",
      rel=CCP),
    M("co-car", "|| obbs == NULL || car == NULL)", "|| obbs == NULL)",
      rel=CCP),
    M("co-h0", "h0 = fabsf((hi.x - lo.x) * 0.5f) * scale;",
      "h0 = fabsf((hi.x - lo.x) * 0.5f);", rel=CCP),
    M("co-h0-fabs", "h0 = fabsf((hi.x - lo.x) * 0.5f) * scale;",
      "h0 = (hi.x - lo.x) * 0.5f * scale;", rel=CCP),
    M("co-h1", "h1 = fabsf((hi.y - lo.y) * 0.5f) * scale;",
      "h1 = fabsf((hi.x - lo.x) * 0.5f) * scale;", rel=CCP),
    M("co-h2", "h2 = fabsf((hi.z - lo.z) * 0.5f) * scale;",
      "h2 = fabsf((hi.z - lo.z) * 0.25f) * scale;", rel=CCP),
    M("co-sincos", "bSinCos(&s, &c, car->State.Angle);",
      "bSinCos(&c, &s, car->State.Angle);", rel=CCP),
    M("co-0-a0x", "obbs[0].A0.x = c;", "obbs[0].A0.x = s;", rel=CCP),
    M("co-0-a0y", "obbs[0].A0.y = s;", "obbs[0].A0.y = -s;", rel=CCP),
    M("co-0-a1x", "obbs[0].A1.x = -s;", "obbs[0].A1.x = s;", rel=CCP),
    M("co-0-a1y", "obbs[0].A1.y = c;", "obbs[0].A1.y = -c;", rel=CCP),
    M("co-0-a0pad", "    obbs[0].A0.pad = 0.0f;\n", "", rel=CCP),
    M("co-0-a2z", "obbs[0].A2.z = 1.0f;", "obbs[0].A2.z = 0.0f;", rel=CCP),
    M("co-0-a2y", "    obbs[0].A2.y = 0.0f;\n", "", rel=CCP),
    M("co-0-h0", "obbs[0].a0 = h0;", "obbs[0].a0 = h1;", rel=CCP),
    M("co-0-h1", "obbs[0].a1 = h1;", "obbs[0].a1 = h0;", rel=CCP),
    M("co-0-h2", "obbs[0].a2 = h2;", "obbs[0].a2 = h1;", rel=CCP),
    M("co-0-pos", "obbs[0].Position = t->Points[0];",
      "obbs[0].Position = t->Points[1];", rel=CCP),
    M("co-loop", "for (i = 1; i < t->NumPoints; i++) {",
      "for (i = 1; i < t->NumPoints - 1; i++) {", rel=CCP),
    M("co-dir-y", "dir.y = t->Points[i - 1].y - t->Points[i].y;",
      "dir.y = t->Points[i].y - t->Points[i - 1].y;", rel=CCP),
    M("co-dir-x", "dir.x = t->Points[i - 1].x - t->Points[i].x;",
      "dir.x = t->Points[i].x - t->Points[i - 1].x;", rel=CCP),
    M("co-norm", "        bNormalize2(&dir, &dir);\n", "", rel=CCP),
    M("co-a0y", "o->A0.y = dir.y;", "o->A0.y = dir.x;", rel=CCP),
    M("co-a0x", "o->A0.x = dir.x;", "o->A0.x = -dir.x;", rel=CCP),
    M("co-a1y", "o->A1.y = dir.x;", "o->A1.y = -dir.x;", rel=CCP),
    M("co-a1x", "o->A1.x = -dir.y;", "o->A1.x = dir.y;", rel=CCP),
    M("co-a1pad", "        o->A1.pad = 0.0f;\n", "", rel=CCP),
    M("co-a2z", "o->A2.z = 1.0f;", "o->A2.z = -1.0f;", rel=CCP),
    M("co-a2x", "        o->A2.x = 0.0f;\n", "", rel=CCP),
    M("co-h0s", "o->a0 = h0;", "o->a0 = h1;", rel=CCP),
    M("co-h1s", "o->a1 = h1;", "o->a1 = h2;", rel=CCP),
    M("co-h2s", "o->a2 = h2;", "o->a2 = h0;", rel=CCP),
    M("co-pos", "o->Position = t->Points[i];",
      "o->Position = t->Points[i - 1];", rel=CCP),
    # -- WhenWillOverlapOccur2D ------------------------------------------
    M("cv-c10", "float c10 = a->A1.x * b->A0.x + a->A1.y * b->A0.y;",
      "float c10 = a->A1.x * b->A0.x + a->A1.y * b->A1.y;", rel=CCP),
    M("cv-c00", "float c00 = a->A0.x * b->A0.x + a->A0.y * b->A0.y;",
      "float c00 = a->A0.x * b->A0.x - a->A0.y * b->A0.y;", rel=CCP),
    M("cv-c11", "float c11 = a->A1.x * b->A1.x + a->A1.y * b->A1.y;",
      "float c11 = a->A1.x * b->A1.x;", rel=CCP),
    M("cv-c01", "float c01 = a->A0.x * b->A1.x + a->A0.y * b->A1.y;",
      "float c01 = a->A0.x * b->A1.y + a->A0.y * b->A1.x;", rel=CCP),
    M("cv-ra1-own", "float rA1 = (fabsf(a->a1) +", "float rA1 = (fabsf(a->a0) +",
      rel=CCP),
    M("cv-ra1-c", "fabsf(b->a0 * c10)) + fabsf(b->a1 * c11);",
      "fabsf(b->a0 * c11)) + fabsf(b->a1 * c10);", rel=CCP),
    M("cv-ra0-c", "fabsf(b->a0 * c00)) + fabsf(b->a1 * c01);",
      "fabsf(b->a0 * c00));", rel=CCP),
    M("cv-ra0-fabs", "fabsf(b->a0 * c00)) + fabsf(b->a1 * c01);",
      "b->a0 * c00) + fabsf(b->a1 * c01);", rel=CCP),
    M("cv-ra0-own", "float rA0 = (fabsf(a->a0) +", "float rA0 = (a->a0 +",
      rel=CCP),
    M("cv-rb1-c", "fabsf(a->a0 * c01)) + fabsf(a->a1 * c11);",
      "fabsf(a->a0 * c10)) + fabsf(a->a1 * c11);", rel=CCP),
    M("cv-rb1-own", "float rB1 = (fabsf(b->a1) +", "float rB1 = (fabsf(b->a0) +",
      rel=CCP),
    M("cv-rb0-c", "fabsf(a->a0 * c00)) + fabsf(a->a1 * c10);",
      "fabsf(a->a0 * c00)) + fabsf(a->a1 * c01);", rel=CCP),
    M("cv-rb0-own", "float rB0 = (fabsf(b->a0) +", "float rB0 = (fabsf(b->a1) +",
      rel=CCP),
    M("cv-a1-d", "v->x * a->A1.x + v->y * a->A1.y, d->x * a->A1.x + d->y * a->A1.y,",
      "v->x * a->A1.x + v->y * a->A1.y, d->x * a->A1.x - d->y * a->A1.y,",
      rel=CCP),
    M("cv-a1-v", "v->x * a->A1.x + v->y * a->A1.y, d->x * a->A1.x + d->y * a->A1.y,",
      "v->x * a->A0.x + v->y * a->A0.y, d->x * a->A1.x + d->y * a->A1.y,",
      rel=CCP),
    M("cv-a0-v", "v->x * a->A0.x + v->y * a->A0.y, d->x * a->A0.x + d->y * a->A0.y,",
      "-(v->x * a->A0.x + v->y * a->A0.y), d->x * a->A0.x + d->y * a->A0.y,",
      rel=CCP),
    M("cv-a0-d", "v->x * a->A0.x + v->y * a->A0.y, d->x * a->A0.x + d->y * a->A0.y,",
      "v->x * a->A0.x + v->y * a->A0.y, d->y * a->A0.x + d->x * a->A0.y,",
      rel=CCP),
    M("cv-b1-d", "v->x * b->A1.x + v->y * b->A1.y, d->x * b->A1.x + d->y * b->A1.y,",
      "v->x * b->A1.x + v->y * b->A1.y, d->x * b->A1.x,", rel=CCP),
    M("cv-b1-v", "v->x * b->A1.x + v->y * b->A1.y, d->x * b->A1.x + d->y * b->A1.y,",
      "v->x * b->A1.x - v->y * b->A1.y, d->x * b->A1.x + d->y * b->A1.y,",
      rel=CCP),
    M("cv-b0-v", "v->x * b->A0.x + v->y * b->A0.y, d->x * b->A0.x + d->y * b->A0.y,",
      "v->y * b->A0.x + v->x * b->A0.y, d->x * b->A0.x + d->y * b->A0.y,",
      rel=CCP),
    M("cv-b0-d", "v->x * b->A0.x + v->y * b->A0.y, d->x * b->A0.x + d->y * b->A0.y,",
      "v->x * b->A0.x + v->y * b->A0.y, -(d->x * b->A0.x + d->y * b->A0.y),",
      rel=CCP),
    M("cv-r-a1", "rA1, &in[0], &in[1]);", "rA0, &in[0], &in[1]);", rel=CCP),
    M("cv-r-a0", "rA0, &in[2], &in[3]);", "rA1, &in[2], &in[3]);", rel=CCP),
    M("cv-r-b1", "rB1, &in[4], &in[5]);", "rB0, &in[4], &in[5]);", rel=CCP),
    M("cv-r-b0", "rB0, &in[6], &in[7]);", "rB1, &in[6], &in[7]);", rel=CCP),
    M("cv-ov1", "if (!ccp_interval_overlap(in[0], in[1], in[2], in[3], &lo, &hi)",
      "if (!ccp_interval_overlap(in[0], in[1], in[0], in[1], &lo, &hi)",
      rel=CCP),
    M("cv-ov2", "        || !ccp_interval_overlap(lo, hi, in[4], in[5], &lo, &hi)\n",
      "", rel=CCP),
    M("cv-ov3",
      "        || !ccp_interval_overlap(lo, hi, in[6], in[7], &lo, &hi)) {",
      "        ) {", rel=CCP),
    M("cv-fail", "        lo = CCP_NO_OVERLAP;\n        hi",
      "        lo = -1.0f;\n        hi", rel=CCP),
    M("cv-ret-lo", "if (0.0f < lo)\n        return lo;",
      "if (0.0f <= lo)\n        return lo;", rel=CCP),
    M("cv-ret-0", "if (lo < 0.0f && 0.0f < hi)", "if (lo < 0.0f)", rel=CCP),
    M("cv-ret-0-hi", "if (lo < 0.0f && 0.0f < hi)",
      "if (lo < 0.0f && 0.0f <= hi)", rel=CCP),
    M("cv-ret-0-lo", "if (lo < 0.0f && 0.0f < hi)",
      "if (lo <= 0.0f && 0.0f < hi)", rel=CCP),
    M("cv-ret-none", "        return 0.0f;\n    return CCP_NO_OVERLAP;",
      "        return 0.0f;\n    return hi;", rel=CCP),
    # -- TimeIntervalForSeparatingAxis ------------------------------------
    M("ct-still-fabs", "if (fabsf(v) < CCP_AXIS_STILL) {",
      "if (v < CCP_AXIS_STILL) {", rel=CCP),
    M("ct-still-le", "if (fabsf(v) < CCP_AXIS_STILL) {",
      "if (fabsf(v) <= CCP_AXIS_STILL) {", rel=CCP),
    M("ct-r", "if (r < fabsf(d)) {", "if (r <= fabsf(d)) {", rel=CCP),
    M("ct-r-fabs", "if (r < fabsf(d)) {", "if (r < d) {", rel=CCP),
    M("ct-never-min", "*tmin = CCP_NEVER;", "*tmin = CCP_ALWAYS;", rel=CCP),
    M("ct-never-max", "*tmin = CCP_NEVER;\n            *tmax = CCP_NEVER;",
      "*tmin = CCP_NEVER;\n            *tmax = CCP_ALWAYS;", rel=CCP),
    M("ct-always-min", "*tmin = CCP_ALWAYS;", "*tmin = CCP_NEVER;", rel=CCP),
    M("ct-always-max", "*tmin = CCP_ALWAYS;\n            *tmax = CCP_NEVER;",
      "*tmin = CCP_ALWAYS;\n            *tmax = CCP_ALWAYS;", rel=CCP),
    M("ct-return", "        return;\n    }\n    *tmax = (r - d) / v;",
      "    }\n    *tmax = (r - d) / v;", rel=CCP),
    M("ct-tmax", "*tmax = (r - d) / v;", "*tmax = (r + d) / v;", rel=CCP),
    M("ct-tmin", "*tmin = -(r + d) / v;", "*tmin = (r + d) / v;", rel=CCP),
    M("ct-tmin-d", "*tmin = -(r + d) / v;", "*tmin = -(r - d) / v;", rel=CCP),
    M("ct-swap", "if (v < 0.0f) {", "if (v > 0.0f) {", rel=CCP),
    M("ct-swap-half", "        *tmin = *tmax;\n        *tmax = lo;",
      "        *tmin = *tmax;", rel=CCP),
    # -- IntervalOverlap ------------------------------------------------
    M("cn-passes", "for (n = 3; n > 0; n--) {", "for (n = 2; n > 0; n--) {",
      rel=CCP),
    M("cn-inner", "for (k = 0; k < n; k++) {", "for (k = 1; k < n; k++) {",
      rel=CCP),
    M("cn-cmp", "if (e[k + 1] < e[k]) {", "if (e[k + 1] <= e[k]) {",
      rel=CCP),
    M("cn-swap", "                e[k] = e[k + 1];\n                e[k + 1] = x;",
      "                e[k] = e[k + 1];", rel=CCP),
    M("cn-a0", "if (a0 <= e[1] && e[1] <= a1", "if (a0 < e[1] && e[1] <= a1",
      rel=CCP),
    M("cn-a1", "&& e[1] <= a1 &&", "&& e[1] < a1 &&", rel=CCP),
    M("cn-b0", "&& b0 <= e[1] &&", "&& b0 < e[1] &&", rel=CCP),
    M("cn-b1", "&& e[1] <= b1)", "&& e[1] < b1)", rel=CCP),
    M("cn-lo", "*lo = e[1];", "*lo = e[0];", rel=CCP),
    M("cn-hi", "*hi = e[2];", "*hi = e[3];", rel=CCP),
    M("cn-ret", "        return 1;\n    }\n    return 0;",
      "        return 0;\n    }\n    return 0;", rel=CCP),
    # -- IsDriveable (11b-4b) -------------------------------------------
    M("id-score-init", "    *score = -1.0f;\n    *hitCar = NULL;",
      "    *score = 0.0f;\n    *hitCar = NULL;"),
    M("id-hitcar-init",
      "*hitCar = NULL;\n    *hitTime = DC_NO_HIT;\n    if (drivingchoice_build",
      "*hitCar = list->MyCar;\n    *hitTime = DC_NO_HIT;\n"
      "    if (drivingchoice_build"),
    M("id-hittime-init",
      "*hitTime = DC_NO_HIT;\n    if (drivingchoice_build",
      "*hitTime = 0.0f;\n    if (drivingchoice_build"),
    M("id-m", "maxTime,\n                                         m)) {",
      "maxTime,\n                                         !m)) {"),
    M("id-score-gt", "if (-1.0f < s) {", "if (-1.0f <= s) {"),
    M("id-pref", "        if (preferred) {\n                *score",
      "        if (!preferred) {\n                *score"),
    M("id-pref-scale", "*score = s * DC_PREFERRED;", "*score = s;"),
    M("id-exclude-pref",
      "c->CarToExcludeFromCollisionPrediction = d->pCar;",
      "c->CarToExcludeFromCollisionPrediction = NULL;"),
    M("id-exclude-none",
      "            } else {\n"
      "                c->CarToExcludeFromCollisionPrediction = NULL;",
      "            } else {\n"
      "                c->CarToExcludeFromCollisionPrediction = d->pCar;"),
    M("id-who-max", "loc,\n                                                         maxTime, hitTime);",
      "loc,\n                                                         maxTime + 1.0f, hitTime);"),
    M("id-ok-lt", "if (maxTime < *hitTime)", "if (maxTime <= *hitTime)"),
    M("id-pdt", "    pCurrentWorld->PotentialDriveTargetID++;\n    return ok;",
      "    return ok;"),
    # -- TryChoice --------------------------------------------------------
    M("tc-traffic",
      "TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n        && AITrafficTuningMode != 0) {",
      "TheDriverType != DRIVER_TYPE_TRAFFIC_CAR\n        && AITrafficTuningMode != 0) {"),
    M("tc-tuning",
      "DRIVER_TYPE_TRAFFIC_CAR\n        && AITrafficTuningMode != 0) {",
      "DRIVER_TYPE_TRAFFIC_CAR\n        && AITrafficTuningMode == 0) {"),
    M("tc-and", "DRIVER_TYPE_TRAFFIC_CAR\n        && AITrafficTuningMode != 0) {",
      "DRIVER_TYPE_TRAFFIC_CAR\n        || AITrafficTuningMode != 0) {"),
    M("tc-side", "        if (!drivingchoice_type_is_side_of_car(c->Type))\n            ok = 0;",
      "        if (drivingchoice_type_is_side_of_car(c->Type))\n            ok = 0;"),
    M("tc-racer", "TheDriverType != DRIVER_TYPE_AI_RACER\n                 && c->pCar",
      "TheDriverType == DRIVER_TYPE_AI_RACER\n                 && c->pCar"),
    M("tc-player", "&& c->pCar->pPlayer == NULL)", "&& c->pCar->pPlayer != NULL)"),
    M("tc-racer-or", "DRIVER_TYPE_AI_RACER\n                 && c->pCar->pPlayer",
      "DRIVER_TYPE_AI_RACER\n                 || c->pCar->pPlayer"),
    M("tc-ok", "        if (!ok)\n            return 0;\n    }\n    *hitCar",
      "        if (ok)\n            return 0;\n    }\n    *hitCar"),
    M("tc-hittime-init",
      "*hitTime = DC_NO_HIT;\n    if (drivingchoice_is_driveable",
      "*hitTime = 0.0f;\n    if (drivingchoice_is_driveable"),
    M("tc-pref", "drivingchoice_is_driveable(c, t, preferred, &score,",
      "drivingchoice_is_driveable(c, t, 0, &score,"),
    M("tc-m", "loc, list, 0.0f, maxTime, 0.0f,\n"
      "                                   MOVEMENT_TOWARDS_LINE)",
      "loc, list, 0.0f, maxTime, 0.0f,\n"
      "                                   MOVEMENT_PARALLEL_TO_LINE)"),
    M("tc-max", "loc, list, 0.0f, maxTime, 0.0f,\n"
      "                                   MOVEMENT_TOWARDS_LINE)",
      "loc, list, 0.0f, maxTime * 2.0f, 0.0f,\n"
      "                                   MOVEMENT_TOWARDS_LINE)"),
    M("tc-best-lt", "&& *bestScore < score) {", "&& *bestScore <= score) {"),
    M("tc-best-and", "MOVEMENT_TOWARDS_LINE)\n        && *bestScore < score) {",
      "MOVEMENT_TOWARDS_LINE)\n        || *bestScore < score) {"),
    M("tc-found", "        *found = 1;\n        *best = *c;",
      "        *found = 0;\n        *best = *c;"),
    M("tc-best", "        *found = 1;\n        *best = *c;",
      "        *found = 1;"),
    M("tc-best-target", "drivetarget_assign(bestTarget, t);", ";"),
    M("tc-bestout", "*bestOut = 0;", "*bestOut = 1;"),
    M("tc-bestscore", "        *bestScore = score;\n", "\n"),
    M("tc-scored", "scored = !(fabsf(score - -1.0f) <= DC_NO_SCORE);",
      "scored = !(fabsf(score - -1.0f) < DC_NO_SCORE);"),
    M("tc-scored-not", "scored = !(fabsf(score - -1.0f) <= DC_NO_SCORE);",
      "scored = (fabsf(score - -1.0f) <= DC_NO_SCORE);"),
    M("tc-round-side",
      "    if (!drivingchoice_type_is_side_of_car(c->Type)\n        || c->Use",
      "    if (drivingchoice_type_is_side_of_car(c->Type)\n        || c->Use"),
    M("tc-round-extra", "|| c->UseExtraLateralDistance || c->pCar != inTheWay)",
      "|| !c->UseExtraLateralDistance || c->pCar != inTheWay)"),
    M("tc-round-car", "|| c->pCar != inTheWay)", "|| c->pCar == inTheWay)"),
    M("tc-round-pref", "    if (preferred) {\n        *round = *c;",
      "    if (!preferred) {\n        *round = *c;"),
    M("tc-round", "        *round = *c;\n", "\n"),
    M("tc-round-target", "drivetarget_assign(roundTarget, t);", ";"),
    M("tc-round-time", "*roundTime = *hitTime;", "*roundTime = 0.0f;"),
    M("tc-ret", "        *roundTime = *hitTime;\n    }\n    return scored;",
      "        *roundTime = *hitTime;\n    }\n    return !scored;"),
    # -- MakeNewChoice ----------------------------------------------------
    M("mn-valid", "    if (drivingchoice_is_valid(d, loc, list))\n"
      "        drivingchoice_set_choice_choice(&current, d);",
      "    if (!drivingchoice_is_valid(d, loc, list))\n"
      "        drivingchoice_set_choice_choice(&current, d);"),
    M("mn-try-current",
      "    if (tryCurrent) {\n        if (drivingchoice_type_is_side_of_car(current.Type)) {",
      "    if (!tryCurrent) {\n        if (drivingchoice_type_is_side_of_car(current.Type)) {"),
    M("mn-cur-side",
      "        if (drivingchoice_type_is_side_of_car(current.Type)) {\n"
      "            NearbyCar",
      "        if (!drivingchoice_type_is_side_of_car(current.Type)) {\n"
      "            NearbyCar"),
    M("mn-cur-pside",
      "                if (drivingchoice_get_preferred_side_of_car(nc, list, loc)) {",
      "                if (!drivingchoice_get_preferred_side_of_car(nc, list, loc)) {"),
    M("mn-pref-left",
      "if (current.Type == CHOICE_LEFT_SIDE_OF_CAR)\n                        preferred = 1;",
      "if (current.Type == CHOICE_RIGHT_SIDE_OF_CAR)\n                        preferred = 1;"),
    M("mn-pref-right",
      "} else if (current.Type == CHOICE_RIGHT_SIDE_OF_CAR) {\n"
      "                    preferred = 1;",
      "} else if (current.Type == CHOICE_LEFT_SIDE_OF_CAR) {\n"
      "                    preferred = 1;"),
    M("mn-cur-time", "currentTime = hitTime;", "currentTime = DC_NO_HIT;"),
    M("mn-intheway", "inTheWay = hitCar;", "inTheWay = NULL;"),
    M("mn-round-and", "if (preferred && current.pCar == inTheWay) {",
      "if (preferred || current.pCar == inTheWay) {"),
    M("mn-round-car", "if (preferred && current.pCar == inTheWay) {",
      "if (preferred && current.pCar != inTheWay) {"),
    M("mn-round", "            roundChoice = current;\n", "\n"),
    M("mn-round-target", "drivetarget_assign(&round, &scratch);", ";"),
    M("mn-lines", "    if (!found) {\n        for (i = 0;",
      "    if (found) {\n        for (i = 0;"),
    M("mn-lines-n",
      "for (i = 0; i < AICarControllerNumDrivingLinesToConsider && !found;",
      "for (i = 0; i <= AICarControllerNumDrivingLinesToConsider && !found;"),
    M("mn-lines-stop",
      "AICarControllerNumDrivingLinesToConsider && !found;",
      "AICarControllerNumDrivingLinesToConsider;"),
    M("mn-line", "drivingchoice_set_choice(&tryChoice, i + 1, NULL, 0);",
      "drivingchoice_set_choice(&tryChoice, i, NULL, 0);"),
    M("mn-line-skip",
      "if (tryCurrent && drivingchoice_is_equal_to(&tryChoice, &current))",
      "if (!tryCurrent && drivingchoice_is_equal_to(&tryChoice, &current))"),
    M("mn-line-pref", "drivingchoice_try_choice(&tryChoice, 0, maxTime,",
      "drivingchoice_try_choice(&tryChoice, 1, maxTime,"),
    M("mn-line-way", "&hitCar, &hitTime,\n                                     inTheWay);",
      "&hitCar, &hitTime,\n                                     NULL);"),
    M("mn-cars", "    if (!found) {\n        // Every car",
      "    if (found) {\n        // Every car"),
    M("mn-cars-n", "for (i = 0; i < list->NumCarsInArray; i++) {\n"
      "            NearbyCar *nc = &list->Array[i];\n            int side",
      "for (i = 1; i < list->NumCarsInArray; i++) {\n"
      "            NearbyCar *nc = &list->Array[i];\n            int side"),
    M("mn-care", "            if (!ai_do_we_care_about_this_car(nc, list))\n"
      "                continue;\n            side =",
      "            if (ai_do_we_care_about_this_car(nc, list))\n"
      "                continue;\n            side ="),
    M("mn-left", "drivingchoice_set_choice(&tryChoice, CHOICE_LEFT_SIDE_OF_CAR,",
      "drivingchoice_set_choice(&tryChoice, CHOICE_RIGHT_SIDE_OF_CAR,"),
    M("mn-left-skip", "            if (!tryCurrent\n"
      "                || !drivingchoice_is_equal_to(&tryChoice, &current))\n"
      "                tried =",
      "            if (tryCurrent\n"
      "                || !drivingchoice_is_equal_to(&tryChoice, &current))\n"
      "                tried ="),
    M("mn-left-eq", "                || !drivingchoice_is_equal_to(&tryChoice, &current))\n"
      "                tried =",
      "                || drivingchoice_is_equal_to(&tryChoice, &current))\n"
      "                tried ="),
    M("mn-left-pref", "&tryChoice, side, maxTime,", "&tryChoice, !side, maxTime,"),
    M("mn-left-tried", "&hitCar, &hitTime, inTheWay) != 0;",
      "&hitCar, &hitTime, inTheWay) == 0;"),
    M("mn-right", "drivingchoice_set_choice(&tryChoice, CHOICE_RIGHT_SIDE_OF_CAR,",
      "drivingchoice_set_choice(&tryChoice, CHOICE_LEFT_SIDE_OF_CAR,"),
    M("mn-right-skip", "            if (!tryCurrent\n"
      "                || !drivingchoice_is_equal_to(&tryChoice, &current)) {",
      "            if (tryCurrent\n"
      "                || !drivingchoice_is_equal_to(&tryChoice, &current)) {"),
    M("mn-right-pref", "&tryChoice, side ^ 1, maxTime,",
      "&tryChoice, side, maxTime,"),
    M("mn-tried-or", "tried = tried || r;", "tried = r;"),
    M("mn-tried", "            if (!tried) {", "            if (tried) {"),
    M("mn-dot-x", "float dot = v->x * mine->x;", "float dot = v->x * mine->y;"),
    M("mn-dot-y", "dot = dot + v->y * mine->y;", "dot = v->y * mine->y;"),
    M("mn-dot-lt", "if (dot < 0.0f) {", "if (dot > 0.0f) {"),
    M("mn-opp-side", "side ? CHOICE_LEFT_SIDE_OF_CAR\n"
      "                                         : CHOICE_RIGHT_SIDE_OF_CAR,",
      "side ? CHOICE_RIGHT_SIDE_OF_CAR\n"
      "                                         : CHOICE_LEFT_SIDE_OF_CAR,"),
    M("mn-opp-extra", "                        nc->TheCar, 1);",
      "                        nc->TheCar, 0);"),
    M("mn-opp-pref", "                        &tryChoice, 1, maxTime,",
      "                        &tryChoice, 0, maxTime,"),
    M("mn-found", "    if (found) {\n        drivingchoice_set_choice_choice(d, &bestChoice);",
      "    if (!found) {\n        drivingchoice_set_choice_choice(d, &bestChoice);"),
    M("mn-found-set", "drivingchoice_set_choice_choice(d, &bestChoice);",
      "drivingchoice_set_choice_choice(d, &roundChoice);"),
    M("mn-found-target", "drivetarget_assign(t, &best);",
      "drivetarget_assign(t, &round);"),
    M("mn-found-out", "*out = bestOut;", "*out = 1;"),
    M("mn-rvalid", "} else if (drivingchoice_is_valid(&roundChoice, loc, list)",
      "} else if (!drivingchoice_is_valid(&roundChoice, loc, list)"),
    M("mn-rand", "list)\n               && currentTime - DC_HIT_MARGIN <= roundTime) {",
      "list)\n               || currentTime - DC_HIT_MARGIN <= roundTime) {"),
    M("mn-rmargin", "currentTime - DC_HIT_MARGIN <= roundTime",
      "currentTime + DC_HIT_MARGIN <= roundTime"),
    M("mn-rle", "currentTime - DC_HIT_MARGIN <= roundTime",
      "currentTime - DC_HIT_MARGIN < roundTime"),
    M("mn-rset", "drivingchoice_set_choice_choice(d, &roundChoice);",
      "drivingchoice_set_choice_choice(d, &bestChoice);"),
    M("mn-rtarget", "drivetarget_assign(t, &round);",
      "drivetarget_assign(t, &best);"),
    M("mn-rout", "        *out = 1;\n    } else if (!(fabsf(currentScore",
      "        *out = 0;\n    } else if (!(fabsf(currentScore"),
    M("mn-third", "} else if (!(fabsf(currentScore - -1.0f) <= DC_NO_SCORE)) {",
      "} else if (0) {"),
    M("mn-fb-loc", "        drivingchoice_set_choice_location(d, loc);\n"
      "        drivingchoice_fill_up_drive_target(t, loc, list,",
      "        drivingchoice_fill_up_drive_target(t, loc, list,"),
    M("mn-fb-m", "MOVEMENT_PARALLEL_TO_LINE, 1);\n        *out = 0;\n        found = 0;",
      "MOVEMENT_TOWARDS_LINE, 1);\n        *out = 0;\n        found = 0;"),
    M("mn-fb-flag", "MOVEMENT_PARALLEL_TO_LINE, 1);\n        *out = 0;\n        found = 0;",
      "MOVEMENT_PARALLEL_TO_LINE, 0);\n        *out = 0;\n        found = 0;"),
    M("mn-fb-out", "        *out = 0;\n        found = 0;",
      "        *out = 1;\n        found = 0;"),
    M("mn-fixup", "d, list->MyCar, *out, list);\n    return found;",
      "d, list->MyCar, 0, list);\n    return found;"),
    M("mn-ret", "    return found;\n}", "    return !found;\n}"),
    # -- TryToDriveAroundCar ----------------------------------------------
    M("ta-saved", "drivetarget_copy(&saved, t);", "drivetarget_init(&saved);"),
    M("ta-current", "if (d->Type != CHOICE_NONE)\n        drivingchoice_set_choice_choice(&current, d);",
      "if (d->Type == CHOICE_NONE)\n        drivingchoice_set_choice_choice(&current, d);"),
    M("ta-fast-its", "            < nc->TheCar->State.VelocityMagnitude",
      "            <= nc->TheCar->State.VelocityMagnitude"),
    M("ta-fast-mine", "               < list->MyCar->State.VelocityMagnitude)",
      "               <= list->MyCar->State.VelocityMagnitude)"),
    M("ta-fast-or", "VelocityMagnitude\n        || TryToDriveAroundCarMinSpeedForDrivingLine",
      "VelocityMagnitude\n        && TryToDriveAroundCarMinSpeedForDrivingLine"),
    M("ta-try", "    if (tryCurrent\n        && (!drivingchoice_type_is_driving_line",
      "    if (!tryCurrent\n        && (!drivingchoice_type_is_driving_line"),
    M("ta-line", "(!drivingchoice_type_is_driving_line(current.Type) || fast)",
      "(drivingchoice_type_is_driving_line(current.Type) || fast)"),
    M("ta-line-or", "(!drivingchoice_type_is_driving_line(current.Type) || fast)",
      "(!drivingchoice_type_is_driving_line(current.Type) && fast)"),
    M("ta-valid", "        && drivingchoice_is_valid(&current, loc, list)\n        && (!",
      "        && !drivingchoice_is_valid(&current, loc, list)\n        && (!"),
    M("ta-side", "        && (!drivingchoice_type_is_side_of_car(current.Type)\n"
      "            || nc->TheCar == current.pCar)) {",
      "        && (drivingchoice_type_is_side_of_car(current.Type)\n"
      "            || nc->TheCar == current.pCar)) {"),
    M("ta-side-car", "|| nc->TheCar == current.pCar)) {",
      "|| nc->TheCar != current.pCar)) {"),
    M("ta-pref-left", "preferred = side != 0;", "preferred = side == 0;"),
    M("ta-pref-right", "            preferred = side == 0;\n        drivetarget_assign",
      "            preferred = side != 0;\n        drivetarget_assign"),
    M("ta-cur-restore", "        drivetarget_assign(t, &saved);\n"
      "        if (drivingchoice_is_driveable(&current,",
      "        if (drivingchoice_is_driveable(&current,"),
    M("ta-cur-pref", "drivingchoice_is_driveable(&current, t, preferred, &score,",
      "drivingchoice_is_driveable(&current, t, 0, &score,"),
    M("ta-cur-m", "&hitTime, loc, list, a, maxTime, 0.0f,\n"
      "                                       MOVEMENT_TOWARDS_LINE)) {",
      "&hitTime, loc, list, a, maxTime, 0.0f,\n"
      "                                       MOVEMENT_PARALLEL_TO_LINE)) {"),
    M("ta-cur-out", "*out = preferred;", "*out = !preferred;"),
    M("ta-lines", "    if (!done && fast) {", "    if (!done || fast) {"),
    M("ta-lines-fast", "    if (!done && fast) {", "    if (!done && !fast) {"),
    M("ta-lines-n",
      "for (i = 0; i < AICarControllerNumDrivingLinesToConsider && !done;",
      "for (i = 0; i <= AICarControllerNumDrivingLinesToConsider && !done;"),
    M("ta-lines-stop", "AICarControllerNumDrivingLinesToConsider && !done;",
      "AICarControllerNumDrivingLinesToConsider;"),
    M("ta-line-num", "drivingchoice_set_choice(&line, i + 1, NULL, 0);",
      "drivingchoice_set_choice(&line, i, NULL, 0);"),
    M("ta-line-skip", "if (tryCurrent && drivingchoice_is_equal_to(&line, &current))",
      "if (!tryCurrent && drivingchoice_is_equal_to(&line, &current))"),
    M("ta-line-restore", "            drivetarget_assign(t, &saved);\n"
      "            if (drivingchoice_is_driveable(&line,",
      "            if (drivingchoice_is_driveable(&line,"),
    M("ta-line-set", "                drivingchoice_set_choice_choice(d, &line);\n", "\n"),
    M("ta-line-out", "(d, &line);\n                done = 1;\n                *out = 0;",
      "(d, &line);\n                done = 1;\n                *out = 1;"),
    M("ta-sides", "    if (!done) {\n        DrivingChoice first, second;",
      "    if (done) {\n        DrivingChoice first, second;"),
    M("ta-first", "drivingchoice_set_choice(&first, side ? CHOICE_LEFT_SIDE_OF_CAR\n"
      "                                              : CHOICE_RIGHT_SIDE_OF_CAR,",
      "drivingchoice_set_choice(&first, side ? CHOICE_RIGHT_SIDE_OF_CAR\n"
      "                                              : CHOICE_LEFT_SIDE_OF_CAR,"),
    M("ta-second", "drivingchoice_set_choice(&second, side ? CHOICE_RIGHT_SIDE_OF_CAR\n"
      "                                               : CHOICE_LEFT_SIDE_OF_CAR,",
      "drivingchoice_set_choice(&second, side ? CHOICE_LEFT_SIDE_OF_CAR\n"
      "                                               : CHOICE_RIGHT_SIDE_OF_CAR,"),
    M("ta-first-skip", "if (!(tryCurrent && drivingchoice_is_equal_to(&first, &current))",
      "if ((tryCurrent && drivingchoice_is_equal_to(&first, &current))"),
    M("ta-first-eq", "if (!(tryCurrent && drivingchoice_is_equal_to(&first, &current))",
      "if (!(tryCurrent && !drivingchoice_is_equal_to(&first, &current))"),
    M("ta-first-fast", "&& (fast || drivingchoice_is_enough_room(&first, nc, list))) {",
      "&& (drivingchoice_is_enough_room(&first, nc, list))) {"),
    M("ta-first-room", "&& (fast || drivingchoice_is_enough_room(&first, nc, list))) {",
      "&& (fast || !drivingchoice_is_enough_room(&first, nc, list))) {"),
    M("ta-first-restore", "            drivetarget_assign(t, &saved);\n"
      "            if (drivingchoice_is_driveable(&first,",
      "            if (drivingchoice_is_driveable(&first,"),
    M("ta-first-pref", "drivingchoice_is_driveable(&first, t, 1, &score,",
      "drivingchoice_is_driveable(&first, t, 0, &score,"),
    M("ta-first-set", "                drivingchoice_set_choice_choice(d, &first);\n"
      "                done = 1;\n                *out = 1;",
      "                done = 1;\n                *out = 1;"),
    M("ta-first-out", "(d, &first);\n                done = 1;\n                *out = 1;",
      "(d, &first);\n                done = 1;\n                *out = 0;"),
    M("ta-second-done", "        if (!done\n            && !(tryCurrent",
      "        if (1\n            && !(tryCurrent"),
    M("ta-second-skip", "&& !(tryCurrent && drivingchoice_is_equal_to(&second, &current))",
      "&& (tryCurrent && drivingchoice_is_equal_to(&second, &current))"),
    M("ta-second-fast", "&& (fast || drivingchoice_is_enough_room(&second, nc, list))) {",
      "&& (drivingchoice_is_enough_room(&second, nc, list))) {"),
    M("ta-second-room", "&& (fast || drivingchoice_is_enough_room(&second, nc, list))) {",
      "&& (fast || !drivingchoice_is_enough_room(&second, nc, list))) {"),
    M("ta-second-restore", "            drivetarget_assign(t, &saved);\n"
      "            if (drivingchoice_is_driveable(&second,",
      "            if (drivingchoice_is_driveable(&second,"),
    M("ta-second-pref", "drivingchoice_is_driveable(&second, t, 0, &score,",
      "drivingchoice_is_driveable(&second, t, 1, &score,"),
    M("ta-second-set", "                drivingchoice_set_choice_choice(d, &second);\n", "\n"),
    M("ta-second-out", "(d, &second);\n                done = 1;\n                *out = 0;",
      "(d, &second);\n                done = 1;\n                *out = 1;"),
    M("ta-fb", "        if (!done) {\n            // The current choice",
      "        if (done) {\n            // The current choice"),
    M("ta-fb-valid", "            if (drivingchoice_is_valid(&current, loc, list))\n"
      "                drivingchoice_set_choice_choice(&first, &current);",
      "            if (!drivingchoice_is_valid(&current, loc, list))\n"
      "                drivingchoice_set_choice_choice(&first, &current);"),
    M("ta-fb-m", "drivingchoice_build_drive_target(&first, t, loc, list, a, maxTime,\n"
      "                                             MOVEMENT_PARALLEL_TO_LINE);",
      "drivingchoice_build_drive_target(&first, t, loc, list, a, maxTime,\n"
      "                                             MOVEMENT_TOWARDS_LINE);"),
    M("ta-fb-set", "MOVEMENT_PARALLEL_TO_LINE);\n            drivingchoice_set_choice_choice(d, &first);",
      "MOVEMENT_PARALLEL_TO_LINE);"),
    M("ta-fixup", "d, list->MyCar, *out, list);\n    return done;",
      "d, list->MyCar, 0, list);\n    return done;"),
    M("ta-ret", "*out, list);\n    return done;\n}",
      "*out, list);\n    return !done;\n}"),
    # -- step 11d-1's: the five actions ------------------------------------
    AM("aa-tick", "0.000250000012f  // gp-28708", "0.00026f  // gp-28708"),
    AM("aa-signed", "    return (float)(int32_t)((uint32_t)WorldTimer - t->PackedTime)",
       "    return (float)((uint32_t)WorldTimer - t->PackedTime)"),
    AM("aa-exp-lt", "return p->DeltaTime < seconds_since", "return p->DeltaTime <= seconds_since"),
    AM("aa-exp-can", "           && p->CanExpire != 0;", ";"),
    AM("aa-un-le", "if (seconds_since(&a->Base.ExpiryTimer) <= a->Base.DeltaTime)",
       "if (seconds_since(&a->Base.ExpiryTimer) < a->Base.DeltaTime)"),
    AM("aa-un-nan", "if (seconds_since(&a->Base.ExpiryTimer) <= a->Base.DeltaTime)",
       "if (!(a->Base.DeltaTime < seconds_since(&a->Base.ExpiryTimer)))"),
    AM("aa-un-pt", "    if (a->PointsToDriveWillExecuteAction != 0)\n        return 0;\n", ""),
    AM("aa-un-can", "    return a->Base.CanExpire != 0;\n}", "    return 1;\n}"),
    AM("aa-dtor-flags", "    aiaction_destroy(a, 0);\n    if (flags & 1)",
       "    aiaction_destroy(a, 0);\n    if (flags & 2)"),
    AM("aa-dtor-zero", "    aiaction_destroy(a, 0);", "    aiaction_destroy(a, flags);"),
    AM("aa-line-test", "    if (drivingchoice_type_is_driving_line(choice->Type))\n        return;",
       "    if (!drivingchoice_type_is_driving_line(choice->Type))\n        return;"),
    AM("aa-line-set", "    drivingchoice_set_choice(choice, CHOICE_DRIVING_LINE_0, NULL, 0);",
       "    drivingchoice_set_choice(choice, CHOICE_DRIVING_LINE_1, NULL, 0);"),
    AM("aa-line-line", "drivingchoice_get_driving_line(CHOICE_DRIVING_LINE_0,\n                                       info",
       "drivingchoice_get_driving_line(CHOICE_DRIVING_LINE_1,\n                                       info"),
    AM("aa-line-relaxed", "info->MyNearbyCarList.MyCar),\n        1);",
       "info->MyNearbyCarList.MyCar),\n        0);"),
    AM("aa-avoid", "float AIDriverAvoidCarsImpactTimeThreshold = 2.0f;",
       "float AIDriverAvoidCarsImpactTimeThreshold = 2.5f;"),
    # JustDrive.
    AM("jd-type", "a->Base.Type = AIACTION_JUST_DRIVE;", "a->Base.Type = AIACTION_DRAFT;"),
    AM("jd-vt", "    a->Base.Base._vtable = AIJUSTDRIVE_VTABLE;",
       "    a->Base.Base._vtable = AIDRAFT_VTABLE;"),
    AM("jd-last", "AIJUSTDRIVE_VTABLE;\n    a->LastDecisionReevaluationTime.PackedTime = 0;",
       "AIJUSTDRIVE_VTABLE;\n    a->LastDecisionReevaluationTime.PackedTime = (uint32_t)WorldTimer;"),
    AM("jd-score", "    (void)info;\n    return 0;\n}\n\nint aijustdrive_has_been",
       "    (void)info;\n    return 1;\n}\n\nint aijustdrive_has_been"),
    AM("jd-acc", "    // 0x001c7460.\n    (void)a;\n    (void)info;\n    return 0;",
       "    // 0x001c7460.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("jd-fail", "    // 0x001c74b0.\n    (void)a;\n    (void)info;\n    return 0;",
       "    // 0x001c74b0.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("jd-exp", "    // 0x001c7468.\n    (void)info;\n    return past_timeout(&a->Base.Base);",
       "    // 0x001c7468.\n    (void)info;\n    return 0;"),
    AM("jd-every", "    if (AIJD_REEVALUATE_EVERY\n        <= (float)",
       "    if (AIJD_REEVALUATE_EVERY\n        < (float)"),
    AM("jd-every-const", "AIJD_REEVALUATE_EVERY  3.0f", "AIJD_REEVALUATE_EVERY  2.0f"),
    AM("jd-now", "        a->LastDecisionReevaluationTime.PackedTime = (uint32_t)now;\n", ""),
    AM("jd-now-inside",
       "        a->LastDecisionReevaluationTime.PackedTime = (uint32_t)now;\n"
       "        if (choice->Type != CHOICE_DRIVING_LINE_0) {\n",
       "        if (choice->Type != CHOICE_DRIVING_LINE_0) {\n"
       "            a->LastDecisionReevaluationTime.PackedTime = (uint32_t)now;\n"),
    AM("jd-type-test", "        if (choice->Type != CHOICE_DRIVING_LINE_0) {",
       "        if (!drivingchoice_type_is_driving_line(choice->Type)) {"),
    AM("jd-try-line", "drivingchoice_set_choice(&c, CHOICE_DRIVING_LINE_0, NULL, 0);",
       "drivingchoice_set_choice(&c, CHOICE_DRIVING_LINE_1, NULL, 0);"),
    AM("jd-pref", "&c, &t, 0, &score,", "&c, &t, 1, &score,"),
    AM("jd-a", "&info->MyNearbyCarList, 0.0f,\n                    AIDriverAvoid",
       "&info->MyNearbyCarList, 1.0f,\n                    AIDriverAvoid"),
    AM("jd-thr", "AIDriverAvoidCarsImpactTimeThreshold, 0.0f,\n                    MOVEMENT_TOWARDS_LINE)) {",
       "2.0f, 0.0f,\n                    MOVEMENT_TOWARDS_LINE)) {"),
    AM("jd-move", "                    MOVEMENT_TOWARDS_LINE)) {",
       "                    MOVEMENT_PARALLEL_TO_LINE)) {"),
    AM("jd-copy", "                *choice = c;\n                done = 1;\n", "                done = 1;\n"),
    AM("jd-done", "                done = 1;\n", ""),
    AM("jd-relaxed", "                    1);\n                drivetarget_assign",
       "                    0);\n                drivetarget_assign"),
    AM("jd-assign", "                drivetarget_assign(&a->Base.PointsToDrive, &t);\n            }", "            }"),
    AM("jd-notdone", "    if (!done) {\n        make_choice_a_line(info);",
       "    if (1) {\n        make_choice_a_line(info);"),
    AM("jd-mkline", "    if (!done) {\n        make_choice_a_line(info);",
       "    if (!done) {"),
    AM("jd-build", "&info->MyNearbyCarList, 0.0f, 0.0f,\n                                         MOVEMENT_TOWARDS_LINE);",
       "&info->MyNearbyCarList, 0.0f, 0.0f,\n                                         MOVEMENT_PARALLEL_TO_LINE);"),
    AM("jd-tol", "    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.PointsToDriveWillExecuteAction = 1;\n    a->Base.UseDrivingLineSpeed = 1;",
       "    a->Base.DesiredSpeedTolerance = 1.0f;\n    a->Base.PointsToDriveWillExecuteAction = 1;\n    a->Base.UseDrivingLineSpeed = 1;"),
    AM("jd-pt", "    a->Base.PointsToDriveWillExecuteAction = 1;\n    a->Base.UseDrivingLineSpeed = 1;",
       "    a->Base.PointsToDriveWillExecuteAction = 0;\n    a->Base.UseDrivingLineSpeed = 1;"),
    AM("jd-udl", "    a->Base.UseDrivingLineSpeed = 1;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.AllowedToUseBoost = 1;",
       "    a->Base.UseDrivingLineSpeed = 0;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.AllowedToUseBoost = 1;"),
    AM("jd-tb", "    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.AllowedToUseBoost = 1;\n}",
       "    a->Base.AllowedToUseThrottleAndBrake = 0;\n    a->Base.AllowedToUseBoost = 1;\n}"),
    AM("jd-bo", "    a->Base.AllowedToUseBoost = 1;\n}", "    a->Base.AllowedToUseBoost = 0;\n}"),
    AM("jd-name", "\"Just Drive\"", "\"Just drive\""),
    AM("jd-dtor", "destroy_as(&a->Base, AIJUSTDRIVE_VTABLE, flags);",
       "destroy_as(&a->Base, AIJUSTDRIVE_VTABLE, 0);"),
    # Draft.
    AM("dr-type", "a->Base.Type = AIACTION_DRAFT;", "a->Base.Type = AIACTION_BLOCK;"),
    AM("dr-vt", "    a->Base.Base._vtable = AIDRAFT_VTABLE;",
       "    a->Base.Base._vtable = AIJUSTDRIVE_VTABLE;"),
    AM("dr-score", "car) != NULL\n               ? AIDR_SCORE", "car) == NULL\n               ? AIDR_SCORE"),
    AM("dr-score-car", "nearbycarlist_get_car_ahead(&info->MyNearbyCarList, car)",
       "nearbycarlist_get_car_ahead(&info->MyNearbyCarList,\n                                       info->MyNearbyCarList.MyCar)"),
    AM("dr-acc", "    // 0x001c7750.\n    (void)a;\n    (void)info;\n    return 0;",
       "    // 0x001c7750.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("dr-fail", "    // 0x001c77a0.\n    (void)a;\n    (void)info;\n    return 0;",
       "    // 0x001c77a0.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("dr-exp", "    // 0x001c7758.\n    (void)info;\n    return past_timeout(&a->Base.Base);",
       "    // 0x001c7758.\n    (void)info;\n    return past_timeout_unstarted(&a->Base);"),
    AM("dr-mkline", "    make_choice_a_line(info);\n    drivingchoice_build_drive_target(&info->MyDrivingChoice,",
       "    drivingchoice_build_drive_target(&info->MyDrivingChoice,"),
    AM("dr-move", "list, 0.0f,\n                                     0.0f, MOVEMENT_TOWARDS_LINE);",
       "list, 0.0f,\n                                     0.0f, MOVEMENT_PARALLEL_TO_LINE);"),
    AM("dr-tol", "    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.AllowedToUseBoost = 1;",
       "    a->Base.DesiredSpeedTolerance = 1.0f;\n    a->Base.AllowedToUseBoost = 1;"),
    AM("dr-bo", "    a->Base.AllowedToUseBoost = 1;\n    a->Base.UseDrivingLineSpeed = 1;",
       "    a->Base.AllowedToUseBoost = 0;\n    a->Base.UseDrivingLineSpeed = 1;"),
    AM("dr-udl", "    a->Base.UseDrivingLineSpeed = 1;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    nc",
       "    a->Base.UseDrivingLineSpeed = 0;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    nc"),
    AM("dr-tb", "    a->Base.AllowedToUseThrottleAndBrake = 1;\n    nc",
       "    a->Base.AllowedToUseThrottleAndBrake = 0;\n    nc"),
    AM("dr-ahead", "    nc = nearbycarlist_get_car_ahead(list, list->MyCar);",
       "    nc = NULL;"),
    AM("dr-abs", "&& fabsf(nc->Position.x) <", "&& nc->Position.x <"),
    AM("dr-across-lt", "fabsf(nc->Position.x) < list->MyHalfSizeL",
       "fabsf(nc->Position.x) <= list->MyHalfSizeL"),
    AM("dr-across-hl", "< list->MyHalfSizeL + nc->ApparentHalfSizeL",
       "< nc->ApparentHalfSizeL"),
    AM("dr-close-lt", "&& nc->Position.y < AIDR_CLOSE", "&& nc->Position.y <= AIDR_CLOSE"),
    AM("dr-close", "AIDR_CLOSE             6.0f", "AIDR_CLOSE             7.0f"),
    AM("dr-gap", "AIDR_GAP               20.0f", "AIDR_GAP               21.0f"),
    AM("dr-gap-sign", "- (AIDR_GAP - nc->Position.y)", "- (AIDR_GAP + nc->Position.y)"),
    AM("dr-the-car", "nc->TheCar->State.VelocityMagnitude", "list->MyCar->State.VelocityMagnitude"),
    AM("dr-lower", "if (speed < a->Base.DesiredSpeed) {", "if (speed <= a->Base.DesiredSpeed) {"),
    AM("dr-lower-any", "if (speed < a->Base.DesiredSpeed) {", "if (1) {"),
    AM("dr-ds", "            a->Base.DesiredSpeed = speed;\n", ""),
    AM("dr-tt", "            a->Base.TimeToGetToDesiredSpeed = 0.0f;",
       "            a->Base.TimeToGetToDesiredSpeed = 1.0f;"),
    AM("dr-udl0", "            a->Base.TimeToGetToDesiredSpeed = 0.0f;\n            a->Base.UseDrivingLineSpeed = 0;",
       "            a->Base.TimeToGetToDesiredSpeed = 0.0f;\n            a->Base.UseDrivingLineSpeed = 1;"),
    AM("dr-pt", "    a->Base.PointsToDriveWillExecuteAction = 1;\n}\n\n// "
       "---------------------------------------------- NudgeCar",
       "    a->Base.PointsToDriveWillExecuteAction = 0;\n}\n\n// "
       "---------------------------------------------- NudgeCar"),
    AM("dr-dtor", "destroy_as(&a->Base, AIDRAFT_VTABLE, flags);",
       "destroy_as(&a->Base, AIDRAFT_VTABLE, 0);"),
    # NudgeCar and Block.
    AM("nc-type", "a->Base.Type = AIACTION_NUDGE_CAR;", "a->Base.Type = AIACTION_BLOCK;"),
    AM("nc-car", "a->CarToNudge = car;", "a->CarToNudge = NULL;"),
    AM("nc-vt", "    a->Base.Base._vtable = AINUDGECAR_VTABLE;",
       "    a->Base.Base._vtable = AIBLOCK_VTABLE;"),
    AM("bl-type", "a->Base.Type = AIACTION_BLOCK;", "a->Base.Type = AIACTION_NUDGE_CAR;"),
    AM("bl-car", "a->CarToBlock = car;", "a->CarToBlock = NULL;"),
    AM("bl-vt", "    a->Base.Base._vtable = AIBLOCK_VTABLE;",
       "    a->Base.Base._vtable = AINUDGECAR_VTABLE;"),
    AM("nc-score", "    return AINC_SCORE;", "    return AIBL_SCORE;"),
    AM("nc-out", "    *car = NULL;\n    return AINC_SCORE;", "    return AINC_SCORE;"),
    AM("bl-score", "    return AIBL_SCORE;", "    return AINC_SCORE;"),
    AM("bl-out", "    *car = NULL;\n    return AIBL_SCORE;", "    return AIBL_SCORE;"),
    AM("nc-acc", "    // 0x001c80e8.\n    (void)a;\n    (void)info;\n    return 1;",
       "    // 0x001c80e8.\n    (void)a;\n    (void)info;\n    return 0;"),
    AM("nc-fail", "    // 0x001c8148.\n    (void)a;\n    (void)info;\n    return 0;",
       "    // 0x001c8148.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("bl-acc", "    // 0x001c8220.\n    (void)a;\n    (void)info;\n    return 1;",
       "    // 0x001c8220.\n    (void)a;\n    (void)info;\n    return 0;"),
    AM("bl-fail", "    // 0x001c8280.\n    (void)a;\n    (void)info;\n    return 0;",
       "    // 0x001c8280.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("nc-exp", "    // 0x001c80f0.\n    (void)info;\n    return past_timeout_unstarted(&a->Base);",
       "    // 0x001c80f0.\n    (void)info;\n    return past_timeout(&a->Base.Base);"),
    AM("bl-exp", "    // 0x001c8228.\n    (void)info;\n    return past_timeout_unstarted(&a->Base);",
       "    // 0x001c8228.\n    (void)info;\n    return past_timeout(&a->Base.Base);"),
    AM("nc-pt", "    // 0x001c8150.\n    (void)info;\n    a->Base.PointsToDriveWillExecuteAction = 1;",
       "    // 0x001c8150.\n    (void)info;\n    a->Base.PointsToDriveWillExecuteAction = 0;"),
    AM("bl-pt", "    // 0x001c8288.\n    (void)info;\n    a->Base.PointsToDriveWillExecuteAction = 1;",
       "    // 0x001c8288.\n    (void)info;\n    a->Base.PointsToDriveWillExecuteAction = 0;"),
    AM("nc-dtor", "destroy_as(&a->Base, AINUDGECAR_VTABLE, flags);",
       "destroy_as(&a->Base, AINUDGECAR_VTABLE, 0);"),
    AM("bl-dtor", "destroy_as(&a->Base, AIBLOCK_VTABLE, flags);",
       "destroy_as(&a->Base, AIBLOCK_VTABLE, 0);"),
    # AccidentRecovery.
    AM("ar-vt", "    a->Base.Base._vtable = AIACCIDENTRECOVERY_VTABLE;",
       "    a->Base.Base._vtable = AIJUSTDRIVE_VTABLE;"),
    AM("ar-type", "a->Base.Type = AIACTION_ACCIDENT_RECOVERY;", "a->Base.Type = AIACTION_NONE;"),
    AM("ar-made", "AIACTION_ACCIDENT_RECOVERY;\n    a->MyCreationTime.PackedTime = (uint32_t)WorldTimer;\n",
       "AIACTION_ACCIDENT_RECOVERY;\n"),
    AM("ar-reset0", "    a->HaveResetYet = 0;\n    return a;", "    a->HaveResetYet = 1;\n    return a;"),
    AM("ar-score-nw", "if (car->State.nWheelsTouchingGround < 2)",
       "if (car->State.nWheelsTouchingGround <= 2)"),
    AM("ar-score-par", "crashed = !aiaccidentrecovery_sort_of_parallel_to_track(car,",
       "crashed = aiaccidentrecovery_sort_of_parallel_to_track(car,"),
    AM("ar-score-thr", "track(car,\n                                                                AIAR_UPRIGHT);",
       "track(car,\n                                                                0.5f);"),
    AM("ar-score", "return crashed ? AIAR_SCORE : AIA_NO_SCORE;",
       "return crashed ? AIA_NO_SCORE : AIAR_SCORE;"),
    AM("ar-upright", "AIAR_UPRIGHT           0.707000017f", "AIAR_UPRIGHT           0.7071f"),
    AM("ar-par-lt", "return threshold < (ux * normal.x", "return threshold <= (ux * normal.x"),
    AM("ar-par-norm", "    q = 1.0f / sqrtf(", "    q = 1.0f + 0.0f * sqrtf("),
    AM("ar-par-z", "+ uz * normal.z;", "+ uz * normal.y;"),
    AM("ar-par-found", "&terrain, &normal, NULL);", "&terrain, &normal, &terrain);"),
    AM("ar-acc-reset", "    if (a->HaveResetYet != 0)\n        return 1;",
       "    if (a->HaveResetYet != 0)\n        return 0;"),
    AM("ar-acc-nw", "if (car->State.nWheelsTouchingGround != 4)",
       "if (car->State.nWheelsTouchingGround < 4)"),
    AM("ar-acc-par", "AIAR_UPRIGHT)\n           != 0;", "AIAR_UPRIGHT)\n           == 0;"),
    AM("ar-fail", "    // 0x001ca430.\n    (void)a;\n    (void)info;\n    return 0;",
       "    // 0x001ca430.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("ar-exp", "    // 0x001ca3e8.\n    (void)info;\n    return past_timeout(&a->Base.Base);",
       "    // 0x001ca3e8.\n    (void)info;\n    return past_timeout_unstarted(&a->Base);"),
    AM("ar-cp-line", "    if (!drivingchoice_type_is_driving_line(choice->Type))\n        drivingchoice_set_choice_location",
       "    if (drivingchoice_type_is_driving_line(choice->Type))\n        drivingchoice_set_choice_location"),
    AM("ar-cp-move", "MOVEMENT_PARALLEL_TO_LINE);\n    a->Base.TimeToGetToDesiredSpeed",
       "MOVEMENT_TOWARDS_LINE);\n    a->Base.TimeToGetToDesiredSpeed"),
    AM("ar-tt", "    a->Base.TimeToGetToDesiredSpeed = 0.0f;\n    a->Base.UseDrivingLineSpeed = 0;",
       "    a->Base.TimeToGetToDesiredSpeed = 1.0f;\n    a->Base.UseDrivingLineSpeed = 0;"),
    AM("ar-udl", "    a->Base.UseDrivingLineSpeed = 0;\n    a->Base.DesiredSpeed = 0.0f;",
       "    a->Base.UseDrivingLineSpeed = 1;\n    a->Base.DesiredSpeed = 0.0f;"),
    AM("ar-ds", "    a->Base.DesiredSpeed = 0.0f;\n    a->Base.DesiredSpeedTolerance",
       "    a->Base.DesiredSpeed = 1.0f;\n    a->Base.DesiredSpeedTolerance"),
    AM("ar-tol", "    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.PointsToDriveWillExecuteAction = 1;\n    a->Base.AllowedToUseThrottleAndBrake = 0;",
       "    a->Base.DesiredSpeedTolerance = 1.0f;\n    a->Base.PointsToDriveWillExecuteAction = 1;\n    a->Base.AllowedToUseThrottleAndBrake = 0;"),
    AM("ar-pt", "    a->Base.PointsToDriveWillExecuteAction = 1;\n    a->Base.AllowedToUseThrottleAndBrake = 0;",
       "    a->Base.PointsToDriveWillExecuteAction = 0;\n    a->Base.AllowedToUseThrottleAndBrake = 0;"),
    AM("ar-tb", "    a->Base.PointsToDriveWillExecuteAction = 1;\n    a->Base.AllowedToUseThrottleAndBrake = 0;",
       "    a->Base.PointsToDriveWillExecuteAction = 1;\n    a->Base.AllowedToUseThrottleAndBrake = 1;"),
    AM("ar-after-le", "if (AIAR_RESET_AFTER <= seconds_since", "if (AIAR_RESET_AFTER < seconds_since"),
    AM("ar-after", "AIAR_RESET_AFTER       5.0f", "AIAR_RESET_AFTER       4.0f"),
    AM("ar-once", "\n        && a->HaveResetYet == 0) {", ") {"),
    AM("ar-reset-call", "        car_please_reset_me_later(info->MyNearbyCarList.MyCar);\n", ""),
    AM("ar-reset-set", "        a->HaveResetYet = 1;\n", ""),
    AM("ar-name", "\"Accident recovery\"", "\"Accident Recovery\""),
    AM("ar-dtor", "destroy_as(&a->Base, AIACCIDENTRECOVERY_VTABLE, flags);",
       "destroy_as(&a->Base, AIACCIDENTRECOVERY_VTABLE, 0);"),
    # The tables.
    AM("vt-jd-cptd", "E(aijustdrive_calculate_points_to_drive),   //  24",
       "E(aidraft_calculate_points_to_drive),   //  24"),
    AM("vt-dr-name", "E(aiaction_get_name),                       //  32  0x001caae0\n    E(aidraft",
       "E(aijustdrive_get_name),                       //  32  0x001caae0\n    E(aidraft"),
    AM("vt-dr-exp", "E(aidraft_has_expired),", "E(ainudgecar_has_expired),"),
    AM("vt-nc-acc", "E(ainudgecar_has_been_accomplished),", "E(ainudgecar_has_failed),"),
    AM("vt-bl-exp", "E(aiblock_has_expired),", "E(aidraft_has_expired),"),
    AM("vt-ar-acc", "E(aiaccidentrecovery_has_been_accomplished),", "E(aiaccidentrecovery_has_failed),"),
    AM("vt-ar-name", "E(aiaccidentrecovery_get_name),", "E(aiaction_get_name),"),
    AM("vt-install", "    vt_install(AIBLOCK_VTABLE, aiblock_vt, AIACTION_VT_ENTRIES);\n", ""),
    # Pass.
    AM("pa-amt", "    a->AmountToProjectIntoFuture = amount;\n", ""),
    AM("pa-car", "    a->CarToPass = car;\n    a->Base", "    a->CarToPass = NULL;\n    a->Base"),
    AM("pa-vt", "    a->Base.Base._vtable = AIPASS_VTABLE;",
       "    a->Base.Base._vtable = AIAVOIDCARS_VTABLE;"),
    AM("pa-made", "    a->MyCreationTime.PackedTime = (uint32_t)WorldTimer;\n    a->Base.Type = AIACTION_PASS;",
       "    a->Base.Type = AIACTION_PASS;"),
    AM("pa-type", "a->Base.Type = AIACTION_PASS;", "a->Base.Type = AIACTION_DRAFT;"),
    AM("pa-dtor", "destroy_as(&a->Base, AIPASS_VTABLE, flags);",
       "destroy_as(&a->Base, AIPASS_VTABLE, 0);"),
    AM("pa-sc-grace", "    if (race_grace_period_is_active(pCurrentRace, me))\n        return AIA_NO_SCORE;\n", ""),
    AM("pa-sc-n", "    n = nearbycarlist_get_cars_index_in_array(list, me);",
       "    n = list->NumCarsInArray;"),
    AM("pa-sc-found", "for (i = 0; i < n && !found; i++)", "for (i = 0; i < n; i++)"),
    AM("pa-sc-y", "        if (!(0.0f < nc->Position.y)\n", "        if (!(0.0f <= nc->Position.y)\n"),
    AM("pa-sc-x", "            || !(nc->Position.x < nc->Position.y + nc->Position.y)\n",
       "            || !(nc->Position.x < nc->Position.y)\n"),
    AM("pa-sc-x-abs", "            || !(nc->Position.x < nc->Position.y + nc->Position.y)\n",
       "            || !(fabsf(nc->Position.x) < nc->Position.y + nc->Position.y)\n"),
    AM("pa-sc-x-le", "            || !(nc->Position.x < nc->Position.y + nc->Position.y)\n",
       "            || !(nc->Position.x <= nc->Position.y + nc->Position.y)\n"),
    AM("pa-sc-catch", "            || !ai_can_i_catch_this_car(nc, me, maxAccel, 1))",
       "            || 0)"),
    AM("pa-sc-copy", "        *choice = info->MyDrivingChoice;\n        if (drivingchoice_try_to_drive_around_car(",
       "        if (drivingchoice_try_to_drive_around_car("),
    AM("pa-sc-time", "0.0f, AIActionPassMaxTimeAheadToMakeAttempt, 0.0f, 1)",
       "0.0f, AIDriverAvoidCarsImpactTimeThreshold, 0.0f, 1)"),
    AM("pa-sc-flag", "0.0f, AIActionPassMaxTimeAheadToMakeAttempt, 0.0f, 1)",
       "0.0f, AIActionPassMaxTimeAheadToMakeAttempt, 0.0f, 0)"),
    AM("pa-sc-side", "            && aipass_side_of_car_is_okay(nc, choice, preferred)) {",
       "            ) {"),
    AM("pa-sc-side-pref", "aipass_side_of_car_is_okay(nc, choice, preferred)",
       "aipass_side_of_car_is_okay(nc, choice, 1)"),
    AM("pa-sc-car", "            *car = nc->TheCar;\n            found = 1;", "            found = 1;"),
    AM("pa-score", "#define AIPA_SCORE   300", "#define AIPA_SCORE   200"),
    AM("pa-so-traffic", "    if (car->TheControlMode == TRAFFIC_CONTROL)\n        return 1;\n    if (!(TryTo",
       "    if (car->TheControlMode == REAL_CONTROL)\n        return 1;\n    if (!(TryTo"),
    AM("pa-so-speed", "    if (!(TryToDriveAroundCarMinSpeedForDrivingLine\n          < car->State.VelocityMagnitude))",
       "    if (!(TryToDriveAroundCarMinSpeedForDrivingLine\n          <= car->State.VelocityMagnitude))"),
    AM("pa-so-line", "    if (drivingchoice_type_is_driving_line(choice->Type))\n        return 1;\n    return preferred != 0;",
       "    return preferred != 0;"),
    AM("pa-so-pref", "    return preferred != 0;", "    return 0;"),
    AM("pa-acc-car", "list->Array[0].TheCar != a->CarToPass", "list->Array[0].TheCar == a->CarToPass"),
    AM("pa-acc-ge", "        if (aipass_calculate_score(info, &car, &c, &amount) >= 0\n",
       "        if (aipass_calculate_score(info, &car, &c, &amount) < 0\n"),
    AM("pa-acc-eq", "            && !drivingchoice_is_equal_to(&info->MyDrivingChoice, &c)) {",
       "            ) {"),
    AM("pa-acc-copy", "            info->MyDrivingChoice = c;\n            a->CarToPass = car;",
       "            a->CarToPass = car;"),
    AM("pa-acc-setcar", "            a->CarToPass = car;\n            a->MyCreationTime", "            a->MyCreationTime"),
    AM("pa-acc-made", "            a->MyCreationTime.PackedTime = (uint32_t)WorldTimer;\n        }\n    }",
       "        }\n    }"),
    AM("pa-settle", "#define AIPA_SETTLE            3.0f", "#define AIPA_SETTLE            2.5f"),
    AM("pa-acc-settle", "    if (!(seconds_since(&a->MyCreationTime) < AIPA_SETTLE)) {",
       "    if ((seconds_since(&a->MyCreationTime) < AIPA_SETTLE)) {"),
    AM("pa-acc-behind", "nc->Position.y < -((list->MyHalfSizeD + nc->ApparentHalfSizeD)",
       "nc->Position.y <= -((list->MyHalfSizeD + nc->ApparentHalfSizeD)"),
    AM("pa-acc-hd", "nc->Position.y < -((list->MyHalfSizeD + nc->ApparentHalfSizeD)",
       "nc->Position.y < -((list->MyHalfSizeL + nc->ApparentHalfSizeD)"),
    AM("pa-behind", "#define AIPA_BEHIND            10.0f", "#define AIPA_BEHIND            9.0f"),
    AM("pa-acc-relaxed", "            done = 1;\n    }\n    if (done)\n        drivinglocation_set_relaxed_switch(&info->MyDrivingLocation, 1);",
       "            done = 1;\n    }\n    if (done)\n        drivinglocation_set_relaxed_switch(&info->MyDrivingLocation, 0);"),
    AM("pa-fail-null", "    if (nc == NULL)\n        failed = 1;", "    if (nc == NULL)\n        failed = 0;"),
    AM("pa-fail-settle", "    else if (seconds_since(&a->MyCreationTime) < AIPA_SETTLE\n             && 0.0f < nc->Position.y)",
       "    else if (0.0f < nc->Position.y)"),
    AM("pa-fail-y", "             && 0.0f < nc->Position.y)", "             && 0.0f <= nc->Position.y)"),
    AM("pa-fail-catch", "        failed = !ai_can_i_catch_this_car(nc, list->MyCar, -1.0f, 0);",
       "        failed = ai_can_i_catch_this_car(nc, list->MyCar, -1.0f, 0);"),
    AM("pa-fail-relaxed", "    if (failed)\n        drivinglocation_set_relaxed_switch(&info->MyDrivingLocation, 1);",
       "    if (failed)\n        drivinglocation_set_relaxed_switch(&info->MyDrivingLocation, 0);"),
    AM("pa-exp", "    // 0x001c7d00.\n    (void)info;\n    return past_timeout(&a->Base.Base);",
       "    // 0x001c7d00.\n    (void)info;\n    return 0;"),
    AM("pa-cp-clear", "    drivetarget_clear(&a->Base.PointsToDrive, NULL, 0.0f);\n    a->Base.UseDrivingLineSpeed = 0;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.AllowedToUseBoost = 1;",
       "    a->Base.UseDrivingLineSpeed = 0;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.AllowedToUseBoost = 1;"),
    AM("pa-cp-tb", "    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.AllowedToUseBoost = 1;\n    a->Base.PointsToDriveWillExecuteAction = 1;\n    nc =",
       "    a->Base.AllowedToUseThrottleAndBrake = 0;\n    a->Base.AllowedToUseBoost = 1;\n    a->Base.PointsToDriveWillExecuteAction = 1;\n    nc ="),
    AM("pa-cp-bo", "    a->Base.AllowedToUseBoost = 1;\n    a->Base.PointsToDriveWillExecuteAction = 1;\n    nc =",
       "    a->Base.AllowedToUseBoost = 0;\n    a->Base.PointsToDriveWillExecuteAction = 1;\n    nc ="),
    AM("pa-cp-pt", "    a->Base.PointsToDriveWillExecuteAction = 1;\n    nc = nearbycarlist_get_nearby_car(list, a->CarToPass);",
       "    a->Base.PointsToDriveWillExecuteAction = 0;\n    nc = nearbycarlist_get_nearby_car(list, a->CarToPass);"),
    AM("pa-cp-y", "        if (0.0f < nc->Position.y) {\n            drivingchoice_try_to_drive_around_car(",
       "        if (0.0f <= nc->Position.y) {\n            drivingchoice_try_to_drive_around_car("),
    AM("pa-cp-time", "loc, list,\n                0.0f, AIDriverAvoidCarsImpactTimeThreshold, 0.0f, 1);",
       "loc, list,\n                0.0f, AIActionPassMaxTimeAheadToMakeAttempt, 0.0f, 1);"),
    AM("pa-cp-flag", "loc, list,\n                0.0f, AIDriverAvoidCarsImpactTimeThreshold, 0.0f, 1);",
       "loc, list,\n                0.0f, AIDriverAvoidCarsImpactTimeThreshold, 0.0f, 0);"),
    AM("pa-cp-setloc", "            if (!drivingchoice_type_is_driving_line(choice->Type))\n                drivingchoice_set_choice_location(choice, loc);\n            drivingchoice_is_driveable(",
       "            drivingchoice_is_driveable("),
    AM("pa-cp-drv-time", "                                       AIDriverAvoidCarsImpactTimeThreshold,\n                                       0.0f, MOVEMENT_PARALLEL_TO_LINE);",
       "                                       AIActionPassMaxTimeAheadToMakeAttempt,\n                                       0.0f, MOVEMENT_PARALLEL_TO_LINE);"),
    AM("pa-cp-drv-move", "                                       0.0f, MOVEMENT_PARALLEL_TO_LINE);",
       "                                       0.0f, MOVEMENT_TOWARDS_LINE);"),
    AM("pa-cp-drv-pref", "drivingchoice_is_driveable(choice, &a->Base.PointsToDrive, 0,\n",
       "drivingchoice_is_driveable(choice, &a->Base.PointsToDrive, 1,\n"),
    AM("pa-cp-udl", "        a->Base.UseDrivingLineSpeed = 1;\n    } else {",
       "        a->Base.UseDrivingLineSpeed = 0;\n    } else {"),
    AM("pa-cp-else-setloc", "    } else {\n        if (!drivingchoice_type_is_driving_line(choice->Type))\n            drivingchoice_set_choice_location(choice, loc);\n        drivingchoice_build_drive_target(choice, &a->Base.PointsToDrive, loc,\n                                         list, 0.0f, 0.0f,\n                                         MOVEMENT_PARALLEL_TO_LINE);\n        a->Base.UseDrivingLineSpeed = 1;",
       "    } else {\n        drivingchoice_build_drive_target(choice, &a->Base.PointsToDrive, loc,\n                                         list, 0.0f, 0.0f,\n                                         MOVEMENT_PARALLEL_TO_LINE);\n        a->Base.UseDrivingLineSpeed = 1;"),
    AM("pa-cp-else-move", "                                         MOVEMENT_PARALLEL_TO_LINE);\n        a->Base.UseDrivingLineSpeed = 1;\n        a->Base.PointsToDriveWillExecuteAction = 0;",
       "                                         MOVEMENT_TOWARDS_LINE);\n        a->Base.UseDrivingLineSpeed = 1;\n        a->Base.PointsToDriveWillExecuteAction = 0;"),
    AM("pa-cp-else-udl", "        a->Base.UseDrivingLineSpeed = 1;\n        a->Base.PointsToDriveWillExecuteAction = 0;",
       "        a->Base.UseDrivingLineSpeed = 0;\n        a->Base.PointsToDriveWillExecuteAction = 0;"),
    AM("pa-cp-else-pt", "        a->Base.PointsToDriveWillExecuteAction = 0;\n    }\n}",
       "        a->Base.PointsToDriveWillExecuteAction = 1;\n    }\n}"),
    AM("pa-name", "\"Pass\"", "\"pass\""),
    # AvoidCars.
    AM("ac-last", "    a->LastDecisionReevaluationTime.PackedTime = (uint32_t)WorldTimer;\n    a->CarToAvoid = car;",
       "    a->CarToAvoid = car;"),
    AM("ac-car", "    a->CarToAvoid = car;\n", "    a->CarToAvoid = NULL;\n"),
    AM("ac-okay", "    a->IsMyDrivingChoiceOkay = okay;", "    a->IsMyDrivingChoiceOkay = !okay;"),
    AM("ac-used", "    a->UsedPreferredSide = usedPreferred;", "    a->UsedPreferredSide = 0;"),
    AM("ac-secs", "    a->SecondsToImpact = secs;", "    a->SecondsToImpact = 0.0f;"),
    AM("ac-type", "a->Base.Type = AIACTION_AVOID_CARS;", "a->Base.Type = AIACTION_PASS;"),
    AM("ac-min", "    a->MinLifetime = secs + AIAC_MIN_LIFETIME;", "    a->MinLifetime = AIAC_MIN_LIFETIME;"),
    AM("ac-min-k", "#define AIAC_MIN_LIFETIME      2.0f", "#define AIAC_MIN_LIFETIME      2.5f"),
    AM("ac-made", "    a->MyCreationTime.PackedTime = (uint32_t)WorldTimer;\n    return a;\n}\n\nvoid aiavoidcars_destroy",
       "    return a;\n}\n\nvoid aiavoidcars_destroy"),
    AM("ac-vt", "    a->Base.Base._vtable = AIAVOIDCARS_VTABLE;", "    a->Base.Base._vtable = AIPASS_VTABLE;"),
    AM("ac-dtor", "destroy_as(&a->Base, AIAVOIDCARS_VTABLE, flags);",
       "destroy_as(&a->Base, AIAVOIDCARS_VTABLE, 0);"),
    AM("ac-nohit", "#define AIAC_NO_HIT            99999.0f", "#define AIAC_NO_HIT            9999.0f"),
    AM("pa-nohit", "#define AIPA_NO_HIT            99999.0f", "#define AIPA_NO_HIT            9999.0f"),
    AM("ac-sc-secs", "    *secs = AIAC_NO_HIT;\n", "    *secs = 0.0f;\n"),
    AM("ac-sc-okay0", "    *okay = 0;\n    *usedPreferred = 0;\n    hit", "    *usedPreferred = 0;\n    hit"),
    AM("ac-sc-used0", "    *usedPreferred = 0;\n    hit", "    hit"),
    AM("ac-sc-time", "        &list->MyCar->pCarDriver->MyDriveTarget, list, loc,\n        AIDriverAvoidCarsImpactTimeThreshold, &hitTime);",
       "        &list->MyCar->pCarDriver->MyDriveTarget, list, loc,\n        AIActionPassMaxTimeAheadToMakeAttempt, &hitTime);"),
    AM("ac-sc-null", "    if (hit != NULL && hitTime < AIDriverAvoidCarsImpactTimeThreshold) {",
       "    if (hitTime < AIDriverAvoidCarsImpactTimeThreshold) {"),
    AM("ac-sc-lt", "    if (hit != NULL && hitTime < AIDriverAvoidCarsImpactTimeThreshold) {",
       "    if (hit != NULL && hitTime <= AIDriverAvoidCarsImpactTimeThreshold) {"),
    AM("ac-sc-car", "        *car = hit;\n", ""),
    AM("ac-sc-secsout", "        *secs = hitTime;\n", ""),
    AM("ac-sc-grace", "        grace = race_grace_period_is_active(pCurrentRace, list->MyCar);",
       "        grace = 0;"),
    AM("ac-sc-copy", "        *choice = info->MyDrivingChoice;\n        if (grace", "        if (grace"),
    AM("ac-sc-player", "        if (grace && hit->pPlayer == NULL) {", "        if (grace) {"),
    AM("ac-sc-okay1", "            *okay = 1;\n            *usedPreferred = 0;\n        } else {",
       "            *okay = 0;\n            *usedPreferred = 0;\n        } else {"),
    AM("ac-sc-used1", "            *okay = 1;\n            *usedPreferred = 0;\n        } else {",
       "            *okay = 1;\n        } else {"),
    AM("ac-sc-mnc-time", "                choice, &t, loc, list, AIDriverAvoidCarsImpactTimeThreshold,\n                0.0f, usedPreferred, 1);",
       "                choice, &t, loc, list, AIActionPassMaxTimeAheadToMakeAttempt,\n                0.0f, usedPreferred, 1);"),
    AM("ac-sc-mnc-flag", "                0.0f, usedPreferred, 1);", "                0.0f, usedPreferred, 0);"),
    AM("ac-score", "#define AIAC_SCORE   400", "#define AIAC_SCORE   300"),
    AM("ac-acc-le", "    int done = !(seconds_since(&a->MyCreationTime) <= a->MinLifetime);",
       "    int done = !(seconds_since(&a->MyCreationTime) < a->MinLifetime);"),
    AM("ac-acc-relaxed", "    if (done)\n        drivinglocation_set_relaxed_switch(&info->MyDrivingLocation, 1);\n    return done;\n}\n\nint aiavoidcars_has_failed",
       "    if (done)\n        drivinglocation_set_relaxed_switch(&info->MyDrivingLocation, 0);\n    return done;\n}\n\nint aiavoidcars_has_failed"),
    AM("ac-fail", "    // 0x001c6ef0.\n    (void)a;\n    (void)info;\n    return 0;",
       "    // 0x001c6ef0.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("ac-exp", "    // 0x001c6ee8.\n    (void)a;\n    (void)info;\n    return 0;",
       "    // 0x001c6ee8.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("ac-cp-assign", "    drivetarget_assign(&a->Base.PointsToDrive, &me->pCarDriver->MyDriveTarget);\n    a->Base.DesiredSpeedTolerance = 0.0f;\n",
       "    a->Base.DesiredSpeedTolerance = 0.0f;\n"),
    AM("ac-cp-tol", "    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.UseDrivingLineSpeed = 1;\n    // Asked",
       "    a->Base.DesiredSpeedTolerance = 1.0f;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.UseDrivingLineSpeed = 1;\n    // Asked"),
    AM("ac-cp-tb", "    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.UseDrivingLineSpeed = 1;\n    // Asked",
       "    a->Base.AllowedToUseThrottleAndBrake = 0;\n    a->Base.UseDrivingLineSpeed = 1;\n    // Asked"),
    AM("ac-cp-udl", "    a->Base.UseDrivingLineSpeed = 1;\n    // Asked", "    a->Base.UseDrivingLineSpeed = 0;\n    // Asked"),
    AM("ac-cp-slow-me", "me->State.VelocityMagnitude < AIAC_SLOW_ME", "me->State.VelocityMagnitude <= AIAC_SLOW_ME"),
    AM("ac-cp-slow-it", "ncAvoid->TheCar->State.VelocityMagnitude < AIAC_SLOW_IT",
       "ncAvoid->TheCar->State.VelocityMagnitude <= AIAC_SLOW_IT"),
    AM("ac-cp-slow-me-k", "#define AIAC_SLOW_ME           10.0f", "#define AIAC_SLOW_ME           12.0f"),
    AM("ac-cp-slow-it-k", "#define AIAC_SLOW_IT           5.0f", "#define AIAC_SLOW_IT           6.0f"),
    AM("ac-cp-slow-mine", "me->State.VelocityMagnitude < AIAC_SLOW_ME", "ncAvoid->TheCar->State.VelocityMagnitude < AIAC_SLOW_ME"),
    AM("ac-cp-grace", "    reevaluate = !race_grace_period_is_active(pCurrentRace, me)\n                 || a->CarToAvoid->pPlayer != NULL;",
       "    reevaluate = 1;"),
    AM("ac-cp-player", "                 || a->CarToAvoid->pPlayer != NULL;", "                 || a->CarToAvoid->pPlayer == NULL;"),
    AM("ac-cp-every", "    if (!(AIAC_REEVALUATE_EVERY\n          < seconds_since(&a->LastDecisionReevaluationTime)))",
       "    if (!(AIAC_REEVALUATE_EVERY\n          <= seconds_since(&a->LastDecisionReevaluationTime)))"),
    AM("ac-cp-every-k", "#define AIAC_REEVALUATE_EVERY  0.300000012f", "#define AIAC_REEVALUATE_EVERY  0.5f"),
    AM("ac-cp-every-off", "        reevaluate = 0;\n", ""),
    AM("ac-cp-line-slow", "        if (drivingchoice_type_is_driving_line(choice->Type) && slow) {",
       "        if (slow) {"),
    AM("ac-cp-line-only", "        if (drivingchoice_type_is_driving_line(choice->Type) && slow) {",
       "        if (drivingchoice_type_is_driving_line(choice->Type) && slow && 0) {"),
    AM("ac-cp-left", "            drivingchoice_set_choice(choice, CHOICE_LEFT_SIDE_OF_CAR,\n",
       "            drivingchoice_set_choice(choice, CHOICE_RIGHT_SIDE_OF_CAR,\n"),
    AM("ac-cp-room", "            if (!drivingchoice_is_enough_room(choice, ncAvoid, list))",
       "            if (drivingchoice_is_enough_room(choice, ncAvoid, list))"),
    AM("ac-cp-right", "                drivingchoice_set_choice(choice, CHOICE_RIGHT_SIDE_OF_CAR,\n",
       "                drivingchoice_set_choice(choice, CHOICE_LEFT_SIDE_OF_CAR,\n"),
    AM("ac-cp-used0", "        a->UsedPreferredSide = 0;\n        a->IsMyDrivingChoiceOkay = drivingchoice_make_new_choice(",
       "        a->IsMyDrivingChoiceOkay = drivingchoice_make_new_choice("),
    AM("ac-cp-mnc-time", "            AIDriverAvoidCarsImpactTimeThreshold, 0.0f, &used, 1);",
       "            AIActionPassMaxTimeAheadToMakeAttempt, 0.0f, &used, 1);"),
    AM("ac-cp-mnc-flag", "0.0f, &used, 1);", "0.0f, &used, 0);"),
    AM("ac-cp-used-copy", "        a->UsedPreferredSide = used;\n", ""),
    AM("ac-cp-mnc-okay", "        a->UsedPreferredSide = 0;\n        a->IsMyDrivingChoiceOkay = drivingchoice_make_new_choice(",
       "        a->UsedPreferredSide = 0;\n        a->IsMyDrivingChoiceOkay = !drivingchoice_make_new_choice("),
    AM("ac-cp-change", "            if (drivingchoice_get_driving_line(choice->Type, me)\n                != loc->DrivingLine) {",
       "            if (1) {"),
    AM("ac-cp-setline", "                    loc, drivingchoice_get_driving_line(choice->Type, me), 0);",
       "                    loc, drivingchoice_get_driving_line(choice->Type, me), 1);"),
    AM("ac-cp-highlight", "                ai_highlight_driving_line(loc, driver_number(me));\n", ""),
    AM("ac-cp-nc-null", "            ncChoice = NULL;\n", ""),
    AM("ac-cp-side", "        } else if (drivingchoice_type_is_side_of_car(choice->Type)) {\n            ncChoice = nearbycarlist_get_nearby_car(list, choice->pCar);\n        }",
       "        }"),
    AM("ac-cp-last", "        a->LastDecisionReevaluationTime.PackedTime = (uint32_t)WorldTimer;\n    }",
       "    }"),
    AM("ac-cp-stand-pts", "    if (!(a->Base.PointsToDrive.NumPoints != 0 && choice->Type != CHOICE_NONE\n          && reevaluate)) {",
       "    if (!(choice->Type != CHOICE_NONE\n          && reevaluate)) {"),
    AM("ac-cp-stand-none", "    if (!(a->Base.PointsToDrive.NumPoints != 0 && choice->Type != CHOICE_NONE\n          && reevaluate)) {",
       "    if (!(a->Base.PointsToDrive.NumPoints != 0\n          && reevaluate)) {"),
    AM("ac-cp-stand-re", "    if (!(a->Base.PointsToDrive.NumPoints != 0 && choice->Type != CHOICE_NONE\n          && reevaluate)) {",
       "    if (!(a->Base.PointsToDrive.NumPoints != 0 && choice->Type != CHOICE_NONE)) {"),
    AM("ac-cp-none", "        if (choice->Type == CHOICE_NONE\n            || !drivingchoice_is_valid(choice, loc, list)) {",
       "        if (!drivingchoice_is_valid(choice, loc, list)) {"),
    AM("ac-cp-valid", "        if (choice->Type == CHOICE_NONE\n            || !drivingchoice_is_valid(choice, loc, list)) {",
       "        if (choice->Type == CHOICE_NONE) {"),
    AM("ac-cp-setloc", "            a->IsMyDrivingChoiceOkay = 0;\n            drivingchoice_set_choice_location(choice, loc);\n",
       "            a->IsMyDrivingChoiceOkay = 0;\n"),
    AM("ac-cp-drv-used", "            choice, &a->Base.PointsToDrive, a->UsedPreferredSide, &score,",
       "            choice, &a->Base.PointsToDrive, 0, &score,"),
    AM("ac-cp-drv-move", "            AIDriverAvoidCarsImpactTimeThreshold, 0.0f, MOVEMENT_TOWARDS_LINE);",
       "            AIDriverAvoidCarsImpactTimeThreshold, 0.0f, MOVEMENT_PARALLEL_TO_LINE);"),
    AM("ac-cp-drv-time", "            AIDriverAvoidCarsImpactTimeThreshold, 0.0f, MOVEMENT_TOWARDS_LINE);",
       "            AIActionPassMaxTimeAheadToMakeAttempt, 0.0f, MOVEMENT_TOWARDS_LINE);"),
    AM("ac-cp-zero", "        if (a->Base.PointsToDrive.NumPoints == 0) {", "        if (a->Base.PointsToDrive.NumPoints < 0) {"),
    AM("ac-cp-build-move", "                                             MOVEMENT_PARALLEL_TO_LINE);\n            a->IsMyDrivingChoiceOkay = 0;",
       "                                             MOVEMENT_TOWARDS_LINE);\n            a->IsMyDrivingChoiceOkay = 0;"),
    AM("ac-cp-build-okay", "                                             MOVEMENT_PARALLEL_TO_LINE);\n            a->IsMyDrivingChoiceOkay = 0;",
       "                                             MOVEMENT_PARALLEL_TO_LINE);"),
    AM("ac-cp-close-okay", "    if (!a->IsMyDrivingChoiceOkay\n        && (ai_do_we_care", "    if (1\n        && (ai_do_we_care"),
    AM("ac-cp-care-avoid", "        && (ai_do_we_care_about_this_car(ncAvoid, list)\n            || ai_do_we_care_about_this_car(ncChoice, list))",
       "        && (ai_do_we_care_about_this_car(ncChoice, list))"),
    AM("ac-cp-care-choice", "        && (ai_do_we_care_about_this_car(ncAvoid, list)\n            || ai_do_we_care_about_this_car(ncChoice, list))",
       "        && (ai_do_we_care_about_this_car(ncAvoid, list))"),
    AM("ac-cp-blink", "        && ncAvoid != NULL && !car_is_blinking(ncAvoid->TheCar)) {",
       "        && ncAvoid != NULL) {"),
    AM("ac-cp-real", "        if (car->TheControlMode == REAL_CONTROL)", "        if (car->TheControlMode == TRAFFIC_CONTROL)"),
    AM("ac-cp-half", "            close = list->MyHalfSizeD * AIAC_HALF\n                    < ncAvoid->Position.y",
       "            close = list->MyHalfSizeD * AIAC_HALF\n                    <= ncAvoid->Position.y"),
    AM("ac-cp-half-l", "            close = list->MyHalfSizeD * AIAC_HALF", "            close = list->MyHalfSizeL * AIAC_HALF"),
    AM("ac-cp-half-k", "#define AIAC_HALF              0.5f", "#define AIAC_HALF              0.6f"),
    AM("ac-cp-look-k", "#define AIAC_LOOK_AHEAD        0.100000001f", "#define AIAC_LOOK_AHEAD        0.2f"),
    AM("ac-cp-look-x", "+ ncAvoid->Velocity.y * AIAC_LOOK_AHEAD;", "+ ncAvoid->Velocity.x * AIAC_LOOK_AHEAD;"),
    AM("ac-cp-ahead", "            close = 0.0f < ncAvoid->Position.y;", "            close = 0.0f <= ncAvoid->Position.y;"),
    AM("ac-cp-across", "        if (!(fabsf(ncAvoid->Position.x)\n              < (list->MyHalfSizeL",
       "        if (!(fabsf(ncAvoid->Position.x)\n              <= (list->MyHalfSizeL"),
    AM("ac-cp-across-abs", "        if (!(fabsf(ncAvoid->Position.x)\n", "        if (!((ncAvoid->Position.x)\n"),
    AM("ac-cp-across-hl", "              < (list->MyHalfSizeL + ncAvoid->ApparentHalfSizeL)",
       "              < (list->MyHalfSizeL + ncAvoid->ApparentHalfSizeD)"),
    AM("ac-cp-across-k", "#define AIAC_ACROSS_MARGIN     1.0f", "#define AIAC_ACROSS_MARGIN     2.0f"),
    AM("ac-cp-across-player", "            && car->pPlayer == NULL)\n            close = 0;", "            )\n            close = 0;"),
    AM("ac-cp-udl0", "            a->Base.UseDrivingLineSpeed = 0;\n            if (slow)",
       "            a->Base.UseDrivingLineSpeed = 1;\n            if (slow)"),
    AM("ac-cp-slow-udl", "            if (slow)\n                a->Base.UseDrivingLineSpeed = 1;",
       "            if (slow)\n                a->Base.UseDrivingLineSpeed = 0;"),
    AM("ac-cp-slower-a", "                    &a->Base, ncAvoid, list, AIAC_SLOWER_BY, AIAC_SLOWER_BY);",
       "                    &a->Base, ncAvoid, list, 0.0f, AIAC_SLOWER_BY);"),
    AM("ac-cp-slower-b", "                    &a->Base, ncAvoid, list, AIAC_SLOWER_BY, AIAC_SLOWER_BY);",
       "                    &a->Base, ncAvoid, list, AIAC_SLOWER_BY, 0.0f);"),
    AM("ac-cp-slower-k", "#define AIAC_SLOWER_BY         0.100000001f", "#define AIAC_SLOWER_BY         0.2f"),
    AM("ac-cp-traffic", "            if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n                || car->MyDriver->TheDriverType == DRIVER_TYPE_COP)",
       "            if (car->MyDriver->TheDriverType == DRIVER_TYPE_COP)"),
    AM("ac-cp-cop", "            if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n                || car->MyDriver->TheDriverType == DRIVER_TYPE_COP)",
       "            if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)"),
    AM("ac-cp-min-k", "#define AIAC_MIN_SPEED_BEHIND  20.0f", "#define AIAC_MIN_SPEED_BEHIND  25.0f"),
    AM("ac-cp-max", "    return fs < ft ? ft : fs;", "    return fs < ft ? fs : ft;"),
    AM("ac-cp-pt", "    a->Base.PointsToDriveWillExecuteAction = 1;\n}\n\nconst char *aiavoidcars_get_name",
       "    a->Base.PointsToDriveWillExecuteAction = 0;\n}\n\nconst char *aiavoidcars_get_name"),
    AM("ac-name", "\"Avoid Cars\"", "\"Avoid cars\""),
    AM("ac-ga", "    // 0x001ca9e8.\n    return a->CarToAvoid;", "    // 0x001ca9e8.\n    return NULL;"),
    AM("ac-dnum", "    return ((CarDriverNumberFn)e->fn)(vt_this(d, e));", "    (void)e;\n    return car->DriverNumber;"),
    AM("vt-pa-acc", "E(aipass_has_been_accomplished),            //  40", "E(aipass_has_failed),            //  40"),
    AM("vt-pa-exp", "E(aipass_has_expired),                      //  56", "E(aiavoidcars_has_expired),                      //  56"),
    AM("vt-ac-cptd", "E(aiavoidcars_calculate_points_to_drive),   //  24", "E(aipass_calculate_points_to_drive),   //  24"),
    AM("vt-ac-name", "E(aiavoidcars_get_name),                    //  32", "E(aiaction_get_name),                    //  32"),
    AM("vt-ac-fail", "E(aiavoidcars_has_failed),                  //  48", "E(aiavoidcars_has_been_accomplished),                  //  48"),
    AM("vt-install-pa", "    vt_install(AIPASS_VTABLE, aipass_vt, AIACTION_VT_ENTRIES);\n", ""),
    # -- Step 11d-3a's: PullOver -------------------------------------------
    AM("po-chop-k", "#define AIPO_CHOPPER_RANGE     150.0f", "#define AIPO_CHOPPER_RANGE     151.0f"),
    AM("po-lsec-k", "#define AIPO_LIGHTS_SECONDS    3.5f", "#define AIPO_LIGHTS_SECONDS    3.6f"),
    AM("po-lmin-k", "#define AIPO_LIGHTS_MIN        100.0f", "#define AIPO_LIGHTS_MIN        101.0f"),
    AM("po-nto-k", "#define AIPO_NO_TIMEOUT        (-999.0f)", "#define AIPO_NO_TIMEOUT        (-998.0f)"),
    AM("po-eps-k", "#define AIPO_TIMEOUT_EPSILON   0.00100000005f", "#define AIPO_TIMEOUT_EPSILON   0.002f"),
    AM("po-every-k", "#define AIPO_REEVALUATE_EVERY  0.300000012f", "#define AIPO_REEVALUATE_EVERY  0.5f"),
    AM("po-soon-k", "#define AIPO_HIT_SOON          2.0f", "#define AIPO_HIT_SOON          2.5f"),
    AM("po-gentle-k", "#define AIPO_GENTLE            0.120000005f", "#define AIPO_GENTLE            0.13f"),
    AM("po-firm-k", "#define AIPO_FIRM              0.200000003f", "#define AIPO_FIRM              0.25f"),
    AM("po-fast-k", "#define AIPO_TOO_FAST          15.0f", "#define AIPO_TOO_FAST          16.0f"),
    AM("po-low-k", "#define AIPO_ROOM_LOW          2.0f", "#define AIPO_ROOM_LOW          2.5f"),
    AM("po-high-k", "#define AIPO_ROOM_HIGH         4.0f", "#define AIPO_ROOM_HIGH         4.5f"),
    AM("po-creep-k", "#define AIPO_CREEP_SPEED       14.0f", "#define AIPO_CREEP_SPEED       13.0f"),
    AM("po-tol-k", "#define AIPO_TOLERANCE         2.0f", "#define AIPO_TOLERANCE         3.0f"),
    AM("po-stopped-k", "#define AIPO_STOPPED           0.5f", "#define AIPO_STOPPED           0.6f"),
    AM("po-tts-k", "#define AIPO_TIME_TO_SPEED     0.200000003f", "#define AIPO_TIME_TO_SPEED     0.3f"),
    AM("po-careful-k", "#define AIPO_CAREFUL_SKILL     (-2)", "#define AIPO_CAREFUL_SKILL     (-1)"),
    AM("po-score-k", "#define AIPO_SCORE   600", "#define AIPO_SCORE   500"),
    AM("po-brake-clear-k", "AIPO_BRAKE);\n        } else {\n            int stop;", "0.25f);\n        } else {\n            int stop;"),
    AM("po-brake-stop-k", "AIPO_BRAKE);\n            else\n", "0.25f);\n            else\n"),
    AM("po-made", "    a->MyCreationTime.PackedTime = (uint32_t)WorldTimer;\n    a->IsMyDrivingChoiceOkay = 1;\n",
       "    a->IsMyDrivingChoiceOkay = 1;\n"),
    AM("po-okay0", "    a->IsMyDrivingChoiceOkay = 1;\n    a->PullOverTimeout = pullOverTimeout;",
       "    a->IsMyDrivingChoiceOkay = 0;\n    a->PullOverTimeout = pullOverTimeout;"),
    AM("po-ctor-pot","    a->PullOverTimeout = pullOverTimeout;", "    a->PullOverTimeout = timeout;"),
    AM("po-ctor-list", "    if (list != NULL && loc != NULL)\n        a->New620", "    if (loc != NULL)\n        a->New620"),
    AM("po-ctor-loc", "    if (list != NULL && loc != NULL)\n        a->New620", "    if (list != NULL)\n        a->New620"),
    AM("po-ctor-lt", "        a->New620 = AIPO_ROOM_LOW < room_to_the_right_edge(list,",
       "        a->New620 = AIPO_ROOM_LOW <= room_to_the_right_edge(list,"),
    AM("po-ctor-else", "    else\n        a->New620 = 1;\n", "    else\n        a->New620 = 0;\n"),
    AM("po-ctor-last", "    a->LastDecisionReevaluationTime.PackedTime = 0;\n    drivetarget_clear(&a->Base.PointsToDrive, NULL, 0.0f);\n    return a;",
       "    a->LastDecisionReevaluationTime.PackedTime = (uint32_t)WorldTimer;\n    drivetarget_clear(&a->Base.PointsToDrive, NULL, 0.0f);\n    return a;"),
    AM("po-ctor-clear", "    drivetarget_clear(&a->Base.PointsToDrive, NULL, 0.0f);\n    return a;\n}\n\nvoid aipullover_destroy",
       "    return a;\n}\n\nvoid aipullover_destroy"),
    AM("po-type", "a->Base.Type = AIACTION_PULL_OVER;", "a->Base.Type = AIACTION_PASS;"),
    AM("po-vt", "    a->Base.Base._vtable = AIPULLOVER_VTABLE;", "    a->Base.Base._vtable = AIPASS_VTABLE;"),
    AM("po-dtor", "destroy_as(&a->Base, AIPULLOVER_VTABLE, flags);", "destroy_as(&a->Base, AIPULLOVER_VTABLE, 0);"),
    AM("po-room-hl", "    return (rp->RightWidth - list->MyHalfSizeL)", "    return (rp->RightWidth - list->MyHalfSizeD)"),
    AM("po-room-rw", "    return (rp->RightWidth - list->MyHalfSizeL)", "    return (rp->LeftWidth - list->MyHalfSizeL)"),
    AM("po-room-x", "- ((me->State.Position.x - rp->Position.x) * rp->Direction.y",
       "- ((me->State.Position.x - rp->Position.x) * rp->Direction.x"),
    AM("po-room-y", "- (me->State.Position.y - rp->Position.y) * rp->Direction.x);",
       "- (me->State.Position.y - rp->Position.y) * rp->Direction.y);"),
    AM("po-room-sign", "           - ((me->State.Position.x - rp->Position.x)", "           + ((me->State.Position.x - rp->Position.x)"),
    AM("po-room-assoc", "    return (rp->RightWidth - list->MyHalfSizeL)\n           - ((me->State.Position.x - rp->Position.x) * rp->Direction.y\n              - (me->State.Position.y - rp->Position.y) * rp->Direction.x);",
       "    return rp->RightWidth - (list->MyHalfSizeL\n           + ((me->State.Position.x - rp->Position.x) * rp->Direction.y\n              - (me->State.Position.y - rp->Position.y) * rp->Direction.x));"),
    AM("po-word", "    return (p[0] | p[1] | p[2] | p[3]) != 0;", "    return p[0] != 0;"),
    AM("po-word-3", "    return (p[0] | p[1] | p[2] | p[3]) != 0;", "    return (p[0] | p[1] | p[2]) != 0;"),
    AM("po-lights-off", "    if (!cop_lights_word(c))\n        return 0;\n", ""),
    AM("po-lights-le", "    return sqrtf(dx * dx + dy * dy) <= range;", "    return sqrtf(dx * dx + dy * dy) < range;"),
    AM("po-lights-max", "    float range = max_s(c->State.VelocityMagnitude * AIPO_LIGHTS_SECONDS,\n                        AIPO_LIGHTS_MIN);",
       "    float range = c->State.VelocityMagnitude * AIPO_LIGHTS_SECONDS;"),
    AM("po-lights-me", "    dx = c->State.Position.x - me->State.Position.x;", "    dx = c->State.Position.x - me->State.Position.y;"),
    AM("po-sc-ctl", "    if (me->TheControlMode != TRAFFIC_CONTROL)\n        return AIA_NO_SCORE;\n    h = ", "    h = "),
    AM("po-sc-heli", "    h = pCurrentWorld->Helicopter;", "    h = NULL;"),
    AM("po-sc-plan3", "&& ((uint32_t)h->Plan < 3u || h->Plan == CHOPPLAN_BOMBING_RUN)) {",
       "&& ((uint32_t)h->Plan < 2u || h->Plan == CHOPPLAN_BOMBING_RUN)) {"),
    AM("po-sc-plan-signed", "&& ((uint32_t)h->Plan < 3u || h->Plan == CHOPPLAN_BOMBING_RUN)) {",
       "&& (h->Plan < 3 || h->Plan == CHOPPLAN_BOMBING_RUN)) {"),
    AM("po-sc-plan4", "&& ((uint32_t)h->Plan < 3u || h->Plan == CHOPPLAN_BOMBING_RUN)) {",
       "&& ((uint32_t)h->Plan < 3u)) {"),
    AM("po-sc-chop-le", "        if (sqrtf(dx * dx + dy * dy) <= AIPO_CHOPPER_RANGE)", "        if (sqrtf(dx * dx + dy * dy) < AIPO_CHOPPER_RANGE)"),
    AM("po-sc-chop-dy", "        float dy = h->CurrentPos.y - me->State.Position.y;", "        float dy = h->CurrentPos.x - me->State.Position.y;"),
    AM("po-sc-chop-near", "            near = 1;\n    }\n    if (pCopManager != NULL) {", "            near = 0;\n    }\n    if (pCopManager != NULL) {"),
    AM("po-sc-copm", "    if (pCopManager != NULL) {\n        const tCopManagerHead", "    if (1) {\n        const tCopManagerHead"),
    AM("po-sc-ncops", "        for (i = 0; i < m->nNumAICops && !near; i++) {", "        for (i = 0; i < m->nNumCops && !near; i++) {"),
    AM("po-sc-ncops-1", "        for (i = 0; i < m->nNumAICops && !near; i++) {", "        for (i = 1; i < m->nNumAICops && !near; i++) {"),
    AM("po-sc-cop-null", "            if (cop == NULL || cop->DesiredLogicState == LS_DISABLED)",
       "            if (cop->DesiredLogicState == LS_DISABLED)"),
    AM("po-sc-disabled", "            if (cop == NULL || cop->DesiredLogicState == LS_DISABLED)",
       "            if (cop == NULL || cop->LogicState == LS_DISABLED)"),
    AM("po-sc-disabled-k", "            if (cop == NULL || cop->DesiredLogicState == LS_DISABLED)",
       "            if (cop == NULL || cop->DesiredLogicState == LS_LIMBO)"),
    AM("po-sc-cop-car", "            if (cop_lights_in_range(cop->pMyCar, me))", "            if (cop_lights_in_range(me, me))"),
    AM("po-sc-players", "    for (i = 0; i < PlayerNumPlayers && !near; i++)", "    for (i = 1; i < PlayerNumPlayers && !near; i++)"),
    AM("po-sc-players-n", "    for (i = 0; i < PlayerNumPlayers && !near; i++)", "    for (i = 0; i < PlayerNumPlayers - 1 && !near; i++)"),
    AM("po-sc-player-car", "        if (cop_lights_in_range(PlayerPlayersByIndex[i]->MyCar, me))",
       "        if (cop_lights_in_range(PlayerPlayersByIndex[0]->MyCar, me))"),
    AM("po-sc-ret", "    return near ? AIPO_SCORE : AIA_NO_SCORE;", "    return near ? AIIJ_SCORE : AIA_NO_SCORE;"),
    AM("po-acc-ctl", "    if (info->MyNearbyCarList.MyCar->TheControlMode != TRAFFIC_CONTROL)\n        return 0;\n    return aipullover_calculate_score(info) == AIA_NO_SCORE;",
       "    return aipullover_calculate_score(info) == AIA_NO_SCORE;"),
    AM("po-acc-eq", "    return aipullover_calculate_score(info) == AIA_NO_SCORE;", "    return aipullover_calculate_score(info) != AIA_NO_SCORE;"),
    AM("po-fail", "    // 0x001c8658.\n    (void)a;\n    (void)info;\n    return 0;", "    // 0x001c8658.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("po-exp", "    // 0x001c8650.\n    (void)a;\n    (void)info;\n    return 0;", "    // 0x001c8650.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("po-cp-assign", "    drivetarget_assign(&a->Base.PointsToDrive, &me->pCarDriver->MyDriveTarget);\n    a->Base.UseDrivingLineSpeed = 0;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.AllowedToUseBoost = 0;\n    careful",
       "    a->Base.UseDrivingLineSpeed = 0;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.AllowedToUseBoost = 0;\n    careful"),
    AM("po-cp-udl", "    a->Base.UseDrivingLineSpeed = 0;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.AllowedToUseBoost = 0;\n    careful",
       "    a->Base.UseDrivingLineSpeed = 1;\n    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.AllowedToUseBoost = 0;\n    careful"),
    AM("po-cp-tb", "    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.AllowedToUseBoost = 0;\n    careful",
       "    a->Base.AllowedToUseThrottleAndBrake = 0;\n    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.AllowedToUseBoost = 0;\n    careful"),
    AM("po-cp-tol", "    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.AllowedToUseBoost = 0;\n    careful",
       "    a->Base.DesiredSpeedTolerance = 1.0f;\n    a->Base.AllowedToUseBoost = 0;\n    careful"),
    AM("po-cp-boost", "    a->Base.AllowedToUseBoost = 0;\n    careful", "    a->Base.AllowedToUseBoost = 1;\n    careful"),
    AM("po-cp-careful", "    careful = me->MyDriver->SkillLevel == AIPO_CAREFUL_SKILL;", "    careful = 0;"),
    AM("po-cp-careful-all", "    careful = me->MyDriver->SkillLevel == AIPO_CAREFUL_SKILL;", "    careful = 1;"),
    AM("po-cp-nto-le", "    if (fabsf(a->PullOverTimeout - AIPO_NO_TIMEOUT) <= AIPO_TIMEOUT_EPSILON",
       "    if (fabsf(a->PullOverTimeout - AIPO_NO_TIMEOUT) < AIPO_TIMEOUT_EPSILON"),
    AM("po-cp-nto-abs", "    if (fabsf(a->PullOverTimeout - AIPO_NO_TIMEOUT) <= AIPO_TIMEOUT_EPSILON",
       "    if ((a->PullOverTimeout - AIPO_NO_TIMEOUT) <= AIPO_TIMEOUT_EPSILON"),
    AM("po-cp-nto-off", "    if (fabsf(a->PullOverTimeout - AIPO_NO_TIMEOUT) <= AIPO_TIMEOUT_EPSILON\n        || ",
       "    if (0\n        || "),
    AM("po-cp-secs-lt", "        || seconds_since(&a->MyCreationTime) < a->PullOverTimeout) {",
       "        || seconds_since(&a->MyCreationTime) <= a->PullOverTimeout) {"),
    AM("po-cp-secs-made", "        || seconds_since(&a->MyCreationTime) < a->PullOverTimeout) {",
       "        || seconds_since(&a->LastDecisionReevaluationTime) < a->PullOverTimeout) {"),
    AM("po-cp-every-lt", "        if (AIPO_REEVALUATE_EVERY\n                < seconds_since(&a->LastDecisionReevaluationTime)",
       "        if (AIPO_REEVALUATE_EVERY\n                <= seconds_since(&a->LastDecisionReevaluationTime)"),
    AM("po-cp-every-off", "        if (AIPO_REEVALUATE_EVERY\n                < seconds_since(&a->LastDecisionReevaluationTime)",
       "        if (0\n                && seconds_since(&a->LastDecisionReevaluationTime)"),
    AM("po-cp-every-pts", "            || a->Base.PointsToDrive.NumPoints == 0) {\n            float hitTime",
       "            || 0) {\n            float hitTime"),
    AM("po-cp-last", "            a->LastDecisionReevaluationTime.PackedTime = (uint32_t)WorldTimer;\n            if (!drivingchoice_type_is_driving_line(choice->Type))",
       "            if (!drivingchoice_type_is_driving_line(choice->Type))"),
    AM("po-cp-line", "(uint32_t)WorldTimer;\n            if (!drivingchoice_type_is_driving_line(choice->Type))\n                drivingchoice_set_choice_location(choice, loc);",
       "(uint32_t)WorldTimer;\n            if (drivingchoice_type_is_driving_line(choice->Type))\n                drivingchoice_set_choice_location(choice, loc);"),
    AM("po-cp-setloc", "                drivingchoice_set_choice_location(choice, loc);\n            a->IsMyDrivingChoiceOkay = 1;",
       "            a->IsMyDrivingChoiceOkay = 1;"),
    AM("po-cp-okay1", "            a->IsMyDrivingChoiceOkay = 1;\n            if (careful) {",
       "            a->IsMyDrivingChoiceOkay = 0;\n            if (careful) {"),
    AM("po-cp-build-careful", "            if (careful) {\n                drivingchoice_build_drive_target(choice,",
       "            if (!careful) {\n                drivingchoice_build_drive_target(choice,"),
    AM("po-cp-build-move", "                                                 MOVEMENT_PARALLEL_TO_LINE);\n            } else {",
       "                                                 MOVEMENT_TOWARDS_LINE);\n            } else {"),
    AM("po-cp-clear", "                drivetarget_clear(&a->Base.PointsToDrive, NULL, 0.0f);\n                drivingchoice_fill_up_drive_target(",
       "                drivingchoice_fill_up_drive_target("),
    AM("po-cp-fill-move", "                    MOVEMENT_TOWARDS_RIGHT_SIDE_OF_TRACK, 0);",
       "                    MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK, 0);"),
    AM("po-cp-fill-in", "                    MOVEMENT_TOWARDS_RIGHT_SIDE_OF_TRACK, 0);",
       "                    MOVEMENT_TOWARDS_RIGHT_SIDE_OF_TRACK, 1);"),
    AM("po-cp-who-time", "                AIDriverAvoidCarsImpactTimeThreshold, &hitTime);\n            if (hit != NULL && hitTime < AIPO_HIT_SOON) {",
       "                AIActionPassMaxTimeAheadToMakeAttempt, &hitTime);\n            if (hit != NULL && hitTime < AIPO_HIT_SOON) {"),
    AM("po-cp-hit-null", "            if (hit != NULL && hitTime < AIPO_HIT_SOON) {", "            if (hitTime < AIPO_HIT_SOON) {"),
    AM("po-cp-hit-lt", "            if (hit != NULL && hitTime < AIPO_HIT_SOON) {", "            if (hit != NULL && hitTime <= AIPO_HIT_SOON) {"),
    AM("po-cp-hit-soon", "            if (hit != NULL && hitTime < AIPO_HIT_SOON) {", "            if (hit != NULL) {"),
    AM("po-cp-used", "                int usedPreferred = 1;\n", "                int usedPreferred = 0;\n"),
    AM("po-cp-left", "                drivingchoice_set_choice(&c, CHOICE_LEFT_SIDE_OF_CAR, hit, 0);",
       "                drivingchoice_set_choice(&c, CHOICE_RIGHT_SIDE_OF_CAR, hit, 0);"),
    AM("po-cp-set-flag", "                drivingchoice_set_choice(&c, CHOICE_LEFT_SIDE_OF_CAR, hit, 0);",
       "                drivingchoice_set_choice(&c, CHOICE_LEFT_SIDE_OF_CAR, hit, 1);"),
    AM("po-cp-set-car", "                drivingchoice_set_choice(&c, CHOICE_LEFT_SIDE_OF_CAR, hit, 0);",
       "                drivingchoice_set_choice(&c, CHOICE_LEFT_SIDE_OF_CAR, me, 0);"),
    AM("po-cp-mnc-okay", "                a->IsMyDrivingChoiceOkay = drivingchoice_make_new_choice(\n                    &c, &t,",
       "                a->IsMyDrivingChoiceOkay = !drivingchoice_make_new_choice(\n                    &c, &t,"),
    AM("po-cp-mnc-time", "                    &c, &t, loc, list, AIDriverAvoidCarsImpactTimeThreshold,",
       "                    &c, &t, loc, list, AIActionPassMaxTimeAheadToMakeAttempt,"),
    AM("po-cp-mnc-flag", "                    0.0f, &usedPreferred, 1);\n                drivetarget_assign",
       "                    0.0f, &usedPreferred, 0);\n                drivetarget_assign"),
    AM("po-cp-mnc-assign", "                    0.0f, &usedPreferred, 1);\n                drivetarget_assign(&a->Base.PointsToDrive, &t);\n",
       "                    0.0f, &usedPreferred, 1);\n"),
    AM("po-cp-mnc-copy", "                drivetarget_assign(&a->Base.PointsToDrive, &t);\n                *choice = c;\n",
       "                drivetarget_assign(&a->Base.PointsToDrive, &t);\n"),
    AM("po-cp-speed", "        speed = me->State.VelocityMagnitude;\n        if (careful) {", "        speed = me->State.ForwardSpeed;\n        if (careful) {"),
    AM("po-cp-gentle", "            if (a->IsMyDrivingChoiceOkay)\n                a->Base.DesiredSpeed =",
       "            if (!a->IsMyDrivingChoiceOkay)\n                a->Base.DesiredSpeed ="),
    AM("po-cp-gentle-sign", "                    speed + ai_calculate_max_deceleration(me, speed)\n                            * AIPO_GENTLE;",
       "                    speed - ai_calculate_max_deceleration(me, speed)\n                            * AIPO_GENTLE;"),
    AM("po-cp-firm-speed", "                    speed + ai_calculate_max_deceleration(me, speed)\n                            * AIPO_FIRM;",
       "                    speed + ai_calculate_max_deceleration(me, 0.0f)\n                            * AIPO_FIRM;"),
    AM("po-cp-firm", "                            * AIPO_FIRM;", "                            * AIPO_GENTLE;"),
    AM("po-cp-is-clear", "        } else if (drivinglocation_is_clear(loc)\n                   || !a->IsMyDrivingChoiceOkay) {",
       "        } else if (!a->IsMyDrivingChoiceOkay) {"),
    AM("po-cp-not-okay", "        } else if (drivinglocation_is_clear(loc)\n                   || !a->IsMyDrivingChoiceOkay) {",
       "        } else if (drivinglocation_is_clear(loc)) {"),
    AM("po-cp-fast-lt", "            if (AIPO_TOO_FAST < speed) {", "            if (AIPO_TOO_FAST <= speed) {"),
    AM("po-cp-fast-620", "                a->New620 = 1;\n                stop = 1;", "                a->New620 = 0;\n                stop = 1;"),
    AM("po-cp-fast-stop", "                a->New620 = 1;\n                stop = 1;", "                a->New620 = 1;\n                stop = 0;"),
    AM("po-cp-low-lt", "                    if (room < AIPO_ROOM_LOW)", "                    if (room <= AIPO_ROOM_LOW)"),
    AM("po-cp-low-set", "                        a->New620 = 0;\n                } else if", "                        a->New620 = 1;\n                } else if"),
    AM("po-cp-high-lt", "                } else if (AIPO_ROOM_HIGH < room) {", "                } else if (AIPO_ROOM_HIGH <= room) {"),
    AM("po-cp-high-set", "                    a->New620 = 1;\n                }\n                stop = !a->New620;",
       "                    a->New620 = 0;\n                }\n                stop = !a->New620;"),
    AM("po-cp-hyst", "                if (a->New620) {\n                    if (room < AIPO_ROOM_LOW)",
       "                if (!a->New620) {\n                    if (room < AIPO_ROOM_LOW)"),
    AM("po-cp-stop", "                stop = !a->New620;", "                stop = a->New620;"),
    AM("po-cp-creep", "                a->Base.DesiredSpeed = AIPO_CREEP_SPEED;", "                a->Base.DesiredSpeed = AIPO_TOO_FAST;"),
    AM("po-cp-tol2", "            a->Base.DesiredSpeedTolerance = AIPO_TOLERANCE;\n", ""),
    AM("po-cp-stopped-lt", "        if (a->Base.DesiredSpeed < AIPO_STOPPED) {", "        if (a->Base.DesiredSpeed <= AIPO_STOPPED) {"),
    AM("po-cp-stopped-ds", "        if (a->Base.DesiredSpeed < AIPO_STOPPED) {\n            a->Base.DesiredSpeed = 0.0f;\n",
       "        if (a->Base.DesiredSpeed < AIPO_STOPPED) {\n"),
    AM("po-cp-stopped-tol", "            a->Base.DesiredSpeedTolerance = 0.0f;\n        } else {\n            CollisionBody",
       "        } else {\n            CollisionBody"),
    AM("po-cp-coll-n", "            for (i = 0; i < b->NumCollisions; i++)\n                if (collision_is_two_car_collision(",
       "            for (i = 1; i < b->NumCollisions; i++)\n                if (collision_is_two_car_collision("),
    AM("po-cp-coll-two", "                if (collision_is_two_car_collision(\n                        collisionbody_get_collision(b, i))) {",
       "                if (!collision_is_two_car_collision(\n                        collisionbody_get_collision(b, i))) {"),
    AM("po-cp-coll-ds", "                    a->Base.DesiredSpeed = 0.0f;\n                    a->Base.DesiredSpeedTolerance = 0.0f;\n                    break;",
       "                    a->Base.DesiredSpeedTolerance = 0.0f;\n                    break;"),
    AM("po-cp-coll-tol", "                    a->Base.DesiredSpeedTolerance = 0.0f;\n                    break;", "                    break;"),
    AM("po-cp-coll-break", "                    break;\n                }\n        }", "                }\n        }"),
    AM("po-cp-past-setloc", "        drivingchoice_clear(&c);\n        drivingchoice_set_choice_location(&c, loc);\n",
       "        drivingchoice_clear(&c);\n"),
    AM("po-cp-past-move", "                                         MOVEMENT_PARALLEL_TO_LINE);\n        a->Base.DesiredSpeedTolerance = 0.0f;\n        a->Base.DesiredSpeed = 0.0f;",
       "                                         MOVEMENT_TOWARDS_LINE);\n        a->Base.DesiredSpeedTolerance = 0.0f;\n        a->Base.DesiredSpeed = 0.0f;"),
    AM("po-cp-past-build", "        drivingchoice_build_drive_target(&c, &a->Base.PointsToDrive, loc,\n                                         list, 0.0f, 0.0f,\n                                         MOVEMENT_PARALLEL_TO_LINE);\n",
       ""),
    AM("po-cp-past-tol", "        a->Base.DesiredSpeedTolerance = 0.0f;\n        a->Base.DesiredSpeed = 0.0f;\n    }",
       "        a->Base.DesiredSpeedTolerance = 1.0f;\n        a->Base.DesiredSpeed = 0.0f;\n    }"),
    AM("po-cp-past-ds", "        a->Base.DesiredSpeed = 0.0f;\n    }\n    a->Base.PointsToDriveWillExecuteAction = 1;\n    a->Base.TimeToGetToDesiredSpeed = AIPO_TIME_TO_SPEED;",
       "    }\n    a->Base.PointsToDriveWillExecuteAction = 1;\n    a->Base.TimeToGetToDesiredSpeed = AIPO_TIME_TO_SPEED;"),
    AM("po-cp-pt", "    a->Base.PointsToDriveWillExecuteAction = 1;\n    a->Base.TimeToGetToDesiredSpeed = AIPO_TIME_TO_SPEED;",
       "    a->Base.PointsToDriveWillExecuteAction = 0;\n    a->Base.TimeToGetToDesiredSpeed = AIPO_TIME_TO_SPEED;"),
    AM("po-cp-tts", "    a->Base.TimeToGetToDesiredSpeed = AIPO_TIME_TO_SPEED;\n", ""),
    AM("po-name", "\"Pull over\"", "\"Pull Over\""),
    # -- Step 11d-3a's: IJustGotHit ----------------------------------------
    AM("ij-every-k", "#define AIIJ_REEVALUATE_EVERY  0.200000003f", "#define AIIJ_REEVALUATE_EVERY  0.3f"),
    AM("ij-brake-k", "#define AIIJ_BRAKE             0.200000003f", "#define AIIJ_BRAKE             0.3f"),
    AM("ij-overlap-k", "#define AIIJ_OVERLAP           2.79999995f", "#define AIIJ_OVERLAP           3.0f"),
    AM("ij-back-k", "#define AIIJ_BACK_OFF          6.0f", "#define AIIJ_BACK_OFF          7.0f"),
    AM("ij-slower-k", "#define AIIJ_SLOWER_BY         0.100000001f", "#define AIIJ_SLOWER_BY         0.2f"),
    AM("ij-slower-unused-k", "#define AIIJ_SLOWER_UNUSED     0.200000003f", "#define AIIJ_SLOWER_UNUSED     0.3f"),
    AM("ij-min-k", "#define AIIJ_MIN_SPEED         20.0f", "#define AIIJ_MIN_SPEED         25.0f"),
    AM("ij-score-k", "#define AIIJ_SCORE   400", "#define AIIJ_SCORE   300"),
    AM("ij-type", "a->Base.Type = AIACTION_I_JUST_GOT_HIT;", "a->Base.Type = AIACTION_PASS;"),
    AM("ij-car", "    a->CarIHit = car;\n    a->Base.Base._vtable", "    a->CarIHit = NULL;\n    a->Base.Base._vtable"),
    AM("ij-vt", "    a->Base.Base._vtable = AIIJUSTGOTHIT_VTABLE;", "    a->Base.Base._vtable = AIPASS_VTABLE;"),
    AM("ij-last", "    a->LastDecisionReevaluationTime.PackedTime = 0;\n    return a;\n}\n\nvoid aijustgothit_destroy",
       "    a->LastDecisionReevaluationTime.PackedTime = (uint32_t)WorldTimer;\n    return a;\n}\n\nvoid aijustgothit_destroy"),
    AM("ij-dtor", "destroy_as(&a->Base, AIIJUSTGOTHIT_VTABLE, flags);", "destroy_as(&a->Base, AIIJUSTGOTHIT_VTABLE, 0);"),
    AM("ij-sc-null", "    *car = NULL;\n    for (i = 0; i < b->NumCollisions; i++) {\n        Collision *c",
       "    for (i = 0; i < b->NumCollisions; i++) {\n        Collision *c"),
    AM("ij-sc-n", "    for (i = 0; i < b->NumCollisions; i++) {\n        Collision *c",
       "    for (i = 1; i < b->NumCollisions; i++) {\n        Collision *c"),
    AM("ij-sc-two", "        if (!collision_is_two_car_collision(c))\n            continue;\n", ""),
    AM("ij-sc-other", "        other = c1 == list->MyCar ? c2 : c1;", "        other = c1 != list->MyCar ? c2 : c1;"),
    AM("ij-sc-other-2", "        other = c1 == list->MyCar ? c2 : c1;", "        other = c2;"),
    AM("ij-sc-nc", "        if (nc == NULL)\n            continue;\n        if (best", "        if (best"),
    AM("ij-sc-best-null", "        if (best == NULL || bestCar == NULL)", "        if (best == NULL)"),
    AM("ij-sc-ahead-lt", "        else if (best->Position.y < 0.0f && 0.0f < nc->Position.y)",
       "        else if (best->Position.y <= 0.0f && 0.0f < nc->Position.y)"),
    AM("ij-sc-ahead-gt", "        else if (best->Position.y < 0.0f && 0.0f < nc->Position.y)",
       "        else if (best->Position.y < 0.0f && 0.0f <= nc->Position.y)"),
    AM("ij-sc-ahead-off", "        else if (best->Position.y < 0.0f && 0.0f < nc->Position.y)\n            take = 1;\n", ""),
    AM("ij-sc-behind-only", "        else if (best->Position.y < 0.0f && 0.0f < nc->Position.y)",
       "        else if (0.0f < nc->Position.y)"),
    AM("ij-sc-smaller", "            take = nc->Position.y < best->Position.y;", "            take = nc->Position.y <= best->Position.y;"),
    AM("ij-sc-larger", "            take = nc->Position.y < best->Position.y;", "            take = best->Position.y < nc->Position.y;"),
    AM("ij-sc-bestcar", "            bestCar = other;\n", ""),
    AM("ij-sc-best", "            best = nc;\n", ""),
    AM("ij-sc-found", "            best = nc;\n            found = 1;\n", "            best = nc;\n"),
    AM("ij-sc-out", "    *car = bestCar;\n    return AIIJ_SCORE;", "    return AIIJ_SCORE;"),
    AM("ij-acc-set", "    if (!none)\n        a->CarIHit = car;\n", ""),
    AM("ij-acc-cond", "    if (!none)\n        a->CarIHit = car;", "    if (none)\n        a->CarIHit = car;"),
    AM("ij-acc-null", "    if (a->CarIHit == NULL\n        || nearbycarlist", "    if (0\n        || nearbycarlist"),
    AM("ij-acc-off", "           == NULL)\n        return 1;\n    return none;", "           != NULL)\n        return 1;\n    return none;"),
    AM("ij-acc-none", "        return 1;\n    return none;", "        return 1;\n    return 0;"),
    AM("ij-fail", "    // 0x001c9f58.\n    (void)a;\n    (void)info;\n    return 0;", "    // 0x001c9f58.\n    (void)a;\n    (void)info;\n    return 1;"),
    AM("ij-exp", "    // 0x001c9f10.\n    (void)info;\n    return past_timeout(&a->Base.Base);", "    // 0x001c9f10.\n    (void)info;\n    return 0;"),
    AM("ij-cp-nc", "    NearbyCar *nc = nearbycarlist_get_nearby_car(list, a->CarIHit);\n    Car *me;", "    NearbyCar *nc = NULL;\n    Car *me;"),
    AM("ij-cp-assign", "    drivetarget_assign(&a->Base.PointsToDrive,\n                       &list->MyCar->pCarDriver->MyDriveTarget);\n", ""),
    AM("ij-cp-tb", "    a->Base.AllowedToUseThrottleAndBrake = 1;\n    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.UseDrivingLineSpeed = 0;\n    if (AIIJ",
       "    a->Base.AllowedToUseThrottleAndBrake = 0;\n    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.UseDrivingLineSpeed = 0;\n    if (AIIJ"),
    AM("ij-cp-tol", "    a->Base.DesiredSpeedTolerance = 0.0f;\n    a->Base.UseDrivingLineSpeed = 0;\n    if (AIIJ",
       "    a->Base.DesiredSpeedTolerance = 1.0f;\n    a->Base.UseDrivingLineSpeed = 0;\n    if (AIIJ"),
    AM("ij-cp-udl", "    a->Base.UseDrivingLineSpeed = 0;\n    if (AIIJ", "    a->Base.UseDrivingLineSpeed = 1;\n    if (AIIJ"),
    AM("ij-cp-every-lt", "    if (AIIJ_REEVALUATE_EVERY < seconds_since(&a->LastDecisionReevaluationTime)",
       "    if (AIIJ_REEVALUATE_EVERY <= seconds_since(&a->LastDecisionReevaluationTime)"),
    AM("ij-cp-every-off", "    if (AIIJ_REEVALUATE_EVERY < seconds_since(&a->LastDecisionReevaluationTime)\n        ||",
       "    if (0\n        ||"),
    AM("ij-cp-every-pts", "        || a->Base.PointsToDrive.NumPoints == 0) {\n        int usedPreferred = 0;",
       "        || 0) {\n        int usedPreferred = 0;"),
    AM("ij-cp-last", "        a->LastDecisionReevaluationTime.PackedTime = (uint32_t)WorldTimer;\n        drivingchoice_make_new_choice(&info->MyDrivingChoice,",
       "        drivingchoice_make_new_choice(&info->MyDrivingChoice,"),
    AM("ij-cp-mnc-time", "                                      AIDriverAvoidCarsImpactTimeThreshold,\n                                      0.0f, &usedPreferred, 1);",
       "                                      AIActionPassMaxTimeAheadToMakeAttempt,\n                                      0.0f, &usedPreferred, 1);"),
    AM("ij-cp-mnc-flag", "                                      0.0f, &usedPreferred, 1);\n    }\n    me = list->MyCar;",
       "                                      0.0f, &usedPreferred, 0);\n    }\n    me = list->MyCar;"),
    AM("ij-cp-head", "        == HEADING_OUT_OF_ROUTE_FORWARDS) {", "        == HEADING_OUT_OF_ROUTE_BACKWARDS) {"),
    AM("ij-cp-head-flag", "    if (aiaction_get_heading_classification(loc, me, 0)", "    if (aiaction_get_heading_classification(loc, me, 1)"),
    AM("ij-cp-nc-udl", "    } else if (nc == NULL) {\n        a->Base.UseDrivingLineSpeed = 1;",
       "    } else if (nc == NULL) {\n        a->Base.UseDrivingLineSpeed = 0;"),
    AM("ij-cp-player", "    } else if (a->CarIHit->pPlayer != NULL\n", "    } else if (a->CarIHit->pPlayer == NULL\n"),
    AM("ij-cp-player-traffic", "               && me->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR) {", "               ) {"),
    AM("ij-cp-ahead-lt", "        if ((list->MyHalfSizeD + nc->ApparentHalfSizeD) - AIIJ_OVERLAP\n            < nc->Position.y)",
       "        if ((list->MyHalfSizeD + nc->ApparentHalfSizeD) - AIIJ_OVERLAP\n            <= nc->Position.y)"),
    AM("ij-cp-ahead-l", "        if ((list->MyHalfSizeD + nc->ApparentHalfSizeD) - AIIJ_OVERLAP",
       "        if ((list->MyHalfSizeL + nc->ApparentHalfSizeD) - AIIJ_OVERLAP"),
    AM("ij-cp-ahead-assoc", "        if ((list->MyHalfSizeD + nc->ApparentHalfSizeD) - AIIJ_OVERLAP",
       "        if (list->MyHalfSizeD + (nc->ApparentHalfSizeD - AIIJ_OVERLAP)"),
    AM("ij-cp-back-off", "                &a->Base, nc, list, AIIJ_BACK_OFF, AIIJ_SLOWER_UNUSED);",
       "                &a->Base, nc, list, AIIJ_SLOWER_BY, AIIJ_SLOWER_UNUSED);"),
    AM("ij-cp-back-lt", "        else if (nc->Position.y\n                 < (-list->MyHalfSizeD",
       "        else if (nc->Position.y\n                 <= (-list->MyHalfSizeD"),
    AM("ij-cp-back-assoc", "                 < (-list->MyHalfSizeD - nc->ApparentHalfSizeD)\n                   + AIIJ_OVERLAP)",
       "                 < -list->MyHalfSizeD - (nc->ApparentHalfSizeD\n                   - AIIJ_OVERLAP))"),
    AM("ij-cp-back-accel", "AIIJ_ACCEL);\n        else\n", "0.3f);\n        else\n"),
    AM("ij-cp-mid-udl", "        else\n            a->Base.UseDrivingLineSpeed = 1;\n    } else if",
       "        else\n            a->Base.UseDrivingLineSpeed = 0;\n    } else if"),
    AM("ij-cp-behind", "    } else if (!(0.0f < nc->Position.y)) {", "    } else if (!(0.0f <= nc->Position.y)) {"),
    AM("ij-cp-behind-accel", "AIIJ_ACCEL);\n    } else if (me->MyDriver", "0.3f);\n    } else if (me->MyDriver"),
    AM("ij-cp-head-on-traffic", "    } else if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n",
       "    } else if (me->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR\n"),
    AM("ij-cp-head-on-lt", "                  < 0.0f) {\n        // Traffic hit head on", "                  <= 0.0f) {\n        // Traffic hit head on"),
    AM("ij-cp-head-on-y", "                      * a->CarIHit->State.BodyMatrix.v0.y\n", "                      * a->CarIHit->State.BodyMatrix.v0.x\n"),
    AM("ij-cp-head-on-x", "                      * a->CarIHit->State.BodyMatrix.v0.x\n", "                      * a->CarIHit->State.BodyMatrix.v0.y\n"),
    AM("ij-cp-head-on-tts", "        a->Base.TimeToGetToDesiredSpeed = 0.0f;\n        a->Base.DesiredSpeed = me->State.VelocityMagnitude;",
       "        a->Base.DesiredSpeed = me->State.VelocityMagnitude;"),
    AM("ij-cp-head-on-ds", "        a->Base.DesiredSpeed = me->State.VelocityMagnitude;\n        a->Base.AllowedToUseThrottleAndBrake = 0;",
       "        a->Base.DesiredSpeed = me->State.ForwardSpeed;\n        a->Base.AllowedToUseThrottleAndBrake = 0;"),
    AM("ij-cp-head-on-tb", "        a->Base.AllowedToUseThrottleAndBrake = 0;\n    } else {", "        a->Base.AllowedToUseThrottleAndBrake = 1;\n    } else {"),
    AM("ij-cp-slower", "            &a->Base, nc, list, AIIJ_SLOWER_BY, AIIJ_SLOWER_UNUSED);",
       "            &a->Base, nc, list, AIIJ_BACK_OFF, AIIJ_SLOWER_UNUSED);"),
    AM("ij-cp-min-udl", "    if (!a->Base.UseDrivingLineSpeed && a->Base.DesiredSpeed < AIIJ_MIN_SPEED)",
       "    if (a->Base.DesiredSpeed < AIIJ_MIN_SPEED)"),
    AM("ij-cp-pt", "    a->Base.PointsToDriveWillExecuteAction = 1;\n}\n\nconst char *aijustgothit_get_name",
       "    a->Base.PointsToDriveWillExecuteAction = 0;\n}\n\nconst char *aijustgothit_get_name"),
    AM("ij-name", "\"I just got hit!\"", "\"I just got hit\""),
    AM("vt-po-acc", "E(aipullover_has_been_accomplished),", "E(aipullover_has_failed),"),
    AM("vt-po-name", "E(aipullover_get_name),", "E(aiaction_get_name),"),
    AM("vt-po-exp", "E(aipullover_has_expired),", "E(aijustgothit_has_expired),"),
    AM("vt-ij-cptd", "E(aijustgothit_calculate_points_to_drive),", "E(aipullover_calculate_points_to_drive),"),
    AM("vt-ij-acc", "E(aijustgothit_has_been_accomplished),", "E(aijustgothit_has_failed),"),
    AM("vt-ij-exp", "E(aijustgothit_has_expired),", "E(aijustgothit_has_failed),"),
    AM("vt-install-po", "    vt_install(AIPULLOVER_VTABLE, aipullover_vt, AIACTION_VT_ENTRIES);\n", ""),
    AM("vt-install-ij", "    vt_install(AIIJUSTGOTHIT_VTABLE, aijustgothit_vt, AIACTION_VT_ENTRIES);\n", ""),
    # -- EstimateScore's distances, which a stale pick reads ------------------
    M("es-static", "    static float dist[DRIVETARGET_MAX_POINTS];",
      "    float dist[DRIVETARGET_MAX_POINTS] = { 0.0f };", rel=DT),
]

EQUIVALENT = {
    "jd-every":
        "`<=` and `<` part only where the seconds are exactly 3.0f, and no "
        "tick count gives that: 11999 ticks times 0.00025f is 2.99975f and "
        "12000 is 3.0000002f.",
    "jd-pref":
        "A preferred IsDriveable scales only the score it hands back, which "
        "JustDrive never reads (the driveable test is on the score before "
        "it), and leaves out the choice's own car, which is NULL for "
        "DRIVING_LINE_0, as the other arm does.",
    "jd-a":
        "IsDriveable hands that float to BuildDriveTarget, which does not "
        "read it.",
    "mn-third":
        "MakeNewChoice's third arm needs the current choice's score off -1, "
        "and that score is bestScore read straight after the current try, "
        "which TryChoice moves only when it sets found -- and then the "
        "first arm is taken. Without the try the score stays -1.",
    "fx-its-side":
        "The side test on the oncoming car's own choice guards two tests "
        "that its type is CHOICE_LEFT_SIDE_OF_CAR or CHOICE_RIGHT_SIDE_OF_"
        "CAR, the only two types IsSideOfCar accepts. Without it, a choice "
        "of any other type with pCar equal to this car reaches those tests "
        "and fails both, leaving ok as it was: the same result for every "
        "type.",
    "sm-full":
        "Without the test before the loop, a full target goes once round "
        "it: the point is worked out and handed to AddPointToTarget, which "
        "refuses it at its own NumPoints < 20 before touching anything, "
        "and the loop's own test then stops. Nothing in the pass writes "
        "anywhere else.",
    "tc-hittime-init":
        "TryChoice's store to *hitTime is followed by IsDriveable, whose "
        "first lines store DC_NO_HIT there again before anything reads it.",
    "mn-line-way":
        "TryChoice reads the car in the way only after its side-of-car "
        "test, and a line choice returns at that test.",
    "tc-scored":
        "`<=` and `<` part only where |score + 1| is 0.00100000005f. For a "
        "score from -2 to -0.5 the subtraction is exact (Sterbenz), so "
        "|score + 1| is a multiple of 2^-24, and that float, 0x3a83126f, "
        "has an odd mantissa at 2^-33. Any other score is at least 0.5 "
        "from -1, and a NaN fails both.",
    "ta-saved":
        "The saved target is read only by the four restores, each followed "
        "at once by IsDriveable, whose BuildDriveTarget first copies the "
        "driver's own target over all 528 bytes of t. Retail's callers "
        "hand in their action's target (+32), never the driver's, so t is "
        "never that target.",
    "ta-cur-restore":
        "IsDriveable's BuildDriveTarget copies the driver's own target over "
        "all of t before reading it (see ta-saved).",
    "ta-line-restore":
        "IsDriveable's BuildDriveTarget copies the driver's own target over "
        "all of t before reading it (see ta-saved).",
    "ta-first-restore":
        "IsDriveable's BuildDriveTarget copies the driver's own target over "
        "all of t before reading it (see ta-saved).",
    "ta-second-restore":
        "IsDriveable's BuildDriveTarget copies the driver's own target over "
        "all of t before reading it (see ta-saved).",
    # Step 11d-2's.
    "pa-nohit":
        "IsDriveable's first lines store DC_NO_HIT in *hitTime before "
        "anything reads it, and Pass drops the time after.",
    "pa-cp-clear":
        "Every way on rebuilds PointsToDrive with BuildDriveTarget, whose "
        "first step copies the driver's own target over all of it: "
        "IsDriveable's, the last arm's, and TryToDriveAroundCar's, whose "
        "saved copy is put back only just before one (see ta-saved).",
    "pa-cp-drv-time":
        "The time reaches BuildDriveTarget, which does not read it, and "
        "WhoWillThisDriveTargetHit, where it only stops the walk: the hit "
        "and its time come back to IsDriveable's answer, which Pass drops, "
        "and the IDs move once a car either way.",
    "ac-sc-used1":
        "*usedPreferred was stored 0 at the top, and nothing between "
        "writes it.",
    "ac-cp-used0":
        "MakeNewChoice stores *out on each of its four ways out.",
    "ac-cp-none":
        "IsValid answers 0 for CHOICE_NONE (neither a line nor a side of a "
        "car), so the type test only says what the IsValid test says.",
    "ac-cp-zero":
        "PointsToDrive is empty after IsDriveable only for a clear "
        "location (with one, GetRoutePointsToUse always gives a point and "
        "FillUpDriveTarget adds it). Then IsDriveable's BuildDriveTarget "
        "built the same empty target, with the same choice and the same "
        "car left out, and answered 0, so a second build changes nothing.",
    "ac-cp-build-move":
        "This BuildDriveTarget runs only for a clear location (see "
        "ac-cp-zero), where FillUpDriveTarget returns before it reads the "
        "movement.",
    "ac-cp-build-okay":
        "This store runs only for a clear location (see ac-cp-zero), where "
        "IsDriveable's BuildDriveTarget did not build, so it answered 0 "
        "already.",
    "ac-cp-slower-b":
        "SetDesiredSpeedSlowerThanThisCar does not read its second float.",
    "po-ctor-clear":
        "AIAction's constructor has just initialised PointsToDrive, which "
        "ends in Clear on an empty target; nothing touches the target "
        "between, so a second Clear takes the same NumPoints == 0 way out "
        "and makes the same three stores.",
    "po-cp-nto-le":
        "`<=` and `<` part only where |pot + 999| is exactly 0.00100000005f. "
        "For pot within a factor of two of -999 the sum is exact (Sterbenz) "
        "and so a multiple of pot's ulp, 2^-14; 0.00100000005f is not one "
        "(times 2^14 it is 16.384). Any other pot is 499.5 or more away.",
    "po-cp-used":
        "MakeNewChoice stores *out on each of its four ways out before "
        "anything reads it, and PullOver never reads usedPreferred after.",
    "ij-slower-unused-k":
        "SetDesiredSpeedSlowerThanThisCar does not read its second float.",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model_cached(sc)
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "scenarios.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text().splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "drivingchoice_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    scdir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))

    sc = script()
    lines = model_cached(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "scenarios.txt"
        scp.write_text(encode(sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    ops = sum(len(s) for s in sc)
    print("%d scenarios, %d ops, %d lines, %d differ"
          % (len(sc), ops, len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
