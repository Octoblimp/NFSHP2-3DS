// sun -- see sun.h.

#include "sun.h"

#include <string.h>

#include "bchunk.h"

SunChunkInfoE *SunInfo;                     // gp-23584
SunChunkInfoE  SunGlareInfo;                // 0x002ef4c0
TextureInfo   *SunTextures[NUM_SUN_TEXTURES];   // 0x002ef5b8

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

static void glare_layer(SunLayer *l, int32_t texture, float intensity,
                        float size, float ox, float oy, uint8_t r, uint8_t g,
                        uint8_t b, int32_t angle, float sweep)
{
    l->Texture          = texture;
    l->AlphaType        = SUNALPHA_ADD;
    l->IntensityScale   = intensity;
    l->Size             = size;
    l->OffsetX          = ox;
    l->OffsetY          = oy;
    l->Colour[0]        = r;
    l->Colour[1]        = g;
    l->Colour[2]        = b;
    l->Colour[3]        = 128;
    l->Angle            = angle;
    l->SweepAngleAmount = sweep;
}

// The image clears the record with memset and then stores the fields one
// by one; the two empty layers stay as the memset left them. Its 0.7, 0.3
// and 0.2 are gp-32148, gp-32144 and gp-32152.
static void fill_glare_info(void)
{
    SunChunkInfoE *g = &SunGlareInfo;

    memset(g, 0, sizeof *g);
    g->Version = SUN_INFO_VERSION;
    glare_layer(&g->SunLayers[0], SUNTEX_CENTER, 1.0f, 60.0f, 0.0f, 0.0f,
                255, 200, 100, 0, 0.0f);
    glare_layer(&g->SunLayers[1], SUNTEX_CENTER, 0.5f, 320.0f, 0.0f, 0.0f,
                130, 159, 122, 0, 0.0f);
    glare_layer(&g->SunLayers[2], SUNTEX_MAJORRAYS, 0.7f, 800.0f, -9.0f,
                28.0f, 159, 122, 75, 0, 0.2f);
    glare_layer(&g->SunLayers[3], SUNTEX_MAJORRAYS, 0.3f, 800.0f, 28.0f,
                9.0f, 166, 119, 72, 16384, 0.2f);
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
    fill_glare_info();
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
