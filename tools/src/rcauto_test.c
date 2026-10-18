// Drives rcauto.c for tools/rcauto_check.py. A script of ops, one per
// line, fields split on '|'; T is 1 for RC and 2 for RC2, a car C is 0 for
// NULL, 1 for C0 and 2 for C1, and floats are their bits in hex:
//
//   car|K|X|Y|Z|W        car K's (0, 1) State.Position
//   prc|T                pRaceCoordinator
//   players|N            PlayerNumPlayers
//   ans|TAKE|AUTO|IR|PRESENT  what TakeSnapshot answers (1 a snapshot, 0
//                        NULL), and RestoreSnapshot by each name
//   rp|ON                what Car::GetRoutePoint answers: TP, or NULL
//   route|N|RET          the route constructor: N points from PTS and
//                        itself, or (RET 0) NULL and nothing written
//   width|K|L|R          route point K's LeftWidth and RightWidth
//   tpcs|R|D|...         what the next TrackPathCoordinates find, in turn:
//                        RatioAroundTrack and DistanceAroundTrack; then 0
//   loops|END|WORLD      EndCapturingLoopCount and WorldLoopCounter
//   dir|D                TheRaceParameters' TrackDirection
//   old|T|M|CD|FOV|ROUTE|BANK|EYE  the fields set to the old objects (1)
//                        or NULL (0); each old object set is made afresh
//   oroute|N             OROUTE's point count
//   ocd|H                OCD's EnterHorizComp
//   rewinds|T|N          mNumRewinds
//   hl|T|C1|C2|VIEW      the highlight cars and the view
//   msg|MSG|PARAM        the state's callback, on RC
//   setup|C1|C2|VIEW     SetUpAutoReplay on RC (C1 never NULL)
//   cleanup|T  check|T  setupcam|T   the methods
//   dump                 both coordinators' fields
//   tag|TEXT             nothing: a heading in the transcript
//
// Every call out of rcauto.c prints what it was asked, as the model's
// stubs at retail's addresses do. A call that would read through NULL --
// a rewind with no route, record or arrays, the camera set up with no
// route -- prints "unsafe" or "no route" instead, on both sides.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "cammover.h"
#include "car.h"
#include "player.h"
#include "playercam.h"
#include "previewroute.h"
#include "race.h"
#include "racecoord.h"
#include "rcauto.h"
#include "rcpost.h"
#include "rcstates.h"
#include "realtime.h"
#include "replay.h"
#include "replaymgr.h"
#include "trackcarcam.h"
#include "trackflow.h"
#include "trackpath.h"
#include "trackroute.h"

#define NUM_PTS     16
#define MAX_BLOCKS  60000
#define MAX_TPCS    8
#define SLACK       512
#define DUMP_VERTS  12

// ------------------------------------------------------- the globals

RaceCoordinator *pRaceCoordinator;
ReplayManager *pReplayManager;
int32_t PlayerNumPlayers;
struct Player *PlayerPlayersByIndex[2];
int32_t WorldLoopCounter;
RaceParameters TheRaceParameters;
void (*gSetFlailerScreenVisibilityFn)(uint32_t screen, int visibility);
void (*gRestoreTypeChangedHandlersFn)(void);

static RaceCoordinator rcMem, rc2Mem;
static ReplayManager rmMem;
static struct Player players[2];
static struct Car cars[2];
static ReplaySnapshot snap;
static TrackRoutePoint tp;
static PreviewRoutePoint pts[NUM_PTS];
static TrackRoutePoint trp[NUM_PTS];
static TrackCarCameraMover om;
static CameraDataItems ocd;
static bVector3 ofov[64];
static PreviewRoute oroute;
static bVector3 obank[48], oeye[48];
static int32_t orouteN;

static void *blocks[MAX_BLOCKS];
static int numBlocks;

static int ansTake, ansAuto, ansIR, ansPresent;
static int rpOn;
static int routeN, routeRet;
static uint32_t tpcs[MAX_TPCS][2];
static int numTpcs, nextTpc;

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, sizeof u);
    return u;
}

static float flt(uint32_t u)
{
    float f;

    memcpy(&f, &u, sizeof f);
    return f;
}

static int block_of(const void *p)
{
    int i;

    for (i = 0; i < numBlocks; i++)
        if (blocks[i] == p)
            return i;
    return -1;
}

static const char *label(const void *p)
{
    static char buf[8][32];
    static int k;
    char *b = buf[k++ & 7];
    int i;

    if (p == NULL)
        return "NULL";
    if (p == &rcMem)
        return "RC";
    if (p == &rc2Mem)
        return "RC2";
    if (p == &rmMem)
        return "RM";
    if (p == &tp)
        return "TP";
    if (p == pts)
        return "PTS";
    if (p == &om)
        return "OM";
    if (p == &ocd)
        return "OCD";
    if (p == ofov)
        return "OFOV";
    if (p == &oroute)
        return "OROUTE";
    if (p == obank)
        return "OBANK";
    if (p == oeye)
        return "OEYE";
    if (p == &snap)
        return "S0";
    for (i = 0; i < 2; i++) {
        if (p == &players[i]) {
            snprintf(b, 32, "P%d", i);
            return b;
        }
        if (p == &cars[i]) {
            snprintf(b, 32, "C%d", i);
            return b;
        }
    }
    i = block_of(p);
    if (i >= 0) {
        snprintf(b, 32, "B%d", i);
        return b;
    }
    snprintf(b, 32, "%d", (int)(int32_t)(intptr_t)p);
    return b;
}

// A block or an old object: memory a dump may read.
static int known(const void *p)
{
    return p != NULL && (block_of(p) >= 0 || p == ofov || p == obank
                         || p == oeye);
}

static RaceCoordinator *coord(int t)
{
    return t == 2 ? &rc2Mem : &rcMem;
}

static struct Car *car_arg(int c)
{
    return c == 1 ? &cars[0] : c == 2 ? &cars[1] : NULL;
}

static void print_verts(const char *what, const bVector3 *v, int n)
{
    int i;

    printf("  %s", what);
    for (i = 0; i < n; i++)
        printf(" %08x,%08x,%08x", (unsigned)bits(v[i].x),
               (unsigned)bits(v[i].y), (unsigned)bits(v[i].z));
    printf("\n");
}

static int clamp16(int32_t n)
{
    return n < 0 ? 0 : n > 16 ? 16 : (int)n;
}

// ------------------------------------------------------- the stubs

void *bMalloc(int size, const char *name, int flags, int pool)
{
    uint8_t *p = malloc((size_t)size + SLACK);

    if (p == NULL || numBlocks >= MAX_BLOCKS) {
        fprintf(stderr, "out of blocks\n");
        exit(3);
    }
    memset(p, 0x3c, (size_t)size + SLACK);
    blocks[numBlocks++] = p;
    printf("  malloc %d %s %d %d -> %s\n", size, name, flags, pool,
           label(p));
    return p;
}

void bFree(void *p)
{
    printf("  free %s\n", label(p));
}

ReplaySnapshot *replaymgr_take_snapshot(ReplayManager *rm, const char *name)
{
    printf("  take %s %s\n", label(rm), name);
    return ansTake ? &snap : NULL;
}

int32_t replaymgr_restore_snapshot_named(ReplayManager *rm, const char *name)
{
    printf("  restore %s %s\n", label(rm), name);
    if (strcmp(name, "AUTO_REPLAY_SNAPSHOT") == 0)
        return ansAuto;
    if (strcmp(name, "INSTANT_REPLAY") == 0)
        return ansIR;
    if (strcmp(name, "THE_PRESENT") == 0)
        return ansPresent;
    return 0;
}

int32_t replaymgr_delete_snapshot_named(ReplayManager *rm, const char *name)
{
    printf("  delete %s %s\n", label(rm), name);
    return 0;
}

void racecoordinator_change_state(RaceCoordinator *rc, RCState state)
{
    printf("  change %s %d\n", label(rc), (int)state);
}

void racecoordinator_send_message(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param)
{
    printf("  send %s %d %d\n", label(rc), (int)msg, (int)param);
}

static void screen_visibility(uint32_t screen, int visibility)
{
    printf("  screen %08x %d\n", (unsigned)screen, visibility);
}

void player_disable_camera_movers(struct Player *p)
{
    printf("  disable %s\n", label(p));
}

void player_enable_camera_movers(struct Player *p)
{
    printf("  enable %s\n", label(p));
}

static void type_handlers(void)
{
    printf("  type handlers\n");
}

TrackRoutePoint *car_get_route_point(Car *c, int find)
{
    printf("  route point %s %d\n", label(c), find);
    return rpOn ? &tp : NULL;
}

PreviewRoute *preview_route_init(PreviewRoute *pr, struct Car *car,
                                 float radius, float length)
{
    printf("  route ctor %s %s %08x %08x\n", label(pr), label(car),
           (unsigned)bits(radius), (unsigned)bits(length));
    if (!routeRet)
        return NULL;
    pr->pPoints = pts;
    pr->nPoints = routeN;
    return pr;
}

void preview_route_destroy(PreviewRoute *pr, int32_t flags)
{
    printf("  route dtor %s %d\n", label(pr), (int)flags);
}

void preview_route_point_get_position_at(const PreviewRoutePoint *pt,
                                         bVector3 *o, float along,
                                         float across)
{
    int k = (int)(pt - pts);

    if (k < 0 || k >= NUM_PTS) {
        printf("  pos ? %08x %08x\n", (unsigned)bits(along),
               (unsigned)bits(across));
        return;
    }
    printf("  pos %d %08x %08x\n", k, (unsigned)bits(along),
           (unsigned)bits(across));
    o->x = 10.0f * (float)k + 1.0f;
    o->y = -3.0f * (float)k + 2.0f;
    o->z = 0.25f * (float)k + 3.0f;
    o->pad = (float)k + 0.5f;
}

void trackpath_coord_init_at(TrackPathCoordinate *c, const bVector2 *pos)
{
    uint32_t x = bits(pos->x);

    if (x == (uint32_t)(uintptr_t)&tp)
        printf("  tpc TP %08x\n", (unsigned)bits(pos->y));
    else
        printf("  tpc %08x %08x\n", (unsigned)x, (unsigned)bits(pos->y));
    if (nextTpc < numTpcs) {
        c->RatioAroundTrack = flt(tpcs[nextTpc][0]);
        c->DistanceAroundTrack = flt(tpcs[nextTpc][1]);
        nextTpc++;
    } else {
        c->RatioAroundTrack = 0.0f;
        c->DistanceAroundTrack = 0.0f;
    }
}

static void mover_destroy(CameraMover *m)
{
    printf("  mover dtor %s\n", label(m));
}

static const CameraMoverVtbl moverVtbl = { .Destroy = mover_destroy };

static void print_cd(const CameraDataItems *cd)
{
    printf("  cd %d %s %d %08x %08x %08x %08x %08x %d %d %08x %08x %08x"
           " %08x %d %s %d %s %d %s %d %s %s %d %s\n",
           (int)cd->Type, label(cd->Name), (int)cd->IsFOVIso,
           (unsigned)bits(cd->MinPercent), (unsigned)bits(cd->MaxPercent),
           (unsigned)bits(cd->EyeSplineSpeed),
           (unsigned)bits(cd->LookSplineSpeed),
           (unsigned)bits(cd->FOVSplineSpeed), (int)cd->LockEyeSpeedToCar,
           (int)cd->LockLookSpeedToCar, (unsigned)bits(cd->MinAreaPercent),
           (unsigned)bits(cd->MaxAreaPercent), (unsigned)bits(cd->NearClip),
           (unsigned)bits(cd->FarClip), (int)cd->Backwards,
           label(cd->FOVTable), (int)cd->NumAreaVerts, label(cd->AreaVerts),
           (int)cd->NumAreaFaces, label(cd->AreaFaces),
           (int)cd->NumEyeVerts, label(cd->EyeVerts), label(cd->BankVerts),
           (int)cd->NumLookVerts, label(cd->LookVerts));
    printf("  cd2 %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x"
           " %08x %d %08x %d %d\n",
           (unsigned)bits(cd->SpringXVel), (unsigned)bits(cd->SpringYVel),
           (unsigned)bits(cd->SpringZVel), (unsigned)bits(cd->SpringDamp),
           (unsigned)bits(cd->SpringConst), (unsigned)bits(cd->LookOffsetX),
           (unsigned)bits(cd->LookOffsetY), (unsigned)bits(cd->LookOffsetZ),
           (unsigned)bits(cd->EnterVertComp),
           (unsigned)bits(cd->EnterHorizComp),
           (unsigned)bits(cd->LeaveVertComp),
           (unsigned)bits(cd->LeaveHorizComp), (int)cd->IsLeaveSet,
           (unsigned)bits(cd->WipeDistance), (int)cd->WipeAutoDisable,
           (int)cd->ShakeBankNumber);
    if (known(cd->FOVTable))
        print_verts("fov", cd->FOVTable, 32);
    if (known(cd->EyeVerts))
        print_verts("eye", cd->EyeVerts, clamp16(cd->NumEyeVerts));
    if (known(cd->BankVerts))
        print_verts("bank", cd->BankVerts, clamp16(cd->NumEyeVerts));
}

TrackCarCameraMover *track_car_camera_mover_init(
    TrackCarCameraMover *m, int viewID, struct Car *car,
    const CameraDataItems *cd, const CameraShake *shake, int focusEffects)
{
    const uint8_t *s = (const uint8_t *)shake;
    int i, nz = 0;

    printf("  mover ctor %s %d %s %s\n", label(m), viewID, label(car),
           label(cd));
    if (cd != NULL)
        print_cd(cd);
    for (i = 0; i < (int)sizeof *shake; i++)
        nz += s[i] != 0;
    printf("  shake %d %d focus %d\n", (int)shake->NumCVs, nz, focusEffects);
    m->base.vtbl = &moverVtbl;
    return m;
}

// ------------------------------------------------------- the script

static int field(char **f, int n, int i)
{
    return i < n ? (int)strtoll(f[i], NULL, 0) : 0;
}

static uint32_t ufield(char **f, int n, int i)
{
    return i < n ? (uint32_t)strtoull(f[i], NULL, 0) : 0;
}

static void set_old(RaceCoordinator *rc, char **f, int n)
{
    if (field(f, n, 2)) {
        memset(&om, 0, sizeof om);
        om.base.vtbl = &moverVtbl;
        rc->mpCameraMover = &om;
    } else {
        rc->mpCameraMover = NULL;
    }
    if (field(f, n, 3)) {
        memset(&ocd, 0, sizeof ocd);
        rc->mpCD = &ocd;
    } else {
        rc->mpCD = NULL;
    }
    if (field(f, n, 4)) {
        memset(ofov, 0, sizeof ofov);
        rc->mpFOVtable = ofov;
    } else {
        rc->mpFOVtable = NULL;
    }
    if (field(f, n, 5)) {
        memset(&oroute, 0, sizeof oroute);
        oroute.pPoints = pts;
        oroute.nPoints = orouteN;
        rc->mpRoute = &oroute;
    } else {
        rc->mpRoute = NULL;
    }
    if (field(f, n, 6)) {
        memset(obank, 0, sizeof obank);
        rc->mpBankVerts = obank;
    } else {
        rc->mpBankVerts = NULL;
    }
    if (field(f, n, 7)) {
        memset(oeye, 0, sizeof oeye);
        rc->mpEyeVerts = oeye;
    } else {
        rc->mpEyeVerts = NULL;
    }
}

static void dump_coord(const char *name, const RaceCoordinator *rc)
{
    const PreviewRoute *r = (const PreviewRoute *)rc->mpRoute;

    printf("  %s rew %d mover %s cd %s ip %s view %d car %s car2 %s\n",
           name, (int)rc->mNumRewinds, label(rc->mpCameraMover),
           label(rc->mpCD), label(rc->mIncidentPoint), (int)rc->mViewID,
           label(rc->mpHighlightCar), label(rc->mpHighlightCar2));
    printf("  %s ic %08x %08x %08x %08x fin %08x %08x %08x %08x"
           " start %08x %08x %08x %08x\n", name,
           (unsigned)bits(rc->mIncidentCoord.x),
           (unsigned)bits(rc->mIncidentCoord.y),
           (unsigned)bits(rc->mIncidentCoord.z),
           (unsigned)bits(rc->mIncidentCoord.pad),
           (unsigned)bits(rc->mFinalPosition.x),
           (unsigned)bits(rc->mFinalPosition.y),
           (unsigned)bits(rc->mFinalPosition.z),
           (unsigned)bits(rc->mFinalPosition.pad),
           (unsigned)bits(rc->mStartPosition.x),
           (unsigned)bits(rc->mStartPosition.y),
           (unsigned)bits(rc->mStartPosition.z),
           (unsigned)bits(rc->mStartPosition.pad));
    printf("  %s eye %s bank %s fov %s route %s", name,
           label(rc->mpEyeVerts), label(rc->mpBankVerts),
           label(rc->mpFOVtable), label(rc->mpRoute));
    if (r != NULL)
        printf(" n %d pts %s", (int)r->nPoints, label(r->pPoints));
    printf("\n");
    if (known(rc->mpEyeVerts))
        print_verts("eyes", (const bVector3 *)rc->mpEyeVerts, DUMP_VERTS);
    if (known(rc->mpBankVerts))
        print_verts("banks", (const bVector3 *)rc->mpBankVerts, DUMP_VERTS);
}

// Whether a tick would rewind with nothing to rewind into.
static int tick_unsafe(const RaceCoordinator *rc)
{
    const PreviewRoute *r = (const PreviewRoute *)rc->mpRoute;

    if ((int32_t)((uint32_t)rmMem.EndCapturingLoopCount
                  - (uint32_t)WorldLoopCounter) > 0)
        return 0;
    if ((int32_t)((uint32_t)rc->mNumRewinds + 1u) >= 3)
        return 0;
    if (r == NULL || rc->mpCD == NULL)
        return 1;
    return r->nPoints > 0
           && (rc->mpBankVerts == NULL || rc->mpEyeVerts == NULL);
}

static void op(char *line)
{
    char *f[24];
    int n = 0;
    char *s = line;

    while (n < 24) {
        f[n++] = s;
        s = strchr(s, '|');
        if (s == NULL)
            break;
        *s++ = 0;
    }
    if (strcmp(f[0], "tag") == 0)
        return;
    if (strcmp(f[0], "car") == 0) {
        bVector3 *p = &cars[field(f, n, 1)].State.Position;

        p->x = flt(ufield(f, n, 2));
        p->y = flt(ufield(f, n, 3));
        p->z = flt(ufield(f, n, 4));
        p->pad = flt(ufield(f, n, 5));
    } else if (strcmp(f[0], "prc") == 0) {
        pRaceCoordinator = coord(field(f, n, 1));
    } else if (strcmp(f[0], "players") == 0) {
        PlayerNumPlayers = field(f, n, 1);
    } else if (strcmp(f[0], "ans") == 0) {
        ansTake = field(f, n, 1);
        ansAuto = field(f, n, 2);
        ansIR = field(f, n, 3);
        ansPresent = field(f, n, 4);
    } else if (strcmp(f[0], "rp") == 0) {
        rpOn = field(f, n, 1);
    } else if (strcmp(f[0], "route") == 0) {
        routeN = field(f, n, 1);
        routeRet = field(f, n, 2);
    } else if (strcmp(f[0], "width") == 0) {
        int k = field(f, n, 1);

        trp[k].LeftWidth = flt(ufield(f, n, 2));
        trp[k].RightWidth = flt(ufield(f, n, 3));
    } else if (strcmp(f[0], "tpcs") == 0) {
        int i;

        numTpcs = nextTpc = 0;
        for (i = 1; i + 1 < n && numTpcs < MAX_TPCS; i += 2) {
            tpcs[numTpcs][0] = ufield(f, n, i);
            tpcs[numTpcs][1] = ufield(f, n, i + 1);
            numTpcs++;
        }
    } else if (strcmp(f[0], "loops") == 0) {
        rmMem.EndCapturingLoopCount = field(f, n, 1);
        WorldLoopCounter = field(f, n, 2);
    } else if (strcmp(f[0], "dir") == 0) {
        TheRaceParameters.TrackDirection = field(f, n, 1);
    } else if (strcmp(f[0], "old") == 0) {
        set_old(coord(field(f, n, 1)), f, n);
    } else if (strcmp(f[0], "oroute") == 0) {
        orouteN = field(f, n, 1);
        oroute.nPoints = orouteN;
    } else if (strcmp(f[0], "ocd") == 0) {
        ocd.EnterHorizComp = flt(ufield(f, n, 1));
    } else if (strcmp(f[0], "rewinds") == 0) {
        coord(field(f, n, 1))->mNumRewinds = field(f, n, 2);
    } else if (strcmp(f[0], "hl") == 0) {
        RaceCoordinator *rc = coord(field(f, n, 1));

        rc->mpHighlightCar = car_arg(field(f, n, 2));
        rc->mpHighlightCar2 = car_arg(field(f, n, 3));
        rc->mViewID = field(f, n, 4);
    } else if (strcmp(f[0], "msg") == 0) {
        RCMessage m = (RCMessage)field(f, n, 1);
        int32_t r;

        if ((m == RC_TICK && tick_unsafe(&rcMem))
            || (m == RC_ACTIVATE && pRaceCoordinator != &rcMem
                && rcMem.mpRoute == NULL)) {
            printf("  unsafe\n");
            return;
        }
        r = rc_state_auto_replay_callback(&rcMem, m, field(f, n, 2));
        printf("  -> %d\n", (int)r);
    } else if (strcmp(f[0], "setup") == 0) {
        racecoordinator_set_up_auto_replay(&rcMem, car_arg(field(f, n, 1)),
                                           car_arg(field(f, n, 2)),
                                           field(f, n, 3));
    } else if (strcmp(f[0], "cleanup") == 0) {
        racecoordinator_clean_up_auto_replay(coord(field(f, n, 1)));
    } else if (strcmp(f[0], "check") == 0) {
        printf("  -> %d\n",
               (int)racecoordinator_check_auto_replay_cam(
                   coord(field(f, n, 1))));
    } else if (strcmp(f[0], "setupcam") == 0) {
        RaceCoordinator *rc = coord(field(f, n, 1));

        if (rc->mpRoute == NULL) {
            printf("  no route\n");
            return;
        }
        racecoordinator_set_up_auto_replay_cam(rc);
    } else if (strcmp(f[0], "dump") == 0) {
        dump_coord("RC", &rcMem);
        dump_coord("RC2", &rc2Mem);
    } else {
        printf("  unknown op %s\n", f[0]);
    }
}

int main(int argc, char **argv)
{
    static char line[1024];
    FILE *sc;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: rcauto_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    for (i = 0; i < 2; i++)
        PlayerPlayersByIndex[i] = &players[i];
    for (i = 0; i < NUM_PTS; i++) {
        pts[i].pPoint = &trp[i];
        trp[i].LeftWidth = 2.5f + (float)i;
        trp[i].RightWidth = 1.75f + 0.5f * (float)i;
    }
    pReplayManager = &rmMem;
    pRaceCoordinator = &rcMem;
    gSetFlailerScreenVisibilityFn = screen_visibility;
    gRestoreTypeChangedHandlersFn = type_handlers;

    while (fgets(line, sizeof line, sc)) {
        size_t len = strlen(line);

        while (len && (line[len - 1] == '\n' || line[len - 1] == '\r'))
            line[--len] = 0;
        if (!len)
            continue;
        printf("> %s\n", line);
        op(line);
    }
    fclose(sc);
    return 0;
}
