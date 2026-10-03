# Collision -- the record of two bodies in contact

    retail 0x0021e5c8 .. 0x0021ec54    Collision.obj, 1676 bytes
    retail 0x0021e760                  DoSnapshot (not ported)
    retail 0x0014e3e8, 0x0014e440      World::GetDistanceToClosestPlayer
    gp-15880 (0x00331ae8)              CollisionSlotPool
    gp-15884 (0x00331ae4)              CollisionLifetime, 0.3 (3e99999a)

    the demo's 0x0020b238 .. 0x0020b87c, 1604 bytes; its addresses below
    are in brackets where retail's moved

A Collision exists while two bodies are in contact, and for a short while
after. A CollisionBodyWitness makes one on its bodies' first touch
(BeginCollision, retail 0x001d63b8). CollisionImpulse then hands it every impulse
it applies (AddImpulse). From the start it sits on the current World's
CollisionList, so the sound, the damage and the AI can walk every collision
in the world. Each world step, World::DoTimestepCollisions asks every
collision whether it is still live (Update). It ends the ones that are not
(End), which goes through the witness and destroys them.

The port is `3DS Files/source/collision.{c,h}`, and the two World methods
are in `world.c`. `tools/collision_check.py` cross-checks them against
`tools/src/collision_test.c`, with the image running in mipsemu as the
oracle. Everything is ported except DoSnapshot. That one is the replay's,
and waits on ReplaySnapshot like every other DoSnapshot.

The port follows retail (step 8m-4b). Retail made the record 112 bytes:
its last sixteen hold the direction of the last impulse AddImpulse took
near a player, which Player::UpdateScoring reads for the bonus scores
(`docs/formats/hud-score.md`). InitCollision, the constructor and
AddImpulse changed for it, and GetTerrainType for the 144-byte
TerrainTypeInfo. The rest is the demo's code, moved.

## The record

The demo's stab is `Collision:Tt254=s96!1,020,245`: one base,
bTNode<Collision>, and no virtuals. Retail has no stabs; its record is the
demo's with sixteen bytes on the end.

| Offset | Field | Type | What it holds |
|-------:|-------|------|---------------|
| 0 | next, prev | bTNode | the World's CollisionList |
| 8 | CollisionTime | Timer | WorldTimer at construction |
| 12 | LastContactTime | Timer | WorldTimer at the last impulse |
| 16 | InitialContactPoint | bVector3 | the constructor's point |
| 32 | CurrentContactPoint | bVector3 | the last impulse's point |
| 48 | CurrentScrapeSpeed | float | the last impulse's slide speed |
| 52 | -- | 12 bytes | the quadword round-up |
| 64 | TotalImpulse | bVector3 | every impulse, summed in all four lanes |
| 80 | TotalImpulseMagnitude | float | every impulse's length, summed |
| 84 | pWitness | CollisionBodyWitness* | the witness that made it |
| 88 | Sample | CollisionSample* | the sound's voice, if it gave one |
| 92 | Scrape | CollisionSample* | the scrape's voice; the sound sets it |
| 96 | ImpulseDirection | bVector3 | retail's: the last near impulse over its length |

Only AddImpulse writes CurrentContactPoint and CurrentScrapeSpeed. Sample is
written only when the constructor asks the sound for one. The slots come
from CollisionSlotPool with the default flags, so bOMalloc zeroes each one
and every field the constructor skips reads 0.

The stab also lists inline getters, all of them one field wide:
GetCollisionTime, GetInitialContactPoint, GetCurrentContactPoint,
GetTotalImpulse, GetTotalImpulseMagnitude, GetScrapeSpeed, GetSound,
GetScrape, SetSound and SetScrape. `collision.h` has them as static
inlines. IsStillActive, GetAge and GetTimeSinceLastContact are inline too,
but no caller the port has reached expands them, so they wait for the
first one that does.

## The pool

- **InitCollision** (0x0021e5c8) runs
  `bNewSlotPool(112, 32, "CollisionSlotPool", 16)`. The demo's asked for 96.
- **CloseCollision** (0x0021e5f8) deletes the pool and zeroes the pointer.

The callers are EndGameFlowLoadingTrackSpecific and
BeginGameFlowUnloadingTrackSpecific. `new Collision` is written out at its
one site, BeginCollision: `bOMalloc(CollisionSlotPool)`, then the
constructor on the result, with no NULL test. The pool keeps the default
flags, so a full pool grows instead of failing. `operator delete`
(0x0021ec48) is `bFree(CollisionSlotPool, p)`.

## The constructor, 0x0021e620 (0x0020b290)

    list = &pCurrentWorld->CollisionList
    TotalImpulse.xyz = 0                      the fourth lane is not written
    AddTail(list, this)
    pWitness = w
    CollisionTime = LastContactTime = 0
    TotalImpulseMagnitude = 0
    Scrape = NULL
    if pt:
        InitialContactPoint = *pt             all four lanes
        if World::GetDistanceToClosestPlayer(pt) < 100:
            Sample = collision_sound::CreateSample(this)
    else:
        InitialContactPoint.xyz = 0           the fourth lane is not written
    CollisionTime = LastContactTime = WorldTimer
    ImpulseDirection.xyz = 0                  retail's; the fourth lane is not written

The distance is in three dimensions. Exactly 100 is not near. The sound
gets the collision already linked and stamped with its point, but not yet
with its time. The collision keeps whatever CreateSample returns, including
NULL when the sound has no voice free.

## The destructor, 0x0021e6f8 (0x0020b358)

    unlink from the list
    collision_sound::ReleaseSample(this)
    ~bTNode(0)                                bNode's destructor; nothing at 0
    if flags & 1: operator delete(this)

The witness's EndCollision calls it with 3 (`_$_9Collision(c, 3)`). The
witness's destructor goes through EndCollision too, when it still has a
collision.

## AddImpulse(at, impulse, scrape), 0x0021e7f0 (0x0020b450)

    TotalImpulse += *impulse                  vadd.xyzw: all four lanes
    len = sqrt((x*x + y*y) + z*z) of impulse  vmul.xyz, vaddy.x, vaddz.x
    TotalImpulseMagnitude += len
    LastContactTime = WorldTimer
    CurrentContactPoint = *at
    CurrentScrapeSpeed = scrape
    if World::GetDistanceToClosestPlayer((bVector2 *)at) < 50:
        tt = GetTerrainType()
        info = &TerrainTypeInfoTable[tt]
        if info.CollisionScrapeMinSpeed < scrape:
            s = (scrape - min) / (max - min), clamped to [0, 1]
            v1 = pBody1->GetVelocity(); v2 = pBody1->GetVelocity()
            v = |v1| < |v1| ? v2 : v1                    always v1
            TerrainEffectEmitters::TriggerEffect(6, tt, s, at, v)
            collision_sound::PlayScrape(this)
        if info.CollisionImpactMinForce < len:
            s = (len - min) / (max - min), clamped to [0, 1]
            TriggerEffect(5, tt, s, at, &(0, 0, 0))     a stack vector
        ImpulseDirection = *impulse / |impulse|          retail's

The effects test takes the bVector2 overload, straight on `at`, so it
measures on the ground plane. The height does not count, and exactly 50 is
not near.

The scrape looks as if it hands the particles the faster of the two bodies'
velocities. But both calls are on body 1, and both lengths come from the
first answer. The test is therefore `l < l`, which never holds, and the
scrape always gets body 1's velocity. Both calls still happen, so the port
makes both.

ROAD's (1) and terrain 31's scrape range is 50 to 50, so the scrape's divide
can be x / 0. On the EE that gives FLT_MAX, and the port uses `ee_div` for
it. The numerator is past the minimum and so above 0, and every terrain's
range is at least 0 wide, so the quotient is never negative and the clamp
brings x / 0 to 1 whichever divide does it.

The impact's zero vector is three stores to the stack. Its fourth lane is
whatever the stack held. The port's is zero.

Retail's direction is `vrsqrt Q,vf00w,vf02x ; vaddq.x ; vmulx.xyzw` on the
impulse, which it loads again after the effects: all four lanes over the
length of the first three. The VU's divide of a zero length is the EE's,
FLT_MAX, so a zero impulse makes zeroes (and a fourth lane of 0xa5a5a5a5
grows to infinity). The port is `0.0f + ee_div(1.0f, sqrtf(dot))`, as
contact.c's normalise is. Far from every player the direction is left as
it was, so it is the last near impulse's, or zero.

## Update(dt), 0x0021ea40 (0x0020b668)

    return (float)(int)(WorldTimer - LastContactTime) * 0.00025 < CollisionLifetime

The subtraction is unsigned, and the conversion treats the result as
signed. So a last contact "after" now gives a negative age, which counts as
live. 0.00025 is gp-27200 (3983126f), a second over 4000. At 1200 ticks,
1200 × 0.00025 rounds to 0.3's own float, so it is not below the lifetime,
and the collision ends. The argument, the world step, is never read.

## End, GetTerrainType and the questions

- **End** (0x0021ea80) is `pWitness->EndCollision()`, which clears the
  witness's pointer and destroys the collision.
- **GetTerrainType** (0x0021ea88) calls GetTerrainType (vtable slot 144) on
  body 1 and then body 2. It returns t1 when
  `Table[t2].CollisionPriority <= Table[t1].CollisionPriority`, so the
  first body wins a tie. Retail's indexes the 144-byte TerrainTypeInfo.
- **IsTwoCarCollision** (0x0021eb20): both bodies' Type (byte 12, signed)
  is 0.
- **GetCollidingCars(car1, car2)** (0x0021eb48): each body's `pCar` (word
  256) if its Type is 0, else NULL. Both outs are cleared first.
- **IsPlayerInvolved** (0x0021eb90): true if car 1 has a Player (word 24),
  else car 2's Player if there is a car 2, else false.
- **IsSmokeableInvolved** (0x0021ebd8): either body's Type is 1.

## World::GetDistanceToClosestPlayer

World keeps each player's car position in `PlayerPositions` (336 and 352).
DoTimestep writes them every step, with 9999999 in the first three lanes
for a player who has no car.

- **The bVector3 overload** (0x0014e440) works on the VU: for each player,
  `vsub.xyzw`, `vmul.xyz`, `vaddy.x`, `vaddz.x`, then `sqrt.s`. The result
  is `min.s(d0, d1)`.
- **The bVector2 overload** (0x0014e3e8) is scalar: for each player,
  `sqrt.s(dx*dx + dy*dy)`, then `min.s(d0, d1)`.

`min.s` is `ft < fs ? ft : fs`. A distance is never NaN or -0, so the
operand order does not matter here.

## The seams

The image calls these unconditionally. In the port, each is a pointer, and
a NULL one skips the call:

| Port pointer | Image function | Task |
|--------------|----------------|------|
| `gCollisionSoundCreateSampleFn` | collision_sound::CreateSample, 0x001e5278 | 29 |
| `gCollisionSoundReleaseSampleFn` | collision_sound::ReleaseSample, 0x001e53b0 | 29 |
| `gCollisionSoundPlayScrapeFn` | collision_sound::PlayScrape, 0x001e57d0 | 29 |
| `gTerrainEffectTriggerFn` | TerrainEffectEmitters::TriggerEffect, 0x00222438 | 30 |

A skipped CreateSample answers NULL, which is what the sound itself answers
when it has no voice free. `pTerrainEffectEmitters` (gp-15816) is passed
through as it stands.

In the other direction, collision.c fills three of `collisionbody.h`'s
seams: `gCollisionNewFn` (collision_new), `gCollisionAddImpulseFn` and
`gCollisionDestroyFn`. `main.c` sets all three.

## The cross-check

`collision_check.py` runs on the retail image (it ran on the demo's
until step 8m-4b, and moved wholly when the port took retail's record).
It runs the image's own InitCollision, bNewSlotPool,
bOMalloc and bFree against `bslotpool.c`. Each side's pool gets a block
the script owns, so a label (Cn, slot n) says where a collision is, and the
order in which a freed slot comes back is checked too. Two more collisions,
R0 and R1, are built outside the pool on memory filled with 0xa5, which
shows every field the constructor writes and every field it skips. The
stand-in bodies share one recording vtable, whose two slots take `this`
eight bytes in. The sound, the particles and the witness's EndCollision are
stubs that log.

The script covers:

- the distances at their edges and at random;
- the 100 and 50 boundaries;
- a sample given, withheld, and not asked for;
- destroy with each flag;
- slot reuse and a full pool;
- scrape and impact scales across terrains 0, 1, 6, 15, 17, 31 and 32,
  including the 50-to-50 divide;
- priority ties;
- every pairing of body types, cars and players;
- update ages across the lifetime, negative ones, and ones that wrap;
- close and re-init;
- a random walk of 1500 steps;
- the direction: zero, unit, 0xa5a5a5a5 and infinite lanes, near and far.

15 scenarios, 3587 operations, 7506 lines, 0 differ. The mutation pass
makes 144 mutations: 134 caught, 10 equivalent by construction, 0
unexplained. The thirteen on the direction are all caught.
