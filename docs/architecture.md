# Meshtastic NOC — Arquitectura base

Versión 1.0 — aprobada el 2026-06-12. Las decisiones individuales se registran en
`docs/adr/` (los ADR prevalecen sobre este resumen si divergen).

## Visión

Plataforma profesional de administración y monitorización de redes Meshtastic,
desplegada con Docker Compose (amd64/arm64). Principio rector: **el NOC es un
observador pasivo por defecto** — LoRa ofrece muy poco ancho de banda y duty cycle
limitado (EU_868), por lo que la información llega por difusión periódica de los
nodos y las acciones activas (admin, traceroute) se encolan, espacian y auditan.

## Servicios

| Servicio | Rol |
|---|---|
| gateway | Conexión exclusiva al nodo central (serial/TCP/HTTP/simulada). Decodifica protobufs y publica eventos v1; consume cola de comandos. Único módulo que importa la librería `meshtastic`. |
| backend | Monolito modular FastAPI (`domain` → `application` → `adapters`): API REST versionada, WebSockets, auth/RBAC, alertas, auditoría, persistencia. |
| frontend | React + TypeScript + Vite, servido por nginx (punto único de entrada, proxy de `/api` y `/ws`). |
| postgres | Base de datos recomendada (SQLite soportado vía `NOC_DATABASE_URL`). |
| redis | Pub/Sub de eventos (`noc:events`) + Streams de comandos (`noc:commands:<gateway_id>`) + caché. |

## Flujos

- **Eventos**: gateway → Redis pub/sub → backend (persiste + evalúa alertas) → WebSocket → frontend.
- **Comandos**: frontend → API REST → auditoría + Redis Stream → gateway → malla LoRa → ACK → evento de resultado.

## Contrato de eventos

`shared/events/` es la fuente de verdad (JSON Schema, versionado). Todo evento
lleva `gateway_id` desde v1 para soporte multi-pasarela futuro.

## Decisiones confirmadas

Gateway desacoplado; Redis como bus/cola; FastAPI; React+TS; Compose; diseño
multi-pasarela; pasarela simulada desde Fase 0; PostgreSQL recomendado y SQLite
soportado; firmware objetivo = última estable; región EU_868; escala decenas→cientos
de nodos; notificaciones webhook+ntfy primero (arquitectura extensible a
Telegram/email); RBAC preparado aunque inicialmente haya un solo admin; MQTT fuera
del alcance inicial.

## Fases

0. Cimientos (esqueleto, Compose, contrato v1, simulador) — **esta entrega**
1. Observabilidad pasiva (transportes reales, registry, ingesta, API lectura)
2. NOC visual (mapa, dashboard, históricos, favoritos/ignorados)
3. Seguridad (auth, RBAC, auditoría, TLS)
4. Administración remota (PKC admin keys, acciones unitarias)
5. Escala (grupos, acciones masivas, alertas con notificaciones, tracks geográficos)
6. Madurez (multi-pasarela, retención/agregación, MQTT opcional)

## Riesgos clave

- Remote admin requiere `admin_key` (PKC, firmware ≥2.5) en cada nodo gestionado.
- La API del nodo es de cliente único: el gateway posee la conexión en exclusiva.
- Acciones masivas sobre LoRa son lentas y sin garantía de ACK: cola con estados
  por nodo (pendiente/enviado/confirmado/fallido) y rate limiting.
- Re-enumeración USB en Docker: ver `docs/operations/usb.md`.
