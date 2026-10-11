// fredevent -- FrontendDatabase's event calls. See fredevent.h; the decode
// is docs/formats/fred-event.md.

#include "fredevent.h"

#include <string.h>

#include "bmath.h"
#include "cartypeinfo.h"
#include "eefpu.h"
#include "eventrace.h"
#include "fredrace.h"
#include "quickrace.h"
#include "track.h"

extern int32_t bVersionE3;

EventsOpened TheEventsOpened;

// What a NULL table or TrackInfo reads as: the bottom of memory, zeros in
// retail.
static const uint8_t kZeros[8];
static const TrackInfo kNoTrack;

static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16
           | (uint32_t)p[3] << 24;
}

static int16_t rd16(const uint8_t *p)
{
    return (int16_t)(uint16_t)(p[0] | p[1] << 8);
}

// ------------------------------------------------------------- the tree

EventTree *fred_get_event_tree(const FrontendDatabase *f)
{
    if (f->GameType == 8)
        return get_event_tree(bVersionE3 != 0 ? "Championship E3"
                                              : "Championship");
    if (f->GameType == 9)
        return get_event_tree(bVersionE3 != 0 ? "Hot Pursuit E3"
                                              : "Hot Pursuit");
    return NULL;
}

int32_t data_event_select_get_selected_event(const int32_t *d, int32_t type)
{
    if (type == 0)
        return d[2];
    if (type == 1)
        return d[1];
    return 1;
}

void data_event_select_set_selected_event(int32_t *d, int32_t type,
                                          int32_t n)
{
    (void)type;
    if (d[0] == 0)
        d[2] = n;
    else if (d[0] == 1)
        d[1] = n;
}

void data_event_select_set_tree_type(int32_t *d, int32_t type)
{
    d[0] = type;
}

// The event the select screen chose in the game's tree; NULL without the
// tree or the event. Retail has no test for the tree, and reads the bottom
// of memory, which finds no event.
static EventInfo *selected_event(FrontendDatabase *f)
{
    EventTree *t = fred_get_event_tree(f);

    if (t == NULL)
        return NULL;
    return event_tree_get_event_number(
        t, data_event_select_get_selected_event(f->SelectedEventData,
                                                t->nType));
}

// ------------------------------------------------------------- the cars

void fpi_flush_available_cars(FrontendPlayerInfo *p)
{
    int32_t i;

    for (i = 0; i < FRED_NUM_CAR_TYPES; i++)
        p->aCarStatus[i].nStatus = CAR_STATUS_HIDDEN;
}

void fred_make_event_cars_available(FrontendDatabase *f,
                                    const EventTree *tree,
                                    const EventInfo *e)
{
    int32_t p, i;

    for (p = 0; p < 2; p++)
        fpi_flush_available_cars(&f->FrontendPlayers[p]);
    // The event's car indexes are read as retail reads them, past aCars
    // when nCars runs over; the disc's counts are within it.
    for (i = 0; i < e->nCars; i++) {
        int32_t idx = rd16((const uint8_t *)e + offsetof(EventInfo, aCars)
                           + 2 * i);
        const uint8_t *rec;
        uint32_t w;
        int32_t skin, dash;

        // Retail skips a record at address 0, and a car whose
        // CarTypeInfo would be.
        if (tree->pCars == NULL) {
            if (idx == 0)
                continue;
            rec = kZeros;
        } else {
            rec = tree->pCars + 4 * idx;
        }
        if (CarTypeInfoArray == NULL && rec[2] == 0)
            continue;
        w = rd32(rec);
        skin = (int32_t)(w >> 24 & 0xf);
        if (skin == 0)
            skin = -1;
        dash = (int32_t)(w >> 30 & 1);
        for (p = 0; p < 2; p++)
            fpi_set_car_availability(&f->FrontendPlayers[p],
                                     CAR_STATUS_AVAILABLE, rec[2], skin,
                                     dash);
    }
}

void fred_maybe_set_selected_car_for_multi_track_event(FrontendDatabase *f)
{
    const RideInfo *ride;
    EventInfo *e;

    if (!fred_use_tree_event(f))
        return;
    ride = fpi_get_selected_ride_info(&f->FrontendPlayers[0], Fred.GameType);
    e = selected_event(f);
    // Retail's SetSelectedCar reads a NULL event's type as 0, a race, and
    // sets nothing.
    if (e != NULL)
        event_info_set_selected_car(e, ride->Type, ride->SkinNumber,
                                    ride->HasDash != 0);
}

void fred_continue_multi_track_event(FrontendDatabase *f)
{
    int32_t car = 0, skin = 0, dash = 0;
    EventInfo *e;

    if (!fred_use_tree_event(f))
        return;
    e = selected_event(f);
    // Retail's car is its stack's leftovers when the event is not a
    // knockout or a tournament; the port's is 0.
    if (e != NULL)
        event_info_get_selected_car(e, &car, &skin, &dash);
    fpi_assign_car_of_type(&f->FrontendPlayers[0], Fred.GameType, car,
                           (uint32_t)skin, dash);
    fred_start_race(f);
}

// ------------------------------------------------- the challenge knockout

// tRandomlyPickableTrackInfo: a TrackInfo and a direction. Retail keeps
// them on a bList of bMalloc'd nodes; the port keeps them in order in an
// array, two for each track a TrackNumber can name and the race's own.
typedef struct PickableTrack {
    const TrackInfo *Info;
    int32_t          Direction;
} PickableTrack;

#define MAX_PICKABLE (2 * 256 + 1)

static PickableTrack pickable[MAX_PICKABLE];

// RandomizeList, 0x00184578: each place in turn swapped with one bRandom
// picks out of all of them.
static void randomize(PickableTrack *a, int32_t n)
{
    int32_t k;

    for (k = 0; k < n; k++) {
        int32_t j = bRandomI(n, &bDefaultSeed);
        PickableTrack t;

        // bRandom's answer is under n; retail does not test it.
        if ((uint32_t)j >= (uint32_t)n)
            continue;
        t = a[k];
        a[k] = a[j];
        a[j] = t;
    }
}

// The knockout's race `s` from a picked track: retail's EventTrack word
// written field by field, as SetFromRace writes it, but with the track's
// own time of day and laps.
static void pick_word(EventTrack *t, const PickableTrack *pt,
                      const RaceParameters *rp)
{
    const TrackInfo *ti = pt->Info != NULL ? pt->Info : &kNoTrack;
    uint32_t w;

    t->b[0] = (uint8_t)ti->TrackNumber;
    w = rd32(t->b);
    w = (w & 0xfffff3ffu) | (uint32_t)(rp->TrackWeather & 3) << 10;
    w = (w & 0xffffcfffu) | (uint32_t)(ti->TimeOfDay & 3) << 12;
    w = (w & 0xfffffdffu) | (uint32_t)(pt->Direction & 1) << 9;
    w = (w & 0xfe03ffffu)
        | ((uint32_t)ee_trunc_w(ee_mul(rp->TrafficDensity, 100.0f)) & 0x7f)
              << 18;
    w = (w & 0x01ffffffu)
        | (uint32_t)ee_trunc_w(ee_mul(rp->TrafficOncoming, 100.0f)) << 25;
    w = (w & 0xfffc3fffu) | (ti->Point2Point != 0 ? 0x4000u : 0x8000u);
    t->b[0] = (uint8_t)w;
    t->b[1] = (uint8_t)(w >> 8);
    t->b[2] = (uint8_t)(w >> 16);
    t->b[3] = (uint8_t)(w >> 24);
}

void fred_pick_random_tracks_for_challenge_knockout(FrontendDatabase *f)
{
    const RaceParameters *rp = &TheRaceParameters;
    RaceEvent *ev = &TheRaceEvent;
    int32_t n = 0, i, k, s;

    (void)f;
    // One place is kept for the race's own track.
    for (i = 0; i <= HighestTrackNumber; i++) {
        const TrackInfo *ti = track_get_info(i);
        int32_t dir;

        if (ti == NULL)
            continue;
        for (dir = 0; dir < 2; dir++) {
            if (is_track_unlocked(ti->SameAsTrackNumber, dir)
                && n < MAX_PICKABLE - 1) {
                pickable[n].Info = ti;
                pickable[n].Direction = dir;
                n++;
            }
        }
    }
    randomize(pickable, n);

    // The race's track and direction to the front, or a new one there
    // (GetTrackInfo's, NULL for a track it does not have).
    for (k = 0; k < n; k++)
        if (pickable[k].Info->TrackNumber == rp->TrackNumber
            && pickable[k].Direction == rp->TrackDirection)
            break;
    if (k < n) {
        PickableTrack t = pickable[k];

        memmove(&pickable[1], &pickable[0], (size_t)k * sizeof *pickable);
        pickable[0] = t;
    } else {
        memmove(&pickable[1], &pickable[0], (size_t)n * sizeof *pickable);
        pickable[0].Info = track_get_info(rp->TrackNumber);
        pickable[0].Direction = rp->TrackDirection;
        n++;
    }

    // Each race takes the list's head. Retail takes the list's own head
    // once it is empty; the port stops there. A race past aTracks' eight is
    // not written (retail's goes into aRewards).
    for (s = 0; s < ev->nTracks && s < n; s++)
        if (s < 8)
            pick_word(&ev->aTracks[s], &pickable[s], rp);
}

void fred_setup_fake_race_event_for_challenge_knockout(FrontendDatabase *f)
{
    RaceEvent *ev = &TheRaceEvent;
    const RaceParameters *rp = &TheRaceParameters;
    int32_t players = f->NumPlayerCars;
    int16_t races = (int16_t)(uint16_t)((uint32_t)rp->NumAICars
                                        + (uint32_t)players - 1u);
    int32_t mode, t;

    ev->pState = ev->aOldState;
    ko_state_reset(ev->aOldState);
    strcpy(ev->sName, "Challenge Race Knockout");
    ev->Objective.nData = 3;
    ev->nType = EVENT_RACE_KNOCKOUT;
    ev->nInitialPlayers = (int16_t)players;
    ev->Objective.nType = 1;
    ev->nOpponents = races;
    ev->nTracks = races;
    ev->nNumber = 0;
    ev->nClass = 0;
    ev->nCars = 0;
    ev->nRewards = 0;
    ev->Objective.nEvent = 0;

    mode = Fred.RaceKnockoutSetupData[5];
    if (mode == 0) {
        fred_pick_random_tracks_for_challenge_knockout(f);
    } else if (mode == 1) {
        for (t = 0; t < ev->nTracks && t < 8; t++)
            event_track_set_from_race(&ev->aTracks[t], rp);
    }
    raceevent_reset_results(ev);
}

// --------------------------------------------------------- the race's

int32_t fred_event_word(FrontendDatabase *f)
{
    EventTree *t = fred_get_event_tree(f);
    EventInfo *e;

    if (t == NULL)
        return 0;
    e = event_tree_get_event_number(t, f->nCurrentEvent);
    // Retail asks IsLastOpen of the bottom of memory for a number the tree
    // does not have; nCurrentEvent is always SetRace's event.
    return e != NULL ? event_info_is_last_open(e) : 0;
}

const uint8_t *fred_event_opponent(FrontendDatabase *f, int32_t i)
{
    EventTree *t = fred_get_event_tree(f);
    const EventInfo *e;
    int32_t idx = 0;

    if (t == NULL)
        return NULL;
    e = event_tree_get_event_number(t, f->nCurrentEvent);
    // A number the tree does not have reads index 0 from the bottom of
    // memory, the table's first record. The index is read as retail reads
    // it, past aOpponents for an `i` over 6.
    if (e != NULL)
        idx = rd16((const uint8_t *)e + offsetof(EventInfo, aOpponents)
                   + 2 * i);
    if (t->pOpponents == NULL)
        return NULL;
    return t->pOpponents + 4 * idx;
}

// --------------------------------------------------- the events opened

void events_opened_clear(EventsOpened *l)
{
    l->nCount = 0;
}

void events_opened_add(EventsOpened *l, const EventGoal *g, int32_t n)
{
    if (l->nCount < 4) {
        l->aEvents[l->nCount].nEvent = n;
        l->aEvents[l->nCount].Goal = *g;
        l->nCount++;
    }
}

int32_t events_opened_passed(const EventsOpened *l, int32_t *out,
                             int32_t max, const RaceEvent *ev)
{
    int32_t i, n = 0;

    (void)max;
    for (i = 0; i < l->nCount && i < 4; i++)
        if (raceevent_get_status_goal(ev, &l->aEvents[i].Goal)
            == EVENT_PASSED)
            out[n++] = l->aEvents[i].nEvent;
    return n;
}

int32_t events_opened_num_passed(const EventsOpened *l, const RaceEvent *ev)
{
    int32_t out[8];

    return events_opened_passed(l, out, 8, ev);
}
