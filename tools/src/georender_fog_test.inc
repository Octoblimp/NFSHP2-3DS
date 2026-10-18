// tools/georender_cuts_check.py's fog test, after georender.c's
// georender_fog_fill, cut out of it.
//
// The stubs stand in for citro3d and GSP: C3D_TexInit gives a buffer of
// the texture's size (or fails when told to), and GSPGPU_FlushDataCache
// copies the range it is given into `gpu`, which is what the GPU would
// read. Each fill is held to the fill before TASKS 46 (old_fill) on the
// same fractions: what the GPU reads must be its bytes, and a fill must
// flush exactly when its fractions differ to the bit from the last ones
// the texture took.

static uint64_t s = 0x13198A2E03707344ull;
static uint32_t rnd(void)
{
    s ^= s << 13; s ^= s >> 7; s ^= s << 17;
    return (uint32_t)(s >> 16);
}

static uint8_t gpu[GEO_FOG_TEX_W * 8];
static long    flushes, badFlushes;

void GSPGPU_FlushDataCache(const void* p, uint32_t n)
{
    flushes++;
    if (p != s_texData || n != GEO_FOG_TEX_W * 8) {
        badFlushes++;
        return;
    }
    memcpy(gpu, p, n);
}

// georender_fog_fill as it was before TASKS 46: every texel's fraction
// worked out where it is written, every fill written and flushed.
static void old_fill(uint8_t* p, const float keep[GEO_FOG_STEPS + 1])
{
    int k, m;

    for (k = 0; k < GEO_FOG_TEX_W / 8; k++) {
        for (m = 0; m < 64; m++) {
            int   x = k * 8 + ((m & 1) | (m >> 1 & 2) | (m >> 2 & 4));
            float f = keep[x < GEO_FOG_STEPS ? x : GEO_FOG_STEPS];

            f = f < 0.0f ? 0.0f : f > 1.0f ? 1.0f : f;
            p[k * 64 + m] = (uint8_t)(f * 255.0f + 0.5f);
        }
    }
}

static float any_float(void)
{
    union { uint32_t u; float f; } v;

    v.u = rnd() << 16 ^ rnd();
    return v.f;
}

// A fraction as the fog makes them, 0 to 1 by 128ths, or, now and then,
// one past either end, a -0, a NaN, an infinity or any bits at all.
static float fraction(void)
{
    switch (rnd() % 40) {
    case 0: return -0.0f;
    case 1: return NAN;
    case 2: return INFINITY;
    case 3: return -INFINITY;
    case 4: return -(float)(rnd() % 1000) / 100.0f;
    case 5: return 1.0f + (float)(rnd() % 1000) / 100.0f;
    case 6: return any_float();
    default: return (float)(rnd() % 129) / 128.0f;
    }
}

static GeoFog fog;

int main(void)
{
    float   keep[GEO_FOG_STEPS + 1], last[GEO_FOG_STEPS + 1];
    uint8_t want[GEO_FOG_TEX_W * 8];
    bool    held = false;
    long    fills = 0, same = 0, failed = 0, bad = 0, wantFlushes = 0;
    int     n, j;

    for (j = 0; j <= GEO_FOG_STEPS; j++) {
        keep[j] = fraction();
    }
    for (n = 0; n < 300000; n++) {
        uint32_t r = rnd() % 100;
        bool     ok, differs;

        // Mostly the same fractions again, as a race has them frame to
        // frame; else one changed, a few, or all of them.
        if (r < 55) {
        } else if (r < 70) {
            keep[rnd() % (GEO_FOG_STEPS + 1)] = fraction();
        } else if (r < 75) {
            union { float f; uint32_t u; } v;

            j = (int)(rnd() % (GEO_FOG_STEPS + 1));
            v.f = keep[j];
            v.u ^= 1u << (rnd() % 32);
            keep[j] = v.f;
        } else if (r < 90) {
            int c = 1 + (int)(rnd() % 8);

            while (c--) {
                keep[rnd() % (GEO_FOG_STEPS + 1)] = fraction();
            }
        } else {
            for (j = 0; j <= GEO_FOG_STEPS; j++) {
                keep[j] = fraction();
            }
        }
        // Now and then the texture goes and must be made again, and the
        // making may fail.
        if (rnd() % 5000 == 0) {
            free(fog.tex.data);
            fog.tex.data = NULL;
            s_texData = NULL;
            held = false;
            s_failInit = rnd() % 3 == 0;
        }

        differs = !held || memcmp(last, keep, sizeof last) != 0;
        if (s_failInit && fog.tex.data == NULL) {
            differs = false;
        }
        flushes = 0;
        ok = georender_fog_fill(&fog, keep);
        fills++;
        if (!ok) {
            failed++;
            s_failInit = false;
            if (fog.tex.data != NULL || flushes != 0) {
                if (bad++ < 5) {
                    printf("fill %d: failed with a texture or a flush\n", n);
                }
            }
            continue;
        }
        if (!differs) {
            same++;
        }
        wantFlushes += differs;
        old_fill(want, keep);
        if (flushes != (differs ? 1 : 0)
            || memcmp(gpu, want, sizeof want) != 0
            || memcmp(fog.tex.data, want, sizeof want) != 0) {
            if (bad++ < 5) {
                printf("fill %d: %ld flushes for %s fractions, the GPU's "
                       "bytes %s, the texture's %s\n",
                       n, flushes, differs ? "new" : "the same",
                       memcmp(gpu, want, sizeof want) ? "differ" : "match",
                       memcmp(fog.tex.data, want, sizeof want) ? "differ"
                                                               : "match");
            }
        }
        memcpy(last, keep, sizeof last);
        held = true;
    }
    printf("%ld fills, %ld the same as the last, %ld made no texture, "
           "%ld flushes wanted, %ld flushes out of range\n",
           fills, same, failed, wantFlushes, badFlushes);
    bad += badFlushes;
    printf("%ld fills, %ld differ\n", fills, bad);
    return bad != 0;
}
