# ADR 0030 — Retención de datos y mantenimiento de almacenamiento

Estado: aceptada (2026-10-03)

## Contexto

Solo `activity_log` se podaba (por número de filas). Telemetría, posiciones,
vecinos (N filas por paquete), chat, alertas resueltas, operaciones y
registro de accesos crecían sin límite. Con una malla real (~1000 nodos) eso
degrada las consultas de «lo último por nodo» (`row_number()`) y el tamaño de
la BD.

## Decisión

1. **Plazo por tipo de dato, en días** (`Settings.retention_*_days`, 0 =
   conservar siempre), editable en caliente desde Ajustes → Datos. Reutiliza
   el registro de ajustes existente (overrides en `system_settings`, aplicados
   sobre la instancia compartida de `Settings`): cero mecanismo nuevo.
2. **`RetentionService`** (bucle cada hora, primera pasada 2 min tras el
   arranque, «Aplicar ahora» a demanda). Borra por **lotes de 5000 ids con una
   transacción por lote** (SQLite = un escritor: una DELETE gigante bloquearía
   la ingesta).
3. **Solo se poda lo terminado**: alertas `resolved`, operaciones admin en
   estado terminal y lotes sin operaciones restantes, operaciones Nexus
   `confirmed`/`no_response` (con sus respuestas). Nunca algo vivo.
4. **Nodos**: política opcional (default 0 = nunca). Borra el nodo y toda su
   historia por la vía existente (`delete_bulk`); excluye favoritos de
   cualquier usuario y nodos locales de pasarela.
5. **Defaults** (no son 0 a propósito, para que el crecimiento esté acotado de
   fábrica): telemetría 90 d, posiciones 90 d, vecinos 30 d, chat 180 d,
   alertas resueltas 180 d, admin 180 d, Nexus 180 d, accesos 180 d.
   `auth_login_log` deja de ser «nunca se poda»: sigue siendo configurable
   hasta 0 (siempre) para quien necesite auditoría ilimitada.
6. **Visibilidad**: `GET /maintenance/storage` (tamaño de BD, filas, tamaño y
   dato más antiguo por tabla — `pg_total_relation_size` en PostgreSQL,
   `dbstat` en SQLite si está disponible), `POST /maintenance/prune`,
   `GET /maintenance/runtime` (salud del propio proceso).
7. **Copia lógica portable** (`GET /maintenance/backup`, JSONL+gzip,
   `python -m noc.restore_backup`): no se usa `pg_dump` porque la imagen del
   backend (Debian bookworm) trae cliente 15 y el servidor es 17. Se restaura
   solo sobre BD vacía y a la misma revisión de alembic.

## Consecuencias

- Tras actualizar, la primera pasada puede borrar datos que superen los
  plazos de fábrica; quien quiera conservarlo todo debe poner «Siempre».
- Resumen periódico (`DigestService`): reutiliza los proveedores de
  notificación; fuera del alcance de la retención, vive en la misma pestaña.
