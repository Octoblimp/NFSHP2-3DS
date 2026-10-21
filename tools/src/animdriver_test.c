// Harness for tools/animdriver_check.py: runs the checker's script on
// animdriver.c (with eanim.c, banim.c's bspline_seek, bquat.c, bmath.c,
// emath.c and eframe.c under it) and prints what the model prints for the
// retail image. See the checker's docstring.
//
//     animdriver_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "animdriver.h"
#include "banim.h"
#include "bchunk.h"
#include "bmath.h"
#include "bquat.h"
#include "car.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "drivecam.h"
#include "eanim.h"
#include "eframe.h"
#include "emodel.h"
#include "esolid.h"
#include "eview.h"
#include "realtime.h"
#include "replay.h"
#include "scenery.h"
#include "scenerycull.h"
#include "selcam.h"
#include "stomper.h"
#include "trackflow.h"

// ------------------------------------- what animdriver.c reaches for

// As realtime.c starts them, retail's data.
int32_t WorldTime = 1;
float   WorldTimeElapsed;
int32_t WorldLoopCounter = 100000;
int32_t AnimatedDriverNeedsFixup;
int32_t OverrideAnimatedDriverLOD;

#define MAX_CARS    4
#define MAX_CHARS   5
#define MAX_DRIVERS 4
#define MAX_SOLIDS  4
#define MAX_ANIMS   2
#define NUM_TYPES   64

static Car           s_car[MAX_CARS];
static RideInfo      s_ride[MAX_CARS];
static uint8_t       s_carDriver[MAX_CARS][16];
static uint16_t      s_steer[MAX_CARS];
static CharacterInfo s_char[MAX_CHARS];
static AnimatedDriver s_drv[MAX_DRIVERS];
static CarTypeInfo   s_types[NUM_TYPES];
static eAnimationSolid s_solid[MAX_SOLIDS];
static eAnimation    s_anim[MAX_ANIMS];
static int           s_viewMode;
static int           s_lookCar = -1, s_lookCop;
static uint16_t      s_lookAngle;

const CarTypeInfo *CarTypeInfoArray = s_types;

int32_t eGetCurrentViewMode(void)
{
    return s_viewMode;
}

Car *get_lookback_car(Car *car, int32_t *isCop)
{
    (void)car;
    *isCop = s_lookCop;
    return s_lookCar < 0 ? NULL : &s_car[s_lookCar];
}

uint16_t calculate_lookback_angle(const Car *from, const Car *to,
                                  const bMatrix4 *m)
{
    (void)from;
    (void)to;
    (void)m;
    return s_lookAngle;
}

static void unreached(const char *what);

// Retail's reads through the CarDriver unchecked, as car.c's does.
uint16_t car_get_steering(Car *c)
{
    if (c->pCarDriver == NULL)
        unreached("car_get_steering without a CarDriver");
    return s_steer[c - s_car];
}

void *bMalloc(uint32_t size, const char *file, int32_t line, int32_t flags)
{
    void *p;

    (void)file;
    (void)line;
    (void)flags;
    p = aligned_alloc(16, (size + 15u) & ~15u);
    memset(p, 0xa5, size);
    return p;
}

void bFree(void *p)
{
    free(p);
}

// What the two files link to and the script never reaches: the artwork,
// the replays, eAnimation's blend and box. Reaching one is a harness bug.
int32_t    eDirtyAnimations;
int32_t    nBoneScale = -1;
float      vBoneScale[4] = { 1.0f, 1.0f, 1.0f, 0.0f };
BSlotPool *eModelSlotPool;
void (*gEModelRenderFn)(eModel *m, bMatrix4 *matrix, void *light,
                        uint32_t flags);

static void unreached(const char *what)
{
    fprintf(stderr, "harness reached %s\n", what);
    exit(3);
}

void *bSlotOMalloc(BSlotPool *pool)
{
    (void)pool;
    unreached("bSlotOMalloc");
    return NULL;
}

void emodel_init(eModel *m, uint32_t name_hash)
{
    (void)m;
    (void)name_hash;
    unreached("emodel_init");
}

void emodel_uninit(eModel *m)
{
    (void)m;
    unreached("emodel_uninit");
}

void emodel_delete(eModel *m, int32_t flags)
{
    (void)m;
    (void)flags;
    unreached("emodel_delete");
}

void emodel_attach_replacement_texture_table(eModel *m,
                                             eReplacementTextureTable *t,
                                             int32_t count, int32_t instance)
{
    (void)m;
    (void)t;
    (void)count;
    (void)instance;
    unreached("emodel_attach_replacement_texture_table");
}

void emodel_get_bounding_box(const eModel *m, bVector3 *mn, bVector3 *mx)
{
    (void)m;
    (void)mn;
    (void)mx;
    unreached("emodel_get_bounding_box");
}

BodyTypeInfo *get_body_type_info(const char *name)
{
    (void)name;
    unreached("get_body_type_info");
    return NULL;
}

void ReplaySnapshot_BeginSection(ReplaySnapshot *s, void *object,
                                 const char *name)
{
    (void)s;
    (void)object;
    (void)name;
    unreached("ReplaySnapshot_BeginSection");
}

void ReplaySnapshot_EndSection(ReplaySnapshot *s)
{
    (void)s;
    unreached("ReplaySnapshot_EndSection");
}

void ReplaySnapshot_MoveData(ReplaySnapshot *s, void *p, int32_t stored,
                             int32_t size, int32_t is_signed)
{
    (void)s;
    (void)p;
    (void)stored;
    (void)size;
    (void)is_signed;
    unreached("ReplaySnapshot_MoveData");
}

void selcam_slerp(bQuaternion *o, bQuaternion *a, bQuaternion *b, float t)
{
    (void)o;
    (void)a;
    (void)b;
    (void)t;
    unreached("selcam_slerp");
}

void bInitializeBoundingBox3At(bVector3 *mn, bVector3 *mx, const bVector3 *p)
{
    (void)mn;
    (void)mx;
    (void)p;
    unreached("bInitializeBoundingBox3At");
}

void bExpandBoundingBox3(bVector3 *mn, bVector3 *mx, const bVector3 *p)
{
    (void)mn;
    (void)mx;
    (void)p;
    unreached("bExpandBoundingBox3");
}

// ----------------------------------------------------------- the draw

#define FRAME_BYTES 8192
#define MAX_NODES   48
#define MAX_MODELS  3

static _Alignas(16) uint8_t s_frame[FRAME_BYTES];
static eSolid             s_esolid[MAX_ANIMS];
static eAnimationTreeNode s_nodes[MAX_ANIMS][MAX_NODES];
static eModel             s_model[MAX_MODELS];
static bMatrix4           s_mtx;
static int                s_vis = 1;

// ------------------------------------------------------------- printing

static int row_of(const DriverAnimationInfo *info)
{
    if (info >= AnimationInfoTable && info < AnimationInfoTable + DRIVER_ANIM_NUM)
        return (int)(info - AnimationInfoTable);
    return info == NULL ? -1 : -2;
}

static uint32_t fbits(float f)
{
    uint32_t w;

    memcpy(&w, &f, 4);
    return w;
}

static void print_driver(int d)
{
    const AnimatedDriver *a = &s_drv[d];
    const BSpline        *s = a->pSteeringFrame;
    int                   i;

    printf(" |");
    for (i = 0; i < 2; i++) {
        const AnimationPlayer *p = &a->AnimationPlayers[i];

        printf(" p%d=%d,%d,%d,%d", i, row_of(p->pAnimationInfo),
               (int)p->StartTime, (int)p->EndTime, (int)p->PauseFrameNumber);
    }
    printf(" lb=%d db=%d cur=%d", (int)a->LookingBackwardsFlag,
           (int)a->DrivingBackwardsFlag, (int)a->CurrentLookingBackwardsType);
    if (s != NULL)
        printf(" spl=%08x,%08x,%08x,%08x,%08x,%08x,%08x,%d,%d",
               (unsigned)fbits(s->val), (unsigned)fbits(s->dval),
               (unsigned)fbits(s->valDesired), (unsigned)fbits(s->dvalDesired),
               (unsigned)fbits(s->time), (unsigned)fbits(s->duration),
               (unsigned)fbits(s->arrivalThreshold), (int)s->state,
               (int)s->flags);
    printf(" seed=%08x\n", (unsigned)bDefaultSeed);
}

static uint32_t crc32(const void *p, size_t n)
{
    const uint8_t *b = p;
    uint32_t       c = 0xffffffffu;
    size_t         i;
    int            k;

    for (i = 0; i < n; i++) {
        c ^= b[i];
        for (k = 0; k < 8; k++)
            c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
    }
    return ~c;
}

static void *read_file(const char *path, size_t *n)
{
    FILE *f = fopen(path, "rb");
    void *p;
    long  len;

    if (f == NULL) {
        fprintf(stderr, "no %s\n", path);
        exit(2);
    }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    p = aligned_alloc(16, ((size_t)len + 15u) & ~(size_t)15u);
    if (fread(p, 1, (size_t)len, f) != (size_t)len)
        exit(2);
    fclose(f);
    *n = (size_t)len;
    return p;
}

static size_t s_rotBytes[MAX_SOLIDS];

static void print_words(const void *p, int n)
{
    const uint32_t *w = p;
    int             i;

    for (i = 0; i < n; i++)
        printf(" %08x", (unsigned)w[i]);
}

// Where `p` is: in the frame buffer by its offset, the matrix REN passed,
// or neither.
static void print_where(const void *p)
{
    const uint8_t *b = p;

    if (b >= s_frame && b < s_frame + FRAME_BYTES)
        printf("f+%d", (int)(b - s_frame));
    else if (p == (const void *)&s_mtx)
        printf("in");
    else
        printf("?");
}

static int anim_of_model(const eModel *m)
{
    int i;

    for (i = 0; i < MAX_ANIMS; i++)
        if (m == &s_anim[i].Model)
            return i;
    return -1;
}

static int32_t record_visible(eModel *m, const bMatrix4 *matrix, int32_t a,
                              int32_t b)
{
    printf(" vis(%d,", anim_of_model(m));
    print_where(matrix);
    printf(",%d,%d)", (int)a, (int)b);
    print_words(matrix, 16);
    return s_vis;
}

static void record_strips(eModel *m, bMatrix4 *matrix, void *light,
                          uint32_t flags, bMatrix4 *bones)
{
    const eSolid *s = m->Solid;

    printf(" strips(%d,", anim_of_model(m));
    print_where(matrix);
    printf(",%x,%x,", (unsigned)(uintptr_t)light, (unsigned)flags);
    print_where(bones);
    printf(")");
    print_words(bones, 16 * (s != NULL ? s->AnimationTreeNumNodes : 0));
}

static void record_model(eModel *m, bMatrix4 *matrix, void *light,
                         uint32_t flags)
{
    printf(" emodel(%d,", m >= s_model && m < s_model + MAX_MODELS
                          ? (int)(m - s_model) : -1);
    print_where(matrix);
    printf(",%x,%x)", (unsigned)(uintptr_t)light, (unsigned)flags);
}

int main(int argc, char **argv)
{
    static char line[8192];
    char       *t[32];
    FILE       *f;
    int         i;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: animdriver_test script\n");
        return 2;
    }
    eAnimationSolidList.next = &eAnimationSolidList;
    eAnimationSolidList.prev = &eAnimationSolidList;
    for (i = 0; i < NUM_TYPES; i++)
        s_types[i].Type = i;

    while (fgets(line, sizeof line, f) != NULL) {
        int   n = 0;
        char *p = strtok(line, " \r\n");
        const char *c;

        while (p != NULL && n < 32) {
            t[n++] = p;
            p = strtok(NULL, " \r\n");
        }
        if (n == 0)
            continue;
        c = t[0];
#define I(k) ((int32_t)strtol(t[k], NULL, 0))
#define U(k) ((uint32_t)strtoul(t[k], NULL, 16))
        if (!strcmp(c, "TABLE")) {
            for (i = 0; i < DRIVER_ANIM_NUM; i++) {
                const DriverAnimationInfo *r = &AnimationInfoTable[i];

                printf("TABLE %d: %d %s %08x %d %d %d %d %d %d\n", i,
                       (int)r->Type, r->SolidName, (unsigned)r->SolidNameHash,
                       (int)r->BeginFrame, (int)r->NumFrames,
                       (int)r->PauseFrameNumber,
                       (int)r->AllowCollisionInterruption,
                       (int)r->BlendWithSteering, (int)r->CombineWithSteering);
            }
        } else if (!strcmp(c, "CT")) {
            s_types[I(1)].OpenTop = (int8_t)I(2);
        } else if (!strcmp(c, "CAR")) {
            Car *car = &s_car[I(1)];

            car->pCarTypeInfo = &s_types[I(2)];
            s_ride[I(1)].Type = I(3);
            car->pRideInfo = &s_ride[I(1)];
            car->pCarDriver = I(4) ? (void *)s_carDriver[I(1)] : NULL;
        } else if (!strcmp(c, "STEER")) {
            s_steer[I(1)] = (uint16_t)I(2);
        } else if (!strcmp(c, "CHAR")) {
            memset(s_char[I(1)].BodyTypeName, 0,
                   sizeof s_char[I(1)].BodyTypeName);
            strcpy(s_char[I(1)].BodyTypeName, t[2]);
        } else if (!strcmp(c, "DRV")) {
            AnimatedDriver *a = &s_drv[I(1)];

            memset(a, 0, sizeof *a);
            a->pCar = I(2) < 0 ? NULL : &s_car[I(2)];
            a->pCharacterInfo = I(3) < 0 ? NULL : &s_char[I(3)];
            animplayer_cancel(&a->AnimationPlayers[0]);
            animplayer_cancel(&a->AnimationPlayers[1]);
            a->SteeringWiggleNumber = I(4);
            a->ShiftAnimationNameHash = bchunk_hash("DRIVER_SHIFT01");
            animdriver_setup_steering_frame(a);
            printf("DRV %d:", I(1));
            print_driver(I(1));
        } else if (!strcmp(c, "LOOK")) {
            s_lookCar = I(1);
            s_lookAngle = (uint16_t)I(2);
            s_lookCop = I(3);
        } else if (!strcmp(c, "VM")) {
            s_viewMode = I(1);
        } else if (!strcmp(c, "W")) {
            WorldTime = I(1);
        } else if (!strcmp(c, "WE")) {
            uint32_t w = U(1);

            memcpy(&WorldTimeElapsed, &w, 4);
        } else if (!strcmp(c, "WL")) {
            WorldLoopCounter = I(1);
        } else if (!strcmp(c, "FIX")) {
            AnimatedDriverNeedsFixup = I(1);
        } else if (!strcmp(c, "SEED")) {
            bDefaultSeed = U(1);
        } else if (!strcmp(c, "TP")) {
            // TP t k v: row t's word k (2 the hash .. 8 Combine) set to v.
            DriverAnimationInfo *r = &AnimationInfoTable[I(1)];

            switch (I(2)) {
            case 2: r->SolidNameHash = U(3); break;
            case 3: r->BeginFrame = I(3); break;
            case 4: r->NumFrames = I(3); break;
            case 5: r->PauseFrameNumber = I(3); break;
            case 6: r->AllowCollisionInterruption = I(3); break;
            case 7: r->BlendWithSteering = I(3); break;
            case 8: r->CombineWithSteering = I(3); break;
            default: fprintf(stderr, "TP %d\n", I(2)); return 2;
            }
        } else if (!strcmp(c, "SOL")) {
            eAnimationSolid *s = &s_solid[I(1)];
            size_t           nb;

            memset(s, 0, sizeof *s);
            s->NameHash = U(2);
            s->NumNodes = (uint16_t)I(3);
            s->NumFrames = (uint16_t)I(4);
            s->pRotationKeys = read_file(t[5], &nb);
            s_rotBytes[I(1)] = nb;
            s->NumRotationKeys = (int32_t)(nb / 8);
            s->pTranslationKeys = read_file(t[6], &nb);
            s->NumTranslationKeys = (int32_t)(nb / 16);
        } else if (!strcmp(c, "LINK")) {
            bNode *nd = &s_solid[I(1)].Node;

            nd->next = &eAnimationSolidList;
            nd->prev = eAnimationSolidList.prev;
            eAnimationSolidList.prev->next = nd;
            eAnimationSolidList.prev = nd;
        } else if (!strcmp(c, "UNLINK")) {
            bNode *nd = &s_solid[I(1)].Node;

            nd->prev->next = nd->next;
            nd->next->prev = nd->prev;
        } else if (!strcmp(c, "ANIM")) {
            eAnimation *a = &s_anim[I(1)];

            memset(a, 0, sizeof *a);
            a->NameHash1 = U(2);
            a->pAnimationSolid1 = I(3) < 0 ? NULL : &s_solid[I(3)];
            a->NameHash2 = U(4);
            a->pAnimationSolid2 = I(5) < 0 ? NULL : &s_solid[I(5)];
        } else if (!strcmp(c, "INIT")) {
            InitAnimatedDriver();
            printf("INIT: fix=%d", (int)AnimatedDriverNeedsFixup);
            for (i = 0; i < DRIVER_ANIM_NUM; i++)
                printf(" %08x/%d", (unsigned)AnimationInfoTable[i].SolidNameHash,
                       (int)AnimationInfoTable[i].NumFrames);
            for (i = 0; i < MAX_SOLIDS; i++)
                if (s_solid[i].pRotationKeys != NULL)
                    printf(" crc%d=%08x", i,
                           (unsigned)crc32(s_solid[i].pRotationKeys,
                                           s_rotBytes[i]));
            printf("\n");
        } else if (!strcmp(c, "KEYS")) {
            // KEYS s node frame: the key as it is now.
            const int16_t *k = s_solid[I(1)].pRotationKeys
                             + (s_solid[I(1)].NumFrames * I(2) + I(3)) * 4;

            printf("KEYS %d %d %d: %04x %04x %04x %04x\n", I(1), I(2), I(3),
                   (unsigned)(uint16_t)k[0], (unsigned)(uint16_t)k[1],
                   (unsigned)(uint16_t)k[2], (unsigned)(uint16_t)k[3]);
        } else if (!strcmp(c, "PB")) {
            animplayer_begin(&s_drv[I(1)].AnimationPlayers[I(2)], I(3), I(4));
            printf("PB %d %d:", I(1), I(2));
            print_driver(I(1));
        } else if (!strcmp(c, "PP")) {
            animplayer_release_paused_frame(&s_drv[I(1)].AnimationPlayers[I(2)]);
            printf("PP %d %d:", I(1), I(2));
            print_driver(I(1));
        } else if (!strcmp(c, "PR")) {
            animplayer_release(&s_drv[I(1)].AnimationPlayers[I(2)]);
            printf("PR %d %d:", I(1), I(2));
            print_driver(I(1));
        } else if (!strcmp(c, "PF")) {
            printf("PF %d %d: %d\n", I(1), I(2),
                   (int)animplayer_get_frame_number(
                       &s_drv[I(1)].AnimationPlayers[I(2)]));
        } else if (!strcmp(c, "PC")) {
            animplayer_cancel(&s_drv[I(1)].AnimationPlayers[I(2)]);
            printf("PC %d %d:", I(1), I(2));
            print_driver(I(1));
        } else if (!strcmp(c, "Q")) {
            printf("Q %d %d: %d", I(1), I(2),
                   (int)animdriver_queue_animation(&s_drv[I(1)], I(2)));
            print_driver(I(1));
        } else if (!strcmp(c, "LEN")) {
            printf("LEN %d: %d\n", I(1),
                   (int)animdriver_get_length_of_queued(&s_drv[I(1)]));
        } else if (!strcmp(c, "FIND")) {
            AnimationPlayer *p = animdriver_find_animation(&s_drv[I(1)], I(2));

            printf("FIND %d %d: %d\n", I(1), I(2),
                   p == NULL ? -1 : (int)(p - s_drv[I(1)].AnimationPlayers));
        } else if (!strcmp(c, "REL")) {
            animdriver_release_animation(&s_drv[I(1)], I(2));
            printf("REL %d %d:", I(1), I(2));
            print_driver(I(1));
        } else if (!strcmp(c, "CA")) {
            animdriver_cancel_all(&s_drv[I(1)]);
            printf("CA %d:", I(1));
            print_driver(I(1));
        } else if (!strcmp(c, "RA")) {
            animdriver_release_all(&s_drv[I(1)]);
            printf("RA %d:", I(1));
            print_driver(I(1));
        } else if (!strcmp(c, "GC")) {
            animdriver_begin_gear_change(&s_drv[I(1)]);
            printf("GC %d:", I(1));
            print_driver(I(1));
        } else if (!strcmp(c, "DBB")) {
            animdriver_begin_driving_backwards(&s_drv[I(1)]);
            printf("DBB %d:", I(1));
            print_driver(I(1));
        } else if (!strcmp(c, "DBE")) {
            animdriver_end_driving_backwards(&s_drv[I(1)]);
            printf("DBE %d:", I(1));
            print_driver(I(1));
        } else if (!strcmp(c, "DBH")) {
            animdriver_handle_driving_backwards(&s_drv[I(1)]);
            printf("DBH %d:", I(1));
            print_driver(I(1));
        } else if (!strcmp(c, "LBB")) {
            animdriver_begin_looking_backwards(&s_drv[I(1)]);
            printf("LBB %d:", I(1));
            print_driver(I(1));
        } else if (!strcmp(c, "LBE")) {
            animdriver_end_looking_backwards(&s_drv[I(1)]);
            printf("LBE %d:", I(1));
            print_driver(I(1));
        } else if (!strcmp(c, "LBH")) {
            animdriver_handle_looking_backwards(&s_drv[I(1)]);
            printf("LBH %d:", I(1));
            print_driver(I(1));
        } else if (!strcmp(c, "COL")) {
            animdriver_begin_collision(&s_drv[I(1)], I(2), I(3));
            printf("COL %d %d %d:", I(1), I(2), I(3));
            print_driver(I(1));
        } else if (!strcmp(c, "SFN")) {
            printf("SFN %d: %d", I(1),
                   (int)animdriver_calculate_steering_frame_number(&s_drv[I(1)]));
            print_driver(I(1));
        } else if (!strcmp(c, "RQ")) {
            animdriver_queue_random_animations(&s_drv[I(1)], I(2), I(3), I(4));
            printf("RQ %d %d %d %d:", I(1), I(2), I(3), I(4));
            print_driver(I(1));
        } else if (!strcmp(c, "PRE")) {
            animdriver_begin_a_pre_race_animation(&s_drv[I(1)]);
            printf("PRE %d:", I(1));
            print_driver(I(1));
        } else if (!strcmp(c, "BB")) {
            printf("BB %d %d %d: %d\n", I(1), I(2), I(3),
                   (int)animdriver_blackballed(I(1), I(2),
                                               I(3) < 0 ? NULL : &s_char[I(3)]));
        } else if (!strcmp(c, "QT")) {
            bQuaternion q[42];
            bVector3    v;
            eAnimation *an = &s_anim[I(2)];

            memset(q, 0x5a, sizeof q);
            memset(&v, 0x5a, sizeof v);
            animdriver_build_quaternion_table(&s_drv[I(1)], an, q, &v);
            printf("QT %d %d: t=%08x,%08x,%08x", I(1), I(2),
                   (unsigned)fbits(v.x), (unsigned)fbits(v.y),
                   (unsigned)fbits(v.z));
            printf(" anim=%08x,%d,%08x,%d", (unsigned)an->NameHash1,
                   an->pAnimationSolid1 == NULL ? -1
                       : (int)(an->pAnimationSolid1 - s_solid),
                   (unsigned)an->NameHash2,
                   an->pAnimationSolid2 == NULL ? -1
                       : (int)(an->pAnimationSolid2 - s_solid));
            for (i = 0; i < 42; i++)
                printf(" %08x,%08x,%08x,%08x", (unsigned)fbits(q[i].x),
                       (unsigned)fbits(q[i].y), (unsigned)fbits(q[i].z),
                       (unsigned)fbits(q[i].w));
            print_driver(I(1));
        } else if (!strcmp(c, "NODE")) {
            // NODE a i parent first next o2b0..o2b15 tx ty tz
            eAnimationTreeNode *nd = &s_nodes[I(1)][I(2)];
            uint32_t            w[19];
            int                 k;

            for (k = 0; k < 19; k++)
                w[k] = U(6 + k);
            memset(nd, 0, sizeof *nd);
            memcpy(&nd->ObjectToBoneSpace, w, 64);
            memcpy(nd->Translation, w + 16, 12);
            nd->ThisNodeIndex = (int8_t)I(2);
            nd->ParentNodeIndex = (int8_t)I(3);
            nd->FirstChildNodeIndex = (int8_t)I(4);
            nd->NextChildNodeIndex = (int8_t)I(5);
        } else if (!strcmp(c, "MS")) {
            // MS a n: anim a's model on a solid of n nodes; -1 for none.
            eAnimation *a = &s_anim[I(1)];

            if (I(2) < 0) {
                a->Model.Solid = NULL;
            } else {
                s_esolid[I(1)].AnimationTreeNumNodes = I(2);
                s_esolid[I(1)].pAnimationTreeNodes = s_nodes[I(1)];
                a->Model.Solid = &s_esolid[I(1)];
            }
        } else if (!strcmp(c, "DA")) {
            s_drv[I(1)].pAnimations[I(2)] = I(3) < 0 ? NULL : &s_anim[I(3)];
        } else if (!strcmp(c, "DM")) {
            s_drv[I(1)].pModels[I(2)] = I(3) < 0 ? NULL : &s_model[I(3)];
        } else if (!strcmp(c, "FL")) {
            ForceAnimatedDriverLOD = I(1);
            OverrideAnimatedDriverLOD = I(2);
        } else if (!strcmp(c, "BS")) {
            uint32_t w[3] = { U(2), U(3), U(4) };

            nBoneScale = I(1);
            memcpy(vBoneScale, w, 12);
        } else if (!strcmp(c, "FB")) {
            CurrentBufferPos = s_frame + I(1);
            CurrentBufferEnd = s_frame + I(2);
            FrameMallocFailed = 0;
            FrameMallocFailAmount = 0;
        } else if (!strcmp(c, "VIS")) {
            s_vis = I(1);
        } else if (!strcmp(c, "X")) {
            uint32_t w[16];
            int      k;

            for (k = 0; k < 16; k++)
                w[k] = U(1 + k);
            memcpy(&s_mtx, w, 64);
        } else if (!strcmp(c, "REN")) {
            // REN d lod light flags
            gEModelDetermineVisibleStripsFn = record_visible;
            gEModelRenderStripsBonesFn = record_strips;
            gEModelRenderFn = record_model;
            printf("REN %d %d:", I(1), I(2));
            animdriver_render(&s_drv[I(1)], &s_mtx,
                              (struct eLightContext *)(uintptr_t)U(3), U(4),
                              I(2));
            printf(" pos=%d fail=%d amt=%u",
                   (int)(CurrentBufferPos - s_frame), (int)FrameMallocFailed,
                   (unsigned)FrameMallocFailAmount);
            print_driver(I(1));
        } else {
            fprintf(stderr, "unknown op %s\n", c);
            return 2;
        }
#undef I
#undef U
        fflush(stdout);
    }
    fclose(f);
    return 0;
}
