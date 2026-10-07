// cameracoord -- CameraCoordinator.obj (0x00199a98 .. 0x0019c0d0), in
// part: the coordinators' base and their list, TheCameraLoader and the
// camera chunks it keeps, the CameraDataItems parser, and
// CountdownCameraCoordinator.
//
// A camera coordinator owns a CameraMover and swaps it as the race goes
// on. Each one is on CameraCoordinatorList from its constructor to its
// destructor, and UpdateCameraCoordinators runs the Update of each that is
// not disabled, once a frame.
//
// The camera data are slot 13 of the loader table: four lists of cameras
// (each track bundle's highlight and fly-by cameras, INGAMEB's pre-race and
// post-race ones), the NIS cameras and the shakes. A camera is a block of
// numbers and arrays that CameraDataItems(char*) reads in place; the lists
// keep pointers to the blocks. No bundle on the retail disc has a camera
// named COUNTDOWN_n, so the countdown's coordinator never finds one and
// never builds a mover: the player's UpdateNonGameState then gives the car
// its drive camera, all through the countdown.
//
// Not ported here: the Demo, FlyBy, PreRace, PostRace and NIS coordinators
// (0x0019a440 .. 0x0019b6a4) and BumperCameraMover, which four of them
// build. Written up in docs/formats/camera-coordinator.md and checked on
// retail's image by tools/cameracoord_check.py.
#ifndef CAMERACOORD_H
#define CAMERACOORD_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "cammover.h"
#include "trackcarcam.h"

struct Car;
struct Player;

// ------------------------------------------------------------ the loader

// TheCameraLoader, retail's 0x00310370. The demo's .mdebug record is 2528
// bytes (type#2795); retail's is 2596, its readers' offsets: retail put the
// two players' NIS cameras between the NIS list and the shakes, and the
// rest moved on 72 bytes. The names are the demo's, the two new fields the
// port's.
#define CAMERA_LOADER_HIGHLIGHTS 512
#define CAMERA_LOADER_LIST 32
#define CAMERA_LOADER_NIS 8

typedef struct CameraLoader {
    int32_t      NumHighlightCameras;                         //    0
    char        *HighlightCameraData[CAMERA_LOADER_HIGHLIGHTS]; //  4
    int32_t      NumFlyByCameras;                             // 2052
    char        *FlyByCameraData[CAMERA_LOADER_LIST];         // 2056
    int32_t      NumPreRaceCameras;                           // 2184
    char        *PreRaceCameraData[CAMERA_LOADER_LIST];       // 2188
    int32_t      NumPostRaceCameras;                          // 2316
    char        *PostRaceCameraData[CAMERA_LOADER_LIST];      // 2320
    int32_t      NumNisCameras;                               // 2448
    char        *NisCameraData[CAMERA_LOADER_NIS];            // 2452
    int32_t      NumPlayerNisCameras[2];                      // 2484
    char        *PlayerNisCameraData[2][CAMERA_LOADER_NIS];   // 2492
    int32_t      NumCameraShakes;                             // 2556
    CameraShake *Shakes;                                      // 2560
    uint8_t      _pad2564[12];                                // 2564
    bVector3     TuningVortex;                                // 2576
    int32_t      VortexCount;                                 // 2592
} CameraLoader;                                               // 2596

#if UINTPTR_MAX == 0xffffffffu
typedef char cameraloader_layout_check[
    (offsetof(CameraLoader, NumFlyByCameras) == 2052
     && offsetof(CameraLoader, NumPreRaceCameras) == 2184
     && offsetof(CameraLoader, NumPostRaceCameras) == 2316
     && offsetof(CameraLoader, NumNisCameras) == 2448
     && offsetof(CameraLoader, NumPlayerNisCameras) == 2484
     && offsetof(CameraLoader, PlayerNisCameraData) == 2492
     && offsetof(CameraLoader, NumCameraShakes) == 2556
     && offsetof(CameraLoader, TuningVortex) == 2576
     && offsetof(CameraLoader, VortexCount) == 2592) ? 1 : -1];
#endif

// The chunks. Each list is a container of its cameras; the highlights'
// also holds the vortex, 16 bytes and a count.
#define CAMERA_CHUNK_HIGHLIGHTS  0x80034405u
#define CAMERA_CHUNK_PRE_RACE    0x80034410u
#define CAMERA_CHUNK_POST_RACE   0x80034415u
#define CAMERA_CHUNK_NIS         0x80034420u
#define CAMERA_CHUNK_FLY_BY      0x80034425u
#define CAMERA_CHUNK_SHAKES      0x00034492u
#define CAMERA_CHUNK_VORTEX      0x00034440u
#define CAMERA_CHUNK_HIGHLIGHT   0x00034450u
#define CAMERA_CHUNK_PRE_RACE_CAMERA  0x00034460u
#define CAMERA_CHUNK_POST_RACE_CAMERA 0x00034470u
#define CAMERA_CHUNK_NIS_CAMERA  0x00034480u
#define CAMERA_CHUNK_FLY_BY_CAMERA    0x00034490u

extern CameraLoader TheCameraLoader;

// 0x00199c80, run by the list's static constructor: the five list counts,
// the two players' NIS counts (a bMemSet of 8), the vortex's x, y and z
// and its count are zeroed. The shakes are not.
void camera_loader_init(CameraLoader *cl);

// 0x00199cd8. A list's container sets its count to 0 and appends each
// child of the list's type, by its payload, aligned as every chunk is to
// 16 past the header; children of other types are passed over, and no
// count is bounded. The NIS list is appended to without being cleared.
// The highlights' vortex child copies its 16 bytes to TuningVortex and the
// word after them to VortexCount. The shakes are the payload, size / 560
// of them, unsigned. Each of the six marks the coordinators' camera data
// for a reload and returns 1; any other chunk returns 0.
int camera_loader_load(CameraLoader *cl, uint8_t *chunk);

// 0x0019a010. The four lists and the shakes have their count zeroed; the
// highlights' vortex stays. The NIS container is matched against the two
// players' NIS lists, not the loader's own: every time one of its cameras
// is found in either player's list counts one, and the total comes off
// the count of the last list one was found in. 1, or 0 for any other
// chunk. Nothing is marked.
int camera_loader_unload(CameraLoader *cl, uint8_t *chunk);

// 0x0019a1b8. NULL for bank 0. Otherwise one of the bank's shakes, drawn
// with bRandom on bDefaultSeed over how many there are, or NULL if there
// are none (no draw then). Nothing in retail calls it.
CameraShake *camera_loader_find_random_camera_shake(CameraLoader *cl,
                                                    int32_t bank);

// 0x0019a280. The first camera, highlights then fly-by, pre-race and
// post-race, whose name is `name` to bStrICmp, as its raw block; NULL if
// none is. The NIS cameras are not looked at.
char *camera_loader_find_camera_data(CameraLoader *cl, const char *name);

// 0x0019a3e8, which has no symbol (the name is the port's):
// NisManager::NisLoadedCallback hands its player's index. The NIS count
// and all eight NIS pointers go to that player's, and the NIS count is
// zeroed. The index is not bounded.
void camera_loader_keep_nis_cameras(int32_t player);

// LoaderCameras and UnloaderCameras (0x0019a398, 0x0019a3c0): the two on
// TheCameraLoader, slot 13 of the loader table.
int loader_cameras(uint8_t *chunk);
int unloader_cameras(uint8_t *chunk);

// ---------------------------------------------------- CameraDataItems

// 0x0019b6b0. Reads a camera's block into `cd`. Type, at 0, and Name, the
// block's 32 bytes at 4, are set for any type. Types 0, 1 and 2 then read
// their numbers in their order and point FOVTable (512 bytes, after a pad
// of 8 for types 0 and 2 and 12 for type 1), EyeVerts, BankVerts (as many
// as EyeVerts), type 1's and 2's LookVerts, AreaFaces and AreaVerts, each
// after the last, into the block. Type 0 is the highlights' spring camera:
// no look spline, so LookSplineSpeed, LockLookSpeedToCar, NumLookVerts and
// LookVerts are zeroed. Types 1 and 2 zero the spring's five and
// ShakeBankNumber, and only type 2 reads FOVSplineSpeed. What a type does
// not set it leaves as it was. Returns `cd`.
CameraDataItems *camera_data_items_parse(CameraDataItems *cd, char *data);

// ------------------------------------------------------- the coordinators

// BaseCameraCoordinator, 28 bytes (the demo's type#2329, retail's the
// same). The vptr is the image's table address, in vtable.h's way.
typedef struct BaseCameraCoordinator {
    bNode        Node;                    //  0  on CameraCoordinatorList
    CameraMover *pCameraMover;            //  8
    int32_t      Disabled;                // 12
    int32_t      ViewID;                  // 16
    int32_t      NeedToReloadCameraData;  // 20
    uint32_t     _vtable;                 // 24
} BaseCameraCoordinator;

// CountdownCameraCoordinator, 36 bytes (type#2371).
typedef struct CountdownCameraCoordinator {
    BaseCameraCoordinator Base;           //  0
    struct Player *pPlayer;               // 28
    int32_t      CurrentCountdownNumber;  // 32
} CountdownCameraCoordinator;

#if UINTPTR_MAX == 0xffffffffu
typedef char cameracoord_layout_check[
    (sizeof(BaseCameraCoordinator) == 28
     && offsetof(BaseCameraCoordinator, pCameraMover) == 8
     && offsetof(BaseCameraCoordinator, _vtable) == 24
     && offsetof(CountdownCameraCoordinator, pPlayer) == 28
     && sizeof(CountdownCameraCoordinator) == 36) ? 1 : -1];
#endif

// The tables: _vt$21BaseCameraCoordinator, whose Update is the pure
// virtual (0x002a0550), and _vt$26CountdownCameraCoordinator. Slot 8 is
// the destructor, with its flags; 16 is Update(float).
#define BASECAMERACOORDINATOR_VTABLE      0x002b52f8u
#define COUNTDOWNCAMERACOORDINATOR_VTABLE 0x002b5298u
#define CAMERACOORDINATOR_VT_DTOR   8
#define CAMERACOORDINATOR_VT_UPDATE 16
#define CAMERACOORDINATOR_VT_ENTRIES 3

// CameraCoordinatorList, gp-19920: a bTList<BaseCameraCoordinator>.
extern bNode CameraCoordinatorList;

// 0x00192398 in the demo (retail's 0x0019c058),
// _GLOBAL_$I$CameraCoordinatorList: the list made empty and
// TheCameraLoader built.
void cameracoord_static_init(void);

// 0x00199a98. The coordinator goes on the list's tail, with the base's
// table, the view, no mover, not disabled and nothing to reload.
BaseCameraCoordinator *camera_coordinator_init(BaseCameraCoordinator *c,
                                               int32_t viewID);

// 0x00199ad8. The base's table back; the mover deleted by its own
// deleting destructor (the pointer is left as it was); off the list; and
// freed if flags has bit 0.
void camera_coordinator_destroy(BaseCameraCoordinator *c, int32_t flags);

// The deleting destructor by the table, slot 8 with flags 3, as Player's
// and the RaceCoordinator's deletes call it.
void camera_coordinator_delete(void *c);

// 0x00199b48 and 0x00199b90. Each does nothing if the coordinator is
// already that way; otherwise it sets Disabled and, with a mover, calls
// the mover's own Disable or Enable by its table.
void camera_coordinator_disable(void *c);
void camera_coordinator_enable(void *c);

// 0x00199c40: NeedToReloadCameraData set on every coordinator on the list.
void mark_camera_data_as_needing_to_be_reloaded(void);

// 0x00199bd0: each coordinator on the list, from the head, that is not
// disabled has its Update called by its table. The next is read after the
// call.
void update_camera_coordinators(float dt);

// ------------------------------------------------------------ the countdown

// What CountdownCameraCoordinator::Update builds for a number with camera
// data: BumperCameraMover's constructor (0x00158800) on 1116 bytes of
// bMalloc's, with the coordinator's view and its player's car. Not ported:
// NULL, and then nothing is allocated and the coordinator has no mover.
// The retail disc never gets this far.
extern CameraMover *(*gBumperCameraMoverFn)(void *mem, int32_t viewID,
                                            struct Car *car,
                                            CameraDataItems *cd);

// 0x0019b130. The base's constructor, the player, the countdown's table, a
// number of -1, and one Update(0).
CountdownCameraCoordinator *countdown_camera_coordinator_init(
    CountdownCameraCoordinator *c, int32_t viewID, struct Player *p);

// The constructor as playerupdate.c's gCountdownCameraCoordinatorFn calls
// it, on the 36 bytes it bMallocs.
CountdownCameraCoordinator *countdown_camera_coordinator_construct(
    void *mem, int32_t viewID, struct Player *p);

// 0x0019b188: the countdown's table, then the base's destructor.
void countdown_camera_coordinator_destroy(CountdownCameraCoordinator *c,
                                          int32_t flags);

// 0x0019b1a0. Nothing while the race's countdown number to display is the
// one it has. When it changes, the mover is deleted and cleared; the
// camera named COUNTDOWN_<number> is looked up, and if it is found a
// BumperCameraMover is built on it; and the number is kept. dt is unread.
void countdown_camera_coordinator_update(CountdownCameraCoordinator *c,
                                         float dt);

// The two tables, into vtable.h's registry. main.c calls it at boot.
void cameracoord_install_vtables(void);

#endif
