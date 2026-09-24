// drivetargetrenderer -- see drivetargetrenderer.h.
#include "drivetargetrenderer.h"

#include <stdio.h>
#include <stdlib.h>

DriveTargetRenderer TheDriveTargetRenderer; // 0x0030c640
int32_t             RenderDriveTargetPoints; // 0x003242c8

static void not_ported(const char *what)
{
    fprintf(stderr, "drivetargetrenderer: %s is not ported\n", what);
    abort();
}

// 0x001c1458.
void drivetargetrenderer_destroy_target_markers(DriveTargetRenderer *r)
{
    int i;

    if (!r->HasTargetMarkers)
        return;
    for (i = 0; i < DRIVETARGETRENDERER_MARKERS; i++) {
        // `j _$_11WorldObject` with flags 3 on each one that is there.
        if (r->DriveTargetMarker[i] != NULL)
            not_ported("~WorldObject");
        r->DriveTargetMarker[i] = NULL;
    }
    r->HasTargetMarkers = 0;
}

// 0x001c14c0.
void drivetargetrenderer_set_target_to_render(DriveTargetRenderer *r,
                                              DriveTarget *t)
{
    (void)t;
    if (!RenderDriveTargetPoints) {
        if (r->HasTargetMarkers)
            drivetargetrenderer_destroy_target_markers(r);
        return;
    }
    // CreateTargetMarkers and a WorldObject moved to each point.
    not_ported("SetTargetToRender with RenderDriveTargetPoints on");
}
