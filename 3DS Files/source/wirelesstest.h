// wirelesstest -- TASKS 37a's soak of the link between two consoles.
//
// The config's "WirelessTest 1" hosts and "WirelessTest 2" joins the first
// host it finds; either runs in place of the game, before citro3d is up,
// with the top screen a text console. Once connected, each side sends, at
// the race's 30 a second, numbered reliable messages and a per-frame
// unreliable one whose bytes say what they are (as tools/src/wlproto_test.c
// does), and checks what comes from the other. After WirelessTestSeconds
// each sends how many reliable messages it sent; the test passes when
// each has every one of the other's, intact and in order, and no message
// came that was not sent. The screen and the log show the counts each
// second and the result at the end. START leaves at any time.

#ifndef WIRELESSTEST_H
#define WIRELESSTEST_H

#include "wireless.h"

// 0 when it passed, 1 when not, 2 when it never connected.
int wirelesstest_run(int mode, int seconds, WirelessLogFn log);

#endif
