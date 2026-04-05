from __future__ import annotations

import json
import time
from dataclasses import dataclass


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class TelemetryEnvelope:
    topic: str
    qos: int
    retain: bool
    payload: dict
    created_at_ms: int

    def to_json(self) -> str:
        return json.dumps(self.payload, separators=(",", ":"), ensure_ascii=False)


def build_envelope(
    *,
    base_topic: str,
    device_id: str,
    stream: str,
    payload: dict,
    sample_period_ms: int,
    qos: int = 0,
    retain: bool = False,
    source_ts_ms: int | None = None,
    seq: int | None = None,
    explicit_topic: str | None = None,
) -> TelemetryEnvelope:
    collector_ts_ms = now_ms()
    source_ts_ms = source_ts_ms if source_ts_ms is not None else collector_ts_ms

    full_payload = {
        "device_id": device_id,
        "stream": stream,
        "seq": seq if seq is not None else collector_ts_ms,
        "ts_source_ms": source_ts_ms,
        "ts_collector_ms": collector_ts_ms,
        "sample_period_ms": sample_period_ms,
        "payload": payload,
    }

    topic = explicit_topic or f"{base_topic}/{device_id}/{stream}"

    return TelemetryEnvelope(
        topic=topic,
        qos=qos,
        retain=retain,
        payload=full_payload,
        created_at_ms=collector_ts_ms,
    )
