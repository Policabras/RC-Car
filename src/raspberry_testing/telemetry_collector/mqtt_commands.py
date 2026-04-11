from __future__ import annotations

import json
import logging

import paho.mqtt.client as mqtt

from command_state import ThreadSafeCommandState
from config import AppConfig
from ingestors import StoppableThread

LOGGER = logging.getLogger(__name__)


class MqttCommandSubscriber(StoppableThread):
    def __init__(
        self,
        *,
        config: AppConfig,
        command_state: ThreadSafeCommandState,
    ) -> None:
        super().__init__(name="mqtt_commands")
        self.config = config
        self.command_state = command_state
        self.client: mqtt.Client | None = None

    @property
    def base_topic(self) -> str:
        return self.config.robot_control.command_topic.rstrip("/")

    def _build_client(self) -> mqtt.Client:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{self.config.mqtt.client_id}_cmd",
            clean_session=True,
            protocol=mqtt.MQTTv311,
            reconnect_on_failure=True,
        )

        if self.config.mqtt.username:
            client.username_pw_set(
                username=self.config.mqtt.username,
                password=self.config.mqtt.password,
            )

        client.enable_logger(LOGGER)
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        LOGGER.info("MQTT command subscriber connected reason_code=%s", reason_code)

        topics = [
            (self.base_topic, 1),
            (f"{self.base_topic}/drive", 1),
            (f"{self.base_topic}/flipper", 1),
            (f"{self.base_topic}/arm/base", 1),
            (f"{self.base_topic}/arm/elbow", 1),
            (f"{self.base_topic}/arm/wrist", 1),
            (f"{self.base_topic}/arm/grip", 1),
            (f"{self.base_topic}/stop", 1),
        ]
        client.subscribe(topics)
        LOGGER.info("Subscribed to robot command topics base_topic=%s", self.base_topic)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        LOGGER.warning("MQTT command subscriber disconnected reason_code=%s", reason_code)

    @staticmethod
    def _decode_payload(payload: bytes) -> object:
        text = payload.decode("utf-8").strip()
        if not text:
            return {}

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                return int(float(text))
            except ValueError:
                lowered = text.lower()
                if lowered in {"stop", "true", "on"}:
                    return {"stop": True}
                raise ValueError(f"Unsupported non-JSON payload: {text!r}")

    def _apply_base_command(self, data: object, *, topic: str) -> None:
        if not isinstance(data, dict):
            raise ValueError("Base command topic expects a JSON object payload")

        if data.get("stop") is True:
            self.command_state.stop_all(source=topic)
            return

        self.command_state.update_partial(data, source=topic)

    def _apply_drive_command(self, data: object, *, topic: str) -> None:
        if not isinstance(data, dict):
            raise ValueError("Drive topic expects JSON like {'v': 100, 'w': 0}")
        self.command_state.update_partial(
            {
                "v": data.get("v", 0),
                "w": data.get("w", 0),
            },
            source=topic,
        )

    def _apply_scalar_command(self, field: str, data: object, *, topic: str) -> None:
        if isinstance(data, dict):
            if field in data:
                value = data[field]
            else:
                value = data.get("value")
        else:
            value = data

        if value is None:
            raise ValueError(f"Topic {topic} requires a numeric payload")

        self.command_state.update_partial({field: value}, source=topic)

    def _on_message(self, client, userdata, message) -> None:
        topic = message.topic.rstrip("/")

        try:
            data = self._decode_payload(message.payload)

            if topic == self.base_topic:
                self._apply_base_command(data, topic=topic)
                return

            if topic == f"{self.base_topic}/drive":
                self._apply_drive_command(data, topic=topic)
                return

            if topic == f"{self.base_topic}/flipper":
                self._apply_scalar_command("f", data, topic=topic)
                return

            if topic == f"{self.base_topic}/arm/base":
                self._apply_scalar_command("base", data, topic=topic)
                return

            if topic == f"{self.base_topic}/arm/elbow":
                self._apply_scalar_command("elbow", data, topic=topic)
                return

            if topic == f"{self.base_topic}/arm/wrist":
                self._apply_scalar_command("wrist", data, topic=topic)
                return

            if topic == f"{self.base_topic}/arm/grip":
                self._apply_scalar_command("grip", data, topic=topic)
                return

            if topic == f"{self.base_topic}/stop":
                self.command_state.stop_all(source=topic)
                return

            LOGGER.warning("Unhandled robot command topic=%s", topic)

        except Exception as exc:
            LOGGER.exception(
                "Invalid robot command topic=%s payload=%r error=%s",
                topic,
                message.payload[:300],
                exc,
            )

    def run(self) -> None:
        LOGGER.info(
            "Starting MQTT command subscriber broker=%s:%s base_topic=%s",
            self.config.mqtt.host,
            self.config.mqtt.port,
            self.base_topic,
        )

        self.client = self._build_client()
        self.client.connect_async(
            host=self.config.mqtt.host,
            port=self.config.mqtt.port,
            keepalive=self.config.mqtt.keepalive,
        )
        self.client.loop_start()

        try:
            while not self.stopped():
                self._stop_event.wait(0.5)
        finally:
            if self.client is not None:
                try:
                    self.client.disconnect()
                except Exception:
                    LOGGER.exception("Error disconnecting MQTT command subscriber")
                finally:
                    self.client.loop_stop()

            LOGGER.info("MQTT command subscriber stopped")