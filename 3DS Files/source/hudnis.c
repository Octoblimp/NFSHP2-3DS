// hudnis -- see hudnis.h.

#include "hudnis.h"

#include <stddef.h>

#include "banim.h"
#include "eefpu.h"
#include "flailer.h"
#include "hudrender.h"
#include "race.h"
#include "raceparams.h"
#include "realtime.h"
#include "trackflow.h"

int32_t (*gCdReadClockFn)(NisClock *c);
void (*gScfGetLocalTimeFn)(NisClock *c);

// FlailerScreenVisibility's VISIBLE.
#define NISOVERLAY_SCREEN_VISIBLE 0

#define TRACK_SECONDS  0.25f               // gp-20676
#define SCALE_FROM     5.0f                // gp-20688
#define ALPHA_FROM     0.0f                // gp-20684
#define ALPHA_TO     128.0f                // gp-20680

#define DATE_EVERY     31                  // frames

// Month 1, then months 2 to 12, in the language tables.
#define JANUARY_ID   0xe86c
#define FEBRUARY_ID  0xe86d

// tCubic1D's methods, inlined.
static void track_aim(BSpline *t, float v)
{
    t->valDesired = v;
    if (!(v == t->val))
        t->state = 2;
}

static void track_snap(BSpline *t)
{
    t->val = t->valDesired;
    t->dval = t->dvalDesired;
    t->state = 0;
}

static void track_start(BSpline *t, float from, float to)
{
    t->flags = 0;
    t->duration = TRACK_SECONDS;
    track_aim(t, from);
    track_snap(t);
    track_aim(t, to);
}

static struct FlailerTextChunk *text(struct FlailerObjectChunk *o)
{
    return (struct FlailerTextChunk *)(void *)o;
}

static int32_t bcd(uint8_t b)
{
    return (b >> 4) * 10 + (b & 15);
}

static const char *translate(int32_t id)
{
    const char *s = gHudTranslateFn != NULL ? gHudTranslateFn(id) : NULL;

    return s != NULL ? s : "";
}

void nisoverlay_update_date_and_time(NISOverlayManager *o)
{
    NisClock c;
    int32_t month, day, year, hour, minute, second, id;
    const char *name;

    if (gCdReadClockFn == NULL || gCdReadClockFn(&c) == 0)
        return;
    if (c.stat != 0)
        return;
    if (gScfGetLocalTimeFn != NULL)
        gScfGetLocalTimeFn(&c);
    month = bcd(c.month);
    day = bcd(c.day);
    year = bcd(c.year);
    hour = bcd(c.hour);
    minute = bcd(c.minute);
    second = bcd(c.second);
    // Unsigned, so month 0 and 13 and over take January's name too.
    if ((uint32_t)(month - 2) < 11)
        id = FEBRUARY_ID + (month - 2);
    else
        id = JANUARY_ID;
    name = translate(id);
    if (gCurrLanguageFn != NULL && gCurrLanguageFn() != 0)
        flailer_printf(o->ScreenHash, NISOVERLAY_DATE_OBJECT, "%d %s 20%02d",
                       day, name, year);
    else
        flailer_printf(o->ScreenHash, NISOVERLAY_DATE_OBJECT, "%s %d 20%02d",
                       name, day, year);
    flailer_printf(o->ScreenHash, NISOVERLAY_TIME_OBJECT, "%02d:%02d:%02d",
                   hour, minute, second);
    o->LastDateTimeUpdate = (uint32_t)RealTimeFrames;
}

void nisoverlay_start(NISOverlayManager *o)
{
    uint32_t s = o->ScreenHash;

    if (s == 0)
        return;
    o->LastDateTimeUpdate = 0;
    nisoverlay_update_date_and_time(o);
    if (gSetFlailerScreenVisibilityFn != NULL)
        gSetFlailerScreenVisibilityFn(s, NISOVERLAY_SCREEN_VISIBLE);
    o->BustedDisplay = flailer_find_object(s, NISOVERLAY_BUSTED_OBJECT,
                                           FLAILER_TYPE_TEXT);
    o->PointsDisplay = flailer_find_object(s, NISOVERLAY_POINTS_OBJECT,
                                           FLAILER_TYPE_TEXT);
    o->sx = flailer_get_top_left_x(s, NISOVERLAY_BUSTED_OBJECT);
    o->sy = flailer_get_top_left_y(s, NISOVERLAY_BUSTED_OBJECT);
    flailer_get_scale(s, NISOVERLAY_BUSTED_OBJECT, &o->ScaleX, &o->ScaleY);
    track_start(o->ScaleAnimationTrack, SCALE_FROM, o->ScaleX);
    track_start(o->AlphaAnimationTrack, ALPHA_FROM, ALPHA_TO);
}

void nisoverlay_update(NISOverlayManager *o, int32_t playing)
{
    if (o->BustedDisplay != NULL) {
        int32_t a;

        flailerobject_set_top_left_y(o->BustedDisplay, o->sy);
        flailerobject_set_scale_y(o->BustedDisplay, o->ScaleY);
        // FlailerTextChunk's own; BustedDisplay was found as a text.
        flailerobject_scale_about_center(o->BustedDisplay,
                                         o->ScaleAnimationTrack->val);
        a = ee_trunc_w(o->AlphaAnimationTrack->val);
        flailertext_set_alpha(text(o->BustedDisplay), a);
        a = ee_trunc_w(o->AlphaAnimationTrack->val);
        // Retail writes through it unchecked.
        if (o->PointsDisplay != NULL)
            flailertext_set_alpha(text(o->PointsDisplay), a);
    }
    bspline_seek(o->ScaleAnimationTrack, WorldTimeElapsed);
    bspline_seek(o->AlphaAnimationTrack, WorldTimeElapsed);
    // subu then slti: the difference wraps, and is compared signed.
    if (!((int32_t)((uint32_t)RealTimeFrames - o->LastDateTimeUpdate)
          < DATE_EVERY))
        nisoverlay_update_date_and_time(o);
    if (!playing || (WorldTimeFrames & 8))
        flailer_set_visibility(o->ScreenHash, NISOVERLAY_REC_LIGHT,
                               FLAILER_OBJECT_INVISIBLE);
    else
        flailer_set_visibility(o->ScreenHash, NISOVERLAY_REC_LIGHT,
                               FLAILER_OBJECT_VISIBLE);
    flailer_set_visibility(o->ScreenHash, NISOVERLAY_FRAME,
                           playing ? FLAILER_OBJECT_VISIBLE
                                   : FLAILER_OBJECT_INVISIBLE);
}

static int32_t in_replay(void)
{
    RCState state;

    // The port's test; retail reads the state through it.
    if (pRaceCoordinator == NULL)
        return 0;
    state = racecoordinator_get_current_state(pRaceCoordinator);
    return state == RCSTATE_INSTANT_REPLAY || state == RCSTATE_POSTRACE
           || state == RCSTATE_AUTO_REPLAY
           || racecoordinator_is_replay_demo_mode(pRaceCoordinator);
}

static void show_points(NISOverlayManager *o)
{
    int32_t v = FLAILER_OBJECT_INVISIBLE;

    if (TheRaceParameters.BeACop != 0
        && TheRaceParameters.NumPlayerCars == 1)
        v = FLAILER_OBJECT_VISIBLE;
    flailer_set_visibility(o->ScreenHash, NISOVERLAY_POINTS_OBJECT, v);
}

void nisoverlay_set_visible(NISOverlayManager *o, uint32_t on)
{
    if (o->ScreenHash == 0 || in_replay())
        return;
    if (!on) {
        flailer_set_group_visibility(o->ScreenHash, NISOVERLAY_GROUP,
                                     FLAILER_OBJECT_INVISIBLE);
        return;
    }
    if (o->State == FLAILER_NIS_TICKET || o->State == FLAILER_NIS_ARREST) {
        flailer_set_group_visibility(o->ScreenHash, NISOVERLAY_GROUP,
                                     FLAILER_OBJECT_VISIBLE);
        show_points(o);
    } else if (o->State == FLAILER_NIS_BUSTED) {
        flailer_set_group_visibility(o->ScreenHash, NISOVERLAY_GROUP,
                                     FLAILER_OBJECT_INVISIBLE);
        flailer_set_visibility(o->ScreenHash, NISOVERLAY_BUSTED_OBJECT,
                               FLAILER_OBJECT_VISIBLE);
        show_points(o);
    }
}

void nisoverlay_start_arrest(NISOverlayManager *o)
{
    o->State = FLAILER_NIS_ARREST;
    nisoverlay_start(o);
}

void nisoverlay_start_ticket(NISOverlayManager *o)
{
    o->State = FLAILER_NIS_TICKET;
    nisoverlay_start(o);
}

void nisoverlay_start_busted(NISOverlayManager *o)
{
    o->State = FLAILER_NIS_BUSTED;
    nisoverlay_start(o);
}
