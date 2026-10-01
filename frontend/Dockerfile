# La etapa de build solo genera ficheros estáticos (independientes de la arquitectura):
# se ejecuta siempre en la plataforma nativa del builder para evitar la emulación QEMU
# en el build multi-arch (npm install tardaba >20 min emulando arm64).
FROM --platform=$BUILDPLATFORM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
