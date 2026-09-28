// sun -- the data half of Sun.obj (retail 0x00124f30 .. 0x001252b0, the
// demo's 0x00123d30 .. 0x00123ec0): the track's sun chunk, slot 14 of the
// LoaderTable, the glare's layers, and the five textures the sun is drawn
// with.
//
// A track has one 0x34202 chunk, a SunChunkInfoE of 244 bytes at the next
// 16 in the chunk. It gives the sun's position in the world, where the
// cars' shadows are cast from, and six layers of sprite. The loader keeps
// a pointer to it and copies the position out. All 30 of the retail
// disc's tracks have one, version 2, whose shadows are cast from the sun's
// own place. Retail TRACKB12's is at (-3900, 650, 1300); the demo's was at
// (-16384, 800, 6000), with the same layers. TRACKB14..16's and
// TRACKB24..26's layers are all empty, TRACKB31..36's are their own, and
// the other 18 tracks have TRACKB12's.
//
// Retail's loader then fills SunGlareInfo, a record of its own that the
// glare draws from, with four fixed layers. The demo's glare drew the
// track's.
//
// SunTrackLoader, from EndGameFlowLoadingTrackSpecific, looks up the five
// SUN textures, which are TEX12LOCATION's, and gives each rendering order
// 7. SunTrackUnloader forgets them.
//
// StuffSun and StuffSunGlare, the draw, are sundraw.c's.
//
// Cross-check: tools/sky_check.py. Write-up: docs/formats/sky-sun.md.

#ifndef SUN_H
#define SUN_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "texturepack.h"

// SunTextureType (.mdebug type#4777).
enum {
    SUNTEX_CENTER    = 0,
    SUNTEX_HALO      = 1,
    SUNTEX_MAJORRAYS = 2,
    SUNTEX_MINORRAYS = 3,
    SUNTEX_RING      = 4,
    NUM_SUN_TEXTURES = 5
};

// SunAlphaType (type#4778).
enum {
    SUNALPHA_BLEND = 0,
    SUNALPHA_ADD   = 1
};

// SunLayer, 36 bytes (type#4779): one sprite of the sun.
typedef struct SunLayer {
    int32_t   Texture;                      //  0  SunTextureType
    int32_t   AlphaType;                    //  4  SunAlphaType
    float     IntensityScale;               //  8
    float     Size;                         // 12
    float     OffsetX;                      // 16
    float     OffsetY;                      // 20
    uint8_t   Colour[4];                    // 24  bColour: r, g, b, a
    int32_t   Angle;                        // 28
    float     SweepAngleAmount;             // 32
} SunLayer;                                 // 36

#define SUN_NUM_LAYERS 6

// SunChunkInfoE, 244 bytes (type#4785).
typedef struct SunChunkInfoE {
    int32_t   Version;                      //   0  2
    float     PositionX;                    //   4
    float     PositionY;                    //   8
    float     PositionZ;                    //  12
    float     CarShadowPositionX;           //  16
    float     CarShadowPositionY;           //  20
    float     CarShadowPositionZ;           //  24
    SunLayer  SunLayers[SUN_NUM_LAYERS];    //  28
} SunChunkInfoE;                            // 244

typedef char sun_layout_check[
    (sizeof(SunLayer) == 36 && sizeof(SunChunkInfoE) == 244
     && offsetof(SunChunkInfoE, SunLayers) == 28) ? 1 : -1];

#define SUN_CHUNK_ID      0x00034202u
#define SUN_INFO_VERSION  2

// SunInfo, retail gp-23584 (the demo's gp-24144): the loaded chunk's, or
// NULL.
extern SunChunkInfoE *SunInfo;

// SunPosition, retail 0x002e03c0 (the demo's 0x002dfdf0): the sun's
// position, 0 with no chunk. It is eviewmatrix.c's, whose light context
// looks from it.
extern bVector3 SunPosition;

// SunGlareInfo, retail 0x002ef4c0: the glare's layers. Zero until a sun
// chunk loads; then version 2, at 0, with these four layers and two empty:
//
//   texture  alpha  intensity  size  offset   colour            angle  sweep
//   CENTER   ADD    1.0          60    0,  0  255,200,100,128       0    0
//   CENTER   ADD    0.5         320    0,  0  130,159,122,128       0    0
//   MAJOR    ADD    0.7         800   -9, 28  159,122, 75,128       0    0.2
//   MAJOR    ADD    0.3         800   28,  9  166,119, 72,128   16384    0.2
//
// They are TRACKB12's own four but for two numbers: the second's colour
// there is 130,110,25, and the fourth's intensity 0.32.
extern SunChunkInfoE SunGlareInfo;

// SunTextures, retail 0x002ef5b8 (the demo's 0x002e76f0): by
// SunTextureType.
extern TextureInfo *SunTextures[NUM_SUN_TEXTURES];

// The five names, bStringHash of SUNCENTER, SUNHALO, SUNMAJORRAYS,
// SUNMINORRAYS and SUNRING.
extern const uint32_t kSunTextureHashes[NUM_SUN_TEXTURES];

// LoaderSun(bChunk *), retail 0x00124f30, and UnloaderSun, 0x00125188: 0
// for a chunk of any other type. The loader takes a chunk of any version;
// one that is not 2 leaves SunInfo NULL and the position 0. Either way it
// then fills SunGlareInfo afresh. The unloader leaves SunGlareInfo be.
int loader_sun(uint8_t *chunk);
int unloader_sun(uint8_t *chunk);

// SunTrackLoader, retail 0x001251c0, and SunTrackUnloader, 0x00125290.
void SunTrackLoader(void);
void SunTrackUnloader(void);

#endif
