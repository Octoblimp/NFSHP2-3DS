// endtimes -- the times a finished race shows; endtimes.h has the map.

#include "endtimes.h"

#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "bprintf.h"
#include "car.h"
#include "cartypeinfo.h"
#include "endresults.h"
#include "flailer.h"
#include "fredend.h"
#include "highscore.h"
#include "player.h"
#include "race.h"
#include "startrace.h"
#include "track.h"

void (*gPostGameLapRecordFn)(int32_t player, int32_t place,
                             TransientStatsElement *row);
void (*gPostGameTimeRecordFn)(int32_t player, int32_t place,
                              TransientStatsElement *row);

LapTimesDisplay *pLapTimesDisplay;

// Everything here is bMalloc'd in pool 16.
#define END_TIMES_POOL 16

// FlailerTextFormatOption 64: the text right-aligned.
#define TEXT_RIGHT_ALIGN 64

// The once-only record speech flags on the screens' list (endgame.h).
#define LAP_RECORD_SPEECH_SAID(s)  ((s)->Zeroed[7])
#define TIME_RECORD_SPEECH_SAID(s) ((s)->Zeroed[8])

// The record speech is for a player who finished in the top three: the
// place starts at 9 and only a better one replaces it.
#define NO_FINISH_POSITION  9
#define SPEECH_FINISH_LIMIT 4

// The best lap's search starts above any lap a race runs.
#define NO_BEST_LAP 99999999

// The lap-record colour (0x0031a000), which the end-game screens' static
// init (0x001e1ea0) makes with PlayerTextColors and DefaultTextColor.
static const bVector4 kLapRecordColor = { 134.0f, 96.0f, 48.0f, 128.0f };

// ------------------------------------------------------------- the seams

static void nothing(EndGameMenusBase *m, BScreenMessage msg,
                    BScreenCallbackData *data)
{
    (void)m;
    (void)msg;
    (void)data;
}

static const char *get_translated_string(int32_t id)
{
    const char *s = gStartRaceTranslateFn != NULL ? gStartRaceTranslateFn(id)
                                                  : NULL;

    return s != NULL ? s : "NOT TRANSLATED PROPERLY";
}

static const char *get_translated_string_by_name(const char *s)
{
    const char *t = gStartRaceTranslateStringFn != NULL
                        ? gStartRaceTranslateStringFn(s) : NULL;

    return t != NULL ? t : s;
}

// CarTypeInfo::GetShortName, 0x00187eb8, as endresults.c's.
static const char *car_type_info_get_short_name(const CarTypeInfo *ct)
{
    return get_translated_string(ct->pCarSpecs->FullName);
}

// SprintfAndHash, 0x001dc4d0, as endresults.c's.
static uint32_t sprintf_and_hash(const char *fmt, int32_t n)
{
    char buf[32];

    snprintf(buf, sizeof buf, fmt, (int)n);
    return bchunk_hash(buf);
}

static void post_game_record(void (*fn)(int32_t, int32_t,
                                        TransientStatsElement *),
                             int32_t player, int32_t place,
                             TransientStatsElement *row)
{
    if (fn != NULL)
        fn(player, place, row);
}

static int32_t is_time(Timer t)
{
    return t.PackedTime != 0 && t.PackedTime != HIGH_SCORE_NO_TIME;
}

// ------------------------------------------------------------- who set it

// Retail reads PlayerPlayersByIndex unchecked up to NumPlayers; the port
// stops at its two and skips an empty one.
static int32_t which_player(const FredHighScore *e, int lap)
{
    int32_t n = PlayerNumPlayers < 2 ? PlayerNumPlayers : 2;
    int32_t i;

    for (i = 0; i < n; i++) {
        const struct Player *p = PlayerPlayersByIndex[i];

        if (p == NULL)
            continue;
        if ((lap ? p->BestLapRecordData : p->BestTotalRecordData) == e)
            return p->PlayerNumber;
    }
    return -1;
}

int32_t which_player_set_lap_time_record(const FredHighScore *e)
{
    return which_player(e, 1);
}

int32_t which_player_set_total_time_record(const FredHighScore *e)
{
    return which_player(e, 0);
}

// ------------------------------------------------------- the best times

const EndGameMenusVTable kBestLapTimesVTable = {
    nothing,
    endgame_menus_base_handle_event,
    nothing,
    nothing,
    best_lap_times_destroy,
};

const EndGameMenusVTable kBestTotalTimesVTable = {
    nothing,
    endgame_menus_base_handle_event,
    nothing,
    nothing,
    best_total_times_destroy,
};

// Who the record speech is for: the first row this race set, its place
// from 0, the player's row of TransientStats and the better of 9 and
// where the player finished.
typedef struct RecordSpeech {
    int32_t                Player;
    int32_t                Place;
    TransientStatsElement *Row;
    int32_t                Finish;
} RecordSpeech;

// The first racing car's type, whose class both screens look the records
// up by. Retail reads through pCurrentRace unchecked; the port answers
// NULL, which finds no records.
static const CarTypeInfo *first_car_type(void)
{
    const Race *r = pCurrentRace;
    const struct RacingCar *rc = r != NULL ? r->pRacingCars[0] : NULL;

    if (rc == NULL || rc->pCar == NULL)
        return NULL;
    return rc->pCar->pCarTypeInfo;
}

static void hide_row(uint32_t hash, uint32_t pos, uint32_t name,
                     uint32_t type, uint32_t time)
{
    flailer_set_visibility(hash, pos, FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(hash, name, FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(hash, type, FLAILER_OBJECT_INVISIBLE);
    flailer_set_visibility(hash, time, FLAILER_OBJECT_INVISIBLE);
}

// Row k (1 to 5): the record's place, name, car and time, in the colour of
// the player who set it this race. The first such row is the speech's.
// Retail's GetDriver for the speech's row takes whether the player is 1,
// and the one for the place takes the player; the port keeps both.
// Retail indexes PlayerTextColors by the player unchecked (2 lands on
// DefaultTextColor); the port is DefaultTextColor for anything but 0
// and 1. A name the table does not have, which retail prints from NULL,
// is "".
static void show_record(uint32_t hash, const FredHighScore *e, int32_t k,
                        int32_t (*which)(const FredHighScore *),
                        RecordSpeech *rs)
{
    TransientStats *ts = &Fred.TransientStatsTable;
    uint32_t pos = sprintf_and_hash("POS_%d", k);
    uint32_t name = sprintf_and_hash("NAME_%d", k);
    uint32_t type = sprintf_and_hash("TYPE_%d", k);
    uint32_t time = sprintf_and_hash("TIME_%d", k);
    const bVector4 *color = &DefaultTextColor;
    const char *who;
    char buf[32];
    int32_t pl;

    if (e == NULL || !is_time(e->Time)) {
        hide_row(hash, pos, name, type, time);
        return;
    }
    flailer_set_visibility(hash, pos, FLAILER_OBJECT_VISIBLE);
    flailer_set_visibility(hash, name, FLAILER_OBJECT_VISIBLE);
    flailer_set_visibility(hash, type, FLAILER_OBJECT_VISIBLE);
    flailer_set_visibility(hash, time, FLAILER_OBJECT_VISIBLE);
    end_game_print_timer(buf, e->Time, 0);
    flailer_printf(hash, pos, "%2d", (int)k);
    who = fred_lookup_player_name_from_table(&Fred, e->NameIndex);
    flailer_printf(hash, name, "%s", who != NULL ? who : "");
    flailer_printf(hash, type, "%s",
                   get_translated_string_by_name(
                       car_type_info_get_short_name(
                           cartypeinfo_get(e->CarType))));
    flailer_printf(hash, time, "%s", buf);
    pl = which(e);
    if (pl != -1) {
        if (pl == 0 || pl == 1)
            color = &PlayerTextColors[pl];
        if (rs->Player == -1) {
            const TransientStatsElement *d;

            rs->Player = pl;
            rs->Place = k - 1;
            rs->Row = transient_stats_get_driver(ts, pl == 1);
            d = transient_stats_get_driver(ts, pl);
            if (d != NULL && d->FinishPosition < rs->Finish)
                rs->Finish = d->FinishPosition;
        }
    }
    flailer_set_object_color(hash, pos, color);
    flailer_set_object_color(hash, name, color);
    flailer_set_object_color(hash, type, color);
    flailer_set_object_color(hash, time, color);
    flailer_set_text_format_option(hash, time, TEXT_RIGHT_ALIGN);
}

// The five rows from `table`, then the speech once per list: for a row
// this race set, by a player who finished in the top three.
// pEndGameScreens is read unchecked in retail; with none the port says
// nothing.
static void show_records(EndGameMenusBase *m, const FredHighScore *table,
                         int32_t (*which)(const FredHighScore *),
                         int32_t lap)
{
    RecordSpeech rs = { -1, 0, NULL, NO_FINISH_POSITION };
    EndGameScreens *s;
    int32_t i;

    for (i = 0; i < BEST_TIMES_ROWS; i++)
        show_record(m->ScreenHash, table != NULL ? &table[i] : NULL, i + 1,
                    which, &rs);
    s = pEndGameScreens;
    if (s == NULL)
        return;
    if (lap) {
        if (LAP_RECORD_SPEECH_SAID(s) == 0 && rs.Player != -1
            && rs.Finish < SPEECH_FINISH_LIMIT && rs.Row != NULL)
            post_game_record(gPostGameLapRecordFn, rs.Player, rs.Place,
                             rs.Row);
        LAP_RECORD_SPEECH_SAID(s) = 1;
    } else {
        if (TIME_RECORD_SPEECH_SAID(s) == 0 && rs.Player != -1
            && rs.Finish < SPEECH_FINISH_LIMIT && rs.Row != NULL)
            post_game_record(gPostGameTimeRecordFn, rs.Player, rs.Place,
                             rs.Row);
        TIME_RECORD_SPEECH_SAID(s) = 1;
    }
}

static void show_track_name(uint32_t hash)
{
    flailer_set_language_id(hash, RACE_RESULTS_OBJ_TRACK_NAME,
                            get_the_right_track_language_id(
                                CurrentTrackInfo,
                                TheRaceParameters.TrackDirection));
}

EndGameMenusBase *best_lap_times_construct(void *mem, uint32_t hash,
                                           BScreenCallbackData *data)
{
    EndGameMenusBase *m = (EndGameMenusBase *)mem;
    const RaceParameters *rp = &TheRaceParameters;
    const CarTypeInfo *ct;
    const FredHighScore *table = NULL;

    (void)data;
    endgame_menus_base_construct(m, hash);
    m->vt = &kBestLapTimesVTable;
    ct = first_car_type();
    if (ct != NULL)
        table = fred_get_best_lap_times_table(&Fred, rp->TrackNumber,
                                              ct->CarClass,
                                              rp->TrackDirection);
    show_track_name(m->ScreenHash);
    show_records(m, table, which_player_set_lap_time_record, 1);
    return m;
}

EndGameMenusBase *best_total_times_construct(void *mem, uint32_t hash,
                                             BScreenCallbackData *data)
{
    EndGameMenusBase *m = (EndGameMenusBase *)mem;
    const RaceParameters *rp = &TheRaceParameters;
    const CarTypeInfo *ct;
    const FredHighScore *table = NULL;

    (void)data;
    endgame_menus_base_construct(m, hash);
    m->vt = &kBestTotalTimesVTable;
    ct = first_car_type();
    show_track_name(m->ScreenHash);
    if (ct != NULL)
        table = fred_get_best_total_times_table(&Fred, rp->TrackNumber,
                                                ct->CarClass,
                                                rp->TrackDirection,
                                                rp->NumLapsInRace);
    show_records(m, table, which_player_set_total_time_record, 0);
    return m;
}

void best_lap_times_destroy(EndGameMenusBase *m, int32_t flags)
{
    m->vt = &kBestLapTimesVTable;
    endgame_menus_base_destroy(m, flags);
}

void best_total_times_destroy(EndGameMenusBase *m, int32_t flags)
{
    m->vt = &kBestTotalTimesVTable;
    endgame_menus_base_destroy(m, flags);
}

// ------------------------------------------------------------- lap times

// The player's name on the text object `obj`, through a 128-byte buffer.
// Retail sets the string of FindFlailerObject's answer unchecked.
static void show_player_name(uint32_t hash, uint32_t obj,
                             const struct Player *p)
{
    struct FlailerObjectChunk *o = flailer_find_object(hash, obj,
                                                       FLAILER_TYPE_TEXT);
    char buf[128];

    b_snprintf(buf, sizeof buf, "%s", p->PlayerSettings.PlayerName);
    if (o != NULL)
        flailertext_set_string((struct FlailerTextChunk *)(void *)o, buf);
}

// The fastest of laps 1 to 9 from 0, -1 for none. Retail skips a lap
// whose GetSeconds is 0, which is a lap of 0 ticks.
static int32_t best_lap(const TransientStatsElement *e)
{
    int32_t best = NO_BEST_LAP;
    int32_t place = -1;
    int32_t i;

    if (e == NULL)
        return -1;
    for (i = 0; i < LAP_TIMES_ROWS; i++) {
        int32_t t = (int32_t)e->LapTimes[i + 1].PackedTime;

        if (t != 0 && t < best) {
            best = t;
            place = i;
        }
    }
    return place;
}

// Lap k of `e` on `obj`, in the lap-record colour if it is the best.
// Retail prints the time with itself as the format; no time has a '%',
// so the port prints it with "%s".
static void show_lap(uint32_t hash, uint32_t obj,
                     const TransientStatsElement *e, int32_t k, int best)
{
    char buf[32];
    Timer t;

    if (e == NULL) {
        flailer_set_visibility(hash, obj, FLAILER_OBJECT_INVISIBLE);
        return;
    }
    flailer_set_object_color(hash, obj,
                             best ? &kLapRecordColor : &DefaultTextColor);
    flailer_set_visibility(hash, obj, FLAILER_OBJECT_VISIBLE);
    t = e->LapTimes[k];
    if (is_time(t)) {
        end_game_print_timer(buf, t, 0);
        flailer_printf(hash, obj, "%s", buf);
        flailer_set_text_format_option(hash, obj, TEXT_RIGHT_ALIGN);
    } else {
        flailer_set_visibility(hash, obj, FLAILER_OBJECT_INVISIBLE);
    }
}

// The track, the players' names (the second for two player cars), and
// the laps of TransientStats' drivers 0 and 1. With only driver 1 it is
// the first column. With no player there is no more than the track; with
// two player cars and no second player, no more than the first name.
LapTimesDisplay *lap_times_display_construct(LapTimesDisplay *d,
                                             uint32_t hash)
{
    TransientStats *ts = &Fred.TransientStatsTable;
    const struct Player *p;
    const TransientStatsElement *a, *b;
    int32_t np = TheRaceParameters.NumPlayerCars;
    int32_t na, nb, n, bestA, bestB, i;

    d->ScreenHash = hash;
    show_track_name(hash);
    p = PlayerPlayersByIndex[0];
    if (p == NULL) {
        p = PlayerPlayersByIndex[1];
        if (p == NULL)
            return d;
    }
    show_player_name(hash, LAP_TIMES_OBJ_P1_NAME, p);
    if (np == 2) {
        p = PlayerPlayersByIndex[1];
        if (p == NULL)
            return d;
        show_player_name(hash, LAP_TIMES_OBJ_P2_NAME, p);
    }
    a = transient_stats_get_driver(ts, 0);
    b = transient_stats_get_driver(ts, 1);
    if (a == NULL) {
        a = b;
        b = NULL;
    }
    na = a != NULL ? a->NumLapTimes : 0;
    nb = b != NULL ? b->NumLapTimes : 0;
    n = na > nb ? na : nb;
    bestA = best_lap(a);
    bestB = best_lap(b);
    for (i = 0; i < LAP_TIMES_ROWS; i++) {
        int32_t k = i + 1;
        uint32_t lapName = sprintf_and_hash("LAPNAME_%d", k);
        uint32_t lap = sprintf_and_hash("LAP_%d", k);
        uint32_t p1 = sprintf_and_hash("P1_LAP_%d", k);
        uint32_t p2 = sprintf_and_hash("P2_LAP_%d", k);

        flailer_printf(hash, lap, "%d", (int)k);
        show_lap(hash, p1, a, k, bestA == i);
        show_lap(hash, p2, b, k, bestB == i);
        if (i < n) {
            flailer_set_visibility(hash, lapName, FLAILER_OBJECT_VISIBLE);
        } else {
            flailer_set_visibility(hash, lapName, FLAILER_OBJECT_INVISIBLE);
            flailer_set_visibility(hash, lap, FLAILER_OBJECT_INVISIBLE);
            flailer_set_visibility(hash, p1, FLAILER_OBJECT_INVISIBLE);
            flailer_set_visibility(hash, p2, FLAILER_OBJECT_INVISIBLE);
        }
    }
    return d;
}

void lap_times_display_destroy(LapTimesDisplay *d, int32_t flags)
{
    if (flags & 1)
        bFree(d);
}

void lap_times_display_handle_event(LapTimesDisplay *d, BScreenMessage msg,
                                    BScreenCallbackData *data)
{
    (void)d;
    if (msg != BMSG_SCREEN_BACK_BUTTON)
        data->noise = 0;
}

// Retail constructs on bMalloc's answer unchecked; the port makes none
// when it fails.
void lap_times_display_callback(struct BGameFlow *gf, BScreenMessage msg,
                                BScreenCallbackData *data)
{
    (void)gf;
    if (msg == BMSG_SCREEN_ACTIVATE) {
        LapTimesDisplay *d = (LapTimesDisplay *)bMalloc(
            sizeof(LapTimesDisplay), "LapTimesDisplay", 0, END_TIMES_POOL);

        pLapTimesDisplay =
            d != NULL ? lap_times_display_construct(d, data->itemHash)
                      : NULL;
    } else if (msg == BMSG_SCREEN_UNACTIVATE) {
        if (pLapTimesDisplay != NULL)
            lap_times_display_destroy(pLapTimesDisplay, 3);
        pLapTimesDisplay = NULL;
    } else {
        lap_times_display_handle_event(pLapTimesDisplay, msg, data);
    }
}
