#!/bin/sh
# Inicia o controle do EV3. O main.py ja espera o controle conectar sozinho.
# -u = saida sem buffer, para os prints aparecerem no journalctl na hora.
exec /usr/bin/python3 -u /home/robot/main.py
