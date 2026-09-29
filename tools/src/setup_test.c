// Drives bsetup.c for tools/setup_check.py. A script of ops, one per line,
// fields split on '|':
//
//   obj|HASH|KIND|L|T|R|B|CY|XBITS   an object on the screen: KIND 0 none,
//                      1 text, 2 bitmap; its box, its centre Y, its top
//                      left X (float bits)
//   joy|PORT|N         IsJoystickPluggedIn(PORT)
//   dcs|A|B|C|D|E      Fred's DataChallengeScreen
//   type|N, cars|N     Fred's GameType and NumPlayerCars
//   police|N           Fred.MainMenuOpts.mPolice (the port's gf->copsOn)
//   elapsed|BITS       RealTimeElapsed
//   msg|M|ITEM|PORT    the callback, with {ITEM, PORT, 0x5a, 0x5b}
//   wave|LO|HI|RATE    a tfeSineWave of its own (float bits)
//   wstep|DT           steps it and prints its phase and both values
//   dump               the instance, Fred and TheRaceParameters
//
// The animation kit is not linked: the banim_* below stand in for it and
// print what they are asked, as the model's stubs at retail's kit
// addresses do. Every hook prints too.
//
// Fred is read and written at retail's offsets, written out here rather
// than taken from bsetup.h, so a wrong offset there shows.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bsetup.h"
#include "memcard.h"

#define MAX_OBJECTS 32

#define RETAIL_DCS              8
#define RETAIL_GAME_TYPE        0x1072c
#define RETAIL_NUM_PLAYER_CARS  0x10734

typedef struct {
    uint32_t hash;
    int      kind;
    int32_t  box[4];
    int32_t  cy;
    float    x;
} Object;

static Object   objects[MAX_OBJECTS];
static int      numObjects;
static int      joy[2];
static int32_t  rpNumPlayerCars = -7, rpRaceMode = -9;
static uint8_t  fred[BMC_SAVE_SIZE];
static BAnim    anim;
static BGameFlow flow;
static BSetup   setup;
static BSineWave wave;

static uint32_t fbits(float f)
{
    uint32_t u;
    memcpy(&u, &f, 4);
    return u;
}

static float bitsf(uint32_t u)
{
    float f;
    memcpy(&f, &u, 4);
    return f;
}

static Object* find(uint32_t hash)
{
    for (int i = 0; i < numObjects; i++) {
        if (objects[i].hash == hash && objects[i].kind) {
            return &objects[i];
        }
    }
    return NULL;
}

static Object* slot(uint32_t hash)
{
    for (int i = 0; i < numObjects; i++) {
        if (objects[i].hash == hash) {
            return &objects[i];
        }
    }
    if (numObjects == MAX_OBJECTS) {
        exit(3);
    }
    Object* o = &objects[numObjects++];
    memset(o, 0, sizeof *o);
    o->hash = hash;
    return o;
}

static int32_t get32(const uint8_t* p)
{
    return (int32_t)((uint32_t)p[0] | (uint32_t)p[1] << 8
                     | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24);
}

// ------------------------------------------------------------- the kit

static const char* slideName(const BSlideAnim* s)
{
    static char buf[16];
    if (s == &setup.beACop.slideIn) return "slidein";
    if (s == &setup.beACop.exit.slide) return "exit";
    snprintf(buf, sizeof buf, "?%p", (const void*)s);
    return buf;
}

static const char* hlName(const BHighlightAnim* h)
{
    if (h == &setup.beACop.highlight) return "hl1";
    if (h == &setup.beACop.change) return "hl2";
    return "?";
}

void banim_set_clock(BAnim* a, int32_t timer, float elapsed)
{
    a->timer = timer;
    a->elapsed = elapsed;
}

void bsel_init(BAnim* a, BSelSet* s, uint32_t screen)
{
    (void)a;
    memset(s, 0, sizeof *s);
    s->screen = screen;
    s->mode = 1;
    printf("  kit sel init\n");
}

void bsel_set_indicator_mode(BSelSet* s, int mode)
{
    s->indicatorMode = mode;
}

void bsel_add_items(BAnim* a, BSelSet* s, const uint32_t* hashes, int n)
{
    (void)a;
    printf("  kit sel items %08x mode %d n %d", s->screen, s->indicatorMode,
           n);
    for (int i = 0; i < n; i++) {
        printf(" %08x", hashes[i]);
    }
    printf("\n");
}

void bsel_set_current(BAnim* a, BSelSet* s, uint32_t object)
{
    (void)a;
    (void)s;
    printf("  kit sel current %08x\n", object);
}

void banim_blurb_init(BAnim* a, BBlurb* b, uint32_t screen,
                      uint32_t slideText, uint32_t fadeout, uint32_t whiteout)
{
    (void)a;
    (void)b;
    printf("  kit blurb init %08x %08x %08x %08x\n", screen, slideText,
           fadeout, whiteout);
}

void banim_blurb_new_text_id(BAnim* a, BBlurb* b, int languageID)
{
    (void)a;
    (void)b;
    printf("  kit blurb text %d\n", languageID);
}

void banim_blurb_animate(BAnim* a, BBlurb* b)
{
    (void)a;
    (void)b;
    printf("  kit blurb animate\n");
}

void banim_blurb_release(BAnim* a, BBlurb* b)
{
    (void)a;
    (void)b;
    printf("  kit blurb release\n");
}

void banim_slide_in_init(BAnim* a, BSlideAnim* s, uint32_t screen,
                         float targetX)
{
    (void)a;
    memset(s, 0, sizeof *s);
    printf("  kit slidein init %08x %08x\n", screen, fbits(targetX));
}

void banim_slide_animate(BAnim* a, BSlideAnim* s)
{
    (void)a;
    printf("  kit slide animate %s\n", slideName(s));
}

void banim_slide_release(BAnim* a, BSlideAnim* s)
{
    (void)a;
    printf("  kit slide release %s\n", slideName(s));
}

void banim_slide_add_group(BAnim* a, BSlideAnim* s, uint32_t group,
                           uint32_t master, float start, float end,
                           float duration)
{
    (void)a;
    printf("  kit slide group %s %08x %08x %08x %08x %08x\n", slideName(s),
           group, master, fbits(start), fbits(end), fbits(duration));
}

void banim_highlight_init(BAnim* a, BHighlightAnim* h, uint32_t screen,
                          uint32_t textObject, int32_t targetColor)
{
    (void)a;
    printf("  kit hl init %s %08x %08x %08x\n", hlName(h), screen,
           textObject, (uint32_t)targetColor);
}

void banim_highlight_set_item(BAnim* a, BHighlightAnim* h, uint32_t item)
{
    (void)a;
    printf("  kit hl item %s %08x\n", hlName(h), item);
}

void banim_highlight_animate(BAnim* a, BHighlightAnim* h)
{
    (void)a;
    printf("  kit hl animate %s\n", hlName(h));
}

// The model's constructor stub writes 0.75 into TotalTime, as though the
// screen had its groups.
void banim_exit_init(BAnim* a, BExitAnim* e, uint32_t screen,
                     const char* target)
{
    (void)a;
    memset(e, 0, sizeof *e);
    e->target = target;
    e->slide.totalTime = 0.75f;
    printf("  kit exit init %08x %s %d\n", screen, target ? target : "(null)",
           1);
}

int banim_exit_message(BAnim* a, BExitAnim* e, int message, int32_t* param,
                       int32_t* noise)
{
    (void)a;
    (void)e;
    printf("  kit exit msg %d\n", message);
    // The model's stub marks the reply the same way.
    *param = 100 + message;
    *noise = 0;
    return 0;
}

// ------------------------------------------------------------ the hooks

static int h_find(void* u, uint32_t screen, uint32_t object, int type)
{
    (void)u;
    Object* o = find(object);
    printf("  find %08x %08x %d\n", screen, object, type);
    return o && (type == 0 || o->kind == type);
}

static void h_alpha(void* u, uint32_t screen, uint32_t object, int alpha)
{
    (void)u;
    printf("  alpha %08x %08x %d %d\n", screen, object, alpha, -1);
}

static void h_centery(void* u, uint32_t screen, uint32_t object, float y)
{
    (void)u;
    printf("  centery %08x %08x %08x\n", screen, object, fbits(y));
}

static void h_chunkvis(void* u, uint32_t screen, uint32_t object, int vis)
{
    (void)u;
    printf("  chunkvis %08x %08x %d\n", screen, object, vis);
}

static int32_t h_cy(void* u, uint32_t screen, uint32_t object)
{
    (void)u;
    Object* o = find(object);
    printf("  cy %08x %08x\n", screen, object);
    return o ? o->cy : 0;
}

static void h_bbox(void* u, uint32_t screen, uint32_t object, int32_t box[4])
{
    (void)u;
    Object* o = find(object);
    printf("  bbox %08x %08x\n", screen, object);
    if (o) {
        memcpy(box, o->box, sizeof o->box);
    }
}

static void h_topy(void* u, uint32_t screen, uint32_t object, int32_t y)
{
    (void)u;
    printf("  topy %08x %08x %d\n", screen, object, y);
}

static float h_topx(void* u, uint32_t screen, uint32_t object)
{
    (void)u;
    Object* o = find(object);
    printf("  topx %08x %08x\n", screen, object);
    return o ? o->x : 0.0f;
}

static void h_lang(void* u, uint32_t screen, uint32_t object, int id)
{
    (void)u;
    printf("  lang %08x %08x %d\n", screen, object, id);
}

static void h_vis(void* u, uint32_t screen, uint32_t object, int vis)
{
    (void)u;
    printf("  vis %08x %08x %d\n", screen, object, vis);
}

static void h_gray(void* u, uint32_t screen, uint32_t item, int mode)
{
    (void)u;
    printf("  gray %08x %08x %d\n", screen, item, mode);
}

static int h_joy(void* u, int port)
{
    (void)u;
    printf("  joy %d\n", port);
    return port == 0 || port == 1 ? joy[port] : 0;
}

static void h_movie(void* u, const char* path)
{
    (void)u;
    printf("  movie %s\n", path);
}

static void h_help(void* u, const int32_t* lines)
{
    (void)u;
    if (!lines) {
        printf("  help none\n");
        return;
    }
    printf("  help");
    for (; *lines; lines++) {
        printf(" %d", *lines);
    }
    printf("\n");
}

static void h_cars(void* u)
{
    (void)u;
    printf("  fred cars\n");
}

static void h_preload(void* u)
{
    (void)u;
    printf("  fred preload\n");
}

static void h_rpsetup(void* u)
{
    (void)u;
    printf("  fred rp setup\n");
}

static void h_rp(void* u, int32_t numPlayerCars, int32_t raceMode)
{
    (void)u;
    rpNumPlayerCars = numPlayerCars;
    rpRaceMode = raceMode;
}

static const BSetupHooks hooks = {
    .user = NULL,
    .findObject = h_find,
    .setBitmapAlpha = h_alpha,
    .setBitmapCenterY = h_centery,
    .setBitmapVisible = h_chunkvis,
    .getCenterY = h_cy,
    .getBoundingBox = h_bbox,
    .setTopLeftY = h_topy,
    .getTopLeftX = h_topx,
    .setLanguageID = h_lang,
    .setVisible = h_vis,
    .grayMenuItem = h_gray,
    .isJoystickPluggedIn = h_joy,
    .startMovie = h_movie,
    .setHelpOverride = h_help,
    .makeChallengeCarsAvailable = h_cars,
    .preloadCars = h_preload,
    .setupRaceParametersAfterRaceSetup = h_rpsetup,
    .setRaceParameters = h_rp,
    .trace = NULL,
};

static uint32_t num(const char* s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static void dump(void)
{
    const BBeACopSetup* b = &setup.beACop;
    const uint8_t*      d = fred + RETAIL_DCS;

    if (!b->live) {
        printf("  inst 0\n");
    } else {
        printf("  inst 1 cur %08x data %d %d %d %d %d exit %d\n", b->current,
               b->data.numPlayers, b->data.challengeMode, b->data.raceMode,
               b->data.skillLevel, b->data.beACopSkill, b->exitActive);
        printf("  arrows %d %d %08x wave %08x %08x %08x %08x\n",
               b->arrows.hasLeft != 0, b->arrows.hasRight != 0,
               b->arrows.follow, fbits(b->arrows.pulse.lo),
               fbits(b->arrows.pulse.hi), fbits(b->arrows.pulse.rate),
               fbits(b->arrows.pulse.phase));
    }
    printf("  fred dcs %d %d %d %d %d type %d cars %d\n", get32(d),
           get32(d + 4), get32(d + 8), get32(d + 12), get32(d + 16),
           get32(fred + RETAIL_GAME_TYPE),
           get32(fred + RETAIL_NUM_PLAYER_CARS));
    printf("  rp %d %d\n", rpNumPlayerCars, rpRaceMode);
}

static void put32(uint8_t* p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

int main(int argc, char** argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: setup_test script\n");
        return 2;
    }
    FILE* sc = fopen(argv[1], "r");
    if (!sc) {
        return 2;
    }
    flow.anim = &anim;
    flow.fred = fred;
    bsetup_init(&setup, &flow, &hooks);
    static char line[512];
    while (fgets(line, sizeof line, sc)) {
        line[strcspn(line, "\r\n")] = 0;
        if (!line[0]) {
            continue;
        }
        printf("> %s\n", line);
        char* arg[12];
        int n = 0;
        for (char* t = strtok(line, "|"); t && n < 12; t = strtok(NULL, "|")) {
            arg[n++] = t;
        }
        const char* op = arg[0];
        if (!strcmp(op, "obj")) {
            Object* o = slot(num(arg[1]));
            o->kind = (int)num(arg[2]);
            for (int i = 0; i < 4; i++) {
                o->box[i] = (int32_t)num(arg[3 + i]);
            }
            o->cy = (int32_t)num(arg[7]);
            o->x = bitsf(num(arg[8]));
        } else if (!strcmp(op, "joy")) {
            joy[num(arg[1]) & 1] = (int)num(arg[2]);
        } else if (!strcmp(op, "dcs")) {
            for (int i = 0; i < 5; i++) {
                put32(fred + RETAIL_DCS + 4 * i, num(arg[1 + i]));
            }
        } else if (!strcmp(op, "type")) {
            put32(fred + RETAIL_GAME_TYPE, num(arg[1]));
        } else if (!strcmp(op, "cars")) {
            put32(fred + RETAIL_NUM_PLAYER_CARS, num(arg[1]));
        } else if (!strcmp(op, "wave")) {
            bsine_init(&wave, bitsf(num(arg[1])), bitsf(num(arg[2])),
                       bitsf(num(arg[3])));
            printf("  wave %08x %08x %08x %08x\n", fbits(wave.lo),
                   fbits(wave.hi), fbits(wave.rate), fbits(wave.phase));
        } else if (!strcmp(op, "wstep")) {
            bsine_step(&wave, bitsf(num(arg[1])));
            printf("  wave phase %08x val %08x int %d\n", fbits(wave.phase),
                   fbits(bsine_val(&wave)), bsine_val_int(&wave));
        } else if (!strcmp(op, "police")) {
            flow.copsOn = (int)num(arg[1]);
        } else if (!strcmp(op, "elapsed")) {
            flow.realElapsed = bitsf(num(arg[1]));
        } else if (!strcmp(op, "msg")) {
            BScreenCallbackData data;
            memset(&data, 0, sizeof data);
            data.itemHash = num(arg[2]);
            data.port = (int32_t)num(arg[3]);
            data.param = 0x5a;
            data.noise = 0x5b;
            bsetup_beacop_callback(&flow, (BScreenMessage)num(arg[1]), &data);
            printf("  data %d %d\n", data.param, data.noise);
        } else if (!strcmp(op, "dump")) {
            dump();
        }
    }
    return 0;
}
