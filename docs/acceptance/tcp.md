# Transporte TCP (ADR 0023)

Objetivo: verificar que TCP se comporta **exactamente igual** que USB en todo
el sistema — la única diferencia es cómo se crea la conexión. Requiere un nodo
Meshtastic con WiFi/Ethernet accesible en la red (puerto 4403).

## Preparación

- Anota la IP (o mDNS `*.local`) del nodo. Comprueba alcance:
  `nc -vz <host> 4403`.
- **Cierra la app oficial de Meshtastic si está conectada a ese nodo**: el
  firmware solo admite UN cliente TCP simultáneo. Si la prueba de conexión
  falla o se desconecta sola, esto es lo primero a descartar.
- Gateway nativo (Mac): el transporte TCP no necesita acceso a `/dev/*`, así
  que —a diferencia de USB— también funcionaría dockerizado; para esta guía
  usa el gateway nativo igualmente, es el flujo habitual.

## A. Asistente de la UI (camino recomendado)

1. Arranca un proceso gateway sin configurar (p. ej. `GATEWAY_TRANSPORT=simulated`
   o el que ya tengas) y abre la pestaña **Gateways** → **+ Añadir gateway**.
2. Selecciona transporte **TCP**. No hay paso "Buscar dispositivos" (no hay
   autodetección posible): introduce host y puerto a mano.
3. **Probar conexión** con el host correcto → ✓ con nodo local (nombre corto,
   hardware, firmware), igual que USB.
4. **Probar conexión** con un host inalcanzable → ✗ con error, y la conexión
   que hubiera activa antes debe seguir viva (bug del teardown prematuro,
   ADR 0023 §4). Con host vacío el botón queda deshabilitado.
5. **Guardar** → la tarjeta muestra transporte "TCP", 🟢 conectado, nodo
   local y stats. `connection_params` persistidos: `{host, port}`.

## B. Arranque por `.env` (compatibilidad)

1. `GATEWAY_TRANSPORT=tcp GATEWAY_TCP_HOST=<host>` y arranca el proceso →
   en logs `tcp.connected endpoint=<host>:4403 ... nodedb_size=N` y el
   snapshot de NodeDB puebla la tabla de nodos al instante.
2. Sin `GATEWAY_TCP_HOST`: el proceso arranca, loguea
   `transport_manager.bootstrap_failed` y queda sin transporte pero vivo —
   configurable después desde la app.

## C. Paridad funcional con USB (lo importante)

Con el gateway TCP conectado, repite las comprobaciones habituales:

1. **Telemetría/posiciones**: los nodos de la malla aparecen y actualizan
   igual que por USB (mismo decoder, mismo pump).
2. **Reconexión**: apaga el WiFi del nodo (o desenchúfalo) → estado
   `disconnected`/`error` → `reconnecting` con backoff 5→300 s; al volver el
   nodo, reconecta solo y re-emite el snapshot. OJO: un corte de red
   silencioso puede tardar más en detectarse que un cable USB extraído
   (riesgo aceptado, ADR 0023 §Consecuencias) — si el estado se queda
   `connected` indefinidamente con el nodo apagado, anótalo.
3. **Admin GET** (Operaciones → metadata.get a un nodo remoto): mismo flujo,
   estados y resultado que por USB.
4. **SET verificable** (owner.set o editor de configuración): GET previo →
   SET → verify read-back, veredicto confirmed/mismatch/unavailable.
5. **Ack-only** (favorito/ignorado remoto): 3 intentos con passkey renovado,
   vocabulario Pendiente/Enviado/Confirmado/Error en su panel.
6. **Batches y Multi-Gateway**: un lote reparte operaciones a la pasarela
   TCP igual que a cualquier otra; en `GET /gateways/stats` aparece con sus
   nodos visibles/exclusivos; el enrutado la considera candidata normal.
7. **Desconectar/Conectar/Eliminar** desde la tarjeta: igual que USB.

## D. Regresión USB/simulado

1. Los transportes USB y simulado siguen funcionando igual (mismos tests en
   verde, `usb.connected`/`usb.stats` en logs sin cambios de formato).
2. `command.gateway_connect` con un tipo aún no soportado (`http`) no
   destruye la conexión activa (test de regresión en
   `test_transport_manager.py`).
