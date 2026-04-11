#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from evdev import InputDevice, ecodes, ff, list_devices

# =========================================================
# CONFIG
# =========================================================
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "gamepad_mqtt_publisher")
MQTT_COMMAND_TOPIC = os.getenv("MQTT_COMMAND_TOPIC", "telemetry/pi_robot_01/cmd")
MQTT_QOS = int(os.getenv("MQTT_QOS", "0"))

FORCED_EVENT_PATH = os.getenv("FORCED_EVENT_PATH", "/dev/input/event4")
if FORCED_EVENT_PATH.strip().lower() in {"", "none", "null"}:
    FORCED_EVENT_PATH = None

RETRY_DELAY = 2.0
SEND_INTERVAL = 0.02      # 50 Hz
PRINT_INTERVAL = 0.50

AXIS_CENTER = 128

DEADZONE_STICK = 0.08
DEADZONE_TRIGGER = 0.03

V_MAX = 1000
W_MAX = 1000
F_MAX = 1000
BASE_MAX = 1000
ELBOW_MAX = 1000
WRIST_MAX = 1000
GRIP_MAX = 1000

INVERT_RY = True
INVERT_LY = True
INVERT_HAT_Y = True

BTN_OPTIONS = ecodes.BTN_START
BTN_GRIP_OPEN = ecodes.BTN_WEST   # cuadrado
BTN_GRIP_CLOSE = ecodes.BTN_EAST  # círculo

SHUTDOWN_HOLD = 5.0

ABS_X = ecodes.ABS_X       # left stick X -> giro
ABS_Y = ecodes.ABS_Y       # left stick Y -> elbow
ABS_RX = ecodes.ABS_RX     # right stick X -> base
ABS_RY = ecodes.ABS_RY     # right stick Y -> flipper
ABS_Z = ecodes.ABS_Z       # L2
ABS_RZ = ecodes.ABS_RZ     # R2
ABS_HAT0Y = ecodes.ABS_HAT0Y  # dpad up/down -> wrist

running = True


# =========================================================
# MODELOS
# =========================================================
@dataclass(slots=True)
class CommandState:
    v: int = 0
    w: int = 0
    f: int = 0
    base: int = 0
    elbow: int = 0
    wrist: int = 0
    grip: int = 0

    def as_payload(self) -> dict[str, int]:
        return {
            "v": self.v,
            "w": self.w,
            "f": self.f,
            "base": self.base,
            "elbow": self.elbow,
            "wrist": self.wrist,
            "grip": self.grip,
        }


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
# MQTT
# =========================================================
def build_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=MQTT_CLIENT_ID,
        protocol=mqtt.MQTTv311,
    )

    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    client.reconnect_delay_set(min_delay=1, max_delay=10)

    def on_connect(client, userdata, flags, reason_code, properties):
        print(f"[MQTT] Conectado rc={reason_code} host={MQTT_HOST}:{MQTT_PORT}")

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        print(f"[MQTT] Desconectado rc={reason_code}")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    return client


def connect_mqtt_forever() -> mqtt.Client:
    while running:
        try:
            client = build_mqtt_client()
            client.connect(MQTT_HOST, MQTT_PORT, 30)
            client.loop_start()
            return client
        except Exception as exc:
            print(f"[MQTT] Error conectando: {exc}")
            print("[MQTT] Reintentando...")
            time.sleep(RETRY_DELAY)

    raise RuntimeError("Stopped before MQTT connection was established")


def publish_command(client: mqtt.Client, state: CommandState) -> None:
    payload = json.dumps(state.as_payload(), separators=(",", ":"))
    info = client.publish(MQTT_COMMAND_TOPIC, payload, qos=MQTT_QOS, retain=False)
    if MQTT_QOS > 0:
        info.wait_for_publish(timeout=1.0)


def publish_zero(client: mqtt.Client, *, times: int = 3, delay_s: float = 0.03) -> None:
    zero = CommandState()
    for _ in range(times):
        try:
            publish_command(client, zero)
        except Exception as exc:
            print(f"[MQTT] Error publicando cero: {exc}")
        time.sleep(delay_s)


# =========================================================
# RUMBLE
# =========================================================
def setup_rumble(dev):
    try:
        if ecodes.EV_FF not in dev.capabilities():
            print("[RUMBLE] No soportado")
            return None

        rumble = ff.Rumble(strong_magnitude=0xC000, weak_magnitude=0x8000)
        effect = ff.Effect(
            ecodes.FF_RUMBLE,
            -1,
            0,
            ff.Trigger(0, 0),
            ff.Replay(1000, 0),
            ff.EffectType(ff_rumble_effect=rumble),
        )

        effect_id = dev.upload_effect(effect)
        print(f"[RUMBLE] Effect ID={effect_id}")
        return effect_id
    except Exception as exc:
        print(f"[RUMBLE] Error: {exc}")
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
        except Exception as exc:
            print(f"[CONTROL] No se pudo abrir {FORCED_EVENT_PATH}: {exc}")
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
def compute_drive(lx, l2, r2):
    v = int((r2 - l2) * V_MAX)
    w = int(lx * W_MAX)
    return clamp(v, -1000, 1000), clamp(w, -1000, 1000)


def compute_flipper(ry):
    if INVERT_RY:
        ry = -ry
    return clamp(int(ry * F_MAX), -1000, 1000)


def compute_base(rx):
    return clamp(int(rx * BASE_MAX), -1000, 1000)


def compute_elbow(ly):
    if INVERT_LY:
        ly = -ly
    return clamp(int(ly * ELBOW_MAX), -1000, 1000)


def compute_wrist(hat_y):
    # En muchos controles: arriba = -1, abajo = +1
    if INVERT_HAT_Y:
        hat_y = -hat_y
    return clamp(int(hat_y * WRIST_MAX), -1000, 1000)


def compute_grip(open_pressed, close_pressed):
    if open_pressed and not close_pressed:
        return -GRIP_MAX
    if close_pressed and not open_pressed:
        return GRIP_MAX
    return 0


def describe(state: CommandState):
    if abs(state.v) < 50 and abs(state.w) < 50 and abs(state.f) < 50:
        return "QUIETO"

    if abs(state.v) < 50:
        return "GIRO DERECHA" if state.w > 0 else "GIRO IZQUIERDA"

    if state.v > 0:
        if state.w > 50:
            return "ADELANTE + DERECHA"
        if state.w < -50:
            return "ADELANTE + IZQUIERDA"
        return "ADELANTE"

    if state.v < 0:
        if state.w > 50:
            return "ATRAS + DERECHA"
        if state.w < -50:
            return "ATRAS + IZQUIERDA"
        return "ATRAS"

    return "MOV"


# =========================================================
# MAIN
# =========================================================
def main():
    global running

    client = connect_mqtt_forever()

    while running:
        dev = wait_for_controller()
        if dev is None:
            break

        estado_abs = {
            ABS_X: AXIS_CENTER,
            ABS_Y: AXIS_CENTER,
            ABS_RX: AXIS_CENTER,
            ABS_RY: AXIS_CENTER,
            ABS_Z: 0,
            ABS_RZ: 0,
            ABS_HAT0Y: 0,
        }

        estado_btn = {
            BTN_OPTIONS: 0,
            BTN_GRIP_OPEN: 0,
            BTN_GRIP_CLOSE: 0,
        }

        last_send = 0.0
        last_print = 0.0

        total_loops = 0
        total_events = 0
        total_mqtt_sent = 0

        options_pressed = False
        options_press_time = 0.0
        shutdown_triggered = False

        rumble_effect_id = None
        rumble_on = False

        try:
            try:
                dev.grab()
            except PermissionError:
                print("[CONTROL] No se pudo hacer grab(); prueba con sudo o permisos del grupo input")

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
                    except Exception as exc:
                        print(f"[ERROR] Leyendo eventos: {exc}")
                        break

                    if event is None:
                        break

                    got_events_this_loop += 1
                    total_events += 1

                    if event.type == ecodes.EV_ABS:
                        estado_abs[event.code] = event.value

                    elif event.type == ecodes.EV_KEY:
                        estado_btn[event.code] = event.value

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

                lx = deadzone(normalize_axis(estado_abs.get(ABS_X, AXIS_CENTER)), DEADZONE_STICK)
                ly = deadzone(normalize_axis(estado_abs.get(ABS_Y, AXIS_CENTER)), DEADZONE_STICK)
                rx = deadzone(normalize_axis(estado_abs.get(ABS_RX, AXIS_CENTER)), DEADZONE_STICK)
                ry = deadzone(normalize_axis(estado_abs.get(ABS_RY, AXIS_CENTER)), DEADZONE_STICK)

                l2 = normalize_trigger(estado_abs.get(ABS_Z, 0))
                r2 = normalize_trigger(estado_abs.get(ABS_RZ, 0))
                l2 = 0.0 if l2 < DEADZONE_TRIGGER else l2
                r2 = 0.0 if r2 < DEADZONE_TRIGGER else r2

                hat_y = int(estado_abs.get(ABS_HAT0Y, 0))
                grip_open = estado_btn.get(BTN_GRIP_OPEN, 0) == 1
                grip_close = estado_btn.get(BTN_GRIP_CLOSE, 0) == 1

                cmd = CommandState(
                    v=compute_drive(lx, l2, r2)[0],
                    w=compute_drive(lx, l2, r2)[1],
                    f=compute_flipper(ry),
                    base=compute_base(rx),
                    elbow=compute_elbow(ly),
                    wrist=compute_wrist(hat_y),
                    grip=compute_grip(grip_open, grip_close),
                )

                mov = describe(cmd)

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
                        publish_zero(client, times=5, delay_s=0.03)
                        os.system("sudo shutdown now")
                else:
                    if rumble_on:
                        stop_rumble(dev, rumble_effect_id)
                        rumble_on = False

                if now - last_send >= SEND_INTERVAL:
                    last_send = now
                    try:
                        publish_command(client, cmd)
                        total_mqtt_sent += 1
                    except Exception as exc:
                        print(f"[MQTT] Error publicando comando: {exc}")

                if now - last_print >= PRINT_INTERVAL:
                    last_print = now
                    print(
                        f"[STAT] "
                        f"v={cmd.v:4d} w={cmd.w:4d} f={cmd.f:4d} "
                        f"base={cmd.base:4d} elbow={cmd.elbow:4d} "
                        f"wrist={cmd.wrist:4d} grip={cmd.grip:4d} "
                        f"LX={lx:+.2f} LY={ly:+.2f} RX={rx:+.2f} RY={ry:+.2f} "
                        f"L2={l2:.2f} R2={r2:.2f} HATY={hat_y:+d} "
                        f"{mov} loops={total_loops} events={total_events} "
                        f"mqtt={total_mqtt_sent} got={got_events_this_loop}"
                    )

                time.sleep(0.001)

        except KeyboardInterrupt:
            print("\n[EXIT] Ctrl+C detectado, cerrando limpio...")
            running = False
            publish_zero(client)

        except OSError as exc:
            print(f"[CONTROL] OSError real, posible desconexion: {exc}")
            publish_zero(client)
            time.sleep(RETRY_DELAY)

        except Exception as exc:
            print(f"[ERROR] {exc}")
            publish_zero(client)
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
        publish_zero(client)
    except Exception:
        pass

    try:
        client.loop_stop()
        client.disconnect()
    except Exception:
        pass

    print("[EXIT] Programa terminado.")


if __name__ == "__main__":
    main()