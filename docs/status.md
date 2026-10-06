# Estado del proyecto

Resumen público del estado de MeshSentinel, módulo a módulo. Este documento
se actualiza cuando se cierra una fase o módulo; para el detalle de cada
decisión ver el ADR correspondiente en `docs/adr/`.

## Infraestructura base

| Pieza | Estado |
|---|---|
| Gateway desacoplado (USB / TCP / HTTP / MQTT / simulado, base de transporte común) | Implementado — ADR 0001, 0002, 0009, 0010, 0023, 0032 |
| Contrato de eventos versionado (`shared/events/`) | Implementado — ADR 0006 |
| Bus de eventos y colas (Redis pub/sub + Streams por pasarela) | Implementado — ADR 0003 |
| Persistencia (SQLAlchemy, Postgres recomendado / SQLite soportado) | Implementado — ADR 0004 |
| Node Registry, series de posiciones/telemetría (append-only) | Implementado |
| API REST + WebSocket | Implementado |
| `/system/health`, `/system/version` | Implementado |
| Autenticación, roles (admin/gestor/usuario), tokens API | Implementado — ADR 0024, 0029, 0035 |
| Lanzador de contenedores de pasarela | Implementado — ADR 0028 |
| Retención de datos, copias programadas, resumen periódico | Implementado — ADR 0030, 0034 |

## Módulos funcionales

| Módulo | Qué hace | Estado |
|---|---|---|
| Mapa e inventario de nodos | Vista de mapa con clustering, marcadores por estado | Implementado (fase 2A), integrado luego en el Centro de Operaciones |
| Dashboard NOC | Agregados de la malla, nodos críticos, umbrales | Implementado (fase 3B), integrado luego en el Situation Center |
| Motor de alertas | Reglas (batería baja, nodo desconectado, SNR degradado, pasarela caída), reconciliación, ciclo firing→acknowledged→resolved, reglas por grupo y 20+ tipos, proveedores webhook/ntfy/Telegram/Apprise (ADR 0025, 0034, 0035) | Implementado (fase 3C) — ACK ahora también desde la propia vista de Alertas |
| M1 — Administración remota | Lecturas (metadata/config), SETs verificados (owner, posición fija), editor completo de config/module_config por introspección de protobufs | Implementado |
| M1.2 — Organización de nodos | Favoritos/ignorados locales, etiquetas, grupos, búsqueda avanzada (DSL de filtros) | Implementado |
| M2 — Batch Engine | Lotes sobre varios nodos: dry-run, ejecución, pausa/cancelación, progreso y ETA | Implementado |
| M3 — Perfiles de configuración | Plantillas versionadas e inmutables, diff contra el nodo real, sincronización vía batch | Implementado |
| M4 — Favoritos/ignorados remotos | Gestión de las listas de favoritos/ignorados del propio dispositivo, más `contact.add`/`SharedContact` | Implementado (con 6 erratas de campo documentadas y corregidas en ADR 0019) |
| M5 — Gestión de gateways | Alta/baja/configuración de pasarelas desde la app (sin depender de `.env`), descubrimiento, prueba de conexión | Implementado |
| M6 — Multi-Gateway funcional | Visibilidad N:M nodo↔pasarela, estadísticas de redundancia, enrutado de operaciones a una pasarela sana al encolar (sin failover) | Implementado (M6.1/M6.2/M6.7/M6.8). **Pendiente**: rate limit por pasarela (hoy es global), ranking completo de selección de pasarela por prioridad/saltos/SNR/recencia (hoy es "primer candidato sano"), regla de alerta de enlace obsoleto |
| Grupo activo / contexto de grupo | Clasificación de nodos (pasarela/infraestructura/fijo/usuario), agrupación en sitios, malla activa que acota la interfaz | Implementado |
| Registro de actividad (Actividad 2.0) | Una entrada por paquete decodificado, en lenguaje de operador, con detalle técnico plegable; narra también hechos derivados (reinicio, nodo nuevo, cambio de identidad) | Implementado — tercera revisión de diseño, ver `docs/design/actividad-2.0-registro-por-paquete.md` |
| Trazas de la red real y topología | Trazas y NeighborInfo persistidos, mapa 3D, capas de malla/rutas/cobertura (ADR 0031, 0035). Pendiente: barrido activo y dibujado del grafo acumulado | Parcial |
| JenTastic-Nexus | Control de nodos con firmware custom por comandos de texto (ADR 0027) | Implementado |
| Identidad de nodos 2.8 | Detección de cambio de node_id y fusión manual (ADR 0034) | Implementado |
| Consola / identidad de producto (v0.7 → v0.9) | Rediseño completo del frontend: riel de navegación (NavRail), Inspector global, Focus, capas de mapa, Situation Center, Flota, Trabajos | Implementado |

## Explícitamente fuera de alcance por ahora

- Selección "inteligente" de pasarela para administración remota (override →
  `preferred_gateway_id` → ranking por prioridad/saltos/SNR/RSSI/recencia →
  fallback) — diseñado en `docs/roadmap.md`, no implementado.
- Límite de tasa de administración remota por pasarela (hoy es global entre
  todas las pasarelas).
- Correlación de alertas.
- Notificaciones por email.
- Barrido activo de traceroute y grafo acumulado dibujado (`docs/roadmap.md` §2).
- Failover automático de pasarela tras fijarse en una operación.
- MQTT como fuente bidireccional (hoy solo ingesta).

## Deuda técnica conocida

- El tamaño de algunas vistas de frontend heredadas (`ProfilesView.tsx`,
  parte de `client.ts`) y la falta de tests de frontend siguen pendientes
  (decisión consciente de posponerlos, ver auditoría técnica pre-M6).
- Convenciones de API no unificadas del todo (mezcla de verbos PUT/PATCH/
  POST) y transacciones commit-en-router vs. commit-en-servicio
  inconsistentes en algunos endpoints antiguos.
- El bundle de producción solo separa ECharts y las vistas 3D (carga diferida); el resto sigue en un chunk principal.
