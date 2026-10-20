// Host harness for 3DS Files/source/zonecam.c, the freeze zone's camera, and
// the parts of spline.c and banim.c it brought. Runs the op script
// tools/zonecam_check.py writes and prints the transcript it diffs against
// the retail image, run in mipsemu over the same script.
//
// The harness owns what the mover reads and calls outside its own files:
// the cars, the players, the camera keys, the clocks, SoundEnabled, the
// saved mover whose IsExteriorView answers from the script, and printing
// stand-ins for bMalloc (a patterned arena), bFree, the TopologyCoordinate
// calls, the radial blur and Player::UpdateZoneSound. GetElevation and
// ConstrainToTopology answer from scripted lists, as the model's stubs do.
//
// Every camera, mover, car and block is filled with 0xa5 before the script
// sets it, so a field the port leaves alone and retail writes (or the other
// way round) shows. A float prints as its bits, every NaN as "nan", and a
// pointer by what it points at. The topology stand-ins print their vectors
// without the pad lanes, which retail leaves to the stack in Update.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "banim.h"
#include "bmath.h"
#include "bmem.h"
#include "camera.h"
#include "cammover.h"
#include "car.h"
#include "carinit.h"
#include "eview.h"
#include "player.h"
#include "playerzone.h"
#include "race.h"
#include "realdriver.h"
#include "realtime.h"
#include "spline.h"
#include "topology.h"
#include "zonecam.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

#define NCAM 2
#define NMOV 2
#define NCAR 2
#define NPL 2
#define NFOV 32
#define NEYE 8
#define ARENA_SIZE 0x40000
#define NBLOCK 512

// What zonecam.c links against, the harness's own.
float WorldTimeElapsed = 1.0f / 30.0f;
float RealTimeElapsed = 1.0f / 30.0f;
int32_t SoundEnabled = 1;
void (*gRadialBlurOffFn)(int32_t view);
void (*gRadialBlurAlphaFn)(int32_t view, float from, float to);

static Camera cams[NCAM];
static ZoneFreezeCameraMover movs[NMOV];
static struct Car cars[NCAR];
static struct Player players[NPL];
static CameraMover saved;
static CameraMoverVtbl saved_vt;
static int saved_ext;
static Spline spl;
static bVector3 fovt[NFOV], eyev[NEYE];
static int32_t coordinator[4];

static unsigned char arena[ARENA_SIZE] __attribute__((aligned(16)));
static size_t arena_used;
static void *blocks[NBLOCK];
static int nblocks;

static uint32_t elevs[64];
static int nelev, ielev;
static struct { int r; uint32_t d[3]; } cons[64];
static int ncons, icons;

static int block_index(const void *p)
{
    int i;

    for (i = nblocks - 1; i >= 0; i--)
        if (blocks[i] == p)
            return i;
    return -1;
}

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    int i;

    if ((i = block_index(p)) >= 0) {
        sprintf(b, "m%d", i);
        return b;
    }
    if (p == 0)
        return "null";
    if (p == &CameraMoverBaseVtbl)
        return "base";
    if (p == &ZoneFreezeCameraMoverVtbl)
        return "zone";
    if (p == fovt)
        return "fovt";
    if (p == eyev)
        return "eyev";
    if (p == &spl)
        return "spl";
    if (p == &saved)
        return "saved";
    for (i = 0; i < NCAM; i++) {
        if (p == &cams[i]) {
            sprintf(b, "c%d", i);
            return b;
        }
        if (p == &cams[i].CurrentKey.Target) {
            sprintf(b, "c%d.tgt", i);
            return b;
        }
    }
    for (i = 0; i < NMOV; i++) {
        if (p == &movs[i]) {
            sprintf(b, "o%d", i);
            return b;
        }
        if (p == &movs[i].Topology) {
            sprintf(b, "o%d.tc", i);
            return b;
        }
    }
    for (i = 0; i < NCAR; i++) {
        if (p == &cars[i]) {
            sprintf(b, "k%d", i);
            return b;
        }
    }
    for (i = 0; i < NPL; i++) {
        if (p == &players[i]) {
            sprintf(b, "p%d", i);
            return b;
        }
    }
    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        if (p == &eViews[i]) {
            sprintf(b, "v%d", i);
            return b;
        }
        if (p == &eViews[i].CameraMoverList) {
            sprintf(b, "v%d.list", i);
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
    static char buf[32][12];
    static int slot;
    char *b = buf[slot++ & 31];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

static const char *v3(const bVector3 *v)
{
    static char buf[8][40];
    static int slot;
    char *b = buf[slot++ & 7];

    sprintf(b, "%s %s %s", fx(v->x), fx(v->y), fx(v->z));
    return b;
}

static void pvec(const char *tag, const bVector3 *v)
{
    printf(" %s %s %s %s %s", tag, fx(v->x), fx(v->y), fx(v->z), fx(v->pad));
}

// ------------------------------------------------------------ the stubs

void *bMalloc(int size, const char *name, int flags, int pool)
{
    size_t off = (arena_used + 15) & ~(size_t)15;
    void *p = arena + off;

    arena_used = off + (size_t)size;
    if (arena_used > ARENA_SIZE || nblocks == NBLOCK) {
        fprintf(stderr, "arena full\n");
        exit(2);
    }
    blocks[nblocks] = p;
    printf("  malloc %d %s %d %d -> m%d\n", size, name, flags, pool, nblocks);
    nblocks++;
    return p;
}

void bFree(void *p)
{
    printf("  free %s\n", nm(p));
}

void topology_init(TopologyCoordinate *tc)
{
    printf("  topo init %s\n", nm(tc));
}

void topology_destroy(TopologyCoordinate *tc)
{
    printf("  topo destroy %s\n", nm(tc));
}

void topology_set_interest_bbox3(TopologyCoordinate *tc, const bVector3 *pos,
                                 float r, const bVector3 *vel)
{
    printf("  bbox %s pos %s r %s vel %s\n", nm(tc), v3(pos), fx(r),
           vel != NULL ? v3(vel) : "null");
}

float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    float v = from_bits(elevs[ielev++ % nelev]);

    printf("  elev %s pt %s args %d%d%d -> %s\n", nm(tc), v3(pt),
           terrain != NULL, normal != NULL, found != NULL, fx(v));
    return v;
}

int topology_constrain(TopologyCoordinate *tc, int type, int twoSided,
                       const bVector3 *from, bVector3 *to, float dist,
                       float lift)
{
    int k = icons++ % ncons;

    printf("  constrain %s type %d two %d from %s to %s dist %s lift %s"
           " -> %d\n", nm(tc), type, twoSided, v3(from), v3(to), fx(dist),
           fx(lift), cons[k].r);
    to->x = to->x + from_bits(cons[k].d[0]);
    to->y = to->y + from_bits(cons[k].d[1]);
    to->z = to->z + from_bits(cons[k].d[2]);
    return cons[k].r;
}

static void blur_off(int32_t view)
{
    printf("  blur off %d\n", (int)view);
}

static void blur_alpha(int32_t view, float from, float to)
{
    printf("  blur alpha %d %s %s\n", (int)view, fx(from), fx(to));
}

void player_update_zone_sound(struct Player *p, float muffle, float volume,
                              uint16_t azimuth, float pitch)
{
    printf("  zsound %s %s %s %04x %s\n", nm(p), fx(muffle), fx(volume),
           (unsigned)azimuth, fx(pitch));
}

static int ext_answer(CameraMover *m)
{
    (void)m;
    return saved_ext;
}

// ------------------------------------------------------------ the dumps

static void pkey(const char *tag, const CameraParams *k)
{
    const bMatrix4 *m = &k->Matrix;

    printf("    %s m %s %s %s %s %s %s %s %s", tag,
           fx(m->v0.x), fx(m->v0.y), fx(m->v0.z), fx(m->v0.w),
           fx(m->v1.x), fx(m->v1.y), fx(m->v1.z), fx(m->v1.w));
    printf(" %s %s %s %s %s %s %s %s\n",
           fx(m->v2.x), fx(m->v2.y), fx(m->v2.z), fx(m->v2.w),
           fx(m->v3.x), fx(m->v3.y), fx(m->v3.z), fx(m->v3.w));
    printf("    %s", tag);
    pvec("p", &k->Position);
    pvec("d", &k->Direction);
    pvec("t", &k->Target);
    printf("\n");
    printf("    %s s %s %s %s %s %s fov %04x\n", tag,
           fx(k->TargetDistance), fx(k->FocalDistance), fx(k->DepthOfField),
           fx(k->NearZ), fx(k->FarZ), (unsigned)k->FieldOfView);
}

static void pcam(const Camera *c)
{
    printf("  %s\n", nm(c));
    pkey("cur", &c->CurrentKey);
    pkey("prev", &c->PreviousKey);
    pkey("vel", &c->VelocityKey);
    printf("    clear %08lx elapsed %s last %08lx carnot %08lx dash %08lx\n",
           (unsigned long)(uint32_t)c->ClearVelocity, fx(c->ElapsedTime),
           (unsigned long)c->LastUpdateTime,
           (unsigned long)(uint32_t)(uintptr_t)c->CarNotToRender,
           (unsigned long)(uint32_t)c->RenderDash);
}

static void pspline(const char *tag, const Spline *s)
{
    int i;

    printf("    %s %08lx %08lx %08lx %s %s %08lx %08lx %08lx %s %s %08lx %s\n",
           tag, (unsigned long)(uint32_t)s->ControlPointBufferSize,
           (unsigned long)(uint32_t)s->NumControlPoints,
           (unsigned long)(uint32_t)s->Type, nm(s->pControlPoints),
           nm(s->pControlPointArray), (unsigned long)(uint32_t)s->Dirty,
           (unsigned long)(uint32_t)s->TableSize,
           (unsigned long)(uint32_t)s->CalLevel, fx(s->Length),
           fx(s->CalTableStep), (unsigned long)(uint32_t)s->CalTableSize,
           nm(s->pCalTable));
    if ((block_index(s->pControlPoints) >= 0 || s->pControlPoints == eyev)
        && s->NumControlPoints > 0 && s->NumControlPoints <= 256) {
        for (i = 0; i < s->NumControlPoints; i++) {
            printf("    %s %d", tag, i);
            printf(" %s %s %s %s\n", fx(s->pControlPoints[i].x),
                   fx(s->pControlPoints[i].y), fx(s->pControlPoints[i].z),
                   fx(s->pControlPoints[i].pad));
        }
    }
}

static void pcubic(const char *tag, const BSpline *c)
{
    printf("    %s %s %s %s %s %s %s %s %s %s %s %s st %04x fl %04x\n", tag,
           fx(c->val), fx(c->dval), fx(c->valDesired), fx(c->dvalDesired),
           fx(c->coeff[0]), fx(c->coeff[1]), fx(c->coeff[2]),
           fx(c->coeff[3]), fx(c->time), fx(c->duration),
           fx(c->arrivalThreshold), (unsigned)(uint16_t)c->state,
           (unsigned)(uint16_t)c->flags);
}

static void pblend(const char *tag, const BSpline3D *b)
{
    char t[8];

    if (block_index(b) < 0)
        return;
    sprintf(t, "%sx", tag);
    pcubic(t, &b->x);
    sprintf(t, "%sy", tag);
    pcubic(t, &b->y);
    sprintf(t, "%sz", tag);
    pcubic(t, &b->z);
}

static void pmov(int j, int full)
{
    const ZoneFreezeCameraMover *o = &movs[j];
    const CameraMover *m = &o->base;

    printf("  o%d type %d view %d en %d pview %s pcam %s player %s"
           " carnot %08lx dash %08lx vtbl %s next %s prev %s\n",
           j, (int)m->Type, m->ViewID, m->Enabled, nm(m->pView),
           nm(m->pCamera), nm(m->pPlayer),
           (unsigned long)(uint32_t)(uintptr_t)m->CarNotToRender,
           (unsigned long)(uint32_t)m->RenderDash, nm(m->vtbl),
           nm(m->Node.next), nm(m->Node.prev));
    printf("    ft %s tan %s ei %s eo %s li %s lo %s fp %s\n", fx(o->fTime),
           fx(o->fTanFov), nm(o->pEyeBlendIn), nm(o->pEyeBlendOut),
           nm(o->pLookBlendIn), nm(o->pLookBlendOut), nm(o->pFocusPull));
    pblend("ei", o->pEyeBlendIn);
    pblend("eo", o->pEyeBlendOut);
    pblend("li", o->pLookBlendIn);
    pblend("lo", o->pLookBlendOut);
    if (block_index(o->pFocusPull) >= 0)
        pcubic("fp", o->pFocusPull);
    if (full) {
        pspline("eye", &o->EyeSpline);
        pspline("look", &o->LookSpline);
    }
}

static void pviews(void)
{
    int i, any = 0;

    printf("  views");
    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        const bNode *head = &eViews[i].CameraMoverList, *n = head->next;
        int k = 0;

        if (n == head)
            continue;
        printf(" v%d:", i);
        any = 1;
        for (; n != head && k < 20; n = n->next, k++)
            printf("%s%s", k ? "," : "", nm(n));
    }
    printf("%s\n", any ? "" : " -");
}

static void reset(void)
{
    int i;

    memset(cams, 0xa5, sizeof cams);
    memset(movs, 0xa5, sizeof movs);
    memset(cars, 0xa5, sizeof cars);
    memset(players, 0xa5, sizeof players);
    memset(&saved, 0xa5, sizeof saved);
    saved_vt = CameraMoverBaseVtbl;
    saved_vt.IsExteriorView = ext_answer;
    saved.vtbl = &saved_vt;
    saved_ext = 1;
    memset(&spl, 0xa5, sizeof spl);
    memset(fovt, 0xa5, sizeof fovt);
    memset(eyev, 0xa5, sizeof eyev);
    memset(arena, 0xa5, sizeof arena);
    arena_used = 0;
    nblocks = 0;
    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        eViews[i].pCamera = 0;
        eViews[i].CameraMoverList.next = &eViews[i].CameraMoverList;
        eViews[i].CameraMoverList.prev = &eViews[i].CameraMoverList;
    }
    CameraStopUpdating = 0;
    WorldTimeElapsed = 1.0f / 30.0f;
    RealTimeElapsed = 1.0f / 30.0f;
    pRaceCoordinator = NULL;
    SoundEnabled = 1;
    elevs[0] = 0;
    nelev = 1;
    ielev = 0;
    memset(cons, 0, sizeof cons);
    ncons = 1;
    icons = 0;
}

static char *tok(void)
{
    char *t = strtok(NULL, " \t\r\n");

    if (t == NULL) {
        fprintf(stderr, "short line\n");
        exit(2);
    }
    return t;
}

static int itok(void) { return atoi(tok()); }
static uint32_t xtok(void) { return (uint32_t)strtoul(tok(), NULL, 16); }
static float ftok(void) { return from_bits(xtok()); }

static void read_vec(bVector3 *v)
{
    v->x = ftok();
    v->y = ftok();
    v->z = ftok();
    v->pad = ftok();
}

static void read_mat(bMatrix4 *m)
{
    bVector4 *r[4];
    int i;

    r[0] = &m->v0; r[1] = &m->v1; r[2] = &m->v2; r[3] = &m->v3;
    for (i = 0; i < 4; i++) {
        r[i]->x = ftok();
        r[i]->y = ftok();
        r[i]->z = ftok();
        r[i]->w = ftok();
    }
}

static struct Car *car_at(int i)
{
    return i < 0 ? NULL : &cars[i];
}

static bVector3 *arr_of(const char *s)
{
    if (!strcmp(s, "f"))
        return fovt;
    if (!strcmp(s, "e"))
        return eyev;
    fprintf(stderr, "bad array %s\n", s);
    exit(2);
}

static void query(int j)
{
    CameraMover *m = &movs[j].base;
    const CameraMoverVtbl *vt = m->vtbl;
    const CameraInfo *info = vt->GetCameraInfo(m);
    const POV *pov0 = vt->GetPOV(m, 0);
    int ext = vt->IsExteriorView(m);
    int lb = vt->IsLookingBack(m);
    float gap = vt->GetWallGap(m);
    void *car = vt->GetCarToFollow(m);

    printf("  q o%d info %s pov %s ext %d lb %d gap %s car %s tgt %s\n",
           j, nm(info), nm(pov0), ext, lb, fx(gap), nm(car),
           nm(vt->GetTarget(m)));
}

static void spline_op(int alloc)
{
    int type = itok(), cnt = itok(), k = itok(), i;
    char *t;

    memset(&spl, 0xa5, sizeof spl);
    if (alloc)
        spline_init_alloc(&spl, (SplineType)type, cnt, 16384);
    else
        spline_init(&spl, (SplineType)type, cnt, eyev, 16384);
    for (i = 0; i < k; i++)
        spline_add_control_point(&spl, &fovt[i % NFOV]);
    pspline("spl", &spl);
    while ((t = strtok(NULL, " \t\r\n")) != NULL) {
        float tt = from_bits((uint32_t)strtoul(t, NULL, 16));
        bVector3 o;

        memset(&o, 0xa5, sizeof o);
        spline_get_point(&spl, &o, tt);
        printf("  at %s", fx(tt));
        pvec("p", &o);
        memset(&o, 0xa5, sizeof o);
        spline_get_derivative(&spl, &o, tt);
        pvec("d", &o);
        printf("\n");
    }
    spline_destroy(&spl, 2);
    printf("  destroyed\n");
}

int main(int argc, char **argv)
{
    static char line[8192];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: zonecam_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    gRadialBlurOffFn = blur_off;
    gRadialBlurAlphaFn = blur_alpha;

    while (fgets(line, sizeof line, fp) != NULL) {
        char echo[64];
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        snprintf(echo, sizeof echo, "%.40s", line);
        t = strtok(line, " \t");
        if (t == NULL)
            continue;
        if (!strcmp(t, "B")) {
            printf("B %d\n", itok());
            reset();
            continue;
        }
        if (strchr("AEJKX", t[0]) == NULL || t[1])
            printf("> %s\n", echo);

        if (!strcmp(t, "C")) {
            int k = itok();

            memset(&cams[k], 0xa5, sizeof cams[k]);
            camera_init(&cams[k]);
            pcam(&cams[k]);
        } else if (!strcmp(t, "V")) {
            int i = itok();

            eViews[i].pCamera = &cams[itok()];
        } else if (!strcmp(t, "J")) {
            Camera *c = &cams[itok()];

            read_vec(&c->CurrentKey.Position);
            read_vec(&c->CurrentKey.Target);
            read_vec(&c->VelocityKey.Position);
            read_vec(&c->VelocityKey.Target);
            c->CurrentKey.FieldOfView = (uint16_t)xtok();
        } else if (!strcmp(t, "M")) {
            // Raw words, never followed: the constructor only clears them.
            Camera *c = &cams[itok()];

            c->CarNotToRender = (void *)(uintptr_t)xtok();
            c->RenderDash = itok();
        } else if (!strcmp(t, "P")) {
            pcam(&cams[itok()]);
        } else if (!strcmp(t, "K")) {
            struct Car *k = &cars[itok()];

            read_vec(&k->State.Position);
            read_vec(&k->State.Velocity);
            read_mat(&k->State.BodyMatrix);
            k->State.VelocityMagnitude = ftok();
        } else if (!strcmp(t, "L")) {
            int i = itok();

            players[i].PlayerNumber = itok();
        } else if (!strcmp(t, "S")) {
            saved_ext = itok();
        } else if (!strcmp(t, "Z")) {
            CameraStopUpdating = itok();
        } else if (!strcmp(t, "T")) {
            WorldTimeElapsed = ftok();
            RealTimeElapsed = ftok();
        } else if (!strcmp(t, "Q")) {
            int s = itok();

            if (s < 0) {
                pRaceCoordinator = NULL;
            } else {
                coordinator[0] = s;
                pRaceCoordinator = (RaceCoordinator *)(void *)coordinator;
            }
        } else if (!strcmp(t, "Y")) {
            SoundEnabled = itok();
        } else if (!strcmp(t, "E")) {
            int i;

            nelev = itok();
            for (i = 0; i < nelev; i++)
                elevs[i] = xtok();
            ielev = 0;
        } else if (!strcmp(t, "X")) {
            int i;

            ncons = itok();
            for (i = 0; i < ncons; i++) {
                cons[i].r = itok();
                cons[i].d[0] = xtok();
                cons[i].d[1] = xtok();
                cons[i].d[2] = xtok();
            }
            icons = 0;
        } else if (!strcmp(t, "O")) {
            int j = itok(), view = itok(), car = itok();

            memset(&movs[j], 0xa5, sizeof movs[j]);
            zone_freeze_camera_mover_init(&movs[j], view, car_at(car),
                                          &saved);
            pmov(j, 1);
            pviews();
            pcam(movs[j].base.pCamera);
        } else if (!strcmp(t, "R")) {
            int j = itok();

            movs[j].base.pPlayer = &players[itok()];
        } else if (!strcmp(t, "U")) {
            int j = itok();

            movs[j].base.vtbl->Update(&movs[j].base);
            pmov(j, 0);
            pcam(movs[j].base.pCamera);
        } else if (!strcmp(t, "D")) {
            int j = itok();
            Camera *c = movs[j].base.pCamera;

            movs[j].base.vtbl->Destroy(&movs[j].base);
            pmov(j, 0);
            pviews();
            pcam(c);
        } else if (!strcmp(t, "F")) {
            ZoneFreezeCameraMover *o = &movs[itok()];
            const char *f = tok();

            if (!strcmp(f, "ft"))
                o->fTime = ftok();
            else
                o->pFocusPull->val = ftok();
        } else if (!strcmp(t, "G")) {
            query(itok());
        } else if (!strcmp(t, "A")) {
            bVector3 *a = arr_of(tok());

            read_vec(&a[itok()]);
        } else if (!strcmp(t, "a")) {
            spline_op(1);
        } else if (!strcmp(t, "n")) {
            spline_op(0);
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
