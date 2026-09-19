#ifndef NFSHP2_HEAPCFG_H
#define NFSHP2_HEAPCFG_H

#include <3ds.h>

// Filled in by __system_allocateHeaps() (heapcfg.c) before main() runs, so
// initPlatformPerf() can log what the console actually handed over instead of
// what this build asked for. Plain integers only: this struct is populated
// before the malloc heap exists, so the code that writes it cannot allocate,
// cannot printf, and cannot touch the filesystem.
typedef struct {
	u32 commitMax;    // RESLIMIT_COMMIT limit -- this IS the APPMEMTYPE grant
	u32 commitUsed;   // already committed when we ran (code + data + bss)
	u32 avail;        // commitMax - commitUsed, 4K aligned
	u32 linearAsked;  // the first linear size we tried
	u32 linearGot;    // what we actually got
	u32 linearTries;  // 1 = the first ask succeeded, >1 = the cap was too high
	u32 linearFailRc; // last failing Result from the linear step-down
	u32 heapAsked;
	u32 heapGot;
	u32 heapTries;
	u32 heapFailRc;
	u32 queryFailed;  // 1 = svcGetResourceLimit failed and avail is a guess
} NfsHeapInfo;

extern NfsHeapInfo g_heapInfo;

#endif
