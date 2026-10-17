# Munitions: what the helicopter drops and fires

Slice 12k-6 (TASKS 39, 2026-10-12). The armed helicopter's rockets, its
smoke bombs (the plain exploding barrels) and its dropped spikes (barrels
that lay a spike belt), and FireSalvo, which launches them.

| Object | Retail (SLES_507.31) | Port |
|--------|----------------------|------|
| `Munition.obj` | 0x001be4b8 .. 0x001bfea0 | `munition.{c,h}` |
| `Chopper::FireSalvo` and its helpers | 0x001ea8c0 .. 0x001ead3c | `chopperfire.c` |
| Munition's tables, main / system | 0x002b7120 / 0x002b7100 | `munition_install_vtables` |
| DroppedBomb's | 0x002b7020 / 0x002b7000 | the same |
| SmokeBomb's | 0x002b6f20 / 0x002b6f00 | the same |
| DroppedSpikes' | 0x002b6e20 / 0x002b6e00 | the same |
| Rocket's | 0x002b6d20 / 0x002b6d00 | the same |
| The three ExplodeParams | 0x003143d8, 0x003143f8, 0x00314418 | `munition.c` |

Before this, a bombing run counted its salvos and fired nothing: the
helicopter flew its run over the car and nothing came out of it.

## The classes

Every munition is a Smokeable (`smokeable.md`) with one more word,
BackupDone, and comes from a pool of its own.

| Class | Size | Pool | Smoke type | Info, model |
|-------|------|------|------------|-------------|
| Rocket | 1168 | RocketSlotPool, 3 | ST_ROCKET (1) | `CS_Rocket`, `ROCKET` |
| SmokeBomb | 1152 | SmokeBombSlotPool, 14 | ST_SMOKEBOMB (2) | `CS_SMOKEBOMB`, `SMOKEBOMB` |
| DroppedSpikes | 1168 | DroppedSpikesSlotPool, 8 | ST_DROPPED_SPIKES (3) | `CS_SMOKEBOMB`, `SMOKEBOMB` |

The spikes look like a smoke bomb. Every pool grows, so a launch always
makes its munition. The extra fields:

- **Munition +1136, BackupDone.** Backup (slot 72) sets it. Move reads it
  and clears it: a step that was backed up does not go off.
- **DroppedSpikes +1152, DeploySpikes.** Set by any impulse on the
  spikes (ConsiderImpulse and ApplyImpulse, slots 120 and 128). The
  impulse is taken whole and never applied, so the spikes stop where they
  land.
- **Rocket +1152, Target** (cleared when it is struck) **and +1156, Yaw**
  (degrees). The demo's Rocket had a RocketSound as well; retail's has
  none.

InitMunitions (0x001be638), which the world calls as it is made
(`gInitMunitionsFn`), makes MunitionEffectsHandler, then for SmokeBomb,
Rocket and DroppedSpikes in turn the pool, the creator on
SmokeableCreators, and a copy of WorldEffects' auto emitters of the
class's explosion group: `SMOKEBOMBEXPLD` for the smoke bomb,
`ROCKETEXPLD` for the rocket and the spikes. CloseMunitions (0x001be680)
undoes them in the same order and deletes the handler.

## Launching

FireSalvo (0x001ea8c0) reads the bombing run's row of BombRunBehaviours
(`chopper.c`):

| Row | Type | Ahead | Velocity | Adjust | Salvos | Size | Spread |
|-----|------|-------|----------|--------|--------|------|--------|
| 0 | Rocket | 2.0 | 20 | 0 | 1 | 1 | 0 |
| 1 | SmokeBomb | 2.0 | -10 | 0 | 1 | 8 | 30 |
| 2 | SmokeBomb | 1.5 | -10 | 0 | 2 | 3 | 5 |
| 3 | DroppedSpikes | 2.0 | -10 | 0 | 1 | 1 | 0 |
| 4 | DroppedSpikes | 1.0 | -10 | 0 | 1 | 2 | 4 |

- **A salvo of one rocket** comes from one of four launchers in turn
  (NextLauncher, 0 to 3): 0.06 forward, 1.3 out for launchers 0 and 1 and
  1.62 for 2 and 3, the odd ones to the left, and 1.47 below the
  helicopter. Its velocity is toward the target car at the run's
  Velocity.
- **A salvo of one bomb** comes from 2.3 below, its spread chosen at
  random within the row's.
- **A salvo of n** is laid in a line across the helicopter, from n - 1 to
  one side to n - 1 to the other, 2.3 below, each bomb's spread a step
  along the row's.
- **A bomb's velocity** is Adjust ahead, Velocity down and the spread
  across over the time the fall takes, turned to the helicopter's yaw.

Launch (0x001eab70) registers a replay event, "ChopperFireWeapon", when the
car is a player's and is doing better than 30. LaunchMunition (0x001bea40)
then gives the munition its place and velocity, wakes it, and lights its
anchor emitters. LaunchRocket also sets the rocket's yaw along its
velocity and its target.

## Going off

- **A smoke bomb** goes off at the first collision of a step with a car,
  playing the smokeable crash sound if the collision made none of its own,
  or when its Lifetime runs out.
- **Spikes** go off at the Move after any impulse, which is mostly the
  ground.
- **A rocket** flies itself. It turns toward its target at 90 degrees a
  second, at 30 a second, holding 0.9 above the ground. It goes off when
  anything strikes it, when its target is gone or when its Lifetime runs
  out. Its ConsiderImpulse answers -57575.0 and clears Target.

Going off is OnLifetimeEnd (slot 216). It copies the class's explosion
emitters into MunitionEffectsHandler at the munition's place (a flat
matrix, the identity at its position) and calls ExplodeWarhead. The
handler's DoTimestep, which the helicopter's Fly calls every step, drops
each explosion that has finished. The spikes then lay a spike belt.

### ExplodeWarhead (0x001be778)

| Class | MaxStrength | MinStrength | ArmZAdjust | CoordZAdjust | MinRange | MaxRange | Zone camera |
|-------|-------------|-------------|------------|--------------|----------|----------|-------------|
| SmokeBomb | 25 | 10 | 10 | 5 | 3 | 6 | yes |
| DroppedSpikes | 1 | 0 | 10 | 5 | 2 | 8 | no |
| Rocket | 20 | 20 | 10 | 8 | 0 | 6 | no |

For every car that moves and is within MaxRange of the munition, the
distance taken in x and y only:

1. The strength is MaxStrength within MinRange. Out to MaxRange it falls
   linearly to MinStrength.
2. The push is that strength away from the munition in x and y, with
   CoordZAdjust up for a car with a wheel on the ground. It is applied at
   ArmZAdjust above the car's centre, after the car's body is put into
   physics mode (body slots 112 and 128).
3. **A player's car:**
   - A rocket (MT_BANG_FLASH) in a one-player race starts the glare.
   - A hit harder than 0.8 of MaxStrength wrecks the car through
     CarDamage, gives a real driver a 3.5-second e-brake stop, and, for
     the smoke bomb and a car still racing, asks for the slow-motion zone
     camera.
4. **An AI car** on physics or mellow movement is e-braked for 3.5 seconds
   whatever the strength.

Then the explosion's sound plays at the munition's place.

### The spike belt (MakeSpikeBelt, 0x001bf188)

The spikes lay a belt only on the ground (within 1 of it) and on a racing
route's road. The strip runs across the nearest route point's direction,
2 to either side of where the spikes lie, cut short where the road's edge
is nearer. It goes to the cop manager's AddSpikeStrip with id -1 and 20
seconds.

## Where the helicopter fires them

A chase's ATTACKING state picks the attack (`pursuitchopper.c`):

- a spike belt, when the chase allows it, the car's tyres are whole and
  World::Random says so;
- otherwise a rocket on the same terms, never twice running;
- otherwise a smoke bomb.

The chase's behaviours allow them:

- **The helicopter** (0x20): heat level 4, or a roadblock dodged while
  the cops are following backwards.
- **The second smoke bomb row** (0x40): fewer than 3 roadblocks.
- **Rockets** (0x100, with 0x10): 3 or 4 roadblocks, in a race with the
  helicopter.
- **Spike belts** (0x80): 5 or more roadblocks.
- **Be A Cop's helicopter** (R): all four at once (0x1e0).

No track picks the weapon. The user's note (TASKS 39) says only the
armed helicopter fires missiles, and only on some tracks. What a track
decides is whether a helicopter comes at all, since it needs the track's
heli sheet. It also decides how the helicopter looks: the model is the
track's own `TRACK_HELICOPTER` (`chopper.c`). The weapons come from the
chase above.

## The port

- The seams the image calls directly are function pointers, NULL-guarded:
  - CarDamage's wreck (`gCarDamageWreckFn`). A NULL seam with a CarDamage
    aborts, since it is unported;
  - RealDriver's e-brake stop;
  - Player::RequestZone;
  - the cop manager's AddSpikeStrip;
  - the replay's interesting event.
- Slot 16, DoSnapshot: Munition's, DroppedBomb's and SmokeBomb's tables
  hold Smokeable's (TASKS 72d-2, [replay.md](replay.md)). DroppedSpikes'
  (0x001bef90) and Rocket's (0x001bf910) own are TASKS 72e's and NULL
  until then.
- Retail's Fly calls the handler's DoTimestep unguarded. The port's
  `munition_effects_do_timestep` does nothing when there is no handler.
- Rocket::Move passes the velocity it wrote through GetVelocity's pointer
  to RigidBody::SetState, which multiplies it by the mass. The image also
  computes velocity × mass into the stack and never reads it. The port
  leaves that out.
- DoTweakerTriggers' bomb launch is the tweaker's (debug only) and is not
  ported.
- With `DebugLog 1`, each race log line also gives the run, its salvos,
  the munitions in flight (and the most at once) and the explosions
  playing.

## The checker

`tools/munition_check.py` runs retail's image through `retail_model`, and
`tools/src/munition_test.c` runs the port; the two logs must match. Both
are built on the smokeables' checker: the harness includes
`smokeable_test.c` whole, with its pools and bMalloc renamed so the
munitions' three pools and the handler's block are its own and the rest
go on to the smokeables'. mutpar's snapshot now copies a `.c` file a
source includes from beside it, so the pass builds the pair.

The script covers:
- the module's init and close, twice; the creators; the three classes'
  tables, as a vtable dump;
- making each kind, then launching it, or a rocket at a target;
- ExplodeWarhead over nine cars: the hard and soft hits, exactly at and
  just inside MinRange, exactly at MaxRange, the glare in a one-player
  race, the zone camera, the e-brake on real and AI cars, physics and
  mellow movement, no movement and out of range;
- a smoke bomb's collisions, with and without a sample, and backed up;
- the spikes deployed by an impulse, backed up, and every branch of
  MakeSpikeBelt (no ground, too high, no route point, either side,
  past the edge, on the line, exactly on an edge);
- a rocket backed up, turning against both clamps, climbing against both
  clamps, struck (the -57575 impulse) and running out of time;
- the effects handler's tick and add, and no handler;
- the destructors, the base classes' with both flags, and deletes from
  the physics system.

Results:
- `--dump out/munition`: 262 ops, 1038 lines, 0 differ.
- Mutations: 175 over `munition.c`, all caught, none equivalent.

## Testing them: ForceChopper

A chase reaches the helicopter late, if at all: in a scripted Azahar run
the gas alone rarely makes the heat climb far enough. The port's own
config item `ForceChopper N` (in `nfshp2_config.txt`, off by default)
sends it at once in an R-held (SkipFE) race:

- `main.c`'s `eggIsOn` answers 1 for retail's helicopter egg
  (`EGG_HELICOPTER`, 5) in such a race; the port's eggs are otherwise all
  off. So InitCars makes the helicopter even with no cops, and its word
  at 960 has it follow car 0 by itself (Chopper::DoTweakerTriggers). No
  chase can take it.
- `forceChopperTick`, just before World's step, waits 5 seconds and then
  starts a bombing run (Chopper::AttackCar) each time the helicopter has
  been back in PURSUIT for 4 seconds. N picks the row: 1 rockets, 2 and 3
  the smoke bombs, 4 the spike belt, 5 each in turn.
- With no cops there is no cop manager to take the belt's spike strip
  (`DroppedSpikes::Explode` adds it there), so a belt becomes a smoke
  bomb. `SkipFEMaxCops 1` gives the race a cop, and the manager with it.

What the runs showed (2026-10-12, track 12, gas held):

- `ForceChopper 5`: rocket, smoke bomb, smoke bomb, the belt as a smoke
  bomb, then round again. One rocket at a time; eight smoke bombs at
  once at most. Each went off with the fireball, smoke and flash, and
  one blast threw the car into the air, as in the reference video.
- `ForceChopper 4` with `SkipFEMaxCops 1`: two belts, two spike strips
  on the cop manager's list.
- `ForceChopper 2`, shots every 0.7 seconds: a falling barrel trails
  magenta smoke that turns khaki, then olive, as it spreads. That is
  GLOBALB's data, not a colour fault. `SMOKEBOMBD`'s two emitters
  (`XEM_SmokeBombD_SmkA` and `SmkB`, texture `SMOKE_CS`) have the
  colour keys (80, 45, 45, 0), (55, 0, 25, 250), (195, 180, 110, 250)
  and (130, 130, 55, 0), at 0, 0.5, 2 and 3 seconds, and the draw
  doubles texture times colour. The blast itself
  (`SMOKEBOMBEXPLD`: sparks and `XE_EXPLOSIONA`) is white to yellow.
