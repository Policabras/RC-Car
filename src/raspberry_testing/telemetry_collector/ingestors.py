from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Callable

import psutil

from models import TelemetryEnvelope, build_envelope, now_ms

LOGGER = logging.getLogger(__name__)
EmitFn = Callable[[TelemetryEnvelope], None]


class StoppableThread(threading.Thread):
    def __init__(self, *, name: str) -> None:
        super().__init__(name=name, daemon=True)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def stopped(self) -> bool:
        return self._stop_event.is_set()


class SystemIngestor(StoppableThread):
    def __init__(
        self,
        *,
        emit_fn: EmitFn,
        base_topic: str,
        edge_id: str,
        sample_period_ms: int = 1000,
    ) -> None:
        super().__init__(name="system_ingestor")
        self.emit_fn = emit_fn
        self.base_topic = base_topic
        self.edge_id = edge_id
        self.sample_period_ms = sample_period_ms

    def _read_temperature_c(self) -> float | None:
        try:
            temps = psutil.sensors_temperatures()
        except Exception:
            LOGGER.exception("Failed to read system temperatures")
            return None

        if not temps:
            return None

        for _, entries in temps.items():
            if entries:
                first = entries[0]
                current = getattr(first, "current", None)
                if current is not None:
                    return float(current)

        return None

    def run(self) -> None:
        LOGGER.info("SystemIngestor started with %sms period", self.sample_period_ms)

        # Warm-up required for meaningful non-blocking cpu_percent() values.
        psutil.cpu_percent(interval=None)

        prev_net = psutil.net_io_counters()
        prev_mono = time.monotonic()

        while not self.stopped():
            if self._stop_event.wait(self.sample_period_ms / 1000.0):
                break

            now_mono = time.monotonic()
            elapsed = max(now_mono - prev_mono, 0.001)

            net = psutil.net_io_counters()
            vm = psutil.virtual_memory()
            du = psutil.disk_usage("/")

            rx_Bps = (net.bytes_recv - prev_net.bytes_recv) / elapsed
            tx_Bps = (net.bytes_sent - prev_net.bytes_sent) / elapsed

            payload = {
                "cpu_percent_total": psutil.cpu_percent(interval=None),
                "cpu_percent_per_core": psutil.cpu_percent(interval=None, percpu=True),
                "mem_percent": vm.percent,
                "mem_available_bytes": vm.available,
                "disk_percent_root": du.percent,
                "temperature_c": self._read_temperature_c(),
                "net_rx_Bps": rx_Bps,
                "net_tx_Bps": tx_Bps,
                "boot_time_s": int(psutil.boot_time()),
                "loadavg": list(getattr(psutil, "getloadavg", lambda: (0.0, 0.0, 0.0))()),
            }

            envelope = build_envelope(
                base_topic=self.base_topic,
                device_id=self.edge_id,
                stream="system",
                payload=payload,
                sample_period_ms=self.sample_period_ms,
                qos=1,
                retain=False,
            )
            self.emit_fn(envelope)
            LOGGER.debug(
                "System telemetry emitted topic=%s cpu=%s mem=%s temp=%s",
                envelope.topic,
                payload["cpu_percent_total"],
                payload["mem_percent"],
                payload["temperature_c"],
            )

            prev_net = net
            prev_mono = now_mono

        LOGGER.info("SystemIngestor stopped")


class UDPJsonIngestor(StoppableThread):
    RESERVED_FIELDS = {
        "device_id",
        "stream",
        "sample_period_ms",
        "qos",
        "retain",
        "topic",
        "payload",
        "ts_source_ms",
        "seq",
    }

    def __init__(
        self,
        *,
        emit_fn: EmitFn,
        base_topic: str,
        bind_host: str = "0.0.0.0",
        bind_port: int = 9100,
    ) -> None:
        super().__init__(name="udp_json_ingestor")
        self.emit_fn = emit_fn
        self.base_topic = base_topic
        self.bind_host = bind_host
        self.bind_port = bind_port

    def run(self) -> None:
        LOGGER.info("UDPJsonIngestor listening on %s:%s", self.bind_host, self.bind_port)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.bind_host, self.bind_port))
        sock.settimeout(0.5)

        try:
            while not self.stopped():
                try:
                    data, addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue

                try:
                    msg = json.loads(data.decode("utf-8"))

                    device_id = str(msg["device_id"])
                    stream = str(msg["stream"])
                    sample_period_ms = int(msg.get("sample_period_ms", 0))
                    qos = int(msg.get("qos", 0))
                    retain = bool(msg.get("retain", False))
                    explicit_topic = msg.get("topic")
                    source_ts_ms = int(msg.get("ts_source_ms", now_ms()))
                    seq = msg.get("seq")

                    payload = msg.get("payload")
                    if payload is None:
                        payload = {
                            key: value
                            for key, value in msg.items()
                            if key not in self.RESERVED_FIELDS
                        }

                    envelope = build_envelope(
                        base_topic=self.base_topic,
                        device_id=device_id,
                        stream=stream,
                        payload=payload,
                        sample_period_ms=sample_period_ms,
                        qos=qos,
                        retain=retain,
                        source_ts_ms=source_ts_ms,
                        seq=seq,
                        explicit_topic=explicit_topic,
                    )
                    self.emit_fn(envelope)
                    LOGGER.debug(
                        "UDP telemetry accepted from %s:%s topic=%s device_id=%s stream=%s",
                        addr[0],
                        addr[1],
                        envelope.topic,
                        device_id,
                        stream,
                    )

                except Exception as exc:
                    LOGGER.exception(
                        "Invalid UDP packet from %s:%s. Error: %s. Raw=%r",
                        addr[0],
                        addr[1],
                        exc,
                        data[:300],
                    )
        finally:
            sock.close()
            LOGGER.info("UDPJsonIngestor stopped")