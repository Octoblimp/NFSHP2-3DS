// scenerycull_test -- the harness tools/scenerycull_check.py runs against
// the cull half of Scenery.obj's port, 3DS Files/source/scenerycull.c, with
// the frame malloc (eframe.c) and the eView table (eview.c).
//
// It reads a script of hex words from argv[1], one op and its operands at a
// time (the checker has the list), and prints what the model prints. No
// address is printed:
//
//   #n     the nth made-up eModel
//   D[i]   the ith entry of SceneryDrawInfoTable
//   B0+o   o bytes into the first frame buffer bMalloc handed out, B1+o
//          the second
//   I      eMathIdentityMatrix
//   L<n>   the nth made-up light context
//   ?      anything else
//
// The sections are built here straight from the script, not through the
// loader, which scenery_check has already checked: a header, its kinds,
// its objects and its tree, the tree followed by two zeroed nodes that a
// child count past five or a code one past the last node reads.

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bslotpool.h"
#include "eframe.h"
#include "emath.h"
#include "eview.h"
#include "race.h"
#include "scenery.h"
#include "scenerycull.h"

enum {
    OP_TAG = 1, OP_SECTION, OP_UNSECTION, OP_ZONE, OP_ZCLEAR, OP_VIEW,
    OP_CI, OP_NUMCI, OP_CLASSIFY, OP_BBVIS, OP_ISVIS, OP_DRAW, OP_BRUTE,
    OP_TREE, OP_RECURSE, OP_WHAT, OP_CULLVIEW, OP_BATCH, OP_DOCULL,
    OP_STUFF, OP_SETUP, OP_SETUPVIEWS, OP_MODE, OP_DIR, OP_ENV, OP_FALLOC,
    OP_FSWAP, OP_FFREE, OP_FSIZE, OP_FSET, OP_CURZONE, OP_DUMPG,
};

#define NSECT   160
#define NMODEL  8192
#define NZONE   64
#define NLIGHT  16
#define GUARD   2

static FILE *script;

typedef struct Section {
    ScenerySectionHeader h;
    SceneryInfo     *kinds;
    SceneryInstance *inst;
    SceneryTreeNode *tree;
    int              ntree;
} Section;

static Section  sects[NSECT];
static eModel   models[NMODEL];
static VisibleZone zones[NZONE];
static int      nzones;
static Camera   cams[EVIEW_NUM_VIEWS];
static eRenderTarget rts[EVIEW_NUM_VIEWS];
static bMatrix4 wvs[EVIEW_NUM_VIEWS], clips[EVIEW_NUM_VIEWS];
static uint8_t  lights[NLIGHT * 16];
static GrandSceneryCullInfo grand;

static uint8_t *bufs[2];
static uint32_t buf_size[2];
static int      nbufs;

// ---------------------------------------------------------------- output

static void out(const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
}

static uint32_t fb(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

static uint32_t fx(float f)
{
    uint32_t b = fb(f);

    if ((b & 0x7f800000u) == 0x7f800000u && (b & 0x007fffffu))
        return 0x7fc00000u;
    return b;
}

static char namebuf[8][48];
static int  nameslot;

static const char *name_of(const void *vp)
{
    uintptr_t p = (uintptr_t)vp;
    char *s = namebuf[nameslot++ & 7];
    int k;

    if (p == 0)
        return "null";
    if (vp == &eMathIdentityMatrix)
        return "I";
    if (p >= (uintptr_t)models && p < (uintptr_t)(models + NMODEL)) {
        uintptr_t o = p - (uintptr_t)models;

        if (o % sizeof(eModel) == 0)
            sprintf(s, "#%d", (int)(o / sizeof(eModel)));
        else
            sprintf(s, "#%d+%d", (int)(o / sizeof(eModel)),
                    (int)(o % sizeof(eModel)));
        return s;
    }
    if (p >= (uintptr_t)SceneryDrawInfoTable
        && p <= (uintptr_t)(SceneryDrawInfoTable + SCENERY_MAX_DRAW_INFOS)) {
        uintptr_t o = p - (uintptr_t)SceneryDrawInfoTable;

        sprintf(s, "D[%d]", (int)(o / sizeof(SceneryDrawInfo)));
        return s;
    }
    for (k = 0; k < nbufs && k < 2; k++) {
        if (bufs[k] != NULL && p >= (uintptr_t)bufs[k]
            && p <= (uintptr_t)bufs[k] + buf_size[k] + 64) {
            sprintf(s, "B%d+%d", k, (int)(p - (uintptr_t)bufs[k]));
            return s;
        }
    }
    if (p >= (uintptr_t)lights && p < (uintptr_t)lights + sizeof lights) {
        sprintf(s, "L%d", (int)((p - (uintptr_t)lights) / 16));
        return s;
    }
    return "?";
}

static void dump_matrix(const char *label, const bMatrix4 *m)
{
    const float *f = (const float *)(const void *)m;
    int j;

    out("   %s", label);
    for (j = 0; j < 16; j++)
        out(" %08x", fx(f[j]));
    out("\n");
}

static void dump_draw(const SceneryDrawInfo *d)
{
    uintptr_t p = (uintptr_t)d->pModel;

    out("  %s %s/%d %s\n", name_of(d), name_of((void *)(p & ~(uintptr_t)3)),
        (int)(p & 3), name_of(d->pMatrix));
    if (d->pMatrix != NULL && d->pMatrix != &eMathIdentityMatrix)
        dump_matrix("m", d->pMatrix);
}

static void dump_frame(void)
{
    out("  frame pos %s end %s failed %d amount %u max %u alloc %d\n",
        name_of(CurrentBufferPos), name_of(CurrentBufferEnd),
        FrameMallocFailed, FrameMallocFailAmount, FrameMallocMaxFailAmount,
        FrameMallocAllocNum);
}

static void dump_zones(void)
{
    bNode *n;

    out("  zones:");
    for (n = VisibleZoneList.next; n != &VisibleZoneList; n = n->next)
        out(" %d", ((VisibleZone *)(void *)n)->ZoneNumber);
    out(" current %d\n", CurrentZoneNumber);
}

static void dump_views_visible(void)
{
    int k;

    out("  views visible:");
    for (k = 0; k < NSECT; k++) {
        if (sects[k].h.ViewsVisibleThisFrame != 0)
            out(" %d:%x", k, sects[k].h.ViewsVisibleThisFrame);
    }
    out("\n");
}

static void dump_ci_head(int i)
{
    const SceneryCullInfo *ci = &grand.SceneryCullInfos[i];

    out("  ci %d view %d flags %x first %s current %s top %s\n", i,
        ci->pView != NULL ? (int)(ci->pView - eViews) : -1,
        (unsigned)ci->ExcludeFlags, name_of(ci->pFirstDrawInfo),
        name_of(ci->pCurrentDrawInfo), name_of(ci->pTopDrawInfo));
}

static void dump_ci_full(int i)
{
    const SceneryCullInfo *ci = &grand.SceneryCullInfos[i];
    const float *p = (const float *)(const void *)&ci->Position;
    const float *d = (const float *)(const void *)&ci->Direction;

    dump_ci_head(i);
    dump_matrix("facade", &ci->FacadeMatrix);
    dump_matrix("clip", &ci->ClipMatrix);
    out("   pos %08x %08x %08x %08x dir %08x %08x %08x %08x h %08x\n",
        fx(p[0]), fx(p[1]), fx(p[2]), fx(p[3]),
        fx(d[0]), fx(d[1]), fx(d[2]), fx(d[3]), fx(ci->H));
}

// ---------------------------------------------------------------- script

static uint32_t next(void)
{
    unsigned int w;

    if (fscanf(script, "%x", &w) != 1) {
        fprintf(stderr, "script ends inside an op\n");
        exit(2);
    }
    return (uint32_t)w;
}

static float nextf(void)
{
    uint32_t b = next();
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static void next_vec4(void *v)
{
    float *f = (float *)v;
    int j;

    for (j = 0; j < 4; j++)
        f[j] = nextf();
}

static void next_matrix(bMatrix4 *m)
{
    float *f = (float *)(void *)m;
    int j;

    for (j = 0; j < 16; j++)
        f[j] = nextf();
}

static void next_bytes(void *dst, size_t n)
{
    uint8_t *d = (uint8_t *)dst;
    size_t i;

    for (i = 0; i < n; i += 4) {
        uint32_t w = next();
        size_t j;

        for (j = 0; j < 4 && i + j < n; j++)
            d[i + j] = (uint8_t)(w >> (8 * j));
    }
}

static void add_tail(bNode *head, bNode *n)
{
    n->prev = head->prev;
    n->next = head;
    head->prev->next = n;
    head->prev = n;
}

static void add_head(bNode *head, bNode *n)
{
    n->next = head->next;
    n->prev = head;
    head->next->prev = n;
    head->next = n;
}

static void unlink_node(bNode *n)
{
    n->prev->next = n->next;
    n->next->prev = n->prev;
}

// ---------------------------------------------------------------- the seams

static void f_render(eModel *m, bMatrix4 *matrix, void *light,
                     uint32_t flags)
{
    out("  render %s matrix %s light %s flags %u\n", name_of(m),
        name_of(matrix), name_of(light), flags);
}

static void *h_malloc(int size, const char *name, int flags, int pool)
{
    void *p = malloc((size_t)size + 64);

    out("  bMalloc %d %s %d %d -> B%d\n", size, name, flags, pool, nbufs);
    if (nbufs < 2) {
        bufs[nbufs] = (uint8_t *)p;
        buf_size[nbufs] = (uint32_t)size;
    }
    nbufs++;
    return p;
}

static void h_free(void *p)
{
    out("  bFree %s\n", name_of(p));
}

// scenery.c's loader makes its models from the slot pool. The cull never
// loads, so this is never reached.
void *bSlotOMalloc(BSlotPool *pool)
{
    (void)pool;
    fprintf(stderr, "bSlotOMalloc reached\n");
    exit(3);
}

// ---------------------------------------------------------------- the ops

static void op_section(void)
{
    uint32_t k = next(), sec = next(), head = next();
    uint32_t nk = next(), ni = next(), nt = next();
    Section *s = &sects[k];
    uint32_t i;
    int j;

    free(s->kinds);
    free(s->inst);
    free(s->tree);
    memset(s, 0, sizeof *s);
    s->kinds = (SceneryInfo *)calloc(nk + 1, sizeof(SceneryInfo));
    s->inst = (SceneryInstance *)calloc(ni + 1, sizeof(SceneryInstance));
    s->tree = (SceneryTreeNode *)calloc(nt + GUARD, sizeof(SceneryTreeNode));
    for (i = 0; i < nk; i++) {
        SceneryInfo *f = &s->kinds[i];
        uint32_t w;

        for (j = 0; j < 3; j++)
            f->NameHash[j] = next();
        w = next();
        f->FarClipSize[0] = (int16_t)(w & 0xffff);
        f->FarClipSize[1] = (int16_t)(w >> 16);
        w = next();
        f->FarClipSize[2] = (int16_t)(w & 0xffff);
        f->Dummy = (int16_t)(w >> 16);
        for (j = 0; j < 3; j++) {
            uint32_t m = next();

            f->pModel[j] = m == 0 ? NULL : &models[m];
        }
        w = next();
        f->IsFacadeFlag[0] = (uint8_t)w;
        f->IsFacadeFlag[1] = (uint8_t)(w >> 8);
        f->IsFacadeFlag[2] = (uint8_t)(w >> 16);
        f->Dummy2 = (uint8_t)(w >> 24);
        f->Radius = nextf();
    }
    for (i = 0; i < ni; i++)
        next_bytes(&s->inst[i], 48);
    for (i = 0; i < nt; i++)
        next_bytes(&s->tree[i], 24);
    s->ntree = (int)nt;
    s->h.SectionNumber = (int32_t)sec;
    s->h.pSceneryInfo = s->kinds;
    s->h.NumSceneryInfo = (int32_t)nk;
    s->h.pSceneryInstance = s->inst;
    s->h.NumSceneryInstances = (int32_t)ni;
    s->h.SceneryTreeNodeTable = nt != 0 ? s->tree : NULL;
    s->h.NumSceneryTreeNodes = (int32_t)nt;
    ScenerySectionHeaderTable[sec] = &s->h;
    if (head)
        add_head(&ScenerySectionHeaderList, &s->h.Node);
    else
        add_tail(&ScenerySectionHeaderList, &s->h.Node);
}

static void op_unsection(void)
{
    Section *s = &sects[next()];

    unlink_node(&s->h.Node);
    ScenerySectionHeaderTable[s->h.SectionNumber] = NULL;
}

static void op_zone(void)
{
    VisibleZone *z = &zones[nzones++];
    int j;

    memset(z, 0, sizeof *z);
    z->ZoneNumber = (int32_t)next();
    z->NumVisibleScenerySections = (int32_t)next();
    next_bytes(z->VisibleScenerySections, 128);
    z->NumPerimeterPoints = (int32_t)next();
    for (j = 0; j < 16; j++) {
        z->PerimeterPoints[j].x = nextf();
        z->PerimeterPoints[j].y = nextf();
    }
    add_tail(&VisibleZoneList, &z->Node);
}

static void op_view(void)
{
    uint32_t v = next();
    eView *e = &eViews[v];

    e->ID = (int32_t)next();
    e->Active = (uint8_t)next();
    rts[v].Active = next();
    e->pRenderTarget0 = &rts[v];
    e->H = nextf();
    e->WorldLightContext = &lights[16 * next()];
    next_vec4(&cams[v].CurrentKey.Position);
    next_vec4(&cams[v].CurrentKey.Direction);
    e->pCamera = &cams[v];
    next_matrix(&wvs[v]);
    next_matrix(&clips[v]);
    e->WorldViewMatrix = &wvs[v];
    e->WorldScreenClipMatrix = &clips[v];
}

static SceneryDrawInfo *draw_at(uint32_t i)
{
    return &SceneryDrawInfoTable[i];
}

static void op_ci(void)
{
    SceneryCullInfo *ci = &grand.SceneryCullInfos[next()];

    ci->pView = &eViews[next()];
    ci->ExcludeFlags = (int32_t)next();
    next_matrix(&ci->FacadeMatrix);
    next_matrix(&ci->ClipMatrix);
    next_vec4(&ci->Position);
    next_vec4(&ci->Direction);
    ci->H = nextf();
    ci->pFirstDrawInfo = draw_at(next());
    ci->pCurrentDrawInfo = draw_at(next());
    ci->pTopDrawInfo = draw_at(next());
}

static void dump_new_draws(SceneryCullInfo *ci, SceneryDrawInfo *from)
{
    SceneryDrawInfo *d;

    for (d = from; d < ci->pCurrentDrawInfo; d++)
        dump_draw(d);
}

static void dump_all(void)
{
    int i;

    out("  grand num %d first %s current %s top %s\n", grand.NumCullInfos,
        name_of(grand.pFirstDrawInfo), name_of(grand.pCurrentDrawInfo),
        name_of(grand.pTopDrawInfo));
    for (i = 0; i < grand.NumCullInfos && i < SCENERY_MAX_CULL_INFOS; i++) {
        SceneryCullInfo *ci = &grand.SceneryCullInfos[i];

        dump_ci_head(i);
        dump_new_draws(ci, ci->pFirstDrawInfo);
    }
    dump_frame();
    dump_zones();
    dump_views_visible();
}

static void run(void)
{
    uint32_t code;

    while (fscanf(script, "%x", &code) == 1) {
        switch (code) {
        case OP_TAG:
            out("[%u]\n", next());
            break;
        case OP_SECTION:
            op_section();
            break;
        case OP_UNSECTION:
            op_unsection();
            break;
        case OP_ZONE:
            op_zone();
            break;
        case OP_ZCLEAR:
            VisibleZoneList.next = VisibleZoneList.prev = &VisibleZoneList;
            nzones = 0;
            break;
        case OP_VIEW:
            op_view();
            break;
        case OP_CI:
            op_ci();
            break;
        case OP_NUMCI:
            grand.NumCullInfos = (int32_t)next();
            break;
        case OP_CLASSIFY: {
            bVector4 mn, mx;
            bMatrix4 m;

            next_vec4(&mn);
            next_vec4(&mx);
            next_matrix(&m);
            out("classify -> %d\n", scenery_classify_aabb(&mn, &mx, &m));
            break;
        }
        case OP_BBVIS: {
            bVector3 mn, mx;
            bMatrix4 m;

            next_vec4(&mn);
            next_vec4(&mx);
            next_matrix(&m);
            out("bbvis -> %d\n",
                scenery_is_bounding_box_visible(&mn, &mx, &m));
            break;
        }
        case OP_ISVIS: {
            uint32_t k = next(), c = next();

            out("isvis %u ci %u -> %d\n", k, c,
                scenery_is_visible(&sects[k].h, &grand.SceneryCullInfos[c]));
            break;
        }
        case OP_DRAW: {
            uint32_t k = next(), idx = next(), c = next(), cls = next();
            SceneryCullInfo *ci = &grand.SceneryCullInfos[c];
            SceneryDrawInfo *from = ci->pCurrentDrawInfo;

            out("draw %u %d ci %u cls %d\n", k, (int)idx, c, (int)cls);
            scenery_draw_a_scenery(&sects[k].h, (int32_t)idx, ci,
                                   (int32_t)cls);
            dump_ci_head((int)c);
            dump_new_draws(ci, from);
            dump_frame();
            break;
        }
        case OP_BRUTE:
        case OP_TREE: {
            uint32_t k = next(), c = next();
            SceneryCullInfo *ci = &grand.SceneryCullInfos[c];
            SceneryDrawInfo *from = ci->pCurrentDrawInfo;

            out("%s %u ci %u\n", code == OP_BRUTE ? "brute" : "tree", k, c);
            if (code == OP_BRUTE)
                scenery_cull_brute_force(&sects[k].h, ci);
            else
                scenery_tree_cull(&sects[k].h, ci);
            dump_ci_head((int)c);
            dump_new_draws(ci, from);
            dump_frame();
            break;
        }
        case OP_RECURSE: {
            uint32_t k = next(), node = next(), c = next(), cls = next();
            SceneryCullInfo *ci = &grand.SceneryCullInfos[c];
            SceneryDrawInfo *from = ci->pCurrentDrawInfo;

            out("recurse %u node %u ci %u cls %u\n", k, node, c, cls);
            scenery_cull_node_recursive(&sects[k].h, &sects[k].tree[node],
                                        ci, cls);
            dump_ci_head((int)c);
            dump_new_draws(ci, from);
            dump_frame();
            break;
        }
        case OP_WHAT: {
            uint32_t c = next(), max = next();
            int16_t secs[300];
            int32_t n, i;

            memset(secs, 0xa5, sizeof secs);
            n = scenery_what_sections_should_we_draw(
                &grand, secs, (int32_t)max, &grand.SceneryCullInfos[c]);
            out("what ci %u max %u -> %d:", c, max, n);
            for (i = 0; i < n && i < 300; i++)
                out(" %d", secs[i]);
            out("\n");
            dump_zones();
            break;
        }
        case OP_CULLVIEW: {
            uint32_t c = next();
            SceneryCullInfo *ci = &grand.SceneryCullInfos[c];
            SceneryDrawInfo *from = ci->pCurrentDrawInfo;

            out("cull view ci %u\n", c);
            scenery_cull_view(&grand, ci);
            dump_ci_head((int)c);
            dump_new_draws(ci, from);
            dump_frame();
            dump_zones();
            break;
        }
        case OP_BATCH:
            out("batch\n");
            scenery_batch_cull_views(&grand);
            dump_all();
            break;
        case OP_DOCULL:
            out("do culling\n");
            scenery_do_culling(&grand);
            dump_all();
            break;
        case OP_STUFF: {
            uint32_t v = next();

            out("stuff view %u\n", v);
            scenery_stuff_scenery(&grand, &eViews[v]);
            break;
        }
        case OP_SETUP: {
            uint32_t v = next(), c = next();

            out("setup view %u ci %u\n", v, c);
            scenery_setup_cull_info(&eViews[v], &grand.SceneryCullInfos[c]);
            dump_ci_full((int)c);
            break;
        }
        case OP_SETUPVIEWS: {
            uint32_t in_game = next();
            int i;

            out("setup views %u\n", in_game);
            scenery_cull_setup_views(&grand, (int32_t)in_game);
            out("  num %d\n", grand.NumCullInfos);
            for (i = 0; i < grand.NumCullInfos; i++)
                dump_ci_full(i);
            break;
        }
        case OP_MODE:
            CurrentViewMode = (int32_t)next();
            break;
        case OP_DIR:
            RaceParametersTrackDirection = (eTrackDirection)next();
            break;
        case OP_ENV:
            EnvironmentMappingEnable = (int32_t)next();
            break;
        case OP_FALLOC: {
            uint32_t size = next();

            out("allocate frame %u\n", size);
            nbufs = 0;
            eAllocateFrameMallocBuffers(size);
            out("  size %u buffers %s %s\n", FrameMemoryBufferSize,
                name_of(FrameMemoryBuffer[0]), name_of(FrameMemoryBuffer[1]));
            dump_frame();
            break;
        }
        case OP_FSWAP:
            out("swap frame\n");
            eSwapFrameMallocBuffers();
            out("  buffers %s %s used %d %d\n", name_of(FrameMemoryBuffer[0]),
                name_of(FrameMemoryBuffer[1]), FrameMemoryBufferAmountUsed[0],
                FrameMemoryBufferAmountUsed[1]);
            dump_frame();
            break;
        case OP_FFREE:
            out("free frame\n");
            eFreeFrameMallocBuffers();
            out("  size %u buffers %s %s\n", FrameMemoryBufferSize,
                name_of(FrameMemoryBuffer[0]), name_of(FrameMemoryBuffer[1]));
            dump_frame();
            nbufs = 0;
            break;
        case OP_FSIZE: {
            int32_t used = 0x5a5a5a5a;
            int32_t r = eGetSizeofFrameMallocBuffers(&used);

            out("frame size -> %d used %d\n", r, used);
            break;
        }
        case OP_FSET: {
            uint32_t pos = next(), end = next();

            CurrentBufferPos = FrameMemoryBuffer[0] + pos;
            CurrentBufferEnd = FrameMemoryBuffer[0] + end;
            FrameMallocFailed = (int32_t)next();
            FrameMallocFailAmount = next();
            FrameMallocMaxFailAmount = next();
            break;
        }
        case OP_CURZONE:
            CurrentZoneNumber = (int32_t)next();
            break;
        case OP_DUMPG:
            out("dump\n");
            dump_all();
            break;
        default:
            fprintf(stderr, "unknown op %u\n", code);
            exit(2);
        }
    }
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: scenerycull_test SCRIPT\n");
        return 2;
    }
    script = fopen(argv[1], "r");
    if (script == NULL) {
        perror(argv[1]);
        return 2;
    }
    setvbuf(stdout, NULL, _IOFBF, 1 << 16);
    eMathInit();
    scenery_static_init();
    gEModelRenderFn = f_render;
    bSetMemoryHooks(h_malloc, h_free);
    run();
    fflush(stdout);
    return 0;
}
