// copmanager -- the global that points at tCopManager, the two lookups the
// drive camera makes through it, and the HUD's busted-text test.
//
// tCopManager is 10472 bytes (.mdebug type#5615) and task 26's: the
// pursuit, the roadblocks, the helicopter, Be A Cop's siren. Ported code
// reads the pointer, to test it and hand it to seams, and the few fields
// below in place, so the struct stays incomplete. tCop and tPursuit are
// the prefixes the drive camera reads; task 26 finishes them.

#ifndef COPMANAGER_H
#define COPMANAGER_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "bvector.h"

struct Car;

typedef struct tCopManager tCopManager;
typedef struct tPursuit tPursuit;
typedef struct tCop tCop;

// The demo's type#1303 is 120 bytes: a roadblock a pursuit called. These
// are the two fields the minimap reads, at the demo's offsets, which
// retail's TrackMap::Render reads them at too. The two cops' pointers at
// 0 are bytes here, so the offsets hold on any host.
typedef struct tRoadBlock {
    uint8_t  Unported0[28];             //   0
    uint16_t aTrackMapIconAngle;        //  28  a BAM
    uint8_t  Unported30[38];            //  30
    bVector2 v2Position;                //  68
    uint8_t  Unported76[44];            //  76
} tRoadBlock;                           // 120

typedef char troadblock_layout_check[
    (offsetof(tRoadBlock, aTrackMapIconAngle) == 28
     && offsetof(tRoadBlock, v2Position) == 68
     && sizeof(tRoadBlock) == 120) ? 1 : -1];

// The demo's type#5558 is 32 bytes; these are its first two words.
struct tCop {
    tPursuit   *pMyPursuit;             //  0 NULL while not chasing
    struct Car *pMyCar;                 //  4
};

// bTNode<tPursuit>: a pursuit's links in the manager's PursuitList. The
// list's own node is the sentinel, so the last pursuit's Next is the list.
typedef struct tPursuitNode {
    struct tPursuitNode *Next;          //  0
    struct tPursuitNode *Prev;          //  4
} tPursuitNode;

// The demo's type#1640 is 1216 bytes; retail's is longer and these are
// the words read so far, at retail's offsets on a 32-bit target. The
// demo's nHUDPursuitLevel was at 1112.
struct tPursuit {
    tPursuitNode Node;                  //    0
    uint8_t     Unported8[8];           //    8
    struct Car *pChasedCar;             //   16, the demo's 20
    tRoadBlock *pRoadBlock;             //   20, the demo's 24; NULL for none
    uint8_t     Unported24[1468];       //   24
    int32_t     nHUDPursuitLevel;       // 1492  the HUD's pursuit meter
    uint8_t     Unported1496[64];       // 1496
    // Retail's. RenderHud lights one more Be The Cop roadblock, in the
    // "on its way" colour, while it is set.
    int32_t     New1560;                // 1560
};

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char tpursuit_layout_check[
    (offsetof(struct tPursuit, pChasedCar) == 16
     && offsetof(struct tPursuit, pRoadBlock) == 20
     && offsetof(struct tPursuit, nHUDPursuitLevel) == 1492
     && offsetof(struct tPursuit, New1560) == 1560) ? 1 : -1];
#endif

// gp-15620, 0x00331bec (the demo's gp-16500). NULL outside a race with
// cops, and NULL in the port until tCopManager exists.
extern tCopManager *pCopManager;

// tCopManager's head as Player::SetInputMode and RenderHud read it,
// inline: the demo's nPlayerCopIndex, Cops[7] and PursuitList were at 8,
// 12 and 40, and retail's are a word later. Retail's word at 0 is new;
// RenderHud lights that many of Be The Cop's roadblocks as used. On a
// 64-bit host the head ends at 88, where the pullovers start, so their
// byte offsets hold there too.
typedef struct tCopManagerHead {
    int32_t  New0;                        //  0
    uint8_t  Unported4[8];                //  4
    int32_t  nPlayerCopIndex;             // 12  -1 for none
    tCop    *Cops[7];                     // 16
    tPursuitNode PursuitList;             // 44  bTList<tPursuit>
} tCopManagerHead;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char tcopmanagerhead_layout_check[
    (offsetof(tCopManagerHead, Cops) == 16
     && offsetof(tCopManagerHead, PursuitList) == 44) ? 1 : -1];
#endif

static inline tCopManagerHead *copmanager_head(tCopManager *m)
{
    return (tCopManagerHead *)(void *)m;
}

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

// tCarPulloverInfo (type#5538), 28 bytes: a car a cop has pulled over.
// tCopManager holds eight, CarPullovers, at 88 in retail (the demo's 56).
typedef struct tCarPulloverInfo {
    int32_t nCopIndex;                    //  0
    float   fHoldTimer;                   //  4
    int8_t  nNumTickets;                  //  8
    int32_t bActive;                      // 12
    int32_t bPlayNIS;                     // 16
    int32_t bArrest;                      // 20
    int32_t bShouldDisplayBustedText;     // 24
} tCarPulloverInfo;

typedef char tcarpulloverinfo_size_check[
    sizeof(tCarPulloverInfo) == 28 ? 1 : -1];

#define COPMANAGER_PULLOVERS        88
#define COPMANAGER_NUM_PULLOVERS    8

// Words past the pullovers, by retail's byte offset; none holds a pointer.
// Each is the demo's named field 32 bytes on.
#define COPMANAGER_CHOPPER_BUSY     312    // bChopperBusy, an int
#define COPMANAGER_CAR_DAMAGE       10420  // fCarDamage[14], by CarIndex
#define COPMANAGER_BEACOP_TIME      10480  // fBeACopTime, seconds
#define COPMANAGER_BEACOP_CHOPPERS  10492  // nBeACopNumChopperAttacks

// The word at 960 of the World's Chopper that 0x00224ec0 wants 0 before
// a helicopter can be called (hudrender.c's can_call_helicopter).
#define CHOPPER_NEW960              960

static inline int32_t copmanager_word(const tCopManager *m, size_t off)
{
    int32_t v;

    memcpy(&v, (const uint8_t *)m + off, sizeof v);
    return v;
}

static inline float copmanager_float(const tCopManager *m, size_t off)
{
    float v;

    memcpy(&v, (const uint8_t *)m + off, sizeof v);
    return v;
}

// tCopManager::ShouldDisplayBustedText, 0x002289f8: 1 if any pullover is
// active and has bShouldDisplayBustedText, the first such ending the
// search. The manager must be there.
int32_t copmanager_should_display_busted_text(const tCopManager *m);

// tCopManager::IsBeingPursued, 0x00227438: the first pursuit in
// PursuitList whose pChasedCar is `c`, or NULL.
tPursuit *copmanager_is_being_pursued(tCopManager *m, struct Car *c);

// tCopManager::GetPursuitLevelForHUD, 0x00227480: that pursuit's
// nHUDPursuitLevel, or 0 for none.
int32_t copmanager_get_pursuit_level_for_hud(tCopManager *m,
                                             struct Car *c);

// tCopManager::GetNumTickets, 0x00228520: the signed byte nNumTickets of
// CarPullovers[c->CarIndex], the index read as a short.
int32_t copmanager_get_num_tickets(tCopManager *m, struct Car *c);

// tCopManager::GetNumActiveRoadBlocks, 0x00226968: how many pursuits in
// PursuitList have a pRoadBlock.
int32_t copmanager_get_num_active_road_blocks(tCopManager *m);

// tCopManager::GetActiveRoadBlock, 0x00226238: the pRoadBlock of the
// i-th pursuit in PursuitList that has one, counting from 0, or NULL.
tRoadBlock *copmanager_get_active_road_block(tCopManager *m, int32_t i);

// tCopManager::GetCopByCar (0x00224f70), the cop driving `c`, and
// GetCopByChase (0x00224fc8), the cop chasing it. Seams until task 26; a
// NULL seam finds no cop.
extern tCop *(*gCopManagerGetCopByCarFn)(tCopManager *m, struct Car *c);
extern tCop *(*gCopManagerGetCopByChaseFn)(tCopManager *m, struct Car *c);

#endif
