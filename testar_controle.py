#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mostra os eventos do controle com nome, para conferir/mapear botoes e eixos.

Pare o servico antes (senao os motores andam junto):
    sudo systemctl stop ev3main.service
    python3 testar_controle.py          # escolhe o controle sozinho
    python3 testar_controle.py 3        # usa /dev/input/event3
Ctrl+C para sair.
"""
import sys

import evdev
from evdev import ecodes


def path_of(d):
    return getattr(d, "path", None) or getattr(d, "fn", "?")


def nome(etype, code):
    try:
        n = ecodes.bytype[etype][code]
        if isinstance(n, (list, tuple)):
            n = "/".join(n)
        return n
    except Exception:
        return "?"


devs = [evdev.InputDevice(fn) for fn in evdev.list_devices()]
print("Dispositivos:")
for d in devs:
    print("  {}  {}".format(path_of(d), d.name))

if len(sys.argv) > 1:
    dev = evdev.InputDevice("/dev/input/event" + sys.argv[1])
else:
    candidatos = [d for d in devs
                  if ecodes.EV_ABS in d.capabilities()
                  and ecodes.EV_KEY in d.capabilities()
                  and "motion" not in d.name.lower()
                  and "touchpad" not in d.name.lower()]
    if not candidatos:
        print("Nenhum controle encontrado. No PS3, aperte o botao PS.")
        sys.exit(1)
    dev = candidatos[0]

print("\nLendo: {} ({})".format(dev.name, path_of(dev)))
for code, info in dev.capabilities(absinfo=True).get(ecodes.EV_ABS, []):
    print("  eixo {:>3} {:<10} faixa {}..{}".format(code, nome(ecodes.EV_ABS, code), info.min, info.max))
print("Mexa nos analogicos e aperte os botoes...\n")

try:
    for e in dev.read_loop():
        if e.type == ecodes.EV_KEY:
            estado = {0: "solto", 1: "apertado", 2: "segurando"}.get(e.value, e.value)
            print("BOTAO code={:<4} {:<22} {}".format(e.code, nome(e.type, e.code), estado))
        elif e.type == ecodes.EV_ABS:
            print("EIXO  code={:<4} {:<22} {}".format(e.code, nome(e.type, e.code), e.value))
except KeyboardInterrupt:
    pass
