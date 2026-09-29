// Heap split configuration.
//
// app.rsf asks for the largest APPLICATION region each console will give
// (96MB on Old3DS, 178MB on New3DS -- see meta/app.rsf). That grant works:
// a New 3DS XL reported RESLIMIT_COMMIT == 0x0B200000, exactly 178MB, so the
// kernel read the ExHeader, checked the model and handed the memory over.
//
// Dividing it up is the part that needed fixing, and the first attempt at it
// crashed on real hardware. What follows is why, because the reason is not
// obvious and it would be easy to reintroduce.
//
// A 3DS process has two heaps:
//   * the "linear" heap -- PHYSICALLY CONTIGUOUS and GPU-visible. This is
//     what linearAlloc() hands out, so every C3D_Tex (texpack.c, and
//     avimovie.c's video textures), every VBO (model3d.c) and every ndsp
//     audio buffer (audio.c, main.c) lives here.
//   * the ordinary malloc heap -- normal CPU memory, backing every malloc()
//     in the port: whole-file .BUN/.LZC loads, COMP output buffers,
//     DXT->RGBA decode scratch.
//
// libctru 2.4.1 splits the available memory A like this when both of its weak
// size globals are zero (disassembled out of the shipped libctru.a, since
// only the headers are installed here):
//     linear = align4K(A / 2); heap = A - linear;
//     if (heap > 24MB) { heap = 24MB; linear = A - 24MB;
//                        if (linear > 32MB) { linear = 32MB; heap = A - 32MB; } }
// For any A above ~56MB that always lands on "linear = 32MB, malloc heap =
// everything else". The linear heap is hard-capped at 32MB, so a 96MB or
// 178MB grant under the stock policy would pour every extra byte into the
// malloc heap and leave GPU-visible memory exactly where it started -- no
// more textures, no more geometry, the opposite of what the RAM is for.
//
// The same function has a second branch: __ctru_heap_size non-zero with
// __ctru_linear_heap_size zero gives "linear = A - __ctru_heap_size", with no
// cap. Setting only __ctru_heap_size = 28MB was the first attempt, and it is
// what broke the New 3DS XL:
//
//     prefetch abort (svcBreak: panic), pc = svcBreak, lr = allocateHeaps.c:71
//     r4 = 0x09506000   <- the size it asked for: 148.8MB
//     [sp] = 0x00010003 <- MEMOP_ALLOC_LINEAR
//
// i.e. it asked svcControlMemory for ONE PHYSICALLY CONTIGUOUS 148.8MB block
// and the kernel refused. libctru answers any allocation failure with an
// unconditional svcBreak(USERBREAK_PANIC), so the app died before main().
// The 28MB malloc heap allocated immediately before it succeeded, because
// MEMOP_ALLOC does not require contiguity.
//
// Address space is not the constraint: OS_FCRAM_VADDR is 0x30000000 with
// OS_FCRAM_SIZE 256MB, so 148.8MB of VA was there for the taking. Physical
// contiguity is. Old3DS FCRAM is 128MB at 0x20000000 and New3DS adds a second
// 128MB above it, so a 178MB APPLICATION region necessarily straddles the
// 0x28000000 boundary and cannot contain a single free 148.8MB run. Azahar
// never saw this: its HLE memory manager serves linear allocations out of one
// contiguous host buffer, so it happily validated a layout the real kernel
// rejects. Same class of emulator blind spot as the dsp::DSP /
// IORegisterMapping incident recorded in app.rsf, and the exact risk
// TASKS.md #112 called out.
//
// So: cap the linear ask instead of taking the whole grant. That cap used to
// be a flat 96MB, chosen to sit "comfortably inside" the first physical half.
// It is now DERIVED, because a fixed 96MB left a New 3DS with exactly the same
// GPU-visible memory as an Old one despite an 82MB larger grant -- the whole
// point of asking for the bigger region.
//
// The real ceiling is the largest single contiguous run the kernel can find,
// and userland cannot compute that: it depends on where the kernel placed the
// APPLICATION region and how much of the first bank our own code/data/bss
// already occupies. So do not try. Bound the ask by the one hard fact we do
// know -- a linear block cannot straddle the FCRAM bank boundary at
// 0x28000000, so it can never exceed one 128MB bank -- and let the step-down
// retry loop DISCOVER the rest. That loop already exists and is already
// failure-tolerant; this just gives it a starting point worth descending from
// rather than one picked to never fail.
//
// LINEAR_STEP is deliberately fine (4MB): the step-down is now doing real
// work rather than being a safety net that never fires, and each step it
// takes is memory left on the table. Worst case on an Old 3DS it makes a
// handful of extra svcControlMemory calls before it settles, all of them
// before main().
//
// g_heapInfo.linearTries records how many it took, so the true per-model
// ceiling is in the boot log rather than being guessed at here.
//
// Two smaller decisions worth recording:
//   * The linear heap is allocated FIRST, before the malloc heap. Only the
//     linear one needs contiguity, so it should get its block while the
//     region is least fragmented; the malloc heap can take scattered pages
//     afterwards. Stock libctru does it the other way round.
//   * Neither allocation can panic. Each steps its request down and retries,
//     so a LINEAR_CAP that is still too high for some console or some future
//     memory mode costs a few megabytes and a log line rather than a dead
//     boot. That is the whole reason this function is replaced rather than
//     just setting the two size globals: the stock one svcBreak()s.
//
// Nothing here needs to know which console it is running on. RESLIMIT_COMMIT
// already reflects the APPMEMTYPE the kernel picked from app.rsf, so "avail"
// comes out at 178MB-ish on a New3DS and 96MB-ish on an Old3DS by itself.
//
// g_heapInfo records what was asked for and what came back, and
// initPlatformPerf() in main.c logs it, so the true hardware ceiling is
// measurable rather than guessed at and LINEAR_CAP can be tuned from
// evidence.

#include <3ds.h>
#include <3ds/allocator/mappable.h>
#include "heapcfg.h"

// libctru heap globals, defined in allocateHeaps.o and not declared in any
// installed header. The two _size ones are weak (nm reports 'V'); the two
// pointers are ordinary .bss ('B'). All four are a contract with the rest of
// libctru, so whatever this file allocates must be recorded in them exactly:
//   * linear.o builds its allocator pool from __ctru_linear_heap /
//     __ctru_linear_heap_size on the first linearAlloc() call.
//   * __libctru_exit() frees precisely (__ctru_linear_heap, size) and then
//     (__ctru_heap, size) with MEMOP_FREE.
extern u32 __ctru_heap;
extern u32 __ctru_heap_size;
extern u32 __ctru_linear_heap;
extern u32 __ctru_linear_heap_size;

// newlib sbrk window. initSystem() carves the main thread stack
// (__stacksize__, 32KB) off the front of it immediately after we return, so
// the malloc heap must always stay substantially larger than that.
extern char* fake_heap_start;
extern char* fake_heap_end;

NfsHeapInfo g_heapInfo;

#define HEAP_WANT   (28u * 1024 * 1024)  // what the old 64MB grant effectively gave
#define HEAP_MIN    ( 4u * 1024 * 1024)
#define HEAP_STEP   ( 4u * 1024 * 1024)

// FCRAM is organised in 128MB physical banks (Old3DS has one at 0x20000000,
// New3DS adds a second above it). A physically contiguous block cannot cross
// the boundary between them, so one bank is the absolute ceiling on a linear
// allocation no matter how large the APPLICATION grant is. This is the only
// number here that is a hardware fact rather than a policy choice.
#define FCRAM_BANK  (128u * 1024 * 1024)
#define LINEAR_MIN  ( 4u * 1024 * 1024)
#define LINEAR_STEP ( 4u * 1024 * 1024)

#define ALIGN4K(x)  ((u32)(x) & ~0xFFFu)

// Replaces the weak __system_allocateHeaps() in libctru. Called from
// __libctru_init() before main(), after crt0 has already cleared .bss.
void __system_allocateHeaps(void)
{
	s64 commitMax = 0, commitUsed = 0;
	ResourceLimitType kind = RESLIMIT_COMMIT;
	Handle reslimit = 0;
	u32 avail, heapWant, want;
	Result rc;

	// How much this process may commit, minus what loading it already took.
	// The same query stock libctru makes.
	if (R_SUCCEEDED(svcGetResourceLimit(&reslimit, CUR_PROCESS_HANDLE))) {
		svcGetResourceLimitLimitValues(&commitMax, reslimit, &kind, 1);
		svcGetResourceLimitCurrentValues(&commitUsed, reslimit, &kind, 1);
		svcCloseHandle(reslimit);
	}

	if (commitUsed >= 0 && commitMax > commitUsed) {
		avail = ALIGN4K((u32)(commitMax - commitUsed));
	} else {
		// Query failed, so assume the smallest grant any CIA launch path
		// gets (64MB mode, ~1MB already committed). The step-downs below
		// correct it if even that turns out to be optimistic.
		avail = 60u * 1024 * 1024;
		g_heapInfo.queryFailed = 1;
	}

	g_heapInfo.commitMax  = (u32)commitMax;
	g_heapInfo.commitUsed = (u32)commitUsed;
	g_heapInfo.avail      = avail;

	// The malloc heap keeps the 28MB the old 64MB grant effectively gave it,
	// so nothing regresses if the extended grant is ever refused, or on the
	// .3dsx path (which inherits its host process memory and never sees
	// app.rsf at all). Never claim more than half of a small grant.
	heapWant = HEAP_WANT;
	if (heapWant > avail / 2)
		heapWant = ALIGN4K(avail / 2);

	// Everything the malloc heap does not want goes to the linear heap, up to
	// one FCRAM bank. Reserving heapWant here is what guarantees the malloc
	// heap still has commit budget left after the linear heap is taken.
	//
	// On an Old 3DS `avail - heapWant` is ~68MB and is itself the binding
	// limit; on a New 3DS it is ~150MB and the bank ceiling binds instead.
	// Either way the step-down below finds what the kernel will actually give,
	// so this is an upper bound and not a prediction.
	want = avail - heapWant;
	if (want > FCRAM_BANK)
		want = FCRAM_BANK;
	want = ALIGN4K(want);
	g_heapInfo.linearAsked = want;

	// Linear heap first: it is the one that needs a contiguous run, so it
	// should ask while the region is least fragmented. Step down on refusal
	// rather than panicking.
	for (;;) {
		__ctru_linear_heap = 0;
		g_heapInfo.linearTries++;
		rc = svcControlMemory(&__ctru_linear_heap, 0, 0, want,
		                      MEMOP_ALLOC_LINEAR, MEMPERM_READWRITE);
		if (R_SUCCEEDED(rc)) {
			__ctru_linear_heap_size = want;
			g_heapInfo.linearGot = want;
			break;
		}
		g_heapInfo.linearFailRc = (u32)rc;
		if (want <= LINEAR_MIN) {
			__ctru_linear_heap      = 0;
			__ctru_linear_heap_size = 0;
			break;
		}
		want = (want > LINEAR_MIN + LINEAR_STEP) ? (want - LINEAR_STEP)
		                                         : LINEAR_MIN;
	}

	// Malloc heap second, at the fixed 0x08000000 base libctru uses. This one
	// does not need contiguity and its budget was reserved above, so the
	// step-down here is belt and braces.
	want = heapWant;
	g_heapInfo.heapAsked = want;
	for (;;) {
		__ctru_heap = 0;
		g_heapInfo.heapTries++;
		rc = svcControlMemory(&__ctru_heap, OS_HEAP_AREA_BEGIN, 0, want,
		                      MEMOP_ALLOC, MEMPERM_READWRITE);
		if (R_SUCCEEDED(rc)) {
			__ctru_heap_size = want;
			g_heapInfo.heapGot = want;
			break;
		}
		g_heapInfo.heapFailRc = (u32)rc;
		if (want <= HEAP_MIN) {
			// A console that will not give 4MB of ordinary heap cannot run
			// anything: newlib would have no sbrk window, so there would be
			// no state left to report from. Panic honestly, with a known lr,
			// exactly as stock libctru would have.
			svcBreak(USERBREAK_PANIC);
		}
		want = (want > HEAP_MIN + HEAP_STEP) ? (want - HEAP_STEP) : HEAP_MIN;
	}

	// The rest is what stock __system_allocateHeaps() does on the way out.
	mappableInit(OS_MAP_AREA_BEGIN, OS_MAP_AREA_END);

	fake_heap_start = (char*)__ctru_heap;
	fake_heap_end   = fake_heap_start + __ctru_heap_size;
}
