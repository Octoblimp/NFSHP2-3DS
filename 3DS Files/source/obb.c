// obb -- see obb.h.

#include "obb.h"

#include <stdio.h>
#include <stdlib.h>

#include "emath.h"

WorldObject *(*gWorldObjectNewFn)(uint32_t name_hash, const bMatrix4 *matrix,
                                  int32_t add_lighting);
void (*gWorldObjectDeleteFn)(WorldObject *o);

// A cube can only have been made through gWorldObjectNewFn, so a NULL
// delete with a cube to delete is a port that set one seam and not the
// other.
static void delete_cube(WorldObject *o)
{
    if (gWorldObjectDeleteFn == NULL) {
        fprintf(stderr, "obb: a WorldObject to delete and no "
                        "gWorldObjectDeleteFn\n");
        abort();
    }
    gWorldObjectDeleteFn(o);
}

OBB *obb_init(OBB *o)
{
    o->WorldObj = NULL;
    return o;
}

void obb_destroy(OBB *o)
{
    if (o->WorldObj != NULL)
        delete_cube(o->WorldObj);
}

OBB *obb_assign(OBB *dst, OBB *src)
{
    dst->A0 = src->A0;
    dst->A1 = src->A1;
    dst->A2 = src->A2;
    dst->a0 = src->a0;
    dst->a1 = src->a1;
    dst->a2 = src->a2;
    if (dst->WorldObj != NULL)
        delete_cube(dst->WorldObj);
    dst->WorldObj = src->WorldObj;
    src->WorldObj = NULL;
    return dst;
}

static bVector4 scaled(const bVector3 *a, float s)
{
    bVector4 v;

    v.x = a->x * s;
    v.y = a->y * s;
    v.z = a->z * s;
    v.w = a->pad * s;
    return v;
}

void obb_render(OBB *o, const bVector3 *pos)
{
    bMatrix4 m;
    bMatrix4 id;
    bMatrix4 out;

    eIdentity(&m);
    eIdentity(&id);
    m.v0 = scaled(&o->A0, o->a0 + o->a0);
    m.v1 = scaled(&o->A1, o->a1 + o->a1);
    m.v2 = scaled(&o->A2, o->a2 + o->a2);
    eMulMatrix(&out, &m, &id);
    out.v3.x = pos->x;
    out.v3.y = pos->y;
    out.v3.z = pos->z;

    if (o->WorldObj == NULL) {
        if (gWorldObjectNewFn == NULL)
            return;
        o->WorldObj = gWorldObjectNewFn(OBB_DEBUG_CUBE_HASH, NULL, 0);
        if (o->WorldObj == NULL)
            return;
    }
    o->WorldObj->Matrix = out;
    o->WorldObj->Enabled = 1;
}

void obb_do_not_render(OBB *o)
{
    if (o->WorldObj != NULL)
        o->WorldObj->Enabled = 0;
}

void obb_print(OBB *o)
{
    (void)o;
}
