import uuid
from datetime import datetime, timezone

from noc.adapters.persistence.activity_repositories import SqlActivityLogRepository
from noc.adapters.persistence.admin_repositories import (
    SqlAdminBatchRepository,
    SqlAdminOperationRepository,
)
from noc.adapters.persistence.alert_repositories import SqlAlertRepository, SqlAlertRuleRepository
from noc.adapters.persistence.maintenance import reset_node_db
from noc.adapters.persistence.nexus_repositories import (
    SqlNexusOperationRepository,
    SqlNexusOperationResponseRepository,
)
from noc.adapters.persistence.repositories import SqlNodeRepository
from noc.application.ingest import IngestService
from noc.domain.admin.entities import AdminBatch, AdminOperation
from noc.domain.alerts.entities import Alert, AlertRule
from noc.domain.nexus.entities import NexusOperation, NexusOperationResponse

NODE = "!00000001"


def make_event(event_type: str, payload: dict) -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": "gw-a",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


async def test_reset_node_db_wipes_everything_derived_from_nodes(session_factory):
    """Reinicio de fábrica (a petición del usuario): además de la NodeDB
    propiamente dicha, borra alertas, operaciones/lotes de admin, operaciones
    Nexus y el diario — pero deja intactas las reglas globales/por grupo."""
    ingest = IngestService(session_factory)
    await ingest.handle_event(
        make_event("node.seen", {"node_id": NODE, "short_name": "ALFA", "hw_model": "TBEAM"})
    )

    async with session_factory() as session, session.begin():
        # Regla global (debe sobrevivir) + regla escopada a este nodo (huérfana tras el reset)
        await SqlAlertRuleRepository(session).create(
            AlertRule(name="global", rule_type="low_battery", severity="WARNING")
        )
        scoped_rule = await SqlAlertRuleRepository(session).create(
            AlertRule(name="solo-alfa", rule_type="low_battery", severity="WARNING", node_id=NODE)
        )
        await SqlAlertRepository(session).create(
            Alert(
                rule_id=scoped_rule.id, rule_name=scoped_rule.name, subject_type="node",
                subject_id=NODE, severity="WARNING", message="batería baja",
            )
        )
        batch = await SqlAdminBatchRepository(session).create(
            AdminBatch(name="lote", operation_type="owner.set", node_ids=[NODE])
        )
        await SqlAdminOperationRepository(session).create(
            AdminOperation(target_node_id=NODE, gateway_id="gw-a", operation_type="owner.set", batch_id=batch.id)
        )
        nexus_op = await SqlNexusOperationRepository(session).create(
            NexusOperation(gateway_id="gw-a", target_kind="node", target_value="ALFA", command_name="INFO")
        )
        await SqlNexusOperationResponseRepository(session).add(
            NexusOperationResponse(operation_id=nexus_op.id, from_node_id=NODE, response_text="ok", response_kind="raw")
        )
        await SqlActivityLogRepository(session).add_many(
            [make_event("activity.event", {"node_id": NODE, "source": "mesh", "severity": "info"})]
        )

    async with session_factory() as session:
        counts = await reset_node_db(session)
        await session.commit()

    assert counts.nodes == 1
    assert counts.alerts == 1
    assert counts.node_scoped_rules == 1
    assert counts.admin_operations == 1
    assert counts.admin_batches == 1
    assert counts.nexus_operations == 1
    assert counts.activity_log == 1

    async with session_factory() as session:
        assert await SqlNodeRepository(session).list_all() == []
        rules = await SqlAlertRuleRepository(session).list_all()
        assert [r.name for r in rules] == ["global"]
        assert await SqlAlertRepository(session).list_alerts(None, 100) == []
        assert await SqlActivityLogRepository(session).count() == 0

    # Idempotente: repetir sobre una instalación ya "de fábrica" no falla
    async with session_factory() as session:
        again = await reset_node_db(session)
        await session.commit()
    assert again.nodes == 0
    assert again.alerts == 0
