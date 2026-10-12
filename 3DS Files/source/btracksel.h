// btracksel -- track select: retail's SelectTrackScreen, the screen car
// select goes on to for every game but the event games, as logic and 2D
// (step 12m-3c-1).
//
// What is ported, retail's addresses (SLES_507.31):
//
//   IsTrackUnavailable      0x0019dd20  game types 5 and 7 have no point to
//                                       point tracks
//   CalculateTrackNumberToLoad 0x0019ddc0  the variant for a time of day
//   SelectableTrack         0x0019de58 .. 0x0019e318  a track's thumbnail,
//                                       its times of day and its model
//   SelectableTrackManager  0x0019e318 .. 0x0019e970  the thumbnail strip
//   SelectTrackSlideshow    0x0019e970 .. 0x0019ed78  TSELECT.BIN's pictures
//   TODMenuManager          0x0019ed78 .. 0x0019ef00  the time-of-day menu
//   TrackRecordDisplayer    0x0019ef00 .. 0x0019f460  the best lap and the
//                                       best totals, in turn
//   TrackLockedDisplayer    0x0019f460 .. 0x0019f720  the "how to unlock
//                                       this track" box
//   SelectTrackScreen       0x0019f720 .. 0x001a0920  the screen, its lap
//                                       selector and StartRace (0x001a0790)
//   TrackSelectScreenCallback 0x001a0920
//
// and from the frontend animation kit, privately, as bcarsel.c has them:
// feAlphaAnimation (0x00248360) and AnimationGroup (0x00248568).
//
// Retail keeps its lists as bTLists of bMalloc'd nodes; the port keeps
// arrays, as long as the track table could need. The 3D (the TRACK%d_MINI
// model and the still camera) goes straight to emodel.c and stillcam.c, the
// Flailer calls to flailer.c, the records to highscore.c, and everything
// else out through BTrackSelHooks. tools/tracksel_check.py runs retail's
// code beside this over FRONTB's screen. Written up in
// docs/formats/track-select.md.

#ifndef BTRACKSEL_H
#define BTRACKSEL_H

#include <stdint.h>

#include "banim.h"
#include "bmenu.h"
#include "emodel.h"
#include "fred.h"
#include "gameflow.h"
#include "stillcam.h"
#include "track.h"

#define BTRACKSEL_SCREEN 0x15417b53u   // "Select Track"

#define BTRACKSEL_MAX_TRACKS  64        // 2 directions of 30 base tracks
#define BTRACKSEL_MAX_TODS    8         // the table has 2 a track
#define BTRACKSEL_MAX_RECORDS 4         // 1, 2, 4 and 8 laps
#define BTRACKSEL_MAX_FADE    8         // the slideshow's fades: 1 object

struct FlailerObjectChunk;
struct FlailerBitmapChunk;

// ------------------------------------------------------------ the hooks

// Everything the screen does outside the Flailer, the records, the model
// and the camera. Every hook is optional: a missing one does nothing and
// answers 0 (or "" for the strings).
typedef struct BTrackSelHooks {
    void* user;

    // GetTranslatedString(int) (0x0021e560). The answer may be overwritten
    // by the next call.
    const char* (*translate)(void* user, int32_t id);

    // speech::mgr_t::fade, and SQUARE's line: SPCH_AddEventV(155, 1,
    // Speech::ConvertTrackNumber(track)).
    void (*speechFade)(void* user, float level);
    void (*speakTrack)(void* user, int32_t track);

    // The easter eggs' test (0x0024f930 on TheEasterEggs): a track the egg
    // unlocks.
    int (*eggActive)(void* user, int32_t track, int32_t direction);
    // IsTrackUnlocked (0x0024b760); quickrace.h's is_track_unlocked.
    int (*isTrackUnlocked)(void* user, int32_t track, int32_t direction);
    // FormatUnlockBlurbForTrack (0x0024b6b0): how the track is unlocked,
    // into buf. A missing hook leaves its last answer, "This track should
    // be unlocked".
    void (*formatUnlockBlurb)(void* user, char* buf, int len, int32_t track,
                              int32_t direction);
    // FlailerRenderManager::RenderTextIntoRectangle (0x001451e0).
    void (*renderTextIntoRectangle)(void* user, uint32_t screen,
                                    uint32_t object, uint32_t rect,
                                    const char* text, float scale);

    // SetActiveMenuItem (0x0016d3d0) and GetActiveMenuItem (0x0016d3f0),
    // the current menu's, by item hash.
    void (*setActiveMenuItem)(void* user, uint32_t item);
    uint32_t (*getActiveMenuItem)(void* user);

    // The slideshow's TexturePack: bMalloc(148), TexturePack("TrackSelect",
    // NULL) and LoadTextureTableFromFile("FRONTEND\\TSELECT.BIN"); its
    // ~TexturePack(3); UnloadAllTexturesFromFile, which retail calls even
    // on a NULL pack; GetTexture's answer as a flag; and
    // LoadTexturesFromFile(pack, &hash, 1, cb, param).
    void* (*packNew)(void* user);
    void (*packDelete)(void* user, void* pack);
    void (*packUnloadAll)(void* user, void* pack);
    int (*packHasTexture)(void* user, void* pack, uint32_t hash);
    void (*packLoad)(void* user, void* pack, uint32_t hash,
                     void (*cb)(intptr_t param), intptr_t param);

    // tHighlightAnimation's constructor (0x00248870), SetCurrentMenuItem
    // (0x002488d0) and Animate (0x00248970), on the screen's own: banim.h's
    // banim_highlight_init, _set_item and _animate, on the flow's kit with
    // its clock set. The destructor (0x002488b0) does nothing to undo.
    void (*highlightInit)(void* user, BHighlightAnim* hl, uint32_t screen,
                          uint32_t object, int32_t color);
    void (*highlightSetItem)(void* user, BHighlightAnim* hl, uint32_t item);
    void (*highlightAnimate)(void* user, BHighlightAnim* hl);
    // CurrLanguage (0x0031c1c8), 0 English and 1 French.
    int32_t (*language)(void* user);

    // FrontendDatabase::StartRace (0x00184f68), StartRace's last step.
    void (*startRace)(void* user);

    void (*trace)(void* user, const char* line);
} BTrackSelHooks;

// ------------------------------------------------------------ the tracks

// TimeOfDayTrack, 16 bytes in retail: a node, the variant, and its icon's
// offset down the list, 50 a row.
typedef struct BTrackSelTOD {
    TrackInfo* ti;          //  8
    float      offset;      // 12
} BTrackSelTOD;

// SelectableTrack, 48 bytes in retail. curTOD is an index here, -1 for
// none.
typedef struct BTrackSelTrack {
    int32_t      vis;       //  8  0 unlocked, 1 unavailable, 2 locked
    int32_t      dir;       // 12
    uint32_t     thumb;     // 16  "TN_TRACK%d", or "TN_TRACK%dR"
    float        x;         // 20
    int32_t      curTOD;    // 24
    int32_t      nTOD;      // 28  the list
    BTrackSelTOD tod[BTRACKSEL_MAX_TODS];
    TrackInfo*   ti;        // 36  the base track
    eModel       model;     // 40  TRACK%d_MINI; retail's from the slot pool
    float        height;    // 44  the list's, 50 a row
} BTrackSelTrack;

// SelectableTrackManager: the list, the current track (an index, -1 for
// none) and the thumbnails' spacing.
typedef struct BTrackSelManager {
    int32_t        count;
    BTrackSelTrack tracks[BTRACKSEL_MAX_TRACKS];
    int32_t        cur;     //  8
    float          spacing; // 12
} BTrackSelManager;

// feAlphaAnimation: the objects' alphas, saved.
typedef struct BTrackSelFade {
    uint32_t screen;
    int32_t  count;
    struct {
        struct FlailerObjectChunk* obj;
        float alpha[4];
    } el[BTRACKSEL_MAX_FADE];
} BTrackSelFade;

// SelectTrackSlideshow.
typedef struct BTrackSelShow {
    uint32_t        screen;  //  0
    void*           pack;    //  4
    BTrackSelTrack* track;   //  8
    int32_t         t0;      // 12  RealTimer as the picture went up
    int32_t         t1;      // 16  RealTimer as the cross-fade began
    uint32_t        tex;     // 20  the picture loading or shown next
    int32_t         loaded;  // 24
    int32_t         state;   // 28  0 showing, 1 fading to the next
    BTrackSelFade   front;   // 32  0x883beb15
    BTrackSelFade   back;    // 44  0x886bfd7d
} BTrackSelShow;

// TODMenuManager.
typedef struct BTrackSelTODMenu {
    uint32_t        screen;  //  0
    BTrackSelTrack* track;   //  4
} BTrackSelTODMenu;

// TrackRecordDisplayer. The track at +4 is never written, so every
// SetCurrentTrack runs.
typedef struct BTrackSelRecords {
    uint32_t        screen;  //  0
    BTrackSelTrack* track;   //  4
    int32_t         time;    //  8  RealTimer as the record went up
    int32_t         count;   // 12  the list: {laps, the table}
    struct {
        int32_t        laps;
        FredHighScore* table;
    } rec[BTRACKSEL_MAX_RECORDS];
    int32_t         cur;     // 20  an index, -1 for the head
    int32_t         n;       // 24
    int32_t         flag;    // 28  the next fade moves on
} BTrackSelRecords;

// Retail's AnimationGroup, as bcarsel.h's BCarSelSlide.
typedef struct BTrackSelSlide {
    uint32_t screen, group, master;
    int32_t  savedX, savedY;
    BSpline  spline;
} BTrackSelSlide;

// TrackLockedDisplayer, 352 bytes in retail.
typedef struct BTrackSelLocked {
    BTrackSelTrack* track;      //   0
    uint32_t        screen;     //   4
    float           x;          //   8  the box's resting X
    int32_t         alpha;      //  12  the fade's alpha as laid out
    BTrackSelSlide  slide;      //  16
    char            blurb[256]; //  92
    int32_t         start;      // 348  RealTimer when it last slid on
} BTrackSelLocked;

// SelectTrackScreen, 656 bytes in retail. The offsets are retail's; the
// camera mover is bMalloc'd there and kept in place here.
typedef struct SelectTrackScreen {
    int32_t          normal;    //   0  0 while the lap selector is up
    int32_t          data[4];   //   4  SelectTrackScreenData: base track,
                                //      laps, direction, time of day
    uint32_t         screen;    //  20
    int32_t          speaking;  //  24  SQUARE's toggle
    struct FlailerBitmapChunk* bitmaps[6]; // 32  d1cda594, 9345e4a7,
                                //      3b89e410, 3489f2a3, edf2e4ee,
                                //      20d73d01
    BSpline          x;         //  56  the strip's X
    BSpline          y;         // 104  the time-of-day list's Y
    BTrackSelManager mgr;       // 152
    float            phase;     // 168  the arrows' pulse
    StillCameraMover mover;     // 172
    int32_t          haveMover;
    BTrackSelShow    show;      // 176
    BTrackSelTODMenu todMenu;   // 232
    BTrackSelRecords records;   // 240
    BTrackSelLocked  locked;    // 272
    BHighlightAnim   highlight; // 624
} SelectTrackScreen;

// The module: the hooks and the screen (gp-19760).
typedef struct BTrackSel {
    BTrackSelHooks     hooks;
    SelectTrackScreen* screen;
} BTrackSel;

void btracksel_init(BTrackSel* m, const BTrackSelHooks* hooks);

// TrackSelectScreenCallback (0x001a0920), "Select Track"'s.
void btracksel_screen_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data);

// Whether the screen is up.
int btracksel_active(void);

// The port's: the textures on the slideshow's two bitmaps, the front's and
// then the back's, 0 for one the screen lacks or with the screen down.
// main.c draws the TSELECT.BIN pictures among them from copies of its own.
void btracksel_show_textures(uint32_t out[2]);

// gp-19700, the model's angle, which persists from one visit to the next.
extern float btracksel_model_angle;

#endif
