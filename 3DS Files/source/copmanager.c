// copmanager -- see copmanager.h.

#include "copmanager.h"

tCopManager *pCopManager;       // 0x00331bec

tCop *(*gCopManagerGetCopByCarFn)(tCopManager *m, struct Car *c);
tCop *(*gCopManagerGetCopByChaseFn)(tCopManager *m, struct Car *c);
