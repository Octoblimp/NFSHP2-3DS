// Drives 3DS Files/source/geometry.c over real disc data and prints a
// transcript. tools/geometry_check.py prints the same transcript from
// tools/geometry_convert.py, and the diff is the test.
//
// This checker is shaped differently from the others in tools/, and for a
// reason worth stating. Every earlier one drives scripted scenarios, because
// there was no oracle but a second implementation. Here there is one: the
// Python reader came first and was checked against the shipped data itself --
// every vertex of all 1,465 solids inside its own AABB, the ADC rule
// reproducing eStripEntry.NumPolys for all 22,280 strips, unit-length
// normals. So this drives the *disc*, not a script.
//
// A full per-vertex dump of the disc would be tens of millions of lines, so
// the transcript has two densities and both sides print both:
//
//   * a digest per strip and per solid -- FNV-1a over the decoded bytes,
//     which covers every vertex of every strip without printing them;
//   * the same three invariants the document used, recomputed here so a
//     disagreement shows up as a count rather than as a checksum nobody can
//     read;
//   * and, for solids named on the command line, every vertex and triangle
//     in full, so that when a digest does differ there is something to look
//     at.
//
// Floats are never recomputed -- XYZ and ST are read verbatim out of the
// file -- so unlike bmath's checker there is no float determinism problem
// here at all, and the digest can be taken over the raw bit patterns.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "geometry.h"

#define MAX_SOLIDS   1400
#define MAX_DETAIL   8

static GeoSolid  g_solids[MAX_SOLIDS];
static GeoStrip  g_strip;

// ----------------------------------------------------------------- the digest

// FNV-1a, 32-bit. Chosen because it is four lines in either language and
// needs no table, so the two implementations cannot drift.
#define FNV_OFFSET  2166136261u
#define FNV_PRIME   16777619u

static unsigned fnv_byte(unsigned h, unsigned char b)
{
    h ^= b;
    h *= FNV_PRIME;
    return h;
}

static unsigned fnv_u32(unsigned h, unsigned v)
{
    h = fnv_byte(h, (unsigned char)(v & 0xff));
    h = fnv_byte(h, (unsigned char)((v >> 8) & 0xff));
    h = fnv_byte(h, (unsigned char)((v >> 16) & 0xff));
    h = fnv_byte(h, (unsigned char)((v >> 24) & 0xff));
    return h;
}

static unsigned fnv_f32(unsigned h, float f)
{
    unsigned bits;

    memcpy(&bits, &f, sizeof bits);
    return fnv_u32(h, bits);
}

// --------------------------------------------------------------- conversions

// The colour is RGBA5551 in the file. Both sides print it widened to 0..255
// the way a renderer would want it, because that is the form the Python
// already produced and the widening is exact in both.
static void colour8(unsigned short packed, int out[4])
{
    unsigned char c[4];

    geo_unpack_colour(packed, c);
    out[0] = c[0] * 255 / 31;
    out[1] = c[1] * 255 / 31;
    out[2] = c[2] * 255 / 31;
    out[3] = c[3] ? 255 : 0;
}

// ------------------------------------------------------------------ the dump

static int g_detailCount;
static const char* g_detail[MAX_DETAIL];

static int wanted_detail(const char* name)
{
    int i;

    for (i = 0; i < g_detailCount; i++) {
        if (strcmp(g_detail[i], name) == 0) {
            return 1;
        }
    }
    return 0;
}

static void dump_strip_detail(const GeoStrip* s)
{
    int v;
    int t;

    for (v = 0; v < s->numVerts; v++) {
        const GeoVertex* p = &s->vert[v];
        int              c[4];

        colour8(p->colour, c);
        printf("      v%-2d %.6f %.6f %.6f  st %.6f %.6f  rgba %d %d %d %d",
               v, p->pos[0], p->pos[1], p->pos[2], p->st[0], p->st[1],
               c[0], c[1], c[2], c[3]);
        if (s->hasNormals) {
            printf("  n %d %d %d", p->normal[0], p->normal[1], p->normal[2]);
        }
        printf("\n");
    }
    for (t = 0; t < s->numTris; t++) {
        printf("      t%-2d %d %d %d\n", t,
               s->tri[t][0], s->tri[t][1], s->tri[t][2]);
    }
}

static unsigned strip_digest(const GeoStrip* s)
{
    unsigned h = FNV_OFFSET;
    int      v;
    int      t;

    h = fnv_u32(h, (unsigned)s->numVerts);
    h = fnv_u32(h, (unsigned)s->numTris);
    h = fnv_u32(h, (unsigned)s->hasNormals);
    h = fnv_u32(h, (unsigned)(s->lightMaterial & 0xff));

    for (v = 0; v < s->numVerts; v++) {
        const GeoVertex* p = &s->vert[v];
        int              c[4];
        int              i;

        for (i = 0; i < 3; i++) {
            h = fnv_f32(h, p->pos[i]);
        }
        for (i = 0; i < 2; i++) {
            h = fnv_f32(h, p->st[i]);
        }
        colour8(p->colour, c);
        for (i = 0; i < 4; i++) {
            h = fnv_byte(h, (unsigned char)c[i]);
        }
        if (s->hasNormals) {
            for (i = 0; i < 3; i++) {
                h = fnv_byte(h, (unsigned char)(unsigned)(p->normal[i] & 0xff));
            }
        }
    }
    for (t = 0; t < s->numTris; t++) {
        h = fnv_byte(h, s->tri[t][0]);
        h = fnv_byte(h, s->tri[t][1]);
        h = fnv_byte(h, s->tri[t][2]);
    }
    return h;
}

// ------------------------------------------------------------- the invariants

typedef struct {
    int strips;
    int decodedTris;
    int entryPolys;
    int vertsOutsideAABB;
    int badNormals;
    int zeroNormals;
    int skipped;
} Checks;

// Every decoded vertex should fall inside the solid's own AABB. The box is
// exact in the shipped data, which makes this the cheapest statement that a
// decode is right -- a transposition error puts vertices light years away.
static int outside(const GeoSolid* solid, const GeoVertex* v)
{
    int i;

    for (i = 0; i < 3; i++) {
        if (v->pos[i] < solid->aabbMin[i] || v->pos[i] > solid->aabbMax[i]) {
            return 1;
        }
    }
    return 0;
}

// Normals are unit vectors quantised onto a radius-127 sphere, so their
// integer length lands in 125..127 -- never above, because 127 is the radius,
// and never far below, because only rounding loses any. Measured over all 28
// cars: 192,822 of 192,822 non-zero normals inside that band, the shortest
// 125.355. A length outside it means the field was read at the wrong address
// or with the wrong sign.
//
// 53 of those 192,875 normals are exactly zero. Those are in the data, not a
// decode failure, so they are counted apart rather than called bad.
#define NORM_MIN2 (125 * 125)
#define NORM_MAX2 (127 * 127)

static int bad_normal(const GeoVertex* v)
{
    int len2 = v->normal[0] * v->normal[0]
             + v->normal[1] * v->normal[1]
             + v->normal[2] * v->normal[2];

    return len2 != 0 && (len2 < NORM_MIN2 || len2 > NORM_MAX2);
}

static int zero_normal(const GeoVertex* v)
{
    return !v->normal[0] && !v->normal[1] && !v->normal[2];
}

static void dump_solid(const GeoSolid* solid, int index, Checks* totals)
{
    GeoStripCursor cursor;
    Checks         c;
    unsigned       solidDigest = FNV_OFFSET;
    int            detail = wanted_detail(solid->name);
    int            rc;

    memset(&c, 0, sizeof c);

    printf("solid %d '%s' hash=%08x strips=%d verts=%d polys=%d tex=%d lmat=%d\n",
           index, solid->name, (unsigned)solid->nameHash, solid->numStrips,
           solid->numVerts, solid->numPolys, solid->numTextures,
           solid->numLightMaterials);
    printf("  aabb %.6f %.6f %.6f  %.6f %.6f %.6f\n",
           solid->aabbMin[0], solid->aabbMin[1], solid->aabbMin[2],
           solid->aabbMax[0], solid->aabbMax[1], solid->aabbMax[2]);

    geo_strip_begin(&cursor);
    for (;;) {
        GeoStripEntry entry;
        unsigned      d;
        int           v;
        int           at = cursor.index;

        rc = geo_strip_entry(solid, at, &entry);
        if (rc != GEO_OK) {
            break;
        }
        rc = geo_decode_next(solid, &cursor, &g_strip);
        if (rc == GEO_EEND) {
            break;
        }
        if (rc != GEO_OK) {
            // The Python drops a strip it cannot read rather than failing the
            // file. Say so on the same line count so the two stay in step.
            printf("  strip %d unreadable: %s\n", at, geo_error(rc));
            c.skipped++;
            continue;
        }

        d = strip_digest(&g_strip);
        solidDigest = fnv_u32(solidDigest, d);

        c.strips++;
        c.decodedTris += g_strip.numTris;
        c.entryPolys  += entry.numPolys;

        for (v = 0; v < g_strip.numVerts; v++) {
            if (outside(solid, &g_strip.vert[v])) {
                c.vertsOutsideAABB++;
            }
            if (g_strip.hasNormals) {
                if (bad_normal(&g_strip.vert[v])) {
                    c.badNormals++;
                }
                if (zero_normal(&g_strip.vert[v])) {
                    c.zeroNormals++;
                }
            }
        }

        printf("  strip %d e.verts=%d e.polys=%d e.lmat=%d e.tex=%d "
               "qwords=%d group=%d flags=%04x\n",
               at, entry.numVerts, entry.numPolys, entry.lightMaterial,
               entry.textureNumber, entry.dataQWordSize, entry.polyGroup,
               entry.flags);
        printf("    verts=%d tris=%d lmat=%d normals=%d adc %08x %08x %08x %08x"
               " digest %08x\n",
               g_strip.numVerts, g_strip.numTris, g_strip.lightMaterial,
               g_strip.hasNormals, (unsigned)g_strip.adc[0],
               (unsigned)g_strip.adc[1], (unsigned)g_strip.adc[2],
               (unsigned)g_strip.adc[3], d);
        if (detail) {
            dump_strip_detail(&g_strip);
        }
    }

    printf("  checks strips=%d tris=%d entrypolys=%d outside=%d badnormals=%d"
           " zeronormals=%d skipped=%d digest %08x\n",
           c.strips, c.decodedTris, c.entryPolys, c.vertsOutsideAABB,
           c.badNormals, c.zeroNormals, c.skipped, solidDigest);

    totals->strips           += c.strips;
    totals->decodedTris      += c.decodedTris;
    totals->entryPolys       += c.entryPolys;
    totals->vertsOutsideAABB += c.vertsOutsideAABB;
    totals->badNormals       += c.badNormals;
    totals->zeroNormals      += c.zeroNormals;
    totals->skipped          += c.skipped;
}

// --------------------------------------------------------------------- main

static unsigned char* slurp(const char* path, size_t* bytes)
{
    FILE*          fh = fopen(path, "rb");
    unsigned char* buf;
    long           n;

    if (!fh) {
        return NULL;
    }
    if (fseek(fh, 0, SEEK_END) != 0 || (n = ftell(fh)) < 0) {
        fclose(fh);
        return NULL;
    }
    rewind(fh);
    buf = (unsigned char*)malloc((size_t)n ? (size_t)n : 1);
    if (!buf || fread(buf, 1, (size_t)n, fh) != (size_t)n) {
        free(buf);
        fclose(fh);
        return NULL;
    }
    fclose(fh);
    *bytes = (size_t)n;
    return buf;
}

// The file is named by its last two path components, so the transcript does
// not change with where the tree is checked out.
static const char* short_name(const char* path)
{
    const char* a = NULL;
    const char* b = NULL;
    const char* p;

    for (p = path; *p; p++) {
        if (*p == '/' || *p == '\\') {
            a = b;
            b = p;
        }
    }
    return a ? a + 1 : (b ? b + 1 : path);
}

int main(int argc, char** argv)
{
    GeoSolidList   list;
    unsigned char* buf;
    size_t         bytes;
    Checks         totals;
    int            rc;
    int            i;

    if (argc < 2) {
        fprintf(stderr, "usage: geometry_test <file> [solid-to-detail ...]\n");
        return 2;
    }
    for (i = 2; i < argc && g_detailCount < MAX_DETAIL; i++) {
        g_detail[g_detailCount++] = argv[i];
    }

    buf = slurp(argv[1], &bytes);
    if (!buf) {
        fprintf(stderr, "cannot read %s\n", argv[1]);
        return 2;
    }

    memset(&totals, 0, sizeof totals);
    rc = geo_open(buf, bytes, &list, g_solids, MAX_SOLIDS);
    if (rc != GEO_OK) {
        printf("file %s\n", short_name(argv[1]));
        printf("open failed: %s\n", geo_error(rc));
        free(buf);
        return 0;
    }

    printf("file %s\n", short_name(argv[1]));
    printf("source %s\n", list.source);
    printf("solids %d of %d\n", list.numSolids, list.numSolidsInFile);

    for (i = 0; i < list.numSolids; i++) {
        dump_solid(&list.solid[i], i, &totals);
    }

    printf("totals solids=%d strips=%d tris=%d entrypolys=%d outside=%d"
           " badnormals=%d zeronormals=%d skipped=%d\n",
           list.numSolids, totals.strips, totals.decodedTris,
           totals.entryPolys, totals.vertsOutsideAABB, totals.badNormals,
           totals.zeroNormals, totals.skipped);

    free(buf);
    return 0;
}
