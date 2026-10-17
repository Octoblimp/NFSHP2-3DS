// cardamage_test -- tools/cardamage_check.py's harness.
//
// Runs cardamage.c over the checker's script and prints what the model
// prints for the image. The script lays out each info chunk, car, solid
// and model; this host has 8-byte pointers, so each is built here with the
// host's structs from the same numbers. What CarDamage calls out of its
// object -- eFindPositionMarker, PlayGlass, Car::TriggerEffect,
// UpdateCarReplacementTextures, eModel::SetEnvironmentMapping and the
// delete -- is a stand-in here and a stub in the model, and both print the
// call. The walk over a model's vertices is estripdata.c's here and the
// image's in the model, over the strips the script lays out, and the
// port's seam at its end prints what the model's hook on the walk's
// epilogue does.
//
// A pointer prints as what it is: iK (info K) and iK.keys (the words after
// it), IH and BH (the two lists' heads), cN (car N), cN.pos (its
// position), riN (its render info), dN (its damage), dN.b (the body
// damage), dN.mI (its I-th model slot), sN (solid N), mN (model N), pN
// (marker N), 0 for NULL and ? for anything else.
//
// A strip's packet is 1,024 bytes of the script's seed: each word a float,
// (k - 1000) / 64 for k the generator's next bits 16 up mod 2001, and then
// each vertex's colour the next bits 16 up, where the colours are.
//
//     cardamage_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "car.h"
#include "cardamage.h"
#include "carrenderinfo.h"
#include "cartypeinfo.h"
#include "collisionsound.h"
#include "emodel.h"
#include "epositionmarker.h"
#include "esolid.h"
#include "estripdata.h"
#include "race.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

// race.c's and carrace.c's, which the harness does not link.
RaceParameters     TheRaceParameters;
CarTriggerEffectFn gCarTriggerEffectFn;

#define NINFO   32
#define NCAR    8
#define NSOLID  16
#define NMODEL  16
#define NMARK   48
#define NSTRIP  16              // a solid's strips at most
#define PACKET  1024            // a strip's packet's bytes

static uint8_t         *info_chunk[NINFO];
static BodyDamageInfo  *infos[NINFO];
static Car             *cars[NCAR];
static CarDamage       *dmg[NCAR];
static uint8_t          ris[NCAR][16];  // the render infos: only addresses
static eSolid          *solids[NSOLID];
static eModel           models[NMODEL];
static ePositionMarker  marks[NMARK];
static int              nmarks;

static float fb(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static uint32_t bf(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static const char *label(const void *p)
{
    static char buf[8][32];
    static int  b;
    char       *s = buf[b++ & 7];
    int         k, i;

    if (p == NULL)
        return "0";
    if (p == &BodyDamageInfoList)
        return "IH";
    if (p == &BodyDamageList)
        return "BH";
    for (k = 0; k < NINFO; k++) {
        if (infos[k] == NULL)
            continue;
        if (p == infos[k]) {
            snprintf(s, 32, "i%d", k);
            return s;
        }
        if (p == (const void *)(infos[k] + 1)) {
            snprintf(s, 32, "i%d.keys", k);
            return s;
        }
    }
    for (k = 0; k < NCAR; k++) {
        if (cars[k] == NULL)
            continue;
        if (p == cars[k])
            snprintf(s, 32, "c%d", k);
        else if (p == &cars[k]->State.Position)
            snprintf(s, 32, "c%d.pos", k);
        else if (p == ris[k])
            snprintf(s, 32, "ri%d", k);
        else if (p == dmg[k])
            snprintf(s, 32, "d%d", k);
        else if (p == &dmg[k]->TheBodyDamage)
            snprintf(s, 32, "d%d.b", k);
        else {
            for (i = 0; i < BODYDAMAGE_MODELS; i++)
                if (p == &dmg[k]->TheBodyDamage.BodyDamageModels[i]) {
                    snprintf(s, 32, "d%d.m%d", k, i);
                    return s;
                }
            continue;
        }
        return s;
    }
    for (k = 0; k < NSOLID; k++)
        if (solids[k] != NULL && p == solids[k]) {
            snprintf(s, 32, "s%d", k);
            return s;
        }
    for (k = 0; k < NMODEL; k++)
        if (p == &models[k]) {
            snprintf(s, 32, "m%d", k);
            return s;
        }
    for (k = 0; k < nmarks; k++)
        if (p == &marks[k]) {
            snprintf(s, 32, "p%d", k);
            return s;
        }
    return "?";
}

// ---------------------------------------------------------- the stand-ins

ePositionMarker *eFindPositionMarker(uint32_t name_hash, uint32_t type_hash,
                                     ePositionMarker *prev)
{
    int k;

    printf("  pm %08x %08x %s\n", (unsigned)name_hash, (unsigned)type_hash,
           label(prev));
    for (k = 0; k < nmarks; k++)
        if (marks[k].NameHash == name_hash && marks[k].TypeHash == type_hash)
            return &marks[k];
    return NULL;
}

void collision_sound_play_glass(const bVector3 *pos)
{
    printf("  glass %s\n", label(pos));
}

void carrenderinfo_update_car_replacement_textures(CarRenderInfo *ri)
{
    printf("  textures %s\n", label(ri));
}

void emodel_set_environment_mapping(eModel *m, uint32_t hash, int32_t on)
{
    printf("  envmap %s %08x %d\n", label(m), (unsigned)hash, (int)on);
}

void bFree(void *p)
{
    printf("  delete %s\n", label(p));
}

static void fake_effect(Car *c, CarEffect fx, float scale, int32_t where,
                        bVector3 *pos)
{
    printf("  effect %s fx=%d scale=%08x where=%d at=%s\n", label(c),
           (int)fx, (unsigned)bf(scale), (int)where, label(pos));
}

static void changed(const eSolid *s)
{
    printf("  changed %s\n", label(s));
}

// ---------------------------------------------------------------- strips

static uint32_t lcg(uint32_t *state)
{
    *state = *state * 1103515245u + 12345u;
    return *state;
}

// Where vertex i's colour is in a packet of n vertices, worked out apart
// from estripdata.c so that its mistakes show.
static size_t colour_at(int32_t n, int32_t i)
{
    size_t p = 28 + (size_t)n * 12 + 4;

    if (n % 4 != 0 && n >= 4)
        p += 4;
    p += (size_t)n * 8 + 4;
    if (n % 2 != 0 && n >= 2)
        p += 4;
    return p + 4 + (size_t)i * 2;
}

static uint32_t fnv(const uint8_t *p, size_t n)
{
    uint32_t h = 2166136261u;
    size_t   i;

    for (i = 0; i < n; i++)
        h = (h ^ p[i]) * 16777619u;
    return h;
}

// ---------------------------------------------------------------- dumps

static void dump_list(const char *name, bNode *head, int limit)
{
    bNode *n;
    int    steps;

    printf("  %s", name);
    for (n = head->next, steps = 0; n != head && steps < limit;
         n = n->next, steps++) {
        const char *l = label(n);

        printf(" %s", l);
        if (strcmp(l, "?") == 0 || strcmp(l, "0") == 0)
            break;
    }
    printf("\n  %s back", name);
    for (n = head->prev, steps = 0; n != head && steps < limit;
         n = n->prev, steps++) {
        const char *l = label(n);

        printf(" %s", l);
        if (strcmp(l, "?") == 0 || strcmp(l, "0") == 0)
            break;
    }
    printf("\n");
}

static void dump_infos(void)
{
    dump_list("infos", &BodyDamageInfoList, NINFO + 2);
}

static void dump_bodies(void)
{
    dump_list("bodies", &BodyDamageList, NCAR + 2);
}

static void dump_damage(int c)
{
    CarDamage  *d = dmg[c];
    BodyDamage *b = &d->TheBodyDamage;
    int         i, n;

    printf("  d%d car=%s base=%08x items=%08x applied=%08x\n", c,
           label(d->pCar), (unsigned)d->CarBaseNameHash,
           (unsigned)d->BreakableCarItemDamageAmounts,
           (unsigned)d->AppliedBreakableCarItemDamageAmounts);
    printf("  d%d zones=", c);
    for (i = 0; i < BODYDAMAGE_ZONES; i++)
        printf("%02x", b->CompressedDamageAmounts[i]);
    printf(" total=%u\n  d%d shown=", (unsigned)b->CompressedTotalDamage, c);
    for (i = 0; i < BODYDAMAGE_ZONES; i++)
        printf("%02x", b->CompressedAppliedDamageAmounts[i]);
    printf(" total=%u\n", (unsigned)b->CompressedTotalAppliedDamage);
    printf("  d%d alevel=%s models=%d parts=", c,
           label(b->pALevelBodyDamageInfo), (int)b->NumBodyDamageModels);
    for (i = 0; i < CARDAMAGE_ITEMS; i++)
        printf("%s%d", i ? "," : "", (int)d->ItemZones[i]);
    printf("\n");
    n = b->NumBodyDamageModels;
    if (n > BODYDAMAGE_MODELS)
        n = BODYDAMAGE_MODELS;
    for (i = 0; i < n; i++) {
        BodyDamageModel *m = &b->BodyDamageModels[i];

        printf("  d%d.m%d bd=%s model=%s info=%s nv=%d polys=%d rep=%d "
               "key=%d\n", c, i, label(m->pBodyDamage), label(m->pModel),
               label(m->pBodyDamageInfo), (int)m->NumVertices,
               (int)m->DamagePolysOnly, (int)m->RepeatCount,
               (int)m->KeyNum);
    }
}

// ---------------------------------------------------------------- the ops

static char *fields[32];
static int   nfields;

// `s` cut at each `sep` in place, empty pieces skipped: the pieces' count.
static int split(char *s, char sep, char **out, int max)
{
    int n = 0;

    while (*s != 0 && n < max) {
        char *e = strchr(s, sep);

        if (e != NULL)
            *e = 0;
        if (*s != 0)
            out[n++] = s;
        if (e == NULL)
            break;
        s = e + 1;
    }
    return n;
}

static uint32_t U(int i)
{
    return (uint32_t)strtoul(fields[i], NULL, 0);
}

static int32_t I(int i)
{
    return (int32_t)strtol(fields[i], NULL, 0);
}

static float F(int i)
{
    return fb(U(i));
}

static void reset(void)
{
    BodyDamageInfoList.next = BodyDamageInfoList.prev = &BodyDamageInfoList;
    BodyDamageList.next = BodyDamageList.prev = &BodyDamageList;
    memset(infos, 0, sizeof infos);
    memset(info_chunk, 0, sizeof info_chunk);
    memset(cars, 0, sizeof cars);
    memset(dmg, 0, sizeof dmg);
    memset(solids, 0, sizeof solids);
    memset(models, 0, sizeof models);
    nmarks = 0;
    TheRaceParameters.DamageEnabled = 1;
}

// info|k|type|name|hash|nverts|nkeys|minx|miny|maxx|maxy|cx|cy
static void op_info(void)
{
    int             k = I(1), nkeys = I(6);
    size_t          size = 8 + sizeof(BodyDamageInfo) + 4u * (size_t)nkeys;
    uint8_t        *c = (uint8_t *)malloc(size + 16);
    BodyDamageInfo *bi;
    uint32_t        w[2];

    memset(c, 0xcd, size + 16);
    w[0] = U(2);
    w[1] = 84u + 4u * (uint32_t)nkeys;
    memcpy(c, w, sizeof w);
    bi = (BodyDamageInfo *)(void *)(c + 8);
    memset(bi->Name, 0, sizeof bi->Name);
    strncpy(bi->Name, fields[3], sizeof bi->Name - 1);
    bi->NameHash = U(4);
    bi->NumVertices = I(5);
    bi->NumKeys = nkeys;
    bi->BBoxMin.x = F(7);
    bi->BBoxMin.y = F(8);
    bi->BBoxMax.x = F(9);
    bi->BBoxMax.y = F(10);
    bi->Center.x = F(11);
    bi->Center.y = F(12);
    info_chunk[k] = c;
    infos[k] = bi;
}

// car|c|type|base
static void op_car(void)
{
    int          c = I(1);
    Car         *car = (Car *)calloc(1, sizeof(Car));
    CarTypeInfo *cti = (CarTypeInfo *)calloc(1, sizeof(CarTypeInfo));
    RideInfo    *ride = (RideInfo *)calloc(1, sizeof(RideInfo));
    void        *mem = malloc(sizeof(CarDamage));
    CarDamage   *r;

    strncpy(cti->BaseModelName, fields[3], sizeof cti->BaseModelName - 1);
    ride->Type = I(2);
    car->pCarTypeInfo = cti;
    car->pRideInfo = ride;
    car->pRenderInfo = (CarRenderInfo *)(void *)ris[c];
    memset(mem, 0xcd, sizeof(CarDamage));
    cars[c] = car;
    dmg[c] = (CarDamage *)mem;
    printf("car c%d type=%d base=%s\n", c, (int)ride->Type, fields[3]);
    r = cardamage_construct(mem, car);
    printf("  -> %s\n", label(r));
    dump_damage(c);
    dump_bodies();
}

// solid|s|nverts: no strips yet, room for NSTRIP.
static void op_solid(void)
{
    eSolid *s = (eSolid *)calloc(1, sizeof(eSolid));

    s->NumVerts = (int16_t)I(2);
    s->StripEntryTable = calloc(NSTRIP, sizeof(eStripEntry));
    solids[I(1)] = s;
}

// strip|s|nverts|flags|seed: one more strip on solid s.
static void op_strip(void)
{
    eSolid      *s = solids[I(1)];
    eStripEntry *e = (eStripEntry *)s->StripEntryTable + s->NumStrips;
    uint8_t     *d = (uint8_t *)calloc(1, PACKET);
    uint32_t     state = U(4);
    int32_t      n = I(2), i;

    for (i = 0; i < PACKET / 4; i++) {
        float f = (float)((int32_t)((lcg(&state) >> 16) % 2001u) - 1000)
                  / 64.0f;

        memcpy(d + 4 * i, &f, 4);
    }
    d[4] = (uint8_t)n;
    for (i = 0; i < n; i++) {
        uint16_t c = (uint16_t)(lcg(&state) >> 16);

        memcpy(d + colour_at(n, i), &c, 2);
    }
    e->Data = d;
    e->DataQWordSize = PACKET / 16;
    e->Flags = (uint16_t)U(3);
    e->NumVerts = (uint8_t)n;
    s->NumStrips++;
}

// verts|s: each strip's flags and packet, and each vertex as the
// accessors read it.
static void op_verts(void)
{
    eSolid *s = solids[I(1)];
    int32_t j, v;

    printf("verts s%d\n", (int)I(1));
    for (j = 0; j < s->NumStrips; j++) {
        eStripEntry *e = (eStripEntry *)s->StripEntryTable + j;

        printf("  s%d.%d flags=%04x sum=%08x\n", (int)I(1), (int)j,
               (unsigned)e->Flags, (unsigned)fnv(e->Data, PACKET));
        for (v = 0; v < e->NumVerts; v++) {
            float    x, y, z;
            uint16_t c;

            estripdata_get_xyz(e->Data, v, &x, &y, &z);
            memcpy(&c, e->Data + estripdata_element_rgba(e->Data, v), 2);
            printf("  s%d.%d.%d %08x %08x %08x %04x\n", (int)I(1), (int)j,
                   (int)v, (unsigned)bf(x), (unsigned)bf(y), (unsigned)bf(z),
                   (unsigned)c);
        }
    }
}

static void call_op(void)
{
    const char *o = fields[0];
    int         c = nfields > 1 ? I(1) : 0;

    if (strcmp(o, "reset") == 0) {
        reset();
        printf("reset\n");
    } else if (strcmp(o, "enabled") == 0) {
        TheRaceParameters.DamageEnabled = I(1);
        printf("enabled %d\n", (int)I(1));
    } else if (strcmp(o, "info") == 0) {
        op_info();
    } else if (strcmp(o, "load") == 0 || strcmp(o, "unload") == 0) {
        int r = o[0] == 'l' ? loader_body_damage(info_chunk[c])
                            : unloader_body_damage(info_chunk[c]);

        printf("%s i%d -> %d\n", o, c, r);
        printf("  i%d keys=%s vi=%s\n", c, label(infos[c]->pKeys),
               label(infos[c]->pVertexIndices));
        dump_infos();
    } else if (strcmp(o, "find") == 0) {
        printf("find %08x -> %s\n", (unsigned)U(1),
               label(find_body_damage_info(U(1))));
    } else if (strcmp(o, "car") == 0) {
        op_car();
    } else if (strcmp(o, "solid") == 0) {
        op_solid();
    } else if (strcmp(o, "strip") == 0) {
        op_strip();
    } else if (strcmp(o, "verts") == 0) {
        op_verts();
    } else if (strcmp(o, "key") == 0) {
        ((uint32_t *)(void *)(infos[c] + 1))[I(2)] = U(3);
    } else if (strcmp(o, "model") == 0) {
        models[c].Solid = I(2) < 0 ? NULL : solids[I(2)];
    } else if (strcmp(o, "marker") == 0) {
        ePositionMarker *m = &marks[nmarks++];

        memset(m, 0, sizeof *m);
        m->NameHash = U(1);
        m->TypeHash = U(2);
        m->Position[0] = F(3);
        m->Position[1] = F(4);
        m->Position[2] = F(5);
    } else if (strcmp(o, "seam") == 0) {
        gESolidVerticesChangedFn = I(1) ? changed : NULL;
    } else if (strcmp(o, "alevel") == 0) {
        printf("alevel d%d %s\n", c, fields[2]);
        bodydamage_set_alevel_info(&dmg[c]->TheBodyDamage, fields[2]);
        printf("  -> %s\n", label(dmg[c]->TheBodyDamage.pALevelBodyDamageInfo));
    } else if (strcmp(o, "add") == 0) {
        printf("add d%d m%d %s %d\n", c, (int)I(2), fields[3], (int)I(4));
        bodydamage_add_model(&dmg[c]->TheBodyDamage, &models[I(2)], fields[3],
                             I(4));
        dump_damage(c);
    } else if (strcmp(o, "parts") == 0) {
        printf("parts d%d\n", c);
        cardamage_find_item_parts(dmg[c]);
        dump_damage(c);
    } else if (strcmp(o, "hit") == 0) {
        bVector3 at;

        at.x = F(2);
        at.y = F(3);
        at.z = F(4);
        at.pad = 0.0f;
        printf("hit d%d %08x %08x %08x %08x\n", c, (unsigned)U(2),
               (unsigned)U(3), (unsigned)U(4), (unsigned)U(5));
        cardamage_add_damage(dmg[c], &at, F(5));
        dump_damage(c);
    } else if (strcmp(o, "zone") == 0) {
        printf("zone d%d %d %08x %08x\n", c, (int)I(2), (unsigned)U(3),
               (unsigned)U(4));
        cardamage_add_zone(dmg[c], I(2), F(3), F(4));
        dump_damage(c);
    } else if (strcmp(o, "states") == 0) {
        printf("states d%d -> %08x\n", c,
               (unsigned)cardamage_compute_item_states(dmg[c]));
    } else if (strcmp(o, "rethink") == 0) {
        printf("rethink d%d\n", c);
        cardamage_rethink_damage(dmg[c]);
        dump_damage(c);
    } else if (strcmp(o, "apply") == 0) {
        printf("apply d%d\n", c);
        cardamage_apply_damage(dmg[c]);
        dump_damage(c);
    } else if (strcmp(o, "wreck") == 0) {
        printf("wreck d%d\n", c);
        cardamage_wreck(dmg[c]);
        dump_damage(c);
    } else if (strcmp(o, "repair") == 0) {
        printf("repair d%d\n", c);
        cardamage_repair_all(dmg[c]);
        dump_damage(c);
    } else if (strcmp(o, "bapply") == 0) {
        printf("bapply d%d\n", c);
        bodydamage_apply_damage(&dmg[c]->TheBodyDamage);
        dump_damage(c);
    } else if (strcmp(o, "brepair") == 0) {
        printf("brepair d%d\n", c);
        bodydamage_repair_all(&dmg[c]->TheBodyDamage);
        dump_damage(c);
    } else if (strcmp(o, "setdmg") == 0) {
        printf("setdmg d%d %d %08x\n", c, (int)I(2), (unsigned)U(3));
        bodydamage_set_damage(&dmg[c]->TheBodyDamage, I(2), F(3));
        dump_damage(c);
    } else if (strcmp(o, "getzone") == 0) {
        float at[2];

        at[0] = F(2);
        at[1] = F(3);
        printf("getzone d%d %08x %08x -> %d\n", c, (unsigned)U(2),
               (unsigned)U(3),
               (int)bodydamage_get_zone(&dmg[c]->TheBodyDamage, at));
    } else if (strcmp(o, "amount") == 0 || strcmp(o, "visat") == 0) {
        float at[2], r;

        at[0] = F(2);
        at[1] = F(3);
        r = o[0] == 'a'
            ? bodydamage_get_damage_amount(&dmg[c]->TheBodyDamage, at)
            : bodydamage_get_visible_damage_amount_at(&dmg[c]->TheBodyDamage,
                                                      at);
        printf("%s d%d %08x %08x -> %08x\n", o, c, (unsigned)U(2),
               (unsigned)U(3), (unsigned)bf(r));
    } else if (strcmp(o, "vis") == 0) {
        printf("vis d%d %d -> %08x\n", c, (int)I(2),
               (unsigned)bf(bodydamage_get_visible_damage_amount(
                   &dmg[c]->TheBodyDamage, I(2))));
    } else if (strcmp(o, "cvis") == 0) {
        printf("cvis d%d %d -> %d\n", c, (int)I(2),
               (int)bodydamage_get_compressed_visible_damage_amount(
                   &dmg[c]->TheBodyDamage, I(2)));
    } else if (strcmp(o, "total") == 0) {
        printf("total d%d -> %08x\n", c,
               (unsigned)bf(bodydamage_get_visible_total_damage(
                   &dmg[c]->TheBodyDamage)));
    } else if (strcmp(o, "benv") == 0) {
        printf("benv d%d %08x %d\n", c, (unsigned)U(2), (int)I(3));
        bodydamage_set_environment_mapping(&dmg[c]->TheBodyDamage, U(2),
                                           I(3));
    } else if (strcmp(o, "destroy") == 0) {
        printf("destroy d%d %d\n", c, (int)I(2));
        cardamage_destroy(dmg[c], I(2));
        dump_bodies();
    } else if (strcmp(o, "dump") == 0) {
        printf("dump d%d\n", c);
        dump_damage(c);
    } else if (strcmp(o, "lists") == 0) {
        printf("lists\n");
        dump_infos();
        dump_bodies();
    } else {
        fprintf(stderr, "cardamage_test: no op %s\n", o);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE       *fh;

    if (argc != 2 || (fh = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: cardamage_test script.txt\n");
        return 2;
    }
    gCarTriggerEffectFn = fake_effect;
    gESolidVerticesChangedFn = changed;
    reset();
    while (fgets(line, sizeof line, fh) != NULL) {
        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        nfields = split(line, '|', fields, 32);
        call_op();
        fflush(stdout);
    }
    fclose(fh);
    return 0;
}
