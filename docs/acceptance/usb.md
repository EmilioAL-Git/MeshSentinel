# Fase 3A — Acceptance Test: Meshtastic USB Transport

Validación manual del transporte USB con un nodo Meshtastic real conectado al
host. Requiere haber pasado antes la guía `fase1.md` con el simulador.

**Hardware:** un nodo Meshtastic (T-Beam, Heltec, RAK…) con firmware estable
reciente, en región EU_868, conectado por USB al host Docker.

---

## 1. Identificación del dispositivo USB en Linux

```bash
ls -l /dev/serial/by-id/        # nombre estable con VID/PID y serial
dmesg | tail -5                 # tras enchufar: "ttyACM0: USB ACM device" o ttyUSB0
lsusb                           # localiza el conversor (CP210x, CH340, ACM nativo…)
```

**Esperado:** un dispositivo `/dev/ttyACM0` o `/dev/ttyUSB0`. Anota la ruta.
Recomendado: crear la regla udev con symlink estable (`docs/operations/usb.md` §2).

## 2. Configuración del entorno

En `.env`:

```env
GATEWAY_TRANSPORT=usb
MESHTASTIC_USB_DEVICE=          # vacío = autodetección (recomendado con 1 nodo)
MESHTASTIC_RECONNECT_INITIAL_DELAY=5
MESHTASTIC_RECONNECT_MAX_DELAY=300
```

En `docker-compose.yml`, descomenta el bloque `devices:` del servicio `gateway`
ajustando la ruta real:

```yaml
devices:
  - "/dev/ttyACM0:/dev/ttyACM0"
```

**Importante:** no uses `privileged: true` (ADR 0010).

## 3. Arranque

```bash
docker compose up --build -d
docker compose logs -f gateway
```

**Esperado (logs estructurados, en orden):**

```
Gateway gw-01 started (transport=usb)
usb.autodetect candidates=['/dev/ttyACM0']        # solo en modo autodetección
usb.device_selected device=/dev/ttyACM0 source=autodetect
usb.connected device=/dev/ttyACM0 local_node=!xxxxxxxx nodedb_size=N
```

Y en Redis (`docker compose exec redis redis-cli subscribe noc:events`):
`gateway.status` con `"status":"connecting"` → `"connected"`,
`"transport":"usb"` y `local_node_id` del nodo central, seguido de una **ráfaga
de `node.seen`** (snapshot de la NodeDB del dispositivo).

## 4. El nodo aparece en el frontend

Abrir <http://localhost:8080>:

- Barra superior: `gw-01 connected (usb)`.
- La tabla muestra el nodo central **y los nodos de su NodeDB** en segundos.

**Limitación conocida (ADR 0009):** los nodos del snapshot aparecen `online`
durante los primeros ~15 min aunque lleven tiempo sin transmitir; después el
estado refleja la actividad real.

## 5. Recepción de NodeInfo

Los nodos difunden NodeInfo con baja frecuencia (horas). Para forzarlo: en la
app móvil de otro nodo, cambia su nombre corto, o reinícialo.

```bash
docker compose logs gateway | grep "type=node.seen" | tail
curl -s http://localhost:8080/api/v1/nodes | jq '.[].node | {node_id, short_name, hw_model}'
```

**Esperado:** el cambio de nombre aparece en la API/UI tras la difusión.

## 6. Recepción de posiciones GPS

Necesita al menos un nodo con GPS (o posición fija configurada) al alcance.

```bash
docker compose logs gateway | grep "type=position.updated" | tail
NODE=<node_id_con_gps>
curl -s "http://localhost:8080/api/v1/nodes/$NODE/positions?limit=5" | jq
```

**Esperado:** posiciones con coordenadas reales; el nodo aparece en la vista
Mapa. Nota: la precisión puede estar reducida por configuración del canal
(`precision_bits` < 32).

## 7. Recepción de telemetría

```bash
docker compose logs gateway | grep "type=telemetry.received" | tail
curl -s "http://localhost:8080/api/v1/nodes/$NODE/telemetry?kind=device&limit=5" | jq
```

**Esperado:** batería/voltaje del propio nodo central como mínimo (se
auto-reporta); del resto, según el intervalo de telemetría configurado en cada
nodo. `battery_level=101` = alimentación externa (normal en el nodo USB).
Contadores acumulados: `docker compose logs gateway | grep usb.stats | tail -1`.

## 8. Desconexión física del USB

Desenchufa el cable USB del nodo central.

```bash
docker compose logs -f gateway
```

**Esperado:**

```
usb.connection_lost device=/dev/ttyACM0
```

`gateway.status` pasa a `disconnected` (visible en `/api/v1/system/health`:
`gw-01` con `status:"disconnected"` y el sistema `degraded`). El contenedor
gateway **sigue vivo** (`docker compose ps`), el heartbeat continúa y la UI
muestra la pasarela caída sin perder el histórico.

## 9. Reconexión automática

Mantén el cable desenchufado ≥1 min y observa los reintentos con backoff:

```
usb.connect_failed error=... retry_in=5s
usb.connect_failed error=... retry_in=10s
usb.connect_failed error=... retry_in=20s
```

Vuelve a enchufar el cable.

**Esperado:** en el siguiente reintento, `usb.device_selected` →
`usb.connected` y nueva ráfaga de snapshot; `/system/health` vuelve a `ok` y el
flujo de eventos se reanuda sin reiniciar nada manualmente. Si el dispositivo
no reaparece dentro del contenedor (depende del host), `docker compose restart
gateway` debe recuperar en <30 s — anótalo como observación.

## 10. Exportación de logs

```bash
mkdir -p /tmp/noc-usb-debug
docker compose logs --no-color --timestamps gateway > /tmp/noc-usb-debug/gateway.log
grep -E "usb\.(autodetect|device_selected|connected|connection_lost|connect_failed|stats)" \
  /tmp/noc-usb-debug/gateway.log > /tmp/noc-usb-debug/gateway-usb-lifecycle.log
curl -s http://localhost:8080/api/v1/system/health > /tmp/noc-usb-debug/system-health.json
ls -l /dev/serial/by-id/ > /tmp/noc-usb-debug/host-devices.txt 2>&1
tar -czf noc-usb-debug-$(date +%Y%m%d-%H%M).tar.gz -C /tmp noc-usb-debug
```

Para ver cada evento individual traducido al bus: `NOC_LOG_LEVEL=DEBUG` en
`.env` y recrear el gateway (`docker compose up -d gateway`) — aparecen líneas
`usb.event_published type=... node=...`.

---

## Registro de resultados

| Paso | Resultado (OK/FALLO) | Notas |
|---|---|---|
| 1. Identificación USB | | |
| 2. Configuración | | |
| 3. Arranque y conexión | | |
| 4. Nodos en frontend | | |
| 5. NodeInfo | | |
| 6. Posiciones GPS | | |
| 7. Telemetría | | |
| 8. Desconexión | | |
| 9. Reconexión automática | | |
| 10. Logs | | |
