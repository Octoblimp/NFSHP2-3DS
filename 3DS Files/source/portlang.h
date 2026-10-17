#pragma once
#include <stddef.h>
#include <stdint.h>

// The port's own strings, for what retail never had to say: local wireless
// play (TASKS 37). They take LanguageIDs from PORTLANG_FIRST, well past
// retail's last (980002), and langtab_get() answers them from here, so a
// text object, a popup's button or a blurb takes one like any other ID.
//
// Each has the six languages retail ships, in retail's encoding (Latin-1:
// the accents are the high bytes). FE_LONGEST gets the longest of the six
// and FE_ID the ID's own number, as retail's tables do.
//
// Host-buildable: no <3ds.h> here.

#define PORTLANG_FIRST 2000000

enum {
    PORTLANG_LOCAL_WIRELESS = PORTLANG_FIRST,   // the Players value
    PORTLANG_LOCAL_WIRELESS_BLURB,              // its blurb
    PORTLANG_HOST,                              // the lobby's two choices
    PORTLANG_JOIN,
    PORTLANG_HOST_OR_JOIN,                      // the question
    PORTLANG_SEARCHING,                         // a joiner's scan
    PORTLANG_FOUND,                             // a race: host, $N/$MAX
    PORTLANG_NEXT,                              // the next race found
    PORTLANG_WAITING_FOR_PLAYERS,               // the host's list
    PORTLANG_WAITING_FOR_HOST,                  // a joiner's wait
    PORTLANG_START,                             // the host's go
    PORTLANG_LINK_LOST,                         // the host left
    PORTLANG_WIRELESS_OFF,                      // UDS would not start
    PORTLANG_JOIN_FAILED,
    PORTLANG_WAITING_FOR_CARS,                  // the host's, for their cars
    PORTLANG_CPU_RACERS,                        // the host's count: button
    PORTLANG_CPU_RACERS_N,                      // and line, $N of them
    PORTLANG_WIRELESS_DISABLED,                 // the HOME Menu's switch off
    PORTLANG_HOST_MODE,                         // Host's question, TASKS 63
    PORTLANG_RECONNECTING,                      // a race held, $N left (37g)
    PORTLANG_CPU_DRIVES,                        // past it, $NAME's car
    PORTLANG_CATCHING_UP,                       // back after a restart
                                                // (37g-3), $N percent
    PORTLANG_COMING_BACK,                       // and $NAME's, to the rest
    PORTLANG_SURROUND,                          // Audio Mode's third value,
                                                // for Dolby Pro Logic II
    PORTLANG_RACER,                             // Controller's two tables
    PORTLANG_COP,
    PORTLANG_ROADBLOCK,                         // the cop's two calls
    PORTLANG_HELICOPTER,
    PORTLANG_CONTROLS_BLURB,                    // the page's bottom screen
    PORTLANG_CONTROLS_PRESS,                    // and its wait, $NAME's key
    PORTLANG_SAVE_CHANGES,                      // a screen's prompt on the
    PORTLANG_SAVE_CHANGES_RACE,                 // way out, and the debug race's
    PORTLANG_END
};

// The string for `id` in `languageEnum` (LangEnum), or NULL when the ID is
// not the port's. *outLen is its length; it is NUL-terminated too.
const char* portlang_get(int32_t languageEnum, int32_t id, size_t* outLen);

// The port's wording of one of retail's own IDs in `languageEnum`, or NULL
// to keep retail's: the memory card's messages and the Load/Save screen's
// help lines name the 3DS's SD Card and no MEMORY CARD slot (TASKS 52).
// LANG_LONGEST and LANG_ID_NUM keep retail's. langtab_get() asks this
// before the table on the disc.
const char* portlang_retail(int32_t languageEnum, int32_t id,
                            size_t* outLen);
