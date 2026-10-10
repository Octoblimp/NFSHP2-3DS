# pursuit-speech -- what the cops on a chase say

Each chase (tPursuit, [pursuit](pursuit.md)) decides what its cops say
and raises it on the speech manager ([speechmgr](speechmgr.md)). A method
picks:

- the speakers, from the chase or the cop manager's queue of four;
- what the cops can tell of the chased car: its name and its paint;
- whether the supervisor is on the radio.

The supervisor is on while tCopManager's fSupervisorTimer is within 0.001
of 0. Retail gives each method its own 0.001 (gp-27036 .. gp-26992).

Retail has these in pursuit.obj. The port has them in
`pursuitspeech.{c,h}`, with Speech::ConvertCarType in `speechconv.{c,h}`.
`tools/pursuitspeech_check.py` runs retail's code against both.

| function | retail |
|---|---|
| GetChasedCarColour | `0x0022aa20` |
| GetExactDescription (jump table `0x002bd3b0`) | `0x0022aa50` |
| the supervisor's test | `0x0022aaf0` |
| RaiseBackupSpeech | `0x0022acc0` |
| DeclarePursuitSpeech | `0x0022ad30` |
| BeginPursuitCollisionSpeech | `0x0022aef8` |
| StartPursuitSpeech | `0x0022afb8` |
| JoinPursuitSpeech | `0x0022b288` |
| RoadblockFailedSpeech | `0x0022b3f8` |
| RoadBlockSetSpeech | `0x0022b5d0` |
| CopBackOffSpeech | `0x0022b788` |
| AITicketSpeech | `0x0022b840` |
| SuperInitiates | `0x0022b908` |
| Speech::ConvertCarType (table `0x0031c1f0`) | `0x002232f8` |

Not ported:

- **`0x0022b990`**, the chased car's heading as a direction_t. Nothing
  calls it.
- **ChangeChaseTarget's speech** (`0x0022cb30`). It is Be A Cop's (12m).

## The chased car

**The paint.** GetChasedCarColour is the PaintType of the chased car's
skin. It comes from GetSkinInfo with the default flag, and it is a
racerVehicleColor_t.

**The name.** GetExactDescription gives a racerVehicleExactDescription_t:

- A cop car (its type's UsageType is 1) is `0x10000000`.
- Types 15, 16 and 22 are -1, "the cops cannot tell".
- Types 5, 6, 13, 14, 43 and 44 are also -1 in French and German
  (CurrLanguage 1 or 2).
- Every other type goes through ConvertCarType's table of 67.

ConvertCarType gives 0 for a type below 0 or past 66. Types 49 to 66 are
0 in the table too. Most bits belong to two neighbouring types.

**The supervisor's test** (`0x0022aaf0`, SupervisorActivate's): the car
can be told, and the chase is at LEVEL2 or LEVEL3.

## The speakers

A chase keeps a primary and a secondary cop speaker (5 is none).
`GetCopSpeaker` gives the chase's speaker. The cop manager also keeps a
queue of four:

- **GetCurrentCopSpeaker** gives the queue's current speaker.
- **NextCopSpeaker** moves the queue on.
- **ReserveCopSpeaker** takes a speaker out of the queue for a chase.

A roadblock has its own speaker (its CopSpeaker). In Be A Cop, the
player's id (BeACopId) speaks for the AI tickets.

## The methods

**RaiseBackupSpeech** (a player's chase only) asks for backup at the
chase's landmark, or with no landmark.

**DeclarePursuitSpeech** runs only with a player involved:

- A car the cops cannot tell gets the general description.
- Otherwise bRandom(40) picks:

  | roll | speech |
  |---|---|
  | 0 | the repeated id |
  | 1-16 | the specific id |
  | 17-25 | the general id |
  | 26-35 | the avoidance |
  | 36-39 | no id |

**BeginPursuitCollisionSpeech** gets the car the chased car hit. Retail's
test is the wrong way round:

- With a landmark, it raises the general call.
- Without one, it raises the hit and run's speech on landmark 0:
  - for a cop's car, the cop's, and the chase goes to LEVEL2;
  - for anything else, the traffic's, and a LEVEL0 chase goes to LEVEL1.

**StartPursuitSpeech** is RequestPursuit's, for a new chase. In Be A Cop
the queue is flushed first.

- **An AI car's chase** (not in the AI or replay demos) gets its
  description from the queue's current speaker. The queue then moves on.
- **A player's chase**, outside Be A Cop, takes the first that applies:
  1. after a recent collision, the collision speech, with PursuitSubState
     1 and bAlreadyBeenHit set;
  2. with tickets, LEVEL1, and "again" 8 times in 10 for a car the cops
     can tell;
  3. over 100 (mph or km/h), its speed, 7 times in 10;
  4. erratic or general, one time in two each.
- **Be A Cop's chase** gets the description, from the chase's speaker.

**JoinPursuitSpeech** is RequestPursuit's for a cop joining, on a
player's chase only.

- With no primary speaker, one is reserved. It reports one of these:
  - the suspect found at the landmark;
  - the car again;
  - the general call.
- Otherwise it speaks only once (bAlreadyJoined), and only past LEVEL0.
  Backup confirms to the chase's speaker. The confirming speaker is:
  - a newly reserved secondary, when there is none and there is one
    player;
  - else the queue's current speaker, and the queue moves on.

**RoadblockFailedSpeech** is RoadBlockDefeated's, with its bool for
"through".

- With spike strips (BehaviourFlags 0x10), it raises the strip's failure.
  While the helicopter is attacking, one time in three it raises the
  helicopter's failure instead. Retail passes that one's arguments
  swapped: the supervisor's bool as the speaker, and "the speaker is not
  0" as the bool. The port keeps this.
- Without strips, the roadblock failed: the car went through it, or
  around it.
- Then, outside Be A Cop, the roadblock's speaker asks for another one.

**RoadBlockSetSpeech** is CreateRoadBlock's. It finds the landmark at the
roadblock (0 for none) and rolls bRandom(20):

- With spike strips, 0-2 sets a strip with no side. Otherwise the strip
  is set on its side: nSpikeSide 2 is the right, anything else the left.
- With no strips, 0-2 is a roadblock "setting", and the rest are "set"
  at the landmark.

**CopBackOffSpeech**: the cop backs off. The supervisor calls it off
instead when there are no cops, or, while the supervisor is on, three
times in four.

**AITicketSpeech** is CreatePullover's, for an AI car, and not in the AI
or replay demos.

- The speaker is Be A Cop's, or the queue's current one (the queue then
  moves on).
- It raises the car stopped, with its description. One time in three, or
  for a car the cops cannot tell, it raises the radio arrest instead.

**SuperInitiates** is SupervisorActivate's. It gives the supervisor the
speaker, the speed, the landmark, the description and the paint.

Every roll is bRandom on bDefaultSeed. The rolls happen in retail's order
and only where retail rolls: a test that fails first skips the roll after
it.

## The filler speech

When the player's chase has been quiet a while, the cops and the
helicopter fill the gap. tCopManager's TimeBasedSpeech
([cop-manager](cop-manager.md)) counts the time since the last speech.
Past its MaxSpeechGapTime it calls SayFillerSpeech (0x00231760) on the
player's chase with the manager's SpeechFillerCookie. It does not call it
while the supervisor's timer runs, while the chase is about to say
something, or while it is not chasing.

Retail has nine filler classes. FillerSpeechBanks (0x0031c658) points at
them in this order, and _GLOBAL_$I$FillerSpeechBanks (0x002317b0) gives
each its vtable: GetBank, IsAppropriate, GetWeight and Speak. Each bank
is one bit of the cookie.

| Bank | Class | Weight | Its test | What it raises |
|---|---|---|---|---|
| 1 | ChopperLocation | 4 | the helicopter near, a landmark | the rotor's location |
| 2 | ChopperTraffic | 4 | the helicopter near, traffic over 0.9 | the rotor's traffic |
| 4 | ChopperMisc | 4 | the helicopter near | the rotor's chatter, with the chased car past 30 forward |
| 8 | CopLocation | 2 | a cop within 65, a landmark | the subject's location |
| 32 | CopTacticMisc | 2 | a cop within 65, not Be A Cop | a divert or a cutoff, one roll in two |
| 64 | CopSpeed | 2 | a cop within 65, over 100 | the current speed |
| 128 | CopReckless | 2 | a cop within 65, 80 mph or more | the reckless update |
| 256 | CopDirection | 2 | a cop within 65 | the reckless update |
| 16 | TacticHit | 5 | flag 4, not Be A Cop, two different speakers, a cop within 40 | the tactic hit |

"A cop within 65" is tPursuit::IsCopNearChasedCar (0x0022bb28): one of
the chase's cars within 65 of the chased car, in three dimensions. Each
cop class tests that a cop is on the chase first. 80 mph is 0x0022bbb0's
35.762 m/s. "Over 100" is GetSpeedMPHOrKPH, in the player's units.

CopDirection's Speak is retail's reckless update, the same as
CopReckless's. The port keeps it.

TryFillerSpeech (0x002315d0) gathers the classes whose bank is not in the
cookie and whose test passes, rolls bRandom over their summed weights and
says the one the roll falls in. It adds that bank to the cookie and
returns 1. With no class to say it returns 0 and rolls nothing.
SayFillerSpeech empties the cookie on a 0 and tries again, so the
banks come round once each before any repeats.

The port has them in `fillerspeech.{c,h}`, the classes as a table of the
bank, the weight, the test and the speech. main.c binds
`say_filler_speech` into copmgr.h's gSayFillerSpeechFn.

## The seams

main.c binds pursuitspeech.h's methods into these seams:

- pursuit.h's start, join, back-off, declare, backup, collision,
  roadblock-failed and roadblock-set seams;
- pullover.h's AI ticket seam;
- copmgr.h's supervisor test and SuperInitiates;
- copmgr.h's filler speech, fillerspeech.h's `say_filler_speech`.

It also binds wrappers that call speechmgr.h's raise functions on
`speechmgr_get_instance()`:

- crash tow, crash, flat tire and the super request;
- the cop hit, the suspect's traffic crash, the spike strip's blowout;
- the requests for another roadblock, a spike strip and a roadblock,
  and the dispatch's "no roadblock";
- the helicopter's request and confirm, and the dispatch's "no
  helicopter";
- the racer caught.

## The check

`python tools/pursuitspeech_check.py` runs retail's code on the MIPS model
and the port's code on the host. Both run the same script. Every call the
methods make, to the manager or the queue or the game, is a logged stub.
The script covers:

- ConvertCarType from -5 to 75, and the extremes;
- GetExactDescription for types -2 to 70, with each usage and language;
- each method's branches: the rolls at each boundary, the landmarks, the
  speakers, the states, Be A Cop, the demos and the supervisor's timer;
- 3000 random steps.

Result: 258792 ops, 47809 lines, 0 differ.

The mutation pass makes 281 mutations. Some are generated:

- every table entry;
- every case label dropped, and a neighbour added to each group.

The rest are hand-written. They cover every test, constant, argument,
raise, return and call order. All 281 are caught.

### The filler speech's check

`python tools/fillerspeech_check.py` runs retail's TryFillerSpeech,
SayFillerSpeech, the nine classes through their vtables,
IsCopNearChasedCar and the reckless test on the MIPS model, against
`fillerspeech.c` on the host (`tools/src/fillerspeech_test.c`). The
helicopter's test, the speakers, the speed, bRandom and the nine raises
are logged stubs. The race's traffic and Be A Cop, the cars and the cops
are memory both sides read. The script covers IsCopNearChasedCar's
distances, each class's test at its boundaries with every bank of the
cookie, the roll at each weight's edges, SayFillerSpeech's second try on
a full cookie, and random chases.

Result: 81169 ops, 23198 lines, 0 differ.

The mutation pass makes 122 mutations. Each row of the class table has
its bank, its weight, its test and its speech changed or swapped with the
next row's. The rest cover every test, constant, argument and the roll's
sum. All 122 are caught.
