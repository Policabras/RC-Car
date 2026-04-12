import { useEffect, useRef, useState } from "react";
import { io, Socket } from "socket.io-client";
import JSZip from "jszip";
import "./Dashboard.css";

type Punto = { x: number; y: number };

type Sesion = {
  id: number;
  fecha: string;
  puntos: number;
  imagen: string;
  csv: string;
  qrs: string[];
};

function App() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const socketRef = useRef<Socket | null>(null);

  const [view, setView] = useState<"live" | "history">("live");
  const [connected, setConnected] = useState(false);

  const [isRecording, setIsRecording] = useState(false);
  const [clawOpen, setClawOpen] = useState(false);

  const [data, setData] = useState({ x: 0, y: 0, theta: 0 });
  const [points, setPoints] = useState<Punto[]>([]);
  const [history, setHistory] = useState<Sesion[]>([]);
  const [qrList, setQrList] = useState<string[]>([]);
  const [notification, setNotification] = useState("");

  useEffect(() => {
    const saved = localStorage.getItem("robot_history");
    if (saved) setHistory(JSON.parse(saved));
  }, []);

  useEffect(() => {
    const socket = io("http://localhost:3000", {
      transports: ["websocket"],
      upgrade: false
    });

    socketRef.current = socket;

    socket.on("connect", () => setConnected(true));
    socket.on("disconnect", () => setConnected(false));

    socket.on("robotData", (newData) => {
      setData({
        x: newData.x,
        y: newData.y,
        theta: newData.theta
      });

      if (isRecording) {
        setPoints(prev => [...prev, { x: newData.x, y: newData.y }]);
      }
    });

    // QR detectados desde backend
    socket.on("qrData", (data) => {
      console.log("QR detectado:", data.qr);
      setQrList(prev => [...prev, data.qr]);
    });

    return () => {
      socket.disconnect();
    };
  }, [isRecording]);

  const toggleClaw = () => {
    const newState = !clawOpen;
    setClawOpen(newState);

    socketRef.current?.emit("robotCommand", {
      device: "claw",
      action: newState ? "open" : "close"
    });
  };

  const guardarEnHistorial = () => {
    const canvas = canvasRef.current;
    if (!canvas || points.length === 0) return;

    const imagenData = canvas.toDataURL("image/png");

    const nuevaSesion: Sesion = {
      id: Date.now(),
      fecha: new Date().toLocaleString(),
      puntos: points.length,
      imagen: imagenData,
      csv: points.map(p => `${p.x.toFixed(4)},${p.y.toFixed(4)}`).join("\n"),
      qrs: qrList
    };

    const nuevoHistorial = [nuevaSesion, ...history];

    setHistory(nuevoHistorial);
    localStorage.setItem("robot_history", JSON.stringify(nuevoHistorial));

    setNotification("💾 Sesión guardada");
    setTimeout(() => setNotification(""), 2500);
  };

  const descargarZip = async (sesion: Sesion) => {
    const zip = new JSZip();

    zip.file("ruta.csv", sesion.csv);

    sesion.qrs.forEach((qr, i) => {
      zip.file(`qr_${i + 1}.txt`, qr);
    });

    const blob = await zip.generateAsync({ type: "blob" });

    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `sesion_${sesion.id}.zip`;
    link.click();
  };

  useEffect(() => {
    if (view !== "live") return;

    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    const scale = 5;

    // Trayectoria
    ctx.beginPath();
    ctx.strokeStyle = "#2dd4bf";
    ctx.lineWidth = 2;

    points.forEach((p, i) => {
      const x = centerX + p.x * scale;
      const y = centerY - p.y * scale;

      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });

    ctx.stroke();

    // Robot
    const rX = centerX + data.x * scale;
    const rY = centerY - data.y * scale;

    ctx.save();
    ctx.translate(rX, rY);
    ctx.rotate(-(data.theta * Math.PI) / 180);

    ctx.fillStyle = "#60a5fa";
    ctx.fillRect(-12, -8, 24, 16);

    ctx.fillStyle = "white";
    ctx.fillRect(8, -2, 6, 4);

    ctx.restore();

  }, [points, data, view]);

  return (
    <div className="dashboard-container">
      <header className="topbar">
        <div className="title">
          <h1>TMR Control Station</h1>

          <nav style={{ marginTop: "10px" }}>
            <button
              className={`nav-btn ${view === "live" ? "active" : ""}`}
              onClick={() => setView("live")}
            >
              EN VIVO
            </button>

            <button
              className={`nav-btn ${view === "history" ? "active" : ""}`}
              onClick={() => setView("history")}
            >
              HISTORIAL
            </button>
          </nav>
        </div>

        <div className="status-pill">
          <span className={`dot ${connected ? "online" : "offline"}`}></span>
          {connected ? "CONECTADO" : "DESCONECTADO"}
        </div>
      </header>

      {view === "live" ? (
        <main className="dashboard-grid">

          <div className="visual-section">

            <section className="card camera-card">
              <div className="card-header">
                <h3>Cámara en Tiempo Real</h3>
              </div>

              <div className="camera-container">
                <img
                  src="http://localhost:5000/video_feed"
                  alt="Transmisión"
                  style={{ width: "100%" }}
                  onError={(e) => {
                    (e.target as HTMLImageElement).src =
                      "http://localhost:5000/video_feed";
                  }}
                />
              </div>
            </section>

            <section className="card map-card">
              <div className="card-header">
                <h3>Vista de trayectoria</h3>
              </div>

              <div className="robot-stage">
                <div className="grid-bg"></div>
                <canvas ref={canvasRef} width={600} height={400} />
              </div>
            </section>

          </div>

          <aside className="telemetry-card card">

            <div className="card-header">
              <h3>Panel de Control</h3>
            </div>

            <div style={{ display: "flex", gap: "10px", marginBottom: "20px" }}>

              <button
                className="save-button"
                onClick={() => setIsRecording(!isRecording)}
                style={{
                  backgroundColor: isRecording ? "#ef4444" : "#22c55e"
                }}
              >
                {isRecording ? "⏹ DETENER" : "▶ INICIAR"}
              </button>

              <button
                className="save-button"
                onClick={toggleClaw}
                style={{
                  backgroundColor: clawOpen ? "#f59e0b" : "#3b82f6"
                }}
              >
                {clawOpen ? "🦾 CERRAR GARRA" : "👐 ABRIR GARRA"}
              </button>

            </div>

            <div className="telemetry-grid">
              <div className="stat-item"><span>X</span><strong>{data.x.toFixed(2)}</strong></div>
              <div className="stat-item"><span>Y</span><strong>{data.y.toFixed(2)}</strong></div>
              <div className="stat-item"><span>Yaw</span><strong>{data.theta.toFixed(1)}°</strong></div>
              <div className="stat-item"><span>Puntos</span><strong>{points.length}</strong></div>
            </div>

            <div style={{ marginTop: 20, display: "flex", gap: "10px" }}>
              <button className="save-button secondary" onClick={guardarEnHistorial}>
                💾 Guardar
              </button>

              <button className="save-button secondary" onClick={() => setPoints([])}>
                🧹 Limpiar
              </button>
            </div>

          </aside>

        </main>
      ) : (
        <main className="history-grid">
          {history.map((s) => (
            <div className="card" key={s.id}>
              <img src={s.imagen} width="100%" alt="Ruta" />
              <p>{s.fecha}</p>

              <button
                className="save-button"
                onClick={() => descargarZip(s)}
              >
                Descargar ZIP
              </button>
            </div>
          ))}
        </main>
      )}

      {notification && (
        <div className="toast-notification">
          {notification}
        </div>
      )}
    </div>
  );
}

export default App;