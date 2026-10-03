# ADR 0028 — Lanzador dinámico de contenedores gateway

Sustituye la piscina estática de repuestos (M6.3). Requiere el stack
completo levantado con `docker compose up --build` (o el override de dev) —
`gateway-launcher` es un servicio nuevo, no aplica a un gateway nativo fuera
de Docker.

## Conceptos clave a verificar

- Ya no hay `gateway-2`..`gateway-6` en `docker compose ps`. Solo `gateway`
  (el original, arranca desde `.env`) y `gateway-launcher` (nuevo, sin
  puertos publicados).
- `docker compose exec gateway-launcher wget -qO- http://localhost:9000/health`
  debe devolver `{"ok": true}`.
- Cualquier pasarela creada desde la interfaz debe aparecer en
  `docker ps --filter label=meshsentinel.gateway=true`.

## A. Crear una pasarela simulada (sin hardware)

1. Pestaña **Gateways** → **+ Añadir enlace** → pestaña "Crear contenedor"
   (por defecto).
2. Transporte **SIM**, nombre "Prueba simulada" (el `gateway_id` se rellena
   solo como `gw-prueba-simulada`, editable).
3. **Crear pasarela**. Debe aparecer casi al instante un contenedor
   `meshsentinel-gateway-gw-prueba-simulada` en `docker ps`, y la tarjeta en la
   interfaz debe pasar de "Sin conexión" a "Conectado" en pocos segundos
   (chip "contenedor" visible).
4. **Eliminar** esa pasarela desde su panel (confirmar "¿Eliminar y destruir
   contenedor?"). El contenedor debe desaparecer de `docker ps` y la
   tarjeta del listado.

## B. Crear una pasarela TCP

1. Mismo asistente, transporte **TCP**, host de un nodo real accesible por
   red (o cualquier IP para probar el camino de error).
2. Si el host no responde, la tarjeta debe quedar en "Error" con el detalle
   del fallo — no debe romper el resto de la interfaz ni dejar el
   contenedor a medias (`docker ps` debe seguir mostrándolo, reintentando).

## C. USB (solo en un host Linux con paso de dispositivo; en macOS con
Docker Desktop se espera que falle — ver ADR 0028 §2)

1. Transporte **USB** → "Buscar dispositivos del host". Si `gateway-launcher`
   no ve ningún `/dev/ttyACM*`/`/dev/ttyUSB*`, la lista sale vacía (esperado
   en macOS).
2. En un host Linux con el dispositivo conectado, selecciona el puerto y
   crea la pasarela — el contenedor debe nacer ya con `--device` mapeado
   (`docker inspect meshsentinel-gateway-<id> --format '{{.HostConfig.Devices}}'`).

## D. Registrar un proceso externo (camino de siempre, sin lanzador)

1. Pestaña "Registrar externo" del mismo asistente.
2. Escribe a mano el `gateway_id` de un proceso que arrancas tú (p. ej. el
   gateway nativo USB de macOS, fuera de Docker). El resto es idéntico al
   asistente de siempre (Buscar → Probar → Guardar).
3. Confirmar que esta pasarela NUNCA muestra el chip "contenedor" y que
   "Eliminar" no intenta tocar ningún contenedor Docker (revisar logs de
   `gateway-launcher`: no debe recibir ninguna petición de `DELETE
   /containers/...` para este `gateway_id`).

## E. Lanzador caído

1. `docker compose stop gateway-launcher`.
2. "+ Añadir enlace" → "Crear contenedor" → Crear pasarela: debe fallar con
   un mensaje claro (502), sin dejar ninguna fila a medias en la BD
   (`GET /api/v1/gateways` no debe mostrar el `gateway_id` que intentaste
   crear).
3. "Registrar externo" debe seguir funcionando con normalidad (no depende
   del lanzador).
4. `docker compose start gateway-launcher` y repetir A — debe volver a
   funcionar sin reiniciar nada más.
