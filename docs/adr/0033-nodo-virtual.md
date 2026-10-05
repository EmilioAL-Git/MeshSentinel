# ADR 0033 — Nodo virtual (clientes Meshtastic a través de la pasarela)

Estado: aceptada (2026-10-05). Origen: revisión de MeshMonitor (Virtual Node) para esquivar el límite
de un único cliente TCP del firmware, que la pasarela ya ocupa.

## Decisión

Cada pasarela USB/TCP/HTTP puede exponer un **servidor TCP propio** (`gateway/virtual_node.py`) que
habla el protocolo de stream de Meshtastic (`0x94 0xC3` + longitud + protobuf). La app móvil, el CLI
de Python u otro cliente se conectan a `host-de-la-pasarela:puerto` como si fuera el nodo.

- **Hacia el cliente.** La configuración inicial (`want_config_id`) se sirve desde el estado que la
  librería ya tiene del nodo (`myInfo`, `metadata`, `nodesByNum`, canales, `localConfig`,
  `moduleConfig`) en el orden del firmware, sin molestar al nodo. Lo que el nodo emite después
  (`packet`, `node_info`, `clientNotification`) se difunde a los clientes ya configurados, enganchado
  en el mismo punto que sella la actividad (`_instrument`).
- **Hacia el nodo.** Los paquetes del cliente se reenvían al nodo real con `_sendToRadio`. `heartbeat`
  se responde localmente (QueueStatus) y `disconnect` cierra el cliente. Un mismo `want_config_id`
  repetido en 5 s se ignora (bucle de reconexión del cliente).
- **Bloqueos (lección de MeshMonitor + seguridad):** `ADMIN_APP` bloqueado salvo que se active
  «permitir administración» (apagado por defecto); aun permitido, `add_contact` nunca (corrompería las
  claves PKI del nodo) ni administración ilegible; paquetes cifrados (no inspeccionables) siguen la
  política de administración; `xmodemPacket` (ficheros del dispositivo) nunca.
- **Configuración** en `connection_params`: `vn_enabled`, `vn_port` (defecto 4404), `vn_allow_admin`;
  en el gateway `GATEWAY_VN_*`. Desactivado por defecto. Estado runtime
  `gateway.status.virtual_node {port, clients, allow_admin}` (contrato v1 aditivo) → columna
  `gateways.virtual_node` (migración 0033). El número de clientes se re-emite al conectar/desconectar.
- **Contenedores.** El lanzador publica el puerto del nodo virtual en el host (mismo número dentro y
  fuera). Como el puerto publicado es del contenedor, activar/desactivar o mover el puerto **recrea el
  contenedor** (`GatewayService.update`); cambiar solo la política de administración se aplica en
  caliente. El backend valida rango (1024-65535) y unicidad entre pasarelas (409).
- No disponible para MQTT (sin nodo) ni para el simulador.

## Consecuencias / riesgos asumidos

- **Sin autenticación:** cualquiera en la red que alcance el puerto actúa como cliente del nodo (puede
  enviar mensajes por la malla). Por eso está apagado por defecto, la administración exige un segundo
  interruptor y la UI lo advierte. El puerto se publica en `0.0.0.0`.
- Un cliente conectado ve la NodeDB tal como la tiene la librería (sin `deviceuiConfig` ni `fileInfo`),
  suficiente para el cliente oficial de Python (validado en hardware).
- Si el enlace con el nodo cae, los clientes ya conectados quedan sin datos hasta que vuelve; una
  petición de configuración sin enlace cierra la conexión para que el cliente reintente.
- Dos clientes haciendo **a la vez su sincronización inicial** contra el mismo nodo pueden pisarse los
  FromRadio del firmware (observado con 3 sesiones simultáneas); el nodo virtual lo evita para los
  clientes del usuario porque ninguno habla con el nodo real salvo la pasarela.
