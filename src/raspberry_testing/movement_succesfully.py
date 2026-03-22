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

# Forzar event correcto
FORCED_EVENT_PATH = "/dev/input/event4"
# FORCED_EVENT_PATH = None

RETRY_DELAY = 2.0
SEND_INTERVAL = 0.02      # 50 Hz
PRINT_INTERVAL = 0.50

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
# DEBUG
# =========================================================

DEBUG = True
LOOP_STALL_WARN_S = 0.05

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

    while True:
        dev = find_controller()
        if dev:
            return dev
        time.sleep(RETRY_DELAY)

# =========================================================
# MOVEMENT LOGIC
# =========================================================

def compute_v_w(lx, l2, r2):
    v = int((r2 - l2) * V_MAX)

    throttle = max(l2, r2)
    w_scale = W_TANK - (W_TANK - W_MIN_CURVA) * throttle
    w = int(lx * w_scale)

    v = clamp(v, -1000, 1000)
    w = clamp(w, -1000, 1000)

    return v, w

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
    ser = open_uart()

    while True:
        dev = wait_for_controller()

        estado = {
            ABS_X: AXIS_CENTER,
            ABS_Z: 0,
            ABS_RZ: 0
        }

        last_send = 0.0
        last_print = 0.0
        last_loop = time.time()

        total_loops = 0
        total_events = 0
        total_uart_sent = 0

        try:
            try:
                dev.grab()
            except PermissionError:
                print("[CONTROL] No se pudo hacer grab(), prueba con sudo")

            print(f"[CONTROL] Conectado: {dev.path} ({dev.name})")

            while True:
                now = time.time()
                loop_dt = now - last_loop
                last_loop = now
                total_loops += 1

                if loop_dt > LOOP_STALL_WARN_S:
                    print(f"[WARN] Loop lento: {loop_dt*1000:.1f} ms")

                got_events_this_loop = 0

                # =====================================
                # LECTURA NO BLOQUEANTE CON read_one()
                # =====================================
                while True:
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

                # =====================================
                # PROCESAMIENTO
                # =====================================
                lx = normalize_axis(estado.get(ABS_X, AXIS_CENTER))
                l2 = normalize_trigger(estado.get(ABS_Z, 0))
                r2 = normalize_trigger(estado.get(ABS_RZ, 0))

                lx = deadzone(lx, DEADZONE_STICK)
                l2 = 0.0 if l2 < DEADZONE_TRIGGER else l2
                r2 = 0.0 if r2 < DEADZONE_TRIGGER else r2

                v, w = compute_v_w(lx, l2, r2)
                mov = describe(v, w)

                # =====================================
                # UART SEND PERIODICO
                # =====================================
                if now - last_send >= SEND_INTERVAL:
                    last_send = now
                    packet = f"<{v},{w}>\n"
                    ser = safe_uart_send(ser, packet)
                    total_uart_sent += 1

                # =====================================
                # PRINT STATUS
                # =====================================
                if now - last_print >= PRINT_INTERVAL:
                    last_print = now
                    print(
                        f"[STAT] "
                        f"v={v:4d} w={w:4d} "
                        f"LX={lx:+.2f} L2={l2:.2f} R2={r2:.2f} "
                        f"{mov} "
                        f"loops={total_loops} events={total_events} "
                        f"uart={total_uart_sent} got={got_events_this_loop}"
                    )

                time.sleep(0.001)

        except OSError as e:
            print(f"[CONTROL] OSError real, posible desconexion: {e}")
            ser = safe_uart_send(ser, "<0,0>\n")
            time.sleep(RETRY_DELAY)

        except Exception as e:
            print(f"[ERROR] {e}")
            ser = safe_uart_send(ser, "<0,0>\n")
            time.sleep(RETRY_DELAY)

        finally:
            try:
                dev.ungrab()
            except Exception:
                pass

# =========================================================

if __name__ == "__main__":
    main()