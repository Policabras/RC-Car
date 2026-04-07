from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from config import QrConfig
from ingestors import StoppableThread
from models import TelemetryEnvelope, build_envelope, now_ms

LOGGER = logging.getLogger(__name__)
EmitFn = Callable[[TelemetryEnvelope], None]


class QrCodeIngestor(StoppableThread):
    def __init__(
        self,
        *,
        emit_fn: EmitFn,
        base_topic: str,
        config: QrConfig,
    ) -> None:
        super().__init__(name="qr_code_ingestor")
        self.emit_fn = emit_fn
        self.base_topic = base_topic
        self.config = config
        self._last_seen_by_value: dict[str, int] = {}

    def _should_emit(self, qr_value: str, ts_ms: int) -> bool:
        last_seen = self._last_seen_by_value.get(qr_value)
        if last_seen is None or (ts_ms - last_seen) >= self.config.dedup_window_ms:
            self._last_seen_by_value[qr_value] = ts_ms
            return True
        return False

    def _cleanup_cache(self, ts_ms: int) -> None:
        cutoff = ts_ms - max(self.config.dedup_window_ms * 3, 10000)
        stale_keys = [key for key, value in self._last_seen_by_value.items() if value < cutoff]
        for key in stale_keys:
            self._last_seen_by_value.pop(key, None)

    def _save_detection_artifacts(self, frame, qr_value: str, timestamp: str) -> tuple[str | None, str | None]:
        if not self.config.save_detections:
            return None, None

        storage_dir = Path(self.config.storage_dir)
        storage_dir.mkdir(parents=True, exist_ok=True)

        image_path = storage_dir / f"{timestamp}.png"
        text_path = storage_dir / f"{timestamp}.txt"

        try:
            import cv2  # pylint: disable=import-outside-toplevel

            cv2.imwrite(str(image_path), frame)
            text_path.write_text(qr_value, encoding="utf-8")
            return str(image_path), str(text_path)
        except Exception:
            LOGGER.exception("Failed to save QR detection artifacts")
            return None, None

    def run(self) -> None:
        if not self.config.stream_url:
            LOGGER.warning("QR ingestion enabled but QR_STREAM_URL is empty")
            return

        try:
            import cv2  # pylint: disable=import-outside-toplevel
        except ImportError:
            LOGGER.exception("opencv-python-headless is required for QR ingestion")
            return

        detector = cv2.QRCodeDetector()

        LOGGER.info(
            "QrCodeIngestor started stream=%s device_id=%s stream_name=%s",
            self.config.stream_url,
            self.config.device_id,
            self.config.stream_name,
        )

        while not self.stopped():
            cap = cv2.VideoCapture(self.config.stream_url)
            if not cap.isOpened():
                LOGGER.warning("Unable to open QR stream: %s", self.config.stream_url)
                if self._stop_event.wait(self.config.reconnect_delay_ms / 1000.0):
                    break
                continue

            LOGGER.info("QR stream connected: %s", self.config.stream_url)

            try:
                while not self.stopped():
                    success, frame = cap.read()
                    if not success or frame is None:
                        LOGGER.warning("Failed to read frame from QR stream; reconnecting...")
                        break

                    small = cv2.resize(
                        frame,
                        (self.config.decode_width, self.config.decode_height),
                    )
                    retval, decoded_info, points, _ = detector.detectAndDecodeMulti(small)

                    if retval and points is not None:
                        scale_x = frame.shape[1] / self.config.decode_width
                        scale_y = frame.shape[0] / self.config.decode_height

                        for index, qr_value in enumerate(decoded_info):
                            if not qr_value:
                                continue

                            detected_at_ms = now_ms()
                            if not self._should_emit(qr_value, detected_at_ms):
                                continue

                            pts = points[index].astype(int)
                            polygon = [
                                [int(point[0] * scale_x), int(point[1] * scale_y)]
                                for point in pts
                            ]
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            image_path, text_path = self._save_detection_artifacts(frame, qr_value, timestamp)

                            payload = {
                                "qr_value": qr_value,
                                "camera_stream_url": self.config.stream_url,
                                "detected_at_iso": datetime.now().isoformat(timespec="seconds"),
                                "bbox": polygon,
                                "image_path": image_path,
                                "text_path": text_path,
                                "source": "opencv_qrcode_detector",
                            }

                            envelope = build_envelope(
                                base_topic=self.base_topic,
                                device_id=self.config.device_id,
                                stream=self.config.stream_name,
                                payload=payload,
                                sample_period_ms=self.config.sample_period_ms,
                                qos=1,
                                retain=False,
                                source_ts_ms=detected_at_ms,
                                seq=detected_at_ms,
                            )
                            self.emit_fn(envelope)
                            LOGGER.info(
                                "QR detected and queued topic=%s value=%s",
                                envelope.topic,
                                qr_value,
                            )

                        self._cleanup_cache(now_ms())

                    if self._stop_event.wait(self.config.sample_period_ms / 1000.0):
                        break
            except Exception:
                LOGGER.exception("Unexpected error in QR ingestion loop")
            finally:
                cap.release()
                LOGGER.info("QR stream released")

            if not self.stopped():
                if self._stop_event.wait(self.config.reconnect_delay_ms / 1000.0):
                    break

        LOGGER.info("QrCodeIngestor stopped")
