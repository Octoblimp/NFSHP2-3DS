// trackview_sort_test.inc -- holds sort_deferred to what it replaced,
// qsort of the entries themselves with compare_deferred (TASKS 46).
//
// trackview_cuts_check.py puts TrackDeferred, compare_deferred,
// compare_deferred_at and sort_deferred above this. Each round fills a
// list of random entries -- unsorted and sorted ones, a few orders and
// texture uses, depths from a short list with ties, -0, the infinities
// and NaNs among them, and the frame's seqs in a random order -- sorts one
// copy the old way and the other the new, and compares every field.

static uint32_t s_rng = 0x2468ace1u;

static uint32_t rnd(void)
{
    s_rng ^= s_rng << 13;
    s_rng ^= s_rng >> 17;
    s_rng ^= s_rng << 5;
    return s_rng;
}

static float rnd_depth(int nanOk)
{
    static const float kDepths[] = {
        0.0f, -0.0f, 1.0f, -1.0f, 2.5f, 2.5f, 100.0f, 1e-30f, 3.4e38f,
    };
    uint32_t r = rnd() % 16;

    if (r < 9) {
        return kDepths[r];
    }
    if (r == 9) {
        return nanOk ? NAN : 7.0f;
    }
    if (r == 10) {
        return (rnd() & 1) ? INFINITY : -INFINITY;
    }
    return (float)(int32_t)(rnd() % 2001 - 1000) * 0.125f;
}

static int same(const TrackDeferred* a, const TrackDeferred* b)
{
    return memcmp(&a->modelView, &b->modelView, sizeof a->modelView) == 0
        && a->light == b->light
        && memcmp(&a->depth, &b->depth, sizeof a->depth) == 0
        && a->solid == b->solid && a->batch == b->batch
        && a->order == b->order && a->sorted == b->sorted
        && a->texUse == b->texUse && a->seq == b->seq
        && a->flags == b->flags && a->strip == b->strip
        && a->sprites == b->sprites;
}

static TrackView     s_view;
static TrackDeferred s_old[TRACKVIEW_MAX_DEFERRED];
static uint16_t      s_seqs[TRACKVIEW_MAX_DEFERRED];

int main(void)
{
    long rounds = 0, entries = 0, nans = 0, differ = 0;
    int  round;

    for (round = 0; round < 40000; round++) {
        int n, i, k, orders, uses, nanOk;

        // Mostly short lists, as a race's are, some to the end.
        switch (rnd() % 8) {
        case 0: n = (int)(rnd() % 3); break;
        case 1: n = TRACKVIEW_MAX_DEFERRED - (int)(rnd() % 3); break;
        case 2: n = (int)(rnd() % TRACKVIEW_MAX_DEFERRED) + 1; break;
        default: n = (int)(rnd() % 200) + 1; break;
        }
        if (n > TRACKVIEW_MAX_DEFERRED) {
            n = TRACKVIEW_MAX_DEFERRED;
        }
        orders = (int)(rnd() % 4) + 1;
        uses   = (int)(rnd() % 40) + 1;
        nanOk  = (rnd() % 4) == 0;
        // A frame's seqs, from wherever it had got to, shuffled.
        k = (int)(rnd() % 40000);
        for (i = 0; i < n; i++) {
            s_seqs[i] = (uint16_t)(k + i);
        }
        for (i = n - 1; i > 0; i--) {
            int      j = (int)(rnd() % (uint32_t)(i + 1));
            uint16_t t = s_seqs[i];

            s_seqs[i] = s_seqs[j];
            s_seqs[j] = t;
        }
        memset(s_view.deferred, 0, sizeof s_view.deferred);
        for (i = 0; i < n; i++) {
            TrackDeferred* d = &s_view.deferred[i];
            int            m;

            for (m = 0; m < 16; m++) {
                d->modelView.m[m] = (float)(rnd() % 1000);
            }
            d->light   = (const void*)(uintptr_t)(rnd() % 7 * 16);
            d->depth   = rnd_depth(nanOk);
            d->solid   = (uint16_t)rnd();
            d->batch   = (uint8_t)rnd();
            d->order   = (uint8_t)(rnd() % (uint32_t)orders);
            d->sorted  = (rnd() & 1) != 0;
            d->texUse  = (uint16_t)(rnd() % (uint32_t)uses);
            d->seq     = s_seqs[i];
            d->flags   = (uint16_t)rnd();
            d->strip   = (int16_t)((rnd() & 3) ? -1 : (int)(rnd() % 100));
            d->sprites = (int16_t)((rnd() & 3) ? -1 : (int)(rnd() % 100));
            nans += d->depth != d->depth;
        }
        // Half the time, the kept tail of an earlier sort, as the second
        // call of a pair finds it.
        if (rnd() & 1) {
            qsort(s_view.deferred, (size_t)n, sizeof s_view.deferred[0],
                  compare_deferred);
        }
        s_view.numDeferred = n;
        memcpy(s_old, s_view.deferred, sizeof s_old[0] * (size_t)n);

        qsort(s_old, (size_t)n, sizeof s_old[0], compare_deferred);
        sort_deferred(&s_view);

        for (i = 0; i < n; i++) {
            if (!same(&s_old[i], &s_view.deferred[i])) {
                if (differ < 5) {
                    printf("round %d: entry %d of %d differs (seq %u, "
                           "not %u)\n", round, i, n,
                           (unsigned)s_view.deferred[i].seq,
                           (unsigned)s_old[i].seq);
                }
                differ++;
                break;
            }
        }
        if (s_view.numDeferred != n) {
            differ++;
        }
        rounds++;
        entries += n;
    }
    printf("%ld lists, %ld entries, %ld NaN depths, %ld differ\n",
           rounds, entries, nans, differ);
    return differ != 0;
}
