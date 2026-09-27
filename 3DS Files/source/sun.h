// sun -- the data half of Sun.obj (0x00123d30 .. 0x00123ec0): the track's
// sun chunk, slot 14 of the LoaderTable, and the five textures the sun is
// drawn with.
//
// A track has one 0x34202 chunk, a SunChunkInfoE of 244 bytes at the next
// 16 in the chunk. It gives the sun's position in the world, where the
// cars' shadows are cast from, and six layers of sprite. The loader keeps
// a pointer to it and copies the position out. TRACKB12's is version 2,
// at (-16384, 800, 6000), and its shadows are cast from the same place.
//
// SunTrackLoader, from EndGameFlowLoadingTrackSpecific, looks up the five
// SUN textures, which are TEX12LOCATION's, and gives each rendering order
// 7. SunTrackUnloader forgets them.
//
// StuffSun (0x00123ec0) and StuffSunGlare (0x001244c8), the draw, are not
// here yet.
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

// SunInfo, 0x00322da0 (gp-24144): the loaded chunk's, or NULL.
extern SunChunkInfoE *SunInfo;

// SunPosition, 0x002dfdf0: the sun's position, 0 with no chunk. It is
// eviewmatrix.c's, whose light context looks from it.
extern bVector3 SunPosition;

// SunTextures, 0x002e76f0: by SunTextureType.
extern TextureInfo *SunTextures[NUM_SUN_TEXTURES];

// The five names, bStringHash of SUNCENTER, SUNHALO, SUNMAJORRAYS,
// SUNMINORRAYS and SUNRING.
extern const uint32_t kSunTextureHashes[NUM_SUN_TEXTURES];

// LoaderSun(bChunk *), 0x00123d30, and UnloaderSun, 0x00123da8: 0 for a
// chunk of any other type. The loader takes a chunk of any version; one
// that is not 2 leaves SunInfo NULL and the position 0.
int loader_sun(uint8_t *chunk);
int unloader_sun(uint8_t *chunk);

// SunTrackLoader, 0x00123de0, and SunTrackUnloader, 0x00123ea0.
void SunTrackLoader(void);
void SunTrackUnloader(void);

#endif
