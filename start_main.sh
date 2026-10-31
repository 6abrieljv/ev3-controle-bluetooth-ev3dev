#!/bin/sh
# 1) Mostra na hora a tela "Carregando" (copia do LCD salva pelo main.py)
#    e tira o console de texto da tela. Python sem 'site' (-S) abre rapido.
/usr/bin/python3 -S -c '
import os, fcntl
try:
    fd = os.open("/dev/tty0", os.O_RDWR)
    fcntl.ioctl(fd, 0x4B3A, 1)   # KDSETMODE = KD_GRAPHICS
    os.close(fd)
except Exception:
    pass
try:
    with open("/home/robot/.ev3_splash", "rb") as s:
        dados = s.read()
    with open("/dev/fb0", "wb") as fb:
        fb.write(dados)
except Exception:
    pass
'
# 2) Abre o menu (demora uns segundos no EV3; a tela acima fica enquanto isso)
# -u = saida sem buffer, para os prints aparecerem no journalctl na hora.
exec /usr/bin/python3 -u /home/robot/main.py
