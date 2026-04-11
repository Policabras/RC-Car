from __future__ import annotations

import logging
import queue
import signal
import sys
import threading
import time

from command_state import ThreadSafeCommandState
from config import AppConfig, load_config
from ingestors import StoppableThread, SystemIngestor, UDPJsonIngestor
from models import TelemetryEnvelope
from mqtt_commands import MqttCommandSubscriber
from mqtt_uplink import MqttUplinkPublisher
from outbox import SQLiteOutbox
from robot_serial_bridge import RobotSerialBridge
from serial_ingestors import SerialJsonIngestor

LOGGER = logging.getLogger(__name__)


class PersistWorker(StoppableThread):
    def __init__(self, *, inbox: queue.Queue[TelemetryEnvelope], outbox: SQLiteOutbox) -> None:
        super().__init__(name="persist_worker")
        self.inbox = inbox
        self.outbox = outbox

    def run(self) -> None:
        LOGGER.info("PersistWorker started")
        while not self.stopped():
            try:
                envelope = self.inbox.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self.outbox.enqueue(
                    topic=envelope.topic,
                    payload_json=envelope.to_json(),
                    qos=envelope.qos,
                    retain=envelope.retain,
                    created_at_ms=envelope.created_at_ms,
                )
            except Exception:
                LOGGER.exception("Failed to persist telemetry envelope")
            finally:
                self.inbox.task_done()

        LOGGER.info("PersistWorker stopped")


class CollectorApp:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.inbox: queue.Queue[TelemetryEnvelope] = queue.Queue(maxsize=10000)
        self.outbox = SQLiteOutbox(config.storage.sqlite_path)

        self.persist_worker = PersistWorker(inbox=self.inbox, outbox=self.outbox)
        self.mqtt_uplink = MqttUplinkPublisher(config=config, outbox=self.outbox)
        self.system_ingestor = SystemIngestor(
            emit_fn=self.emit,
            base_topic=config.mqtt.base_topic,
            edge_id=config.edge_id,
            sample_period_ms=config.system.sample_period_ms,
        )

        self.udp_ingestor = None
        if config.udp.enabled:
            self.udp_ingestor = UDPJsonIngestor(
                emit_fn=self.emit,
                base_topic=config.mqtt.base_topic,
                bind_host=config.udp.bind_host,
                bind_port=config.udp.bind_port,
            )

        serial_ports = list(config.serial.ports)
        self.command_state = None
        self.mqtt_commands = None
        self.robot_bridge = None

        if config.robot_control.enabled:
            self.command_state = ThreadSafeCommandState()
            self.mqtt_commands = MqttCommandSubscriber(
                config=config,
                command_state=self.command_state,
            )
            self.robot_bridge = RobotSerialBridge(
                emit_fn=self.emit,
                command_state=self.command_state,
                base_topic=config.mqtt.base_topic,
                port=config.robot_control.port,
                baudrate=config.robot_control.baudrate,
                timeout_s=config.robot_control.timeout_ms / 1000.0,
                reconnect_delay_s=config.robot_control.reconnect_delay_ms / 1000.0,
                tx_period_s=config.robot_control.tx_period_ms / 1000.0,
                command_timeout_ms=config.robot_control.command_timeout_ms,
            )

            if config.robot_control.port in serial_ports:
                LOGGER.warning(
                    "Removing robot control port %s from SERIAL_PORTS to avoid double-open conflicts",
                    config.robot_control.port,
                )
                serial_ports = [p for p in serial_ports if p != config.robot_control.port]

        self.serial_ingestors: list[SerialJsonIngestor] = []
        if config.serial.enabled and serial_ports:
            self.serial_ingestors = [
                SerialJsonIngestor(
                    emit_fn=self.emit,
                    base_topic=config.mqtt.base_topic,
                    port=port,
                    baudrate=config.serial.baudrate,
                    timeout_s=config.serial.timeout_ms / 1000.0,
                    reconnect_delay_s=config.serial.reconnect_delay_ms / 1000.0,
                )
                for port in serial_ports
            ]

        self._workers: list[threading.Thread] = [
            self.persist_worker,
            self.mqtt_uplink,
            self.system_ingestor,
        ]
        if self.udp_ingestor is not None:
            self._workers.append(self.udp_ingestor)
        if self.mqtt_commands is not None:
            self._workers.append(self.mqtt_commands)
        if self.robot_bridge is not None:
            self._workers.append(self.robot_bridge)
        self._workers.extend(self.serial_ingestors)

    def emit(self, envelope: TelemetryEnvelope) -> None:
        try:
            self.inbox.put(envelope, timeout=1.0)
            LOGGER.debug("Envelope queued topic=%s queue_size=%s", envelope.topic, self.inbox.qsize())
        except queue.Full:
            LOGGER.error("Inbox queue is full. Dropping message: %s", envelope.topic)

    def start(self) -> None:
        self.outbox.setup()

        LOGGER.info("Collector starting with edge_id=%s", self.config.edge_id)
        LOGGER.info("MQTT remote broker: %s:%s", self.config.mqtt.host, self.config.mqtt.port)
        LOGGER.info(
            "UDP enabled=%s input=%s:%s",
            self.config.udp.enabled,
            self.config.udp.bind_host,
            self.config.udp.bind_port,
        )
        LOGGER.info(
            "Serial enabled=%s ports=%s baudrate=%s",
            self.config.serial.enabled,
            self.config.serial.ports,
            self.config.serial.baudrate,
        )
        LOGGER.info(
            "Robot control enabled=%s port=%s topic=%s tx_period_ms=%s timeout_ms=%s",
            self.config.robot_control.enabled,
            self.config.robot_control.port,
            self.config.robot_control.command_topic,
            self.config.robot_control.tx_period_ms,
            self.config.robot_control.command_timeout_ms,
        )
        LOGGER.info("SQLite path: %s", self.config.storage.sqlite_path)

        if self.config.serial.enabled and not self.config.serial.ports:
            LOGGER.warning("Serial ingestion is enabled but SERIAL_PORTS is empty")
        if self.config.robot_control.enabled and not self.config.robot_control.port:
            LOGGER.warning("Robot control is enabled but ROBOT_SERIAL_PORT is empty")

        for worker in self._workers:
            LOGGER.info("Starting worker=%s", worker.name)
            worker.start()

    def stop(self) -> None:
        LOGGER.info("Stopping collector...")
        self.persist_worker.stop()
        self.mqtt_uplink.stop()
        self.system_ingestor.stop()

        if self.udp_ingestor is not None:
            self.udp_ingestor.stop()
        if self.mqtt_commands is not None:
            self.mqtt_commands.stop()
        if self.robot_bridge is not None:
            self.robot_bridge.stop()

        for ingestor in self.serial_ingestors:
            ingestor.stop()

        for worker in self._workers:
            LOGGER.info("Joining worker=%s", worker.name)
            worker.join(timeout=3.0)

    def run_forever(self) -> None:
        self.start()

        try:
            while True:
                time.sleep(5)
                counts = self.outbox.get_counts()
                LOGGER.info(
                    "Outbox status => PENDING=%s RETRY=%s SENT=%s queue=%s",
                    counts["PENDING"],
                    counts["RETRY"],
                    counts["SENT"],
                    self.inbox.qsize(),
                )
        except KeyboardInterrupt:
            LOGGER.info("KeyboardInterrupt received")
        finally:
            self.stop()


def setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    LOGGER.info("Logging configured level=%s", "DEBUG" if debug else "INFO")


def main() -> None:
    config = load_config()
    setup_logging(config.debug)
    LOGGER.info("Configuration loaded successfully")

    app = CollectorApp(config)

    def _handle_signal(signum, frame) -> None:
        LOGGER.info("Signal received signum=%s", signum)
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    app.run_forever()


if __name__ == "__main__":
    main()