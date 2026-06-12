# ADR 0005 — Frontend: React + TypeScript + Vite

- Estado: Aceptado (2026-06-12)

## Contexto

Se evaluaron Vue 3 y React para la SPA del NOC. Ambos cubren los requisitos
(dashboard denso, mapa, tiempo real). El usuario confirmó React.

## Decisión

- **React 18 + TypeScript + Vite**.
- Mapa con **Leaflet** (react-leaflet) sobre OpenStreetMap.
- Gráficas con **ECharts**.
- Estado de servidor con **TanStack Query**; eventos en vivo vía WebSocket.
- Cliente REST tipado generado a partir del OpenAPI del backend.
- Servido en producción por **nginx**, que además actúa de reverse proxy único
  hacia `/api` y `/ws`.

## Consecuencias

- Un único punto de entrada HTTP (nginx) simplifica TLS y CORS.
- El tipado extremo a extremo (OpenAPI → cliente TS) protege el contrato API.
