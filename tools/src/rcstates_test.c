// Host harness for 3DS Files/source/rcstates.c, racefinish.c and rcpost.c:
// the race coordinator's NONE, CAMERA_FLYBY, PRERACE, RACE_IN_PROGRESS,
// PAUSE and POSTRACE states, the countdown, the finish, the small methods,
// and the Race's countdown and finish questions. Runs the op script tools/rcstates_check.py writes
// and prints the transcript it diffs against the retail image, run in
// mipsemu over the same script.
//
// rcstates.c, racefinish.c and rcpost.c are the port sources under test,
// with race.c and joystick.c under them and racecoord.c's queue, which the checker links
// through a wrapper that renames InitForRace and CleanupAfterRace so the
// two below can stand in for them. The harness owns everything else, and
// each piece prints in the model's words: bMalloc over a numbered arena,
// the message slot pool, SetRaceStage, SortRacingCarsByLeadership,
// Player::ChangeCameraMover, and every seam.
//
// States 4, 5, 8 and 9 are fake callbacks that print the message, the state and
// the queue, and each script reaction answers one message once with a
// message of its own.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "carinit.h"
#include "player.h"
#include "playercam.h"
#include "playerinit.h"
#include "race.h"
#include "racecoord.h"
#include "racecore.h"
#include "racefinish.h"
#include "raceinit.h"
#include "racerun.h"
#include "rcpost.h"
#include "rcstates.h"
#include "realtime.h"
#include "replay.h"
#include "track.h"
#include "trackflow.h"
#include "world.h"

#define NOBJ 64                 // a0 .. a63
#define OBJ_BYTES 1024
#define NSLOT 64                // m0 .. m63
#define NRC 8                   // r0 .. r7
#define NCAR 6                  // c0 .. c5, each with ad0 .. ad5
#define NREACT 32
#define PATTERN 0xa5
#define PRE_FINISHED 184        // the prerace camera's finished word
#define OBJ_VIS 41              // a Flailer object's visibility byte
#define JB_START 0x3f99999au
#define NTSE 4                  // ts0 .. ts3

typedef char nrc_fits[(NRC <= RACE_MAX_RACING_CARS) ? 1 : -1];

// What the sources under test reach outside the ones linked with them.
World *pCurrentWorld;
ReplayManager *pReplayManager;
int32_t PlayerNumPlayers;
struct Player *PlayerPlayersByNumber[2];
struct Player *PlayerPlayersByIndex[2];
int32_t WorldTimeFrames;
int32_t WorldLoopCounter;
int (*gBCountFreeMemoryFn)(int pool);
void (*gUnloadResourceFileFn)(void *file);
const int *gPlayerCamSkipFE;
void (*gCameraCoordinatorDeleteFn)(void *coord);
void (*gSetFlailerScreenVisibilityFn)(uint32_t screen, int visibility);
struct bSample *(*gGetInGameSampleFn)(const char *name);
struct FlailerObjectChunk *(*gFindFlailerObjectFn)(uint32_t screen,
                                                   uint32_t object,
                                                   int32_t type);

static _Alignas(16) unsigned char arena[NOBJ][OBJ_BYTES];
static int nobj;
static RaceCoordinator rcbuf;
static RCQueuedMessage slots[NSLOT];
static int slotUsed[NSLOT];
static BSlotPool fakePool;
static Race raceObj;
static struct RacingCar rcars[NRC];
static struct Player players[2];
static World worldObj;
static Car cars[NCAR];
static ReplayManager rmObj;
static _Alignas(16) unsigned char fly[256], pre[256], demo[256], eg[256],
    file0[32], sample[32], ads[NCAR][16], flobj[3][64], menu[64];
static TransientStatsElement tse[NTSE];
static int tsPresent[NTSE];
static const uint32_t countObjs[3] = {RC_COUNTDOWN_3, RC_COUNTDOWN_2,
                                      RC_COUNTDOWN_1};

static tGlobalDisplaySettings fedDS;
static float jbTimer;
static int32_t begun;

// The script's answers.
static int tFlyFin, tPFin, tPrerace, tPlaying, tNoSample, tNoObj,
    tAnother, tMulti, tFcDrop, tRDrop, tInitState, tRmMute, tHlEnd;

static struct {
    int state, msg;
    char kind;
    int a, b;
} react[NREACT];
static int nreact;

// ------------------------------------------------------------- the names

static int index_in(const void *p, const void *base, size_t stride, int n)
{
    const unsigned char *c = p, *b = base;
    size_t off;

    if (c < b || c >= b + stride * (size_t)n)
        return -1;
    off = (size_t)(c - b);
    return off % stride ? -1 : (int)(off / stride);
}

static const char *nm(const void *p)
{
    static char b16[16][32];
    static int slot;
    char *b = b16[slot++ & 15];
    int i;

    if (p == NULL)
        return "null";
    if (p == &rcbuf)
        return "rc";
    if (p == fly)
        return "fly";
    if (p == pre)
        return "pre";
    if (p == demo)
        return "demo";
    if (p == eg)
        return "eg";
    if (p == &rmObj)
        return "rm";
    if (p == sample)
        return "smp";
    if (p == file0)
        return "f0";
    if (p == &fakePool)
        return "pool";
    if (p == &raceObj)
        return "race";
    if (p == &worldObj)
        return "w";
    if (p == menu)
        return "menu";
    if ((i = index_in(p, arena, OBJ_BYTES, NOBJ)) >= 0)
        sprintf(b, "a%d", i);
    else if ((i = index_in(p, slots, sizeof slots[0], NSLOT)) >= 0)
        sprintf(b, "m%d", i);
    else if ((i = index_in(p, rcars, sizeof rcars[0], NRC)) >= 0)
        sprintf(b, "r%d", i);
    else if ((i = index_in(p, cars, sizeof cars[0], NCAR)) >= 0)
        sprintf(b, "c%d", i);
    else if ((i = index_in(p, ads, sizeof ads[0], NCAR)) >= 0)
        sprintf(b, "ad%d", i);
    else if ((i = index_in(p, players, sizeof players[0], 2)) >= 0)
        sprintf(b, "p%d", i);
    else if ((i = index_in(p, flobj, sizeof flobj[0], 3)) >= 0)
        sprintf(b, "o%d", 3 - i);
    else if ((i = index_in(p, tse, sizeof tse[0], NTSE)) >= 0)
        sprintf(b, "ts%d", i);
    else
        return "s";
    return b;
}

static const char *fx(float f)
{
    static char b16[16][12];
    static int slot;
    char *b = b16[slot++ & 15];
    uint32_t u;

    memcpy(&u, &f, 4);
    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

// The queue both ways: each message with its RCMessage and parameter
// forward, the names back.
static const char *queue_str(const RaceCoordinator *rc)
{
    static char b[4096];
    const bNode *list = &rc->RCQueuedMessageList;
    const bNode *n;
    size_t k = 0;
    int i;

    b[0] = 0;
    for (n = list->next, i = 0; n != list && i < 80; n = n->next, i++) {
        const RCQueuedMessage *m = (const RCQueuedMessage *)(const void *)n;

        k += (size_t)sprintf(b + k, " %s:%d/%d", nm(m), (int)m->Msg,
                             (int)m->Param);
    }
    k += (size_t)sprintf(b + k, " |");
    for (n = list->prev, i = 0; n != list && i < 80; n = n->prev, i++)
        k += (size_t)sprintf(b + k, " %s", nm(n));
    return b;
}

static void unexpected(const char *what)
{
    fprintf(stderr, "unexpected call: %s\n", what);
    exit(3);
}

// ---------------------------------------------------- the arena and pool

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p;

    if (nobj >= NOBJ) {
        fprintf(stderr, "arena full\n");
        exit(3);
    }
    p = arena[nobj++];
    memset(p, PATTERN, OBJ_BYTES);
    printf("  malloc %d %s %d %d -> %s\n", size, name, flags, pool, nm(p));
    return p;
}

void bFree(void *p)
{
    printf("  delete %s\n", nm(p));
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *name,
                        int pool)
{
    (void)slotSize, (void)numSlots, (void)name, (void)pool;
    unexpected("bNewSlotPool");
    return NULL;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    (void)pool;
    unexpected("bDeleteSlotPool");
}

void *bSlotOMalloc(BSlotPool *pool)
{
    int i;

    for (i = 0; i < NSLOT; i++) {
        if (!slotUsed[i]) {
            slotUsed[i] = 1;
            memset(&slots[i], PATTERN, sizeof slots[i]);
            printf("  omalloc %s -> %s\n", nm(pool), nm(&slots[i]));
            return &slots[i];
        }
    }
    fprintf(stderr, "slots full\n");
    exit(3);
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    int i = index_in(slot, slots, sizeof slots[0], NSLOT);

    printf("  free %s %s ex=%d\n", nm(pool), nm(slot),
           (int)rcbuf.RCExecutingMessage);
    if (i >= 0)
        slotUsed[i] = 0;
}

// ------------------------------------- what only racecoord.c's rest calls

struct Player *player_init(struct Player *p, JoystickPort port,
                           int32_t number)
{
    (void)port, (void)number;
    unexpected("player_init");
    return p;
}

void player_destroy(struct Player *p, int32_t flags)
{
    (void)p, (void)flags;
    unexpected("player_destroy");
}

void player_cleanup_after_race(struct Player *p)
{
    (void)p;
    unexpected("player_cleanup_after_race");
}

void racecoordinator_init_players(RaceCoordinator *rc)
{
    (void)rc;
    unexpected("racecoordinator_init_players");
}

void racecoordinator_init_cars(RaceCoordinator *rc)
{
    (void)rc;
    unexpected("racecoordinator_init_cars");
}

Race *race_construct(Race *r)
{
    unexpected("race_construct");
    return r;
}

void race_destroy(Race *r, int32_t flags)
{
    (void)r, (void)flags;
    unexpected("race_destroy");
}

void race_init(Race *r, eRaceStage stage)
{
    (void)r, (void)stage;
    unexpected("race_init");
}

void race_setup_ghost_cars(Race *r)
{
    (void)r;
    unexpected("race_setup_ghost_cars");
}

World *world_init(World *w)
{
    unexpected("world_init");
    return w;
}

void world_destroy(World *w, int32_t flags)
{
    (void)w, (void)flags;
    unexpected("world_destroy");
}

void world_flush_collisions(World *w)
{
    (void)w;
    unexpected("world_flush_collisions");
}

void car_destruct(Car *c, int32_t flags)
{
    (void)c, (void)flags;
    unexpected("car_destruct");
}

TrackInfo *track_get_info(int i)
{
    (void)i;
    unexpected("track_get_info");
    return NULL;
}

// ------------------------------------------- what the states call directly

void race_set_race_stage(Race *r, eRaceStage stage)
{
    printf("  stage %s %d\n", nm(r), (int)stage);
    r->RaceStage = stage;
}

void race_sort_racing_cars_by_leadership(Race *r)
{
    printf("  sort %s\n", nm(r));
}

void racecoordinator_cleanup_after_race(RaceCoordinator *rc)
{
    printf("  cleanup %s\n", nm(rc));
}

void player_change_camera_mover(struct Player *p, CameraMoverType type,
                                int keep)
{
    printf("  mover %s %d %d\n", nm(p), (int)type, keep);
}

// rcreplay.c's state, which gRCStateCallbacks names; main() puts a fake
// in its place, as for the other states this does not run.
int32_t rc_state_instant_replay_callback(RaceCoordinator *rc,
                                         RCMessage msg, int32_t param)
{
    (void)rc;
    (void)msg;
    (void)param;
    printf("  instant replay never\n");
    return 0;
}

void racecoordinator_init_for_race(RaceCoordinator *rc)
{
    printf("  initforrace %s\n", nm(rc));
    if (tInitState >= 0)
        racecoordinator_change_state(rc, tInitState);
}

// ------------------------------------------------------------ the seams

static void s_mute(int32_t on)          { printf("  mute %d\n", (int)on); }
static void s_setup_next(void)          { printf("  setupnext\n"); }
static void s_abort_check(void)         { printf("  abortcheck\n"); }
static void s_srs_on(void)              { printf("  srs-on\n"); }
static void s_srs_off(void)             { printf("  srs-off\n"); }

static void s_records(int32_t player)
{
    printf("  records %d\n", (int)player);
}

static void s_race_over(Race *r)
{
    printf("  raceover %s\n", nm(r));
}

static int32_t s_another(void)
{
    printf("  another -> %d\n", tAnother);
    return tAnother;
}

static int32_t s_multi(void)
{
    printf("  multi -> %d\n", tMulti);
    return tMulti;
}

static void s_delayed(float seconds)
{
    printf("  delayed %s\n", fx(seconds));
}

static void s_flow(int32_t desired, int32_t pending)
{
    printf("  flow %d %d\n", (int)desired, (int)pending);
}

// A constructed camera coordinator: the prerace camera's finished word.
static void coordinator(void *mem)
{
    int32_t v = tPFin;

    memcpy((unsigned char *)mem + PRE_FINISHED, &v, 4);
}

static void *s_fly_ctor(void *mem, int32_t a)
{
    printf("  flyctor %s %d\n", nm(mem), (int)a);
    coordinator(mem);
    return mem;
}

static void *s_pre_ctor(void *mem, int32_t a)
{
    printf("  prector %s %d\n", nm(mem), (int)a);
    coordinator(mem);
    return mem;
}

static void *s_demo_ctor(void *mem, int32_t a, struct Car *car)
{
    printf("  democtor %s %d %s\n", nm(mem), (int)a, nm(car));
    coordinator(mem);
    return mem;
}

static int32_t s_fly_finished(void *coord)
{
    printf("  flyfin %s -> %d\n", nm(coord), tFlyFin);
    return tFlyFin;
}

static int32_t s_pre_finished(void *coord)
{
    int32_t v;

    memcpy(&v, (unsigned char *)coord + PRE_FINISHED, 4);
    return v;
}

static void s_cancel(struct AnimatedDriver *d)
{
    printf("  cancel %s\n", nm(d));
}

static void *s_find(const char *name)
{
    void *f = tPrerace ? file0 : NULL;

    printf("  find %s -> %s\n", name, nm(f));
    return f;
}

static void s_unload(void *f)
{
    printf("  unload %s\n", nm(f));
    tPrerace = 0;
}

static int32_t s_begun(const struct ReplayManager *rm)
{
    (void)rm;
    return begun;
}

static void s_mark_begin(struct ReplayManager *rm)
{
    printf("  mark-begin %s\n", nm(rm));
    begun = WorldTimeFrames;
}

static void s_mark_end(struct ReplayManager *rm)
{
    printf("  mark-end %s\n", nm(rm));
}

static void s_democams(struct Player *p, struct Car *car)
{
    printf("  democams %s %s\n", nm(p), nm(car));
}

static struct EndGameScreens *s_endgame(void *mem, eContinueRaceType type)
{
    printf("  endgame %s %d\n", nm(mem), (int)type);
    return mem;
}

static struct bSample *s_sample(const char *name)
{
    void *s = tNoSample ? NULL : sample;

    printf("  sample %s -> %s\n", name, nm(s));
    return s;
}

static int32_t s_is_playing(struct bSample *s)
{
    printf("  isplaying %s -> %d\n", nm(s), tPlaying);
    return tPlaying;
}

static void s_play(struct bSample *s, float volume, float a, float b)
{
    printf("  play %s %s %s %s\n", nm(s), fx(volume), fx(a), fx(b));
}

static void s_screen(uint32_t screen, int visibility)
{
    printf("  screen %08lx %d\n", (unsigned long)screen, visibility);
}

static unsigned char *flailer_obj(uint32_t screen, uint32_t object)
{
    int k;

    if (screen != RC_COUNTDOWN_SCREEN)
        return NULL;
    for (k = 0; k < 3; k++)
        if (object == countObjs[k])
            return flobj[k];
    return NULL;
}

static struct FlailerObjectChunk *s_find_obj(uint32_t screen,
                                             uint32_t object, int32_t type)
{
    unsigned char *o = tNoObj ? NULL : flailer_obj(screen, object);

    printf("  findobj %08lx %08lx %d -> %s\n", (unsigned long)screen,
           (unsigned long)object, (int)type, nm(o));
    return (struct FlailerObjectChunk *)(void *)o;
}

static int32_t s_obj_vis(struct FlailerObjectChunk *o)
{
    return (int8_t)((unsigned char *)o)[OBJ_VIS];
}

static void s_set_vis(uint32_t screen, uint32_t object, int32_t visibility)
{
    unsigned char *o = flailer_obj(screen, object);

    printf("  setvis %08lx %08lx %d\n", (unsigned long)screen,
           (unsigned long)object, (int)visibility);
    if (o != NULL)
        o[OBJ_VIS] = (unsigned char)visibility;
}

static void s_alpha(uint32_t screen, uint32_t object, int32_t alpha)
{
    printf("  alpha %08lx %08lx %d\n", (unsigned long)screen,
           (unsigned long)object, (int)alpha);
}

static void s_scale(uint32_t screen, uint32_t object, float scale)
{
    printf("  scale %08lx %08lx %s\n", (unsigned long)screen,
           (unsigned long)object, fx(scale));
}

static void s_ccdel(void *coord)
{
    printf("  ccdel %s 3\n", nm(coord));
}

static void s_finish_car(Race *r, int32_t index, int32_t a, int32_t b,
                         eRaceFinishReason reason)
{
    printf("  finishcar %s %d %d %d %d\n", nm(r), (int)index, (int)a,
           (int)b, (int)reason);
    if (index >= 0 && index < NRC)
        r->pRacingCars[index]->FinishReason = (int16_t)reason;
    if (tFcDrop > 0) {
        tFcDrop--;
        r->NumRacingCars--;
    }
}

static void s_record(Race *r, struct RacingCar *rc, int32_t position)
{
    printf("  record %s %s %d\n", nm(r), nm(rc), (int)position);
    if (tRDrop > 0) {
        tRDrop--;
        r->NumRacingCars--;
    }
}

static void s_hud_clear(struct Player *p)
{
    printf("  hudclear %s\n", nm(p));
}

static void s_enter_pause(struct PauseMenu *m, JoystickPort port)
{
    printf("  enterpause %s %d\n", nm(m), (int)port);
}

static void s_exit_pause(struct PauseMenu *m)
{
    printf("  exitpause %s\n", nm(m));
}

static void s_to_screen(const char *name, int32_t push)
{
    printf("  toscreen %s %d\n", name != NULL ? name : "null", (int)push);
}

static void s_quit(void)                { printf("  quit\n"); }
static void s_restarted(void)           { printf("  restarted\n"); }
static void s_flush(void)               { printf("  flush\n"); }

static void s_mute_replay(int32_t on)
{
    printf("  mutereplay %d\n", (int)on);
}

static void s_highlights(struct ReplayManager *rm)
{
    printf("  highlights %s\n", nm(rm));
}

static void s_next_highlight(struct ReplayManager *rm)
{
    printf("  nexthighlight %s\n", nm(rm));
}

static int32_t s_mute_highlights(const struct ReplayManager *rm)
{
    (void)rm;
    return tRmMute;
}

static int32_t s_highlight_end(const struct ReplayManager *rm)
{
    (void)rm;
    return tHlEnd;
}

static void s_resume(struct EndGameScreens *s)
{
    printf("  resume %s\n", nm(s));
}

static void s_suspend(struct EndGameScreens *s)
{
    printf("  suspend %s\n", nm(s));
}

static const TransientStatsElement *s_get_driver(int32_t num)
{
    const TransientStatsElement *d =
        num >= 0 && num < NTSE && tsPresent[num] ? &tse[num] : NULL;

    printf("  getdriver %d -> %s\n", (int)num, nm(d));
    return d;
}

static void s_type_handlers(void)
{
    printf("  typehandlers demo=%s pn=%d\n",
           nm(rcbuf.pDemoCameraCoordinator), (int)rcbuf.PostRacePlayerNumber);
}

// ------------------------------------------------------- the callbacks

static void respond(int state, RaceCoordinator *rc, RCMessage msg)
{
    int i;

    for (i = 0; i < nreact; i++) {
        if (react[i].state == state && react[i].msg == msg) {
            char kind = react[i].kind;
            int a = react[i].a, b = react[i].b;

            memmove(&react[i], &react[i + 1],
                    sizeof react[0] * (size_t)(nreact - i - 1));
            nreact--;
            if (kind == 'S')
                racecoordinator_send_message(rc, a, b);
            else if (kind == 'P')
                racecoordinator_post_message(rc, a, b);
            else if (kind == 'C')
                racecoordinator_change_state(rc, a);
            else if (kind == 'E')
                racecoordinator_execute_queued_messages(rc);
            return;
        }
    }
}

static int32_t callback(int state, RaceCoordinator *rc, RCMessage msg,
                        int32_t param)
{
    printf("  cb %d %d %d this=%s st=%d ex=%d bp=%d port=%d q=%s\n", state,
           (int)msg, (int)param, nm(rc), (int)rc->CurrentRCState,
           (int)rc->RCExecutingMessage, (int)rc->BeforePauseRCState,
           (int)rc->PausedJoystickPort, queue_str(rc));
    respond(state, rc, msg);
    return 1;
}

#define CB(n)                                                              \
    static int32_t cb##n(RaceCoordinator *rc, RCMessage m, int32_t p)      \
    {                                                                      \
        return callback(n, rc, m, p);                                      \
    }
CB(4) CB(5) CB(8) CB(9)

// -------------------------------------------------------------- the dump

static void dump(void)
{
    const RaceCoordinator *rc = &rcbuf;
    const unsigned char *ds =
        (const unsigned char *)&RaceParametersGlobalDisplaySettings;
    uint32_t jb;
    int i;

    printf("  rc st=%d ex=%d cd=%d port=%d bp=%d demo=%s fly=%s pre=%s "
           "eg=%s pn=%d q%s\n",
           (int)rc->CurrentRCState, (int)rc->RCExecutingMessage,
           (int)rc->DisplayingCountdownNumber, (int)rc->PausedJoystickPort,
           (int)rc->BeforePauseRCState, nm(rc->pDemoCameraCoordinator),
           nm(rc->pFlyByCameraCoordinator),
           nm(rc->pPreRaceCameraCoordinator), nm(rc->pEndGameScreens),
           (int)rc->PostRacePlayerNumber, queue_str(rc));
    memcpy(&jb, &jbTimer, 4);
    printf("  g stage=%d go=%d cdt=%d nrc=%d np=%d wtf=%d jbt=%s begun=%d "
           "ds=",
           (int)raceObj.RaceStage, (int)raceObj.StartGoTimeFrames,
           (int)raceObj.StartCountdownTimeFrames,
           (int)raceObj.NumRacingCars, (int)PlayerNumPlayers,
           (int)WorldTimeFrames, fx(jbTimer), (int)begun);
    for (i = 0; i < 8; i++)
        printf("%02x", ds[i]);
    printf(" vis=%d,%d,%d jt=%d,%d\n", flobj[0][OBJ_VIS], flobj[1][OBJ_VIS],
           flobj[2][OBJ_VIS], (int)players[0].JoyType,
           (int)players[1].JoyType);
    printf("  rcars");
    for (i = 0; i < NRC; i++)
        printf(" %d/%d", (int)rcars[i].FinishReason,
               (int)rcars[i].RacePosition);
    printf("\n");
}

// --------------------------------------------------------------- the ops

static void reset(void)
{
    int i;
    uint32_t jb = JB_START;

    nobj = 0;
    memset(slotUsed, 0, sizeof slotUsed);
    memset(&rcbuf, PATTERN, sizeof rcbuf);
    rcbuf.CurrentRCState = RCSTATE_NONE;
    rcbuf.RCQueuedMessageList.next = &rcbuf.RCQueuedMessageList;
    rcbuf.RCQueuedMessageList.prev = &rcbuf.RCQueuedMessageList;
    rcbuf.RCExecutingMessage = 0;
    rcbuf.DisplayingCountdownNumber = 0;
    rcbuf.PausedJoystickPort = 0;
    rcbuf.BeforePauseRCState = 0;
    rcbuf.pDemoCameraCoordinator = NULL;
    rcbuf.pFlyByCameraCoordinator = NULL;
    rcbuf.pPreRaceCameraCoordinator = NULL;
    rcbuf.pEndGameScreens = NULL;
    rcbuf.PostRacePlayerNumber = 0;
    memset(fly, 0, sizeof fly);
    memset(pre, 0, sizeof pre);
    memset(demo, 0, sizeof demo);
    memset(eg, 0, sizeof eg);
    {
        int32_t one = 1;

        memcpy(pre + PRE_FINISHED, &one, 4);
    }
    memset(&raceObj, PATTERN, sizeof raceObj);
    raceObj.RaceStage = RACE_STAGE_NONE;
    raceObj.StartGoTimeFrames = 0;
    raceObj.StartCountdownTimeFrames = 0;
    raceObj.NumRacingCars = 0;
    memset(rcars, PATTERN, sizeof rcars);
    for (i = 0; i < NRC; i++)
        raceObj.pRacingCars[i] = &rcars[i];
    memset(players, PATTERN, sizeof players);
    for (i = 0; i < 2; i++) {
        players[i].MyCar = NULL;
        players[i].TimeFinishedRacing = 0;
        players[i].FinishAnimationLength = 0;
        players[i].JoyPort = i;
        players[i].JoyType = 0;
        players[i].PlayerNumber = i;
        PlayerPlayersByIndex[i] = &players[i];
        PlayerPlayersByNumber[i] = NULL;
    }
    PlayerNumPlayers = 0;
    memset(&worldObj, PATTERN, sizeof worldObj);
    worldObj.CarList.next = worldObj.CarList.prev = &worldObj.CarList;
    memset(cars, PATTERN, sizeof cars);
    for (i = 0; i < NCAR; i++)
        cars[i].pAnimatedDriver = NULL;
    for (i = 0; i < NCAR; i++)
        worldObj.CarTable[i] = &cars[i];
    memset(tse, PATTERN, sizeof tse);
    memset(tsPresent, 0, sizeof tsPresent);
    WorldLoopCounter = 0;
    ThePauseMenu = (struct PauseMenu *)(void *)menu;
    memset(CurrentJoystickTypes, 0, sizeof CurrentJoystickTypes);
    begun = 0;
    memset(flobj, PATTERN, sizeof flobj);
    for (i = 0; i < 3; i++)
        flobj[i][OBJ_VIS] = 0;
    memset(&fedDS, 0, sizeof fedDS);
    memset(&RaceParametersGlobalDisplaySettings, 0,
           sizeof RaceParametersGlobalDisplaySettings);
    pRaceCoordinator = &rcbuf;
    pCurrentRace = &raceObj;
    pCurrentWorld = &worldObj;
    pReplayManager = &rmObj;
    RCQueuedMessageSlotPool = &fakePool;
    WorldTimeFrames = 0;
    memcpy(&jbTimer, &jb, 4);
    RaceParametersNumPlayerCars = 1;
    RaceParametersBeACop = 0;
    tFlyFin = 1;
    tPFin = 1;
    tPrerace = 0;
    tPlaying = 0;
    tNoSample = 0;
    tNoObj = 0;
    tAnother = 0;
    tMulti = 0;
    tFcDrop = 0;
    tRDrop = 0;
    tInitState = -1;
    tRmMute = 0;
    tHlEnd = 0;
    nreact = 0;
}

static void set_global(const char *f, int v)
{
    if (!strcmp(f, "state"))
        rcbuf.CurrentRCState = v;
    else if (!strcmp(f, "exec"))
        rcbuf.RCExecutingMessage = v;
    else if (!strcmp(f, "port"))
        rcbuf.PausedJoystickPort = v;
    else if (!strcmp(f, "bp"))
        rcbuf.BeforePauseRCState = v;
    else if (!strcmp(f, "beacop"))
        RaceParametersBeACop = v;
    else if (!strcmp(f, "nplaycars"))
        RaceParametersNumPlayerCars = v;
    else if (!strcmp(f, "wtf"))
        WorldTimeFrames = v;
    else if (!strcmp(f, "stage"))
        raceObj.RaceStage = v;
    else if (!strcmp(f, "go"))
        raceObj.StartGoTimeFrames = v;
    else if (!strcmp(f, "cdt"))
        raceObj.StartCountdownTimeFrames = v;
    else if (!strcmp(f, "nrc"))
        raceObj.NumRacingCars = v;
    else if (!strcmp(f, "np"))
        PlayerNumPlayers = v;
    else if (!strcmp(f, "begun"))
        begun = v;
    else if (!strcmp(f, "rmmute"))
        tRmMute = v;
    else if (!strcmp(f, "hlend"))
        tHlEnd = v;
    else if (!strcmp(f, "wlc"))
        WorldLoopCounter = v;
    else if (!strcmp(f, "pn"))
        rcbuf.PostRacePlayerNumber = v;
    else if (!strcmp(f, "jt0"))
        CurrentJoystickTypes[0] = (uint8_t)v;
    else if (!strcmp(f, "jt1"))
        CurrentJoystickTypes[1] = (uint8_t)v;
    else if (!strcmp(f, "menu"))
        ThePauseMenu = v ? (struct PauseMenu *)(void *)menu : NULL;
    else if (!strcmp(f, "flyfin"))
        tFlyFin = v;
    else if (!strcmp(f, "pfin")) {
        tPFin = v;
        if (rcbuf.pPreRaceCameraCoordinator != NULL)
            memcpy((unsigned char *)rcbuf.pPreRaceCameraCoordinator
                       + PRE_FINISHED, &v, 4);
    } else if (!strcmp(f, "prerace"))
        tPrerace = v;
    else if (!strcmp(f, "playing"))
        tPlaying = v;
    else if (!strcmp(f, "nosample"))
        tNoSample = v;
    else if (!strcmp(f, "noobj"))
        tNoObj = v;
    else if (!strcmp(f, "another"))
        tAnother = v;
    else if (!strcmp(f, "multi"))
        tMulti = v;
    else if (!strcmp(f, "fcdrop"))
        tFcDrop = v;
    else if (!strcmp(f, "rdrop"))
        tRDrop = v;
    else if (!strcmp(f, "initstate"))
        tInitState = v;
    else if (!strcmp(f, "vis3"))
        flobj[0][OBJ_VIS] = (unsigned char)v;
    else if (!strcmp(f, "vis2"))
        flobj[1][OBJ_VIS] = (unsigned char)v;
    else if (!strcmp(f, "vis1"))
        flobj[2][OBJ_VIS] = (unsigned char)v;
    else if (!strcmp(f, "fly"))
        rcbuf.pFlyByCameraCoordinator = v ? fly : NULL;
    else if (!strcmp(f, "pre")) {
        rcbuf.pPreRaceCameraCoordinator = v ? pre : NULL;
        if (v)
            memcpy(pre + PRE_FINISHED, &tPFin, 4);
    } else if (!strcmp(f, "demo"))
        rcbuf.pDemoCameraCoordinator = v ? demo : NULL;
    else if (!strcmp(f, "eg"))
        rcbuf.pEndGameScreens = v ? (struct EndGameScreens *)(void *)eg
                                  : NULL;
    else {
        fprintf(stderr, "bad global %s\n", f);
        exit(2);
    }
}

static int ints(char *s, int *out, int max)
{
    int n = 0;
    char *t;

    while (n < max && (t = strtok(s, " \t\r\n")) != NULL) {
        out[n++] = (int)strtol(t, NULL, 0);
        s = NULL;
    }
    return n;
}

static void op(char *line)
{
    char c[8] = {0}, f[32] = {0};
    int n[32], k;
    char *rest;
    RaceCoordinator *rc = &rcbuf;

    if (sscanf(line, "%7s", c) != 1)
        return;
    rest = line + strlen(c);
    if (!strcmp(c, "S")) {
        int v;

        if (sscanf(rest, "%31s %i", f, &v) != 2) {
            fprintf(stderr, "bad S\n");
            exit(2);
        }
        set_global(f, v);
        return;
    }
    if (!strcmp(c, "R")) {
        char kind;

        if (nreact >= NREACT) {
            fprintf(stderr, "reactions full\n");
            exit(2);
        }
        if (sscanf(rest, "%d %d %c %d %d", &react[nreact].state,
                   &react[nreact].msg, &kind, &react[nreact].a,
                   &react[nreact].b) != 5) {
            fprintf(stderr, "bad R\n");
            exit(2);
        }
        react[nreact++].kind = kind;
        return;
    }
    k = ints(rest, n, 32);
    if (!strcmp(c, "PL")) {
        players[n[0]].TimeFinishedRacing = (uint32_t)n[1];
        players[n[0]].FinishAnimationLength = (uint32_t)n[2];
        players[n[0]].MyCar = n[3] >= 0 ? &cars[n[3]] : NULL;
        return;
    }
    if (!strcmp(c, "K")) {
        rcars[n[0]].FinishReason = (int16_t)n[1];
        rcars[n[0]].RacePosition = (int8_t)n[2];
        return;
    }
    if (!strcmp(c, "WL")) {
        World *w = &worldObj;
        int i;

        w->CarList.next = w->CarList.prev = &w->CarList;
        for (i = 0; i < k; i++) {
            Car *car = &cars[n[i]];
            CarNode *tail = (CarNode *)w->CarList.prev;

            car->Link.prev = tail;
            car->Link.next = (CarNode *)(void *)&w->CarList;
            tail->next = &car->Link;
            w->CarList.prev = car;
        }
        return;
    }
    if (!strcmp(c, "PJ")) {
        players[n[0]].JoyPort = n[1];
        players[n[0]].JoyType = n[2];
        players[n[0]].PlayerNumber = n[3];
        return;
    }
    if (!strcmp(c, "TS")) {
        tse[n[0]].FinishPosition = n[1];
        tse[n[0]].UniqueDriveNumber = n[0];
        tsPresent[n[0]] = n[2];
        return;
    }
    if (!strcmp(c, "AD")) {
        cars[n[0]].pAnimatedDriver =
            n[1] ? (struct AnimatedDriver *)(void *)ads[n[0]] : NULL;
        return;
    }
    if (!strcmp(c, "FD")) {
        unsigned char *b = (unsigned char *)&fedDS;
        int i;

        for (i = 0; i < 8 && i < k; i++)
            b[i] = (unsigned char)n[i];
        return;
    }

    if (!strcmp(c, "M")) {
        racecoordinator_send_message(rc, n[0], n[1]);
    } else if (!strcmp(c, "P")) {
        racecoordinator_post_message(rc, n[0], n[1]);
    } else if (!strcmp(c, "E")) {
        racecoordinator_execute_queued_messages(rc);
    } else if (!strcmp(c, "T")) {
        racecoordinator_change_state(rc, n[0]);
    } else if (!strcmp(c, "C")) {
        static const RCStateCallbackFn real[NUM_RCSTATES] = {
            [RCSTATE_NONE] = rc_state_none_callback,
            [RCSTATE_CAMERA_FLYBY] = rc_state_camera_flyby_callback,
            [RCSTATE_PRERACE] = rc_state_prerace_callback,
            [RCSTATE_RACE_IN_PROGRESS] = rc_state_race_in_progress_callback,
            [RCSTATE_PAUSE] = rc_state_pause_callback,
            [RCSTATE_POSTRACE] = rc_state_post_race_callback};

        printf("  ret %d\n", (int)real[n[0]](rc, n[1], n[2]));
    } else if (!strcmp(c, "DN")) {
        racecoordinator_display_countdown_number(rc, n[0]);
    } else if (!strcmp(c, "RF")) {
        racecoordinator_the_race_has_finished(rc);
    } else if (!strcmp(c, "J")) {
        racecoordinator_joystick_handler(0, n[0], 0, NULL);
    } else if (!strcmp(c, "RP")) {
        racecoordinator_request_pause(rc, n[0]);
    } else if (!strcmp(c, "RU")) {
        racecoordinator_request_unpause(rc, n[0]);
    } else if (!strcmp(c, "DR")) {
        racecoordinator_resume_demo_cameras(rc);
    } else if (!strcmp(c, "DS")) {
        racecoordinator_suspend_demo_cameras(rc);
    } else if (!strcmp(c, "GN")) {
        printf("  number %d\n",
               (int)race_get_countdown_number_to_display(&raceObj));
    } else if (!strcmp(c, "GP")) {
        printf("  progress %s\n", fx(race_get_countdown_progress(&raceObj)));
    } else if (!strcmp(c, "SIM")) {
        race_simulate_race_finish(&raceObj);
    } else if (!strcmp(c, "NOT")) {
        race_notify_the_race_is_over(&raceObj);
    } else if (!strcmp(c, "AA")) {
        printf("  allfin %d\n",
               (int)race_are_all_players_finished_racing(&raceObj));
    } else if (!strcmp(c, "MR")) {
        printf("  recent %s\n",
               nm(race_get_most_recently_finished_player(&raceObj)));
    } else {
        fprintf(stderr, "bad op %s\n", c);
        exit(2);
    }
    dump();
}

int main(int argc, char **argv)
{
    static char line[512];
    FILE *fp;

    if (argc < 2) {
        fprintf(stderr, "usage: rcstates_test SCRIPT\n");
        return 2;
    }

    gSoundMuteFn = s_mute;
    gFEDSetupNextRaceFn = s_setup_next;
    gFEDSetRecordTimesToBeatFn = s_records;
    gFEDCheckForAbortionFn = s_abort_check;
    gFEDTheRaceIsOverFn = s_race_over;
    gFEDIsThereAnotherRaceFn = s_another;
    gFEDIsMultiTrackFn = s_multi;
    gFEDGlobalDisplaySettings = &fedDS;
    gJukeboxDelayedStartFn = s_delayed;
    gJukeboxDelayedStartTimer = &jbTimer;
    gChangeGameFlowFn = s_flow;
    gFlyByCameraCoordinatorCtorFn = s_fly_ctor;
    gPreRaceCameraCoordinatorCtorFn = s_pre_ctor;
    gDemoCameraCoordinatorCtorFn = s_demo_ctor;
    gFlyByCameraIsFinishedFn = s_fly_finished;
    gPreRaceCameraIsFinishedFn = s_pre_finished;
    gEnableStartRaceScreensFn = s_srs_on;
    gDisableStartRaceScreensFn = s_srs_off;
    gAnimatedDriverCancelAllAnimationsFn = s_cancel;
    gFindResourceFileByNameFn = s_find;
    gUnloadResourceFileFn = s_unload;
    gReplayGetBeginningOfTimeFn = s_begun;
    gReplayMarkTheBeginningOfTimeFn = s_mark_begin;
    gReplayMarkTheEndOfTimeFn = s_mark_end;
    gPlayerBeginDemoCamerasFn = s_democams;
    gEndGameScreensCtorFn = s_endgame;
    gGetInGameSampleFn = s_sample;
    gSampleIsPlayingFn = s_is_playing;
    gSamplePlayFn = s_play;
    gSetFlailerScreenVisibilityFn = s_screen;
    gFindFlailerObjectFn = s_find_obj;
    gFlailerObjectVisibilityFn = s_obj_vis;
    gFlailerSetVisibilityFn = s_set_vis;
    gFlailerSetAlphaFn = s_alpha;
    gFlailerScaleAboutCenterFn = s_scale;
    gCameraCoordinatorDeleteFn = s_ccdel;
    gRaceFinishCarFn = s_finish_car;
    gRaceEventRecordResultsFn = s_record;
    gPlayerClearHudAnimationsFn = s_hud_clear;
    gPauseMenuEnterPauseFn = s_enter_pause;
    gPauseMenuExitPauseFn = s_exit_pause;
    gChangeToScreenFn = s_to_screen;
    gFEDTheRaceWasQuitFn = s_quit;
    gFEDTheRaceWasRestartedFn = s_restarted;
    gSpeechFlushQueueFn = s_flush;
    gSoundMuteReplayFn = s_mute_replay;
    gReplayBeginRaceHighlightsFn = s_highlights;
    gReplayBeginNextRaceHighlightFn = s_next_highlight;
    gReplayMuteHighlightsFn = s_mute_highlights;
    gReplayEndCurrentHighlightTimeFn = s_highlight_end;
    gEndGameScreensResumeFn = s_resume;
    gEndGameScreensSuspendFn = s_suspend;
    gTransientStatsGetDriverFn = s_get_driver;
    gRestoreTypeChangedHandlersFn = s_type_handlers;
    gRCStateCallbacks[4] = cb4;
    gRCStateCallbacks[5] = cb5;
    gRCStateCallbacks[8] = cb8;
    gRCStateCallbacks[9] = cb9;

    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    while (fgets(line, sizeof line, fp)) {
        size_t len = strlen(line);

        while (len && (line[len - 1] == '\n' || line[len - 1] == '\r'))
            line[--len] = 0;
        if (!len)
            continue;
        if (line[0] == 'B' && line[1] == ' ') {
            printf("%s\n", line);
            reset();
            continue;
        }
        printf("> %.40s\n", line);
        op(line);
    }
    fclose(fp);
    return 0;
}
