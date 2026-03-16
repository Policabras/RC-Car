import { useEffect, useRef, useState } from "react";
import { io } from "socket.io-client";
import JSZip from "jszip";
import "./Dashboard.css";

const socket = io("http://localhost:3000");

function App() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [view, setView] = useState<"live" | "history">("live");
  const [data, setData] = useState({ x: 0, y: 0, theta: 0 });
  const [points, setPoints] = useState<{ x: number; y: number }[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [notification, setNotification] = useState("");

  // Cargar historial local al iniciar
  useEffect(() => {
    const saved = localStorage.getItem("robot_history");
    if (saved) setHistory(JSON.parse(saved));
  }, []);

  // Escuchar datos del WebSocket
  useEffect(() => {
    socket.on("robotData", (newData) => {
      setData(newData);
      setPoints((prev) => [...prev, { x: newData.x, y: newData.y }]);
    });
    return () => { socket.off("robotData"); };
  }, []);

  // Guardar en el historial (No bloqueante)
  const guardarEnHistorial = async () => {
    const canvas = canvasRef.current;
    if (!canvas || points.length === 0) return;

    const fecha = new Date().toLocaleString();
    const imagenData = canvas.toDataURL("image/png");
    
    const nuevaSesion = {
      id: Date.now(),
      fecha,
      puntos: points.length,
      imagen: imagenData,
      csv: points.map(p => `${p.x.toFixed(4)},${p.y.toFixed(4)}`).join('\n')
    };

    const nuevoHistorial = [nuevaSesion, ...history];
    setHistory(nuevoHistorial);
    localStorage.setItem("robot_history", JSON.stringify(nuevoHistorial));

    setNotification("✅ Prueba guardada en el historial");
    setTimeout(() => setNotification(""), 3000);
  };

  // Limpiar el mapa para una nueva prueba
  const resetMapa = () => {
    if (window.confirm("¿Deseas limpiar la trayectoria actual?")) {
      setPoints([]);
      setNotification("🧹 Mapa reiniciado");
      setTimeout(() => setNotification(""), 3000);
    }
  };

  // Descargar ZIP desde el historial
  const descargarZipDesdeHistorial = async (sesion: any) => {
    const zip = new JSZip();
    const folder = zip.folder(`reporte_${sesion.id}`);
    folder?.file("datos_odometria.txt", "X,Y\n" + sesion.csv);
    folder?.file("mapa_visual.png", sesion.imagen.split(',')[1], { base64: true });
    
    const content = await zip.generateAsync({ type: "blob" });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(content);
    link.download = `reporte_robot_${sesion.id}.zip`;
    link.click();
  };

  // Lógica de Dibujo del Canvas
  useEffect(() => {
    if (view !== "live") return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    const scale = 40;

    // Dibujar Trayectoria
    ctx.beginPath();
    ctx.strokeStyle = "#2dd4bf";
    ctx.lineWidth = 3;
    ctx.lineJoin = "round";
    points.forEach((p, i) => {
      const x = centerX + p.x * scale;
      const y = centerY - p.y * scale;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Dibujar Robot
    const rX = centerX + data.x * scale;
    const rY = centerY - data.y * scale;
    ctx.save();
    ctx.translate(rX, rY);
    ctx.rotate(-data.theta);
    ctx.fillStyle = "#60a5fa";
    ctx.fillRect(-15, -10, 30, 20);
    ctx.fillStyle = "white";
    ctx.fillRect(10, -2, 8, 4);
    ctx.restore();
  }, [points, data, view]);

  return (
    <div className="dashboard-container">
      <header className="topbar">
        <div className="title">
          <h1>Control TMR · Estación Base</h1>
          <nav style={{ marginTop: '10px' }}>
            <button className={`nav-btn ${view === 'live' ? 'active' : ''}`} onClick={() => setView('live')}>🔴 EN VIVO</button>
            <button className={`nav-btn ${view === 'history' ? 'active' : ''}`} onClick={() => setView('history')}>📁 HISTORIAL</button>
          </nav>
        </div>
        <div className="status-pill">
          <span className="dot"></span> {view === 'live' ? 'SISTEMA ACTIVO' : 'MODO ARCHIVO'}
        </div>
      </header>

      {view === "live" ? (
        <main className="grid-layout">
          <section className="card map-card">
            <div className="card-header"><h2>Vista de Trayectoria</h2></div>
            <div className="robot-stage">
              <div className="grid-bg"></div>
              <canvas ref={canvasRef} width={600} height={400} />
            </div>
          </section>

          <section className="card stats-card">
            <div className="card-header"><h2>Telemetría</h2></div>
            <div className="telemetry-grid">
              <div className="stat-item"><span>X</span><strong>{data.x.toFixed(2)}</strong></div>
              <div className="stat-item"><span>Y</span><strong>{data.y.toFixed(2)}</strong></div>
              <div className="stat-item"><span>Yaw</span><strong>{(data.theta * 57.2).toFixed(1)}°</strong></div>
              <div className="stat-item"><span>Puntos</span><strong>{points.length}</strong></div>
            </div>
            
            <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <button className="save-button" onClick={guardarEnHistorial}>💾 GUARDAR EN HISTORIAL</button>
              <button className="save-button" onClick={resetMapa} style={{ background: 'var(--panel-2)' }}>✨ LIMPIAR MAPA</button>
            </div>
          </section>
        </main>
      ) : (
        <main className="history-view">
          {history.length === 0 ? <p style={{ textAlign: 'center', color: 'var(--muted)' }}>No hay pruebas guardadas aún.</p> : (
            <div className="history-grid">
              {history.map(sesion => (
                <div className="card history-card" key={sesion.id}>
                  <img src={sesion.imagen} alt="Mapa" style={{ width: '100%', borderRadius: '10px', background: '#070c18' }} />
                  <div style={{ marginTop: '15px' }}>
                    <p style={{ fontSize: '0.9rem' }}><strong>📅 Fecha:</strong> {sesion.fecha}</p>
                    <p style={{ fontSize: '0.9rem', marginBottom: '15px' }}><strong>📍 Puntos:</strong> {sesion.puntos}</p>
                    <button className="save-button" onClick={() => descargarZipDesdeHistorial(sesion)}>📦 Descargar ZIP</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </main>
      )}

      {notification && <div className="toast-notification">{notification}</div>}
    </div>
  );
}

export default App;