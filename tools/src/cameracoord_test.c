// Harness for tools/cameracoord_check.py: runs the checker's op script on
// the port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out, and stands in for what the checker stubs.
//
//     cameracoord_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bmem.h"
#include "cameracoord.h"
#include "player.h"
#include "race.h"
#include "racefinish.h"
#include "vtable.h"

enum {
    OP_TAG, OP_PUT, OP_JUNKL, OP_INITL, OP_SINIT, OP_LOAD, OP_UNLOAD,
    OP_DUMPL, OP_POKEL, OP_POKEP, OP_SEED, OP_SHAKE, OP_FIND, OP_KEEP,
    OP_PARSE, OP_CCNEW, OP_CDNEW, OP_CCDEL, OP_CCDELETE, OP_RAWDTOR,
    OP_DISABLE, OP_ENABLE, OP_MARK, OP_UPDATE, OP_CDUPDATE, OP_SETMOVER,
    OP_SETF, OP_CD, OP_JUNKK, OP_DUMPK
};

// The loader's fields OP_POKEL sets, and the lists OP_POKEP writes into.
enum { L_HL, L_FB, L_PRE, L_POST, L_NIS, L_PN0, L_PN1, L_SHAKES, L_SHAKEP };
enum { LIST_HL, LIST_FB, LIST_PRE, LIST_POST, LIST_NIS, LIST_PN0, LIST_PN1 };

// A coordinator's fields OP_SETF sets.
enum { F_DISABLED, F_VIEW, F_NEED, F_NUMBER, F_VPTR, F_PLAYER };

#define ARENA_SIZE (4u << 20)
#define NEAR       0x100000
#define NK         8
#define NMOVERS    4
#define MAX_HEAP   4096
#define SLACK      16

// The test coordinator table, whose destructor and Update print.
#define FAKE_COORD_VT 0x01e0b000u

// The arena: the checker's chunks, at the same offsets on both sides.
static uint8_t *arena;

static union {
    CountdownCameraCoordinator c;
    unsigned char b[0x100];
} ks[NK];

static CameraMover   movers[NMOVERS];
static struct Player players[2];
static char          cars[2][16];
static char          race_mem[16];

static struct { void *p; size_t span; } heap[MAX_HEAP];
static int nheap;

static int     junk_byte = -1;
static int32_t countdown_number;

// What the linked files leave to the game.
Race *pCurrentRace;

// ---------------------------------------------------------------- input

static int32_t *words_in;
static size_t   nwords_in;
static int32_t *rd;

static int32_t next(void)
{
    if ((size_t)(rd - words_in) >= nwords_in) {
        fprintf(stderr, "script ran out\n");
        exit(2);
    }
    return *rd++;
}

static char **read_strings(int32_t *n)
{
    int32_t i, k = next();
    char  **out = calloc((size_t)(k > 0 ? k : 1), sizeof *out);

    for (i = 0; i < k; i++) {
        int32_t j, len = next();

        out[i] = malloc((size_t)len + 1);
        for (j = 0; j < len; j++)
            out[i][j] = (char)next();
        out[i][len] = 0;
    }
    *n = k;
    return out;
}

static float fbits(uint32_t b)
{
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static uint32_t bitsf(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

// ---------------------------------------------------------------- labels

static int is_junk(const void *field, size_t n)
{
    const unsigned char *b = field;
    size_t i;

    if (junk_byte < 0)
        return 0;
    for (i = 0; i < n; i++)
        if (b[i] != (unsigned char)junk_byte)
            return 0;
    return 1;
}

static const char *lab(const void *a)
{
    static char bufs[8][48];
    static int  which;
    char       *buf = bufs[which++ & 7];
    uintptr_t   p = (uintptr_t)a;
    int         i;

    if (a == NULL)
        return "null";
    if (is_junk(&a, sizeof a))
        return "junk";
    if (p + NEAR >= (uintptr_t)arena
        && p < (uintptr_t)arena + ARENA_SIZE + NEAR) {
        snprintf(buf, 48, "a%+ld", (long)((intptr_t)p - (intptr_t)arena));
        return buf;
    }
    if (a == &CameraCoordinatorList)
        return "list";
    for (i = 0; i < NK; i++)
        if (a == &ks[i]) {
            snprintf(buf, 48, "k%d", i);
            return buf;
        }
    for (i = 0; i < NMOVERS; i++)
        if (a == &movers[i]) {
            snprintf(buf, 48, "m%d", i);
            return buf;
        }
    for (i = 0; i < 2; i++) {
        if (a == &players[i]) {
            snprintf(buf, 48, "p%d", i);
            return buf;
        }
        if (a == cars[i]) {
            snprintf(buf, 48, "car%d", i);
            return buf;
        }
    }
    if (a == race_mem)
        return "race";
    for (i = 0; i < nheap; i++)
        if (a == heap[i].p) {
            snprintf(buf, 48, "h%d", i);
            return buf;
        }
    return "?";
}

// ---------------------------------------------------------------- memory

static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    size_t span = (size > 0 ? (size_t)size : 0) + SLACK;
    void  *p = malloc(span);

    if (nheap >= MAX_HEAP) {
        fprintf(stderr, "heap log full\n");
        exit(3);
    }
    memset(p, 0xcd, span);
    heap[nheap].p = p;
    heap[nheap].span = span;
    printf("  alloc h%d size %d name %s flags %d pool %d\n", nheap, size,
           name, flags, pool);
    nheap++;
    return p;
}

// Kept, so no address is handed out twice.
static void free_hook(void *p)
{
    printf("  free %s\n", lab(p));
}

// ---------------------------------------------------------------- the stand-ins

int32_t race_get_countdown_number_to_display(const Race *r)
{
    printf("  countdown %s\n", lab(r));
    return countdown_number;
}

static void mover_destroy(CameraMover *m)
{
    printf("  mover dtor %s\n", lab(m));
}

static void mover_enable(CameraMover *m)
{
    printf("  mover enable %s\n", lab(m));
}

static void mover_disable(CameraMover *m)
{
    printf("  mover disable %s\n", lab(m));
}

static const CameraMoverVtbl fake_mover_vt = {
    .Destroy = mover_destroy,
    .Enable = mover_enable,
    .Disable = mover_disable,
};

static void dump_cd_read(const char *head, const CameraDataItems *cd);

static CameraMover *bumper(void *mem, int32_t viewID, struct Car *car,
                           CameraDataItems *cd)
{
    printf("  bumper %s view %d car %s\n", lab(mem), viewID, lab(car));
    dump_cd_read("  bumper cd", cd);
    ((CameraMover *)mem)->vtbl = &fake_mover_vt;
    return (CameraMover *)mem;
}

static void fake_dtor(void *c, int32_t flags)
{
    printf("  fake dtor %s %d\n", lab(c), flags);
}

static void fake_update(void *c, float dt)
{
    printf("  fake update %s %08x\n", lab(c), bitsf(dt));
}

static const VtEntry fake_coord_vt[CAMERACOORDINATOR_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)fake_dtor },
    { 0, 0, (VtFn)fake_update },
};

// ---------------------------------------------------------------- dumps

static void word(const void *f)
{
    uint32_t v;

    memcpy(&v, f, 4);
    printf(" %08x", v);
}

static void dump_cd(const char *head, const CameraDataItems *cd)
{
    printf("%s", head);
    word(&cd->Type);
    printf(" %s", lab(cd->Name));
    word(&cd->IsFOVIso);
    word(&cd->MinPercent);
    word(&cd->MaxPercent);
    word(&cd->EyeSplineSpeed);
    word(&cd->LookSplineSpeed);
    word(&cd->FOVSplineSpeed);
    word(&cd->LockEyeSpeedToCar);
    word(&cd->LockLookSpeedToCar);
    word(&cd->MinAreaPercent);
    word(&cd->MaxAreaPercent);
    word(&cd->NearClip);
    word(&cd->FarClip);
    word(&cd->Backwards);
    printf(" %s", lab(cd->FOVTable));
    word(&cd->NumAreaVerts);
    printf(" %s", lab(cd->AreaVerts));
    word(&cd->NumAreaFaces);
    printf(" %s", lab(cd->AreaFaces));
    word(&cd->NumEyeVerts);
    printf(" %s %s", lab(cd->EyeVerts), lab(cd->BankVerts));
    word(&cd->NumLookVerts);
    printf(" %s", lab(cd->LookVerts));
    word(&cd->SpringXVel);
    word(&cd->SpringYVel);
    word(&cd->SpringZVel);
    word(&cd->SpringDamp);
    word(&cd->SpringConst);
    word(&cd->LookOffsetX);
    word(&cd->LookOffsetY);
    word(&cd->LookOffsetZ);
    word(&cd->EnterVertComp);
    word(&cd->EnterHorizComp);
    word(&cd->LeaveVertComp);
    word(&cd->LeaveHorizComp);
    word(&cd->IsLeaveSet);
    word(&cd->WipeDistance);
    word(&cd->WipeAutoDisable);
    word(&cd->ShakeBankNumber);
    printf("\n");
}

// What the parser has set of a block of cd's type: the Update's
// CameraDataItems is a local nothing clears, so the rest is the stack's.
// Type 2 alone reads FOVSplineSpeed; type 0 alone the look offset, the
// enter and leave components and the wipe.
static void dump_cd_read(const char *head, const CameraDataItems *cd)
{
    int t = cd->Type;

    printf("%s", head);
    word(&cd->Type);
    printf(" %s", lab(cd->Name));
    if (t < 0 || t > 2) {
        printf("\n");
        return;
    }
    word(&cd->IsFOVIso);
    word(&cd->MinPercent);
    word(&cd->MaxPercent);
    word(&cd->EyeSplineSpeed);
    word(&cd->LookSplineSpeed);
    if (t == 2)
        word(&cd->FOVSplineSpeed);
    word(&cd->LockEyeSpeedToCar);
    word(&cd->LockLookSpeedToCar);
    word(&cd->MinAreaPercent);
    word(&cd->MaxAreaPercent);
    word(&cd->NearClip);
    word(&cd->FarClip);
    word(&cd->Backwards);
    printf(" %s", lab(cd->FOVTable));
    word(&cd->NumAreaVerts);
    printf(" %s", lab(cd->AreaVerts));
    word(&cd->NumAreaFaces);
    printf(" %s", lab(cd->AreaFaces));
    word(&cd->NumEyeVerts);
    printf(" %s %s", lab(cd->EyeVerts), lab(cd->BankVerts));
    word(&cd->NumLookVerts);
    printf(" %s", lab(cd->LookVerts));
    word(&cd->SpringXVel);
    word(&cd->SpringYVel);
    word(&cd->SpringZVel);
    word(&cd->SpringDamp);
    word(&cd->SpringConst);
    if (t == 0) {
        word(&cd->LookOffsetX);
        word(&cd->LookOffsetY);
        word(&cd->LookOffsetZ);
        word(&cd->EnterVertComp);
        word(&cd->EnterHorizComp);
        word(&cd->LeaveVertComp);
        word(&cd->LeaveHorizComp);
        word(&cd->IsLeaveSet);
        word(&cd->WipeDistance);
        word(&cd->WipeAutoDisable);
    }
    word(&cd->ShakeBankNumber);
    printf("\n");
}

// A list of pointers, runs of one label merged.
static void dump_list(const char *name, int32_t count, char *const *list,
                      int n)
{
    int i = 0;

    printf("  %s %d:", name, count);
    while (i < n) {
        char first[48];
        int  j = i + 1;

        snprintf(first, sizeof first, "%s", lab(list[i]));
        while (j < n && strcmp(lab(list[j]), first) == 0)
            j++;
        if (j - i > 1)
            printf(" %s*%d", first, j - i);
        else
            printf(" %s", first);
        i = j;
    }
    printf("\n");
}

static void dump_loader(void)
{
    const CameraLoader *cl = &TheCameraLoader;

    printf("loader\n");
    dump_list("hl", cl->NumHighlightCameras, cl->HighlightCameraData,
              CAMERA_LOADER_HIGHLIGHTS);
    dump_list("fb", cl->NumFlyByCameras, cl->FlyByCameraData,
              CAMERA_LOADER_LIST);
    dump_list("pre", cl->NumPreRaceCameras, cl->PreRaceCameraData,
              CAMERA_LOADER_LIST);
    dump_list("post", cl->NumPostRaceCameras, cl->PostRaceCameraData,
              CAMERA_LOADER_LIST);
    dump_list("nis", cl->NumNisCameras, cl->NisCameraData,
              CAMERA_LOADER_NIS);
    dump_list("pn0", cl->NumPlayerNisCameras[0], cl->PlayerNisCameraData[0],
              CAMERA_LOADER_NIS);
    dump_list("pn1", cl->NumPlayerNisCameras[1], cl->PlayerNisCameraData[1],
              CAMERA_LOADER_NIS);
    printf("  shakes %d %s vortex", cl->NumCameraShakes,
           lab(cl->Shakes));
    word(&cl->TuningVortex.x);
    word(&cl->TuningVortex.y);
    word(&cl->TuningVortex.z);
    word(&cl->TuningVortex.pad);
    printf(" %d\n", cl->VortexCount);
}

static void dump_coordinators(void)
{
    const bNode *n;
    int i, guard;

    printf("coordinators");
    guard = 0;
    for (n = CameraCoordinatorList.next; n != &CameraCoordinatorList
         && guard < 64; n = n->next, guard++)
        printf(" %s", lab(n));
    printf(" /");
    guard = 0;
    for (n = CameraCoordinatorList.prev; n != &CameraCoordinatorList
         && guard < 64; n = n->prev, guard++)
        printf(" %s", lab(n));
    printf("\n");
    for (i = 0; i < NK; i++) {
        const CountdownCameraCoordinator *c = &ks[i].c;

        printf("  k%d %s %s %s", i, lab(c->Base.Node.next),
               lab(c->Base.Node.prev), lab(c->Base.pCameraMover));
        word(&c->Base.Disabled);
        word(&c->Base.ViewID);
        word(&c->Base.NeedToReloadCameraData);
        word(&c->Base._vtable);
        printf(" %s", lab(c->pPlayer));
        word(&c->CurrentCountdownNumber);
        printf("\n");
    }
}

// ---------------------------------------------------------------- helpers

static char **list_of(int k, int *n)
{
    CameraLoader *cl = &TheCameraLoader;

    switch (k) {
    case LIST_HL:   *n = CAMERA_LOADER_HIGHLIGHTS; return cl->HighlightCameraData;
    case LIST_FB:   *n = CAMERA_LOADER_LIST; return cl->FlyByCameraData;
    case LIST_PRE:  *n = CAMERA_LOADER_LIST; return cl->PreRaceCameraData;
    case LIST_POST: *n = CAMERA_LOADER_LIST; return cl->PostRaceCameraData;
    case LIST_NIS:  *n = CAMERA_LOADER_NIS; return cl->NisCameraData;
    case LIST_PN0:  *n = CAMERA_LOADER_NIS; return cl->PlayerNisCameraData[0];
    case LIST_PN1:  *n = CAMERA_LOADER_NIS; return cl->PlayerNisCameraData[1];
    }
    fprintf(stderr, "list %d\n", k);
    exit(2);
}

static void *at(int32_t off)
{
    if (off == -1)
        return NULL;
    if (off < 0 || (uint32_t)off >= ARENA_SIZE) {
        fprintf(stderr, "arena offset %d\n", off);
        exit(2);
    }
    return arena + off;
}

static BaseCameraCoordinator *k_of(int32_t k)
{
    if (k < 0 || k >= NK) {
        fprintf(stderr, "coordinator %d\n", k);
        exit(2);
    }
    return &ks[k].c.Base;
}

typedef void (*DtorFn)(void *c, int32_t flags);
typedef void (*UpdateFn)(void *c, float dt);

int main(int argc, char **argv)
{
    FILE   *fp;
    long    len;
    int32_t ntags, nflat;
    char  **tags;
    int32_t *end;
    int     i;

    if (argc != 2) {
        fprintf(stderr, "usage: cameracoord_test ops.bin\n");
        return 2;
    }
    fp = fopen(argv[1], "rb");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    fseek(fp, 0, SEEK_END);
    len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    words_in = malloc((size_t)len);
    nwords_in = (size_t)len / 4;
    if (fread(words_in, 4, nwords_in, fp) != nwords_in) {
        fprintf(stderr, "short read\n");
        return 2;
    }
    fclose(fp);
    rd = words_in;

    tags = read_strings(&ntags);
    nflat = next();
    end = rd + (size_t)nflat;

    arena = aligned_alloc(16, ARENA_SIZE);
    memset(arena, 0, ARENA_SIZE);
    bSetMemoryHooks(malloc_hook, free_hook);
    vt_reset();
    cameracoord_install_vtables();
    vt_install(FAKE_COORD_VT, fake_coord_vt, CAMERACOORDINATOR_VT_ENTRIES);
    gBumperCameraMoverFn = bumper;
    pCurrentRace = (Race *)(void *)race_mem;
    for (i = 0; i < NMOVERS; i++)
        movers[i].vtbl = &fake_mover_vt;
    for (i = 0; i < 2; i++)
        players[i].MyCar = (struct Car *)(void *)cars[i];

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_PUT: {
            int32_t off = next(), n = next(), j;
            uint8_t *p = at(off);

            for (j = 0; j < n; j += 4) {
                int32_t w = next();
                int     m = n - j < 4 ? n - j : 4;

                memcpy(p + j, &w, (size_t)m);
            }
            break;
        }
        case OP_JUNKL:
            junk_byte = next() & 0xff;
            memset(&TheCameraLoader, junk_byte, sizeof TheCameraLoader);
            break;
        case OP_INITL:
            printf("init\n");
            camera_loader_init(&TheCameraLoader);
            break;
        case OP_SINIT:
            printf("sinit\n");
            cameracoord_static_init();
            break;
        case OP_LOAD: {
            int32_t off = next();
            printf("load %s\n", lab(at(off)));
            printf("load -> %d\n", loader_cameras(at(off)));
            break;
        }
        case OP_UNLOAD: {
            int32_t off = next();
            printf("unload %s\n", lab(at(off)));
            printf("unload -> %d\n", unloader_cameras(at(off)));
            break;
        }
        case OP_DUMPL:
            dump_loader();
            break;
        case OP_POKEL: {
            int32_t f = next(), v = next();
            CameraLoader *cl = &TheCameraLoader;

            switch (f) {
            case L_HL:      cl->NumHighlightCameras = v; break;
            case L_FB:      cl->NumFlyByCameras = v; break;
            case L_PRE:     cl->NumPreRaceCameras = v; break;
            case L_POST:    cl->NumPostRaceCameras = v; break;
            case L_NIS:     cl->NumNisCameras = v; break;
            case L_PN0:     cl->NumPlayerNisCameras[0] = v; break;
            case L_PN1:     cl->NumPlayerNisCameras[1] = v; break;
            case L_SHAKES:  cl->NumCameraShakes = v; break;
            case L_SHAKEP:  cl->Shakes = at(v); break;
            default:
                fprintf(stderr, "loader field %d\n", f);
                return 2;
            }
            break;
        }
        case OP_POKEP: {
            int32_t k = next(), idx = next(), off = next();
            int     n;
            char  **list = list_of(k, &n);

            if (idx < 0 || idx >= n) {
                fprintf(stderr, "slot %d\n", idx);
                return 2;
            }
            list[idx] = at(off);
            break;
        }
        case OP_SEED:
            bDefaultSeed = (uint32_t)next();
            break;
        case OP_SHAKE: {
            int32_t bank = next();
            CameraShake *s;

            printf("shake %d\n", bank);
            s = camera_loader_find_random_camera_shake(&TheCameraLoader,
                                                       bank);
            printf("shake -> %s seed %08x\n", lab(s), bDefaultSeed);
            break;
        }
        case OP_FIND: {
            const char *name = tags[next()];
            printf("find '%s'\n", name);
            printf("find -> %s\n",
                   lab(camera_loader_find_camera_data(&TheCameraLoader,
                                                      name)));
            break;
        }
        case OP_KEEP: {
            int32_t player = next();
            printf("keep %d\n", player);
            camera_loader_keep_nis_cameras(player);
            break;
        }
        case OP_PARSE: {
            int32_t off = next(), fill = next() & 0xff, save = junk_byte;
            CameraDataItems cd;
            CameraDataItems *r;

            memset(&cd, fill, sizeof cd);
            junk_byte = fill;
            r = camera_data_items_parse(&cd, at(off));
            printf("parse %s -> %s\n", lab(at(off)),
                   r == &cd ? "cd" : "?");
            dump_cd(" ", &cd);
            junk_byte = save;
            break;
        }
        case OP_CCNEW: {
            int32_t k = next(), view = next();
            BaseCameraCoordinator *r;

            printf("ccnew k%d %d\n", k, view);
            r = camera_coordinator_init(k_of(k), view);
            printf("ccnew -> %s\n", lab(r));
            break;
        }
        case OP_CDNEW: {
            int32_t k = next(), view = next(), p = next();
            CountdownCameraCoordinator *r;

            printf("cdnew k%d %d p%d\n", k, view, p);
            r = countdown_camera_coordinator_init(
                (CountdownCameraCoordinator *)(void *)k_of(k), view,
                &players[p & 1]);
            printf("cdnew -> %s\n", lab(r));
            break;
        }
        case OP_CCDEL: {
            int32_t k = next(), flags = next();
            BaseCameraCoordinator *c = k_of(k);
            const VtEntry *e = vt_slot(c->_vtable, CAMERACOORDINATOR_VT_DTOR);

            printf("ccdel k%d %d\n", k, flags);
            ((DtorFn)e->fn)(vt_this(c, e), flags);
            break;
        }
        case OP_CCDELETE: {
            int32_t k = next();
            printf("ccdelete k%d\n", k);
            camera_coordinator_delete(k_of(k));
            break;
        }
        case OP_RAWDTOR: {
            int32_t k = next(), flags = next(), which = next();
            printf("rawdtor k%d %d %d\n", k, flags, which);
            if (which)
                countdown_camera_coordinator_destroy(
                    (CountdownCameraCoordinator *)(void *)k_of(k), flags);
            else
                camera_coordinator_destroy(k_of(k), flags);
            break;
        }
        case OP_DISABLE: {
            int32_t k = next();
            printf("disable k%d\n", k);
            camera_coordinator_disable(k_of(k));
            break;
        }
        case OP_ENABLE: {
            int32_t k = next();
            printf("enable k%d\n", k);
            camera_coordinator_enable(k_of(k));
            break;
        }
        case OP_MARK:
            printf("mark\n");
            mark_camera_data_as_needing_to_be_reloaded();
            break;
        case OP_UPDATE: {
            float dt = fbits((uint32_t)next());
            printf("update %08x\n", bitsf(dt));
            update_camera_coordinators(dt);
            break;
        }
        case OP_CDUPDATE: {
            int32_t k = next();
            float dt = fbits((uint32_t)next());
            printf("cdupdate k%d %08x\n", k, bitsf(dt));
            countdown_camera_coordinator_update(
                (CountdownCameraCoordinator *)(void *)k_of(k), dt);
            break;
        }
        case OP_SETMOVER: {
            int32_t k = next(), m = next();
            k_of(k)->pCameraMover = m < 0 ? NULL : &movers[m % NMOVERS];
            break;
        }
        case OP_SETF: {
            int32_t k = next(), f = next(), v = next();
            CountdownCameraCoordinator *c =
                (CountdownCameraCoordinator *)(void *)k_of(k);

            switch (f) {
            case F_DISABLED: c->Base.Disabled = v; break;
            case F_VIEW:     c->Base.ViewID = v; break;
            case F_NEED:     c->Base.NeedToReloadCameraData = v; break;
            case F_NUMBER:   c->CurrentCountdownNumber = v; break;
            case F_VPTR:     c->Base._vtable = (uint32_t)v; break;
            case F_PLAYER:   c->pPlayer = &players[v & 1]; break;
            default:
                fprintf(stderr, "coordinator field %d\n", f);
                return 2;
            }
            break;
        }
        case OP_CD:
            countdown_number = next();
            break;
        case OP_JUNKK: {
            int32_t k = next(), b = next() & 0xff;
            (void)k_of(k);
            memset(&ks[k], b, sizeof ks[0]);
            break;
        }
        case OP_DUMPK:
            dump_coordinators();
            break;
        default:
            fprintf(stderr, "op %d\n", op);
            return 2;
        }
    }
    return 0;
}
