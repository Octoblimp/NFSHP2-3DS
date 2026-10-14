// geobake -- see geobake.h.

#include "geobake.h"

#include <stdlib.h>
#include <string.h>

#include "estripdata.h"

#ifdef __3DS__
#include <3ds.h>
#define block_alloc linearAlloc
#define block_free  linearFree
#else
#define block_alloc malloc
#define block_free  free
#endif

// The bake's working buffers, a few hundred KB for a car's body, come
// from the linear heap, which has megabytes free in a race; the main
// heap's largest free block can be under 128 KB by then, and a body
// that will not bake does not draw.
static void* scratch_alloc(size_t n)
{
    return block_alloc(n);
}

static void scratch_free(void* p)
{
    if (p != NULL) {
        block_free(p);
    }
}

// Strips are baked in texture order so that a solid draws in one call per
// distinct texture rather than one per strip -- and within a texture by
// flags and light material, which a batch has one of. eSolid does not store them
// that way, so this is a pass over the entry table first -- which is cheap,
// because eStripEntry carries NumVerts, NumPolys and TextureNumber and none
// of them need the packet replayed to read. See the note in
// docs/formats/solid-geometry.md about the entry table being a redundant
// copy of the packet header; this is what that redundancy buys.
typedef struct {
    int      texture;
    int      strip;
    uint16_t flags;             // less ESTRIP_HIDDEN
    int8_t   lightMaterial;
    bool     hidden;            // ESTRIP_HIDDEN
} StripOrder;

// An editable mesh's strips. `vertFirst` is each strip's first entry in
// `remap`, in the entry table's order, and one past the last; `remap` is
// each strip vertex's vertex in the mesh, or NO_VERTEX for one that no
// triangle uses or whose strip did not bake. Each scuff strip that baked
// is a toggle, with its indices as baked kept in `indices`.
//
// A mesh vertex can be several strips' vertices, as the bake keeps one of
// each it meets. CarDamage's walk leaves them alike: on the disc's 115
// solids that have a BodyDamageInfo, the 107,961 strip vertices that the
// bake merges have the same key (zone, dent and colour step) and the same
// scuff flag as the vertex they merge with.
#define NO_VERTEX 0xffffu

typedef struct {
    int32_t strip;
    int32_t first;              // its first index in the mesh's ibo
    int32_t count;              // and how many
    int32_t kept;               // its first in `indices`
} GeoToggle;

struct GeoMeshEdit {
    int        numStrips;
    int32_t*   vertFirst;
    uint16_t*  remap;
    int        numToggles;
    GeoToggle* toggle;
    uint16_t*  indices;
};

static int order_cmp(const void* a, const void* b)
{
    const StripOrder* x = (const StripOrder*)a;
    const StripOrder* y = (const StripOrder*)b;

    if (x->texture != y->texture) {
        return x->texture < y->texture ? -1 : 1;
    }
    if (x->flags != y->flags) {
        return x->flags < y->flags ? -1 : 1;
    }
    if (x->lightMaterial != y->lightMaterial) {
        return x->lightMaterial < y->lightMaterial ? -1 : 1;
    }
    // Ties keep file order, so a solid bakes the same way every time.
    return x->strip < y->strip ? -1 : (x->strip > y->strip ? 1 : 0);
}

// RGBA5551 widened as the VIF's V4-5 unpack widens it, c << 3, which is
// what the GS's modulate and the lighter's CBVMix both count in: 0x80 is
// 1.0 to the GS, so a full 248 nearly doubles a texture.
static void put_colour(GeoRenderVertex* dst, uint16_t colour)
{
    uint8_t rgba[4];

    geo_unpack_colour(colour, rgba);
    dst->colour[0] = (uint8_t)(rgba[0] << 3);
    dst->colour[1] = (uint8_t)(rgba[1] << 3);
    dst->colour[2] = (uint8_t)(rgba[2] << 3);
    dst->colour[3] = rgba[3] ? 255u : 0u;
}

static void put_vertex(GeoRenderVertex* dst, const GeoStrip* s, int v)
{
    const GeoVertex* src = &s->vert[v];
    int              i;

    for (i = 0; i < 3; i++) {
        dst->pos[i] = src->pos[i];
    }
    dst->st[0] = src->st[0];
    dst->st[1] = src->st[1];
    put_colour(dst, src->colour);

    if (s->hasNormals) {
        for (i = 0; i < 3; i++) {
            dst->normal[i] = src->normal[i];
        }
    } else {
        // 17% of strips carry no normal field. Facing the viewer is the
        // least wrong constant: it makes them fully lit rather than black.
        dst->normal[0] = 0;
        dst->normal[1] = 0;
        dst->normal[2] = 127;
    }
    dst->pad = 0;
}

// A batch is an indexed triangle list: its triangles in the strips' order,
// three 16-bit indices each into the mesh's vertices. A vertex goes in
// once however many triangles and strips share it -- the same position,
// ST, colour and normal, byte for byte -- so the PICA fetches it once, and
// its post-vertex cache (which C3D_DrawElements clears after each draw)
// shades a corner the last few triangles had once. The shipped strips are
// mostly runs of separate quads cut by ADC restarts, so a GPU strip saves
// little: TRACKB12's 133,795 triangles are 401,385 vertices as a list and
// 335,909 as strips joined by degenerates, but 176,505 indexed, and with a
// cache of 4 the GPU shades 1.70 a triangle where the list shaded 3. The
// draw order of the triangles is the list's.
typedef struct {
    GeoRenderVertex* vert;      // scratch, the entries' NumVerts summed
    int32_t*         slot;      // the hash's: a vertex, or -1
    uint32_t         mask;      // its size less 1, a power of two
    int              n;
} VertexSet;

static uint32_t vertex_hash(const GeoRenderVertex* v)
{
    const uint8_t* p = (const uint8_t*)v;
    uint32_t       h = 2166136261u;
    size_t         i;

    for (i = 0; i < sizeof *v; i++) {
        h = (h ^ p[i]) * 16777619u;
    }
    return h;
}

// The index of a vertex the same as `v`, which is added if there is none.
static int vertex_index(VertexSet* s, const GeoRenderVertex* v)
{
    uint32_t h = vertex_hash(v) & s->mask;

    while (s->slot[h] >= 0) {
        if (!memcmp(&s->vert[s->slot[h]], v, sizeof *v)) {
            return s->slot[h];
        }
        h = (h + 1) & s->mask;
    }
    s->vert[s->n] = *v;
    s->slot[h]    = s->n;
    return s->n++;
}

// The edit's one block, from the linear heap like the scratch: the toggles,
// vertFirst, remap and the kept indices, after the struct.
static GeoMeshEdit* edit_alloc(int numStrips, int numRemap, int numToggles,
                               int numKept)
{
    size_t       bytes = sizeof(GeoMeshEdit)
                         + (size_t)numToggles * sizeof(GeoToggle)
                         + (size_t)(numStrips + 1) * sizeof(int32_t)
                         + (size_t)numRemap * sizeof(uint16_t)
                         + (size_t)numKept * sizeof(uint16_t);
    GeoMeshEdit* e     = (GeoMeshEdit*)block_alloc(bytes);
    uint8_t*     p;

    if (e == NULL) {
        return NULL;
    }
    p             = (uint8_t*)(e + 1);
    e->numStrips  = numStrips;
    e->numToggles = numToggles;
    e->toggle     = (GeoToggle*)p;
    p            += (size_t)numToggles * sizeof(GeoToggle);
    e->vertFirst  = (int32_t*)p;
    p            += (size_t)(numStrips + 1) * sizeof(int32_t);
    e->remap      = (uint16_t*)p;
    p            += (size_t)numRemap * sizeof(uint16_t);
    e->indices    = (uint16_t*)p;
    return e;
}

static bool bake(const GeoSolid* solid, GeoMesh* out, bool editable)
{
    StripOrder*    order;
    GeoStrip*      strip;
    VertexSet      set     = { 0 };
    uint16_t*      idx;
    int32_t*       vertFirst = NULL;
    uint16_t*      remap     = NULL;
    GeoToggle*     toggle    = NULL;
    int            numToggles = 0;
    int            numTris = 0;
    int            cap     = 0;
    int            n       = 0;
    int            i;
    int            at      = 0;
    size_t         vbytes;
    size_t         ibytes;
    int            numClusters = 0;
    uint32_t       size;

    memset(out, 0, sizeof *out);
    for (i = 0; i < 3; i++) {
        out->aabbMin[i] = solid->aabbMin[i];
        out->aabbMax[i] = solid->aabbMax[i];
    }
    if (solid->numStrips <= 0) {
        return true;
    }

    // NumVerts and NumPolys from the entry table are the header's, so the
    // buffers can be sized without decoding anything: no more vertices than
    // the strips have, and three indices a triangle.
    for (i = 0; i < solid->numStrips; i++) {
        GeoStripEntry entry;

        if (geo_strip_entry(solid, i, &entry) != GEO_OK) {
            continue;
        }
        if (entry.numPolys > 0) {
            cap += entry.numVerts;
        }
        numTris += entry.numPolys;
    }
    if (numTris <= 0 || cap <= 0) {
        return true;
    }

    for (size = 1; size < 2u * (uint32_t)cap; size <<= 1) {
    }
    order    = (StripOrder*)scratch_alloc((size_t)solid->numStrips * sizeof *order);
    strip    = (GeoStrip*)scratch_alloc(sizeof *strip);
    set.vert = (GeoRenderVertex*)scratch_alloc((size_t)cap * sizeof *set.vert);
    set.slot = (int32_t*)scratch_alloc((size_t)size * sizeof *set.slot);
    idx      = (uint16_t*)scratch_alloc((size_t)numTris * 3u * sizeof *idx);
    if (editable) {
        vertFirst = (int32_t*)scratch_alloc((size_t)(solid->numStrips + 1)
                                     * sizeof *vertFirst);
        toggle    = (GeoToggle*)scratch_alloc((size_t)solid->numStrips
                                       * sizeof *toggle);
    }
    if (!order || !strip || !set.vert || !set.slot || !idx
        || (editable && (!vertFirst || !toggle))) {
        scratch_free(order);
        scratch_free(strip);
        scratch_free(set.vert);
        scratch_free(set.slot);
        scratch_free(idx);
        scratch_free(vertFirst);
        scratch_free(toggle);
        return false;
    }
    memset(set.slot, 0xff, (size_t)size * sizeof *set.slot);
    set.mask = size - 1u;

    // Every strip's vertices, in the order the walk counts them.
    if (editable) {
        vertFirst[0] = 0;
        for (i = 0; i < solid->numStrips; i++) {
            GeoStripEntry entry;

            vertFirst[i + 1] = vertFirst[i];
            if (geo_strip_entry(solid, i, &entry) == GEO_OK) {
                vertFirst[i + 1] += entry.numVerts;
            }
        }
        remap = (uint16_t*)scratch_alloc((size_t)(vertFirst[solid->numStrips] + 1)
                                  * sizeof *remap);
        if (remap == NULL) {
            scratch_free(order);
            scratch_free(strip);
            scratch_free(set.vert);
            scratch_free(set.slot);
            scratch_free(idx);
            scratch_free(vertFirst);
            scratch_free(toggle);
            return false;
        }
        memset(remap, 0xff, (size_t)(vertFirst[solid->numStrips] + 1)
                            * sizeof *remap);
    }

    for (i = 0; i < solid->numStrips; i++) {
        GeoStripEntry entry;
        bool          hidden;

        if (geo_strip_entry(solid, i, &entry) != GEO_OK) {
            out->skippedStrips++;
            continue;
        }
        // RenderStrips skips a hidden strip. An editable mesh keeps its
        // scuff strips however they are now, as the walk can show them.
        hidden = (entry.flags & ESTRIP_HIDDEN) != 0;
        if (hidden && !(editable && (entry.flags & ESTRIP_SCUFFS))) {
            continue;
        }
        // TextureNumber is one past the end on 25 strips across the disc --
        // the untextured sentinel. Normalise it to -1 here so the draw does
        // not have to know about it.
        order[n].texture = (entry.textureNumber >= 0
                            && entry.textureNumber < solid->numTextures)
                         ? entry.textureNumber : -1;
        order[n].strip   = i;
        order[n].flags   = (uint16_t)(entry.flags & ~ESTRIP_HIDDEN);
        order[n].lightMaterial = (int8_t)entry.lightMaterial;
        order[n].hidden  = hidden;
        n++;
    }

    qsort(order, (size_t)n, sizeof *order, order_cmp);

    for (i = 0; i < n; i++) {
        GeoBatch* batch;
        int       local[GEO_MAX_STRIP_VERTS];
        int       t, c;
        int       first;

        if (geo_decode_strip(solid, order[i].strip, strip) != GEO_OK) {
            out->skippedStrips++;
            continue;
        }

        // A new batch whenever the texture, the flags or the material
        // changes, which after the sort is once per distinct three. The cap
        // is a guard, not a limit that the data reaches: the most on the
        // disc is 34, TRN_SECTION40B's in TRACKB46.
        if (out->numBatches == 0
            || out->batch[out->numBatches - 1].texture != order[i].texture
            || out->batch[out->numBatches - 1].flags != order[i].flags
            || out->batch[out->numBatches - 1].lightMaterial
                   != order[i].lightMaterial) {
            if (out->numBatches >= GEO_MAX_BATCHES) {
                break;
            }
            batch = &out->batch[out->numBatches++];
            batch->first   = at;
            batch->count   = 0;
            batch->texture = order[i].texture;
            batch->strip   = order[i].strip;
            batch->flags   = order[i].flags;
            batch->lightMaterial = order[i].lightMaterial;
        }
        batch = &out->batch[out->numBatches - 1];

        // The entry's NumVerts and NumPolys sized the buffers; a strip that
        // decodes to more than they claimed would run past the end. It
        // never happens -- the cross-check compares them on all 18,848
        // strips -- but the buffers are the one thing here that cannot be
        // allowed to depend on that holding. Nor can a 16-bit index.
        if (at + 3 * strip->numTris > numTris * 3
            || set.n + strip->numVerts > cap
            || set.n + strip->numVerts > 65536) {
            out->skippedStrips++;
            continue;
        }
        for (c = 0; c < strip->numVerts; c++) {
            local[c] = -1;
        }
        first = at;
        for (t = 0; t < strip->numTris; t++) {
            for (c = 0; c < 3; c++) {
                int v = strip->tri[t][c];

                if (local[v] < 0) {
                    GeoRenderVertex r;

                    put_vertex(&r, strip, v);
                    local[v] = vertex_index(&set, &r);
                }
                idx[at++] = (uint16_t)local[v];
            }
            batch->count += 3;
            out->numTris++;
        }
        if (editable) {
            int s    = order[i].strip;
            int have = vertFirst[s + 1] - vertFirst[s];

            for (c = 0; c < strip->numVerts && c < have; c++) {
                if (local[c] >= 0) {
                    remap[vertFirst[s] + c] = (uint16_t)local[c];
                }
            }
            if ((order[i].flags & ESTRIP_SCUFFS) && at > first) {
                toggle[numToggles].strip = s;
                toggle[numToggles].first = first;
                toggle[numToggles].count = at - first;
                toggle[numToggles].kept  = order[i].hidden ? 1 : 0;
                numToggles++;
            }
        }
    }

    // The toggles' indices as baked, and then a hidden one's triangles each
    // three times its first vertex, which the PICA draws as nothing.
    // `kept` held whether it was hidden until here.
    if (editable) {
        int numKept = 0;
        int k;

        for (k = 0; k < numToggles; k++) {
            numKept += toggle[k].count;
        }
        out->edit = edit_alloc(solid->numStrips,
                               vertFirst[solid->numStrips], numToggles,
                               numKept);
        if (out->edit != NULL) {
            memcpy(out->edit->vertFirst, vertFirst,
                   (size_t)(solid->numStrips + 1) * sizeof *vertFirst);
            memcpy(out->edit->remap, remap,
                   (size_t)vertFirst[solid->numStrips] * sizeof *remap);
            numKept = 0;
            for (k = 0; k < numToggles; k++) {
                GeoToggle* g      = &out->edit->toggle[k];
                bool       hidden = toggle[k].kept != 0;
                int        j;

                *g      = toggle[k];
                g->kept = numKept;
                memcpy(out->edit->indices + numKept, idx + g->first,
                       (size_t)g->count * sizeof *idx);
                numKept += g->count;
                if (hidden) {
                    for (j = 1; j < g->count; j++) {
                        idx[g->first + j] = idx[g->first];
                    }
                }
            }
        }
        scratch_free(vertFirst);
        scratch_free(remap);
        scratch_free(toggle);
    }

    // The vertices, then the indices from the next 16 bytes, then the
    // batches' boxes, in one block.
    for (i = 0; i < out->numBatches; i++) {
        out->batch[i].cluster = numClusters;
        numClusters += geocull_count(out->batch[i].count);
    }
    vbytes   = ((size_t)set.n * sizeof(GeoRenderVertex) + 15u) & ~(size_t)15u;
    ibytes   = ((size_t)at * sizeof *idx + 3u) & ~(size_t)3u;
    out->vbo = set.n > 0 && (!editable || out->edit != NULL)
             ? (GeoRenderVertex*)block_alloc(
                   vbytes + ibytes + (size_t)numClusters * sizeof(GeoCluster))
             : NULL;
    if (out->vbo) {
        GeoCluster* clusters = (GeoCluster*)((uint8_t*)out->vbo + vbytes
                                             + ibytes);

        memcpy(out->vbo, set.vert, (size_t)set.n * sizeof *set.vert);
        out->ibo = (uint16_t*)((uint8_t*)out->vbo + vbytes);
        memcpy(out->ibo, idx, (size_t)at * sizeof *idx);
        out->numVerts   = set.n;
        out->numIndices = at;
        for (i = 0; i < out->numBatches; i++) {
            const GeoBatch* b = &out->batch[i];

            geocull_build(set.vert[0].pos,
                          (int)(sizeof(GeoRenderVertex) / sizeof(float)),
                          idx + b->first, b->count, clusters + b->cluster);
        }
        out->clusters = numClusters > 0 ? clusters : NULL;
    }

    scratch_free(order);
    scratch_free(strip);
    scratch_free(set.vert);
    scratch_free(set.slot);
    scratch_free(idx);
    if (!out->vbo && set.n > 0) {
        scratch_free(out->edit);
        memset(out, 0, sizeof *out);
        return false;
    }
    return true;
}

bool georender_bake(const GeoSolid* solid, GeoMesh* out)
{
    return bake(solid, out, false);
}

bool georender_bake_editable(const GeoSolid* solid, GeoMesh* out)
{
    return bake(solid, out, true);
}

// The walk writes the packet the bake decoded (estripdata.h), so its
// vertices are read back out of each strip's slice as the bake's decode
// found them, and only a slice whose header still says as many vertices
// as the entry is touched.
bool georender_refresh(const GeoSolid* solid, GeoMesh* mesh)
{
    GeoMeshEdit* e = mesh->edit;
    GeoCluster*  clusters;
    size_t       off = 0;
    int          s, k;

    if (e == NULL || mesh->vbo == NULL) {
        return false;
    }
    for (s = 0; s < e->numStrips && s < solid->numStrips; s++) {
        GeoStripEntry  entry;
        const uint8_t* d;
        size_t         slice;
        int32_t        nv = e->vertFirst[s + 1] - e->vertFirst[s];
        int32_t        v;

        if (geo_strip_entry(solid, s, &entry) != GEO_OK) {
            break;
        }
        slice = (size_t)entry.dataQWordSize * 16u;
        d     = solid->packet + off;
        off  += slice;
        if (nv <= 0 || solid->packet == NULL || off > solid->packetSize
            || slice < 8u || estripdata_num_verts(d) != nv
            || estripdata_element_rgba(d, nv - 1) + 2u > slice) {
            continue;
        }
        for (v = 0; v < nv; v++) {
            uint16_t at = e->remap[e->vertFirst[s] + v];
            uint16_t colour;

            if (at == NO_VERTEX || at >= mesh->numVerts) {
                continue;
            }
            estripdata_get_xyz(d, v, &mesh->vbo[at].pos[0],
                               &mesh->vbo[at].pos[1], &mesh->vbo[at].pos[2]);
            memcpy(&colour, d + estripdata_element_rgba(d, v), 2);
            put_colour(&mesh->vbo[at], colour);
        }
    }
    for (k = 0; k < e->numToggles; k++) {
        const GeoToggle* g    = &e->toggle[k];
        const uint16_t*  kept = e->indices + g->kept;
        uint16_t*        ibo  = mesh->ibo + g->first;
        int              j;

        if (geo_strip_flags(solid, g->strip, 0) & ESTRIP_HIDDEN) {
            for (j = 0; j < g->count; j++) {
                ibo[j] = kept[0];
            }
        } else {
            memcpy(ibo, kept, (size_t)g->count * sizeof *ibo);
        }
    }
    clusters = (GeoCluster*)mesh->clusters;
    if (clusters != NULL) {
        for (k = 0; k < mesh->numBatches; k++) {
            const GeoBatch* b = &mesh->batch[k];

            geocull_build(mesh->vbo[0].pos,
                          (int)(sizeof(GeoRenderVertex) / sizeof(float)),
                          mesh->ibo + b->first, b->count,
                          clusters + b->cluster);
        }
    }
    return true;
}

void georender_free(GeoMesh* mesh)
{
    if (mesh->vbo) {
        block_free(mesh->vbo);
    }
    if (mesh->edit) {
        block_free(mesh->edit);
    }
    memset(mesh, 0, sizeof *mesh);
}

