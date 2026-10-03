// Drives hudanim.c for tools/hudanim_check.py: HudAnimator and the Player
// functions that start, run and clear the HUD's animations, on two
// Players, over hudrender.c (for ConvertScoreString), flailer.c and the
// rest RenderHud links, with INGAMEB's HUD screens loaded. A script of ops,
// one per line, fields split on '|'; numbers are C literals, floats their
// bits. An object is t:HASH (a text) or b:HASH (a bitmap) on the player's
// HudScreenHash, or none:
//
//   load|PATH          a bundle: bui_open, then flailer_add_project
//   rp|NAME|V          a TheRaceParameters field
//   g|NAME|V           PlayerNumPlayers (np), WorldTimer, RealTimer
//   use|N              the player the ops below take
//   pl|N|NAME|V        a field of player N
//   pos|OBJ|X|Y|SX|SY  an object's top left and scale
//   alpha|OBJ|A        FlailerTextChunk::SetAlpha
//   grow|A|B|T|F       HudStartGrowAnimation(A, B, T, F)
//   speed|A|B|T|F      HudStartSpeedAnimation(A, B, T, F)
//   text|S|O|...       HudStartAnimation (text) in slot S: from, to, the
//                      two scales, the two alphas, the duration, the time
//   bitmap|S|O|...     HudStartAnimation (bitmap), and keep last
//   wrong              HudStartWrongWay
//   clear              ClearHudAnimations
//   do                 HudDoAnimations
//   add|S              AddToTotalScore(S)
//   new|S              slot S's HudAnimator, if it has none
//   scored|S|O|...     StartAnimation (scored) on slot S's animator; the
//                      string "-" is NULL
//   doscored|S|T|STR   DoAnimation(&T, STR) on slot S's; prints = R
//   do1|S              DoAnimation(Timer) on slot S's; prints = R
//   finish|S           FinishAnimation on slot S's
//   an|S|OFF|V         the word of slot S's at retail offset OFF
//
// After each op every line that changed: each Player's twenty slots (the
// animator's allocation number and its 288 bytes in retail's order, the
// two objects by name), TotalScore, and every Flailer object's bytes.
// bMalloc fills a new animator with a pattern by retail offset, and its two
// object pointers with a dummy object's, so a field nothing writes shows.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bui.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "eview.h"
#include "flailer.h"
#include "hudanim.h"
#include "hudrender.h"
#include "hudtex.h"
#include "player.h"
#include "playerhud.h"
#include "playersettings.h"
#include "race.h"
#include "racecoord.h"
#include "racecore.h"
#include "raceinit.h"
#include "raceparams.h"
#include "realtime.h"
#include "scenery.h"
#include "trackflow.h"
#include "world.h"

#define MAX_LOADS  4
#define MAX_ALLOCS 64
#define NUM_ARGS   48
#define NUM_SLOTS  20

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
int32_t         RealTimer;
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

// RenderHud's callees, which nothing here reaches.
struct Car *world_get_car_by_driver_number(int32_t n)
{
    (void)n;
    return NULL;
}

struct RacingCar *race_get_racing_car(Race *r, struct Car *c)
{
    (void)r;
    (void)c;
    return NULL;
}

int32_t scenery_get_current_zone_number(void)
{
    return 0;
}

float race_get_lap_number_exact(Race *r, float pct)
{
    (void)r;
    return pct;
}

float tatt_get_time_around_track(TimeAroundTrackTable *t, float lap)
{
    (void)t;
    return lap;
}

SkinInfo *cartypeinfo_get_skin_info(int32_t car_type, int32_t skin_number,
                                    int use_default)
{
    (void)car_type;
    (void)skin_number;
    (void)use_default;
    return NULL;
}

// SetHudFeatures' callees, which nothing here reaches either.
eView *eGetView(int32_t id)
{
    (void)id;
    return NULL;
}

void ChooseLoadableTextures(int32_t car, int32_t units,
                            tLoadableHudTextures *t)
{
    (void)car;
    (void)units;
    memset(t, 0, sizeof *t);
}

// ------------------------------------------------------------ the world

static BUI      loads[MAX_LOADS];
static uint8_t *bufs[MAX_LOADS];
static int      numLoads;

static struct Player *players[2];
static int            curPlayer;

// What every object pointer starts as: an object of nothing's.
static uint8_t        dummy[256];

// The animators bMalloc handed out, in order.
static void          *allocs[MAX_ALLOCS];
static int            numAllocs;

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

static void vec2(bVector2 *v, char **a)
{
    v->x = fnum(a[0]);
    v->y = fnum(a[1]);
}

static void vec4(bVector4 *v, char **a)
{
    v->x = fnum(a[0]);
    v->y = fnum(a[1]);
    v->z = fnum(a[2]);
    v->w = fnum(a[3]);
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

// ------------------------------------------------------------ the heap
//
// HudAnimator's fields by retail offset, all but the two pointers at 72.

typedef struct AnimField {
    size_t host;
    int    retail;
    int    size;
} AnimField;

#define AF(f, r) { offsetof(HudAnimator, f), r, (int)sizeof(((HudAnimator *)0)->f) }

static const AnimField animFields[] = {
    AF(String, 0), AF(bHasString, 64), AF(New68, 68), AF(Pos, 80),
    AF(DeltaPos, 88), AF(_pad96, 96), AF(Scale, 100), AF(DeltaScale, 108),
    AF(_pad116, 116), AF(Alpha, 120), AF(DeltaAlpha, 124),
    AF(DeltaPos2, 128), AF(Scale1, 136), AF(DeltaScale2, 144),
    AF(Alpha1, 152), AF(DeltaAlpha2, 156), AF(Colour, 160),
    AF(DeltaColour, 176), AF(_pad192, 192), AF(Colour3, 208),
    AF(DeltaColour3, 224), AF(Duration, 240), AF(StartSeconds, 252),
    AF(Phase, 256), AF(bActive, 260), AF(bKeepVisible, 264),
    AF(bRealTimer, 268), AF(Type, 272), AF(_pad276, 276),
};
#define NUM_ANIM_FIELDS (sizeof animFields / sizeof animFields[0])

// The word a new block holds at retail offset o.
static uint32_t pattern(int o)
{
    return 0x3f800000u + (uint32_t)o * 16u;
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    HudAnimator *a;
    uint8_t      img[288];
    void        *d = dummy;

    (void)name;
    (void)flags;
    (void)pool;
    if (size != (int)sizeof(HudAnimator) || numAllocs == MAX_ALLOCS) {
        printf("  bad malloc %d\n", size);
        exit(2);
    }
    a = (HudAnimator *)malloc(sizeof *a);
    for (int o = 0; o < 288; o += 4) {
        uint32_t w = pattern(o);
        memcpy(img + o, &w, 4);
    }
    for (size_t f = 0; f < NUM_ANIM_FIELDS; f++)
        memcpy((uint8_t *)a + animFields[f].host, img + animFields[f].retail,
               (size_t)animFields[f].size);
    memcpy(&a->pText, &d, sizeof d);
    memcpy(&a->pBitmap, &d, sizeof d);
    allocs[numAllocs++] = a;
    return a;
}

void bFree(void *p)
{
    (void)p;
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

static int alloc_of(const void *a)
{
    for (int i = 0; i < numAllocs; i++)
        if (allocs[i] == a) return i;
    return -1;
}

// An object of the current player's screen: t:HASH, b:HASH or none.
static struct FlailerObjectChunk *object(const char *s)
{
    uint32_t screen = players[curPlayer]->HudScreenHash;

    if (!strncmp(s, "t:", 2))
        return flailer_find_object(screen, num(s + 2), FLAILER_TYPE_TEXT);
    if (!strncmp(s, "b:", 2))
        return flailer_find_object(screen, num(s + 2), FLAILER_TYPE_BITMAP);
    return NULL;
}

// ------------------------------------------------------------- the dump

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

static void hex(char *out, const uint8_t *p, uint32_t from, uint32_t to)
{
    static const char digits[] = "0123456789abcdef";
    for (uint32_t i = from; i < to; i++) {
        *out++ = digits[p[i] >> 4];
        *out++ = digits[p[i] & 15];
    }
    *out = 0;
}

static void dump_anim(int n, int slot)
{
    const HudAnimator *a = players[n]->pHudAnimations[slot];
    uint8_t            img[288];
    char               key[32], text[1024], nb[2][16];
    char              *o = text;

    snprintf(key, sizeof key, "p%d.anim[%d]", n, slot);
    if (a == NULL) {
        note(key, "none");
        return;
    }
    memset(img, 0, sizeof img);
    for (size_t f = 0; f < NUM_ANIM_FIELDS; f++)
        memcpy(img + animFields[f].retail,
               (const uint8_t *)a + animFields[f].host,
               (size_t)animFields[f].size);
    o += sprintf(o, "a%d ", alloc_of(a));
    hex(o, img, 0, 72);
    o += strlen(o);
    o += sprintf(o, " %s %s ", obj_name(a->pText, nb[0], sizeof nb[0]),
                 obj_name(a->pBitmap, nb[1], sizeof nb[1]));
    hex(o, img, 80, 288);
    note(key, text);
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
    char text[16];

    for (int n = 0; n < 2; n++) {
        char key[32];
        for (int s = 0; s < NUM_SLOTS; s++)
            dump_anim(n, s);
        snprintf(key, sizeof key, "p%d.TotalScore", n);
        snprintf(text, sizeof text, "%08x", (uint32_t)players[n]->TotalScore);
        note(key, text);
    }
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

static void set_string(char *dst, size_t n, char **a, int na)
{
    memset(dst, 0, n);
    if (na > 0) strncpy(dst, a[0], n - 1);
}

static void set_player(int k, const char *n, char **a, int na)
{
    struct Player *p = players[k];
    uint32_t       v = na > 0 ? num(a[0]) : 0;

    if (!strcmp(n, "PN")) p->PlayerNumber = (int32_t)v;
    else if (!strcmp(n, "chf")) p->CurrentHudFeatures = v;
    else if (!strcmp(n, "screen")) p->HudScreenHash = v;
    else if (!strcmp(n, "score")) p->TotalScore = (int32_t)v;
    else if (!strcmp(n, "speedstr")) p->pFlailerSpeedString = object(a[0]);
    else if (!strcmp(n, "scoretotal")) p->pFlailerScoreTotal = object(a[0]);
    else if (!strcmp(n, "evscore"))
        set_string(p->strEventScore, sizeof p->strEventScore, a, na);
    else if (!strcmp(n, "evtitle"))
        set_string(p->strEventTitle, sizeof p->strEventTitle, a, na);
    else if (!strcmp(n, "prevscore"))
        set_string(p->strPrevScore, sizeof p->strPrevScore, a, na);
    else {
        printf("  no player field %s\n", n);
        exit(2);
    }
}

static void set_global(char **a)
{
    const char *k = a[0];
    uint32_t    v = num(a[1]);

    if (!strcmp(k, "np")) PlayerNumPlayers = (int32_t)v;
    else if (!strcmp(k, "timer")) WorldTimer = (int32_t)v;
    else if (!strcmp(k, "real")) RealTimer = (int32_t)v;
    else {
        printf("  no global %s\n", k);
        exit(2);
    }
}

// The slot's animator, or NULL having said so.
static HudAnimator *slot(char *s)
{
    HudAnimator *a = players[curPlayer]->pHudAnimations[inum(s)];
    if (a == NULL) printf("  no anim\n");
    return a;
}

// The word at retail offset off of a HudAnimator.
static void *anim_word(HudAnimator *a, int off)
{
    for (size_t f = 0; f < NUM_ANIM_FIELDS; f++) {
        const AnimField *d = &animFields[f];
        if (off >= d->retail && off + 4 <= d->retail + d->size)
            return (uint8_t *)a + d->host + (off - d->retail);
    }
    printf("  no word at %d\n", off);
    exit(2);
}

static void run(char *line)
{
    char          *a[NUM_ARGS];
    int            n = 0;
    char          *s = line;
    struct Player *p;
    HudAnimator   *an;

    while (n < NUM_ARGS) {
        a[n++] = s;
        s = strchr(s, '|');
        if (!s) break;
        *s++ = 0;
    }
    if (!strcmp(a[0], "load")) {
        load(a[1]);
        return;
    }
    p = players[curPlayer];
    if (!strcmp(a[0], "rp")) {
        if (!strcmp(a[1], "RaceType"))
            TheRaceParameters.RaceType = inum(a[2]);
        else if (!strcmp(a[1], "Laps"))
            TheRaceParameters.NumLapsInRace = inum(a[2]);
        else if (!strcmp(a[1], "BeACop"))
            TheRaceParameters.BeACop = inum(a[2]);
        else {
            printf("  no rp %s\n", a[1]);
            exit(2);
        }
    } else if (!strcmp(a[0], "g")) set_global(a + 1);
    else if (!strcmp(a[0], "use")) curPlayer = inum(a[1]);
    else if (!strcmp(a[0], "pl"))
        set_player(inum(a[1]), a[2], a + 3, n - 3);
    else if (!strcmp(a[0], "pos")) {
        struct FlailerObjectChunk *o = object(a[1]);
        o->X = fnum(a[2]);
        o->Y = fnum(a[3]);
        o->ScaleX = fnum(a[4]);
        o->ScaleY = fnum(a[5]);
    } else if (!strcmp(a[0], "alpha"))
        flailertext_set_alpha((struct FlailerTextChunk *)object(a[1]),
                              inum(a[2]));
    else if (!strcmp(a[0], "grow"))
        player_hud_start_grow_animation(
            p, (struct FlailerTextChunk *)object(a[1]),
            (struct FlailerTextChunk *)object(a[2]), num(a[3]), inum(a[4]));
    else if (!strcmp(a[0], "speed"))
        player_hud_start_speed_animation(
            p, (struct FlailerTextChunk *)object(a[1]),
            (struct FlailerTextChunk *)object(a[2]), num(a[3]), inum(a[4]));
    else if (!strcmp(a[0], "text") || !strcmp(a[0], "bitmap")) {
        bVector2 from, to, sf, st;
        vec2(&from, a + 3);
        vec2(&to, a + 5);
        vec2(&sf, a + 7);
        vec2(&st, a + 9);
        if (a[0][0] == 't')
            player_hud_start_text_animation(
                p, inum(a[1]), (struct FlailerTextChunk *)object(a[2]), &from,
                &to, &sf, &st, inum(a[11]), inum(a[12]), fnum(a[13]),
                num(a[14]));
        else
            player_hud_start_bitmap_animation(
                p, inum(a[1]), (struct FlailerBitmapChunk *)object(a[2]),
                &from, &to, &sf, &st, inum(a[11]), inum(a[12]), fnum(a[13]),
                num(a[14]), inum(a[15]));
    } else if (!strcmp(a[0], "wrong")) player_hud_start_wrong_way(p);
    else if (!strcmp(a[0], "clear")) player_clear_hud_animations(p);
    else if (!strcmp(a[0], "do")) player_hud_do_animations(p);
    else if (!strcmp(a[0], "add"))
        player_add_to_total_score(p, n > 1 ? a[1] : "");
    else if (!strcmp(a[0], "new")) {
        if (p->pHudAnimations[inum(a[1])] == NULL)
            p->pHudAnimations[inum(a[1])] = hudanim_new();
    } else if (!strcmp(a[0], "scored")) {
        bVector2 pos, dpos, dpos2, scale, dscale, scale1, dscale2;
        bVector4 colour, dcolour;
        if ((an = slot(a[1])) == NULL) return;
        vec2(&pos, a + 3);
        vec2(&dpos, a + 5);
        vec2(&dpos2, a + 7);
        vec2(&scale, a + 9);
        vec2(&dscale, a + 11);
        vec4(&colour, a + 15);
        vec2(&scale1, a + 19);
        vec2(&dscale2, a + 21);
        vec4(&dcolour, a + 25);
        hudanim_start_scored(
            an, (struct FlailerTextChunk *)object(a[2]), &pos, &dpos, &dpos2,
            &scale, &dscale, inum(a[13]), fnum(a[14]), &colour, &scale1,
            &dscale2, inum(a[23]), fnum(a[24]), &dcolour, fnum(a[29]),
            fnum(a[30]), fnum(a[31]), strcmp(a[32], "-") ? a[32] : NULL,
            inum(a[33]));
    } else if (!strcmp(a[0], "doscored")) {
        Timer t;
        if ((an = slot(a[1])) == NULL) return;
        t.PackedTime = num(a[2]);
        printf("  = %d\n", hudanim_do_scored(an, &t, n > 3 ? a[3] : ""));
    } else if (!strcmp(a[0], "do1")) {
        if ((an = slot(a[1])) == NULL) return;
        printf("  = %d\n", hudanim_do(an));
    } else if (!strcmp(a[0], "finish")) {
        if ((an = slot(a[1])) == NULL) return;
        hudanim_finish(an);
    } else if (!strcmp(a[0], "an")) {
        uint32_t v = num(a[3]);
        if ((an = slot(a[1])) == NULL) return;
        memcpy(anim_word(an, inum(a[2])), &v, 4);
    } else {
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

    for (int k = 0; k < 2; k++)
        players[k] = (struct Player *)calloc(1, sizeof(struct Player));

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
