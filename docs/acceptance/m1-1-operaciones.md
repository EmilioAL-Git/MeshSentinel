# M1.1 — Acceptance Test: pipeline de operaciones remotas (solo lectura)

Valida el flujo completo Aplicación → Cola → Gateway → Nodo → Respuesta →
Historial → UI. Primero con el **simulador** (sin hardware), después con USB.

## A. Con simulador (`GATEWAY_TRANSPORT=simulator`)

1. `docker compose up --build -d` y abrir la pestaña **Operaciones**.
2. Crear `metadata.get` sobre un nodo de la lista → estado `pending` → `queued`
   → `running` → `succeeded` en <10 s; al expandir la fila: JSON con
   `firmwareVersion`.
3. Crear `config.get` sección `lora` → resultado `{"lora": {"region": "EU_868", ...}}`.
4. Encolar 5 operaciones seguidas → se despachan **de una en una** (1 en vuelo
   por pasarela) respetando el rate limit; la actividad del Dashboard muestra
   `Operación #N → running/succeeded`.
5. Repetir hasta observar un **timeout simulado** (~10% de las peticiones):
   la operación pasa a `pending` con reintento (columna intentos 1/3 → 2/3) y
   termina en `succeeded` o `timeout` final. Verificar `Reintentar` sobre una
   fallida y `Cancelar` sobre una `pending`.
6. Reiniciar el backend con operaciones en cola (`docker compose restart backend`)
   → las `pending` se despachan al volver (cola persistente en BD).
7. API: `curl -s localhost:8080/api/v1/admin/operations | jq '.[0]'` y
   `/api/v1/admin/capabilities`.

## B. Con hardware (`GATEWAY_TRANSPORT=usb`)

Requisito: la clave pública del nodo central en `security.admin_key` del nodo
objetivo (firmware ≥2.5). Sin ella, las operaciones terminarán en `timeout`.

1. `metadata.get` sobre el **nodo central** (siempre administrable por sí mismo)
   → firmware/hardware reales en el historial.
2. `config.get` sección `lora` sobre un nodo remoto administrable → verificar
   `region: EU_868`. En logs del gateway: `usb.admin_sent` → `usb.admin_response`.
3. `metadata.get` sobre un nodo **sin admin_key** → reintentos con backoff y
   `timeout` final (comportamiento esperado, no un fallo del NOC).
4. Apagar el nodo objetivo a mitad de operación → `timeout` + reintentos.

| Paso | OK/FALLO | Notas |
|---|---|---|
| A1–A7 | | |
| B1–B4 | | |
