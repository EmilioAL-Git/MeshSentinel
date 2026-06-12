from gateway.config import Settings
from gateway.transports.base import EmitFn, Transport
from gateway.transports.simulated import SimulatedTransport


def create_transport(settings: Settings, emit: EmitFn) -> Transport:
    if settings.transport == "simulated":
        return SimulatedTransport(emit, settings)
    if settings.transport == "usb":
        # Import perezoso: la librería meshtastic es pesada y solo se necesita aquí
        from gateway.transports.usb import MeshtasticUsbTransport

        return MeshtasticUsbTransport(emit, settings)
    # tcp / http: fases futuras
    raise NotImplementedError(f"Transport '{settings.transport}' not implemented yet")
