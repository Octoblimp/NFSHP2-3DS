// Host harness for 3DS Files/source/zonepreview.c, the preview zone's
// camera. Runs the op script tools/zonepreview_check.py writes and prints
// the transcript it diffs against the retail image, run in mipsemu over the
// same script.
//
// The harness owns what the mover reads and calls outside its own files:
// the route, the players, the camera keys, the clocks, SoundEnabled, the race
// coordinator, and printing stand-ins for bMalloc (a patterned arena), bFree,
// the TopologyCoordinate calls, the radial blur, Player::UpdateZoneSound,
// PreviewRoute's constructor and destructor, and the three pieces checked on
// their own: PreviewRoute::MakeSplines and the stops (which fill the splines
// and the stops from the script) and PreviewComet. ConstrainToTopology
// answers from a scripted list, as the model's stub does.
//
// Every camera, mover and block is filled with 0xa5 before the script sets
// it, so a field the port leaves alone and retail writes (or the other way
// round) shows. A float prints as its bits, every NaN as "nan", and a
// pointer by what it points at. The topology stand-ins print their vectors
// without the pad lanes, which retail leaves to the stack in Update.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "average.h"
#include "banim.h"
#include "bmath.h"
#include "bmem.h"
#include "camera.h"
#include "cammover.h"
#include "eview.h"
#include "player.h"
#include "playerzone.h"
#include "previewcomet.h"
#include "previewroute.h"
#include "previewspline.h"
#include "previewstops.h"
#include "race.h"
#include "realdriver.h"
#include "realtime.h"
#include "spline.h"
#include "topology.h"
#include "zonecam.h"
#include "zonepreview.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

#define NCAM 2
#define NMOV 2
#define NPL 2
#define NARR 64
#define ARENA_SIZE 0x80000
#define NBLOCK 1024
#define MAXPTS 100

// What zonepreview.c and zonecam.c link against, the harness's own.
float WorldTimeElapsed = 1.0f / 30.0f;
float RealTimeElapsed = 1.0f / 30.0f;
int32_t SoundEnabled = 1;
void (*gRadialBlurOnFn)(int32_t view);
void (*gRadialBlurOffFn)(int32_t view);
void (*gRadialBlurAlphaFn)(int32_t view, float from, float to);

// The comet's parameters are previewcomet.c's; here only its address
// matters.
PreviewCometParams ZonePreviewCometParams;

static Camera cams[NCAM];
static ZonePreviewCameraMover movs[NMOV];
static struct Player players[NPL];
static PreviewRoute route;
static char route_pos[16];
static char route_points[16];
static char car_mem[16];
static struct Car *car_token;
static Spline spl;
static bVector3 arr[NARR];
static bVector3 gv[4];
static TopologyCoordinate gtc;
static int32_t coordinator[4];
static const void *local_tc;

static unsigned char arena[ARENA_SIZE] __attribute__((aligned(16)));
static size_t arena_used;
static void *blocks[NBLOCK];
static int nblocks;

static struct { int r; uint32_t d[3]; } cons[64];
static int ncons, icons;

// What the stand-ins hand out: the four splines' points (look, eye out,
// eye back, look ahead), the stops, and the route constructor's answer.
static bVector3 wpts[4][MAXPTS];
static int wn[4];
static uint32_t wstops[4];
static int rc_points, rc_n;

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
    if (p == &ZonePreviewCameraMoverVtbl)
        return "zone";
    if (p == &ZonePreviewCometParams)
        return "cparams";
    if (p == &route)
        return "route";
    if (p == route_pos)
        return "rpos";
    if (p == route_points)
        return "rpts";
    if (p == car_token)
        return "car";
    if (p == &spl)
        return "spl";
    if (p == arr)
        return "arr";
    if (p == &gtc)
        return "tc";
    if (p != NULL && p == local_tc)
        return "ltc";
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
        const ZonePreviewCameraMover *o = &movs[i];
        static const char *const part[] = {"look", "ahead", "eyef", "eyeb"};
        const Spline *s[4];
        int k;

        s[0] = &o->LookSpline;
        s[1] = &o->LookAheadSpline;
        s[2] = &o->EyeForwardSpline;
        s[3] = &o->EyeBackwardSpline;
        if (p == o) {
            sprintf(b, "o%d", i);
            return b;
        }
        if (p == &o->Topology) {
            sprintf(b, "o%d.tc", i);
            return b;
        }
        if (p == &o->Comet) {
            sprintf(b, "o%d.comet", i);
            return b;
        }
        if (p == &o->EyeParameter) {
            sprintf(b, "o%d.ep", i);
            return b;
        }
        if (p == &o->LookParameter) {
            sprintf(b, "o%d.lp", i);
            return b;
        }
        if (p == o->fStops) {
            sprintf(b, "o%d.stops", i);
            return b;
        }
        for (k = 0; k < 4; k++) {
            if (p == s[k]) {
                sprintf(b, "o%d.%s", i, part[k]);
                return b;
            }
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
    // A PreviewRoute is 24 bytes on the handheld; the host's pointers make
    // it bigger, and nothing else here is that size.
    if (size == (int)sizeof(PreviewRoute))
        size = 24;
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
    if (!strncmp(nm(tc), "?", 1))
        local_tc = tc;
    printf("  topo init %s\n", nm(tc));
}

void topology_destroy(TopologyCoordinate *tc)
{
    printf("  topo destroy %s\n", nm(tc));
    if (tc == local_tc)
        local_tc = NULL;
}

void topology_set_interest_bbox3(TopologyCoordinate *tc, const bVector3 *pos,
                                 float r, const bVector3 *vel)
{
    printf("  bbox %s pos %s r %s vel %s\n", nm(tc), v3(pos), fx(r),
           vel != NULL ? v3(vel) : "null");
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

// zonecam.c's other callees, which these scripts never reach.
float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    (void)terrain;
    (void)normal;
    (void)found;
    printf("  elev %s pt %s\n", nm(tc), v3(pt));
    return 0.0f;
}

static void blur_on(int32_t view)
{
    printf("  blur on %d\n", (int)view);
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

PreviewRoute *preview_route_init(PreviewRoute *pr, struct Car *car,
                                 float radius, float length)
{
    printf("  route init %s car %s r %s len %s -> %s %d\n", nm(pr), nm(car),
           fx(radius), fx(length), rc_points ? "rpts" : "null", rc_n);
    pr->pPoints = rc_points ? (PreviewRoutePoint *)(void *)route_points
                            : NULL;
    pr->nPoints = rc_n;
    return pr;
}

void preview_route_destroy(PreviewRoute *pr, int32_t flags)
{
    printf("  route destroy %s %d\n", nm(pr), (int)flags);
}

// The splines the stand-ins fill: the points written straight into the
// spline's own buffer, the count, and Dirty, as AddControlPoint leaves it.
static void fill_spline(Spline *s, int k)
{
    int i;

    for (i = 0; i < wn[k]; i++)
        s->pControlPoints[i] = wpts[k][i];
    s->NumControlPoints = wn[k];
    s->Dirty = 1;
}

void preview_route_make_splines(PreviewRoute *r, TopologyCoordinate *tc,
                                Spline *look, Spline *eyeFwd,
                                Spline *eyeBack, const Linear *eyeParam)
{
    printf("  mksplines %s %s %s %s %s %s\n", nm(r), nm(tc), nm(look),
           nm(eyeFwd), nm(eyeBack), nm(eyeParam));
    fill_spline(look, 0);
    fill_spline(eyeFwd, 1);
    fill_spline(eyeBack, 2);
}

int32_t preview_route_find_stops(PreviewRoute *r, TopologyCoordinate *tc,
                                 Spline *eyeFwd, Spline *look, Spline *ahead,
                                 const Linear *eyeParam,
                                 const Linear *lookParam,
                                 float *stops, int32_t n)
{
    int i;

    printf("  stops %s %s %s %s %s %s %s %s %d\n", nm(r), nm(tc), nm(eyeFwd),
           nm(look), nm(ahead), nm(eyeParam), nm(lookParam), nm(stops),
           (int)n);
    fill_spline(ahead, 3);
    for (i = 0; i < 4; i++)
        stops[i] = from_bits(wstops[i]);
    return 4;
}

void preview_comet_init(PreviewComet *c, Spline *s, PreviewCometParams *p)
{
    printf("  comet init %s %s %s\n", nm(c), nm(s), nm(p));
}

void preview_comet_destroy(PreviewComet *c)
{
    printf("  comet destroy %s\n", nm(c));
}

void preview_comet_enable(PreviewComet *c)
{
    printf("  comet enable %s\n", nm(c));
}

void preview_comet_disable(PreviewComet *c)
{
    printf("  comet disable %s\n", nm(c));
}

void preview_comet_render(PreviewComet *c, eView *view, float t)
{
    printf("  comet render %s %s %s\n", nm(c), nm(view), fx(t));
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

static void pspline(const char *tag, const Spline *s, int points)
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
    if (points && block_index(s->pControlPoints) >= 0
        && s->NumControlPoints > 0 && s->NumControlPoints <= MAXPTS) {
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

// `full` 0: the fields and the blends Update can be in; 1: every blend
// and the splines with their points; 2: the fields alone.
static void pmov(int j, int full)
{
    const ZonePreviewCameraMover *o = &movs[j];
    const CameraMover *m = &o->base;

    printf("  o%d type %d view %d en %d pview %s pcam %s player %s"
           " carnot %08lx dash %08lx vtbl %s next %s prev %s\n",
           j, (int)m->Type, m->ViewID, m->Enabled, nm(m->pView),
           nm(m->pCamera), nm(m->pPlayer),
           (unsigned long)(uint32_t)(uintptr_t)m->CarNotToRender,
           (unsigned long)(uint32_t)m->RenderDash, nm(m->vtbl),
           nm(m->Node.next), nm(m->Node.prev));
    printf("    ft %s tan %s out %s back %s hold %s stops %s %s %s %s\n",
           fx(o->fTime), fx(o->fTanFov), fx(o->fOutTime), fx(o->fBackTime),
           fx(o->fHoldTime), fx(o->fStops[0]), fx(o->fStops[1]),
           fx(o->fStops[2]), fx(o->fStops[3]));
    printf("    ei %s li %s em %s lm %s eo %s lo %s fp %s\n",
           nm(o->pEyeBlendIn), nm(o->pLookBlendIn), nm(o->pEyeBlendMid),
           nm(o->pLookBlendMid), nm(o->pEyeBlendOut), nm(o->pLookBlendOut),
           nm(o->pFocusPull));
    printf("    ep %s %s lp %s %s", fx(o->EyeParameter.m),
           fx(o->EyeParameter.b), fx(o->LookParameter.m),
           fx(o->LookParameter.b));
    pvec("ae", &o->vAnchorEye);
    pvec("al", &o->vAnchorLook);
    printf("\n");
    if (full == 2)
        return;
    if (full || o->fTime < 0.25f)
        pblend("ei", o->pEyeBlendIn), pblend("li", o->pLookBlendIn);
    pblend("em", o->pEyeBlendMid);
    pblend("lm", o->pLookBlendMid);
    pblend("eo", o->pEyeBlendOut);
    pblend("lo", o->pLookBlendOut);
    if (block_index(o->pFocusPull) >= 0)
        pcubic("fp", o->pFocusPull);
    if (full) {
        pspline("look", &o->LookSpline, 1);
        pspline("ahead", &o->LookAheadSpline, 1);
        pspline("eyef", &o->EyeForwardSpline, 1);
        pspline("eyeb", &o->EyeBackwardSpline, 1);
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
    memset(players, 0xa5, sizeof players);
    memset(&route, 0xa5, sizeof route);
    memset(&spl, 0xa5, sizeof spl);
    memset(arr, 0xa5, sizeof arr);
    memset(gv, 0xa5, sizeof gv);
    memset(arena, 0xa5, sizeof arena);
    arena_used = 0;
    nblocks = 0;
    local_tc = NULL;
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
    memset(cons, 0, sizeof cons);
    ncons = 1;
    icons = 0;
    memset(wn, 0, sizeof wn);
    memset(wstops, 0, sizeof wstops);
    rc_points = 0;
    rc_n = 0;
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

// The next Update's look parameter, from the step it is about to take
// (`which` n) or from where it is (o), or the run out's first or last (0,
// 1): a stop placed exactly there.
static void stop_at(int j, int i, const char *which)
{
    ZonePreviewCameraMover *o = &movs[j];
    float t = o->fTime;
    float last, u;

    if (!strcmp(which, "0") || !strcmp(which, "1")) {
        u = (float)atoi(which);
    } else {
        if (!strcmp(which, "n"))
            t = t + RealTimeElapsed;
        u = (t - 0.25f) / o->fOutTime;
    }
    last = (float)(o->LookSpline.NumControlPoints - 1);
    o->fStops[i] = linear_get_value(&o->LookParameter, u) * last;
}

static void length_op(void)
{
    int i;
    float r;

    memset(&spl, 0xa5, sizeof spl);
    spl.Type = (SplineType)itok();
    spl.NumControlPoints = itok();
    spl.Dirty = itok();
    spl.Length = ftok();
    spl.pControlPoints = arr;
    for (i = 0; i < spl.NumControlPoints && i < NARR; i++)
        read_vec(&arr[i]);
    r = spline_linear_estimate_length(&spl);
    printf("  length %s dirty %08lx len %s\n", fx(r),
           (unsigned long)(uint32_t)spl.Dirty, fx(spl.Length));
}

static void ensure_op(void)
{
    int i;

    for (i = 0; i < 4; i++)
        read_vec(&gv[i]);
    zone_ensure_topology(&gtc, &gv[0], &gv[1], &gv[2], &gv[3]);
    printf("  ensured");
    for (i = 0; i < 4; i++)
        pvec("v", &gv[i]);
    printf("\n");
}

int main(int argc, char **argv)
{
    static char line[16384];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: zonepreview_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    gRadialBlurOnFn = blur_on;
    gRadialBlurOffFn = blur_off;
    gRadialBlurAlphaFn = blur_alpha;
    car_token = (struct Car *)(void *)car_mem;

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
        if (strchr("JWX", t[0]) == NULL || t[1])
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
        } else if (!strcmp(t, "L")) {
            int i = itok();

            players[i].PlayerNumber = itok();
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
        } else if (!strcmp(t, "W")) {
            int k = itok(), i;

            wn[k] = itok();
            for (i = 0; i < wn[k]; i++)
                read_vec(&wpts[k][i]);
        } else if (!strcmp(t, "H")) {
            int i;

            for (i = 0; i < 4; i++)
                wstops[i] = xtok();
        } else if (!strcmp(t, "N")) {
            route.fDistance = ftok();
        } else if (!strcmp(t, "I")) {
            rc_points = itok();
            rc_n = itok();
        } else if (!strcmp(t, "O")) {
            int j = itok(), view = itok();

            memset(&movs[j], 0xa5, sizeof movs[j]);
            zone_preview_camera_mover_init(&movs[j], view, &route,
                                           (bVector3 *)(void *)route_pos);
            pmov(j, 1);
            pviews();
            pcam(movs[j].base.pCamera);
        } else if (!strcmp(t, "R")) {
            int j = itok(), p = itok();

            movs[j].base.pPlayer = p < 0 ? NULL : &players[p];
        } else if (!strcmp(t, "U")) {
            int j = itok();

            movs[j].base.vtbl->Update(&movs[j].base);
            pmov(j, 0);
            pcam(movs[j].base.pCamera);
        } else if (!strcmp(t, "D")) {
            int j = itok();
            Camera *c = movs[j].base.pCamera;

            movs[j].base.vtbl->Destroy(&movs[j].base);
            pmov(j, 2);
            pviews();
            pcam(c);
        } else if (!strcmp(t, "E")) {
            int j = itok();

            movs[j].base.vtbl->Enable(&movs[j].base);
            pmov(j, 2);
            pviews();
            pcam(movs[j].base.pCamera);
        } else if (!strcmp(t, "e")) {
            int j = itok();

            movs[j].base.vtbl->Disable(&movs[j].base);
            pmov(j, 2);
            pviews();
            pcam(movs[j].base.pCamera);
        } else if (!strcmp(t, "r")) {
            int j = itok(), v = itok();

            movs[j].base.vtbl->Render(&movs[j].base, &eViews[v]);
        } else if (!strcmp(t, "u")) {
            int j = itok();

            printf("  duration %s\n",
                   fx(zone_preview_duration_fn(&movs[j].base)));
        } else if (!strcmp(t, "v")) {
            int j = itok();
            int32_t r = zone_preview_violates_topology_fn(&movs[j].base);

            printf("  violates %d\n", (int)r);
            pspline("look", &movs[j].LookSpline, 0);
        } else if (!strcmp(t, "f")) {
            PreviewRoute *r = zone_preview_find_route(car_token);

            printf("  found %s\n", nm(r));
        } else if (!strcmp(t, "F")) {
            ZonePreviewCameraMover *o = &movs[itok()];
            const char *f = tok();

            if (!strcmp(f, "ft"))
                o->fTime = ftok();
            else if (!strcmp(f, "fh"))
                o->fHoldTime = ftok();
            else if (!strcmp(f, "fv"))
                o->pFocusPull->val = ftok();
            else
                o->fStops[f[1] - '0'] = ftok();
        } else if (!strcmp(t, "S")) {
            int j = itok(), i = itok();

            stop_at(j, i, tok());
        } else if (!strcmp(t, "G")) {
            query(itok());
        } else if (!strcmp(t, "l")) {
            length_op();
        } else if (!strcmp(t, "g")) {
            ensure_op();
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
