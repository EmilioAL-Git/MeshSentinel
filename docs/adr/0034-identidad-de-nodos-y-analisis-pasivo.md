# ADR 0034 — Identidad de nodos, seguridad de claves y análisis pasivo

Estado: aceptada (2026-10-06). Origen: `docs/research/meshmonitor-comparativa.md` (puntos 3.1, 3.2,
3.3 fase 1, 3.5 y 3.9). Todo es **pasivo**: no transmite nada por la malla.

## 1. Cambios de identidad (Meshtastic 2.8)

Desde 2.8, `node_num = crc32(clave pública)` (zlib, sin signo, sobre los 32 bytes). **Verificado con
la malla real**: 55 nodos de la BD cumplen `node_num == crc32(base64decode(public_key))`, incluido el
X1. Un nodo que actualiza (o regenera su clave) aparece como nodo nuevo y el viejo se queda mudo.

`application/node_identity.py` (puro) empareja `viejo → nuevo` **solo por clave**: el sucesor es el
nodo cuyo número es el CRC de la clave del viejo; si el sucesor declara una clave distinta, **veto
duro** (nunca se empareja por nombre). Cada par lleva su base (`same_key` / `derived_num`).

Desviación deliberada respecto a MeshMonitor: **no se exige que el viejo se haya callado**. Aquí
`last_seen_at` del viejo se refresca con los snapshots de NodeDB y siempre parece vivo; exigirlo
descartaría casi todos los pares reales. El silencio se informa (`predecessor_quiet`), no se exige.

Consecuencias: `node_offline` ignora al viejo emparejado (`NetworkSnapshot.superseded_ids`);
`GET /identity` devuelve el informe; Flota muestra ⇄/⚠ y el Inspector (pestaña Resumen) explica el par.

**Fusión de historial** (`POST /identity/merge`, gestor, `adapters/persistence/identity_merge.py`):
acción **destructiva y siempre manual** — exige teclear el id del nodo viejo, solo acepta pares que el
detector avala (409 si no), y corre en una transacción. Mueve posiciones, telemetría, vecinos (ambos
lados), mensajes (emisor y destino), trazas y saltos, operaciones admin, etiquetas, grupos, favoritos,
enlaces con pasarela y banderas Nexus; las filas de clave compuesta que chocarían se descartan (manda
el nuevo); el nuevo hereda las marcas del NOC (favorito/ignorado/Nexus/pasarela preferida/tipo) y la
fecha de primera vez más antigua; después se borra la fila vieja. No se tocan `alerts` ni
`activity_log` (auditoría histórica que solo menciona el id viejo). **No hay fusión automática**.

## 2. Seguridad de claves

Regla de alerta `key_security` (sin parámetros): clave **duplicada** (misma clave en ≥2 nodos no
explicados por un cambio de identidad) y clave **débil**. Un duplicado con mismo nombre corto+largo se
anota «posible mismo equipo con otro número» (caso real LDVN): se alerta igual, con la pista.
Débil = lista versionada (`weak_keys.json`, ampliable) + heurística estructural (todos los bytes
iguales, <16 bytes distintos de 32, secuencia, patrón repetido). **Límite honesto**: no se ha
incluido ninguna lista de «claves comprometidas» publicada porque no hay una fuente verificable a
mano; la heurística cubre los casos groseros, no sustituye a un aviso de seguridad.
Con la malla real: 17 cambios de identidad y 11 grupos de claves duplicadas (uno de 5 nodos).

## 3. Informe de problemas, fase 1 (sin grafo)

Cuatro reglas de alerta nuevas sobre datos ya persistidos, umbrales editables en la UI:
`chatty_node` (`air_util_tx` > 8 %, guía de buenas prácticas de Meshtastic), `obsolete_role`
(`ROUTER_CLIENT`), `position_overbroadcast` y `telemetry_overbroadcast` (> 12 paquetes/h; conteo por
nodo de la última hora, puede contar doble un paquete oído por 2 pasarelas → umbral holgado).

**Descartada: «desfase de reloj».** La única hora que recibimos es la del fix GPS; un nodo sin fix
reciente reenvía su última posición con hora vieja, y no se distingue de un reloj roto (prueba real:
22 falsos positivos, «48 d»). Se retiró en la misma fase en vez de afirmar lo que no se sabe.
Las fases 2 y 3 (grafo de vecinos/trazas) quedan fuera.

## 4. Diagnóstico de entrega («heard by»)

`chat_messages` ya guardaba `packet_id` y una fila por pasarela (el informe original lo daba por
ausente). `application/delivery.py` (puro) agrupa por (remitente, `packet_id`) en ±10 min (el id de
32 bits se reutiliza) y etiqueta **cada dato con su procedencia**: reportado (campos del paquete),
observado (SNR/RSSI/pasarela), inferido (saltos = `hop_start − hop_limit`, solo si `hop_start > 0`),
desconocido. `GET /chat/heard-by?node_id&packet_id` y `/chat/messages/{id}/heard-by`; UI: «ⓘ entrega»
en cada fila del Chat. Solo prueba recepción por NUESTRAS pasarelas, nunca entrega al destino.

## 5. Copias programadas

`application/backup.py`: bucle como el de retención (`backup_period_hours`, `backup_keep`,
`NOC_BACKUP_DIR`; volumen Docker `backups-data` en `/backups`). Sin estado propio: «la última» se
deduce de la fecha de los ficheros. Escritura atómica (temporal + rename), rotación, descarga solo de
nombres listados, y **un fallo avisa a las integraciones de notificación**. Los ficheros contienen
hashes de contraseña y tokens: el volumen es un secreto.

## Fuera de alcance

Estimación de posición sin GPS, cobertura medida, geofence, API con tokens, Apprise, suplantación,
grafo RF (fases 2-3 del informe). Sin migración en esta ADR.
