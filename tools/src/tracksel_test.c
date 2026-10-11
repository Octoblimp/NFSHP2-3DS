// Drives btracksel.c for tools/tracksel_check.py: track select's screen
// callback over flailer.c with FRONTB's screens loaded and GLOBALB's track
// table. A script of ops, one per line, fields split on '|'; numbers are C
// literals, floats their bits:
//
//   load|PATH              a bundle: bui_open, then flailer_add_project
//   tracks|PATH            GLOBALB: the track table (0x34201), track 54
//                          cleared as the loader does
//   g|NAME|V               gametype, players, units, lang, opts (Fred's
//                          MainMenuOpts[0]), rtimer, relapsed, active
//                          (GetActiveMenuItem's answer), tex (GetTexture's
//                          rule: 0 none, 1 all, 2 odd hashes), seed
//                          (bDefaultSeed), solid, rpnp, rpnai
//   data|A|B|C|D           Fred's SelectTrackScreenData
//   cls|P|V                player P's selected car class
//   unl|T|D|V              IsTrackUnlocked's answer for track T, way D
//   egg|T|D|V              the easter eggs' answer
//   ev|T|D|TREE|NUM        track T, way D an event's reward (TREE -1: none)
//   lap|T|C|D|TIME|NAME    the best lap record for track, class and way
//   tot|T|C|D|L|TIME|NAME  the best total over L laps
//   xl|ID|TEXT             GetTranslatedString's answer for ID
//   msg|MSG|ITEM|PORT|PARAM|NOISE   TrackSelectScreenCallback
//   texloaded              the slideshow's load finishes: its callback
//   frame|SIZE             a fresh frame-malloc buffer of SIZE bytes
//
// After each msg and texloaded every line that changed: the screen, its
// splines, the track list with each track's times of day and model, the
// camera, the slideshow, the time-of-day menu, the records, the locked
// box, the model's angle, Fred's data, the race parameters, the frame
// buffer and every Flailer object's bytes. The hooks and the seams log
// their calls in the model's stubs' words.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "btracksel.h"
#include "bui.h"
#include "eframe.h"
#include "emodel.h"
#include "flailer.h"
#include "fred.h"
#include "fredrace.h"
#include "highscore.h"
#include "nfsrewards.h"
#include "race.h"
#include "realtime.h"
#include "scenerycull.h"
#include "stillcam.h"
#include "timer.h"
#include "track.h"

#define MAX_LOADS  4
#define NUM_ARGS   48
#define MAX_XL     256
#define NUM_TRACKS 70

// ------------------------------------------------------------ the globals

FrontendDatabase Fred;
RaceParameters   TheRaceParameters;
int32_t          RealTimer;
int32_t          RealTime;
int32_t          RealTimeFrames;
float            RealTimeElapsed;

// track.c's, which pulls in the world.
TrackInfo *TrackInfoTable;
int32_t    HighestTrackNumber;

TrackInfo *track_get_info(int i)
{
    TrackInfo *p;
    if (i <= 0 || HighestTrackNumber < i) return NULL;
    p = TrackInfoTable + (i - 1);
    return p->Name[0] != 0 ? p : NULL;
}

static uint8_t *trackChunk;

static void load_tracks(const char *path)
{
    FILE    *f = fopen(path, "rb");
    long     len, off = 0;
    uint8_t *d;

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
        if (id == 0x34201 && !trackChunk) {
            TrackInfo *hidden;
            trackChunk = (uint8_t *)malloc(size);
            memcpy(trackChunk, d + off + 8, size);
            TrackInfoTable = (TrackInfo *)(void *)trackChunk;
            HighestTrackNumber = (int32_t)(size / (uint32_t)sizeof(TrackInfo));
            hidden = track_get_info(54);
            if (hidden) memset(hidden, 0, sizeof *hidden);
        }
        off += 8 + (long)size;
    }
    free(d);
    printf("  tracks %d\n", (int)HighestTrackNumber);
}

static int ti_index(const TrackInfo *ti)
{
    return ti ? (int)(ti - TrackInfoTable) + 1 : 0;
}

// ------------------------------------------------------------ the seams

static struct {
    int32_t id;
    char    text[128];
} xl[MAX_XL];
static int numXl;

static int32_t language, activeItem, texMode = 1;
static int32_t carClass[2];
static int8_t  unlockedAns[NUM_TRACKS][2], eggAns[NUM_TRACKS][2];
static int32_t evTree[NUM_TRACKS][2], evNum[NUM_TRACKS][2];
static uint32_t solidNext = 1;

static FredHighScore lapRec[NUM_TRACKS][8][2];
static FredHighScore totRec[NUM_TRACKS][8][2][4];

static int lapsIndex(int32_t laps)
{
    return laps == 1 ? 0 : laps == 2 ? 1 : laps == 4 ? 2 : 3;
}

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

static uint32_t fbits(float f)
{
    uint32_t v;
    memcpy(&v, &f, 4);
    return v;
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

int32_t fpi_get_selected_car_class(FrontendPlayerInfo *p)
{
    int i = (int)(p - Fred.FrontendPlayers);
    int32_t v = i >= 0 && i < 2 ? carClass[i] : 0;
    printf("  class %d -> %d\n", i, (int)v);
    return v;
}

FredHighScore *fred_get_best_lap_times_table(FrontendDatabase *f,
                                             int32_t track,
                                             int32_t carClass_,
                                             int32_t direction)
{
    (void)f;
    printf("  laptable %d %d %d\n", (int)track, (int)carClass_,
           (int)direction);
    return &lapRec[track % NUM_TRACKS][carClass_ & 7][direction & 1];
}

FredHighScore *fred_get_best_total_times_table(FrontendDatabase *f,
                                               int32_t track,
                                               int32_t carClass_,
                                               int32_t direction,
                                               int32_t laps)
{
    (void)f;
    printf("  tottable %d %d %d %d\n", (int)track, (int)carClass_,
           (int)direction, (int)laps);
    return &totRec[track % NUM_TRACKS][carClass_ & 7][direction & 1]
                  [lapsIndex(laps)];
}

const char *fred_lookup_player_name_from_table(FrontendDatabase *f, int32_t i)
{
    static char names[128][8];
    (void)f;
    printf("  name %d\n", (int)i);
    if (i < 0 || i >= 128) return NULL;
    snprintf(names[i], sizeof names[i], "P%d", (int)i);
    return names[i];
}

void timer_print_to_string(const Timer *t, char *buf, int32_t flags,
                           int32_t language_)
{
    (void)language_;
    printf("  print %u %d\n", (unsigned)t->PackedTime, (int)flags);
    sprintf(buf, "T%u", (unsigned)t->PackedTime);
}

// The 3D: the camera and the models are stubbed, here as in the model.
uint8_t *CurrentBufferPos;
uint8_t *CurrentBufferEnd;
int32_t  FrameMallocFailed;
uint32_t FrameMallocFailAmount;
static uint8_t *frameBase;

void (*gEModelRenderFn)(eModel *m, bMatrix4 *matrix, void *light,
                        uint32_t flags);

StillCameraMover *still_camera_mover_init(StillCameraMover *m, int viewID)
{
    memset(m, 0, sizeof *m);
    printf("  cam init view %d\n", viewID);
    return m;
}

void still_camera_mover_destroy(StillCameraMover *m)
{
    (void)m;
    printf("  cam delete\n");
}

void emodel_init(eModel *m, uint32_t name_hash)
{
    m->NameHash = name_hash;
    m->Solid = (void *)(uintptr_t)solidNext;
    printf("  model init %08x\n", (unsigned)name_hash);
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
    hex(text, (const uint8_t *)matrix, 0, 64);
    printf("  model render %08x at %ld light %d flags %u matrix %s\n",
           (unsigned)m->NameHash, (long)((uint8_t *)matrix - frameBase),
           light != NULL, (unsigned)flags, text);
}

// ------------------------------------------------------------ the hooks

static const char *h_translate(void *u, int32_t id)
{
    (void)u;
    return seam_xl(id);
}

static void h_fade(void *u, float level)
{
    (void)u;
    printf("  fade %08x\n", (unsigned)fbits(level));
}

static void h_speak(void *u, int32_t track)
{
    (void)u;
    printf("  speak 155 1 %d\n", (int)track);
}

static int h_egg(void *u, int32_t track, int32_t dir)
{
    int v = track >= 0 && track < NUM_TRACKS ? eggAns[track][dir & 1] : 0;
    (void)u;
    printf("  egg? %d %d -> %d\n", (int)track, (int)dir, v);
    return v;
}

static int h_unlocked(void *u, int32_t track, int32_t dir)
{
    int v = track >= 0 && track < NUM_TRACKS ? unlockedAns[track][dir & 1]
                                             : 1;
    (void)u;
    printf("  unlocked? %d %d -> %d\n", (int)track, (int)dir, v);
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

static int r_find_event(void *u, int32_t track, int32_t dir, int32_t *tree,
                        int32_t *num)
{
    int v = track >= 0 && track < NUM_TRACKS && evTree[track][dir & 1] != -1;
    (void)u;
    printf("  event? %d %d -> %d\n", (int)track, (int)dir, v);
    if (v) {
        *tree = evTree[track][dir & 1];
        *num = evNum[track][dir & 1];
    }
    return v;
}

static const NFSRewardHooks rewardHooks = {
    NULL, r_translate, r_language, NULL, r_find_event,
};

static void h_blurb(void *u, char *buf, int len, int32_t track, int32_t dir)
{
    (void)u;
    nfs_format_unlock_blurb_for_track(&rewardHooks, buf, len, track, dir);
}

static void h_rtext(void *u, uint32_t screen, uint32_t obj, uint32_t rect,
                    const char *text, float scale)
{
    (void)u;
    printf("  rtext %08x %08x %08x \"%s\" %08x\n", (unsigned)screen,
           (unsigned)obj, (unsigned)rect, text, (unsigned)fbits(scale));
}

static void h_set_active(void *u, uint32_t item)
{
    (void)u;
    printf("  setactive %08x\n", (unsigned)item);
}

static uint32_t h_get_active(void *u)
{
    (void)u;
    printf("  getactive -> %08x\n", (unsigned)activeItem);
    return (uint32_t)activeItem;
}

static int  packDummy;
static void (*loadCb)(intptr_t);
static intptr_t loadParam;

static void *h_pack_new(void *u)
{
    (void)u;
    printf("  pack new TrackSelect\n");
    printf("  pack table FRONTEND\\TSELECT.BIN\n");
    return &packDummy;
}

static void h_pack_delete(void *u, void *pack)
{
    (void)u;
    (void)pack;
    printf("  pack delete\n");
}

static void h_pack_unload(void *u, void *pack)
{
    (void)u;
    printf("  pack unload %d\n", pack != NULL);
}

static int h_pack_has(void *u, void *pack, uint32_t hash)
{
    int v = texMode == 1 || (texMode == 2 && (hash & 1));
    (void)u;
    (void)pack;
    printf("  pack has %08x -> %d\n", (unsigned)hash, v);
    return v;
}

static void h_pack_load(void *u, void *pack, uint32_t hash,
                        void (*cb)(intptr_t), intptr_t param)
{
    (void)u;
    (void)pack;
    printf("  pack load %08x\n", (unsigned)hash);
    loadCb = cb;
    loadParam = param;
}

static void h_hl_init(void *u, BHighlightAnim *hl, uint32_t screen,
                      uint32_t object, int32_t color)
{
    (void)u;
    (void)hl;
    printf("  hl_init %08x %08x %x\n", (unsigned)screen, (unsigned)object,
           (unsigned)color);
}

static void h_hl_item(void *u, BHighlightAnim *hl, uint32_t item)
{
    (void)u;
    (void)hl;
    printf("  hl_item %08x\n", (unsigned)item);
}

static void h_hl_anim(void *u, BHighlightAnim *hl)
{
    (void)u;
    (void)hl;
    printf("  hl_anim\n");
}

static int32_t h_language(void *u)
{
    (void)u;
    return language;
}

static void h_start_race(void *u)
{
    (void)u;
    printf("  startrace\n");
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
static BTrackSel module;

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

// An object pointer as load:index, as the model names it.
static void obj_name(char *out, const void *ptr)
{
    if (!ptr) {
        strcpy(out, "none");
        return;
    }
    for (int l = 0; l < numLoads; l++) {
        BUI *ui = &loads[l];
        for (uint32_t s = 0; s < ui->numScreens; s++) {
            const BUIScreen *sc = &ui->screens[s];
            for (uint32_t i = 0; i < sc->count; i++)
                if (ui->objects[sc->first + i].payload == ptr) {
                    sprintf(out, "%d:%u", l, sc->first + i);
                    return;
                }
        }
    }
    strcpy(out, "stray");
}

static int track_idx(const SelectTrackScreen *p, const BTrackSelTrack *t)
{
    return t ? (int)(t - p->mgr.tracks) : -1;
}

static void dump_screen(const SelectTrackScreen *p)
{
    static char text[8192];
    char        key[16], *o, bm[6][24];

    for (int i = 0; i < 6; i++) obj_name(bm[i], p->bitmaps[i]);
    snprintf(text, sizeof text,
             "present 1 normal %d data %d %d %d %d screen %08x speaking %d "
             "bm %s %s %s %s %s %s phase %08x",
             (int)p->normal, (int)p->data[0], (int)p->data[1],
             (int)p->data[2], (int)p->data[3], (unsigned)p->screen,
             (int)p->speaking, bm[0], bm[1], bm[2], bm[3], bm[4], bm[5],
             (unsigned)fbits(p->phase));
    note("scr", text);

    hex(text, (const uint8_t *)&p->x, 0, 48);
    hex(text + 96, (const uint8_t *)&p->y, 0, 48);
    note("splines", text);

    snprintf(text, sizeof text, "n %d cur %d spacing %08x",
             (int)p->mgr.count, (int)p->mgr.cur,
             (unsigned)fbits(p->mgr.spacing));
    note("mgr", text);
    for (int i = 0; i < p->mgr.count; i++) {
        const BTrackSelTrack *t = &p->mgr.tracks[i];
        snprintf(key, sizeof key, "trk%d", i);
        o = text;
        o += sprintf(o, "vis %d dir %d thumb %08x x %08x cur %d ti %d "
                     "height %08x model %08x %d tods",
                     (int)t->vis, (int)t->dir, (unsigned)t->thumb,
                     (unsigned)fbits(t->x), (int)t->curTOD, ti_index(t->ti),
                     (unsigned)fbits(t->height), (unsigned)t->model.NameHash,
                     t->model.Solid != NULL);
        for (int k = 0; k < t->nTOD; k++)
            o += sprintf(o, " %d:%08x", ti_index(t->tod[k].ti),
                         (unsigned)fbits(t->tod[k].offset));
        note(key, text);
    }

    if (p->haveMover) {
        o = text;
        o += sprintf(o, "eye ");
        hex(o, (const uint8_t *)&p->mover.Eye, 0, 12);
        o += strlen(o);
        o += sprintf(o, " look ");
        hex(o, (const uint8_t *)&p->mover.Look, 0, 12);
        note("cam", text);
    }

    snprintf(text, sizeof text,
             "screen %08x pack %d track %d t0 %d t1 %d tex %08x loaded %d "
             "state %d",
             (unsigned)p->show.screen, p->show.pack != NULL,
             track_idx(p, p->show.track), (int)p->show.t0, (int)p->show.t1,
             (unsigned)p->show.tex, (int)p->show.loaded, (int)p->show.state);
    note("show", text);

    snprintf(text, sizeof text, "screen %08x track %d",
             (unsigned)p->todMenu.screen, track_idx(p, p->todMenu.track));
    note("todm", text);

    o = text;
    o += sprintf(o, "screen %08x track %d time %d cur %d n %d flag %d list",
                 (unsigned)p->records.screen,
                 track_idx(p, p->records.track), (int)p->records.time,
                 (int)p->records.cur, (int)p->records.n,
                 (int)p->records.flag);
    for (int k = 0; k < p->records.count; k++)
        o += sprintf(o, " %d:%08x:%d", (int)p->records.rec[k].laps,
                     (unsigned)p->records.rec[k].table->Time.PackedTime,
                     (int)p->records.rec[k].table->NameIndex);
    note("rec", text);

    {
        const BTrackSelLocked *l = &p->locked;
        o = text;
        o += sprintf(o, "track %d screen %08x x %08x alpha %d start %d "
                     "slide %08x %08x %08x %d %d ",
                     track_idx(p, l->track), (unsigned)l->screen,
                     (unsigned)fbits(l->x), (int)l->alpha, (int)l->start,
                     (unsigned)l->slide.screen, (unsigned)l->slide.group,
                     (unsigned)l->slide.master, (int)l->slide.savedX,
                     (int)l->slide.savedY);
        hex(o, (const uint8_t *)&l->slide.spline, 0, 48);
        o += strlen(o);
        sprintf(o, " \"%s\"", l->blurb);
        note("lock", text);
    }
}

static void dump(void)
{
    char text[256];

    if (module.screen) dump_screen(module.screen);
    else note("scr", "present 0");
    snprintf(text, sizeof text, "%08x", (unsigned)fbits(btracksel_model_angle));
    note("angle", text);
    snprintf(text, sizeof text, "%d %d %d %d",
             (int)Fred.SelectTrackScreenData[0],
             (int)Fred.SelectTrackScreenData[1],
             (int)Fred.SelectTrackScreenData[2],
             (int)Fred.SelectTrackScreenData[3]);
    note("fred", text);
    snprintf(text, sizeof text,
             "track %d dir %d type %d p2p %d laps %d np %d nai %d tree %d",
             (int)TheRaceParameters.TrackNumber,
             (int)TheRaceParameters.TrackDirection,
             (int)TheRaceParameters.RaceType,
             (int)TheRaceParameters.Point2Point,
             (int)TheRaceParameters.NumLapsInRace,
             (int)TheRaceParameters.NumPlayerCars,
             (int)TheRaceParameters.NumAICars,
             (int)TheRaceParameters.EventTreeRace);
    note("rp", text);
    snprintf(text, sizeof text, "used %ld failed %d amount %u",
             (long)(CurrentBufferPos - frameBase), (int)FrameMallocFailed,
             (unsigned)FrameMallocFailAmount);
    note("frame", text);
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
    else if (!strcmp(k, "opts")) Fred.MainMenuOpts[0] = inum(v);
    else if (!strcmp(k, "rtimer")) RealTimer = inum(v);
    else if (!strcmp(k, "relapsed")) RealTimeElapsed = fnum(v);
    else if (!strcmp(k, "active")) activeItem = inum(v);
    else if (!strcmp(k, "tex")) texMode = inum(v);
    else if (!strcmp(k, "seed")) bDefaultSeed = num(v);
    else if (!strcmp(k, "solid")) solidNext = num(v);
    else if (!strcmp(k, "rpnp")) TheRaceParameters.NumPlayerCars = inum(v);
    else if (!strcmp(k, "rpnai")) TheRaceParameters.NumAICars = inum(v);
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
    if (!strcmp(a[0], "tracks")) {
        load_tracks(a[1]);
        return;
    }
    if (!strcmp(a[0], "g")) set_global(a[1], a[2]);
    else if (!strcmp(a[0], "data")) {
        for (int i = 0; i < 4; i++) Fred.SelectTrackScreenData[i] = inum(a[1 + i]);
    } else if (!strcmp(a[0], "cls")) carClass[inum(a[1]) & 1] = inum(a[2]);
    else if (!strcmp(a[0], "unl"))
        unlockedAns[inum(a[1])][inum(a[2]) & 1] = (int8_t)inum(a[3]);
    else if (!strcmp(a[0], "egg"))
        eggAns[inum(a[1])][inum(a[2]) & 1] = (int8_t)inum(a[3]);
    else if (!strcmp(a[0], "ev")) {
        evTree[inum(a[1])][inum(a[2]) & 1] = inum(a[3]);
        evNum[inum(a[1])][inum(a[2]) & 1] = inum(a[4]);
    } else if (!strcmp(a[0], "lap")) {
        FredHighScore *r = &lapRec[inum(a[1])][inum(a[2]) & 7][inum(a[3]) & 1];
        r->Time.PackedTime = num(a[4]);
        r->NameIndex = (int16_t)inum(a[5]);
    } else if (!strcmp(a[0], "tot")) {
        FredHighScore *r = &totRec[inum(a[1])][inum(a[2]) & 7][inum(a[3]) & 1]
                                  [lapsIndex(inum(a[4]))];
        r->Time.PackedTime = num(a[5]);
        r->NameIndex = (int16_t)inum(a[6]);
    } else if (!strcmp(a[0], "xl")) {
        int32_t id = inum(a[1]);
        int     i;
        for (i = 0; i < numXl && xl[i].id != id; i++)
            ;
        if (i == numXl) numXl++;
        xl[i].id = id;
        snprintf(xl[i].text, sizeof xl[i].text, "%s", a[2]);
    } else if (!strcmp(a[0], "msg")) {
        BScreenCallbackData d;
        d.itemHash = num(a[2]);
        d.port = inum(a[3]);
        d.param = inum(a[4]);
        d.noise = inum(a[5]);
        btracksel_screen_callback(NULL, (BScreenMessage)inum(a[1]), &d);
        printf("  data %d %d\n", (int)d.param, (int)d.noise);
    } else if (!strcmp(a[0], "texloaded")) {
        if (loadCb) loadCb(loadParam);
    } else if (!strcmp(a[0], "frame")) {
        uint32_t size = num(a[1]);
        free(frameBase);
        frameBase = size ? (uint8_t *)calloc(size, 1) : NULL;
        CurrentBufferPos = frameBase;
        CurrentBufferEnd = frameBase ? frameBase + size : NULL;
        FrameMallocFailed = 0;
        FrameMallocFailAmount = 0;
    } else {
        printf("  no op %s\n", a[0]);
        exit(2);
    }
    // The set-up ops change nothing until the next action shows it.
    if (!strcmp(a[0], "msg") || !strcmp(a[0], "texloaded")) dump();
}

int main(int argc, char **argv)
{
    static char    line[1 << 16];
    FILE          *f;
    BTrackSelHooks h;

    if (argc < 2) return 2;
    f = fopen(argv[1], "r");
    if (!f) return 2;

    gFlailerTextScaledWidthFn = text_w;
    gFlailerTextScaledHeightFn = text_h;
    gFlailerBitmapTextureSizeFn = texture_size;
    gEModelRenderFn = h_render;

    for (int t = 0; t < NUM_TRACKS; t++)
        for (int d = 0; d < 2; d++) {
            unlockedAns[t][d] = 1;
            evTree[t][d] = -1;
            for (int c = 0; c < 8; c++) {
                lapRec[t][c][d].Time.PackedTime = HIGH_SCORE_NO_TIME;
                for (int l = 0; l < 4; l++)
                    totRec[t][c][d][l].Time.PackedTime = HIGH_SCORE_NO_TIME;
            }
        }

    memset(&h, 0, sizeof h);
    h.translate = h_translate;
    h.speechFade = h_fade;
    h.speakTrack = h_speak;
    h.eggActive = h_egg;
    h.isTrackUnlocked = h_unlocked;
    h.formatUnlockBlurb = h_blurb;
    h.renderTextIntoRectangle = h_rtext;
    h.setActiveMenuItem = h_set_active;
    h.getActiveMenuItem = h_get_active;
    h.packNew = h_pack_new;
    h.packDelete = h_pack_delete;
    h.packUnloadAll = h_pack_unload;
    h.packHasTexture = h_pack_has;
    h.packLoad = h_pack_load;
    h.highlightInit = h_hl_init;
    h.highlightSetItem = h_hl_item;
    h.highlightAnimate = h_hl_anim;
    h.language = h_language;
    h.startRace = h_start_race;
    btracksel_init(&module, &h);

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
