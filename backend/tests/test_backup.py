import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from noc.adapters.persistence.backup import RestoreError, restore_backup, write_backup
from noc.adapters.persistence.database import Base
from noc.adapters.persistence.models import NodeModel, TelemetryModel
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
RECENT = NOW - timedelta(days=1)


async def _seed_node(factory, node_id, last_seen):
    async with factory() as s:
        s.add(NodeModel(id=node_id, first_seen_at=last_seen, last_seen_at=last_seen))
        await s.commit()



async def _empty_db(tmp_path, name):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/{name}.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('0030')"))
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def test_backup_roundtrip(session_factory, tmp_path):
    src_engine, src = await _empty_db(tmp_path, "src")
    await _seed_node(src, "!00000001", RECENT)
    async with src() as s:
        s.add(TelemetryModel(node_id="!00000001", kind="device", battery_level=77, received_at=NOW))
        await s.commit()
    out = tmp_path / "b.jsonl.gz"
    counts = await write_backup(src, out)
    assert counts["nodes"] == 1 and counts["node_telemetry"] == 1
    assert "auth_sessions" not in counts

    dst_engine, dst = await _empty_db(tmp_path, "dst")
    restored = await restore_backup(dst, out)
    assert restored["node_telemetry"] == 1
    async with dst() as s:
        tel = (await s.scalars(select(TelemetryModel))).one()
        assert tel.battery_level == 77 and tel.received_at.replace(tzinfo=None) == NOW.replace(tzinfo=None)
        assert (await s.execute(select(func.count()).select_from(NodeModel))).scalar_one() == 1

    # Una segunda restauración sobre BD ya poblada se rechaza
    with pytest.raises(RestoreError, match="no está vacía"):
        await restore_backup(dst, out)
    await src_engine.dispose()
    await dst_engine.dispose()


async def test_restore_rejects_other_schema_revision(tmp_path):
    engine, factory = await _empty_db(tmp_path, "a")
    out = tmp_path / "b.jsonl.gz"
    await write_backup(factory, out)
    async with factory() as s:
        await s.execute(text("UPDATE alembic_version SET version_num = '0031'"))
        await s.commit()
    with pytest.raises(RestoreError, match="Esquema distinto"):
        await restore_backup(factory, out)
    await engine.dispose()
