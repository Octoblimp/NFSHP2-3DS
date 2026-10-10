#!/usr/bin/env python3
"""Cross-check 3DS Files/source/speechnoise.c against the retail image,
SLES_507.31.

**The model** is retail's own SpeechNoise.obj run in
retail_model.RetailEmu: getInstance (0x001b0188, the copy that is
called), the constructor, LoadSamples, RequestSamples, UnLoadSamples,
Update, Mute, Start- and StopHelicopterNoise, Start- and StopRadioNoise,
IsRadioNoise, BeginSquelchNoise and IsSquelchNoisePlaying, all on the
one instance at 0x003341d0. Sound.obj's IsSoundRegionLoadingComplete
runs in the image too. The harness (tools/src/speechnoise_test.c) runs
speechnoise.c's.

**The fakes**, the same on both sides, each printing what it is handed:
bSound's Region (the region, or none when the script says), bRegion's
Sample (a sample a name, none for those the script names, none from no
region), bSample's SetCategory (kept), Play, Pause, Stop and IsPlaying
(playing from Play to Stop, or as the script says; retail asks it of a
missing squelch, and the model's is silent then, where the harness's
complains, since the port must ask it of none); the sound's random
int and float (the script's queues) and its loading flag (gp-19056,
which IsSoundRegionLoadingComplete negates); and atexit, silent.

**The script** builds the instance and asks again over a changed record;
runs the constructor over a filled one; updates while loading, with the
radio off, muted, and on with the draw at, under and over 3%; asks for
the samples while loading and once in, with the region missing and with
samples missing; draws each burst of static; mutes with 0, 1 and 5, with
and without the helicopter's sample; starts and stops the helicopter's
noise playing, stopped and missing; plays each squelch, present and
missing, and asks whether either plays in every case; and unloads with
the helicopter's sample playing, stopped and missing.

    python tools/speechnoise_check.py
    python tools/speechnoise_check.py --mutate [--only a,b]
    python tools/speechnoise_check.py --dump out/speechnoise
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/speechnoise_test.c"
SNC = "3DS Files/source/speechnoise.c"
SOURCES = [HARNESS, SNC]
HARNESS_TIMEOUT = 30
LIMIT = 200000

GP = retail_model.RETAIL_GP
F = {
    "inst": 0x001b0188, "ctor": 0x002155d8, "load": 0x00215610,
    "request": 0x00215770, "unload": 0x00215780, "update": 0x002157c0,
    "mute": 0x002158a0, "hstart": 0x00215930, "hstop": 0x00215958,
    "rstart": 0x002159a0, "rstop": 0x002159b0, "isradio": 0x002159b8,
    "squelch": 0x002159c0, "issquelch": 0x00215a08,
}

INST = 0x003341d0
BSOUND, LOADING = GP - 13696, GP - 19056
SIZE = 52
HELI, SQUELCH, RADIO = 0, 4, 12
ON, REQ, MUTED = 40, 44, 48
CATEGORY = 132
SAMPLE_SIZE = 188


def fbits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def fx(x):
    return "%08x" % fbits(x)


class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.srcs = {}                  # name -> sample, in creation order
        self.order = []
        self.nosrc = set()
        self.playing = set()
        self.rf, self.ri = [], []
        self.noregion = 0
        self.bsound = e.alloc(16)
        self.region = e.alloc(64)
        e.put32(BSOUND, self.bsound)
        e.put32(LOADING, 0)

        e.stub(0x00277a18, self.region_of)
        e.stub(0x002719b8, self.rsample)
        e.stub(0x00273618, self.b_cat)
        e.stub(0x00274080, self.b_play)
        e.stub(0x00274488, self.b_pause)
        e.stub(0x00274618, self.b_stop)
        e.stub(0x00274410, self.b_isplaying)
        e.stub(0x001af2e0, self.loading)
        e.stub(0x001af9a0, self.randi)
        e.stub(0x001af9c0, self.randf)
        e.stub(0x00296220, lambda em: 0)        # atexit

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, n=64):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def name(self, a):
        a &= M32
        if a == 0:
            return "0"
        if a == self.bsound:
            return "bsound"
        if a == self.region:
            return "region"
        for nm, p in self.srcs.items():
            if a == p:
                return "src:" + nm
        return "?"

    def src_named(self, nm):
        if nm in self.nosrc:
            return 0
        if nm not in self.srcs:
            s = self.e.alloc(SAMPLE_SIZE, 16)
            self.e.mem[s:s + SAMPLE_SIZE] = b"\0" * SAMPLE_SIZE
            self.srcs[nm] = s
            self.order.append(nm)
        return self.srcs[nm]

    # ---- bSound, bRegion

    def region_of(self, em):
        r = 0 if self.noregion else self.region
        self.emit("  region %s %s -> %s" % (
            self.name(em.reg[4]), self.cstr(em.reg[5] & M32), self.name(r)))
        return r

    def rsample(self, em):
        r = em.reg[4] & M32
        nm = self.cstr(em.reg[5] & M32)
        s = self.src_named(nm) if r else 0
        self.emit("  rsample %s %s -> %s" % (self.name(r), nm,
                                             self.name(s)))
        return s

    # ---- bSample

    def b_cat(self, em):
        s = em.reg[4] & M32
        self.emit("  bcat %s %d" % (self.name(s), em.reg[5] & M32))
        if s:
            self.e.put32(s + CATEGORY, em.reg[5] & M32)
        return 0

    def b_play(self, em):
        s = em.reg[4] & M32
        self.emit("  bplay %s %08x %08x %08x" % (
            self.name(s), em.fpr[12], em.fpr[13], em.fpr[14]))
        if s:
            self.playing.add(s)
        return 0

    def b_pause(self, em):
        self.emit("  bpause %s %d" % (self.name(em.reg[4]),
                                      1 if em.reg[5] & 0xff else 0))
        return 0

    def b_stop(self, em):
        s = em.reg[4] & M32
        self.emit("  bstop %s" % self.name(s))
        self.playing.discard(s)
        return 0

    def b_isplaying(self, em):
        s = em.reg[4] & M32
        if not s:
            return 0
        v = 1 if s in self.playing else 0
        self.emit("  bisplaying %s %d" % (self.name(s), v))
        return v

    # ---- the sound module

    def loading(self, em):
        v = s32(self.e.u32(LOADING))
        self.emit("  loading -> %d" % v)
        return v

    def randi(self, em):
        v = self.ri.pop(0) if self.ri else 0
        self.emit("  randi %d -> %d" % (s32(em.reg[4]), v))
        return v

    def randf(self, em):
        v = self.rf.pop(0) if self.rf else 0
        self.emit("  randf %08x -> %08x" % (em.fpr[12], v))
        em.fpr[0] = v
        return 0

    # ---- the dumps

    def dump(self):
        e = self.e
        radio = ",".join(self.name(e.u32(INST + RADIO + 4 * i))
                         for i in range(7))
        self.emit("  nd heli=%s sq=%s,%s radio=%s on=%d req=%d muted=%d" % (
            self.name(e.u32(INST + HELI)),
            self.name(e.u32(INST + SQUELCH)),
            self.name(e.u32(INST + SQUELCH + 4)), radio,
            s32(e.u32(INST + ON)), s32(e.u32(INST + REQ)),
            s32(e.u32(INST + MUTED))))

    def dump_cats(self):
        for nm in self.order:
            self.emit("  cat src:%s %d" % (
                nm, self.e.u32(self.srcs[nm] + CATEGORY)))

    # ---- the ops

    def call(self, name, *args):
        return self.e.call(F[name], *args, limit=LIMIT)

    def op(self, f):
        e = self.e

        def i(k):
            return int(f[k], 0) if k < len(f) else 0

        def fb(k):
            return int(f[k], 16) & M32 if k < len(f) else 0

        o = f[0]
        if o == "inst":
            v = self.call("inst") & M32
            self.emit("  -> %s" % ("inst" if v == INST else "?"))
        elif o == "fill":
            e.mem[INST:INST + SIZE] = b"\xa5" * SIZE
        elif o == "ctor":
            self.call("ctor", INST)
        elif o == "nd":
            self.dump()
        elif o == "cats":
            self.dump_cats()
        elif o in ("load", "request", "unload", "update", "hstart",
                   "hstop", "rstart", "rstop", "squelch"):
            self.call(o, INST)
        elif o == "mute":
            self.call("mute", INST, i(1))
        elif o in ("isradio", "issquelch"):
            self.emit("  = %d" % self.call(o, INST))
        elif o == "heli":
            e.put32(INST + HELI, 0 if f[1] == "0" else self.src_named(f[1]))
        elif o == "slot":
            s = 0 if f[2] == "0" else self.src_named(f[2])
            k = int(f[1][1:])
            e.put32(INST + (SQUELCH if f[1][0] == "s" else RADIO) + 4 * k, s)
        elif o == "poke":
            off = {"on": ON, "req": REQ}.get(f[1], MUTED)
            e.put32(INST + off, i(2) & M32)
        elif o == "noregion":
            self.noregion = i(1)
        elif o == "nosrc":
            self.nosrc.add(f[1])
        elif o == "unsrc":
            self.nosrc.clear()
        elif o == "loading":
            e.put32(LOADING, i(1) & M32)
        elif o == "rf":
            self.rf.append(fb(1))
        elif o == "ri":
            self.ri.append(i(1))
        elif o == "playing":
            s = self.src_named(f[1])
            if s:
                if i(2):
                    self.playing.add(s)
                else:
                    self.playing.discard(s)
        else:
            self.emit("  unknown op %s" % o)

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


def model(lines):
    m = Model()
    out = m.run(lines)
    return out, m.e


# ================================================================ script

SLOTS = ["s0", "s1"] + ["r%d" % k for k in range(7)]


def script():
    L = []
    a = L.append

    def rf(*v):
        for x in v:
            a("rf|%s" % (x if isinstance(x, str) else fx(x)))

    def ri(*v):
        for x in v:
            a("ri|%d" % x)

    # The instance, and the guard: a second call keeps what is there.
    a("inst")
    a("nd")
    a("poke|on|1")
    a("poke|req|1")
    a("inst")
    a("nd")

    # The constructor over a filled record: the static is left alone.
    a("fill")
    a("nd")
    a("ctor")
    a("nd")
    for s in SLOTS:
        a("slot|%s|0" % s)
    a("nd")

    # Update with nothing asked for: loading, the radio off, muted, then
    # on with the draw at, under and over 3% and the static missing.
    a("loading|1")
    a("update")
    a("loading|0")
    a("update")
    a("rstart")
    a("isradio")
    a("loading|1")
    a("update")
    a("loading|0")
    a("poke|muted|1")
    a("update")
    a("poke|muted|0")
    rf("3cf5c28f")
    a("update")
    rf("3cf5c290")
    a("update")
    rf("3cf5c28e", 0.25)
    ri(3)
    a("update")
    rf(0.0, 0.0)
    ri(0)
    a("update")

    # Ask for the samples: still loading, then in with no region.
    a("request")
    a("nd")
    a("loading|1")
    a("update")
    a("nd")
    a("loading|0")
    a("noregion|1")
    rf(0.5)
    a("update")
    a("nd")
    a("noregion|0")

    # Again with a squelch and a burst missing, the radio off and on.
    a("nosrc|RadioNoise03")
    a("nosrc|RadioNoiseSquelch02")
    a("request")
    a("rstop")
    a("update")
    a("nd")
    a("cats")
    a("rstart")
    a("request")
    rf(0.01, 0.125)
    ri(5)
    a("update")
    a("nd")

    # Each burst of static, the missing one skipped.
    for k in range(7):
        rf(0.02, 0.0625 * k)
        ri(k)
        a("update")
    rf(0.75)
    a("update")
    rf(0.029, 0.4)
    ri(6)
    a("update")

    # The rest of the samples in, then the categories.
    a("unsrc")
    a("request")
    a("poke|on|0")
    a("update")
    a("nd")
    a("cats")
    a("poke|on|1")

    # Mute with 0, 1 and 5, with and without the helicopter's sample, a
    # burst missing; updates while muted.
    a("mute|1")
    a("nd")
    a("update")
    a("mute|0")
    a("nd")
    rf(0.001, 0.3)
    ri(2)
    a("update")
    a("heli|Heli")
    a("slot|r4|0")
    a("mute|5")
    a("nd")
    a("update")
    a("mute|0")
    a("nd")
    a("slot|r4|RadioNoise05")

    # The helicopter's noise: missing, then playing and stopped.
    a("heli|0")
    a("hstart")
    a("hstop")
    a("heli|Heli")
    a("hstop")
    a("hstart")
    a("hstop")
    a("hstop")
    a("playing|Heli|1")
    a("hstop")

    # The squelches: each played, then asked of in every case.
    ri(0)
    a("squelch")
    a("issquelch")
    ri(1)
    a("squelch")
    a("issquelch")
    a("playing|RadioNoiseSquelch01|0")
    a("issquelch")
    a("playing|RadioNoiseSquelch02|0")
    a("issquelch")
    a("slot|s0|0")
    a("issquelch")
    a("playing|RadioNoiseSquelch02|1")
    a("issquelch")
    a("slot|s1|0")
    a("issquelch")
    ri(1)
    a("squelch")
    a("slot|s0|RadioNoiseSquelch01")
    a("slot|s1|RadioNoiseSquelch02")
    a("playing|RadioNoiseSquelch02|0")
    a("issquelch")

    # Unload with the helicopter's sample playing, stopped and missing.
    a("playing|Heli|1")
    a("unload")
    a("nd")
    a("isradio")
    a("rstart")
    a("heli|Heli")
    a("unload")
    a("nd")
    a("rstart")
    a("unload")
    a("nd")
    a("isradio")
    a("rstop")
    a("isradio")
    a("poke|on|7")
    a("isradio")
    return L


# ================================================================= build

def build_harness(tmp, name="speechnoise_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)],
                               stdout=fh, stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return pcc.HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


diff = pcc.diff


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return sc


# ============================================================= mutations

MUTATIONS_HEADER = "# " + "=" * 61 + " mutations" + NL


def model_cached(lines):
    """model(lines)'s transcript, or its last one when nothing it reads
    has changed. Nothing past the mutations' header is the model's."""
    return mutpar.model_cached(lines, lambda sc: model(sc)[0],
                               cut=MUTATIONS_HEADER)


def _m(name, before, after, rel=SNC):
    return (name, rel, before, after)


MUTATIONS = [
    # getInstance and the constructor.
    _m("inst-guard", "    if (!gSpeechNoiseBuilt) {", "    if (1) {"),
    _m("inst-set", "        gSpeechNoiseBuilt = 1;\n", ""),
    _m("ctor-on", "    n->RadioNoiseOn = 0;\n    n->RequestSampleLoad = 0;",
       "    n->RequestSampleLoad = 0;"),
    _m("ctor-req", "    n->RequestSampleLoad = 0;\n    n->Helicopter = NULL;",
       "    n->Helicopter = NULL;"),
    _m("ctor-heli", "    n->Helicopter = NULL;\n    n->SpeechNoiseMuted = 0;",
       "    n->SpeechNoiseMuted = 0;"),
    _m("ctor-muted", "    n->SpeechNoiseMuted = 0;\n}\n\nvoid speechnoise_load",
       "}\n\nvoid speechnoise_load"),

    # LoadSamples.
    _m("load-region", 'bsound_region(bsound_get(), "InGame");',
       'bsound_region(bsound_get(), "Ingame");'),
    _m("load-sq-name", '"RadioNoiseSquelch01", "RadioNoiseSquelch02",',
       '"RadioNoiseSquelch01", "RadioNoiseSquelch01",'),
    _m("load-sq-name1", '"RadioNoiseSquelch01", "RadioNoiseSquelch02",',
       '"RadioNoiseSquelch02", "RadioNoiseSquelch02",'),
    _m("load-r-name1", '"RadioNoise01", "RadioNoise02",',
       '"RadioNoise02", "RadioNoise02",'),
    _m("load-r-name7", '"RadioNoise05", "RadioNoise06", "RadioNoise07",',
       '"RadioNoise05", "RadioNoise06", "RadioNoise06",'),
    _m("load-sq-count", "    for (i = 0; i < SPEECHNOISE_SQUELCHES; i++) {\n        n->Squelch",
       "    for (i = 0; i < 1; i++) {\n        n->Squelch"),
    _m("load-r-count", "    for (i = 0; i < SPEECHNOISE_RADIOS; i++) {\n        n->Radio[i] = bregion",
       "    for (i = 0; i < 6; i++) {\n        n->Radio[i] = bregion"),
    _m("load-sq-cat", "        bsample_set_category(n->Squelch[i], 6);",
       "        bsample_set_category(n->Squelch[i], 5);"),
    _m("load-r-cat", "        bsample_set_category(n->Radio[i], 6);",
       "        bsample_set_category(n->Radio[i], 7);"),
    _m("load-sq-catdrop", "        bsample_set_category(n->Squelch[i], 6);\n", ""),
    _m("load-order",
       "    for (i = 0; i < SPEECHNOISE_SQUELCHES; i++) {\n"
       "        n->Squelch[i] = bregion_sample(r, SquelchNames[i]);\n"
       "        bsample_set_category(n->Squelch[i], 6);\n"
       "    }\n"
       "    for (i = 0; i < SPEECHNOISE_RADIOS; i++) {\n"
       "        n->Radio[i] = bregion_sample(r, RadioNames[i]);\n"
       "        bsample_set_category(n->Radio[i], 6);\n"
       "    }\n",
       "    for (i = 0; i < SPEECHNOISE_RADIOS; i++) {\n"
       "        n->Radio[i] = bregion_sample(r, RadioNames[i]);\n"
       "        bsample_set_category(n->Radio[i], 6);\n"
       "    }\n"
       "    for (i = 0; i < SPEECHNOISE_SQUELCHES; i++) {\n"
       "        n->Squelch[i] = bregion_sample(r, SquelchNames[i]);\n"
       "        bsample_set_category(n->Squelch[i], 6);\n"
       "    }\n"),
    _m("load-req", "    n->RequestSampleLoad = 0;\n}\n\nvoid speechnoise_request",
       "}\n\nvoid speechnoise_request"),

    # RequestSamples, UnLoadSamples.
    _m("request", "    n->RequestSampleLoad = 1;", "    n->RequestSampleLoad = 0;"),
    _m("unload-heli-test", "    if (n->Helicopter != NULL)\n        speechnoise_stop_helicopter_noise(n);",
       "    if (n->Helicopter == NULL)\n        speechnoise_stop_helicopter_noise(n);"),
    _m("unload-heli-stop", "    if (n->Helicopter != NULL)\n        speechnoise_stop_helicopter_noise(n);\n",
       ""),
    _m("unload-radio", "    speechnoise_stop_radio_noise(n);\n    n->Helicopter = NULL;",
       "    n->Helicopter = NULL;"),
    _m("unload-null", "    speechnoise_stop_radio_noise(n);\n    n->Helicopter = NULL;",
       "    speechnoise_stop_radio_noise(n);"),

    # Update.
    _m("update-req", "    if (n->RequestSampleLoad && sound_is_region_loading_complete(m))",
       "    if (sound_is_region_loading_complete(m))"),
    _m("update-req-done", "    if (n->RequestSampleLoad && sound_is_region_loading_complete(m))",
       "    if (n->RequestSampleLoad)"),
    _m("update-loading", "    if (!sound_is_region_loading_complete(m) || n->SpeechNoiseMuted",
       "    if (n->SpeechNoiseMuted"),
    _m("update-muted", "    if (!sound_is_region_loading_complete(m) || n->SpeechNoiseMuted\n        || !n->RadioNoiseOn)",
       "    if (!sound_is_region_loading_complete(m)\n        || !n->RadioNoiseOn)"),
    _m("update-on", "        || !n->RadioNoiseOn)", "        || n->RadioNoiseOn)"),
    _m("update-draw-range", "    if (sound_random_float(m, 1.0f) < 0.03f) {",
       "    if (sound_random_float(m, 0.9f) < 0.03f) {"),
    _m("update-chance", "    if (sound_random_float(m, 1.0f) < 0.03f) {",
       "    if (sound_random_float(m, 1.0f) < 0.04f) {"),
    _m("update-chance-le", "    if (sound_random_float(m, 1.0f) < 0.03f) {",
       "    if (sound_random_float(m, 1.0f) <= 0.03f) {"),
    _m("update-vol-range", "sound_random_float(m, 0.4f) + 0.6f;",
       "sound_random_float(m, 0.5f) + 0.6f;"),
    _m("update-vol-base", "sound_random_float(m, 0.4f) + 0.6f;",
       "sound_random_float(m, 0.4f) + 0.5f;"),
    _m("update-count", "n->Radio[sound_random_int(m, SPEECHNOISE_RADIOS)];",
       "n->Radio[sound_random_int(m, 6)];"),
    _m("update-null", "        if (s != NULL)\n            bsample_play(s, vol, 0.0f, 1.0f);",
       "        bsample_play(s, vol, 0.0f, 1.0f);"),
    _m("update-pan", "bsample_play(s, vol, 0.0f, 1.0f);", "bsample_play(s, vol, 1.0f, 1.0f);"),
    _m("update-pitch", "bsample_play(s, vol, 0.0f, 1.0f);", "bsample_play(s, vol, 0.0f, 0.0f);"),
    _m("update-vol", "bsample_play(s, vol, 0.0f, 1.0f);", "bsample_play(s, 1.0f, 0.0f, 1.0f);"),
    _m("update-order",
       "        float vol = sound_random_float(m, 0.4f) + 0.6f;     // gp-27368, -27364\n"
       "        BSample *s = n->Radio[sound_random_int(m, SPEECHNOISE_RADIOS)];\n",
       "        BSample *s = n->Radio[sound_random_int(m, SPEECHNOISE_RADIOS)];\n"
       "        float vol = sound_random_float(m, 0.4f) + 0.6f;     // gp-27368, -27364\n"),

    # Mute.
    _m("mute-store", "    n->SpeechNoiseMuted = on;\n", ""),
    _m("mute-store-bool", "    n->SpeechNoiseMuted = on;", "    n->SpeechNoiseMuted = on != 0;"),
    _m("mute-count", "    for (i = 0; i < SPEECHNOISE_RADIOS; i++)\n        if (n->Radio[i] != NULL)",
       "    for (i = 0; i < 6; i++)\n        if (n->Radio[i] != NULL)"),
    _m("mute-null", "        if (n->Radio[i] != NULL)\n            bsample_pause(n->Radio[i], on != 0);",
       "        bsample_pause(n->Radio[i], on != 0);"),
    _m("mute-arg", "            bsample_pause(n->Radio[i], on != 0);",
       "            bsample_pause(n->Radio[i], on == 0);"),
    _m("mute-heli", "    if (n->Helicopter != NULL)\n        bsample_pause(n->Helicopter, on != 0);",
       "    if (n->Helicopter == NULL)\n        bsample_pause(n->Helicopter, on != 0);"),
    _m("mute-heli-drop", "    if (n->Helicopter != NULL)\n        bsample_pause(n->Helicopter, on != 0);\n",
       ""),
    _m("mute-squelch", "        if (n->Radio[i] != NULL)\n            bsample_pause(n->Radio[i], on != 0);",
       "        if (n->Radio[i] != NULL)\n            bsample_pause(n->Radio[i], on != 0);\n"
       "    bsample_pause(n->Squelch[0], on != 0);"),
    _m("mute-order",
       "    for (i = 0; i < SPEECHNOISE_RADIOS; i++)\n        if (n->Radio[i] != NULL)",
       "    for (i = SPEECHNOISE_RADIOS - 1; i >= 0; i--)\n        if (n->Radio[i] != NULL)"),

    # The helicopter.
    _m("hstart-null", "    if (n->Helicopter != NULL)\n        bsample_play(n->Helicopter, 1.0f, 0.0f, 0.0f);",
       "    bsample_play(n->Helicopter, 1.0f, 0.0f, 0.0f);"),
    _m("hstart-vol", "bsample_play(n->Helicopter, 1.0f, 0.0f, 0.0f);",
       "bsample_play(n->Helicopter, 0.5f, 0.0f, 0.0f);"),
    _m("hstart-pitch", "bsample_play(n->Helicopter, 1.0f, 0.0f, 0.0f);",
       "bsample_play(n->Helicopter, 1.0f, 0.0f, 1.0f);"),
    _m("hstop-null", "    if (n->Helicopter != NULL && bsample_is_playing(n->Helicopter))",
       "    if (bsample_is_playing(n->Helicopter))"),
    _m("hstop-playing", "    if (n->Helicopter != NULL && bsample_is_playing(n->Helicopter))",
       "    if (n->Helicopter != NULL)"),
    _m("hstop-stop", "        bsample_stop(n->Helicopter);", "        ;"),

    # The radio.
    _m("rstart", "    n->RadioNoiseOn = 1;", "    n->RadioNoiseOn = 2;"),
    _m("rstop", "void speechnoise_stop_radio_noise(SpeechNoise *n)\n{\n    n->RadioNoiseOn = 0;",
       "void speechnoise_stop_radio_noise(SpeechNoise *n)\n{\n    (void)n;"),
    _m("isradio", "    return n->RadioNoiseOn;", "    return n->RadioNoiseOn != 0;"),

    # The squelches.
    _m("squelch-count", "                                             SPEECHNOISE_SQUELCHES)],",
       "                                             1)],"),
    _m("squelch-vol", "                 1.0f, 0.0f, 0.0f);\n}", "                 0.5f, 0.0f, 0.0f);\n}"),
    _m("squelch-pitch", "                 1.0f, 0.0f, 0.0f);\n}", "                 1.0f, 0.0f, 1.0f);\n}"),
    _m("issq-first", "    if (n->Squelch[0] != NULL && bsample_is_playing(n->Squelch[0]))",
       "    if (n->Squelch[1] != NULL && bsample_is_playing(n->Squelch[1]))"),
    _m("issq-second", "    else if (n->Squelch[1] != NULL && bsample_is_playing(n->Squelch[1]))",
       "    else if (n->Squelch[0] != NULL && bsample_is_playing(n->Squelch[0]))"),
    _m("issq-or", "        playing = 1;\n    else if", "        playing = 1;\n    if"),
    _m("issq-second-val", "    else if (n->Squelch[1] != NULL && bsample_is_playing(n->Squelch[1]))\n        playing = 1;",
       "    else if (n->Squelch[1] != NULL && bsample_is_playing(n->Squelch[1]))\n        playing = 2;"),
    _m("issq-init", "    int32_t playing = 0;", "    int32_t playing = 1;"),
    _m("issq-null0", "    if (n->Squelch[0] != NULL && bsample_is_playing(n->Squelch[0]))",
       "    if (bsample_is_playing(n->Squelch[0]))"),
    _m("issq-null1", "    else if (n->Squelch[1] != NULL && bsample_is_playing(n->Squelch[1]))",
       "    else if (bsample_is_playing(n->Squelch[1]))"),
]

EQUIVALENT = {
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines = script()
    scp = write_script(indir.name, lines)
    base = model_cached(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)
    limit = mutpar.timeout_for(took)
    result = mutpar.run_pass(
        todo, SOURCES, "speechnoise_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    indir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, result)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))

    lines = script()
    got, e = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if n or rc else 0)


if __name__ == "__main__":
    main()
