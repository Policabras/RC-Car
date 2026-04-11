#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import paho.mqtt.client as mqtt
import pygame
from dotenv import load_dotenv

# =========================================================
# LOAD .env
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
ENV_PATHS = [
    BASE_DIR / ".env",
    BASE_DIR.parent / ".env",
    BASE_DIR.parent.parent / ".env",
    Path.cwd() / ".env",
]

LOADED_ENV_PATH: str | None = None
for env_path in ENV_PATHS:
    if env_path.exists():
        load_dotenv(env_path, override=False)
        LOADED_ENV_PATH = str(env_path)
        break

# =========================================================
# CONFIG
# =========================================================
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "gamepad_mqtt_publisher_mac")
MQTT_COMMAND_TOPIC = os.getenv("MQTT_COMMAND_TOPIC", "telemetry/pi_robot_01/cmd")
MQTT_QOS = int(os.getenv("MQTT_QOS", "0"))

RETRY_DELAY = float(os.getenv("RETRY_DELAY", "2.0"))
SEND_INTERVAL = float(os.getenv("SEND_INTERVAL", "0.02"))   # 50 Hz
PRINT_INTERVAL = float(os.getenv("PRINT_INTERVAL", "0.50"))

DEADZONE_STICK = float(os.getenv("DEADZONE_STICK", "0.08"))
DEADZONE_TRIGGER = float(os.getenv("DEADZONE_TRIGGER", "0.03"))

V_MAX = int(os.getenv("V_MAX", "1000"))
W_MAX = int(os.getenv("W_MAX", "1000"))
F_MAX = int(os.getenv("F_MAX", "1000"))
BASE_MAX = int(os.getenv("BASE_MAX", "1000"))
ELBOW_MAX = int(os.getenv("ELBOW_MAX", "1000"))
WRIST_MAX = int(os.getenv("WRIST_MAX", "1000"))
GRIP_MAX = int(os.getenv("GRIP_MAX", "1000"))

INVERT_LY = os.getenv("INVERT_LY", "true").strip().lower() in {"1", "true", "yes", "on"}
INVERT_RY = os.getenv("INVERT_RY", "true").strip().lower() in {"1", "true", "yes", "on"}
INVERT_HAT_Y = os.getenv("INVERT_HAT_Y", "true").strip().lower() in {"1", "true", "yes", "on"}

ENABLE_RUMBLE = os.getenv("ENABLE_RUMBLE", "true").strip().lower() in {"1", "true", "yes", "on"}
ENABLE_LOCAL_SHUTDOWN = os.getenv("ENABLE_LOCAL_SHUTDOWN", "false").strip().lower() in {"1", "true", "yes", "on"}
SHUTDOWN_HOLD = float(os.getenv("SHUTDOWN_HOLD", "5.0"))

# Axis mapping (defaults comunes, ajustables por env)
AXIS_LEFT_X = int(os.getenv("AXIS_LEFT_X", "0"))
AXIS_LEFT_Y = int(os.getenv("AXIS_LEFT_Y", "1"))
AXIS_RIGHT_X = int(os.getenv("AXIS_RIGHT_X", "2"))
AXIS_RIGHT_Y = int(os.getenv("AXIS_RIGHT_Y", "3"))
AXIS_L2 = int(os.getenv("AXIS_L2", "4"))
AXIS_R2 = int(os.getenv("AXIS_R2", "5"))

# Button mapping (ajustable por env)
BTN_OPTIONS = int(os.getenv("BTN_OPTIONS", "9"))
BTN_GRIP_OPEN = int(os.getenv("BTN_GRIP_OPEN", "2"))
BTN_GRIP_CLOSE = int(os.getenv("BTN_GRIP_CLOSE", "1"))

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


def deadzone(value: float, threshold: float) -> float:
    return 0.0 if abs(value) < threshold else value


def normalize_stick(value: float) -> float:
    return clamp(value, -1.0, 1.0)


def normalize_trigger(value: float) -> float:
    """
    Convierte gatillos reportados como:
    - [-1, 1] -> [0, 1]
    - [0, 1]  -> [0, 1]
    """
    if value < 0.0:
        return clamp((value + 1.0) / 2.0, 0.0, 1.0)
    return clamp(value, 0.0, 1.0)


def safe_get_axis(joystick: pygame.joystick.Joystick, axis_index: int) -> float:
    if axis_index < 0 or axis_index >= joystick.get_numaxes():
        return 0.0
    return joystick.get_axis(axis_index)


def safe_get_button(joystick: pygame.joystick.Joystick, button_index: int) -> int:
    if button_index < 0 or button_index >= joystick.get_numbuttons():
        return 0
    return joystick.get_button(button_index)


def safe_get_hat_y(joystick: pygame.joystick.Joystick) -> int:
    if joystick.get_numhats() <= 0:
        return 0
    _, hat_y = joystick.get_hat(0)
    return int(hat_y)


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
def start_rumble(joystick: pygame.joystick.Joystick) -> bool:
    if not ENABLE_RUMBLE:
        return False

    if not hasattr(joystick, "rumble"):
        return False

    try:
        return bool(joystick.rumble(0.75, 0.50, 1000))
    except Exception:
        return False


def stop_rumble(joystick: pygame.joystick.Joystick) -> None:
    if not ENABLE_RUMBLE:
        return

    if not hasattr(joystick, "stop_rumble"):
        try:
            if hasattr(joystick, "rumble"):
                joystick.rumble(0.0, 0.0, 1)
        except Exception:
            pass
        return

    try:
        joystick.stop_rumble()
    except Exception:
        pass


# =========================================================
# GAMEPAD
# =========================================================
def init_pygame() -> None:
    pygame.init()
    pygame.joystick.init()


def shutdown_pygame() -> None:
    try:
        pygame.joystick.quit()
    except Exception:
        pass
    try:
        pygame.quit()
    except Exception:
        pass


def list_joysticks() -> list[pygame.joystick.Joystick]:
    pygame.joystick.quit()
    pygame.joystick.init()

    devices: list[pygame.joystick.Joystick] = []
    count = pygame.joystick.get_count()

    for idx in range(count):
        js = pygame.joystick.Joystick(idx)
        js.init()
        devices.append(js)

    return devices


def wait_for_controller() -> pygame.joystick.Joystick | None:
    print("[CONTROL] Buscando control...")

    while running:
        pygame.event.pump()
        devices = list_joysticks()
        if devices:
            js = devices[0]
            print(f"[CONTROL] Conectado: index={js.get_instance_id()} name={js.get_name()}")
            print(
                "[CONTROL] axes=%s buttons=%s hats=%s"
                % (js.get_numaxes(), js.get_numbuttons(), js.get_numhats())
            )
            return js

        time.sleep(RETRY_DELAY)

    return None


# =========================================================
# LOGICA DE MOVIMIENTO
# =========================================================
def compute_drive(lx: float, l2: float, r2: float) -> tuple[int, int]:
    v = int((r2 - l2) * V_MAX)
    w = int(lx * W_MAX)
    return clamp(v, -1000, 1000), clamp(w, -1000, 1000)


def compute_flipper(ry: float) -> int:
    if INVERT_RY:
        ry = -ry
    return clamp(int(ry * F_MAX), -1000, 1000)


def compute_base(rx: float) -> int:
    return clamp(int(rx * BASE_MAX), -1000, 1000)


def compute_elbow(ly: float) -> int:
    if INVERT_LY:
        ly = -ly
    return clamp(int(ly * ELBOW_MAX), -1000, 1000)


def compute_wrist(hat_y: int) -> int:
    if INVERT_HAT_Y:
        hat_y = -hat_y
    return clamp(int(hat_y * WRIST_MAX), -1000, 1000)


def compute_grip(open_pressed: bool, close_pressed: bool) -> int:
    if open_pressed and not close_pressed:
        return -GRIP_MAX
    if close_pressed and not open_pressed:
        return GRIP_MAX
    return 0


def describe(state: CommandState) -> str:
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
# SHUTDOWN
# =========================================================
def maybe_shutdown_mac() -> None:
    if not ENABLE_LOCAL_SHUTDOWN:
        print("[SYSTEM] ENABLE_LOCAL_SHUTDOWN=false, apagado omitido")
        return

    print("[SYSTEM] APAGANDO MAC...")
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to shut down',
            ],
            check=False,
        )
    except Exception as exc:
        print(f"[SYSTEM] Error intentando apagar: {exc}")


# =========================================================
# MAIN
# =========================================================
def main() -> None:
    global running

    if LOADED_ENV_PATH:
        print(f"[ENV] Archivo cargado: {LOADED_ENV_PATH}")
    else:
        print("[ENV] No se encontró .env; usando variables del sistema o defaults")

    print(f"[ENV] MQTT_HOST={MQTT_HOST}")
    print(f"[ENV] MQTT_PORT={MQTT_PORT}")
    print(f"[ENV] MQTT_COMMAND_TOPIC={MQTT_COMMAND_TOPIC}")

    init_pygame()
    client = connect_mqtt_forever()

    while running:
        joystick = wait_for_controller()
        if joystick is None:
            break

        last_send = 0.0
        last_print = 0.0

        total_loops = 0
        total_events = 0
        total_mqtt_sent = 0

        options_pressed = False
        options_press_time = 0.0
        shutdown_triggered = False
        rumble_on = False

        try:
            while running:
                now = time.time()
                total_loops += 1
                got_events_this_loop = 0

                events = pygame.event.get()
                for event in events:
                    got_events_this_loop += 1
                    total_events += 1

                    if event.type == pygame.QUIT:
                        running = False

                    elif event.type == pygame.JOYDEVICEREMOVED:
                        if event.instance_id == joystick.get_instance_id():
                            raise OSError("Control desconectado")

                    elif event.type == pygame.JOYBUTTONDOWN:
                        if event.button == BTN_OPTIONS:
                            options_pressed = True
                            options_press_time = now
                            shutdown_triggered = False

                    elif event.type == pygame.JOYBUTTONUP:
                        if event.button == BTN_OPTIONS:
                            options_pressed = False
                            shutdown_triggered = False
                            if rumble_on:
                                stop_rumble(joystick)
                                rumble_on = False

                lx = deadzone(normalize_stick(safe_get_axis(joystick, AXIS_LEFT_X)), DEADZONE_STICK)
                ly = deadzone(normalize_stick(safe_get_axis(joystick, AXIS_LEFT_Y)), DEADZONE_STICK)
                rx = deadzone(normalize_stick(safe_get_axis(joystick, AXIS_RIGHT_X)), DEADZONE_STICK)
                ry = deadzone(normalize_stick(safe_get_axis(joystick, AXIS_RIGHT_Y)), DEADZONE_STICK)

                l2 = normalize_trigger(safe_get_axis(joystick, AXIS_L2))
                r2 = normalize_trigger(safe_get_axis(joystick, AXIS_R2))
                l2 = 0.0 if l2 < DEADZONE_TRIGGER else l2
                r2 = 0.0 if r2 < DEADZONE_TRIGGER else r2

                hat_y = safe_get_hat_y(joystick)
                grip_open = safe_get_button(joystick, BTN_GRIP_OPEN) == 1
                grip_close = safe_get_button(joystick, BTN_GRIP_CLOSE) == 1

                drive_v, drive_w = compute_drive(lx, l2, r2)

                cmd = CommandState(
                    v=drive_v,
                    w=drive_w,
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
                        rumble_on = start_rumble(joystick)

                    if held >= SHUTDOWN_HOLD and not shutdown_triggered:
                        shutdown_triggered = True
                        print("[SYSTEM] Evento de apagado activado")
                        stop_rumble(joystick)
                        rumble_on = False
                        publish_zero(client, times=5, delay_s=0.03)
                        maybe_shutdown_mac()
                else:
                    if rumble_on:
                        stop_rumble(joystick)
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
            print(f"[CONTROL] Posible desconexión: {exc}")
            publish_zero(client)
            time.sleep(RETRY_DELAY)

        except Exception as exc:
            print(f"[ERROR] {exc}")
            publish_zero(client)
            time.sleep(RETRY_DELAY)

        finally:
            try:
                stop_rumble(joystick)
            except Exception:
                pass

            try:
                joystick.quit()
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

    shutdown_pygame()
    print("[EXIT] Programa terminado.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[FATAL] {exc}")
        shutdown_pygame()
        sys.exit(1)