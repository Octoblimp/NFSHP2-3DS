// Harness for tools/sky_check.py: runs the checker's scenarios on sky.c and
// sun.c and prints what the model prints for the image. Every callee is a
// stub here, and each logs its name and its arguments; after each step the
// state both objects keep is dumped. See the checker's docstring.
//
//     sky_test scenarios.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "emath.h"
#include "emodel.h"
#include "eview.h"
#include "scenery.h"
#include "scenerycull.h"
#include "sky.h"
#include "sun.h"
#include "texturepack.h"

void (*gEModelRenderFn)(eModel *m, bMatrix4 *matrix, void *light,
                        uint32_t flags);
bVector3 SunPosition;

// ------------------------------------------------------------ the world

static SceneryInstance inst[2];
static SceneryInfo     info[2];
static int             present[2];
static eModel          lod[6];
static int             solid_obj, junk_obj;
static TextureInfo     tex[6];              // t0 .. t4, then the default
static int             found_mask, has_default;
static eView           view;
static uint8_t         chunk_raw[512 + 16];
static uint8_t        *chunk;
static size_t          chunk_len;

static const uint32_t kHash[2] = { SKY_HASH_SKYDOME, SKY_HASH_SKYDOME_ENVMAP };

static const char *label(const void *p)
{
    static char buf[4][32];
    static int  k;
    char       *b = buf[k++ & 3];
    int         i;

    if (p == NULL)
        return "null";
    if (p == &SkydomeModel)
        return "sky";
    if (p == &SkydomeEnvmapModel)
        return "env";
    if (p == &SkydomeLocalWorld)
        return "skyM";
    if (p == &SkydomeEnvmapLocalWorld)
        return "envM";
    if (p == &inst[0])
        return "isky";
    if (p == &inst[1])
        return "ienv";
    if (p == &info[0])
        return "fsky";
    if (p == &info[1])
        return "fenv";
    if (p == &solid_obj)
        return "solid";
    if (p == &junk_obj)
        return "junk";
    for (i = 0; i < 6; i++) {
        if (p == &lod[i]) {
            snprintf(b, 32, "m%d", i);
            return b;
        }
        if (p == &tex[i]) {
            if (i == 5)
                return "dflt";
            snprintf(b, 32, "t%d", i);
            return b;
        }
    }
    if (chunk && (const uint8_t *)p >= chunk
        && (const uint8_t *)p < chunk + 512) {
        snprintf(b, 32, "c+%d", (int)((const uint8_t *)p - chunk));
        return b;
    }
    snprintf(b, 32, "x%p", p);
    return b;
}

// ------------------------------------------------------- the callees

SceneryInstance *scenery_find_instance_by_hash(uint32_t h)
{
    SceneryInstance *r = NULL;
    int              k;

    for (k = 0; k < 2; k++)
        if (present[k] && h == kHash[k])
            r = &inst[k];
    printf("  FindSceneryInstance %08x -> %s\n", (unsigned)h, label(r));
    return r;
}

SceneryInfo *scenery_find_info(uint32_t h)
{
    SceneryInfo *r = NULL;
    int          k;

    for (k = 0; k < 2; k++)
        if (present[k] && h == kHash[k])
            r = &info[k];
    printf("  FindSceneryInfo %08x -> %s\n", (unsigned)h, label(r));
    return r;
}

void emodel_init(eModel *m, uint32_t h)
{
    printf("  Init %s %08x\n", label(m), (unsigned)h);
    m->NameHash = h;
    m->Solid    = &solid_obj;
}

void emodel_uninit(eModel *m)
{
    printf("  UnInit %s\n", label(m));
    m->NameHash = 0;
    m->Solid    = NULL;
}

void emodel_delete(eModel *m, int32_t flags)
{
    printf("  ~eModel %s %d\n", label(m), (int)flags);
}

void eIdentity(bMatrix4 *m)
{
    printf("  eIdentity %s\n", label(m));
    memset(m, 0, sizeof *m);
    m->v0.x = m->v1.y = m->v2.z = m->v3.w = 1.0f;
}

static void render(eModel *m, bMatrix4 *matrix, void *light, uint32_t flags)
{
    printf("  Render %s %s %s %u\n", label(m), label(matrix), label(light),
           (unsigned)flags);
}

TextureInfo *GetTextureInfo(uint32_t h, int use_default)
{
    TextureInfo *r = NULL;
    int          i;

    for (i = 0; i < NUM_SUN_TEXTURES; i++)
        if (h == kSunTextureHashes[i] && (found_mask >> i & 1))
            r = &tex[i];
    if (r == NULL && use_default && has_default)
        r = &tex[5];
    printf("  GetTextureInfo %08x %d -> %s\n", (unsigned)h, use_default,
           label(r));
    return r;
}

// ------------------------------------------------------------ the state

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float from_bits(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static void dump_matrix(const char *name, const bMatrix4 *m)
{
    const float *f = &m->v0.x;
    int          i;

    printf("  %s", name);
    for (i = 0; i < 16; i++)
        printf(" %08x", (unsigned)bits(f[i]));
    printf("\n");
}

static void dump(void)
{
    int i;

    printf("  = sky %08x %s env %08x %s draw %d\n",
           (unsigned)SkydomeModel.NameHash, label(SkydomeModel.Solid),
           (unsigned)SkydomeEnvmapModel.NameHash,
           label(SkydomeEnvmapModel.Solid), (int)DrawSky);
    dump_matrix("skyM", &SkydomeLocalWorld);
    dump_matrix("envM", &SkydomeEnvmapLocalWorld);
    for (i = 0; i < 6; i++)
        printf("%s%08x %s", i ? " " : "  lods ", (unsigned)lod[i].NameHash,
               label(lod[i].Solid));
    printf("\n");
    printf("  sun %s pos %08x %08x %08x tex", label(SunInfo),
           (unsigned)bits(SunPosition.x), (unsigned)bits(SunPosition.y),
           (unsigned)bits(SunPosition.z));
    for (i = 0; i < NUM_SUN_TEXTURES; i++)
        printf(" %s", label(SunTextures[i]));
    printf(" ord");
    for (i = 0; i < 6; i++)
        printf(" %d", tex[i].RenderingOrder);
    printf("\n");
}

static void reset(int draw)
{
    int i;

    SkydomeModel.NameHash       = 0x0bad0001u;
    SkydomeModel.Solid          = &junk_obj;
    SkydomeEnvmapModel.NameHash = 0x0bad0002u;
    SkydomeEnvmapModel.Solid    = &junk_obj;
    for (i = 0; i < 16; i++) {
        (&SkydomeLocalWorld.v0.x)[i]       = from_bits(0x7f000000u + i);
        (&SkydomeEnvmapLocalWorld.v0.x)[i] = from_bits(0x7e000000u + i);
    }
    for (i = 0; i < 6; i++) {
        lod[i].NameHash = 0x1000u + (uint32_t)i;
        lod[i].Solid    = &junk_obj;
    }
    DrawSky       = draw;
    SunInfo       = NULL;
    SunPosition.x = 1.0f;
    SunPosition.y = 2.0f;
    SunPosition.z = 3.0f;
    for (i = 0; i < NUM_SUN_TEXTURES; i++)
        SunTextures[i] = NULL;
}

// ----------------------------------------------------------------- driver

static int hexval(int c)
{
    return c <= '9' ? c - '0' : (c | 0x20) - 'a' + 10;
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE       *fh;
    int         n = 0;

    if (argc < 2 || (fh = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: sky_test scenarios.txt\n");
        return 2;
    }
    printf("DrawSky starts %d\n", (int)DrawSky);
    while (fgets(line, sizeof line, fh)) {
        if (line[0] == 'O') {
            int      k, pr, mask, r[9], j;
            unsigned p[3];

            if (sscanf(line, "O %d %d %d %d %d %d %d %d %d %d %d %d %x %x %x",
                       &k, &pr, &mask, &r[0], &r[1], &r[2], &r[3], &r[4],
                       &r[5], &r[6], &r[7], &r[8], &p[0], &p[1], &p[2]) != 15)
                return 3;
            present[k] = pr;
            memset(&inst[k], 0, sizeof inst[k]);
            memset(&info[k], 0, sizeof info[k]);
            for (j = 0; j < 9; j++)
                inst[k].Rotation[j] = (int16_t)r[j];
            for (j = 0; j < 3; j++)
                inst[k].Position[j] = from_bits(p[j]);
            info[k].NameHash[0] = kHash[k];
            for (j = 0; j < 3; j++)
                info[k].pModel[j] = (mask >> j & 1) ? &lod[3 * k + j] : NULL;
        } else if (line[0] == 'C') {
            int         mis;
            char        hex[1200];
            size_t      i;

            if (sscanf(line, "C %d %1199s", &mis, hex) != 2)
                return 3;
            chunk = (uint8_t *)(((uintptr_t)chunk_raw + 15) & ~(uintptr_t)15)
                  + mis;
            memset(chunk, 0, 512 - 16);
            chunk_len = strlen(hex) / 2;
            for (i = 0; i < chunk_len; i++)
                chunk[i] = (uint8_t)(hexval(hex[2 * i]) << 4
                                     | hexval(hex[2 * i + 1]));
        } else if (line[0] == 'T') {
            int ord, i;

            if (sscanf(line, "T %d %d %d", &found_mask, &has_default, &ord)
                != 3)
                return 3;
            for (i = 0; i < 6; i++)
                tex[i].RenderingOrder = (uint8_t)ord;
        } else if (line[0] == 'S') {
            int  draw, null, v[8], i;
            char ops[64];

            if (sscanf(line, "S %d %d %d %d %d %d %d %d %d %d %63s", &draw,
                       &null, &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6],
                       &v[7], ops) != 11)
                return 3;
            gEModelRenderFn = null ? NULL : render;
            reset(draw);
            printf("scenario %d %s\n", n++, ops);
            for (const char *o = ops; *o; o++) {
                uint32_t id;

                printf(" %c\n", *o);
                switch (*o) {
                case 'I': sky_static_init(); break;
                case 'D': sky_static_close(); break;
                case 'L': SkyLoader(); break;
                case 'U': SkyUnloader(); break;
                case 'a':
                    printf("  -> %d\n", (int)SkyInitModel(
                        &SkydomeModel, &SkydomeLocalWorld, SKY_HASH_SKYDOME));
                    break;
                case 'b':
                    printf("  -> %d\n", (int)SkyInitModel(
                        &SkydomeEnvmapModel, &SkydomeEnvmapLocalWorld,
                        SKY_HASH_SKYDOME_ENVMAP));
                    break;
                case 'c':
                    printf("  -> %d\n", (int)SkyInitModel(
                        &SkydomeModel, &SkydomeLocalWorld, 0x12345678u));
                    break;
                case 'R':
                    for (i = 0; i < 8; i++) {
                        view.ID = v[i];
                        printf("  view %d\n", v[i]);
                        StuffSky(&view);
                    }
                    break;
                case 'S':
                    printf("  -> %d\n", loader_sun(chunk));
                    break;
                case 's':
                    printf("  -> %d\n", unloader_sun(chunk));
                    break;
                case 'X':
                case 'x':
                    // The same chunk, one type along.
                    memcpy(&id, chunk, 4);
                    id ^= 1u;
                    memcpy(chunk, &id, 4);
                    printf("  -> %d\n", *o == 'X' ? loader_sun(chunk)
                                                  : unloader_sun(chunk));
                    id ^= 1u;
                    memcpy(chunk, &id, 4);
                    break;
                case 'T': SunTrackLoader(); break;
                case 't': SunTrackUnloader(); break;
                case 'd': DrawSky = 0; break;
                }
                dump();
            }
        }
    }
    fclose(fh);
    return 0;
}
