// tools/trackview_cuts_check.py's texture test, after trackview.c's
// tex_bucket and find_texture, load_texture's append (as append) and
// forget_all's emptying (as reset), cut out of it.

static uint64_t s = 0x243F6A8885A308D3ull;
static uint32_t rnd(void)
{
    s ^= s << 13; s ^= s >> 7; s ^= s << 17;
    return (uint32_t)(s >> 16);
}

// The scan from the front, as find_texture was before TASKS 46.
static TrackTex* scan(TrackView* v, const TextureInfo* info)
{
    int i;

    for (i = 0; i < v->numTextures; i++) {
        if (v->texture[i].info == info) {
            return &v->texture[i];
        }
    }
    return NULL;
}

#define POOLS 12
#define POOL_MAX 600

static TrackTex list[TRACKVIEW_MAX_TEXTURES];
static TrackView view;

int main(void)
{
    const TextureInfo* pool[POOLS];
    int                poolSize[POOLS];
    long               finds = 0, appends = 0, full = 0, resets = 0;
    long               bad = 0, lastUsed = 0, peak = 0;
    int                n, p;

    for (p = 0; p < POOLS; p++) {
        poolSize[p] = 1 + (int)(rnd() % POOL_MAX);
        pool[p] = (const TextureInfo*)calloc((size_t)poolSize[p],
                                             sizeof(TextureInfo));
    }
    view.texture = list;
    for (n = 0; n < 4000000; n++) {
        const TextureInfo* info;
        TrackTex *       a, *b;
        uint32_t           r = rnd();

        if (r % 50000 == 0) {
            reset(&view);
            resets++;
            continue;
        }
        p = (int)(rnd() % POOLS);
        info = rnd() % 997 == 0 ? NULL : &pool[p][rnd() % poolSize[p]];
        a = find_texture(&view, info);
        b = scan(&view, info);
        finds++;
        if (a != b) {
            if (bad++ < 5) {
                printf("find %p at %d entries: %p, the scan %p\n",
                       (const void*)info, view.numTextures, (void*)a,
                       (void*)b);
            }
        }
        if (!b && (r & 1)) {
            // load_texture's append, then the entry is found as itself.
            int was = view.numTextures;

            a = append(&view, info);
            if (a == NULL) {
                if (was != TRACKVIEW_MAX_TEXTURES) {
                    bad++;
                }
                full++;
            } else {
                appends++;
                if (a != &list[was] || find_texture(&view, info) != a
                    || view.numTextures != was + 1) {
                    if (bad++ < 5) {
                        printf("append %d: entry %p\n", was, (void*)a);
                    }
                }
            }
        }
        if (view.numTextures > peak) {
            peak = view.numTextures;
        }
        lastUsed += view.texBucket[TRACKVIEW_TEX_BUCKETS - 1] != 0;
    }
    printf("%ld finds, %ld appends, %ld full, %ld resets, peak %ld, "
           "last bucket used %ld times, %ld differ\n",
           finds, appends, full, resets, peak, lastUsed, bad);
    return bad != 0;
}
