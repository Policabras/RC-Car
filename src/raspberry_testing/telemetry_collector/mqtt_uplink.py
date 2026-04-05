from __future__ import annotations

import json
import logging
import threading

import paho.mqtt.client as mqtt

from config import AppConfig
from models import now_ms
from outbox import SQLiteOutbox

LOGGER = logging.getLogger(__name__)


class MqttUplinkPublisher(threading.Thread):
    def __init__(self, *, config: AppConfig, outbox: SQLiteOutbox) -> None:
        super().__init__(name="mqtt_uplink", daemon=True)
        self.config = config
        self.outbox = outbox
        self._stop_event = threading.Event()
        self.client: mqtt.Client | None = None

    def stop(self) -> None:
        self._stop_event.set()

    def stopped(self) -> bool:
        return self._stop_event.is_set()

    @property
    def status_topic(self) -> str:
        return f"{self.config.mqtt.base_topic}/{self.config.edge_id}/status"

    def _status_payload(self, status: str) -> str:
        return json.dumps(
            {
                "device_id": self.config.edge_id,
                "stream": "status",
                "status": status,
                "ts_ms": now_ms(),
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def _build_client(self) -> mqtt.Client:
        LOGGER.info(
            "Creating MQTT client client_id=%s base_topic=%s",
            self.config.mqtt.client_id,
            self.config.mqtt.base_topic,
        )

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.config.mqtt.client_id,
            clean_session=False,
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=True,
        )

        if self.config.mqtt.username:
            LOGGER.info("Configuring MQTT authentication username=%s", self.config.mqtt.username)
            client.username_pw_set(
                username=self.config.mqtt.username,
                password=self.config.mqtt.password,
            )

        client.enable_logger(LOGGER)
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        client.will_set(
            topic=self.status_topic,
            payload=self._status_payload("offline"),
            qos=1,
            retain=True,
        )
        LOGGER.debug("Configured MQTT last will topic=%s", self.status_topic)

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        return client

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        LOGGER.info("Connected to MQTT broker. reason_code=%s", reason_code)
        client.publish(
            topic=self.status_topic,
            payload=self._status_payload("online"),
            qos=1,
            retain=True,
        )
        LOGGER.debug("Published MQTT online status topic=%s", self.status_topic)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        LOGGER.warning("Disconnected from MQTT broker. reason_code=%s", reason_code)

    def run(self) -> None:
        LOGGER.info(
            "Starting MQTT uplink to %s:%s",
            self.config.mqtt.host,
            self.config.mqtt.port,
        )

        self.client = self._build_client()
        self.client.connect_async(
            host=self.config.mqtt.host,
            port=self.config.mqtt.port,
            keepalive=self.config.mqtt.keepalive,
        )
        self.client.loop_start()
        LOGGER.info("MQTT network loop started")

        try:
            while not self.stopped():
                if not self.client.is_connected():
                    LOGGER.debug("MQTT client not connected yet; waiting...")
                    self._stop_event.wait(self.config.publish.poll_interval_ms / 1000.0)
                    continue

                batch = self.outbox.fetch_batch(limit=self.config.publish.batch_size)
                if not batch:
                    self._stop_event.wait(self.config.publish.poll_interval_ms / 1000.0)
                    continue

                LOGGER.debug("Fetched MQTT batch size=%s", len(batch))

                for row in batch:
                    if self.stopped():
                        break

                    try:
                        LOGGER.debug(
                            "Publishing row_id=%s topic=%s qos=%s retain=%s",
                            row["id"],
                            row["topic"],
                            row["qos"],
                            row["retain"],
                        )
                        info = self.client.publish(
                            topic=row["topic"],
                            payload=row["payload_json"],
                            qos=int(row["qos"]),
                            retain=bool(row["retain"]),
                        )
                        info.wait_for_publish(timeout=2.0)
                        if info.rc == mqtt.MQTT_ERR_SUCCESS:
                            self.outbox.mark_sent(int(row["id"]))
                            LOGGER.debug("Publish successful row_id=%s", row["id"])
                        else:
                            raise RuntimeError(f"MQTT publish rc={info.rc}")

                    except Exception as exc:
                        LOGGER.exception("MQTT publish failed for row_id=%s", row["id"])
                        self.outbox.mark_retry(int(row["id"]), str(exc))
                        break

        finally:
            if self.client is not None:
                try:
                    if self.client.is_connected():
                        LOGGER.info("Publishing MQTT stopped status topic=%s", self.status_topic)
                        self.client.publish(
                            topic=self.status_topic,
                            payload=self._status_payload("stopped"),
                            qos=1,
                            retain=True,
                        )
                        self.client.disconnect()
                        LOGGER.info("MQTT client disconnected")
                finally:
                    self.client.loop_stop()
                    LOGGER.info("MQTT network loop stopped")

            LOGGER.info("MQTT uplink stopped")