from __future__ import annotations

import json
import logging
import time
from typing import Callable

import serial

from command_state import ThreadSafeCommandState
from ingestors import StoppableThread
from models import TelemetryEnvelope, build_envelope, now_ms

LOGGER = logging.getLogger(__name__)
EmitFn = Callable[[TelemetryEnvelope], None]


class RobotSerialBridge(StoppableThread):
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
        command_state: ThreadSafeCommandState,
        base_topic: str,
        port: str,
        baudrate: int = 115200,
        timeout_s: float = 0.05,
        reconnect_delay_s: float = 1.5,
        tx_period_s: float = 0.05,
        command_timeout_ms: int = 300,
    ) -> None:
        super().__init__(name=f"robot_serial_bridge[{port}]")
        self.emit_fn = emit_fn
        self.command_state = command_state
        self.base_topic = base_topic
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.reconnect_delay_s = reconnect_delay_s
        self.tx_period_s = tx_period_s
        self.command_timeout_ms = command_timeout_ms

        self._non_json_debug_budget = 25

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

    def _log_non_json(self, raw: bytes) -> None:
        if self._non_json_debug_budget <= 0:
            return

        self._non_json_debug_budget -= 1
        preview = raw[:120]
        text_preview = preview.decode("utf-8", errors="replace").strip()
        LOGGER.debug(
            "Ignoring non-JSON serial line on %s len=%s raw=%r hex=%s text=%s",
            self.port,
            len(raw),
            preview,
            preview.hex(" "),
            text_preview,
        )

    def run(self) -> None:
        LOGGER.info(
            "RobotSerialBridge starting port=%s baudrate=%s tx_period_s=%.3f command_timeout_ms=%s",
            self.port,
            self.baudrate,
            self.tx_period_s,
            self.command_timeout_ms,
        )

        while not self.stopped():
            try:
                with serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout_s,
                    write_timeout=1.0,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    exclusive=True,
                ) as ser:
                    try:
                        ser.dtr = False
                        ser.rts = False
                    except Exception:
                        LOGGER.debug("Could not force DTR/RTS low on %s", self.port, exc_info=True)

                    time.sleep(0.25)

                    try:
                        ser.reset_input_buffer()
                        ser.reset_output_buffer()
                    except Exception:
                        LOGGER.debug("Could not reset serial buffers on %s", self.port, exc_info=True)

                    LOGGER.info("Robot serial connected: %s", self.port)
                    next_tx = time.monotonic()

                    while not self.stopped():
                        now = time.monotonic()

                        if now >= next_tx:
                            packet = self.command_state.to_serial_packet(
                                timeout_ms=self.command_timeout_ms,
                            )
                            ser.write(packet)
                            ser.flush()
                            LOGGER.debug("Robot UART TX port=%s packet=%r", self.port, packet)
                            next_tx = now + self.tx_period_s

                        raw = ser.readline()
                        if not raw:
                            continue

                        line = raw.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue

                        if not line.startswith("{"):
                            self._log_non_json(raw)
                            continue

                        try:
                            envelope = self._line_to_envelope(line)
                            self.emit_fn(envelope)
                            LOGGER.debug(
                                "Robot UART RX accepted port=%s topic=%s",
                                self.port,
                                envelope.topic,
                            )
                        except Exception as exc:
                            LOGGER.exception(
                                "Invalid robot serial JSON on %s error=%s line=%r",
                                self.port,
                                exc,
                                line[:500],
                            )

            except serial.SerialException as exc:
                LOGGER.warning("Robot serial disconnected on %s: %s", self.port, exc)
            except Exception as exc:
                LOGGER.exception("Unexpected robot serial error on %s: %s", self.port, exc)

            if not self.stopped():
                time.sleep(self.reconnect_delay_s)

        LOGGER.info("RobotSerialBridge stopped: %s", self.port)
