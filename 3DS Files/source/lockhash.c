// lockhash -- the world's checksum in parts: see lockhash.h.

#include "lockhash.h"

#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "bmath.h"
#include "car.h"
#include "chopper.h"
#include "race.h"
#include "racecoord.h"
#include "realtime.h"
#include "world.h"

#define MASK      (NETSTEP_RING - 1)
#define DRAW_MASK (LOCKHASH_DRAWS - 1)

const char* const kLockHashParts[LOCKHASH_PARTS] = {
    "time", "seeds", "players", "racers", "cops", "traffic", "race",
};

typedef struct Draw {
    uint32_t frame;
    uint32_t at;
} Draw;

static struct {
    LockHashLogFn log;
    int           on;
    int           logged;     // the window's, once a race
    uint32_t      frame;      // the frame the draws are now
    LockHash      ring[NETSTEP_RING];
    uint32_t      ringFor[NETSTEP_RING];
    Draw          draws[LOCKHASH_DRAWS];
    uint32_t      drawn;      // every draw since GO
    uint32_t      viewSeed;   // bViewSeed's, from GO
} L;

static void say(const char* fmt, ...)
{
    char    line[256];
    va_list ap;

    if (!L.log) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    L.log(line);
}

// ------------------------------------------------------------ the hash

static uint32_t mix(uint32_t h, uint32_t v)
{
    h ^= v;
    h *= 0x01000193u;
    return h ^ (h >> 15);
}

// `n` bytes, a multiple of 4, as words: every float as its bits.
static uint32_t mixBytes(uint32_t h, const void* p, size_t n)
{
    const uint8_t* b = p;
    size_t         i;

    for (i = 0; i + 4 <= n; i += 4) {
        uint32_t v;

        memcpy(&v, b + i, 4);
        h = mix(h, v);
    }
    return h;
}

#define SPAN(type, first, last) \
    (offsetof(type, last) + sizeof(((type*)0)->last) - offsetof(type, first))

static uint32_t mixCar(uint32_t h, const Car* c)
{
    h = mix(h, (uint32_t)c->TheControlMode);
    h = mix(h, (uint32_t)c->TheMovementMode);
    return mixBytes(h, &c->State.GeometryPosition,
                    SPAN(CarState, GeometryPosition, DistanceMoved));
}

// The cars of the table from `first` to `last`, each with its slot.
static uint32_t mixCars(const World* w, int32_t first, int32_t last)
{
    uint32_t h = 0x811c9dc5u;
    int32_t  i;

    if (first < 0) first = 0;
    if (last > w->TotalNumCars) last = w->TotalNumCars;
    for (i = first; i < last; i++) {
        h = mix(h, (uint32_t)i);
        if (w->CarTable[i] != NULL) h = mixCar(h, w->CarTable[i]);
    }
    return h;
}

static uint32_t mixChopper(uint32_t h, const struct Chopper* c)
{
    if (c == NULL) return mix(h, 0);
    h = mix(h, 1);
    h = mixBytes(h, &c->TimeUntilThink, sizeof c->TimeUntilThink);
    h = mixBytes(h, &c->Plan, SPAN(struct Chopper, Plan, MoveMode));
    h = mixBytes(h, &c->TargetDistance, sizeof c->TargetDistance);
    return mixBytes(h, &c->BombRunType,
                    SPAN(struct Chopper, BombRunType, New960));
}

static uint32_t mixRace(const Race* r, const RaceCoordinator* rc)
{
    uint32_t h = 0x811c9dc5u;
    int32_t  i, n;

    if (rc != NULL) {
        h = mix(h, (uint32_t)rc->CurrentRCState);
        h = mix(h, (uint32_t)rc->RCExecutingMessage);
        h = mix(h, (uint32_t)rc->DisplayingCountdownNumber);
        h = mix(h, (uint32_t)rc->BeforePauseRCState);
    }
    if (r == NULL) return mix(h, 0);
    h = mixBytes(h, r, SPAN(Race, RaceStage, DetectedOneCarRemaining));
    h = mix(h, (uint32_t)r->NumLapsInRace);
    h = mix(h, (uint32_t)r->ForceRaceFinishPosition);
    h = mix(h, (uint32_t)r->ForceRaceFinishPlayerNum);
    n = r->NumRacingCars;
    if (n < 0) n = 0;
    if (n > RACE_MAX_RACING_CARS) n = RACE_MAX_RACING_CARS;
    for (i = 0; i < n; i++)
        h = mixBytes(h, &r->RacingCarTable[i].CurrentBoundaryRegion,
                     SPAN(struct RacingCar, CurrentBoundaryRegion,
                          AverageSpeed));
    return h;
}

void lockhash_world(World* w, LockHash* h)
{
    uint32_t t;

    memset(h, 0, sizeof *h);
    if (w == NULL) return;
    t = mix(0x811c9dc5u, (uint32_t)WorldTimer);
    t = mixBytes(t, &w->fTimeToRemainPaused,
                 SPAN(World, fTimeToRemainPaused, fTimeScaleTimer));
    t = mix(t, (uint32_t)w->TimeScaleCallbackParam);
    h->part[LOCKHASH_TIME] = mix(t, world_calculate_debug_checksum(w));
    h->part[LOCKHASH_SEEDS] =
        mix(mix(0x811c9dc5u, bDefaultSeed), w->WorldRandomSeed);
    h->part[LOCKHASH_PLAYERS] = mixCars(w, 0, w->AICarPos);
    h->part[LOCKHASH_RACERS]  = mixCars(w, w->AICarPos, w->CopCarPos);
    h->part[LOCKHASH_COPS]    = mixChopper(
        mixCars(w, w->CopCarPos, w->TrafficCarPos), w->Helicopter);
    h->part[LOCKHASH_TRAFFIC] =
        mixCars(w, w->TrafficCarPos, w->TotalNumCars);
    h->part[LOCKHASH_RACE] = mixRace(pCurrentRace, pRaceCoordinator);
}

uint16_t lockhash_fold(const LockHash* h)
{
    uint32_t s = 0;
    int      i;

    for (i = 0; i < LOCKHASH_PARTS; i++) s = s * 33u + h->part[i];
    return (uint16_t)((s >> 16) + s);
}

// ------------------------------------------------------------ the draws

static void watch(void* at)
{
    Draw* d = &L.draws[L.drawn & DRAW_MASK];

    d->frame = L.frame;
    d->at    = (uint32_t)(uintptr_t)at;
    L.drawn++;
}

// ------------------------------------------------------------ the race's

void lockhash_start(LockHashLogFn log)
{
    int i;

    memset(&L, 0, sizeof L);
    L.log = log;
    L.on  = 1;
    for (i = 0; i < NETSTEP_RING; i++) L.ringFor[i] = NETSTEP_NONE;
    bDefaultSeedWatch = watch;
    L.viewSeed = bDefaultSeed ^ 0x5bd1e995u;
    bViewSeed  = &L.viewSeed;
}

void lockhash_stop(void)
{
    if (!L.on) return;
    L.on = 0;
    if (bDefaultSeedWatch == watch) bDefaultSeedWatch = NULL;
    if (bViewSeed == &L.viewSeed) bViewSeed = &bDefaultSeed;
}

static void logParts(const char* what, uint32_t n, const LockHash* h)
{
    say("lockhash: %s %lu time %08lx seeds %08lx players %08lx racers %08lx "
        "cops %08lx traffic %08lx race %08lx",
        what, (unsigned long)n,
        (unsigned long)h->part[LOCKHASH_TIME],
        (unsigned long)h->part[LOCKHASH_SEEDS],
        (unsigned long)h->part[LOCKHASH_PLAYERS],
        (unsigned long)h->part[LOCKHASH_RACERS],
        (unsigned long)h->part[LOCKHASH_COPS],
        (unsigned long)h->part[LOCKHASH_TRAFFIC],
        (unsigned long)h->part[LOCKHASH_RACE]);
}

uint16_t lockhash_ran(uint32_t n, World* w)
{
    LockHash* h = &L.ring[n & MASK];

    lockhash_world(w, h);
    L.ringFor[n & MASK] = n;
    L.frame = n + 1;
    if (n % NETSTEP_LOG_EVERY == 0) logParts("frame", n, h);
    return lockhash_fold(h);
}

// Frame `n`'s draws, LOCKHASH_LINE to a line, from those still kept.
static void logDraws(uint32_t n)
{
    char     line[256];
    size_t   len = 0;
    uint32_t i, first, count = 0, onLine = 0;

    first = L.drawn > LOCKHASH_DRAWS ? L.drawn - LOCKHASH_DRAWS : 0;
    for (i = first; i < L.drawn; i++)
        if (L.draws[i & DRAW_MASK].frame == n) count++;
    say("lockhash: draws %lu: %lu", (unsigned long)n, (unsigned long)count);
    for (i = first; i < L.drawn; i++) {
        const Draw* d = &L.draws[i & DRAW_MASK];

        if (d->frame != n) continue;
        if (onLine == 0)
            len = (size_t)snprintf(line, sizeof line, "lockhash: at %lu:",
                                   (unsigned long)n);
        len += (size_t)snprintf(line + len, sizeof line - len, " %08lx",
                                (unsigned long)d->at);
        if (++onLine == LOCKHASH_LINE) {
            say("%s", line);
            onLine = 0;
        }
    }
    if (onLine) say("%s", line);
}

void lockhash_differs(uint32_t n)
{
    uint32_t k;

    if (!L.on || L.logged) return;
    L.logged = 1;
    say("lockhash: frame %lu differs; the %d frames up to it", (unsigned long)n,
        LOCKHASH_WINDOW);
    for (k = 0; k < LOCKHASH_WINDOW; k++) {
        uint32_t f = n - (LOCKHASH_WINDOW - 1) + k;

        if (n < LOCKHASH_WINDOW - 1 - k) continue;   // before frame 0
        if (L.ringFor[f & MASK] != f) continue;
        logParts("parts", f, &L.ring[f & MASK]);
        logDraws(f);
    }
}
