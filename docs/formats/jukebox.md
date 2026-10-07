# Jukebox (EA TRAX)

`bJukebox.cpp` in the asserts: EA's `cJukeboxPlayer` and
`cJukeboxCartridge` (0x0027d5b0 .. 0x0027eb10), the game's `sound::jukebox`
wrapper round them (0x001ae028 .. 0x001afb40), and the playlist half of
`DataAudioOptionsScreen` (0x001eef60 .. 0x001ef240). Part of task 36, the
frontend: it is what plays "Fever for the Flava" on the main menu.

Ported to `3DS Files/source/jukebox.{c,h}`, free of `<3ds.h>`. The 3DS half
-- the file read off the card, decoded and fed to ndsp -- is
`3DS Files/source/jbstream.{c,h}`.

Cross-checked by:

- `tools/jukebox_check.py` against `tools/src/jukebox_test.c`: retail's
  code in mipsemu next to the port, 952 ops, with a fake sample on both
  sides and two made-up cartridges plus the retail one. `--mutate` runs 283
  mutations of `jukebox.c`; four are equivalent by construction (listed in
  the checker's `EQUIVALENT`).
- `tools/jbstream_check.py` against `tools/src/jbstream_test.c`: the stream
  decoder against `tools/audio_convert.py`'s ADPCM decoder on real tunes,
  cut at the pair boundaries and the end.

## The file

`SOUND\JUKEBOXM.JBC` on the retail disc, 193,167,360 bytes. Little-endian.

### Header, 32 bytes

| Off | Value | |
|----:|------:|---|
| 0 | 16 | not read |
| 4 | 2 | channels; not read, the player is stereo |
| 8 | 32000 | the sample rate, `GetSampleRate` |
| 12 | 1 | categories |
| 16 | 4096 | bytes of index that follow the header |
| 20..31 | 0 | |

### Index

`header[4]` bytes read in one go, right after the header. For each of
`header[3]` categories:

- a 64-byte category record: the tune count (u32), then the name (60
  bytes, NUL-padded);
- that many 96-byte tune records: offset, size, sync size (three u32s), then
  the name (84 bytes, NUL-padded).

Nothing else in the index is read. The retail one has one category,
`InGame`, with 23 tunes, and ends at byte 2304 of the 4096. Every sync size
is 0.

A tune's name is five fields cut at `-`: artist, title, album, genre and
status, as `Hot Action Cop-Fever for the Flava--Rock-4`. "--" is an empty
field -- that tune has no album -- and a dash at the very end starts none:
`ExtractJukeboxTrackStrings` (0x001aed90) only starts a field when
something follows its dash. The EA TRAX box prints the first three.

### A tune

`offset` points at a 48-byte `VAGp` header (the rate at +16, big-endian,
is 32000 too); the audio starts at `offset + 48`, which is always a multiple
of 0x800. Retail plays `size` bytes from there, and `size` is 48 more than
the audio, so the stream's last 48 bytes are the next tune's padding. The
audio itself is whole pairs.

The audio is PS2 SPU ADPCM, stereo, in blocks of 0x8000 bytes alternating
left and right: a pair is 0x10000 bytes, 2048 frames of 16 bytes per
channel, 28 samples a frame. The end is marked only in the last pair, by the
frame flags: the last frame played carries flag 1 (decoded, then the stream
ends), and the frames after it carry 7 (not decoded).

The status is a number, 0 to 5, and says which lists a tune is on
(0x002b6300; the columns are the menu, a race, a pursuit):

| Status | Menu | Race | Pursuit |
|-------:|:----:|:----:|:-------:|
| 0 | | | |
| 1 | | | yes |
| 2 | | yes | |
| 3 | yes | | |
| 4 | yes | yes | |
| 5 | yes | yes | yes |

The retail tunes are 4 (the vocal ones), 2 (the instrumentals and remixes)
and 0. So the main menu picks among the eight 4s.

## How it runs

`InitializeSoundDriver` (0x001ae780) builds the jukebox and calls
`LoadCartridge` (0x0027dac8) on the JBC. That reads the header and index and
news the one `bSampleStream` the player keeps; it does nothing if
`bSound::GetStatus()` is not 1. It then sets each bSound category's volume
(0x001afab8):

| Cat | | Volume |
|---:|---|---:|
| 0 | SFX | 0.38 |
| 1 | tires | 0.55 |
| 2 | engine | 0.33 |
| 3 | menu SFX | 0.31 |
| 4 | racing music | 0.85 |
| 5 | menu music | 0.45 |
| 6 | speech | 0.75 |

Each is multiplied by 1.0 -- or by the demo disc's volume ×0.1 when
`TheDemoDiscManager` is active, which the port leaves out -- and the lot is
saved for speech. The audio options' Default button (0x001efea8) calls the
same function.

The playlist lives in Fred at +148 (`DataAudioOptionsScreen`, 176 bytes; see
`JB_AO_*` in `jukebox.h`). `InitWithDefaults` (0x001ef1c8) fills it from the
cartridge; the memory card's settings load over it and 0x001ef120 applies
them (the volumes, then `SetSelection(5)`).

`SetSelection` (0x001af050) is called with the list the game is in: 5 in
the frontend (`LoadSoundRegionsFrontEnd`), 4 in a race. It turns each tune
on or off by its status and genre. `jukebox::Start` (0x001aeab0) picks a
tune and plays it; the main menu's constructor calls it. Every frame
`sound::Update` (0x001af4c0) runs the player's `Update`, which moves the
state on from the sample's events: buffered, play end, fade end.

## The port

`jukebox.c` is retail's code throughout. The sample is a `JBHost`, a table
of the bSample calls the player makes, so the checker can drive it with a
fake and the 3DS with `jbstream.c`.

`jbstream.c` opens the JBC off the card, seeks to `offset + 48` and reads
`size` bytes a pair at a time. A worker thread (one priority above the main
thread, on the process's default core) decodes each pair to PCM16 into a ring of eight
128-frame ndsp waves on channel 22. bsnd has channels 0 to 21 and the boot
movies 23. The events are posted back to the main thread as bits and
delivered by `jbstream_poll` in retail's order: buffered once four waves
are queued, then fade end, then play end once the decoder hit flag 1 and
the ring has drained. The channel's mix is the scale × the play volume × the
fade level × the category's volume.

## The EA TRAX box

`tNewSongMonitor` (0x0016bd30 .. 0x0016c214, 24 bytes) is what shows the
tune. `FlailerScreenList` builds one in its constructor (+0x44) and ticks it
every frame from `Tick` (+0x7c), after the menus' movie.
`UnlaunchFrontendMenus` resets it (+0x100). Retail's reset only deletes the
alpha animation at +20, which nothing ever creates, so it does nothing, and
the box stayed up for the rest of its five seconds over the loading screen
with the stopped tune's name. The port's `bsm_reset` takes the box down and
forgets the tune (start 0x7fffffff, starts 0), so the next tune shows its
name again. That is a change from retail, made at the user's request.

### The race's music

The jukebox stops when the menus go, and the race starts its own:

- `LoadSoundRegionsInGame` (`0x001ae798`), as the track loads, clears
  `DelayedStart`'s timer (gp-19028) and `Mute`'s flag (gp-19040) with sound
  up and turns the selection to the racing list (category 4). The first
  tune is the audio options' list 7 (14 in a pursuit) when that is enabled,
  else a random skip. main.c's `hookLoadSoundRegionsInGame` does this and
  calls the callback at once, since the port has no engine regions to load.
- `RACE_IN_PROGRESS`'s first `TICK` at `RACING` (GO) calls
  `DelayedStart(6.0)` (`0x001aec88`, the call at `0x0014af60`), so the music
  starts six seconds after the countdown ends, never during it.
  `jb_music_update` counts the timer down outside the frontend.
- `RaceCoordinator`'s cleanup calls `Stop`; `RESTART_RACE` parks the timer
  at 9e9 for the next start.

That `TICK` reads the replay's beginning of time, `ReplayManager`'s Timer at
+92. The port's stand-in `ReplayManager` is zeroed, so main.c's
`replayGetBeginningOfTime` and `replayMarkTheBeginningOfTime` keep that one
Timer in it, and the first `RACING` tick marks it as retail's does.

| offset | field |
|--------|-------|
| 0  | the track it last saw, `(category << 16) + tune`, -1 at first |
| 4  | `RealTimer` when that track started, 0x7fffffff before any |
| 8  | the screen, `bStringHash("CHYRON")` = 0x54987eb2 |
| 12 | starts: tunes it has seen since the jukebox was last silent |
| 16 | printed |
| 20 | an `feAlphaAnimation`, never made |

`Update` does the following each frame:

1. While nothing plays, it zeroes the starts.
2. When a tune plays that is not the one it saw, or the starts are zero, it
   takes the track and the time, counts a start and clears printed.
3. With no start time (0 or 0x7fffffff) it stops there.
4. Otherwise `t = (float)(int)(RealTimer - start) * 0.00025`. Outside
   (0, 5) seconds, CHYRON is hidden. Inside, CHYRON is shown (gp-21264 is 1
   in the image and nothing writes it).
5. On the first frame shown it prints three lines:
   - `RECORD_LABEL` `"%s"` with the label;
   - `ARTIST_NAME` `"%s"` with the artist;
   - `SONG_TITLE` `"\"%s\""` with the name.

   `bVSPrintf` spells a NULL string `(null)`.
6. It then takes the widest of the three lines and `RECORD_TITLE` ("EA
   GAMES  TRAX"), as signed widths from `FlailerGetWidth`. The last of those
   is also kept at gp-21244.
7. It stretches `CHYRON_BG_1..5` to that width plus 20:
   `ScaleX = (widest + 20) / (width / ScaleX)`, `ScaleY` untouched.

In the main menu the tune is "Hot Action Cop-Fever for the Flava--Rock-4".
Its label is empty, so the box shows "Fever for the Flava", then Hot Action
Cop, then EA GAMES TRAX. It sits bottom-left and covers the Help button for
five seconds, as the retail photo shows it. The strips are black on
`WHITE16X16` at an over-bright alpha 0xc8. They come out as charcoal bars
only with the GS's multiply (flailer-ui.md, "Colour: the GS's MODULATE").

`songmon.c` is `Update` line for line. `tools/songmon_check.py` runs it next
to retail's in mipsemu, with the Flailer, jukebox and timer calls stubbed at
their addresses: 321 ops, 1307 lines, 0 differ. The checker has 48 mutations:
46 are caught and 2 are equivalent.

- `t-unsigned`: `t` is only tested against (0, 5). A difference of 2^31 or
  more falls outside it read either way.
- `scale-preset`: `FlailerGetScale` leaves the preset alone only for a
  missing object, and `FlailerGetWidth` gives 0 for that object, so the
  width over the preset is 0 whatever the preset is.
