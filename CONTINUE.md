# CONTINUE

## The device crashes (Session 77, open)

Two random race crashes on the user's New 3DS XL were Process9 (the SD
driver) reading ENGLISHDAT.PCK at 0x094B2400. The debug log is off now
unless `DebugLog 1` is in nfshp2_config.txt. After deleting and
recopying the files the user heard French and English speech at once,
then it crashed again (Session 78). The port opens one language's
speech, so the card's FAT is the suspect (two files sharing clusters);
the user was told to back up, run `chkdsk X: /f` or reformat FAT32 and
copy afresh, and try H2testw. Ask how that went.
HANDOFF.md, "Session 77 -- the device crashes and the debug log".

## Be A Cop, step 12m (the audit of Session 76)

A SkipFE Be A Cop race (`SkipFEBeACop 1` and `DefaultPlayer1CarType
33`, the CORVETTECOP, parked on the SD card as
`nfshp2_config.txt.beacop`; copy it to `nfshp2_config.txt` for a run and
delete that after) runs at 30 fps. Since 12m-1 the horn (3DS X, Azahar
key 90) opens a chase, and since 12m-2 Time Left counts down. Ported already: tPursuit's Be A Cop branches
(the catch speeds, the roadblock count, the arrests' speech), the
requests for a roadblock and the chopper (pursuitchopper.c), the
cop's HUD (hudcop.c, hudrender.c, hudscore.c), the setup screens
(bsetup.c) and You're The Cop's results (RE-6d). Missing, in order:

- **12m-1 (done)** tPlayerCop's Think (`0x0022d5c8`),
  ChangeChaseTarget (`0x0022d700`) and SelectCarToChase (`0x0022d898`),
  and the horn's BeACopToggleSirenAndLights (`0x002289b8`), in
  `playercop.c` (`docs/formats/cops.md`, "Be A Cop's player cop").
  DoSnapshot (`0x0022d7e8`) is the replay's and waits for it.
- **12m-2 (done)** tCopManager::BeACopThink (`0x00227f30`,
  `gCopManagerBeACopThinkFn`) in `playercop.c`: the clock, the
  time-out finish, the Busted and Be On Lookout speech, and each
  wrecked speeder (`docs/formats/cops.md`, "BeACopThink").
  GetBeACopSpeaker and GetBeACopTime are getters with no caller.
- **12m-3 (done)** The controls, the user's plan of 2026-10-08: in Be
  A Cop D-Pad Left calls the helicopter and Right the roadblock
  (retail's TRIANGLE + L2 and + R2, sent as that combo by
  `joyhid_cop_keys`), and only the Circle Pad steers
  (`docs/formats/joystick.md`, "Be A Cop's D-pad").
- **12m-3b (done)** SetupRaceParametersAfterRaceSetup (`0x001862b0`)
  in `fredrace.c`: the challenge setup screens' words into
  TheRaceParameters (the AI, the traffic, the clock, three roadblocks
  and three choppers, the objective), bound to main.c's hook
  (`docs/formats/race-start.md`).
- **12m-3c (done)** Select Track (`TrackSelectScreenCallback`,
  `0x001a0920`; its StartRace is `0x001a0790`). Car select goes on to
  it for every game type but the event games. Read HANDOFF.md's
  "Session 77, continued -- 12m-3c-1" first. The still camera
  (`stillcam.c`) is ported and checked, and the whole screen is decoded
  in `docs/formats/track-select.md`:
  - **12m-3c-1 (done)** `btracksel.c`: the logic, the 2D, the model and
    StartRace, with ACTIVATE's reply, `bmenu_set_active_item` and
    `tracksel_check.py` (0 differ; 171 mutations, 155 caught, 16
    equivalent). On Azahar it works from car select. Y (SQUARE) works;
    the run script's key was 0 (fixed in Session 78).
  - **12m-3c-2 (done)** The TSELECT.BIN slideshow: main.c's five pack
    hooks over `texturestream.h`, and `trackSelSyncPictures` puts the
    shown pictures on the GPU (HANDOFF.md, "Session 78"). The white
    specks on some pictures are the disc's.
- **12m-4 (done)** The Pre Race Blurb and the two-player You're The
  Cop screen (startrace.c, f3767e9; HANDOFF.md, "Session 79").
  startrace_check: 0 differ; 278 mutations, 274 caught, 4 equivalent.
- **12m-5 (done)** A Be A Cop race from the frontend in Azahar
  (`tools/run_azahar_coprace.ps1`; HANDOFF.md, "Session 80"): the
  chase, the calls, the clock, the end and the results, with no abort
  since the IsBeingPursued seam. The icons go green to blue at a call,
  as retail's code has them. The cop buttons are X target, L roadblock,
  R helicopter (ce58fac). Not seen: an arrest, which the gas-only
  script cannot make. TASKS 43 is done (3DS button icons).

**Now (Session 87, 2026-10-12): TASKS 39 is done (12k-6). The
helicopter's rockets, smoke bombs and dropped spikes are retail's
(`munition.c`, FireSalvo in `chopperfire.c`; `docs/formats/munitions.md`).
munition_check: 1038 lines, 0 differ, and 175 of 175 mutations caught
(HANDOFF.md, "Session 87"). TASKS 55 is done too: the Luma dumps
on closing were threadguard's thread waking after exit() freed its
stack; the three watcher threads are stopped and joined at atexit
(HANDOFF.md, "Session 87, continued"). TASKS 56 is done: the boot
asked for the language after loading the card, and the language's
defaults wiped the save; retail's order (language, then BootAutoload)
keeps it, and points now add up across races and boots (HANDOFF.md,
"Session 87, continued -- TASKS 56"). TASKS 58 (the car through the
road, walls and cars) is closed at the user's word with no fault
found: the hull matches the body and no penetration showed (HANDOFF.md,
"Session 87, continued -- TASKS 58").**

**Now (Session 93, 2026-10-14): TASKS 51c (the vertices) is done. The
walk and DamageVertexFunction dent and darken a car's vertices and show
its scuffs, and the car's editable mesh is refreshed at its next draw
(`geobake.c`, `georender_refresh`; `docs/formats/car-damage.md`, "The
renderer's vertices"). The user saw the player's cop car drawn black, or
only as wheels and a shadow. Its body (CROWNVIC_A2) failed to bake: the
bake's working buffers came from the main heap, whose largest free
block is 64 KB in a race. They come from the linear heap now, and the
race's stats line counts failed bakes (HANDOFF.md, "Session 93"). SkipFE
and Quick Race run with damage off; a You're The Cop race has it on.
Next, one at a time: 51d (Car::DamageAbove), then TASKS 37 (multi-card
multiplayer).**

**Now (Session 92, 2026-10-13): TASKS 51a (the damage logic) is done.
`cardamage.c` ports BodyDamage and CarDamage whole, and `main.c` binds
every seam but the vertex walk, DamageAbove and TriggerEffect: each
racer and cop has a CarDamage, hits dent its zones, break its lights and
windows and derate its engine, and a blast wrecks it. cardamage_check:
13,349 lines, 0 differ, 132 of 135 mutations caught, 3 equivalent
(HANDOFF.md, "Session 92"; `docs/formats/car-damage.md`). 51b is done
too: the renderer reads each batch's strip flags live, so a broken
window loses its environment map (HANDOFF.md, "Session 92, continued
-- 51b"). Next, one at a time: 51c (the vertices), 51d (DamageAbove). Then TASKS 37, multi-card multiplayer, at the user's
word of 2026-10-13. TASKS 60 (Car::TriggerEffect, the car's particles)
is new.**

**Now (Session 91, 2026-10-13): TASKS 54 (Player Names on the 3DS
keyboard) is done. A on Player 1's name opens the 3DS's keyboard with
retail's rules: seven characters, letters, numbers, ! . # and the
space. OK keeps the name; Cancel keeps the old one. Player 2's rows are
hidden (no split screen, the user's word; TASKS 30 is closed with it).
The sound is held while the keyboard is open. On Azahar it stays off
3.5 s after, because Azahar stops the whole console during its dialog
and its audio stretcher swings for about three seconds. B with anything
changed asks "Save your changes to the card?" (Yes, No, or B to stay).
The Azahar walk passes (HANDOFF.md, "Session 91";
`docs/formats/name-entry.md`). TASKS 59, stereoscopic 3D on the top
screen, is logged for later at the user's word. Next: TASKS 51 (the
damage system, CarDamage). Ask the user for a log at the fire with the
GpuSends build.**

**Now (Session 90, 2026-10-13): TASKS 53 (the debug menu) is done.
L + R + D-Pad Up on the main menu, or "DebugMenu 1" in the config,
shows a fourth item, "Debug Menu". It has two screens:
- Debug Menu: Start Debug Race, NFS Points, Set Save to 100%, Unlock
  Everything, Lock Everything.
- Debug Race: Start Race at the top, then the race's settings.

Leaving, or starting a race, with the save changed asks "Save your
changes to the card?". Yes saves on the Autosave screen, No undoes,
and B stays. Both Azahar walks pass (HANDOFF.md, "Session 90";
`docs/formats/debug-menu.md`). Next: TASKS 54 (the keyboard). Ask the
user for a log at the fire with the GpuSends build.**

**Now (Session 89, 2026-10-13): TASKS 53 (the debug menu) is designed
but nothing is written. The session was stopped at the user's word
before any code. The plan:**

- **FRONTB rebuilt at boot.** A new `debugmenu.c` rebuilds FRONTB's
  Flailer chunk with two things added:
  - a hidden 4th main-menu item, "Debug Menu", with its mask;
  - a new screen, "Port Debug Menu" (`0xd98ab71e`), copied from Be The
    Cop Setup with bigger text rooms.
- **Showing the item.** The L + R + D-Pad Up chord on the main menu,
  or "DebugMenu 1" in the config, shows the item.
- **The panel** starts any track with chosen settings, unlocks or
  locks everything, and gives NFS points.

**Every offset, hash and call is in HANDOFF.md, "Session 89". Read it
first and write the code from it. Then do TASKS 54 (the keyboard). Ask
the user for a log at the fire with the GpuSends build.**

**Now (Session 88, 2026-10-13): TASKS 57 is done, waiting on the
device's word. The fire is on track 11, where the user's log was
GPU-bound at 13.8 FPS, with the GPU starting only after the CPU's whole
draw. The frame now goes to the GPU in parts by default (`GpuSends`
1, with one more send after the envmap). "GpuSends 0" in
nfshp2_config.txt goes back. The pixels are the same, and Azahar ran
the race with no hang (HANDOFF.md, "Session 88";
`docs/formats/draw-cuts.md`, "TASKS 57"). Ask the user for a log at
the fire with this build ("DebugLog 1"). If the GPU ever stops, the
sends are the first suspect. Next, one at a time: TASKS 53 (the debug
menu), then 54 (the keyboard).**

**Now (Session 86, 2026-10-12): TASKS 52 is done, the profiles.
Retail's `MemcardSaver`, `LoadSaveWrapper` and `Autosaver` are in
`memcard.c`. The Options menu's Save/Load saves, loads and turns
autosave on or off. Each race's Quit or Next Race asks to create or
overwrite `sdmc:/NFSHP2/SAVES/settings.db`
(`gEndGameAlwaysAskToSave`, `saveAskCreate`). bootflow_check: 95
scenarios, 0 differ; the save/load mutations are 76, with 75 caught and
1 equivalent. endgame_check: 0 differ. Both are seen on Azahar
(HANDOFF.md, "Session 86"). Next: TASKS 39 (12k-6, the helicopter's
munitions) to 100%, then TASKS 53 (the debug menu). TASKS 47 and 46
wait on the user.**

**Now (Session 85, 2026-10-12): step 14b is done. The smokeables are
retail's (`smokeable.c`, `smokeableinfo.c`; `docs/formats/smokeable.md`):
the two chunks load, a virgin stands in for each spawner, a car's touch
converts it, and it wakes, breaks, sleeps and comes back as retail's
does. The roadblock's barrels spawn and delete through it. smokeable_check
runs retail's image: 0 differ; 276 mutations, all caught or equivalent.
The track's cones and signs show again: they had been hidden since the
chunk slot was unported. Also fixed: a SkipFE race paused on its first
frame. The 32-read type detection had no frames before the race, so
`main.c` now primes it. Next: TASKS 39 (12k-6, the helicopter's
munitions), then the user's profile save and load with a save prompt
after each race. TASKS 47 and 46 wait on the user.**

**Now (Session 84, 2026-10-12): TASKS 49 is done. The joystick is
retail's: its tables and event numbers (`gen_scanner_tables.py` from
SLES_507.31), the 32-read type detection, the frame's own pad read, and
the type monitor letting go of a port's cars
(`docs/formats/joystick.md`). joystick_check runs retail's image: 0
differ, 266 mutations, 261 caught, 5 equivalent. New: TASKS 50 (the main
menu's code reader, the cheats). Next: TASKS 39, the helicopter's
missiles and barrels. Its munitions are Smokeables, so step 14b comes
first: the smokeable chunk loads as nothing today (bchunkload.c's slot
27), so the track's breakables and the roadblock's barrels are
missing. TASKS 47 and 46 wait on the user.**

**Now (Session 83, 2026-10-12): TASKS 43 is done. Every help
character draws the 3DS key that does its job (`helpglyph.c`, the
port's own icon sheet `data/buttons3ds.bin`), and the cop's Blurb
reads X target, R helicopter, L roadblock, D-pad Down boost. Its
target was the boost's glyph: retail's JoyEvent numbers run one
above the demo's from 110 (TASKS 49 has the joystick tables, which
are still the demo's). New: TASKS 48 (tHelpMenu, the frontend's
dead Circle "help"). TASKS 40 (12n, the radar meter) is done too:
`copmgr.c`'s GetRadarDetectorIntensity, retail-checked and bound,
and the lights climb near a cop on Azahar. Next: TASKS 49, then 39
(12k-6, after step 14b). TASKS 47 and 46 wait on the user.**

**Now (Session 82, 2026-10-12): step 14 is done (14-10d, 3ac6572)
and so is task 38 (BUSTED! animates and is whole; no change, see
TASKS.md 38). Next: TASKS 43's Blurb glyphs, TASKS 39 (12k-6, the
helicopter's missiles), TASKS 40 (12n, the radar meter). TASKS 47 has
the user's log read (track 44; the helicopter over the bridge both
laps) and waits on what the artifact looked like; TASKS 46 waits on
the device's timing.**

**Now (Session 81, 2026-10-12): TASKS 45 is done (9e044f3, the sun's
glare). TASKS 46 has three lossless cuts in (the shader b293a76, the
sends 9e044f3 opt-in, the clusters bb70171; `docs/formats/draw-cuts.md`,
"TASKS 46") and waits for the device's timing at the fog and the
desert, and the user's word on the envmap a face a frame. Then step 14
(full audio) and task 38 (BUSTED!). The user's build is bb70171.
First, TASKS 47: the brief artifact on the bridge before the finish
line the user saw on their 3DS, both laps; their logs come on
2026-10-13.**

**Then (Session 80, 2026-10-12): TASKS 45, the slight polygon artifacts
(the sun's glare has a hard, stepped edge), then TASKS 46, a smooth 30
FPS with many cars and fog (the GPU plan of 2026-10-05), then step 14
and task 38.** TASKS 42 (the Circle Pad in the menus) and 44 (the bottom
screen laid out again) are done.

**Now (Session 76, 2026-10-11): Be A Cop "100% working", the user's
ask of 2026-10-11. TASKS 41 (the Starting Grid only once the race
has loaded) is done.** The end of the race, RE-1 to RE-6
(below in "First"; the user's ask of Session 70: "I do need the end of
races to be coded in"), is done. RE-1 is done (the list of screens, the classes' base, the
callback and the End Game Menu; `docs/formats/end-game.md`), and so is
RE-2a (what Fred keeps of the race and the rewards;
`docs/formats/race-over.md`), and RE-2b (Race Results with its stats
slideshow and points tally, and the Points and Task Rewards screens;
`docs/formats/race-results.md`), and RE-2c (the race-over overlay's
message, `docs/formats/race-over-overlay.md`), and RE-3 (the records,
Best Lap Times, Best Total Times and the Lap Times screens;
`docs/formats/best-times.md`), and RE-4 (the post-race camera;
`docs/formats/camera-coordinator.md`, "The demo camera"), and RE-5
(the race's speech, 14-10c; `docs/formats/race-speech.md`). RE-6, the
career's screens, was split into RE-6a to RE-6d: RE-6a (the
event trees, `docs/formats/event-tree.md`) is done in Session 71,
RE-6b (RaceEvent, `docs/formats/race-event.md`) in Session 73,
RE-6c-1 (the races an event sets, `docs/formats/event-race.md`) in
Session 74, RE-6c-2 (FrontendDatabase's event functions,
`docs/formats/fred-event.md`) in Session 75, and RE-6d (the career's
end screens, `docs/formats/end-event.md`) in Session 76. Next is the
user's ask of 2026-10-11, Be A Cop "100% working"; TASKS 41 (the
Starting Grid shown before the race has loaded) is done. 14-10d comes after it. Two asks were added to
TASKS.md the same day, with no order given: task 39, the armed
helicopter's missiles and barrels (12k-6), and task 40, the radar
detection meter under the rear-view mirror (12n). The user's device log of
2026-10-10 (`3DS Files/nfshp2_debug.txt`, a Hot Pursuit quick race on
track 43): no hitch and no abort; 15-30 fps in the race, median 24.5,
17-20 with the pack and the cops in view; a spike strip was laid. At
the finish the race went to POSTRACE (rc 7), braked the car to a stop
and sat there: nothing after the finish is ported.

Session 71 (2026-10-11): the user's second device log of 2026-10-10
(a Hot Pursuit quick race on track 62, finished, the End Game Menu's
Quit, then Be A Cop's Select Car to see the points carry over, which
they did). The race ran at a median of 22 fps, 13 at the lowest; the
user called the slowdowns minor. The user also confirmed on the device
that the spike strips work. Select Car after the race showed the
turntable as GLOBALB's DEFAULTTEXTURE checker. The cause:
EndGameFlowLoadingFrontEnd's `eDisableFixUpTables = 0; eFixUpTables()`
had been left out of the port, so after a race FRONTB's solids kept
the default texture their load-time fixup gave them. The flow's new
`fixUpTables` hook runs the two lines (`docs/formats/boot-flow.md`,
"End"). Checked on Azahar: a quit quick race, then Be A Cop's Select
Car, shows the lit brushed-metal turntable. Then RE-6a, the event
trees: FRONTB's two trees load through slot 24, and on a new save
they lock their 19 reward cars and 23 reward tracks, as retail's do,
until RE-6b to RE-6d make the events playable.

Updated in Session 62 (2026-10-09):
the cars' light flares now show -- the cop light bars, headlights and
brake lights -- since the position-marker loader (slot 8) is ported
(`epositionmarker.c`; `docs/formats/car-render-info.md`, "The position
markers"). Before it, 12k-7: the helicopter in the chase. tPursuit's UpdateChopper,
the manager's IsChopperAvailable and RequestChopper and Be A Cop's two
requests are in `pursuitchopper.c` (`docs/formats/pursuit.md`, "The
helicopter"), and the helicopter's seams are bound: a race with cops
has its helicopter, and a chase that asks for it sends it at the chased
car. Before it, 12k-4b: the helicopter's moving, Fly, MoveChopper, DrawChopper
and the dust (`chopper.c`; `docs/formats/chopper.md`, "Moving"). 12k-5
(the ChopperSound) moves to step 14 and 12k-6 (the salvos' munitions,
which are Smokeables) after step 14b, so 12k-7 came next. Before it,
12k-4a: the helicopter's flying, Think and the seven functions under it
(SetXAccel .. SubtractFromYaw, with coputil's MakeRelativeAngle;
"Flying"). Before it, 12k-3b: the helicopter's plans, HighLevelPlanning,
CleverPursuitPlan and BombRunLogic ("Planning"). Before them, 12k-3a: the
helicopter's chase logic, the sixteen functions under its plans
(StartChaseLogic .. AdjustByThinkTime; "The chase logic"). Before that,
12k-3's first part: the route planners the helicopter follows
(ReturnToLastBranch, FindRoutesToTarget, FindPointsToTarget and
FindNearbySignpost, in `airouteplan.c`; `docs/formats/ai-route.md`).
Before them, the light flares. Cars' headlights, brake and reverse lights
and the cops' red, blue and white now glow, and the tunnels' lamps too
(`elightflare.c`, `docs/formats/light-flare.md`). Nothing had drawn
them: eRenderLightFlare was not ported, so the cop lights did not
flash. Before it, 12k-2, the helicopter's object. `chopper.c` builds and frees
the Chopper. It follows and attacks a car, finds the bombing run's
target spot, and places the helicopter in the world and takes it out
(`docs/formats/chopper.md`). Nothing calls it until 12k-7. The same
slice guards a car's collision body with no RigidBody: a cop's hit on
the player read through NULL in the knock test (`carcollisionbody.c`).
Before it, 12k-1 loaded the helicopter's sheet. Each track's ground
polygons for the helicopter now load through slot 23, and FindZValue
finds the height under a point (`docs/formats/helisheet.md`). Before
it, 12j-2b
drew the spike strips. The belt's pieces are
WorldObjects, now drawn in the player's view and the rear-view mirror
(`docs/formats/cop-manager.md`, "Drawing the strips"). Before that, 12j-2a
made the strips' logic: a roadblock with spikes lays its strip, and a
car whose wheels cross it has those tires blown
(`docs/formats/cop-manager.md`, "Spike strips"). Before that, 12j-1
made the radar traps: the manager's SpawnSpeedTraps sends a cop out of
limbo to a radar trap ahead of a racer (`docs/formats/cop-manager.md`,
"Radar traps"). Before that, 12i-3
made RealDriver's ForcedEBrakeStop retail's float timer and bound
MonitorRoadBlock's 5 s stop (`docs/formats/real-driver.md`). 12i-2 made
the roadblock (`docs/formats/pursuit.md`, "Making a roadblock"): a
chase that asks for one gets its cops sent to their spots, with no
barrels (the smokeables are not ported, step 14b) and no spike strip
(12j). 12i-1 ported the roadblocks' running logic, 12h-2
tPursuit::Update and 12h-1 tPursuit's object and RequestPursuit. The
cops' cars wait in limbo until a radar trap or a roadblock calls them
out. A radar trap's search is what starts a chase.
Session 58, continued: 12g-3, the chase (the hot pursuit and caught
speeder logics), so all of tAICop's logic is in. 12g-2 (the radar traps', roadblocks' and patrols' logic) and
12g-1 (tAICop::Think, which made a race with cops make their cars) were
Session 58's earlier slices.
12d to 12f (CopDriver and the drive target, the track graph,
the manager's Think) were Session 57's; 12a to 12c (the cop manager,
the cops, CopMover) Session 56's ("First" below).
Session 54 (2026-10-08): the AI pack runs at 20 FPS with all eight cars in view
(commits 569dfde and ba9ef1f), which the user accepted; see "First"
below. Session 53 (2026-10-08) took out the mid-race hitches
(3b62e00). Session 52
(2026-10-08) made two graphics fixes: a second car of the player's
type drew its wheels alone (eDuplicateSolid was a NULL seam; ported,
d110c44), and skins went missing on TRACKB45 (the upload's scratch now
comes from the linear heap). Then 11h-3, the TrafficTeleporter
(cd443d0), and B in a race no longer pops the frontend's stack
(f539fdf).
**Start at "Now" just below.** Step 11, the racer AI, is under way:
11a, what an AI car knows as it drives, 11b-1, retail's DriveTarget,
11b-2 to 11b-4b, DrivingChoice whole, 11b-4a, CarCollisionPredict, 11c,
AIPlan and the AIAction base, 11d-1 to 11d-3b, all eleven actions,
11e-0, Average at retail's size, 11e-1, AICarController's record,
route methods and actions, 11e-2, its signposts and sticky
decisions, 11e-3, its belt, glue and boost, 11e-4, its horn and
ExecuteCurrentAction, 11e-5, its Think with Timer::CountDown and
Race::CanAICarsStartDriving, 11e-6, the BeltMover, 11f-1,
PsychoDriver, the AI's CarDriver, and 11f-2, AIDriver, the racer's
controller, are done and checked against retail. 11g-1 ran a SkipFE
race with three AI racers (the port's config file) and fixed what
stopped them: GLOBALB's DifficultyInfo chunk was never loaded, so every
skill's SpeedFactor was 0 and the cars sat on the grid. They now race
the route. 11g-2a, the user's way in, is done: Quick Race on Hot
Pursuit's Mode Select starts the race as retail's StartQuickRace does,
and Azahar reaches RACING with three AI racers. 11h-1, TrafficCar, the
traffic's mover, and 11h-2, TrafficDriver, its controller, are done.
11g-2b, Race::Update, is done: the race from the frontend leaves its
countdown at GO, the race time runs, the laps count and the cars
finish. Azahar's run shows lap 1 of 2 with the three AI racers ahead.
11g-2c-1, the camera data and the countdown coordinator, is done: the
3-2-1 is in the drive camera, as on retail. 11g-2c-2a, the fly-by
camera (TrackFlyCameraMover and FlyByCameraCoordinator), and 11g-2c-2b,
the Starting Grid over it, are done: a quick race from the frontend
shows the grid over the fly-by, and A goes on to the countdown.
11g-2d, the pause menu (the user's ask, 2026-10-07), is done: START
pauses, and Resume, Restart and Quit work. 11g-2c-2c-1, the pre-race
coordinator, and 11g-2c-2c-2, BumperCameraMover, are done: after the
grid's A the camera flies INGAMEB's four close-ups round the cars, then
the 3-2-1. 11g-2e, the rear-view mirror, is done: view 3 draws into
its own target and shows top centre in retail's frame. 11h-3, the
TrafficTeleporter, is done: the traffic is placed on its routes, and
moved out of sight at densities of 0.4 and up. Next is the texture
memory work (the user's ask, 2026-10-08, "Next, in this order" below),
then step 12, the cops. The car selector is finished and checked against retail: SC-1
(the logic and 2D), SC-2 (the 3D car on its turntable) and SC-3 (the
effect system and the nebula, commits b7cb25c, 24976dd and 6427cc5).
13b-4f, the device GPU's cost per model, waits on the user's timing
run of 2fc77fc (below).

**The race on the New 3DS XL** (below, "The race on the device"):
- **Speed.** With Session 35's mip chains it runs at 27-29 FPS where
  under about 150 models are in view, the GPU's median 27-30 ms a frame.
  With 200-380 in view the GPU's median is 43-47 ms (up to 58), and the
  race drops to 17-18 FPS (14 at worst). HANDOFF's Session 37 has the
  table.
- **The jump cam is ported and on (Session 37, commits ce37726 to
  6f168b6).** The user's ramp on the device "looked AMAZING". Its log
  (`3DS Files/nfshp2_debug_capture2.txt`) has zone 0 to 6 at world
  frame 3935, 6 to 7 at 3975 and 7 to 0 at 4023, the spans Azahar's run
  had. Its speed was as before: 28.9 FPS and a GPU median of 27.0 ms
  under 150 models in view, 24.6 and 32.0 at 150-199, 16.4 and 46.9 at
  200 or more.
- **The capture.** The device's capture (Session 37) showed no dark box
  in its frame. It showed the light-blue wedge to be the Opel's own
  WINDOW batch (draws 722 and 723), which the device puts one corner of
  above the roof. That is open.
- **With the user.** The build (`3DS Files/NFSHP2-3DS.3dsx`, commit
  2fc77fc) has the nebula, the race's smoke, the indexed meshes, the
  Old 3DS's message and the timing frame's probes. Ask for:
  - the race's `frame:` and `models:` lines in a heavy stretch, and
    whether the FPS there moved from 16-18;
  - a timing run (`sdmc:/nfshp2_gputiming.txt` on the card): the
    models' "1-pixel scissor" less "3 vertices a draw" is the vertex
    work, about 7.5 ms before; the early depth lines say whether that
    test is safe on the device and what it saves, and "RGB8 for RGBA8"
    what the lossless RGB8 would;
  - how the car select's nebula and the chimney smoke look, with the
    `carsel: nebula` and `race: effects` lines;
  - whether the light-blue wedge over the Opel's roof is still there;
  - on their Old 3DS, that the .3dsx now shows "This port needs a New
    3DS" and goes back to the launcher on START (6ac29d1).
Session 31 took the race on Azahar from 20 FPS to 28-30 and
the draw from 39-46 ms to 23 (`docs/formats/draw-cuts.md`). The rest
of 13b-4 (the models, 9 ms; the envmap, 6; the cull, 3) is 13b-4f,
which waits on the device. "Where the port stands" below has the count
of what is left.
`HANDOFF.md` is the running narrative; this file is the short list of what
to do next and what not to trust.

## First: the end of the race, RE-1 to RE-6 (Session 70)

The user's ask of 2026-10-10. After the finish, retail's
RaceCoordinator::TheRaceHasFinished builds EndGameScreens (72 bytes)
and goes to POSTRACE; POSTRACE's ACTIVATE resumes the screens and starts
the demo camera on the race's highlights. Both are NULL seams in the
port (`rcstates.h`, `rcpost.h`), so the race stops at the line. The
code is EndGameScreens.obj, 0x001dc850 .. 0x001e26f0, 24 KB.

The screens, in BuildScreenList's order (0x001dcae0), each with its
test; End Game Menu is always last:

| Screen | Test | Class (ctor) |
|---|---|---|
| Points Rewards | gp-15392 not -1, and IsCarUnlocked(its car, 3) as it answers | 0x001de568 |
| Task Rewards | gp-15388 not -1 | 0x001de6a8 |
| Events Unlocked | an event tree's event, done, with unlocks | 0x001df180 |
| Reward menu | 0x001dc758 | 0x001def38 |
| Be The Cop Results 1P / 2P | 0x001dc6e8 / 0x001dc720 | 0x001e0898 / 0x001e0a10 |
| Race Results | not Be A Cop; GameType not 6; 8 or 9 only off the tourney | RaceResultsScreen 0x001dffe8 |
| Tourney Standings | GameType 8 or 9 at the tourney | 0x001dd5d0 |
| Best Lap Times | not Be A Cop, GameType not 6, a lapped race of 2+ laps | 0x001ddc10 |
| Best Total Times | as Race Results | 0x001ddfd0 |
| End Game Menu | always | EndGameMenu 0x001e12b8 |

"Lap Times 1P"/"2P" (0xc4881cbd/0xc4881cde) are the End Game Menu's
View Lap Times, callback 0x001e10f0. Every other screen's callback is
EndGameMenusBase::Callback (0x001dd278): SCREEN_ACTIVATE builds the
class by the screen's name, UNACTIVATE deletes it, the rest go to its
vtable. EndGameMenusBase::HandleEvent (0x001dd0f0): SELECT goes to the
next screen, BACK to the one before.

The End Game Menu ("RACE OVER", "PURSUIT OVER", "EVENT OVER"): Next
Race, Restart Race, Restart Event, View Replay, View Lap Times and Quit
Race, each shown by its own test, each but two behind an OK/Cancel
popup (MaybeRestart, 0x001e1858). OK posts the race coordinator's
NEXT_RACE (9), RESTART_RACE (8) or QUIT_RACE (10), through the
Autosave screen when ShouldAutoSave.

A Hot Pursuit quick race sees Race Results, Best Lap Times, Best Total
Times and the End Game Menu.

The slices:
- **RE-1, done (Session 70):** EndGameScreens (the tests, BuildScreenList, the list's
  navigation, Resume/Suspend, the autosave bridge), EndGameMenusBase
  (its ctor, HandleEvent and Callback), EndGameMenu (its ctor, the
  label table 0x001e15f0, MaybeRestart, HandleEvent and the popups'
  answers), and the screens' rows in main.c's kScreens. Screens whose
  class is not ported yet get the bare EndGameMenusBase, so SELECT
  passes them. `endgame.c`, `tools/endgame_check.py` (0 differ, 270
  of 272 mutations caught, two equivalent), `docs/formats/end-game.md`.
  The Autosave screen is not ported: main.c's
  SetAutosaveCompletionCallback runs the callback at once. View Replay
  is hidden while RCSTATE_INSTANT_REPLAY has no handler
  (`gEndGameReplayViewableFn`). `screen_registry.py
  --check-port` flags Events Unlocked and Be The Cop Results 1P/2P
  because it reads the demo's ELF; retail registers all three
  (0x001e2018, 0x001e20c8, 0x001e20f4).
- **RE-2a, done (Session 70):** FrontendDatabase's end of a race
  (0x00186e08 .. 0x001878b0): TransientStats and its rows,
  GetOptionsSetFromRace, the bonus and the points, CheckForAbortion,
  TheRaceIsOver, TheRaceWasQuit, TheRaceWasRestarted and
  TheRaceIsLeaving. Also the rewards (0x0024ab90 .. 0x0024b914): the
  tasks' CheckForCompletion, the two reward lists,
  CheckForTaskAndPointRewards and IsCarUnlocked. `fredend.c`,
  `tools/fredend_check.py` (0 differ, 164 of 165 mutations caught, one
  equivalent), `docs/formats/race-over.md`. main.c binds the FED seams,
  `gTransientStatsGetDriverFn`, `gRaceIsLeavingFn`, `gIsCarUnlockedFn`
  and SetAudioDataFromSound. The high scores (MaybeRecordHighScore) came
  with RE-3; the race events stay NULL until step 16.
- **RE-2b, done (Session 70):** RaceResultsScreen (0x001dffe8, Scroll
  0x001e0838, Tick 0x001e0868, the destructor 0x001e23b8),
  tSlideshowStats (0x001df3a0 .. 0x001dfd40), the points tally
  (0x001dfdb8 .. 0x001dffe4, 0x001e2410 .. 0x001e25d0) and
  ShowPointsResults (0x001e0430). Also the Points Rewards and Task
  Rewards screens (0x001de568, 0x001de6a8) with the car count
  (0x001de3a8 .. 0x001de550), GetNumPointsRewardsEarned, the tasks'
  lookups and the car counts (0x0024af40 .. 0x0024b430). `endresults.c`,
  `tools/endresults_check.py` (0 differ, 144 of 144 mutations caught),
  `docs/formats/race-results.md`. main.c binds the three classes'
  constructors and RenderTextIntoGroup. The race event's rewards stay
  NULL until step 16. The two speeches are bound since RE-5.
- **RE-2c, done (Session 70):** the race-over overlay's message,
  which had read "You finished" twice (the layout's placeholder):
  FillInRaceOverMessages (0x00181558) with its two format helpers
  (0x00181498, 0x00181500), and FEFlailer's RenderTextIntoGroup
  (0x00144ba0) with WriteTextIntoChunk and isspace. `raceovermsg.c`,
  `flailerwrap.c`, `timer_print_to_string_rounded` in `timer.c`,
  `tools/raceover_check.py` (0 differ; 64 of 66 mutations caught, 2
  equivalent), `docs/formats/race-over-overlay.md`. The knockout
  speech seam is bound since RE-5.
- **RE-3, done (Session 70):** the records and the screens that list
  them. MaybeRecordHighScore (0x00186af0), the name table (0x00186a20,
  0x00186a50) and the two table lookups (0x00186d98, 0x00186dd0) are in
  `highscore.c`. BestLapTimes (0x001ddc10), BestTotalTimes (0x001ddfd0),
  WhichPlayerSet*Record (0x001ddb80, 0x001ddbc8) and the Lap Times
  screens (0x001e0bd0 .. 0x001e10f0) are in `endtimes.c`.
  `tools/endtimes_check.py` gives 0 differ and catches all 95 mutations;
  the decode is `docs/formats/best-times.md`. main.c binds both
  constructors, the Lap Times rows, MaybeRecordHighScore and
  SetRecordTimesToBeat. The two record speeches are bound since RE-5.
- **RE-4, done (Session 70):** the post-race camera.
  DemoCameraCoordinator (0x0019a440 .. 0x0019abd8), the near-plane test
  (0x001044c8) and Player::BeginDemoCameras (0x00176868) are in
  `democam.c`. `tools/democam_check.py` gives 0 differ; of 152
  mutations it catches 149, and 3 are equivalent. main.c binds the
  coordinator's constructor, BeginDemoCameras and the TrackCar and
  Drive mover seams. PostRaceCameraCoordinator (0x0019b280) is dead in
  retail: nothing builds it. With no replay, the camera shows the live
  race. Seen in Azahar on TRACKB12: highlight shots behind the end
  screens, and the drive camera where no highlight holds the car. The
  End Game Menu shows Restart Race, View Lap Times and Quit Race.
- **RE-5, done (Session 70):** 14-10c, the race's speech, all of
  RaceSpeech.obj (0x00206900 .. 0x00207870) in `racespeech.c`, and
  Speech's conversions (0x00223328 .. 0x00223480, ConvertTrackNumber
  too) in `speechconv.c`. `tools/racespeech_check.py`: 773239 ops,
  90612 lines, 0 differ; 516 mutations, 512 caught and 4 equivalent. It
  found one bug: a lap record over a 0 best (retail's delay slot says
  none). main.c binds the finish, the laps, the knockout, the two
  records, the reward car, the points, the pullover and Be A Cop's
  arrests. The event's won test is RaceEvent's since RE-6b; the
  tournament's, the event's and its reward's speeches wait for RE-6;
  PlayBustedSpeech waits for BeACopThink (12m). Azahar's Quick Race
  (seven AI) said event 160 after each lap and 165 for seventh place.
  `docs/formats/race-speech.md`.
- **RE-6, done (Sessions 71 to 76):** split into RE-6a (the event
  trees, done in Session 71: `eventtree.{c,h}`,
  `docs/formats/event-tree.md`), RE-6b (RaceEvent, done in
  Session 73: `raceevent.{c,h}`, `docs/formats/race-event.md`),
  RE-6c (the races an event sets; RE-6c-1 done in Session 74:
  `eventrace.{c,h}`, `docs/formats/event-race.md`; RE-6c-2 in Session
  75: `fredevent.{c,h}`, `docs/formats/fred-event.md`) and RE-6d (the
  screens, done in Session 76: `endevent.{c,h}`,
  `docs/formats/end-event.md`): Tourney Standings (with
  `tournament_race_speech`), the Reward menu (0x001def38, with
  `race_event_speech` and `race_event_reward_speech`), Events Unlocked
  and the two Be The Cop Results. Be A Cop's results show after its
  races now; the event screens wait for step 16's event tree, which
  starts the events (GameType 4, 8 and 9).

## Step 12, the cops and cop mode (Session 56)

The user, 2026-10-08: "When you're done doing whatever, move on to cops
and cop mode." The texture memory work is done (2f0a300, HANDOFF's
Session 55): a cache that evicts the least recently drawn, and about
4 MB of textures in VRAM. The skins' padding (e) waits for a map that
needs it. TRACKB12 still wants a look on the device.

Step 12 is retail's copmgr.obj, cop.obj, copdriver.obj, coputil.obj and
pursuit.obj, on a 10 KB manager. Its slices:

- **12a, done (Session 56):** tCopManager's record, LoaderCops, the
  constructor and destructor, InitCops and CleanupCops, the roadblock
  and radar-trap spots, the speakers' queue, FindLandmark, the pursuit
  ids, GetCopByCar and MonitorImpact, with retail's AddDamage tail
  (`docs/formats/cop-manager.md`). A race with cops builds the manager
  and runs at 30 FPS; no cop is on the road yet.
- **12b, done (Session 56):** tCop, tAICop and tPlayerCop's records,
  constructors and destructors, the setters, ClearPursuit and
  ClearSpeedTrap, CreateCop, AddCopCarToRace, `0x002276a0` (the cop
  cars' largest size), the zone permissions, and tAICop::DisableMyCar,
  now bound to `gAICopDisableMyCarFn` (`docs/formats/cops.md`).
  `gAddCopCarToRaceFn` stays NULL until 12d: COP_CONTROL needs
  CopDriver's constructor (`0x001a1ce8`, `gCopDriverCtorFn`), and a cop
  on the road needs Think. tPursuit's RemoveCopFromPursuit and
  RemovePrimarySpeaker, and CarDamage's wreck, are NULL seams that
  abort.
- **12c, done (Session 56):** CopMover, the mover a cop car rides away
  from the players: STEERING (a speed along a heading) and TRANSLATING (a
  velocity), held to the ground and sat on five height samples
  (`docs/formats/cop-mover.md`). `gCopMoverCtorFn` is bound;
  `COPMOVER_SIZE` is `sizeof`, retail's 128. Nothing builds one until
  CopDriver does.
- **12d, done (Session 57):** CopDriver, the controller an AI cop's
  car gets (`docs/formats/cop-driver.md`), with tAICop's drive target
  (IsNearPursuitTarget, InitializeDriveTarget, UpdateDriveTarget;
  `cops.md`), CarInRecentCollision (`coputil.c`), and tPursuit's near
  and far drive targets and history (`copmanager.h`).
  `gCopDriverCtorFn` is bound. `gAddCopCarToRaceFn` stays NULL until
  the cops can think (12f, 12g): a Hot Pursuit race would otherwise
  reach tAICop's NULL Think.
- **12e, done (Session 57):** tTrackGraph, the racing routes as a
  graph of signposted vertices and the edges between them, each with
  its roadblock and radar-trap spots; FindRoadBlock and FindSpeedTrap
  walk up to five edges from a car (`docs/formats/track-graph.md`).
  With it, `coputil.c`'s GetForwardTrackDistance and
  IsTeleportLocationClear. `gInitTrackGraphFn` and
  `gCleanupTrackGraphFn` are bound: every World builds the graph.
- **12f, done (Session 57):** tCopManager::Think and GlobalCopThink,
  now bound to `gGlobalCopThinkFn`: TimeBasedSpeech,
  SupervisorActivate, PursuitManagement, FindPlayerPursuit,
  MonitorPullovers, ReclaimPatrollers, the pursuable timers, each
  cop's Think through its table, and the landmark that uncloaks the
  graph. tPursuit's AboutToSaySomething and NotInChasingState are in
  `copmanager.c`. tPursuit::Update, the supervisor's test, the speech,
  SpawnSpeedTraps, MonitorSpikeBelts, EndPullover and BeACopThink are
  NULL seams that do nothing (`docs/formats/cop-manager.md`).
- **12g-1, done (Session 58):** tAICop::Think (`0x0022df88`) with
  HandleStateTransitions, MovementModeTransitions, the limbo, disabled
  and guard logics (they hold position), and the manager's
  ResetAllDamage (`docs/formats/cops.md`, "Think"). The sub-states are
  in retail's numbering (b94f189): two values the demo lacks sit at 1
  and 2, so PURSUIT_FOLLOW is 3 and CAUGHTSPEEDER_WAITING 16.
  `gAddCopCarToRaceFn` is bound: a Hot Pursuit race makes its four cop
  cars, each in limbo (not drawn, parked, not colliding), and still runs
  at 30 FPS. The seven state logics (`gAICopInit...`/`gAICopDo...LogicFn`)
  and tPlayerCop's Think (`gPlayerCopThinkFn`) are NULL seams that do
  nothing. `eefpu.h` has `ee_mul` (the EE's FLT_MAX for an overflowing
  product), and `mipsemu.py` its `eemul` twin.
- **12g-2, done (Session 58, continued):** the radar traps', roadblocks'
  and patrols' Init and Do logics, Teleport, SetSpeedTrap and
  SetRoadBlock, IsValidPursuitTarget and CanPatrollerSeeThisCar in
  `cop.c`, and CanTeleport and CarCausedRecentCollision in `coputil.c`
  (`docs/formats/cops.md`, "Radar traps, roadblocks and patrols").
  tRoadBlock's `pos` and `ang` are now `CopPos[2]` and `CopAng[2]`, as
  the code reads them. The searches ask tCopManager::RequestPursuit
  through `gCopManagerRequestPursuitFn`, a NULL seam that grants no
  chase until 12h. Only the hot pursuit and caught speeder logics are
  still seams. None of these logics use sub-state 1, so it stays
  unnamed.
- **12g-3, done (Session 58, continued):** DoHotPursuitLogic and its ten
  sub-logics, ReturnToPatrol and GetBestFlankSide, and
  DoCaughtSpeederLogic in `cop.c`; DidTheseCarsCollide in `coputil.c`
  (`docs/formats/cops.md`, "The chase"). Think calls both logics
  straight, so `gAICopDoHotPursuitLogicFn` and
  `gAICopDoCaughtSpeederLogicFn` are gone. No cop reaches them until
  RequestPursuit grants a chase. DoSegmentsIntersect (`0x00230f00`) was
  not needed.
- **12h-1, done (Session 59):** `pursuit.c` and `barricade.c`. They
  hold tPursuit's constructor and destructor, its states and their
  timers, the cops joining and leaving, the speakers and the
  one-liners. With them: RequestPursuit, NewPursuit,
  PossibleCallSupervisor, DeleteRoadBlockSpikeStrips, GetTopSpeed and
  retail's new BarricadeManager (`docs/formats/pursuit.md`).
  - `main.c` binds RemoveCopFromPursuit and RemovePrimarySpeaker.
  - Retail quirks kept: ReleaseAllCops releases only the first of two
    cops. An empty speaker queue gives the constructor 0x41a00000
    (its a2, 20.0f).
- **12h-2, done (Session 59):** tPursuit::Update (`0x00229288`) in
  `pursuit.c`, with its parts:
  - Level0SubStates, ShouldPursuitBeCalledOff, UpdateDriveTargets and
    tPursuitHistory::Update;
  - the roadblock state machine's Update, and the barrels' count down
    (`0x0024f268`, `barricade.c`);
  - DoEarlyChaseCollisionCheck and IsChasedCarStoppable, with Be A
    Cop's half and the chase direction;
  - the manager's IsCopNearby and DidRecentlyCollideWithCop.

  `main.c` binds `gCopManagerRequestPursuitFn` and `gPursuitUpdateFn`.
  These are NULL seams that do nothing:
  - Update's five speeches;
  - CreatePullover (12l);
  - CreateRoadBlock and UpdateRoadBlocks (12i);
  - UpdateChopper (12k).

  12h-1's GetSpeedMPHOrKPH read VelocityMagnitude; retail reads
  ForwardSpeed (car+960), now fixed.
- **12i-1, done (Session 59):** the roadblocks' running logic in
  `pursuit.c`: RequestRoadBlock (`0x0022cc38`), MonitorRoadBlock
  (`0x0022c390`), RoadBlockDefeated (`0x00229970`) and UpdateRoadBlocks
  (`0x00229b58`).
  - `main.c` binds `gPursuitUpdateRoadBlocksFn`.
  - New NULL seams that do nothing: six roadblock speeches, the bust
    sound, and RealDriver::ForceEBrakeStop
    (`gRealDriverForceEBrakeStopFn`, 12i-3).
  - An AI car that hits a roadblock cop gets its PsychoDriver's
    EBrakeTimer set to 4 s, the timer's second writer
    (`psycho-driver.md`).
  - The DodgeRoadblock replay event is skipped while `pReplayManager`
    is NULL. The demo disc's branch in RoadBlockDefeated is left out.
- **12i-2, done (Session 59):** making a roadblock, in `pursuit.c`
  and `barricade.c`: CreateRoadBlock (`0x00229e30`), the manager's
  (`0x00226298`), FindCopsForRoadBlock (`0x00226810`), the escape
  lane (`0x0022ca78`), the layout (`0x00226478`) and its ten lists,
  the plan's code (`0x0024fae8` to `0x00250150`), and the barrels'
  spawn (`0x0024f0a8`).
  - `main.c` binds `gPursuitCreateRoadBlockFn`.
  - New NULL seams: RoadBlockSetSpeech (says nothing), AddSpikeStrip
    (12j, lays nothing), and the smokeables' FindSmokeableInfo (finds
    nothing, so no barrel) and spawn (aborts if reached), step 14b.
  - Retail quirks kept: the escape lane's spot is half a lane past
    the lane, and a closed left lane doubles the right one.
- **12i-3, done (Session 59):** retail's e-brake stop in
  `realdriver.c`. ForcedEBrakeStop (580) is a float, the seconds left.
  ForceEBrakeStop (`0x0013b558`) stores it, and DoThrottleBrakeReverse
  (`0x0013bb40`) runs it down by dt. It holds the e-brake while time is
  left and the car is faster than 20 mph, then clears.
  - `main.c` binds `gRealDriverForceEBrakeStopFn`, so a player who
    hits a roadblock cop is braked for up to 5 s.
  - `realdriver_check` has a retail run for it (`OP_RETAIL`); the demo
    scenarios keep the stop at 0.
- **12j-1, done (Session 59):** SpawnSpeedTraps (`0x00224a20`) and
  FindCopForSpeedTrap (`0x00224838`) in `copmgr.c`.
  - `main.c` binds `gCopManagerSpawnSpeedTrapsFn`, so a ready cop in
    limbo is sent to a radar trap ahead of a racer that wants one.
  - The want follows retail: the roll by difficulty, the chase's cops
    and backup, the split to the leader against -15 s, and an AI
    racer's tickets against its laps.
  - `copmanager_check` also fixed two mutations that had gone stale
    since 12h-1's rename (`copmanager_replaying`).
- **12j-2a, done (Session 60):** the spike strips' logic, in the new
  `spikestrip.c` and `worldobject.c`: tSpikeStrip (`0x00241308` ..
  `0x00241ae0`), its belt pieces, AddSpikeStrip (`0x002276d0`),
  MonitorSpikeBelts (`0x00227758`), WorldObject's constructor and
  destructor, InitWorldObjects and CloseWorldObjects, and
  DoSegmentsIntersect (`0x00230f00`, `coputil.c`).
  - `main.c` binds `gCopManagerAddSpikeStripFn`,
    `gCopManagerMonitorSpikeBeltsFn`, `gSpikeStripBlinkBlinkPoofFn`,
    `gInitWorldObjectsFn` and `gCloseWorldObjectsFn`.
  - A car whose wheels cross a strip has those tires blown. An AI
    racer is told to pull over and slowed; a player's car gets the
    short slow motion. The pull-over itself is CreatePullover (12l).
  - `tools/spikestrip_check.py`: 3193 lines, 0 differ; 116 mutations,
    115 caught, one equivalent. `trackgraph_check` checks
    DoSegmentsIntersect alone, its 20 mutations all caught.
- **12j-2b, done (Session 60):** drawing the belt, in
  `worldobject.c`: WorldObject::Render (`0x001cd998`), with
  eModel::IsVisible (`0x0010cea8`), and RenderWorldObjects
  (`0x001cdb20`).
  - `trackview.c` sets the current view (eSetCurrentView) and draws
    the world objects after StuffSun and before the effects, in the
    player's view and the rear-view mirror.
  - SPIKEBELT_00 is in INGAMEB.BUN's solid list eLabInGame, which the
    port never loaded. `load_shared_packs` now loads INGAMEB's three
    solid lists, once, with the first track: the loader's relocation
    is not safe to repeat.
  - The race log counts the world objects and the strips.
  - `tools/spikestrip_check.py`: 742 operations, 6337 lines, 0 differ;
    32 more mutations, all caught.
  - A test build laid three strips ahead of the player in Azahar: the
    belts lay across the road, with the spikes upright, at 30 FPS.
- **12k-1, done (Session 60):** the HeliSheet, in `helisheet.c`:
  LoaderHeliSheet (`0x001ebd20`), UnloaderHeliSheet and
  HeliSheet::FindZValue (`0x001ebad8`), with PointInPoly and ZValue.
  - Slot 23 of the LoaderTable now loads it. Retail's chunk is a
    container, `0x80034800`, of the 536-byte sheet and the polygons.
    The polygon count is worked out from the second child's size, less
    a pad to 16 in memory.
  - The race log's world-objects line ends with the sheet's polygon
    count: 897 on track 16, as in the file.
  - `tools/helisheet_check.py`: every container on the card, at each
    misalignment, plus edits for each edge of the search. 54,570 ops,
    38,140 lines, 0 differ; 50 mutations, all caught.
  - `tools/loadertable_check.py` had not linked since 12a wired slot
    15. It links again, with `tools/src/loadertable_copstubs.c` for
    what the rest of `copmgr.c` calls. Demo 1,617 lines, retail 49,626,
    0 differ; 156 mutations, 154 caught, 2 equivalent.
  - Azahar: a Hot Pursuit quick race at 30 FPS and Speed 100%.
- **12k-2, done (Session 60):** the Chopper object, in `chopper.c`.
  That is the constructor (`0x001e7a90`), destructor and
  ClearVariables, plus FollowThisCar, AttackCar, AdjustBombTarget,
  ShiftTarget and FindUnobstructedSpot. Also FindGroundHeight,
  Place/RemoveChopperInWorld and ChopperBehindCar. Then
  RotateToChopperCoord (with coputil's RotateVector, `0x002313e0`),
  GetMaxDeceleration and AbortBombingRun. Then Mute, UpdateSound, the
  two route-point finders, CalcMatrix and the WorldObject's update.
  - Retail's Chopper is 976 bytes: the layout is in `chopper.h` and
    `docs/formats/chopper.md`. The bombing runs' table (`0x0031a7c8`)
    has five rows; the demo's enum has four types.
  - The port's divergences: no ChopperSound unless
    `gCreateChopperSoundFn` is set (task 29), with every call through
    it skipped; and FindUnobstructedSpot's flags word starts at 0,
    where retail's first miss reads its stack.
  - `tools/chopper_check.py`: 3,667 ops, 25,881 lines, 0 differ; 213
    mutations, all caught. A yaw just under 180 (180 - 359/65536)
    catches CalcMatrix's `< 0` against `< 1`.
  - **The knock fix.** Azahar's first run logged sixteen unmapped
    reads at 0x11C in carcollisionbody_get_mass_inverse. The user saw
    a cop hit them. A cop that a collision puts in MELLOW_MOVEMENT can
    go back to COP_MOVEMENT before the Player's knock test reads the
    collision, and then its body has no RigidBody. Retail reads the
    PS2's word at 0x11C; the 3DS would abort. The port answers 0, as a
    static body does, and the knock test (under 500?) is unchanged.
    `tools/collisionbody_check.py` asks a car body with no RigidBody
    for its mass: 0 differ, and the guard's two mutations are caught.
- **The light flares, done (Session 60):** `elightflare.c`.
  eLightUpdateTextures (`0x00116488`), eRenderLightFlare
  (`0x001164f0`) with its part renderer (`0x00116118`), and
  eRenderWorldLightFlares (`0x00116778`); retail's nine parts
  (`0x002d6080`, 60 bytes each) and ten types (`0x002d62d8`).
  - Bound: PostLoadFixup's `gELightUpdateTexturesFn`, CarRenderInfo's
    `gERenderLightFlareFn` (main.c), and ePoly::Render3D as the new
    `gEPolyRender3DFn`, which trackview.c draws as a four-vertex strip
    through the strip builder (`render_epoly_3d`). The world's flares
    (the tunnels' `EF_TunnelA`) draw after the world objects, in the
    main view and the mirror.
  - The divergence: a Type outside 0..9 draws nothing (retail indexes
    the table unchecked).
  - `tools/lightflare_check.py`: 3,143 ops, 5,499 lines, 0 differ,
    1,034 polys drawn; 96 mutations, all caught.
  - **Azahar, on AC (2026-10-09):** 30 fps at 100% speed, the
    headlights glow, and a pursuit with wanted stars. The user saw the
    cop's light bar flash. That run was also 12k-2's rerun after the
    knock fix: no abort. A longer run ended "reached RACING, then
    died" because the user closed it: the held A stopped them driving.
- **12k-3's planners, done (Session 60):** `airouteplan.c` gains
  ReturnToLastBranch (`0x001cc130`), FindRoutesToTarget (`0x001cc270`),
  FindPointsToTarget (`0x001cc5d0`) and FindNearbySignpost
  (`0x001cc838`), with the two deques as `RoutePlanRoutes` and
  `RoutePlanBranches`.
  - The divergences, none on a shipped track: ReturnToLastBranch with
    the routes run out answers 0; a branch with no point counts as
    running off; the look through a full routes deque stops at twenty;
    the walk gives up after `ROUTEPLAN_MAX_WALK` (0x11800) steps.
  - `tools/routeplan_check.py`: 81,092 ops, 100,285 lines, 0 differ.
    Of 98 mutations, 97 are caught and 1 is equivalent.
  - 12k-3a's FollowRoute and FindPreviousFork call FindPointsToTarget
    and FindNearbySignpost.
- **12k-3a, done (Session 60):** the chase logic in `chopper.c`,
  StartChaseLogic (`0x001e8590`) .. AdjustByThinkTime (`0x001e9940`),
  sixteen functions, with `ChopperTarget` (12 bytes: Location and
  DesiredSpeed).
  - The divergence: HangoutNearHere stops after a miss once both
    offsets are below the least normal float, or NaN. The EE has
    flushed them to zero by then, and the image tries the point itself
    for ever.
  - `tools/chopper_check.py`: 9,820 ops, 84,153 lines, 0 differ. Of
    378 mutations, 376 are caught and 2 are equivalent: the stakeout's
    index done by a divide, and by an unsigned shift.
  - Azahar, on AC: a quick race with cops, PASS at 29.9 fps. Nothing
    calls the chase logic until 12k-3b.
- **12k-3b, done (Session 60):** the plans in `chopper.c`,
  HighLevelPlanning (`0x001e9648`), CleverPursuitPlan (`0x001e9150`) and
  BombRunLogic (`0x001e9398`).
  - FireSalvo (`0x001ea8c0`) is a placeholder in the new
    `chopperfire.c` until 12k-6; the run still counts its salvos.
  - The divergence: BombRunLogic skips the car's progress when the
    car's point or OldCarPoint is NULL, where the image reads address 0.
  - Fly (`0x001ea7d0`) skips Think in EATING_DONUTS, the one plan
    whose CurrentCar may be NULL, so the planning always has a car.
  - `tools/chopper_check.py`: 31,633 ops, 279,448 lines, 0 differ. Of
    524 mutations, 519 are caught and 5 are equivalent: 12k-3a's two,
    and HighLevelPlanning's starting on_sheet, flags and z, which
    nothing reads unless FindZValue set them.
  - Azahar, on AC: a quick race with cops, PASS at 30.0 fps. Nothing
    calls the plans until 12k-4's Think.
- **12k-4a, done (Session 61):** the flying in `chopper.c`: Think
  (`0x001e9d48`), SetXAccel (`0x001e9950`), SetYAccel (`0x001e9a20`),
  SetRotateTarget (`0x001e9ae8`), HoverTime (`0x001e9b30`),
  CheckMomentumWithinBounds (`0x001e9c68`), CalcChopperRotation
  (`0x001e9e40`) and SubtractFromYaw (`0x001e9e80`), with coputil's
  MakeRelativeAngle (`0x00231478`).
  - No divergence. HoverTime reads the car's heading unsigned, and the
    momentum's push is gp-28008, `0x3e999999`, kept as `0.29999998f`.
  - `tools/chopper_check.py`: 64,934 ops, 600,739 lines, 0 differ. Of
    632 mutations, 627 are caught and 5 are equivalent, the earlier
    slices' five.
  - Nothing calls Think until Fly (12k-4b).
- **12k-4b, done (Session 62):** the moving in `chopper.c`: Fly
  (`0x001ea7d0`), DoTweakerTriggers' egg part (`0x001ea6c8`),
  MoveChopper (`0x001e9ee8`), DrawChopper (`0x001ea3b0`) and
  TriggerDustEmitter (`0x001ea5c0`).
  - The divergences: a NULL ChopperPoint is on neither side in
    MoveChopper, where the image reads address 0, and the munitions'
    step is the seam `gMunitionEffectsDoTimestepFn` until 12k-6. The
    tweaker's two triggers are debug, and left out.
  - `tools/chopper_check.py`: 86,504 ops, 821,720 lines, 0 differ. Of
    741 mutations, 736 are caught and 5 are equivalent, the earlier
    slices' five. MoveChopper's pitch cap of 20 is never reached (the
    speed is at most 100, and 0.15 of it is 15), so it has none.
  - Azahar, on AC: a quick race with cops, PASS at 30.0 fps. Nothing
    calls Fly until 12k-7.
- **12k-5 moves to step 14.** The ChopperSound (CreateChopperSound
  `0x00215098`: bMalloc(48) and the constructor `0x00214d68`; table
  `0x002bc2a8`) is a Sound3d, and no in-race sound is ported yet. Until
  then `gCreateChopperSoundFn` stays NULL and the helicopter is silent.
- **12k-6, done (Session 87; `docs/formats/munitions.md`).** FireSalvo's munitions are
  Smokeables: Munition (`0x001be6c8`) and DroppedBomb (`0x001beae0`)
  under Rocket (`0x001bf340`), SmokeBomb (`0x001beb90`) and
  DroppedSpikes (`0x001bee88`), with the MunitionEffectsHandler
  (`0x001bf980` .. `0x001bfad0`). They need the Smokeable base (step
  14b) first. What FireSalvo does, decoded:
  - FireSalvo (`0x001ea8c0`) copies Matrix and takes the row of
    `0x0031a7c8` (32 bytes each) for BombRunType: +0 the kind (0
    rocket, 1 SmokeBomb, else DroppedSpikes), +8, +12, +16 the count
    n, +24 the spread.
  - n == 1, a rocket: m.v3.z -= gp-27968, and an offset (gp-27964,
    gp-27960) whose y is gp-27956 from NextLauncher 2 on and negated
    for an odd one, rotated by Yaw onto m.v3.xy. NextLauncher counts
    to 4 and wraps.
  - n == 1, a bomb: m.v3.z -= gp-27952; with a spread f > 0, f =
    World::Random(f) - f / 2 (`0x0014e548`). Then Launch(f, m).
  - n > 1: (0, -(n - 1)) by Yaw onto m.v3.xy, the step that times
    -2 / n, m.v3.z -= gp-27948, f = -(spread / 2) * (n - 1); n times
    Launch(f, m), then m.v3.xy += step and f += spread.
  - Launch (`0x001eab70`): a replay event (gp-22440, 4.0, string
    `0x002b98e0`) for a car whose +24 is set and +964 over 30. A
    rocket aims at the car's position (`0x001ead08`, the row's +8 as
    the speed): Rocket from its pool (gp-18440) and LaunchRocket
    (`0x001bf528`). A bomb's velocity is (+12, f / ((GroundZ -
    CurrentPos.z) / +8), +8) with xy by Yaw (`0x001eacb0`), from the
    SmokeBomb pool (gp-18436) or DroppedSpikes' (gp-18432), and
    LaunchBomb (`0x001bfe90`).
- **12k-7, done (Session 62):** the helicopter in the chase, in
  `pursuitchopper.c`: tPursuit's UpdateChopper (`0x00229678`) and
  IsChopperNearCar (`0x0022bab8`), and tCopManager's IsChopperAvailable
  (`0x00224ec0`), RequestChopper (`0x00224f00`), BeACopRequestChopper
  (`0x002287d8`) and BeACopRequestRoadBlock (`0x002288c8`). The speech
  manager's raiseRotorRequest, raiseRotorConfirm and
  raiseDispatchHelicopterNA are seams, NULL until task 29.
  `docs/formats/pursuit.md`, "The helicopter", has them.
  - The divergence: Be A Cop's requests take the player cop through
    `copmanager_get_player_cop`, so no cop is no chase; retail reads the
    cop with no test.
  - `hudrender.c` keeps its own copy of IsChopperAvailable
    (`can_call_helicopter`), the same test, so its harness need not
    link `chopper.c`.
  - `tools/pursuitchopper_check.py`: 136,412 ops, 36,879 lines, 0
    differ. 107 mutations, all caught.
  - `main.c` binds gChopperCtorFn, gChopperDestroyFn, gChopperFlyFn,
    gChopperNew960Fn, gChopperFollowThisCarFn, gPursuitUpdateChopperFn
    and Be A Cop's two request seams. A new "race: chases" log line has
    the first chase's helicopter side and the helicopter's plan and
    place.
  - Azahar, on AC: a quick race with cops, PASS at 30.0 fps, the
    helicopter made and idle (plan 6). A chase asks for it only after a
    dodged roadblock at level 3 (RoadBlockDefeated), which the run did
    not reach.
- **The position markers, done (Session 62):** the user's report
  (2026-10-09) that the cop light bars did not light. No car had any
  flare: the position-marker loader (chunk 0x34013, slot 8) was never
  ported, so `PositionMarkerList` stayed empty and CreateCarLightFlares
  found nothing. LoaderPositionMarkers (`0x001a7e90`) and
  UnloaderPositionMarkers (`0x001a7f08`) are now in `epositionmarker.c`
  and in both tables. Each car's GEOMETRY.BIN starts with one (44
  chunks, 956 markers on the disc).
  - `tools/positionmarker_check.py`: 12,145 ops, 14,676 lines, 0
    differ; 27 mutations, all caught. `loadertable_check.py` calls slot
    8 of both tables on a one-record chunk and checks the list (2 more
    mutations, caught); 49,626 retail lines, 0 differ.
  - Azahar, on AC: a Hot Pursuit quick race, PASS at 30 fps; 24 cop
    flares on the 4 cops, the chasing cop's red, white and blue bar in
    the rear-view mirror, and the player's brake lights glowing.
  - The "race: cop cars" log line counts the cops, those with lights
    on, their flares, and the flares asked for and drawn.
- **12l-1, done (Session 63):** the pullovers, in `pullover.c`:
  tCopManager's CreatePullover (`0x00226f30`), EndPullover
  (`0x00225878`) and the NIS's callback to it (`0x00225868`),
  GetArrestingOfficer (`0x00225c40`) and RemoveSpeedTrapsForCar
  (`0x00228538`), tAICop::DoneWritingTicket (`0x00230c58`), and the
  Player's StartBustedDisplay and StopBustedDisplay (`0x00228f08`,
  `0x00228f00`). `docs/formats/pullover.md` has them.
  - A chase that stops its car, or a spike strip, pulls it over. A
    player gets a ticket, or an arrest at nNumTicketsBeforeArrest; an
    arrest finishes the car's race.
  - The speech calls (raiseRacerCaught, the pull-over event, Be A Cop's
    arrests, AITicketSpeech) are seams for step 14.
  - `tools/pullover_check.py`: 212,448 ops, 161,773 lines, 0 differ.
    145 mutations, all caught.
- **12l-2, done (Session 63):** the ticket and arrest NISes' timing.
  `docs/formats/nis.md` has them.
  - `nisinfo.c`: LoaderNisInfo (slot 20) and the three lookups.
  - `nismanager.c`: the NisManager's constructor and destructor, Start,
    Stop and Unload.
  - `playernis.c`: PlayNextNis, ServiceNis, CreateRandomNisArray,
    UpdateGameState with DetectWrongWay, IsAllowedToReset and
    ChooseToDisplayReset, and UpdatePlayersGameState.
  - `player.h`: retail's 180 and 184 are the trouble watch's
    fTroubleSpeed and tTroubleSpeedTimer, where they were New180 and
    tZoneSoundTimer.
  - `main.c` now gives GLOBALB's NIS chunk to `loader_nis_info`. Without
    it every NIS was 0 frames long. The "car data:" line counts 8 NISes.
  - The NIS player is not ported: Load, the posing, the animation, the
    NIS camera and LoadNextNis (`0x001761e8`). The view stays on the
    stopped car under the camcorder overlay for the NIS's time.
  - `tools/nis_check.py`: 17,748 ops, 40,372 lines, 0 differ. 97
    mutations, 96 caught, 1 equivalent.
  - `tools/playernis_check.py`: 173,532 ops, 89,260 lines, 0 differ.
    150 mutations, 147 caught, 3 equivalent.
  - `loadertable_check.py` (slot 20) and `player_check.py` (the renamed
    fields): 0 differ.
  - Azahar 2126.2, on AC: a Hot Pursuit quick race on track 26, PASS at
    30 fps. The chase caught the stopped player, and NIS_Ticket04 played
    on camera 1 for 282 world frames under REC, the date, the time and
    BUSTED!. The car came back blinking with one ticket. The log's
    "race: player NIS" line follows the NIS.
  - `run_azahar_quickrace.ps1 -HoldPlan` runs holds in turn. The user,
    2026-10-09: no braking in these runs.
- **Now: step 14, the audio in full.** The user, 2026-10-09: after 12l,
  the engines, sirens, cop speech and radio, and the world's sounds,
  before anything else. The slices:
  - **14-1, done:** bSound, bSample, bRegion and bVoiceMgr
    (`bsound.c`, docs/formats/bsound.md), over bsnd.c's new
    LockChannels and patch queries. `tools/bsound_check.py` runs
    retail's library (0x002716f8-0x0027c730) in mipsemu against the
    port over one fake driver: 33 runs, 50664 lines, 0 differ; 101
    mutations, 99 caught, 2 equivalent. main.c makes the one bSound
    after bsnd_hw_init, and bsound_update is the last of sound::Update
    in the frame, replacing the bare bsnd_update. Found on the way:
    retail's vector erase of a region that is not there drops the last
    region from view, and on an empty vector breaks it for good (the
    port leaves an empty vector alone).
  - **14-2a, done:** the game's sound module, Sound.obj (`sound.c`,
    docs/formats/sound.md): InitializeSoundDriver (0x001ae608, with
    sound's callback 0x001ae3c8 and the wait for "common"),
    LoadSoundRegionsInGame (0x001ae798) and the frontend's, the region
    loader (0x001ae340), UnLoadSoundRegions (0x001af420), sound::Update
    (0x001af4c0) in full with the twenty-second hang, the muffler,
    ScaleCategoryVolumes, the mutes, the samples, the random and the
    audio mode, over hooks for what is not ported yet.
    `tools/sound_check.py` runs retail's Sound.obj in mipsemu against
    the port over one fake bSound: 1252 ops, 5919 lines, 0 differ; 206
    mutations, 204 caught, 2 equivalent. Azahar, on AC: a Hot Pursuit
    quick race, PASS; the log has "common in", "loaded sound regions"
    and "sound regions: InGame Parkland NewENeo" (driver number 1 is
    none in a one-player race, so one car). The user heard the 3-2-1
    beeps; no engine or siren yet, which are 14-3 and 14-4.
  - **14-2b, done:** Sound3d (0x00208ae8 .. 0x002091a0), sound3d_oneshot
    (0x002091d0 .. 0x002093d8) and Sound3dSample (0x002094b0 ..
    0x00209e98), with GetActiveCameras (0x001cf268), the sound scape's
    (`sound3d.c`, docs/formats/sound3d.md). The two vtables are
    installed at boot; sound.c's one-shot hooks and RaceCoordinator's
    Reset seam are set. `tools/sound3d_check.py` runs retail's
    Sound3d.obj in mipsemu, with the EE's divide, product and root,
    against the port: 1425 ops, 3323 lines, 0 differ; 193 mutations, 193
    caught. Play's only callers are collision_sound's (14-6). Azahar, on
    AC: a Hot Pursuit quick race, PASS at 30 fps.
  - **14-3, done:** the car sounds, CarSounds.obj (0x0018d0a8 ..
    0x0018f800): BaseCarSound, BasePlayerCarSound, BaseAICarSound,
    HornSound3d, SirenSound3d, UpdateCarSounds and the closest list
    (`carsound.c`, docs/formats/carsound.md). The five vtables are
    installed at boot. Car's constructor and destructor, the splash,
    the tyre pop and the drivers' horn are bound, and sound::Update
    runs UpdateCarSounds. The engines and the tyres are NULL hooks
    until 14-4 and 14-5. In a race X and Y swap, so the horn is on X
    (the user's ask). `tools/carsound_check.py` runs retail's
    CarSounds.obj in mipsemu, with the EE's divide, product and root,
    against the port: 592 ops, 3388 lines, 0 differ; 313 mutations,
    313 caught, run out of the tree by mutpar. mipsemu gained lwl, lwr,
    swl and swr, for ChooseHornSample's copy of "Horn01".
    Azahar, on AC: a Hot Pursuit quick race with two presses of X and
    then the gas, PASS at 29.9 fps (speed 99%), sound 0.5 ms a frame,
    a chase up with four cop cars.
  - **14-4, done (816ae93):** the engines, CarSoundEngine.obj
    (0x0020fad0 .. 0x00212470): PlayerEngineSound, AIEngineSound and
    engine_sound's two factories (`enginesound.c`,
    docs/formats/enginesound.md), bound at boot; bGetFile reads
    engine.ctb and engine.ltb. The 3DS has 22 voices to the PS2's 48
    and retail's player engine takes up to twenty, so the port plays
    it as retail does in mono (one voice a patch, six locked);
    ENGINESOUND_RETAIL_VOICES=1 brings back the pairs.
    `tools/enginesound_check.py` runs retail's code in mipsemu against
    both builds: 1024 ops, 6355 and 6234 lines, 0 differ; 384
    mutations, 384 caught (the voices' 15-step volume smoothing hides
    a one-call case, so the volume cases settle over ten calls).
    The link's .elf now stays in 3DS Files/build. Azahar, on AC: a Hot
    Pursuit quick race, gas only, PASS at 29.9 fps (speed 100%), sound
    0.8 ms a frame.
  - **14-5, done (4278190):** the tyres, CarSoundTires.obj
    (0x002124d8 .. 0x00214d68): BaseTireSound (the flop and the
    bottom-out), TerrainOneShot (the metal bump and the pothole, under a
    shared 0.3 s delay), PlayerTireSound (one a side: road or gravel
    noise, the skid, the squall, the burn-out peel, autumn leaves, a
    blown tyre's thump and scrape), OpponentTireSound (the skid on road
    or dirt) and tire_sound's factories and slot calls (`tiresound.c`,
    docs/formats/tiresound.md), bound at boot. Retail's functions do not
    agree on which two wheels a side means; the doc has the table.
    bSound's Flush does nothing on the 3DS. `tools/tiresound_check.py`:
    5042 ops, 13994 lines, 0 differ; 447 mutations, 445 caught, 2
    equivalent (the squall volume's scale and cap). Azahar: a gas-only
    SkipFE race, no abort, 29 fps, sound 0.3 ms a frame.
  - **14-6, done (39f7fd7):** the crashes and scrapes, CollisionSounds.obj
    (0x001e4658 .. 0x001e5e58): the crash libraries (metal small,
    medium and hard by the impulse, wood on a wood or cactus wall,
    foliage), the looping scrapes on wood, cactus and solid walls, the
    free list that lets a released sample finish, Update and Mute, and
    the one-shots: a smokeable knocked over, a car's glass, the busted
    roadblock, the explosion (`collisionsound.c`,
    docs/formats/collisionsound.md). CollisionSample's table is
    installed at boot; sound's four collision hooks and collision.c's,
    racecoord.c's, pursuit.c's and playernis.c's seams are bound.
    PlaySmokeable, PlayGlass and PlayExplosion have no ported caller
    yet. The port's Mute tests pCurrentWorld (retail does not).
    `tools/collisionsound_check.py`: 633 ops, 1630 lines, 0 differ; 153
    mutations, 153 caught. Azahar, on AC: a gas-only SkipFE race, no
    abort, 30 fps (speed 99%), sound 0.1-0.7 ms a frame.
  - **14-7, done (6084aa3):** the track's ambience and the chopper's
    rotor. SoundScape.obj (0x001cdde0 .. 0x001cff20): the 0x80038000
    chunk's reverb areas, looping ambients (over an area, or a sound
    sphere round a source inside it) and one-shot ambients, the reverb's
    smoothing and its road-over-the-car test, Update, Mute and
    SoundScapeIsInsideTunnel (`soundscape.c`,
    docs/formats/soundscape.md), on bchunkload's slot 21 and sound's
    scape hooks. The 3DS has no reverb unit, so the three effect calls
    are NULL seams. ChopperSound.obj (0x00214d68 .. 0x002150d8): the
    Sound3d over "ChopperEngine" with its tunnel fade
    (`choppersound.c`, docs/formats/choppersound.md), set as
    gCreateChopperSoundFn. `tools/soundscape_check.py`: 4854 ops, 21476
    lines, 0 differ, every distinct retail track's chunk included; 342
    mutations, 338 caught, 4 equivalent. loadertable_check covers slot
    21 (0 differ). Azahar, on AC: a gas-only SkipFE race, no abort, 30
    fps (speed 99%).
  - **14-8:** the speech's engine, in four parts (retail addresses;
    out/retail_syms.txt's first column is retail's, its fifth the
    demo's):
    - **14-8a, done:** SpeechNoise.obj (0x002155d8 .. 0x00215a5c, and
      getInstance 0x001b0188): the radio's two squelches and seven
      bursts of static, category 6, a 3% chance a frame of one burst
      while the radio is on (`speechnoise.c`,
      docs/formats/speechnoise.md), on sound's four noise hooks. Retail
      never sets the helicopter's sample. Nothing turns the radio on
      until 14-9, so it is quiet for now. `tools/speechnoise_check.py`:
      175 ops, 433 lines, 0 differ; 67 mutations, 67 caught. Azahar, on
      AC: a gas-only SkipFE race, no abort, 31 fps (speed 99%).
    - **14-8b, done:** the SPCH library (0x00290720 .. 0x00295afc, 130
      functions): the banks, the event queue, the event and sentence
      choice, the rules, its random and the sample unpacking (`spch.c`,
      `spchbank.c`, `spchevnt.c`, `spchpick.c`, `spchrule.c`,
      `spchi.h`; docs/formats/spch.md). The SPCHLOG/SPCHDBG debug log
      is dropped. Nothing calls it until 14-8d. `tools/spch_check.py`:
      3054 ops, 10070 lines, 0 differ, with retail's EVENTS.EVT and all
      1806 banks of ENGLISHBAN.PCK; 591 mutations, 588 caught, 3
      equivalent. Azahar, on AC: a gas-only SkipFE race, no abort, 29
      fps (speed 100%).
    - **14-8c, done (c8a4ce9):** the speech's stream. bSnd_VoicePlay's
      "_STREAM" path (0x0026129c), the "_CHAIN" queue (0x00261e80),
      PlayChain (0x00262848) and the stream poll (0x00263090) in
      `bsnd.c` (docs/formats/sound-driver.md, "Streams and the queue");
      bSample's part play, SetSampleRate and the chain sample with
      AddToChain (0x00206760) in `bsound.c` (docs/formats/bsound.md);
      and `bsndstream.c`, which reads ENGLISHDAT.PCK's parts off the
      card on a worker, decodes the SPU ADPCM and queues it on the
      voice's ndsp channel (docs/formats/bsndstream.md). The port
      guards retail's full-queue overrun and keeps one `streamVoice`
      for every StreamChannel's poll. Nothing calls the chain until
      14-8d. `tools/bsndstream_check.py`: 716 ops, 3627 lines, 0
      differ; the decoder 112 inputs, 0 differ; 56 mutations, 54
      caught, 2 equivalent. bsnd_check and bsound_check stay at 0
      differ. Azahar, on AC: a gas-only SkipFE race, no abort, 30 fps
      (speed 100%).
    - **14-8d, done (c8b0d26):** cSEDWedge (0x002056f0 ..
      0x00206760), bSegment (0x002761d0 .. 0x00276538) and Sound.obj's
      wedge creation (0x001ae754), LoadLocalizedSpeechFiles and
      UnLoadLocalizedSpeechFiles (0x001ae4d8, 0x001ae5e8) in
      `sedwedge.c` (docs/formats/sedwedge.md). The wedge loads
      EVENTS.EVT and the language's BAN into SPCH; each update plays
      channel 0's best pending event as bSegments of the DAT, handed to
      the chain. main.c binds sound's sed_create and sed_update, the
      gameflow's speech load and unload, and the finish's
      ClearEventQueue. The port returns 0 for a missing BAN (bGetFile
      would stop the game) and a full pool. spch.md's BAN entries are
      corrected. `tools/sedwedge_check.py`: 300 ops, 1329 lines, 0
      differ; 195 mutations, 193 caught, 2 equivalent. sound_check and
      spch_check stay at 0 differ. Azahar, on AC, with SOUND/SPEECH on
      the card: a gas-only SkipFE race at 30 fps, and a frontend Hot
      Pursuit quick race at 30 fps with "speech bank 0: loaded". No
      event is queued until 14-9, so nothing speaks yet.
  - **14-9, done (a7f8f4b):** speech::mgr_t (0x00209ef0 ..
    0x0020b868), its nfsFsm, conditions and actions (0x0020bf00 ..
    0x0020f7c0), speechContext_t (0x0020f7f8 .. 0x0020fac8) and
    ConvertSpeed (0x00223528) in `speechmgr.c`
    (docs/formats/speechmgr.md). The transition tables are generated
    from retail's constructor. main.c binds sound's speech_update,
    speech_mute, speech_flush and speech_sed_playing,
    gSpeechFlushQueueFn, gCopSpeechFlushQueueFn,
    gCopSpeechAllocateVoicesFn, gCopSpeechPlaybackStateFn and the car
    selector's speechFade and soundEnabled.
    `tools/speechmgr_check.py`: 4145 ops, 27220 lines, 0 differ; 885
    mutations, 876 caught, 9 equivalent. Azahar, on AC: a frontend
    Hot Pursuit quick race at 30 fps. Nothing raises an event until
    14-10, so nothing speaks yet.
  - **14-10a, done (a96f7b6):** tPursuit's 13 speech methods
    (0x0022aa20 .. 0x0022b908) in `pursuitspeech.c`, and
    Speech::ConvertCarType (0x002232f8) in `speechconv.c`
    (docs/formats/pursuit-speech.md). main.c binds them, and wraps the
    raises that pursuit.h, pursuitchopper.h and pullover.h make
    straight to speech::mgr_t. `tools/pursuitspeech_check.py`: 258792
    ops, 47809 lines, 0 differ; 281 mutations, all caught. Azahar, on
    AC: a frontend Hot Pursuit quick race, PASS, with two chases
    started. The cops speak with NFSHP2/SOUND/SPEECH on the SD card.
  - **14-10b, done (95ea945):** the filler speech: TryFillerSpeech,
    SayFillerSpeech and the nine filler classes (0x002315d0 ..
    0x00231d70) in `fillerspeech.c`, with IsCopNearChasedCar
    (docs/formats/pursuit-speech.md, "The filler speech"). main.c binds
    gSayFillerSpeechFn. `tools/fillerspeech_check.py`: 81169 ops, 23198
    lines, 0 differ; 122 mutations, all caught.
  - **14-10c, done (RE-5, Session 70):** the race's speech
    (0x00206900 .. 0x00207870; docs/formats/race-speech.md):
    RaceFinishedSpeech (0x00206ab8, gRaceFinishedSpeechFn),
    LapFinishedSpeech (0x00207198, gLapFinishedSpeechFn), 0x002075d8
    (gSpeechPulloverEventFn), 0x00207648 (gSpeechBeACopArrestFn),
    PlayBustedSpeech, and Speech's conversions 0x00223328,
    0x00223358 .. 0x002233b8 and 0x00223480 into speechconv.
  - **14-10d, done (3ac6572, Session 82):** bcarsel's speakCar
    (ConvertCarType; event 211 for a cop, 146 otherwise) bound in
    main.c; Select Track's ConvertTrackNumber was already bound. The
    selector now registers its eleven joystick events as retail's
    constructor does (0x00195210): one player on both pads, two players
    each on their own. In the frontend joyhid swaps B and Y
    (JOYHID_LAYOUT_FE), so Y is Square, the orbit view. Step 14 is
    done.

  After step 14:
  - **12m** Be A Cop. The user's controls (2026-10-08): in Be A Cop
    the D-Pad triggers the cop's options (the helicopter, backup and
    the like) and the Circle Pad drives. In a racer's race the D-Pad is
    just another directional control;
  - **12n** the radar detector's intensity. Done (TASKS 40,
    Session 83).

  Since 12j-1 the radar traps take cops out of limbo, so a chase can
  start.

The test config for a race with cops is parked as
`nfshp2_config.txt.cops` (SkipFE, track 12, 3 AI, traffic 0.5,
SkipFEMaxCops 3).

The AI pack's cost is closed. The user's asks, 2026-10-08, were "sluggish
until I get away from all the AI racers" and "still hitching when all
the AI cars are in the view at once".

- The hitches are gone: `trackview_prepare` bakes and uploads
  everything at the load (3b62e00).
- Track 45 with eight cars in view runs at 20 FPS (15 before), and 30
  with the pack gone. Two commits did it:
  - 569dfde: one shbin, and the lit batches' and strips' state sent
    only when it changes;
  - ba9ef1f: citro3d's draws written in one go, in c3dwrap.c. The log's
    `c3d: indexed draws written here` and `c3d: array draws written
    here` say its self-check passed.
- The user: "20 to 30 isn't a big difference and I'm willing to let it
  slide. May need more optimizations later for cops, helicopters etc."
- `docs/formats/draw-cuts.md`, 13b-6, lists the next cuts for then.

The order now:
  1. Step 12, the cops and cop mode.
  2. AnimatedDriver.
  3. The PostRace and Demo coordinators.
  4. Pause's other screens.
  5. Task 37.
  6. TRACKB45's speed.

The SD card's race config for testing is parked as
`nfshp2_config.txt.track45` (SkipFE, track 45, 7 AI, traffic 0.5).
Rename it to `nfshp2_config.txt` for a forced race.

## Now: step 11, the racer AI

Retail's racers are AICarController and AIDriver. They stand on a
DrivingInformation, a DrivingChoice, CarCollisionPredict, an AIPlan and
its actions. Each slice is checked against retail in mipsemu, as the
car's were.

- **11a, done:** what an AI car knows as it drives.
  - `nearbycar.c` has NearbyCarList (BuildArray, ClearArray and the
    three lookups), DrivingInformation's Clear, and five of the AI's
    free functions: CalculateMaxAcceleration, CanICatchThisCar,
    DoWeCareAboutThisCar, GetCurrentCurvatureOfDrivingLine and
    HighlightDrivingLine.
  - `drivinglocation.c` has DrivingLocation's methods, and
    `drivingchoice.h` the choice's record. `drivetarget.h`'s stand-in
    for the location is gone.
  - `nearbycar_check`: 36 scenarios, 10,309 lines, 0 differ; 99
    mutations, all caught. The ten other checkers that link
    `drivetarget.c` still have 0 differ.
  - `docs/formats/ai-driving-info.md` has the detail. The belt mover's
    gravity is a seam (`gBeltMoverGravityFn`) until BeltMover is
    ported.
- **11b-1, done:** DriveTarget is retail's. DrivingChoice builds its
  targets with retail's DriveTarget, so that came first.
  - `drivetarget.c` gains retail's byte at 516 (LastPointToScore,
    which Clear sets to -1), its accessor, CalculateMaxSpeed split in
    two, the first corner from the car, and EstimateScore's rebuilt
    walks. The from-car corner divides by zero for a car at rest, so
    its projection and `bNormalize2To`'s first divide are `ee_div`.
  - `drivetarget_check` and the image check, now run on retail's
    image: 22 scenarios, 993 lines, 0 differ. The model's pass: 288
    mutations, 268 caught, 20 equivalent.
  - The 54 checkers that link `drivetarget.c` or `bvector.c` still
    have 0 differ. The demo-image oracles that run Clear hook its tail
    for retail's -1 (`physicscar_check.retail_clear`), and
    `drivecam_check` divides the EE's way.
  - `docs/formats/car-drive-target.md`, "Retail's DriveTarget".
- **11b-2, done:** DrivingChoice's small methods and the walk along
  the route.
  - `drivingchoice.c` has GetChoiceType, GetDrivingLine, the three
    SetChoices, Clear, IsValid, IsEqualTo, IsEnoughRoom,
    FixupCarToExcludeFromCollisionPrediction and GetPreferredSideOfCar.
    It also has the walk: FuturePointList::Add, AdvancePoint,
    GetRoutePointsToUse and the road block's point list (0x00244c88).
    Then GetSpeedBackToLine, ReduceCurrentL, AddToDriveTarget and
    FillUpDriveTarget.
  - `racecore.c` has Race::GracePeriodIsActive (0x001492b0) and its two
    globals. `aicarcontroller.h` has as much of the controller's record
    as these read.
  - AICarController::SignPostDecision is a seam
    (`gAISignPostDecisionFn`), which main.c points at the port's since
    11e-2. Car::GetRoutePoint and
    GetAmountOutOfBounds go through the controller's vtable.
  - `drivingchoice_check` runs the image as the model: 45 scenarios,
    25,798 lines, 0 differ. Its mutation pass: 240 mutations, 239
    caught, 1 equivalent. `racecore_check`, `racerun_check`,
    `nearbycar_check` and `drivetarget_check` still have 0 differ.
  - Five divergences are written down in the source and in
    `docs/formats/ai-driving-choice.md`, which has the rest.
- **11b-3, done:** `drivingchoice.c` builds the target for a choice.
  BuildDriveTarget (0x00241ea0) fills up an invalid choice as asked, a
  line on that line, and sends a side to BuildDriveTargetAroundCar
  (0x00243aa8). That one puts a point beside the car with room to
  pass, eases out to it (DoSmoothOffsetChange, 0x00244ea0), follows the
  car's own target alongside it when it is a player or traffic
  (MakeDriveTargetParallelToCar, 0x00243f70), then fills up on the
  line. Retail's own clearance (0x002442c0) and closest point ahead
  (0x00244d80) are in too, with the three `.sdata` globals they read.
  - `drivingchoice_check` runs with the EE's divide now: 71 scenarios,
    79,543 lines, 0 differ. The slope's divide by zero (0x00245050) is
    ee_div, and no other site takes the EE's path. Its mutation pass:
    385 mutations, 383 caught, 2 equivalent.
  - Two more divergences are in the source and in
    `docs/formats/ai-driving-choice.md`: the entry read with no NULL
    test, and the new points' w (STACK-W).
- **11b-4a, done:** `carcollisionpredict.c` has CarCollisionPredict,
  which car an AI car's target runs it into, and when.
  - The four live methods are WhoWillThisDriveTargetHit (0x001e5e60),
    IsThisCarStoppedDirectlyInFrontOfMe, WillIHitThisCar and
    MakeOBBsForDriveTarget. The three free functions under them are
    WhenWillOverlapOccur2D, TimeIntervalForSeparatingAxis and
    IntervalOverlap. Its four dead functions are left out.
  - Each car's target becomes a chain of boxes. The two are walked
    together at their speeds, and each step asks when the current boxes
    first overlap on the ground.
  - The walk divides 0 by 0 on a leg of 0 (0x001e65ec, 0x001e65f4), so
    both divides are ee_div. WillIHitThisCar's 4720-byte frame (two
    targets and forty boxes) is static storage in the port.
  - Retail's own corners: a still axis with the boxes apart answers
    9999, so two crawling cars "hit" at 9999 s. A miss after a long
    step comes out past 99999.
  - `drivingchoice_check` links it, with `obb.c`: 98 scenarios, 97,604
    lines, 0 differ. Four new kinds of scenario: s_predict, s_parts,
    s_meet and s_stopped. Its 207 mutations are all caught, so the
    checker's 592 have 590 caught and the old 2 equivalent.
  - `docs/formats/ai-collision-predict.md` has the detail.
- **11b-4b, done:** DrivingChoice is whole. `drivingchoice.c` has
  IsDriveable (0x00241ff8), TryChoice (0x002428d0), MakeNewChoice
  (0x00242170) and TryToDriveAroundCar (0x00242c20).
  - IsDriveable builds the target and asks WhoWillThisDriveTargetHit.
    A choice is driveable when it built, scored above -1 and hits later
    than the longest time.
  - TryChoice tries one choice. MakeNewChoice tries the current choice,
    the lines, then each side of each car worth caring about, and goes
    round the car in the way when nothing fits.
  - EstimateScore's distances are static now (retail's 80-byte carry),
    in `drivetarget.c`.
  - `drivingchoice_check`: 231 scenarios, 105,136 ops, 151,404 lines,
    0 differ. Four new kinds of scenario: s_choose (a hundred), s_jam,
    s_pass and s_tie. s_tie is one built case, an exact 0.1f tie found
    by bisecting a car's speed.
  - Its mutation pass: 741 mutations, 730 caught, 11 equivalent, 0
    unexplained. 11b-4b's share is 149, with 140 caught and 9
    equivalent.
  - `docs/formats/ai-driving-choice.md` has the detail.
- **11c, done:** AIPlan and the AIAction base, in `aiaction.c`.
  - AIPlan has its constructor, destructor, SetTimeout, TimeToChange
    and the status tests.
  - AIAction has:
    - its constructor and destructor, and new and delete on
      "AIActionSlotPool";
    - UpdateStatus and the three SetDesiredSpeeds;
    - GetHeadingClassification and GetCollisionClassification;
    - ClearPointsToDrive and GetName.
  - InitAIPlans and CloseAIPlans make the pool as a track loads and
    delete it as it unloads (`gInitAIPlansFn`, `gCloseAIPlansFn`).
    CalculateMaxDeceleration is in `nearbycar.c`.
  - The record is retail's 608 bytes, with DesiredSpeedTolerance at
    572. `aicarcontroller.h`'s placeholder for it is gone.
  - SetDesiredSpeedSlowerThanThisCar divides by zero for a car keeping
    pace (0x001c6520), so that divide is ee_div.
  - `nearbycar_check`: 58 scenarios, 16,061 lines, 0 differ. Its
    mutation pass has 220 mutations, all caught; 11c's share is 121. The
    first pass left nine alive, all gaps in the script. s_ai_edges
    closes them with exact cases: edges at exactly 0, a time to the edge
    of exactly 1.0f, and a route whose direction is not unit length.
  - `docs/formats/ai-action.md` has the detail.
- **11d: the actions.** Eleven subclasses, retail 0x001c6ba0 to
  0x001caa00; `out/retail_syms.txt` has every function. They split
  three ways by size:
  - **11d-1, done:** the five small ones, in `aiactions.c`:
    JustDrive, Draft, NudgeCar, Block and AccidentRecovery (with
    SortOfParallelToTrack). Each has its constructor, CalculateScore,
    the three tests, CalculatePointsToDrive, GetName and destructor, and
    `main.c` installs the five tables.
    - JustDrive tries line 0 with IsDriveable at most every three
      seconds (AIDriverAvoidCarsImpactTimeThreshold, 2.0f, is defined
      in `aiactions.c`). Draft slows behind a car under 6 m ahead, and
      only ever lowers its speed. NudgeCar and Block only set
      PointsToDriveWillExecuteAction and are always accomplished.
      AccidentRecovery stops on the route and resets the car once,
      five seconds after it was made.
    - NudgeCar's and Block's HasExpired use `c.le.s` the other way
      round, so a NaN timeout goes on to the other tests.
    - Retail leaves f14 (IsDriveable) and f13 (BuildDriveTarget) stale;
      neither is read, and the port passes 0.
    - `drivingchoice_check` runs them, over retail's AIAction base:
      - 352 scenarios, 142016 ops, 178348 lines, 0 differ;
      - 136 mutations for 11d-1: 133 caught (1 by a crash) and 3
        equivalent (jd-every, jd-pref, jd-a). Across the checker, 877
        mutations: 863 caught, 14 equivalent and 0 unexplained.
      - s_act_edges closes the first pass's four gaps: the slot's fill,
        the -1 timeout, the exact 4000 ticks and normals between 0.5
        and 0.707.
    - `docs/formats/ai-action.md` has the detail, under "The small
      actions (11d-1)".
  - **11d-2, done:** Pass (with SideOfCarIsOkay) and AvoidCars (with
    GetCarToAvoid), in `aiactions.c`, and `main.c` installs their
    tables too (seven in all).
    - Pass goes round a car ahead it can catch: TryToDriveAroundCar over
      AIActionPassMaxTimeAheadToMakeAttempt (3.0f, defined in
      `aiactions.c`). It is done 3 s on with the car 10 m behind, and
      fails when the car leaves the list or can't be caught in its
      first 3 s.
    - AvoidCars steers off a hit my own target is heading for:
      MakeNewChoice, made again every 0.3 s, and when nothing is
      driveable it slows behind the car to avoid.
    - CalculateMaxAcceleration's answer reaches only CanICatchThisCar,
      which doesn't read it; the model stubs it. GetDriverNumber is a
      test CarDriver table in the checker, on both sides.
    - `drivingchoice_check`: 532 scenarios, 194029 ops, 218234 lines,
      0 differ.
    - 170 mutations for 11d-2: 160 caught, 10 equivalent. Across the
      checker, 1047 mutations: 1023 caught, 24 equivalent and 0
      unexplained.
    - The first pass left 45 alive. Ten are equivalent. The other 35
      were gaps in the script, which s_pa_edge closes with exact
      cases: x at 2y, the car exactly 10 m past the half lengths, y at
      0, and the close test's edges behind a car stopped just ahead. It
      also covers no location with an empty target, and AvoidCars'
      time far from Pass's.
    - `docs/formats/ai-action.md` has the detail, under "Pass and
      AvoidCars (11d-2)".
  - **11d-3a, done:** PullOver and IJustGotHit, in `aiactions.c`, and
    `main.c` installs their tables too (nine in all).
    - PullOver (600) is for traffic only. It scores when the chopper is
      within 150 m in plan 0, 1, 2 or a bombing run, or when an AI cop
      (not disabled) or a player has cop lights on within its speed
      times 3.5 s, and no less than 100 m. It is done when that stops.
    - Its points head for the right edge, or stay on the line for a
      careful driver (skill -2). Every 0.3 s it goes round a car hit
      sooner than 2 s with MakeNewChoice. It creeps at 14 m/s while
      there is room to the edge, losing the room under 2 m and getting
      it back over 4 m, and brakes otherwise. It stops in a two-car
      collision or under 0.5 m/s. Past its own timeout (-999 is none)
      it stops on the line.
    - IJustGotHit (400) takes my car's two-car collisions with a car on
      the list, one ahead over one behind, else the smaller y, and is
      done when there are none. Every 0.2 s it makes a new choice. It
      backs off from a player's car ahead and gets away from one
      behind. It also gets away from any car not ahead. As traffic hit
      head on it holds its speed, hands off. Otherwise it slows behind,
      and never under 20 off the line's speed.
    - The checker stubs GetCollision, IsTwoCarCollision and
      GetCollidingCars on both sides. CalculateMaxAcceleration and
      CalculateMaxDeceleration now run as shipped, because IJustGotHit
      reads the answer. The model clears PullOver's stack choice
      (PO_CHOICE, sp+0 of 720) on the way in, as drivingchoice.c's is
      cleared.
    - `drivingchoice_check`: 672 scenarios, 239714 ops, 264995 lines,
      0 differ.
    - 220 mutations for 11d-3a: 216 caught (11 by a crash) and 4
      equivalent. Across the checker, 1267 mutations: 1239 caught, 28
      equivalent and 0 unexplained.
    - The first pass left 14 alive, and s_ph_gap closes ten. Its cases
      are the hit exactly 2 s on, the room either side of 2 and 4 in
      both float orders, and car 2 blocking the way round car 1. It also
      covers the list's entry with no car, a player's car at the back
      overlap edge, and the head-on time to speed. Four are equivalent.
      Five of the earlier slices' patterns carry a line of context now.
    - `docs/formats/ai-action.md` has the detail, under "PullOver and
      IJustGotHit (11d-3a)".
  - **11d-3b, done:** GetUnstuck and AvoidRoadBlock, the last two
    actions, in `aiactions.c`. All eleven tables are installed.
    - GetUnstuck (500) needs the grace period over, a location and 3
      wheels down. It scores when my car is 20 m past an edge, or heads
      out of the route forwards as an AI car at 25 m/s or less (traffic
      at 20). It also scores when the car is stuck behind a slow one in
      its way (within 9 m), or hit something in front at least 0.4 s ago
      and is all but stopped.
    - It backs out, at -15 m/s as AI and -6 otherwise, towards the point
      three on from the location's, on its line. It is done facing that
      point (a dot of 0.98) with no one in the way. It fails heading out
      backwards, or backed into something. A minimum lifetime (-1 is
      none) holds both tests off. Every way out asks the controller's
      FindWhereIAm and the driver's ClearSteeringMemory.
    - AvoidRoadBlock (600) takes the first active roadblock with a cop
      ahead within my speed times 2.5 s, and no less than 100 m. It is
      done 15 m past it, or when the cops are gone.
    - Its points move smoothly to the escape lane's offset at the
      roadblock's route point. Off that route it uses the closest point
      ahead of the escape lane on mine, when the lane is under 5 m past
      the edge there; otherwise it keeps my offset to my route's end. A
      racer in the way within 1 s, ahead, is followed 0.1 slower, at no
      less than 30 m/s.
    - copmanager.h's tRoadBlock has the cops, the route and its point,
      the spike belt, the escape lane and the distance round the track.
      The checker stubs FindWhereIAm, ClearSteeringMemory and
      GetSteerToPoint on both sides. The roadblocks, the pursuits and
      the collisions' times are ops.
    - `drivingchoice_check`: 778 scenarios, 274688 ops, 297126 lines,
      0 differ.
    - 186 mutations for 11d-3b: 180 caught (10 by a crash) and 6
      equivalent. Across the checker, 1453 mutations: 1419 caught, 34
      equivalent and 0 unexplained.
    - The first pass left 32 alive. s_gu_edge, two rounds of thirteen
      kinds, closes 26. Eleven kinds are on a straight road: the exact
      edges of 20 m off, 25 and 20 m/s, 0.4 s, 15 m/s, the 0.98 facing,
      the lifetime, the range, 15 m behind, 5 m off the road, and a racer
      ahead. Two are on curved roads: where the search for the escape's
      point starts, and the route's last point. Six are equivalent.
      Three of the earlier patterns carry a line of context now.
    - `docs/formats/ai-action.md` has the detail, under "GetUnstuck and
      AvoidRoadBlock (11d-3b)".
  - The demo's mangled names gave the other constructors' arguments;
    retail's, read from each constructor, are in
    `docs/formats/ai-action.md`. Every one starts (int score, float
    timeout).
  - Each subclass's fields sit sixteen bytes later than the demo's
    (retail's 608-byte base). Their tables are in retail's `.data` near
    `_vt$8AIAction` (0x002b7c90). The DoSnapshots wait on ReplaySnapshot.
  - `drivingchoice_check` has the actions' ops (`@n`, `@cp`, `@us`,
    `@t`, `@sc` and the rest) and stubs (the pool, GetElevation,
    PleaseResetMeLater). `nearbycar_check` keeps the base's.
- **11e, next: AICarController**, which scores the actions, keeps the
  best and drives by it.
  - **11e-0 is done: Average at retail's size.** Retail's Average is 16
    bytes with its three counters as bytes (the demo's 24, with words),
    and PidError 40 (the demo's 56). The controller keeps two (580 and
    692), so `average.c` came first. `average_check` runs retail's image
    now: 552 ops, 972 lines, 0 differ; 73 mutations, 72 caught and one
    equivalent. GetLastValue (0x0018fdf8) is new in retail and unused.
    `docs/formats/average.md` has it.
  - **11e-1 is done: the record, the route methods and the action.**
    `aicarcontroller.{c,h}` have the 720-byte record, the constructor
    and destructor, the 17-entry table (Think and DoSnapshot NULL), the
    route methods, GetNewDrivingLine, JustReset, InterruptAction,
    GeneratePointsToFulfillAction, SetToPhysicsMode, the line speed (the
    seam's, from main.c), the boosts and the accessors. Retail's
    CarController::SetToPhysicsMode (0x001c0100) sends a player's car to
    physics where the demo's sent every car to mellow; that is
    `carcontroller_physics_or_mellow`, which Car::SetToPhysicsMode uses
    too. `car_get_route` and `car_get_route_point` take retail's find
    flag. The checker is its own, `aicarcontroller_check`, over
    drivingchoice_check's world (split into
    `tools/src/drivingchoice_world.inc`), with the port's installed
    table copied into its test table: 156 scenarios, 24485 ops, 15468
    lines, 0 differ; 126 mutations, 121 caught, 5 equivalent. Of note:
    GetNewDrivingLine's relaxed switch can't be seen (BuildDriveTarget
    builds a valid line from a copy with no switch, and throws an
    invalid one away), every car IsDriveable meets needs its collision
    box, and a location with a route and no point is never made.
    `docs/formats/ai-car-controller.md` has it.
  - **11e-2 is done: the signposts and sticky decisions.**
    FindSignpostIndex, GetStickyIndex, DoStickyDecisions,
    SignPostDecision and GetCurrentTrackRoutePoint. main.c points
    drivingchoice.h's `gAISignPostDecisionFn` at the port's
    SignPostDecision. A decision is a sticky word (bit 0 in use, 1
    taken, 2-7 the line, 8-15 the sign), dropped 10 m past its sign;
    signs are decided AIDriverSecondsToLookAhead x speed x 1.1 ahead,
    100 to 250 m. Every sign but AlwaysTake waits out the sign grace
    period (the track's SignpostGracePeriod in seconds, or
    Race::GracePeriodIsActive at -1); Equivalent is a coin flip,
    DontTake never, the rest a draw against the skill's TakeSignChance
    (the switch at 0x002b4cb0). AIHint 2 sets TakenSignpostIndex, and
    AIHint 1, in GetCurrentTrackRoutePoint, TakenSignpostTimer (10000
    ticks). With every slot used, retail's slot -1 stores over
    nSignpostIndex, and the port does the same. The checker stands in
    World::Random and GetTrackInfo: 378 scenarios, 67592 ops, 40802
    lines, 0 differ; 226 mutations, 217 caught, 9 equivalent (11e-2's
    100: 96 caught, 4 equivalent). mipsemu has no NaN, so a NaN speed
    isn't scripted, and DoStickyDecisions with no sign past the
    look-ahead loops for ever, so the script always has one.
    track.h, topology.md, trackroute.h and track-route.md had the grace
    gate and AIHint wrong, and are fixed.
  - **11e-3 is done: the belt, the glue and the boost.** WeHaveTheBelt,
    WeNeedTheBelt (bBeltMover), WeCanHaveTheBelt (eleven tests: 3 points,
    not AIDemoMode, both belt timers off, 5 m/s forward on a wheel, an
    action that isn't PullOver, GetUnstuck, AccidentRecovery,
    AvoidRoadBlock or IJustGotHit, not careful, no player within 120 m,
    30 s raced), the glue's seven (WeHave/WeNeed/WeCanHaveTheGlue,
    GlueOn, GlueOff, GetGlueSpeed over the gp-20336 Graph), and
    DecideBoostFactor with CalculateDistanceAndPositionBoost (the
    distance and position boosts from TheDifficultyInfo, the two-player
    catchup target, the speed ratio's table). `player.h` gains
    `player_get_speed_ratio` and `player_catchup_allowed`, the second
    comparing its argument (the SlowFactor) with fMaxSpeedRatio. The glue
    has no caller in retail, so it never runs in the game.
    drivingchoice_check's Model keeps its allowed divides in `OK_DIVS`,
    which aicarcontroller_check extends with WeCanHaveTheGlue's two
    `vrsqrt`. 568 scenarios, 95996 ops, 75041 lines, 0 differ; 407
    mutations, 394 caught, 13 equivalent (11e-3's 181: 177 caught, 4
    equivalent, two of them the 30 s clock no whole tick count reaches
    exactly).
  - **11e-4 is done: the horn and ExecuteCurrentAction.**
    MaybeHonkAndOrBlinkHeadlights (0x00192fa8) honks only at a player's
    car (or any in AIDemoMode) that isn't a cop's or traffic's, and only
    from an AI car that cares about it (DoWeCareAboutThisCar) or a
    traffic car. It draws on, off and second durations and the two-honk
    flag, then a chance by the closing speed (over 50 m/s, or a traffic
    driver closing under -3, is 1), a player (0.75) or the list's count
    (0.075 under 6, else 0.05), and the blink only with the honk.
    Retail's car takes the second on phase's duration as a third float
    (Car+2088, the port's 2176): car.c's HonkAndOrBlinkHeadlights and
    UpdateHeadlightsAndHorn are retail's now (0x00134130, 0x00134198),
    with the cycle `(On + Off) + SecondOn` and the gap ending On after
    the first phase. ExecuteCurrentAction (0x001932e8) sets the driver's
    target to the action's points, runs DecideBoostFactor and sets the
    desired speed: 0 with the location clear, 15 within 10 for
    SuperEasyAI (gp-20120), the point's line speed for
    BoringAIForCameraTuningOn, the action's own four, or the line speed
    (the taken sign's new point's, 99999 on the sign timer, or the point
    CurrentRoutePointLookahead on, redrawn every RoutePointChangeFrequency
    s within RoutePointVariance + 1 by World::Random(int), times the
    unclamped skill's SpeedFactor), times 0.75 in a cop race and the
    BoostFactor; then ClearPointsToDrive. 738 scenarios, 125785 ops,
    110422 lines, 0 differ; 522 mutations, 509 caught, 13 equivalent
    (11e-4's 115 all caught, with car.c's honk and lights among them).
  - Retail's runs from 0x00190140 to about 0x00194058: some 16 KB in
    about 50 functions (`grep AICarController out/retail_syms.txt`).
    Think alone is 2536 bytes, DecideBoostFactor 904 and
    ExecuteCurrentAction 868. The slices, each checked in
    `aicarcontroller_check` (over drivingchoice_check's world):
    - 11e-1 (done): the 720-byte record, constructor, destructor, the table
      (Think and the snapshot NULL until theirs), the route methods
      (SetCurrentRoute, GetCurrentRoute and GetCurrentRoutePoint with
      retail's find flag, GetAmountOutOfBounds, FindWhereIAm,
      FindClosestTrackRoute, GetNewDrivingLine), JustReset,
      ClearStickyDecisions, SteerStraightAhead, InterruptAction,
      GeneratePointsToFulfillAction, SetToPhysicsMode,
      GetCurrentDrivingLineSpeed (for car.h's seam), the boosts and the
      small accessors. Retail's Car::GetRoute and GetRoutePoint pass a
      flag through in a1 (1 from every caller but IsFacingWrongWay's 0),
      so `car_get_route` and `car_get_route_point` take it too.
    - 11e-2 (done): FindSignpostIndex, GetStickyIndex,
      DoStickyDecisions, SignPostDecision (main.c's
      `gAISignPostDecisionFn`) and GetCurrentTrackRoutePoint. The jump
      table at 0x002b4cb0 is SignPostDecision's.
    - 11e-3 (done): the belt, the glue and the boost: WeHave/WeNeed/
      WeCanHave the belt and the glue, GlueOn, GlueOff, GetGlueSpeed,
      DecideBoostFactor, CalculateDistanceAndPositionBoost. Of these
      only the belt's WeNeed and WeCanHave (Think's) and DecideBoostFactor
      (ExecuteCurrentAction's) have callers in retail.
    - 11e-4 (done): MaybeHonkAndOrBlinkHeadlights and
      ExecuteCurrentAction, with car.c's honk and lights moved to
      retail's. The start-up code at 0x00193f00 that builds the glue
      Graph also stores 0xc000 at gp-13390; find out whose that is when
      a slice reads it.
    - 11e-5 (done): Think (0x00191148), with Timer::CountDown
      (0x001a3cf0) in timer.c and Race::CanAICarsStartDriving
      (0x00149078) in race.c. Before the start it stands, or from the
      pre-race runs the brake stand; then the progress check (a car
      under 0.2 m/s round the track for 15 s, out of a player's 50 m, is
      reset), the timers, the debug reset, the turn (an AI racer by
      `WorldLoopCounter % 8`, traffic by `% 6`, anyone else on its
      clock), between thinks, and the think: the sticky decisions,
      BuildArray, the track route point, the action (a new JustDrive by
      bOMalloc for none), the points, ExecuteCurrentAction and the belt.
      BeltMover::SetBelt is carmodes.h's `gBeltMoverSetBeltFn` (main.c
      sets it since 11e-6; a harness that leaves it NULL aborts). Retail's
      BuildArray reads RenderingEnabled as a byte at Car+1192 and
      IsPoofed the word at 2160 (the demo's 1160 and 2120). 865
      scenarios, 173272 ops, 170252 lines, 0 differ; 654 mutations, 639
      caught, 15 equivalent (11e-5's 132: 130 caught, 2 equivalent).
    - 11e-6 (done): the BeltMover (BeltMover.obj, 0x00204098 to
      0x002056b4), in `beltmover.{c,h}`, all but DoSnapshot. The car
      rides a QuickSpline through its DriveTarget's points, its place a
      quadratic in the belt's clock, its heading and slide eased by two
      tCubic2Ds and its offset by a tCubic1D. banim.c gains GetddVal
      (0x001da830) and the tCubic2D's inline methods (`bspline2d_*`);
      cPoint::SplineSeek's two clamps never run, as every seek the mover
      makes passes 0 for both. main.c sets `gBeltMoverCtorFn`,
      `gBeltMoverSetBeltFn` and `gBeltMoverGravityFn`, and
      BELTMOVER_SIZE is `sizeof(BeltMover)`. `tools/beltmover_check.py`:
      6049 ops, 34239 lines, 0 differ; 277 mutations, 271 caught, 6 equivalent.
      `docs/formats/belt-mover.md` has it all.
  - `aicarcontroller.h` has the whole 720-byte record. 684 and 688 are
    retail's own (TakenSignpostIndex and TakenSignpostTimer, named for
    what 11e-2's SignPostDecision and GetCurrentTrackRoutePoint and
    11e-4's ExecuteCurrentAction do with them).
  - `gAICarControllerGetCurrentDrivingLineSpeedFn` in `car.h` is the
    line speed's seam, set in main.c. drivingchoice_check still stubs
    FindWhereIAm (0x00192f10) for the actions.
- 11f-1 (done): PsychoDriver (PsychoDriver.obj, 0x00139700 to 0x0013a6ac
  and 0x0013ab68 to 0x0013ad84), in `psychodriver.{c,h}`, all but
  DoSnapshot, with AIDrivingInfo.obj's two SteerStraight functions. The
  624-byte record keeps CarDriver's 560 and adds the car, the steer-to
  point, the speed with its time and tolerance, the e-brake timer, the
  direction latch and three PidErrors (body, heading, velocity). Drive
  steers on a PID of the heading's or the body's error (the body's when
  the two disagree), turns the wheel at the speed table's rate, and
  picks the gear and pedals by a latch on the speed's sign. Indices 3
  and 4 (traffic, delivery, and mellow under traffic control) take
  their weights from arrays, the rest from seven Tables the start-up
  code builds (sinit.c's [16]). The demo's line predictor is gone from
  retail. 0x0013a630 (a `sw zero,0(a2)`) and SetEBrakeTimer have no
  caller, so the e-brake never comes on. main.c installs the table; the
  horn's seams stay NULL until BaseCarSound. `tools/psychodriver_check.py`:
  55673 ops, 49373 lines, 0 differ; 247 mutations, 238 caught, 9
  equivalent. `docs/formats/psycho-driver.md` has it all.
- 11f-2 (done): AIDriver (AIDriver.obj, 0x0012ffc8 to 0x001308a0), in
  `aidriver.{c,h}`, all but DoSnapshot. The 736-byte record is
  AICarController's 720, the car it has decided not to avoid with the
  time it chose, the progress timer and a five-slot Average of the
  progress. The constructor builds the PsychoDriver; Think records
  TrackLength x |lap rate| every 1.5 s and jumps to AICarController's;
  ShouldWeAvoidThisCar spares a car the skill's dice spare for a
  second; ChooseNewAction news a forced action, or else runs the
  cascade (GetUnstuck after six seconds, AvoidRoadBlock, IJustGotHit,
  AvoidCars, AccidentRecovery, Pass, JustDrive), each but JustDrive
  skipped for the current action's type or a higher score. Retail's
  AvoidCars quirk is kept: `okay` goes in as the float seconds. The
  scores and lifetimes are retail `.sdata` nothing writes. main.c
  installs the table and sets `gAIDriverCtorFn`; AIDRIVER_SIZE is
  `sizeof(AIDriver)` (carmode_check maps it to the demo's 720).
  `tools/aidriver_check.py`: 56131 ops, 25276 lines, 0 differ; 191
  mutations, 184 caught, 7 equivalent. `docs/formats/ai-driver.md` has
  it all.
- **11g-1, done: a SkipFE race with AI racers that drive.**
  - **The config file.** `sdmc:/nfshp2_config.txt`, the port's own, in
    place of the joylog's channel 32, which only a development kit
    records. Each line is a configitems.h name and a value
    (`SkipFENumAICars 3`), `#` starts a comment, and `SkipFE 1` turns
    SkipFE on as R held does. main.c's `readConfigItems` reads it at
    boot, before InitFred. With no file nothing changes, so the build
    the user plays is as before. It is a test aid only: the user wants
    the AI race from the frontend (11g-2).
  - **The fix.** With `SkipFE 1` and `SkipFENumAICars 3` the race came
    up with three AI racers on the grid, and nothing aborted, but they
    never moved. Each was on JustDrive in the MellowMover with a
    desired speed of 0. ExecuteCurrentAction's speed is the line's
    speed byte times the skill's `SpeedFactor` times the boost, and
    `SpeedFactor` read 0.000. GLOBALB's last chunk, 0x34b00
    (DifficultyInfo, 992 bytes), was never loaded: main.c's
    `loadGlobalCarInfo` offers GLOBALB's chunks to the loaders the port
    needs, and `loader_difficulty_info` was not among them. It is now
    ("car data: 9 chunks"). The three racers leave the grid at full
    throttle for 56 m/s and race the route, about 680 m out at 40 s, on
    JustDrive, AvoidCars and Pass. The same empty table had made every
    frontend opponent's skill 0 (StartRace draws it from
    SkillLevelDistribution) and the boost recalculate every frame.
    `docs/formats/difficulty-info.md` has it.
  - main.c's race log has a line per AI racer each second: its place,
    speed, movement mode, action and its PsychoDriver's inputs, then
    its route point, line, speed byte, skill, `SpeedFactor`, boost and
    next think.
  - GLOBALB's NisInfo chunk (0x37010) is still dropped; its loader
    (slot 20) is unported.
  - The player's car drove itself in two Azahar runs: the analog gas
    (the Cross pressure byte) read 255. That byte is set only while the
    3DS A is held, and a third run, with no key sent, stood still. It
    was keyboard input reaching Azahar, not the port.
- **11g-2a, done: Quick Race from Hot Pursuit's Mode Select.** The
  user (2026-10-07), on an Azahar run that wandered into Be The Cop's
  Select Car and the placeholder Select Track: "This still needs to be
  setup within the hot pursuit cop mode setup lol". Quick Race is the
  first item of both Mode Selects, and the shortest way in.
  - `quickrace.c` is retail's StartQuickRace (0x00216c18), with
    PickTrackNumberForExpressGame, the track locks and
    FrontendPlayerInfo::GetCarStatus: the defaults, the express game,
    the pick's track, 3 AI racers and 4 cops for Hot Pursuit (7 and 0
    for World Racing), the player at the back of the grid, traffic at
    0.33, 2 laps, a car from GenerateRandomRideInfo, then StartRace.
    `bscreens.c`'s startQuickRace hands it the screen's transmission
    flag, and New Main Menu's two items set the police flag
    (`MainMenuOpts[1]`) as retail's do. `docs/formats/quick-race.md`.
  - BeginGameFlowUnloadingFrontEnd now asks for LOADING_TRACK_COMMON,
    so the flow leaves the frontend. `world_add_traffic_car` places no
    traffic car while PlaceNewCar is a NULL seam (it aborted), as a
    NULL AddCopCarToRace places no cop.
  - `fredrace_check` runs retail's as shipped (`s_quickrace`,
    `s_tracklocks`) and now mutates through mutpar: 3958 ops, 71235
    lines, 0 differ; 296 mutations, 291 caught (2 by a hung harness),
    5 equivalent.
  - `tools/run_azahar_quickrace.ps1` plays it on Azahar: the title, Hot
    Pursuit (`-CopsOff` for World Racing), A on Quick Race. Azahar runs
    the frontend at about 57%, and a single press was lost twice, so
    each press is repeated until the log shows the game took it. The
    run: track 31 backwards, 3 AI racers, 4 cops, car 37, 14 drivers
    (the 6 traffic cars and the 4 cops are not placed), RACING with 4
    cars at 30 FPS.
  - **What it showed: the race never leaves the countdown.** It sits
    at stage 3 (COUNTDOWN) for good, the AI racers wait in
    CanAICarsStartDriving (action -1), and the view hangs at 0, 0,
    1100 over the track. Two seams are NULL:
    - Race::Update (0x00148a78, called by World::DoTimestep at
      0x0014e20c; the port's `gRaceUpdateFn`) sets RACING once
      GetCountdownNumberToDisplay is 4. It also runs the lap counts,
      the best lap, the finish and the leadership, which the SkipFE
      race (it starts at RACING) has never had either. That is 11g-2b.
    - While the race counts down, `choose_camera` asks for the
      countdown cameras, whose coordinator
      (`gCountdownCameraCoordinatorFn`) is NULL, so the player has no
      camera mover until RACING. That is 11g-2c.
- **11h-1, done: TrafficCar, the traffic's mover.** `trafficcar.c` is
  retail's TrafficCar.obj (0x00167a08 to 0x00168098) but DoSnapshot: a
  bicycle on the ground plane, the speed from the pedals through two
  Tables, held between 0 and 55 mph, and the CarState written
  outright. Its start-up code is sinit's [28]
  (`_GLOBAL_$I$TrafficAccelerationTable`). `trafficcar_check`: 7947
  ops, 10693 lines, 0 differ; 148 mutations, 145 caught (6 by a
  crash), 3 equivalent. `docs/formats/traffic-car.md`.
- **11h-2, done: TrafficDriver, the traffic's controller.**
  `trafficdriver.c` is retail's TrafficDriver.obj (0x0018c380 to
  0x0018d070) but DoSnapshot, the table at 0x002b4730: an
  AICarController with a PsychoDriver and a Think of its own. A traffic
  car thinks on the odd frames of twelve whose half is its place among
  the traffic. It keeps the best of six actions: GetUnstuck (2 s after
  the last), AccidentRecovery, IJustGotHit, AvoidCars (with AIDriver's
  quirk), PullOver and JustDrive. Each is tried while the best so far is
  below its global. AvoidCars and PullOver take the car off its belt.
  Its speed stays under 24.59 m/s, under 0.328 m/s a metre to the next
  hairpin sign (whose route it takes within 10 m), and under 10 m/s
  through a bend. `trafficdriver_check`: 72743 ops, 31387 lines, 0
  differ; 230 mutations, 226 caught (11 by a crash), 4 equivalent.
  carmode_check maps its 736 to the demo's 720 (size-trafficdriver
  caught). `docs/formats/traffic-driver.md`. The TrafficTeleporter
  (11h-3) places them.
- **11g-2b, done: Race::Update.** `raceupdate.c` is retail's
  Race::Update (0x00148a78), both FinishCars, the finders,
  MonitorLeadership, the ghost car's capture, replay and save, and the
  race time projection new in retail (0x001473f8). `playerfinish.c` is
  Player::SetFinishedRacing (0x00176650), and aicarcontroller.h has the
  pull-over at 0x001908d8. World::DoTimestep calls it through
  `gRaceUpdateFn`, and SimulateRaceFinish finishes through
  `gRaceFinishCarFn`.
  - At COUNTDOWN with GetCountdownNumberToDisplay at 4 (GO), the stage
    becomes RACING. The race time then runs, the laps count, and the
    best lap, the forced finish, the knockout, the time trial, the laps
    led, the finish and the leadership's replay events follow.
  - A finished player's car goes to AI_CONTROL (an AIDriver), and every
    AI car that finishes pulls over within 15 s.
  - The speech, the finish line sound and the ghosts' samples are NULL
    seams that do nothing. Retail never makes a ghost.
  - `raceupdate_check`: 997307 ops, 73230 lines, 0 differ; 161
    mutations, all caught (7 by a crash). `docs/formats/race-update.md`.
  - On Azahar the quick race now leaves the countdown, and the race runs
    at 29-30 FPS with lap 1 of 2 on the HUD.
- **11g-2c-1, done: the camera data and the countdown coordinator.**
  `cameracoord.c` is CameraCoordinator.obj in part (0x00199a98 on):
  - TheCameraLoader (retail's 2596 bytes) and slot 13 of the loader
    table, the six camera chunk types;
  - FindCameraData, FindRandomCameraShake and the NIS keeper;
  - CameraDataItems' parser;
  - BaseCameraCoordinator, CameraCoordinatorList (its static
    constructor is sinit's [40]) and UpdateCameraCoordinators, which
    main.c's race frame runs after UpdatePlayersNonGameState;
  - CountdownCameraCoordinator.
  No bundle on the retail disc has a COUNTDOWN_n camera, so the
  countdown's coordinator builds no mover and UpdateNonGameState gives
  the car its drive camera. `gBumperCameraMoverFn` stays NULL until
  BumperCameraMover is ported.
  - `cameracoord_check`: 2973 ops, 5925 lines, 0 differ; 167
    mutations, all caught. `loadertable_check` holds slot 13 as
    ported (its two slot-13 mutations caught).
    `docs/formats/camera-coordinator.md`.
  - On Azahar the 3-2-1 is in the drive camera with the cinema bars
    and the AI racers ahead, as in the user's photo 4.
- **11g-2c-2a, done: the fly-by camera.**
  - `trackflycam.c` is TrackFlyCameraMover (0x00159d08 on, 412 bytes):
    the eye, bank, look and FOV splines, IsFinished, Update.
  - `cameracoord.c` adds FlyByCameraCoordinator (0x0019abd8 on, 40
    bytes). It flies the loader's fly-bys in turn, each to its end. Its
    IsFinished is true only with no fly-bys, so CAMERA_FLYBY ends only
    on RC_SKIP from the Starting Grid's X.
  - main.c sets `gTrackFlyCameraMoverFn` and
    `gTrackFlyCameraMoverIsFinishedFn`. The race coordinator's
    `gFlyByCameraCoordinatorCtorFn` and `gFlyByCameraIsFinishedFn` stay
    NULL until 11g-2c-2b: without the grid the state would never end.
  - `trackflycam_check`: 25 scenarios, 14170 ops, 39418 lines, 0
    differ; 84 mutations, all caught. `cameracoord_check`: 3970 ops,
    9251 lines, 0 differ; 209 mutations, 206 caught, 3 equivalent.
    `docs/formats/camera-coordinator.md`, "The fly-by".
- **11g-2c-2b, done: the Starting Grid over the fly-by.**
  - `startrace.c` is retail's PRERACE_STATS module (0x001e27b8 to
    0x001e3b40):
    - tStartRaceScreenManager: Enable picks this race's screens, then
      Disable and ReadyToSkip;
    - PreRaceStats, the grid: a line for each racer by starting
      position, the knockout's and the tournament's lines, the track's
      name and "Race n of m";
    - its HandleEvent: SELECT posts RC_SKIP unless START made it;
    - the letterbox's callback.
    The Blurb and the two-player You're The Cop screen are not ported.
  - **A bmenu fix:** FlailerMenuItem's JoyHandler puts the JoyEvent in
    the item message's Param (retail 0x00169d98). The port never had,
    and the grid tells START from A by it. `bmenu_check` passes on
    FRONTB (demo and retail) and on INGAMEB.
  - main.c registers "Pre Race Stats" and "Pre Race Letterbox". It sets
    the fly-by coordinator's two race seams, the screens' two, the
    flow's ChangeToScreen and the two translates. RaceEvent's seams stay
    NULL.
  - **The check:** `startrace_check`: 4817 ops, 18822 lines, 0 differ;
    197 mutations, 193 caught (11 by a crash or hang), 4 equivalent.
    `docs/formats/start-race-screens.md`.
  - **On Azahar:** the grid draws over the fly-by with the cinema bars
    (Desert Heat II, the player's row in orange). CAMERA_FLYBY holds for
    20 s, until the script's A, then the countdown and the race follow.
    The flow's per-frame TICK no longer goes to the card's log; it was
    1538 of its 2448 lines.
  - **Open:** grey specks show over the grid's backdrop along far road
    lines. Their cause is not known; look for them on the device.
- **11g-2d, done: the pause menu** (the user's ask, 2026-10-07).
  - `pausemenu.c` is retail's PAUSE_MAIN module (0x00170560 to
    0x001710f4): PauseMenu (56 bytes) with EnterPause, ExitPause,
    Activate, DeActivate, MaybeRestart, MaybeQuit, MaybeResume and
    MenuCallback; PauseMenuCallback; ChooseWhoSelectedMenuItem; and
    tHighlightAnimation's new HandleMessage (0x00248ae0), the bloom.
  - `jukebox.c` adds sound::Mute (0x001af850), `jb_sound_mute`, for
    RCSTATE_PAUSE's mute.
  - main.c registers "Pause Menu" (0x605d2bf1) and fills the pause
    seams. `flowInput` now runs after `raceFrame` in a race, as
    retail's GenerateJoyEvents does, so the START that pauses does not
    also unpause. `flowChangeToScreen` keeps the screen up when asked
    for one not ported (Pause Options, Race Objective, the BAC
    controls). `flowBeginUnloadingTrackCommon` hides every INGAMEB and
    FRONTB screen, so the Quit popup (KEEP_VISIBLE, drawn from FRONTB's
    POPUP) no longer stays over the frontend (the user's screenshot).
  - **The check:** `pausemenu_check`: 14633 ops, 28698 lines, 0
    differ; 198 mutations, all caught. `jukebox_check`: 1263 ops, 7061
    lines, 0 differ; 292 mutations, 287 caught, 5 equivalent.
    `docs/formats/pause-menu.md`.
  - **On Azahar:** the menu draws and mutes the music; Resume unmutes;
    Restart works with Cancel and OK; Quit unloads to the frontend
    (from SkipFE to the language screen, as retail's
    frontendLaunchType 1 does; from a quick race to the New Main Menu).
    The linear heap is back to 68926 KB free once the track detaches
    (69397 at boot).
  - **The music after a quit is retail's.** "Fever for the Flava" opens
    the menu once a boot (jukebox.c's `jb_first_pick`, 0x001aea40);
    later visits carry on down the menu list. The user found that odd
    (2026-10-07); a port option like `randomRaceOpener` could reopen
    the menu with it every time if they want.
  - **Left of the pause:** Pause Options with its audio and display
    pages (0x00171180 to 0x00173e30), Race Objective and the BAC
    controls (0x00171a28 to 0x00172068). Until then those items do
    nothing.
- **11g-2c-2c-1, done: the pre-race coordinator.**
  - `cameracoord.c` adds PreRaceCameraCoordinator (0x0019ad78 on, 188
    bytes). Its constructor picks the cars: racing car 0, then the
    player three times (Be A Cop and two players pick otherwise). Its
    Update flies INGAMEB's four pre-race cameras in turn, each on the
    next car, building a BumperCameraMover through
    `gBumperCameraMoverFn`. It finishes after four, unless the config
    item `TunePreRaceSequence` (gp-23108, now in configitems.c) is set.
  - main.c sets the race coordinator's
    `gPreRaceCameraCoordinatorCtorFn` and `gPreRaceCameraIsFinishedFn`.
    `gBumperCameraMoverFn`, `gBumperCameraMoverIsFinishedFn` and
    `gAnimatedDriverBeginAPreRaceAnimationFn` stay NULL: with no mover
    the coordinator moves on every frame and ends after four frames, so
    nothing shows yet (the user, 2026-10-07: "I didn't see the camera").
  - **The check:** `cameracoord_check`: 6400 ops, 13655 lines, 0
    differ; 293 mutations, 289 caught, 4 equivalent.
    `docs/formats/camera-coordinator.md`, "The pre-race".
  - **On Azahar:** the quick race goes from the grid's A through
    PRERACE (rc 3, stage 3) to the countdown and lap 1, at 30 FPS.
- **11g-2c-2c-2, done: BumperCameraMover.**
  - New `bumpercam.c` (0x00158800 on, 1116 bytes, table 0x002b1bd0,
    type 5): the constructor, destructor, IsFinished, GetTarget and
    Update, with the wall routine (0x00157c60) for a race that is
    racing. The eye and look are in the car's frame, the eye shaken by
    the road noise and held 0.7 over the ground.
  - main.c points `gBumperCameraMoverFn` and
    `gBumperCameraMoverIsFinishedFn` at it. The AnimatedDriver's seam
    stays NULL: the driver does not move yet.
  - **The check:** `tools/bumpercam_check.py` with
    `tools/src/bumpercam_test.c`: 16 scenarios, 15038 ops, 37485 lines,
    0 differ; 145 mutations, 143 caught, 2 equivalent.
    `docs/formats/camera-coordinator.md`, "`BumperCameraMover`".
  - **On Azahar:** the quick race goes grid, A, the close-ups round the
    yellow player car (each about 1.5 s), the 3-2-1 and lap 1. The
    close-ups run at 30 FPS.
- **11g-2e, done: the rear-view mirror** (the user's photo 5).
  - New `rvmcam.c`: RearViewMirrorCameraMover (0x00158f78 on, vtable
    0x002b1b50) and Player::SetRearViewMirrorCameraMover (0x001767a8).
    main.c points `gPlayerSetRearViewMirrorCameraMoverFn` at it, so the
    HUD's HUD_REAR_VIEW_MIRROR puts the mover on view 3, and the view
    mode turns target 7 on. `camera_mover_get_target` is public now.
  - `trackview_draw_mirror` draws view 3 into a 256 by 64 texture
    (`georender_mirror_*`) after the envmap: the sky, the scenery and
    the cars (not the player's), then DisplayRVMImages' frame and mask
    (0x0010ec70). `display_rvms` puts it on the top screen at retail's
    GS (160, 20) to (352, 84), mirrored and blended by the mask's alpha
    (DisplayRVMs, 0x0010edc8). `setup_view` sets target 7 as retail's
    SetScreenBuffers does (run in mipsemu: 1.5 and 1.08 aspect, black
    background).
  - The projection takes in a quarter more across than retail's,
    because the top screen is 5:3 where the PS2's is 4:3.
  - The frame profiler has a `mirror` stage and a third `models:` half.
  - **The check:** `tools/rvmcam_check.py` with
    `tools/src/rvmcam_test.c`: 7 scenarios, 2088 ops, 9863 lines, 0
    differ; 52 mutations, 51 caught, 1 equivalent.
    `docs/formats/camera.md`, "The rear-view mirror".
  - **On Azahar:** the SkipFE race shows the mirror top centre in its
    frame, upright and mirrored, without the player's car. It draws 81
    to 128 models (the view 225 to 313) in 3.7 to 5.2 ms of CPU, and
    the race holds 29 to 30 FPS. The device's cost is not measured; if
    it is too much, draw the mirror every other frame.
  - **Left:** the sun, the NIS objects and the effects in the mirror's
    view, which retail draws there too.
  - **Broken late in a long race (2026-10-08):** the frame and the mask
    were gone and the main view showed through. RVM and RVM_MASK had
    failed to upload, with the linear heap down to 6 MB, and a texture
    that fails is not tried again. The texture memory work fixes it.
- **11h-3, done: the TrafficTeleporter** (commit cd443d0).
  - `traffictele.c` is retail's TrafficTeleporter.obj (0x002226f8 to
    0x002232c0) but DoSnapshot. `airouteplan.c` is
    GuessTargetDestinations (0x001cbb70), the route walk it asks.
    `carrenderinfo.c` gains Car::SwitchSkin (0x0011e588),
    UpdateSkinTextures and UpdateTextureInfo for the repaint.
  - **The check:** `traffictele_check`: 7563 ops, 0 differ; 180
    mutations, 178 caught, 2 equivalent. `carrenderinfo_check`: 327
    scenarios, 108561 lines, 0 differ; 175 mutations, 173 caught.
    `docs/formats/traffic-teleporter.md`; ai-route.md has
    GuessTargetDestinations.
  - **On Azahar:** Quick Race on track 24 places its six traffic cars,
    all drawn, and with the gas held the player passes four of them at 10
    to 42 m. Quick Race's density is 0.33, under the 0.4 below which
    DoTimestep moves nothing, so its traffic stays where it was put
    and drives its routes. No car starts within 2000 of the start line.
- **B in a race, fixed** (commit f539fdf). B is the brake and the
  port's BACK. With no screen up in a race, retail has no screen-list
  handler at all (ChangeToScreen, 0x0016c4c0), but `flowInput` passed B
  on, and it popped the stack to New Main Menu under the race. The
  user's "S" in Azahar. pause-menu.md has it.
- **Task 37, Local Wireless (multi-card) play,** is in TASKS.md (the
  user's ask, 2026-10-07). It comes after the single-player race is
  whole.
- **Next, in this order:**
  1. **The texture memory work** (the user's ask, 2026-10-08: every
     texture loads on every map, done globally and not per track).
     HANDOFF's Session 52 has the research. Every texture is RGBA8 now,
     padded to powers of two with a full chain, and on a big map the
     linear heap runs out: whatever loads last fails and is never tried
     again (the mirror's frame, OPEL_SKIN1 on track 12, TRACKB45's
     skins). In order:
     a. lossless format per texture at upload: RGB8 for the opaque, L8
        and LA8 for the gray, and so on. Exact, so nothing changes on
        screen; 13-21% off the tracks, 25% off the cars;
     b. a texture cache with a budget: the least recently drawn are
        evicted and uploaded again from the pixels kept in the main
        heap when drawn, so a missing texture is never final;
     c. the VRAM left over after the frame buffers;
     d. on the device (the CIA's 178 MB, memory type 7, which the user
        confirmed): LINEAR_WANT up from 80 MB to about 112, the malloc
        heap down from 96 to about 66. The race uses about 45 MB of
        it. Azahar's .3dsx (124 MB) is unchanged by it;
     e. later, the car skins' power-of-two padding (38%).
     Pre-decoding offline is out: memory is the limit, not the CPU, and
     the card holds retail's files only. ETC1 is out: it is lossy.
  2. Step 12, the cops.
  3. The AnimatedDriver that PRERACEANIM.LZC feeds (trackflow.c's Part3
     loads it), so the driver moves in the close-ups.
  4. The PostRace and Demo coordinators.
  5. The pause's other screens (Pause Options and its pages, Race
     Objective, the BAC controls), with the frontend's.

## Waiting on the device: 13b-4f, the device GPU's cost per model

The device's GPU takes 43-47 ms a frame with 200-380 models in view,
and the lap drops to 16-18 FPS there. Session 36's timing frames split
the models' list (895 draws): the texture fetch about 6.5 ms, the fill
about 10.2 with the fetch in it, the vertex work about 7.5, the draws'
own cost about 1.44, the texture cache clears about 0.35.
`docs/formats/draw-cuts.md`, "13b-4f", has the detail.

- **The Old 3DS (6ac29d1).** The user's Old 3DS ran the .3dsx out of
  heap at the race's track (a 31.8 MB heap and a 31.8 MB linear heap
  under the Homebrew Launcher). They chose the New 3DS alone, for good:
  an Old 3DS now stops at boot with a message. No Old 3DS mode, ever.
- **Done (609b418): indexed meshes.** `georender_bake` keeps each
  distinct vertex once a solid and the batches draw with
  `C3D_DrawElements`. TRACKB12's 401,385 list vertices are 176,505, and
  the post-vertex cache should shade about 1.7 a triangle where the
  list shaded 3. On Azahar the picture is the list's (the same depth to
  the bit) at 29.2 FPS; only the device can show the gain. The capture
  no longer numbers the envmap's draws (`capture_offscreen`).
- **Probes (2fc77fc).** The timing frame sends the
  models' and the first envmap view's lists again three ways more: with
  the early depth test on, compared either way, each with its pixels
  counted against "as drawn", and with every RGBA8 texture fetched as
  RGB8. The early depth buffer's rules are documented nowhere public and
  Azahar ignores the test, so the device decides both whether the
  picture holds and what it saves. On Azahar both early pictures match
  to the pixel and RGB8's differs in all of them, as it must.
- **The envmap is a third of a light frame's GPU.** Session 36's lines
  have three views at 3.6-4.0 ms each, of 27.7. Its "1-pixel scissor"
  is 3.39 of 3.57: its 64 by 64 faces are vertex work and draws, not
  fill. The indexed meshes are its cut; the early depth test is not.
- **Next, each kept only if the device's log shows it helps** (memory:
  gpu-speed-plan):
  1. The fill and the fetch: the PICA's early depth test, with the
     opaque models drawn nearer first; then lossless RGB8 for textures
     of one alpha, which fetch three bytes a texel where RGBA8 fetches
     four.
  2. The envmap's cube faces back to RGBA5551 (the face pair was not
     the hang; the user's "lossless only" is about the disc's textures).
  3. Each draw's own cost: fewer state changes between batches.
  4. On the CPU: the envmap (6.2 ms on Azahar), the cull (2.7).
- **The user's playtest, 2026-10-09: heavy scenes lag** (TASKS.md
  task 28). On the device, on the desert track near the end, where the
  yellow neon signs point left and the dust/fog effect is, the race
  slows down. It is playable but more than expected, and a little worse
  with the helicopter. No logs. Soon: profile it there with the timing
  build and cut what the profile shows, keeping retail's look.
- Then the road beyond 13b: the retail pass, the AI, the cops, the
  sounds (memory: cars-racing-over-menus).

## The car selector (SC-1 to SC-3), done

The user asked for the car selector after seeing the stand-in Select
Car screen ("Could use work LOL"). Retail's shows the car in 3D on a lit
turntable. SC-1 is retail's SelectCarScreen and CarSelector
(`SLES_507.31`) as logic and 2D, in `bcarsel.c`. SC-2 is the 3D car,
and SC-3 the nebula behind it. `docs/formats/car-select.md` has all of
it.

**SC-1 is done.** At its end, `carsel_check` agreed with retail over
the whole script: 7282 ops, 430239 lines. Its mutation pass caught 196
of 201, and the other 5 are equivalent. SC-2c has grown both since. The checker found that
`BCARSEL_MAX_FADE` was 48 when FRONTB's fade groups hold up to 103
objects. It is 128 now, and that is built. The plain run takes about
eight minutes, most of it the model's 170 ms ticks, so run it in the
background.

**Mutation passes are quicker (tools/mutpar.py).** carsel, selcam and
fecar use it. The model's transcript is cached by a hash of the checker
above its mutations and of every source and header, so a pass after an
EQUIVALENT-only edit skips the model. The mutants build from a snapshot
of the sources taken once the model is done, sixteen at a time, so the
tree may be edited, and built, while they run. carsel's pass is about
12 minutes (it was 24), fecar's 25 s, selcam's 43 s. Convert other
checkers to it as they are touched; selcam_check is the pattern.

**SC-2, in four parts:**
- **SC-2a, the camera, is done.** `selcam.c` is SelectCarCameraMover
  (CM_SELECT_CAR) with its sounds. `selcam_check` runs 4266 ops with 0
  differ, and its mutation pass catches 141 of 143 (2 equivalent).
- **SC-2b, the car and its light, is done.** `fecar.c` is
  FrontEndRenderingCar and RenderFrontEndCars. `elight.c` gains
  SetSelectCarLighting and elSetupLightContext's frontend branch.
  `fecar_check` runs 1439 ops with 0 differ, over an empty light
  database and over a pack of six lights. Its mutation pass catches 124
  of 125 (1 equivalent). Nothing on the device calls them yet:
  gElInFrontendFn and gElCarSelectActiveFn stay NULL until SC-2d.
- **SC-2c, the selector's 3D, is done.** `bcarsel.c` keeps the car,
  its reflection, the CARCOVER and PLATFORM models and the camera in
  place. The Tick sets the camera, the cars' matrices and the light,
  and RENDER draws the platform. The spotlights are dead code in retail
  and not ported. `carsel_check` runs 7373 ops, 459051 lines, 0
  differ, and its mutation pass catches 264 of 273 (9 equivalent). On
  the device the CarRenderInfos
  are built, but nothing draws yet: render_model returns outside the
  race's draw. `docs/formats/car-select.md`, "The selector's 3D
  (SC-2c)", has retail's facts.
- **SC-2d, the draw on the device, is done.** The car select shows
  the user's PCSX2 photo 7: the Crown Victoria lit on its turntable,
  with its reflection in the floor, under the make, the badge and the
  icons. It runs at 60 FPS, about 4 ms a frame, on Azahar.
  - `frontres.c` puts FRONTB, which the UI holds, through LoadChunks and
    PostLoadFixup when the flow loads the frontend. The solid list gets
    a fresh copy each time. A new flow hook, `unloadFrontEnd`, after
    closeSelectCar, unloads it in reverse.
  - `trackview_attach_frontend` and `trackview_draw_frontend` give the
    frontend a second TrackView with no track, drawn in eDisplayFrame's
    order. main.c's `drawCarSelTop` draws Flailer layers 24 to 20
    (`UIR_BACK_PASSES`), the 3D, then the rest. The unlock blurb is
    queued during the 3D and drawn after the layers.
  - Its solids and textures are forgotten, after the next
    C3D_FrameBegin, when a resource file or a car's textures unload.
    They are freed with FRONTB.
  - render_model honours RenderStrips' flags 8 and 16, in the race too.
    The env map is CARSELECTENVMAP, through
    `georender_set_env_texture`.
  - main.c sets gElInFrontendFn and gElCarSelectActiveFn, and runs
    update_camera_movers() in frontend frames.
  - **A fix the race needed too.** `georender_set_fog(NULL)` bound NULL
    to texture unit 1. citro3d reads the type of what it is given there,
    so that read address 12 every frame. It was an unmapped read on
    Azahar and would be a data abort on the device. Unit 1 now gets a
    texture of its own. The race and car select runs both have 0
    unmapped accesses, and `run_azahar_carsel.ps1` fails on any.
  - `bootflow_check` (48 scenarios, 27964 lines) and `bscreens_check`
    (17, 1277) still agree. Nothing else checked compiles the files
    SC-2d touched. `docs/formats/car-select.md`, "The draw on the
    device (SC-2d)", has it all.

**Gaps, on purpose:**
- The event trees are not ported, so findEventForCar is NULL in main.c
  and the device shows no tree blurbs.
- The nebula is done (SC-3d).
- Select Track is `btracksel.c` since 12m-3c-1 (Session 77).
- Joy event 34 does nothing in retail either.

**SC-3, the nebula, is done.** It is the frontend's effects,
which eDisplayFrame draws between RENDER and AttachSolidPolys, behind
the car. The effect system is retail's AcidFXE.obj (0x00126d70 ..
0x001276fc and 0x0012a1e0 .. 0x0012a5e8). `docs/formats/acidfx.md` has
SC-3a's retail facts, and HANDOFF.md, "SC-3a", the harness's ops. There
are four parts:
- **SC-3a, the data half, is done.** `acidsys.{c,h}` has the four
  structs at retail's offsets, the three slot pools (afxInit, afxClose),
  slot 6 (LoaderAcidFX, UnloaderAcidFX), afxUpdateTextures, the lookups
  and copies (afxGetEmitterData, afxGetEmitter, afxCopyEmitter,
  afxGetEmitters, afxDeleteEmitters, both SetEmitterData), and
  AcidEffectSystem's constructor, AddAutoEmitter, RemoveAutoEmitter,
  KillAllActiveEffects and the deleting destructors.
  - `afx_check` runs 9295 ops over 16 scenarios with 0 differ, and its
    mutation pass (mutpar) catches 172 of 175, with 3 equivalent.
    `loadertable_check` (slot 6 now ported) and `sinit_check` (24
    calls) still agree.
  - The device runs it: acid_static_init in sinit_run, afx_init after
    the display's init, GLOBALB's two packs in loadGlobalCarInfo, the
    tracks' through slot 6, and the four seams set
    (gAfxUpdateTexturesFn, gAfxGetEmittersFn, gAcidEmitterDeleteFn,
    gKillAllActiveEffectsFn). Each car now takes copies of GLOBALB's
    CARFX emitters. The carsel and race runs on Azahar have 0 unmapped
    accesses.
- **SC-3b is done.** TriggerEmitter (0x00127700), DoTimeStep
  (0x00128718), UpdateInterestPoints (0x001286a0) and hermite_basis.
  - `afx_check` runs 14885 ops over 24 scenarios with 0 differ, and
    its mutation pass catches 310 of 313, with the same 3 equivalent.
    `eview_check` still agrees.
  - World's step runs WorldEffects' DoTimeStep on the device. The race
    and carsel runs on Azahar have 0 unmapped accesses.
- **The hang on a New 3DS XL** (2026-10-04, the user's): with R
  held, the race's first frame drew (1.7 s, most of it the textures'
  first upload) and then nothing; HOME was dead and the console had
  to be powered off. It was the first race on real hardware.
  - The log says only that frame 1 got to C3D_FrameEnd. The next
    frame line is a second later, so the stop is anywhere after.
    Nothing found by reading: every draw has a count, the buffers
    are linear, the targets are in VRAM, and no frame comes near
    citro3d's 32 GX entries (9 at most on Azahar).
  - The watchdog build's log (2026-10-05) put the stop in envmap view
    0's command list, the boot's first georender draws, with the GPU
    wedged: its registers stopped answering GSP too. Azahar flags
    nothing.
  - The draw check's log (2026-10-05, kept as
    `nfshp2_debug_draw_check.txt`) stopped at draw 1, the sky into
    envmap face 0: a 16-bit RGBA5551 colour buffer over a 32-bit D24S8
    depth buffer. Every address was in range and the clear before it
    was done. Nothing else the device had drawn on mixed the two
    sizes.
  - The cube faces are RGBA8 now (commit 1644100), the top screen's
    pair. The device still stopped at the same draw, now
    `c .../4` (`nfshp2_debug_rgba8_face.txt`), so the pair was not it.
    The faces stay RGBA8 for now; georender.c and light.md say so and
    name the real cause.
  - It was the first georender draw the device ever ran: with R held
    the frontend's 3D never draws. On Azahar the same draw (draw 16
    after the probes) has the same addresses, and the sky's 3168
    vertices are all finite, 1446 of them at w <= 0.
  - **The check's own stop (found 2026-10-05).** The stride-fix build
    stopped at the same first probe draw (`nfshp2_debug_stride_fix.txt`),
    with `28=28`. hangwatch's `gpu_wait` flushed the linear heap and
    then called C3D_FrameSplit, which writes the list's FINALIZE: those
    words stayed in the CPU's cache (the New 3DS's 2 MB L2), and the GPU
    read stale memory where the list should end. Every check build since
    the first watchdog one sent its lists that way, and each stopped at
    its first split list with a draw in it: envmap view 0, then draw 1,
    then the probe's first triangle. So none of those stops says where
    the race hangs. `gpu_wait` now splits, then flushes, then runs the
    queue, as C3D_FrameEnd does. On Azahar all 1798 draws go one at a
    time and the race keeps 30 FPS. That build is with the user.
  - The original hang, with no check in the build, fits the stride:
    frame 1 got to C3D_FrameEnd and the GPU never finished its list.
  - **The vertex stride (fixed 2026-10-05).** The probe
    build's log (`nfshp2_debug_probe.txt`) stopped at its first draw:
    one triangle through geosolid onto the top screen, with no texture
    and no depth test. 3dbrew's GPU/Pitfalls page says the PICA freezes
    when a loader's attributes do not fill the stride CONFIG2 gives it.
    GeoRenderVertex's loader was float3, float2, ubyte4 and byte3, 27
    bytes, against a stride of 28. Azahar draws either way.
    - The fix: the normal is loaded as four bytes, the pad its w,
      which neither shader reads (`georender_init`). The fold's vertex
      (20) and citro2d's (32) already filled theirs.
    - The draw check now works out each loader's size by the PICA's
      alignment and flags a stride that is not it, and logs both
      (`4/28=28`). On Azahar all 1798 draws of the checked frame match,
      with 0 issues, and the race keeps 30 FPS.
    - No shader has a MOVA, and unit 1 only ever has A8 textures, not
      4-bit ones. (This bullet said each output component was written
      once too. It was wrong: see the next bullet.)
  - **The output components (fixed 2026-10-05, Session 34).** The
    flush-fix build (`nfshp2_debug_flush_fix.txt`) still stopped at the
    probe's first triangle: geosolid onto the top screen, no texture
    units, no depth test, stride `28=28`, the queue's entry not done in
    2 s. With everything else stripped away, the shader is what is
    left.
    - 3dbrew's GPU/Pitfalls: each configured output component must be
      written exactly once or the PICA freezes.
      GPUREG_SH_OUTMAP_MASK enables an output register whole, one bit
      per register, so all four components count, even ones no
      semantic reads.
    - picasso gave geosolid's `texcoord0` and `texcoord1` the mask
      xyzw. The shader wrote `.x` and `.y` of each, so o1.zw and o3.zw
      were never written. geolit never wrote o1.w or o3.zw, and geofold
      never wrote o1.w.
    - citro2d's shader, which the device runs every frame, and all three
      of NFSU2-3DS's (`../NFSU2-3DS/3DS Files/source/*.v.pica`), which
      drew its world on hardware, write all four components of every
      output. The user pointed at NFSU2-3DS. Its world path is
      otherwise ours: citro3d, RGBA8 over D24S8 targets, loaders that
      fill their stride (3 floats, 3 floats, 2 floats; 32).
    - The fix writes the missing components as zeros (`mov outtex.zw,
      zeros` and the like), once on every path.
    - `tools/check_shbin.py`, run by `build_cia.ps1` after
      check_3dsx, follows each shader both ways through every IFU and
      IFC and fails the build on a component of an output written
      twice or never, and on two MOVAs in a row. It passes the fixed
      three, citro2d's and NFSU2's, and fails the old three on exactly
      the components above.
    - On Azahar: the checked frame's draws all pass, 0 unmapped
      accesses, 29.5 FPS, and the race looks as it did.
    - The stride fix stays: it was a real fault too. Which of the two
      stopped the original build cannot be told now; both were in it.
  - **It was the output components.** The build in
    `3DS Files/Hang Test Build/` (02:30), with that fix, loaded the race
    on the device and drove it. Its log is kept there with the older
    ones. The probe and the per-draw check are gone (commit 0355be5).
- **The race on the device (2026-10-05): 8 FPS, the GPU's.** The
  device's GPU takes 113-120 ms a frame: the models' list 78 ms, each
  envmap view 5-7 ms. The CPU's part is about what Azahar shows (23 ms).
  The user wants retail's look kept whole and the hardware used to the
  full. Their answers (memory: gpu-speed-plan):
  - Lossless textures only: RGBA8 where alpha varies, and, later, RGB8
    with the combiner's alpha for a texture of one alpha. No ETC1, no
    16-bit.
  - Mip chains: the disc's, and made ones for the single-level
    textures. **Done** (commit 0355be5): `texpack_upload_chain`, about
    38 MB for the track where level 0 alone was 28.9. A chain that will
    not fit uploads as its one level and is counted `unchained` in the
    race's texture line.
  - A timing build first. **Done, and with the user:** every 10 s of a
    race (first at 5 s), one frame times each draw stage on the GPU and
    sends the models' and the first envmap view's lists again, a
    different way each time, onto a VRAM target never shown. The race
    hitches each time (65 ms on Azahar, up to a second or so on the
    device) and looks as it does otherwise.
    Azahar's GPU times (0.12 ms) mean nothing; only the device's count.
  - Then indexed meshes and the early depth test, each kept only if the
    device's log shows it helps.
  - **Reading the timing lines.** `gpu time: frame N:` has each stage's
    ms and the sum. `gpu time: the models sent again (draws, vertices,
    texture addresses, cache clears, words)` has five times:
    - texture fetch is about "as drawn" less "8x8 textures";
    - fill (pixels: depth, blend, the combiners) is about "as drawn"
      less "1-pixel scissor";
    - vertex work is about "1-pixel scissor" less "3 vertices a draw";
    - what is left at "3 vertices a draw" is each draw's own cost:
      the commands, the state, the texture changes;
    - the texture cache clears cost about "as drawn" less "no texture
      cache clears";
    - since 13b-4f's probes, "early depth >=" and "early depth <=" are
      the list with the PICA's early depth test on, and the line after
      counts the pixels of each that differ from "as drawn" (0 and 0 is
      a picture the test leaves alone; RGB8's count, which must not be
      0, shows the compare works). "RGB8 for RGBA8" is the fetch the
      lossless RGB8 textures would have.
  - **What to do with them.** Fetch or cache clears large: sort the
    models' batches by texture, and send a cache clear only when the
    texture changes (it is about one a draw now). Fill large: the early
    depth test, and opaque draws nearer first. Vertex work large:
    indexed meshes (the strips' shared vertices go once, and the PICA's
    vertex cache works). Per-draw large: fewer, bigger draws. Then the
    lossless RGB8 textures, and the envmap's cube faces back to
    RGBA5551, as they were before the hang hunt made them RGBA8 (the
    face pair was not the hang).
- **The second run (Session 36, build 0355be5): 27-28 FPS.** The
  timing frames say 27.5-27.9 ms of GPU a frame: each envmap view
  3.6-4.0, the fold 0.3, the sky 1.4, the models 5.7, the sun and
  scenery 1.5, the cars and alpha lists 5.6, the bottom screen 1.1, the
  frame's end 0.7. The CPU's draw is about 10 ms. The worst frame each
  second was 70-150 ms: the log's own writes (fixed in 8bf178a, below).
  That run has no AI, cops or other cars; more will be needed for them.
  - **Hitches (fixed, 8bf178a).** `logwriter.c` puts each log line in
    a 128 KB ring that a thread one priority below the main loop writes
    out, on core 2 of a New 3DS. stderr stays synchronous. The timing
    frame (a hitch of about 150 ms) now runs only when
    `sdmc:/nfshp2_gputiming.txt` is on the card as the race starts.
  - **The ramp's abort (8bf178a), then the jump cam (Session 37).**
    8bf178a's stand-in, `no_jump_cam`, is gone. `playerzone.c`,
    `previewroute.c`, `spline.c` and `trackcarcam.c` are the jump cam,
    checked by `prevroute_check`, `trackcarcam_check` and
    `playerzone_check` (0 differ; every mutation caught but one
    equivalent). `docs/formats/camera.md` has three sections on it: "The
    jump cam's route", "The jump cam's mover" and "The camera zones".
    Still seams, NULL in `main.c`:
    - the freeze and preview zones' movers (zones 1 and 2 are a dead
      button);
    - the zones' sounds (the sample seams in `playerzone.h`);
    - `RadialBlurOn` and `RadialBlurOff`.
  - **The warp, for Azahar runs.** `sdmc:/nfshp2_warp.txt` holds
    `seconds x y z angle speed` (`warp.h`). It puts the car anywhere,
    once a race. `4 -1346.1 413.4 -68.5 610 55` with the gas held
    (`run_azahar_race.ps1 -HoldKeys 65`) meets the jump at x = -1200 on
    track 12. Azahar's copy is parked as `nfshp2_warp.txt.off`.
  - **The device's capture (Session 37): no box, and the wedge is the
    car's window.**
    - In the capture's frame the rock wall was dark and sharp, as on
      Azahar. The level-0 frame was a mean of 4.31 from it.
    - The linear heap was 20000000 to 25000000, inside the PICA's
      window.
    - The wedge is draws 722 and 723: the Opel's WINDOW batch, 21
      vertices, lit (blend 1) and then its env pass (blend 2). All its
      corners are inside the car on the disc, but on the device one
      ends up above the roof. Azahar draws it right.
    - Open: the batch's vertices as the car's strips build them, and
      what the device's PICA does with them that Azahar's does not
      (`pica-freezes-azahar-misses` in memory lists the known
      differences).
    - The PNGs are in `out/cap_device` (`wedge_zoom.png`).
    - The box may only show on a still car after a while. Ask the user
      for a capture later in a still race if it comes back.

    Session 36's notes, before the capture: in the user's photos the
    car stands still and the rock wall behind it is pale and blurred,
    with a dark sharp box in it and a light-blue wedge up from the roof.
    Moving, it goes. Azahar draws none of it. On Azahar the box's place
    is W_MOUNTVERS1 (the wall, the models' batch) under
    SHADOWSPINEMIDFADE2 (blend ALPHA) and the wedge's is
    SHADOWSPINEMIDR, a road shadow decal (blend ALPHA). Ruled out: the
    mips' colours and alphas, the sun's glare (0 quads), the driver and
    the light flares (not hooked up), a race on the strips' buffers. The
    likeliest: the PICA picks mip levels its own way (per triangle,
    say), so most of the wall reads small levels and the box reads
    level 0. Less likely: the linear heap past the PICA's 256 MB vertex
    window (the log's `Linear heap: physical` line says; on Azahar it is
    20000000 to 24a33000). If it crosses 28000000, base georender's
    attribute buffers at 0x20000000 (after each BufInfo_Init and in
    `s_run.bufBase`).
  - **The capture (commit 7480451).** With `sdmc:/nfshp2_capture.txt`
    on the card as a race starts (its number the seconds in, 6 if none),
    `capture.c` writes `nfshp2_cap_colour.bmp` and `_depth.bmp`, then a
    frame of each georender draw in a flat colour that is its number
    (`_ids.bmp`, with the legend `_ids.txt`), then a frame with every
    texture at level 0 alone (`_lod0.bmp`). `tools/capture_view.py DIR
    --out OUT --box X0,Y0,X1,Y1` makes PNGs and names the draws under a
    box. If the level-0 frame has no box, the mip choice is it: set the
    LOD bias, or the made levels' sizes, so the PICA's choice agrees
    with the GS's. If it still has one, read the box's draws and their
    depth.
- **SC-3c is done** (b7cb25c, 24976dd). RenderEffects (0x00128da0)
  is in `acidsys.c`, checked by `afx_check` (30 scenarios, 0 differ;
  394 mutants, 390 caught, 4 equivalent). `trackview_draw` and
  `trackview_draw_frontend` run it for FrameEffects and WorldEffects
  in eDisplayFrame's order, and `georender_draw_sprites` draws its
  packets. On Azahar TRACKB12's chimney smoke draws at 29.4 FPS.
  `docs/formats/acidfx.md` has it.
- **SC-3d is done** (6427cc5). The CarSelector's 20 emitters of
  XE_SelectCarNebula and UpdateNebula, checked by `carsel_check`
  (8364 ops, 0 differ; 29 nebula mutations, 28 caught, 1
  equivalent). main.c steps FrameEffects each frame. On Azahar a faint
  blue haze rises round the car.


## State

**The target is the full game now, not the demo.** On 2026-09-27 the user
put the PAL retail disc in `PS2 Files/Full Game/` (`SLES_507.31`, stripped)
and asked for the full game: every track and car, the whole frontend, and
saving. Everything so far was ported from the demo disc's ELF, which keeps
its symbols. `docs/retail.md` has what differs. The short of it:
- The demo ELF already has most of the full game's code: the memory card
  flow, the save game, the autosave and the event tree. What made it a
  demo was its data and `TheDemoDiscManager`.
- `tools/retail_match.py` names 9,333 of the demo's 9,669 procedures in
  retail. `--audit` checks the 1,617 the port cites. 1,148 are the same,
  139 differ only in field offsets, 301 changed and 29 are unmatched. Of
  those cited from a `.c`, 130 changed. The list is `docs/retail_audit.txt`.
- `tools/retail_layout.py` maps each class's demo field offsets to
  retail's (`docs/retail_layout.txt`). 91 classes moved fields.
- Retail's data keeps the demo's chunk formats, with a few changes, and
  most tracks are only on the disc as `.LZC`.

**The port follows retail's behaviour and keeps the demo's names.**
Where retail changed only offsets, nothing is owed: the port keeps the
demo's struct layouts wherever the PS2's layout does not reach the 3DS.
A record read in place from the disc takes retail's layout, because the
port reads retail's discs: TrackInfo is 164 bytes now. Where retail
changed the code, the port follows retail, read through `retail_layout`'s
map. A checker whose object retail changed runs two scripts through its
one harness. The scenarios over what the port follows as retail has it
run on `tools/retail_model.py`'s image over `extracted-retail/`. The rest
run on the demo image, as before (`docs/retail.md`, "Two images, one
harness"). `loadertable_check` and `trackpath_check` do this so far.
`track_check` runs wholly on the retail image now.

**Phases 0-3 are closed.** Cars draw on the top screen out of
`CARS\*\GEOMETRY.BIN` (task 21), the frontend makes the disc's own menu
sounds through a ported `bSnd` over ndsp, and the geometry viewer is now
framed by the shipped `CM_ORBIT_CAR` boom on the ported `Camera` rather than
by a camera of its own -- all three heard or seen on Azahar, not just diffed.

Task 24 closed Phase 3: `TrackRoute.obj` is ported and the track's
centreline, its driving lines and its signposts all load. It is diffed, not
run -- see "Next" below for why, and for what task 27 owes it.

One hundred cross-checkers pass, plus the four table generators:

```bash
python tools/bvector_check.py && python tools/bmath_check.py && python tools/banim_check.py && python tools/bscreens_check.py && python tools/bootflow_check.py && python tools/bslotpool_check.py && python tools/geometry_check.py && python tools/texsrc_check.py && python tools/bui_check.py extracted/FRONTEND/FRONTB.BUN && python tools/sndbank_check.py out/SOUND && python tools/bsnd_check.py out/SOUND && python tools/bsound_check.py && python tools/emath_check.py && python tools/camera_check.py && python tools/cambase_check.py && python tools/orbit_check.py && python tools/shake_check.py && python tools/drivecam_check.py && python tools/playercam_check.py && python tools/player_check.py && python tools/raceinit_check.py && python tools/racecore_check.py && python tools/racerun_check.py && python tools/racecoord_check.py && python tools/rcstates_check.py && python tools/trackroute_check.py && python tools/carstate_check.py && python tools/engine_check.py && python tools/cartypeinfo_check.py && python tools/carinfo_check.py && python tools/carloader_check.py && python tools/cardriver_check.py && python tools/steering_check.py && python tools/rigidbody_check.py && python tools/suspension_check.py && python tools/wheel_check.py && python tools/drivetrain_check.py && python tools/drivetarget_check.py && python tools/drivetarget_image_check.py && python tools/graph_check.py && python tools/car_check.py && python tools/physicssystem_check.py && python tools/aerodynamics_check.py && python tools/physcomp_check.py && python tools/sinit_check.py && python tools/physicscar_check.py && python tools/mellowmover_check.py && python tools/carmode_check.py && python tools/careffects_check.py && python tools/carinit_check.py && python tools/difficulty_check.py && python tools/joystick_check.py && python tools/joyhid_check.py && python tools/realtime_check.py && python tools/mainloop_check.py && python tools/realdriver_check.py && python tools/quickspline_check.py && python tools/trackpath_check.py && python tools/average_check.py && python tools/airoute_check.py && python tools/realcontroller_check.py && python tools/track_check.py && python tools/vclip_check.py && python tools/polyhedra_check.py && python tools/collisionbody_check.py && python tools/collision_check.py && python tools/world_check.py && python tools/scenery_check.py && python tools/scenerycull_check.py && python tools/eview_check.py && python tools/loadertable_check.py && python tools/texturepack_check.py && python tools/texturestream_check.py && python tools/trackflow_check.py && python tools/sky_check.py && python tools/sun_check.py && python tools/weather_check.py && python tools/rain_check.py && python tools/mv3_check.py && python tools/jukebox_check.py && python tools/jbstream_check.py && python tools/songmon_check.py && python tools/setup_check.py && python tools/racesetup_check.py && python tools/carrenderinfo_check.py && python tools/carrender_check.py && python tools/rendercars_check.py && python tools/resource_check.py && python tools/fred_check.py && python tools/fredrace_check.py && python tools/flailer_check.py && python tools/hudfeatures_check.py && python tools/bprintf_check.py && python tools/hudrender_check.py && python tools/hudanim_check.py && python tools/hudscore_check.py && python tools/hudcop_check.py && python tools/hudnis_check.py && python tools/hudtach_check.py && python tools/carsel_check.py && python tools/selcam_check.py && python tools/fecar_check.py && python tools/trackmap_check.py && python tools/envsample_check.py && python tools/gen_bmath_tables.py --check && python tools/gen_bsnd_tables.py --check && python tools/gen_scanner_tables.py --check && python tools/gen_terrain_table.py --check
```

```
bvector_check      27 scenarios,  5721 lines, 0 differ   (23/23 mutations caught)
bmath_check        19 scenarios,  6643 lines, 0 differ   (11/11 mutations caught)
banim_check        23 scenarios,  2219 lines, 0 differ
bscreens_check     17 scenarios,  1277 lines, 0 differ
bootflow_check     61 scenarios, 46779 lines, 0 differ   (219 mutations; the 25 for UnlaunchFrontendMenus all caught)
bslotpool_check    18 scenarios,  1025 lines, 0 differ   (47/47 mutations caught)
geometry_check     30 files,     42047 lines, 0 differ   (53/53 mutations caught)
texsrc_check       6 packs, 2 levels, 2958 textures, 0 differ
bui_check          FRONTB.BUN    1395 lines, 0 differ
sndbank_check      30 banks,       908 lines, 0 differ   (20000 mutations, 0 disagree)
bsnd_check         12 scenarios,  5157 lines, 0 differ   (25/25 mutations caught)
emath_check         9 scenarios,  2418 lines, 0 differ   (42/42 mutations caught)
camera_check        4 scenarios,   556 lines, 0 differ   (32 caught, 3 equivalent)
cambase_check       1588 ops,     5624 lines, 0 differ   (61/61 mutations caught; retail's image)
orbit_check         3416 ops,    28635 lines, 0 differ   (119 caught, 5 equivalent; retail's image)
shake_check         4114 ops,    10604 lines, 0 differ   (95 caught, 3 equivalent; retail's image)
drivecam_check     45598 ops,   105702 lines, 0 differ   (474 caught, 19 equivalent; retail's image)
playercam_check     5277 ops,   162056 lines, 0 differ   (109/109 mutations caught; retail's image)
player_check        3659 ops,   515143 lines, 0 differ   (287/287 mutations caught; retail's image)
raceinit_check      3280 ops,    13317 lines, 0 differ   (123/123 mutations caught; retail's image)
racecore_check      6097 ops,    18698 lines, 0 differ   (158 caught, 3 equivalent; retail's image)
racerun_check      21656 ops,    40973 lines, 0 differ   (169 caught, 2 equivalent; retail's image)
racecoord_check     7038 ops,    26129 lines, 0 differ   (135 caught, 1 equivalent; retail's image)
rcstates_check    29584 ops,    64046 lines, 0 differ   (225 caught, 5 equivalent; retail's image)
trackroute_check   11 scenarios,  1353 lines, 0 differ   (57 caught, 1 equivalent)
carstate_check     10 scenarios,   653 lines, 0 differ   (56 caught, 7 equivalent)
engine_check        8 scenarios,   414 lines, 0 differ   (56 caught, 2 equivalent)
cartypeinfo_check   4 scenarios,   200 lines, 0 differ   (45/45 mutations caught)
carinfo_check       198 ops,      2602 lines, 0 differ   (85 caught, 2 equivalent; retail's image)
carloader_check     583 ops,     10747 lines, 0 differ   (107 caught, 7 equivalent; retail's image)
cardriver_check     5 scenarios,   118 lines, 0 differ   (45 caught, 1 equivalent)
steering_check      5 scenarios,   873 lines, 0 differ   (43 caught, 1 equivalent)
rigidbody_check    10 scenarios,   935 lines, 0 differ   (76 caught, 2 equivalent)
suspension_check   10 scenarios,  1108 lines, 0 differ   (66 caught, 2 equivalent)
wheel_check        19 scenarios, 10696 lines, 0 differ   (145 caught, 10 equivalent)
drivetrain_check   18 scenarios,   498 lines, 0 differ   (173 caught, 3 equivalent)
drivetarget_check  22 scenarios,   897 lines, 0 differ   (243 caught, 19 equivalent)
drivetarget_image_check 22 scenarios, 897 lines, 160 masked, 0 differ (243 caught, 19 equivalent)
graph_check        16 scenarios,   151 lines, 0 differ   (21 caught, 4 equivalent)
car_check          58 scenarios,  4242 lines, 0 differ   (238 caught, 16 equivalent)
physicssystem_check 12 scenarios,  739 lines, 0 differ   (61 caught, 1 equivalent)
aerodynamics_check  7 scenarios,   107 lines, 0 differ   (74/74 mutations caught)
physcomp_check      8 scenarios,   239 lines, 0 differ   (46 caught, 1 equivalent)
sinit_check        19 calls,        0 problems           (6/6 mutations caught)
physicscar_check  106 scenarios, 102908 lines, 0 differ (257 caught, 6 equivalent)
mellowmover_check  39 scenarios, 56080 lines, 0 differ  (341 caught, 5 equivalent)
carmode_check      74 transitions, 19 resets, 36093 lines, 0 differ (380 caught, 11 equivalent)
careffects_check    110 ops,       519 lines, 0 differ   (133 caught, 3 equivalent; retail's image)
carinit_check     247 scenarios,  9637 lines, 0 differ   (168 caught, 1 equivalent; retail's image)
difficulty_check     42 ops,       374 lines, 0 differ  (24/24 mutations caught; 68 image facts, 11 readers)
joystick_check     64240 ops,    75891 lines, 0 differ  (246 caught, 4 equivalent)
joyhid_check       every key and stick reaches its event
realtime_check     28 scenarios, 2016 ops, 8781 lines, 0 differ (101 caught, 2 equivalent)
mainloop_check     11 scenarios, 4195 ops, 5097 lines, 0 differ (46/46 mutations caught)
realdriver_check  152455 ops,    41163 lines, 0 differ  (118 caught, 4 equivalent)
quickspline_check   6640 ops,     6898 lines, 0 differ  (133/133 mutations caught)
trackpath_check     4946 ops,     4746 lines, 0 differ; retail 5557 ops, 5095 lines, 0 differ  (201 caught, 3 equivalent)
average_check        482 ops,      843 lines, 0 differ  (64/64 mutations caught)
airoute_check      14738 ops,     7224 lines, 0 differ  (86 caught, 5 equivalent)
realcontroller_check 14096 ops,  25318 lines, 0 differ  (129 caught, 11 equivalent)
track_check        18033 ops,    11379 lines, 0 differ  (308 caught, 6 equivalent; retail's image)
vclip_check        11890 ops,    22389 lines, 0 differ  (280 caught, 1 equivalent)
polyhedra_check    15907 ops,    64560 lines, 0 differ  (172 caught, 12 equivalent)
collisionbody_check 1572 ops,    35426 lines, 0 differ  (622 caught, 24 equivalent)
collision_check     3587 ops,     6859 lines, 0 differ  (121 caught, 10 equivalent)
world_check         2742 ops,    15110 lines, 0 differ  (330/330 mutations caught)
scenery_check       3450 ops,    16724 lines, 0 differ  (77 caught, 2 equivalent)
scenerycull_check   7273 ops,    46687 lines, 0 differ  (147 caught, 1 equivalent)
eview_check         2103 ops,    15454 lines, 0 differ  (152 caught, 1 equivalent)
loadertable_check  37553 ops,    50792 lines, 0 differ  (138 caught, 2 equivalent)
texturepack_check   6698 ops,    11464 lines, 0 differ  (131 caught, 1 equivalent)
texturestream_check  380 ops,     7353 lines, 0 differ  (142/142 mutations caught; retail's image)
trackflow_check       22 scenarios, 2333 lines, 0 differ  (252 caught, 2 equivalent; retail's image)
sky_check             46 scenarios, 1311 lines, 0 differ  (93 caught, 2 equivalent)
sun_check            115 scenarios, 3427 lines, 0 differ  (154/154 mutations caught)
weather_check         75 scenarios, 4368 lines, 0 differ  (85 caught, 4 equivalent)
rain_check            31 calls,       31 lines, 0 differ  (5/5 mutations caught; 41 image facts)
mv3_check            904 scenarios, 50435 lines, 0 differ  (191 caught, 6 equivalent; 8 frames)
jukebox_check        952 ops,       4833 lines, 0 differ  (279 caught, 4 equivalent)
jbstream_check       real tunes cut at pairs and the end, 0 differ
songmon_check        321 ops,       1307 lines, 0 differ  (46 caught, 2 equivalent)
setup_check          359 ops,       2293 lines, 0 differ  (142 caught, 3 equivalent)
racesetup_check      398 ops,       3420 lines, 0 differ  (82 caught, 4 equivalent)
carrenderinfo_check  321 scenarios, 105544 lines, 0 differ (161 caught, 2 equivalent)
carrender_check      740 scenarios, 211648 lines, 0 differ (301 caught, 3 equivalent)
rendercars_check    1272 scenarios,  20075 lines, 0 differ (89 caught, 0 equivalent)
resource_check        10 scenarios,  3250 lines, 0 differ (153 caught, 2 equivalent; retail's image)
fred_check             9 scenarios, 54344 lines, 0 differ (103/103 mutations caught; retail's image)
fredrace_check         8 scenarios, 50503 lines, 0 differ (216 caught, 1 equivalent; retail's image)
flailer_check      54104 ops,   120233 lines, 0 differ  (106 caught, 4 equivalent; retail's image)
hudfeatures_check   1298 ops,    10373 lines, 0 differ  (164 caught, 6 equivalent; retail's image)
bprintf_check       5879 ops,    11758 lines, 0 differ  (35 caught, 1 equivalent; retail's image)
hudrender_check     1278 ops,     7620 lines, 0 differ  (152 caught, 4 equivalent; retail's image)
hudanim_check        473 ops,     2829 lines, 0 differ  (290 caught, 2 equivalent; retail's image)
hudscore_check      1608 ops,     6184 lines, 0 differ  (150 caught, 0 equivalent; retail's image)
hudcop_check        1187 ops,     4763 lines, 0 differ  (115 caught, 5 equivalent; retail's image)
hudnis_check         818 ops,     4359 lines, 0 differ  (118 caught, 1 equivalent; retail's image)
hudtach_check       2287 ops,     7804 lines, 0 differ  (89 caught, 4 equivalent; retail's image)
carsel_check        7373 ops,   459051 lines, 0 differ  (264 caught, 9 equivalent; retail's image)
selcam_check        4266 ops,    52296 lines, 0 differ  (141 caught, 2 equivalent; retail's image)
fecar_check         1439 ops,    13217 lines, 0 differ  (124 caught, 1 equivalent; retail's image)
gen_bmath_tables --check           bmathtab.c is up to date
gen_bsnd_tables  --check           bsndtab.c is up to date
gen_scanner_tables --check         joyeventid.h, scannertab.c are up to date
gen_terrain_table --check          terraintypetab.c is up to date
```

`texpack_check.py` takes a file and is run per pack; it now also diffs the UV
scroll, offsets and all: `FRONTB.BUN` 2 scrolling textures, `INGAMEB.BUN` 1,
`TEX12LOCATION.BIN` 21, 0 differ.

Two mutation runners are kept rather than thrown away:
`python tools/bslotpool_mutate.py` (~20 minutes) and
`python tools/geometry_mutate.py` (~2 minutes; `--full` for all 30 files).

Both sound checkers want a directory of `.SBK`. Build it first. The
chain's is the demo's; the card's is retail's:

```bash
python tools/audio_pack.py extracted/SOUND out/SOUND
python tools/audio_pack.py extracted-retail/SOUND out/SOUND-retail --report
python tools/sndbank_check.py out/SOUND-retail --audio --sound extracted-retail/SOUND
```

The transcode is exact (`docs/formats/sound-bank.md`, "The transcode is
exact"), and `--audio` fails on any sample that differs.

The emulator's copy lives at `%APPDATA%\Azahar\sdmc\NFSHP2\SOUND` -- that is
the data root `gamedata.c` resolves to on this machine, and the
`.SBK` files go beside the other converted assets. `bsnd_check.py --mutate`
takes about ten minutes; `sndbank_check.py --mutate 20000` takes a couple of
hours.

`camera_check.py --mutate` reports "3 equivalent, 0 unexplained" rather than
"3 survived": the three are named in the script with an argument each. They
are uncatchable because the disc's velocity record is structurally zero. See `docs/formats/camera.md`. `trackroute_check.py
--mutate` reads the same way and takes about four minutes.

Open tasks: **7** (26-31 and 36, the full game). All four the user asked for mid-session are
done and looked at on Azahar: 32 (stretch the frontend to the 3DS's 5:3 top
screen), 33 (the ten unregistered screen names), 34 (the menu description on
the bottom screen, wrapped) and 35 (no console sharing that screen).

The bottom screen is a citro2d target now, not a console. Everything the
console used to show is in `sdmc:/nfshp2_debug.txt`, which is opened `"w"`
and so replaced every boot.

## Next, in order

1. **Task 36's first slice is closed: the demo's names carried over to
   the retail ELF.** `docs/retail.md` has it all.
   - `tools/mdebug.py` reads the demo's ECOFF procedure table: 9,669
     procedures, 1,336 of them missing from `.symtab`. They are each
     unit's copies of inline destructors and `operator delete`, and the
     statics.
   - `tools/retail_match.py` pairs demo functions with retail's. Its
     `--audit` and `--diff` are how to use it while porting.
   - `tools/retail_layout.py` votes demo field offset -> retail offset
     from loads and stores off `this` in matched methods.
   - `tools/zdir_names.py --retail` names 369 of the retail directory's
     406 entries into `docs/zdir_names_retail.txt`. It now names every
     entry that shares a hash, because retail lays three files down twice.
   - `tools/zdir_extract.py --retail --only GLOB` extracts pieces of the
     retail disc into `extracted-retail/` (ignored). Do not extract all
     3 GB: the tree is under OneDrive, and C: has about 20 GB free.

   **Task 36's second slice is closed: the retail model (step 5), and
   the first of step 4.**
   - `tools/retail_model.py` runs `SLES_507.31` in mipsemu under the
     demo's names. `e.code`, `e.data` and `e.field` map a demo address,
     datum or field to retail's. The plain `Emu` answers them with what
     it is given, so one checker runs either image.
   - `track_check` runs the track info on the retail image over retail
     GLOBALB and TRACKB12. TrackInfo is retail's 164 bytes, with
     `SignpostGracePeriod` at 128.
   - The LoaderTable is retail's 30 slots. PhysPredict is gone, and
     HeliSheet takes `0x80034800`. `loadertable_check` runs the claims
     and the walks through LoadChunks on the retail image.
   - `retail_match` no longer cuts a function at a return that a branch
     crosses. That had put UnloaderHeliSheet inside LoaderHeliSheet.
   - `zdir_extract.py --decompress` writes a track's `.LZC` out expanded
     as its `.BUN`. The port ships the tracks already expanded and never
     decompresses one on the 3DS.

   **Task 36's third slice is closed: TrackRoute's retail pass.**
   - Retail's Signpost is 12 bytes, with an int32 `AIHint` at 8 (0, 1 or
     2; only 2 is read, by the AI). The loader divides by 12, and every
     walk over the signs steps by 12.
   - Retail's InitTrackRoutes marks each DontTake sign's `NewRoute` with
     Flags bit 2, `TROUTE_DONT_TAKE_TARGET`. The constructor clears it,
     and nothing in retail reads it. Sign 5 is DontTake, by the .mdebug's
     predicate order and SignPostDecision.
   - `trackroute_check` is a hand-written model, rewritten to retail's
     disassembly. A new scenario runs the loader, both inits and the
     unloader over retail TRACKB12's and TRACKB21's own routes and signs.
   - The AI's use of `AIHint` goes with the step-10 retail pass of
     `airoute.c` and the controller.

   **Task 36's fourth slice is closed: the texture pack's retail pass.**
   - The header is 84 bytes, with a 64-byte file name between the name
     and the pointer. `TexturePack` is 148 bytes, with the file name at
     40. The constructor takes it, or NULL for the streaming half's packs.
   - GetTextureInfo's third argument looks among unloaded records too.
     AttachTextureTable no longer looks each record up.
   - `RenameTextureInfo` (`0x001ac4d8`) and `SwapTextureInfoNames`
     (`0x001ac548`) are ported. ServiceGameFlow's French swap, their one
     caller, goes with the frontend (step 16).
   - `texturepack_check` runs wholly on the retail image, over twelve
     retail texture files: a TRACKB12 race's ten and TRACKB21's two.
   - `sky_check` gained a mutation for the third argument of the sky's
     own lookup.

   **Task 36's fifth slice is closed: the difficulty table's retail
   pass.**
   - `DifficultyInfo` is retail's 992 bytes. The demo's two static
     position-ratio tables moved into it at 240 and 304, and
     `SkillLevelDistribution` gained a second set, `[0]` with cops and
     `[1]` with none. Everything else is 128 or 248 bytes on.
   - Retail's ELF has no stab, so the layout is held to its readers:
     `difficulty_check` decodes 68 instructions in eleven functions and
     scans retail for every address formed in the table. It runs the
     loader and unloader on the retail image over retail GLOBALB's chunk
     and eight more. `docs/formats/difficulty-info.md` has it all.
   - `carmode_check` dumps only the catchup's knees, which both discs
     share, and its loader mutations moved to `difficulty_check`.
   - Two of `carmode_check`'s mutations had drifted onto
     `carcollisionbody_init` since b702739 and survived unseen. They are
     anchored to the set-up now, and caught.

   **Task 36's sixth slice is closed: the solid list's retail pass.**
   - eFixUpTables looks up nine textures. The eighth,
     `pTextureInfoFalloffRamp` (`0xb9ab56e4`, a name on no disc), is
     made at run time. `efix_falloff_ramp` is retail's `0x00103260`,
     which fills its palette with greys from 128 down to 1.
   - ReconnectSolid ORs `bRandom(256)` from `bDefaultSeed` into the
     start time when the solid has flag `0x20` (`SOLID_RANDOM_START`),
     which only TRACKB61..66's waving flag carries.
   - Every `get_texture_info` passes GetTextureInfo's third argument, 0.
   - UnloaderSolidList and UnloaderTrackGeometry differ only in an
     address and an unused `divu`: nothing to port.
   - `loadertable_check` runs the solid, fix-up and model scenarios on
     the retail image, and adds the random start, the ramp, a list of a
     header alone, and retail's disc (all but the tracks, plus TRACKB12
     and TRACKB61). Each disc file's heap is given back after it.
   - `retail_model` gave a name at two demo addresses (a COMDAT copy)
     the map's pick, not the demo symbol's copy, so a stub by name could
     miss on retail what it caught on the demo. 134 names were so. It
     takes the demo symbol's copy now.

   **Task 36's seventh slice is closed: the sun's retail pass.**
   - Retail's Z buffer is PSMZ24, and eTransferZBufferRect reads it as
     32-bit words: a SunZBuffer is 4,112 bytes, and StuffSun counts a
     word's low 24 bits under 2. The transfer does nothing without
     `InGameFlag`.
   - StuffSun draws layer 0 at z 1, which GEQUAL passes only over the
     clear, and the rest at the render target's `MaxZ` (retail's +116,
     set by 0x00105ac0: 16777215 for PSMZ24). The glare draws at `MaxZ`.
     ePoly's constructor puts z at 0. `eview_set_max_z` is that part of
     0x00105ac0, and the viewer's target is PSMZ24.
   - The rect is moved onto the target, and StartX..EndX is the sun's
     part of it.
   - StuffSunGlare draws `SunGlareInfo` (0x002ef4c0), which LoaderSun
     fills with four fixed layers for any sun chunk, and times itself in
     RealTimer's ticks in a `Timer` (0 and 0x7fffffff unset).
   - On the 3DS, `render_epoly` turns the quad's Z back into a depth:
     `MaxZ` draws with no test, and layer 0 at depth 0, GEQUAL, over the
     sky alone. The readback is 32-bit.
   - `sun_check` and `sky_check` run on the retail image; `sky_check`
     takes retail TRACKB12's own chunk, and `loadertable_check` runs its
     sun scenario on retail too.

   **Task 36's eighth slice is closed: retail's data on the card (step
   4).** The card's data folder is `sdmc:/NFSHP2` and holds retail's
   files alone, all 30 tracks expanded.
   - The viewer takes a track number and names `TRACKB<n>.BUN`,
     `TEX<n>TRACK.BIN` and `TEX<n>LOCATION.BIN` from it. ZL/ZR unload
     one and load the next on the card; `run_azahar_track.ps1 -Switches
     5` walks TRACKB12, 21, 31, 41, 61 and 11, and they all draw.
     `TRACKVIEW_MAX_SOLIDS` is 1,536 for TRACKB61 and B64's 1,345.
   - Retail's Flailer objects carry a `char Name[24]` at +16 that shifts
     everything after it. `bui.c` and `flailer_dump.py` tell the layouts
     apart per object, and `bui_check` gives 0 differ on all six bundles
     of both discs. `docs/formats/flailer-ui.md`, "Retail".
   - The title screen's logo, `LOADING`, is only in `GLOBAL\DYNTEX.BIN`
     on retail. The port loads that pack at boot, as the game does.
   - The sound banks are retail's 25. `audio_pack.py` no longer decodes
     and re-encodes: it rewrites each SPU frame as two DSPADPCM frames,
     and all 398 retail and 469 demo channels come back sample-exact.
     The user heard the frontend's sounds on Azahar.

   **Task 36's ninth slice is closed: the boot movies.** The title
   screen plays retail's `EALOGO_EN.AVI` and then `NFSINTRO_EN.AVI`
   (`NFSINTRO_FR.AVI` in French) straight off the card, with their
   sound, and START skips the intro. The user watched and heard both on
   Azahar. `docs/formats/mv3-video.md`.
   - `mv3.c` is a native MV3 decoder from retail's DCTImage, Huffman and
     MV3Codec. It decodes intra frames only, and every frame of all 12
     retail movies is one. `mv3_check` holds it bit-exact to the retail
     image in mipsemu.
   - `avimovie.c` streams the AVI's `movi` list off the card. It paces
     frames by the console's tick and skips any frame that is late.
     Azahar at 100% decodes 154 of the EA logo's 180 frames.
   - The sound is not the 8-bit mono the `strf` claims. It is SPU ADPCM
     stereo at 43,617 Hz, decoded chunk by chunk into ndsp. `bSnd`
     leaves the movie a channel (`BSND_HW_VOICES` 23).
   - Retail's `TitleMoviesToPlay` (`0x002fb750`) is in `gameflow.c`. The
     demo's `.M3V` path is gone: `movie.c`, `movie_bake.py` and
     `movie_check.py`.
   - The movies fill the top screen, as the user asked. The EA logo is
     stretched from 4:3. The intro loses at most a 32nd of its width
     each side, so the EA TRAX credit stays in frame
     (`docs/formats/boot-flow.md`).
   - START goes through the menu, as FlailerMenu's `JoyHandler` takes
     it, so it skips the intro and leaves PRESS START. `main.c` used to
     send the screen `SCREEN_START_BUTTON` alone.
   - Two things cost time, and neither was the port. First, Azahar was
     unthrottled (`frame_limit=0`, "Speed: 1792%"), which made the
     movies run fast. Second, `--mutate` writes its mutants into the
     real sources. An ARM build made while it ran took `pace-done` and
     hung the EA logo on its last frame. Build only after a mutation
     pass finishes.

   **Task 36's tenth slice is closed: Car's constructor and
   destructor, from retail.** It is the first slice of road step 6.
   `carinit.c` has retail's `Car::Car` (`0x00130a48`), `~Car`
   (`0x00130ee0`), `CloseRenderInfo` and `CarReflectEventHandler`, on the
   demo's layout of Car. `docs/formats/car.md`'s twelfth code slice has
   them and the field map.
   - `car.h` gains retail's four new fields, at the end (2016..2047), so
     that every demo offset still holds. The table in `car.md` maps
     every demo offset to retail's (retail's Car is 2200 bytes).
   - Retail made five changes:
     - a distance along the track, and the weighted reset it seeds;
     - the new fields zeroed, and the rumble timer too;
     - `vOldPos` saved at the start;
     - CarDamage's part lookup after InitRenderInfo;
     - `ForceBuzzTime` rounded.
   - `trackpath.c` gains retail's weighted `FindClosestPoint` and the
     `ResetPosition` it seeds (`track-path.md`). `trackpath_check` runs
     on both images now.
   - `car_new_null_controller` moved into `carcontroller.c`, and
     `esp_set_attribute_int` into `espresso.c`, a seam that skips when
     unset. `CarUsageType`'s values are in `cartypeinfo.h`.
   - The sound, CarDamage, the render info and the event manager are
     seams. Those that only add a part are skipped when unset. Those that
     can only be reached through a part abort. Step 8b's AddRacingCar
     calls the constructor.
   - `carinit_check` runs the retail image in RetailEmu, with the
     callees stubbed. It dumps the whole car at retail's offsets after
     every call, so every store is checked, and so is its order.

   **The frontend's first slice is closed: retail's title screen.**
   On 2026-09-28 the user sent seven PCSX2 photos of the retail PAL
   frontend and asked for the port's to match them. The port works down
   that list now, ahead of step 6's second slice. The title screen runs
   retail's `TitleScreen` now, not the demo's. The user confirmed it on
   Azahar. After a skipped intro, the screen comes to rest on the logo.
   The logo sits alone for four seconds. Then PRESS START blooms under
   it, with the copyright line.
   - A select during the NFS intro stops the intro and stays on the
     title. The demo went to the main menu, and so did the port.
   - `PRESS START` and the select that leaves both wait four seconds
     from the first tick at rest (`0x0016f4f8`). The `TITLE_IMAGE`
     group shows at rest, and a `tHighlightAnimation` blooms PRESS
     START.
   - `RenderFlailerBitmap` draws a `SPLASH_SCREEN` or `PANELMOVIE`
     bitmap only as the open movie. With no movie open, it draws
     nothing. `uirender.c` and `flailer_render.py` now do the same.
     Before this, a skipped intro left its frozen last frame over the
     logo.
   - `bootflow_check` runs retail's `TitleScreen::Callback` itself, in
     mipsemu. It has a `--mutate` pass, which catches 25 of 25.
   - Events start with the Noise their JoyHandler gives them
     (`joyNoise` in `gameflow.c`), so a swallowed click shows.
   - `docs/formats/boot-flow.md`, "Retail's `TitleScreen`".
   - Step 6's second slice was parked on `wip/carrenderinfo`
     (`616bb08`). It is in master now, with its checker (below).

   **The frontend's second slice is closed: the boot's loading and
   language screens.** The user corrected the order on 2026-09-28:
   LOADING is the first thing shown, then the language screen, then the
   movies, then the title. The title stays as it is. Azahar shows that
   order now. `docs/formats/boot-flow.md`, "Retail's
   `LOADING_FRONTEND`".
   - Retail's `LoadGlobalChunks` (`0x001682d0`), at the end of
     `InitializeEverything`, sets English, shows `LOADING_TRACK` and
     draws one frame outside `MainLoop`. `main.c` calls
     `bgf_load_global_chunks` before the `FRONTEND` bundle decodes, so
     LOADING stays up while it does.
   - Retail's Begin, Loop and End (`0x00168698`, `0x00168718`,
     `0x001687a8`). FRONTB's load callback (`0x00168668`) and the sound
     regions' (`0x00168658`) move the flow on. The Loop is only the demo
     slideshow. `main.c` has a small load queue for the callbacks.
   - `LanguageManager::SetLanguage` (`0x0021e0d0`) and its tail: speech
     swapped only if loaded, and the French logo art (`0x001681b0`).
   - `LanguageOptionsScreenBase` (`0x001f1a78`, `0x001f1b08`,
     `0x001f1dd8`), for both language screens. BACK takes the
     highlighted language. `MoveBackScreen` is `(n, 0, -1)` and the
     pad's BACK is `(1, 1, port)`. `MoveToPreviousScreen` sends
     `ItemHash` 0.
   - `uirender_draw_visible` draws every visible screen by layer, as
     `eDisplayFrame` does. The menu is built before `SCREEN_ACTIVATE`
     and activated after it (`hookOpenScreen`), as
     `FlailerScreen::Activate` does.
   - `bootflow_check` runs all of it on the retail image. There are five
     new scenarios and 57 mutations: 56 are caught, and
     `back-names-screen` is equivalent.
   - Owed: the speech banks, the French logo art on the host
     (`hookSwapLogoArt` only logs), and `Language Options`'
     `tSlideOnScreen` (`0x001ee918`).

   **The frontend's third slice is closed: `BootAutoload` and
   `ConsiderStartDemoMode` in full.** `docs/formats/boot-flow.md`, "The
   memory card" and "Retail's `ConsiderStartDemoMode`".
   - `memcard.c` holds retail's `BootAutoLoader` and everything under it:
     `MemcardLoader`'s state machine (`0x00246c00`), `MemcardTester`,
     `MemcardPrompter`, `SavegameData` and `OverwriteFred`.
   - `bpopup.c` holds `tPopupMenu` and the screen list's two popups, with
     `RenderTextIntoGroup`'s word wrap.
   - The card is the SD card. The user asked on 2026-09-28 for every save
     under `sdmc:/NFSHP2/SAVES`. `settings.db` goes there, and the folder
     is made on demand (`main.c`'s `SdCard`).
   - Azahar shows "Checking" and then "no save file" on the popup, in
     real translated strings, before the language screen. A save put
     there by hand was loaded, and was then removed from the card.
   - A popup takes the pad before the menus do (`main.c`, `MODE_FLOW`).
   - `ConsiderStartDemoMode` is retail's: signed, and it knows the demo
     disc's attract mode and `TheDemoModeReplay`.
   - `bootflow_check` runs it all on the retail image: 46 scenarios, with
     a scripted card table in both harnesses. `RetailAutoload` restores
     the emulator's stubs after each run. Before that fix, its
     `MoveBackScreen` stub swallowed the language screen's.
   - `--mutate`: 147 mutations, 144 caught, 3 equivalent.
     - `manualhalf` runs at half-second frames. At one-second frames,
       0.00025f rounds a whole second up, and a two-second wait and a
       three-second one end together.
     - The `slow` card's Verify outlasts the "Checking" wait.
   - Owed: message 24 (`ANY_BUTTON_PRESSED`), `OverwriteFred`'s six calls
     (nothing reads `Fred` yet), and the internals of `StartDemoMode`
     and `DemoModeReplay`. `MemcardSaver` came in Session 86. The popup's title strip runs
     off the right edge, as the popup screen is authored.

   **The frontend's fourth slice is closed: the menus' movie.** The main
   menu's movie loops in its `PANELMOVIE` plane on Azahar; Cops On's and
   Options' play in theirs. `docs/formats/mv3-video.md` and
   `docs/formats/boot-flow.md`, "The menus' movie".
   - `mv3.c` decodes inter frames: `pTransp`'s copy and no-residual bits,
     the vectors, `CopyPreviousFrameBlock`, the `IDCTAdd` family, and
     `SwapPrevBuffer`. The menus' five movies are 900 frames each, mostly
     inter. `mv3_check` holds them bit-exact to the retail image over
     synthetic inter movies and two runs of `MAINMENU_MOVIE`: 904
     scenarios, and 171 mutations, 168 caught and 3 equivalent.
   - `avimovie_step` is `MoviePlayer::Update`'s pacing: the next frame
     when it is due, one a call, never skipping, since an inter frame
     cannot be read past. `mv3_check` holds it to retail's `Update`.
   - `gameflow.c` has retail's `StartMovie`, `UpdateMovie` and
     `StopMovie`, and `StartDemoMode` and `UnlaunchFrontendMenus` stop the
     movie. The title's movie and the menus' share the player, as in
     retail: BACK to the title leaves the gate up, and `UpdateMovie`
     reopens `mainmenu_movie` under the title when the title's movies end.
   - `bootflow_check` runs the three on the image (`RetailMovie`), and
     `StartDemoMode` too: 49 scenarios, 159 mutations, 156 caught and 3
     equivalent. `mainmenu` was retimed; it had never reached the menu.
   - `run_azahar_test.ps1 -MenuLoop` waits on the main menu for the loop,
     and the log has each movie's `movie cost`.
   - The menu movies were slow on Azahar then: 22 ms to decode a frame
     and 9 to convert it. The fifth slice fixed that.

   **The frontend's fifth slice is closed: the menu movie at full speed.**
   The main menu runs at 59 FPS on Azahar and its movie at 30 fps, 900
   frames in 30.0 s. The Cops screens run at about 60.
   `docs/formats/mv3-video.md`: "The player", "Quantisation and the IDCT"
   and "YUV -> RGBA".
   - A worker thread decodes the menus' movies ahead of the picture, on
     core 2 on a New 3DS or else core 1, into three texture slots
     (`AVIMOVIE_SLOTS`). `aviplayer_update` keeps retail's rule. Where
     the rule decodes, it takes the next slot off the queue, and with none
     ready it answers 1, which is retail's ring-buffer wait.
     `avimovie_decode_next` is the read and decode both paths share. Movies
     with sound (the boot's) keep the main-thread path.
   - Exact speedups, each held by `mv3_check`:
     - The full IDCT's all-zero-AC column and row shortcuts.
     - The scan read inside the column pass.
     - The bit reader in registers.
     - The conversion a tile at a time, with `UQADD8` and `UQSUB8` in
       `Clamp`'s place. All 16.7 million Y, U and V were compared on the
       host and on Azahar.
   - On Azahar the worker spends 2.7 ms reading a main menu frame, 17
     decoding it and 5.4 converting it. Options' is the dearest, at 29 ms.
     An Old 3DS gives the worker 80% of core 1, about 27 ms, so the
     dearest movie will play a little slow there (road step 19).
   - `mv3_check`: 904 scenarios, 0 differ. Of 197 mutations, 191 are caught
     and 6 are equivalent: they turn off the 4-point and full IDCTs'
     shortcuts.

   **The frontend's sixth slice is closed: the Easter egg group
   hidden.** "Unlocked" and "Easter Egg" no longer show on the main menu,
   as in the retail photos. `docs/formats/boot-flow.md`, "`NewMainMenu`".
   - Both are authored visible in retail's `NEW_MAIN_MENU`, in group
     `0x74e404b4`. Retail's constructor (`0x00216460`) hides the group
     after `TheEasterEggs.Start()`, and the destructor hides it again after
     `Stop()`. The port does the same; `hooks.easterEggs` only logs, as
     the 78 codes are not ported.
   - Retail's `HandleEvent` vetoes BACK without a sound: `Param` and
     `Noise` cleared. The demo's went back to the title, and so did the
     port. BACK on the main menu now does nothing.
   - So the title's movie and the menus' no longer meet: the fourth
     slice's "BACK to the title leaves the gate up" cannot happen now.
   - `bootflow_check` runs retail's `Callback`, `HandleEvent` and
     `OnTick` on the image (`RetailMainMenu`) in place of the demo's
     model. The members, the jukebox, the two `Fred` calls and
     `ConsiderStartDemoMode` are stubbed, as the port owes them.
     `menuattract` is `menuidle`. `select` presses BACK on the title,
     `menumovie` drops InGameFlag again (`outgame`), and `attractmovie`
     stops a movie in attract mode: without them, the veto left the
     title's BACK and `StopMovie`'s gate unreached. 50 scenarios, 169
     mutations, 166 caught and 3 equivalent.
   - Azahar: BACK on the main menu is vetoed, silently. The group is set
     hidden 6 times in the walk and never shown.
   - Owed from the main menu: the 78 codes; attract mode from `OnTick`
     with message 24 (it waits on `StartDemoMode`'s race);
     `MakeChallengeCarsAvailable` and `InitWithDefaults`.

   **The main menu's highlight bars follow the highlight.** The user saw
   them stay around Hot Pursuit after going into a menu and back. The
   port's `NewMainMenu` had no `OnHighlight`, so the bars stayed where
   `NEW_MAIN_MENU` authors them.
   - Retail's `OnHighlight` (`0x00216938`) and `HighlightMenuItem`
     (`0x00216880`) are in `gameflow.c` now. Brackets go to the item's
     `MI_n_MASK` at -3 and -6, blurbs are 10016, 10015 and 10009, and
     `hooks.moveBrackets` and `hooks.setBlurb` are the Mode Selects'
     hooks in `main.c`.
   - The blurb shows on the bottom panel. The top screen's
     `SCROLLING_TEXT` stays hidden.
   - `bootflow_check` runs retail's `HighlightMenuItem`
     (`menuhighlight`). `run_azahar_test.ps1` counts the main menu's own
     bracket moves.
   - The bloom's `SetCurrentMenuItem` waits for the echo.

   **The demo disc's code is out of the port.** The port is the retail
   game, where `TheDemoDiscManager.bActive` is always 0, so it is
   written as if it were.
   - Gone: `demodisc.c`, the `EXIT_DEMO_DISC` state, the loading
     slideshow and its Loop, `BeginScreenFadeTime`, the one-movie title,
     the title's `StartDemoDiscGame`, `CheckForDemoDiscTimeout`, and
     `GenerateJoyEvents`' activity stamp.
   - Kept: attract mode (`StartDemoMode`, `ConsiderStartDemoMode`,
     `TheDemoModeReplay`), and retail's event table whole, with
     `JOY_EVENT_EXIT_DEMO_DISC` (2) and its START+SELECT row, since
     removing them would renumber every event after them.
   - The checkers hold `bActive` at 0 on the image. The demo scenarios
     and mutants are gone: `bootflow_check` 48 scenarios, 171 mutations
     (168 caught, 3 equivalent); `joystick_check` 250 (246 caught, 4
     equivalent; `gen-count` is new, as nothing reads the scanners'
     count now); `trackflow_check` 74 (73 caught, 1 equivalent).
   - The unused VP6 decoder, `source/vp6/`, is deleted too. Every movie
     is MV3 and `mv3.c` decodes it.

   **The highlight's echo is closed.** A red copy of the highlighted
   label grows out of it and fades, every four seconds, on Azahar.
   `docs/formats/boot-flow.md`, "The echo".
   - The echo is the bloom, `tHighlightAnimation` on
     `ANIMATING_MENUITEM`. Retail's `CopyFlailerText` (`0x001410a0`)
     copies the whole object but its hashes and strip: position, scale, Z,
     visibility and text. The port's copied only the text, and every
     screen authors `ANIMATING_MENUITEM` off the bottom edge (y 534 on the
     main menu, 676 on the title), so no bloom had ever shown.
     `bui_copy_text` is the whole copy now.
   - `NewMainMenu` builds retail's four members in the constructor's
     order (blurb, bloom, slide-in, SelectionSet), animates them in
     `OnTick`, and releases them in the destructor. `OnHighlight` calls
     the bloom's `SetCurrentMenuItem` first. Message 24 resets the idle
     Timer.
   - `bootflow_check`: 48 scenarios, 27,890 lines, 0 differ; 190
     mutations, 187 caught, 3 equivalent.
   - `run_azahar_test.ps1 -Echo` takes a burst of shots on the main menu.

   **The jukebox, EA TRAX and the GS's MODULATE are done** (HANDOFF.md,
   Session 31). `jukebox.c` is retail's player, `jbstream.c` streams the
   JBC to ndsp channel 22 (`bsnd` has 0..21), and `songmon.c` is
   `tNewSongMonitor`. `uirender.c` draws every Flailer quad with the GS's
   texel × vertex / 0x80, so `WHITE16X16`'s strips and masks have the
   photo's strength (flailer-ui.md, "Colour: the GS's MODULATE").
   - Open: the Options' Jukebox screen, and the stream on real hardware.

   **You're The Cop is done** (HANDOFF.md, Session 31, continued).
   `bsetup.c` is retail's `BeACopChallengeSetup` (`0x001b6c68`, screen
   `e55f1297`), with the arrows class (`0x0024a690`) and `tfeSineWave`
   that every setup screen shares. `docs/formats/frontend-setup.md`.
   - `setup_check`: 359 ops, 0 differ; 145 mutations, 142 caught, 3
     equivalent. Its harness reads Fred at retail's offsets written out,
     so a wrong offset in `bsetup.h` shows.
   - main.c's `hookSetup*` answer the Flailer calls. They include
     `GetBoundingBox` in ints and `SetCenterY` on
     `uirender_object_height`, which is `GetHeightFloat`.
   - "Select Car" and "Select Car2P" are registered as plain screens;
     `screen_registry.py --check-port` lists nothing reachable and
     unregistered.
   - Open: `tHelpMenu`, `mPolice` in Fred, and the three car calls.

   **Be The Cop Setup is done** (HANDOFF.md, Session 31, continued).
   `bsetup.c` has `RaceSetupBaseClass` (`0x001b8390`), `BeTheCopSetup`
   (`0x001b9248`, screen `d1eadbca`) and `tScrollingMenuList`: Catch-up,
   Traffic and Damage, with the arrows on the current row. BACK or SELECT
   writes them to Fred's `DataBeTheCopSetup` (+64).
   - `racesetup_check`: 398 ops, 3420 lines, 0 differ; 86 mutations, 82
     caught, 4 equivalent. `setup_check` still passes.
   - `bsetup_fred_defaults` puts retail's `InitWithDefaults` values for
     the two setup tables in Fred at boot (`main.c`). With no save, that
     is what the screens show: Catch-up On, Traffic Minimum, Damage On.
   - `uirender.c` does not clip yet: `bui_set_object_clip` keeps
     `SetClipToPoly`'s poly and format bit, and nothing draws with them.
     Three rows never reach the clip, so nothing shows it.
   - Open: the other four race setups (100..103), on the same base.

   **Next is cars and racing, not more menus.** On 2026-09-29 the user
   asked for the port to go back to making cars and racing work once Be
   The Cop Setup was done: "We don't need every single menu working".
   Car select (`SelectCarScreen`, `MakeChallengeCarsAvailable`
   `0x00183af8`, the preload at `0x00194898`, `Fred::InitWithDefaults`
   `0x00183830`) and the briefing wait, unless a race needs them.

   **CarRenderInfo is built from retail** (HANDOFF.md, Session 31,
   continued). This is the second slice of step 6, from `wip/carrenderinfo`.
   `carrenderinfo.c` has retail's `Car::InitRenderInfo`, the constructor,
   the destructor, SwitchSkin, UpdateCarReplacementTextures,
   CreateCarLightFlares and the culler's InitPart. It sits on
   `epositionmarker.c`, GetSkinInfo and GetUsedCarTextureInfo in
   `cartypeinfo.c`, and four eModel methods in `emodel.c`. The write-up is
   `docs/formats/car-render-info.md`.
   - `carrenderinfo_check`: 321 scenarios, 105544 lines, 0 differ. It runs
     163 mutations: 161 are caught and 2 are equivalent.
   - The check's model has to run bmath's static constructor
     (`0x002598d8`). Without it, bInitializeBoundingBox's empty box is zero.
   - Retail's box starts each model's box on uninitialised stack. The
     port starts it empty.
   - `main.c` sets `gCarInitRenderInfoFn` and `gCarRenderInfoDestroyFn`
     since step 8b. The sound, CarDamage and the event manager's seams
     stay NULL.

   **CarRenderInfo::Render is ported** (HANDOFF.md, Session 31,
   continued). This is step 6's third slice. `carrender.c` has Render
   (`0x00120ef8`), UpdateLightStateTextures, CalculateTireBlur and the
   culler's pass (`0x0011d980`). It also has the hull shadow's sh_Setup,
   convex_hull, smooth_shadow_corners, ch2d, make_chain, cmpl and cmph.
   The write-up is `docs/formats/car-render-info.md`, "Render".
   - `carrender_check`: 740 scenarios, 211648 lines, 0 differ. It runs
     304 mutations: 301 are caught and 3 are equivalent. Every stub is
     reached, and all 21 models are drawn.
   - Retail uses `lq` and `sq` on frame memory, so the scenarios keep the
     frame position 16-aligned, as the game does. Each stub's v0 is
     sign-extended; a zero-extended -1 passes retail's `slti`.
   - The culler's other function, `0x0011d648`, has no callers and is not
     ported.
   - Render takes the forced lights as its seventh argument (1, 2, 4 and
     8 for head, brake, reverse and cop). RenderCars passes 0.
   - Nothing calls Render in the game yet, so the 3DS link drops it.

   **RenderCars is ported** (HANDOFF.md, Session 31, continued). This is
   step 6's fourth slice, and it closes the step. `rendercars.c` has
   RenderCars (`0x00124060`) and the two helpers only it calls:
   `0x00133190`, whether the car blinks in the view, and `0x00135fb8`, the
   tyres' and the brakes' matrices. The write-up is
   `docs/formats/car-render-info.md`, "RenderCars".
   - `rendercars_check`: 1272 scenarios, 20075 lines, 0 differ on the
     first run. It runs 89 mutations, and all 89 are caught.
   - DamageAbove (`0x00135280`) is `gCarDamageAboveFn`, NULL until the
     cops (step 12): it calls DamageCap and asks the race coordinator, the
     cop manager and IsBeingPursued.
   - `player.h` now names ViewID (+20; retail +24), and `player.c` has
     `PlayerPlayersByIndex` (retail gp-20928).
   - The loop reads `pCurrentWorld` again for each test, as retail does.
   - Nothing calls RenderCars in the game yet. eDisplayFrame is not
     ported; step 8's game flow is what draws a race.
   - The front end's cars wait for the car selector (step 16). Only
     CarSelector and tCarModelViewer make a FrontEndRenderingCar, so
     RenderFrontEndCars (`0x00123d28`) draws nothing in a race. Its layout
     notes: the demo's record is 640 bytes, and retail puts an eModel * at
     624 and adds fields at 640 and 644. Its methods are the constructor
     `0x0011e5c0`, ReInit `0x0011e758`, the destructor `0x0011e7d8` and
     OverRideAlpha `0x0011e858`; RenderFrontEndCar is `0x00123c90`.

   **Step 7's first slice, 7a-1, is done** (HANDOFF.md, Session 31,
   continued: the camera base). Step 7 is cut in five: 7a-1, the
   foundations; 7a-2, the shake (7a-2a) and the drive camera's small
   members (7a-2b); 7b, DriveCameraMover::Update; 7c, the orbit mover's
   retail pass; 7d, Player's camera functions.
   `docs/formats/camera.md`, "Retail", has the write-up.
   - Retail's bATan (`0x0025a890`) returns 0 below a squared length of
     1e-4 (gp-26336), and eMulVector (`0x0011b300`) takes a -0 lane in as
     +0. Both are in `bmath.c` and `emath.c` now.
   - Camera is retail's 464 bytes, with ClearVelocity at 432. Both
     constructors put the far plane at 10000.
   - CameraMover has retail's fifteen-slot vtable (`CameraMoverVtbl`),
     the destructor, "CM_UNKNOWN(?)", and UpdateCameraMovers and
     RenderCameraMovers (`update_camera_movers`, `render_camera_movers`).
     The orbit mover sat on the vtable and was otherwise still the
     demo's until 7c.
   - `cambase_check` runs retail's own code for all of it in RetailEmu:
     1588 ops, 5624 lines, 0 differ, and 59 of 59 mutations caught. It
     runs the static constructor at `0x0011bf70` itself, since RetailEmu
     runs none, and eMulVector reads the (0, 0, 0, 1) it writes.
   - `eview_check`'s demo model now reads 10000 for the camera's far
     plane (demo gp-31464).
   - `scenery_check`'s demo model runs the bATan under
     CreateFacadeMatrix on retail's image. CreateFacadeMatrix is the same
     on both discs, and its (0.001, 0.002) case showed the floor.

   **7a-2a, the camera shake, is done too** (HANDOFF.md, Session 31,
   continued: the camera shake). `docs/formats/camera.md`, "The camera
   shake", has the write-up.
   - `shake.c` has tEnvelope, tShaker, the shake globals and their share
     of the static initialiser (`sinit.c` [24]), the reset
     (`reset_camera_shakers`), UpdateCameraShakers, GetShake,
     IsShakeActive, ApplyCameraShake, MaybeCameraShake and
     Car::MaybeCameraShake. `player.c` has Player::IsCameraPOVInCar.
   - ApplyCameraShake builds the shake into its rotation's translation
     row, because the image's frame puts the matrix at sp+16 and
     eMulVector's output at sp+64. So the camera moves as well as tips,
     and each angle reads the row as the rotations before it left it.
   - `player.h` has cPlayerSettings (40 bytes) and pCameraMover, at the
     demo's offsets. `cammover.h` has POV (32 bytes) and its types.
   - `main.c` sets `gCarMaybeCameraShakeFn`. No car has a player until
     step 8, so nothing shakes yet.
   - `shake_check` runs retail's code in RetailEmu: 4114 ops, 10604 lines,
     0 differ. Of 98 mutations, 95 are caught and 3 are equivalent.

   **7a-2b, the drive camera's small members, is done** (HANDOFF.md,
   Session 31, continued: the drive camera's small members).
   `docs/formats/camera.md`, "The drive camera", has the write-up.
   - `drivecam.c` has DriveCameraMover's vtable (`0x002b1dd0`), the
     constructor, the destructor, ResetState, SetPOVIndex, GetPOV,
     GetTarget, GetCameraInfo, GetCarToFollow, the three new virtuals
     (IsExteriorView, IsLookingBack, GetWallGap), the three corrections,
     CalculateLookbackAngle and the accessors. `camerainfo.h` lays out
     CameraInfo (272 bytes) and POV, and CarTypeInfo carries it at 960.
   - The vtable's Update is the base's, which does nothing, until 7b.
     Nothing builds a drive camera until 7d.
   - `player.h`'s word at 12 is retail's int Lookback, where the demo's
     was the float LookbackSpeed. The three new virtuals count a look back
     only while it is 0.
   - GetAccelLag (`0x0015c708`) has no caller, and nothing points at it,
     so it is not ported. The in-car correction has no caller either, but
     it is small and is ported.
   - `drivecam_check` runs retail's code in RetailEmu: 2941 ops, 7406
     lines, 0 differ. Of 149 mutations, 146 are caught and 3 are
     equivalent.

   **The topology's retail pass is done** (HANDOFF.md, Session 31,
   continued: the topology's retail pass). `docs/formats/topology.md` has
   the write-up.
   - `track.c` is retail's `Track.obj` (`0x001513c8 .. 0x00153984`). Road
     noise followed with TerrainType's retail pass, below.
   - TopologyCoordinate is retail's 704 bytes: 160 polygons, the last
     polygon at 688 and three unused words at 692. TopologyTree is 44
     bytes, with an unused word at 32. Car's TC is at 1280 in the port, so
     everything after it moved on by 144. `car.h` is 2192 bytes.
   - GetElevation tries the last polygon first, at any height. That
     polygon is set by a hit strictly inside, and forgotten by
     SetInterestBBox's rebuild and by ClearInterestBBox.
   - SetInterestBBox's look-ahead is 0.15, times 0.75 per try, over five
     tries, and the fifth uses 0. A box fits when its diagonal is under
     28.8. NumUpsideDown now counts what pass 3 placed.
   - BuildTrackPolygons walks every square under the box, and only while
     the box is inside (-32768, 32767). The timing is gone.
   - `track_check` ran everything but road noise and MatchTerrainType on
     the retail image, over retail TRACKB12. The retail model has to run
     bmatrix's static initialiser (`0x0025afa8`), or retail's
     `bMulMatrix(bVector3)` loses the translation.

   **TerrainType's retail pass is done** (HANDOFF.md, Session 31,
   continued: TerrainType's retail pass). `docs/formats/topology.md` and
   `docs/formats/car.md`'s tenth slice have the write-up.
   - TerrainTypeInfo is retail's 144 bytes. SkidWidthMultiplier is new at
     20 (MaybeMakeSkids, `0x001a568c`, multiplies it into
     `WheelInfo.Width`), and everything after it is 4 bytes later. On a
     64-bit host the record is 184 bytes.
   - `gen_terrain_table.py` writes the table (`0x00318c00`, 33 x 144) out
     of `SLES_507.31`. Retail changed the loose surfaces' emitter groups,
     ROAD's skid smoke window, BOARDWALK's and COBBLESTONE's road noise
     and METAL_GRATE's road sound.
   - GetRoadNoise reads offsets 24 and 28, so `track.c` is all of
     retail's `Track.obj`. `track_check` runs wholly on the retail image:
     18033 ops, 11379 lines, 0 differ (308 caught, 6 equivalent).
   - TriggerCarTerrainEffects (`careffects.c`) is retail's `0x00133920`.
     Inside the splash, a player's car on every fourth world step above
     30 m/s registers "InDeepWater" (10, once, through
     InDeepWaterRegistered) or "InShallowWater" (1.25) with the replay.
     The engine smokes above 0.9 of visible damage. Short of that, the
     radiator steams when item 14's level is 3 (`0x00124d38`) and the
     damage is above 0.65.
   - `careffects_check` runs it in RetailEmu: 110 ops, 519 lines, 0
     differ, 133 of 136 mutations caught and 3 equivalent.
     `carmode_check` no longer runs slice ten.
   - `replay.h` is still the demo's layout (retail's ReplaySnapshotList
     is at 112 and TotalInterestingValue at 332). Nothing reads a
     ReplayManager in place yet, so it owes a retail pass before that
     happens.

   **7b, DriveCameraMover::Update, is done** (HANDOFF.md, Session 31,
   continued: the drive camera's Update). `docs/formats/camera.md`,
   "`Update`", has the write-up.
   - `drivecam.c` has Update (`0x0015c880`), GetLookbackCar
     (`0x0015c680`), the wall push (`0x00157930`, `camera_wall_offset`)
     and the look-at offset (`0x00157b60`, `camera_look_at_offset`), with
     the Drive* and Cam* tuning words at retail's values. The vtable's
     Update is drive_cam_update now.
   - `copmanager.h` has tCop (pMyPursuit 0, pMyCar 4) and tPursuit's
     pChasedCar at retail's 16 (the demo's 20), `pCopManager` at retail's
     gp-15620, and seams for GetCopByCar (`0x00224f70`) and GetCopByChase
     (`0x00224fc8`). Nothing sets the seams until the cop manager is
     ported.
   - The constructor and ResetState take LastCarSpeed from
     State.ForwardSpeed (retail car +960). 7a-2b called that word
     VelocityMagnitude.
   - Every float constant is checked against the words the image loads.
     The heading's 1/4.7 is `0.21276592f` (`0x3e59df4f`). The first
     `0.212766f` was six units off, and no transcript showed it.
   - `drivecam_check` runs all of it in RetailEmu: 14 scenarios, 45598
     ops, 105702 lines, 0 differ. Of 493 mutations, 474 are caught and 19
     are equivalent. Ten of those are the boom's last translate and turn,
     which the image works out after the eye and never reads outside. The
     corners scenario catches the twelve that line coverage missed.
     Every line and branch of
     Update runs under `gcov -b`, except the no-cop-manager answer Update
     never asks for, retail's own dead branch (`air` is ±1 and is tested
     against 0) and combinations the code rules out.
   - The demo's GetBoomDistToWall (`0x0015e028`) and its two line-segment
     helpers are dead in retail and not owed. `0x00157c60`,
     BumperCameraMover::Update's wall code, calls the same two helpers
     and waits for the bumper camera.

   **7c, the orbit mover's retail pass, is done** (HANDOFF.md, Session
   31, continued: the orbit mover's retail pass). `docs/formats/camera.md`,
   "Retail's orbit mover", has the write-up.
   - The mover moved out of `cammover.c` into `orbitcam.c` and
     `orbitcam.h`, as `drivecam.c` holds CM_DRIVE. It follows a Car:
     GetTarget (`0x001580e0`) is the car's GeometryPosition, and
     GetCarToFollow is `0x0015fb18`. CamCarView is gone.
   - The constructor (`0x00157e48`) ends with AddJoyHandlers, and the
     destructor (`0x00158080`) calls RemoveJoyHandlers first. Both go
     through `joyevent.c`, for events 46-54 on JoyPort. Neither checks for
     a camera. TM is never written.
   - Update (`0x00158298`) returns while IsGameFlowPaused (`0x001680b8`,
     `is_game_flow_paused` in `race.c`). It follows World's Helicopter
     while its Plan is below 3 (unsigned) or is 4, with no boom offset.
     The AngleV clamp is gone.
   - `chopper.h` lays out Chopper's head: Plan at 728, CurrentPos at 832,
     Matrix at 848, counted from TOPOLOGY_SIZEOF. Nothing builds a chopper
     until task 26, so Helicopter is NULL.
   - The geometry viewer follows a stand-in Car and clamps AngleV itself.
     It destroys its mover before building the next one, and in
     geoview_free: each constructor takes nine of EventNodeSlotPool's 96
     nodes, and the pool does not overflow.
   - `orbit_check` runs retail's code in RetailEmu: 9 scenarios, 3416
     ops, 28635 lines, 0 differ. Of 124 mutations, 119 are caught and 5
     are equivalent. `camera_check` keeps only the Camera and base-mover
     scenarios: 4 scenarios, 32 of 35 caught, 3 equivalent. Its two view
     mutations moved to `cambase_check`, which catches 61 of 61.

   **7d, Player's camera functions, is done** (HANDOFF.md, Session 31,
   continued: Player's camera functions). It closes step 7.
   `docs/formats/camera.md`, "The player's cameras", has the write-up.
   - `playercam.c` and `playercam.h` have ChangeCameraMover
     (`0x00176ae8`), CycleDriveCameraPOVIndex (`0x001786d0`),
     RestoreCameraMover (`0x00176948`), RemoveCameraMovers (`0x00177430`),
     EnableCameraMovers (`0x001774a8`) and DisableCameraMovers
     (`0x00177558`). They sit apart from `player.c` because they build
     movers, and `player.c`'s harnesses have no use for `drivecam.c` and
     `orbitcam.c`.
   - The drive camera and the orbit camera are built. The debug world,
     the track route editor, the zone freeze, the zone preview, the cubic
     damper and the two zone jumpers are seams, NULL until their classes
     are ported. So are the coordinators, the NIS manager's three calls,
     the driving line's two and PreviewRoute's destructor. With a mover's
     seam NULL, nothing is allocated and the player has no camera.
   - The coordinators are deleted before the same-type test, as retail
     does. Movers are deleted through their virtual destructor, so the
     orbit's joystick handlers come off.
   - `player.h` gained pSavedCameraMover2 (retail +208), first at the
     port's 2480 and at 208 since 8a gave Player retail's layout. SkipFE
     is `gPlayerCamSkipFE`, which
     `main.c` points at the flow's skipFE.
   - Restoring with nothing saved does nothing. Retail calls Enable
     through NULL there. Its two callers, RequestZone and ClearZone,
     restore when a zone camera is up.
   - `playercam_check` runs retail's six functions in RetailEmu: 7
     scenarios, 5277 ops, 162056 lines, 0 differ. All 109 mutations are
     caught. Three of them crash the harness on a NULL car, and that
     counts as caught.
   - Nothing calls these yet.

   **8a, Player's lifetime, is done** (HANDOFF.md, Session 31,
   continued: Player's lifetime (step 8a)). `docs/formats/player.md` has
   the write-up.
   - `player.h` is retail's 2752-byte Player, field for field, with
     retail's 48-byte cPlayerSettings. The offsets are asserted where
     pointers are 4 bytes. pSavedCameraMover2 is at retail's 208 now, and
     camera.md's offset table has one column. lastCar is at 2616, not
     the 2600 the first 8a notes gave.
   - `playerinit.c` and `playerinit.h` have the constructor
     (`0x001751d8`), the destructor (`0x00175bf0`), InitForRace
     (`0x00181920`), PredetermineNisNumbers (`0x001819e0`),
     CleanupAfterRace (`0x00181970`), CleanUpJumpCam (`0x00176ab0`) and
     cPlayerSettings::ResetToDefaults (`0x001edf90`). `nisoverlay.c` and
     `nisoverlay.h` have NISOverlayManager (56 bytes in retail): its
     constructor (`0x00182350`), destructor (`0x00182430`), SetScreen
     (`0x001829a8`) and Finish (`0x00182948`).
   - These are seams:
     - the HUD's Flailer calls
     - the NIS manager's three calls
     - the zone sample's and the driving line's destructors
     - the HUD animators' destructor
     - CreateRandomNisArray
     - SetInputMode

     With gNewNisManagerFn NULL there is no manager.
   - The port differs from retail in three places:
     - Both player tables stop at two. Retail's third pPlayersByIndex
       entry would be the count.
     - GetTopLeft isn't called on a missing score object.
     - The Average is the port's size until Average's retail pass.
   - TheRaceParameters' +628, which the overlay test reads, is BeACop.
     `race.h` has AIDemoMode and ReplayDemoMode, and `playerinit.h` has
     RaceParametersPlayerSettings[2] (+652). When
     RaceParameters::InitWithDefaults is ported, it still owes
     ResetToDefaults on both settings.
   - `main.c` sets gPlayerCleanUpJumpCamFn, so Car::FinishMovement ends
     the jump cam through playerinit.c.
   - `player_check` runs retail's code in RetailEmu: 8 scenarios, 3659
     ops, 501513 lines, 0 differ. All 287 mutations are caught, three
     of them by crashing the harness. Before the run, it compiles
     player.h with devkitARM and asserts all 158 Player fields and 14
     overlay fields at retail's offsets.
   - Nothing builds a Player yet. 8e's InitForRace does, once
     the flow into a race wires the coordinator in.

   **8b, InitCars and InitPlayers, is done** (HANDOFF.md, Session 31,
   continued: InitCars and InitPlayers (step 8b)).
   `docs/formats/raceinit.md` has the write-up.
   - `raceinit.c` and `raceinit.h` have InitCars (`0x0014a2c8`),
     InitPlayers (`0x00149cb8`), AddRacingCar (`0x00149f10`) and
     CalculateRacerPositions (`0x0014a020`). `race.c` has the driver
     array and GetDriverInfo (`0x001edb28`).
   - DriverInfo is 24 bytes, as retail's is. It gains retail's rank
     byte, EliminatedRank, at the end. Above 0, InitCars skips the
     driver.
   - These are seams: AddCopCarToRace (`0x00227d78`), Chopper's
     constructor (`0x001e7a90`) and the egg table. With the cop seam
     NULL, each cop driver still counts towards the helicopter and the
     Be A Cop call.
   - The heights are not what the first 8b notes said. One
     TopologyCoordinate serves every slot, and each probe starts from
     the height of the slot before, 0 for the first.
   - The port differs from retail in three places, none of them seen:
     - With no override, the AI racers' start route is zeroed. Retail
       leaves it unset.
     - The slots' fourth lanes are zeroed.
     - An override that names a NULL route gives a NULL point, not 1064.
   - `main.c` sets gCarInitRenderInfoFn and gCarRenderInfoDestroyFn, and
     makes the two render-info slot pools.
   - `raceinit_check` runs retail's code in RetailEmu: 32 scenarios,
     3280 ops, 13317 lines, 0 differ. All 123 mutations are caught,
     five of them by crashing the harness. Before the run, it compiles
     raceinit.h with devkitARM and asserts DriverInfo's layout.
   - Nothing calls InitCars yet. 8e's InitForRace does, once
     the flow into a race wires the coordinator in.

   **8c, Race's construction, is done** (HANDOFF.md, Session 31,
   continued: Race's construction (step 8c)). `docs/formats/race.md` has
   the write-up. Race.obj turned out to be three steps, not one: 8c is
   the construction, 8d the race's own running start (Race::Init and
   what it calls), 8e RaceCoordinator::InitForRace.
   - `race.h` declares the whole 1716-byte Race, field for field, with
     the offsets asserted where pointers are 4 bytes. `race.c` has
     TheRaceParameters' Point2Point (+40) and NumLapsInRace (+44, 2 by
     default). pCurrentRace is retail's gp-22272, `0x003301f0`.
   - `racecore.c` and `racecore.h` have Race's constructor
     (`0x001475e8`) and destructor (`0x001476e0`), FigureOutBoundaries
     (`0x00147b20`), AddBoundaryPosition (`0x001479f8`),
     GetLapNumberExact (`0x00147d58`), SetupGhostCars (`0x001485e0`,
     empty), RacingCar's constructor (`0x001493b8`) and UnInit, and
     TimeAroundTrackTable's constructor (`0x001467a0`),
     GetTimeTableEntry, GetTimeAroundTrack and destructor.
   - The one seam is the WorldObject destructor, gWorldObjectDeleteFn.
     Retail destroys the replaying ghost car's WorldObject only inside
     the test of its data, and nothing in retail makes either.
   - The boundaries are read and written through the Race's bytes, as
     the image does, so a finish number of -1 reads the four bytes
     before the array.
   - `racecore_check` runs retail's code in RetailEmu: 9 scenarios, 6097
     ops, 18698 lines, 0 differ. Of 161 mutations, 158 are caught, one
     of them by crashing the harness, and 3 are equivalent. Before the
     run, it compiles racecore.h with devkitARM and asserts Race's and
     the table's layout.
   - Nothing builds a Race yet. 8e's InitForRace does, once
     the flow into a race wires the coordinator in.

   **8d, Race::Init and the lap counting, is done** (HANDOFF.md,
   Session 31, continued: Race::Init and the lap counting (step 8d)).
   `docs/formats/race.md` has the write-up.
   - `racerun.c` and `racerun.h` have Race::Init (`0x00147960`),
     AddRacingCars (`0x00147dc0`), AddRacingCar (`0x00147e88`),
     SetRaceStage (`0x00147ef0`), SortRacingCarsByLeadership
     (`0x00148218`), RacingCar::Init (`0x00146bb0`), UpdateLapCounts
     (`0x00146fd0`), CheckBoundaryCrossing (`0x00146e58`),
     FakeStartlineCrossing (`0x00146e08`) and GetPlayer (`0x001475b8`).
     `timer.c` has Timer::Round (`0x001a3e28`) and RoundSeconds
     (`0x001a3d70`).
   - `race.h` has the RaceTypes enum (type#1000) and TheRaceParameters'
     RaceType (+32, `0x0031a8b8`). Only a time trial's finish line is
     timed while a replay plays.
   - The one seam is FrontendDatabase::TheRaceIsLeaving (`0x00187570`),
     gRaceIsLeavingFn, which SetRaceStage calls on the way to racing.
     With it NULL nothing is told.
   - `carstate.h` gains retail's DistanceMoved (State+876 in retail).
     The port keeps it in the record's spare tail, at 1012, so that every
     demo offset holds. The constructor zeroes it, as retail's does, and
     UpdateLapCounts divides it by the race time for AverageSpeed.
     **Still owed:** retail's FinishMovement (`0x00131da8`) adds to it
     how far Position moved since vOldPos. The port's FinishMovement is
     the demo's and does not, so AverageSpeed reads 0 in the game until
     FinishMovement has its retail pass.
   - `racerun_check` runs retail's code in RetailEmu: 14 scenarios,
     21656 ops, 40973 lines, 0 differ. Of 171 mutations, 169 are
     caught and 2 are equivalent. Before the run, it compiles
     racerun.h with devkitARM and asserts its layout.
   - Nothing calls Race::Init yet. 8e's InitForRace does, once
     the flow into a race wires the coordinator in.

   **8e, RaceCoordinator's lifetime, is done** (HANDOFF.md, Session 31,
   continued: RaceCoordinator's lifetime (step 8e)).
   `docs/formats/race-coordinator.md` has the write-up.
   - `racecoord.c` and `racecoord.h` have the constructor (`0x00149738`),
     the destructor (`0x00149858`), InitForRace (`0x00149988`),
     CleanupAfterRace (`0x00149b88`), CleanupPlayers (`0x00149d78`),
     CleanupCars (`0x0014a5f0`), the queue (ChangeState `0x00149520`,
     ExecuteQueuedMessages `0x00149578`, SendMessage `0x00149650`,
     PostMessage `0x001496d8`), SetAIDriverModesFromPlayers
     (`0x001cd240`) and GetDriverInfoByDriverNumber (`0x001edb40`).
     `racecoordinator_new` is `new RaceCoordinator` for trackflow's seam.
   - The ten state callbacks are a table of seams, gRCStateCallbacks.
     A NULL entry takes nothing. Retail's table is at `0x002f0bf0`.
   - The other seams, each NULL until its class lands: the pause menu,
     the ReplayManager, DisableRenderEggs, collision_sound::Reset, the
     speech queue, CleanUpAutoReplay, the Chopper's destructor,
     KillAllActiveEffects, jukebox::Stop, sound3d_oneshot::Reset,
     EndGameScreens' destructor and FindResourceFile by name.
   - `race.h` gains TheRaceParameters' NumAICars (+52, 7).
   - Retail's destructor frees what is left on the queue into the pool
     it has just deleted. The port only empties the list.
   - `racecoord_check` runs retail's code in RetailEmu: 175 scenarios,
     7038 ops, 26129 lines, 0 differ. Of 136 mutations, 135 are
     caught and 1 is equivalent. Before the run it compiles
     racecoord.h with devkitARM and asserts its layout.
   - **Not wired yet:** `main.c` leaves gNewRaceCoordinatorFn NULL, so
     loading a track still builds no race. Wiring it builds the players,
     the World and the cars through the real InitCars. That belongs to
     the slice that flows into a race, which first needs the state
     callbacks. trackflow.h's delete seam takes `int` flags, but
     racecoordinator_destroy takes `int32_t`, which is `long` on
     devkitARM. The wiring needs a cast or a wrapper.

   **8f, the states up to the finish, is done** (HANDOFF.md, Session
   31, continued: the race coordinator's states up to the finish (step
   8f)). `docs/formats/race-coordinator.md` has the write-up.
   - `rcstates.c` and `rcstates.h` have RCStateNoneCallback
     (`0x0014a668`), RCStateCameraFlybyCallback (`0x0014abe0`),
     RCStatePreRaceCallback (`0x0014acf8`), RCStateRaceInProgressCallback
     (`0x0014ae80`), DisplayCountdownNumber (`0x0014b260`) with
     Animate321GoElement (`0x0014b108`), TheRaceHasFinished
     (`0x0014bce0`), the joystick handler (`0x0014a7f8`), RequestPause
     (`0x001832a8`), RequestUnPause (`0x00174e00`), Resume/
     SuspendDemoCameras (`0x0014a818`, `0x0014a878`) and the frontend's
     record-times loop (`0x001842a8`). `rcstates.c` defines
     gRCStateCallbacks with these four; the other six are NULL.
   - `racefinish.c` and `racefinish.h` have Race's
     GetCountdownNumberToDisplay (`0x001480c0`), GetCountdownProgress
     (`0x00148188`), SimulateRaceFinish (`0x00148f68`),
     NotifyTheRaceIsOver (`0x00148ff8`), AreAllPlayersFinishedRacing
     (`0x001490b0`) and GetMostRecentlyFinishedPlayer (`0x001490f8`).
     FinishCar (`0x001485f0`) and RaceEvent::RecordResults are seams.
   - `race.h` gains tGlobalDisplaySettings and
     TheRaceParameters.GlobalDisplaySettings (+748).
   - The port reads a NULL flyby or prerace camera as finished, skips
     the replay's marks without a ReplayManager, and does not finish a
     race with no players. Retail reads all of these unchecked. The
     demo-disc branches are dropped.
   - `rcstates_check` runs retail's code in RetailEmu: 402 scenarios,
     17258 ops, 40165 lines, 0 differ. Of 148 mutations, 143 are caught
     and 5 are equivalent.
   - **Not wired yet:** as for 8e. Every seam is NULL in the game.

   **8g, the pause and the post-race, is done** (HANDOFF.md, Session
   31, continued: the race coordinator's pause and post-race (step 8g)).
   `docs/formats/race-coordinator.md` has the write-up.
   - `rcpost.c` and `rcpost.h` have RCStatePauseCallback (`0x0014b3d8`),
     RCStatePostRaceCallback (`0x0014bdd8`), Player::BeginPause
     (`0x00181bd0`) and EndPause (`0x00181bd8`), and TellPlayersToPause
     and TellPlayersToUnPause (`0x00181c88`, `0x00181ce8`).
     gRCStateCallbacks has six states now; the two replays and the two
     demos stay NULL.
   - RaceCoordinator+140 is `PostRacePlayerNumber`: the best-placed
     player, whose car the post-race's demo camera follows.
   - The replay's two words (+12, the highlights' mute, and +160,
     EndCurrentHighlightTime) are seams, as 8f's marks are. The port's
     post-race TICK does nothing with no ReplayManager.
   - `rcstates_check` runs both, with GetJoystickType and the empty
     World::BeginPause/EndPause, in RetailEmu: 600 scenarios, 29584 ops,
     64046 lines, 0 differ. Of 230 mutations, 225 are caught and 5 are
     equivalent.
   - **Not wired yet:** as for 8e. Every seam is NULL in the game.

   The replay states (instant `0x0014b568`, auto `0x0014b848`) and the
   demo states (`0x0014a8c0`, `0x0014aa38`) wait: a race runs without
   them, and the replays need ReplaySnapshot, which is not in the count.
   Their table entries are NULL: ChangeState enters such a state, and no
   callback runs for its messages.

   **8h, the car data loader, is done** (HANDOFF.md, Session 31,
   continued: the car data loader (step 8h)). `docs/formats/car-info.md`
   has the write-up.
   - `carinfo.c` and `carinfo.h` have LoaderCarInfo (`0x00187f98`),
     UnloaderCarInfo (`0x00188128`), AccelerationTable's constructor
     (`0x00188d68`), GetAccelerationTable (`0x00188dd8`),
     MakeAccelerationTable (`0x00188df0`) and the static constructor
     (`0x001890c8`, the demo's `0x00181060`, `__CTOR_LIST__` [35]) over
     TheCarTypeAccelerationTable (`0x0030daf0`, 64 of 148 bytes).
   - Slot 16 is ported in `bchunkload.c`, and `sinit.c` runs the
     constructor. At boot `main.c`'s loadGlobalCarInfo offers slot 16
     GLOBALB's top-level chunks in the file's order, so CarTypeInfoArray
     and the 235 skins point into the resident bundle and the 64 tables
     are made before the frontend loads. The rest of GLOBALB is still
     only the UI's (trackview.h). Seen on Azahar: the boot log has
     `car data: 2 chunks, 235 skins`, and `run_azahar_test.ps1` passes.
   - MakeAccelerationTable's samples go to a 404-byte bMalloc that is
     never freed (25856 bytes once, at boot), as in retail. With no
     samples at all, which no record on the disc reaches, the port
     leaves the table as it was.
   - The last session's worry that six-gear cars read a stale up[7] was
     wrong: CalculateShiftPoints writes the top gear's up point (MaxRPM)
     at NumGears + 1, so every point the walk reads is the car's.
     `carinfo_check` runs every load under seven stack fills and no
     table moves.
   - `carinfo_check` runs retail's code in RetailEmu: 6 scenarios, 114
     ops, 2181 lines, 0 differ. Of 78 mutations, 77 are caught and 1 is
     equivalent. `loadertable_check` links the car modules now and
     treats slot 16 as ported.

   **8i, CarLoader, is done** (HANDOFF.md, Session 31, continued:
   CarLoader (step 8i)). `docs/formats/car-loader.md` has the write-up.
   - `carloader.c` and `carloader.h` are retail `0x001b0260` ..
     `0x001b0fd0`: InitCarLoader, CloseCarLoader, LoadedSkin's
     constructor and GetUsedTextures, LoadedCar's constructor,
     FindLoadedCar, FindLoadedSkin, Load, IsLoaded, Unload,
     UnloadEverything, RemoveUnusedCarsAndSkins, BeginLoading,
     LoadingDoneCallback, ~CarLoader, the static constructor and the
     bridge.
   - **Correction to the old plan:** retail's Load, IsLoaded and Unload
     read `CompressedGeometryFilename` (CarTypeInfo+96) and
     `CompressedDashGeometryFilename` (+160), not `GeometryFilename`
     (+64) or the plain dash name (+128). Those are the demo's.
   - `cartypeinfo.c` has GetNumSkins (`0x001884b8`) and GetSkinNumber
     (`0x001884d8`), both new in retail. A cop's skin is 1 in English and 2
     otherwise, read through `gCurrLanguageFn`.
   - Wired in `main.c`:
     - `gCurrLanguageFn` answers `g_flow.currLanguage`.
     - `init_car_loader` runs after the frontend's bundles, as
       InitializeEverything's InitCarLoader does.
     - `sinit.c` runs the static constructor at `__CTOR_LIST__` [56].
   - Nothing loads through TheCarLoader yet. Its four seams
     (LoadResourceFile, ServiceResourceLoading, LoadTexturesFromFile and
     UnloadTexturesFromFile) are NULL until the resource system is in.
     Seen on Azahar: `car loader: pool up` in the boot log, and
     `run_azahar_test.ps1` passes.
   - Port-only decisions:
     - UnloadEverything returns when the service seam is NULL, where
       retail would spin forever.
     - The slot size stays a literal 48, guarded by a 32-bit-only layout
       check.
   - Retail lets a count go below 0: a skin or dash still loading that is
     unloaded twice. The port does the same.
   - `carloader_check`: 11 scenarios, 583 ops, 10747 lines, 0 differ. Of
     114 mutations, 107 are caught and 7 are equivalent.
   - InitCarInfo (`0x00188d08`) is still unported.

   **8j, the resource system, is done** (HANDOFF.md, Session 31,
   continued: the resource system (step 8j)).
   `docs/formats/resource-file.md` has the write-up.
   - `resource.c` and `resource.h` are retail's ResourceFile, `0x00199320`
     .. `0x00199a6c`: the constructor, AllocateMemory, the destructor,
     LoadResourceIfFileTransferFinished, FileTransferCallback, GetSize,
     both LoadResourceFile, both ChangeFilenameForHotChunking,
     UnloadResourceFile, ServiceResourceLoading,
     IsResourceLoadingComplete, both FindResourceFile, GetResourceFileSize
     and the list's static constructor and destructor.
   - `queuedfile.c` and `queuedfile.h` are retail's QueuedFile,
     `0x001ad6d8` .. `0x001add40`: the constructor, BeginRead,
     ServiceQueuedFiles, FindQueuedFile, Init/CloseQueuedFiles,
     AddQueuedFile, ChangeQueuedFileParams, AbortQueuedFile,
     ReadDoneCallback, SortByPriority and the static pair.
   - `bfile.c` and `bfile.h` are port-only: bOpen, bClose, both
     bFileSize, bSeek, bReadAsync and bServiceFileSystem over stdio and
     the SD card. A read lands at once and its callback waits for the next
     bServiceFileSystem, so none runs before bReadAsync returns.
   - `bmem.c`'s bMalloc now keeps the pool word's alignment (0x40 is 128
     bytes, 0x20 64, 0x10 32), through memalign. ResourceFile's buffers
     are 0x40, as LoadChunks needs.
   - `lzc.h` builds on the host now (`<3ds.h>` only under `__3DS__`).
   - Retail's behaviour worth knowing for 8k:
     - one file loads per ServiceResourceLoading, in request order, and
       the callback runs after the count drops;
     - a missing or empty file loads as nothing (`LoadChunks(NULL, 0)`)
       on the next service; a read that fails loads the heap's leftovers;
     - UnloadResourceFile services until the file is loaded, which loads
       every older file first;
     - GLOBAL\INGAMEA.BUN is 0 bytes on the disc, so 8k's first load is
       one of those.
   - Wired in `main.c`:
     - `init_queued_files` runs where InitializeEverything's
       InitQueuedFiles does, after LoadConfig and before eMathInit;
     - the car loader's LoadResourceFile, ServiceResourceLoading and
       UnloadResourceFile seams, trackflow's `gFindResourceFileFn`,
       racecoord's `gFindResourceFileByNameFn` and the texture packs'
       `gServiceQueuedFilesFn` are the real ones;
     - ServiceResourceLoading runs after each frontend frame, before the
       frontend's own bundle callbacks;
     - `trackview_free` puts the two track seams back as it found them,
       instead of NULLing them.
   - `sinit.c` runs both static constructors: [39] and [52].
   - `resource_check`: 10 scenarios, 429 ops, 3250 lines, 0 differ;
     155 mutations, 153 caught, 2 equivalent (`lif_guard_done`,
     `dtor_hnum`). The 17 other checkers that link `bmem.c` pass,
     `sinit_check` has 21 calls, and Azahar passes.
   - The frontend's bundles (FRONTB, INGAMEB, GLOBALB) are still read by
     `main.c`'s addBundle, not through ResourceFile.

   **8k, the track-loading game flow states, is done** (HANDOFF.md,
   Session 31, continued: the track flow (step 8k)).
   `docs/formats/track-flow.md` has the write-up.
   - `trackflow.c` and `trackflow.h` are retail's four track states and
     their parts: BeginGameFlowLoadingTrackCommon (`0x00168db8`) and its
     Parts 1 and 2, LoadHudTextures (`0x00168c30`),
     BeginGameFlowLoadingTrackSpecific (`0x001690a0`) and its Parts 1 to
     6, the End (`0x00169168`, now retail's: it sets the eggs unless a
     demo), and both Begins of unloading (`0x00169288`, `0x00168ea0`, with
     the leak checks and the eggs' reset).
   - `hudtex.c` and `hudtex.h` are ChooseLoadableTextures (`0x001ee3c0`),
     which Player::SetHudFeatures (`0x001796b0`) calls too.
   - `gameflow.c` makes the speech public: `bgf_load_current_speech` and
     `bgf_unload_current_speech` (LanguageManager's `0x0021e250` and
     `0x0021e280`).
   - `bfile.c` opens a missing `.LZC` as its `.BUN`: the card has the
     tracks' TRACKB only expanded.
   - `main.c` puts the four states in `kGameFlowStages` (rows 4, 5, 7 and
     8), through wrappers that set `gTrackFlowGameFlow` first.
     `trackview_free` runs the Begin of unloading with it NULL, so the
     viewer neither changes the flow nor unloads the frontend's speech.
   - New seams, NULL on the device: eFlashScreen, DemoModeReplayLoad,
     LoadSoundRegionsInGame, SetRenderEggFromEasterEggs, ResetRenderEggs
     and ClearTemporaryEasterEggs. A NULL load seam runs its callback at
     once, so the chain still reaches RACING.
   - `trackflow_check` runs retail's code in RetailEmu: 22 scenarios, 749
     ops, 2333 lines, 0 differ. Of 254 mutations, 252 are caught and 2
     are equivalent (`uts_files_unguarded`, `utc_files_unguarded`).

   **8l-1, InitFred and TheRaceParameters, is done** (HANDOFF.md,
   Session 31, continued: InitFred and TheRaceParameters (step 8l-1)).
   `docs/formats/frontend-database.md` has the write-up.
   - `fred.c` and `fred.h` are FrontendDatabase as retail's byte layout
     (FrontendPlayerInfo 1744 bytes at `0x10738`), its constructor
     (`0x001836a0`), InitFred (`0x00183820`), InitWithDefaults
     (`0x00183830`), MakeChallengeCarsAvailable (`0x00183af8`),
     HighScoreTable's InitStatsTables (`0x00186708`) and the four
     FrontendPlayerInfo methods: SetCarAvailability, SetDefaultCarType,
     AssignCarOfType and SetCharacterInfo.
   - `raceparams.c` and `raceparams.h` are RaceParameters'
     InitWithDefaults (`0x001ed5c8`), its static constructor
     (`0x001ee590`, sinit's [73]) and tGlobalDisplaySettings' defaults
     (`0x001ee0a0`). `race.h` has the 788-byte struct; its per-field
     globals are macros on TheRaceParameters now.
   - `characterinfo.c` is the character loader and unloader (chunks
     `0x34300` and `0x34301`) and the four getters. `playersettings.c` is
     cPlayerSettings' reset. `configitems.c` has the SkipFE and default-car
     words at their disc values. `edisplay.c` has the display offsets.
   - `gameflow.h` has three new hooks: raceDefaults, frontendDefaults and
     challengeCars. `main.c` calls InitFred after the global chunks, where
     it used to call `bsetup_fred_defaults`. GLOBALB's car chunks now also
     go through LoaderCharacterInfo, and its track table through
     LoaderTrackGeometry. Fred is `fred.c`'s, and the card loads over it.
   - Seams: IsCarUnlocked (NULL answers 0, as a fresh save does), the
     audio defaults (the jukebox's) and GetTranslatedString (the
     language table's).
   - `fred_check` runs retail's code in RetailEmu: 9 scenarios, 668 ops,
     54344 lines, 0 differ. All 103 mutations are caught. bootflow (48
     scenarios), player, loadertable, careffects, trackflow and every
     checker that links `race.c` pass, `sinit_check` has 23 calls, and
     Azahar passes. On the device the log reads `fred defaults: Player1
     (Rick), Player2 (Wayne), car 37 / 37`.

   **8l-2, the race start, is done** (HANDOFF.md, Session 31, continued:
   the race start (step 8l-2)). `docs/formats/race-start.md` has the
   write-up.
   - `fredrace.c` and `fredrace.h` are StartSkipFEGame (`0x00184bd8`),
     StartRace (`0x00184f68`), SetupCarsForRace (`0x00185690`),
     CalculateStartingPositions (`0x00185fe8`), GenerateRandomRideInfo
     (`0x00188218`), GetRandomSkin (`0x00188460`), the character and cop
     picks, AreThereAnyCarsOfType and OfColour, the unused-skin pick,
     DriverInfo's constructor, RideInfo::Init, SetRecordTimesToBeat and
     the four record indexes.
   - `raceparams.c` adds AddDriverInfo (`0x001eda40`),
     GetDriverInfoByDriverNumber (`0x001edb40`), the restore and the
     eliminate (`0x001edc50`, `0x001edbc8`), the model count
     (`0x001ede08`), and GetLocationNumber and GetLocationIndex.
     `configitems.c` has ForceAllAICarsToBeThisType (-1) and
     MaximumNumAICars (7).
   - The race events, the event trees, the demo replay and the reward
     cars are 17 seams. All are NULL on the device except the flow's two,
     the current state and `bgf_change_state`. `TheRaceEventFields` holds
     the four words of TheRaceEvent that the other game types touch.
   - `main.c` is the switch. Holding R at boot sets SkipFE: the pad is
     read once, after `bgf_init` and before InitFred. The boot then calls
     `fred_start_skip_fe_game(&Fred)` in place of LOADING_FRONTEND and
     logs the drivers. `tools/run_azahar_race.ps1` holds R and reads the
     log.
   - `fredrace_check` runs retail's code in RetailEmu: 8 scenarios, 2527
     ops, 50503 lines, 0 differ. Of 217 mutations, 216 are caught and 1
     is equivalent (`cp_pos1`). The full pass caught 200, and the other
     17 were rerun after `s_holes` went in.
   - On Azahar, R held at boot logs the race start (track 12, 8 laps, one
     driver: car 37 skin 1 on grid 1). The flow enters
     LOADING_TRACK_COMMON from NONE and runs its Begin, then stays on
     LOADING at 60 fps. By the code, Part1's car load waits on the NULL
     LoadTexturesFromFile; nothing logs that step. A boot without R walks
     the frontend as before (`run_azahar_test.ps1` passes).
   - Retail's BeginGameFlowUnloadingFrontEnd (`0x00168830`) is not
     ported. It waits for the frontend's way into a race, below, and the
     doc lists what it calls.

   **8l-3a, texture streaming, is done** (HANDOFF.md, Session 31,
   continued: texture streaming (step 8l-3a)).
   `docs/formats/texture-streaming.md` has the write-up.
   - `texturestream.c` and `texturestream.h` are TexturePack's streaming
     half, retail's `0x001ac608` to `0x001ad048` and the read's bridge
     (`0x001ad608`): LoadTextureTableFromFile, the ranges (Find,
     FindNotYetLoadedNeighbour, Add, Remove, Delete), Load and
     UnloadTextureFromFile, Load and UnloadTexturesFromFile,
     ServiceLoadingTextures and ReadCallback, UnloadAllTexturesFromFile and
     GetLoadedSize. Retail's oddities are kept (the doc lists them).
   - `main.c` makes LoadGlobalChunks' three packs (DynTextures,
     HudTextures, CarTextures) with its two waits, and sets CarLoader's two
     seams and trackflow's UnloadAllTexturesFromFile.
   - `texturestream_check` runs retail's code in RetailEmu: 9 scenarios,
     380 ops, 7353 lines, 0 differ. All 142 mutations are caught.
   - **The malloc heap is 48 MB now, not 28** (`heapcfg.c`). At
     LOADING_TRACK_SPECIFIC 22.8 MB is in use, and TRACKB12's 8.6 MB
     block failed: bMalloc aborts, and Azahar closed with it. The
     linear heap is 76 MB on Azahar with about 6 MB of it in use.
   - `main.c` sends stderr to `sdmc:/nfshp2_stderr.txt`, so an abort's
     reason (bMalloc's size and name) is on the card. Each state's Begin
     logs the heap's and the linear heap's use.
   - On Azahar, R held at boot now runs LOADING_TRACK_COMMON,
     LOADING_TRACK_SPECIFIC and enters RACING at 60 fps. The screen still
     shows LOADING, since nothing draws the race yet (8l-3b). A boot
     without R passes `run_azahar_test.ps1` as before.

   **8l-3b, the race, is done** (HANDOFF.md, Session 31, continued: the
   race (step 8l-3b)), in three commits:
   - **The race from MainLoop** (`3853ceb`). `main.c` builds the
     RaceCoordinator, and `raceFrame` is MainLoop's race half: the
     queued messages, RC_TICK, DetermineAllPlayersInputModes
     (`0x00181c28`), the world's step, UpdatePlayersNonGameState and the
     camera movers and shakers. `playerinput.c` is Player's
     DetermineInputMode (`0x00177608`), SetInputMode (`0x001776b0`) and
     the handlers. The racing mode is what gives the car's RealDriver the
     pad. `playerupdate.c` and `traffictele.c` came with it. The attach
     loops' mode now picks the alpha test: modes 1 and 3 always pass
     (`GeoPass.noAlphaTest`), so T_RD2DIRT's gloss map no longer cuts
     the road's edge.
   - **The cars drawn** (`4811ca7`). The solids that are not the track's
     draw through trackview, with GLOBALB's packs for the car textures.
     `tools/vu1dis.py` disassembles VU1 microcode.
   - **The cars lit.** `elight.c` is eLight.obj's database half:
     LoaderTable slot 5 (the light packs, flares and materials),
     QueryLightDatabase, elSetupLightContext and vAABBTree's leaf query.
     `geolit.v.pica` is the VU1 lighter and its environment pass.
     `eenvmap.c` is eEnvMap's six views, which draw into a 64-square cube
     map in VRAM. Since Session 31 the cube is folded into retail's
     256-square sphere map, which the environment pass reads.
     `docs/formats/light.md` has the write-up, with the two PICA facts
     that set the cube's orientation and the citro3d check that fails
     for every cube target.
   - Not ported, and named in `raceFrame` where they would run:
     ReplayManager's BeginFrame and EndFrame, ReplayScreen::Update,
     UpdateCameraCoordinators (`0x00199bd0`) and UpdatePortRumblers.
     LoadSoundRegionsInGame's seam is NULL, and the speech bank is not
     loaded.
   - On Azahar, R held at boot runs into RACING. The coordinator is in
     RCSTATE_RACE_IN_PROGRESS and the race in stage RACING, as retail's
     SkipFE puts them, so there is no countdown. With the throttle held
     the Opel drives off the grid at 58-60 fps, with the chase camera
     behind it. The track draws about 310 of 410 solids, 31,000
     triangles, and the car is lit with the sky in its reflections.
     `loadertable_check`: the demo image 178 ops and 1617 lines, the
     retail image 37375 ops and 49175 lines, 0 differ.

   **8l is done, and step 9 is reached: one car driving the track.** The
   next slices, in the order the user set (cars and racing before menus):
   - **8m, the HUD** (step 13, taken ahead of 10-12 since every later race
     test reads it): on the split decided on 2026-09-21, with the minimap,
     the lap and the objective on the bottom screen, and the speedometer
     and the pursuit on the top. HudTextures is loaded already. It goes in
     five slices:
     - **8m-1, the Flailer runtime, is done** (HANDOFF.md, Session 31,
       continued: the Flailer runtime (step 8m-1)).
       `docs/formats/flailer-runtime.md` has the write-up. `flailer.c`
       and `flailer.h` are retail's lookups (FindFlailerScreen,
       FindFlailerObject, ByGroup), the object, text and bitmap methods,
       and the Flailer* wrappers from `0x00143e70` to `0x00145690`. They
       write into the chunk bytes `bui.c` holds, so `uirender.c` draws
       what the game sets. `main.c` registers each bundle as a project
       (3 projects, 86 screens on Azahar) and binds the race's Flailer
       seams to it. `flailer_check`: 54,104 ops, 120,233 lines, 0 differ.
       110 mutations: 106 caught, 4 equivalent.
     - **8m-2, the HUD's features, is done** (HANDOFF.md, Session 31,
       continued: the HUD's features (step 8m-2)).
       `docs/formats/hud-features.md` has the write-up and a name for each
       bit. `playerhud.{c,h}` hold DetermineHudFeatures (`0x00178da0`),
       its gauge helper, SetHudFeatures (`0x001796b0`), SetTrackMapMode
       and UpdateHud's head. `main.c` binds the head to
       `gPlayerUpdateHudFn`. `hudfeatures_check`: 1298 ops, 10373 lines,
       0 differ; 170 mutations, 164 caught, 6 equivalent. On Azahar the
       one-player HUD screen (`f1f1f8e5`) comes up. It shows the bundle's
       placeholder texts (Lap 99/99, 00:00:00), the debug texts and the
       tracker's seven triangles, which RenderHud writes and places.
       SetHudFeatures' seams are not bound yet:
       SetRearViewMirrorCameraMover, InitializeFlailerTachometer,
       TrackMap's constructor and destructor, FillInRaceOverMessages,
       RaceFinishedSpeech, HudStartWrongWay and
       NISOverlayManager::SetVisible.
     - **8m-3, RenderHud, is done** (HANDOFF.md, Session 31, continued:
       RenderHud (step 8m-3)). `docs/formats/hud-render.md` has the
       write-up. `hudrender.{c,h}` hold the rest of UpdateHud
       (`0x0017ecf0`): the score's fade, the start bonus and the scoring's
       call. They also hold RenderHud (`0x0017f040`, 6812 bytes, no
       symbol), GetCurrentBestLapRecord, ConvertScoreString,
       DisplayDebugInfo, GetLetterForGear and TriggerTimerWarningSound.
       `racesplit.{c,h}` hold the RacingCar lap accessors and
       CalculateSplitTime. `bprintf.{c,h}` is bWare's bSPrintf and
       bVSPrintf (`0x00251398`, `0x00251440`), whose rules differ from the
       C library's: `%f` has 3 places, and halves round away from zero.
       FlailerPrintf now goes through it. `main.c` binds UpdateHud and
       `gHudTranslateFn`.
       - `hudrender_check`: 1278 ops, 7620 lines, 0 differ; 156
         mutations, 152 caught, 4 equivalent.
       - `bprintf_check`: 5879 ops, 11758 lines, 0 differ; 36 mutations,
         35 caught, 1 equivalent.
       - Azahar (`run_azahar_race.ps1 -HoldKeys 65`, shots in
         `out/azahar_8m3`): no crash. The top screen's HUD shows Lap 1/8,
         the record "--:--.--", the lap time counting, the speed and gear
         rising, and the leaderboard's "1 Player1". The debug strings and
         the trackers are hidden.
       - InitializeFlailerTachometer (`0x001434a0`) and
         RenderFlailerTachometer (`0x00143858`) moved to 8m-4.
       - SetHudFeatures' seams are still not bound:
         SetRearViewMirrorCameraMover, TrackMap's constructor and
         destructor, FillInRaceOverMessages, RaceFinishedSpeech,
         HudStartWrongWay and NISOverlayManager::SetVisible.
     - **8m-4:** the seams RenderHud and UpdateHud leave NULL, in three
       parts:
       - **8m-4a, the animations, is done** (HANDOFF.md, Session 31,
         continued: the HUD's animations (step 8m-4a)).
         `docs/formats/hud-anim.md` has the write-up. `hudanim.{c,h}`
         hold HudAnimator (`0x0023b0f8` to `0x0023c0fc`),
         ClearHudAnimations (`0x0017c7c8`), HudStartWrongWay
         (`0x0017c888`), HudStartGrowAnimation (`0x0017cb18`),
         HudStartSpeedAnimation (`0x0017cd30`), the two
         HudStartAnimation (`0x0017cfb8`, `0x0017d130`), HudDoAnimations
         (`0x0017e038`) and AddToTotalScore (`0x0017e350`). `main.c`
         binds their six seams. Nothing in retail calls HudStartBlink,
         StartBlink, the blink's DoAnimation, HudAnimator::SetVisibility
         or StartMusicTitleAnimation, so they stay out.
         - `hudanim_check`: 473 ops, 2829 lines, 0 differ; 292
           mutations, 290 caught, 2 equivalent.
         - Azahar (`out/azahar_8m4a`, `out/azahar_8m4a_2`): no crash.
           Passing 100 km/h grows a faded "100" behind the speedo for a
           second, as retail does. Speed 100%, 20 FPS, as in 8m-3.
         - SetHudFeatures' seams still not bound:
           SetRearViewMirrorCameraMover, TrackMap's constructor and
           destructor, FillInRaceOverMessages, RaceFinishedSpeech and
           NISOverlayManager::SetVisible.
       - **8m-4b, the scoring, is done** (HANDOFF.md, Session 31,
         continued: the race's bonus scores (step 8m-4b)).
         `docs/formats/hud-score.md` has the write-up. `hudscore.{c,h}`
         hold PlayScoreSound (`0x00175100`), StartScoreAnimation
         (`0x0017d370`), GetFinishBonus (`0x0017e2d0`), both StartScore
         with an eScoring (`0x0017e3b0`, `0x0017e558`) and
         UpdateScoring (`0x0017e820`). `main.c` binds
         `gUpdateScoringFn` and `gStartScoreFn`. StartScore()
         (`0x0017e6e8`) stays out: no code calls it and no data holds
         its address.
         - `hudscore_check`: 1608 ops, 6184 lines, 0 differ; 150
           mutations, all caught.
         - Azahar (`out/azahar_8m4b`): no crash in 40 seconds. No score
           fired (one driver, no lap finished). The frame rate was not
           read, since the chain was running.
         - The cop manager's CreatePullover, MonitorSpikeBelts,
           tPursuit::RoadBlockDefeated and the unnamed `0x00225a60`
           call StartScore(eScoring), and
           FrontendDatabase::FigureOutBonusPoints calls GetFinishBonus.
           They will call `hudscore.c` when they are ported.
       - **8m-4c, the rest, in three parts.** CONTINUE used to list a
         "MovePursuitMeter (`0x00182948`)". That was `retail_match`'s
         guess from a 0.12 ratio. The address is NISOverlayManager's
         Finish, which is already ported, and the meter moves inside
         UpdatePursuitMeter.
         - **8m-4c-1, the cop parts, is done** (HANDOFF.md, Session
           31, continued: the HUD's cop parts (step 8m-4c-1)).
           `docs/formats/hud-cop.md` has the write-up. `hudcop.{c,h}`
           hold UpdateRadarDetector (`0x0017be70`), DrawTracker
           (`0x0017c278`) and UpdatePursuitMeter (`0x0017c380`).
           `main.c` binds `gUpdateRadarDetectorFn`, `gDrawTrackerFn`
           and `gUpdatePursuitMeterFn`.
           - `hudcop_check`: 1187 ops, 4763 lines, 0 differ; 120
             mutations, 115 caught, 5 equivalent.
           - Azahar (`out/azahar_8m4c1`): no crash in 40 seconds. The
             race has no cops, so the radar and the meter are off, and
             no tracker is drawn. The frame rate was not read, since
             the chain was running.
           - tCopManager::GetRadarDetectorIntensity (`0x002274a8`) walks
             the cops, so it is a seam until step 12, and the radar
             reads 0 until then. It writes its flag as a word (`sw`),
             and only for a cop in range; retail reads the stack
             otherwise, and the port's flag starts at 0.
         - **8m-4c-2, the NIS overlay, is done** (HANDOFF.md, Session
           31, continued: the NIS overlay (step 8m-4c-2)).
           `docs/formats/hud-nis.md` has the write-up. `hudnis.{c,h}`
           hold Start (`0x00182488`), Update (`0x001825f0`),
           UpdateDateAndTime (`0x00182748`), SetVisible (`0x00182a48`),
           StartArrest (`0x001832f8`), StartTicket (`0x00183308`) and
           StartBusted (`0x00228f10`). `main.c` binds
           `gNisOverlayUpdateFn`, `gNisOverlaySetVisibleFn` and
           `gCdReadClockFn`, a reader of the 3DS's clock. The word at
           +24 is now `PointsDisplay`, the bounty's "+2000".
           - `hudnis_check`: 818 ops, 4359 lines, 0 differ; 119
             mutations, 118 caught, 1 equivalent.
           - `bspline_get_dval` now rounds as retail's GetdVal does,
             and `banim_check`'s model with it (`hud-nis.md`, "banim.c's
             GetdVal").
           - Azahar (`out/azahar_8m4c2`): no crash in 40 seconds. The
             race has no cops, so the overlay is never shown.
           - The Start* are called by the cops' NIS code (step 12).
         - **8m-4c-3, the tach's red band, is done** (HANDOFF.md,
           Session 31, continued: the tach's red band (step 8m-4c-3)).
           `docs/formats/hud-tach.md` has the write-up. `hudtach.{c,h}`
           hold InitializeFlailerTachometer (`0x001434a0`),
           RenderFlailerTachometer (`0x00143858`) and next_power_of_2
           (`0x0013ff60`). `main.c` binds
           `gInitializeFlailerTachometerFn`.
           - `uirender.c`'s `draw_tach` draws a TACH_GRADIENT bitmap
             as retail does: Render's polys, through the new
             `georender_draw_hud_quad`, and nothing without a list.
             `BUIObject.chunk` is the object on retail's layout.
           - The word at +108 holds a token for the list, not its
             address: 1 + a slot in `hudtach.c`'s table of four.
           - `hudtach_check`: 2287 ops, 7804 lines, 0 differ; 93
             mutations, 89 caught, 4 equivalent.
           - Azahar (`out/azahar_8m4c3b`): the chase view's band runs
             from about half past twelve to half past two, with the
             needle and the gear as before. 20 FPS. No crash in 30 seconds.
           - **Not checked:** the bumper view, where 38 of the 51
             cars that show the gradient cut with s = 2, and retail's
             strip draws a sliver to the constructor's (64, 64).
             Compare it with PCSX2.

       Ghidra headless decompiles by address with
       `tools/ghidra_scripts/DecompileByAddr.java` (env `DECOMPILE_ADDRS`,
       `DECOMPILE_OUT`, `RETAIL_SYMS`), launched from Git Bash by
       `tools/ghidra_headless.sh` with no cmd. It merges functions that
       have no symbol into their callers and gets EABI float arguments
       wrong, so read the disassembly from `tools/retaildis.py` beside it.
     - **8m-5, the two-screen split, is done** (HANDOFF.md, Session
       31, continued: the HUD on two screens (step 8m-5)), as the user
       placed it on 2026-10-03. `docs/formats/hud-split.md` has the
       write-up.
       - Top screen: the speedometer and tach, the race position moved
         from the top left to the bottom left, the radar and the
         pursuit meter.
       - Bottom screen: the lap block, the split times, the live split
         list, the score and Be The Cop's panel; the minimap since
         8m-6c.
       - `hudsplit.{c,h}` hold the table. `uirender.{c,h}` gain
         `UIPlacement`, `uirender_set_placements` and
         `uirender_draw_visible_bottom`, which draws the 640x480 frame
         at half size. RenderHud stays retail's.
       - No checker, since no retail function is behind it.
       - Azahar (`out/azahar_8m5`): the lap block and the split row on
         the bottom screen, the gauges alone on the top. 20 FPS.
       - **Not checked:** the race position at the bottom left, the
         score, the split times and Be The Cop's panel. A one-car race
         hides the position, and the races that show the others need
         the AI, the cops or a time trial.
     - **8m-6, the minimap (TrackMap)**, which the split puts on the
       bottom screen. Retail's TrackMap is 176 bytes (the demo's stabs
       give the fields) and fourteen functions, about 11.5 KB:
       | function | address | size |
       |---|---|---|
       | ctor (TrackInfo *, Car *, Player *) | `0x001babb8` | 528 |
       | dtor | `0x001badc8` | 28 |
       | Render | `0x001bade8` | 2188 |
       | GetAngle | `0x001bb678` | 300 |
       | DrawMap | `0x001bb7a8` | 1192 |
       | DrawMarker | `0x001bbc50` | 824 |
       | DrawOverOrUnderLay | `0x001bbf88` | 440 |
       | ClipPolygon | `0x001bc140` | 2236 |
       | EmitPoint | `0x001bca08` | 72 |
       | GetCarUVPosition | `0x001bca50` | 148 |
       | GetBoxOnMap | `0x001bcae8` | 364 |
       | MapToScreen | `0x001bcc58` | 1112 |
       | GetCameraDirection | `0x001bd0b0` | 324 |
       | InitTrackMapModeInfo | `0x001bd1f8` | 1428 |
       Player::RenderTrackMap (`0x00181c08`) calls Render, and
       eDisplayFrame calls that for each player after StuffDemoPolys.
       - **8m-6a is done** (HANDOFF.md, Session 31, continued: the
         minimap's table, constructor and turn (step 8m-6a)).
         `docs/formats/trackmap.md` has the write-up.
         - `trackmap.{c,h}` hold the record (176 bytes, a layout
           check on 32-bit builds), InitTrackMapModeInfo (the eleven
           68-byte modes at `0x003140b8` and the nine marker colours
           at `0x003143a8`), the constructor and destructor, GetAngle
           with EvalCubic (`0x001bdad0`), GetCameraDirection,
           GetCarUVPosition and GetBoxOnMap.
         - `main.c` binds gDeleteTrackMapFn to `trackmap_delete`, and
           gNewTrackMapFn to `newTrackMapLogged`, which logs the track
           and SufficientDataToRenderMe for each map made.
           SetTrackMapMode writes `CurrentMode`.
         - `trackmap_check`: 2399 ops, 6631 lines, 0 differ; 111
           mutations, 110 caught, 1 equivalent.
         - Azahar (`out/azahar_8m6a`): the log has `trackmap: track
           12, sufficient 1`, so all seven textures load in a race.
           20 FPS, no crash. Nothing draws the map until 8m-6c.
       - **8m-6b is done** (HANDOFF.md, Session 31, continued: the
         minimap's draw (step 8m-6b)). `trackmap.md` has the write-up.
         - `trackmap.c` adds DrawMap, MapToScreen (the tilt by AngleX,
           the projection at H and the fade), ClipPolygon with
           EmitPoint (Sutherland-Hodgman to the mode's box, then a fan
           of quads from the top point), DrawOverOrUnderLay, and the
           free GetSideOfLine (`0x001cb138`) and
           CalculateCentroidOfQuad (`0x001bda40`).
         - They hand Flailer polys, flags 0, to `gEPolyRenderFn`.
           Nothing calls them until Render, so nothing draws yet.
         - DrawMap's calls bear out GetBoxOnMap's argument names:
           forward and backward, then one side distance as both l and
           r.
         - `trackmap_check`: 5092 ops, 12519 lines, 0 differ.
           The mutation pass: 188, 187 caught, 1 equivalent.
         - Azahar (`out/azahar_8m6b`): 19 FPS, no crash, the HUD as
           before.
       - **8m-6c is done** (HANDOFF.md, Session 31, continued: the
         minimap's markers, Render and draw (step 8m-6c)). `trackmap.md`
         has the write-up.
         - `trackmap.c` adds IsPointInPoly (`0x001cb1f0`), DrawMarker
           (`0x001bbc50`) and Render (`0x001bade8`). Render draws the
           backing, the map, the start and finish lines, the AI's cars,
           the cops, the roadblocks, a ghost, the players and the
           frame, and switches to Be The Cop's targeting (mode 10).
         - `copmanager.c` adds GetNumActiveRoadBlocks (`0x00226968`)
           and GetActiveRoadBlock (`0x00226238`), with `tRoadBlock`.
         - `playerhud.c` adds Player::RenderTrackMap (`0x00181c08`),
           through `gTrackMapRenderFn`, which `main.c` binds to
           `trackmap_render`.
         - The draw: trackview's `render_epoly` queues each Flailer
           poly. `main.c` renders each player's map after the bottom
           screen's HUD, and `trackview_draw_flailer_polys` draws the
           queue there at the HUD's half size, by retail's Flailer Z
           table (`0x002c9e70`), with each texture's blend and alpha
           test. `georender_draw_hud_quad_w` takes a w per vertex, so
           the tilted map's UVs are perspective-correct.
           `GEO_QUAD_RING` is 192.
         - `trackmap_check`: 6012 ops, 15025 lines, 0 differ; 284
           mutations, 283 caught, 1 equivalent. `hudfeatures_check`
           runs RenderTrackMap: 1305 ops, 0 differ, 2 new mutations
           caught.
         - Azahar (`out/azahar_8m6c`): mode 0's tilted map on the
           bottom screen, with the road, the start line and the
           player's dot. 20 FPS, no crash. The log has `race: minimap
           6 polys (0 failed)` and each map texture.
         - **Not checked on screen:** the other modes, the AI's and the
           cops' dots, the roadblocks, the ghost and two players. The
           race SkipFE starts has none of them. The checker covers all
           of them.
   - **The cars' look is done** (HANDOFF.md, Session 31, continued: the
     cars' look), set by the user on 2026-10-03, with the PS2's frame of
     the Mustang on track 31 to match.
     - `trackview.c` renders `gEStripFns` and `gExStripFns`, so the
       shadows draw (`track-render.md`).
     - The cube folds into retail's sphere map through the sample table
       (`light.md`). `envsample_check`: 0 differ; 25 mutations, 24
       caught, 1 equivalent.
     - The depth buffer is the Z-buffer's. The W-buffer let the licence
       plate break up into the body.
     - The fog is a texture read by unit 1 and laid on by combiner stage
       5, since the PICA's fog unit reads the depth buffer
       (`weather-fog.md`).
     - `bMalloc` zeroes, as the PS2's pools do: CarRenderInfo's
       constructor reads its bodies' NumReplacementTextures before it
       sets them.
     - **Not done:** the light flares and AnimatedDriver::Render, the
       other two of Render's seams, have no renderer yet.
   - **13b, New 3DS mode in full and a steady 30 FPS** (task 28, set by
     the user on 2026-10-03). It comes right after the HUD, because every
     race test after it (the AI, the cops) needs the race in real time.
     - **The target** is the New 3DS in New 3DS mode.
     - **Only the optimizations the New 3DS needs to hold 30 go in.**
     - **Nothing is done for the Old 3DS.** Since 2026-10-05 the port
       is the New 3DS's alone, the user's call: an Old 3DS stops at boot
       with a message (6ac29d1, `new3ds-mode.md`, "An Old 3DS").

     It goes in four slices:
     - ~~**13b-1, the real clock and the pacing.**~~ Done in Session
       31 (`realtime.md`, "The frame on the 3DS"):
       - `prepare_real_timestep_from_ticker` is MainLoop's measure
         (`0x0012f43c`): the ticker's difference from s2, times 0.001,
         into PrepareRealTimestep, and s2 read again after. `BOOT_DT`
         is gone. The flow, the blurb, the UI counter and the viewers
         take the real step, and the jukebox's delayed start the
         world's.
       - `FrameCounter` is `C3D_FrameCounter(0)`, the top screen's
         blanks. sound::Update's 8 ms gate passes at any rate up to
         125, so it stays out.
       - The pacing: in a race, a frame with no blank since the last
         frame's sync waits one more before C3D_FrameBegin, so every
         frame is two blanks or more and none is 16.7 ms. The frontend
         and the movies stay at 60.
       - `race: clock` logs the wall, real and world seconds, the step,
         the blanks and the frames drawn, each world second.
       - `realtime_check`: 28 scenarios, 2016 ops, 8781 lines, 0
         differ; 103 mutations, 101 caught, 2 equivalent.
       - On Azahar (track 12, Speed 101%): 20 FPS at three blanks a
         frame, the step at NTSC's 0.05 s ceiling, and the world keeps
         pace with the wall (5.986 s in 6.017 s). Under 20 FPS the
         ceiling drops the excess, as on the PS2.
     - ~~**13b-2, a frame profiler.**~~ Done in Session 31
       (`frame-profiler.md`):
       - Retail's own, ported: MainLoopTiming's ten ticks
         (`0x002f0058`), CalculateFrameRate (`0x0012f090`) and the
         four Previous* it keeps (`mainloop.c`), and the two display
         times, WaitBufferSwapTime and VifTime in 16.16 ms, with
         GetWaitForBufferSwapTime and GetVifTime (`edisplay.c`).
         DisplayDebugInfo's "C: %dfps" and "G: %dfps" print the kept
         rates. `SHOW_FRAME_RATES` in `main.c` shows them, and is 0.
       - C3D_FrameBegin(C3D_FRAME_SYNCDRAW) is split, so the blank's
         wait and the GPU's are timed apart. The GPU's is
         WaitBufferSwapTime, and C3D_GetDrawingTime is VifTime.
       - `frameprof.c`, the port's own: a `frame:` line a second of a
         race, with each phase, the draw's nine stages (`main.c` and
         `trackview.c` stamp them), the waits, citro3d's two times and
         retail's two rates. At boot, a `console:` line: the model,
         the speedup, the memory type and grant, the heap, core 1.
       - `mainloop_check`: 11 scenarios, 4195 ops, 5097 lines, 0
         differ; 46 mutations, 46 caught.
       - On Azahar (track 12, Speed 100%): 18-20 FPS. The draw is 45
         of 50 ms: the cull 15-18, the envmap 10-13, the bottom screen
         5.3, the HUD 5, the cars 4.4. The world is 2-7 ms. Azahar's
         GPU takes almost no emulated time, so its numbers mean little
         there.
     - ~~**13b-3, New 3DS mode in full.**~~ Done in Session 31
       (`new3ds-mode.md`):
       - **The clock.** The CIA's service list lacked `ptm:sysm`, so
         `osSetSpeedupEnable(true)` failed silently and nothing restored
         the clock after the HOME menu. `app.rsf` adds it. A `clock:`
         line at boot times a 2,000,000-turn loop as launched, with the
         speedup off and back on; their ratio is the clock's.
       - **The memory.** `heapcfg.c` gives the linear heap what is
         left after the heap's 48 MB, up to 80 MB (`LINEAR_WANT`), and
         the malloc heap the rest, up to its 96 MB window. The CIA on a
         New 3DS gets 80 and 96; the .3dsx and an Old 3DS divide as
         before.
       - **The cores.** The jukebox worker sums its decode and read
         time (`jbstream_busy`): a `jukebox:` section in the `frame:`
         line, and a line of its own every five seconds out of a race.
         In the menus it decodes 6-7 ms a second, under 1% of core 0,
         so it stays there. Nothing else outside the draw is worth
         moving.
       - **The draw's stages renamed.** 13b-2's "cull" was
         `scenery_stuff_scenery`, the models' render, and the real cull
         (`scenery_do_culling` in `begin_frame`) was inside "envmap".
         `frameprof` now has cull, envmap, sky, models, scenery, cars,
         hud and bottom.
       - On Azahar (track 12): the clock line reads x1.00, since
         Azahar runs ConfigureNew3DSCPU as unimplemented (its log has
         all four calls). The .3dsx's grant is 124 MB, so the split is
         unchanged. Frames of 50-54 ms: models 12.6-17.8, envmap
         7.8-10, bottom 5.3, hud 4.7, cars 4.4, cull 2.2-2.9.
       - **On hardware, still to see:** the clock line's x3, the CIA's
         96 + 80 MB, and the `frame:` lines at 804 MHz.
     - **13b-4, only what the profile demands.**
       - Cut the largest cost, re-measure, and stop once the race holds
         30. A New 3DS's `frame:` lines decide the order; until the user
         runs one, Azahar's proportions are the guide.
       - ~~13b-4a to 13b-4d~~ done in Session 31 (`draw-cuts.md`):
         - **a**, georender's runs: in one eModel::Render loop the
           program, the frame's uniforms, the cull mode, the pass, the
           combiner and the texture go only when they change. A
           `models:` line after each `frame:` line counts the models,
           batches and words.
         - **b**, a mesh's vertex buffer as one register write
           (`GPUREG_ATTRIBBUFFER0_OFFSET`) after the run's first, and
           the model-view only when it changes.
         - **c**, `c3dwrap.c`: `C3D_UpdateUniforms` wrapped at link
           time (the Makefile's `C3DWRAP`), so a draw with no uniform
           changed skips citro3d's two 96-flag scans.
         - **d**, the Flailer layers drawn from lists built in one walk,
           as retail's LayerRenderInfoTable. The port unpacked every
           object 29 times a frame to compare its Z: 4.7 and 5.4 ms
           for the two screens, now 0.3 and 0.9.
       - ~~13b-4e~~ done in Session 31: the strips and the screen
         quads are not flushed one by one (`C3D_FrameEnd(0)` flushes
         the linear heap before the GPU runs the frame), and the sky,
         the scenery's list and the cars' chain are runs. A probe build
         found 27 strips at 86 µs each, nearly all the GSP request.
       - On Azahar after 13b-4e (`out/azahar_13b4g`): 27.5-30 FPS,
         frames of 33.8 ms on average, some of three blanks. The draw is
         23.3 ms: models 9.2, envmap 6.2, cull 2.7, cars 2.6, sky 0.8,
         scenery 0.5, bottom 0.5, hud 0.2. The world takes 1.4-4.5. The
         worst frame of a second is 34-67 ms.
       - **13b-4f, under way** ("Waiting on the device" at the top): the device GPU's
         cost per model. The indexed meshes are in (609b418). Then the
         fill and the fetch, the draws' own cost, the envmap, the cull,
         and the spikes that make a frame of three blanks.
         To time a stage's parts, a probe of `svcGetSystemTick` marks
         is cheap enough at tens of marks a frame; at a thousand it
         costs 5 ms.
       - Keep retail's look. A cut that changes it, such as a view
         updated every other frame or drawn smaller, goes to the user
         first.
       - Re-measure after the AI (step 11) and the cops (step 12).
         Repeat only if the race drops under 30.

     Azahar is set to New 3DS (`is_new_3ds=true`), but neither its GPU
     timing nor its CPU timing is the hardware's. Its FPS is a guide, and
     the hardware's is the measure. Take no reading while a build or a
     checker runs on the same machine: 8m-4a's first run read 57% and
     11 FPS that way, and 100% and 20 FPS idle.
   - The car's sounds (step 14): LoadSoundRegionsInGame and the engine.
   - **Music in a race: done in Session 43.** The flow stops the
     jukebox when the menus go (retail's UnlaunchFrontendMenus, now
     ported), and the race coordinator's TICK starts the racing list
     with `DelayedStart(6.0)` at GO. The stand-in ReplayManager keeps
     its beginning-of-time Timer for that; main.c sets the jukebox's
     seams (`docs/formats/jukebox.md`, "The race's music"). The rest of
     the replay is still unported.
   - The racer AI (step 11), and a SkipFE race with AI cars in it.

   The way in is retail's own debug path. With SkipFE (gp-23220) set,
   `main` (`0x0012f000`) calls StartSkipFEGame (`0x00184bd8`) in place of
   ChangeGameFlow(1). That fills TheRaceParameters from the SkipFE
   globals (gp-23256 to gp-23132, the demo's SkipFE* names shifted by
   568, or 572 past the new word at gp-23180) and jumps into StartRace
   (`0x00184f68`), which asks for state 4 straight from NONE. The
   shipped values are one car (type 37), no AI, no traffic and no cops,
   on track 12 (TrackSelectedInConfigFile is -1), for 8 laps. Retail sets
   SkipFE only from a joylog's config items (LoadConfigItems,
   `0x0012faf0`); `Config.bin` (LoadConfig, `0x0012eda0`) holds only the
   track. So the port needs its own switch. The frontend's way in comes
   later: car select's MaybeContinueToNextScreen (`0x00198b64`),
   SelectTrackScreen's StartRace (`0x001a0918`), and
   BeginGameFlowUnloadingFrontEnd (`0x00168830`), the state StartRace
   asks for from IN_FRONTEND. The port's `bgf_begin_unloading_frontend`
   neither chains nor unlaunches the menus.

   The RACING state has no callbacks: its row in the state table
   (`0x002faea0`, 16 bytes a row) is all zeroes. MainLoop
   (`0x0012f378`) runs the race: ServiceGameFlow, then the coordinator's
   ExecuteQueuedMessages (gp-22216), World's DoTimestep,
   UpdateCameraMovers, UpdateCameraShakers and eDisplayFrame.
   EndGameFlowLoadingTrackSpecific builds the coordinator, and
   BeginGameFlowUnloadingTrackSpecific deletes it.

   - **8l-1, InitFred and TheRaceParameters (done, above).**
     - TheRaceParameters as retail's struct, 788 bytes (InitWithDefaults
       clears that much). race.h's per-field globals become macros on
       it. It has its static init (`0x001ee590`, which sets the 14
       DriverInfos at `0x0031abb0`), InitWithDefaults (`0x001ed5c8`) and
       tGlobalDisplaySettings' defaults (`0x001ee0a0`).
     - CharacterInfo: Loader/UnloaderCharacterInfo (`0x001d9330` and
       `0x001d93b0`; chunks `0x34300`, 68 bytes a record, and `0x34301`,
       180 bytes) and the four getters (`0x001d9480` to `0x001d9590`).
     - FrontendDatabase's constructor (`0x001836a0`) and InitFred
       (`0x00183820`, which calls InitWithDefaults at `0x00183830`).
       InitializeEverything calls InitFred after InitializeSoundDriver.
       The port's Fred stays the byte image, at retail's offsets:
       FrontendPlayerInfo is 1744 bytes at `0x10738`; its parts are 64
       car statuses of 24 bytes, CharacterInfo at 1536, cPlayerSettings
       at 1604, RideInfoByGameMode[11] at 1652, and a word at 1740.
     - The rest of what InitWithDefaults reaches:
       - MakeChallengeCarsAvailable (`0x00183af8`). IsCarUnlocked
         (`0x0024b208`) is a seam there, because the reward system is
         not ported; NULL reads 0, which is what a fresh save answers.
       - FrontendPlayerInfo's SetCharacterInfo, SetCarAvailability (with
         `0x00187b08`, the skins), SetDefaultCarType, AssignCarOfType
         and `0x001879b8`.
       - The Data*::InitWithDefaults not yet ported, and HighScoreTable's
         InitStatsTables (`0x00186708`).
       - The two player names.
     - `main.c` calls InitFred where it calls `bsetup_fred_defaults`
       today.
   - **8l-2, the race start (done, above).** The SkipFE globals,
     StartSkipFEGame, StartRace, SetupCarsForRace and everything it
     calls, with RaceEvent's calls as seams and the port's switch for
     SkipFE. UseTheRaceEvent is true only for GameTypes 4, 8 and 9.
     ChooseHudTextures (`0x001ee388`) is an empty function in retail.
   - **8l-3a, texture streaming (done, above).** LoadGlobalChunks' packs
     and the streaming behind LoadTexturesFromFile (`0x001acc98`), which
     CarLoader and LoadHudTextures use.
   - **8l-3b, the race (done, above).**
     - `main.c` builds the coordinator (`gNewRaceCoordinatorFn`,
       `racecoordinator_new`; `gDeleteRaceCoordinatorFn`,
       `racecoordinator_destroy`) and runs MainLoop's race half. The
       track draws as trackview draws it, plus RenderCars.
     - Retail's MainLoop (`0x0012f378`), in order: ServiceGameFlow; with a
       coordinator (gp-22216), ExecuteQueuedMessages,
       CheckForDemoDiscTimeout and SendMessage(RC_TICK, 0); ServiceGameFlow
       again; UpdateStomper (empty); `0x0012f190` (the joylog's checksum,
       debug) unless gp-21424; DetermineAllPlayersInputModes
       (`0x00181c28`, Player::DetermineInputMode `0x00177608` for each);
       PrepareRealTimestep. Paused flow: PrepareWorldTimestep(0) and
       GenerateJoyEvents. Otherwise, with a World (gp-22120),
       UpdateWorldPaused and IsWorldPaused, then the ReplayManager's
       BeginFrame, World::GetTimestep, PrepareWorldTimestep,
       GenerateJoyEvents, World::DoTimestep and EndFrame. Then
       MenuSystemTick, UpdatePlayersNonGameState (`0x00181d88`,
       Player::UpdateNonGameState `0x00180e60` for each),
       ReplayScreen::Update, UpdateCameraCoordinators (`0x00199bd0`, the
       list at gp-19920), UpdateCameraMovers, sound::Update,
       UpdatePortRumblers, UpdateCameraShakers, World::DebugDisplay,
       eDisplayFrame, ServiceResourceLoading, AdvanceRealTime and
       AdvanceWorldTime.
     - The items below.
   - LoadSoundRegionsInGame (`0x001ae798`), or its NULL;
   - eDuplicateSolid and eDeleteAllDuplicatedSolids: **done**, Session
     52 (`esolid.c`, `docs/formats/loader-table.md`);
   - the RaceCoordinator built in `main.c` (`gNewRaceCoordinatorFn`) and
     its seams set where the port has the class;
   - the main loop's UpdateCameraMovers and UpdateCameraShakers, and the
     coordinator's TICK;
   - BeginCountdownCameras (`0x001768e0`) and UpdateNonGameState
     (`0x00180e60`), the likely first callers of
     ChangeCameraMover(CM_DRIVE); SetRearViewMirrorCameraMover
     (`0x001767a8`);
   - eDisplayFrame and RenderCars.

   - The InitForRace decode is in `docs/formats/race-coordinator.md` now.
   - InitPlayers, retail's DriverInfo, InitCars, AddRacingCar and
     CalculateRacerPositions are in `docs/formats/raceinit.md` now.
   - The 8d decode (Race::Init, RacingCar::Init, UpdateLapCounts,
     CheckBoundaryCrossing, FakeStartlineCrossing and
     Timer::Round) is in `docs/formats/race.md` now.
     - `0x001473f8` (328 bytes, no symbol) is FinishCar's (`0x00148740`
       calls it), so it goes with FinishCar, not 8d.
   - Then the flow into a race:
     - the main loop's UpdateCameraMovers and UpdateCameraShakers
     - BeginCountdownCameras (`0x001768e0`) and UpdateNonGameState
       (`0x00180e60`). These are the likely first callers of
       ChangeCameraMover(CM_DRIVE).
     - SetRearViewMirrorCameraMover (`0x001767a8`)
     - eDisplayFrame and RenderCars

   Step 7 as a whole: Player and the chase cameras. The core is
   DriveCameraMover (CM_DRIVE). Its constructor is `0x0015c258` (420
   bytes), ResetState `0x0015c470`, and Update `0x0015c880` (6056 bytes;
   the demo's is 5380). The demo's wall code is dead in retail, and
   Update calls two new helpers in its place (see 7b above). All of it is
   ported, and so is Player's ChangeCameraMover (`0x00176ae8`, 2372),
   which picks the mover for each view (7d). `main.c` sets
   `gCarInitRenderInfoFn` since 8b. The 3DS build gives
   Render's seams (the strips, the flares and the driver) their
   renderers, and the game flow calls RenderCars.

   Follow-ups found on the way:
   - Retail's GetRandomSkin (`0x00188460`) is `fredrace.c`'s
     `car_type_info_get_random_skin` since 8l-2. `cartypeinfo.c`'s
     `cartypeinfo_get_random_skin` is the demo's, and nothing in the port
     calls it now (`docs/formats/car-type-info.md`).
   - Retail's DriverInfo keeps TheDriverType at +8, and the port keeps it
     at +4. Since 8b the port's record is 24 bytes, as retail's is, but
     retail's rank byte 0 is the port's byte 20, and the next three bytes
     are one lower (`docs/formats/raceinit.md`). Everything reads them by
     name, so nothing is owed until a record is read in place.
   - Retail's Car::GetRoute and GetRoutePoint (`0x001332a8`,
     `0x001332d8`) take no argument. The controller slots they call take
     a bool, and it gets whatever the caller left in a1. The port's
     `car_get_route` passes none. AICarController's versions read it:
     with it set and the driving location clear, they run FindWhereIAm
     first. When task 26 ports AICarController, check what each caller
     of `car_get_route` leaves in a1.
   - The Car's CopLights is a word in retail and an `int8_t` in the port.
   - The hull shadow casts at most 64 points (`HULL_MAX_POINTS`), and
     retail has no bound. Check that bound against the cars' collision
     bodies when every car loads (step 18).
   - Retail's World constructor calls the shakers' reset (`0x00156480`,
     from `0x0014cf28`) after InitFernShakers, and has no InitParticles.
     `world_init` and `world_check` are still the demo's, so World's
     retail pass owes both.
   - MainLoop calls UpdateCameraShakers (from `0x0012f5e0`) after
     UpdatePortRumblers and before World::DebugDisplay. The port's main
     loop owes it in step 8, with UpdateCameraMovers.

   "The road to the full game", below, has everything after it.
2. **Task 27's first slice is closed: `Track.obj` and `TerrainType.obj`**,
   the track's collision surface. It is written up in
   `docs/formats/topology.md`.
   - `track.c`, `topology.h` and `track.h` carry the TopologyTree, the
     pooled TrackPolygons, and TopologyCoordinate: the SetInterestBBox,
     GetElevation and Constrain a car stands on. They also carry the
     position markers, the track info table and the road noise.
   - `terraintype.c` and the generated `terraintypetab.c` carry the 33
     terrains.
   - `track_check` runs the image in mipsemu as the oracle, over a
     synthetic world and over TRACKB12 itself: 14,753 ops, 11,231 lines,
     0 differ. Of 209 mutations, 206 are caught and 3 are equivalent,
     with 0 unexplained.
   - **The second slice is Car's first callers of it**, in `cartrack.c`:
     `FindFlatOnTrackPosition` (`0x00130c58`) and `PutFlatOnTrack`
     (`0x00130e90`), with the `SetInterestBBox(bVector3)` wrapper
     (`0x00134f28`) in `track.c`. `track_check` checks them, and they are
     written up in `car.md`. The slope's constant is 65536 / 6.28, not
     65536 / 2 pi, and that is kept. They are apart from `car.c` because
     `car.c` links into six checkers that have no topology.
   - **The third slice is Car's reset group**, in `carreset.c`:
     `ResetCore` (`0x001312c0`), `ResetToPosition`, `ResetToRoutePoint`
     and `DebugSetPosition`, with `ReplayManager`'s
     `RegisterInterestingEvent` and `InvalidateInterestingEvents` in
     `replay.c`. `carmode_check` runs them after the transitions, over a
     real looping track path loaded through `LoaderTrackPath`: 19 resets,
     32,797 lines, 0 differ. Its whole pass is 188 mutations, 185 caught
     and 3 equivalent, with 0 unexplained. Two words reach the state from
     the stack. The checker poisons the stack two ways and masks only
     those words' fourth lanes. The port tests `pReplayManager` for NULL
     where the image does not, because the replay is not ported yet.
     Written up in `car.md`.
   - **The fourth slice is `AverageAir` and `BeginMovement`**, in
     `cartrack.c`, checked by `track_check`: 16,149 ops, 11,790 lines,
     0 differ. Of the slice's 62 mutations, 60 are caught and 2 are
     equivalent. The first 209, rerun after its scenario went in, are
     still 206 caught and 3 equivalent. Every wheel goes through `WheelMatrix[0]`, as shipped.
   - **The fifth slice is the step**, in `carmove.c`: `Car::Move`
     (`0x00130200`), `ChangeGear`, `CalculateNewCatchupMultipliers` and
     `UpdatePosition`. `carmode_check` runs seventy steps after the
     resets: 35,405 lines, 0 differ. Of the slice's 79 mutations, 77 are
     caught and 2 are equivalent. Car is 55 of 80 methods. New files:
     - `timer.{c,h}`: Timer, moved out of `collisionbody.h`, and
       `Timer::SetTime`.
     - `player.c`: `NumPlayers` and `pPlayersByNumber`.
     - `difficultyinfo.{c,h}`: the table and chunk 0x34b00's loader. No
       LoaderTable registers the loader yet.
     `RacingCar` is whole in `race.h`.
   - **The sixth slice is Car's calls out**, in `carrace.c`:
     `GetDistanceAndSpeed`, `FixBlownTires`, `TriggerTireBlowOut`,
     `PleaseResetMeLater`, `GetDrivingLineSpeed` and `DeliverMeFromEvil`,
     with `DynamicCollisionBody::GetDistanceAndSpeed` in
     `carcollisionbody.c`. `carmode_check` runs them after the steps: 35,602
     lines, 0 differ, and all 43 of the slice's mutations are caught. Car
     is 61 of 80 methods. Five calls are seams in `car.h`:
     - the cop manager, the AI's controller and the DeliveryMover, which
       abort if reached unset (task 26);
     - `TriggerEffect` and `BaseCarSound::TriggerTireBlowOut`, which are
       skipped (tasks 27 and 29).
   - **The seventh slice is Car's terrain effects**, in `careffects.c`:
     `TriggerCarTerrainEffects` (`0x00131db8`, 1872 bytes), the skid
     smoke, tire spew, drive-over, bottom-out, splash, damage smoke, nitro
     and flat-tire effects. `carmode_check` runs 54 cases after the sixth
     slice's: 35,875 lines, 0 differ. Of its 107 mutations, 104 are caught
     and 3 are equivalent. Car is 62 of 80 methods, 10448 of 22876 bytes.
     `BaseCarSound::TriggerSplash` is a new seam, skipped when NULL (task
     29).
   - **One finding, fixed:** Car's `NumTimesSkidding` is `unsigned
     char[4]` (stab `ar1;0;3;11`), a count a wheel, and not one
     `int32_t`. The offset did not move, and every checker still gives 0
     differ.
   - Apart from that, the checks found no disagreement between the image
     and the port.
   - **The eighth slice is the clock object**, in `realtime.c`: the video
     mode, the real clock and the world clock (`0x001992a0` ..
     `0x001995d8`), and all eighteen globals at `0x00323cc8` ..
     `0x00323d0c` with the image's initial values. `WorldTimer`,
     `WorldTimeElapsed`, `WorldLoopCounter` and `RealTimeElapsed` moved
     there from `engine.c`, `drivetrain.c`, `world.c` and `cammover.c`.
     Harnesses that do not link `realtime.c` define the ones they read.
     `main.c` drives both clocks the way MainLoop does with no race.
     `realtime_check` is new: 20 scenarios, 1,044 ops, 3,470 lines, 0
     differ. Of its 86 mutations, 84 are caught and 2 are equivalent.
     NTSC's ceiling is `0x3d4cccce`, one ulp above 0.05f. Written up in
     `docs/formats/realtime.md`. `WorldTimeDoSnapshot` waits on
     ReplaySnapshot.
   - **The ninth slice is VClip**, in `vclip.{c,h}`: all of `VClip.obj`
     (`0x001c5d90` .. `0x001ca008`, 54 functions) but `DoSnapshot`, which
     waits on ReplaySnapshot. That is the polyhedron and its Voronoi
     planes, the feature codes and memory images, the transform, the
     three clips, the five checks and the walk. The Caffeine plots go
     through the new `espresso.{c,h}` seams, which abort if reached
     unset. `gEspSetObjectPositionFn` is defined there now, so
     `carmode_check` links `espresso.c`. `vclip_check` is new: 47
     scenarios, 11,890 ops, 22,389 lines, 0 differ, over 2,001 VClips
     and 938 single checks. Of its 281 mutations, 280 are caught and 1 is
     equivalent, with 0 unexplained. Written up in
     `docs/formats/vclip.md`.
   - **The tenth slice is `polyhedra.cpp`**, in `polyhedra.{c,h}`: all of
     `0x00205058` .. `0x00206440`, the polyhedra the collision bodies hand
     to VClip. That is the Rect and Cube boxes, `WaferPolyhedron::Init`
     for a track polygon, the loader and unloader for chunk `0x80034020`'s
     collision volumes, `FindPipelinePolyhedron`, `MoveCenterOfGravity`,
     the list's globals, and the four debug tests nothing calls.
     `polyhedra_check` is new: 55 scenarios, 15,907 ops, 64,560 lines, 0
     differ, over all 15,708 of TRACKB12's polygons and all 43 volumes on
     the disc. Of its 184 mutations, 172 are caught and 12 are equivalent,
     with 0 unexplained. No disagreement between the image and the port
     was found. Written up in `docs/formats/polyhedra.md`.
   - **The eleventh slice is the bodies that do not move**, the first part
     of `CollisionBody.obj`, in `collisionbody.{c,h}`. That is the
     NumberAllocator, `Init/CloseCollisionBody`, the stats, the base
     class with its list sorted on BBoxMax.x, StaticCollisionBody and its
     twenty-two methods, TrackPolygonCollisionBody, the witness's
     constructor, destructor and bookkeeping, the three tables, and the
     static initialiser and destructor. Car's two CarCollisionBody
     methods moved to `carcollisionbody.c`, because they need car.h and
     the movers. `collisionbody_check` is new: 21 scenarios, 743 ops,
     2,945 lines, 39 dumps, 0 differ, with track-polygon bodies on seven
     TRACKB12 polygons. Of its 184 mutations, 175 are caught and 9 are
     equivalent, with 0 unexplained. No disagreement between the image and
     the port was found. Written up in `docs/formats/collision-body.md`.
   - **The twelfth slice is DynamicCollisionBody**, the second part of
     `CollisionBody.obj`, in `collisionbody.{c,h}`: the constructor and
     destructor, the bounding volumes, UpdatePosition, BeginMove, the two
     interpolations and Backup, the RigidBody and PhysicsSystem
     pass-throughs, GetLocalCollisionBodies, MaybeCreateWitnesses,
     CreateTrackPolygonCollisionBodies, TrackPolygonCheck, the inline
     methods and its table. `collisionbody_check` runs it on bodies whose
     four pure slots are logging stubs: 39 scenarios, 1,039 ops, 8,733
     lines, 60 dumps, 0 differ. Of its 329 mutations, 318 are caught
     and 11 are equivalent, with 0 unexplained. No disagreement between
     the image and the port was found. Written up in `collision-body.md`.
   - **The thirteenth slice is CarCollisionBody**, the third part of
     `CollisionBody.obj`, in `carcollisionbody.c`. That is its
     constructor and destructor, the getters, Move, ApplyImpulse,
     AddDamage, AnimateCollisionReaction, AreCollisionsEnabled, the mass
     and inertia, IsBlinking, the constants, the inline accessors and
     its table. RaceCoordinator's pointer, state and IsReplayDemoMode
     are in `race.c`. The damage, the pursuit, the driver's animation,
     the rumble and the force feedback are five seams, and `main.c` sets
     none of them. `collisionbody_check` runs it on stand-in Cars: 55
     scenarios, 1,211 ops, 30,218 lines, 73 dumps, 0 differ. Of its 483
     mutations, 462 are caught and 21 are equivalent, with 0
     unexplained. No disagreement between the image and the port was
     found. The port's AI demo test overflowed an int32 at INT_MIN, and
     it subtracts unsigned now, as the image does. Written up in
     `collision-body.md`.
   - **The fourteenth and fifteenth slices are the contacts**, the rest
     of `CollisionBody.obj`, in `contact.c`: InitContact and CloseContact,
     RemoveContacts, the sort and `bList::AddSorted`, all of Contact
     (FindContactTime, Crowbar, Resolve, the contact point and normal,
     CollisionImpulse and the rest), and the witness's FindWaferNormal,
     GetCollision, BeginCollision and TestForContact. They were done
     together because TestForContact builds a Contact. `Collision`'s
     constructor and AddImpulse are the seams `gCollisionNewFn` and
     `gCollisionAddImpulseFn`, which abort if reached unset. The
     sixteenth slice fills them. `collisionbody_check` runs the contacts on E0..E3,
     bodies whose nineteen contact slots are logging stubs: 81 scenarios,
     1,572 ops, 35,426 lines, 89 dumps, 0 differ. Of its 646 mutations,
     622 are caught and 24 are equivalent, with 0 unexplained. No
     disagreement between the image and the port was found. Written up in
     `collision-body.md`.
   - **The sixteenth slice is `Collision.obj`**, in `collision.{c,h}`,
     with World's two GetDistanceToClosestPlayer overloads in `world.c`.
     That is the pool, the constructor and destructor, AddImpulse, Update,
     End, GetTerrainType and the four questions. DoSnapshot waits on
     ReplaySnapshot. The sound's CreateSample, ReleaseSample and
     PlayScrape and the particles' TriggerEffect are seams that a NULL
     skips; tasks 29 and 30 fill them. `main.c` points the witness's
     `gCollisionNewFn`, `gCollisionAddImpulseFn` and `gCollisionDestroyFn`
     at it. `collision_check` is new: the image's own InitCollision,
     bNewSlotPool, bOMalloc and bFree run against `bslotpool.c`, and two
     more collisions are built on 0xa5 memory: 15 scenarios, 3,587 ops,
     6,859 lines, 0 differ. Of its 131 mutations, 121 are caught and 10
     are equivalent, with 0 unexplained. No disagreement between the image
     and the port was found. The scrape's "faster body" test compares
     body 1's length with itself, so the particles always get body 1's
     velocity. Written up in `docs/formats/collision.md`.
   - **The seventeenth slice is World's timestep**, in `worldstep.c`, with
     bList::Sort in `blist.c`. That is the clock, the pause and the time
     scale, GetTimestep, the car table, the Randoms,
     GetDATToClosestPlayer, the checksums, DoTimestepMove,
     DoTimestepCollisions and DoTimestep. The step's twenty calls out are
     seams in `world.h`, skipped when NULL, apart from FinishMovement and
     PlaceNewCar, which abort. `smokeable.h` names Smokeable up to
     pSmokeableSpawner and has Break and DeleteFarAway as seams.
     `world_check` is new: the image's World.obj, bRandom, bList::Sort and
     the replay's clock helpers run against the port, with the Car
     methods, the collision system, the replay's data and the seams as
     logging stubs on both sides: 24 scenarios, 2,173 ops, 12,963 lines,
     0 differ. Of its 200 mutations, all 200 are caught. The first pass
     left seven, each a hole the script now covers (a NaN clock, the
     ticker either side of exactly 0.3 s, a replay byte with high bits,
     a loop count that is a multiple of 64 but not of 128, and cars at
     exactly 100 and 150 from a player). No disagreement between the
     image and the port was found. Written up in `docs/formats/world.md`.
   - **The eighteenth slice is World's constructor and destructor**, in
     `worldinit.c`, with the record's tail in `world.h`: the constructor,
     the destructor, DebugDisplay, the four recorders and
     UpdateAIDebugRendering. Only DoSnapshot and DoPointerSnapshot of
     World.obj are left, for ReplaySnapshot. OBB's methods are `obb.c`,
     with the front of WorldObject in `worldobject.h`. The bPNode pool is
     `bplist.c`, and GetVectorOnTrack is in `track.c`. The constructor's
     eleven Init calls and the destructor's eleven Close calls are seams,
     skipped when NULL. The teleporter's constructor and destructor and
     Car's destructor are seams that abort when they are needed and
     unset. `world_check` runs it all against the image: 32 scenarios,
     2,742 ops, 15,110 lines, 0 differ. Of its 328 mutations, all 328
     are caught. The first pass left one, `render mul order`, which the
     new box covers (see below).
     `bslotpool_check` has a bPList scenario (18 scenarios, 47/47
     mutations caught), and `bslotpool_mutate.py` can now mutate a second
     file. `track_check` puts 31 points on the ground with
     GetVectorOnTrack (273 caught, 5 equivalent). The port departs from
     the listing in one place: for a driver number that no car has,
     UpdateAIDebugRendering reads the word at 44 in low memory. The port
     passes NULL; the one renderer the game runs never reads its target.
     Written up in `docs/formats/world.md`.
   - **The nineteenth slice is `Car::FinishMovement`** (`0x00130480`, 2008
     bytes), in `carfinish.c`: the accelerations, the odometer, the track
     path's update, the lost-car and search tests, the headlights, the
     zone clear, the air, the jump cam and its zone, and the replay's
     CarInAir, CloseCars, CarSlidingSideways, CarCollision and
     SmokeableCollision. Car is 63 of 80 methods, 12456 of 22876 bytes.
     `main.c` sets `gCarFinishMovementFn`, so World's step no longer
     aborts there. The Player's ClearZone, RequestZone, IsJumpCamAvailable
     and CleanUpJumpCam are seams that abort when unset (task 26), and
     `player.h` names `nZoneCurrent`, `bWrongWay` and `EyeVerts`.
     `g_DisableAutoReplay` is in `car.c`, and
     TrackPathCoordinate::ResetPosition in `trackpath.c`. `carmode_check`
     runs 105 cases after the terrain effects, with a player, a five-car
     world table, a Collision and the topology's answers scripted one per
     question: 36,396 lines, 0 differ, no line of it masked. Of its 88
     mutations, 82 are caught and 6 are equivalent, with 0 unexplained.
     No disagreement between the image and the port was found. Written
     up in `car.md`.
   - **The twentieth slice is `Scenery.obj`'s data half**, in `scenery.c`:
     LoaderScenery and UnloaderScenery, the three finds, IsPointInPoly,
     FindVisibleZone, the zone's two index helpers, Init- and
     CloseVisibleZones, the debug tables, CreateFacadeMatrix,
     FlipObjectsOnBackwardsTrack and the statics, which are
     `__CTOR_LIST__[21]` in `sinit_run`. eModel::Init and its deleting
     destructor are the seams `gEModelInitFn` and `gEModelDestroyFn`,
     which abort when unset; `eModelSlotPool` is NULL until the renderer
     makes it. `scenery_check` loads all 122 of TRACKB12's sections and
     its 23 zones, forward and backwards, with made-up sections beside
     them: 17 scenarios, 3,450 ops, 16,724 lines, 0 differ. Of its 79
     mutations, 77 are caught and 2 are equivalent. One port bug was
     found by the pass and fixed: indexed through the array, GCC took
     FindIndexTo's 64 as a bound on the count. No disagreement between
     the image and the port was found. Written up in
     `docs/formats/scenery.md`.
   - **The twenty-first slice is the scenery cull**, in `scenerycull.c`,
     `eframe.c` and `eview.c`: ClassifyAABB (`0x0010b940`, VU0's
     `vclipw`, which `mipsemu` now models with the clip register),
     IsBoundingBoxVisible, IsVisible, the tree and brute-force culls,
     DrawAScenery, WhatSectionsShouldWeDraw, CullView, BatchCullViews,
     DoCulling, StuffScenery, SetupSceneryCullInfo, eDisplayFrame's loop
     over the views, Ecstasy.obj's frame malloc and the table of ten
     eViews: 17 functions, 4,608 bytes. eModel::Render is the seam
     `gEModelRenderFn`, which aborts when unset. `scenerycull_check` runs
     the image over made-up sections and over all of TRACKB12's, from
     every zone and twelve random points: 9 scenarios, 7,273 ops, 46,687
     lines, 0 differ. Of its 148 mutations, 147 are caught and 1 is
     equivalent. Six reassociations survived the first pass and each now
     has a case, found by search, where the other order rounds across a
     plane, the 2 or a far clip. No disagreement between the image and
     the port was found. Written up in `docs/formats/scenerycull.md`.
   - **The twenty-second slice is `eView.obj`**, in `eview.c` and
     `eviewmatrix.c`. It covers:
     - `CalculateViewMatricies` (`0x00106700`), `CreateViewMatricies`
       (`0x0010d268`), `CalculateH` and `SetupMatrixPacks`;
     - the two local-to-clip products and `BiasMatrixForZSorting`;
     - the three `GetPixelSize`s, `GetScreenPosition`, `GetScreenWidth`
       and `GetScreenHeight`, and `SetupWorldLightContext`;
     - the view names and lookups, the camera movers' attach and detach,
       `eUpdateViewMode` and `MaybeChangeViewMode`;
     - the static constructor's four cameras and ten views, which are
       `__CTOR_LIST__[2]` in `sinit_run`.

     `eWaitUntilRenderingDone` and `elSetupLightContext` are seams that do
     nothing when NULL. `eview_check` runs the image against the port: 12
     scenarios, 2,103 ops, 15,454 lines, 0 differ. Of its 153 mutations,
     152 are caught and 1 is equivalent. The check found one bug outside
     the slice, in `camera.c`. The eye is a subtraction from VU0's (0, 0,
     0, 1), and the port negated it instead, so the default eye was -0 in
     x and y. That is fixed, and `camera_check` has a mutation for it (46
     caught, 7 equivalent). Written up in `docs/formats/eview.md`.
   - **The twenty-third slice is the track on the screen**, roadmap step
     1, in `trackview.c`, `emodel.c` and `main.c`'s `MODE_TRACK` (SELECT
     past the geometry viewer). It:
     - reads TRACKB12.BUN whole and links its 1,135 eSolids onto
       `SolidList` in place;
     - hands the 122 sections and 23 zones to `scenery_loader`, with
       eModel::Init and its destructor in `emodel.c` (2,494 models, 7
       without a solid);
     - bakes the 915 named solids (125,498 triangles, 342 textures, none
       missing) and runs eDisplayFrame's order on view 1 every frame;
     - draws what the ported cull picks through `georender`, in the
       engine's order: opaque order-0 textures at once, everything else
       after StuffScenery, by the attach loops' RenderingOrder, first use
       and alpha-sort rules, with the GS's blend equations and TEST_1
       (depth GEQUAL, alpha GREATER 0x30).

     A free camera flies it, and the D-pad steps along 24 stops of route
     1. `tools/run_azahar_track.ps1` shoots stops 1 to 7 in Azahar, and
     all seven show the road, the trees, the signs and the shadows.
     Written up in `docs/formats/track-render.md`, which lists where the
     port departs: the sort is per batch, not per strip; there is no
     `pStackedActiveTexture`, no shadow matrix pack, no light materials;
     and the sky domes draw in the main view until step 3 (the
     twenty-sixth slice moved them to StuffSky).

   - **The twenty-fourth slice is the LoaderTable**, the first half of
     roadmap step 2, in `bchunkload.c`, `esolid.c` and `emodel.c`. It
     covers:
     - ResourceFile's load half (`0x0018f6c8` .. `0x0018f918`):
       LoaderNull, both walks, LoadChunks and UnloadChunks, PostLoadFixup
       and HotChunksPostLoadFixup;
     - the two tables of 31 slots. Slot 0 is LoaderNull, and the seven
       slots whose object is ported call it. Every other slot is its guard
       alone, handing what it takes to `gUnportedLoaderFn`;
     - LoaderSolidList and its unloader, FixStripEntryTable,
       FixTextureTable, FixLightMaterialTable and eFixUpTables, with the
       eVertexAnimator pool;
     - the rest of eModel.obj's list half: UnInit, ReconnectSolid,
       ReconnectTextureTable, ApplyReplacementTextureTable,
       ReconnectAllModels and the deleting destructor.

     `trackview.c` loads TRACKB12 through `load_chunks` and
     `post_load_fixup` now, and unloads it through `unload_chunks`. It no
     longer links the solids itself. Seen on Azahar: 1,135 solids linked
     by LoaderSolidList, 2,494 models, 342 textures, 0 missing, and the
     track draws as before. `loadertable_check` runs the image against
     the port: 27,856 ops, 41,730 lines, 0 differ, over every solid list
     on the disc and all 497 of TRACKB12's top-level chunks. Of its 102
     mutations, 100 are caught and 2 are equivalent. The first pass left
     five, and all five were holes in the script: the ported unloaders
     were never called on a bare chunk, and there was no case for a tree
     whose pad changes its count of nodes, for labelled frames apart from
     their animation, or for UnInit on a model with a solid. Written up in
     `docs/formats/loader-table.md`.

   - **The twenty-fifth slice closes step 2.** It has three parts.
     - **TexturePack.obj** is ported in `texturepack.c`. Its loader and
       unloader are slot 2. Its in-memory half has the constructor and
       destructor, AttachTextureTable, Assign and UnAssignTextureData, the
       three lookups, GetTextureInfo and GetNthTextureInfo, the flipbook
       pack, InitAnims, UpdateTextureAnimations and GetTextureAnim.
     - **The track flow** is ported in `trackflow.c`:
       EndGameFlowLoadingTrackSpecific (`0x001645e8`) and
       BeginGameFlowUnloadingTrackSpecific (`0x001646e0`). The End clears
       `eDisableFixUpTables` and runs the one eFixUpTables. Then it calls
       the collision pools, InitTree, InitPhysics, the visible zones, the
       paths and the routes. Every callee the port lacks is a seam.
     - **The viewer** loads in the game's order: the shared packs;
       `eDisableFixUpTables` set; TRACKB12, TEX12TRACK and TEX12LOCATION;
       then the End. It unloads through the Begin, whose
       FindResourceFile loop hands the three files back newest first.

     Seen on Azahar:
     - The track draws textured by the game's own GetTextureInfo, and 49
       names get the default, as the disc predicts.
     - All 46 flipbook frames upload, and none fails.
     - `InGameFlag` is 1 after the load and 0 after the free, and the
       free leaves no solids, models or packs.

     `texturepack_check`: 5,452 ops, 11,201 lines, 0 differ; 95 of 97
     mutations caught, 2 equivalent. `trackflow_check`: 16 scenarios, 694
     lines, 0 differ; 73 of 74 caught, 1 port-only. Written up in
     `docs/formats/texture-pack.md` and `docs/formats/track-flow.md`.

   - **The twenty-sixth slice starts step 3** with the sky dome and the
     sun's data.
     - **Sky.obj** is ported whole in `sky.c`: SkyInitModel, SkyLoader,
       SkyUnloader, StuffSky, and the static constructor and destructor.
       SkyLoader takes SKYDOME and SKYDOME_ENVMAP out of the scenery.
       Each placement becomes a matrix, and each kind's LOD models are
       UnInit'ed, so the cull no longer draws the dome.
     - **Sun.obj's data half** is ported in `sun.c`: LoaderSun and
       UnloaderSun, which is slot 14, plus SunTrackLoader and
       SunTrackUnloader, which give the five SUN textures order 7.
     - **The End and the Begin** call all four directly now, not through
       seams. Only rain_Load and rain_Unload are still seams.
     - **The viewer** draws the dome the way eDisplayFrame does: Z writes
       off, StuffSky, the deferred list, then Z writes back on, all
       before the scenery. `georender_set_zwrite` is eSetZWriteState.

     Seen on Azahar:
     - SKYDOME is drawn by StuffSky, and the envmap views get their own
       dome.
     - The sun chunk is version 2, at (-16384, 800, 6000).
     - All five sun textures are found, at order 7.
     - The track drew 437 of 438 objects, 1 of them the sky, and the
       mountains and clouds show behind the canyon.
     - The free leaves no solids, models or packs.

     `sky_check`: 45 scenarios, 1,159 lines, 0 differ; 76 of 78
     mutations caught, 2 equivalent. `trackflow_check` is now 702 lines,
     and `loadertable_check` treats slot 14 as ported; 0 differ in each.
     Written up in `docs/formats/sky-sun.md`.

     Three fixes followed the slice:
     - `sinit_run` now calls `sky_static_init` ([6], `0x0011cfb8`).
     - `loadertable_test.c` defines SunPosition, which sun.c writes and
       eviewmatrix.c owns.
     - `loadertable_check`'s dump now shows SunInfo and SunPosition. A new
       scenario takes TRACKB12's sun chunk through both tables at each
       misalignment, then at version 1. That catches `unloader-14-loads`,
       which the first commit left open. The checker is now 27,897 ops
       and 41,988 lines, 0 differ; of its 102 mutations, 100 are caught
       and 2 are equivalent.

   - **The twenty-seventh slice is the sun's draw.**
     - **StuffSun and StuffSunGlare** are ported in `sundraw.c`. That
       includes the glare's globals, PhaseTimes and the 15 SunZBuffers.
     - **ePoly** and its constructor are in `epoly.c`, and ePoly::Render
       is a seam.
     - **The 3DS side** is in `trackview.c` and `georender.c`.
       - `render_epoly` maps the quad's pixels onto the top screen. It
         draws with the poly's blend, the main target's alpha test and no
         depth test. No depth test is needed: the poly's z of 65535 passes
         GEQUAL against any 16-bit Z.
       - `transfer_zbuffer_rect` queues the rect.
       - main() calls `trackview_read_depth` after the next
         C3D_FrameBegin, before the clear. It reads the D24S8 buffer and
         turns each depth into the GS's Z, 16 + (0x0ff000 - 16) t, with
         t the same on both.
     - **A probe** logs 15 screen points' colour and depth words at each
       stop. Scored against seven stops' screenshots, the tiled mapping
       comes out at 531, and its flips at 3,643 to 5,931.

     Seen on Azahar:
     - At every stop the sun is just above the frame. Its rect is off the
       target, so its layers draw at alpha 0.
     - The new `track-sun` shot goes back to stop 1 and looks up. The
       whole rect is sky, and the layers draw at 128, 64, 89 and 40.
     - The halo has a hard edge, and the fourth layer never shows. The
       PS2's alpha test does both of these too, because the textures'
       alpha stops at 0x7f.

     `sun_check`: 91 scenarios, 2,680 lines, 0 differ; of its 115
     mutations, 114 are caught and 1 is equivalent. Written up in
     `docs/formats/sun-draw.md`.

   - **The twenty-eighth slice is the weather and the fog.**
     - **WeatherMan.obj** is ported whole in `weatherman.c`: the four
       lists and the inactive one, LoaderWeatherMan and its unloader in
       slot 29, the add, remove and state calls, and WeatherManQuery.
       With it is eView::GetWeatherQuery and its cache, one query per
       view per frame by `eFrameCounter`, which the end of the track's
       draw now counts, as eDisplayFrame's does.
     - **The fog half of EcstasyE.obj** is in `efog.c`: FogModeInfos,
       fpow, RemapLinearIntoClut8, GetFogPalette, CreateFogPalette with
       its four modes, and eAttachDepthIntoAlpha and eAttachFog. The fog
       sprite that eAttachFog builds is a seam, `gEFogAttachFn`.
     - **The 3DS side** is in `trackview.c` and `georender.c`. The PS2
       lays the fog over the finished frame, reading its Z back into the
       alpha. The PICA cannot, so its fog does the same per fragment.
       - The depth map becomes a W-buffer, so the fog's depth is the
         view's own. Each of the lookup's 128 entries takes the GS's Z
         for that depth, the alpha the image's depth palettes give that
         Z, and the fraction ALPHA_1 leaves of the frame for that alpha.
       - The fog's colour is the palette's one colour. A palette with
         more, or mode 1's with any colour but black, is left off and
         counted.
       - The sky and the sun get a lookup at Z = 0, and the additive
         and subtractive blends a fog colour of 0.

     Seen on Azahar:
     - TRACKB12 has 20 fog regions and no others. DrawFog is 1, both
       modes are 0, and FogPower is 4.6.
     - At the start the query gives FOG<MAIN>'s 0.1 of 0xa0a082 from
       246. That leaves the whole frame nearer than 1000, 97.7% of it at
       2000, and 90.6% at 4000 and in the sky.
     - eFrameCounter counts, and the sun's depth readback still works.

     `weather_check`: 75 scenarios, 4,368 lines, 0 differ; of its 89
     mutations, 85 are caught and 4 are equivalent. `loadertable_check`
     treats slot 29 as ported: 42,243 lines, 0 differ, and 103 of its
     105 mutations caught. Written up in `docs/formats/weather-fog.md`.

   - **The twenty-ninth slice is the rain, and it closes step 3.** The
     shipped image draws no rain, snow or storm.
     - rain_Load, rain_Unload, rain_TimeStep and rain_Render are each
       `jr ra ; nop`. They are ported as such in `rain.c`, and the End,
       the Begin and World::DoTimestep call them directly. The seams
       `gRainLoadFn`, `gRainUnloadFn` and `gRainTimeStepFn` are gone.
     - Nothing reaches the rest of Rain.obj: RainSystem's constructor,
       Update, Render, SplashLoop and TweakSplashes, and the RainSplashes
       under them.
     - The storm in EcstasyE.obj is dead too. UpdateStorm and
       RenderAllStorms have no caller, SetStormType is empty, and
       GetStormType returns 0.
     - SoundScape::UpdateWeather has no caller either. So
       CreateFogPalette is the weather query's one live reader, and the
       rain, snow and wind regions load and do nothing.

     `rain_check` scans every loaded section for references to all of
     it. It finds 30, and each is in its expected table. It also runs the
     four entry points in mipsemu against `rain.c`: 31 calls, 0 differ,
     5 of 5 mutations caught. `trackflow_check` and `world_check` stub
     the rain calls by name now, and gain mutations that drop and move
     them. Written up in `docs/formats/rain.md`.

     - Nothing sets bStartGlare until the munitions are ported.
       Munition::ExplodeWarhead (`0x001b4798`) sets it for a
       MunitionsType of 1.

   - **Then the retail disc came, and task 36 opened (item 1).** The
     car on the track moves to step 6 of "The road to the full game".

   "The road to the full game", below, has the steps.

   Things to know before the next slice:
   - **A bundle with texture packs must sit at 128 in memory.**
     LoaderTexturePack rounds the blob's address up to 128, and the
     packer sized each blob's filler for the file's own address. A buffer
     from plain malloc shifts every texture. Read bundles with
     `memalign(128, ...)`, as `uirender.c` and `trackview.c` do.
   - **Nothing fixes the tables up between the Begin and the End of
     loading.** `eDisableFixUpTables` is 1 from
     BeginGameFlowLoadingTrackSpecific until the End clears it. A solid
     loaded in between has its texture table as the loader left it
     until then. The Begin of unloading sets the flag again, and it
     stays set after the viewer's free.
   - **`eMathInit` must run before anything draws.** It is the only
     thing that fills `eMathIdentityMatrix`, which StuffScenery hands to
     every object drawn in place: the road and the terrain. Left zero,
     they fold to a point. `main.c` calls it where InitializeEverything
     does, just before eInitEngine's share.
   - **Azahar refuses a .3dsx with a bad relocation and says only "Error
     1".** `tools/check_3dsx.py` runs after every build now and names the
     word. The first one was gcc folding `table + negative constant` in
     `bFixATan1` for INT32_MIN; `bmath.c` compares unsigned there now.
   - **The GPU command buffer is 4x citro3d's default**, and it has to
     be: stop 2 uses 139,068 of its 262,144 words. `GPUCMD_Add` drops
     what does not fit silently, so `trackview.c` stops 8,192 words short
     and counts the draws it skipped.
   - **A subtraction from zero is not a negation.** VU0 makes a negative
     with `vsub` from vf00, and 0 - (+0) is +0 where -(+0) is -0. The
     camera's eye was wrong this way from the camera's port until
     `eview_check` printed its bits. Where the listing subtracts from vf00, the port
     writes `0.0f - x`.
   - **`sinit.c`'s bracketed index is 1-based past the count word.** The
     list's first function is [1], and `sinit_check` reads every index, so
     an index that is off by one fails there.
   - **The track fits the Old 3DS's linear heap.** `heapcfg.c` gives it
     about 68 MB. The scenery's 932 solids are 122,937 triangles, which is
     10.3 MB as `georender`'s triangle lists. Their 330 textures are
     27.3 MB as RGBA8, and 11 more are in no pack. That was before the
     race grew: on 2026-10-05 an Old 3DS's .3dsx ran its heap out at the
     track, and the port now stops on an Old 3DS (step 19).
   - **The track's surface is loaded on hardware, but not built.** The
     track viewer's `load_chunks` reaches `track_loader_geometry` and
     TopologyTree::Loader now, with the collision volumes and the track
     path. The `InitTree` call in `EndGameFlowLoadingTrackSpecific`
     (`0x0016461c`) is still not wired, and it is the one thing left
     before the surface is live. Car.obj's `SetInterestBBox(bVector3)`
     wrapper (`0x00134f28`) is ported.
   - **A slot is taken by its guard even when its object is not ported.**
     `bchunkload.c`'s unported slots claim the image's types and hand the
     chunk to `gUnportedLoaderFn`, which is NULL. So TRACKB12's lights,
     effects, event manager, cameras, sun, cops, soundscape, helicopter,
     smokeables and weather (14 chunks, 10 slots) load as nothing, with no
     `bBreak`. Porting one means calling its loader from the guard, as
     the seven ported slots do.
   - **LoaderSolidList fixes up the file in place.** It moves each strip's
     `Data` by the packet's address and writes the texture and
     light-material pointers into the bundle. The unloader does not move
     the strips back, so a second load of the same buffer moves them
     twice, unloaded in between or not. The game reads a bundle afresh
     for each load, and the port has to as well. The viewer never reads
     the strips' `Data`, and `geo_open` parses the bundle before
     `load_chunks` runs.
   - **`chunk_loader_table.py` misses five of LoaderTrackGeometry's seven
     types**: `0x34146`, and `0x34130`..`0x34133`, which go through the
     tail call into TopologyTree::Loader. `bchunk.md` explains the two
     causes. Trust `topology.md`'s list over the tool's.
   - **`NumUpsideDownTrackPolygons` holds (placed) minus (vertical)**, which
     is the total for an all-floor build. Nothing in Track.obj reads it back.
     Check any reader outside it.
   - **`WorldTimer` is set per step case** in `carmode_check` (`mv(now=)`,
     W by default). The blink tail's sentinels only show with a clock a
     quarter second past them.
   - **A mutation pattern replaces its first match.** If the pattern is
     also in a comment above the code, the mutant edits the comment and
     survives. Two of the step's did that. Spell a pattern so it only
     matches code.
   - **The rest of Car** is 17 methods, and every one reaches a class
     that is not ported: the constructor and destructor, `TriggerEvents`
     (the ferns, the event manager, `Player::TriggerVisibleDrivingLine`),
     the AnimatedDriver pair, the damage, render and force-feedback
     groups, and `DoSnapshot`. `car.md` lists them.
   - **Two clocks are still apart from the clock object.** `gameflow.c`
     keeps its own in the flow's record (`bgf_advance_time`), and
     `main.c`'s `uiTimer` drives the scrolling textures. Both tick at the
     same 1/60. Fold them in when the flow's MainLoop is.
   - **A walk hides its steps.** VClip settles on the same closest pair
     whichever way one step goes, so 21 mutants of the checks and clips
     survived every whole-walk scenario. `OP_CHECK` runs one check on its
     own, set up the way VClip sets it up, and the single-step scenarios
     kill all 21. Build each survivor's harness once and run candidate
     scripts through it without the emulator; that finds a killing
     family in seconds. The model then confirms it.
   - **`hostbuild` failed a link with every object cached** under msys2
     ("compile failed (msys2 bash)" with no diagnostic). It treated
     "nothing to compile" as failure. Fixed in `_build_cached`.
   - **mipsemu zero-extends a call's arguments.** Pass anything the image
     reads as signed through `s32` first. Find of a hash with the top bit
     set missed in the model until `polyhedra_check` did.
   - **A disc container only loads at its own 16-byte residue.** The
     pipeline laid each array's pad out for where the container lies, and
     the loader just rounds up. A copy moved anywhere else has to be
     repacked first; `polyhedra_check` has the code.
   - **Run a long `--mutate` with `python -u`** when its output goes to a
     file, or nothing shows until it ends. A background shell's timeout
     did not stop one either. Keep a copy of any untracked source a pass
     edits, in case the run dies mid-mutant.
   - **A guard the image does not have needs its own case.** The image
     calls PortRumbleImpact and StartForceImpact with no test, so the
     model always calls them, and the harness always set both seams.
     The port's NULL tests never ran until `G_SEAMS` left the seams
     NULL and quieted the model's two stubs.
   - **A length only shows its sum's order off a tie.** Every impulse
     in the first script summed exactly. (4.5, 0.1, 0.2) sums to
     different floats the two ways, and the difference survives the
     root. A quick search over float32 finds such a triple.
   - **Two of Init's allocations are short, and the image reads past
     both.** The NumberAllocator takes `n >> 3` bytes, so IDs 200 to 205
     are in a twenty-sixth byte, and the witness bit field is 5304 bytes
     for 42,436 bits. On the console both land in bMalloc's round-up.
     The port asks for the byte more (`COLLISIONBODY_SHORT_SLACK`).
   - **A witness never joins a body with a negative ID, or a body to
     itself.** The pair bit `ID1 * 206 + ID2` would land before the
     field, and the witness's last destructor would destroy a track body
     twice. The game converts a virgin smokeable (ID `~index`) before it
     builds a witness. A script that does either reads junk on the host.
   - **A mutant that breaks the body list hangs the harness.**
     `collisionbody_check`'s timeout is 30 s now, not 300. The first pass
     ran with 300, and the hung harnesses were killed by hand after 30 s.
   - **An equivalence has to hold for what is printed, not just for the
     state.** The pair bits are symmetric, but DoesWitnessExist answers
     the masked byte, so swapping the order was caught although it was
     listed as equivalent. Every checker's tally now counts the
     equivalents that survived, and fails on one whose mutant was caught
     or that names no mutation. Eighteen of them printed the list's size
     until this session; every mutation pass was rerun whole after the
     change, with no stale entry and 0 unexplained.
   - **A dot product's order only shows at a tie.** The script's values
     summed exactly, so both association mutants of TrackPolygonCheck
     survived. Put a compare one rounding away from its tie: 1.5 plus two
     of -2^-24 is 1.5 added one way and just under it the other.
   - **`MaxCollisionBodyWidthX` can be below a body's width.** When the
     widest body narrows, the recount leaves it out, and MaybeCreateWitnesses'
     walk then stops short of it.
   - **CollisionImpulse divides by the slide**, and a car dropped straight
     onto flat ground has none. The EE's −0 / 0 is FLT_MAX, which the zero
     slide then makes 0; IEEE's is NaN, which would reach both bodies. The
     port calls `ee_div` there, and `collisionbody_check` runs mipsemu with
     `eediv` and stops if any other division sees a zero.
   - **A stamp only shows if a dump comes before the next one.** Two of the
     contacts' survivors had their case in the script, but the test after
     it stamped the same body again before any dump. The same thing hid
     the car count's highest in slice C.
   - **A product and a quotient round apart.** Update's age is
     `(float)ticks * 0.00025f`, and `ticks / 4000.0f` differs from it at
     5 ticks (3aa3d70b against 3aa3d70a). Both of Update's mutants that
     changed the scale survived a script of round ages. A lifetime one
     ulp above each age's product, at 5, 1200 and 4000 ticks, kills them.
   - **A NaN or an exact boundary is what tells an order apart.** Five
     of the timestep's seven survivors swapped `min.s`/`max.s` operands or
     turned a `<` into `<=`, and only a NaN clock or a value exactly on
     the line (0.3 s of wait, 100 and 150 from a player) separates them.
   - **A multiply by the identity is not a no-op for the check.** OBB's
     Render takes `m × I`, and a mutant that swapped it for `I × m`
     survived every random box. Each column of `I × m` adds the identity's
     fourth row times zero, a +0, so only an axis that is -0 in one lane
     and negative in the rest tells the two apart.
   - **The closest-point search walks the paths, not the points.**
     `trackpath_find_closest_point` loops over `NumPaths`, so a manager
     with no points still hands back a point. To test "no point", zero
     `NumPaths`, as `carmode_check`'s `nopaths` case does.
   - **A BAM angle never lands on a round radian.** GetYaw is one of
     65536 differences times `BAM_TO_RAD`, and a scan of all of them finds
     none exactly on 3.14/32 or 3.14/8, so a yaw's `<` and `<=` are
     equivalent. Scan before hunting for the boundary case.
   - **Next are the track's rendering and streaming, and RaceCoordinator's
     InitForRace** (`0x001473c0`, 500 bytes), which is what will build a
     World outside a harness. InitForRace reaches much that is not ported:
     the `Player(JoystickPort, int)` constructor, the ReplayManager and
     Race constructors, InitCars (`0x00147ce8`, which needs Car's
     constructor), InitPlayers (`0x001476e8`), Race::Init, SetupGhostCars,
     SetAIDriverModesFromPlayers, and the speech and collision-sound
     resets. The World constructor it calls is ported.
   - **The 3DS build compiles every file so far.** `tools/build_cia.ps1`
     built the CIA, 316,352 bytes, with `worldinit.c`, `obb.c` and
     `bplist.c` in it and no warnings from the port's sources. Nothing on
     the boot path calls them yet, so the linker drops them and the size
     did not move.

3. **Task 26's second slice is closed: `TrackedController` and
   `RealController`**, which is what builds a RealDriver, with
   `DriveTargetRenderer`'s flag-off path. `gRealControllerCtorFn` is set at
   boot and `REALCONTROLLER_SIZE` is `sizeof`. See
   `docs/formats/real-controller.md`. `realcontroller_check` runs the
   image in mipsemu as the oracle: 14,096 ops, 25,318 lines, 0 differ,
   and 129 of 140 mutations caught with 11 equivalent.
   The first slice (Session 29) was `Joystick.obj`, the generated
   `ScannerConfigTable`, the 3DS HID backend and `RealDriver`; the
   prerequisites were `QuickSpline.obj`, `TrackPath`'s manager and
   coordinate, `Average` and the AI's four route helpers.

   - **The image check found a DriveTarget bug that its own checker had
     passed.** FillWithCurrentAcceleration integrates while the
     acceleration is *under* three quarters of the speed, and falls back to
     a straight line past it. The port and `drivetarget_check.py`'s model
     both had it the other way round, so they agreed with each other. Both
     are fixed, and the `fi` fixtures were re-derived. See "What not to
     trust" and `car-drive-target.md`.
   - **`drivetarget_image_check` then found a second one.** Above 1 m/s
     StraightLinePredict normalises the velocity inline on VU0, and the
     last multiply is `.xyzw`: the pad lane is divided by the length too.
     Port and model both copied it across unscaled. Fixed on both sides;
     `fn slp divide` and two new mutants cover it. The image checker runs
     every DriveTarget method in mipsemu with the model's scenarios, and
     both passes come out 262 mutations, 243 caught, 19 equivalent.
   - **A predicted point's pad is garbage on the console**:
     `GetPosition(bVector3)` stores a VU0 lane it never set. It is not
     compared (STACK-W).
   - Think's wrong-way test is `pPlayer->bWrongWay` (Car+24, then
     Player+736). An earlier note here said pRideInfo; that was wrong.
   - Then the rest of task 26: the other seven classes behind Car's
     constructor seams (`carmodes.h`), Player, the race and cop AI, the
     pursuit, and Car's reset and damage methods listed in TASKS.md.
   - The menus still take their input from `kBinds` in `main.c`. It moves
     onto the joystick path when the frontend's
     `AddNormalMenuJoyHandlers` is ported with the screens that use it.

   **Task 25**, the car simulation -- **closed**; the notes below are
   kept for what they teach. It was **much bigger than the task list
   said**. Nineteen slices are closed: `CarState`, `Engine`
   + `Table`, `CarTypeInfo`, `CarDriver` + `DriveTarget`'s layout,
   `Steering` + `TwoWheelAckermanSteering`, `RigidBody`, `Suspension`,
   `Wheel`, `DriveTrain`, `DriveTarget`'s methods, `Graph`, **`Car`'s
   record plus three code slices**, `PhysicsSystem` and `Aerodynamics`,
   the component vtables, **`PhysicsCar`**, and **`MellowMover` with its
   `Mellovator`**. Each has a checker and a doc under `docs/formats/`.
   Most are `car-*.md`; `RigidBody`'s is `rigid-body.md`, `Car`'s is
   `car.md`, and the rest are `physics-system.md`, `aerodynamics.md`,
   `physics-components.md`, `physics-car.md` and `mellow-mover.md`.

   The old "178 functions, 16680 bytes" note was wrong by an order of
   magnitude -- it matched a narrow symbol pattern and missed most
   methods. Remeasured by demangling every symbol to its owning class,
   task 25 was ~39.9 KB across 140 functions. Thirty-nine Car methods,
   `PhysicsCar`, the `Mellovator` and `MellowMover` are ported, so
   **18.8 KB across 41 functions** is still to go, all of it `Car`'s:

   ```
   Car 41 funcs 19256 B   (done: PhysicsCar 16 / 8496,
                           Mellovator 31 / 5420, MellowMover 13 / 3096)
   ```

   Three `DoSnapshot`s are counted as done but are not: PhysicsCar's,
   MellowMover's and the Mellovator's wait on `ReplaySnapshot`.

   `PhysicsSystem` (`0x00192460`, ~1.2 KB) and `Aerodynamics`
   (`0x001a4b58`, ~0.65 KB), which `PhysicsCar`'s constructor needs and
   the count never had, are ported now -- see below.

   The thirty-nine are 3620 B of the 22876 -- the cheap ones went
   first, and the expensive half of Car is the constructor, the reset
   and damage groups and the render path.

   **Car's third code slice is closed** -- `IsCarToLeft`,
   `IsCarToRight`, `GetRelativeCarPosition`, `IsCarInFront`,
   `GetPostCollisionYawControlBoost`, `IsDrifting` and `ComputeFakeRPM`
   with `smooth<float>`, and `bToPolar`, which `bmath.c` had never had
   although `bmath.md` said all nineteen were ported. 58 scenarios,
   4238 lines, 0 differing; 254 mutations, 238 caught, 16 equivalent, 0
   unexplained. Poke an aliased array to make a shipped-invisible
   branch visible: the yaw profile and `RPMTable`'s neighbours are both
   fixtures now.

   **Car's second code slice is closed** -- the vtable seam
   (`vtable.{c,h}`), the nine dispatchers, the three borrowed fields,
   both `CalculateDraftFactor`s and `_GLOBAL_$I$fDraftFalloff`. 42
   scenarios, 3864 lines, 0 differing; 178 mutations, 169 caught, 9 equivalent, 0 unexplained. Read the second half of
   `docs/formats/car.md` before the next slice, and in particular:

   - **Virtual calls go through `vt_slot` / `vt_this`**, keyed by the
     image's own vtable address. A class that installs a real table
     computes its deltas with `offsetof`: the host's slack moves bases.
   - **Static initialisers run from `sinit_run()`**, which `main.c`
     calls first thing, in `__CTOR_LIST__` order. A new `*_static_init`
     that is not added there fails `sinit_check`. Four had been ported
     and never run before this.
   - **A boundary fixture is not a boundary test until the boundary can
     be reached from it.** The draft's reach at 60 is visible only
     through `dot / dist` rounding above 1, which no single-axis fixture
     can produce.

   **`PhysicsSystem` and `Aerodynamics` are closed**, with two pieces
   the system needed: the EE ticker (`bticker.{c,h}`) that times
   `ComputeAuxiliaries`, and `p32.{c,h}`, which lets a 32-bit link slot
   hold a pointer on the 64-bit host, so the list walk the checker runs
   is the code the handheld runs. `physicssystem_check`: 12 scenarios,
   739 lines, 0 differ; 62 mutations, 61 caught, 1 equivalent -- and the
   equivalent was checked over 723,967 inputs, not just argued.
   `aerodynamics_check`: 7 scenarios, 107 lines, 0 differ; 74 mutations,
   74 caught. What matters for `PhysicsCar`:

   - **IntegrateEuler is the only integrator the game runs.** RK4 is
     ported and has no caller anywhere in the image.
   - **A PhysicsSystem owns its components.** Its destructor destroys
     every one with flags 3, so nothing else may free them.
   - **The walk asks each component its size after the slot call**, and
     reads the next link after it too. `Size` is only trusted by RK4.
   - **Aerodynamics' downforce is linear in speed**, and its "direction"
     is not a unit vector unless Boost is 1.
   - **`ApplyForceInFrame` had no checker before this one.** It has now:
     two `bMulMatrixVector`s, the first a `j` thunk, then `ApplyForce`.
   - `SetGroundEffect` was missing from the port and is in it now.

   **The component vtables are closed** -- `physcomp.{c,h}`: all seven
   tables at the image's addresses, the eight destructors, every
   operator new and delete, and `InitPhysics` / `ClosePhysics` with the
   ten slot pools. `physcomp_check`: 8 scenarios, 239 lines, 0 differ;
   47 mutations, 46 caught, 1 equivalent. `main.c` installs the tables
   right after PhysicsSystem's. Read `docs/formats/physics-components.md`
   first; what matters for `PhysicsCar`:

   - **A new component is zeroed.** Every pool starts with flags 15, and
     `bOMalloc` clears the slot, so the constructors lean on it.
   - **After destruction a component carries PhysicsComponent's vptr**
     and an Ackerman carries Steering's; a freed slot keeps everything
     but its first word.
   - **Engine's own vptr store in `~Engine` is dead** -- the base
     overwrites it -- and is the one equivalent mutant.
   - **`~SkidMaker` is `MakeNoSkid`**, which goes through a seam,
     `gSkidSetFinishedAddingFn`; a wheel with no set never reaches it.
   - **The pools take n as a parameter**, since the race parameters
     are not ported. The RigidBody pool's 32 spare slots are the
     Smokeables'. NullMover's slot size is an image constant in
     `physcomp.h` until that class exists; the Mellovator's and
     MellowMover's are `sizeof` now.
   - Ackerman's `DoSnapshot` is the one NULL entry, pending
     `ReplaySnapshot`, and the checker says so on every run.

   **`PhysicsCar` is closed** but for `DoSnapshot`, and three small
   modules `Move` reads came with it: `race.{c,h}`, `cardamage.{c,h}`
   and `joystick.{c,h}`. `physicscar_check` is the first checker whose
   oracle is the image itself. `mipsemu` runs the shipped constructor,
   both integrators, UpdateCar and Move, with every component method
   they reach, and the harness runs the port on the same records. 106
   scenarios, 102908 lines, 0 differ; 263 mutations, 257 caught, 6
   equivalent, 0 unexplained. Read `docs/formats/physics-car.md`. What
   matters next:

   - **Two older ports were wrong, and their models agreed with them.**
     GetLateralForce's curve scale is 12 (`lui at,0x4140`), not 11, and
     CheckTerrain's fifth argument is the terrain it refreshes. A model
     written from the same reading as the port is not an oracle.
   - **A car sitting in gear divides zero by zero**, in DriveTrain's
     clutch split. The EE gives FLT_MAX and IEEE gives NaN. A divide that
     can see 0/0 uses `ee_div` (`eefpu.h`), and mipsemu's `eediv_pcs`
     lists every one a run reaches.
   - **The image reads uninitialised stack words** in six places. The
     port writes zero, and the model hooks the image to zero them too.
   - **`hostbuild` caches objects**, so a mutant rebuilds one file, and
     `diff_count` replaced difflib. A PhysicsCar mutant takes about 2 s,
     down from minutes.

   **`MellowMover` and its `Mellovator` are closed** but for their two
   `DoSnapshot`s. `mellowmover_check` runs the image the same way: 39
   scenarios, 56080 lines, 0 differ; 346 mutations, 341 caught, 5
   equivalent, 0 unexplained. Read `docs/formats/mellow-mover.md`.
   What matters next:

   - **`.lit4` is not always the nearest float.** The half-pi is
     `0x3fc90fdc`, one ulp high, and it feeds `bSin`'s truncation to a
     BAM. The checker reads all eighteen pool constants back out.
   - **An airborne, level car divides 0/0 in `bNormalize3To`**, which
     now uses `ee_div`.
   - **Three synthetic records**: car 0 with CoG.y 0.0625, car 0 with
     the droop stops at -2, and car 34 for its two final drives. The
     shipped data hides those branches.

   **Car's fourth code slice is closed** -- `SetMovementMode`,
   `SetControlMode`, `SetToPhysicsMode`, `SetFrictionBoost`, with
   `NullMover`, `NullController`, `NullDriver`, the `CarController` base
   and `CarCollisionBody`'s two methods. `carmode_check`: 74
   transitions, 27324 lines, 0 differ; 114 mutations, 114 caught.
   `wheel_install_seams()` runs at boot. Read `docs/formats/car-modes.md`;
   what matters next:

   - **Task 26's eight classes are behind constructor seams** in
     `carmodes.h` (`gTrafficCarCtorFn` .. `gCopDriverCtorFn`). A NULL seam
     aborts and names the class. Porting one means setting its seam at
     boot and changing its `_SIZE` constant to `sizeof`.
   - **Both methods store the mode before the arm runs**, so a
     constructor that reads the car sees the new mode.
   - **A store through the wrong type lands in the neighbour.** Check the
     bytes past an object, not only its fields.

   **`Car`'s record is whole and its first code slice is closed.** The
   2016-byte layout is in `3DS Files/source/car.h` -- 72 offsets, each
   re-derived from a load or a store -- and it has been through the ARM
   build, where every `CAR_SLACK` term is zero and `CAR_AT(f, n, k)`
   reduces to the console's raw offset. `TopologyCoordinate` came with it,
   layout only, in `topology.h`, because Car embeds one by value and its
   128-pointer table would have made a blob agree with the wrong number on
   the host.

   The first slice's eighteen are the three retail stubs, the blinking,
   the debug checksum, the two wheel aggregates, the two effect gates,
   the forward acceleration, the horn request, the wiper window, the
   borrowed steering angle and the eight-byte `WorldToCar` forwarder.

   Read `docs/formats/car.md` before the next slice. Three things in it
   cost time to find: `GetWheelTraction` pairs the **diagonals**, not the
   axles; `IsBlinking` has **two** sentinels, 0 and `0x7fffffff`; and
   `cvt.w.s` saturates by the sign of the source, which x86 does not do
   and ARM does, so the conversion is written out rather than cast.

   **That order used to read "PhysicsCar, Car" and it was wrong.**
   `PhysicsCar::Move` (`0x00135c78`) calls three `Car` methods and reads
   seven `Car` offsets outside the embedded `CarState`, so the
   `CarState`-only stand-in that carried `DriveTarget` does not carry
   `PhysicsCar`. `Car` comes first. Checked in the disassembly, the same
   way `DriveTarget`'s independence from `Car` was.

   **This said two small things came before `Car`. It was one.**
   `Graph` (`0x00187440`, `0x00187450`) is ported. The second --
   `CarState::WorldToCar` at `0x001b6ab0` -- turned out to have been
   ported already, by the `CarState` slice: both overloads, three
   mutations, and a paragraph in `docs/formats/car-state.md` about the
   quadword subtract in the 3D one. The plan was written off a symbol
   search rather than off `carstate.c`, and a search for the PS2 name
   does not find `carstate_world_to_car2`. **Before porting anything a
   plan calls a prerequisite, grep the ported sources for it under the
   name the port would have given it, not the name the ELF has.**

   ```
   Graph  0x00187440, 0x00187450   8 bytes, 2 methods; four Car methods
                                   want it. Ported -- 16 scenarios,
                                   25 mutations, docs/formats/car-graph.md
   ```

   **And the same mistake was underneath it twice.** That paragraph used
   to end by saying `DriveTarget::Dump` was still blocked on
   `Car::WorldToCar`. It was not: `drivetarget_dump` has been in
   `drivetarget.c` since the DriveTarget slice, and it reaches the
   transform the way the forwarder would have -- `carstate_world_to_car2(
   &car->State, ...)`, which is the `+64` written out. `docs/formats/
   car-drive-target.md` said so at the time ("It is ported anyway, for two
   reasons") and the planning note was never corrected to match.

   So the lesson above is not about one symbol. **A plan's "blocked on"
   list decays; the ported sources do not. Check the source before
   believing the plan, every time, including when the plan is this file.**

   `Car::WorldToCar` (`0x00138e90`) is ported now regardless -- it is a
   real method of the eighty and it is eight bytes, `j
   CarState::WorldToCar; addiu a0,a0,64` -- so the forwarder exists under
   its own name for the next caller that wants it.

   **`Car` is the hub, not the physics -- measured, not assumed.**
   Eighty methods, 22876 bytes, `Car.obj` at `0x0012f150` (`0x5e1c`).
   Six are emitted outside that object, including the eight-byte
   `Car::WorldToCar` at `0x00138e90`. The record is 2016 bytes with one
   non-virtual base at offset 0, `bTNode<Car>` (8 bytes) -- **`Car` has
   no vtable**; the `__pure_virtual` the map shows against `Car.obj`
   belongs to the `CarDriver` / `CarMover` / `CarController` abstract
   bases that share the object.

   **Thirty-four of the eighty make no call outside the class, and thirty
   of them are ported.** The other four are `SetToPhysicsMode` and
   `SetFrictionBoost` (both PhysicsCar's), `DoWheelForces` (force
   feedback) and `PutFlatOnTrack` (a real `TopologyCoordinate`, task 27).
   The split is over all eighty, and seventy-four of those are in
   `Car.obj`; `WorldToCar` is one of the six emitted elsewhere, and it is
   in the forty-six because its `j` leaves the class. Two of the forty-six
   are ported. The partition is spelled out at the bottom of `car.c`.

   The other forty-six reach about a dozen subsystems belonging to tasks
   26, 27 and 29: replay, cop manager, the effect system, force feedback,
   sound, topology, collision, render info, damage, `Player` and `Race`,
   and eleven driver/mover classes that `SetControlMode` and
   `SetMovementMode` construct between them. The next slice is named
   above; `HANDOFF.md`'s Session 25 entry has the scan behind it.

   Two `DriveTarget` methods are blocked, and always were two rather than
   the three this file used to list: `DoSnapshot` on `ReplaySnapshot`, and
   the `DrivingLocation` overload of `AddPointToTarget` on
   `DrivingLocation::IsClear`, which is `lw v0,0(a0); sltiu v0,v0,1` and
   has a one-word stand-in until task 26 brings the class.

   `drivetarget.h`'s stand-in `Car` is **gone**; it includes `car.h` now.
   Two consequences, both already handled. The include-ordering rule
   car.h's header describes is retired -- either order gives the real
   record. And `drivetarget_check`'s `[layout]` scenario changed, because
   the stand-in's padding was written to cancel the host's pointer slack
   and the real record does not: the three offsets read 18, 48 and 112 on
   this host, which is `CAR_AT(DriverNumber, 10, 2)`,
   `CAR_AT(pPlayer, 24, 6)` and `CAR_AT(State, 64, 12)`. On ARM they are
   10, 24 and 64 again. The two mutations that used to aim at the stand-in
   now aim at `car.h`.

   `car.h` names `CarTypeInfo` and `CarDriver` rather than including
   their headers, because `cardriver.h` -> `drivetarget.h` -> `car.h` is
   a cycle: with the include in place, compiling `cardriver.c` reaches
   `struct Car` before `CarDriver` is defined. `car.c` includes
   `cardriver.h` itself for `pCarDriver->Steering`.

   **Mutation passes are crash-safe now.** A stopped `drivetarget_check
   --mutate` had left `sr-count-signed` in `drivetarget.c` -- equivalent,
   so plain runs stayed clean -- and `camera_check`/`trackroute_check`
   had been restoring with a translating write, which put CR CR LF on
   every line of `camera.c`, `cammover.c` and `trackroute.c`. All four
   repaired (the three are byte-identical to HEAD again), and every
   checker's `write_source` is `hostbuild.write_source` now: it parks the
   original as `<name>.<pid>.mutate-backup`, and `hostbuild.build()`
   restores any whose process has died. **Still: never edit a source a
   live pass compiles, and never run two passes that mutate one file
   -- the second now stops at its first write to that file rather than
   restore the first one's mutant for it.** A pass that must run beside
   another that mutates a file it links can run from a copy of the tree:
   every checker finds its sources from its own path, so `tools/`,
   `3DS Files/source/`, the ELF, `docs/mdebug_structs.txt` and the two
   extracted bundles are enough (Session 30).

   **`Wheel`'s two seams are wired but nothing installs them, and their
   home is now known.** `wheel_install_seams()` points
   `gWheelFindDrivingSurfaceFn` and `gWheelExchangeZForcesFn` at the
   real methods, and no code in `3DS Files/source/` calls it, so they
   are still `NULL` on hardware. That is correct today -- nothing
   constructs a `Suspension` or a `Wheel` yet -- but the call belongs in
   **`Car::SetMovementMode`'s `PHYSICS_MOVEMENT` arm**, which is what
   constructs the `PhysicsCar` that owns the `Suspension` and the four
   `Wheel`s, and it has to happen before that car's first
   `ResolveForces` or every corner reports airborne. The seams are a
   port artifact: at `0x0019bdd4` and `0x0019c104` the PS2 build makes
   two ordinary `jal`s.

   The HUD split is settled, below.
4. Then in order: 36 the full game (the road below), 26 race/cop AI, 27 track render/stream/collision,
   28 New3DS perf, 29 save/options/sound mix, 30 split-screen scope,
   31 final CIA + Old3DS/New3DS pass.
5. **`QuickSpline.obj` is ported** (Session 29, continued), which pays
   task 24's debt. `TrackPathCoordinate::UpdatePosition` now measures
   through the spline, so `SetFirstAndLastPoints`, `Signpost::SetDistances`
   and `TestSignpostConsistency` run for real. `gTrackPathDistanceFn` is
   now only `trackroute_check`'s closed form, and it is `NULL` on
   hardware. `cammover.c` still leaves out the CM_TRACK_CAR and
   CM_TRACK_FLY movers, which needed the spline too.
6. Whenever a screen class gets ported, take its row in `kScreens[]` off
   `bgf_plain_screen_callback`. Ten of the eighteen are on it -- they draw
   and answer the D-pad and nothing else -- and
   `python tools/screen_registry.py --check-port` lists them, along with
   anything new the port can reach and has not registered. Run it after any
   change to `kScreens[]`: a hash typed by hand is not checked by anything
   else, and a name with no row is a black top screen, not a no-op.

**Phase 4 constraint, from the user:** the gameplay HUD is to be designed for
**two screens from the start** -- readouts on the bottom screen rather than
all stacked on the top one, to keep the view of the road clear.

The split is **decided** (2026-09-21, asked and answered): **bottom screen
takes the minimap, lap/position and objective text; the top keeps the
speedo/tach and the pursuit meter**, because those two are monitored
continuously rather than glanced at and belong in the same eyeline as the
road. Build tasks 25-27's HUD to that from the start rather than making a
top-screen HUD and splitting it later. `uirender.c` (citro2d) is the home
for the bottom-screen widgets; `georender.c` (citro3d) owns the top. Also
at the head of Phase 4 in `TASKS.md`.

## The road to the full game

The user supplied the retail disc on 2026-09-27, so the target is the
full game. "Playable" means its loop: start or load a career, pick a car
and an event in the frontend, race any of the thirty tracks against the
AI with the cops on, see the result, have it saved to the SD card, and go
back to the menus. The count below is in slices of the size the last ten
were, one or two sessions each. It is an estimate, and it will move as
each class shows what it reaches.

| Step | What | Slices |
|---|---|---|
| 1 | ~~The track on the screen: the viewer mode, eModel over `georender`, a free camera~~ done, task 27's twenty-third slice | 1 |
| 2 | ~~The LoaderTable: every chunk type in TRACKB12, with the solids, the texture packs, the topology and the routes live~~ done, task 27's twenty-fourth and twenty-fifth slices | 2 |
| 3 | ~~The sky, the sun and the weather's draw~~ done, task 27's twenty-sixth to twenty-ninth slices. The shipped image has no rain or storm to draw | 2-3 |
| 4 | ~~The retail disc's data in the track viewer: the tracks shipped expanded, the retail chunk set, the changed loaders, and a second location~~ done, task 36's second to eighth slices | 1 |
| 5 | ~~The retail model: mipsemu on `SLES_507.31` by retail_match's names, so that a checker can run the retail function~~ done, task 36's second slice: `tools/retail_model.py`, in `track_check` and `loadertable_check` | 1 |
| 6 | ~~Car's constructor and destructor, and CarRenderInfo, from retail where retail changed them (all of them did), so that a car draws on the track~~ done. The constructor and destructor are done, task 36's tenth slice; CarRenderInfo's build is done, the eleventh; Render is done, the twelfth; RenderCars is done, the thirteenth. The front end's cars wait for the car selector (step 16) | 3-4 |
| 7 | ~~Player and the chase cameras (CM_DRIVE and the rest of `cammover.c`'s set)~~ done, slices 7a-1 to 7d: the camera base, the shake, the drive camera, the orbit's retail pass and Player's camera functions. The other movers are seams until their classes are ported | 2 |
| 8 | ~~RaceCoordinator's InitForRace, InitCars, InitPlayers and Race::Init~~ done, and the game flow into a race by SkipFE (8l). The frontend's way into a race and back is not done | 2-3 |
| 9 | ~~**One car driving the track.**~~ Reached in 8l-3b | |
| 10 | The retail pass over what is already ported: the 130 changed functions cited from a `.c` in `docs/retail_audit.txt`, module by module, each checker gaining a retail model run where it can | 4-6 |
| 11 | The rest of task 26: the racer and traffic AI, the six classes behind Car's constructor seams | 4-6 |
| 12 | The cops and the pursuit: CopManager, the cop drivers, roadblocks and spikes | 4-6 |
| 13 | ~~The two-screen HUD, to the split decided below~~ done as 8m: 8m-1 to 8m-6c | 10 |
| 13b | New 3DS mode in full and a steady 30 FPS race (task 28), right after step 13: the real clock and the pacing, a frame profiler, New 3DS mode checked part by part, then only the optimizations the New 3DS needs. Set by the user on 2026-10-03 | 4 |
| 14 | The car and world sounds and the speech, and the ChopperSound (12k-5) | 12 (14-1, 14-2a, 14-2b, 14-3, 14-4, 14-5, 14-6, 14-7, 14-8a, 14-8b, 14-8c and 14-8d done) |
| 14b | ~~The smokeables: FindSmokeableInfo, the spawner (`0x0021ed28`) and delete (`0x0021ef88`), Smokeable's Break and DeleteFarAway, and their collision~~ done (Session 85, `docs/formats/smokeable.md`). The roadblock's barrels use it, and the helicopter's munitions (12k-6, Session 87) | 1 |
| 15 | **A whole race with the AI and the cops.** Steps 10-14 add about 15-23 slices | |
| 16 | The full frontend from retail: the 44 screens still plain or unregistered (`screen_registry.py --check-port`), the event tree (the career), the tourneys and the car selector | 6-10 |
| 17 | Save data on the SD card in the memory card's place: Phils Load Save, the autosave, the boot autoload and the options (task 29) | 2-3 |
| 18 | Every track and car: the thirty tracks and the whole car list load and race | 1-2 |
| 19 | ~~Old 3DS performance~~ none: since 2026-10-05 the port is the New 3DS's alone (the user's call). An Old 3DS shows "This port needs a New 3DS" at boot and exits on START (6ac29d1); there is no Old 3DS mode | 0 |
| 20 | The split-screen decision (task 30), then the final CIA, banner and hardware pass (task 31) | 1-2 |

That was about 41-60 slices to the full game when the table was set.
After 12k-7 (2026-10-09), about 22-35 are left, and the count has
run low before:
- step 12's: 12m (12n and 12k-6 are done), and the NIS
  player;
- steps 10, 14, 14b, 16, 17, 18 and 20.

The replay (`ReplaySnapshot` and every `DoSnapshot`) is not in the
count. It is its own slice when it goes in.

### Where the port stands (2026-10-08, after 11h-3)

- **Done:** steps 1-9 and 13. One car drives the retail track at the
  retail start, lit, with the chase camera. The HUD shows the race on
  both screens with its animations, and the minimap on the bottom one.
  Tasks 1-25 and 32-35 are closed: 29 of 37. The open ones are 26-31,
  36 and 37.
- **Next:** Be A Cop (the user's ask; the end of the race, RE-1 to
  RE-6, is done, see "First"; so is TASKS 41), then step 14's 14-10d. 14-1, 14-2a, 14-2b, 14-3, 14-4, 14-5, 14-6, 14-7, 14-8a,
  14-8b, 14-8c, 14-8d, 14-9, 14-10a, 14-10b and 14-10c are done. Of step 12,
  12a to 12k-2, the light flares, 12k-3's planners, 12k-3a, 12k-3b,
  12k-4a, 12k-4b, 12k-7, 12l-1 and 12l-2 are done. See
  "First" at the top.
  These are done:
  - 11a, what an AI car knows as it drives;
  - 11b-1, retail's DriveTarget;
  - 11b-2, DrivingChoice's small methods and the walk;
  - 11b-3, BuildDriveTarget and round a car;
  - 11b-4a, CarCollisionPredict;
  - 11b-4b, MakeNewChoice and the three it calls;
  - 11c, AIPlan and the AIAction base;
  - 11d-1, the five small actions;
  - 11d-2, Pass and AvoidCars;
  - 11d-3a, PullOver and IJustGotHit;
  - 11d-3b, GetUnstuck and AvoidRoadBlock;
  - 11e-0, Average at retail's size;
  - 11e-1, AICarController's record, route methods and action;
  - 11e-2, AICarController's signposts and sticky decisions;
  - 11e-3, AICarController's belt, glue and boost;
  - 11e-4, AICarController's horn and ExecuteCurrentAction;
  - 11e-5, AICarController's Think;
  - 11e-6, the BeltMover;
  - 11f-1, PsychoDriver;
  - 11f-2, AIDriver;
  - 11g-1, a SkipFE race with AI racers that drive;
  - 11g-2a, the Quick Race from Hot Pursuit's Mode Select;
  - 11h-1, TrafficCar;
  - 11h-2, TrafficDriver;
  - 11g-2b, Race::Update;
  - 11g-2c-1, the camera data and the countdown coordinator;
  - 11g-2c-2a, the fly-by camera;
  - 11g-2c-2b, the Starting Grid;
  - 11g-2d, the pause menu;
  - 11g-2c-2c-1, the pre-race coordinator;
  - 11g-2c-2c-2, BumperCameraMover;
  - 11g-2e, the rear-view mirror;
  - 11h-3, the TrafficTeleporter.
  13b-4f, the device GPU's cost per model, waits on the device's timing
  run. The car selector (SC-1 to SC-3) is done, the nebula and the
  effect system with it. 13b-1 (the real clock and the pacing), 13b-2
  (the frame profiler), 13b-3 (New 3DS mode in full), 13b-4a to 13b-4e
  (the draw's cuts) and the jump cam are done.
- **Left, in the table's units:**

  | Step | Slices left |
  |---|---|
  | 13b, New 3DS mode and 30 FPS | 1 |
  | 10, the retail pass | 4-6 |
  | 11, the racer and traffic AI (11a to 11h-3 done) | 1 |
  | 12, the cops | 4-6 |
  | 14, the sounds | 2-3 |
  | 16, the frontend | 6-10 |
  | 17, the saves | 2-3 |
  | 18, every track and car | 1-2 |
  | 19, Old 3DS performance (dropped; New 3DS only since 2026-10-05) | 0 |
  | 20, the split-screen decision and the final CIA | 1-2 |
  | **Total** | **22-34** |

- **How far along:** about 37-40 of the road's 60-75 slices are done,
  roughly half. The estimates run low. Step 13 was put at 1-2 slices
  and took 10, and step 8 took eighteen commits (8a to 8l) for its 2-3.
  Read the 22-34 as a floor. Step 11 was put at 4-6 before its slices
  were laid out. They are fourteen, with traffic beside them: 11a,
  11b-1 to 11b-3, 11b-4a and 11b-4b, 11c, 11d-1, 11d-2, 11d-3a and
  11d-3b, and 11e to 11g. 11b was one slice until DrivingChoice's 13 KB
  were read, and 11d until the eleven actions were counted and read.
  11f became two (PsychoDriver, then AIDriver) when AIDriver's
  constructor was found to build a PsychoDriver.
- **The pace:** 80 commits from 2026-09-27 to 2026-10-04, most of them a
  slice each.
- **Not yet in the count:** the replay. The race's music no longer
  waits on it (Session 43). The race runs in real time since 13b-1, at
  28-30 FPS on Azahar since 13b-4d. Holding 30 is the rest of 13b-4.
  The car selector's 2D is retail's now (SC-1). The car itself is SC-2.

## What not to trust

Ordered roughly by how much time it costs to rediscover.

* **The race's heap is nearly full.** About 6 MB of the 48 MB malloc
  heap is free once the track has loaded (2026-10-05, Azahar), and not
  in one piece. A car's textures upload after that, so a big scratch
  malloc in a texture upload fails there and nowhere else. The mip
  chains' first build asked for 1.25 MB for a 512x320 skin: the
  Speedster drew with no paint, only its reflection. The solids listing
  in the race log marks a texture that would not upload with `!`
  (`OPEL_SKIN1!`), and the texture line counts it as missing. Keep
  scratch to the decoded level, or use the linear heap.

* **A checker whose model was written from the disassembly can share a
  misreading with the port.** `drivetarget_check`'s model and
  `drivetarget.c` both had FillWithCurrentAcceleration's first test
  negated. The two agreed, and the checker's own `fi-dominates-flipped`
  mutant was "caught" against the wrong answer. Only running the image
  (`realcontroller_check`) showed it. The image-backed checkers are
  airoute, average, car, carinit, carmode, drivetarget_image,
  joystick, mellowmover, physicscar, quickspline, realcontroller,
  realdriver and trackpath; carinit and trackpath run retail's. Every
  other
  `*_check.py` compares against a Python model, which includes most of
  task 25: carstate, engine, cartypeinfo, cardriver, steering, rigidbody,
  suspension, wheel, drivetrain, graph, physicssystem,
  aerodynamics and physcomp. car_check, physicscar_check and
  mellowmover_check do run the image's copies of some of those beneath
  them, but only as far as their scenarios reach. A model-only pass is
  evidence that two readings agree, not that either matches the console.
  DriveTarget did it twice (the Fill test, then StraightLinePredict's pad
  lane) before `drivetarget_image_check` took the model out of the oracle.
* **A scenario that hands a mover the Car's own CarState cannot tell
  `State` from `pCar->State`.** MellowMover reads each in different
  places. In the game they are the same object, so a port that mixed
  them up would pass every such scenario. `mellowmover_check`'s
  `c0-apart` passes a copy with a different ForwardSpeed, and task 26's
  movers want the same.
* **A NULL seam that the image calls unconditionally needs its NULL case
  checked too.** `realdriver_check`'s seam mask does this: a clear bit
  leaves the harness's pointer NULL and makes the model's stub silent,
  answering what the port assumes. Without it, the port's "skip when
  NULL" branches are code no checker has run.
* **Two calls that share no state have an order only their logs can
  show.** RealDriver's Drive could run DoSteering before
  DoThrottleBrakeReverse and every dumped field would agree. A mutant
  that swaps them needs a frame on which both of them log something.
* **A decimal constant is not the pool's bits.** The `.lit4` half-pi is
  one ulp above the float nearest pi/2, and the port's first BAM-to-radian
  constant was a digit short. Write the bits beside the literal
  (`// gp-27752  38d1b717`) and have the checker read the pool.
* **Shipped data hides branches.** CoG.y is 0 in all 66 car records, 61
  have equal final drives, and 21 have CoG.x 0. A survivor on shipped
  records may want a copy of a real record with one field changed, not a
  new scenario.
* **The Microsoft Store Python virtualises writes under `AppData`.** A
  file it writes there is not where the shell or a harness looks for it.
  Debug output goes under the repo's `out/`.
* **A format loaded by casting has no parse step to get wrong -- the struct
  layout *is* the format.** `TrackRoutesLoader` casts the chunk's bytes to
  `TrackRoute *` and registers the pointer; nothing is copied and nothing is
  read field by field. So a field at the wrong offset is not a compile error
  and not a decode failure, it is a route that loads and then reads
  nonsense. Two things follow, and both bit this session: the record's
  `pNext`/`pPrev` are **32-bit slots holding disc garbage**, not host
  pointers, and `sizeof` has to be asserted -- it came out 115760 instead of
  115752 on the 64-bit host and only the harness noticed. Any future
  cast-loaded chunk wants the same assert and the same byte-image model in
  its checker.
* **A `bChunk` header of all zeroes is padding, not a terminator.**
  `bchunk_dump.py` stopped at the first one and so reported 8 chunks in
  TRACKB12.BUN's 9 MB, having given up at the alignment run at `0x7048`
  after five top-level chunks. The real counts are 497 top-level and 7,101
  recursively. The dumper still leaves out the 25 all-zero headers, so it
  counts 472 and 7,076. `bchunk.c` had always skipped them, so the C and the
  tool disagreed silently. Fixed this session -- but the lesson is that the
  dumper is not the authority, the loader is. LoadChunks walks all 497, and
  LoaderNull takes the 285 of type 0, the 25 zero headers among them.
* **The task list can be wrong about what a format even is.** Task 24 asked
  for an "`espEmptyLayer` spline/track-layer format". No such format exists:
  Espresso is bware's live editor RPC protocol and Caffeine is the PC end of
  it, evidenced by `EspressoServer`, the `Caffeine = %d, Espresso = %d`
  version handshake and an `EspressoFunctions` enum of `EF_LoadWorld`-style
  members. Half a day can go into looking for a file format that was never
  a file format. Check the strings and the mdebug enum before believing a
  name in `TASKS.md`.
* **A PARTIAL from `run_azahar_test.ps1` is worth re-running before it is
  worth debugging.** The harness drives Azahar with synthesised keystrokes
  and it can drop one; a dropped A at the main menu walks the rest of the
  script down the wrong branch and the verdict blames the wrong thing. The
  same build went PARTIAL then PASS with nothing changed in between.
* **The Bash tool eats one level of backslash inside a heredoc.** A patch
  script whose replacement string contains a C escape gets a real newline
  instead, the pattern stops matching, and the script cheerfully prints
  "done" having changed nothing -- or worse, having applied half its edits.
  Build the backslash from `chr(92)`, or use the file-editing tool. This cost
  two broken source files this session.

  **Apostrophes go the same way**, which is why `tools/trackroute_check.py`
  was written out with the file-editing tool rather than a heredoc. A
  heredoc with quotes nested inside quotes can also fail outright
  ("unexpected EOF while looking for matching"). If a
  script's content has either character in it, do not pipe it through a
  shell.
* **`C3D_FVec` is declared `w, z, y, x`.** `r[i].c[j]` is element
  `(i, 3 - j)`, so a loop that fills `c[0..3]` as though they were columns
  0..3 writes every row backwards. It cost a build this session: the camera's
  view matrix came out transposed *and* mirrored, the eye never left the
  world origin, and the car drew as a black fan of triangles seen from
  inside the bodyshell. Nothing in the cross-check could see it. Use the
  named `.x/.y/.z/.w` fields, or subtract.
* **Azahar shows an "Update Available" dialog on launch** and it swallows
  every `PostMessage` keypress aimed at the emulator window. All three
  `run_azahar_*.ps1` scripts now close any visible top-level window of the
  process that is not titled "Azahar" before they start pressing keys. A run
  that does not is indistinguishable from a dead key binding: the app boots,
  the log looks healthy, and nothing responds.
* **A libctru console and citro2d cannot share a screen.**
  `consoleInit(GFX_BOTTOM, NULL)` switches that screen to RGB565 while
  citro3d goes on presenting BGR8 into the same framebuffer, and the result
  is not a flicker -- it is two half-width copies of the frame under a
  coloured dither, which looks like a render bug in your own code. There is
  no console in the port any more except on the top screen on the way out.
* **`tools/hostbuild.py` is a library, not a CLI.** Running it as a script
  exits 0 and produces nothing. Call `hostbuild.build(tmp, sources, name=...)`.
* **A survivor in a mutation run is not automatically a coverage hole.** Two
  of `bsnd_check.py`'s survived because they were equivalent mutants -- a
  quadrant boundary where both arms compute the same number, and a float that
  rounds identically in double. Work out which before adding scenarios.

  There is a third answer besides "hole" and "equivalent": **the mutation
  itself was badly written.** `(uint16_t)(int16_t)x` on a `uint16_t` field
  is a no-op by C's own rules and could never be caught; a mutation that
  fails to compile because it used `memset` without `<string.h>` was
  rejected by the compiler rather than by the transcript. Both were
  rewritten into the transcription errors they were standing in for.

  Two more shapes of the same mistake turned up in `Wheel`. A mutation
  whose body writes only to **its own parameters** (`lo = hi = value;` in
  an empty function) is three dead stores and cannot be caught by
  anything. And a mutation that writes **the value the target already
  held** -- `gMaxStaticSlip = value` where the call passed 0.5 and
  `gMaxStaticSlip` is 0.5 -- leaves no trace either; the call site had to
  pass 0.375 before the mutation meant anything.
* **A comment claiming a case is covered is not coverage, and it is worse
  than no comment.** `wheel_check.py` and `wheel_test.c` both said vx 0.4
  with a spin of 1.25 put the slip at exactly zero and so reached
  `GuessGroundForce`'s zero-magnitude early-out. `1.25 * 0.32f` is
  0.399999976, so the slip was -2.98e-08 and the guard was never reached
  at all. The mutation that deletes it survived a full pass, and the
  comment was read twice as the reason it could not be a hole. Where a
  case depends on an exact float, compute it rather than asserting it --
  `37.5 * 0.32f` is 12 with nothing left over, and that is the pair that
  works.
* **A mutation can survive because the fixture agrees with itself.**
  Three of `DriveTrain`'s eighteen survivors were that shape: a swap of
  `gShiftUpDetune` for `gShiftDownDetune` where the image ships both at
  0.95, a dropped store of a pedal the constructor had already left at
  the value the store writes, and a clamp to `FIRST_GEAR` of a
  `DesiredGear` the constructor had already set to `FIRST_GEAR`. Nothing
  is wrong with the mutation or with the code -- the input cannot tell
  them apart. Drive the fixture from a value the object would have to go
  out of its way to produce (detunes of 0.8 and 0.6, a pedal at 0.25, a
  gear of fifth) and all three die.
* **A `<` against `<=` needs the two sides equal bit for bit, and
  picking a likely number is not good enough.** `DriveTrain`'s inclusive
  mutants are killed by writing the shift point back as the very RPM the
  object computes, from the same product on both sides, so the compare
  is against itself. Where the fixture cannot be fed back like that the
  value has to be searched for: `94.2477036f` is the only float whose
  product with the rads-to-RPM constant is exactly 900.0f, and both
  neighbours land an ulp away.
* **A mutation nothing reaches is not covered by the scenario next to
  it.** Two of `DriveTrain`'s survivors were in the crossover search,
  which only does work when the torque curve falls hard past its peak --
  every fixture engine crossed over on the first probe or not at all, so
  the search's own branches never ran. Two extra engines, a steep curve
  and an all-zero one for the single case where two sides can be equal,
  killed both. Check that the *shape* of the fixture data exercises the
  loop before concluding the loop is equivalent.
* **Reaching the branch is not enough -- the difference has to land
  somewhere the dump prints.** Every survivor up to `DriveTarget` meant
  the fixture never got to the code. Two of `DriveTarget`'s got to it
  exactly, took different paths, and printed the same numbers.
  `bl-window-inclusive` gives `BlendWithCurrentAcceleration` one extra
  pass, but that pass blends at a weight which clamps to 1 and so moves
  x and y not at all, and z, the pad and `CalculatedSpeed` were zero on
  both sides -- until the fixture's points are given a z of 3, which
  `SetPoint3` zeroes whatever the blend is. `rs-inner-test-strict` needs
  `travelled == len[k]` exactly *and* `fadd(P[k], fsub(P[k+1], P[k])) !=
  P[k+1]` at the same k, because the two arms otherwise emit the same
  point; the separation goes in the pad, where `16777218 - 1` and
  `1 + 16777216` are both round-half-to-even ties landing on 16777216.
  So a survivor has two causes, not one, and the second is harder to
  see: the fixture's comment says it is on the boundary and the comment
  is right.
* **Check which float of a fixture helper you are writing.**
  `dt_point(t, i, x, y, z, speed, route, rpn, dl)`'s fourth float is the
  `CalculatedSpeed`, and the helper writes 0.0 into every pad by design.
  A kill built entirely around a pad value went into the speed column
  instead and the mutation survived a fixture aimed straight at it. The
  dump said so -- the number was sitting in `s`, with `0` in the pad --
  which is the argument for a dump that prints **every** field rather
  than the interesting ones.
* **An explicit alignment pad cannot be checked by deleting it.** A
  `uint8_t _pad[2]` in front of a pointer is reinstated by the ABI the
  moment it is removed: every following offset, and `sizeof`, come out
  unchanged and the layout assert passes. What pins the field after it is
  the `offsetof` in the assert. Do not read "the pad mutation survived" as
  a coverage hole.
* **A guard can be protecting the read rather than the number.**
  `Table::GetValue` returns `pTable[i]` outright when `i == last`. Delete
  that and the interpolation computes
  `pTable[last] + (pTable[last + 1] - pTable[last]) * 0.0`, because the
  weight is exactly zero there -- the same number, off the back of a load
  one element past the end of the array. A transcript cannot see it and a
  sanitiser build would.
* **An array's extent is part of the layout claim, and offsets do not pin
  it.** Shrink an array, pad behind it, and every following offset *and*
  the total size are unchanged -- the static assert passes. Nine
  CarTypeInfo mutations and one Steering mutation exploited exactly that.
  Print `sizeof` of each array, the element stride, and a width and
  signedness probe per field.
* **A layout is not checked until the ARM build compiles it.** The host
  harness cross-checks *arithmetic*; it is not the target and its structs
  are not the target's. `wheel.h`'s assert was wrapped in
  `#if __SIZEOF_POINTER__ == 4`, so neither toolchain ever compiled it, and
  when `tools/build_cia.ps1` finally did it failed. This port's `bVector4`
  is four-byte aligned where the PS2's was a sixteen-byte quadword, so a
  four-byte gap the PS2 record has before `Wheel::WorldGroundForce` did not
  appear and the handheld's record came out 396 bytes instead of 400. On the
  64-bit host the pointer widening cancelled the gap exactly, so the model
  and the harness agreed on the wrong record. Never guard a layout assert
  with a host test that makes it vanish on the host, and run the ARM build
  before calling a slice with a record in it done.
* **The vtable pointer is at the END of the object in this image.** Old
  g++ ABI. `CarState` has none, `CarDriver`'s is at 556, `Steering`'s at
  8, and every class still to come in task 25 is the same. Looking for it
  at offset 0 will shift every field by four.

* **The emulator harnesses are slow and flaky for a reason that is ours.**
  Once the boot flow's idle timer expires, `bgf_consider_start_demo_mode()`
  traces every frame, because the port's `startDemoMode` hook is a stub that
  never changes state. Two SD writes a frame slows the emulated app enough
  that most `PostMessage` key presses fall inside a single frame and are
  never scanned -- which looks exactly like a dead key binding.
  `run_azahar_scroll.ps1` presses SELECT up to 40 times to get past it. The
  fix belongs in `gameflow.c`, whose transcript `bootflow_check.py` diffs, so
  the Python reference has to move with it.

  It also makes `run_azahar_test.ps1` flaky: two PARTIALs in a row, with
  *different* failure modes, then three PASSes in a row once the machine was
  quiet -- including one at `0a58704` to rule out a regression. Re-run a
  PARTIAL once before believing it; the same failure mode twice is real.
* **A scroll offset is in the *padded* texture's space.** The original
  divides its UVs by the power-of-two allocation and only then adds the
  offset, so a citro3d caller adds it after converting pixels to UVs -- and
  T's sign flips, because `subtex_from_pixels` has already flipped the axis.
* **A passing cross-check does not mean the decoder is right.** Session 15
  found two decoder bugs `geometry_check.py` had been passing for four
  sessions, one of them in a field the digest explicitly covers. Both
  implementations were wrong the same way, because the C was written from a
  document that was written from the Python. Independence has to reach back
  to the disc or the ELF -- and look at the output on the emulator too.
* **ST is mirrored two vertices to a quad**, `(S_even, T_even, T_odd,
  S_odd)`, not transposed like XYZ. The cheap check is the S==T rate: 44.43%
  if you have it wrong, 1.68% if you have it right.
* **Skip `0x11` chunk filler a whole entry at a time on `0x00034006` and
  `0x0003401d`.** A byte scan eats the first byte of a table whose first hash
  ends in `0x11` (`TS50_C`: `0x4342fd11`) and shifts every hash in that solid
  by 8 bits, silently. The byte scan is still correct for the header, the
  entry table and the packet blob, checked against their sizes on all 1,461
  solids.
* **The game's T counts down from the image's top row.** A citro3d renderer
  over `texpack_upload` needs `v = 1 - T * scale`; `uirender.c`'s
  `subtex_from_pixels` is the hardware-verified precedent.
* **58 of the 132 texture hashes car geometry refers to are in no pack on the
  disc** -- 9.0% of strips. That is the data, not a bug to chase. Draw those
  strips untextured, the same path the `TextureNumber >= NumTextures`
  sentinel takes.
* **`eSolid.NumTextureTableEntries` (0xAC) is zero on all solids.** Count the
  `0x00034006` chunk instead; `geometry.c` does. `NumLightMaterials` at 0xAE
  is fine.
* **`eSolid.NumPolys` is stale** for 19 of the 1,465 solids. The per-strip
  counts are the truth.
* **`eStripEntry.TextureNumber` can be one past the end** -- 25 strips do
  that, and it means untextured. Range-check it.
* **Normals are 125..127, not 126..127**, and 53 across the car set are
  exactly zero. A zero normal is not the same as "this strip has no normal
  field" (about 17% of strips); check `hasNormals`.
* **`TRACKS\TRACKA12.BUN` has no solid list.** All 1,135 track solids are in
  B12.
* **The GS had no hardware backface culling** -- the VU did it in software,
  and nothing in the data forces a consistent winding. `georender_draw` uses
  `GPU_CULL_NONE` deliberately. Do not "fix" that without evidence from the
  normals.
* **`C2D_CreateScreenTarget` gives no depth buffer**, and `C3D_DepthTest`
  against no depth buffer silently does nothing. `main.c` builds the top
  target with `C3D_RenderTargetCreate(240, 400, GPU_RB_RGBA8,
  GPU_RB_DEPTH24_STENCIL8)` instead.
* **Azahar's X button is `Z` (0x5A) and its Y is `X` (0x58).**
  `%APPDATA%\Azahar\config\qt-config.ini` is the authority; guessing from the
  letter costs a wasted run that looks like a code bug.
* **A screenshot harness must not sleep.** A *faster* boot moves the
  keypresses earlier, not later, and the shot lands on the wrong screen.
  `main.c` logs its mode on every SELECT and `tools/run_azahar_geo.ps1`
  presses-and-confirms against the log.
* **`.gitattributes` / `core.autocrlf=true`**: there is no `.gitattributes`,
  and **every blob in the repo is LF** -- git normalises on commit, so line
  endings never show up in a diff and never need fixing for git's sake. What
  differs is the *working tree*, and the previous note here had it backwards.
  Measured: `TASKS.md`, `HANDOFF.md`, `CONTINUE.md`, every `.c`/`.h` under
  `3DS Files/source/` and `tools/geometry_convert.py` are **CRLF**;
  `tools/*.py` (all the others), `tools/src/*.c`, `README.md` and everything
  under `docs/` are **LF**. Match the neighbour when adding a file, and read
  and write with an explicit newline rather than letting a tool normalise
  one -- not because git minds, but because a whole-file rewrite buries the
  change you actually made when someone reads the working tree.
* **A multi-line mutation pattern written with bare newlines misses a
  CRLF source silently, and "not found" is not "survived".** `core.autocrlf`
  is `true` with no `.gitattributes`, so a checked-out ported source is CRLF
  while one a patch script wrote in place is LF -- the tree is a real mix,
  51 files under `3DS Files/source/` are LF today. A pattern that misses
  prints `PATTERN NOT FOUND` and is then dropped from the denominator, so
  the tally line still reads clean. It is not even stable: `cardriver` was
  honestly measured at 48/48 when its two files happened to be LF, and
  reported 32/32 later with the checker unchanged. **Every runner now
  detects the file's own newline and translates the pattern**; where a
  runner instead read with universal newlines (`camera`, `trackroute`) it
  was rewriting each file it touched from CRLF to LF and leaving it that
  way, so those read with `newline=""` now too. Check the `NOT FOUND` count,
  not just the last line.
* **A checker mutates the file it owns.** When `drivetarget_assign` moved
  out of `cardriver.c`, its three mutations went with it rather than being
  retargeted across the file boundary -- `drivetarget_check` already had
  them. `cardriver_check` is 45 mutations now, not 48, and 45 is the honest
  number.
* **A forward-ported helper in a neighbour's file is a link edge that
  breaks when its real file arrives.** `drivetarget_assign` sat at the top
  of `cardriver.c` for two slices because `SetDriveTarget` tail-calls it
  and DriveTarget had no `.c` yet. Moving it home broke
  `cardriver_check.py`'s link, and the checker that broke was not the one
  being worked on. **Run the whole checker list before calling a slice
  done, not just the new one.** The second failure was `WorldTimer`, which
  `engine.c` owns: harnesses define their own tick rather than linking
  Engine, Table, CarTypeInfo and Wheel behind it.
* **A mutation runner's restore is the one write that must not fail
  quietly.** These sources sit under OneDrive, and a write to a file the
  sync client has open comes back `OSError: [Errno 22] Invalid argument`.
  It is transient, but when the failing write is the **restore** in the
  `finally`, the pass dies with the tree still holding the mutation, and
  the traceback says only that a write failed. The next clean run then
  disagrees with the model for a reason nothing in the diff explains.
  All twelve mutation runners now retry the write five times and, if the
  original truly cannot go back, `sys.exit` naming the file and the
  mutation rather than letting the numbers that follow describe a source
  nobody meant to write. That is the second repo-wide hole in the
  runners found by a mutation happening to trigger it; the first was the
  missing `timeout=`. **When a checker disagrees for no visible reason,
  check `git diff` on the ported source before debugging the model.**
* **Checkers must not pipe harness stdout.** `subprocess.run` with
  `capture_output=True` deadlocks against a runaway child, and `timeout=`
  cannot rescue it because killing a cygwin-built exe from Windows does not
  reliably close its handles. `geometry_check.py` writes to a file and caps
  the line count; the older checkers still use a pipe and have the same
  latent problem.

## PICA200 notes

* At most **one uniform per instruction**, and only in the **first** source
  slot. `dp3 r3, r2, lightVec` is rejected; `dp3 r3, lightVec, r2` is fine.
* `mad` cannot take a uniform in either slot it leaves over. Spell
  ambient-plus-diffuse as `mul` then `add`.
* A `GPU_BYTE`/`GPU_UNSIGNED_BYTE` attribute is **not** normalised on its way
  in -- it arrives as the plain integer, so scaling is the shader's job.
  Leave an RGBA8 colour unscaled and the whole model saturates to white.
* It is `Mtx_Identity`, not `C3D_Mtx_Identity`.
* `.v.pica` files are already handled by the Makefile -- they compile
  straight to `.shbin.o` plus a `_shbin.h`, no extra target needed.

## Carried over, still open

* **TRACKB45 at 15-20 FPS on Azahar (Session 52).** 45-50 ms of CPU
  draw: about 550 models in view (15 ms) and eight cars close up at LOD 0
  (17 ms), about 1,194 batches. For the speed work.
* **The main heap is short on the big tracks (Session 52):** 1.5 to
  3.4 MB free with traffic. bMalloc aborts on a failure, so move big
  buffers that can live in linear memory there.

* **The half-texel UV inset.** `RenderSingleFlailerBitmap` insets every
  corner by half a texel of the padded size before adding the scroll offset;
  the port does not. It touches all 397 textures in `FRONTB.BUN` rather than
  the two that scroll, so it wants its own verification pass.
* **`bui.c`'s eight setters are not cross-checked.** `bui_check.py` covers
  the parse path only.
* **No alpha blending on geometry.** Glass draws opaque. It is not vertex
  alpha -- all 212,408 car vertex colours have the alpha bit set -- so it is
  texture alpha plus a GS blend mode, and the blend state has not been
  recovered from the ELF. Strip `Flags` high bytes seen: `0x4100` on body,
  `0xc100` on the unresolved textures, `0x5000`, `0x0c00`, `0x0000`.
* **Car part transforms** are not decoded, so wheels, mirrors and wipers all
  sit at the origin. `geoview` steps solids one at a time rather than imply
  otherwise. Needed before a car can be driven.
* 58 unresolved texture hashes; only `0xece04847` = `WIPER01` named so far.
