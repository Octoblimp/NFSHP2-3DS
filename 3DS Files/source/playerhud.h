// playerhud -- which parts of the HUD a player shows, and showing them.
//
// Player::DetermineHudFeatures (retail 0x00178da0) answers a word of
// HUD_* bits from the race's state, the player's settings and the camera;
// SetHudFeatures (0x001796b0) takes such a word and, for each bit that
// changed, shows or hides the Flailer objects behind it on the player's
// HUD screen (HudScreenHash) and finds the ones UpdateHud writes into the
// Player's pFlailer* fields. UpdateHud (0x0017ecf0) calls the two in turn
// every frame; the destructor calls SetHudFeatures with 0.
//
// The bit names are the port's: retail has no symbols and the demo's
// stabs give CurrentHudFeatures only as an unsigned int. Each is named for
// what SetHudFeatures does with it. 0x10 and 0x100 are set by
// DetermineHudFeatures and read by nothing here.
//
// Written up in docs/formats/hud-features.md; checked on retail's image
// by tools/hudfeatures_check.py.

#ifndef PLAYERHUD_H
#define PLAYERHUD_H

#include <stdint.h>

#include "nisoverlay.h"
#include "track.h"

struct Car;
struct FlailerObjectChunk;
struct Player;
struct TrackMap;

#define HUD_TRACK_MAP         0x00000001u  // the TrackMap, made and freed
#define HUD_TIRE_FORCE        0x00000002u  // the four tyre-force bitmaps
#define HUD_RACE_OVER         0x00000004u  // the race-over messages
#define HUD_LAP_COUNTER       0x00000008u  // the lap block, with HUD_BEST_LAP
#define HUD_GAUGES            0x00000020u  // the bumper view's speedo and tach
#define HUD_GAUGES_OUTSIDE    0x00000040u  // the third-person gauge
#define HUD_SPLIT_TIMES       0x00000080u
#define HUD_RACE_POSITION     0x00000200u
#define HUD_BEST_LAP          0x00000400u
#define HUD_REAR_VIEW_MIRROR  0x00001000u
#define HUD_LETTERBOX         0x00002000u  // the eView's LetterBox byte
#define HUD_WRONG_WAY         0x00004000u
#define HUD_PURSUIT           0x00008000u
#define HUD_RESET_PROMPT      0x00010000u
#define HUD_SCORE             0x00020000u
#define HUD_MUSIC             0x00040000u  // the EA TRAX box's objects
#define HUD_RADAR             0x00080000u
#define HUD_TRACKER           0x00100000u
#define HUD_NIS_OVERLAY       0x00200000u
#define HUD_COP_LOOKING_BACK  0x00400000u  // Be A Cop's player 0, looking back
#define HUD_LIVE_SPLIT        0x00800000u
#define HUD_BE_THE_COP        0x01000000u
#define HUD_CINEMA_BARS       0x02000000u  // screen 0x49c15518's black bars
#define HUD_PURSUIT_HI        0x04000000u
#define HUD_PURSUIT_NIS       0x08000000u
#define HUD_GAUGES_IN_CAR     0x10000000u  // the in-car view's digits

// The track map modes SetTrackMapMode keeps to, and the one that is no map.
#define TRACKMAP_MODE_OFF 6

// Player::DetermineHudFeatures, 0x00178da0. 0 with no car or no HUD
// screen, during an AI or replay demo, an instant replay and after the
// race; HUD_MUSIC alone while a camera zone is on; then the NIS, busted,
// stage, finish and pause cases before the player's HUD state picks the
// rest (docs/formats/hud-features.md has the whole tree). pRaceCoordinator
// is read with no test, as retail does, and pCurrentRace once the NIS and
// busted cases are past: UpdateHud runs only in a race.
uint32_t player_determine_hud_features(struct Player *p);

// Player::SetHudFeatures, 0x001796b0: the HUD made to show `features`.
// The gauge bits (HUD_GAUGES and HUD_GAUGES_OUTSIDE) are redone every
// call; every other block runs only for a bit that changed. Last of all
// CurrentHudFeatures is `features`.
void player_set_hud_features(struct Player *p, uint32_t features);

// Player::UpdateHud, 0x0017ecf0, so far its head (to 0x0017ed34):
// DetermineHudFeatures, and SetHudFeatures when the answer differs from
// CurrentHudFeatures. The rest (HudDoAnimations, the score's fade at
// 0x0017d7c8, the scoring and RenderHud) is 8m-3.
void player_update_hud(struct Player *p);

// 0x00178c90, the port's name (the demo's SetTrackMapMode__6Playeri): the
// mode kept to the ones the race allows, stored in the race's display
// settings with RealTimeFrames in TimeTrackMapModeChanged if it changed,
// and handed to the TrackMap.
void player_set_track_map_mode(struct Player *p, int32_t mode);

// Player::IsNisPlaying, 0x00176520: the NisManager's word at +68, read
// with no test of the manager. The port reads it through playerinit.h's
// gNisManagerIsPlayingFn, and no manager or no seam is not playing.
int32_t player_is_nis_playing(const struct Player *p);

// Player::ShouldShowBustedText, 0x00182318: pCopManager is there and its
// ShouldDisplayBustedText (0x002289f8, copmanager.h's) says so.
int32_t player_should_show_busted_text(const struct Player *p);

// ----------------------------------------------------------------- seams
//
// The callees not yet ported. NULL skips the call. ClearHudAnimations is
// rcpost.h's gPlayerClearHudAnimationsFn.

// Player::SetRearViewMirrorCameraMover (0x001767a8), with the mirror's bit.
extern void (*gPlayerSetRearViewMirrorCameraMoverFn)(struct Player *p,
                                                     uint32_t on);
// InitializeFlailerTachometer (0x001434a0): the tach's points, from its
// needle and gradient, into the Player's FlailerTachPointList.
extern void (*gInitializeFlailerTachometerFn)(
    struct FlailerObjectChunk *needle, struct FlailerObjectChunk *gradient,
    void *points);
// `new TrackMap`: bMalloc(176, "TrackMap", 0, 16) and the constructor
// (0x001babb8) on the current track, the player's car and the player.
// NULL leaves pTrackMap NULL.
extern struct TrackMap *(*gNewTrackMapFn)(TrackInfo *track, struct Car *car,
                                          struct Player *p);
// TrackMap's deleting destructor (0x001badc8) with 3.
extern void (*gDeleteTrackMapFn)(struct TrackMap *m);
// Player::FillInRaceOverMessages (0x00181558).
extern void (*gPlayerFillInRaceOverMessagesFn)(struct Player *p);
// RaceFinishedSpeech (0x00206ab8), with the car's RacingCar FinishReason.
extern void (*gRaceFinishedSpeechFn)(struct Car *c, int32_t reason);
// Player::HudStartWrongWay (0x0017c888).
extern void (*gPlayerHudStartWrongWayFn)(struct Player *p);
// NISOverlayManager::SetVisible (0x00182a48), with the overlay's bit.
extern void (*gNisOverlaySetVisibleFn)(NISOverlayManager *o, uint32_t on);

#endif
