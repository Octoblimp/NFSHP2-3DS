# The Local Wireless lobby (TASKS 37b-2)

The port's own. On retail, Players 2 on a mode screen means split screen
on one PS2, and its car select is "Select Car2P". The port has no split
screen (the user, 2026-10-13). There, Players 2 means local wireless,
with up to eight New 3DS consoles (`docs/formats/wireless.md`). The
lobby is where they find each other before car select.

- `bsetup.c` shows Players 2 as "Local Wireless" with its own blurb
  while `BSetup.wirelessPlayers` is set. `main.c` sets it, and the
  setup hook answers that pad port 1 is plugged in, so Players can reach
  2. Where retail goes on to "Select Car2P", the port goes on to the
  lobby instead. That covers Challenge and the four setups behind its
  Setup (Single Race, Knockout, Lap Knockout, Free Run).
- `lobby.c` is the screen "Local Wireless". It has no `<3ds.h>`: the
  link comes in through `LobbyNet` (`lobby.h`), which `main.c` fills
  with `wireless.c`'s calls. `tools/lobby_check.py` runs it on the
  host.
- `portlang.c` holds the port's strings, which retail never had to say,
  in retail's six languages.

## The screen

"Local Wireless" is a screen with no Flailer hash of its own (hash 0).
It draws nothing but one popup at a time, on the memory card's popup
screen: the buttons side by side under the message, the lobby's name
over it as the title, and BACK the way out. Each step is a new popup.
The previous one is taken down with no sound and no answer.

| State | The message | Buttons | What A does | BACK |
|---|---|---|---|---|
| Ask | "Host a race, or join one?" | Host, Join | Host: hosts. Join: searches. | Back to the mode screen |
| Hosting | "Waiting for players:", then each name | Start, once a client is on | Starts the race | Ask |
| Searching | "Looking for races..." | none | Puts it back | Ask |
| Found | "Race: name", "Players: n/max" | Join, Next | Join: joins. Next: the next race found. | Ask |
| Joined | "Waiting for name to start the race." | none | Puts it back | Ask |
| Notice | what went wrong | OK | Ask, or Searching after a failed join | the same as A |

A popup with no buttons gives SELECT an answer that only puts it back,
with no sound. BACK plays the cancel sound. Every other answer plays
the select sound.

Going to Ask takes the link down: UDS's network is left and UDS
stopped. Leaving the screen any way but on to car select takes it down
too, and so does coming back from car select (SCREEN_ACTIVATE starts at
Ask). Only the host's Start and a client's start message go on to
"Select Car" with the link up.

### Hosting

Host starts UDS and a network of up to 8 consoles. The popup's lines
are "Waiting for players:", this console's name, then each client still
on, in the order they came. It goes up again only when that changes, so
the list stays put while nothing happens. Start shows once one client
is on. A client that goes is dropped from the list. Its place in the
network is cleared too (`wireless_forget_lost`), or it would keep the
next console out.

Start closes the network and sends each client, reliably, the message
`LOBBY_MSG_START` (0x10) with two bytes: how many consoles there are,
and the client's place (1 on; the host is 0). Then it goes on. If the
last client went as Start was pressed, the list comes back instead.

If the network goes from under the host, it says local wireless could
not start, and OK goes back to Ask.

### Joining

Join starts UDS and scans at once. While nothing is found, it scans
again every second (`LOBBY_SCAN_MS`), with "Looking for races..." up.
The first scan that finds a race shows the first one found: its host's
name and how many consoles of how many are on it. Next shows the next
race. Past the last, it scans again and starts over at the first, or
goes back to searching when there are none left. After Next, the
highlight stays on Next, so A alone walks the races.

Join joins that race. Then the client waits, reading the link each
frame, until the host's start message comes, and goes on. If the link
goes first, it says "The link to name was lost.", and OK goes back to
Ask. A failed join says so, and OK goes back to searching.

### Names

A name is the console's user name, which UDS carries as UTF-8.
`lobby_latin1` turns it into the font's Latin-1. A character past
0xff, a control character, a bad sequence, or `@` (which breaks the
popup's lines) becomes `?`.

## The strings

`portlang.c` holds 14 strings, each in the six languages retail ships
(English, French, German, Italian, Spanish, Swedish), in retail's
encoding, Latin-1. Their IDs start at 2000000 (`PORTLANG_FIRST`), well
past retail's last (980002). `langtab_get` answers those IDs from
`portlang_get`, so a text object, a blurb or a popup's button takes one
like any of retail's. FE_LONGEST gets the longest of the six and FE_ID
the ID's own number, as retail's tables do. Before a language is
chosen (-1), the lobby takes English.

`$NAME`, `$N` and `$MAX` in a string are filled in by the lobby. `@`
starts a new line in a popup's message, as in retail's strings.

| ID | English |
|---|---|
| 2000000 | Local Wireless |
| 2000001 | Up to eight players, each on their own 3DS. |
| 2000002 | Host |
| 2000003 | Join |
| 2000004 | Host a race, or join one? |
| 2000005 | Looking for races... |
| 2000006 | Race: $NAME@Players: $N/$MAX |
| 2000007 | Next |
| 2000008 | Waiting for players: |
| 2000009 | Waiting for $NAME to start the race. |
| 2000010 | Start |
| 2000011 | The link to $NAME was lost. |
| 2000012 | Local wireless could not start. Is the wireless switch on? |
| 2000013 | Could not join the race. |

### How it looks

The lobby's screen has no Flailer art, so its popups sit on black, the
way retail's memory card popups do on BootAutoload, which has no objects
either. The bottom screen shows "LOCAL WIRELESS" over an empty panel. A
popup with one button (Start, OK) shows it where the first of two would
be, as the popup screen's own layout has it.

## On Azahar

`tools/run_azahar_lobby.ps1 -Consoles N` (2 to 8) runs the lobby between
N copies of Azahar, the soak's portable copies under `%TEMP%\nfshp2_wl`
in a room of their own (`docs/formats/wireless.md`, "On Azahar"), on
port 24873.

- Each card's `sdmc:/NFSHP2` gets a junction to each of the user's data
  folders (`%APPDATA%\Azahar\sdmc\NFSHP2`), except SAVES. SAVES is each
  copy's own folder, with the user's saves copied in, so every copy
  starts from the same profile and none writes another's. The script
  refuses to go on if a data folder is a real folder or SAVES is a
  junction.
- Each copy boots the game with `DebugLog 1` and is driven by its own
  log: language and intro if they come, the title, World Racing,
  Challenge, right on Players to Local Wireless, and A. A step waits
  for its line among the lines logged since the last press, since a
  line can land up to ~7 s late.
- Copy A hosts and waits until its list has every copy, then presses
  Start. The rest press right to Join and A to search, wait for
  hp2host's race, join it, and wait for the start.
- It passes when every copy reaches Select Car: the host after "start,
  N consoles", each joiner after "started by hp2host, place p of N".
  Screenshots of each step go to `%TEMP%\nfshp2_lobby`.

Session 97, all passing:

| Consoles | Every copy at Select Car | From the host's lobby | Places told |
|---|---|---|---|
| 2 | 115 s from launch | 13 s | 1 of 2 |
| 4 | 139 s | 16 s | 1 to 3 of 4 |
| 8 | 197 s | 22 s | 1 to 7 of 8 |

With 2, B's first scan found nothing, since A was not hosting yet. Its
second, a second later, found A's race at 1 of 8. With 8, the host's
list grew one name at a time in the order they joined, not their
letters, and each joiner was told the place of its turn. Its nine lines
and Start fit the top screen, and the host held 100% speed.

## The check

`tools/lobby_check.py` builds `tools/src/lobby_test.c` with `lobby.c`,
`portlang.c` and the real flow and popups under them (`gameflow.c`,
`bpopup.c`, `memcard.c`, `banim.c`). A fake network stands in for
`wireless.c`. It runs 28 scenarios, each a script of presses and of
what the network does: hosting alone, with one, with seven and with a
full network; clients coming and going; the network going; joining,
Next past every race, a failed join, a lost host, leaving; no wireless;
back from car select; a language not yet chosen; French.

At every frame and after every press it checks:

- one popup up on the lobby, the lobby's own, and none off it;
- the question never up with the link up;
- the host's list against the network, and Start there exactly when a
  client is on;
- the joiner's wait naming the host joined;
- each press's sound, and no sound without a press;
- a new search scanning at once, and no scan sooner than a second
  after the last;
- each call on the network only when it makes sense (no host or scan
  while on a network, no join of a host the last scan did not see, no
  send to a client that went);
- on to car select only with the link up and the network closed, each
  client told once its place and the count, and a joiner only after
  reading its start;
- back out only with the link down;
- where each scenario ends, and the lines its log must say, in order.

The last line is `total faults N`, and the check passes at 0.

`--mutate` makes 67 mutations of `lobby.c` (out of tree, in parallel).
64 are caught and 3 are equivalent, named in the script:

- `lb-latin1-two`: a two-byte lead's bit 5 is always clear, so masking
  it again changes nothing.
- `lb-hide-index`: every `hidePopup` is followed by a new popup or by
  leaving the screen, so the index it leaves is never read.
- `lb-ask-hide`: Ask is only reached after a popup was dismissed or the
  screen came up, so there is no popup left for it to hide.
