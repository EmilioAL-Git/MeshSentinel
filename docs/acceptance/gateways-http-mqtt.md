# Guía de aceptación — Fuentes HTTP/MQTT y propiedades de pasarela (ADR 0032)

Requiere: backend reconstruido (migración 0032 automática) y `docker compose build gateway gateway-launcher`.

## A. HTTP de nodo
1. Gateways → + Añadir enlace → Crear contenedor → HTTP, host = IP de un nodo WiFi (puerto 80).
2. Espera ~1 min (volcado inicial lento, ~40 s con 200 nodos). Debe pasar a conectado con el nodo local.
3. Con la app oficial conectada al mismo nodo por TCP, la pasarela HTTP debe seguir viva (sin choque).

## B. MQTT (solo ingesta)
1. Añadir enlace → MQTT, broker/puerto/usuario/clave, tema `msh/<región>/#`, PSK `AQ==`.
2. Pon una zona (sur, oeste, norte, este) si no quieres nodos de medio continente en la BD.
3. Estado conectado, insignia «👂 solo recepción». Aparecen nodos/posiciones/telemetría/mensajes de los
   canales con la PSK. Cualquier operación forzada por esta pasarela devuelve 409.

## C. Solo recepción / primaria / orden / resync (como admin)
1. «👂 Marcar solo recepción» en una pasarela: chip visible; crear una operación forzada por ella → 409
   «es de solo recepción»; el enrutado automático ya no la elige; Nexus no la lista.
2. «★ Hacer primaria»: chip ★, solo una a la vez.
3. ▲▼ cambia el orden y persiste tras recargar.
4. «↻ Resincronizar» en una pasarela conectada: republica la NodeDB sin reconectar.
5. Nodo con TX apagado en el firmware (lora.tx_enabled=false): la pasarela muestra «solo recepción» sola.
