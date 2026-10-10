# speechmgr -- speech::mgr_t, the cops' radio talk

speech::mgr_t decides what the cops say on the radio, and when. The game
raises a speech event, such as "begin pursuit" or "road block set". The
manager queues it, and its machine (nfsFsm) turns it into one or more
sentences: the officer's call, then dispatch's or the supervisor's
answer. Each sentence is a speech library event
([spch](spch.md)) added with SPCH_AddEventV. The wedge
([sedwedge](sedwedge.md)) chooses the clips and plays them.

Retail has it in speechmgr.obj (`indep/src/speech/speechmgr.cpp`), with
the machine (nfsfsm), its conditions and actions, and speechContext_t.
The port has all of it in `speechmgr.{c,h}`, and
`tools/speechmgr_check.py` runs retail's code against it.

| function | retail |
|---|---|
| getInstance (a static, made on the first call) | `0x00209ef0` |
| update | `0x00209ff8` |
| FlushQueue, AllocateVoices | `0x0020a230`, `0x0020a288` |
| fade, Mute | `0x0020a290`, `0x0020a2b0` |
| pushSpeechEvent | `0x0020a2e8` |
| the raise functions | `0x0020a3e0` .. `0x0020b868` |
| the constructor (it builds the machine) | `0x0020b868` |
| nfsFsm, its states and transitions | `0x0020bf00` .. `0x0020c770` |
| the conditions and actions | `0x0020daa0` .. `0x0020f7c0` |
| speechContext_t | `0x0020f7f8` .. `0x0020fac8` |
| Speech::ConvertSpeed | `0x00223528` |

The instance is at `0x00334418`. The cop manager keeps a pointer to it at
gp-15624.

Not ported:

- **maybeSayDebugPhrase** (`0x0020a1f0`). It raises a tweaker's debug
  event (168), but the tweaker's flag (gp-16420) is never set in a retail
  build.
- **Unused machine parts**: fsm::stop, the destructor, isSpeaking (no
  callers; previousSedPlaybackState is read directly), test (empty), and
  the machine's other accessors.
- **randomCondition_t**, which no transition uses, and the four actions
  no transition uses: beginPursuitReckless, crashAmbulance,
  dispatchAmbulanceConfirm and dispatchBeginPursuitReckless.
- **Thirteen raise functions nothing calls**: BeginPursuitReckless,
  BeginPursuitRacing, ChatterGeneral, ChatterTraffic, CrashAmbulance,
  PursuitUpdateSpeed, PursuitUpdateVehicleIdSpecific, SuspectLost,
  Airborne, Direction, SuspectCrash, SuspectCrashAmbulance and
  SuspectCrashTow. The machine still has transitions for their events.

## Who calls it

- **sound::Update** calls `update` once per frame. sound::Mute calls
  `Mute`, and UnLoadSoundRegions calls `FlushQueue`.
- **The race's start and the post-race** (racecoord.c, rcpost.c) call
  `FlushQueue`, and so does the pullover when its NIS plays.
- **The cop manager's set-up** calls `AllocateVoices`, then
  `FlushQueue`.
- **The car selector** calls `fade`: 1.0 when it leaves the orbit, and
  0.2 when its screen closes.
- **previousSedPlaybackState** (+1452) is read by two callers:
  - while it is set, the jukebox's music is a little quieter in a race
    (0.95) and much quieter in the menus (0.3);
  - the cop manager's TimeBasedSpeech holds off its filler speech.
- **The pursuit code, the chopper, the pullover and the rest** call the
  raise functions. Step 14-10 binds those seams.

## The records

**speechContext_t**, 56 bytes, holds what one event says:

| offset | field | |
|---|---|---|
| 0 | copUnitId | the speaker, 0 to 3 |
| 4 | copTargetUnitId | whom it speaks to, 0 to 3 |
| 8 | copUnitLocation | location_t, a speech library bit value |
| 12 | arrestType | 1 formal, 2 informal |
| 16 | arrestLevel | |
| 20 | isSupervisorActive | |
| 24 | racerVehicleApproximateDescription | |
| 28 | racerVehicleExactDescription | |
| 32 | racerVehicleColor | |
| 36 | racerVehicleSpeed | ConvertSpeed's bit |
| 40 | raceType | |
| 44 | direction | |
| 48 | roadBlockLocation | location_t |
| 52 | boolParam | rotor chatter's flag |

**speech::mgr_t** is 1464 bytes:

| offset | field |
|---|---|
| 0 .. 1192 | nfsFsm: the 25 states (32 bytes each, from 16), the conditions (816 ..), the actions (840 .. 1188), the current state |
| 1192 | the queue: two (event, context number) pairs |
| 1208, 1212, 1216 | read, write, full |
| 1220, 1224 | nextContext, currContext |
| 1228 | four speechContext_t |
| 1452 | previousSedPlaybackState |

The port keeps the machine's current state as a number, and its
transitions as const tables (`kReady` and the rest in speechmgr.c). The
tables were generated from a dump of retail's constructor.

## Raising an event

Each raise function fills the next context: `contexts[nextContext]`,
with only the fields it is handed. It does not clear the context first,
so older values stay. It then calls pushSpeechEvent:

- Nothing happens during the replays or the post-race (see `update`).
- Nothing happens if the queue is full.
- Otherwise, the event and the context's number go in at `write`. Write
  wraps at 2, and the queue is full when write meets read.
- nextContext wraps at 4.

So at most two events wait, and a third is dropped. A context is reused
four raises later, so a queued event's context is never overwritten
before it is spoken.

A few raise functions store something besides their arguments:

- RadioArrest sets arrestType to 1, formal.
- SuperInitiate makes the speaker its own target.
- BeginPursuitSpeed, CurrentSpeed and SuperInitiate store
  ConvertSpeed's bit for the speed.
- UpdateReckless ignores its flag.
- SuperBackOff, RotorConfirm and RotorTraffic store nothing.

## update

Each frame:

1. **Off.** It does nothing during the race coordinator's INSTANT_REPLAY,
   POSTRACE and AUTO_REPLAY states, or during the replay demo
   (state 9).
2. **A sentence is playing.** That means the wedge is there and its
   status is neither PAUSED nor IDLE. The radio's static starts
   (SpeechNoise), unless it is already on.
   previousSedPlaybackState is set to 1, and update returns.
3. **Nothing is playing.** If the radio's static is on, it stops, and
   so does the helicopter's noise.
4. **Mid-exchange.** If the machine is not in READY, it handles event 1
   ("go on") with the current context. That says the exchange's next
   sentence. previousSedPlaybackState is set to 1.
5. **Idle.** If the queue is empty, previousSedPlaybackState is set to 0.
6. **Otherwise**, update takes the next event off the queue:
   - read wraps at 2;
   - full is cleared;
   - currContext becomes the event's context;
   - the machine handles the event with that context;
   - previousSedPlaybackState is set to 1.

So an exchange of three sentences takes three updates, each once the last
sentence has played.

## The machine

A state's transitions are tried in order. The first whose event matches
and whose condition holds runs its action, and the machine moves to its
state. An event with no matching transition does nothing.

The conditions:

- **NULL** always holds.
- **supervisor active** is isSupervisorActive.
- **supervisor not active** is `isSupervisorActive ^ 1`.
- **cop location set** is `copUnitLocation != 0`.
- **cop target id set** is that the target's "to" id is not 0.

Every action first squelches the radio (SpeechNoise::BeginSquelchNoise).
Four of them also start the helicopter's noise: rotor location, rotor
chatter, rotor traffic and rotor spike failed. Then the action adds its
sentence.

READY's transitions are the events below. Every other state has only
event 1. States 3, 17 and 24 (dispatchBeginPursuitReckless,
secondaryRespond, requestAnotherRoadBlock) have no transitions, and
nothing leads to them.

The table gives each raised event, its raise, and the speech library
event of each sentence. "Then" is what the following updates say, by
condition. "Nothing" is a transition with the null action.

| event | raise | first sentence | then |
|---|---|---|---|
| 2 | PursuitCopHit | 22 | 13 |
| 3 | BeginPursuitCopHitRun | 11 | 86 |
| 4 | BeginPursuitErratic | 6 | 13 |
| 5 | BeginPursuitGeneral | 7 | 13 |
| 6 | BeginPursuitHitRunTraffic | 14 | 85 |
| 7 | BeginPursuitIdGeneral | 16 | 13 |
| 8 | BeginPursuitIdSpecific | 17 | 92 |
| 9 | BeginPursuitIdRepeated | 17 | 67, then 17, then 92 |
| 10 | BeginPursuitNoId | 9 | 13 |
| 11 | BeginPursuitRacing (not ported) | 8 | 83, with a location |
| 13 | BeginPursuitSpeed | 15 | 91 |
| 14 | BeginPursuitAgain | 199 | 92 |
| 15 | BackupRequest | 41 | -- |
| 16 | BackupRequestLocation | 42 | -- |
| 17 | BackupConfirm | 19 | -- |
| 18 | ChatterGeneral (not ported) | 21 | -- |
| 19 | ChatterTraffic (not ported) | 20 | -- |
| 20 | CopPursuitAvoidance | 10 | 13 |
| 21 | PursuitUpdateSpeed (not ported) | 54 | 180 (supervisor) or 13 (no supervisor) |
| 22 | PursuitUpdateSubjectLocation | 56 | 180 (supervisor) or 13 (no supervisor) |
| 24 | PursuitUpdateVehicleIdSpecific (not ported) | 65 | 180 (supervisor) or 13 (no supervisor) |
| 25 | SuspectFound | 62 | 180 (supervisor) or 13 (no supervisor) |
| 26 | SuspectLost (not ported) | 63 | 180 (supervisor) or 13 (no supervisor) |
| 27 | TacticHit | 25 | 28 |
| 29 | TacticDivert | 24 | -- |
| 30 | TacticCutoff | 23 | -- |
| 31 | UpdateReckless | 50 | 13 (no supervisor) or nothing |
| 32 | RacerCaught | 194 (level 1), 195 (level 2), else 0 | -- |
| 33 | SuperBackOff | 100 | 43 |
| 34 | CopBackOff | 187 | 179 (supervisor) or 186 (no supervisor) |
| 35 | RadioArrest | 178 | 13 |
| 36 | CarStopped | 188 | 13 |
| 38 | CrashTow | 45 | 198 (a target) or 81 |
| 39 | Crash | 44 | 198 (a target) or 81 |
| 40 | FlatTire | 177 | 198 (a target) or 81 |
| 41 | RotorRequest | 53 | 13 (no supervisor) or 96 (supervisor) |
| 42 | RotorConfirm | 72 | -- |
| 43 | RotorLocation | 109 | -- |
| 44 | RotorChatter | 112 | -- |
| 45 | RotorTraffic | 121 | -- |
| 46 | RotorSpikeFailed | 181 | -- |
| 47 | RoadBlockFailureAvoid | 33 | -- |
| 48 | RoadBlockFailureThrough | 34 | -- |
| 49 | RoadblockRequest | 31 | 97 (supervisor) or 13 (no supervisor) |
| 50 | RoadBlockSet | 35, or 172 with no location | 71 or 171 |
| 51 | RoadBlockSetting | 52 | 71 or 171 |
| 52 | RequestAnotherRoadblock | 189 | 180 (supervisor) or 13 (no supervisor) |
| 53 | SpikeStripFailure | 36 | -- |
| 54 | SpikeStripRequest | 32 | 98 (supervisor) or 13 (no supervisor) |
| 55 | SpikeStripSet | 40, or 173 with no location | 170 or 73 |
| 56 | SpikeStripSetLeft | 38, or 174 with no location | 170 or 73 |
| 57 | SpikeStripSetRight | 39, or 175 with no location | 170 or 73 |
| 58 | SpikeStripTireBlow | 37 | -- |
| 59 | SuperRequest | 57 | 185 |
| 60 | SuperInitiate | 101 | 56 (a location) or 65 |
| 61 | Airborne (not ported) | 51 | -- |
| 62 | CurrentSpeed | 47 | 13 |
| 63 | Direction (not ported) | 48 | 13 |
| 64 | SuspectCrash (not ported) | 58 | -- |
| 67 | SuspectCrashTraffic | 61 | -- |
| 68 | DispatchBeOnLookout | 203 | -- |
| 69 | DispatchRoadBlockNA | 201 | -- |
| 70 | DispatchHelicopterNA | 202 | -- |

Events 12, 37, 65 and 66 (BeginPursuitReckless, CrashAmbulance,
SuspectCrashAmbulance and SuspectCrashTow) have no transition at all.

Some sentences branch on random draws, all of them `bRandom(2)` on
bDefaultSeed:

- **Dispatch's road block update** says 71 with the road block's place
  when there is one and the draw is 0. Otherwise it says 171, with no
  place.
- **Dispatch's spike strip set** works the same way: 170, or 73.

Each action's parameters are what the speech library's rules and
choices test. They are cop ids and the context's bit values. The
parameters of every action are in `action_say` in speechmgr.c.

## The cop ids

Each speaker (0 to 3) has three ids:

- a **voice**, its cop id: one of 2, 4, 8 and 32;
- a **from** id, for "this is unit N";
- a **to** id, for "unit N, go ahead".

AllocateVoices makes them:

1. It shuffles {2, 4, 8, 32} into the voice table.
2. It shuffles {1, 2, 4, 8, 16, 32}, and copies the first four into
   both the from and the to tables. The two tables are always the same.

A speaker past 3 gets id 0.

The shuffle walks the array. At each step, with n left, it swaps the
first with `bRandom(n)` on bDefaultSeed. It stops at one left. So the
voices take three draws and the from ids five.

The getters read the speaker's ids (cop, from, to) or the target's
(target cop, target from, target to).

## ConvertSpeed

ConvertSpeed turns a speed into the speech library's speed bit:

- under 100, it is 0;
- over 340, it is 4096;
- otherwise it is `1 << (unsigned)((speed - 100) * 0.05f)`, giving
  1 << 0 to 1 << 12 in steps of 20.

A NaN speed passes both tests. Its float-to-unsigned conversion gives 0,
so it returns 1.

## Fade and Mute

These two act on the wedge only, if there is one:

- **fade** hands it the level (cSEDWedge::Fade);
- **Mute** hands it `on != 0` (cSEDWedge::Mute).

**FlushQueue** stops everything:

- the machine goes back to READY, and the queue empties (write = read,
  full = 0);
- the radio's static stops, and so does the helicopter's noise;
- the wedge's own queue is cleared.

## The check

`tools/speechmgr_check.py` (with `tools/src/speechmgr_test.c`) runs
retail's code in the MIPS model and the port in a host harness, then
compares them. It covers:

- every raise, four times each, including with a full queue;
- every event from -1 to 72 (plus 100, 255 and 288), under five
  contexts;
- every state, with each of the four current contexts;
- the queue's overflow and flush;
- the wedge's statuses, with the radio on and off;
- the race coordinator's states;
- ConvertSpeed, over a range of speeds plus NaN, the infinities, a
  denormal, -0 and the largest float;
- fade and Mute, with and without a wedge.

Result: 4145 ops, 27220 lines, 0 differ.

The mutation pass makes 885 mutations. Most are generated:

- every sentence's event and parameters;
- every transition's event, state, condition and action, and the order
  of each two-transition state's;
- every raise's event and each of its stores.

The rest are written by hand. 876 are caught. The 9 that survive are
equivalent, and the checker gives the reason for each:

- six are a second transition's supervisor condition, already settled
  by the first's;
- one is the state set before the action, which never reads it;
- one is ConvertSpeed's `<=` at 340;
- one is `/ 20` for `* 0.05`.
