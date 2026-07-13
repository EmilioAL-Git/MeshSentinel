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
  de salud, alertas con reconocimiento en línea, estado de pasarelas), mapa
  en vivo con pulsos de actividad y capas activables (estado, calidad de
  señal, redundancia, tipo de nodo, enlaces nodo↔pasarela), y consola lateral
  con Actividad/Trabajos/Alertas siempre montada.
- **Flota** — listado denso de nodos con KPIs, filtros avanzados (DSL de
  búsqueda), medidor de batería, barras de señal, favoritos/etiquetas/grupos/
  ignorados, y selección masiva para lanzar lotes.
- **Grupos y contexto de grupo activo** — clasificación de nodos (pasarela,
  infraestructura, fijo, usuario), agrupación en "sitios" y una malla activa
  que acota el resto de la interfaz (o "Toda la red" como escape).
- **Inspector** — cajón de detalle global para cualquier nodo (no una
  página): cabecera vital, acciones rápidas de lectura a un clic, histórico
  de telemetría/posición con gráficas, gestión de favoritos/ignorados
  remotos, observaciones por pasarela.
- **Focus** — fijar un nodo como contexto: atenúa el mapa salvo alertas
  activas, prioriza su actividad y sus trabajos en curso.
- **Motor de alertas** — reglas configurables (batería baja, nodo
  desconectado, SNR degradado, pasarela caída) con severidad, ciclo de vida
  firing → acknowledged → resolved, y canales de notificación extensibles
  (webhook, ntfy).
- **Administración remota** — lectura de metadata/configuración, cambios
  seguros con verificación de lectura (GET→SET→GET), editor completo de
  `config`/`module_config` por secciones generado desde los propios
  protobufs (sin lógica por parámetro), gestión de favoritos/ignorados
  remotos del propio dispositivo — con cola persistente, límite de tasa de
  malla y reintentos automáticos.
- **Perfiles de configuración** — plantillas versionadas e inmutables,
  comparación por diferencias contra el estado real de un nodo, y
  sincronización masiva.
- **Trabajos (batches)** — selección de nodos, previsualización sin efectos
  (dry-run), ejecución con confirmación explícita, progreso y ETA en vivo,
  pausa/cancelación, reparto automático entre pasarelas cuando hay varias.
- **Gestión de pasarelas** — alta/baja de pasarelas gestionadas por la propia
  app (sin depender de variables de entorno), transporte USB, TCP o
  simulado, descubrimiento de dispositivos, prueba de conexión antes de
  guardar, habilitar/deshabilitar, borrado lógico.
- **Multi-Gateway funcional** — un nodo puede ser visto por varias pasarelas
  a la vez (N:M); estadísticas de cobertura y redundancia; cada operación se
  enruta a una pasarela sana al encolarse (sin failover automático una vez
  fijada).
- **Registro de actividad** — diario cronológico de la malla: cada paquete
  decodificado (telemetría, posición, identidad, vecinos, traceroute,
  waypoints, mensajes) genera su propia entrada en lenguaje de operador, con
  el detalle técnico plegado bajo "Ver paquete".

Lo que **no** está implementado todavía (para no llevarse sorpresas):
transporte HTTP para el gateway (solo USB, TCP y simulado), autenticación/
RBAC real, selección "inteligente" de pasarela para administración remota
(hoy es la primera pasarela sana disponible, sin ranking por prioridad/
saltos/SNR/recencia — ver `docs/roadmap.md`), límite de tasa por pasarela
(hoy es global entre todas), correlación de alertas, notificaciones por
Telegram/email, reglas de alerta por grupo, histórico de trazas GPS, y
topología nodo↔nodo persistida (el registro ya narra vecinos/traceroute,
pero no se guarda un grafo consultable).

## Arquitectura

Cuatro servicios orquestados con Docker Compose:

- **gateway** — el único proceso que habla con el nodo Meshtastic (USB, TCP o
  transporte simulado) y el único módulo que importa la librería oficial
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
  FastAPI directamente. Persiste nodos, posiciones y telemetría (series
  append-only), expone la API REST y el WebSocket, evalúa el **motor de
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

Por defecto el gateway usa el **transporte simulado** (una malla ficticia de
12 nodos), así que no hace falta hardware para probar la plataforma. Para
conectar un nodo real por TCP:

```env
GATEWAY_TRANSPORT=tcp
GATEWAY_TCP_HOST=192.168.1.50
```

(El firmware Meshtastic solo admite un cliente TCP a la vez: cierra la app
oficial si está conectada al mismo nodo. Ver `docs/acceptance/tcp.md`.)

Para USB, además descomenta el bloque `devices:` del servicio `gateway` en
`docker-compose.yml` y ajusta `MESHTASTIC_USB_DEVICE` — en macOS, Docker
Desktop no tiene acceso al puerto serie del host; hace falta correr el
gateway de forma nativa (ver `docs/operations/usb.md`).

## Cómo se desarrolla

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

- Frontend con HMR: http://localhost:5173
- Backend con recarga automática: http://localhost:8000/api/v1/docs

```bash
# Tests + lint (venv en .venv/, instalado con -e "backend[dev]" -e "gateway[dev]")
.venv/bin/python -m pytest backend/tests gateway/tests -q
.venv/bin/ruff check backend/src gateway/src backend/tests gateway/tests

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
