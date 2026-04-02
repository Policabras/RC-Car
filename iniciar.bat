@echo off

echo 🚀 Levantando infraestructura Docker...
docker-compose up -d --build

echo ⏳ Esperando MQTT...
timeout /t 10 /nobreak

echo 🐍 Ejecutando bridge serial...
start cmd /k "py esp32-serial\bridge_final.py"

echo ⏳ Esperando backend...
timeout /t 3 /nobreak

echo 🌐 Ejecutando frontend React...
start cmd /k "cd frontend && npm run dev"

echo 🌍 Abriendo dashboard...
timeout /t 3 /nobreak
start http://localhost:5173

echo 📜 Logs Docker:
docker-compose logs -f