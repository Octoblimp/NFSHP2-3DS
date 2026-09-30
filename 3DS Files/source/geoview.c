#include "geoview.h"

#include <dirent.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <3ds.h>

#include "emath.h"
#include "gamedata.h"

#define CAR_DIR        "CARS"
#define CAR_GEOMETRY   "GEOMETRY.BIN"
#define CAR_PACK       "CARS/TEXTURES.BIN"
#define GLOBAL_PACK    "GLOBAL/GLOBALB.BUN"

#define PAD_DEAD       24           // circle pad noise floor

// The mover's rotation speeds are BAMs per FRAME, not per second -- that is
// the disc's unit and the port keeps it -- so these are frame quantities.
// ORBIT_JOY_SPEED (500) is what the PS2's stick sent at full deflection;
// SPIN_SPEED is the viewer's own idle drift, about 40 degrees a second at
// 60fps, slow enough to look at a car by.
#define SPIN_SPEED     120

// The camera's own axes are the engine's: +z forward and +y DOWN, because
// the boom matrix ends with eRotateX(16384) then eRotateY(0xc000) and that
// is where those two land world +x and world +z. citro3d wants +y up and
// -z forward, so the view matrix is the transpose with rows 1 and 2 negated.
#define VIEW_FLIP_Y    (-1.0f)
#define VIEW_FLIP_Z    (-1.0f)

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

    // Park the stand-in car on the AABB centre and give the mover a boom
    // range to work in. MinRadius/MaxRadius are the mover's own clamp, so
    // the zoom stops where the viewer says rather than where the disc's
    // 1.0 .. 1000.0 defaults would. The mover reads the car's
    // GeometryPosition and BodyMatrix and nothing else.
    v->standIn.State.GeometryPosition.x = v->centre[0];
    v->standIn.State.GeometryPosition.y = v->centre[1];
    v->standIn.State.GeometryPosition.z = v->centre[2];
    v->standIn.State.GeometryPosition.pad = 0.0f;
    v->standIn.State.Position = v->standIn.State.GeometryPosition;
    eIdentity(&v->standIn.State.BodyMatrix);

    orbit_set_min_radius(&v->orbit, v->radius * 0.6f);
    orbit_set_max_radius(&v->orbit, v->radius * 40.0f);
    orbit_set_desired_radius(&v->orbit, v->dist);
    orbit_set_radius(&v->orbit, v->dist);
}

// The mover holds pointers into the GeoView, so it is rebuilt whenever the
// struct is cleared or a new car is framed rather than being set up once.
//
// Retail's constructor ends with AddJoyHandlers, nine event nodes out of the
// 96 in EventNodeSlotPool, which does not overflow. So the old mover is
// destroyed before the new one is built, and by geoview_free: about ten car
// changes would otherwise run the pool dry. A zeroed GeoView has no vtable,
// which is how a mover that was never built is told apart.
static void destroy_camera(GeoView* v)
{
    if (v->orbit.base.vtbl != NULL) {
        orbit_destroy(&v->orbit);
        v->orbit.base.vtbl = NULL;
    }
}

// The mover goes on view 0's list and takes its camera from it. The viewer
// is that view's only user, and the struct the last mover lived in may have
// been cleared since, so the list is started over rather than unlinked from.
static void reset_camera(GeoView* v)
{
    eView* view = eGetView(EVIEW_ID_FRONTEND);

    destroy_camera(v);
    camera_init(&v->cam);
    view->CameraMoverList.next = &view->CameraMoverList;
    view->CameraMoverList.prev = &view->CameraMoverList;
    view->pCamera = &v->cam;
    orbit_init(&v->orbit, EVIEW_ID_FRONTEND, &v->standIn, 0);
    // The near plane the mover sets is 0.5 and its far plane 10000, which are
    // the disc's and are wrong for a 4.5-metre car seen from 6 metres only
    // in that they waste depth range. Left alone: they are what the camera
    // ships with, and the depth buffer has 24 bits to spend.
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
    reset_camera(v);
    frame_camera(v);

    v->loadMs = (int)(osGetTime() - t0);
    snprintf(v->note, sizeof v->note, "%s: %d solids, %d tris, %d ms",
             v->car[index], v->numSolids, v->loadedTris, v->loadMs);
    return true;
}

void geoview_free(GeoView* v)
{
    destroy_camera(v);
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

void geoview_input(GeoView* v, uint32_t kDown, uint32_t kHeld, int cpx,
                   int cpy, float dt)
{
    bool reframe = false;

    (void)dt;
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
        // Back to the angles the mover's own constructor picks, which is
        // where the car select screen opens.
        orbit_set_angles(&v->orbit, 26000, 0xf230);
        reframe = true;
    }
    if (reframe) {
        frame_camera(v);
    }

    // Zoom is the disc's: hold the button and RadiusMultiplier compounds
    // 1% a frame into DesiredRadius. Releasing it must put the multiplier
    // back to exactly 1.0, because Update tests for that and skips the
    // multiply -- a multiplier of 0.999 left behind would creep for ever.
    if (kHeld & KEY_DUP) {
        orbit_set_radius_multiplier(&v->orbit, ORBIT_ZOOM_IN);
    } else if (kHeld & KEY_DDOWN) {
        orbit_set_radius_multiplier(&v->orbit, ORBIT_ZOOM_OUT);
    } else {
        orbit_set_radius_multiplier(&v->orbit, 1.0f);
    }

    // The circle pad asks for a rotation speed rather than setting an angle,
    // and the mover ramps to it at MaxRotationAccel -- 24 BAMs per frame per
    // frame -- so the orbit has the weight the shipped one has. The pad
    // suspends the idle spin while it is off centre rather than toggling it.
    if (cpx > PAD_DEAD || cpx < -PAD_DEAD) {
        orbit_set_desired_h_rotation_speed(
            &v->orbit, -(int)((float)cpx / 156.0f * ORBIT_JOY_SPEED));
    } else {
        orbit_set_desired_h_rotation_speed(&v->orbit,
                                           v->spin ? SPIN_SPEED : 0);
    }
    if (cpy > PAD_DEAD || cpy < -PAD_DEAD) {
        // Both signs are the disc's, from the jump table at 0x2950e0:
        // ROTATE_RIGHT and ROTATE_UP ask for a NEGATIVE speed and their
        // opposites for a positive one. Pad up therefore walks AngleV up
        // toward MaxAngleV, which lowers the boom -- elevation is measured
        // the other way round -- and that is what the disc does.
        orbit_set_desired_v_rotation_speed(
            &v->orbit, -(int)((float)cpy / 156.0f * ORBIT_JOY_SPEED));
    } else {
        orbit_set_desired_v_rotation_speed(&v->orbit, 0);
    }

    // One frame of the real mover. Its IsGameFlowPaused test finds no race
    // coordinator here, so it always runs.
    orbit_update(&v->orbit, dt);

    // The demo's mover clamped AngleV to MinAngleV .. MaxAngleV after the
    // step; retail's dropped the clamp and leaves the range to whoever sets
    // the speeds. So the viewer clamps, after the fact, and stops the
    // vertical speed so the ramp starts again from rest: the frame that hits
    // the stop overshoots it by one step, and each held frame after that by
    // MaxRotationAccel, 24 BAMs.
    if (v->orbit.AngleV > v->orbit.MaxAngleV) {
        v->orbit.AngleV = v->orbit.MaxAngleV;
        v->orbit.VRotationSpeed = 0;
    } else if (v->orbit.AngleV < v->orbit.MinAngleV) {
        v->orbit.AngleV = v->orbit.MinAngleV;
        v->orbit.VRotationSpeed = 0;
    }
}

// --------------------------------------------------------------------- draw

void geoview_draw(GeoView* v)
{
    C3D_Mtx          proj, view;
    const bMatrix4*  m;
    const float*     row;
    int              i, c;

    if (v->numSolids == 0) {
        return;
    }

    // The view matrix is the camera's, straight out of CurrentKey, with two
    // conversions and no third: bMatrix4 is row-vector (a point multiplies
    // on the LEFT) where C3D_Mtx is column-vector, so it transposes; and the
    // engine's view space is +y down, +z forward where citro3d's is +y up,
    // -z forward, so rows 1 and 2 of the result are negated. Z is up in
    // eSolid space and the mover already knows that -- its boom elevates
    // around world Z and its final eRotateX/eRotateY are exactly the change
    // of basis that puts it on screen.
    m = &v->cam.CurrentKey.Matrix;
    row = &m->v0.x;
    for (i = 0; i < 4; i++) {
        float sign = (i == 1) ? VIEW_FLIP_Y : (i == 2) ? VIEW_FLIP_Z : 1.0f;
        for (c = 0; c < 4; c++) {
            // C3D_FVec is declared w, z, y, x -- in that order -- so c[0]
            // is the w lane and r[i].c[j] is element (i, 3 - j). Writing
            // c[j] as though it were column j mirrors every row: the
            // translation lands in column 0, the camera never leaves the
            // origin, and the car draws as a fan of triangles seen from
            // inside it. That is what the first emulator run showed.
            view.r[i].c[3 - c] = sign * row[c * 4 + i];
        }
    }

    // And the projection is the camera's too: FieldOfView is a BAM, 65536 to
    // the turn, and the mover writes 8000 of them (about 44 degrees) every
    // frame. NearZ and FarZ come from the mover as well, 0.5 and 5000.
    Mtx_PerspTilt(&proj,
                  (float)v->cam.CurrentKey.FieldOfView * (2.0f * M_PI /
                                                          65536.0f),
                  400.0f / 240.0f, v->cam.CurrentKey.NearZ,
                  v->cam.CurrentKey.FarZ, false);

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
