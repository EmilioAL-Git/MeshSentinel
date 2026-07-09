# M5 — Gestión de gateways

Valida primero con el gateway nativo en modo `simulated` (sin hardware) y
después con el USB real. No requiere reiniciar Docker en ningún paso.

## Conceptos clave a verificar

- Una fila de `gateways` puede estar **sin gestionar** (`managed=false`,
  nacida solo de un heartbeat — comportamiento anterior a M5) o **gestionada**
  (`managed=true`, configurada desde la pestaña Gateways). Solo las
  gestionadas admiten editar/conectar/desconectar/eliminar.
- El **nombre** (`name`) es lo único que debería tener que mirar el usuario;
  `gateway_id`/transporte son metadato secundario.
- El estado runtime (🟢/🟡/🔴) viene siempre del heartbeat real del proceso,
  nunca de lo que el usuario acaba de pedir — tras "Conectar" puede tardar
  unos segundos en pasar de 🔴 a 🟡 (`connecting`) a 🟢 (`connected`).
- **"Probar conexión" ≠ "Guardar"**: probar deja una conexión real activa;
  guardar siempre vuelve a conectar con los parámetros definitivos (una
  reconexión de más es esperable, ver ADR 0021 §3).
- **Borrado lógico**: "Eliminar" nunca borra la fila (`enabled=false,
  deleted_at` no nulo). No debe aparecer en el listado por defecto pero sí
  con `include_deleted=true`.

## A. Asistente "Añadir gateway" (con el gateway nativo en `simulated`)

1. Arranca el gateway nativo con `GATEWAY_TRANSPORT=simulated` (o déjalo por
   defecto) y el backend. En la pestaña **Gateways** debe aparecer una
   tarjeta "sin configurar" para `gw-01` (o el `GATEWAY_ID` configurado).
2. Pulsa **+ Añadir gateway** (usa ese `gateway_id` automáticamente al ser el
   único candidato sin gestionar).
3. **Buscar dispositivos**: con transporte simulado no hay USB real; la lista
   puede salir vacía — es el comportamiento esperado (el escaneo es real,
   independiente del transporte activo).
4. Para continuar la prueba end-to-end sin hardware, deja el campo de
   dispositivo vacío (autodetección) y pulsa **Probar conexión** apuntando a
   `transport_type=simulated` (o repite este apartado directamente con
   hardware USB, más representativo — ver sección B).

## B. Asistente completo con hardware USB real

1. Conecta el nodo Meshtastic por USB. Arranca el gateway nativo (puede
   seguir en `GATEWAY_TRANSPORT=simulated`, o cualquier config previa: el
   objetivo es demostrar que **no hace falta tocar el `.env`**).
2. Pestaña Gateways → **+ Añadir gateway** → **Buscar dispositivos**: debe
   aparecer el puerto real (`/dev/cu.usbmodemXXXX`) con descripción/VID/PID/
   número de serie si el sistema operativo los expone.
3. Selecciona el dispositivo → **Probar conexión**. Debe mostrar "✓
   Conectado" con nodo/hardware/firmware reales en pocos segundos. Si el
   dispositivo está ocupado o no responde, debe mostrar el error concreto sin
   tumbar el asistente.
4. Escribe un nombre (p. ej. "Casa") → **Guardar**. La tarjeta pasa a
   gestionada; el estado runtime debe llegar a 🟢 Conectado sin haber tocado
   Docker ni el `.env`.
5. Repite el ciclo desconectando físicamente el USB: el estado debe pasar por
   🔴 Desconectado y luego 🟡 Reconectando… (no un salto brusco 🟢→🔴 fijo)
   hasta que se reconecta solo o mediante backoff.

## C. Editar / conectar / desconectar / habilitar / eliminar

1. Con el gateway ya gestionado (apartado B), expande la tarjeta: deben verse
   nodo local, nombre corto/largo, hardware y firmware (refrescados, no
   almacenados en un histórico), además de última conexión/desconexión/error.
2. Cambia el nombre y la prioridad → **Guardar cambios**: se refleja de
   inmediato sin reconectar (no toca `connection_params`).
3. **Desconectar**: el estado debe caer a 🔴 sin que el proceso intente
   reconectar solo (a diferencia de una caída real del USB). **Conectar**
   debe volver a 🟢 en segundos.
4. **Deshabilitar**: igual que desconectar pero persistente — reinicia el
   gateway nativo (mata el proceso y vuelve a lanzarlo) y comprueba que NO
   reconecta automáticamente pese a que la config gestionada existe (porque
   `enabled=false`). **Habilitar** debe reconectar.
5. **Eliminar**: la tarjeta desaparece del listado; `GET /gateways
   ?include_deleted=true` (o inspección directa de BD) debe mostrar
   `enabled=false, deleted_at` no nulo, fila intacta.

## D. Compatibilidad `.env` y reconciliación

1. Con un gateway YA gestionado y habilitado (apartado B), mata el proceso
   nativo y vuelve a lanzarlo tal cual (mismas variables `.env`, sin usar la
   UI). Debe reconectar solo con la config de `.env` primero (comportamiento
   heredado) y, en el siguiente heartbeat tras detectarse como *stale*, el
   backend debe reenviar `command.gateway_connect` con los
   `connection_params` guardados — comprueba en los logs del backend
   (`admin.gateways` o el nivel INFO del command queue) que se reenvía el
   comando poco después del primer heartbeat "de vuelta".
2. Para probar el flujo de importación desde cero: usa un `GATEWAY_ID` nuevo
   que nunca se haya gestionado desde la app. Tras su primer heartbeat debe
   aparecer "sin configurar" en la pestaña Gateways con un botón
   **Importar configuración actual**; tras pulsarlo pasa a gestionado sin
   reconectar (ya estaba conectado).

## E. Casos límite

1. Dos pestañas del navegador abiertas: una pulsa "Eliminar", la otra sigue
   viendo la tarjeta hasta el siguiente refresco (`refetchInterval`, sin
   necesidad de recargar la página a mano).
2. Editar mientras el gateway está desconectado no debe reconectarlo salvo
   que se cambie `transport_type`/`connection_params` o se habilite
   explícitamente.
3. Un intento de "Probar conexión" que falla no debe dejar ningún proceso ni
   tarjeta a medio configurar (nada se persiste hasta "Guardar").
