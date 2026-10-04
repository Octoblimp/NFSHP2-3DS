// hudcop -- see hudcop.h.

#include "hudcop.h"

#include <math.h>
#include <stddef.h>

#include "car.h"
#include "carinit.h"
#include "copmanager.h"
#include "eefpu.h"
#include "flailer.h"
#include "hudanim.h"
#include "player.h"
#include "raceparams.h"
#include "rcstates.h"
#include "realtime.h"
#include "timer.h"

float (*gCopManagerGetRadarDetectorIntensityFn)(struct tCopManager *m,
                                                struct Car *c,
                                                int32_t *flag);

// ------------------------------------------------------- the radar detector

#define RADAR_LIGHTS        12
#define RADAR_STEPS         11.0f          // 41300000
#define RADAR_MOST          10
#define RADAR_SWELL_FROM     9             // light 10 off light 8
#define RADAR_SWELL_TWO     10             // light 11 off light 9
#define RADAR_SWELL_SECONDS  0.2f          // gp-30392 and gp-30388
#define RADAR_SWELL_BY     -10.0f          // c1200000
#define RADAR_BEEP_PER_LIGHT -0.038333334f // gp-30384, bd1d036a
#define RADAR_BEEP_AT        0.5f
#define TICK_SECONDS         0.00025f      // gp-30380

// 0x002fbb30, four rows of twelve, ABGR: lit and unlit, then lit and
// unlit for a flagged cop. Green, then amber, then red.
static const uint32_t RadarColours[4][RADAR_LIGHTS] = {
    { 0xff008800, 0xff008800, 0xff008800, 0xff008800, 0xff008800,
      0xff004488, 0xff004488, 0xff004488,
      0xff000088, 0xff000088, 0xff000088, 0xff000088 },
    { 0x80004000, 0x80004000, 0x80004000, 0x80004000, 0x80004000,
      0x80002240, 0x80002240, 0x80002240,
      0x80000040, 0x80000040, 0x80000040, 0x80000040 },
    { 0xff008888, 0xff008888, 0xff008888, 0xff008888, 0xff008888,
      0xff004488, 0xff004488, 0xff004488,
      0xff000088, 0xff000088, 0xff000088, 0xff000088 },
    { 0x80004040, 0x80004040, 0x80004040, 0x80004040, 0x80004040,
      0x80002240, 0x80002240, 0x80002240,
      0x80000040, 0x80000040, 0x80000040, 0x80000040 },
};

static void set_light(struct FlailerObjectChunk *o, uint32_t colour)
{
    if (o != NULL)
        flailerbitmap_set_color((struct FlailerBitmapChunk *)(void *)o,
                                colour);
}

static void set_vis(struct FlailerObjectChunk *o, int32_t v)
{
    if (o != NULL)
        flailerobject_set_visibility(o, v);
}

// Light `light` swells from light `from`'s top left, by -10 each way and
// from scale 1 to 2, fading out over 0.2 s in `slot`.
static void swell(struct Player *p, int32_t slot, int32_t light,
                  int32_t from)
{
    const struct FlailerObjectChunk *b = p->pFlailerRadarLight[from];
    bVector2 at, to;
    bVector2 scale_from = { 1.0f, 1.0f };
    bVector2 scale_to = { 2.0f, 2.0f };

    if (b == NULL)
        return;
    at.x = b->X;
    at.y = b->Y;
    to.x = at.x + RADAR_SWELL_BY;
    to.y = at.y + RADAR_SWELL_BY;
    player_hud_start_bitmap_animation(
        p, slot, (struct FlailerBitmapChunk *)(void *)
                     p->pFlailerRadarLight[light],
        &at, &to, &scale_from, &scale_to, 128, 0, RADAR_SWELL_SECONDS,
        (uint32_t)WorldTimer, 0);
}

void player_update_radar_detector(struct Player *p)
{
    // Retail's flag is the stack's until the cop manager writes it, which
    // it does only for a cop in range; here it starts 0.
    int32_t flag = 0;
    float intensity = 0.0f;
    int32_t lit, row, i;

    if (gCopManagerGetRadarDetectorIntensityFn != NULL && pCopManager != NULL)
        intensity = gCopManagerGetRadarDetectorIntensityFn(pCopManager,
                                                           p->MyCar, &flag);
    lit = ee_trunc_w(intensity * RADAR_STEPS);
    if (lit > RADAR_MOST)
        lit = RADAR_MOST;
    row = flag != 0 ? 2 : 0;
    for (i = 0; i < lit; i++)
        set_light(p->pFlailerRadarLight[i], RadarColours[row][i]);
    for (; i < RADAR_LIGHTS; i++)
        set_light(p->pFlailerRadarLight[i], RadarColours[row + 1][i]);

    if (lit >= RADAR_SWELL_FROM)
        swell(p, 16, 10, 8);
    else
        set_vis(p->pFlailerRadarLight[10], FLAILER_OBJECT_INVISIBLE);
    if (lit >= RADAR_SWELL_TWO)
        swell(p, 17, 11, 9);
    else
        set_vis(p->pFlailerRadarLight[11], FLAILER_OBJECT_INVISIBLE);

    if (!SoundEnabled || lit <= 0) {
        p->RadarTimer.PackedTime = 0;
        return;
    }
    {
        Timer step;

        timer_set_time(&step, WorldTimeElapsed);
        p->RadarTimer.PackedTime += step.PackedTime;
    }
    if ((float)lit * RADAR_BEEP_PER_LIGHT + RADAR_BEEP_AT
        < (float)(int32_t)p->RadarTimer.PackedTime * TICK_SECONDS) {
        p->RadarTimer.PackedTime = 0;
        if (p->pRadarBeep != NULL && gSamplePlayFn != NULL)
            gSamplePlayFn(p->pRadarBeep, 1.0f, 0.0f, 0.0f);
    }
}

// -------------------------------------------------------------- the trackers

#define TRACKER_RANGE     50.0f            // 42480000
#define TRACKER_TURN       0.5f
#define TRACKER_WIDTH    400.0f            // 43c80000
#define TRACKER_LEFT        120
#define TRACKER_PER_UNIT   0.02f           // gp-30376

void player_draw_tracker(struct Player *p, struct Car *c, int32_t index)
{
    const bVector3 *a = &c->State.Position;
    const bVector3 *b = &p->MyCar->State.Position;
    struct FlailerObjectChunk *t;
    float dx, dy, dz, d, turn, s;

    // `vsub ; vmul.xyz ; vaddy.x ; vaddz.x`, then sqrt.s.
    dx = b->x - a->x;
    dy = b->y - a->y;
    dz = b->z - a->z;
    d = sqrtf((dx * dx + dy * dy) + dz * dz);
    if (!(d <= TRACKER_RANGE))
        return;
    turn = c->fAngleToCamera;
    if (turn < -TRACKER_TURN || TRACKER_TURN < turn)
        return;
    t = p->pFlailerTracker[index];
    // Retail writes through it unchecked.
    if (t == NULL)
        return;
    s = d * TRACKER_PER_UNIT;
    t->X = (float)(ee_trunc_w((turn + TRACKER_TURN) * TRACKER_WIDTH)
                   + TRACKER_LEFT);
    if (1.0f < s)
        s = 1.0f;
    s = 1.0f - s;
    t->ScaleY = s + s;
    t->ScaleX = s + s;
    flailerobject_set_visibility(t, FLAILER_OBJECT_VISIBLE);
}

// ---------------------------------------------------------- the pursuit meter

#define PURSUIT_BARS        4
#define PURSUIT_TICKETS     3
#define PURSUIT_IN_FROM   300.0f           // 43960000
#define PURSUIT_IN_SCALE    4.0f
#define PURSUIT_IN_SECONDS  1.5f
#define PURSUIT_SLOT        2              // a bar's slot is 2 on

// 0x002b3f20: where each bar flies out to, from its place.
static const bVector2 PursuitOut[PURSUIT_BARS] = {
    { 0.0f, -50.0f }, { 0.0f, 50.0f }, { 0.0f, -50.0f }, { 0.0f, 50.0f },
};

void player_update_pursuit_meter(struct Player *p, int32_t level)
{
    int32_t tickets = 0;
    int32_t prev, i, last;

    if (p->pFlailerPursuitStar == NULL)
        return;
    // Retail asks pCopManager unchecked.
    if (pCopManager != NULL) {
        tickets = copmanager_get_num_tickets(pCopManager, p->MyCar);
        if (tickets >= 4)
            tickets = PURSUIT_TICKETS;
    }
    if (race_parameters_is_free_run(&TheRaceParameters))
        tickets = 0;
    for (i = 0; i < tickets; i++)
        set_vis(p->pFlailerPursuitX[i], FLAILER_OBJECT_VISIBLE);
    for (; i < PURSUIT_TICKETS; i++)
        set_vis(p->pFlailerPursuitX[i], FLAILER_OBJECT_INVISIBLE);

    prev = p->PrevPursuitLevel;
    if (level == prev)
        return;
    // The bars are 0 to 3; retail reads past them for a level over 4,
    // which tCopManager does not give.
    for (i = prev; i < level && i < PURSUIT_BARS; i++) {
        bVector2 at, to;
        bVector2 scale_from = { PURSUIT_IN_SCALE, PURSUIT_IN_SCALE };
        bVector2 scale_to = { 1.0f, 1.0f };

        if (i < 0)
            continue;
        at.x = p->PursuitObjectPos[i].x - PURSUIT_IN_FROM;
        at.y = p->PursuitObjectPos[i].y;
        to.x = PURSUIT_IN_FROM + at.x;
        to.y = 0.0f + at.y;
        player_hud_start_bitmap_animation(
            p, i + PURSUIT_SLOT,
            (struct FlailerBitmapChunk *)(void *)p->pFlailerPursuitLevel[i],
            &at, &to, &scale_from, &scale_to, 0, 128, PURSUIT_IN_SECONDS,
            (uint32_t)WorldTimer, 1);
    }
    if (level < prev) {
        // Down to one below the new level, and bar 0 for level 0 or 1.
        last = level - 1;
        if (last < 0)
            last = 0;
        for (i = prev - 1; i >= last; i--) {
            bVector2 at, to;
            bVector2 one = { 1.0f, 1.0f };

            if (i >= PURSUIT_BARS)
                continue;
            at = p->PursuitObjectPos[i];
            to.x = PursuitOut[i].x + at.x;
            to.y = PursuitOut[i].y + at.y;
            player_hud_start_bitmap_animation(
                p, i + PURSUIT_SLOT,
                (struct FlailerBitmapChunk *)(void *)
                    p->pFlailerPursuitLevel[i],
                &at, &to, &one, &one, 128, 0, 1.0f, (uint32_t)WorldTimer, 1);
        }
    }
    p->PrevPursuitLevel = level;
}
