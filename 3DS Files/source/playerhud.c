// playerhud -- see playerhud.h.

#include "playerhud.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "camerainfo.h"
#include "cammover.h"
#include "car.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "drivecam.h"
#include "eview.h"
#include "flailer.h"
#include "hudtex.h"
#include "player.h"
#include "playerinit.h"
#include "race.h"
#include "raceinit.h"
#include "raceparams.h"
#include "rcpost.h"
#include "realtime.h"
#include "trackflow.h"

void (*gPlayerSetRearViewMirrorCameraMoverFn)(struct Player *p, uint32_t on);
void (*gInitializeFlailerTachometerFn)(struct FlailerObjectChunk *needle,
                                       struct FlailerObjectChunk *gradient,
                                       void *points);
struct TrackMap *(*gNewTrackMapFn)(TrackInfo *track, struct Car *car,
                                   struct Player *p);
void (*gDeleteTrackMapFn)(struct TrackMap *m);
void (*gPlayerFillInRaceOverMessagesFn)(struct Player *p);
void (*gRaceFinishedSpeechFn)(struct Car *c, int32_t reason);
void (*gPlayerHudStartWrongWayFn)(struct Player *p);
void (*gNisOverlaySetVisibleFn)(NISOverlayManager *o, uint32_t on);

// The word in the TrackMap SetTrackMapMode hands the mode to.
#define TRACKMAP_MODE_WORD 160

// CarHudInfo, read out of CarTypeInfo's HudInfo bytes as hudtex.c does.
#define HUDINFO_IS_INTEGRATED 0
#define HUDINFO_TACH_X       20
#define HUDINFO_TACH_Y       22
#define HUDINFO_SPEEDO_X     56
#define HUDINFO_SPEEDO_Y     58
#define HUDINFO_SPEEDTEXT_X  60
#define HUDINFO_SPEEDTEXT_Y  62
#define HUDINFO_RPMTEXT_X    64
#define HUDINFO_RPMTEXT_Y    66

static int32_t hud_info_s16(const CarTypeInfo *ti, int off)
{
    int16_t v;

    memcpy(&v, ti->HudInfo + off, sizeof v);
    return v;
}

static int32_t hud_info_is_integrated(const CarTypeInfo *ti)
{
    int32_t v;

    memcpy(&v, ti->HudInfo + HUDINFO_IS_INTEGRATED, sizeof v);
    return v;
}

int32_t player_is_nis_playing(const struct Player *p)
{
    return p->pNisManager != NULL && gNisManagerIsPlayingFn != NULL
        && gNisManagerIsPlayingFn(p->pNisManager) != 0;
}

int32_t player_should_show_busted_text(const struct Player *p)
{
    (void)p;
    return pCopManager != NULL
        && copmanager_should_display_busted_text(pCopManager) != 0;
}

// 0x001795f8, the gauge for the player's camera: the third-person one
// outside the car or in a two-player race, the bumper view's alone, the
// in-car digits, or none.
static uint32_t gauge_features(struct Player *p)
{
    CameraMover *m = p->pCameraMover;
    const POV *pov;

    if (m == NULL)
        return 0;
    pov = m->vtbl->GetPOV(m, p->PlayerSettings.DriveCameraPOVIndex);
    if (pov == NULL)
        return 0;
    m = p->pCameraMover;
    if (m->vtbl->IsExteriorView(m))
        return HUD_GAUGES_OUTSIDE;
    if (TheRaceParameters.NumPlayerCars == 2)
        return HUD_GAUGES_OUTSIDE;
    if (pov->Type == POV_BUMPER && TheRaceParameters.NumPlayerCars == 1)
        return HUD_GAUGES;
    if (pov->Type == POV_INCAR)
        return HUD_GAUGES_IN_CAR;
    return 0;
}

uint32_t player_determine_hud_features(struct Player *p)
{
    const RaceParameters *rp = &TheRaceParameters;
    const tGlobalDisplaySettings *ds = &rp->GlobalDisplaySettings;
    int32_t cop = rp->BeACop;
    int32_t np = PlayerNumPlayers;
    uint32_t f = HUD_MUSIC;
    uint32_t reset;
    RCState rc;
    eRaceStage stage;

    if (p->MyCar == NULL || p->HudScreenHash == 0)
        return 0;
    if (p->nZoneCurrent != 0)
        return HUD_MUSIC;
    rc = pRaceCoordinator->CurrentRCState;
    if (rc == RCSTATE_AI_DEMO_MODE || rc == RCSTATE_REPLAY_DEMO_MODE)
        return 0;
    if (rc == RCSTATE_INSTANT_REPLAY || rc == RCSTATE_POSTRACE)
        return 0;

    // A NIS: this player's, or Be A Cop's player 0's seen by player 1.
    if (player_is_nis_playing(p)
        || (np == 2 && p->PlayerNumber == 1 && cop != 0
            && PlayerPlayersByNumber[0] != NULL
            && player_is_nis_playing(PlayerPlayersByNumber[0]))) {
        int8_t state = p->PlayerSettings.PlayersHudState;

        if (rp->nMaxCops != 0 && rc != RCSTATE_PAUSE && np == 1)
            f = HUD_PURSUIT_NIS | HUD_MUSIC;
        if (rp->NumPlayerCars + rp->NumAICars == 1
            || race_parameters_is_free_run(rp) || state == 1 || state == 3
            || cop != 0)
            f &= ~(HUD_RACE_POSITION | HUD_PURSUIT_NIS);
        if (rc != RCSTATE_PAUSE)
            f |= HUD_NIS_OVERLAY;
        if (np == 1 || cop != 0)
            f |= HUD_CINEMA_BARS;
        if (np != 2 || p->PlayerNumber != 0 || cop != 0
            || ds->TwoPlayerTrackMapMode == TRACKMAP_MODE_OFF)
            return f;
        return f | HUD_TRACK_MAP;
    }

    if (player_should_show_busted_text(p))
        return rc == RCSTATE_PAUSE ? HUD_MUSIC : HUD_MUSIC | HUD_NIS_OVERLAY;

    stage = pCurrentRace->RaceStage;
    if (stage == RACE_STAGE_FLYBY || stage == RACE_STAGE_PRERACE)
        return HUD_CINEMA_BARS;
    if (stage == RACE_STAGE_COUNTDOWN && np == 1)
        return HUD_CINEMA_BARS | HUD_MUSIC;

    // Finished: the race-over messages, and player 0's map while player 1
    // still races.
    if (p->TimeFinishedRacing != 0 && rc == RCSTATE_RACE_IN_PROGRESS) {
        const struct Player *q = PlayerPlayersByNumber[1];

        if (np != 2 || p->PlayerNumber != 0 || q == NULL
            || q->TimeFinishedRacing != 0
            || ds->TwoPlayerTrackMapMode == TRACKMAP_MODE_OFF)
            return HUD_MUSIC | HUD_RACE_OVER;
        return HUD_MUSIC | HUD_RACE_OVER | HUD_TRACK_MAP;
    }

    // Paused: the bars over a flyby or the prerace, and the map for a
    // second after its mode changed.
    if (rc == RCSTATE_PAUSE) {
        if ((uint32_t)(pRaceCoordinator->BeforePauseRCState - 1) < 2)
            f = HUD_CINEMA_BARS | HUD_MUSIC;
        if (p->TimeTrackMapModeChanged == 0)
            return f;
        if ((int32_t)((uint32_t)RealTimeFrames - p->TimeTrackMapModeChanged)
            >= 60) {
            p->TimeTrackMapModeChanged = 0;
            return f;
        }
        return f | HUD_TRACK_MAP;
    }

    if (p->nZoneCurrent == 1 || p->nZoneCurrent == 2)
        return HUD_MUSIC | HUD_LETTERBOX;

    switch (p->PlayerSettings.PlayersHudState) {
    case 0: {
        CameraMover *m = p->pCameraMover;
        int8_t mode;
        uint32_t s;

        f |= HUD_TRACKER;
        if (m != NULL && m->vtbl->IsLookingBack(m))
            f &= ~HUD_TRACKER;
        mode = cop != 0 ? ds->BeTheCopTrackMapMode
             : np == 2 ? ds->TwoPlayerTrackMapMode
             : ds->OnePlayerTrackMapMode;
        if (mode != TRACKMAP_MODE_OFF)
            f |= HUD_TRACK_MAP;
        m = p->pCameraMover;
        if (cop != 0 && p->PlayerNumber == 0 && m != NULL
            && m->Type == CM_DRIVE
            && ((DriveCameraMover *)m)->DesiredLookBackParam == 1.0f)
            f |= HUD_COP_LOOKING_BACK;
        s = p->PlayerSettings.PreferredHudFeatures;
        if (s & 0x100)
            f |= HUD_LAP_TIME;
        if (s & 0x4)
            f |= HUD_SPLIT_TIMES;
        if (s & 0x100)
            f |= HUD_BEST_LAP;
        if (s & 0x10)
            f |= HUD_RACE_POSITION;
        if (s & 0x100)
            f |= HUD_LAP_COUNTER;
        if ((s & 0x200) && np == 1 && cop == 0
            && (rp->TimeTrialTime.PackedTime == 0
                || rp->TimeTrialTime.PackedTime == 0x7fffffff)
            && !race_parameters_is_free_run(rp) && ds->LeaderboardMode != 0)
            f |= HUD_LIVE_SPLIT;
        if (ds->RearViewMirror != 0 && p->bLookBack == 0)
            f |= HUD_REAR_VIEW_MIRROR;
        if (rp->RaceType == RACE_TYPE_TIME_TRIAL && rp->Point2Point == 0)
            f &= ~HUD_RACE_POSITION;
        if (rp->NumPlayerCars + rp->NumAICars == 1
            || race_parameters_is_free_run(rp))
            f &= ~HUD_RACE_POSITION;
        if (rp->nMaxCops != 0 && cop == 0) {
            f |= (p->PlayerSettings.PreferredHudFeatures & 0x100)
                ? HUD_PURSUIT : HUD_PURSUIT_HI;
            if (p->bLookBack == 0)
                f |= HUD_RADAR;
        }
        if (cop != 0) {
            if (p->PlayerNumber == 0)
                f = (f & ~(HUD_LAP_TIME | HUD_SPLIT_TIMES | HUD_BEST_LAP
                           | HUD_RACE_POSITION | HUD_LAP_COUNTER))
                    | HUD_BE_THE_COP;
            if (p->PlayerNumber == 1)
                f = (f & ~(HUD_SPLIT_TIMES | HUD_BEST_LAP | HUD_RACE_POSITION))
                    | HUD_BE_THE_COP;
        }
        if (!race_parameters_is_free_run(rp) && (cop == 0 || np != 2)
            && p->PlayerSettings.New44 != 0)
            f |= HUD_SCORE;
        if (p->PlayerSettings.PreferredHudFeatures & 0x40)
            f |= gauge_features(p);
        break;
    }
    case 1:
        if (rp->nMaxCops != 0 && cop == 0)
            f |= HUD_PURSUIT_HI;
        if (np == 1)
            f |= HUD_TRACK_MAP;
        break;
    case 2:
        if (rp->nMaxCops != 0 && cop == 0 && p->TimeFinishedRacing == 0)
            f |= HUD_PURSUIT_HI;
        break;
    case 3:
        if (rp->nMaxCops != 0 && cop == 0)
            f |= HUD_PURSUIT_HI;
        f |= gauge_features(p);
        break;
    default:
        break;
    }

    if (cop != 0)
        f &= ~(HUD_RACE_POSITION | HUD_PURSUIT | HUD_PURSUIT_HI);
    if (np == 2) {
        if (f & HUD_PURSUIT_HI)
            f = (f & ~HUD_PURSUIT_HI) | HUD_PURSUIT;
        f &= ~HUD_TRACKER;
    }
    if (np == 2 && p->PlayerNumber == 1)
        f &= ~HUD_TRACK_MAP;
    if (p->bWrongWay != 0)
        f |= HUD_WRONG_WAY;
    reset = p->TimeToDisplayResetPrompt.PackedTime;
    if (reset != 0 && reset != 0x7fffffff)
        f |= HUD_RESET_PROMPT;
    return f;
}

// The modes each kind of race allows (retail's word tables behind
// 0x001bd7a8, 0x001bd7f0 and 0x001bd838); a miss takes the first.
static const int32_t OnePlayerModes[] = { 0, 1, 2, 3, 4, 6 };
static const int32_t TwoPlayerModes[] = { 7, 6 };
static const int32_t BeTheCopModes[] = { 8, 6 };

static int32_t valid_mode(const int32_t *modes, size_t n, int32_t mode)
{
    size_t i;

    for (i = 0; i < n; i++)
        if (modes[i] == mode)
            return mode;
    return modes[0];
}

void player_set_track_map_mode(struct Player *p, int32_t mode)
{
    tGlobalDisplaySettings *ds = &TheRaceParameters.GlobalDisplaySettings;
    int8_t *stored;

    if (TheRaceParameters.BeACop != 0) {
        mode = valid_mode(BeTheCopModes, 2, mode);
        stored = &ds->BeTheCopTrackMapMode;
    } else if (PlayerNumPlayers == 2) {
        mode = p->PlayerNumber >= 1 ? TRACKMAP_MODE_OFF
             : valid_mode(TwoPlayerModes, 2, mode);
        stored = &ds->TwoPlayerTrackMapMode;
    } else {
        mode = valid_mode(OnePlayerModes, 6, mode);
        stored = &ds->OnePlayerTrackMapMode;
    }
    if (*stored != mode) {
        *stored = (int8_t)mode;
        p->TimeTrackMapModeChanged = (uint32_t)RealTimeFrames;
    }
    if (p->pTrackMap != NULL)
        memcpy((uint8_t *)p->pTrackMap + TRACKMAP_MODE_WORD, &mode,
               sizeof mode);
}

// ------------------------------------------------------------ SetHudFeatures

static struct FlailerObjectChunk *find(uint32_t screen, uint32_t object,
                                       int32_t type)
{
    return flailer_find_object(screen, object, type);
}

static struct FlailerObjectChunk *find_numbered(uint32_t screen,
                                                const char *fmt, int32_t n,
                                                int32_t type)
{
    char name[64];

    snprintf(name, sizeof name, fmt, (int)n);
    return flailer_find_object(screen, bchunk_hash(name), type);
}

// Every object of the group shown or hidden, as SetHudFeatures' own loops
// over FindFlailerObjectByGroup do.
static void group_visibility(uint32_t screen, uint32_t group, int32_t v)
{
    struct FlailerObjectChunk *o = NULL;

    while ((o = flailer_find_object_by_group(screen, group, FLAILER_TYPE_ANY,
                                             o)) != NULL)
        flailerobject_set_visibility(o, v);
}

static void set_format(struct FlailerObjectChunk *o, uint32_t f)
{
    if (o != NULL)
        flailertext_set_format_options((struct FlailerTextChunk *)o, f);
}

// FormatOptions |= f straight into the chunk, with no dirty flag, as the
// third-person and Be The Cop blocks do.
static void or_format(struct FlailerObjectChunk *o, uint32_t f)
{
    if (o != NULL)
        ((struct FlailerTextChunk *)o)->FormatOptions |= f;
}

static void hide(struct FlailerObjectChunk *o)
{
    if (o != NULL)
        flailerobject_set_visibility(o, FLAILER_OBJECT_INVISIBLE);
}

static void screen_visibility(uint32_t screen, int32_t v)
{
    if (gSetFlailerScreenVisibilityFn != NULL)
        gSetFlailerScreenVisibilityFn(screen, v);
}

static void set_visibility_all(uint32_t h, const uint32_t *objects, size_t n,
                               int32_t v)
{
    size_t i;

    for (i = 0; i < n; i++)
        flailer_set_visibility(h, objects[i], v);
}

static void init_tachometer(struct Player *p)
{
    if (p->pFlailerTachGradient != NULL && gInitializeFlailerTachometerFn)
        gInitializeFlailerTachometerFn(p->pFlailerTachNeedle,
                                       p->pFlailerTachGradient,
                                       p->FlailerTachPointList);
}

// HUD_GAUGES: the bumper view's speedo and tach, placed from the car's
// HudInfo on the textures ChooseLoadableTextures picks.
static void show_gauges(struct Player *p, uint32_t h, int32_t v)
{
    static const uint32_t off[] = {
        0xc637891c, 0x9309e75c, 0xd312f0cb, 0x39c9eead, 0xd2f7fa46,
        0x7be1e0f4, 0xc8842af9, 0x7bb54948, 0xcf9bf6f3,
    };
    static const uint32_t on[] = {
        0x8d28acce, 0x01223abd, 0xf446d30e, 0x35710a5d, 0x31f74338,
        0xf81dffa6, 0xd9098a4b, 0x7aa7a2a1,
    };
    const CarTypeInfo *ti = p->MyCar->pCarTypeInfo;
    tLoadableHudTextures tex;
    int32_t ax, ay, x, y;
    int32_t stx, sty;

    set_visibility_all(h, off, sizeof off / sizeof off[0], 0);
    set_visibility_all(h, on, sizeof on / sizeof on[0], v);
    ChooseLoadableTextures(p->MyCar->pRideInfo->Type,
                           TheRaceParameters.GlobalDisplaySettings.Units, &tex);
    stx = hud_info_s16(ti, HUDINFO_SPEEDTEXT_X);
    sty = hud_info_s16(ti, HUDINFO_SPEEDTEXT_Y);
    flailer_change_texture(h, 0xf446d30e, tex.Speedo);
    flailer_get_top_left_position_int(h, 0xf446d30e, &ax, &ay);
    flailer_set_center(h, 0x8d28acce,
                       ax + hud_info_s16(ti, HUDINFO_SPEEDO_X),
                       ay + hud_info_s16(ti, HUDINFO_SPEEDO_Y));
    flailer_set_top_left_position(h, 0xd9098a4b, ax + stx, ay + sty);
    flailer_set_visibility(h, 0xd9098a4b, v);
    flailer_change_texture(h, 0xd9098a4b, tex.Shadow);
    if (hud_info_is_integrated(ti) == 0) {
        flailer_set_top_left_position(h, 0xd9098a4b,
                                      ax + hud_info_s16(ti, HUDINFO_RPMTEXT_X),
                                      ay + hud_info_s16(ti, HUDINFO_RPMTEXT_Y));
        flailer_change_texture(h, 0x01223abd, tex.Tach);
        flailer_get_top_left_position_int(h, 0x01223abd, &x, &y);
        flailer_set_center(h, 0x35710a5d,
                           x + hud_info_s16(ti, HUDINFO_TACH_X),
                           y + hud_info_s16(ti, HUDINFO_TACH_Y));
        flailer_set_top_left_position(h, 0x31f74338, ax + stx + 42,
                                      ay + sty + 1);
        flailer_set_top_left_position(h, 0xf81dffa6, ax + stx + 18,
                                      ay + sty + 23);
        flailer_set_top_left_position(h, 0x7aa7a2a1, ax + stx + 16,
                                      ay + sty + 53);
    } else {
        flailer_get_top_left_position_int(h, 0xf446d30e, &x, &y);
        flailer_set_top_left_position(h, 0xd9098a4b,
                                      x + hud_info_s16(ti, HUDINFO_RPMTEXT_X),
                                      y + hud_info_s16(ti, HUDINFO_RPMTEXT_Y)
                                          - 30);
        flailer_set_visibility(h, 0x01223abd, 0);
        flailer_set_visibility(h, 0x7307c47f, 0);
        flailer_set_center(h, 0x35710a5d,
                           x + hud_info_s16(ti, HUDINFO_TACH_X),
                           y + hud_info_s16(ti, HUDINFO_TACH_Y));
        flailer_set_top_left_position(h, 0x31f74338, x + stx, y + sty - 20);
        flailer_set_top_left_position(h, 0x7aa7a2a1, x + stx + 2,
                                      y + sty - 20);
        flailer_set_top_left_position(h, 0xf81dffa6, x + stx + 22,
                                      y + sty - 20);
    }
    p->pFlailerSpeedNeedle = find(h, 0x8d28acce, FLAILER_TYPE_BITMAP);
    p->pFlailerTachNeedle = find(h, 0x35710a5d, FLAILER_TYPE_BITMAP);
    p->pFlailerTachGradient = find(h, 0x7307c47f, FLAILER_TYPE_BITMAP);
    p->pFlailerSpeedString = find(h, 0x31f74338, FLAILER_TYPE_TEXT);
    p->pFlailerSpeedString2 = find(h, 0x8cd4fda9, FLAILER_TYPE_TEXT);
    p->pFlailerTachGear = NULL;
    p->pFlailerGearString = find(h, 0xf81dffa6, FLAILER_TYPE_TEXT);
    p->pFlailerShiftUp = find(h, 0x7aa7a2a1, FLAILER_TYPE_BITMAP);
    init_tachometer(p);
    // Retail sets the three with no test.
    set_format(p->pFlailerSpeedString, BUI_FMT_FIXEDWIDTH);
    set_format(p->pFlailerSpeedString2, BUI_FMT_FIXEDWIDTH);
    set_format(p->pFlailerGearString, BUI_FMT_FIXEDWIDTH);
}

// HUD_GAUGES_OUTSIDE: the third-person gauge, its texture the units' own
// in a two-player race.
static void show_gauges_outside(struct Player *p, uint32_t h, int32_t v)
{
    static const uint32_t off[] = {
        0x8d28acce, 0x01223abd, 0xf446d30e, 0x35710a5d, 0x7307c47f,
        0x7307c47f, 0x31f74338, 0xf81dffa6, 0xd9098a4b, 0xf25e727a,
        0x7aa7a2a1,
    };
    static const uint32_t on[] = {
        0x9309e75c, 0xd312f0cb, 0x39c9eead, 0xd2f7fa46, 0x7be1e0f4,
        0xcf9bf6f3,
    };
    int8_t units = TheRaceParameters.GlobalDisplaySettings.Units;
    tLoadableHudTextures tex;
    uint32_t t;

    ChooseLoadableTextures(p->MyCar->pRideInfo->Type, units, &tex);
    if (units == 1)
        t = PlayerNumPlayers < 2 ? tex.ThirdPerson
                                 : bchunk_hash("3RDPERSONGAUGE_KMH");
    else
        t = PlayerNumPlayers > 1 ? bchunk_hash("3RDPERSONGAUGE_MPH")
                                 : tex.ThirdPerson;
    flailer_change_texture(h, 0x9309e75c, t);
    set_visibility_all(h, off, sizeof off / sizeof off[0], 0);
    set_visibility_all(h, on, sizeof on / sizeof on[0], v);
    p->pFlailerSpeedNeedle = find(h, 0xc637891c, FLAILER_TYPE_BITMAP);
    p->pFlailerTachNeedle = find(h, 0xd312f0cb, FLAILER_TYPE_BITMAP);
    p->pFlailerTachGradient = find(h, 0x39c9eead, FLAILER_TYPE_BITMAP);
    p->pFlailerSpeedString = find(h, 0xd2f7fa46, FLAILER_TYPE_TEXT);
    p->pFlailerSpeedString2 = find(h, 0x70dfb037, FLAILER_TYPE_TEXT);
    p->pFlailerTachGear = NULL;
    p->pFlailerGearString = find(h, 0x7be1e0f4, FLAILER_TYPE_TEXT);
    p->pFlailerShiftUp = find(h, 0xcf9bf6f3, FLAILER_TYPE_BITMAP);
    init_tachometer(p);
    // Retail ORs the two with no test and no dirty flag.
    or_format(p->pFlailerSpeedString, BUI_FMT_FIXEDWIDTH);
    or_format(p->pFlailerSpeedString2, BUI_FMT_FIXEDWIDTH);
}

static void hide_gauges(uint32_t h)
{
    static const uint32_t off[] = {
        0x8d28acce, 0x01223abd, 0xf446d30e, 0x35710a5d, 0x7307c47f,
        0x7307c47f, 0x31f74338, 0xf81dffa6, 0xd9098a4b, 0xf25e727a,
        0x7aa7a2a1, 0xcf9bf6f3, 0xc637891c, 0x9309e75c, 0xd312f0cb,
        0x39c9eead, 0xd2f7fa46, 0x7be1e0f4, 0xc8842af9, 0x7bb54948,
    };

    set_visibility_all(h, off, sizeof off / sizeof off[0], 0);
}

// The lap block's three labels say laps, or legs for a point-to-point,
// with a time trial's target on the third.
static void lap_labels(uint32_t h)
{
    const RaceParameters *rp = &TheRaceParameters;
    uint32_t tt = rp->TimeTrialTime.PackedTime;
    int32_t target = rp->RaceType == RACE_TYPE_TIME_TRIAL && tt != 0
        && tt != 0x7fffffff && rp->BeACop == 0;
    struct FlailerObjectChunk *o;

    if (race_parameters_is_free_run(rp)) {
        if ((o = find(h, 0x0390d3df, FLAILER_TYPE_TEXT)) != NULL)
            flailertext_set_language_id((struct FlailerTextChunk *)o, 0x494ac);
        if ((o = find(h, 0x0390d3e0, FLAILER_TYPE_TEXT)) != NULL)
            flailertext_set_language_id((struct FlailerTextChunk *)o, 0x494ad);
        if ((o = find(h, 0x0390d3e1, FLAILER_TYPE_TEXT)) != NULL)
            flailertext_set_language_id((struct FlailerTextChunk *)o, 0x494a8);
        return;
    }
    if ((o = find(h, 0x0390d3df, FLAILER_TYPE_TEXT)) != NULL)
        flailertext_set_language_id((struct FlailerTextChunk *)o,
                                    rp->Point2Point != 0 ? 0x494ab : 0x494aa);
    if ((o = find(h, 0x0390d3e0, FLAILER_TYPE_TEXT)) != NULL)
        flailertext_set_language_id((struct FlailerTextChunk *)o, 0x494a9);
    if ((o = find(h, 0x0390d3e1, FLAILER_TYPE_TEXT)) != NULL) {
        // Point2Point's second test is the first's again, with the race
        // type's sense turned round.
        if (!target && rp->Point2Point != 0 && tt != 0 && tt != 0x7fffffff
            && rp->BeACop == 0 && rp->RaceType != RACE_TYPE_TIME_TRIAL)
            target = 1;
        flailertext_set_language_id((struct FlailerTextChunk *)o,
                                    target ? 0x494da : 0x494a8);
    }
}

// The three pursuit meters share the Player's fields: the star, four
// levels, three crosses, and the four dummies' places.
static void show_pursuit(struct Player *p, uint32_t h, uint32_t group,
                         const uint32_t *objects, const char *dummy,
                         int32_t v)
{
    int32_t i;

    group_visibility(h, group, v);
    if (v != 1)
        return;
    p->pFlailerPursuitStar = find(h, objects[0], FLAILER_TYPE_BITMAP);
    for (i = 0; i < 4; i++)
        p->pFlailerPursuitLevel[i] = find(h, objects[1 + i],
                                          FLAILER_TYPE_BITMAP);
    for (i = 0; i < 3; i++)
        p->pFlailerPursuitX[i] = find(h, objects[5 + i], FLAILER_TYPE_BITMAP);
    for (i = 0; i < 4; i++) {
        struct FlailerObjectChunk *d;

        // Retail sets both with no test.
        if (p->pFlailerPursuitLevel[i] != NULL) {
            flailerbitmap_set_alpha(
                (struct FlailerBitmapChunk *)p->pFlailerPursuitLevel[i], 0,
                FLAILER_ALL_CORNERS);
            flailerobject_set_visibility(p->pFlailerPursuitLevel[i], 0);
        }
        d = find_numbered(h, dummy, i + 1, FLAILER_TYPE_BITMAP);
        if (d != NULL) {
            p->PursuitObjectPos[i].x = d->X;
            p->PursuitObjectPos[i].y = d->Y;
        }
    }
    p->PrevPursuitLevel = 0;
}

static void show_live_split(struct Player *p, uint32_t h, uint32_t f)
{
    struct FlailerObjectChunk *anchor;
    float dx = 0.0f, dy = 0.0f;
    int32_t v = (int32_t)(f >> 23) & 1;
    int32_t i;

    for (i = 0; i < 4; i++) {
        p->pFlailerLiveSplitStatus[i] = find_numbered(
            h, "LIVE_SPLIT_STATUS%d", i + 1, FLAILER_TYPE_TEXT);
        set_format(p->pFlailerLiveSplitStatus[i], BUI_FMT_FIXEDWIDTH);
        p->pFlailerLiveSplitSwatch[i] = find_numbered(
            h, "LIVE_SPLIT_SWATCH%d", i + 1, FLAILER_TYPE_BITMAP);
        p->pFlailerLiveSplitPos[i] = find_numbered(
            h, "LIVE_SPLIT_POS%d", i + 1, FLAILER_TYPE_TEXT);
        p->pFlailerLiveSplitBG[i] = find_numbered(
            h, "LIVE_SPLIT_BG%d", i + 1, FLAILER_TYPE_BITMAP);
    }
    p->pFlailerLiveSplitBar = find(h, 0xa3e3b399, FLAILER_TYPE_BITMAP);
    // The rows move to sit under the race position's anchor, or the
    // other one without it.
    anchor = find(h, (f & HUD_RACE_POSITION) ? 0x363392ae : 0x363392af,
                  FLAILER_TYPE_ANY);
    if (anchor != NULL && p->pFlailerLiveSplitSwatch[0] != NULL) {
        float ax, ay, sx, sy;

        flailerobject_get_top_left(anchor, &ax, &ay);
        flailerobject_get_top_left(p->pFlailerLiveSplitSwatch[0], &sx, &sy);
        dy = ay - sy;
        flailerobject_get_top_left(anchor, &ax, &ay);
        flailerobject_get_top_left(p->pFlailerLiveSplitSwatch[0], &sx, &sy);
        dx = ax - sx;
    }
    for (i = 0; i < 4; i++) {
        struct FlailerObjectChunk *o = NULL;
        char name[64];
        uint32_t group;

        // A row past the racing cars hides it and every row after.
        if (pCurrentRace == NULL || pCurrentRace->NumRacingCars <= i)
            v = 0;
        snprintf(name, sizeof name, "LIVE_SPLIT_GROUP_%d", (int)(i + 1));
        group = bchunk_hash(name);
        while ((o = flailer_find_object_by_group(h, group, FLAILER_TYPE_ANY,
                                                 o)) != NULL) {
            float x, y;

            flailerobject_set_visibility(o, v);
            flailerobject_get_top_left(o, &x, &y);
            flailerobject_set_top_left_y(o, y + dy);
            flailerobject_get_top_left(o, &x, &y);
            flailerobject_set_top_left_x(o, x + dx);
        }
    }
    if (p->pFlailerLiveSplitBar != NULL)
        flailerobject_set_visibility(p->pFlailerLiveSplitBar, v);
}

// HUD_RADAR. In a one-player race the radar's group moves 70 down when
// the mirror comes in and back up when it goes: bRadarOffset says the
// first light is off the place it started.
static void show_radar(struct Player *p, uint32_t h, uint32_t f,
                       uint32_t chg)
{
    struct FlailerObjectChunk *o = NULL;
    int32_t v = (int32_t)(f >> 19) & 1;
    int32_t first = 1, mirror = 0;
    int32_t i;

    if (PlayerNumPlayers == 1) {
        p->bRadarOffset = 1;
        mirror = (chg & HUD_REAR_VIEW_MIRROR) != 0;
    }
    for (i = 0; i < 12; i++)
        p->pFlailerRadarLight[i] = find_numbered(h, "RADAR_LIGHT%d", i + 1,
                                                 FLAILER_TYPE_BITMAP);
    while ((o = flailer_find_object_by_group(h, 0x062743f5, FLAILER_TYPE_ANY,
                                             o)) != NULL) {
        struct FlailerObjectChunk *l0 = p->pFlailerRadarLight[0];
        float x, y;

        flailerobject_set_visibility(o, v);
        if (PlayerNumPlayers != 1)
            continue;
        if (p->fInitialRadarY == 0.0f && l0 != NULL) {
            flailerobject_get_top_left(l0, &x, &y);
            p->fInitialRadarY = y;
        }
        if (first) {
            // Retail reads the light with no test.
            if (l0 != NULL) {
                flailerobject_get_top_left(l0, &x, &y);
                if (y == p->fInitialRadarY)
                    p->bRadarOffset = 0;
            }
            first = 0;
        }
        if (p->bRadarOffset != 0) {
            if (mirror) {
                flailerobject_get_top_left(o, &x, &y);
                flailerobject_set_top_left_y(o, y + 70.0f);
            }
            if (p->bRadarOffset != 0)
                continue;
        }
        if (mirror)
            continue;
        flailerobject_get_top_left(o, &x, &y);
        flailerobject_set_top_left_y(o, y - 70.0f);
    }
}

static void show_be_the_cop(struct Player *p, uint32_t h, uint32_t f)
{
    int32_t i;

    group_visibility(h, 0x068e2c75, (int32_t)(f >> 24) & 1);
    for (i = 0; i < 5; i++)
        p->pFlailerDamageLight[i] = find_numbered(h, "DAMAGE_LIGHT%d", i + 1,
                                                  FLAILER_TYPE_BITMAP);
    for (i = 0; i < 4; i++)
        p->pFlailerBeTheCopTickets[i] = find_numbered(
            h, "BETHECOP_X_%d", i + 1, FLAILER_TYPE_BITMAP);
    for (i = 0; i < 3; i++) {
        char name[64];

        if (p->PlayerNumber == 0) {
            p->pFlailerBeTheCopHelicopter[i] = find_numbered(
                h, "HELICOPTERICON%d", i + 1, FLAILER_TYPE_BITMAP);
            p->pFlailerBeTheCopRoadblock[i] = find_numbered(
                h, "COPCAR_ICON%d", i + 1, FLAILER_TYPE_BITMAP);
            continue;
        }
        snprintf(name, sizeof name, "HELICOPTERICON%d", (int)(i + 1));
        flailer_set_visibility(h, bchunk_hash(name), 0);
        snprintf(name, sizeof name, "COPCAR_ICON%d", (int)(i + 1));
        flailer_set_visibility(h, bchunk_hash(name), 0);
    }
    p->pFlailerBeTheCopTime = find(h, bchunk_hash("BETHECOP_TIME"),
                                   FLAILER_TYPE_TEXT);
    // Retail ORs it with no test.
    or_format(p->pFlailerBeTheCopTime, BUI_FMT_FIXEDWIDTH);
}

void player_set_hud_features(struct Player *p, uint32_t f)
{
    static const uint32_t PursuitObjects[] = {
        0x843fd334, 0xc7509d62, 0xc7509d63, 0xc7509d64, 0xc7509d65,
        0xfc401542, 0xfc401543, 0xfc401544,
    };
    static const uint32_t PursuitHiObjects[] = {
        0x03b11464, 0x9bab19d2, 0x9bab19d3, 0x9bab19d4, 0x9bab19d5,
        0x9ff605b2, 0x9ff605b3, 0x9ff605b4,
    };
    static const uint32_t PursuitNisObjects[] = {
        0x79d3babd, 0x117aba2b, 0x117aba2c, 0x117aba2d, 0x117aba2e,
        0x9f23220b, 0x9f23220c, 0x9f23220d,
    };
    static const uint32_t LapObjects[] = {
        0xc2ea8de7, 0x40e81be1, 0x40e81be2, 0x40e81be3, 0x6486623b,
        0xfc1b498a, 0xa8247197, 0x0390d3df, 0x0390d3e0, 0x0390d3e1,
    };
    // 0x002fbb20, which 0x001831d0 fills: player 2's position colour.
    static const bVector4 PlayerTwoColor = { 0.0f, 79.0f, 128.0f, 128.0f };
    uint32_t h = p->HudScreenHash;
    uint32_t cur = p->CurrentHudFeatures & ~(HUD_GAUGES | HUD_GAUGES_OUTSIDE);
    uint32_t chg = cur ^ f;
    int32_t v;

    p->CurrentHudFeatures = cur;
    if (gPlayerClearHudAnimationsFn != NULL)
        gPlayerClearHudAnimationsFn(p);
    if (p->CurrentHudFeatures == 0) {
        if (f != 0)
            screen_visibility(h, FLAILER_SCREEN_VISIBLE);
    } else if (f == 0) {
        screen_visibility(h, FLAILER_SCREEN_INVISIBLE);
    }
    if ((chg & HUD_REAR_VIEW_MIRROR) && gPlayerSetRearViewMirrorCameraMoverFn)
        gPlayerSetRearViewMirrorCameraMoverFn(p, f & HUD_REAR_VIEW_MIRROR);

    if (chg & HUD_GAUGES)
        show_gauges(p, h, (int32_t)(f >> 5) & 1);
    else if (chg & HUD_GAUGES_OUTSIDE)
        show_gauges_outside(p, h, (int32_t)(f >> 6) & 1);
    else
        hide_gauges(h);

    if (chg & HUD_GAUGES_IN_CAR) {
        v = (int32_t)(f >> 28) & 1;
        if (v == 1) {
            hide(p->pFlailerSpeedString);
            hide(p->pFlailerSpeedString2);
        }
        group_visibility(h, 0xcd086c26, v);
        if (v == 1) {
            p->pFlailerSpeedString = find(h, 0x31f74339, FLAILER_TYPE_TEXT);
            p->pFlailerGearString = find(h, 0xf81dffa7, FLAILER_TYPE_TEXT);
            p->pFlailerShiftUp = find(h, 0xcf9bf6f4, FLAILER_TYPE_BITMAP);
            or_format(p->pFlailerSpeedString, BUI_FMT_FIXEDWIDTH);
        }
    }

    if (chg & HUD_RACE_POSITION) {
        v = (int32_t)(f >> 9) & 1;
        flailer_set_visibility(h, 0x3405c44e, v);
        p->pFlailerRacePosition = find(h, 0x3405c44e, FLAILER_TYPE_TEXT);
        flailer_set_visibility(h, 0x004e27a0, v);
        p->pFlailerBigRacePosition = find(h, 0x004e27a0, FLAILER_TYPE_TEXT);
        p->pFlailerBigRacePosition2 = find(h, 0x4c769c11, FLAILER_TYPE_TEXT);
        flailer_set_visibility(h, 0x9a492668, v);
        p->pFlailerBigRaceExtension = find(h, 0x9a492668, FLAILER_TYPE_TEXT);
        flailer_set_visibility(h, 0x84bb420f, v);
        p->pFlailerBigRaceTotal = find(h, 0x84bb420f, FLAILER_TYPE_TEXT);
        if (PlayerNumPlayers == 2 && p->PlayerNumber == 1) {
            flailer_set_object_color(h, 0x004e27a0, &PlayerTwoColor);
            flailer_set_object_color(h, 0x9a492668, &PlayerTwoColor);
        }
    }

    if (chg & (HUD_LAP_TIME | HUD_LAP_COUNTER)) {
        int32_t on = (f & (HUD_LAP_TIME | HUD_LAP_COUNTER)) != 0;

        group_visibility(h, 0xb7a3bc7a, 0);
        p->pFlailerLapTime = find(h, 0xfc1b498a, FLAILER_TYPE_TEXT);
        p->pFlailerLapCounter = find(h, 0x6486623b, FLAILER_TYPE_TEXT);
        p->pFlailerBestLap = find(h, 0xa8247197, FLAILER_TYPE_TEXT);
        if (TheRaceParameters.BeACop == 0 && PlayerNumPlayers == 2 && on) {
            p->pFlailerLeadTitle = find(h, 0xeb406fec, FLAILER_TYPE_TEXT);
            p->pFlailerLeadTime = find(h, 0xf7292837, FLAILER_TYPE_TEXT);
            flailer_set_visibility(h, 0xeb406fec, 1);
            flailer_set_visibility(h, 0xf7292837, 1);
        } else {
            p->pFlailerLeadTitle = NULL;
            p->pFlailerLeadTime = NULL;
        }
        set_format(p->pFlailerBestLap, BUI_FMT_FIXEDWIDTH);
        set_format(p->pFlailerLapTime, BUI_FMT_FIXEDWIDTH);
        set_format(p->pFlailerLapCounter, BUI_FMT_FIXEDWIDTH);
        set_format(p->pFlailerLeadTime, BUI_FMT_FIXEDWIDTH);
        if (on)
            set_visibility_all(h, LapObjects,
                               sizeof LapObjects / sizeof LapObjects[0], 1);
        lap_labels(h);
        if (race_parameters_is_free_run(&TheRaceParameters)) {
            flailer_set_visibility(h, 0x6486623b, 0);
            p->pFlailerLapCounter = NULL;
        }
    }

    if (chg & HUD_SPLIT_TIMES) {
        // Hidden either way; UpdateHud shows them as splits come in.
        flailer_set_visibility(h, 0x89c3ac59, 0);
        flailer_set_visibility(h, 0xd1e5c713, 0);
        p->pFlailerRunningSplitTime = find(h, 0x89c3ac59, FLAILER_TYPE_TEXT);
        p->pFlailerCompSplitTime = find(h, 0xd1e5c713, FLAILER_TYPE_TEXT);
    }

    if (chg & (HUD_LIVE_SPLIT | HUD_RACE_POSITION))
        show_live_split(p, h, f);

    if (chg & HUD_TRACK_MAP) {
        if ((f & HUD_TRACK_MAP) == 0) {
            if (p->pTrackMap != NULL && gDeleteTrackMapFn != NULL)
                gDeleteTrackMapFn(p->pTrackMap);
            p->pTrackMap = NULL;
        } else {
            const tGlobalDisplaySettings *ds =
                &TheRaceParameters.GlobalDisplaySettings;
            int8_t mode;

            p->pTrackMap = gNewTrackMapFn != NULL
                ? gNewTrackMapFn(CurrentTrackInfo, p->MyCar, p) : NULL;
            if (TheRaceParameters.BeACop != 0) {
                mode = ds->BeTheCopTrackMapMode;
            } else {
                mode = PlayerNumPlayers != 1 ? ds->TwoPlayerTrackMapMode
                                             : ds->OnePlayerTrackMapMode;
                if (p->PlayerSettings.PlayersHudState == 1
                    && mode == TRACKMAP_MODE_OFF)
                    mode = 2;
            }
            player_set_track_map_mode(p, mode);
        }
    }

    if (chg & HUD_TIRE_FORCE) {
        v = (int32_t)(f >> 1) & 1;
        flailer_set_visibility(h, 0x9fae4af3, v);
        flailer_set_visibility(h, 0x13be6877, v);
        flailer_set_visibility(h, 0x12420a8a, v);
        flailer_set_visibility(h, 0xdebde88b, v);
        flailer_set_visibility(h, 0xb7ffbcd8, v);
        p->pFlailerTireForce[0] = find(h, 0x13be6877, FLAILER_TYPE_BITMAP);
        p->pFlailerTireForce[1] = find(h, 0x12420a8a, FLAILER_TYPE_BITMAP);
        p->pFlailerTireForce[2] = find(h, 0xdebde88b, FLAILER_TYPE_BITMAP);
        p->pFlailerTireForce[3] = find(h, 0xb7ffbcd8, FLAILER_TYPE_BITMAP);
    }

    if (chg & HUD_PURSUIT)
        show_pursuit(p, h, 0x0b603727, PursuitObjects, "PURSUIT_DUMMY_%d",
                     (int32_t)(f >> 15) & 1);
    if (chg & HUD_PURSUIT_HI)
        show_pursuit(p, h, 0xed9fd777, PursuitHiObjects,
                     "PURSUIT_DUMMY_HI_%d", (int32_t)(f >> 26) & 1);
    if (chg & HUD_PURSUIT_NIS)
        show_pursuit(p, h, 0xa19ae030, PursuitNisObjects,
                     "PURSUIT_DUMMY_NIS_%d", (int32_t)(f >> 27) & 1);

    if (chg & HUD_SCORE) {
        v = (int32_t)(f >> 17) & 1;
        group_visibility(h, 0x5c9c03a7, v);
        if (v == 0) {
            p->pFlailerEventTitle = NULL;
            p->pFlailerEventScore = NULL;
            p->pFlailerScoreTitle = NULL;
            p->pFlailerScoreTotal = NULL;
        } else {
            char buf[16];

            p->pFlailerEventTitle = find(h, 0xa3ff1482, FLAILER_TYPE_TEXT);
            p->pFlailerEventScore = find(h, 0xa3e99d3c, FLAILER_TYPE_TEXT);
            p->pFlailerScoreTitle = find(h, 0x5d8266dc, FLAILER_TYPE_TEXT);
            p->pFlailerScoreTotal = find(h, 0x5d85afbe, FLAILER_TYPE_TEXT);
            hide(p->pFlailerScoreTitle);
            hide(p->pFlailerScoreTotal);
            hide(p->pFlailerEventTitle);
            hide(p->pFlailerEventScore);
            snprintf(buf, sizeof buf, "%d", (int)p->TotalScore);
            if (p->pFlailerScoreTotal != NULL)
                flailertext_set_string(
                    (struct FlailerTextChunk *)p->pFlailerScoreTotal, buf);
        }
    }

    if (chg & HUD_MUSIC) {
        v = (int32_t)(f >> 18) & 1;
        group_visibility(h, 0x6edac70c, v);
        if (v == 0) {
            p->pFlailerMusicTitle = NULL;
            p->pFlailerMusicArtist = NULL;
            p->pFlailerMusicLabel = NULL;
            p->pFlailerMusicEA = NULL;
        } else {
            p->pFlailerMusicTitle = find(h, 0x6fc12a41, FLAILER_TYPE_TEXT);
            p->pFlailerMusicArtist = find(h, 0x3c374056, FLAILER_TYPE_TEXT);
            p->pFlailerMusicLabel = find(h, 0x6f2bb5bf, FLAILER_TYPE_TEXT);
            p->pFlailerMusicEA = find(h, 0x1f87a436, FLAILER_TYPE_TEXT);
            // Shown when a song starts.
            hide(p->pFlailerMusicTitle);
            hide(p->pFlailerMusicArtist);
            hide(p->pFlailerMusicLabel);
            hide(p->pFlailerMusicEA);
        }
    }

    if (chg & HUD_RACE_OVER) {
        v = (int32_t)(f >> 2) & 1;
        group_visibility(h, 0xc707e093, v);
        group_visibility(h, 0x97f9252a, v);
        flailer_set_visibility(h, 0x76494c5b, 0);
        flailer_set_visibility(h, 0x233dfbe1, 0);
        if (v == 1) {
            if (gPlayerFillInRaceOverMessagesFn != NULL)
                gPlayerFillInRaceOverMessagesFn(p);
            if (gRaceFinishedSpeechFn != NULL)
                gRaceFinishedSpeechFn(p->MyCar,
                                      p->MyCar->pRacingCar->FinishReason);
        }
    }

    if (chg & HUD_WRONG_WAY) {
        struct FlailerObjectChunk *o = NULL;

        v = (int32_t)(f >> 14) & 1;
        while ((o = flailer_find_object_by_group(h, 0xbbbb857c,
                                                 FLAILER_TYPE_ANY, o))
               != NULL) {
            flailerobject_set_visibility(o, v);
            if (v == 1 && gPlayerHudStartWrongWayFn != NULL)
                gPlayerHudStartWrongWayFn(p);
        }
    }

    if (chg & HUD_RESET_PROMPT)
        group_visibility(h, 0xf74c9d43, (int32_t)(f >> 16) & 1);

    if (chg & HUD_LETTERBOX)
        eGetView(p->ViewID)->LetterBox = (uint8_t)((f >> 13) & 1);

    if (chg & HUD_CINEMA_BARS) {
        // The bars' screen is shown when the bit is set.
        v = (int32_t)((f >> 25) ^ 1) & 1;
        if (PlayerNumPlayers == 1) {
            screen_visibility(0x49c15518, v);
        } else if (PlayerNumPlayers == 2) {
            if (TheRaceParameters.BeACop == 0
                && (pCurrentRace == NULL
                    || (pCurrentRace->RaceStage != RACE_STAGE_FLYBY
                        && pCurrentRace->RaceStage != RACE_STAGE_PRERACE))) {
                // A race of two hides the whole screen's bars and gives
                // each player its half's.
                screen_visibility(0x49c15518, FLAILER_SCREEN_INVISIBLE);
                screen_visibility(p->PlayerNumber == 0 ? 0xaccbfcb8
                                                       : 0xaccbfcb9, v);
            } else {
                screen_visibility(0x49c15518, v);
            }
        }
    }

    if (chg & HUD_RADAR)
        show_radar(p, h, f, chg);

    if (chg & HUD_BE_THE_COP)
        show_be_the_cop(p, h, f);

    if (chg & HUD_TRACKER) {
        int32_t i;

        group_visibility(h, 0xc258f297, (int32_t)(f >> 20) & 1);
        for (i = 0; i < 7; i++)
            p->pFlailerTracker[i] = find_numbered(h, "TRACKER_%d", i,
                                                  FLAILER_TYPE_BITMAP);
    }

    // Egg 4's group, every call.
    flailer_set_group_visibility(h, 0x06d1f9fb,
                                 gEggIsOnFn != NULL && gEggIsOnFn(4) != 0);

    if ((chg & HUD_NIS_OVERLAY) && gNisOverlaySetVisibleFn != NULL)
        gNisOverlaySetVisibleFn(&p->mFlailerNIS, f & HUD_NIS_OVERLAY);

    p->CurrentHudFeatures = f;
}

// UpdateHud's head, 0x0017ed18 to 0x0017ed34.
void player_update_hud_features(struct Player *p)
{
    uint32_t f = player_determine_hud_features(p);

    if (f != p->CurrentHudFeatures)
        player_set_hud_features(p, f);
}
