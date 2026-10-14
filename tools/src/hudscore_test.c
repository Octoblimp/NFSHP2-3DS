// Drives hudscore.c for tools/hudscore_check.py: the race's bonus scores,
// on two Players, over hudanim.c, hudrender.c, flailer.c and the rest
// hudanim_test.c links, with INGAMEB's HUD screens loaded. A script of
// ops, one per line, fields split on '|'; numbers are C literals, floats
// their bits. An object is t:HASH (a text) or b:HASH (a bitmap) on the
// player's HudScreenHash, or none. hudanim_test.c's ops, and:
//
//   g|sound|V          SoundEnabled
//   rcstate|S          pRaceCoordinator's CurrentRCState
//   sample|N           GetInGameSample's answer: 0 none, 1 the sample
//   playing|N          bSample::IsPlaying's answer
//   blink|N            Car::IsBlinking's answer
//   racing|-           GetRacingCar's answer NULL, or
//   racing|NL|POS|X|R  a RacingCar: NumLapsCompleted, RacePosition,
//                      CrossedFinishLine, FinishReason
//   car|K|F|...        car K's field: player (N, or -1), up (four floats),
//                      wheels
//   body|K|TYPE|CAR|M  body K: its Type, its car (or -1), its inverse mass
//   coll|-             the car's GetCollision NULL, or
//   coll|B1|B2|MAG|DX|DY|DZ|DW  a collision of bodies B1 and B2 with
//                      TotalImpulseMagnitude MAG and ImpulseDirection D
//   sound|E            PlayScoreSound(E)
//   anim|...           StartScoreAnimation: pos, dpos, dpos2, scale and
//                      dscale (two each), colour and dcolour (four each)
//   bonus|P            GetFinishBonus(P); prints = R
//   score|E            StartScore(E)
//   scorev|E|V         StartScore(E, V)
//   update             UpdateScoring
//
// Player N's car is car N, whose body is body N. After each op every line
// that changed: hudanim_test.c's, each Player's scoring fields and three
// strings, and bResetGlare. The two colours' fourth lanes in an animator
// are retail's stack, which StartScore does not write, so both sides show
// them as eeeeeeee.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bui.h"
#include "car.h"
#include "carinit.h"
#include "cartypeinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "eview.h"
#include "flailer.h"
#include "hudanim.h"
#include "hudrender.h"
#include "hudscore.h"
#include "hudtex.h"
#include "player.h"
#include "playerhud.h"
#include "playersettings.h"
#include "race.h"
#include "racecoord.h"
#include "racecore.h"
#include "raceinit.h"
#include "raceparams.h"
#include "rcstates.h"
#include "realtime.h"
#include "scenery.h"
#include "sundraw.h"
#include "trackflow.h"
#include "vtable.h"
#include "world.h"

#define MAX_LOADS  4
#define MAX_ALLOCS 64
#define NUM_ARGS   48
#define NUM_SLOTS  20
#define NUM_CARS   4
#define FAKE_VT    0x01F00000u
#define DELTA      8
#define PLACE_WORDS 64                  // places -1 to 14, in bytes

// ------------------------------------------------------------ the globals
//
// What the linked sources read and the rest of the game defines.

RaceParameters  TheRaceParameters;
int32_t         PlayerNumPlayers;
struct Player  *PlayerPlayersByNumber[2];
struct Player  *PlayerPlayersByIndex[2];
int32_t         PlayerNetLocal = -1;
Race           *pCurrentRace;
RaceCoordinator *pRaceCoordinator;
World          *pCurrentWorld;
int32_t         RealTimeFrames;
float           PreviousCpuFrameRate;   // mainloop.c's
float           PreviousGpuFrameRate;
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
int32_t (*gSampleIsPlayingFn)(struct bSample *s);
int32_t SoundEnabled;
int32_t bResetGlare;

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

// ------------------------------------------------------ the race's answers
//
// UpdateScoring's callees, scripted: GetRacingCar, IsBlinking and the
// body's GetCollision; and race.c's two RaceCoordinator tests, as race.c
// has them.

static RaceCoordinator  coordinator;
static struct RacingCar racingCar;
static int              racingCarSet;
static int32_t          blinking;

static struct Car       *cars[NUM_CARS];
static CarCollisionBody *bodies[NUM_CARS];
static float             massInverse[NUM_CARS];
static CollisionBodyWitness witness;
static Collision         collision;
static int               collisionSet;

struct RacingCar *race_get_racing_car(Race *r, struct Car *c)
{
    (void)r;
    (void)c;
    return racingCarSet ? &racingCar : NULL;
}

int32_t car_is_blinking(Car *c)
{
    (void)c;
    return blinking;
}

static int body_index(const void *b)
{
    for (int i = 0; i < NUM_CARS; i++)
        if (b == (const void *)&bodies[i]->Dynamic.Body) return i;
    return -1;
}

struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i)
{
    printf("  getcoll B%d %d\n", body_index(b), i);
    return collisionSet ? &collision : NULL;
}

RCState racecoordinator_get_current_state(const RaceCoordinator *rc)
{
    return *(const RCState *)(const void *)rc;
}

int32_t racecoordinator_is_replay_demo_mode(const RaceCoordinator *rc)
{
    return racecoordinator_get_current_state(rc) == RCSTATE_REPLAY_DEMO_MODE;
}

// collision.c's two, which tools/collision_check.py checks; here so the
// harness need not link the world.
void collision_get_colliding_cars(Collision *c, struct Car **car1,
                                  struct Car **car2)
{
    CollisionBodyWitness *w = c->pWitness;

    *car1 = NULL;
    *car2 = NULL;
    if (w->pBody1->Type == CAR_COLLISION_BODY)
        *car1 = ((CarCollisionBody *)(void *)w->pBody1)->pCar;
    if (w->pBody2->Type == CAR_COLLISION_BODY)
        *car2 = ((CarCollisionBody *)(void *)w->pBody2)->pCar;
}

int32_t collision_is_smokeable_involved(Collision *c)
{
    CollisionBodyWitness *w = c->pWitness;

    if (w->pBody1->Type == SMOKEABLE_COLLISION_BODY)
        return 1;
    return w->pBody2->Type == SMOKEABLE_COLLISION_BODY;
}

static float fake_get_mass_inverse(void *self)
{
    int k = body_index((char *)self - DELTA);

    printf("  mass B%d\n", k);
    return k >= 0 ? massInverse[k] : 0.0f;
}

static void install_vtable(void)
{
    static VtEntry entries[COLLISIONBODY_VT_ENTRIES];

    entries[VT_SLOT(COLLISIONBODY_VT_GET_MASS_INVERSE)].delta = DELTA;
    entries[VT_SLOT(COLLISIONBODY_VT_GET_MASS_INVERSE)].fn =
        (VtFn)fake_get_mass_inverse;
    vt_install(FAKE_VT, entries, COLLISIONBODY_VT_ENTRIES);
}

// ----------------------------------------------------------- the sound

static int32_t sampleGiven, samplePlaying;
static int     theSample;

static struct bSample *seam_get_sample(const char *name)
{
    printf("  sample \"%s\" -> %s\n", name, sampleGiven ? "S" : "none");
    return sampleGiven ? (struct bSample *)(void *)&theSample : NULL;
}

static int32_t seam_is_playing(struct bSample *s)
{
    (void)s;
    printf("  playing? -> %d\n", samplePlaying);
    return samplePlaying;
}

static uint32_t fbits(float f)
{
    uint32_t v;
    memcpy(&v, &f, 4);
    return v;
}

static void seam_play(struct bSample *s, float volume, float a, float b)
{
    (void)s;
    printf("  play %08x %08x %08x\n", (unsigned)fbits(volume),
           (unsigned)fbits(a), (unsigned)fbits(b));
}

// GetTranslatedString: "TITLE" and the id.
static const char *seam_translate(int32_t id)
{
    static char text[32];

    printf("  translate %d\n", id);
    snprintf(text, sizeof text, "TITLE %d", id);
    return text;
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
    // The colours' fourth lanes: retail's stack under StartScore.
    memset(img + 220, 0xee, 4);
    memset(img + 236, 0xee, 4);
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

// The Player's scoring fields, and its three strings.
static void dump_score(int n)
{
    const struct Player *p = players[n];
    char                 key[32], text[512];
    char                *o = text;

    o += sprintf(o, "hang %08x pf %d lrp %d top %d n2540 %d coll %d smoke %d"
                 " seg %d places", (unsigned)fbits(p->HangTime),
                 p->PositionFlag, p->LastRacePosition, p->bNewTopSpeed,
                 p->New2540, p->bCollisionDetected, p->bSmokeableHit,
                 p->bSegmentCollisionDetected);
    for (int i = 0; i < 8; i++)
        o += sprintf(o, " %d", p->baPlaceReached[i]);
    sprintf(o, " music %d clean %d tscore %08x", p->bShownMusicTitle,
            p->numCleanLaps, (unsigned)p->tScoreAnimation.PackedTime);
    snprintf(key, sizeof key, "p%d.scoring", n);
    note(key, text);
    snprintf(key, sizeof key, "p%d.strings", n);
    snprintf(text, sizeof text, "\"%s\" \"%s\" \"%s\"", p->strEventTitle,
             p->strEventScore, p->strPrevScore);
    note(key, text);
    // The words a place from -1 to 14 reaches, LastCrossingTime's to
    // fInitialPursuitY's.
    o = text;
    for (int i = 0; i < PLACE_WORDS; i++)
        o += sprintf(o, "%02x", ((const uint8_t *)&p->LastCrossingTime)[i]);
    snprintf(key, sizeof key, "p%d.placewords", n);
    note(key, text);
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
        dump_score(n);
    }
    snprintf(text, sizeof text, "%d", bResetGlare);
    note("glare", text);
    dump_objects();
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

// A scoring field by name, or NULL.
static int32_t *score_word(struct Player *p, const char *n)
{
    static const char *names[] = {
        "PositionFlag", "LastRacePosition", "bNewTopSpeed", "New2540",
        "bCollisionDetected", "bSmokeableHit", "bSegment", "bShownMusicTitle",
        "numCleanLaps",
    };
    int32_t *words[9];

    words[0] = &p->PositionFlag;
    words[1] = &p->LastRacePosition;
    words[2] = &p->bNewTopSpeed;
    words[3] = &p->New2540;
    words[4] = &p->bCollisionDetected;
    words[5] = &p->bSmokeableHit;
    words[6] = &p->bSegmentCollisionDetected;
    words[7] = &p->bShownMusicTitle;
    words[8] = &p->numCleanLaps;
    for (int i = 0; i < 9; i++)
        if (!strcmp(n, names[i])) return words[i];
    if (!strncmp(n, "place", 5)) return &p->baPlaceReached[inum(n + 5)];
    return NULL;
}

static void set_player(int k, const char *n, char **a, int na)
{
    struct Player *p = players[k];
    uint32_t       v = na > 0 ? num(a[0]) : 0;
    int32_t       *w = score_word(p, n);

    if (w != NULL) *w = (int32_t)v;
    else if (!strcmp(n, "PN")) p->PlayerNumber = (int32_t)v;
    else if (!strcmp(n, "chf")) p->CurrentHudFeatures = v;
    else if (!strcmp(n, "screen")) p->HudScreenHash = v;
    else if (!strcmp(n, "score")) p->TotalScore = (int32_t)v;
    else if (!strcmp(n, "HangTime")) p->HangTime = fnum(a[0]);
    else if (!strcmp(n, "tscore")) p->tScoreAnimation.PackedTime = v;
    else if (!strcmp(n, "scoretotal")) p->pFlailerScoreTotal = object(a[0]);
    else if (!strcmp(n, "evscoreobj")) p->pFlailerEventScore = object(a[0]);
    else if (!strcmp(n, "evtitleobj")) p->pFlailerEventTitle = object(a[0]);
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
    else if (!strcmp(k, "sound")) SoundEnabled = (int32_t)v;
    else if (!strcmp(k, "glare")) bResetGlare = (int32_t)v;
    else {
        printf("  no global %s\n", k);
        exit(2);
    }
}

static void set_rp(char **a)
{
    int32_t v = inum(a[1]);

    if (!strcmp(a[0], "RaceType")) TheRaceParameters.RaceType = v;
    else if (!strcmp(a[0], "Laps")) TheRaceParameters.NumLapsInRace = v;
    else if (!strcmp(a[0], "BeACop")) TheRaceParameters.BeACop = v;
    else if (!strcmp(a[0], "TTT"))
        TheRaceParameters.TimeTrialTime.PackedTime = (uint32_t)v;
    else if (!strcmp(a[0], "P2P")) TheRaceParameters.Point2Point = v;
    else {
        printf("  no rp %s\n", a[0]);
        exit(2);
    }
}

static void set_car(char **a)
{
    struct Car *c = cars[inum(a[0])];

    if (!strcmp(a[1], "player")) {
        int32_t k = inum(a[2]);
        c->pPlayer = k >= 0 ? players[k] : NULL;
    } else if (!strcmp(a[1], "up")) {
        vec4(&c->State.BodyMatrix.v2, a + 2);
    } else if (!strcmp(a[1], "wheels")) {
        c->State.nWheelsTouchingGround = inum(a[2]);
    } else {
        printf("  no car field %s\n", a[1]);
        exit(2);
    }
}

static void set_body(char **a)
{
    int              k = inum(a[0]);
    int32_t          car = inum(a[2]);
    CarCollisionBody *b = bodies[k];

    b->Dynamic.Body.Type = (int8_t)inum(a[1]);
    b->pCar = car >= 0 ? cars[car] : NULL;
    massInverse[k] = fnum(a[3]);
}

static void set_collision(char **a, int na)
{
    collisionSet = strcmp(a[0], "-") != 0;
    if (!collisionSet) return;
    if (na < 7) exit(2);
    witness.pBody1 = &bodies[inum(a[0])]->Dynamic.Body;
    witness.pBody2 = &bodies[inum(a[1])]->Dynamic.Body;
    collision.pWitness = &witness;
    collision.TotalImpulseMagnitude = fnum(a[2]);
    collision.ImpulseDirection.x = fnum(a[3]);
    collision.ImpulseDirection.y = fnum(a[4]);
    collision.ImpulseDirection.z = fnum(a[5]);
    collision.ImpulseDirection.pad = fnum(a[6]);
}

static void set_racing(char **a)
{
    racingCarSet = strcmp(a[0], "-") != 0;
    if (!racingCarSet) return;
    racingCar.NumLapsCompleted = (int8_t)inum(a[0]);
    racingCar.RacePosition = (int8_t)inum(a[1]);
    racingCar.CrossedFinishLine = (int8_t)inum(a[2]);
    racingCar.FinishReason = (int16_t)inum(a[3]);
}

// The slot's animator, or NULL having said so.
static HudAnimator *slot(char *s)
{
    HudAnimator *a = players[curPlayer]->pHudAnimations[inum(s)];
    if (a == NULL) printf("  no anim\n");
    return a;
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
    if (!strcmp(a[0], "rp")) set_rp(a + 1);
    else if (!strcmp(a[0], "g")) set_global(a + 1);
    else if (!strcmp(a[0], "use")) curPlayer = inum(a[1]);
    else if (!strcmp(a[0], "pl"))
        set_player(inum(a[1]), a[2], a + 3, n - 3);
    else if (!strcmp(a[0], "rcstate"))
        coordinator.CurrentRCState = (RCState)inum(a[1]);
    else if (!strcmp(a[0], "sample")) sampleGiven = inum(a[1]);
    else if (!strcmp(a[0], "playing")) samplePlaying = inum(a[1]);
    else if (!strcmp(a[0], "blink")) blinking = inum(a[1]);
    else if (!strcmp(a[0], "racing")) set_racing(a + 1);
    else if (!strcmp(a[0], "car")) set_car(a + 1);
    else if (!strcmp(a[0], "body")) set_body(a + 1);
    else if (!strcmp(a[0], "coll")) set_collision(a + 1, n - 1);
    else if (!strcmp(a[0], "pos")) {
        struct FlailerObjectChunk *o = object(a[1]);
        o->X = fnum(a[2]);
        o->Y = fnum(a[3]);
        o->ScaleX = fnum(a[4]);
        o->ScaleY = fnum(a[5]);
    } else if (!strcmp(a[0], "do")) player_hud_do_animations(p);
    else if (!strcmp(a[0], "new")) {
        if (p->pHudAnimations[inum(a[1])] == NULL)
            p->pHudAnimations[inum(a[1])] = hudanim_new();
    } else if (!strcmp(a[0], "an")) {
        uint32_t v = num(a[3]);
        if ((an = slot(a[1])) == NULL) return;
        memcpy(anim_word(an, inum(a[2])), &v, 4);
    } else if (!strcmp(a[0], "sound")) play_score_sound(inum(a[1]));
    else if (!strcmp(a[0], "anim")) {
        bVector2 pos, dpos, dpos2, scale, dscale;
        bVector4 colour, dcolour;
        vec2(&pos, a + 1);
        vec2(&dpos, a + 3);
        vec2(&dpos2, a + 5);
        vec2(&scale, a + 7);
        vec2(&dscale, a + 9);
        vec4(&colour, a + 11);
        vec4(&dcolour, a + 15);
        player_start_score_animation(p, &pos, &dpos, &dpos2, &scale, &dscale,
                                     &colour, &dcolour);
    } else if (!strcmp(a[0], "bonus"))
        printf("  = %d\n", player_get_finish_bonus(p, inum(a[1])));
    else if (!strcmp(a[0], "score")) player_start_score(p, inum(a[1]));
    else if (!strcmp(a[0], "scorev"))
        player_start_score_value(p, inum(a[1]), inum(a[2]));
    else if (!strcmp(a[0], "update")) player_update_scoring(p);
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
    gGetInGameSampleFn = seam_get_sample;
    gSampleIsPlayingFn = seam_is_playing;
    gSamplePlayFn = seam_play;
    gHudTranslateFn = seam_translate;
    pRaceCoordinator = &coordinator;

    install_vtable();
    for (int k = 0; k < NUM_CARS; k++) {
        cars[k] = (struct Car *)calloc(1, sizeof(struct Car));
        bodies[k] = (CarCollisionBody *)calloc(1, sizeof(CarCollisionBody));
        bodies[k]->Dynamic.Body._vtable = FAKE_VT;
        cars[k]->pDynamicCollisionBody = bodies[k];
    }
    for (int k = 0; k < 2; k++) {
        players[k] = (struct Player *)calloc(1, sizeof(struct Player));
        players[k]->MyCar = cars[k];
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
