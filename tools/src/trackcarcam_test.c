// Host harness for 3DS Files/source/trackcarcam.c, the jump cam's mover, and
// spline.c, the splines it flies along. Runs the op script
// tools/trackcarcam_check.py writes and prints the transcript it diffs
// against the retail image, run in mipsemu over the same script.
//
// The harness owns what the mover reads from outside: the cars, a race
// coordinator, the two clocks, the record and the shake it is built from
// and the record's three arrays. bFree prints the block it is given.
//
// Every camera, mover, record and array is filled with 0xa5 before the
// script sets it, so a field the port leaves alone and retail writes (or
// the other way round) shows. A float prints as its bits, every NaN as
// "nan", and a pointer by what it points at. The mover's three vectors
// print without their pad lanes, which retail leaves to the stack.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "camera.h"
#include "cammover.h"
#include "car.h"
#include "eview.h"
#include "race.h"
#include "realtime.h"
#include "spline.h"
#include "trackcarcam.h"

#define NCAM 4
#define NMOV 3
#define NCAR 3
#define NFOV 32
#define NEYE 8

// What trackcarcam.c links against, the harness's own.
float WorldTimeElapsed = 1.0f / 30.0f;
float RealTimeElapsed = 1.0f / 30.0f;

static Camera cams[NCAM];
static TrackCarCameraMover movs[NMOV];
static struct Car cars[NCAR];
static CameraDataItems cdt;
static CameraShake shk;
static bVector3 fovt[NFOV], eyev[NEYE], bankv[NEYE];
static Spline spl;
static char blk[2][16];
static int32_t coordinator[4];

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
    if (p == &TrackCarCameraMoverVtbl)
        return "track";
    if (p == fovt)
        return "fovt";
    if (p == eyev)
        return "eyev";
    if (p == bankv)
        return "bankv";
    if (p == &spl)
        return "spl";
    if (p == blk[0])
        return "blk0";
    if (p == blk[1])
        return "blk1";
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
        if (p == movs[i].TheCameraShake.CV) {
            sprintf(b, "o%d.cv", i);
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

// A pointer into one of the arrays, by its element, or "ext" for the
// spline's own extrapolated point.
static const char *nm_point(const bVector3 *p)
{
    static char b[32];
    const struct { const bVector3 *a; int n; const char *s; } arrs[] = {
        { fovt, NFOV, "fovt" }, { eyev, NEYE, "eyev" },
        { bankv, NEYE, "bankv" },
    };
    int i;

    for (i = 0; i < 3; i++) {
        if (p >= arrs[i].a && p < arrs[i].a + arrs[i].n) {
            sprintf(b, "%s:%d", arrs[i].s, (int)(p - arrs[i].a));
            return b;
        }
    }
    return "ext";
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
    static char buf[32][12];
    static int slot;
    char *b = buf[slot++ & 31];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

static void pvec(const char *tag, const bVector3 *v)
{
    printf(" %s %s %s %s %s", tag, fx(v->x), fx(v->y), fx(v->z), fx(v->pad));
}

static void pvec3(const char *tag, const bVector3 *v)
{
    printf(" %s %s %s %s", tag, fx(v->x), fx(v->y), fx(v->z));
}

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

// ------------------------------------------------------------ the records

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
    if (!strcmp(s, "blk0"))
        return blk[0];
    if (!strcmp(s, "blk1"))
        return blk[1];
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

static uint32_t word(const void *a)
{
    uint32_t u;

    memcpy(&u, a, 4);
    return u;
}

static void pmov(int j)
{
    const TrackCarCameraMover *o = &movs[j];
    const CameraMover *m = &o->base;
    const BSpline *c = &o->FocalDistCubic;
    const uint8_t *sb = (const uint8_t *)&o->TheCameraShake;
    int i;

    printf("  o%d type %d view %d en %d pview %s pcam %s player %08lx"
           " carnot %08lx dash %08lx vtbl %s next %s prev %s pad %08lx\n",
           j, (int)m->Type, m->ViewID, m->Enabled, nm(m->pView),
           nm(m->pCamera), (unsigned long)(uint32_t)(uintptr_t)m->pPlayer,
           (unsigned long)(uint32_t)(uintptr_t)m->CarNotToRender,
           (unsigned long)(uint32_t)m->RenderDash, nm(m->vtbl),
           nm(m->Node.next), nm(m->Node.prev),
           (unsigned long)word(o->_pad44));
    printf("   ");
    pvec3("look", &o->Look);
    pvec3("sv", &o->SpringVelocity);
    pvec3("sd", &o->SpringDisplacement);
    printf(" k %s d %s\n", fx(o->SpringConstant), fx(o->DampingConstant));
    pcd(&o->CD);
    printf("    pad %08lx shk ", (unsigned long)word(o->_pad268));
    for (i = 0; i < (int)sizeof o->TheCameraShake; i++)
        printf("%02x", sb[i]);
    printf("\n");
    pspline("fov", &o->FOVSpline);
    pspline("eye", &o->EyeSpline);
    pspline("bank", &o->BankSpline);
    pspline("shake", &o->ShakeSpline);
    printf("    ep %s sp %s pad %08lx %08lx", fx(o->EyeSplineParam),
           fx(o->ShakeSplineParam), (unsigned long)word(o->_pad1032),
           (unsigned long)word(o->_pad1032 + 4));
    pvec("ws", &o->WipeStart);
    pvec("we", &o->WipeEnd);
    printf(" halt %08lx apart %s car %s\n",
           (unsigned long)(uint32_t)o->WipeTrackingHalted,
           fx(o->WipeDistApart), nm(o->CarToFollow));
    printf("    cub %s %s %s %s %s %s %s %s %s %s %s st %04x fl %04x fe %08lx\n",
           fx(c->val), fx(c->dval), fx(c->valDesired), fx(c->dvalDesired),
           fx(c->coeff[0]), fx(c->coeff[1]), fx(c->coeff[2]),
           fx(c->coeff[3]), fx(c->time), fx(c->duration),
           fx(c->arrivalThreshold), (unsigned)(uint16_t)c->state,
           (unsigned)(uint16_t)c->flags,
           (unsigned long)(uint32_t)o->FocusEffects);
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
    memset(&shk, 0xa5, sizeof shk);
    memset(fovt, 0xa5, sizeof fovt);
    memset(eyev, 0xa5, sizeof eyev);
    memset(bankv, 0xa5, sizeof bankv);
    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        eViews[i].pCamera = 0;
        eViews[i].CameraMoverList.next = &eViews[i].CameraMoverList;
        eViews[i].CameraMoverList.prev = &eViews[i].CameraMoverList;
    }
    CameraStopUpdating = 0;
    WorldTimeElapsed = 1.0f / 30.0f;
    RealTimeElapsed = 1.0f / 30.0f;
    pRaceCoordinator = NULL;
    TheRaceParameters.TrackDirection = 0;
    bDefaultSeed = 0x12345678u;
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
    if (!strcmp(s, "b"))
        return bankv;
    fprintf(stderr, "bad array %s\n", s);
    exit(2);
}

static void set_mov(int j, const char *f)
{
    TrackCarCameraMover *o = &movs[j];

    if (!strcmp(f, "ep"))
        o->EyeSplineParam = ftok();
    else if (!strcmp(f, "sp"))
        o->ShakeSplineParam = ftok();
    else if (!strcmp(f, "halt"))
        o->WipeTrackingHalted = (int32_t)xtok();
    else if (!strcmp(f, "apart"))
        o->WipeDistApart = ftok();
    else if (!strcmp(f, "car"))
        o->CarToFollow = car_at(itok());
    else if (!strcmp(f, "fe"))
        o->FocusEffects = (int32_t)xtok();
    else if (!strcmp(f, "val"))
        o->FocalDistCubic.val = ftok();
    else if (!strcmp(f, "k"))
        o->SpringConstant = ftok();
    else if (!strcmp(f, "d"))
        o->DampingConstant = ftok();
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

static void spline_op(int evaluate)
{
    int type = itok(), n = itok();
    bVector3 *a = arr_of(tok());
    float t = ftok();
    const bVector3 *p;
    bVector3 o;

    memset(&spl, 0xa5, sizeof spl);
    spline_init(&spl, (SplineType)type, n, a, 16384);
    pspline("spl", &spl);
    memset(&o, 0xa5, sizeof o);
    if (evaluate) {
        float c0 = ftok(), c1 = ftok(), c2 = ftok(), c3 = ftok();

        spline_evaluate(&spl, &o, t, c0, c1, c2, c3);
        printf("  ev");
        pvec("o", &o);
        printf("\n");
        return;
    }
    p = spline_get_control_point(&spl, t);
    printf("  cp %s", nm_point(p));
    pvec("v", p);
    spline_get_point(&spl, &o, t);
    pvec("o", &o);
    printf("\n");
}

int main(int argc, char **argv)
{
    static char line[8192];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: trackcarcam_test SCRIPT\n");
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
        if (strchr("AFHhK", t[0]) == NULL || t[1])
            printf("> %s\n", echo);

        if (!strcmp(t, "C")) {
            int k = itok();

            memset(&cams[k], 0xa5, sizeof cams[k]);
            camera_init(&cams[k]);
            pcam(&cams[k]);
        } else if (!strcmp(t, "N")) {
            // Raw words, never followed: the mover only clears them.
            int k = itok();

            cams[k].CarNotToRender = (void *)(uintptr_t)xtok();
            cams[k].RenderDash = (int)xtok();
        } else if (!strcmp(t, "L")) {
            // A focus left on the camera, for the constructor to clear.
            int k = itok();

            cams[k].CurrentKey.FocalDistance = ftok();
            cams[k].CurrentKey.DepthOfField = ftok();
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
        } else if (!strcmp(t, "Q")) {
            int s = itok();

            if (s < 0) {
                pRaceCoordinator = NULL;
            } else {
                coordinator[0] = s;
                pRaceCoordinator = (RaceCoordinator *)(void *)coordinator;
            }
        } else if (!strcmp(t, "R")) {
            TheRaceParameters.TrackDirection = itok();
        } else if (!strcmp(t, "Y")) {
            bDefaultSeed = xtok();
        } else if (!strcmp(t, "K")) {
            struct Car *k = &cars[itok()];

            read_vec(&k->State.Position);
            read_vec(&k->State.GeometryPosition);
            read_mat(&k->State.BodyMatrix);
            k->TheTrackPathCoordinate.RatioAroundTrack = ftok();
        } else if (!strcmp(t, "A")) {
            bVector3 *a = arr_of(tok());

            read_vec(&a[itok()]);
        } else if (!strcmp(t, "F")) {
            const char *f = tok();

            set_cd(f, tok());
        } else if (!strcmp(t, "H")) {
            shk.Speed = ftok();
            shk.NumCVs = (int32_t)xtok();
            shk.BankNumber = (int32_t)xtok();
        } else if (!strcmp(t, "h")) {
            read_vec(&shk.CV[itok()]);
        } else if (!strcmp(t, "O")) {
            int j = itok(), view = itok(), car = itok(), fe = itok();

            memset(&movs[j], 0xa5, sizeof movs[j]);
            track_car_camera_mover_init(&movs[j], view, car_at(car), &cdt,
                                        &shk, fe);
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
        } else if (!strcmp(t, "G")) {
            query(itok());
        } else if (!strcmp(t, "W")) {
            int j = itok();

            set_mov(j, tok());
        } else if (!strcmp(t, "s")) {
            spline_op(0);
        } else if (!strcmp(t, "e")) {
            spline_op(1);
        } else if (!strcmp(t, "x")) {
            int flags = itok();

            memset(&spl, 0xa5, sizeof spl);
            spline_init(&spl, SPLINE_CLAMP, 4, eyev, 16384);
            spl.pControlPointArray = sym(tok());
            spl.pCalTable = sym(tok());
            spline_destroy(&spl, flags);
            printf("  destroyed\n");
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
