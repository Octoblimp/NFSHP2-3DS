// cardamageabove -- Car::DamageAbove and Car::DamageCap: see
// cardamageabove.h.

#include "cardamageabove.h"

#include <math.h>
#include <stddef.h>

#include "bchunk.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "eframe.h"
#include "emath.h"
#include "epoly.h"
#include "player.h"
#include "playerhud.h"
#include "race.h"
#include "texturepack.h"

// gp-31836, gp-31832 and gp-31828.
#define DISTANCE_SCALE  0.005f
#define CAP_SIZE_NEAR   0.05f
#define CAP_SIZE_REPLAY 0.1f

// The GS's RGBA, red in the low byte.
#define COLOUR_SIDE           0xff00aa00u
#define COLOUR_SIDE_PURSUED   0xffcc0000u
#define COLOUR_DAMAGE         0xff005599u
#define COLOUR_DAMAGE_PURSUED 0xff995500u

void car_damage_above(Car *c, bVector3 *eye, bVector3 *direction)
{
    const bVector3 *pos = &c->State.Position;
    float dx, dy, dz, len, inv, nx, ny, nz, dot, cz, a, dist;
    int32_t pursued;

    // The way from the car to the eye, and the turn to it from the
    // camera's direction.
    dx = eye->x - pos->x;
    dy = eye->y - pos->y;
    dz = eye->z - pos->z;
    len = sqrtf((dx * dx + dy * dy) + dz * dz);
    inv = 1.0f / len;
    nx = dx * inv;
    ny = dy * inv;
    nz = dz * inv;
    dot = (direction->x * nx + direction->y * ny) + direction->z * nz;
    cz = direction->x * ny - nx * direction->y;
    a = (dot + 1.0f) * 0.5f;
    if (0.0f <= cz)
        a = -a;
    c->fAngleToCamera = a;

    if (PlayerPlayersByIndex[0] != NULL
        && player_is_nis_playing(PlayerPlayersByIndex[0]))
        return;
    if (PlayerPlayersByIndex[1] != NULL
        && player_is_nis_playing(PlayerPlayersByIndex[1]))
        return;
    if (!TheRaceParameters.BeACop)
        return;
    // Retail reads the state with no test. The port's test is for a race
    // torn down under a world still drawn; retail would read the word at
    // 0, which is not 3 either.
    if (pRaceCoordinator == NULL
        || racecoordinator_get_current_state(pRaceCoordinator)
               != RCSTATE_RACE_IN_PROGRESS)
        return;
    if (pCopManager == NULL)
        return;
    if (c->MyDriver->TheDriverType != DRIVER_TYPE_AI_RACER) {
        if (c->pPlayer == NULL)
            return;
        if (c->pCarTypeInfo->UsageType == CAR_USAGE_TYPE_COP)
            return;
    }

    // Retail takes the way again, the car's position less the eye.
    dx = pos->x - eye->x;
    dy = pos->y - eye->y;
    dz = pos->z - eye->z;
    dist = sqrtf((dx * dx + dy * dy) + dz * dz) * DISTANCE_SCALE;
    if (dist < 0.0f)
        dist = 0.0f;
    if (1.0f < dist)
        dist = 1.0f;
    pursued = copmanager_is_being_pursued(pCopManager, c) != NULL;
    car_damage_cap(c, pursued, pCopManager->fCarDamage[c->CarIndex], dist);
}

// A point times the cap's size, all four lanes, as vmulx has it.
static void cap_point(bVector4 *o, const bVector4 *p, float s)
{
    o->x = p->x * s;
    o->y = p->y * s;
    o->z = p->z * s;
    o->w = p->w * s;
}

static void cap_colours(ePoly *p, uint32_t colour)
{
    int32_t k;

    for (k = 0; k < 4; k++) {
        p->Colours[k][0] = (uint8_t)colour;
        p->Colours[k][1] = (uint8_t)(colour >> 8);
        p->Colours[k][2] = (uint8_t)(colour >> 16);
        p->Colours[k][3] = (uint8_t)(colour >> 24);
    }
}

static void cap_render(ePoly *p, TextureInfo *tex, bMatrix4 *m)
{
    if (gEPolyRender3DFn != NULL)
        gEPolyRender3DFn(p, tex, m, 0);
}

void car_damage_cap(Car *c, int32_t pursued, float damage, float distance)
{
    bVector4 op[5];
    TextureInfo *tex;
    ePoly p;
    bMatrix4 local, *m;
    RCState st;
    uint32_t side;
    float s;
    int32_t i, k;

    tex = GetTextureInfo(bchunk_hash("WHITE16X16_NOALPHA"), 0, 0);
    s = (distance + distance) + CAP_SIZE_NEAR;
    st = racecoordinator_get_current_state(pRaceCoordinator);
    if (st == RCSTATE_INSTANT_REPLAY || st == RCSTATE_POSTRACE)
        s = CAP_SIZE_REPLAY;

    epoly_init(&p);
    p.UVs[0][0] = 0.0f;
    p.UVs[0][1] = 0.0f;
    p.UVs[1][0] = 0.0f;
    p.UVs[1][1] = 1.0f;
    p.UVs[2][0] = 1.0f;
    p.UVs[2][1] = 1.0f;
    p.UVs[3][0] = 1.0f;
    p.UVs[3][1] = 0.0f;
    p.AlphaA = EPOLY_ALPHA_CS;
    p.AlphaB = EPOLY_ALPHA_CD;
    p.AlphaC = 0;
    p.AlphaD = EPOLY_ALPHA_CD;
    p.AlphaFix = 128;
    p.AlphaEnabled = 0;

    m = (bMatrix4 *)eframe_malloc(64);
    if (m == NULL)
        return;
    local.v0 = c->State.BodyMatrix.v0;
    local.v1 = c->State.BodyMatrix.v1;
    local.v2 = c->State.BodyMatrix.v2;
    local.v3.x = c->State.Position.x;
    local.v3.y = c->State.Position.y;
    local.v3.z = c->State.Position.z;
    local.v3.w = 1.0f;
    eMulMatrix(m, (const bMatrix4 *)(const void *)DamageAboveMatrix,
               &local);

    // The quadwords as the VU reads them, the pad as the fourth lane.
    for (k = 0; k < 5; k++) {
        op[k].x = ObjectPoints[k].x;
        op[k].y = ObjectPoints[k].y;
        op[k].z = ObjectPoints[k].z;
        op[k].w = ObjectPoints[k].pad;
    }

    side = pursued ? COLOUR_SIDE_PURSUED : COLOUR_SIDE;
    if (damage == 0.0f) {
        // Each side whole: the point, a corner, the next, the point.
        for (i = 0; i < 4; i++) {
            cap_point(&p.Vertices[0], &op[0], s);
            cap_point(&p.Vertices[1], &op[1 + i], s);
            cap_point(&p.Vertices[2], &op[1 + (i + 1) % 4], s);
            cap_point(&p.Vertices[3], &op[0], s);
            cap_colours(&p, side);
            cap_render(&p, tex, m);
        }
    } else {
        bVector4 edge[4], at;
        float len, f, inv;

        // The four edges up from the point, the first one's length, and
        // `damage` of it. Retail's edges are the square's corners less the
        // point, then made unit by the first edge's length.
        for (k = 0; k < 4; k++) {
            edge[k].x = op[1 + k].x - op[0].x;
            edge[k].y = op[1 + k].y - op[0].y;
            edge[k].z = op[1 + k].z - op[0].z;
            edge[k].w = op[1 + k].w - op[0].w;
        }
        len = sqrtf((edge[0].x * edge[0].x + edge[0].y * edge[0].y)
                    + edge[0].z * edge[0].z);
        f = len * damage;
        inv = 1.0f / len;
        for (k = 0; k < 4; k++) {
            edge[k].x = edge[k].x * inv;
            edge[k].y = edge[k].y * inv;
            edge[k].z = edge[k].z * inv;
            edge[k].w = edge[k].w * inv;
        }

        for (i = 0; i < 4; i++) {
            const int32_t j = (i + 1) % 4;

            // The damage, from the point up to `f` along the two edges.
            cap_point(&p.Vertices[0], &op[0], s);
            cap_point(&p.Vertices[1], &op[0], s);
            at.x = edge[j].x * f + op[0].x;
            at.y = edge[j].y * f + op[0].y;
            at.z = edge[j].z * f + op[0].z;
            at.w = edge[j].w * f + op[0].w;
            cap_point(&p.Vertices[2], &at, s);
            at.x = edge[i].x * f + op[0].x;
            at.y = edge[i].y * f + op[0].y;
            at.z = edge[i].z * f + op[0].z;
            at.w = edge[i].w * f + op[0].w;
            cap_point(&p.Vertices[3], &at, s);
            cap_colours(&p, pursued ? COLOUR_DAMAGE_PURSUED : COLOUR_DAMAGE);
            cap_render(&p, tex, m);

            // The rest of the side, from there to the square.
            p.Vertices[0] = p.Vertices[3];
            p.Vertices[1] = p.Vertices[2];
            cap_point(&p.Vertices[2], &op[1 + j], s);
            cap_point(&p.Vertices[3], &op[1 + i], s);
            cap_colours(&p, side);
            cap_render(&p, tex, m);
        }
    }

    // The square on top.
    cap_point(&p.Vertices[0], &op[1], s);
    cap_point(&p.Vertices[1], &op[2], s);
    cap_point(&p.Vertices[2], &op[3], s);
    cap_point(&p.Vertices[3], &op[4], s);
    cap_colours(&p, side);
    cap_render(&p, tex, m);
}
