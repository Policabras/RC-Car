from __future__ import annotations

import os
import socket
from dataclasses import dataclass


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


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
class AppConfig:
    edge_id: str
    mqtt: MqttConfig
    storage: StorageConfig
    udp: UdpConfig
    publish: PublishConfig
    system: SystemConfig
    debug: bool


def load_config() -> AppConfig:
    hostname = socket.gethostname()
    edge_id = os.getenv("EDGE_ID", f"pi_{hostname}")
    client_id = os.getenv("MQTT_CLIENT_ID", f"{edge_id}_collector")

    mqtt = MqttConfig(
        host=os.getenv("MQTT_HOST", "192.168.0.106"),
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

    return AppConfig(
        edge_id=edge_id,
        mqtt=mqtt,
        storage=storage,
        udp=udp,
        publish=publish,
        system=system,
        debug=_get_bool("DEBUG", False),
    )
