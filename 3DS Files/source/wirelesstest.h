// wirelesstest -- TASKS 37a's soak of the link between two consoles.
//
// The config's "WirelessTest 1" hosts a network for WirelessTestConsoles
// consoles (2 to 8) and "WirelessTest 2" joins the first host it finds;
// either runs in place of the game, before citro3d is up, with the top
// screen a text console. The host closes its network once all have come.
// Over each link (the host has one for each client), each side sends, at
// the race's 30 a second, numbered reliable messages and a per-frame
// unreliable one whose bytes say what they are (as tools/src/wlproto_test.c
// does), and checks what comes from the other. After WirelessTestSeconds
// each sends how many reliable messages it sent; a link passes when each
// side has every one of the other's, intact and in order, and no message
// came that was not sent, and the test passes when every link has. The
// screen and the log show the counts each second and the result at the
// end. START leaves at any time.

#ifndef WIRELESSTEST_H
#define WIRELESSTEST_H

#include "wireless.h"

// 0 when it passed, 1 when not, 2 when it never connected.
int wirelesstest_run(int mode, int seconds, int consoles,
                      WirelessLogFn log);

#endif
