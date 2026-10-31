#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EV3 (ev3dev) + controle PS4 / PS3 / Xbox, com MENU na tela do EV3.

Liga o EV3 e o menu aparece sozinho. Use so os botoes do bloco:
  CIMA/BAIXO = escolhe   ENTER = abre   VOLTAR = volta/cancela

Opcoes:
  Dirigir      - usa o controle (analogico esquerdo)
  Parear controle - pareia controle Bluetooth (PS4 ou universal)
  Parear PS3   - pareia um controle de PS3 (cabo USB uma vez)
  Rede         - mostra o IP e conecta Wi-Fi salvo ou o Bluetooth do PC
  Info         - IP, bateria e controle conectado
  Brickman     - abre o menu normal do ev3dev
  Desligar     - desliga o EV3

Dirigindo: PS4 = X volta ao menu | outros = segure START 1 s | EV3 = VOLTAR.

Compativel com Python 3.5 (ev3dev stretch): NAO usar f-strings.
"""

import os
import queue
import re
import select
import signal
import subprocess
import sys
import threading
import time

import evdev
from evdev import ecodes
import ev3dev.auto as ev3

try:
    from ev3dev2.display import Display as _Display
except Exception:
    _Display = None
try:
    from PIL import ImageFont as _ImageFont
except Exception:
    _ImageFont = None

# =====================================================================
# Configuracao
# =====================================================================
DEBUG_EVENT = False      # imprime eventos brutos do controle
DEADZONE = 100           # zona morta do analogico (escala -1000..1000)
MAX_SPEED = 1000         # speed_sp maximo (LargeMotor aguenta ~1050)
INVERT_THROTTLE = False  # inverta se o robo andar para tras ao empurrar pra cima
INVERT_TURN = False      # inverta se virar para o lado errado
QUIT_HOLD_S = 1.0        # PS3: tempo segurando START para voltar ao menu

MOTOR_RIGHT = ev3.OUTPUT_C
MOTOR_LEFT = ev3.OUTPUT_B

# Codigos de botao (linux/input-event-codes.h)
BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST = 304, 305, 307, 308
BTN_SELECT, BTN_START, BTN_MODE = 314, 315, 316

# Botao que volta ao menu, por controle. hold=0 -> na hora; >0 -> segurar.
PROFILES = {
    # PS3 kernel novo: X=304 O=305 Tri=307 Quad=308 SELECT=314 START=315 PS=316
    "ps3": {"label": "PS3", "quit": [BTN_START], "hold": QUIT_HOLD_S,
            "dica": "Segure START"},
    # PS3 kernel antigo: X=302 O=301 Tri=300 Quad=303 SELECT=288 START=291
    "ps3_old": {"label": "PS3", "quit": [291], "hold": QUIT_HOLD_S,
                "dica": "Segure START"},
    # PS4 kernel novo: X=304 O=305 Tri=307 Quad=308 SHARE=314 OPTIONS=315
    "ps4": {"label": "PS4", "quit": [BTN_SOUTH], "hold": 0, "dica": "X = menu"},
    # PS4 kernel antigo: Quad=304 X=305 O=306 Tri=307 (o 305 do codigo original)
    "ps4_old": {"label": "PS4", "quit": [305], "hold": 0, "dica": "X = menu"},
    # Xbox / genericos
    "generic": {"label": "Controle", "quit": [BTN_START, BTN_SELECT],
                "hold": QUIT_HOLD_S, "dica": "Segure START"},
}


# =====================================================================
# Utilitarios
# =====================================================================
def clamp(n, minn, maxn):
    return max(min(maxn, n), minn)


def scale(val, src, dst):
    return (float(val - src[0]) / (src[1] - src[0])) * (dst[1] - dst[0]) + dst[0]


def scale_axis(value, rng):
    """Valor bruto do eixo -> -1000..1000, usando a faixa real do controle
    (PS3/PS4: 0..255, Xbox: -32768..32767)."""
    if rng is None:
        rng = (0, 255)
    if rng[1] == rng[0]:
        return 0
    v = clamp(scale(value, rng, (-1000, 1000)), -1000, 1000)
    if -DEADZONE < v < DEADZONE:
        return 0
    return int(v)


def dc_clamp(value):
    return int(clamp(value, -MAX_SPEED, MAX_SPEED))


def _dev_path(device):
    # python-evdev novo usa .path; o do stretch usa .fn
    return getattr(device, "path", None) or getattr(device, "fn", "?")


def _beep():
    try:
        ev3.Sound.beep()
    except Exception:
        pass


def _run(cmd, timeout=10):
    """Roda um comando e devolve a saida (texto). Nunca levanta erro."""
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout)
        return out.decode("utf-8", "replace")
    except Exception as e:
        return str(e)


# =====================================================================
# Tela (LCD 178x128)
# =====================================================================
def _load_font(size, bold=False):
    if _ImageFont is None:
        return None
    nomes = ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"] if bold else ["DejaVuSans.ttf"]
    for n in nomes:
        try:
            return _ImageFont.truetype("/usr/share/fonts/truetype/dejavu/" + n, size)
        except Exception:
            pass
    try:
        return _ImageFont.load_default()
    except Exception:
        return None


KDSETMODE, KD_TEXT, KD_GRAPHICS = 0x4B3A, 0, 1


def _console_grafico(ligar):
    """Tira o console de texto do Linux da tela (igual o brickman faz),
    senao ele escreve por cima do menu. Precisa de root."""
    try:
        import fcntl
        fd = os.open("/dev/tty0", os.O_RDWR)
        try:
            fcntl.ioctl(fd, KDSETMODE, KD_GRAPHICS if ligar else KD_TEXT)
        finally:
            os.close(fd)
    except Exception as e:
        print("Console: {}".format(e))


class Tela(object):
    def __init__(self):
        self.disp = None
        try:
            if _Display is not None:
                self.disp = _Display()
            elif hasattr(ev3, "Display"):
                self.disp = ev3.Display()
        except Exception as e:
            print("Sem display: {}".format(e))
            self.disp = None
        # ev3dev2 usa xres/yres; outras versoes usam width/height
        d = self.disp
        self.W = getattr(d, "xres", None) or getattr(d, "width", None) or 178
        self.H = getattr(d, "yres", None) or getattr(d, "height", None) or 128
        if d is not None:
            _console_grafico(True)
        self.font = _load_font(12)
        self.bold = _load_font(13, bold=True)
        self.lh = self._h(self.font) + 4
        self.th = self._h(self.bold) + 4

    def _h(self, font):
        try:
            return font.getsize("Ag")[1]
        except Exception:
            return 10

    def _w(self, text, font):
        try:
            return font.getsize(text)[0]
        except Exception:
            return len(text) * 6

    def _fit(self, text, font, maxw):
        if self._w(text, font) <= maxw:
            return text
        while text and self._w(text + "..", font) > maxw:
            text = text[:-1]
        return text + ".."

    def _text(self, draw, xy, text, font, fill):
        if font is not None:
            draw.text(xy, text, fill=fill, font=font)
        else:
            draw.text(xy, text, fill=fill)

    def _begin(self, titulo):
        d = self.disp
        draw = d.draw
        draw.rectangle((0, 0, self.W, self.H), fill="white")
        draw.rectangle((0, 0, self.W, self.th), fill="black")
        self._text(draw, (3, 1), self._fit(titulo, self.bold, self.W - 6), self.bold, "white")
        return draw

    def _rodape(self, draw, rodape):
        if not rodape:
            return
        y = self.H - self.lh + 1
        draw.line((0, y - 1, self.W, y - 1), fill="black")
        self._text(draw, (2, y), self._fit(rodape, self.font, self.W - 4), self.font, "black")

    def mostrar(self, titulo, linhas, rodape=None):
        if self.disp is None:
            print("[LCD] {} | {} | {}".format(titulo, " / ".join(linhas), rodape or ""))
            return
        try:
            draw = self._begin(titulo)
            y = self.th + 3
            for ln in linhas:
                self._text(draw, (3, y), self._fit(ln, self.font, self.W - 6), self.font, "black")
                y += self.lh
            self._rodape(draw, rodape)
            self.disp.update()
        except Exception as e:
            print("Erro desenhando: {}".format(e))

    def menu(self, titulo, itens, sel, rodape=None):
        if self.disp is None:
            print("[LCD] {} | {} | {}".format(titulo, " ".join(
                ("[" + t + "]") if i == sel else t for i, t in enumerate(itens)), rodape or ""))
            return
        try:
            d = self.disp
            draw = self._begin(titulo)
            area = self.H - self.th - 2 - (self.lh if rodape else 0)
            vis = max(1, area // self.lh)
            top = 0
            if sel >= vis:
                top = sel - vis + 1
            y = self.th + 2
            for i in range(top, min(len(itens), top + vis)):
                txt = self._fit(itens[i], self.font, self.W - 14)
                if i == sel:
                    draw.rectangle((0, y, self.W, y + self.lh), fill="black")
                    self._text(draw, (2, y + 1), ">", self.font, "white")
                    self._text(draw, (14, y + 1), txt, self.font, "white")
                else:
                    self._text(draw, (14, y + 1), txt, self.font, "black")
                y += self.lh
            self._rodape(draw, rodape)
            d.update()
        except Exception as e:
            print("Erro desenhando menu: {}".format(e))


# =====================================================================
# Botoes do EV3
# =====================================================================
BOTOES = ("up", "down", "left", "right", "enter", "backspace")


class Teclas(object):
    """Le os botoes do bloco e devolve so quando um botao e APERTADO."""

    def __init__(self):
        try:
            self.btn = ev3.Button()
        except Exception as e:
            print("Botoes do EV3 indisponiveis ({})".format(e))
            self.btn = None
        self.prev = set()

    def _pressed(self):
        btn = self.btn
        if btn is None:
            return set()
        try:
            if hasattr(btn, "process"):
                btn.process()
        except Exception:
            pass
        try:
            p = btn.buttons_pressed
            if callable(p):
                p = p()
            return set(p)
        except Exception:
            pass
        p = set()
        for name in BOTOES:
            try:
                if getattr(btn, name):
                    p.add(name)
            except Exception:
                pass
        return p

    def poll(self):
        cur = self._pressed()
        novo = cur - self.prev
        self.prev = cur
        for name in BOTOES:
            if name in novo:
                return name
        return None

    def wait(self, timeout=None):
        fim = None if timeout is None else time.time() + timeout
        while fim is None or time.time() < fim:
            k = self.poll()
            if k:
                return k
            time.sleep(0.03)
        return None


def lista(tela, teclas, titulo, itens, sel=0, rodape="CIMA/BAIXO  ENTER", status=None):
    """Menu generico. Devolve o indice escolhido ou None (VOLTAR).
    status(): funcao opcional que devolve o texto do rodape (atualiza sozinho)."""
    ultimo = 0
    while True:
        if status is not None and time.time() - ultimo > 1.5:
            rodape = status()
            ultimo = time.time()
        tela.menu(titulo, itens, sel, rodape)
        k = teclas.wait(1.5 if status is not None else None)
        if k in ("up", "left"):
            sel = (sel - 1) % len(itens)
        elif k in ("down", "right"):
            sel = (sel + 1) % len(itens)
        elif k == "enter":
            _beep()
            return sel
        elif k == "backspace":
            return None


def confirmar(tela, teclas, titulo, linhas):
    tela.mostrar(titulo, linhas, "ENTER sim  VOLTAR nao")
    while True:
        k = teclas.wait()
        if k == "enter":
            return True
        if k == "backspace":
            return False


def aviso(tela, teclas, titulo, linhas, tempo=None):
    """Mostra uma mensagem ate apertar qualquer botao (ou passar 'tempo')."""
    tela.mostrar(titulo, linhas, "Aperte um botao")
    teclas.wait(tempo)


# =====================================================================
# Deteccao do controle
# =====================================================================
CONTROLLER_KEYWORDS = [
    "playstation", "ps3", "sixaxis", "shanwan", "gasia",
    "xbox", "x-box", "microsoft", "wireless controller",
    "sony", "ps4", "ps5", "dualshock", "dualsense",
    "nintendo", "switch", "pro controller",
    "gamepad", "controller", "joystick", "8bitdo",
]
BAD_KEYWORDS = ["brick", "speaker", "motion sensors", "touchpad", "keyboard", "mouse"]


def _eh_ps4(nome):
    n = (nome or "").lower()
    return "wireless controller" in n or "ps4" in n or "dualshock 4" in n


def _eh_ps3(nome):
    n = (nome or "").lower()
    return ("playstation" in n and "3" in n) or "ps3" in n or "sixaxis" in n \
        or "shanwan" in n or "gasia" in n


def _score_device(device):
    try:
        name = (device.name or "").lower()
    except Exception:
        name = ""
    score = 0
    if any(k in name for k in CONTROLLER_KEYWORDS):
        score += 50
    if any(k in name for k in BAD_KEYWORDS):
        score -= 100
    try:
        caps = device.capabilities()
        if ecodes.EV_ABS in caps:
            score += 10
            if ecodes.ABS_X in caps[ecodes.EV_ABS] and ecodes.ABS_Y in caps[ecodes.EV_ABS]:
                score += 5
        if ecodes.EV_KEY in caps:
            score += 10
    except Exception:
        pass
    return score


def achar_controle():
    """Devolve (caminho, nome) do melhor controle conectado, ou (None, None)."""
    melhor, nome, pts = None, None, -999
    for fn in evdev.list_devices():
        try:
            d = evdev.InputDevice(fn)
        except Exception:
            continue
        try:
            s = _score_device(d)
            if s > pts:
                melhor, nome, pts = _dev_path(d), d.name, s
        finally:
            try:
                d.close()
            except Exception:
                pass
    if pts >= 50:
        return melhor, nome
    return None, None


def _detect_profile(device):
    name = device.name or ""
    try:
        keys = device.capabilities().get(ecodes.EV_KEY, [])
    except Exception:
        keys = []
    if _eh_ps3(name):
        if BTN_SOUTH not in keys and 302 in keys:
            return PROFILES["ps3_old"]
        return PROFILES["ps3"]
    if _eh_ps4(name):
        if 306 in keys:  # botao 306 so existe no mapeamento antigo
            return PROFILES["ps4_old"]
        return PROFILES["ps4"]
    return PROFILES["generic"]


def _axis_ranges(device):
    ranges = {}
    try:
        caps = device.capabilities(absinfo=True)
        for code, info in caps.get(ecodes.EV_ABS, []):
            ranges[code] = (info.min, info.max)
    except Exception:
        pass
    return ranges


def _rotulo(nome):
    if _eh_ps4(nome):
        return "PS4"
    if _eh_ps3(nome):
        return "PS3"
    return "Controle"


# =====================================================================
# Motores
# =====================================================================
throttle = 0   # -1000..1000 (frente/tras)
turn = 0       # -1000..1000 (direita positiva)
_motores = None


class Motores(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.right_motor = ev3.LargeMotor(MOTOR_RIGHT)
        self.left_motor = ev3.LargeMotor(MOTOR_LEFT)
        # ev3dev antigo nao da erro na criacao; checa se existe de verdade
        for m in (self.right_motor, self.left_motor):
            if hasattr(m, "connected") and not m.connected:
                raise IOError("motor nao conectado")
        self._last = None
        self._erro = False

    def parar(self):
        for m in (self.right_motor, self.left_motor):
            try:
                m.stop()
            except Exception:
                pass
        self._last = (0, 0)

    def run(self):
        print("Motores ativos!")
        while True:
            try:
                rs = dc_clamp(throttle - turn)
                ls = dc_clamp(throttle + turn)
                if (rs, ls) != self._last:   # so escreve quando muda
                    if rs == 0 and ls == 0:
                        self.parar()
                    else:
                        self.right_motor.run_forever(speed_sp=rs)
                        self.left_motor.run_forever(speed_sp=ls)
                    self._last = (rs, ls)
                self._erro = False
            except Exception as e:
                if not self._erro:
                    print("Erro nos motores: {}".format(e))
                self._erro = True
                self._last = None
                time.sleep(0.5)
            time.sleep(0.02)


def garantir_motores(tela, teclas):
    global _motores
    if _motores is not None:
        return True
    try:
        _motores = Motores()
        _motores.start()
        return True
    except Exception as e:
        print("Motores: {}".format(e))
        _motores = None
        aviso(tela, teclas, "Erro nos motores", [
            "Ligue os motores", "grandes nas portas", "B (esq) e C (dir)"])
        return False


def parar_tudo():
    global throttle, turn
    throttle = 0
    turn = 0
    if _motores is not None:
        _motores.parar()


# =====================================================================
# Dirigir
# =====================================================================
def dirigir(path, tela, teclas):
    """Le o controle. Devolve 'menu' (pediu para sair) ou 'desconectado'."""
    global throttle, turn
    try:
        dev = evdev.InputDevice(path)
    except Exception as e:
        print("Nao abriu {}: {}".format(path, e))
        return "desconectado"

    profile = _detect_profile(dev)
    ranges = _axis_ranges(dev)
    print("Usando {} [{}] perfil={} eixos={}".format(dev.name, path, profile["label"], ranges))
    tela.mostrar("{} conectado".format(profile["label"]), [
        "Analogico esquerdo:",
        "  frente / re / vira",
        "",
        profile["dica"],
    ], "VOLTAR (EV3) = menu")
    _beep()

    quit_at = None
    try:
        while True:
            if teclas.poll() == "backspace":
                return "menu"
            r, _, _ = select.select([dev.fd], [], [], 0.05)
            if not r:
                continue
            try:
                eventos = list(dev.read())
            except BlockingIOError:
                continue
            for event in eventos:
                if DEBUG_EVENT:
                    print(repr(event))
                if event.type == ecodes.EV_ABS:
                    if event.code == ecodes.ABS_X:
                        v = scale_axis(event.value, ranges.get(ecodes.ABS_X))
                        turn = -v if INVERT_TURN else v
                    elif event.code == ecodes.ABS_Y:
                        # eixo Y e invertido (cima = valor menor)
                        v = -scale_axis(event.value, ranges.get(ecodes.ABS_Y))
                        throttle = -v if INVERT_THROTTLE else v
                elif event.type == ecodes.EV_KEY and event.code in profile["quit"]:
                    if event.value == 1 and profile["hold"] <= 0:
                        return "menu"
                    if event.value == 1:
                        quit_at = time.time()
                    elif event.value == 0 and quit_at is not None:
                        if time.time() - quit_at >= profile["hold"]:
                            return "menu"
                        quit_at = None
    except (OSError, IOError) as e:
        print("Controle desconectado ({})".format(e))
        return "desconectado"
    finally:
        parar_tudo()   # seguranca: robo parado antes de qualquer coisa
        try:
            dev.close()
        except Exception:
            pass


def modo_dirigir(tela, teclas):
    if not garantir_motores(tela, teclas):
        return
    msg = "Sem controle"
    while True:
        path, nome = achar_controle()
        if path:
            if dirigir(path, tela, teclas) == "menu":
                _beep()
                return
            _beep()
            msg = "Desconectado!"
            continue
        tela.mostrar("Dirigir", [msg, "", "Aperte PS no", "controle"], "VOLTAR = menu")
        if teclas.wait(1.0) == "backspace":
            return


# =====================================================================
# Bluetooth (bluetoothctl)
# =====================================================================
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|[\x01\x02]")
PROMPT_RE = re.compile(r"^\[[^\]]*\]#\s*")
MAC = r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})"
DEV_RE = re.compile(r"Device " + MAC + r" (.+)$")


class Bt(object):
    """Conversa com o bluetoothctl e responde 'yes' sozinho nas autorizacoes."""

    def __init__(self):
        self.p = subprocess.Popen(["bluetoothctl"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.q = queue.Queue()
        t = threading.Thread(target=self._ler)
        t.daemon = True
        t.start()

    def _ler(self):
        fd = self.p.stdout.fileno()
        buf = ""
        while True:
            try:
                data = os.read(fd, 1024)
            except OSError:
                break
            if not data:
                break
            buf += data.decode("utf-8", "replace").replace("\r", "\n")
            while "\n" in buf:
                linha, buf = buf.split("\n", 1)
                self._put(linha)
            if "(yes/no)" in buf:      # pergunta sem quebra de linha
                self._put(buf)
                buf = ""
        self.q.put(None)

    def _put(self, linha):
        linha = ANSI_RE.sub("", linha).strip()
        while PROMPT_RE.match(linha):
            linha = PROMPT_RE.sub("", linha, count=1).strip()
        if not linha:
            return
        print("bt: " + linha)
        if "(yes/no)" in linha:
            self.cmd("yes")
        self.q.put(linha)

    def cmd(self, c):
        print("bt> " + c)
        try:
            self.p.stdin.write((c + "\n").encode("utf-8"))
            self.p.stdin.flush()
        except Exception:
            pass

    def ler(self, timeout):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return ""

    def esperar(self, teclas, timeout, achou):
        """Le linhas ate achou(linha) devolver algo. Pode devolver
        'cancelado' (VOLTAR), 'timeout' ou 'erro'."""
        fim = time.time() + timeout
        while time.time() < fim:
            if teclas.poll() == "backspace":
                return "cancelado"
            linha = self.ler(0.1)
            if linha is None:
                return "erro"
            if linha:
                r = achou(linha)
                if r is not None:
                    return r
        return "timeout"

    def dispositivos(self):
        """Lista (mac, nome) que o EV3 ja conhece."""
        while self.ler(0.05):   # limpa a fila
            pass
        self.cmd("devices")
        achados = []
        fim = time.time() + 1.5
        while time.time() < fim:
            linha = self.ler(0.1)
            if linha is None:
                break
            m = DEV_RE.search(linha or "")
            if m and not linha.startswith("["):
                achados.append((m.group(1).upper(), m.group(2)))
        return achados

    def fechar(self):
        self.cmd("scan off")
        self.cmd("quit")
        try:
            self.p.wait(timeout=3)
        except Exception:
            try:
                self.p.kill()
            except Exception:
                pass


def _bt_ligar():
    # no ev3dev quem liga/desliga o Bluetooth e o connman
    _run(["connmanctl", "enable", "bluetooth"])
    _run(["rfkill", "unblock", "bluetooth"])
    time.sleep(1)


def _bt_abrir(tela):
    tela.mostrar("Bluetooth", ["Ligando..."])
    _bt_ligar()
    try:
        bt = Bt()
    except Exception as e:
        print("bluetoothctl: {}".format(e))
        return None
    bt.cmd("power on")
    bt.cmd("agent NoInputNoOutput")
    bt.cmd("default-agent")
    time.sleep(0.5)
    return bt


def _falhou(tela, teclas, r, extra=None):
    if r == "cancelado":
        return
    linhas = {"timeout": ["Demorou demais.", "Tente de novo."],
              "erro": ["bluetoothctl", "parou de responder."]}.get(r, [str(r)])
    aviso(tela, teclas, "Nao pareou", linhas + (extra or []))


def _parece_controle(nome):
    n = (nome or "").lower()
    return any(k in n for k in CONTROLLER_KEYWORDS) or "game" in n or "pad" in n \
        or "joy" in n or n.startswith("bt") or "bluetooth" in n


def _sem_nome(mac, nome):
    # aparelho sem nome aparece com o proprio MAC (ex: 7C-11-22-33-44-01)
    return not nome or nome.replace("-", ":").upper() == mac


def _escolher_aparelho(tela, teclas, bt, timeout=90):
    """Busca aparelhos Bluetooth e deixa escolher na tela.
    Devolve (mac, nome), 'cancelado', 'timeout' ou 'erro'."""
    achados = {}          # mac -> nome
    ordem = []
    sel = 0
    sel_mac = None        # aparelho que o usuario escolheu com as setas
    mudou = True
    fim = time.time() + timeout
    while time.time() < fim:
        k = teclas.poll()
        if k == "backspace":
            return "cancelado"

        # controles primeiro, depois quem tem nome, por ultimo so-MAC
        lista_ = sorted(ordem, key=lambda m: (
            0 if _parece_controle(achados[m]) else (2 if _sem_nome(m, achados[m]) else 1),
            ordem.index(m)))
        if lista_:
            # mantem a selecao no mesmo aparelho mesmo se a lista reordenar;
            # sem o usuario mexer, fica no primeiro (o controle mais provavel)
            sel = lista_.index(sel_mac) if sel_mac in lista_ else 0
            if k in ("up", "left"):
                sel = (sel - 1) % len(lista_)
                sel_mac = lista_[sel]
                mudou = True
            elif k in ("down", "right"):
                sel = (sel + 1) % len(lista_)
                sel_mac = lista_[sel]
                mudou = True
            elif k == "enter":
                mac = lista_[sel]
                return mac, achados[mac]

        if mudou:
            if lista_:
                tela.menu("Escolha o controle",
                          [achados[m] if not _sem_nome(m, achados[m]) else m for m in lista_],
                          sel, "ENTER pareia  VOLTAR")
            else:
                tela.mostrar("Parear controle", [
                    "Ligue o controle em",
                    "modo pareamento",
                    "(PS4: SHARE + PS).",
                    "Procurando...",
                ], "VOLTAR cancela")
            mudou = False

        linha = bt.ler(0.05)
        if linha is None:
            return "erro"
        if not linha:
            continue
        m = DEV_RE.search(linha)
        if not m:
            continue
        mac = m.group(1).upper()
        resto = m.group(2)
        if linha.startswith("[DEL]"):
            if mac in achados:
                del achados[mac]
                ordem.remove(mac)
                if sel_mac == mac:
                    sel_mac = None
                mudou = True
            continue
        if linha.startswith("[NEW]"):
            nome = resto
        elif linha.startswith("[CHG]") and (resto.startswith("Name: ") or resto.startswith("Alias: ")):
            nome = resto.split(": ", 1)[1]
        else:
            continue
        if mac not in achados:
            ordem.append(mac)
            achados[mac] = nome
            mudou = True
        elif _sem_nome(mac, achados[mac]) and not _sem_nome(mac, nome):
            achados[mac] = nome
            mudou = True
    return "timeout"


def parear_controle(tela, teclas):
    """Pareia qualquer controle Bluetooth (PS4 original ou universal)."""
    bt = _bt_abrir(tela)
    if bt is None:
        aviso(tela, teclas, "Erro", ["Bluetooth indisponivel"])
        return
    try:
        # esquece controles antigos: se o controle pareou com outro aparelho,
        # a chave velha impede a conexao
        for mac, nome in bt.dispositivos():
            if _parece_controle(nome) and not _eh_ps3(nome):
                bt.cmd("remove " + mac)
                time.sleep(0.5)
        time.sleep(0.5)
        while bt.ler(0.05):   # descarta respostas do 'remove'
            pass

        bt.cmd("scan on")
        r = _escolher_aparelho(tela, teclas, bt)
        if not isinstance(r, tuple):
            _falhou(tela, teclas, r, ["Ligue o modo", "pareamento do controle."])
            return
        mac, nome = r

        tela.mostrar("Pareando", [nome if not _sem_nome(mac, nome) else "", mac,
                                  "Aguarde..."], "VOLTAR cancela")
        bt.cmd("scan off")
        time.sleep(1)
        bt.cmd("pair " + mac)

        def _fim_pair(linha):
            if "Pairing successful" in linha or "AlreadyExists" in linha:
                return "ok"
            if "Failed to pair" in linha:
                return "Falha no pareamento"
            return None

        r = bt.esperar(teclas, 30, _fim_pair)
        if r != "ok":
            _falhou(tela, teclas, r, ["Ponha o controle em", "pareamento de novo."])
            return

        bt.cmd("trust " + mac)
        time.sleep(0.5)
        bt.cmd("connect " + mac)
        bt.esperar(teclas, 10, lambda l: "ok" if ("Connection successful" in l
                                                   or "Connected: yes" in l) else None)
        _beep()
        aviso(tela, teclas, "Controle pareado!", [
            "Pronto. Da proxima",
            "vez e so ligar o",
            "controle e usar",
            "Dirigir no menu.",
        ])
    finally:
        bt.fechar()


def _ps3_conectado():
    path, nome = achar_controle()
    return path is not None and _eh_ps3(nome)


def _esperar_ps3(teclas, presente, timeout, bt):
    """Espera o PS3 aparecer (presente=True) ou sumir (False) no evdev."""
    fim = time.time() + timeout
    while time.time() < fim:
        if teclas.poll() == "backspace":
            return "cancelado"
        if _ps3_conectado() == presente:
            return "ok"
        if bt.ler(0.3) is None:   # tambem responde as autorizacoes
            return "erro"
    return "timeout"


def parear_ps3(tela, teclas):
    bt = _bt_abrir(tela)
    if bt is None:
        aviso(tela, teclas, "Erro", ["Bluetooth indisponivel"])
        return
    try:
        if not _ps3_conectado():
            tela.mostrar("Parear PS3 (1/2)", [
                "Ligue o controle",
                "no USB do EV3",
                "(cabo mini-USB).",
            ], "VOLTAR cancela")
            r = _esperar_ps3(teclas, True, 120, bt)
            if r != "ok":
                _falhou(tela, teclas, r)
                return
        _beep()
        time.sleep(2)  # da tempo do EV3 gravar o endereco no controle

        tela.mostrar("Parear PS3 (2/2)", [
            "Tire o cabo USB",
            "e aperte o botao PS",
            "do controle.",
        ], "VOLTAR cancela")
        r = _esperar_ps3(teclas, False, 60, bt)
        if r == "ok":
            r = _esperar_ps3(teclas, True, 60, bt)
        if r != "ok":
            _falhou(tela, teclas, r, ["Ligue no USB e", "tente de novo."])
            return

        for mac, nome in bt.dispositivos():
            if _eh_ps3(nome):
                bt.cmd("trust " + mac)
        time.sleep(0.5)
        _beep()
        aviso(tela, teclas, "PS3 pareado!", [
            "Pronto. Agora e so",
            "apertar PS e usar",
            "Dirigir no menu.",
        ])
    finally:
        bt.fechar()


# =====================================================================
# Info, Brickman e Desligar
# =====================================================================
def _ip():
    out = _run(["hostname", "-I"]).split()
    ips = [x for x in out if re.match(r"^\d+\.\d+\.\d+\.\d+$", x)]
    return ips[0] if ips else "sem rede"


def _bateria():
    try:
        return "{:.1f} V".format(ev3.PowerSupply().measured_volts)
    except Exception:
        return "?"


# =====================================================================
# Rede (connman): mostra IP e conecta Wi-Fi salvo / Bluetooth do PC
# =====================================================================
def _servicos_rede():
    """Le 'connmanctl services'. Devolve [(id, nome, estado)]."""
    out = _run(["connmanctl", "services"], timeout=15)
    servicos = []
    for linha in out.splitlines():
        if len(linha) < 5 or not linha.strip():
            continue
        partes = linha[4:].rsplit(None, 1)
        if len(partes) != 2:
            continue
        nome, sid = partes[0].strip(), partes[1].strip()
        if not re.match(r"^(wifi|bluetooth|ethernet|gadget)_", sid):
            continue
        flags = linha[:4]
        if "O" in flags:
            estado = "online"
        elif "R" in flags:
            estado = "ligado"
        else:
            estado = ""
        servicos.append((sid, nome or sid, estado))
    return servicos


def _tipo(sid):
    for pref, nome in (("bluetooth_", "BT"), ("wifi_", "WiFi"),
                       ("gadget_", "USB"), ("ethernet_", "Cabo")):
        if sid.startswith(pref):
            return nome
    return "?"


def tela_rede(tela, teclas):
    tela.mostrar("Rede", ["Ligando Bluetooth", "e Wi-Fi..."])
    for tech in ("bluetooth", "wifi", "gadget"):
        _run(["connmanctl", "enable", tech])
    _run(["connmanctl", "scan", "wifi"], timeout=20)
    sel = 0
    while True:
        servicos = _servicos_rede()
        if not servicos:
            aviso(tela, teclas, "Rede " + _ip(), [
                "Nada encontrado.",
                "Bluetooth do PC:",
                "pareie o PC com o",
                "EV3 primeiro."])
            return
        itens = ["{} {}{}".format(_tipo(sid), nome, " *" if est else "")
                 for sid, nome, est in servicos]
        escolha = lista(tela, teclas, "IP " + _ip(), itens, min(sel, len(itens) - 1),
                        "* = conectado  ENTER")
        if escolha is None:
            return
        sel = escolha
        sid, nome, est = servicos[escolha]
        if est:
            if confirmar(tela, teclas, nome[:20], ["Ja conectado.", "Desconectar?"]):
                _run(["connmanctl", "disconnect", sid], timeout=20)
            continue
        tela.mostrar("Conectando", [nome, "Aguarde..."])
        out = _run(["connmanctl", "connect", sid], timeout=40)
        _run(["connmanctl", "config", sid, "--autoconnect", "yes"])
        print("connmanctl connect {}: {}".format(sid, out.strip()))
        time.sleep(2)
        if "Connected" in out or "Already connected" in out:
            aviso(tela, teclas, "Conectado!", [nome, "IP: " + _ip(),
                                              "ssh robot@" + _ip()])
        else:
            aviso(tela, teclas, "Nao conectou", [nome, out.strip()[:40],
                                                 "Wi-Fi novo: conecte", "pelo Brickman 1 vez."])


def tela_info(tela, teclas):
    while True:
        path, nome = achar_controle()
        tela.mostrar("Info", [
            "IP: " + _ip(),
            "Bateria: " + _bateria(),
            "Controle: " + (_rotulo(nome) if path else "nenhum"),
            "Login: robot / maker",
        ], "Aperte um botao")
        if teclas.wait(2.0):
            return


def abrir_brickman(tela, teclas):
    global _brickman_pedido
    if not confirmar(tela, teclas, "Brickman", [
            "Abrir o menu normal", "do ev3dev?", "Para voltar aqui:", "reinicie o EV3."]):
        return
    _brickman_pedido = True
    tela.mostrar("Brickman", ["Abrindo..."])
    parar_tudo()
    _console_grafico(False)
    print("Usuario abriu o brickman pelo menu.")
    # para este servico (senao o Restart=always traz ele de volta)
    _run(["systemctl", "--no-block", "start", "brickman.service"])
    _run(["systemctl", "--no-block", "stop", "ev3main.service"])
    time.sleep(30)
    sys.exit(0)


def desligar(tela, teclas):
    if not confirmar(tela, teclas, "Desligar", ["Desligar o EV3?"]):
        return
    parar_tudo()
    tela.mostrar("Desligando", ["Ate mais!"])
    _run(["poweroff"])
    time.sleep(30)


# =====================================================================
# Menu principal
# =====================================================================
_brickman_pedido = False   # True quando o usuario escolheu abrir o brickman


def _vigiar_brickman():
    """Se algo abrir o brickman por tras, ele briga pela tela. Fecha ele.
    Roda numa thread separada para nao travar os botoes do menu."""
    while True:
        time.sleep(5)
        if _brickman_pedido:
            return
        if _run(["systemctl", "is-active", "brickman.service"]).strip() == "active":
            print("brickman estava rodando por fora; parando ele.")
            _run(["systemctl", "--no-block", "stop", "brickman.service"])
            time.sleep(2)
            _console_grafico(True)


def _status():
    path, nome = achar_controle()
    if path:
        return "{} conectado".format(_rotulo(nome))
    return "Sem controle"


def main():
    def _sigterm(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _sigterm)

    tela = Tela()
    teclas = Teclas()
    vigia = threading.Thread(target=_vigiar_brickman)
    vigia.daemon = True
    vigia.start()
    _beep()

    opcoes = [
        ("Dirigir", modo_dirigir),
        ("Parear controle", parear_controle),
        ("Parear PS3", parear_ps3),
        ("Rede (IP/Bluetooth PC)", tela_rede),
        ("Info (bateria)", tela_info),
        ("Brickman", abrir_brickman),
        ("Desligar", desligar),
    ]
    sel = 0
    try:
        while True:
            escolha = lista(tela, teclas, "Menu EV3",
                            [o[0] for o in opcoes], sel, status=_status)
            if escolha is None:
                continue          # VOLTAR no menu principal nao faz nada
            sel = escolha
            try:
                opcoes[escolha][1](tela, teclas)
            except SystemExit:
                raise
            except Exception as e:
                print("Erro em {}: {}".format(opcoes[escolha][0], e))
                parar_tudo()
                aviso(tela, teclas, "Erro", [str(e)[:60]])
    except KeyboardInterrupt:
        print("Interrompido.")
    finally:
        parar_tudo()
        tela.mostrar("Encerrado", [])
        _console_grafico(False)


if __name__ == "__main__":
    main()
