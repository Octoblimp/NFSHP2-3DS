// estripdata -- see estripdata.h.

#include "estripdata.h"

#include <string.h>

#include "esolid.h"

void (*gESolidVerticesChangedFn)(const eSolid *s);

int32_t estripdata_num_verts(const uint8_t *d)
{
    return d[4];
}

// The groups of four take 48 bytes and a VIF word each. Past them the last
// n % 4 vertices' x, y and z are rem floats each, after a word of their own
// and, with any group before them, the group's word too.
void estripdata_element_xyz(const uint8_t *d, int32_t i, size_t off[3])
{
    int32_t n = estripdata_num_verts(d);
    int32_t full = n >> 2;
    int32_t rem = n - (full << 2);
    int32_t lane = i & 3;
    size_t  p = 28;

    if (i < full << 2) {
        p += (size_t)((i >> 2) * 48 + 4);
        off[0] = p + (size_t)(lane * 4);
        off[1] = p + (size_t)(lane * 4 + 16);
        off[2] = p + (size_t)(lane * 4 + 32);
        return;
    }
    if (full != 0)
        p += (size_t)((i >> 2) * 48 + 4);
    p += 4;
    off[0] = p + (size_t)(lane * 4);
    off[1] = p + (size_t)((rem + lane) * 4);
    off[2] = p + (size_t)((rem * 2 + lane) * 4);
}

// Past the xyz, 12 bytes a vertex and a word, and another when n % 4
// vertices follow at least one group; then the ST, 8 bytes a vertex and a
// word, and another when an odd vertex follows at least one pair; then two
// words, and the colours.
size_t estripdata_element_rgba(const uint8_t *d, int32_t i)
{
    int32_t n = estripdata_num_verts(d);
    size_t  p = 28;

    p += (size_t)(n * 12 + 4);
    if ((n >> 2) << 2 < n && (n >> 2) != 0)
        p += 4;
    p += (size_t)(n * 8 + 4);
    if ((n >> 1) << 1 < n && (n >> 1) != 0)
        p += 4;
    return p + 4 + (size_t)(i * 2);
}

void estripdata_get_xyz(const uint8_t *d, int32_t i, float *x, float *y,
                        float *z)
{
    size_t off[3];

    estripdata_element_xyz(d, i, off);
    memcpy(x, d + off[0], 4);
    memcpy(y, d + off[1], 4);
    memcpy(z, d + off[2], 4);
}

void estripdata_set_xyz(uint8_t *d, int32_t i, float x, float y, float z)
{
    size_t off[3];

    estripdata_element_xyz(d, i, off);
    memcpy(d + off[0], &x, 4);
    memcpy(d + off[1], &y, 4);
    memcpy(d + off[2], &z, 4);
}

// The count of the solid's strips is read once, and each strip's Flags
// again after its vertices.
void ecall_damage_vertex_function_for_every_vertex(eModel *m, void *user,
                                                   EDamageVertexFn fn)
{
    eSolid  *s = (eSolid *)m->Solid;
    int32_t  vertex = 0;
    int32_t  n, i;

    if (s == NULL)
        return;
    n = s->NumStrips;
    for (i = 0; i < n; i++) {
        eStripEntry *e = (eStripEntry *)s->StripEntryTable + i;
        int32_t      polys = e->Flags & ESTRIP_SCUFFS;
        int32_t      nv = e->NumVerts;
        uint8_t     *d = e->Data;
        int32_t      any = 0;
        int32_t      v;

        for (v = 0; v < nv; v++) {
            bVector3 pos;
            uint16_t *colour;

            pos.pad = 0.0f;
            estripdata_get_xyz(d, v, &pos.x, &pos.y, &pos.z);
            colour = (uint16_t *)(void *)(d + estripdata_element_rgba(d, v));
            any |= fn(user, vertex, &pos, colour, NULL, polys);
            vertex++;
            estripdata_set_xyz(d, v, pos.x, pos.y, pos.z);
        }
        if (polys != 0) {
            if (any != 0)
                e->Flags = (uint16_t)(e->Flags & ~ESTRIP_HIDDEN);
            else
                e->Flags = (uint16_t)(e->Flags | ESTRIP_HIDDEN);
        }
    }
    if (gESolidVerticesChangedFn != NULL)
        gESolidVerticesChangedFn(s);
}
