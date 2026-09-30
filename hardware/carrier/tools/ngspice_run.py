#!/usr/bin/env python3
"""Run one SPICE deck through KiCad's bundled libngspice, dump every plot to JSON.

    flatpak run --command=python3 org.kicad.KiCad tools/ngspice_run.py DECK.cir OUT.json

The deck's own .control block (if any) runs as written; without one, the
deck's analysis lines run once. Output JSON: {"log": [...], "plots": {name:
{vec: [values] or {"re": [...], "im": [...]}}}}. Called by tools/sim.py.
"""
import ctypes as C
import json
import sys

LIB = "/app/lib/libngspice.so.0"


class VecInfo(C.Structure):
    _fields_ = [("name", C.c_char_p), ("type", C.c_int), ("flags", C.c_short),
                ("real", C.POINTER(C.c_double)), ("comp", C.POINTER(C.c_double)),
                ("length", C.c_int)]


def main(deck, out):
    ng = C.CDLL(LIB)
    log = []
    PRINT = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
    STAT = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
    EXIT = C.CFUNCTYPE(C.c_int, C.c_int, C.c_bool, C.c_bool, C.c_int, C.c_void_p)
    BG = C.CFUNCTYPE(C.c_int, C.c_bool, C.c_int, C.c_void_p)

    def on_print(s, _i, _u):
        t = s.decode(errors="replace")
        for pre in ("stdout ", "stderr "):
            if t.startswith(pre):
                t = t[len(pre):]
        log.append(t)
        return 0

    cbs = [PRINT(on_print), STAT(lambda *a: 0), EXIT(lambda *a: 0), None, None, BG(lambda *a: 0)]
    ng.ngSpice_Init(cbs[0], cbs[1], cbs[2], None, None, cbs[5], None)
    ng.ngSpice_Command.argtypes = [C.c_char_p]
    ng.ngSpice_Command(f"source {deck}".encode())
    has_control = ".control" in open(deck).read().lower()
    if not has_control:
        ng.ngSpice_Command(b"run")

    ng.ngSpice_AllPlots.restype = C.POINTER(C.c_char_p)
    ng.ngSpice_AllVecs.restype = C.POINTER(C.c_char_p)
    ng.ngSpice_AllVecs.argtypes = [C.c_char_p]
    ng.ngGet_Vec_Info.restype = C.POINTER(VecInfo)
    ng.ngGet_Vec_Info.argtypes = [C.c_char_p]
    plots = {}
    pp = ng.ngSpice_AllPlots()
    names = []
    i = 0
    while pp[i]:
        names.append(pp[i].decode())
        i += 1
    for p in names:
        if p == "const":
            continue
        vecs = {}
        vp = ng.ngSpice_AllVecs(p.encode())
        j = 0
        while vp[j]:
            v = vp[j].decode()
            j += 1
            info = ng.ngGet_Vec_Info(f"{p}.{v}".encode())
            if not info:
                continue
            n = info.contents.length
            if info.contents.real:
                vecs[v] = [info.contents.real[k] for k in range(n)]
            elif info.contents.comp:
                c = info.contents.comp
                vecs[v] = {"re": [c[2 * k] for k in range(n)], "im": [c[2 * k + 1] for k in range(n)]}
        plots[p] = vecs
    json.dump({"log": log, "plots": plots}, open(out, "w"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
