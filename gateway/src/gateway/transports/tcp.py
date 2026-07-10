"""Transporte TCP (ADR 0023): nodo Meshtastic accesible por red (WiFi/Ethernet,
puerto 4403 del firmware).

`TCPInterface` hereda de la misma `StreamInterface` que `SerialInterface` y
publica exactamente los mismos topics PyPubSub, así que TODO el comportamiento
(reconexión, snapshot, telemetría, pipeline admin) es el heredado de
`MeshtasticStreamTransport` sin ninguna lógica propia — la única diferencia
es cómo se crea la interfaz. No hay autodetección posible: el host es
configuración obligatoria (a diferencia de USB, se valida al construir el
transporte para que un test de conexión falle al instante, no tras backoff).

Limitación del firmware a tener en cuenta al operar: un nodo solo admite UN
cliente TCP simultáneo — si la app oficial u otro proceso está conectado, la
conexión se rechazará o expulsará a la anterior.
"""

from typing import Any

from gateway.config import Settings
from gateway.transports.base import EmitFn
from gateway.transports.meshtastic_stream import MeshtasticStreamTransport


class MeshtasticTcpTransport(MeshtasticStreamTransport):
    name = "tcp"

    def __init__(self, emit: EmitFn, settings: Settings) -> None:
        if not settings.tcp_host:
            raise ValueError("TCP transport requires a host (GATEWAY_TCP_HOST / connection_params.host)")
        super().__init__(emit, settings)

    def _connect_blocking(self) -> Any:
        from meshtastic.tcp_interface import TCPInterface

        return TCPInterface(
            hostname=self._settings.tcp_host,
            portNumber=self._settings.tcp_port,
        )

    def _endpoint_description(self) -> str:
        return f"{self._settings.tcp_host}:{self._settings.tcp_port}"
