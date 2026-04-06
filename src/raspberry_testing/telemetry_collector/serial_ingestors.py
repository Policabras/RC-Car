from __future__ import annotations

import json
import logging
import time
from typing import Callable

import serial

from ingestors import StoppableThread
from models import TelemetryEnvelope, build_envelope, now_ms

LOGGER = logging.getLogger(__name__)
EmitFn = Callable[[TelemetryEnvelope], None]


class SerialJsonIngestor(StoppableThread):
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
        port: str,
        baudrate: int = 115200,
        timeout_s: float = 0.2,
        reconnect_delay_s: float = 1.5,
    ) -> None:
        super().__init__(name=f"serial_ingestor[{port}]")
        self.emit_fn = emit_fn
        self.base_topic = base_topic
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.reconnect_delay_s = reconnect_delay_s

    def _line_to_envelope(self, line: str) -> TelemetryEnvelope:
        msg = json.loads(line)

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

        return build_envelope(
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

    def run(self) -> None:
        LOGGER.info(
            "SerialJsonIngestor starting on port=%s baudrate=%s",
            self.port,
            self.baudrate,
        )

        while not self.stopped():
            try:
                with serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout_s,
                    write_timeout=1.0,
                ) as ser:
                    LOGGER.info("Serial connected: %s", self.port)

                    while not self.stopped():
                        raw = ser.readline()
                        if not raw:
                            continue

                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue

                        if not line.startswith("{"):
                            LOGGER.debug(
                                "Ignoring non-JSON serial line on %s: %s",
                                self.port,
                                line,
                            )
                            continue

                        try:
                            envelope = self._line_to_envelope(line)
                            self.emit_fn(envelope)
                            LOGGER.debug(
                                "Serial telemetry accepted port=%s topic=%s",
                                self.port,
                                envelope.topic,
                            )
                        except Exception as exc:
                            LOGGER.exception(
                                "Invalid JSON line on %s. Error=%s line=%r",
                                self.port,
                                exc,
                                line[:500],
                            )

            except serial.SerialException as exc:
                LOGGER.warning("Serial disconnected/unavailable on %s: %s", self.port, exc)
            except Exception as exc:
                LOGGER.exception("Unexpected serial error on %s: %s", self.port, exc)

            if not self.stopped():
                time.sleep(self.reconnect_delay_s)

        LOGGER.info("SerialJsonIngestor stopped: %s", self.port)