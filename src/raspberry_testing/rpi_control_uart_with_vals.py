#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import serial
from evdev import InputDevice, list_devices, ecodes

# =========================================================
# CONFIG
# =========================================================

UART_PORT = "/dev/serial0"
UART_BAUD = 115200

# Forzar event correcto (recomendado por ahora)
FORCED_EVENT_PATH = "/dev/input/event4"
# FORCED_EVENT_PATH = None

CONTROL_NAME_HINT = "Wireless Controller"

RETRY_DELAY = 2.0
SEND_INTERVAL = 0.05
PRINT_INTERVAL = 0.20

ABS_X  = ecodes.ABS_X
ABS_Y  = ecodes.ABS_Y
ABS_Z  = ecodes.ABS_Z
ABS_RZ = ecodes.ABS_RZ

AXIS_CENTER = 128

DEADZONE_STICK = 0.08
DEADZONE_TRIGGER = 0.03

V_MAX = 1000
W_TANK = 1000
W_MIN_CURVA = 300

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
# UART
# =========================================================

def open_uart():

    while True:
        try:
            ser = serial.Serial(UART_PORT, UART_BAUD, timeout=0)
            print(f"[UART] Abierto {UART_PORT} @ {UART_BAUD}")
            return ser

        except Exception as e:
            print(f"[UART] Error abriendo puerto: {e}")
            print("[UART] Reintentando...")
            time.sleep(RETRY_DELAY)


def safe_uart_send(ser, msg):

    try:
        ser.write(msg.encode())
        return ser

    except Exception as e:
        print(f"[UART] Error enviando: {e}")
        print("[UART] Reabriendo UART")

        try:
            ser.close()
        except:
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
    except:
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

        except:
            continue

    if not candidates:
        return None

    dev = candidates[0]

    print(f"[CONTROL] Encontrado: {dev.path} ({dev.name})")

    return dev


def wait_for_controller():

    print("[CONTROL] Buscando control...")

    while True:

        dev = find_controller()

        if dev:
            return dev

        time.sleep(RETRY_DELAY)

# =========================================================
# MOVEMENT LOGIC
# =========================================================

def compute_v_w(lx, l2, r2):

    # velocidad lineal
    v = int((r2 - l2) * V_MAX)

    # cuánto estás acelerando
    throttle = max(l2, r2)

    # escala de giro progresiva
    w_scale = W_TANK - (W_TANK - W_MIN_CURVA) * throttle

    w = int(lx * w_scale)

    v = clamp(v, -1000, 1000)
    w = clamp(w, -1000, 1000)

    return v, w


def describe(v, w):

    if abs(v) < 50 and abs(w) < 50:
        return "QUIETO"

    if abs(v) < 50:
        if w > 0:
            return "GIRO TANQUE DERECHA"
        else:
            return "GIRO TANQUE IZQUIERDA"

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

    ser = open_uart()

    while True:

        dev = wait_for_controller()

        estado = {
            ABS_X: AXIS_CENTER,
            ABS_Z: 0,
            ABS_RZ: 0
        }

        last_send = 0
        last_print = 0

        try:

            try:
                dev.grab()
            except PermissionError:
                print("[CONTROL] No se pudo hacer grab(), prueba con sudo")

            print(f"[CONTROL] Conectado: {dev.path} ({dev.name})")

            for event in dev.read_loop():

                if event.type == ecodes.EV_ABS:
                    estado[event.code] = event.value

                now = time.time()

                lx = normalize_axis(estado.get(ABS_X, AXIS_CENTER))
                l2 = normalize_trigger(estado.get(ABS_Z, 0))
                r2 = normalize_trigger(estado.get(ABS_RZ, 0))

                lx = deadzone(lx, DEADZONE_STICK)
                l2 = 0 if l2 < DEADZONE_TRIGGER else l2
                r2 = 0 if r2 < DEADZONE_TRIGGER else r2

                v, w = compute_v_w(lx, l2, r2)

                mov = describe(v, w)

                # ======================
                # UART SEND
                # ======================

                if now - last_send >= SEND_INTERVAL:

                    last_send = now

                    packet = f"<{v},{w}>\n"

                    ser = safe_uart_send(ser, packet)

                # ======================
                # PRINT STATUS
                # ======================

                if now - last_print >= PRINT_INTERVAL:

                    last_print = now

                    print(
                        f"v={v:4d} w={w:4d} "
                        f"LX={lx:+.2f} "
                        f"L2={l2:.2f} "
                        f"R2={r2:.2f} "
                        f"{mov} "
                        f"UART=<{v},{w}>"
                    )

        except OSError:

            print("[CONTROL] Control desconectado")

            ser = safe_uart_send(ser, "<0,0>\n")

            time.sleep(RETRY_DELAY)

        finally:

            try:
                dev.ungrab()
            except:
                pass


# =========================================================

if __name__ == "__main__":
    main()