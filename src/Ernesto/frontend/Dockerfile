FROM node:20

WORKDIR /app

# Copiamos los archivos de configuración
COPY package.json ./
# Instalamos las dependencias
RUN npm install

# Copiamos el resto del código
COPY . .

# Exponemos el puerto de Vite
EXPOSE 5173

# Comando para arrancar en modo desarrollo
CMD ["npm", "run", "dev", "--", "--host"]