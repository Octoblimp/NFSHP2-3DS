// Drives raceovermsg.c and flailerwrap.c for tools/raceover_check.py. A
// script of ops, one per line, fields split on '|':
//
//   lang|L             the language
//   rp|TYPE|NP|COP     TheRaceParameters' RaceType, NumPlayerCars, BeACop
//   ev|USE|TYPE        UseTheRaceEvent's answer, TheRaceEventFields.Type
//   race|N|FINISH      pCurrentRace's NumRacingCars and
//                      FinishLineBoundaryNumber
//   rc|I|PLACE|REASON|TIME|B0|B1|B2|B3|B4  RacingCar I's FinishingOrder,
//                      FinishReason, RaceTime and BestRunningTimes
//   car|I|PLAYER       car I's pPlayer (-1 NULL); its pRacingCar is rc I
//   link|RC|CAR        RacingCar RC's pCar (-1 NULL)
//   player|I|NUM|HUD|CAR  player I's PlayerNumber, HudScreenHash and MyCar
//   bynum|N|I          PlayerPlayersByNumber[N] (-1 NULL)
//   str|ID|TEXT        what GetTranslatedString(ID) answers; any other ID
//                      answers "T" and the number
//   grp|SCREEN|GROUP|Y|MAXC...  the group's text objects, in order, with
//                      these MaxChars; the first at Y, each next 20 below
//   height|BITS        what GetScaledHeight answers, a float's bits
//   fill|I             FillInRaceOverMessages on player I
//   rtig|SCREEN|GROUP|TEXT  RenderTextIntoGroup, and its answer
//   fpos|PLACE|ID      FormatFinishPositionForRaceOverOverlay's text
//   ftime|PACKED|ID    FormatTimeForRaceOverOverlay's text
//
// Every call out of the two prints what it was asked, as the model's stubs
// at retail's addresses do; after fill and rtig every object's visibility
// byte is printed.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "car.h"
#include "cartypeinfo.h"
#include "flailer.h"
#include "flailerwrap.h"
#include "fred.h"
#include "fredrace.h"
#include "player.h"
#include "race.h"
#include "racerun.h"
#include "raceovermsg.h"
#include "racesplit.h"

#define MAX_RC      4
#define MAX_CARS    4
#define MAX_PLAYERS 4
#define MAX_STRINGS 64
#define MAX_CHUNKS  64
#define MAX_GROUPS  8

// What raceovermsg.c reads.
FrontendDatabase Fred;
RaceParameters TheRaceParameters;
RaceEventFields TheRaceEventFields;
Race *pCurrentRace;
struct Player *PlayerPlayersByNumber[2];
int32_t (*gCurrLanguageFn)(void);
float (*gFlailerTextScaledHeightFn)(struct FlailerTextChunk *t);

static Race race;
static struct RacingCar rcs[MAX_RC];
static Car cars[MAX_CARS];
static struct Player players[MAX_PLAYERS];
static int32_t language;
static int32_t useEvent;
static float height;

static struct { int32_t id; char text[128]; } strs[MAX_STRINGS];
static int numStrs;

// Every object, in the order made; a group is a run of them.
static struct FlailerTextChunk *chunks[MAX_CHUNKS];
static int numChunks;
static struct { uint32_t screen, group; int first, n; } groups[MAX_GROUPS];
static int numGroups;

static int64_t num(const char *s)
{
    return strtoll(s, NULL, 0);
}

static float bitsf(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static int chunk_index(const void *o)
{
    int i;

    for (i = 0; i < numChunks; i++)
        if ((const void *)chunks[i] == o)
            return i;
    return -1;
}

static int32_t curr_language(void)
{
    return language;
}

// One buffer for every answer, as main.c's: the next call overwrites it.
static const char *translate(int32_t id)
{
    static char one[256];
    int i;

    printf("  tr %d\n", id);
    for (i = 0; i < numStrs; i++)
        if (strs[i].id == id) {
            snprintf(one, sizeof one, "%s", strs[i].text);
            return one;
        }
    snprintf(one, sizeof one, "T%d", id);
    return one;
}

static void knockout_speech(struct Player *p, int32_t advances)
{
    printf("  kospeech p%d %d\n", (int)(p - players), advances);
}

static float scaled_height(struct FlailerTextChunk *t)
{
    printf("  height #%d\n", chunk_index(t));
    return height;
}

// ----------------------------------------------------- the stubbed calls

int32_t fred_use_the_race_event(const FrontendDatabase *f)
{
    (void)f;
    printf("  usetre\n");
    return useEvent;
}

struct Player *racingcar_get_player(const struct RacingCar *rc)
{
    if (rc->pCar == NULL)
        return NULL;
    return rc->pCar->pPlayer;
}

Timer *racingcar_get_last_best_lap_time(struct RacingCar *rc)
{
    return &rc->BestRunningTimes[pCurrentRace->FinishLineBoundaryNumber];
}

struct FlailerObjectChunk *flailer_find_object_by_group(
    uint32_t screen, uint32_t group, int32_t type,
    struct FlailerObjectChunk *after)
{
    int g, i;

    if (after == NULL)
        printf("  find %08x %08x %d -\n", screen, group, type);
    else
        printf("  find %08x %08x %d #%d\n", screen, group, type,
               chunk_index(after));
    for (g = 0; g < numGroups; g++) {
        if (groups[g].screen != screen || groups[g].group != group)
            continue;
        if (after == NULL)
            return groups[g].n > 0 ? &chunks[groups[g].first]->Object : NULL;
        for (i = 0; i < groups[g].n - 1; i++)
            if (&chunks[groups[g].first + i]->Object == after)
                return &chunks[groups[g].first + i + 1]->Object;
        return NULL;
    }
    return NULL;
}

void flailerobject_set_visibility(struct FlailerObjectChunk *o, int32_t v)
{
    printf("  vis #%d %d\n", chunk_index(o), v);
    o->Visibility = (int8_t)v;
}

void flailertext_set_string(struct FlailerTextChunk *t, const char *s)
{
    printf("  str #%d [%s]\n", chunk_index(t), s);
}

// ----------------------------------------------------------------- dump

static void dump_vis(void)
{
    int i;

    printf("  visible");
    for (i = 0; i < numChunks; i++)
        printf(" %d", chunks[i]->Object.Visibility);
    printf("\n");
}

static struct Player *player_or_null(int64_t i)
{
    return i < 0 ? NULL : &players[i];
}

int main(int argc, char **argv)
{
    static char line[512];
    FILE *sc;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: raceover_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    pCurrentRace = &race;
    for (i = 0; i < MAX_CARS; i++) {
        cars[i].pRacingCar = &rcs[i];
        rcs[i].pCar = &cars[i];
    }
    gCurrLanguageFn = curr_language;
    gRaceOverTranslateFn = translate;
    gMaybeDoKnockoutRaceOverSpeechFn = knockout_speech;
    gFlailerTextScaledHeightFn = scaled_height;

    while (fgets(line, sizeof line, sc)) {
        char *arg[40];
        const char *op;
        int n = 0;
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        printf("> %s\n", line);
        for (t = strtok(line, "|"); t && n < 40; t = strtok(NULL, "|"))
            arg[n++] = t;
        op = arg[0];
        if (!strcmp(op, "lang")) {
            language = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "rp")) {
            TheRaceParameters.RaceType = (int32_t)num(arg[1]);
            TheRaceParameters.NumPlayerCars = (int32_t)num(arg[2]);
            TheRaceParameters.BeACop = (int32_t)num(arg[3]);
        } else if (!strcmp(op, "ev")) {
            useEvent = (int32_t)num(arg[1]);
            TheRaceEventFields.Type = (int16_t)num(arg[2]);
        } else if (!strcmp(op, "race")) {
            race.NumRacingCars = (int32_t)num(arg[1]);
            race.FinishLineBoundaryNumber = (int8_t)num(arg[2]);
        } else if (!strcmp(op, "rc")) {
            struct RacingCar *rc = &rcs[num(arg[1])];

            rc->FinishingOrder = (int8_t)num(arg[2]);
            rc->FinishReason = (int16_t)num(arg[3]);
            rc->RaceTime.PackedTime = (uint32_t)num(arg[4]);
            for (i = 0; i < 5; i++)
                rc->BestRunningTimes[i].PackedTime = (uint32_t)num(arg[5 + i]);
        } else if (!strcmp(op, "car")) {
            cars[num(arg[1])].pPlayer = player_or_null(num(arg[2]));
        } else if (!strcmp(op, "link")) {
            int64_t c = num(arg[2]);

            rcs[num(arg[1])].pCar = c < 0 ? NULL : &cars[c];
        } else if (!strcmp(op, "player")) {
            struct Player *p = &players[num(arg[1])];

            p->PlayerNumber = (int32_t)num(arg[2]);
            p->HudScreenHash = (uint32_t)num(arg[3]);
            p->MyCar = &cars[num(arg[4])];
        } else if (!strcmp(op, "bynum")) {
            PlayerPlayersByNumber[num(arg[1])] = player_or_null(num(arg[2]));
        } else if (!strcmp(op, "str")) {
            int32_t id = (int32_t)num(arg[1]);

            for (i = 0; i < numStrs && strs[i].id != id; i++)
                ;
            if (i == numStrs)
                numStrs++;
            strs[i].id = id;
            snprintf(strs[i].text, sizeof strs[i].text, "%s", arg[2]);
        } else if (!strcmp(op, "grp")) {
            float y = bitsf((uint32_t)num(arg[3]));

            groups[numGroups].screen = (uint32_t)num(arg[1]);
            groups[numGroups].group = (uint32_t)num(arg[2]);
            groups[numGroups].first = numChunks;
            groups[numGroups].n = n - 4;
            for (i = 4; i < n; i++) {
                int32_t maxc = (int32_t)num(arg[i]);
                struct FlailerTextChunk *c =
                    calloc(1, sizeof *c + (size_t)maxc + 1);

                c->Object.ObjectType = FLAILER_TYPE_TEXT;
                c->Object.Visibility = 7;
                c->Object.Y = y + 20.0f * (float)(i - 4);
                c->MaxChars = maxc;
                chunks[numChunks++] = c;
            }
            numGroups++;
        } else if (!strcmp(op, "height")) {
            height = bitsf((uint32_t)num(arg[1]));
        } else if (!strcmp(op, "fill")) {
            player_fill_in_race_over_messages(&players[num(arg[1])]);
            dump_vis();
        } else if (!strcmp(op, "rtig")) {
            int32_t r = flailer_render_text_into_group(
                (uint32_t)num(arg[1]), (uint32_t)num(arg[2]),
                n > 3 ? arg[3] : "");

            printf("  = %d\n", r);
            dump_vis();
        } else if (!strcmp(op, "fpos")) {
            char buf[128];

            race_over_format_finish_position(buf, (int32_t)num(arg[1]),
                                             (int32_t)num(arg[2]));
            printf("  [%s]\n", buf);
        } else if (!strcmp(op, "ftime")) {
            char buf[128];
            Timer tm;

            tm.PackedTime = (uint32_t)num(arg[1]);
            race_over_format_time(buf, &tm, (int32_t)num(arg[2]));
            printf("  [%s]\n", buf);
        } else {
            printf("  ?\n");
        }
    }
    return 0;
}
