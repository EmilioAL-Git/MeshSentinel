# ADR 0001 — Monolito modular con pasarela desacoplada

- Estado: Aceptado (2026-06-12)

## Contexto

El sistema combina una conexión stateful y frágil al nodo Meshtastic (serial/TCP/HTTP)
con una aplicación web clásica (API, auth, dashboard). La conexión al nodo es de
cliente único en la práctica y el dispositivo USB debe mapearse al contenedor.

## Decisión

Dos servicios backend independientes:

- **gateway**: posee en exclusiva la conexión al nodo central. Decodifica protobufs
  y publica eventos normalizados; consume una cola de comandos.
- **backend**: monolito modular (arquitectura hexagonal ligera: `domain` →
  `application` → `adapters`) con API REST, WebSockets, auth, alertas y auditoría.

No se adoptan microservicios: el dominio es cohesionado y el coste operativo no se
justifica para el tamaño del equipo y el hardware objetivo (incl. Raspberry Pi).

## Consecuencias

- El gateway puede reiniciarse sin afectar a la API.
- El dispositivo USB solo se mapea al contenedor gateway.
- Soporte multi-pasarela futuro sin cambios en el backend: cada gateway tiene un
  `gateway_id` y todos los eventos lo incluyen desde la v1 del contrato.
- Se necesita un bus de comunicación entre servicios (ver ADR 0003).
