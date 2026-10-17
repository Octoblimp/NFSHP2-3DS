// Host harness for 3DS Files/source/bumpercam.c, the pre-race's mover. Runs
// the op script tools/bumpercam_check.py writes and prints the transcript
// it diffs against the retail image, run in mipsemu over the same script.
//
// The harness owns what the mover reads from outside: the cars, the two
// clocks, the race coordinator's state, the race's stage, the record it is
// built from and the record's four arrays. It also stands in for the
// mover's callees outside the camera and the maths, each printing what it
// was given: TopologyCoordinate's constructor and destructor,
// SetInterestBBox, GetElevation, GetRoadNoise, GetCarSpaceBoundingBox and
// the two wall helpers drivecam.c ports (camera_wall_offset and
// camera_look_at_offset, checked by drivecam_check). bFree prints the
// block it is given.
//
// Every camera, mover, record and array is filled with 0xa5 before the
// script sets it, so a field the port leaves alone and retail writes (or
// the other way round) shows. A float prints as its bits, every NaN as
// "nan", and a pointer by what it points at.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bumpercam.h"
#include "camera.h"
#include "cammover.h"
#include "car.h"
#include "drivecam.h"
#include "eview.h"
#include "race.h"
#include "realtime.h"
#include "spline.h"
#include "topology.h"
#include "track.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

#define NCAM 4
#define NMOV 3
#define NCAR 3
#define NARR 32

// What bumpercam.c links against, the harness's own.
float WorldTimeElapsed = 1.0f / 30.0f;
float RealTimeElapsed = 1.0f / 30.0f;

static Camera cams[NCAM];
static BumperCameraMover movs[NMOV];
static struct Car cars[NCAR];
static CameraDataItems cdt;
static bVector3 fovt[NARR], eyev[NARR], bankv[NARR], lookv[NARR];
static int32_t coordinator[4];
static Race race;

// The stand-ins' answers, from the script.
static float noise[3];
static int noise_at;
static float elev;
static bVector3 wall;
static bVector3 box_min[NCAR], box_max[NCAR];

void bFree(void *p);

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    int i;

    if (p == 0)
        return "null";
    if (p == &CameraMoverBaseVtbl)
        return "base";
    if (p == &BumperCameraMoverVtbl)
        return "bumper";
    if (p == fovt)
        return "fovt";
    if (p == eyev)
        return "eyev";
    if (p == bankv)
        return "bankv";
    if (p == lookv)
        return "lookv";
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
        if (p == &movs[i].TheTopologyCoordinate) {
            sprintf(b, "o%d.tc", i);
            return b;
        }
    }
    for (i = 0; i < NCAR; i++) {
        if (p == &cars[i]) {
            sprintf(b, "k%d", i);
            return b;
        }
        if (p == &cars[i].State.GeometryPosition) {
            sprintf(b, "k%d.gpos", i);
            return b;
        }
        if (p == &cars[i].State.Position) {
            sprintf(b, "k%d.pos", i);
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

// A TopologyCoordinate: a mover's, or the wall routine's own on the stack.
static const char *tcn(const void *p)
{
    int i;

    for (i = 0; i < NMOV; i++)
        if (p == &movs[i].TheTopologyCoordinate)
            return nm(p);
    return "local";
}

void bFree(void *p)
{
    printf("  free %s\n", nm(p));
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
    static char buf[64][12];
    static int slot;
    char *b = buf[slot++ & 63];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

static const char *v4(const bVector3 *v)
{
    static char buf[8][48];
    static int slot;
    char *b = buf[slot++ & 7];

    sprintf(b, "%s %s %s %s", fx(v->x), fx(v->y), fx(v->z), fx(v->pad));
    return b;
}

static void pvec(const char *tag, const bVector3 *v)
{
    printf(" %s %s", tag, v4(v));
}

static void pmat(const bMatrix4 *m)
{
    printf(" %s %s %s %s %s %s %s %s",
           fx(m->v0.x), fx(m->v0.y), fx(m->v0.z), fx(m->v0.w),
           fx(m->v1.x), fx(m->v1.y), fx(m->v1.z), fx(m->v1.w));
    printf(" %s %s %s %s %s %s %s %s",
           fx(m->v2.x), fx(m->v2.y), fx(m->v2.z), fx(m->v2.w),
           fx(m->v3.x), fx(m->v3.y), fx(m->v3.z), fx(m->v3.w));
}

static void pkey(const char *tag, const CameraParams *k)
{
    printf("    %s m", tag);
    pmat(&k->Matrix);
    printf("\n");
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
    printf("    clear %08lx elapsed %s last %08lx carnot %s dash %08lx\n",
           (unsigned long)(uint32_t)c->ClearVelocity, fx(c->ElapsedTime),
           (unsigned long)c->LastUpdateTime, nm(c->CarNotToRender),
           (unsigned long)(uint32_t)c->RenderDash);
}

// ------------------------------------------------------------ the stubs

void topology_init(TopologyCoordinate *tc)
{
    printf("  topo init %s\n", tcn(tc));
}

void topology_destroy(TopologyCoordinate *tc)
{
    printf("  topo destroy %s\n", tcn(tc));
}

void topology_set_interest_bbox3(TopologyCoordinate *tc, const bVector3 *pos,
                                 float r, const bVector3 *vel)
{
    printf("  bbox %s pos %s r %s vel %s\n", tcn(tc), v4(pos), fx(r),
           nm(vel));
}

float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    printf("  elev %s pt %s args %d%d%d -> %s\n", tcn(tc), v4(pt),
           terrain != NULL, normal != NULL, found != NULL, fx(elev));
    return elev;
}

float track_get_road_noise(const bVector2 *p, int32_t terrain)
{
    float n = noise[noise_at];

    noise_at = (noise_at + 1) % 3;
    printf("  noise %s %s %d -> %s\n", fx(p->x), fx(p->y), (int)terrain,
           fx(n));
    return n;
}

void car_get_car_space_bounding_box(Car *c, bVector3 *min, bVector3 *max)
{
    int i = (int)(c - cars);

    printf("  box %s\n", nm(c));
    *min = box_min[i];
    *max = box_max[i];
}

void camera_wall_offset(CameraMover *m, TopologyCoordinate *tc,
                        const bVector3 *from, const bVector3 *eye,
                        bVector3 *out)
{
    printf("  wall %s %s from %s eye %s -> %s\n", nm(m), tcn(tc), nm(from),
           v4(eye), v4(&wall));
    *out = wall;
}

// The image's 0x00157b60 takes the mover first; the stand-in prints the
// matrix it is to overwrite, then puts the eye in its fourth row.
void camera_look_at_offset(bMatrix4 *out, const bVector3 *eye,
                           const bVector3 *target, const bVector2 *off)
{
    printf("  lookoff eye %s tgt %s off %s %s\n   ", v4(eye), nm(target),
           fx(off->x), fx(off->y));
    pmat(out);
    printf("\n");
    out->v3.x = eye->x;
    out->v3.y = eye->y;
    out->v3.z = eye->z;
    out->v3.w = 1.0f;
}

// ------------------------------------------------------------ the record

// CameraDataItems by name: `i` a word, `f` a float, `p` a pointer.
#define CDF(f, k) { #f, offsetof(CameraDataItems, f), k }
static const struct { const char *name; size_t off; char kind; } CD_FIELDS[] = {
    CDF(Type, 'i'), CDF(Name, 'p'), CDF(IsFOVIso, 'i'),
    CDF(MinPercent, 'f'), CDF(MaxPercent, 'f'), CDF(EyeSplineSpeed, 'f'),
    CDF(LookSplineSpeed, 'f'), CDF(FOVSplineSpeed, 'f'),
    CDF(LockEyeSpeedToCar, 'i'), CDF(LockLookSpeedToCar, 'i'),
    CDF(MinAreaPercent, 'f'), CDF(MaxAreaPercent, 'f'), CDF(NearClip, 'f'),
    CDF(FarClip, 'f'), CDF(Backwards, 'i'), CDF(FOVTable, 'p'),
    CDF(NumAreaVerts, 'i'), CDF(AreaVerts, 'p'), CDF(NumAreaFaces, 'i'),
    CDF(AreaFaces, 'p'), CDF(NumEyeVerts, 'i'), CDF(EyeVerts, 'p'),
    CDF(BankVerts, 'p'), CDF(NumLookVerts, 'i'), CDF(LookVerts, 'p'),
    CDF(SpringXVel, 'f'), CDF(SpringYVel, 'f'), CDF(SpringZVel, 'f'),
    CDF(SpringDamp, 'f'), CDF(SpringConst, 'f'), CDF(LookOffsetX, 'f'),
    CDF(LookOffsetY, 'f'), CDF(LookOffsetZ, 'f'), CDF(EnterVertComp, 'f'),
    CDF(EnterHorizComp, 'f'), CDF(LeaveVertComp, 'f'),
    CDF(LeaveHorizComp, 'f'), CDF(IsLeaveSet, 'i'), CDF(WipeDistance, 'f'),
    CDF(WipeAutoDisable, 'i'), CDF(ShakeBankNumber, 'i'),
};
#define NCDF (sizeof CD_FIELDS / sizeof CD_FIELDS[0])

static void pcd(const CameraDataItems *cd)
{
    const char *base = (const char *)cd;
    size_t i;

    printf("    cd");
    for (i = 0; i < NCDF; i++) {
        const void *a = base + CD_FIELDS[i].off;

        if (CD_FIELDS[i].kind == 'p') {
            printf(" %s", nm(*(void *const *)a));
        } else {
            uint32_t u;

            memcpy(&u, a, 4);
            if (CD_FIELDS[i].kind == 'f')
                printf(" %s", fx(from_bits(u)));
            else
                printf(" %08lx", (unsigned long)u);
        }
    }
    printf("\n");
}

// A pointer field's symbol: "-" NULL, an array's name, else raw hex.
static void *sym(const char *s)
{
    if (!strcmp(s, "-"))
        return NULL;
    if (!strcmp(s, "fovt"))
        return fovt;
    if (!strcmp(s, "eyev"))
        return eyev;
    if (!strcmp(s, "bankv"))
        return bankv;
    if (!strcmp(s, "lookv"))
        return lookv;
    return (void *)(uintptr_t)strtoul(s, NULL, 16);
}

static void set_cd(const char *f, const char *v)
{
    char *base = (char *)&cdt;
    size_t i;

    for (i = 0; i < NCDF; i++) {
        if (strcmp(CD_FIELDS[i].name, f))
            continue;
        if (CD_FIELDS[i].kind == 'p') {
            void *p = sym(v);

            memcpy(base + CD_FIELDS[i].off, &p, sizeof p);
        } else {
            uint32_t u = (uint32_t)strtoul(v, NULL, 16);

            memcpy(base + CD_FIELDS[i].off, &u, 4);
        }
        return;
    }
    fprintf(stderr, "bad cd field %s\n", f);
    exit(2);
}

static void pspline(const char *tag, const Spline *s)
{
    printf("    %s %08lx %08lx %08lx %s %s %08lx %08lx %08lx %s %s %08lx %s\n",
           tag, (unsigned long)(uint32_t)s->ControlPointBufferSize,
           (unsigned long)(uint32_t)s->NumControlPoints,
           (unsigned long)(uint32_t)s->Type, nm(s->pControlPoints),
           nm(s->pControlPointArray), (unsigned long)(uint32_t)s->Dirty,
           (unsigned long)(uint32_t)s->TableSize,
           (unsigned long)(uint32_t)s->CalLevel, fx(s->Length),
           fx(s->CalTableStep), (unsigned long)(uint32_t)s->CalTableSize,
           nm(s->pCalTable));
}

static void pmov(int j)
{
    const BumperCameraMover *o = &movs[j];
    const CameraMover *m = &o->base;

    printf("  o%d type %d view %d en %d pview %s pcam %s player %08lx"
           " carnot %s dash %08lx vtbl %s next %s prev %s\n",
           j, (int)m->Type, m->ViewID, m->Enabled, nm(m->pView),
           nm(m->pCamera), (unsigned long)(uint32_t)(uintptr_t)m->pPlayer,
           nm(m->CarNotToRender),
           (unsigned long)(uint32_t)m->RenderDash, nm(m->vtbl),
           nm(m->Node.next), nm(m->Node.prev));
    pcd(&o->CD);
    pspline("eye", &o->EyeSpline);
    pspline("bank", &o->BankSpline);
    pspline("look", &o->LookSpline);
    pspline("fov", &o->FOVSpline);
    printf("    ep %s lp %s car %s\n", fx(o->EyeSplineParam),
           fx(o->LookSplineParam), nm(o->CarToFollow));
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
    memset(&cdt, 0xa5, sizeof cdt);
    memset(fovt, 0xa5, sizeof fovt);
    memset(eyev, 0xa5, sizeof eyev);
    memset(bankv, 0xa5, sizeof bankv);
    memset(lookv, 0xa5, sizeof lookv);
    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        eViews[i].pCamera = 0;
        eViews[i].CameraMoverList.next = &eViews[i].CameraMoverList;
        eViews[i].CameraMoverList.prev = &eViews[i].CameraMoverList;
    }
    CameraStopUpdating = 0;
    WorldTimeElapsed = 1.0f / 30.0f;
    RealTimeElapsed = 1.0f / 30.0f;
    TheRaceParameters.TrackDirection = 0;
    pRaceCoordinator = NULL;
    memset(&race, 0, sizeof race);
    race.RaceStage = RACE_STAGE_PRERACE;
    pCurrentRace = &race;
    memset(noise, 0, sizeof noise);
    noise_at = 0;
    elev = 0.0f;
    memset(&wall, 0, sizeof wall);
    memset(box_min, 0, sizeof box_min);
    memset(box_max, 0, sizeof box_max);
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
    if (!strcmp(s, "b"))
        return bankv;
    if (!strcmp(s, "l"))
        return lookv;
    fprintf(stderr, "bad array %s\n", s);
    exit(2);
}

static void set_mov(int j, const char *f)
{
    BumperCameraMover *o = &movs[j];

    if (!strcmp(f, "ep"))
        o->EyeSplineParam = ftok();
    else if (!strcmp(f, "lp"))
        o->LookSplineParam = ftok();
    else if (!strcmp(f, "car"))
        o->CarToFollow = car_at(itok());
    else if (!strcmp(f, "es"))
        o->CD.EyeSplineSpeed = ftok();
    else if (!strcmp(f, "ls"))
        o->CD.LookSplineSpeed = ftok();
    else if (!strcmp(f, "ne"))
        o->CD.NumEyeVerts = (int32_t)xtok();
    else if (!strcmp(f, "nl"))
        o->CD.NumLookVerts = (int32_t)xtok();
    else {
        fprintf(stderr, "bad mover field %s\n", f);
        exit(2);
    }
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

int main(int argc, char **argv)
{
    static char line[8192];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: bumpercam_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }

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
        if (strchr("AFKM", t[0]) == NULL || t[1])
            printf("> %s\n", echo);

        if (!strcmp(t, "C")) {
            int k = itok();

            memset(&cams[k], 0xa5, sizeof cams[k]);
            camera_init(&cams[k]);
            pcam(&cams[k]);
        } else if (!strcmp(t, "L")) {
            // A focus left on the camera, for the destructor to clear.
            int k = itok();

            cams[k].CurrentKey.FocalDistance = ftok();
            cams[k].CurrentKey.DepthOfField = ftok();
        } else if (!strcmp(t, "Y")) {
            // What the camera renders, for the constructor to clear.
            int k = itok();

            cams[k].CarNotToRender = car_at(itok());
            cams[k].RenderDash = itok();
            cams[k].CurrentKey.FieldOfView = (uint16_t)xtok();
        } else if (!strcmp(t, "P")) {
            pcam(&cams[itok()]);
        } else if (!strcmp(t, "V")) {
            int i = itok();

            eViews[i].pCamera = &cams[itok()];
        } else if (!strcmp(t, "Z")) {
            CameraStopUpdating = itok();
        } else if (!strcmp(t, "T")) {
            WorldTimeElapsed = ftok();
            RealTimeElapsed = ftok();
        } else if (!strcmp(t, "R")) {
            TheRaceParameters.TrackDirection = itok();
        } else if (!strcmp(t, "Q")) {
            int s = itok();

            if (s < 0) {
                pRaceCoordinator = NULL;
            } else {
                coordinator[0] = s;
                pRaceCoordinator = (RaceCoordinator *)(void *)coordinator;
            }
        } else if (!strcmp(t, "S")) {
            race.RaceStage = itok();
        } else if (!strcmp(t, "N")) {
            noise[0] = ftok();
            noise[1] = ftok();
            noise[2] = ftok();
            noise_at = 0;
        } else if (!strcmp(t, "E")) {
            elev = ftok();
        } else if (!strcmp(t, "H")) {
            read_vec(&wall);
        } else if (!strcmp(t, "X")) {
            int i = itok();

            read_vec(&box_min[i]);
            read_vec(&box_max[i]);
        } else if (!strcmp(t, "K")) {
            struct Car *k = &cars[itok()];

            read_vec(&k->State.Position);
            read_vec(&k->State.GeometryPosition);
            k->TheTrackPathCoordinate.RatioAroundTrack = ftok();
        } else if (!strcmp(t, "M")) {
            bMatrix4 *b = &cars[itok()].State.BodyMatrix;

            read_vec((bVector3 *)(void *)&b->v0);
            read_vec((bVector3 *)(void *)&b->v1);
            read_vec((bVector3 *)(void *)&b->v2);
            read_vec((bVector3 *)(void *)&b->v3);
        } else if (!strcmp(t, "A")) {
            bVector3 *a = arr_of(tok());

            read_vec(&a[itok()]);
        } else if (!strcmp(t, "F")) {
            const char *f = tok();

            set_cd(f, tok());
        } else if (!strcmp(t, "O")) {
            int j = itok(), view = itok(), car = itok();

            memset(&movs[j], 0xa5, sizeof movs[j]);
            bumper_camera_mover_construct(&movs[j], view, car_at(car), &cdt);
            pmov(j);
            pviews();
            pcam(movs[j].base.pCamera);
        } else if (!strcmp(t, "D")) {
            int j = itok();
            Camera *c = movs[j].base.pCamera;

            movs[j].base.vtbl->Destroy(&movs[j].base);
            pmov(j);
            pviews();
            pcam(c);
        } else if (!strcmp(t, "U")) {
            int j = itok();

            movs[j].base.vtbl->Update(&movs[j].base);
            pmov(j);
            pcam(movs[j].base.pCamera);
        } else if (!strcmp(t, "I")) {
            int j = itok();

            printf("  fin o%d %d\n", j,
                   (int)bumper_camera_mover_is_finished_fn(&movs[j].base));
        } else if (!strcmp(t, "G")) {
            query(itok());
        } else if (!strcmp(t, "W")) {
            int j = itok();

            set_mov(j, tok());
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
