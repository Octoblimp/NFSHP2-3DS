// sky -- see sky.h.

#include "sky.h"

#include <stddef.h>

#include "emath.h"
#include "emodel.h"
#include "scenerycull.h"

eModel   SkydomeModel;                      // 0x002dc600
bMatrix4 SkydomeLocalWorld;                 // 0x002dc620
eModel   SkydomeEnvmapModel;                // 0x002dc660
bMatrix4 SkydomeEnvmapLocalWorld;           // 0x002dc680
int32_t  DrawSky = 1;                       // 0x00322c28

// A scenery object's rotation is in units of 2^-14 (0x38800000).
#define ROTATION_UNIT (1.0f / 16384.0f)

int32_t SkyInitModel(eModel *model, bMatrix4 *matrix, uint32_t name_hash)
{
    SceneryInstance *inst = scenery_find_instance_by_hash(name_hash);
    SceneryInfo     *info;
    const int16_t   *r;
    int              i;

    if (inst == NULL) {
        emodel_uninit(model);
        eIdentity(matrix);
        return 0;
    }
    emodel_init(model, name_hash);
    r = inst->Rotation;
    matrix->v0.x = (float)r[0] * ROTATION_UNIT;
    matrix->v0.y = (float)r[1] * ROTATION_UNIT;
    matrix->v0.z = (float)r[2] * ROTATION_UNIT;
    matrix->v0.w = 0.0f;
    matrix->v1.x = (float)r[3] * ROTATION_UNIT;
    matrix->v1.y = (float)r[4] * ROTATION_UNIT;
    matrix->v1.z = (float)r[5] * ROTATION_UNIT;
    matrix->v1.w = 0.0f;
    matrix->v2.x = (float)r[6] * ROTATION_UNIT;
    matrix->v2.y = (float)r[7] * ROTATION_UNIT;
    matrix->v2.z = (float)r[8] * ROTATION_UNIT;
    matrix->v2.w = 0.0f;
    matrix->v3.x = inst->Position[0];
    matrix->v3.y = inst->Position[1];
    matrix->v3.z = inst->Position[2];
    matrix->v3.w = 1.0f;

    // The image does not check the kind: an object of the name means a
    // kind whose first LOD has it.
    info = scenery_find_info(name_hash);
    for (i = 0; i < 3; i++) {
        if (info->pModel[i] != NULL) {
            emodel_uninit(info->pModel[i]);
        }
    }
    return 1;
}

void SkyLoader(void)
{
    SkyInitModel(&SkydomeModel, &SkydomeLocalWorld, SKY_HASH_SKYDOME);
    if (!SkyInitModel(&SkydomeEnvmapModel, &SkydomeEnvmapLocalWorld,
                      SKY_HASH_SKYDOME_ENVMAP)) {
        emodel_init(&SkydomeEnvmapModel, SKY_HASH_SKYDOME);
        SkydomeEnvmapLocalWorld = SkydomeLocalWorld;
    }
}

void SkyUnloader(void)
{
    emodel_uninit(&SkydomeModel);
    eIdentity(&SkydomeLocalWorld);
    emodel_uninit(&SkydomeEnvmapModel);
    eIdentity(&SkydomeEnvmapLocalWorld);
}

void StuffSky(eView *view)
{
    if (!DrawSky || gEModelRenderFn == NULL) {
        return;
    }
    if ((uint32_t)(view->ID - 1) < 3u) {
        gEModelRenderFn(&SkydomeModel, &SkydomeLocalWorld, NULL, 0);
    } else {
        gEModelRenderFn(&SkydomeEnvmapModel, &SkydomeEnvmapLocalWorld, NULL,
                        0);
    }
}

void sky_static_init(void)
{
    SkydomeModel.Solid          = NULL;
    SkydomeModel.NameHash       = 0;
    SkydomeEnvmapModel.Solid    = NULL;
    SkydomeEnvmapModel.NameHash = 0;
}

void sky_static_close(void)
{
    emodel_delete(&SkydomeEnvmapModel, 2);
    emodel_delete(&SkydomeModel, 2);
}
