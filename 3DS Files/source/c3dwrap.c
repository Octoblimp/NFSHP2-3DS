// citro3d's uniform upload, skipped when no uniform has changed (step 13b-4).
// Its draws and its clears too, below.
//
// Every C3D_DrawArrays starts with C3Di_UpdateContext, which ends with
// C3D_UpdateUniforms for the vertex shader and again for the geometry
// shader. Each call walks the shader's 96 float uniforms' dirty bytes one
// at a time, then the integer and bool ones (disassembled out of the
// shipped libcitro3d.a): about 1,200 instructions a draw with nothing to
// send. The race draws two thousand and more a frame, nearly all with no
// uniform changed since the last, and no geometry shader at all.
//
// The Makefile links with --wrap, so base.o's calls come here:
//   * __wrap_C3D_UpdateUniforms looks at the public dirty flags a word at a
//     time, and calls citro3d's only when one is set;
//   * the shader's own constants have a dirty flag that is local to
//     uniforms.o (C3Di_ShaderFVecData). The two functions that set it,
//     C3Di_LoadShaderUniforms (from C3D_BindProgram) and C3Di_DirtyUniforms,
//     are called from base.o, so their wrappers note it here.
// What goes to the GPU is what citro3d sent: its function sends it, with
// the same flags, whenever it has anything to send.
//
// Then the float uniforms themselves (TASKS 46). A model changes its mvp,
// fog and light rows, so nearly a thousand draws a frame find some dirty,
// and citro3d's walk sends them: a byte at a time over all 96 flags, two
// GPUCMD_Add calls a run, newlib's word-at-a-time memcpy and two memsets.
// Azahar's samples put that walk and its calls at about a fifth of the
// models' time. send_floats sends the same words itself: for each run of
// dirty registers, FLOATUNIFORM_CONFIG with the run's first in 32-bit
// mode, then the run's words to FLOATUNIFORM_DATA as one GPUCMD_Add
// writes them, its padding word too. The flags are cleared as citro3d
// clears them. citro3d also marks what it sent "ever dirty", in a table
// of uniforms.o's own, so that C3Di_DirtyUniforms (after the HOME menu)
// marks it dirty again; s_ever keeps that for what is sent here, and
// __wrap_C3Di_DirtyUniforms marks it too. Whatever else is dirty -- the
// shader's constants, an integer or the bools -- is citro3d's to send, as
// before, after the floats as its own function orders them. The first 64
// sends go both ways, and one that differs leaves the floats to citro3d
// (check_floats; the log says "c3d: float uniforms sent here").
//
// Two more, for the race's lit batches and strips (step 13b-5), which set
// the same program and uniforms again for every draw:
//   * __wrap_C3D_BindProgram does nothing for the program citro3d has
//     already. citro3d's own would load that shader's constants again, and
//     send them again;
//   * c3d_unif_set and the rest (c3dwrap.h) leave a uniform alone when the
//     GPU holds its value already. citro3d's copy, C3D_FVUnif, is what the
//     GPU holds or is about to be sent, for a register set through it at
//     least once since the last program's constants: those go to the GPU
//     straight from the shader (C3Di_LoadShaderUniforms) and not through
//     the copy, so the registers they take are not known again until set.
//
// And the draws themselves (step 13b-6). C3D_DrawElements and
// C3D_DrawArrays write a draw as 15 and 11 single registers, each through
// libctru's GPUCMD_Add: about 700 instructions an indexed draw, where the
// words are the same every time but for the indices' offset and count.
// The race draws two thousand and more of them a frame. So:
//   * __wrap_C3D_DrawElements (triangles) and __wrap_C3D_DrawArrays bring
//     the state up to date as citro3d's do, with C3Di_UpdateContext, then
//     write the draw's words in one go from a template, and mark the frame
//     as drawn on, as citro3d's do. The first draw of each is citro3d's own,
//     and its words are compared with the template's: only when they match,
//     and the context's head below is where citro3d's is, are the next
//     draws written here (c3d_lean_state; main.c logs it);
//   * __wrap_GPUCMD_Add writes a single register's command itself, the
//     rest of citro3d's state does most of: the same two words libctru's
//     writes, without its loop.
//
// And the clears (TASKS 64). C3D_FrameBufClear clears a target's colour
// and depth with one GX_MemoryFill: the colour as its first buffer, on
// the PSC's first fill unit, and the depth as its second, on the other.
// __wrap_C3D_FrameBufClear makes a clear of both two fills, each on the
// first unit (4803cfc). That was for the user's road blink on track 31,
// on the theory that a list queued behind a clear could start while the
// depth fill was still going. It cannot: GSP runs the GX commands in its
// queue one after another. The blink stayed (the user, 2026-10-20); the
// two fills cost nothing seen, and stay.

#include <stdint.h>
#include <string.h>

#include <3ds.h>
#include <citro3d.h>

#include "c3dwrap.h"

typedef uint32_t __attribute__((may_alias)) u32_alias;

void __real_C3D_UpdateUniforms(GPU_SHADER_TYPE type);
void __real_C3Di_LoadShaderUniforms(shaderInstance_s* si);
void __real_C3Di_DirtyUniforms(GPU_SHADER_TYPE type);
void __real_C3D_BindProgram(shaderProgram_s* program);
void __real_C3D_DrawElements(GPU_Primitive_t primitive, int count, int type,
                             const void* indices);
void __real_C3D_DrawArrays(GPU_Primitive_t primitive, int first, int size);
void __real_GPUCMD_Add(u32 header, const u32* param, u32 paramlength);
void __real_C3D_FrameBufClear(C3D_FrameBuf* fb, C3D_ClearBits clearBits,
                              u32 clearColor, u32 clearDepth);

void __wrap_C3D_UpdateUniforms(GPU_SHADER_TYPE type);
void __wrap_C3Di_LoadShaderUniforms(shaderInstance_s* si);
void __wrap_C3Di_DirtyUniforms(GPU_SHADER_TYPE type);
void __wrap_C3D_BindProgram(shaderProgram_s* program);
void __wrap_C3D_DrawElements(GPU_Primitive_t primitive, int count, int type,
                             const void* indices);
void __wrap_C3D_DrawArrays(GPU_Primitive_t primitive, int first, int size);
void __wrap_GPUCMD_Add(u32 header, const u32* param, u32 paramlength);
void __wrap_C3D_FrameBufClear(C3D_FrameBuf* fb, C3D_ClearBits clearBits,
                              u32 clearColor, u32 clearDepth);

// citro3d's own, from base.o.
void C3Di_UpdateContext(void);

// The head of citro3d's C3D_Context, as its source/internal.h has it in
// the release devkitPro ships (1.7.1, 2023-10-28): the flags, and the
// vertex buffers' base the index buffer's offset is from.
typedef struct {
    gxCmdQueue_s     gxQueue;
    u32*             cmdBuf;
    size_t           cmdBufSize;
    float            cmdBufUsage;
    u32              flags;
    shaderProgram_s* program;
    C3D_AttrInfo     attrInfo;
    C3D_BufInfo      bufInfo;
} C3DiContextHead;

extern C3DiContextHead __C3D_Context;

enum {
    C3DIF_ACTIVE    = 1u << 0,
    C3DIF_DRAW_USED = 1u << 1,
};

// Whether a shader's constants may be waiting, by shader type.
static bool s_constants[2] = { true, true };

// The program last bound.
static shaderProgram_s* s_program;

// The vertex shader's float registers whose value is C3D_FVUnif's, a bit
// each, and its bools likewise.
static uint32_t s_known[(C3D_FVUNIF_COUNT + 31) / 32];
static uint16_t s_boolKnown;

// The float registers send_floats has sent, by shader type, which citro3d
// would have marked ever dirty.
static uint32_t s_ever[2][(C3D_FVUNIF_COUNT + 31) / 32];

// The first FLOAT_CHECKS sends with floats in them are sent both ways and
// compared: send_floats's words, then citro3d's in their place. One that
// differs leaves the floats to citro3d for good. The log says which
// (main.c hands it over after C3D_Init, before any draw).
#define FLOAT_CHECKS 64
#define FLOAT_WORDS  (C3D_FVUNIF_COUNT * 4 + C3D_FVUNIF_COUNT / 2 * 4)
static int  s_floatChecks;
static bool s_floatsOff;
static u32  s_floatSent[FLOAT_WORDS];
static void (*s_log)(const char* fmt, ...);

// Blocks of command words, which the compiler copies with ldm and stm. A
// copy of more than 64 bytes at once is a call to newlib's memcpy, which
// goes a word at a time.
typedef struct {
    u32 w[4];
} __attribute__((may_alias)) Words4;
typedef struct {
    u32 w[6];
} __attribute__((may_alias)) Words6;
typedef struct {
    u32 w[14];
} __attribute__((may_alias)) Words14;
typedef struct {
    u32 w[16];
} __attribute__((may_alias)) Words16;

static bool any_set(const bool* flags, int n)
{
    uint32_t acc = 0;
    int      i   = 0;

    if (((uintptr_t)flags & 3) == 0) {
        const u32_alias* w = (const u32_alias*)flags;
        for (; i + 4 <= n; i += 4) {
            acc |= w[i / 4];
        }
    }
    for (; i < n; i++) {
        acc |= flags[i];
    }
    return acc != 0;
}

static u32* room(u32 n);

// The dirty float uniforms of shader type `t` sent as C3D_UpdateUniforms
// sends them, and their flags cleared. false, with nothing sent or cleared,
// where citro3d's should send them: flags off a word boundary, a run past
// one write's 256 words (GPUCMD_Add splits it), or no room (GPUCMD_Add
// stops the app). No loop here is a memset or memcpy call.
__attribute__((optimize("no-tree-loop-distribute-patterns")))
static bool send_floats(int t)
{
    bool*            dirty = C3D_FVUnifDirty[t];
    u32_alias*       dw    = (u32_alias*)dirty;
    u32              reg   = t ? GPUREG_GSH_FLOATUNIFORM_CONFIG
                               : GPUREG_VSH_FLOATUNIFORM_CONFIG;
    uint8_t          first[C3D_FVUNIF_COUNT / 2];
    uint8_t          count[C3D_FVUNIF_COUNT / 2];
    int              runs = 0, i = 0, r;
    u32              words = 0;
    u32*             w;

    if ((uintptr_t)dirty & 3) {
        return false;
    }
    // The runs, as citro3d's walk finds them: a run ends at a clear flag,
    // so the next starts past it.
    while (i < C3D_FVUNIF_COUNT) {
        int j;

        if ((i & 3) == 0 && dw[i >> 2] == 0) {
            i += 4;
            continue;
        }
        if (!dirty[i]) {
            i++;
            continue;
        }
        for (j = i + 1; j < C3D_FVUNIF_COUNT && dirty[j]; j++) {
        }
        if (j - i > 64) {
            return false;
        }
        first[runs] = (uint8_t)i;
        count[runs] = (uint8_t)(j - i);
        runs++;
        words += 4 * (u32)(j - i) + 4;
        i = j + 1;
    }
    if (runs == 0) {
        return true;
    }
    w = room(words);
    if (w == NULL) {
        return false;
    }
    for (r = 0; r < runs; r++) {
        const u32_alias* src = (const u32_alias*)&C3D_FVUnif[t][first[r]];
        u32              n   = 4 * (u32)count[r];
        u32              k;
        int              id, end = first[r] + count[r];

        // GPUCMD_AddWrite of the config, then GPUCMD_AddWrites of the
        // data: its first word, the header with the count less one, the
        // rest, and a zero after an odd count.
        w[0] = 0x80000000u | first[r];
        w[1] = GPUCMD_HEADER(0, 0xF, reg);
        w[2] = src[0];
        w[3] = GPUCMD_HEADER(0, 0xF, reg + 1) | ((n - 1) << 20);
        for (k = 1; k + 4 <= n; k += 4) {
            *(Words4*)(w + 3 + k) = *(const Words4*)(src + k);
        }
        w[3 + k] = src[k];
        w[4 + k] = src[k + 1];
        w[5 + k] = src[k + 2];
        w[3 + n] = 0;
        w += n + 4;
        // Every dirty flag is in a run, so the words the run spans clear.
        for (id = first[r] >> 2; id <= (end - 1) >> 2; id++) {
            dw[id] = 0;
        }
        for (id = first[r]; id < end; id++) {
            s_ever[t][id >> 5] |= 1u << (id & 31);
        }
    }
    gpuCmdBufOffset += words;
    return true;
}

// A send with only floats dirty, both ways: send_floats's words kept and
// taken back, the flags put back as they were, and citro3d's sent in their
// place, which stay.
static void check_floats(GPU_SHADER_TYPE type, int t)
{
    bool     dirty[C3D_FVUNIF_COUNT];
    uint32_t ever[(C3D_FVUNIF_COUNT + 31) / 32];
    u32      at = gpuCmdBufOffset, n;
    bool     same;

    memcpy(dirty, C3D_FVUnifDirty[t], sizeof dirty);
    memcpy(ever, s_ever[t], sizeof ever);
    if (!send_floats(t)) {
        __real_C3D_UpdateUniforms(type);
        return;
    }
    n = gpuCmdBufOffset - at;
    if (n == 0) {
        return;
    }
    memcpy(s_floatSent, gpuCmdBuf + at, n * sizeof *s_floatSent);
    gpuCmdBufOffset = at;
    memcpy(C3D_FVUnifDirty[t], dirty, sizeof dirty);
    memcpy(s_ever[t], ever, sizeof ever);
    __real_C3D_UpdateUniforms(type);
    same = gpuCmdBufOffset - at == n
           && memcmp(gpuCmdBuf + at, s_floatSent, n * sizeof *s_floatSent)
                  == 0;
    s_floatChecks++;
    if (!same) {
        s_floatsOff = true;
        if (s_log) {
            s_log("c3d: float uniforms citro3d's (send %d of %u words "
                  "differs, %u from citro3d)",
                  s_floatChecks, (unsigned)n,
                  (unsigned)(gpuCmdBufOffset - at));
        }
    } else if (s_floatChecks == FLOAT_CHECKS && s_log) {
        s_log("c3d: float uniforms sent here (%d sends matched citro3d's)",
              FLOAT_CHECKS);
    }
}

void __wrap_C3D_UpdateUniforms(GPU_SHADER_TYPE type)
{
    int t = type == GPU_GEOMETRY_SHADER ? 1 : 0;

    // With no geometry shader bound its uniforms are nobody's: they wait,
    // with their flags, for a program that has one.
    if (t == 1 && s_program != NULL && s_program->geometryShader == NULL) {
        return;
    }
    if (s_constants[t] || s_floatsOff) {
        s_constants[t] = false;
        __real_C3D_UpdateUniforms(type);
        return;
    }
    if (s_floatChecks < FLOAT_CHECKS && !C3D_BoolUnifsDirty[t]
        && !any_set(C3D_IVUnifDirty[t], C3D_IVUNIF_COUNT)) {
        check_floats(type, t);
        return;
    }
    if (!send_floats(t)) {
        __real_C3D_UpdateUniforms(type);
        return;
    }
    // The floats are clean now, so citro3d's sends only these.
    if (C3D_BoolUnifsDirty[t]
        || any_set(C3D_IVUnifDirty[t], C3D_IVUNIF_COUNT)) {
        __real_C3D_UpdateUniforms(type);
    }
}

void __wrap_C3Di_LoadShaderUniforms(shaderInstance_s* si)
{
    int i;

    s_constants[0] = true;
    s_constants[1] = true;
    if (si->dvle->type == VERTEX_SHDR) {
        for (i = 0; i < si->numFloat24Uniforms; i++) {
            uint32_t id = si->float24Uniforms[i].id;

            if (id < C3D_FVUNIF_COUNT) {
                s_known[id >> 5] &= ~(1u << (id & 31));
            }
        }
        // A program's own bools go into C3D_BoolUnifs, so the copy holds
        // them; none of the port's shaders has one.
    }
    __real_C3Di_LoadShaderUniforms(si);
}

void __wrap_C3D_BindProgram(shaderProgram_s* program)
{
    if (program != NULL && program == s_program) {
        return;
    }
    s_program = program;
    __real_C3D_BindProgram(program);
}

static bool known(int id)
{
    return (s_known[id >> 5] >> (id & 31) & 1u) != 0;
}

void c3d_unif_set(int id, float x, float y, float z, float w)
{
    C3D_FVec v;

    if (id < 0 || id >= C3D_FVUNIF_COUNT) {
        return;
    }
    v.x = x;
    v.y = y;
    v.z = z;
    v.w = w;
    // memcmp's equality, the bits, without its call.
    if (known(id)) {
        const u32_alias* a =
            (const u32_alias*)&C3D_FVUnif[GPU_VERTEX_SHADER][id];
        const u32_alias* b = (const u32_alias*)&v;

        if (a[0] == b[0] && a[1] == b[1] && a[2] == b[2] && a[3] == b[3]) {
            return;
        }
    }
    C3D_FVUnifSet(GPU_VERTEX_SHADER, id, x, y, z, w);
    s_known[id >> 5] |= 1u << (id & 31);
}

void c3d_unif_vec(int id, const float v[4])
{
    c3d_unif_set(id, v[0], v[1], v[2], v[3]);
}

void c3d_unif_mtx(int id, const C3D_Mtx* m)
{
    int i;

    if (id < 0 || id + 4 > C3D_FVUNIF_COUNT) {
        return;
    }
    if (known(id) && known(id + 1) && known(id + 2) && known(id + 3)
        && memcmp(&C3D_FVUnif[GPU_VERTEX_SHADER][id], m->r,
                  sizeof m->r) == 0) {
        return;
    }
    C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, id, m);
    for (i = id; i < id + 4; i++) {
        s_known[i >> 5] |= 1u << (i & 31);
    }
}

void c3d_unif_bool(int id, bool on)
{
    int      bit = id - 0x68;
    uint16_t m;

    if (bit < 0 || bit > 15) {
        return;
    }
    m = (uint16_t)(1u << bit);
    if ((s_boolKnown & m)
        && ((C3D_BoolUnifs[GPU_VERTEX_SHADER] & m) != 0) == on) {
        return;
    }
    C3D_BoolUnifSet(GPU_VERTEX_SHADER, id, on);
    s_boolKnown |= m;
}

void __wrap_C3Di_DirtyUniforms(GPU_SHADER_TYPE type)
{
    int t = type == GPU_GEOMETRY_SHADER ? 1 : 0;
    int id;

    s_constants[t] = true;
    __real_C3Di_DirtyUniforms(type);
    // What citro3d's table would hold of what send_floats sent.
    for (id = 0; id < C3D_FVUNIF_COUNT; id++) {
        if (s_ever[t][id >> 5] >> (id & 31) & 1u) {
            C3D_FVUnifDirty[t][id] = true;
        }
    }
}

// ------------------------------------------------------------- the draws

#define CMD(mask, reg) GPUCMD_HEADER(0, (mask), (reg))

// C3D_DrawElements' words for triangles: each register's value and then
// its header, as GPUCMD_Add writes a single one. The index buffer's offset
// and type go in at [4], the count at [6].
static const u32 s_elementWords[30] = {
    GPU_GEOMETRY_PRIM, CMD(0x2, GPUREG_PRIMITIVE_CONFIG),
    1,                 CMD(0xF, GPUREG_RESTART_PRIMITIVE),
    0,                 CMD(0xF, GPUREG_INDEXBUFFER_CONFIG),
    0,                 CMD(0xF, GPUREG_NUMVERTICES),
    0,                 CMD(0xF, GPUREG_VERTEX_OFFSET),
    0x100,             CMD(0x2, GPUREG_GEOSTAGE_CONFIG),
    0x100,             CMD(0x2, GPUREG_GEOSTAGE_CONFIG2),
    0,                 CMD(0x1, GPUREG_START_DRAW_FUNC0),
    1,                 CMD(0xF, GPUREG_DRAWELEMENTS),
    1,                 CMD(0x1, GPUREG_START_DRAW_FUNC0),
    0,                 CMD(0x2, GPUREG_GEOSTAGE_CONFIG),
    0,                 CMD(0x2, GPUREG_GEOSTAGE_CONFIG2),
    1,                 CMD(0xF, GPUREG_VTX_FUNC),
    0,                 CMD(0x8, GPUREG_PRIMITIVE_CONFIG),
    0,                 CMD(0x8, GPUREG_PRIMITIVE_CONFIG),
};

// C3D_DrawArrays' likewise: the primitive at [0], the count at [6] and the
// first vertex at [8].
static const u32 s_arrayWords[22] = {
    0,          CMD(0x2, GPUREG_PRIMITIVE_CONFIG),
    1,          CMD(0xF, GPUREG_RESTART_PRIMITIVE),
    0x80000000, CMD(0xF, GPUREG_INDEXBUFFER_CONFIG),
    0,          CMD(0xF, GPUREG_NUMVERTICES),
    0,          CMD(0xF, GPUREG_VERTEX_OFFSET),
    1,          CMD(0x1, GPUREG_GEOSTAGE_CONFIG2),
    0,          CMD(0x1, GPUREG_START_DRAW_FUNC0),
    1,          CMD(0xF, GPUREG_DRAWARRAYS),
    1,          CMD(0x1, GPUREG_START_DRAW_FUNC0),
    0,          CMD(0x1, GPUREG_GEOSTAGE_CONFIG2),
    1,          CMD(0xF, GPUREG_VTX_FUNC),
};

// Whether each kind of draw is written here: unknown until its first, then
// on or off for good.
enum { LEAN_UNKNOWN, LEAN_ON, LEAN_OFF };
static uint8_t s_leanElements;
static uint8_t s_leanArrays;

void c3d_lean_log(void (*fn)(const char* fmt, ...))
{
    s_log = fn;
}

// The command buffer's next `n` words, or NULL where GPUCMD_Add would stop
// for want of room.
static u32* room(u32 n)
{
    if (gpuCmdBuf == NULL || gpuCmdBufOffset + n > gpuCmdBufSize) {
        return NULL;
    }
    return gpuCmdBuf + gpuCmdBufOffset;
}

// Whether citro3d's context is where C3DiContextHead has it, just after a
// draw of citro3d's own: on, with a draw in the frame, the command buffer
// inside the one C3D_Init made, and the vertex buffers' base the one
// BufInfo_Init sets.
static bool head_ok(void)
{
    const C3DiContextHead* c    = &__C3D_Context;
    u32                    want = C3DIF_ACTIVE | C3DIF_DRAW_USED;

    return (c->flags & want) == want && c->cmdBuf != NULL
           && gpuCmdBuf >= c->cmdBuf
           && gpuCmdBuf + gpuCmdBufSize <= c->cmdBuf + c->cmdBufSize
           && c->bufInfo.base_paddr == 0x18000000;
}

// A first draw: citro3d's, from a context with nothing left to send, and
// its words against the template's.
static uint8_t check(const char* what, u32 at, const u32* words, u32 n)
{
    bool same = head_ok() && gpuCmdBufOffset - at == n
                && memcmp(gpuCmdBuf + at, words, n * sizeof *words) == 0;

    if (s_log) {
        s_log("c3d: %s draws %s", what,
              same ? "written here" : "citro3d's (its words differ)");
    }
    return same ? LEAN_ON : LEAN_OFF;
}

void __wrap_C3D_DrawElements(GPU_Primitive_t primitive, int count, int type,
                             const void* indices)
{
    u32  pa, base;
    u32* w;

    if (primitive != GPU_TRIANGLES || s_leanElements == LEAN_OFF) {
        __real_C3D_DrawElements(primitive, count, type, indices);
        return;
    }
    pa   = osConvertVirtToPhys(indices);
    base = __C3D_Context.bufInfo.base_paddr;
    if (s_leanElements == LEAN_UNKNOWN) {
        u32 words[30];
        u32 at;

        C3Di_UpdateContext();
        at = gpuCmdBufOffset;
        __real_C3D_DrawElements(primitive, count, type, indices);
        memcpy(words, s_elementWords, sizeof words);
        words[4] = (pa - base) | ((u32)type << 31);
        words[6] = (u32)count;
        s_leanElements = check("indexed", at, words, 30);
        return;
    }
    if (pa < base) {
        return;
    }
    C3Di_UpdateContext();
    w = room(30);
    if (w == NULL) {
        // citro3d's, to stop where it stops.
        __real_C3D_DrawElements(primitive, count, type, indices);
        return;
    }
    *(Words16*)w        = *(const Words16*)s_elementWords;
    *(Words14*)(w + 16) = *(const Words14*)(s_elementWords + 16);
    w[4] = (pa - base) | ((u32)type << 31);
    w[6] = (u32)count;
    gpuCmdBufOffset += 30;
    __C3D_Context.flags |= C3DIF_DRAW_USED;
}

void __wrap_C3D_DrawArrays(GPU_Primitive_t primitive, int first, int size)
{
    u32* w;

    if (s_leanArrays == LEAN_OFF) {
        __real_C3D_DrawArrays(primitive, first, size);
        return;
    }
    if (s_leanArrays == LEAN_UNKNOWN) {
        u32 words[22];
        u32 at;

        C3Di_UpdateContext();
        at = gpuCmdBufOffset;
        __real_C3D_DrawArrays(primitive, first, size);
        memcpy(words, s_arrayWords, sizeof words);
        words[0] = (u32)primitive;
        words[6] = (u32)size;
        words[8] = (u32)first;
        s_leanArrays = check("array", at, words, 22);
        return;
    }
    C3Di_UpdateContext();
    w = room(22);
    if (w == NULL) {
        __real_C3D_DrawArrays(primitive, first, size);
        return;
    }
    *(Words16*)w       = *(const Words16*)s_arrayWords;
    *(Words6*)(w + 16) = *(const Words6*)(s_arrayWords + 16);
    w[0] = (u32)primitive;
    w[6] = (u32)size;
    w[8] = (u32)first;
    gpuCmdBufOffset += 22;
    __C3D_Context.flags |= C3DIF_DRAW_USED;
}

// One register: its value, then its header with no more to follow, as
// libctru's writes it. Anything longer, or with no value (zeros), and the
// buffer's end are libctru's.
void __wrap_GPUCMD_Add(u32 header, const u32* param, u32 paramlength)
{
    u32 off = gpuCmdBufOffset;

    if (paramlength == 1 && param != NULL && gpuCmdBuf != NULL
        && off + 2 <= gpuCmdBufSize) {
        gpuCmdBuf[off]     = *param;
        gpuCmdBuf[off + 1] = header;
        gpuCmdBufOffset    = off + 2;
        return;
    }
    __real_GPUCMD_Add(header, param, paramlength);
}

// A clear of colour and depth, as two fills: the colour's, then the
// depth's, each its fill's only buffer, so GSP signals each one's end
// (the header's note). A target with no depth buffer has one fill.
void __wrap_C3D_FrameBufClear(C3D_FrameBuf* fb, C3D_ClearBits clearBits,
                              u32 clearColor, u32 clearDepth)
{
    if ((clearBits & C3D_CLEAR_ALL) == C3D_CLEAR_ALL && fb->depthBuf != NULL) {
        __real_C3D_FrameBufClear(fb, C3D_CLEAR_COLOR, clearColor, clearDepth);
        __real_C3D_FrameBufClear(fb, C3D_CLEAR_DEPTH, clearColor, clearDepth);
        return;
    }
    __real_C3D_FrameBufClear(fb, clearBits, clearColor, clearDepth);
}
