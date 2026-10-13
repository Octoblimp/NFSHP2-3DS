// chopperfire -- the helicopter's salvos (retail 0x001ea8c0 .. 0x001ead3c),
// 12k-6's: FireSalvo, Launch and the two velocities.
//
// A salvo of one comes from under the helicopter's matrix: a rocket from
// one of four launchers in turn, 0.06 forward and 1.3 or 1.62 out to
// either side, 1.47 below; a bomb from 2.3 below, the run's spread given
// to it at random. A salvo of n is laid in a line across the helicopter,
// n - 1 to one side to n - 1 the other, 2.3 below, each bomb's spread a
// step along. The munitions themselves are munition.c's.

#include "chopper.h"

#include "bslotpool.h"
#include "bvector.h"
#include "car.h"
#include "coputil.h"
#include "eefpu.h"
#include "munition.h"
#include "realdriver.h"
#include "replay.h"
#include "world.h"

// gp-27968 .. gp-27948.
#define ROCKET_DROP        1.47f
#define LAUNCHER_FORWARD   0.06f
#define LAUNCHER_INNER     1.3f
#define LAUNCHER_OUTER     1.62f
#define BOMB_DROP          2.3f
#define SALVO_DROP         2.3f

// A launch while a player's car does better than 30 is worth a replay.
#define REPLAY_SPEED       30.0f
#define REPLAY_WEIGHT      4.0f

// 0x001ead08: from the launch point to the target car, all four lanes,
// at the run's Velocity.
static void rocket_velocity(struct Chopper *h, bVector3 *v,
                            const bVector4 *from)
{
    const bVector3 *t = &h->CurrentCar->State.Position;

    v->x = t->x - from->x;
    v->y = t->y - from->y;
    v->z = t->z - from->z;
    v->pad = t->pad - from->w;
    bNormalize3To(v, v, BombRunBehaviours[h->BombRunType].Velocity);
}

// 0x001eacb0: Adjust ahead, Velocity down (it is negative), and across
// the bomb's spread over the time the fall takes; turned to the
// helicopter's yaw. The fourth lane is the stack's in the image, 0 here.
// The two divides are the R5900's, should the helicopter be level with
// the ground.
static void bomb_velocity(struct Chopper *h, bVector3 *v, float spread)
{
    const BombRunBehaviour *row = &BombRunBehaviours[h->BombRunType];

    v->x = row->Adjust;
    v->z = row->Velocity;
    v->pad = 0.0f;
    v->y = ee_div(spread, ee_div(h->GroundZ - h->CurrentPos.z,
                                 row->Velocity));
    rotate_vector((bVector2 *)(void *)v, (const bVector2 *)(const void *)v,
                  h->Yaw);
}

// 0x001eab70. The pools grow, so a munition is always made.
static void launch(struct Chopper *h, float spread, const bMatrix4 *m)
{
    struct Car *car = h->CurrentCar;
    bVector3    v;

    if (car->pPlayer != NULL && REPLAY_SPEED < car->State.VelocityMagnitude
        && gReplayRegisterInterestingEventFn != NULL)
        gReplayRegisterInterestingEventFn(pReplayManager, REPLAY_WEIGHT,
                                          "ChopperFireWeapon");
    if (BombRunBehaviours[h->BombRunType].Type == CM_ROCKET) {
        Rocket *r;

        rocket_velocity(h, &v, &m->v3);
        r = rocket_new((Rocket *)bSlotOMalloc(RocketSlotPool));
        rocket_launch(r, m, &v, h->CurrentCar);
        return;
    }
    bomb_velocity(h, &v, spread);
    if (BombRunBehaviours[h->BombRunType].Type == CM_SMOKEBOMB) {
        droppedbomb_launch(
            smokebomb_new((SmokeBomb *)bSlotOMalloc(SmokeBombSlotPool)), m,
            &v);
    } else {
        DroppedSpikes *s = droppedspikes_new(
            (DroppedSpikes *)bSlotOMalloc(DroppedSpikesSlotPool));

        droppedbomb_launch(&s->Base, m, &v);
    }
}

void chopper_fire_salvo(struct Chopper *h)
{
    const BombRunBehaviour *row = &BombRunBehaviours[h->BombRunType];
    bMatrix4 m = h->Matrix;
    int32_t  n = row->SalvoSize;
    bVector2 off;
    float    f;

    if (n == 1) {
        if (row->Type == CM_ROCKET) {
            m.v3.z = m.v3.z - ROCKET_DROP;
            off.x = LAUNCHER_FORWARD;
            off.y = LAUNCHER_INNER;
            if (!(h->NextLauncher < 2))
                off.y = LAUNCHER_OUTER;
            if (h->NextLauncher % 2 == 1)
                off.y = -off.y;
            rotate_vector(&off, &off, h->Yaw);
            m.v3.x = m.v3.x + off.x;
            m.v3.y = m.v3.y + off.y;
            h->NextLauncher = h->NextLauncher + 1;
            if (h->NextLauncher == 4)
                h->NextLauncher = 0;
        } else {
            m.v3.z = m.v3.z - BOMB_DROP;
        }
        f = BombRunBehaviours[h->BombRunType].SalvoSpread;
        if (0.0f < f)
            f = world_random_f(pCurrentWorld, f) - f * 0.5f;
        launch(h, f, &m);
        return;
    }
    f = (float)(n - 1);
    off.x = 0.0f;
    off.y = -f;
    rotate_vector(&off, &off, h->Yaw);
    {
        float k = -2.0f / (float)n;
        float half = row->SalvoSpread * 0.5f;

        m.v3.x = m.v3.x + off.x;
        m.v3.y = m.v3.y + off.y;
        off.y = off.y * k;
        off.x = off.x * k;
        m.v3.z = m.v3.z - SALVO_DROP;
        f = -half * f;
    }
    for (; n > 0; n--) {
        launch(h, f, &m);
        m.v3.x = m.v3.x + off.x;
        m.v3.y = m.v3.y + off.y;
        f = f + BombRunBehaviours[h->BombRunType].SalvoSpread;
    }
}
