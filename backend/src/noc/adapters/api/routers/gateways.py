"""API de gestión de gateways (M5, ADR 0021).

Lectura (`GET`) va contra la BD directamente (igual que el resto de la API);
las acciones que implican al proceso gateway (`discover`, `test-connection`,
`configure`, `connect`, `disconnect`) pasan por `GatewayService`
(`request.app.state.gateways`), que dirige comandos por el stream ya
existente (ADR 0003) y correla las respuestas de descubrimiento/prueba.
"""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from noc.adapters.api.deps import SessionDep
from noc.adapters.api.schemas import GatewayOut
from noc.adapters.persistence.organization_repositories import SqlGroupRepository
from noc.adapters.persistence.repositories import (
    SqlGatewayRepository,
    SqlNodeGatewayLinkRepository,
    SqlNodeRepository,
)
from noc.application.gateway_stats import GatewayStats, compute_multi_gateway_stats, scope_to_members
from noc.application.gateways.service import GatewayService
from noc.config import get_settings

router = APIRouter(prefix="/gateways", tags=["gateways"])


def _service(request: Request) -> GatewayService:
    return request.app.state.gateways


class DeviceOut(BaseModel):
    port: str
    description: str | None = None
    vid: str | None = None
    pid: str | None = None
    serial_number: str | None = None


class TestConnectionIn(BaseModel):
    transport_type: str = Field(pattern="^(usb|tcp|http|simulated)$")
    connection_params: dict[str, Any] = Field(default_factory=dict)


class TestConnectionOut(BaseModel):
    ok: bool
    error: str | None = None
    local_node_id: str | None = None
    local_short_name: str | None = None
    local_long_name: str | None = None
    local_hw_model: str | None = None
    local_firmware_version: str | None = None


class GatewayConfigureIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    transport_type: str = Field(pattern="^(usb|tcp|http|simulated)$")
    connection_params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    priority: int = 0


class GatewayUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    transport_type: str | None = Field(default=None, pattern="^(usb|tcp|http|simulated)$")
    connection_params: dict[str, Any] | None = None
    enabled: bool | None = None
    priority: int | None = None


@router.get("", response_model=list[GatewayOut])
async def list_gateways(session: SessionDep, include_deleted: bool = Query(False)) -> list[GatewayOut]:
    gateways = await SqlGatewayRepository(session).list_all(include_deleted)
    return [GatewayOut.from_entity(g) for g in gateways]


class GatewayStatsOut(BaseModel):
    gateway_id: str
    name: str | None
    status: str
    nodes_visible: int
    nodes_exclusive: int
    nodes_shared: int
    primary_for: int
    last_heard_at: datetime | None

    @classmethod
    def from_entity(cls, s: GatewayStats) -> "GatewayStatsOut":
        return cls(**{f: getattr(s, f) for f in cls.model_fields})


class MultiGatewayStatsOut(BaseModel):
    generated_at: datetime
    nodes_observed: int
    nodes_shared: int
    redundancy_percent: float
    gateways: list[GatewayStatsOut]


# Registrada ANTES de GET /gateways/{gateway_id}: "stats" no es un gateway_id.
@router.get("/stats", response_model=MultiGatewayStatsOut)
async def gateway_stats(session: SessionDep, group_id: int | None = Query(None)) -> MultiGatewayStatsOut:
    """Métricas Multi-Gateway (M6.2): nodos visibles/exclusivos/compartidos y
    última actividad por pasarela, más redundancia global. Los nodos ignorados
    quedan fuera, igual que en el resto de agregados del NOC (M1.2).

    `group_id` (Flota orientada a grupos): mismo cálculo, `compute_multi_gateway_stats`
    sin tocar, solo pre-filtrando `nodes`/`links` a los miembros del grupo — las
    pasarelas se listan completas para que el desglose siga siendo legible."""
    settings = get_settings()
    nodes = await SqlNodeRepository(session).list_all()
    links = await SqlNodeGatewayLinkRepository(session).list_all()
    if group_id is not None:
        member_ids = set(await SqlGroupRepository(session).members(group_id))
        nodes, links = scope_to_members(nodes, links, member_ids)
    stats = compute_multi_gateway_stats(
        links=links,
        gateways=await SqlGatewayRepository(session).list_all(),
        nodes=nodes,
        offline_threshold_seconds=settings.node_offline_after_seconds,
        now=datetime.now(timezone.utc),
    )
    return MultiGatewayStatsOut(
        generated_at=stats.generated_at,
        nodes_observed=stats.nodes_observed,
        nodes_shared=stats.nodes_shared,
        redundancy_percent=stats.redundancy_percent,
        gateways=[GatewayStatsOut.from_entity(g) for g in stats.gateways],
    )


@router.get("/{gateway_id}", response_model=GatewayOut)
async def get_gateway(gateway_id: str, session: SessionDep) -> GatewayOut:
    gateway = await SqlGatewayRepository(session).get(gateway_id)
    if gateway is None:
        raise HTTPException(status_code=404, detail="Gateway not found")
    return GatewayOut.from_entity(gateway)


@router.post("/{gateway_id}/discover", response_model=list[DeviceOut])
async def discover_devices(gateway_id: str, request: Request) -> list[DeviceOut]:
    devices = await _service(request).discover(gateway_id)
    return [DeviceOut(**d) for d in devices]


@router.post("/{gateway_id}/test-connection", response_model=TestConnectionOut)
async def test_connection(gateway_id: str, body: TestConnectionIn, request: Request) -> TestConnectionOut:
    result = await _service(request).test_connection(gateway_id, body.transport_type, body.connection_params)
    return TestConnectionOut(**{f: result.get(f) for f in TestConnectionOut.model_fields})


@router.post("/{gateway_id}/configure", response_model=GatewayOut)
async def configure_gateway(gateway_id: str, body: GatewayConfigureIn, request: Request) -> GatewayOut:
    info = await _service(request).configure(
        gateway_id, body.name, body.transport_type, body.connection_params, body.enabled, body.priority
    )
    return GatewayOut.from_entity(info)


@router.post("/{gateway_id}/import", response_model=GatewayOut)
async def import_gateway(gateway_id: str, request: Request) -> GatewayOut:
    info = await _service(request).import_legacy(gateway_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Gateway not found")
    return GatewayOut.from_entity(info)


@router.put("/{gateway_id}", response_model=GatewayOut)
async def update_gateway(gateway_id: str, body: GatewayUpdateIn, request: Request) -> GatewayOut:
    info = await _service(request).update(
        gateway_id, body.name, body.transport_type, body.connection_params, body.enabled, body.priority
    )
    if info is None:
        raise HTTPException(status_code=404, detail="Gateway not configured yet")
    return GatewayOut.from_entity(info)


@router.post("/{gateway_id}/connect", response_model=GatewayOut)
async def connect_gateway(gateway_id: str, request: Request) -> GatewayOut:
    info = await _service(request).connect(gateway_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Gateway not configured yet")
    return GatewayOut.from_entity(info)


@router.post("/{gateway_id}/disconnect", response_model=GatewayOut)
async def disconnect_gateway(gateway_id: str, request: Request) -> GatewayOut:
    info = await _service(request).disconnect(gateway_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Gateway not configured yet")
    return GatewayOut.from_entity(info)


@router.delete("/{gateway_id}", status_code=204)
async def delete_gateway(gateway_id: str, request: Request) -> None:
    deleted = await _service(request).delete(gateway_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Gateway not configured yet")
