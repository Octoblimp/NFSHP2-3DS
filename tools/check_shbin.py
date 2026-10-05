#!/usr/bin/env python3
"""Refuses a vertex shader that would freeze the PICA200.

3dbrew's GPU/Pitfalls lists two shader faults that stop a real 3DS's GPU
and that Azahar draws through:

  - a component of an enabled output register written twice, or never.
    GPUREG_SH_OUTMAP_MASK enables an output register whole, so all four
    of its components count, even ones no semantic reads: picasso's
    `.out outtex texcoord0` with only outtex.xy written leaves z and w
    unwritten. The race hung on a New 3DS XL at the first draw through
    geosolid.v.pica that way (2026-10-05);
  - two MOVA instructions in a row.

This runs each DVLE's code from its main both ways through every IFU and
IFC, and counts each output register's component writes on each path to
END. CALL, LOOP, JMP and BREAK are not followed; a shader with one is
refused until this learns them.

Usage: check_shbin.py a.shbin [b.shbin ...]      (exit 1 on a fault)
"""

import struct
import sys

# Opcodes, from 3dbrew's GPU/Shader Instruction Set.
MOVA, END, IFU, IFC = 0x12, 0x22, 0x27, 0x28
UNFOLLOWED = {0x20: "BREAK", 0x23: "BREAKC", 0x24: "CALL", 0x25: "CALLC",
              0x26: "CALLU", 0x29: "LOOP", 0x2c: "JMPC", 0x2d: "JMPU"}


def written(ins, ops):
    """The output register and components an instruction writes, or None."""
    op = ins >> 26
    if op >= 0x30:                              # MADI, MAD
        reg, desc = (ins >> 24) & 0x1f, ins & 0x1f
    elif op <= 0x0f or op == 0x13 or 0x18 <= op <= 0x1b:
        reg, desc = (ins >> 21) & 0x1f, ins & 0x7f
    else:
        return None
    if reg >= 0x10:
        return None
    mask = ops[desc] & 0xf                      # bit 3 is x, bit 0 is w
    return reg, [i for i in range(4) if mask >> (3 - i) & 1]


def paths(code, ops, main, faults):
    """Each path's (counts, branches taken) at its END."""
    done = []
    # pc, the IF blocks being run as (where one ends, where it goes on),
    # the writes so far, and the branches taken.
    todo = [(main, (), {}, ())]
    while todo:
        pc, stack, counts, taken = todo.pop()
        while True:
            if stack and pc == stack[-1][0]:
                pc, stack = stack[-1][1], stack[:-1]
                continue
            if pc >= len(code):
                faults.append("runs past the code without END")
                break
            ins = code[pc]
            op = ins >> 26
            if op == END:
                done.append((counts, taken))
                break
            if op in UNFOLLOWED:
                faults.append("pc %d: %s is not followed" % (pc, UNFOLLOWED[op]))
                break
            if op == MOVA and pc + 1 < len(code) and code[pc + 1] >> 26 == MOVA:
                faults.append("pc %d: two MOVAs in a row" % pc)
            if op in (IFU, IFC):
                num, dst = ins & 0xff, (ins >> 10) & 0xfff
                # Else: from dst for num, then on, which is where it ends.
                todo.append((dst, stack, dict(counts),
                             taken + ("else@%d" % pc,)))
                # If: up to dst, then on past the else.
                stack = stack + ((dst, dst + num),)
                taken = taken + ("if@%d" % pc,)
                pc += 1
                continue
            w = written(ins, ops)
            if w is not None:
                counts = dict(counts)
                for i in w[1]:
                    counts[(w[0], i)] = counts.get((w[0], i), 0) + 1
            pc += 1
    return done


def check_file(path):
    d = open(path, "rb").read()
    if d[:4] != b"DVLB":
        return ["not a DVLB"]
    n, = struct.unpack_from("<I", d, 4)
    offs = struct.unpack_from("<%dI" % n, d, 8)
    dvlp = 8 + 4 * n
    w = struct.unpack_from("<7I", d, dvlp)
    code = struct.unpack_from("<%dI" % w[3], d, dvlp + w[2])
    ops = struct.unpack_from("<%dQ" % w[5], d, dvlp + w[4])
    faults = []
    for k, o in enumerate(offs):
        e = struct.unpack_from("<16I", d, o)
        enabled = sorted({struct.unpack_from("<HH", d, o + e[10] + 8 * j)[1]
                          for j in range(e[11])})
        mine = []
        for counts, taken in paths(code, ops, e[2], mine):
            via = " via " + ", ".join(taken) if taken else ""
            for reg in enabled:
                for i, c in enumerate("xyzw"):
                    if counts.get((reg, i), 0) != 1:
                        mine.append("o%d.%s written %d times%s"
                                    % (reg, c, counts.get((reg, i), 0), via))
            for reg in sorted({r for r, _ in counts} - set(enabled)):
                mine.append("o%d written but not an output%s" % (reg, via))
        faults += ["DVLE %d: %s" % (k, f) for f in dict.fromkeys(mine)]
    return faults


def main():
    bad = 0
    for path in sys.argv[1:]:
        for f in check_file(path):
            print("check_shbin: %s: %s" % (path, f))
            bad += 1
    if bad:
        return 1
    print("check_shbin: %d shaders, each output component written once"
          % (len(sys.argv) - 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
