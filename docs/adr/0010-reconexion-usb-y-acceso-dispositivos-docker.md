# ADR 0010 — Reconexión USB con backoff y acceso a dispositivos en Docker sin privileged

- Estado: Aceptado (2026-06-12)
- **Nota (ADR 0023, 2026-07-12)**: el bucle de reconexión con backoff
  descrito aquí fue **movido** a la base común
  `gateway/transports/meshtastic_stream.py`, compartida con TCP —
  `usb.py` ya no lo implementa por separado. La decisión sobre acceso a
  dispositivos en Docker sin `privileged` no cambió. Ver ADR 0023.

## Contexto

Los nodos USB se desconectan (cable, reinicio del nodo, re-enumeración
`ttyACM0`→`ttyACM1`). El gateway debe sobrevivir indefinidamente sin nodo y
recuperarse solo. En Docker, el acceso a dispositivos puede resolverse con
`privileged: true` (inseguro) o mapeo explícito.

## Decisión

1. **Reconexión**: bucle infinito con backoff exponencial
   `MESHTASTIC_RECONNECT_INITIAL_DELAY` (5 s) ×2 hasta
   `MESHTASTIC_RECONNECT_MAX_DELAY` (300 s), con jitter ±20% . El backoff se
   reinicia tras cada conexión exitosa. `gateway.status` refleja cada transición
   (`connecting`/`connected`/`disconnected`/`error` con `detail`) y el heartbeat
   de 30 s sigue activo siempre.
2. **Autodetección**: `meshtastic.util.findPorts()` (lista blanca VID/PID
   oficial), re-ejecutada en **cada** intento de conexión — así una
   re-enumeración del dispositivo no rompe la recuperación. Con
   `MESHTASTIC_USB_DEVICE` definido se usa esa ruta exacta. Sin parámetros
   serie (baudrate, etc.): los gestiona la librería.
3. **Docker sin `privileged`**: mapeo explícito `devices:` del dispositivo
   concreto (comentado por defecto en `docker-compose.yml`). Privilegiar el
   contenedor expondría todo `/dev` y no aporta nada para este caso. Ruta
   estable en el host vía regla udev con symlink (`docs/operations/usb.md`);
   `restart: unless-stopped` como red de seguridad si el nodo de dispositivo
   no reaparece dentro del contenedor tras un replug.

## Consecuencias

- El gateway nunca termina por ausencia de hardware; el NOC muestra la pasarela
  `disconnected`/`error` con motivo en lugar de morir.
- Desenchufar/enchufar el nodo es un escenario soportado y testeable
  (`docs/acceptance/usb.md` §8–9).
