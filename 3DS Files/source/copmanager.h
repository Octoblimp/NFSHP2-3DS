// copmanager -- the global that points at tCopManager.
//
// tCopManager is 10472 bytes (.mdebug type#5615) and task 26's: the
// pursuit, the roadblocks, the helicopter, Be A Cop's siren. Ported code
// reads only the pointer, to test it and hand it to seams, so the struct
// stays incomplete.

#ifndef COPMANAGER_H
#define COPMANAGER_H

typedef struct tCopManager tCopManager;

// gp-16500, 0x00324b7c. NULL outside a race with cops, and NULL in the
// port until tCopManager exists.
extern tCopManager *pCopManager;

#endif
