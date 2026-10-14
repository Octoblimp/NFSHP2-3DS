// Harness for tools/carrenderinfo_check.py: runs the checker's scenarios on
// carrenderinfo.c and prints what the model prints for the retail image.
// emodel.c, epositionmarker.c, cartypeinfo.c, bmath.c and bvector.c are
// the real ones; every other callee is a stub here, and each logs its name
// and its arguments. After each build and each act the render info is
// printed field by field in retail's order, then the solids' tables, the
// textures' rendering orders, the model list and the seed. See the
// checker's docstring.
//
//     carrenderinfo_test scenarios.txt > out.txt

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "cardamage.h"
#include "carrenderinfo.h"
#include "cartypeinfo.h"
#include "emodel.h"
#include "epositionmarker.h"
#include "esolid.h"
#include "eview.h"
#include "gameflow.h"
#include "texturepack.h"
#include "trackflow.h"

#define PATTERN 0xa5
#define NCTI    4
#define NSOLID  64
#define NTEX    64
#define NMARK   64
#define NEM     64
#define NEP     256
#define NLF     256
#define NLM     256
#define NSKIN   16
#define NTAB    32

// ------------------------------------------------------ what it links to

bNode       SolidList = { &SolidList, &SolidList };
bNode       ModelList = { &ModelList, &ModelList };
BSlotPool  *eModelSlotPool;
BGameFlow  *gTrackFlowGameFlow;
void      (*gEWaitUntilRenderingDoneFn)(void);
void      (*gFixStripSTsFn)(eSolid *solid);

// ------------------------------------------------------------ the world

static Car          g_car;
static CarDamage    g_dmg;
static RideInfo     g_ride, g_ride2;
static CarTypeInfo  g_ctis[NCTI];
static SkinInfo     g_skins[NSKIN];
static eSolid       g_solids[NSOLID];
static eTextureTable        g_soltex[NSOLID][NTAB];
static eLightMaterialEntry  g_sollm[NSOLID][NTAB];
static uint8_t      g_anim[NSOLID][16];
static TextureInfo  g_tex[NTEX], g_tdef;
static ePositionMarker g_marks[NMARK];
static _Alignas(16) CarRenderInfo g_ri;
static _Alignas(16) unsigned char g_alpha[16];
static _Alignas(16) unsigned char g_eppool[64], g_lfpool[64];
static CarEmitterPosition g_ep[NEP];
static eLightFlare  g_lf[NLF];
static struct { bNode node; unsigned char rest[16]; } g_em[NEM];
static _Alignas(16) unsigned char g_lm[NLM][16];
static BGameFlow    g_flow;

static int      g_nep, g_nlf, g_nem, g_nlm;
static uint32_t g_lmhash[NLM];
static uint32_t g_afx;

// The scenario's world as read, to dump the solids and textures after.
static int      g_nsolid, g_ntex, g_nmark, g_nskin;
static int      g_solid_ntex[NSOLID], g_solid_nlm[NSOLID];
static uint32_t g_texhash[NTEX];

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, sizeof u);
    return u;
}

static float flt(uint32_t u)
{
    float f;

    memcpy(&f, &u, sizeof f);
    return f;
}

static int all_pattern(const void *p, size_t n)
{
    const unsigned char *b = p;
    size_t i;

    for (i = 0; i < n; i++)
        if (b[i] != PATTERN)
            return 0;
    return 1;
}

// The model's labels, from its register(), by address.
static const char *const kModelNames[] = {
    "Body0", "Body1", "Body2", "Body3",
    "Tire00", "Tire01", "Tire10", "Tire11", "Tire20", "Tire21",
    "TireBlur0", "TireBlur1", "Brake0", "Brake1", "Wiper0", "Wiper1",
    "Mirror0", "Mirror1", "Plate0", "Plate1",
    "Scuffs", "Dashboard", "DashWindow", "DashWheel", "Speedo", "Tacho",
};

static eModel *model_at(CarRenderInfo *ri, int k)
{
    if (k < 4)  return &ri->Body[k];
    if (k < 10) return &ri->Tires[(k - 4) / 2][(k - 4) % 2];
    if (k < 12) return &ri->TireBlur[k - 10];
    if (k < 14) return &ri->Brakes[k - 12];
    if (k < 16) return &ri->Wipers[k - 14];
    if (k < 18) return &ri->SideMirrors[k - 16];
    if (k < 20) return &ri->LicensePlates[k - 18];
    switch (k) {
    case 20: return &ri->Scuffs;
    case 21: return &ri->Dashboard;
    case 22: return &ri->DashboardWindow;
    case 23: return &ri->DashboardWheel;
    case 24: return &ri->SpeedometerNeedle;
    default: return &ri->TachometerNeedle;
    }
}

#define NMODELS ((int)(sizeof kModelNames / sizeof kModelNames[0]))

static const char *lab(const void *p)
{
    static char buf[16][40];
    static int k;
    char *b = buf[k++ & 15];
    CarRenderInfo *ri = &g_ri;
    int i;

    if (p == NULL)
        return "null";
    if (all_pattern(&p, sizeof p))
        return "a5";
    if (p == (void *)&g_car)                return "car";
    if (p == (void *)&g_dmg)                return "dmg";
    if (p == (void *)&g_dmg.TheBodyDamage)  return "bd";
    if (p == (void *)&g_ride)               return "ride";
    if (p == (void *)&g_ride2)              return "ride2";
    if (p == (void *)ri)                    return "ri";
    if (p == (void *)g_alpha)               return "alpha";
    if (p == (void *)g_eppool)              return "EPPool";
    if (p == (void *)g_lfpool)              return "LFPool";
    if (p == (void *)&g_tdef)               return "tdef";
    if (p == (void *)&ModelList)            return "ModelList";
    if (p == (void *)&SolidList)            return "SolidList";
    if (p == (void *)&PositionMarkerList)   return "MarkerList";
    for (i = 0; i < NCTI; i++)
        if (p == (void *)&g_ctis[i]) {
            sprintf(b, "cti%d", i);
            return b;
        }
    for (i = 0; i < NMODELS; i++)
        if (p == (void *)model_at(ri, i))
            return kModelNames[i];
    if (p == (void *)&ri->LightFlareList)
        return "LFL";
    for (i = 0; i < CARRENDERINFO_NUM_EMITTERS; i++)
        if (p == (void *)&ri->EmitterList[i]) {
            sprintf(b, "EL%d", i);
            return b;
        }
    for (i = 0; i < CARRENDERINFO_NUM_EMITTER_POSITIONS; i++)
        if (p == (void *)&ri->EmitterPositionList[i]) {
            sprintf(b, "EPL%d", i);
            return b;
        }
    if (p == (void *)ri->SkinReplacementTextureTable)            return "Skin";
    if (p == (void *)ri->DamageableSkinReplacementTextureTable)  return "Dmg";
    if (p == (void *)ri->DashReplacementTextureTable)            return "Dash";
    if (p == (void *)ri->TireReplacementTextureTable)            return "Tire";
    if (p == (void *)ri->TireBlurReplacementTextureTable)        return "TireBlur";
    for (i = 0; i < NSOLID; i++)
        if (p == (void *)&g_solids[i]) {
            sprintf(b, "s%d", i);
            return b;
        }
    for (i = 0; i < NTEX; i++)
        if (p == (void *)&g_tex[i]) {
            sprintf(b, "t%d", i);
            return b;
        }
    for (i = 0; i < NMARK; i++)
        if (p == (void *)&g_marks[i]) {
            sprintf(b, "mk%d", i);
            return b;
        }
    for (i = 0; i < NEM; i++)
        if (p == (void *)&g_em[i]) {
            sprintf(b, "em%d", i);
            return b;
        }
    for (i = 0; i < NEP; i++)
        if (p == (void *)&g_ep[i]) {
            sprintf(b, "ep%d", i);
            return b;
        }
    for (i = 0; i < NLF; i++)
        if (p == (void *)&g_lf[i]) {
            sprintf(b, "lf%d", i);
            return b;
        }
    for (i = 0; i < NLM; i++)
        if (p == (void *)g_lm[i]) {
            sprintf(b, "lm%d", i);
            return b;
        }
    sprintf(b, "?%p", p);
    return b;
}

// ------------------------------------------------------------ the stubs

void *bMalloc(int size, const char *name, int flags, int pool)
{
    char n[16];

    if ((size_t)size == sizeof(CarRenderInfo))
        strcpy(n, "sizeof");
    else
        sprintf(n, "%d", size);
    printf("  bMalloc %s %s %d %d -> ri\n", n, name, flags, pool);
    memset(&g_ri, PATTERN, sizeof g_ri);
    return &g_ri;
}

void bFree(void *p)
{
    printf("  bFree %s\n", lab(p));
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *name,
                        int flags)
{
    fprintf(stderr, "bNewSlotPool %d %d %s %d\n", slotSize, numSlots, name,
            flags);
    abort();
}

void *bSlotOMalloc(BSlotPool *pool)
{
    void *a;

    if (pool == (BSlotPool *)(void *)g_eppool) {
        if (g_nep >= NEP) abort();
        a = &g_ep[g_nep++];
        memset(a, PATTERN, sizeof g_ep[0]);
    } else if (pool == (BSlotPool *)(void *)g_lfpool) {
        if (g_nlf >= NLF) abort();
        a = &g_lf[g_nlf++];
        memset(a, PATTERN, sizeof g_lf[0]);
    } else {
        fprintf(stderr, "bSlotOMalloc from %p\n", (void *)pool);
        exit(3);
    }
    printf("  bSlotOMalloc %s -> %s\n", lab(pool), lab(a));
    return a;
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    printf("  bSlotFree %s %s\n", lab(pool), lab(slot));
}

void *get_texture_info(uint32_t name_hash, int use_default,
                       int include_unloaded)
{
    void *r = NULL;
    int k;

    for (k = 0; k < g_ntex; k++)
        if (g_texhash[k] == name_hash) {
            r = &g_tex[k];
            break;
        }
    if (r == NULL && use_default)
        r = &g_tdef;
    printf("  GetTextureInfo %08x %d %d -> %s\n", name_hash, use_default,
           include_unloaded, lab(r));
    return r;
}

void *get_light_material(uint32_t name_hash)
{
    void *r = NULL;
    int k;

    if (name_hash != 0) {
        for (k = 0; k < g_nlm; k++)
            if (g_lmhash[k] == name_hash)
                break;
        if (k == g_nlm) {
            if (g_nlm >= NLM) abort();
            g_lmhash[g_nlm++] = name_hash;
        }
        r = g_lm[k];
    }
    printf("  elGetLightMaterial %08x -> %s\n", name_hash, lab(r));
    return r;
}

static void fix_strip(eSolid *s)
{
    printf("  FixStripSTs %s\n", lab(s));
}

// esolid.c's, which emodel.c's environment mapping calls; CarDamage calls
// that, and nothing here does.
void esolid_set_environment_mapping(eSolid *s, uint32_t hash, int32_t on)
{
    (void)s;
    (void)hash;
    (void)on;
    fprintf(stderr, "esolid_set_environment_mapping reached\n");
    exit(3);
}

static void assign_drv(Car *c, const char *name)
{
    printf("  AssignAnimatedDriver %s %s\n", lab(c), name);
}

static void unassign_drv(Car *c)
{
    printf("  UnAssignAnimatedDriver %s\n", lab(c));
}

static void set_alevel(BodyDamage *bd, const char *name)
{
    printf("  SetALevelBodyDamageInfo %s %s\n", lab(bd), name);
}

static void add_model(BodyDamage *bd, eModel *m, const char *name,
                      int32_t flag)
{
    printf("  AddModel %s %s %s %d\n", lab(bd), lab(m), name, flag);
}

static void afx_get(bNode *list, uint32_t hash)
{
    long k = (long)(list - g_ri.EmitterList);

    printf("  afxGetEmitters %s %08x\n", lab(list), hash);
    if (k >= 0 && k < CARRENDERINFO_NUM_EMITTERS && (g_afx >> k & 1)) {
        bNode *n, *tail;

        if (g_nem >= NEM) abort();
        n = &g_em[g_nem++].node;
        memset(n, PATTERN, sizeof g_em[0]);
        tail = list->prev;
        n->next = list;
        n->prev = tail;
        tail->next = n;
        list->prev = n;
    }
}

static void acid_del(bNode *e, int32_t flags)
{
    printf("  ~AcidEmitter %s %d\n", lab(e), flags);
}

static void wait_render(void)
{
    printf("  eWaitUntilRenderingDone\n");
}

// ---------------------------------------------------------- the reading

static uint32_t hexu(const char *s)
{
    if (s == NULL) {
        fprintf(stderr, "short line\n");
        exit(2);
    }
    return (uint32_t)strtoul(s, NULL, 16);
}

static int deci(const char *s)
{
    if (s == NULL) {
        fprintf(stderr, "short line\n");
        exit(2);
    }
    return (int)strtol(s, NULL, 10);
}

static const char *tok(void)
{
    return strtok(NULL, " \t\r\n");
}

static void link_list(bNode *sentinel, bNode **nodes, int n)
{
    bNode *prev = sentinel;
    int i;

    for (i = 0; i < n; i++) {
        prev->next = nodes[i];
        nodes[i]->prev = prev;
        prev = nodes[i];
    }
    prev->next = sentinel;
    sentinel->prev = prev;
}

// ------------------------------------------------------------ the dumps

static void dump_table(void)
{
    int i, j;

    for (i = 0; i < NUM_CULLABLE_CAR_PARTS; i++) {
        const CarPartCullInfo *c = &CarPartCullInfoTable[i];
        const float *f = &c->Planes[0].x;

        printf("  cull%d %08x %s %08x %08x", i, (uint32_t)c->Id, c->Name,
               (uint32_t)c->Flag8, (uint32_t)c->NumPlanes);
        for (j = 0; j < 12; j++)
            printf(" %08x", bits(f[j]));
        printf(" %08x %08x %08x %08x\n", bits(c->Extra.x), bits(c->Extra.y),
               bits(c->Extra.z), bits(c->Extra.w));
    }
}

static void hexbytes(const void *p, size_t n)
{
    const unsigned char *b = p;
    size_t i;

    for (i = 0; i < n; i++)
        printf("%02x", b[i]);
}

static void dump_ri(void)
{
    CarRenderInfo *ri = &g_ri;
    const uint32_t *u;
    bNode *n;
    int i, k, first;

    printf("  ri %s %s %s %08x\n", lab(ri->pCar), lab(ri->pRideInfo),
           lab(ri->pCarTypeInfo), ri->pad12);
    printf("  box %08x %08x %08x * %08x %08x %08x * %08x %08x %08x %08x\n",
           bits(ri->AABBMin.x), bits(ri->AABBMin.y), bits(ri->AABBMin.z),
           bits(ri->AABBMax.x), bits(ri->AABBMax.y), bits(ri->AABBMax.z),
           bits(ri->BodyPivot.x), bits(ri->BodyPivot.y), bits(ri->BodyPivot.z),
           bits(ri->BodyPivot.pad));
    for (i = 0; i < NMODELS; i++) {
        eModel *m = model_at(ri, i);

        printf("  %s %08x %s %s %02x %02x %04x %s %s\n", kModelNames[i],
               m->NameHash, lab(m->Solid), lab(m->pReplacementTextureTable),
               m->NumReplacementTextures, m->ReplacementTextureInstanceIndex,
               (uint16_t)m->RigidAnimationStartTime, lab(m->Node.next),
               lab(m->Node.prev));
    }
    u = (const uint32_t *)(const void *)&ri->UsedTextureInfos;
    printf("  used");
    for (i = 0; i < 43; i++)
        printf(" %08x", u[i]);
    printf("\n");
    printf("  tex %s %s %s %08x %08x\n", lab(ri->ShadowTexture),
           lab(ri->ShadowRampTexture), lab(ri->pCarSkinLightMaterial),
           ri->CarTimebaseStart, ri->BrokenLightFlags);

    printf("  flares %s | ", lab(ri->LightFlareList.prev));
    first = 1;
    k = 0;
    for (n = ri->LightFlareList.next; n != &ri->LightFlareList && k < 300;
         n = n->next, k++) {
        eLightFlare *f = (eLightFlare *)(void *)n;

        printf("%s%s<%s %08x %02x %02x %04x %02x %08x %08x %08x %08x %08x "
               "%08x %08x %08x", first ? "" : " ; ", lab(n), lab(n->prev),
               f->NameHash, (uint8_t)f->Enabled, (uint8_t)f->Type,
               (uint16_t)f->Flags, (uint8_t)f->Name[0], bits(f->PositionX),
               bits(f->PositionY), bits(f->PositionZ), bits(f->pad0),
               bits(f->DirectionX), bits(f->DirectionY), bits(f->DirectionZ),
               bits(f->pad1));
        first = 0;
    }
    printf("\n");

    for (i = 0; i < CARRENDERINFO_NUM_EMITTERS; i++) {
        bNode *l = &ri->EmitterList[i];

        printf("  EL%d %s | ", i, lab(l->prev));
        first = 1;
        k = 0;
        for (n = l->next; n != l && k < 50; n = n->next, k++) {
            printf("%s%s<%s", first ? "" : " ", lab(n), lab(n->prev));
            first = 0;
        }
        printf("\n");
    }
    for (i = 0; i < CARRENDERINFO_NUM_EMITTER_POSITIONS; i++) {
        bSList *l = &ri->EmitterPositionList[i];
        bSNode *s;

        printf("  EPL%d %s | ", i, lab(l->Tail));
        first = 1;
        k = 0;
        for (s = l->Head; s != (bSNode *)(void *)l && k < 50;
             s = s->next, k++) {
            CarEmitterPosition *p = (CarEmitterPosition *)(void *)s;

            printf("%s%s %08x %08x %08x", first ? "" : " ; ", lab(s),
                   bits(p->X), bits(p->Y), bits(p->Z));
            first = 0;
        }
        printf("\n");
    }

    {
        static const struct { const char *name; int count; } kTables[] = {
            { "Skin", 2 }, { "Dmg", 12 }, { "Dash", 1 }, { "Tire", 3 },
            { "TireBlur", 2 },
        };
        eReplacementTextureTable *tabs[5];

        tabs[0] = ri->SkinReplacementTextureTable;
        tabs[1] = ri->DamageableSkinReplacementTextureTable;
        tabs[2] = ri->DashReplacementTextureTable;
        tabs[3] = ri->TireReplacementTextureTable;
        tabs[4] = ri->TireBlurReplacementTextureTable;
        for (k = 0; k < 5; k++)
            for (i = 0; i < kTables[k].count; i++) {
                eReplacementTextureTable *t = &tabs[k][i];

                printf("  %s%d %08x %08x %s ", kTables[k].name, i,
                       t->OldNameHash, t->NewNameHash, lab(t->pTextureInfo));
                hexbytes(t->ReplaceIndex, 16);
                printf("\n");
            }
    }
    printf("  pad1880 ");
    hexbytes(ri->pad1880, 8);
    printf("\n");
    for (i = 0; i < NUM_CULLABLE_CAR_PARTS; i++) {
        const CarPartCullerPart *p = &ri->PartCuller[i];

        printf("  part%d %08x %08x %08x %08x %08x %08x %08x %08x\n", i,
               bits(p->Point.x), bits(p->Point.y), bits(p->Point.z),
               bits(p->Point.w), p->State[0], p->State[1], p->State[2],
               p->State[3]);
    }
    printf("  alpha %s %08x ", lab(ri->pAlphaInfo),
           (uint32_t)ri->AlphaOverridden);
    hexbytes(ri->pad2344, 8);
    printf("\n");
}

static void dump_world(void)
{
    bNode *n;
    int k, j, first;

    for (k = 0; k < g_nsolid; k++) {
        printf("  s%d tex ", k);
        for (j = 0; j < g_solid_ntex[k]; j++)
            printf("%s%08x:%s", j ? " " : "", g_soltex[k][j].NameHash,
                   lab(g_soltex[k][j].pTextureInfo));
        printf(" | lm ");
        for (j = 0; j < g_solid_nlm[k]; j++)
            printf("%s%08x:%s", j ? " " : "", g_sollm[k][j].NameHash,
                   lab(g_sollm[k][j].LightMaterial));
        printf("\n");
    }
    // The model joins the orders and then adds " tdef", so an empty list
    // leaves two spaces.
    printf("  order ");
    for (k = 0; k < g_ntex; k++)
        printf("%s%02x", k ? " " : "", g_tex[k].RenderingOrder);
    printf(" %02x\n", g_tdef.RenderingOrder);
    printf("  models %s | ", lab(ModelList.prev));
    first = 1;
    k = 0;
    for (n = ModelList.next; n != &ModelList && k < 100; n = n->next, k++) {
        printf("%s%s<%s", first ? "" : " ", lab(n), lab(n->prev));
        first = 0;
    }
    printf("\n");
    printf("  car %s test %s seed %08x\n", lab(g_car.pRenderInfo),
           lab(TestRenderInfo), bDefaultSeed);
}

// ------------------------------------------------------------ the runs

typedef struct Build {
    uint32_t mode, seed, flow, dmg, dbits, ride[5], cartype, afx;
    char     act;
    uint32_t args[8];
    int      nargs;
} Build;

static void set_ride(RideInfo *r, const uint32_t *v)
{
    r->Type = (int32_t)v[0];
    r->InstanceIndex = (int8_t)(uint8_t)v[1];
    r->SkinNumber = (int8_t)(uint8_t)v[2];
    r->HasDash = (int8_t)(uint8_t)v[3];
    r->CanBeVertexDamaged = (int8_t)(uint8_t)v[4];
}

static void begin_world(const Build *b)
{
    memset(&g_car, PATTERN, sizeof g_car);
    memset(&g_dmg, PATTERN, sizeof g_dmg);
    memset(&g_ri, PATTERN, sizeof g_ri);
    memset(g_alpha, PATTERN, sizeof g_alpha);
    g_dmg.BreakableCarItemDamageAmounts = b->dbits;
    g_car.pCarDamage = b->dmg ? &g_dmg : NULL;
    set_ride(&g_ride, b->ride);
    g_nep = g_nlf = g_nem = g_nlm = 0;
    g_nsolid = g_ntex = g_nmark = g_nskin = 0;
    g_afx = b->afx;
    ModelList.next = ModelList.prev = &ModelList;
    SolidList.next = SolidList.prev = &SolidList;
    PositionMarkerList.next = PositionMarkerList.prev = &PositionMarkerList;
    g_flow.current = (int)b->flow;
    bDefaultSeed = b->seed;
}

static void read_cti(void)
{
    const char *base = tok(), *name = tok();
    int i = (int)hexu(tok()), k, j;
    CarTypeInfo *c;

    if (i < 0 || i >= NCTI) exit(2);
    c = &g_ctis[i];
    memset(c, PATTERN, sizeof *c);
    strcpy(c->CarTypeName, name);
    strcpy(c->BaseModelName, base);
    c->UsageType = (int32_t)hexu(tok());
    for (k = 0; k < 4; k++) {
        float w[4];

        for (j = 0; j < 4; j++)
            w[j] = flt(hexu(tok()));
        c->Wheels[k].PositionX = w[0];
        c->Wheels[k].PositionY = w[1];
        c->Wheels[k].PositionZ = w[2];
        c->Wheels[k].Radius = w[3];
    }
}

static void read_skins(void)
{
    int n = deci(tok()), k;

    if (n > NSKIN) exit(2);
    memset(g_skins, PATTERN, sizeof g_skins);
    for (k = 0; k < n; k++) {
        g_skins[k].TheCarType = (int32_t)hexu(tok());
        g_skins[k].SkinNumber = (int32_t)hexu(tok());
        g_skins[k].LightMaterialNameHash = bchunk_hash(tok());
    }
    SkinInfoTable = g_skins;
    NumSkinInfo = n;
    g_nskin = n;
}

static bNode *g_solid_nodes[NSOLID], *g_mark_nodes[NMARK];

static void read_solid(void)
{
    const char *name = tok();
    int k = g_nsolid++, j, n;
    eSolid *s;
    uint32_t v[11];

    if (k >= NSOLID) exit(2);
    s = &g_solids[k];
    memset(s, PATTERN, sizeof *s);
    memset(g_soltex[k], PATTERN, sizeof g_soltex[k]);
    memset(g_sollm[k], PATTERN, sizeof g_sollm[k]);
    memset(g_anim[k], PATTERN, sizeof g_anim[k]);
    s->NameHash = bchunk_hash(name);
    for (j = 0; j < 11; j++)
        v[j] = hexu(tok());
    s->Flags = (uint16_t)v[0];
    s->AABBMin.x = flt(v[2]);
    s->AABBMin.y = flt(v[3]);
    s->AABBMin.z = flt(v[4]);
    s->AABBMax.x = flt(v[5]);
    s->AABBMax.y = flt(v[6]);
    s->AABBMax.z = flt(v[7]);
    s->PivotMatrix.v3.x = flt(v[8]);
    s->PivotMatrix.v3.y = flt(v[9]);
    s->PivotMatrix.v3.z = flt(v[10]);
    if (v[1]) {
        g_anim[k][2] = v[1] == 1 ? 0 : 1;
        s->pRigidAnimation = g_anim[k];
    } else {
        s->pRigidAnimation = NULL;
    }
    n = deci(tok());
    if (n > NTAB) exit(2);
    for (j = 0; j < n; j++)
        g_soltex[k][j].NameHash = bchunk_hash(tok());
    s->NumTextureTableEntries = (int16_t)n;
    g_solid_ntex[k] = n;
    n = deci(tok());
    if (n > NTAB) exit(2);
    for (j = 0; j < n; j++)
        g_sollm[k][j].NameHash = bchunk_hash(tok());
    s->NumLightMaterials = (int16_t)n;
    g_solid_nlm[k] = n;
    s->pTextureTable = g_soltex[k];
    s->LightMaterialTable = g_sollm[k];
    g_solid_nodes[k] = &s->Node;
}

static void read_marker(void)
{
    const char *name = tok(), *model = tok();
    int k = g_nmark++, j;
    ePositionMarker *m;

    if (k >= NMARK) exit(2);
    m = &g_marks[k];
    memset(m, PATTERN, sizeof *m);
    m->NameHash = bchunk_hash(name);
    m->TypeHash = bchunk_hash(model);
    for (j = 0; j < 3; j++)
        m->Position[j] = flt(hexu(tok()));
    m->Param = hexu(tok());
    g_mark_nodes[k] = &m->Node;
}

static void read_textures(void)
{
    int n = deci(tok()), k;

    if (n > NTEX) exit(2);
    for (k = 0; k < n; k++) {
        g_texhash[k] = bchunk_hash(tok());
        memset(&g_tex[k], PATTERN, sizeof g_tex[k]);
    }
    memset(&g_tdef, PATTERN, sizeof g_tdef);
    g_ntex = n;
}

static void run_build(int idx, const Build *b)
{
    CarRenderInfo *ret;

    link_list(&SolidList, g_solid_nodes, g_nsolid);
    link_list(&PositionMarkerList, g_mark_nodes, g_nmark);
    g_car.pCarTypeInfo = &g_ctis[b->cartype];

    printf("B %d\n", idx);
    if (b->mode == 0) {
        car_init_render_info(&g_car, &g_ride);
        ret = &g_ri;
    } else {
        ret = carrenderinfo_construct(&g_ri, &g_ride,
                                      b->mode == 1 ? &g_car : NULL);
    }
    printf("  ret %s\n", lab(ret));
    dump_ri();
    dump_world();

    switch (b->act) {
    case 'S':
        set_ride(&g_ride2, b->args);
        printf("S\n");
        carrenderinfo_switch_skin(&g_ri, &g_ride2);
        break;
    case 'C':
        set_ride(&g_ride2, b->args);
        g_car.pRideInfo = &g_ride2;
        g_car.pRenderInfo = &g_ri;
        printf("C\n");
        car_switch_skin(&g_car, b->args[5]);
        break;
    case 'U':
        g_dmg.BreakableCarItemDamageAmounts = b->args[0];
        printf("U\n");
        carrenderinfo_update_car_replacement_textures(&g_ri);
        break;
    case 'L':
        printf("L\n");
        carrenderinfo_create_car_light_flares(&g_ri);
        break;
    case 'D':
        if (b->args[1]) {
            g_ri.pAlphaInfo = g_alpha;
            g_ri.AlphaOverridden = 1;
        }
        printf("D\n");
        carrenderinfo_delete(&g_ri, (int32_t)b->args[0]);
        break;
    default:
        return;
    }
    dump_ri();
    dump_world();
}

static void run_part(int idx)
{
    CarPartCullInfo saved;
    CarPartCullerPart culler[NUM_CULLABLE_CAR_PARTS];
    bVector4 pt;
    int32_t part = (int32_t)hexu(tok());
    float *f;
    int j;

    if (part < 0 || part >= NUM_CULLABLE_CAR_PARTS) exit(2);
    saved = CarPartCullInfoTable[part];
    CarPartCullInfoTable[part].NumPlanes = (int32_t)hexu(tok());
    f = &CarPartCullInfoTable[part].Planes[0].x;
    for (j = 0; j < 12; j++)
        f[j] = flt(hexu(tok()));
    pt.x = flt(hexu(tok()));
    pt.y = flt(hexu(tok()));
    pt.z = flt(hexu(tok()));
    pt.w = flt(hexu(tok()));
    memset(culler, PATTERN, sizeof culler);

    printf("P %d\n", idx);
    carrenderinfo_init_part(culler, part, &pt);
    printf("  planes");
    for (j = 0; j < 12; j++)
        printf(" %08x", bits(f[j]));
    printf("\n  culler ");
    hexbytes(culler, sizeof culler);
    printf("\n");
    CarPartCullInfoTable[part] = saved;
}

int main(int argc, char **argv)
{
    static char line[16384];
    FILE *fh;
    Build b;
    int idx = 0, in_build = 0;

    if (argc != 2) {
        fprintf(stderr, "usage: carrenderinfo_test scenarios.txt\n");
        return 2;
    }
    fh = fopen(argv[1], "r");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    setvbuf(stdout, NULL, _IOFBF, 1 << 16);

    CarEmitterPositionSlotPool = (BSlotPool *)(void *)g_eppool;
    eLightFlareSlotPool = (BSlotPool *)(void *)g_lfpool;
    CarTypeInfoArray = g_ctis;
    TestRenderInfo = NULL;
    gTrackFlowGameFlow = &g_flow;
    gEWaitUntilRenderingDoneFn = wait_render;
    gFixStripSTsFn = fix_strip;
    gCarAssignAnimatedDriverFn = assign_drv;
    gCarUnAssignAnimatedDriverFn = unassign_drv;
    gBodyDamageSetALevelInfoFn = set_alevel;
    gBodyDamageAddModelFn = add_model;
    gAfxGetEmittersFn = afx_get;
    gAcidEmitterDeleteFn = acid_del;

    dump_table();
    memset(&b, 0, sizeof b);
    while (fgets(line, sizeof line, fh)) {
        const char *op = strtok(line, " \t\r\n");

        if (op == NULL)
            continue;
        if (strcmp(op, "B") == 0) {
            int j;

            memset(&b, 0, sizeof b);
            b.mode = hexu(tok());
            b.seed = hexu(tok());
            b.flow = hexu(tok());
            b.dmg = hexu(tok());
            b.dbits = hexu(tok());
            for (j = 0; j < 5; j++)
                b.ride[j] = hexu(tok());
            b.cartype = hexu(tok());
            b.afx = hexu(tok());
            if (b.cartype >= NCTI) exit(2);
            begin_world(&b);
            in_build = 1;
        } else if (strcmp(op, "C") == 0 && in_build) {
            read_cti();
        } else if (strcmp(op, "K") == 0 && in_build) {
            read_skins();
        } else if (strcmp(op, "O") == 0 && in_build) {
            read_solid();
        } else if (strcmp(op, "M") == 0 && in_build) {
            read_marker();
        } else if (strcmp(op, "T") == 0 && in_build) {
            read_textures();
        } else if (strcmp(op, "A") == 0 && in_build) {
            const char *a = tok(), *s;

            b.act = a ? a[0] : 'N';
            while ((s = tok()) != NULL && b.nargs < 8)
                b.args[b.nargs++] = hexu(s);
            run_build(idx++, &b);
            in_build = 0;
        } else if (strcmp(op, "P") == 0) {
            run_part(idx++);
        } else {
            fprintf(stderr, "bad line: %s\n", op);
            return 2;
        }
    }
    dump_table();
    fclose(fh);
    return 0;
}
