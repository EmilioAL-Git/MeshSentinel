# Guía de aceptación — Nodo virtual (ADR 0033)

Requiere backend reconstruido (migración 0033) y `docker compose build gateway gateway-launcher`.

1. Gateways → + Añadir enlace → Crear contenedor → TCP o HTTP, host del nodo. Marca **Nodo virtual**
   (puerto 4404) y crea. La tarjeta muestra la insignia `⇄ :4404 · 0`.
2. Desde otro equipo/terminal: `meshtastic --host IP-DEL-SERVIDOR --port 4404 --info`
   (o la app móvil «TCP» con esa IP y puerto). Debe mostrar tu nodo, la NodeDB, canales y región.
   La insignia pasa a `· 1` mientras esté conectado.
3. Mientras tanto la pasarela sigue ingiriendo y el resto de la app funciona igual.
4. Administración: `meshtastic --host … --port 4404 --set lora.region EU_868` debe fallar (bloqueado,
   log `virtual_node.blocked`). Activa «Permitir administración» en la tarjeta (Guardar nodo
   virtual): ahora se aplica, salvo `add_contact`.
5. Cambiar el puerto o activar/desactivar el nodo virtual recrea el contenedor (unos segundos de
   corte); dos pasarelas con el mismo puerto → error 409.
6. Quitar el nodo virtual libera el puerto; el cliente conectado se desconecta.

Pruebas de seguridad: el puerto no tiene contraseña — no lo expongas fuera de tu red.
