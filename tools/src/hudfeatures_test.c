// Drives playerhud.c for tools/hudfeatures_check.py: DetermineHudFeatures,
// SetHudFeatures and SetTrackMapMode on two Players, over flailer.c and
// bui.c with INGAMEB's HUD screens loaded. A script of ops, one per line,
// fields split on '|'; numbers are C literals:
//
//   load|PATH          a bundle: bui_open, then flailer_add_project
//   rp|NAME|V          a TheRaceParameters field
//   pl|N|NAME|V        a field of player N
//   cam|N|NAME|V       player N's camera: what it is and what it answers
//   car|N|NAME|V       player N's car
//   g|NAME|V...        the race around them
//   use|N              the player the calls below take
//   det                DetermineHudFeatures; prints = F
//   set|F              SetHudFeatures(F)
//   map|M              SetTrackMapMode(M)
//   upd                UpdateHud's head: set only if det's answer changed
//   order              the project list and each one's screens
//
// After each op the seams print as they are called; then every Player
// field, view, display setting and Flailer object whose printed line
// changed. Objects print as P:I, the project's load number and bui's object
// index; a pointer to anything else prints "stray", and every pointer field
// starts as one, so that a field nothing writes stays so.
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
#include "configitems.h"
#include "copmanager.h"
#include "drivecam.h"
#include "eview.h"
#include "flailer.h"
#include "hudtex.h"
#include "player.h"
#include "playerhud.h"
#include "playerinit.h"
#include "playersettings.h"
#include "race.h"
#include "racecoord.h"
#include "raceinit.h"
#include "raceparams.h"
#include "rcpost.h"
#include "realtime.h"
#include "trackflow.h"

#define MAX_LOADS 4
#define NUM_VIEWS 4

// ------------------------------------------------------------ the globals
//
// What the linked sources read and the rest of the game defines.

RaceParameters  TheRaceParameters;
int32_t         PlayerNumPlayers;
struct Player  *PlayerPlayersByNumber[2];
Race           *pCurrentRace;
RaceCoordinator *pRaceCoordinator;
int32_t         RealTimeFrames;
TrackInfo      *CurrentTrackInfo;
EggIsOnFn       gEggIsOnFn;
void (*gSetFlailerScreenVisibilityFn)(uint32_t screen, int visibility);
int32_t (*gNisManagerIsPlayingFn)(const struct NisManager *m);
void (*gPlayerClearHudAnimationsFn)(struct Player *p);

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
static struct Car        *cars[2];
static DriveCameraMover  *cams[2];
static int32_t            povType[2], camExt[2], camBack[2];
static POV                povs[2];
static int32_t            nisWords[2][32];
static eView              views[NUM_VIEWS];
static Race               race;
static RaceCoordinator    coord;
static uint8_t            copManager[312];
static uint8_t            track[16];
static int32_t            egg4;
static int                curPlayer;

// What every pointer field starts as: an object of nothing's.
static uint8_t            dummy[256];

// --------------------------------------------------------- number parsing

static uint32_t num(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static int32_t inum(const char *s)
{
    return (int32_t)strtol(s, NULL, 0);
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

// ----------------------------------------------------------------- seams

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
    return (struct TrackMap *)calloc(1, 176);
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

// ------------------------------------------------------------- the dump

typedef struct Field {
    const char *name;
    size_t      off;
    char        kind;       // p an object, w a word, m the TrackMap
    int         count;
    size_t      step;
} Field;

#define FP(f, n) { #f, offsetof(struct Player, f), 'p', n, sizeof(void *) }
#define FW(f, n) { #f, offsetof(struct Player, f), 'w', n, 4 }

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

static void dump_player(int n)
{
    const uint8_t *p = (const uint8_t *)players[n];
    char key[64], text[64], nb[16];

    for (size_t f = 0; f < NUM_FIELDS; f++) {
        const Field *d = &fields[f];
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
                uint8_t *m;
                int32_t  mode;
                memcpy(&m, a, sizeof m);
                if (m == NULL) {
                    snprintf(text, sizeof text, "none");
                } else {
                    memcpy(&mode, m + 160, 4);
                    snprintf(text, sizeof text, "map:%d", mode);
                }
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
    char text[64];

    dump_player(0);
    dump_player(1);
    for (int v = 0; v < NUM_VIEWS; v++) {
        char key[16];
        snprintf(key, sizeof key, "view%d", v);
        snprintf(text, sizeof text, "lb %u", views[v].LetterBox);
        note(key, text);
    }
    hex(text, (const uint8_t *)&TheRaceParameters.GlobalDisplaySettings, 0,
        8);
    note("gds", text);
    dump_objects();
}

static void order(void)
{
    const uint32_t *ord;
    uint32_t        n;
    BUI            *ui;
    for (int k = 0; (ui = flailer_project_at(k, &ord, &n)) != NULL; k++) {
        printf("  project %d:", load_of(ui));
        for (uint32_t i = 0; i < n; i++) printf(" %u", ord[i]);
        printf("\n");
    }
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

static void set_player(int k, const char *n, uint32_t v)
{
    struct Player *p = players[k];

    if (!strcmp(n, "PN")) p->PlayerNumber = (int32_t)v;
    else if (!strcmp(n, "view")) p->ViewID = (int32_t)v;
    else if (!strcmp(n, "hud")) p->PlayerSettings.PlayersHudState = (int8_t)v;
    else if (!strcmp(n, "pov"))
        p->PlayerSettings.DriveCameraPOVIndex = (int8_t)v;
    else if (!strcmp(n, "pref")) p->PlayerSettings.PreferredHudFeatures = v;
    else if (!strcmp(n, "new44")) p->PlayerSettings.New44 = (int32_t)v;
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

static void set_car(int k, const char *n, uint32_t v)
{
    struct Car *c = cars[k];
    uint8_t    *h = c->pCarTypeInfo->HudInfo;

    if (!strcmp(n, "type")) c->pRideInfo->Type = (int32_t)v;
    else if (!strcmp(n, "integ")) memcpy(h, &v, 4);
    else if (!strcmp(n, "tx")) put16(h, 20, v);
    else if (!strcmp(n, "ty")) put16(h, 22, v);
    else if (!strcmp(n, "sx")) put16(h, 56, v);
    else if (!strcmp(n, "sy")) put16(h, 58, v);
    else if (!strcmp(n, "stx")) put16(h, 60, v);
    else if (!strcmp(n, "sty")) put16(h, 62, v);
    else if (!strcmp(n, "rx")) put16(h, 64, v);
    else if (!strcmp(n, "ry")) put16(h, 66, v);
    else if (!strcmp(n, "reason"))
        c->pRacingCar->FinishReason = (int16_t)v;
    else {
        printf("  no car field %s\n", n);
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
    else if (!strcmp(k, "cop"))
        pCopManager = v ? (tCopManager *)(void *)copManager : NULL;
    else if (!strcmp(k, "pull") && n >= 4) {
        uint8_t *pl = copManager + 88 + 28 * v;
        int32_t  act = inum(a[2]), busted = inum(a[3]);
        memcpy(pl + 12, &act, 4);
        memcpy(pl + 24, &busted, 4);
    } else if (!strcmp(k, "byn") && n >= 3) {
        int32_t who = inum(a[2]);
        PlayerPlayersByNumber[v] = who < 0 ? NULL : players[who];
    } else {
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

static struct Car *make_car(void)
{
    struct Car *c = (struct Car *)calloc(1, sizeof *c);
    c->pCarTypeInfo = (CarTypeInfo *)calloc(1, sizeof(CarTypeInfo));
    c->pRideInfo = (RideInfo *)calloc(1, sizeof(RideInfo));
    c->pRacingCar = (RacingCar *)calloc(1, sizeof(RacingCar));
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
    if (!strcmp(a[0], "order")) {
        order();
        return;
    }
    if (!strcmp(a[0], "rp")) set_rp(a[1], num(a[2]));
    else if (!strcmp(a[0], "pl")) set_player(inum(a[1]), a[2], num(a[3]));
    else if (!strcmp(a[0], "cam")) set_cam(inum(a[1]), a[2], num(a[3]));
    else if (!strcmp(a[0], "car")) set_car(inum(a[1]), a[2], num(a[3]));
    else if (!strcmp(a[0], "g")) set_global(a + 1, n - 1);
    else if (!strcmp(a[0], "use")) curPlayer = inum(a[1]);
    else if (!strcmp(a[0], "det"))
        printf("  = %08x\n",
               player_determine_hud_features(players[curPlayer]));
    else if (!strcmp(a[0], "set"))
        player_set_hud_features(players[curPlayer], num(a[1]));
    else if (!strcmp(a[0], "map"))
        player_set_track_map_mode(players[curPlayer], inum(a[1]));
    else if (!strcmp(a[0], "upd"))
        player_update_hud(players[curPlayer]);
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

    pCurrentRace = &race;
    pRaceCoordinator = &coord;
    CurrentTrackInfo = (TrackInfo *)(void *)track;
    for (int k = 0; k < 2; k++) {
        players[k] = make_player(k);
        cars[k] = make_car();
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
