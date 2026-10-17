// nis_test -- tools/nis_check.py's harness.
//
// Runs nisinfo.c and nismanager.c over the checker's script. What they call
// is a stub here that logs its arguments, as the model's stubs do: the NIS
// player's Load, SetupCarsBeforeNIS, StartAnimating, StopAnimating and
// RestoreCarsAfterNIS, the resource files' UnloadResourceFile and
// ServiceResourceLoading, eModel's destructor and bFree. Pointers print as
// names: M0 and M1 the managers, L NisManagerList, A0 and A1 cars, R0 and
// R1 resource files, M0.pc0 .. M1.oc1 the props, and a record of the table
// as I and its index.
//
//     nis_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "emodel.h"
#include "nisinfo.h"
#include "nismanager.h"
#include "realtime.h"
#include "replay.h"
#include "world.h"

#define NM    2
#define MAXT  64
#define NREC  12

int32_t WorldTimeFrames;

static NisManager mgrs[NM];
static char       cars[2][16];
static char       rfs[2][16];
static uint8_t    chunk_raw[8 + 160 * NREC + 16];
static uint8_t   *chunk;

// The service stub clears svc_target's LoadingNisNumber on its svc_at'th
// call, and every manager's from the 64th, whatever the script said.
static int        svc_at = 1, svc_n;
static NisManager *svc_target;
// The Load stub sets the manager's LoadingNisNumber to this, but -2.
static int32_t    load_sets = -2;

static uint32_t hx(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static int ix(const char *s)
{
    return (int)strtol(s, NULL, 0);
}

// ---------------------------------------------------------------- names

static const char *sym(const void *p)
{
    static char b[4][24];
    static int  k;
    int         i;

    if (p == NULL)
        return "0";
    if (p == (const void *)&NisManagerList)
        return "L";
    k = (k + 1) & 3;
    for (i = 0; i < NM; i++) {
        if (p == (const void *)&mgrs[i]) {
            snprintf(b[k], 24, "M%d", i);
            return b[k];
        }
        if (p == (const void *)&mgrs[i].PlayerCharProps[0]
            || p == (const void *)&mgrs[i].PlayerCharProps[1]) {
            snprintf(b[k], 24, "M%d.pc%d", i,
                     p == (const void *)&mgrs[i].PlayerCharProps[1]);
            return b[k];
        }
        if (p == (const void *)&mgrs[i].OtherCharProps[0]
            || p == (const void *)&mgrs[i].OtherCharProps[1]) {
            snprintf(b[k], 24, "M%d.oc%d", i,
                     p == (const void *)&mgrs[i].OtherCharProps[1]);
            return b[k];
        }
    }
    for (i = 0; i < 2; i++) {
        if (p == (const void *)cars[i]) {
            snprintf(b[k], 24, "A%d", i);
            return b[k];
        }
        if (p == (const void *)rfs[i]) {
            snprintf(b[k], 24, "R%d", i);
            return b[k];
        }
    }
    if (chunk != NULL && (const uint8_t *)p >= chunk + 8
        && (const uint8_t *)p < chunk + 8 + 160 * NREC
        && ((const uint8_t *)p - (chunk + 8)) % 160 == 0) {
        snprintf(b[k], 24, "I%d", (int)(((const uint8_t *)p - (chunk + 8))
                                        / 160));
        return b[k];
    }
    return "?";
}

// --------------------------------------------------------------- stubs

void bFree(void *p)
{
    printf("  free %s\n", sym(p));
}

void emodel_delete(eModel *m, int32_t flags)
{
    printf("  emodel_dtor %s %d\n", sym(m), (int)flags);
}

static void load(NisManager *m, int32_t nis)
{
    printf("  load %s %d\n", sym(m), (int)nis);
    if (load_sets != -2)
        m->LoadingNisNumber = load_sets;
}

static void setup(NisManager *m)
{
    printf("  setup %s\n", sym(m));
}

static void anim_on(NisManager *m)
{
    printf("  anim_on %s\n", sym(m));
}

static void anim_off(NisManager *m)
{
    printf("  anim_off %s\n", sym(m));
}

static void restore(NisManager *m)
{
    printf("  restore %s\n", sym(m));
}

static void unload_rf(struct ResourceFile *rf)
{
    printf("  unload_rf %s\n", sym(rf));
}

static int32_t service(void)
{
    svc_n++;
    printf("  svc %d\n", svc_n);
    if (svc_n == svc_at && svc_target != NULL)
        svc_target->LoadingNisNumber = -1;
    if (svc_n >= 64) {
        int k;

        for (k = 0; k < NM; k++)
            mgrs[k].LoadingNisNumber = -1;
    }
    return 0;
}

// ---------------------------------------------------------------- dumps

static void dump_name(const char *s)
{
    int i;

    printf(" name '");
    for (i = 0; i < 32 && s[i] != 0; i++) {
        unsigned char c = (unsigned char)s[i];

        if (c < 0x20 || c > 0x7e || c == '\'' || c == '\\')
            printf("\\x%02x", c);
        else
            putchar(c);
    }
    printf("'");
}

static uint32_t fw(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static void dump_mi(const NisModelInfo *mi)
{
    printf(" %s %08x %08x %08x %08x %s", sym(mi->pAnimation),
           (unsigned)fw(mi->Offset.x), (unsigned)fw(mi->Offset.y),
           (unsigned)fw(mi->Offset.z), (unsigned)fw(mi->Offset.pad),
           sym(mi->pCarWeStoleAnimationFrom));
}

static void dump_prop(const eModel *e)
{
    printf(" %08x %s %s %d %d", (unsigned)e->NameHash, sym(e->Solid),
           sym(e->pReplacementTextureTable), e->NumReplacementTextures,
           e->RigidAnimationStartTime);
}

static void dump(void)
{
    int k, i;

    printf("L next %s prev %s\n", sym(NisManagerList.next),
           sym(NisManagerList.prev));
    printf("T %s n %d\n", NisInfoTable == NULL ? "0"
                          : (uint8_t *)NisInfoTable == chunk + 8 ? "C+8"
                                                                  : "?",
           (int)NumNisInfos);
    for (k = 0; k < NM; k++) {
        NisManager *m = &mgrs[k];

        printf("M%d n %s p %s psf %08x lded %d ling %d ld %d nrf %s crf %s "
               "num %d", k, sym(m->Node.next), sym(m->Node.prev),
               (unsigned)m->PrevSoundEventFrame, (int)m->LoadedNisNumber,
               (int)m->LoadingNisNumber, (int)m->LoadNisNumber,
               sym(m->NisResourceFile), sym(m->CamResourceFile),
               (int)m->PlayerNumber);
        dump_name(m->Name);
        printf("\n");
        printf("M%d play %d st %d et %d nis %d cam %d pc %s oc %s anim %d "
               "views %d omm %d pmm %d\n", k, (int)m->Playing,
               (int)m->StartTime, (int)m->EndTime, (int)m->NisNumber,
               (int)m->CamNumber, sym(m->PlayerCar), sym(m->OtherCar),
               (int)m->Animating, (int)m->ViewsWatchingNis,
               (int)m->OtherCarMovementModeBeforeNIS,
               (int)m->PlayerCarMovementModeBeforeNIS);
        printf("M%d ri %d %08x", k, (int)m->NisRendInfo.NumFrames,
               (unsigned)fw(m->NisRendInfo.fElevation));
        dump_mi(&m->NisRendInfo.PlayerModelInfo);
        dump_mi(&m->NisRendInfo.OtherModelInfo);
        printf("\n");
        printf("M%d props", k);
        for (i = 0; i < 2; i++)
            dump_prop(&m->PlayerCharProps[i]);
        for (i = 0; i < 2; i++)
            dump_prop(&m->OtherCharProps[i]);
        printf("\n");
    }
}

// ------------------------------------------------------------------ ops

static void *named(const char *s)
{
    if (strcmp(s, "0") == 0)
        return NULL;
    if (s[0] == 'A')
        return cars[ix(s + 1)];
    if (s[0] == 'R')
        return rfs[ix(s + 1)];
    if (s[0] == 'M')
        return &mgrs[ix(s + 1)];
    if (strcmp(s, "L") == 0)
        return &NisManagerList;
    if (strcmp(s, "?") == 0)
        return (void *)(uintptr_t)0xa5a5a5a5a5a5a5a5ull;
    fprintf(stderr, "bad name %s\n", s);
    exit(2);
}

static void set_field(NisManager *m, const char *f, const char *v)
{
    int32_t n = (int32_t)hx(v);

    if (strcmp(f, "lded") == 0)
        m->LoadedNisNumber = n;
    else if (strcmp(f, "ling") == 0)
        m->LoadingNisNumber = n;
    else if (strcmp(f, "ld") == 0)
        m->LoadNisNumber = n;
    else if (strcmp(f, "play") == 0)
        m->Playing = n;
    else if (strcmp(f, "st") == 0)
        m->StartTime = n;
    else if (strcmp(f, "et") == 0)
        m->EndTime = n;
    else if (strcmp(f, "nis") == 0)
        m->NisNumber = n;
    else if (strcmp(f, "cam") == 0)
        m->CamNumber = n;
    else if (strcmp(f, "anim") == 0)
        m->Animating = n;
    else if (strcmp(f, "nrf") == 0)
        m->NisResourceFile = named(v);
    else if (strcmp(f, "crf") == 0)
        m->CamResourceFile = named(v);
    else if (strcmp(f, "pc") == 0)
        m->PlayerCar = named(v);
    else if (strcmp(f, "oc") == 0)
        m->OtherCar = named(v);
    else {
        fprintf(stderr, "bad field %s\n", f);
        exit(2);
    }
}

static void reset(void)
{
    NisInfoTable = NULL;
    NumNisInfos = 0;
    NisManagerList.next = &NisManagerList;
    NisManagerList.prev = &NisManagerList;
    WorldTimeFrames = 0;
    memset(mgrs, 0, sizeof mgrs);
    memset(chunk, 0, 8 + 160 * NREC);
    svc_at = 1;
    svc_n = 0;
    svc_target = NULL;
    load_sets = -2;
}

static int split(char *s, char **t)
{
    int n = 0;

    t[n++] = s;
    for (; *s; s++) {
        if (*s == '|' && n < MAXT) {
            *s = 0;
            t[n++] = s + 1;
        }
    }
    return n;
}

static void run(char **t, int n)
{
    const char *o = t[0];

    if (strcmp(o, "reset") == 0) {
        reset();
        return;
    } else if (strcmp(o, "rec") == 0) {
        // rec|i|type|nisnumber|frames|cameras
        NisInfo *r = (NisInfo *)(void *)(chunk + 8 + 160 * ix(t[1]));

        memset(r, 0, sizeof *r);
        snprintf(r->Name, sizeof r->Name, "NIS_%02d", ix(t[1]));
        r->Type = (int32_t)hx(t[2]);
        r->NisNumber = (int32_t)hx(t[3]);
        r->NumFrames = (int32_t)hx(t[4]);
        r->NumCameras = (int32_t)hx(t[5]);
        return;
    } else if (strcmp(o, "hdr") == 0) {
        uint32_t w[2] = { hx(t[1]), hx(t[2]) };

        memcpy(chunk, w, sizeof w);
        return;
    } else if (strcmp(o, "wtf") == 0) {
        WorldTimeFrames = (int32_t)hx(t[1]);
        return;
    } else if (strcmp(o, "fill") == 0) {
        memset(&mgrs[ix(t[1])], (int)hx(t[2]), sizeof mgrs[0]);
        return;
    } else if (strcmp(o, "set") == 0) {
        set_field(&mgrs[ix(t[1])], t[2], t[3]);
        return;
    } else if (strcmp(o, "svc") == 0) {
        svc_at = ix(t[1]);
        svc_n = 0;
        svc_target = &mgrs[ix(t[2])];
        return;
    } else if (strcmp(o, "ldv") == 0) {
        load_sets = (int32_t)hx(t[1]);
        return;
    }

    if (strcmp(o, "loader") == 0) {
        printf("loader -> %d\n", loader_nis_info(chunk));
    } else if (strcmp(o, "unloader") == 0) {
        printf("unloader -> %d\n", unloader_nis_info(chunk));
    } else if (strcmp(o, "num") == 0) {
        printf("num %d -> %d\n", ix(t[1]),
               (int)get_num_nis_info((int32_t)hx(t[1])));
        return;
    } else if (strcmp(o, "get") == 0) {
        printf("get %d -> %s\n", ix(t[1]),
               sym(get_nis_info((int32_t)hx(t[1]))));
        return;
    } else if (strcmp(o, "gett") == 0) {
        printf("gett %d %d -> %s\n", ix(t[1]), ix(t[2]),
               sym(get_nis_info_by_type((int32_t)hx(t[1]),
                                        (int32_t)hx(t[2]))));
        return;
    } else if (strcmp(o, "ctor") == 0) {
        NisManager *r;

        printf("ctor M%s '%s' %d\n", t[1], t[2], ix(t[3]));
        r = nismanager_new(&mgrs[ix(t[1])], t[2], (int32_t)hx(t[3]));
        printf("  -> %s\n", sym(r));
    } else if (strcmp(o, "dtor") == 0) {
        printf("dtor M%s %d\n", t[1], ix(t[2]));
        nismanager_destruct(&mgrs[ix(t[1])], (int32_t)hx(t[2]));
    } else if (strcmp(o, "start") == 0) {
        printf("start M%s %d %d %s %s\n", t[1], ix(t[2]), ix(t[3]), t[4],
               t[5]);
        nismanager_start(&mgrs[ix(t[1])], (int32_t)hx(t[2]),
                         (int32_t)hx(t[3]), named(t[4]), named(t[5]));
    } else if (strcmp(o, "stop") == 0) {
        printf("stop M%s\n", t[1]);
        nismanager_stop(&mgrs[ix(t[1])]);
    } else if (strcmp(o, "unload") == 0) {
        printf("unload M%s\n", t[1]);
        nismanager_unload(&mgrs[ix(t[1])]);
    } else if (strcmp(o, "ensure") == 0) {
        printf("ensure M%s\n", t[1]);
        nismanager_ensure_nis_is_loaded(&mgrs[ix(t[1])]);
    } else if (strcmp(o, "adl") == 0) {
        printf("adl M%s -> %d\n", t[1],
               (int)nismanager_allow_debug_looping(&mgrs[ix(t[1])]));
        return;
    } else if (strcmp(o, "isp") == 0) {
        printf("isp M%s -> %d\n", t[1],
               (int)nismanager_is_playing(&mgrs[ix(t[1])]));
        return;
    } else {
        fprintf(stderr, "unknown op %s\n", o);
        exit(2);
    }
    (void)n;
    dump();
}

int main(int argc, char **argv)
{
    static char line[4096];
    char       *t[MAXT];
    FILE       *f;

    if (argc != 2) {
        fprintf(stderr, "usage: nis_test script\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    chunk = (uint8_t *)(((uintptr_t)chunk_raw + 15u) & ~(uintptr_t)15u);
    gNisManagerLoadFn = load;
    gNisSetupCarsBeforeNisFn = setup;
    gNisStartAnimatingFn = anim_on;
    gNisStopAnimatingFn = anim_off;
    gNisRestoreCarsAfterNisFn = restore;
    gNisUnloadResourceFileFn = unload_rf;
    gNisServiceResourceLoadingFn = service;
    reset();
    while (fgets(line, sizeof line, f) != NULL) {
        char *e = line + strlen(line);
        int   n;

        while (e > line && (e[-1] == '\n' || e[-1] == '\r'))
            *--e = 0;
        if (line[0] == 0)
            continue;
        n = split(line, t);
        run(t, n);
    }
    fclose(f);
    return 0;
}

// ----------------------------------------------- the snapshots, unreached
// The replay snapshot code in nismanager.c (TASKS 72d) calls these;
// nothing here takes a snapshot.

World *pCurrentWorld;

static void snapshot_unreached_72d(const char *f)
{
    fprintf(stderr, "%s reached\n", f);
    exit(3);
}

void ReplaySnapshot_MoveData(ReplaySnapshot *s, void *p, int32_t stored,
                             int32_t size, int32_t is_signed)
{
    (void)s; (void)p; (void)stored; (void)size; (void)is_signed;
    snapshot_unreached_72d("ReplaySnapshot_MoveData");
}

void ReplaySnapshot_BeginSection(ReplaySnapshot *s, void *object,
                                 const char *name)
{
    (void)s; (void)object; (void)name;
    snapshot_unreached_72d("ReplaySnapshot_BeginSection");
}

void ReplaySnapshot_EndSection(ReplaySnapshot *s)
{
    (void)s;
    snapshot_unreached_72d("ReplaySnapshot_EndSection");
}

void world_do_pointer_snapshot(const World *w, struct ReplaySnapshot *s,
                               struct Car **pp)
{
    (void)w; (void)s; (void)pp;
    snapshot_unreached_72d("world_do_pointer_snapshot");
}
