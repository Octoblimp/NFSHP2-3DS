// carloader -- see carloader.h.

#include "carloader.h"

#include <stddef.h>
#include <string.h>

#include "cartypeinfo.h"
#include "trackflow.h"

CarLoader TheCarLoader;
BSlotPool *LoadedCarSlotPool;
TexturePack *pCarTexturePack;

void *(*gCarLoadResourceFileFn)(const char *name, int type, int arg,
                                CarLoaderDoneFn done, intptr_t param);
void (*gServiceResourceLoadingFn)(void);
void (*gLoadTexturesFromFileFn)(TexturePack *p, uint32_t *hashes, int n,
                                CarLoaderDoneFn done, intptr_t param);
void (*gUnloadTexturesFromFileFn)(TexturePack *p, uint32_t *hashes, int n);

// The size of the hash lists RemoveUnusedCarsAndSkins and BeginLoading
// keep on the stack.
#define CARLOADER_MAX_TEXTURES 512

// A car's geometry file, its ResourceFileType and LoadResourceFile's third
// argument.
#define CARLOADER_RESOURCE_TYPE 5
#define CARLOADER_RESOURCE_ARG  8

// --------------------------------------------------------------- the lists

// bTList::AddTail, inline in Load.
static void add_tail(bNode *list, bNode *n)
{
    bNode *last = list->prev;

    last->next = n;
    list->prev = n;
    n->prev = last;
    n->next = list;
}

// bNode::Remove, inline wherever an entry is freed. The node's own links
// are left as they were.
static void unlink_node(bNode *n)
{
    bNode *next = n->next;
    bNode *prev = n->prev;

    prev->next = next;
    next->prev = prev;
}

// The deleting destructors (0x001b0e88, 0x001b0ed8) with their 3: the
// bNode destructor does nothing, and the delete is LoadedCar's and
// LoadedSkin's operator delete (0x001b0fb0, 0x001b0fc0), a bFree into the
// pool.
static void delete_entry(void *p)
{
    bSlotFree(LoadedCarSlotPool, p);
}

// --------------------------------------------------------------- lifetime

void carloader_construct(CarLoader *cl)
{
    cl->pCallback = NULL;
    cl->LoadedCarList.prev = &cl->LoadedCarList;
    cl->LoadedSkinList.prev = &cl->LoadedSkinList;
    cl->RoundRobinFlag = 1;
    cl->InFrontEndFlag = 0;
    cl->LoadedCarList.next = &cl->LoadedCarList;
    cl->LoadedSkinList.next = &cl->LoadedSkinList;
    cl->LoadingInProgress = 0;
}

// Retail 0x001b0d68; the demo's _GLOBAL_$I$TheCarLoader is 0x001a76a8.
void carloader_static_init(void)
{
    carloader_construct(&TheCarLoader);
}

void carloader_destruct(CarLoader *cl)
{
    bNode *n;

    // The skins' list first: it is the later member.
    while ((n = cl->LoadedSkinList.next) != &cl->LoadedSkinList) {
        unlink_node(n);
        delete_entry(n);
    }
    while ((n = cl->LoadedCarList.next) != &cl->LoadedCarList) {
        unlink_node(n);
        delete_entry(n);
    }
}

void init_car_loader(void)
{
    LoadedCarSlotPool = bNewSlotPool(48, 42, "LoadedCarSlotPool", 16);
}

void close_car_loader(void)
{
    bDeleteSlotPool(LoadedCarSlotPool);
    LoadedCarSlotPool = NULL;
}

// --------------------------------------------------------------- the skin

LoadedSkin *loadedskin_construct(LoadedSkin *s, const RideInfo *ri)
{
    // RideInfo's own constructor first, then the copy over it.
    s->TheRideInfo.Type = -1;
    s->TheRideInfo.CanBeVertexDamaged = 0;
    s->TheRideInfo.InstanceIndex = 0;
    s->TheRideInfo.SkinNumber = 0;
    s->TheRideInfo.HasDash = 0;
    s->TheRideInfo = *ri;
    s->NumInstances = 0;
    s->Loading = 0;
    s->Loaded = 0;
    return s;
}

int loadedskin_get_used_textures(LoadedSkin *s, uint32_t *tex, int num,
                                 int max, int in_front_end)
{
    UsedCarTextureInfo info;
    int i, j;

    if (s->TheRideInfo.SkinNumber == -1) {
        const CarTypeInfo *ct = cartypeinfo_get(s->TheRideInfo.Type);

        for (i = 0; i < cartypeinfo_get_num_skins(ct); i++) {
            s->TheRideInfo.SkinNumber =
                (int8_t)cartypeinfo_get_skin_number(ct, i);
            num = loadedskin_get_used_textures(s, tex, num, max,
                                               in_front_end);
        }
        s->TheRideInfo.SkinNumber = -1;
        return num;
    }

    cartypeinfo_get_used_car_texture_info(&info, &s->TheRideInfo,
                                          in_front_end);
    for (i = 0; i < info.NumTexturesToLoad; i++) {
        uint32_t h = info.TexturesToLoad[i];
        int found = 0;

        for (j = 0; j < num; j++) {
            if (tex[j] == h) {
                found = 1;
                break;
            }
        }
        if (found)
            continue;
        if (!(num < max))
            return num;
        tex[num++] = h;
    }
    return num;
}

// --------------------------------------------------------------- the car

LoadedCar *loadedcar_construct(LoadedCar *c, const char *name)
{
    strcpy(c->GeometryFilename, name);
    c->NumInstances = 0;
    c->Loading = 0;
    c->Loaded = 0;
    c->pResourceFile = NULL;
    return c;
}

// ------------------------------------------------------------- the lookups

LoadedCar *carloader_find_loaded_car(CarLoader *cl, const char *name)
{
    bNode *n;

    for (n = cl->LoadedCarList.next; n != &cl->LoadedCarList; n = n->next) {
        LoadedCar *c = (LoadedCar *)(void *)n;

        if (strcmp(c->GeometryFilename, name) == 0)
            return c;
    }
    return NULL;
}

LoadedSkin *carloader_find_loaded_skin(CarLoader *cl, int32_t type,
                                       int32_t skin)
{
    bNode *n;

    for (n = cl->LoadedSkinList.next; n != &cl->LoadedSkinList;
         n = n->next) {
        LoadedSkin *s = (LoadedSkin *)(void *)n;

        if (s->TheRideInfo.Type == type && s->TheRideInfo.SkinNumber == skin)
            return s;
    }
    return NULL;
}

// --------------------------------------------------------- load and unload

// The entry for a geometry file, made when there is none.
static LoadedCar *want_car(CarLoader *cl, const char *name)
{
    LoadedCar *c = carloader_find_loaded_car(cl, name);

    if (c == NULL) {
        c = loadedcar_construct(bSlotOMalloc(LoadedCarSlotPool), name);
        add_tail(&cl->LoadedCarList, &c->Node);
    }
    c->NumInstances++;
    return c;
}

int carloader_load(CarLoader *cl, const RideInfo *ri)
{
    const CarTypeInfo *ct = cartypeinfo_get(ri->Type);
    LoadedCar *car;
    LoadedSkin *skin;

    car = want_car(cl, ct->CompressedGeometryFilename);
    if (ri->HasDash)
        want_car(cl, ct->CompressedDashGeometryFilename);

    skin = carloader_find_loaded_skin(cl, ri->Type, ri->SkinNumber);
    if (skin == NULL) {
        skin = loadedskin_construct(bSlotOMalloc(LoadedCarSlotPool), ri);
        add_tail(&cl->LoadedSkinList, &skin->Node);
    } else if (ri->HasDash) {
        // A skin first wanted without its dash lists the dash's textures
        // from now on.
        skin->TheRideInfo.HasDash = 1;
    }
    skin->NumInstances++;
    return car->NumInstances - 1;
}

int carloader_is_loaded(CarLoader *cl, const RideInfo *ri, int requested)
{
    const CarTypeInfo *ct = cartypeinfo_get(ri->Type);
    LoadedCar *c;
    LoadedSkin *s;

    c = carloader_find_loaded_car(cl, ct->CompressedGeometryFilename);
    if (c == NULL || (!requested && !c->Loaded))
        return 0;
    if (ri->HasDash) {
        c = carloader_find_loaded_car(cl, ct->CompressedDashGeometryFilename);
        if (c == NULL || (!requested && !c->Loaded))
            return 0;
    }
    s = carloader_find_loaded_skin(cl, ri->Type, ri->SkinNumber);
    if (s == NULL)
        return 0;
    if (requested)
        return 1;
    return s->Loaded != 0;
}

void carloader_unload(CarLoader *cl, const RideInfo *ri)
{
    const CarTypeInfo *ct = cartypeinfo_get(ri->Type);

    if (!carloader_is_loaded(cl, ri, 1))
        return;
    // Nothing stops a count at 0: a second Unload of an entry still
    // loading takes it to -1, and it is never freed.
    carloader_find_loaded_car(cl, ct->CompressedGeometryFilename)
        ->NumInstances--;
    if (ri->HasDash)
        carloader_find_loaded_car(cl, ct->CompressedDashGeometryFilename)
            ->NumInstances--;
    carloader_find_loaded_skin(cl, ri->Type, ri->SkinNumber)->NumInstances--;
    carloader_remove_unused_cars_and_skins(cl);
}

void carloader_unload_everything(CarLoader *cl)
{
    bNode *n;

    for (n = cl->LoadedCarList.next; n != &cl->LoadedCarList; n = n->next)
        ((LoadedCar *)(void *)n)->NumInstances = 0;
    for (n = cl->LoadedSkinList.next; n != &cl->LoadedSkinList; n = n->next)
        ((LoadedSkin *)(void *)n)->NumInstances = 0;
    carloader_remove_unused_cars_and_skins(cl);
    // What was loading stays until its load is done. With no seam nothing
    // would ever be done, and the port stops rather than spin.
    while (cl->LoadedCarList.next != &cl->LoadedCarList
           || cl->LoadedSkinList.next != &cl->LoadedSkinList) {
        if (gServiceResourceLoadingFn == NULL)
            return;
        gServiceResourceLoadingFn();
        carloader_remove_unused_cars_and_skins(cl);
    }
}

void carloader_remove_unused_cars_and_skins(CarLoader *cl)
{
    uint32_t tex[CARLOADER_MAX_TEXTURES];
    int n = 0;
    bNode *node, *next;

    for (node = cl->LoadedCarList.next; node != &cl->LoadedCarList;
         node = next) {
        LoadedCar *c = (LoadedCar *)(void *)node;

        next = node->next;
        if (c->NumInstances != 0)
            continue;
        if (c->Loaded) {
            // pResourceFile is kept.
            if (gUnloadResourceFileFn != NULL)
                gUnloadResourceFileFn(c->pResourceFile);
            c->Loaded = 0;
        }
        if (!c->Loading) {
            unlink_node(node);
            delete_entry(c);
        }
    }

    for (node = cl->LoadedSkinList.next; node != &cl->LoadedSkinList;
         node = next) {
        LoadedSkin *s = (LoadedSkin *)(void *)node;

        next = node->next;
        if (s->NumInstances != 0)
            continue;
        if (s->Loaded) {
            n = loadedskin_get_used_textures(s, tex, n,
                                             CARLOADER_MAX_TEXTURES,
                                             cl->InFrontEndFlag);
            s->Loaded = 0;
        }
        if (!s->Loading) {
            unlink_node(node);
            delete_entry(s);
        }
    }

    if (n != 0 && gUnloadTexturesFromFileFn != NULL)
        gUnloadTexturesFromFileFn(pCarTexturePack, tex, n);
}

// ------------------------------------------------------------- the loading

void carloader_begin_loading(CarLoader *cl, void (*callback)(void))
{
    uint32_t tex[CARLOADER_MAX_TEXTURES];
    int n = 0;
    int any = 0;
    bNode *node;

    if (callback != NULL)
        cl->pCallback = callback;
    if (cl->LoadingInProgress)
        return;

    for (node = cl->LoadedSkinList.next; node != &cl->LoadedSkinList;
         node = node->next) {
        LoadedSkin *s = (LoadedSkin *)(void *)node;

        if (!s->Loading && !s->Loaded) {
            s->Loading = 1;
            any = 1;
            n = loadedskin_get_used_textures(s, tex, n,
                                             CARLOADER_MAX_TEXTURES,
                                             cl->InFrontEndFlag);
        }
        if (any && cl->RoundRobinFlag)
            break;
    }
    if (any) {
        cl->LoadingInProgress = 1;
        if (gLoadTexturesFromFileFn != NULL)
            gLoadTexturesFromFileFn(pCarTexturePack, tex, n,
                                    carloader_loading_done_callback_bridge,
                                    (intptr_t)cl);
        return;
    }

    // Every skin is in or on its way: one geometry file.
    for (node = cl->LoadedCarList.next; node != &cl->LoadedCarList;
         node = node->next) {
        LoadedCar *c = (LoadedCar *)(void *)node;

        if (!c->Loading && !c->Loaded) {
            cl->LoadingInProgress = 1;
            c->Loading = 1;
            c->pResourceFile = gCarLoadResourceFileFn == NULL ? NULL
                : gCarLoadResourceFileFn(c->GeometryFilename,
                                         CARLOADER_RESOURCE_TYPE,
                                         CARLOADER_RESOURCE_ARG,
                                         carloader_loading_done_callback_bridge,
                                         (intptr_t)cl);
            return;
        }
    }
}

void carloader_loading_done_callback(CarLoader *cl)
{
    bNode *n;

    // Whatever was loading is what the load brought in.
    for (n = cl->LoadedSkinList.next; n != &cl->LoadedSkinList; n = n->next) {
        LoadedSkin *s = (LoadedSkin *)(void *)n;

        if (s->Loading) {
            s->Loading = 0;
            s->Loaded = 1;
        }
    }
    for (n = cl->LoadedCarList.next; n != &cl->LoadedCarList; n = n->next) {
        LoadedCar *c = (LoadedCar *)(void *)n;

        if (c->Loading) {
            c->Loading = 0;
            c->Loaded = 1;
        }
    }
    cl->LoadingInProgress = 0;
    carloader_remove_unused_cars_and_skins(cl);
    carloader_begin_loading(cl, NULL);
    if (!cl->LoadingInProgress && cl->pCallback != NULL) {
        void (*cb)(void) = cl->pCallback;

        cl->pCallback = NULL;
        cb();
    }
}

void carloader_loading_done_callback_bridge(intptr_t param)
{
    carloader_loading_done_callback((CarLoader *)param);
}
