# CollisionBody

`CollisionBody.obj` (0x001ca170 .. 0x001cebb8). Task 27's eleventh slice is
its first part, the bodies that do not move. The twelfth is its second,
DynamicCollisionBody, and the thirteenth its third, CarCollisionBody. The
fourteenth and fifteenth are the rest: the witness's contact tests and
Contact. It builds on [VClip](vclip.md) and the [polyhedra](polyhedra.md). A
collision body is anything VClip can be asked about: a car, a smokeable, or
a track polygon near a car. A witness is a VCWitness for one pair of bodies.
A contact is a pair a witness has found inside each other, backed up to
where they touched.

Ported to `3DS Files/source/collisionbody.{c,h}`. CarCollisionBody is in
`carcollisionbody.c`, because it needs car.h and the movers, and the
contacts are in `contact.c`. Cross-checked by `tools/collisionbody_check.py`
against `tools/src/collisionbody_test.c`.

| Class | Size | What it is | Slice |
|---|---|---|---|
| `NumberAllocator` | 12 | a bit per number, and the lowest clear one | A |
| `CollisionBody` | 84 | abstract: list node, polyhedron, box, ID, counts, name | A |
| `StaticCollisionBody` | 84 | a body that does not move | A |
| `TrackPolygonCollisionBody` | 1080 | a TrackPolygon as a WaferPolyhedron | A |
| `CollisionBodyWitness` | 112 | a VCWitness for two bodies | A; the contact tests in D |
| `DynamicCollisionBody` | 256 | a body that moves | B |
| `CarCollisionBody` | 336 | a car's | C |
| `Contact` | 64 | a pair found touching, to be resolved | E |

Slice A covers:

- the NumberAllocator;
- `InitCollisionBody` and `CloseCollisionBody`;
- the stats;
- the base class, the static bodies and the track-polygon bodies;
- the witness's constructor, destructor and bookkeeping;
- the three virtual tables;
- the static initialiser and destructor.

Slice B is all of DynamicCollisionBody but two methods:

- `GetDistanceAndSpeed` came earlier, with Car's sixth slice, and is in
  `carcollisionbody.c`;
- `FindWaferNormal` (0x001ca460) is the contact tests', and waits for
  slice D.

Slice C is all of CarCollisionBody: 0x001cd750 .. 0x001cddc0, the inline
methods at 0x001ce6c0 .., and the table at 0x0029bc08. Car's fourth slice
had already brought two of its methods, SetupPhysicsPointers and
SetToPhysicsMode (see [Car's modes](car-modes.md)). Slice C also brought
RaceCoordinator's `pRaceCoordinator`, `GetCurrentState` and
`IsReplayDemoMode` (0x00134b00), in `race.c`.

Slices D and E were done together, because D's TestForContact builds a
Contact and sorts it with E's code:

- D is the witness's GetCollision, BeginCollision and TestForContact, and
  `FindWaferNormal`;
- E is all of Contact. That is 0x001ca170 .. 0x001cb4ec, the stretch before
  the NumberAllocator, and the inline destructor and delete that World.obj
  emitted (0x0014c188, 0x0014c330);
- `bList::AddSorted` (0x00238290), which TestForContact calls, came with
  them.

0x001cb4f0 .. 0x001cb57c holds more copies of the inline destructor and
delete, and three thunks, none of them named. The port has one of each.

The DoSnapshot and SnapshotEverything methods belong to the replay
(TASKS 72): the bodies' DoSnapshots, Dynamic's (0x001cc950) and the
car's (0x001cd950) among them, are in `collisionbody.c` and
`carsnap.c` since 72b, and the three SnapshotEverythings (Track
polygon bodies', 0x001d8980; every body's, 0x001d6e70; the witnesses',
0x001d6208) in `bodysnap.c` since 72d-2. See
[replay.md](replay.md).

| Address | Function |
|---|---|
| 0x001cb580 | `NumberAllocator::SetMaxNumbers` |
| 0x001cb618 / 0x001cb658 | `NumberAllocator::AllocateNumber()` / `(i)` |
| 0x001cb718 | `NumberAllocator::FreeNumber` |
| 0x001ce590 | `~NumberAllocator` |
| 0x001cb760 / 0x001cb880 | `InitCollisionBody` / `CloseCollisionBody` |
| 0x001cb8f0 / 0x001cba18 | `CollisionBodyWitness` / `~CollisionBodyWitness` |
| 0x001cbea8 | `CollisionBodyWitness::EndCollision` |
| 0x001cbf18 | `CollisionBodyWitness::HasExpired` |
| 0x001cc010 | `IsYawControlInducingCollisionBody` |
| 0x001cc248 | `CollisionBodyWitness::EliminateAllWitnesses` |
| 0x001cc298 | `CollisionBodyWitness::DoesWitnessExist` |
| 0x001cc2e8 / 0x001cc3b0 | `CollisionBody` / `~CollisionBody` |
| 0x001cc530 | `CollisionBodyFlipFunction` |
| 0x001cc578 | `CollisionBody::UpdateMaxCollisionBodyWidth` |
| 0x001cc630 | `CollisionBody::SetBBoxMinMax` |
| 0x001cc758 | `CollisionBody::GetNextCollisionBodyID` |
| 0x001cc768 | `CollisionBody::SetDebugName` |
| 0x001cc820 | `CollisionBody::FindCollisionBody` |
| 0x001cc838 | `CollisionBody::GetCollision` |
| 0x001cdf48 / 0x001cdfa8 | `StaticCollisionBody` / `~StaticCollisionBody` |
| 0x001ce020 / 0x001ce138 | `TrackPolygonCollisionBody` / `~TrackPolygonCollisionBody` |
| 0x001ce3d0 / 0x001ce3e0 | `TrackPolygonCollisionBody::GetPosition` / `GetTerrainType` |
| 0x001ce8e8 .. 0x001cea30 | StaticCollisionBody's twenty-two methods |
| 0x001cea50 .. 0x001cebb0 | the base's inline accessors and the two box tests |
| 0x001ce548 / 0x001ce520 | `_GLOBAL_$I$` / `_GLOBAL_$D$TheCollisionStats` |
| 0x001cc8a8 / 0x001cc928 | `DynamicCollisionBody` / `~DynamicCollisionBody` |
| 0x001cca58 | `DynamicCollisionBody::BuildBoundingVolumes` |
| 0x001ccbf0 | `DynamicCollisionBody::UpdatePosition` |
| 0x001ccc68 | `DynamicCollisionBody::BeginMove` |
| 0x001ccd08 / 0x001cceb0 | `DynamicCollisionBody::Interpolate` / `InterpolateVelocity` |
| 0x001ccf60 | `DynamicCollisionBody::Backup` |
| 0x001cd010 | `DynamicCollisionBody::RecomputeAuxilliaries` |
| 0x001cd040 / 0x001cd060 | `DynamicCollisionBody::GetCurrentVelocities` / `GetTestImpulseVelocities` |
| 0x001cd078 | `DynamicCollisionBody::GetLocalCollisionBodies` |
| 0x001cd130 | `DynamicCollisionBody::MaybeCreateWitnesses` |
| 0x001cd3a0 | `DynamicCollisionBody::CreateTrackPolygonCollisionBodies` |
| 0x001cd5f0 | `DynamicCollisionBody::TrackPolygonCheck` |
| 0x001cd710 | `DynamicCollisionBody::ChangeInEnergy` |
| 0x001ce820 .. 0x001ce870 | Dynamic's seven inline methods, GetBoundingBox to SetPosition |
| 0x001cd750 / 0x001cd898 | `CarCollisionBody` / `~CarCollisionBody` |
| 0x001cda20 / 0x001cda80 | `CarCollisionBody::SetupPhysicsPointers` / `SetToPhysicsMode` |
| 0x001cdad0 | `CarCollisionBody::Move` |
| 0x001cdb50 | `CarCollisionBody::AreCollisionsEnabled` |
| 0x001cdb78 / 0x001cdba0 | `CarCollisionBody::GetMassInverse` / `GetInertiaTensorInverse` |
| 0x001cdbe8 | `CarCollisionBody::ApplyImpulse` |
| 0x001cdca0 / 0x001cddc0 | `CarCollisionBody::AddDamage` / `AnimateCollisionReaction` |
| 0x001ce6c0 .. 0x001ce6f0 | the car's inline accessors: the two Timers and GetCar |
| 0x001ce6f8 .. 0x001ce7d0 | its small methods, GetFriction to GetPosition |
| 0x001ce7f0 / 0x001ce800 | its `operator delete` / `new`, on the pool |
| 0x001ca170 / 0x001ca1a0 | `InitContact` / `CloseContact` |
| 0x001ca1c8 | `Contact::RemoveContacts` |
| 0x001ca240 | `Contact::ContactTimeSorting` |
| 0x001ca268 | `Contact` |
| 0x0014c188 / 0x0014c330 | `~Contact` / its `operator delete`, inline, in World.obj |
| 0x001ca2a8 | `Contact::FindContactTime` |
| 0x001ca460 | `FindWaferNormal` |
| 0x001ca538 | `Contact::Crowbar` |
| 0x001ca760 | `Contact::Resolve` |
| 0x001ca968 | `Contact::FindContactPointAndNormal` |
| 0x001cabb0 | `Contact::FindPlanarCollisionContactPoint` |
| 0x001cad30 / 0x001cad60 | `GetContactPointVelocity` / `DenominatorTerm` |
| 0x001cade0 | `Contact::CollisionImpulse` |
| 0x001cbde0 / 0x001cbe18 | `CollisionBodyWitness::GetCollision` / `BeginCollision` |
| 0x001cc058 | `CollisionBodyWitness::TestForContact` |
| 0x00238290 | `bList::AddSorted` |

## The records

**CollisionBody** (stabs `t4605`, s84):

| Offset | Field | Notes |
|---|---|---|
| 0 | `bTNode<CollisionBody>` | next, prev |
| 8 | `pPoly` | set by the derived class |
| 12 | `Type` | `CollisionBodyType`: car 0, smokeable 1, virgin smokeable 2, track polygon 3 |
| 13 | `Dynamic` | set by the derived class |
| 14 | `ID` | read with `lh`; negative for a body with no number |
| 16 | `NumWitnesses` | |
| 17 | `CollisionsDisabled` | a count, not a flag |
| 18 | `NumCollisions` | |
| 19 | `ActiveCollisionDetection` | |
| 20 | `BBoxMin` | a bVector2 |
| 28 | `BBoxMax` | a bVector2 |
| 36 | `DebugName[40]` | |
| 76 | `pCaffeineObj` | |
| 80 | vptr | |

The stabs give the byte fields no sign. The code reads every one with `lb`,
so the port makes them signed.

**TrackPolygonCollisionBody** (`t268`, s1080) adds `pTP` at 84 and its
WaferPolyhedron at 88. StaticCollisionBody adds nothing.

**DynamicCollisionBody** (s256):

| Offset | Field | Notes |
|---|---|---|
| 0 | `CollisionBody` | |
| 84 | `PhysicsMode` | |
| 88 | `pTC` | the TopologyCoordinate whose polygons it is tested against |
| 92 | `pSystem` | a PhysicsSystem |
| 96 | `pBody` | a RigidBody |
| 100 | `BackupTime` | |
| 104 | | eight bytes: the matrix's quadword alignment |
| 112 | `BackupRotation` | a bMatrix4 |
| 176 / 192 | `BackupPosition` / `BackupVelocity` | bVector3s, pad and all |
| 208 / 212 | `CylinderBaseHeight` / `CylinderTopHeight` | below and above the origin |
| 216 | `CylinderRadius` | |
| 220 | `Radius` | the bounding sphere's |
| 224 / 240 | `LocalBBMin` / `LocalBBMax` | bVector3s |

The port's bMatrix4 is only float-aligned, so the eight bytes at 104 are
written into the struct.

**CarCollisionBody** (s336):

| Offset | Field | Notes |
|---|---|---|
| 0 | `DynamicCollisionBody` | |
| 256 | `pCar` | |
| 260 | `LastCollisionTime` | retail's, and the name is ours: a Timer, stamped at each contact |
| 264 | `LastPenetrationTime` | a Timer |
| 268 | `LastYawControlCollisionTime` | a Timer |
| 272 | `ScaledInverseInertiaTensor` | a bMatrix4, what GetInertiaTensorInverse answers |

This is retail's order, which the port has had since TASKS 73. The demo
has LastPenetrationTime at 260, LastYawControlCollisionTime at 264 and four
bytes of the matrix's quadword alignment at 268. Retail put a third stamp
first, and all of these agree on it:

- its TestForContact (0x001d65f8);
- the six accessors (0x001d8e08 .. 0x001d8e48), with a pair for the new
  stamp that nothing calls;
- DoSnapshot (0x001d8058), which moves the three in order;
- Car::GetLastPenetrationTime (0x00135190), which loads 264;
- GetPostCollisionYawControlBoost (0x00135eb8), which loads 268.

The constructor stamps all three with `WorldTimer`. Player::ChooseToDisplayReset
(0x00181f68, which the demo lacks) reads the new one: a car is in trouble
only within 3 s of its last contact. The port had been reading
LastPenetrationTime there, which only a blinking car's contact stamps.

**CollisionBodyWitness** (`t1522`, s112) has two bases: the bTNode at 0 and
the VCWitness at 16. The eight bytes between them are the VCWitness's
quadword alignment. After the VCWitness come `pBody1` at 96, `pBody2` at
100 and `pCollision` at 104.

Retail's witness has `pCollision` at 108, and nothing reads or writes 104:
not the constructor, the destructor, DoSnapshot, SnapshotEverything,
GetCollision, BeginCollision, EndCollision, HasExpired or the Collision's
constructor. Those differ from the demo's only in that offset, so the port
keeps the demo's layout.

**Contact** (`t2017`, s64):

| Offset | Field | Notes |
|---|---|---|
| 0 | `bTNode<Contact>` | next, prev: World's list of contacts |
| 8 | `BackupTime` | how far back the pair first touched |
| 12 / 16 | `pBody1` / `pBody2` | |
| 20 | `pWitness` | the witness that found them |
| 24 | | eight bytes: the vector's quadword alignment |
| 32 | `CrowbarVector` | a bVector3: the push that parts them |
| 48 | `LoopFound` | `WorldLoopCounter` when it was made |
| 52 | | twelve bytes: the round-up to sixteen |

**CollisionStats** (`TheCollisionStats`, 0x00311ca0, s72) holds nine counts
and then the highest each has reached:

- witnesses, collisions and bodies;
- static, dynamic, track-polygon and car bodies;
- virgin smokeables and smokeables.

Every constructor bumps its class's count and, if the count passed it, its
highest. Every destructor drops the count. Nothing reads them.

On a 64-bit host the pointers widen. The header's asserts allow for that:
`CB_AT(T, f, n, k)` is offset n on the console plus k pointers' worth of
slack.

## The globals

| Address | Name | What it is |
|---|---|---|
| 0x00311cf0 | `ZeroVector` | the static bodies' velocity and position |
| 0x00311d00 | `IdentityMatrix` | the static bodies' rotation |
| 0x00311d40 | `ZeroMatrix` | the static bodies' inverse inertia |
| gp-18400 | `pCollisionBodyTable` | the body with each ID |
| gp-18392 | `CollisionBodyList` | every body, sorted on BBoxMax.x |
| gp-18384 | `MaxCollisionBodyWidthX` | the widest box, kept up as boxes change |
| gp-18356 | `pCollisionBodyNumberAllocator` | the allocator of IDs |
| gp-18352 | `CollisionBodyWitnessList` | every witness, oldest first |
| gp-18316 | `pWitnessExistanceBitField` | which pairs have a witness |
| gp-18312 | `TrackPolygonCollisionBodySlotPool` | made by Init |
| gp-18308 | `CarCollisionBodySlotPool` | made by Init |
| gp-18304 | `CollisionBodyWitnessSlotPool` | made by Init |
| gp-23156 | `BoringAIForCameraTuningOn` | an AI tuning switch: no car collides while it is set |
| gp-16016 | `WilliamsAITuningMode` | the other |
| gp-28760 .. gp-28712 | | CarCollisionBody's floats: the box, 1/1.3 twice, 0.4 twice, 0.03 (retail's 0.013), 0.3 and 0.1 |
| 0x003243d4 | `ContactSlotPool` | made by InitContact |
| 0x003243d8 | `ContactThreshold` | 0.05: bodies parted by less are touching |
| 0x003243e0 | `WaferBias` | 0.5; retail's (gp-17844) is 0 |
| 0x003243ec | `MinimumContactImpulseFactor` | 0.3: the impulse's floor |
| 0x003243f0 | `MinimumContactImpulseSpeed` | 0.1: the closing speed that earns the whole floor |
| 0x003243f8 | `MaxFrictionScrapeSpeed` | 1.0: a slower slide fades the friction |
| gp-28816 .. gp-28780 | | Contact's floats: 0.05, 1e-6, -57575, 0.3 twice, 0.1, -0.025, -0.4 and 4/7 twice |

(gp is 0x00328bf0.) Nothing on the disc writes either AI switch. They are
defined in `carcollisionbody.c` until the AI, which reads them too, is
ported.

`CollisionBodyList` is an 8-byte node, and the list's code reaches it as
a CollisionBody, the list's end, as the image does. Under GCC's strict
aliasing a write through a body could not touch it, and a push kept a
head it had read before; the Makefile builds with `-fno-strict-aliasing`
(TASKS 37f-2, `smokeable.md`).

Nothing writes Contact's five tuning globals either. Between them are
`ContactDebug` (0), `Restitution` (0.1), `TestImpulse` (1.0) and
`ContactFrictionCoefficient` (0.3), which nothing reads. CollisionImpulse's
0.3 and 0.1 are literals of their own, not these.

Both list heads are zero on the disc. They do not point at themselves until
the static initialiser runs.

## NumberAllocator

- **SetMaxNumbers(n)** frees the old field, but only when `MaxNumbers` is
  not zero. It then takes `n >> 3` bytes, zeroed, with every number free.
  n = 0 leaves the allocator empty.
- **AllocateNumber()** answers the lowest free number and takes it. It
  answers -1 when the lowest free is not below `MaxNumbers`.
- **AllocateNumber(i)** sets bit i. When i was the lowest free number, the
  lowest is searched for again from i + 1 up, and it becomes `MaxNumbers`
  when none is free. It does not check whether i was already taken.
- **FreeNumber(i)** clears bit i. i becomes the lowest free number if it is
  lower. It does not check the range either.
- **~NumberAllocator** runs SetMaxNumbers(0), and bFrees the allocator when
  flags & 1.

**The field is short.** `n >> 3` rounds down, so when n is not a multiple
of eight the top numbers live in a byte past the request. For the game's
206 that is 25 bytes, and numbers 200 to 205 are in a twenty-sixth. For 7
it is zero bytes. On the console the byte lands in bMalloc's round-up to
sixteen. The port asks for one byte more and zeroes it
(`COLLISIONBODY_SHORT_SLACK`).

## Init and Close

**InitCollisionBody** (0x001cb760) makes, in order:

1. the car pool (336 × 14), the track-polygon pool (1080 × 160) and the
   witness pool (112 × 256);
2. the allocator, a 12-byte bMalloc, set up for 206 numbers;
3. the table, 824 bytes (206 pointers), zeroed;
4. `IdentityMatrix` with bIdentity, and `ZeroMatrix` zeroed;
5. the witness bit field, 5304 bytes, zeroed.

EndGameFlowLoadingTrackSpecific is its one caller.

**The bit field is short too.** 206 × 206 is 42436 bits, which is 5304 bytes
and a half. The pairs (205, 202) to (205, 205) are in a 5305th byte. The
port asks for that byte as well.

**CloseCollisionBody** (0x001cb880):

- deletes the three pools and leaves their pointers NULL;
- destroys the allocator with flags 3, if there is one;
- frees the table without testing it;
- frees the bit field if there is one.

It does not touch the lists or the bodies on them. A body still in a pool
makes the pool print its WARN_IF_NONEMPTY_DELETE line, and the list is left
pointing into the freed pool.

## CollisionBody

**The constructor** (0x001cc2e8) takes an ID and a type. It:

- sets the table pointer, the type and the ID;
- if the ID is not negative, takes that number from the allocator and
  points the table entry at the body. The number goes through `sll 16 ;
  sra 16`, so it is the halfword as stored;
- bumps the stats;
- empties the name;
- links the body at the head of the list;
- sets the box to -9999999 all four ways (gp-28776);
- zeroes `pCaffeineObj` and the four counts.

It leaves `pPoly` and `Dynamic` to the derived class.

A second body built on a taken ID takes the table entry over. Its
destructor then clears the entry and frees the number, although the first
body still holds it.

**The destructor** (0x001cc3b0):

1. resets the table pointer and drops the stats;
2. runs UpdateMaxCollisionBodyWidth(0) while the body is still listed;
3. unlinks the body;
4. if `NumWitnesses` is not zero, walks the witness list and destroys,
   with flags 3, every witness that has the body at either end;
5. if the ID is not negative, clears the table entry and frees the number;
6. bFrees the body when flags & 1.

**The list** is sorted on BBoxMax.x, smallest first. Ties go by ID, lowest
first. `CollisionBodyFlipFunction(a, b)` (0x001cc530) answers whether a
belongs after b:

- 1 when a's BBoxMax.x is the greater;
- 0 when b's is;
- otherwise `b.ID < a.ID`. A NaN falls through to the ID as well.

A new body goes in at the head with its seed box, so the bodies not yet
given a box sit together at the head, newest first, whatever their IDs.

**SetBBoxMinMax** (0x001cc630) runs UpdateMaxCollisionBodyWidth with the
new width `max.x - min.x`, then stores the minimum and the maximum. If
BBoxMax.x has not changed, it stops there. Otherwise it moves the body one
place at a time and looks again from the top after every move:

1. if the body before it should follow it, the body moves one place toward
   the head;
2. if not, and the body after it should lead it, the body moves one place
   toward the tail;
3. when neither applies, it stops.

**UpdateMaxCollisionBodyWidth(w)** (0x001cc578) compares w with the body's
current width, `cur = BBoxMax.x - BBoxMin.x`:

- **w == cur**: nothing.
- **cur < w and the widest < w**: w becomes the widest.
- **w < cur and cur == the widest**: the body was the widest and is
  narrowing. The widest becomes the largest width among **the other
  bodies**, starting from 0.
- **anything else**: nothing.

The body's new width is not counted, so the widest can end up below a live
body's width. A body alone on the list that narrows from 10 to 5 leaves the
widest at 0. The destructor's call with 0 relies on this skip: the body is
still listed at that point.

The rest of the base:

- **GetNextCollisionBodyID** (0x001cc758) reads the allocator's lowest free
  number with `lhu` and does not take it.
- **SetDebugName** (0x001cc768) copies forty bytes with bStrNCpy, which
  stops after the NUL and never pads, and forces the last byte to NUL.
- **FindCollisionBody(i)** answers table entry i.
- **GetCollision(i)** (0x001cc838) answers NULL unless i is below
  `NumCollisions`. Otherwise it walks the witness list, oldest first, and
  answers the collision of the i-th witness that has one and has this body
  at either end. If there are fewer such witnesses than i + 1, it answers
  NULL.
- **EnableCollisions** takes one off `CollisionsDisabled` if it is not
  zero. **DisableCollisions** adds one. Both store a byte, so 127 disabled
  once more becomes -128. A negative count is not zero, so enabling it only
  takes it further down.
- **DoBoundingBoxCheck**, in both forms, answers whether the two boxes
  overlap with the margin to spare. Every test is `<=`, so touching boxes
  pass, and a negative margin demands an overlap.
- **IsBlinking** answers 0. Only a car blinks.
- **PlotToCaffeine**, **DebugPrint** and **MaybePrintAllCollisionBodies**
  are empty.

## StaticCollisionBody

Its constructor runs the base's, bumps the static stats, sets its table and
clears `Dynamic`. Its destructor resets the table pointer, drops the stats
and runs the base's.

Its methods say that a static body does not move and cannot be pushed:

| Slot | Method | Does |
|---|---|---|
| 32 | GetVelocity | `&ZeroVector` |
| 40 | GetRotation | `&IdentityMatrix` |
| 56 | GetMaxBackupTime | 1000.0 |
| 80 | Interpolate | the rotation set to IdentityMatrix and the position to ZeroVector, all sixteen bytes of each |
| 96 | GetCurrentVelocities | both set to ZeroVector |
| 104 | GetTestImpulseVelocities | the first two of its four set to ZeroVector; the other two untouched |
| 120 | ConsiderImpulse | 1.0 |
| 136 | AreCollisionsEnabled | `CollisionsDisabled == 0` |
| 152 | GetMassInverse | 0.0 |
| 160 | GetInertiaTensorInverse | `&ZeroMatrix` |
| 168 | IsMoveable | 0 |
| 176 | ChangeInEnergy | 0.0 |
| 192 | GetBounciness | 0.1 (gp-28704) |
| 200 | GetFriction | 0.3 (gp-28708) |

SetPosition (48), Move (64), Backup (72), RecomputeAuxilliaries (88),
SetToPhysicsMode (112) and ApplyImpulse (128) are empty.

## TrackPolygonCollisionBody

**The constructor** (0x001ce020) takes an ID and a TopologyTreePolygon. It:

1. runs the static constructor with type 3, then sets its own table;
2. runs the VCPolyhedron constructor on the Wafer, bumps the stats, and
   points `pPoly` at the Wafer;
3. names the body `"TrackPolygon%d"`. The number is the polygon's index in
   the tree's table, `subu ; sra 5` of the two addresses;
4. takes a reference on the polygon's TrackPolygon (`AssignTrackPolygon`),
   keeps it in `pTP`, and points the TrackPolygon's `pCollisionBody` back
   at the body;
5. builds the Wafer from the TrackPolygon at the origin;
6. sets its box from the TrackPolygon's BBoxMin and BBoxMax, which sorts
   it into the list;
7. calls PlotToCaffeine with an identity matrix, which does nothing.

**The destructor** (0x001ce138):

1. clears the TrackPolygon's `pCollisionBody` and gives the reference back
   (`UnAssignTrackPolygon`);
2. drops the stats;
3. destroys the Wafer with flags 2, then runs the static destructor with
   flags 0;
4. returns the slot to the pool when flags & 1.

Two bodies can be made on one polygon. Each takes a reference, and the
TrackPolygon points at the second. When either goes, the pointer is
cleared, even though the other body is still alive.

The methods:

- **GetPosition** answers `&ZeroVector`. The Wafer is built at the origin,
  so that is where the polygon is.
- **GetTerrainType** reads the TrackPolygon's terrain with `lb`, so a
  terrain of 0x80 or more comes out negative.
- **GetTrackPolygon** answers `pTP`.
- **operator new and delete** use the track-polygon pool.

## CollisionBodyWitness

**The constructor** (0x001cb8f0):

1. builds the VCWitness on the two bodies' polyhedra;
2. bumps the stats;
3. links the witness at the tail of the list and clears `pCollision`;
4. sets the pair's two bits;
5. adds one to each body's `NumWitnesses`.

**The pair bits.** Pair (ID1, ID2) is bit `ID1 * 206 + ID2`. The byte is
`sra 3` of that and the bit is `andi 7`. The constructor sets both orders
and the destructor clears both, so the field is symmetric.

- **DoesWitnessExist(a, b)** (0x001cc298) answers 0 if either ID is
  negative. Otherwise it answers the byte masked with the bit. That is 0 or
  a power of two, not 0 or 1.
- **The constructor and destructor do not test the IDs.** A body with a
  negative ID would put its bits before the field. The game never pairs
  one. The only negative IDs are a virgin smokeable's: VirginSmokeable
  (0x0020c3b4) gives a static body `~index`, and MaybeCreateWitnesses calls
  ConvertToSmokeable at 0x001cd2e0, which gives it a number, before it
  builds the witness.

**The destructor** (0x001cba18):

1. drops the stats;
2. ends the collision, if there is one;
3. unlinks the witness, takes one off each body's `NumWitnesses`, and
   clears both pair bits;
4. looks at each end in turn. A body of type 3 that is left with no
   witnesses is destroyed through its table with flags 3, and the witness's
   pointer to it is cleared;
5. destroys the VCWitness with flags 0;
6. returns the slot to the pool when flags & 1.

A track polygon's body is made for its witnesses and lives only while it
has one. Step 4 tests the type, not the class, so a static body given
type 3 would be destroyed too. The image reads the type through the
pointer before it tests the pointer for NULL.

The game never pairs a body with itself. If it did, the witness's last
destructor would destroy a track body twice.

**EndCollision** (0x001cbea8) destroys the collision, if there is one,
through `~Collision` with flags 3, and clears `pCollision`. It then takes
one off the stats' collisions and off each body's `NumCollisions`, **whether
or not there was a collision**. Ended twice, the counts go negative.

**HasExpired** (0x001cbf18) answers:

- 0 while there is a collision;
- 1 when the two boxes no longer overlap. The test is inclusive and has no
  margin;
- 1 when neither body has `ActiveCollisionDetection`;
- 1 when either body's AreCollisionsEnabled, called through the table,
  answers 0;
- 0 otherwise.

**IsYawControlInducingCollisionBody** (0x001cc010) answers whether a hit
on the body stirs the yaw control:

- a car, a smokeable or a virgin smokeable (types 0 to 2): 1;
- a track polygon's body (type 3): whether the TrackPolygon's flags have
  `TRACKPOLY_VERTICAL` (0x02), that is, whether it is a wall;
- a negative type, or 4 and above: 0.

**EliminateAllWitnesses** (0x001cc248) destroys the head of the list with
flags 3 until the list is empty. Its NULL test never fails.

## DynamicCollisionBody

A body that moves: a car's, through CarCollisionBody, or a smokeable once
it is hit. The class leaves GetPosition, GetVelocity, GetRotation and
AreCollisionsEnabled pure, and every method that needs the body's place
asks through the table.

**The constructor** (0x001cc8a8) runs the base's, bumps the dynamic count,
sets the table and `pTC`, sets `Dynamic`, and clears `pSystem`, `pBody` and
`PhysicsMode`. The backups, the cylinder and the local box are left as the
memory was. **The destructor** (0x001cc928) sets the table, drops the count
and runs the base's.

**BuildBoundingVolumes** (0x001cca58) walks the polyhedron's vertices once.
It finds:

- the sphere's radius, from the root of x² + y² + z²;
- the cylinder's radius, from the root of x² + y²;
- the highest and lowest z, as the cylinder's top and base;
- each axis's highest and lowest, as the local box.

Every extreme starts at zero, so the box always holds the origin. Each is
`if (hi < v) hi = v; else if (v < lo) lo = v;`, which, starting from zero,
is the same as two separate tests. The roots are of sums of squares, so
they are plain ones. Then 0.05 is added to the cylinder's radius and top,
and the base is stored as 0.05 less the lowest z: a height below the
origin, never negative. The sphere and the box get no margin. The top and
the box's z maximum are the same number, as are the base and its minimum;
both are kept.

**UpdatePosition** (0x001ccbf0) sets the box to the position, plus and minus
`CylinderRadius`, in x and y, through SetBBoxMinMax. That keeps the list
sorted and the widest width up to date.

**BeginMove** (0x001ccc68) keeps the rotation, the position, the velocity
(asked for in that order) and the time given.

**Interpolate** (0x001ccd08) and **InterpolateVelocity** (0x001cceb0) go
back from where the body is towards the backup. When `BackupTime` is below
1e-6 (0x358637bd, which is itself not below), they answer the body as it
is. Otherwise, with f = (BackupTime − t) / BackupTime, each answers
(now − backup) × f + backup:

- t of 0 gives now, and t of BackupTime gives the backup;
- Interpolate does it for the position and all four rows of the rotation;
- all four lanes are computed and stored, pads too. Every difference is
  taken before any blend is stored.

**Backup** (0x001ccf60) goes back to t:

1. Interpolate, through the table, gives a position and a rotation.
2. InterpolateVelocity, by name, gives a velocity.
3. The velocity is multiplied by the RigidBody's `Mass` in all four lanes,
   which makes a momentum.
4. The position, the rotation and the momentum are copied into the
   RigidBody's X, R and P.

**The pass-throughs**:

- **RecomputeAuxilliaries** (0x001cd010) calls the PhysicsSystem's
  ComputeAuxiliaries through its table.
- **GetCurrentVelocities** (0x001cd040) copies the RigidBody's `Velocity`
  and `AngularVelocity`.
- **GetTestImpulseVelocities** (0x001cd060) is RigidBody::TestImpulse.
- **ChangeInEnergy** (0x001cd710) is the RigidBody's test-impulse energy
  less its present energy.
- **ApplyImpulse** is RigidBody::ApplyImpulse.
- **GetMassInverse** and **GetInertiaTensorInverse** read the RigidBody.
- **GetBoundingBox** gives the local box.
- **GetMaxBackupTime** gives `BackupTime`.
- **SetPosition** writes through GetPosition's pointer.
- **SetToPhysicsMode** does nothing.

See [RigidBody](rigid-body.md).

**GetLocalCollisionBodies** (0x001cd078) gives the part of the list that
may reach the body, both ends exclusive:

- the first end is the first body back whose `BBoxMax.x` is below
  `BBoxMin.x` less the margin;
- the last is the first body on whose `BBoxMin.x` is past `BBoxMax.x` plus
  the margin.

Both compares are inclusive, so a body that just touches is in the range.
Either end may be the list's head.

**MaybeCreateWitnesses** (0x001cd130) does nothing if the body's collisions
are off. Otherwise:

1. It runs CreateTrackPolygonCollisionBodies.
2. It walks back to the first body that ends before this one starts.
3. It reads `MaxCollisionBodyWidthX`, after step 1, which may have widened
   it, and walks on to the first body that ends past this one's end by
   more than that.
4. It visits each body between the two, taking the next link before
   anything is done to the body. A body is skipped if it is this one, if
   the boxes do not touch, if a witness for the pair exists, or if its
   collisions are off.
5. A virgin smokeable (type 2) is handed to ConvertToSmokeable. If that
   gives NULL, or a body whose box does not touch, it is skipped.
6. A witness is made for this body and the other, in that order.

The walk on trusts the recorded width. A body wider than that is not
reached, and the game can have one: when the widest body narrows,
UpdateMaxCollisionBodyWidth leaves it out of the recount, so it can stay
wider than the width recorded.

When the walk back reaches the head, the image goes on from the head's own
next, which is the first body. The box test is the image's inlined one:
four inclusive compares with no margin. The witness pool running out is a
NULL the image would write through; the port stops there.

**CreateTrackPolygonCollisionBodies** (0x001cd3a0) makes bodies for the
TrackPolygons in `pTC`'s table that the body may be touching:

1. It keeps each polygon that has no body yet, whose box touches this
   one's, and that passes TrackPolygonCheck. Only the first 48 are kept;
   the rest are passed over without a word.
2. If none are kept, it returns 0.
3. It bubble-sorts them by their tree polygon's address (`sltu`), in whole
   passes until a pass swaps nothing.
4. It makes a TrackPolygonCollisionBody for each, with the next ID. When
   the pool is full it stops and returns how many it made.
5. Otherwise it returns how many it kept.

After each body is made, the image tests its box against this one and drops
the answer. It then asks whether a witness exists for the pair, which it
cannot, since the body is new, and would print the body if one did. The
port leaves out the box test and keeps the rest.

**TrackPolygonCheck** (0x001cd5f0) asks whether the body's cylinder reaches
the polygon's plane:

- `up` is the rotation's third row dotted with the plane's normal;
- `s` is the root of 1 − up², the cylinder's lean away from the normal;
- `dist` is the position dotted with the normal, less `PlaneDistance`;
- `h` is the base height, or the top height when `up × dist` is below
  zero, that is, when the plane is on the top's side;
- the answer is |dist| < |up| × h + s × `CylinderRadius`, strictly.

The heights and the radius are read before the table is asked for the
rotation, and the rotation before the position. The root is the EE's
`sqrt.s`, which takes the root of the magnitude. A third row a little too
long, or rounding, can put `up` past one, and there the console gets a
small root where IEEE gets a NaN. That NaN fails every compare, so the
polygon would be dropped. The port calls `ee_sqrt` (eefpu.h), and the
checker runs mipsemu with `eesqrt`.

## CarCollisionBody

A car's body. Car's constructor takes one from `CarCollisionBodySlotPool`.
While the car drives on rails, the body answers with the car's own
CarState. Once `PhysicsMode` is set, it answers with the car's RigidBody.
An impulse on it becomes four things: damage, a rumble, a flinch from the
driver, and a jolt in the force feedback.

**The constructor** (0x001cd750) runs Dynamic's with the next ID, type 0
and the car's TopologyCoordinate. Then, in order:

- the table, and the car count and its highest;
- `pCar`; `ActiveCollisionDetection` set; `pSystem` and `pBody` cleared
  again;
- both Timers stamped with `WorldTimer`. Their own constructors zero them
  first;
- the debug name `Car<DriverNumber>`, through bSPrintf into sixteen bytes;
- the volume. That is `FindPipelinePolyhedron` of the hash of
  `<BaseModelName>_CV`, given the car type's `CenterOfGravity`, so a volume
  not fixed yet is moved to it. When the disc has none, it is a
  RectPolyhedron from the two-argument `bMalloc(2800, 16)`: x from -2.217 to
  2.165, y ±0.971 and z from -0.2 to 0.624;
- BuildBoundingVolumes and UpdatePosition.

**The destructor** (0x001cd898):

1. It sets the table and drops the count.
2. It looks the volume up again by name, with no centre.
3. If that finds nothing and `pPoly` is set, it destroys `pPoly` with
   flags 3, calling VCPolyhedron's destructor directly, not through a
   table. `pPoly` is then the constructor's box, or a disc volume that has
   left the list since.
4. Dynamic's destructor runs.
5. The slot goes back to the pool when `flags & 1`.

VCPolyhedron's destructor does not take a volume off the list.

**The getters** (slots 24, 32 and 40) answer the RigidBody's X, Velocity
and R when `PhysicsMode` is set. When it is not, they answer the car's
Position, Velocity and BodyMatrix.

**Move** (0x001cdad0, slot 64):

1. BeginMove.
2. `Car::Move(t)`, which answers how long the car moved: `done`.
3. If that is less than t -- a car on rails that hit something -- the body
   goes to physics mode through slot 112 with no other body, and
   `Car::Move` is called again for the rest, t − done. A NaN on either side
   fails the compare and skips this.
4. UpdatePosition.

**SetupPhysicsPointers** (0x001cda20) clears `pSystem` and `pBody`. Then, if
`PhysicsMode` is set and the car moves by PHYSICS_MOVEMENT or
MELLOW_MOVEMENT, it points them at the mover's PhysicsSystem (mover + 8)
and at its RigidBody (the pointer at mover + 24). Both movers keep them
there, and the image does not tell the two apart. The image's `movz`
guards a NULL mover in the first store, and then reads through it in the
second. The port aborts on a NULL mover.

**SetToPhysicsMode** (0x001cda80, slot 112) hands `Car::SetToPhysicsMode`
the car on the other side, then sets the pointers up again. That car is
`other`'s pCar when `other` is a car's body (Type 0, read with `lb`). It is
NULL for any other body, or with no `other`.

**ApplyImpulse** (0x001cdbe8, slot 128):

1. f is 1. When the RigidBody's inverse mass is past 1/1.3
   (`0x3f44ec4f`), f is 1/1.3 over it, so a car lighter than 1.3 takes the
   impulse a car of 1.3 would. `vmulx` scales all four of the impulse's
   lanes, pad too.
2. The scaled impulse goes to `ApplyImpulseWithScaledInverseInertiaTensor`
   with 0.4.
3. Its length is summed (x² + y²) + z², and a root is taken. AddDamage gets
   it with `at`, and AnimateCollisionReaction with the scaled impulse.

**AddDamage** (0x001cdca0; retail's 0x001d83d0) has three parts:

- **The damage.** With `pCarDamage` set, `at` in the car's frame and 0.013
  of the size go to `CarDamage::AddDamage`: retail's gp-28324. The demo's
  is 0.03 (gp-28720), which the port had until TASKS 73, so each hit
  dented a car 2.3 times as much as on the PS2. The frame is the transpose of
  the RigidBody's rotation, applied by bMulMatrixVec3 with a w of 1. The w
  brings in the transpose's fourth row, which is zero because R's fourth
  column is, and it is written into the pad.
- **The rumble.** On a player's car, with a RaceCoordinator, the whole size
  goes to `PortRumbleImpact` on the player's JoyPort. The state must be
  none of these:
  - INSTANT_REPLAY (4);
  - AUTO_REPLAY (5);
  - POSTRACE (7);
  - REPLAY_DEMO_MODE (9);
  - AI_DEMO_MODE (8).

  The first four are RaceCoordinator's IsReplaying and IsDemoMode inlined,
  and 9 goes through IsReplayDemoMode out of line. The state is then read
  again, and `state − 8 < 2`, unsigned, shuts out 8 and 9. So 9 is tested
  twice. The port subtracts unsigned too; as an int32 the subtraction
  would overflow at INT_MIN.
- **The pursuit.** With a cop manager, the whole size goes to
  `tCopManager::MonitorImpact`. Retail calls it only for a size of 1 or
  more, and passes whether any of the body's NumCollisions collisions is
  a two-car one (GetCollision, then IsTwoCarCollision, stopping at the
  first). The port has that in the seam, `copmgr_car_impact`
  (`copmgr.c`).

**AnimateCollisionReaction** (0x001cddc0):

- **The flinch.** With an AnimatedDriver:
  - past 20, strictly, the impulse in the car's frame picks the flinch at
    priority 3. If |y| < |x|, it is back (10) for x > 0 and front (7)
    otherwise. Else it is left (9) for y > 0 and right (8) otherwise;
  - past 4, strictly, it is the light flinch (6) at priority 2.

  The frame spreads a NaN in any lane of the impulse to every lane, and a
  NaN direction is right. 20 and 4 are built with `lui` (0x41a0 and 0x4080)
  and are not loaded.
- **The jolt.** On a player's car past 4, `Car::StartForceImpact` gets the
  impulse in the car's frame and the size. The vector goes by value, as a
  copy of all four lanes.

**AreCollisionsEnabled** (0x001cdb50, slot 136) is 0 while either AI switch
is set. Otherwise it is `CollisionsDisabled == 0`. Car::IsCollideable is
its one caller in Car.obj.

**GetMassInverse** (0x001cdb78, slot 152) is the RigidBody's, clamped to
1/1.3 with `c.lt.s`, so a NaN is answered as it is.

Retail reads through `pBody` without a check. A car in COP_MOVEMENT or
TRAFFIC_MOVEMENT has none: a cop a collision put in MELLOW_MOVEMENT can be
put back by its own logic before the Player's knock test reads that
collision. Retail then reads the PS2's word at 0x11C. The port answers 0, as
a static body does; the knock test only asks whether the answer is under
500, and any car's is.

**GetInertiaTensorInverse** (0x001cdba0, slot 160) writes `I_body_inv`'s
first three rows times 0.4, all four lanes, into
`ScaledInverseInertiaTensor`, copies the fourth row, and answers that
matrix.

**IsBlinking** (0x001ce720, slot 184) is `Car::IsBlinking`. Only when that
is 0 is `Car::IsPoofed` called.

The rest answer constants:

- ConsiderImpulse: 1.0;
- GetTerrainType: TERRAIN_TYPE_CAR;
- IsMoveable: 1;
- GetBounciness: 0.1;
- GetFriction: 0.3.

The inline accessors set and get the two Timers and get `pCar`. The Timer
getters answer the Timer in `v0`.

**What the port does not have yet.** An impulse reaches five things the port
does not have, and each is a seam in `collisionbody.h`:

- `CarDamage::AddDamage` (0x001aba30);
- `tCopManager::MonitorImpact` (0x00213ff0);
- `AnimatedDriver::BeginCollision` (0x0019fa20);
- `PortRumbleImpact` (0x00152fa0);
- `Car::StartForceImpact` (0x00133160).

The damage, the pursuit and the driver's animation change what happens
next, so the port aborts on a NULL one that is reached. Nothing sets
`pCarDamage`, `pCopManager` or `pAnimatedDriver` yet. The rumble and the
jolt are only felt, so a NULL one is skipped. `main.c` sets none of the
five. bSPrintf and bStrCat are `snprintf`.

## Contact

Two bodies a witness has found inside each other. World's
DoTimestepCollisions (0x0014b110) asks every witness for a contact, resolves
them in the list's order, and takes a resolved body's other contacts off the
list. A contact backs its pair up to the moment they touched, pushes them
apart if they never stopped overlapping, and gives them an impulse there.

**The vectors are VU0's.**

- Every add, subtract and scale is all four lanes.
- A dot product is `vmul.xyz` and two `vadd`s: (x + y) + z.
- A cross product is `vopmula` and `vopmsub`, and keeps its first operand's
  fourth lane.
- A normalise is `vrsqrt` into Q, which scales all four lanes. A zero length
  divides the EE's way, to FLT_MAX.
- A length is `sqrt.s` of the dot product.
- A vector is turned round by `vsub` from vf00, which is (0, 0, 0, 1). The
  fourth lane comes out 1 − w, not −w.

**InitContact** (0x001ca170) makes `ContactSlotPool`, 32 slots of 64 bytes.
**CloseContact** (0x001ca1a0) deletes it and leaves the pointer NULL. Their
callers are EndGameFlowLoadingTrackSpecific and
BeginGameFlowUnloadingTrackSpecific.

**RemoveContacts** (0x001ca1c8) walks the list, taking each next link first.
It unlinks every contact with the body at either end and destroys it with
flags 3. The destructor is World.obj's inline copy (0x0014c188): `~bTNode`
with flags 0, which does nothing, then the slot back to the pool when
flags & 1.

**ContactTimeSorting** (0x001ca240) answers 0 when a backs up further than
b, and 1 otherwise, a NaN included. **bList::AddSorted** (0x00238290) puts
the new node before the first node the function answers 0 for, or at the
tail. So the list runs from the longest backup down, and a tie goes after
the ones already there.

**The constructor** (0x001ca268) sets the two bodies and the witness, then
BackupTime from FindContactTime, then `LoopFound` from `WorldLoopCounter`.
It leaves the links alone.

**FindContactTime** (0x001ca2a8) finds how far back the bodies first
touched. Its answer is a backup time: 0 is now, and more is further back.

1. It zeroes CrowbarVector.
2. hi is the shorter of the two bodies' GetMaxBackupTime, the first asked
   first, and lo is 0.
3. Eight times, t is halfway from lo to hi, both bodies are interpolated
   back to t, and VClip is asked about them there:
   - overlapping: lo becomes t, and the next t is further back;
   - apart by less than `ContactThreshold`: the answer is t;
   - apart by more: hi becomes t.
4. If the eighth still overlapped, Crowbar finds the push that parts them
   at t.
5. The answer is the last t.

The zero it stores is a quadword whose fourth lane the image never writes,
so on the console CrowbarVector's pad is whatever the stack held. The port
writes it zero.

**FindWaferNormal** (0x001ca460; retail's 0x001d4950) gives the normal of a
track body's wafer that faces a dynamic body. It starts from the plane of
the wafer's first face. When the body's position dotted with the normal is
above the plane's distance less `WaferBias`, the normal is kept. Otherwise
x, y and z are negated and the fourth lane stays 0. With the demo's bias of
0.5, a body up to 0.5 below the plane is still taken to be above it.
Retail's code is the demo's, but its `WaferBias` is 0 (gp-17844 holds 0 in
SLES_507.31's .sdata, and nothing writes it), so a body on or below the
plane is taken to be below it. The port has had retail's 0 since TASKS 73.

**Crowbar** (0x001ca538) pushes two bodies apart at t:

1. Both are interpolated back to t.
2. The direction always runs from the first body towards the second:
   - the first a track polygon's body (type 3): its wafer's normal, facing
     the second;
   - the second one: its wafer's normal facing the first, turned round from
     vf00, so the fourth lane is 1;
   - otherwise the line between the centres, normalised in all four lanes.
3. Twenty times, s grows by 0.05, added up and not multiplied. The first
   body is moved back by s along the direction and the second on, each only
   if IsMoveable, and VClip is asked. As soon as they are apart, that push
   is CrowbarVector.

Neither body is moved; the push is only recorded. Twenty steps that do not
part them leave CrowbarVector as it was.

**Resolve** (0x001ca760):

1. Each body goes to physics mode against the other, the first first.
2. Each is backed up BackupTime.
3. The first's position less CrowbarVector and the second's plus it, each
   only if IsMoveable, are set.
4. Both recompute their auxiliaries.
5. CollisionImpulse.
6. Both recompute their auxiliaries again, and each moves on through
   BackupTime.

**FindContactPointAndNormal** (0x001ca968). The witness keeps its two
closest points in each body's frame. Each is rotated by bMulMatrixVec3 and
moved by its body's position, and the contact point is halfway between. The
normal runs from the first body to the second:

- the first body not `Dynamic`: its wafer's normal, facing the second;
- the second not `Dynamic`: its wafer's normal facing the first, turned
  round from vf00, so the fourth lane is 1;
- otherwise the line between the two closest points, over its length. When
  that length is below 1e-6, the points are taken to coincide, and the
  normal is the line between the centres, normalised on VU0.

This tests `Dynamic`, where Crowbar tests the type. A static body that is
not a track polygon's would have its polyhedron read as a wafer.

**FindPlanarCollisionContactPoint** (0x001cabb0) has no callers. e is up
with its part along the line between the centres taken out, normalised. The
point is moved along e onto the plane through the first centre that e is
square to. That plane holds both centres; for two bodies level with each
other it is the horizontal plane through them. Its up vector's fourth lane
is never written, as with FindContactTime's zero.

**GetContactPointVelocity** (0x001cad30) is v + w × r, all four lanes: the
fourth is v's plus w's. **DenominatorTerm** (0x001cad60) is
n · ((M (a × n)) × a), the rotational part of an impulse's denominator.

**CollisionImpulse** (0x001cade0) gives the bodies rounds of impulse at the
contact point until they stop closing. It starts with:

- the contact point and the normal;
- the witness's Collision, begun at the point if there is none;
- r1 and r2, the point less each body's position.

Each round then has seven steps:

1. **Closing.** Each body's current velocities give its point's velocity,
   and vrel is the second's less the first's. vn is vrel along the normal,
   and vt is the rest of vrel, across it. When vn is not below 0 the bodies
   are not closing, and it returns.
2. **The impulse along the normal.** e is the bouncier body's bounciness,
   and j is −(e + 1) vn over the two mass inverses and both
   DenominatorTerms. j is never less than a floor:
   `MinimumContactImpulseFactor` × (the closing speed over
   `MinimumContactImpulseSpeed`, held at 1), over the larger mass inverse,
   which is the lighter body's.
3. **What each body will take.** ConsiderImpulse is asked of the second
   body with the impulse, then of the first with it turned round. If the
   first answers −57575 it returns, and then likewise the second: that is
   a veto. If the first answered negative, its answer is negated and this
   is the last round; if not, the same goes for the second. Only one is
   negated, so when both are negative the second stays negative, and it is
   the lesser. j is scaled by the lesser answer.
4. **Friction.** μ is the rougher body's friction. When the first body
   cannot move (a mass inverse of 0) and the second's friction is 0.3,
   which is a car's, the second is the scraper and μ is 0.1. Failing that,
   the same goes the other way round. vtl is the slide's length. The
   friction is j × μ, faded by vtl / `MaxFrictionScrapeSpeed` when vtl is
   below that, and it acts against the slide: vt × (−friction / vtl). jt is
   the normal impulse plus the friction. jn is vf00 less jt.
5. **The scraper's pull.** A scraper moving faster than 30 is pulled back.
   The pull starts as its velocity × −0.025, but where that is past −0.4 it
   is −0.4 / speed instead. Past 30 it always is, so the pull is an impulse
   of 0.4 against the scraper's travel. Its z is zeroed. The image then
   compares m1 with the z it has just zeroed, so the pull goes by whether
   the first body can move:
   - m1 of 0: the pull is added to jt, and r2 is shortened by
     |jt| / (speed × 4/7 + |jt|), with |jt| taken before the pull;
   - otherwise it goes to jn and r1 in the same way.

   The shortening is gated on 1 < speed + |j|, which past 30 always holds.
   The lever arm stays short for the rounds after.
6. **Applying it.** jt goes to the second body and jn to the first, through
   ApplyImpulse. The Collision gets AddImpulse(point, jt, vtl).
7. **Again?** If the lesser answer was exactly 1, or one was negative, it
   returns. Otherwise another round starts, from the bodies' new
   velocities.

**A car dropped straight onto flat ground has no slide.** vtl is 0, the fade
makes the friction 0, and the friction's direction is −0 / 0. The EE's
division answers FLT_MAX, and vt × FLT_MAX is 0. IEEE would answer NaN, and
the NaN would reach both bodies. The port divides with `ee_div` (eefpu.h).

**Two calls go through seams.** Two of `Collision`'s calls are seams in
`collisionbody.h`, so `collisionbody_check` can log them:

- BeginCollision's `new Collision(w, pt)`, which is bOMalloc on
  CollisionSlotPool and then the constructor at 0x0020b290, is
  `gCollisionNewFn`;
- `Collision::AddImpulse` (0x0020b450) is `gCollisionAddImpulseFn`.

A collision is state the sound and the damage read, so a NULL one that is
reached aborts. `Collision` is ported now (`collision.c`, see
`collision.md`), and `main.c` sets both, and `gCollisionDestroyFn`, to it.

## The witness's contact tests

**GetCollision** (0x001cbde0) answers the witness's Collision, begun at the
point if there is none.

**BeginCollision** (0x001cbe18) adds one to each body's `NumCollisions`, a
byte that wraps (`lbu`, `addiu`, `sb`), and to the stats' collisions, raising
their highest if it is passed. Then it makes the Collision, without looking
at the one there may already be.

**TestForContact** (0x001cc058; retail's 0x001d65f8, which the port has):

1. Retail's: the first body is asked AreCollisionsEnabled (slot 136), then
   the second. If either answers 0, that is all, before VClip.
2. VClip is asked about the two bodies where they are now: the first's
   rotation and position, then the second's.
3. `PrintThisTime` is cleared if it was set.
4. If they do not overlap, that is all.
5. If either blinks and both are dynamic, each that is a car (type 0) has
   its LastPenetrationTime stamped with `WorldTimer`, and that is all. The
   first is asked whether it blinks first, and the second only if the first
   does not. A blinking car goes through other cars, but still hits the
   track, which is not dynamic.
6. Otherwise each body that is a car has its LastYawControlCollisionTime
   stamped if the other body stirs the yaw control
   (IsYawControlInducingCollisionBody), and, retail's, its LastCollisionTime
   stamped whatever the other is; the first body, then the second.
7. A Contact is made on the pool, for the first body, the second and the
   witness, and added to the list in order.

The pool grows, so it does not run out; the port aborts if it ever answers
NULL.

## The tables

Each table has twenty-six 8-byte entries: the empty one, the destructor at
8, DoSnapshot at 16, then twenty-three methods at 24 .. 200. Unfilled
entries are `__pure_virtual`.

| Table | Address | Fills |
|---|---|---|
| `_vt$13CollisionBody` | 0x0029bf48 | the destructor, DoSnapshot and IsBlinking |
| `_vt$19StaticCollisionBody` | 0x0029be78 | all but GetPosition (24) and GetTerrainType (144) |
| `_vt$25TrackPolygonCollisionBody` | 0x0029bda8 | those two and its destructor, the rest Static's |
| `_vt$20DynamicCollisionBody` | 0x0029bcd8 | the destructor, 48 .. 56, 72 .. 112, 128, 152, 160, 176 and IsBlinking |
| `_vt$16CarCollisionBody` | 0x0029bc08 | every slot but the empty one: its own, and Dynamic's at 48, 56, 72 .. 104 and 176 |

Dynamic's table leaves these slots pure:

- 24, 32, 40: GetPosition, GetVelocity, GetRotation;
- 64: Move;
- 120: ConsiderImpulse;
- 136, 144: AreCollisionsEnabled, GetTerrainType;
- 168: IsMoveable;
- 192, 200: GetBounciness, GetFriction.

Its DoSnapshot is ported (TASKS 72b).

The car's table fills its own slots at 8, 16 (DoSnapshot), 24 .. 40,
64, 112 .. 168 and 184 .. 200.

## The static initialiser and destructor

`_GLOBAL_$I$TheCollisionStats` (0x001ce548) points both list heads at
themselves and zeroes ZeroVector's x, y and z.

`_GLOBAL_$D$TheCollisionStats` (0x001ce520) runs two list destructors:

- `~bTList<CollisionBodyWitness>` (0x001ce440) unlinks each witness and
  destroys it with flags 3;
- `~bTList<CollisionBody>` (0x001ce4b0) then does the same for each body,
  through its table.

Each destructor unlinks its record a second time. That is harmless: the
first unlink changes the neighbours' links but not the record's own, so the
second writes the same two pointers again. The console never runs its
static destructors.

## Verification

`tools/collisionbody_check.py` runs the shipped functions out of
`NFSHP2.ELF` in `tools/mipsemu.py`, and the port in the harness. Both follow
one script, and the two transcripts are diffed.

Under the image are bWare's slot pools, track.cpp's tree and polyhedra.cpp's
wafers. Under the port are track.c, polyhedra.c and vclip.c. The tree is
loaded from TRACKB12's polygon chunk. Floats are compared as bits.

Records are named, not printed as addresses:

- H0..H15: bodies in the checker's memory;
- Tn, Wn, Kn, Pn: slot n of the track-polygon-body, witness, car-body and
  TrackPolygon pools;
- #n: the nth bMalloc;
- na: the checker's own NumberAllocator;
- poly0..poly3 and C1..C4: stand-in polyhedra and Collisions.

The heap is filled with 0xa5, so a field the code does not write shows. The
model leaves the short requests' extra byte zero, and the harness prints
the port's size less the slack. Each pool gets one fixed block on each
side, and slots are labelled by number, because the host's slots are wider.
Both sides log every pool allocation and free, every bPrintf, and every
`~Collision`. The port reaches `~Collision` through `gCollisionDestroyFn`,
which the harness leaves as a logging stub. At boot `main.c` points it at
`collision_destroy`.

The script covers:

- the image's tables entry by entry, and the data before the static
  initialiser;
- the NumberAllocator:
  - an empty allocator;
  - taking numbers in and out of order, freeing below and above the lowest,
    and running out;
  - 206 numbers, including 200 and 205 in the extra byte;
  - sizes of 7, 8, 9 and 1;
  - SetMaxNumbers(0) twice, and both destructor flags;
- Init, and Close with a slot still held;
- base and static bodies:
  - IDs of 0, 205 and -1, and types 0 to 4;
  - a second body on a taken ID;
  - virtual and direct destructors with each flag;
- SetBBoxMinMax:
  - ties on BBoxMax.x, with and without an ID;
  - inverted boxes and a max.x that does not change;
  - ±0;
  - twenty-four random boxes over nine bodies;
- UpdateMaxCollisionBodyWidth on its own, down every branch, with the
  widest printed after each call;
- the flip function, including ±0 and a body against itself;
- the debug name: short, 39, 40 and 48 bytes, and junk after the NUL;
- enable and disable, across the byte's wrap;
- both box tests, at the corners and with margins of each sign;
- the static methods, called through the table on three bodies;
- track-polygon bodies on seven TRACKB12 polygons: a floor, a quad, a
  wall, a ceiling, and three other terrains. That includes a body with no
  ID and a second body on the first polygon. The TrackPolygons' flags and
  terrains are then poked, including terrains above 0x7f;
- IsYawControlInducingCollisionBody over eight types from -128 to 127;
- witnesses:
  - the bits of (205, 204), which are in the field's extra byte;
  - pairs with track bodies at either end or both;
  - HasExpired down each exit, including touching boxes;
  - GetCollision over every index;
  - EndCollision twice;
  - the destructors, with the track bodies they take along;
  - a body destroyed with witnesses left;
  - the stats' highest-counts;
  - EliminateAllWitnesses;
- the static destructor with witnesses and bodies left, and everything
  closed and started again from the top.

Slice B's scenarios follow slice A's, on the records below. They cover:

- the constructor on IDs 40, 41, 42, 43, 44 and -1 with types 1, 4 and 5;
  the destructor directly and through the table, with flags 0, 2 and 3;
  and the highest count;
- the pass-throughs on two RigidBodies of random words: through the table,
  GetTestImpulseVelocities directly, and ApplyImpulse with the energy
  before and after;
- BuildBoundingVolumes over eight vertices, then over three, two, none, a
  negative count, a NaN coordinate, one vertex, and a vertex at the
  origin;
- UpdatePosition, and a body that narrows, so the widest is recomputed;
- BeginMove, then both interpolations at six times: 0, before and at the
  backup time, past it, and below 0. Then BackupTime at 0, -0, -1, either
  side of 1e-6, and 1/128;
- Backup through the class's Interpolate, through testB's stub, and with a
  BackupTime of 0;
- the four slots testA fills, SetPosition through them, and
  AreCollisionsEnabled either side of a Disable;
- GetLocalCollisionBodies over ten bodies with margins of 0, 0.5, 10, 1e8,
  -1 and -3, and from the list's far end;
- MaybeCreateWitnesses:
  - boxes that meet at an edge;
  - witnesses already there;
  - the body disabled;
  - a list out of order, and another body disabled;
  - virgin smokeables that convert to a body before this one, to a body
    after it, to nothing, and to a body that misses;
  - the widest read after the track bodies;
  - a stale widest that misses the wider bodies;
- CreateTrackPolygonCollisionBodies:
  - nine polygons, each kept or dropped for its own reason;
  - fifty-two in shuffled order, of which the first 48 are kept;
  - the pool two slots short of full, and then full;
- TrackPolygonCheck over 22 cases:
  - the base and the top, with a tie at each;
  - facing away, and at a lean;
  - a third row long enough to take `sqrt.s` negative;
  - NaN in the position, the distance and the row;
  - two sums whose order decides a tie;
  - a base of 0 on the plane;
- a dynamic body destroyed with witnesses.

Its records:

- D0..D3: DynamicCollisionBodies in the checker's memory;
- testA and testB: the class's table with GetPosition, GetVelocity,
  GetRotation and AreCollisionsEnabled pointed at logging stubs, each
  with a `this` delta of 8. testB stubs Interpolate too;
- S0..S3: what the stubs answer, a position, a velocity and a rotation
  each;
- PS0: a PhysicsSystem whose ComputeAuxiliaries logs, with a delta of 4;
- RB0 and RB1: RigidBodies, filled word by word;
- TC0: a TopologyCoordinate over the TrackPolygon pool's slots;
- dpoly0 and dpoly1: stand-in polyhedra of up to eight vertices;
- ConvertToSmokeable: `gConvertToSmokeableFn` in the port, a stub in the
  model, both answering from the script's map.

The model runs mipsemu with `eesqrt`, and the port calls `ee_sqrt`. The
model stops if any `sqrt.s` but TrackPolygonCheck's (0x001cd668) takes a
negative, or if that one never does.

Slice C's scenarios come after slice B's and before its teardown. They
cover:

- the constructor:
  - on DIABLO's volume, which is fixed already;
  - on a name with no volume, so it gets the box;
  - on BUS's volume, which is moved to the centre of gravity;
  - with driver numbers 3, -7 and 11, and a WorldTimer of 123456, then -5;
- the Timer accessors and GetCar;
- the destructor:
  - directly with flags 0, which destroys the box and keeps the slot;
  - through the table with flags 3;
  - a car made again on BUS, now fixed, and a second box;
  - a car whose `_CV` has gone, and one with no volume at all;
  - a dump with two cars left and the highest still 3;
- the getters, on rails and in physics mode;
- the constants and Dynamic's slots, all through the car's table;
- GetMassInverse and GetInertiaTensorInverse over eight inverse masses:
  4, the bound, one ulp either side of it, 0, -1, NaN and infinity;
- GetMassInverse with no RigidBody. The model's word at 0x11C is 0, which
  the checker asserts, so retail answers the port's 0;
- AreCollisionsEnabled with each switch at 1, -1 and 0, and with the body
  disabled;
- IsBlinking over six pairs of answers. The stubs' logs show where it
  stops;
- Move over ten steps: the car finishing, falling short, answering -0, NaN
  or 0, a NaN t, and a step one ulp short;
- Move into physics mode, onto M0;
- SetupPhysicsPointers with neither movement, on M1's mellow movement, and
  with `PhysicsMode` clear;
- SetToPhysicsMode with another car's body, a dynamic body, none and a
  second car, and through the table;
- ApplyImpulse on a turned car:
  - the damage alone, the light flinch, and the four hard ones;
  - 20 and 4 exactly;
  - 2000, past RigidBody's 1000;
  - (4.5, 0.1, 0.2), whose length's two sum orders differ in the root;
- ApplyImpulse on a car lighter than 1.3, with three impulses, one with
  all three lanes set;
- AddDamage:
  - in every race state from -1 to 10, and at INT_MAX and INT_MIN;
  - with no race, no player, no damage and no cop manager;
  - on JoyPort 3;
  - with sizes of NaN, -0 and 1e30;
- AddDamage and AnimateCollisionReaction with the rumble and force seams
  NULL;
- AnimateCollisionReaction:
  - twelve directions at 25: the four sides, the four diagonals, straight
    up, -0, and a NaN in x or in y;
  - nine sizes: one ulp past 20, 20, 10, one ulp past 4, 4, 3, NaN, -25
    and infinity;
  - a turned car;
  - no driver;
  - no player.

Its records:

- CAR0..CAR2: stand-in Cars with only the fields a car's body reads. The
  model has them at the image's offsets; the harness uses a real Car. Their
  CarTypeInfos are named DIABLO, BUS and NOSUCHCAR;
- PP0 and PP1: stand-in PipelinePolyhedrons, linked at the list's tail as
  the loader links them and hashed as DIABLO_CV and BUS_CV. PP1's centre of
  gravity is not fixed yet;
- PL0, a Player;
- M0, a PhysicsCar on RB1, with M0.sys its PhysicsSystem;
- M1, a MellowMover on RB0;
- AD0, DMG0, RC0 and COP0;
- Car's calls: Move, IsBlinking, IsPoofed and SetToPhysicsMode are stubs
  on the model's side and the harness's own on the port's. They answer
  from the script, and Move answers from a queue;
- the five seams: logging stubs on both sides. `G_SEAMS` leaves the rumble
  and the force NULL, as the 3DS build does, and quiets the model's two
  stubs.

A dump adds the PipelinePolyhedron list and each volume's corners. For a
car's body it adds the box's corners and faces, so the move to the centre
of gravity shows.

The model runs `_GLOBAL_$I$RectEdgesNearFaces`, which points the list's
head at itself.

Slices D and E's scenarios come after slice C's. They cover:

- InitContact, with the pool dumped before and after;
- TestForContact:
  - two cars the bisection finds touching, and the same two apart;
  - `PrintThisTime` set and cleared;
  - a second contact at the same time as the first, which goes after it;
  - a blinking car, first and second, against a car, against a body that
    is not a car, and with either body not dynamic;
  - the yaw stamps: against a type of -1, with only one car, and against a
    track body whose polygon is a wall and then is not, at either end;
  - retail's: collisions off on the first body, then on the second, so
    that neither is asked anything more and nothing is stamped;
- RemoveContacts: the last contact, none, a run of them, a track body's,
  and an empty list;
- AddSorted: ties, and a new contact at the head, at the tail and between;
- ContactTimeSorting, with a NaN and with -0 against 0;
- the destructor with flags 0, 2, 1 and 3, and a slot used again;
- FindContactTime:
  - overlapping by 0.25, with both bodies moveable, one, or neither;
  - overlapping deep enough that the eighth step still overlaps, and
    Crowbar's twenty steps that do not part them;
  - off the axis, turned, and with the fourth lanes set;
  - either body's backup the shorter, and both equal;
  - `ContactThreshold` at 0, 0.25 and 0.05;
- Crowbar along the line of centres at three times, and where the bodies
  are apart at once;
- FindContactTime and Crowbar against the flat quad and the leaning
  triangle, with the track body first and second, below the plane within
  `WaferBias` and past it, and with nothing moveable;
- FindWaferNormal at nineteen positions, with the bias at retail's 0 (on
  the plane and 1e-7 either side), the demo's 0.5 and -0.25, and one
  position just inside it;
- FindContactPointAndNormal:
  - two dynamic bodies, turned, with the closest points apart, one, 3e-8
    apart and 5e-6 apart;
  - six random pairs;
  - either body with `Dynamic` cleared, so its box is read as a wafer;
  - four cases with a track body, at either end;
- FindPlanarCollisionContactPoint in three set cases and five random ones;
- GetContactPointVelocity and DenominatorTerm nine times each, one
  DenominatorTerm a sum whose order decides it;
- GetCollision and BeginCollision: a collision begun, one already there,
  the counts' bytes wrapping at 127 and 255, and the stats' count below its
  highest and level with it;
- CollisionImpulse:
  - two cars in one round, the pair parting already, and the other way about
    (the second body bouncier, lighter and rougher);
  - the floor: vn of 0, closing at 0.2 over mass inverses of 1 and 0.5,
    and of 0.5 and 0.25, closing at 0.008, and both constants changed;
  - ConsiderImpulse's answers: a veto from either side, a negative from
    either and from both, several rounds, more than 1, and 0;
  - the friction: the rougher side, a car scraping something immovable at
    four velocities either way round, both bodies at a car's friction, the
    other body not a car either way round, two rounds pulled, a slow slide,
    and `MaxFrictionScrapeSpeed` at 4;
  - a car on the track: straight down with no slide, fast, rough, with the
    track body second, and with a collision already on the witness;
  - six random pairs;
- Resolve: two cars crowbarred apart, with each body moveable or not, and a
  car on the flat quad;
- CloseContact, and everything closed.

Their records:

- E0..E3: DynamicCollisionBodies on testC. That is the class's table with
  the nineteen slots a contact calls pointed at logging stubs, each with a
  `this` delta of 8. They answer from what the script sets for each body:
  - a position, a velocity and a rotation;
  - the current velocities and an inertia tensor inverse;
  - the maximum backup, the mass inverse, the bounciness and the friction;
  - whether it moves and whether it blinks.

  Interpolate backs the position up along the velocity. ApplyImpulse adds
  the mass inverse times the impulse to the current velocity.
  ConsiderImpulse answers from a queue, and then 1;
- B0..B3: RectPolyhedra for their shapes;
- two track bodies on TRACKB12 polygons, given a flat quad at z = 0 and a
  triangle leaning towards -y;
- six witnesses: E0 and E1, a track body first, a track body second, E2 and
  E3, and the triangle at either end;
- Xn: slot n of the contact pool, and clist, the list TestForContact sorts
  into. The script names a contact by slot, by its place on clist, or as the
  one made last, since the pool's free list runs last in, first out;
- the Collision's two seams, `gCollisionNewFn` and `gCollisionAddImpulseFn`
  in the port, stubs in the model. Both log.

Two quadwords are loaded with a fourth lane the image never wrote:
FindContactTime's zero and FindPlanarCollisionContactPoint's up. The model
zeroes both words, since the port writes them zero.

The model runs with `eediv` too, and the port calls `ee_div`. The model
stops if any division but CollisionImpulse's friction (0x001cb278) divides
by zero, or if that one never does.

```
collisionbody_check  83 scenarios, 1583 ops, 35588 lines, 90 dumps, 0 differ
                     TrackPolygon bodies on TRACKB12 polygons 2 11 1553 1543 40 220 734
```

`--mutate` ran 648 mutations: 624 were caught and 24 are
equivalent, with 0 unexplained. There are 661 now: TASKS 73's slices
added the rest and ran their own with `--only NAME,...`, which runs just
those. Slice 13's sixteen, its own and the yaw stamps' rewritten for the
new shape, are all caught. The twenty-four are:

- the static destructor's two unlinks, of a witness and of a body. Each
  record's own destructor unlinks it again from its own links, which the
  first unlink did not touch;
- AllocateNumber(i) looking one bit past the top. Bit `MaxNumbers` is
  never set, since nothing allocates past the top and every field starts
  zeroed;
- Init's zeroing of ZeroMatrix, which nothing else writes;
- UpdateMaxCollisionBodyWidth's `w == cur` test. An equal width fails the
  widening test and then returns at `!(w < cur)` anyway;
- the Static and TrackPolygon destructors' table stores. The base's
  destructor overwrites them before anything reads them;
- the witness constructor's `pCollision = NULL`. The witness pool zeroes
  every slot it hands out, and a witness is only built in one;
- the witness destructor clearing its pointer to a track body it has
  destroyed. Nothing reads a destroyed witness: it is off the list, and
  with flags 3 its slot is freed straight after and zeroed before it is
  handed out again;
- the Dynamic destructor's table store, which the base's destructor
  overwrites before anything reads it;
- CreateTrackPolygonCollisionBodies' early return when nothing is kept.
  Without it, the sort's one pass and the loop that makes the bodies run
  no times, and n, which is 0, is returned;
- the car constructor's highest-count test as `<=`. At an equal count the
  highest is stored over itself;
- the car constructor's clearing of `pSystem` and `pBody`. Dynamic's
  constructor has already cleared them;
- the car destructor's table store, which Dynamic's destructor overwrites
  before anything reads it;
- ApplyImpulse's clamp as `<=`. At the bound, f is the bound over itself,
  exactly 1;
- GetMassInverse's clamp as `<=`, which at the bound stores the bound over
  itself;
- AddDamage's `pPlayer` and `pRaceCoordinator` tests in the other order.
  Both are loads, and nothing between them writes;
- AddDamage without the IsReplayDemoMode test. The AI demo range shuts out
  state 9 again;
- the AI demo range narrowed to state 8 alone. IsReplayDemoMode has
  already shut out 9;
- AnimateCollisionReaction's `0 < x` as `<=` in the x branch. That branch
  is only taken when |y| < |x|, so x is neither zero nor a NaN in it;
- SetupPhysicsPointers reading a PhysicsCar as a MellowMover. The two hold
  the PhysicsSystem and the RigidBody's pointer at the same offsets, on the
  host as on the console;
- CollisionImpulse's pull starting at −0.025. It is only worked out past 30,
  where speed × −0.025 is below −0.75 and so always past −0.4, and the
  −0.025 is always replaced by −0.4 / speed;
- the lever arm's `1 < speed + len` test left out. It too is only reached
  past 30, where it always holds;
- the lever arm's length taken from jn rather than jt. jn is vf00 less jt,
  so its first three lanes are jt's negated, and the length squares them.

Slices D and E's first pass, 163 mutations, left seven. Three are the
equivalents above. The other four were holes in the script:

- **Every floor case had a larger mass inverse of 1**, where dividing by it
  and multiplying by it agree. One case now has 0.5 and 0.25.
- **No case had a first body that is not a car against an immovable
  second**, so the second branch's friction test never showed. The mirror
  of the first branch's case is in now.
- **The second body's two stamps were overwritten before any dump.** The
  script had a blinking car against a body that is not a car, and a body
  that is not a car against a car that stirs the yaw control, but the next
  test stamped the second body as a car before any dump. A dump now follows
  each.

Slice C's first pass, 156 mutations, left eighteen:

- **Two were dropped as not the slice's mutants.** One was a signed rewrite
  of the AI demo test, which shuts out the same two states. The other was
  GetDistanceAndSpeed's `*speed`, which is Car's sixth slice's, and
  `carmode_check` already has it (`dcb-speed-kept`).
- **Ten are the equivalents above.**
- **Six were holes in the script:**
  - every dump came after the car count was back at its highest, so the
    highest-count test never showed;
  - every impulse on a car lighter than 1.3 had y and z of 0, so their
    scale did not show;
  - every impulse's length summed exactly, whichever way it was summed;
  - the harness always set the rumble and force seams, so their NULL
    tests never ran.

Slice B's first pass, 145 mutations, left seven. Two are the equivalents
above. The other five were holes in the script:

- no box met the dynamic body's bottom edge exactly;
- BeginMove was given 0.5, which was the constant the mutant stored;
- the widest was never stale, which is the only way the walk on tests
  anything past `BBoxMax.x`;
- every dot product in TrackPolygonCheck summed exactly, so neither
  sum's order showed. Two cases now put a tie one rounding away.

Slice A's first pass left two unexplained, and one of its equivalents was
wrong:

- **UpdateMaxCollisionBodyWidth's `cur == widest`** against `<=`. They
  part only when a body that was not the widest narrows. The script had
  that case, but its op printed only its inputs, and the next op set the
  widest again before any dump. The op now prints the widest after the
  call.
- **DoesActiveCollisionDetection** answering `CollisionsDisabled`. Every
  body the script read had both at 0. It now reads one with -1 and 0.
- **The pair bit's order** was listed as equivalent, because the field is
  symmetric. It is, but DoesWitnessExist answers the masked byte, so the
  order picks which power of two comes back, and the pass caught it. The
  tally had printed the list's size instead of the survivors, which hid
  that. It now counts the survivors, and fails on an entry whose mutant
  was caught.

A mutant that breaks the body list, such as a destructor that does not
unlink, makes the next walk loop forever. The harness's timeout, 30 s,
counts that as caught. The whole script runs in about four seconds.

Three things surfaced while it was being built:

- **The first witnesses paired a body of ID -1**, and the host wrote junk
  just before its bit field. Nothing in the game does that (see above), so
  the script keeps witness bodies to real IDs.
- **The first script paired a body with itself**, and the model and the
  harness each freed a body twice. The script now pairs two bodies.
- **The harness printed the tree's polygon count as 0.** It had loaded the
  tree and printed the count in one printf, and C leaves the order of the
  arguments open. The load is now sequenced first.
