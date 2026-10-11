# The race-over overlay's message

When a player's race is over, the HUD's RACE_OVER feature comes on
([hud-features.md](hud-features.md)), with one message in the middle of
the top screen, such as "You finished in 1st place!". SetHudFeatures calls
`Player::FillInRaceOverMessages` when the bit turns on. That function
picks the message from the race's type and how the player's car finished,
and word-wraps it into group `0xc707e093` of the player's HUD screen.

The code is retail's Player.obj (`0x00181498` to `0x001818c4`) and the
word wrap in FEFlailer.obj (`0x00144a68` to `0x00144e24`). Slice RE-2c
ported them in `3DS Files/source/raceovermsg.c` and
`3DS Files/source/flailerwrap.c`.

| Function | Address | Size |
|---|---:|---:|
| `FormatFinishPositionForRaceOverOverlay(char *, int, int)` | `0x00181498` | 100 |
| `FormatTimeForRaceOverOverlay(char *, Timer &, int)` | `0x00181500` | 88 |
| `Player::FillInRaceOverMessages()` | `0x00181558` | 876 |
| `isspace(int)` | `0x00144a68` | 44 |
| `WriteTextIntoChunk(FlailerTextChunk *, char *, char *)` | `0x00144ae8` | 112 |
| `RenderTextIntoGroup(int, int, char *)` | `0x00144ba0` | 644 |

## FillInRaceOverMessages, `0x00181558`

The function reads these from the player's car's RacingCar
(`p->MyCar->pRacingCar`):

- the place, `FinishingOrder` (`+12`, a signed byte);
- the reason, `FinishReason` (`+18`, a short): 1 NORMAL_COMPLETION,
  2 ARRESTED, 3 KNOCKED_OUT, 4 BE_THE_COP_WON, 5 BE_THE_COP_LOST;
- the best lap, a copy of `*GetBestLapTime()`, which is
  `BestRunningTimes` (`+96`) at Race's `FinishLineBoundaryNumber`
  (`+1619`);
- the race's time, `RaceTime` (`+180`).

It then switches on `TheRaceParameters.RaceType` through the jump table
at `0x002b3fc0`. The message is built in a 128-byte buffer at `sp+0`.

| RaceType | Reason | Message |
|---|---|---|
| 2 TIME_TRIAL | ARRESTED, best lap valid | 59012 with the best lap |
| | ARRESTED, no best lap | 59013 |
| | NORMAL_COMPLETION | 59015 with the best lap |
| | other | none |
| 4 RACE_KNOCKOUT | ARRESTED | 59011 |
| | KNOCKED_OUT, or place = `NumRacingCars` | 59018 with the place; speech 0 |
| | other, `NumRacingCars` 3 or more | 59017 with the place; speech 1 |
| | other, fewer cars | 59010 with the place; speech 1 |
| 3 LAP_KNOCKOUT | ARRESTED | 59011 |
| | KNOCKED_OUT | 59019 with the place; speech 0 |
| | other | 59010 with the place |
| 1 SINGLE_RACE, 5 TOURNAMENT | BeACop set | You're The Cop's, below |
| | race event of type 5 (POINT2POINT), ARRESTED | 59014 |
| | race event of type 5, NORMAL_COMPLETION | 59016 with the race's time |
| | race event of type 5, other | none |
| | otherwise, ARRESTED | 59011, through the place's format |
| | otherwise, other | 59010 with the place |
| 0, or 6 and up | any | none |

"Race event" means `UseTheRaceEvent(&Fred)` (`0x001841a8`) answers true
and `TheRaceEventFields.Type` (`+106`) is 5. "Speech" is
`MaybeDoKnockoutRaceOverSpeech(Player *, bool)` (`0x00207018`); 1 means
the player goes on to the next race.

You're The Cop's message comes from `RacingCar::GetPlayer`:

- With one player car, BE_THE_COP_WON gives 59020. Any other reason gives
  59022.
- With two, player 0 gets 59024 for WON. For LOST, it gets 59023 if
  player 1's car also lost, and 59025 otherwise.
- Player 1 gets 59026 for WON or NORMAL_COMPLETION. For LOST, it gets
  59023 if player 0's car also lost, and 59027 otherwise.
- Any other count, player number or reason has no message.

"Also lost" reads `PlayerPlayersByNumber[n]->MyCar->pRacingCar->
FinishReason`.

A plain message (no `%s`) goes through `bSPrintf(buf, string)` with
nothing to put in. A message with no case renders whatever the buffer
held on the stack.

The buffer then goes to `RenderTextIntoGroup(p->HudScreenHash (+772),
0xc707e093, buf)`. Its answer is dropped.

### The strings

English, from `LANGUAGES/FE_ENGLISH.BIN`. An `@` breaks the line.

| ID | Text |
|---:|---|
| 59010 | You finished in %s place! |
| 59011 | You were arrested! |
| 59012 | You were arrested!@You recorded a lap time of %s |
| 59013 | You were arrested!@You didn't record a lap time. |
| 59014 | You were arrested!@You didn't get to the finish. |
| 59015 | You recorded a lap time of %s |
| 59016 | You recorded a time of %s |
| 59017 | You finished in %s place.@You advance to the next race! |
| 59018 | You finished in %s place.@You were knocked out! |
| 59019 | You were knocked out!@You finish in %s place! |
| 59020 | You arrested all of the racers! |
| 59022 | You failed to fill@your ticket quota! |
| 59023 | Out of time! |
| 59024, 59026 | You win! |
| 59025, 59027 | You lose! |

59021, "You arrested all of the racers in %s", is never used. No plain
message has a `%` in any language. The longest string is German's 59017,
at 73 characters.

### The place, `0x00181498`

`FormatFinishPositionForRaceOverOverlay(buf, place, id)` is
`bSPrintf(buf, GetTranslatedString(id), GetTranslatedString(table[place]))`.
The table at `0x002fc028` holds nine IDs:

| Place | ID | English |
|---:|---:|---|
| 0 | 321001 | 0th |
| 1 | 61009 | 1st |
| 2 to 8 | 321003 to 321009 | 2nd to 8th |

Place 1 uses 61009, not 321002, which has the same text.

### The time, `0x00181500`

`FormatTimeForRaceOverOverlay(buf, t, id)` prints the time into a 32-byte
buffer with `Timer::PrintToString(char *, float, int)` (`0x001a3ca0`).
That is RoundSeconds by `0.01` (gp-30248), then SetTime and
`PrintToString(char *, int)` with flags 0 in the current language. Then it
runs `bSPrintf(buf, GetTranslatedString(id), time)`.

## RenderTextIntoGroup, `0x00144ba0`

This is the Flailer copy of the frontend popup's word wrap
([boot-flow.md](boot-flow.md), `bpopup.c`). It works on the HUD's Flailer
chunks, not BUI objects.

1. It collects the group's text objects with `FindFlailerObjectByGroup(
   screen, group, 2, prev)`, up to 32 (`slti 32`), into an array on the
   stack. With none it returns 0.
2. It walks the string while there is one:
   - A space, tab, NUL (`isspace`, `0x00144a68`) or `@` marks a break at
     that character.
   - Before the first break, every character counts.
   - After it, the line takes another character while its count is under
     `MaxChars - 2` (`+84`) and the character is not `@`.
   - Otherwise the line from its start to the last break goes into the
     current object. The next object starts after the break; the loop's
     own step skips that character unexamined. If there is no next
     object, the function returns 0.
3. The rest of the string goes into the current object.
4. The answer comes from `chunks[next]`, or `chunks[next - 1]` when that
   is NULL: its `Y` (`+52`) plus `GetScaledHeight`, truncated to an int.
5. Every object from `next` on has its visibility byte (`+41`) cleared
   directly (`sb zero`), not through SetVisibility.

`WriteTextIntoChunk` (`0x00144ae8`) zeroes a 256-byte buffer, copies the
line in, then calls `SetVisibility(1)` and `SetString`.

So the line is cut late: a word longer than the line runs past
`MaxChars`. An `@` always cuts, and `@ @` makes a blank line.

## The port

`player_fill_in_race_over_messages` is bound to
`gPlayerFillInRaceOverMessagesFn` in main.c, so playerhud.c's
SetHudFeatures runs it. The two seams are:

- `gRaceOverTranslateFn`, GetTranslatedString. main.c's `raceOverTranslate`
  copies into its own 256-byte buffer, because `fredTranslate`'s 64 bytes
  would cut German's 59017. The place helper copies the format out
  before it asks for the place's word, since the seam's answer need not
  outlast the next call.
- `gMaybeDoKnockoutRaceOverSpeechFn`, which stays NULL until 14-10c.

`timer_print_to_string_rounded` in `timer.c` is
`PrintToString(char *, float, int)`.

The port departs from retail in a few guarded cases:

- **No message.** Retail renders its stack's leftovers; the port renders
  "", which hides every object but the first.
- **Place outside 0 to 8.** Retail reads past the table; the port puts ""
  in.
- **You're The Cop's other player.** Retail reads through
  `PlayerPlayersByNumber` unchecked. The port takes a missing player, car
  or RacingCar as not lost. A missing player for the car itself gives no
  message.
- **A line over 255 bytes.** Retail's bMemCpy has no bound; the port
  stops at 255. No line on the disc is that long.
- **A 33rd object.** Retail's array is 32 words, and the one past it is
  the stack's. The port's is NULL.
- **NULL seams.** A NULL translate, or a NULL answer, is "". A NULL
  height function is 0.

## Checking

`tools/raceover_check.py` runs retail's three Player.obj functions and
RenderTextIntoGroup in `retail_model.RetailEmu`. Under them run retail's
GetBestLapTime, GetPlayer, PrintToString and RoundSeconds, SetTime,
WriteTextIntoChunk, isspace, bSPrintf and bStrLen. The stubs print what
they are asked on both sides: GetTranslatedString,
UseTheRaceEvent, MaybeDoKnockoutRaceOverSpeech, FindFlailerObjectByGroup,
SetVisibility, SetString and GetScaledHeight.

`tools/src/raceover_test.c` runs `raceovermsg.c` and `flailerwrap.c` with
`timer.c` and `bprintf.c`. Its translate uses one shared buffer, as
main.c's does. The model zeroes 8 KB of stack below its frame before
each call, so retail's no-message cases read as the port's "".

The script covers:

- the English strings;
- wraps over five group shapes (one with 34 objects) and 300 random
  texts;
- every place and times in each language;
- the message over every RaceType, FinishReason, place, knockout size and
  race event;
- You're The Cop with one and two players;
- 400 random fills.

The result is 18562 ops, 40226 lines, 0 differ. `--mutate` runs 66
mutations: 64 caught and 2 equivalent:

- `tr-null`: retail never answers NULL.
- `place-int8`: the sign only matters outside 0 to 8.
