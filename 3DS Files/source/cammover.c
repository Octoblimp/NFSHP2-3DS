// cammover -- CameraMover.obj, the base. See cammover.h.
#include "cammover.h"

#include <math.h>

#include "emath.h"

static const char *const MOVER_NAMES[] = {
    "CM_NONE", "CM_DRIVE", "CM_DEBUG_WORLD", "CM_TRACK_ROUTE_EDITOR",
    "CM_ORBIT_CAR", "CM_BUMPER", "CM_REAR_VIEW_MIRROR", "CM_TRACK_CAR",
    "CM_GARAGE", "CM_TRACK_FLY", "CM_MAX", "CM_SELECT_CAR", "CM_STILL",
    "CM_ZONE_FREEZE", "CM_ZONE_PREVIEW", "CM_ZONE_JUMPER", "CM_ZONE_JUMPER2",
    "CM_CUBIC_DAMPER"
};

// Retail's 0x00157578. The original is a chain of eighteen compares, and
// the fall through is retail's "CM_UNKNOWN(?)"; the demo's returned the
// CM_NONE string again.
const char *camera_mover_type_name(CameraMoverType t)
{
    if ((unsigned)t >= sizeof MOVER_NAMES / sizeof MOVER_NAMES[0])
        return "CM_UNKNOWN(?)";
    return MOVER_NAMES[t];
}

// ------------------------------------------------------------- the base

void camera_mover_nothing(CameraMover *m) { (void)m; }
void camera_mover_render(CameraMover *m, eView *view) { (void)m; (void)view; }
const CameraInfo *camera_mover_get_camera_info(CameraMover *m) { (void)m; return 0; }
const POV *camera_mover_get_pov(CameraMover *m, int index) { (void)m; (void)index; return 0; }
int camera_mover_is_exterior_view(CameraMover *m) { (void)m; return 1; }
int camera_mover_is_looking_back(CameraMover *m) { (void)m; return 0; }
float camera_mover_get_wall_gap(CameraMover *m) { (void)m; return 0.7f; }
static void *base_get_car_to_follow(CameraMover *m) { (void)m; return 0; }

// 0x0015fcb0.
static const bVector3 *base_get_target(CameraMover *m)
{
    return &m->pCamera->CurrentKey.Target;
}

const CameraMoverVtbl CameraMoverBaseVtbl = {
    camera_mover_destroy,
    camera_mover_nothing,       // Update
    camera_mover_render,
    camera_mover_nothing,       // AddJoyHandlers
    camera_mover_nothing,       // RemoveJoyHandlers
    camera_mover_get_camera_info,
    camera_mover_get_pov,
    camera_mover_is_exterior_view,
    camera_mover_is_looking_back,
    camera_mover_get_wall_gap,
    camera_mover_nothing,       // ResetState
    camera_mover_enable,
    camera_mover_disable,
    base_get_car_to_follow,
    base_get_target,
};

// Retail's 0x001576e8.
void camera_mover_init(CameraMover *m, int viewID, CameraMoverType type)
{
    eView *v;
    Camera *cam;

    m->vtbl = &CameraMoverBaseVtbl;
    m->Type = type;
    m->ViewID = viewID;
    m->Enabled = 0;
    m->pPlayer = 0;

    if (viewID == -1) {
        m->pView = 0;
        m->pCamera = 0;
        m->CarNotToRender = 0;
        m->RenderDash = 0;
        return;
    }

    // The far plane is set here and the near plane down in Enable, which is
    // an odd place for it but is where the disc puts it.
    v = eGetView(viewID);
    cam = v->pCamera;
    m->pView = v;
    cam->CurrentKey.FarZ = 10000.0f;    /* gp-31292; the demo's was 5000 */
    m->CarNotToRender = cam->CarNotToRender;
    m->RenderDash = cam->RenderDash;
    m->pCamera = cam;
    camera_mover_enable(m);
}

// Retail's 0x00157780. The tail is bTNode's destructor, which only deletes.
void camera_mover_destroy(CameraMover *m)
{
    m->vtbl = &CameraMoverBaseVtbl;
    camera_mover_disable(m);
}

// Retail's 0x001577d8.
void camera_mover_enable(CameraMover *m)
{
    if (m->Enabled)
        return;
    m->Enabled = 1;

    if (!CameraStopUpdating) {
        m->pCamera->CarNotToRender = m->CarNotToRender;
        m->pCamera->RenderDash = m->RenderDash;
    }
    eview_attach_camera_mover(m->pView, &m->Node);
    m->pCamera->CurrentKey.NearZ = 0.5f;
}

// Retail's 0x00157850. Not symmetric with Enable, in two ways that matter. It returns
// immediately when the mover is already disabled -- so a mover that never
// attached, whose pCamera is null, never dereferences it -- and it copies the
// camera's two render flags back INTO the mover before letting go, so a
// disable/enable pair round-trips whatever another mover left on the camera
// in between rather than restoring what this one first saw. And unlike
// Enable it does not consult CameraStopUpdating at all.
void camera_mover_disable(CameraMover *m)
{
    if (!m->Enabled)
        return;
    m->Enabled = 0;
    m->CarNotToRender = m->pCamera->CarNotToRender;
    m->RenderDash = m->pCamera->RenderDash;
    eview_unattach_camera_mover(m->pView, &m->Node);
}

// 0x0015fcd0 and 0x0015fcc0.
const bVector3 *camera_mover_get_position(const CameraMover *m)
{
    return &m->pCamera->CurrentKey.Position;
}

const bVector3 *camera_mover_get_direction(const CameraMover *m)
{
    return &m->pCamera->CurrentKey.Direction;
}

// 0x0015fca0.
void camera_mover_set_player(CameraMover *m, void *player)
{
    m->pPlayer = player;
}

// 0x00157888. The way from eye to look, normalised on VU0 (all four lanes,
// by 1 / sqrt), the axis of a `roll` turn, and world up turned by it. Up's
// pad lane is the stack's; eMulVector makes it 1 anyway.
void camera_mover_compute_banked_up_vector(CameraMover *m, bVector3 *out,
                                           const bVector3 *eye,
                                           const bVector3 *look,
                                           uint16_t roll)
{
    bMatrix4 r;
    bVector3 axis, up;
    float q;

    (void)m;
    axis.x = look->x - eye->x;
    axis.y = look->y - eye->y;
    axis.z = look->z - eye->z;
    axis.pad = look->pad - eye->pad;
    q = 1.0f / sqrtf((axis.x * axis.x + axis.y * axis.y) + axis.z * axis.z);
    axis.x = axis.x * q;
    axis.y = axis.y * q;
    axis.z = axis.z * q;
    axis.pad = axis.pad * q;
    eCreateAxisRotationMatrix(&r, &axis, roll);
    up.x = 0.0f;
    up.y = 0.0f;
    up.z = 1.0f;
    up.pad = 0.0f;
    eMulVector3(out, &r, &up);
}

// The first mover on a view's list, or NULL, as both loops below test it:
// the head's next against the head itself.
static CameraMover *first_mover(eView *v)
{
    bNode *n = v->CameraMoverList.next;

    return n != &v->CameraMoverList ? (CameraMover *)n : 0;
}

// Retail's 0x0015ef28. eGetView has no failure, so the NULL view test the
// original makes never fires, and is not kept.
void update_camera_movers(void)
{
    int i;

    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        CameraMover *m = first_mover(eGetView(i));

        if (m)
            m->vtbl->Update(m);
    }
}

// Retail's 0x0015eee0.
void render_camera_movers(eView *view)
{
    CameraMover *m = first_mover(view);

    if (m)
        m->vtbl->Render(m, view);
}
