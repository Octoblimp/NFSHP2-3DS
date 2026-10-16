// eventtreeview -- the career's screen, "View Event Tree" (0x147f8a59):
// retail's tEventTreeView and the classes it is built from (EventTree.obj,
// 0x001f5dd0 .. 0x001fb868 in SLES_507.31).
//
// The screen draws one of the two event trees -- the World Championship
// (game type 8) or Ultimate Road Racer (9) -- as a grid of panels joined by
// lines, pans and zooms to the event the D-pad picks, and shows that
// event's details (its track, its cars, its description) when it is
// chosen. Select on the details starts the event: the race parameters are
// set from it and the flow goes to Select Car, or, for a tournament under
// way, straight back into its next race.
//
// Retail draws the panels, the lines and the details by copying Flailer
// objects and handing the copies to FlailerRenderManager each frame
// (RenderFlailerBitmap 0x00143078, RenderFlailerText 0x00142260). The port
// does the copying here and hands the copies to the renderer through the
// hooks, which queue them for the frame's layers (uirender_queue_copy).
//
// What is not here:
//
//   - The reward's 3D view (tCarModelViewer and tTrackModelViewer,
//     ModelViewer.obj): the reward page shows its name and its Flailer
//     objects, not the turning model.
//   - The help menu (tHelpMenu): SetHelpOverride is a hook, which main.c
//     logs.
//   - The StillCameraMover the constructor makes: the frontend's backdrop
//     camera is main.c's.
//
// Written up in docs/formats/event-tree-view.md.

#ifndef EVENTTREEVIEW_H
#define EVENTTREEVIEW_H

#include <stdint.h>

#include "banim.h"
#include "bmenu.h"
#include "eventtree.h"
#include "flailer.h"
#include "gameflow.h"

#define ETV_SCREEN          0x147f8a59u   // "View Event Tree"
#define ETV_SCREEN_DETAILS  0xa744ba7bu   // the details panel
#define ETV_SCREEN_POPUP    0xfd297fd4u   // the Ultimate's help popup
#define ETV_SCREEN_REWARD   0xf1eed4cdu   // the reward page

// The blurb line along the bottom (tAnimatedBlurb's SCROLLING text and its
// wipe bar), which main.c shows on the bottom screen.
#define ETV_OBJ_SCROLLING   0xfecebef6u

typedef struct EtvHooks {
    void* user;

    // GetTranslatedString(int) (0x0021e560) and (const char*) (0x0021e508).
    const char* (*translate)(void* user, int32_t id);
    const char* (*translateString)(void* user, const char* s);

    // The flow's animation kit with its clock set, for tAnimatedBlurb.
    BAnim* (*anim)(void* user);

    // RenderFlailerBitmap (0x00143078) and RenderFlailerText (0x00142260)
    // on a copy of `orig`: drawn this frame in the copy's layer, whatever
    // the visibility of the object or its screen, at `alpha` times its own.
    // `clip` is the clip window (x0, y0, x1, y1) a bitmap is cut to, and a
    // text whose FormatOptions has 0x10; NULL for a text without it.
    void (*renderBitmap)(void* user, struct FlailerBitmapChunk* orig,
                         const struct FlailerBitmapChunk* copy, float alpha,
                         const float* clip);
    void (*renderText)(void* user, struct FlailerTextChunk* orig,
                       const struct FlailerTextChunk* copy, float alpha,
                       const float* clip);
    // FlailerRenderManager::RenderTextIntoRectangle (0x001451e0), drawn
    // whatever the screen's visibility.
    void (*renderTextIntoRectangle)(void* user, uint32_t screen,
                                    uint32_t object, uint32_t rect,
                                    const char* text, float scale);

    // SetHelpOverride (0x0016d448), NULL lines for off; 0x001e3dd0, the
    // help menu's hide.
    void (*setHelpOverride)(void* user, const int32_t* lines);
    void (*hideHelp)(void* user);
    // StopMovie, the jukebox's Start(1), and Select Car's preload
    // (0x00183ec0).
    void (*stopMovie)(void* user);
    void (*jukeboxStart)(void* user);
    void (*preloadCars)(void* user);
    // The frontend's kept textures (0x00249730, 0x00249828): a car logo
    // the slideshow will show, and all of them let go.
    void (*keepTexture)(void* user, uint32_t hash);
    void (*releaseKept)(void* user);
    // 0x0016fdb0, the debug unlock's test; 0 in retail. NULL answers 0.
    int (*debugUnlock)(void* user);

    void (*trace)(void* user, const char* line);
} EtvHooks;

// The hooks, kept by pointer; set once before the screen is first shown.
void eventtreeview_init(const EtvHooks* h);

// The screen's FlailerScreenConfig callback (0x001fb218).
void eventtreeview_screen_callback(BGameFlow* gf, BScreenMessage msg,
                                   BScreenCallbackData* data);

// FormatStatus (0x001f60e8): the event's status line into `buf`, by the
// status names 62000 .. 62004 -- a tournament's "race %d of %d", a won
// event's finish. A status past 4 leaves `buf` alone.
void eventtreeview_format_status(char* buf, int size, const EventInfo* e);
// FormatReward (0x001f6220): the first reward's name, a car's or a track's;
// "No reward" (0x101d8) for none, nothing for any other type.
void eventtreeview_format_reward(char* buf, int size, const EventInfo* e);

// True while the screen is up; for the bottom screen.
int eventtreeview_active(void);

#endif  // EVENTTREEVIEW_H
