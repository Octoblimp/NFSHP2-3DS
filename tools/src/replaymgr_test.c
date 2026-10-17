// Drives replaymgr.c's ReplayManager for tools/replaymgr_check.py (TASKS
// 72f-1). A script of ops, one per line, fields split on '|'; every number
// is decimal or 0x hex, taken mod 2^32:
//
//   g|NAME|V           a global: wlc wt wtf wte (bits) rlc joy demo, free
//                      (what bCountFreeMemory answers), grow (bytes each
//                      recorded snapshot call moves on), rc
//                      (pRaceCoordinator, 0 or the RC)
//   ovfname|NAME       the next recorded call on a snapshot named NAME
//                      overflows it
//   cst|A|B|C|D        ChecksumSnapshotTimes
//   f|OFF|V            a word of the manager
//   sfn|NAME|K|OFF|N|V the Kth snapshot named NAME, N bytes at OFF
//   rset|OFF|V         a word of the log
//   demosnap|NAME      a snapshot at the end of TheDemoModeReplay's, with its
//                      memory image loaded
//   demolog            a log for TheDemoModeReplay
//   hadd|T|A|B         the next special event handled appends this one
//   ctor dtor|F bot eot bf ef fancy brh bnrh   the methods
//   ase|T|A|B          AddSpecialEvent
//   find|NAME|K get|K sort|NAME rsn|NAME dsn|NAME del|K take|NAME
//   rest|NAME|K        the Kth snapshot named NAME restored
//   gd|BITS|C gsd|BITS|C ad|V|BITS|C
//   atend|D atbegin|D  WorldLoopCounter D past the capture's end, beginning
//   atsnap|NAME|K|D    D past the Kth snapshot named NAME's BeginLoopTime
//   step|D             D more
//   fancyat|D          NextFancyDebugTime D past WorldLoopCounter
//   rmw                the manager's first eleven words
//   dump               the manager, its lists, the demo's and the log
//
// Blocks print as #n in the order bMalloc made them; the manager is #0.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
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
#include "replay.h"
#include "replaymgr.h"
#include "trackflow.h"

int32_t WorldTimer;
int32_t WorldLoopCounter;
int32_t WorldTimeFrames;
float WorldTimeElapsed;
int32_t RealLoopCounter;
int32_t Joylog_ReplayingFlag;
int32_t DemoModeReplayActiveFlag;
int (*gBCountFreeMemoryFn)(int pool);
RaceParameters TheRaceParameters;
RaceCoordinator *pRaceCoordinator;

#define FILL 0xcd
#define MAX_BLOCKS 1024
#define MAX_NAMES 64
#define LOG_SIZE 0x32000

static ReplayManager rm_obj;
#define RM (&rm_obj)
static uint64_t rcstore[8];
#define RC ((RaceCoordinator *)(void *)rcstore)

static void *blocks[MAX_BLOCKS];
static int32_t sizes[MAX_BLOCKS];
static int num_blocks;
static char *names[MAX_NAMES];
static int num_names;

static uint32_t free_mem = 0x7fffffff;
static int32_t grow;
static const char *ovf_name;
static int hadd_pending;
static ReplaySpecialEventInfo hadd_ev;

static int32_t num(const char *s)
{
    return (int32_t)(uint32_t)strtoll(s, NULL, 0);
}

static const char *intern(const char *s)
{
    int i;

    for (i = 0; i < num_names; i++)
        if (strcmp(names[i], s) == 0)
            return names[i];
    if (num_names == MAX_NAMES) {
        fprintf(stderr, "too many names\n");
        exit(2);
    }
    names[num_names] = malloc(strlen(s) + 1);
    strcpy(names[num_names], s);
    return names[num_names++];
}

static uint32_t crc_table[256];

static uint32_t crc32(const void *data, size_t n)
{
    const uint8_t *p = data;
    uint32_t c = 0xffffffffu;
    size_t i;

    if (crc_table[1] == 0) {
        uint32_t k, j;

        for (k = 0; k < 256; k++) {
            uint32_t v = k;

            for (j = 0; j < 8; j++)
                v = (v & 1) ? 0xedb88320u ^ (v >> 1) : v >> 1;
            crc_table[k] = v;
        }
    }
    for (i = 0; i < n; i++)
        c = crc_table[(c ^ p[i]) & 0xff] ^ (c >> 8);
    return c ^ 0xffffffffu;
}

// ---------------------------------------------------------------- blocks

static const char *label(const void *p)
{
    static char buf[8][16];
    static int k;
    char *b = buf[k++ & 7];
    int i;

    if (p == NULL)
        return "0";
    if (p == (const void *)RC)
        return "RC";
    for (i = 0; i < num_blocks; i++)
        if (blocks[i] == p) {
            snprintf(b, 16, "#%d", i);
            return b;
        }
    for (i = 0; i < num_blocks; i++)
        if ((const uint8_t *)p > (const uint8_t *)blocks[i]
            && (const uint8_t *)p < (const uint8_t *)blocks[i] + sizes[i]) {
            snprintf(b, 16, "#%d+%d", i,
                     (int)((const uint8_t *)p - (const uint8_t *)blocks[i]));
            return b;
        }
    return "?";
}

static void *new_block(int size, const char *name, int flags, int pool)
{
    uint8_t *p = malloc((size_t)size + 16);

    if (num_blocks == MAX_BLOCKS) {
        fprintf(stderr, "too many blocks\n");
        exit(2);
    }
    memset(p, FILL, (size_t)size);
    blocks[num_blocks] = p;
    sizes[num_blocks] = size;
    printf("malloc #%d size=%d name=%s flags=%d pool=%d\n", num_blocks, size,
           name ? name : "-", flags, pool);
    num_blocks++;
    return p;
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    return new_block(size, name, flags, pool);
}

void bFree(void *p)
{
    printf("free %s\n", label(p));
}

static int count_free(int pool)
{
    printf("count pool=%d\n", pool);
    return (int)free_mem;
}

// ------------------------------------------------- the recorded callees

static void recorded(const char *what, int ok, ReplaySnapshot *s)
{
    printf("cb %s ok=%d s=%s mode=%d,%d,%d,%d pos=%d\n", what, ok, label(s),
           s->TakingSnapshotFlag, s->RestoringSnapshotFlag,
           s->TakingChecksumFlag, s->VerifyingChecksumFlag, s->DataPosition);
    s->DataPosition += grow;
    if (ovf_name != NULL && strcmp(s->Name, ovf_name) == 0) {
        ovf_name = NULL;
        s->OverflowedFlag = 1;
    }
}

void race_parameters_do_snapshot(RaceParameters *rp, ReplaySnapshot *s)
{
    recorded("rp", rp == &TheRaceParameters, s);
}

void JoystickDoSnapshot(ReplaySnapshot *s)
{
    recorded("joy", 1, s);
}

void racecoordinator_do_snapshot(RaceCoordinator *rc, ReplaySnapshot *s)
{
    printf("cb rc arg=%s\n", label(rc));
    recorded("rc", 1, s);
}

static void on_event(const ReplaySpecialEventInfo *e)
{
    const ReplaySpecialEventInfo *t = RM->SpecialEventTable;
    int in = (e >= t && e < t + REPLAY_MAX_SPECIAL_EVENTS) ? (int)(e - t)
                                                           : -1;

    printf("ev in=%d type=%d loop=%d a=%d b=%d\n", in, e->Type, e->LoopCount,
           e->A, e->B);
    if (hadd_pending) {
        hadd_pending = 0;
        RM->SpecialEventTable[RM->NumSpecialEvents++] = hadd_ev;
        printf("hadd n=%d\n", RM->NumSpecialEvents);
    }
}

static void on_service(int32_t flag)
{
    printf("svc flag=%d\n", flag);
}

// ---------------------------------------------------------------- lists

typedef struct Link {
    uint32_t Next;
    uint32_t Prev;
} Link;

static void link_init(Link *l)
{
    l->Next = p32_of(l);
    l->Prev = p32_of(l);
}

static void link_add_tail(Link *l, Link *n)
{
    Link *tail;

    if (l->Next == 0 && l->Prev == 0)
        link_init(l);
    tail = p32_ptr(l->Prev);
    tail->Next = p32_of(n);
    l->Prev = p32_of(n);
    n->Prev = p32_of(tail);
    n->Next = p32_of(l);
}

static void print_snapshot(const ReplaySnapshot *s)
{
    uint32_t tiv;

    memcpy(&tiv, &s->TotalInterestingValue, 4);
    printf("  s %s name=%.32s t=%d et=%d blt=%d elt=%d mil=%d "
           "f=%d,%d,%d,%d,%d,%d tiv=%08x pos=%d size=%d crc=%08x\n",
           label(s), s->Name, s->Time, s->EndTime, s->BeginLoopTime,
           s->EndLoopTime, s->MemoryImageLoadedFlag, s->TakingSnapshotFlag,
           s->RestoringSnapshotFlag, s->TakingChecksumFlag,
           s->VerifyingChecksumFlag, s->CurrentSectionDepth,
           s->OverflowedFlag, tiv, s->DataPosition, s->SizeofData,
           crc32(s->Data, sizeof s->Data));
}

static void walk(const char *what, Link *head)
{
    uint32_t hh = p32_of(head);
    uint32_t prev = hh;
    uint32_t n = head->Next;
    Link *seen[64];
    int k = 0;
    int i;

    printf("%s:", what);
    if (head->Next == 0 && head->Prev == 0)
        n = prev = hh;
    while (n != hh && k < 64) {
        Link *node = p32_ptr(n);

        if (node == NULL) {
            printf(" NULL");
            break;
        }
        printf(" %s%s", label(node), node->Prev == prev ? "" : "!");
        seen[k++] = node;
        prev = n;
        n = node->Next;
    }
    printf("%s back=%s\n", n == hh ? "" : " ...",
           (head->Next == 0 && head->Prev == 0) || head->Prev == prev
               ? "ok" : "bad");
    for (i = 0; i < k; i++)
        print_snapshot((ReplaySnapshot *)(void *)seen[i]);
}

// The Kth snapshot named `name`, or with name NULL the Kth.
static ReplaySnapshot *nth(const char *name, int32_t k)
{
    Link *l = (Link *)(void *)RM->ReplaySnapshotList;
    uint32_t hh = p32_of(l);
    uint32_t n = l->Next;
    int guard = 0;

    while (n != hh && guard++ < 256) {
        ReplaySnapshot *s = p32_ptr(n);

        if (name == NULL || strcmp(s->Name, name) == 0) {
            if (k == 0)
                return s;
            k--;
        }
        n = s->pNext;
    }
    return NULL;
}

// ----------------------------------------------------------------- dump

static void dump_words(const char *what, const uint8_t *base, int from,
                       int to)
{
    int o;

    printf("%s", what);
    for (o = from; o < to; o += 4) {
        int32_t v;

        memcpy(&v, base + o, 4);
        printf(" %d", v);
    }
    printf("\n");
}

static void dump(void)
{
    const uint8_t *b = (const uint8_t *)RM;
    int32_t n;
    int i;

    dump_words("rm", b, 0, 44);
    printf("fancy");
    for (i = 0; i < 32; i++)
        printf("%s%02x", i ? "" : " ", RM->FancyJoyEventTable[i]);
    printf("\n");
    dump_words("rm2", b, 76, 100);
    printf("rep %s\n", label(p32_ptr(RM->pRepeat)));
    dump_words("rm3", b, 120, 176);
    n = RM->NumSnapshotsTaken;
    n = n < 0 ? 0 : n > 24 ? 24 : n;
    printf("times crc=%08x",
           crc32(RM->SnapshotTimeTable, sizeof RM->SnapshotTimeTable));
    for (i = 0; i < n; i++)
        printf(" %d", RM->SnapshotTimeTable[i]);
    printf("\n");
    dump_words("rm4", b, 16560, 16568);
    n = RM->NumSpecialEvents;
    n = n < 0 ? 0 : n > 12 ? 12 : n;
    printf("events crc=%08x",
           crc32(RM->SpecialEventTable, sizeof RM->SpecialEventTable));
    for (i = 0; i < n; i++) {
        const ReplaySpecialEventInfo *e = &RM->SpecialEventTable[i];

        printf(" %d/%d/%d/%d", e->Type, e->LoopCount, e->A, e->B);
    }
    printf("\n");
    walk("free", (Link *)(void *)RM->FreeReplaySnapshotList);
    walk("snaps", (Link *)(void *)RM->ReplaySnapshotList);
    printf("demo rep=%s\n", label(p32_ptr(DemoModeReplay_pRepeat)));
    walk("demo", (Link *)(void *)DemoModeReplay_SnapshotList);
    printf("glob cst=%d,%d,%d,%d joy=%d breaks=%d\n",
           ChecksumSnapshotTimes[0], ChecksumSnapshotTimes[1],
           ChecksumSnapshotTimes[2], ChecksumSnapshotTimes[3],
           Joylog_ReplayingFlag, replay_breaks);
    if (RM->pRepeat != 0) {
        bRepeat *r = p32_ptr(RM->pRepeat);

        dump_words("log", (const uint8_t *)r, 0, 48);
        printf("logcrc %08x\n", crc32(r, LOG_SIZE));
    }
}

// ------------------------------------------------------------------ ops

static void set_global(const char *g, int32_t v)
{
    if (!strcmp(g, "wlc"))
        WorldLoopCounter = v;
    else if (!strcmp(g, "wt"))
        WorldTimer = v;
    else if (!strcmp(g, "wtf"))
        WorldTimeFrames = v;
    else if (!strcmp(g, "wte"))
        memcpy(&WorldTimeElapsed, &v, 4);
    else if (!strcmp(g, "rlc"))
        RealLoopCounter = v;
    else if (!strcmp(g, "joy"))
        Joylog_ReplayingFlag = v;
    else if (!strcmp(g, "demo"))
        DemoModeReplayActiveFlag = v;
    else if (!strcmp(g, "free"))
        free_mem = (uint32_t)v;
    else if (!strcmp(g, "grow"))
        grow = v;
    else if (!strcmp(g, "rc"))
        pRaceCoordinator = v ? RC : NULL;
    else {
        fprintf(stderr, "no global %s\n", g);
        exit(2);
    }
}

static void set_bytes(void *base, int32_t off, int32_t n, int32_t v)
{
    uint8_t *p = (uint8_t *)base + off;

    if (n == 1)
        *p = (uint8_t)v;
    else
        memcpy(p, &v, 4);
}

int main(int argc, char **argv)
{
    char line[512];
    FILE *sc;

    if (argc < 2 || (sc = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: replaymgr_test SCRIPT\n");
        return 2;
    }
    p32_reset();
    memset(RM, FILL, sizeof *RM);
    blocks[num_blocks] = RM;
    sizes[num_blocks++] = (int32_t)sizeof(ReplayManager);
    gBCountFreeMemoryFn = count_free;
    gReplayHandleSpecialEventFn = on_event;
    gDemoModeReplayServiceFn = on_service;
    while (fgets(line, sizeof line, sc)) {
        char *arg[8] = {0};
        const char *o;
        int n = 0;
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        printf("> %s\n", line);
        for (t = strtok(line, "|"); t && n < 8; t = strtok(NULL, "|"))
            arg[n++] = t;
        o = arg[0];
        if (!strcmp(o, "g")) {
            set_global(arg[1], num(arg[2]));
        } else if (!strcmp(o, "ovfname")) {
            ovf_name = intern(arg[1]);
        } else if (!strcmp(o, "rmw")) {
            dump_words("rm", (const uint8_t *)RM, 0, 44);
        } else if (!strcmp(o, "cst")) {
            int i;

            for (i = 0; i < 4; i++)
                ChecksumSnapshotTimes[i] = num(arg[1 + i]);
        } else if (!strcmp(o, "f")) {
            set_bytes(RM, num(arg[1]), 4, num(arg[2]));
        } else if (!strcmp(o, "sfn")) {
            ReplaySnapshot *s = nth(intern(arg[1]), num(arg[2]));

            if (s == NULL)
                printf("sfn none\n");
            else
                set_bytes(s, num(arg[3]), num(arg[4]), num(arg[5]));
        } else if (!strcmp(o, "rset")) {
            set_bytes(p32_ptr(RM->pRepeat), num(arg[1]), 4, num(arg[2]));
        } else if (!strcmp(o, "demosnap")) {
            ReplaySnapshot *s = new_block((int)sizeof(ReplaySnapshot),
                                          "DemoSnapshot", 0, 16);

            ReplaySnapshot_Init(s, intern(arg[1]));
            s->MemoryImageLoadedFlag = 1;
            link_add_tail((Link *)(void *)DemoModeReplay_SnapshotList,
                          (Link *)(void *)s);
        } else if (!strcmp(o, "demolog")) {
            bRepeat *r = new_block(LOG_SIZE, "DemoLog", 0, 16);

            bRepeat_PrepareToAddData(r, LOG_SIZE, 4, 0);
            bRepeat_InitChannel(r, 0, 8, 0);
            bRepeat_InitChannel(r, 1, 4, 1);
            bRepeat_InitChannel(r, 2, 0, 0);
            bRepeat_InitChannel(r, 3, 8, 0);
            DemoModeReplay_pRepeat = p32_of(r);
        } else if (!strcmp(o, "hadd")) {
            hadd_pending = 1;
            hadd_ev.Type = num(arg[1]);
            hadd_ev.LoopCount = WorldLoopCounter;
            hadd_ev.A = num(arg[2]);
            hadd_ev.B = num(arg[3]);
        } else if (!strcmp(o, "ctor")) {
            memset(RM, FILL, sizeof *RM);
            printf("-> %s\n", label(replaymgr_construct(RM)));
        } else if (!strcmp(o, "dtor")) {
            replaymgr_destroy(RM, num(arg[1]));
        } else if (!strcmp(o, "bot")) {
            replaymgr_mark_the_beginning_of_time(RM);
        } else if (!strcmp(o, "eot")) {
            replaymgr_mark_the_end_of_time(RM);
        } else if (!strcmp(o, "bf")) {
            replaymgr_begin_frame(RM);
        } else if (!strcmp(o, "ef")) {
            replaymgr_end_frame(RM);
        } else if (!strcmp(o, "fancy")) {
            replaymgr_do_fancy_joylog_debugging(RM);
        } else if (!strcmp(o, "brh")) {
            replaymgr_begin_race_highlights(RM);
        } else if (!strcmp(o, "bnrh")) {
            replaymgr_begin_next_race_highlight(RM);
        } else if (!strcmp(o, "ase")) {
            replaymgr_add_special_event(RM, num(arg[1]), num(arg[2]),
                                        num(arg[3]));
        } else if (!strcmp(o, "find")) {
            printf("-> %s\n", label(replaymgr_find_snapshot(
                                   RM, intern(arg[1]), num(arg[2]))));
        } else if (!strcmp(o, "get")) {
            printf("-> %s\n",
                   label(replaymgr_get_snapshot(RM, num(arg[1]))));
        } else if (!strcmp(o, "sort")) {
            replaymgr_sort_snapshots(RM, intern(arg[1]));
        } else if (!strcmp(o, "rsn")) {
            printf("-> %d\n",
                   replaymgr_restore_snapshot_named(RM, intern(arg[1])));
        } else if (!strcmp(o, "dsn")) {
            printf("-> %d\n",
                   replaymgr_delete_snapshot_named(RM, intern(arg[1])));
        } else if (!strcmp(o, "del")) {
            ReplaySnapshot *s = nth(NULL, num(arg[1]));

            if (s == NULL)
                printf("none\n");
            else
                replaymgr_delete_snapshot(RM, s);
        } else if (!strcmp(o, "take")) {
            printf("-> %s\n",
                   label(replaymgr_take_snapshot(RM, intern(arg[1]))));
        } else if (!strcmp(o, "rest")) {
            ReplaySnapshot *s = nth(intern(arg[1]), num(arg[2]));

            if (s == NULL)
                printf("none\n");
            else
                replaymgr_restore_snapshot(RM, s);
        } else if (!strcmp(o, "gd")) {
            printf("-> %d\n", replaymgr_get_data(RM, num(arg[1]),
                                                 num(arg[2])));
        } else if (!strcmp(o, "gsd")) {
            printf("-> %d\n", replaymgr_get_signed_data(RM, num(arg[1]),
                                                        num(arg[2])));
        } else if (!strcmp(o, "ad")) {
            replaymgr_add_data(RM, num(arg[1]), num(arg[2]), num(arg[3]));
        } else if (!strcmp(o, "atend")) {
            WorldLoopCounter = RM->EndCapturingLoopCount + num(arg[1]);
        } else if (!strcmp(o, "atbegin")) {
            WorldLoopCounter = RM->BeginCapturingLoopCount + num(arg[1]);
        } else if (!strcmp(o, "atsnap")) {
            ReplaySnapshot *s = nth(intern(arg[1]), num(arg[2]));

            if (s == NULL)
                printf("atsnap none\n");
            else
                WorldLoopCounter = s->BeginLoopTime + num(arg[3]);
        } else if (!strcmp(o, "step")) {
            WorldLoopCounter += num(arg[1]);
        } else if (!strcmp(o, "fancyat")) {
            RM->NextFancyDebugTime = WorldLoopCounter + num(arg[1]);
        } else if (!strcmp(o, "dump")) {
            dump();
        } else {
            fprintf(stderr, "unknown op %s\n", o);
            return 2;
        }
        fflush(stdout);
    }
    return 0;
}
