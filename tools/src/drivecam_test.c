// Host harness for 3DS Files/source/drivecam.c, DriveCameraMover. Runs the
// op script tools/drivecam_check.py writes and prints the transcript it
// diffs against the retail image, run in mipsemu over the same script.
//
// The mover carries a TopologyCoordinate, whose constructor and destructor
// are track.c's; the harness does not link that and has its own, which print
// what they were given. The model stubs retail's two the same way.
//
// Update's callees outside the camera and the maths are stubs here and in
// the model alike: the car lookup by driver number, the cop manager's two,
// GetYaw, road noise, the topology's SetInterestBBox, GetElevation and
// ConstrainToTopology, PointInShaft, the car's bounding box and the camera
// shake. Each prints what it was given and answers from the script.
//
// Every camera, mover, car, car type and player is filled with 0xa5 at the
// start of each scenario (a mover again before it is built), so a field the
// port leaves alone and retail writes (or the other way round) shows. A
// float prints as its bits, every NaN as "nan", and a pointer by what it
// points at: a camera or its target, a mover, a view or its list's head, a
// car or its GeometryPosition, a player, a vtable, or a car type and the
// byte offset into it.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "camera.h"
#include "cammover.h"
#include "car.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "drivecam.h"
#include "drivetarget.h"
#include "eview.h"
#include "player.h"
#include "realtime.h"
#include "shake.h"
#include "topology.h"
#include "track.h"
#include "world.h"

// realtime.c's, cartypeinfo.c's and drivetarget.c's, which the harness does
// not link. reset() puts each back to retail's value.
float RealTimeElapsed;
float WorldTimeElapsed;
const CarTypeInfo *CarTypeInfoArray;
int32_t CameraFollowDefaultCar;
int32_t CameraFollowThisCarInstead;

#define NCAM 4
#define NDRV 4
#define NCAR 4
#define NCTI 3
#define NPL 2

#define NPOLY 24
#define NCOP 3
#define NPUR 2
#define NDRIVER 12

static Camera cams[NCAM];
static DriveCameraMover drvs[NDRV];
static Car cars[NCAR];
static CarTypeInfo ctis[NCTI];
static struct Player players[NPL];
static TrackPolygon polys[NPOLY];
static tCop cops[NCOP];
static tPursuit pursuits[NPUR];
static char copmgr;                     // stands in for tCopManager

// What the stubs answer.
static int      poly_inside[NPOLY];
static int      cand[NPOLY], ncand;
static int      bydriver[NDRIVER];      // driver number -> car, or -1
static int      copbycar[NCAR], copbychase[NCAR];
static float    yaws[NCAR];
static float    noise_value, elev_value;
static bVector3 constrain_delta;
static int      constrain_ret;
static bVector3 box_min[NCAR], box_max[NCAR];
static bVector3 shake_delta;

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    const char *c = (const char *)p;
    int i;

    if (p == 0)
        return "null";
    if (p == &CameraMoverBaseVtbl)
        return "base";
    if (p == &DriveCameraMoverVtbl)
        return "drive";
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
    for (i = 0; i < NDRV; i++) {
        if (p == &drvs[i]) {
            sprintf(b, "d%d", i);
            return b;
        }
    }
    for (i = 0; i < NCAR; i++) {
        if (p == &cars[i]) {
            sprintf(b, "car%d", i);
            return b;
        }
        if (p == &cars[i].State.GeometryPosition) {
            sprintf(b, "car%d.gpos", i);
            return b;
        }
    }
    for (i = 0; i < NPL; i++) {
        if (p == &players[i]) {
            sprintf(b, "p%d", i);
            return b;
        }
    }
    for (i = 0; i < NCAR; i++) {
        if (p == &cars[i].State) {
            sprintf(b, "car%d.state", i);
            return b;
        }
    }
    for (i = 0; i < NDRV; i++) {
        if (p == &drvs[i].TheTopologyCoordinate) {
            sprintf(b, "d%d.tc", i);
            return b;
        }
    }
    for (i = 0; i < NPOLY; i++) {
        if (p == &polys[i]) {
            sprintf(b, "poly%d", i);
            return b;
        }
    }
    for (i = 0; i < NCOP; i++) {
        if (p == &cops[i]) {
            sprintf(b, "cop%d", i);
            return b;
        }
    }
    for (i = 0; i < NPUR; i++) {
        if (p == &pursuits[i]) {
            sprintf(b, "pur%d", i);
            return b;
        }
    }
    if (p == &copmgr)
        return "copmgr";
    for (i = 0; i < NCTI; i++) {
        const char *t = (const char *)&ctis[i];

        if (c >= t - 256 && c < t + sizeof ctis[i]) {
            sprintf(b, "t%d%+d", i, (int)(c - t));
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

static unsigned long u32(int32_t v)
{
    return (unsigned long)(uint32_t)v;
}

static int drv_index(const DriveCameraMover *d)
{
    return (int)(d - drvs);
}

// The topology's two, as the model's stubs print them.
void topology_init(TopologyCoordinate *tc)
{
    const DriveCameraMover *d = (const DriveCameraMover *)
        ((const char *)tc - offsetof(DriveCameraMover, TheTopologyCoordinate));

    printf("  topo init d%d\n", drv_index(d));
}

void topology_destroy(TopologyCoordinate *tc)
{
    const DriveCameraMover *d = (const DriveCameraMover *)
        ((const char *)tc - offsetof(DriveCameraMover, TheTopologyCoordinate));

    printf("  topo destroy d%d\n", drv_index(d));
}

static int car_index(const Car *c)
{
    return c == NULL ? -1 : (int)(c - cars);
}

static const char *v4(const bVector3 *v)
{
    static char buf[8][40];
    static int slot;
    char *b = buf[slot++ & 7];

    sprintf(b, "%s %s %s %s", fx(v->x), fx(v->y), fx(v->z), fx(v->pad));
    return b;
}

static void pmatrix(const char *tag, const bMatrix4 *m)
{
    const float *f = &m->v0.x;
    int i;

    printf("%s", tag);
    for (i = 0; i < 16; i++)
        printf(" %s", fx(f[i]));
    printf("\n");
}

// ------------------------------------------------ Update's stubs

struct Car *world_get_car_by_driver_number(int32_t n)
{
    Car *c = n >= 0 && n < NDRIVER && bydriver[n] >= 0
        ? &cars[bydriver[n]] : NULL;

    printf("  bydriver %d -> %s\n", (int)n, nm(c));
    return c;
}

static tCop *cop_by_car(tCopManager *m, struct Car *c)
{
    int k = copbycar[car_index(c)];
    tCop *r = k < 0 ? NULL : &cops[k];

    printf("  copbycar %s %s -> %s\n", nm(m), nm(c), nm(r));
    return r;
}

static tCop *cop_by_chase(tCopManager *m, struct Car *c)
{
    int k = copbychase[car_index(c)];
    tCop *r = k < 0 ? NULL : &cops[k];

    printf("  copbychase %s %s -> %s\n", nm(m), nm(c), nm(r));
    return r;
}

float carstate_get_yaw(CarState *st)
{
    int c = (int)((const Car *)((const char *)st - offsetof(Car, State))
                  - cars);

    printf("  getyaw %s -> %s\n", nm(st), fx(yaws[c]));
    return yaws[c];
}

float track_get_road_noise(const bVector2 *p, int32_t terrain)
{
    printf("  noise %s %s %d -> %s\n", fx(p->x), fx(p->y), (int)terrain,
           fx(noise_value));
    return noise_value;
}

void topology_set_interest_bbox3(TopologyCoordinate *tc, const bVector3 *pos,
                                 float r, const bVector3 *vel)
{
    int i;

    printf("  bbox %s pos %s r %s vel %s\n", nm(tc), v4(pos), fx(r),
           v4(vel));
    for (i = 0; i < ncand; i++)
        tc->TrackPolygonTable[i] = &polys[cand[i]];
    tc->TotalNumTrackPolygons = ncand;
}

float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    printf("  elev %s pt %s args %d%d%d -> %s\n", nm(tc), v4(pt),
           terrain != NULL, normal != NULL, found != NULL, fx(elev_value));
    return elev_value;
}

int topology_constrain(TopologyCoordinate *tc, int type, int twoSided,
                       const bVector3 *from, bVector3 *to, float dist,
                       float lift)
{
    printf("  constrain %s type %d two %d from %s to %s dist %s lift %s\n",
           nm(tc), type, twoSided, v4(from), v4(to), fx(dist), fx(lift));
    to->x = to->x + constrain_delta.x;
    to->y = to->y + constrain_delta.y;
    to->z = to->z + constrain_delta.z;
    return constrain_ret;
}

// The plane's distance, as the model works it out: ((nx px + ny py) + nz pz)
// + D, each step a float.
int trackpolygon_point_in_shaft(const TrackPolygon *tp, const bVector3 *pt,
                                float *dist)
{
    int k = (int)(tp - polys);
    float d = tp->Normal.x * pt->x;

    d = d + tp->Normal.y * pt->y;
    d = d + tp->Normal.z * pt->z;
    d = d + tp->PlaneDistance;
    *dist = d;
    printf("  shaft %s at %s %s %s -> %d %s\n", nm(tp), fx(pt->x), fx(pt->y),
           fx(pt->z), poly_inside[k], fx(d));
    return poly_inside[k];
}

void car_get_car_space_bounding_box(Car *c, bVector3 *min, bVector3 *max)
{
    int k = car_index(c);

    printf("  box %s\n", nm(c));
    *min = box_min[k];
    *max = box_max[k];
}

void apply_camera_shake(int32_t view, bMatrix4 *m)
{
    printf("  shake view %d\n", (int)view);
    pmatrix("   ", m);
    m->v3.x = m->v3.x + shake_delta.x;
    m->v3.y = m->v3.y + shake_delta.y;
    m->v3.z = m->v3.z + shake_delta.z;
}

// Every word of the camera before CarNotToRender, then it and RenderDash by
// name.
static void pcam(const Camera *c)
{
    uint32_t w[111];
    int i;

    memcpy(w, c, sizeof w);
    printf("    camera %s", nm(c));
    for (i = 0; i < 111; i++)
        printf(" %08lx", (unsigned long)w[i]);
    printf(" carnot %s dash %08lx\n", nm(c->CarNotToRender),
           u32(c->RenderDash));
}

static void pdrv(int j)
{
    const DriveCameraMover *d = &drvs[j];
    const CameraMover *m = &d->base;
    const Camera *c = m->pCamera;
    int i;

    printf("  d%d type %d view %d en %d pview %s pcam %s player %s"
           " carnot %08lx dash %08lx vtbl %s next %s prev %s\n",
           j, (int)m->Type, m->ViewID, m->Enabled, nm(m->pView),
           nm(m->pCamera), nm(m->pPlayer),
           (unsigned long)(uint32_t)(uintptr_t)m->CarNotToRender,
           u32(m->RenderDash), nm(m->vtbl), nm(m->Node.next),
           nm(m->Node.prev));
    printf("    car %s info %s pov %08lx want %s lbp %s ilbp %08lx"
           " ilbh %s lba %04x\n",
           nm(d->CarToFollow), nm(d->pCameraInfo), u32(d->POVIndex),
           fx(d->DesiredLookBackParam), fx(d->LookBackParam),
           u32(d->iLookBackParam), fx(d->iLookBackHeight),
           (unsigned)d->LookBackAngle);
    printf("    yaw %08lx %08lx amount %s pitch %08lx %08lx"
           " lag %s %s speed %s touch %s\n",
           u32(d->LastCarYaw), u32(d->LastBoomYaw),
           fx(d->AmountToUseYawCorrection), u32(d->LastCarPitch),
           u32(d->LastBoomPitch), fx(d->DesiredAccelLag),
           fx(d->CurrentAccelLag), fx(d->LastCarSpeed),
           fx(d->TouchingGroundFactor));
    printf("    dlag %08lx lbspeed %s pf %08lx cur %s adj %s hold %s"
           " fract %s mult %s\n",
           u32(d->DisableLag), fx(d->LookbackSpeed), u32(d->PerfectFocus),
           fx(d->CamCurrentAccel), fx(d->CamLagAdjust),
           fx(d->CamHoldLagTime), fx(d->CamTimeFract),
           fx(d->CamAdjustMultiplier));
    printf("    accel");
    for (i = 0; i < 20; i++)
        printf(" %s", fx(d->CamLastAccel[i]));
    printf("\n");
    if (c)
        printf("    cam %s carnot %s dash %08lx fd %s dof %s near %s"
               " far %s\n", nm(c), nm(c->CarNotToRender),
               u32(c->RenderDash), fx(c->CurrentKey.FocalDistance),
               fx(c->CurrentKey.DepthOfField), fx(c->CurrentKey.NearZ),
               fx(c->CurrentKey.FarZ));
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
    printf("%s mode %d\n", any ? "" : " -", (int)CurrentViewMode);
}

static void query(int j)
{
    DriveCameraMover *d = &drvs[j];
    CameraMover *m = &d->base;
    const CameraMoverVtbl *vt = m->vtbl;
    const CameraInfo *info = vt->GetCameraInfo(m);
    const char *pov[6];
    int i, ext, lb;
    float gap;

    for (i = 0; i < 6; i++)
        pov[i] = nm(vt->GetPOV(m, i - 1));
    ext = vt->IsExteriorView(m);
    lb = vt->IsLookingBack(m);
    gap = vt->GetWallGap(m);
    printf("  q d%d info %s pov %s %s %s %s %s %s ext %d lb %d gap %s"
           " car %s tgt %s\n",
           j, nm(info), pov[0], pov[1], pov[2], pov[3], pov[4], pov[5],
           ext, lb, fx(gap), nm(vt->GetCarToFollow(m)),
           nm(vt->GetTarget(m)));
    printf("  a d%d lba %04x speed %s lag %08lx want %d full %d\n",
           j, (unsigned)drive_cam_get_lookback_angle(d),
           fx(drive_cam_get_lookback_speed(d)),
           u32(drive_cam_get_disable_lag(d)), drive_cam_looking_back(d),
           drive_cam_look_back_full(d));
}

// The tuning Update reads, by the checker's names, with retail's values.
static const struct {
    const char *name;
    void *at;
    int kind;                           // 0 float, 1 int32, 2 uint16
    uint32_t value;
} tuning[] = {
    { "DriveUseTweakables", &DriveUseTweakables, 1, 0 },
    { "DriveLag", &DriveLag, 0, 0x40e9999a },
    { "DriveHeight", &DriveHeight, 0, 0x40133333 },
    { "DriveLatOffset", &DriveLatOffset, 0, 0 },
    { "DriveAngle", &DriveAngle, 2, 0 },
    { "DriveMaxAngle", &DriveMaxAngle, 2, 2000 },
    { "CamGlobalMultiplier", &CamGlobalMultiplier, 0, 0x3f800000 },
    { "CamAdjustment", &CamAdjustment, 0, 0x3cf5c28f },
    { "CamBackAdjust", &CamBackAdjust, 0, 0x3c449ba6 },
    { "CamHoldTimeout", &CamHoldTimeout, 0, 0x40000000 },
    { "CamYawAdjuster", &CamYawAdjuster, 0, 0x40c00000 },
    { "CamAccelScaleRatio", &CamAccelScaleRatio, 0, 0x3f19999a },
    { "CamDecelScaleRatio", &CamDecelScaleRatio, 0, 0x3d3851ec },
    { "CamRangeCheckA", &CamRangeCheckA, 0, 0x3f333333 },
    { "CamRangeCheckD", &CamRangeCheckD, 0, 0xbe99999a },
    { "CamLagMultiplier", &CamLagMultiplier, 0, 0x3f800000 },
    { "CamSpeedAdjust", &CamSpeedAdjust, 0, 0x43fa0000 },
    { "CamHeightMultiplierD", &CamHeightMultiplierD, 0, 0x3e4ccccd },
    { "CamAccelCap", &CamAccelCap, 0, 0x40c00000 },
    { "CamDecelCap", &CamDecelCap, 0, 0xbf800000 },
    { "CamDisableAdjust", &CamDisableAdjust, 0, 0x3ecccccd },
    { "CamBackAdjustQuicker", &CamBackAdjustQuicker, 0, 0x40400000 },
    { "RoadNoiseAmplitude", &RoadNoiseAmplitude, 0, 0x437a0000 },
    { "CameraFollowDefaultCar", &CameraFollowDefaultCar, 1, 1 },
    { "CameraFollowThisCarInstead", &CameraFollowThisCarInstead, 1,
      0xffffffffu },
    { "WorldTimeElapsed", &WorldTimeElapsed, 0, 0x3c888889 },
    { "RealTimeElapsed", &RealTimeElapsed, 0, 0x3c888889 },
};

static void set_tuning(int i, uint32_t v)
{
    if (tuning[i].kind == 2) {
        uint16_t h = (uint16_t)v;

        memcpy(tuning[i].at, &h, 2);
    } else {
        memcpy(tuning[i].at, &v, 4);
    }
}

static void tuning_defaults(void)
{
    size_t i;

    for (i = 0; i < sizeof tuning / sizeof tuning[0]; i++)
        set_tuning((int)i, tuning[i].value);
}

static void tune(const char *name, uint32_t v)
{
    size_t i;

    for (i = 0; i < sizeof tuning / sizeof tuning[0]; i++) {
        if (!strcmp(tuning[i].name, name)) {
            set_tuning((int)i, v);
            return;
        }
    }
    fprintf(stderr, "bad tuning %s\n", name);
    exit(2);
}

static void reset(void)
{
    int i;

    memset(cams, 0xa5, sizeof cams);
    memset(drvs, 0xa5, sizeof drvs);
    memset(cars, 0xa5, sizeof cars);
    memset(ctis, 0xa5, sizeof ctis);
    memset(players, 0xa5, sizeof players);
    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        eViews[i].pCamera = 0;
        eViews[i].CameraMoverList.next = &eViews[i].CameraMoverList;
        eViews[i].CameraMoverList.prev = &eViews[i].CameraMoverList;
    }
    CameraStopUpdating = 0;
    CurrentViewMode = 0;
    CarTypeInfoArray = &ctis[0];

    memset(polys, 0xa5, sizeof polys);
    memset(cops, 0xa5, sizeof cops);
    memset(pursuits, 0xa5, sizeof pursuits);
    for (i = 0; i < NPOLY; i++)
        poly_inside[i] = 0;
    ncand = 0;
    for (i = 0; i < NDRIVER; i++)
        bydriver[i] = -1;
    for (i = 0; i < NCAR; i++) {
        copbycar[i] = -1;
        copbychase[i] = -1;
        yaws[i] = 0.0f;
        memset(&box_min[i], 0, sizeof box_min[i]);
        memset(&box_max[i], 0, sizeof box_max[i]);
    }
    noise_value = 0.0f;
    elev_value = 0.0f;
    memset(&constrain_delta, 0, sizeof constrain_delta);
    constrain_ret = 0;
    memset(&shake_delta, 0, sizeof shake_delta);
    pCopManager = NULL;
    gCopManagerGetCopByCarFn = cop_by_car;
    gCopManagerGetCopByChaseFn = cop_by_chase;
    tuning_defaults();
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

static void vec(bVector3 *v)
{
    v->x = ftok();
    v->y = ftok();
    v->z = ftok();
    v->pad = ftok();
}

static void set_drive(int j, const char *f)
{
    DriveCameraMover *d = &drvs[j];

    if (!strcmp(f, "want"))
        d->DesiredLookBackParam = ftok();
    else if (!strcmp(f, "lbp"))
        d->LookBackParam = ftok();
    else if (!strcmp(f, "pov"))
        d->POVIndex = (int32_t)xtok();
    else if (!strcmp(f, "lba"))
        d->LookBackAngle = (uint16_t)xtok();
    else if (!strcmp(f, "car")) {
        int c = itok();

        d->CarToFollow = c < 0 ? NULL : &cars[c];
    } else if (!strcmp(f, "player")) {
        int p = itok();

        camera_mover_set_player(&d->base, p < 0 ? NULL : &players[p]);
    } else {
        fprintf(stderr, "bad field %s\n", f);
        exit(2);
    }
}

// The checker's scribble_word(): a finite float's bits, never 0 or 1.
static uint32_t scribble_word(uint32_t seed, int k)
{
    uint32_t v = (seed ^ (uint32_t)k * 0x9e3779b9u) & ~0x40000000u;

    return v == 0 || v == 0x3f800000u ? v | 1 : v;
}

// X: the words only Update writes, in the checker's UPDATE_WORDS order.
static void scribble(DriveCameraMover *d, uint32_t seed)
{
    void *f[36];
    int n = 0, i;

    f[n++] = &d->iLookBackParam;
    f[n++] = &d->iLookBackHeight;
    f[n++] = &d->LastCarYaw;
    f[n++] = &d->LastBoomYaw;
    f[n++] = &d->AmountToUseYawCorrection;
    f[n++] = &d->LastCarPitch;
    f[n++] = &d->LastBoomPitch;
    f[n++] = &d->DesiredAccelLag;
    f[n++] = &d->CurrentAccelLag;
    f[n++] = &d->LastCarSpeed;
    f[n++] = &d->TouchingGroundFactor;
    for (i = 0; i < 20; i++)
        f[n++] = &d->CamLastAccel[i];
    f[n++] = &d->CamCurrentAccel;
    f[n++] = &d->CamLagAdjust;
    f[n++] = &d->CamHoldLagTime;
    f[n++] = &d->CamTimeFract;
    f[n++] = &d->CamAdjustMultiplier;
    for (i = 0; i < n; i++) {
        uint32_t v = scribble_word(seed, i);

        memcpy(f[i], &v, 4);
    }
}

static void set_camera(int k, const char *f, uint32_t v)
{
    Camera *c = &cams[k];

    if (!strcmp(f, "carnot"))
        c->CarNotToRender = (void *)(uintptr_t)v;
    else if (!strcmp(f, "dash"))
        c->RenderDash = (int)v;
    else if (!strcmp(f, "fd"))
        c->CurrentKey.FocalDistance = from_bits(v);
    else if (!strcmp(f, "dof"))
        c->CurrentKey.DepthOfField = from_bits(v);
    else {
        fprintf(stderr, "bad camera field %s\n", f);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: drivecam_test SCRIPT\n");
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
        printf("> %s\n", echo);

        if (!strcmp(t, "C")) {
            camera_init(&cams[itok()]);
        } else if (!strcmp(t, "c")) {
            int k = itok();
            const char *f = tok();

            set_camera(k, f, xtok());
        } else if (!strcmp(t, "V")) {
            int i = itok();

            eViews[i].pCamera = &cams[itok()];
        } else if (!strcmp(t, "A")) {
            Car *car = &cars[itok()];

            car->pCarTypeInfo = &ctis[itok()];
            car->State.Angle = (uint16_t)xtok();
            car->State.BodyMatrix.v0.z = ftok();
            car->State.ForwardSpeed = ftok();
            vec(&car->State.GeometryPosition);
            vec(&car->State.Position);
        } else if (!strcmp(t, "I")) {
            CameraInfo *ci = &ctis[itok()].Camera;

            ci->NumFullScreenPOVs = (int32_t)xtok();
            ci->NumSplitScreenPOVs = (int32_t)xtok();
        } else if (!strcmp(t, "P")) {
            int k = itok(), off = itok();
            uint32_t v = xtok();

            memcpy((char *)&ctis[k] + off, &v, 4);
        } else if (!strcmp(t, "G")) {
            CarTypeInfoArray = &ctis[itok()];
        } else if (!strcmp(t, "L")) {
            int p = itok();

            players[p].PlayerSettings.Lookback = (int32_t)xtok();
        } else if (!strcmp(t, "N")) {
            int j = itok(), view = itok(), car = itok(), pov = itok();
            float speed = ftok();
            int lag = (int)xtok(), lb = (int)xtok(), pf = (int)xtok();

            memset(&drvs[j], 0xa5, sizeof drvs[j]);
            drive_cam_init(&drvs[j], view, &cars[car], pov, speed, lag, lb,
                           pf);
            pdrv(j);
            pviews();
        } else if (!strcmp(t, "D")) {
            int j = itok();

            drvs[j].base.vtbl->Destroy(&drvs[j].base);
            pdrv(j);
            pviews();
        } else if (!strcmp(t, "R")) {
            int j = itok();

            drvs[j].base.vtbl->ResetState(&drvs[j].base);
            pdrv(j);
        } else if (!strcmp(t, "X")) {
            int j = itok();

            scribble(&drvs[j], xtok());
        } else if (!strcmp(t, "S")) {
            int j = itok();

            drive_cam_set_pov_index(&drvs[j], (int)xtok());
        } else if (!strcmp(t, "F")) {
            int j = itok();

            set_drive(j, tok());
        } else if (!strcmp(t, "W")) {
            DriveCameraMover *d = &drvs[itok()];
            const char *f = tok();
            uint32_t v = xtok();

            if (!strcmp(f, "speed"))
                drive_cam_set_lookback_speed(d, from_bits(v));
            else if (!strcmp(f, "lag"))
                drive_cam_set_disable_lag(d, (int32_t)v);
            else if (!strcmp(f, "look"))
                drive_cam_set_look_back(d, (int)v);
            else {
                fprintf(stderr, "bad setter %s\n", f);
                return 2;
            }
        } else if (!strcmp(t, "Q")) {
            query(itok());
        } else if (!strcmp(t, "M")) {
            CurrentViewMode = itok();
        } else if (!strcmp(t, "Z")) {
            CameraStopUpdating = itok();
        } else if (!strcmp(t, "Y")) {
            uint16_t a = (uint16_t)xtok();

            printf("  y %04x yaw %s pitch %08lx incar %08lx\n", (unsigned)a,
                   fx(drive_cam_get_correction_yaw(a)),
                   u32(drive_cam_get_correction_pitch(a)),
                   u32(drive_cam_get_in_car_correction_angle(a)));
        } else if (!strcmp(t, "K")) {
            int f = itok(), to = itok();
            bMatrix4 m;

            memset(&m, 0, sizeof m);
            m.v0.x = ftok(); m.v0.y = ftok(); m.v0.z = ftok(); m.v0.w = ftok();
            m.v1.x = ftok(); m.v1.y = ftok(); m.v1.z = ftok(); m.v1.w = ftok();
            printf("  k %04x\n", (unsigned)calculate_lookback_angle(
                       &cars[f], &cars[to], &m));
        } else if (!strcmp(t, "E")) {
            Car *car = &cars[itok()];
            float *m = &car->State.BodyMatrix.v0.x;
            int i;

            vec(&car->State.Velocity);
            vec(&car->State.Acceleration);
            for (i = 0; i < 16; i++)
                m[i] = ftok();
            car->State.nWheelsTouchingGround = (int32_t)xtok();
            car->State.DriverMode = (int32_t)xtok();
        } else if (!strcmp(t, "z")) {
            int k = itok();

            ctis[k].Body.Zdim = ftok();
        } else if (!strcmp(t, "T")) {
            const char *name = tok();

            tune(name, xtok());
        } else if (!strcmp(t, "g")) {
            int n = itok();

            bydriver[n] = itok();
        } else if (!strcmp(t, "H")) {
            pCopManager = itok() ? (tCopManager *)(void *)&copmgr : NULL;
        } else if (!strcmp(t, "o")) {
            int k = itok(), pur = itok(), car = itok();

            cops[k].pMyPursuit = pur < 0 ? NULL : &pursuits[pur];
            cops[k].pMyCar = car < 0 ? NULL : &cars[car];
        } else if (!strcmp(t, "u")) {
            int k = itok(), car = itok();

            pursuits[k].pChasedCar = car < 0 ? NULL : &cars[car];
        } else if (!strcmp(t, "O")) {
            int c = itok();

            copbycar[c] = itok();
            copbychase[c] = itok();
        } else if (!strcmp(t, "a")) {
            int c = itok();

            yaws[c] = ftok();
        } else if (!strcmp(t, "n")) {
            noise_value = ftok();
        } else if (!strcmp(t, "e")) {
            elev_value = ftok();
        } else if (!strcmp(t, "p")) {
            TrackPolygon *tp = &polys[itok()];

            tp->Flags = (uint8_t)xtok();
            tp->TheTerrainType = (uint8_t)xtok();
            tp->Normal.x = ftok();
            tp->Normal.y = ftok();
            tp->Normal.z = ftok();
            tp->PlaneDistance = ftok();
            poly_inside[tp - polys] = (int)xtok();
        } else if (!strcmp(t, "l")) {
            int i;

            ncand = itok();
            for (i = 0; i < ncand; i++)
                cand[i] = itok();
        } else if (!strcmp(t, "t")) {
            constrain_delta.x = ftok();
            constrain_delta.y = ftok();
            constrain_delta.z = ftok();
            constrain_ret = (int)xtok();
        } else if (!strcmp(t, "b")) {
            int c = itok();

            vec(&box_min[c]);
            vec(&box_max[c]);
        } else if (!strcmp(t, "s")) {
            shake_delta.x = ftok();
            shake_delta.y = ftok();
            shake_delta.z = ftok();
        } else if (!strcmp(t, "U")) {
            int j = itok();

            drvs[j].base.vtbl->Update(&drvs[j].base);
            pdrv(j);
            if (drvs[j].base.pCamera)
                pcam(drvs[j].base.pCamera);
            printf("  g follow %ld cgm %s\n", (long)CameraFollowThisCarInstead,
                   fx(CamGlobalMultiplier));
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
