from gateway.config import Settings
from gateway.transports.base import EmitFn, Transport
from gateway.transports.simulated import SimulatedTransport


def create_transport(settings: Settings, emit: EmitFn) -> Transport:
    if settings.transport == "simulated":
        return SimulatedTransport(emit, settings)
    # serial / tcp / http: Fase 1 (envuelven la librería oficial `meshtastic`)
    raise NotImplementedError(f"Transport '{settings.transport}' not implemented yet (Fase 1)")
