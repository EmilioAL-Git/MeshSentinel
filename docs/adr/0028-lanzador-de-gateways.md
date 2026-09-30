# ADR 0028 — Lanzador dinámico de contenedores gateway

- Estado: Aceptado (2026-09-30)
- Sustituye: la "piscina de repuestos" M6.3 (enmienda §6 de ADR 0021, commits
  `0fd773f`/`0538ff3`/`f755bb9`/`acb924e`/`dd5494a`/`b4c53b7`) — retirada por
  completo, no convive con este ADR.
- Complementa: ADR 0001 (gateway desacoplado), ADR 0003 (Redis pub/sub +
  comandos por-gateway), ADR 0021 (gestión de gateways, transporte dirigible
  en caliente), ADR 0022/0023 (Multi-Gateway, transportes).

## Contexto

M6.3 resolvió "añadir un gateway sin tocar YAML ni reconstruir" con una
piscina estática de 6 contenedores (`gateway`, `gateway-2`..`gateway-6`) que
arrancan siempre con `GATEWAY_TRANSPORT=idle` y esperan a ser "reclamados"
desde la UI. El usuario ha pedido rehacer esto: el pool fijo es incómodo por
tres motivos concretos —

1. El número de pasarelas disponibles queda grabado en `docker-compose.yml`:
   añadir una 7ª exige editar el archivo y reconstruir.
2. Los contenedores no son entidades de la aplicación — son procesos Docker
   que laten hacia la BD sin que la BD sepa nada de su ciclo de vida real.
   Cualquier operación de gestión (borrar, redescubrir, distinguir "vivo" de
   "fantasma") necesita lógica extra en el lado de la aplicación para no
   perder sincronía con lo que hay realmente en Docker (de ahí los parches
   sucesivos: borrado real con comprobaciones de seguridad, `IdleTransport`
   al desconectar para no perder el latido, filtrar candidatos por
   frescura, ocultar ids técnicos).
3. Ninguna columna de BD representa el pool — es una convención puramente de
   cliente (`transport === "idle" && !managed`), frágil y fácil de romper
   silenciosamente si un valor cambia de forma en un extremo y no en el
   otro.

## Decisión

**Se elimina la piscina estática por completo** y se sustituye por un
**lanzador de contenedores bajo demanda**: un servicio nuevo que crea y
destruye contenedores gateway hablando con el daemon de Docker, en respuesta
a acciones explícitas de la aplicación ("+ Añadir gateway" → crear; "Eliminar"
→ destruir). El número de pasarelas deja de ser una decisión de
infraestructura y pasa a ser 100% estado de aplicación.

### 1. Aislamiento: sidecar propio, no el backend

Hablar con el daemon de Docker exige acceso a `/var/run/docker.sock`, que
equivale a control total del host Docker (montar un volumen arbitrario,
lanzar un contenedor privilegiado, leer cualquier secreto de otro
contenedor). El backend ya expone una API HTTP con usuarios autenticados
(ADR 0024) — es la superficie de ataque más grande de todo el stack. **El
socket de Docker se monta únicamente en un servicio nuevo y separado,
`gateway-launcher`** (`launcher/`, FastAPI, sin autenticación propia porque
nunca se expone fuera de la red interna de Docker — ningún puerto publicado
al host). El backend le habla por HTTP interno (`http://gateway-launcher:9000`)
con una API mínima y deliberadamente estrecha (crear/destruir/listar
contenedores etiquetados como propios, listar dispositivos USB del host) —
nunca ejecución de comandos arbitrarios ni acceso genérico al SDK de Docker.

```
backend (FastAPI + auth de usuarios) --HTTP interno--> gateway-launcher --socket--> dockerd
```

Riesgo asumido explícitamente: quien comprometa `gateway-launcher` controla
el host Docker. Se mitiga (no se elimina) con: sin puertos publicados, sin
autenticación de usuarios que atacar (superficie mínima: 4 endpoints, sin
lógica de negocio), y todas las escrituras a Docker limitadas a contenedores
con la etiqueta `noc.gateway=true` (nunca toca nada que no haya creado él
mismo).

### 2. Alcance: todos los transportes, incluido USB con paso de dispositivo

El lanzador cubre `simulated`, `tcp` y `usb`. Para USB, el mapeo del
dispositivo (`--device /dev/ttyACMx`) se fija en la creación del contenedor
— a diferencia del resto de parámetros (que ya eran dirigibles en caliente
por comandos desde ADR 0021 §3), el dispositivo físico no se puede
reasignar a un contenedor ya corriendo. `gateway-launcher` monta `/dev`
en modo lectura (`/dev:/dev:ro`) únicamente para poder *listar* dispositivos
serie visibles en el host (`GET /devices`, mismo mecanismo que
`MeshtasticUsbTransport.discover_devices()` ya usaba, reimplementado aquí
con `pyserial` en vez de importar la librería `meshtastic` completa — ADR
0001 solo permite importar esa librería en `gateway/transports` y
`gateway/decoder`; el lanzador es un componente nuevo, no `gateway/`, así
que replica el listado con su única dependencia real, `pyserial`, en vez de
acoplarse al paquete `gateway`).

Limitación conocida y aceptada: en macOS con Docker Desktop, la VM que aloja
el daemon no expone los dispositivos USB del host (ya documentado en
`docs/operations/usb.md` y en las notas de este archivo) — el lanzador
puede crear el contenedor igualmente, pero fallará al conectar exactamente
igual que fallaría hoy `docker compose up gateway` con USB en Mac. El
proceso nativo fuera de Docker sigue siendo el camino para USB real en
desarrollo en Mac; el lanzador solo mejora el caso de un host Linux con
paso de dispositivo real, o `tcp`/`simulated` en cualquier host.

### 3. Modelo de datos: `container_managed`, ortogonal a `managed`

`gateways.managed` (M5) ya distinguía "configurado desde la app" de "solo
heartbeat sin configurar". Se añade `container_managed` (booleano,
migración `0026`): si es verdadero, el ciclo de vida del contenedor físico
también lo controla la aplicación (creado por el lanzador, se destruye con
"Eliminar"). Si es falso, la pasarela es un proceso externo — el `gateway`
por defecto que arranca desde `.env` (compatibilidad, sin cambios, ADR 0021
§1), un proceso nativo (macOS USB) o cualquier despliegue manual —
"Eliminar" solo desconecta/borra la fila, nunca intenta tocar un contenedor
que no existe o no es suyo.

### 4. Flujo de "+ Añadir gateway"

Dos caminos, explícitos en el asistente:

- **Crear un contenedor nuevo** (requiere que `gateway-launcher` responda):
  el operador elige transporte (USB: lista de `GET /devices` del lanzador;
  TCP: host/puerto; Simulado: semilla opcional), nombre y `gateway_id`
  (generado a partir del nombre, editable). Un único paso llama a
  `POST /gateways` en el backend, que: valida el id, pide al lanzador crear
  el contenedor ya con el transporte definitivo como variables de entorno
  de arranque (sin el baile de "crear en idle, luego reconectar en
  caliente" que usaban los repuestos — el contenedor nuevo nace apuntando
  ya a su transporte final), y persiste la fila `managed=True,
  container_managed=True`. Si el lanzador no responde (no desplegado, o
  este es un entorno sin Docker de por medio), el backend devuelve un error
  claro y el operador usa el otro camino.
- **Registrar un proceso externo**: exactamente el pre-registro que ya
  existía (escribir `gateway_id` + nombre a mano, guardar deshabilitado,
  esperar a que el proceso arranque solo) — sigue existiendo sin cambios,
  ahora como única vía para pasarelas que la aplicación no lanza ella
  misma.

### 5. Borrado

`GatewayService.delete()` conserva las comprobaciones de seguridad ya
existentes (bloquea si sigue conectada de verdad, o si tiene trabajo en
vuelo). Si `container_managed`, además pide al lanzador destruir el
contenedor — si el lanzador falla, el borrado se aborta entero (no se
borra la fila ni se manda `command.gateway_disconnect`) para no dejar un
contenedor huérfano corriendo sin fila que lo represente; el operador puede
reintentar. Si no es `container_managed`, el comportamiento es exactamente
el de ADR 0021 §6 (borrado real de la fila + `command.gateway_disconnect`
best-effort).

## Consecuencias

- Se elimina `docker-compose.yml` líneas del pool estático (`gateway-2`
  .. `gateway-6`), la lógica de "candidatos"/"repuestos sin reclamar"
  (`isUnclaimedSpare` y sus usos en frontend), y el paso 1 del asistente
  que ofrecía elegir entre repuestos existentes.
- Nuevo componente de primer nivel `launcher/` (Python, FastAPI, `docker`
  SDK, `pyserial`) — build propio (`launcher/Dockerfile`), sin exponer
  puertos al host.
- `docker-compose.yml` gana una red nombrada explícita (`meshtastic-noc`)
  para que el lanzador pueda adjuntar los contenedores que crea a la red
  correcta sin depender de la convención de nombres por defecto de Compose;
  la imagen del gateway se etiqueta explícitamente (`meshtastic-noc-gateway:
  local`) por el mismo motivo — el lanzador necesita un nombre de imagen
  estable para poder recrearla.
- Migración `0026`: columna `gateways.container_managed` (default `false`,
  compatible con filas existentes — ninguna pasarela previa a este ADR fue
  creada por un lanzador).
- Riesgo de seguridad nuevo y explícito (socket de Docker), mitigado por
  aislamiento en un sidecar sin superficie de ataque propia — ver §1. No
  apto para exponer `gateway-launcher` a una red no confiable bajo ninguna
  circunstancia.
- El pool estático moría con el proceso backend reiniciado igual que
  cualquier otro contenedor; el lanzador no cambia la reconciliación tras
  reinicio ya descrita en ADR 0021 §5 (sigue siendo el propio proceso
  gateway, vía `command.gateway_connect` reenviado tras heartbeat, quien se
  reconecta — el lanzador no vigila ni reinicia contenedores caídos, solo
  crea/destruye a petición explícita).
