"""Restaura una copia lógica en una BD VACÍA ya migrada a la misma revisión.

    python -m noc.restore_backup meshsentinel-20261003-1530.jsonl.gz

Usa NOC_DATABASE_URL (la misma que el backend). Dentro de Docker:
    docker compose exec backend python -m noc.restore_backup /tmp/copia.jsonl.gz
"""

import asyncio
import sys
from pathlib import Path

from noc.adapters.persistence.backup import RestoreError, restore_backup
from noc.adapters.persistence.database import Database
from noc.config import get_settings


async def _main(path: Path) -> int:
    db = Database(get_settings().database_url)
    try:
        counts = await restore_backup(db.session_factory, path)
    except RestoreError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        await db.dispose()
    total = sum(counts.values())
    print(f"Restauradas {total} filas en {len(counts)} tablas")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_main(Path(sys.argv[1]))))
