# AIDriver: the racer's controller

`AIDriver.obj` (0x0012ffc8 .. 0x001308a0; the demo's starts at 0x0012e810)
and `_vt$8AIDriver` (0x002ae328; the demo's 0x00291fa8). This is step
11f-2. SetControlMode builds one for a car under `AI_CONTROL`, which is
every AI racer AddRacingCar puts on the grid.

Ported to `3DS Files/source/aidriver.{c,h}`; DoSnapshot (0x00130108)
came with the replay, TASKS 72c: the AICarController's, the car not to
avoid by its driver number, both timers and the stuck Average.
`tools/aisnap_check.py` checks it. Cross-checked by
`tools/aidriver_check.py` against `tools/src/aidriver_test.c`, with the
image as the oracle.

An AIDriver is an AICarController (see
[ai-car-controller](ai-car-controller.md)) with a PsychoDriver (see
[psycho-driver](psycho-driver.md)) for its driver. It adds three things:

- **ChooseNewAction**, which AICarController's Think and InterruptAction
  ask through the table. It scores the actions in a fixed order and makes
  the first one worth having. AICarController's own is `jr ra`.
- **A car it has decided not to avoid** (ShouldWeAvoidThisCar). Once the
  skill's dice say no, it leaves that car alone for a second.
- **A five-sample average of its progress**, recorded every 1.5 s. A car
  that is off the road with too little progress is held in GetUnstuck for
  at least 1.6 s.

## The record, 736 bytes

AICarController's 720 (see [ai-car-controller](ai-car-controller.md)),
then the demo stab's four fields (type#1382, which had them at 704 to
716):

| Off | Field | Type |
|----:|-------|------|
| 720 | CarToPurposefullyNotAvoid | Car *, NULL for none |
| 724 | StartTimeForPurposefullyNotAvoidingCar | Timer, when that car was chosen |
| 728 | VeryStuckProgressTimer | Timer, counting down to the next sample |
| 732 | pVeryStuckProgress | Average *, "Very Stuck Progress Average", 5 slots |

**Retail's SetControlMode (0x00131410) bMallocs 736** for AIDriver and for
TrafficDriver. The demo's asks 720, and `carmode_check` runs the demo's,
so its malloc hook maps `sizeof(AIDriver)` back to 720, as it does for
RealController and BeltMover. `carmodes.h`'s AIDRIVER_SIZE is
`sizeof(AIDriver)`.

On the host the four fields sit later, past AICarController's wider
record. The header's layout check holds only for a 4-byte pointer.

## The table

`_vt$8AIDriver` has seventeen entries, the header included. AIDriver's
own slots:

| Slot | Address | Method |
|-----:|---------|--------|
| 8 | 0x00130090 | destructor |
| 24 | 0x00130108 | DoSnapshot (TASKS 72c) |
| 32 | 0x00130188 | Think |
| 112 | 0x00130890 | GetRouteNumbersToUse |
| 120 | 0x00130238 | ChooseNewAction |

Every other slot is AICarController's, in the same place as in
`aicarcontroller_vt`. Slot 64 is GetAmountOutOfBounds (0x001907b8), which
ChooseNewAction calls through the table.

## The constructor (0x0012ffc8)

1. AICarController's constructor (0x00190140) on the car.
2. The two Timers' constructors: 724 and 728 are zeroed. Then the vptr.
3. `bMalloc(624, "PsychoDriver", 0, 16)`, and PsychoDriver's constructor
   (0x00139760) on it and the car.
4. CurrentAction (532), 720 and 724 are zeroed again, and the PsychoDriver
   goes into the controller's Driver (4).
5. `bMalloc(16, "Very Stuck Progress Average", 0, 16)`, Average's
   constructor with 5 slots, into 732.
6. 728 is set to `cvt.w.s(6000.5f)` (gp-32044): 6000 ticks, what
   `timer_set_time(1.5f)` stores.
7. Car::SetFrictionBoost (0x001315f8) with AIDriverFrictionBoost
   (gp-23008, 1.0).

`aidriver_construct` is `gAIDriverCtorFn`'s shape, (memory, car), and
main.c sets the seam at boot.

## The destructor (0x00130090)

1. The vptr.
2. The driver, when there is one, through its own table (vptr at 556,
   slot 8) with flags 3.
3. The Average, when there is one, with flags 3.
4. A jump to ~AICarController (0x001903a0) with the caller's flags.

Neither pointer is cleared; nothing reads them again.

## Think (0x00130188)

1. SetFrictionBoost(car, AIDriverFrictionBoost), every think.
2. When 728 is running (not 0 and not 0x7fffffff) and Timer::CountDown(dt)
   answers 0 (it has run out):
   - 728 goes back to 6000 ticks;
   - the Average records `TheTrackPathManager.TrackLength` (0x0031bc38)
     times `|dCurrentLapNumberExact|` of the car's RacingCar (car+28,
     +24): the metres a second it is making along the track.
3. A `j` to AICarController::Think (0x00191148), not through the table.

A timer that is 0 or 0x7fffffff is never counted down and never records.
The constructor's 6000 is the only way in.

## GetRouteNumbersToUse (0x00130890)

`*first = 0` and `*last = 49`. AICarController's slot is pure; AIDriver
and TrafficDriver (50 to 59 or 60 to 69, see
[traffic-driver](traffic-driver.md)) each fill it.

## ShouldWeAvoidThisCar (0x001307b0)

Takes (car, float). **The float is not read.**

1. If a second or more has passed since 724 (`1.0 <= (float)(int)(WorldTimer
   - [724]) * 0.00025`, gp-32020), 720 is cleared.
2. If the car is 720, the answer is 0. **A NULL car meets a NULL 720**, so
   with nothing set aside a NULL car is not avoided and draws nothing.
3. `r = World::Random(pCurrentWorld, 1.0)` (0x0014e548).
4. The skill is the driver's SkillLevel (`lb 3` of car->MyDriver, car+20).
   An `xor` and a `movz` read -2 as 0; any other value is used as it is,
   with no clamp.
5. If `r < TheDifficultyInfo.AISkillLevel[skill].CollisionAvoidanceChance`
   (0x002f0080 + 380 + 28 x skill), the answer is 1.
6. Otherwise the car goes into 720, WorldTimer into 724, and the answer
   is 0.

So a car the dice spare is spared for a second; any other car is drawn for
afresh each time.

## ChooseNewAction (0x00130238)

Takes (AIAction **out, AIActionType type). Every `new` here is bOMalloc
(0x00257c80) on AIActionSlotPool, inline, with no NULL test (see
[ai-action](ai-action.md) for the actions).

### A forced type (anything but 11)

A switch on `type - 2` through the jump table at 0x002ae300. Each case news
an action, stores it in `*out` and returns:

| Type | Action | Arguments |
|-----:|--------|-----------|
| 2 | Draft | DraftScore, DraftLifetime |
| 5 | JustDrive | JustDriveScore, JustDriveLifetime |
| 6 | PullOver | PullOverScore, PullOverLifetime, the controller's PullOverTimeout (548), the nearby list (512), the location (504); then 548 = 1e7 (gp-32024) |
| 7 | GetUnstuck | GetUnstuckScore, GetUnstuckLifetime, -1.0 |
| 10 | AccidentRecovery | AccidentRecoveryScore, AccidentRecoveryLifetime |
| any other | PullOver | PullOverScore, PullOverLifetime, PullOverStoppedByCopsTimeout (3.0), the list, the location |

"Any other" is 0, 1, 3, 4, 8 and 9, and anything below 0 or past 11: the
unsigned compare on `type - 2` sends them all to the default.

### No forced type (11): the cascade

A DrivingChoice on the stack is Cleared (0x00130920, three zero words). The
out slots the CalculateScores write start as:

| Slot | Start |
|------|-------|
| the road block | NULL |
| the hit car | NULL |
| the car to avoid | NULL |
| AvoidCars' seconds | 0.0 |
| AvoidCars' okay | 1 |
| AvoidCars' usedPreferred | 0 |
| the car to pass | NULL |
| the pass amount | 0.0 |

`cur` is the current action's (Type at 588, Score at 592), or (11, -1)
with none. **Steps 1 to 6 are each skipped when `cur`'s type is their
own, or their score global is below `cur`'s score.** With no action none
is skipped. Step 7, JustDrive, has no such test: it is tried whatever the
current action.

A step whose CalculateScore answers `s >= 0` news its action with score
`s`, stores it in `*out`, runs ~DrivingChoice(choice, 2) (a no-op) and
returns. The steps, in order:

1. **GetUnstuck**, only when more than six seconds have passed since
   LastTimeNonGetUnstuckActionWasCalled (544): `(float)(int)(WorldTimer -
   [544]) x 0.00025 > 6.0`. `aigetunstuck_calculate_score(info)`, with
   info the DrivingInformation at 12.
   - The minimum lifetime is 1.6 (gp-32028) when GetAmountOutOfBounds
     (slot 64) answers more than 0 **and** the Average is full
     (`nSamples == nSlots`) **and** its mean is under 0.2 (gp-32032).
     Otherwise it is -1.0.
   - New GetUnstuck(s, GetUnstuckLifetime, that minimum), and WorldTimer
     into 544.
2. **AvoidRoadBlock.** `aiavoidroadblock_calculate_score(info, &rb)`, then
   new (s, -1.0, rb).
3. **IJustGotHit.** `aijustgothit_calculate_score(info, &hit)`, then
   MaybeHonkAndOrBlinkHeadlights(this, hit, the list), then new (s, -1.0,
   hit).
4. **AvoidCars.** `aiavoidcars_calculate_score(info, &car, &choice, &secs,
   &okay, &used)`. With `s >= 0`, MaybeHonk(this, car, the list), and
   then only if ShouldWeAvoidThisCar(car, secs) answers 1:
   - the choice is copied into MyCurrentDrivingInformation's
     MyDrivingChoice (this+492, 12 bytes);
   - new AvoidCars(s, AvoidCarsLifetime, car, `(float)(uint32)okay`,
     used, 0).

   **This is retail's quirk, and the port keeps it.** The bool `okay`
   goes in as the float seconds, `used` as okay, and 0 as usedPreferred.
   The bool is a word, converted with the unsigned pattern (a word with
   the top bit set comes out at 2^31 or more, not negative). If ShouldWeAvoidThisCar
   answers 0, the cascade goes on to step 5, with the honk already done.
5. **AccidentRecovery.** `aiaccidentrecovery_calculate_score(info)`, then
   new (s, -1.0).
6. **Pass.** `aipass_calculate_score(info, &pcar, &choice, &amount)`. Only
   if `s >= 0` and then ShouldWeAvoidThisCar(pcar, -1.0) answers 1: the
   choice is copied into 492 as above, then new Pass(s, PassLifetime,
   pcar, amount). A negative score does not draw.
7. **JustDrive.** `aijustdrive_calculate_score(info)`. With `s >= 0`, new
   JustDrive(s, -1.0). Then ~DrivingChoice and the return. **With a
   negative score `*out` is left as it was.**

The honks in steps 3 and 4 come before ShouldWeAvoidThisCar, so a car the
racer decides not to avoid can still be honked at.

## The globals

AIAction.obj's scores and lifetimes, retail `.sdata`. Retail lays the
scores out in another order than the demo, so the gp offset is the guide.
**Nothing in the image writes them.** A scan of every load and store with
`$gp` for a base, from gp-18288 to gp-18136, finds 104 loads and two
stores, both to AIActionSlotPool (gp-18288, at 0x001c604c and
0x001c6070). The port defines them in `aidriver.c`;
AIActionJustDriveScore (gp-18272, 0) is `aiaction.c`'s.

| Global | gp | Value |
|--------|---:|------:|
| AIActionDraftScore | -18268 | 200 |
| AIActionPassScore | -18264 | 300 |
| AIActionNudgeCarScore | -18260 | 300 |
| AIActionBlockScore | -18256 | 400 |
| AIActionAvoidCarsScore | -18252 | 400 |
| AIActionIJustGotHitScore | -18248 | 400 |
| AIActionGetUnstuckScore | -18244 | 500 |
| AIActionAccidentRecoveryScore | -18240 | 500 |
| AIActionPullOverScore | -18236 | 600 |
| AIActionAvoidRoadBlockScore | -18232 | 600 |
| AIActionPassLifetime | -18228 | 5.0 |
| AIActionDraftLifetime | -18224 | 0 |
| AIActionNudgeCarLifetime | -18220 | 5.0 |
| AIActionJustDriveLifetime | -18216 | 0 |
| AIActionBlockLifetime | -18212 | 5.0 |
| AIActionGetUnstuckLifetime | -18208 | 5.0 |
| AIActionPullOverLifetime | -18204 | 0 |
| AIActionAvoidCarsLifetime | -18200 | 0 |
| AIActionIJustGotHitLifetime | -18196 | 0 |
| AIActionAccidentRecoveryLifetime | -18192 | 0 |
| AIActionPullOverTrafficCarTimeout | -18160 | -999 |
| AIActionPullOverCrossFinishLineTimeout | -18156 | 15 |
| AIActionPullOverStoppedByCopsTimeout | -18152 | 3.0 |
| AIDriverFrictionBoost | -23008 | 1.0 |

AIActionPullOverCrossFinishLineTimeout is read by Race::FinishCar's
pull-over (0x001908d8) instead ([race-update.md](race-update.md)).

AIDriverAvoidCarsImpactTimeThreshold (gp-18168, 2.0) is `aiactions.c`'s
and AIActionPassMaxTimeAheadToMakeAttempt (gp-18164, 3.0) `nearbycar.c`'s,
where their readers are.

## In the port

- `aidriver_install_vtables` is called from main.c, and main.c sets
  `gAIDriverCtorFn = aidriver_construct`.
- A race with AI racers now builds an AIDriver for each, where the NULL
  seam aborted before. **The game does not make one yet**: the SkipFE
  race has SkipFENumAICars, 0, and the frontend's way into a race is not
  wired. 11g puts AI cars in the SkipFE race.

## The checker

`tools/aidriver_check.py` runs the image's constructor, destructor, Think,
GetRouteNumbersToUse, ShouldWeAvoidThisCar and ChooseNewAction in
mipsemu, with Average, Timer::CountDown, DrivingChoice::Clear and the
table as shipped. `tools/src/aidriver_test.c` runs `aidriver.c`,
`average.c`, `timer.c`, `difficultyinfo.c`, `bmem.c` and `vtable.c`. Both
sides stand in for, and print:

- AICarController's constructor (which sets the car and AICarController's
  vptr), destructor and Think;
- Car::SetFrictionBoost, with its car and boost;
- MaybeHonkAndOrBlinkHeadlights and GetAmountOutOfBounds (a set answer);
- PsychoDriver's constructor, which gives the driver a test table whose
  destructor prints; every other AICarController slot exits if called;
- World::Random(float), from a queue of draws;
- the seven CalculateScores, each answering a set score and writing the
  outs a mask allows;
- the nine action constructors, printing their arguments; bOMalloc hands
  out numbered slots.

The record is printed field by field after each op, with cars and actions
by name and the console's sizes for the host's wider records.

The scenarios:

- the table, slot by slot as retail addresses, and the globals, at the
  start and the end;
- the constructor and destructor with each flag, over junk; the
  destructor with no driver, no Average or neither, and called directly
  with AICarController's vptr in place;
- GetRouteNumbersToUse;
- Think: as built; the timer a tick either side of the step at 1 to
  0x40000000 ticks; timers of 0, 0x7fffffff and past with odd steps
  (negative, -0, 1e10); lap rates of 0, -0, the smallest float and huge,
  over track lengths of 0, 5000 and -1; and round the ring twice;
- ShouldWeAvoidThisCar: the second a tick either side, and wrapped; no
  car with and without one set aside; every skill from -13 to 21 with the
  draw at its chance and an ulp either side; and seven calls in turn;
- the forced types, -2 to 13 and both extremes, PullOver and the default
  with and without a list and location;
- the cascade: each step alone at scores 0, 1, 777 and -1; the order;
  the current action's types -1 to 12 against each score global and a
  point either side, once with only JustDrive scoring and once with
  every step scoring; the six seconds a tick either side; the very stuck
  test at each edge; AvoidCars' okay over every way through the unsigned
  conversion; what the CalculateScores leave unwritten; the cars set
  aside; 60 thinks and choices in turn; and 400 random rounds.

56131 ops, 25276 lines, 0 differ.

### The mutation pass

191 mutations: 184 caught, 7 of them by crashing the harness, and 7
equivalent.

| Mutation | Why it cannot show |
|----------|--------------------|
| ni-zero724, ni-zero724b | The constructor zeroes 724 twice; either alone leaves it 0. ni-zero724-both drops the two and is caught. |
| ni-zero728 | timer_set_time sets 728 before anything reads it. |
| cur-score | Every score global is over 0, so none is below -1 or 0. |
| cur-type | No step's type is -1 or 11. |
| un-wait | No whole number of ticks is 6 s exactly: 23999 are 5.99975 s and 24000 6.0000005. |
| pa-secs | ShouldWeAvoidThisCar does not read its float. |

The destructor's own vptr store (dd-vt) showed only once the "del with
another vptr" scenario called it with AICarController's vptr in place.
