

import evdev
import ev3dev.auto as ev3
import threading
import time
import sys

try:
    from ev3dev2.display import Display as _Display
except Exception:
    _Display = None
try:
    from PIL import ImageFont as _ImageFont
except Exception:
    _ImageFont = None

# Ative para imprimir eventos brutos (mapa/debug)
DEBUG_EVENT = False

## Funcoes utilitarias ##
def clamp(n, minn, maxn):
    return max(min(maxn, n), minn)

def scale(val, src, dst):
    return (float(val - src[0]) / (src[1] - src[0])) * (dst[1] - dst[0]) + dst[0]

def scale_stick(value):
    return scale(value,(0,255),(-1000,1000))

def dc_clamp(value):
    return clamp(value,-1000,1000)

## Inicializacao ##
def _beep():
    try:
        ev3.Sound.beep()
    except Exception:
        pass

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
    try:
        fs = int(forward_speed)
        ss = int(side_speed)
    except Exception:
        fs = 0
        ss = 0
    _display_lines([
        "DEBUG",
        "t{} c{}".format(_debug_last_event.type, _debug_last_event.code),
        "v{}".format(_debug_last_event.value),
        "F {} S {}".format(fs, ss),
    ])

def _read_buttons(btn):
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

def _device_label(device, max_len=12):
    try:
        name = device.name or device.fn
    except Exception:
        name = "device"
    name = name.strip()
    if len(name) > max_len:
        return name[: max_len - 3] + "..."
    return name

def _select_with_ev3_buttons(devices, timeout_s=30, preferred_idx=0):
    try:
        btn = ev3.Button()
    except Exception as e:
        print("EV3 buttons not available ({}) - using device 0.".format(e))
        return devices[0].fn

    idx = preferred_idx if 0 <= preferred_idx < len(devices) else 0
    print("Use botoes do EV3: CIMA/BAIXO muda, ENTER confirma.")
    print("Atual: {} -> {}".format(devices[idx].fn, devices[idx].name))
    def _show():
        total = len(devices)
        _display_lines([
            "Controle",
            "{}/{} {}".format(idx + 1, total, _device_label(devices[idx])),
            "CIMA/BAIXO",
            "ENTER OK",
        ])

    _show()
    start = time.time()
    last_draw = 0

    while time.time() - start < timeout_s:
        # redesenha sempre para o brickman nao apagar
        now = time.time()
        if now - last_draw > 0.2:
            _show()
            last_draw = now
        pressed = _read_buttons(btn)
        if "down" in pressed or "right" in pressed:
            idx = (idx + 1) % len(devices)
            print("Atual: {} -> {}".format(devices[idx].fn, devices[idx].name))
            _show()
            _beep()
            time.sleep(0.25)
            continue
        if "up" in pressed or "left" in pressed:
            idx = (idx - 1) % len(devices)
            print("Atual: {} -> {}".format(devices[idx].fn, devices[idx].name))
            _show()
            _beep()
            time.sleep(0.25)
            continue
        if "enter" in pressed:
            print("Selecionado: {} -> {}".format(devices[idx].fn, devices[idx].name))
            _display_lines([
                "Selecionado",
                devices[idx].name[:16],
                "Iniciando...",
            ])
            _beep()
            return devices[idx].fn
        time.sleep(0.05)

    if 0 <= preferred_idx < len(devices):
        print("Timeout - usando dispositivo preferido.")
        _display_lines([
            "Timeout",
        "Usando preferido",
            devices[preferred_idx].name[:16],
        ])
        return devices[preferred_idx].fn

    print("Timeout - usando dispositivo 0.")
    _display_lines([
        "Timeout",
        "Usando disp 0",
        devices[0].name[:16],
    ])
    return devices[0].fn

def _score_device(device):
    name = ""
    try:
        name = (device.name or "").lower()
    except Exception:
        name = ""
    score = 0
    # nomes comuns de controle
    keywords = [
        "xbox", "x-box", "microsoft", "wireless controller",
        "sony", "ps4", "ps5", "dualshock", "dualsense",
        "nintendo", "switch", "pro controller",
        "gamepad", "controller", "8bitdo",
    ]
    if any(k in name for k in keywords):
        score += 50
    if "brick" in name or "speaker" in name:
        score -= 100
    try:
        caps = device.capabilities()
        if evdev.ecodes.EV_ABS in caps:
            score += 10
        if evdev.ecodes.EV_KEY in caps:
            score += 10
    except Exception:
        pass
    return score

print("Procurando controle...")
devices = [evdev.InputDevice(fn) for fn in evdev.list_devices()]
if not devices:
    print("Nenhum dispositivo de entrada. O controle esta conectado?")
    _display_lines([
        "Sem entrada",
        "Conecte controle",
    ])
    sys.exit(1)

print("\nDispositivos disponiveis:")
for i, d in enumerate(devices):
    print("  {}: {} -> {}".format(i, d.fn, d.name))

# Sempre deixa escolher na tela do EV3 (sem input no console)
preferred_idx = 0
best_score = -999
for i, d in enumerate(devices):
    score = _score_device(d)
    if score > best_score:
        best_score = score
        preferred_idx = i

if best_score < 10:
    print("\nControle nao detectado.")
    _display_lines([
        "Controle nao achado",
        "Escolha disp",
    ])

selected_dev = _select_with_ev3_buttons(devices, preferred_idx=preferred_idx)

print("Usando dispositivo: {}\n".format(selected_dev))
_display_lines([
    "Usando disp",
    selected_dev,
])
gamepad = evdev.InputDevice(selected_dev)

forward_speed = 0
side_speed = 0
running = True

class MotorThread(threading.Thread):
    def __init__(self):
        self.right_motor = ev3.LargeMotor(ev3.OUTPUT_C)
        self.left_motor = ev3.LargeMotor(ev3.OUTPUT_B)
        threading.Thread.__init__(self)

    def run(self):
        print("Motores ativos!")
        global forward_speed, side_speed, running
        try:
            while running:
                # le as velocidades atuais (race condition ok para este uso)
                rs = dc_clamp(forward_speed + side_speed)
                ls = dc_clamp(-forward_speed + side_speed)
                self.right_motor.run_forever(speed_sp=rs)
                self.left_motor.run_forever(speed_sp=ls)
                # pausa curta para evitar loop apertado
                time.sleep(0.02)
        finally:
            try:
                self.right_motor.stop()
            except Exception:
                pass
            try:
                self.left_motor.stop()
            except Exception:
                pass

motor_thread = MotorThread()
motor_thread.setDaemon(True)
motor_thread.start()

try:
    for event in gamepad.read_loop():   # loop infinito
        if DEBUG_EVENT:
            print(repr(event))

        if event.type == evdev.ecodes.EV_ABS:             # Movimento do analogico
            if event.code == 0:         # Eixo X no analogico esquerdo (confirme no debug)
                forward_speed = -scale_stick(event.value)
            if event.code == 1:         # Eixo Y no analogico esquerdo (confirme no debug)
                side_speed = -scale_stick(event.value)
            if side_speed < 100 and side_speed > -100:
                side_speed = 0
            if forward_speed < 100 and forward_speed > -100:
                forward_speed = 0

        # Botao (pode variar por controle) - mantenha, mas valide os codigos
        if event.type == evdev.ecodes.EV_KEY and event.code == 305 and event.value == 1:
            print("Botao X pressionado. Parando.")
            running = False
            time.sleep(0.5) # Espera a thread dos motores terminar
            break
        _debug_lcd(event)
except KeyboardInterrupt:
    print("Interrompido, parando...")
    running = False
    time.sleep(0.5)
except Exception as e:
    print("Erro no loop de entrada:", e)
    running = False
    time.sleep(0.5)