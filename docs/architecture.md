# MeshSentinel (meshtastic-noc) — Arquitectura base

Versión 1.0 — aprobada el 2026-06-12, actualizada para reflejar el estado
vigente del proyecto. Las decisiones individuales se registran en
`docs/adr/` (los ADR prevalecen sobre este resumen si divergen). Para saber
qué módulos funcionales existen hoy sobre esta base, ver `docs/status.md`;
el plan de "Fases" original de este documento (§Fases) fue sustituido en la
práctica por un desarrollo por módulos (M1–M6) y, en el frontend, por tres
rediseños sucesivos de la interfaz (v0.7 → v0.8 → v0.9) — ninguno de los dos
cambió las decisiones de este documento, solo lo que se construyó encima.

## Visión

Plataforma profesional de administración y monitorización de redes Meshtastic,
desplegada con Docker Compose (amd64/arm64). Principio rector: **el NOC es un
observador pasivo por defecto** — LoRa ofrece muy poco ancho de banda y duty cycle
limitado (EU_868), por lo que la información llega por difusión periódica de los
nodos y las acciones activas (admin, traceroute) se encolan, espacian y auditan.

## Servicios

| Servicio | Rol |
|---|---|
| gateway | Conexión exclusiva al nodo central (USB, TCP o simulada — **no existe transporte HTTP**; los tres transportes reales comparten una base común, ver ADR 0023). Decodifica protobufs y publica eventos v1; consume cola de comandos. Único módulo que importa la librería `meshtastic`. |
| backend | Monolito modular FastAPI (`domain` → `application` → `adapters`): API REST versionada, WebSockets, motor de alertas, motor de operaciones/lotes remotos, persistencia. Auth/RBAC sigue sin implementar (preparado en el diseño, no construido). |
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

## Fases (histórico — plan original de Fase 0)

Plan de fases tal como se aprobó al inicio del proyecto. En la práctica, tras
la Fase 3 el desarrollo pasó a organizarse por **módulos funcionales**
(M1 Administración Remota, M2 Batch Engine, M3 Perfiles de Configuración, M4
Favoritos/Ignorados remotos, M5 Gestión de Gateways, M6 Multi-Gateway) y,
después, por versiones de rediseño de frontend (v0.7 → v0.8 → v0.9). Ver
`docs/status.md` para el estado real módulo a módulo.

0. Cimientos (esqueleto, Compose, contrato v1, simulador) — completada
1. Observabilidad pasiva (transportes reales, registry, ingesta, API lectura) — completada
2. NOC visual (mapa, dashboard, históricos, favoritos/ignorados) — completada
3. Seguridad — **parcial**: se implementó el motor de alertas (3C); auth/RBAC/TLS
   se pospusieron y siguen sin implementar
4. Administración remota — completada como módulos M1/M4 (sin PKC admin keys
   explícitas gestionadas por la UI; ver ADR 0013/0019)
5. Escala — completada como módulos M2/M3 (grupos, batches, perfiles);
   notificaciones siguen limitadas a webhook/ntfy, sin Telegram/email
6. Madurez — **parcial**: Multi-Gateway funcional implementado (M6, sin la
   selección "inteligente" de pasarela ni el rate limit por pasarela
   diseñados — ver `docs/roadmap.md`); retención/agregación y MQTT no
   implementados

## Riesgos clave

- Remote admin requiere `admin_key` (PKC, firmware ≥2.5) en cada nodo gestionado.
- La API del nodo es de cliente único: el gateway posee la conexión en exclusiva.
- Acciones masivas sobre LoRa son lentas y sin garantía de ACK: cola con estados
  por nodo (pendiente/enviado/confirmado/fallido) y rate limiting.
- Re-enumeración USB en Docker: ver `docs/operations/usb.md`.
