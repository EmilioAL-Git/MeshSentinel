import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from noc.adapters.api.routers import gateways, health, nodes, system
from noc.adapters.api.ws import hub, router as ws_router
from noc.adapters.events.redis_bus import RedisEventBus
from noc.adapters.persistence.database import Database
from noc.application.ingest import IngestService
from noc.config import get_settings

logger = logging.getLogger("noc")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app.state.db = Database(settings.database_url)
    app.state.event_bus = RedisEventBus(settings.redis_url, settings.events_channel)
    ingest = IngestService(app.state.db.session_factory)
    app.state.event_bus.subscribe(ingest.handle_event)
    app.state.event_bus.subscribe(hub.broadcast)
    await app.state.event_bus.start()
    logger.info("Backend started (env=%s)", settings.environment)
    try:
        yield
    finally:
        await app.state.event_bus.stop()
        await app.state.db.dispose()
        logger.info("Backend stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        lifespan=lifespan,
        docs_url=f"{settings.api_v1_prefix}/docs",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    )
    app.include_router(health.router, prefix=settings.api_v1_prefix)
    app.include_router(nodes.router, prefix=settings.api_v1_prefix)
    app.include_router(gateways.router, prefix=settings.api_v1_prefix)
    app.include_router(system.router, prefix=settings.api_v1_prefix)
    app.include_router(ws_router)
    return app


app = create_app()
