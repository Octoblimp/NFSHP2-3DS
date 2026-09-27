// epoly -- see epoly.h.

#include "epoly.h"

void (*gEPolyRenderFn)(ePoly *p, TextureInfo *tex, int flags);

void epoly_init(ePoly *p)
{
    int i;

    p->Vertices[0].x = 0.0f;
    p->Vertices[0].y = 0.0f;
    p->Vertices[1].x = 64.0f;
    p->Vertices[1].y = 0.0f;
    p->Vertices[2].x = 64.0f;
    p->Vertices[2].y = 64.0f;
    p->Vertices[3].x = 0.0f;
    p->Vertices[3].y = 64.0f;
    for (i = 0; i < 4; i++) {
        p->Vertices[i].z = EPOLY_DEFAULT_Z;
        p->Vertices[i].w = 0.0f;
    }

    p->UVs[0][0] = 0.0f;
    p->UVs[0][1] = 0.0f;
    p->UVs[1][0] = 1.0f;
    p->UVs[1][1] = 0.0f;
    p->UVs[2][0] = 1.0f;
    p->UVs[2][1] = 1.0f;
    p->UVs[3][0] = 0.0f;
    p->UVs[3][1] = 1.0f;
    for (i = 0; i < 4; i++) {
        p->UVs[i][2] = 1.0f;
        p->Colours[i][0] = 0x80;
        p->Colours[i][1] = 0x80;
        p->Colours[i][2] = 0x80;
        p->Colours[i][3] = 0x80;
    }

    p->AlphaA              = EPOLY_ALPHA_CS;
    p->AlphaB              = EPOLY_ALPHA_CD;
    p->AlphaC              = 0;
    p->AlphaD              = EPOLY_ALPHA_CD;
    p->AlphaFix            = 128;
    p->AlphaEnabled        = 0;
    p->SunPoly             = 0;
    p->ApplyAspectRatio    = 1;
    p->Flailer             = 0;
    p->pDynamicFrameMemory = NULL;
}
