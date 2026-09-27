// rain -- Rain.obj's entry points, which the image compiles to `jr ra ;
// nop`. See rain.h for what the rest of Rain.obj and the storm are.

#include "rain.h"

// 0x00128bf8
void rain_Load(void)
{
}

// 0x00128c00
void rain_Unload(void)
{
}

// 0x00128c08
void rain_TimeStep(float dt)
{
    (void)dt;
}

// 0x00128c10
void rain_Render(struct eView *view)
{
    (void)view;
}
