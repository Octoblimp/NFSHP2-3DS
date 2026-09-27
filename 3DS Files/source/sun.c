// sun -- see sun.h.

#include "sun.h"

#include "bchunk.h"

SunChunkInfoE *SunInfo;                     // 0x00322da0
TextureInfo   *SunTextures[NUM_SUN_TEXTURES];   // 0x002e76f0

const uint32_t kSunTextureHashes[NUM_SUN_TEXTURES] = {
    0x47beb4b6u,    // SUNCENTER
    0xd4d26c59u,    // SUNHALO
    0x1744b82du,    // SUNMAJORRAYS
    0xad3c5239u,    // SUNMINORRAYS
    0xd4d80a65u,    // SUNRING
};

// The rendering order SunTrackLoader gives each sun texture.
#define SUN_RENDERING_ORDER 7

static void forget_sun(void)
{
    SunInfo       = NULL;
    SunPosition.x = 0.0f;
    SunPosition.z = 0.0f;
    SunPosition.y = 0.0f;
}

int loader_sun(uint8_t *chunk)
{
    SunChunkInfoE *info;

    if (bchunk_u32(chunk) != SUN_CHUNK_ID) {
        return 0;
    }
    // The chunk's data, rounded up to 16.
    info = (SunChunkInfoE *)(((uintptr_t)chunk + 8 + 15) & ~(uintptr_t)15);
    SunInfo = info;
    if (info->Version != SUN_INFO_VERSION) {
        forget_sun();
    } else {
        SunPosition.x = info->PositionX;
        SunPosition.y = info->PositionY;
        SunPosition.z = info->PositionZ;
    }
    return 1;
}

int unloader_sun(uint8_t *chunk)
{
    if (bchunk_u32(chunk) != SUN_CHUNK_ID) {
        return 0;
    }
    forget_sun();
    return 1;
}

void SunTrackLoader(void)
{
    int i;

    for (i = 0; i < NUM_SUN_TEXTURES; i++) {
        SunTextures[i] = GetTextureInfo(kSunTextureHashes[i], 1, 0);
    }
    // The image does not check them. A name that no pack has is given the
    // default, and it is the default that gets order 7. Only with no
    // default either is it NULL, which the image stores through at 41.
    for (i = 0; i < NUM_SUN_TEXTURES; i++) {
        if (SunTextures[i] != NULL) {
            SunTextures[i]->RenderingOrder = SUN_RENDERING_ORDER;
        }
    }
}

void SunTrackUnloader(void)
{
    int i;

    for (i = 0; i < NUM_SUN_TEXTURES; i++) {
        SunTextures[i] = NULL;
    }
}
