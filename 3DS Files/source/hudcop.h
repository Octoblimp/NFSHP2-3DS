// hudcop -- the HUD's cop parts: the radar detector's lights and beep, the
// trackers over the cars near the player, and the pursuit meter with its
// tickets.
//
//   Player::UpdateRadarDetector                    0x0017be70   1032 bytes
//   Player::DrawTracker(Car *, int)                0x0017c278    264 bytes
//   Player::UpdatePursuitMeter(int)                0x0017c380   1092 bytes
//
// UpdateHud (hudrender.c) calls each through its seam: the pursuit meter
// with tCopManager's HUD pursuit level when the HUD shows a pursuit, the
// radar detector when it shows the radar, and DrawTracker for each AI car
// and cop drawn, in a race that is racing.
//
// tCopManager::GetRadarDetectorIntensity (0x002274a8) walks the cops and
// the track path; it is copmgr.c's, and main.c binds its seam (12n).
//
// Step 8m-4c-1. Written up in docs/formats/hud-cop.md; checked on
// retail's image by tools/hudcop_check.py.

#ifndef HUDCOP_H
#define HUDCOP_H

#include <stdint.h>

struct Car;
struct Player;
struct tCopManager;

// Player::UpdateRadarDetector. The intensity, times 11 and truncated to
// at most 10, lights that many of the twelve radar lights in the lit
// colour and the rest in the unlit one, from RadarColours: rows 0 and 1
// normally, 2 and 3 when the cop manager flags the nearest cop. At 9 and
// over, light 10 swells off light 8 in slot 16; at 10, light 11 off light
// 9 in slot 17; otherwise each is hidden. With the sound on and a light
// lit, RadarTimer counts the world's time and the beep plays each time it
// passes 0.5 - 0.0383 a light, in seconds; otherwise RadarTimer is 0.
void player_update_radar_detector(struct Player *p);

// Player::DrawTracker: tracker `index` over car `c`, when `c` is within
// 50 of the player's car and its fAngleToCamera within half a turn of
// straight ahead either way: x at 120 + 400 for the turn, scale 2 near to
// 0 at 50, shown.
void player_draw_tracker(struct Player *p, struct Car *c, int32_t index);

// Player::UpdatePursuitMeter: with the pursuit star found, the tickets
// shown (at most 3, none in a free run), then, when the level changed,
// each bar gained flies in from 300 to the left, and each bar from the
// old level down to one below the new flies out up or down 50.
// PrevPursuitLevel takes the level.
void player_update_pursuit_meter(struct Player *p, int32_t level);

// tCopManager::GetRadarDetectorIntensity (0x002274a8): 0 to 1 for the
// nearest cop in range, with *flag the cop's kind (1 for a roadblock's).
// copmgr.c's copmanager_get_radar_detector_intensity; NULL reads 0 and
// leaves the flag 0.
extern float (*gCopManagerGetRadarDetectorIntensityFn)(struct tCopManager *m,
                                                       struct Car *c,
                                                       int32_t *flag);

#endif
