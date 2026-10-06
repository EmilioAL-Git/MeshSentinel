# MeshSentinel

Plataforma NOC (Network Operations Center) para redes **Meshtastic**: observa
la malla LoRa en tiempo real, organiza la flota de nodos, administra
configuración remota y alerta ante anomalías, todo desde una única consola
web pensada para operar la red, no para navegar entre pantallas.

## Qué problema resuelve

Meshtastic da malla LoRa lista para usar, pero no herramientas de operación:
sin un NOC, saber qué nodos están vivos, quién ve a quién, si una pasarela se
cayó o si a un sensor le queda batería exige leer logs o abrir la app móvil
nodo a nodo. MeshSentinel agrega esa información en un único sitio y añade lo
que la app oficial no ofrece: alertas automáticas, cambios de configuración
remotos con verificación de lectura, operaciones sobre grupos de nodos, y
redundancia real cuando varias pasarelas ven la misma malla.

El diseño respeta las limitaciones físicas de LoRa (EU_868: ancho de banda
mínimo, duty cycle limitado): **el NOC es un observador pasivo por defecto**.
Nada de polling activo — la información llega por difusión periódica de los
propios nodos, y cualquier acción (lectura remota, cambio de configuración)
se encola, se espacia con límite de tasa y queda auditada.

## Para quién está pensado

Para quien opera una red Meshtastic real más allá de un puñado de nodos de
prueba: comunidades, despliegues de emergencia/resiliencia, sensórica
distribuida — cualquier escenario con varias pasarelas y decenas o cientos de
nodos donde hace falta saber, de un vistazo, el estado de la malla y poder
actuar sobre ella sin tocar cada dispositivo a mano.

## Estado actual

Funcionalidades realmente implementadas hoy (no aspiracionales):

- **Centro de Operaciones** — vista por defecto: panel de situación (semáforo
  de salud, cola única de atención con alertas y ACK en línea, estado de
  pasarelas), mapa en vivo con pulsos de actividad y consola lateral con
  Actividad/Trabajos siempre montada.
- **Mapa como centro operativo** — capas activables: estado, calidad de señal,
  redundancia, tipo de nodo, enlaces nodo↔pasarela, malla real nodo↔nodo
  (NeighborInfo persistido), rutas de traceroute, traza GPS, cobertura por
  pasarela y medida, posiciones estimadas. El grupo activo filtra el mapa.
- **Mapa 3D de trazas** y **Herramientas** (hub con historial de trazas,
  calculador de cobertura 3D y administración remota).
- **Flota** — roster denso y virtualizado con KPIs, filtros avanzados (DSL),
  medidor de batería, barras de señal, favoritos personales/etiquetas/grupos/
  ignorados, insignias de identidad, y selección masiva para lanzar lotes.
- **Grupos y contexto de grupo activo** — clasificación de nodos (pasarela,
  infraestructura, fijo, usuario), "sitios" y una malla activa que acota la
  interfaz (o "Toda la red" como escape).
- **Inspector** — cajón de detalle global para cualquier nodo: cabecera vital,
  acciones rápidas (lecturas, traceroute activo), histórico y resumen 24 h con
  gráficas, favoritos/ignorados remotos, observaciones por pasarela.
- **Focus** — fijar un nodo como contexto: atenúa el mapa salvo alertas y
  prioriza su actividad y trabajos.
- **Motor de alertas** — 20+ tipos de regla (batería, offline, SNR, pasarela
  caída/sorda, redundancia, temperatura, utilización de canal, pérdida de
  posición, enlaces vecinos, claves duplicadas/débiles, nodo charlatán,
  geovalla, asimetría de enlace…), ámbito global o por grupo, severidad,
  ciclo firing → acknowledged → resolved, y notificación multi-proveedor
  (webhook, ntfy, Telegram, Apprise) a través de canales lógicos.
- **Administración remota** — lectura de metadata/config, SETs con verificación
  de lectura (GET→SET→GET), editor completo de `config`/`module_config`
  generado desde los protobufs, favoritos/ignorados remotos con sincronización,
  traceroute activo; cola persistente, límite de tasa y reintentos.
- **Perfiles de configuración** — plantillas versionadas e inmutables,
  comparación por diferencias y sincronización masiva.
- **Trabajos (batches)** — dry-run, confirmación explícita, progreso/ETA en
  vivo, pausa/cancelación, reparto automático entre pasarelas.
- **Gestión de pasarelas** — desde la propia app, sin tocar `.env`:
  contenedores creados/destruidos por un **lanzador** dedicado, o pasarelas
  externas registradas a mano. Transportes USB, TCP, HTTP, MQTT (solo
  ingesta) y simulado; modo solo recepción; **nodo virtual** (servidor TCP que
  permite conectar la app oficial a través de la pasarela).
- **Multi-Gateway** — un nodo visto por varias pasarelas (N:M), estadísticas de
  redundancia, enrutado de cada operación a una pasarela sana (con selección
  manual por operación).
- **Identidad de nodos** — detecta el cambio de node_id de firmware 2.8 y
  permite fusionar historial de forma manual y confirmada.
- **Registro de actividad persistente** — un paquete = una entrada en lenguaje
  de operador, con búsqueda de servidor, filtros, histórico paginado y detalle
  técnico plegado.
- **Chat** y diagnóstico de entrega (heard-by).
- **JenTastic-Nexus** — módulo opcional para nodos con firmware custom:
  catálogo de ~190 comandos de texto, detección pasiva/activa, cola de
  operaciones, difusión con respuestas por nodo y consola interpretada.
- **Estadísticas** — récords de la malla con rankings completos.
- **Seguridad y usuarios** — autenticación por sesión (cookie) y tokens API
  Bearer, roles admin/gestor/usuario, espacio personal (favoritos y grupo
  propios), registro de accesos. Sin administrador creado la plataforma queda
  en modo abierto.
- **Datos** — retención configurable por tipo, copias lógicas programadas,
  resumen periódico por los proveedores de notificación, URLs compartibles
  para cada vista y uso adaptado a móvil.

Lo que **no** está implementado todavía (ver `docs/roadmap.md`): barrido
activo de traceroute con presupuesto de airtime y grafo acumulado de la red
real, failover automático de pasarela, límite de tasa de administración por
pasarela (hoy global), correlación de alertas, alertas por `heapFreeBytes`
(LocalStats no se decodifica) y notificación por email.

## Arquitectura

Servicios orquestados con Docker Compose:

- **gateway** — el único proceso que habla con el nodo Meshtastic (USB, TCP, HTTP, MQTT
  o simulado) y el único módulo que importa la librería oficial
  `meshtastic`. Decodifica los paquetes protobuf, publica eventos
  normalizados en Redis y consume su propia cola de comandos. Está
  deliberadamente desacoplado del backend: puede reiniciarse, cambiar de
  transporte o correr en réplicas (varias pasarelas sobre la misma malla)
  sin tocar el resto del sistema.
- **redis** — el bus del sistema. Pub/sub (`noc:events`) para eventos en
  tiempo real (fire-and-forget: si nadie escucha en ese instante, no pasa
  nada grave, el siguiente heartbeat lo corrige) y Streams por pasarela
  (`noc:commands:<gateway_id>`) con grupo de consumidores y ACK para
  comandos, donde sí importa que nada se pierda.
- **backend** — FastAPI, organizado en capas (`domain` → `application` →
  `adapters`) para que la lógica de negocio no dependa de SQLAlchemy ni de
  FastAPI directamente. Persiste nodos, posiciones, telemetría, vecinos y trazas (series
  append-only con retención configurable), expone la API REST y el WebSocket, evalúa el **motor de
  alertas** cada 30 s reconciliando el estado de la malla contra las reglas
  activas, y coordina el **motor de operaciones/lotes**: cada acción remota
  pasa por una cola persistente en base de datos, con reintentos, límite de
  tasa y, para las operaciones de escritura críticas, verificación de
  lectura antes de darse por confirmada.
- **frontend** — React + TypeScript servido por nginx como único punto de
  entrada (proxy de `/api` y `/ws`). No es una colección de páginas: es una
  consola con un riel de navegación fijo, un cajón de detalle global
  (Inspector) que nunca cambia de vista, y un mapa que permanece montado en
  todo momento.
- **gateway-launcher** — sidecar que crea y destruye contenedores de pasarela
  a petición del backend (ADR 0028). Es el único servicio que monta el socket
  de Docker, por diseño: el backend nunca lo toca.
- **postgres** — persistencia recomendada (SQLite soportado para desarrollo
  vía `NOC_DATABASE_URL`, sin SQL dialectal para mantener ambos motores
  compatibles).

`gateway_id` viaja en todo evento desde el contrato v1, precisamente para que
Multi-Gateway (varias pasarelas viendo la misma malla) funcionara sin
rediseñar el modelo de datos cuando llegó el momento de implementarlo.

## Cómo se ejecuta

```bash
cp .env.example .env
docker compose up --build
```

- UI: http://localhost:8080
- Documentación de la API: http://localhost:8080/api/v1/docs

El servicio `gateway` de Compose no arranca por defecto (`scale: 0`): al
levantar el stack no hay ninguna pasarela. Créala desde la UI, en la pestaña
**Enlaces** → «Añadir gateway»: con el **transporte simulado** (malla ficticia
de 12 nodos) no hace falta hardware para probar la plataforma. Para forzar un
gateway desde `.env` (simulado por defecto, o TCP), arráncalo a mano:

```env
GATEWAY_TRANSPORT=tcp
GATEWAY_TCP_HOST=192.168.1.50
```

```bash
docker compose up -d --scale gateway=1 gateway
```

(El firmware Meshtastic solo admite un cliente TCP a la vez: cierra la app
oficial si está conectada al mismo nodo. Ver `docs/acceptance/tcp.md`.)

La imagen del gateway se construye igualmente: la usa el lanzador para las
pasarelas que creas desde la UI. Para USB en macOS, Docker Desktop no ve el
puerto serie del host: hay que correr el gateway de forma nativa (ver
`docs/operations/usb.md`).

## Cómo se desarrolla

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

- Frontend con HMR: http://localhost:5173
- Backend con recarga automática: http://localhost:8000/api/v1/docs

```bash
# Tests + lint (venv en .venv/, instalado con -e "backend[dev]" -e "gateway[dev]" -e "launcher[dev]")
.venv/bin/python -m pytest backend/tests gateway/tests launcher/tests -q
.venv/bin/ruff check backend/src gateway/src launcher/src backend/tests gateway/tests launcher/tests

# Frontend (incluye comprobación de tipos)
cd frontend && npm run build
```

Las migraciones de base de datos (Alembic) corren automáticamente al
arrancar el contenedor del backend; para ejecutarlas a mano ver
`docs/deployment.md`.

## Cómo contribuir

- Cada decisión de arquitectura relevante se documenta como un ADR nuevo en
  `docs/adr/` (numeración correlativa, formato de los existentes). Los ADRs
  **prevalecen** sobre cualquier otro documento si hay contradicción.
- `shared/events/` es la única fuente de verdad del contrato de eventos
  gateway↔backend (JSON Schema, versionado): cambios incompatibles
  incrementan versión.
- Variables de entorno nuevas se documentan siempre en `.env.example`, con
  prefijo `NOC_` (backend) o `GATEWAY_`/`MESHTASTIC_` (gateway).

## Documentación

| Documento | Para qué sirve |
|---|---|
| [`docs/status.md`](docs/status.md) | Estado del proyecto módulo a módulo, qué está vigente y qué es histórico |
| [`docs/architecture.md`](docs/architecture.md) | Arquitectura, flujos de datos y decisiones confirmadas |
| [`docs/glossary.md`](docs/glossary.md) | Vocabulario canónico de la interfaz y el dominio |
| [`docs/user-guide.md`](docs/user-guide.md) | Guía para operar MeshSentinel desde la consola |
| [`docs/deployment.md`](docs/deployment.md) | Despliegue, variables de entorno y migraciones |
| [`docs/roadmap.md`](docs/roadmap.md) | Lo que está planeado pero aún no implementado |
| `docs/adr/` | Decisiones de arquitectura (ADRs), fuente de verdad ante cualquier conflicto |
| `docs/design/` | Diseños de funcionalidades, marcados como vigentes/implementados/parciales/históricos |
| `docs/acceptance/` | Guías de validación manual usadas al cerrar cada fase (uso interno) |
| `shared/events/` | Contrato de eventos gateway↔backend versionado |
