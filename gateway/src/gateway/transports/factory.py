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
    if settings.transport == "tcp":
        from gateway.transports.tcp import MeshtasticTcpTransport

        return MeshtasticTcpTransport(emit, settings)
    if settings.transport == "http":
        from gateway.transports.http import MeshtasticHttpTransport

        return MeshtasticHttpTransport(emit, settings)
    if settings.transport == "mqtt":
        from gateway.transports.mqtt import MqttIngestTransport

        return MqttIngestTransport(emit, settings)
    if settings.transport == "idle":
        from gateway.transports.idle import IdleTransport

        return IdleTransport(emit, settings)
    raise NotImplementedError(f"Transport '{settings.transport}' not implemented yet")
