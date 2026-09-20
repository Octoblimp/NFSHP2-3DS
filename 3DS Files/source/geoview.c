#include "geoview.h"

#include <dirent.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <3ds.h>

#include "gamedata.h"

#define CAR_DIR        "CARS"
#define CAR_GEOMETRY   "GEOMETRY.BIN"
#define CAR_PACK       "CARS/TEXTURES.BIN"
#define GLOBAL_PACK    "GLOBAL/GLOBALB.BUN"

#define PITCH_LIMIT    1.45f        // just under 90 degrees
#define SPIN_RATE      0.55f        // radians a second
#define PAD_DEAD       24           // circle pad noise floor

// ------------------------------------------------------------------ the list

static int car_cmp(const void* a, const void* b)
{
    return strcmp((const char*)a, (const char*)b);
}

static void scan_cars(GeoView* v)
{
    char           dir[GAMEDATA_MAX_PATH];
    DIR*           d;
    struct dirent* e;

    if (!gamedata_path(CAR_DIR, dir, sizeof dir)) {
        return;
    }
    d = opendir(dir);
    if (!d) {
        return;
    }
    while ((e = readdir(d)) != NULL && v->numCars < GEOVIEW_MAX_CARS) {
        char rel[GAMEDATA_MAX_PATH];

        if (e->d_name[0] == '.') {
            continue;
        }
        // Whether a directory entry is a directory is not worth asking the
        // filesystem: what makes it a car is that it holds a GEOMETRY.BIN,
        // and CARS\ also holds TEXTURES.BIN, which is a file and is not one.
        snprintf(rel, sizeof rel, "%s/%.*s/%s", CAR_DIR,
                 GEOVIEW_NAME_LEN - 1, e->d_name, CAR_GEOMETRY);
        if (!gamedata_exists(rel)) {
            continue;
        }
        snprintf(v->car[v->numCars], GEOVIEW_NAME_LEN, "%.*s",
                 GEOVIEW_NAME_LEN - 1, e->d_name);
        v->numCars++;
    }
    closedir(d);

    // readdir's order is the filesystem's, and on a real SD card that is
    // neither alphabetical nor stable between machines. Sorting means "car 3"
    // is the same car in a screenshot taken anywhere.
    qsort(v->car, (size_t)v->numCars, GEOVIEW_NAME_LEN, car_cmp);
}

bool geoview_init(GeoView* v)
{
    char path[GAMEDATA_MAX_PATH];

    memset(v, 0, sizeof *v);
    v->curSolid = 0;
    v->spin     = true;
    v->textured = true;

    if (gamedata_path(CAR_PACK, path, sizeof path)) {
        v->hasCarPack = texsrc_open(&v->carPack, path);
    }
    if (gamedata_path(GLOBAL_PACK, path, sizeof path)) {
        v->hasGlobalPack = texsrc_open(&v->globalPack, path);
    }

    scan_cars(v);
    if (v->numCars == 0) {
        snprintf(v->note, sizeof v->note, "no cars under %s", CAR_DIR);
        return false;
    }
    return true;
}

// ------------------------------------------------------------- the textures
//
// A car's solids share textures heavily -- every LOD of the body indexes the
// same skin -- so the upload is cached per hash for the whole model and the
// per-solid table is pointers into that cache.

static GeoViewTex* find_texture(GeoView* v, uint32_t hash)
{
    int i;

    for (i = 0; i < v->numTextures; i++) {
        if (v->texture[i].hash == hash) {
            return &v->texture[i];
        }
    }
    return NULL;
}

static GeoViewTex* load_texture(GeoView* v, uint32_t hash)
{
    GeoViewTex* slot = find_texture(v, hash);
    TexSrcEntry e;
    TexSource*  src = NULL;

    if (slot) {
        return slot;
    }
    if (v->numTextures >= GEOVIEW_MAX_TEXTURES) {
        return NULL;
    }
    slot = &v->texture[v->numTextures++];
    memset(slot, 0, sizeof *slot);
    slot->hash       = hash;
    slot->uvScale[0] = 1.0f;
    slot->uvScale[1] = 1.0f;

    // The car's own skin first, then the shared parts -- TIRE, TIREBACK,
    // CARBOTTOM, BRAKESFRONT, SKRATCHES are all in GLOBALB.BUN, and no hash
    // is in both packs.
    if (v->hasCarPack && texsrc_find(&v->carPack, hash, &e)) {
        src = &v->carPack;
    } else if (v->hasGlobalPack && texsrc_find(&v->globalPack, hash, &e)) {
        src = &v->globalPack;
    }
    if (!src) {
        v->missingTextures++;
        return slot;
    }
    if (!texsrc_upload(src, &e, 0, &slot->tex)) {
        v->missingTextures++;
        return slot;
    }
    slot->valid = true;

    // texpack_upload() pads to a power of two with the image in the
    // top-left, so ST has to be scaled by the image's share of the
    // allocation: a 512x320 skin in a 512x512 texture needs 0.625 on T.
    slot->uvScale[0] = (float)e.info.width  / (float)slot->tex.width;
    slot->uvScale[1] = (float)e.info.height / (float)slot->tex.height;
    return slot;
}

static void resolve_textures(GeoView* v, int index)
{
    const GeoSolid* s = &v->solid[index];
    int             n = s->numTextures;
    int             i;

    if (n > GEOVIEW_MAX_SLOTS) {
        n = GEOVIEW_MAX_SLOTS;
    }
    for (i = 0; i < n; i++) {
        // eTextureTable is {NameHash, pTextureInfo}; the pointer half is
        // fixed up at load time and means nothing in a file.
        uint32_t    hash = bchunk_u32(s->textureTable + (size_t)i * 8);
        GeoViewTex* t    = load_texture(v, hash);

        if (t && t->valid) {
            v->slot[index][i].tex        = &t->tex;
            v->slot[index][i].uvScale[0] = t->uvScale[0];
            v->slot[index][i].uvScale[1] = t->uvScale[1];
        } else {
            v->slot[index][i].tex        = NULL;
            v->slot[index][i].uvScale[0] = 1.0f;
            v->slot[index][i].uvScale[1] = 1.0f;
        }
    }
}

// ------------------------------------------------------------------ loading

static uint8_t* read_file(const char* path, size_t* outLen)
{
    FILE*    f = fopen(path, "rb");
    long     len;
    uint8_t* buf;

    if (!f) {
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (len <= 0) {
        fclose(f);
        return NULL;
    }
    buf = (uint8_t*)malloc((size_t)len);
    if (!buf || fread(buf, 1, (size_t)len, f) != (size_t)len) {
        free(buf);
        fclose(f);
        return NULL;
    }
    fclose(f);
    *outLen = (size_t)len;
    return buf;
}

static void unload(GeoView* v)
{
    int i;

    for (i = 0; i < v->numSolids; i++) {
        georender_free(&v->mesh[i]);
    }
    for (i = 0; i < v->numTextures; i++) {
        if (v->texture[i].valid) {
            C3D_TexDelete(&v->texture[i].tex);
        }
    }
    free(v->data);
    v->data            = NULL;
    v->len             = 0;
    v->numSolids       = 0;
    v->numTextures     = 0;
    v->loadedTris      = 0;
    v->missingTextures = 0;
    v->skippedStrips   = 0;
    memset(&v->list, 0, sizeof v->list);
    memset(v->slot, 0, sizeof v->slot);
}

// The body ships as four LODs and they z-fight if drawn together, so the
// viewer opens on the one with the most triangles -- which is _A on every
// car, and is found by counting rather than by matching a name suffix.
static int biggest_solid(const GeoView* v)
{
    int best = 0, bestTris = -1, i;

    for (i = 0; i < v->numSolids; i++) {
        if (v->mesh[i].numTris > bestTris) {
            bestTris = v->mesh[i].numTris;
            best     = i;
        }
    }
    return best;
}

static void frame_camera(GeoView* v)
{
    const GeoMesh* m;
    float          span = 0.0f;
    int            i;
    float          lo[3], hi[3];

    if (v->numSolids == 0) {
        return;
    }
    if (v->drawAll) {
        lo[0] = lo[1] = lo[2] =  1e30f;
        hi[0] = hi[1] = hi[2] = -1e30f;
        for (i = 0; i < v->numSolids; i++) {
            int k;
            for (k = 0; k < 3; k++) {
                if (v->mesh[i].aabbMin[k] < lo[k]) lo[k] = v->mesh[i].aabbMin[k];
                if (v->mesh[i].aabbMax[k] > hi[k]) hi[k] = v->mesh[i].aabbMax[k];
            }
        }
    } else {
        m = &v->mesh[v->curSolid];
        for (i = 0; i < 3; i++) {
            lo[i] = m->aabbMin[i];
            hi[i] = m->aabbMax[i];
        }
    }
    for (i = 0; i < 3; i++) {
        v->centre[i] = (lo[i] + hi[i]) * 0.5f;
        if (hi[i] - lo[i] > span) {
            span = hi[i] - lo[i];
        }
    }
    v->radius = span * 0.5f;
    if (v->radius < 0.01f) {
        v->radius = 0.01f;
    }
    v->dist = v->radius * 2.8f;
}

bool geoview_load(GeoView* v, int index)
{
    char     path[GAMEDATA_MAX_PATH];
    char     rel[GAMEDATA_MAX_PATH];
    uint64_t t0 = osGetTime();
    int      rc, i;

    unload(v);
    if (index < 0 || index >= v->numCars) {
        return false;
    }
    v->curCar = index;

    snprintf(rel, sizeof rel, "%s/%s/%s", CAR_DIR, v->car[index],
             CAR_GEOMETRY);
    if (!gamedata_path(rel, path, sizeof path)) {
        snprintf(v->note, sizeof v->note, "path too long");
        return false;
    }
    v->data = read_file(path, &v->len);
    if (!v->data) {
        snprintf(v->note, sizeof v->note, "cannot read %.40s", rel);
        return false;
    }

    rc = geo_open(v->data, v->len, &v->list, v->solid, GEOVIEW_MAX_SOLIDS);
    if (rc != GEO_OK) {
        snprintf(v->note, sizeof v->note, "geo_open: %s", geo_error(rc));
        free(v->data);
        v->data = NULL;
        return false;
    }
    v->numSolids = v->list.numSolids;

    for (i = 0; i < v->numSolids; i++) {
        if (!georender_bake(&v->solid[i], &v->mesh[i])) {
            snprintf(v->note, sizeof v->note, "bake failed on solid %d", i);
            break;
        }
        v->loadedTris    += v->mesh[i].numTris;
        v->skippedStrips += v->mesh[i].skippedStrips;
        resolve_textures(v, i);
    }

    v->curSolid = biggest_solid(v);
    v->drawAll  = false;
    v->yaw      = 2.3f;
    v->pitch    = 0.35f;
    frame_camera(v);

    v->loadMs = (int)(osGetTime() - t0);
    snprintf(v->note, sizeof v->note, "%s: %d solids, %d tris, %d ms",
             v->car[index], v->numSolids, v->loadedTris, v->loadMs);
    return true;
}

void geoview_free(GeoView* v)
{
    unload(v);
    if (v->hasCarPack) {
        texsrc_close(&v->carPack);
    }
    if (v->hasGlobalPack) {
        texsrc_close(&v->globalPack);
    }
    memset(v, 0, sizeof *v);
}

// -------------------------------------------------------------------- input

void geoview_input(GeoView* v, uint32_t kDown, int cpx, int cpy, float dt)
{
    bool reframe = false;

    if (v->numCars == 0) {
        return;
    }

    if (kDown & KEY_R) {
        geoview_load(v, (v->curCar + 1) % v->numCars);
        return;
    }
    if (kDown & KEY_L) {
        geoview_load(v, (v->curCar + v->numCars - 1) % v->numCars);
        return;
    }
    if (v->numSolids > 0) {
        if (kDown & KEY_DRIGHT) {
            v->curSolid = (v->curSolid + 1) % v->numSolids;
            reframe = true;
        }
        if (kDown & KEY_DLEFT) {
            v->curSolid = (v->curSolid + v->numSolids - 1) % v->numSolids;
            reframe = true;
        }
    }
    if (kDown & KEY_A) {
        v->drawAll = !v->drawAll;
        reframe = true;
    }
    if (kDown & KEY_Y) {
        v->spin = !v->spin;
    }
    if (kDown & KEY_X) {
        v->textured = !v->textured;
    }
    if (kDown & KEY_B) {
        v->yaw   = 2.3f;
        v->pitch = 0.35f;
        reframe  = true;
    }
    if (kDown & KEY_DUP) {
        v->dist *= 0.8f;
    }
    if (kDown & KEY_DDOWN) {
        v->dist *= 1.25f;
    }
    if (reframe) {
        frame_camera(v);
    }

    // The circle pad drives the orbit directly and suspends the idle spin
    // while it is off centre, rather than toggling it -- so a glance at the
    // car does not leave it stopped.
    if (cpx > PAD_DEAD || cpx < -PAD_DEAD) {
        v->yaw -= (float)cpx / 156.0f * 2.2f * dt;
    } else if (v->spin) {
        v->yaw += SPIN_RATE * dt;
    }
    if (cpy > PAD_DEAD || cpy < -PAD_DEAD) {
        v->pitch += (float)cpy / 156.0f * 1.6f * dt;
        if (v->pitch >  PITCH_LIMIT) v->pitch =  PITCH_LIMIT;
        if (v->pitch < -PITCH_LIMIT) v->pitch = -PITCH_LIMIT;
    }
}

// --------------------------------------------------------------------- draw

void geoview_draw(GeoView* v)
{
    C3D_Mtx    proj, view;
    C3D_FVec   eye, at, up;
    float      cp = cosf(v->pitch);
    int        i;

    if (v->numSolids == 0) {
        return;
    }

    // Z is up in eSolid space -- a car's AABB is 4.46 long on X, 1.95 wide
    // on Y and 1.45 tall on Z -- so the orbit is around Z and the up vector
    // is +Z, not the +Y a citro3d example would use.
    eye = FVec3_New(v->centre[0] + v->dist * cp * cosf(v->yaw),
                    v->centre[1] + v->dist * cp * sinf(v->yaw),
                    v->centre[2] + v->dist * sinf(v->pitch));
    at  = FVec3_New(v->centre[0], v->centre[1], v->centre[2]);
    up  = FVec3_New(0.0f, 0.0f, 1.0f);

    Mtx_PerspTilt(&proj, C3D_AngleFromDegrees(45.0f), 400.0f / 240.0f,
                  v->radius * 0.05f, v->radius * 40.0f, false);
    Mtx_LookAt(&view, eye, at, up, false);

    georender_set_camera(&proj, &view);
    // Over the viewer's left shoulder, in view space, so the car relights
    // itself as it turns without the caller touching anything.
    georender_set_light(-0.35f, 0.45f, 1.0f, 1.0f, 0.98f, 0.94f, 0.38f);

    if (v->drawAll) {
        for (i = 0; i < v->numSolids; i++) {
            georender_draw(&v->mesh[i],
                           v->textured ? v->slot[i] : NULL,
                           v->textured ? GEOVIEW_MAX_SLOTS : 0);
        }
    } else {
        i = v->curSolid;
        georender_draw(&v->mesh[i],
                       v->textured ? v->slot[i] : NULL,
                       v->textured ? GEOVIEW_MAX_SLOTS : 0);
    }
}

const char* geoview_solid_name(const GeoView* v)
{
    if (v->numSolids == 0) {
        return "-";
    }
    if (v->drawAll) {
        return "(all)";
    }
    return v->solid[v->curSolid].name;
}
