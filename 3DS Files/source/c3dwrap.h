// citro3d's uniforms and program binds, sent only when they change (step
// 13b-4, 13b-5), its draws written in one go (13b-6), and its clears of
// colour and depth made two fills (TASKS 64). See c3dwrap.c.

#ifndef C3DWRAP_H
#define C3DWRAP_H

#include <stdbool.h>

#include <citro3d.h>

// The vertex shader's float uniform `id` set to (x, y, z, w), or its four
// rows from `id` to the matrix's, and its bool uniform `id` to `on`, each
// only when the GPU does not hold that already: citro3d sends a uniform it
// is handed again whatever it holds.
void c3d_unif_set(int id, float x, float y, float z, float w);
void c3d_unif_vec(int id, const float v[4]);
void c3d_unif_mtx(int id, const C3D_Mtx* m);
void c3d_unif_bool(int id, bool on);

// Where to say, once each, whether the indexed and the array draws are
// written by c3dwrap.c or left to citro3d.
void c3d_lean_log(void (*fn)(const char* fmt, ...));

#endif
