# The HUD's cop parts (step 8m-4c-1)

Three of the HUD's parts follow the cops: the radar detector's row of
lights and its beep, the trackers drawn over the cars near the player,
and the pursuit meter with its tickets. UpdateHud (`hudrender.c`) calls
each through a seam, and this step fills them:

| function | address | size | port |
|----------|---------|------|------|
| Player::UpdateRadarDetector | `0x0017be70` | 1032 | `player_update_radar_detector` |
| Player::DrawTracker(Car *, int) | `0x0017c278` | 264 | `player_draw_tracker` |
| Player::UpdatePursuitMeter(int) | `0x0017c380` | 1092 | `player_update_pursuit_meter` |

All three are in `hudcop.c`. `main.c` binds `gUpdateRadarDetectorFn`,
`gDrawTrackerFn` and `gUpdatePursuitMeterFn`. UpdateHud calls them:

- the pursuit meter with tCopManager's HUD pursuit level, when the HUD
  shows a pursuit;
- the radar detector, when the HUD shows the radar;
- DrawTracker for each AI car and cop it draws, in a race that is
  racing.

The radar asks tCopManager::GetRadarDetectorIntensity (`0x002274a8`) how
near the nearest cop is. That walks the cops and the track path; it is
copmgr.c's (12n), bound to the seam
`gCopManagerGetRadarDetectorIntensityFn` in main.c and checked on
retail's image by tools/copmanager_check.py. The cops that count are
a player's, and the AI's at a speed trap, a roadblock, on patrol, with
a caught speeder or guarding a spot (not those chasing or in limbo).
The nearest under 250 m in the plane, in front (IsCarInFront, a
quarter turn either side) and within 250 along the track gives
(250 - distance) * 0.004, so a cop 250 m off lights nothing and one
just ahead lights the lot; its flag is 1 for a roadblock's cop, which
turns the lights to RadarColours' yellow rows. With no cop near the
answer is 0, every light unlit, no beep.

The Player fields are:

| field | offset | |
|-------|--------|-|
| `MyCar` | +4 | |
| `pFlailerPursuitStar` | +1072 | the meter's star |
| `pFlailerPursuitLevel[4]` | +1076 | the bars |
| `pFlailerPursuitX[3]` | +1092 | the tickets |
| `PrevPursuitLevel` | +1104 | |
| `pFlailerTracker[7]` | +1112 | |
| `pFlailerRadarLight[12]` | +1176 | |
| `pRadarBeep` | +1404 | the beep's sample |
| `RadarTimer` | +1408 | a Timer, in ticks of 0.25 ms |
| `PursuitObjectPos[4]` | +2484 | each bar's place, read from the bundle |

## UpdateRadarDetector

**The lights.** The intensity is 0 to 1, from the cop manager, which
also writes a flag for the kind of cop. The intensity times 11, truncated
as the EE does, is the number of lights lit, at most 10. A negative or
NaN intensity lights none, and an infinite one lights ten.

RadarColours (`0x002fbb30`) has four rows of twelve ABGR colours: lit,
unlit, and then lit and unlit again for a flagged cop. Each row runs five
green, three amber and four red:

| row | green | amber | red |
|-----|-------|-------|-----|
| 0, lit | `ff008800` | `ff004488` | `ff000088` |
| 1, unlit | `80004000` | `80002240` | `80000040` |
| 2, lit, flagged | `ff008888` | `ff004488` | `ff000088` |
| 3, unlit, flagged | `80004040` | `80002240` | `80000040` |

Any flag but 0 picks rows 2 and 3. The lights below the count take the
lit row's colour and the rest the unlit row's, all twelve each frame.
Lights 10 and 11 are never lit by the count; they are the swells.

**The swells.**

- At 9 lights or more, light 10 swells off light 8 in animation slot 16.
- At 10, light 11 swells off light 9 in slot 17.
- Below those, each is hidden.

A swell is a bitmap animation from the other light's top left to 10 up
and 10 left of it, scale 1 to 2, alpha 128 to 0, over 0.2 seconds on
WorldTimer, not kept. It is started every frame, but a bitmap start
leaves a running animator be (`hud-anim.md`), so while the lights stay
up the light pulses: it swells, is hidden at the end, and starts again
the next frame.

**The beep.** With the sound off (`SoundEnabled`, gp−23056) or no light
lit, `RadarTimer` is set to 0 and nothing else happens. Otherwise:

1. The frame's time, `WorldTimeElapsed` (gp−19560), is made a Timer with
   Timer::SetTime, `(int)(t × 4000 + 0.5)` ticks, and added to
   `RadarTimer`.
2. If `lit × −0.038333334 + 0.5` is below the timer as a signed int
   times 0.00025, `RadarTimer` goes back to 0 and the beep plays at
   volume 1, with 0 for its other two floats.

So one light beeps every 0.46 seconds and ten every 0.12. The test is
`<`. The two are equal only for 9 lights at 620 ticks, which does not
beep.

## DrawTracker

Draws tracker `index` over car `c`:

1. **The distance** from `c` to the player's car, as the VU adds it:
   `(dx·dx + dy·dy) + dz·dz`, then the square root. Over 50, or NaN, and
   nothing is drawn.
2. **The turn**, `c`'s `fAngleToCamera` (Car +2192). Below −0.5 or above
   0.5 and nothing is drawn. A NaN passes. DamageAbove writes it as the
   last frame's views draw the car, and the mirror draws last, so with
   the mirror up a car behind the player has the mirror's angle and gets
   a tracker ([car-damage](car-damage.md), "The marker over the car").
3. **The tracker** is placed at x = `trunc((turn + 0.5) × 400) + 120`,
   which is 120 to 520. Its y is left as it is.
4. **The scale** is `1 − d × 0.02`, so 1 near and 0 at 50, doubled into
   both ScaleX and ScaleY. The tracker is shown.

The scale is capped at 1 before it is taken from 1, but by then the
distance is at most 50, and 50 × 0.02 rounds to 1 exactly, so the cap
never acts.

## UpdatePursuitMeter

Does nothing without the pursuit star. Then:

**The tickets.** The player's car's ticket count from
tCopManager::GetNumTickets, as 3 when it is 4 or more, or 0 in a free run
(a single race with no laps, not as the cop). That many of the three X's
are shown and the rest hidden. A negative count hides all three.

**The bars**, only when `level` is not `PrevPursuitLevel`. The meter's
bars are 0 to 3, and bar `i` animates in slot `i + 2`.

- **Going up**, each bar from the old level up to below the new one
  flies in. It goes from 300 left of its place to `300 + that`, scale 4
  to 1, alpha 0 to 128, over 1.5 seconds, kept. The y is `0 + y`, which
  turns a −0 into 0, but the animator keeps only the change, which is +0
  either way.
- **Going down**, each bar from one below the old level down to one
  below the new one flies out. That is one bar more than the meter
  loses, and bar 0 for a new level of 0 or 1. It goes from its place to
  50 up (bars 0 and 2) or 50 down (bars 1 and 3), from the table at
  `0x002b3f20`, at scale 1, alpha 128 to 0, over 1 second, kept.

`PrevPursuitLevel` then takes the level. A bar whose slot is still
running keeps its old animation, so a level that changes faster than
the bars fly leaves them where the first change sent them.

## Where the port differs

- **No cop manager.** The radar reads 0 and the meter shows no tickets.
  Retail reads through `pCopManager` unchecked.
- **The flag starts at 0.** GetRadarDetectorIntensity writes the flag
  with `sw` only when a cop is in range. Retail's flag is otherwise
  whatever the stack held.
- **Missing objects.** Retail itself skips a radar light the bundle
  lacks when it colours the lights, and does nothing without the pursuit
  star. The port also skips, where retail reads or writes through them:
  - light 10 or 11 when hiding it;
  - a swell off a missing light 8 or 9;
  - a missing X or tracker;
  - the beep with no sample.
- **Levels over 4.** Retail bounds neither loop. A level over 4 would
  read PursuitOut and the bars past their ends, into the stack and the
  next fields. The port keeps to bars 0 to 3. tCopManager gives levels 0
  to 4, so this never shows.

The checker shows none of these.

## The checker

**`tools/hudcop_check.py`** runs the three retail functions in the
emulator, against the port in the harness `tools/src/hudcop_test.c`.
Underneath are hudanim's checker, its animators and the Flailer runtime
on INGAMEB's Flailer chunk. Both sides run tCopManager::GetNumTickets,
RaceParameters::IsFreeRun and Timer::SetTime as they are.

**The stubs.** The HUD does not own these callees, so both sides script
them the same way and log each call:

- GetRadarDetectorIntensity, logged with the manager, the car, the
  answer and the flag. The stub always writes the flag.
- bSample::Play, logged with the sample and its three floats.

**What is compared.** The stubs' logs and, after each op, every line
that changed: hudanim's (both Players' twenty slots, `TotalScore` and
every Flailer object), and each Player's `RadarTimer` and
`PrevPursuitLevel`.

**The script** covers:

- **The radar** over every count of lights, each side of each step,
  negative and huge intensities, −0, NaN and the infinities. Also every
  kind of flag (0, 1, 2, −1, `0x100`) at five lights and at ten, the
  swells as they run with lights 8 and 9 moved, a light that is missing,
  and player 1.
- **The beep** at 1, 5, 9 and 10 lights, a frame at a time past two
  beeps. Also with the sound off and no lights; steps of 0, negative,
  a second, huge and tiny; the timer past the int's range; and the one
  equal case.
- **The trackers** on each side of the range along each axis and on the
  slant, at distances where the order of the adds shows, at a NaN and an
  infinite place, and on each side of each turn limit with NaN and the
  infinities. Also every tracker, the player's own car, and player 1.
- **The pursuit meter** over ticket counts 0 to 5, 127 and the negatives;
  a free run and the races that are not; another car's tickets; every
  level to every other, 0 to 4, with the animations run between; changes
  faster than the animations; a level set from outside; no star; and
  player 1, with a bar at y = −0.

The result is 1187 ops, 4763 lines, and 0 differences.

The mutation pass makes 120 mutations. 115 are caught, and 5 are
equivalent:

- `tracker-no-cap`: the distance is at most 50 by the time of the cap,
  and 50 × 0.02 rounds to exactly 1.
- `meter-same-level`: at an unchanged level neither loop runs, and
  `PrevPursuitLevel` is given the value it already holds.
- `swell-real-timer`: the bitmap's HudStartAnimation drops its timer
  argument; the animator reads WorldTimer itself.
- `in-to-y` and `out-to-x`: the animator keeps `to − from`, and
  `(0 + y) − y` is `y − y` for every y, −0 included. PursuitOut's x are
  all 0.

The first pass had 1 survivor that was a gap in the script:
`tracker-dist-order`. Adding the three squares in the other order is off
by one bit at most, and none of the scripted distances showed it. Two
places found by search, where it changes the scale's last bit, are now
in the script, and the mutation is caught.
