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

// The draw check (below).
static bool              s_perDraw;      // this frame's draws one at a time
static bool              s_perDrawDone;  // once a boot
static bool              s_shadowOff;    // after the first race's check
static unsigned          s_draws;        // this frame's
static unsigned          s_issues;       // logged, of at most kMaxIssues
static u32               s_linLo, s_linHi;

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
    s_linLo = osConvertVirtToPhys((const void *)__ctru_linear_heap);
    s_linHi = s_linLo + __ctru_linear_heap_size;
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
    s_perDraw = !s_perDrawDone;
    s_perDrawDone = true;
    s_log("gpu check: frame %lu%s", (unsigned long)s_frames,
          s_perDraw ? ", each draw alone" : "");
}

// The commands so far to the GPU, as C3D_FrameEnd sends them, and
// waited on. The queue is stopped again after, as the frame had it, and
// emptied, as citro3d's own sync transfer empties it within a frame: a
// frame's 33rd entry is svcBreak, and the draws one at a time make
// hundreds. A draw's (no `stage`) is logged only if it is not done.
static void gpu_wait(const char *stage, bool split)
{
    gxCmdQueue_s *q = queue();
    u64           t0 = svcGetSystemTick();
    unsigned      n = q->numEntries;
    bool          done;

    if (split) {
        GSPGPU_FlushDataCache((const void *)__ctru_linear_heap,
                              __ctru_linear_heap_size);
        C3D_FrameSplit(0);
        n = q->numEntries;
        gxCmdQueueRun(q);
    }
    done = gxCmdQueueWait(q, 2 * (s64)SYSCLOCK_ARM11);
    if (done) {
        if (split) {
            gxCmdQueueStop(q);
            gxCmdQueueClear(q);
        }
        if (stage)
            s_log("gpu check: %s done in %.2f ms, %u entries", stage,
                  ms_since(t0), n);
        else if (ms_since(t0) > 20.0)
            s_log("gpu check: draw %u took %.1f ms", s_draws, ms_since(t0));
        return;
    }
    if (stage)
        s_log("gpu check: %s NOT done in 2 s", stage);
    else
        s_log("gpu check: draw %u NOT done in 2 s", s_draws);
    log_queue("gpu check");
    log_regs("gpu check");
    s_checking = false;
    s_perDraw = false;
    s_armed = 0;
}

// ------------------------------------------------------- the draw check
//
// What the GPU is told, read back out of citro3d's command buffer from
// boot to the end of the first race's checked frames: the registers the
// draws read, and at each draw its vertex buffers, its textures and its
// target checked against the memory the GPU may reach, the linear heap
// and VRAM. Azahar reads past those without a word where the console's
// bus may stop. In the first checked frame each draw is also logged
// before it goes, and is sent and waited on alone, so that the last line
// before a stop names the draw.

#define REGS       0x300
#define VRAM_LO    0x18000000u
#define VRAM_HI    0x18600000u
static const unsigned kMaxIssues = 40;

static u32         s_reg[REGS];
static u8          s_regBytes[REGS];  // which bytes have been written
static const u32  *s_cur;             // the frame's first command not read
static const shaderProgram_s *s_prog;

static bool reachable(u32 pa, u32 len)
{
    if (pa >= s_linLo && pa < s_linHi) return len <= s_linHi - pa;
    if (pa >= VRAM_LO && pa < VRAM_HI) return len <= VRAM_HI - pa;
    return false;
}

static bool known(unsigned reg)
{
    return s_regBytes[reg] == 0xf;
}

static const char *last_mark(void)
{
    const char *m = HangwatchTrail[(HangwatchMarks - 1) % HANGWATCH_TRAIL];

    return m ? m : "?";
}

static void issue(const char *what, u32 a, u32 b)
{
    if (s_issues >= kMaxIssues) return;
    s_issues++;
    s_log("draw check: frame %lu draw %u (at %s): %s %08lx %08lx",
          (unsigned long)s_frames, s_draws, last_mark(), what,
          (unsigned long)a, (unsigned long)b);
}

// Bits a texel, by the PICA's format number.
static const u8 kTexBits[14] = { 32, 24, 16, 16, 16, 16, 16, 8, 8, 8, 4, 4,
                                 4, 8 };
// Each unit's dimensions, parameters, LOD, address and format registers.
static const u16 kTexReg[3][5] = {
    { 0x082, 0x083, 0x084, 0x085, 0x08e },
    { 0x092, 0x093, 0x094, 0x095, 0x096 },
    { 0x09a, 0x09b, 0x09c, 0x09d, 0x09e },
};

// One texture unit, into `line`: its address, size, format and mode.
static size_t check_unit(int u, char *line, size_t len, size_t cap)
{
    const u16 *r = kTexReg[u];
    u32        dim, w, h, fmt, mode, levels, size = 0, pa, l;

    if (!known(r[0]) || !known(r[3]) || !(s_regBytes[r[4]] & 1)) {
        return len + (size_t)snprintf(line + len, cap - len, "; t%d ?", u);
    }
    dim = s_reg[r[0]];
    h = dim & 0x7ff;
    w = dim >> 16 & 0x7ff;
    fmt = s_reg[r[4]] & 0xf;
    mode = s_reg[r[1]] >> 28 & 7;
    levels = (s_reg[r[2]] >> 16 & 0xf) + 1;
    pa = (s_reg[r[3]] & 0x0fffffff) << 3;
    if (fmt > 13) issue("texture format", (u32)u, fmt);
    if (w < 8 || h < 8 || w > 1024 || h > 1024 || (w & 7) || (h & 7))
        issue("texture size", (u32)u, w << 16 | h);
    for (l = 0; l < levels && fmt <= 13; l++) {
        size += (w >> l) * (h >> l) * kTexBits[fmt] / 8;
    }
    if (!reachable(pa, size)) issue("texture address", (u32)u << 28 | size,
                                    pa);
    // A cube's other five faces: their addresses' low 22 bits, the rest
    // the first face's.
    if (u == 0 && (mode == 1 || mode == 4)) {
        for (l = 0; l < 5; l++) {
            u32 f = ((s_reg[0x086 + l] & 0x3fffff)
                     | (s_reg[0x085] & 0x0fc00000)) << 3;

            if (!known(0x086 + l) || !reachable(f, size))
                issue("cube face address", l + 1, f);
        }
    }
    return len + (size_t)snprintf(line + len, cap - len,
                                  "; t%d %08lx %lux%lu f%lu m%lu l%lu", u,
                                  (unsigned long)pa, (unsigned long)w,
                                  (unsigned long)h, (unsigned long)fmt,
                                  (unsigned long)mode, (unsigned long)levels);
}

// A float24 register (1 sign, 7 exponent, 16 mantissa bits) as a float.
static float f24(u32 v)
{
    union { u32 u; float f; } x;

    v &= 0xffffff;
    if ((v & 0x7fffff) == 0) return 0.0f;
    x.u = (v >> 23) << 31 | ((v >> 16 & 0x7f) + 64) << 23 | (v & 0xffff) << 7;
    return x.f;
}

// The viewport, the scissor and the shader's outputs, into `line`, and the
// first two checked against the target: a fragment past it is a write past
// the buffer, which on the console may be past what the bus maps.
static size_t check_view(u32 fw, u32 fh, char *line, size_t len, size_t cap)
{
    u32 vw = (u32)(f24(s_reg[0x041]) * 2.0f + 0.5f);
    u32 vh = (u32)(f24(s_reg[0x043]) * 2.0f + 0.5f);
    u32 vx = s_reg[0x068] & 0x3ff, vy = s_reg[0x068] >> 16 & 0x3ff;
    u32 sm = s_reg[0x065] & 3;
    u32 sx0 = s_reg[0x066] & 0x3ff, sy0 = s_reg[0x066] >> 16 & 0x3ff;
    u32 sx1 = s_reg[0x067] & 0x3ff, sy1 = s_reg[0x067] >> 16 & 0x3ff;

    if (vx + vw > fw || vy + vh > fh)
        issue("viewport", vx << 16 | vy, vw << 16 | vh);
    if (sm != 0 && (sx1 >= fw || sy1 >= fh))
        issue("scissor", s_reg[0x066], s_reg[0x067]);
    return len + (size_t)snprintf(line + len, cap - len,
                                  "; vp %lu,%lu %lux%lu sc%lu %lu,%lu-%lu,%lu"
                                  " out %lu/%03lx",
                                  (unsigned long)vx, (unsigned long)vy,
                                  (unsigned long)vw, (unsigned long)vh,
                                  (unsigned long)sm, (unsigned long)sx0,
                                  (unsigned long)sy0, (unsigned long)sx1,
                                  (unsigned long)sy1,
                                  (unsigned long)(s_reg[0x04f] & 7),
                                  (unsigned long)(s_reg[0x2bd] & 0xffff));
}

// The draw the commands just read start: what it reads and writes,
// checked, and in the first checked frame logged.
static void check_draw(bool elements)
{
    static const char *const kPrim[4] = { "tris", "strip", "fan", "geo" };
    char     line[512];
    size_t   len;
    u32      base = (s_reg[0x200] & 0x1fffffff) << 3;
    u32      attrs = (s_reg[0x202] >> 28) + 1, comps = 0;
    u32      first = s_reg[0x22a], count = s_reg[0x228];
    u32      units = s_reg[0x080], dim = s_reg[0x11e];
    u32      fw = dim & 0x7ff, fh = (dim >> 12 & 0x3ff) + 1;
    u32      cpa = (s_reg[0x11d] & 0x0fffffff) << 3;
    u32      dpa = (s_reg[0x11c] & 0x0fffffff) << 3;
    u32      cb = 2 + (s_reg[0x117] & 3);
    u32      dfmt = s_reg[0x116] & 3;
    u32      db = dfmt == 3 ? 4 : dfmt == 2 ? 3 : 2;
    bool     colour = (s_reg[0x112] | s_reg[0x113]) & 0xf;
    bool     depth = (s_reg[0x114] | s_reg[0x115]) & 0x3;
    int      i;

    s_draws++;
    len = (size_t)snprintf(line, sizeof line, "draw %u at %s: %s %lu+%lu",
                           s_draws, last_mark(),
                           elements ? "elements"
                                    : kPrim[s_reg[0x25e] >> 8 & 3],
                           (unsigned long)first, (unsigned long)count);
    if (s_prog && s_prog->vertexShader && s_prog->vertexShader->dvle)
        len += (size_t)snprintf(line + len, sizeof line - len, ", vsh %lu",
                                (unsigned long)
                                s_prog->vertexShader->dvle->dvlp->codeSize);
    if (count == 0 || count > 0x100000 || first > 0x100000)
        issue("vertex count", first, count);
    if (elements) {
        u32 ib = s_reg[0x227];

        if (!reachable(base + (ib & 0x0fffffff),
                       count * (ib >> 31 ? 2u : 1u)))
            issue("index buffer", base, ib);
    }
    for (i = 0; i < 12; i++) {
        u32 c2 = s_reg[0x205 + 3 * i];
        u32 n = c2 >> 28, stride = c2 >> 16 & 0xff;
        u32 pa = base + (s_reg[0x203 + 3 * i] & 0x0fffffff);

        if (n == 0) continue;
        comps += n;
        if (!known(0x203 + 3 * i) || !known(0x205 + 3 * i)) {
            issue("vertex buffer not known", (u32)i, c2);
            continue;
        }
        len += (size_t)snprintf(line + len, sizeof line - len,
                                "; vb%d %08lx %lu/%lu", i,
                                (unsigned long)pa, (unsigned long)n,
                                (unsigned long)stride);
        if (!elements && !reachable(pa + first * stride, count * stride))
            issue("vertex buffer", pa + first * stride, count * stride);
    }
    if (comps != attrs) issue("attributes", attrs, comps);
    if ((s_reg[0x242] & 0xf) + 1 != attrs
        || (s_reg[0x2b9] & 0xf) + 1 != attrs)
        issue("shader inputs", s_reg[0x242], s_reg[0x2b9]);
    for (i = 0; i < 3; i++) {
        if (units >> i & 1) len = check_unit(i, line, len, sizeof line);
    }
    len += (size_t)snprintf(line + len, sizeof line - len,
                            "; fb %lux%lu c %08lx/%lu%s d %08lx/%lu%s",
                            (unsigned long)fw, (unsigned long)fh,
                            (unsigned long)cpa, (unsigned long)cb,
                            colour ? "" : " off", (unsigned long)dpa,
                            (unsigned long)db, depth ? "" : " off");
    if (colour && !reachable(cpa, fw * fh * cb))
        issue("colour buffer", cpa, fw << 16 | fh);
    if (depth && !reachable(dpa, fw * fh * db))
        issue("depth buffer", dpa, fw << 16 | fh);
    len = check_view(fw, fh, line, len, sizeof line);
    if (s_perDraw) s_log("%s", line);
}

static void reg_write(unsigned reg, unsigned mask, u32 v)
{
    u32 m = (mask & 1 ? 0xffu : 0) | (mask & 2 ? 0xff00u : 0)
            | (mask & 4 ? 0xff0000u : 0) | (mask & 8 ? 0xff000000u : 0);

    if (reg >= REGS) return;
    s_reg[reg] = (s_reg[reg] & ~m) | (v & m);
    s_regBytes[reg] |= (u8)mask;
    if (reg == 0x22e || reg == 0x22f) check_draw(reg == 0x22f);
}

// The commands from the last read to `end`: a parameter and a header, the
// header's extra parameters, and a word more when there are an odd number.
static void read_commands(const u32 *end)
{
    const u32 *p = s_cur;

    if (!p || end < p || end - p > 0x400000) {
        if (p) issue("command buffer", (u32)p, (u32)end);
        s_cur = NULL;
        return;
    }
    while (end - p >= 2) {
        u32      hdr = p[1];
        unsigned reg = hdr & 0xffff, mask = hdr >> 16 & 0xf;
        unsigned extra = hdr >> 20 & 0x7ff, i;
        bool     inc = hdr >> 31;

        if ((u32)(end - p) < 2 + extra + (extra & 1)) {
            issue("command past the end", hdr, (u32)(end - p));
            break;
        }
        if (reg >= 0x400) issue("command register", hdr, p[0]);
        reg_write(reg, mask, p[0]);
        for (i = 0; i < extra; i++) {
            reg_write(inc ? reg + 1 + i : reg, mask, p[2 + i]);
        }
        p += 2 + extra + (extra & 1);
    }
    s_cur = p;
}

void __real_C3D_DrawArrays(GPU_Primitive_t primitive, int first, int size);
void __wrap_C3D_DrawArrays(GPU_Primitive_t primitive, int first, int size);
void __real_C3D_DrawElements(GPU_Primitive_t primitive, int count, int type,
                             const void *indices);
void __wrap_C3D_DrawElements(GPU_Primitive_t primitive, int count, int type,
                             const void *indices);
bool __real_C3D_FrameBegin(u8 flags);
bool __wrap_C3D_FrameBegin(u8 flags);
void __real_C3D_BindProgram(shaderProgram_s *program);
void __wrap_C3D_BindProgram(shaderProgram_s *program);

// After a draw: its commands read, and in the first checked frame the
// draw sent and waited on alone.
static void after_draw(void)
{
    if (s_shadowOff) return;
    read_commands(gpuCmdBuf + gpuCmdBufOffset);
    if (s_perDraw) {
        s_beatMs = now_ms();
        gpu_wait(NULL, true);
    }
}

void __wrap_C3D_DrawArrays(GPU_Primitive_t primitive, int first, int size)
{
    __real_C3D_DrawArrays(primitive, first, size);
    after_draw();
}

// citro2d's.
void __wrap_C3D_DrawElements(GPU_Primitive_t primitive, int count, int type,
                             const void *indices)
{
    __real_C3D_DrawElements(primitive, count, type, indices);
    after_draw();
}

// A frame's commands start at the buffer's start.
bool __wrap_C3D_FrameBegin(u8 flags)
{
    bool ok = __real_C3D_FrameBegin(flags);

    if (ok && !s_shadowOff) {
        s_cur = gpuCmdBuf + gpuCmdBufOffset;
        s_draws = 0;
    }
    return ok;
}

void __wrap_C3D_BindProgram(shaderProgram_s *program)
{
    s_prog = program;
    __real_C3D_BindProgram(program);
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
    // The shadow's parse costs every draw; the race's checked frames are
    // what it is for.
    if (s_armed == 0) {
        s_shadowOff = true;
        s_perDraw = false;
        s_log("draw check: %u issues; the shadow is off", s_issues);
    }
}
