# CarLoader

Retail's carloader.cpp is the set of car bodies, dashes and skins the
game wants resident, and the loads that bring them in. The port has it in
`carloader.{c,h}`. Retail's ELF is stripped, so the addresses below are
retail's with the demo's beside them, and the names are the demo's.

| | retail | demo |
|---|---:|---:|
| `InitCarLoader()` | 0x001b0260 | 0x001a6b78 |
| `CloseCarLoader()` | 0x001b0290 | 0x001a6ba8 |
| `LoadedSkin::LoadedSkin(RideInfo *)` | 0x001b02b8 | 0x001a6bd0 |
| `LoadedSkin::GetUsedTextures(uint *, int, int, int)` | 0x001b02f8, changed | 0x001a6c10 |
| `LoadedCar::LoadedCar(const char *)` | 0x001b0470 | 0x001a6da0 |
| `CarLoader::FindLoadedCar(const char *)` | 0x001b04b0 | 0x001a6de0 |
| `CarLoader::FindLoadedSkin(int, int)` | 0x001b0518 | 0x001a6e48 |
| `CarLoader::Load(RideInfo *)` | 0x001b0560, changed | 0x001a6e90 |
| `CarLoader::IsLoaded(RideInfo *, int)` | 0x001b06f8, changed | 0x001a7028 |
| `CarLoader::Unload(RideInfo *)` | 0x001b07e0, changed | 0x001a7110 |
| `CarLoader::UnloadEverything()` | 0x001b08c0 | 0x001a7200 |
| `CarLoader::RemoveUnusedCarsAndSkins()` | 0x001b09b0 | 0x001a72f0 |
| `CarLoader::BeginLoading(void (*)())` | 0x001b0b00 | 0x001a7440 |
| `CarLoader::LoadingDoneCallback()` | 0x001b0c30 | 0x001a7570 |
| `CarLoader::~CarLoader()` | 0x001b0cf8 | 0x001a7638 |
| `_GLOBAL_$D$TheCarLoader` | 0x001b0d58 | 0x001a7698 |
| `_GLOBAL_$I$TheCarLoader` | 0x001b0d68 | 0x001a76a8, `__CTOR_LIST__` [56] |
| `CarLoader::LoadingDoneCallbackBridge(int)` | 0x001b0da0 | 0x001a76e0 |
| the two `bTList` destructors | 0x001b0da8, 0x001b0e18 | |
| `LoadedCar`'s and `LoadedSkin`'s deleting destructors | 0x001b0e88, 0x001b0ed8 | |
| their operator deletes | 0x001b0fb0, 0x001b0fc0 | |
| `CarTypeInfo::GetNumSkins()` | 0x001884b8, new | |
| `CarTypeInfo::GetSkinNumber(int)` | 0x001884d8, new | |
| `TheCarLoader` | 0x00313a38 | |
| `LoadedCarSlotPool` | gp-18888 | |
| `pCarTexturePack` | gp-21436 | |

## The records

```
LoadedCar, 48 bytes                 LoadedSkin, 20 bytes
  0  bNode (next, prev)               0  bNode (next, prev)
  8  s8  NumInstances                 8  RideInfo TheRideInfo
  9  s8  Loading                         (Type s32, InstanceIndex s8,
 10  s8  Loaded                           SkinNumber s8, HasDash s8,
 11  s8  (pad, left as allocated)         CanBeVertexDamaged s8)
 12  ResourceFile *pResourceFile     16  s8  NumInstances
 16  char GeometryFilename[32]       17  s8  Loading
                                     18  s8  Loaded
CarLoader, 32 bytes                  19  (pad, left as allocated)
  0  void (*pCallback)()
  4  s32 RoundRobinFlag
  8  s32 InFrontEndFlag
 12  s32 LoadingInProgress
 16  bTList<LoadedCar>  LoadedCarList
 24  bTList<LoadedSkin> LoadedSkinList
```

Both kinds of entry come from LoadedCarSlotPool. InitCarLoader makes it:
`bNewSlotPool(48, 42, "LoadedCarSlotPool", 16)`. CloseCarLoader deletes
it and zeroes the pointer. The static constructor is the inline
constructor over TheCarLoader. It sets no callback, RoundRobinFlag 1,
InFrontEndFlag 0, LoadingInProgress 0, and both lists empty.

## Load, IsLoaded and Unload

```
want(name)
    c = FindLoadedCar(name)                  strcmp, first in list order
    if !c: c = new LoadedCar(name); LoadedCarList.AddTail(c)
    c->NumInstances++

Load(ri)
    ct = GetCarTypeInfo(ri->Type)
    car = want(ct->CompressedGeometryFilename)          +96
    if ri->HasDash: want(ct->CompressedDashGeometryFilename)   +160
    s = FindLoadedSkin(ri->Type, ri->SkinNumber)
    if !s: s = new LoadedSkin(ri); LoadedSkinList.AddTail(s)
    else if ri->HasDash: s->TheRideInfo.HasDash = 1
    s->NumInstances++
    return car->NumInstances - 1                         as a signed byte

IsLoaded(ri, requested)
    every entry the ride needs exists, and with requested 0 each is
    Loaded as well; 0 at the first that fails

Unload(ri)
    if !IsLoaded(ri, 1): return
    body, dash (if HasDash) and skin each NumInstances--
    RemoveUnusedCarsAndSkins()
```

- **Retail reads the Compressed names.** The demo's Load, IsLoaded and
  Unload read GeometryFilename (+64) and DashGeometryFilename (+128).
  Retail's read the `.LZC` names at +96 and +160. That is most of why
  the three show as changed.
- A skin is one per car type and skin number. Its InstanceIndex,
  CanBeVertexDamaged and HasDash are the first ride's. A later ride with
  a dash turns HasDash on, and nothing turns it off.
- Nothing stops a count at 0. Suppose a skin is still loading when its
  last ride is unloaded. Remove keeps it, so a second Unload of that ride
  still finds every entry and takes the skin to -1. The body is then
  freed under it. An entry at -1 is never freed by Remove, only by
  UnloadEverything or the destructor. The checker covers this for a skin
  and for a dash.

## RemoveUnusedCarsAndSkins and UnloadEverything

```
Remove()
    tex[512], n = 0
    for each car with NumInstances == 0:
        if Loaded: UnloadResourceFile(pResourceFile); Loaded = 0
        if !Loading: unlink, delete
    for each skin with NumInstances == 0:
        if Loaded: n = GetUsedTextures(tex, n, 512, InFrontEndFlag); Loaded = 0
        if !Loading: unlink, delete
    if n: pCarTexturePack->UnloadTexturesFromFile(tex, n)

UnloadEverything()
    every count = 0
    Remove()
    while either list is non-empty:
        ServiceResourceLoading(); Remove()
```

The file pointer is kept after the unload. What is still loading stays
until its load is done, which is why UnloadEverything services the
resource system until both lists are empty.

## BeginLoading and LoadingDoneCallback

```
BeginLoading(callback)
    if callback: pCallback = callback
    if LoadingInProgress: return
    tex[512], n = 0, any = 0
    for each skin:
        if !Loading && !Loaded:
            Loading = 1; any = 1
            n = GetUsedTextures(tex, n, 512, InFrontEndFlag)
        if any && RoundRobinFlag: break
    if any:
        LoadingInProgress = 1
        pCarTexturePack->LoadTexturesFromFile(tex, n, Bridge, this)
        return
    for each car:
        if !Loading && !Loaded:
            LoadingInProgress = 1; Loading = 1
            pResourceFile = LoadResourceFile(GeometryFilename, 5, 8,
                                             Bridge, this)
            return

LoadingDoneCallback()
    every skin, then every car, that is Loading: Loading = 0, Loaded = 1
    LoadingInProgress = 0
    Remove()
    BeginLoading(0)
    if !LoadingInProgress && pCallback:
        cb = pCallback; pCallback = 0; cb()
```

- The skins' textures always go before any geometry. With round robin,
  each load is one skin. Without it, every skin not yet in goes in one
  load, up to 512 hashes. Once each skin is loaded or loading, the
  bodies and dashes follow one file at a time, in list order.
- The callback is cleared before it is called. A callback can therefore
  call BeginLoading with a new one, and that one survives.
- The bridge is a static member that casts its int back to the loader.
  Every completion goes through it with the loader that started the load.

## GetUsedTextures

```
GetUsedTextures(tex, num, max, fe)
    if SkinNumber == -1:
        ct = GetCarTypeInfo(Type)
        for i in 0 .. ct->GetNumSkins()-1:
            SkinNumber = ct->GetSkinNumber(i)
            num = GetUsedTextures(tex, num, max, fe)
        SkinNumber = -1
        return num
    GetUsedCarTextureInfo(&info, &TheRideInfo, fe)
    for each of info.TexturesToLoad:
        if it is in tex[0..num): skip
        if num >= max: return num
        tex[num++] = it
    return num

GetNumSkins()       a cop: 1; otherwise NumAvailableSkins
GetSkinNumber(i)    a cop: CurrLanguage ? 2 : 1;
                    otherwise AvailableSkins[i % NumAvailableSkins]
```

Retail rewrote this. The skin of -1 is new, and so are the two getters
under it, which the demo does not have: a ride can now ask for every
skin a car has. A cop's skin follows the language: 1 is the English
livery and 2 everyone else's. The list is deduplicated across skins, so
a car's shared textures (lights, tyres, plate) are listed once.

## The port

- The resource system and TexturePack's file loads are not ported. The
  four calls are seams: `gCarLoadResourceFileFn`,
  `gServiceResourceLoadingFn`, `gLoadTexturesFromFileFn` and
  `gUnloadTexturesFromFileFn`. UnloadResourceFile is trackflow's
  `gUnloadResourceFileFn`. A NULL seam does nothing. A seam must not run
  its completion before it returns, as retail's never does.
- With no service seam, UnloadEverything returns rather than spin.
- The language comes through `gCurrLanguageFn` (NULL is English).
- The slot size is a literal 48. `carloader.h` checks the layouts when
  pointers are 4 bytes. A 64-bit host's records are wider, and its
  harness hands out bigger slots.

## Checked by

`tools/carloader_check.py` runs everything above as shipped, in
RetailEmu, over GLOBALB's own 64 records. It stubs the slot pool, the
seams and two callbacks. It diffs the result against the port in
`tools/src/carloader_test.c`. After each op it prints the loader, both
lists and every back link.
