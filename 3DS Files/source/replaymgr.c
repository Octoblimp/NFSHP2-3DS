// replaymgr -- see replaymgr.h.

#include "replaymgr.h"

#include <stdio.h>
#include <string.h>

#include "bmem.h"
#include "brepeat.h"
#include "joyevent.h"
#include "joylog.h"
#include "p32.h"
#include "race.h"
#include "racecoord.h"
#include "raceparams.h"
#include "realtime.h"
#include "timer.h"
#include "trackflow.h"

uint32_t DemoModeReplay_pRepeat;
uint32_t DemoModeReplay_SnapshotList[2];

int32_t ChecksumSnapshotTimes[4] = { -1, -1, -1, -1 };

void (*gReplayHandleSpecialEventFn)(const ReplaySpecialEventInfo *e);
void (*gDemoModeReplayServiceFn)(int32_t snapshot_this_loop);

#define REPLAY_POOL      16
#define REPLAY_LOG_SIZE  0x32000
// What MarkTheBeginningOfTime wants free past 32 KB: the log and seventeen
// snapshots, 0xd0ad8 bytes.
#define REPLAY_MIN_FREE  0xd0ad8

// ---------------------------------------------------------------- the lists
//
// A bTList<ReplaySnapshot>'s head and a snapshot's bNode are both two
// words, Next and Prev, as p32 handles. ReplayLink is that shape.

typedef struct ReplayLink {
    uint32_t Next;
    uint32_t Prev;
} ReplayLink;

static ReplayLink *link_at(uint32_t h)
{
    return (ReplayLink *)p32_ptr(h);
}

static ReplayLink *snap_link(ReplaySnapshot *s)
{
    return (ReplayLink *)(void *)s;
}

static ReplaySnapshot *link_snap(ReplayLink *n)
{
    return (ReplaySnapshot *)(void *)n;
}

static ReplayLink *free_list(ReplayManager *rm)
{
    return (ReplayLink *)(void *)rm->FreeReplaySnapshotList;
}

static ReplayLink *snap_list(ReplayManager *rm)
{
    return (ReplayLink *)(void *)rm->ReplaySnapshotList;
}

static void list_init(ReplayLink *l)
{
    l->Next = p32_of(l);
    l->Prev = p32_of(l);
}

static void list_unlink(ReplayLink *n)
{
    ReplayLink *next = link_at(n->Next);
    ReplayLink *prev = link_at(n->Prev);

    prev->Next = n->Next;
    next->Prev = n->Prev;
}

static void list_add_tail(ReplayLink *l, ReplayLink *n)
{
    ReplayLink *tail = link_at(l->Prev);

    tail->Next = p32_of(n);
    l->Prev = p32_of(n);
    n->Prev = p32_of(tail);
    n->Next = p32_of(l);
}

// bList::AddTail(bList *) (0x00250458): every node of `other`, in order, to
// the end of `l`, and `other` left empty.
static void list_append(ReplayLink *l, ReplayLink *other)
{
    ReplayLink *first = link_at(other->Next);
    ReplayLink *last;
    ReplayLink *tail;

    if (first == other)
        return;
    last = link_at(other->Prev);
    tail = link_at(l->Prev);
    last->Next = p32_of(l);
    first->Prev = p32_of(tail);
    tail->Next = p32_of(first);
    l->Prev = p32_of(last);
    other->Prev = p32_of(other);
    other->Next = p32_of(other);
}

// 0x0013e678, the sort's order: a may stay in front of b.
static int32_t in_begin_loop_order(ReplayLink *a, ReplayLink *b)
{
    return link_snap(a)->BeginLoopTime <= link_snap(b)->BeginLoopTime;
}

// bList::Sort (0x00250550), blist.h's bubble sort, on the snapshots' p32
// links: each pass walks a and the node b after it, and a b out of order
// goes back in front of a; the passes repeat until one moves nothing.
static void list_sort(ReplayLink *l)
{
    int32_t moved;

    do {
        ReplayLink *a = link_at(l->Next);
        ReplayLink *b;

        moved = 0;
        if (a == l)
            break;
        for (b = link_at(a->Next); b != l; b = link_at(a->Next)) {
            if (in_begin_loop_order(a, b)) {
                a = b;
            } else {
                ReplayLink *prev;

                moved = 1;
                list_unlink(b);
                prev = link_at(a->Prev);
                prev->Next = p32_of(b);
                a->Prev = p32_of(b);
                b->Prev = p32_of(prev);
                b->Next = p32_of(a);
            }
        }
    } while (moved);
}

// TheDemoModeReplay's snapshots, made empty at the first use.
static ReplayLink *demo_list(void)
{
    ReplayLink *l = (ReplayLink *)(void *)DemoModeReplay_SnapshotList;

    if (l->Next == 0 && l->Prev == 0)
        list_init(l);
    return l;
}

// A new snapshot at the free list's end. Its constructor clears only Time
// and EndTime; Init does the rest when it is taken.
static void new_free_snapshot(ReplayManager *rm)
{
    ReplaySnapshot *s = bMalloc((int)sizeof(ReplaySnapshot),
                                "ReplaySnapshot", 0, REPLAY_POOL);

    s->Time = 0;
    s->EndTime = 0;
    list_add_tail(free_list(rm), snap_link(s));
}

// The free list's first snapshot moved to the end of the snapshots, a new
// one made when there is none, and named.
static ReplaySnapshot *use_free_snapshot(ReplayManager *rm, const char *name)
{
    ReplaySnapshot *s;

    if (link_at(free_list(rm)->Next) == free_list(rm))
        new_free_snapshot(rm);
    s = link_snap(link_at(free_list(rm)->Next));
    list_unlink(snap_link(s));
    list_add_tail(snap_list(rm), snap_link(s));
    ReplaySnapshot_Init(s, name);
    return s;
}

// ----------------------------------------------------- making and unmaking

// 0x0013d448. The demo's snapshots move over whole: bList::AddTail.
ReplayManager *replaymgr_construct(void *mem)
{
    ReplayManager *rm = mem;
    int32_t n;

    list_init(free_list(rm));
    list_init(snap_list(rm));
    rm->LastSnapshotTime = -1;
    rm->LapSnapshotSpacing = 15.0f;
    rm->NextFancyDebugTime = 9999999;
    rm->BeginCapturingLoopCount = -1;
    rm->EndCapturingLoopCount = -1;
    rm->ReplayingFlag = 0;
    rm->CapturingFlag = 0;
    rm->RemoveDataError = 0;
    rm->MuteHighlightSoundFlag = 0;
    rm->PausedFlag = 0;
    rm->SlowMotionFlag = 0;
    rm->ReplayPausedThisFrame = 0;
    rm->FinishedAllCapturing = 0;
    rm->BeginningOfTime = 0;
    rm->EndOfTime = 0;
    rm->NextInstantReplaySnapshotTime = 0;
    rm->NumSnapshotsTaken = 0;
    rm->SnapshotTimeCursor = 0;
    rm->FancyReplayInProgress = 0;
    rm->FancyJoyEventNumber = 0;
    rm->NumFancyJoyEvents = 0;
    rm->pRepeat = 0;
    rm->MaxNumSnapshots = 0;
    rm->MaxNumInstantReplaySnapshots = 0;
    rm->MaxNumLapSnapshots = 0;
    rm->MaxNumHighlightSnapshots = 0;
    rm->NumInstantReplaySnapshots = 0;
    rm->NumLapSnapshots = 0;
    rm->NumHighlightSnapshots = 0;
    rm->NextHighlightNumber = 0;
    rm->EndCurrentHighlightTime = 0;
    rm->NumSpecialEvents = 0;
    memset(rm->SpecialEventTable, 0, sizeof rm->SpecialEventTable);
    rm->LastSpecialEventNumber = 0;
    if (DemoModeReplayActiveFlag) {
        rm->pRepeat = DemoModeReplay_pRepeat;
        DemoModeReplay_pRepeat = 0;
        list_append(snap_list(rm), demo_list());
        rm->MaxNumSnapshots = 1;
        n = 0;
        do
            new_free_snapshot(rm);
        while (++n < rm->MaxNumSnapshots);
    }
    return rm;
}

// 0x0013d5c0. The lists' own destructors find them empty, and are left out.
void replaymgr_destroy(ReplayManager *rm, int32_t flags)
{
    ReplayLink *l = snap_list(rm);
    ReplayLink *f = free_list(rm);

    while (link_at(l->Next) != l) {
        ReplaySnapshot *s = link_snap(link_at(l->Next));

        list_unlink(snap_link(s));
        if (s->MemoryImageLoadedFlag) {
            list_add_tail(demo_list(), snap_link(s));
            if (rm->pRepeat != 0) {
                DemoModeReplay_pRepeat = rm->pRepeat;
                rm->pRepeat = 0;
            }
        } else {
            bFree(s);
        }
    }
    while (link_at(f->Next) != f) {
        ReplaySnapshot *s = link_snap(link_at(f->Next));

        list_unlink(snap_link(s));
        bFree(s);
    }
    if (rm->pRepeat != 0)
        bFree(p32_ptr(rm->pRepeat));
    if (flags & 1)
        bFree(rm);
}

// 0x0013d6f8. The log's channels: 0 the pad events, 8-bit repeat counts;
// 1 4-bit, answering 1 on an error; 2 no repeats; 3 8-bit. The five
// highlights are max(5, 0) in the listing. A NULL bCountFreeMemory reads as
// plenty.
void replaymgr_mark_the_beginning_of_time(ReplayManager *rm)
{
    bRepeat *r;
    int32_t n;

    if (rm->BeginCapturingLoopCount != -1)
        return;
    rm->EndCapturingLoopCount = WorldLoopCounter;
    rm->BeginCapturingLoopCount = WorldLoopCounter;
    rm->BeginningOfTime = WorldTimer;
    rm->EndOfTime = WorldTimer;
    if (gBCountFreeMemoryFn != NULL
        && gBCountFreeMemoryFn(REPLAY_POOL) - 32768 < REPLAY_MIN_FREE)
        return;
    r = bMalloc(REPLAY_LOG_SIZE, "ReplayLogBuffer", 0, REPLAY_POOL);
    bRepeat_PrepareToAddData(r, REPLAY_LOG_SIZE, 4, 0);
    bRepeat_InitChannel(r, 0, 8, 0);
    bRepeat_InitChannel(r, 1, 4, 1);
    bRepeat_InitChannel(r, 2, 0, 0);
    bRepeat_InitChannel(r, 3, 8, 0);
    rm->pRepeat = p32_of(r);
    rm->MaxNumSnapshots = 17;
    rm->MaxNumInstantReplaySnapshots = 2;
    rm->MaxNumLapSnapshots = 8;
    rm->MaxNumHighlightSnapshots = 5;
    rm->FinishedAllCapturing = 0;
    rm->MaxNumAutoReplaySnapshots = 0;
    n = 0;
    do
        new_free_snapshot(rm);
    while (++n < rm->MaxNumSnapshots);
}

// 0x0013d868.
void replaymgr_mark_the_end_of_time(ReplayManager *rm)
{
    if (!rm->FinishedAllCapturing)
        rm->FinishedAllCapturing = 1;
}

// ------------------------------------------------------------------ frames

static void maybe_take_instant_replay_snapshot(ReplayManager *rm);
static void maybe_take_lap_snapshot(ReplayManager *rm);
static void maybe_take_dummy_snapshot(ReplayManager *rm);
static void maybe_do_checksum_snapshot(ReplayManager *rm);
static void check_for_special_events(ReplayManager *rm);

// 0x0013d880. Without a log nothing captures or replays. A demo replay
// replays throughout. Otherwise the frame at the capture's end captures,
// unless the replay is paused there (then it replays) or the capture is
// over (then neither); a frame from the capture's beginning up to its end
// replays. Slow motion pauses three frames in four of RealLoopCounter,
// whose C remainder the listing works out.
void replaymgr_begin_frame(ReplayManager *rm)
{
    if (rm->pRepeat != 0) {
        if (DemoModeReplayActiveFlag)
            rm->ReplayingFlag = 1;
        else if (WorldLoopCounter == rm->EndCapturingLoopCount
                 && rm->PausedFlag)
            rm->ReplayingFlag = 1;
        else if (WorldLoopCounter == rm->EndCapturingLoopCount
                 && !rm->FinishedAllCapturing)
            rm->CapturingFlag = 1;
        else if (!(WorldLoopCounter < rm->BeginCapturingLoopCount)
                 && WorldLoopCounter < rm->EndCapturingLoopCount)
            rm->ReplayingFlag = 1;
    }
    if (rm->CapturingFlag) {
        maybe_take_instant_replay_snapshot(rm);
        if (rm->CapturingFlag)
            maybe_take_lap_snapshot(rm);
    }
    if (rm->ReplayingFlag) {
        if (rm->PausedFlag)
            rm->ReplayPausedThisFrame = 1;
        else if (rm->SlowMotionFlag)
            rm->ReplayPausedThisFrame = RealLoopCounter % 4 != 0;
        check_for_special_events(rm);
    }
    maybe_take_dummy_snapshot(rm);
    maybe_do_checksum_snapshot(rm);
    if (gDemoModeReplayServiceFn != NULL)
        gDemoModeReplayServiceFn(WorldLoopCounter == rm->LastSnapshotTime);
}

// 0x0013e008. The end of time is the world's timer after this frame's
// step, through Timer::SetTime.
void replaymgr_end_frame(ReplayManager *rm)
{
    if (rm->CapturingFlag) {
        Timer t;

        rm->EndCapturingLoopCount = WorldLoopCounter + 1;
        timer_set_time(&t, WorldTimeElapsed);
        rm->CapturingFlag = 0;
        rm->EndOfTime = (int32_t)((uint32_t)WorldTimer + t.PackedTime);
    } else if (rm->ReplayingFlag) {
        rm->ReplayPausedThisFrame = 0;
        rm->ReplayingFlag = 0;
    }
}

// 0x0013d9b8, new in retail: whether the capture took a snapshot on loop
// `t`. The search starts at the last one found when that is before `t`.
static int32_t is_snapshot_time(ReplayManager *rm, int32_t t)
{
    int32_t i = 0;

    if (rm->SnapshotTimeCursor != 0
        && rm->SnapshotTimeTable[rm->SnapshotTimeCursor] < t)
        i = rm->SnapshotTimeCursor;
    for (; i < rm->NumSnapshotsTaken; i++)
        if (rm->SnapshotTimeTable[i] == t) {
            rm->SnapshotTimeCursor = i;
            return 1;
        }
    return 0;
}

// 0x0013da20. Replaying, on each loop the capture took one; capturing,
// every 211th loop and after 30 with none. Taken, then let go at once.
static void maybe_take_dummy_snapshot(ReplayManager *rm)
{
    int32_t take = 0;

    if (rm->ReplayingFlag && !rm->ReplayPausedThisFrame
        && WorldLoopCounter != rm->LastSnapshotTime)
        take = is_snapshot_time(rm, WorldLoopCounter) != 0;
    if (rm->CapturingFlag) {
        if (WorldLoopCounter % 211 == 0)
            take = 1;
        if (rm->LastSnapshotTime + 30 < WorldLoopCounter)
            take = 1;
    }
    if (take && replaymgr_take_snapshot(rm, "DUMMY_SNAPSHOT") != NULL)
        replaymgr_delete_snapshot_named(rm, "DUMMY_SNAPSHOT");
}

// 0x0013daf0. Every 300 frames of WorldTimeFrames. With both instant
// replays held, the older one goes: kept as a highlight when its total is
// above 0 and above the highlight it would replace, else deleted. The
// highlight to replace is the first that ends after the older one begins,
// or the least interesting -- but a walk past NumHighlightSnapshots leaves
// none, so with a slot free nothing is replaced unless it overlaps. A full
// set, or an overlap, deletes it first.
static void maybe_take_instant_replay_snapshot(ReplayManager *rm)
{
    if (WorldTimeFrames < rm->NextInstantReplaySnapshotTime)
        return;
    rm->NextInstantReplaySnapshotTime = WorldTimeFrames + 300;
    if (rm->NumInstantReplaySnapshots != 0
        && !(rm->NumInstantReplaySnapshots
             < rm->MaxNumInstantReplaySnapshots)) {
        ReplaySnapshot *oldest =
            replaymgr_find_snapshot(rm, "INSTANT_REPLAY", 0);
        ReplaySnapshot *pick = NULL;
        int32_t k;

        for (k = 0; k < rm->MaxNumHighlightSnapshots; k++) {
            ReplaySnapshot *h;

            if (!(k < rm->NumHighlightSnapshots)) {
                pick = NULL;
                continue;
            }
            h = replaymgr_find_snapshot(rm, "HIGHLIGHT_SNAPSHOT", k);
            if (oldest->BeginLoopTime < h->EndLoopTime) {
                pick = h;
                break;
            }
            if (pick == NULL
                || h->TotalInterestingValue < pick->TotalInterestingValue)
                pick = h;
        }
        if (0.0f < oldest->TotalInterestingValue
            && (pick == NULL || pick->TotalInterestingValue
                                    < oldest->TotalInterestingValue)) {
            if (rm->NumHighlightSnapshots == rm->MaxNumHighlightSnapshots
                || (pick != NULL
                    && oldest->BeginLoopTime < pick->EndLoopTime)) {
                replaymgr_delete_snapshot(rm, pick);
                rm->NumHighlightSnapshots--;
            }
            ReplaySnapshot_ChangeName(oldest, "HIGHLIGHT_SNAPSHOT");
            oldest->EndLoopTime = WorldLoopCounter;
            oldest->EndTime = WorldTimer;
            rm->NumInstantReplaySnapshots--;
            rm->NumHighlightSnapshots++;
        } else {
            replaymgr_delete_snapshot_named(rm, "INSTANT_REPLAY");
            rm->NumInstantReplaySnapshots--;
        }
    }
    if (replaymgr_take_snapshot(rm, "INSTANT_REPLAY") != NULL)
        rm->NumInstantReplaySnapshots++;
}

static void do_checksum_snapshot(ReplayManager *rm, const char *name);

// 0x0013dd00. The first of the four times that is this loop.
static void maybe_do_checksum_snapshot(ReplayManager *rm)
{
    char name[16];
    int32_t i;

    for (i = 0; i < 4; i++)
        if (ChecksumSnapshotTimes[i] == WorldLoopCounter)
            break;
    if (i < 4) {
        snprintf(name, sizeof name, "CHECKSUM%d", (int)i);
        do_checksum_snapshot(rm, name);
    }
}

static void handle_snapshot(ReplayManager *rm, ReplaySnapshot *s);

// 0x0013dd88. Capturing, a checksum of the race now, at the list's end; a
// second of the same name is a bBreak. Replaying (and not paused this
// frame), the one of that name verified against the race now. Retail tests
// the free list again after making a snapshot for it, which cannot find it
// empty.
static void do_checksum_snapshot(ReplayManager *rm, const char *name)
{
    ReplaySnapshot *s;

    if (rm->CapturingFlag) {
        if (replaymgr_find_snapshot(rm, name, 0) != NULL)
            replay_breaks++;
        s = use_free_snapshot(rm, name);
        s->DataPosition = 0;
        s->TakingChecksumFlag = 1;
        handle_snapshot(rm, s);
        s->SizeofData = s->DataPosition;
        s->TakingChecksumFlag = 0;
    } else if (rm->ReplayingFlag && !rm->ReplayPausedThisFrame) {
        s = replaymgr_find_snapshot(rm, name, 0);
        if (s != NULL) {
            s->DataPosition = 0;
            s->VerifyingChecksumFlag = 1;
            handle_snapshot(rm, s);
            s->VerifyingChecksumFlag = 0;
        }
    }
}

// 0x0013ded8. A lap snapshot when NumLapSnapshots spacings have gone by
// since the beginning of time, in seconds (ticks times 0.00025, gp-31500).
// With all eight taken, the spacing doubles and every other one goes, the
// first kept, and the test runs again.
static void maybe_take_lap_snapshot(ReplayManager *rm)
{
    for (;;) {
        ReplaySnapshot *s;
        int32_t k;

        if (!(rm->LapSnapshotSpacing * (float)rm->NumLapSnapshots
              <= (float)(int32_t)((uint32_t)WorldTimer
                                  - (uint32_t)rm->BeginningOfTime)
                     * 0.00025f))
            return;
        if (rm->NumLapSnapshots != rm->MaxNumLapSnapshots) {
            if (replaymgr_take_snapshot(rm, "LAP_SNAPSHOT") != NULL)
                rm->NumLapSnapshots++;
            return;
        }
        rm->LapSnapshotSpacing = rm->LapSnapshotSpacing
                                 + rm->LapSnapshotSpacing;
        k = 0;
        while (replaymgr_find_snapshot(rm, "LAP_SNAPSHOT", k) != NULL) {
            k++;
            s = replaymgr_find_snapshot(rm, "LAP_SNAPSHOT", k);
            if (s != NULL) {
                replaymgr_delete_snapshot(rm, s);
                rm->NumLapSnapshots--;
            }
        }
        if (!(rm->NumLapSnapshots < rm->MaxNumLapSnapshots))
            return;
    }
}

// ---------------------------------------------------- the joylog's debugging

// The pad events DoFancyJoylogDebugging plays: the first run's 24, the
// second's 13.
static const uint8_t FancyEventsFirst[24] = {
    131, 0, 0, 0, 0, 0, 4, 0, 0, 0, 0, 4, 0, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 9,
};
static const uint8_t FancyEventsSecond[13] = {
    99, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 9,
};

// 0x0013e078. FancyReplayInProgress is the state: 0 waits for the joylog
// replay to reach NextFancyDebugTime; 1 turns the joylog off; 2 waits for
// the capture's end, paused, then moves NextFancyDebugTime on 211 loops,
// deletes the four checksums and sets their loops 1, 52, 105 and 158 on;
// 3 waits for the fancy events to run out and turns the joylog on.
void replaymgr_do_fancy_joylog_debugging(ReplayManager *rm)
{
    int32_t state = rm->FancyReplayInProgress;

    if (state == 0) {
        if (Joylog_ReplayingFlag
            && WorldLoopCounter == rm->NextFancyDebugTime - 1) {
            rm->FancyReplayInProgress = 1;
            memcpy(rm->FancyJoyEventTable, FancyEventsFirst,
                   sizeof FancyEventsFirst);
            rm->NumFancyJoyEvents = (int32_t)sizeof FancyEventsFirst;
            rm->FancyJoyEventNumber = 0;
        }
    } else if (state == 1) {
        Joylog_ReplayingFlag = 0;
        rm->FancyReplayInProgress = 2;
    } else if (state == 2) {
        int32_t now;

        if (WorldLoopCounter != rm->EndCapturingLoopCount
            || !rm->PausedFlag)
            return;
        rm->NextFancyDebugTime += 211;
        replaymgr_delete_snapshot_named(rm, "CHECKSUM0");
        replaymgr_delete_snapshot_named(rm, "CHECKSUM1");
        replaymgr_delete_snapshot_named(rm, "CHECKSUM2");
        replaymgr_delete_snapshot_named(rm, "CHECKSUM3");
        now = WorldLoopCounter;
        ChecksumSnapshotTimes[0] = now + 1;
        ChecksumSnapshotTimes[3] = now + 158;
        ChecksumSnapshotTimes[1] = now + 52;
        ChecksumSnapshotTimes[2] = now + 105;
        rm->FancyReplayInProgress = 3;
        memcpy(rm->FancyJoyEventTable, FancyEventsSecond,
               sizeof FancyEventsSecond);
        rm->NumFancyJoyEvents = (int32_t)sizeof FancyEventsSecond;
        rm->FancyJoyEventNumber = 0;
    } else if (state == 3) {
        if (rm->FancyJoyEventNumber < rm->NumFancyJoyEvents)
            return;
        Joylog_ReplayingFlag = 1;
        rm->FancyReplayInProgress = 0;
    }
}

// -------------------------------------------------------------- highlights

// 0x0013e308.
void replaymgr_begin_race_highlights(ReplayManager *rm)
{
    rm->NextHighlightNumber = 0;
    replaymgr_begin_next_race_highlight(rm);
}

// 0x0013e318. A highlight plays to the loop it ended on; the first lap
// snapshot plays to the capture's end, and with neither the end is 0.
void replaymgr_begin_next_race_highlight(ReplayManager *rm)
{
    ReplaySnapshot *s;

    if (rm->MuteHighlightSoundFlag) {
        rm->PausedFlag = 1;
        rm->EndCurrentHighlightTime = WorldLoopCounter + 1;
        return;
    }
    s = replaymgr_find_snapshot(rm, "HIGHLIGHT_SNAPSHOT",
                                rm->NextHighlightNumber);
    if (s != NULL) {
        rm->EndCurrentHighlightTime = s->EndLoopTime;
        rm->NextHighlightNumber = rm->NextHighlightNumber + 1;
        if (replaymgr_find_snapshot(rm, "HIGHLIGHT_SNAPSHOT",
                                    rm->NextHighlightNumber) == NULL)
            rm->NextHighlightNumber = 0;
    } else {
        s = replaymgr_find_snapshot(rm, "LAP_SNAPSHOT", 0);
        if (s != NULL)
            rm->EndCurrentHighlightTime = rm->EndCapturingLoopCount;
        else
            rm->EndCurrentHighlightTime = 0;
        rm->NextHighlightNumber = 0;
    }
    if (s != NULL)
        replaymgr_restore_snapshot(rm, s);
}

// ---------------------------------------------------------- special events

// 0x0013e4a8.
static void handle_special_event(ReplayManager *rm,
                                 const ReplaySpecialEventInfo *e)
{
    (void)rm;
    if (gReplayHandleSpecialEventFn != NULL)
        gReplayHandleSpecialEventFn(e);
}

// 0x0013e3f8. Kept from the beginning of time until the capture is over,
// with a log.
void replaymgr_add_special_event(ReplayManager *rm, int32_t type, int32_t a,
                                 int32_t b)
{
    ReplaySpecialEventInfo e;

    e.Type = type;
    e.LoopCount = WorldLoopCounter;
    e.A = a;
    e.B = b;
    if (rm->BeginCapturingLoopCount != -1 && !rm->FinishedAllCapturing
        && rm->pRepeat != 0) {
        if (rm->NumSpecialEvents < REPLAY_MAX_SPECIAL_EVENTS)
            rm->SpecialEventTable[rm->NumSpecialEvents++] = e;
        else
            replaymgr_mark_the_end_of_time(rm);
    }
    handle_special_event(rm, &e);
}

// 0x0013e4b0. From the last event looked at, back past every event not
// before this loop, then on through those up to it, making each one on
// it. A handler can add events; the count is read again after each.
static void check_for_special_events(ReplayManager *rm)
{
    int32_t n = rm->NumSpecialEvents;
    int32_t i;

    if (n == 0)
        return;
    i = rm->LastSpecialEventNumber;
    while (i >= 0
           && !(rm->SpecialEventTable[i].LoopCount < WorldLoopCounter))
        i--;
    if (i < 0)
        i = 0;
    if (i < n && !(WorldLoopCounter < rm->SpecialEventTable[i].LoopCount)) {
        do {
            if (rm->SpecialEventTable[i].LoopCount == WorldLoopCounter) {
                handle_special_event(rm, &rm->SpecialEventTable[i]);
                n = rm->NumSpecialEvents;
            }
            i++;
        } while (i < n
                 && !(WorldLoopCounter < rm->SpecialEventTable[i].LoopCount));
    }
    if (n - 1 < i)
        i = n - 1;
    rm->LastSpecialEventNumber = i;
}

// --------------------------------------------------------------- snapshots

// 0x0013e5c8. bStrCmp's zero is strcmp's.
ReplaySnapshot *replaymgr_find_snapshot(ReplayManager *rm, const char *name,
                                        int32_t k)
{
    ReplayLink *l = snap_list(rm);
    ReplayLink *n;

    for (n = link_at(l->Next); n != l; n = link_at(n->Next))
        if (strcmp(link_snap(n)->Name, name) == 0) {
            if (k == 0)
                return link_snap(n);
            k--;
        }
    return NULL;
}

// 0x0013e648.
ReplaySnapshot *replaymgr_get_snapshot(ReplayManager *rm, int32_t k)
{
    ReplayLink *l = snap_list(rm);
    ReplayLink *n;

    for (n = link_at(l->Next); n != l; n = link_at(n->Next)) {
        if (k == 0)
            return link_snap(n);
        k--;
    }
    return NULL;
}

// 0x0013e690. Through a list on the stack, sorted with bList::Sort.
void replaymgr_sort_snapshots(ReplayManager *rm, const char *name)
{
    ReplayLink tmp = { 0, 0 };
    ReplaySnapshot *s;

    list_init(&tmp);
    while ((s = replaymgr_find_snapshot(rm, name, 0)) != NULL) {
        list_unlink(snap_link(s));
        list_add_tail(&tmp, snap_link(s));
    }
    list_sort(&tmp);
    list_append(snap_list(rm), &tmp);
}

// 0x0013e748.
int32_t replaymgr_restore_snapshot_named(ReplayManager *rm, const char *name)
{
    ReplaySnapshot *s = replaymgr_find_snapshot(rm, name, 0);

    if (s == NULL)
        return 0;
    replaymgr_restore_snapshot(rm, s);
    return 1;
}

// 0x0013e790.
int32_t replaymgr_delete_snapshot_named(ReplayManager *rm, const char *name)
{
    ReplaySnapshot *s = replaymgr_find_snapshot(rm, name, 0);

    if (s == NULL)
        return 0;
    replaymgr_delete_snapshot(rm, s);
    return 1;
}

// 0x0013e7d8.
void replaymgr_delete_snapshot(ReplayManager *rm, ReplaySnapshot *s)
{
    list_unlink(snap_link(s));
    list_add_tail(free_list(rm), snap_link(s));
}

static void do_end_snapshot(ReplayManager *rm, ReplaySnapshot *s);

// 0x0013e808. REPLAY_MANAGER_STATE is the manager's own. Any other is the
// race's: its setup, the log (the add side's while a capture takes or
// checksums the frame at its end, else the remove side's), the pads and
// the coordinator, which takes the world, the race and the players.
static void handle_snapshot(ReplayManager *rm, ReplaySnapshot *s)
{
    if (strcmp(s->Name, "REPLAY_MANAGER_STATE") == 0) {
        do_end_snapshot(rm, s);
        return;
    }
    race_parameters_do_snapshot(&TheRaceParameters, s);
    if ((s->TakingSnapshotFlag || s->TakingChecksumFlag)
        && WorldLoopCounter == rm->EndCapturingLoopCount)
        bRepeat_DoSnapshot(p32_ptr(rm->pRepeat), s, 1);
    else
        bRepeat_DoSnapshot(p32_ptr(rm->pRepeat), s, 0);
    JoystickDoSnapshot(s);
    racecoordinator_do_snapshot(pRaceCoordinator, s);
}

// 0x0013e8d8, section "ReplayManager": the capture's loop counts, the
// snapshot times and the special events. A restore reads each count before
// the table it counts.
static void do_end_snapshot(ReplayManager *rm, ReplaySnapshot *s)
{
    int32_t i;

    ReplaySnapshot_BeginNamedSection(s, "ReplayManager");
    ReplaySnapshot_MoveInt(s, &rm->BeginCapturingLoopCount, 4);
    ReplaySnapshot_MoveInt(s, &rm->EndCapturingLoopCount, 4);
    ReplaySnapshot_MoveInt(s, &rm->NumSnapshotsTaken, 4);
    for (i = 0; i < rm->NumSnapshotsTaken; i++)
        ReplaySnapshot_MoveInt(s, &rm->SnapshotTimeTable[i], 4);
    ReplaySnapshot_MoveInt(s, &rm->NumSpecialEvents, 4);
    for (i = 0; i < rm->NumSpecialEvents; i++)
        ReplaySnapshot_MoveData(s, &rm->SpecialEventTable[i], 16, -1, 0);
    ReplaySnapshot_EndNamedSection(s);
}

// 0x0013e9f0. A snapshot taken on the frame at the capture's end goes in
// the snapshot times, while there is room.
ReplaySnapshot *replaymgr_take_snapshot(ReplayManager *rm, const char *name)
{
    ReplaySnapshot *s;

    if (rm->BeginCapturingLoopCount < 0)
        return NULL;
    s = use_free_snapshot(rm, name);
    if (WorldLoopCounter == rm->EndCapturingLoopCount
        && rm->NumSnapshotsTaken < REPLAY_MAX_SNAPSHOT_TIMES)
        rm->SnapshotTimeTable[rm->NumSnapshotsTaken++] = WorldLoopCounter;
    rm->LastSnapshotTime = WorldLoopCounter;
    s->DataPosition = 0;
    s->TakingSnapshotFlag = 1;
    handle_snapshot(rm, s);
    s->SizeofData = s->DataPosition;
    s->TakingSnapshotFlag = 0;
    if (s->OverflowedFlag) {
        replaymgr_delete_snapshot(rm, s);
        return NULL;
    }
    return s;
}

// 0x0013eb38. LastSnapshotTime is the restored loop.
void replaymgr_restore_snapshot(ReplayManager *rm, ReplaySnapshot *s)
{
    s->DataPosition = 0;
    s->RestoringSnapshotFlag = 1;
    handle_snapshot(rm, s);
    s->RestoringSnapshotFlag = 0;
    rm->RemoveDataError = 0;
    rm->LastSnapshotTime = WorldLoopCounter;
}

// ------------------------------------------------------------------ the log

// 0x0013eb88. The log's error stays the manager's until a restore.
int32_t replaymgr_get_data(ReplayManager *rm, int32_t bits, int32_t channel)
{
    bRepeat *r;
    int32_t v;

    if (!rm->ReplayingFlag)
        return 0;
    if (rm->RemoveDataError)
        return 0;
    r = p32_ptr(rm->pRepeat);
    v = bRepeat_RemoveData(r, bits, channel);
    if (r->RemoveDataError)
        rm->RemoveDataError = 1;
    return v;
}

// 0x0013ebe8. sllv and srlv take the shift's low five bits.
int32_t replaymgr_get_signed_data(ReplayManager *rm, int32_t bits,
                                  int32_t channel)
{
    uint32_t v = (uint32_t)replaymgr_get_data(rm, bits, channel);
    uint32_t sh = (uint32_t)(32 - bits) & 31u;

    return (int32_t)((v << sh) >> sh);
}

// 0x0013ec20. The capture ends once fewer than 68 bits are left.
void replaymgr_add_data(ReplayManager *rm, int32_t value, int32_t bits,
                        int32_t channel)
{
    bRepeat *r;

    if (!rm->CapturingFlag)
        return;
    r = p32_ptr(rm->pRepeat);
    bRepeat_AddData(r, value, bits, channel);
    if (!(r->AddLocation < r->AddBufferSize * 8 - 68)) {
        rm->CapturingFlag = 0;
        replaymgr_mark_the_end_of_time(rm);
    }
}
