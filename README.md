# Need for Speed: Hot Pursuit 2 for the New 3DS

An unofficial homebrew port of the PS2 version of **Need for Speed: Hot
Pursuit 2** to the New Nintendo 3DS. It is the PS2 game itself, not a
remake: its code was reverse-engineered from the retail disc and
reimplemented in C, function by function, and checked against the disc's
own code. It plays from your own disc's files, which you copy to the SD
card. No game data comes with it.

What you get is the PS2 game: Hot Pursuit and World Racing, Quick Race,
You're The Cop, the challenges and the career, the cops and the
helicopter, the replays, the EA TRAX jukebox, every car and track, the
saves, and the PS2's cheat codes. The top screen shows the race and the
bottom screen the map and the standings. On top of that, Local Wireless
races up to eight New 3DS consoles against each other.

## What you need

- A **New 3DS, New 3DS XL or New 2DS XL** with custom firmware (Luma3DS)
  and FBI. An Old 3DS or 2DS shows a message at boot and stops: it has too
  little memory and a third of the speed.
- **Your own PS2 disc** of Need for Speed: Hot Pursuit 2. The port was
  made from the European disc (SLES-50731); other discs are untested.
- About **2.9 GB** free on the SD card.
- A computer with **Python 3.8 or newer** (nothing else to install) and
  about 7 GB free for the steps below.

## Installing

1. In this repository's top folder, make a `PS2 Files/Full Game/` folder
   and copy `ZDIR.BIN` and `ZZDATA.BIN` from the root of your disc into
   it. Run the commands below from the top folder too.
2. Extract the disc's files into `extracted-retail/` (3.3 GB, a minute or
   two):

   ```
   python tools/zdir_extract.py --retail --decompress
   ```

3. Turn the sound banks into the 3DS's format:

   ```
   python tools/audio_pack.py extracted-retail/SOUND extracted-retail/SOUND
   ```

4. Copy the files the game reads to the SD card, here with the card in
   your computer as `E:`:

   ```
   python tools/make_card.py E:\
   ```

   That makes `E:\NFSHP2` (2.9 GB), so that
   `sdmc:/NFSHP2/GLOBAL/GLOBALB.BUN` exists. Give it a folder instead
   and it makes the `NFSHP2` folder there, for you to copy to the card's
   root. Don't copy `extracted-retail/` over as it is: it holds the
   tracks a second time, packed, and the game would load those.
5. Install `NFSHP2-3DS.cia` with FBI and start it from the HOME Menu. The
   `.3dsx` runs from the Homebrew Launcher as well, but the CIA is what has
   been tested on hardware.

Saves go to `sdmc:/NFSHP2/SAVES`, made the first time the game saves. A
screen that changes your save asks whether to save when you leave it.

## Controls

### In a race

| Key | Racer | You're The Cop |
| --- | --- | --- |
| Circle Pad, D-pad Left / Right | steer | steer |
| A | gas | gas |
| B | brake and reverse | brake and reverse |
| X | horn | change the target |
| Y | change the camera | change the camera |
| L | look back | call a roadblock |
| R | handbrake | call the helicopter |
| ZL | shift down | nitro |
| ZR | shift up | shift up |
| D-pad Down | | shift down |
| D-pad Up | change the HUD | change the HUD |
| C-Stick up / down | gas / brake | gas / brake |
| START | pause | pause |

With the automatic gearbox, shift down is Zone Freeze and shift up Zone
Preview; Y held with either does the same with the manual gearbox, as on
the PS2. The keys in the table can be changed in Options, Controller,
for the racer and the cop separately; steering, the C-Stick and START
stay where they are.

### In the menus

The D-pad or the Circle Pad moves, A selects, B goes back and Y shows the
help. In the pause menu and on the screens at a race's end, X goes back
instead of B, as the PS2's Triangle does there.

## Local Wireless

Local Wireless on the main menu races two to eight New 3DS consoles. Each
needs the game and the disc's files on its own SD card. One console hosts
and picks the race; the others join it. The host can fill the grid with
CPU racers.

## Cheat codes

The PS2 game's cheat codes are entered on the main menu: press the eight
keys in order and the menu says "Unlocked" and what. On the main menu L,
ZL, R and ZR are the PS2's L1, L2, R1 and R2, X is Square and B is
Triangle.

A car, track or bonus-event code stays on until you switch the game off.
A picture code (Motion Blur, Black & White, Heavy Fog, R/C Car, Video
Mode, Chrome Cars) lasts the next race, and only one at a time works.
Nothing is saved.

### Picture and bonus codes

| Unlocks | 3DS keys |
| --- | --- |
| Motion Blur | ZL, L, R, X, R, R, R, L |
| Black & White | R, L, D-pad Left, B, D-pad Left, D-pad Left, D-pad Left, L |
| Heavy Fog | B, X, D-pad Right, ZR, D-pad Right, D-pad Right, D-pad Right, X |
| R/C Car | D-pad Right, B, L, R, L, L, L, B |
| Video Mode | L, R, D-pad Right, X, D-pad Right, D-pad Right, D-pad Right, R |
| Championship Bonus Event | L, X, ZR, ZR, ZR, R, L, X |
| Ultimate Racer Bonus Event | D-pad Right, X, D-pad Left, D-pad Left, D-pad Left, ZR, D-pad Right, X |
| Chrome Cars | ZL, ZR, D-pad Left, X, D-pad Left, D-pad Left, D-pad Left, ZR |

### Cars

| Unlocks | 3DS keys |
| --- | --- |
| McLaren F1 | B, L, B, L, R, D-pad Left, R, D-pad Left |
| McLaren F1: NFS | D-pad Left, B, B, B, ZL, X, X, B |
| McLaren F1 LM | X, L, X, L, B, D-pad Right, B, D-pad Right |
| McLaren F1 LM: NFS | R, X, X, X, ZR, D-pad Left, D-pad Left, X |
| Mercedes CLK-GTR | ZR, R, ZR, R, D-pad Left, B, D-pad Left, B |
| Mercedes CLK-GTR: NFS | B, D-pad Left, D-pad Left, D-pad Left, L, ZL, ZL, D-pad Left |
| Chevrolet Corvette Z06 | D-pad Left, ZR, D-pad Left, ZR, L, R, L, R |
| Chevrolet Corvette: NFS | X, D-pad Right, D-pad Right, D-pad Right, ZR, R, R, D-pad Right |
| Dodge Viper GTS: NFS | L, ZL, ZL, ZL, D-pad Right, B, B, ZL |
| Ferrari F50 | L, B, L, B, D-pad Right, ZL, D-pad Right, ZL |
| Ferrari F50: NFS | B, L, L, L, D-pad Left, D-pad Right, D-pad Right, L |
| Lamborghini Diablo 6.0 VT | D-pad Right, ZR, D-pad Right, ZR, R, L, R, L |
| Lamborghini Diablo: NFS | X, ZR, ZR, ZR, B, R, R, ZR |
| Lamborghini Murcielago | R, ZL, R, ZL, L, D-pad Right, L, D-pad Right |
| Lamborghini Murcielago: NFS | L, ZR, ZR, ZR, D-pad Left, X, X, ZR |
| Porsche 911 Turbo: NFS | D-pad Right, D-pad Left, D-pad Left, D-pad Left, B, R, R, D-pad Left |
| Porsche Carrera GT | D-pad Left, D-pad Right, D-pad Left, D-pad Right, R, ZR, R, ZR |
| Porsche Carrera GT: NFS | ZR, B, B, B, R, X, X, B |
| Aston Martin V12 Vanquish | ZR, D-pad Right, ZR, D-pad Right, B, D-pad Left, B, D-pad Left |
| V12 Vanquish: NFS | X, D-pad Left, D-pad Left, D-pad Left, R, ZR, ZR, D-pad Left |
| BMW Z8 | X, D-pad Right, X, D-pad Right, ZR, B, ZR, B |
| Ferrari 360 Challenge | D-pad Left, X, X, X, R, ZL, ZL, X |
| Ferrari 360 Spider | ZR, X, ZR, X, B, ZL, B, ZL |
| Ferrari 550 Barchetta | L, X, L, X, D-pad Right, R, D-pad Right, R |
| Ferrari 550 Barchetta: NFS | X, R, R, R, ZR, D-pad Left, D-pad Left, R |
| Mustang Cobra R: NFS | R, D-pad Right, D-pad Right, D-pad Right, D-pad Left, ZR, ZR, D-pad Right |
| HSV Coupe GTS | L, ZL, L, ZL, R, B, R, B |
| HSV Coupe GTS: NFS | D-pad Right, ZL, ZL, ZL, L, D-pad Left, D-pad Left, ZL |
| Jaguar XKR: NFS | L, D-pad Right, D-pad Right, D-pad Right, ZL, R, R, D-pad Right |
| Ford TS50 | D-pad Right, D-pad Left, D-pad Right, D-pad Left, ZR, X, ZR, X |
| Ford TS50: NFS | D-pad Right, L, L, L, R, D-pad Left, D-pad Left, L |
| Lotus Elise | B, ZR, B, ZR, D-pad Left, X, D-pad Left, X |
| Lotus Elise: NFS | X, L, L, L, ZR, ZL, ZL, L |
| Mercedes CL55 AMG | L, D-pad Right, L, D-pad Right, ZL, X, ZL, X |
| Mercedes CL55 AMG: NFS | B, ZR, ZR, ZR, R, L, L, ZR |
| Opel Speedster: NFS | ZL, ZR, ZR, ZR, X, D-pad Left, D-pad Left, ZL |
| Vauxhall VX220: NFS | L, R, R, R, D-pad Left, D-pad Right, D-pad Right, L |
| Pursuit Corvette Z06 in all Challenge Modes | ZL, ZR, ZR, ZL, B, D-pad Right, B, D-pad Right |
| Pursuit Murcielago in all Challenge Modes | R, L, L, R, D-pad Right, ZR, D-pad Right, ZR |
| Pursuit Mustang Cobra R in all Challenge Modes | D-pad Left, X, D-pad Left, X, ZR, R, ZR, R |
| Pursuit M5 in all Challenge Modes | X, B, B, X, D-pad Left, R, D-pad Left, R |
| Pursuit Crown Victoria in all Challenge Modes | D-pad Right, D-pad Left, D-pad Left, D-pad Right, X, B, X, B |

### Cop cars in You're The Cop

| Unlocks | 3DS keys |
| --- | --- |
| Pursuit Corvette Z06 in You're The Cop Mode | ZR, L, L, ZR, R, D-pad Right, D-pad Right, R |
| Pursuit Murcielago in You're The Cop Mode | D-pad Right, ZL, ZL, D-pad Right, X, D-pad Left, D-pad Left, X |
| Pursuit Mustang Cobra R in You're The Cop Mode | D-pad Left, B, B, D-pad Left, R, ZR, ZR, R |
| Pursuit M5 in You're The Cop Mode | B, X, X, B, L, R, R, L |

### Tracks

| Unlocks | 3DS keys |
| --- | --- |
| Coastal Parklands II | ZR, ZR, D-pad Left, D-pad Left, D-pad Left, ZR, R, L |
| National Forest | X, X, ZL, ZL, R, R, D-pad Left, D-pad Left |
| National Forest II | D-pad Left, D-pad Left, L, L, L, D-pad Left, D-pad Right, X |
| Scenic Drive II | ZL, ZL, L, L, L, ZL, B, X |
| Desert Heat II | R, R, ZR, ZR, ZR, R, L, D-pad Left |
| Outback | B, B, D-pad Right, D-pad Right, L, L, R, R |
| Outback II | L, L, B, B, B, L, X, D-pad Right |
| Rocky Canyons | R, R, D-pad Left, D-pad Left, X, X, D-pad Right, D-pad Right |
| Rocky Canyons II | X, X, B, B, B, X, L, D-pad Left |
| Ancient Ruins II | D-pad Right, D-pad Right, D-pad Left, D-pad Left, D-pad Left, D-pad Right, L, X |
| Calypso Coast | ZR, ZR, R, R, L, L, B, B |
| Calypso Coast II | B, B, D-pad Right, D-pad Right, D-pad Right, B, X, L |
| Mediterranean Paradise II | X, X, D-pad Right, D-pad Right, D-pad Right, X, D-pad Left, ZL |
| Fall Winds II | ZR, ZR, X, X, X, ZR, D-pad Left, R |
| Alpine Trail | X, X, B, B, D-pad Left, D-pad Left, ZL, ZL |
| Alpine Trail II | D-pad Left, D-pad Left, ZR, ZR, ZR, D-pad Left, R, X |
| Autumn Crossing | D-pad Right, D-pad Right, B, B, R, R, D-pad Left, D-pad Left |
| Autumn Crossing II | R, R, D-pad Right, D-pad Right, D-pad Right, R, ZR, B |
| Island Outskirts II | ZL, ZL, R, R, R, ZL, D-pad Left, ZR |
| Palm City Island | D-pad Left, D-pad Left, R, R, D-pad Right, D-pad Right, X, X |
| Palm City Island II | D-pad Right, D-pad Right, ZR, ZR, ZR, D-pad Right, R, D-pad Left |
| Tropical Circuit | ZR, ZR, B, B, D-pad Right, D-pad Right, R, R |
| Tropical Circuit II | L, L, D-pad Right, D-pad Right, D-pad Right, L, X, ZR |

The PS2 game's Pet Helicopter code has no keys on the disc, so nothing
can enter it. `docs/formats/easter-eggs.md` has every code with its PS2
buttons too.

## The config file

`sdmc:/nfshp2_config.txt` is optional. Each line is a name and a number,
and a line the game doesn't know does nothing. The ones a player might
want:

| Line | What it does |
| --- | --- |
| `DebugLog 1` | writes `sdmc:/nfshp2_debug.txt`, for a bug report |
| `PauseLog 1` | keeps the last 3 seconds of a race and writes `sdmc:/nfshp2_pause_N.bin` when you pause, for a graphics bug |
| `FallLog 1` | with `DebugLog 1`, logs your car's collisions every frame, for a car that falls through the road |
| `DemoReplays 1` | lets attract mode start the disc's demo replays (on the 3DS they leave the PS2's path after one frame and end, so they are off by default) |
| `DemoReplayDrift 1` | with `DemoReplays 1` and `DebugLog 1`, a demo replay plays on past that point, and the log counts the frames that left the path |
| `DemoReplayFile N` | with `DemoReplays 1`, attract mode plays the disc's replay file N (1 to 6) each time, where the game would pick one by chance |
| `EggCodes N` | turns cheat codes on at boot by N's bits, as entering them does: 1 Motion Blur, 2 Black & White, 4 Heavy Fog, 8 R/C Car, 16 Video Mode, 256 Chrome Cars |

## Known issues

- On Ancient Ruins, at the curb turn by the cones, the road can vanish
  for a frame or two.
- The frame rate drops below 30 in the heaviest places: the fire on
  Coastal Parklands, the end of Desert Heat, and by some roadblocks.
- R/C Car shrinks the cars, but not with the PS2's big-headed driver.
- The PS2's two-player split screen is left out; Local Wireless takes
  its place. There is no rumble.

## Building from source

Requires devkitPro's 3DS tools (`DEVKITPRO` and `DEVKITARM` set up). In
PowerShell:

```powershell
& .\tools\build_cia.ps1
```

It works around the space in the path and produces
`3DS Files/NFSHP2-3DS.3dsx` and `.cia`.

- `3DS Files/` -- the devkitARM project.
- `tools/` -- the Python reverse-engineering and data tools, and the
  vendored `makerom` and `bannertool`. The `*_check.py` scripts run the
  disc's own code in a MIPS emulator (`tools/mipsemu.py`) beside the
  port's, and their `--mutate` passes break the port on purpose to show
  that the check notices.
- `docs/formats/` -- write-ups of every file format and system.
- `HANDOFF.md` -- the session-by-session engineering log.
- `TASKS.md` -- the numbered task list.
- `PS2 Files/` -- your own disc's files, never in the repository.

## About

A fan project, not made, endorsed or supported by Electronic Arts.
Need for Speed and Hot Pursuit 2 are Electronic Arts' trademarks. The
repository holds no game data: the port runs only with files from a disc
you own. The CIA's HOME Menu icon, banner and siren are made from the
disc's files when it is built.

## License

The port's own code is under the GNU General Public License, version 3
(`LICENSE`). It covers the code alone: the game, its data and its art
stay Electronic Arts'. The vendored `makerom` and `bannertool` keep their
own licenses.
