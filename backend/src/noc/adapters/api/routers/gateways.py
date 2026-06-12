from fastapi import APIRouter

from noc.adapters.api.deps import SessionDep
from noc.adapters.api.schemas import GatewayOut
from noc.adapters.persistence.repositories import SqlGatewayRepository

router = APIRouter(prefix="/gateways", tags=["gateways"])


@router.get("", response_model=list[GatewayOut])
async def list_gateways(session: SessionDep) -> list[GatewayOut]:
    gateways = await SqlGatewayRepository(session).list_all()
    return [GatewayOut.from_entity(g) for g in gateways]
