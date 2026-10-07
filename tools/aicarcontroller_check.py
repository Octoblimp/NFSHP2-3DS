#!/usr/bin/env python3
"""Cross-check 3DS Files/source/aicarcontroller.c -- the AI car controller,
steps 11e-1 to 11e-5's parts of it -- against the retail image, run in
mipsemu.

The model is retail's image, over drivingchoice_check.py's world: its cars,
routes, signs, list and test tables, its stubs and every one of its ops,
which this checker's script uses too. On top of them come the '%' ops,
which build a controller in place of a car's own (CTRLS + 0x400 k) and
call its methods as shipped: the constructor and destructor,
SetCurrentRoute, GetCurrentRoute and GetCurrentRoutePoint with and without
the find, GetAmountOutOfBounds, FindWhereIAm, FindClosestTrackRoute,
GetNewDrivingLine, JustReset, GetMyDriverNumber, ClearStickyDecisions,
SteerStraightAhead, ChooseNewAction, InterruptAction,
GeneratePointsToFulfillAction, GetCurrentActionType,
ForceMyCurrentAction, SetToPhysicsMode (and CarController's, which the
port now takes from retail), GetCurrentDrivingLineSpeed, ForceBoost,
ReleaseBoost, AboutToFly, SetOffBeltTimer, the exclusion's get and set,
GetCurrentDrivingLocation and DebugDisplay; and 11e-2's FindSignpostIndex,
GetStickyIndex, DoStickyDecisions, SignPostDecision and
GetCurrentTrackRoutePoint; and 11e-3's WeHaveTheBelt, WeNeedTheBelt,
WeCanHaveTheBelt, WeHaveTheGlue, WeNeedTheGlue, WeCanHaveTheGlue, GlueOn,
GlueOff, GetGlueSpeed, DecideBoostFactor and
CalculateDistanceAndPositionBoost; and 11e-4's
MaybeHonkAndOrBlinkHeadlights and ExecuteCurrentAction, with the car's
HonkAndOrBlinkHeadlights and UpdateHeadlightsAndHorn beside them; and
11e-5's Think, with Timer::CountDown and Race::CanAICarsStartDriving, and
under it NearbyCarList::BuildArray, AIAction::UpdateStatus,
Average::Record, Car::IsBlinking, bRandom's two over bDefaultSeed and a new
AIActionJustDrive (its constructor, tests, CalculatePointsToDrive and
destructor) as shipped.
SignPostDecision runs as shipped wherever it is reached, DrivingChoice::AdvancePoint too, as main.c points
drivingchoice.h's seam at the port's. Under them everything the port
has runs as shipped too: the Average's constructor and destructor,
Signpost::GetIndex, the route manager's table, DistanceIsWithinRoute,
FindClosestPoint, GetPosition, the DrivingLocation, DrivingChoice and
DrivingInformation methods, IsDriveable and all beneath it,
GetCarAhead and HighlightDrivingLine, and 11e-3's Graph, Linear, Table,
World::GetDistanceToClosestPlayer, Race::GetRacingCar and the
RaceCoordinator's state, and 11e-4's DoWeCareAboutThisCar,
NearbyCarList::GetNearbyCar, TrackRoute::GetPointNumber,
Signpost::GetNewRoutePoint, AIAction::ClearPointsToDrive and the timers.
The glue's Graph is built by the image's own
start-up code (_GLOBAL_$I$sRankHeadings) in the model.

**The stand-ins**, each printing a line, so both sides must ask the same
questions in the same order:
  bMalloc (0x002577c0): a block of 64 bytes, filled with 0xa5, named m0,
    m1, ... in the order asked for, with the size, name, flags and pool
    printed (the port's Average record, 24 bytes on a 64-bit host, prints
    as retail's 16);
  bFree (0x00257850), which __builtin_delete jumps to: the block's name;
  Car::SetMovementMode (0x00131618): the car and the mode, which it sets;
  a test CarDriver table at DVT, drivingchoice_check's, with
    SetSteerToPoint (72) and ZeroSteeringMemory (120) added;
  a test controller table at TVT: retail's _vt$15AICarController with
    GetRouteNumbersToUse (112, pure in retail) answering the script's
    first and last route numbers and ChooseNewAction (120) the script's
    queue of fake actions;
  the fake actions, in a table at AVT whose destructor (8) and
    CalculatePointsToDrive (24) print, the second setting the action's
    PointsToDriveWillExecuteAction to the script's answer;
  drivingchoice_check's controller table at CVT, which every car the "C"
    op sets up has, now with GetCurrentRoutePoint (56) and
    GetAmountOutOfBounds (64) answering the script's point and amount: the
    model no longer stubs Car::GetRoutePoint and GetAmountOutOfBounds, which
    reach a built controller's own methods through its table;
  World::Random (0x0014e548): the world (1 for pCurrentWorld) and the
    range, answering the script's queue, then 0;
  GetTrackInfo (0x00153420): the track number, answering a TrackInfo of
    the script's, its SignpostGracePeriod -1 until set;
  the test driver table's GetDesiredSpeed (136): the car, answering the
    script's speed for it;
  for 11e-4, the test driver table's SetDesiredSpeed (56), with the car,
    the three floats and the flag, SetTarget (64), with the car and the
    target, StartHonkHorn (88) and StopHonkHorn (96), with the car, and
    IsHonking (104), with the car, answering the script's flag for it;
  World::Random(int) (0x0014e520): the world and the range, answering the
    float's queue as words, so the two draw from one queue in turn;
  for 11e-5, bOMalloc (0x00257c80): the pool, answering
    drivingchoice_check's action block (ab), where Think's new JustDrive
    goes; BeltMover::SetBelt (0x00204990): the mover;
    Car::DebugSetPosition (0x00133338): the car, the place, the speed and
    the angle; DriveTargetRenderer::SetTargetToRender (0x001cb600): the
    renderer (tdr for TheDriveTargetRenderer) and the target;
    bRefreshTweaker (0x0025d2c8), a call to the host, silent; and the fake
    actions' HasBeenAccomplished (40), HasFailed (48) and HasExpired (56):
    the action and the information, answering the script's.
SuperEasyAI and BoringAIForCameraTuningOn are words the script sets.
11e-3's players (PLR), their speed-ratio Averages, the RacingCars, the
coordinator's state, the race parameters' fields, TheDifficultyInfo and
the World's PlayerPositions are memory the script fills. WeCanHaveTheGlue's
two vrsqrt divide by zero for a car standing still (GLUE_DIVS), which the
model allows.

A float prints as its bits, a NaN as "nan", and a pointer by what it is,
as drivingchoice_check names them, with these added: kn3, kl3 and kc3 car
3's controller's own list, location and choice, ke3:5 its list's sixth
entry, m4 the fifth block bMalloc handed out, fa2 the third fake
action, pt2 its PointsToDrive and P1 car 1's player. vK is _vt$15AICarController, vT the test table, vC
drivingchoice_check's, vB _vt$13CarController and vF the actions'.

    python tools/aicarcontroller_check.py
    python tools/aicarcontroller_check.py --mutate [--only a,b]
    python tools/aicarcontroller_check.py --dump out/aicarcontroller
"""
import argparse
import math
import os
import random
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import drivingchoice_check as dcc
import mutpar
from drivingchoice_check import (CARS, CAR_STRIDE, CTRLS, CTRL_STRIDE,
                                 CDRIVERS, CDRIVER_STRIDE, NCARS, PLAYERS,
                                 PLAYER_STRIDE, LIST, LOC, CHOICE, SIGNS,
                                 SIGN_SIZE, GLOBALS, DVT, CVT, PATTERN, LINES,
                                 RACE, WORLD,
                                 car_at, route_at, h, f32, fb, fx, s8,
                                 World, walk_world, place_me, place_other,
                                 seen_list, decide, boxed, heading_of)
from mipsemu import M32, s32

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/aicarcontroller_test.c"
AICC = "3DS Files/source/aicarcontroller.c"
PLAYER_H = "3DS Files/source/player.h"
CCC = "3DS Files/source/carcontroller.c"
CAR_C = "3DS Files/source/car.c"
TIMER_C = "3DS Files/source/timer.c"
RACE_C = "3DS Files/source/race.c"
SOURCES = [HARNESS] + dcc.SOURCES[1:] + ["3DS Files/source/" + f for f in (
    "aicarcontroller.c", "carcontroller.c", "average.c", "timer.c",
    "difficultyinfo.c", "configitems.c")]

# ================================================================ the image

AICC_VTABLE = 0x002b4d90          # _vt$15AICarController
CC_VTABLE = 0x002b7218            # _vt$13CarController
AICC_VT_BYTES = 17 * 8
NDMM = 0x0032ff40                 # nDefaultMovementMode, gp-22960

F = {
    "ctor": 0x00190140, "dtor": 0x001903a0, "sr": 0x00190670,
    "gr": 0x00190708, "gp": 0x00190760, "oob": 0x001907b8,
    "jr": 0x00190850, "dn": 0x001908f0, "fc": 0x00190900,
    "af": 0x00191130, "dd": 0x00191138, "cs": 0x00191d10,
    "gl": 0x00192488, "gpf": 0x00192668, "cn": 0x00192780,
    "ia": 0x00192788, "st": 0x00192848, "fw": 0x00192f10,
    "pm": 0x00193650, "ls": 0x001936f0, "fb": 0x00193758,
    "rb": 0x00193780, "gx": 0x00193fe0, "ex": 0x00193fe8,
    "gdl": 0x00193ff8, "cat": 0x00194000, "force": 0x00194020,
    "ob": 0x00194028, "cc": 0x001c0100,
    # 11e-2's.
    "fsi": 0x00191d40, "gsi": 0x00191d90, "dsd": 0x00191b30,
    "spd": 0x00191de0, "gct": 0x001921f8,
    # 11e-3's.
    "whb": 0x00190af8, "wnb": 0x00190b10, "wcb": 0x00190b20,
    "whg": 0x00190c78, "wng": 0x00190c88, "wcg": 0x00190c90,
    "gon": 0x00190f38, "goff": 0x00190fb8, "ggs": 0x00190ff8,
    "dbf": 0x001928f0, "cdp": 0x00192c78,
    # 11e-4's, and the car's honk and its UpdateHeadlightsAndHorn.
    "mh": 0x00192fa8, "eca": 0x001932e8, "honk": 0x00134130,
    "uh": 0x00134198,
    # 11e-5's: Think, Timer::CountDown and Race::CanAICarsStartDriving.
    "think": 0x00191148, "tcd": 0x001a3cf0, "cas": 0x00149078,
}
BMALLOC = 0x002577c0
BFREE = 0x00257850
SET_MOVEMENT = 0x00131618
WORLD_RANDOM = 0x0014e548         # World::Random(float)
GET_TRACK_INFO = 0x00153420
RACE_PARAMS = 0x0031a898          # TheRaceParameters, TrackNumber at 0
SKILLS = 0x002f0080 + 368         # TheDifficultyInfo.AISkillLevel
SKILL_STRIDE = 28
NSKILLS = 10
RACE_TIME = 16                    # Race::RaceTime
S_FLAGS, S_HINT = 1, 8            # a sign's Flags byte and AIHint

# The checker's own memory, past drivingchoice_check's.
STUB_SSTP = 0x010b3430
STUB_ZSM = 0x010b3440
STUB_RNUM = 0x010b3450
STUB_CHOOSE = 0x010b3460
STUB_ADEL = 0x010b3470
STUB_ACP = 0x010b3480
STUB_CRP = 0x010b3490
STUB_COOB = 0x010b34a0
HEAP = 0x010c0000
HEAP_BLOCK = 64
NHEAP = 16
TVT = 0x010c2100                  # the harness's addresses for the two
AVT = 0x010c2200                  # test tables
AVT_BYTES = 8 * 8
LINEVAR = 0x010c2400
OUTP = 0x010c2410
FACTS = 0x010c3000
FACT_SIZE = 608
NFACTS = 8
TINFO = 0x010c2500                # GetTrackInfo's answer
TINFO_SIZE = 164
TI_GRACE = 128                    # its SignpostGracePeriod
NRANDOM = 16

# 11e-3's. _GLOBAL_$I$sRankHeadings builds the glue's Graph (gp-20336) over
# its two points at 0x00310108, which the emulator does not run until the
# model calls it. WeCanHaveTheGlue's two `vrsqrt`s divide by zero for a car
# standing still, as the EE does and the port's ee_div spells.
GLUE_CTOR = 0x00193f00
GLUE_DIVS = {0x00190d28, 0x00190d54}
G3 = {
    "BELT": dcc.GP - 20344,       # bBeltMover
    "DISABLE": dcc.GP - 20132,    # CarControllerDisableCatchup
    "REASON": dcc.GP - 20296,     # nLastGlueReason
    "RCOORD": dcc.GP - 22216,     # pRaceCoordinator
    "BYNUM": dcc.GP - 20936,      # PlayerPlayersByNumber, two words
    "SKIPFE": dcc.GP - 23220,     # SkipFE
    "SKIPFE_COP": dcc.GP - 23176,  # SkipFEBeACop
}
DIFF = 0x002f0080                 # TheDifficultyInfo
DIFF_SIZE = 992
RP_FIELDS = {"npc": 48, "nai": 52, "cop": 628, "boost": 760, "s0": 764,
             "s1": 768}           # TheRaceParameters'
STUB_GDS = 0x010b34b0             # the drivers' GetDesiredSpeed (136)
DVT_GDS = 136
PLR = 0x010c5000                  # car k's player, retail's offsets
PLR_STRIDE = 0x200
P_CAR, P_NUM, P_AVG, P_MAX, P_GLUE = 4, 16, 160, 168, 192
PAVG = 0x010c7000                 # its speed ratio's Average
PAVG_STRIDE = 16
RCARS = 0x010c7400                # car k's RacingCar
RC_STRIDE = 192
RC_POS, RC_LAP = 10, 20
C_RC = 28
RCOORD = 0x010c8000               # the race coordinator, its state at 0
W_PPOS = 336                      # World's PlayerPositions, 16 bytes each
A_BOOST = 584                     # an action's AllowedToUseBoost
# The controller's fields %kf sets.
KF = {"lbt": 564, "ob": 568, "rp": 572, "glue": 588, "on": 592, "off": 596,
      "bias": 604, "ba": 640, "cp": 644, "lrs": 536, "la": 540, "tt": 688,
      "bs": 552, "bss": 556, "bsg": 560, "pt": 576, "secs": 524}

# 11e-4's. The car's horn and headlights, by retail's offsets from
# WantToBlinkHeadlights: the honk and two-honk words, the start, the on,
# second and off durations, the forcing and the headlights' state.
C_HONK = 2068
H_BLINK, H_HONK, H_TWO, H_START = 0, 4, 8, 12
H_ON, H_SECOND, H_OFF, H_FORCE, H_STATE = 16, 20, 24, 28, 32
WORLD_RANDOM_I = 0x0014e520       # World::Random(int)
G4 = {
    "EASY": dcc.GP - 20120,       # SuperEasyAI, retail's alone
    "BORING": dcc.GP - 22580,     # BoringAIForCameraTuningOn
}
STUB_SDS = 0x010b34c0             # the drivers' SetDesiredSpeed (56),
STUB_STG = 0x010b34d0             # SetTarget (64), StartHonkHorn (88),
STUB_HON = 0x010b34e0             # StopHonkHorn (96) and IsHonking (104)
STUB_HOFF = 0x010b34f0
STUB_ISH = 0x010c2440
DVT_STUBS4 = ((56, STUB_SDS), (64, STUB_STG), (88, STUB_HON),
              (96, STUB_HOFF), (104, STUB_ISH))
# An action's PointsToDrive and speed fields, and the target's.
A_PTD = 32
A_SPEED, A_TIME, A_TOL, A_USE, A_ALLOWED = 564, 568, 572, 576, 580
T_WPC, T_WPT, T_LEN, T_LPS = 504, 508, 512, 516
TP_SPEEDS = 90                    # a route point's DrivingLineSpeeds

# 11e-5's. bOMalloc, which Think's new JustDrive takes its slot from (AB,
# as the harness's bSlotOMalloc); BeltMover::SetBelt, Car::DebugSetPosition,
# DriveTargetRenderer::SetTargetToRender and bRefreshTweaker, stubbed; and
# the globals Think reads.
BOMALLOC = 0x00257c80
SET_BELT = 0x00204990
DEBUG_SET_POS = 0x00133338
SET_TARGET_TO_RENDER = 0x001cb600
REFRESH_TWEAKER = 0x0025d2c8
TDR = 0x00314630                  # TheDriveTargetRenderer
G5 = {
    "RESET": dcc.GP - 20320,      # ResetThisCarsPosition
    "ANGLE": dcc.GP - 13390,      # ThisCarsResetAngle, a halfword
    "LOOP": dcc.GP - 19552,       # WorldLoopCounter
    "SEED": dcc.GP - 14472,       # bDefaultSeed
}
STUB_AHBA = 0x010c2450            # the fake actions' HasBeenAccomplished
STUB_AHF = 0x010c2460             # (40), HasFailed (48) and HasExpired
STUB_AHE = 0x010c2470             # (56)
TCD = 0x010c2480                  # CountDown's timer
# The World's car counts and table, a car's rendering byte and poofed
# word, a RacingCar's dCurrentLapNumberExact, an action's CanExpire and
# Status.
W_TOTAL, W_AIPOS, W_COPPOS, W_TRAFFICPOS, W_TABLE = 28, 32, 36, 40, 44
W_MAX_CARS = 14
C_RENDER, C_POOFED = 1192, 2160   # retail's, past the demo's 1160, 2120
RC_DLAP = 24
A_CAN, A_STATUS = 0, 12

# The controller, by retail's offsets.
K_SIZE = 720
K_DRIVER, K_VPTR, K_LIST, K_ILOC, K_ICH = 4, 8, 12, 476, 492
K_LOC, K_CHOICE, K_NLIST, K_EXCLUDE = 504, 508, 512, 516
K_LTR, K_SECS, K_FORCE, K_ACTION = 520, 524, 528, 532
K_TIMERS = (536, 544, 552, 556, 564, 568, 572, 576, 592, 596, 688)
K_LA, K_POT, K_BS, K_PROG, K_LP, K_GLUE = 540, 548, 560, 580, 584, 588
K_GR, K_GB, K_GD, K_BOOST, K_CP, K_SIGN = 600, 604, 608, 640, 644, 648
K_STICKY, K_TS, K_DLS, K_VP = 652, 684, 692, 704
K_OB, K_RP = 568, 572
NSTICKY = 8
LIST_BYTES = 464
LIST_HL, LIST_HD = 456, 460
NC_SIZE = 28

# A fake action's vptr, answer, type and score.
A_VPTR, A_PT, A_TYPE, A_SCORE = 16, 560, 588, 592

# The car's.
C_INDEX, C_PLAYER, C_MODE = 8, 24, 36
C_BOOST, C_ANGLE, C_DIST = 992, 932, 2036
C_POS = 96

# A route's distances and box, and a sign's distance.
R_START, R_END, R_BMIN, R_BMAX = 32, 36, 1048, 1056
S_DIST = 4

VT_NAMES = {AICC_VTABLE: "vK", TVT: "vT", CVT: "vC", CC_VTABLE: "vB",
            AVT: "vF"}
PAT32 = PATTERN * 0x01010101

AIACTION_NONE = 11
PHYSICS, MELLOW, BELT = 1, 4, 6


def ctrl_at(k):
    return CTRLS + CTRL_STRIDE * k


def fact_at(i):
    return FACTS + FACT_SIZE * i if i >= 0 else 0


# ============================================================ the scenarios
#
# drivingchoice_check's ops, and these. Set up, and echoed:
# %d k dist              car k's distance around the track
# %S i dist              sign i's distance
# %NS n                  NumSignposts
# %U k s e x0 y0 x1 y1   route k's start and end distances and its box
# %a k angle             car k's angle, a bam
# %mm k mode             car k's movement mode
# %pl k p                car k's player, or none
# %bf k f                car k's BoostFactor
# %ci k i                car k's CarIndex
# %pos k x y z           car k's position
# %vp k x y z w          controller k's vPreviousLinePoint
# %cp k k2               route k's points copied over route k2's, but for
#                        each point's own route number, so that the two
#                        tie for closest
# %G mode                nDefaultMovementMode
# %v k i                 controller k's vptr: vK, vT or vC
# %dr k                  controller k's driver: car k's CarDriver
# %J k                   the list, the location and the choice copied
#                        into controller k's own
# %L k r j line t        what controller k's location points at, set
# %ch k type car x       what its choice points at, set
# %sk k w0 .. w7         its sticky decisions
# %rn k first last       what GetRouteNumbersToUse answers for it
# %q a0 a1 ..            ChooseNewAction's answers, in turn (-1 NULL)
# %fa i type score pt p0 fake action i: its type and score, what its
#                        CalculatePointsToDrive answers and its answer now
# %cur k i               controller k's CurrentAction (-1 NULL)
#
# The calls, each on controller k (a car's own, in place):
# %n k                   filled with 0xa5, then built for car k
# %x k flags             destroyed
# %K k                   dumped
# %sr k r j              SetCurrentRoute
# %gr k find / %gp k find  GetCurrentRoute / GetCurrentRoutePoint
# %oob k                 GetAmountOutOfBounds
# %fw k                  FindWhereIAm
# %fc k first last       FindClosestTrackRoute
# %gl k r j relaxed hl   GetNewDrivingLine, its line filled with 0xa5;
#                        hl -1 NULL, 0 the location, 1 its own
# %jr k                  JustReset
# %dn k                  GetMyDriverNumber
# %cs k                  ClearStickyDecisions
# %st k                  SteerStraightAhead
# %cn k type             ChooseNewAction, its out NULL
# %ia k                  InterruptAction
# %gpf k i               GeneratePointsToFulfillAction with fake action i
# %cat k / %force k type GetCurrentActionType / ForceMyCurrentAction
# %pm k car / %cc k car  SetToPhysicsMode / CarController's
# %ls k / %seam k        GetCurrentDrivingLineSpeed, direct and through
#                        the port's seam
# %fb k f / %rb k        ForceBoost / ReleaseBoost
# %af k t / %ob k secs   AboutToFly / SetOffBeltTimer
# %ex k car / %gx k      the car to exclude, set / got
# %gdl k / %dd k         GetCurrentDrivingLocation / DebugDisplay
#
# 11e-2's. Set up:
# %rnd n v0 ..           World::Random's next n answers
# %tg g / %tn n          the TrackInfo's SignpostGracePeriod / TrackNumber
# %rt 0 t                the race's RaceTime, in ticks
# %tsc s c0 c1 c2        skill level s's TakeSignChance
# %sf i flags hint       sign i's Flags byte and AIHint
# %si k i / %ts k i      controller k's nSignpostIndex / TakenSignpostIndex
# %hl k f                its own list's MyHalfSizeL
# %vm k f                car k's VelocityMagnitude
# The calls:
# %fsi k / %gsi k        FindSignpostIndex / GetStickyIndex
# %dsd k                 DoStickyDecisions
# %spd k i line          SignPostDecision on sign i from the line, at the
#                        controller's location
# %gct k                 GetCurrentTrackRoutePoint
#
# 11e-3's. Set up:
# %P k pn ratio max slots n glue  car k's player, P k: its PlayerNumber,
#                        its speed ratio's mean, slot and sample counts,
#                        fMaxSpeedRatio and nGlueCount
# %PT n i0 i1 b0 b1      PlayerNumPlayers, the players by index and by
#                        number (each the player of that car, -1 NULL)
# %rc k pos lap          car k's RacingCar: its RacePosition and
#                        CurrentLapNumberExact (%rc k x: none)
# %RC state              the race coordinator's state
# %rp npc nai cop boost s0 s1  TheRaceParameters' NumPlayerCars, NumAICars,
#                        BeACop, Boost and BoostScale
# %sfe skipfe cop        SkipFE and SkipFEBeACop
# %dw off w0 ..          words into TheDifficultyInfo from byte off
# %gds k f               what car k's driver's GetDesiredSpeed answers
# %wp i x y z            the world's PlayerPositions[i]
# %bm v / %dc v          bBeltMover / CarControllerDisableCatchup
# %ab i v                fake action i's AllowedToUseBoost
# %np k n                car k's driver's target's NumPoints
# %vel k x y z           car k's velocity
# %fsw k fs nw           car k's ForwardSpeed and nWheelsTouchingGround
# %kf k field v          controller k's lbt, ob, rp, on and off timers,
#                        glue (a car), bias, ba (bBoostAllowed) or cp (the
#                        player of a car)
# The calls:
# %whb k / %wnb k / %wcb k  WeHaveTheBelt / WeNeedTheBelt / WeCanHaveTheBelt
# %whg k / %wng k        WeHaveTheGlue / WeNeedTheGlue
# %wcg k p               WeCanHaveTheGlue with car p's player
# %gon k p / %goff k     GlueOn with car p's player / GlueOff
# %ggs k                 GetGlueSpeed
# %cdp k me them         CalculateDistanceAndPositionBoost on two cars'
#                        RacingCars
# %dbf k                 DecideBoostFactor
#
# 11e-4's. Set up:
# %ctl k m / %dt k t     car k's control mode / its driver's type
# %hk k blink honk two start on second off force  car k's horn and
#                        headlights (the start and the floats in hex)
# %ish k v               what car k's driver's IsHonking answers
# %ad i use speed time tol allowed  fake action i's UseDrivingLineSpeed,
#                        DesiredSpeed, TimeToGetToDesiredSpeed,
#                        DesiredSpeedTolerance and AllowedToUseThrottleAndBrake
# %at i n len            fake action i's PointsToDrive: NumPoints, Length,
#                        and its two pick times and LastPointToScore set
# %sea v / %bai v        SuperEasyAI / BoringAIForCameraTuningOn
# %lsp r j line v        route r's point j's speed byte for the line
# %kf k field v          as 11e-3's, with lrs (the look-ahead switch's
#                        time), la (the look-ahead) and tt (the
#                        TakenSignpostTimer)
# The calls:
# %mh k car lst          MaybeHonkAndOrBlinkHeadlights on the car, with the
#                        list (0) or controller k's own (1), then car k's horn
# %hr k on off second blink honk two  car k's HonkAndOrBlinkHeadlights,
#                        then its horn
# %uh k                  car k's UpdateHeadlightsAndHorn, then its
#                        HeadlightsState
# %eca k i               ExecuteCurrentAction, then the look-ahead, its
#                        time, the BoostFactor and fake action i's target
#
# 11e-5's. Set up:
# %rs s                  the race's RaceStage
# %wlc v                 WorldLoopCounter
# %wt total ai cop traffic c0 .. c13  the World's TotalNumCars, AICarPos,
#                        CopCarPos and TrafficCarPos, and its CarTable (each
#                        a car, -1 NULL)
# %cl k ..               the World's car list, the cars in turn, each
#                        rendering and not poofed (none: empty)
# %seed w                bDefaultSeed
# %rtp v angle           ResetThisCarsPosition and ThisCarsResetAngle
# %dl k f                car k's RacingCar's dCurrentLapNumberExact
# %pg k cur n total d    controller k's progress Average: its slot, its
#                        count, its total and the slot's sample
# %fs i can exp fail acc fake action i's CanExpire and what its HasExpired,
#                        HasFailed and HasBeenAccomplished answer
# %kf k field v          as 11e-4's, with bs and bss (the brake stand's
#                        timers), bsg (BrakeStanding), pt (ProgressTimer)
#                        and secs (SecondsBeforeNextActionEvaluation)
# The calls:
# %think k dt            Think, then the controller, the seed, the debug
#                        reset's switch, the car's mode, the world's two
#                        counts, the action's type, status and answer, and
#                        the fakes'
# %tcd w dt              Timer::CountDown on a timer of w, then its answer
#                        and the timer
# %cas                   Race::CanAICarsStartDriving on pCurrentRace
#
# Not scripted: a find on a controller whose table is vK and whose
# location is clear (retail's slot 112 is __pure_virtual), a route number
# over 99 (retail reads on past the manager's table), FindClosestTrackRoute
# finding a route through vC (whose SetCurrentRoute is no one's), and
# GeneratePointsToFulfillAction's second CalculatePointsToDrive on a NULL
# action. From 11e-2: a NaN speed (the EE has no NaN, and retail's
# look-ahead comes out at 250 where an IEEE FPU's is a NaN); DoStickyDecisions
# with no sign past the look-ahead (retail goes round the signs for ever) or
# with a used decision's sign past the table; and DoStickyDecisions or
# FindSignpostIndex after SignPostDecision stored a decision with every
# slot used, into nSignpostIndex, which they index the signs by. From
# 11e-3: GetGlueSpeed with no glued car (the port reads through NULL where
# retail reads address 28), a player's car or the AI car out of the race
# where the glue or the boost reads its RacingCar, a skill over 9 (past
# AISkillLevel), a place gap past eight either way (past the position
# boosts), and a velocity whose squares underflow (the EE flushes them).
# From 11e-4: MaybeHonk for a traffic car whose nearby car isn't in the
# list (the port reads through NULL where retail reads address 12; an AI
# car's DoWeCareAboutThisCar turns it away), ExecuteCurrentAction with no
# current action, a taken sign with no new route, and a skill whose
# SpeedFactor lies outside TheDifficultyInfo (below -13 or past 21). From
# 11e-5: ChooseNewAction answering NULL where Think goes on to the action's
# points or its execution (both read through it), a CarTable slot before
# the table (a negative loop counter's remainder past AICarPos or
# TrafficCarPos), a choice beside a car of NULL (retail reads address 24),
# a sign within the look-ahead when Think runs DoStickyDecisions, which
# 11e-2's scenarios cover, and BuildArray beside no list owner.

# Distances either side of the ones that matter.
SECS = (0.0, 0.5, 1.5, 2.0, 3.0, -1.0, 0.000125, 0.0001, 1e6, 1e9, -1e9,
        f32(0.1))
ANGLES = (0, 1, 0x4000, 0x8000, 0xc000, 0xffff, 12345)
INDICES = (0, 1, 7, 15, -1, 140, 32767, -32768)


def sign_ops(rnd, n):
    """n signs at rising distances, now and then two at one, and their
    count."""
    ds = []
    d = rnd.uniform(-50.0, 100.0)
    for _ in range(n):
        ds.append(f32(d))
        if rnd.random() > 0.2:
            d += rnd.uniform(1.0, 400.0)
    ops = ["%%S %d %s" % (i, h(v)) for i, v in enumerate(ds)]
    ops.append("%%NS %d" % n)
    return ops, ds


def dist_near(rnd, ds):
    """A distance around the track before, at, between or past the
    signs, or a NaN."""
    c = rnd.randrange(8)
    if not ds or c == 0:
        return h(f32(rnd.uniform(-100.0, 3000.0)))
    if c == 1:
        return h(ds[0] - 1.0)
    if c in (2, 3):
        return h(rnd.choice(ds))
    if c == 4:
        return h(ds[-1] + 1.0)
    if c == 5:
        return "7fc00000"
    i = rnd.randrange(len(ds))
    return h(f32(ds[i] + rnd.choice((-0.001, 0.001, -2.0, 2.0))))


def s_build(rnd):
    """The constructor over signs and a car's distance and index, the
    small methods, and the destructor with and without an action."""
    w = World(rnd)
    ops = []
    n = rnd.choice((0, 1, 2, 3, 8, 32))
    so, ds = sign_ops(rnd, n)
    ops += so
    ks = rnd.sample(range(4), rnd.choice((1, 2, 3)))
    for k in ks:
        w.car(k, pl=rnd.choice((0, 0, 1)))
    ops = w.ops + ops
    nfacts = rnd.randrange(1, 4)
    for i in range(nfacts):
        ops.append("%%fa %d %d %d %d %d" % (
            i, rnd.choice((0, 2, 5, 11, -1)), rnd.randrange(0, 700),
            rnd.choice((0, 1)), rnd.choice((0, 1))))
    for k in ks:
        ops.append("%%d %d %s" % (k, dist_near(rnd, ds)))
        ops.append("%%ci %d %d" % (k, rnd.choice(INDICES)))
        ops.append("%%n %d" % k)
        ops.append("%%dr %d" % k)
    for _ in range(rnd.randrange(6, 16)):
        k = rnd.choice(ks)
        c = rnd.randrange(17)
        if c == 0:
            ops.append("%%dn %d" % k)
        elif c == 1:
            ops.append("%%sk %d %s" % (k, " ".join(
                "%08x" % rnd.choice((0, 1, 2, 3, 0xffffffff,
                                     rnd.getrandbits(32)))
                for _ in range(NSTICKY))))
            ops.append("%%cs %d" % k)
        elif c == 2:
            ops.append("%%cur %d %d" % (k, rnd.randrange(-1, nfacts)))
            ops.append("%%cat %d" % k)
        elif c == 3:
            ops.append("%%force %d %d" % (k, rnd.choice((0, 2, 5, 10, 11))))
        elif c == 4:
            ops.append("%%ex %d %d" % (k, rnd.choice((-1, 0, 1, 2, 3))))
            ops.append("%%gx %d" % k)
        elif c == 5:
            ops.append("%%gdl %d" % k)
            ops.append("%%dd %d" % k)
        elif c == 6:
            ops.append("%%af %d %s" % (k, h(f32(rnd.uniform(-2.0, 5.0)))))
        elif c == 7:
            ops.append("%%ob %d %s" % (k, h(f32(rnd.choice(SECS)))))
        elif c == 8:
            ops.append("%%bf %d %s" % (k, h(f32(rnd.uniform(0.5, 3.0)))))
            ops.append("%%fb %d %s" % (k, h(f32(rnd.choice(
                (0.0, 1.0, 1.5, 2.0, -1.0))))))
        elif c == 9:
            ops.append("%%rb %d" % k)
        elif c == 10:
            ops.append("%%a %d %d" % (k, rnd.choice(ANGLES)))
            ops.append("%%st %d" % k)
        elif c == 11:
            ops.append("%%d %d %s" % (k, dist_near(rnd, ds)))
            ops.append("%%ci %d %d" % (k, rnd.choice(INDICES)))
            # Sticky decisions in use and a previous line point, which
            # JustReset clears.
            if rnd.random() < 0.6:
                ops.append("%%sk %d %s" % (k, " ".join(
                    "%08x" % rnd.choice((1, 3, 0xffffffff,
                                         rnd.getrandbits(32)))
                    for _ in range(NSTICKY))))
            if rnd.random() < 0.6:
                ops.append("%%vp %d %s" % (k, " ".join(
                    h(f32(rnd.uniform(-500.0, 500.0))) for _ in range(4))))
            ops.append("%%jr %d" % k)
        elif c in (12, 13):
            ops += physics_ops(rnd, k, ks)
        elif c == 14:
            # CarController's: on my car, whichever car it is handed.
            other = rnd.choice([-1, k, k] + ks)
            for j in sorted({k, other} - {-1}):
                ops.append("%%mm %d %d" % (j, rnd.choice((0, 1, 2, 3, 4, 5,
                                                          6))))
                ops.append("%%pl %d %d" % (j, rnd.choice((0, 1))))
            ops.append("%%cc %d %d" % (k, other))
        elif c == 15:
            ops.append("%%cn %d %d" % (k, rnd.choice((0, 2, 11))))
        else:
            ops.append("%%K %d" % k)
    for k in ks:
        ops.append("%%cur %d %d" % (k, rnd.randrange(-1, nfacts)))
        ops.append("%%x %d %d" % (k, rnd.choice((0, 1, 2, 3))))
    return ops


def physics_ops(rnd, k, ks):
    """SetToPhysicsMode from each movement mode, for my car, another or
    none, a player's or not, over each default mode."""
    other = rnd.choice([-1, k] + list(ks))
    return ["%%G %d" % rnd.choice((4, 4, 1, 6, 0, 2)),
            "%%mm %d %d" % (k, rnd.choice((0, 1, 2, 3, 4, 5, 6, 6))),
            "%%pl %d %d" % (other if other >= 0 else k,
                            rnd.choice((0, 1))),
            "G TIMER %08x" % rnd.choice((0, 1000, 0x7fffffff)),
            "%%pm %d %d" % (k, other)]


def number_zero(w):
    """Route 0 filed under number 0, the first slot FindClosestTrackRoute
    takes past its `bltz`, its signs with it."""
    old = w.rn[0]
    if 0 in w.rn.values():
        return
    for i, op in enumerate(w.ops):
        f = op.split()
        if f[0] == "U" and f[1] == "0":
            f[3] = "0"
        elif f[0] == "K" and f[2] == str(old):
            f[2] = "0"
        else:
            continue
        w.ops[i] = " ".join(f)
    w.rn[0] = 0
    for p in w.pts[0]:
        p["rn"] = 0


def route_world(rnd, nsigns=None):
    """drivingchoice_check's walk world with its signs and decisions, my
    car (0) near a route and a few more about, their targets, the list,
    and my controller built, its table the test one."""
    w = World(rnd)
    if nsigns is None:
        nsigns = rnd.choice((0, 2, 4))
    sizes = walk_world(rnd, w, nsigns=nsigns)
    if rnd.random() < 0.25:
        number_zero(w)
    w.ops += decide(rnd, w)
    kr = rnd.randrange(5)
    j0 = rnd.randrange(sizes[kr] - 4)
    line = rnd.randrange(LINES)
    place_me(rnd, w, 0, kr, j0, line,
             dn=rnd.choice((0, 1, 5)), pl=rnd.choice((0, 0, 1)))
    # Every car has a box: WillIHitThisCar reads both cars'.
    boxed(rnd, w, 0)
    others = []
    for k in range(1, rnd.choice((1, 2, 3, 4))):
        place_other(rnd, w, sizes, k, rnd.randrange(5),
                    rnd.randrange(sizes[0] // 2), span=10)
        boxed(rnd, w, k)
        others.append(k)
    w.ops += seen_list(rnd, w, others)
    w.ops.append("G CAM %08x" % rnd.choice((M32, 0, 1, 5, 0)))
    w.ops.append("G NLINES %08x" % rnd.choice((3, 3, 1, 0, 2, 4)))
    if rnd.random() < 0.5:
        w.ops.append("G TIMER %08x" % rnd.randrange(1, 100000))
    for k in range(5):
        if rnd.random() < 0.4:
            w.ops.append(route_range(rnd, k))
    so, ds = sign_ops(rnd, rnd.choice((0, 1, 4)))
    w.ops += so
    w.ops.append("%%d 0 %s" % dist_near(rnd, ds))
    w.ops += ["%n 0", "%dr 0", "%v 0 1"]
    # The list's location and choice, which "%gl" can highlight and "%J"
    # copies.
    kr = rnd.randrange(5)
    if rnd.random() < 0.2:
        w.ops.append("D -1 -1 -1 0")
    else:
        w.ops.append("D %d %d %d %08x" % (
            kr, rnd.randrange(sizes[kr]), rnd.randrange(LINES),
            rnd.choice((0, 777))))
    w.ops.append("X %d -1 %d" % (rnd.randrange(5), rnd.choice((0, 1))))
    if rnd.random() < 0.6:
        w.ops.append("%J 0")
    return w, sizes, others


def route_range(rnd, k):
    """Route k's distances, so that the first pass takes it or not, and
    now and then its box far off."""
    s = f32(rnd.uniform(0.0, 3000.0))
    e = f32(rnd.choice((s + rnd.uniform(1.0, 800.0), s - rnd.uniform(1.0,
                                                                      800.0),
                        s)))
    if rnd.random() < 0.15:
        box = (2e6, 2e6, 3e6, 3e6)
    else:
        box = (-1000.0, -1000.0, 1000.0, 1000.0)
    return "%%U %d %s %s %s" % (k, h(s), h(e), " ".join(h(f32(v))
                                                         for v in box))


def rnum(rnd, w):
    rns = sorted(w.rn.values())
    c = rnd.randrange(6)
    if c == 0:
        return 0, 99
    if c == 1:
        r = rnd.choice(rns)
        return r, r
    if c == 2:
        return rnd.choice(rns) - 1, rnd.choice(rns) + 1
    if c == 3:
        return -5, rnd.choice(rns)
    if c == 4:
        return rns[-1], rns[0]
    return rnd.randrange(0, 50), rnd.randrange(50, 100)


def s_where(rnd):
    """The route methods: SetCurrentRoute, both getters with and without
    the find, out of bounds, FindWhereIAm, FindClosestTrackRoute and the
    line speed, through the test table or drivingchoice_check's."""
    w, sizes, others = route_world(rnd)
    ops = w.ops
    me = w.cars[0]
    home = "%%pos 0 %s %s %s" % (h(f32(me["px"])), h(f32(me["py"])),
                                 h(f32(me["pz"])))
    for _ in range(rnd.randrange(5, 12)):
        c = rnd.randrange(16)
        kr = rnd.randrange(5)
        if c == 0:
            first, last = rnum(rnd, w)
            ops.append("%%rn 0 %d %d" % (first, last))
            ops.append("%fw 0")
        elif c == 1:
            first, last = rnum(rnd, w)
            ops.append("%%fc 0 %d %d" % (first, last))
        elif c == 2:
            r, j = kr, rnd.randrange(sizes[kr])
            if rnd.random() < 0.15:
                r, j = rnd.choice(((-1, j), (r, -1), (-1, -1)))
            ops.append("%%sr 0 %d %d" % (r, j))
        elif c in (3, 4):
            if rnd.random() < 0.4:
                ops.append("%L 0 -1 -1 -1 0")
                first, last = rnum(rnd, w)
                ops.append("%%rn 0 %d %d" % (first, last))
            if rnd.random() < 0.3:
                ops.append("%v 0 2")
                ops.append("%%%s 0 %d" % (rnd.choice(("gr", "gp")),
                                          rnd.choice((0, 1))))
                ops.append("%v 0 1")
            else:
                ops.append("%%%s 0 %d" % (rnd.choice(("gr", "gp")),
                                          rnd.choice((0, 1, 1))))
        elif c == 5:
            ops.append("%oob 0")
        elif c == 6:
            ops.append(loc_op(rnd, sizes))
            ops.append("%oob 0")
            ops.append(rnd.choice(("%ls 0", "%seam 0")))
        elif c == 7:
            ops.append(rnd.choice(("%ls 0", "%seam 0")))
        elif c == 8:
            ops.append(route_range(rnd, kr))
        elif c == 9:
            ops.append("%%d 0 %s" % h(f32(rnd.uniform(-100.0, 3500.0))))
        elif c == 10:
            ops.append("%K 0")
        elif c == 12:
            # Through _vt$15AICarController, whose SetCurrentRoute the
            # find takes.
            first, last = rnum(rnd, w)
            ops += ["%v 0 0", "%%fc 0 %d %d" % (first, last), "%v 0 1"]
        elif c == 13:
            # High above the routes or below them, where the height
            # decides which is closest.
            ops.append("%%pos 0 %s %s %s" % (
                h(f32(me["px"])), h(f32(me["py"])),
                h(f32(me["pz"] + rnd.choice((30.0, -30.0, 200.0, -200.0))))))
            # Over every route, so that there is a choice to make.
            if rnd.random() < 0.5:
                ops.append("%fc 0 0 99")
            else:
                ops.append("%rn 0 0 99")
                ops.append("%fw 0")
            ops.append(home)
        elif c == 14:
            # Exactly on the location's point, where the cross product is
            # zero.
            j = rnd.randrange(sizes[kr])
            p = w.pts[kr][j]
            ops.append("%%pos 0 %s %s %s" % (h(p["x"]), h(p["y"]),
                                             h(f32(me["pz"]))))
            ops.append("%%L 0 %d %d %d 0" % (kr, j, rnd.randrange(LINES)))
            ops.append("%oob 0")
            ops.append(home)
        elif c == 15:
            # Two routes alike, so the first of them in the table is the
            # closest.
            k2 = rnd.choice([x for x in range(5) if x != kr])
            ops.append("%%cp %d %d" % (kr, k2))
            lo, hi = sorted((w.rn[kr], w.rn[k2]))
            first, last = rnd.choice(((lo, hi), (0, 99),
                                      (lo - 1, min(hi + 1, 99))))
            if rnd.random() < 0.5:
                ops.append("%%fc 0 %d %d" % (first, last))
            else:
                ops.append("%%rn 0 %d %d" % (first, last))
                ops.append("%fw 0")
        else:
            ops.append("%%gl 0 %d %d %d %d" % (
                kr, rnd.randrange(sizes[kr]), rnd.choice((0, 1)),
                rnd.choice((-1, 0, 1))))
    return ops


def loc_op(rnd, sizes):
    """The location set by hand: a route's point and a line from -1 to 20,
    or clear, a point with no route. Never a route with no point, which
    the game doesn't make: IsClear tests the route alone, and every reader
    here reads the point when it is set."""
    kr = rnd.randrange(5)
    j = rnd.randrange(sizes[kr])
    c = rnd.randrange(10)
    if c == 0:
        return "%%L 0 -1 %d %d 0" % (j, rnd.randrange(LINES))
    line = rnd.choice((-1, -1, 0, 20, rnd.randrange(LINES)))
    return "%%L 0 %d %d %d %08x" % (kr, j, line, rnd.choice((0, 1234)))


def s_line(rnd):
    """GetNewDrivingLine over every count of lines to consider, from the
    location or none, highlighted or not, past cars that block lines."""
    w, sizes, others = route_world(rnd)
    ops = w.ops
    for _ in range(rnd.randrange(3, 7)):
        kr = rnd.randrange(5)
        j = rnd.randrange(sizes[kr])
        r = kr
        c = rnd.random()
        if c < 0.08:
            r = -1
        elif c < 0.16:
            j = -1
        if rnd.random() < 0.3:
            ops.append("G NLINES %08x" % rnd.choice((0, 1, 2, 3, 4)))
        if rnd.random() < 0.3:
            ops.append("G CAM %08x" % rnd.choice((M32, 0, 1, 5)))
        ops.append("%%gl 0 %d %d %d %d" % (r, j, rnd.choice((0, 1)),
                                           rnd.choice((-1, 0, 1, 1))))
    return ops


def s_relax(rnd):
    """GetNewDrivingLine and SetCurrentRoute where the switch decides: my
    car off its line and past 29.5 m/s, where a relaxed switch comes back
    0.25 m a point and any other 0.5, or comes back not at all, the clock
    well past a switch's 3 s, the grace period over, and slower cars ahead
    on the line or beside it, at distances where coming back sooner or
    later decides whether one is hit within the threshold."""
    w = World(rnd)
    ops = w.ops
    sizes = walk_world(rnd, w, nsigns=0)
    kr = rnd.randrange(5)
    j0 = rnd.randrange(sizes[kr] - 8)
    p = w.pts[kr][j0]
    cls = rnd.randint(0, 8)
    line = 2 * cls
    hd = heading_of(p)
    off = rnd.choice((-1.0, 1.0)) * rnd.choice((2.0, 2.5, 3.0, 3.5,
                                                rnd.uniform(1.5, 4.5)))
    x, y = dcc.beside(p, dcc.off_of(p, line) + off, 1.0)
    sp = rnd.choice((30.0, 35.0, 40.0, 50.0))
    w.car(0, px=x, py=y, bx=math.cos(hd), by=math.sin(hd), vmag=sp,
          vx=sp * math.cos(hd), vy=sp * math.sin(hd), cls=cls, dtype=2,
          ctl=rnd.choice((0, 1, 2, 4)), oob=0.0, pl=0, nw=4, fs=sp,
          dn=rnd.choice((0, 1, 5)), act=-1)
    boxed(rnd, w, 0)
    others = []
    for k in range(1, rnd.choice((2, 2, 3))):
        j = j0 + rnd.choice((1, 1, 2, 2, 3, 5))
        q = w.pts[kr][j]
        lat = dcc.off_of(q, line) + rnd.choice(
            (0.0, rnd.uniform(-1.0, 1.0), off * rnd.uniform(0.1, 0.6)))
        v = rnd.choice((5.0, 10.0, 15.0, 20.0, 25.0))
        qx, qy = dcc.beside(q, lat, rnd.uniform(-2.0, 2.0))
        qh = heading_of(q)
        w.car(k, px=qx, py=qy, bx=math.cos(qh), by=math.sin(qh), vmag=v,
              vx=v * math.cos(qh), vy=v * math.sin(qh), nw=4, pl=0,
              dtype=rnd.choice((1, 2, 3)), ctl=rnd.choice((0, 2, 3)),
              oob=0.0, fs=v, act=rnd.choice((-1, 0, 5)))
        boxed(rnd, w, k)
        # Its own target: on along the route where it is across it.
        ops.append("H %d 0 %s 0 0 0" % (k, h(f32(40.0))))
        for i in range(rnd.choice((4, 6, 8))):
            jj = min(sizes[kr] - 1, j + i)
            f = dcc.tgt_point(w, kr, jj, lat, line, sp=v).split()
            ops.append("I %d %s" % (k, " ".join(f[1:])))
        others.append(k)
    ops += seen_list(rnd, w, others)
    ops.append("G TIMER %08x" % rnd.randrange(20000, 200000))
    ops.append("G GRACE %s" % h(f32(0.0)))
    ops.append("G NLINES %08x" % rnd.choice((1, 1, 2, 3)))
    if rnd.random() < 0.5:
        ops.append("G AVOID %s" % h(f32(rnd.choice((1.0, 2.0, 3.0)))))
    ops += ["%d 0 0", "%n 0", "%dr 0", "%v 0 1",
            "D %d %d %d 00000000" % (kr, j0, line), "X 1 -1 0", "%J 0"]
    for _ in range(rnd.randrange(1, 4)):
        j = min(sizes[kr] - 1, j0 + rnd.choice((0, 0, 1)))
        ops.append("%%gl 0 %d %d 0 -1" % (kr, j))
        ops.append("%%gl 0 %d %d 1 -1" % (kr, j))
        ops.append("%L 0 -1 -1 -1 0")
        ops.append("%%sr 0 %d %d" % (kr, j))
    return ops


def s_action(rnd):
    """InterruptAction forced and not, over scores either way, and
    GeneratePointsToFulfillAction answered both ways, over each kind of
    choice and the location's line or another."""
    w, sizes, others = route_world(rnd)
    ops = w.ops
    nf = rnd.randrange(2, NFACTS + 1)
    for i in range(nf):
        ops.append("%%fa %d %d %d %d %d" % (
            i, rnd.choice((0, 1, 2, 5, 6, 10)),
            rnd.choice((0, 100, 300, 300, 500, 600, -1)),
            rnd.choice((0, 1, 1)), rnd.choice((0, 1))))
    if rnd.random() < 0.5:
        ops.append("%%sr 0 %d %d" % (0, rnd.randrange(sizes[0])))
    for _ in range(rnd.randrange(4, 10)):
        c = rnd.randrange(8)
        if c in (0, 1):
            q = [rnd.randrange(-1, nf) for _ in range(rnd.randrange(0, 4))]
            ops.append("%q " + " ".join("%d" % i for i in q) if q else "%q")
            if rnd.random() < 0.5:
                ops.append("%%force 0 %d" % rnd.choice((0, 2, 5, 11, 11)))
            ops.append("%%cur 0 %d" % rnd.randrange(-1, nf))
            if rnd.random() < 0.3:
                ops.append("%v 0 0")
                ops.append("%ia 0")
                ops.append("%v 0 1")
            else:
                ops.append("%ia 0")
        elif c in (2, 3, 4):
            i = rnd.randrange(nf)
            ops.append("%%fa %d %d %d %d %d" % (
                i, rnd.choice((0, 2, 5)), rnd.randrange(0, 700),
                rnd.choice((0, 1)), rnd.choice((0, 1))))
            # A second answer for the action ChooseNewAction hands back,
            # so that its CalculatePointsToDrive has an action to run on.
            ops.append("%%q %d" % rnd.randrange(nf))
            ops.append("%%cur 0 %d" % rnd.randrange(-1, nf))
            ops.append("%%ch 0 %d %d %d" % (
                rnd.choice((0, 1, 2, 3, 4, 4, 5, 6, 7, -1)),
                rnd.choice((-1, -1, 1)), rnd.choice((0, 1))))
            if rnd.random() < 0.5:
                ops.append(loc_op(rnd, sizes))
            ops.append("%%gpf 0 %d" % i)
        elif c == 5:
            ops.append("%cat 0")
        elif c == 6:
            ops.append("%%cn 0 %d" % rnd.choice((0, 2, 11)))
        else:
            ops.append("%K 0")
    ops.append("%%cur 0 %d" % rnd.randrange(-1, nf))
    ops.append("%%x 0 %d" % rnd.choice((0, 1, 2, 3)))
    return ops


# ---- 11e-2's: the signposts and sticky decisions

F11 = f32(1.1)                    # gp-29840
TICK = f32(0.00025)               # gp-29836


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def ulp(x, n=1):
    """f32 x moved n ulps, down for a negative n, across zero."""
    b = fbits(x)
    i = -(b & 0x7fffffff) if b >> 31 else b
    i += n
    b = i if i >= 0 else 0x80000000 | -i
    return struct.unpack("<f", struct.pack("<I", b))[0]


def around(x):
    return (ulp(x, -1), x, ulp(x, 1))


def look_ahead(v, secs=2.0):
    """DoStickyDecisions' look-ahead for a speed, in floats."""
    a = f32(f32(secs) * f32(f32(v) * F11))
    return min(250.0, max(a, 100.0))


def edge_speed(rnd, target, secs=2.0):
    """A speed whose look-ahead comes out at the target, or an ulp or two
    from it."""
    v = f32(target / secs / F11)
    return ulp(v, rnd.choice((-2, -1, 0, 0, 1, 2)))


def grace_ticks(g):
    """The race clocks either side of the first one past SignpostGracePeriod
    g, in floats: on track 1 that is 4001, as 4000 ticks come to exactly
    1 s."""
    t = 4000 * g - 3
    while not float(g) < f32(f32(t) * TICK):
        t += 1
    return (t - 2, t - 1, t - 1, t, t, t + 1)


def clamp_skill(s):
    return 0 if s < 0 else 9 if s > 9 else s


SIGN_SPEEDS = (0.0, 5.0, 20.0, 35.0, 60.0, 80.0, 100.0, 150.0, -10.0)
SKILLS_TRIED = (-128, -3, -1, 0, 0, 1, 2, 4, 8, 9, 10, 12, 127)
CHANCES = (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)
HINTS = (0, 0, 1, 1, 2, 2, 3, -1)


def sign_flags(rnd, sign=None):
    """A sign's Flags byte: its Sign, now and then Backwards or Cloaked,
    and the bits SignPostDecision never reads."""
    f = rnd.choice((0, 0, 1, 1, 2, 2, 2, 3, 4, 4, 5, 6, 7)) if sign is None \
        else sign
    if rnd.random() < 0.12:
        f |= 0x08
    if rnd.random() < 0.15:
        f |= 0x40
    if rnd.random() < 0.3:
        f |= rnd.choice((0x10, 0x20, 0x80, 0xb0))
    return f


def sign_routes(rnd, w, sizes, n, flags=None):
    """Signs 0 to n-1 each leading on to a point of a route, now and then
    to a number with no route; each one's Flags kept in `flags`."""
    ops = []
    for i in range(n):
        k2 = rnd.randrange(5)
        rn = w.rn[k2] if rnd.random() < 0.92 else 98
        ops.append("K %d %d %d" % (i, rn, rnd.randrange(sizes[k2] - 5)))
        f = sign_flags(rnd)
        if flags is not None:
            flags[i] = f
        ops.append("%%sf %d %d %d" % (i, f, rnd.choice(HINTS)))
    return ops


def chance_ops(rnd, sk=None):
    """A skill level's TakeSignChance: three rising, or not."""
    s = rnd.randrange(NSKILLS) if sk is None else sk
    cs = sorted(rnd.choice(CHANCES) for _ in range(3))
    if rnd.random() < 0.15:
        rnd.shuffle(cs)
    return "%%tsc %d %s" % (s, " ".join(h(f32(c)) for c in cs)), cs


def draws_for(rnd, cs, eq=False):
    """World::Random's answers: at and either side of the chances, or of
    an Equivalent sign's 0.5, 0, 1, a NaN or anything."""
    out = []
    for _ in range(rnd.randrange(1, 4)):
        c = rnd.randrange(8)
        if eq and c < 5:
            x = rnd.choice(around(f32(0.5)))
        elif c < 4:
            x = rnd.choice(around(f32(rnd.choice(cs))))
        elif c == 4:
            x = rnd.choice(around(f32(0.5)))
        elif c == 5:
            x = rnd.choice((0.0, 1.0, f32(0.999)))
        elif c == 6:
            out.append("7fc00000")
            continue
        else:
            x = f32(rnd.random())
        out.append(h(x))
    return "%%rnd %d %s" % (len(out), " ".join(out))


def grace_ops(rnd, clock):
    """The track's SignpostGracePeriod: none (-1), so the race's grace
    period decides, or a time with the race clock either side of it."""
    ops = ["%%tn %d" % rnd.choice((0, 0, 3, 7, 12, 15))]
    c = rnd.randrange(5)
    if c < 2:
        ops.append("%tg -1")
        ops.append("G TIMER %08x" % clock)
        ops.append("R %08x" % ((clock - rnd.choice(dcc.GRACE_AGO)) & M32))
    else:
        g = rnd.choice((0, 1, 5, 12, 30, -2, 1000000))
        ops.append("%%tg %d" % g)
        if abs(g) < 1000 and rnd.random() < 0.8:
            t = rnd.choice(grace_ticks(g))
        else:
            t = rnd.choice((0, 1, 4000, 48000, 0x7fffffff, -4000))
        ops.append("%%rt 0 %08x" % (t & M32))
    return ops


def sticky_words(rnd, nsg, i=None, full=False, dsd=False):
    """Eight sticky decisions: used or not, taken or not, any line, and a
    sign's index, now and then sign i's. For DoStickyDecisions every used
    one's sign is one of ours, which it reads."""
    ws = []
    for _ in range(NSTICKY):
        used = 1 if full else rnd.choice((0, 0, 1))
        if dsd:
            s = rnd.randrange(nsg)
        elif i is not None and rnd.random() < 0.3:
            s = i
        else:
            s = rnd.randrange(256) if rnd.random() < 0.2 else rnd.randrange(nsg)
        hi = rnd.getrandbits(16) if rnd.random() < 0.3 else 0
        ws.append((hi << 16) | (s << 8) | (rnd.randrange(64) << 2)
                  | (rnd.randrange(2) << 1) | used)
    return "%%sk 0 %s" % " ".join("%08x" % v for v in ws)


def s_signdec(rnd):
    """SignPostDecision on every kind of sign and flag, inside the sign
    grace period and out of it, the race's or the track's, through each
    skill level's chances with draws at and either side of the row the
    car's skill clamps to (an Equivalent sign's at 0.5), over sticky
    decisions for the sign and not, every slot used and not, from a line
    of -1, 0, 1 and past, at the location or with it clear, its line 0 or
    1 now and then."""
    w, sizes, others = route_world(rnd, nsigns=rnd.choice((2, 4, 6)))
    ops = w.ops
    nsg = rnd.choice((4, 8, 12))
    flags = {}
    ops += sign_routes(rnd, w, sizes, nsg, flags)
    ops.append("%%NS %d" % nsg)
    clock = rnd.choice((100000, 200000, 5000))
    ops += grace_ops(rnd, clock)
    rows = {}
    for s in range(NSKILLS):
        if rnd.random() < 0.5:
            op, rows[s] = chance_ops(rnd, s)
            ops.append(op)
    sk = [0]

    def skill():
        sk[0] = rnd.choice(SKILLS_TRIED)
        ops.append("@sk 0 %d" % sk[0])
        s = clamp_skill(sk[0])
        # The row the skill comes to, set more often than not.
        if s not in rows or rnd.random() < 0.3:
            op, rows[s] = chance_ops(rnd, s)
            ops.append(op)

    skill()
    for _ in range(rnd.randrange(6, 14)):
        i = rnd.randrange(nsg)
        c = rnd.randrange(12)
        if c == 0:
            ops += grace_ops(rnd, clock)
        elif c == 1:
            skill()
        elif c == 2:
            ops.append(sticky_words(rnd, nsg, i,
                                    full=rnd.random() < 0.3))
        elif c == 3:
            ops.append(rnd.choice(("%cs 0", "%gsi 0")))
        elif c == 4:
            ops.append(loc_op(rnd, sizes))
        elif c == 5:
            ops.append("%%L 0 -1 -1 %d 0" % rnd.choice((-1, 0, 1, 1)))
        if c >= 6 or rnd.random() < 0.3:
            if rnd.random() < 0.5:
                flags[i] = sign_flags(rnd)
                ops.append("%%sf %d %d %d" % (i, flags[i],
                                              rnd.choice(HINTS)))
            row = rows.get(clamp_skill(sk[0]), [0.0, 0.0, 0.0])
            ops.append(draws_for(rnd, row, eq=flags[i] & 7 == 4))
            ops.append("%%spd 0 %d %d" % (i, rnd.choice((-1, -1, -1, 0, 1,
                                                          2, 3, 20, -2))))
    return ops


def s_takechance(rnd):
    """The draw by skill on its own: past the sign grace period, each Sign
    that reaches TakeSignChance (Faster, Slower, Stop and the two with no
    name), the draw at and either side of each of the skill's three
    chances, rising strictly or with two of them equal, the decisions
    cleared before each."""
    w, sizes, others = route_world(rnd, nsigns=4)
    ops = w.ops
    nsg = 6
    ops += sign_routes(rnd, w, sizes, nsg)
    ops += ["%%NS %d" % nsg, "%tg 0", "%rt 0 00010000"]
    sk = rnd.choice(SKILLS_TRIED)
    ops.append("@sk 0 %d" % sk)
    cs = sorted(f32(v) for v in rnd.sample((0.1, 0.25, 0.4, 0.5, 0.6, 0.75,
                                            0.9), 3))
    if rnd.random() < 0.25:
        j = rnd.randrange(2)
        cs[j + 1] = cs[j]
    ops.append("%%tsc %d %s" % (clamp_skill(sk), " ".join(h(c) for c in cs)))
    for _ in range(rnd.randrange(8, 16)):
        i = rnd.randrange(nsg)
        ops.append("%%sf %d %d %d" % (i, rnd.choice((0, 0, 1, 1, 3, 6, 7)),
                                      rnd.choice(HINTS)))
        x = rnd.choice(around(rnd.choice(cs)) + (0.0, 1.0))
        ops += ["%%rnd 1 %s" % h(x), "%cs 0"]
        ops.append("%%spd 0 %d %d" % (i, rnd.choice((-1, 0, 1))))
    return ops


def s_sticky(rnd, edge=False):
    """FindSignpostIndex, GetStickyIndex and DoStickyDecisions: decisions
    dropped exactly 10 m past their sign and either side, the look-ahead
    at its 100 and 250 m clamps and between, signs behind me, at me and
    exactly the look-ahead on, the index wrapping at NumSignposts, the
    track's length or none, and the decision on a sign the car took
    forgotten with it. There is always a sign past the look-ahead, else
    retail goes round its signs for ever. With `edge`, the speed puts the
    look-ahead at its 250 m clamp and the first sign just inside it, where
    a clamp of 249 would stop short."""
    w, sizes, others = route_world(rnd, nsigns=rnd.choice((2, 4)))
    ops = w.ops
    tlen = rnd.choice((0.0, 0.0, 5000.0, 3000.0))
    ops.append("G TLEN %s" % h(f32(tlen)))
    nsg = rnd.choice((2, 3, 4, 8, 12, 16))
    ops += sign_routes(rnd, w, sizes, nsg)
    ops.append("%%NS %d" % nsg)
    clock = rnd.choice((100000, 200000))
    ops += grace_ops(rnd, clock)
    ops.append("@sk 0 %d" % rnd.choice(SKILLS_TRIED))
    op, cs = chance_ops(rnd, 0)
    ops.append(op)
    exact = rnd.random() < 0.6
    mine = 0.0 if exact else f32(rnd.choice((100.0, 1234.5, 2990.0,
                                              4990.0, 20.0)))
    secs = 2.0 if rnd.random() < 0.7 else rnd.choice((1.0, 3.0))
    c = 1 if edge else rnd.randrange(4)
    if c == 0:
        v = edge_speed(rnd, 100.0, secs)
    elif c == 1:
        v = edge_speed(rnd, 250.0, secs)
    else:
        v = f32(rnd.choice(SIGN_SPEEDS))
    ahead = look_ahead(v, secs)
    rels = []
    for _ in range(nsg - 1):
        c = rnd.randrange(9)
        if c == 0:
            rels.append(rnd.choice(around(-10.0)))
        elif c == 1:
            rels.append(rnd.choice(around(ahead)))
        elif c == 2:
            rels.append(rnd.choice((0.0, -0.0, ulp(0.0, 1), -ulp(0.0, 1))))
        elif c == 3:
            rels.append(rnd.choice((-5.0, -50.0, -400.0, -2600.0)))
        elif c == 4:
            rels.append(f32(rnd.uniform(0.0, ahead)))
        elif c == 5:
            rels.append(f32(rnd.uniform(-300.0, 600.0)))
        else:
            rels.append(f32(rnd.uniform(-20.0, 260.0)))
    if edge:
        rels[0] = rnd.choice((ulp(ahead, -1), ulp(ahead, -2), 249.5,
                              249.0, ulp(249.0, 1)))
        rels[1:] = [f32(r - 300.0) if 0.0 <= r < 260.0 else r
                    for r in rels[1:]]
    rels.append(1000.0)
    if rnd.random() < 0.8:
        rels.sort()
    else:
        rnd.shuffle(rels)
    ds = [f32(mine + r) for r in rels]
    for i, d in enumerate(ds):
        ops.append("%%S %d %s" % (i, h(d)))
    ops.append("%%d 0 %s" % h(mine))
    ops.append("%%vm 0 %s" % h(v))
    ops.append("G SECS %s" % h(f32(secs)))
    ops.append(sticky_words(rnd, nsg, dsd=True, full=rnd.random() < 0.15))
    if rnd.random() < 0.6:
        ops.append("%%ts 0 %d" % rnd.choice((-1, 0, 1, 2, rnd.randrange(nsg))))
    ops.append("%%si 0 %d" % rnd.randrange(nsg))
    if edge:
        ops += ["%fsi 0", "%dsd 0"]
    for _ in range(rnd.randrange(3, 8)):
        c = rnd.randrange(8)
        if c == 0:
            ops.append("%fsi 0")
        elif c == 1:
            ops.append("%gsi 0")
        elif c == 2:
            # On a little: the decisions behind me go, more signs come in.
            mine2 = f32(mine + rnd.choice((0.0, 5.0, 10.0, 10.5, 50.0,
                                           100.0)))
            if all(f32(d - mine2) < 260.0 for d in ds):
                continue
            ops.append("%%d 0 %s" % h(mine2))
            mine = mine2
        elif c == 3:
            ops.append("%%vm 0 %s" % h(f32(rnd.choice(SIGN_SPEEDS))))
        elif c == 4:
            ops.append(sticky_words(rnd, nsg, dsd=True))
            ops.append("%%si 0 %d" % rnd.randrange(nsg))
        elif c == 5:
            ops.append(draws_for(rnd, cs))
        else:
            ops.append("%dsd 0")
    ops.append("%dsd 0")
    return ops


def s_signindex(rnd):
    """FindSignpostIndex from each sign, my car before the signs, at one,
    between them and past them all, with the entry past the table's end
    far ahead or not, so that where it wraps at NumSignposts decides; and
    GetStickyIndex over sticky decisions of every kind."""
    w = World(rnd)
    w.car(0, pl=0)
    ops = w.ops
    n = rnd.choice((1, 2, 3, 5, 8))
    ds = sorted(f32(rnd.uniform(-100.0, 1000.0)) for _ in range(n))
    if n > 1 and rnd.random() < 0.3:
        ds[1] = ds[0]
    for i, d in enumerate(ds):
        ops.append("%%S %d %s" % (i, h(d)))
    ops.append("%%S %d %s" % (n, h(f32(rnd.choice((1e6, 1e6, -1e6, ds[-1]))))))
    ops.append("%%NS %d" % n)
    ops += ["%%d 0 %s" % h(ds[0]), "%n 0"]
    for _ in range(rnd.randrange(4, 10)):
        c = rnd.randrange(6)
        if c == 0:
            mine = f32(ds[0] - 1.0)
        elif c == 1:
            mine = rnd.choice(ds)
        elif c == 2:
            mine = f32(rnd.uniform(ds[0], ds[-1]))
        elif c == 3:
            mine = ulp(ds[-1], 1)
        else:
            mine = f32(ds[-1] + rnd.choice((1.0, 500.0)))
        ops.append("%%d 0 %s" % h(mine))
        ops.append("%%si 0 %d" % rnd.randrange(n))
        ops.append("%fsi 0")
        if rnd.random() < 0.4:
            ops.append(sticky_words(rnd, n, full=rnd.random() < 0.3))
            ops.append("%gsi 0")
    return ops


def s_trackpoint(rnd):
    """GetCurrentTrackRoutePoint on the walk world: my car about a sign's
    point and the location a few points short of it, on the road, near an
    edge or off it, the location clear, and the signs taken or not."""
    w, sizes, others = route_world(rnd, nsigns=rnd.choice((4, 6, 8)))
    ops = w.ops
    nsg = w.nsign
    for i in range(nsg):
        ops.append("%%sf %d %d %d" % (
            i, sign_flags(rnd, rnd.choice((2, 2, 0, 1, 4, 5, None))),
            rnd.choice(HINTS)))
    ops.append("%%NS %d" % max(nsg, 1))
    clock = rnd.choice((100000, 200000))
    ops += grace_ops(rnd, clock)
    ops.append("@sk 0 %d" % rnd.choice(SKILLS_TRIED))
    op, cs = chance_ops(rnd, 0)
    ops.append(op)
    me = w.cars[0]
    ops.append("%%rn 0 %d %d" % rnd.choice(((0, 99), (0, 99), (0, 49))))
    for _ in range(rnd.randrange(3, 8)):
        if w.sign_points and rnd.random() < 0.8:
            kr, js = rnd.choice(w.sign_points)
        else:
            kr = rnd.randrange(5)
            js = rnd.randrange(sizes[kr])
        j = max(0, js - rnd.randrange(0, 5))
        jc = min(sizes[kr] - 1, js + rnd.choice((-1, 0, 0, 1, 2, 5, 30)))
        p = w.pts[kr][jc]
        lat = rnd.choice((0.0, rnd.uniform(-3.0, 3.0), p["rw"] + 0.5,
                          -p["lw"] - 0.5, p["rw"] + 1.5, -p["lw"] - 1.5,
                          p["rw"] + 10.0))
        x, y = dcc.beside(p, lat, rnd.uniform(-3.0, 8.0))
        ops.append("%%pos 0 %s %s %s" % (h(f32(x)), h(f32(y)),
                                         h(f32(me["pz"]))))
        if rnd.random() < 0.1:
            ops.append("%L 0 -1 -1 -1 0")
        else:
            ops.append("%%L 0 %d %d %d 0" % (kr, j, rnd.choice(
                (0, 1, rnd.randrange(LINES), -1))))
        if rnd.random() < 0.3:
            ops.append("%%hl 0 %s" % h(f32(rnd.choice((0.0, 1.0, 2.25,
                                                         5.0)))))
        if rnd.random() < 0.3:
            ops.append(sticky_words(rnd, max(nsg, 1),
                                    full=rnd.random() < 0.2))
        ops.append(draws_for(rnd, cs))
        ops.append("%gct 0")
    return ops


def s_trackpoint_edge(rnd):
    """GetCurrentTrackRoutePoint on a straight road along x, 25 m each side,
    so my car's offset across it is -y exactly: exactly the half length
    past either edge and an ulp either side, on its points and between,
    behind the location's point, and past the road's last point with a
    sign taken there or not."""
    w = World(rnd)
    ops = w.ops
    n0 = 12
    rn0, rn1 = rnd.sample(range(50), 2)
    sj = sorted(rnd.sample(range(n0), rnd.choice((0, 1, 2, 3, 4))))
    signs = {j: i for i, j in enumerate(sj)}
    pts = w.route(0, n0, rn0, x=-60.0, y=0.0, hd=0.0, turn=0.0,
                  smooth=True, signs=signs)
    w.route(1, 12, rn1, x=-60.0, y=60.0, hd=0.0, turn=0.0, smooth=True)
    for i in range(len(sj)):
        w.sign(1, rnd.randrange(8))
        ops.append("%%sf %d %d %d" % (
            i, sign_flags(rnd, rnd.choice((2, 2, 2, 0, 5))),
            rnd.choice(HINTS)))
    nsg = max(1, len(sj))
    ops.append("%%NS %d" % nsg)
    sp = f32(rnd.choice((0.0, 20.0)))
    w.car(0, px=pts[3]["x"], py=0.0, pz=0.0, bx=1.0, by=0.0, vmag=sp,
          vx=sp, vy=0.0, dn=0, cls=0, dtype=2, ctl=1, oob=0.0, rpr=-1,
          rpj=-1, ct=0, cc=-1, cx=0, act=-1, pl=0, nw=4, fs=sp)
    boxed(rnd, w, 0)
    ops += seen_list(rnd, w, [])
    ops.append("G TIMER %08x" % 100000)
    ops.append("R 00000000")
    ops.append("G TLEN %s" % h(0.0))
    ops += ["%d 0 0", "%n 0", "%dr 0", "%v 0 1",
            "D 0 3 0 00000000", "X 1 -1 0", "%J 0", "%rn 0 0 99"]
    ops.append("%tg -1")
    margin = f32(rnd.choice((2.25, 2.0, 0.0)))
    edge = f32(25.0 + margin)
    for _ in range(rnd.randrange(4, 9)):
        j = rnd.randrange(n0 - 1)
        c = rnd.randrange(6)
        if c < 3:
            along = rnd.choice((0.0, 0.5, 5.0, 9.5, 10.0, 20.0, -0.5))
            y = rnd.choice(around(edge) + around(-edge) + (0.0, 3.0))
        elif c == 3:
            along = rnd.choice((0.0, 5.0))
            y = f32(rnd.choice((0.0, 26.0, -26.0, 40.0)))
        else:
            # Past the last point.
            j = rnd.choice((n0 - 1, n0 - 2, n0 - 3, n0 - 5))
            along = 10.0 * (n0 - 1 - j) + rnd.choice((0.0, 0.5, 4.0, 30.0))
            y = f32(rnd.choice((0.0, 0.0, 10.0, -10.0)))
        x = f32(pts[j]["x"] + along)
        ops.append("%%pos 0 %s %s %s" % (h(x), h(y), h(0.0)))
        ops.append("%%L 0 0 %d %d 0" % (j, rnd.choice((0, 1, -1, 3))))
        ops.append("%%hl 0 %s" % h(margin))
        if rnd.random() < 0.3:
            ops.append(sticky_words(rnd, nsg, full=rnd.random() < 0.2))
        elif rnd.random() < 0.5:
            ops.append("%cs 0")
        ops.append("%gct 0")
    return ops


# ---------------------------------------------------------------- 11e-3's

T30 = 120000                      # 30 s of race time, in ticks
TIMERS = (0, 0x7fffffff, 1, 28000, 80000, 0x80000000, 0xffffffff)
UNSET_TIMERS = (0, 0x7fffffff)
BELT_STOP = (6, 7, 8, 9, 10)      # PullOver, GetUnstuck, AvoidRoadBlock,
                                  # IJustGotHit, AccidentRecovery


def below(x):
    """The float just under x."""
    return ulp(f32(x), -1)


def above(x):
    return ulp(f32(x), 1)


def near(x):
    x = f32(x)
    return rnd_pick(x, below(x), above(x))


def rnd_pick(*xs):
    return xs[_PICK.randrange(len(xs))]


_PICK = random.Random(0)


def unit3(rnd, flat=False):
    a = rnd.uniform(-math.pi, math.pi)
    e = 0.0 if flat else rnd.uniform(-0.3, 0.3)
    return (math.cos(a) * math.cos(e), math.sin(a) * math.cos(e),
            math.sin(e))


def turned(u, c, rnd):
    """A unit vector at the angle whose cosine is c from u, about z."""
    s = math.sqrt(max(0.0, 1.0 - c * c)) * rnd.choice((1, -1))
    x, y, z = u
    return (x * c - y * s, x * s + y * c, z)


def vec_op(op, k, v):
    return "%s %d %s" % (op, k, " ".join(h(f32(c)) for c in v))


def int_pos(rnd):
    return tuple(float(rnd.randint(-100, 100)) for _ in range(3))


def fword(s):
    """The float a hex word's bits make."""
    return struct.unpack("<f", struct.pack("<I", int(s, 16)))[0]


def gate_picker(rnd, gates, none=3, single=0.8, p_ok=0.85):
    """ok(gate) for one round: four rounds in five fail at most one of
    `gates`, chosen at random (or none), with every other passing; the rest
    pass each on its own with p_ok."""
    if rnd.random() < single:
        fail = rnd.choice(list(gates) + [None] * none)
        return lambda g: g != fail
    return lambda g: rnd.random() < p_ok


BELT_GATES = ("np", "demo", "ob", "rp", "fs", "nw", "act", "type", "skill",
              "range", "race")
BELT_TYPES = (0, 1, 2, 3, 4, 5, 11, 12, -1)


def s_belt(rnd):
    """WeCanHaveTheBelt over each of its tests either side, the race clock
    and the distance to the players at their edges, and WeHaveTheBelt and
    WeNeedTheBelt on the movement mode and bBeltMover."""
    w = World(rnd)
    me = int_pos(rnd)
    w.car(0, px=me[0], py=me[1], pz=me[2], pl=0, act=-1)
    ops = w.ops + ["%NS 0", "%n 0", "%dr 0"]
    for i in range(3):
        ops.append("%%fa %d %d 0 0 0" % (i, rnd.choice(BELT_TYPES
                                                       + BELT_STOP)))
    for _ in range(rnd.randrange(6, 14)):
        ok = gate_picker(rnd, BELT_GATES)
        ops.append("%%np 0 %d" % (rnd.choice((3, 4, 20)) if ok("np")
                                  else rnd.choice((0, 2, -1))))
        ops.append("%%RC %d" % (rnd.choice((0, 3, 9, 7)) if ok("demo")
                                else 8))
        for f in ("ob", "rp"):
            ops.append("%%kf 0 %s %08x" % (f, rnd.choice(UNSET_TIMERS)
                                            if ok(f)
                                            else rnd.choice(TIMERS[2:])))
        fs = (rnd.choice((5.0, above(5.0), 30.0)) if ok("fs")
              else rnd.choice((below(5.0), 0.0, -10.0)))
        nw = rnd.choice((1, 4)) if ok("nw") else rnd.choice((0, -1))
        ops.append("%%fsw 0 %s %d" % (h(f32(fs)), nw))
        if not ok("act"):
            i = -1
        else:
            i = rnd.randrange(3)
            ops.append("%%fa %d %d 0 0 0" % (i, rnd.choice(
                BELT_TYPES if ok("type") else BELT_STOP)))
        ops.append("%%cur 0 %d" % i)
        ops.append("@sk 0 %d" % (rnd.choice((-3, -1, 0, 5, 9)) if ok("skill")
                                 else -2))
        far = rnd.choice((120.0, above(120.0), 300.0, 1000.0)) \
            if ok("range") else rnd.choice((below(120.0), 119.0, 0.0))
        for j in range(2):
            d = far if j == 0 else rnd.choice((far, 1000.0, 5000.0))
            ax = rnd.randrange(3)
            pos = list(me)
            pos[ax] += d * rnd.choice((1, -1))
            ops.append(vec_op("%wp", j if rnd.random() < 0.5 else 1 - j,
                              pos))
        ops.append("%%rt 0 %08x" % (rnd.choice((T30, T30 + 1, 10 * T30))
                                    if ok("race")
                                    else rnd.choice((T30 - 1, 0, T30 // 2,
                                                     0xffffffff,
                                                     0x80000000))))
        ops.append("%wcb 0")
        if rnd.random() < 0.3:
            ops.append("%%mm 0 %d" % rnd.choice((0, 1, 4, 5, 6, 6, 7)))
            ops.append("%whb 0")
        if rnd.random() < 0.2:
            ops.append("%%bm %d" % rnd.choice((0, 1, 2, -1)))
            ops.append("%wnb 0")
    return ops


RATIO_OK = (0.939999998, 1.0, 1.2, 0.95)
RATIO_NO = (0.93999994, 0.5, 0.0)
# Each test's passing and failing values near its edge, held and taken.
GLUE_EDGES = {
    True: dict(dist=((0.0, 10.0, 59.0, 60.0), (61.0, 60.5, 100.0)),
               dv=((0.0, 5.0, 9.0, 10.0),
                   (above(10.0), above(10.0), 10.5, 11.0, 30.0)),
               dot=((1.0, 0.9, 0.6, 0.51), (0.49, 0.3, -0.5, -1.0))),
    False: dict(dist=((0.0, 10.0, 29.0, 30.0), (31.0, 30.5, 45.0, 100.0)),
                dv=((0.0, 3.0, 5.5, 6.0),
                    (above(6.0), above(6.0), 6.5, 7.0, 30.0)),
                dot=((1.0, 0.9, 0.8, 0.71), (0.69, 0.6, 0.3, -1.0))),
}
# Unit vectors (x, y) whose x is a heading edge's dot exactly: x*x + y*y
# rounds to 1, so the VU0's normalise leaves them as they are. Held and
# taken, passing then failing.
GLUE_DOTS = {
    True: ((("3f000000", "3f5db3d7"), ("3f000001", "3f5db3d7")),
           (("3effffff", "3f5db3d7"),)),
    False: ((("3f333333", "3f36d211"), ("3f333334", "3f36d210")),
            (("3f333332", "3f36d212"),)),
}
GLUE_HELD_GATES = ("act", "type", "ratio", "on", "dist", "dv", "dot")
GLUE_TAKE_GATES = ("act", "type", "ratio", "off", "dist", "dv", "dot",
                   "ahead")


def glue_layout(rnd, me, k, held, np_):
    """Car k (a player's) placed, both cars moving, and my controller's
    timers and action, failing at most one test (gate_picker)."""
    ok = gate_picker(rnd, GLUE_HELD_GATES if held else GLUE_TAKE_GATES)
    ed = GLUE_EDGES[held]
    ops = ["%%P %d %d %s %s 4 4 %d" % (
        k, k - 1, h(f32(rnd.choice(RATIO_OK if ok("ratio") else RATIO_NO))),
        h(f32(1.0)), rnd.choice((0, 1, 2)))]
    d = rnd.choice(ed["dist"][0 if ok("dist") else 1])
    if rnd.random() < 0.5:
        pos = list(me)
        pos[rnd.randrange(3)] += d * rnd.choice((1, -1))
    else:
        u = unit3(rnd, flat=rnd.random() < 0.5)
        pos = [me[i] + d * u[i] for i in range(3)]
    ops.append(vec_op("%pos", k, pos))
    sm = rnd.choice((1.0, 20.0, rnd.uniform(1.0, 60.0)))
    st = rnd.choice((1.0, 20.0, rnd.uniform(1.0, 60.0)))
    if rnd.random() < 0.4:
        # The heading at its edge exactly: my car along an axis, theirs at
        # the edge's angle, both at powers of two.
        x, y = rnd.choice(GLUE_DOTS[held][0 if ok("dot") else 1])
        x, y = fword(x), fword(y) * rnd.choice((1, -1))
        sm, st = rnd.choice((1.0, 4.0, 32.0)), rnd.choice((1.0, 2.0, 16.0))
        ax, sg = rnd.randrange(2), rnd.choice((1, -1))
        mv = [0.0, 0.0, 0.0]
        tv = [0.0, 0.0, 0.0]
        mv[ax] = sg
        tv[ax] = sg * x
        tv[1 - ax] = y
    else:
        mv = unit3(rnd, flat=rnd.random() < 0.6)
        tv = turned(mv, rnd.choice(ed["dot"][0 if ok("dot") else 1]), rnd)
        if rnd.random() < 0.1:
            # Standing still: the normalise divides by zero.
            if rnd.random() < 0.5:
                sm = 0.0
            else:
                st = 0.0
    ops.append(vec_op("%vel", 0, [c * sm for c in mv]))
    ops.append(vec_op("%vel", k, [c * st for c in tv]))
    dv = rnd.choice(ed["dv"][0 if ok("dv") else 1])
    if dv in (above(10.0), above(6.0)) or rnd.random() < 0.4:
        # Exactly dv apart: one car's speed 0.
        a, z = f32(dv), 0.0
        if rnd.random() < 0.5:
            a, z = z, a
        ops.append("%%vm 0 %s" % h(a))
        ops.append("%%vm %d %s" % (k, h(z)))
    else:
        vm = f32(rnd.choice((20.0, 35.5, rnd.uniform(0.0, 60.0))))
        ops.append("%%vm 0 %s" % h(vm))
        ops.append("%%vm %d %s" % (k, h(f32(vm + dv * rnd.choice((1, -1))))))
    on = rnd.choice(TIMERS[2:] if ok("on") else UNSET_TIMERS)
    off = rnd.choice(UNSET_TIMERS if ok("off") else TIMERS[2:])
    ops.append("%%kf 0 on %08x" % (on if held or rnd.random() < 0.5
                                   else rnd.choice(TIMERS)))
    ops.append("%%kf 0 off %08x" % (off if not held or rnd.random() < 0.5
                                    else rnd.choice(TIMERS)))
    mine = rnd.randint(1, 8)
    theirs = rnd.randint(mine, 8) if ok("ahead") else rnd.randint(0, mine - 1)
    ops.append("%%rc 0 %d %s" % (mine, h(f32(rnd.uniform(0.0, 3.0)))))
    ops.append("%%rc %d %d %s" % (k, theirs, h(f32(rnd.uniform(0.0, 3.0)))))
    for j in range(1, np_):
        if j != k:
            ops.append("%%rc %d %d %s" % (j, rnd.randint(1, 8),
                                          h(f32(1.5))))
    ops.append("%%fa 0 %d 0 0 0" % (rnd.choice((0, 1, 2, 5, -1))
                                    if ok("type")
                                    else rnd.choice((6, 7, 10, 11))))
    ops.append("%%cur 0 %d" % (0 if ok("act") else -1))
    return ops


def s_glue(rnd):
    """WeCanHaveTheGlue held and taken over each test either side (the
    distance, speeds and headings at and near their edges, standing cars
    among them), GlueOn and GlueOff with the glue on and off, and
    GetGlueSpeed with and without both RacingCars."""
    w = World(rnd)
    me = int_pos(rnd)
    w.car(0, px=me[0], py=me[1], pz=me[2], pl=0, act=-1)
    np_ = rnd.choice((2, 3))
    for k in range(1, np_):
        w.car(k, pl=0, act=-1)
    ops = w.ops + ["%NS 0", "%n 0", "%dr 0"]
    for k in range(1, np_):
        ops.append("%%P %d %d %s %s 4 4 %d" % (
            k, k - 1, h(f32(1.0)), h(f32(1.0)), rnd.choice((0, 1, 3, -1))))
    ops.append("%%gds 0 %s" % h(f32(rnd.uniform(0.0, 60.0))))
    glued = None
    if rnd.random() < 0.5:
        glued = rnd.randrange(1, np_)
        ops.append("%%kf 0 glue %d" % glued)
        ops.append("%%kf 0 bias %s" % h(f32(rnd.choice(
            (0.2, 0.0, 0.5, rnd.uniform(-1.0, 1.0))))))
    for _ in range(rnd.randrange(6, 12)):
        k = glued if glued is not None else rnd.randrange(1, np_)
        ops += glue_layout(rnd, me, k, glued is not None, np_)
        c = rnd.randrange(10)
        if c < 5:
            # A player who isn't the glued one's, with the glue on.
            p = rnd.randrange(1, np_) if rnd.random() < 0.2 else k
            ops.append("%%wcg 0 %d" % p)
        elif c == 5:
            ops.append("%%gon 0 %d" % k)
            if glued is None:
                glued = k
        elif c == 6:
            ops.append("%goff 0")
            glued = None
        elif c == 7:
            ops.append(rnd.choice(("%whg 0", "%wng 0")))
        elif glued is not None:
            if rnd.random() < 0.3:
                ops.append("%%rc %d x" % rnd.choice((0, glued)))
            ops.append("%ggs 0")
        else:
            ops.append("%%wcg 0 %d" % k)
    return ops


def diff_ops(rnd):
    """TheDifficultyInfo's boost tables, filled: the distance graphs (seven
    rising points each), the position boosts, the speed-ratio rows, each
    skill's SlowFactor and the Misc frequency and range."""
    words = [0] * (DIFF_SIZE // 4)

    def put(off, x):
        words[off // 4] = fbits(f32(x))

    for base in (0, 56):
        xs = sorted(rnd.sample(range(-3000, 3000, 7), 7))
        for i, x in enumerate(xs):
            put(base + 8 * i, x + rnd.choice((0.0, 0.5)))
            put(base + 8 * i + 4, rnd.uniform(-0.3, 0.3))
    for i in range(32):
        put(112 + 4 * i, rnd.uniform(-0.3, 0.3))
    for i in range(32):
        put(240 + 4 * i, rnd.uniform(-2.0, 2.0))
    for s in range(NSKILLS):
        put(368 + SKILL_STRIDE * s + 20, rnd.choice(
            (rnd.uniform(0.5, 1.2), rnd.uniform(0.5, 1.2), 0.0, 1.0)))
    put(984, rnd.choice((0.0, 0.5, 1.0, 2.0, -1.0)))
    put(988, rnd.choice((500.0, 1e4, 1e5, 2000.0, -1.0, 0.0)))
    ops = []
    for off in range(0, DIFF_SIZE, 64):
        ops.append("%%dw %d %s" % (off, " ".join(
            "%08x" % v for v in words[off // 4:off // 4 + 16])))
    return ops


BOOST_GATES = ("npc", "boost", "full", "RC", "dc", "ba", "ab", "act",
               "race", "freq", "rc")


def boost_round(rnd, np_, catchup=False):
    """A race set up for the boost, failing at most one early out
    (gate_picker); for `catchup`, none, and the two-player race with the
    AI field and every place drawn round the split."""
    ok = (lambda g: True) if catchup else gate_picker(rnd, BOOST_GATES)
    ops = ["%%rp %d %d %d %d %s %s" % (
        rnd.choice((1, 2, 3)) if ok("npc") else rnd.choice((0, -1)),
        rnd.randrange(10) if catchup else rnd.choice((0, 1, 3, 4, 7, 8, 9)),
        rnd.choice((0, 0, 1)), 1 if ok("boost") else 0,
        h(f32(rnd.uniform(0.0, 2.0))), h(f32(rnd.uniform(0.0, 2.0))))]
    if catchup:
        n = 2
    elif np_ == 3:
        n = rnd.choice((1, 2, 2)) if rnd.random() < 0.8 else rnd.choice(
            (0, 3))
    else:
        n = 1 if rnd.random() < 0.8 else 0
    b0, b1 = (1, 2) if rnd.random() < 0.6 else (2, 1)
    if np_ == 2:
        b0 = b1 = 1
    ops.append("%%PT %d %d %d %d %d" % (n, rnd.randrange(1, np_), -1, b0,
                                         b1))
    if rnd.random() < 0.3:
        ops.append("%%sfe %d %d" % (rnd.choice((0, 1)), rnd.choice((0, 1))))
    if catchup:
        places = [rnd.randint(1, 8) for _ in range(np_)]
    else:
        places = list(range(1, 9))
        rnd.shuffle(places)
        if rnd.random() < 0.15:
            places[rnd.randrange(np_)] = 0
        if np_ == 3 and rnd.random() < 0.15:
            # The two players level.
            places[2] = places[1]
    for k in range(np_):
        ops.append("%%rc %d %d %s" % (k, places[k], h(f32(
            rnd.choice((0.0, 1.0, 2.0, 3.0)) + rnd.choice(
                (0.0, 0.25, 0.5, 0.75, rnd.uniform(0.0, 1.0)))))))
    ops.append("@sk 0 %d" % rnd.choice((-3, -1, 0, 1, 4, 8, 9)))
    for k in range(np_):
        ops.append("%%vm %d %s" % (k, h(f32(rnd.uniform(0.0, 60.0)))))
    for k in range(1, np_):
        ops.append("%%P %d %d %s %s %d %d 0" % (
            k, k - 1, h(f32(rnd.choice((1.0, 0.9, 1.1,
                                        rnd.uniform(0.5, 1.5))))),
            h(f32(rnd.choice((1.0, 1.2, 0.8, 2.0)))),
            4, 4 if ok("full") else rnd.choice((3, 0))))
    ops.append("%%RC %d" % (rnd.choice((0, 3)) if ok("RC") else 8))
    ops.append("%%dc %d" % (0 if ok("dc") else 1))
    ops.append("%%kf 0 ba %d" % (1 if ok("ba") else 0))
    ops.append("%%ab 0 %d" % (rnd.choice((1, 2)) if ok("ab") else 0))
    ops.append("%%cur 0 %d" % (0 if ok("act") else -1))
    ops.append("%%rt 0 %08x" % (rnd.choice((T30, T30 + 1, 3 * T30))
                                if ok("race")
                                else rnd.choice((T30 - 1, 0, 0xffffffff))))
    now = rnd.randrange(0, 400000)
    ops.append("G TIMER %08x" % now)
    if catchup:
        # Every frequency passes 8001 ticks on.
        lbt = 8001
    elif ok("freq"):
        lbt = rnd.choice((1, 2001, 4001, 8001, 100000, 400001))
    else:
        lbt = rnd.choice((0, 2000, 4000, 8000, -1, -4001))
    ops.append("%%kf 0 lbt %08x" % ((now - lbt) & M32))
    if not ok("rc"):
        ops.append("%rc 0 x")
    if rnd.random() < 0.3:
        ops.append("G TLEN %s" % h(f32(rnd.choice(
            (0.0, 1000.0, 3456.5, rnd.uniform(500.0, 8000.0))))))
    return ops


def s_boost(rnd, catchup=False):
    """CalculateDistanceAndPositionBoost and DecideBoostFactor over one
    player and two (each leading, and the AI car either side of the split),
    the catchup on and off, the cop race's lap fraction, the boost
    frequency and the race clock at their edges, and the speed ratio's
    table; for `catchup`, the two-player race with every early out passed,
    the split round each place."""
    w = World(rnd)
    w.car(0, pl=0, act=-1)
    np_ = 3 if catchup else rnd.choice((2, 3, 3))
    for k in range(1, np_):
        w.car(k, pl=0, act=-1)
    ops = w.ops + ["%NS 0", "%n 0", "%dr 0"]
    if not catchup and rnd.random() < 0.08:
        # My car a player's: no boost at all.
        ops.append("%%P 0 1 %s %s 4 4 0" % (h(f32(1.0)), h(f32(1.0))))
    ops += diff_ops(rnd)
    if catchup:
        # Every distance within range.
        ops.append("%%dw 988 %s" % h(f32(1e9)))
    ops.append("G TLEN %s" % h(f32(rnd.choice(
        (1000.0, 3456.5, rnd.uniform(500.0, 8000.0))))))
    ops.append("%fa 0 0 0 0 0")
    for _ in range(rnd.randrange(5, 10)):
        ops += boost_round(rnd, np_, catchup)
        if rnd.random() < 0.4:
            k = rnd.randrange(np_)
            ops.append("%%cdp 0 %d %d" % (rnd.choice((0, k)), k))
        ops.append("%dbf 0")
        if rnd.random() < 0.2:
            ops.append("%dbf 0")
    return ops


# ---- 11e-4's: the horn and ExecuteCurrentAction

HONK_GATES = ("usage", "real", "mine", "list", "care")
HONK_PASSING = f32(50.0)
HONK_CLOSING = f32(-3.0)


def ticks_round(x):
    """The tick counts either side of x seconds: the last whose time,
    (float)(int)t * TICK, is not past x, and the one after it."""
    x = f32(x)
    t = int(x / TICK)
    while f32(f32(float(t)) * TICK) > x:
        t -= 1
    while f32(f32(float(t + 1)) * TICK) <= x:
        t += 1
    return t, t + 1


def secs_of(t):
    return f32(f32(float(t)) * TICK)


def durations(rnd):
    return tuple(f32(rnd.choice((0.0, 0.25, 0.5, 0.75, 0.3, 0.125,
                                 rnd.uniform(0.0, 1.2))))
                 for _ in range(3))


def hk_op(rnd, k, start, on, sec, off):
    return "%%hk %d %d %d %d %08x %s %s %s %d" % (
        k, rnd.choice((0, 1, 1, 3)), rnd.choice((0, 1, 1, -2)),
        rnd.choice((0, 1, 1, 5)), start & M32, h(on), h(sec), h(off),
        rnd.choice((0, 0, 1, -1)))


def honk_guard(rnd, k, now):
    """The last request on car k, its whole cycle either side of the time
    since it started, so that a new one is taken or dropped."""
    on, off, sec = durations(rnd)
    cycle = f32(f32(on + off) + sec)
    lo, hi = ticks_round(cycle)
    ticks = rnd.choice((lo, hi, lo, hi, rnd.randrange(0, 10000), -5,
                        0x7fffffff))
    return hk_op(rnd, k, now - ticks, on, sec, off)


def honk_draws(rnd, chance, blink):
    """MaybeHonk's six draws: on, off and second within their ranges, then
    the two-honk, honk and blink draws round 0.5, the chance and the
    blink's."""
    def at(x):
        x = f32(x)
        return rnd.choice((x, below(x), above(x), x, below(x),
                           f32(rnd.random())))
    ds = [f32(rnd.choice((0.0, rnd.uniform(0.0, 0.4)))),
          f32(rnd.choice((0.0, rnd.uniform(0.0, 0.2)))),
          f32(rnd.choice((0.0, rnd.uniform(0.0, 0.4)))),
          at(0.5), at(chance), at(blink)]
    return "%%rnd 6 %s" % " ".join(h(d) for d in ds)


def honk_round(rnd, n):
    """One MaybeHonkAndOrBlinkHeadlights, failing at most one of its early
    outs (gate_picker): the car's usage, the race or its control, my
    control, the car missing from my list and DoWeCareAboutThisCar's edge;
    then the chance from its closing speed round 50 and -3 m/s, a traffic
    driver, a player and the list's count round 6, each draw round it."""
    ok = gate_picker(rnd, HONK_GATES)
    now = rnd.randrange(0, 1 << 22)
    ops = ["G TIMER %08x" % now]
    other = rnd.randrange(1, n)
    ops.append("@ut %d %d" % (other, rnd.choice((0, 3, 4, -1, 0x7fffffff))
                              if ok("usage") else rnd.choice((1, 2))))
    if ok("real"):
        st, ctl = rnd.choice(((8, rnd.choice((0, 1, 2, 3))),
                              (rnd.choice((0, 3, 7, 9)), 1)))
    else:
        st, ctl = rnd.choice((0, 3, 7, 9)), rnd.choice((0, 2, 3, 4))
    ops.append("%%RC %d" % st)
    ops.append("%%ctl %d %d" % (other, ctl))
    mine = rnd.choice((2, 2, 3)) if ok("mine") else rnd.choice((0, 1, 4))
    ops.append("%%ctl 0 %d" % mine)
    dtype = rnd.choice((3, 3, 0, 1, 2, 4))
    ops.append("%%dt 0 %d" % dtype)
    pl = rnd.random() < 0.3
    ops.append("%%pl %d %d" % (other, int(pl)))
    # My own list, which GetNearbyCar searches: a traffic car's must hold
    # the car, which past the count is not in it.
    cnt = rnd.choice((5, 6, 5, 6, 1, 3, 7, 12))
    in_list = ok("list") or mine == 3
    cars_in = [rnd.choice([-1] + [c for c in range(n) if c != other])
               for _ in range(min(16, cnt + 2))]
    if in_list:
        at_ = rnd.randrange(cnt)
        cars_in[at_] = other
        if rnd.random() < 0.3 and at_ + 1 < len(cars_in):
            cars_in[rnd.randrange(at_ + 1, len(cars_in))] = other
    elif rnd.random() < 0.5 and cnt < len(cars_in):
        cars_in[cnt] = other
    hd = f32(rnd.choice((0.9, 1.0, 2.2, 0.5)))
    D = f32(rnd.choice((1.0, 0.9, 2.25, 0.75, 1.5)))
    vy = f32(rnd.choice((50.0, above(50.0), below(50.0), -3.0, below(-3.0),
                         above(-3.0), 0.0, 20.0, -20.0, 80.0, -0.0)))
    # The list the call is given: the global one, or my own; the global
    # one, after the copy, its car, count and half size changed.
    lst = rnd.choice((0, 1))
    pme, pcnt, phd = 0, cnt, hd
    if lst == 0 and rnd.random() < 0.7:
        pme = 0 if ok("care") or rnd.random() < 0.5 else other
        pcnt = rnd.choice((5, 6, 0, -1, 16, cnt))
        phd = f32(rnd.choice((0.9, 1.0, 2.2, 0.5, hd)))
    bias = -0.5 if pl else 0.0
    edge = -f32(f32(D + phd) + bias)
    if ok("care"):
        py = rnd.choice((above(edge), above(edge), f32(edge + 3.0),
                         f32(rnd.uniform(edge, 60.0))))
    else:
        py = rnd.choice((edge, below(edge), f32(edge - 2.0)))
    ops.append("N 0 %d %s %s" % (cnt, h(f32(2.2)), h(hd)))
    first = True
    for i, c in enumerate(cars_in):
        if c == other and first:
            first = False
            ops.append("E %d %s %s %s %s %s %s %d" % (
                i, h(f32(rnd.uniform(-5.0, 5.0))), h(py),
                h(f32(rnd.uniform(-5.0, 5.0))), h(vy), h(f32(2.0)), h(D), c))
        else:
            ops.append("E %d %s %s %s %s %s %s %d" % (
                i, h(f32(rnd.uniform(-5.0, 5.0))),
                h(f32(rnd.uniform(-60.0, 60.0))),
                h(f32(rnd.uniform(-5.0, 5.0))),
                h(f32(rnd.uniform(-60.0, 60.0))), h(f32(2.0)),
                h(f32(rnd.choice((1.0, 0.9)))), c))
    ops.append("%J 0")
    if (pme, pcnt, phd) != (0, cnt, hd):
        ops.append("N %d %d %s %s" % (pme, pcnt, h(f32(2.2)), h(phd)))
    if HONK_PASSING < vy:
        chance = 1.0
    elif dtype == 3 and vy < HONK_CLOSING:
        chance = 1.0
    elif pl:
        chance = 0.75
    else:
        chance = 0.0750000030 if pcnt < 6 else 0.0500000007
    blink = 0.899999976 if HONK_PASSING < vy else 0.5
    ops.append(honk_draws(rnd, chance, blink))
    ops.append(honk_guard(rnd, 0, now))
    ops.append("%%mh 0 %d %d" % (other, lst))
    if rnd.random() < 0.3:
        ops.append("%%ish 0 %d" % rnd.choice((0, 1)))
        ops.append("%uh 0")
    return ops


def s_honk(rnd):
    """MaybeHonkAndOrBlinkHeadlights, round after round on my car (0) and
    the cars about, into HonkAndOrBlinkHeadlights as shipped."""
    w = World(rnd)
    n = rnd.randint(2, 6)
    for k in range(n):
        w.car(k, act=-1, pl=0)
    ops = w.ops + ["%NS 0", "%n 0", "%dr 0"]
    for _ in range(rnd.randrange(6, 12)):
        ops += honk_round(rnd, n)
    return ops


def s_lights(rnd):
    """HonkAndOrBlinkHeadlights and UpdateHeadlightsAndHorn on their own:
    the request's guard either side, each phase of the cycle at its edges,
    the time run backwards, the driver honking or not and a player's car
    passed over."""
    w = World(rnd)
    n = rnd.randint(1, 3)
    for k in range(n):
        w.car(k, act=-1, pl=0)
    ops = w.ops + ["%NS 0"]
    for _ in range(rnd.randrange(8, 16)):
        k = rnd.randrange(n)
        now = rnd.randrange(0, 1 << 22)
        ops.append("G TIMER %08x" % now)
        if rnd.random() < 0.4:
            ops.append(honk_guard(rnd, k, now))
            on, off, sec = durations(rnd)
            ops.append("%%hr %d %s %s %s %d %d %d" % (
                k, h(on), h(off), h(sec), rnd.choice((0, 1, 1, 4)),
                rnd.choice((0, 1, 1, -1)), rnd.choice((0, 1, 1, 3))))
        else:
            on, off, sec = durations(rnd)
            t1 = f32(on + on)
            edge = rnd.choice((on, t1, f32(f32(t1 - on) + off),
                               f32(f32(on + off) + sec)))
            lo, hi = ticks_round(edge)
            ticks = rnd.choice((lo, hi, lo - 1, hi + 1, -7,
                                rnd.randrange(0, 12000)))
            ops.append(hk_op(rnd, k, now - ticks, on, sec, off))
        ops.append("%%pl %d %d" % (k, int(rnd.random() < 0.15)))
        ops.append("%%ish %d %d" % (k, rnd.choice((0, 1, 2))))
        ops.append("%%uh %d" % k)
    return ops


EXEC_PATHS = ("clear", "easy", "boring", "own", "own", "sign", "timer",
              "line", "line", "line", "line")
EXEC_SKILLS = tuple(range(10)) + (-1, 10, -13, 21, -2, 15, 0, 9)
EXEC_LINES = tuple(range(LINES)) + (-1, 21)


def exec_diff(rnd):
    """TheDifficultyInfo filled with floats, as each skill's SpeedFactor
    and whatever a skill outside the table reads in its place."""
    words = [fbits(f32(rnd.uniform(-2.0, 2.0))) for _ in range(DIFF_SIZE // 4)]
    return ["%%dw %d %s" % (off, " ".join(
        "%08x" % v for v in words[off // 4:off // 4 + 16]))
        for off in range(0, DIFF_SIZE, 64)]


def exec_round(rnd, sizes, nsigns):
    """One ExecuteCurrentAction down one of its ways: the location clear,
    SuperEasyAI, BoringAIForCameraTuningOn, the action's own speed, the
    taken sign's point, TakenSignpostTimer's 99999 and the line's speed,
    the look-ahead drawn again either side of RoutePointChangeFrequency,
    the point clamped either end, a zero speed, a cop race and the boost
    either kept or set by DecideBoostFactor."""
    path = rnd.choice(EXEC_PATHS)
    now = rnd.randrange(1 << 20, 1 << 23)
    ops = ["G TIMER %08x" % now]
    kr = rnd.randrange(len(sizes))
    np_ = sizes[kr]
    j = rnd.randrange(np_)
    line = rnd.choice(EXEC_LINES)
    if path == "clear":
        ops.append("%%L 0 -1 -1 %d 00000000" % line)
    else:
        ops.append("%%L 0 %d %d %d %08x" % (kr, j, line,
                                            rnd.choice((0, now))))
    sea = rnd.choice((1, -1, 2)) if path == "easy" else 0
    bai = rnd.choice((1, -1, 2)) if path == "boring" else 0
    if path == "clear":
        sea, bai = rnd.choice((0, 1)), rnd.choice((0, 1))
    elif path == "easy":
        bai = rnd.choice((0, 1))
    ops.append("%%sea %d" % sea)
    ops.append("%%bai %d" % bai)
    if path == "own":
        use = 0
    elif path in ("clear", "easy", "boring"):
        use = rnd.choice((0, 1))
    else:
        use = rnd.choice((1, 1, 2, -1))
    ops.append("%%ad 0 %d %s %s %s %d" % (
        use, h(f32(rnd.uniform(-5.0, 80.0))), h(f32(rnd.uniform(0.0, 3.0))),
        h(f32(rnd.choice((0.0, 1.0, rnd.uniform(0.0, 10.0))))),
        rnd.choice((0, 1, 1, 2))))
    ops.append("%%at 0 %d %s" % (rnd.choice((0, 1, 5, 20)),
                                 h(f32(rnd.uniform(0.0, 300.0)))))
    ops.append("%%ts 0 %d" % (rnd.randrange(nsigns) if path == "sign"
                              else -1))
    ops.append("%%kf 0 tt %08x" % (
        rnd.choice((1, now, 0x80000000, 5, 0xffffffff)) if path == "timer"
        else rnd.choice((0, 0x7fffffff))))
    skill = rnd.choice(EXEC_SKILLS)
    ops.append("@sk 0 %d" % skill)
    # The look-ahead: the frequency either side of the time since its
    # switch, the variance's byte with the bytes after it set.
    freq = f32(rnd.choice((0.5, 0.25, 1.0, 2.0, 0.0, -1.0,
                           rnd.uniform(0.1, 5.0))))
    ops.append("%%dw 980 %s" % h(freq))
    lo, hi = ticks_round(freq) if freq >= 0 else (-1, 0)
    since = rnd.choice((lo, hi, lo, hi, 0, rnd.randrange(0, 40000), -3))
    ops.append("%%kf 0 lrs %08x" % ((now - since) & M32))
    var = rnd.choice((0, 1, 2, 5, 255, rnd.randrange(256)))
    if 0 <= skill < NSKILLS:
        ops.append("%%dw %d %08x" % (392 + SKILL_STRIDE * skill,
                                     var | rnd.getrandbits(24) << 8))
    drawn = 0 <= skill < NSKILLS and freq < secs_of(since)
    la = rnd.choice((-j - 1, -j, np_ - 1 - j, np_ - j,
                     rnd.randint(-j - 3, np_ - j + 3), 0))
    v = var + 1
    if drawn:
        answer = la + v
        if rnd.random() < 0.15:
            answer = rnd.choice((0, 2 * v - 1, 2 * v, -1))
        ops.append("%%rnd 1 %08x" % (answer & M32))
        ops.append("%%kf 0 la %d" % rnd.randint(-5, 5))
    else:
        ops.append("%%rnd 1 %08x" % rnd.randrange(0, 50))
        ops.append("%%kf 0 la %d" % la)
    if path == "line" and 0 <= line < LINES:
        i = min(max(j + la, 0), np_ - 1)
        ops.append("%%lsp %d %d %d %d" % (kr, i, line, rnd.choice(
            (0, 0, 1, 30, 255, rnd.randrange(256)))))
    ops.append("%%rp 0 0 %d 0 0 0" % rnd.choice((0, 0, 1, 2)))
    ops.append("%%sfe %d %d" % (rnd.choice((0, 0, 1)), rnd.choice((0, 1))))
    ops.append("%%bf 0 %s" % h(f32(rnd.choice(
        (1.0, 0.5, 1.25, 0.0, rnd.uniform(0.8, 1.2))))))
    if rnd.random() < 0.2:
        # DecideBoostFactor sets the boost to 1 first.
        ops += ["%rc 0 1 00000000", "%kf 0 ba 1", "%dc 1",
                "%dw 984 00000000", "%%kf 0 lbt %08x" % (now - 1)]
    else:
        ops.append("%rc 0 x")
    ops.append("%eca 0 0")
    return ops


def s_execute(rnd):
    """ExecuteCurrentAction, round after round, on my car (0) over three
    routes and a few signs leading on to them."""
    w = World(rnd)
    sizes = []
    rns = rnd.sample(range(0, 60), 3)
    for k in range(3):
        sizes.append(rnd.randint(3, 14))
        w.route(k, sizes[k], rns[k])
    nsigns = rnd.randint(1, 4)
    for _ in range(nsigns):
        k2 = rnd.randrange(3)
        w.sign(k2, rnd.randrange(sizes[k2]))
    w.car(0, act=-1, pl=0)
    ops = w.ops + ["%NS 0", "%n 0", "%dr 0", "%fa 0 0 0 0 0", "%cur 0 0"]
    ops += exec_diff(rnd)
    for _ in range(rnd.randrange(6, 12)):
        ops += exec_round(rnd, sizes, nsigns)
    return ops


# ---------------------------------------------------------------- 11e-5's

THINK_DTS = (1.0 / 30.0, 1.0 / 60.0, 0.1, 0.05, 0.0, 0.25, 0.0333)
THINK_TYPES = (0, 1, 2, 3, 4, 5, 5, 6, 6, 7, 8, 9, 10)
# UpdateStatus's three answers: HasExpired, HasFailed, HasBeenAccomplished.
THINK_TESTS = ((0, 0, 0),) * 5 + ((1, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1),
                                  (1, 1, 0), (1, 0, 1), (0, 1, 1), (1, 1, 1))
TCD_DTS = (0.0, 1.0 / 30.0, 1.0 / 60.0, 0.1, 0.25, 1.0, -0.1, -1.0, 1e6,
           -1e6, 1e9, -1e9, 0.000125, 0.00025, 0.0002499, 0.0005)


def ticks_of(dt):
    """CountDown's step: dt x 4000, truncated toward zero, as the EE's
    `cvt.w.s` saturates."""
    v = int(f32(f32(dt) * f32(4000.0)))
    return max(-0x80000000, min(0x7fffffff, v))


def after_count(v, dt):
    """What CountDown leaves of a timer of v after a step of dt."""
    if v in (0, 0x7fffffff):
        return v
    n = (v - ticks_of(dt)) & M32
    return 0 if n >= 0x80000000 else n


def count_timer(rnd, dt, out=None):
    """A timer running out on this step or a tick either side of it, a long
    one, one the step leaves at 0x7fffffff, a negative one, or one not
    running; with `out`, one the step leaves not running (True) or running
    (False)."""
    tr = ticks_of(dt)
    vs = [v & M32 for v in (0, 0x7fffffff, tr, tr, tr + 1, max(tr - 1, 1),
                            tr + 4000, 0x7fffffff + tr, 0x80000000,
                            0xffffffff, 1)]
    if out is not None:
        vs = [v for v in vs if (after_count(v, dt) in (0, 0x7fffffff)) == out]
    return rnd.choice(vs)


def c_rem(a, b):
    """C's remainder, with the dividend's sign."""
    r = abs(a) % b
    return -r if a < 0 else r


def mean_edge(ns):
    """The totals either side of a mean of 0.2 over ns samples: the last
    under it and the first not."""
    lim = f32(0.2)
    t = f32(lim * ns)
    while f32(t / ns) >= lim:
        t = below(t)
    while f32(above(t) / ns) < lim:
        t = above(t)
    return t, above(t)


def think_signs(rnd, w, mine):
    """The signs each past the look-ahead's 250 m clamp or behind me, never
    within it, so that DoStickyDecisions decides none and stops at the
    first ahead (sign 0 always is); a decision on one more than 10 m
    behind goes."""
    nsg = max(w.nsign, rnd.choice((1, 2, 3, 4)))
    ops = []
    for i in range(nsg):
        if i == 0 or rnd.random() < 0.5:
            d = f32(mine + rnd.uniform(300.0, 2000.0))
        else:
            d = f32(mine - rnd.choice((rnd.uniform(0.01, 9.0), 10.0,
                                       rnd.uniform(11.0, 800.0))))
        ops.append("%%S %d %s" % (i, h(d)))
    ops.append("%%NS %d" % nsg)
    return ops, nsg


def brake_ops(rnd, now):
    """The brake stand's timers: not running (a coin flip's phase), or the
    phase's length a tick either side of the time since it started; the
    phase either way, and the seed."""
    ticks = rnd.randrange(1400, 10000)
    since = rnd.choice((ticks - 1, ticks, ticks + 1, ticks, 0,
                        rnd.randrange(0, 20000), -5))
    ops = ["%%kf 0 bs %08x" % rnd.choice((ticks, ticks, ticks, 0,
                                          0x7fffffff)),
           "%%kf 0 bss %08x" % ((now - since) & M32),
           "%%kf 0 bsg %d" % rnd.choice((0, 1, 1, 0, 2))]
    if rnd.random() < 0.5:
        ops.append("%%seed %08x" % rnd.getrandbits(32))
    return ops


def turn_ops(rnd, dtype, others):
    """The world's car table and loop counter for an AI racer (a frame in
    8) or a traffic car (a frame in 6): the counter's C remainder against
    the count of them a car either side, and my car at that slot of the
    table or another or none. A negative counter's slot is before the
    first's, which is placed far enough on to stay in the table."""
    n = 8 if dtype == 2 else 6
    loop = rnd.choice((0, 1, 5, 7, 8, 13, 100, 12345, 0x7fffffff, -1, -5, -8,
                       -13, -0x80000000, rnd.randrange(1 << 20)))
    m = c_rem(loop, n)
    base = rnd.randint(max(0, -m), W_MAX_CARS - 1 - max(m, 0))
    diff = rnd.choice((m + 1, m + 1, m, m - 1, m + rnd.randint(1, 8), -1, 0,
                       W_MAX_CARS))
    table = [rnd.choice([-1, -1] + others) for _ in range(W_MAX_CARS)]
    if rnd.random() < 0.65:
        table[base + m] = 0
    elif rnd.random() < 0.5:
        table[rnd.randrange(W_MAX_CARS)] = 0
    total, ai, cop, traffic = (rnd.randrange(W_MAX_CARS + 1),
                               rnd.randrange(W_MAX_CARS),
                               rnd.randrange(W_MAX_CARS),
                               rnd.randrange(W_MAX_CARS))
    if dtype == 2:
        ai, cop = base, base + diff
    else:
        traffic, total = base, base + diff
    return ["%%wlc %d" % loop,
            "%%wt %d %d %d %d %s" % (total, ai, cop, traffic,
                                     " ".join("%d" % v for v in table))]


def progress_ops(rnd, dt):
    """ProgressTimer either side of running out, and the progress Average
    full or not (nine samples fill it with this one), its mean after this
    sample a float either side of 0.2 with nothing recorded or dropped, or
    a lap's rate over the track's length recorded over any slot."""
    ops = ["%%kf 0 pt %08x" % count_timer(rnd, dt)]
    n = rnd.choice((10, 10, 9, 8, 0, 4))
    cur = rnd.randrange(10)
    if rnd.random() < 0.5:
        lo, hi = mean_edge(min(n + 1, 10) or 1)
        ops.append("%%dl 0 %s" % h(rnd.choice((0.0, -0.0))))
        ops.append("%%pg 0 %d %d %s %s" % (cur, n, h(rnd.choice((lo, hi, hi))),
                                          h(0.0)))
    else:
        ops.append("%%dl 0 %s" % h(f32(rnd.choice(
            (0.5, -0.5, 1.75, -0.0001, rnd.uniform(-3.0, 3.0))))))
        ops.append("%%pg 0 %d %d %s %s" % (
            cur, n, h(f32(rnd.uniform(-5.0, 50.0))),
            h(f32(rnd.uniform(-5.0, 50.0)))))
    return ops


def player_ops(rnd, me):
    """The two players' positions: 50 m from me along an axis and a float
    either side, or further, or anywhere about."""
    ops = []
    for i in range(2):
        ax = rnd.randrange(3)
        p = list(me)
        c = rnd.random()
        if c < 0.4:
            x = f32(me[ax] + 50.0 * rnd.choice((1, -1)))
            p[ax] = rnd.choice((x, below(x), above(x)))
        elif c < 0.75:
            p[ax] = f32(me[ax] + rnd.choice((130.0, 200.0, -300.0, 1000.0)))
        else:
            p[ax] = f32(me[ax] + rnd.uniform(-150.0, 150.0))
        ops.append(vec_op("%wp", i, p))
    return ops


THINK_BELT_GATES = ("np", "demo", "ob", "rp", "fs", "nw", "act", "skill",
                    "range", "race", "bm")
BELT_GO_TYPES = (0, 1, 2, 3, 4, 5)


def fake_op(rnd, i, types):
    # A score of 1 lands just past a JustDrive's (AIActionJustDriveScore,
    # gp-18272, 0).
    return "%%fa %d %d %d %d %d" % (i, rnd.choice(types),
                                    rnd.choice((0, 1, 100, 300, 600)),
                                    rnd.choice((1, 1, 0)), rnd.choice((0, 1)))


def belt_players(rnd, me, far):
    """The two players, the nearer 120 m from me and a float either side,
    or nearer still."""
    d0 = (rnd.choice((120.0, above(120.0), 300.0, 1000.0)) if far
          else rnd.choice((below(120.0), 119.0, 50.0, 10.0, 0.0)))
    ops = []
    for j, slot in enumerate(rnd.sample((0, 1), 2)):
        d = d0 if j == 0 else rnd.choice((d0, 1000.0, 5000.0))
        ax = rnd.randrange(3)
        p = list(me)
        p[ax] = f32(me[ax] + d * rnd.choice((1, -1)))
        ops.append(vec_op("%wp", slot, p))
    return ops


def think_round(rnd, others, me, dn):
    """One Think: before the start, on the brake stand or standing; or
    racing, past the progress check, the timers, the debug reset, the turn
    and between thinks, or a think over the action, its points, its
    execution and the belt. Every other round is the belt's, failing at
    most one of WeCanHaveTheBelt's tests (gate_picker)."""
    dt = f32(rnd.choice(THINK_DTS))
    now = rnd.randrange(1 << 20, 1 << 24)
    ops = ["G TIMER %08x" % now]
    if rnd.random() < 0.2:
        cop = rnd.choice((0, 0, 1))
        stage = (rnd.choice((0, 1, 2, 2, 3, 3, 5, -1)) if not cop
                 else rnd.choice((0, 1, -1)))
        ops += ["%%rs %d" % stage,
                "%%rp 0 0 %d 0 00000000 00000000" % cop]
        ops += brake_ops(rnd, now)
        ops.append("%%think 0 %s" % h(dt))
        return ops
    cop = rnd.choice((0, 0, 0, 1))
    ops += ["%%rs %d" % (4 if not cop else rnd.choice((2, 3, 4, 5))),
            "%%rp 0 0 %d 0 00000000 00000000" % cop]
    belt = rnd.random() < 0.5
    if belt:
        ok = gate_picker(rnd, THINK_BELT_GATES)
    else:
        ok = lambda g: rnd.random() < 0.75
    # The queue, and in a belt round its actions of a kind the belt takes
    # or refuses.
    q = [rnd.randrange(NFACTS) for _ in range(3)]
    types = (BELT_GO_TYPES if ok("act") else BELT_STOP) if belt else None
    if types:
        for i in sorted(set(q)):
            ops.append(fake_op(rnd, i, types))
    ops.append("%%q %s" % " ".join("%d" % i for i in q))
    # The action: none, a fake (now and then of a new type) answering
    # UpdateStatus's tests, or whatever the last think left.
    c = rnd.random()
    if c < 0.15:
        ops.append("%cur 0 -1")
    elif c < 0.75:
        i = rnd.randrange(NFACTS)
        if types:
            ops.append(fake_op(rnd, i, types))
        elif rnd.random() < 0.4:
            ops.append(fake_op(rnd, i, THINK_TYPES))
        ops.append("%%cur 0 %d" % i)
        ops.append("%%fs %d %d %d %d %d" % ((i, rnd.choice((0, 1)))
                                           + rnd.choice(THINK_TESTS)))
    ops.append("%%bai %d" % rnd.choice((0, 0, 0, 0, 1)))
    ops += progress_ops(rnd, dt)
    if belt:
        ops += belt_players(rnd, me, ok("range"))
    else:
        ops += player_ops(rnd, me)
    if rnd.random() < 0.4:
        ops.append("@bk 0 %08x %s" % (
            (now - rnd.choice((0, 1000, 3999, 4000, 4001, -1000))) & M32
            if rnd.random() < 0.7 else rnd.choice((0, 0x7fffffff)),
            h(f32(rnd.choice((0.0, 0.25, 1.0, 2.0))))))
    # RealPhysicsTimer and the wheels down, OffBeltTimer and the mode, the
    # glue's and the taken sign's timers.
    ops.append("%%kf 0 rp %08x" % count_timer(rnd, dt, ok("rp")))
    ops.append("%%fsw 0 %s %d" % (
        h(rnd.choice((f32(5.0), above(5.0), f32(30.0))) if ok("fs")
          else rnd.choice((below(5.0), f32(0.0), f32(-10.0)))),
        rnd.choice((4, 4, 3, 1, 5)) if ok("nw") else rnd.choice((0, -1))))
    ops.append("%%kf 0 ob %08x" % count_timer(rnd, dt, ok("ob")))
    ops.append("%%mm 0 %d" % rnd.choice((6, 6, 4, 1, 0)))
    for f in ("on", "off", "tt"):
        if rnd.random() < 0.5:
            ops.append("%%kf 0 %s %08x" % (f, count_timer(rnd, dt)))
    # The debug reset, for the camera's car or another.
    ops.append("G CAM %08x" % (rnd.choice((dn, dn, M32, dn + 1)) & M32))
    if rnd.random() < 0.25:
        ops.append("%%rtp %d %d" % (rnd.choice((1, 1, -1, 0)),
                                    rnd.choice((0xc000, 0, 12345))))
    # The turn.
    dtype = rnd.choice((2, 2, 3, 3, 0, 1, 4))
    ops.append("%%dt 0 %d" % dtype)
    if dtype in (2, 3):
        ops += turn_ops(rnd, dtype, others)
    ops.append("%%kf 0 secs %s" % h(rnd.choice(
        (dt, below(dt), above(dt), 0.0, f32(-0.5), f32(0.1), f32(1.0),
         f32(dt + 0.1)))))
    # Between thinks: a choice beside a player's car or not.
    if rnd.random() < 0.5:
        if others and rnd.random() < 0.7:
            k = rnd.choice(others)
            ops.append("%%ch 0 %d %d %d" % (rnd.choice((5, 6)), k,
                                            rnd.choice((0, 1))))
            ops.append("%%pl %d %d" % (k, rnd.choice((1, 1, 0))))
        else:
            ops.append("%%ch 0 %d %d %d" % (rnd.choice((0, 1, 2, 3, 4, 7)),
                                            rnd.choice([-1] + others),
                                            rnd.choice((0, 1))))
    if rnd.random() < 0.15:
        ops.append("%%cl %s" % " ".join(
            "%d" % k for k in rnd.sample([0] + others,
                                         rnd.randrange(len(others) + 2))))
    # The location cleared now and then, and the routes FindWhereIAm may
    # take.
    if rnd.random() < 0.12:
        ops.append("%L 0 -1 -1 -1 0")
    if rnd.random() < 0.15:
        ops.append("%%rn 0 %d %d" % rnd.choice(((0, 99), (0, 0), (0, 49))))
    # The belt's other tests.
    ops.append("%%np 0 %d" % (rnd.choice((3, 4, 20)) if ok("np")
                              else rnd.choice((0, 2, -1))))
    ops.append("%%RC %d" % (rnd.choice((0, 0, 3, 9, 7)) if ok("demo")
                            else 8))
    ops.append("%%rt 0 %08x" % (rnd.choice((T30, T30 + 1, 10 * T30))
                                if ok("race")
                                else rnd.choice((T30 - 1, 0, T30 // 2,
                                                 0xffffffff, 0x80000000))))
    ops.append("@sk 0 %d" % (rnd.choice((-3, -1, 0, 5, 9)) if ok("skill")
                             else -2))
    ops.append("%%bm %d" % (rnd.choice((1, 1, 2, -1)) if ok("bm") else 0))
    ops.append("%%think 0 %s" % h(dt))
    # Half the rounds that began with no action think again at once, so the
    # JustDrive this one made meets InterruptAction with a fact scored at
    # its own score (AIActionJustDriveScore, 0) or just past it.
    if c < 0.15 and rnd.random() < 0.5:
        i = rnd.randrange(NFACTS)
        ops += ["%%fa %d %d %d %d %d" % (i, rnd.choice(THINK_TYPES),
                                         rnd.choice((1, 1, 0, 2)),
                                         rnd.choice((1, 1, 0)),
                                         rnd.choice((0, 1))),
                "%%q %d %d %d" % (i, rnd.randrange(NFACTS),
                                  rnd.randrange(NFACTS)),
                "%%think 0 %s" % h(dt)]
    return ops


def s_think(rnd):
    """Think, frame after frame, on my car (0) in the walk world, the
    others about it in the world's car list: before the start (standing,
    or the brake stand's phases at their edges from the default seed), and
    racing, over the progress check, every timer either side of running
    out, the debug reset, an AI racer's and a traffic car's turn at the
    loop counter's edges and anyone else's on its clock, between thinks
    beside a player's car, the location clear, each action's way to done,
    interrupted, BoringAIForCameraTuningOn's three, and the belt taken,
    kept, refused and left."""
    w, sizes, others = route_world(rnd, nsigns=rnd.choice((0, 0, 2)))
    ops = w.ops
    v = w.cars[0]
    me = tuple(f32(v[a]) for a in ("px", "py", "pz"))
    mine = f32(rnd.uniform(0.0, 1000.0))
    so, nsg = think_signs(rnd, w, mine)
    ops += so
    ops.append("%%d 0 %s" % h(mine))
    ops.append("%%si 0 %d" % rnd.randrange(nsg))
    if rnd.random() < 0.4:
        ops.append(sticky_words(rnd, nsg, dsd=True))
    for k in others:
        ops.append("%%d %d %s" % (k, h(f32(mine + rnd.uniform(-60.0,
                                                               60.0)))))
    ops.append("G TLEN %s" % h(f32(rnd.choice((0.0, 5000.0, 20000.0)))))
    ops += ["%rc 0 1 00000000", "%kf 0 ba 0"]
    for i in range(NFACTS):
        ops.append("%%fa %d %d %d %d %d" % (
            i, rnd.choice(THINK_TYPES), rnd.choice((0, 100, 300, 500, 600)),
            rnd.choice((1, 1, 0)), rnd.choice((0, 1))))
    ops.append("%%rn 0 %d %d" % rnd.choice(((0, 99), (0, 99), (0, 99),
                                            (0, 0))))
    ops.append("%%cl %s" % " ".join(
        "%d" % k for k in rnd.sample([0] + others, len(others) + 1)))
    for _ in range(rnd.randrange(5, 11)):
        ops += think_round(rnd, others, me, v["dn"])
    return ops


def s_tcd(rnd):
    """Timer::CountDown over steps of every size and sign, timers either
    side of running out, wrapping and not running."""
    ops = []
    for _ in range(rnd.randrange(10, 20)):
        dt = f32(rnd.choice(TCD_DTS + (rnd.uniform(-1.0, 1.0),)))
        tr = ticks_of(dt)
        ops.append("%%tcd %08x %s" % (rnd.choice(
            (0, 0x7fffffff, 1, 0x80000000, 0xffffffff, 0x7ffffffe,
             rnd.getrandbits(32), tr, tr + 1, tr - 1,
             0x7fffffff + tr)) & M32, h(dt)))
    return ops


def s_cas():
    """Race::CanAICarsStartDriving at every stage, BeACop or not."""
    ops = []
    for s in (-1, 0, 1, 2, 3, 4, 5, 6, 0x7fffffff, -0x80000000):
        for cop in (0, 1, -1, 2):
            ops += ["%%rs %d" % s,
                    "%%rp 0 0 %d 0 00000000 00000000" % cop, "%cas"]
    return ops


N_BUILD = 40
N_WHERE = 30
N_LINE = 16
N_ACTION = 30
N_RELAX = 40
N_SIGNDEC = 60
N_STICKY = 50
N_TRACKPOINT = 30
N_TRACKPOINT_EDGE = 30
N_SIGNINDEX = 20
N_TAKECHANCE = 20
N_STICKY_EDGE = 12
N_BELT = 40
N_GLUE = 60
N_BOOST = 60
N_CATCHUP = 30
N_HONK = 60
N_LIGHTS = 30
N_EXECUTE = 80
N_THINK = 120
N_TCD = 6


def script():
    rnd = random.Random(0x11e1)
    sc = []
    for _ in range(N_BUILD):
        sc.append(s_build(rnd))
    for _ in range(N_WHERE):
        sc.append(s_where(rnd))
    for _ in range(N_LINE):
        sc.append(s_line(rnd))
    for _ in range(N_ACTION):
        sc.append(s_action(rnd))
    for _ in range(N_RELAX):
        sc.append(s_relax(rnd))
    rnd = random.Random(0x11e2)
    for _ in range(N_SIGNDEC):
        sc.append(s_signdec(rnd))
    for _ in range(N_STICKY):
        sc.append(s_sticky(rnd))
    for _ in range(N_TRACKPOINT):
        sc.append(s_trackpoint(rnd))
    for _ in range(N_TRACKPOINT_EDGE):
        sc.append(s_trackpoint_edge(rnd))
    for _ in range(N_SIGNINDEX):
        sc.append(s_signindex(rnd))
    for _ in range(N_TAKECHANCE):
        sc.append(s_takechance(rnd))
    for _ in range(N_STICKY_EDGE):
        sc.append(s_sticky(rnd, edge=True))
    rnd = random.Random(0x11e3)
    _PICK.seed(0x11e3)
    for _ in range(N_BELT):
        sc.append(s_belt(rnd))
    for _ in range(N_GLUE):
        sc.append(s_glue(rnd))
    for _ in range(N_BOOST):
        sc.append(s_boost(rnd))
    for _ in range(N_CATCHUP):
        sc.append(s_boost(rnd, catchup=True))
    rnd = random.Random(0x11e4)
    _PICK.seed(0x11e4)
    for _ in range(N_HONK):
        sc.append(s_honk(rnd))
    for _ in range(N_LIGHTS):
        sc.append(s_lights(rnd))
    for _ in range(N_EXECUTE):
        sc.append(s_execute(rnd))
    rnd = random.Random(0x11e5)
    _PICK.seed(0x11e5)
    for _ in range(N_THINK):
        sc.append(s_think(rnd))
    for _ in range(N_TCD):
        sc.append(s_tcd(rnd))
    sc.append(s_cas())
    return sc


encode = dcc.encode


# ================================================================ the model


class Model(dcc.Model):
    OK_DIVS = dcc.Model.OK_DIVS | GLUE_DIVS

    def __init__(self):
        dcc.Model.__init__(self)
        e = self.e
        # Car::GetRoutePoint and GetAmountOutOfBounds run as shipped, into
        # the controller's table.
        del e.stubs[dcc.GET_ROUTE_POINT]
        del e.stubs[dcc.GET_OOB]
        e.stub(STUB_CRP, self.s_crp)
        e.stub(STUB_COOB, self.s_coob)
        e.stub(BMALLOC, self.s_malloc)
        e.stub(BFREE, self.s_free)
        e.stub(SET_MOVEMENT, self.s_movement)
        e.stub(STUB_SSTP, self.s_sstp)
        e.stub(STUB_ZSM, self.s_zsm)
        e.stub(STUB_RNUM, self.s_rnum)
        e.stub(STUB_CHOOSE, self.s_choose)
        e.stub(STUB_ADEL, self.s_adel)
        e.stub(STUB_ACP, self.s_acp)
        # SignPostDecision runs as shipped (11e-2), from AdvancePoint too,
        # as main.c points drivingchoice.h's seam at the port's.
        del e.stubs[dcc.SIGN_DECISION]
        e.stub(WORLD_RANDOM, self.s_random)
        e.stub(GET_TRACK_INFO, self.s_tinfo)
        self.vt0 = bytes(e.mem[AICC_VTABLE:AICC_VTABLE + AICC_VT_BYTES])
        self.nheap = 0
        self.fa_pt = [0] * NFACTS
        self.queue = []
        self.qi = 0
        self.rnums = {}
        self.rq = []
        self.ri = 0
        # 11e-3's: the drivers' GetDesiredSpeed, and the glue's Graph built
        # as the image's start-up code builds it.
        e.stub(STUB_GDS, self.s_gds)
        self.gds = {}
        self.plrs = set()
        self.call(GLUE_CTOR)
        # 11e-4's: the drivers' SetDesiredSpeed, SetTarget and horn, and
        # World::Random(int).
        e.stub(STUB_SDS, self.s_sds)
        e.stub(STUB_STG, self.s_stg)
        e.stub(STUB_HON, self.s_hon)
        e.stub(STUB_HOFF, self.s_hoff)
        e.stub(STUB_ISH, self.s_ish)
        e.stub(WORLD_RANDOM_I, self.s_irandom)
        self.ish = {}
        # 11e-5's: bOMalloc, SetBelt, DebugSetPosition, SetTargetToRender
        # and bRefreshTweaker, and the fake actions' three tests.
        e.stub(BOMALLOC, self.s_omalloc)
        e.stub(SET_BELT, self.s_setbelt)
        e.stub(DEBUG_SET_POS, self.s_dsp)
        e.stub(SET_TARGET_TO_RENDER, self.s_render)
        e.stub(REFRESH_TWEAKER, self.s_tweak)
        e.stub(STUB_AHE, lambda em: self.s_atest(em, 0, "ahe"))
        e.stub(STUB_AHF, lambda em: self.s_atest(em, 1, "ahf"))
        e.stub(STUB_AHBA, lambda em: self.s_atest(em, 2, "ahba"))
        self.fa_test = {}

    # ---- names -----------------------------------------------------------

    def name(self, a):
        a &= M32
        n = dcc.Model.name(self, a)
        if not n.startswith("?"):
            return n
        for k in range(NCARS):
            c = ctrl_at(k)
            if a == c + K_LIST:
                return "kn%d" % k
            if a == c + K_ILOC:
                return "kl%d" % k
            if a == c + K_ICH:
                return "kc%d" % k
            off = a - (c + K_LIST + 8)
            if 0 <= off < NC_SIZE * 16 and off % NC_SIZE == 0:
                return "ke%d:%d" % (k, off // NC_SIZE)
        if (HEAP <= a < HEAP + HEAP_BLOCK * NHEAP
                and (a - HEAP) % HEAP_BLOCK == 0):
            return "m%d" % ((a - HEAP) // HEAP_BLOCK)
        if (CDRIVERS <= a < CDRIVERS + CDRIVER_STRIDE * NCARS
                and (a - CDRIVERS) % CDRIVER_STRIDE == 0):
            return "d%d" % ((a - CDRIVERS) // CDRIVER_STRIDE)
        if (FACTS <= a < FACTS + FACT_SIZE * NFACTS
                and (a - FACTS) % FACT_SIZE == 0):
            return "fa%d" % ((a - FACTS) // FACT_SIZE)
        off = a - (FACTS + A_PTD)
        if 0 <= off < FACT_SIZE * NFACTS and off % FACT_SIZE == 0:
            return "pt%d" % (off // FACT_SIZE)
        if (PLR <= a < PLR + PLR_STRIDE * NCARS
                and (a - PLR) % PLR_STRIDE == 0):
            return "P%d" % ((a - PLR) // PLR_STRIDE)
        return n

    def vtn(self, v):
        return VT_NAMES.get(v & M32, "%08x" % (v & M32))

    def ctrl_index(self, a):
        k, off = divmod((a & M32) - CTRLS, CTRL_STRIDE)
        if off or not 0 <= k < NCARS:
            raise SystemExit("a controller that is not one of ours: %08x"
                             % (a & M32))
        return k

    def fact_index(self, a):
        i, off = divmod((a & M32) - FACTS, FACT_SIZE)
        if off or not 0 <= i < NFACTS:
            raise SystemExit("an action that is not one of ours: %08x"
                             % (a & M32))
        return i

    # ---- the stubs -------------------------------------------------------

    def s_crp(self, em):
        k = self.ctrl_index(em.reg[4])
        self.emit("  rp %s" % self.name(car_at(k)))
        return self.rp.get(k, 0)

    def s_coob(self, em):
        k = self.ctrl_index(em.reg[4])
        self.emit("  oob %s" % self.name(car_at(k)))
        em.fpr[0] = self.oob.get(k, 0)

    def s_malloc(self, em):
        r = em.reg
        size = s32(r[4])
        if self.nheap >= NHEAP or not 0 <= size <= HEAP_BLOCK:
            raise SystemExit("bMalloc: %d bytes for %s"
                             % (size, self.cstr(r[5] & M32)))
        p = HEAP + HEAP_BLOCK * self.nheap
        self.emit("  alloc m%d size %d name %s flags %d pool %d" % (
            self.nheap, size, self.cstr(r[5] & M32), s32(r[6]), s32(r[7])))
        self.nheap += 1
        self.fill(p, HEAP_BLOCK)
        return p

    def s_free(self, em):
        self.emit("  free %s" % self.name(em.reg[4]))

    def s_movement(self, em):
        car, mode = em.reg[4] & M32, em.reg[5] & M32
        self.emit("  mode %s %d" % (self.name(car), s32(mode)))
        self.e.put32(car + C_MODE, mode)

    def s_sstp(self, em):
        k = self.driver_car(em)
        p = em.reg[5] & M32
        self.emit("  sstp %s %s %s" % (self.name(car_at(k)), fx(self.w(p)),
                                       fx(self.w(p + 4))))

    def s_zsm(self, em):
        self.emit("  zsm %s" % self.name(car_at(self.driver_car(em))))

    def s_rnum(self, em):
        r = em.reg
        k = self.ctrl_index(r[4])
        self.emit("  rnum %s" % self.name(r[4]))
        first, last = self.rnums.get(k, (0, 0))
        self.e.put32(r[5] & M32, first & M32)
        self.e.put32(r[6] & M32, last & M32)

    def s_choose(self, em):
        r = em.reg
        self.ctrl_index(r[4])
        if self.qi < len(self.queue):
            i = self.queue[self.qi]
            self.qi += 1
        else:
            i = -1
        self.emit("  choose %s %d" % (self.name(r[4]), s32(r[6])))
        self.e.put32(r[5] & M32, fact_at(i))

    def s_adel(self, em):
        a = em.reg[4] & M32
        self.emit("  adel %s %d" % (self.name(a), s32(em.reg[5])))
        self.fact_index(a)

    def s_acp(self, em):
        a = em.reg[4] & M32
        i = self.fact_index(a)
        self.emit("  acp %s %s" % (self.name(a), self.name(em.reg[5])))
        self.e.put32(a + A_PT, self.fa_pt[i] & M32)

    def s_random(self, em):
        self.emit("  random %d %s" % (int(em.reg[4] & M32 == WORLD),
                                      fx(em.fpr[12])))
        v = 0
        if self.ri < len(self.rq):
            v = self.rq[self.ri]
            self.ri += 1
        em.fpr[0] = v

    def s_tinfo(self, em):
        self.emit("  tinfo %d" % s32(em.reg[4]))
        return TINFO

    def s_gds(self, em):
        k = self.driver_car(em)
        self.emit("  gds %s" % self.name(car_at(k)))
        em.fpr[0] = self.gds.get(k, 0)

    def s_sds(self, em):
        k = self.driver_car(em)
        self.emit("  sds %s %s %s %s %d" % (
            self.name(car_at(k)), fx(em.fpr[12]), fx(em.fpr[13]),
            fx(em.fpr[14]), s32(em.reg[5])))

    def s_stg(self, em):
        """A target that is no one's is Think's own, on its stack: shown
        whole."""
        k = self.driver_car(em)
        t = em.reg[5] & M32
        n = self.name(t)
        if not n.startswith("?"):
            self.emit("  stg %s %s" % (self.name(car_at(k)), n))
            return
        self.emit("  stg %s tmp" % self.name(car_at(k)))
        self.dump_target(t)

    def s_hon(self, em):
        self.emit("  honkon %s" % self.name(car_at(self.driver_car(em))))

    def s_hoff(self, em):
        self.emit("  honkoff %s" % self.name(car_at(self.driver_car(em))))

    def s_ish(self, em):
        k = self.driver_car(em)
        self.emit("  ishonk %s" % self.name(car_at(k)))
        return self.ish.get(k, 0) & M32

    def s_irandom(self, em):
        self.emit("  irandom %d %d" % (int(em.reg[4] & M32 == WORLD),
                                       s32(em.reg[5])))
        v = 0
        if self.ri < len(self.rq):
            v = self.rq[self.ri]
            self.ri += 1
        return v

    def s_omalloc(self, em):
        self.emit("  omalloc %s" % self.name(em.reg[4]))
        return dcc.AB

    def s_setbelt(self, em):
        self.emit("  setbelt %s" % self.name(em.reg[4]))

    def s_dsp(self, em):
        r, w = em.reg, self.w
        p = r[5] & M32
        self.emit("  dsp %s %s %s %s %s %d" % (
            self.name(r[4]), fx(w(p)), fx(w(p + 4)), fx(w(p + 8)),
            fx(em.fpr[12]), r[6] & 0xffff))

    def s_render(self, em):
        r = em.reg
        tdr = "tdr" if r[4] & M32 == TDR else self.name(r[4])
        self.emit("  render %s %s" % (tdr, self.name(r[5])))

    def s_tweak(self, em):
        pass

    def s_atest(self, em, which, tag):
        a = em.reg[4] & M32
        i = self.fact_index(a)
        self.emit("  %s %s %s" % (tag, self.name(a), self.name(em.reg[5])))
        return self.fa_test.get(i, (0, 0, 0))[which] & M32

    # ---- the world -------------------------------------------------------

    def reset(self):
        dcc.Model.reset(self)
        e = self.e
        e.put32(NDMM, MELLOW)
        e.mem[TVT:TVT + AICC_VT_BYTES] = self.vt0
        e.put32(TVT + 112 + 4, STUB_RNUM)
        e.put32(TVT + 120 + 4, STUB_CHOOSE)
        e.mem[AVT:AVT + AVT_BYTES] = bytes(AVT_BYTES)
        e.put32(AVT + 8 + 4, STUB_ADEL)
        e.put32(AVT + 24 + 4, STUB_ACP)
        e.put32(DVT + 72 + 4, STUB_SSTP)
        e.put32(DVT + 120 + 4, STUB_ZSM)
        e.put32(CVT + 56 + 4, STUB_CRP)
        e.put32(CVT + 64 + 4, STUB_COOB)
        e.mem[FACTS:FACTS + FACT_SIZE * NFACTS] = bytes(FACT_SIZE * NFACTS)
        e.mem[TINFO:TINFO + TINFO_SIZE] = bytes(TINFO_SIZE)
        e.put32(TINFO + TI_GRACE, M32)
        e.put32(RACE_PARAMS, 0)
        e.mem[SKILLS:SKILLS + SKILL_STRIDE * NSKILLS] = bytes(
            SKILL_STRIDE * NSKILLS)
        self.nheap = 0
        self.fa_pt = [0] * NFACTS
        self.queue = []
        self.qi = 0
        self.rnums = {}
        self.rq = []
        self.ri = 0
        # 11e-3's: no players, RacingCars, catchup, SkipFE, race parameters,
        # difficulty or player positions; the coordinator in state 0.
        e.put32(DVT + DVT_GDS + 4, STUB_GDS)
        e.mem[PLR:PLR + PLR_STRIDE * NCARS] = bytes(PLR_STRIDE * NCARS)
        e.mem[PAVG:PAVG + PAVG_STRIDE * NCARS] = bytes(PAVG_STRIDE * NCARS)
        e.mem[RCARS:RCARS + RC_STRIDE * NCARS] = bytes(RC_STRIDE * NCARS)
        e.mem[RCOORD:RCOORD + 16] = bytes(16)
        for name, v in (("BELT", 1), ("DISABLE", 0), ("REASON", 0),
                        ("RCOORD", RCOORD), ("BYNUM", 0), ("SKIPFE", 0),
                        ("SKIPFE_COP", 0)):
            e.put32(G3[name], v)
        e.put32(G3["BYNUM"] + 4, 0)
        for off in RP_FIELDS.values():
            e.put32(RACE_PARAMS + off, 0)
        e.mem[DIFF:DIFF + DIFF_SIZE] = bytes(DIFF_SIZE)
        e.mem[WORLD + W_PPOS:WORLD + W_PPOS + 32] = bytes(32)
        self.gds = {}
        self.plrs = set()
        # 11e-4's: the drivers' speed, target and horn, no driver honking,
        # both debug switches off.
        for off, stub in DVT_STUBS4:
            e.put32(DVT + off + 4, stub)
        for g in G4.values():
            e.put32(g, 0)
        self.ish = {}
        # 11e-5's: the fake actions' three tests, the loop counter 0, the
        # default seed as the image starts it, the debug reset off at its
        # angle, an empty car list and car table, and no test answering.
        e.put32(AVT + 40 + 4, STUB_AHBA)
        e.put32(AVT + 48 + 4, STUB_AHF)
        e.put32(AVT + 56 + 4, STUB_AHE)
        e.put32(G5["LOOP"], 0)
        e.put32(G5["SEED"], 0x12345678)
        e.put32(G5["RESET"], 0)
        struct.pack_into("<H", e.mem, G5["ANGLE"], 0xc000)
        e.put32(WORLD, WORLD)
        e.put32(WORLD + 4, WORLD)
        for off in (W_TOTAL, W_AIPOS, W_COPPOS, W_TRAFFICPOS):
            e.put32(WORLD + off, 0)
        e.mem[WORLD + W_TABLE:WORLD + W_TABLE + 4 * W_MAX_CARS] = bytes(
            4 * W_MAX_CARS)
        self.fa_test = {}

    # ---- the dumps -------------------------------------------------------

    def dump_avg(self, tag, a):
        a &= M32
        if a == 0 or a == PAT32:
            self.emit("  %s %s" % (tag, "null" if a == 0 else "pat"))
            return
        w, m = self.w, self.e.mem
        data = w(a + 12)
        self.emit("  %s %s slots %d cur %d n %d total %s avg %s data %s" % (
            tag, self.name(a), m[a], m[a + 1], m[a + 2], fx(w(a + 4)),
            fx(w(a + 8)), self.name(data)))
        if not (HEAP <= data < HEAP + HEAP_BLOCK * NHEAP
                and (data - HEAP) % HEAP_BLOCK == 0):
            return
        n = min(m[a], HEAP_BLOCK // 4)
        self.emit("   " + "".join(" %s" % fx(w(data + 4 * i))
                                  for i in range(n)))

    def dump_loc(self, tag, l):
        w = self.w
        self.emit("  %s %s %s %d %08x" % (tag, self.name(w(l)),
                                          self.name(w(l + 4)),
                                          s32(w(l + 8)), w(l + 12)))

    def dump_ctrl(self, k):
        w, m, nm = self.w, self.e.mem, self.name
        c = ctrl_at(k)
        lst = c + K_LIST
        self.emit("  K vt %s car %s drv %s" % (self.vtn(w(c + K_VPTR)),
                                              nm(w(c)), nm(w(c + K_DRIVER))))
        self.emit("  K list %s %d %s %s" % (nm(w(lst)), s32(w(lst + 4)),
                                            fx(w(lst + LIST_HL)),
                                            fx(w(lst + LIST_HD))))
        self.emit("   " + "".join(" %s" % nm(w(lst + 8 + NC_SIZE * i + 24))
                                  for i in range(16)))
        self.dump_loc("K iloc", c + K_ILOC)
        self.dump_choice(c + K_ICH, "K ich")
        self.emit("  K ptr %s %s %s exc %s ltr %d secs %s force %d act %s"
                  % (nm(w(c + K_LOC)), nm(w(c + K_CHOICE)),
                     nm(w(c + K_NLIST)), nm(w(c + K_EXCLUDE)),
                     s8(m[c + K_LTR]), fx(w(c + K_SECS)),
                     s32(w(c + K_FORCE)), nm(w(c + K_ACTION))))
        self.emit("  K t " + " ".join("%08x" % w(c + o) for o in K_TIMERS))
        self.emit("  K la %d pot %s bs %d lp %s glue %s gr %d gb %s boost %d "
                  "cp %s sign %d ts %d" % (
                      s32(w(c + K_LA)), fx(w(c + K_POT)), s32(w(c + K_BS)),
                      fx(w(c + K_LP)), nm(w(c + K_GLUE)), s32(w(c + K_GR)),
                      fx(w(c + K_GB)), s32(w(c + K_BOOST)),
                      nm(w(c + K_CP)), s32(w(c + K_SIGN)),
                      s32(w(c + K_TS))))
        self.emit("  K sticky" + "".join(" %08x" % w(c + K_STICKY + 4 * i)
                                         for i in range(NSTICKY)))
        self.emit("  K gd " + "".join("%02x" % m[c + K_GD + i]
                                      for i in range(32)))
        self.emit("  K vp %s" % " ".join(fx(w(c + K_VP + 4 * i))
                                         for i in range(4)))
        self.dump_avg("K prog", w(c + K_PROG))
        self.dump_avg("K dls", w(c + K_DLS))

    def dump_where(self, k):
        w = self.w
        c = ctrl_at(k)
        self.dump_loc("K at", w(c + K_LOC))
        self.emit("  K ltr %d hl %d %d" % (
            s8(self.e.mem[c + K_LTR]), s32(w(GLOBALS["HROUTE"])),
            s32(w(GLOBALS["HLINE"]))))

    def dump_signs(self, k):
        w = self.w
        c = ctrl_at(k)
        self.emit("  S sign %d ts %d tt %08x ltr %d" % (
            s32(w(c + K_SIGN)), s32(w(c + K_TS)), w(c + K_TS + 4),
            s8(self.e.mem[c + K_LTR])))
        self.emit("  S sticky" + "".join(" %08x" % w(c + K_STICKY + 4 * i)
                                         for i in range(NSTICKY)))

    def plr_at(self, k):
        return PLR + PLR_STRIDE * k if k >= 0 else 0

    def dump_glue(self, k):
        w = self.w
        a = ctrl_at(k)
        self.emit("  G glue %s on %08x off %08x bias %s reason %d n%s" % (
            self.name(w(a + KF["glue"])), w(a + KF["on"]), w(a + KF["off"]),
            fx(w(a + KF["bias"])), s32(w(G3["REASON"])),
            "".join(" %d" % s32(w(self.plr_at(i) + P_GLUE))
                    for i in sorted(self.plrs))))

    def dump_facts(self):
        for i in range(NFACTS):
            a = fact_at(i)
            if self.w(a + A_VPTR):
                self.emit("  fa%d pt %d" % (i, s32(self.w(a + A_PT))))

    def dump_honk(self, k):
        w = self.w
        p = car_at(k) + C_HONK
        self.emit("  H blink %d honk %d two %d start %08x on %s second %s "
                  "off %s" % (s32(w(p + H_BLINK)), s32(w(p + H_HONK)),
                              s32(w(p + H_TWO)), w(p + H_START),
                              fx(w(p + H_ON)), fx(w(p + H_SECOND)),
                              fx(w(p + H_OFF))))

    def dump_ptd(self, i):
        w = self.w
        p = fact_at(i) + A_PTD
        self.emit("  E pt%d n %d wpc %d wpt %d len %s lps %d" % (
            i, s8(self.e.mem[p]), s32(w(p + T_WPC)), s32(w(p + T_WPT)),
            fx(w(p + T_LEN)), s8(self.e.mem[p + T_LPS])))

    def dump_think(self, k):
        """After a think: the controller, the seed, the debug reset's
        switch, the car's movement mode, the world's two counts, the action
        and the fakes."""
        w = self.w
        self.dump_ctrl(k)
        self.emit("  T seed %08x rtp %d mode %d ids %d %d" % (
            w(G5["SEED"]), s32(w(G5["RESET"])), s32(w(car_at(k) + C_MODE)),
            s32(w(WORLD + dcc.W_ID)), s32(w(WORLD + dcc.W_PDT_ID))))
        act = w(ctrl_at(k) + K_ACTION)
        if act:
            self.emit("  T act type %d st %d pt %d" % (
                s32(w(act + A_TYPE)), s32(w(act + A_STATUS)),
                s32(w(act + A_PT))))
        self.dump_facts()

    # ---- the ops ---------------------------------------------------------

    def hl_of(self, k, s):
        v = int(s)
        if v < 0:
            return 0
        return LOC if v == 0 else self.w(ctrl_at(k) + K_LOC)

    def pct(self, t):
        e, w = self.e, self.w
        c = t[0][1:]
        # %seed's and %tcd's first word is hex, where the harness's atoi
        # reads 0 or its leading digits; neither reads k.
        k = int(t[1]) if len(t) > 1 and c not in ("seed", "tcd") else 0
        a = ctrl_at(k) if 0 <= k < NCARS else ctrl_at(0)
        car = car_at(k) if 0 <= k < NCARS else 0
        if c == "d":
            e.put32(car + C_DIST, int(t[2], 16))
        elif c == "S":
            e.put32(SIGNS + SIGN_SIZE * k + S_DIST, int(t[2], 16))
        elif c == "NS":
            e.put32(GLOBALS["NSIGNS"], k & M32)
        elif c == "U":
            r = route_at(k)
            for off, v in zip((R_START, R_END, R_BMIN, R_BMIN + 4, R_BMAX,
                               R_BMAX + 4), t[2:8]):
                e.put32(r + off, int(v, 16))
        elif c == "a":
            struct.pack_into("<H", e.mem, car + C_ANGLE, int(t[2]) & 0xffff)
        elif c == "mm":
            e.put32(car + C_MODE, int(t[2]) & M32)
        elif c == "pl":
            e.put32(car + C_PLAYER,
                    PLAYERS + PLAYER_STRIDE * k if int(t[2]) else 0)
        elif c == "bf":
            e.put32(car + C_BOOST, int(t[2], 16))
        elif c == "ci":
            struct.pack_into("<h", e.mem, car + C_INDEX, int(t[2]))
        elif c == "pos":
            for i in range(3):
                e.put32(car + dcc.C_POS + 4 * i, int(t[2 + i], 16))
        elif c == "vp":
            for i in range(4):
                e.put32(a + K_VP + 4 * i, int(t[2 + i], 16))
        elif c == "cp":
            src, dst = route_at(k), route_at(int(t[2]))
            n = min(s32(w(src + 16)), s32(w(dst + 16)))
            for i in range(n):
                o = dcc.RT_HEADER + dcc.RT_POINT * i
                e.mem[dst + o:dst + o + 111] = e.mem[src + o:src + o + 111]
        elif c == "G":
            e.put32(NDMM, k & M32)
        elif c == "n":
            self.fill(a, K_SIZE)
            self.call(F["ctor"], a, car)
            self.dump_ctrl(k)
        elif c == "x":
            self.call(F["dtor"], a, int(t[2]) & M32)
            self.emit("  vt %s" % self.vtn(w(a + K_VPTR)))
        elif c == "K":
            self.dump_ctrl(k)
        elif c == "v":
            e.put32(a + K_VPTR, (AICC_VTABLE, TVT, CVT)[int(t[2])])
        elif c == "dr":
            e.put32(a + K_DRIVER, CDRIVERS + CDRIVER_STRIDE * k)
        elif c == "J":
            e.mem[a + K_LIST:a + K_LIST + LIST_BYTES] = \
                e.mem[LIST:LIST + LIST_BYTES]
            e.mem[a + K_ILOC:a + K_ILOC + 16] = e.mem[LOC:LOC + 16]
            e.mem[a + K_ICH:a + K_ICH + 12] = e.mem[CHOICE:CHOICE + 12]
        elif c == "L":
            l = w(a + K_LOC)
            e.put32(l, self.route_of(t[2]))
            e.put32(l + 4, self.point_of(t[2], t[3]))
            e.put32(l + 8, int(t[4]) & M32)
            e.put32(l + 12, int(t[5], 16))
        elif c == "ch":
            self.set_choice(w(a + K_CHOICE), t[1:])
        elif c == "sk":
            for i in range(NSTICKY):
                e.put32(a + K_STICKY + 4 * i, int(t[2 + i], 16))
        elif c == "rn":
            self.rnums[k] = (int(t[2]), int(t[3]))
        elif c == "q":
            self.queue = [int(v) for v in t[1:17]]
            self.qi = 0
        elif c == "fa":
            f = fact_at(k)
            e.mem[f:f + FACT_SIZE] = bytes(FACT_SIZE)
            e.put32(f + A_VPTR, AVT)
            e.put32(f + A_TYPE, int(t[2]) & M32)
            e.put32(f + A_SCORE, int(t[3]) & M32)
            self.fa_pt[k] = int(t[4])
            e.put32(f + A_PT, int(t[5]) & M32)
        elif c == "cur":
            e.put32(a + K_ACTION, fact_at(int(t[2])))
        elif c == "sr":
            self.call(F["sr"], a, self.route_of(t[2]),
                      self.point_of(t[2], t[3]))
            self.dump_where(k)
        elif c == "gr":
            got = self.call(F["gr"], a, int(t[2]) & M32)
            self.emit("  route %s" % self.name(got))
            self.dump_where(k)
        elif c == "gp":
            got = self.call(F["gp"], a, int(t[2]) & M32)
            self.emit("  point %s" % self.name(got))
            self.dump_where(k)
        elif c == "oob":
            self.call(F["oob"], a)
            self.emit("  oob %s" % fx(e.fpr[0]))
        elif c == "fw":
            self.call(F["fw"], a)
            self.dump_where(k)
        elif c == "fc":
            self.call(F["fc"], a, int(t[2]) & M32, int(t[3]) & M32)
            self.dump_where(k)
        elif c == "gl":
            self.fill(LINEVAR, 4)
            got = self.call(F["gl"], a, self.route_of(t[2]),
                            self.point_of(t[2], t[3]), int(t[4]) & M32,
                            LINEVAR, self.hl_of(k, t[5]))
            self.emit("  line %d %d" % (s32(got), s32(w(LINEVAR))))
            self.dump_where(k)
            self.dump_after()
        elif c == "jr":
            self.call(F["jr"], a)
            self.dump_ctrl(k)
        elif c == "dn":
            self.emit("  dnum %d" % s32(self.call(F["dn"], a)))
        elif c == "cs":
            self.call(F["cs"], a)
            self.emit("  sticky" + "".join(" %08x" % w(a + K_STICKY + 4 * i)
                                           for i in range(NSTICKY)))
        elif c == "st":
            self.call(F["st"], a)
        elif c == "cn":
            e.put32(OUTP, 0)
            self.call(F["cn"], a, OUTP, int(t[2]) & M32)
            self.emit("  chosen %s" % self.name(w(OUTP)))
        elif c == "ia":
            got = self.call(F["ia"], a)
            self.emit("  interrupt %s force %d act %s" % (
                self.name(got), s32(w(a + K_FORCE)),
                self.name(w(a + K_ACTION))))
        elif c == "gpf":
            self.call(F["gpf"], a, fact_at(int(t[2])))
            self.emit("  act %s" % self.name(w(a + K_ACTION)))
            self.dump_facts()
            self.dump_where(k)
        elif c == "cat":
            self.emit("  atype %d" % s32(self.call(F["cat"], a)))
        elif c == "force":
            self.call(F["force"], a, int(t[2]) & M32)
            self.emit("  force %d" % s32(w(a + K_FORCE)))
        elif c == "pm":
            self.call(F["pm"], a, self.car_ptr(t[2]))
            self.emit("  movement %d ob %08x rp %08x" % (
                s32(w(car + C_MODE)), w(a + K_OB), w(a + K_RP)))
        elif c == "cc":
            self.call(F["cc"], a, self.car_ptr(t[2]))
            self.emit("  movement %d" % s32(w(car + C_MODE)))
        elif c in ("ls", "seam"):
            self.call(F["ls"], a)
            self.emit("  lspeed %s" % fx(e.fpr[0]))
        elif c == "fb":
            self.call(F["fb"], a, f12=int(t[2], 16))
            self.emit("  boost %s %d" % (fx(w(car + C_BOOST)),
                                         s32(w(a + K_BOOST))))
        elif c == "rb":
            self.call(F["rb"], a)
            self.emit("  boost %s %d" % (fx(w(car + C_BOOST)),
                                         s32(w(a + K_BOOST))))
        elif c == "af":
            got = self.call(F["af"], a, f12=int(t[2], 16))
            self.emit("  fly %d" % s32(got))
        elif c == "ob":
            self.call(F["ob"], a, f12=int(t[2], 16))
            self.emit("  ob %08x" % w(a + K_OB))
        elif c == "ex":
            self.call(F["ex"], a, self.car_ptr(t[2]))
            self.emit("  exc %s" % self.name(w(a + K_EXCLUDE)))
        elif c == "gx":
            self.emit("  exc %s" % self.name(self.call(F["gx"], a)))
        elif c == "gdl":
            self.emit("  dloc %s" % self.name(self.call(F["gdl"], a)))
        elif c == "dd":
            self.call(F["dd"], a)
        # 11e-2's.
        elif c == "rnd":
            self.rq = [int(v, 16) for v in t[2:2 + min(k, NRANDOM)]]
            self.ri = 0
        elif c == "tg":
            e.put32(TINFO + TI_GRACE, k & M32)
        elif c == "tn":
            e.put32(RACE_PARAMS, k & M32)
        elif c == "rt":
            e.put32(RACE + RACE_TIME, int(t[2], 16))
        elif c == "si":
            e.put32(a + K_SIGN, int(t[2]) & M32)
        elif c == "ts":
            e.put32(a + K_TS, int(t[2]) & M32)
        elif c == "hl":
            e.put32(a + K_LIST + LIST_HL, int(t[2], 16))
        elif c == "vm":
            e.put32(car + dcc.C_VMAG, int(t[2], 16))
        elif c == "tsc":
            for i in range(3):
                e.put32(SKILLS + SKILL_STRIDE * k + 4 * i, int(t[2 + i], 16))
        elif c == "sf":
            s = SIGNS + SIGN_SIZE * k
            e.mem[s + S_FLAGS] = int(t[2]) & 0xff
            e.put32(s + S_HINT, int(t[3]) & M32)
        elif c == "fsi":
            self.call(F["fsi"], a)
            self.emit("  sign %d" % s32(w(a + K_SIGN)))
        elif c == "gsi":
            self.emit("  free %d" % s32(self.call(F["gsi"], a)))
        elif c == "dsd":
            self.call(F["dsd"], a)
            self.dump_signs(k)
            self.dump_where(k)
        elif c == "spd":
            e.put32(LINEVAR, int(t[3]) & M32)
            got = self.call(F["spd"], a, SIGNS + SIGN_SIZE * int(t[2]),
                            LINEVAR, w(a + K_LOC))
            self.emit("  take %d line %d" % (s32(got), s32(w(LINEVAR))))
            self.dump_signs(k)
            self.dump_where(k)
        elif c == "gct":
            self.call(F["gct"], a, car)
            self.dump_signs(k)
            self.dump_where(k)
        elif not self.pct3(c, k, a, car, t):
            raise SystemExit("bad op %r" % (t,))

    def pct3(self, c, k, a, car, t):
        """11e-3's ops; False for none of them."""
        e, w = self.e, self.w
        if c == "P":
            p, avg = self.plr_at(k), PAVG + PAVG_STRIDE * k
            e.mem[p:p + PLR_STRIDE] = bytes(PLR_STRIDE)
            e.mem[avg:avg + PAVG_STRIDE] = bytes(PAVG_STRIDE)
            e.put32(p + P_CAR, car)
            e.put32(p + P_NUM, int(t[2]) & M32)
            e.put32(p + P_AVG, avg)
            e.put32(avg + 8, int(t[3], 16))
            e.put32(p + P_MAX, int(t[4], 16))
            e.mem[avg] = int(t[5]) & 0xff
            e.mem[avg + 2] = int(t[6]) & 0xff
            e.put32(p + P_GLUE, int(t[7]) & M32)
            e.put32(car + C_PLAYER, p)
            self.plrs.add(k)
        elif c == "PT":
            e.put32(GLOBALS["NPLAYERS"], k & M32)
            for i in range(2):
                e.put32(GLOBALS["PLAYERS"] + 4 * i,
                        self.plr_at(int(t[2 + i])))
                e.put32(G3["BYNUM"] + 4 * i, self.plr_at(int(t[4 + i])))
        elif c == "rc":
            r = RCARS + RC_STRIDE * k
            if t[2] == "x":
                e.put32(car + C_RC, 0)
            else:
                e.mem[r:r + RC_STRIDE] = bytes(RC_STRIDE)
                e.put32(r, car)
                e.mem[r + RC_POS] = int(t[2]) & 0xff
                e.put32(r + RC_LAP, int(t[3], 16))
                e.put32(car + C_RC, r)
        elif c == "RC":
            e.put32(RCOORD, k & M32)
        elif c == "rp":
            for name, v in zip(("npc", "nai", "cop", "boost"), t[1:5]):
                e.put32(RACE_PARAMS + RP_FIELDS[name], int(v) & M32)
            e.put32(RACE_PARAMS + RP_FIELDS["s0"], int(t[5], 16))
            e.put32(RACE_PARAMS + RP_FIELDS["s1"], int(t[6], 16))
        elif c == "sfe":
            e.put32(G3["SKIPFE"], k & M32)
            e.put32(G3["SKIPFE_COP"], int(t[2]) & M32)
        elif c == "dw":
            for i, v in enumerate(t[2:]):
                e.put32(DIFF + k + 4 * i, int(v, 16))
        elif c == "gds":
            self.gds[k] = int(t[2], 16)
        elif c == "wp":
            for i in range(3):
                e.put32(WORLD + W_PPOS + 16 * k + 4 * i, int(t[2 + i], 16))
        elif c == "bm":
            e.put32(G3["BELT"], k & M32)
        elif c == "dc":
            e.put32(G3["DISABLE"], k & M32)
        elif c == "ab":
            e.put32(fact_at(k) + A_BOOST, int(t[2]) & M32)
        elif c == "np":
            e.mem[CDRIVERS + CDRIVER_STRIDE * k] = int(t[2]) & 0xff
        elif c == "vel":
            for i in range(3):
                e.put32(car + dcc.C_VEL + 4 * i, int(t[2 + i], 16))
        elif c == "fsw":
            e.put32(car + dcc.C_FS, int(t[2], 16))
            e.put32(car + dcc.C_NW, int(t[3]) & M32)
        elif c == "kf":
            f, v = t[2], t[3]
            if f == "glue":
                e.put32(a + KF[f], self.car_ptr(v))
            elif f == "cp":
                e.put32(a + KF[f], self.plr_at(int(v)))
            elif f in ("ba", "la", "bsg"):
                e.put32(a + KF[f], int(v) & M32)
            else:
                e.put32(a + KF[f], int(v, 16))
        elif c in ("whb", "wnb", "wcb"):
            self.emit("  belt %d" % s32(self.call(F[c], a)))
        elif c in ("whg", "wng"):
            self.emit("  glue %d" % s32(self.call(F[c], a)))
        elif c == "wcg":
            got = self.call(F[c], a, self.plr_at(int(t[2])))
            self.emit("  glue %d" % s32(got))
            self.dump_glue(k)
        elif c == "gon":
            self.call(F[c], a, self.plr_at(int(t[2])))
            self.dump_glue(k)
        elif c == "goff":
            self.call(F[c], a)
            self.dump_glue(k)
        elif c == "ggs":
            self.call(F[c], a)
            self.emit("  gspeed %s" % fx(e.fpr[0]))
        elif c == "cdp":
            self.fill(OUTP, 8)
            self.call(F[c], a, RCARS + RC_STRIDE * int(t[2]),
                      RCARS + RC_STRIDE * int(t[3]), OUTP, OUTP + 4)
            self.emit("  dpb %s %s" % (fx(w(OUTP)), fx(w(OUTP + 4))))
        elif c == "dbf":
            self.call(F[c], a)
            self.emit("  boost %s lbt %08x cp %s" % (
                fx(w(car + C_BOOST)), w(a + KF["lbt"]),
                self.name(w(a + KF["cp"]))))
        else:
            return self.pct4(c, k, a, car, t)
        return True

    def pct4(self, c, k, a, car, t):
        """11e-4's ops; False for none of them."""
        e, w = self.e, self.w
        if c == "ctl":
            e.put32(car + dcc.C_CTL, int(t[2]) & M32)
        elif c == "dt":
            e.put32(dcc.DRIVERS + dcc.DRIVER_STRIDE * k + dcc.DRV_TYPE,
                    int(t[2]) & M32)
        elif c == "hk":
            p = car + C_HONK
            for off, v in zip((H_BLINK, H_HONK, H_TWO), t[2:5]):
                e.put32(p + off, int(v) & M32)
            e.put32(p + H_START, int(t[5], 16))
            for off, v in zip((H_ON, H_SECOND, H_OFF), t[6:9]):
                e.put32(p + off, int(v, 16))
            e.put32(p + H_FORCE, int(t[9]) & M32)
        elif c == "ish":
            self.ish[k] = int(t[2])
        elif c == "mh":
            lst = LIST if int(t[3]) == 0 else a + K_LIST
            self.call(F["mh"], a, self.car_ptr(t[2]), lst)
            self.dump_honk(k)
        elif c == "hr":
            self.call(F["honk"], car, int(t[5]) & M32, int(t[6]) & M32,
                      int(t[7]) & M32, f12=int(t[2], 16), f13=int(t[3], 16),
                      f14=int(t[4], 16))
            self.dump_honk(k)
        elif c == "uh":
            self.call(F["uh"], car)
            self.emit("  L state %d" % s32(w(car + C_HONK + H_STATE)))
        elif c == "ad":
            f = fact_at(k)
            e.put32(f + A_USE, int(t[2]) & M32)
            e.put32(f + A_SPEED, int(t[3], 16))
            e.put32(f + A_TIME, int(t[4], 16))
            e.put32(f + A_TOL, int(t[5], 16))
            e.put32(f + A_ALLOWED, int(t[6]) & M32)
        elif c == "at":
            p = fact_at(k) + A_PTD
            e.mem[p] = int(t[2]) & 0xff
            e.put32(p + T_LEN, int(t[3], 16))
            e.put32(p + T_WPC, 5)
            e.put32(p + T_WPT, 7)
            e.mem[p + T_LPS] = 3
        elif c == "sea":
            e.put32(G4["EASY"], k & M32)
        elif c == "bai":
            e.put32(G4["BORING"], k & M32)
        elif c == "lsp":
            e.mem[route_at(k) + dcc.RT_HEADER + dcc.RT_POINT * int(t[2])
                  + TP_SPEEDS + int(t[3])] = int(t[4]) & 0xff
        elif c == "eca":
            self.call(F["eca"], a)
            self.emit("  E la %d lrs %08x boost %s" % (
                s32(w(a + K_LA)), w(a + KF["lrs"]), fx(w(car + C_BOOST))))
            self.dump_ptd(int(t[2]))
        else:
            return self.pct5(c, k, a, car, t)
        return True

    def pct5(self, c, k, a, car, t):
        """11e-5's ops; False for none of them."""
        e, w = self.e, self.w
        if c == "rs":
            e.put32(RACE, k & M32)
        elif c == "wlc":
            e.put32(G5["LOOP"], k & M32)
        elif c == "wt":
            for off, v in zip((W_TOTAL, W_AIPOS, W_COPPOS, W_TRAFFICPOS),
                              t[1:5]):
                e.put32(WORLD + off, int(v) & M32)
            e.mem[WORLD + W_TABLE:WORLD + W_TABLE + 4 * W_MAX_CARS] = bytes(
                4 * W_MAX_CARS)
            for i, v in enumerate(t[5:5 + W_MAX_CARS]):
                e.put32(WORLD + W_TABLE + 4 * i, self.car_ptr(v))
        elif c == "cl":
            nodes = [WORLD] + [car_at(int(v)) for v in t[1:]]
            for i, nd in enumerate(nodes):
                e.put32(nd, nodes[(i + 1) % len(nodes)])
                e.put32(nd + 4, nodes[i - 1])
            for nd in nodes[1:]:
                e.mem[nd + C_RENDER] = 1
                e.put32(nd + C_POOFED, 0)
        elif c == "seed":
            e.put32(G5["SEED"], int(t[1], 16))
        elif c == "rtp":
            e.put32(G5["RESET"], k & M32)
            struct.pack_into("<H", e.mem, G5["ANGLE"], int(t[2]) & 0xffff)
        elif c == "dl":
            e.put32(RCARS + RC_STRIDE * k + RC_DLAP, int(t[2], 16))
        elif c == "pg":
            p = w(a + K_PROG)
            cur = int(t[2]) & 0xff
            e.mem[p + 1] = cur
            e.mem[p + 2] = int(t[3]) & 0xff
            e.put32(p + 4, int(t[4], 16))
            e.put32(w(p + 12) + 4 * cur, int(t[5], 16))
        elif c == "fs":
            e.put32(fact_at(k) + A_CAN, int(t[2]) & M32)
            self.fa_test[k] = (int(t[3]), int(t[4]), int(t[5]))
        elif c == "think":
            self.call(F["think"], a, f12=int(t[2], 16))
            self.dump_think(k)
        elif c == "tcd":
            e.put32(TCD, int(t[1], 16))
            got = self.call(F["tcd"], TCD, f12=int(t[2], 16))
            self.emit("  tcd %d %08x" % (s32(got), w(TCD)))
        elif c == "cas":
            got = self.call(F["cas"], w(GLOBALS["RACE"]))
            self.emit("  cas %d" % s32(got))
        else:
            return False
        return True

    def op(self, t):
        if t[0].startswith("%"):
            self.pct(t)
        else:
            dcc.Model.op(self, t)


# ================================================================ the build


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


def build_harness(tmp, name="aicarcontroller_test"):
    return dcc.hostbuild.build(tmp, SOURCES, name=name)


run_harness = dcc.run_harness
diff = dcc.diff


# ============================================================ the mutations


def M(name, before, after, rel=AICC):
    return (name, rel, before, after)


MUTATIONS = [
    # The constructor.
    M("ct-vt", "    c->Base._vtable = AICARCONTROLLER_VTABLE;\n    // The NearbyCars'",
      "    // The NearbyCars'"),
    M("ct-mycar", "    list->MyCar = car;\n", ""),
    M("ct-stagger", "        (float)car->CarIndex * AICC_EVALUATION_STAGGER;",
      "        (float)car->CarIndex * -AICC_EVALUATION_STAGGER;"),
    M("ct-force", "    c->ForceCurrentAction = AIACTION_NONE;\n    c->LastTrackRouteNumber = -1;",
      "    c->ForceCurrentAction = AIACTION_DRAFT;\n    c->LastTrackRouteNumber = -1;"),
    M("ct-ltr", "    c->LastTrackRouteNumber = -1;\n    c->CurrentAction = NULL;",
      "    c->LastTrackRouteNumber = 0;\n    c->CurrentAction = NULL;"),
    M("ct-list", "    c->CurrentNearbyCarList = list;",
      "    c->CurrentNearbyCarList =\n"
      "        (NearbyCarList *)(void *)c->CurrentDrivingChoice;"),
    M("ct-lookahead", "    c->CurrentRoutePointLookahead = 0;",
      "    c->CurrentRoutePointLookahead = 1;"),
    M("ct-exclude", "    c->CarToExcludeFromCollisionPrediction = NULL;\n"
      "    c->LastBoostCalculationTime", "    c->LastBoostCalculationTime"),
    M("ct-glue", "    c->pGlueCar = NULL;\n    c->GlueOnTimer.PackedTime = 0;",
      "    c->GlueOnTimer.PackedTime = 0;"),
    M("ct-progress", "    timer_set_time(&c->ProgressTimer, AICC_PROGRESS_SECONDS);\n    c->pProgress",
      "    timer_set_time(&c->ProgressTimer, AICC_OFF_BELT_SECONDS);\n    c->pProgress"),
    M("ct-avg10", "                           CAR_MEMORY_POOL), 10);",
      "                           CAR_MEMORY_POOL), 11);"),
    M("ct-avg5", "                           CAR_MEMORY_POOL), 5);",
      "                           CAR_MEMORY_POOL), 4);"),
    M("ct-prev", "    memset(&c->vPreviousLinePoint, 0, sizeof c->vPreviousLinePoint);\n"
      "    c->bBoostAllowed = 1;", "    c->bBoostAllowed = 1;"),
    M("ct-boost", "    c->bBoostAllowed = 1;\n    c->pCatchupPlayer = NULL;",
      "    c->bBoostAllowed = 0;\n    c->pCatchupPlayer = NULL;"),
    M("ct-catchup", "    c->pCatchupPlayer = NULL;\n    c->LastTimeNonGetUnstuckActionWasCalled",
      "    c->pCatchupPlayer = (struct Player *)(void *)c;\n    c->LastTimeNonGetUnstuckActionWasCalled"),
    M("ct-pot", "    c->PullOverTimeout = AICC_PULL_OVER_TIMEOUT;",
      "    c->PullOverTimeout = 0.0f;"),
    M("ct-sign", "    c->nSignpostIndex = signpost_get_index(car->TheTrackPathCoordinate\n"
      "                                               .DistanceAroundTrack);",
      "    c->nSignpostIndex = 0;"),
    M("ct-bs", "    c->BrakeStanding = 1;", "    c->BrakeStanding = 0;"),
    M("ct-tsi", "    c->TakenSignpostIndex = -1;\n    c->TakenSignpostTimer",
      "    c->TakenSignpostIndex = 0;\n    c->TakenSignpostTimer"),
    # The destructor.
    M("dt-action", "    if (c->CurrentAction != NULL)\n        delete_action(c->CurrentAction);\n"
      "    if (c->pProgress", "    if (c->pProgress"),
    M("dt-prog", "    if (c->pProgress != NULL)\n        average_destroy(c->pProgress, 3);\n",
      ""),
    M("dt-dls", "        average_destroy(c->pDeltaLineSpeed, 3);",
      "        average_destroy(c->pDeltaLineSpeed, 2);"),
    M("dt-flags", "    carcontroller_destroy(&c->Base, flags);",
      "    carcontroller_destroy(&c->Base, 0);"),
    # SetCurrentRoute.
    M("sr-null", "    if (r == NULL || p == NULL)\n        return;\n    old =",
      "    if (r == NULL)\n        return;\n    old ="),
    M("sr-ltr", "    c->LastTrackRouteNumber = old != NULL ? (int8_t)old->RouteNumber : -1;",
      "    c->LastTrackRouteNumber = old != NULL ? (int8_t)old->RouteNumber : 0;"),
    M("sr-relax", "    aicarcontroller_get_new_driving_line(c, r, p, 1, &line, NULL);",
      "    aicarcontroller_get_new_driving_line(c, r, p, 0, &line, NULL);"),
    M("sr-relax2", "    drivinglocation_set_route(c->CurrentDrivingLocation, r, p, line, 1);",
      "    drivinglocation_set_route(c->CurrentDrivingLocation, r, p, line, 0);"),
    M("sr-line", "    drivinglocation_set_route(c->CurrentDrivingLocation, r, p, line, 1);",
      "    drivinglocation_set_route(c->CurrentDrivingLocation, r, p, 0, 1);"),
    # The getters' find.
    M("fic-find", "    if (find && drivinglocation_is_clear(c->CurrentDrivingLocation)) {",
      "    if (drivinglocation_is_clear(c->CurrentDrivingLocation)) {"),
    M("fic-clear", "    if (find && drivinglocation_is_clear(c->CurrentDrivingLocation)) {",
      "    if (find && !drivinglocation_is_clear(c->CurrentDrivingLocation)) {"),
    M("gr-route", "    find_if_clear(c, find);\n    return c->CurrentDrivingLocation->pRoute;",
      "    find_if_clear(c, 0);\n    return c->CurrentDrivingLocation->pRoute;"),
    M("gp-point", "    find_if_clear(c, find);\n    return c->CurrentDrivingLocation->pRoutePoint;",
      "    find_if_clear(c, 0);\n    return c->CurrentDrivingLocation->pRoutePoint;"),
    # GetAmountOutOfBounds.
    M("oob-clear", "        return 0.0f;\n    p = c->CurrentDrivingLocation->pRoutePoint;",
      "        return 1.0f;\n    p = c->CurrentDrivingLocation->pRoutePoint;"),
    M("oob-gt", "    if (0.0f < f)\n        return f - p->RightWidth;",
      "    if (0.0f <= f)\n        return f - p->RightWidth;"),
    M("oob-rw", "        return f - p->RightWidth;", "        return f - p->LeftWidth;"),
    M("oob-lw", "    return -(f + p->LeftWidth);", "    return -(f + p->RightWidth);"),
    M("oob-cross", "        - (pos->y - p->Position.y) * p->Direction.x;\n    if (0.0f < f)",
      "        + (pos->y - p->Position.y) * p->Direction.x;\n    if (0.0f < f)"),
    # FindWhereIAm.
    M("fw-clear", "    drivinglocation_clear(c->CurrentDrivingLocation);\n"
      "    e = vt_slot(c->Base._vtable, AICARCONTROLLER_VT_GET_ROUTE_NUMBERS_TO_USE);",
      "    e = vt_slot(c->Base._vtable, AICARCONTROLLER_VT_GET_ROUTE_NUMBERS_TO_USE);"),
    M("fw-swap", "    aicarcontroller_find_closest_track_route(c, first, last);",
      "    aicarcontroller_find_closest_track_route(c, last, first);"),
    # FindClosestTrackRoute.
    M("fc-pass2", "    for (pass = 0; pass < 2 && bestRoute == NULL; pass++) {",
      "    for (pass = 0; pass < 1 && bestRoute == NULL; pass++) {"),
    M("fc-found", "    for (pass = 0; pass < 2 && bestRoute == NULL; pass++) {",
      "    for (pass = 0; pass < 2; pass++) {"),
    M("fc-pass0", "            if (pass <= 0 && !troute_distance_is_within_route(r, d))",
      "            if (!troute_distance_is_within_route(r, d))"),
    M("fc-within", "            if (pass <= 0 && !troute_distance_is_within_route(r, d))",
      "            if (pass <= 0 && troute_distance_is_within_route(r, d))"),
    M("fc-neg", "            TrackRoute *r = i >= 0 ? TheTrackRouteManager.pTrackRoutes[i]",
      "            TrackRoute *r = i > 0 ? TheTrackRouteManager.pTrackRoutes[i]"),
    M("fc-last", "        for (i = first; i <= last; i++) {",
      "        for (i = first; i < last; i++) {"),
    M("fc-flags", "                AICC_ROUTE_RADIUS, AICC_ROUTE_FLAGS, 0.0f);",
      "                AICC_ROUTE_RADIUS, TRFIND_AHEAD_ONLY, 0.0f);"),
    M("fc-flags2", "                AICC_ROUTE_RADIUS, AICC_ROUTE_FLAGS, 0.0f);",
      "                AICC_ROUTE_RADIUS, TRFIND_POSTED_ONLY, 0.0f);"),
    M("fc-radius", "                AICC_ROUTE_RADIUS, AICC_ROUTE_FLAGS, 0.0f);",
      "                40.0f, AICC_ROUTE_FLAGS, 0.0f);"),
    M("fc-nopoint", "            if (p == NULL)\n                continue;\n            trpoint",
      "            if (p == NULL)\n                break;\n            trpoint"),
    M("fc-dx", "            dv.x = car->State.Position.x - v.x;",
      "            dv.x = car->State.Position.y - v.x;"),
    M("fc-dz", "            dv.z = car->State.Position.z - v.z;", "            dv.z = 0.0f;"),
    M("fc-lt", "            if (dist < best && r != current) {",
      "            if (dist <= best && r != current) {"),
    M("fc-cur", "            if (dist < best && r != current) {",
      "            if (dist < best) {"),
    M("fc-best", "                best = dist;\n", ""),
    M("fc-ret", "        ((SetRouteFn)e->fn)(vt_this(c, e), bestRoute, bestPoint);\n        return;",
      "        ((SetRouteFn)e->fn)(vt_this(c, e), bestRoute, bestPoint);"),
    M("fc-cl-line", "    c->CurrentDrivingLocation->DrivingLine = -1;\n"
      "    c->CurrentDrivingLocation->LastRelaxed",
      "    c->CurrentDrivingLocation->DrivingLine = 0;\n"
      "    c->CurrentDrivingLocation->LastRelaxed"),
    M("fc-cl-time", "    c->CurrentDrivingLocation->LastRelaxedDrivingLineSwitchTime.PackedTime = 0;\n"
      "    c->CurrentDrivingLocation->pRoute = NULL;",
      "    c->CurrentDrivingLocation->pRoute = NULL;"),
    M("fc-cl-route", "    c->CurrentDrivingLocation->pRoute = NULL;\n"
      "    c->CurrentDrivingLocation->pRoutePoint = NULL;\n}",
      "    c->CurrentDrivingLocation->pRoutePoint = NULL;\n}"),
    M("fc-cl-point", "    c->CurrentDrivingLocation->pRoutePoint = NULL;\n}\n\nint",
      "}\n\nint"),
    # GetNewDrivingLine.
    M("gl-init", "    *line = drivingchoice_get_driving_line(CHOICE_DRIVING_LINE_0,\n"
      "                                           c->Base.pCar);",
      "    *line = 0;"),
    M("gl-rp", "    if (r != NULL && p != NULL) {\n        DrivingChoiceType type;",
      "    if (r != NULL) {\n        DrivingChoiceType type;"),
    M("gl-n", "             type - 1 < AICarControllerNumDrivingLinesToConsider; type++) {",
      "             type - 1 <= AICarControllerNumDrivingLinesToConsider; type++) {"),
    M("gl-type", "            drivingchoice_set_choice(&ch, type, NULL, 0);",
      "            drivingchoice_set_choice(&ch, CHOICE_DRIVING_LINE_0, NULL, 0);"),
    M("gl-relax", "                &l, drivingchoice_get_driving_line(type, c->Base.pCar),\n"
      "                relaxed);", "                &l, drivingchoice_get_driving_line(type, c->Base.pCar),\n"
      "                0);"),
    M("gl-relax0", "    drivinglocation_set_route(&l, r, p, *line, relaxed);",
      "    drivinglocation_set_route(&l, r, p, *line, !relaxed);"),
    M("gl-time", "                    AIDriverAvoidCarsImpactTimeThreshold, 0.0f,",
      "                    0.5f, 0.0f,"),
    M("gl-move", "                    MOVEMENT_TOWARDS_LINE)) {",
      "                    MOVEMENT_PARALLEL_TO_LINE)) {"),
    M("gl-list", "                    c->CurrentNearbyCarList, 0.0f,\n                    AIDriverAvoid",
      "                    &c->MyCurrentDrivingInformation.MyNearbyCarList, 0.0f,\n                    AIDriverAvoid"),
    M("gl-found", "                found = 1;", "                found = 0;"),
    M("gl-line", "                *line = drivingchoice_get_driving_line(type, c->Base.pCar);\n"
      "                break;", "                break;"),
    M("gl-break", "                *line = drivingchoice_get_driving_line(type, c->Base.pCar);\n"
      "                break;", "                *line = drivingchoice_get_driving_line(type, c->Base.pCar);"),
    M("gl-hl", "        if (highlight != NULL)\n            ai_highlight_driving_line(highlight,",
      "        if (highlight != NULL && 0)\n            ai_highlight_driving_line(highlight,"),
    M("gl-hl-loc", "            ai_highlight_driving_line(highlight,",
      "            ai_highlight_driving_line(&l,"),
    # JustReset, GetMyDriverNumber, ClearStickyDecisions,
    # SteerStraightAhead.
    M("jr-stagger", "        (float)c->Base.pCar->CarIndex * AICC_EVALUATION_STAGGER;",
      "        (float)c->Base.pCar->CarIndex * -AICC_EVALUATION_STAGGER;"),
    M("jr-prev", "    memset(&c->vPreviousLinePoint, 0, sizeof c->vPreviousLinePoint);\n"
      "    d = c->Base.Driver;", "    d = c->Base.Driver;"),
    M("jr-zsm", "    e = vt_slot(d->_vtable, CARDRIVER_VT_ZERO_STEERING_MEMORY);",
      "    e = vt_slot(d->_vtable, CARDRIVER_VT_CLEAR_STEERING_MEMORY);"),
    M("jr-sticky", "    aicarcontroller_clear_sticky_decisions(c);\n"
      "    c->nSignpostIndex = signpost_get_index(\n",
      "    c->nSignpostIndex = signpost_get_index(\n"),
    M("jr-sign", "    c->nSignpostIndex = signpost_get_index(\n"
      "        c->Base.pCar->TheTrackPathCoordinate.DistanceAroundTrack);",
      "    c->nSignpostIndex = 0;"),
    M("dn", "    return c->Base.pCar->DriverNumber;", "    return c->Base.pCar->CarIndex;"),
    M("cs-mask", "        c->aStickyDecisions[i] &= ~1u;\n}",
      "        c->aStickyDecisions[i] &= ~2u;\n}"),
    M("cs-n", "    for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++)\n"
      "        c->aStickyDecisions[i] &= ~1u;\n}",
      "    for (i = 1; i < AICC_NUM_STICKY_DECISIONS; i++)\n"
      "        c->aStickyDecisions[i] &= ~1u;\n}"),
    M("st-swap", "    float cs = bCosBam(a), sn = bSinBam(a);",
      "    float cs = bSinBam(a), sn = bCosBam(a);"),
    M("st-x", "    to.x = car->State.Position.x + cs;", "    to.x = car->State.Position.x - cs;"),
    M("st-y", "    to.y = car->State.Position.y + sn;", "    to.y = car->State.Position.y - sn;"),
    M("st-slot", "    e = vt_slot(d->_vtable, CARDRIVER_VT_SET_STEER_TO_POINT);",
      "    e = vt_slot(d->_vtable, CARDRIVER_VT_GET_STEER_TO_POINT);"),
    # InterruptAction.
    M("ia-force", "    if (c->ForceCurrentAction == AIACTION_NONE) {",
      "    if (c->ForceCurrentAction != AIACTION_NONE) {"),
    M("ia-type", "        choose_new_action(c, &a, AIACTION_NONE);",
      "        choose_new_action(c, &a, AIACTION_DRAFT);"),
    M("ia-null", "        if (a == NULL)\n            return NULL;\n", ""),
    M("ia-cur", "        if (c->CurrentAction != NULL && c->CurrentAction->Score < a->Score)",
      "        if (c->CurrentAction == NULL || c->CurrentAction->Score < a->Score)"),
    M("ia-lt", "        if (c->CurrentAction != NULL && c->CurrentAction->Score < a->Score)",
      "        if (c->CurrentAction != NULL && c->CurrentAction->Score <= a->Score)"),
    M("ia-del", "        delete_action(a);\n        return NULL;", "        return NULL;"),
    M("ia-reset", "    choose_new_action(c, &a, c->ForceCurrentAction);\n"
      "    c->ForceCurrentAction = AIACTION_NONE;",
      "    choose_new_action(c, &a, c->ForceCurrentAction);"),
    # GeneratePointsToFulfillAction.
    M("gp-ahead", "    nearbycarlist_get_car_ahead(c->CurrentNearbyCarList, c->Base.pCar);\n",
      ""),
    M("gp-will", "    if (!a->PointsToDriveWillExecuteAction) {",
      "    if (a->PointsToDriveWillExecuteAction) {"),
    M("gp-del", "        if (c->CurrentAction != NULL)\n            delete_action(c->CurrentAction);\n"
      "        c->CurrentAction = NULL;", "        c->CurrentAction = NULL;"),
    M("gp-draft", "        choose_new_action(c, &c->CurrentAction, AIACTION_DRAFT);",
      "        choose_new_action(c, &c->CurrentAction, AIACTION_NONE);"),
    M("gp-calc2", "        action_calculate_points(c->CurrentAction, info);\n    }",
      "    }"),
    M("gp-isline", "    if (drivingchoice_type_is_driving_line(type)) {",
      "    if (type != CHOICE_NONE) {"),
    M("gp-ne", "        if (line != c->CurrentDrivingLocation->DrivingLine) {",
      "        if (1) {"),
    M("gp-relax", "            drivinglocation_set_driving_line(c->CurrentDrivingLocation, line,\n"
      "                                             0);",
      "            drivinglocation_set_driving_line(c->CurrentDrivingLocation, line,\n"
      "                                             1);"),
    M("gp-hl", "            ai_highlight_driving_line(c->CurrentDrivingLocation,\n"
      "                                      aicarcontroller_get_my_driver_number(c));\n"
      "        }", "        }"),
    # The action's getter and setter.
    M("cat", "                                    : AIACTION_NONE;",
      "                                    : AIACTION_DRAFT;"),
    M("force", "    c->ForceCurrentAction = type;", "    c->ForceCurrentAction = AIACTION_NONE;"),
    # SetToPhysicsMode.
    M("pm-belt", "    if (old == BELT_MOVEMENT)", "    if (old != BELT_MOVEMENT)"),
    M("pm-belt-s", "    timer_set_time(&c->OffBeltTimer, AICC_OFF_BELT_SECONDS);",
      "    timer_set_time(&c->OffBeltTimer, AICC_REAL_PHYSICS_SECONDS);"),
    M("pm-def", "    MovementMode mode = nDefaultMovementMode;",
      "    MovementMode mode = MELLOW_MOVEMENT;"),
    M("pm-car", "    if (car != NULL && car->pPlayer != NULL)\n        mode = PHYSICS_MOVEMENT;",
      "    if (car != NULL)\n        mode = PHYSICS_MOVEMENT;"),
    M("pm-mine", "    if (car != NULL && car->pPlayer != NULL)\n        mode = PHYSICS_MOVEMENT;",
      "    if (mine->pPlayer != NULL)\n        mode = PHYSICS_MOVEMENT;"),
    M("pm-ne", "    if (mode != old)\n        car_set_movement_mode(mine, mode);",
      "    car_set_movement_mode(mine, mode);"),
    M("pm-phys", "    if (mode == PHYSICS_MOVEMENT)\n        timer_set_time(&c->RealPhysicsTimer",
      "    if (mode != PHYSICS_MOVEMENT)\n        timer_set_time(&c->RealPhysicsTimer"),
    M("pm-rp-s", "        timer_set_time(&c->RealPhysicsTimer, AICC_REAL_PHYSICS_SECONDS);",
      "        timer_set_time(&c->RealPhysicsTimer, AICC_OFF_BELT_SECONDS);"),
    # The line speed, the boost, the exclusion.
    M("ls-clear", "        return 0.0f;\n    b = (const uint8_t *)l->pRoutePoint",
      "        return 1.0f;\n    b = (const uint8_t *)l->pRoutePoint"),
    M("ls-off", "        + offsetof(TrackRoutePoint, DrivingLineSpeeds) + l->DrivingLine;",
      "        + offsetof(TrackRoutePoint, DrivingLineSpeeds) + l->DrivingLine + 1;"),
    M("fb", "    carcontroller_force_boost(&c->Base, f);\n    c->bBoostAllowed = 0;",
      "    carcontroller_force_boost(&c->Base, f);\n    c->bBoostAllowed = 1;"),
    M("fb-f", "    carcontroller_force_boost(&c->Base, f);",
      "    carcontroller_force_boost(&c->Base, 1.0f);"),
    M("rb", "    carcontroller_release_boost(&c->Base);\n    c->bBoostAllowed = 1;",
      "    carcontroller_release_boost(&c->Base);\n    c->bBoostAllowed = 0;"),
    M("rb-call", "    carcontroller_release_boost(&c->Base);\n", ""),
    M("ob", "    timer_set_time(&c->OffBeltTimer, seconds);",
      "    timer_set_time(&c->OffBeltTimer, seconds + 1.0f);"),
    M("gx", "    return c->CarToExcludeFromCollisionPrediction;", "    return NULL;"),
    M("ex", "    c->CarToExcludeFromCollisionPrediction = car;",
      "    c->CarToExcludeFromCollisionPrediction = NULL;"),
    # The table, which the test table copies.
    M("vt-sr", "    E(aicarcontroller_set_current_route),             //  40",
      "    E(aicarcontroller_debug_display),                 //  40"),
    M("vt-fw", "    E(aicarcontroller_find_where_i_am),               //  72",
      "    E(aicarcontroller_debug_display),                 //  72"),
    # CarController::SetToPhysicsMode, retail's.
    M("cc-phys", "    if (car->TheMovementMode == PHYSICS_MOVEMENT\n"
      "        || car->TheMovementMode == MELLOW_MOVEMENT)\n        return;",
      "    if (car->TheMovementMode == MELLOW_MOVEMENT)\n        return;", rel=CCC),
    M("cc-mellow", "    if (car->TheMovementMode == PHYSICS_MOVEMENT\n"
      "        || car->TheMovementMode == MELLOW_MOVEMENT)\n        return;",
      "    if (car->TheMovementMode == PHYSICS_MOVEMENT)\n        return;", rel=CCC),
    M("cc-player", "    car_set_movement_mode(car, car->pPlayer != NULL ? PHYSICS_MOVEMENT\n"
      "                                                    : MELLOW_MOVEMENT);",
      "    car_set_movement_mode(car, MELLOW_MOVEMENT);", rel=CCC),
    M("cc-arg", "    (void)car;\n    carcontroller_physics_or_mellow(c->pCar);",
      "    carcontroller_physics_or_mellow(car != NULL ? car : c->pCar);",
      rel=CCC),
    # 11e-2's. The index's step and FindSignpostIndex.
    M("ns-wrap", "    c->nSignpostIndex = i;\n    if (!(i < (int32_t)NumSignposts))",
      "    c->nSignpostIndex = i;\n    if (!(i <= (int32_t)NumSignposts))"),
    M("ns-zero", "    if (!(i < (int32_t)NumSignposts))\n        c->nSignpostIndex = 0;",
      "    if (!(i < (int32_t)NumSignposts))\n        c->nSignpostIndex = 1;"),
    M("fsi-lt", "    while (SignpostArray[c->nSignpostIndex].Distance < mine) {",
      "    while (SignpostArray[c->nSignpostIndex].Distance <= mine) {"),
    M("fsi-wrap", "        if (!(i < (int32_t)NumSignposts)) {",
      "        if (!(i <= (int32_t)NumSignposts)) {"),
    M("fsi-zero", "            c->nSignpostIndex = 0;\n            return;",
      "            c->nSignpostIndex = 1;\n            return;"),
    M("fsi-mine", "    // 0x00191d40.\n    float mine = c->Base.pCar->TheTrackPathCoordinate.DistanceAroundTrack;",
      "    // 0x00191d40.\n    float mine = c->Base.pCar->State.VelocityMagnitude;"),
    # GetStickyIndex.
    M("gsi-bit", "        if (!(c->aStickyDecisions[i] & STICKY_USED))\n            return i;",
      "        if (!(c->aStickyDecisions[i] & STICKY_TAKE))\n            return i;"),
    M("gsi-none", "            return i;\n    return -1;", "            return i;\n    return 0;"),
    M("gsi-n", "    for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++)\n"
      "        if (!(c->aStickyDecisions[i] & STICKY_USED))",
      "    for (i = 0; i < AICC_NUM_STICKY_DECISIONS - 1; i++)\n"
      "        if (!(c->aStickyDecisions[i] & STICKY_USED))"),
    # DoStickyDecisions.
    M("dsd-used", "        if (!(w & STICKY_USED))\n            continue;\n", ""),
    M("dsd-drop", "        if (AICC_STICKY_DROP\n            < trackpath_compare_distances(",
      "        if (AICC_STICKY_DROP\n            <= trackpath_compare_distances("),
    M("dsd-drop-k", "#define AICC_STICKY_DROP      10.0f",
      "#define AICC_STICKY_DROP      10.5f"),
    M("dsd-drop-args", "                &TheTrackPathManager, mine,\n"
      "                SignpostArray[STICKY_SIGN(w)].Distance)) {",
      "                &TheTrackPathManager,\n"
      "                SignpostArray[STICKY_SIGN(w)].Distance, mine)) {"),
    M("dsd-clear", "            c->aStickyDecisions[i] &= ~STICKY_USED;",
      "            c->aStickyDecisions[i] &= ~STICKY_TAKE;"),
    M("dsd-ts", "                == c->TakenSignpostIndex)\n                c->TakenSignpostIndex = -1;",
      "                == c->TakenSignpostIndex)\n                c->TakenSignpostIndex = 0;"),
    M("dsd-ts-test", "                == c->TakenSignpostIndex)\n",
      "                != c->TakenSignpostIndex)\n"),
    M("dsd-scale", "#define AICC_SIGN_SPEED_SCALE 1.10000002f",
      "#define AICC_SIGN_SPEED_SCALE 1.20000005f"),
    M("dsd-secs", "    ahead = AIDriverSecondsToLookAhead\n            * (car->State.VelocityMagnitude",
      "    ahead = 2.0f\n            * (car->State.VelocityMagnitude"),
    M("dsd-min", "#define AICC_SIGN_AHEAD_MIN   100.0f",
      "#define AICC_SIGN_AHEAD_MIN   101.0f"),
    M("dsd-max", "#define AICC_SIGN_AHEAD_MAX   250.0f",
      "#define AICC_SIGN_AHEAD_MAX   249.0f"),
    M("dsd-clamp", "    ahead = min_s(AICC_SIGN_AHEAD_MAX, max_s(ahead, AICC_SIGN_AHEAD_MIN));",
      "    ahead = max_s(AICC_SIGN_AHEAD_MIN, min_s(ahead, AICC_SIGN_AHEAD_MAX));"),
    M("dsd-max-args", "    ahead = min_s(AICC_SIGN_AHEAD_MAX, max_s(ahead, AICC_SIGN_AHEAD_MIN));",
      "    ahead = min_s(AICC_SIGN_AHEAD_MAX, max_s(AICC_SIGN_AHEAD_MIN, ahead));"),
    M("dsd-loop", "    while (aicarcontroller_get_sticky_index(c) != -1) {",
      "    while (aicarcontroller_get_sticky_index(c) > 0) {"),
    M("dsd-behind", "        if (d < 0.0f) {\n            next_signpost(c);",
      "        if (d <= 0.0f) {\n            next_signpost(c);"),
    M("dsd-ahead", "        } else if (d < ahead) {", "        } else if (d <= ahead) {"),
    M("dsd-d-args", "        float d = trackpath_compare_distances(&TheTrackPathManager,\n"
      "                                              s->Distance, mine);",
      "        float d = trackpath_compare_distances(&TheTrackPathManager,\n"
      "                                              mine, s->Distance);"),
    M("dsd-line", "            int32_t line = -1;\n\n            aicarcontroller_sign_post_decision(",
      "            int32_t line = 0;\n\n            aicarcontroller_sign_post_decision("),
    # The line a sign not taken keeps, and the sign grace period.
    M("kl-clear", "    if (drivinglocation_is_clear(loc))\n        return drivingchoice_get_driving_line(",
      "    if (0)\n        return drivingchoice_get_driving_line("),
    M("kl-line", "        return drivingchoice_get_driving_line(CHOICE_DRIVING_LINE_0,",
      "        return drivingchoice_get_driving_line(CHOICE_DRIVING_LINE_1,"),
    M("pg-neg1", "    if (g == -1)\n        return !race_grace_period_is_active(",
      "    if (g < 0)\n        return !race_grace_period_is_active("),
    M("pg-race", "        return !race_grace_period_is_active(pCurrentRace, c->Base.pCar);",
      "        return race_grace_period_is_active(pCurrentRace, c->Base.pCar);"),
    M("pg-lt", "    return (float)g < (float)(int32_t)pCurrentRace->RaceTime.PackedTime",
      "    return (float)g <= (float)(int32_t)pCurrentRace->RaceTime.PackedTime"),
    M("pg-tick", "#define AICC_TICKS_TO_SECONDS 0.000250000012f",
      "#define AICC_TICKS_TO_SECONDS 0.000250000041f"),
    M("pg-track", "    int32_t g = track_get_info(TheRaceParameters.TrackNumber)",
      "    int32_t g = track_get_info(0)"),
    M("pg-unsigned", "    return (float)g < (float)(int32_t)pCurrentRace->RaceTime.PackedTime",
      "    return (float)g < (float)(uint32_t)pCurrentRace->RaceTime.PackedTime"),
    # The draw by skill.
    M("tk-max", "    skill = skill < 0 ? 0 : skill;\n", ""),
    M("tk-min", "    skill = skill < 9 ? skill : 9;", "    skill = skill < 8 ? skill : 8;"),
    M("tk-arg", "    r = world_random_f(pCurrentWorld, 1.0f);\n    chance =",
      "    r = world_random_f(pCurrentWorld, 0.5f);\n    chance ="),
    M("tk-row", "    chance = TheDifficultyInfo.AISkillLevel[skill].TakeSignChance;",
      "    chance = TheDifficultyInfo.AISkillLevel[0].TakeSignChance;"),
    M("tk-le0", "    if (r <= chance[0])", "    if (r < chance[0])"),
    M("tk-le1", "    else if (r <= chance[1])", "    else if (r < chance[1])"),
    M("tk-le2", "    else if (r <= chance[2])", "    else if (r < chance[2])"),
    M("tk-k2", "        k = 2;\n    else if (r <= chance[1])",
      "        k = 3;\n    else if (r <= chance[1])"),
    M("tk-k1", "        k = 1;\n    else if (r <= chance[2])",
      "        k = 2;\n    else if (r <= chance[2])"),
    M("tk-k3", "        k = 3;\n    switch (k) {", "        k = 0;\n    switch (k) {"),
    M("tk-case0", "        return sign == SIGN_FASTER;\n    case 2:",
      "        return sign == SIGN_SLOWER;\n    case 2:"),
    M("tk-case2", "    case 2:\n        return sign == SIGN_SLOWER;",
      "    case 2:\n        return sign == SIGN_FASTER;"),
    M("tk-default", "    default:\n        return 0;\n    }\n}",
      "    default:\n        return 1;\n    }\n}"),
    # SignPostDecision.
    M("sp-back", "    if ((flags & SIGNPOST_BACKWARDS) != 0\n        ||",
      "    if (0\n        ||"),
    M("sp-cloak", "        || ((flags & SIGNPOST_CLOAKED) != 0 && sign != SIGN_ALWAYS_TAKE)) {",
      "        || (flags & SIGNPOST_CLOAKED) != 0) {"),
    M("sp-cloak-at", "        || ((flags & SIGNPOST_CLOAKED) != 0 && sign != SIGN_ALWAYS_TAKE)) {",
      "        || ((flags & SIGNPOST_CLOAKED) != 0 && sign != SIGN_EQUIVALENT)) {"),
    M("sp-early-line", "        *line = keep_line(c, loc);\n        return 0;",
      "        return 0;"),
    M("sp-index", "    index = (uint32_t)(s - SignpostArray) & 0xffu;",
      "    index = (uint32_t)(s - SignpostArray + 1) & 0xffu;"),
    M("sp-match-used", "        if ((w & STICKY_USED) && STICKY_SIGN(w) == index) {",
      "        if (STICKY_SIGN(w) == index) {"),
    M("sp-match-line", "            *line = (int32_t)((w >> 2) & 0x3fu);",
      "            *line = (int32_t)((w >> 2) & 0x1fu);"),
    M("sp-match-take", "            return (int)((w >> 1) & 1u);",
      "            return (int)(w & 1u);"),
    M("sp-at", "    if (sign == SIGN_ALWAYS_TAKE) {\n        take = 1;",
      "    if (sign == SIGN_STOP) {\n        take = 1;"),
    M("sp-grace", "        if (!past_sign_grace(c))\n            take = 0;",
      "        if (past_sign_grace(c))\n            take = 0;"),
    M("sp-eq", "            take = world_random_f(pCurrentWorld, 1.0f) < 0.5f;",
      "            take = world_random_f(pCurrentWorld, 1.0f) <= 0.5f;"),
    M("sp-eq-sign", "        else if (sign == SIGN_EQUIVALENT)",
      "        else if (sign == SIGN_STOP)"),
    M("sp-dont", "        else if (sign == SIGN_DONT_TAKE)\n            take = 0;",
      "        else if (sign == SIGN_DONT_TAKE)\n            take = 1;"),
    M("sp-notake-line", "            *line = loc->DrivingLine;",
      "            *line = keep_line(c, loc);"),
    M("sp-relaxed", "                       signpost_get_new_route_point(s), 1, line, loc)) {",
      "                       signpost_get_new_route_point(s), 0, line, loc)) {"),
    M("sp-hint", "            if (s->AIHint == SIGNPOST_AIHINT_HOLD_LINE_SPEED)",
      "            if (s->AIHint != SIGNPOST_AIHINT_HOLD_LINE_SPEED)"),
    M("sp-hint-idx", "                c->TakenSignpostIndex = (int32_t)index;",
      "                c->TakenSignpostIndex = (int32_t)index + 1;"),
    M("sp-fail", "        } else {\n            take = 0;\n        }\n    }",
      "        } else {\n            take = 1;\n        }\n    }"),
    M("sp-again", "    if (take && *line < 0)\n", "    if (take && *line < -1)\n"),
    M("sp-again-take", "    if (take && *line < 0)\n", "    if (*line < 0)\n"),
    M("sp-again-relaxed", "            c, signpost_get_new_route(s), signpost_get_new_route_point(s), 1,\n",
      "            c, signpost_get_new_route(s), signpost_get_new_route_point(s), 0,\n"),
    M("sp-range", "    if (!((uint32_t)*line < 2u))", "    if (!((uint32_t)*line < 3u))"),
    M("sp-range-signed", "    if (!((uint32_t)*line < 2u))", "    if (!(*line < 2))"),
    M("sp-slot0", "    slotp = slot >= 0 ? &c->aStickyDecisions[slot]",
      "    slotp = slot > 0 ? &c->aStickyDecisions[slot]"),
    M("sp-slot-full", "                      : (uint32_t *)(void *)&c->nSignpostIndex;",
      "                      : &c->aStickyDecisions[0];"),
    M("sp-store-used", "    v = ((*slotp | STICKY_USED) & ~STICKY_TAKE) | ((uint32_t)take << 1);",
      "    v = (*slotp & ~STICKY_TAKE) | ((uint32_t)take << 1);"),
    M("sp-store-take", "    v = ((*slotp | STICKY_USED) & ~STICKY_TAKE) | ((uint32_t)take << 1);",
      "    v = (*slotp | STICKY_USED) | ((uint32_t)take << 1);"),
    M("sp-store-line", "    v = (v & ~STICKY_LINE_MASK) | (((uint32_t)*line & 0x3fu) << 2);",
      "    v = v | (((uint32_t)*line & 0x3fu) << 2);"),
    M("sp-store-sign", "    *slotp = (v & ~0xff00u) | (index << 8);",
      "    *slotp = v | (index << 8);"),
    M("sp-store-hi", "    *slotp = (v & ~0xff00u) | (index << 8);",
      "    *slotp = (v & 0xffu) | (index << 8);"),
    M("sp-ret", "    *slotp = (v & ~0xff00u) | (index << 8);\n    return take;",
      "    *slotp = (v & ~0xff00u) | (index << 8);\n    return 1;"),
    # GetCurrentTrackRoutePoint.
    M("gc-margin", "    float margin = c->MyCurrentDrivingInformation.MyNearbyCarList.MyHalfSizeL;",
      "    float margin = c->MyCurrentDrivingInformation.MyNearbyCarList.MyHalfSizeD;"),
    M("gc-clear", "        find_where_i_am(c);\n        return;\n    }\n    p = loc->pRoutePoint;",
      "        return;\n    }\n    p = loc->pRoutePoint;"),
    M("gc-cross", "        - (pos->y - p->Position.y) * p->Direction.x;\n"
      "    if (p->RightWidth",
      "        + (pos->y - p->Position.y) * p->Direction.x;\n"
      "    if (p->RightWidth"),
    M("gc-right", "    if (p->RightWidth < f - margin || f + margin < -p->LeftWidth) {",
      "    if (p->RightWidth <= f - margin || f + margin < -p->LeftWidth) {"),
    M("gc-left", "    if (p->RightWidth < f - margin || f + margin < -p->LeftWidth) {",
      "    if (p->RightWidth < f - margin || f + margin <= -p->LeftWidth) {"),
    M("gc-sides", "    if (p->RightWidth < f - margin || f + margin < -p->LeftWidth) {",
      "    if (p->LeftWidth < f - margin || f + margin < -p->RightWidth) {"),
    M("gc-margin-sign", "    if (p->RightWidth < f - margin || f + margin < -p->LeftWidth) {",
      "    if (p->RightWidth < f + margin || f - margin < -p->LeftWidth) {"),
    M("gc-off-find", "        find_where_i_am(c);\n        return;\n    }\n    r = loc->pRoute;",
      "        return;\n    }\n    r = loc->pRoute;"),
    M("gc-end", "    if (np == NULL) {\n        atEnd = 1;", "    if (np == NULL) {\n        atEnd = 0;"),
    M("gc-last", "        np = &r->TrackRoutePointTable[r->NumPoints - 1];",
      "        np = &r->TrackRoutePointTable[r->NumPoints - 2];"),
    M("gc-setpt", "    drivinglocation_set_route_point(c->CurrentDrivingLocation, np);\n", ""),
    M("gc-from", "    for (i = troute_get_point_number(r, p); i <= last; i++) {",
      "    for (i = troute_get_point_number(r, p) + 1; i <= last; i++) {"),
    M("gc-to", "    for (i = troute_get_point_number(r, p); i <= last; i++) {",
      "    for (i = troute_get_point_number(r, p); i < last; i++) {"),
    M("gc-line", "        int32_t line = -1;\n\n        if (!trpoint_has_signpost(pt))",
      "        int32_t line = 0;\n\n        if (!trpoint_has_signpost(pt))"),
    M("gc-ltr", "                                          : (int8_t)l->pRoute->RouteNumber;",
      "                                          : (int8_t)(l->pRoute->RouteNumber + 1);"),
    M("gc-relaxed", "                                      signpost_get_new_route_point(s), line,\n"
      "                                      1);",
      "                                      signpost_get_new_route_point(s), line,\n"
      "                                      0);"),
    M("gc-break", "                    (int32_t)AICC_TAKEN_SIGN_TICKS;\n            break;\n",
      "                    (int32_t)AICC_TAKEN_SIGN_TICKS;\n"),
    M("gc-hint", "            if (s->AIHint == 1)", "            if (s->AIHint == 2)"),
    M("gc-timer", "#define AICC_TAKEN_SIGN_TICKS 10000.5f",
      "#define AICC_TAKEN_SIGN_TICKS 10001.5f"),
    M("gc-end-find", "    if (atEnd && !took)", "    if (atEnd)"),
    M("gc-end-took", "    if (atEnd && !took)", "    if (!took)"),
    # 11e-3's. The belt.
    M("whb-mode", "    return c->Base.pCar->TheMovementMode == BELT_MOVEMENT;",
      "    return c->Base.pCar->TheMovementMode != BELT_MOVEMENT;"),
    M("wnb-flag", "    return bBeltMover != 0;", "    return 1;"),
    M("wcb-np", "    if (c->Base.Driver->MyDriveTarget.NumPoints < 3)",
      "    if (c->Base.Driver->MyDriveTarget.NumPoints < 2)"),
    M("wcb-np-le", "    if (c->Base.Driver->MyDriveTarget.NumPoints < 3)",
      "    if (c->Base.Driver->MyDriveTarget.NumPoints <= 3)"),
    M("wcb-demo", "        == RCSTATE_AI_DEMO_MODE)\n        return 0;\n    if (timer_is_valid(&c->OffBeltTimer)",
      "        == RCSTATE_POSTRACE)\n        return 0;\n    if (timer_is_valid(&c->OffBeltTimer)"),
    M("wcb-ob", "    if (timer_is_valid(&c->OffBeltTimer)\n        || timer_is_valid(&c->RealPhysicsTimer))",
      "    if (timer_is_valid(&c->RealPhysicsTimer))"),
    M("wcb-rp", "    if (timer_is_valid(&c->OffBeltTimer)\n        || timer_is_valid(&c->RealPhysicsTimer))",
      "    if (timer_is_valid(&c->OffBeltTimer))"),
    M("wcb-speed", "#define AICC_BELT_MIN_SPEED       5.0f", "#define AICC_BELT_MIN_SPEED       5.5f"),
    M("wcb-speed-le", "    if (car->State.ForwardSpeed < AICC_BELT_MIN_SPEED",
      "    if (car->State.ForwardSpeed <= AICC_BELT_MIN_SPEED"),
    M("wcb-wheels", "        || car->State.nWheelsTouchingGround <= 0)\n        return 0;\n    if (c->CurrentAction == NULL)\n        return 0;\n    type",
      "        || car->State.nWheelsTouchingGround < 0)\n        return 0;\n    if (c->CurrentAction == NULL)\n        return 0;\n    type"),
    M("wcb-noact", "    if (c->CurrentAction == NULL)\n        return 0;\n    type = c->CurrentAction->Type;",
      "    if (c->CurrentAction == NULL)\n        return 1;\n    type = c->CurrentAction->Type;"),
    M("wcb-po", "    if (type == AIACTION_PULL_OVER || type == AIACTION_GET_UNSTUCK",
      "    if (0 || type == AIACTION_GET_UNSTUCK"),
    M("wcb-gu", "    if (type == AIACTION_PULL_OVER || type == AIACTION_GET_UNSTUCK",
      "    if (type == AIACTION_PULL_OVER || 0"),
    M("wcb-ar", "        || type == AIACTION_ACCIDENT_RECOVERY\n        || type == AIACTION_AVOID_ROADBLOCK",
      "        || 0\n        || type == AIACTION_AVOID_ROADBLOCK"),
    M("wcb-rb", "        || type == AIACTION_AVOID_ROADBLOCK\n        || type == AIACTION_I_JUST_GOT_HIT)",
      "        || 0\n        || type == AIACTION_I_JUST_GOT_HIT)"),
    M("wcb-ij", "        || type == AIACTION_AVOID_ROADBLOCK\n        || type == AIACTION_I_JUST_GOT_HIT)",
      "        || type == AIACTION_AVOID_ROADBLOCK\n        || 0)"),
    M("wcb-careful", "#define AICC_CAREFUL_SKILL        (-2)", "#define AICC_CAREFUL_SKILL        (-1)"),
    M("wcb-range", "#define AICC_BELT_PLAYER_RANGE  120.0f", "#define AICC_BELT_PLAYER_RANGE  121.0f"),
    M("wcb-range-le", "        < AICC_BELT_PLAYER_RANGE)", "        <= AICC_BELT_PLAYER_RANGE)"),
    M("wcb-race", "#define AICC_BELT_RACE_SECONDS   30.0f", "#define AICC_BELT_RACE_SECONDS   30.5f"),
    M("wcb-race-le", "             < AICC_BELT_RACE_SECONDS);", "             <= AICC_BELT_RACE_SECONDS);"),
    M("wcb-race-u", "    return !((float)(int32_t)pCurrentRace->RaceTime.PackedTime",
      "    return !((float)pCurrentRace->RaceTime.PackedTime"),
    M("wcb-race-not", "    return !((float)(int32_t)pCurrentRace->RaceTime.PackedTime",
      "    return !!((float)(int32_t)pCurrentRace->RaceTime.PackedTime"),
    # The glue.
    M("whg-car", "    return c->pGlueCar != NULL;", "    return c->pGlueCar == NULL;"),
    M("wng-zero", "int aicarcontroller_we_need_the_glue(AICarController *c)\n{\n    // 0x00190c88.\n    (void)c;\n    return 0;",
      "int aicarcontroller_we_need_the_glue(AICarController *c)\n{\n    // 0x00190c88.\n    (void)c;\n    return 1;"),
    M("uv-div", "    float q = ee_div(1.0f, sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z));",
      "    float q = 1.0f / sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);"),
    M("uv-z", "    u->z = v->z * q;", "    u->z = v->y * q;"),
    M("ng-reason", "    nLastGlueReason = reason;\n    return 0;", "    (void)reason;\n    return 0;"),
    M("wcg-held-p", "    if (aicarcontroller_we_have_the_glue(c))\n        p = c->pGlueCar->pPlayer;\n", ""),
    M("wcg-noact", "        return no_glue(AICC_GLUE_NO_ACTION);",
      "        return no_glue(AICC_GLUE_NO_ACTION_TYPE);"),
    M("wcg-type", "    if (c->CurrentAction->Type >= AIACTION_PULL_OVER)",
      "    if (c->CurrentAction->Type > AIACTION_PULL_OVER)"),
    M("wcg-type-u", "    if (c->CurrentAction->Type >= AIACTION_PULL_OVER)",
      "    if ((uint32_t)c->CurrentAction->Type >= AIACTION_PULL_OVER)"),
    M("wcg-ratio", "#define AICC_GLUE_MIN_RATIO     0.939999998f", "#define AICC_GLUE_MIN_RATIO     0.940000057f"),
    M("wcg-ratio-le", "    if (player_get_speed_ratio(p) < AICC_GLUE_MIN_RATIO)",
      "    if (player_get_speed_ratio(p) <= AICC_GLUE_MIN_RATIO)"),
    M("wcg-dz", "    d.z = mine->State.Position.z - theirs->State.Position.z;\n    dist",
      "    d.z = 0.0f;\n    dist"),
    M("wcg-dv-abs", "    dv = fabsf(theirs->State.VelocityMagnitude\n               - mine->State.VelocityMagnitude);",
      "    dv = (theirs->State.VelocityMagnitude\n               - mine->State.VelocityMagnitude);"),
    M("wcg-dot-z", "    dot = (a.x * b.x + a.y * b.y) + a.z * b.z;", "    dot = a.x * b.x + a.y * b.y;"),
    M("wcg-on", "        if (!timer_is_valid(&c->GlueOnTimer)) {", "        if (timer_is_valid(&c->GlueOnTimer)) {"),
    M("wcg-no-time", "            nLastGlueReason = AICC_GLUE_NO_TIME;\n", ""),
    M("wcg-off-set", "            timer_set_time(&c->GlueOffTimer, AICC_GLUE_OFF_SECONDS);\n", ""),
    M("wcg-off-secs", "#define AICC_GLUE_OFF_SECONDS  20.0f", "#define AICC_GLUE_OFF_SECONDS  21.0f"),
    M("wcg-hold-range", "#define AICC_GLUE_HOLD_RANGE   60.0f", "#define AICC_GLUE_HOLD_RANGE   61.0f"),
    M("wcg-hold-range-le", "        if (AICC_GLUE_HOLD_RANGE < dist)", "        if (AICC_GLUE_HOLD_RANGE <= dist)"),
    M("wcg-hold-speed", "#define AICC_GLUE_HOLD_SPEED   10.0f", "#define AICC_GLUE_HOLD_SPEED   10.0000010f"),
    M("wcg-hold-speed-le", "        if (AICC_GLUE_HOLD_SPEED < dv)", "        if (AICC_GLUE_HOLD_SPEED <= dv)"),
    M("wcg-hold-dot", "#define AICC_GLUE_HOLD_DOT      0.5f", "#define AICC_GLUE_HOLD_DOT      0.500000060f"),
    M("wcg-hold-dot-le", "        if (dot < AICC_GLUE_HOLD_DOT)", "        if (dot <= AICC_GLUE_HOLD_DOT)"),
    M("wcg-hold-yes", "            return no_glue(AICC_GLUE_NO_HEADING);\n        return 1;",
      "            return no_glue(AICC_GLUE_NO_HEADING);\n        return 0;"),
    M("wcg-off-test", "    if (timer_is_valid(&c->GlueOffTimer))\n        return no_glue(AICC_GLUE_NO_OFF_TIME);",
      "    if (0)\n        return no_glue(AICC_GLUE_NO_OFF_TIME);"),
    M("wcg-take-range", "#define AICC_GLUE_TAKE_RANGE   30.0f", "#define AICC_GLUE_TAKE_RANGE   30.25f"),
    M("wcg-take-range-le", "    if (AICC_GLUE_TAKE_RANGE < dist)", "    if (AICC_GLUE_TAKE_RANGE <= dist)"),
    M("wcg-take-speed", "#define AICC_GLUE_TAKE_SPEED    6.0f", "#define AICC_GLUE_TAKE_SPEED    6.00000048f"),
    M("wcg-take-speed-le", "    if (AICC_GLUE_TAKE_SPEED < dv)", "    if (AICC_GLUE_TAKE_SPEED <= dv)"),
    M("wcg-take-dot", "#define AICC_GLUE_TAKE_DOT      0.699999988f", "#define AICC_GLUE_TAKE_DOT      0.700000048f"),
    M("wcg-take-dot-le", "    if (dot < AICC_GLUE_TAKE_DOT)", "    if (dot <= AICC_GLUE_TAKE_DOT)"),
    M("wcg-ahead", "    if (theirs->pRacingCar->RacePosition < mine->pRacingCar->RacePosition)",
      "    if (theirs->pRacingCar->RacePosition <= mine->pRacingCar->RacePosition)"),
    M("wcg-ahead-swap", "    if (theirs->pRacingCar->RacePosition < mine->pRacingCar->RacePosition)",
      "    if (mine->pRacingCar->RacePosition < theirs->pRacingCar->RacePosition)"),
    M("wcg-take-yes", "        return no_glue(AICC_GLUE_NO_AHEAD);\n    return 1;",
      "        return no_glue(AICC_GLUE_NO_AHEAD);\n    return 0;"),
    M("rs-action", "#define AICC_GLUE_NO_ACTION       1", "#define AICC_GLUE_NO_ACTION       11"),
    M("rs-type", "#define AICC_GLUE_NO_ACTION_TYPE  2", "#define AICC_GLUE_NO_ACTION_TYPE  11"),
    M("rs-ratio", "#define AICC_GLUE_NO_SPEED_RATIO  3", "#define AICC_GLUE_NO_SPEED_RATIO  11"),
    M("rs-range", "#define AICC_GLUE_NO_RANGE        5", "#define AICC_GLUE_NO_RANGE        11"),
    M("rs-speed", "#define AICC_GLUE_NO_SPEED        6", "#define AICC_GLUE_NO_SPEED        11"),
    M("rs-heading", "#define AICC_GLUE_NO_HEADING      7", "#define AICC_GLUE_NO_HEADING      11"),
    M("rs-time", "#define AICC_GLUE_NO_TIME         8", "#define AICC_GLUE_NO_TIME         11"),
    M("rs-off", "#define AICC_GLUE_NO_OFF_TIME     9", "#define AICC_GLUE_NO_OFF_TIME     11"),
    M("rs-ahead", "#define AICC_GLUE_NO_AHEAD       10", "#define AICC_GLUE_NO_AHEAD       11"),
    M("gon-have", "    if (aicarcontroller_we_have_the_glue(c))\n        return;\n    p->nGlueCount++;",
      "    p->nGlueCount++;"),
    M("gon-count", "    p->nGlueCount++;\n", ""),
    M("gon-timer", "    timer_set_time(&c->GlueOnTimer, AICC_GLUE_ON_SECONDS);\n", ""),
    M("gon-secs", "#define AICC_GLUE_ON_SECONDS    7.0f", "#define AICC_GLUE_ON_SECONDS    7.5f"),
    M("gon-car", "    c->pGlueCar = p->MyCar;\n", ""),
    M("gon-bias", "    c->fCurrentGlueTimeBias = AICC_GLUE_TIME_BIAS;\n", ""),
    M("gon-bias-val", "#define AICC_GLUE_TIME_BIAS     0.200000003f", "#define AICC_GLUE_TIME_BIAS     0.25f"),
    M("goff-null", "    c->pGlueCar = NULL;\n    g->pPlayer->nGlueCount--;", "    g->pPlayer->nGlueCount--;"),
    M("goff-count", "    c->pGlueCar = NULL;\n    g->pPlayer->nGlueCount--;", "    c->pGlueCar = NULL;"),
    M("goff-have", "    if (!aicarcontroller_we_have_the_glue(c))\n        return;\n    g = c->pGlueCar;",
      "    g = c->pGlueCar;"),
    M("ggs-rm", "    if (rm == NULL || rg == NULL) {", "    if (rg == NULL) {"),
    M("ggs-rg", "    if (rm == NULL || rg == NULL) {", "    if (rm == NULL) {"),
    M("ggs-gds", "        return ((DriverSpeedFn)e->fn)(vt_this(drv, e));", "        (void)e;\n        return 0.0f;"),
    M("ggs-sign", "    if (rg->RacePosition < rm->RacePosition)\n        gap = -gap;",
      "    if (rg->RacePosition <= rm->RacePosition)\n        gap = -gap;"),
    M("ggs-sign-swap", "    if (rg->RacePosition < rm->RacePosition)\n        gap = -gap;",
      "    if (rm->RacePosition < rg->RacePosition)\n        gap = -gap;"),
    M("ggs-bias", "    gap = gap - c->fCurrentGlueTimeBias * gv;", "    gap = gap + c->fCurrentGlueTimeBias * gv;"),
    M("ggs-dv", "    dv = mine->State.VelocityMagnitude - gv;", "    dv = gv - mine->State.VelocityMagnitude;"),
    M("ggs-graph", "    f = (graph_get_value(&gGlueBoostGraph, gap) + 1.0f)",
      "    f = (graph_get_value(&gGlueBoostGraph, -gap) + 1.0f)"),
    M("ggs-gain", "#define AICC_GLUE_SPEED_GAIN  (-0.0500000007f)", "#define AICC_GLUE_SPEED_GAIN  (-0.06f)"),
    M("ggs-scale", "#define AICC_GLUE_GAP_SCALE     0.00999999978f", "#define AICC_GLUE_GAP_SCALE     0.02f"),
    M("ggs-one", "                                       + 1.0f);\n    f = max_s(f, AICC_GLUE_MIN_FACTOR);",
      "                                       + 2.0f);\n    f = max_s(f, AICC_GLUE_MIN_FACTOR);"),
    M("ggs-min", "    f = max_s(f, AICC_GLUE_MIN_FACTOR);\n", ""),
    M("ggs-min-val", "#define AICC_GLUE_MIN_FACTOR    0.899999976f", "#define AICC_GLUE_MIN_FACTOR    0.95f"),
    M("ggs-max", "    return min_s(AICC_GLUE_MAX_FACTOR, f) * gv;", "    return f * gv;"),
    M("ggs-max-val", "#define AICC_GLUE_MAX_FACTOR    1.10000002f", "#define AICC_GLUE_MAX_FACTOR    1.05f"),
    M("ggs-points", "    { -20.0f, 0.100000001f }, { 20.0f, -0.100000001f }",
      "    { -20.0f, 0.100000001f }, { 21.0f, -0.100000001f }"),
    M("ggs-points-y", "    { -20.0f, 0.100000001f }, { 20.0f, -0.100000001f }",
      "    { -20.0f, 0.100000001f }, { 20.0f, -0.125f }"),
    # The boost.
    M("cdp-dist0", "    *dist = 0.0f;\n    *pos = 0.0f;\n    if (!TheRaceParameters.Boost)",
      "    *pos = 0.0f;\n    if (!TheRaceParameters.Boost)"),
    M("cdp-pos0", "    *dist = 0.0f;\n    *pos = 0.0f;\n    if (!TheRaceParameters.Boost)",
      "    *dist = 0.0f;\n    if (!TheRaceParameters.Boost)"),
    M("cdp-boost", "    if (!TheRaceParameters.Boost)\n        return;\n    laps", "    laps"),
    M("cdp-laps", "    laps = me->CurrentLapNumberExact - them->CurrentLapNumberExact;",
      "    laps = them->CurrentLapNumberExact - me->CurrentLapNumberExact;"),
    M("cdp-cop", "    if (TheRaceParameters.BeACop || (config_skip_fe() && SkipFEBeACop)) {",
      "    if ((config_skip_fe() && SkipFEBeACop)) {"),
    M("cdp-sfe", "    if (TheRaceParameters.BeACop || (config_skip_fe() && SkipFEBeACop)) {",
      "    if (TheRaceParameters.BeACop) {"),
    M("cdp-sfe-only", "    if (TheRaceParameters.BeACop || (config_skip_fe() && SkipFEBeACop)) {",
      "    if (TheRaceParameters.BeACop || SkipFEBeACop) {"),
    M("cdp-sfe-cop", "    if (TheRaceParameters.BeACop || (config_skip_fe() && SkipFEBeACop)) {",
      "    if (TheRaceParameters.BeACop || config_skip_fe()) {"),
    M("cdp-floor", "        if (x < f)\n            f -= 1.0f;\n", ""),
    M("cdp-floor-le", "        if (x < f)\n            f -= 1.0f;\n", "        if (x <= f)\n            f -= 1.0f;\n"),
    M("cdp-half", "        laps = (x - f) - 0.5f;", "        laps = x - f;"),
    M("cdp-ahead", "    ahead = TheTrackPathManager.TrackLength * laps;", "    ahead = laps;"),
    M("cdp-range", "    if (!(ahead <= di->Misc.MaxDistanceForBoost))", "    if (!(ahead < di->Misc.MaxDistanceForBoost))"),
    M("cdp-range-abs", "    if (!(ahead <= di->Misc.MaxDistanceForBoost))", "    if (!(fabsf(ahead) <= di->Misc.MaxDistanceForBoost))"),
    M("cdp-lo", "    graph_init(&lo, di->AIDistanceBoostLoSkill, AICC_DISTANCE_BOOST_POINTS);",
      "    graph_init(&lo, di->AIDistanceBoostHiSkill, AICC_DISTANCE_BOOST_POINTS);"),
    M("cdp-hi", "    graph_init(&hi, di->AIDistanceBoostHiSkill, AICC_DISTANCE_BOOST_POINTS);",
      "    graph_init(&hi, di->AIDistanceBoostLoSkill, AICC_DISTANCE_BOOST_POINTS);"),
    M("cdp-points", "#define AICC_DISTANCE_BOOST_POINTS   7", "#define AICC_DISTANCE_BOOST_POINTS   6"),
    M("cdp-lin", "    linear_init(&l, AICC_LO_SKILL, graph_get_value(&lo, ahead),",
      "    linear_init(&l, AICC_LO_SKILL, graph_get_value(&hi, ahead),"),
    M("cdp-skill", "    skill = (float)(s < 0 ? 0 : s);", "    skill = (float)s;"),
    M("cdp-lo-skill", "#define AICC_LO_SKILL                0.0f", "#define AICC_LO_SKILL                1.0f"),
    M("cdp-hi-skill", "#define AICC_HI_SKILL                9.0f", "#define AICC_HI_SKILL                8.0f"),
    M("cdp-k", "    k = (me->pCar->State.VelocityMagnitude\n         - them->pCar->State.VelocityMagnitude)",
      "    k = (them->pCar->State.VelocityMagnitude\n         - me->pCar->State.VelocityMagnitude)"),
    M("cdp-gain", "#define AICC_BOOST_SPEED_GAIN      (-0.00499999989f)", "#define AICC_BOOST_SPEED_GAIN      (-0.006f)"),
    M("cdp-scale", "#define AICC_BOOST_GAP_SCALE         0.00999999978f", "#define AICC_BOOST_GAP_SCALE         0.02f"),
    M("cdp-one", "        / (ahead * (ahead * AICC_BOOST_GAP_SCALE) + 1.0f);",
      "        / (ahead * (ahead * AICC_BOOST_GAP_SCALE) + 2.0f);"),
    M("cdp-kmin", "    k = max_s(k, -AICC_BOOST_SPEED_LIMIT);\n", ""),
    M("cdp-kmax", "    *dist = *dist + min_s(AICC_BOOST_SPEED_LIMIT, k);", "    *dist = *dist + k;"),
    M("cdp-klim", "#define AICC_BOOST_SPEED_LIMIT       0.0500000007f", "#define AICC_BOOST_SPEED_LIMIT       0.04f"),
    M("cdp-diff", "    diff = them->RacePosition - me->RacePosition;", "    diff = me->RacePosition - them->RacePosition;"),
    M("cdp-diff0", "    i = diff >= 0 ? diff + 7 : diff + 8;", "    i = diff > 0 ? diff + 7 : diff + 8;"),
    M("cdp-diff7", "    i = diff >= 0 ? diff + 7 : diff + 8;", "    i = diff + 8;"),
    M("cdp-diff8", "    i = diff >= 0 ? diff + 7 : diff + 8;", "    i = diff + 7;"),
    M("cdp-plo", "    linear_init(&l, AICC_LO_SKILL, di->AIPositionBoostLoSkill[i],",
      "    linear_init(&l, AICC_LO_SKILL, di->AIPositionBoostHiSkill[i],"),
    M("cdp-pskill", "    *pos = linear_get_value(&l, skill);", "    *pos = linear_get_value(&l, (float)s);"),
    M("ct-swap", "    if (rt->RacePosition < rl->RacePosition) {", "    if (rt->RacePosition <= rl->RacePosition) {"),
    M("ct-swap-rt", "        rl = rt;\n        trail = p;\n        rt = r;\n", "        rl = rt;\n        trail = p;\n"),
    M("ct-half", "    n = TheRaceParameters.NumAICars / 2;", "    n = (TheRaceParameters.NumAICars + 1) / 2;"),
    M("ct-rl", "    if (!(n < rl->RacePosition))\n        n++;", "    if (!(n <= rl->RacePosition))\n        n++;"),
    M("ct-rt", "    if (!(n < rt->RacePosition))\n        n++;", "    if (!(n <= rt->RacePosition))\n        n++;"),
    M("ct-rt-skip", "    if (!(n < rt->RacePosition))\n        n++;\n", ""),
    M("ct-mine", "    if (n < mine->RacePosition) {", "    if (n <= mine->RacePosition) {"),
    M("ct-target", "        *target = rt;\n        return trail;", "        *target = rl;\n        return trail;"),
    M("pr-over", "    size_t off = over ? offsetof(DifficultyInfo, PositionRatioOverOne)\n                      : offsetof(DifficultyInfo, PositionRatioUnderOne);",
      "    size_t off = over ? offsetof(DifficultyInfo, PositionRatioUnderOne)\n                      : offsetof(DifficultyInfo, PositionRatioOverOne);"),
    M("pr-place", "                                         + off + 8 * (place - 1));",
      "                                         + off + 8 * place);"),
    M("dbf-rc", "    if (rc == NULL || !c->bBoostAllowed || car->pPlayer != NULL)",
      "    if (rc == NULL || car->pPlayer != NULL)"),
    M("dbf-player", "    if (rc == NULL || !c->bBoostAllowed || car->pPlayer != NULL)",
      "    if (rc == NULL || !c->bBoostAllowed)"),
    M("dbf-allowed", "    allowed = c->CurrentAction != NULL\n              && c->CurrentAction->AllowedToUseBoost != 0;",
      "    allowed = c->CurrentAction != NULL;"),
    M("dbf-early", "#define AICC_BOOST_RACE_SECONDS     30.0f", "#define AICC_BOOST_RACE_SECONDS     30.5f"),
    M("dbf-early-le", "            < AICC_BOOST_RACE_SECONDS;", "            <= AICC_BOOST_RACE_SECONDS;"),
    M("dbf-early-u", "    early = (float)(int32_t)pCurrentRace->RaceTime.PackedTime",
      "    early = (float)pCurrentRace->RaceTime.PackedTime"),
    M("dbf-freq", "    if (!(TheDifficultyInfo.Misc.BoostCalculationFrequency\n          < (float)",
      "    if (!(TheDifficultyInfo.Misc.BoostCalculationFrequency\n          <= (float)"),
    M("dbf-freq-u", "    if (!(TheDifficultyInfo.Misc.BoostCalculationFrequency\n"
      "          < (float)(int32_t)((uint32_t)WorldTimer\n",
      "    if (!(TheDifficultyInfo.Misc.BoostCalculationFrequency\n"
      "          < (float)((uint32_t)WorldTimer\n"),
    M("dbf-lbt", "    c->LastBoostCalculationTime.PackedTime = (uint32_t)WorldTimer;\n", ""),
    M("dbf-cp-null", "    c->pCatchupPlayer = NULL;\n    if (!CarControllerDisableCatchup",
      "    if (!CarControllerDisableCatchup"),
    M("dbf-dc", "    if (!CarControllerDisableCatchup\n", "    if (1\n"),
    M("dbf-demo", "               != RCSTATE_AI_DEMO_MODE\n        && TheRaceParameters.NumPlayerCars > 0) {",
      "               != RCSTATE_RACE_IN_PROGRESS\n        && TheRaceParameters.NumPlayerCars > 0) {"),
    M("dbf-npc", "        && TheRaceParameters.NumPlayerCars > 0) {", "        && TheRaceParameters.NumPlayerCars >= 0) {"),
    M("dbf-npc1", "        && TheRaceParameters.NumPlayerCars > 0) {", "        && TheRaceParameters.NumPlayerCars > 1) {"),
    M("dbf-not-set", "        if (!allowed) {\n            car->State.BoostFactor = boost;\n            return;",
      "        if (!allowed) {\n            return;"),
    M("dbf-not", "        if (!allowed) {\n            car->State.BoostFactor = boost;\n            return;\n        }\n", ""),
    M("dbf-early-skip", "        if (!early) {", "        if (1) {"),
    M("dbf-dist1", "            float dist = 0.0f, pos = 0.0f, scale = 1.0f;",
      "            float dist = 1.0f, pos = 0.0f, scale = 1.0f;"),
    M("dbf-np1", "            if (PlayerNumPlayers == 1) {", "            if (PlayerNumPlayers <= 1) {"),
    M("dbf-np2", "            } else if (PlayerNumPlayers == 2) {", "            } else if (PlayerNumPlayers >= 2) {"),
    M("dbf-cp1", "                c->pCatchupPlayer = p;\n                scale = TheRaceParameters.BoostScale[p->PlayerNumber];\n                aicarcontroller",
      "                scale = TheRaceParameters.BoostScale[p->PlayerNumber];\n                aicarcontroller"),
    M("dbf-scale1", "                scale = TheRaceParameters.BoostScale[p->PlayerNumber];\n                aicarcontroller",
      "                scale = TheRaceParameters.BoostScale[0];\n                aicarcontroller"),
    M("dbf-args1", "                    c, rc, p->MyCar->pRacingCar, &dist, &pos);",
      "                    c, rc, p->MyCar->pRacingCar, &pos, &dist);"),
    M("dbf-me1", "                    c, rc, p->MyCar->pRacingCar, &dist, &pos);",
      "                    c, p->MyCar->pRacingCar, rc, &dist, &pos);"),
    M("dbf-args2", "                    c, rc, target, &dist, &pos);", "                    c, target, rc, &dist, &pos);"),
    M("dbf-cp2", "                c->pCatchupPlayer = p;\n                scale = TheRaceParameters.BoostScale[p->PlayerNumber];\n            }",
      "                scale = TheRaceParameters.BoostScale[p->PlayerNumber];\n            }"),
    M("dbf-scale2", "                scale = TheRaceParameters.BoostScale[p->PlayerNumber];\n            }",
      "                scale = TheRaceParameters.BoostScale[1];\n            }"),
    M("dbf-formula", "            boost = (dist + 1.0f) + pos * scale;", "            boost = (dist + 1.0f) + pos;"),
    M("dbf-formula-d", "            boost = (dist + 1.0f) + pos * scale;", "            boost = 1.0f + pos * scale;"),
    M("dbf-ratio-allowed", "    if (allowed && cp != NULL) {", "    if (cp != NULL) {"),
    M("dbf-ratio-clamp", "        s = s < 0 ? 0 : s;\n        slow =", "        slow ="),
    M("dbf-slow-idx", "        slow = TheDifficultyInfo.AISkillLevel[s].SlowFactor;",
      "        slow = TheDifficultyInfo.AISkillLevel[s + 1].SlowFactor;"),
    M("dbf-ratio-place", "            int32_t place = cp->MyCar->pRacingCar->RacePosition;",
      "            int32_t place = rc->RacePosition;"),
    M("dbf-ratio-over", "            table_init(&t, position_ratio_row(1.0f <= ratio, place), 2,",
      "            table_init(&t, position_ratio_row(1.0f < ratio, place), 2,"),
    M("dbf-ratio-n", "            table_init(&t, position_ratio_row(1.0f <= ratio, place), 2,",
      "            table_init(&t, position_ratio_row(1.0f <= ratio, place), 3,"),
    M("dbf-ratio-f", "            f = (ratio - 1.0f) * table_get_value(&t, (float)s) + 1.0f;",
      "            f = ratio * table_get_value(&t, (float)s);"),
    M("dbf-ratio-max", "            boost *= max_s(f, slow);", "            boost *= f;"),
    M("dbf-ratio-mul", "            boost *= max_s(f, slow);", "            boost = max_s(f, slow);"),
    M("dbf-set", "    }\n    car->State.BoostFactor = boost;\n}\n", "    }\n}\n"),
    M("pl-full", "    return a->nSlots == a->nSamples && f < p->fMaxSpeedRatio;",
      "    return f < p->fMaxSpeedRatio;", rel=PLAYER_H),
    M("pl-max", "    return a->nSlots == a->nSamples && f < p->fMaxSpeedRatio;",
      "    return a->nSlots == a->nSamples;", rel=PLAYER_H),
    M("pl-max-le", "    return a->nSlots == a->nSamples && f < p->fMaxSpeedRatio;",
      "    return a->nSlots == a->nSamples && f <= p->fMaxSpeedRatio;", rel=PLAYER_H),
    M("pl-ratio", "    return p->pAverageSpeedRatio->fAverage;", "    return 1.0f;", rel=PLAYER_H),
    # 11e-4's. MaybeHonkAndOrBlinkHeadlights.
    M("mh-usage", "    if ((uint32_t)(car->pCarTypeInfo->UsageType - CAR_USAGE_TYPE_COP) < 2)",
      "    if ((uint32_t)(car->pCarTypeInfo->UsageType - CAR_USAGE_TYPE_COP) < 1)"),
    M("mh-usage-signed", "    if ((uint32_t)(car->pCarTypeInfo->UsageType - CAR_USAGE_TYPE_COP) < 2)",
      "    if ((int32_t)(car->pCarTypeInfo->UsageType - CAR_USAGE_TYPE_COP) < 2)"),
    M("mh-demo", "            != RCSTATE_AI_DEMO_MODE\n        && car->TheControlMode != REAL_CONTROL)",
      "            == RCSTATE_AI_DEMO_MODE\n        && car->TheControlMode != REAL_CONTROL)"),
    M("mh-demo-or", "            != RCSTATE_AI_DEMO_MODE\n        && car->TheControlMode != REAL_CONTROL)",
      "            != RCSTATE_AI_DEMO_MODE\n        || car->TheControlMode != REAL_CONTROL)"),
    M("mh-real-mine", "            != RCSTATE_AI_DEMO_MODE\n        && car->TheControlMode != REAL_CONTROL)",
      "            != RCSTATE_AI_DEMO_MODE\n        && c->Base.pCar->TheControlMode != REAL_CONTROL)"),
    M("mh-list", "    nc = nearbycarlist_get_nearby_car(c->CurrentNearbyCarList, car);",
      "    nc = nearbycarlist_get_nearby_car(list, car);"),
    M("mh-care", "        if (!ai_do_we_care_about_this_car(nc, list))\n            return;",
      "        if (nc == NULL)\n            return;"),
    M("mh-care-list", "        if (!ai_do_we_care_about_this_car(nc, list))",
      "        if (!ai_do_we_care_about_this_car(nc, c->CurrentNearbyCarList))"),
    M("mh-traffic", "    } else if (me->TheControlMode != TRAFFIC_CONTROL) {\n        return;",
      "    } else if (me->TheControlMode != TRAFFIC_CONTROL && nc == NULL) {\n        return;"),
    M("mh-ai", "    if (me->TheControlMode == AI_CONTROL) {\n        if (!ai_do_we_care",
      "    if (me->TheControlMode == AI_CONTROL && nc == NULL) {\n        if (!ai_do_we_care"),
    M("mh-on-range", "#define AICC_HONK_ON_RANGE   0.400000006f", "#define AICC_HONK_ON_RANGE   0.5f"),
    M("mh-on-add", "#define AICC_HONK_ON_ADD     0.300000012f", "#define AICC_HONK_ON_ADD     0.3125f"),
    M("mh-on-less", "#define AICC_HONK_ON_LESS    0.200000003f", "#define AICC_HONK_ON_LESS    0.1875f"),
    M("mh-off-range", "#define AICC_HONK_OFF_RANGE  0.200000003f", "#define AICC_HONK_OFF_RANGE  0.25f"),
    M("mh-off-add", "#define AICC_HONK_OFF_ADD    0.150000006f", "#define AICC_HONK_OFF_ADD    0.15625f"),
    M("mh-off-less", "#define AICC_HONK_OFF_LESS   0.100000001f", "#define AICC_HONK_OFF_LESS   0.09375f"),
    M("mh-off-order", "    off = (world_random_f(pCurrentWorld, AICC_HONK_OFF_RANGE)\n           + AICC_HONK_OFF_ADD) - AICC_HONK_OFF_LESS;",
      "    off = world_random_f(pCurrentWorld, AICC_HONK_OFF_RANGE)\n           + (AICC_HONK_OFF_ADD - AICC_HONK_OFF_LESS);"),
    M("mh-second-range", "    second = (world_random_f(pCurrentWorld, AICC_HONK_ON_RANGE)",
      "    second = (world_random_f(pCurrentWorld, AICC_HONK_OFF_RANGE)"),
    M("mh-twice", "    two = world_random_f(pCurrentWorld, 1.0f) < AICC_HONK_TWICE;",
      "    two = world_random_f(pCurrentWorld, 1.0f) <= AICC_HONK_TWICE;"),
    M("mh-twice-val", "#define AICC_HONK_TWICE          0.5f", "#define AICC_HONK_TWICE          0.5625f"),
    M("mh-twice-range", "    two = world_random_f(pCurrentWorld, 1.0f) < AICC_HONK_TWICE;",
      "    two = world_random_f(pCurrentWorld, 2.0f) < AICC_HONK_TWICE;"),
    M("mh-passing", "    if (AICC_HONK_PASSING < nc->Velocity.y) {\n        chance = 1.0f;",
      "    if (AICC_HONK_PASSING <= nc->Velocity.y) {\n        chance = 1.0f;"),
    M("mh-passing-val", "#define AICC_HONK_PASSING        50.0f", "#define AICC_HONK_PASSING        50.5f"),
    M("mh-passing-x", "    if (AICC_HONK_PASSING < nc->Velocity.y) {\n        chance = 1.0f;",
      "    if (AICC_HONK_PASSING < nc->Velocity.x) {\n        chance = 1.0f;"),
    M("mh-passing-chance", "    if (AICC_HONK_PASSING < nc->Velocity.y) {\n        chance = 1.0f;",
      "    if (AICC_HONK_PASSING < nc->Velocity.y) {\n        chance = 0.875f;"),
    M("mh-passing-two", "        two = 1;\n        second += AICC_HONK_PASSING_SECOND;",
      "        second += AICC_HONK_PASSING_SECOND;"),
    M("mh-passing-second", "        two = 1;\n        second += AICC_HONK_PASSING_SECOND;",
      "        two = 1;"),
    M("mh-passing-second-val", "#define AICC_HONK_PASSING_SECOND 0.600000024f",
      "#define AICC_HONK_PASSING_SECOND 0.625f"),
    M("mh-traffic-type", "    } else if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR",
      "    } else if (car->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR"),
    M("mh-traffic-type-no", "    } else if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR\n               && nc",
      "    } else if (1\n               && nc"),
    M("mh-closing", "               && nc->Velocity.y < AICC_HONK_CLOSING) {",
      "               && nc->Velocity.y <= AICC_HONK_CLOSING) {"),
    M("mh-closing-val", "#define AICC_HONK_CLOSING        (-3.0f)", "#define AICC_HONK_CLOSING        (-2.5f)"),
    M("mh-closing-chance", "               && nc->Velocity.y < AICC_HONK_CLOSING) {\n        chance = 1.0f;",
      "               && nc->Velocity.y < AICC_HONK_CLOSING) {\n        chance = 0.875f;"),
    M("mh-player", "    } else if (car->pPlayer != NULL) {", "    } else if (me->pPlayer != NULL) {"),
    M("mh-player-val", "#define AICC_HONK_PLAYER         0.75f", "#define AICC_HONK_PLAYER         0.8125f"),
    M("mh-few", "        chance = list->NumCarsInArray < AICC_HONK_FEW_CARS ? AICC_HONK_FEW",
      "        chance = list->NumCarsInArray <= AICC_HONK_FEW_CARS ? AICC_HONK_FEW"),
    M("mh-few-list", "        chance = list->NumCarsInArray < AICC_HONK_FEW_CARS ? AICC_HONK_FEW",
      "        chance = c->CurrentNearbyCarList->NumCarsInArray < AICC_HONK_FEW_CARS ? AICC_HONK_FEW"),
    M("mh-few-val", "#define AICC_HONK_FEW            0.0750000030f", "#define AICC_HONK_FEW            0.0625f"),
    M("mh-many-val", "#define AICC_HONK_MANY           0.0500000007f", "#define AICC_HONK_MANY           0.0625f"),
    M("mh-honk-le", "    honk = world_random_f(pCurrentWorld, 1.0f) < chance;",
      "    honk = world_random_f(pCurrentWorld, 1.0f) <= chance;"),
    M("mh-blink-gate", "    if (honk) {\n        chance = AICC_HONK_PASSING", "    if (1) {\n        chance = AICC_HONK_PASSING"),
    M("mh-blink-passing", "        chance = AICC_HONK_PASSING < nc->Velocity.y ? AICC_BLINK_PASSING",
      "        chance = AICC_HONK_PASSING <= nc->Velocity.y ? AICC_BLINK_PASSING"),
    M("mh-blink-passing-val", "#define AICC_BLINK_PASSING       0.899999976f", "#define AICC_BLINK_PASSING       0.875f"),
    M("mh-blink-val", "#define AICC_BLINK               0.5f", "#define AICC_BLINK               0.5625f"),
    M("mh-blink-le", "        blink = world_random_f(pCurrentWorld, 1.0f) < chance;",
      "        blink = world_random_f(pCurrentWorld, 1.0f) <= chance;"),
    M("mh-args", "    car_honk_and_or_blink_headlights(c->Base.pCar, on, off, second, blink,\n                                     honk, two);",
      "    car_honk_and_or_blink_headlights(c->Base.pCar, on, off, second, honk,\n                                     blink, two);"),
    M("mh-args-dur", "    car_honk_and_or_blink_headlights(c->Base.pCar, on, off, second, blink,",
      "    car_honk_and_or_blink_headlights(c->Base.pCar, on, second, off, blink,"),
    M("mh-car", "    car_honk_and_or_blink_headlights(c->Base.pCar, on, off, second, blink,",
      "    car_honk_and_or_blink_headlights(car, on, off, second, blink,"),
    # HonkAndOrBlinkHeadlights and UpdateHeadlightsAndHorn, car.c's.
    M("ch-guard-le", "    if (cycle < elapsed) {\n        c->WantTwoHonksAndOrBlinks",
      "    if (cycle <= elapsed) {\n        c->WantTwoHonksAndOrBlinks", rel=CAR_C),
    M("ch-cycle", "                  + c->HeadlightsAndHornOffDuration\n                  + c->HeadlightsAndHornSecondOnDuration;",
      "                  + c->HeadlightsAndHornOffDuration;", rel=CAR_C),
    M("ch-cycle-on", "    float cycle = c->HeadlightsAndHornOnDuration\n                  + c->HeadlightsAndHornOffDuration",
      "    float cycle = c->HeadlightsAndHornOffDuration", rel=CAR_C),
    M("ch-store-second", "        c->HeadlightsAndHornSecondOnDuration = secondOnDuration;\n", "", rel=CAR_C),
    M("ch-store-start", "        c->HeadlightsAndHornStartTime        = WorldTimer;\n", "", rel=CAR_C),
    M("ch-store-two", "        c->WantTwoHonksAndOrBlinks           = two;\n", "", rel=CAR_C),
    M("uh-player", "    if (c->pPlayer)\n        return;\n\n    elapsed =", "    elapsed =", rel=CAR_C),
    M("uh-on-le", "    if (elapsed < on) {\n        lit = 1;", "    if (elapsed <= on) {\n        lit = 1;", rel=CAR_C),
    M("uh-gap", "        if (t < on)\n            lit = (c->WantTwoHonksAndOrBlinks == 0);",
      "        if (t < c->HeadlightsAndHornOffDuration)\n            lit = (c->WantTwoHonksAndOrBlinks == 0);", rel=CAR_C),
    M("uh-gap-le", "        if (t < on)\n            lit = (c->WantTwoHonksAndOrBlinks == 0);",
      "        if (t <= on)\n            lit = (c->WantTwoHonksAndOrBlinks == 0);", rel=CAR_C),
    M("uh-two", "            lit = (c->WantTwoHonksAndOrBlinks == 0);", "            lit = (c->WantTwoHonksAndOrBlinks != 0);", rel=CAR_C),
    M("uh-second-le", "                   < c->HeadlightsAndHornSecondOnDuration);",
      "                   <= c->HeadlightsAndHornSecondOnDuration);", rel=CAR_C),
    M("uh-second-off", "            lit = (t - c->HeadlightsAndHornOffDuration\n",
      "            lit = (t\n", rel=CAR_C),
    M("uh-force", "                         ? 1 : (c->ForceHeadlightsOn != 0);", "                         ? 1 : 0;", rel=CAR_C),
    M("uh-blink", "    c->HeadlightsState = (lit && c->WantToBlinkHeadlights)",
      "    c->HeadlightsState = (lit)", rel=CAR_C),
    M("uh-honk-lit", "    honk = lit ? (c->WantToHonkHorn != 0) : 0;", "    honk = c->WantToHonkHorn != 0;", rel=CAR_C),
    M("uh-edge-on", "    if (honk) {\n        if (((VtBoolFn)e->fn)(vt_this(d, e)))\n            return;\n",
      "    if (honk) {\n", rel=CAR_C),
    M("uh-edge-off", "        if (!((VtBoolFn)e->fn)(vt_this(d, e)))\n            return;\n", "", rel=CAR_C),
    # ExecuteCurrentAction.
    M("eca-target", "    ((DriverTargetFn)e->fn)(vt_this(d, e), &c->CurrentAction->PointsToDrive);",
      "    ((DriverTargetFn)e->fn)(vt_this(d, e), &c->Base.Driver->MyDriveTarget);"),
    M("eca-boost", "    aicarcontroller_decide_boost_factor(c);\n    l = c->CurrentDrivingLocation;",
      "    l = c->CurrentDrivingLocation;"),
    M("eca-clear", "    if (drivinglocation_is_clear(l)) {\n        // 0, 0, 0", "    if (0) {\n        // 0, 0, 0"),
    M("eca-allowed", "    float speed = 0.0f, time = 0.0f, tol = 0.0f;\n    int32_t allowed = 1;",
      "    float speed = 0.0f, time = 0.0f, tol = 0.0f;\n    int32_t allowed = 0;"),
    M("eca-easy-speed", "#define AICC_SUPER_EASY_SPEED     15.0f", "#define AICC_SUPER_EASY_SPEED     15.5f"),
    M("eca-easy-tol", "#define AICC_SUPER_EASY_TOLERANCE 10.0f", "#define AICC_SUPER_EASY_TOLERANCE 10.5f"),
    M("eca-easy-first", "    } else if (SuperEasyAI) {", "    } else if (SuperEasyAI && !BoringAIForCameraTuningOn) {"),
    M("eca-boring", "    } else if (BoringAIForCameraTuningOn) {\n        speed = line_speed_at(l->pRoutePoint, l->DrivingLine);",
      "    } else if (BoringAIForCameraTuningOn) {\n        speed = line_speed_at(l->pRoutePoint, 0);"),
    M("eca-boring-tol", "        speed = line_speed_at(l->pRoutePoint, l->DrivingLine);\n    } else if",
      "        speed = line_speed_at(l->pRoutePoint, l->DrivingLine);\n        tol = a->DesiredSpeedTolerance;\n    } else if"),
    M("eca-own-use", "    } else if (!a->UseDrivingLineSpeed) {", "    } else if (a->UseDrivingLineSpeed != 1) {"),
    M("eca-own-speed", "        speed = a->DesiredSpeed;\n        time =", "        speed = 0.0f;\n        time ="),
    M("eca-own-time", "        time = a->TimeToGetToDesiredSpeed;\n", ""),
    M("eca-own-tol", "        tol = a->DesiredSpeedTolerance;\n        allowed = a->AllowedToUseThrottleAndBrake;\n    } else {",
      "        allowed = a->AllowedToUseThrottleAndBrake;\n    } else {"),
    M("eca-own-allowed", "        allowed = a->AllowedToUseThrottleAndBrake;\n    } else {", "    } else {"),
    M("eca-line-time", "        speed = action_line_speed(c, l);\n",
      "        speed = action_line_speed(c, l);\n        time = a->TimeToGetToDesiredSpeed;\n"),
    M("eca-cop", "        if (TheRaceParameters.BeACop || (config_skip_fe() && SkipFEBeACop))",
      "        if (TheRaceParameters.BeACop)"),
    M("eca-cop-sfe", "        if (TheRaceParameters.BeACop || (config_skip_fe() && SkipFEBeACop))",
      "        if (TheRaceParameters.BeACop || (config_skip_fe() || SkipFEBeACop))"),
    M("eca-cop-skip", "        if (TheRaceParameters.BeACop || (config_skip_fe() && SkipFEBeACop))",
      "        if (TheRaceParameters.BeACop || SkipFEBeACop)"),
    M("eca-cop-val", "#define AICC_COP_SPEED            0.75f", "#define AICC_COP_SPEED            0.8125f"),
    M("eca-line-boost", "        speed *= c->Base.pCar->State.BoostFactor;\n", ""),
    M("eca-line-tol", "        speed *= c->Base.pCar->State.BoostFactor;\n        tol = a->DesiredSpeedTolerance;\n",
      "        speed *= c->Base.pCar->State.BoostFactor;\n"),
    M("eca-line-allowed", "        tol = a->DesiredSpeedTolerance;\n        allowed = a->AllowedToUseThrottleAndBrake;\n    }\n    d = c->Base.Driver;",
      "        tol = a->DesiredSpeedTolerance;\n    }\n    d = c->Base.Driver;"),
    M("eca-sds-order", "    ((DriverDesiredSpeedFn)e->fn)(vt_this(d, e), speed, time, tol, allowed);\n    aiaction_clear",
      "    ((DriverDesiredSpeedFn)e->fn)(vt_this(d, e), speed, tol, time, allowed);\n    aiaction_clear"),
    M("eca-clear-ptd", "    aiaction_clear_points_to_drive(c->CurrentAction);\n}", "}"),
    M("eca-sign", "    if (c->TakenSignpostIndex != -1) {", "    if (c->TakenSignpostIndex > 0) {"),
    M("eca-sign-line", "                                 &SignpostArray[c->TakenSignpostIndex]),\n                             l->DrivingLine);",
      "                                 &SignpostArray[c->TakenSignpostIndex]),\n                             0);"),
    M("eca-sign-factor", "                             l->DrivingLine);\n    }\n    if (timer_is_valid",
      "                             l->DrivingLine) * speed_factor(skill);\n    }\n    if (timer_is_valid"),
    M("eca-timer", "    if (timer_is_valid(&c->TakenSignpostTimer))\n        return AICC_SIGN_TIMER_SPEED;",
      "    if (c->TakenSignpostTimer.PackedTime != 0)\n        return AICC_SIGN_TIMER_SPEED;"),
    M("eca-timer-val", "#define AICC_SIGN_TIMER_SPEED     99999.0f", "#define AICC_SIGN_TIMER_SPEED     9999.0f"),
    M("eca-timer-factor", "        return AICC_SIGN_TIMER_SPEED;", "        return AICC_SIGN_TIMER_SPEED * speed_factor(skill);"),
    M("eca-skill-signed", "    if ((uint32_t)skill < 10\n", "    if (skill < 10\n"),
    M("eca-skill-9", "    if ((uint32_t)skill < 10\n", "    if ((uint32_t)skill < 9\n"),
    M("eca-freq-le", "        && TheDifficultyInfo.Misc.RoutePointChangeFrequency\n               < (float)",
      "        && TheDifficultyInfo.Misc.RoutePointChangeFrequency\n               <= (float)"),
    M("eca-freq-time", "                                  - c->LastRoutePointLookaheadSwitch.PackedTime)\n                     * AICC_TICKS_TO_SECONDS) {",
      "                                  - c->LastBoostCalculationTime.PackedTime)\n                     * AICC_TICKS_TO_SECONDS) {"),
    M("eca-freq-u", "               < (float)(int32_t)((uint32_t)WorldTimer\n                                  - c->LastRoutePoint",
      "               < (float)((uint32_t)WorldTimer\n                                  - c->LastRoutePoint"),
    M("eca-var", "        int32_t v = TheDifficultyInfo.AISkillLevel[skill].RoutePointVariance\n                    + 1;",
      "        int32_t v = TheDifficultyInfo.AISkillLevel[skill].RoutePointVariance\n                    + 2;"),
    M("eca-var-2", "            world_random_i(pCurrentWorld, 2 * v) - v;", "            world_random_i(pCurrentWorld, v) - v;"),
    M("eca-var-sub", "            world_random_i(pCurrentWorld, 2 * v) - v;", "            world_random_i(pCurrentWorld, 2 * v);"),
    M("eca-switch-time", "        c->LastRoutePointLookaheadSwitch.PackedTime = (uint32_t)WorldTimer;\n", ""),
    M("eca-la", "    i = troute_get_point_number(r, l->pRoutePoint)\n        + c->CurrentRoutePointLookahead;",
      "    i = troute_get_point_number(r, l->pRoutePoint);"),
    M("eca-clamp0", "    i = i < 0 ? 0 : i;\n", ""),
    M("eca-clamp-last", "    last = r->NumPoints - 1;", "    last = r->NumPoints - 2;"),
    M("eca-clamp-last-le", "    i = last < i ? last : i;", "    i = last <= i ? last - 1 : i;"),
    M("eca-zero", "    if (fabsf(speed) <= AICC_NO_LINE_SPEED)\n        speed = AICC_DEFAULT_LINE_SPEED;",
      "    if (0)\n        speed = AICC_DEFAULT_LINE_SPEED;"),
    M("eca-zero-val", "#define AICC_DEFAULT_LINE_SPEED   30.0f", "#define AICC_DEFAULT_LINE_SPEED   30.5f"),
    M("eca-zero-line", "    speed = line_speed_at(&r->TrackRoutePointTable[i], l->DrivingLine);",
      "    speed = line_speed_at(&r->TrackRoutePointTable[i], 0);"),
    M("eca-factor", "    return speed * speed_factor(skill);", "    return speed;"),
    M("eca-factor-clamp", "        + (ptrdiff_t)sizeof(SkillLevelEntry) * skill\n",
      "        + (ptrdiff_t)sizeof(SkillLevelEntry) * (skill < 0 ? 0 : skill)\n"),
    M("eca-factor-field", "        + offsetof(SkillLevelEntry, SpeedFactor));",
      "        + offsetof(SkillLevelEntry, SpeedFactor) + 4);"),
    # 11e-5's: Timer::CountDown, Race::CanAICarsStartDriving and Think.
    M("tcd-valid", "    if (timer_is_valid(t)) {\n        // `subu`", "    if (1) {\n        // `subu`", rel=TIMER_C),
    M("tcd-neg1", "        if ((int32_t)v < 0)\n            t->PackedTime = 0;", "        if ((int32_t)v < -1)\n            t->PackedTime = 0;", rel=TIMER_C),
    M("tcd-unsigned", "        if ((int32_t)v < 0)\n            t->PackedTime = 0;", "        if (v > 0xfffffff0u)\n            t->PackedTime = 0;", rel=TIMER_C),
    M("tcd-round", "(uint32_t)ee_trunc_w(dt * 4000.0f);", "(uint32_t)ee_trunc_w(dt * 4000.0f + 0.5f);", rel=TIMER_C),
    M("tcd-rate", "(uint32_t)ee_trunc_w(dt * 4000.0f);", "(uint32_t)ee_trunc_w(dt * 4001.0f);", rel=TIMER_C),
    M("tcd-return", "            t->PackedTime = 0;\n    }\n    return timer_is_valid(t);", "            t->PackedTime = 0;\n    }\n    return t->PackedTime != 0;", rel=TIMER_C),
    M("cas-racing", "    return s == RACE_STAGE_RACING\n", "    return s >= RACE_STAGE_RACING\n", rel=RACE_C),
    M("cas-cop-stage", "&& s >= RACE_STAGE_PRERACE);", "&& s > RACE_STAGE_PRERACE);", rel=RACE_C),
    M("cas-cop-or", "(TheRaceParameters.BeACop != 0 && s >= RACE_STAGE_PRERACE)", "(TheRaceParameters.BeACop != 0 || s >= RACE_STAGE_PRERACE)", rel=RACE_C),
    M("cas-cop-pos", "(TheRaceParameters.BeACop != 0 && s", "(TheRaceParameters.BeACop > 0 && s", rel=RACE_C),
    M("th-start", "    if (!race_can_ai_cars_start_driving(pCurrentRace)) {", "    if (0) {"),
    M("th-prerace-le", "        if (race_get_race_stage(pCurrentRace) < RACE_STAGE_PRERACE)", "        if (race_get_race_stage(pCurrentRace) <= RACE_STAGE_PRERACE)"),
    M("th-prerace-u", "        if (race_get_race_stage(pCurrentRace) < RACE_STAGE_PRERACE)", "        if ((uint32_t)race_get_race_stage(pCurrentRace) < RACE_STAGE_PRERACE)"),
    M("th-stand-allowed", "            set_desired_speed(c, 0.0f, 0.0f, 0.0f, 1);\n        else\n            brake_stand(c);", "            set_desired_speed(c, 0.0f, 0.0f, 0.0f, 0);\n        else\n            brake_stand(c);"),
    M("th-stand-straight", "            brake_stand(c);\n        aicarcontroller_steer_straight_ahead(c);\n", "            brake_stand(c);\n"),
    M("th-stand-return", "        aicarcontroller_steer_straight_ahead(c);\n        return;\n    }\n\n    a = c->CurrentAction;", "        aicarcontroller_steer_straight_ahead(c);\n    }\n\n    a = c->CurrentAction;"),
    M("bs-valid", "    if (!timer_is_valid(&c->BrakeStandTimer)) {", "    if (c->BrakeStandTimer.PackedTime == 0) {"),
    M("bs-coin", "        c->BrakeStanding = bRandomI(2, &bDefaultSeed) != 0;", "        c->BrakeStanding = 1;"),
    M("bs-coin-3", "        c->BrakeStanding = bRandomI(2, &bDefaultSeed) != 0;", "        c->BrakeStanding = bRandomI(3, &bDefaultSeed) != 0;"),
    M("bs-le", "               < (float)(int32_t)((uint32_t)WorldTimer\n                                  - c->BrakeStandTimerStart.PackedTime)", "               <= (float)(int32_t)((uint32_t)WorldTimer\n                                  - c->BrakeStandTimerStart.PackedTime)"),
    M("bs-since", "                                  - c->BrakeStandTimerStart.PackedTime)\n                     * AICC_TICKS_TO_SECONDS) {\n        c->BrakeStanding ^= 1;", "                                  - c->BrakeStandTimer.PackedTime)\n                     * AICC_TICKS_TO_SECONDS) {\n        c->BrakeStanding ^= 1;"),
    M("bs-since-u", "               < (float)(int32_t)((uint32_t)WorldTimer\n                                  - c->BrakeStandTimerStart.PackedTime)", "               < (float)((uint32_t)WorldTimer\n                                  - c->BrakeStandTimerStart.PackedTime)"),
    M("bs-toggle", "        c->BrakeStanding ^= 1;", "        c->BrakeStanding = !c->BrakeStanding;"),
    M("bs-toggle-none", "        c->BrakeStanding ^= 1;\n", ""),
    M("bs-phase", "        if (c->BrakeStanding) {\n            f = bRandomF(AICC_BRAKE_STAND_RANGE", "        if (!c->BrakeStanding) {\n            f = bRandomF(AICC_BRAKE_STAND_RANGE"),
    M("bs-range", "#define AICC_BRAKE_STAND_RANGE   0.25f", "#define AICC_BRAKE_STAND_RANGE   0.375f"),
    M("bs-add", "#define AICC_BRAKE_STAND_ADD     0.349999994f", "#define AICC_BRAKE_STAND_ADD     0.375f"),
    M("bs-roll-range", "#define AICC_ROLL_RANGE          1.0f", "#define AICC_ROLL_RANGE          1.25f"),
    M("bs-roll-add", "#define AICC_ROLL_ADD            1.5f", "#define AICC_ROLL_ADD            1.625f"),
    M("bs-set", "        timer_set_time(&c->BrakeStandTimer, f + add);\n", "        timer_set_time(&c->BrakeStandTimer, f);\n"),
    M("bs-start", "        timer_set_time(&c->BrakeStandTimerStart,\n                       (float)WorldTimer * AICC_TICKS_TO_SECONDS);\n", ""),
    M("bs-speed", "#define AICC_BRAKE_STAND_SPEED   100.0f", "#define AICC_BRAKE_STAND_SPEED   99.0f"),
    M("bs-speed-phase", "    set_desired_speed(c, c->BrakeStanding ? AICC_BRAKE_STAND_SPEED : 0.0f,", "    set_desired_speed(c, c->BrakeStanding ? 0.0f : AICC_BRAKE_STAND_SPEED,"),
    M("bs-allowed", "                      0.0f, 0.0f, 1);\n}\n\n// Whether this frame", "                      0.0f, 0.0f, 0);\n}\n\n// Whether this frame"),
    M("pg-act", "    if (a != NULL && a->Type != AIACTION_PULL_OVER\n", "    if ((a == NULL || a->Type != AIACTION_PULL_OVER)\n"),
    M("pg-type", "    if (a != NULL && a->Type != AIACTION_PULL_OVER\n", "    if (a != NULL\n"),
    M("pg-valid", "        && timer_is_valid(&c->ProgressTimer)\n", ""),
    M("pg-count", "        && !timer_count_down(&c->ProgressTimer, dt)) {", "        && timer_count_down(&c->ProgressTimer, dt)) {"),
    M("pg-secs", "        timer_set_time(&c->ProgressTimer, AICC_PROGRESS_SECONDS);\n        average_record", "        timer_set_time(&c->ProgressTimer, 1.75f);\n        average_record"),
    M("pg-abs", "                           * fabsf(car->pRacingCar->dCurrentLapNumberExact));", "                           * car->pRacingCar->dCurrentLapNumberExact);"),
    M("pg-len", "                       TheTrackPathManager.TrackLength\n                           * fabsf(", "                       1.0f\n                           * fabsf("),
    M("pg-near-le", "               < AICC_PROGRESS_PLAYER_RANGE;", "               <= AICC_PROGRESS_PLAYER_RANGE;"),
    M("pg-range", "#define AICC_PROGRESS_PLAYER_RANGE  50.0f", "#define AICC_PROGRESS_PLAYER_RANGE  50.5f"),
    M("pg-blink", "        if (!car_is_blinking(car)\n", "        if (1\n"),
    M("pg-full", "            && c->pProgress->nSamples == c->pProgress->nSlots\n", "            && c->pProgress->nSamples + 1 >= c->pProgress->nSlots\n"),
    M("pg-full-none", "            && c->pProgress->nSamples == c->pProgress->nSlots\n", ""),
    M("pg-min-le", "            && c->pProgress->fAverage < AICC_PROGRESS_MIN && !near)", "            && c->pProgress->fAverage <= AICC_PROGRESS_MIN && !near)"),
    M("pg-min", "#define AICC_PROGRESS_MIN           0.200000003f", "#define AICC_PROGRESS_MIN           0.25f"),
    M("pg-near", "            && c->pProgress->fAverage < AICC_PROGRESS_MIN && !near)", "            && c->pProgress->fAverage < AICC_PROGRESS_MIN)"),
    M("pg-reset", "            car_please_reset_me_later(car);\n    }\n\n    if (timer_is_valid(&c->RealPhysicsTimer)", "            ;\n    }\n\n    if (timer_is_valid(&c->RealPhysicsTimer)"),
    M("rp-valid", "    if (timer_is_valid(&c->RealPhysicsTimer)\n        && !timer_count_down", "    if (!timer_count_down"),
    M("rp-wheels", "        if (car->State.nWheelsTouchingGround < 4)", "        if (car->State.nWheelsTouchingGround < 3)"),
    M("rp-again", "#define AICC_REAL_PHYSICS_AGAIN_SECONDS 1.0f", "#define AICC_REAL_PHYSICS_AGAIN_SECONDS 1.25f"),
    M("rp-mode", "            car_set_movement_mode(car, nDefaultMovementMode);\n    }\n    if (timer_is_valid(&c->OffBeltTimer)) {", "            car_set_movement_mode(car, PHYSICS_MOVEMENT);\n    }\n    if (timer_is_valid(&c->OffBeltTimer)) {"),
    M("ob-valid", "    if (timer_is_valid(&c->OffBeltTimer)) {", "    if (1) {"),
    M("ob-mode", "        if (car->TheMovementMode == BELT_MOVEMENT)\n            car_set_movement_mode(car, nDefaultMovementMode);\n        timer_count_down", "        if (1)\n            car_set_movement_mode(car, nDefaultMovementMode);\n        timer_count_down"),
    M("ob-count", "        timer_count_down(&c->OffBeltTimer, dt);\n", ""),
    M("glue-on-count", "    timer_count_down(&c->GlueOnTimer, dt);\n", ""),
    M("glue-off-count", "    timer_count_down(&c->GlueOffTimer, dt);\n", ""),
    M("tt-count", "    timer_count_down(&c->TakenSignpostTimer, dt);\n", ""),
    M("rtp-cam", "    if (CameraFollowThisCarInstead == car->DriverNumber\n        && ResetThisCarsPosition) {", "    if (ResetThisCarsPosition) {"),
    M("rtp-switch", "    if (CameraFollowThisCarInstead == car->DriverNumber\n        && ResetThisCarsPosition) {", "    if (CameraFollowThisCarInstead == car->DriverNumber) {"),
    M("rtp-clear", "        ResetThisCarsPosition = 0;\n", ""),
    M("rtp-x", "#define AICC_RESET_X              (-890.0f)", "#define AICC_RESET_X              (-889.0f)"),
    M("rtp-y", "#define AICC_RESET_Y              (-332.0f)", "#define AICC_RESET_Y              (-331.0f)"),
    M("rtp-z", "#define AICC_RESET_Z              (-78.0f)", "#define AICC_RESET_Z              (-77.0f)"),
    M("rtp-angle", "        car_debug_set_position(car, &p, 0.0f, ThisCarsResetAngle);", "        car_debug_set_position(car, &p, 0.0f, 0xc000);"),
    M("rtp-speed", "        car_debug_set_position(car, &p, 0.0f, ThisCarsResetAngle);", "        car_debug_set_position(car, &p, 1.0f, ThisCarsResetAngle);"),
    M("th-secs-sub", "    c->SecondsBeforeNextActionEvaluation -= dt;\n", ""),
    M("th-start-n", "    list->NumCarsInArray = 0;\n    list->MyHalfSizeL = 0.0f;\n    list->MyHalfSizeD = 0.0f;\n    if (!my_turn", "    list->MyHalfSizeL = 0.0f;\n    list->MyHalfSizeD = 0.0f;\n    if (!my_turn"),
    M("th-start-hl", "    list->NumCarsInArray = 0;\n    list->MyHalfSizeL = 0.0f;\n    list->MyHalfSizeD = 0.0f;\n    if (!my_turn", "    list->NumCarsInArray = 0;\n    list->MyHalfSizeD = 0.0f;\n    if (!my_turn"),
    M("th-start-hd", "    list->NumCarsInArray = 0;\n    list->MyHalfSizeL = 0.0f;\n    list->MyHalfSizeD = 0.0f;\n    if (!my_turn", "    list->NumCarsInArray = 0;\n    list->MyHalfSizeL = 0.0f;\n    if (!my_turn"),
    M("turn-8", "#define AICC_RACER_TURNS   8", "#define AICC_RACER_TURNS   7"),
    M("turn-6", "#define AICC_TRAFFIC_TURNS 6", "#define AICC_TRAFFIC_TURNS 5"),
    M("turn-racer-u", "        m = WorldLoopCounter % AICC_RACER_TURNS;", "        m = (int32_t)((uint32_t)WorldLoopCounter % AICC_RACER_TURNS);"),
    M("turn-traffic-u", "        m = WorldLoopCounter % AICC_TRAFFIC_TURNS;", "        m = (int32_t)((uint32_t)WorldLoopCounter % AICC_TRAFFIC_TURNS);"),
    M("turn-racer-le", "        return m < w->CopCarPos - w->AICarPos\n", "        return m <= w->CopCarPos - w->AICarPos\n"),
    M("turn-racer-table", "            && w->CarTable[w->AICarPos + m] == car;", "            && w->CarTable[w->AICarPos + m] != NULL;"),
    M("turn-racer-count", "        return m < w->CopCarPos - w->AICarPos\n", "        return m < w->TotalNumCars - w->AICarPos\n"),
    M("turn-traffic-le", "        return m < w->TotalNumCars - w->TrafficCarPos\n", "        return m <= w->TotalNumCars - w->TrafficCarPos\n"),
    M("turn-traffic-table", "            && w->CarTable[w->TrafficCarPos + m] == car;", "            && w->CarTable[w->TrafficCarPos + m] != NULL;"),
    M("turn-traffic-count", "        return m < w->TotalNumCars - w->TrafficCarPos\n", "        return m < w->CopCarPos - w->TrafficCarPos\n"),
    M("turn-secs-lt", "        return c->SecondsBeforeNextActionEvaluation <= 0.0f;", "        return c->SecondsBeforeNextActionEvaluation < 0.0f;"),
    M("turn-racer-type", "    case DRIVER_TYPE_AI_RACER:\n        m = WorldLoopCounter", "    case DRIVER_TYPE_COP:\n        m = WorldLoopCounter"),
    M("turn-act", "    if (!my_turn(c, car) && c->CurrentAction != NULL) {", "    if (!my_turn(c, car)) {"),
    M("th-interval", "#define AICC_THINK_INTERVAL         0.100000001f", "#define AICC_THINK_INTERVAL         0.125f"),
    M("th-secs-add", "    c->SecondsBeforeNextActionEvaluation += AICC_THINK_INTERVAL;\n", ""),
    M("th-sticky", "    aicarcontroller_do_sticky_decisions(c);\n    nearbycarlist_build_array", "    nearbycarlist_build_array"),
    M("th-build", "    nearbycarlist_build_array(c->CurrentNearbyCarList,\n                              c->CurrentDrivingLocation, list_look_ahead());\n    aicarcontroller_get_current_track_route_point", "    aicarcontroller_get_current_track_route_point"),
    M("th-gct", "    aicarcontroller_get_current_track_route_point(c, NULL);\n", ""),
    M("th-clear-straight", "    if (drivinglocation_is_clear(c->CurrentDrivingLocation)) {\n        aicarcontroller_steer_straight_ahead(c);\n", "    if (drivinglocation_is_clear(c->CurrentDrivingLocation)) {\n"),
    M("th-clear-allowed", "        aicarcontroller_steer_straight_ahead(c);\n        set_desired_speed(c, 0.0f, 0.0f, 0.0f, 1);\n        return;", "        aicarcontroller_steer_straight_ahead(c);\n        set_desired_speed(c, 0.0f, 0.0f, 0.0f, 0);\n        return;"),
    M("th-clear-return", "        set_desired_speed(c, 0.0f, 0.0f, 0.0f, 1);\n        return;\n    }\n    think_action(c);", "        set_desired_speed(c, 0.0f, 0.0f, 0.0f, 1);\n        list->NumCarsInArray = 0;\n        return;\n    }\n    think_action(c);"),
    M("ta-boring", "    if (BoringAIForCameraTuningOn) {", "    if (0) {"),
    M("ta-boring-type", "        } else if (a->Type == AIACTION_JUST_DRIVE) {", "        } else if (a->Type == AIACTION_PULL_OVER) {"),
    M("ta-boring-calc", "            action_calculate_points(a, info);\n        } else {", "            ;\n        } else {"),
    M("ta-boring-del", "            delete_action(a);\n            c->CurrentAction = NULL;\n            choose_new_action(c, &c->CurrentAction, AIACTION_JUST_DRIVE);", "            c->CurrentAction = NULL;\n            choose_new_action(c, &c->CurrentAction, AIACTION_JUST_DRIVE);"),
    M("ta-boring-choose", "            choose_new_action(c, &c->CurrentAction, AIACTION_JUST_DRIVE);", "            choose_new_action(c, &c->CurrentAction, AIACTION_NONE);"),
    M("ta-boring-return", "        }\n        return;\n    }\n    if (a == NULL) {", "        }\n    } else\n    if (a == NULL) {"),
    M("ta-null-jd", "    if (a == NULL) {\n        c->CurrentAction = new_just_drive();\n    } else {", "    if (a == NULL) {\n        choose_new_action(c, &c->CurrentAction, AIACTION_JUST_DRIVE);\n    } else {"),
    M("ta-update", "        aiaction_update_status(a, info);\n", ""),
    M("ta-done-exp", "    return a == NULL || aiplan_success(&a->Base) || aiplan_failure(&a->Base)\n        || aiplan_is_expired(&a->Base);", "    return a == NULL || aiplan_success(&a->Base) || aiplan_failure(&a->Base);"),
    M("ta-done-fail", "    return a == NULL || aiplan_success(&a->Base) || aiplan_failure(&a->Base)\n", "    return a == NULL || aiplan_success(&a->Base)\n"),
    M("ta-done-succ", "    return a == NULL || aiplan_success(&a->Base) || aiplan_failure(&a->Base)\n", "    return a == NULL || aiplan_failure(&a->Base)\n"),
    M("ta-done-exp-status", "        || aiplan_is_expired(&a->Base);", "        || a->Base.Status == STATUS_EXPIRED;"),
    M("ta-done-del", "            if (a != NULL)\n                delete_action(a);\n", ""),
    M("ta-done-type", "            choose_new_action(c, &next, AIACTION_NONE);", "            choose_new_action(c, &next, AIACTION_DRAFT);"),
    M("ta-int", "            if (n != NULL) {\n                if (c->CurrentAction != NULL)\n                    delete_action(c->CurrentAction);\n", "            if (n != NULL) {\n"),
    M("ta-int-set", "                c->CurrentAction = n;\n", "                delete_action(n);\n"),
    M("ta-int-none", "            AIAction *n = aicarcontroller_interrupt_action(c);", "            AIAction *n = NULL;"),
    M("ta-gen", "    generate_points(c, c->CurrentAction);\n}", "}"),
    M("jd-arg", "                           AIActionJustDriveScore, -1.0f)->Base;", "                           AIActionJustDriveScore, 1.0f)->Base;"),
    M("jd-score", "                           AIActionJustDriveScore, -1.0f)->Base;", "                           AIActionJustDriveScore + 1, -1.0f)->Base;"),
    M("th-exec", "    think_action(c);\n    aicarcontroller_execute_current_action(c);\n", "    think_action(c);\n"),
    M("belt-need", "    if (aicarcontroller_we_need_the_belt(c)\n        && aicarcontroller_we_can_have_the_belt(c)) {", "    if (aicarcontroller_we_can_have_the_belt(c)) {"),
    M("belt-can", "    if (aicarcontroller_we_need_the_belt(c)\n        && aicarcontroller_we_can_have_the_belt(c)) {", "    if (aicarcontroller_we_need_the_belt(c)) {"),
    M("belt-mode", "        if (c->Base.pCar->TheMovementMode != BELT_MOVEMENT)\n            car_set_movement_mode(c->Base.pCar, BELT_MOVEMENT);", "        car_set_movement_mode(c->Base.pCar, BELT_MOVEMENT);"),
    M("belt-set", "        set_belt(c->Base.pCar->pCarMover);\n", ""),
    M("belt-off", "    } else if (c->Base.pCar->TheMovementMode == BELT_MOVEMENT) {", "    } else {"),
    M("belt-off-mode", "        car_set_movement_mode(c->Base.pCar, nDefaultMovementMode);\n    }\n    render_target(c);", "        car_set_movement_mode(c->Base.pCar, PHYSICS_MOVEMENT);\n    }\n    render_target(c);"),
    M("rt-cam", "    if (aicarcontroller_get_my_driver_number(c) == CameraFollowThisCarInstead)", "    if (aicarcontroller_get_my_driver_number(c) != CameraFollowThisCarInstead)"),
    M("rt-end", "    render_target(c);\n    list = c->CurrentNearbyCarList;", "    list = c->CurrentNearbyCarList;"),
    M("th-end-n", "    list->MyHalfSizeD = 0.0f;\n    list->NumCarsInArray = 0;\n    list->MyHalfSizeL = 0.0f;\n}", "    list->MyHalfSizeD = 0.0f;\n    list->MyHalfSizeL = 0.0f;\n}"),
    M("th-end-hl", "    list->MyHalfSizeD = 0.0f;\n    list->NumCarsInArray = 0;\n    list->MyHalfSizeL = 0.0f;\n}", "    list->MyHalfSizeD = 0.0f;\n    list->NumCarsInArray = 0;\n}"),
    M("th-end-hd", "    list->MyHalfSizeD = 0.0f;\n    list->NumCarsInArray = 0;\n    list->MyHalfSizeL = 0.0f;\n}", "    list->NumCarsInArray = 0;\n    list->MyHalfSizeL = 0.0f;\n}"),
    M("bt-side", "    if (!drivingchoice_type_is_side_of_car(c->CurrentDrivingChoice->Type)\n        || c->CurrentDrivingChoice->pCar->pPlayer == NULL)", "    if (c->CurrentDrivingChoice->pCar == NULL\n        || c->CurrentDrivingChoice->pCar->pPlayer == NULL)"),
    M("bt-player", "        || c->CurrentDrivingChoice->pCar->pPlayer == NULL)\n        return;", "        || c->CurrentDrivingChoice->pCar == NULL)\n        return;"),
    M("bt-build", "                              c->CurrentDrivingLocation, list_look_ahead());\n    if (nearbycarlist_get_nearby_car", "                              c->CurrentDrivingLocation, list_look_ahead());\n    c->CurrentNearbyCarList->NumCarsInArray = 0;\n    if (nearbycarlist_get_nearby_car"),
    M("bt-extra", "                                         c->CurrentNearbyCarList, 0.0f, 0.0f,", "                                         c->CurrentNearbyCarList, 1.0f, 0.0f,"),
    M("bt-move", "                                         MOVEMENT_TOWARDS_LINE);", "                                         MOVEMENT_TOWARDS_LINE + 1);"),
    M("bt-target", "        ((DriverTargetFn)e->fn)(vt_this(d, e), &t);\n        render_target(c);", "        render_target(c);"),
    M("bt-render", "        ((DriverTargetFn)e->fn)(vt_this(d, e), &t);\n        render_target(c);", "        ((DriverTargetFn)e->fn)(vt_this(d, e), &t);"),
]

EQUIVALENT = {
    "sr-relax":
        "GetNewDrivingLine's relaxed switch reaches only its own location, "
        "which IsDriveable hands to BuildDriveTarget: a valid line choice "
        "is built from a copy set to its line with no switch, and an "
        "invalid one, the only target built from the location as it is, "
        "makes IsDriveable answer 0 whatever it holds (s_relax shows it).",
    "gl-relax":
        "As sr-relax: the switch on the location's line never reaches a "
        "target IsDriveable reads.",
    "gl-relax0":
        "SetRoute's switch is overwritten by SetDrivingLine's on every pass "
        "before IsDriveable reads the location, and with no pass the "
        "location is not read at all.",
    "gl-list":
        "The constructor points CurrentNearbyCarList at the controller's "
        "own list and nothing in 11e-1 moves it.",
    "gp-ahead":
        "GetCarAhead only reads; retail calls it and drops the answer.",
    "dsd-clamp":
        "max(100, min(a, 250)) and min(250, max(a, 100)) agree for every "
        "a but a NaN, which the EE does not have (retail's look-ahead for a "
        "NaN speed is 250).",
    "dsd-max-args":
        "max.s's two orders differ only for a NaN, which the EE does not "
        "have.",
    "sp-relaxed":
        "As gl-relax: GetNewDrivingLine's relaxed flag reaches only its own "
        "location, never a target IsDriveable reads.",
    "sp-again-relaxed":
        "As sp-relaxed, for the second GetNewDrivingLine.",
    "wcb-race-le":
        "The race clock is whole ticks, and no whole tick count times "
        "0.000250000012f rounds to 30 exactly: 120000 ticks is 30.000002, "
        "119999 is 29.99975, so < and <= agree.",
    "dbf-early-le":
        "As wcb-race-le, for DecideBoostFactor's own 30 s.",
    "dbf-ratio-allowed":
        "pCatchupPlayer is cleared before the catchup and set only past its "
        "!allowed return, so a catchup player means the action allows the "
        "boost.",
    "dbf-ratio-over":
        "At a speed ratio of exactly 1 the row's value is multiplied by "
        "ratio - 1, 0, and the rows hold finite values, so either row gives "
        "1.",
    "bt-extra":
        "BuildDriveTarget never reads its two floats; IsDriveable's caller "
        "passes them on unread too.",
    "bt-move":
        "Between thinks the target is built only once GetNearbyCar has found "
        "the choice's car, so IsValid passes and a side-of-car choice goes to "
        "BuildDriveTargetAroundCar, which fills up parallel to the line "
        "whatever the movement.",
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
        todo, SOURCES, "aicarcontroller_test",
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
