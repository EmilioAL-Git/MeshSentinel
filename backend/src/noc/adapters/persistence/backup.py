"""Copia de seguridad lógica y portable (JSON Lines + gzip).

Independiente del motor (SQLite o PostgreSQL) y sin binarios externos: cada
fila de cada tabla es una línea `{"t": tabla, "r": {...}}` tras una cabecera
con la versión del esquema (revisión de alembic). `restore_backup` la carga
sobre una BD ya migrada a la misma revisión y vacía.

Excluye `auth_sessions` (sesiones efímeras: restaurarlas sería un riesgo, no
un valor). OJO: el fichero SÍ contiene hashes de contraseña y tokens de
integraciones (Telegram…) — tratarlo como un secreto.
"""

import asyncio
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, Integer, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from noc.adapters.persistence.database import Base

FORMAT = "meshsentinel-backup"
VERSION = 1
EXCLUDED_TABLES = {"auth_sessions"}
BATCH = 2000


def _default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return str(value)


async def schema_revision(session: AsyncSession) -> str | None:
    try:
        return (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one_or_none()
    except Exception:
        await session.rollback()
        return None


def _tables() -> list[Any]:
    return [t for t in Base.metadata.sorted_tables if t.name not in EXCLUDED_TABLES]


async def write_backup(
    session_factory: async_sessionmaker[AsyncSession], path: Path
) -> dict[str, int]:
    """Escribe la copia en `path`; devuelve filas por tabla."""
    counts: dict[str, int] = {}
    async with session_factory() as session:
        header = {
            "format": FORMAT,
            "version": VERSION,
            "schema_revision": await schema_revision(session),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(json.dumps(header) + "\n")
            for table in _tables():
                n = 0
                result = await session.stream(select(table).execution_options(yield_per=BATCH))
                async for partition in result.partitions():
                    for row in partition:
                        fh.write(json.dumps({"t": table.name, "r": dict(row._mapping)}, default=_default) + "\n")
                        n += 1
                    await asyncio.sleep(0)  # no acaparar el bucle de eventos en BDs grandes
                counts[table.name] = n
    return counts


def _coerce(table: Any, record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    for column in table.columns:
        value = out.get(column.name)
        if isinstance(column.type, DateTime) and isinstance(value, str):
            parsed = datetime.fromisoformat(value)
            out[column.name] = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return out


class RestoreError(Exception):
    pass


async def restore_backup(session_factory: async_sessionmaker[AsyncSession], path: Path) -> dict[str, int]:
    """Carga una copia sobre una BD vacía y migrada a la misma revisión."""
    tables = {t.name: t for t in _tables()}
    counts: dict[str, int] = {}
    async with session_factory() as session:
        current_rev = await schema_revision(session)
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            header = json.loads(fh.readline() or "{}")
            if header.get("format") != FORMAT:
                raise RestoreError("El fichero no es una copia de MeshSentinel")
            if header.get("schema_revision") != current_rev:
                raise RestoreError(
                    f"Esquema distinto: copia en {header.get('schema_revision')}, BD en {current_rev}. "
                    "Migra la BD destino (alembic upgrade) a la revisión de la copia."
                )
            non_empty = [
                n for n in ("nodes", "auth_users", "alert_rules")
                if (await session.execute(select(tables[n]).limit(1))).first() is not None
            ]
            if non_empty:
                raise RestoreError(f"La BD destino no está vacía ({', '.join(non_empty)})")

            pending: dict[str, list[dict[str, Any]]] = {}

            async def flush(name: str) -> None:
                rows = pending.pop(name, [])
                if rows:
                    await session.execute(tables[name].insert(), rows)

            current: str | None = None
            for line in fh:
                obj = json.loads(line)
                name = obj["t"]
                if name not in tables:
                    continue
                if current is not None and name != current:
                    await flush(current)
                current = name
                pending.setdefault(name, []).append(_coerce(tables[name], obj["r"]))
                counts[name] = counts.get(name, 0) + 1
                if len(pending[name]) >= BATCH:
                    await flush(name)
            if current is not None:
                await flush(current)

            if session.get_bind().dialect.name == "postgresql":
                for name, table in tables.items():
                    if "id" in table.c and isinstance(table.c.id.type, Integer) and counts.get(name):
                        await session.execute(
                            text(
                                f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), "
                                f"(SELECT COALESCE(MAX(id), 1) FROM {name}))"
                            )
                        )
            await session.commit()
    return counts
