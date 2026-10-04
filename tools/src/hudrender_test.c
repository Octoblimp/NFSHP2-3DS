// Drives hudrender.c for tools/hudrender_check.py: RenderHud, UpdateHud and
// GetCurrentBestLapRecord on two Players, over playerhud.c, racesplit.c,
// timer.c, flailer.c, bui.c, copmanager.c and raceparams.c with INGAMEB's
// HUD screens loaded. A script of ops, one per line, fields split on '|';
// numbers are C literals:
//
//   load|PATH          a bundle: bui_open, then flailer_add_project
//   rp|NAME|V          a TheRaceParameters field
//   elim|N             two drivers in the table, the first eliminated at N
//   pn|N|NAME          player N's PlayerName
//   pl|N|NAME|V...     a field of player N
//   cam|N|NAME|V       player N's camera: what it is and what it answers
//   car|N|NAME|V...    car N; cars 0 and 1 are the players'
//   rc|N|NAME|V...     car N's RacingCar
//   race|NAME|V...     the race
//   w|NAME|V...        the World
//   cm|NAME|V...       the cop manager
//   g|NAME|V...        the globals around them
//   use|N              the player the calls below take
//   set|F              SetHudFeatures(F)
//   ren                RenderHud
//   upd                UpdateHud
//   best|N             GetCurrentBestLapRecord(N); prints best R
//
// After each op the seams print as they are called; then every Player
// field and Flailer object whose printed line changed. Objects print as
// P:I, the project's load number and bui's object index; a pointer to
// anything else prints "stray", and every pointer field starts as one, so
// that a field nothing writes stays so.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bui.h"
#include "cammover.h"
#include "camerainfo.h"
#include "car.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "configitems.h"
#include "copmanager.h"
#include "drivecam.h"
#include "drivetarget.h"
#include "eview.h"
#include "flailer.h"
#include "hudrender.h"
#include "hudtex.h"
#include "player.h"
#include "playerhud.h"
#include "playerinit.h"
#include "playersettings.h"
#include "race.h"
#include "racecoord.h"
#include "racecore.h"
#include "raceinit.h"
#include "raceparams.h"
#include "rcpost.h"
#include "rcstates.h"
#include "realtime.h"
#include "scenery.h"
#include "trackflow.h"
#include "trackmap.h"
#include "world.h"

#define MAX_LOADS 4
#define NUM_VIEWS 4
#define NCARS     10
#define NPURSUITS 3
#define NCOPS     7

// ------------------------------------------------------------ the globals
//
// What the linked sources read and the rest of the game defines.

RaceParameters  TheRaceParameters;
int32_t         PlayerNumPlayers;
struct Player  *PlayerPlayersByNumber[2];
struct Player  *PlayerPlayersByIndex[2];
Race           *pCurrentRace;
RaceCoordinator *pRaceCoordinator;
World          *pCurrentWorld;
int32_t         RealTimeFrames;
float           PreviousCpuFrameRate;   // mainloop.c's
float           PreviousGpuFrameRate;
int32_t         WorldTimer;
int32_t         WorldTimeFrames;
int32_t         WorldLoopCounter;
int32_t         CameraFollowDefaultCar = 1;
int32_t         CameraFollowThisCarInstead = -1;
TrackInfo      *CurrentTrackInfo;
EggIsOnFn       gEggIsOnFn;
void (*gSetFlailerScreenVisibilityFn)(uint32_t screen, int visibility);
int32_t (*gNisManagerIsPlayingFn)(const struct NisManager *m);
void (*gPlayerClearHudAnimationsFn)(struct Player *p);
struct bSample *(*gGetInGameSampleFn)(const char *name);
void (*gSamplePlayFn)(struct bSample *s, float volume, float a, float b);

// raceparams.c's, none of which IsFreeRun reaches.
uint32_t bDefaultSeed;
int32_t  SkipFERearView, SkipFESpeedoMode, SkipFEEnableJumpCam,
         SkipFEEnableZoneCam;
int32_t (*gCurrLanguageFn)(void);

int32_t bRandomI(int32_t range, uint32_t *seed)
{
    (void)range;
    (void)seed;
    return 0;
}

const CarTypeInfo *cartypeinfo_get(int32_t carType)
{
    (void)carType;
    return NULL;
}

int32_t config_skip_fe(void)
{
    return 0;
}

void player_settings_reset_to_defaults(cPlayerSettings *s)
{
    memset(s, 0, sizeof *s);
}

// ------------------------------------------------------------ the world

static BUI      loads[MAX_LOADS];
static uint8_t *bufs[MAX_LOADS];
static int      numLoads;

static struct Player     *players[2];
static struct Car        *cars[NCARS];
static CharacterInfo      chars[NCARS];
static DriveCameraMover  *cams[2];
static int32_t            povType[2], camExt[2], camBack[2];
static POV                povs[2];
static int32_t            nisWords[2][32];
static eView              views[NUM_VIEWS];
static Race               race;
static RaceCoordinator    coord;
static World              world;
static uint8_t            heli[1024];
static tPursuit           pursuits[NPURSUITS];
static tCop               cops[NCOPS];
static DriverInfo         drivers[2];
static SkinInfo           skin;
static uint8_t            track[16];
static int32_t            egg4;
static int32_t            language;
static int32_t            zone;
static float              lapExact;
static int                curPlayer;

// The cop manager's bytes, as aligned as its pointers need.
static uint64_t           copStore[10600 / 8];
#define COP_BYTES ((uint8_t *)copStore)
#define COP_MGR   ((tCopManager *)(void *)copStore)

// What every pointer field starts as: an object of nothing's.
static uint8_t            dummy[256];

// The one sample GetInGameSample hands out.
static uint8_t            sample[64];

// --------------------------------------------------------- number parsing

static uint32_t num(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static int32_t inum(const char *s)
{
    return (int32_t)strtol(s, NULL, 0);
}

static float fnum(const char *s)
{
    uint32_t v = num(s);
    float    f;
    memcpy(&f, &v, 4);
    return f;
}

static uint32_t fbits(float f)
{
    uint32_t v;
    memcpy(&v, &f, 4);
    return v;
}

// ------------------------------------------------------- Flailer's seams
//
// The renderer's answers, from the object alone, as flailer_test.c's are.

static uint32_t text_len(const struct FlailerTextChunk *t)
{
    uint32_t n = 0;
    while ((int32_t)n < t->MaxChars && t->String[n]) n++;
    return n;
}

static float text_w(struct FlailerTextChunk *t)
{
    uint32_t k = text_len(t) * 9 + t->Object.NameHash % 7;
    return t->Object.ScaleX * (float)k;
}

static float text_h(struct FlailerTextChunk *t)
{
    return t->Object.ScaleY * (float)(t->Object.NameHash % 23 + 8);
}

static bool texture_size(struct FlailerBitmapChunk *b, int32_t *w,
                         int32_t *h)
{
    *w = (int32_t)(b->TextureHash % 509 + 1);
    *h = (int32_t)(b->TextureHash % 251 + 1);
    return true;
}

// ----------------------------------------------------------------- names

static int load_of(const BUI *ui)
{
    for (int i = 0; i < numLoads; i++)
        if (&loads[i] == ui) return i;
    return -1;
}

static const char *obj_name(const void *p, char *buf, size_t n)
{
    BUI     *ui = NULL;
    uint32_t idx = 0;
    if (p == NULL) return "none";
    if (!flailer_object_index((const struct FlailerObjectChunk *)p, &ui,
                              &idx))
        return "stray";
    snprintf(buf, n, "%d:%u", load_of(ui), idx);
    return buf;
}

static const char *player_name(const struct Player *p)
{
    if (p == players[0]) return "p0";
    if (p == players[1]) return "p1";
    return "p?";
}

static const char *car_name(const struct Car *c, char *buf, size_t n)
{
    if (c == NULL) return "none";
    for (int i = 0; i < NCARS; i++)
        if (c == cars[i]) {
            snprintf(buf, n, "car%d", i);
            return buf;
        }
    return "car?";
}

static struct Car *car_or_none(uint32_t v)
{
    int32_t i = (int32_t)v;
    return i >= 0 && i < NCARS ? cars[i] : NULL;
}

// ------------------------------------------- hudfeatures_test.c's seams

static void screen_vis(uint32_t screen, int v)
{
    printf("  screen %08x %d\n", screen, v);
}

static int32_t nis_playing(const struct NisManager *m)
{
    return ((const int32_t *)(const void *)m)[17];
}

static void clear_anims(struct Player *p)
{
    printf("  clear %s\n", player_name(p));
}

static void mirror(struct Player *p, uint32_t on)
{
    printf("  mirror %s %u\n", player_name(p), on);
}

static void init_tach(struct FlailerObjectChunk *needle,
                      struct FlailerObjectChunk *gradient, void *points)
{
    char a[16], b[16];
    printf("  tach %s %s %s\n", obj_name(needle, a, sizeof a),
           obj_name(gradient, b, sizeof b),
           points == players[curPlayer]->FlailerTachPointList ? "pts"
                                                               : "bad");
}

static struct TrackMap *new_map(TrackInfo *t, struct Car *c,
                                struct Player *p)
{
    printf("  newmap t%d c%d %s\n", t == CurrentTrackInfo,
           p != NULL && c == p->MyCar, player_name(p));
    return (struct TrackMap *)calloc(1, sizeof(TrackMap));
}

static void delete_map(struct TrackMap *m)
{
    printf("  delmap %s\n",
           m == players[curPlayer]->pTrackMap ? "ok" : "bad");
    free(m);
}

static void race_over(struct Player *p)
{
    printf("  raceover %s\n", player_name(p));
}

static void speech(struct Car *c, int32_t reason)
{
    printf("  speech c%d %d\n", c == players[curPlayer]->MyCar, reason);
}

static void wrong_way(struct Player *p)
{
    printf("  wrongway %s\n", player_name(p));
}

static void nis_visible(NISOverlayManager *o, uint32_t on)
{
    printf("  nisvis %s %u\n",
           o == &players[curPlayer]->mFlailerNIS ? player_name(
               players[curPlayer]) : "bad", on);
}

static int32_t egg_is_on(int32_t n)
{
    return n == 4 ? egg4 : 0;
}

eView *eGetView(int32_t id)
{
    printf("  view %d\n", id);
    return &views[id];
}

// Words from the car and the units alone, as the model's stub writes.
void ChooseLoadableTextures(int32_t car, int32_t units,
                            tLoadableHudTextures *t)
{
    printf("  textures %d %d\n", car, units);
    t->Speedo = 0x1000u + (uint32_t)car * 16u + (uint32_t)units;
    t->Tach = car % 3 == 0 ? 0u : 0x2000u + (uint32_t)car;
    t->Shadow = 0x3000u + (uint32_t)car;
    t->ThirdPerson = 0x4000u + (uint32_t)units;
}

static const POV *get_pov(CameraMover *m, int index)
{
    int n = m == &cams[0]->base ? 0 : 1;
    printf("  pov %d\n", index);
    if (povType[n] < 0) return NULL;
    povs[n].Type = povType[n];
    return &povs[n];
}

static int is_exterior(CameraMover *m)
{
    int n = m == &cams[0]->base ? 0 : 1;
    printf("  ext\n");
    return camExt[n];
}

static int is_looking_back(CameraMover *m)
{
    int n = m == &cams[0]->base ? 0 : 1;
    printf("  lookback\n");
    return camBack[n];
}

static const CameraMoverVtbl camVtbl = {
    .GetPOV = get_pov,
    .IsExteriorView = is_exterior,
    .IsLookingBack = is_looking_back,
};

// ------------------------------------------------- hudrender.c's seams

static void do_anims(struct Player *p)
{
    printf("  anims %s\n", player_name(p));
}

static void scoring(struct Player *p)
{
    printf("  scoring %s\n", player_name(p));
}

static void start_score(struct Player *p, int32_t what, int32_t value)
{
    printf("  startscore %s %d %d\n", player_name(p), what, value);
}

static void anim(const char *what, struct Player *p,
                 struct FlailerTextChunk *a, struct FlailerTextChunk *b,
                 uint32_t time, int32_t flag)
{
    char x[16], y[16];
    printf("  %s %s %s %s %08x %d\n", what, player_name(p),
           obj_name(a, x, sizeof x), obj_name(b, y, sizeof y), time,
           flag & 0xff);
}

static void speed_anim(struct Player *p, struct FlailerTextChunk *a,
                       struct FlailerTextChunk *b, uint32_t time,
                       int32_t flag)
{
    anim("speedanim", p, a, b, time, flag);
}

static void grow_anim(struct Player *p, struct FlailerTextChunk *a,
                      struct FlailerTextChunk *b, uint32_t time,
                      int32_t flag)
{
    anim("growanim", p, a, b, time, flag);
}

static void pursuit_meter(struct Player *p, int32_t level)
{
    printf("  pursuitmeter %s %d\n", player_name(p), level);
}

static void radar(struct Player *p)
{
    printf("  radar %s\n", player_name(p));
}

static void tracker(struct Player *p, struct Car *c, int32_t j)
{
    char b[16];
    printf("  tracker %s %s %d\n", player_name(p),
           car_name(c, b, sizeof b), j);
}

static void nis_update(NISOverlayManager *o, int32_t playing)
{
    const char *who = "bad";
    for (int k = 0; k < 2; k++)
        if (o == &players[k]->mFlailerNIS) who = player_name(players[k]);
    printf("  nisupdate %s %d\n", who, playing & 0xff);
}

// GetTranslatedString: "T" and the id in hex, one string per id.
static struct {
    int32_t id;
    char    s[16];
} strings[256];
static int numStrings;

static const char *translate(int32_t id)
{
    printf("  translate %x\n", (uint32_t)id);
    for (int i = 0; i < numStrings; i++)
        if (strings[i].id == id) return strings[i].s;
    if (numStrings == 256) exit(2);
    strings[numStrings].id = id;
    snprintf(strings[numStrings].s, sizeof strings[0].s, "T%x",
             (uint32_t)id);
    return strings[numStrings++].s;
}

static int32_t curr_language(void)
{
    return language;
}

static struct bSample *get_sample(const char *name)
{
    printf("  sample %s\n", name);
    return (struct bSample *)(void *)sample;
}

static void play(struct bSample *s, float v, float a, float b)
{
    printf("  play %s %08x %08x %08x\n",
           s == (struct bSample *)(void *)sample ? "ok" : "bad", fbits(v),
           fbits(a), fbits(b));
}

struct Car *world_get_car_by_driver_number(int32_t n)
{
    printf("  bydriver %d\n", n);
    return n >= 0 && n < NCARS ? cars[n] : NULL;
}

struct RacingCar *race_get_racing_car(Race *r, struct Car *c)
{
    (void)r;
    return c->pRacingCar;
}

SkinInfo *cartypeinfo_get_skin_info(int32_t car_type, int32_t skin_number,
                                    int use_default)
{
    printf("  skin %d %d %d\n", car_type, skin_number, use_default);
    skin.ColourSwatchHash = 0x5000u + 16u * (uint32_t)car_type
                            + (uint32_t)skin_number;
    return &skin;
}

int32_t scenery_get_current_zone_number(void)
{
    printf("  zone\n");
    return zone;
}

float race_get_lap_number_exact(Race *r, float pct)
{
    (void)r;
    printf("  lapexact %08x\n", fbits(pct));
    return lapExact;
}

// 64 seconds a lap and a half more.
float tatt_get_time_around_track(TimeAroundTrackTable *t, float lap)
{
    printf("  tatt %s %08x\n",
           t == (TimeAroundTrackTable *)(void *)dummy ? "ok" : "bad",
           fbits(lap));
    return lap * 64.0f + 0.5f;
}

// ------------------------------------------------------------- the dump

typedef struct Field {
    const char *name;
    size_t      off;
    char        kind;       // p an object, w a word, m the TrackMap, s text
    int         count;
    size_t      step;
} Field;

#define FP(f, n) { #f, offsetof(struct Player, f), 'p', n, sizeof(void *) }
#define FW(f, n) { #f, offsetof(struct Player, f), 'w', n, 4 }

// hudfeatures_test.c's fields.
static const Field fields[] = {
    FP(pFlailerSpeedNeedle, 1), FP(pFlailerTachNeedle, 1),
    FP(pFlailerTachGear, 1), FP(pFlailerTachGradient, 1),
    FP(pFlailerRacePosition, 1), FP(pFlailerBigRacePosition, 1),
    FP(pFlailerBigRacePosition2, 1), FP(pFlailerBigRaceExtension, 1),
    FP(pFlailerBigRaceTotal, 1), FP(pFlailerLapCounter, 1),
    FP(pFlailerLapTime, 1), FP(pFlailerBestLap, 1),
    FP(pFlailerRunningSplitTime, 1), FP(pFlailerCompSplitTime, 1),
    FP(pFlailerTireForce, 4), FP(pFlailerSpeedString, 1),
    FP(pFlailerSpeedString2, 1), FP(pFlailerGearString, 1),
    FP(pFlailerShiftUp, 1), FP(pFlailerShiftDown, 1),
    FP(pFlailerPursuitStar, 1), FP(pFlailerPursuitLevel, 4),
    FP(pFlailerPursuitX, 3), FW(PrevPursuitLevel, 1),
    FP(pFlailerTracker, 7), FP(pFlailerEventTitle, 1),
    FP(pFlailerEventScore, 1), FP(pFlailerScoreTitle, 1),
    FP(pFlailerScoreTotal, 1), FP(pFlailerMusicArtist, 1),
    FP(pFlailerMusicTitle, 1), FP(pFlailerMusicLabel, 1),
    FP(pFlailerMusicEA, 1), FP(pFlailerRadarLight, 12),
    FP(pFlailerDamageLight, 5), FP(pFlailerBeTheCopTickets, 4),
    FP(pFlailerLiveSplitStatus, 4), FP(pFlailerLiveSplitSwatch, 4),
    FP(pFlailerLiveSplitPos, 4), FP(pFlailerLiveSplitBG, 4),
    FP(pFlailerLiveSplitBar, 1), FP(pFlailerBeTheCopTime, 1),
    FP(pFlailerBeTheCopHelicopter, 3), FP(pFlailerBeTheCopRoadblock, 3),
    FP(pFlailerLeadTitle, 1), FP(pFlailerLeadTime, 1),
    FW(CurrentHudFeatures, 1), FW(TotalScore, 1),
    { "pTrackMap", offsetof(struct Player, pTrackMap), 'm', 1, 0 },
    FW(TimeTrackMapModeChanged, 1), FW(PursuitObjectPos, 14),
    FW(bRadarOffset, 1), FW(fInitialRadarY, 1),
};
#define NUM_FIELDS (sizeof fields / sizeof fields[0])

// RenderHud's and UpdateHud's own.
static const Field renderFields[] = {
    FP(pFlailerCFPSString, 1), FP(pFlailerGFPSString, 1),
    FP(pFlailerPosString, 1), FP(pFlailerDistString, 1),
    { "strEventScore", offsetof(struct Player, strEventScore), 's', 1, 0 },
    FW(PosChangeTime, 1), FW(PositionFlag, 1), FW(LastRacePosition, 1),
    FW(LastSpeed, 1), FW(TopSpeed, 1), FW(bNewTopSpeed, 1),
    FW(bCheckTopSpeed, 1), FW(SpeedFactor, 1), FW(baPlaceReached, 8),
    FW(tScoreAnimation, 1), FW(New2736, 1),
};
#define NUM_RENDER_FIELDS (sizeof renderFields / sizeof renderFields[0])

// The printed lines, by key, as the last dump left them.
typedef struct Line {
    char *key;
    char *text;
} Line;

static Line  *lines;
static size_t numLines, capLines;

// strdup, which -std=c11 does not declare.
static char *dup(const char *s)
{
    size_t n = strlen(s) + 1;
    return (char *)memcpy(malloc(n), s, n);
}

static void note(const char *key, const char *text)
{
    for (size_t i = 0; i < numLines; i++) {
        if (strcmp(lines[i].key, key) != 0) continue;
        if (strcmp(lines[i].text, text) != 0) {
            free(lines[i].text);
            lines[i].text = dup(text);
            printf("  %s %s\n", key, text);
        }
        return;
    }
    if (numLines == capLines) {
        capLines = capLines ? capLines * 2 : 1024;
        lines = (Line *)realloc(lines, capLines * sizeof *lines);
    }
    lines[numLines].key = dup(key);
    lines[numLines].text = dup(text);
    numLines++;
    printf("  %s %s\n", key, text);
}

static void dump_fields(int n, const Field *fs, size_t count)
{
    const uint8_t *p = (const uint8_t *)players[n];
    char key[64], text[64], nb[16];

    for (size_t f = 0; f < count; f++) {
        const Field *d = &fs[f];
        for (int i = 0; i < d->count; i++) {
            const uint8_t *a = p + d->off + (size_t)i * d->step;
            if (d->count > 1)
                snprintf(key, sizeof key, "p%d.%s[%d]", n, d->name, i);
            else
                snprintf(key, sizeof key, "p%d.%s", n, d->name);
            if (d->kind == 'p') {
                void *v;
                memcpy(&v, a, sizeof v);
                snprintf(text, sizeof text, "%s", obj_name(v, nb, sizeof nb));
            } else if (d->kind == 'm') {
                TrackMap *m;
                memcpy(&m, a, sizeof m);
                if (m == NULL) {
                    snprintf(text, sizeof text, "none");
                } else {
                    snprintf(text, sizeof text, "map:%d",
                             (int)m->CurrentMode);
                }
            } else if (d->kind == 's') {
                int k = 0;
                while (k < 31 && a[k]) k++;
                snprintf(text, sizeof text, "\"%.*s\"", k, (const char *)a);
            } else {
                uint32_t v;
                memcpy(&v, a, 4);
                snprintf(text, sizeof text, "%08x", v);
            }
            note(key, text);
        }
    }
}

static void hex(char *out, const uint8_t *p, uint32_t from, uint32_t to)
{
    static const char digits[] = "0123456789abcdef";
    for (uint32_t i = from; i < to; i++) {
        *out++ = digits[p[i] >> 4];
        *out++ = digits[p[i] & 15];
    }
    *out = 0;
}

// flailer_test.c's dump: all but the bTNode and pFlailerStrip, and a text
// object's characters up to the NUL.
static void dump_objects(void)
{
    static char text[8192];
    char        key[32];

    for (int l = 0; l < numLoads; l++) {
        BUI *ui = &loads[l];
        for (uint32_t s = 0; s < ui->numScreens; s++) {
            const BUIScreen *sc = &ui->screens[s];
            for (uint32_t i = 0; i < sc->count; i++) {
                const BUIObjectRef *r = &ui->objects[sc->first + i];
                const uint8_t      *p = r->payload;
                char               *o = text;
                snprintf(key, sizeof key, "obj %d:%u", l, sc->first + i);
                hex(o, p, 8, 44);
                o += strlen(o);
                *o++ = ' ';
                if ((int8_t)p[40] == FLAILER_TYPE_TEXT && r->size >= 100) {
                    const struct FlailerTextChunk *t =
                        (const struct FlailerTextChunk *)(const void *)p;
                    hex(o, p, 48, 100);
                    o += strlen(o);
                    snprintf(o, sizeof text - (size_t)(o - text),
                             " \"%.*s\"", (int)text_len(t), t->String);
                } else {
                    hex(o, p, 48, r->size);
                }
                note(key, text);
                // A drawn frame clears DirtyFlag, so the next dump shows
                // only what the next op stamps.
                ((uint8_t *)(uintptr_t)p)[43] = 0;
            }
        }
    }
}

static void dump(void)
{
    dump_fields(0, fields, NUM_FIELDS);
    dump_fields(1, fields, NUM_FIELDS);
    dump_fields(0, renderFields, NUM_RENDER_FIELDS);
    dump_fields(1, renderFields, NUM_RENDER_FIELDS);
    dump_objects();
}

// ------------------------------------------------------------------- ops

static void load(const char *path)
{
    FILE *f = fopen(path, "rb");
    long  len;
    BUI  *ui = &loads[numLoads];
    if (!f) {
        printf("  cannot open %s\n", path);
        exit(2);
    }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    bufs[numLoads] = (uint8_t *)malloc((size_t)len);
    if (fread(bufs[numLoads], 1, (size_t)len, f) != (size_t)len) exit(2);
    fclose(f);
    if (!bui_open(ui, bufs[numLoads], 0, (size_t)len)) {
        printf("  bui_open failed\n");
        exit(2);
    }
    numLoads++;
    printf("  loaded %d\n", flailer_add_project(ui) ? 1 : 0);
}

static void set_rp(const char *n, uint32_t v)
{
    RaceParameters         *rp = &TheRaceParameters;
    tGlobalDisplaySettings *d = &rp->GlobalDisplaySettings;

    if (!strcmp(n, "RaceType")) rp->RaceType = (int32_t)v;
    else if (!strcmp(n, "TTT")) rp->TimeTrialTime.PackedTime = v;
    else if (!strcmp(n, "P2P")) rp->Point2Point = (int32_t)v;
    else if (!strcmp(n, "Laps")) rp->NumLapsInRace = (int32_t)v;
    else if (!strcmp(n, "NPC")) rp->NumPlayerCars = (int32_t)v;
    else if (!strcmp(n, "NAI")) rp->NumAICars = (int32_t)v;
    else if (!strcmp(n, "MaxCops")) rp->nMaxCops = (int32_t)v;
    else if (!strcmp(n, "New624")) rp->New624 = (int32_t)v;
    else if (!strcmp(n, "BeACop")) rp->BeACop = (int32_t)v;
    else if (!strcmp(n, "RVM")) d->RearViewMirror = (int8_t)v;
    else if (!strcmp(n, "Units")) d->Units = (int8_t)v;
    else if (!strcmp(n, "Map1")) d->OnePlayerTrackMapMode = (int8_t)v;
    else if (!strcmp(n, "Map2")) d->TwoPlayerTrackMapMode = (int8_t)v;
    else if (!strcmp(n, "MapC")) d->BeTheCopTrackMapMode = (int8_t)v;
    else if (!strcmp(n, "Leader")) d->LeaderboardMode = (int8_t)v;
    else {
        printf("  no rp field %s\n", n);
        exit(2);
    }
}

static void set_player(int k, const char *n, uint32_t v, char **a, int na)
{
    struct Player   *p = players[k];
    cPlayerSettings *s = &p->PlayerSettings;

    if (!strcmp(n, "PN")) p->PlayerNumber = (int32_t)v;
    else if (!strcmp(n, "view")) p->ViewID = (int32_t)v;
    else if (!strcmp(n, "hud")) s->PlayersHudState = (int8_t)v;
    else if (!strcmp(n, "pov")) s->DriveCameraPOVIndex = (int8_t)v;
    else if (!strcmp(n, "pref")) s->PreferredHudFeatures = v;
    else if (!strcmp(n, "new44")) s->New44 = (int32_t)v;
    else if (!strcmp(n, "trans")) s->TransmissionType = (int8_t)v;
    else if (!strcmp(n, "split")) s->SplitTimeType = (int8_t)v;
    else if (!strcmp(n, "gender")) s->PreferredGender = (int8_t)v;
    else if (!strcmp(n, "besttotal")) s->BestTotalTimeRecord.PackedTime = v;
    else if (!strcmp(n, "bestlap")) s->BestLapTimeRecord.PackedTime = v;
    else if (!strcmp(n, "tfr")) p->TimeFinishedRacing = v;
    else if (!strcmp(n, "zone")) p->nZoneCurrent = (int32_t)v;
    else if (!strcmp(n, "reset")) p->TimeToDisplayResetPrompt.PackedTime = v;
    else if (!strcmp(n, "wrongway")) p->bWrongWay = (int32_t)v;
    else if (!strcmp(n, "lookback")) p->bLookBack = (int32_t)v;
    else if (!strcmp(n, "chf")) p->CurrentHudFeatures = v;
    else if (!strcmp(n, "screen")) p->HudScreenHash = v;
    else if (!strcmp(n, "ttmmc")) p->TimeTrackMapModeChanged = v;
    else if (!strcmp(n, "score")) p->TotalScore = (int32_t)v;
    else if (!strcmp(n, "radaroff")) p->bRadarOffset = (int32_t)v;
    else if (!strcmp(n, "radary")) memcpy(&p->fInitialRadarY, &v, 4);
    else if (!strcmp(n, "prevpl")) p->PrevPursuitLevel = (int32_t)v;
    else if (!strcmp(n, "poschange")) memcpy(&p->PosChangeTime, &v, 4);
    else if (!strcmp(n, "posflag")) p->PositionFlag = (int32_t)v;
    else if (!strcmp(n, "lastpos")) p->LastRacePosition = (int32_t)v;
    else if (!strcmp(n, "lastspeed")) p->LastSpeed = (int32_t)v;
    else if (!strcmp(n, "topspeed")) p->TopSpeed = (int32_t)v;
    else if (!strcmp(n, "newtop")) p->bNewTopSpeed = (int32_t)v;
    else if (!strcmp(n, "checktop")) p->bCheckTopSpeed = (int32_t)v;
    else if (!strcmp(n, "sf")) memcpy(&p->SpeedFactor, &v, 4);
    else if (!strcmp(n, "tscore")) p->tScoreAnimation.PackedTime = v;
    else if (!strcmp(n, "new2736")) p->New2736 = (int32_t)v;
    else if (!strcmp(n, "place") && na >= 1)
        p->baPlaceReached[v] = inum(a[0]);
    else if (!strcmp(n, "other"))
        p->pOtherPlayer = (int32_t)v < 0 ? NULL : players[v];
    else if (!strcmp(n, "car")) p->MyCar = v ? cars[k] : NULL;
    else if (!strcmp(n, "cam")) p->pCameraMover = v ? &cams[k]->base : NULL;
    else if (!strcmp(n, "nis")) nisWords[k][17] = (int32_t)v;
    else {
        printf("  no player field %s\n", n);
        exit(2);
    }
}

static void set_cam(int k, const char *n, uint32_t v)
{
    DriveCameraMover *c = cams[k];

    if (!strcmp(n, "type")) c->base.Type = (CameraMoverType)v;
    else if (!strcmp(n, "lb")) memcpy(&c->DesiredLookBackParam, &v, 4);
    else if (!strcmp(n, "pov")) povType[k] = (int32_t)v;
    else if (!strcmp(n, "ext")) camExt[k] = (int32_t)v;
    else if (!strcmp(n, "back")) camBack[k] = (int32_t)v;
    else {
        printf("  no camera field %s\n", n);
        exit(2);
    }
}

static void put16(uint8_t *p, int off, uint32_t v)
{
    int16_t s = (int16_t)v;
    memcpy(p + off, &s, 2);
}

static void set_car(int k, const char *n, uint32_t v, char **a, int na)
{
    struct Car  *c = cars[k];
    CarTypeInfo *ti = c->pCarTypeInfo;
    uint8_t     *h = ti->HudInfo;
    CarState    *st = &c->State;

    if (!strcmp(n, "type")) c->pRideInfo->Type = (int32_t)v;
    else if (!strcmp(n, "skin")) c->pRideInfo->SkinNumber = (int8_t)v;
    else if (!strcmp(n, "integ")) memcpy(h, &v, 4);
    else if (!strcmp(n, "tx")) put16(h, 20, v);
    else if (!strcmp(n, "ty")) put16(h, 22, v);
    else if (!strcmp(n, "sx")) put16(h, 56, v);
    else if (!strcmp(n, "sy")) put16(h, 58, v);
    else if (!strcmp(n, "stx")) put16(h, 60, v);
    else if (!strcmp(n, "sty")) put16(h, 62, v);
    else if (!strcmp(n, "rx")) put16(h, 64, v);
    else if (!strcmp(n, "ry")) put16(h, 66, v);
    else if (!strcmp(n, "hud") && na >= 1) {
        uint32_t w = num(a[0]);
        memcpy(h + v, &w, 4);
    } else if (!strcmp(n, "reason"))
        c->pRacingCar->FinishReason = (int16_t)v;
    else if (!strcmp(n, "idx")) c->CarIndex = (int16_t)v;
    else if (!strcmp(n, "px")) memcpy(&st->Position.x, &v, 4);
    else if (!strcmp(n, "py")) memcpy(&st->Position.y, &v, 4);
    else if (!strcmp(n, "pz")) memcpy(&st->Position.z, &v, 4);
    else if (!strcmp(n, "odo")) memcpy(&st->Odometer, &v, 4);
    else if (!strcmp(n, "speed")) memcpy(&st->ForwardSpeed, &v, 4);
    else if (!strcmp(n, "gear")) st->CurrentGear = (Gear)v;
    else if (!strcmp(n, "rpm")) memcpy(&st->RPM, &v, 4);
    else if (!strcmp(n, "clutch")) st->ClutchEngaged = (int32_t)v;
    else if (!strcmp(n, "render")) c->RenderingEnabled = (int8_t)v;
    else if (!strcmp(n, "wtu") && na >= 1)
        st->WheelTractionUsage[v] = fnum(a[0]);
    else if (!strcmp(n, "short"))
        ((CarSpecs *)(uintptr_t)ti->pCarSpecs)->ShortName = (int32_t)v;
    else if (!strcmp(n, "maxrpm")) memcpy(&ti->Engine.MaxRPM, &v, 4);
    else if (!strcmp(n, "redline")) memcpy(&ti->Engine.RedLineRPM, &v, 4);
    else if (!strcmp(n, "driver"))
        c->MyDriver->pCharacterInfo = v ? &chars[k] : NULL;
    else {
        printf("  no car field %s\n", n);
        exit(2);
    }
}

static void set_rc(int k, const char *n, uint32_t v, char **a, int na)
{
    struct RacingCar *r = cars[k]->pRacingCar;
    uint32_t          w = na >= 1 ? num(a[0]) : 0;

    if (!strcmp(n, "hbr")) r->HighestBoundaryRegion = (int16_t)v;
    else if (!strcmp(n, "laps")) r->NumLapsCompleted = (int8_t)v;
    else if (!strcmp(n, "pos")) r->RacePosition = (int8_t)v;
    else if (!strcmp(n, "reason")) r->FinishReason = (int16_t)v;
    else if (!strcmp(n, "clne")) memcpy(&r->CurrentLapNumberExact, &v, 4);
    else if (!strcmp(n, "flne")) memcpy(&r->FinishedLapNumberExact, &v, 4);
    else if (!strcmp(n, "time")) r->RaceTime.PackedTime = v;
    else if (!strcmp(n, "bct")) r->BoundaryCrossingTimes[v].PackedTime = w;
    else if (!strcmp(n, "run")) r->RunningTimes[v].PackedTime = w;
    else if (!strcmp(n, "prun")) r->PreviousRunningTimes[v].PackedTime = w;
    else if (!strcmp(n, "best")) r->BestRunningTimes[v].PackedTime = w;
    else if (!strcmp(n, "pbest"))
        r->PreviousBestRunningTimes[v].PackedTime = w;
    else {
        printf("  no rc field %s\n", n);
        exit(2);
    }
}

static void set_race(const char *n, uint32_t v, char **a, int na)
{
    uint32_t w = na >= 1 ? num(a[0]) : 0;

    if (!strcmp(n, "stage")) race.RaceStage = (eRaceStage)v;
    else if (!strcmp(n, "start")) race.StartTime.PackedTime = v;
    else if (!strcmp(n, "n")) race.NumRacingCars = (int32_t)v;
    else if (!strcmp(n, "fin")) race.NumRacingCarsFinished = (int32_t)v;
    else if (!strcmp(n, "laps")) race.NumLapsInRace = (int32_t)v;
    else if (!strcmp(n, "slb")) race.StartLineBoundaryNumber = (int8_t)v;
    else if (!strcmp(n, "flb")) race.FinishLineBoundaryNumber = (int8_t)v;
    else if (!strcmp(n, "car")) {
        struct Car *c = car_or_none(w);
        race.pRacingCars[v] = c ? c->pRacingCar : NULL;
    } else if (!strcmp(n, "bd")) memcpy(&race.BoundaryDistances[v], &w, 4);
    else {
        printf("  no race field %s\n", n);
        exit(2);
    }
}

static void set_world(const char *n, uint32_t v, char **a, int na)
{
    uint32_t w = na >= 1 ? num(a[0]) : 0;

    if (!strcmp(n, "on")) pCurrentWorld = v ? &world : NULL;
    else if (!strcmp(n, "heli"))
        world.Helicopter = v ? (struct Chopper *)(void *)heli : NULL;
    else if (!strcmp(n, "heli960")) memcpy(heli + 960, &v, 4);
    else if (!strcmp(n, "ai")) world.AICarPos = (int32_t)v;
    else if (!strcmp(n, "cop")) world.CopCarPos = (int32_t)v;
    else if (!strcmp(n, "traffic")) world.TrafficCarPos = (int32_t)v;
    else if (!strcmp(n, "table")) world.CarTable[v] = car_or_none(w);
    else {
        printf("  no world field %s\n", n);
        exit(2);
    }
}

static void put_cop(size_t off, uint32_t v)
{
    memcpy(COP_BYTES + off, &v, 4);
}

static void set_cop(const char *n, char **a, int na)
{
    tCopManagerHead *h = copmanager_head(COP_MGR);
    uint32_t         v = strcmp(n, "list") && na >= 1 && a[0][0]
                         ? num(a[0]) : 0;

    if (!strcmp(n, "on")) pCopManager = v ? COP_MGR : NULL;
    else if (!strcmp(n, "new0")) h->New0 = (int32_t)v;
    else if (!strcmp(n, "pci")) h->nPlayerCopIndex = (int32_t)v;
    else if (!strcmp(n, "cop") && na >= 2) {
        int32_t pi = inum(a[1]);
        if (pi < 0) {
            h->Cops[v] = NULL;
        } else {
            cops[v].pMyPursuit = &pursuits[pi];
            h->Cops[v] = &cops[v];
        }
    } else if (!strcmp(n, "time")) put_cop(COPMANAGER_BEACOP_TIME, v);
    else if (!strcmp(n, "choppers")) put_cop(COPMANAGER_BEACOP_CHOPPERS, v);
    else if (!strcmp(n, "busy")) put_cop(COPMANAGER_CHOPPER_BUSY, v);
    else if (!strcmp(n, "dmg") && na >= 2)
        put_cop(COPMANAGER_CAR_DAMAGE + 4 * v, num(a[1]));
    else if (!strcmp(n, "tickets") && na >= 2)
        COP_BYTES[COPMANAGER_PULLOVERS + 28 * v + 8] = (uint8_t)num(a[1]);
    else if (!strcmp(n, "active") && na >= 2)
        put_cop(COPMANAGER_PULLOVERS + 28 * v + 12, num(a[1]));
    else if (!strcmp(n, "pur") && na >= 3) {
        tPursuit   *pu = &pursuits[v];
        const char *f = a[1];
        uint32_t    x = num(a[2]);
        if (!strcmp(f, "chased")) pu->pChasedCar = car_or_none(x);
        else if (!strcmp(f, "level")) pu->nHUDPursuitLevel = (int32_t)x;
        else if (!strcmp(f, "n1560")) pu->New1560 = (int32_t)x;
        else {
            printf("  no pursuit field %s\n", f);
            exit(2);
        }
    } else if (!strcmp(n, "list")) {
        // The pursuits linked in this order, after the list's own node.
        tPursuitNode *prev = &h->PursuitList;
        const char   *s = na >= 1 ? a[0] : "";
        while (*s) {
            char         *end;
            long          i = strtol(s, &end, 10);
            tPursuitNode *node = &pursuits[i].Node;
            prev->Next = node;
            node->Prev = prev;
            prev = node;
            s = *end == '.' ? end + 1 : end;
        }
        prev->Next = &h->PursuitList;
        h->PursuitList.Prev = prev;
    } else {
        printf("  no cop manager field %s\n", n);
        exit(2);
    }
}

static void set_global(char **a, int n)
{
    const char *k = a[0];
    uint32_t    v = num(a[1]);

    if (!strcmp(k, "np")) PlayerNumPlayers = (int32_t)v;
    else if (!strcmp(k, "rc")) coord.CurrentRCState = (RCState)v;
    else if (!strcmp(k, "before")) coord.BeforePauseRCState = (RCState)v;
    else if (!strcmp(k, "stage")) race.RaceStage = (eRaceStage)v;
    else if (!strcmp(k, "racing")) race.NumRacingCars = (int32_t)v;
    else if (!strcmp(k, "frames")) RealTimeFrames = (int32_t)v;
    else if (!strcmp(k, "egg")) egg4 = (int32_t)v;
    else if (!strcmp(k, "cop")) pCopManager = v ? COP_MGR : NULL;
    else if (!strcmp(k, "pull") && n >= 4) {
        uint8_t *pl = COP_BYTES + 88 + 28 * v;
        int32_t  act = inum(a[2]), busted = inum(a[3]);
        memcpy(pl + 12, &act, 4);
        memcpy(pl + 24, &busted, 4);
    } else if (!strcmp(k, "byn") && n >= 3) {
        int32_t who = inum(a[2]);
        PlayerPlayersByNumber[v] = who < 0 ? NULL : players[who];
    } else if (!strcmp(k, "byidx") && n >= 3) {
        int32_t who = inum(a[2]);
        PlayerPlayersByIndex[v] = who < 0 ? NULL : players[who];
    } else if (!strcmp(k, "timer")) WorldTimer = (int32_t)v;
    else if (!strcmp(k, "wframes")) WorldTimeFrames = (int32_t)v;
    else if (!strcmp(k, "loop")) WorldLoopCounter = (int32_t)v;
    else if (!strcmp(k, "follow")) CameraFollowDefaultCar = (int32_t)v;
    else if (!strcmp(k, "followcar")) CameraFollowThisCarInstead = (int32_t)v;
    else if (!strcmp(k, "live")) LiveUpdateSplitTimeRate = (int32_t)v;
    else if (!strcmp(k, "smf")) SpeedMinFactor = fnum(a[1]);
    else if (!strcmp(k, "tach")) TachTestRpm = fnum(a[1]);
    else if (!strcmp(k, "debug")) DisplayPlayerDebugInfo = (int32_t)v;
    else if (!strcmp(k, "cpu")) PreviousCpuFrameRate = fnum(a[1]);
    else if (!strcmp(k, "gpu")) PreviousGpuFrameRate = fnum(a[1]);
    else if (!strcmp(k, "lang")) language = (int32_t)v;
    else if (!strcmp(k, "zone")) zone = (int32_t)v;
    else if (!strcmp(k, "lapx")) lapExact = fnum(a[1]);
    else {
        printf("  no global %s\n", k);
        exit(2);
    }
}

static struct Player *make_player(int k)
{
    struct Player *p = (struct Player *)calloc(1, sizeof *p);
    uint8_t       *b = (uint8_t *)p;
    void          *d = dummy;

    for (size_t f = 0; f < NUM_FIELDS; f++)
        if (fields[f].kind == 'p')
            for (int i = 0; i < fields[f].count; i++)
                memcpy(b + fields[f].off + (size_t)i * fields[f].step, &d,
                       sizeof d);
    p->pNisManager = (struct NisManager *)(void *)nisWords[k];
    return p;
}

static struct Car *make_car(int k)
{
    struct Car *c = (struct Car *)calloc(1, sizeof *c);
    c->pCarTypeInfo = (CarTypeInfo *)calloc(1, sizeof(CarTypeInfo));
    c->pCarTypeInfo->pCarSpecs = (const CarSpecs *)calloc(1,
                                                          sizeof(CarSpecs));
    c->pRideInfo = (RideInfo *)calloc(1, sizeof(RideInfo));
    c->MyDriver = (DriverInfo *)calloc(1, sizeof(DriverInfo));
    c->pRacingCar = (RacingCar *)calloc(1, sizeof(RacingCar));
    c->pRacingCar->pCar = c;
    snprintf(chars[k].CharacterName, sizeof chars[k].CharacterName, "DRV%d",
             k);
    return c;
}

static void run(char *line)
{
    char *a[8];
    int   n = 0;
    char *s = line;

    while (n < 8) {
        a[n++] = s;
        s = strchr(s, '|');
        if (!s) break;
        *s++ = 0;
    }
    if (!strcmp(a[0], "load")) {
        load(a[1]);
        return;
    }
    if (!strcmp(a[0], "rp")) set_rp(a[1], num(a[2]));
    else if (!strcmp(a[0], "elim")) {
        TheRaceParameters.pDriverInfoTable = drivers;
        TheRaceParameters.NumDriverInfo = 2;
        drivers[0].EliminatedRank = (int8_t)inum(a[1]);
    } else if (!strcmp(a[0], "pn")) {
        char *nm = players[inum(a[1])]->PlayerSettings.PlayerName;
        memset(nm, 0, 12);
        strncpy(nm, a[2], 11);
    } else if (!strcmp(a[0], "pl"))
        set_player(inum(a[1]), a[2], num(a[3]), a + 4, n - 4);
    else if (!strcmp(a[0], "cam")) set_cam(inum(a[1]), a[2], num(a[3]));
    else if (!strcmp(a[0], "car"))
        set_car(inum(a[1]), a[2], num(a[3]), a + 4, n - 4);
    else if (!strcmp(a[0], "rc"))
        set_rc(inum(a[1]), a[2], num(a[3]), a + 4, n - 4);
    else if (!strcmp(a[0], "race")) set_race(a[1], num(a[2]), a + 3, n - 3);
    else if (!strcmp(a[0], "w")) set_world(a[1], num(a[2]), a + 3, n - 3);
    else if (!strcmp(a[0], "cm")) set_cop(a[1], a + 2, n - 2);
    else if (!strcmp(a[0], "g")) set_global(a + 1, n - 1);
    else if (!strcmp(a[0], "use")) curPlayer = inum(a[1]);
    else if (!strcmp(a[0], "set"))
        player_set_hud_features(players[curPlayer], num(a[1]));
    else if (!strcmp(a[0], "ren")) player_render_hud(players[curPlayer]);
    else if (!strcmp(a[0], "upd")) player_update_hud(players[curPlayer]);
    else if (!strcmp(a[0], "best"))
        printf("  best %08x\n", player_get_current_best_lap_record(
                                    players[curPlayer], inum(a[1])));
    else if (!strcmp(a[0], "conv"))
        printf("  conv %d\n", player_convert_score_string(
                                  players[curPlayer], n > 1 ? a[1] : ""));
    else {
        printf("  no op %s\n", a[0]);
        exit(2);
    }
    dump();
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE       *f;

    if (argc < 2) return 2;
    f = fopen(argv[1], "r");
    if (!f) return 2;

    gFlailerTextScaledWidthFn = text_w;
    gFlailerTextScaledHeightFn = text_h;
    gFlailerBitmapTextureSizeFn = texture_size;
    gSetFlailerScreenVisibilityFn = screen_vis;
    gNisManagerIsPlayingFn = nis_playing;
    gPlayerClearHudAnimationsFn = clear_anims;
    gPlayerSetRearViewMirrorCameraMoverFn = mirror;
    gInitializeFlailerTachometerFn = init_tach;
    gNewTrackMapFn = new_map;
    gDeleteTrackMapFn = delete_map;
    gPlayerFillInRaceOverMessagesFn = race_over;
    gRaceFinishedSpeechFn = speech;
    gPlayerHudStartWrongWayFn = wrong_way;
    gNisOverlaySetVisibleFn = nis_visible;
    gEggIsOnFn = egg_is_on;

    gHudTranslateFn = translate;
    gHudDoAnimationsFn = do_anims;
    gUpdateScoringFn = scoring;
    gStartScoreFn = start_score;
    gHudStartSpeedAnimationFn = speed_anim;
    gHudStartGrowAnimationFn = grow_anim;
    gUpdatePursuitMeterFn = pursuit_meter;
    gUpdateRadarDetectorFn = radar;
    gDrawTrackerFn = tracker;
    gNisOverlayUpdateFn = nis_update;
    gCurrLanguageFn = curr_language;
    gGetInGameSampleFn = get_sample;
    gSamplePlayFn = play;

    pCurrentRace = &race;
    pRaceCoordinator = &coord;
    CurrentTrackInfo = (TrackInfo *)(void *)track;
    race.pTimeAroundTrackTable = (TimeAroundTrackTable *)(void *)dummy;
    world.Helicopter = (struct Chopper *)(void *)heli;
    {
        tCopManagerHead *h = copmanager_head(COP_MGR);
        h->PursuitList.Next = h->PursuitList.Prev = &h->PursuitList;
    }
    for (int k = 0; k < NCARS; k++) cars[k] = make_car(k);
    for (int k = 0; k < 2; k++) {
        players[k] = make_player(k);
        cams[k] = (DriveCameraMover *)calloc(1, sizeof(DriveCameraMover));
        cams[k]->base.vtbl = &camVtbl;
    }

    while (fgets(line, sizeof line, f)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            line[--n] = 0;
        if (!n) continue;
        printf("> %s\n", line);
        run(line);
    }
    fclose(f);
    return 0;
}
