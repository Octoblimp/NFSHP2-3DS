// geobake_test -- tools/geobake_check.py's harness.
//
// Bakes every solid of each GEOMETRY.BIN it is given and checks the
// editable bake and georender_refresh (geobake.c) against bakes made
// afresh:
//
//   - with every scuff strip shown, the editable bake is the plain bake,
//     byte for byte, and a refresh before any change changes nothing;
//   - then three times: every strip vertex changed in its packet, as a
//     function of what it holds (so vertices the bake merged stay alike,
//     as CarDamage's keys keep them), each scuff strip shown or hidden at
//     random, and the mesh refreshed. It must draw what an editable bake
//     of the changed solid draws -- the same batches, and at each index
//     the same vertex, byte for byte -- with the same boxes; and it must
//     draw what the plain bake does, triangle for triangle, which has the
//     hidden scuff strips' triangles fewer.
//
// It prints each fault, and then the counts; "faults 0" is a pass.
//
//     geobake_test GEOMETRY.BIN...

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "estripdata.h"
#include "geobake.h"
#include "geometry.h"

#define MAX_SOLIDS 1400
#define ROUNDS     3
#define FLAGS_AT   14           // eStripEntry's Flags
#define ENTRY_SIZE 64

static GeoSolid g_solids[MAX_SOLIDS];
static long     g_faults;
static long     g_files, g_solidsSeen, g_strips, g_scuffs, g_hiddenOnDisc;
static long     g_verts, g_refreshes, g_compares, g_hiddenTris;

static const char* g_file;
static const char* g_solid;

static void fault(const char* what, long a, long b)
{
    if (g_faults < 60)
        printf("FAULT %s %s: %s (%ld, %ld)\n", g_file, g_solid, what, a, b);
    g_faults++;
}

static uint8_t* slurp(const char* path, size_t* n)
{
    FILE*    f = fopen(path, "rb");
    uint8_t* b;
    long     size;

    if (f == NULL)
        return NULL;
    fseek(f, 0, SEEK_END);
    size = ftell(f);
    fseek(f, 0, SEEK_SET);
    b = (uint8_t*)malloc((size_t)size);
    if (b == NULL || fread(b, 1, (size_t)size, f) != (size_t)size) {
        fclose(f);
        free(b);
        return NULL;
    }
    fclose(f);
    *n = (size_t)size;
    return b;
}

static uint32_t fnv(const void* p, size_t n, uint32_t h)
{
    const uint8_t* b = (const uint8_t*)p;
    size_t         i;

    for (i = 0; i < n; i++)
        h = (h ^ b[i]) * 16777619u;
    return h;
}

static uint32_t lcg(uint32_t* state)
{
    *state = *state * 1103515245u + 12345u;
    return *state >> 16;
}

// The buffer is the harness's own, so the solid's tables are written in
// place, as the walk writes the game's.
static uint8_t* entry_of(const GeoSolid* s, int i)
{
    return (uint8_t*)(uintptr_t)s->stripEntries + (size_t)i * ENTRY_SIZE;
}

static void set_flags(const GeoSolid* s, int i, uint16_t flags)
{
    uint8_t* e = entry_of(s, i);

    e[FLAGS_AT] = (uint8_t)flags;
    e[FLAGS_AT + 1] = (uint8_t)(flags >> 8);
}

// Every scuff strip shown or hidden: `how` 0 shows them all, otherwise
// the generator picks.
static void scuffs(const GeoSolid* s, uint32_t* state, int how)
{
    int i;

    for (i = 0; i < s->numStrips; i++) {
        uint16_t f = geo_strip_flags(s, i, 0);

        if (!(f & ESTRIP_SCUFFS))
            continue;
        if (how != 0 && (lcg(state) & 1))
            f = (uint16_t)(f | ESTRIP_HIDDEN);
        else
            f = (uint16_t)(f & ~ESTRIP_HIDDEN);
        set_flags(s, i, f);
    }
}

// Each strip vertex moved and recoloured by a hash of its position,
// colour and the round.
static void change(const GeoSolid* s, uint32_t round)
{
    uint8_t* packet = (uint8_t*)(uintptr_t)s->packet;
    size_t   off = 0;
    int      i, v;

    for (i = 0; i < s->numStrips; i++) {
        GeoStripEntry e;
        uint8_t*      d;
        int           nv;

        if (geo_strip_entry(s, i, &e) != GEO_OK)
            break;
        d = packet + off;
        off += (size_t)e.dataQWordSize * 16u;
        if (off > s->packetSize)
            break;
        nv = estripdata_num_verts(d);
        if (nv != e.numVerts) {
            fault("packet's vertex count not the entry's", nv, e.numVerts);
            continue;
        }
        for (v = 0; v < nv; v++) {
            float    x, y, z;
            uint16_t c;
            size_t   at = estripdata_element_rgba(d, v);
            uint32_t h;

            estripdata_get_xyz(d, v, &x, &y, &z);
            memcpy(&c, d + at, 2);
            h = fnv(&x, 4, 2166136261u ^ (round * 2654435761u));
            h = fnv(&y, 4, h);
            h = fnv(&z, 4, h);
            h = fnv(&c, 2, h);
            x += (float)((int32_t)(h & 0xffu) - 128) / 512.0f;
            y += (float)((int32_t)((h >> 8) & 0xffu) - 128) / 512.0f;
            z += (float)((int32_t)((h >> 16) & 0xffu) - 128) / 512.0f;
            c = (uint16_t)(c - ((h >> 24) & 7u) * 0x421u);
            if (h & 0x80000000u)
                c ^= 0x8000u;
            estripdata_set_xyz(d, v, x, y, z);
            memcpy(d + at, &c, 2);
            g_verts++;
        }
    }
}

static int clusters_of(const GeoMesh* m)
{
    int i, n = 0;

    for (i = 0; i < m->numBatches; i++)
        n += geocull_count(m->batch[i].count);
    return n;
}

// `a` draws what `b` does: the same batches and, at each index, the same
// vertex, and the same boxes. `exact`: the same buffers, byte for byte.
static void compare(const char* what, const GeoMesh* a, const GeoMesh* b,
                    int exact)
{
    char note[96];
    int  i, k;

    g_compares++;
    if (a->numBatches != b->numBatches || a->numIndices != b->numIndices
        || a->numTris != b->numTris) {
        snprintf(note, sizeof note, "%s: batches or indices differ", what);
        fault(note, a->numIndices, b->numIndices);
        return;
    }
    for (i = 0; i < a->numBatches; i++) {
        const GeoBatch* x = &a->batch[i];
        const GeoBatch* y = &b->batch[i];

        if (x->first != y->first || x->count != y->count
            || x->texture != y->texture || x->strip != y->strip
            || x->flags != y->flags || x->lightMaterial != y->lightMaterial
            || x->cluster != y->cluster) {
            snprintf(note, sizeof note, "%s: batch differs", what);
            fault(note, i, x->flags);
            return;
        }
    }
    for (k = 0; k < a->numIndices; k++) {
        if (a->ibo[k] >= a->numVerts || b->ibo[k] >= b->numVerts) {
            snprintf(note, sizeof note, "%s: index past the vertices", what);
            fault(note, k, a->ibo[k]);
            return;
        }
        if (memcmp(&a->vbo[a->ibo[k]], &b->vbo[b->ibo[k]],
                   sizeof(GeoRenderVertex)) != 0) {
            snprintf(note, sizeof note, "%s: vertex differs", what);
            fault(note, k, a->ibo[k]);
            return;
        }
    }
    if ((a->clusters == NULL) != (b->clusters == NULL)
        || (a->clusters != NULL
            && memcmp(a->clusters, b->clusters,
                      (size_t)clusters_of(a) * sizeof(GeoCluster)) != 0)) {
        snprintf(note, sizeof note, "%s: boxes differ", what);
        fault(note, clusters_of(a), clusters_of(b));
        return;
    }
    if (exact && (a->numVerts != b->numVerts
                  || memcmp(a->vbo, b->vbo, (size_t)a->numVerts
                                                * sizeof(GeoRenderVertex))
                  || memcmp(a->ibo, b->ibo, (size_t)a->numIndices
                                                * sizeof(uint16_t)))) {
        snprintf(note, sizeof note, "%s: buffers differ", what);
        fault(note, a->numVerts, b->numVerts);
    }
}

// The batch a mesh's index `k` is in, or -1.
static int batch_of(const GeoMesh* m, int k)
{
    int i;

    for (i = 0; i < m->numBatches; i++)
        if (k >= m->batch[i].first && k < m->batch[i].first + m->batch[i].count)
            return i;
    return -1;
}

// The next triangle of `m` from index `*k` on that draws: two of its
// corners the same index draw nothing. Its first index, or -1 at the end.
static int next_drawn(const GeoMesh* m, int* k)
{
    while (*k + 3 <= m->numIndices) {
        const uint16_t* t = m->ibo + *k;

        *k += 3;
        if (t[0] != t[1] && t[1] != t[2] && t[0] != t[2])
            return *k - 3;
    }
    return -1;
}

// `a` draws what `b` does, triangle for triangle: the triangles that draw,
// in order, each with the same three vertices byte for byte, in a batch
// of the same texture, flags and material.
static void compare_drawn(const char* what, const GeoMesh* a,
                          const GeoMesh* b)
{
    char note[96];
    int  ka = 0, kb = 0, n = 0;

    g_compares++;
    for (;;) {
        int ta = next_drawn(a, &ka);
        int tb = next_drawn(b, &kb);
        int ba, bb, c;

        if (ta < 0 || tb < 0) {
            if (ta >= 0 || tb >= 0) {
                snprintf(note, sizeof note, "%s: one draws more", what);
                fault(note, n, ta < 0 ? 1 : 0);
            }
            return;
        }
        ba = batch_of(a, ta);
        bb = batch_of(b, tb);
        if (ba < 0 || bb < 0
            || a->batch[ba].texture != b->batch[bb].texture
            || a->batch[ba].flags != b->batch[bb].flags
            || a->batch[ba].lightMaterial != b->batch[bb].lightMaterial) {
            snprintf(note, sizeof note, "%s: drawn in another batch", what);
            fault(note, n, ba);
            return;
        }
        for (c = 0; c < 3; c++) {
            if (memcmp(&a->vbo[a->ibo[ta + c]], &b->vbo[b->ibo[tb + c]],
                       sizeof(GeoRenderVertex)) != 0) {
                snprintf(note, sizeof note, "%s: drawn vertex differs", what);
                fault(note, n, c);
                return;
            }
        }
        n++;
    }
}

// The triangles of the scuff strips hidden now.
static int hidden_tris(const GeoSolid* s)
{
    int i, n = 0;

    for (i = 0; i < s->numStrips; i++) {
        GeoStripEntry e;

        if (geo_strip_entry(s, i, &e) == GEO_OK
            && (e.flags & ESTRIP_SCUFFS) && (e.flags & ESTRIP_HIDDEN))
            n += e.numPolys;
    }
    return n;
}

static void check_solid(const GeoSolid* s)
{
    GeoMesh  plain, edit, fresh;
    GeoMesh  before;
    uint32_t state = s->nameHash;
    uint32_t round;
    int      i;

    g_solidsSeen++;
    g_strips += s->numStrips;
    for (i = 0; i < s->numStrips; i++) {
        uint16_t f = geo_strip_flags(s, i, 0);

        g_scuffs += (f & ESTRIP_SCUFFS) != 0;
        g_hiddenOnDisc += (f & ESTRIP_HIDDEN) != 0;
    }

    // Every scuff strip shown: the editable bake is the plain one.
    scuffs(s, &state, 0);
    if (!georender_bake(s, &plain) || !georender_bake_editable(s, &edit)) {
        fault("a bake failed", 0, 0);
        return;
    }
    if (plain.edit != NULL)
        fault("the plain bake is editable", 0, 0);
    if (edit.vbo != NULL && edit.edit == NULL)
        fault("the editable bake is not", 0, 0);
    if (plain.skippedStrips != 0 || edit.skippedStrips != 0)
        fault("strips skipped", plain.skippedStrips, edit.skippedStrips);
    if (georender_refresh(s, &plain))
        fault("a plain mesh refreshed", 0, 0);
    compare("editable, all shown", &edit, &plain, 1);
    georender_free(&plain);
    if (edit.vbo == NULL) {
        georender_free(&edit);
        return;
    }

    // A refresh with nothing changed changes nothing.
    before = edit;
    before.vbo = (GeoRenderVertex*)malloc(
        (size_t)edit.numVerts * sizeof(GeoRenderVertex)
        + (size_t)edit.numIndices * sizeof(uint16_t)
        + (size_t)clusters_of(&edit) * sizeof(GeoCluster));
    memcpy(before.vbo, edit.vbo,
           (size_t)edit.numVerts * sizeof(GeoRenderVertex));
    before.ibo = (uint16_t*)(before.vbo + edit.numVerts);
    memcpy(before.ibo, edit.ibo, (size_t)edit.numIndices * sizeof(uint16_t));
    before.clusters = edit.clusters == NULL ? NULL
        : (const GeoCluster*)(void*)(before.ibo + edit.numIndices);
    if (edit.clusters != NULL)
        memcpy((void*)(uintptr_t)before.clusters, edit.clusters,
               (size_t)clusters_of(&edit) * sizeof(GeoCluster));
    if (!georender_refresh(s, &edit))
        fault("the editable mesh did not refresh", 0, 0);
    g_refreshes++;
    compare("refreshed unchanged", &edit, &before, 1);
    free(before.vbo);

    for (round = 1; round <= ROUNDS; round++) {
        change(s, round);
        scuffs(s, &state, 1);
        if (!georender_refresh(s, &edit))
            fault("the editable mesh did not refresh", (long)round, 0);
        g_refreshes++;
        if (!georender_bake_editable(s, &fresh)) {
            fault("a bake failed", (long)round, 0);
            continue;
        }
        compare("refreshed against baked", &edit, &fresh, 0);
        georender_free(&fresh);
        if (!georender_bake(s, &plain)) {
            fault("a bake failed", (long)round, 1);
            continue;
        }
        g_hiddenTris += hidden_tris(s);
        if (plain.numTris != edit.numTris - hidden_tris(s))
            fault("the plain bake's triangles not the shown ones",
                  plain.numTris, edit.numTris - hidden_tris(s));
        compare_drawn("refreshed against plain", &edit, &plain);
        georender_free(&plain);
    }
    georender_free(&edit);
    if (edit.vbo != NULL || edit.edit != NULL)
        fault("georender_free left the mesh", 0, 0);
}

int main(int argc, char** argv)
{
    int a, i;

    if (argc < 2) {
        fprintf(stderr, "usage: geobake_test GEOMETRY.BIN...\n");
        return 2;
    }
    for (a = 1; a < argc; a++) {
        GeoSolidList list;
        size_t       bytes;
        uint8_t*     buf = slurp(argv[a], &bytes);
        int          rc;

        g_file = argv[a];
        g_solid = "-";
        if (buf == NULL) {
            fault("cannot read", 0, 0);
            continue;
        }
        rc = geo_open(buf, bytes, &list, g_solids, MAX_SOLIDS);
        if (rc != GEO_OK || list.numSolids != list.numSolidsInFile) {
            fault("geo_open", rc, list.numSolidsInFile);
            free(buf);
            continue;
        }
        g_files++;
        for (i = 0; i < list.numSolids; i++) {
            g_solid = list.solid[i].name;
            check_solid(&list.solid[i]);
        }
        free(buf);
    }
    printf("files %ld solids %ld strips %ld scuffs %ld hidden-on-disc %ld\n",
           g_files, g_solidsSeen, g_strips, g_scuffs, g_hiddenOnDisc);
    printf("vertices-changed %ld refreshes %ld compares %ld "
           "hidden-tris %ld\n", g_verts, g_refreshes, g_compares,
           g_hiddenTris);
    printf("faults %ld\n", g_faults);
    return 0;
}
