// Host harness for 3DS Files/source/camera.c and the base of cammover.c.
// Prints a transcript that tools/camera_check.py diffs line by line against
// an independent model. The orbit mover is tools/orbit_check.py's now.
//
// Same rules as the other harnesses: every float is a float32 printed with
// %.9g, so a single-ulp disagreement is a changed line rather than something
// a tolerance swallows. The camera is the first thing in the port whose state
// carries from frame to frame -- Previous and Velocity are differences of
// differences -- so the scenarios drive it for runs of frames rather than
// checking one call at a time.
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "camera.h"
#include "cammover.h"
#include "emath.h"
#include "eview.h"

// A mover takes its camera from its view, as on the disc. The view is
// started over each time: the movers it held last are gone with the frames
// they lived in.
static void use_view(int id, Camera *c)
{
    eview_construct(eGetView(id));
    eGetView(id)->pCamera = c;
}

// How many movers the view's list holds, and whether m is the first.
static int listed(const CameraMover *m)
{
    const bNode *head = &eGetView(m->ViewID)->CameraMoverList, *n;
    int k = 0;

    for (n = head->next; n != head; n = n->next)
        k++;
    return k;
}

static int listed_first(const CameraMover *m)
{
    return eGetView(m->ViewID)->CameraMoverList.next == &m->Node;
}

// ------------------------------------------------------------------- output

// All four lanes. The camera's three vectors are bVector3, which is a padded
// quadword, and every VU0 instruction that touches them in SetCameraMatrix
// is .xyzw -- so the pad carries real arithmetic and printing three
// components would hide it.
static void pv3(const char *tag, const bVector3 *v)
{
    printf("  %s %.9g %.9g %.9g %.9g\n", tag, v->x, v->y, v->z, v->pad);
}

static void pmat(const bMatrix4 *m)
{
    printf("    %.9g %.9g %.9g %.9g\n", m->v0.x, m->v0.y, m->v0.z, m->v0.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v1.x, m->v1.y, m->v1.z, m->v1.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v2.x, m->v2.y, m->v2.z, m->v2.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v3.x, m->v3.y, m->v3.z, m->v3.w);
}

// `withMatrix` is 0 for the velocity key. Nothing on the disc ever writes
// VelocityKey.Matrix -- SetCameraMatrix differences the vectors and the
// scalars and stops -- so those sixteen floats are whatever the allocation
// held, on the PS2 and here, and printing them would make the transcript
// depend on the host's stack.
static void pkey2(const char *tag, const CameraParams *k, int withMatrix)
{
    printf("  key %s\n", tag);
    if (withMatrix)
        pmat(&k->Matrix);
    pv3("pos", &k->Position);
    pv3("dir", &k->Direction);
    pv3("tgt", &k->Target);
    printf("  scal %.9g %.9g %.9g %.9g %.9g fov %u\n",
           k->TargetDistance, k->FocalDistance, k->DepthOfField,
           k->NearZ, k->FarZ, (unsigned)k->FieldOfView);
}

static void pcam(const Camera *c)
{
    pkey2("cur", &c->CurrentKey, 1);
    pkey2("prev", &c->PreviousKey, 1);
    pkey2("vel", &c->VelocityKey, 0);
    printf("  cam elapsed %.9g last %08lx dash %d car %d clear %d\n",
           c->ElapsedTime, (unsigned long)c->LastUpdateTime, c->RenderDash,
           c->CarNotToRender != 0, (int)c->ClearVelocity);
}

// ------------------------------------------------------------------ the rng
//
// The same LCG as the emath harness, for the same reason: every step is exact
// in float32, so the model reproduces it without caring how its host rounds.

static uint32_t rngState;

static void rseed(uint32_t s)
{
    rngState = s;
}

static float frand(float scale)
{
    float u;

    rngState = rngState * 1103515245u + 12345u;
    u = (float)(int32_t)(rngState >> 8) * (1.0f / 8388608.0f) - 1.0f;
    return u * scale;
}

// ---------------------------------------------------------------- scenarios

static void scenario_ctor(void)
{
    Camera c;

    printf("scenario ctor\n");
    camera_init(&c);
    pcam(&c);

    // The copy constructor, which resets LastUpdateTime and nothing else.
    // The reset only shows if the source is holding something other than
    // the 0x80000000 the constructor left, so put a real timestamp in
    // first; there is no setter for it because nothing but the frame loop
    // writes it.
    {
        Camera d;

        c.LastUpdateTime = 0x12345678u;
        c.ClearVelocity = 1;
        camera_copy(&d, &c);
        printf("  copied\n");
        pcam(&d);
    }
}

static void scenario_setmatrix(void)
{
    Camera c;
    bMatrix4 m, id;
    int i;

    printf("scenario setmatrix\n");
    camera_init(&c);
    rseed(0x5a5a1234u);

    // A run of real view matrices: a rotation with a translation in row 3,
    // which is what every mover in the game hands over.
    for (i = 0; i < 10; i++) {
        eIdentity(&id);
        eRotateZ(&m, &id, (uint16_t)(i * 4000 + 137));
        eRotateX(&m, &m, (uint16_t)(i * 9001));
        m.v3.x = frand(100.0f);
        m.v3.y = frand(100.0f);
        m.v3.z = frand(100.0f);
        camera_set_matrix(&c, &m, 1.0f / 60.0f);
        printf("  frame %d\n", i);
        pcam(&c);
    }

    // Moving the scalars between frames, which does NOT make the velocity
    // key do anything: the six scalar velocities are zero by construction,
    // because SetCameraMatrix copies the key it is about to difference. The
    // steps below are kept anyway -- they are what proves it, and the
    // CurrentKey and PreviousKey halves of the transcript still move.
    camera_set_target_distance(&c, 25.0f);
    camera_set_focal_distance(&c, 7.5f);
    camera_set_depth_of_field(&c, 3.25f);
    camera_set_near_z(&c, 0.125f);
    camera_set_far_z(&c, 9000.0f);
    camera_set_field_of_view(&c, 200);
    camera_set_matrix(&c, &m, 0.5f);
    printf("  scalars moved\n");
    pcam(&c);

    // 200 -> 65500 would be a wrap if the difference were ever taken across
    // two different values. It is not -- see above -- so what these four
    // steps actually pin down is that the field of view itself moves and
    // that its velocity stays 0 while it does.
    camera_set_field_of_view(&c, 65500);
    camera_set_matrix(&c, &m, 0.5f);
    printf("  fov wrapped\n");
    pcam(&c);
    camera_set_field_of_view(&c, 200);
    camera_set_matrix(&c, &m, 0.25f);
    printf("  fov wrapped back\n");
    pcam(&c);

    // A fractional scale and an odd product, which is what it would take to
    // tell a u16 difference from a signed one and a truncation from a
    // rounding IF the difference were ever non-zero. Kept as the record of
    // the attempt: these two steps are why the three FOV mutations are
    // listed as equivalent in camera_check.py rather than as holes.
    camera_set_field_of_view(&c, 65500);
    camera_set_matrix(&c, &m, 2.0f);
    printf("  fov half step\n");
    pcam(&c);
    camera_set_field_of_view(&c, 201);
    camera_set_matrix(&c, &m, 2.0f);
    printf("  fov half step odd\n");
    pcam(&c);

    // A matrix with something in the fourth column, like the constructor's.
    eIdentity(&m);
    m.v2.w = 100.0f;
    m.v3.z = 1200.0f;
    camera_set_matrix(&c, &m, 1.0f);
    printf("  fourth column\n");
    pcam(&c);

    // Retail's ClearVelocity: the key is taken as the last one as well, so
    // this frame's velocities are zero and the flag clears; the next frame
    // differences again.
    eIdentity(&id);
    eRotateY(&m, &id, 7000);
    m.v3.x = 50.0f;
    m.v3.y = -20.0f;
    m.v3.z = 5.0f;
    c.ClearVelocity = 1;
    camera_set_matrix(&c, &m, 0.5f);
    printf("  velocity cleared\n");
    pcam(&c);
    m.v3.x = 60.0f;
    camera_set_matrix(&c, &m, 0.5f);
    printf("  after the clear\n");
    pcam(&c);

    // And a frozen camera: every one of these must leave it alone, the
    // ClearVelocity flag included.
    CameraStopUpdating = 1;
    c.ClearVelocity = 1;
    eIdentity(&m);
    m.v3.x = 999.0f;
    camera_set_matrix(&c, &m, 1.0f);
    printf("  frozen\n");
    pcam(&c);
    CameraStopUpdating = 0;
    c.ClearVelocity = 0;
}

static void scenario_types(void)
{
    printf("scenario types\n");

    // ViewID -1 leaves it detached, which is the only way to get a mover
    // with no camera at all.
    {
        CameraMover b;

        memset(&b, 0x5a, sizeof b);
        camera_mover_init(&b, -1, CM_DRIVE);
        printf("  detached type %s view %d enabled %d camera %d pview %d\n",
               camera_mover_type_name(b.Type), b.ViewID, b.Enabled,
               b.pCamera != 0, b.pView != 0);
    }

    // Every name in the enum, plus the two out-of-range answers.
    {
        int i;

        for (i = -1; i <= 18; i++)
            printf("  name %2d %s\n", i,
                   camera_mover_type_name((CameraMoverType)i));
    }
}

// Enable and Disable are not symmetric and neither one is a plain flag
// write, so they get their own scenario: the two render flags move between
// the mover and the camera in one direction on the way in and the other on
// the way out, the near plane is forced on every enable, and
// CameraStopUpdating stops one of them and not the other.
static void pmover(const char *tag, const CameraMover *m, const Camera *c)
{
    printf("  %s en %d movercar %d moverdash %d camcar %d camdash %d"
           " near %.9g far %.9g listed %d first %d\n",
           tag, m->Enabled, m->CarNotToRender != 0, m->RenderDash,
           c->CarNotToRender != 0, c->RenderDash, c->CurrentKey.NearZ,
           c->CurrentKey.FarZ, listed(m), listed_first(m));
}

static void scenario_enable(void)
{
    Camera c;
    CameraMover m;
    int dash1 = 1, dash2 = 2;

    printf("scenario enable\n");

    // A fresh mover takes the camera's flags at construction and pushes them
    // straight back, so nothing appears to move. Then the camera is changed
    // behind its back and disabled, which is what pulls the change in.
    camera_init(&c);
    c.CarNotToRender = &dash1;
    c.RenderDash = 7;
    use_view(0, &c);
    camera_mover_init(&m, 0, CM_STILL);
    pmover("constructed", &m, &c);

    c.CarNotToRender = 0;
    c.RenderDash = 9;
    camera_mover_disable(&m);
    pmover("disabled", &m, &c);

    // A second disable must do nothing at all, including not picking the
    // camera's flags up a second time.
    c.RenderDash = 11;
    camera_mover_disable(&m);
    pmover("disabled twice", &m, &c);

    // Re-enabling pushes what the mover is now holding, and forces NearZ.
    c.CurrentKey.NearZ = 123.0f;
    camera_mover_enable(&m);
    pmover("re-enabled", &m, &c);

    // Enabling an enabled mover is the early-out, so NearZ stays where the
    // test just put it.
    c.CurrentKey.NearZ = 456.0f;
    camera_mover_enable(&m);
    pmover("enabled twice", &m, &c);

    // Frozen: Enable skips the two flags but still writes NearZ, and Disable
    // ignores the freeze completely.
    camera_mover_disable(&m);
    m.CarNotToRender = &dash2;
    m.RenderDash = 33;
    c.CarNotToRender = 0;
    c.RenderDash = 0;
    c.CurrentKey.NearZ = 789.0f;
    CameraStopUpdating = 1;
    camera_mover_enable(&m);
    pmover("frozen enable", &m, &c);
    c.RenderDash = 44;
    camera_mover_disable(&m);
    pmover("frozen disable", &m, &c);
    CameraStopUpdating = 0;
}

int main(void)
{
    scenario_ctor();
    scenario_setmatrix();
    scenario_types();
    scenario_enable();
    return 0;
}
