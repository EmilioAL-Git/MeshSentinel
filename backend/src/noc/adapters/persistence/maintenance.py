"""Reinicio de fábrica de la NodeDB (mantenimiento manual, nunca automático).

`SqlNodeRepository.delete_all()` ya borra los nodos y su historia PROPIA
(posiciones/telemetría/vecinos/enlaces/tags/membresías/chat). Este módulo va
más allá, a petición explícita del usuario ("como si la instalación fuera de
fábrica"): borra también todo rastro HISTÓRICO derivado de esos nodos que
`delete_all` deja intacto a propósito (alertas, operaciones/lotes de
administración, operaciones Nexus, diario de actividad) — nada de eso tiene
sentido ya sin los nodos a los que se refería.

Configuración NO se toca: gateways, grupos/tags (definiciones), reglas de
alerta globales o por grupo, canales/integraciones de notificación, perfiles
de configuración, usuarios, ajustes Nexus. Solo se eliminan las reglas
escopadas a un nodo concreto (`AlertRule.node_id`), porque su sujeto
desaparece con el reset y quedarían huérfanas para siempre.
"""

from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from noc.adapters.persistence.models import (
    ActivityLogModel,
    AdminBatchModel,
    AdminOperationModel,
    AlertModel,
    AlertRuleChannelModel,
    AlertRuleModel,
    NexusOperationModel,
    NexusOperationResponseModel,
)
from noc.adapters.persistence.repositories import SqlNodeRepository


@dataclass(slots=True)
class NodeDbResetCounts:
    nodes: int
    alerts: int
    node_scoped_rules: int
    admin_operations: int
    admin_batches: int
    nexus_operations: int
    activity_log: int


async def _count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def reset_node_db(session: AsyncSession) -> NodeDbResetCounts:
    # Alertas: TODO el histórico (activas/reconocidas/resueltas), referencien
    # o no un nodo — junto con las reglas escopadas a un nodo (mutuamente
    # excluyentes con group_id, ADR de reglas §1.3), cuyo sujeto ya no existirá.
    alerts = await _count(session, AlertModel)
    await session.execute(delete(AlertModel))

    scoped_rule_ids = list(
        (
            await session.scalars(
                select(AlertRuleModel.id).where(AlertRuleModel.node_id.is_not(None))
            )
        ).all()
    )
    if scoped_rule_ids:
        await session.execute(
            delete(AlertRuleChannelModel).where(AlertRuleChannelModel.rule_id.in_(scoped_rule_ids))
        )
        await session.execute(delete(AlertRuleModel).where(AlertRuleModel.id.in_(scoped_rule_ids)))

    # Admin: operaciones antes que lotes (FK admin_operations.batch_id).
    admin_operations = await _count(session, AdminOperationModel)
    await session.execute(delete(AdminOperationModel))
    admin_batches = await _count(session, AdminBatchModel)
    await session.execute(delete(AdminBatchModel))

    # Nexus: respuestas antes que operaciones (FK operation_id).
    nexus_operations = await _count(session, NexusOperationModel)
    await session.execute(delete(NexusOperationResponseModel))
    await session.execute(delete(NexusOperationModel))

    # Diario de actividad: el registro persistente entero es historia de
    # tráfico de la malla, sin sentido sin los nodos a los que se refiere.
    activity_log = await _count(session, ActivityLogModel)
    await session.execute(delete(ActivityLogModel))

    nodes = await SqlNodeRepository(session).delete_all()

    return NodeDbResetCounts(
        nodes=nodes,
        alerts=alerts,
        node_scoped_rules=len(scoped_rule_ids),
        admin_operations=admin_operations,
        admin_batches=admin_batches,
        nexus_operations=nexus_operations,
        activity_log=activity_log,
    )
