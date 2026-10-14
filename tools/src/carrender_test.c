// carrender_test -- the host half of tools/carrender_check.py: reads its
// scenarios, lays each world out, calls carrenderinfo_render, and prints
// what every stand-in was asked and what Render left behind, in the
// model's words.
//
// A scenario is a run of lines, "S" first and "G" to go; every value is
// hex, a float by its bits. The world is laid out afresh each time, every
// byte Render should not read 0xa5 first.

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmatrix.h"
#include "camera.h"
#include "car.h"
#include "cardamage.h"
#include "cardriver.h"
#include "carrenderinfo.h"
#include "cartypeinfo.h"
#include "collisionbody.h"
#include "eframe.h"
#include "emath.h"
#include "emodel.h"
#include "eview.h"
#include "eviewmatrix.h"
#include "frameprof.h"
#include "gameflow.h"
#include "realtime.h"
#include "scenery.h"
#include "scenerycull.h"
#include "sun.h"
#include "topology.h"
#include "track.h"
#include "trackflow.h"
#include "vclip.h"

#define PATTERN    0xa5
#define FRAME_SIZE 0x10000
#define NMODELS    21

// ------------------------------------------------ what Render reaches

BGameFlow     *gTrackFlowGameFlow;
TrackInfo     *CurrentTrackInfo;
SunChunkInfoE *SunInfo;
int32_t        WorldTimeFrames;
bMatrix4       hack_man_matrix;
void (*gElSetupLightContextFn)(eLightContext *lc, const bMatrix4 *local_world,
                               const bMatrix4 *hack, const bVector4 *eye,
                               eView *view);
void (*gEModelRenderFn)(eModel *m, bMatrix4 *matrix, void *light,
                        uint32_t flags);
CarPartCullInfo CarPartCullInfoTable[NUM_CULLABLE_CAR_PARTS];

uint8_t  *CurrentBufferPos;
uint8_t  *CurrentBufferEnd;
int32_t   FrameMallocFailed;
uint32_t  FrameMallocFailAmount;

// ------------------------------------------------------------ the world

static BGameFlow      g_flow;
static TrackInfo      g_track;
static SunChunkInfoE  g_sun;
static CarRenderInfo  g_ri;
static Car            g_car;
static CarDamage      g_dmg;
static RideInfo       g_ride;
static DriverInfo     g_drvinfo;
static CarDriver      g_cardrv;
static CarCollisionBody g_colbody;
static VCPolyhedron   g_poly;
static VCVertex       g_verts[64];
static uint32_t       g_anim[32];
static CarTypeInfo    g_cti;
static eView          g_view;
static Camera         g_cam;
static bMatrix4       g_wvm, g_wscm;
static bVector3       g_pos;
static bMatrix4       g_body, g_tm[4], g_bm[4];
static uint32_t       g_skinlm[4], g_shadow[4], g_ramp[4];
static eSolid         g_solids[NMODELS];
static uint8_t        g_rigid[2][16];
static eLightFlare    g_lfs[64];
static _Alignas(16) uint8_t g_frame[FRAME_SIZE + 0x1000];

static uint32_t g_extra, g_forced;
static int32_t  g_px, g_vm, g_cls, g_queued;
static float    g_vd;
static uint32_t g_emask, g_exmask;
static uint32_t g_sunl[8];
static int32_t  g_nsunl;
static float    g_ebase, g_eax, g_eay;
static int32_t  g_emod, g_eoff;
static float    g_enrm[4];

static int32_t  g_nlc, g_nel, g_neb, g_nxb;

// ------------------------------------------------------------- printing

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float flt(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static uint32_t word_at(const void *p, size_t off)
{
    uint32_t u;

    memcpy(&u, (const uint8_t *)p + off, 4);
    return u;
}

static void put_word(void *p, size_t off, uint32_t u)
{
    memcpy((uint8_t *)p + off, &u, 4);
}

static void words(const void *p, int n)
{
    int i;

    for (i = 0; i < n; i++)
        printf("%s%08x", i ? " " : "", word_at(p, 4 * (size_t)i));
}

typedef struct { const void *p; char name[24]; } Name;
static Name g_names[160];
static int  g_nnames;

static void reg(const void *p, const char *name)
{
    Name *n = &g_names[g_nnames++];

    n->p = p;
    snprintf(n->name, sizeof n->name, "%s", name);
}

static const char *label(const void *vp)
{
    static char buf[4][32];
    static int k;
    const uint8_t *p = vp;
    char *b = buf[k++ & 3];
    int i;

    if (p == NULL)
        return "null";
    if (p >= g_frame && p < g_frame + sizeof g_frame) {
        snprintf(b, 32, "F+%x", (unsigned)(p - g_frame));
        return b;
    }
    {
        struct { const bVector3 *base; int n; const char *name; } h[3] = {
            { hullVertArray3, 3 * HULL_MAX_POINTS, "h3" },
            { hullVertArray2, HULL_MAX_POINTS, "h2" },
            { hullVertArray1, HULL_MAX_POINTS, "h1" },
        };

        for (i = 0; i < 3; i++) {
            const uint8_t *b0 = (const uint8_t *)h[i].base;

            if (p >= b0 && p < b0 + sizeof(bVector3) * (size_t)h[i].n
                && (size_t)(p - b0) % sizeof(bVector3) == 0) {
                snprintf(b, 32, "%s[%d]", h[i].name,
                         (int)((size_t)(p - b0) / sizeof(bVector3)));
                return b;
            }
        }
    }
    for (i = 0; i < g_nnames; i++)
        if (g_names[i].p == vp)
            return g_names[i].name;
    return "-";
}

static eModel *model_n(int k)
{
    if (k < 4)
        return &g_ri.Body[k];
    k -= 4;
    if (k < 6)
        return &g_ri.Tires[k / 2][k % 2];
    k -= 6;
    if (k < 2)
        return &g_ri.TireBlur[k];
    k -= 2;
    if (k < 2)
        return &g_ri.Brakes[k];
    k -= 2;
    if (k < 2)
        return &g_ri.Wipers[k];
    k -= 2;
    if (k < 2)
        return &g_ri.SideMirrors[k];
    k -= 2;
    if (k < 2)
        return &g_ri.LicensePlates[k];
    return &g_ri.Scuffs;
}

static const char *model_name(int k, char *b)
{
    if (k < 4)
        sprintf(b, "Body%d", k);
    else if (k < 10)
        sprintf(b, "Tire%d%d", (k - 4) / 2, (k - 4) % 2);
    else if (k < 12)
        sprintf(b, "TireBlur%d", k - 10);
    else if (k < 14)
        sprintf(b, "Brake%d", k - 12);
    else if (k < 16)
        sprintf(b, "Wiper%d", k - 14);
    else if (k < 18)
        sprintf(b, "Mirror%d", k - 16);
    else if (k < 20)
        sprintf(b, "Plate%d", k - 18);
    else
        sprintf(b, "Scuffs");
    return b;
}

static void register_all(void)
{
    char b[24], s[24];
    int k;

    g_nnames = 0;
    reg(&g_car, "car");
    reg(&g_car.TheTopologyCoordinate, "topo");
    reg(&g_dmg, "dmg");
    reg(&g_dmg.TheBodyDamage, "bd");
    reg(g_anim, "drv");
    reg(&g_view, "view");
    reg(&g_cam, "cam");
    reg(&g_wvm, "wvm");
    reg(&g_wscm, "wscm");
    reg(&hack_man_matrix, "hack");
    reg(&g_pos, "pos");
    reg(&g_body, "body");
    for (k = 0; k < 4; k++) {
        sprintf(b, "tm%d", k);
        reg(&g_tm[k], b);
        sprintf(b, "bm%d", k);
        reg(&g_bm[k], b);
    }
    reg(g_skinlm, "skinlm");
    reg(g_shadow, "shadow");
    reg(g_ramp, "ramp");
    reg(&g_ri, "ri");
    reg(&g_ri.AABBMin, "aabbmin");
    reg(&g_ri.AABBMax, "aabbmax");
    for (k = 0; k < NMODELS; k++)
        reg(model_n(k), model_name(k, b));
    for (k = 0; k < NMODELS; k++) {
        sprintf(s, "s%s", model_name(k, b));
        reg(&g_solids[k], s);
    }
    for (k = 0; k < 64; k++) {
        sprintf(b, "lf%d", k);
        reg(&g_lfs[k], b);
    }
    reg(&g_cti, "cti");
    reg(&g_cti.DriverRenderingOffset, "drvoff");
    for (k = 0; k < 4; k++) {
        sprintf(b, "wheel%d", k);
        reg(&g_cti.Wheels[k], b);
    }
    reg(&hull_Origin, "hO");
    reg(&hull_Normal, "hN");
    reg(&cs_lightV, "cs");
}

// ------------------------------------------------------- the stand-ins

int32_t eview_get_pixel_size_sphere(eView *view, const bVector3 *p, float r)
{
    printf("  px %s %s %08x -> %d\n", label(view), label(p), bits(r), g_px);
    return g_px;
}

int32_t eGetCurrentViewMode(void)
{
    printf("  vm -> %d\n", g_vm);
    return g_vm;
}

int32_t scenery_classify_aabb(const bVector4 *min, const bVector4 *max,
                              const bMatrix4 *m)
{
    printf("  cls %s %s ", label(min), label(max));
    words(m, 16);
    printf(" -> %d\n", g_cls);
    return g_cls;
}

void eview_bias_matrix_for_z_sorting(eView *view, bMatrix4 *m, float scale)
{
    printf("  bias %s %s ", label(view), label(m));
    words(m, 16);
    printf(" %08x\n", bits(scale));
    m->v3.z = m->v3.z + 0.125f;
    m->v3.w = m->v3.w + scale;
}

void esolid_replace_light_material(eSolid *s, uint32_t old_hash,
                                   void *material)
{
    printf("  rlm %s %08x %s\n", label(s), old_hash, label(material));
}

void emodel_reconnect_texture_table(eModel *m)
{
    printf("  rtt %s\n", label(m));
}

// The frame profiler's (frameprof.c, bticker.c): the draw counts its cars
// and times its parts, which nothing here reads.
FrameProfTicks FrameProfDraw;

uint32_t bGetTicker(void)
{
    return 0;
}

SkinInfo *cartypeinfo_get_skin_info(int32_t car_type, int32_t skin_number,
                                    int use_default)
{
    printf("  skin %d %d %d\n", car_type, skin_number, use_default);
    return NULL;
}

float bodydamage_get_visible_total_damage(const BodyDamage *b)
{
    printf("  vdmg %s -> %08x\n", label(b), bits(g_vd));
    return g_vd;
}

float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    float el = g_ebase + (pt->x * g_eax + pt->y * g_eay);
    int32_t k = g_nel++;
    int32_t f = (g_emod && k % g_emod == g_eoff) ? 0 : 1;

    printf("  el %s %s ", label(tc), label(pt));
    words(pt, 3);
    printf(" %s %s %s -> %08x %d\n", label(terrain), label(normal),
           label(found), bits(el), f);
    if (normal != NULL)
        memcpy(normal, g_enrm, 16);
    if (found != NULL)
        *found = f;
    return el;
}

static void light_words(const eLightContext *lc)
{
    if (lc == NULL) {
        printf("null");
        return;
    }
    printf("%s %08x %08x %08x", label(lc), word_at(lc, 0), word_at(lc, 60),
           word_at(lc, 212));
}

static void st_model_render(eModel *m, bMatrix4 *matrix, void *light,
                            uint32_t flags)
{
    printf("  mr %s %04x %s ", label(m),
           (unsigned)(uint16_t)m->RigidAnimationStartTime, label(matrix));
    words(matrix, 16);
    printf(" | ");
    light_words(light);
    printf(" | %x\n", flags);
}

static void st_elsetup(eLightContext *lc, const bMatrix4 *lw,
                       const bMatrix4 *hack, const bVector4 *eye, eView *view)
{
    int32_t k;

    printf("  lc %s %s ", label(lc), label(lw));
    words(lw, 16);
    printf(" %s | ", label(hack));
    words(eye, 4);
    printf(" %s q %d\n", label(view), (int)QueryLightMat);
    k = g_nlc++;
    put_word(lc, 0, (uint32_t)k);
    put_word(lc, 60, 0x100u * (uint32_t)k + 0x55u);
    put_word(lc, 212, g_sunl[k % g_nsunl]);
}

static void st_flare(eView *view, eLightFlare *flare, bMatrix4 *lw, float f)
{
    printf("  flare %s %s %s %08x\n", label(view), label(flare), label(lw),
           bits(f));
}

static void st_drv_render(AnimatedDriver *d, bMatrix4 *m, eLightContext *lc,
                          uint32_t flags, int32_t lod)
{
    printf("  dr %s %s ", label(d), label(m));
    words(m, 16);
    printf(" %s %x %d\n", label(lc), flags, lod);
}

static int32_t st_drv_queued(AnimatedDriver *d)
{
    printf("  dq %s -> %d\n", label(d), g_queued);
    return g_queued;
}

static int32_t strip_begin(const char *name, uint32_t mask, int32_t *count,
                           void *tex, int32_t n, bMatrix4 *m)
{
    int32_t k = (*count)++;
    int32_t r = (int32_t)((mask >> (k % 32)) & 1);

    printf("  %s %s %d %s ", name, label(tex), n, label(m));
    words(m, 16);
    printf(" -> %d\n", r);
    return r;
}

static int32_t eb(void *t, int32_t n, bMatrix4 *m)
{
    return strip_begin("eb", g_emask, &g_neb, t, n, m);
}

static int32_t xb(void *t, int32_t n, bMatrix4 *m)
{
    return strip_begin("xb", g_exmask, &g_nxb, t, n, m);
}

static void ev(const bVector3 *v)  { printf("  ev "); words(v, 3); printf("\n"); }
static void xv(const bVector3 *v)  { printf("  xv "); words(v, 3); printf("\n"); }
static void ec(uint32_t c)         { printf("  ec %08x\n", c); }
static void xc(uint32_t c)         { printf("  xc %08x\n", c); }
static void euv(float u, float v)  { printf("  euv %08x %08x\n", bits(u), bits(v)); }
static void xuv(float u, float v)  { printf("  xuv %08x %08x\n", bits(u), bits(v)); }
static void ee(void)               { printf("  ee\n"); }
static void xe(void)               { printf("  xe\n"); }

// ------------------------------------------------------------- parsing

static char *tok(void)
{
    char *t = strtok(NULL, " \t\r\n");

    if (t == NULL) {
        fprintf(stderr, "short line\n");
        exit(2);
    }
    return t;
}

static uint32_t hexu(const char *t)
{
    return (uint32_t)strtoul(t, NULL, 16);
}

static uint32_t u(void)
{
    return hexu(tok());
}

static float f(void)
{
    return flt(u());
}

static void floats(void *p, int n)
{
    int i;

    for (i = 0; i < n; i++)
        put_word(p, 4 * (size_t)i, u());
}

static void reset(void)
{
    int k;

    memset(&g_track, PATTERN, sizeof g_track);
    memset(&g_sun, PATTERN, sizeof g_sun);
    memset(&g_ri, PATTERN, sizeof g_ri);
    memset(&g_car, PATTERN, sizeof g_car);
    memset(&g_dmg, PATTERN, sizeof g_dmg);
    memset(&g_ride, PATTERN, sizeof g_ride);
    memset(&g_drvinfo, PATTERN, sizeof g_drvinfo);
    memset(&g_cardrv, PATTERN, sizeof g_cardrv);
    memset(&g_colbody, PATTERN, sizeof g_colbody);
    memset(&g_poly, PATTERN, sizeof g_poly);
    memset(g_verts, PATTERN, sizeof g_verts);
    memset(g_anim, PATTERN, sizeof g_anim);
    memset(&g_cti, PATTERN, sizeof g_cti);
    memset(&g_view, PATTERN, sizeof g_view);
    memset(&g_cam, PATTERN, sizeof g_cam);
    memset(g_frame, PATTERN, sizeof g_frame);
    for (k = 0; k < NMODELS; k++)
        memset(&g_solids[k], PATTERN, sizeof g_solids[k]);
    memset(g_lfs, PATTERN, sizeof g_lfs);
    g_nlc = g_nel = g_neb = g_nxb = 0;
    QueryLightMat = 0;
    FrameMallocFailed = 0;
    FrameMallocFailAmount = 0;
    register_all();
}

static void line_g(void)
{
    uint32_t w;

    g_flow.current = (int)u();
    gTrackFlowGameFlow = &g_flow;
    WorldTimeFrames = (int32_t)u();
    EnableEnvMap = (int32_t)u();
    PrintQueryLightMat = (int32_t)u();
    CarPartCullerNormalise = (int32_t)u();
    ForceHeadlights = (int32_t)u();
    ForceBrakelights = (int32_t)u();
    ForceReverselights = (int32_t)u();
    ForceCoplights = (int32_t)u();
    ForceRenderDriver = (int32_t)u();
    ForceCarLOD = (int32_t)u();
    ForceTireLOD = (int32_t)u();
    w = u();
    CarShadowElevationFE = flt(w);
    w = u();
    FancyCarShadowEdgeMult = flt(w);
}

static void line_k(void)
{
    int has_cd, has_dmg, has_anim;

    if (!u()) {
        g_ri.pCar = NULL;
        return;
    }
    g_ri.pCar = &g_car;
    g_car.MyDriver = &g_drvinfo;
    g_drvinfo.TheDriverType = (DriverType)u();
    has_cd = (int)u();
    g_cardrv.Steering = (uint16_t)u();
    g_cardrv.Brake = f();
    g_car.pCarDriver = has_cd ? &g_cardrv : NULL;
    g_car.pDynamicCollisionBody = u() ? &g_colbody : NULL;
    has_dmg = (int)u();
    g_dmg.BreakableCarItemDamageAmounts = u();
    g_car.pCarDamage = has_dmg ? &g_dmg : NULL;
    has_anim = (int)u();
    g_anim[25] = u();
    g_car.pAnimatedDriver = has_anim ? (AnimatedDriver *)(void *)g_anim : NULL;
    g_car.DriverRenderingEnabled = (int32_t)u();
    g_car.CopLights = (int8_t)u();
    g_car.HeadlightsState = (int32_t)u();
    g_car.WiperOnTime = u();
    g_car.WiperOffTime = u();
    g_car.WiperState = (int32_t)u();
    g_car.State.CurrentGear = (int32_t)u();
    g_car.State.nWheelsTouchingGround = (int32_t)u();
    floats(g_car.State.WheelAngularVelocity, 4);
    floats(&g_car.State.Position, 4);
}

static void line_o(void)
{
    uint32_t solids, wanim;
    int k;

    floats(&g_ri.AABBMin, 4);
    floats(&g_ri.AABBMax, 4);
    solids = u();
    wanim = u();
    floats(&g_solids[14].PivotMatrix, 16);
    floats(&g_solids[15].PivotMatrix, 16);
    for (k = 0; k < NMODELS; k++) {
        eSolid *s = &g_solids[k];
        eModel *m = model_n(k);

        s->AABBMin.x = -1.0f; s->AABBMin.y = -0.5f;
        s->AABBMin.z = -0.25f; s->AABBMin.w = 0.0f;
        s->AABBMax.x = 1.0f; s->AABBMax.y = 0.5f;
        s->AABBMax.z = 0.25f; s->AABBMax.w = 0.0f;
        s->pRigidAnimation = NULL;
        m->Solid = (solids >> k & 1) ? s : NULL;
    }
    for (k = 0; k < 2; k++)
        g_solids[14 + k].pRigidAnimation =
            (wanim >> k & 1) ? g_rigid[k] : NULL;
    g_ri.Wipers[0].RigidAnimationStartTime = (int16_t)u();
    g_ri.Wipers[1].RigidAnimationStartTime = (int16_t)u();
    g_ri.ShadowTexture = u() ? g_shadow : NULL;
    g_ri.ShadowRampTexture = u() ? g_ramp : NULL;
    g_ri.pCarSkinLightMaterial = u() ? g_skinlm : NULL;
    g_ri.CarTimebaseStart = u();
    g_ri.BrokenLightFlags = u();
    for (k = 0; k < 3; k++)
        g_ri.UsedTextureInfos.ReplaceHeadlightHash[k] = u();
    for (k = 0; k < 3; k++)
        g_ri.UsedTextureInfos.ReplaceBrakelightHash[k] = u();
    for (k = 0; k < 4; k++)
        g_ri.DamageableSkinReplacementTextureTable[8 + k].NewNameHash = u();
}

static void line_l(void)
{
    int n = (int)strtol(tok(), NULL, 10), k;
    bNode *prev = &g_ri.LightFlareList;

    for (k = 0; k < n; k++) {
        g_lfs[k].NameHash = u();
        prev->next = &g_lfs[k].Node;
        g_lfs[k].Node.prev = prev;
        prev = &g_lfs[k].Node;
    }
    prev->next = &g_ri.LightFlareList;
    g_ri.LightFlareList.prev = prev;
}

// ------------------------------------------------------------- the dump

static void dump(void)
{
    int i;

    printf("  end %s fail %d %x qlm %d edge %08x oz %08x\n",
           label(CurrentBufferPos), FrameMallocFailed, FrameMallocFailAmount,
           QueryLightMat, bits(FancyCarShadowEdgeMult), bits(cs_OneOverZ));
    printf("  cs ");
    words(&cs_lightV, 3);
    printf(" hO ");
    words(&hull_Origin, 4);
    printf(" hN ");
    words(&hull_Normal, 4);
    printf("\n  cull");
    for (i = 0; i < NUM_CULLABLE_CAR_PARTS; i++) {
        printf(" ");
        words(g_ri.PartCuller[i].State, 4);
    }
    printf("\n  dmg");
    for (i = 0; i < 4; i++)
        printf(" %08x", g_ri.DamageableSkinReplacementTextureTable[8 + i]
                            .NewNameHash);
    printf("\n  wst %04x %04x\n",
           (unsigned)(uint16_t)g_ri.Wipers[0].RigidAnimationStartTime,
           (unsigned)(uint16_t)g_ri.Wipers[1].RigidAnimationStartTime);
    printf("  h1");
    for (i = 0; i < 12; i++) {
        printf(" ");
        words(&hullVertArray1[i], 2);
    }
    printf("\n  h2");
    for (i = 0; i < 12; i++) {
        printf(" ");
        words(&hullVertArray2[i], 3);
    }
    printf("\n  h3");
    for (i = 0; i < 24; i++) {
        printf(" ");
        words(&hullVertArray3[i], 4);
    }
    printf("\n  hp");
    for (i = 0; i < 13; i++)
        printf(" %s", label(hullVertPointers[i]));
    printf("\n");
}

static void bytes_hex(const uint8_t *b, int n)
{
    int i;

    printf(" ");
    for (i = 0; i < n; i++)
        printf("%02x", b[i]);
}

// The starting values of what the scenarios set, before any is.
static void initial(void)
{
    int32_t w[10] = { EnableEnvMap, PrintQueryLightMat, CarPartCullerNormalise,
                      ForceHeadlights, ForceBrakelights, ForceReverselights,
                      ForceCoplights, ForceRenderDriver, ForceCarLOD,
                      ForceTireLOD };
    int i;

    printf("I");
    for (i = 0; i < 10; i++)
        printf(" %08x", (uint32_t)w[i]);
    printf(" %08x %08x", bits(FancyCarShadowEdgeMult),
           bits(CarShadowElevationFE));
    bytes_hex(CopLightsHeadlights, 16);
    bytes_hex(CopLightsRed, 8);
    bytes_hex(CopLightsBlue, 8);
    bytes_hex(CopLightsWhite, 8);
    bytes_hex(CopLightsRedSlow, 16);
    bytes_hex(CopLightsBlueSlow, 16);
    bytes_hex(CopLightsWhiteSlow, 16);
    printf(" ");
    words(CarLodPixelSizes, 4);
    printf("\n");
}

int main(int argc, char **argv)
{
    static char line[16384];
    FILE *fp;
    int n = 0;

    if (argc != 2) {
        fprintf(stderr, "usage: carrender_test scenarios.txt\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    eMathInit();
    gEModelRenderFn = st_model_render;
    gElSetupLightContextFn = st_elsetup;
    gERenderLightFlareFn = st_flare;
    gAnimatedDriverRenderFn = st_drv_render;
    gAnimatedDriverQueuedFn = st_drv_queued;
    gEStripFns.Begin = eb;
    gEStripFns.AddVertex = ev;
    gEStripFns.AddColour = ec;
    gEStripFns.AddUV = euv;
    gEStripFns.End = ee;
    gExStripFns.Begin = xb;
    gExStripFns.AddVertex = xv;
    gExStripFns.AddColour = xc;
    gExStripFns.AddUV = xuv;
    gExStripFns.End = xe;

    initial();
    while (fgets(line, sizeof line, fp) != NULL) {
        char *t = strtok(line, " \t\r\n");

        if (t == NULL)
            continue;
        switch (t[0]) {
        case 'S':
            reset();
            break;
        case 'g':
            line_g();
            break;
        case 't':
            if (u()) {
                CurrentTrackInfo = &g_track;
                g_track.TimeOfDay = (int16_t)u();
            } else {
                CurrentTrackInfo = NULL;
            }
            break;
        case 'u':
            if (u()) {
                SunInfo = &g_sun;
                g_sun.CarShadowPositionX = f();
                g_sun.CarShadowPositionY = f();
                g_sun.CarShadowPositionZ = f();
            } else {
                SunInfo = NULL;
            }
            break;
        case 'f': {
            uint32_t used = u(), size = u();

            CurrentBufferPos = g_frame + used;
            CurrentBufferEnd = g_frame + size;
            break;
        }
        case 'm':
            floats(&CarRenderMatrix, 16);
            break;
        case 'c': {
            int i = (int)strtol(tok(), NULL, 10);
            CarPartCullInfo *c = &CarPartCullInfoTable[i];

            c->Flag8 = (int32_t)u();
            c->NumPlanes = (int32_t)u();
            floats(c->Planes, 12);
            floats(&c->Extra, 4);
            break;
        }
        case 'a': {
            int k;

            floats(&g_pos, 4);
            floats(&g_body, 16);
            for (k = 0; k < 4; k++)
                floats(&g_tm[k], 16);
            for (k = 0; k < 4; k++)
                floats(&g_bm[k], 16);
            g_extra = u();
            g_forced = u();
            break;
        }
        case 'v':
            g_view.ID = (int32_t)u();
            g_view.pCamera = &g_cam;
            g_view.WorldViewMatrix = &g_wvm;
            g_view.WorldScreenClipMatrix = &g_wscm;
            floats(&g_cam.CurrentKey.Position, 4);
            floats(&g_wvm, 16);
            floats(&g_wscm, 16);
            break;
        case 'r': {
            int k;

            g_px = (int32_t)u();
            g_vm = (int32_t)u();
            g_cls = (int32_t)u();
            g_vd = f();
            g_queued = (int32_t)u();
            g_emask = u();
            g_exmask = u();
            g_nsunl = (int32_t)strtol(tok(), NULL, 10);
            for (k = 0; k < g_nsunl; k++)
                g_sunl[k] = u();
            break;
        }
        case 'e':
            g_ebase = f();
            g_eax = f();
            g_eay = f();
            g_emod = (int32_t)u();
            g_eoff = (int32_t)u();
            floats(g_enrm, 4);
            break;
        case 'k':
            line_k();
            break;
        case 'x': {
            int k, nv = (int)strtol(tok(), NULL, 10);

            g_colbody.Dynamic.Body.pPoly = &g_poly;
            g_poly.NumVertices = (int16_t)nv;
            g_poly.pVertices = g_verts;
            for (k = 0; k < nv; k++)
                floats(g_verts[k].CompressedPosition, 3);
            break;
        }
        case 'i': {
            int k;

            g_cti.OpenTop = (int8_t)u();
            g_cti.Type = (int32_t)u();
            floats(&g_cti.DriverRenderingOffset, 4);
            for (k = 0; k < 4; k++)
                floats(&g_cti.Wheels[k], 4);
            break;
        }
        case 'd':
            g_ride.Type = (int32_t)u();
            g_ride.SkinNumber = (int8_t)u();
            break;
        case 'o':
            g_ri.pRideInfo = &g_ride;
            g_ri.pCarTypeInfo = &g_cti;
            line_o();
            break;
        case 'p': {
            int i = (int)strtol(tok(), NULL, 10), k;

            floats(&g_ri.PartCuller[i].Point, 4);
            for (k = 0; k < 4; k++)
                g_ri.PartCuller[i].State[k] = u();
            break;
        }
        case 'l':
            line_l();
            break;
        case 'G':
            printf("R %d\n", n++);
            carrenderinfo_render(&g_ri, &g_view, &g_pos, &g_body, g_tm, g_bm,
                                 g_extra, g_forced);
            dump();
            break;
        default:
            fprintf(stderr, "bad line %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
