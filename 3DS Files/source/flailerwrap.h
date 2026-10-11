// flailerwrap -- FEFlailer.obj from retail: text word-wrapped into a group of
// Flailer text objects.
//
//   isspace(int)                0x00144a68    44 bytes
//   WriteTextIntoChunk          0x00144ae8   112 bytes
//   RenderTextIntoGroup         0x00144ba0   644 bytes
//
// bpopup.c has the same on the flow's BUI screens, for the frontend's
// popups and the end of the race's screens. This one works on flailer.c's
// chunks, as the HUD's are. Slice RE-2c, for the race-over overlay
// (raceovermsg.c). docs/formats/race-over-overlay.md has the decode.

#ifndef FLAILERWRAP_H
#define FLAILERWRAP_H

#include <stdint.h>

// `str` word-wrapped into the text objects of `group` on `screen`, one line
// each in the order FindFlailerObjectByGroup finds them, up to 32:
//   - a line breaks at a space, a tab or '@', and '@' always breaks it;
//   - a line is cut at its last break once it reaches MaxChars - 2
//     characters, so a word longer than a line runs on past it;
//   - the character after a break is not tested, so "@ @" is a blank line;
//   - each line is made visible and set with SetString;
//   - the objects left over have their visibility byte cleared.
// Answers (int)(TopLeftY + GetScaledHeight) of the first object left over,
// or of the last one when every one was used. Answers 0 when the group has
// no text objects, or the text ran out of objects.
int32_t flailer_render_text_into_group(uint32_t screen, uint32_t group,
                                       const char *str);

#endif
