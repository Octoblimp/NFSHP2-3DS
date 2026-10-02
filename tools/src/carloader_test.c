// Host harness for tools/carloader_check.py: runs carloader.c over the
// scenario and prints what each op leaves -- the loader, its two lists and
// every call into the seams and the slot pool.
//
// The pool is this file's: 160 slots, each filled with 0xcd when handed
// out and the lowest free one first, as the model's stub hands them out.
// The five seams print their arguments; the loads queue their completion,
// and D (or ServiceResourceLoading, from UnloadEverything) runs the oldest.
//
// Scenario lines:
//   B <n>                     scenario n
//   R <hex>                   the 64 car records, 1376 bytes each, widened
//                             to the host's CarTypeInfo; CarTypeInfoArray
//   A <type> <off> <hex>      bytes into a record, below pCarSpecs
//   S <rr|fe|lang> <n>        the loader's two flags, or the language
//   W <0|1>                   the ops act on TheCarLoader or a second one
//   P <hex>                   the loader's 32 bytes set to the byte
//   C                         TheCarLoader's static constructor
//   N                         carloader_construct on the loader
//   I, X                      InitCarLoader, CloseCarLoader
//   L|U <ride>                Load, Unload
//   Q <ride> <requested>      IsLoaded
//   E, M, Y, Z                UnloadEverything, RemoveUnusedCarsAndSkins,
//                             LoadingDoneCallback, the destructor
//   G <0|1|2>                 BeginLoading with NULL, cb or cb2; cb2 calls
//                             BeginLoading with cb
//   D                         the oldest load is done
//   T <ride> <num> <max> <fe> <keep>
//                             GetUsedTextures on a skin made from the ride,
//                             over the list (filled with eeeeeeee unless
//                             keep); a num of -1 is the last answer
//   FC <type> <0|1>           FindLoadedCar on the body's or dash's name
//   FS <type> <skin>          FindLoadedSkin
//   FN <hex>                  FindLoadedCar on a name
// A <ride> is Type, InstanceIndex, SkinNumber, HasDash and
// CanBeVertexDamaged. Every op is echoed as "> " and its first 40
// characters, and every one but B and P prints the loader.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "carloader.h"
#include "cartypeinfo.h"
#include "trackflow.h"

#define REC_SIZE   1376
#define NUM_TYPES  64
#define NSLOT      160
#define SLOT_BYTES 128
#define PATTERN    0xcd
#define NTEX       600
#define MAXPEND    16
#define MAXRF      256
#define MAX_SERVICES 50

void (*gUnloadResourceFileFn)(void *file);

typedef union Slot {
    uint8_t   b[SLOT_BYTES];
    uintptr_t align;
} Slot;

static Slot   slots[NSLOT];
static int    slot_used[NSLOT];
static char   pool_token;
static TexturePack fake_pack;
static char   rf_tokens[MAXRF];
static int    nrf;
static CarLoader scratch;
static CarLoader *cur = &TheCarLoader;
static int32_t language;
static int    services;

typedef struct Pending {
    CarLoaderDoneFn done;
    intptr_t        param;
} Pending;

static Pending pend[MAXPEND];
static int     npend;

static uint8_t *recmem;
static uint32_t tex[NTEX];
static int      last_ret;

static char  *line;
static size_t line_cap;

// --------------------------------------------------------------- labels

static const char *nm(const void *p)
{
    static char buf[4][32];
    static int k;
    char *b = buf[k++ & 3];
    const uint8_t *q = p;

    if (p == NULL)
        return "NULL";
    if (p == &pool_token)
        return "pool";
    if (p == &fake_pack)
        return "pack";
    if (p == &TheCarLoader)
        return "L0";
    if (p == &scratch)
        return "L1";
    if (p == &TheCarLoader.LoadedCarList)
        return "L0.cars";
    if (p == &TheCarLoader.LoadedSkinList)
        return "L0.skins";
    if (p == &scratch.LoadedCarList)
        return "L1.cars";
    if (p == &scratch.LoadedSkinList)
        return "L1.skins";
    if (q >= slots[0].b && q < slots[NSLOT].b
        && (size_t)(q - slots[0].b) % sizeof(Slot) == 0) {
        snprintf(b, 32, "#%d", (int)((size_t)(q - slots[0].b) / sizeof(Slot)));
        return b;
    }
    if (q >= (const uint8_t *)rf_tokens
        && q < (const uint8_t *)rf_tokens + MAXRF) {
        snprintf(b, 32, "rf%d", (int)(q - (const uint8_t *)rf_tokens));
        return b;
    }
    return "?";
}

static void user_cb(void);
static void user_cb2(void);

static const char *cnm(void (*f)(void))
{
    if (f == NULL)
        return "NULL";
    if (f == user_cb)
        return "cb";
    if (f == user_cb2)
        return "cb2";
    return "?";
}

static const char *dnm(CarLoaderDoneFn f)
{
    if (f == NULL)
        return "NULL";
    if (f == carloader_loading_done_callback_bridge)
        return "bridge";
    return "?";
}

// ------------------------------------------------------------- the pool

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *name,
                        int memoryPool)
{
    printf("  newpool %d %d %s %d\n", slotSize, numSlots, name, memoryPool);
    return (BSlotPool *)(void *)&pool_token;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("  delpool %s\n", nm(pool));
}

void *bSlotOMalloc(BSlotPool *pool)
{
    int i;

    for (i = 0; i < NSLOT; i++) {
        if (!slot_used[i]) {
            slot_used[i] = 1;
            memset(&slots[i], PATTERN, sizeof slots[i]);
            printf("  omalloc %s -> #%d\n", nm(pool), i);
            return &slots[i];
        }
    }
    fprintf(stderr, "slots full\n");
    exit(3);
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    const uint8_t *q = slot;

    printf("  free %s %s\n", nm(pool), nm(slot));
    if (q >= slots[0].b && q < slots[NSLOT].b)
        slot_used[(size_t)(q - slots[0].b) / sizeof(Slot)] = 0;
}

// ------------------------------------------------------------ the seams

static void push_pending(CarLoaderDoneFn done, intptr_t param)
{
    if (npend >= MAXPEND) {
        fprintf(stderr, "too many loads\n");
        exit(3);
    }
    pend[npend].done = done;
    pend[npend].param = param;
    npend++;
}

// The oldest load is done.
static void complete(void)
{
    Pending p;

    if (npend == 0) {
        printf("  nothing pending\n");
        return;
    }
    p = pend[0];
    memmove(pend, pend + 1, (size_t)(npend - 1) * sizeof pend[0]);
    npend--;
    if (p.done != NULL)
        p.done(p.param);
}

static void *s_load_res(const char *name, int type, int arg,
                        CarLoaderDoneFn done, intptr_t param)
{
    if (nrf >= MAXRF)
        exit(3);
    printf("  loadres %s %d %d %s %s -> rf%d\n", name, type, arg, dnm(done),
           nm((const void *)param), nrf);
    push_pending(done, param);
    return &rf_tokens[nrf++];
}

static void s_unload_res(void *file)
{
    printf("  unloadres %s\n", nm(file));
}

static void s_service(void)
{
    printf("  service\n");
    if (++services > MAX_SERVICES) {
        printf("service spin\n");
        exit(9);
    }
    if (npend > 0)
        complete();
}

static void print_hashes(const uint32_t *h, int n)
{
    int i;

    for (i = 0; i < n; i++)
        printf(" %08x", (unsigned)h[i]);
    printf("\n");
}

static void s_load_tex(TexturePack *p, uint32_t *hashes, int n,
                       CarLoaderDoneFn done, intptr_t param)
{
    printf("  loadtex %s %d %s %s:", nm(p), n, dnm(done),
           nm((const void *)param));
    print_hashes(hashes, n);
    push_pending(done, param);
}

static void s_unload_tex(TexturePack *p, uint32_t *hashes, int n)
{
    printf("  unloadtex %s %d:", nm(p), n);
    print_hashes(hashes, n);
}

static int32_t s_language(void)
{
    return language;
}

static void user_cb(void)
{
    printf("  callback\n");
}

static void user_cb2(void)
{
    printf("  callback2\n");
    carloader_begin_loading(cur, user_cb);
}

// ------------------------------------------------------------ the input

static int hexval(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    return -1;
}

static size_t unhex(const char *s, uint8_t **out)
{
    size_t len = strlen(s) / 2, n;
    uint8_t *b = malloc(len ? len : 1);

    for (n = 0; n < len; n++) {
        int hi = hexval(s[2 * n]), lo = hexval(s[2 * n + 1]);

        if (hi < 0 || lo < 0)
            exit(5);
        b[n] = (uint8_t)(hi << 4 | lo);
    }
    *out = b;
    return len;
}

static int read_line(FILE *f)
{
    size_t n = 0;
    int c;

    while ((c = fgetc(f)) != EOF && c != '\n') {
        if (n + 2 > line_cap) {
            line_cap = line_cap ? 2 * line_cap : 4096;
            line = realloc(line, line_cap);
            if (line == NULL)
                exit(3);
        }
        line[n++] = (char)c;
    }
    if (c == EOF && n == 0)
        return 0;
    if (line == NULL) {
        line_cap = 16;
        line = malloc(line_cap);
    }
    line[n] = '\0';
    return 1;
}

static void op_records(const char *s)
{
    uint8_t *bytes;
    size_t len = unhex(s, &bytes);
    CarTypeInfo *recs;
    int i;

    if (len != (size_t)NUM_TYPES * REC_SIZE)
        exit(4);
    free(recmem);
    recmem = calloc(NUM_TYPES, sizeof(CarTypeInfo));
    recs = (CarTypeInfo *)(void *)recmem;
    for (i = 0; i < NUM_TYPES; i++) {
        const uint8_t *src = bytes + (size_t)i * REC_SIZE;

        memcpy(&recs[i], src, offsetof(CarTypeInfo, pCarSpecs));
        recs[i].pCarSpecs = NULL;
        memcpy(&recs[i].Pad1, src + REC_SIZE - 4, 4);
    }
    CarTypeInfoArray = recs;
    free(bytes);
}

static void op_patch(const char *s)
{
    int type, off, used;
    uint8_t *bytes;
    size_t len;

    if (sscanf(s, "%d %d %n", &type, &off, &used) != 2)
        exit(4);
    len = unhex(s + used, &bytes);
    if (type < 0 || type >= NUM_TYPES || off < 0
        || (size_t)off + len > offsetof(CarTypeInfo, pCarSpecs))
        exit(4);
    memcpy(recmem + (size_t)type * sizeof(CarTypeInfo) + (size_t)off, bytes,
           len);
    free(bytes);
}

static int ride(const char *s, RideInfo *ri, int *used)
{
    int t, i, k, d, v;

    if (sscanf(s, "%d %d %d %d %d %n", &t, &i, &k, &d, &v, used) != 5)
        return 0;
    ri->Type = t;
    ri->InstanceIndex = (int8_t)i;
    ri->SkinNumber = (int8_t)k;
    ri->HasDash = (int8_t)d;
    ri->CanBeVertexDamaged = (int8_t)v;
    return 1;
}

// ------------------------------------------------------------ the print

static void print_state(void)
{
    CarLoader *cl = cur;
    bNode *n;
    int k, j;

    printf("st %s cb=%s rr=%d fe=%d lip=%d pool=%s pack=%s\n", nm(cl),
           cnm(cl->pCallback), (int)cl->RoundRobinFlag,
           (int)cl->InFrontEndFlag, (int)cl->LoadingInProgress,
           nm(LoadedCarSlotPool), nm(pCarTexturePack));
    for (n = cl->LoadedCarList.next, k = 0;
         n != &cl->LoadedCarList && n != NULL && k < NSLOT;
         n = n->next, k++) {
        const LoadedCar *c = (const LoadedCar *)(void *)n;

        printf("car %s n=%d ld=%d ok=%d pad=%d rf=%s prev=%s name=", nm(c),
               c->NumInstances, c->Loading, c->Loaded, (uint8_t)c->Padding,
               nm(c->pResourceFile), nm(n->prev));
        for (j = 0; j < 32; j++)
            printf("%02x", (uint8_t)c->GeometryFilename[j]);
        printf("\n");
    }
    if (n == NULL)
        printf("cars null\n");
    else if (k == NSLOT)
        printf("cars loop\n");
    printf("cars end prev=%s\n", nm(cl->LoadedCarList.prev));
    for (n = cl->LoadedSkinList.next, k = 0;
         n != &cl->LoadedSkinList && n != NULL && k < NSLOT;
         n = n->next, k++) {
        const LoadedSkin *s = (const LoadedSkin *)(void *)n;
        const RideInfo *r = &s->TheRideInfo;

        printf("skin %s type=%d inst=%d skin=%d dash=%d dmg=%d n=%d ld=%d "
               "ok=%d prev=%s\n", nm(s), (int)r->Type, r->InstanceIndex,
               r->SkinNumber, r->HasDash, r->CanBeVertexDamaged,
               s->NumInstances, s->Loading, s->Loaded, nm(n->prev));
    }
    if (n == NULL)
        printf("skins null\n");
    else if (k == NSLOT)
        printf("skins loop\n");
    printf("skins end prev=%s\n", nm(cl->LoadedSkinList.prev));
}

static void op_textures(const char *s)
{
    RideInfo ri;
    LoadedSkin sk;
    int used, num, max, fe, keep, ret, lim, j;

    if (!ride(s, &ri, &used)
        || sscanf(s + used, "%d %d %d %d", &num, &max, &fe, &keep) != 4)
        exit(4);
    memset(&sk, PATTERN, sizeof sk);
    loadedskin_construct(&sk, &ri);
    if (!keep)
        for (j = 0; j < NTEX; j++)
            tex[j] = 0xeeeeeeeeu;
    if (num == -1)
        num = last_ret;
    ret = loadedskin_get_used_textures(&sk, tex, num, max, fe);
    last_ret = ret;
    printf("T -> %d type=%d inst=%d skin=%d dash=%d dmg=%d n=%d ld=%d "
           "ok=%d\n", ret, (int)sk.TheRideInfo.Type,
           sk.TheRideInfo.InstanceIndex, sk.TheRideInfo.SkinNumber,
           sk.TheRideInfo.HasDash, sk.TheRideInfo.CanBeVertexDamaged,
           sk.NumInstances, sk.Loading, sk.Loaded);
    lim = (ret > num ? ret : num) + 2;
    if (lim > NTEX)
        lim = NTEX;
    if (lim < 0)
        lim = 0;
    printf("tex");
    print_hashes(tex, lim);
}

static void op_find(const char *s)
{
    int t, w;

    if (s[0] == 'C') {
        const CarTypeInfo *ct;

        sscanf(s + 1, "%d %d", &t, &w);
        ct = cartypeinfo_get(t);
        printf("found %s\n", nm(carloader_find_loaded_car(cur,
            w ? ct->CompressedDashGeometryFilename
              : ct->CompressedGeometryFilename)));
    } else if (s[0] == 'S') {
        sscanf(s + 1, "%d %d", &t, &w);
        printf("found %s\n", nm(carloader_find_loaded_skin(cur, t, w)));
    } else if (s[0] == 'N') {
        uint8_t *name;
        size_t len = unhex(s + 2, &name);

        name = realloc(name, len + 1);
        name[len] = 0;
        printf("found %s\n", nm(carloader_find_loaded_car(cur,
                                                          (char *)name)));
        free(name);
    } else {
        exit(7);
    }
}

int main(int argc, char **argv)
{
    FILE *f;

    if (argc != 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: carloader_test <scenarios>\n");
        return 2;
    }
    gCarLoadResourceFileFn = s_load_res;
    gUnloadResourceFileFn = s_unload_res;
    gServiceResourceLoadingFn = s_service;
    gLoadTexturesFromFileFn = s_load_tex;
    gUnloadTexturesFromFileFn = s_unload_tex;
    gCurrLanguageFn = s_language;
    pCarTexturePack = &fake_pack;

    while (read_line(f)) {
        RideInfo ri;
        char name[16];
        int used, a, show = 1;

        if (line[0] == 'B') {
            printf("%s\n", line);
            continue;
        }
        printf("> %.40s\n", line);
        services = 0;
        switch (line[0]) {
        case 'R':
            op_records(line + 2);
            show = 0;
            break;
        case 'A':
            op_patch(line + 2);
            show = 0;
            break;
        case 'S':
            sscanf(line + 2, "%15s %d", name, &a);
            if (strcmp(name, "rr") == 0)
                cur->RoundRobinFlag = a;
            else if (strcmp(name, "fe") == 0)
                cur->InFrontEndFlag = a;
            else if (strcmp(name, "lang") == 0)
                language = a;
            else
                return 6;
            break;
        case 'W':
            cur = line[2] == '1' ? &scratch : &TheCarLoader;
            break;
        case 'P': {
            unsigned w;

            sscanf(line + 2, "%x", &w);
            memset(cur, (int)w, sizeof *cur);
            show = 0;
            break;
        }
        case 'C':
            carloader_static_init();
            break;
        case 'N':
            carloader_construct(cur);
            break;
        case 'I':
            init_car_loader();
            break;
        case 'X':
            close_car_loader();
            break;
        case 'L':
            if (!ride(line + 2, &ri, &used))
                return 4;
            printf("L -> %d\n", carloader_load(cur, &ri));
            break;
        case 'U':
            if (!ride(line + 2, &ri, &used))
                return 4;
            carloader_unload(cur, &ri);
            break;
        case 'Q':
            if (!ride(line + 2, &ri, &used)
                || sscanf(line + 2 + used, "%d", &a) != 1)
                return 4;
            printf("Q -> %d\n", carloader_is_loaded(cur, &ri, a));
            break;
        case 'E':
            carloader_unload_everything(cur);
            break;
        case 'M':
            carloader_remove_unused_cars_and_skins(cur);
            break;
        case 'Y':
            carloader_loading_done_callback(cur);
            break;
        case 'Z':
            carloader_destruct(cur);
            break;
        case 'G':
            a = line[2] - '0';
            carloader_begin_loading(cur, a == 1 ? user_cb
                                         : a == 2 ? user_cb2 : NULL);
            break;
        case 'D':
            complete();
            break;
        case 'T':
            op_textures(line + 2);
            show = 0;
            break;
        case 'F':
            op_find(line + 1);
            break;
        default:
            fprintf(stderr, "bad op %s\n", line);
            return 7;
        }
        if (show)
            print_state();
    }
    fclose(f);
    return 0;
}
