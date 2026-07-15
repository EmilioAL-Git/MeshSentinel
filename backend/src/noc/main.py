import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI

from noc.adapters.api.routers import (
    activity as activity_router,
    admin_batches,
    admin_config,
    admin_operations,
    admin_profiles,
    admin_remote_flags,
    alerts,
    auth as auth_router,
    chat,
    dashboard,
    gateways,
    health,
    nodes,
    organization,
    system,
    topology,
)
from noc.adapters.api.ws import hub, router as ws_router
from noc.adapters.events.command_queue import RedisCommandQueue
from noc.adapters.events.redis_bus import RedisEventBus
from noc.adapters.persistence.database import Database
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.application.activity import activity
from noc.application.activity_events import render_alert_transition
from noc.application.activity_log import ActivityLogWriter
from noc.application.admin.batches import BatchService
from noc.application.admin.profiles import ProfileService
from noc.application.admin.service import AdminOperationService
from noc.application.alerting.engine import AlertEngine, AlertEngineLoop, AlertTransition
from noc.application.alerting.dispatcher import NotificationDispatcher
from noc.application.alerting.seed import seed_default_rules
from noc.application.auth.service import AuthService
from noc.application.dashboard import DashboardService
from noc.application.envelopes import make_event_envelope
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
    # Autenticación: cookie de sesión opaca + rate limit de login sobre Redis
    # (misma infraestructura que el resto del backend, sin dependencia nueva).
    app.state.auth = AuthService(app.state.db.session_factory, settings.redis_url, settings)

    command_queue = RedisCommandQueue(settings.redis_url, settings.commands_stream_prefix)
    # Gestión de gateways (M5, ADR 0021): CRUD + comandos command.gateway_*,
    # reutiliza el mismo stream de comandos que el pipeline de administración
    app.state.gateways = GatewayService(app.state.db.session_factory, command_queue)
    app.state.event_bus.subscribe(app.state.gateways.handle_event)

    ingest = IngestService(
        app.state.db.session_factory,
        app.state.gateways,
        settings.gateway_stale_after_seconds,
        settings.node_offline_after_seconds,
    )
    app.state.event_bus.subscribe(ingest.handle_event)
    app.state.event_bus.subscribe(hub.broadcast)

    # Consola de actividad: eventos de ciclo de vida backend→UI por el hub WS
    activity.attach(hub.broadcast)
    # Diario operativo (Actividad 2.0 Fase 1): las narrativas admin resuelven
    # el nombre del nodo con una lectura puntual (fuera de la transacción del
    # llamante — sesión propia, solo lectura)
    activity.attach_labeler(_make_node_labeler(app.state.db.session_factory))
    # Registro persistente (hardening): el MISMO envelope del WS se encola
    # hacia un escritor en background (cola acotada, poda por tamaño) — nunca
    # una sesión propia inline, que en SQLite chocaría con la transacción de
    # la ingesta que está narrando.
    activity_log_writer = ActivityLogWriter(
        app.state.db.session_factory, settings.activity_log_max_rows
    )
    activity.attach_store(activity_log_writer.enqueue)
    activity_log_writer.start()

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
    engine.add_listener(NotificationDispatcher(app.state.db.session_factory))
    engine.add_listener(_ws_alert_broadcaster)
    # Diario operativo: narrativa de transiciones de alertas (la lógica de
    # detección vive SOLO en el motor; aquí solo se redacta)
    engine.add_listener(_make_alert_narrator(app.state.db.session_factory))
    alert_loop = AlertEngineLoop(engine, settings.alert_eval_interval_seconds)
    alert_loop.start()

    logger.info("Backend started (env=%s)", settings.environment)
    try:
        yield
    finally:
        await admin_service.stop()
        await alert_loop.stop()
        await app.state.event_bus.stop()
        activity.attach_store(None)
        await activity_log_writer.stop()
        await command_queue.close()
        await app.state.auth.close()
        await app.state.db.dispose()
        logger.info("Backend stopped")


def _make_node_labeler(session_factory: Any) -> Any:
    """Etiqueta de nodo para narrativas (short_name o node_id), con sesión
    propia de solo lectura — reutilizable por admin y alertas."""

    async def labeler(node_id: str) -> str:
        async with session_factory() as session:
            node = await SqlNodeRepository(session).get(node_id)
        return node.short_name if node is not None and node.short_name else node_id

    return labeler


def _make_alert_narrator(session_factory: Any) -> Any:
    """Listener del motor de alertas para el diario operativo (Actividad 2.0
    Fase 1): traduce transiciones a lenguaje de operador. Solo redacta — la
    detección (umbrales, duraciones) vive únicamente en el motor."""
    labeler = _make_node_labeler(session_factory)

    async def narrator(transition: AlertTransition) -> None:
        if transition.rule is None:
            return
        a = transition.alert
        label = await labeler(a.subject_id) if a.subject_type == "node" else a.subject_id
        event = render_alert_transition(
            transition.rule.rule_type, transition.kind, a.subject_type, a.subject_id, label, a.message
        )
        if event is not None:
            await activity.emit_activity(event)

    return narrator


async def _ws_alert_broadcaster(transition: AlertTransition) -> None:
    a = transition.alert
    await hub.broadcast(
        make_event_envelope(
            f"alert.{transition.kind}",
            {
                "alert_id": a.id,
                "rule_name": a.rule_name,
                "severity": a.severity,
                "subject_type": a.subject_type,
                "subject_id": a.subject_id,
                "message": a.message,
            },
        )
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
    app.include_router(auth_router.router, prefix=settings.api_v1_prefix)
    app.include_router(nodes.router, prefix=settings.api_v1_prefix)
    app.include_router(gateways.router, prefix=settings.api_v1_prefix)
    app.include_router(system.router, prefix=settings.api_v1_prefix)
    app.include_router(dashboard.router, prefix=settings.api_v1_prefix)
    app.include_router(alerts.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_operations.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_remote_flags.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_config.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_batches.router, prefix=settings.api_v1_prefix)
    app.include_router(admin_profiles.router, prefix=settings.api_v1_prefix)
    app.include_router(organization.router, prefix=settings.api_v1_prefix)
    app.include_router(activity_router.router, prefix=settings.api_v1_prefix)
    app.include_router(chat.router, prefix=settings.api_v1_prefix)
    app.include_router(topology.router, prefix=settings.api_v1_prefix)
    app.include_router(ws_router)
    return app


app = create_app()
