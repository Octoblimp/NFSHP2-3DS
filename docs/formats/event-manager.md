# event-manager -- the track's triggers, the event queue and the bushes

A track holds spheres, its event triggers. Each step, a car near a player
asks which of them a point just ahead of it is inside. The bushes it is
inside shake and shed leaves. The driving-line triggers would show the
training line, but retail never turns training lines on.

Retail splits this over four objects:

| object | retail | port |
|---|---|---|
| EventManager.obj | `0x001ba078` .. `0x001ba898` | `eventmgr.{c,h}` |
| FernShaker.obj's FernShaker half | `0x001d9b58` .. `0x001da5d8` | `fernshaker.{c,h}` |
| eModel's rigid animation timing | `0x0010c8f0`, `0x0010c910`, `0x0010dae8` | `emodelanim.c` (prototypes in `emodel.h`) |
| Car::TriggerEvents, Player::TriggerVisibleDrivingLine | `0x001335c0`, `0x00180b78` | `carevents.c` (prototypes in `car.h`) |

`tools/eventmgr_check.py` runs retail's code for all four against the
port (see "The check").

## The chunk

LoaderTable slot 7 takes the container `0x80036000`. A track's bundle has
one. Its children:

| id | what | payload |
|---|---|---|
| `0x36001` | the pack's header, EventTriggerPack | 24 bytes |
| `0x36002` | an AABB tree over the triggers, its nodes after it | vAABBTree |
| `0x36003` | the triggers, EventTrigger | 32 bytes each |

Each payload starts at the child's first 16-byte boundary after its 8-byte
header (`(chunk + 23) & ~15`). The loader points into the chunk and copies
nothing.

EventTriggerPack:

| off | field | |
|---:|---|---|
| 0 | `Node` | the pack's place on its list |
| 8 | `Version` | 1 |
| 12 | `NumEventTriggers` | |
| 16 | `EventTree` | set by the loader |
| 20 | `EventTriggerArray` | set by the loader |

EventTrigger:

| off | field | |
|---:|---|---|
| 0 | `NameHash` | |
| 4 | `EventID` | |
| 8 | `Parameter` | what the event acts on |
| 12 | pad | |
| 16 | `PositionX`, `PositionY`, `PositionZ` | the centre |
| 28 | `Radius` | |

Retail's tracks have two kinds of trigger:

- `TRIGGER_EVENT_CAR_ON_FERN` (`0x10003`), 5 to 909 a track. The parameter
  names a bush: its scenery section in the high half and its instance in
  the low half.
- `TRIGGER_EVENT_VIEW_DRIVING_LINE` (`0x10005`). The low byte is the track
  direction (0 forward, anything else backward), the next byte the
  seconds, and the high half the line.

## The loader

LoaderEventManager (`0x001ba100`) returns 0 for any other chunk. Otherwise
it walks the children in order:

- a header makes the pack. A pack whose Version is not 1 ends the walk
  there with 1, on no list;
- a tree goes in the pack, with its NodeArray just after the tree, and the
  triggers go in the pack. Either one before a header is skipped.

After the walk, a pack with triggers, a tree and an array goes on
EventTriggerPackList's tail. A pack missing any of the three goes on
EmptyEventTriggerPackList. The loader returns 1.

UnloaderEventManager (`0x001ba248`) takes the pack off its list when the
first child is a header of Version 1. The image reads only the first
child's type and never steps on from it, so a container that starts with
anything else spins for ever. No disc has one; the port returns 1.

## The queue

The module has two slot pools in pool 16: 60 events of 36 bytes and 20
handlers of 24. InitializeEverything makes them (emEventManagerInit),
between InitQueuedFiles and eMathInit. Nothing calls emEventManagerClose.

emEvent:

| off | field | |
|---:|---|---|
| 0 | `Node` | the queue's links |
| 8 | `ReferenceCount` | locks |
| 12 | `ID` | an EVENT_ID |
| 16 | `pEventTrigger` | the trigger, for a trigger's event |
| 20 | `CarPtr` | |
| 24 | `Parameter0` .. `Parameter2` | |

- **Handlers.** emAddHandler(fn, mask) returns 0 for no function or a mask
  of 0. A function already on the list gets its count raised and keeps its
  old mask. A new handler from the pool goes on the list's tail with the
  mask and a count of 1. emRemoveHandler lowers the first match's count,
  and at 0 the handler goes back to the pool. Each Car's constructor adds
  one shared handler with mask `0x10000`, which every trigger event
  matches, and its destructor removes it. The handler passes an event
  with a CarPtr to Car::EventHandler, which is empty. Trigger events have
  no CarPtr.
- **Events.** emAddEvent(id) takes an event from the pool, clears it, sets
  the id and puts it on CurrentEventQueue's tail. It returns NULL when the
  pool is empty. emRemoveEvent frees any event except the one being
  handled. emLockEvent and emUnlockEvent raise and lower the count;
  nothing in the image calls them.
- **emProcessAllEvents** (`0x001ba520`) runs at the end of
  World::DoTimestep. While it runs, new events go on a list of its own.
  For each event on the master queue, reading the next link first:
  1. every handler whose StreamMask shares a bit with the id gets the
     event, and the ticker's measure of the call is added to its
     TotalTime;
  2. the event comes off the queue. With a count of 0 it goes back to the
     pool, without being counted off; otherwise it goes on a second list.

  At the end, the second list and then the new events go back on the
  master queue's tail, and the master queue is current again.

The stats are loose. Freed events are never counted off, and nothing sets
PreviousProcessTime or EventQueueHighWaterMark.

## emTriggerEvents

emTriggerEvents(point) (`0x001ba6f8`) goes over EventTriggerPackList in
order. For each pack it asks the tree for the first leaf holding the point
(vAABBTree::QueryLeaf). It then tests each trigger the leaf lists, with
the leaf's count negated. A trigger whose sphere holds the point strictly,
`(dx dx + dy dy) + dz dz < r r` with `d = |point - centre|` in that order,
becomes an event with the trigger's id, and the event points at the
trigger.

At most 40 events are made per call, across all packs. The answer is
TriggerEventArray, the events and a NULL after them, or NULL when no
trigger is hit.

When the pool runs out, the image stores the trigger through the NULL
event, into low RAM. The port puts the NULL in the array and skips the
store, so the array ends there, as the image's does when read.

## Car::TriggerEvents

World::DoTimestep calls it for every car within 100 of a player. The point
it asks about is GeometryPosition plus 0.15 s of the velocity (gp-31928).
For each event in the answer:

- **a bush**: FlattenFern, which is empty, then ShakeFern with the
  parameter and the car's velocity. For a player's car going over 30
  (VelocityMagnitude, retail CarState+900), on loops where
  `(WorldLoopCounter + 3) & 3` is 0, the replay hears of it:
  RegisterInterestingEvent(2, "FlattenFern").
- **a driving line**: for a player's car whose race direction matches the
  trigger's, going over 40 and not the wrong way:
  Player::TriggerVisibleDrivingLine(line, seconds).
- **anything else**: taken off the queue at once.

The bush and line events stay on the queue for emProcessAllEvents.

TriggerVisibleDrivingLine makes a 108-byte VisibleDrivingLine (bMalloc,
pool 16) for 5 seconds when the parameter's seconds are 0, but only when:

- TheRaceParameters.TrainingLinesEnabled is set,
- the race coordinator's state is RACE_IN_PROGRESS, and
- the player has no line yet.

Every race setup in retail clears TrainingLinesEnabled, and no menu sets
it, so no line is ever shown. The line's class is not ported. Its
constructor is a seam (`gVisibleDrivingLineCtorFn`), and while that is
NULL nothing is made.

## The fern shakers

A FernShaker (28 bytes, a 32-slot pool in pool 16) is a bush being shaken:

| off | field | |
|---:|---|---|
| 0 | `Node` | on FernShakerList |
| 8 | `SceneryCode` | the trigger's parameter |
| 12 | `StartTime` | WorldTimeFrames of its last start |
| 16 | `pSceneryInstance` | |
| 20 | `pWorldObject` | the bush, drawn as an object |
| 24 | `pFernShakerInfo` | its leaves |

InitFernShakers, called from the World's constructor, makes the pool and
two FernShakerInfos, BUSHSHAKE_A and BUSHSHAKE_B. They are a new[]: the
bMalloc block holds the count, and the table starts 16 bytes on. Each info
names a rigid animation and an emitter group, and keeps the group's
emitters (afxGetEmitters). CloseFernShakers destroys the infos last
first, frees the block, flushes the shakers and deletes the pool.
World::DoSnapshot flushes them on a restore.

ShakeFern(code, velocity) (`0x001da270`):

1. Drops every shaker whose age, `WorldTimeFrames - StartTime` as a signed
   number, is 241 or more. Its instance is shown again and its
   WorldObject deleted.
2. Finds the code's shaker. If there is none and the pool is not full, it
   makes one on the list's tail (FernShaker's constructor, `0x001d9b68`):
   - the section's header (ScenerySectionHeaderTable),
   - the instance,
   - the instance's info's LOD 0 model, which must have a rigid animation,
   - a WorldObject of that model at the instance's place: rotation rows in
     units of 2^-14, w 0; the position with w 1; unlit, from
     WorldObjectSlotPool,
   - the instance hidden (ExcludeFlags bit `0x10`),
   - the first info whose animation is the model's.

   Any part missing leaves the shaker empty, and an empty shaker does
   nothing.
3. Shakes it (`0x001d9e08`). The speed is `sqrtf((x x + y y) + z z) *
   2.23`, in mph, and nothing happens at 5 or under. An animation that
   is not playing starts now, from its middle frame
   (`trunc(NumFrames * 0.5)`) over 30 mph and from frame 0 otherwise, and
   the shaker's StartTime restarts with it. The shake is
   `(speed - 5) * 0.04`, held to 0..1. Each of the info's emitters is put
   at the instance, given the velocity (w 0) and fired on WorldEffects
   with minus the shake and no car.

So a bush stays shaken for 4 s after the shake that last started its
animation. A car still in it after that starts it again.

InitFernFlatteners, ServiceFernFlatteners and FlattenFern are empty in
retail and are not ported.

## The rigid animation's timing

eModel's RigidAnimationStartTime (16 bits) packs these:

- the start, in WorldTimeFrames, in the low 14 bits;
- bit `0x4000`, which loops the animation;
- bit `0x8000`, which marks the start as set, so a field of 0 is an
  animation not started.

GetRigidAnimationTime (`0x0010dae8`):

- returns -1 for 0;
- otherwise takes the frames since the start mod `0x4000`, and the
  animation's length, `NumFrames * FrameRateScale` (both read signed);
- for a looping animation returns that time mod the length, and for any
  other returns the time while it is under the length and -1 after.

SetRigidAnimationFrameNumber(frame) (`0x0010c910`) sets the start to
`WorldTimeFrames - 2 frame` (low 14 bits) with bit `0x8000` and not
`0x4000`. It counts two to a frame whatever the scale.

## What the port leaves out

- **The bush's animation.** No renderer code reads RigidAnimationStartTime,
  so no rigid animation plays: a shaken bush's WorldObject stands still at
  the instance's place while its leaves fly. That is TASKS 76.
- **VisibleDrivingLine**, which retail never shows (above).

## The check

`tools/eventmgr_check.py` runs retail's functions in mipsemu
(`retail_model.RetailEmu`, IEEE rounding) and the port's in a host harness
(`tools/src/eventmgr_test.c`). Each side builds the same chunks, scenery
sections, models and cars in its own layout, so records are named by chunk
and index, not by address. Every stub prints its arguments. After every
op, both sides print the queue, the handler list, the pack lists, the pool
counts, the shakers, the infos and the emitters.

There are four scenarios:

- **queue**: handlers, locks (one below zero), events added while locked,
  handlers that remove themselves or others, add handlers, run once, and a
  full 60-event pool.
- **triggers**: packs with the children out of order, a second header,
  children nobody takes, a version 2 pack, packs missing one part, no
  leaf and a parent node, a distance of exactly the radius and NaNs, five
  packs of ten against the 40 cap and the pool, and a point 2 ulp outside
  a sphere that the other summation order would put inside. Unloads come
  at the end.
- **ferns**: exactly 5 mph, a velocity whose speed changes with the
  summation order, ages 240 and 241, the clock wrapping and going back, a
  full pool, the flush and close, and a grid over the animation times.
- **cars**: Car::TriggerEvents over the event kinds, player or none, 30
  and 40 exactly, the directions, the training-line tests, and the replay
  manager.

On retail's image: 4 scenarios, 1090 ops, 11687 lines, 404 events
handled, 237 emitters fired, 0 differ. The mutation pass (`--mutate`)
makes 134 changes to the four port files: 132 caught, and 2 equivalent:
- `shake-30-inclusive`: no float speed times 2.23 is exactly 30 (13.452914
  gives 29.999998 and the next float 30.000002);
- `shake-not-floored`: only speeds over 5 get that far, so the shake is
  never below 0.
