"""Espaciado de comandos: nunca en ráfaga.

Tres reglas acumulativas, pura aritmética sobre instantes (el reloj lo pone
quien llama, así se testea sin dormir):

1. **5 s entre difusiones** (cooldown de broadcast del firmware). El manual
   v2.8.006 (verificado contra el código fuente, §1) es explícito: los envíos
   dirigidos (`-device`, `-node`) **se saltan** este cooldown — solo se
   aplica entre un envío multi-nodo (difusión/grupo) y el siguiente.
2. **10 s entre comandos consecutivos al mismo destino** (decisión del
   usuario: el nodo necesita tiempo para responder antes del siguiente). Se
   aplica igual a dirigidos y a difusión.
3. **Tiempo de nodo ocupado** (`busy_seconds`): tras REBOOT/FREQSCAN/
   SETLORA... ese destino no recibe nada hasta que termina.

Un destino multi-nodo (difusión/grupo) sigue esperando a que todos los
destinos concretos estén libres (regla 2/3) — eso no lo exime el manual, solo
exime el cooldown de canal (regla 1) a los envíos dirigidos.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from noc.application.nexus.addressing import Target, is_directed, is_multi_node
from noc.application.nexus.builder import NexusCommand

CHANNEL_COOLDOWN = timedelta(seconds=5)
PER_TARGET_SPACING = timedelta(seconds=10)

_ALL = "*"


def target_key(target: Target) -> str:
    return _ALL if is_multi_node(target) else repr(target)


@dataclass(slots=True)
class CommandPacer:
    channel_cooldown: timedelta = CHANNEL_COOLDOWN
    per_target_spacing: timedelta = PER_TARGET_SPACING
    _last_broadcast_send: datetime | None = None
    _target_ready_at: dict[str, datetime] = field(default_factory=dict)

    def next_allowed_at(self, command: NexusCommand, now: datetime) -> datetime:
        candidates = [now]
        # Regla 1: el cooldown de canal solo se aplica a difusión/grupo — los
        # envíos dirigidos lo bypasean (manual v2.8.006 §1).
        if not is_directed(command.target) and self._last_broadcast_send is not None:
            candidates.append(self._last_broadcast_send + self.channel_cooldown)
        key = target_key(command.target)
        if key == _ALL:
            # Una difusión espera a que TODOS los destinos concretos estén libres.
            candidates.extend(self._target_ready_at.values())
        else:
            for k in (key, _ALL):
                if k in self._target_ready_at:
                    candidates.append(self._target_ready_at[k])
        return max(candidates)

    def record_sent(self, command: NexusCommand, at: datetime) -> None:
        if is_multi_node(command.target):
            self._last_broadcast_send = at
        # Poda: los destinos ya libres no aportan nada al cálculo.
        self._target_ready_at = {k: v for k, v in self._target_ready_at.items() if v > at}
        busy = timedelta(seconds=command.busy_seconds)
        self._target_ready_at[target_key(command.target)] = at + max(
            self.per_target_spacing, busy
        )
