# Audio Options and JukeBox Music (TASKS 71b)

Options' Audio is retail's `AudioOptionsScreen`, and its Jukebox row opens
`JukeBoxMusicScreen` (`audiooptions.c`, `audiooptions.h`). Both are
OptionsScreenBase pages (`bscreens.c`'s `bscr_optbase_*`: the blurb, the
highlight, the exit animation) with a scrolling list (`bsetup.c`'s
`bscroll_*`) and a pair of pulsing arrows (`barrows_*`).

| Config name | Flailer screen | Callback |
|---|---|---|
| "Audio Options" | e116761c | `audioopts_callback` (0x001f0278) |
| "JukeBox Music" | 95b2b627 | `jukeboxscreen_callback` (0x001f1220) |

| Retail function | Address | Port |
|---|---|---|
| FlailerSlider::FlailerSlider | 0x0016dc20 | `sliderInit` |
| FlailerSlider::StepValue | 0x0016dd38 | `sliderStep` |
| FlailerSlider::Animate | 0x0016de30 | `sliderAnimate` |
| the options into bSound | 0x001ef120 | `applyAudio` (`jb_audio_apply`, then `sound_set_audio_mode`) |
| AudioOptionsScreen::AudioOptionsScreen | 0x001ef3c8 | `audioConstruct` |
| AudioOptionsScreen::FindSlider | 0x001efa68 | `findSlider` |
| AudioOptionsScreen::ChangeAudioMode | 0x001efaa0 | `changeAudioMode` |
| AudioOptionsScreen::RedrawAudioMode | 0x001efb38 | `redrawAudioMode` |
| AudioOptionsScreen::HandleEvent | 0x001efb80 | `audioEvent` |
| JukeBoxMusicScreen::JukeBoxMusicScreen | 0x001f02d8 | `jukeConstruct` |
| JukeBoxMusicScreen::ShowPlaylist | 0x001f0478 | `showPlaylist` |
| JukeBoxMusicScreen::PlayCurrentSelectedSong | 0x001f0cc8 | `playSelected` |
| JukeBoxMusicScreen::HandleEvent | 0x001f0d10 | `jukeEvent` |

## Audio Options

Eleven rows in a window of seven (`MENUITEM_1` .. `MENUITEM_7` visible, the
list scrolling under `edf2e4ee`/`20d73d01` and clipped by `c67cfb4a`; the 26
objects that scroll are `0x002b9c30`'s table):

1. Menu Music, Racing Music, Ambient SFX, Tire SFX, Engine SFX, Menu SFX,
   Speech: seven `FlailerSlider`s, each a track and a knob.
2. Audio Mode: Mono (110009), Stereo (110008), Dolby Pro Logic II (110011),
   with the left and right arrows (`d1cda594`/`9345e4a7`) while it is
   highlighted.
3. Jukebox: JukeBox Music.
4. Default Volumes (`aee77883`): `jb_default_category_volumes`, and every
   slider set again.
5. Default Jukebox (`aee77884`): `jb_audio_default_jukebox`, every genre on
   and every tune back to its shipped status.

The blurb is 150500 plus the row (150509 and 150510 for the two Defaults).

A slider's place is its volume scaled so the game's shipped volume sits at
0.7 of the track: `scale = 0.7 / kDefault[cat]`, kDefault `{0.38, 0.55,
0.33, 0.31, 0.85, 0.45, 0.75}` (`0x001afa28`). Left and Right step the
place by 0.05, clamped to [0, 1]. The volume is set at once
(`jb_save_volumes_for_speech` after it) and "MenuAdjustVolume" plays at the
new place when it changed. The knob eases there over a quarter second
(`BSpline`, `bspline_seek` by the real elapsed time). Its x is `left + place
* (right - left)` of the track's box.

The mode goes round Mono, Stereo, Prologic with Left and Right and applies
at once. **The port shows Prologic as "Surround"** (`PORTLANG_SURROUND`,
"Envolvente" in Spanish). The 3DS has no Pro Logic decoder on the other end.
`bsnd_set_mode` plays mode 2 through the console's own Surround output
(`NDSP_OUTPUT_SURROUND`), mono through `NDSP_OUTPUT_MONO` and stereo through
`NDSP_OUTPUT_STEREO`. Prologic takes the stereo volume path
(docs/formats/sound-driver.md). The user chose Mono / Stereo / Surround on
2026-10-16, over dropping the value or the row.

## JukeBox Music

`jb_genre_populate` builds the genres from the tune list (`JBGenreMgr`). The
genre's name is on `MENUITEM_1` with the left and right arrows while the list
is not entered. The rows below it are a window over the genre's tunes:

- the name (`64a819c7`+row, the big line);
- the artist (`03b57047`+row, the small line);
- the status, by `AudioPlaylistOnOff`'s Status (`0x002b9d30`): Off 110041,
  World Racing 110042, Hot Pursuit 110045, Menu 110043, Menu/Racing 110052,
  Always 110044;
- the selected row's two bars (`0b825845`.., `fc0279b8`..).

The selected row is orange (`0x80004080`), the others white (`0x00808080`),
and a genre turned off grays them all (`0x80181818`). The favourite line
`0b41999a` is "%s (%s)", the name and the artist.

| Key | Outside the list | In the list |
|---|---|---|
| Left / Right | the genre, wrapping | the tune's status, wrapping 0..5 |
| Down | into the list, if the genre is on and has tunes | the next tune |
| Up | nothing | the previous tune; from the first, out of the list (the music stops) |
| L | the genre on or off | the same, and out of the list when it goes off |
| B | back to Audio Options | the same |

A tune picked in the list plays half a second after the last move
(`pending`, `timer`), so scrolling past tunes does not start each one. Past
30 seconds the screen checks the jukebox and starts the tune again if it
stopped. B writes the page into Fred and `jb_music_set_selection(.., 5)`.
It then plays the favourite if its genre is on and its status is not Off, or
the list from the top (`jb_start`).

L is `BJOY_MENU_L1` (`KEY_L`, main.c's `kBinds`), sent as
`BMSG_SCREEN_L1` with no noise, as retail's L1. R is bound to `BJOY_MENU_R1`
the same way for the pages that use it.

## The save prompt

Retail's B on either page writes the page into Fred and, with autosave on and
anything changed, goes to the Autosave screen. The port follows the user's
rule of 2026-10-13: any screen that changes the save asks "Save your changes
to the SD Card?" when it is left with changes, with autosave on or off.

- Audio Options snapshots Fred's audio options (176 bytes) when the player
  comes in from Options. It keeps the snapshot while JukeBox Music is open,
  so the JukeBox's changes count too.
- B with Fred unchanged from the snapshot goes back to Options.
- B with changes asks, as a cancelable Yes/No memory card popup:
  - **Yes**: the Autosave screen, which saves (its overwrite question first,
    when a save is there).
  - **No**: the snapshot put back into Fred and applied (volumes, mode,
    jukebox), and back to Options.
  - **B**: stays on Audio Options.
- JukeBox Music's B goes back to Audio Options without asking. The question
  comes when Audio Options is left.

## Testing

`tools/run_azahar_audio.ps1` boots to Options and walks both pages:

1. A slider stepped, the mode changed and back.
2. JukeBox Music: genre changed, a tune picked and played, its status
   changed, the genre off and on with L.
3. The prompt: B stayed, then No put the options back.
4. Back in Audio Options: Menu Music and the mode changed, Default Volumes,
   then Yes saved on the Autosave screen.

The run puts `NFSHP2/SAVES/settings.db` back after. Audio Options comes back
on the row it was left on (the menu remembers its last highlight), so the
script goes Up to the top before counting rows.
