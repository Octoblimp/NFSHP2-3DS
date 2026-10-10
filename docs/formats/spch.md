# spch -- EA's speech library

SPCH is the library behind the cop radio and the race speech. The game
adds speech events as things happen, each one an event ID and up to 19
parameters. On a later frame it asks a channel to play. The library then
picks the best pending event on that channel and one of the event's
sentences whose rules the parameters pass. For each of the sentence's
phrases it picks a sample from the phrase's bank. Every chosen sample
goes to a request callback as an offset and a size in the bank's sample
data. cSEDWedge (14-8d) streams them out of ENGLISHDAT.PCK (14-8c).

Retail links it from SPP2A380.A at `0x00290720` .. `0x00295afc`, 130
functions in eleven objects. The port has it in `spch.{c,h}`,
`spchbank.c`, `spchevnt.c`, `spchpick.c`, `spchrule.c` and `spchi.h`.
The port names are retail's in snake case: SPCH_AddEvent is
`spch_add_event`, and the internal iSPCH_ functions are `spchi_`.
`tools/spch_check.py` runs retail's code against the port (see the end).

| object | port | what |
|---|---|---|
| spchrslv.o, sputil.o, spchinit.o | `spch.c` | binding the event dats, the vectors, Init and Deinit |
| spchlog.o | `spch.c` | the debug event log, dropped |
| spdprint.o, spabort.o, sptick.o | `spch.c` | the print and abort vectors and the clock |
| spchbank.o, spchsamp.o | `spchbank.c` | the bank table, the repeat queues, the cycle bits, UnPackSample |
| spchevnt.o | `spchevnt.c` | the event lookups, the queue, the event choice, Play |
| spchpick.o | `spchpick.c` | the sentence choice, the sample picks, the requests |
| spchrule.o, spchrand.o | `spchrule.c` | the rules and the random numbers |

## The data

Both files are read in place, so they must stay where they are while the
library runs. The library writes the banks' repeat queues and cycle bits
back into the bank data. All words are little-endian unless noted.

### EVENTS.EVT, the event dat

`SOUND/SPEECH/EVENTS.EVT`:

| at | what |
|---|---|
| 0 | u16 version, 0x0803. Anything else is refused with "This event dat goes with SED %d.%d" |
| 8 | the dat's first ID (the event word's fourth byte) |
| 9 | the dat's second ID (the event word's third byte, and the "dat ID" sent with each request) |
| 16 | u16 the number of events |
| 20 | u16 the filter's length, in hundredths of a second |
| 22 | u16 the filter's priority |
| 24 | a u16 for each event: its offset in the dat, in words |

Up to eight dats can be bound at once, each on a channel (0..7). Two dats
with the same pair of IDs are refused. Retail's has IDs 0 and 0, 201
events (IDs 0 .. 217), a filter length of 100 and a filter priority of
500. Nothing in the game binds a second dat.

**The event word** names an event: its ID in the low half, the dat's
byte 9 in bits 16..23 and the dat's byte 8 in bits 24..31. The event's
channel is the channel its dat was bound on.

### An event

| at | what |
|---|---|
| 0 | u16 ID |
| 2 | u16 life in ticks, 0 for none |
| 4 | u16 priority |
| 6 | the number of sentences |
| 7 | s8 the number of rules |
| 8 | s8 the repeat limit: plays in a row on the channel, 0 for no limit |
| 9 | s8 the probability (0 .. 100) that AddEvent queues it |
| 10 | flags (below) |
| 11 | unused |
| 12 | a u16 for each sentence: its offset from the event, in words |

The sentence table is padded to a word. After it come the rules, three
bytes each (the rule's ID, the event parameter it tests and its type),
also padded to a word. Then, with flag 8, the exact-match mask: a u32
with two bits per parameter, then a u16 for each sentence, padded to a
word. Then, with flag 0x10, the follow group: a count byte, a pad byte and
the u16 event IDs.

| flag | what |
|---|---|
| 1 | filterable: passed by under filter 1 if its priority is under the dat's |
| 4 | stays: ClearOldEvents leaves it in the queue |
| 8 | it has the exact-match mask |
| 0x10 | it has a follow group |
| 0x20 | an append event, played after the channel's last start event |

Retail's events use none of the flags. 158 of them have no rules, 40
have one and 3 have two. Every one of those rules is type 4.

### A sentence

| at | what |
|---|---|
| 0 | the weight: the low 5 bits times 4 to the power of the top 3 |
| 1 | the rule mask |
| 2 | the rule values |
| 3 | the number of phrases << 2, then the short rule in the low 2 bits |
| 4 | a byte for each phrase: its offset from the sentence, in words |

Retail's sentences have up to 5 phrases and no short rules; an event has
up to 20 sentences.

### A phrase, 32 bytes

| at | what |
|---|---|
| 0 | u16 the bank's ID |
| 2 | the event parameter that holds the subbank (type 1) or the template index (type 2) |
| 3 | the bank type: 0 by ID, 1 by ID and subbank, 2 by ID and template index |
| 4 | s8 the number of rules (at most 4) |
| 5 | three unused bytes |
| 8 | four rule references: an event parameter, 0 for none, 254 to set the match parameter, 255 to match it |
| 12 | four constant rules: an index into the event's rules, 255 for none |
| 16 | four u32 rule masks |

Retail's phrases are types 0 (1362) and 1 (124), with 0 to 3 rules and
references up to parameter 8. There are no constant rules.

### ENGLISHBAN.PCK, the banks

`SOUND/SPEECH/<language>BAN.PCK` starts with a 16-byte entry for each
bank, then the banks. An entry's words:

| at | what |
|---|---|
| 0 | the number of banks in the first entry, 0 in the rest; cSEDWedge writes each bank's handle over it |
| 4 | the bank's offset in the BAN file (the first is just past the entries) |
| 8 | unused: 0 in English, leftover bytes in the other languages |
| 12 | the bank's base in `<language>DAT.PCK`, where its sample data starts (the first is 256) |

The library only sees the banks themselves, through SPCH_AddBank;
[sedwedge](sedwedge.md) reads the entries.

A bank:

| at | what |
|---|---|
| 0 | u16 ID |
| 2 | u16 subbank ID |
| 4 | flags: the number of sample parameters (low 4 bits), the number of parameter IDs (bits 4..6), cycle bits (bit 7) |
| 5 | the number of samples |
| 6 | the repeat queue's length |
| 7 | the size unit less 1, in 256 bytes |
| 8 | u16 the end of the sample data, in units |
| 10 | u16 the number of template subbanks, 0xffff for none |
| 12 | the samples' entries (below) |

After the entries come the parameter IDs, one big-endian u16 each (the
parameter in the top 3 bits, the ID in the low 13). Then, with bit 7, the
cycle part: its length, then a bit for each sample. Then, with a queue
length, the repeat queue: its index, then one byte for each slot. Then
the template bits, a bit for each sample for each subbank.

A sample's entry is a big-endian u16 offset in units, then a byte for
each parameter. An entry with bit 7 set is an alias: its second byte
names the sample whose data it shares. A sample ends where the next
sample that is not an alias starts, or at the bank's end. AddBank refuses
a bank whose repeat queue is not index 0 with every slot 255.

Retail's ENGLISHBAN.PCK has 1806 banks: 0 to 3 sample parameters, queues
of up to 23 slots, and no parameter IDs, cycle bits or aliases.

## The state

Retail's globals are at `0x0032b240` .. `0x0032bf28`. The port has them in
one SpchState, `gSpch` (`spchi.h`):

- **The vectors.** These are the request callback, the rule test and set
  callbacks, the event rule and reparm callbacks, and the three external
  vectors: abort, print and gettick.
- **The bank table.** The game's array of bank pointers and its length.
- **The bound dats.** Up to eight, each with its channel.
- **The in-game record.** For each channel, the event word last played
  and how many times in a row.
- **The settings.** The game number, the data rate, the eight channels'
  filters and the preload ticks.
- **The event queue.** 16 slots of 96 bytes, with the channels' pending
  counts, last added and last head slots, and the bump flag.
- **The choice.** Up to 8 chosen sentences and 48 chosen parts.
- **The random state.** The six-word add-with-carry seed and a queue of
  the last 32 values handed out, each with its key.

## The functions

**Setup** (spchinit, spchrslv, sputil):

- **SPCH_Init(request, game, rate)** `0x00290a68` clears the callbacks and
  the vectors. It sets the request, the data rate and the game number, and
  seeds the random from the game (game + game << 16). It then clears the
  choice, the preload, the filters, the dats, the in-game records, the
  bank table and the queue, and marks the library initialized. It
  returns 1.
- **SPCH_Deinit** `0x00290b48` clears the mark, the callbacks, the bank
  table and the dats.
- **SPCH_InitRuleCallbacks**, **InitReparmCallback** and
  **InitEventRuleCallback** abort before Init.
- **SPCH_AddEventDB(dat, channel)** `0x00290858` binds a dat to a channel.
  It returns 1 if the dat was taken. SPCH_ResolveData binds to channel 0.
- **SPCH_GetSampleDataRate(rate, bits, mode)** `0x00290920` is rate * bits
  / 8, then / 10 for mode 1 and * 2 / 7 for mode 2.

**Banks** (spchbank):

- **SPCH_InitBankMem(n, table)** gives the library the game's table of `n`
  bank pointers and clears it.
- **SPCH_AddBank(bank)** `0x002910e8` checks the repeat queue and sets the
  cycle bits. It puts the bank in the first free slot and returns that
  slot as the bank's handle, or -1 when the table is full.
- **The cycle bits** give this game its share of a bank's samples. Of
  every `length` games, game `g` (the game number mod the length) gets
  samples `g * n / length` up to `(g + 1) * n / length`. A played sample's
  bit is cleared.
- **The repeat queue** holds a bank's last few samples. A sample in it is
  passed by while another one matches. When none does, the one played
  longest ago is taken.

**The queue** (spchevnt):

- **SPCH_AddEvent(parms)** `0x002916d0` takes `parms[0]`, the event word.
  An unknown event is dropped. A start event passes its probability test
  first, against a random number below 100. It then takes a slot: a free
  one, else one whose event has lived out its life, else the first on the
  channel of no higher priority. An append event takes its start event's
  priority, is linked after the channel's last added event, and may not
  take its start's slot.
- **SPCH_Play(channel)** `0x002923e0` plays the chosen sentences if there
  are any, else chooses with SPCH_Choose and plays. It returns the number
  of samples requested.
- **SPCH_Choose(channel)** `0x00292490`:
  1. It picks the channel's best start event. That is the highest
     priority, then the youngest, then the later added. Events past their
     life are cleared on the way. If the event last played has a follow
     group, only the group's events count, unless none is pending.
  2. It asks the event rule callback, which must answer 1, else the event
     is cleared and the next best is tried.
  3. It clears the channel's older events, except those flagged to stay.
     A newer one with probability 100 sets the bump flag.
  4. It chooses a sentence for the event and then for each event of its
     append chain, until one fails. Then it clears the event.
- **SPCH_PlayLastEvent(channel)** `0x00292358` chooses for the channel's
  last start event alone and plays it.
- **SPCH_SetFilter(setting, channel)** sets the channel's filter.

**The sentence** (spchpick) is chosen in ChooseSentence `0x00294178`:

1. **The repeat limit.** An event at its repeat limit, counted as plays in
   a row on the channel, is refused.
2. **The filter mode.** It starts as the channel's filter, plus one when
   the bump flag is set, at most 2. A filter of 1 on an event that is not
   filterable counts as 0. With a filter, the dat's filter length is the
   longest the sentence may be.
3. **The rules.** Each of the event's rules is tested on its parameter
   and gives one bit, the first rule's bit 7. A type 4 rule passes if the
   parameter is non-zero. The others ask the rule test callback: above 0
   passes, 0 fails, and below 0 fails and marks the bit as a fallback.
   Rules on parameter 0 are tested last, with the value 0.
4. **The order.** The sentences are tried in a random order drawn by
   their weights. Those of weight 0 come last, in their own order.
5. **The tests.** A sentence must match the event's exact-match mask if
   there is one. Its short rule is checked against the filter mode: 0
   always, 1 only in mode 2, 2 only outside it. Its rule values must
   equal the rule bits on its mask, the fallback bits excepted.
6. **The samples.** Each phrase finds its bank. That is by ID, by ID and
   the subbank in the parameter the phrase names, or by ID with that
   parameter as the template's subbank index. It then gathers the bank's
   samples that pass:
   - **the rules:** each sample parameter's bit must be in the rule's
     mask and, for a rule that names an event parameter, in that
     parameter's bits;
   - **the template and the cycle bits;**
   - **the repeat queue.**
7. **The pick.** With filter mode 1, the first combination shorter than
   the filter length is taken, after shuffling. Otherwise each phrase
   takes a pick:
   - a rule referring to 254 picks at random and sets the match parameter
     from the sample;
   - a rule referring to 255 takes a pick that matches the match
     parameter;
   - a phrase with neither picks at random.
8. **The reparm.** If no sentence fits, the reparm callback may change the
   event's parameters and try again.

**Playing** (PlayChosen `0x00293fb8`): for each chosen sentence, the
event's set rules (types 0 and 3) on the parameters the sentence uses go
to the rule set callback. Next the phrases' constant rules, from the
chosen samples' parameters, go to it as well. Then each sample goes to the
request callback as a SPCHType_SampleRequestData:

| at | what |
|---|---|
| 0 | the bank's handle |
| 4 | the offset in the bank's sample data, plus the template subbank times the bank's size |
| 8 | the size |
| 12 | the event word |
| 16 | the channel |
| 20 | the bank's subbank ID |
| 24 | the dat's ID |

The sample goes into its bank's repeat queue and its cycle bit is
cleared. The first sentence counts toward the channel's plays in a row.

**The random** (spchrand) is EA's add-with-carry generator over six words.
Rand(range, key) draws up to 32 numbers below `range`. It looks for one
not among the key's last min(range / 2, 10) values; failing that, it
queues the one seen longest ago. It returns the last draw, which is not
always the one it queued.

## Where the port differs

The port follows retail's code, including where retail reads past its
data. These are the exceptions, each noted in the source:

- **The debug log is dropped.** SPCHLOG writes only its own buffer.
  SPCH_InitEvlog keeps its check that Init came first. The library's log
  messages ("Rejected by short rule." and the like) are dropped with it.
- **Abort without a vector.** Retail saves the log, prints and exits; the
  port prints to stderr and goes on, as the callers do with a vector.
- **Reads past the data take 0.** Retail reads past the event's 20
  parameters for a reference, a template index or a rule parameter of 20
  or more. It reads past a sample record's four parameters for a bank
  with more. The port takes 0 or stops at four.
- **Writes past the data are refused.** Retail writes chosen parts past
  its 48 over the chosen sentences, and AddEventV copies more than 19
  arguments past its buffer. The port refuses them.
- **The pointer table.** SPCH_GetBankPtrMemSize is `n << 2` in retail, for
  its 4-byte pointers; the port is `n * sizeof(uint8_t *)`.
- **Uninitialized locals.** Retail leaves the dat's ID unset in a few
  places when the event's dat is gone. The port uses 0, which is what
  retail reads on a cleared stack.

## The checker

`tools/spch_check.py` runs retail's code from the ELF in a MIPS model and
the port in a host harness (`tools/src/spch_test.c`). It drives both with
the same script and diffs the transcripts. The script has built events
and banks that reach every branch, then retail's own EVENTS.EVT and all
1806 banks of ENGLISHBAN.PCK, played with varied parameters. The
callbacks are fakes that log their arguments and answer from a table.
AddEventV gets all 19 of its parameters: retail takes those past the
sixth off the caller's stack, a doubleword each.

A few tests reach inside. They poke the queue's last-head and last-added
indices and a start event's append link, to test the guards against bad
ones, and call EventInFollowGroup directly. A phrase or rule naming
parameter 20 runs only through the direct calls: there retail reads the
word past the checker's parameter buffer, which is 0, the port's value.

`--mutate` runs 591 mutations over the five files and `spchi.h`. All are
caught but three, listed in `EQUIVALENT` with the reason each cannot
change the result: Rand's first carry, the queue search's 33rd pass and
Rand's tie between two tries.
