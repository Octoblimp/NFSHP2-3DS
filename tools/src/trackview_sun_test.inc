// tools/trackview_cuts_check.py's sun test, after trackview.c's
// read_sun_rect and what it calls, cut out of it.
//
// The loop as it was before TASKS 46 (trackview.c at 009bbda), with its
// own copy of tiled_index.
static uint32_t old_tiled_index(int x, int y)
{
    uint32_t bx = (uint32_t)(239 - y);
    uint32_t by = (uint32_t)x;
    uint32_t m  = (bx & 1u) | ((by & 1u) << 1) | ((bx & 2u) << 1)
                | ((by & 2u) << 2) | ((bx & 4u) << 2) | ((by & 4u) << 3);

    return ((by >> 3) * (240u / 8u) + (bx >> 3)) * 64u + m;
}

static int old_read(const SunRect* q, const uint32_t* depth)
{
    int sky = 0;
    int i, j;

    for (j = 0; j < q->h; j++) {
        for (i = 0; i < q->w; i++) {
            int      px = q->x + i;
            int      py = q->y + j;
            uint32_t z  = 0xffffffu;

            // StuffSun keeps the rect on the target; a target under
            // 33 across does not, and none of what is off it counts.
            if (px >= 0 && py >= 0 && px < q->targetW
                && py < q->targetH) {
                float sx, sy;
                int   ix, iy;

                target_to_screen((float)px + 0.5f, (float)py + 0.5f,
                                 q->targetW, q->targetH, q->aspX,
                                 q->aspY, &sx, &sy);
                ix = (int)floorf(sx);
                iy = (int)floorf(sy);
                ix = ix < 0 ? 0 : ix > 399 ? 399 : ix;
                iy = iy < 0 ? 0 : iy > 239 ? 239 : iy;
                z  = gs_z(depth[old_tiled_index(ix, iy)] & 0xffffffu);
                if (z < 2) {
                    sky++;
                }
            }
            q->dst[j * q->w + i] = z;
        }
    }
    return sky;
}

static uint64_t s = 0x243F6A8885A308D3ull;
static uint32_t rnd(void)
{
    s ^= s << 13; s ^= s >> 7; s ^= s << 17;
    return (uint32_t)(s >> 16);
}

static uint32_t depth[240 * 400];
static uint32_t dst_old[1024], dst_new[1024];

int main(void)
{
    static const int widths[] = { 400, 512, 256, 320, 33, 32, 20, 1, 640 };
    static const int heights[] = { 240, 256, 224, 128, 33, 16, 1, 480 };
    long rects = 0, pixels = 0, bad = 0, sky = 0, offs = 0;
    int n, k;
    uint32_t x, y;

    // tiled_index against its old self over the whole screen and past it.
    for (y = 0; y < 300; y++)
        for (x = 0; x < 500; x++)
            if (tiled_index((int)x - 50, (int)y - 30)
                != old_tiled_index((int)x - 50, (int)y - 30))
                bad++;
    for (n = 0; n < 400000; n++) {
        SunRect q;
        int so, sn;

        if (n % 2000 == 0) {
            // A new buffer: sky, the near and far, and the rest.
            for (k = 0; k < 240 * 400; k++) {
                uint32_t r = rnd();
                depth[k] = (r & 3) == 0 ? 0 : (r & 3) == 1 ? (rnd() & 3)
                         : (r & 3) == 2 ? 0xff000000u | (rnd() & 0xffffff)
                         : rnd() ^ (rnd() << 16);
            }
        }
        q.targetW = rnd() % 4 ? widths[rnd() % 9] : 1 + (int)(rnd() % 700);
        q.targetH = rnd() % 4 ? heights[rnd() % 8] : 1 + (int)(rnd() % 500);
        q.aspX = rnd() % 3 ? 1.0f : 0.25f + (float)(rnd() % 1000) / 400.0f;
        q.aspY = rnd() % 3 ? 1.0f : 0.25f + (float)(rnd() % 1000) / 400.0f;
        if (rnd() % 8 == 0) {
            q.w = 1 + (int)(rnd() % 1024);
            q.h = 1024 / q.w;
        } else {
            q.w = 1 + (int)(rnd() % 32);
            q.h = 1 + (int)(rnd() % 32);
        }
        q.x = (int)(rnd() % (unsigned)(q.targetW + 80)) - 40;
        q.y = (int)(rnd() % (unsigned)(q.targetH + 80)) - 40;
        memset(dst_old, 0xab, sizeof dst_old);
        memset(dst_new, 0xcd, sizeof dst_new);
        q.dst = dst_old;
        so = old_read(&q, depth);
        q.dst = dst_new;
        sn = read_sun_rect(&q, depth);
        if (so != sn || memcmp(dst_old, dst_new, sizeof(uint32_t) * q.w * q.h)) {
            if (bad++ < 5)
                printf("rect %d,%d %dx%d on %dx%d asp %g %g: sky %d %d\n",
                       q.x, q.y, q.w, q.h, q.targetW, q.targetH, q.aspX,
                       q.aspY, so, sn);
        }
        rects++;
        pixels += q.w * q.h;
        sky += so;
        for (k = 0; k < q.w * q.h; k++)
            offs += dst_old[k] == 0xffffffu;
    }
    printf("%ld rects, %ld pixels (%ld under 2, %ld off or far), %ld differ\n",
           rects, pixels, sky, offs, bad);
    return bad != 0;
}
