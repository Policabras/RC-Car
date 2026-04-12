const express = require("express");
const http = require("http");
const cors = require("cors");
const mqtt = require("mqtt");
const { Server } = require("socket.io");

const app = express();
// Habilitamos CORS para que el frontend pueda consultar la API si es necesario
app.use(cors());

const server = http.createServer(app);

// Configuración de Socket.io optimizada para evitar errores de conexión
const io = new Server(server, {
  cors: {
    origin: "http://localhost:5173", // URL de tu frontend Vite
    methods: ["GET", "POST"]
  },
  transports: ["websocket"] // Forzamos websocket para mayor estabilidad
});

// ==========================
// Variables de Estado
// ==========================
let thetaSuave = 0;

// ==========================
// Conexión MQTT (Docker)
// ==========================
// Importante: Usamos 'mosquitto' porque es el nombre del servicio en docker-compose
const mqttClient = mqtt.connect("mqtt://mosquitto:1883");

mqttClient.on("connect", () => {
  console.log("✅ Backend conectado a MQTT Broker (Mosquitto)");
  mqttClient.subscribe("robot/position", (err) => {
    if (!err) {
      console.log("📡 Suscrito al tópico: robot/position");
    }
  });
  mqttClient.subscribe("robot/qr", (err) => {
    if (!err) {
      console.log("📡 Suscrito al tópico: robot/qr");
    }
  });
});

// ==========================
// Procesamiento de Datos
// ==========================
mqttClient.on("message", (topic, message) => {
  try {
    if (topic === "robot/position") {
    // Parseamos el JSON que viene del bridge_final.py
    const raw = JSON.parse(message.toString());

    // Extraemos los valores reales. Si no existen, usamos 0 por seguridad.
    const xReal = raw.x || 0;
    const yReal = raw.y || 0;
    const thetaNuevo = raw.theta || 0;

    // Filtro de suavizado para el ángulo (Yaw)
    thetaSuave = thetaSuave * 0.9 + thetaNuevo * 0.1;

    // Creamos el objeto final con los datos REALES
    const data = {
      x: xReal,
      y: yReal,
      theta: thetaSuave
    };

    // Imprimimos en los logs de Docker para verificar
    console.log(`📩 Posición: X=${data.x}, Y=${data.y}, T=${data.theta.toFixed(4)}`);

    // Enviamos los datos al Frontend en tiempo real
    io.emit("robotData", data);
    }
    if (topic === "robot/qr") {
      console.log("QR recibido:", message.toString());

      io.emit("qrData", {
        qr: message.toString()
      });
    }

  } catch (e) {
    console.error("❌ Error al procesar JSON de MQTT:", e.message);
  }
});

// ==========================
// Gestión de Sockets
// ==========================
io.on("connection", (socket) => {
  console.log("🟢 Estación Base conectada (ID):", socket.id);

  socket.on("disconnect", () => {
    console.log("🔴 Estación Base desconectada");
  });

});


// ==========================
// Inicio del Servidor
// ==========================
const PORT = 3000;
server.listen(PORT, () => {
  console.log(`🚀 Backend del TMR activo en puerto ${PORT}`);
  console.log(`📡 Esperando datos de odometría...`);
});