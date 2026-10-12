// Drives bcarsel.c for tools/carsel_check.py: car select's screen callback,
// its JoyHandler, the preload and CloseSelectCarScreen, over flailer.c with
// FRONTB's screens loaded and GLOBALB's car records and skins. A script of
// ops, one per line, fields split on '|'; numbers are C literals, floats
// their bits:
//
//   load|PATH              a bundle: bui_open, then flailer_add_project
//   cars|PATH              GLOBALB: the car records and the skin table
//   spec|T|Z|MPH|KPH|BHP|FULL|SHORT   car T's CarSpecs
//   cr|T|OFF|SIZE|V        a car record's bytes; sk|I|OFF|SIZE|V a skin's
//   g|NAME|V               gametype, players, units, lang, sound, allcars,
//                          rtimer, rframes, relapsed, help (the help menu's
//                          answer), pi (the next popup's index)
//   fs|P|T|STATUS|N|SKINS|DASH   player P's aCarStatus[T]; SKINS is a
//                          comma list of bytes
//   ride|P|MODE|T|SKIN     player P's RideInfoByGameMode[MODE]
//   pts|P|V                player P's AccumulatedPoints
//   xl|ID|TEXT             GetTranslatedString's answer for ID
//   egg|T|V                the easter eggs' answer for car T
//   ev|T|TREE|NUM          car T an event's reward (TREE -1: none)
//   isl|T|V                CarLoader::IsLoaded's answer for car T
//   msg|MSG|ITEM|PORT|PARAM|NOISE   SelectCarScreenCallback
//   joy|PORT|EV|PRESSED    the JoyHandler, as AddJoyHandler delivers it;
//                          "joy none" when nothing is registered for it
//   preload, close
//   tex|MODE               GetTextureInfo's answer: 0 none, 1 a swatch, 2 one
//                          with no image, 3 no palette size, 4 no palette
//   solid|V                the Solid eModel::Init gives the next model
//   blend|I|V              selector I's camera's Blend
//   frame|SIZE             a fresh frame-malloc buffer of SIZE bytes
//   neb|MODE               the nebula's SetEmitterData: 1 every emitter finds
//                          its data, 0 none, 2 all but every third
//
// After each msg, joy, preload and close every line that changed: the
// screen, each selector's fields, cars, unlock box, thumbnail row and
// nebula (its emitters' bytes), its two rendering cars and its camera,
// the frame buffer, the nebula's data's colour keys, the preload, the
// CarLoader's two flags, the players' settings and every Flailer object's
// bytes. The hooks and the 3D seams log their calls in the model's stubs'
// words.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acidsys.h"
#include "bcarsel.h"
#include "bui.h"
#include "cartypeinfo.h"
#include "eframe.h"
#include "elight.h"
#include "emodel.h"
#include "flailer.h"
#include "fred.h"
#include "fredrace.h"
#include "joyevent.h"
#include "nfsrewards.h"
#include "realtime.h"
#include "scenerycull.h"
#include "texturepack.h"

#define MAX_LOADS  4
#define NUM_ARGS   48
#define MAX_XL     256
#define CAR_REC    1376
#define NUM_CARS   64

// ------------------------------------------------------------ the globals

FrontendDatabase Fred;
int32_t          RealTimer;
int32_t          RealTime;
int32_t          RealTimeFrames;
float            RealTimeElapsed;

// fredrace.c's two, which the selector calls (fredrace.c itself pulls in
// the race).
RideInfo *fpi_get_selected_ride_info(FrontendPlayerInfo *p, int32_t gameType)
{
    return &p->RideInfoByGameMode[gameType];
}

void ride_info_init(RideInfo *r, int32_t type, int32_t skin, int32_t dash,
                    int32_t vertexDamage)
{
    r->CanBeVertexDamaged = (int8_t)vertexDamage;
    r->Type = type;
    r->SkinNumber = (int8_t)skin;
    r->HasDash = (int8_t)dash;
    r->InstanceIndex = 0;
}

static int player_of(const FrontendPlayerInfo *p)
{
    return (int)(p - Fred.FrontendPlayers);
}

// AssignCarOfType, stubbed in the model too.
void fpi_assign_car_of_type(FrontendPlayerInfo *p, int32_t mode,
                            int32_t type, uint32_t skin, int32_t dash)
{
    printf("  assign %d %d %d %d %d\n", player_of(p), (int)mode, (int)type,
           (int)skin, (int)dash);
}

// ------------------------------------------------------------ the cars

static uint8_t     cars[NUM_CARS * CAR_REC];
static CarTypeInfo hostcars[NUM_CARS];
static CarSpecs    specs[NUM_CARS];
static uint8_t    *skinchunk;
static int         skinlen;

static void sync_cars(void)
{
    for (int t = 0; t < NUM_CARS; t++) {
        const CarSpecs *keep = hostcars[t].pCarSpecs;
        memcpy(&hostcars[t], cars + CAR_REC * t,
               offsetof(CarTypeInfo, pCarSpecs));
        hostcars[t].pCarSpecs = keep;
        memcpy(&hostcars[t].Pad1, cars + CAR_REC * t + 1372, 4);
    }
    CarTypeInfoArray = hostcars;
}

static void put_le(uint8_t *p, int n, uint32_t v)
{
    for (int i = 0; i < n; i++)
        p[i] = (uint8_t)(v >> (8 * i));
}

static void load_cars(const char *path)
{
    FILE    *f = fopen(path, "rb");
    long     len, off = 0;
    uint8_t *d;
    int      haveCars = 0;

    if (!f) {
        printf("  cannot open %s\n", path);
        exit(2);
    }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    d = (uint8_t *)malloc((size_t)len);
    if (fread(d, 1, (size_t)len, f) != (size_t)len) exit(2);
    fclose(f);
    while (off + 8 <= len) {
        uint32_t id, size;
        memcpy(&id, d + off, 4);
        memcpy(&size, d + off + 4, 4);
        if (id == 0x34600 && !haveCars) {
            memcpy(cars, d + off + 16, sizeof cars);
            haveCars = 1;
        } else if (id == 0x34601 && !skinchunk) {
            skinlen = (int)size + 8;
            skinchunk = (uint8_t *)malloc((size_t)skinlen);
            memcpy(skinchunk, d + off, (size_t)skinlen);
        }
        off += 8 + (long)size;
    }
    free(d);
    sync_cars();
    SkinInfoTable = (SkinInfo *)(void *)(skinchunk + 8);
    NumSkinInfo = (skinlen - 8) >> 6;
    printf("  cars %d skins %d\n", haveCars, (int)NumSkinInfo);
}

// ------------------------------------------------------------ the seams

static struct {
    int32_t id;
    char    text[128];
} xl[MAX_XL];
static int numXl;

static int32_t language, soundOn, helpActive, nextPopup;
static int32_t eggs[NUM_CARS], loadedAns[NUM_CARS];
static int32_t evTree[NUM_CARS], evNum[NUM_CARS];
static int32_t loaderFlags[2];

// Each id its own buffer, as the string table's are.
static const char *seam_xl(int32_t id)
{
    int i;
    for (i = 0; i < numXl && xl[i].id != id; i++)
        ;
    if (i == numXl) {
        if (numXl == MAX_XL) exit(3);
        numXl++;
        xl[i].id = id;
        snprintf(xl[i].text, sizeof xl[i].text, "M%x", (unsigned)id);
    }
    printf("  xl %#x -> %s\n", (unsigned)id, xl[i].text);
    return xl[i].text;
}

static const char *h_translate(void *u, int32_t id)
{
    (void)u;
    return seam_xl(id);
}

static const char *h_translate_string(void *u, const char *s)
{
    (void)u;
    printf("  xs %s\n", s);
    return s;
}

static void h_sound(void *u, int32_t ev)
{
    (void)u;
    printf("  sound %d\n", (int)ev);
}

static void h_stop_sound(void *u, int32_t ev)
{
    (void)u;
    printf("  stopsound %d\n", (int)ev);
}

static void h_help(void *u, const int32_t *lines)
{
    char  text[256];
    char *o = text;
    (void)u;
    if (!lines) {
        printf("  help -\n");
        return;
    }
    *o = 0;
    for (; *lines; lines++)
        o += sprintf(o, "%s%d", o == text ? "" : ",", (int)*lines);
    printf("  help %s\n", text);
}

static int h_help_active(void *u)
{
    (void)u;
    printf("  helpmenu? -> %d\n", (int)helpActive);
    return helpActive;
}

static int h_summon(void *u, BPopupConfig *c)
{
    (void)u;
    printf("  popup n %d flags %u screen %08x msg %s b %#x %#x %#x "
           "p %d %d %d cancel %d dismiss %d start %d port %d timeout %d "
           "title %d -> %d\n",
           (int)c->numButtons, (unsigned)c->flags, (unsigned)c->screen,
           c->message ? c->message : "(null)", (unsigned)c->button[0],
           (unsigned)c->button[1], (unsigned)c->button[2],
           (int)c->buttonParam[0], (int)c->buttonParam[1],
           (int)c->buttonParam[2], (int)c->cancelParam, (int)c->dismissParam,
           (int)c->startButton, (int)c->joyPort, (int)c->timeout,
           (int)c->title, (int)nextPopup);
    return nextPopup++;
}

static void h_dismiss(void *u, int popup)
{
    (void)u;
    printf("  dismiss %d\n", popup);
}

static void h_change(void *u, const char *name, int push)
{
    (void)u;
    printf("  change %s %d\n", name, push);
}

static void h_start_race(void *u)
{
    (void)u;
    printf("  startrace\n");
}

static void ride_text(char *out, const RideInfo *r)
{
    sprintf(out, "%d %d %d %d %d", (int)r->Type, (int)r->InstanceIndex,
            (int)r->SkinNumber, (int)r->HasDash, (int)r->CanBeVertexDamaged);
}

static void h_loader_front_end(void *u)
{
    (void)u;
    loaderFlags[0] = loaderFlags[1] = 1;
}

static void h_load(void *u, const RideInfo *r)
{
    char t[64];
    (void)u;
    ride_text(t, r);
    printf("  load %s\n", t);
}

static int h_is_loaded(void *u, const RideInfo *r)
{
    char t[64];
    int  v = r->Type >= 0 && r->Type < NUM_CARS ? loadedAns[r->Type] : 1;
    (void)u;
    ride_text(t, r);
    printf("  isloaded %s 0 -> %d\n", t, v);
    return v;
}

static void h_unload(void *u, const RideInfo *r)
{
    char t[64];
    (void)u;
    ride_text(t, r);
    printf("  unload %s\n", t);
}

static void h_begin(void *u)
{
    (void)u;
    printf("  begin 0\n");
}

static int h_egg(void *u, int32_t type, int copsOnly)
{
    int v = type >= 0 && type < NUM_CARS ? eggs[type] : 0;
    (void)u;
    printf("  egg? %d %d -> %d\n", (int)type, copsOnly, v);
    return v;
}

static const char *r_translate(void *u, int32_t id)
{
    (void)u;
    return seam_xl(id);
}

static int32_t r_language(void *u)
{
    (void)u;
    return language;
}

static int r_find_event(void *u, int32_t type, int32_t *tree, int32_t *num)
{
    int v = type >= 0 && type < NUM_CARS && evTree[type] != -1;
    (void)u;
    printf("  event? %d -> %d\n", (int)type, v);
    if (v) {
        *tree = evTree[type];
        *num = evNum[type];
    }
    return v;
}

static const NFSRewardHooks rewardHooks = {
    NULL, r_translate, r_language, r_find_event, NULL,
};

static void h_blurb(void *u, char *buf, int len, int32_t type, int32_t gt,
                    int flag)
{
    (void)u;
    nfs_format_unlock_blurb_for_car(&rewardHooks, buf, len, type, gt, flag);
}

static uint32_t fbits(float f)
{
    uint32_t v;
    memcpy(&v, &f, 4);
    return v;
}

static void hex_bytes(char *out, const uint8_t *p, int n)
{
    static const char digits[] = "0123456789abcdef";
    for (int i = 0; i < n; i++) {
        *out++ = digits[p[i] >> 4];
        *out++ = digits[p[i] & 15];
    }
    *out = 0;
}

static void h_rtext(void *u, uint32_t screen, uint32_t obj, uint32_t rect,
                    const char *text, float scale)
{
    (void)u;
    printf("  rtext %08x %08x %08x \"%s\" %08x\n", (unsigned)screen,
           (unsigned)obj, (unsigned)rect, text, (unsigned)fbits(scale));
}

static void h_speak(void *u, int32_t type, int cop, int hp)
{
    (void)u;
    if (cop) printf("  speak 211 1 %d\n", (int)type);
    else printf("  speak 146 2 %d %d\n", hp ? 1 : 0, (int)type);
}

static void h_fade(void *u, float level)
{
    (void)u;
    printf("  fade %08x\n", (unsigned)fbits(level));
}

static int h_sound_enabled(void *u)
{
    (void)u;
    return soundOn;
}

static int32_t h_language(void *u)
{
    (void)u;
    return language;
}

static void h_per_port(void *u, int on)
{
    (void)u;
    printf("  perport %d\n", on);
}

static void h_stop_movie(void *u)
{
    (void)u;
    printf("  stopmovie\n");
}

// AddJoyHandler and RemoveJoyHandler as the model keeps them: one handler
// for each (port, event), the last registered.
static struct { JoyHandler fn; void* obj; } joys[2][64];

void AddJoyHandler(JoystickPort port, JoyEvent ev, JoyHandler fn, void* obj)
{
    joys[port][ev].fn  = fn;
    joys[port][ev].obj = obj;
}

void RemoveJoyHandler(JoystickPort port, JoyEvent ev)
{
    joys[port][ev].fn  = NULL;
    joys[port][ev].obj = NULL;
}

// ------------------------------------------------------------ the 3D seams

// The rendering cars, the camera, the models, the light and the textures
// are stubbed, here as in the model. The constructors only clear and keep
// the view; the camera's setters keep what they are given, raw.

uint8_t *CurrentBufferPos;
uint8_t *CurrentBufferEnd;
int32_t  FrameMallocFailed;
uint32_t FrameMallocFailAmount;
static uint8_t *frameBase;

void (*gEModelRenderFn)(eModel *m, bMatrix4 *matrix, void *light,
                        uint32_t flags);

static uint32_t solidNext = 1;
static int      texMode = 1;

void fecar_init(FrontEndRenderingCar *f, RideInfo *ride, int32_t view_id)
{
    memset(f, 0, sizeof *f);
    f->ViewID = view_id;
    printf("  fecar init view %d ride %d\n", (int)view_id, ride != NULL);
}

void fecar_reinit(FrontEndRenderingCar *f, RideInfo *ride)
{
    char t[64];
    ride_text(t, ride);
    printf("  reinit %s view %d ride %s\n", f->Reflection ? "refl" : "car",
           (int)f->ViewID, t);
}

void fecar_delete(FrontEndRenderingCar *f, int32_t flags)
{
    (void)flags;
    printf("  fecar delete %s view %d model %d\n",
           f->Reflection ? "refl" : "car", (int)f->ViewID, f->pModel != NULL);
}

void selcam_init(SelectCarCameraMover *o, int viewID)
{
    memset(o, 0, sizeof *o);
    printf("  cam init view %d\n", viewID);
}

void selcam_destroy(SelectCarCameraMover *o)
{
    (void)o;
    printf("  cam delete\n");
}

void selcam_set_mode(SelectCarCameraMover *o, int32_t mode)
{
    (void)o;
    printf("  cam mode %d\n", (int)mode);
}

void selcam_set_radius_stats(SelectCarCameraMover *o, float r)
{
    o->RadiusStats = r;
}

void selcam_set_offset_stats(SelectCarCameraMover *o, const bVector3 *v)
{
    o->OffsetStats.x = v->x;
    o->OffsetStats.y = v->y;
    o->OffsetStats.z = v->z;
}

void selcam_set_offset_orbit(SelectCarCameraMover *o, const bVector3 *v)
{
    o->OffsetOrbit.x = v->x;
    o->OffsetOrbit.y = v->y;
    o->OffsetOrbit.z = v->z;
}

void selcam_set_fov_stats(SelectCarCameraMover *o, uint16_t fov)
{
    o->FOVStats = fov;
}

void selcam_set_orientation_stats(SelectCarCameraMover *o, uint16_t angle,
                                  uint16_t tilt)
{
    o->AngleZ = angle;
    o->TiltStats = tilt;
}

void emodel_init(eModel *m, uint32_t name_hash)
{
    m->NameHash = name_hash;
    m->Solid = (void *)(uintptr_t)solidNext;
    printf("  model init %08x\n", (unsigned)name_hash);
}

void emodel_uninit(eModel *m)
{
    printf("  model uninit %08x\n", (unsigned)m->NameHash);
    m->Solid = NULL;
}

void emodel_delete(eModel *m, int32_t flags)
{
    (void)flags;
    printf("  model delete %08x\n", (unsigned)m->NameHash);
}

static void h_render(eModel *m, bMatrix4 *matrix, void *light,
                     uint32_t flags)
{
    char text[160];
    hex_bytes(text, (const uint8_t *)matrix, 64);
    printf("  model render %08x at %ld light %d flags %u matrix %s\n",
           (unsigned)m->NameHash, (long)((uint8_t *)matrix - frameBase),
           light != NULL, (unsigned)flags, text);
}

void el_set_select_car_lighting(int32_t view_id, int32_t locked,
                                float bright)
{
    printf("  light %d %d %08x\n", (int)view_id, (int)locked,
           (unsigned)fbits(bright));
}

// The nebula's: the emitters' pool, its count and FrameEffects are the
// harness's, each slot from a table with its bytes 0xa5. SetEmitterData,
// AddAutoEmitter, RemoveAutoEmitter, the emitter's delete and
// KillAllActiveEffects are stubbed, here as in the model, and name an
// emitter by the order the pool gave it. SetEmitterData answers with one
// data for all, as the script's `neb` says: 0 none, 1 every emitter, 2
// all but every third.
#define MAX_EMITTERS 1024

BSlotPool       *AcidEmitterSlotPool;
int32_t          NumAcidEmitters;
AcidEffectSystem FrameEffects;
static AcidEmitter     emitterSlots[MAX_EMITTERS];
static int             numEmitterSlots;
static AcidEmitterData nebulaData;
static int             nebulaMode = 1;

static int emitter_id(const AcidEmitter *e)
{
    if (e >= emitterSlots && e < emitterSlots + numEmitterSlots)
        return (int)(e - emitterSlots);
    return -1;
}

static const char *system_name(const AcidEffectSystem *s)
{
    return s == &FrameEffects ? "frame" : "stray";
}

void *bSlotOMalloc(BSlotPool *pool)
{
    AcidEmitter *e;

    if (pool != AcidEmitterSlotPool || numEmitterSlots == MAX_EMITTERS) {
        printf("  stray omalloc\n");
        exit(2);
    }
    e = &emitterSlots[numEmitterSlots++];
    memset(e, 0xa5, sizeof *e);
    return e;
}

int32_t acid_emitter_set_emitter_data_hash(AcidEmitter *e, uint32_t hash)
{
    int id = emitter_id(e);
    int found = nebulaMode == 1 || (nebulaMode == 2 && id % 3 != 0);

    printf("  acid data e%d %08x %d\n", id, (unsigned)hash, found);
    if (!found) return 0;
    e->EmitterData = &nebulaData;
    return 1;
}

void acid_system_add_auto_emitter(AcidEffectSystem *s, AcidEmitter *e)
{
    printf("  acid add %s e%d state %d\n", system_name(s), emitter_id(e),
           (int)e->State);
}

void acid_system_remove_auto_emitter(AcidEffectSystem *s, AcidEmitter *e)
{
    printf("  acid remove %s e%d\n", system_name(s), emitter_id(e));
}

void acid_emitter_delete(AcidEmitter *e, int32_t flags)
{
    printf("  acid delete e%d %d\n", emitter_id(e), (int)flags);
}

void acid_system_kill_all_active_effects(AcidEffectSystem *s)
{
    printf("  acid kill %s\n", system_name(s));
}

// A swatch: its fourth texel the hash's bits 4..6, a palette of eight
// colours from the hash's three high bytes.
TextureInfo *GetTextureInfo(uint32_t hash, int use_default,
                            int include_unloaded)
{
    static TextureInfo ti;
    static uint8_t     image[4], palette[32];

    (void)include_unloaded;
    printf("  tex %08x %d\n", (unsigned)hash, use_default);
    if (texMode == 0) return NULL;
    memset(&ti, 0, sizeof ti);
    image[3] = (uint8_t)((hash >> 4) & 7);
    for (int k = 0; k < 8; k++) {
        palette[4 * k] = (uint8_t)((hash >> 8) + 37u * (uint32_t)k);
        palette[4 * k + 1] = (uint8_t)((hash >> 16) + 59u * (uint32_t)k);
        palette[4 * k + 2] = (uint8_t)((hash >> 24) + 83u * (uint32_t)k);
        palette[4 * k + 3] = 0x80;
    }
    ti.ImageData = texMode == 2 ? NULL : image;
    ti.PaletteSize = texMode == 3 ? 0 : 32;
    ti.PaletteData = texMode == 4 ? NULL : palette;
    return &ti;
}

// ------------------------------------------------------- Flailer's seams

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

// ------------------------------------------------------------ the world

static BUI      loads[MAX_LOADS];
static uint8_t *bufs[MAX_LOADS];
static int      numLoads;
static BCarSel  module;

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

// ------------------------------------------------------------- the dump

typedef struct Line {
    char *key;
    char *text;
} Line;

static Line  *lines;
static size_t numLines, capLines;

static char *dup(const char *s)
{
    size_t n = strlen(s) + 1;
    return (char *)memcpy(malloc(n), s, n);
}

// The keys come in the same order each dump, so the search starts after the
// last one found.
static void note(const char *key, const char *text)
{
    static size_t hint;
    for (size_t k = 0; k < numLines; k++) {
        size_t i = (hint + k) % numLines;
        if (strcmp(lines[i].key, key) != 0) continue;
        hint = i + 1;
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
                ((uint8_t *)(uintptr_t)p)[43] = 0;
            }
        }
    }
}

static int car_type(const VisibleCar *c)
{
    return c ? (int)c->type : -1;
}

// A car's status as player.type.
static void status_name(char *out, const CarStatus *st)
{
    for (int p = 0; p < 2; p++) {
        const CarStatus *a = Fred.FrontendPlayers[p].aCarStatus;
        if (st >= a && st < a + NUM_CARS) {
            sprintf(out, "%d.%d", p, (int)(st - a));
            return;
        }
    }
    strcpy(out, "stray");
}

// A rendering car: its flags, model, lights, place and body on one line,
// its wheels' matrices on another.
static void dump_fecar(const char *key, const CarSelector *c,
                       const FrontEndRenderingCar *f)
{
    static char text[2048];
    char        k[16];
    char       *o = text;

    o += sprintf(o, "en %d refl %d model %s lights %d %d pos %08x %08x %08x ",
                 (int)f->Enabled, (int)f->Reflection,
                 !f->pModel                ? "0"
                 : f->pModel == &c->cover ? "cover"
                                           : "stray",
                 (int)f->Headlights, (int)f->CopLights,
                 (unsigned)fbits(f->Position.x), (unsigned)fbits(f->Position.y),
                 (unsigned)fbits(f->Position.z));
    hex_bytes(o, (const uint8_t *)&f->BodyMatrix, 64);
    note(key, text);
    snprintf(k, sizeof k, "%sw", key);
    hex_bytes(text, (const uint8_t *)f->TireMatrices, 256);
    hex_bytes(text + 512, (const uint8_t *)f->BrakeMatrices, 256);
    note(k, text);
}

static void dump_selector(int i, const CarSelector *c)
{
    static char text[8192];
    char        key[16], *o;
    const bNode *n;

    snprintf(key, sizeof key, "sel%d", i);
    snprintf(text, sizeof text,
             "port %d 2p %d player %d screen %08x fade %d/%d all %d "
             "loaded %d pending %d modes %08x %08x %08x %08x orbit %d %d "
             "state %d popup %d trans %d hand %d turn %d %d %d sw %d",
             (int)c->port, (int)c->twoPlayer, (int)c->playerNum,
             (unsigned)c->screen, (int)c->fade, (int)c->fadeMax,
             (int)c->allUnlocked, car_type(c->loaded), car_type(c->pending),
             (unsigned)fbits(c->chooseMode), (unsigned)fbits(c->orbitMode),
             (unsigned)fbits(c->shownMode), (unsigned)fbits(c->mode),
             (int)c->orbitFrame, (int)c->orbitTouched, (int)c->state,
             (int)c->popup, (int)c->transmission, (int)c->handling,
             (int)c->turnTilt, (int)c->turnFOV, (int)c->turnAngle,
             (int)c->nSwatches);
    note(key, text);

    snprintf(key, sizeof key, "set%d", i);
    o = text;
    o += sprintf(o, "cur %d total %d unl %d list", car_type(c->set.current),
                 (int)c->set.total, (int)c->set.unlocked);
    for (n = c->set.list.next; n != &c->set.list; n = n->next) {
        const VisibleCar *v = (const VisibleCar *)(const void *)n;
        char              st[16];
        status_name(st, v->status);
        o += sprintf(o, " %d:%d:%d:%d:%08x:%s", (int)v->type,
                     (int)v->available, (int)v->skinIndex, (int)v->carIndex,
                     (unsigned)v->thumbHash, st);
    }
    note(key, text);

    snprintf(key, sizeof key, "unl%d", i);
    o = text;
    o += sprintf(o, "car %d screen %08x x %08x alpha %d start %d state %d "
                 "hide %d slide %08x %08x %08x %d %d ",
                 car_type(c->unlock.car), (unsigned)c->unlock.screen,
                 (unsigned)fbits(c->unlock.x), (int)c->unlock.alpha,
                 (int)c->unlock.start, (int)c->unlock.state,
                 (int)c->unlock.hide, (unsigned)c->unlock.slide.screen,
                 (unsigned)c->unlock.slide.group,
                 (unsigned)c->unlock.slide.master,
                 (int)c->unlock.slide.savedX, (int)c->unlock.slide.savedY);
    hex(o, (const uint8_t *)&c->unlock.slide.spline, 0, 48);
    o += strlen(o);
    sprintf(o, " \"%s\"", c->unlock.blurb);
    note(key, text);

    snprintf(key, sizeof key, "thumbs%d", i);
    hex(text, (const uint8_t *)&c->thumbs, 0, 48);
    note(key, text);

    snprintf(key, sizeof key, "neb%d", i);
    o = text;
    o += sprintf(o, "n %d shade %08x", (int)c->nNebula,
                 (unsigned)fbits(c->nebulaLocked));
    for (int k = 0; k < c->nNebula && k < BCARSEL_MAX_NEBULA; k++)
        o += sprintf(o, " e%d", emitter_id(c->nebula[k]));
    note(key, text);
    for (int k = 0; k < c->nNebula && k < BCARSEL_MAX_NEBULA; k++) {
        const AcidEmitter *e = c->nebula[k];
        if (!e) continue;
        snprintf(key, sizeof key, "neb%d.%d", i, k);
        o = text;
        o += sprintf(o, "hash %08x %08x state %d rem %08x cd %08x data %s "
                     "last %d seed %08x dont %08x pad %08x world ",
                     (unsigned)e->NameHash, (unsigned)e->EmitterDataNameHash,
                     (int)e->State, (unsigned)fbits(e->RemainingCycleTime),
                     (unsigned)fbits(e->EmissionCountdown),
                     !e->EmitterData ? "0"
                     : e->EmitterData == &nebulaData ? "neb" : "stray",
                     e->LastActiveGroup != NULL, (unsigned)e->RandomSeed,
                     (unsigned)e->DontEmit, (unsigned)e->pad2);
        hex(o, (const uint8_t *)&e->LocalWorld, 0, 64);
        o += strlen(o);
        o += sprintf(o, " inherit ");
        hex(o, (const uint8_t *)&e->InheritVelocity, 0, 16);
        o += strlen(o);
        o += sprintf(o, " name ");
        hex(o, (const uint8_t *)e->Name, 0, 64);
        note(key, text);
    }

    snprintf(key, sizeof key, "swatch%d", i);
    o = text;
    *o = 0;
    for (int k = 0; k < BCARSEL_MAX_SWATCHES; k++)
        o += sprintf(o, "%s%08x:%08x", k ? " " : "",
                     (unsigned)c->swatchHash[k], (unsigned)c->swatchColour[k]);
    note(key, text);

    snprintf(key, sizeof key, "fe%d", i);
    dump_fecar(key, c, &c->car);
    snprintf(key, sizeof key, "fr%d", i);
    dump_fecar(key, c, &c->reflection);

    snprintf(key, sizeof key, "cam%d", i);
    {
        const SelectCarCameraMover *m = &c->mover;
        snprintf(text, sizeof text,
                 "blend %08x angle %d tilt %d radius %08x off %08x %08x %08x "
                 "orbit %08x %08x %08x fov %d desired %08x %08x",
                 (unsigned)fbits(m->Blend), (int)m->AngleZ, (int)m->TiltStats,
                 (unsigned)fbits(m->RadiusStats),
                 (unsigned)fbits(m->OffsetStats.x),
                 (unsigned)fbits(m->OffsetStats.y),
                 (unsigned)fbits(m->OffsetStats.z),
                 (unsigned)fbits(m->OffsetOrbit.x),
                 (unsigned)fbits(m->OffsetOrbit.y),
                 (unsigned)fbits(m->OffsetOrbit.z), (int)m->FOVStats,
                 (unsigned)fbits(m->DesiredHorizSpeed),
                 (unsigned)fbits(m->DesiredVertSpeed));
    }
    note(key, text);
}

static void dump(void)
{
    char             text[256];
    SelectCarScreen *p = module.screen;

    if (p) {
        snprintf(text, sizeof text, "present 1 count %d sel %d %d",
                 (int)p->count, p->selectors[0] != NULL,
                 p->selectors[1] != NULL);
        note("scr", text);
        for (int i = 0; i < BCARSEL_MAX_SELECTORS; i++)
            if (p->selectors[i]) dump_selector(i, p->selectors[i]);
    } else {
        note("scr", "present 0");
    }
    snprintf(text, sizeof text, "%d %d", (int)module.preloaded[0],
             (int)module.preloaded[1]);
    note("pre", text);
    snprintf(text, sizeof text, "%d %d", (int)loaderFlags[0],
             (int)loaderFlags[1]);
    note("carloader", text);
    snprintf(text, sizeof text, "used %ld failed %d amount %u",
             (long)(CurrentBufferPos - frameBase), (int)FrameMallocFailed,
             (unsigned)FrameMallocFailAmount);
    note("frame", text);
    {
        char acid[200], *o = acid;
        o += sprintf(o, "emitters %d colour ", (int)NumAcidEmitters);
        hex(o, (const uint8_t *)&nebulaData.ColourMatrix, 0, 64);
        note("acid", acid);
    }
    for (int i = 0; i < 2; i++) {
        char key[8];
        snprintf(key, sizeof key, "pl%d", i);
        snprintf(text, sizeof text, "trans %d style %d",
                 (int)Fred.FrontendPlayers[i].mPlayerSettings.TransmissionType,
                 (int)Fred.FrontendPlayers[i].mPlayerSettings.DrivingStyle);
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

static void set_global(const char *k, const char *v)
{
    if (!strcmp(k, "gametype")) Fred.GameType = inum(v);
    else if (!strcmp(k, "players")) Fred.NumPlayerCars = inum(v);
    else if (!strcmp(k, "units")) Fred.DisplayOptionsData.Units = (int8_t)inum(v);
    else if (!strcmp(k, "lang")) language = inum(v);
    else if (!strcmp(k, "sound")) soundOn = inum(v);
    else if (!strcmp(k, "allcars")) AllCarsAvailableInCarSelectScreen = inum(v);
    else if (!strcmp(k, "rtimer")) RealTimer = inum(v);
    else if (!strcmp(k, "rframes")) RealTimeFrames = inum(v);
    else if (!strcmp(k, "relapsed")) RealTimeElapsed = fnum(v);
    else if (!strcmp(k, "help")) helpActive = inum(v);
    else if (!strcmp(k, "pi")) nextPopup = inum(v);
    else {
        printf("  no global %s\n", k);
        exit(2);
    }
}

static void run(char *line)
{
    char *a[NUM_ARGS];
    int   n = 0;
    char *s = line;

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
    if (!strcmp(a[0], "cars")) {
        load_cars(a[1]);
        return;
    }
    if (!strcmp(a[0], "spec")) {
        int       t = inum(a[1]);
        CarSpecs *c = &specs[t];
        c->CarType = t;
        c->ZeroTo60 = inum(a[2]);
        c->TopSpeedMph = inum(a[3]);
        c->TopSpeedKph = inum(a[4]);
        c->BHP = inum(a[5]);
        c->FullName = inum(a[6]);
        c->ShortName = inum(a[7]);
        hostcars[t].pCarSpecs = c;
        return;
    }
    if (!strcmp(a[0], "cr")) {
        put_le(cars + CAR_REC * inum(a[1]) + inum(a[2]), inum(a[3]), num(a[4]));
        sync_cars();
        return;
    }
    if (!strcmp(a[0], "sk")) {
        put_le(skinchunk + 8 + 64 * inum(a[1]) + inum(a[2]), inum(a[3]),
               num(a[4]));
        return;
    }
    if (!strcmp(a[0], "g")) set_global(a[1], a[2]);
    else if (!strcmp(a[0], "fs")) {
        CarStatus *st = &Fred.FrontendPlayers[inum(a[1])].aCarStatus[inum(a[2])];
        char      *b = a[5];
        int        k = 0;
        st->nStatus = inum(a[3]);
        st->nSkins = inum(a[4]);
        memset(st->aSkins, 0, sizeof st->aSkins);
        while (*b && k < FRED_MAX_SKINS) {
            st->aSkins[k++] = (uint8_t)strtoul(b, &b, 0);
            if (*b == ',') b++;
        }
        st->bDashAvailable = inum(a[6]);
    } else if (!strcmp(a[0], "ride")) {
        RideInfo *r =
            &Fred.FrontendPlayers[inum(a[1])].RideInfoByGameMode[inum(a[2])];
        r->Type = inum(a[3]);
        r->SkinNumber = (int8_t)inum(a[4]);
    } else if (!strcmp(a[0], "pts"))
        Fred.FrontendPlayers[inum(a[1])].AccumulatedPoints = inum(a[2]);
    else if (!strcmp(a[0], "xl")) {
        int32_t id = inum(a[1]);
        int     i;
        for (i = 0; i < numXl && xl[i].id != id; i++)
            ;
        if (i == numXl) numXl++;
        xl[i].id = id;
        snprintf(xl[i].text, sizeof xl[i].text, "%s", a[2]);
    } else if (!strcmp(a[0], "egg")) eggs[inum(a[1])] = inum(a[2]);
    else if (!strcmp(a[0], "ev")) {
        evTree[inum(a[1])] = inum(a[2]);
        evNum[inum(a[1])] = inum(a[3]);
    } else if (!strcmp(a[0], "isl")) loadedAns[inum(a[1])] = inum(a[2]);
    else if (!strcmp(a[0], "msg")) {
        BScreenCallbackData d;
        d.itemHash = num(a[2]);
        d.port = inum(a[3]);
        d.param = inum(a[4]);
        d.noise = inum(a[5]);
        bcarsel_screen_callback(NULL, (BScreenMessage)inum(a[1]), &d);
        printf("  data %d %d\n", (int)d.param, (int)d.noise);
    } else if (!strcmp(a[0], "joy")) {
        int p = inum(a[1]), ev = inum(a[2]);
        if (joys[p][ev].fn)
            joys[p][ev].fn(p, ev, (uint8_t)num(a[3]), joys[p][ev].obj);
        else
            printf("  joy none\n");
    } else if (!strcmp(a[0], "tex")) texMode = inum(a[1]);
    else if (!strcmp(a[0], "neb")) nebulaMode = inum(a[1]);
    else if (!strcmp(a[0], "solid")) solidNext = num(a[1]);
    else if (!strcmp(a[0], "blend"))
        module.screen->selectors[inum(a[1])]->mover.Blend = fnum(a[2]);
    else if (!strcmp(a[0], "frame")) {
        uint32_t size = num(a[1]);
        free(frameBase);
        frameBase = size ? (uint8_t *)calloc(size, 1) : NULL;
        CurrentBufferPos = frameBase;
        CurrentBufferEnd = frameBase ? frameBase + size : NULL;
        FrameMallocFailed = 0;
        FrameMallocFailAmount = 0;
    } else if (!strcmp(a[0], "preload")) bcarsel_preload();
    else if (!strcmp(a[0], "close")) bcarsel_close_screen();
    else {
        printf("  no op %s\n", a[0]);
        exit(2);
    }
    // The set-up ops change nothing until the next action shows it.
    if (!strcmp(a[0], "msg") || !strcmp(a[0], "joy")
        || !strcmp(a[0], "preload") || !strcmp(a[0], "close"))
        dump();
}

int main(int argc, char **argv)
{
    static char  line[1 << 16];
    FILE        *f;
    BCarSelHooks h;

    if (argc < 2) return 2;
    f = fopen(argv[1], "r");
    if (!f) return 2;

    gFlailerTextScaledWidthFn = text_w;
    gFlailerTextScaledHeightFn = text_h;
    gFlailerBitmapTextureSizeFn = texture_size;
    gEModelRenderFn = h_render;

    for (int i = 0; i < NUM_CARS; i++) {
        loadedAns[i] = 1;
        evTree[i] = -1;
    }
    memset(&nebulaData, 0xa5, sizeof nebulaData);

    memset(&h, 0, sizeof h);
    h.translate = h_translate;
    h.translateString = h_translate_string;
    h.sound = h_sound;
    h.stopSound = h_stop_sound;
    h.setHelpOverride = h_help;
    h.helpMenuActive = h_help_active;
    h.summonPopup = h_summon;
    h.dismissPopup = h_dismiss;
    h.changeToScreen = h_change;
    h.startRace = h_start_race;
    h.loaderFrontEnd = h_loader_front_end;
    h.loaderLoad = h_load;
    h.loaderIsLoaded = h_is_loaded;
    h.loaderUnload = h_unload;
    h.loaderBeginLoading = h_begin;
    h.eggActive = h_egg;
    h.formatUnlockBlurb = h_blurb;
    h.renderTextIntoRectangle = h_rtext;
    h.speakCar = h_speak;
    h.speechFade = h_fade;
    h.soundEnabled = h_sound_enabled;
    h.language = h_language;
    h.setPerPortJoy = h_per_port;
    h.stopMovie = h_stop_movie;
    bcarsel_init(&module, &h);

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
