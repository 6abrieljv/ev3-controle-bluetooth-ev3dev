#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Controle do EV3 (ev3dev) por gamepad Bluetooth ou USB.

Suporta PS3 (DualShock 3 / Sixaxis), PS4, Xbox e controles genericos.
- Analogico esquerdo: CIMA/BAIXO acelera, ESQ/DIR vira (arcade drive).
- Encerrar: PS4 = aperte X (igual ao original) | PS3 = segure START 1 s e solte.
- Se o controle desconectar, os motores param e o programa espera ele voltar
  (e so apertar o botao PS de novo).

Compativel com Python 3.5 (ev3dev stretch): NAO usar f-strings.
"""

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
DEBUG_EVENT = False      # imprime eventos brutos (e mostra no LCD)
AUTO_SELECT = True       # entra direto no controle quando reconhece um
DEADZONE = 100           # zona morta do analogico (escala -1000..1000)
MAX_SPEED = 1000         # speed_sp maximo (LargeMotor aguenta ~1050)
INVERT_THROTTLE = False  # inverta se o robo andar para tras ao empurrar pra cima
INVERT_TURN = False      # inverta se virar para o lado errado
QUIT_HOLD_S = 1.0        # tempo segurando o botao de sair

MOTOR_RIGHT = ev3.OUTPUT_C
MOTOR_LEFT = ev3.OUTPUT_B

# Codigos de botao (linux/input-event-codes.h)
BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST = 304, 305, 307, 308
BTN_SELECT, BTN_START, BTN_MODE = 314, 315, 316

# Perfis de controle. Os eixos do analogico esquerdo (ABS_X=0 / ABS_Y=1)
# sao iguais em todos; o que muda entre eles sao os codigos dos botoes.
PROFILES = {
    # PS3 no kernel do ev3dev stretch (hid-sony com mapeamento padrao):
    # X=304  O=305  Triangulo=307  Quadrado=308  L1=310 R1=311
    # L2=312 R2=313 SELECT=314 START=315 PS=316
    # Analogico direito: ABS_RX=3 / ABS_RY=4 ; gatilhos L2/R2: ABS_Z=2 / ABS_RZ=5
    "ps3": {"label": "PS3", "quit": [BTN_START], "hold": QUIT_HOLD_S},

    # PS3 em kernels antigos (ev3dev jessie): X=302 O=301 Triangulo=300
    # Quadrado=303 SELECT=288 START=291 ; analogico direito ABS_Z=2 / ABS_RZ=5
    "ps3_old": {"label": "PS3 (antigo)", "quit": [291], "hold": QUIT_HOLD_S},

    # PS4 igual ao repositorio original: apertou X, para na hora.
    # Kernel novo (stretch): X=304 O=305 Triangulo=307 Quadrado=308
    #   SHARE=314 OPTIONS=315 PS=316
    "ps4": {"label": "PS4", "quit": [BTN_SOUTH], "hold": 0},

    # Kernel antigo: Quadrado=304 X=305 O=306 Triangulo=307 (o 305 do codigo
    # original era o X por causa deste mapeamento)
    "ps4_old": {"label": "PS4 (antigo)", "quit": [305], "hold": 0},

    # Xbox / genericos: mantem o botao 305 do codigo original
    "generic": {"label": "Generico", "quit": [BTN_EAST], "hold": 0},
}


# =====================================================================
# Utilitarios
# =====================================================================
def clamp(n, minn, maxn):
    return max(min(maxn, n), minn)


def scale(val, src, dst):
    return (float(val - src[0]) / (src[1] - src[0])) * (dst[1] - dst[0]) + dst[0]


def scale_axis(value, rng):
    """Converte o valor bruto do eixo para -1000..1000 usando a faixa real
    do controle (PS3/PS4: 0..255, Xbox: -32768..32767)."""
    if rng is None:
        rng = (0, 255)
    if rng[1] == rng[0]:
        return 0
    v = scale(value, rng, (-1000, 1000))
    v = clamp(v, -1000, 1000)
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


# =====================================================================
# LCD
# =====================================================================
_display = None
_font = None
_line_height = 12
_font_size = 16


def _init_display():
    global _display
    if _display is not None:
        return _display
    try:
        if _Display is not None:
            _display = _Display()
            return _display
    except Exception:
        _display = None
    try:
        if hasattr(ev3, "Display"):
            _display = ev3.Display()
    except Exception:
        _display = None
    return _display


def _init_font():
    global _font, _line_height
    if _font is not None:
        return _font
    if _ImageFont is None:
        return None
    try:
        _font = _ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", _font_size)
    except Exception:
        try:
            _font = _ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", _font_size - 2)
        except Exception:
            try:
                _font = _ImageFont.load_default()
            except Exception:
                _font = None
    if _font is not None:
        try:
            _line_height = _font.getsize("Ag")[1] + 2
        except Exception:
            _line_height = 12
    return _font


def _display_lines(lines):
    disp = _init_display()
    if disp is None:
        return
    try:
        font = _init_font()
        draw = disp.draw
        draw.rectangle((0, 0, disp.width, disp.height), fill="white")
        y = 0
        for line in lines:
            if font is not None:
                draw.text((0, y), line, fill="black", font=font)
            else:
                draw.text((0, y), line, fill="black")
            y += _line_height
        disp.update()
    except Exception:
        pass


_debug_last_draw = 0
_debug_last_event = None


def _debug_lcd(event=None):
    if not DEBUG_EVENT:
        return
    global _debug_last_draw, _debug_last_event
    if event is not None:
        _debug_last_event = event
    now = time.time()
    if now - _debug_last_draw < 0.1:
        return
    _debug_last_draw = now
    if _debug_last_event is None:
        return
    _display_lines([
        "DEBUG",
        "t{} c{}".format(_debug_last_event.type, _debug_last_event.code),
        "v{}".format(_debug_last_event.value),
        "A {} V {}".format(int(throttle), int(turn)),
    ])


# =====================================================================
# Botoes do EV3 e menu de selecao
# =====================================================================
def _read_buttons(btn):
    if btn is None:
        return set()
    try:
        if hasattr(btn, "process"):
            btn.process()
    except Exception:
        pass
    try:
        pressed = btn.buttons_pressed
        if callable(pressed):
            pressed = pressed()
        return set(pressed)
    except Exception:
        pass
    pressed = set()
    for name in ("left", "right", "up", "down", "enter", "backspace"):
        try:
            if getattr(btn, name):
                pressed.add(name)
        except Exception:
            pass
    return pressed


def _get_ev3_buttons():
    try:
        return ev3.Button()
    except Exception as e:
        print("Botoes do EV3 indisponiveis ({})".format(e))
        return None


def _device_label(device, max_len=12):
    try:
        name = device.name or _dev_path(device)
    except Exception:
        name = "device"
    name = name.strip()
    if len(name) > max_len:
        return name[: max_len - 3] + "..."
    return name


def _select_with_ev3_buttons(devices, btn, timeout_s=30, preferred_idx=0):
    if btn is None:
        return _dev_path(devices[preferred_idx])

    idx = preferred_idx if 0 <= preferred_idx < len(devices) else 0
    print("Use botoes do EV3: CIMA/BAIXO muda, ENTER confirma.")

    def _show():
        _display_lines([
            "Controle",
            "{}/{} {}".format(idx + 1, len(devices), _device_label(devices[idx])),
            "CIMA/BAIXO",
            "ENTER OK",
        ])

    # espera soltar o ENTER que abriu o menu
    while "enter" in _read_buttons(btn):
        time.sleep(0.05)

    _show()
    start = time.time()
    last_draw = 0
    while time.time() - start < timeout_s:
        now = time.time()
        if now - last_draw > 0.2:   # redesenha para o brickman nao apagar
            _show()
            last_draw = now
        pressed = _read_buttons(btn)
        if "down" in pressed or "right" in pressed:
            idx = (idx + 1) % len(devices)
            _show()
            _beep()
            time.sleep(0.25)
            continue
        if "up" in pressed or "left" in pressed:
            idx = (idx - 1) % len(devices)
            _show()
            _beep()
            time.sleep(0.25)
            continue
        if "enter" in pressed:
            print("Selecionado: {} -> {}".format(_dev_path(devices[idx]), devices[idx].name))
            _beep()
            return _dev_path(devices[idx])
        time.sleep(0.05)

    print("Timeout - usando dispositivo {}.".format(idx))
    return _dev_path(devices[idx])


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

# dispositivos que NAO sao o controle principal
BAD_KEYWORDS = ["brick", "speaker", "motion sensors", "touchpad", "keyboard", "mouse"]


def _score_device(device):
    try:
        name = (device.name or "").lower()
    except Exception:
        name = ""
    score = 0
    if any(k in name for k in CONTROLLER_KEYWORDS):
        score += 50
    if "playstation" in name or "ps3" in name or "sixaxis" in name:
        score += 10
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


def _list_devices():
    devs = []
    for fn in evdev.list_devices():
        try:
            devs.append(evdev.InputDevice(fn))
        except Exception:
            pass
    return devs


def _close_all(devs, keep=None):
    for d in devs:
        if keep is not None and _dev_path(d) == keep:
            continue
        try:
            d.close()
        except Exception:
            pass


def _best_device(devs):
    best_idx, best_score = 0, -999
    for i, d in enumerate(devs):
        s = _score_device(d)
        if s > best_score:
            best_idx, best_score = i, s
    return best_idx, best_score


def _detect_profile(device):
    name = (device.name or "").lower()
    try:
        keys = device.capabilities().get(ecodes.EV_KEY, [])
    except Exception:
        keys = []
    is_ps3 = ("playstation" in name or "ps3" in name or "sixaxis" in name
              or "shanwan" in name or "gasia" in name)
    if is_ps3:
        if BTN_SOUTH in keys:
            return PROFILES["ps3"]
        if 302 in keys:
            return PROFILES["ps3_old"]
        return PROFILES["ps3"]
    if "wireless controller" in name or "ps4" in name or "dualshock" in name:
        # no mapeamento antigo existe o botao 306 (bolinha); no novo, nao
        if 306 in keys:
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


def wait_for_controller(btn, first_run):
    """Espera um controle aparecer. ENTER no EV3 abre o menu manual."""
    print("Procurando controle...")
    last_draw = 0
    last_list = None
    while True:
        devs = _list_devices()
        names = [d.name for d in devs]
        if names != last_list:
            print("Dispositivos: " + ", ".join(
                "{} ({})".format(d.name, _dev_path(d)) for d in devs))
            last_list = names

        if devs:
            idx, score = _best_device(devs)
            found = score >= 50
            if found and (AUTO_SELECT or not first_run):
                path = _dev_path(devs[idx])
                print("Controle encontrado: {} -> {}".format(devs[idx].name, path))
                _close_all(devs)
                return path
            if found or "enter" in _read_buttons(btn):
                path = _select_with_ev3_buttons(devs, btn, preferred_idx=idx)
                _close_all(devs)
                return path

        _close_all(devs)
        now = time.time()
        if now - last_draw > 1.0:
            _display_lines([
                "Sem controle",
                "PS3: aperte PS",
                "ENTER = menu",
            ])
            last_draw = now
        # checa o ENTER com frequencia enquanto espera
        for _ in range(10):
            if "enter" in _read_buttons(btn) and devs:
                break
            time.sleep(0.05)


# =====================================================================
# Motores
# =====================================================================
throttle = 0   # -1000..1000 (frente/tras)
turn = 0       # -1000..1000 (direita positiva)
running = True


class MotorThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.right_motor = ev3.LargeMotor(MOTOR_RIGHT)
        self.left_motor = ev3.LargeMotor(MOTOR_LEFT)
        self._last = None

    def _stop(self):
        for m in (self.right_motor, self.left_motor):
            try:
                m.stop()
            except Exception:
                pass

    def run(self):
        print("Motores ativos!")
        try:
            while running:
                rs = dc_clamp(throttle - turn)
                ls = dc_clamp(throttle + turn)
                # so escreve no sysfs quando muda (economiza CPU do EV3)
                if (rs, ls) != self._last:
                    if rs == 0 and ls == 0:
                        self._stop()
                    else:
                        self.right_motor.run_forever(speed_sp=rs)
                        self.left_motor.run_forever(speed_sp=ls)
                    self._last = (rs, ls)
                time.sleep(0.02)
        finally:
            self._stop()


# =====================================================================
# Loop de direcao
# =====================================================================
def drive(path):
    """Le o controle ate desconectar ('disconnected') ou pedir para sair ('quit')."""
    global throttle, turn
    try:
        dev = evdev.InputDevice(path)
    except Exception as e:
        print("Nao abriu {}: {}".format(path, e))
        return "disconnected"

    profile = _detect_profile(dev)
    ranges = _axis_ranges(dev)
    print("Usando {} [{}] perfil={} eixos={}".format(
        dev.name, path, profile["label"], ranges))
    if profile["label"].startswith("PS3"):
        dica = ["Segure START", "1s = sair"]
    elif profile["label"].startswith("PS4"):
        dica = ["X = parar"]
    else:
        dica = []
    _display_lines(["{} OK".format(profile["label"]), _device_label(dev, 16)] + dica)
    _beep()

    quit_pressed_at = None
    try:
        for event in dev.read_loop():
            if DEBUG_EVENT:
                print(repr(event))

            if event.type == ecodes.EV_ABS:
                if event.code == ecodes.ABS_X:
                    v = scale_axis(event.value, ranges.get(ecodes.ABS_X))
                    turn = -v if INVERT_TURN else v
                elif event.code == ecodes.ABS_Y:
                    # eixo Y do analogico e invertido (cima = valor menor)
                    v = -scale_axis(event.value, ranges.get(ecodes.ABS_Y))
                    throttle = -v if INVERT_THROTTLE else v

            elif event.type == ecodes.EV_KEY and event.code in profile["quit"]:
                hold = profile.get("hold", QUIT_HOLD_S)
                if event.value == 1 and hold <= 0:
                    print("Botao de sair pressionado. Parando.")
                    return "quit"
                if event.value == 1:
                    quit_pressed_at = time.time()
                elif event.value == 0 and quit_pressed_at is not None:
                    if time.time() - quit_pressed_at >= hold:
                        print("Botao de sair segurado. Encerrando.")
                        return "quit"
                    quit_pressed_at = None

            _debug_lcd(event)
    except (OSError, IOError) as e:
        print("Controle desconectado ({})".format(e))
        return "disconnected"
    finally:
        # seguranca: para o robo antes de qualquer outra coisa
        throttle = 0
        turn = 0
        try:
            dev.close()
        except Exception:
            pass
    return "disconnected"


def main():
    global running
    btn = _get_ev3_buttons()

    try:
        motor_thread = MotorThread()
    except Exception as e:
        print("Erro nos motores (B e C conectados?): {}".format(e))
        _display_lines(["Erro motor", "Confira B e C"])
        time.sleep(3)
        sys.exit(1)
    motor_thread.start()

    first_run = True
    try:
        while True:
            path = wait_for_controller(btn, first_run)
            first_run = False
            result = drive(path)
            if result == "quit":
                break
            _beep()
            _display_lines(["Desconectado", "PS3: aperte PS"])
            time.sleep(1)
    except KeyboardInterrupt:
        print("Interrompido, parando...")
    finally:
        running = False
        time.sleep(0.3)
        _display_lines(["Encerrado"])


if __name__ == "__main__":
    main()
