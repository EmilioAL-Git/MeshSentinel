# ADR 0004 — SQLAlchemy async + Alembic; PostgreSQL recomendado, SQLite soportado

- Estado: Aceptado (2026-06-12)

## Contexto

El requisito original pedía SQLite con migración futura a PostgreSQL sin cambios en
la lógica de negocio. En revisión se decidió priorizar PostgreSQL como configuración
recomendada desde el inicio, manteniendo SQLite como opción ligera.

## Decisión

- **SQLAlchemy 2.x async** como ORM y **Alembic** para migraciones.
- La lógica de negocio depende de interfaces de repositorio
  (`application/ports`), nunca de modelos ORM ni del motor.
- **PostgreSQL** es el motor por defecto en `docker-compose.yml` (driver `asyncpg`).
- **SQLite** (driver `aiosqlite`, modo WAL) se soporta cambiando `NOC_DATABASE_URL`.
- Prohibido SQL crudo dialectal; la CI ejecutará los tests contra ambos motores.

## Consecuencias

- Cambiar de motor = cambiar una URL y ejecutar `alembic upgrade head`.
- Escala objetivo (cientos de nodos, telemetría histórica) cubierta por PostgreSQL;
  posibilidad futura de TimescaleDB sin romper el esquema.
