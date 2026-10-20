// Harness for tools/weather_check.py: runs the checker's scenarios on
// weatherman.c and efog.c and prints what the model prints for the image.
// eGetView, eFrameCounter and WorldTimeFrames (which only the retail
// Heavy Fog egg's branch reads: stomper_check.py's) are the harness's, and
// the seam eAttachFog
// hands each palette to logs it with its mode's ALPHA_1; after each step
// the lists and the regions' links are dumped. See the checker's docstring.
//
//     weather_test scenarios.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "efog.h"
#include "eview.h"
#include "weatherman.h"

uint32_t eFrameCounter;
int32_t  WorldTimeFrames;

#define MAX_REGIONS 24
#define MAX_POS     16
#define NUM_VIEWS   5

static eView         views[EVIEW_NUM_VIEWS];
static eRenderTarget rts[EVIEW_NUM_VIEWS];
static Camera        cams[EVIEW_NUM_VIEWS];

eView *eGetView(int32_t id)
{
    return &views[id];
}

// ------------------------------------------------------------ the scenario

typedef struct {
    int32_t  type;
    uint32_t group, colour;
    uint32_t start, x, y, z, radius, intensity, far;
} Reg;

static int      mis, version, nregs, npos;
static uint32_t cid;
static Reg      regs[MAX_REGIONS];
static int32_t  tw_use, tw_r, tw_g, tw_b;
static uint32_t tw_fog, tw_start;
static int32_t  g_draw, g_mode1, g_mode2, g_enable;
static uint32_t g_power;
static int32_t  v_active[NUM_VIEWS], v_rt[NUM_VIEWS];
static uint32_t v_pos[NUM_VIEWS][3], v_counter[NUM_VIEWS];
static uint32_t frame0;
static uint32_t pos[MAX_POS][3];

static _Alignas(16) uint8_t chunk_raw[64 + MAX_REGIONS * sizeof(WeatherRegion)];
static uint8_t       *chunk;
static WeatherRegion *region;           // the pack's first
static WeatherQuery   scratch_q;
static uint32_t       scratch_pal[256];

static float fbits(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static uint32_t bitsf(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

// ------------------------------------------------------------ the labels

static const char *label(const void *p)
{
    static char buf[8][32];
    static int  k;
    char       *b = buf[k++ & 7];
    int         i;

    if (p == NULL)
        return "null";
    for (i = 0; i < WEATHER_NUM_TYPES; i++) {
        if (p == &WeatherRegionLists[i]) {
            snprintf(b, 32, "L%d", i);
            return b;
        }
    }
    if (p == &WeatherRegionInactiveList)
        return "Li";
    for (i = 0; i < nregs; i++) {
        if (p == &region[i].Node) {
            snprintf(b, 32, "r%d", i);
            return b;
        }
        if (p == region[i].Name) {
            snprintf(b, 32, "n%d", i);
            return b;
        }
    }
    for (i = 0; i < 4; i++) {
        if (p == FogPalette[i]) {
            snprintf(b, 32, "fog%d", i);
            return b;
        }
    }
    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        if (p == &CachedWeatherQueries[i]) {
            snprintf(b, 32, "cache%d", i);
            return b;
        }
    }
    if (p == scratch_pal)
        return "pal";
    return "x";
}

static int is_node(const bNode *n)
{
    int i;

    for (i = 0; i < WEATHER_NUM_TYPES; i++)
        if (n == &WeatherRegionLists[i])
            return 1;
    if (n == &WeatherRegionInactiveList)
        return 1;
    for (i = 0; i < nregs; i++)
        if (n == &region[i].Node)
            return 1;
    return 0;
}

// ------------------------------------------------------------- the dumps

static void walk(const char *name, bNode *head, int back)
{
    char   line[1024];
    size_t at = 0;
    bNode *n  = back ? head->prev : head->next;
    int    steps;

    at += (size_t)snprintf(line, sizeof line, "  %s%s", name,
                           back ? "<" : ">");
    for (steps = 0; steps < 32 && n != head; steps++) {
        at += (size_t)snprintf(line + at, sizeof line - at, " %s",
                               label(n));
        if (!is_node(n))
            break;
        n = back ? n->prev : n->next;
    }
    if (steps == 32)
        at += (size_t)snprintf(line + at, sizeof line - at, " ...");
    printf("%s\n", line);
}

static void dump_lists(void)
{
    static const char *names[5] = { "L0", "L1", "L2", "L3", "Li" };
    int                i;

    for (i = 0; i < 5; i++) {
        bNode *h = i < 4 ? &WeatherRegionLists[i] : &WeatherRegionInactiveList;

        walk(names[i], h, 0);
        walk(names[i], h, 1);
    }
    printf("  nodes");
    for (i = 0; i < nregs; i++)
        printf(" %s/%s", label(region[i].Node.next),
               label(region[i].Node.prev));
    printf("\n");
}

static void dump_query(const WeatherQuery *q)
{
    printf("  q %08x %08x %08x %08x c %08x s %08x rs %08x hs %08x\n",
           bitsf(q->Rain), bitsf(q->Fog), bitsf(q->Snow), bitsf(q->Wind),
           q->FogColour, bitsf(q->FogStart), bitsf(q->RootScale),
           bitsf(q->HitScale));
    printf("  R %s %08x %08x %08x 0 %s %08x %08x %08x 1 %s %08x %08x %08x"
           " 2 %s %08x %08x %08x\n",
           label(q->RegionR), q->RegionR_Colour, bitsf(q->RegionR_FogStart),
           bitsf(q->RegionR_Scale), label(q->Region0), q->Region0_Colour,
           bitsf(q->Region0_FogStart), bitsf(q->Region0_Scale),
           label(q->Region1), q->Region1_Colour, bitsf(q->Region1_FogStart),
           bitsf(q->Region1_Scale), label(q->Region2), q->Region2_Colour,
           bitsf(q->Region2_FogStart), bitsf(q->Region2_Scale));
}

static void dump_palette(const char *name, const uint32_t *p)
{
    int i, j;

    for (i = 0; i < 256; i += 32) {
        printf("  %s %3d", name, i);
        for (j = 0; j < 32; j++)
            printf(" %08x", p[i + j]);
        printf("\n");
    }
}

// ------------------------------------------------------------- the seam

static void attach(eView *view, const uint32_t *palette,
                   const FogModeInfo *mode)
{
    uint64_t alpha = 0;

    if (mode != NULL)
        alpha = (uint64_t)mode->AlphaA | (uint64_t)mode->AlphaB << 2
              | (uint64_t)mode->AlphaC << 4 | (uint64_t)mode->AlphaD << 6
              | (uint64_t)mode->AlphaFix << 32;
    printf("  attach view %d %s alpha %llx\n", view->ID, label(palette),
           (unsigned long long)alpha);
}

// ------------------------------------------------------------- the setup

static void build_chunk(void)
{
    WeatherRegionPack *pack;
    int                i;

    memset(chunk_raw, 0x5a, sizeof chunk_raw);
    chunk = chunk_raw + mis;
    memcpy(chunk, &cid, 4);
    {
        uint32_t size = (uint32_t)(24 + nregs * 128);

        memcpy(chunk + 4, &size, 4);
    }
    pack = (WeatherRegionPack *)(((uintptr_t)chunk + 8 + 15)
                                 & ~(uintptr_t)15);
    pack->Unnamed[0] = 0;
    pack->Unnamed[1] = 0;
    pack->Version = version;
    pack->NumRegions = nregs;
    region = (WeatherRegion *)(pack + 1);
    for (i = 0; i < nregs; i++) {
        WeatherRegion *r = &region[i];

        memset(r, 0, sizeof *r);
        r->Node.next = &r->Node;
        r->Node.prev = &r->Node;
        r->NameHash = 0x1000u + (uint32_t)i;
        r->GroupNameHash = regs[i].group;
        snprintf(r->Name, sizeof r->Name, "REGION%02d", i);
        snprintf(r->GroupName, sizeof r->GroupName, "G%08x", regs[i].group);
        r->Type = regs[i].type;
        r->FogColour = regs[i].colour;
        r->FogStart = fbits(regs[i].start);
        r->Parameter1 = 0.5f;
        r->PositionX = fbits(regs[i].x);
        r->PositionY = fbits(regs[i].y);
        r->PositionZ = fbits(regs[i].z);
        r->Radius = fbits(regs[i].radius);
        r->Intensity = fbits(regs[i].intensity);
        r->FarFalloffStart = fbits(regs[i].far);
    }
}

static void reset(void)
{
    int i;

    for (i = 0; i < WEATHER_NUM_TYPES; i++) {
        WeatherRegionLists[i].next = &WeatherRegionLists[i];
        WeatherRegionLists[i].prev = &WeatherRegionLists[i];
    }
    WeatherRegionInactiveList.next = &WeatherRegionInactiveList;
    WeatherRegionInactiveList.prev = &WeatherRegionInactiveList;
    memset(CachedWeatherQueries, 0, sizeof CachedWeatherQueries);
    memset(FogPalette, 0, sizeof FogPalette);
    memset(DepthUpperPalette, 0, sizeof DepthUpperPalette);
    memset(DepthLowerPalette, 0, sizeof DepthLowerPalette);
    WeatherUseTweakerValues = tw_use;
    WeatherFog = fbits(tw_fog);
    WeatherFogStart = fbits(tw_start);
    WeatherFogColourR = tw_r;
    WeatherFogColourG = tw_g;
    WeatherFogColourB = tw_b;
    DrawFog = g_draw;
    FogMode1 = g_mode1;
    FogMode2 = g_mode2;
    EnableDepthIntoAlpha = g_enable;
    FogPower = fbits(g_power);
    eFrameCounter = frame0;
    memset(views, 0, sizeof views);
    memset(rts, 0, sizeof rts);
    memset(cams, 0, sizeof cams);
    for (i = 0; i < NUM_VIEWS; i++) {
        views[i].ID = i;
        views[i].Active = (uint8_t)v_active[i];
        views[i].pRenderTarget0 = &rts[i];
        views[i].pCamera = &cams[i];
        views[i].WeatherQueryCounter = v_counter[i];
        rts[i].Active = (uint32_t)v_rt[i];
        cams[i].CurrentKey.Position.x = fbits(v_pos[i][0]);
        cams[i].CurrentKey.Position.y = fbits(v_pos[i][1]);
        cams[i].CurrentKey.Position.z = fbits(v_pos[i][2]);
    }
    for (i = 0; i < 256; i++)
        scratch_pal[i] = 0xdead0000u + (uint32_t)i;
    gEFogAttachFn = attach;
    build_chunk();
}

// ------------------------------------------------------------- the ops

static const uint32_t kZs[] = {
    0, 1, 16, 63, 64, 100, 575, 576, 640, 1000, 4095, 4096, 8000, 12345,
    16320, 16383, 16384, 30000, 65535,
};

static void pica(int m)
{
    const FogModeInfo *mode = m < 4 ? &FogModeInfos[m] : NULL;
    uint32_t           colour = 0x12345678u;
    int                ok = efog_colour(scratch_pal, mode, &colour);
    size_t             i;

    printf("  colour %d %06x\n", ok, colour);
    printf("  keep");
    for (i = 0; i < sizeof kZs / sizeof kZs[0]; i++)
        printf(" %u:%u:%08x", kZs[i], efog_depth_alpha(kZs[i]),
               bitsf(efog_keep(scratch_pal, mode, kZs[i])));
    printf("\n");
}

static void fpow_tests(void)
{
    static const float xy[][2] = {
        { 0.0f, 4.6f }, { 0.5f, 4.6f }, { 1.0f, 4.6f }, { 0.01f, 2.0f },
        { 2.0f, 0.5f }, { -1.0f, 3.0f }, { 1e-3f, 1.0f }, { 100.0f, 2.0f },
        { 0.25f, 0.0f }, { 1e30f, 10.0f }, { 0.75f, 4.5999999f },
        { 0.9f, -2.0f }, { 0.3f, 3.1f }, { 0.35f, 1.7f }, { 0.42f, 1.1f },
    };
    size_t i;

    printf("  fpow");
    for (i = 0; i < sizeof xy / sizeof xy[0]; i++)
        printf(" %08x", bitsf(fpow(xy[i][0], xy[i][1])));
    printf("\n");
}

static void remap_test(void)
{
    uint32_t src[256], dst[256];
    int      i;

    for (i = 0; i < 256; i++) {
        src[i] = (uint32_t)i | (uint32_t)(255 - i) << 8 | 0xab000000u;
        dst[i] = 0;
    }
    RemapLinearIntoClut8(dst, src);
    dump_palette("remap", dst);
}

static void get_palettes(void)
{
    static const int32_t ids[] = {
        -1, 0, 1, 2, 3, 4, 5, 9, 0x7fffffff, (int32_t)0x80000000u,
    };
    eView  v;
    size_t i;

    memset(&v, 0, sizeof v);
    printf("  palettes");
    for (i = 0; i < sizeof ids / sizeof ids[0]; i++) {
        v.ID = ids[i];
        printf(" %s", label(GetFogPalette(&v)));
    }
    printf("\n");
}

static void mode_infos(void)
{
    int m;

    for (m = 0; m < 4; m++) {
        const FogModeInfo *f = &FogModeInfos[m];

        printf("  mode %d %d %d %d %d %d %08x %08x %08x %08x %08x %08x\n", m,
               f->AlphaA, f->AlphaB, f->AlphaC, f->AlphaD, f->AlphaFix,
               bitsf(f->Start), bitsf(f->End), bitsf(f->R), bitsf(f->G),
               bitsf(f->B), bitsf(f->A));
    }
}

static void run_op(const char *op)
{
    int      a = 0, b = 0;
    uint32_t h = 0;

    printf(" %s\n", op);
    switch (op[0]) {
    case 'I':
        mode_infos();
        break;
    case 'L':
        printf("  -> %d\n", loader_weather_man(chunk));
        break;
    case 'U':
        printf("  -> %d\n", unloader_weather_man(chunk));
        break;
    case 'X':
    case 'x': {
        uint32_t c;

        memcpy(&c, chunk, 4);
        c ^= 1u;
        memcpy(chunk, &c, 4);
        printf("  -> %d\n", op[0] == 'X' ? loader_weather_man(chunk)
                                         : unloader_weather_man(chunk));
        c ^= 1u;
        memcpy(chunk, &c, 4);
        break;
    }
    case 'A':
        WeatherAddRegion(&region[atoi(op + 1)]);
        break;
    case '-':
        WeatherRemoveRegion(&region[atoi(op + 1)]);
        break;
    case 's':
        sscanf(op + 1, "%d:%d", &a, &b);
        WeatherSetRegionState(&region[a], b);
        break;
    case 'g':
        sscanf(op + 1, "%x:%d", &h, &b);
        WeatherSetGroupState(h, b);
        break;
    case 'q':
        a = atoi(op + 1);
        memset(&scratch_q, 0xa5, sizeof scratch_q);
        {
            bVector3 p;

            p.x = fbits(pos[a][0]);
            p.y = fbits(pos[a][1]);
            p.z = fbits(pos[a][2]);
            p.pad = 0.0f;
            WeatherManQuery(&scratch_q, &p);
        }
        dump_query(&scratch_q);
        break;
    case 'Q': {
        WeatherQuery *q;

        a = atoi(op + 1);
        q = eview_get_weather_query(&views[a]);
        printf("  -> %s counter %u\n", label(q),
               views[a].WeatherQueryCounter);
        dump_query(q);
        break;
    }
    case '+':
        eFrameCounter++;
        break;
    case 'P':
        a = atoi(op + 1);
        CreateFogPalette(&views[a], scratch_pal);
        dump_palette("pal", scratch_pal);
        break;
    case 'N':
        CreateFogPalette(NULL, scratch_pal);
        dump_palette("pal", scratch_pal);
        break;
    case 'n':
        CreateFogPalette(&views[atoi(op + 1)], NULL);
        break;
    case 'G':
        get_palettes();
        break;
    case 'Z':
        printf("  -> %d\n", eattach_depth_into_alpha());
        dump_palette("upper", DepthUpperPalette);
        dump_palette("lower", DepthLowerPalette);
        break;
    case 'F':
        printf("  -> %d\n", eattach_fog());
        dump_palette("fog0", FogPalette[0]);
        dump_palette("fog1", FogPalette[1]);
        break;
    case 'K':
        pica(atoi(op + 1));
        break;
    case 'p':
        fpow_tests();
        break;
    case 'm':
        remap_test();
        break;
    case 'v':
        // A view's active flags, changed mid-scenario: v<id>:<view>:<rt>.
        {
            int c = 0;

            sscanf(op + 1, "%d:%d:%d", &a, &b, &c);
            views[a].Active = (uint8_t)b;
            rts[a].Active = (uint32_t)c;
        }
        break;
    default:
        printf("  ? %s\n", op);
        break;
    }
    dump_lists();
}

int main(int argc, char **argv)
{
    FILE *f;
    char  line[4096];
    int   scenario = 0;

    if (argc < 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: weather_test scenarios.txt\n");
        return 2;
    }
    // The globals as the port starts them, and the lists.
    printf("start draw %d modes %d %d power %08x enable %d tweak %d %08x %08x"
           " %d %d %d\n", DrawFog, FogMode1, FogMode2, bitsf(FogPower),
           EnableDepthIntoAlpha, WeatherUseTweakerValues, bitsf(WeatherFog),
           bitsf(WeatherFogStart), WeatherFogColourR, WeatherFogColourG,
           WeatherFogColourB);
    printf("lists %s %s %s %s heads", label(WeatherRainList),
           label(WeatherFogList), label(WeatherSnowList),
           label(WeatherWindList));
    {
        int i;

        for (i = 0; i < 5; i++) {
            bNode *h = i < 4 ? &WeatherRegionLists[i]
                             : &WeatherRegionInactiveList;

            printf(" %s/%s", label(h->next), label(h->prev));
        }
    }
    printf("\n");
    while (fgets(line, sizeof line, f)) {
        char *p = line + 2;

        line[strcspn(line, "\r\n")] = '\0';
        switch (line[0]) {
        case 'C':
            nregs = 0;
            npos = 0;
            sscanf(p, "%d %x %d", &mis, &cid, &version);
            break;
        case 'R': {
            Reg *r = &regs[nregs++];

            sscanf(p, "%d %x %x %x %x %x %x %x %x %x", &r->type, &r->group,
                   &r->colour, &r->start, &r->x, &r->y, &r->z, &r->radius,
                   &r->intensity, &r->far);
            break;
        }
        case 'T':
            sscanf(p, "%d %x %x %d %d %d", &tw_use, &tw_fog, &tw_start,
                   &tw_r, &tw_g, &tw_b);
            break;
        case 'M':
            sscanf(p, "%d %d %d %d %x", &g_draw, &g_mode1, &g_mode2,
                   &g_enable, &g_power);
            break;
        case 'V': {
            int i;

            sscanf(p, "%d", &i);
            sscanf(p, "%*d %d %d %x %x %x %u", &v_active[i], &v_rt[i],
                   &v_pos[i][0], &v_pos[i][1], &v_pos[i][2], &v_counter[i]);
            break;
        }
        case 'F':
            sscanf(p, "%u", &frame0);
            break;
        case 'X':
            sscanf(p, "%x %x %x", &pos[npos][0], &pos[npos][1],
                   &pos[npos][2]);
            npos++;
            break;
        case 'S': {
            char *tok;

            reset();
            printf("scenario %d %s\n", scenario++, p);
            for (tok = strtok(p, " "); tok; tok = strtok(NULL, " "))
                run_op(tok);
            break;
        }
        default:
            break;
        }
    }
    fclose(f);
    return 0;
}
