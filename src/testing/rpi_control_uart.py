#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import serial
from evdev import InputDevice, ecodes

# ==============================
# CONFIG
# ==============================
DS4_PATH = "/dev/input/event4"
UART_PORT = "/dev/serial0"
UART_BAUD = 115200

ABS_X  = ecodes.ABS_X    # joystick izquierdo horizontal
ABS_Z  = ecodes.ABS_Z    # L2
ABS_RZ = ecodes.ABS_RZ   # R2

AXIS_MIN = 0
AXIS_MAX = 255
AXIS_CENTER = 128

TRIGGER_MIN = 0
TRIGGER_MAX = 255

DEADZONE_STICK = 0.08
DEADZONE_TRIGGER = 0.03

V_MAX = 1000     # velocidad lineal escalada
W_TANK = 1000    # giro fuerte sin gatillo
W_CURVA = 450    # giro suave con gatillo

PRINT_INTERVAL = 0.10
SEND_INTERVAL = 0.05

# ==============================
# HELPERS
# ==============================
def normalize_axis(value, min_val=0, max_val=255, center=128):
    if value >= center:
        out = (value - center) / (max_val - center)
    else:
        out = (value - center) / (center - min_val)
    return max(-1.0, min(1.0, out))

def normalize_trigger(value, min_val=0, max_val=255):
    out = (value - min_val) / (max_val - min_val)
    return max(0.0, min(1.0, out))

def apply_deadzone(x, deadzone):
    return 0.0 if abs(x) < deadzone else x

def clamp(x, low, high):
    return max(low, min(high, x))

def describir_movimiento(v, w, eps_v=50, eps_w=50):
    adelante = v > eps_v
    atras = v < -eps_v
    izquierda = w < -eps_w
    derecha = w > eps_w

    if not adelante and not atras and not izquierda and not derecha:
        return "QUIETO"
    if not adelante and not atras and izquierda:
        return "GIRO DE TANQUE A LA IZQUIERDA"
    if not adelante and not atras and derecha:
        return "GIRO DE TANQUE A LA DERECHA"
    if adelante and not izquierda and not derecha:
        return "ADELANTE"
    if atras and not izquierda and not derecha:
        return "ATRAS"
    if adelante and izquierda:
        return "ADELANTE + CURVA IZQUIERDA"
    if adelante and derecha:
        return "ADELANTE + CURVA DERECHA"
    if atras and izquierda:
        return "ATRAS + CURVA IZQUIERDA"
    if atras and derecha:
        return "ATRAS + CURVA DERECHA"
    return "MIXTO"

# ==============================
# MAIN
# ==============================
def main():
    dev = InputDevice(DS4_PATH)
    ser = serial.Serial(UART_PORT, UART_BAUD, timeout=0)

    print(f"Control: {dev.path} ({dev.name})")
    print(f"UART: {UART_PORT} @ {UART_BAUD}")
    print("R2 = adelante | L2 = atras | LX = giro\n")

    estado = {
        ABS_X: AXIS_CENTER,
        ABS_Z: TRIGGER_MIN,
        ABS_RZ: TRIGGER_MIN,
    }

    last_print = 0.0
    last_send = 0.0

    try:
        dev.grab()
    except PermissionError:
        print("No se pudo hacer grab(); prueba con sudo.")

    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_ABS:
                estado[event.code] = event.value

            now = time.time()

            # ===== Procesar entradas =====
            lx = normalize_axis(estado.get(ABS_X, AXIS_CENTER))
            l2 = normalize_trigger(estado.get(ABS_Z, TRIGGER_MIN))
            r2 = normalize_trigger(estado.get(ABS_RZ, TRIGGER_MIN))

            lx = apply_deadzone(lx, DEADZONE_STICK)
            l2 = 0.0 if l2 < DEADZONE_TRIGGER else l2
            r2 = 0.0 if r2 < DEADZONE_TRIGGER else r2

            # velocidad lineal
            v = int((r2 - l2) * V_MAX)

            # velocidad angular
            if abs(v) < 50:
                w = int(lx * W_TANK)
            else:
                w = int(lx * W_CURVA)

            v = clamp(v, -1000, 1000)
            w = clamp(w, -1000, 1000)

            movimiento = describir_movimiento(v, w)

            # ===== Enviar UART =====
            if now - last_send >= SEND_INTERVAL:
                last_send = now
                paquete = f"<{v},{w}>\n"
                ser.write(paquete.encode("utf-8"))

            # ===== Imprimir =====
            if now - last_print >= PRINT_INTERVAL:
                last_print = now
                print("----------- CONTROL -----------")
                print(f"LX       = {lx:+.3f}")
                print(f"L2       = {l2:+.3f}")
                print(f"R2       = {r2:+.3f}")
                print(f"v lineal = {v:+d}")
                print(f"w ang    = {w:+d}")
                print(f"MOV      = {movimiento}")
                print(f"UART     = <{v},{w}>")
                print("--------------------------------\n")

    except KeyboardInterrupt:
        print("Saliendo...")

    except OSError as e:
        print(f"Error de dispositivo: {e}")

    finally:
        try:
            dev.ungrab()
        except Exception:
            pass
        ser.close()

if __name__ == "__main__":
    main()