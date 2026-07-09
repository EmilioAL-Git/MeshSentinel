import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

import uuid
from datetime import datetime, timezone

from noc.adapters.api.routers import (
    admin,
    admin_batches,
    admin_config,
    admin_profiles,
    alerts,
    dashboard,
    gateways,
    health,
    nodes,
    organization,
    system,
)
from noc.adapters.api.ws import hub, router as ws_router
from noc.adapters.events.command_queue import RedisCommandQueue
from noc.adapters.events.redis_bus import RedisEventBus
from noc.adapters.persistence.database import Database
from noc.application.activity import activity
from noc.application.admin.batches import BatchService
from noc.application.admin.profiles import ProfileService
from noc.application.admin.service import AdminOperationService
from noc.application.alerting.engine import AlertEngine, AlertEngineLoop, AlertTransition
from noc.application.alerting.notifier import AlertNotifier
from noc.application.alerting.seed import seed_default_rules
from noc.application.dashboard import DashboardService
from noc.application.gateways.service import GatewayService
from noc.application.ingest import IngestService
from noc.config import get_settings

logger = logging.getLogger("noc")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    app.state.db = Database(settings.database_url)
    app.state.dashboard = DashboardService(app.state.db.session_factory, settings)
    app.state.event_bus = RedisEventBus(settings.redis_url, settings.events_channel)

    command_queue = RedisCommandQueue(settings.redis_url, settings.commands_stream_prefix)
    # Gestión de gateways (M5, ADR 0021): CRUD + comandos command.gateway_*,
    # reutiliza el mismo stream de comandos que el pipeline de administración
    app.state.gateways = GatewayService(app.state.db.session_factory, command_queue)
    app.state.event_bus.subscribe(app.state.gateways.handle_event)

    ingest = IngestService(
        app.state.db.session_factory, app.state.gateways, settings.gateway_stale_after_seconds
    )
    app.state.event_bus.subscribe(ingest.handle_event)
    app.state.event_bus.subscribe(hub.broadcast)

    # Consola de actividad: eventos de ciclo de vida backend→UI por el hub WS
    activity.attach(hub.broadcast)

    # Pipeline de administración remota (M1.1, ADR 0013)
    admin_service = AdminOperationService(app.state.db.session_factory, command_queue, settings)
    app.state.batches = BatchService(app.state.db.session_factory, settings)
    admin_service.attach_batch_service(app.state.batches)
    # Perfiles de configuración (M3): reutilizan el Batch Engine para aplicar
    app.state.profiles = ProfileService(app.state.db.session_factory, settings, app.state.batches)
    app.state.event_bus.subscribe(admin_service.handle_event)
    admin_service.start()

    await app.state.event_bus.start()

    # Motor de alertas (ADR 0012): listeners = notificador + WebSocket
    await seed_default_rules(app.state.db.session_factory, settings)
    engine = AlertEngine(app.state.db.session_factory)
    engine.add_listener(AlertNotifier(app.state.db.session_factory))
    engine.add_listener(_ws_alert_broadcaster)
    alert_loop = AlertEngineLoop(engine, settings.alert_eval_interval_seconds)
    alert_loop.start()

    logger.info("Backend started (env=%s)", settings.environment)
    try:
        yield
    finally:
        await admin_service.stop()
        await alert_loop.stop()
        await app.state.event_bus.stop()
        await command_queue.close()
        await app.state.db.dispose()
        logger.info("Backend stopped")


async def _ws_alert_broadcaster(transition: AlertTransition) -> None:
    a = transition.alert
    await hub.broadcast(
        {
            "schema_version": 1,
            "event_type": f"alert.{transition.kind}",
            "event_id": str(uuid.uuid4()),
            "gateway_id": "noc-backend",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "alert_id": a.id,
                "rule_name": a.rule_name,
                "severity": a.severity,
                "subject_type": a.subject_type,
                "subject_id": a.subject_id,
                "message": a.message,
            },
        }
    )


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
    app.include_router(dashboard.router, prefix=settings.api_v1_prefix)
    app.include_router(alerts.router, prefix=settings.api_v1_prefix)
    app.include_router(admin.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_config.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_batches.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_profiles.router, prefix=settings.api_v1_prefix)
    app.include_router(organization.router, prefix=settings.api_v1_prefix)
    app.include_router(ws_router)
    return app


app = create_app()
