# Módulo 1 — Administración Remota: Documento de Diseño Técnico

- Estado: **Borrador para revisión** (v1, 2026-07-08)
- Alcance: solo diseño. Sin código, migraciones, endpoints ni pantallas.
- Base: v0.4.0-beta (`3903abc`), librería oficial `meshtastic` (Python), firmware ≥ 2.5 (PKC).

---

## 1. Visión y principios

Administrar una red Meshtastic completa desde el NOC de forma **segura, auditable
y honesta con el medio físico**: LoRa ofrece decenas de bytes/segundo compartidos
por toda la malla, con duty cycle regulatorio (EU_868). Principios:

1. **La malla es el recurso escaso.** Toda operación remota pasa por una cola con
   rate limiting global; nunca se habla con N nodos en paralelo.
2. **Delivered ≠ Applied.** Un ACK de enrutado no garantiza que la configuración
   se aplicó. El sistema modela explícitamente esa incertidumbre (estados
   `awaiting_response` vs `succeeded_unconfirmed`).
3. **Todo es asíncrono para el operador.** La UI nunca bloquea esperando la malla:
   crear operación → observar su progreso (WebSocket) → consultar historial.
4. **El gateway sigue siendo el único que toca la librería** (ADR 0002/0009).
   El backend orquesta; el gateway ejecuta.
5. **Auditoría primero.** Ninguna operación se envía sin quedar registrada con
   operador, parámetros y resultado.

---

## 2. Gestión de nodos (metadatos del NOC — sin tráfico de malla)

Todo lo de esta sección vive **solo en la BD del NOC**; no genera tráfico LoRa.

| Funcionalidad | Diseño |
|---|---|
| **Favoritos** | flag por nodo. Distinguir del "favorite" del *dispositivo* (la librería ofrece `setFavorite` sobre la NodeDB del nodo central); opcionalmente sincronizable en el futuro, desactivado por defecto. |
| **Ignorados** | flag por nodo: se ocultan de listas/mapa/dashboard/alertas (con toggle "mostrar ignorados"). La telemetría **se sigue persistiendo** (ignorar es presentación, no ingesta). Ídem nota sobre `setIgnored` del dispositivo. |
| **Etiquetas** | `tags` (nombre único, color) + relación N:M `node_tags`. Libres, para clasificación ad-hoc ("solar", "cumbre", "v2.7"). |
| **Grupos** | Dos tipos: **estáticos** (membresía explícita) y **dinámicos** (regla guardada: expresión de filtro evaluada al usarse, p. ej. `hw_model=RAK4631 AND battery<50`). Un grupo puede marcarse `is_critical` (lo consumirá el Dashboard/alertas — ya previsto en Fase 3B). |
| **Búsqueda avanzada** | Un **DSL de filtro único** compartido por búsquedas, grupos dinámicos y acciones masivas: campos (`short_name`, `hw_model`, `role`, `battery`, `snr`, `hops`, `last_seen`, `tag`, `group`, `online`, `has_gps`, `firmware`) con operadores (`= != < > ~ in`). Se compila a SQL sobre las tablas existentes. |
| **Filtros persistentes** | `saved_filters` (nombre, expresión DSL, dueño). Reutilizables como alcance de acciones masivas y como definición de grupos dinámicos — un solo mecanismo, tres usos. |

**Modelo de datos propuesto** (futuras migraciones; nombres tentativos):

```
nodes                 += is_favorite BOOL, is_ignored BOOL, notes TEXT
tags                   (id, name UNIQUE, color)
node_tags              (node_id FK, tag_id FK, PK compuesta)
groups                 (id, name UNIQUE, kind static|dynamic, filter_expr NULL, is_critical)
group_members          (group_id FK, node_id FK)          -- solo grupos estáticos
saved_filters          (id, name, filter_expr, created_by)
```

---

## 3. Capacidades reales de Remote Admin (librería oficial, verificadas)

Inventario obtenido por introspección de `meshtastic.node.Node` (versión instalada)
y semántica de `AdminMessage` del firmware. Prerrequisito global: **PKC** — la
clave pública del nodo central debe estar en `security.admin_key` del nodo
objetivo (máx. 3 claves; canal "admin" legacy obsoleto). Además, toda sesión
admin remota exige un **session passkey** (`ensureSessionKey`): se obtiene con
cualquier `get`, caduca ~300 s, y es **por nodo**.

### 3.1 Inventario de operaciones

| Operación (métodos librería) | Tipo | ¿Respuesta? | ¿Asíncrona? | ¿Modifica config? | ¿Masiva? |
|---|---|---|---|---|---|
| Leer configuración (`requestConfig`, por sección: device, position, power, network, display, lora, bluetooth, security + módulos) | GET | **Sí** (respuesta AdminMessage) | Sí | No | Sí (lectura/auditoría de flota) |
| Leer canales (`requestChannels`) | GET | Sí | Sí | No | Sí |
| Leer metadatos (`getMetadata`: firmware, hw) | GET | Sí | Sí | No | Sí — *resuelve el pendiente "firmware de nodos remotos"* |
| Escribir configuración (`writeConfig` por sección) | SET | Solo ACK de ruta | Sí | **Sí** (algunas secciones **reinician** el nodo: lora, device…) | Sí, con precaución |
| Escribir canal / set de canales (`writeChannel`, `setChannels`, `setURL`) | SET | Solo ACK | Sí | **Sí** (¡puede sacar al nodo de la malla!) | Restringida (ver riesgos) |
| Transacción (`beginSettingsTransaction` / `commitSettingsTransaction`) | SET | Solo ACK | Sí | Agrupa cambios en un commit | Por nodo |
| Identidad (`setOwner`: nombres, licencia) | SET | Solo ACK | Sí | Sí | Sí |
| Posición fija (`setFixedPosition`, `removeFixedPosition`) | SET | Solo ACK | Sí | Sí | Sí |
| Hora (`setTime`) | SET | Solo ACK | Sí | No (volátil) | Sí |
| Reinicio (`reboot`, `rebootOTA`), apagado (`shutdown`) | ACCIÓN | Solo ACK | Sí | No | Sí (escalonada) |
| `factoryReset`, `resetNodeDb`, `removeNode`, `enterDFUMode` | ACCIÓN destructiva | Solo ACK | Sí | **Sí, irreversible** | **No** (solo unitaria + doble confirmación) |
| Favorito/ignorado del dispositivo (`setFavorite/removeFavorite`, `setIgnored/removeIgnored`) | SET | Solo ACK | Sí | NodeDB del nodo | Sí |
| Mensajes enlatados / ringtone (`get/set_canned_message`, `get/set_ringtone`) | GET/SET | GET sí / SET solo ACK | Sí | Sí | Sí |

### 3.2 Semántica clave

- **GET**: piden `want_response`; la respuesta llega como paquete AdminMessage
  minutos después (o nunca). Son la única confirmación fuerte.
- **SET**: el firmware no responde "aplicado". Confirmación fuerte = **GET de
  verificación posterior** (read-back). El diseño lo incorpora como paso opcional
  del pipeline (`verify=true`), al coste de duplicar tráfico.
- **Reinicios inducidos**: cambiar `lora` o `device` reinicia el nodo → el
  read-back debe esperar (delay configurable) y el nodo aparecerá offline un rato
  (el motor de alertas debe poder **suprimir** alertas del sujeto durante una
  operación — integración con Fase 3C vía `correlation_key = operation:<id>`).

---

## 4. Cola de operaciones

### 4.1 Modelo de datos propuesto

```
admin_operations
  id, batch_id FK NULL,
  target_node_id, gateway_id,
  operation_type        (config.get | config.set | channels.get | channels.set |
                         owner.set | position.set_fixed | reboot | shutdown |
                         metadata.get | factory_reset | ... registro extensible),
  params JSON,          -- payload específico validado por tipo
  status,               -- ver §4.3
  priority INT,         -- GET de flota en baja prioridad; acciones del operador en alta
  attempts INT, max_attempts INT,
  verify BOOL,          -- read-back tras SET
  timeout_seconds INT,
  result JSON NULL, error TEXT NULL,
  created_by, created_at, started_at, finished_at,
  duration_ms NULL

admin_operation_batches
  id, name, filter_expr | group_id | node_ids JSON,  -- alcance congelado (snapshot)
  operation_type, params JSON,
  status (agregado), totals JSON {pending, running, succeeded, failed, ...},
  created_by, confirmed_at, created_at, finished_at
```

El **snapshot del alcance** en el batch es deliberado: "todos los filtrados" se
resuelve a una lista concreta de nodos **en el momento de la confirmación**, y esa
lista queda auditada (el filtro puede dar otro resultado mañana).

### 4.2 Flujo de ejecución

```
Operador (UI/API)
   │ 1. POST batch (dry-run) ──► backend resuelve alcance → previsualización
   │ 2. POST confirmación     ──► crea batch + N operations (pending) + auditoría
   ▼
Backend: OperationScheduler (asyncio)
   │ 3. toma pending por prioridad, respeta rate limit global y
   │    concurrencia máx. por gateway (default: 1 en vuelo)
   │ 4. encola en Redis Stream noc:commands:<gateway_id>   (mecanismo ADR 0003 ya existente)
   ▼
Gateway: CommandConsumer (ya existe) → AdminExecutor (nuevo)
   │ 5. ensureSessionKey(node) si procede (caché ~300 s por nodo)
   │ 6. ejecuta método de la librería en to_thread, con timeout
   │ 7. publica evento de resultado en noc:events
   ▼
Backend: OperationTracker
   │ 8. actualiza estado, reintenta/expira, dispara verify (GET) si procede
   │ 9. difunde progreso por WebSocket; cierra batch al terminar sus hijos
   ▼
Historial + auditoría + (opcional) notificación por canales de Fase 3C
```

Contrato de eventos: `command.send_admin` **ya existe** en v1. Harán falta tipos
de evento de resultado (p. ej. `admin.result`) — **cambio aditivo** de contrato a
aprobar en la fase de implementación (este documento no lo modifica).

### 4.3 Máquina de estados de una operación

```
                    ┌──────────┐
        cancel ◄────│ pending  │
                    └────┬─────┘
                         │ scheduler la toma
                    ┌────▼─────┐   timeout/error de envío
        cancel ◄────│ queued   │──────────────┐
                    └────┬─────┘              │
                         │ gateway la recibe  │
                    ┌────▼─────┐              │
                    │ running  │              │
                    └────┬─────┘              │
             ┌───────────┼───────────────┐    │
   GET: resp │   SET sin verify: ACK     │    ▼
   ┌─────────▼──┐  ┌─────────────────┐ ┌─┴──────────┐   attempts<max
   │ succeeded  │  │ succeeded_      │ │ failed /   │──────────────► pending (retry,
   └────────────┘  │ unconfirmed     │ │ timeout    │                backoff exp.)
                   └───────┬─────────┘ └────────────┘   attempts=max → failed (final)
                           │ verify=true: GET read-back
                   ┌───────▼─────────┐
                   │ succeeded (si   │
                   │ coincide) /     │
                   │ verify_failed   │
                   └─────────────────┘
```

Estados: `pending, queued, running, succeeded, succeeded_unconfirmed,
verify_failed, failed, timeout, cancelled`. Terminales: los 5 últimos +
`succeeded*`. `cancelled` solo desde `pending/queued` (lo enviado a LoRa no se
puede retirar). Reintentos: backoff exponencial con jitter (reutiliza la
filosofía de ADR 0010), contador `attempts` auditado.

### 4.4 Rate limiting y escala

- **Presupuesto global de malla**: `N operaciones/minuto` (configurable, default
  conservador ~6/min) + 1 operación en vuelo por gateway. Con cientos de nodos,
  un batch de flota **tarda horas por diseño**: la UI muestra ETA estimada
  (tamaño × cadencia) en la confirmación, y los batches sobreviven a reinicios
  del backend (estado en BD, no en memoria).
- Prioridades: acciones interactivas del operador > verify > GETs de inventario.
- Multi-pasarela (futuro): el scheduler elige gateway por `nodes.gateway_id`
  (última pasarela que oyó al nodo); preparado en el modelo desde ya.

---

## 5. Acciones masivas

| Alcance | Resolución |
|---|---|
| Un nodo | operación unitaria (batch implícito de 1) |
| Varios nodos | selección multiple en UI → lista explícita |
| Un grupo | estático: membresía; dinámico: evaluación del filtro |
| Todos los filtrados | expresión DSL activa en la vista Nodos |

**Confirmación previa obligatoria** en dos pasos API (§7): `dry-run` (devuelve
lista resuelta de nodos, advertencias y ETA) → `confirm` con token del dry-run
(caduca en 5 min). Salvaguardas:

- Operaciones **destructivas** (`factory_reset`, `resetNodeDb`, `enterDFUMode`,
  `channels.set` que toque el canal primario, `lora.region`): prohibidas en
  masivo por defecto (`allow_bulk=false` en el registro de tipos) y con
  confirmación reforzada en unitario (escribir el node_id).
- **Canario opcional** en batches grandes: ejecutar sobre 1 nodo, esperar verify
  OK, y solo entonces continuar con el resto.
- Advertencia automática si la operación puede reiniciar nodos o cortar
  conectividad.

---

## 6. Historial y auditoría

Las tablas `admin_operations`/`admin_operation_batches` **son** el historial:
inmutables una vez terminales, con `created_by` (operador), parámetros, resultado
(JSON de respuesta en GETs), `duration_ms`, error y nº de intentos. Además:

- Vista API/UI filtrable por nodo, operador, tipo, estado y rango de fechas.
- Retención configurable (los GETs de inventario masivos generan volumen).
- Cada transición relevante se registra también en el log estructurado
  (`admin.op state=... id=... node=...`) para correlación con logs del gateway.

---

## 7. API REST futura (esbozo, no implementar)

```
# Metadatos de nodos (sin malla)
PUT    /api/v1/nodes/{id}/favorite          {value}
PUT    /api/v1/nodes/{id}/ignored           {value}
GET/POST/DELETE /api/v1/tags                y  PUT/DELETE /nodes/{id}/tags/{tag}
GET/POST/PATCH/DELETE /api/v1/groups        (+ GET /groups/{id}/members)
GET/POST/DELETE /api/v1/filters             (filtros guardados)
GET    /api/v1/nodes?q=<DSL>                (búsqueda avanzada)

# Administración remota
GET    /api/v1/admin/capabilities           (registro de tipos: params, allow_bulk, riesgos)
POST   /api/v1/admin/batches:dry-run        {operation_type, params, scope} → preview + token
POST   /api/v1/admin/batches                {token}  → 201 batch
GET    /api/v1/admin/batches / {id}         (progreso agregado)
POST   /api/v1/admin/batches/{id}/cancel    (cancela hijos no enviados)
GET    /api/v1/admin/operations?node=&status=&operator=&from=&to=
GET    /api/v1/admin/operations/{id}
POST   /api/v1/admin/operations/{id}/cancel
POST   /api/v1/admin/operations/{id}/retry  (re-encola una fallida)
```

Progreso en tiempo real: eventos `operation.updated` / `batch.updated` por el
WebSocket existente (origen backend, como `alert.*`).

## 8. Seguridad y permisos

- **Modelo RBAC preparado, aplicado después** (la Fase de auth sigue pendiente):
  roles `viewer` (leer todo), `operator` (metadatos + GETs remotos + acciones no
  destructivas), `admin` (todo). Permisos por **tipo de operación** en el registro
  de capacidades (`required_role`), de modo que añadir granularidad no toque el motor.
- Mientras exista un único usuario: `created_by="admin"` fijo, pero **toda** la
  cadena (API → batch → operación → auditoría) transporta ya el campo.
- Claves: el NOC nunca almacena claves privadas de nodos; la clave admin vive en
  el nodo central (gateway). Documentar el *onboarding* de `admin_key` como
  procedimiento operativo (guía tipo acceptance).
- Defensa: rate limit por usuario en la API, tokens de confirmación de un solo
  uso, y `allow_bulk`/`destructive` como propiedades del tipo, no decisiones de UI.

## 9. Frontend sin complicar la interfaz

- **Principio: la administración aparece donde ya estás.** Sin secciones nuevas
  salvo una:
  - Detalle de nodo → pestaña "Administrar" (acciones unitarias + su historial).
  - Vista Nodos → modo selección + barra de acciones ("Aplicar a 12 nodos…"),
    y chips de filtro/etiqueta/grupo reutilizando la búsqueda.
  - Nueva vista **Operaciones** (única adición a la navegación): cola en vivo,
    batches con barra de progreso, historial filtrable.
- Asistente de confirmación único (dry-run → resumen: nodos, advertencias, ETA →
  confirmar) reutilizado por unitario y masivo.
- Favoritos/ignorados/etiquetas: acciones inline (estrella, ojo, chips) en tabla
  y detalle; los ignorados desaparecen de las vistas por defecto.

## 10. Riesgos técnicos y limitaciones de Meshtastic

| # | Riesgo/Limitación | Mitigación en el diseño |
|---|---|---|
| 1 | SET sin confirmación de aplicación | estado `succeeded_unconfirmed` + read-back opcional (`verify`) |
| 2 | Session passkey por nodo, TTL ~300 s | `ensureSessionKey` con caché por nodo en el gateway; agrupar operaciones al mismo nodo |
| 3 | Cambios de `lora`/canales pueden **desconectar el nodo para siempre** | tipos marcados `destructive`, sin masivo, confirmación reforzada, canario |
| 4 | Reinicios inducidos → falsos offline y alertas | supresión de alertas por sujeto durante la ventana de operación (`correlation_key`) |
| 5 | Throughput: cientos de nodos = horas/días | rate limit explícito + ETA visible + batches persistentes y reanudables |
| 6 | Nodos dormidos (power saving) no responden | reintentos espaciados; marcar `timeout` sin agotar presupuesto de malla |
| 7 | `admin_key` no configurada en el objetivo | operación falla con error claro; futuro: sondeo de "administrabilidad" (GET metadata) cacheado por nodo |
| 8 | Librería síncrona/hilos y un solo interface | ejecutor secuencial en el gateway (1 op en vuelo), `to_thread`, timeouts duros |
| 9 | Drift de la librería entre versiones | igual que ADR 0009: solo `gateway/admin_executor` + decoder tocan la librería; registro de capacidades versionado |
| 10 | Multi-gateway: ¿quién alcanza al nodo? | scheduler enruta por `gateway_id` del último avistamiento; si falla, reintento por otra pasarela (futuro) |

## 11. Estrategia de pruebas

1. **Unitarias (sin hardware)**: máquina de estados (todas las transiciones,
   reintentos, cancelación), scheduler (prioridades, rate limit, presupuesto),
   DSL de filtros (parser → SQL), registro de capacidades (validación de params).
2. **Simulador extendido**: el `SimulatedTransport` responderá a
   `command.send_admin` con latencias/pérdidas/reinicios configurables por seed
   — permite testear e2e cola+verify+timeout sin hardware (ADR 0007).
3. **Integración con hardware**: guía de aceptación (`docs/acceptance/admin.md`)
   con un nodo real administrable: GET config, SET owner con verify, reboot,
   timeout con nodo apagado, batch de 3 nodos con canario.
4. **Caos**: reinicio del backend a mitad de batch (debe reanudar), caída del
   gateway a mitad de operación (retry), Redis reiniciado (stream persistente).
5. **CI**: todo lo anterior menos hardware, en SQLite y PostgreSQL.

## 12. Propuesta de fases de implementación (a acordar)

| Fase | Contenido | Valor |
|---|---|---|
| **M1.1** | Metadatos: favoritos, ignorados, etiquetas, notas + UI inline | inmediato, sin riesgo |
| **M1.2** | DSL de búsqueda + filtros guardados + grupos (estáticos y dinámicos) | organización de flota |
| **M1.3** | Cola de operaciones + ejecutor en gateway + `metadata.get`/`config.get` (solo lectura) + vista Operaciones | pipeline completo con riesgo mínimo; de paso, firmware remoto e inventario |
| **M1.4** | SETs no destructivos (`owner`, posición fija, favorito de dispositivo) + verify + supresión de alertas | primera escritura real |
| **M1.5** | Acciones masivas (dry-run/confirm/canario) + `reboot` escalonado | administración de flota |
| **M1.6** | Operaciones destructivas unitarias con confirmación reforzada + capacidades/`admin_key` onboarding doc | cierre del módulo |

RBAC real se implementará en la fase de autenticación (pendiente de planificar),
pero desde M1.3 toda la cadena transporta `created_by` y `required_role`.

---

*Documento para revisión conjunta. Tras su aprobación se abrirán los ADRs
correspondientes (mínimo: cola de operaciones y semántica verify; DSL de
filtros; registro de capacidades) y se planificará M1.1.*
