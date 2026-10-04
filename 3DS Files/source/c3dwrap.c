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

#include <stdint.h>

#include <3ds.h>
#include <citro3d.h>

typedef uint32_t __attribute__((may_alias)) u32_alias;

void __real_C3D_UpdateUniforms(GPU_SHADER_TYPE type);
void __real_C3Di_LoadShaderUniforms(shaderInstance_s* si);
void __real_C3Di_DirtyUniforms(GPU_SHADER_TYPE type);

void __wrap_C3D_UpdateUniforms(GPU_SHADER_TYPE type);
void __wrap_C3Di_LoadShaderUniforms(shaderInstance_s* si);
void __wrap_C3Di_DirtyUniforms(GPU_SHADER_TYPE type);

// Whether a shader's constants may be waiting, by shader type.
static bool s_constants[2] = { true, true };

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
    s_constants[0] = true;
    s_constants[1] = true;
    __real_C3Di_LoadShaderUniforms(si);
}

void __wrap_C3Di_DirtyUniforms(GPU_SHADER_TYPE type)
{
    s_constants[type == GPU_GEOMETRY_SHADER ? 1 : 0] = true;
    __real_C3Di_DirtyUniforms(type);
}
