"""Correlación respuesta → comando.

El firmware no devuelve id de petición: una respuesta se asocia al comando
MÁS RECIENTE que pudo provocarla dentro de su ventana (modelo aprobado por el
usuario). Un comando a `-device !id` solo acepta respuestas de ese nodo;
`-local`, del nodo local del gateway; difusión/grupo/`-node`/`-mac` aceptan
cualquier nodo (el nombre corto o la MAC no se pueden resolver a node_id
aquí sin consultar la NodeDB — cada nodo que conteste es una respuesta
distinta del mismo comando).

Si dos comandos abiertos admiten al mismo nodo, gana el dirigido a él sobre
el multi-nodo, y a igualdad el más reciente.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from noc.application.nexus.addressing import Device, Local, Target
from noc.application.nexus.reassembly import AssembledResponse

# Margen de respuesta: jitter de difusión (hasta 5 s) + paginación a 2 s/página.
DEFAULT_RESPONSE_WINDOW = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class _Pending:
    command_id: str
    target: Target
    sent_at: datetime
    expires_at: datetime
    local_node_id: str | None


@dataclass(slots=True)
class ResponseCorrelator:
    window: timedelta = DEFAULT_RESPONSE_WINDOW
    _pending: list[_Pending] = field(default_factory=list)

    def register(
        self,
        command_id: str,
        target: Target,
        sent_at: datetime,
        busy_seconds: float = 0.0,
        local_node_id: str | None = None,
    ) -> None:
        # Un comando que deja el nodo ocupado (NETSCAN 60 s, REBOOT 20 s...)
        # responde tarde: la ventana se alarga en consecuencia.
        expires = sent_at + self.window + timedelta(seconds=busy_seconds)
        self._pending.append(_Pending(command_id, target, sent_at, expires, local_node_id))

    def match(self, response: AssembledResponse) -> str | None:
        at = response.first_at
        self._pending = [p for p in self._pending if p.expires_at >= at]
        best: tuple[int, datetime, str] | None = None
        for p in self._pending:
            if p.sent_at > at:
                continue
            specificity = self._specificity(p, response.from_node_id)
            if specificity is None:
                continue
            candidate = (specificity, p.sent_at, p.command_id)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
        return best[2] if best else None

    @staticmethod
    def _specificity(p: _Pending, from_node_id: str) -> int | None:
        match p.target:
            case Device(node_id=node_id):
                return 1 if node_id == from_node_id else None
            case Local():
                return 1 if p.local_node_id == from_node_id else None
        return 0
