import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from noc.adapters.persistence import models  # noqa: F401 - registra los modelos en Base
from noc.adapters.persistence.database import Base


def _database_url(tmp_path) -> str:  # type: ignore[no-untyped-def]
    url = os.environ.get("NOC_TEST_DATABASE_URL")
    if url and url.startswith("sqlite"):
        return f"sqlite+aiosqlite:///{tmp_path}/test.db"
    if url:
        return url
    return f"sqlite+aiosqlite:///{tmp_path}/test.db"


@pytest.fixture
async def session_factory(tmp_path):  # type: ignore[no-untyped-def]
    engine = create_async_engine(_database_url(tmp_path))
    # Esquema aislado por test en PostgreSQL para poder paralelizar/repetir
    schema = None
    if engine.dialect.name == "postgresql":
        schema = f"test_{uuid.uuid4().hex[:12]}"
        from sqlalchemy import text

        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            await conn.execute(text(f'SET search_path TO "{schema}"'))
            await conn.run_sync(Base.metadata.create_all)
        engine = create_async_engine(
            _database_url(tmp_path), connect_args={"server_settings": {"search_path": schema}}
        )
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()
