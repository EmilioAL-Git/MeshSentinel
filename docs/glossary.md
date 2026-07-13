# Glosario

Vocabulario canónico de MeshSentinel. Usar estos términos en documentación,
código de cara al operador y comunicación con el usuario — evitar sinónimos
o nombres de fases anteriores (columna "Antes se llamaba").

| Término | Qué es | Antes se llamaba |
|---|---|---|
| **Centro** | Vista por defecto de la consola: panel de situación + mapa en vivo + consola lateral (Actividad/Trabajos/Alertas). Sustituye a lo que antes eran las pestañas "Dashboard" y "Mapa" por separado — hoy es una sola vista. | Dashboard, Mapa, Centro de Operaciones |
| **Flota** | Listado denso de todos los nodos con KPIs, filtros y selección para lotes. | Nodos, tabla de nodos |
| **Inspector** | Cajón de detalle global que se abre para cualquier nodo desde cualquier vista. Nunca navega a una página distinta. | NodeDetail, panel de detalle, popup del mapa |
| **Focus** | Modo que fija un nodo como contexto: atenúa el resto del mapa (salvo alertas activas) y prioriza su actividad/trabajos. Distinto de simplemente **seleccionar** un nodo — Focus solo se activa desde el botón ◎ del Inspector. | — |
| **Grupo** / **Sitio** | Conjunto de nodos agrupados (manual o por criterio); el **grupo activo** acota el resto de la interfaz a esos nodos, con "Toda la red" como escape. | — |
| **Gateway** / **Pasarela** | Proceso que conecta con un nodo Meshtastic físico (USB, TCP o simulado) y traduce la malla LoRa al resto del sistema. Identidad estable por `gateway_id`. | — |
| **Enlaces** | Vista de gestión de pasarelas (rack de módulos: transporte, estado, historial). El identificador interno (`gateways`) no cambió, solo la etiqueta visible. | Gateways (como nombre de pestaña) |
| **Trabajos** | Vista unificada de operaciones remotas y lotes: en ejecución, en cola, que requieren intervención, historial. | Operaciones + Batches (dos pestañas separadas) |
| **Operación** | Una acción remota sobre un nodo (lectura o escritura) que pasa por la cola persistente, con reintentos y — si aplica — verificación de lectura. | — |
| **Batch** / **Lote** | Una operación aplicada a varios nodos a la vez, con previsualización (dry-run), progreso y ETA. Vive dentro de la vista Trabajos, ya no tiene pestaña propia. | — |
| **Alertas** | Vista de triaje de condiciones de alerta activas/resueltas, con reconocimiento (ACK) en línea. | — |
| **Perfiles** | Plantillas de configuración versionadas que se comparan y sincronizan contra nodos reales. | — |
| **Config** | Editor de `config`/`module_config` de un nodo, generado desde los protobufs oficiales. | Configuración |
| **Registro** | Diario cronológico de eventos de la malla: una entrada por paquete decodificado, en lenguaje de operador. | Actividad, consola de actividad |
| **Multi-Gateway** | Capacidad de que varias pasarelas vean el mismo nodo (relación N:M), con estadísticas de redundancia y enrutado de operaciones a una pasarela sana. | — |

## Convenciones de escritura

- El nombre del producto es **MeshSentinel**; el repositorio se sigue
  llamando `meshtastic-noc` y no hace falta cambiarlo.
- "Nodo" es cualquier dispositivo Meshtastic visto por la malla; "pasarela"/
  "gateway" es específicamente el nodo al que el proceso gateway está
  conectado directamente.
- No usar "NodeInfo" para referirse a la operación de administración remota
  `contact.add`/`SharedContact` — son mecanismos distintos del protocolo
  (ver ADR 0019 §4). "NodeInfo" solo describe el paquete de difusión normal
  de identidad (`NODEINFO_APP`).
- "Confirmado"/"Pendiente"/"Enviado"/"Error" es el vocabulario de operador
  para operaciones ack-only (favoritos/ignorados remotos); no usar
  "verificado" ni "succeeded_unconfirmed" de cara al operador — esos son
  términos técnicos internos que sí aparecen en la vista general de Trabajos
  para operaciones que sí tienen verificación de lectura real.
