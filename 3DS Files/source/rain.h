// rain -- the four entry points Rain.obj (0x001282d8 .. 0x00128c18) gives
// the rest of the game, which the shipped image compiles to nothing:
//
//   rain_Load      0x00128bf8   the End of LOADING_TRACK_SPECIFIC, after
//                               SkyLoader
//   rain_Unload    0x00128c00   the Begin of UNLOADING_TRACK_SPECIFIC,
//                               after SkyUnloader
//   rain_TimeStep  0x00128c08   World::DoTimestep, after the players'
//                               game state
//   rain_Render    0x00128c10   nothing calls it
//
// Each is `jr ra ; nop`. The port keeps them as calls, so the End, the
// Begin and the timestep read as the image's do.
//
// The rest of Rain.obj is dead in the image. RainSystem's constructor,
// destructor, Update, Render, SplashLoop and TweakSplashes have no caller
// and no reference in the loaded code, and RainSplash's Cache, Recalc,
// Render and Respawn are reached only from SplashLoop. Nothing reads
// rainSystems or rain_active. rain_pos is read only by RainSystem::Update,
// and rain_default_texture only by RainSplash::Render.
//
// So is the storm, in EcstasyE.obj:
//   - UpdateStorm and RenderAllStorms have no caller, and RenderStorm is
//     reached only from RenderAllStorms. Nothing reads DrawStorm.
//   - SetStormType is `jr ra ; nop`, and GetStormType returns 0.
//     GetStormTypeString returns "None" for any type. PauseDebugMenu is
//     their only caller.
//   - The static constructor stamps StormInfo's three entries. Only
//     UpdateStorm and RenderStorm read StormInfo or RainStorm, and nothing
//     reads SnowStorm or WaterSpray.
//
// Nor does SoundScape::UpdateWeather have a caller. So the weather query's
// one live reader is CreateFogPalette, and a track's rain, snow and wind
// regions load and do nothing. TRACKB12 has none.
//
// Cross-check: tools/rain_check.py. Write-up: docs/formats/rain.md.

#ifndef RAIN_H
#define RAIN_H

struct eView;

void rain_Load(void);
void rain_Unload(void);
void rain_TimeStep(float dt);
void rain_Render(struct eView *view);

#endif
