// hangwatch -- where the game was when it stopped (hangwatch.h).

#include "hangwatch.h"

#include <3ds.h>
#include <citro3d.h>
#include <stdio.h>

// citro3d's context, whose first member is the GX queue its frames go
// through: C3D_FrameBegin waits on it, stops it and clears it, and
// C3D_FrameEnd runs it. The type is citro3d's own and not in its headers.
extern u8  __C3D_Context[];
extern u32 __ctru_linear_heap, __ctru_linear_heap_size;

const char *volatile HangwatchTrail[HANGWATCH_TRAIL];
volatile uint32_t    HangwatchMarks;

static const char kApt[] = "aptMainLoop: HOME, sleep or a suspend";

static void (*s_log)(const char *fmt, ...);
static Thread            s_thread;
static volatile uint32_t s_frames;       // frames begun
static volatile uint32_t s_beatMs;       // the last one's, in ms
static volatile uint32_t s_marksAtBeat;
static int               s_peak;         // the most GX entries a frame had
static int               s_armed;        // frames left to check
static bool              s_checking;     // this frame

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

        svcSleepThread(250LL * 1000 * 1000);
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
    s_thread = threadCreate(watch_main, NULL, 16 << 10, prio, -2, true);
    s_log("hangwatch: watchdog %s, priority 0x%lx", s_thread ? "up" : "failed",
          (unsigned long)prio);
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

void hangwatch_gpu_arm(int frames)
{
    s_armed = frames;
}

void hangwatch_gpu_begin(void)
{
    hangwatch_mark("C3D_FrameBegin done");
    s_checking = s_armed > 0;
    if (!s_checking) return;
    s_armed--;
    s_log("gpu check: frame %lu", (unsigned long)s_frames);
}

// The commands so far to the GPU, as C3D_FrameEnd sends them, and
// waited on. The queue is stopped again after, as the frame had it.
static void gpu_wait(const char *stage, bool split)
{
    gxCmdQueue_s *q = queue();
    u64           t0 = svcGetSystemTick();
    bool          done;

    if (split) {
        GSPGPU_FlushDataCache((const void *)__ctru_linear_heap,
                              __ctru_linear_heap_size);
        C3D_FrameSplit(0);
        gxCmdQueueRun(q);
    }
    done = gxCmdQueueWait(q, 2 * (s64)SYSCLOCK_ARM11);
    if (done) {
        if (split) gxCmdQueueStop(q);
        s_log("gpu check: %s done in %.2f ms, %u entries", stage,
              ms_since(t0), (unsigned)q->numEntries);
        return;
    }
    s_log("gpu check: %s NOT done in 2 s", stage);
    log_queue("gpu check");
    log_regs("gpu check");
    s_checking = false;
    s_armed = 0;
}

void hangwatch_gpu_stage(const char *stage)
{
    hangwatch_mark(stage);
    if (s_checking) gpu_wait(stage, true);
}

void hangwatch_gpu_frame_end(void)
{
    const gxCmdQueue_s *q = queue();

    hangwatch_mark("C3D_FrameEnd done");
    if (!s_checking) {
        if ((int)q->numEntries > s_peak) {
            s_peak = (int)q->numEntries;
            s_log("gx queue: a frame used %d of %u entries", s_peak,
                  (unsigned)q->maxEntries);
        }
        return;
    }
    gpu_wait("the frame's end and its transfers", false);
    s_checking = false;
}
