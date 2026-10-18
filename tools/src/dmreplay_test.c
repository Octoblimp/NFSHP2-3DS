// Drives dmreplay.c, retail's DemoModeReplay, for tools/dmreplay_check.py
// (TASKS 72h-2a). A script of ops, one per line, fields split on spaces;
// every number is decimal:
//
//   state CTOR WT WLC ACTIVE LOADING LOADED FILE REC ERASE RECSNAP PLAYNUM
//         PLAYSNAP TWFILE TWSAVE TWERASE INFO REPEAT RPDEMO TAKEFAIL
//         EXISTS RAND NRES IVER INEW8, then for each of the 8 slots NAME
//         TIME END BEGIN ENDLOOP
//         the whole state. CTOR 1 runs the constructor first, which empties
//         the list. RECSNAP and PLAYSNAP are -1 for NULL, a slot 0..7 or
//         100 + a chunk; INFO and REPEAT -1 or a chunk. TAKEFAIL makes the
//         manager's TakeSnapshot answer NULL, EXISTS is bFileExists', RAND
//         bRandom's, NRES how many replay resource files Find finds; IVER
//         and INEW8 go in chunk 0's info. A slot's NAME is -1 for none, 0
//         DEMO_MODE_SNAPSHOT, 1 REPLAY_MANAGER_STATE, 2 another; the slots
//         there are the manager's, in slot order
//   load K TYPE / unload K TYPE   chunk K made TYPE and handed to slot 29
//   base I                        GetBaseFilename and GenerateFilename
//   ctor                          the constructor alone
//   call NAME [ARG]               one of the object's functions
//
// Each op prints what it did, the stubs' calls, and the state.
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "dmreplay.h"
#include "p32.h"
#include "race.h"
#include "racecoord.h"
#include "raceparams.h"
#include "realtime.h"
#include "replaymgr.h"
#include "replayscreen.h"
#include "resource.h"
#include "trackflow.h"

#define SLOTS  8
#define CHUNKS 6

// ---------------------------------------------------------------- globals

int32_t DemoModeReplayActiveFlag;
int32_t DemoModeReplay_WantToBeErasingSnapshot;
ReplaySnapshot *DemoModeReplay_pCurrentRecordingSnapshot;
ReplaySnapshot *DemoModeReplay_pCurrentPlayingSnapshot;
uint32_t DemoModeReplay_pRepeat;
uint32_t DemoModeReplay_SnapshotList[2];
ReplayManager *pReplayManager;
RaceCoordinator *pRaceCoordinator;
RaceParameters TheRaceParameters;
int32_t WorldTimer;
int32_t WorldLoopCounter;
uint32_t bDefaultSeed;

// A bTList head and a snapshot's bNode, as p32 words.
typedef struct Link {
    uint32_t Next;
    uint32_t Prev;
} Link;

static char fake_rm[16];
static char fake_rc[16];
static ResourceFile fake_rf[8];

static ReplaySnapshot *slots;
static int slot_name[SLOTS];
static int order[SLOTS];
static int norder;
static uint8_t *chunks[CHUNKS];
static int takefail, exists, rnd, nres;

static const char *const kNames[3] = {
    "DEMO_MODE_SNAPSHOT", "REPLAY_MANAGER_STATE", "OTHER"
};

static int name_code(const char *name)
{
    if (strcmp(name, kNames[0]) == 0)
        return 0;
    if (strcmp(name, kNames[1]) == 0)
        return 1;
    return 2;
}

// A snapshot pointer: a slot S0..S7, a chunk C0..C5, NULL or ?.
static void snap_label(char *out, const void *p)
{
    int k;

    if (p == NULL) {
        strcpy(out, "NULL");
        return;
    }
    for (k = 0; k < SLOTS; k++)
        if (p == (const void *)&slots[k]) {
            sprintf(out, "S%d", k);
            return;
        }
    for (k = 0; k < CHUNKS; k++)
        if (p == (const void *)(chunks[k] + 8)) {
            sprintf(out, "C%d", k);
            return;
        }
    strcpy(out, "?");
}

static int slot_of(const ReplaySnapshot *s)
{
    int k;

    for (k = 0; k < SLOTS; k++)
        if (s == &slots[k])
            return k;
    return -1;
}

static void order_remove(int k)
{
    int i, j;

    for (i = j = 0; i < norder; i++)
        if (order[i] != k)
            order[j++] = order[i];
    norder = j;
    slot_name[k] = -1;
}

// ---------------------------------------------------------------- stubs

ReplaySnapshot *replaymgr_find_snapshot(ReplayManager *rm, const char *name,
                                        int32_t k)
{
    int code = name_code(name), i, n = 0;
    char l[8];
    ReplaySnapshot *s = NULL;

    for (i = 0; i < norder; i++)
        if (slot_name[order[i]] == code && n++ == k) {
            s = &slots[order[i]];
            break;
        }
    snap_label(l, s);
    printf("  find%s %s %d %s\n", rm == (ReplayManager *)(void *)fake_rm
           ? "" : " rm?", code == 2 ? name : kNames[code], (int)k, l);
    return s;
}

ReplaySnapshot *replaymgr_take_snapshot(ReplayManager *rm, const char *name)
{
    int code = name_code(name), k;
    ReplaySnapshot *s = NULL;
    char l[8];

    if (!takefail) {
        for (k = 0; k < SLOTS && slot_name[k] >= 0; k++)
            ;
        if (k < SLOTS) {
            s = &slots[k];
            slot_name[k] = code;
            order[norder++] = k;
            s->Time = WorldTimer;
            s->EndTime = WorldTimer;
            s->BeginLoopTime = WorldLoopCounter;
            s->EndLoopTime = WorldLoopCounter;
        }
    }
    snap_label(l, s);
    printf("  take%s %s %s\n", rm == (ReplayManager *)(void *)fake_rm
           ? "" : " rm?", code == 2 ? name : kNames[code], l);
    return s;
}

int32_t replaymgr_delete_snapshot_named(ReplayManager *rm, const char *name)
{
    int code = name_code(name), i;

    for (i = 0; i < norder; i++)
        if (slot_name[order[i]] == code) {
            int k = order[i];

            printf("  delete%s %s S%d\n", rm == (ReplayManager *)(void *)fake_rm
                   ? "" : " rm?", kNames[code], k);
            order_remove(k);
            return 1;
        }
    printf("  delete%s %s none\n", rm == (ReplayManager *)(void *)fake_rm
           ? "" : " rm?", code == 2 ? name : kNames[code]);
    return 0;
}

void replaymgr_delete_snapshot(ReplayManager *rm, ReplaySnapshot *s)
{
    char l[8];
    int k = slot_of(s);

    snap_label(l, s);
    printf("  delete%s %s\n", rm == (ReplayManager *)(void *)fake_rm
           ? "" : " rm?", l);
    if (k >= 0)
        order_remove(k);
}

int32_t replaymgr_restore_snapshot_named(ReplayManager *rm, const char *name)
{
    int code = name_code(name);

    printf("  restore%s %s\n", rm == (ReplayManager *)(void *)fake_rm
           ? "" : " rm?", code == 2 ? name : kNames[code]);
    return 1;
}

void replaymgr_sort_snapshots(ReplayManager *rm, const char *name)
{
    int code = name_code(name);

    printf("  sort%s %s\n", rm == (ReplayManager *)(void *)fake_rm
           ? "" : " rm?", code == 2 ? name : kNames[code]);
}

void racecoordinator_post_message(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param)
{
    int k;
    char l[8] = "?";

    for (k = 0; k < SLOTS; k++)
        if ((int32_t)(intptr_t)&slots[k] == param)
            sprintf(l, "S%d", k);
    printf("  post%s %d %s\n", rc == (RaceCoordinator *)(void *)fake_rc
           ? "" : " rc?", (int)msg, l);
}

void race_parameters_init_with_defaults(RaceParameters *rp)
{
    printf("  rp init%s\n", rp == &TheRaceParameters ? "" : " ?");
}

void race_parameters_do_snapshot(RaceParameters *rp, struct ReplaySnapshot *s)
{
    char l[8];

    snap_label(l, s);
    printf("  rp snap%s %s pos %d take %d restore %d\n",
           rp == &TheRaceParameters ? "" : " ?", l, (int)s->DataPosition,
           (int)s->TakingSnapshotFlag, (int)s->RestoringSnapshotFlag);
    s->DataPosition += 52;
    s->TakingSnapshotFlag = 7;
}

ResourceFile *load_resource_file(const char *name, int32_t type,
                                 int32_t flags, ResourceFileCallback cb,
                                 intptr_t param)
{
    printf("  loadres %s %d %d %s %s\n", name, (int)type, (int)flags,
           cb == dmreplay_resource_file_loaded_callback ? "cb" : "?",
           param == (intptr_t)&TheDemoModeReplay ? "this" : "?");
    return NULL;
}

ResourceFile *find_resource_file_by_type(int32_t type)
{
    printf("  findres %d %d\n", (int)type, nres);
    return nres > 0 ? &fake_rf[nres - 1] : NULL;
}

void unload_resource_file(ResourceFile *rf)
{
    printf("  unloadres R%d\n", (int)(rf - fake_rf) + 1);
    nres--;
}

int32_t bFileSizeName(const char *name)
{
    printf("  exists %s\n", name);
    return exists ? 1000 : -1;
}

int32_t bRandomI(int32_t range, uint32_t *seed)
{
    printf("  random %d%s\n", (int)range, seed == &bDefaultSeed ? "" : " ?");
    return rnd;
}

static void save(void)
{
    printf("  save\n");
}

static void refresh(void)
{
    printf("  refresh\n");
}

// ---------------------------------------------------------------- dump

static void dump(void)
{
    DemoModeReplay *d = &TheDemoModeReplay;
    Link *l = (Link *)(void *)DemoModeReplay_SnapshotList;
    char rec[8], play[8], info[8], rep[8];
    int i;

    snap_label(rec, DemoModeReplay_pCurrentRecordingSnapshot);
    snap_label(play, DemoModeReplay_pCurrentPlayingSnapshot);
    snap_label(info, d->pInfo);
    snap_label(rep, p32_ptr(DemoModeReplay_pRepeat));
    printf("  obj %d %d %d file %d rec %d erase %d %s play %d %s tw %d %d %d"
           " info %s repeat %s rpdemo %d nres %d\n",
           (int)DemoModeReplayActiveFlag, (int)d->LoadingFlag,
           (int)d->LoadedFlag, (int)d->CurrentSnapshotFileNumber,
           (int)d->WantToBeRecordingSnapshot,
           (int)DemoModeReplay_WantToBeErasingSnapshot, rec,
           (int)d->PlayingSnapshotNumber, play,
           (int)d->TweakerSnapshotFileNumber, (int)d->TweakerSaveSnapshotFile,
           (int)d->TweakerEraseRecordedSnapshots, info, rep,
           (int)TheRaceParameters.ReplayDemoMode, nres);
    printf("  slots");
    for (i = 0; i < norder; i++) {
        ReplaySnapshot *s = &slots[order[i]];

        printf(" S%d:%d:%d:%d:%d:%d", order[i], slot_name[order[i]],
               (int)s->Time, (int)s->EndTime, (int)s->BeginLoopTime,
               (int)s->EndLoopTime);
    }
    printf("\n  list");
    if (l->Next == 0 && l->Prev == 0) {
        printf(" none\n");
        return;
    }
    {
        Link *a = (Link *)p32_ptr(l->Next);
        Link *prev = l;

        for (i = 0; a != l && i < 16; i++) {
            ReplaySnapshot *s = (ReplaySnapshot *)(void *)a;
            char c[8];

            snap_label(c, s);
            printf(" %s:%d:%d:%d:%d:%d%s", c, (int)s->MemoryImageLoadedFlag,
                   (int)s->DataPosition, (int)s->SizeofData,
                   (int)s->TakingSnapshotFlag, (int)s->RestoringSnapshotFlag,
                   p32_ptr(a->Prev) == prev ? "" : ":prev?");
            prev = a;
            a = (Link *)p32_ptr(a->Next);
        }
        printf("%s\n", (Link *)p32_ptr(l->Prev) == prev ? "" : " tail?");
    }
}

// ---------------------------------------------------------------- ops

static void *ptr_of(int v)
{
    if (v < 0)
        return NULL;
    if (v >= 100)
        return chunks[v - 100] + 8;
    return &slots[v];
}

static void op_state(char **f)
{
    DemoModeReplay *d = &TheDemoModeReplay;
    int k, info, repeat;

    if (atoi(f[1]))
        dmreplay_construct();
    WorldTimer = atoi(f[2]);
    WorldLoopCounter = atoi(f[3]);
    DemoModeReplayActiveFlag = atoi(f[4]);
    d->LoadingFlag = atoi(f[5]);
    d->LoadedFlag = atoi(f[6]);
    d->CurrentSnapshotFileNumber = atoi(f[7]);
    d->WantToBeRecordingSnapshot = atoi(f[8]);
    DemoModeReplay_WantToBeErasingSnapshot = atoi(f[9]);
    DemoModeReplay_pCurrentRecordingSnapshot = ptr_of(atoi(f[10]));
    d->PlayingSnapshotNumber = atoi(f[11]);
    DemoModeReplay_pCurrentPlayingSnapshot = ptr_of(atoi(f[12]));
    d->TweakerSnapshotFileNumber = atoi(f[13]);
    d->TweakerSaveSnapshotFile = atoi(f[14]);
    d->TweakerEraseRecordedSnapshots = atoi(f[15]);
    info = atoi(f[16]);
    d->pInfo = info < 0 ? NULL
             : (const DemoModeReplayInfo *)(void *)(chunks[info] + 8);
    repeat = atoi(f[17]);
    DemoModeReplay_pRepeat = repeat < 0 ? 0 : p32_of(chunks[repeat] + 8);
    TheRaceParameters.ReplayDemoMode = atoi(f[18]);
    takefail = atoi(f[19]);
    exists = atoi(f[20]);
    rnd = atoi(f[21]);
    nres = atoi(f[22]);
    {
        DemoModeReplayInfo *in = (DemoModeReplayInfo *)(void *)(chunks[0] + 8);

        in->VersionNumber = atoi(f[23]);
        in->New8 = atoi(f[24]);
    }
    norder = 0;
    for (k = 0; k < SLOTS; k++) {
        char **g = f + 25 + 5 * k;
        ReplaySnapshot *s = &slots[k];

        slot_name[k] = atoi(g[0]);
        s->Time = atoi(g[1]);
        s->EndTime = atoi(g[2]);
        s->BeginLoopTime = atoi(g[3]);
        s->EndLoopTime = atoi(g[4]);
        if (slot_name[k] >= 0)
            order[norder++] = k;
    }
    printf("state\n");
    dump();
}

static void op_chunk(char **f, int unload)
{
    int k = atoi(f[1]);
    uint32_t type = (uint32_t)strtoul(f[2], NULL, 10);
    int r;

    memcpy(chunks[k], &type, 4);
    r = unload ? dmreplay_unloader(chunks[k]) : dmreplay_loader(chunks[k]);
    printf("%s C%d %u\n  ret %d\n", unload ? "unload" : "load", k,
           (unsigned)type, r);
    dump();
}

static void op_base(char **f)
{
    int i = atoi(f[1]);
    char name[DEMO_MODE_REPLAY_FILENAME_SIZE];

    dmreplay_generate_filename(name, i);
    printf("base %d %s [%s]\n", i, dmreplay_get_base_filename(i), name);
}

static void op_call(char **f, int nf)
{
    const char *n = f[1];
    int a = nf > 2 ? atoi(f[2]) : 0;
    int r = 0;

    printf("call %s%s%s\n", n, nf > 2 ? " " : "", nf > 2 ? f[2] : "");
    if (!strcmp(n, "loadres"))
        dmreplay_load_resource_file();
    else if (!strcmp(n, "unloadres"))
        dmreplay_unload_resource_file();
    else if (!strcmp(n, "cb"))
        dmreplay_resource_file_loaded_callback(
            (intptr_t)&TheDemoModeReplay);
    else if (!strcmp(n, "consider"))
        r = dmreplay_consider_launching();
    else if (!strcmp(n, "launch"))
        dmreplay_launch();
    else if (!strcmp(n, "restore"))
        dmreplay_restore_race_parameters_snapshot();
    else if (!strcmp(n, "begin"))
        dmreplay_begin_demo_mode();
    else if (!strcmp(n, "numsnaps"))
        r = dmreplay_get_num_snapshots();
    else if (!strcmp(n, "cantest"))
        r = dmreplay_can_test_demo_mode();
    else if (!strcmp(n, "begintest"))
        dmreplay_begin_demo_mode_test();
    else if (!strcmp(n, "goeson"))
        r = dmreplay_test_goes_on();
    else if (!strcmp(n, "servicedemo"))
        dmreplay_service_demo_mode(a);
    else if (!strcmp(n, "end"))
        dmreplay_end_demo_mode();
    else if (!strcmp(n, "service"))
        dmreplay_service(a);
    else if (!strcmp(n, "beginrec"))
        dmreplay_begin_recording_snapshot();
    else if (!strcmp(n, "endrec"))
        dmreplay_end_recording_snapshot(a);
    else if (!strcmp(n, "erase"))
        dmreplay_erase_recorded_snapshots();
    else
        printf("  unknown\n");
    printf("  ret %d\n", r);
    dump();
}

int main(int argc, char **argv)
{
    FILE *fp;
    char line[2048];
    int k;

    if (argc < 2 || (fp = fopen(argv[1], "r")) == NULL)
        return 2;
    slots = calloc(SLOTS, sizeof(ReplaySnapshot));
    for (k = 0; k < CHUNKS; k++)
        chunks[k] = calloc(1, 8 + sizeof(ReplaySnapshot));
    for (k = 0; k < SLOTS; k++)
        slot_name[k] = -1;
    pReplayManager = (ReplayManager *)(void *)fake_rm;
    pRaceCoordinator = (RaceCoordinator *)(void *)fake_rc;
    gDemoModeReplaySaveFn = save;
    gDemoModeReplayRefreshTweakerFn = refresh;
    while (fgets(line, sizeof line, fp)) {
        char *f[80];
        int nf = 0;
        char *t = strtok(line, " \r\n");

        while (t != NULL && nf < 80) {
            f[nf++] = t;
            t = strtok(NULL, " \r\n");
        }
        if (nf == 0)
            continue;
        if (!strcmp(f[0], "state"))
            op_state(f);
        else if (!strcmp(f[0], "load"))
            op_chunk(f, 0);
        else if (!strcmp(f[0], "unload"))
            op_chunk(f, 1);
        else if (!strcmp(f[0], "base"))
            op_base(f);
        else if (!strcmp(f[0], "ctor")) {
            dmreplay_construct();
            printf("ctor\n");
            dump();
        }
        else if (!strcmp(f[0], "call"))
            op_call(f, nf);
        fflush(stdout);
    }
    printf("faults 0\n");
    fclose(fp);
    return 0;
}
