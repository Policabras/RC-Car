#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import faulthandler
import json
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import resource  # Unix/macOS/Linux
except ImportError:
    resource = None

try:
    import psutil  # Windows / fallback multiplataforma
except ImportError:
    psutil = None

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
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "gamepad_mqtt_publisher")
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

# Axis mapping
AXIS_LEFT_X = int(os.getenv("AXIS_LEFT_X", "0"))
AXIS_LEFT_Y = int(os.getenv("AXIS_LEFT_Y", "1"))   # Reservado / no usado en la lógica actual
AXIS_RIGHT_X = int(os.getenv("AXIS_RIGHT_X", "2"))
AXIS_RIGHT_Y = int(os.getenv("AXIS_RIGHT_Y", "3"))
AXIS_L2 = int(os.getenv("AXIS_L2", "4"))
AXIS_R2 = int(os.getenv("AXIS_R2", "5"))

# Button mapping
BTN_OPTIONS = int(os.getenv("BTN_OPTIONS", "9"))
BTN_DRIVE_MODE_TOGGLE = int(os.getenv("BTN_DRIVE_MODE_TOGGLE", "8"))

# Mapeo típico estilo Xbox:
# A=0, B=1, X=2, Y=3
BTN_WRIST_UP = int(os.getenv("BTN_WRIST_UP", os.getenv("BTN_Y", "2")))      # Y
BTN_WRIST_DOWN = int(os.getenv("BTN_WRIST_DOWN", os.getenv("BTN_A", "1")))  # A
BTN_GRIP_OPEN = int(os.getenv("BTN_GRIP_OPEN", os.getenv("BTN_X", "3")))    # X
BTN_GRIP_CLOSE = int(os.getenv("BTN_GRIP_CLOSE", os.getenv("BTN_B", "0")))  # B

# Logging
LOG_DIR = Path(os.getenv("LOG_DIR", str(BASE_DIR / "logs"))).expanduser()
LOG_FILE = os.getenv("LOG_FILE", "controller_monitor.log")
FAULT_LOG_FILE = os.getenv("FAULT_LOG_FILE", "controller_faults.log")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", "5242880"))  # 5 MB
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))
HEARTBEAT_INTERVAL = float(os.getenv("HEARTBEAT_INTERVAL", "10.0"))

running = True
logger = logging.getLogger("gamepad_monitor")
FAULT_LOG_STREAM = None
LAST_RUNTIME_SNAPSHOT: dict[str, object] = {
    "last_cmd": None,
    "last_publish_ts": None,
    "last_event_ts": None,
    "last_loop_ts": None,
    "controller_name": None,
    "controller_instance_id": None,
    "total_loops": 0,
    "total_events": 0,
    "total_mqtt_sent": 0,
}


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
# LOGGING
# =========================================================
def get_log_level() -> int:
    return getattr(logging, LOG_LEVEL, logging.INFO)


def get_memory_mb() -> float:
    """
    Devuelve memoria RSS del proceso en MB.
    - Windows: usa psutil si está disponible
    - macOS/Linux: usa resource
    """
    if sys.platform.startswith("win"):
        if psutil is None:
            return -1.0
        try:
            process = psutil.Process(os.getpid())
            return round(process.memory_info().rss / (1024 * 1024), 2)
        except Exception:
            return -1.0

    if resource is None:
        return -1.0

    try:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return round(usage / (1024 * 1024), 2)  # bytes -> MB
        return round(usage / 1024, 2)  # KB -> MB en Linux
    except Exception:
        return -1.0


def setup_logging() -> None:
    global FAULT_LOG_STREAM

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(threadName)s | %(name)s | %(message)s"
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(get_log_level())

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(get_log_level())
    console_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(get_log_level())
    file_handler.setFormatter(formatter)

    root.addHandler(console_handler)
    root.addHandler(file_handler)
    logging.captureWarnings(True)

    FAULT_LOG_STREAM = open(LOG_DIR / FAULT_LOG_FILE, "a", encoding="utf-8", buffering=1)
    faulthandler.enable(file=FAULT_LOG_STREAM, all_threads=True)

    try:
        if hasattr(signal, "SIGUSR1"):
            faulthandler.register(signal.SIGUSR1, file=FAULT_LOG_STREAM, all_threads=True)
    except Exception:
        logger.exception("No se pudo registrar SIGUSR1 para faulthandler")

    logger.info("Logging inicializado")
    logger.info("Logs normales: %s", LOG_DIR / LOG_FILE)
    logger.info("Logs de fallos fatales: %s", LOG_DIR / FAULT_LOG_FILE)


def install_exception_hooks() -> None:
    def handle_unhandled_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            logger.info("KeyboardInterrupt capturado por excepthook")
            return
        logger.critical(
            "Excepción no controlada",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    def handle_thread_exception(args: threading.ExceptHookArgs):
        logger.critical(
            "Excepción no controlada en hilo '%s'",
            args.thread.name if args.thread else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = handle_unhandled_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = handle_thread_exception


def shutdown_logging() -> None:
    global FAULT_LOG_STREAM
    try:
        if FAULT_LOG_STREAM:
            FAULT_LOG_STREAM.flush()
            FAULT_LOG_STREAM.close()
    except Exception:
        pass
    finally:
        FAULT_LOG_STREAM = None


def snapshot_dict(
    *,
    reason: str,
    joystick: pygame.joystick.Joystick | None = None,
    cmd: CommandState | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "reason": reason,
        "ts": time.time(),
        "running": running,
        "mqtt_host": MQTT_HOST,
        "mqtt_port": MQTT_PORT,
        "mqtt_topic": MQTT_COMMAND_TOPIC,
        "memory_mb": get_memory_mb(),
        "runtime": dict(LAST_RUNTIME_SNAPSHOT),
    }

    if joystick is not None:
        try:
            snapshot["joystick"] = {
                "name": joystick.get_name(),
                "instance_id": joystick.get_instance_id(),
                "axes": joystick.get_numaxes(),
                "buttons": joystick.get_numbuttons(),
                "hats": joystick.get_numhats(),
            }
        except Exception as exc:
            snapshot["joystick_error"] = str(exc)

    if cmd is not None:
        snapshot["cmd"] = cmd.as_payload()

    if extra:
        snapshot["extra"] = extra

    return snapshot


def log_snapshot(
    *,
    level: int,
    reason: str,
    joystick: pygame.joystick.Joystick | None = None,
    cmd: CommandState | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    payload = snapshot_dict(reason=reason, joystick=joystick, cmd=cmd, extra=extra)
    logger.log(level, "SNAPSHOT %s", json.dumps(payload, ensure_ascii=False, default=str))


# =========================================================
# EXIT
# =========================================================
def handle_exit(sig, frame):
    global running
    logger.warning("Señal recibida: sig=%s, cerrando limpio...", sig)
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
    client.enable_logger(logging.getLogger("mqtt.client"))

    def on_connect(client, userdata, flags, reason_code, properties):
        logger.info(
            "[MQTT] Conectado rc=%s host=%s:%s client_id=%s",
            reason_code,
            MQTT_HOST,
            MQTT_PORT,
            MQTT_CLIENT_ID,
        )

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
        logger.warning("[MQTT] Desconectado rc=%s", reason_code)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    return client


def connect_mqtt_forever() -> mqtt.Client:
    while running:
        try:
            logger.info("[MQTT] Intentando conectar a %s:%s ...", MQTT_HOST, MQTT_PORT)
            client = build_mqtt_client()
            client.connect(MQTT_HOST, MQTT_PORT, 30)
            client.loop_start()
            logger.info("[MQTT] loop_start() activado")
            return client
        except Exception:
            logger.exception("[MQTT] Error conectando. Reintentando en %.2f s", RETRY_DELAY)
            time.sleep(RETRY_DELAY)

    raise RuntimeError("Stopped before MQTT connection was established")


def publish_command(client: mqtt.Client, state: CommandState) -> None:
    payload = json.dumps(state.as_payload(), separators=(",", ":"))
    info = client.publish(MQTT_COMMAND_TOPIC, payload, qos=MQTT_QOS, retain=False)
    LAST_RUNTIME_SNAPSHOT["last_cmd"] = state.as_payload()
    LAST_RUNTIME_SNAPSHOT["last_publish_ts"] = time.time()

    if MQTT_QOS > 0:
        info.wait_for_publish(timeout=1.0)

    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"publish rc={info.rc}")


def publish_zero(client: mqtt.Client, *, times: int = 3, delay_s: float = 0.03) -> None:
    zero = CommandState()
    for idx in range(times):
        try:
            publish_command(client, zero)
            logger.info("[MQTT] Comando cero enviado (%s/%s)", idx + 1, times)
        except Exception:
            logger.exception("[MQTT] Error publicando cero (%s/%s)", idx + 1, times)
        time.sleep(delay_s)


# =========================================================
# RUMBLE
# =========================================================
def start_rumble(joystick: pygame.joystick.Joystick) -> bool:
    if not ENABLE_RUMBLE:
        return False

    if not hasattr(joystick, "rumble"):
        logger.warning("[RUMBLE] El joystick no soporta rumble")
        return False

    try:
        result = bool(joystick.rumble(0.75, 0.50, 1000))
        logger.info("[RUMBLE] start result=%s", result)
        return result
    except Exception:
        logger.exception("[RUMBLE] Error al iniciar rumble")
        return False


def stop_rumble(joystick: pygame.joystick.Joystick) -> None:
    if not ENABLE_RUMBLE:
        return

    if not hasattr(joystick, "stop_rumble"):
        try:
            if hasattr(joystick, "rumble"):
                joystick.rumble(0.0, 0.0, 1)
            logger.info("[RUMBLE] stop por fallback")
        except Exception:
            logger.exception("[RUMBLE] Error en fallback stop_rumble")
        return

    try:
        joystick.stop_rumble()
        logger.info("[RUMBLE] stop ok")
    except Exception:
        logger.exception("[RUMBLE] Error al detener rumble")


# =========================================================
# GAMEPAD
# =========================================================
def init_pygame() -> None:
    pygame.init()
    pygame.joystick.init()
    logger.info(
        "[PYGAME] init ok version=%s sdl=%s",
        pygame.version.ver,
        ".".join(str(part) for part in pygame.get_sdl_version()),
    )


def shutdown_pygame() -> None:
    try:
        pygame.joystick.quit()
        logger.info("[PYGAME] joystick.quit ok")
    except Exception:
        logger.exception("[PYGAME] Error en joystick.quit")

    try:
        pygame.quit()
        logger.info("[PYGAME] pygame.quit ok")
    except Exception:
        logger.exception("[PYGAME] Error en pygame.quit")


def list_joysticks() -> list[pygame.joystick.Joystick]:
    pygame.joystick.quit()
    pygame.joystick.init()

    devices: list[pygame.joystick.Joystick] = []
    count = pygame.joystick.get_count()
    logger.debug("[CONTROL] Joysticks detectados=%s", count)

    for idx in range(count):
        js = pygame.joystick.Joystick(idx)
        js.init()
        devices.append(js)

    return devices


def wait_for_controller() -> pygame.joystick.Joystick | None:
    logger.info("[CONTROL] Buscando control...")

    while running:
        pygame.event.pump()
        devices = list_joysticks()
        if devices:
            js = devices[0]
            LAST_RUNTIME_SNAPSHOT["controller_name"] = js.get_name()
            LAST_RUNTIME_SNAPSHOT["controller_instance_id"] = js.get_instance_id()

            logger.info(
                "[CONTROL] Conectado: index=%s name=%s axes=%s buttons=%s hats=%s",
                js.get_instance_id(),
                js.get_name(),
                js.get_numaxes(),
                js.get_numbuttons(),
                js.get_numhats(),
            )
            return js

        time.sleep(RETRY_DELAY)

    return None


# =========================================================
# LOGICA DE MOVIMIENTO
# =========================================================
def compute_drive(
    lx: float,
    l2: float,
    r2: float,
    inverted_drive: bool = False,
) -> tuple[int, int]:
    """
    Modo normal:
      - R2 = adelante
      - L2 = reversa
      - LX = giro normal

    Modo invertido:
      - se invierte v
      - se invierte w
    """
    v = int((r2 - l2) * V_MAX)
    w = int(lx * W_MAX)

    if inverted_drive:
        v = -v
        w = -w

    return clamp(v, -1000, 1000), clamp(w, -1000, 1000)


def compute_flipper_from_hat(hat_y: int) -> int:
    if INVERT_HAT_Y:
        hat_y = -hat_y
    return clamp(int(hat_y * F_MAX), -1000, 1000)


def compute_base(rx: float) -> int:
    return clamp(int(-rx * BASE_MAX), -1000, 1000)


def compute_elbow(ry: float) -> int:
    if INVERT_RY:
        ry = -ry
    return clamp(int(ry * ELBOW_MAX), -1000, 1000)


def compute_wrist(up_pressed: bool, down_pressed: bool) -> int:
    if up_pressed and not down_pressed:
        return WRIST_MAX
    if down_pressed and not up_pressed:
        return -WRIST_MAX
    return 0


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
        logger.warning("[SYSTEM] ENABLE_LOCAL_SHUTDOWN=false, apagado omitido")
        return

    logger.warning("[SYSTEM] APAGANDO MAC...")
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "System Events" to shut down',
            ],
            check=False,
        )
    except Exception:
        logger.exception("[SYSTEM] Error intentando apagar")


# =========================================================
# MAIN
# =========================================================
def main() -> None:
    global running

    setup_logging()
    install_exception_hooks()

    if LOADED_ENV_PATH:
        logger.info("[ENV] Archivo cargado: %s", LOADED_ENV_PATH)
    else:
        logger.info("[ENV] No se encontró .env; usando variables del sistema o defaults")

    logger.info(
        "[ENV] MQTT host=%s port=%s topic=%s qos=%s",
        MQTT_HOST,
        MQTT_PORT,
        MQTT_COMMAND_TOPIC,
        MQTT_QOS,
    )
    logger.info(
        "[ENV] RUMBLE=%s SHUTDOWN_LOCAL=%s SEND_INTERVAL=%.3f PRINT_INTERVAL=%.3f",
        ENABLE_RUMBLE,
        ENABLE_LOCAL_SHUTDOWN,
        SEND_INTERVAL,
        PRINT_INTERVAL,
    )
    logger.info(
        "[MAP] NORMAL: R2->adelante | L2->reversa | LX->w | "
        "BTN_DRIVE_MODE_TOGGLE invierte v y w | "
        "HAT_Y->f | RX->base | RY->elbow | Y/A->wrist | X/B->grip"
    )

    log_snapshot(level=logging.INFO, reason="program_start")

    init_pygame()
    client = connect_mqtt_forever()

    while running:
        joystick = wait_for_controller()
        if joystick is None:
            break

        last_send = 0.0
        last_print = 0.0
        last_heartbeat = 0.0

        total_loops = 0
        total_events = 0
        total_mqtt_sent = 0

        options_pressed = False
        options_press_time = 0.0
        shutdown_triggered = False
        rumble_on = False
        drive_mode_inverted = False
        cmd = CommandState()

        try:
            while running:
                now = time.time()
                total_loops += 1
                got_events_this_loop = 0

                LAST_RUNTIME_SNAPSHOT["last_loop_ts"] = now
                LAST_RUNTIME_SNAPSHOT["total_loops"] = total_loops
                LAST_RUNTIME_SNAPSHOT["total_events"] = total_events
                LAST_RUNTIME_SNAPSHOT["total_mqtt_sent"] = total_mqtt_sent

                events = pygame.event.get()
                for event in events:
                    got_events_this_loop += 1
                    total_events += 1
                    LAST_RUNTIME_SNAPSHOT["last_event_ts"] = now

                    if event.type == pygame.JOYDEVICEREMOVED:
                        logger.warning(
                            "[CONTROL] JOYDEVICEREMOVED instance_id=%s current=%s",
                            getattr(event, "instance_id", None),
                            joystick.get_instance_id(),
                        )
                        if event.instance_id == joystick.get_instance_id():
                            raise OSError("Control desconectado")

                    elif event.type == pygame.JOYBUTTONDOWN:
                        logger.debug("[CONTROL] BUTTON DOWN %s", getattr(event, "button", None))

                        if event.button == BTN_OPTIONS:
                            options_pressed = True
                            options_press_time = now
                            shutdown_triggered = False
                            logger.info("[SYSTEM] Botón OPTIONS presionado")

                        elif event.button == BTN_DRIVE_MODE_TOGGLE:
                            drive_mode_inverted = not drive_mode_inverted
                            logger.info(
                                "[DRIVE] Modo de manejo cambiado a: %s",
                                "INVERTIDO (v y w invertidos)" if drive_mode_inverted else "NORMAL",
                            )

                    elif event.type == pygame.JOYBUTTONUP:
                        logger.debug("[CONTROL] BUTTON UP %s", getattr(event, "button", None))
                        if event.button == BTN_OPTIONS:
                            options_pressed = False
                            shutdown_triggered = False
                            logger.info("[SYSTEM] Botón OPTIONS liberado")
                            if rumble_on:
                                stop_rumble(joystick)
                                rumble_on = False

                # Lectura de sticks/gatillos
                lx = deadzone(normalize_stick(safe_get_axis(joystick, AXIS_LEFT_X)), DEADZONE_STICK)
                ly = deadzone(normalize_stick(safe_get_axis(joystick, AXIS_LEFT_Y)), DEADZONE_STICK)  # Solo debug
                rx = deadzone(normalize_stick(safe_get_axis(joystick, AXIS_RIGHT_X)), DEADZONE_STICK)
                ry = deadzone(normalize_stick(safe_get_axis(joystick, AXIS_RIGHT_Y)), DEADZONE_STICK)

                l2 = normalize_trigger(safe_get_axis(joystick, AXIS_L2))
                r2 = normalize_trigger(safe_get_axis(joystick, AXIS_R2))
                l2 = 0.0 if l2 < DEADZONE_TRIGGER else l2
                r2 = 0.0 if r2 < DEADZONE_TRIGGER else r2

                # Cruceta vertical -> flippers
                hat_y = safe_get_hat_y(joystick)

                # Botones
                wrist_up = safe_get_button(joystick, BTN_WRIST_UP) == 1     # Y
                wrist_down = safe_get_button(joystick, BTN_WRIST_DOWN) == 1 # A
                grip_open = safe_get_button(joystick, BTN_GRIP_OPEN) == 1   # X
                grip_close = safe_get_button(joystick, BTN_GRIP_CLOSE) == 1 # B

                drive_v, drive_w = compute_drive(lx, l2, r2, drive_mode_inverted)

                cmd = CommandState(
                    v=drive_v,
                    w=drive_w,
                    f=compute_flipper_from_hat(hat_y),
                    base=compute_base(rx),
                    elbow=compute_elbow(ry),
                    wrist=compute_wrist(wrist_up, wrist_down),
                    grip=compute_grip(grip_open, grip_close),
                )

                mov = describe(cmd)

                if options_pressed:
                    held = now - options_press_time

                    if not rumble_on:
                        rumble_on = start_rumble(joystick)

                    if held >= SHUTDOWN_HOLD and not shutdown_triggered:
                        shutdown_triggered = True
                        logger.warning("[SYSTEM] Evento de apagado activado")
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
                        LAST_RUNTIME_SNAPSHOT["total_mqtt_sent"] = total_mqtt_sent
                    except Exception:
                        logger.exception("[MQTT] Error publicando comando")
                        log_snapshot(
                            level=logging.ERROR,
                            reason="mqtt_publish_error",
                            joystick=joystick,
                            cmd=cmd,
                        )

                if now - last_print >= PRINT_INTERVAL:
                    last_print = now
                    logger.info(
                        "[STAT] mode=%s v=%4d w=%4d f=%4d base=%4d elbow=%4d wrist=%4d grip=%4d "
                        "LX=%+.2f LY=%+.2f RX=%+.2f RY=%+.2f L2=%.2f R2=%.2f HATY=%+d "
                        "Y=%d A=%d X=%d B=%d "
                        "%s loops=%s events=%s mqtt=%s got=%s mem=%.2fMB",
                        "INV" if drive_mode_inverted else "NOR",
                        cmd.v,
                        cmd.w,
                        cmd.f,
                        cmd.base,
                        cmd.elbow,
                        cmd.wrist,
                        cmd.grip,
                        lx,
                        ly,
                        rx,
                        ry,
                        l2,
                        r2,
                        hat_y,
                        int(wrist_up),
                        int(wrist_down),
                        int(grip_open),
                        int(grip_close),
                        mov,
                        total_loops,
                        total_events,
                        total_mqtt_sent,
                        got_events_this_loop,
                        get_memory_mb(),
                    )

                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    last_heartbeat = now
                    log_snapshot(
                        level=logging.INFO,
                        reason="heartbeat",
                        joystick=joystick,
                        cmd=cmd,
                        extra={
                            "options_pressed": options_pressed,
                            "shutdown_triggered": shutdown_triggered,
                            "rumble_on": rumble_on,
                            "got_events_this_loop": got_events_this_loop,
                            "wrist_up": wrist_up,
                            "wrist_down": wrist_down,
                            "grip_open": grip_open,
                            "grip_close": grip_close,
                            "hat_y": hat_y,
                            "drive_mode_inverted": drive_mode_inverted,
                        },
                    )

                time.sleep(0.001)

        except KeyboardInterrupt:
            logger.warning("[EXIT] Ctrl+C detectado, cerrando limpio...")
            running = False
            publish_zero(client)

        except OSError as exc:
            logger.warning("[CONTROL] Posible desconexión: %s", exc)
            log_snapshot(
                level=logging.WARNING,
                reason="controller_disconnect",
                joystick=joystick,
                cmd=cmd,
                extra={"error": str(exc)},
            )
            publish_zero(client)
            time.sleep(RETRY_DELAY)

        except Exception:
            logger.exception("[ERROR] Excepción dentro del loop principal")
            log_snapshot(
                level=logging.ERROR,
                reason="main_loop_exception",
                joystick=joystick,
                cmd=cmd,
            )
            publish_zero(client)
            time.sleep(RETRY_DELAY)

        finally:
            try:
                stop_rumble(joystick)
            except Exception:
                logger.exception("[RUMBLE] Error en cleanup stop_rumble")

            try:
                joystick.quit()
                logger.info("[CONTROL] joystick.quit ok")
            except Exception:
                logger.exception("[CONTROL] Error en joystick.quit")

    try:
        publish_zero(client)
    except Exception:
        logger.exception("[MQTT] Error enviando cero final")

    try:
        client.loop_stop()
        client.disconnect()
        logger.info("[MQTT] loop_stop + disconnect ok")
    except Exception:
        logger.exception("[MQTT] Error cerrando cliente")

    shutdown_pygame()
    log_snapshot(level=logging.INFO, reason="program_end")
    logger.info("[EXIT] Programa terminado.")
    shutdown_logging()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            logger.critical("[FATAL] Error fatal al arrancar", exc_info=True)
        except Exception:
            print(f"[FATAL] {exc}", file=sys.stderr)
        shutdown_pygame()
        shutdown_logging()
        sys.exit(1)