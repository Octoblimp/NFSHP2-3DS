# The effect system's data (AcidFXE.obj, step 16, SC-3a)

The effect system makes the game's particles: smoke from the tyres,
sparks, water, fire, the munitions and the nebula behind the car in the
car select. It is retail's `AcidFXE.obj` (`SLES_507.31`, 0x00126d70 ..
0x001276fc and 0x0012a1e0 .. 0x0012a5e8; the demo's 0x001258d0 ..
0x00126258).

SC-3a is its data half: the slot pools, the emitter datas and emitters a
file brings, LoaderTable slot 6, the lookups, the copies the cars take,
and an AcidEffectSystem's auto emitters and active groups. Nothing makes,
moves or draws a particle yet. TriggerEmitter and DoTimeStep are SC-3b,
RenderEffects is SC-3c, and the car select's nebula is SC-3d.

The port is `3DS Files/source/acidsys.{c,h}`. `tools/afx_check.py` runs
every function here on the retail image in mipsemu, and
`tools/src/afx_test.c` runs the port over the same script.

## The objects

| Struct | Size | What |
|---|---|---|
| AcidEmitterData | 544 | what an effect looks like: its texture, its on and off cycles, how many particles, how long they live and how they move, its colours and sizes, and its group |
| AcidEmitter | 192 | one place that emits: a data, a cycle state, the time left in the cycle, a seed, a LocalWorld and a name |
| AcidParticle | 32 | one particle, from the particles' pool |
| AcidActiveGroup | 28 | one emission's particles, with its emitter, its data and its car |
| AcidEffectSystem | 96 | a list of active groups and a list of auto emitters, three interest points and the debug fields |

`acidsys.h` has every field at retail's offset, with size checks. The
ones this slice reads or writes:

- AcidEmitterData: the Node at 0, NameHash 8, TextureNameHash 12,
  GroupNameHash 16, Texture 20 (a TextureInfo), and OnCycle,
  OnCycleVariance, OffCycle and OffCycleVariance at 32, 36, 40 and 44.
- AcidEmitter: the Node at 0, NameHash 8, EmitterDataNameHash 12, State
  16, RemainingCycleTime 20, EmissionCountdown 24, EmitterData 28,
  LastActiveGroup 32, RandomSeed 36, DontEmit 40, LocalWorld 48 and Name
  128 (64 bytes).
- AcidActiveGroup: EmitterData 8, Emitter 12, pCar 16 and its
  ParticleList at 20.
- AcidEffectSystem: ActiveGroupList 0, AutoEmitterList 8,
  InterestPoints 16, then CurrentEmitter 64 to UpdateTime 92, with
  NumAutoEmitters at 80.

An emitter's State is one of AcidCycleStateNames: 0 OFF, 1 ON, 2
DISABLED and 3 LIBRARY. A LIBRARY emitter is a template. It never emits
itself; afxGetEmitters copies it for a car or the frontend.

## The globals

| Global | Where | What |
|---|---|---|
| AcidParticleSlotPool | gp-23528 | 1000 particles of 32 bytes |
| AcidActiveGroupSlotPool | gp-23524 | 400 groups of 28 bytes |
| AcidEmitterSlotPool | gp-23520 | 600 emitters of 192 bytes |
| NumAcidEmitters | gp-23516 | the copies made and not yet deleted |
| EmitterDataList | gp-23512 | every loaded data, a bTList |
| AcidRandomSeed | gp-23504 | where an emitter with no seed gets one: 0x23985727 at boot |
| FrameEffects | 0x002ef5e0 | the frontend's system, which the nebula goes on |
| WorldEffects | 0x002ef640 | the race's system, which every loaded emitter goes on |

The static constructor (`_GLOBAL_$I$AcidCycleStateNames`, 0x0012a220;
the demo's is entry 9 of its __CTOR_LIST__, 0x00128cd0) empties
EmitterDataList, then constructs FrameEffects and WorldEffects. The
system's constructor (0x00127418) empties both lists and zeroes
CurrentEmitter, SelectEmitterIndex, the bytes 72 to 77 and the four
words from 80. It leaves the interest points and bytes 78 and 79.

**afxInit** (0x00126d70), from InitializeEverything after
InitDisplaySystem, makes the three pools with memory pool 16:
`bNewSlotPool(32, 1000, "AcidParticleSlotPool", 16)`, then the groups'
(28, 400) and the emitters' (192, 600). It clears flags bits 1 and 2
(OVERFLOW_IF_FULL and ZERO_ALLOCATED_MEMORY) on the particles' and the
groups' pools. The emitters' pool keeps them. The three take about
155 KB.

**afxClose** (0x00126e08) kills FrameEffects' active groups, then
WorldEffects', and deletes the particles' and the groups' pools. It
leaves the emitters' pool. Nothing in the image calls it.

The system's destructor (0x0012a398) and the static destructor
(0x0012a1e0) run only at exit and are not ported.

## The chunks

| Id | Version | Record | What |
|---|---|---|---|
| 0x80035000 | | | a container; taken and passed over |
| 0x80035010 | | | a container; taken and passed over |
| 0x00035021 | 4 | 544 B | AcidEmitterDataPackHeader: the datas |
| 0x00035020 | 5 | 192 B | AcidEmitterPackHeader: the emitters |

A pack's header is at `(chunk + 23) & ~15`, the payload rounded up to 16
bytes. Its version is at +8, the count at +12, and the records start at
+16. The records stay where they are in the file.

On the disc:
- No file has either container. Every Acid chunk is at the top level.
- GLOBALB has 111 datas (0x35021 at 0xa3480) and 112 emitters (0x35020
  at 0xb2080). Every emitter is LIBRARY.
- Each of the 30 tracks (TRACKB11..16, 21..26, 31..36, 41..46 and
  61..66) has both packs: 1 to 20 datas and 10 to 40 emitters. Every
  emitter is ON.
- The pointers, RandomSeed and the cycle times are 0 in every record.
- XE_SelectCarNebula is GLOBALB's one data of group FE_EMITTER.

## The loaders (slot 6)

**LoaderAcidFX** (0x00126e50):
- A container returns 1.
- A data pack of version 4 puts each data on EmitterDataList's tail, in
  order. An emitter pack of version 5 gives each emitter the data its
  EmitterDataNameHash names (`SetEmitterData(unsigned int)`), then
  AddAutoEmitter on WorldEffects.
- A pack of any other version is taken (1) and left alone.
- Any other type returns 0.

**UnloaderAcidFX** (0x00126f60) takes the same chunks. It unlinks each
data, and RemoveAutoEmitter(WorldEffects) each emitter, in the pack's
order.

afxTrackLoader and afxTrackUnloader (0x00127068 and 0x00127070) are
empty.

**afxUpdateTextures** (0x00127078) runs from PostLoadFixup. Each data
whose Texture is NULL, or whose texture's NameHash (+32) is not its
TextureNameHash, looks it up again: `GetTextureInfo(TextureNameHash, 0,
0)` (0x001abf48), which may give NULL.

## The lookups

**afxGetEmitterData** (0x00127120) gives the first data after `after`
(NULL is the list's head) with that name and group. A hash of 0 leaves
that test out, and both 0 gives NULL. afxAddEmitterData (0x001270e8) and
afxRemoveEmitterData (0x00127108) put a data on the list's tail and take
it off. Removing leaves the data's own links.

**afxGetEmitter** (0x00127198) does the same over WorldEffects' auto
emitters:
- With a name and a group, the name is the emitter's NameHash and the
  group its data's. An emitter with no data is passed over.
- With a group only, the same.
- With a name only, the name is compared with the **data's** NameHash.
  The listing doesn't test for a data, so an emitter with none reads
  address 8. On the PS2 that is word 8 of RAM, which is 0. A name lookup
  never asks for hash 0, so the emitter is passed over, and the port
  passes it over without the read.

**afxCopyEmitter** (0x00127228):
1. bOMalloc from the emitters' pool.
2. bMemSet(+8, 0, 184), **even when the pool gave NULL**. That clears
   184 bytes at address 8. The port leaves it out.
3. NumAcidEmitters goes up, even for NULL. NULL then returns.
4. NameHash = bStringHash(the original's Name). Name is a bStrNCpy of
   63 bytes, and Name[63] = 0.
5. The original's data, by SetEmitterData, and its LocalWorld.

The copy's State is 0 (OFF) and its seed is 0.

**afxGetEmitters** (0x001272e0) runs afxGetEmitter(0, group, prev) over
WorldEffects' auto emitters, from the head, and puts a copy of each one
found on the list's tail. A copy the pool can't give is left out. The
cars' CarRenderInfo takes one list for each of its CARFX groups this
way, and the car select's nebula takes FE_EMITTER's.

**afxDeleteEmitters** (0x00127368) takes each emitter off the list from
its head and runs its deleting destructor with flags 3.

**SetEmitterData(AcidEmitterData *)** (0x001273c0) sets the data and
returns 1. For NULL it leaves the data and returns 0.
**SetEmitterData(unsigned int)** (0x001273d8) does the same with
`afxGetEmitterData(hash, 0, NULL)`.

**AcidEmitter's deleting destructor** (0x00124e20, and a twin at
0x0012a3f8) counts NumAcidEmitters down. With bit 0 of the flags, it
gives the slot back to the emitters' pool (bFree(pool, p), 0x00257ca0).
Deleting an emitter that was never counted, one from a file, still
counts down.

## The auto emitters

**AddAutoEmitter** (0x001274a0):
1. If the emitter's RandomSeed (+36) is 0, step AcidRandomSeed by
   xorshift, `x ^= x << 17; x ^= x >> 13; x ^= x << 5`. The seed becomes
   `cvt.w.s(((float)(int)(x & 0x7fffffff) * 2^-31) * 2^31)`. The float
   can round up to 2^31, which saturates to 0x7fffffff.
2. Then by the data and State:
   - No data, or DISABLED: State becomes DISABLED, and the emitter goes
     on the tail.
   - OFF or ON (an unsigned test, State < 2): the cycle and its variance
     come from the data, OnCycle and OnCycleVariance for ON, OffCycle and
     OffCycleVariance for OFF.
     - If the cycle is not zero (`c.eq.s`, so -0 counts as zero):
       `w = variance * cycle`; xorshift the emitter's own seed;
       `cycle = (cycle - w) + unit(seed) * w`, where unit is the same
       fraction as in step 1.
     - The emitter goes on the **head**, with RemainingCycleTime the
       cycle and EmissionCountdown 0.
   - LIBRARY: on the tail.
   - Any other State: DISABLED, on the tail.
3. NumAutoEmitters (+80) goes up in every case.

So a list holds the emitters that cycle at its head and the templates
and the disabled at its tail.

**RemoveAutoEmitter** (0x00127688) unlinks the emitter and counts
NumAutoEmitters down. It leaves the emitter's links.

**KillAllActiveEffects** (0x001276a8) takes each active group off the
list from its head and runs its deleting destructor with flags 3.
**AcidActiveGroup's deleting destructor** (0x0012a258) sets Emitter and
EmitterData to NULL, and gives each particle back to the particles'
pool, from the head. Then, with bit 0 of the flags, it gives the group
to the groups' pool.

TweakerCheck (0x00127490) and RenderDebug (0x00127498) are empty.

## On the device

- `sinit_run` calls `acid_static_init` as entry 9 (`sinit_check`: 24
  calls, 0 problems).
- main.c calls `afx_init` after the display's init, as
  InitializeEverything does, and sets four seams:
  - `gAfxUpdateTexturesFn` (bchunkload.h), which PostLoadFixup calls;
  - `gAfxGetEmittersFn` and `gAcidEmitterDeleteFn` (carrenderinfo.h),
    with which each CarRenderInfo takes its emitter lists and deletes
    them;
  - `gKillAllActiveEffectsFn` (racecoord.h), WorldEffects' KillAll.
- LoaderTable slot 6 is `loader_acid_fx` and `unloader_acid_fx`
  (bchunkload.c), so every track's packs load. GLOBALB is loaded by hand
  in `loadGlobalCarInfo`, which now takes its two packs too: the car
  data log says 8 chunks, where it said 6.
- On Azahar the car select run passes with 0 unmapped accesses. A race
  on TRACKB12 runs as before (539 frames in 19 s), with 0 unmapped
  accesses and an empty `nfshp2_stderr.txt`.

## The checker

`tools/afx_check.py` runs the static constructor, afxInit, afxClose,
both loaders, afxUpdateTextures, every lookup and copy, both
SetEmitterData, the system's constructor, AddAutoEmitter,
RemoveAutoEmitter, KillAllActiveEffects and the three deleting
destructors on the retail image. bStringHash, bStrNCpy, bMemSet and the
list code under them run as shipped.

The stubs are the same on both sides:
- **The slot pools** are fixed arenas that give their lowest free slot.
  A slot is zeroed when the pool's flags have ZERO_ALLOCATED_MEMORY and
  filled with 0xa5 when not. Each call prints a line.
- **GetTextureInfo** answers by a rule on the hash, or as a script sets
  it: NULL, a texture of that name, or one whose NameHash has its low
  bit flipped.
- **bFree(void *)** (0x00257850) would stop the model. Nothing reaches
  it.

The records are the disc's: GLOBALB's and each track's packs, from
extracted-retail. Each side lays them out in its own struct, with the
links and any pointer that isn't zero set to a pattern ("pat"). After
each op both sides print the counts, the seed and every list's length.
The dumps print every list in full: each data and emitter, the bytes
after a name's terminator when any aren't zero (" +hex"), and " !p" if a
list's prev doesn't reach back to its last node.

There are 16 scenarios:
- the boot over GLOBALB and TRACKB12, with every lookup, every group the
  cars and the frontend ask for, the copies, the unloads and the close;
- all 30 tracks, six to a scenario, over GLOBALB;
- AddAutoEmitter in every state, with and without a data, over cycles of
  0, -0, NaN, the infinities and denormals and over the variances. Its
  seeds are made by running the xorshift backwards, so that the fraction
  rounds to 1, to 0 and to just under;
- every type and version the loaders see, counts of 0, and the header at
  each of the 16 offsets a chunk can sit at;
- the copies with the pool failing, 63-byte names, no data and every
  delete flag;
- groups made as TriggerEmitter makes them, killed, deleted by hand and
  left for the close;
- every answer GetTextureInfo gives;
- both SetEmitterData, the constructors run again, and a track's emitters
  loaded before its datas;
- the edges: lookups with both hashes 0 and a data with no group, pools
  that don't zero, and names with bytes after the terminator;
- three fuzz runs: 400 ops over TRACKB12, 1200 over TRACKB24 and 2500
  over TRACKB61. The fuzz knows what each op returned, so it never adds
  an emitter that is already on a list and never names one it deleted.

All 16 scenarios agree: 9295 ops, 35221 lines, 0 differ. The mutation
pass (tools/mutpar.py) catches 172 of 175 mutations. The other three
can't change what either side does:
- `cp-name-64`: bStrNCpy's 64th byte goes to Name[63], which the next
  line clears.
- `cp-no-term`: the clear before it has zeroed Name[63], and bStrNCpy's
  63 bytes stop short of it.
- `aa-disabled`: a DISABLED emitter with a data reaches the last branch,
  which sets it DISABLED again and adds it to the tail.

`tools/loadertable_check.py` runs slot 6 with the other loaders: the
demo image's 178 ops and the retail image's 37375, 0 differ on both.

## Still open

- **SC-3b:** TriggerEmitter (0x00127700, changed from the demo),
  DoTimeStep (0x00128718) and UpdateInterestPoints (0x001286a0).
- **SC-3c:** RenderEffects (0x00128da0) and its draw on the device.
- **SC-3d:** the car select's nebula, 20 emitters of XE_SelectCarNebula
  with UpdateNebula and SetEmitterState (0x0016c3b0).
- GLOBALB has a group CARFX_BREAK_LICENSE_PLATE_REAR, but carrenderinfo.c's
  kCarFxNames has CARFX_BREAK_LICENSE_PLATE_RIGHT. If retail's string
  says RIGHT, that car effect finds no emitters. Check it in SC-3d.
