// afx_test -- runs tools/afx_check.py's op script on the port's acidsys.c,
// printing what the model prints for the image.
//
// The slot pools are this file's: three fixed arenas, each handing out its
// lowest free slot, zeroed when the pool has ZERO_ALLOCATED_MEMORY and
// filled with 0xa5 when not, and full when the script says so or when no
// slot is free. GetTextureInfo is a stub that answers by a rule on the
// hash. eGetView gives three views of this file's, each with a camera the
// script places or none; bGetTicker counts up by 0x1234567 a call, and
// bGetTickerDifference is half the count between. The cars are two of this
// file's, of which DoTimeStep reads the velocity and RenderEffects the
// visible view bits. RenderEffects' views have three matrices each that
// the script sets, an ID and a camera's FOV, car not to render and dash;
// the frame memory is this file's FRAME_SIZE bytes, its CurrentBufferPos
// and CurrentBufferEnd where the script puts them. CalculateH prints the
// FOV it is given and answers the script's H, and eAttachDirectData
// (gEAttachDirectDataFn) prints the packet. The host has 8-byte pointers,
// so each record the script puts in a chunk is laid out as the host's
// struct, field by field from the disc's bytes; a chunk's pack header is
// where the loader will look for it, the payload rounded up to 16, from an
// address with the script's offset mod 16.
//
//     afx_test SCRIPT RECORDS

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acidsys.h"
#include "bslotpool.h"
#include "bticker.h"
#include "camera.h"
#include "car.h"
#include "emath.h"
#include "eframe.h"
#include "eview.h"
#include "eviewmatrix.h"
#include "texturepack.h"

#define PATB 0xa5
static uintptr_t PATPTR;

typedef char host_data_tail_check[
    sizeof(AcidEmitterData) - offsetof(AcidEmitterData, SpreadAsDisc) >= 520
    ? 1 : -1];
typedef char host_emitter_tail_check[
    sizeof(AcidEmitter) - offsetof(AcidEmitter, RandomSeed) >= 156 ? 1 : -1];

// ------------------------------------------------------------ the records

static uint8_t *recs;
static int ndisc_data, ndisc_emit;

static const uint8_t *disc_data(int i)
{
    return recs + 8 + 544 * i;
}

static const uint8_t *disc_emit(int i)
{
    return recs + 8 + 544 * ndisc_data + 192 * i;
}

// --------------------------------------------------------------- buffers

#define NBUF 8
#define NCH 8
#define BUFSZ (1u << 20)

typedef struct Buf {
    uint8_t *mem;
    uint8_t *at;
    int      n;
    uint8_t *ch[NCH];
    int      kind[NCH];          // 0 none, 1 datas, 2 emitters
    int      nrec[NCH];
    uint8_t *rec0[NCH];
} Buf;

static Buf bufs[NBUF];

// ----------------------------------------------------------------- pools

#define NPOOL 3
static const char *const kPoolNames[NPOOL] = {
    "AcidParticleSlotPool", "AcidActiveGroupSlotPool", "AcidEmitterSlotPool"
};
static const char *const kPoolShort[NPOOL] = { "pp", "gp", "ep" };
static const int kRetailSize[NPOOL] = { 32, 28, 192 };
static const int kSlots[NPOOL] = { 1000, 400, 600 };
static const size_t kHostSize[NPOOL] = {
    sizeof(AcidParticle), sizeof(AcidActiveGroup), sizeof(AcidEmitter)
};
static BSlotPool pools[NPOOL];
static uint8_t *arena[NPOOL];
static uint8_t *used[NPOOL];
static int fail_after[NPOOL];

static int pool_index(const BSlotPool *p)
{
    int i;

    for (i = 0; i < NPOOL; i++)
        if (p == &pools[i])
            return i;
    return -1;
}

// -------------------------------------------------------------- textures

#define NTEX 512
static TextureInfo texs[NTEX];
static uint32_t tex_hash[NTEX];
static int ntex;
#define NTXM 64
static uint32_t txm_hash[NTXM];
static int txm_mode[NTXM];
static int ntxm;

static int tex_mode(uint32_t h)
{
    int i;

    for (i = 0; i < ntxm; i++)
        if (txm_hash[i] == h)
            return txm_mode[i];
    return (int)(h % 3u);
}

// ------------------------------------------------------------------ lists

#define NLIST 8
static bNode lists[NLIST];

// "r": what the last CP, RA, GD or GE gave.
static void *reg;

// ---------------------------------------------- the views, ticker and cars

#define NVIEW 3
#define NCAR 2
static eView views[NVIEW];
static Camera cams[NVIEW];
static Car cars[NCAR];
static bMatrix4 mats[NVIEW][3];   // WorldView, WorldClip, WorldScreen
static uint32_t ticker;
static int32_t flow;
static uint32_t hval;             // CalculateH's answer

// ------------------------------------------------------------ frame memory

#define FRAME_SIZE 0x20000
static _Alignas(16) uint8_t frame[FRAME_SIZE];
uint8_t  *CurrentBufferPos;
uint8_t  *CurrentBufferEnd;
int32_t   FrameMallocFailed;
uint32_t  FrameMallocFailAmount;

static int32_t flow_state(void)
{
    return flow;
}

// ------------------------------------------------------------------ names

static char *nbuf(void)
{
    static char b[16][64];
    static int k;

    return b[k++ & 15];
}

static const char *nm(const void *p)
{
    uintptr_t a = (uintptr_t)p;
    char *s;
    int i, k, c;

    if (p == NULL)
        return "null";
    if (a == PATPTR)
        return "pat";
    if (p == &FrameEffects.ActiveGroupList)
        return "FE.act";
    if (p == &FrameEffects.AutoEmitterList)
        return "FE.auto";
    if (p == &WorldEffects.ActiveGroupList)
        return "WE.act";
    if (p == &WorldEffects.AutoEmitterList)
        return "WE.auto";
    if (p == &EmitterDataList)
        return "EDL";
    s = nbuf();
    for (i = 0; i < NCAR; i++)
        if (p == &cars[i]) {
            sprintf(s, "c%d", i);
            return s;
        }
    for (i = 0; i < NLIST; i++)
        if (p == &lists[i]) {
            sprintf(s, "L%d", i);
            return s;
        }
    for (i = 0; i < ntex; i++)
        if (p == &texs[i]) {
            sprintf(s, "t%d", i);
            return s;
        }
    for (i = 0; i < NPOOL; i++) {
        uint8_t *b = arena[i];
        size_t sz = kHostSize[i];

        if (b != NULL && (uint8_t *)p >= b && (uint8_t *)p < b + sz * kSlots[i]) {
            size_t off = (size_t)((uint8_t *)p - b);
            const char *pre = i == 0 ? "p" : i == 1 ? "g" : "e";

            if (off % sz == 0) {
                sprintf(s, "%s%d", pre, (int)(off / sz));
                return s;
            }
            if (i == 1 && off % sz == offsetof(AcidActiveGroup, ParticleList)) {
                sprintf(s, "g%d.pl", (int)(off / sz));
                return s;
            }
            return "?";
        }
    }
    for (k = 0; k < NBUF; k++) {
        Buf *b = &bufs[k];

        for (c = 0; c < b->n; c++) {
            size_t sz;
            uint8_t *r = b->rec0[c];

            if (b->kind[c] == 0)
                continue;
            sz = b->kind[c] == 1 ? sizeof(AcidEmitterData) : sizeof(AcidEmitter);
            if ((uint8_t *)p >= r && (uint8_t *)p < r + sz * b->nrec[c]
                && (size_t)((uint8_t *)p - r) % sz == 0) {
                sprintf(s, "%c%d.%d.%d", b->kind[c] == 1 ? 'D' : 'E', k, c,
                        (int)((size_t)((uint8_t *)p - r) / sz));
                return s;
            }
        }
    }
    return "?";
}

static const char *fx(float f)
{
    uint32_t w;
    char *s = nbuf();

    memcpy(&w, &f, 4);
    if ((w & 0x7f800000u) == 0x7f800000u && (w & 0x7fffffu))
        return "nan";
    sprintf(s, "%08x", (unsigned)w);
    return s;
}

static void add_tail(bNode *list, bNode *n)
{
    bNode *tail = list->prev;

    tail->next = n;
    list->prev = n;
    n->next = list;
    n->prev = tail;
}

static void add_head(bNode *list, bNode *n)
{
    bNode *head = list->next;

    list->next = n;
    head->prev = n;
    n->next = head;
    n->prev = list;
}

// ---------------------------------------------------------------- stubs

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *name,
                        int memoryPool)
{
    int i;

    for (i = 0; i < NPOOL; i++)
        if (!strcmp(name, kPoolNames[i]))
            break;
    if (i == NPOOL) {
        printf("  newpool ? %s\n", name);
        return NULL;
    }
    printf("  newpool %d %d %s %d\n",
           (size_t)slotSize == kHostSize[i] ? kRetailSize[i] : -slotSize,
           numSlots, name, memoryPool);
    pools[i].flags = BSP_DEFAULT_FLAGS;
    memset(used[i], 0, (size_t)kSlots[i]);
    fail_after[i] = -1;
    return &pools[i];
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("  delpool %s\n", pool == NULL ? "null"
           : pool_index(pool) >= 0 ? kPoolShort[pool_index(pool)] : "?");
}

static int free_slot(int i)
{
    int k;

    for (k = 0; k < kSlots[i]; k++)
        if (!used[i][k])
            return k;
    return -1;
}

static void *slot_alloc(BSlotPool *pool, const char *what)
{
    int i = pool_index(pool), k;

    if (i < 0) {
        printf("  %s %s -> null\n", what, pool == NULL ? "null" : "?");
        return NULL;
    }
    if (fail_after[i] == 0) {
        printf("  %s %s -> null\n", what, kPoolShort[i]);
        return NULL;
    }
    k = free_slot(i);
    if (k < 0) {
        printf("  %s %s -> full\n", what, kPoolShort[i]);
        return NULL;
    }
    if (fail_after[i] > 0)
        fail_after[i]--;
    used[i][k] = 1;
    memset(arena[i] + kHostSize[i] * k,
           (pool->flags & BSP_ZERO_ALLOCATED_MEMORY) ? 0 : PATB, kHostSize[i]);
    printf("  %s %s -> %s\n", what, kPoolShort[i],
           nm(arena[i] + kHostSize[i] * k));
    return arena[i] + kHostSize[i] * k;
}

void *bSlotOMalloc(BSlotPool *pool)
{
    return slot_alloc(pool, "omalloc");
}

void *bSlotMalloc(BSlotPool *pool)
{
    return slot_alloc(pool, "malloc");
}

int bIsSlotPoolFull(const BSlotPool *pool)
{
    int i = pool_index(pool), r;

    if (i < 0) {
        printf("  full? %s -> 1\n", pool == NULL ? "null" : "?");
        return 1;
    }
    r = fail_after[i] == 0 || free_slot(i) < 0;
    printf("  full? %s -> %d\n", kPoolShort[i], r);
    return r;
}

eView *eGetView(int32_t id)
{
    if (id < 0 || id >= NVIEW) {
        fprintf(stderr, "view %d\n", (int)id);
        exit(3);
    }
    return &views[id];
}

float CalculateH(uint16_t fov)
{
    float f;

    printf("  calch %04x\n", (unsigned)fov);
    memcpy(&f, &hval, 4);
    return f;
}

static void attach_direct_data(void *tex, float z, void *data, uint16_t qwc)
{
    uint32_t w;
    int i;

    printf("  attach %s z %s at %+ld qwc %d:", nm(tex), fx(z),
           (long)((uint8_t *)data - frame), (int)qwc);
    for (i = 0; i < qwc * 4; i++) {
        memcpy(&w, (uint8_t *)data + 4 * i, 4);
        printf(" %08x", (unsigned)w);
    }
    printf("\n");
}

uint32_t bGetTicker(void)
{
    ticker += 0x1234567u;
    return ticker;
}

float bGetTickerDifference(uint32_t from, uint32_t to)
{
    return (float)(to - from) * 0.5f;
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    int i = pool_index(pool);

    printf("  free %s %s\n", pool == NULL ? "null"
           : i >= 0 ? kPoolShort[i] : "?", nm(slot));
    if (i >= 0) {
        uint8_t *b = arena[i];
        size_t sz = kHostSize[i];

        if ((uint8_t *)slot >= b && (uint8_t *)slot < b + sz * kSlots[i]
            && (size_t)((uint8_t *)slot - b) % sz == 0)
            used[i][(size_t)((uint8_t *)slot - b) / sz] = 0;
    }
}

TextureInfo *GetTextureInfo(uint32_t h, int use_default, int include_unloaded)
{
    int mode = tex_mode(h), i;

    if (mode == 0) {
        printf("  gti %08x %d %d -> null\n", (unsigned)h, use_default,
               include_unloaded);
        return NULL;
    }
    for (i = 0; i < ntex; i++)
        if (tex_hash[i] == h)
            break;
    if (i == ntex) {
        if (ntex == NTEX) {
            fprintf(stderr, "textures full\n");
            exit(3);
        }
        tex_hash[ntex++] = h;
    }
    texs[i].NameHash = mode == 2 ? h ^ 1u : h;
    printf("  gti %08x %d %d -> %s\n", (unsigned)h, use_default,
           include_unloaded, nm(&texs[i]));
    return &texs[i];
}

// ---------------------------------------------------------------- tokens

static char *tok(void)
{
    char *t = strtok(NULL, " \t");

    if (t == NULL) {
        fprintf(stderr, "short line\n");
        exit(2);
    }
    return t;
}

static int itok(void)
{
    return (int)strtol(tok(), NULL, 0);
}

static uint32_t xtok(void)
{
    return (uint32_t)strtoul(tok(), NULL, 16);
}

static float ftok(void)
{
    uint32_t w = xtok();
    float f;

    memcpy(&f, &w, 4);
    return f;
}

// The i-th node of a list, from its head, or NULL.
static bNode *nth(bNode *list, int i)
{
    bNode *n = list->next;

    while (n != list && i > 0 && i < 100000) {
        n = n->next;
        i--;
    }
    return n == list ? NULL : n;
}

static bNode *system_list(const char *s, const char *which)
{
    AcidEffectSystem *sys = !strncmp(s, "FE", 2) ? &FrameEffects
                          : &WorldEffects;

    return !strcmp(which, "act") ? &sys->ActiveGroupList
                                 : &sys->AutoEmitterList;
}

// A name the script gives: null; D/E k.c.i, a record; e/g/p n, a slot;
// t n, a texture; FE, WE; L n, a list; and list.i, the i-th node of
// FE.act, FE.auto, WE.act, WE.auto, EDL or Ln.
static void *ref(const char *t)
{
    char head[16];
    const char *dot;
    int k, c, i;

    if (!strcmp(t, "null"))
        return NULL;
    if (!strcmp(t, "r"))
        return reg;
    if (!strcmp(t, "FE"))
        return &FrameEffects;
    if (!strcmp(t, "WE"))
        return &WorldEffects;
    if ((t[0] == 'D' || t[0] == 'E')
        && sscanf(t + 1, "%d.%d.%d", &k, &c, &i) == 3) {
        Buf *b = &bufs[k];
        size_t sz = t[0] == 'D' ? sizeof(AcidEmitterData) : sizeof(AcidEmitter);

        if (c >= b->n || i >= b->nrec[c])
            return NULL;
        return b->rec0[c] + sz * i;
    }
    if ((t[0] == 'e' || t[0] == 'g' || t[0] == 'p') && t[1] >= '0'
        && t[1] <= '9') {
        int p = t[0] == 'p' ? 0 : t[0] == 'g' ? 1 : 2;

        return arena[p] + kHostSize[p] * atoi(t + 1);
    }
    if (t[0] == 't' && t[1] >= '0' && t[1] <= '9')
        return &texs[atoi(t + 1)];
    if (t[0] == 'c' && t[1] >= '0' && t[1] <= '9')
        return &cars[atoi(t + 1)];
    dot = strrchr(t, '.');
    if (dot == NULL) {
        if (t[0] == 'L')
            return &lists[atoi(t + 1)];
        fprintf(stderr, "bad ref %s\n", t);
        exit(2);
    }
    snprintf(head, sizeof head, "%.*s", (int)(dot - t), t);
    i = atoi(dot + 1);
    if (!strcmp(head, "EDL"))
        return nth(&EmitterDataList, i);
    if (head[0] == 'L')
        return nth(&lists[atoi(head + 1)], i);
    return nth(system_list(head, head + 3), i);
}

// ----------------------------------------------------------------- dumps

static int walk_count(bNode *list, int *broken)
{
    bNode *n;
    int c = 0;

    *broken = 0;
    for (n = list->next; n != list && c < 5000; n = n->next, c++)
        if (n->next->prev != n)
            *broken = 1;
    return c;
}

static void pemit_short(const AcidEmitter *e)
{
    printf(" %s[st %d rc %s ec %s rs %08x d %s lag %s de %08x]", nm(e),
           (int)e->State, fx(e->RemainingCycleTime), fx(e->EmissionCountdown),
           (unsigned)e->RandomSeed, nm(e->EmitterData),
           nm(e->LastActiveGroup), (unsigned)e->DontEmit);
}

static void pemit_full(const AcidEmitter *e)
{
    const float *w = &e->LocalWorld.v0.x;
    int i;

    printf(" %s{nh %08x dh %08x st %d rc %s ec %s d %s lag %s rs %08x"
           " de %08x p2 %08x w", nm(e), (unsigned)e->NameHash,
           (unsigned)e->EmitterDataNameHash, (int)e->State,
           fx(e->RemainingCycleTime), fx(e->EmissionCountdown),
           nm(e->EmitterData), nm(e->LastActiveGroup),
           (unsigned)e->RandomSeed, (unsigned)e->DontEmit,
           (unsigned)e->pad2);
    for (i = 0; i < 16; i++)
        printf(" %s", fx(w[i]));
    printf(" iv %s %s %s %s n '", fx(e->InheritVelocity.x),
           fx(e->InheritVelocity.y), fx(e->InheritVelocity.z),
           fx(e->InheritVelocity.w));
    for (i = 0; i < 64 && e->Name[i] != 0; i++)
        putchar(e->Name[i] >= 0x20 && e->Name[i] < 0x7f ? e->Name[i] : '.');
    printf("'");
    // Any bytes after the terminator, which no string op reads.
    {
        int z = i, k, any = 0;

        for (k = z + 1; k < 64; k++)
            any |= e->Name[k];
        if (any) {
            printf(" +");
            for (k = z + 1; k < 64; k++)
                printf("%02x", (unsigned)(uint8_t)e->Name[k]);
        }
    }
    printf("}");
}

// " !p" when the list's tail is not the last node a walk from its head
// reaches.
static void ptail(bNode *list, bNode *last)
{
    if (list->prev != last)
        printf(" !p");
}

static void pemitters(const char *tag, bNode *list, int full)
{
    bNode *n, *last = list;
    int c = 0, broken;

    printf("  %s %d:", tag, walk_count(list, &broken));
    for (n = list->next; n != list && c < 5000; n = n->next, c++) {
        if (full)
            pemit_full((AcidEmitter *)n);
        else
            pemit_short((AcidEmitter *)n);
        if (n->next->prev != n)
            printf("!");
        last = n;
    }
    ptail(list, last);
    printf("\n");
}

static void pgroups(const char *tag, bNode *list)
{
    bNode *n, *last = list;
    int c = 0, broken;

    printf("  %s %d:", tag, walk_count(list, &broken));
    for (n = list->next; n != list && c < 5000; n = n->next, c++) {
        AcidActiveGroup *g = (AcidActiveGroup *)n;
        bNode *p, *plast = &g->ParticleList;
        int k = 0;

        printf(" %s{d %s e %s c %s:", nm(g), nm(g->EmitterData),
               nm(g->Emitter), nm(g->pCar));
        for (p = g->ParticleList.next; p != &g->ParticleList && k < 5000;
             p = p->next, k++) {
            printf(" %s%s", nm(p), p->next->prev != p ? "!" : "");
            plast = p;
        }
        ptail(&g->ParticleList, plast);
        printf("}%s", n->next->prev != n ? "!" : "");
        last = n;
    }
    ptail(list, last);
    printf("\n");
}

static void psystem(const char *tag, AcidEffectSystem *s)
{
    char t[16];
    const float *ip = &s->InterestPoints[0].x;
    int i;

    snprintf(t, sizeof t, "%s act", tag);
    pgroups(t, &s->ActiveGroupList);
    snprintf(t, sizeof t, "%s auto", tag);
    pemitters(t, &s->AutoEmitterList, 0);
    printf("  %s w cur %s sel %d b %02x %02x %02x %02x %02x %02x n %d nv %d"
           " rt %s ut %s ip", tag, nm(s->CurrentEmitter),
           (int)s->SelectEmitterIndex, s->DebugStats,
           s->CreateEmitterMaxScript, s->pad, s->PrintEmitterList,
           s->PrintNearbyEmitters, s->OnlyShowCurrentEmitter,
           (int)s->NumAutoEmitters, (int)s->NumVisibleParticles,
           fx(s->RenderTime), fx(s->UpdateTime));
    for (i = 0; i < 12; i++)
        printf(" %s", fx(ip[i]));
    printf("\n");
}

static void pip(const char *tag, const AcidEffectSystem *s)
{
    const float *ip = &s->InterestPoints[0].x;
    int i;

    printf("  %s ip", tag);
    for (i = 0; i < 12; i++)
        printf(" %s", fx(ip[i]));
    printf("\n");
}

// DP: each group of the system, and each of its particles.
static void pparticles(const char *tag, AcidEffectSystem *s)
{
    bNode *n;
    int c = 0;

    for (n = s->ActiveGroupList.next; n != &s->ActiveGroupList && c < 5000;
         n = n->next, c++) {
        AcidActiveGroup *g = (AcidActiveGroup *)n;
        bNode *pn;
        int k = 0;

        printf("  %s %s d %s e %s c %s:", tag, nm(g), nm(g->EmitterData),
               nm(g->Emitter), nm(g->pCar));
        for (pn = g->ParticleList.next; pn != &g->ParticleList && k < 5000;
             pn = pn->next, k++) {
            const AcidParticle *p = (const AcidParticle *)pn;

            printf(" %s[%04x %04x %04x %02x %02x %s %s %s %02x %02x %02x %02x]",
                   nm(p), (unsigned)p->Life, (unsigned)(uint16_t)p->Angle,
                   (unsigned)p->Speed, (unsigned)p->Inherit, (unsigned)p->Pad,
                   fx(p->X), fx(p->Y), fx(p->Z), (unsigned)(uint8_t)p->VX,
                   (unsigned)(uint8_t)p->VY, (unsigned)(uint8_t)p->VZ,
                   (unsigned)p->Frame);
        }
        printf("\n");
    }
}

static void pbases(const AcidEmitterData *d)
{
    const float *c = &d->ColourBasis.v0.x, *x = &d->ExtraBasis.v0.x;
    int i;

    printf("  cb");
    for (i = 0; i < 16; i++)
        printf(" %s", fx(c[i]));
    printf(" xb");
    for (i = 0; i < 16; i++)
        printf(" %s", fx(x[i]));
    printf("\n");
}

static const char *pool_str(BSlotPool *p)
{
    char *s;
    int i;

    if (p == NULL)
        return "null";
    i = pool_index(p);
    if (i < 0)
        return "?";
    s = nbuf();
    sprintf(s, "%s:%x", kPoolShort[i], (unsigned)p->flags);
    return s;
}

static void pglobals(void)
{
    bNode *n, *last = &EmitterDataList;
    int c = 0, broken;

    printf("  pools %s %s %s n %d seed %08x\n", pool_str(AcidParticleSlotPool),
           pool_str(AcidActiveGroupSlotPool), pool_str(AcidEmitterSlotPool),
           (int)NumAcidEmitters, (unsigned)AcidRandomSeed);
    printf("  edl %d:", walk_count(&EmitterDataList, &broken));
    for (n = EmitterDataList.next; n != &EmitterDataList && c < 5000;
         n = n->next, c++) {
        AcidEmitterData *d = (AcidEmitterData *)n;

        printf(" %s/%s%s", nm(d), nm(d->Texture), n->next->prev != n ? "!" : "");
        last = n;
    }
    ptail(&EmitterDataList, last);
    printf("\n");
}

static void pshort(void)
{
    int b0, b1, b2, b3, b4;

    printf("  s n %d seed %08x edl %d FE %d/%d/%d WE %d/%d/%d\n",
           (int)NumAcidEmitters, (unsigned)AcidRandomSeed,
           walk_count(&EmitterDataList, &b0),
           walk_count(&FrameEffects.ActiveGroupList, &b1),
           walk_count(&FrameEffects.AutoEmitterList, &b2),
           (int)FrameEffects.NumAutoEmitters,
           walk_count(&WorldEffects.ActiveGroupList, &b3),
           walk_count(&WorldEffects.AutoEmitterList, &b4),
           (int)WorldEffects.NumAutoEmitters);
    (void)b0, (void)b1, (void)b2, (void)b3, (void)b4;
}

static void dump_all(void)
{
    int i;

    pglobals();
    psystem("FE", &FrameEffects);
    psystem("WE", &WorldEffects);
    for (i = 0; i < NLIST; i++) {
        char t[8];

        if (lists[i].next == NULL)
            continue;
        snprintf(t, sizeof t, "L%d", i);
        pemitters(t, &lists[i], 1);
    }
}

// ---------------------------------------------------------------- chunks

static void put_data(AcidEmitterData *d, const uint8_t *r)
{
    uint32_t tex;

    memset(d, PATB, sizeof *d);
    memcpy(&d->NameHash, r + 8, 12);
    memcpy(&tex, r + 20, 4);
    d->Texture = tex ? (void *)PATPTR : NULL;
    memcpy(&d->SpreadAsDisc, r + 24, 520);
}

static void put_emitter(AcidEmitter *e, const uint8_t *r)
{
    uint32_t w;

    memset(e, PATB, sizeof *e);
    memcpy(&e->NameHash, r + 8, 20);
    memcpy(&w, r + 28, 4);
    e->EmitterData = w ? (AcidEmitterData *)PATPTR : NULL;
    memcpy(&w, r + 32, 4);
    e->LastActiveGroup = w ? (struct AcidActiveGroup *)PATPTR : NULL;
    memcpy(&e->RandomSeed, r + 36, 156);
}

// CH k type ver hn mis kind first: a chunk on buffer k, at the next
// address with that offset mod 16, its header where the loader looks,
// and hn records of kind (- none, D, E) from the first.
static void op_chunk(void)
{
    int k = itok();
    uint32_t type = xtok();
    int32_t ver = itok();
    uint32_t hn = (uint32_t)itok();
    int mis = itok();
    const char *kind = tok();
    int first = itok();
    Buf *b = &bufs[k];
    uint8_t *c, *h, *end;
    uint32_t i, size;
    int c_idx = b->n;

    c = b->at;
    while (((uintptr_t)c & 15u) != (uintptr_t)mis)
        c++;
    memset(c, 0, 64);
    memcpy(c, &type, 4);
    h = (uint8_t *)(((uintptr_t)c + 23u) & ~(uintptr_t)15u);
    memset(c + 8, 0, (size_t)(h - c - 8) + 16);
    memcpy(h + 8, &ver, 4);
    memcpy(h + 12, &hn, 4);
    b->ch[c_idx] = c;
    b->rec0[c_idx] = h + 16;
    b->kind[c_idx] = kind[0] == 'D' ? 1 : kind[0] == 'E' ? 2 : 0;
    b->nrec[c_idx] = b->kind[c_idx] ? (int)hn : 0;
    end = h + 16;
    for (i = 0; b->kind[c_idx] && i < hn; i++) {
        if (b->kind[c_idx] == 1) {
            put_data((AcidEmitterData *)end, disc_data(first + (int)i));
            end += sizeof(AcidEmitterData);
        } else {
            put_emitter((AcidEmitter *)end, disc_emit(first + (int)i));
            end += sizeof(AcidEmitter);
        }
    }
    size = (uint32_t)(end - c - 8);
    memcpy(c + 4, &size, 4);
    b->at = end;
    b->n++;
}

// --------------------------------------------------------------- helpers

static void reset(void)
{
    int i, k;

    memset(&FrameEffects, PATB, sizeof FrameEffects);
    memset(&WorldEffects, PATB, sizeof WorldEffects);
    EmitterDataList.next = (bNode *)PATPTR;
    EmitterDataList.prev = (bNode *)PATPTR;
    AcidParticleSlotPool = NULL;
    AcidActiveGroupSlotPool = NULL;
    AcidEmitterSlotPool = NULL;
    NumAcidEmitters = 0;
    AcidRandomSeed = 0x23985727u;
    for (i = 0; i < NPOOL; i++) {
        pools[i].flags = BSP_DEFAULT_FLAGS;
        memset(used[i], 0, (size_t)kSlots[i]);
        memset(arena[i], PATB, kHostSize[i] * (size_t)kSlots[i]);
        fail_after[i] = -1;
    }
    for (k = 0; k < NBUF; k++) {
        bufs[k].n = 0;
        bufs[k].at = bufs[k].mem;
    }
    memset(lists, 0, sizeof lists);
    reg = NULL;
    ntex = 0;
    ntxm = 0;
    memset(views, 0, sizeof views);
    memset(cams, 0, sizeof cams);
    memset(cars, 0, sizeof cars);
    memset(mats, 0, sizeof mats);
    for (i = 0; i < NVIEW; i++) {
        views[i].WorldViewMatrix = &mats[i][0];
        views[i].WorldClipMatrix = &mats[i][1];
        views[i].WorldScreenMatrix = &mats[i][2];
    }
    ticker = 0;
    flow = 0;
    hval = 0x43c80000u;
    acidz = 4;
    memset(frame, PATB, sizeof frame);
    CurrentBufferPos = frame;
    CurrentBufferEnd = frame + FRAME_SIZE;
    FrameMallocFailed = 0;
    FrameMallocFailAmount = 0;
}

// FB pos end: the frame memory's two ends, as offsets into it.
static uint8_t *frame_at(int off)
{
    if (off < 0 || off > FRAME_SIZE) {
        fprintf(stderr, "frame offset %d\n", off);
        exit(2);
    }
    return frame + off;
}

static AcidEffectSystem *sys_tok(void)
{
    const char *t = tok();

    return !strcmp(t, "FE") ? &FrameEffects : &WorldEffects;
}

// w or b: a word or a byte at a retail offset, from the first one past the
// pointers (first_off) on, where both sides lay the struct out alike.
static void set_tail(void *first, int first_off, const char *f)
{
    int off = itok();
    uint32_t v = xtok();
    uint8_t *a;

    if (off < first_off) {
        fprintf(stderr, "offset %d before the tail\n", off);
        exit(2);
    }
    a = (uint8_t *)first + (off - first_off);
    if (!strcmp(f, "w"))
        memcpy(a, &v, 4);
    else
        *a = (uint8_t)v;
}

static void set_field_e(AcidEmitter *e, const char *f)
{
    if (!strcmp(f, "w") || !strcmp(f, "b"))
        set_tail(&e->RandomSeed, 36, f);
    else if (!strcmp(f, "st"))
        e->State = itok();
    else if (!strcmp(f, "rc"))
        e->RemainingCycleTime = ftok();
    else if (!strcmp(f, "ec"))
        e->EmissionCountdown = ftok();
    else if (!strcmp(f, "rs"))
        e->RandomSeed = xtok();
    else if (!strcmp(f, "de"))
        e->DontEmit = xtok();
    else if (!strcmp(f, "nh"))
        e->NameHash = xtok();
    else if (!strcmp(f, "dh"))
        e->EmitterDataNameHash = xtok();
    else if (!strcmp(f, "d"))
        e->EmitterData = (AcidEmitterData *)ref(tok());
    else if (!strcmp(f, "nm")) {
        const char *s = tok();
        size_t n = strlen(s);

        memset(e->Name, 0, sizeof e->Name);
        memcpy(e->Name, s, n < sizeof e->Name ? n : sizeof e->Name);
    } else if (!strcmp(f, "nmz")) {
        tok();
        memset(e->Name, 0, sizeof e->Name);
    } else if (!strcmp(f, "nmg")) {
        // A short name, and 'G' in every byte after its terminator.
        const char *s = tok();
        size_t n = strlen(s);

        if (n > 62)
            n = 62;
        memset(e->Name, 'G', sizeof e->Name);
        memcpy(e->Name, s, n);
        e->Name[n] = 0;
    } else {
        fprintf(stderr, "bad field %s\n", f);
        exit(2);
    }
}

static void set_field_d(AcidEmitterData *d, const char *f)
{
    if (!strcmp(f, "w") || !strcmp(f, "b"))
        set_tail(&d->SpreadAsDisc, 24, f);
    else if (!strcmp(f, "on"))
        d->OnCycle = ftok();
    else if (!strcmp(f, "onv"))
        d->OnCycleVariance = ftok();
    else if (!strcmp(f, "off"))
        d->OffCycle = ftok();
    else if (!strcmp(f, "offv"))
        d->OffCycleVariance = ftok();
    else if (!strcmp(f, "nh"))
        d->NameHash = xtok();
    else if (!strcmp(f, "gh"))
        d->GroupNameHash = xtok();
    else if (!strcmp(f, "th"))
        d->TextureNameHash = xtok();
    else if (!strcmp(f, "tex"))
        d->Texture = ref(tok());
    else {
        fprintf(stderr, "bad field %s\n", f);
        exit(2);
    }
}

static int pool_tok(void)
{
    const char *t = tok();
    int i;

    for (i = 0; i < NPOOL; i++)
        if (!strcmp(t, kPoolShort[i]))
            return i;
    fprintf(stderr, "bad pool %s\n", t);
    exit(2);
}

// MG s e np: a group the way TriggerEmitter makes one, enough of it for
// the kill: from the pool, the emitter's data and the emitter, no car, np
// particles on its tail, and the group on the system's head.
static void make_group(void)
{
    AcidEffectSystem *s = sys_tok();
    AcidEmitter *e = (AcidEmitter *)ref(tok());
    int np = itok(), i;
    AcidActiveGroup *g = (AcidActiveGroup *)bSlotOMalloc(AcidActiveGroupSlotPool);

    if (g == NULL)
        return;
    g->EmitterData = e != NULL ? e->EmitterData : NULL;
    g->Emitter = e;
    g->pCar = NULL;
    g->ParticleList.next = &g->ParticleList;
    g->ParticleList.prev = &g->ParticleList;
    for (i = 0; i < np; i++) {
        bNode *p = (bNode *)bSlotOMalloc(AcidParticleSlotPool);

        if (p == NULL)
            break;
        add_tail(&g->ParticleList, p);
    }
    add_head(&s->ActiveGroupList, &g->Node);
}

// ------------------------------------------------------------------ main

int main(int argc, char **argv)
{
    static char line[4096];
    FILE *fp;
    long len;
    int i;

    if (argc != 3) {
        fprintf(stderr, "usage: afx_test SCRIPT RECORDS\n");
        return 2;
    }
    memset(&PATPTR, PATB, sizeof PATPTR);
    eMathInit();
    gAcidGameFlowStateFn = flow_state;
    gEAttachDirectDataFn = attach_direct_data;
    fp = fopen(argv[2], "rb");
    if (!fp) {
        perror(argv[2]);
        return 2;
    }
    fseek(fp, 0, SEEK_END);
    len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    recs = (uint8_t *)malloc((size_t)len);
    if (fread(recs, 1, (size_t)len, fp) != (size_t)len) {
        fprintf(stderr, "short records\n");
        return 2;
    }
    fclose(fp);
    memcpy(&ndisc_data, recs, 4);
    memcpy(&ndisc_emit, recs + 4, 4);
    for (i = 0; i < NPOOL; i++) {
        arena[i] = (uint8_t *)malloc(kHostSize[i] * (size_t)kSlots[i]);
        used[i] = (uint8_t *)malloc((size_t)kSlots[i]);
        pools[i].debugName = kPoolNames[i];
    }
    for (i = 0; i < NBUF; i++) {
        uint8_t *m = (uint8_t *)malloc(BUFSZ + 16);

        bufs[i].mem = (uint8_t *)(((uintptr_t)m + 15u) & ~(uintptr_t)15u);
    }

    fp = fopen(argv[1], "r");
    if (!fp) {
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

        if (!strcmp(t, "D")) {
            dump_all();
            continue;
        } else if (!strcmp(t, "DL")) {
            char tag[8];
            int k = itok();

            snprintf(tag, sizeof tag, "L%d", k);
            pemitters(tag, &lists[k], 1);
            continue;
        } else if (!strcmp(t, "DE")) {
            AcidEmitter *e = (AcidEmitter *)ref(tok());

            if (e == NULL) {
                printf("  (none)\n");
            } else {
                printf(" ");
                pemit_full(e);
                printf("\n");
            }
            continue;
        } else if (!strcmp(t, "BR")) {
            Buf *b = &bufs[itok()];

            b->n = 0;
            b->at = b->mem;
            continue;
        } else if (!strcmp(t, "CH")) {
            op_chunk();
            continue;
        } else if (!strcmp(t, "S")) {
            acid_static_init();
        } else if (!strcmp(t, "I")) {
            afx_init();
        } else if (!strcmp(t, "C")) {
            afx_close();
        } else if (!strcmp(t, "L") || !strcmp(t, "U")) {
            Buf *b = &bufs[itok()];
            int c = itok();
            int r = t[0] == 'L' ? loader_acid_fx(b->ch[c])
                                : unloader_acid_fx(b->ch[c]);

            printf("  -> %d\n", r);
        } else if (!strcmp(t, "LA")) {
            Buf *b = &bufs[itok()];

            for (i = 0; i < b->n; i++)
                printf("  -> %d\n", loader_acid_fx(b->ch[i]));
        } else if (!strcmp(t, "UA")) {
            Buf *b = &bufs[itok()];

            for (i = b->n - 1; i >= 0; i--)
                printf("  -> %d\n", unloader_acid_fx(b->ch[i]));
        } else if (!strcmp(t, "T")) {
            afx_update_textures();
        } else if (!strcmp(t, "TXM")) {
            txm_hash[ntxm] = xtok();
            txm_mode[ntxm++] = itok();
        } else if (!strcmp(t, "GD")) {
            uint32_t n = xtok(), g = xtok();
            AcidEmitterData *a = (AcidEmitterData *)ref(tok());

            reg = afx_get_emitter_data(n, g, a);
            printf("  -> %s\n", nm(reg));
        } else if (!strcmp(t, "GE")) {
            uint32_t n = xtok(), g = xtok();
            AcidEmitter *a = (AcidEmitter *)ref(tok());

            reg = afx_get_emitter(n, g, a);
            printf("  -> %s\n", nm(reg));
        } else if (!strcmp(t, "CP")) {
            AcidEmitter *e = (AcidEmitter *)ref(tok());

            if (e == NULL) {
                reg = NULL;
                printf("  (none)\n");
            } else {
                AcidEmitter *c = afx_copy_emitter(e);

                reg = c;
                printf("  ->");
                if (c != NULL)
                    pemit_full(c);
                else
                    printf(" null");
                printf("\n");
            }
        } else if (!strcmp(t, "NL")) {
            int k = itok();

            lists[k].next = &lists[k];
            lists[k].prev = &lists[k];
        } else if (!strcmp(t, "GS")) {
            int k = itok();

            afx_get_emitters(&lists[k], xtok());
        } else if (!strcmp(t, "DS")) {
            afx_delete_emitters(&lists[itok()]);
        } else if (!strcmp(t, "SD") || !strcmp(t, "SH")) {
            AcidEmitter *e = (AcidEmitter *)ref(tok());

            if (e == NULL) {
                printf("  (none)\n");
            } else if (t[1] == 'D') {
                AcidEmitterData *d = (AcidEmitterData *)ref(tok());

                printf("  -> %d\n", (int)acid_emitter_set_emitter_data(e, d));
            } else {
                printf("  -> %d\n",
                       (int)acid_emitter_set_emitter_data_hash(e, xtok()));
            }
        } else if (!strcmp(t, "AA") || !strcmp(t, "RA")) {
            AcidEffectSystem *s = sys_tok();
            AcidEmitter *e = (AcidEmitter *)ref(tok());

            if (t[0] == 'R')
                reg = e;
            if (e == NULL)
                printf("  (none)\n");
            else if (t[0] == 'A')
                acid_system_add_auto_emitter(s, e);
            else
                acid_system_remove_auto_emitter(s, e);
        } else if (!strcmp(t, "K")) {
            acid_system_kill_all_active_effects(sys_tok());
        } else if (!strcmp(t, "MG")) {
            make_group();
        } else if (!strcmp(t, "ED") || !strcmp(t, "ED2")) {
            AcidEmitter *e = (AcidEmitter *)ref(tok());
            int f = itok();

            if (e == NULL)
                printf("  (none)\n");
            else
                acid_emitter_delete(e, f);
        } else if (!strcmp(t, "GX")) {
            AcidActiveGroup *g = (AcidActiveGroup *)ref(tok());
            int f = itok();

            if (g == NULL)
                printf("  (none)\n");
            else
                acid_active_group_delete(g, f);
        } else if (!strcmp(t, "CT")) {
            AcidEffectSystem *s = sys_tok();

            memset(s, PATB, sizeof *s);
            acid_system_construct(s);
            psystem(s == &FrameEffects ? "FE" : "WE", s);
        } else if (!strcmp(t, "PE")) {
            AcidEmitter *e = (AcidEmitter *)ref(tok());
            const char *f = tok();

            if (e == NULL)
                printf("  (none)\n");
            else
                set_field_e(e, f);
            continue;
        } else if (!strcmp(t, "PD")) {
            AcidEmitterData *d = (AcidEmitterData *)ref(tok());
            const char *f = tok();

            if (d == NULL)
                printf("  (none)\n");
            else
                set_field_d(d, f);
            continue;
        } else if (!strcmp(t, "CAM")) {
            int v = itok();
            const char *a = tok();

            if (!strcmp(a, "null")) {
                views[v].pCamera = NULL;
            } else {
                uint32_t w[4];
                int k;

                w[0] = (uint32_t)strtoul(a, NULL, 16);
                for (k = 1; k < 4; k++)
                    w[k] = xtok();
                memcpy(&cams[v].CurrentKey.Position, w, 16);
                views[v].pCamera = &cams[v];
            }
            continue;
        } else if (!strcmp(t, "CV")) {
            Car *c = &cars[itok()];

            c->State.Velocity.x = ftok();
            c->State.Velocity.y = ftok();
            c->State.Velocity.z = ftok();
            continue;
        } else if (!strcmp(t, "FS")) {
            flow = itok();
            continue;
        } else if (!strcmp(t, "VW")) {
            int v = itok();

            views[v].ID = itok();
            continue;
        } else if (!strcmp(t, "VM")) {
            int v = itok(), k = itok(), j;
            uint32_t w[16];

            for (j = 0; j < 16; j++)
                w[j] = xtok();
            memcpy(&mats[v][k], w, sizeof w);
            continue;
        } else if (!strcmp(t, "VC")) {
            int v = itok();

            cams[v].CurrentKey.FieldOfView = (uint16_t)xtok();
            cams[v].CarNotToRender = ref(tok());
            cams[v].RenderDash = itok();
            views[v].pCamera = &cams[v];
            continue;
        } else if (!strcmp(t, "CB")) {
            Car *c = &cars[itok()];

            c->TheOverrideRenderingPosition.VisibleViewBits = xtok();
            continue;
        } else if (!strcmp(t, "OS")) {
            AcidEffectSystem *s = sys_tok();

            s->OnlyShowCurrentEmitter = (uint8_t)xtok();
            s->CurrentEmitter = (AcidEmitter *)ref(tok());
            continue;
        } else if (!strcmp(t, "FB")) {
            CurrentBufferPos = frame_at(itok());
            CurrentBufferEnd = frame_at(itok());
            continue;
        } else if (!strcmp(t, "FF")) {
            FrameMallocFailed = itok();
            FrameMallocFailAmount = xtok();
            continue;
        } else if (!strcmp(t, "AZ")) {
            acidz = itok();
            continue;
        } else if (!strcmp(t, "H")) {
            hval = xtok();
            continue;
        } else if (!strcmp(t, "PP")) {
            AcidParticle *pa = (AcidParticle *)ref(tok());
            const char *f = tok();

            set_tail(&pa->Life, 8, f);
            continue;
        } else if (!strcmp(t, "RE")) {
            AcidEffectSystem *s = sys_tok();
            int v = itok();

            acid_system_render_effects(s, &views[v]);
            printf("  re nv %d rt %s pos %+ld fail %d %08x\n",
                   (int)s->NumVisibleParticles, fx(s->RenderTime),
                   (long)(CurrentBufferPos - frame), (int)FrameMallocFailed,
                   (unsigned)FrameMallocFailAmount);
        } else if (!strcmp(t, "DP")) {
            AcidEffectSystem *s = sys_tok();

            pparticles(s == &FrameEffects ? "FE" : "WE", s);
            continue;
        } else if (!strcmp(t, "DD")) {
            AcidEmitterData *d = (AcidEmitterData *)ref(tok());

            if (d == NULL)
                printf("  (none)\n");
            else
                pbases(d);
            continue;
        } else if (!strcmp(t, "UIP")) {
            AcidEffectSystem *s = sys_tok();

            acid_system_update_interest_points(s);
            pip(s == &FrameEffects ? "FE" : "WE", s);
        } else if (!strcmp(t, "TR")) {
            AcidEffectSystem *s = sys_tok();
            AcidEmitter *e = (AcidEmitter *)ref(tok());
            float dt = ftok();
            void *car = ref(tok());

            if (e == NULL) {
                printf("  (none)\n");
            } else {
                acid_system_trigger_emitter(s, e, dt, car);
                printf("  em");
                pemit_short(e);
                printf("\n");
            }
        } else if (!strcmp(t, "DT")) {
            AcidEffectSystem *s = sys_tok();

            acid_system_do_time_step(s, ftok());
            printf("  ut %s\n", fx(s->UpdateTime));
        } else if (!strcmp(t, "SEED")) {
            AcidRandomSeed = xtok();
            continue;
        } else if (!strcmp(t, "F")) {
            int p = pool_tok();

            fail_after[p] = itok();
            continue;
        } else if (!strcmp(t, "PF")) {
            int p = pool_tok();

            pools[p].flags = xtok();
            continue;
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
        pshort();
    }
    fclose(fp);
    return 0;
}
