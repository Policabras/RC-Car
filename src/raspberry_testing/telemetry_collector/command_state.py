from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass
from typing import Mapping

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RobotCommandState:
    v: int = 0
    w: int = 0
    f: int = 0
    base: int = 0
    elbow: int = 0
    wrist: int = 0
    grip: int = 0


class ThreadSafeCommandState:
    VALID_FIELDS = {"v", "w", "f", "base", "elbow", "wrist", "grip"}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = RobotCommandState()
        self._last_update_mono: float | None = None
        self._last_source: str = "init"

    @staticmethod
    def _clamp_int(value: object) -> int:
        parsed = int(float(value))
        return max(-1000, min(1000, parsed))

    @staticmethod
    def _zero_state() -> RobotCommandState:
        return RobotCommandState()

    def update_partial(self, values: Mapping[str, object], *, source: str = "mqtt") -> None:
        updates: dict[str, int] = {}

        for key, raw_value in values.items():
            if key not in self.VALID_FIELDS:
                continue
            if raw_value is None:
                continue
            updates[key] = self._clamp_int(raw_value)

        if not updates:
            LOGGER.debug("Ignoring empty command update source=%s values=%s", source, values)
            return

        with self._lock:
            for key, value in updates.items():
                setattr(self._state, key, value)
            self._last_update_mono = time.monotonic()
            self._last_source = source

        LOGGER.debug("Command state updated source=%s updates=%s", source, updates)

    def stop_all(self, *, source: str = "stop") -> None:
        with self._lock:
            self._state = self._zero_state()
            self._last_update_mono = time.monotonic()
            self._last_source = source

        LOGGER.info("Command state forced to zero source=%s", source)

    def snapshot_for_tx(self, *, timeout_ms: int) -> RobotCommandState:
        with self._lock:
            state = RobotCommandState(**asdict(self._state))
            last_update_mono = self._last_update_mono
            last_source = self._last_source

        if last_update_mono is None:
            return self._zero_state()

        age_ms = (time.monotonic() - last_update_mono) * 1000.0
        if age_ms > timeout_ms:
            LOGGER.debug(
                "Command state stale age_ms=%.1f timeout_ms=%s last_source=%s; sending zeros",
                age_ms,
                timeout_ms,
                last_source,
            )
            return self._zero_state()

        return state

    def to_serial_packet(self, *, timeout_ms: int) -> bytes:
        state = self.snapshot_for_tx(timeout_ms=timeout_ms)
        packet = (
            f"<{state.v},{state.w},{state.f},{state.base},{state.elbow},"
            f"{state.wrist},{state.grip}>\n"
        )
        return packet.encode("utf-8")