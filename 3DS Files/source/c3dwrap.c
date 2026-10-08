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

void __wrap_C3D_UpdateUniforms(GPU_SHADER_TYPE type);
void __wrap_C3Di_LoadShaderUniforms(shaderInstance_s* si);
void __wrap_C3Di_DirtyUniforms(GPU_SHADER_TYPE type);
void __wrap_C3D_BindProgram(shaderProgram_s* program);

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
