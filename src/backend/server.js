const express = require("express");
const http = require("http");
const cors = require("cors");
const mqtt = require("mqtt");
const { Server } = require("socket.io");

const app = express();
app.use(cors());
app.use(express.json());

const server = http.createServer(app);

const FRONTEND_URL = "http://localhost:5173";
const PORT = 3000;
const MQTT_URL = "mqtt://192.168.3.10:1883";
const DEVICE_ID = "pi_robot_01";

const io = new Server(server, {
  cors: {
    origin: FRONTEND_URL,
    methods: ["GET", "POST"],
  },
  transports: ["websocket"],
});

// ==========================
// Estado en memoria
// ==========================
const latestTelemetry = {
  system: null,
  status: null,
  actuators: null,
  cmd: null,
};

// ==========================
// MQTT
// ==========================
const mqttClient = mqtt.connect(MQTT_URL, {
  reconnectPeriod: 2000,
});

mqttClient.on("connect", () => {
  console.log(`Backend conectado a MQTT Broker: ${MQTT_URL}`);

  const topics = [
    `telemetry/${DEVICE_ID}/system`,
    `telemetry/${DEVICE_ID}/status`,
    `telemetry/${DEVICE_ID}/actuators`,
    `telemetry/${DEVICE_ID}/cmd/#`,
  ];

  mqttClient.subscribe(topics, (err) => {
    if (err) {
      console.error("Error al suscribirse a tópicos MQTT:", err.message);
      return;
    }

    topics.forEach((topic) => {
      console.log(`Suscrito al tópico: ${topic}`);
    });
  });
});

mqttClient.on("reconnect", () => {
  console.log("Reintentando conexión con MQTT...");
});

mqttClient.on("error", (err) => {
  console.error("Error MQTT:", err.message);
});

mqttClient.on("offline", () => {
  console.log("MQTT offline");
});

// ==========================
// Utilidad para detectar stream
// ==========================
function getStreamFromTopic(topic) {
  const parts = topic.split("/");

  // Esperado:
  // telemetry/pi_robot_01/system
  // telemetry/pi_robot_01/status
  // telemetry/pi_robot_01/actuators
  // telemetry/pi_robot_01/cmd/...
  if (parts.length < 3) return null;

  return {
    mainStream: parts[2],
    subStream: parts[3] || null,
  };
}

// ==========================
// Procesamiento MQTT -> Socket.io
// ==========================
mqttClient.on("message", (topic, messageBuffer) => {
  try {
    const rawMessage = messageBuffer.toString();
    const parsed = JSON.parse(rawMessage);

    const topicInfo = getStreamFromTopic(topic);

    if (!topicInfo) {
      console.warn(`Tópico no reconocido: ${topic}`);
      return;
    }

    const { mainStream, subStream } = topicInfo;

    switch (mainStream) {
      case "system":
        latestTelemetry.system = parsed;

        console.log("SYSTEM recibido:", parsed);

        io.emit("systemData", parsed);
        io.emit("telemetryData", {
          topic,
          stream: "system",
          data: parsed,
        });
        break;

      case "status":
        latestTelemetry.status = parsed;

        console.log("STATUS recibido:", parsed);

        io.emit("statusData", parsed);
        io.emit("telemetryData", {
          topic,
          stream: "status",
          data: parsed,
        });
        break;

      case "actuators":
        latestTelemetry.actuators = parsed;

        console.log("ACTUATORS recibido:", parsed);

        io.emit("actuatorsData", parsed);
        io.emit("telemetryData", {
          topic,
          stream: "actuators",
          data: parsed,
        });
        break;

      case "cmd":
        latestTelemetry.cmd = {
          topic,
          subStream,
          payload: parsed,
        };

        console.log("CMD recibido:", {
          topic,
          subStream,
          payload: parsed,
        });

        io.emit("cmdData", {
          topic,
          subStream,
          payload: parsed,
        });

        io.emit("telemetryData", {
          topic,
          stream: "cmd",
          subStream,
          data: parsed,
        });
        break;

      default:
        console.warn(`Stream no manejado: ${mainStream} | topic=${topic}`);
        break;
    }
  } catch (error) {
    console.error(`Error procesando mensaje MQTT del tópico ${topic}:`, error.message);
  }
});

// ==========================
// Endpoints opcionales
// ==========================
app.get("/api/health", (req, res) => {
  res.json({
    ok: true,
    mqttConnected: mqttClient.connected,
    deviceId: DEVICE_ID,
  });
});

app.get("/api/telemetry/latest", (req, res) => {
  res.json(latestTelemetry);
});

// ==========================
// Socket.io
// ==========================
io.on("connection", (socket) => {
  console.log("Frontend conectado:", socket.id);

  socket.emit("initialTelemetry", latestTelemetry);

  socket.on("disconnect", () => {
    console.log("Frontend desconectado:", socket.id);
  });
});

// ==========================
// Inicio servidor
// ==========================
server.listen(PORT, () => {
  console.log(`Backend activo en puerto ${PORT}`);
  console.log(`Escuchando telemetría de ${DEVICE_ID}`);
});