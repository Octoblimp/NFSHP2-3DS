// previewstops -- see previewstops.h.

#include "previewstops.h"

#include <math.h>
#include <string.h>

#include "bmem.h"
#include "car.h"
#include "chopper.h"
#include "collision.h"
#include "copmanager.h"
#include "eefpu.h"
#include "previewspline.h"
#include "race.h"
#include "trackroute.h"
#include "world.h"

// A point joins a stop within 20 of each of its points (0x00165880).
#define STOP_RADIUS          20.0f

// A roadblock's two cops' cars closer than 10 stop the camera halfway
// between them (0x00165d38).
#define STOP_ROADBLOCK_PAIR  10.0f

// A stop farther than 60 from the eye-forward spline where the camera
// sees it is dropped (0x001663c8).
#define STOP_MAX_DISTANCE    60.0f

// The cosine the camera sees a stop at, -0.6 (gp-30704), within 0.01
// (gp-30700): about 53 degrees off its way, ahead.
#define STOP_APPROACH_COS    -0.6f
#define STOP_APPROACH_TOL    0.01f

// DownSampleXY's fraction for the look-ahead spline, 0.3333 (gp-30696).
#define STOP_DOWNSAMPLE      0.3333f

// The cops seen: room for six (0x00165a10).
#define STOP_MAX_SEEN        6

// Linear::GetInverse's flat slope, 0.001 (gp-29944).
#define LINEAR_FLAT          0.001f

// The topology's test: one box below 30, else steps of at most 30, by
// 0.033333335 (gp-31332); SegmentIntersects's radius 0.5.
#define TOPO_SHORT           30.0f
#define TOPO_STEP_INV        0.033333335f
#define TOPO_RADIUS          0.5f

// The spline's last parameter, as the image works it out inline at every
// use: n for a loop, n - 1 for the two that end, else 0.
static float spline_last(const Spline *s)
{
    if (s->Type == SPLINE_LOOP)
        return (float)s->NumControlPoints;
    if (s->Type == SPLINE_CLAMP || s->Type == SPLINE_EXTRAPOLATE)
        return (float)(s->NumControlPoints - 1);
    return 0.0f;
}

// VU0's length of a-b over x, y and z: the squares summed x + y, then z.
static float dist3(const bVector3 *a, const bVector3 *b)
{
    float dx = a->x - b->x;
    float dy = a->y - b->y;
    float dz = a->z - b->z;

    return sqrtf((dx * dx + dy * dy) + dz * dz);
}

// (a + b) * 0.5, the four lanes.
static void halfway(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    o->x = (a->x + b->x) * 0.5f;
    o->y = (a->y + b->y) * 0.5f;
    o->z = (a->z + b->z) * 0.5f;
    o->pad = (a->pad + b->pad) * 0.5f;
}

static void list_init(bNode *list)
{
    list->next = list;
    list->prev = list;
}

// bTList::AddTail.
static void list_add_tail(bNode *list, bNode *n)
{
    bNode *last = list->prev;

    last->next = n;
    list->prev = n;
    n->next = list;
    n->prev = last;
}

static void list_remove(bNode *n)
{
    n->prev->next = n->next;
    n->next->prev = n->prev;
}

// ------------------------------------------------------------ the stops

// 0x001657a0: the mean of the stop's points, the sum times 1 over the
// count (at least 1). Retail starts the sum's fourth lane from a stack
// word; the port from 0.
static void pause_centre(const PreviewPause *p, bVector3 *out)
{
    bVector3 sum = { 0.0f, 0.0f, 0.0f, 0.0f };
    const bNode *n;
    int32_t count = 0;
    float k;

    for (n = p->Points.next; n != &p->Points; n = n->next) {
        const bVector3 *v = &((const PreviewPausePoint *)(const void *)n)
                                 ->Position;

        sum.x += v->x;
        sum.y += v->y;
        sum.z += v->z;
        sum.pad += v->pad;
        count++;
    }
    k = 1.0f / (float)(count > 1 ? count : 1);
    out->x = sum.x * k;
    out->y = sum.y * k;
    out->z = sum.z * k;
    out->pad = sum.pad * k;
}

// 0x00165828: 0 when `pt` is farther than 20 from any of the stop's
// points; else 1, and with `addPoint` the point goes on the end of the
// stop's list.
static int32_t pause_try_add(PreviewPause *p, const bVector3 *pt,
                             int32_t addPoint)
{
    bNode *n;
    PreviewPausePoint *q;

    for (n = p->Points.next; n != &p->Points; n = n->next)
        if (STOP_RADIUS < dist3(pt, &((PreviewPausePoint *)(void *)n)
                                         ->Position))
            return 0;
    if (!addPoint)
        return 1;
    q = (PreviewPausePoint *)bMalloc((int)sizeof(PreviewPausePoint),
                                     "PreviewPausePoint", 0, 16);
    q->Position = *pt;
    list_add_tail(&p->Points, &q->Node);
    return 1;
}

// 0x00165908: `pt` into the first stop on `pauses` that takes it (with
// `addPoint` 0 the stop takes it without keeping it), else a new stop of
// its own on the end. Retail's first argument, the route, is not read.
static void add_stop_point(bNode *pauses, const bVector3 *pt,
                           int32_t addPoint)
{
    bNode *n;
    PreviewPause *p;

    for (n = pauses->next; n != pauses; n = n->next)
        if (pause_try_add((PreviewPause *)(void *)n, pt, addPoint))
            return;
    p = (PreviewPause *)bMalloc((int)sizeof(PreviewPause), "PreviewPause",
                                0, 16);
    list_init(&p->Points);
    pause_try_add(p, pt, 1);
    list_add_tail(pauses, &p->Node);
}

// 0x001659e0: `cop` onto the seen list, when not on it and there is room.
static void seen_add(const void *cop, const void **seen, int32_t *numSeen)
{
    int32_t n = *numSeen;
    int32_t i;

    for (i = 0; i < n; i++)
        if (seen[i] == cop)
            return;
    if (n < STOP_MAX_SEEN) {
        seen[n] = cop;
        *numSeen = n + 1;
    }
}

// 0x00165a38: 1 when `cop` is on the seen list.
static int32_t seen_has(const void *cop, const void *const *seen,
                        const int32_t *numSeen)
{
    int32_t i;

    for (i = 0; i < *numSeen; i++)
        if (seen[i] == cop)
            return 1;
    return 0;
}

// A roadblock's cop, a struct stAICop * there: a tCop underneath.
static const bVector3 *rb_cop_pos(const tRoadBlock *rb, int32_t k)
{
    const tCop *c = (const tCop *)(const void *)rb->cops[k];

    return &c->pMyCar->State.GeometryPosition;
}

// 0x00165c40, the jump table's ROAD_BLOCK case: the cop's car, or halfway
// between its roadblock's two cops' cars when they are closer than 10;
// the first active roadblock with the cop in it, and its cops seen.
static void road_block_stop(bNode *pauses, const tCop *cop,
                            const void **seen, int32_t *numSeen)
{
    bVector3 pos = cop->pMyCar->State.GeometryPosition;
    int32_t j, k;

    for (j = 0; j < copmanager_get_num_active_road_blocks(pCopManager);
         j++) {
        tRoadBlock *rb = copmanager_get_active_road_block(pCopManager, j);
        int32_t found = 0, cnt = 0, first = -1, second = -1;

        if (rb == NULL)
            continue;
        for (k = 0; k < 2; k++) {
            const void *c = rb->cops[k];

            if (c == NULL)
                continue;
            cnt++;
            if (c == (const void *)cop)
                found = 1;
            if (cnt == 1)
                first = k;
            if (cnt == 2)
                second = k;
        }
        if (!found)
            continue;
        if (cnt == 2) {
            const bVector3 *a = rb_cop_pos(rb, first);
            const bVector3 *b = rb_cop_pos(rb, second);

            if (dist3(a, b) < STOP_ROADBLOCK_PAIR)
                halfway(&pos, a, b);
        }
        for (k = 0; k < 2; k++)
            if (rb->cops[k] != NULL)
                seen_add(rb->cops[k], seen, numSeen);
        break;
    }
    add_stop_point(pauses, &pos, 1);
}

// 0x00165ae0 to 0x00165e7c: the cop race's stops.
static void cop_stops(bNode *pauses)
{
    const void *seen[STOP_MAX_SEEN];
    int32_t numSeen = 0;
    tPursuitNode *list = &pCopManager->SpikeStripList;
    tPursuitNode *n;
    struct Chopper *h;
    int32_t i, j, k;

    for (i = STOP_MAX_SEEN - 1; i >= 0; i--)
        seen[i] = NULL;

    // The spike strips, and their roadblocks' cops seen.
    for (n = list->Next; n != list; n = n->Next) {
        tSpikeStrip *s = (tSpikeStrip *)(void *)n;
        bVector3 c;

        tspikestrip_get_centre(s, &c);
        add_stop_point(pauses, &c, 1);
        for (j = 0; j < copmanager_get_num_active_road_blocks(pCopManager);
             j++) {
            tRoadBlock *rb = copmanager_get_active_road_block(pCopManager,
                                                              j);

            if (rb == NULL || rb->nIndexIntoLoadedData != s->nRoadBlockID)
                continue;
            for (k = 0; k < 2; k++)
                if (rb->cops[k] != NULL)
                    seen_add(rb->cops[k], seen, &numSeen);
        }
    }

    // The cops, by the jump table at 0x002b1ff0.
    for (i = 0; i < pCopManager->nNumCops; i++) {
        tCop *cop = pCopManager->Cops[i];

        if (cop == NULL)
            continue;
        switch ((uint32_t)cop->DesiredLogicState) {
        case LS_SPEED_TRAP:
        case LS_DRIVING_ON_PATROL:
        case LS_CAUGHT_SPEEDER:
        case LS_GUARD_LOCATION:
            if (!seen_has(cop, seen, &numSeen))
                add_stop_point(pauses, &cop->pMyCar->State.GeometryPosition,
                               1);
            break;
        case LS_ROAD_BLOCK:
            if (!seen_has(cop, seen, &numSeen))
                road_block_stop(pauses, cop, seen, &numSeen);
            break;
        default:
            break;
        }
    }

    // The helicopter, chasing, on its way to a stakeout or at one, or on a
    // bombing run.
    h = pCurrentWorld->Helicopter;
    if (h != NULL && ((uint32_t)h->Plan < (uint32_t)CHOPPLAN_START_CHASE
                      || h->Plan == CHOPPLAN_BOMBING_RUN))
        add_stop_point(pauses, &h->CurrentPos, 1);
}

// The race's cars from AICarPos up to CopCarPos, read afresh each time.
static int32_t racer_count(void)
{
    return pCurrentWorld->CopCarPos - pCurrentWorld->AICarPos;
}

static Car *racer(int32_t i)
{
    return pCurrentWorld->CarTable[pCurrentWorld->AICarPos + i];
}

// 0x00165e80 to 0x00166018: the stops without cops, none joining a stop.
static void race_stops(bNode *pauses)
{
    Collision *c;
    int32_t i;

    for (i = 0; i < racer_count(); i++) {
        Car *car = racer(i);

        if (race_get_racing_car(pCurrentRace, car)->RacePosition == 1) {
            add_stop_point(pauses, &car->State.Position, 0);
            break;
        }
    }
    for (i = 0; i < racer_count(); i++) {
        Car *car = racer(i);

        if (race_get_racing_car(pCurrentRace, car)->RacePosition == 2
            || car->State.nWheelsTouchingGround == 0)
            add_stop_point(pauses, &car->State.Position, 0);
    }
    for (c = (Collision *)pCurrentWorld->CollisionList.next;
         (void *)c != (void *)&pCurrentWorld->CollisionList;
         c = c->Link.next)
        if (collision_is_two_car_collision(c))
            add_stop_point(pauses, &c->CurrentContactPoint, 0);
}

float preview_stop_compare(const void *a, const void *b)
{
    return ((const PreviewStopEntry *)a)->Param
           - ((const PreviewStopEntry *)b)->Param;
}

int32_t preview_route_find_stops(PreviewRoute *route,
                                 TopologyCoordinate *tc, Spline *eyeForward,
                                 Spline *look, Spline *lookAhead,
                                 const Linear *eyeParam,
                                 const Linear *lookParam, float *stops,
                                 int32_t maxStops)
{
    bNode pauses;
    bNode *n;
    int32_t nUsed = look->NumControlPoints - 1;
    // Retail's two arrays on its stack, sized at the call.
    PreviewStopEntry entries[maxStops > 0 ? maxStops : 1];
    int8_t used[nUsed > 0 ? nUsed : 1];
    int32_t count = 0;
    int32_t i, s;
    const bVector3 *src;

    (void)route;
    list_init(&pauses);
    if (pCopManager != NULL)
        cop_stops(&pauses);
    else
        race_stops(&pauses);

    if (nUsed > 0)
        memset(used, 0, (size_t)nUsed);

    // Each stop onto the look spline, in the order found, until maxStops.
    if (maxStops > 0) {
        for (n = pauses.next; n != &pauses && count < maxStops;
             n = n->next) {
            bVector3 centre, eye;
            float t, x, fl;
            int32_t k;

            pause_centre((PreviewPause *)(void *)n, &centre);
            t = spline_find_approach_param(eyeForward, &centre,
                                           STOP_APPROACH_COS,
                                           STOP_APPROACH_TOL);
            x = spline_last(look)
                * linear_get_value(lookParam,
                                   linear_get_inverse(
                                       eyeParam,
                                       t / spline_last(eyeForward)));
            // Floored: truncated, less 1 below zero.
            fl = (float)ee_trunc_w(x);
            if (x < fl)
                fl -= 1.0f;
            k = ee_trunc_w(fl);
            if (k < 0 || k >= nUsed || used[k]) {
                k--;
                if (k < 0 || k >= nUsed || used[k])
                    continue;
                fl = (float)k;
            }
            if (fl <= spline_last(look) * linear_get_value(lookParam, 0.0f))
                continue;
            if (spline_last(look) * linear_get_value(lookParam, 1.0f) <= fl)
                continue;
            spline_get_point(eyeForward, &eye, t);
            if (pCopManager == NULL
                && topology_segment_blocked(tc, &eye, &centre))
                continue;
            if (dist3(&centre, &eye) < STOP_MAX_DISTANCE) {
                used[k] = 1;
                entries[count].Param = fl;
                entries[count].Position = centre;
                count++;
            }
        }
    }

    // HeapSort (0x001c2ff8) by the compare at 0x001659d0.
    heap_sort(entries, count, (int)sizeof(PreviewStopEntry),
              preview_stop_compare);
    for (i = 0; i < count; i++)
        stops[i] = entries[i].Param;

    // The look spline's points, each stop's in place of its own.
    src = look->pControlPoints;
    s = 0;
    for (i = 0; i < look->NumControlPoints; i++, src++) {
        if (s < count && stops[s] == (float)i) {
            spline_add_control_point(lookAhead, &entries[s].Position);
            s++;
        } else {
            spline_add_control_point(lookAhead, src);
        }
    }
    preview_down_sample_xy(lookAhead, STOP_DOWNSAMPLE, stops, count);

    // 0x00167748: each stop's points freed, then the stop.
    while ((n = pauses.next) != &pauses) {
        PreviewPause *p = (PreviewPause *)(void *)n;
        bNode *q;

        list_remove(n);
        while ((q = p->Points.next) != &p->Points) {
            list_remove(q);
            bFree(q);
        }
        bFree(p);
    }
    return count;
}

// ---------------------------------------- other classes' methods, for now

float spline_approach_cosine(const Spline *s, const bVector3 *pt, float t)
{
    bVector3 p, d;
    float vx, vy, vz, q;

    spline_get_point(s, &p, t);
    spline_get_derivative(s, &d, t);
    vx = p.x - pt->x;
    vy = p.y - pt->y;
    vz = p.z - pt->z;
    // vrsqrt: Q = 1 / sqrt(the length squared).
    q = 1.0f / sqrtf((vx * vx + vy * vy) + vz * vz);
    vx *= q;
    vy *= q;
    vz *= q;
    q = 1.0f / sqrtf((d.x * d.x + d.y * d.y) + d.z * d.z);
    d.x *= q;
    d.y *= q;
    d.z *= q;
    return (vx * d.x + vy * d.y) + vz * d.z;
}

float spline_find_approach_param(const Spline *s, const bVector3 *pt,
                                 float target, float tol)
{
    float g, prev, ref, bestD = 0.0f, lo, hi, r;
    int32_t i, best = 0, iter;

    prev = spline_approach_cosine(s, pt, 0.0f) - target;
    g = 0.0f;
    for (i = 1; i < s->NumControlPoints; i++) {
        g = spline_approach_cosine(s, pt, (float)i) - target;
        if (prev * g < 0.0f) {
            const bVector3 *a = &s->pControlPoints[i - 1];
            const bVector3 *b = &s->pControlPoints[i];
            bVector3 mid;
            float d;

            mid.x = b->x * 0.5f + a->x * 0.5f;
            mid.y = b->y * 0.5f + a->y * 0.5f;
            mid.z = b->z * 0.5f + a->z * 0.5f;
            d = dist3(pt, &mid);
            if (best == 0 || d < bestD) {
                bestD = d;
                best = i;
            }
        }
        prev = g;
    }
    if (best == 0)
        return prev < 0.0f ? spline_last(s) + 1.0f : -1.0f;

    // Halved from the pair's lower end; the sign to beat starts as the
    // last control point's (retail's), and moves with the upper end.
    lo = (float)(best - 1);
    hi = (float)best;
    ref = g;
    r = lo;
    g = spline_approach_cosine(s, pt, r) - target;
    for (iter = 0; tol < fabsf(g) && iter < 10; iter++) {
        r = (lo + hi) * 0.5f;
        g = spline_approach_cosine(s, pt, r) - target;
        if (g * ref < 0.0f) {
            lo = r;
        } else {
            ref = g;
            hi = r;
        }
    }
    return r;
}

float linear_get_inverse(const Linear *l, float y)
{
    if (fabsf(l->m) <= LINEAR_FLAT)
        return l->b;
    return (y - l->b) / l->m;
}

int32_t topology_segment_blocked(TopologyCoordinate *tc, const bVector3 *a,
                                 const bVector3 *b)
{
    bVector3 d, mid, prev, cur;
    float len, raw, steps, step, frac;
    int32_t n, k;

    d.x = a->x - b->x;
    d.y = a->y - b->y;
    d.z = a->z - b->z;
    d.pad = a->pad - b->pad;
    len = sqrtf((d.x * d.x + d.y * d.y) + d.z * d.z);
    if (len < TOPO_SHORT) {
        halfway(&mid, a, b);
        topology_set_interest_bbox3(tc, &mid, len * 0.5f, NULL);
        return topology_segment_intersects(tc, a, b, TOPO_RADIUS);
    }

    // ceil(len / 30), as truncated, plus 1 when that was below.
    raw = len * TOPO_STEP_INV;
    steps = (float)ee_trunc_w(raw);
    if (steps < raw)
        steps += 1.0f;
    n = ee_trunc_w(steps);
    if (n <= 0)
        return 0;
    step = len / (float)n;
    prev = *b;
    for (k = 1; k <= n; k++) {
        frac = (float)k / (float)n;
        cur.x = b->x + d.x * frac;
        cur.y = b->y + d.y * frac;
        cur.z = b->z + d.z * frac;
        cur.pad = b->pad + d.pad * frac;
        halfway(&mid, &prev, &cur);
        topology_set_interest_bbox3(tc, &mid, step * 0.5f, NULL);
        if (topology_segment_intersects(tc, &cur, &prev, TOPO_RADIUS))
            return 1;
        prev = cur;
    }
    return 0;
}

void tspikestrip_get_centre(const struct tSpikeStrip *s, bVector3 *out)
{
    bVector3 sum = { 0.0f, 0.0f, 0.0f, 0.0f };
    int32_t n = s->nNumElements;
    int32_t i;

    for (i = 0; i < n; i++) {
        const bVector4 *v = &s->Elements[i].Base.Matrix.v3;

        sum.x += v->x;
        sum.y += v->y;
        sum.z += v->z;
        sum.pad += v->w;
    }
    if (n >= 2) {
        float k = 1.0f / (float)n;

        out->x = sum.x * k;
        out->y = sum.y * k;
        out->z = sum.z * k;
        out->pad = sum.pad * k;
    } else {
        *out = sum;
    }
}
