// estripdata -- eStripData's vertex accessors (retail 0x0011bf98 ..
// 0x0011c398) and CallDamageVertexFunctionForEveryVertex (0x00104100), the
// walk BodyDamage dents a model's vertices with.
//
// An eStripEntry's Data is its strip's VU1 packet: the VIF codes and what
// they unpack, back to back. eStripData reads a vertex's fields where the
// unpacks keep them, stepping over each VIF code's word, so the walk
// changes the packet the renderer draws from. On the disc's 441,933 car
// vertices the accessors read what geometry.c's replay of the VIF decodes.
//
//   the packet header, bytes 4 to 7        NumVerts, NumLoops, Flags,
//                                          LightMatIndex
//   x y z, from byte 28                    four vertices to 48 bytes, x y z
//                                          a quadword each, after a VIF
//                                          word; the last n % 4 after one
//                                          more, x y z each that many floats
//   RGBA, after the ST                     a halfword each, RGBA5551
//
// Port's: the walk ends by telling the renderer, through
// gESolidVerticesChangedFn, that the solid's packet and strip flags may
// have changed, since the port draws a solid from meshes baked out of
// them (trackview.c).

#ifndef ESTRIPDATA_H
#define ESTRIPDATA_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "emodel.h"

// eStripEntry's Flags the walk reads and writes: 0x800 a scuff strip, whose
// vertices take the damage's alpha, and 0x400 a strip RenderStrips skips.
#define ESTRIP_SCUFFS   0x0800u
#define ESTRIP_HIDDEN   0x0400u

// GetNumVerts, 0x0011c248: the header's byte 4.
int32_t estripdata_num_verts(const uint8_t *d);

// GetElementXYZ(int, float **, float **, float **), 0x0011bf98: where
// vertex `i`'s x, y and z are, as offsets from `d`.
void estripdata_element_xyz(const uint8_t *d, int32_t i, size_t off[3]);

// GetElementRGBA(int, unsigned short **), 0x0011c180: where vertex `i`'s
// colour is, as an offset from `d`. It is always even.
size_t estripdata_element_rgba(const uint8_t *d, int32_t i);

// GetXYZ(int, float *, float *, float *), 0x0011c2b8, and SetXYZ(int,
// float, float, float), 0x0011c338.
void estripdata_get_xyz(const uint8_t *d, int32_t i, float *x, float *y,
                        float *z);
void estripdata_set_xyz(uint8_t *d, int32_t i, float x, float y, float z);

// The function the walk calls for each vertex: the caller's pointer, the
// vertex's number over the whole solid, its position (a copy, written back
// after), its colour in the packet, a pointer the walk passes as NULL, and
// the strip's Flags & ESTRIP_SCUFFS. Nonzero says the vertex shows.
typedef int32_t (*EDamageVertexFn)(void *user, int32_t vertex, bVector3 *pos,
                                   uint16_t *colour, float *unused,
                                   int32_t polys);

// CallDamageVertexFunctionForEveryVertex(eModel *, BodyDamageModel *, fn),
// 0x00104100. Nothing for a model with no solid. Otherwise every strip's
// every vertex, in order: its position read, `fn`, and the position
// written back. A scuff strip with any vertex that shows loses
// ESTRIP_HIDDEN, and one with none gets it. Then the seam.
void ecall_damage_vertex_function_for_every_vertex(eModel *m, void *user,
                                                   EDamageVertexFn fn);

// Port's, NULL by default: called at the end of every walk over a solid.
extern void (*gESolidVerticesChangedFn)(const eSolid *s);

#endif
