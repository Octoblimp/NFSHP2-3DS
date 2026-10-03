// copmanager -- the global that points at tCopManager, and the two lookups
// the drive camera makes through it.
//
// tCopManager is 10472 bytes (.mdebug type#5615) and task 26's: the
// pursuit, the roadblocks, the helicopter, Be A Cop's siren. Ported code
// reads only the pointer, to test it and hand it to seams, so the struct
// stays incomplete. tCop and tPursuit are the prefixes the drive camera
// reads; task 26 finishes them.

#ifndef COPMANAGER_H
#define COPMANAGER_H

#include <stddef.h>
#include <stdint.h>

struct Car;

typedef struct tCopManager tCopManager;
typedef struct tPursuit tPursuit;
typedef struct tCop tCop;

// The demo's type#5558 is 32 bytes; these are its first two words.
struct tCop {
    tPursuit   *pMyPursuit;             //  0 NULL while not chasing
    struct Car *pMyCar;                 //  4
};

struct tPursuit {
    uint8_t     Unported[16];           //  0
    struct Car *pChasedCar;             // 16, the demo's 20
};

// gp-15620, 0x00331bec (the demo's gp-16500). NULL outside a race with
// cops, and NULL in the port until tCopManager exists.
extern tCopManager *pCopManager;

// tCopManager's head as Player::SetInputMode reads it, inline: the
// demo's nPlayerCopIndex and Cops[7] were at 8 and 12, and retail's are
// a word later.
typedef struct tCopManagerHead {
    uint8_t  Unported[12];                //  0
    int32_t  nPlayerCopIndex;             // 12  -1 for none
    tCop    *Cops[7];                     // 16
} tCopManagerHead;

// Be A Cop's player cop: Cops[nPlayerCopIndex], or NULL for -1. Retail
// then reads the cop's pMyCar with no test, through NULL when there is
// none; the port's callers test. A NULL manager has none here.
static inline tCop *copmanager_get_player_cop(tCopManager *m)
{
    const tCopManagerHead *h = (const tCopManagerHead *)(const void *)m;

    if (h == NULL || h->nPlayerCopIndex == -1)
        return NULL;
    return h->Cops[h->nPlayerCopIndex];
}

// tCopManager::GetCopByCar (0x00224f70), the cop driving `c`, and
// GetCopByChase (0x00224fc8), the cop chasing it. Seams until task 26; a
// NULL seam finds no cop.
extern tCop *(*gCopManagerGetCopByCarFn)(tCopManager *m, struct Car *c);
extern tCop *(*gCopManagerGetCopByChaseFn)(tCopManager *m, struct Car *c);

#endif
