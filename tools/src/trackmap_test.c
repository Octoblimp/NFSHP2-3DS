// Drives trackmap.c for tools/trackmap_check.py: TrackMap's mode table,
// its constructor, GetAngle with EvalCubic, GetCameraDirection,
// GetCarUVPosition and GetBoxOnMap (8m-6a); MapToScreen, GetSideOfLine,
// CalculateCentroidOfQuad, ClipPolygon, DrawOverOrUnderLay and DrawMap
// (8m-6b). One TrackMap, track, car, pursued car, player, view, drive
// camera and poly. A script of ops, one per line, fields split on '|';
// numbers are C literals, floats their bits:
//
//   fill            every field of the map to its pattern: retail's offset
//                   with 0xa5 on top, and the pointers to junk
//   fillmodes       both tables to 0xaa bytes
//   init            InitTrackMapModeInfo
//   tables          nothing: the tables are printed after it
//   mode|M|OFF|N|V  N bytes (1, 2 or 4) of mode M's record at OFF to V
//   ctor|T|C|P      the constructor; each of T, C, P 1 for the track, the
//                   car and the player, 0 for NULL
//   mask|M          bit i set: the i-th texture the constructor asks for
//                   is not found (the map, CAR_MARKER, CAR_MARKERB,
//                   TRACKMAPFRAME, MAPBACK, START_LINE, BKGBMP)
//   p2p|V           TheRaceParameters.Point2Point
//   track|N         the track's TrackNumber (an int8)
//   cal|X|Y|W|R     the track's calibration: the upper left, the width
//                   in metres and the rotation (a BAM)
//   world|V         WorldTimer
//   stage|V         the race's RaceStage
//   view|V          the player's ViewID
//   mover|T         the view's first mover's Type, or - for an empty list
//   camdir|X|Y|Z    the drive camera's Direction
//   lookback|A      the drive camera's LookBackAngle
//   body|X|Y        the car's BodyMatrix row 0, x and y
//   pos|X|Y         the car's Position, x and y
//   ppos|X|Y        the pursued car's
//   pursued|V       the map's CurrentlyPursuedCar: 1 the pursued car, 0
//                   NULL
//   f|OFF|V         the map's word at retail's offset OFF: the floats and
//                   ints from 0 to 16, the matrix from 32 to 92, and 148
//                   to 164
//   poly            the poly to its pattern: the word at each offset o
//                   from 16 to 152 holds 0xa5000000 + o
//   pv|I|X|Y        the poly's vertex I, x and y
//   puv|I|U|V|Q     its UVs
//   pc|I|C          its colour, a word: r, g, b, a from the low byte up
//   angle           GetAngle, into a halfword that held 0x1234
//   dir             GetCameraDirection, into a vector of 0x7f7f00xx
//   uv|X|Y|Z        GetCarUVPosition of the point
//   box|X|Y|F|B|L|R|A  GetBoxOnMap about (X, Y), F B L R, by A
//   cubic|X|V|T|DT  EvalCubic on x X, speed V, target T, step DT
//   m2s|X0|Y0|Z0|X1|..|Z3  MapToScreen of the four points onto the poly
//   side|AX|AY|BX|BY|PX|PY GetSideOfLine
//   centroid|X0|Y0|..|X3|Y3 CalculateCentroidOfQuad
//   clip|T|L        ClipPolygon of the poly with texture T (0 to 6, or -1
//                   for none) on layer L
//   overlay|T|L     DrawOverOrUnderLay
//   drawmap|A       DrawMap at angle A
//
// After each op: the map's fields and the poly's when they changed, the
// tables after init. The texture and view seams log their calls, and
// ePoly::Render's seam each poly it is given.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "cammover.h"
#include "camera.h"
#include "car.h"
#include "drivecam.h"
#include "epoly.h"
#include "eview.h"
#include "player.h"
#include "race.h"
#include "realtime.h"
#include "track.h"
#include "trackmap.h"

#define NUM_ARGS  16
#define LINE_MAX_ 4096
#define NUM_TEX   7

int32_t        WorldTimer;
RaceParameters TheRaceParameters;
Race          *pCurrentRace;

static TrackMap         map;
static TrackInfo        track;
static Car              car;
static Car              pursuedCar;
static Player           player;
static eView            view;
static Camera           camera;
static DriveCameraMover mover;
static ePoly            poly;
static int32_t          raceStage[4];
static uint32_t         texMask;
static char             texs[NUM_TEX][16];
static char             junk;

static const char *kTexNames[NUM_TEX] = {
    "TRACK%d_MAP", "CAR_MARKER", "CAR_MARKERB", "TRACKMAPFRAME", "MAPBACK",
    "START_LINE", "BKGBMP",
};

static char lastMap[LINE_MAX_];
static char lastPoly[LINE_MAX_];

static float fbits(uint32_t v)
{
    float f;
    memcpy(&f, &v, 4);
    return f;
}

static uint32_t bitsf(float f)
{
    uint32_t v;
    memcpy(&v, &f, 4);
    return v;
}

// -------------------------------------------------------------- the dump

static const char *ptr_name(const void *p)
{
    static char buf[16][32];
    static int k;
    int i;

    k = (k + 1) & 15;
    if (p == NULL) return "0";
    if (p == &junk) return "junk";
    if (p == &track) return "track";
    if (p == &car) return "car";
    if (p == &pursuedCar) return "pcar";
    if (p == &player) return "player";
    for (i = 0; i < NUM_TEX; i++)
        if (p == texs[i]) {
            snprintf(buf[k], sizeof buf[k], "tex%d", i);
            return buf[k];
        }
    snprintf(buf[k], sizeof buf[k], "?%p", p);
    return buf[k];
}

// A poly's fields from retail's offset 16 to 152, and whether it has
// dynamic frame memory.
static int format_poly(char *line, const ePoly *p)
{
    int i, n = 0;

    for (i = 0; i < 4; i++)
        n += sprintf(line + n, " %08x %08x %08x %08x",
                     (unsigned)bitsf(p->Vertices[i].x),
                     (unsigned)bitsf(p->Vertices[i].y),
                     (unsigned)bitsf(p->Vertices[i].z),
                     (unsigned)bitsf(p->Vertices[i].w));
    for (i = 0; i < 4; i++)
        n += sprintf(line + n, " %08x %08x %08x",
                     (unsigned)bitsf(p->UVs[i][0]),
                     (unsigned)bitsf(p->UVs[i][1]),
                     (unsigned)bitsf(p->UVs[i][2]));
    for (i = 0; i < 4; i++)
        n += sprintf(line + n, " %02x%02x%02x%02x", p->Colours[i][0],
                     p->Colours[i][1], p->Colours[i][2], p->Colours[i][3]);
    n += sprintf(line + n, " %u %u %u %u %u %u %u %u %u %d",
                 p->AlphaA, p->AlphaB, p->AlphaC, p->AlphaD, p->AlphaFix,
                 p->AlphaEnabled, p->SunPoly, p->ApplyAspectRatio,
                 p->Flailer, p->pDynamicFrameMemory != NULL);
    return n;
}

static void dump(void)
{
    char line[LINE_MAX_];
    const float *mat = &map.MapRotationMatrix.v0.x;
    int i, n = 0;

    n += sprintf(line + n, "%08x %08x %08x %08x %08x m",
                 (unsigned)bitsf(map.PreviousCameraDirection.x),
                 (unsigned)bitsf(map.PreviousCameraDirection.y),
                 (unsigned)bitsf(map.CurrentCameraSpeed.x),
                 (unsigned)bitsf(map.CurrentCameraSpeed.y),
                 (unsigned)map.PreviousTime);
    for (i = 0; i < 16; i++)
        n += sprintf(line + n, " %08x", (unsigned)bitsf(mat[i]));
    n += sprintf(line + n, " t %s %s %s %s %s %s %s %s %s",
                 ptr_name(map.TrackMapTexture),
                 ptr_name(map.CarMarkerNonrotatingTexture),
                 ptr_name(map.CarMarkerRotatingTexture),
                 ptr_name(map.OverlayTexture),
                 ptr_name(map.UnderlayTexture),
                 ptr_name(map.StartLineTexture),
                 ptr_name(map.FinishLineTexture),
                 ptr_name(map.StartFinishLineTexture),
                 ptr_name(map.RoadblockTexture));
    n += sprintf(line + n, " %s %s %s %s",
                 ptr_name(map.CarToTrack), ptr_name(map.PlayerToTrack),
                 ptr_name(map.CurrentTrack),
                 ptr_name(map.CurrentlyPursuedCar));
    sprintf(line + n, " %08x %08x %d %d %d",
            (unsigned)bitsf(map.CurrentViewDistanceForward),
            (unsigned)bitsf(map.CurrentViewDistanceBackward),
            (int)map.SufficientDataToRenderMe, (int)map.CurrentMode,
            (int)map.CurrentlyDisplayedMode);
    if (strcmp(line, lastMap) != 0) {
        strcpy(lastMap, line);
        printf("  map %s\n", line);
    }
    format_poly(line, &poly);
    if (strcmp(line, lastPoly) != 0) {
        strcpy(lastPoly, line);
        printf("  poly%s\n", line);
    }
}

static void dump_tables(void)
{
    int k;

    for (k = 0; k < TRACKMAP_NUM_MODES; k++) {
        const TrackMapModeInformation *m = &TrackMapModeInfo[k];
        printf("  mode %d %04x %08x %d %d %08x %08x %d %d %08x %08x"
               " %08x %08x %u %08x %08x %08x %u %u %u %08x %u %u\n",
               k, m->AngleX, (unsigned)bitsf(m->H), m->X, m->Y,
               (unsigned)bitsf(m->Width), (unsigned)bitsf(m->Height),
               m->ClippingX, m->ClippingY,
               (unsigned)bitsf(m->ClippingWidth),
               (unsigned)bitsf(m->ClippingHeight),
               (unsigned)bitsf(m->ViewDistanceForward),
               (unsigned)bitsf(m->ViewDistanceBackward),
               m->ZoomToKeepPursuedCarInView,
               (unsigned)bitsf(m->CarDotSize),
               (unsigned)bitsf(m->StartFinishLineWidth),
               (unsigned)bitsf(m->StartFinishLineHeight),
               m->HasRotation, m->HasScrolling, m->HasRotatingCarDots,
               (unsigned)bitsf(m->Alpha), m->IsDrawn, m->HasBorder);
    }
    for (k = 0; k < TRACKMAP_NUM_MARKER_COLOURS; k++)
        printf("  colour %d %u %u %u\n", k, TrackMapMarkerInfo[k].Red,
               TrackMapMarkerInfo[k].Green, TrackMapMarkerInfo[k].Blue);
}

// ------------------------------------------------------------- the seams

static const char *tex_name(uint32_t hash, int *index)
{
    static char buf[32];
    int i;

    snprintf(buf, sizeof buf, "TRACK%d_MAP", track.TrackNumber);
    if (bchunk_hash(buf) == hash) {
        *index = 0;
        return buf;
    }
    for (i = 1; i < NUM_TEX; i++)
        if (bchunk_hash(kTexNames[i]) == hash) {
            *index = i;
            return kTexNames[i];
        }
    *index = -1;
    snprintf(buf, sizeof buf, "%08x", (unsigned)hash);
    return buf;
}

void *get_texture_info(uint32_t name_hash, int use_default,
                       int include_unloaded)
{
    int i;
    const char *n = tex_name(name_hash, &i);

    printf("  texinfo %s %d %d\n", n, use_default, include_unloaded);
    if (i < 0 || (texMask >> i & 1) != 0)
        return NULL;
    return texs[i];
}

eView *eGetView(int32_t id)
{
    printf("  view %d\n", (int)id);
    return &view;
}

eRaceStage race_get_race_stage(const Race *r)
{
    return *(const eRaceStage *)(const void *)r;
}

static void render_poly(ePoly *p, TextureInfo *tex, int flags)
{
    char line[LINE_MAX_];

    format_poly(line, p);
    printf("  render %s %d%s\n", ptr_name(tex), flags, line);
}

// --------------------------------------------------------------- the ops

static uint32_t num(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static TextureInfo *tex_arg(const char *s)
{
    int32_t i = (int32_t)num(s);

    return (i >= 0 && i < NUM_TEX) ? (TextureInfo *)(void *)texs[i] : NULL;
}

static void fill(void)
{
    float *mat = &map.MapRotationMatrix.v0.x;
    int i;

    map.PreviousCameraDirection.x = fbits(0xa5000000u);
    map.PreviousCameraDirection.y = fbits(0xa5000004u);
    map.CurrentCameraSpeed.x = fbits(0xa5000008u);
    map.CurrentCameraSpeed.y = fbits(0xa500000cu);
    map.PreviousTime = 0xa5000010u;
    for (i = 0; i < 16; i++)
        mat[i] = fbits(0xa5000020u + 4u * (uint32_t)i);
    map.TrackMapTexture = (TextureInfo *)(void *)&junk;
    map.CarMarkerNonrotatingTexture = (TextureInfo *)(void *)&junk;
    map.CarMarkerRotatingTexture = (TextureInfo *)(void *)&junk;
    map.OverlayTexture = (TextureInfo *)(void *)&junk;
    map.UnderlayTexture = (TextureInfo *)(void *)&junk;
    map.StartLineTexture = (TextureInfo *)(void *)&junk;
    map.FinishLineTexture = (TextureInfo *)(void *)&junk;
    map.StartFinishLineTexture = (TextureInfo *)(void *)&junk;
    map.RoadblockTexture = (TextureInfo *)(void *)&junk;
    map.CarToTrack = (Car *)(void *)&junk;
    map.PlayerToTrack = (Player *)(void *)&junk;
    map.CurrentTrack = (TrackInfo *)(void *)&junk;
    map.CurrentlyPursuedCar = (Car *)(void *)&junk;
    map.CurrentViewDistanceForward = fbits(0xa5000094u);
    map.CurrentViewDistanceBackward = fbits(0xa5000098u);
    map.SufficientDataToRenderMe = (int32_t)0xa500009cu;
    map.CurrentMode = (int32_t)0xa50000a0u;
    map.CurrentlyDisplayedMode = (int32_t)0xa50000a4u;
}

static void fill_poly(void)
{
    uint8_t *b = (uint8_t *)&poly;
    uint32_t o;

    for (o = 16; o < 156; o += 4) {
        uint32_t v = 0xa5000000u + o;
        memcpy(b + o, &v, 4);
    }
    poly.pDynamicFrameMemory = NULL;
}

static void set_field(uint32_t off, uint32_t v)
{
    float *mat = &map.MapRotationMatrix.v0.x;

    switch (off) {
    case 0:   map.PreviousCameraDirection.x = fbits(v); break;
    case 4:   map.PreviousCameraDirection.y = fbits(v); break;
    case 8:   map.CurrentCameraSpeed.x = fbits(v); break;
    case 12:  map.CurrentCameraSpeed.y = fbits(v); break;
    case 16:  map.PreviousTime = v; break;
    case 148: map.CurrentViewDistanceForward = fbits(v); break;
    case 152: map.CurrentViewDistanceBackward = fbits(v); break;
    case 156: map.SufficientDataToRenderMe = (int32_t)v; break;
    case 160: map.CurrentMode = (int32_t)v; break;
    case 164: map.CurrentlyDisplayedMode = (int32_t)v; break;
    default:
        if (off >= 32 && off < 96 && off % 4 == 0)
            mat[(off - 32) / 4] = fbits(v);
        else
            printf("  bad field %u\n", (unsigned)off);
    }
}

static void run(char *line)
{
    char *a[NUM_ARGS];
    int   n = 0;
    char *p = line;
    int   tables = 0;

    while (n < NUM_ARGS) {
        a[n++] = p;
        p = strchr(p, '|');
        if (!p) break;
        *p++ = 0;
    }
    if (!strcmp(a[0], "fill")) {
        fill();
    } else if (!strcmp(a[0], "fillmodes")) {
        memset(TrackMapModeInfo, 0xaa, sizeof TrackMapModeInfo);
        memset(TrackMapMarkerInfo, 0xaa, sizeof TrackMapMarkerInfo);
        tables = 1;
    } else if (!strcmp(a[0], "init")) {
        trackmap_init_mode_info();
        tables = 1;
    } else if (!strcmp(a[0], "tables")) {
        tables = 1;
    } else if (!strcmp(a[0], "mode")) {
        uint32_t v = num(a[4]);
        memcpy((uint8_t *)&TrackMapModeInfo[num(a[1])] + num(a[2]), &v,
               num(a[3]));
    } else if (!strcmp(a[0], "ctor")) {
        trackmap_construct(&map, num(a[1]) ? &track : NULL,
                           num(a[2]) ? &car : NULL,
                           num(a[3]) ? &player : NULL);
    } else if (!strcmp(a[0], "mask")) {
        texMask = num(a[1]);
    } else if (!strcmp(a[0], "p2p")) {
        TheRaceParameters.Point2Point = (int32_t)num(a[1]);
    } else if (!strcmp(a[0], "track")) {
        track.TrackNumber = (int8_t)num(a[1]);
    } else if (!strcmp(a[0], "cal")) {
        track.TrackMapCalibrationUpperLeft.x = fbits(num(a[1]));
        track.TrackMapCalibrationUpperLeft.y = fbits(num(a[2]));
        track.TrackMapCalibrationMapWidthMetres = fbits(num(a[3]));
        track.TrackMapCalibrationRotation = (uint16_t)num(a[4]);
    } else if (!strcmp(a[0], "world")) {
        WorldTimer = (int32_t)num(a[1]);
    } else if (!strcmp(a[0], "stage")) {
        raceStage[0] = (int32_t)num(a[1]);
    } else if (!strcmp(a[0], "view")) {
        player.ViewID = (int32_t)num(a[1]);
    } else if (!strcmp(a[0], "mover")) {
        if (a[1][0] == '-') {
            view.CameraMoverList.next = &view.CameraMoverList;
        } else {
            view.CameraMoverList.next = &mover.base.Node;
            mover.base.Type = (CameraMoverType)(int32_t)num(a[1]);
        }
    } else if (!strcmp(a[0], "camdir")) {
        camera.CurrentKey.Direction.x = fbits(num(a[1]));
        camera.CurrentKey.Direction.y = fbits(num(a[2]));
        camera.CurrentKey.Direction.z = fbits(num(a[3]));
    } else if (!strcmp(a[0], "lookback")) {
        mover.LookBackAngle = (uint16_t)num(a[1]);
    } else if (!strcmp(a[0], "body")) {
        car.State.BodyMatrix.v0.x = fbits(num(a[1]));
        car.State.BodyMatrix.v0.y = fbits(num(a[2]));
    } else if (!strcmp(a[0], "pos")) {
        car.State.Position.x = fbits(num(a[1]));
        car.State.Position.y = fbits(num(a[2]));
    } else if (!strcmp(a[0], "ppos")) {
        pursuedCar.State.Position.x = fbits(num(a[1]));
        pursuedCar.State.Position.y = fbits(num(a[2]));
    } else if (!strcmp(a[0], "pursued")) {
        map.CurrentlyPursuedCar = num(a[1]) ? &pursuedCar : NULL;
    } else if (!strcmp(a[0], "f")) {
        set_field(num(a[1]), num(a[2]));
    } else if (!strcmp(a[0], "poly")) {
        fill_poly();
    } else if (!strcmp(a[0], "pv")) {
        poly.Vertices[num(a[1])].x = fbits(num(a[2]));
        poly.Vertices[num(a[1])].y = fbits(num(a[3]));
    } else if (!strcmp(a[0], "puv")) {
        poly.UVs[num(a[1])][0] = fbits(num(a[2]));
        poly.UVs[num(a[1])][1] = fbits(num(a[3]));
        poly.UVs[num(a[1])][2] = fbits(num(a[4]));
    } else if (!strcmp(a[0], "pc")) {
        uint32_t c = num(a[2]);
        memcpy(poly.Colours[num(a[1])], &c, 4);
    } else if (!strcmp(a[0], "angle")) {
        uint16_t angle = 0x1234;
        int32_t r = trackmap_get_angle(&map, &angle);
        printf("  angle %d %04x\n", (int)r, angle);
    } else if (!strcmp(a[0], "dir")) {
        bVector3 d;
        int32_t r;
        d.x = fbits(0x7f7f0001u);
        d.y = fbits(0x7f7f0002u);
        d.z = fbits(0x7f7f0003u);
        r = trackmap_get_camera_direction(&map, &d);
        printf("  dir %d %08x %08x %08x\n", (int)r, (unsigned)bitsf(d.x),
               (unsigned)bitsf(d.y), (unsigned)bitsf(d.z));
    } else if (!strcmp(a[0], "uv")) {
        bVector3 v;
        bVector2 o;
        v.x = fbits(num(a[1]));
        v.y = fbits(num(a[2]));
        v.z = fbits(num(a[3]));
        o.x = fbits(0x7f7f0011u);
        o.y = fbits(0x7f7f0012u);
        trackmap_get_car_uv_position(&map, &o, &v);
        printf("  uv %08x %08x\n", (unsigned)bitsf(o.x),
               (unsigned)bitsf(o.y));
    } else if (!strcmp(a[0], "box")) {
        bVector2 c, o[4];
        int i;
        c.x = fbits(num(a[1]));
        c.y = fbits(num(a[2]));
        for (i = 0; i < 4; i++) {
            o[i].x = fbits(0x7f7f0020u + 2u * (uint32_t)i);
            o[i].y = fbits(0x7f7f0021u + 2u * (uint32_t)i);
        }
        trackmap_get_box_on_map(&map, &c, fbits(num(a[3])), fbits(num(a[4])),
                                fbits(num(a[5])), fbits(num(a[6])),
                                (uint16_t)num(a[7]), o);
        printf("  box");
        for (i = 0; i < 4; i++)
            printf(" %08x %08x", (unsigned)bitsf(o[i].x),
                   (unsigned)bitsf(o[i].y));
        printf("\n");
    } else if (!strcmp(a[0], "cubic")) {
        float x = fbits(num(a[1])), v = fbits(num(a[2]));
        eval_cubic(&x, &v, fbits(num(a[3])), fbits(num(a[4])));
        printf("  cubic %08x %08x\n", (unsigned)bitsf(x), (unsigned)bitsf(v));
    } else if (!strcmp(a[0], "m2s")) {
        bVector3 q[4];
        int i;
        for (i = 0; i < 4; i++) {
            q[i].x = fbits(num(a[1 + 3 * i]));
            q[i].y = fbits(num(a[2 + 3 * i]));
            q[i].z = fbits(num(a[3 + 3 * i]));
        }
        trackmap_map_to_screen(&map, &poly, &q[0], &q[1], &q[2], &q[3]);
        printf("  pts");
        for (i = 0; i < 4; i++)
            printf(" %08x %08x %08x", (unsigned)bitsf(q[i].x),
                   (unsigned)bitsf(q[i].y), (unsigned)bitsf(q[i].z));
        printf("\n");
    } else if (!strcmp(a[0], "side")) {
        bVector2 pa, pb, pp;
        pa.x = fbits(num(a[1]));
        pa.y = fbits(num(a[2]));
        pb.x = fbits(num(a[3]));
        pb.y = fbits(num(a[4]));
        pp.x = fbits(num(a[5]));
        pp.y = fbits(num(a[6]));
        printf("  side %d\n", (int)get_side_of_line(&pa, &pb, &pp));
    } else if (!strcmp(a[0], "centroid")) {
        bVector2 q[4], o;
        int i;
        for (i = 0; i < 4; i++) {
            q[i].x = fbits(num(a[1 + 2 * i]));
            q[i].y = fbits(num(a[2 + 2 * i]));
        }
        o.x = fbits(0x7f7f0051u);
        o.y = fbits(0x7f7f0052u);
        calculate_centroid_of_quad(&o, q);
        printf("  centroid %08x %08x\n", (unsigned)bitsf(o.x),
               (unsigned)bitsf(o.y));
    } else if (!strcmp(a[0], "clip")) {
        trackmap_clip_polygon(&map, &poly, tex_arg(a[1]),
                              (int32_t)num(a[2]));
    } else if (!strcmp(a[0], "overlay")) {
        trackmap_draw_over_or_under_lay(&map, tex_arg(a[1]),
                                        (int32_t)num(a[2]));
    } else if (!strcmp(a[0], "drawmap")) {
        bVector2 c, o[4];
        int i;
        c.x = fbits(0x7f7f0031u);
        c.y = fbits(0x7f7f0032u);
        for (i = 0; i < 4; i++) {
            o[i].x = fbits(0x7f7f0040u + 2u * (uint32_t)i);
            o[i].y = fbits(0x7f7f0041u + 2u * (uint32_t)i);
        }
        trackmap_draw_map(&map, &c, o, (uint16_t)num(a[1]));
        printf("  drawmap %08x %08x", (unsigned)bitsf(c.x),
               (unsigned)bitsf(c.y));
        for (i = 0; i < 4; i++)
            printf(" %08x %08x", (unsigned)bitsf(o[i].x),
                   (unsigned)bitsf(o[i].y));
        printf("\n");
    } else {
        printf("  bad op %s\n", a[0]);
    }
    if (tables)
        dump_tables();
    dump();
}

int main(int argc, char **argv)
{
    static char line[LINE_MAX_];
    FILE       *f;

    if (argc < 2) return 2;
    f = fopen(argv[1], "r");
    if (!f) return 2;

    pCurrentRace = (Race *)(void *)raceStage;
    view.CameraMoverList.next = &view.CameraMoverList;
    view.CameraMoverList.prev = &view.CameraMoverList;
    mover.base.pCamera = &camera;
    gEPolyRenderFn = render_poly;
    fill();
    fill_poly();

    while (fgets(line, sizeof line, f)) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r'))
            line[--n] = 0;
        if (!n) continue;
        printf("> %s\n", line);
        run(line);
        fflush(stdout);
    }
    fclose(f);
    return 0;
}
