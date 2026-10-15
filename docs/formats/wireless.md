# The local wireless link (TASKS 37a)

The port's own. Retail's two players share one PS2 (split screen,
which the port leaves out). In the port, up to eight New 3DS consoles
race each other over local wireless, each with the game and the retail
files on its own card (TASKS 37, "The design": lockstep). Eight is a
race's grid, and the user asked for the most the hardware takes
(2026-10-14). A UDS network takes up to 16 nodes (libctru's
`UDS_MAXNODES`), and Mario Kart 7 races eight over Download Play. This
is the link under that design. It has three parts:

- `wlproto.c` is the protocol. It has no `<3ds.h>` in it, so
  `tools/wlproto_check.py` runs it on the host.
- `wireless.c` puts it on UDS, the 3DS's local wireless (libctru's
  `uds*`), and handles the network: hosting, scanning, joining and
  leaving.
- `wirelesstest.c` is a soak of the link between 2 to 8 consoles. It
  runs in place of the game when the config asks for it.

The CIA's `app.rsf` asks for `nwm::UDS` and depends on the nwm module
(0x0004013000002d02).

## The network

| What | Value |
|---|---|
| Comm ID | 0x4e485032 ("NHP2") |
| id8 | 1 |
| Data channel | 1 |
| Nodes | 2 to 8, the host's choice: the host (node 1) and its clients |
| Passphrase | `NFSHP2-3DS local race` (with its terminating 0) |
| Spectators | none (`udsEjectSpectator`) |

The beacon's application data says which hosts are the port's:

| Offset | Size | What |
|---|---|---|
| 0 | 4 | `N` `H` `P` `2` |
| 4 | 1 | wlproto's version (1) |
| 5 | 1 | n, the length of the caller's bytes (at most 64) |
| 6 | n | the caller's bytes (the soak's are `SOAK`) |

A scan skips any host whose tag or version is not these, whose n runs
past the data, or whose network is full. It gives each host's name
(node 1's user name, the console's own) and how many consoles are on
its network of how many.

The network is a star. Each client talks to the host alone, over one
link, and the host keeps a link for each client: its peers, in the
order they came. A client's one peer is the host. Each side sends to a
peer's node alone (unicast), and counts packets from a node that is not
a peer as strays. The status is read on each status event, and every
250 ms without one.

The host gives each client node new to the status's node mask a peer
with a fresh link, with its name from `udsGetNodeInformation`. That
holds while the network is open. `wireless_set_open(0)` closes it (the
lobby's start, or the soak's once all have come):
`udsSetNewConnectionsBlocked`, and any node that comes in anyway is
ejected.

A peer's link is lost:

- when its bit leaves the node mask (the host's bit, for a client);
- when nothing has come for 3 s, once something has;
- when nothing has come within 6 s of the join.

The host ejects a client whose link went quiet. It takes no new peer
on a node it has let go until the mask shows that node gone. A lost
peer keeps its place with `alive` 0, so the race can tell who went;
`wireless_forget_lost` clears those places, for the lobby. A client
whose host is lost is in the state LOST.

## The packet

Each UDS frame is one packet of at most 1024 bytes. UDS itself carries
up to 1478. All numbers are little-endian.

| Offset | Size | What |
|---|---|---|
| 0 | 1 | magic, 0x48 (`H`) |
| 1 | 1 | version, 1 |
| 2 | 2 | ack: the next reliable number the sender has yet to deliver. Its top bit is 0. |
| 4 | 1 | count: how many messages follow |
| 5 | 2 | CRC |
| 7 | | the messages, one after another |

Each message:

| Offset | Size | What |
|---|---|---|
| 0 | 2 | seq: a 15-bit number, or 0x8000 for an unreliable message |
| 2 | 1 | type: the caller's |
| 3 | 1 | len, at most 240 |
| 4 | len | the data |

The CRC is CRC-16/CCITT-FALSE (polynomial 0x1021, starting at 0xffff,
not reflected, no final xor). It covers bytes 0 to 4, then everything
from byte 7 to the end, so the CRC field itself is left out.

A packet is dropped whole, and counted as malformed, when any of these
holds:

- it is shorter than the header;
- its magic or version is wrong, or its CRC does not match;
- its ack has the top bit set;
- an unreliable message's seq has other bits set too;
- a message's len is over 240;
- the messages do not end exactly at the packet's end.

## Reliable and unreliable

**Reliable** messages arrive once, intact and in order, or the link is
lost. Up to 32 are in flight at a time, numbered mod 2^15. Every packet
acks; an acked message is forgotten. A message not acked within
100 ms goes again, every 100 ms until it is acked. The receiver takes
the one it expects and up to 31 past it, holds those that come early,
and delivers them in order. It counts a repeat or one outside the window
as a repeat, and acks again. When the inbox (64 messages) is full, the
next message stays held and goes unacked, so the sender sends it again
until there is room.

**Unreliable** messages go in the next packet only, up to 8 of them.
One may be lost, come twice or overtake another. When the inbox is full
it is dropped and counted. The race's per-frame messages will be of
this kind, each repeating the last few frames (37d).

A side with nothing to send still sends an ack after a reliable message
comes, and a keepalive every 100 ms, so the other's 3 s timeout holds.

`wl_link_send` refuses a message when the window or the unreliable
queue is full, or when it is over 240 bytes. The caller sends it again
later.

## The soak

`WirelessTest 1` in `nfshp2_config.txt` hosts a network for
`WirelessTestConsoles` consoles (2 to 8, itself among them; default 2),
and `WirelessTest 2` joins the first host it finds.
`WirelessTestSeconds` is how long each side sends (default 120). The
soak runs after the New 3DS check, before any game data loads, with the
top screen a text console. START leaves.

Each side retries every 2 s until it is connected: UDS's start, then
hosting or the scan and join. On Azahar it waits for the room that way.
The host closes its network once all have come. Each link has its own
soak (the host has one for each client), and from its connection, at 30
ticks a second, each side sends over it:

- 0 to 2 numbered reliable messages, of up to 200 bytes, whose bytes
  are a hash of their number;
- one 24-byte frame message (unreliable), likewise.

It checks everything that comes. A reliable message has to be the next
in order and intact. A frame has to be intact, and the soak counts
frames that come twice, go back, or skip some. When the time is up,
each side sends a reliable count of what it sent. A link has passed on
a side when that side holds the other's count and every message up to
it, has had no fault, and has all its own messages acked. It then
lingers 1.5 s, so the last acks get there. Once a link is done, its
going away counts as the finish. The test passes when every link has
(the host's consoles - 1 of them, a client's one), and fails when a
console goes before its link is done. It also fails unless the network
held every console at once, as a race needs: the status's node count
has to reach `WirelessTestConsoles`.

Each second the screen and the log show a `wltest: t` line for each
link: the state, the peer's node, reliable messages sent and got,
frames sent and got (with twice, back and gap), faults, and the link's
and UDS's counts. At the end, a `wltest: node N` line gives each link's
totals, and the last line is `wltest: PASS (...)` or
`wltest: FAIL: ...`. A joiner's `wireless: scan sees` line comes each
time what its scans see changes: how many networks, how many to join,
and how many it skips as not the port's or full.

### On Azahar

Azahar carries a game's local wireless over a multiplayer room.
`tools/run_azahar_wireless.ps1` runs the soak between 2 to 8 instances
on one PC (`-Consoles`). The room has places for the consoles and 2
more (`--max_members`), so a room of 4 shows as 4/6. The room server
sets no limit of its own.

- It starts `azahar-room.exe` (a private room on port 24872).
- It makes portable copies of Azahar under `%TEMP%\nfshp2_wl` (`A` to
  `H`), each with a `user` folder beside its `azahar.exe`.
- Each copy's config is the user's `qt-config.ini` with the room's
  address in it, and each card's `nfshp2_config.txt` sets the soak's
  keys and `DebugLog 1`. The user's own Azahar folder is not touched.
- Each copy gets its own console ID and MAC on its first start.
- It boots the `.3dsx` in all of them, and joins each to the room
  through Multiplayer > Direct Connect to Room, driven by UI
  Automation. Qt's Azahar ignores `--multiplayer`. The joins go one
  at a time, so the last copy's scans see nothing for its first minute
  or so with 8.
- It waits up to `-Seconds` + 60 + 20 a console for every result.

Two of Azahar's ways shape the script:

- A room refuses a second member with the same console ID or the same
  nickname.
- The nickname is the console's user name. Direct Connect shows it
  read-only, and every copy starts as "AZAHAR". So the script writes a
  name of its own (`hp2host`, `hp2join1` and on) into block 0x000A0000
  of each copy's config savegame
  (`nand/.../sysdata/00010017/00000000/config`).

Session 95, two consoles, 120 s:

| | Host | Joiner |
|---|---|---|
| Reliable sent | 3634 | 3642 |
| Reliable got | 3642 of 3642 | 3634 of 3634 |
| Frames sent | 3590 | 3581 |
| Frames got | 3581 | 3590 |
| Faults | 0 | 0 |
| Resends | 0 | 0 |
| Malformed | 0 | 0 |
| UDS errors | 0 | 0 |

Then, all PASS with 0 faults and 0 resends:

| Consoles | Soak | Host's links | Reliable got, each link |
|---|---|---|---|
| 4 | 30 s | 3 | 888 to 924 |
| 5 | 30 s | 4 | 870 to 918 |
| 8 | 60 s | 7 | 1733 to 1839 |

With 8, the network held all 8 at once (nodes 1 to 8, mask `00ff`),
and the host closed it at the eighth.

The room's channel loses nothing, so the losses come from
`wlproto_check` instead.

## The check

`tools/wlproto_check.py` builds `tools/src/wlproto_test.c` with
`wlproto.c`. It runs two links over a simulated channel in 38
scenarios: clean, lossy (drops, repeats, reordering), long cuts, reader
stalls (a full inbox), sequence wrap (150 s at 10 ms ticks), one-way
traffic and quiet links. It also sends crafted bad packets and random
noise.

It checks:

- every reliable message arrives once and in order;
- the receiver's state does not change for a packet it rejects;
- the sender's unacked count against the harness's own;
- latency and resends on a clean channel;
- the mean wait on a lossy one;
- when the link is lost and back around a cut;
- keepalives on a quiet link;
- a peek (`wl_link_peek`, TASKS 37f: the race's end leaves the lobby's
  messages on the link for it) is the message the next read takes, and
  leaves it there.

Each scenario prints its counts. The last line is `faults N`, and the
check passes at 0.

`--mutate` makes 53 mutations of `wlproto.c` (out of tree, in parallel).
51 are caught and 2 are equivalent, named in the script:

- `wl-drain-seq`: the held slot of `expect` only ever holds `expect`'s
  message.
- `wl-in-msg-header`: a guard on reading a message's header past the
  packet's end. The length test rejects that packet anyway, and the
  harness's buffers are longer than their packets, so the read itself
  is not seen.
