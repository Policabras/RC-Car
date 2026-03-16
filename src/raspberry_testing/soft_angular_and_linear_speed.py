#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from evdev import InputDevice, ecodes

DS4_PATH = "/dev/input/event4"

ABS_X  = ecodes.ABS_X    # joystick izquierdo horizontal
ABS_Z  = ecodes.ABS_Z    # L2
ABS_RZ = ecodes.ABS_RZ   # R2

AXIS_MIN = 0
AXIS_MAX = 255
AXIS_CENTER = 128

TRIGGER_MIN = 0
TRIGGER_MAX = 255

PRINT_INTERVAL = 0.1

DEADZONE_STICK = 0.08
DEADZONE_TRIGGER = 0.03

V_MAX = 1.0
W_TANK = 1.0     # giro fuerte cuando no hay avance/retroceso
W_CURVA = 0.45   # giro más suave cuando sí hay gatillo

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
    if abs(x) < deadzone:
        return 0.0
    return x

def describir_movimiento(v, w, eps_v=0.05, eps_w=0.05):
    adelante = v > eps_v
    atras = v < -eps_v
    izquierda = w < -eps_w
    derecha = w > eps_w
    quieto = abs(v) <= eps_v and abs(w) <= eps_w

    if quieto:
        return "QUIETO"

    if not adelante and not atras:
        if izquierda:
            return "GIRO DE TANQUE A LA IZQUIERDA"
        if derecha:
            return "GIRO DE TANQUE A LA DERECHA"

    if adelante and not izquierda and not derecha:
        return "ADELANTE"
    if atras and not izquierda and not derecha:
        return "ATRAS"
    if adelante and izquierda:
        return "ADELANTE + CURVA A LA IZQUIERDA"
    if adelante and derecha:
        return "ADELANTE + CURVA A LA DERECHA"
    if atras and izquierda:
        return "ATRAS + CURVA A LA IZQUIERDA"
    if atras and derecha:
        return "ATRAS + CURVA A LA DERECHA"

    return "MOVIMIENTO MIXTO"

def main():
    dev = InputDevice(DS4_PATH)

    print(f"Using device: {dev.path} ({dev.name})")
    print("R2 = adelante | L2 = atras | LX = giro")
    print("Sin gatillo + LX = giro de tanque\n")

    estado = {
        ABS_X: AXIS_CENTER,
        ABS_Z: TRIGGER_MIN,
        ABS_RZ: TRIGGER_MIN,
    }

    last_print = 0.0

    try:
        dev.grab()
    except PermissionError:
        print("No se pudo hacer grab() (probablemente falta sudo).")

    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_ABS:
                estado[event.code] = event.value

            now = time.time()
            if now - last_print >= PRINT_INTERVAL:
                last_print = now

                lx = normalize_axis(estado.get(ABS_X, AXIS_CENTER))
                l2 = normalize_trigger(estado.get(ABS_Z, TRIGGER_MIN))
                r2 = normalize_trigger(estado.get(ABS_RZ, TRIGGER_MIN))

                lx = apply_deadzone(lx, DEADZONE_STICK)
                l2 = 0.0 if l2 < DEADZONE_TRIGGER else l2
                r2 = 0.0 if r2 < DEADZONE_TRIGGER else r2

                # Velocidad lineal
                v = V_MAX * (r2 - l2)

                # Velocidad angular:
                # - si no hay avance/retroceso -> giro de tanque
                # - si sí hay avance/retroceso -> curva suave
                if abs(v) < 0.05:
                    w = W_TANK * lx
                else:
                    w = W_CURVA * lx

                # Si al probar el sentido sale invertido, cambia a:
                # w = -w

                movimiento = describir_movimiento(v, w)

                print("----------- CONTROL -----------")
                print(f"LX       = {lx:+.3f}")
                print(f"L2       = {l2:+.3f}")
                print(f"R2       = {r2:+.3f}")
                print(f"v lineal = {v:+.3f}")
                print(f"w ang    = {w:+.3f}")
                print(f"MOV      = {movimiento}")
                print("--------------------------------\n")

    except KeyboardInterrupt:
        print("Saliendo...")

    except OSError as e:
        print(f"\nError de dispositivo: {e}. ¿Se desconectó el control?")

    finally:
        try:
            dev.ungrab()
        except Exception:
            pass

if __name__ == "__main__":
    main()