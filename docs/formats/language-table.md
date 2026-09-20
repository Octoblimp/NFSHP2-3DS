# `0x00039000` -- `LANGUAGES\FE_*.BIN` string tables

Every piece of UI copy the game shows comes from here. Flailer text objects
(`docs/formats/flailer-ui.md`) carry a `LanguageID`, and the string baked into
the chunk beside it is only the authoring placeholder -- often stale. The
renderer calls `GetTranslatedString(LanguageID)` and draws *that*, so this
table is the real text.

Reader: `tools/language_dump.py` (`--id`, `--grep`, or `--csv` for a
side-by-side of every language; stdlib only). `tools/flailer_dump.py` uses it
automatically.

Eight files ship on this disc, all 1,896 IDs / 1,403 distinct strings:

| file | `LanguageEnum` | text bytes | `10023` |
|------|---------------:|-----------:|---------|
| `FE_ENGLISH.BIN` | 0 `l_EN` | 51,924 | `Hot Pursuit` |
| `FE_FRENCH.BIN`  | 1 `l_FR` | 54,855 | `Poursuite` |
| `FE_GERMAN.BIN`  | 2 `l_DE` | 54,310 | `Hot Pursuit` |
| `FE_ITALIAN.BIN` | 3 `l_IT` | 54,062 | `Inseguimento` |
| `FE_SPANISH.BIN` | 4 `l_ES` | 52,966 | `Persecución` |
| `FE_SWEDISH.BIN` | 5 `l_SE` | 48,297 | `Vild jakt` |
| `FE_LONGEST.BIN` | 6 `l_LONGEST_STRING` | 64,643 | `Inseguimento` |
| `FE_ID.BIN`      | 7 `l_ID_NUM` | 12,518 | `10023` |

The last two are build tools rather than languages: `FE_LONGEST` holds, for
each ID, the longest translation of it in any language, so layouts can be
tested against the worst case; `FE_ID` maps each ID to its own number as
text, so a QA build can read IDs straight off the screen.

## Layout

One `bChunk` wrapping `LanguageDescription` (100 bytes, verbatim from
`docs/mdebug_structs.txt`) followed by its three arrays back to back.

| offset | type | field | meaning |
|-------:|------|-------|---------|
| 0  | `u32` | chunk type | `0x00039000` |
| 4  | `u32` | chunk size | file size - 8, rounded up to 4 |
| 8  | `bNode` | `Next/Prev` | stale |
| 16 | `char[64]` | `FileName` | `..\PSX2\CD\Languages\FE_ENGLISH.bin` |
| 80 | `s32` | `LanguageEnum` | `e_Languages`, table above |
| 84 | `u32` | `NumHashEntries` | |
| 88 | `u32` | `NumIDEntries` | |
| 92 | `u32` | `TextTableSize` | |
| 96 | `ptr` | `pHashEngTable` | absolute PS2 pointer, dead on disc |
| 100| `ptr` | `pHashIDTable`  | ditto |
| 104| `ptr` | `pTextTable`    | ditto |
| 108| `LanguageLookup[NumHashEntries]` | `HashEngTable` | |
| .. | `LanguageLookup[NumIDEntries]`   | `HashIDTable`  | |
| .. | `char[TextTableSize]` | `TextTable` | |

The three stored pointers are the PS2 addresses the tables had when the file
was built and are useless; the arrays simply follow the header in that order.
`108 + 8*NumHash + 8*NumID + TextTableSize` accounts for the file exactly,
modulo the chunk's rounding to 4 bytes.

`LanguageLookup` is 8 bytes, `{s32 Hash; u32 Offset;}`, where `Offset` is a
byte offset into `TextTable`.

**Gotcha:** the last string in `TextTable` is not NUL-terminated -- the table
ends on its final byte -- so a reader has to clamp at `TextTableSize` instead
of scanning for a terminator. In `FE_ENGLISH.BIN` that last entry is the
string `Garbage`, which is presumably exactly what it is there to catch.

## The two lookup tables

Both index the same string pool; they differ only in what they are keyed by.
`LanguageManager::GetString` (`0x0020acd0`) binary-searches with `slt`, so
both are sorted ascending as **signed** 32-bit ints -- the hash table
therefore starts with the negative hashes.

* **`HashIDTable`** is keyed by the numeric `LanguageID`. IDs on this disc run
  10000..980002. This is the table `GetTranslatedString(id)` (`0x0020b0e0`)
  uses, and the one Flailer text objects reach through.
* **`HashEngTable`** is keyed by `bStringHash()` of the English text itself
  (case-sensitive, verified against all 1,896 entries), so code holding an
  English literal can look up its translation without knowing an ID. It has
  1,896 entries too, but only 1,403 distinct keys: 1,403 distinct strings
  carry 1,896 IDs, and a string used under several IDs is stored once per ID
  and listed once per copy, so 205 keys repeat.

  **Do not port a lookup onto this table.** Duplicate keys are harmless in
  `FE_ENGLISH.BIN`, where every copy is the same string by construction, but
  translations are context-sensitive: in `FE_FRENCH.BIN` 55 English hashes
  reach two or more *different* French strings (`Modifier le paramètre` vs
  `Modifier un paramètre`; `E3_HP1_TITLE` vs `Livraison de la Lotus Elise`).
  A binary search returns whichever copy it lands on. The ID table is the
  authoritative one and is strictly ascending with no duplicates at all.

One wrinkle worth knowing before porting `GetString`: it picks the table from
its `bool` argument but takes the entry count from `NumIDEntries` either way,
so a call with the English-hash table would search it using the *other*
table's length. `NumHashEntries` and `NumIDEntries` happen to be equal in
every file on this disc, so the bug is latent.

## The engine side

| symbol | address | role |
|--------|---------|------|
| `GetTranslatedString__Fi` | `0x0020b0e0` | `TheLanguageManager.GetString(id, curr, false)` |
| `GetString__15LanguageManageri11e_Languagesb` | `0x0020acd0` | the binary search |
| `TheLanguageManager` | `0x00313c90` | `LanguageManager`, 16 bytes |
| `LanguageFilenames` | `0x00313c70` | the `FE_*.BIN` name table |

`LanguageManager` is `{bTList LoadedLanguages; LanguageDescription
*CurrentLanguageDescription; e_Languages CurrLanguage;}` -- several languages
can be resident at once and `SetCurrLanguage` swaps the active description.

## The port

`3DS Files/source/langtab.c` is the handheld's reader: `langtab_parse()` over
a `0x00039000` payload, then `langtab_get(id)` / `langtab_copy(id, buf, cap)`.
It repeats `GetString`'s signed binary search but takes each table's own
count rather than reproducing the `NumIDEntries` bug, and it clamps the last
string at `TextTableSize` rather than scanning for a NUL.

`tools/langtab_check.py` builds it for the host and diffs every string
against `language_dump.py`: **all 1,896 IDs in all eight files agree** (15,168
strings), as do all 1,403 distinct English hashes in `FE_ENGLISH.BIN`.

One offset trap worth restating, because the table above is written from the
chunk header: the *payload* a reader is handed starts 8 bytes later, so
`LanguageEnum` is at payload+72 and the arrays begin at payload+100, not 80
and 108. `LanguageDescription` is exactly 100 bytes -- `bNode`(8) +
`FileName[64]` + `LanguageEnum`(4) + three counts(12) + three dead
pointers(12) -- which is the arithmetic to check a port against.
