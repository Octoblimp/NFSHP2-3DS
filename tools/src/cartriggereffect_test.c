// Host harness for 3DS Files/source/cartriggereffect.c, Car::TriggerEffect,
// and terraineffect.c, TerrainEffectEmitters (TASKS 60). Runs the op script
// tools/cartriggereffect_check.py writes and prints the transcript it diffs
// against the retail image, run in mipsemu over the same script.
//
// TriggerEmitter, afxGetEmitters, the AcidEmitter's deleting destructor,
// bMalloc and bFree are stand-ins that print their arguments; afxGetEmitters
// puts 0 to 2 emitters from the harness's pool on the list's tail by the
// group's hash. eMulMatrix, bIdentity, bchunk_hash and the terrain table are
// the port's own.
//
// A float prints as its bits.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acidsys.h"
#include "bmem.h"
#include "car.h"
#include "carrenderinfo.h"
#include "cartriggereffect.h"
#include "collision.h"
#include "terraineffect.h"

#define NUM_EM       512
#define NUM_DATA     8
#define NUM_POS      64
#define NUM_CAR_EM   17
#define FIRST_AFX_EM 32

// collision.c's and acidsys.c's, which the harness does not link.
void            *pTerrainEffectEmitters;
AcidEffectSystem WorldEffects;

static Car                s_car;
static CarRenderInfo      s_ri;
static AcidEmitter        s_em[NUM_EM];
static AcidEmitterData    s_data[NUM_DATA];
static CarEmitterPosition s_pos[NUM_POS];
static bVector3           s_vel, s_at;
static int                s_nextEm = FIRST_AFX_EM;
static unsigned char      s_tee[sizeof(TerrainEffectEmitters)];

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float fl(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static const char *label(const void *p)
{
    static char buf[32];

    if (p == NULL)
        return "NULL";
    if (p == &s_car)
        return "car";
    if (p == &WorldEffects)
        return "world";
    if (p == s_tee)
        return "tee";
    snprintf(buf, sizeof buf, "?%p", p);
    return buf;
}

static void init_emitter(int i, int d)
{
    AcidEmitter *e = &s_em[i];
    float       *lw = &e->LocalWorld.v0.x;
    int          k;

    for (k = 0; k < 16; k++)
        lw[k] = 0.25f * (float)((i * 7 + k * 3) % 11) - 1.0f;
    e->InheritVelocity.x = 5.0f;
    e->InheritVelocity.y = 6.0f;
    e->InheritVelocity.z = 7.0f;
    e->InheritVelocity.w = 8.0f;
    e->EmitterData       = &s_data[d];
}

static void empty(bNode *l)
{
    l->next = l;
    l->prev = l;
}

static void link_tail(bNode *l, bNode *n)
{
    n->next       = l;
    n->prev       = l->prev;
    l->prev->next = n;
    l->prev       = n;
}

static void print_words(const float *f, int n)
{
    int k;

    for (k = 0; k < n; k++)
        printf("%s%08x", k ? " " : "", (unsigned)bits(f[k]));
}

static uint32_t hash_emitter(uint32_t h, int i)
{
    const float *lw = &s_em[i].LocalWorld.v0.x;
    const float *iv = &s_em[i].InheritVelocity.x;
    int          k;

    for (k = 0; k < 16; k++)
        h = (h ^ bits(lw[k])) * 16777619u;
    for (k = 0; k < 4; k++)
        h = (h ^ bits(iv[k])) * 16777619u;
    return h;
}

// The car's emitters, then afxGetEmitters' so far.
static uint32_t emitters_hash(void)
{
    uint32_t h = 0x811c9dc5u;
    int      i;

    for (i = 0; i < NUM_CAR_EM; i++)
        h = hash_emitter(h, i);
    for (i = FIRST_AFX_EM; i < s_nextEm; i++)
        h = hash_emitter(h, i);
    return h;
}

// ---------------------------------------------------------- the stand-ins

void acid_system_trigger_emitter(AcidEffectSystem *s, AcidEmitter *e,
                                 float time_step, void *car)
{
    printf("trigger sys=%s e=%d step=%08x car=%s lw=", label(s),
           (int)(e - s_em), (unsigned)bits(time_step), label(car));
    print_words(&e->LocalWorld.v0.x, 16);
    printf(" iv=");
    print_words(&e->InheritVelocity.x, 4);
    printf("\n");
}

void afx_get_emitters(bNode *list, uint32_t group_hash)
{
    TerrainEffectEmitters *t   = (TerrainEffectEmitters *)s_tee;
    int                    idx = (int)(list - &t->Lists[0][0]);
    int                    n   = (int)((group_hash >> 4) % 3), k;

    printf("afx list=%d,%d hash=%08x n=%d\n", idx / NUM_TERRAIN_TYPES,
           idx % NUM_TERRAIN_TYPES, (unsigned)group_hash, n);
    for (k = 0; k < n; k++) {
        int i = s_nextEm++;

        if (i >= NUM_EM) {
            fprintf(stderr, "emitter pool full\n");
            exit(3);
        }
        init_emitter(i, (int)(group_hash % NUM_DATA));
        link_tail(list, &s_em[i].Node);
    }
}

void acid_emitter_delete(AcidEmitter *e, int32_t flags)
{
    printf("delete e=%d flags=%d\n", (int)(e - s_em), (int)flags);
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    if (size == (int)sizeof(TerrainEffectEmitters))
        printf("bMalloc size=tee name=%s flags=%d pool=%d\n", name, flags,
               pool);
    else
        printf("bMalloc size=%d name=%s flags=%d pool=%d\n", size, name,
               flags, pool);
    memset(s_tee, 0xab, sizeof s_tee);
    return s_tee;
}

void bFree(void *p)
{
    printf("free p=%s\n", label(p));
}

// ---------------------------------------------------------------- the ops

static uint32_t hx(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 16);
}

int main(int argc, char **argv)
{
    char  line[4096];
    FILE *f;
    int   i;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: cartriggereffect_test SCRIPT\n");
        return 2;
    }
    for (i = 0; i < NUM_EM; i++)
        init_emitter(i, 0);
    for (i = 0; i < NUM_POS; i++) {
        s_pos[i].X = 0.5f * (float)i - 3.0f;
        s_pos[i].Y = 0.25f * (float)((i * 5) % 7) + 0.5f;
        s_pos[i].Z = -0.125f * (float)i + 1.0f;
    }
    for (i = 0; i < CARRENDERINFO_NUM_EMITTERS; i++)
        empty(&s_ri.EmitterList[i]);
    for (i = 0; i < CARRENDERINFO_NUM_EMITTER_POSITIONS; i++) {
        s_ri.EmitterPositionList[i].Head =
            (bSNode *)&s_ri.EmitterPositionList[i];
        s_ri.EmitterPositionList[i].Tail =
            (bSNode *)&s_ri.EmitterPositionList[i];
    }

    while (fgets(line, sizeof line, f) != NULL) {
        char *tok[64];
        int   n = 0;
        char *p;

        line[strcspn(line, "\r\n")] = '\0';
        if (line[0] == '\0')
            continue;
        if (line[0] == 'B') {
            printf("%s\n", line);
            continue;
        }
        printf("> %.40s\n", line);
        for (p = strtok(line, " "); p != NULL && n < 64; p = strtok(NULL, " "))
            tok[n++] = p;

        switch (tok[0][0]) {
        case 'D':
            s_data[atoi(tok[1])].CarPosition = atoi(tok[2]);
            break;
        case 'E':
            init_emitter(atoi(tok[1]), atoi(tok[2]));
            break;
        case 'W': {
            bSList *l = &s_ri.EmitterPositionList[atoi(tok[1])];
            int     k;

            l->Head = l->Tail = (bSNode *)l;
            for (k = 2; k < n; k++) {
                bSNode *node = &s_pos[atoi(tok[k])].Node;

                node->next    = (bSNode *)l;
                l->Tail->next = node;
                l->Tail       = node;
            }
            break;
        }
        case 'L': {
            bNode *l = &s_ri.EmitterList[atoi(tok[1])];
            int    k;

            empty(l);
            for (k = 2; k < n; k++)
                link_tail(l, &s_em[atoi(tok[k])].Node);
            break;
        }
        case 'S': {
            float *g = &s_car.State.GeometryPosition.x;
            float *q = &s_car.State.Position.x;
            float *v = &s_car.State.Velocity.x;
            float *m = &s_car.State.BodyMatrix.v0.x;
            int    k;

            for (k = 0; k < 4; k++) {
                g[k] = fl(hx(tok[1 + k]));
                q[k] = fl(hx(tok[5 + k]));
                v[k] = fl(hx(tok[9 + k]));
            }
            for (k = 0; k < 16; k++)
                m[k] = fl(hx(tok[13 + k]));
            break;
        }
        case 'C': {
            int       fx    = atoi(tok[1]);
            float     scale = fl(hx(tok[2]));
            int32_t   where = (int32_t)hx(tok[3]);
            bVector3 *vel   = NULL;

            s_car.pRenderInfo = atoi(tok[4]) ? &s_ri : NULL;
            s_car.TheOverrideRenderingPosition.OverrideViewBits = hx(tok[5]);
            if (atoi(tok[6])) {
                s_vel.x   = fl(hx(tok[7]));
                s_vel.y   = fl(hx(tok[8]));
                s_vel.z   = fl(hx(tok[9]));
                s_vel.pad = fl(hx(tok[10]));
                vel       = &s_vel;
            }
            car_trigger_effect(&s_car, fx, scale, where, vel);
            printf("state %08x\n", (unsigned)emitters_hash());
            break;
        }
        case 'T':
            s_at.x    = fl(hx(tok[4]));
            s_at.y    = fl(hx(tok[5]));
            s_at.z    = fl(hx(tok[6]));
            s_at.pad  = fl(hx(tok[7]));
            s_vel.x   = fl(hx(tok[8]));
            s_vel.y   = fl(hx(tok[9]));
            s_vel.z   = fl(hx(tok[10]));
            s_vel.pad = fl(hx(tok[11]));
            terrain_effect_emitters_trigger(
                (TerrainEffectEmitters *)pTerrainEffectEmitters,
                atoi(tok[1]), atoi(tok[2]), fl(hx(tok[3])), &s_at, &s_vel);
            printf("state %08x\n", (unsigned)emitters_hash());
            break;
        case 'I':
            init_terrain_effect_emitters();
            printf("init tee=%s\n", label(pTerrainEffectEmitters));
            break;
        case 'X':
            close_terrain_effect_emitters();
            printf("close tee=%s\n", label(pTerrainEffectEmitters));
            break;
        case 'Z':
            terrain_effect_emitters_destroy(
                (TerrainEffectEmitters *)pTerrainEffectEmitters,
                atoi(tok[1]));
            pTerrainEffectEmitters = NULL;
            printf("destroyed\n");
            break;
        default:
            fprintf(stderr, "bad op %s\n", tok[0]);
            return 2;
        }
    }
    fclose(f);
    return 0;
}
