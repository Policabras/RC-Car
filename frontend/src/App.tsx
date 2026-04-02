import { useEffect, useRef, useState } from "react";
import { io } from "socket.io-client";
import JSZip from "jszip";
import "./Dashboard.css";

type Punto = { x: number; y: number };

type Sesion = {
  id: number;
  fecha: string;
  puntos: number;
  imagen: string;
  csv: string;
};

function App() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [view, setView] = useState<"live" | "history">("live");
  const [connected, setConnected] = useState(false);

  const [data, setData] = useState({
    x: 0,
    y: 0,
    theta: 0
  });

  const [points, setPoints] = useState<Punto[]>([]);
  const [history, setHistory] = useState<Sesion[]>([]);
  const [notification, setNotification] = useState("");

  // =========================
  // CARGAR HISTORIAL
  // =========================
  useEffect(() => {
    const saved = localStorage.getItem("robot_history");
    if (saved) setHistory(JSON.parse(saved));
  }, []);

  // =========================
  // SOCKET
  // =========================
  useEffect(() => {
  const socket = io("http://localhost:3000", {
    transports: ["websocket"],
    upgrade: false
  });

  socket.on("connect", () => setConnected(true));
  socket.on("disconnect", () => setConnected(false));

  socket.on("robotData", (newData) => {
    setData({
      x: newData.x,
      y: newData.y,
      theta: newData.theta
    });

    setPoints(prev => [...prev, { x: newData.x, y: newData.y }]);
  });

  // ✅ ESTO ES LO IMPORTANTE
  return () => {
    socket.disconnect();
  };

}, []);

  // =========================
  // GUARDAR HISTORIAL
  // =========================
  const guardarEnHistorial = () => {
    const canvas = canvasRef.current;
    if (!canvas || points.length === 0) return;

    const imagenData = canvas.toDataURL("image/png");

    const nuevaSesion: Sesion = {
      id: Date.now(),
      fecha: new Date().toLocaleString(),
      puntos: points.length,
      imagen: imagenData,
      csv: points.map(p => `${p.x.toFixed(4)},${p.y.toFixed(4)}`).join("\n")
    };

    const nuevoHistorial = [nuevaSesion, ...history];
    setHistory(nuevoHistorial);
    localStorage.setItem("robot_history", JSON.stringify(nuevoHistorial));

    setNotification("💾 Ruta guardada");
    setTimeout(() => setNotification(""), 3000);
  };

  // =========================
  // RESET
  // =========================
  const resetMapa = () => {
    if (window.confirm("¿Deseas limpiar la trayectoria actual?")) {
      setPoints([]);
      setData({ x: 0, y: 0, theta: 0 });

      setNotification("🧹 Mapa reiniciado");
      setTimeout(() => setNotification(""), 3000);
    }
  };

  // =========================
  // DESCARGAR ZIP
  // =========================
  const descargarZipDesdeHistorial = async (sesion: Sesion) => {
    const zip = new JSZip();
    const folder = zip.folder(`reporte_${sesion.id}`);

    folder?.file("datos.txt", "X,Y\n" + sesion.csv);
    folder?.file("mapa.png", sesion.imagen.split(",")[1], { base64: true });

    const content = await zip.generateAsync({ type: "blob" });

    const link = document.createElement("a");
    link.href = URL.createObjectURL(content);
    link.download = `reporte_${sesion.id}.zip`;
    link.click();
  };

  // =========================
  // CANVAS
  // =========================
  useEffect(() => {
    if (view !== "live") return;

    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    const scale = 3;

    // trayectoria
    ctx.beginPath();
    ctx.strokeStyle = "#2dd4bf";
    ctx.lineWidth = 3;

    points.forEach((p, i) => {
      const x = centerX + p.x * scale;
      const y = centerY - p.y * scale;

      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });

    ctx.stroke();

    // robot
    const rX = centerX + data.x * scale;
    const rY = centerY - data.y * scale;

    ctx.save();
    ctx.translate(rX, rY);

    const thetaRad = (data.theta * Math.PI) / 180;
    ctx.rotate(-thetaRad);

    ctx.fillStyle = "#60a5fa";
    ctx.fillRect(-15, -10, 30, 20);

    ctx.fillStyle = "white";
    ctx.fillRect(10, -2, 8, 4);

    ctx.restore();

  }, [points, data, view]);

  // =========================
  // UI
  // =========================
  return (
    <div className="dashboard-container">
      <header className="topbar">
        <div className="title">
          <h1>Control TMR · Estación Base</h1>

          <nav style={{ marginTop: "10px" }}>
            <button className={`nav-btn ${view === "live" ? "active" : ""}`} onClick={() => setView("live")}>
              🔴 EN VIVO
            </button>
            <button className={`nav-btn ${view === "history" ? "active" : ""}`} onClick={() => setView("history")}>
              📁 HISTORIAL
            </button>
          </nav>
        </div>

        <div className="status-pill">
          <span style={{
            width: 10,
            height: 10,
            borderRadius: "50%",
            display: "inline-block",
            background: connected ? "#22c55e" : "#ef4444"
          }}></span>
          {connected ? " EN LÍNEA" : " DESCONECTADO"}
        </div>
      </header>

      {view === "live" ? (
        <main className="grid-layout">
          <section className="card map-card">
            <canvas ref={canvasRef} width={600} height={400} />
          </section>

          <section className="card stats-card">
            <h3>Telemetría</h3>

            <div>X: {data.x.toFixed(2)}</div>
            <div>Y: {data.y.toFixed(2)}</div>
            <div>Yaw: {data.theta.toFixed(1)}°</div>
            <div>Puntos: {points.length}</div>

            <button onClick={guardarEnHistorial}>💾 Guardar</button>
            <button onClick={resetMapa}>🧹 Limpiar</button>
          </section>
        </main>
      ) : (
        <main className="history-view">
          {history.map(s => (
            <div key={s.id}>
              <img src={s.imagen} width="200" />
              <p>{s.fecha}</p>
              <button onClick={() => descargarZipDesdeHistorial(s)}>
                Descargar
              </button>
            </div>
          ))}
        </main>
      )}

      {notification && <div>{notification}</div>}
    </div>
  );
}

export default App;