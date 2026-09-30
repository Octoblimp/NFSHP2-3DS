// Host harness for 3DS Files/source/playercam.c, Player's camera functions.
// Runs the op script tools/playercam_check.py writes and prints the
// transcript it diffs against the retail image, run in mipsemu over the
// same script.
//
// playercam.c is the only port source here. The harness owns everything it
// calls: bMalloc and bFree over a numbered arena, the drive and orbit
// constructors and SetPOVIndex, a fake vtable for every mover, the seams,
// and World. Each prints its arguments in the model's words, and the
// constructors set only the Type and vtable a real one would. The check is
// of the dispatch, not the movers: drivecam_check and orbit_check have
// those.
//
// Two pools of movers: a0, a1, ... from bMalloc (and the jump seam), in
// the order they are asked for, and x0, x1, ... that the script makes
// itself to hand the player, so the script always knows their names.
// Every mover's memory is filled with 0xa5 when it is handed out, and the
// Player too, so a field one side writes and the other does not shows.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "camerainfo.h"
#include "cammover.h"
#include "car.h"
#include "drivecam.h"
#include "orbitcam.h"
#include "player.h"
#include "playercam.h"
#include "world.h"

#define NOBJ 1024               // a0 .. a1023
#define NX 256                  // x0 .. x255, at NOBJ ..
#define OBJ_BYTES 4096
#define NCAR 4
#define PATTERN 0xa5

// The harness prints the retail size for sizeof, so neither may stand for
// a size another case asks for.
typedef char sizes_distinct[
    (sizeof(DriveCameraMover) != sizeof(OrbitCarCameraMover)
     && sizeof(DriveCameraMover) != 44 && sizeof(DriveCameraMover) != 76
     && sizeof(DriveCameraMover) != 160 && sizeof(DriveCameraMover) != 872
     && sizeof(DriveCameraMover) != 1104
     && sizeof(OrbitCarCameraMover) != 44 && sizeof(OrbitCarCameraMover) != 76
     && sizeof(OrbitCarCameraMover) != 160
     && sizeof(OrbitCarCameraMover) != 872
     && sizeof(OrbitCarCameraMover) != 1104) ? 1 : -1];

World *pCurrentWorld;

static World world;
static struct Car cars[NCAR];
static RideInfo rides[NCAR];
static struct Player player;
static int skipFE;

// Stand-ins the Player points at, by address only.
static int32_t coDemo[8], coCount[8], coNis[8], nisMgr[8], line[8], route[8];
static int32_t cameraInfo[8];

static _Alignas(16) unsigned char arena[NOBJ + NX][OBJ_BYTES];
static int nobj, nx;
static struct {
    const char *kind;   // what built it
    int live;
    int info;           // GetCameraInfo answers cameraInfo, or NULL
    int pov[4];         // each POV's Type, -1 for none
} meta[NOBJ + NX];
static POV povs[NOBJ + NX][4];
static int defInfo, defPov[4];

static int obj_index(const void *p)
{
    const unsigned char *c = p;
    size_t off;

    if (c < arena[0] || c >= arena[NOBJ + NX])
        return -1;
    off = (size_t)(c - arena[0]);
    return off % OBJ_BYTES ? -1 : (int)(off / OBJ_BYTES);
}

static int pov_index(const void *p)
{
    const unsigned char *c = p;
    size_t off;

    if (c < (const unsigned char *)povs
        || c >= (const unsigned char *)povs + sizeof povs)
        return -1;
    off = (size_t)(c - (const unsigned char *)povs);
    return off % sizeof(POV) ? -1 : (int)(off / sizeof(POV));
}

static const char *obj_name(char *b, int i)
{
    if (i < NOBJ)
        sprintf(b, "a%d", i);
    else
        sprintf(b, "x%d", i - NOBJ);
    return b;
}

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    int i;

    if (p == NULL)
        return "null";
    if (p == &world)
        return "w";
    if (p == (const char *)&world + offsetof(struct Car, State.Position))
        return "w.pos";
    if (p == &player)
        return "pl";
    if (p == coDemo)
        return "cd";
    if (p == coCount)
        return "cc";
    if (p == coNis)
        return "cn";
    if (p == nisMgr)
        return "nm";
    if (p == line)
        return "ln";
    if (p == route)
        return "rt";
    if (p == cameraInfo)
        return "ci";
    i = obj_index(p);
    if (i >= 0)
        return obj_name(b, i);
    i = pov_index(p);
    if (i >= 0) {
        char o[16];

        sprintf(b, "%s.p%d", obj_name(o, i / 4), i % 4);
        return b;
    }
    for (i = 0; i < NCAR; i++) {
        if (p == &cars[i]) {
            sprintf(b, "k%d", i);
            return b;
        }
        if (p == &cars[i].State.Position) {
            sprintf(b, "k%d.pos", i);
            return b;
        }
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

static void *new_obj(int i, const char *kind)
{
    memset(arena[i], PATTERN, OBJ_BYTES);
    meta[i].kind = kind;
    meta[i].live = 1;
    meta[i].info = defInfo;
    memcpy(meta[i].pov, defPov, sizeof defPov);
    return arena[i];
}

static void *new_a(const char *kind)
{
    if (nobj >= NOBJ) {
        fprintf(stderr, "arena full\n");
        exit(3);
    }
    return new_obj(nobj++, kind);
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p = new_a("?");
    int shown = size;

    if (size == (int)sizeof(DriveCameraMover))
        shown = 1008;
    else if (size == (int)sizeof(OrbitCarCameraMover))
        shown = 208;
    printf("  malloc %d %s %d %d -> %s\n", shown, name, flags, pool, nm(p));
    return p;
}

void bFree(void *p)
{
    int i = obj_index(p);

    printf("  free %s\n", nm(p));
    if (i >= 0)
        meta[i].live = 0;
}

// ------------------------------------------------------- the fake vtable

static void f_destroy(CameraMover *m)
{
    printf("  destroy %s flag 3\n", nm(m));
}

static const CameraInfo *f_info(CameraMover *m)
{
    int i = obj_index(m);
    const CameraInfo *r = meta[i].info ? (const CameraInfo *)cameraInfo : NULL;

    printf("  info %s -> %s\n", nm(m), nm(r));
    return r;
}

static const POV *f_pov(CameraMover *m, int index)
{
    int i = obj_index(m);
    const POV *r = NULL;

    if (index >= 0 && index < 4 && meta[i].pov[index] >= 0) {
        povs[i][index].Type = meta[i].pov[index];
        r = &povs[i][index];
    }
    printf("  getpov %s %d -> %s\n", nm(m), index, nm(r));
    return r;
}

static void f_enable(CameraMover *m)
{
    printf("  enable %s\n", nm(m));
}

static void f_disable(CameraMover *m)
{
    printf("  disable %s\n", nm(m));
}

static const CameraMoverVtbl fakeVtbl = {
    f_destroy, NULL, NULL, NULL, NULL, f_info, f_pov, NULL, NULL, NULL,
    NULL, f_enable, f_disable, NULL, NULL,
};

static void *built(void *mem, const char *kind, int type)
{
    CameraMover *m = mem;
    int i = obj_index(mem);

    if (i >= 0)
        meta[i].kind = kind;
    m->Type = (CameraMoverType)type;
    m->vtbl = &fakeVtbl;
    return m;
}

// ------------------------------------------------- the movers playercam.c calls

void drive_cam_init(DriveCameraMover *d, int viewID, struct Car *car,
                    int povIndex, float lookbackSpeed, int disableLag,
                    int lookBack, int perfectFocus)
{
    printf("  drive %s view %d car %s pov %d speed %s lag %d lb %d focus %d\n",
           nm(d), viewID, nm(car), povIndex, fx(lookbackSpeed), disableLag,
           lookBack, perfectFocus);
    built(d, "drive", CM_DRIVE);
}

void drive_cam_set_pov_index(DriveCameraMover *d, int index)
{
    printf("  setpov %s %d\n", nm(d), index);
}

void orbit_init(OrbitCarCameraMover *o, int viewID, struct Car *car,
                JoystickPort port)
{
    printf("  orbit %s view %d car %s port %d\n", nm(o), viewID, nm(car),
           (int)port);
    built(o, "orbit", CM_ORBIT_CAR);
}

// --------------------------------------------------------------- the seams

static void s_codel(void *c)
{
    printf("  codel %s flag 3\n", nm(c));
}

static void s_coen(void *c)
{
    printf("  coen %s\n", nm(c));
}

static void s_codis(void *c)
{
    printf("  codis %s\n", nm(c));
}

static void s_nisdel(struct NisManager *m, struct NisCameraCoordinator *c)
{
    printf("  nisdel %s %s\n", nm(m), nm(c));
}

static void s_nisen(struct NisManager *m, struct NisCameraCoordinator *c)
{
    printf("  nisen %s %s\n", nm(m), nm(c));
}

static void s_nisdis(struct NisManager *m, struct NisCameraCoordinator *c)
{
    printf("  nisdis %s %s\n", nm(m), nm(c));
}

static void s_lineen(struct VisibleDrivingLine *l)
{
    printf("  lineen %s\n", nm(l));
}

static void s_linedis(struct VisibleDrivingLine *l)
{
    printf("  linedis %s\n", nm(l));
}

static CameraMover *s_dw(void *mem, int viewID, const bVector3 *pos,
                         const bVector3 *dir, JoystickPort port)
{
    printf("  dw %s view %d pos %s %s %s %s dir %s %s %s port %d\n", nm(mem),
           viewID, fx(pos->x), fx(pos->y), fx(pos->z), fx(pos->pad),
           fx(dir->x), fx(dir->y), fx(dir->z), (int)port);
    return built(mem, "dw", CM_DEBUG_WORLD);
}

static CameraMover *s_tre(void *mem, int viewID, JoystickPort port)
{
    printf("  tre %s view %d port %d\n", nm(mem), viewID, (int)port);
    return built(mem, "tre", CM_TRACK_ROUTE_EDITOR);
}

static CameraMover *s_zf(void *mem, int viewID, struct Car *car,
                         CameraMover *saved)
{
    printf("  zf %s view %d car %s saved %s\n", nm(mem), viewID, nm(car),
           nm(saved));
    return built(mem, "zf", CM_ZONE_FREEZE);
}

static CameraMover *s_zp(void *mem, int viewID, struct PreviewRoute *r,
                         bVector3 *pos)
{
    printf("  zp %s view %d route %s pos %s\n", nm(mem), viewID, nm(r),
           nm(pos));
    return built(mem, "zp", CM_ZONE_PREVIEW);
}

static CameraMover *s_cubic(void *mem, int viewID, struct Car *car)
{
    printf("  cubic %s view %d car %s\n", nm(mem), viewID, nm(car));
    return built(mem, "cubic", CM_CUBIC_DAMPER);
}

static void s_routedel(struct PreviewRoute *r)
{
    printf("  routedel %s flag 3\n", nm(r));
}

static CameraMover *s_jump(struct Player *p, struct Car *car, int second)
{
    void *mem = new_a("jump");

    printf("  jump %s car %s second %d -> %s\n", nm(p), nm(car), second,
           nm(mem));
    return built(mem, "jump", CM_ZONE_JUMPER + second);
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

static struct Car *car_of(int i)
{
    return i < 0 ? NULL : &cars[i];
}

static CameraMover *x_of(int i)
{
    return i < 0 ? NULL : (CameraMover *)arena[NOBJ + i];
}

static void reset(void)
{
    int i;

    nobj = nx = 0;
    memset(meta, 0, sizeof meta);
    memset(povs, PATTERN, sizeof povs);
    defInfo = 1;
    defPov[0] = 0;
    defPov[1] = 1;
    defPov[2] = 2;
    defPov[3] = 1;
    memset(&player, PATTERN, sizeof player);
    player.MyCar = &cars[0];
    player.ViewID = 0;
    player.PlayerSettings.DriveCameraPOVIndex = 0;
    player.PlayerSettings.CameraSpring = 0;
    player.pRoute = NULL;
    player.pCameraMover = NULL;
    player.pSavedCameraMover = NULL;
    player.pSavedCameraMover2 = NULL;
    player.pRVMCameraMover = NULL;
    player.pDemoCameraCoordinator = NULL;
    player.pCountdownCameraCoordinator = NULL;
    player.pNisCameraCoordinator = NULL;
    player.pVisibleDrivingLine = NULL;
    player.pNisManager = (struct NisManager *)nisMgr;
    player.bLookBack = 0;
    skipFE = 0;
    memset(cars, PATTERN, sizeof cars);
    for (i = 0; i < NCAR; i++) {
        memset(&rides[i], PATTERN, sizeof rides[i]);
        rides[i].HasDash = 0;
        cars[i].pRideInfo = &rides[i];
    }
    world.CarList.next = &cars[0];
}

static void set_field(const char *f, int v)
{
    struct Player *p = &player;

    if (!strcmp(f, "car"))
        p->MyCar = car_of(v);
    else if (!strcmp(f, "view"))
        p->ViewID = v;
    else if (!strcmp(f, "pov"))
        p->PlayerSettings.DriveCameraPOVIndex = (int8_t)v;
    else if (!strcmp(f, "spring"))
        p->PlayerSettings.CameraSpring = v;
    else if (!strcmp(f, "look"))
        p->bLookBack = v;
    else if (!strcmp(f, "route"))
        p->pRoute = v ? (struct PreviewRoute *)route : NULL;
    else if (!strcmp(f, "cur"))
        p->pCameraMover = x_of(v);
    else if (!strcmp(f, "saved"))
        p->pSavedCameraMover = x_of(v);
    else if (!strcmp(f, "saved2"))
        p->pSavedCameraMover2 = x_of(v);
    else if (!strcmp(f, "rvm"))
        p->pRVMCameraMover = x_of(v);
    else if (!strcmp(f, "demo"))
        p->pDemoCameraCoordinator =
            v ? (struct DemoCameraCoordinator *)coDemo : NULL;
    else if (!strcmp(f, "count"))
        p->pCountdownCameraCoordinator =
            v ? (struct CountdownCameraCoordinator *)coCount : NULL;
    else if (!strcmp(f, "nis"))
        p->pNisCameraCoordinator =
            v ? (struct NisCameraCoordinator *)coNis : NULL;
    else if (!strcmp(f, "line"))
        p->pVisibleDrivingLine = v ? (struct VisibleDrivingLine *)line : NULL;
    else if (!strcmp(f, "skip"))
        skipFE = v;
    else {
        fprintf(stderr, "bad field %s\n", f);
        exit(2);
    }
}

static void dump_obj(int i)
{
    const CameraMover *m = (const CameraMover *)arena[i];
    char o[16];

    if (!meta[i].live)
        return;
    printf("  %s %s type %d player %s", obj_name(o, i), meta[i].kind,
           (int)m->Type, nm(m->pPlayer));
    if (m->Type == CM_DRIVE)
        printf(" lb %s",
               fx(((const DriveCameraMover *)m)->DesiredLookBackParam));
    printf("\n");
}

static void dump(void)
{
    const struct Player *p = &player;
    int i;

    printf("  pl car %s view %d pov %d spring %d look %d route %s cur %s"
           " saved %s saved2 %s rvm %s demo %s count %s nis %s line %s"
           " mgr %s\n",
           nm(p->MyCar), p->ViewID, p->PlayerSettings.DriveCameraPOVIndex,
           p->PlayerSettings.CameraSpring, p->bLookBack, nm(p->pRoute),
           nm(p->pCameraMover), nm(p->pSavedCameraMover),
           nm(p->pSavedCameraMover2), nm(p->pRVMCameraMover),
           nm(p->pDemoCameraCoordinator), nm(p->pCountdownCameraCoordinator),
           nm(p->pNisCameraCoordinator), nm(p->pVisibleDrivingLine),
           nm(p->pNisManager));
    for (i = 0; i < nobj; i++)
        dump_obj(i);
    for (i = 0; i < nx; i++)
        dump_obj(NOBJ + i);
}

static void set_pov_config(int i)
{
    int k;

    meta[i].info = itok();
    for (k = 0; k < 4; k++)
        meta[i].pov[k] = itok();
}

int main(int argc, char **argv)
{
    static char text[4096];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: playercam_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    pCurrentWorld = &world;
    gPlayerCamSkipFE = &skipFE;
    gCameraCoordinatorDeleteFn = s_codel;
    gCameraCoordinatorEnableFn = s_coen;
    gCameraCoordinatorDisableFn = s_codis;
    gNisDeleteCameraCoordinatorFn = s_nisdel;
    gNisEnableCameraCoordinatorFn = s_nisen;
    gNisDisableCameraCoordinatorFn = s_nisdis;
    gVisibleDrivingLineEnableFn = s_lineen;
    gVisibleDrivingLineDisableFn = s_linedis;
    gDebugWorldCameraMoverFn = s_dw;
    gTrackRouteEditorCameraMoverFn = s_tre;
    gZoneFreezeCameraMoverFn = s_zf;
    gZonePreviewCameraMoverFn = s_zp;
    gCubicCameraMoverFn = s_cubic;
    gPreviewRouteDeleteFn = s_routedel;
    gPlayerJumpCamMoverFn = s_jump;

    while (fgets(text, sizeof text, fp) != NULL) {
        char echo[64];
        char *t;

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

            set_field(f, itok());
            break;
        }
        case 'W': {
            int i = itok();

            world.CarList.next = i < 0 ? (void *)&world : (void *)&cars[i];
            break;
        }
        case 'H': {
            int i = itok();

            rides[i].HasDash = (int8_t)itok();
            break;
        }
        case 'K': {
            int i = itok();

            cars[i].State.Position.x = from_bits(htok());
            cars[i].State.Position.y = from_bits(htok());
            cars[i].State.Position.z = from_bits(htok());
            cars[i].State.Position.pad = from_bits(htok());
            break;
        }
        case 'F': {
            int k;

            defInfo = itok();
            for (k = 0; k < 4; k++)
                defPov[k] = itok();
            break;
        }
        case 'I':
            set_pov_config(NOBJ + itok());
            break;
        case 'J': {
            // The current mover's POVs; the numbers are read regardless.
            int i = obj_index(player.pCameraMover);

            if (i < 0) {
                int k;

                for (k = 0; k < 5; k++)
                    itok();
            } else {
                set_pov_config(i);
            }
            break;
        }
        case 'X': {
            int type = itok();
            void *m;

            if (nx >= NX) {
                fprintf(stderr, "x pool full\n");
                return 3;
            }
            m = new_obj(NOBJ + nx++, "x");
            printf("  new %s\n", nm(m));
            built(m, "x", type);
            break;
        }
        case 'Y':
            if (player.pCameraMover != NULL)
                player.pCameraMover->Type = (CameraMoverType)itok();
            break;
        case 'C': {
            int type = itok();

            player_change_camera_mover(&player, (CameraMoverType)type,
                                       itok());
            break;
        }
        case 'Q': {
            int r = player_cycle_drive_camera_pov_index(&player, itok());

            printf("  cycle -> %d\n", r);
            break;
        }
        case 'R':
            // Retail calls Enable through NULL with nothing saved, so the
            // script only restores what was saved.
            if (player.pSavedCameraMover == NULL)
                printf("  nothing saved\n");
            else
                player_restore_camera_mover(&player);
            break;
        case 'M':
            player_remove_camera_movers(&player);
            break;
        case 'E':
            player_enable_camera_movers(&player);
            break;
        case 'D':
            player_disable_camera_movers(&player);
            break;
        default:
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
        dump();
    }
    fclose(fp);
    return 0;
}
