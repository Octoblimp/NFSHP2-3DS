// Host harness for 3DS Files/source/playerinit.c and nisoverlay.c, the
// Player's constructor, destructor and race calls and the NIS overlay
// they build. Runs the op script tools/player_check.py writes and prints
// the transcript it diffs against the retail image, run in mipsemu over the
// same script.
//
// playerinit.c, nisoverlay.c and player.c are the port sources here. The
// harness owns everything under them: bMalloc and bFree over a numbered
// arena, the topology, the Average, the joystick type, the real driver's
// transmission, RemoveCameraMovers, TheRaceParameters' words and every
// seam. Each prints its arguments in the model's words.
//
// The players are two statics, p0 and p1, filled with 0xa5 before each
// construction, so a field one side writes and the other does not shows.
// The dump walks the Player by name; the model reads the same names at
// retail's offsets.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "average.h"
#include "bmem.h"
#include "car.h"
#include "joystick.h"
#include "nisoverlay.h"
#include "player.h"
#include "playercam.h"
#include "playerinit.h"
#include "race.h"
#include "realdriver.h"
#include "topology.h"

#define NOBJ 4096               // a0 .. a4095
#define OBJ_BYTES 1024
#define NCAR 4
#define NPLAYER 2
#define NHUD 20
#define PATTERN 0xa5

// The harness prints the retail size for sizeof(Average), so it may not
// stand for a size another allocation asks for.
typedef char sizes_distinct[
    (sizeof(Average) != 48 && sizeof(Average) != 164
     && sizeof(Average) != 320 && sizeof(Average) != 512) ? 1 : -1];

// What playerinit.c and nisoverlay.c reach outside themselves.
RaceParameters TheRaceParameters;
int32_t WorldTimer;
int32_t bResetGlare;
const int *gPlayerCamSkipFE;
void (*gPreviewRouteDeleteFn)(struct PreviewRoute *route);
void (*gRadialBlurOffFn)(int32_t view);
void (*gSetFlailerScreenVisibilityFn)(uint32_t screen, int visibility);

static struct Player players[NPLAYER];
static int shown[NPLAYER];
static struct Car cars[NCAR];
static int skipFE;
static int joyBase;

// Stand-ins the Player points at, by address only.
static int32_t drivers[NCAR][8], route[8], jumpRoute[8], zoneSample[8];
static int32_t line[8], huds[NHUD][4], busted[8], scoreObj[4][8];
static int32_t radarBeep[8];

// The score objects the HUD has (a bit each, in scoreHash's order), each
// one's top, and what the overlay's scale and top answer.
static const uint32_t scoreHash[4] = {
    0x464ba8eau, 0xd911beacu, 0xf7f1cfb3u, 0xf88dd0b1u,
};
static int scoreMask;
static uint32_t scoreTop[4];
static uint32_t nisSx, nisSy, nisTop;

static _Alignas(16) unsigned char arena[NOBJ][OBJ_BYTES];
static int nobj;
static struct {
    int live;
    int track;      // a NISCubicAnimation
    int32_t playing;// a NisManager's word at +68
} meta[NOBJ];

static int obj_index(const void *p)
{
    const unsigned char *c = p;
    size_t off;

    if (c < arena[0] || c >= arena[NOBJ])
        return -1;
    off = (size_t)(c - arena[0]);
    return off % OBJ_BYTES ? -1 : (int)(off / OBJ_BYTES);
}

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    int i;

    if (p == NULL)
        return "null";
    for (i = 0; i < NPLAYER; i++) {
        if (p == &players[i]) {
            sprintf(b, "p%d", i);
            return b;
        }
        if (p == &players[i].Topology) {
            sprintf(b, "p%d.topo", i);
            return b;
        }
        if (p == &players[i].mFlailerNIS) {
            sprintf(b, "p%d.nis", i);
            return b;
        }
    }
    for (i = 0; i < NCAR; i++) {
        if (p == &cars[i]) {
            sprintf(b, "k%d", i);
            return b;
        }
        if (p == drivers[i]) {
            sprintf(b, "d%d", i);
            return b;
        }
    }
    for (i = 0; i < NHUD; i++) {
        if (p == huds[i]) {
            sprintf(b, "h%d", i);
            return b;
        }
    }
    for (i = 0; i < 4; i++) {
        if (p == scoreObj[i]) {
            sprintf(b, "o%d", i);
            return b;
        }
    }
    if (p == route)
        return "rt";
    if (p == jumpRoute)
        return "jr";
    if (p == zoneSample)
        return "zs";
    if (p == line)
        return "ln";
    if (p == busted)
        return "bd";
    if (p == radarBeep)
        return "rb";
    i = obj_index(p);
    if (i >= 0) {
        sprintf(b, "a%d", i);
        return b;
    }
    sprintf(b, "?%08lx", (unsigned long)(uint32_t)(uintptr_t)p);
    return b;
}

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float from_bits(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static const char *fx(float f)
{
    static char buf[16][12];
    static int slot;
    char *b = buf[slot++ & 15];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

// ---------------------------------------------------------------- the arena

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p;
    int shownSize = size == (int)sizeof(Average) ? 16 : size;

    if (nobj >= NOBJ) {
        fprintf(stderr, "arena full\n");
        exit(3);
    }
    p = arena[nobj];
    memset(p, PATTERN, OBJ_BYTES);
    meta[nobj].live = 1;
    meta[nobj].track = !strcmp(name, "NISCubicAnimation");
    meta[nobj].playing = 0;
    nobj++;
    printf("  malloc %d %s %d %d -> %s\n", shownSize, name, flags, pool,
           nm(p));
    return p;
}

void bFree(void *p)
{
    int i = obj_index(p);

    printf("  free %s\n", nm(p));
    if (i >= 0)
        meta[i].live = 0;
}

// ------------------------------------------------- what playerinit.c calls

void topology_init(TopologyCoordinate *tc)
{
    printf("  topo %s\n", nm(tc));
}

void topology_destroy(TopologyCoordinate *tc)
{
    printf("  topodel %s flag 2\n", nm(tc));
}

Average *average_init(Average *a, int32_t slots)
{
    printf("  avg %s %d\n", nm(a), (int)slots);
    return a;
}

void average_destroy(Average *a, int32_t flags)
{
    printf("  avgdel %s flag %d\n", nm(a), (int)flags);
}

int32_t GetJoystickType(JoystickPort port)
{
    int32_t r = joyBase + port;

    printf("  joytype %d -> %d\n", (int)port, (int)r);
    return r;
}

void realdriver_set_manual_transmission(RealDriver *d, int32_t m)
{
    printf("  manual %s %d\n", nm(d), (int)m);
}

void player_remove_camera_movers(struct Player *p)
{
    printf("  rmcams %s\n", nm(p));
}

// --------------------------------------------------------------- the seams

static struct NisManager *s_nisnew(void *mem, const char *name,
                                   int32_t number)
{
    int i = obj_index(mem);

    printf("  nisnew %s %s %d\n", nm(mem), name, (int)number);
    if (i >= 0)
        meta[i].playing = 0;
    return (struct NisManager *)mem;
}

static struct bSample *s_sample(const char *name)
{
    printf("  sample %s -> rb\n", name);
    return (struct bSample *)radarBeep;
}

static struct FlailerObjectChunk *s_find(uint32_t screen, uint32_t object,
                                         int32_t type)
{
    struct FlailerObjectChunk *r = NULL;
    int k;

    for (k = 0; k < 4; k++)
        if (object == scoreHash[k] && (scoreMask >> k & 1))
            r = (struct FlailerObjectChunk *)scoreObj[k];
    printf("  find %08lx %08lx %d -> %s\n", (unsigned long)screen,
           (unsigned long)object, (int)type, nm(r));
    return r;
}

static void s_topleft(struct FlailerObjectChunk *o, float *x, float *y)
{
    int k;

    printf("  topleft %s\n", nm(o));
    *x = from_bits(0x3f800000u);
    *y = 0.0f;
    for (k = 0; k < 4; k++)
        if ((void *)o == scoreObj[k])
            *y = from_bits(scoreTop[k]);
}

static void s_getscale(uint32_t screen, uint32_t object, float *sx,
                       float *sy)
{
    printf("  getscale %08lx %08lx\n", (unsigned long)screen,
           (unsigned long)object);
    *sx = from_bits(nisSx);
    *sy = from_bits(nisSy);
}

static float s_gettop(uint32_t screen, uint32_t object)
{
    printf("  gettop %08lx %08lx\n", (unsigned long)screen,
           (unsigned long)object);
    return from_bits(nisTop);
}

static void s_vis(uint32_t screen, int visibility)
{
    printf("  vis %08lx %d\n", (unsigned long)screen, visibility);
}

static void s_scalex(struct FlailerObjectChunk *o, float v)
{
    printf("  scalex %s %s\n", nm(o), fx(v));
}

static void s_scaley(struct FlailerObjectChunk *o, float v)
{
    printf("  scaley %s %s\n", nm(o), fx(v));
}

static void s_settop(struct FlailerObjectChunk *o, float v)
{
    printf("  settop %s %s\n", nm(o), fx(v));
}

static void s_bluroff(int32_t view)
{
    printf("  bluroff %d\n", (int)view);
}

static void s_inputmode(struct Player *p, int32_t mode)
{
    printf("  inputmode %s %d\n", nm(p), (int)mode);
}

static int32_t s_playing(const struct NisManager *m)
{
    int i = obj_index(m);

    return i >= 0 ? meta[i].playing : 0;
}

static void s_nisstop(struct NisManager *m)
{
    printf("  nisstop %s\n", nm(m));
}

static void s_randnis(struct Player *p, int32_t type)
{
    printf("  randnis %s %d\n", nm(p), (int)type);
}

static void s_resetflailer(struct Player *p)
{
    printf("  resetflailer %s\n", nm(p));
}

static void s_hudfeat(struct Player *p, uint32_t features)
{
    printf("  hudfeat %s %lu\n", nm(p), (unsigned long)features);
}

static void s_routedel(struct PreviewRoute *r)
{
    printf("  routedel %s flag 3\n", nm(r));
}

static void s_sampledel(struct bSample *s)
{
    printf("  sampledel %s flag 3\n", nm(s));
}

static void s_linedel(struct VisibleDrivingLine *l)
{
    printf("  linedel %s flag 3\n", nm(l));
}

static void s_nisdel(struct NisManager *m)
{
    printf("  nisdel %s flag 3\n", nm(m));
}

static void s_huddel(struct HudAnimator *a)
{
    printf("  huddel %s flag 3\n", nm(a));
}

// ---------------------------------------------------------------- the dump

typedef struct {
    const char *name;
    size_t off;
    char kind;      // w a 4-byte word, p a pointer, b a byte
    int n;
} Field;

#define FW(f, n) {#f, offsetof(struct Player, f), 'w', n}
#define FP(f, n) {#f, offsetof(struct Player, f), 'p', n}
#define FB(f, n) {#f, offsetof(struct Player, f), 'b', n}

// The Player but its TopologyCoordinate, which only the stubs touch, and
// the overlay, which has its own table. The model's is the same list at
// retail's offsets.
static const Field playerFields[] = {
    FP(NisFinishedCallback, 1), FP(MyCar, 1), FW(JoyPort, 1),
    FW(JoyType, 1), FW(PlayerNumber, 1), FP(pOtherPlayer, 1),
    FW(ViewID, 1), FW(RearViewMirrorViewID, 1), FB(PlayerSettings, 48),
    FW(TimeFinishedRacing, 1), FW(FinishAnimationLength, 1),
    FW(nZoneCurrent, 1), FW(nZonePrevious, 1), FB(nZoneCredits, 8),
    FW(tAutoZoneTimers, 8), FP(pRoute, 1), FP(pZoneSample, 1),
    FW(bZoneMuffleSound, 1), FW(fZoneMuffleVolume, 1),
    FW(tIgnoreNextPovChange, 1), FW(fFreezeZoneDelayTimer, 1),
    FP(pAverageSpeedRatio, 1), FW(tAverageSpeedTimer, 1),
    FW(fMaxSpeedRatio, 1), FW(LastTimeCarInTrouble, 1),
    FW(TimeToDisplayResetPrompt, 1), FW(New180, 1), FW(tZoneSoundTimer, 1),
    FW(DrivingControls, 1), FW(nGlueCount, 1), FW(PlayerInputMode, 1),
    FP(pCameraMover, 1), FP(pSavedCameraMover, 1),
    FP(pSavedCameraMover2, 1), FP(pRVMCameraMover, 1),
    FP(pDemoCameraCoordinator, 1), FP(pCountdownCameraCoordinator, 1),
    FP(pNisCameraCoordinator, 1), FP(pVisibleDrivingLine, 1),
    FW(ArrestNisIndex, 1), FW(TicketNisIndex, 1),
    FW(NisFinishedCallbackParam, 1), FP(pNisManager, 1),
    FW(TicketNisNumbers, 32), FW(TicketCameraNumbers, 32),
    FW(ArrestNisNumbers, 32), FW(ArrestCameraNumbers, 32),
    FW(bWrongWay, 1), FW(bLookBack, 1), FW(CurrentHudFeatures, 1),
    FW(HudScreenHash, 1), FW(NisOverlayHash, 1),
    FP(pFlailerSpeedNeedle, 1), FP(pFlailerTachNeedle, 1),
    FP(pFlailerTachGear, 1), FP(pFlailerTachGradient, 1),
    FB(FlailerTachPointList, 180), FP(pFlailerRacePosition, 1),
    FP(pFlailerBigRacePosition, 1), FP(pFlailerBigRacePosition2, 1),
    FP(pFlailerBigRaceExtension, 1), FP(pFlailerBigRaceTotal, 1),
    FP(pFlailerLapCounter, 1), FP(pFlailerLapTime, 1),
    FP(pFlailerBestLap, 1), FP(pFlailerRunningSplitTime, 1),
    FP(pFlailerCompSplitTime, 1), FP(pFlailerTireForce, 4),
    FP(pFlailerSpeedString, 1), FP(pFlailerSpeedString2, 1),
    FP(pFlailerGearString, 1), FP(pFlailerShiftUp, 1),
    FP(pFlailerShiftDown, 1), FP(pFlailerCFPSString, 1),
    FP(pFlailerGFPSString, 1), FP(pFlailerPosString, 1),
    FP(pFlailerDistString, 1), FP(pFlailerDebugBacking, 1),
    FP(pFlailerPursuitStar, 1), FP(pFlailerPursuitLevel, 4),
    FP(pFlailerPursuitX, 3), FW(PrevPursuitLevel, 1),
    FW(PrevTicketLevel, 1), FP(pFlailerTracker, 7), FP(pFlailerReticle, 1),
    FP(pFlailerEventTitle, 1), FP(pFlailerEventScore, 1),
    FP(pFlailerScoreTitle, 1), FP(pFlailerScoreTotal, 1),
    FP(pFlailerMusicArtist, 1), FP(pFlailerMusicTitle, 1),
    FP(pFlailerMusicLabel, 1), FP(pFlailerMusicEA, 1),
    FP(pFlailerRadarLight, 12), FP(pFlailerNitrousLight, 10),
    FP(pFlailerDamageLight, 5), FP(pFlailerBeTheCopTickets, 4),
    FB(_flailers1300, 68), FP(pFlailerBeTheCopTime, 1),
    FP(pFlailerBeTheCopHelicopter, 3), FP(pFlailerBeTheCopRoadblock, 3),
    FB(_new1396, 8), FP(pRadarBeep, 1), FW(RadarTimer, 1),
    FB(strEventTitle, 32), FB(strEventScore, 32), FB(strPrevScore, 32),
    FW(HangTime, 1), FW(DriftTime, 1), FW(PosChangeTime, 1),
    FW(PositionFlag, 1), FW(TotalScore, 1), FP(pTrackMap, 1),
    FW(TimeTrackMapModeChanged, 1), FP(pRouteDisplayer, 1),
    FP(pHudAnimations, 20), FW(LastRacePosition, 1), FW(LastSpeed, 1),
    FW(LastSpeedSet, 1), FW(TopSpeed, 1), FW(bNewTopSpeed, 1),
    FW(bCheckTopSpeed, 1), FW(SpeedFactor, 1), FW(fBeginLapNumberExact, 1),
    FP(myCD, 1), FB(_pad1656, 8), FW(EyeVerts, 12), FW(BankVerts, 12),
    FP(FOVtable, 1), FP(pJumpCamRoute, 1), FW(mAutoReplayTimeMarker, 1),
    FW(mLastAutoReplayTime, 1), FW(mAutoReplayState, 1),
    FW(PursuitObjectPos, 14), FW(New2540, 1), FW(bCollisionDetected, 1),
    FW(bSmokeableHit, 1), FW(BestLapRecordData, 1),
    FW(BestTotalRecordData, 1), FP(lastCar, 1), FW(LastCrossingTime, 1),
    FW(bSegmentCollisionDetected, 1), FW(baPlaceReached, 8),
    FW(bShownMusicTitle, 1), FW(CurrentJukeboxIndex, 1),
    FW(bRadarOffset, 1), FW(fInitialRadarY, 1), FW(bPursuitOffset, 1),
    FW(fInitialPursuitY, 1), FW(PursuitOffsetState, 1),
    FW(numCleanLaps, 1), FW(HasHeardRaceOverSpeech, 1), FW(New2696, 1),
    FP(pFlailerScore, 4), FW(fScoreTop, 4), FW(tScoreAnimation, 1),
    FW(New2736, 1), FB(_pad2740, 12),
};

#define NW(f) {#f, offsetof(NISOverlayManager, f), 'w', 1}
#define NP(f) {#f, offsetof(NISOverlayManager, f), 'p', 1}

static const Field nisFields[] = {
    NW(LastDateTimeUpdate), NW(ScreenHash), NW(State),
    NP(ScaleAnimationTrack), NP(AlphaAnimationTrack), NP(BustedDisplay),
    NW(New24), NW(sx), NW(sy), NW(ScaleX), NW(ScaleY), NW(SavedScaleX),
    NW(SavedScaleY), NW(SavedTopLeftY),
};

static void dump_field(const char *who, const void *base, const Field *f)
{
    const unsigned char *a = (const unsigned char *)base + f->off;
    int k;

    printf("  %s %s", who, f->name);
    if (f->kind == 'b')
        printf(" ");
    for (k = 0; k < f->n; k++) {
        if (f->kind == 'w') {
            uint32_t u;

            memcpy(&u, a + 4 * k, 4);
            printf(" %08lx", (unsigned long)u);
        } else if (f->kind == 'p') {
            const void *p;

            memcpy(&p, a + sizeof(void *) * k, sizeof(void *));
            printf(" %s", nm(p));
        } else {
            printf("%02x", a[k]);
        }
    }
    printf("\n");
}

static void dump_globals(void)
{
    printf("  g num %d idx %s %s byn %s %s glare %d\n", (int)PlayerNumPlayers,
           nm(PlayerPlayersByIndex[0]), nm(PlayerPlayersByIndex[1]),
           nm(PlayerPlayersByNumber[0]), nm(PlayerPlayersByNumber[1]),
           (int)bResetGlare);
}

static void dump(void)
{
    char who[16];
    size_t i;
    int k;

    dump_globals();
    for (k = 0; k < NCAR; k++)
        printf("  k%d player %s mode %08lx\n", k, nm(cars[k].pPlayer),
               (unsigned long)(uint32_t)cars[k].State.DriverMode);
    for (k = 0; k < 2; k++) {
        const unsigned char *s =
            (const unsigned char *)&RaceParametersPlayerSettings[k];

        printf("  rs%d ", k);
        for (i = 0; i < sizeof(cPlayerSettings); i++)
            printf("%02x", s[i]);
        printf("\n");
    }
    for (k = 0; k < NPLAYER; k++) {
        if (!shown[k])
            continue;
        sprintf(who, "p%d", k);
        for (i = 0; i < sizeof playerFields / sizeof playerFields[0]; i++)
            dump_field(who, &players[k], &playerFields[i]);
        sprintf(who, "p%d.nis", k);
        for (i = 0; i < sizeof nisFields / sizeof nisFields[0]; i++)
            dump_field(who, &players[k].mFlailerNIS, &nisFields[i]);
    }
    for (k = 0; k < nobj; k++) {
        if (!meta[k].live || !meta[k].track)
            continue;
        printf("  a%d track ", k);
        for (i = 0; i < 48; i++)
            printf("%02x", arena[k][i]);
        printf("\n");
    }
}

// ------------------------------------------------------------- the script

static char *stok(void)
{
    char *t = strtok(NULL, " \t\r\n");

    if (t == NULL) {
        fprintf(stderr, "short line\n");
        exit(2);
    }
    return t;
}

static int itok(void)
{
    return (int)strtol(stok(), NULL, 0);
}

static uint32_t htok(void)
{
    return (uint32_t)strtoul(stok(), NULL, 16);
}

static void reset(void)
{
    int k;

    nobj = 0;
    memset(meta, 0, sizeof meta);
    memset(players, PATTERN, sizeof players);
    memset(shown, 0, sizeof shown);
    PlayerNumPlayers = 0;
    PlayerPlayersByIndex[0] = PlayerPlayersByIndex[1] = NULL;
    PlayerPlayersByNumber[0] = PlayerPlayersByNumber[1] = NULL;
    bResetGlare = 0;
    WorldTimer = 0;
    skipFE = 0;
    PlayerSkipFEPOVIndex = 1;
    RaceParametersNumPlayerCars = 1;
    RaceParametersAIDemoMode = 0;
    RaceParametersReplayDemoMode = 0;
    RaceParametersBeACop = 0;
    memset(RaceParametersPlayerSettings, PATTERN,
           sizeof RaceParametersPlayerSettings);
    memset(cars, PATTERN, sizeof cars);
    for (k = 0; k < NCAR; k++) {
        cars[k].pPlayer = NULL;
        cars[k].TheControlMode = (ControlMode)0;
        cars[k].pCarDriver = (CarDriver *)(void *)drivers[k];
        cars[k].State.DriverMode = 0;
    }
    joyBase = 40;
    scoreMask = 15;
    for (k = 0; k < 4; k++)
        scoreTop[k] = bits(10.0f * (float)(k + 1));
    nisSx = 0x3f000000u;
    nisSy = 0x40000000u;
    nisTop = 0x41200000u;
}

static void set_global(const char *f, int v)
{
    if (!strcmp(f, "cars"))
        RaceParametersNumPlayerCars = v;
    else if (!strcmp(f, "aidemo"))
        RaceParametersAIDemoMode = v;
    else if (!strcmp(f, "replay"))
        RaceParametersReplayDemoMode = v;
    else if (!strcmp(f, "beacop"))
        RaceParametersBeACop = v;
    else if (!strcmp(f, "skip"))
        skipFE = v;
    else if (!strcmp(f, "skippov"))
        PlayerSkipFEPOVIndex = (uint8_t)v;
    else if (!strcmp(f, "timer"))
        WorldTimer = v;
    else if (!strcmp(f, "joy"))
        joyBase = v;
    else {
        fprintf(stderr, "bad global %s\n", f);
        exit(2);
    }
}

static void set_field(struct Player *p, const char *f)
{
    if (!strcmp(f, "route"))
        p->pRoute = itok() ? (struct PreviewRoute *)route : NULL;
    else if (!strcmp(f, "jump"))
        p->pJumpCamRoute = itok() ? (struct PreviewRoute *)jumpRoute : NULL;
    else if (!strcmp(f, "zs"))
        p->pZoneSample = itok() ? (struct bSample *)zoneSample : NULL;
    else if (!strcmp(f, "line"))
        p->pVisibleDrivingLine =
            itok() ? (struct VisibleDrivingLine *)line : NULL;
    else if (!strcmp(f, "mgr")) {
        itok();
        p->pNisManager = NULL;
    } else if (!strcmp(f, "cd")) {
        itok();
        p->myCD = NULL;
    } else if (!strcmp(f, "fov")) {
        itok();
        p->FOVtable = NULL;
    } else if (!strcmp(f, "avg")) {
        itok();
        p->pAverageSpeedRatio = NULL;
    } else if (!strcmp(f, "car")) {
        int k = itok();

        p->MyCar = k < 0 ? NULL : &cars[k];
    } else if (!strcmp(f, "busted"))
        p->mFlailerNIS.BustedDisplay =
            itok() ? (struct FlailerObjectChunk *)busted : NULL;
    else if (!strcmp(f, "ohash"))
        p->mFlailerNIS.ScreenHash = htok();
    else if (!strcmp(f, "style"))
        p->PlayerSettings.DrivingStyle = (int8_t)itok();
    else if (!strcmp(f, "trans"))
        p->PlayerSettings.TransmissionType = (int8_t)itok();
    else if (!strcmp(f, "num"))
        p->PlayerNumber = itok();
    else if (!strcmp(f, "dc"))
        p->DrivingControls = htok();
    else if (!strcmp(f, "lastspeed"))
        p->LastSpeed = (int32_t)htok();
    else if (!strcmp(f, "pursuit"))
        p->PrevPursuitLevel = (int32_t)htok();
    else if (!strcmp(f, "ticket"))
        p->PrevTicketLevel = (int32_t)htok();
    else if (!strcmp(f, "speedset")) {
        uint32_t bits = htok();
        memcpy(&p->LastSpeedSet, &bits, sizeof bits);
    } else {
        fprintf(stderr, "bad field %s\n", f);
        exit(2);
    }
}

static struct Player *player_of(int i)
{
    if (i < 0 || i >= NPLAYER) {
        fprintf(stderr, "bad player %d\n", i);
        exit(2);
    }
    return &players[i];
}

int main(int argc, char **argv)
{
    static char text[4096];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: player_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    gPlayerCamSkipFE = &skipFE;
    gNewNisManagerFn = s_nisnew;
    gGetInGameSampleFn = s_sample;
    gFindFlailerObjectFn = s_find;
    gFlailerChunkGetTopLeftFn = s_topleft;
    gFlailerGetScaleFn = s_getscale;
    gFlailerGetTopLeftYFn = s_gettop;
    gSetFlailerScreenVisibilityFn = s_vis;
    gFlailerChunkSetScaleXFn = s_scalex;
    gFlailerChunkSetScaleYFn = s_scaley;
    gFlailerChunkSetTopLeftYFn = s_settop;
    gRadialBlurOffFn = s_bluroff;
    gPlayerSetInputModeFn = s_inputmode;
    gNisManagerIsPlayingFn = s_playing;
    gNisManagerStopFn = s_nisstop;
    gPlayerCreateRandomNisArrayFn = s_randnis;
    gPlayerResetFlailerMovementFn = s_resetflailer;
    gPlayerSetHudFeaturesFn = s_hudfeat;
    gPreviewRouteDeleteFn = s_routedel;
    gSampleDeleteFn = s_sampledel;
    gVisibleDrivingLineDeleteFn = s_linedel;
    gDeleteNisManagerFn = s_nisdel;
    gHudAnimatorDeleteFn = s_huddel;

    while (fgets(text, sizeof text, fp) != NULL) {
        char echo[64];
        char *t;
        int full = 1;

        text[strcspn(text, "\r\n")] = 0;
        snprintf(echo, sizeof echo, "%.40s", text);
        t = strtok(text, " \t");
        if (t == NULL)
            continue;
        if (!strcmp(t, "B")) {
            printf("B %d\n", itok());
            reset();
            continue;
        }
        printf("> %s\n", echo);
        switch (t[0]) {
        case 'S': {
            char *f = stok();

            set_global(f, itok());
            full = 0;
            break;
        }
        case 'G': {
            int s = itok();
            int off = itok();

            ((unsigned char *)&RaceParametersPlayerSettings[s])[off] =
                (unsigned char)itok();
            full = 0;
            break;
        }
        case 'H': {
            int s = itok();
            int off = itok();
            uint32_t v = htok();

            memcpy((unsigned char *)&RaceParametersPlayerSettings[s] + off,
                   &v, 4);
            full = 0;
            break;
        }
        case 'C': {
            int k = itok();

            cars[k].TheControlMode = (ControlMode)itok();
            full = 0;
            break;
        }
        case 'O':
            scoreMask = itok();
            full = 0;
            break;
        case 'T': {
            int k = itok();

            scoreTop[k] = htok();
            full = 0;
            break;
        }
        case 'Q':
            nisSx = htok();
            nisSy = htok();
            nisTop = htok();
            full = 0;
            break;
        case 'F': {
            struct Player *p = player_of(itok());

            set_field(p, stok());
            full = 0;
            break;
        }
        case 'A': {
            struct Player *p = player_of(itok());
            int k = itok();

            p->pHudAnimations[k] = itok() ? (struct HudAnimator *)huds[k]
                                          : NULL;
            full = 0;
            break;
        }
        case 'W': {
            int i = obj_index(player_of(itok())->pNisManager);
            int v = itok();

            if (i >= 0)
                meta[i].playing = v;
            full = 0;
            break;
        }
        case 'N': {
            int i = itok();
            int port = itok();
            int number = itok();
            char *f = strtok(NULL, " \t\r\n");
            struct Player *p = player_of(i);
            struct Player *r;

            // An optional fill byte, the pattern by default.
            memset(p, f ? (int)strtol(f, NULL, 16) : PATTERN, sizeof *p);
            shown[i] = 1;
            r = player_init(p, port, number);
            printf("  -> %s\n", nm(r));
            break;
        }
        case 'Z': {
            struct Player *p = player_of(itok());

            player_destroy(p, itok());
            break;
        }
        case 'I': {
            struct Player *p = player_of(itok());

            player_init_for_race(p, &cars[itok()]);
            break;
        }
        case 'U':
            player_cleanup_after_race(player_of(itok()));
            break;
        case 'P':
            player_predetermine_nis_numbers(player_of(itok()));
            break;
        case 'J':
            player_clean_up_jump_cam(player_of(itok()));
            break;
        case 'R':
            player_settings_reset_to_defaults(
                &RaceParametersPlayerSettings[itok()]);
            break;
        default:
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
        if (full)
            dump();
        else
            dump_globals();
    }
    fclose(fp);
    return 0;
}
