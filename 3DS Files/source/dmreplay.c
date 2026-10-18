// dmreplay -- see dmreplay.h.

#include "dmreplay.h"

#include <stddef.h>

#include "bchunk.h"
#include "bfile.h"
#include "bmath.h"
#include "bprintf.h"
#include "p32.h"
#include "race.h"
#include "racecoord.h"
#include "raceparams.h"
#include "realtime.h"
#include "replaymgr.h"
#include "replayscreen.h"
#include "resource.h"
#include "timer.h"
#include "trackflow.h"

DemoModeReplay TheDemoModeReplay = { .TweakerSnapshotFileNumber = -1 };

void (*gDemoModeReplaySaveFn)(void);
void (*gDemoModeReplayRefreshTweakerFn)(void);

// DemoModeReplayFilenames (0x002f0948).
static const char *const DemoModeReplayFilenames[DEMO_MODE_REPLAY_NUM_FILES] = {
    "REPLAY0.BIN",
    "JUL23\\T33GoldVanquish.bin",
    "JUL23\\T12YellowSpider.bin",
    "JUL23\\T62OrangeF1LM.bin",
    "JUL23\\T43GreenM5.bin",
    "JUL23\\T11BlueElise.bin",
};

// The chunks' types.
#define CHUNK_INFO      0x00039100u
#define CHUNK_SNAPSHOT  0x00039101u
#define CHUNK_REPEAT    0x00039102u

// gp-31496: a WorldTimer tick in seconds.
#define SECONDS_PER_TICK 0.00025f

// Retail's addu and subu, which wrap.
static int32_t add32(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a + (uint32_t)b);
}

static int32_t sub32(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a - (uint32_t)b);
}

// ---------------------------------------------------------------- the list
//
// ReplaySnapshotList (+56), a bTList<ReplaySnapshot>: replaymgr.c's
// ReplayLink, two p32 words, on DemoModeReplay_SnapshotList.

typedef struct ReplayLink {
    uint32_t Next;
    uint32_t Prev;
} ReplayLink;

static ReplayLink *link_at(uint32_t h)
{
    return (ReplayLink *)p32_ptr(h);
}

static void list_init(ReplayLink *l)
{
    l->Next = p32_of(l);
    l->Prev = p32_of(l);
}

// Made empty at the first use, as replaymgr.c's.
static ReplayLink *demo_list(void)
{
    ReplayLink *l = (ReplayLink *)(void *)DemoModeReplay_SnapshotList;

    if (l->Next == 0 && l->Prev == 0)
        list_init(l);
    return l;
}

static void list_add_tail(ReplayLink *l, ReplayLink *n)
{
    ReplayLink *tail = link_at(l->Prev);

    tail->Next = p32_of(n);
    l->Prev = p32_of(n);
    n->Prev = p32_of(tail);
    n->Next = p32_of(l);
}

// bList::TraversebList (0x00250428): whether `n` is on `l`.
static int32_t list_has(ReplayLink *l, ReplayLink *n)
{
    ReplayLink *a;

    for (a = link_at(l->Next); a != l; a = link_at(a->Next))
        if (a == n)
            return 1;
    return 0;
}

static void list_unlink(ReplayLink *n)
{
    ReplayLink *next = link_at(n->Next);
    ReplayLink *prev = link_at(n->Prev);

    prev->Next = n->Next;
    next->Prev = n->Prev;
}

// ------------------------------------------------------------ the manager
//
// Retail calls the manager and the coordinator with no test: the demo only
// runs in a race. The port answers "none" without them.

static ReplaySnapshot *find_demo(int32_t k)
{
    if (pReplayManager == NULL)
        return NULL;
    return replaymgr_find_snapshot(pReplayManager, DEMO_MODE_SNAPSHOT_NAME, k);
}

static ReplaySnapshot *take(const char *name)
{
    if (pReplayManager == NULL)
        return NULL;
    return replaymgr_take_snapshot(pReplayManager, name);
}

static int32_t delete_named(const char *name)
{
    if (pReplayManager == NULL)
        return 0;
    return replaymgr_delete_snapshot_named(pReplayManager, name);
}

static void delete_snapshot(ReplaySnapshot *s)
{
    if (pReplayManager != NULL)
        replaymgr_delete_snapshot(pReplayManager, s);
}

static void refresh_tweaker(void)
{
    if (gDemoModeReplayRefreshTweakerFn != NULL)
        gDemoModeReplayRefreshTweakerFn();
}

// --------------------------------------------------------------- the object

void dmreplay_construct(void)
{
    DemoModeReplay *d = &TheDemoModeReplay;

    d->TweakerSnapshotFileNumber = -1;
    list_init((ReplayLink *)(void *)DemoModeReplay_SnapshotList);
    DemoModeReplayActiveFlag = 0;
    d->LoadingFlag = 0;
    d->LoadedFlag = 0;
    d->CurrentSnapshotFileNumber = 0;
    d->WantToBeRecordingSnapshot = 0;
    DemoModeReplay_WantToBeErasingSnapshot = 0;
    DemoModeReplay_pCurrentRecordingSnapshot = NULL;
    DemoModeReplay_pCurrentPlayingSnapshot = NULL;
    d->TweakerSaveSnapshotFile = 0;
    d->TweakerEraseRecordedSnapshots = 0;
    d->pInfo = NULL;
    DemoModeReplay_pRepeat = 0;
}

int dmreplay_loader(uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);

    if (type == CHUNK_INFO) {
        TheDemoModeReplay.pInfo = (const DemoModeReplayInfo *)(chunk + 8);
        return 1;
    }
    if (type == CHUNK_SNAPSHOT) {
        ReplaySnapshot *s = (ReplaySnapshot *)(void *)(chunk + 8);

        s->MemoryImageLoadedFlag = 1;
        list_add_tail(demo_list(), (ReplayLink *)(void *)s);
        return 1;
    }
    if (type == CHUNK_REPEAT) {
        DemoModeReplay_pRepeat = p32_of(chunk + 8);
        return 1;
    }
    return 0;
}

int dmreplay_unloader(uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);

    if (type == CHUNK_INFO) {
        TheDemoModeReplay.pInfo = NULL;
        return 1;
    }
    if (type == CHUNK_SNAPSHOT) {
        ReplayLink *n = (ReplayLink *)(void *)(chunk + 8);

        if (list_has(demo_list(), n))
            list_unlink(n);
        return 1;
    }
    if (type == CHUNK_REPEAT) {
        DemoModeReplay_pRepeat = 0;
        return 1;
    }
    return 0;
}

const char *dmreplay_get_base_filename(int32_t i)
{
    if ((uint32_t)i >= DEMO_MODE_REPLAY_NUM_FILES)
        i = 0;
    return DemoModeReplayFilenames[i];
}

void dmreplay_generate_filename(char *out, int32_t i)
{
    if (dmreplay_get_base_filename(i)[0] == 0) {
        out[0] = 0;
        return;
    }
    b_snprintf(out, DEMO_MODE_REPLAY_FILENAME_SIZE, "REPLAY\\%s",
               dmreplay_get_base_filename(i));
}

void dmreplay_resource_file_loaded_callback(intptr_t param)
{
    (void)param;
    TheDemoModeReplay.LoadingFlag = 0;
    TheDemoModeReplay.LoadedFlag = 1;
}

void dmreplay_load_resource_file(void)
{
    char name[DEMO_MODE_REPLAY_FILENAME_SIZE];

    TheDemoModeReplay.LoadingFlag = 1;
    dmreplay_generate_filename(name,
                               TheDemoModeReplay.CurrentSnapshotFileNumber);
    load_resource_file(name, RESOURCE_FILE_REPLAY, 0,
                       dmreplay_resource_file_loaded_callback,
                       (intptr_t)&TheDemoModeReplay);
}

void dmreplay_unload_resource_file(void)
{
    ResourceFile *rf;

    if (!TheDemoModeReplay.LoadedFlag)
        return;
    while ((rf = find_resource_file_by_type(RESOURCE_FILE_REPLAY)) != NULL)
        unload_resource_file(rf);
    TheDemoModeReplay.LoadedFlag = 0;
}

// Retail first asks TheDemoDiscManager (0x002effe0), whose bActive is
// always 0 on the retail disc; the port leaves the demo disc out.
int32_t dmreplay_consider_launching(void)
{
    DemoModeReplay *d = &TheDemoModeReplay;
    char name[DEMO_MODE_REPLAY_FILENAME_SIZE];

    if (d->CurrentSnapshotFileNumber != 0)
        d->CurrentSnapshotFileNumber = add32(d->CurrentSnapshotFileNumber, 1);
    else
        d->CurrentSnapshotFileNumber = add32(bRandomI(5, &bDefaultSeed), 1);
    if (d->TweakerSnapshotFileNumber >= 0)
        d->CurrentSnapshotFileNumber = d->TweakerSnapshotFileNumber;
    if (d->CurrentSnapshotFileNumber >= DEMO_MODE_REPLAY_NUM_FILES)
        d->CurrentSnapshotFileNumber = 1;
    dmreplay_generate_filename(name, d->CurrentSnapshotFileNumber);
    if (name[0] == 0 || bFileSizeName(name) < 0)
        return 0;
    dmreplay_load_resource_file();
    return 1;
}

// Retail's GenerateFilename here is unused, and it reads pInfo with no
// test; the port takes no info as a bad one.
void dmreplay_launch(void)
{
    const DemoModeReplayInfo *info = TheDemoModeReplay.pInfo;

    if (info != NULL && info->VersionNumber == 8 && info->New8 == 1)
        DemoModeReplayActiveFlag = info->New8;
    else
        dmreplay_unload_resource_file();
}

// Retail reads the list's first with no test; the port does nothing with
// none.
void dmreplay_restore_race_parameters_snapshot(void)
{
    ReplayLink *l = demo_list();
    ReplaySnapshot *s;

    if (link_at(l->Next) == l)
        return;
    s = (ReplaySnapshot *)(void *)link_at(l->Next);
    s->DataPosition = 0;
    s->RestoringSnapshotFlag = 1;
    race_parameters_init_with_defaults(&TheRaceParameters);
    race_parameters_do_snapshot(&TheRaceParameters, s);
    TheRaceParameters.ReplayDemoMode = 1;
    s->SizeofData = s->DataPosition;
    s->TakingSnapshotFlag = 0;
}

void dmreplay_begin_demo_mode(void)
{
    TheDemoModeReplay.PlayingSnapshotNumber = -1;
    if (pReplayManager != NULL)
        replaymgr_restore_snapshot_named(pReplayManager,
                                         REPLAY_MANAGER_STATE_NAME);
    dmreplay_service_demo_mode(1);
}

int32_t dmreplay_get_num_snapshots(void)
{
    return DEMO_MODE_REPLAY_NUM_FILES;
}

int32_t dmreplay_can_test_demo_mode(void)
{
    return find_demo(0) != NULL;
}

void dmreplay_begin_demo_mode_test(void)
{
    TheDemoModeReplay.PlayingSnapshotNumber = -1;
    dmreplay_service_demo_mode(1);
}

int32_t dmreplay_test_goes_on(void)
{
    ReplaySnapshot *s = DemoModeReplay_pCurrentPlayingSnapshot;
    float t;

    if (s != NULL && WorldLoopCounter >= s->EndLoopTime) {
        DemoModeReplay_pCurrentPlayingSnapshot = NULL;
        dmreplay_service_demo_mode(1);
        s = DemoModeReplay_pCurrentPlayingSnapshot;
        if (s == NULL)
            return 0;
    }
    if (!DemoModeReplay_WantToBeErasingSnapshot || s == NULL)
        return 1;
    t = (float)sub32(s->EndTime, s->Time) * SECONDS_PER_TICK;
    if (t < 2.0f) {
        delete_snapshot(DemoModeReplay_pCurrentPlayingSnapshot);
        TheDemoModeReplay.PlayingSnapshotNumber =
            sub32(TheDemoModeReplay.PlayingSnapshotNumber, 1);
        DemoModeReplay_pCurrentPlayingSnapshot = NULL;
    } else {
        Timer half;

        timer_set_time(&half, t * 0.5f);
        if (sub32(s->EndTime, (int32_t)half.PackedTime) < WorldTimer) {
            DemoModeReplay_pCurrentPlayingSnapshot->EndTime = WorldTimer;
            DemoModeReplay_pCurrentPlayingSnapshot->EndLoopTime =
                WorldLoopCounter;
            DemoModeReplay_pCurrentPlayingSnapshot = NULL;
        }
    }
    if (DemoModeReplay_pCurrentPlayingSnapshot != NULL)
        return 1;
    dmreplay_service_demo_mode(1);
    return 0;
}

void dmreplay_service_demo_mode(int32_t forward)
{
    DemoModeReplay *d = &TheDemoModeReplay;
    ReplaySnapshot *s;

    if (forward) {
        s = find_demo(add32(d->PlayingSnapshotNumber, 1));
        if (s == NULL)
            return;
        d->PlayingSnapshotNumber = add32(d->PlayingSnapshotNumber, 1);
    } else if (d->PlayingSnapshotNumber > 0) {
        s = find_demo(d->PlayingSnapshotNumber - 1);
        d->PlayingSnapshotNumber--;
    } else {
        s = find_demo(0);
    }
    if (s == NULL)
        return;
    DemoModeReplay_pCurrentPlayingSnapshot = s;
    if (pRaceCoordinator != NULL)
        racecoordinator_post_message(pRaceCoordinator, RC_MOVE_REPLAY,
                                     (int32_t)(intptr_t)s);
}

void dmreplay_end_demo_mode(void)
{
    DemoModeReplay_pCurrentPlayingSnapshot = NULL;
    DemoModeReplayActiveFlag = 0;
    TheDemoModeReplay.PlayingSnapshotNumber = 0;
}

void dmreplay_service(int32_t snapshot_this_loop)
{
    DemoModeReplay *d = &TheDemoModeReplay;

    if (snapshot_this_loop) {
        if (d->WantToBeRecordingSnapshot
            && DemoModeReplay_pCurrentRecordingSnapshot == NULL) {
            delete_named(REPLAY_MANAGER_STATE_NAME);
            take(REPLAY_MANAGER_STATE_NAME);
            DemoModeReplay_pCurrentRecordingSnapshot =
                take(DEMO_MODE_SNAPSHOT_NAME);
        }
        if (DemoModeReplay_WantToBeErasingSnapshot
            && DemoModeReplay_pCurrentPlayingSnapshot != NULL) {
            ReplaySnapshot *s = DemoModeReplay_pCurrentPlayingSnapshot;
            Timer three;

            timer_set_time(&three, 3.0f);
            if (WorldTimer < add32(s->Time, (int32_t)three.PackedTime)) {
                int32_t end_time = s->EndTime;
                int32_t end_loop = s->EndLoopTime;

                delete_snapshot(s);
                s = take(DEMO_MODE_SNAPSHOT_NAME);
                DemoModeReplay_pCurrentPlayingSnapshot = s;
                if (s != NULL) {
                    s->EndLoopTime = end_loop;
                    s->EndTime = end_time;
                }
                if (pReplayManager != NULL)
                    replaymgr_sort_snapshots(pReplayManager,
                                             DEMO_MODE_SNAPSHOT_NAME);
            }
        }
    }
    if (DemoModeReplay_pCurrentRecordingSnapshot != NULL) {
        DemoModeReplay_pCurrentRecordingSnapshot->EndLoopTime =
            WorldLoopCounter;
        DemoModeReplay_pCurrentRecordingSnapshot->EndTime = WorldTimer;
    }
    if (d->TweakerSaveSnapshotFile) {
        if (gDemoModeReplaySaveFn != NULL)
            gDemoModeReplaySaveFn();
        d->TweakerSaveSnapshotFile = 0;
        refresh_tweaker();
    }
    if (d->TweakerEraseRecordedSnapshots) {
        dmreplay_erase_recorded_snapshots();
        d->TweakerEraseRecordedSnapshots = 0;
        refresh_tweaker();
    }
}

void dmreplay_begin_recording_snapshot(void)
{
    TheDemoModeReplay.WantToBeRecordingSnapshot = 1;
}

void dmreplay_end_recording_snapshot(int32_t keep)
{
    ReplaySnapshot *s = DemoModeReplay_pCurrentRecordingSnapshot;

    (void)keep;
    TheDemoModeReplay.WantToBeRecordingSnapshot = 0;
    if (s == NULL)
        return;
    if (sub32(WorldLoopCounter, s->BeginLoopTime) < 31)
        delete_snapshot(s);
    DemoModeReplay_pCurrentRecordingSnapshot = NULL;
}

void dmreplay_erase_recorded_snapshots(void)
{
    while (delete_named(DEMO_MODE_SNAPSHOT_NAME))
        ;
    delete_named(REPLAY_MANAGER_STATE_NAME);
    DemoModeReplay_pCurrentPlayingSnapshot = NULL;
    TheDemoModeReplay.WantToBeRecordingSnapshot = 0;
    DemoModeReplay_pCurrentRecordingSnapshot = NULL;
}
