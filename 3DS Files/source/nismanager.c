// nismanager -- the NisManager's state. See nismanager.h.

#include "nismanager.h"

#include <string.h>

#include "bmem.h"
#include "emodel.h"
#include "nisinfo.h"
#include "realtime.h"
#include "replay.h"
#include "world.h"

bNode NisManagerList = { &NisManagerList, &NisManagerList };

void (*gNisManagerLoadFn)(NisManager *m, int32_t nis);
void (*gNisSetupCarsBeforeNisFn)(NisManager *m);
void (*gNisStartAnimatingFn)(NisManager *m);
void (*gNisStopAnimatingFn)(NisManager *m);
void (*gNisRestoreCarsAfterNisFn)(NisManager *m);
void (*gNisUnloadResourceFileFn)(struct ResourceFile *rf);
int32_t (*gNisServiceResourceLoadingFn)(void);

static void clear_model_info(NisModelInfo *mi)
{
    mi->Offset.x = 0.0f;
    mi->Offset.y = 0.0f;
    mi->Offset.z = 0.0f;
    mi->Offset.pad = 0.0f;
    mi->pAnimation = NULL;
    mi->pCarWeStoleAnimationFrom = NULL;
}

// eModel's constructor, inlined: the name hash and the solid.
static void clear_prop(eModel *e)
{
    e->NameHash = 0;
    e->Solid = NULL;
}

NisManager *nismanager_construct(void *mem, const char *name,
                                 int32_t number)
{
    NisManager *m = mem;
    int i;

    m->NisRendInfo.NumFrames = 0;
    clear_model_info(&m->NisRendInfo.PlayerModelInfo);
    clear_model_info(&m->NisRendInfo.OtherModelInfo);
    for (i = 0; i < 2; i++)
        clear_prop(&m->PlayerCharProps[i]);
    for (i = 0; i < 2; i++)
        clear_prop(&m->OtherCharProps[i]);

    m->NisResourceFile = NULL;
    m->LoadedNisNumber = -1;
    m->LoadingNisNumber = -1;
    m->LoadNisNumber = -1;
    m->CamResourceFile = NULL;
    m->PlayerNumber = number;
    strcpy(m->Name, name);
    m->NisNumber = -1;

    // AddTail.
    m->Node.next = &NisManagerList;
    m->Node.prev = NisManagerList.prev;
    NisManagerList.prev->next = &m->Node;
    NisManagerList.prev = &m->Node;

    m->StartTime = 0;
    m->EndTime = 0;
    m->PlayerCar = NULL;
    m->OtherCar = NULL;
    m->Playing = 0;
    m->Animating = 0;
    m->CamNumber = 0;
    m->ViewsWatchingNis = 0;
    m->OtherCarMovementModeBeforeNIS = 0;
    m->PlayerCarMovementModeBeforeNIS = 0;
    return m;
}

void nismanager_destruct(NisManager *m, int32_t flags)
{
    int i;

    if (gNisStopAnimatingFn != NULL)
        gNisStopAnimatingFn(m);
    nismanager_ensure_nis_is_loaded(m);
    if (m->LoadedNisNumber >= 0)
        nismanager_unload(m);
    m->Node.prev->next = m->Node.next;
    m->Node.next->prev = m->Node.prev;
    for (i = 1; i >= 0; i--)
        emodel_delete(&m->OtherCharProps[i], 0);
    for (i = 1; i >= 0; i--)
        emodel_delete(&m->PlayerCharProps[i], 0);
    if (flags & 1)
        bFree(m);
}

NisManager *nismanager_new(void *mem, const char *name, int32_t number)
{
    return nismanager_construct(mem, name, number);
}

void nismanager_delete(NisManager *m)
{
    nismanager_destruct(m, 3);
}

// 0x001b16e0: Load when the NIS is not the loaded one, then
// EnsureNisIsLoaded. Start and a restored snapshot call it.
static void nismanager_load_if_needed(NisManager *m)
{
    if (m->LoadedNisNumber != m->NisNumber) {
        if (gNisManagerLoadFn != NULL)
            gNisManagerLoadFn(m, m->NisNumber);
        nismanager_ensure_nis_is_loaded(m);
    }
}

void nismanager_start(NisManager *m, int32_t nis, int32_t camera,
                      struct Car *player, struct Car *other)
{
    // Retail reads the table untested; without one the port plays for
    // no time.
    int32_t frames = NisInfoTable != NULL ? NisInfoTable[nis].NumFrames : 0;

    m->StartTime = WorldTimeFrames;
    m->CamNumber = camera;
    m->Playing = 1;
    m->NisNumber = nis;
    m->PlayerCar = player;
    m->OtherCar = other;
    m->EndTime = (int32_t)((uint32_t)WorldTimeFrames
                           + ((uint32_t)frames << 1));

    nismanager_load_if_needed(m);
    if (gNisSetupCarsBeforeNisFn != NULL)
        gNisSetupCarsBeforeNisFn(m);
    if (gNisStartAnimatingFn != NULL)
        gNisStartAnimatingFn(m);
}

void nismanager_stop(NisManager *m)
{
    if (m->Playing == 0)
        return;
    if (gNisStopAnimatingFn != NULL)
        gNisStopAnimatingFn(m);
    if (gNisRestoreCarsAfterNisFn != NULL)
        gNisRestoreCarsAfterNisFn(m);
    m->OtherCar = NULL;
    m->CamNumber = -1;
    m->Playing = 0;
    m->StartTime = 0;
    m->EndTime = 0;
    m->NisNumber = -1;
    m->PlayerCar = NULL;
}

int32_t nismanager_is_playing(const NisManager *m)
{
    return m->Playing;
}

int32_t nismanager_allow_debug_looping(const NisManager *m)
{
    (void)m;
    return 0;
}

void nismanager_unload(NisManager *m)
{
    nismanager_ensure_nis_is_loaded(m);
    if (m->LoadedNisNumber < 0)
        return;
    if (gNisUnloadResourceFileFn != NULL) {
        gNisUnloadResourceFileFn(m->NisResourceFile);
        gNisUnloadResourceFileFn(m->CamResourceFile);
    }
    m->LoadedNisNumber = -1;
}

void nismanager_ensure_nis_is_loaded(NisManager *m)
{
    // Without the service nothing would ever finish loading; the port
    // stops waiting rather than spin.
    while (m->LoadingNisNumber >= 0) {
        if (gNisServiceResourceLoadingFn == NULL)
            break;
        gNisServiceResourceLoadingFn();
    }
}

void nismanager_do_snapshot(NisManager *m, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "NisManager");
    if (s->RestoringSnapshotFlag && gNisStopAnimatingFn != NULL)
        gNisStopAnimatingFn(m);
    ReplaySnapshot_MoveInt(s, &m->StartTime, 4);
    ReplaySnapshot_MoveInt(s, &m->EndTime, 4);
    ReplaySnapshot_MoveInt(s, &m->NisNumber, 4);
    world_do_pointer_snapshot(pCurrentWorld, s, &m->PlayerCar);
    world_do_pointer_snapshot(pCurrentWorld, s, &m->OtherCar);
    ReplaySnapshot_MoveInt(s, &m->Playing, 1);
    ReplaySnapshot_MoveInt(s, &m->CamNumber, 1);
    ReplaySnapshot_MoveData(s, &m->OtherCarMovementModeBeforeNIS, 1, -1, 0);
    ReplaySnapshot_MoveData(s, &m->PlayerCarMovementModeBeforeNIS, 1, -1, 0);
    if (s->RestoringSnapshotFlag && m->Playing != 0) {
        nismanager_load_if_needed(m);
        if (gNisStartAnimatingFn != NULL)
            gNisStartAnimatingFn(m);
    }
    ReplaySnapshot_EndSection(s);
}
