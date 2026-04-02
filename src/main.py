#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import serial
import os
import signal
from evdev import InputDevice, list_devices, ecodes, ff

# =========================================================
# CONFIG
# =========================================================

UART_PORT = "/dev/serial0"
UART_BAUD = 115200

FORCED_EVENT_PATH = "/dev/input/event4"
# FORCED_EVENT_PATH = None

RETRY_DELAY = 2.0
SEND_INTERVAL = 0.02      # 50 Hz
PRINT_INTERVAL = 0.50

ABS_X   = ecodes.ABS_X     # stick izquierdo X
ABS_Y   = ecodes.ABS_Y
ABS_RX  = ecodes.ABS_RX    # stick derecho X
ABS_RY  = ecodes.ABS_RY    # stick derecho Y
ABS_Z   = ecodes.ABS_Z     # L2
ABS_RZ  = ecodes.ABS_RZ    # R2

AXIS_CENTER = 128

DEADZONE_STICK = 0.08
DEADZONE_TRIGGER = 0.03

V_MAX = 1000
W_TANK = 1000

# Flippers
F_MAX = 1000
INVERT_RY = True   # normalmente arriba en RY da negativo; esto lo corrige

# Shutdown
BTN_OPTIONS = ecodes.BTN_START
SHUTDOWN_HOLD = 5.0

running = True


# =========================================================
# EXIT
# =========================================================
def handle_exit(sig, frame):
    global running
    print("\n[EXIT] Señal recibida, cerrando limpio...")
    running = False

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


# =========================================================
# UTILS
# =========================================================
def clamp(x, lo, hi):
    return max(lo, min(hi, x))

def normalize_axis(value, center=128):
    if value >= center:
        out = (value - center) / (255 - center)
    else:
        out = (value - center) / (center - 0)
    return clamp(out, -1.0, 1.0)

def normalize_trigger(value):
    return clamp(value / 255.0, 0.0, 1.0)

def deadzone(x, d):
    return 0.0 if abs(x) < d else x


# =========================================================
# RUMBLE
# =========================================================
def setup_rumble(dev):
    try:
        if ecodes.EV_FF not in dev.capabilities():
            print("[RUMBLE] No soportado")
            return None

        rumble = ff.Rumble(strong_magnitude=0xc000, weak_magnitude=0x8000)
        effect = ff.Effect(
            ecodes.FF_RUMBLE,
            -1,
            0,
            ff.Trigger(0, 0),
            ff.Replay(1000, 0),
            ff.EffectType(ff_rumble_effect=rumble)
        )

        effect_id = dev.upload_effect(effect)
        print(f"[RUMBLE] Effect ID={effect_id}")
        return effect_id
    except Exception as e:
        print(f"[RUMBLE] Error: {e}")
        return None

def start_rumble(dev, effect_id):
    if effect_id is not None:
        try:
            dev.write(ecodes.EV_FF, effect_id, 1)
        except Exception:
            pass

def stop_rumble(dev, effect_id):
    if effect_id is not None:
        try:
            dev.write(ecodes.EV_FF, effect_id, 0)
        except Exception:
            pass


# =========================================================
# UART
# =========================================================
def open_uart():
    while running:
        try:
            ser = serial.Serial(UART_PORT, UART_BAUD, timeout=0)
            print(f"[UART] Abierto {UART_PORT} @ {UART_BAUD}")
            return ser
        except Exception as e:
            print(f"[UART] Error abriendo puerto: {e}")
            print("[UART] Reintentando...")
            time.sleep(RETRY_DELAY)
    return None

def safe_uart_send(ser, msg):
    if ser is None:
        return None

    try:
        ser.write(msg.encode())
        return ser
    except Exception as e:
        print(f"[UART] Error enviando: {e}")
        print("[UART] Reabriendo UART")

        try:
            ser.close()
        except Exception:
            pass

        return open_uart()


# =========================================================
# CONTROL DETECTION
# =========================================================
def device_abs_codes(dev):
    try:
        caps = dev.capabilities()
        abs_caps = caps.get(ecodes.EV_ABS, [])
        return [item[0] if isinstance(item, tuple) else item for item in abs_caps]
    except Exception:
        return []

def looks_like_main_gamepad(dev):
    name = dev.name.lower()
    abs_codes = device_abs_codes(dev)

    if "motion sensors" in name:
        return False

    if "touchpad" in name:
        return False

    required = [
        ecodes.ABS_X,
        ecodes.ABS_Y,
        ecodes.ABS_Z,
        ecodes.ABS_RZ,
        ecodes.ABS_HAT0X,
        ecodes.ABS_HAT0Y,
    ]

    return all(code in abs_codes for code in required)

def find_controller():
    if FORCED_EVENT_PATH:
        try:
            dev = InputDevice(FORCED_EVENT_PATH)
            print(f"[CONTROL] Forzado: {dev.path} ({dev.name})")
            return dev
        except Exception as e:
            print(f"[CONTROL] No se pudo abrir {FORCED_EVENT_PATH}: {e}")
            return None

    candidates = []

    for path in list_devices():
        try:
            dev = InputDevice(path)
            if looks_like_main_gamepad(dev):
                candidates.append(dev)
        except Exception:
            continue

    if not candidates:
        return None

    dev = candidates[0]
    print(f"[CONTROL] Encontrado: {dev.path} ({dev.name})")
    return dev

def wait_for_controller():
    print("[CONTROL] Buscando control...")

    while running:
        dev = find_controller()
        if dev:
            return dev
        time.sleep(RETRY_DELAY)

    return None


# =========================================================
# LOGICA DE MOVIMIENTO
# =========================================================
def compute_v_w(lx, l2, r2):
    v = int((r2 - l2) * V_MAX)
    w = int(lx * W_TANK)

    v = clamp(v, -1000, 1000)
    w = clamp(w, -1000, 1000)

    return v, w

def compute_flipper_cmd(ry):
    if INVERT_RY:
        ry = -ry

    f = int(ry * F_MAX)
    return clamp(f, -1000, 1000)

def describe(v, w):
    if abs(v) < 50 and abs(w) < 50:
        return "QUIETO"

    if abs(v) < 50:
        return "GIRO TANQUE DERECHA" if w > 0 else "GIRO TANQUE IZQUIERDA"

    if v > 0:
        if w > 50:
            return "ADELANTE + DERECHA"
        if w < -50:
            return "ADELANTE + IZQUIERDA"
        return "ADELANTE"

    if v < 0:
        if w > 50:
            return "ATRAS + DERECHA"
        if w < -50:
            return "ATRAS + IZQUIERDA"
        return "ATRAS"

    return "MOV"


# =========================================================
# MAIN
# =========================================================
def main():
    global running

    ser = open_uart()
    if ser is None:
        return

    while running:
        dev = wait_for_controller()
        if dev is None:
            break

        estado = {
            ABS_X: AXIS_CENTER,
            ABS_RX: AXIS_CENTER,
            ABS_RY: AXIS_CENTER,
            ABS_Z: 0,
            ABS_RZ: 0
        }

        last_send = 0.0
        last_print = 0.0

        total_loops = 0
        total_events = 0
        total_uart_sent = 0

        options_pressed = False
        options_press_time = 0.0
        shutdown_triggered = False

        rumble_effect_id = None
        rumble_on = False

        try:
            try:
                dev.grab()
            except PermissionError:
                print("[CONTROL] No se pudo hacer grab(), prueba con sudo")

            print(f"[CONTROL] Conectado: {dev.path} ({dev.name})")
            rumble_effect_id = setup_rumble(dev)

            while running:
                now = time.time()
                total_loops += 1
                got_events_this_loop = 0

                while running:
                    try:
                        event = dev.read_one()
                    except BlockingIOError:
                        break
                    except OSError:
                        raise
                    except Exception as e:
                        print(f"[ERROR] Leyendo eventos: {e}")
                        break

                    if event is None:
                        break

                    got_events_this_loop += 1
                    total_events += 1

                    if event.type == ecodes.EV_ABS:
                        estado[event.code] = event.value

                    elif event.type == ecodes.EV_KEY:
                        if event.code == BTN_OPTIONS:
                            if event.value == 1:
                                options_pressed = True
                                options_press_time = now
                                shutdown_triggered = False
                            elif event.value == 0:
                                options_pressed = False
                                shutdown_triggered = False
                                if rumble_on:
                                    stop_rumble(dev, rumble_effect_id)
                                    rumble_on = False

                lx = normalize_axis(estado.get(ABS_X, AXIS_CENTER))
                ry = normalize_axis(estado.get(ABS_RY, AXIS_CENTER))
                l2 = normalize_trigger(estado.get(ABS_Z, 0))
                r2 = normalize_trigger(estado.get(ABS_RZ, 0))

                lx = deadzone(lx, DEADZONE_STICK)
                ry = deadzone(ry, DEADZONE_STICK)
                l2 = 0.0 if l2 < DEADZONE_TRIGGER else l2
                r2 = 0.0 if r2 < DEADZONE_TRIGGER else r2

                v, w = compute_v_w(lx, l2, r2)
                f = compute_flipper_cmd(ry)
                mov = describe(v, w)

                if options_pressed:
                    held = now - options_press_time

                    if not rumble_on:
                        start_rumble(dev, rumble_effect_id)
                        rumble_on = True

                    if held >= SHUTDOWN_HOLD and not shutdown_triggered:
                        shutdown_triggered = True
                        print("[SYSTEM] APAGANDO RASPBERRY...")
                        stop_rumble(dev, rumble_effect_id)
                        rumble_on = False

                        for _ in range(5):
                            ser = safe_uart_send(ser, "<0,0,0>\n")
                            time.sleep(0.02)

                        os.system("sudo shutdown now")
                else:
                    if rumble_on:
                        stop_rumble(dev, rumble_effect_id)
                        rumble_on = False

                if now - last_send >= SEND_INTERVAL:
                    last_send = now
                    packet = f"<{v},{w},{f}>\n"
                    ser = safe_uart_send(ser, packet)
                    total_uart_sent += 1

                if now - last_print >= PRINT_INTERVAL:
                    last_print = now
                    print(
                        f"[STAT] "
                        f"v={v:4d} w={w:4d} f={f:4d} "
                        f"LX={lx:+.2f} RY={ry:+.2f} L2={l2:.2f} R2={r2:.2f} "
                        f"{mov} "
                        f"loops={total_loops} events={total_events} "
                        f"uart={total_uart_sent} got={got_events_this_loop}"
                    )

                time.sleep(0.001)

        except KeyboardInterrupt:
            print("\n[EXIT] Ctrl+C detectado, cerrando limpio...")
            running = False
            ser = safe_uart_send(ser, "<0,0,0>\n")

        except OSError as e:
            print(f"[CONTROL] OSError real, posible desconexion: {e}")
            ser = safe_uart_send(ser, "<0,0,0>\n")
            time.sleep(RETRY_DELAY)

        except Exception as e:
            print(f"[ERROR] {e}")
            ser = safe_uart_send(ser, "<0,0,0>\n")
            time.sleep(RETRY_DELAY)

        finally:
            try:
                stop_rumble(dev, rumble_effect_id)
            except Exception:
                pass

            try:
                dev.ungrab()
            except Exception:
                pass

    try:
        ser = safe_uart_send(ser, "<0,0,0>\n")
    except Exception:
        pass

    try:
        if ser is not None:
            ser.close()
    except Exception:
        pass

    print("[EXIT] Programa terminado.")


if __name__ == "__main__":
    main()
