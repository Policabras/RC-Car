from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_env_file() -> str | None:
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
    ]

    for env_path in candidates:
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            return str(env_path)

    return None


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _get_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default or []
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    username: str | None
    password: str | None
    client_id: str
    keepalive: int
    base_topic: str


@dataclass(frozen=True)
class StorageConfig:
    sqlite_path: str


@dataclass(frozen=True)
class UdpConfig:
    enabled: bool
    bind_host: str
    bind_port: int


@dataclass(frozen=True)
class PublishConfig:
    batch_size: int
    poll_interval_ms: int


@dataclass(frozen=True)
class SystemConfig:
    sample_period_ms: int


@dataclass(frozen=True)
class SerialConfig:
    enabled: bool
    ports: list[str]
    baudrate: int
    timeout_ms: int
    reconnect_delay_ms: int


@dataclass(frozen=True)
class RobotControlConfig:
    enabled: bool
    port: str
    baudrate: int
    timeout_ms: int
    reconnect_delay_ms: int
    tx_period_ms: int
    command_timeout_ms: int
    command_topic: str


@dataclass(frozen=True)
class AppConfig:
    edge_id: str
    mqtt: MqttConfig
    storage: StorageConfig
    udp: UdpConfig
    publish: PublishConfig
    system: SystemConfig
    serial: SerialConfig
    robot_control: RobotControlConfig
    debug: bool
    env_file: str | None


def load_config() -> AppConfig:
    env_file = _load_env_file()

    hostname = socket.gethostname()
    edge_id = os.getenv("EDGE_ID", f"pi_{hostname}")
    client_id = os.getenv("MQTT_CLIENT_ID", f"{edge_id}_collector")

    mqtt = MqttConfig(
        host=os.getenv("MQTT_HOST", "192.168.1.106"),
        port=_get_int("MQTT_PORT", 1883),
        username=os.getenv("MQTT_USERNAME"),
        password=os.getenv("MQTT_PASSWORD"),
        client_id=client_id,
        keepalive=_get_int("MQTT_KEEPALIVE", 30),
        base_topic=os.getenv("MQTT_BASE_TOPIC", "telemetry"),
    )

    storage = StorageConfig(
        sqlite_path=os.getenv("SQLITE_PATH", "./telemetry.db"),
    )

    udp = UdpConfig(
        enabled=_get_bool("UDP_ENABLED", True),
        bind_host=os.getenv("UDP_BIND_HOST", "0.0.0.0"),
        bind_port=_get_int("UDP_BIND_PORT", 9100),
    )

    publish = PublishConfig(
        batch_size=_get_int("PUBLISH_BATCH_SIZE", 100),
        poll_interval_ms=_get_int("PUBLISH_POLL_INTERVAL_MS", 200),
    )

    system = SystemConfig(
        sample_period_ms=_get_int("SYSTEM_SAMPLE_PERIOD_MS", 1000),
    )

    serial_cfg = SerialConfig(
        enabled=_get_bool("SERIAL_ENABLED", True),
        ports=_get_list("SERIAL_PORTS", []),
        baudrate=_get_int("SERIAL_BAUDRATE", 115200),
        timeout_ms=_get_int("SERIAL_TIMEOUT_MS", 200),
        reconnect_delay_ms=_get_int("SERIAL_RECONNECT_DELAY_MS", 1500),
    )

    robot_command_topic = os.getenv(
        "ROBOT_COMMAND_TOPIC",
        f"{mqtt.base_topic}/{edge_id}/cmd",
    )

    robot_control = RobotControlConfig(
        enabled=_get_bool("ROBOT_CONTROL_ENABLED", False),
        port=os.getenv("ROBOT_SERIAL_PORT", "/dev/ttyUSB0"),
        baudrate=_get_int("ROBOT_SERIAL_BAUDRATE", 115200),
        timeout_ms=_get_int("ROBOT_SERIAL_TIMEOUT_MS", 50),
        reconnect_delay_ms=_get_int("ROBOT_SERIAL_RECONNECT_DELAY_MS", 1500),
        tx_period_ms=_get_int("ROBOT_TX_PERIOD_MS", 50),
        command_timeout_ms=_get_int("ROBOT_COMMAND_TIMEOUT_MS", 300),
        command_topic=robot_command_topic,
    )

    return AppConfig(
        edge_id=edge_id,
        mqtt=mqtt,
        storage=storage,
        udp=udp,
        publish=publish,
        system=system,
        serial=serial_cfg,
        robot_control=robot_control,
        debug=_get_bool("DEBUG", False),
        env_file=env_file,
    )