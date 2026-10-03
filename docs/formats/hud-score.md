# The race's bonus scores (step 8m-4b)

A bonus score is a line of ScoreInfoTable (`hudrender.h`): a title such
as CLEAN LAP, its id in the language tables, and its points as text,
such as "+2000". When one is earned, its title and points fly in on the
HUD's event texts, and when the points text finishes, HudDoAnimations
adds it to `TotalScore`. This step ports what earns the scores the HUD
hands out itself, the sound, and the animation:

| function | address | size | port |
|----------|---------|------|------|
| PlayScoreSound(eScoring) | `0x00175100` | 212 | `play_score_sound` |
| Player::StartScoreAnimation | `0x0017d370` | 1108 | `player_start_score_animation` |
| Player::GetFinishBonus | `0x0017e2d0` | 128 | `player_get_finish_bonus` |
| Player::StartScore(eScoring) | `0x0017e3b0` | 420 | `player_start_score` |
| Player::StartScore(eScoring, int) | `0x0017e558` | 400 | `player_start_score_value` |
| Player::UpdateScoring | `0x0017e820` | 1228 | `player_update_scoring` |

All of it is in `hudscore.c`. `main.c` binds UpdateHud's two seams:
`gUpdateScoringFn` (UpdateScoring, every frame) and `gStartScoreFn`
(StartScore with a value, for the start bonus).

Retail's StartScore() (`0x0017e6e8`) starts the animation at the default
place without setting any text. Nothing calls it and no data holds its
address, so the port leaves it out. The cops (tCopManager, tPursuit) and
the frontend's points also call StartScore and GetFinishBonus; they will
use these functions when they are ported.

## The scorings

eScoring is ScoreInfoTable's index. Retail keeps no names for it, so
`hudscore.h` names each from the table's English title:

| # | title | # | title |
|---|-------|---|-------|
| 0 | BEAT THE COPS | 15 | START BONUS |
| 1 | RESET CAR | 16–22 | TOOK 1ST to 7TH PLACE |
| 2 | HIT COP CAR | 23 | 1ST PLACE BONUS |
| 3 | CLEAN LAP | 24 | 2ND PLACE BONUS |
| 4 | LED FIRST LAP | 25 | 3RD PLACE BONUS |
| 5 | LED A LAP | 26 | SPEED BUSTED |
| 6 | TOP SPEED | 27 | QUOTA FILLED |
| 7 | CLEAN SEGMENT | 28 | BLEW THE TIRES |
| 8–10 | DODGE ROADBLOCK, SMASH ROADBLOCK, SMACK | 29 | BLEW YOUR TIRES |
| 11–14 | AIR, BIG AIR, HUGE AIR, DRIFT | | |

## PlayScoreSound

Plays the in-game sample "ScorePoints" at volume 1 for four scorings
only: BEAT THE COPS, TOOK 1ST PLACE, TOP SPEED and QUOTA FILLED. It plays
nothing when:

- `SoundEnabled` (gp−23056) is 0;
- the race coordinator is in INSTANT_REPLAY (4), AUTO_REPLAY (5) or
  POSTRACE (7), or in a replay demo;
- the sample is missing, or already playing.

Retail reads `pRaceCoordinator` without a test. The port plays nothing
when there is none.

## StartScoreAnimation

Takes the place, two moves, the scale and its change, and the colour and
its change. Retail passes all seven by value, so the copies can change:

1. **Two players.** With `PlayerNumPlayers` ≥ 2, the y of the place and
   of both moves is halved. Then the place moves down 40 for player 0 or
   280 for player 1. Any other player number keeps the full-screen
   numbers.
2. **The points (slot 10).** The slot's animator is made if it is
   missing. If it is still running, `strPrevScore` is added to the total
   first, so points never go missing. Then the scored text starts on
   `pFlailerEventScore` (Player +1148).
3. **The title (slot 11).** `strPrevScore` becomes `strEventScore`, for
   the next score to add. The place moves up 20, and the same scored text
   starts on `pFlailerEventTitle` (+1144).
4. `tScoreAnimation` (+2732) is stamped with `WorldTimer`.

Both texts use HudAnimator's scored start (`hud-anim.md`) with these
settings:

| setting | value |
|---------|-------|
| alpha | 0, rising by 128 |
| second alpha | 64, falling by 64 |
| scale | as given in all three phases |
| colour | the colour and its change, in both colour pairs |
| durations | 0.5, 0.5 and 1 second |
| timer | WorldTimer |
| string | none: the text keeps the caller's |

## StartScore

Both StartScores play the sound, set the title, and start the animation
at the default place:

| | value |
|-|-------|
| place | (530, 236) |
| first move | none |
| second move | (90, −100) |
| scale | 0.7, unchanged |
| colour | (128, 64, 0), changing by (0, 64, 128) |

- **StartScore(e)** prints the entry's points into `strEventScore` and
  its translated title into `strEventTitle`.
- **StartScore(e, value)** prints only the title. The caller has already
  put the points in `strEventScore`, and `value` is not read.

The colours' fourth lanes are left as the stack held them. Nothing draws
them; the port uses 0.

Retail prints both strings with the string as bSPrintf's format,
unbounded. The port prints them with `"%s"`, bounded to 32 bytes. No
title or points text in any of the six languages holds a `%`. The longest
title is Italian's HIT COP CAR, at 31 characters. So the two are the
same.

## GetFinishBonus

Places 1, 2 and 3 return the 1ST, 2ND and 3RD PLACE BONUS points as a
number (10000, 5000, 2500), through ConvertScoreString. Any other place
returns 0.

## UpdateScoring

Runs once a frame for each player, from UpdateHud, in this order.

**A blink.** If the car is blinking (being reset), `HangTime` is cleared,
`bResetGlare` is set, and nothing else happens this frame.

**A lap's end.** The racing car (`Race::GetRacingCar`) must exist, have
no FinishReason (int16 at +18), and have `CrossedFinishLine` (int8 at
+13) set. Then:

- **A segment.** This applies in a point-to-point race, or in a time
  trial (RaceType 2) with a valid target time (`TimeTrialTime`, neither 0
  nor 0x7fffffff) when not the cop. CLEAN SEGMENT is scored unless
  `bSegmentCollisionDetected` (+2624) is set, and that flag is cleared.
- **A lap**, otherwise. With no knock this lap (`bCollisionDetected`,
  +2544), CLEAN LAP is scored and `numCleanLaps` (+2688) counts it.
  Otherwise, in first place, LED FIRST LAP is scored on lap 1 and LED A
  LAP after it. Otherwise, with no knock this segment and a lap done,
  CLEAN SEGMENT is scored. Both flags are then cleared.

**A top speed.** If `bNewTopSpeed` (+1636) is set, TOP SPEED is scored.
UpdateScoring leaves the flag set.

**A knock.** The car body's first collision this frame
(`CollisionBody::GetCollision(0)`) counts as a knock when all of these
hold:

- One of its two bodies is this player's car. When both are, the second
  wins. If neither is, `bSmokeableHit` (+2548) is cleared and nothing
  else happens.
- The other body's inverse mass, from its vtable's GetMassInverse, is
  below 500. Both masses are asked for, the first body's first.
- The car is on the ground: `HangTime` is 0.
- The impulse's direction (Collision +96) against the car's up (row 2 of
  its body matrix) is between −0.8 and 0.8, and not 0. This is a dot of
  three lanes, added as `(x·x + y·y) + z·z`, as the VU's `vmul`,
  `vaddy`, `vaddz` do. A NaN fails.
- `TotalImpulseMagnitude` (+80) is above 8.3333 (`0x41055532`).

A knock sets `bCollisionDetected` and `bSegmentCollisionDetected`, and
clears the word at +2540. If a smokeable is in the collision,
`bSmokeableHit` is set; otherwise it is cleared.

**Air.** With no wheel on the ground, `HangTime` gets the clock in
seconds (`WorldTimer` × 0.00025) unless it already holds a take-off. On
the ground with no take-off, `HangTime` is written 0 again, which turns
a −0 into 0. On landing:

1. The air is `(now − HangTime) × 250`, truncated as the EE does: past
   the int's range it saturates.
2. It is rounded down to a step of 50, toward 0.
3. Each band below that holds it prints "+air" into `strEventScore` and
   scores with StartScore(e, air). The bands are tested as retail does,
   unsigned, so a negative air is in none.
4. `HangTime` is cleared.

| band | scoring |
|------|---------|
| 100 to 199 | AIR |
| 200 to 349 | BIG AIR |
| 350 and over | HUGE AIR |

**A place taken.** If `PositionFlag` (+1520) is above 0, the race
position in `LastRacePosition` (+1620) is looked up in `baPlaceReached`
(+2628). If that place has not been scored before and the player is not
the cop, place + 15 is scored (TOOK 1ST PLACE for place 1) and the place
is marked. `PositionFlag` is then cleared, whatever its value.

Place 8 scores 23, the 1ST PLACE BONUS, because the table stops at TOOK
7TH PLACE. A race of eight cannot take eighth, so this never shows.

## Where the port differs

- **No race coordinator.** PlayScoreSound plays nothing, where retail
  would read through NULL.
- **Places outside 1 to 8.** Retail reads `baPlaceReached[place − 1]`
  with no bounds. The port reaches the same word for places −1 to 14:
  - −1 is `LastCrossingTime`;
  - 0 is `bSegmentCollisionDetected`;
  - 9 is `bShownMusicTitle`;
  - 10 to 14 run up to `fInitialPursuitY`.

  These are all plain words on both the EE and ARM. A place below −1
  would reach `lastCar`, a pointer. A place above 14 would read its
  score from past the end of ScoreInfoTable. The port skips both. A race
  never sets such a place.
- **The strings** are bounded, as above.

The checker shows none of these.

## The checker

**`tools/hudscore_check.py`** runs each retail function above in the
emulator, against the port in the harness `tools/src/hudscore_test.c`.
Underneath are hudanim's checker, its animators and the Flailer runtime
on INGAMEB's Flailer chunk.

**The stubs.** The HUD does not own these callees, so both sides script
them the same way and log each call:

- GetRacingCar and IsBlinking;
- GetCollision, logged with the body it is asked about;
- GetInGameSample, IsPlaying and Play;
- GetTranslatedString, which returns "TITLE" and the id;
- each body's GetMassInverse, through a fake vtable of its own.

The harness's GetCollidingCars and IsSmokeableInvolved are
`collision.c`'s, which `collision_check.py` checks.

**What is compared.** The stubs' logs, GetFinishBonus's answers, and,
after each op, every line that changed:

- hudanim's lines: both Players' twenty slots, `TotalScore` and the
  Flailer objects;
- each Player's scoring fields and three strings;
- the words places −1 to 14 reach;
- `bResetGlare`.

StartScore leaves the colours' fourth lanes as the stack held them, so
both sides show the animators' `Colour3.w` and `DeltaColour3.w` as
`eeeeeeee`.

**The script** covers:

- **The sound** in every coordinator state and for every scoring. Also
  with the sound off, and with the sample missing or busy.
- **Every finish bonus.**
- **The animation** for one player, for each half of two, and for a
  player number of neither. Also started over a score still flying.
- **StartScore** over the table, back to back, and for two players;
  StartScore(e, value) for scorings with and without the sound.
- **UpdateScoring:**
  - a blinking car;
  - every way a lap and a segment end: time trials with and without a
    target, as the cop, point to point, not crossed, finished, no racing
    car, and leading with no lap or fewer done;
  - the top speed;
  - knocks of every pairing of player, stranger and smokeable, with
    both bodies the player's car, and on each side of every limit: mass,
    hang time, the level both ways, a zero dot, a dot that is 0 only
    when added in the other order, NaN, infinity, and the impulse's last
    bit;
  - take-offs and landings across each air band, landings before the
    take-off and past the int's range, −0, and a negative clock;
  - places taken, again, as the cop, and from −1 to 14;
  - all of it in one frame on two players.

The result is 1608 ops, 6184 lines, and 0 differences.

The mutation pass makes 150 mutations, and all 150 are caught.

The first pass had 4 survivors, all of them gaps in the script:

- `scorev-no-sound`: StartScore(e, value) was only run for scorings
  with no sound. It now runs for TOP SPEED and BEAT THE COPS too.
- `led-first`: no first place was taken with 0 laps or fewer done.
- `knock-which-order`: no knock had both bodies on the player's car,
  which is the only case where the order of the two tests matters.
- `knock-dot-order`: every scripted dot added up the same either way.
  The script now has 1e8 − 1e8 + 0.5, which is 0.5 left to right and 0
  the other way.

With the gaps filled, those 4 and `scorev-prints-score` were run again,
and all 5 are caught. `scorev-prints-score` had been listed as
equivalent, but it is caught because the script's StartScore(13, −7)
prints a value other than the one already in the string.
