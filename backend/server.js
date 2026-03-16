const express = require("express");
const http = require("http");
const cors = require("cors");
const mqtt = require("mqtt");
const { Server } = require("socket.io");

const app = express();

app.use(cors());

const server = http.createServer(app);

const io = new Server(server, {
  cors: {
    origin: "*"
  }
});

const mqttClient = mqtt.connect("mqtt://mosquitto:1883");

mqttClient.on("connect", () => {
  mqttClient.subscribe("robot/position");
});

mqttClient.on("message", (topic, message) => {
  const data = JSON.parse(message.toString());
  io.emit("robotData", data);
});

server.listen(3000, () => {
  console.log("backend running");
});