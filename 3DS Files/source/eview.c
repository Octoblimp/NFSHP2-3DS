// eview -- the table of views and the three words beside it. See eview.h.
//
// The table is .bss on the disc, and eInit builds each view.

#include "eview.h"

eView eViews[EVIEW_NUM_VIEWS];

int32_t CurrentViewMode;
int32_t EnvironmentMappingEnable = 1;

static eView *pCurrentView;

eView *eGetView(int32_t id)
{
    return &eViews[id];
}

int32_t eGetCurrentViewMode(void)
{
    return CurrentViewMode;
}

eView *eGetCurrentView(void)
{
    return pCurrentView;
}

void eSetCurrentView(eView *v)
{
    pCurrentView = v;
}

Camera *eGetCurrentCamera(void)
{
    return pCurrentView != 0 ? pCurrentView->pCamera : 0;
}
