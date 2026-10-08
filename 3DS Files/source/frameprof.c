// frameprof -- see frameprof.h.

#include "frameprof.h"

#include <stdio.h>
#include <string.h>

// EE ticks in a millisecond and in the second a line covers.
#define FRAMEPROF_TICKS_PER_MS  (BTICKER_RATE_HZ / 1000u)
#define FRAMEPROF_LINE_TICKS    ((uint64_t)BTICKER_RATE_HZ)

// The sums' slots for the stages either side of the stamped ones.
#define FRAMEPROF_PREP          FRAMEPROF_STAMPED
#define FRAMEPROF_SUBMIT        (FRAMEPROF_STAMPED + 1)

FrameProfTicks FrameProfDraw;

void frameprof_reset(FrameProf *fp)
{
    memset(fp, 0, sizeof *fp);
}

void frameprof_begin_draw(uint32_t sync, uint32_t gpu, uint32_t draw)
{
    memset(&FrameProfDraw, 0, sizeof FrameProfDraw);
    FrameProfDraw.sync = sync;
    FrameProfDraw.gpu = gpu;
    FrameProfDraw.draw = draw;
}

void frameprof_add(FrameProf *fp, const MainLoopTimingStats *t,
                   float c3dCpuMs, float c3dGpuMs)
{
    const FrameProfTicks *d = &FrameProfDraw;
    uint32_t frame = t->LimitFrameRate - t->StartTime;
    uint32_t prev = d->draw;
    int s;

    fp->phase[FRAMEPROF_SOUND]    += t->UpdateSound - t->StartTime;
    fp->phase[FRAMEPROF_FLOW]     += t->ServiceGameFlow - t->UpdateSound;
    fp->phase[FRAMEPROF_RACE]     += t->GenerateJoyEvents
                                     - t->ServiceGameFlow;
    fp->phase[FRAMEPROF_WORLD]    += t->WorldDoTimestep
                                     - t->GenerateJoyEvents;
    fp->phase[FRAMEPROF_CAMERAS]  += t->UpdateCameraMovers
                                     - t->WorldDoTimestep;
    fp->phase[FRAMEPROF_DRAW]     += (d->sync - t->UpdateCameraMovers)
                                     + (t->DisplayFrame - d->draw);
    fp->phase[FRAMEPROF_VSYNC]    += d->gpu - d->sync;
    fp->phase[FRAMEPROF_GPU_WAIT] += d->draw - d->gpu;
    fp->phase[FRAMEPROF_LOADS]    += t->LimitFrameRate - t->DisplayFrame;

    fp->stage[FRAMEPROF_PREP] += d->sync - t->UpdateCameraMovers;
    for (s = 0; s < FRAMEPROF_STAMPED; s++) {
        uint32_t end = d->end[s] != 0 ? d->end[s] : prev;

        fp->stage[s] += end - prev;
        prev = end;
    }
    fp->stage[FRAMEPROF_SUBMIT] += t->DisplayFrame - prev;
    fp->jukeboxDecode += d->jukeboxDecode;
    fp->jukeboxRead += d->jukeboxRead;
    for (s = 0; s < 3 * FRAMEPROF_M_COUNT; s++)
        fp->models[s / FRAMEPROF_M_COUNT][s % FRAMEPROF_M_COUNT] +=
            d->models[s / FRAMEPROF_M_COUNT][s % FRAMEPROF_M_COUNT];
    for (s = 0; s < FRAMEPROF_C_COUNT; s++)
        fp->cars[s] += d->cars[s];

    fp->total += frame;
    if (frame > fp->worst)
        fp->worst = frame;
    fp->c3dCpuMs += c3dCpuMs;
    fp->c3dGpuMs += c3dGpuMs;
    fp->frames++;
}

static double mean_ms(const FrameProf *fp, uint64_t ticks)
{
    return (double)ticks / fp->frames / FRAMEPROF_TICKS_PER_MS;
}

// One view's part of the models' line: its counts a frame.
static int models_part(const FrameProf *fp, int v, char *buf, size_t n)
{
    const uint64_t *m = fp->models[v];
    double f = fp->frames;

    return snprintf(buf, n,
                    "%.0f models, %.0f batches at once, %.0f lit, %.0f held, "
                    "%.0f words (%.0f lit), %.0f indices",
                    m[FRAMEPROF_M_MODELS] / f, m[FRAMEPROF_M_NOW] / f,
                    m[FRAMEPROF_M_LIT] / f, m[FRAMEPROF_M_HELD] / f,
                    m[FRAMEPROF_M_WORDS] / f, m[FRAMEPROF_M_LIT_WORDS] / f,
                    m[FRAMEPROF_M_INDICES] / f);
}

bool frameprof_line(FrameProf *fp, char *buf, size_t n)
{
    double secs;
    int len;

    if (fp->frames == 0 || fp->total < FRAMEPROF_LINE_TICKS)
        return false;
    secs = (double)fp->total / BTICKER_RATE_HZ;
    len = snprintf(buf, n,
             "frame: %.1f fps, %.1f ms, worst %.1f; sound %.1f, flow %.1f, "
             "race %.1f, world %.1f, cameras %.1f, draw %.1f, loads %.1f; "
             "draw: prep %.1f, cull %.1f, envmap %.1f, mirror %.1f, sky %.1f, "
             "models %.1f, scenery %.1f, cars %.1f, hud %.1f, bottom %.1f, "
             "submit %.1f; "
             "waits: vsync %.1f, gpu %.1f; jukebox: decode %.2f, "
             "read %.2f; citro3d cpu %.1f, gpu %.1f; "
             "C %d fps, G %d fps",
             fp->frames / secs, mean_ms(fp, fp->total),
             (double)fp->worst / FRAMEPROF_TICKS_PER_MS,
             mean_ms(fp, fp->phase[FRAMEPROF_SOUND]),
             mean_ms(fp, fp->phase[FRAMEPROF_FLOW]),
             mean_ms(fp, fp->phase[FRAMEPROF_RACE]),
             mean_ms(fp, fp->phase[FRAMEPROF_WORLD]),
             mean_ms(fp, fp->phase[FRAMEPROF_CAMERAS]),
             mean_ms(fp, fp->phase[FRAMEPROF_DRAW]),
             mean_ms(fp, fp->phase[FRAMEPROF_LOADS]),
             mean_ms(fp, fp->stage[FRAMEPROF_PREP]),
             mean_ms(fp, fp->stage[FRAMEPROF_CULL]),
             mean_ms(fp, fp->stage[FRAMEPROF_ENVMAP]),
             mean_ms(fp, fp->stage[FRAMEPROF_MIRROR]),
             mean_ms(fp, fp->stage[FRAMEPROF_SKY]),
             mean_ms(fp, fp->stage[FRAMEPROF_MODELS]),
             mean_ms(fp, fp->stage[FRAMEPROF_SCENERY]),
             mean_ms(fp, fp->stage[FRAMEPROF_CARS]),
             mean_ms(fp, fp->stage[FRAMEPROF_HUD]),
             mean_ms(fp, fp->stage[FRAMEPROF_BOTTOM]),
             mean_ms(fp, fp->stage[FRAMEPROF_SUBMIT]),
             mean_ms(fp, fp->phase[FRAMEPROF_VSYNC]),
             mean_ms(fp, fp->phase[FRAMEPROF_GPU_WAIT]),
             mean_ms(fp, fp->jukeboxDecode),
             mean_ms(fp, fp->jukeboxRead),
             (double)(fp->c3dCpuMs / fp->frames),
             (double)(fp->c3dGpuMs / fp->frames),
             (int)PreviousCpuFrameRate, (int)PreviousGpuFrameRate);
    if (len > 0 && (size_t)len < n) {
        len += snprintf(buf + len, n - len, "\nmodels: view ");
        if (len > 0 && (size_t)len < n)
            len += models_part(fp, 0, buf + len, n - len);
        if (len > 0 && (size_t)len < n)
            len += snprintf(buf + len, n - len, "; envmap ");
        if (len > 0 && (size_t)len < n)
            len += models_part(fp, 1, buf + len, n - len);
        if (len > 0 && (size_t)len < n)
            len += snprintf(buf + len, n - len, "; mirror ");
        if (len > 0 && (size_t)len < n)
            len += models_part(fp, 2, buf + len, n - len);
    }
    if (len > 0 && (size_t)len < n)
        snprintf(buf + len, n - len,
                 "\ncars: %.1f drawn; setup %.1f, shadows %.1f, body %.1f, "
                 "wheels %.1f, lists %.1f",
                 (double)fp->cars[FRAMEPROF_C_CARS] / fp->frames,
                 mean_ms(fp, fp->cars[FRAMEPROF_C_SETUP]),
                 mean_ms(fp, fp->cars[FRAMEPROF_C_SHADOWS]),
                 mean_ms(fp, fp->cars[FRAMEPROF_C_BODY]),
                 mean_ms(fp, fp->cars[FRAMEPROF_C_WHEELS]),
                 mean_ms(fp, fp->cars[FRAMEPROF_C_LISTS]));
    frameprof_reset(fp);
    return true;
}
