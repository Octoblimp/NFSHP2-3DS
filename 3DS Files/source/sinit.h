// sinit -- the image's static constructors, as the port runs them.
//
// The PS2 build's main() calls __main first thing (main+0x14), and __main
// hands bCallFunctions the range __CTOR_LIST__+4 .. +4+4n, where the word at
// __CTOR_LIST__ (0x00314f78) is n, 109. bCallFunctions walks it forwards.
// So every _GLOBAL_$I$ in the image has run, in list order, before main()
// does anything of its own.
//
// The port has no .ctors for these: each ported initialiser is a plain
// function. sinit_run() is that walk, with only the entries that have been
// ported, in the list's order. tools/sinit_check.py holds each call to its
// list index and requires every *_static_init in the source to be here.

#ifndef SINIT_H
#define SINIT_H

void sinit_run(void);

#endif
