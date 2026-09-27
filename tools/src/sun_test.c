// Harness for tools/sun_check.py: runs the checker's scenarios on
// sundraw.c and epoly.c and prints what the model prints for the image.
// Every callee is a stub here, and each logs its name and its arguments;
// after each step the glare's globals and the SunZBuffers' rects are
// dumped. See the checker's docstring.
//
//     sun_test scenarios.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "emath.h"
#include "epoly.h"
#include "eview.h"
#include "realtime.h"
#include "sun.h"
#include "sundraw.h"
#include "texturepack.h"

bVector3 SunPosition;
int32_t  WorldTimer;

// ------------------------------------------------------------ the world

static SunChunkInfoE  info_rec;
static TextureInfo    tex[NUM_SUN_TEXTURES];
static eView          view;
static eRenderTarget  rt;
static Camera         cam;
static bMatrix4       wv, ws;

static int            has_info, texmask;
static int32_t        glare[7];
static uint32_t       ptimes[4];
static int32_t        zrect[4];
static int            seed;
static uint32_t       proj[64][3];
static int            nproj, k;
static int32_t        timers[64];
static int            ntimers, t;

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, sizeof u);
    return u;
}

static float flt(uint32_t u)
{
    float f;

    memcpy(&f, &u, sizeof f);
    return f;
}

static const char *label(const void *p)
{
    static char buf[4][32];
    static int  n;
    char       *b = buf[n++ & 3];
    int         i;

    if (p == NULL)
        return "null";
    if (p == &view)
        return "view";
    if (p == &rt)
        return "rt";
    if (p == &cam)
        return "cam";
    if (p == &wv)
        return "wv";
    if (p == &ws)
        return "ws";
    if (p == &info_rec)
        return "info";
    for (i = 0; i < NUM_SUN_TEXTURES; i++) {
        if (p == &tex[i]) {
            snprintf(b, 32, "t%d", i);
            return b;
        }
    }
    for (i = 0; i < NUM_SUN_ZBUFFERS; i++) {
        if (p == &SunZBuffers[i]) {
            snprintf(b, 32, "zb%d", i);
            return b;
        }
    }
    snprintf(b, 32, "x%p", p);
    return b;
}

// ------------------------------------------------------- the callees

TextureInfo *GetTextureInfo(uint32_t h, int use_default,
                            int include_unloaded)
{
    // Retail's third argument. The demo image the model runs has none, so
    // only a port that passes anything but 0 prints it.
    if (include_unloaded != 0)
        printf("  GetTextureInfo include_unloaded %d\n", include_unloaded);
    printf("  GetTextureInfo %08x %d\n", (unsigned)h, use_default);
    return NULL;
}

static void print_vector(const bVector4 *v)
{
    printf(" v %08x %08x %08x %08x\n", (unsigned)bits(v->x),
           (unsigned)bits(v->y), (unsigned)bits(v->z), (unsigned)bits(v->w));
}

void eRotTransPers(bVector4 *o, const bMatrix4 *m, const bVector4 *v)
{
    const uint32_t *p = proj[k % nproj];

    printf("  eRotTransPers %s", label(m));
    print_vector(v);
    o->x = flt(p[0]);
    o->y = flt(p[1]);
    o->z = 0.5f;
    o->w = 1.0f;
}

void eMulVector4(bVector4 *o, const bMatrix4 *m, const bVector4 *v)
{
    const uint32_t *p = proj[k % nproj];

    printf("  eMulVector %s", label(m));
    print_vector(v);
    o->x = 7.0f;
    o->y = -7.0f;
    o->z = flt(p[2]);
    o->w = 1.0f;
    k++;
}

float bSinBam(uint16_t a)
{
    printf("  bSin %d\n", (int)a);
    return (float)((int)a - 32768) / 32768.0f;
}

float bCosBam(uint16_t a)
{
    printf("  bCos %d\n", (int)a);
    return (float)(((int)a * 7) & 0xffff) / 65536.0f - 0.5f;
}

static void render(ePoly *p, TextureInfo *tx, int flags)
{
    int i, j;

    printf("  Render %s %d v", label(tx), flags);
    for (i = 0; i < 4; i++) {
        printf(" %08x %08x %08x %08x", (unsigned)bits(p->Vertices[i].x),
               (unsigned)bits(p->Vertices[i].y),
               (unsigned)bits(p->Vertices[i].z),
               (unsigned)bits(p->Vertices[i].w));
    }
    printf(" uv");
    for (i = 0; i < 4; i++) {
        for (j = 0; j < 3; j++) {
            printf(" %08x", (unsigned)bits(p->UVs[i][j]));
        }
    }
    printf(" c ");
    for (i = 0; i < 4; i++) {
        for (j = 0; j < 4; j++) {
            printf("%02x", p->Colours[i][j]);
        }
    }
    printf(" a %d %d %d %d %d %d %d %d %d %s\n", p->AlphaA, p->AlphaB,
           p->AlphaC, p->AlphaD, p->AlphaFix, p->AlphaEnabled, p->SunPoly,
           p->ApplyAspectRatio, p->Flailer, label(p->pDynamicFrameMemory));
}

// ePoly's constructor over 0xa5s, and the poly as it leaves it.
static void ctor(void)
{
    static ePoly p;
    int          i, j;

    memset(&p, 0xa5, sizeof p);
    epoly_init(&p);
    printf("  ePoly node ");
    for (i = 0; i < 16; i++) {
        printf("%02x", p.Node[i]);
    }
    printf(" v");
    for (i = 0; i < 4; i++) {
        printf(" %08x %08x %08x %08x", (unsigned)bits(p.Vertices[i].x),
               (unsigned)bits(p.Vertices[i].y),
               (unsigned)bits(p.Vertices[i].z),
               (unsigned)bits(p.Vertices[i].w));
    }
    printf(" uv");
    for (i = 0; i < 4; i++) {
        for (j = 0; j < 3; j++) {
            printf(" %08x", (unsigned)bits(p.UVs[i][j]));
        }
    }
    printf(" c ");
    for (i = 0; i < 4; i++) {
        for (j = 0; j < 4; j++) {
            printf("%02x", p.Colours[i][j]);
        }
    }
    printf(" a %d %d %d %d %d %d %d %d %d pad %02x%02x%02x %s\n", p.AlphaA,
           p.AlphaB, p.AlphaC, p.AlphaD, p.AlphaFix, p.AlphaEnabled,
           p.SunPoly, p.ApplyAspectRatio, p.Flailer, p.pad153[0],
           p.pad153[1], p.pad153[2], label(p.pDynamicFrameMemory));
}

static void transfer(uint8_t *dst, int x, int y, int w, int h)
{
    printf("  eTransferZBufferRect %s %d %d %d %d\n", label(dst), x, y, w,
           h);
}

// ------------------------------------------------------------ the state

static void dump(void)
{
    int b;

    printf("  = pos %08x %08x dist %08x start %d reset %d time %08x "
           "phase %d timer %d info %s\n",
           (unsigned)bits(SunPosX), (unsigned)bits(SunPosY),
           (unsigned)bits(GlareDist), (int)bStartGlare, (int)bResetGlare,
           (unsigned)bits(GlareStartTime), (int)iGlarePhase,
           (int)WorldTimer, label(SunInfo));
    printf("  zb");
    for (b = 0; b < NUM_SUN_ZBUFFERS; b++) {
        const SunZBuffer *z = &SunZBuffers[b];

        printf(" %d,%d,%d,%d", (int)z->StartX, (int)z->EndX, (int)z->StartY,
               (int)z->EndY);
    }
    printf("\n");
}

static const uint16_t kPat[10] = { 0, 63, 64, 65, 1, 0xffff, 32, 100,
                                   0x8000, 63 };

static void fill(int s)
{
    int b, i;

    for (b = 0; b < NUM_SUN_ZBUFFERS; b++) {
        for (i = 0; i < SUN_ZBUFFER_SIZE * SUN_ZBUFFER_SIZE; i++) {
            SunZBuffers[b].Buffer[i] =
                kPat[(i * 7 + b * 3 + s * 5 + (i >> 5)) % 10];
        }
    }
}

static void reset(void)
{
    int i;

    SunInfo = has_info ? &info_rec : NULL;
    for (i = 0; i < NUM_SUN_TEXTURES; i++) {
        SunTextures[i] = (texmask >> i & 1) ? &tex[i] : NULL;
    }
    SunPosX        = flt((uint32_t)glare[0]);
    SunPosY        = flt((uint32_t)glare[1]);
    GlareDist      = flt((uint32_t)glare[2]);
    bStartGlare    = glare[3];
    bResetGlare    = glare[4];
    GlareStartTime = flt((uint32_t)glare[5]);
    iGlarePhase    = glare[6];
    for (i = 0; i < 4; i++) {
        PhaseTimes[i] = flt(ptimes[i]);
    }
    fill(seed);
    for (i = 0; i < NUM_SUN_ZBUFFERS; i++) {
        SunZBuffers[i].StartX = zrect[0];
        SunZBuffers[i].EndX   = zrect[1];
        SunZBuffers[i].StartY = zrect[2];
        SunZBuffers[i].EndY   = zrect[3];
    }
    k = 0;
    t = 0;
}

static void run(int n, const char *ops)
{
    const char *o;

    reset();
    printf("scenario %d %s\n", n, ops);
    for (o = ops; *o; o++) {
        printf(" %c\n", *o);
        switch (*o) {
        case 'S':
        case 'G':
            WorldTimer = timers[t % ntimers];
            t++;
            if (*o == 'S') {
                StuffSun(&view);
            } else {
                StuffSunGlare(&view);
            }
            break;
        case 'b':
            bStartGlare = 1;
            break;
        case 'r':
            bResetGlare = 1;
            break;
        case 'z':
            seed++;
            fill(seed);
            break;
        case 'c':
            ctor();
            break;
        }
        dump();
    }
}

// ------------------------------------------------------- the scenarios

static char *next_tok(char **s)
{
    char *p = *s, *r;

    while (*p == ' ')
        p++;
    r = p;
    while (*p && *p != ' ' && *p != '\n' && *p != '\r')
        p++;
    if (*p)
        *p++ = 0;
    *s = p;
    return r;
}

static uint32_t hex(char **s)
{
    return (uint32_t)strtoul(next_tok(s), NULL, 16);
}

static int32_t dec(char **s)
{
    return (int32_t)strtol(next_tok(s), NULL, 10);
}

int main(int argc, char **argv)
{
    static char line[16384];
    FILE       *f;
    int         n = 0, i;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: sun_test scenarios.txt\n");
        return 2;
    }
    view.pRenderTarget0    = &rt;
    view.pCamera           = &cam;
    view.WorldViewMatrix   = &wv;
    view.WorldScreenMatrix = &ws;
    gEPolyRenderFn          = render;
    gETransferZBufferRectFn = transfer;

    printf("initial times %08x %08x %08x %08x\n",
           (unsigned)bits(PhaseTimes[0]), (unsigned)bits(PhaseTimes[1]),
           (unsigned)bits(PhaseTimes[2]), (unsigned)bits(PhaseTimes[3]));
    dump();
    while (fgets(line, sizeof line, f)) {
        char *s = line + 2;

        switch (line[0]) {
        case 'I': {
            char    *h;
            uint8_t *r = (uint8_t *)&info_rec;

            has_info = dec(&s);
            texmask  = dec(&s);
            h        = next_tok(&s);
            for (i = 0; i < (int)sizeof info_rec; i++) {
                char two[3] = { h[2 * i], h[2 * i + 1], 0 };

                r[i] = (uint8_t)strtoul(two, NULL, 16);
            }
            break;
        }
        case 'V': {
            uint32_t c[8];

            view.ID     = dec(&s);
            rt.ID       = dec(&s);
            rt.ScissorW = dec(&s);
            rt.ScissorH = dec(&s);
            for (i = 0; i < 8; i++) {
                c[i] = hex(&s);
            }
            cam.CurrentKey.Position.x   = flt(c[0]);
            cam.CurrentKey.Position.y   = flt(c[1]);
            cam.CurrentKey.Position.z   = flt(c[2]);
            cam.CurrentKey.Position.pad = flt(c[3]);
            cam.CurrentKey.Direction.x   = flt(c[4]);
            cam.CurrentKey.Direction.y   = flt(c[5]);
            cam.CurrentKey.Direction.z   = flt(c[6]);
            cam.CurrentKey.Direction.pad = flt(c[7]);
            break;
        }
        case 'G':
            for (i = 0; i < 7; i++) {
                glare[i] = (int32_t)hex(&s);
            }
            for (i = 0; i < 4; i++) {
                ptimes[i] = hex(&s);
            }
            break;
        case 'Z':
            for (i = 0; i < 4; i++) {
                zrect[i] = dec(&s);
            }
            seed = dec(&s);
            break;
        case 'P':
            nproj = dec(&s);
            for (i = 0; i < nproj; i++) {
                proj[i][0] = hex(&s);
                proj[i][1] = hex(&s);
                proj[i][2] = hex(&s);
            }
            break;
        case 'T':
            ntimers = dec(&s);
            for (i = 0; i < ntimers; i++) {
                timers[i] = dec(&s);
            }
            break;
        case 'S':
            run(n++, next_tok(&s));
            break;
        }
    }
    fclose(f);
    return 0;
}
