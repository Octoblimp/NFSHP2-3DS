// barricade -- BarricadeManager. See barricade.h.

#include "barricade.h"

#include <stdio.h>
#include <stdlib.h>

#include "bmem.h"
#include "collisionbody.h"
#include "vtable.h"

void (*gBarricadeDeleteBarrelFn)(int16_t id);
void (*gBarricadeMarkBodyFadingFn)(struct CollisionBody *body);

static void unported(const char *name)
{
    fprintf(stderr, "barricade: %s is not ported\n", name);
    abort();
}

BarricadeManager *barricademanager_construct(BarricadeManager *b)
{
    int32_t i;

    b->vptr = BARRICADEMANAGER_VTABLE;
    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {
        b->nBarrel[i] = -1;
        b->fFadeTimer[i] = -1.0f;
    }
    return b;
}

void barricademanager_destruct(BarricadeManager *b, int32_t flags)
{
    int32_t i;

    b->vptr = BARRICADEMANAGER_VTABLE;
    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {
        if (b->nBarrel[i] == -1)
            continue;
        if (gBarricadeDeleteBarrelFn == NULL)
            unported("the barrel's delete (0x0021ef88)");
        gBarricadeDeleteBarrelFn(b->nBarrel[i]);
    }
    if (flags & 1)
        bFree(b);
}

void barricademanager_fade(BarricadeManager *b, float t)
{
    int32_t i;

    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {
        CollisionBody *body;

        if (b->nBarrel[i] == -1)
            continue;
        b->fFadeTimer[i] = t;
        body = collisionbody_find(b->nBarrel[i]);
        if (body != NULL) {
            if (gBarricadeMarkBodyFadingFn == NULL)
                unported("the barrel body's byte at 1123");
            gBarricadeMarkBodyFadingFn(body);
        }
    }
}

void barricademanager_count_down(BarricadeManager *b, float dt)
{
    int32_t i;

    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {
        if (b->nBarrel[i] == -1 || b->fFadeTimer[i] == -1.0f)
            continue;
        b->fFadeTimer[i] -= dt;
        if (b->fFadeTimer[i] < 0.0f) {
            if (gBarricadeDeleteBarrelFn == NULL)
                unported("the barrel's delete (0x0021ef88)");
            gBarricadeDeleteBarrelFn(b->nBarrel[i]);
            b->fFadeTimer[i] = -1.0f;
            b->nBarrel[i] = -1;
        }
    }
}

typedef void (*DtorFn)(void *self, int32_t flags);

static void barricademanager_dtor_entry(void *self, int32_t flags)
{
    barricademanager_destruct((BarricadeManager *)self, flags);
}

static const VtEntry barricademanager_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)barricademanager_dtor_entry },  // 8  0x0024efd8
};

void barricade_install_vtables(void)
{
    vt_install(BARRICADEMANAGER_VTABLE, barricademanager_vt,
               (int)(sizeof barricademanager_vt
                     / sizeof barricademanager_vt[0]));
}
