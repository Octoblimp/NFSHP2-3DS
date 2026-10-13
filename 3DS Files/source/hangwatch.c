// hangwatch -- where the game was when it stopped, and where the GPU's
// time goes (hangwatch.h).

#include "hangwatch.h"

#include <3ds.h>
#include <citro3d.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "georender.h"
#include "logwriter.h"

// citro3d's context, whose first member is the GX queue its frames go
// through: C3D_FrameBegin waits on it, stops it and clears it, and
// C3D_FrameEnd runs it. The type is citro3d's own and not in its headers.
// In the libcitro3d.a this links (disassembled, 2026-10-05) its command
// buffer is at 20 and its flags at 32; hangwatch_gpu_begin checks the
// first before a timing frame sets the second.
extern u8  __C3D_Context[];
extern u32 __ctru_linear_heap, __ctru_linear_heap_size;

// citro3d's own (its internal.h): every uniform the shader has been
// given, and its constants, marked changed, so the next draw sends them.
void C3Di_DirtyUniforms(GPU_SHADER_TYPE type);

// And C3D_FrameSplit's split without its send: false when nothing was
// drawn since the last; otherwise the list, finished with the framebuffer's
// flush when it drew, and its size in words. The buffer goes on after it.
bool C3Di_SplitFrame(u32 **pBuf, u32 *pSize);

const char *volatile HangwatchTrail[HANGWATCH_TRAIL];
volatile uint32_t    HangwatchMarks;

static const char kApt[] = "aptMainLoop: HOME, sleep or a suspend";

static void (*s_log)(const char *fmt, ...);
static Thread            s_thread;
static LightEvent        s_quit;         // hangwatch_stop
static volatile uint32_t s_frames;       // frames begun
static volatile uint32_t s_beatMs;       // the last one's, in ms
static volatile uint32_t s_marksAtBeat;
static int               s_peak;         // the most GX entries a frame had

static gxCmdQueue_s *queue(void)
{
    return (gxCmdQueue_s *)(void *)__C3D_Context;
}

static uint32_t now_ms(void)
{
    return (uint32_t)(svcGetSystemTick() / (SYSCLOCK_ARM11 / 1000u));
}

static double ms_since(u64 tick)
{
    return (double)(svcGetSystemTick() - tick) / CPU_TICKS_PER_MSEC;
}

// The queue's entries, from the first the GPU has not finished. A
// command list's are its address, its size in bytes and its flags.
static void log_queue(const char *who)
{
    static const char *const kType[] = {
        "dma", "commands", "fill", "transfer", "copy", "flush"
    };
    const gxCmdQueue_s *q = queue();
    unsigned            n = q->numEntries, done = q->lastEntry, i;

    s_log("%s: gx queue %u entries of %u, %u sent, %u done", who, n,
          (unsigned)q->maxEntries, (unsigned)q->curEntry, done);
    for (i = done; i < n && i < done + 6u; i++) {
        const gxCmdEntry_s *e = &q->entries[i];

        s_log("%s: entry %u, %s: %08lx %08lx %08lx %08lx", who, i,
              e->type < 6 ? kType[e->type] : "?", (unsigned long)e->args[0],
              (unsigned long)e->args[1], (unsigned long)e->args[2],
              (unsigned long)e->args[3]);
    }
}

// The GPU's registers, raw, through GSP (offsets from 0x1EB00000): the
// two fills' (0x1EF00010..0x1EF00037), the transfer's control
// (0x1EF00C18) and the command lists' sizes and addresses (PICA 0x238 ..
// 0x23d). Last, since a GSP that is stuck too keeps this thread here.
static void log_regs(const char *who)
{
    u32 fill[10] = {0}, ppf = 0, cmd[6] = {0};
    Result r0 = GSPGPU_ReadHWRegs(0x400010, fill, sizeof fill);
    Result r1 = GSPGPU_ReadHWRegs(0x400c18, &ppf, sizeof ppf);
    Result r2 = GSPGPU_ReadHWRegs(0x4018e0, cmd, sizeof cmd);

    s_log("%s: regs fill %08lx %08lx %08lx %08lx, %08lx %08lx %08lx %08lx, "
          "%08lx %08lx; transfer %08lx; commands %08lx %08lx %08lx %08lx "
          "%08lx %08lx (%08lx %08lx %08lx)", who,
          (unsigned long)fill[0], (unsigned long)fill[1],
          (unsigned long)fill[2], (unsigned long)fill[3],
          (unsigned long)fill[4], (unsigned long)fill[5],
          (unsigned long)fill[6], (unsigned long)fill[7],
          (unsigned long)fill[8], (unsigned long)fill[9],
          (unsigned long)ppf, (unsigned long)cmd[0], (unsigned long)cmd[1],
          (unsigned long)cmd[2], (unsigned long)cmd[3],
          (unsigned long)cmd[4], (unsigned long)cmd[5], (unsigned long)r0,
          (unsigned long)r1, (unsigned long)r2);
}

// The marks since the frame began, the last first.
static void log_marks(uint32_t since, bool moving)
{
    char     line[640];
    uint32_t n = HangwatchMarks, count = n - s_marksAtBeat, i;
    size_t   len = 0;

    for (i = 0; i < HANGWATCH_TRAIL && i < n; i++) {
        const char *m = HangwatchTrail[(n - 1 - i) % HANGWATCH_TRAIL];

        if (len + 4 >= sizeof line) break;
        len += (size_t)snprintf(line + len, sizeof line - len, "%s%s",
                                i ? " < " : "", m ? m : "?");
    }
    s_log("hangwatch: no frame for %.1f s, after frame %lu; %lu marks since "
          "it began, %s; at %s", (double)since / 1000.0,
          (unsigned long)s_frames, (unsigned long)count,
          moving ? "still moving" : "none moving", len ? line : "none");
}

static void watch_main(void *arg)
{
    uint32_t frames = 0, marks = 0, next = 3000, stalledAt = 0;
    bool     stalled = false;

    (void)arg;
    for (;;) {
        uint32_t f, m, since;
        bool     moving;

        if (LightEvent_WaitTimeout(&s_quit, 250LL * 1000 * 1000) == 0)
            break;
        f = s_frames;
        m = HangwatchMarks;
        moving = m != marks;
        marks = m;
        if (f != frames) {
            if (stalled)
                s_log("hangwatch: frames again, frame %lu, after %.1f s",
                      (unsigned long)f,
                      (double)(now_ms() - stalledAt) / 1000.0);
            frames = f;
            next = 3000;
            stalled = false;
            continue;
        }
        if (f == 0 || HangwatchTrail[(m - 1) % HANGWATCH_TRAIL] == kApt)
            continue;
        since = now_ms() - s_beatMs;
        if (since < next) continue;
        if (!stalled) stalledAt = s_beatMs;
        log_marks(since, moving);
        log_queue("hangwatch");
        if (!stalled) log_regs("hangwatch");
        // The report on the card now, not with the next batch.
        logwriter_flush_soon();
        stalled = true;
        next = next < 10000 ? 10000 : next + 30000;
    }
}

void hangwatch_start(void (*log)(const char *fmt, ...))
{
    s32 prio = 0x30;

    s_log = log;
    svcGetThreadPriority(&prio, CUR_THREAD_HANDLE);
    if (prio > 0x18) prio--;
    LightEvent_Init(&s_quit, RESET_STICKY);
    s_thread = threadCreate(watch_main, NULL, 16 << 10, prio, -2, false);
    s_log("hangwatch: watchdog %s, priority 0x%lx", s_thread ? "up" : "failed",
          (unsigned long)prio);
}

void hangwatch_stop(void)
{
    if (!s_thread) return;
    LightEvent_Signal(&s_quit);
    threadJoin(s_thread, U64_MAX);
    threadFree(s_thread);
    s_thread = NULL;
}

bool hangwatch_main_loop(void)
{
    bool up;

    hangwatch_mark(kApt);
    up = aptMainLoop();
    s_beatMs = now_ms();
    s_marksAtBeat = HangwatchMarks;
    s_frames++;
    hangwatch_mark("frame begun");
    return up;
}

void hangwatch_log(const char *fmt, ...)
{
    char    line[512];
    va_list ap;

    if (!s_log) return;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    s_log("%s", line);
}

// ------------------------------------------------------- the timing frame

static bool     s_racing;
static bool     s_wanted;      // the flag file was there at the race's start
static bool     s_due;
static bool     s_timing;      // this frame
static bool     s_broken;      // a wait failed: no more timing frames
static bool     s_noReplay;    // no target for the replays: stages only
static bool     s_envDone;     // this frame's first envmap view sent again
static uint32_t s_nextMs;      // when the next is due
static char     s_line[768];   // this frame's stages
static size_t   s_len;
static unsigned s_stages;      // on it
static double   s_total;

static u32 *c3d_flags(void)
{
    return (u32 *)(void *)(__C3D_Context + 32);
}

// citro3d's C3DiF_ flags for all a list's draws read, which
// C3Di_UpdateContext sends before the next draw: the attributes, the
// buffers, the effect, the framebuffer, the viewport, the scissor, the
// program and its code, the combiner buffer, the lighting switch, the
// texture units and their switch, the fog table and the six combiners.
#define C3D_FLAGS_ALL (0x4u | 0x8u | 0x10u | 0x20u | 0x40u | 0x80u | 0x100u \
                       | 0x200u | 0x400u | 0x800u | 0x4000u | (1u << 17)   \
                       | (7u << 23) | (0x3fu << 26))

// Everything sent again before the next draw. Each list a timing frame
// splits off then starts with all it reads, so it can be sent again on
// its own; and the list after a replay does not find the GPU as the
// replay left it. georender's runs send a buffer's start as one register
// over citro3d's (georender.h), so they start again too.
static void send_all_again(void)
{
    *c3d_flags() |= C3D_FLAGS_ALL;
    C3Di_DirtyUniforms(GPU_VERTEX_SHADER);
    georender_forget();
}

// The queue run and waited on for 2 s at most, and then stopped and
// emptied, as C3D_FrameBegin leaves it, when `run`. After C3D_FrameEnd it
// runs already, and its callback is citro3d's.
static bool wait_queue(bool run, double *ms)
{
    gxCmdQueue_s *q = queue();
    u64           t0 = svcGetSystemTick();

    if (run) gxCmdQueueRun(q);
    if (!gxCmdQueueWait(q, 2 * (s64)SYSCLOCK_ARM11)) return false;
    if (ms) *ms = ms_since(t0);
    if (run) {
        gxCmdQueueStop(q);
        gxCmdQueueClear(q);
    }
    return true;
}

static void stuck(const char *what, const char *how)
{
    s_log("gpu time: %s%s%s NOT done in 2 s; no more timing frames", what,
          how[0] ? ", " : "", how);
    log_queue("gpu time");
    log_regs("gpu time");
    s_broken = true;
    s_timing = false;
}

// The replays' target, the top screen's size and formats (RGBA8 over
// D24S8) in VRAM of its own, and their 8x8 RGBA8 texture.
#define OFF_W     240u
#define OFF_H     400u
#define OFF_WORDS (OFF_W * OFF_H)

static u32 *s_offColour, *s_offDepth, *s_standin;

static bool targets_made(void)
{
    if (s_offColour && s_offDepth && s_standin) return true;
    if (s_noReplay) return false;
    // Colour and depth in the two banks, as C3D_RenderTargetCreate puts
    // them.
    if (!s_offColour) s_offColour = (u32 *)vramAllocAt(OFF_WORDS * 4,
                                                       VRAM_ALLOC_A);
    if (!s_offColour) s_offColour = (u32 *)vramAlloc(OFF_WORDS * 4);
    if (!s_offDepth) s_offDepth = (u32 *)vramAllocAt(OFF_WORDS * 4,
                                                     VRAM_ALLOC_B);
    if (!s_offDepth) s_offDepth = (u32 *)vramAlloc(OFF_WORDS * 4);
    if (!s_standin) {
        s_standin = (u32 *)linearAlloc(8 * 8 * 4);
        if (s_standin) {
            for (int i = 0; i < 64; i++) s_standin[i] = 0xff808080u;
            GSPGPU_FlushDataCache(s_standin, 8 * 8 * 4);
        }
    }
    if (s_offColour && s_offDepth && s_standin) return true;
    s_log("gpu time: no VRAM or linear heap for the replays' target; the "
          "stages are timed, and no list is sent again");
    s_noReplay = true;
    return false;
}

// The ways a list is sent again. The last three are 13b-4f's questions.
// The early depth test (GPUREG_EARLYDEPTH_*) is the PICA's test before the
// texture fetch and the combiners. Its buffer is the GPU's own and how it
// updates is not documented anywhere public, and Azahar does not emulate
// it, so the device has to say both what it saves and whether the picture
// stays the same: each early variant's target is compared with the list's
// as drawn. The port's depth is nearer-greater (GEQUAL, cleared to 0), and
// the registers do not say which side of the compare the buffer is on, so
// both are tried. RGB8 reads every RGBA8 texture as RGB8: the texels are
// wrong, but the fetch is the three bytes a texel that the lossless RGB8
// of the textures with one alpha would fetch (memory: gpu-speed-plan).
enum { V_DRAWN, V_TEX8, V_PIXEL, V_VERTS, V_NOCLEAR, V_EARLY_GE,
       V_EARLY_LE, V_RGB8, V_COUNT };

typedef struct {
    unsigned draws;      // GPUREG_DRAWARRAYS and _DRAWELEMENTS
    unsigned verts;      // GPUREG_NUMVERTICES at each
    unsigned texAddrs;   // a unit's address
    unsigned clears;     // texture cache clears
    u32      pending;    // GPUREG_NUMVERTICES
    bool     fbFirst;    // the colour buffer's address before the first draw
    bool     fbFits;     // every framebuffer within the replays' target
} ListStats;

// One register write's value in variant `v`. Every variant draws onto the
// replays' target; the others change what their name says.
static u32 patch(int v, unsigned reg, unsigned mask, u32 val, ListStats *st)
{
    bool pixel = v == V_PIXEL || v == V_VERTS;
    bool early = v == V_EARLY_GE || v == V_EARLY_LE;

    switch (reg) {
    case 0x061:                       // GPUREG_EARLYDEPTH_FUNC
        if (v == V_EARLY_GE) return GPU_EARLYDEPTH_GEQUAL;
        return v == V_EARLY_LE ? GPU_EARLYDEPTH_LEQUAL : val;
    case 0x062:                       // _TEST1 and _TEST2: on
    case 0x118:
        return early ? 1 : val;
    case 0x06a:                       // _DATA, the clear value: the depth's 0
        return early ? 0 : val;
    case 0x11c:                       // GPUREG_DEPTHBUFFER_LOC
        return osConvertVirtToPhys(s_offDepth) >> 3;
    case 0x11d:                       // GPUREG_COLORBUFFER_LOC
        if (st->draws == 0) st->fbFirst = true;
        return osConvertVirtToPhys(s_offColour) >> 3;
    case 0x11e:                       // GPUREG_FRAMEBUFFER_DIM
        if ((val & 0x7ff) > OFF_W || (val >> 12 & 0x3ff) + 1 > OFF_H)
            st->fbFits = false;
        return val;
    case 0x228:                       // GPUREG_NUMVERTICES
        st->pending = val;
        return v == V_VERTS && val > 3 ? 3 : val;
    case 0x22e:                       // GPUREG_DRAWARRAYS
    case 0x22f:                       // GPUREG_DRAWELEMENTS
        st->draws++;
        st->verts += st->pending;
        return val;
    case 0x080:                       // GPUREG_TEXUNIT_CONFIG
        // Bit 16 clears the texture cache; citro3d sets it alone, in a
        // write of byte 2 only, after each texture change.
        if ((mask & 4) && (val & BIT(16))) st->clears++;
        return v == V_NOCLEAR ? val & ~BIT(16) : val;
    case 0x065:                       // GPUREG_SCISSORTEST_MODE: inside
        return pixel ? 3 : val;
    case 0x066:                       // _POS and _DIM, inclusive: (0, 0)
    case 0x067:
        return pixel ? 0 : val;
    case 0x082: case 0x092: case 0x09a:   // TEXUNITn_DIM
        return v == V_TEX8 ? (8u << 16 | 8u) : val;
    case 0x084: case 0x094: case 0x09c:   // _LOD: the base level alone
        return v == V_TEX8 ? val & 0x1fff : val;
    case 0x085: case 0x095: case 0x09d:   // _ADDR1
        st->texAddrs++;
        return v == V_TEX8 ? osConvertVirtToPhys(s_standin) >> 3 : val;
    case 0x08e: case 0x096: case 0x09e:   // _TYPE: RGBA8, or RGB8 for it
        if (v == V_TEX8) return GPU_RGBA8;
        return v == V_RGB8 && val == GPU_RGBA8 ? GPU_RGB8 : val;
    }
    return val;
}

// The list `src` into `dst`, changed for variant `v`. Each command is a
// parameter and a header, the header's extra parameters, and a word more
// when there are an odd number of them. False unless the walk lands on
// the list's end and the list sets its own target before it draws, and
// in the replays' target's bounds.
static bool copy_list(const u32 *src, u32 words, u32 *dst, int v,
                      ListStats *st)
{
    u32 i = 0;

    memset(st, 0, sizeof *st);
    st->fbFits = true;
    while (words - i >= 2) {
        u32      hdr = src[i + 1];
        unsigned reg = hdr & 0xffff, mask = hdr >> 16 & 0xf;
        unsigned extra = hdr >> 20 & 0x7ff, k;
        bool     inc = hdr >> 31;
        u32      len = 2 + extra + (extra & 1);

        if (len > words - i) return false;
        dst[i] = patch(v, reg, mask, src[i], st);
        dst[i + 1] = hdr;
        for (k = 0; k < extra; k++)
            dst[i + 2 + k] = patch(v, inc ? reg + 1 + k : reg, mask,
                                   src[i + 2 + k], st);
        if (extra & 1) dst[i + 2 + extra] = src[i + 2 + extra];
        i += len;
    }
    return i == words && st->fbFirst && st->fbFits && st->draws > 0;
}

// The pixels of the replays' target that differ from `drawn`, colour then
// depth: the target read back as capture.c reads the top screen's.
static void differ(const u32 *drawn, unsigned *colour, unsigned *depth)
{
    u32 i;

    *colour = *depth = 0;
    for (i = 0; i < OFF_WORDS; i++) {
        if (s_offColour[i] != drawn[i]) (*colour)++;
        if (s_offDepth[i] != drawn[OFF_WORDS + i]) (*depth)++;
    }
}

// A stage's list sent again onto the replays' target, cleared first as
// the stage's own was, once each way. RGB8's picture is compared too: its
// texels are wrong, so it must differ. An early variant's copy starts with
// four words more: the early depth buffer cleared to the depth's 0, as
// citro3d's frame split clears it.
static void replay(const char *name, const u32 *list, u32 words)
{
    static const char *const kVariant[V_COUNT] = {
        "as drawn", "8x8 textures", "1-pixel scissor",
        "and 3 vertices a draw", "no texture cache clears",
        "early depth >=", "early depth <=", "RGB8 for RGBA8"
    };
    char      line[1024];
    size_t    len;
    ListStats st, first = {0};
    double    ms[V_COUNT];
    unsigned  diffColour[V_COUNT] = {0}, diffDepth[V_COUNT] = {0};
    u32      *copy, *drawn;
    bool      compared;
    int       v;

    if (!targets_made()) return;
    copy = (u32 *)linearAlloc((words + 4) * 4);
    if (!copy) {
        s_log("gpu time: %s: no %lu bytes of linear heap to copy it into",
              name, (unsigned long)(words + 4) * 4);
        return;
    }
    // The as-drawn target, colour then depth, for the early variants'.
    drawn = (u32 *)malloc(OFF_WORDS * 8);
    if (!drawn)
        s_log("gpu time: %s: no %lu bytes of heap to compare the early "
              "depth test's pictures in", name, (unsigned long)OFF_WORDS * 8);
    for (v = 0; v < V_COUNT; v++) {
        bool early = v == V_EARLY_GE || v == V_EARLY_LE;
        u32 *start = early ? copy : copy + 4;
        u32  size = (early ? words + 4 : words) * 4;

        copy[0] = 0;                       // GPUREG_EARLYDEPTH_DATA
        copy[1] = 0x7u << 16 | 0x06a;
        copy[2] = 1;                       // GPUREG_EARLYDEPTH_CLEAR
        copy[3] = 0xfu << 16 | 0x063;
        if (!copy_list(list, words, copy + 4, v, &st)) {
            s_log("gpu time: %s: not sent again: %lu words, %u draws, the "
                  "target %s, %s", name, (unsigned long)words, st.draws,
                  st.fbFirst ? "set first" : "not set first",
                  st.fbFits ? "fits" : "does not fit");
            linearFree(copy);
            free(drawn);
            return;
        }
        if (v == V_DRAWN) first = st;
        s_beatMs = now_ms();
        GX_MemoryFill(s_offColour, 0, s_offColour + OFF_WORDS,
                      GX_FILL_TRIGGER | GX_FILL_32BIT_DEPTH, s_offDepth, 0,
                      s_offDepth + OFF_WORDS,
                      GX_FILL_TRIGGER | GX_FILL_32BIT_DEPTH);
        if (!wait_queue(true, NULL)) {
            stuck(name, "the replays' clear");
            free(drawn);
            return;   // the copy stays: the GPU may yet read it
        }
        GSPGPU_FlushDataCache(copy, (words + 4) * 4);
        GX_ProcessCommandList(start, size, 0);
        if (!wait_queue(true, &ms[v])) {
            stuck(name, kVariant[v]);
            free(drawn);
            return;
        }
        if (drawn && v == V_DRAWN) {
            memcpy(drawn, s_offColour, OFF_WORDS * 4);
            memcpy(drawn + OFF_WORDS, s_offDepth, OFF_WORDS * 4);
        } else if (drawn && (early || v == V_RGB8)) {
            differ(drawn, &diffColour[v], &diffDepth[v]);
        }
    }
    linearFree(copy);
    compared = drawn != NULL;
    free(drawn);
    len = (size_t)snprintf(line, sizeof line,
                           "gpu time: %s sent again (%u draws, %u vertices, "
                           "%u texture addresses, %u cache clears, %lu "
                           "words):", name, first.draws, first.verts,
                           first.texAddrs, first.clears,
                           (unsigned long)words);
    for (v = 0; v < V_COUNT && len < sizeof line; v++)
        len += (size_t)snprintf(line + len, sizeof line - len, "%s %s %.2f",
                                v ? ";" : "", kVariant[v], ms[v]);
    s_log("%s", line);
    if (compared)
        s_log("gpu time: %s, the early depth test's pictures against as "
              "drawn: >= %u colour and %u depth pixels differ, <= %u and %u "
              "(of %u; RGB8's wrong texels, which show that the compare "
              "sees a change, %u)", name, diffColour[V_EARLY_GE],
              diffDepth[V_EARLY_GE], diffColour[V_EARLY_LE],
              diffDepth[V_EARLY_LE], (unsigned)OFF_WORDS,
              diffColour[V_RGB8]);
}

void hangwatch_gpu_race(bool racing)
{
    uint32_t t = now_ms();

    if (!racing) {
        s_racing = false;
        return;
    }
    if (!s_racing) {
        FILE *f = fopen(HANGWATCH_TIMING_FLAG, "r");

        s_racing = true;
        s_nextMs = t + 5000;
        s_wanted = f != NULL;
        if (f != NULL) fclose(f);
        s_log("gpu time: timing frames %s (%s)", s_wanted ? "on" : "off",
              HANGWATCH_TIMING_FLAG);
    }
    if (s_wanted && !s_broken && (int32_t)(t - s_nextMs) >= 0) s_due = true;
}

void hangwatch_gpu_begin(void)
{
    hangwatch_mark("C3D_FrameBegin done");
    if (!s_due) return;
    s_due = false;
    // A frame just begun writes from the command buffer's start, and the
    // context is active.
    if (*(u32 **)(void *)(__C3D_Context + 20) != gpuCmdBuf
        || !(*c3d_flags() & 1)) {
        s_log("gpu time: citro3d's context is not as hangwatch.c reads it "
              "(buffer %p, flags %08lx); no timing frames", (void *)gpuCmdBuf,
              (unsigned long)*c3d_flags());
        s_broken = true;
        return;
    }
    s_timing = true;
    s_envDone = false;
    s_total = 0.0;
    s_stages = 0;
    s_len = (size_t)snprintf(s_line, sizeof s_line, "gpu time: frame %lu:",
                             (unsigned long)s_frames);
}

// A stage's commands, split off and timed, and sent again if it is one
// of the two.
static void time_stage(const char *name, bool split)
{
    gxCmdQueue_s *q = queue();
    u32          *list = gpuCmdBuf;
    u32           words = 0;
    bool          listed = false;
    double        ms = 0.0;

    if (split) {
        // The flush after the split, as C3D_FrameEnd has it: the split
        // writes the list's FINALIZE, and flushed before it those words
        // stay in the New 3DS's L2 cache (04aa510).
        C3D_FrameSplit(0);
        GSPGPU_FlushDataCache((const void *)__ctru_linear_heap,
                              __ctru_linear_heap_size);
        words = (u32)(gpuCmdBuf - list);
        // The split's list is the queue's last entry.
        if (words && q->numEntries) {
            const gxCmdEntry_s *e = &q->entries[q->numEntries - 1];

            listed = e->type == 1 && e->args[0] == (u32)list
                     && e->args[1] == words * 4;
        }
    }
    if (!wait_queue(split, &ms)) {
        stuck(name, "");
        return;
    }
    s_total += ms;
    if (s_len < sizeof s_line)
        s_len += (size_t)snprintf(s_line + s_len, sizeof s_line - s_len,
                                  "%s %s %.2f", s_stages++ ? ";" : "",
                                  name, ms);
    if (listed && (!strcmp(name, "the models")
                   || (!s_envDone && !strncmp(name, "envmap view", 11)))) {
        s_envDone = s_envDone || name[0] == 'e';
        replay(name, list, words);
    }
    if (split && s_timing) send_all_again();
}

void hangwatch_gpu_stage(const char *stage)
{
    hangwatch_mark(stage);
    if (s_timing) time_stage(stage, true);
}

void hangwatch_gpu_frame_end(void)
{
    const gxCmdQueue_s *q = queue();

    hangwatch_mark("C3D_FrameEnd done");
    if (!s_timing) {
        if ((int)q->numEntries > s_peak) {
            s_peak = (int)q->numEntries;
            s_log("gx queue: a frame used %d of %u entries", s_peak,
                  (unsigned)q->maxEntries);
        }
        return;
    }
    time_stage("the frame's end", false);
    if (s_timing) s_log("%s; %.1f ms in all", s_line, s_total);
    s_timing = false;
    s_nextMs = now_ms() + 10000;
}

// ------------------------------------------------------------ the sends

static bool s_sendsOn;     // this frame goes to the GPU in parts

void hangwatch_gpu_sends_begin(bool on)
{
    s_sendsOn = on && !s_timing;
}

void hangwatch_gpu_send(void)
{
    u32 *list, words;

    if (!s_sendsOn || !C3Di_SplitFrame(&list, &words)) return;
    // The flush after the split, as time_stage has it: the split writes
    // the list's FINALIZE. All the heap, for the vertices written since.
    GSPGPU_FlushDataCache((const void *)__ctru_linear_heap,
                          __ctru_linear_heap_size);
    // Into the queue, and the queue run: the GPU starts on it now, or once
    // the last part is done.
    GX_ProcessCommandList(list, words * 4, 0);
    gxCmdQueueRun(queue());
}

void hangwatch_gpu_sends_end(void)
{
    hangwatch_gpu_send();
    s_sendsOn = false;
}
