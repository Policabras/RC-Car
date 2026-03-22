#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import serial
import os
from evdev import InputDevice, list_devices, ecodes, ff

# =========================================================
# CONFIG
# =========================================================

UART_PORT = "/dev/serial0"
UART_BAUD = 115200

FORCED_EVENT_PATH = "/dev/input/event4"

RETRY_DELAY = 2.0
SEND_INTERVAL = 0.02
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
W_MIN_CURVA = 600   # <- ya ajustado para girar mejor

# SHUTDOWN
BTN_OPTIONS = ecodes.BTN_START
SHUTDOWN_HOLD = 5.0

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

        return dev.upload_effect(effect)
    except:
        return None

def start_rumble(dev, effect_id):
    if effect_id is not None:
        try:
            dev.write(ecodes.EV_FF, effect_id, 1)
        except:
            pass

def stop_rumble(dev, effect_id):
    if effect_id is not None:
        try:
            dev.write(ecodes.EV_FF, effect_id, 0)
        except:
            pass

# =========================================================
# UART
# =========================================================

def open_uart():
    while True:
        try:
            ser = serial.Serial(UART_PORT, UART_BAUD, timeout=0)
            print(f"[UART] Abierto {UART_PORT}")
            return ser
        except:
            time.sleep(RETRY_DELAY)

def safe_uart_send(ser, msg):
    try:
        ser.write(msg.encode())
        return ser
    except:
        try:
            ser.close()
        except:
            pass
        return open_uart()

# =========================================================
# CONTROL
# =========================================================

def find_controller():
    try:
        dev = InputDevice(FORCED_EVENT_PATH)
        print(f"[CONTROL] {dev.path}")
        return dev
    except:
        return None

def wait_for_controller():
    while True:
        dev = find_controller()
        if dev:
            return dev
        time.sleep(RETRY_DELAY)

# =========================================================
# MOVEMENT
# =========================================================

def compute_v_w(lx, l2, r2):
    v = int((r2 - l2) * V_MAX)

    throttle = max(l2, r2)
    w_scale = W_TANK - (W_TANK - W_MIN_CURVA) * throttle
    w = int(lx * w_scale)

    return clamp(v, -1000, 1000), clamp(w, -1000, 1000)

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

        # shutdown
        options_pressed = False
        press_time = 0

        rumble_id = setup_rumble(dev)
        rumble_on = False

        try:
            dev.grab()

            while True:
                now = time.time()

                # ========= INPUT =========
                while True:
                    event = dev.read_one()
                    if event is None:
                        break

                    if event.type == ecodes.EV_ABS:
                        estado[event.code] = event.value

                    if event.type == ecodes.EV_KEY:
                        if event.code == BTN_OPTIONS:
                            if event.value == 1:
                                options_pressed = True
                                press_time = now
                            elif event.value == 0:
                                options_pressed = False
                                stop_rumble(dev, rumble_id)
                                rumble_on = False

                # ========= NORMALIZACION =========
                lx = deadzone(normalize_axis(estado.get(ABS_X, AXIS_CENTER)), DEADZONE_STICK)
                l2 = normalize_trigger(estado.get(ABS_Z, 0))
                r2 = normalize_trigger(estado.get(ABS_RZ, 0))

                v, w = compute_v_w(lx, l2, r2)

                # ========= SHUTDOWN =========
                if options_pressed:
                    held = now - press_time

                    if not rumble_on:
                        start_rumble(dev, rumble_id)
                        rumble_on = True

                    if held > SHUTDOWN_HOLD:
                        print("APAGANDO...")
                        stop_rumble(dev, rumble_id)
                        ser = safe_uart_send(ser, "<0,0>\n")
                        time.sleep(0.2)
                        os.system("sudo shutdown now")

                # ========= UART =========
                if now - last_send > SEND_INTERVAL:
                    last_send = now
                    ser = safe_uart_send(ser, f"<{v},{w}>\n")

                # ========= DEBUG =========
                if now - last_print > PRINT_INTERVAL:
                    last_print = now
                    print(f"v={v} w={w}")

                time.sleep(0.001)

        except:
            ser = safe_uart_send(ser, "<0,0>\n")
            time.sleep(RETRY_DELAY)

        finally:
            stop_rumble(dev, rumble_id)
            try:
                dev.ungrab()
            except:
                pass

if __name__ == "__main__":
    main()

# Este es el código más reciente hasta ahora 22/03/2026, a hora 03:30 AM
# con la funcionalidad de movimiento y shutdown. 
