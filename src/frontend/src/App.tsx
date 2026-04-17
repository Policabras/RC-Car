import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { io, type Socket } from "socket.io-client";
import "./Dashboard.css";

type SystemPayload = {
  device_id: string;
  stream: "system";
  seq: number;
  ts_source_ms: number;
  ts_collector_ms: number;
  sample_period_ms: number;
  payload: {
    cpu_percent_total: number;
    cpu_percent_per_core: number[];
    mem_percent: number;
    mem_available_bytes: number;
    disk_percent_root: number;
    temperature_c: number;
    net_rx_Bps: number;
    net_tx_Bps: number;
    boot_time_s: number;
    loadavg: number[];
  };
};

type StatusData = {
  device_id: string;
  stream: "status";
  status: string;
  ts_ms: number;
};

type ActuatorsData = {
  device_id: string;
  stream: "actuators";
  seq: number;
  ts_source_ms: number;
  ts_collector_ms: number;
  sample_period_ms: number;
  payload: {
    v_cmd: number;
    w_cmd: number;
    f_cmd: number;
    base_cmd: number;
    elbow_cmd: number;
    wrist_cmd: number;
    grip_cmd: number;
    flipper_pos: number;
    base_pos: number;
    elbow_pos: number;
    wrist_pos: number;
    grip_pos: number;
    left_mix: number;
    right_mix: number;
    link_ok: boolean;
  };
};

type CommandPayload = {
  v?: number;
  w?: number;
  f?: number;
  base?: number;
  elbow?: number;
  wrist?: number;
  grip?: number;
  [key: string]: unknown;
};

type QrPayload = {
  qr: string;
  camera: number;
  points: { x: number; y: number }[];
  timestamp: string;
  frame_width: number;
  frame_height: number;
};

type QrData = {
  topic: string;
  subStream: string | null;
  payload: QrPayload;
};

type InitialTelemetry = {
  system: SystemPayload | null;
  status: StatusData | null;
  actuators: ActuatorsData | null;
  cmd: unknown;
  qr: QrData | null;
};

const BACKEND_URL = "http://192.168.3.4:3000";
const FRONT_CAMERA_URL = "http://192.168.3.16:8081/mjpeg/0";
const REAR_CAMERA_URL = "http://192.168.3.16:8081/mjpeg/1";

function App() {
  const socketRef = useRef<Socket | null>(null);

  const [connected, setConnected] = useState(false);
  const [frontCameraLive, setFrontCameraLive] = useState(false);
  const [rearCameraLive, setRearCameraLive] = useState(false);

  const [systemData, setSystemData] = useState<SystemPayload | null>(null);
  const [statusData, setStatusData] = useState<StatusData | null>(null);
  const [actuatorsData, setActuatorsData] = useState<ActuatorsData | null>(null);
  const [cmdData, setCmdData] = useState<CommandPayload | null>(null);
  const [qrData, setQrData] = useState<QrData | null>(null);

  const [lastTelemetryAt, setLastTelemetryAt] = useState<number | null>(null);
  const [lastUpdateSeconds, setLastUpdateSeconds] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!lastTelemetryAt) {
        setLastUpdateSeconds(0);
        return;
      }

      const elapsed = (Date.now() - lastTelemetryAt) / 1000;
      setLastUpdateSeconds(elapsed);
    }, 250);

    return () => window.clearInterval(timer);
  }, [lastTelemetryAt]);

  useEffect(() => {
    const socket = io(BACKEND_URL, {
      transports: ["websocket"],
      upgrade: false,
    });

    socketRef.current = socket;

    const markTelemetry = () => {
      setLastTelemetryAt(Date.now());
    };

    socket.on("connect", () => setConnected(true));
    socket.on("disconnect", () => setConnected(false));

    socket.on("initialTelemetry", (data: InitialTelemetry) => {
      setSystemData(data.system);
      setStatusData(data.status);
      setActuatorsData(data.actuators);
      setCmdData(normalizeCmdData(data.cmd));
      setQrData(data.qr);
      markTelemetry();
    });

    socket.on("systemData", (data: SystemPayload) => {
      setSystemData(data);
      markTelemetry();
    });

    socket.on("statusData", (data: StatusData) => {
      setStatusData(data);
      markTelemetry();
    });

    socket.on("actuatorsData", (data: ActuatorsData) => {
      setActuatorsData(data);
      markTelemetry();
    });

    socket.on("cmdData", (data: unknown) => {
      setCmdData(normalizeCmdData(data));
      markTelemetry();
    });

    socket.on("qrData", (data: QrData) => {
      setQrData(data);
      markTelemetry();
    });

    return () => {
      socket.disconnect();
    };
  }, []);

  const system = systemData?.payload;
  const actuators = actuatorsData?.payload;

  const deviceId =
    statusData?.device_id ||
    systemData?.device_id ||
    actuatorsData?.device_id ||
    "--";

  const robotStatus = formatStatus(statusData?.status);
  const linearSpeed = toNumber(actuators?.v_cmd ?? cmdData?.v);
  const angularSpeed = toNumber(actuators?.w_cmd ?? cmdData?.w);

  const raspStats = useMemo(
    () => [
      {
        label: "CPU",
        value: system ? `${formatNumber(system.cpu_percent_total, 1)}%` : "--",
      },
      {
        label: "RAM",
        value: system ? `${formatNumber(system.mem_percent, 1)}%` : "--",
      },
      {
        label: "Temp",
        value: system ? `${formatNumber(system.temperature_c, 1)} °C` : "--",
      },
      {
        label: "Estado",
        value: robotStatus,
      },
      {
        label: "Último status",
        value: formatDateTime(statusData?.ts_ms),
      },
      {
        label: "Device ID",
        value: deviceId,
      },
    ],
    [deviceId, robotStatus, statusData?.ts_ms, system],
  );

  const armTelemetry = useMemo(
    () => [
      { label: "Flipper cmd", value: formatMaybeNumber(actuators?.f_cmd) },
      { label: "Flipper pos", value: formatMaybeNumber(actuators?.flipper_pos) },
      { label: "Base cmd", value: formatMaybeNumber(actuators?.base_cmd) },
      { label: "Base pos", value: formatMaybeNumber(actuators?.base_pos) },
      { label: "Elbow cmd", value: formatMaybeNumber(actuators?.elbow_cmd) },
      { label: "Elbow pos", value: formatMaybeNumber(actuators?.elbow_pos) },
      { label: "Wrist cmd", value: formatMaybeNumber(actuators?.wrist_cmd) },
      { label: "Wrist pos", value: formatMaybeNumber(actuators?.wrist_pos) },
      { label: "Grip cmd", value: formatMaybeNumber(actuators?.grip_cmd) },
      { label: "Grip pos", value: formatMaybeNumber(actuators?.grip_pos) },
      { label: "Vel R", value: formatMaybeNumber(actuators?.grip_cmd) },
      { label: "Vel L", value: formatMaybeNumber(actuators?.grip_pos) },
      {
        label: "Link OK",
        value:
          actuators?.link_ok === undefined
            ? "--"
            : actuators.link_ok
              ? "Sí"
              : "No",
      },
    ],
    [actuators],
  );

  const frontCameraStatus = FRONT_CAMERA_URL
    ? frontCameraLive
      ? "Activa"
      : "Sin señal"
    : "Sin URL";

  const rearCameraStatus = REAR_CAMERA_URL
    ? rearCameraLive
      ? "Activa"
      : "Sin señal"
    : "Sin URL";

  return (
    <div className="dashboard-page">
      <div className="dashboard-shell">
        <header className="topbar">
          <div className="brand-block">
            <p className="eyebrow">Robot Control Station</p>
            <h1>Dashboard de monitoreo</h1>
            <p className="subtitle">
              Frontend distribuido para system, status, actuators, cmd y qr.
            </p>
          </div>

          <div className="status-pills">
            <StatusPill
              label="Backend"
              value={connected ? "Conectado" : "Desconectado"}
              tone={connected ? "ok" : "danger"}
            />
            <StatusPill
              label="Cam D"
              value={frontCameraStatus}
              tone={frontCameraLive ? "ok" : "neutral"}
            />
            <StatusPill
              label="Cam T"
              value={rearCameraStatus}
              tone={rearCameraLive ? "ok" : "neutral"}
            />
            <StatusPill
              label="Robot"
              value={robotStatus}
              tone={statusData?.status === "online" ? "info" : "neutral"}
            />
            <StatusPill
              label="Última trama"
              value={`${lastUpdateSeconds.toFixed(2)} s`}
              tone="neutral"
            />
          </div>
        </header>

        <main className="workspace-grid">
          <section className="column-stack">
            <Panel
              title="Receptor QR"
              subtitle="Último QR recibido desde MQTT"
              tag="QR"
              bodyClassName="panel-no-padding"
            >
              <div className="trajectory-stage">
                <div className="trajectory-grid"></div>
                <div className="trajectory-center">
                  <div className="trajectory-badge">
                    {qrData?.payload?.camera !== undefined
                      ? `Cámara ${qrData.payload.camera}`
                      : "Sin detección"}
                  </div>

                  <div className="trajectory-title">
                    {qrData?.payload?.qr ?? "Esperando lectura de QR"}
                  </div>

                  <div className="trajectory-text">
                    {qrData?.payload?.timestamp
                      ? `Timestamp: ${qrData.payload.timestamp}`
                      : "Aún no se ha recibido ningún código QR desde el backend."}
                  </div>
                </div>
              </div>

              <div className="mini-metric-row">
                <MiniMetric label="QR" value={qrData?.payload?.qr ?? "--"} />
                <MiniMetric
                  label="Cámara"
                  value={
                    qrData?.payload?.camera !== undefined
                      ? String(qrData.payload.camera)
                      : "--"
                  }
                />
                <MiniMetric
                  label="Puntos"
                  value={
                    qrData?.payload?.points
                      ? String(qrData.payload.points.length)
                      : "--"
                  }
                />
              </div>
            </Panel>

            <Panel title="Datos de la rasp" subtitle="Sistema base" tag="Raspberry">
              <div className="metric-grid metric-grid-2">
                {raspStats.map((item) => (
                  <MetricCard
                    key={item.label}
                    label={item.label}
                    value={item.value}
                  />
                ))}
              </div>
            </Panel>
          </section>

          <section className="column-stack">
            <Panel
              title="Cámara delantera"
              subtitle="Stream MJPEG"
              tag="MJPEG"
              bodyClassName="panel-no-padding"
            >
              <CameraFeed
                src={FRONT_CAMERA_URL}
                statusText={frontCameraStatus}
                footerText={FRONT_CAMERA_URL || "Sin URL configurada"}
                heightClassName="camera-stage-large"
                onLoad={() => setFrontCameraLive(true)}
                onError={() => setFrontCameraLive(false)}
                qrOverlay={qrData?.payload?.camera === 0 ? qrData.payload : null}
              />
            </Panel>

            <Panel
              title="Cámara trasera"
              subtitle="Stream MJPEG"
              tag="MJPEG"
              bodyClassName="panel-no-padding"
            >
              <CameraFeed
                src={REAR_CAMERA_URL}
                statusText={rearCameraStatus}
                footerText={
                  REAR_CAMERA_URL || "Pendiente configurar URL de cámara trasera"
                }
                heightClassName="camera-stage-medium"
                onLoad={() => setRearCameraLive(true)}
                onError={() => setRearCameraLive(false)}
                qrOverlay={qrData?.payload?.camera === 1 ? qrData.payload : null}
              />
            </Panel>
          </section>

          <section className="column-stack">
            <Panel title="Velocidad" subtitle="Lineal y angular" tag="VEL">
              <div className="gauge-grid">
                <GaugeCard
                  label="Velocidad lineal"
                  displayValue={formatNumber(linearSpeed, 2)}
                  unit="m/s"
                  percent={toGaugePercent(linearSpeed)}
                />
                <GaugeCard
                  label="Velocidad angular"
                  displayValue={formatNumber(angularSpeed, 2)}
                  unit="rad/s"
                  percent={toGaugePercent(angularSpeed)}
                />
              </div>
            </Panel>

            <Panel
              title="Datos de telemetría"
              subtitle="Flipper y brazo robótico"
              tag="Live"
            >
              <div className="metric-grid telemetry-grid">
                {armTelemetry.map((item) => (
                  <MetricCard
                    key={item.label}
                    label={item.label}
                    value={item.value}
                  />
                ))}
              </div>
            </Panel>
          </section>
        </main>
      </div>
    </div>
  );
}

function Panel({
  title,
  subtitle,
  tag,
  children,
  bodyClassName = "",
}: {
  title: string;
  subtitle: string;
  tag: string;
  children: ReactNode;
  bodyClassName?: string;
}) {
  return (
    <article className="panel">
      <div className="panel-header">
        <div>
          <h2 className="panel-title">{title}</h2>
          <p className="panel-subtitle">{subtitle}</p>
        </div>
        <span className="panel-tag">{tag}</span>
      </div>

      <div className={`panel-body ${bodyClassName}`.trim()}>{children}</div>
    </article>
  );
}

function StatusPill({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "ok" | "info" | "neutral" | "danger";
}) {
  return (
    <div className={`status-pill status-pill-${tone}`}>
      <span className="status-pill-label">{label}</span>
      <strong className="status-pill-value">{value}</strong>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="mini-metric">
      <div className="mini-metric-label">{label}</div>
      <div className="mini-metric-value">{value}</div>
    </div>
  );
}

function GaugeCard({
  label,
  displayValue,
  unit,
  percent,
}: {
  label: string;
  displayValue: string;
  unit: string;
  percent: number;
}) {
  const radius = 46;
  const stroke = 10;
  const normalizedRadius = radius - stroke / 2;
  const circumference = normalizedRadius * 2 * Math.PI;
  const strokeDashoffset =
    circumference - (clamp(percent, 0, 100) / 100) * circumference;

  return (
    <div className="gauge-card">
      <div className="gauge-label">{label}</div>

      <div className="gauge-wrap">
        <svg className="gauge-svg" width="124" height="124" viewBox="0 0 124 124">
          <circle
            className="gauge-track"
            strokeWidth={stroke}
            r={normalizedRadius}
            cx="62"
            cy="62"
            fill="transparent"
          />
          <circle
            className="gauge-progress"
            strokeWidth={stroke}
            strokeDasharray={`${circumference} ${circumference}`}
            style={{ strokeDashoffset }}
            r={normalizedRadius}
            cx="62"
            cy="62"
            fill="transparent"
          />
        </svg>

        <div className="gauge-center">
          <div className="gauge-value">{displayValue}</div>
          <div className="gauge-unit">{unit}</div>
        </div>
      </div>
    </div>
  );
}

function CameraFeed({
  src,
  statusText,
  footerText,
  heightClassName,
  onLoad,
  onError,
  qrOverlay,
}: {
  src: string;
  statusText: string;
  footerText: string;
  heightClassName: string;
  onLoad: () => void;
  onError: () => void;
  qrOverlay: QrPayload | null;
}) {
  const hasSrc = Boolean(src);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const updateSize = () => {
      if (!stageRef.current) {
        return;
      }

      const rect = stageRef.current.getBoundingClientRect();
      setStageSize({
        width: rect.width,
        height: rect.height,
      });
    };

    updateSize();

    const resizeObserver = new ResizeObserver(() => {
      updateSize();
    });

    if (stageRef.current) {
      resizeObserver.observe(stageRef.current);
    }

    window.addEventListener("resize", updateSize);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener("resize", updateSize);
    };
  }, []);

  const overlay = useMemo(() => {
    if (
      !qrOverlay ||
      !qrOverlay.points ||
      qrOverlay.points.length < 4 ||
      !qrOverlay.frame_width ||
      !qrOverlay.frame_height ||
      !stageSize.width ||
      !stageSize.height
    ) {
      return null;
    }

    const sourceW = qrOverlay.frame_width;
    const sourceH = qrOverlay.frame_height;
    const containerW = stageSize.width;
    const containerH = stageSize.height;

    const scale = Math.min(containerW / sourceW, containerH / sourceH);
    const offsetX = (containerW - sourceW * scale) / 2;
    const offsetY = (containerH - sourceH * scale) / 2;

    const mappedPoints = qrOverlay.points.map((p) => ({
      x: offsetX + p.x * scale,
      y: offsetY + p.y * scale,
    }));

    const polygonPoints = mappedPoints.map((p) => `${p.x},${p.y}`).join(" ");
    const firstPoint = mappedPoints[0];

    return {
      polygonPoints,
      labelX: firstPoint.x,
      labelY: firstPoint.y > 18 ? firstPoint.y - 8 : firstPoint.y + 18,
    };
  }, [qrOverlay, stageSize]);

  return (
    <div ref={stageRef} className={`camera-stage ${heightClassName}`}>
      <div className="camera-overlay-grid"></div>

      <div className="camera-status-badge">{statusText}</div>

      {hasSrc ? (
        <>
          <img
            className="camera-stream"
            src={src}
            alt="Transmisión MJPEG"
            onLoad={onLoad}
            onError={onError}
          />

          {overlay ? (
            <svg
              className="camera-qr-overlay"
              viewBox={`0 0 ${stageSize.width} ${stageSize.height}`}
              preserveAspectRatio="none"
            >
              <polygon
                className="camera-qr-polygon"
                points={overlay.polygonPoints}
              />
              <text
                className="camera-qr-label"
                x={overlay.labelX}
                y={overlay.labelY}
              >
                {qrOverlay?.qr}
              </text>
            </svg>
          ) : null}
        </>
      ) : (
        <div className="camera-placeholder">
          <div className="camera-placeholder-title">Vista de cámara</div>
          <div className="camera-placeholder-text">
            Pendiente configurar fuente MJPEG
          </div>
        </div>
      )}

      <div className="camera-footer">{footerText}</div>
    </div>
  );
}

function normalizeCmdData(value: unknown): CommandPayload | null {
  if (!isRecord(value)) {
    return null;
  }

  if ("payload" in value && isRecord(value.payload)) {
    return value.payload as CommandPayload;
  }

  return value as CommandPayload;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }

  return value.toFixed(digits);
}

function formatMaybeNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }

  return value.toFixed(2);
}

function formatDateTime(value: number | null | undefined): string {
  if (!value) {
    return "--";
  }

  return new Date(value).toLocaleString();
}

function formatStatus(value: string | null | undefined): string {
  if (!value) {
    return "--";
  }

  return value.charAt(0).toUpperCase() + value.slice(1);
}

function toNumber(value: unknown): number {
  if (typeof value === "number" && !Number.isNaN(value)) {
    return value;
  }

  return 0;
}

function toGaugePercent(value: number): number {
  return clamp(Math.abs(value) * 100, 0, 100);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export default App;