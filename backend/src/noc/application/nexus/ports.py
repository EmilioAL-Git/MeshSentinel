"""Puerto de transporte del módulo (ADR 0027).

La implementación real (siguiente iteración) publicará un comando aditivo
`command.send_text` en el stream `noc:commands:<gateway_id>`; el gateway lo
ejecutará con `sendText` por el canal "Nexus" que detecte en su nodo local.
En tests se sustituye por un doble en memoria.
"""

from typing import Protocol

from noc.application.nexus.builder import NexusCommand


class NexusTransport(Protocol):
    async def send(self, gateway_id: str, command: NexusCommand) -> None: ...
