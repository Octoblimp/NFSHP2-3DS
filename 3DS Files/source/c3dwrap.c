// citro3d's uniform upload, skipped when no uniform has changed (step 13b-4).
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

void __wrap_C3D_UpdateUniforms(GPU_SHADER_TYPE type);
void __wrap_C3Di_LoadShaderUniforms(shaderInstance_s* si);
void __wrap_C3Di_DirtyUniforms(GPU_SHADER_TYPE type);
void __wrap_C3D_BindProgram(shaderProgram_s* program);
void __wrap_C3D_DrawElements(GPU_Primitive_t primitive, int count, int type,
                             const void* indices);
void __wrap_C3D_DrawArrays(GPU_Primitive_t primitive, int first, int size);
void __wrap_GPUCMD_Add(u32 header, const u32* param, u32 paramlength);

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

void __wrap_C3D_UpdateUniforms(GPU_SHADER_TYPE type)
{
    int t = type == GPU_GEOMETRY_SHADER ? 1 : 0;

    // With no geometry shader bound its uniforms are nobody's: they wait,
    // with their flags, for a program that has one.
    if (t == 1 && s_program != NULL && s_program->geometryShader == NULL) {
        return;
    }
    if (!s_constants[t] && !C3D_BoolUnifsDirty[t]
        && !any_set(C3D_IVUnifDirty[t], C3D_IVUNIF_COUNT)
        && !any_set(C3D_FVUnifDirty[t], C3D_FVUNIF_COUNT)) {
        return;
    }
    s_constants[t] = false;
    __real_C3D_UpdateUniforms(type);
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
    if (known(id)
        && memcmp(&C3D_FVUnif[GPU_VERTEX_SHADER][id], &v, sizeof v) == 0) {
        return;
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
    s_constants[type == GPU_GEOMETRY_SHADER ? 1 : 0] = true;
    __real_C3Di_DirtyUniforms(type);
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
static void (*s_log)(const char* fmt, ...);

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
    memcpy(w, s_elementWords, sizeof s_elementWords);
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
    memcpy(w, s_arrayWords, sizeof s_arrayWords);
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
