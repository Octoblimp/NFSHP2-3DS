// zonepreview -- zonecameras.cpp's ZonePreviewCameraMover. See zonepreview.h.

#include "zonepreview.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "bmatrix.h"
#include "bmem.h"
#include "camera.h"
#include "car.h"
#include "carinit.h"
#include "eefpu.h"
#include "emath.h"
#include "player.h"
#include "playerzone.h"
#include "previewspline.h"
#include "previewstops.h"
#include "race.h"
#include "realdriver.h"
#include "realtime.h"
#include "zonecam.h"

// The allocations' file name, as retail's bMalloc gives it.
#define ZONECAMERAS_CPP "..\\indep\\src\\zonecameras.cpp"

// The run's times. Out at the route's length times 0.01 (gp-30804), back
// at its length times 0.0033333334 (gp-30800); in over 0.25 s, the turn
// over 0.4 (gp-30792, -30784, -30768, -30728, -30724), out over 0.6
// (gp-30780, -30776, -30764), each blend's tangents scaled by its own time
// (the turn's out side by gp-30796 and -30788). A stop holds 0.8 s
// (gp-30772, -30748, -30744). The look runs 20 of the route's length ahead
// of the eye.
#define ZP_OUT_RATE          0.01f
#define ZP_BACK_RATE         0.0033333334f
#define ZP_IN                0.25f
#define ZP_TURN              0.4f
#define ZP_OUT               0.6f
#define ZP_HOLD              0.8f
#define ZP_LOOK_LEAD         20.0f

// The radial blur: up to 0.8 over the blend in (gp-30756); on the run out
// from 0 to 0.7 (gp-30732), its far alpha from 0.8 to 0.9 (gp-30736,
// -30740); down from 0.7 and 0.9 over the turn (gp-30720, -30716), at 2.5
// a second. The zone sample: 0.6 (gp-30760), up by 0.4 over the run out
// (gp-30752), down over the turn at 2.5 a second, and silent at a stop and
// after.
#define ZP_BLUR_IN           0.8f
#define ZP_BLUR_RUN_FROM     0.7f
#define ZP_BLUR_RUN_TO       0.9f
#define ZP_BLUR_RUN_START    0.8f
#define ZP_BLUR_TURN_FROM    0.7f
#define ZP_BLUR_TURN_TO      0.9f
#define ZP_TURN_RATE         2.5f
#define ZP_SOUND             0.6f
#define ZP_SOUND_RISE        0.4f

// EnsureTopology's largest interest box (0x4170, 15).
#define ZP_ENSURE_BOX        15.0f

// ViolatesTopology's step, 10 in the spline's length; its interest boxes
// 0.5 bigger than half the step, its constraint 0.5 off a polygon with a
// lift of 1.
#define ZP_WALK_STEP         10.0f
#define ZP_WALK_GAP          0.5f

// ------------------------------------------------------------ the vtable

static void zp_destroy_thunk(CameraMover *m)
{
    zone_preview_camera_mover_destroy((ZonePreviewCameraMover *)m);
}

static void zp_update_thunk(CameraMover *m)
{
    zone_preview_camera_mover_update((ZonePreviewCameraMover *)m);
}

static void zp_render_thunk(CameraMover *m, eView *view)
{
    zone_preview_camera_mover_render((ZonePreviewCameraMover *)m, view);
}

static void zp_enable_thunk(CameraMover *m)
{
    zone_preview_camera_mover_enable((ZonePreviewCameraMover *)m);
}

static void zp_disable_thunk(CameraMover *m)
{
    zone_preview_camera_mover_disable((ZonePreviewCameraMover *)m);
}

// The base's (0x0015fcf8), which cammover.c keeps to itself.
static void *zp_get_car_to_follow(CameraMover *m)
{
    (void)m;
    return NULL;
}

// 0x002b2050.
const CameraMoverVtbl ZonePreviewCameraMoverVtbl = {
    zp_destroy_thunk,
    zp_update_thunk,
    zp_render_thunk,
    camera_mover_nothing,       // AddJoyHandlers
    camera_mover_nothing,       // RemoveJoyHandlers
    camera_mover_get_camera_info,
    camera_mover_get_pov,
    camera_mover_is_exterior_view,
    camera_mover_is_looking_back,
    camera_mover_get_wall_gap,
    camera_mover_nothing,       // ResetState
    zp_enable_thunk,
    zp_disable_thunk,
    zp_get_car_to_follow,
    camera_mover_get_target,
};

// ---------------------------------------------------------- the helpers

// a*k + b, a*k, a - b and a + b, on all four lanes, as VU0's vmulx, vadd
// and vsub.
static void scale_add(bVector3 *o, const bVector3 *a, float k,
                      const bVector3 *b)
{
    o->x = a->x * k + b->x;
    o->y = a->y * k + b->y;
    o->z = a->z * k + b->z;
    o->pad = a->pad * k + b->pad;
}

static void scale(bVector3 *o, const bVector3 *a, float k)
{
    o->x = a->x * k;
    o->y = a->y * k;
    o->z = a->z * k;
    o->pad = a->pad * k;
}

static void sub(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    o->x = a->x - b->x;
    o->y = a->y - b->y;
    o->z = a->z - b->z;
    o->pad = a->pad - b->pad;
}

static void add(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    o->x = a->x + b->x;
    o->y = a->y + b->y;
    o->z = a->z + b->z;
    o->pad = a->pad + b->pad;
}

// vmul.xyz, vaddy.x, vaddz.x and sqrt.s.
static float length3(const bVector3 *v)
{
    return sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);
}

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

// How far a Linear goes from 0 to 1, as the constructor works it out:
// GetValue(1) less GetValue(0).
static float linear_span(const Linear *l)
{
    return linear_get_value(l, 1.0f) - linear_get_value(l, 0.0f);
}

// A tCubic3D as the constructor makes each one: every value 0, the
// duration `d`, arriving at 1, idle and free to run. The coefficients and
// the parameter are not written.
static BSpline3D *new_blend(float d, int line)
{
    BSpline3D *b = (BSpline3D *)bMalloc((int)sizeof(BSpline3D),
                                        ZONECAMERAS_CPP, line, 16);
    BSpline *lane[3];
    int i;

    lane[0] = &b->x;
    lane[1] = &b->y;
    lane[2] = &b->z;
    for (i = 0; i < 3; i++) {
        lane[i]->val = 0.0f;
        lane[i]->dval = 0.0f;
        lane[i]->valDesired = 0.0f;
        lane[i]->dvalDesired = 0.0f;
        lane[i]->arrivalThreshold = 1.0f;
        lane[i]->state = 0;
        lane[i]->duration = d;
        lane[i]->flags = 0;
    }
    return b;
}

static BSpline3D *make_blend(float d, int line, const bVector3 *val,
                             bVector3 *dval, bVector3 *valDesired,
                             bVector3 *dvalDesired)
{
    BSpline3D *b = new_blend(d, line);

    bspline3d_set_val(b, val);
    bspline3d_set_dval(b, dval);
    bspline3d_set_val_desired(b, valDesired);
    bspline3d_set_dval_desired(b, dvalDesired);
    return b;
}

static struct Player *zp_player(const ZonePreviewCameraMover *m)
{
    return (struct Player *)m->base.pPlayer;
}

// RadialBlurOn, RadialBlurOff and RadialBlurAlpha (0x0010f178, 0x0010f1b0,
// 0x0010f238), for the player's view.
static void zp_blur_on(const ZonePreviewCameraMover *m)
{
    if (gRadialBlurOnFn != NULL)
        gRadialBlurOnFn(zp_player(m)->PlayerNumber);
}

static void zp_blur_off(const ZonePreviewCameraMover *m)
{
    if (gRadialBlurOffFn != NULL)
        gRadialBlurOffFn(zp_player(m)->PlayerNumber);
}

static void zp_blur(const ZonePreviewCameraMover *m, float from, float to)
{
    if (gRadialBlurAlphaFn != NULL)
        gRadialBlurAlphaFn(zp_player(m)->PlayerNumber, from, to);
}

float spline_linear_estimate_length(Spline *s)
{
    bVector3 d;
    int32_t i;

    if (s->Dirty != 0) {
        s->Length = 0.0f;
        for (i = 1; i < s->NumControlPoints; i++) {
            sub(&d, &s->pControlPoints[i], &s->pControlPoints[i - 1]);
            s->Length = s->Length + length3(&d);
        }
        s->Dirty = 0;
    }
    return s->Length;
}

// One of EnsureTopology's two halves.
static void ensure_pair(TopologyCoordinate *tc, bVector3 *anchor,
                        bVector3 *pt)
{
    bVector3 h, centre;
    float r;

    sub(&h, anchor, pt);
    scale(&h, &h, 0.5f);
    r = length3(&h);
    if (ZP_ENSURE_BOX < r) {
        r = ZP_ENSURE_BOX;
        scale(&h, &h, ZP_ENSURE_BOX);
    }
    add(&centre, &h, pt);
    topology_set_interest_bbox3(tc, &centre, r, NULL);
    zone_constrain_to_topology(tc, anchor, pt, 0, 0);
}

void zone_ensure_topology(TopologyCoordinate *tc, bVector3 *anchorEye,
                          bVector3 *eye, bVector3 *anchorLook,
                          bVector3 *look)
{
    ensure_pair(tc, anchorLook, look);
    ensure_pair(tc, anchorEye, eye);
}

// ------------------------------------------------------ the constructor

ZonePreviewCameraMover *zone_preview_camera_mover_init(
    ZonePreviewCameraMover *m, int viewID, PreviewRoute *route,
    bVector3 *pos)
{
    Camera *cam;
    bVector3 eye, look, p, dp, q, dq, dv;
    float inFrac, lead, last, last2, u;
    uint16_t fov;
    int i;

    (void)pos;
    // CM_STILL, 12, as the image passes it, as the Zone Freeze's does.
    camera_mover_init(&m->base, viewID, CM_STILL);
    m->fTime = 0.0f;
    m->fHoldTime = 0.0f;
    m->base.vtbl = &ZonePreviewCameraMoverVtbl;
    spline_init_alloc(&m->LookSpline, SPLINE_EXTRAPOLATE, 100, 16384);
    spline_init_alloc(&m->LookAheadSpline, SPLINE_EXTRAPOLATE, 100, 16384);
    spline_init_alloc(&m->EyeForwardSpline, SPLINE_EXTRAPOLATE, 100, 16384);
    spline_init_alloc(&m->EyeBackwardSpline, SPLINE_EXTRAPOLATE, 100,
                      16384);
    m->EyeParameter.m = 0.0f;
    m->EyeParameter.b = 0.0f;
    m->LookParameter.m = 0.0f;
    m->LookParameter.b = 0.0f;
    preview_comet_init(&m->Comet, &m->LookSpline, &ZonePreviewCometParams);
    topology_init(&m->Topology);

    // The run out takes the first 0.25 s's share of the eye's parameter
    // and leaves the last 20 of the route; the look starts 20 on and runs
    // to the end.
    m->fOutTime = route->fDistance * ZP_OUT_RATE;
    inFrac = ZP_IN / (m->fOutTime + ZP_IN);
    m->fBackTime = route->fDistance * ZP_BACK_RATE;
    lead = ZP_LOOK_LEAD / route->fDistance;
    linear_init(&m->EyeParameter, 0.0f, inFrac, 1.0f, 1.0f - lead);
    linear_init(&m->LookParameter, 0.0f, inFrac + lead, 1.0f, 1.0f);
    for (i = 3; i >= 0; i--)
        m->fStops[i] = 0.0f;

    preview_route_make_splines(route, &m->Topology, &m->LookSpline,
                               &m->EyeForwardSpline, &m->EyeBackwardSpline,
                               &m->EyeParameter);
    preview_route_find_stops(route, &m->Topology, &m->EyeForwardSpline,
                             &m->LookSpline, &m->LookAheadSpline,
                             &m->EyeParameter, &m->LookParameter, m->fStops,
                             4);

    // The camera as it is, and a frame on.
    cam = m->base.pCamera;
    m->vAnchorLook = cam->CurrentKey.Target;
    m->vAnchorEye = cam->CurrentKey.Position;
    scale_add(&eye, &cam->VelocityKey.Position, WorldTimeElapsed,
              &cam->CurrentKey.Position);
    scale_add(&look, &cam->VelocityKey.Target, WorldTimeElapsed,
              &cam->CurrentKey.Target);

    // In: from the camera, at its speed, onto the run out's starts, at
    // theirs.
    last = spline_last(&m->EyeForwardSpline);
    u = last * linear_get_value(&m->EyeParameter, 0.0f);
    spline_get_point(&m->EyeForwardSpline, &p, u);
    spline_get_derivative(&m->EyeForwardSpline, &dp, u);
    scale(&dv, &cam->VelocityKey.Position, ZP_IN);
    scale(&dp, &dp, last * linear_span(&m->EyeParameter) / m->fOutTime
                    * ZP_IN);
    m->pEyeBlendIn = make_blend(ZP_IN, 1049, &eye, &dv, &p, &dp);

    last = spline_last(&m->LookAheadSpline);
    u = last * linear_get_value(&m->LookParameter, 0.0f);
    spline_get_point(&m->LookAheadSpline, &p, u);
    spline_get_derivative(&m->LookAheadSpline, &dp, u);
    scale(&dv, &cam->VelocityKey.Target, ZP_IN);
    scale(&dp, &dp, last * linear_span(&m->LookParameter) / m->fOutTime
                    * ZP_IN);
    m->pLookBlendIn = make_blend(ZP_IN, 1065, &look, &dv, &p, &dp);

    // The turn: from the run out's ends onto the run back's, which goes
    // the other way.
    last = spline_last(&m->EyeForwardSpline);
    u = last * linear_get_value(&m->EyeParameter, 1.0f);
    spline_get_point(&m->EyeForwardSpline, &p, u);
    spline_get_derivative(&m->EyeForwardSpline, &dp, u);
    scale(&dp, &dp, last * linear_span(&m->EyeParameter) / m->fOutTime
                    * ZP_TURN);
    last = spline_last(&m->EyeBackwardSpline);
    u = last * linear_get_value(&m->EyeParameter, 1.0f);
    spline_get_point(&m->EyeBackwardSpline, &q, u);
    spline_get_derivative(&m->EyeBackwardSpline, &dq, u);
    scale(&dq, &dq, -last * linear_span(&m->EyeParameter) / m->fBackTime
                    * ZP_TURN);
    m->pEyeBlendMid = make_blend(ZP_TURN, 1090, &p, &dp, &q, &dq);

    // The look-ahead spline is read at the look spline's parameter here,
    // and its tangent scaled by its own last, as the image has it.
    last = spline_last(&m->LookSpline);
    u = last * linear_get_value(&m->LookParameter, 1.0f);
    spline_get_point(&m->LookAheadSpline, &p, u);
    spline_get_point(&m->LookSpline, &q, u);
    spline_get_derivative(&m->LookAheadSpline, &dp, u);
    spline_get_derivative(&m->LookSpline, &dq, u);
    last2 = spline_last(&m->LookAheadSpline);
    scale(&dp, &dp, last2 * linear_span(&m->LookParameter) / m->fOutTime
                    * ZP_TURN);
    last = spline_last(&m->LookSpline);
    scale(&dq, &dq, -last * linear_span(&m->LookParameter) / m->fBackTime
                    * ZP_TURN);
    m->pLookBlendMid = make_blend(ZP_TURN, 1111, &p, &dp, &q, &dq);

    // Out: from the run back's ends onto the camera's course as it was.
    last = spline_last(&m->EyeBackwardSpline);
    u = last * linear_get_value(&m->EyeParameter, 0.0f);
    spline_get_point(&m->EyeBackwardSpline, &p, u);
    spline_get_derivative(&m->EyeBackwardSpline, &dp, u);
    scale(&dp, &dp, -last * linear_span(&m->EyeParameter) / m->fBackTime
                    * ZP_OUT);
    scale(&dv, &cam->VelocityKey.Position, ZP_OUT);
    m->pEyeBlendOut = make_blend(ZP_OUT, 1131, &p, &dp, &eye, &dv);

    last = spline_last(&m->LookSpline);
    u = last * linear_get_value(&m->LookParameter, 0.0f);
    spline_get_point(&m->LookSpline, &p, u);
    spline_get_derivative(&m->LookSpline, &dp, u);
    scale(&dp, &dp, -last * linear_span(&m->LookParameter) / m->fBackTime
                    * ZP_OUT);
    scale(&dv, &cam->VelocityKey.Target, ZP_OUT);
    m->pLookBlendOut = make_blend(ZP_OUT, 1147, &p, &dp, &look, &dv);

    // The focus pull: 1, going to 1.
    m->pFocusPull = (BSpline *)bMalloc((int)sizeof(BSpline), ZONECAMERAS_CPP,
                                       1157, 16);
    m->pFocusPull->flags = 0;
    m->pFocusPull->state = 2;
    m->pFocusPull->dvalDesired = 0.0f;
    m->pFocusPull->dval = 0.0f;
    m->pFocusPull->valDesired = 1.0f;
    m->pFocusPull->duration = ZP_IN;
    m->pFocusPull->arrivalThreshold = 1.0f;
    m->pFocusPull->val = 1.0f;

    fov = cam->CurrentKey.FieldOfView;
    m->fTanFov = bSinBam(fov) / bCosBam(fov);
    if (!CameraStopUpdating) {
        cam->CarNotToRender = NULL;
        cam->RenderDash = 0;
    }
    return m;
}

CameraMover *zone_preview_camera_mover_new(void *mem, int viewID,
                                           PreviewRoute *route,
                                           bVector3 *pos)
{
    return &zone_preview_camera_mover_init((ZonePreviewCameraMover *)mem,
                                           viewID, route, pos)->base;
}

// ------------------------------------------------------- the destructor

void zone_preview_camera_mover_destroy(ZonePreviewCameraMover *m)
{
    m->base.vtbl = &ZonePreviewCameraMoverVtbl;
    if (m->base.pPlayer != NULL)
        zp_blur_off(m);
    bFree(m->pEyeBlendIn);
    bFree(m->pEyeBlendMid);
    bFree(m->pEyeBlendOut);
    bFree(m->pLookBlendIn);
    bFree(m->pLookBlendMid);
    bFree(m->pLookBlendOut);
    bFree(m->pFocusPull);
    topology_destroy(&m->Topology);
    preview_comet_destroy(&m->Comet);
    // The Linears' destructor (bNode's, 0x00167950) frees nothing with 2.
    spline_destroy(&m->EyeBackwardSpline, 2);
    spline_destroy(&m->EyeForwardSpline, 2);
    spline_destroy(&m->LookAheadSpline, 2);
    spline_destroy(&m->LookSpline, 2);
    camera_mover_destroy(&m->base);
}

// ------------------------------------------- Duration, Render and the rest

float zone_preview_camera_mover_duration(ZonePreviewCameraMover *m)
{
    float holds = 0.0f, from, to;
    int i;

    from = linear_get_value(&m->LookParameter, 0.0f)
           * spline_last(&m->LookSpline);
    to = linear_get_value(&m->LookParameter, 1.0f)
         * spline_last(&m->LookSpline);
    for (i = 0; i < 4; i++)
        if (from < m->fStops[i] && m->fStops[i] < to)
            holds += ZP_HOLD;
    return ((((holds + ZP_IN) + m->fOutTime) + ZP_TURN) + m->fBackTime)
           + ZP_OUT;
}

float zone_preview_duration_fn(CameraMover *m)
{
    return zone_preview_camera_mover_duration((ZonePreviewCameraMover *)m);
}

void zone_preview_camera_mover_render(ZonePreviewCameraMover *m,
                                      eView *view)
{
    float end = m->fOutTime + ZP_IN;

    if (end < m->fTime)
        return;
    preview_comet_render(&m->Comet, view, m->fTime / end);
}

void zone_preview_camera_mover_enable(ZonePreviewCameraMover *m)
{
    camera_mover_enable(&m->base);
    preview_comet_enable(&m->Comet);
}

void zone_preview_camera_mover_disable(ZonePreviewCameraMover *m)
{
    preview_comet_disable(&m->Comet);
    camera_mover_disable(&m->base);
}

PreviewRoute *zone_preview_find_route(struct Car *car)
{
    PreviewRoute *r = (PreviewRoute *)bMalloc((int)sizeof(PreviewRoute),
                                              ZONECAMERAS_CPP, 1192, 16);

    r = preview_route_init(r, car, 40.0f, 320.0f);
    if (r->pPoints == NULL || r->nPoints < 4) {
        preview_route_destroy(r, 3);
        return NULL;
    }
    return r;
}

int32_t zone_preview_violates_topology(ZonePreviewCameraMover *m)
{
    Spline *s = &m->LookSpline;
    TopologyCoordinate tc;
    bVector3 pts[2], h, centre;
    bVector3 *cur, *prev;
    float step, t, r;
    int32_t i;

    step = spline_last(s) / spline_linear_estimate_length(s) * ZP_WALK_STEP;
    topology_init(&tc);
    for (t = 0.0f, i = 0; t <= spline_last(s); t += step, i++) {
        cur = &pts[i & 1];
        prev = &pts[(i & 1) ^ 1];
        spline_get_point(s, cur, t);
        if (i <= 0)
            continue;
        sub(&h, cur, prev);
        scale(&h, &h, 0.5f);
        r = length3(&h) + ZP_WALK_GAP;
        add(&centre, &h, prev);
        topology_set_interest_bbox3(&tc, &centre, r, NULL);
        if (topology_constrain(&tc, TOPOLOGY_CONSTRAIN_BY_SCALE, 1, prev,
                               cur, ZP_WALK_GAP, 1.0f)) {
            topology_destroy(&tc);
            return 1;
        }
    }
    topology_destroy(&tc);
    return 0;
}

int32_t zone_preview_violates_topology_fn(CameraMover *m)
{
    return zone_preview_violates_topology((ZonePreviewCameraMover *)m);
}

// --------------------------------------------------------------- Update

void zone_preview_camera_mover_update(ZonePreviewCameraMover *m)
{
    float old, t, sound, outEnd, turnEnd;
    bVector3 up, eye, look, d;
    bMatrix4 mat;
    BSpline *focus;
    int32_t fov;
    int i;

    if (is_game_flow_paused())
        return;
    // The image leaves up's fourth lane as the stack had it.
    up.x = 0.0f;
    up.y = 0.0f;
    up.z = 1.0f;
    up.pad = 0.0f;
    eye.pad = 0.0f;
    look.pad = 0.0f;
    old = m->fTime;
    t = old;
    if (0.0f < m->fHoldTime) {
        m->fHoldTime = m->fHoldTime - RealTimeElapsed;
    } else {
        t = old + RealTimeElapsed;
        m->fTime = t;
    }
    sound = ZP_SOUND;
    outEnd = m->fOutTime + ZP_IN;
    turnEnd = outEnd + ZP_TURN;

    if (t < ZP_IN) {
        bspline3d_seek(m->pEyeBlendIn, RealTimeElapsed);
        bspline3d_seek(m->pLookBlendIn, RealTimeElapsed);
        bspline3d_get_val(m->pEyeBlendIn, &eye);
        bspline3d_get_val(m->pLookBlendIn, &look);
        zone_ensure_topology(&m->Topology, &m->vAnchorEye, &eye,
                             &m->vAnchorLook, &look);
        zp_blur(m, 0.0f, m->fTime * 4.0f * ZP_BLUR_IN);
    } else if (t < outEnd) {
        // The run out. Crossing a stop starts its hold, with the blur off
        // and the sample silent for that frame.
        float u = (t - ZP_IN) / m->fOutTime;
        float uo = (old - ZP_IN) / m->fOutTime;
        float to, from, f;
        int on = 1;

        sound = u * ZP_SOUND_RISE + ZP_SOUND;
        to = linear_get_value(&m->LookParameter, u)
             * spline_last(&m->LookSpline);
        from = linear_get_value(&m->LookParameter, uo)
               * spline_last(&m->LookSpline);
        spline_get_point(&m->EyeForwardSpline, &eye,
                         linear_get_value(&m->EyeParameter, u)
                         * spline_last(&m->EyeForwardSpline));
        spline_get_point(&m->LookAheadSpline, &look, to);
        for (i = 0; i < 4; i++) {
            if (from < m->fStops[i] && m->fStops[i] <= to) {
                m->fHoldTime = ZP_HOLD;
                on = 0;
                sound = 0.0f;
                break;
            }
        }
        if (on) {
            f = (m->fTime - ZP_IN) / m->fOutTime;
            zp_blur_on(m);
            zp_blur(m, f * ZP_BLUR_RUN_FROM,
                    f * ZP_BLUR_RUN_TO + (1.0f - f) * ZP_BLUR_RUN_START);
        } else {
            zp_blur_off(m);
        }
    } else if (t < turnEnd) {
        float k;

        if (old < outEnd) {
            focus = m->pFocusPull;
            focus->duration = ZP_TURN;
            focus->valDesired = 1.0f;
            if (focus->val != 1.0f)
                focus->state = 2;
        }
        bspline3d_seek(m->pEyeBlendMid, RealTimeElapsed);
        bspline3d_seek(m->pLookBlendMid, RealTimeElapsed);
        sound = 1.0f - ((m->fTime - ZP_IN) - m->fOutTime) * ZP_TURN_RATE;
        bspline3d_get_val(m->pEyeBlendMid, &eye);
        bspline3d_get_val(m->pLookBlendMid, &look);
        k = (((m->fOutTime + ZP_IN) + ZP_TURN) - m->fTime) * ZP_TURN_RATE;
        zp_blur(m, k * ZP_BLUR_TURN_FROM, k * ZP_BLUR_TURN_TO);
    } else if (t < turnEnd + m->fBackTime) {
        float v;

        if (old < turnEnd)
            zp_blur_off(m);
        sound = 0.0f;
        v = 1.0f - (((m->fTime - ZP_IN) - m->fOutTime) - ZP_TURN)
                   / m->fBackTime;
        spline_get_point(&m->EyeBackwardSpline, &eye,
                         linear_get_value(&m->EyeParameter, v)
                         * spline_last(&m->EyeBackwardSpline));
        spline_get_point(&m->LookSpline, &look,
                         linear_get_value(&m->LookParameter, v)
                         * spline_last(&m->LookSpline));
    } else {
        sound = 0.0f;
        bspline3d_seek(m->pEyeBlendOut, RealTimeElapsed);
        bspline3d_seek(m->pLookBlendOut, RealTimeElapsed);
        bspline3d_get_val(m->pEyeBlendOut, &eye);
        bspline3d_get_val(m->pLookBlendOut, &look);
        zone_ensure_topology(&m->Topology, &m->vAnchorEye, &eye,
                             &m->vAnchorLook, &look);
    }

    // The focus pull draws the eye in along the line of sight and the
    // field of view in with it.
    focus = m->pFocusPull;
    bspline_seek(focus, RealTimeElapsed);
    sub(&d, &eye, &look);
    scale_add(&eye, &d, focus->val, &look);
    fov = bATan(focus->val, m->fTanFov);
    if (!CameraStopUpdating)
        m->base.pCamera->CurrentKey.FieldOfView = (uint16_t)fov;
    eCreateLookAtMatrix(&mat, &eye, &look, &up);
    camera_set_matrix(m->base.pCamera, &mat, RealTimeElapsed);

    if (SoundEnabled)
        player_update_zone_sound(zp_player(m), 1.0f - sound, sound, 0,
                                 sound * 0.5f + -0.5f);
}
