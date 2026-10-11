// Harness for tools/democam_check.py: runs the checker's op script on the
// port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out, and stands in for what the checker stubs: the cars,
// the World, the cameras, the players and the movers are the harness's
// own.
//
//     democam_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bmem.h"
#include "cameracoord.h"
#include "car.h"
#include "cartypeinfo.h"
#include "democam.h"
#include "eview.h"
#include "player.h"
#include "playercam.h"
#include "race.h"
#include "realtime.h"
#include "vtable.h"
#include "world.h"

enum {
    OP_TAG, OP_PUT, OP_SINIT, OP_LOAD, OP_UNLOAD, OP_SEED, OP_TIME, OP_DIR,
    OP_VMODE, OP_FOVZ, OP_CARV, OP_WCLEAR, OP_WADD, OP_CAMV, OP_CAMQ,
    OP_CAMDEF, OP_UPCAM, OP_JUNKK, OP_DCNEW, OP_DCUPDATE, OP_DCDEL,
    OP_SETMOVER, OP_MCAM, OP_SETF, OP_DUMPK, OP_FIND, OP_WLG, OP_NEAR,
    OP_BEGIN, OP_PSET, OP_DUMPP, OP_UPDATEALL
};

// OP_CARV's fields, OP_CAMV's, OP_SETF's and OP_PSET's.
enum { CV_POS = 0, CV_MAT = 4, CV_MIN = 20, CV_MAX = 23, CV_WRONG = 26,
       CV_FULL = 27, CV_SPLIT = 28 };
enum { KV_MAT = 0, KV_POS = 16, KV_NEAR = 20, KV_FOV = 21 };
enum { F_DIS, F_VIEW, F_NEED, F_LOOK, F_POV, F_START, F_ACTIVE, F_VORTEX,
       F_CAR };
enum { P_MYCAR, P_VIEW, P_DEMO };

#define ARENA_SIZE (4u << 20)
#define NEAR       0x100000
#define NK         8
#define NMOVERS    4
#define NCARS      6
#define NCAMS      8
#define MAX_HEAP   8192
#define MAX_CAMQ   64
#define SLACK      16

// The arena: the checker's chunks, at the same offsets on both sides.
static uint8_t *arena;

static union {
    DemoCameraCoordinator d;
    unsigned char b[0x100];
} ks[NK];

static CameraMover   movers[NMOVERS];
static struct Player players[2];
static struct Car    cars[NCARS];
static CarTypeInfo   infos[NCARS];
static World         world;
static Camera        cams[NCAMS];

static uint32_t box[NCARS][2][3];
static int32_t  wrong[NCARS];
static int32_t  vmode;
static int32_t  camq[MAX_CAMQ];
static int      ncamq;
static int32_t  camdef;
static int32_t  upcam = -1;

static struct { void *p; size_t span; } heap[MAX_HEAP];
static int nheap;

// What the linked files leave to the game.
World         *pCurrentWorld = &world;
int32_t        WorldTimeFrames;
uint16_t       aBaselineFovZ;
Race          *pCurrentRace;
RaceParameters TheRaceParameters;
int32_t        PlayerNumPlayers;
struct Player *PlayerPlayersByNumber[2];
struct Player *PlayerPlayersByIndex[2];
int32_t        TunePreRaceSequence;

int32_t race_get_countdown_number_to_display(const Race *r)
{
    (void)r;
    return 0;
}

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

// ---------------------------------------------------------------- labels

static const char *lab(const void *a)
{
    static char bufs[8][48];
    static int  which;
    char       *buf = bufs[which++ & 7];
    uintptr_t   p = (uintptr_t)a;
    int         i;

    if (a == NULL)
        return "null";
    if (p + NEAR >= (uintptr_t)arena
        && p < (uintptr_t)arena + ARENA_SIZE + NEAR) {
        snprintf(buf, 48, "a%+ld", (long)((intptr_t)p - (intptr_t)arena));
        return buf;
    }
    if (a == &CameraCoordinatorList)
        return "list";
    if (a == &world.CarList)
        return "world";
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
    for (i = 0; i < 2; i++)
        if (a == &players[i]) {
            snprintf(buf, 48, "p%d", i);
            return buf;
        }
    for (i = 0; i < NCARS; i++)
        if (a == &cars[i]) {
            snprintf(buf, 48, "car%d", i);
            return buf;
        }
    for (i = 0; i < NCAMS; i++)
        if (a == &cams[i]) {
            snprintf(buf, 48, "cam%d", i);
            return buf;
        }
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

int32_t car_is_facing_wrong_way(Car *c)
{
    printf("  wrongway %s\n", lab(c));
    return wrong[c - cars];
}

void car_get_car_space_bounding_box(Car *c, bVector3 *min, bVector3 *max)
{
    int i = (int)(c - cars);

    printf("  bbox %s\n", lab(c));
    memcpy(&min->x, &box[i][0][0], 4);
    memcpy(&min->y, &box[i][0][1], 4);
    memcpy(&min->z, &box[i][0][2], 4);
    memcpy(&max->x, &box[i][1][0], 4);
    memcpy(&max->y, &box[i][1][1], 4);
    memcpy(&max->z, &box[i][1][2], 4);
}

int32_t eGetCurrentViewMode(void)
{
    printf("  viewmode\n");
    return vmode;
}

void player_change_camera_mover(struct Player *p, CameraMoverType type,
                                int keep)
{
    printf("  change %s %d %d\n", lab(p), (int)type, keep);
}

static void mover_destroy(CameraMover *m)
{
    printf("  mover dtor %s\n", lab(m));
}

static void mover_update(CameraMover *m)
{
    if (upcam >= 0) {
        m->pCamera = &cams[upcam];
        upcam = -1;
    }
    printf("  mover update %s %s\n", lab(m), lab(m->pCamera));
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
    .Update = mover_update,
    .Enable = mover_enable,
    .Disable = mover_disable,
};

// The test table and the next of the script's cameras.
static const char *give_camera(CameraMover *m)
{
    static char buf[16];
    int32_t     cam = camdef;

    if (ncamq > 0) {
        cam = camq[0];
        memmove(camq, camq + 1, (size_t)(ncamq - 1) * sizeof camq[0]);
        ncamq--;
    }
    m->vtbl = &fake_mover_vt;
    m->pCamera = &cams[cam];
    snprintf(buf, sizeof buf, "cam%d", cam);
    return buf;
}

static void word(const void *f)
{
    uint32_t v;

    memcpy(&v, f, 4);
    printf(" %08x", v);
}

// What the parser has set of a block of cd's type: the Update's
// CameraDataItems is a local nothing clears, so the rest is the stack's.
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

static CameraMover *trackcar(void *mem, int32_t viewID, struct Car *car,
                             const CameraDataItems *cd,
                             const CameraShake *shake, int32_t focus)
{
    CameraMover *m = mem;
    const char  *cam = give_camera(m);
    int          o;

    printf("  trackcar %s view %d car %s focus %d %s\n", lab(m), viewID,
           lab(car), focus, cam);
    dump_cd_read("  trackcar cd", cd);
    printf("  shake");
    for (o = 0; o < 560; o += 4) {
        uint32_t v;

        memcpy(&v, (const char *)shake + o, 4);
        if (v)
            printf(" %d:%08x", o, v);
    }
    printf("\n");
    return m;
}

static CameraMover *bumper(void *mem, int32_t viewID, struct Car *car,
                           CameraDataItems *cd)
{
    CameraMover *m = mem;
    const char  *cam = give_camera(m);

    printf("  bumper %s view %d car %s %s\n", lab(m), viewID, lab(car), cam);
    dump_cd_read("  bumper cd", cd);
    return m;
}

static CameraMover *trackfly(void *mem, int32_t viewID, CameraDataItems *cd,
                             struct Car *car)
{
    CameraMover *m = mem;
    const char  *cam = give_camera(m);

    printf("  trackfly %s view %d car %s %s\n", lab(m), viewID, lab(car),
           cam);
    dump_cd_read("  trackfly cd", cd);
    return m;
}

static CameraMover *drive(void *mem, int32_t viewID, struct Car *car,
                          int32_t pov, float lookbackSpeed,
                          int32_t disableLag, int32_t lookBack,
                          int32_t perfectFocus)
{
    CameraMover *m = mem;
    const char  *cam = give_camera(m);
    uint32_t     sb;

    memcpy(&sb, &lookbackSpeed, 4);
    printf("  drive %s view %d car %s pov %d speed %08x lag %d back %d "
           "focus %d %s\n", lab(m), viewID, lab(car), pov, sb, disableLag,
           lookBack, perfectFocus, cam);
    return m;
}

// ---------------------------------------------------------------- dumps

static void coord_line(const DemoCameraCoordinator *c)
{
    printf("  %s %s %s %s", lab(c), lab(c->Base.Node.next),
           lab(c->Base.Node.prev), lab(c->Base.pCameraMover));
    word(&c->Base.Disabled);
    word(&c->Base.ViewID);
    word(&c->Base.NeedToReloadCameraData);
    word(&c->Base._vtable);
    printf(" %s", lab(c->pCar));
    word(&c->DefaultCameraLookback);
    word(&c->DefaultCameraPOV);
    word(&c->CurrentCameraStartTime);
    word(&c->CurrentlyActiveCameraData);
    word(&c->CurrVortexCount);
    printf("\n");
}

static void dump_coordinators(void)
{
    const bNode *n;
    int guard = 0;

    printf("coordinators");
    for (n = CameraCoordinatorList.next; n != &CameraCoordinatorList
         && guard < 64; n = n->next, guard++)
        printf(" %s", lab(n));
    printf("\n");
    guard = 0;
    for (n = CameraCoordinatorList.next; n != &CameraCoordinatorList
         && guard < 64; n = n->next, guard++)
        coord_line((const DemoCameraCoordinator *)(const void *)n);
}

static void dump_players(void)
{
    int i;

    printf("players\n");
    for (i = 0; i < 2; i++)
        printf("  p%d car %s view %08x demo %s\n", i,
               lab(players[i].MyCar), (uint32_t)players[i].ViewID,
               lab(players[i].pDemoCameraCoordinator));
}

// ---------------------------------------------------------------- helpers

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

static DemoCameraCoordinator *k_of(int32_t k)
{
    if (k < 0 || k >= NK) {
        fprintf(stderr, "coordinator %d\n", k);
        exit(2);
    }
    return &ks[k].d;
}

static struct Car *car_of(int32_t c)
{
    return c < 0 ? NULL : &cars[c % NCARS];
}

typedef void (*DtorFn)(void *c, int32_t flags);

int main(int argc, char **argv)
{
    FILE   *fp;
    long    len;
    int32_t ntags, nflat;
    char  **tags;
    int32_t *end;
    int     i;

    if (argc != 2) {
        fprintf(stderr, "usage: democam_test ops.bin\n");
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
    democam_install_vtables();
    gTrackCarCameraMoverFn = trackcar;
    gBumperCameraMoverFn = bumper;
    gTrackFlyCameraMoverFn = trackfly;
    gDriveCameraMoverFn = drive;
    for (i = 0; i < NMOVERS; i++)
        movers[i].vtbl = &fake_mover_vt;
    for (i = 0; i < NCARS; i++)
        cars[i].pCarTypeInfo = &infos[i];
    world.CarList.next = world.CarList.prev = &world.CarList;

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
        case OP_SINIT:
            cameracoord_static_init();
            break;
        case OP_LOAD: {
            int32_t off = next();
            int     r = loader_cameras(at(off));

            printf("load %s -> %d\n", lab(at(off)), r);
            break;
        }
        case OP_UNLOAD: {
            int32_t off = next();
            int     r = unloader_cameras(at(off));

            printf("unload %s -> %d\n", lab(at(off)), r);
            break;
        }
        case OP_SEED:
            bDefaultSeed = (uint32_t)next();
            break;
        case OP_TIME:
            WorldTimeFrames = next();
            break;
        case OP_DIR:
            TheRaceParameters.TrackDirection = next();
            break;
        case OP_VMODE:
            vmode = next();
            break;
        case OP_FOVZ:
            aBaselineFovZ = (uint16_t)next();
            break;
        case OP_CARV: {
            int32_t c = next(), f = next();
            uint32_t v = (uint32_t)next();

            if (f < CV_MAT)
                memcpy((char *)&cars[c].State.Position + 4 * f, &v, 4);
            else if (f < CV_MIN)
                memcpy((char *)&cars[c].State.BodyMatrix + 4 * (f - CV_MAT),
                       &v, 4);
            else if (f < CV_MAX)
                box[c][0][f - CV_MIN] = v;
            else if (f < CV_WRONG)
                box[c][1][f - CV_MAX] = v;
            else if (f == CV_WRONG)
                wrong[c] = (int32_t)v;
            else if (f == CV_FULL)
                infos[c].Camera.NumFullScreenPOVs = (int32_t)v;
            else if (f == CV_SPLIT)
                infos[c].Camera.NumSplitScreenPOVs = (int32_t)v;
            break;
        }
        case OP_WCLEAR:
            world.CarList.next = world.CarList.prev = &world.CarList;
            break;
        case OP_WADD: {
            struct Car *c = &cars[next()];
            CarNode    *last = world.CarList.prev;

            c->Link.next = (CarNode *)(void *)&world.CarList;
            c->Link.prev = last;
            last->next = &c->Link;
            world.CarList.prev = &c->Link;
            break;
        }
        case OP_CAMV: {
            int32_t k = next(), f = next();
            uint32_t v = (uint32_t)next();

            if (f < KV_POS)
                memcpy((char *)&cams[k].CurrentKey.Matrix + 4 * f, &v, 4);
            else if (f < KV_NEAR)
                memcpy((char *)&cams[k].CurrentKey.Position
                       + 4 * (f - KV_POS), &v, 4);
            else if (f == KV_NEAR)
                memcpy(&cams[k].CurrentKey.NearZ, &v, 4);
            else
                cams[k].CurrentKey.FieldOfView = (uint16_t)v;
            break;
        }
        case OP_CAMQ: {
            int32_t cam = next();

            if (cam < 0)
                ncamq = 0;
            else if (ncamq < MAX_CAMQ)
                camq[ncamq++] = cam;
            break;
        }
        case OP_CAMDEF:
            camdef = next();
            break;
        case OP_UPCAM:
            upcam = next();
            break;
        case OP_JUNKK: {
            int32_t k = next(), b = next();

            memset(&ks[k], b & 0xff, sizeof ks[k]);
            break;
        }
        case OP_DCNEW: {
            int32_t k = next(), view = next(), c = next();
            void   *r;

            printf("dcnew k%d %d %s\n", k, view, lab(car_of(c)));
            r = demo_camera_coordinator_construct(k_of(k), view, car_of(c));
            printf("dcnew -> %s\n", lab(r));
            coord_line(k_of(k));
            break;
        }
        case OP_DCUPDATE: {
            int32_t  k = next();
            uint32_t dt = (uint32_t)next();

            printf("update k%d %08x t %d\n", k, dt, WorldTimeFrames);
            demo_camera_coordinator_update(k_of(k), fbits(dt));
            coord_line(k_of(k));
            printf("  seed %08x\n", bDefaultSeed);
            break;
        }
        case OP_DCDEL: {
            int32_t k = next(), flags = next();
            DemoCameraCoordinator *c = k_of(k);
            const VtEntry *e = vt_slot(c->Base._vtable,
                                       CAMERACOORDINATOR_VT_DTOR);

            printf("dcdel k%d %d\n", k, flags);
            ((DtorFn)e->fn)(vt_this(c, e), flags);
            break;
        }
        case OP_SETMOVER: {
            int32_t k = next(), m = next();

            k_of(k)->Base.pCameraMover = m < 0 ? NULL
                                               : &movers[m % NMOVERS];
            break;
        }
        case OP_MCAM: {
            int32_t m = next(), cam = next();

            movers[m].pCamera = &cams[cam];
            break;
        }
        case OP_SETF: {
            int32_t k = next(), f = next(), v = next();
            DemoCameraCoordinator *c = k_of(k);

            switch (f) {
            case F_DIS:    c->Base.Disabled = v; break;
            case F_VIEW:   c->Base.ViewID = v; break;
            case F_NEED:   c->Base.NeedToReloadCameraData = v; break;
            case F_LOOK:   c->DefaultCameraLookback = v; break;
            case F_POV:    c->DefaultCameraPOV = v; break;
            case F_START:  c->CurrentCameraStartTime = v; break;
            case F_ACTIVE: c->CurrentlyActiveCameraData = v; break;
            case F_VORTEX: c->CurrVortexCount = v; break;
            case F_CAR:    c->pCar = car_of(v); break;
            }
            break;
        }
        case OP_DUMPK:
            dump_coordinators();
            break;
        case OP_FIND: {
            int32_t k = next(), c = next();
            int32_t r = demo_camera_coordinator_find_good_looking_highlight_camera(
                k_of(k), car_of(c));

            printf("find k%d %s -> %d\n", k, lab(car_of(c)), r);
            break;
        }
        case OP_WLG: {
            int32_t k = next(), idx = next(), c = next();
            int32_t r = demo_camera_coordinator_will_look_good_data(
                k_of(k), TheCameraLoader.HighlightCameraData[idx],
                car_of(c));

            printf("wlg k%d %d %s -> %d\n", k, idx, lab(car_of(c)), r);
            break;
        }
        case OP_NEAR: {
            int32_t cam = next(), c = next();
            int32_t r = camera_near_plane_cuts_car(&cams[cam], car_of(c));

            printf("near cam%d %s -> %d\n", cam, lab(car_of(c)), r);
            break;
        }
        case OP_BEGIN: {
            int32_t p = next(), c = next();

            printf("begin p%d %s\n", p, lab(car_of(c)));
            player_begin_demo_cameras(&players[p], car_of(c));
            break;
        }
        case OP_PSET: {
            int32_t p = next(), f = next(), v = next();

            if (f == P_MYCAR)
                players[p].MyCar = car_of(v);
            else if (f == P_VIEW)
                players[p].ViewID = v;
            else
                players[p].pDemoCameraCoordinator = v < 0 ? NULL
                    : (struct DemoCameraCoordinator *)k_of(v);
            break;
        }
        case OP_DUMPP:
            dump_players();
            break;
        case OP_UPDATEALL: {
            uint32_t dt = (uint32_t)next();

            printf("updateall %08x\n", dt);
            update_camera_coordinators(fbits(dt));
            printf("  seed %08x\n", bDefaultSeed);
            break;
        }
        default:
            fprintf(stderr, "op %d\n", op);
            return 2;
        }
    }
    return 0;
}
