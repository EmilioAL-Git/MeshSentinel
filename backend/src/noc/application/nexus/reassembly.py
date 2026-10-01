"""Reensamblado de respuestas paginadas y deduplicación (§4 del documento).

- Paginación: las respuestas largas llegan troceadas con cabeceras `P1:`,
  `P2:`… y 2 s entre partes. El documento NO dice si la cabecera indica el
  total, así que el fin de una respuesta se detecta por SILENCIO
  (`quiet`, por defecto 8 s = varias veces el intervalo entre páginas), o
  porque el mismo nodo empieza otra respuesta (página repetida).
  PENDIENTE: ajustar `PAGE_HEADER` y el criterio de fin con capturas reales
  (si resulta ser `P1/3:`, el total permite cerrar sin esperar).
- Doble copia: el mismo texto puede llegar dos veces (copia al móvil local +
  malla, u oído por dos pasarelas). Se descarta por (nodo, `packet_id`) —
  mismo paquete oído dos veces — y por (nodo, texto) dentro de
  `dedupe_window` — la copia al móvil local es OTRO paquete con otro id
  (confirmado con captura real), solo la delata el texto. La ventana (8 s,
  medida contra una duplicación real de 5.36 s) se queda corta del
  espaciado de 10 s entre comandos al mismo destino de pacing.py, así que
  no debería confundir la respuesta de un comando con la del siguiente.
- Solo se agrupa por nodo emisor: el jitter de 100 ms–5 s de las respuestas en
  difusión (§4) no rompe nada porque cada nodo tiene su propio buffer.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from noc.application.nexus.addressing import is_command_text

PAGE_HEADER = re.compile(r"^P(\d+):\s?(.*)$", re.DOTALL)
# Aviso del firmware que acompaña a una respuesta paginada («JT: Paging
# favorites to mesh...», con el marcador 🟢/🔴 delante). NO es contenido ni
# una marca de fin fiable: en capturas reales llegó después de las páginas
# (FAVS/IGNORED/SENSORS) pero también ENTRE `P1` y `P2` (2026-10-01, FAVS).
# Por eso solo se descarta: nunca resuelve una operación por sí mismo ni
# cierra el buffer; el fin sigue siendo el silencio de `quiet`. Si no llega
# ninguna página, tras `quiet` se entrega como mensaje normal (p. ej. HELP).
MARKER = re.compile(r"^[\U0001F7E2\U0001F534]\s*")
PAGING_TRAILER = re.compile(r"^(?:[\U0001F7E2\U0001F534]\s*)?JT:\s*Paging\b", re.I)
DEFAULT_QUIET = timedelta(seconds=8)
# Captura real (2026-09-28, nodos X1→T1000): la doble copia (móvil local +
# malla) de una respuesta idéntica llegó con 5.36 s de diferencia — por
# encima de los 5 s que se habían estimado sin datos. 8 s da margen sin
# acercarse a los 10 s de espaciado entre comandos al mismo destino.
DEFAULT_DEDUPE_WINDOW = timedelta(seconds=8)


@dataclass(frozen=True, slots=True)
class IncomingText:
    from_node_id: str
    text: str
    received_at: datetime
    packet_id: int | None = None


@dataclass(frozen=True, slots=True)
class AssembledResponse:
    from_node_id: str
    text: str
    first_at: datetime
    last_at: datetime
    pages: tuple[int, ...] = ()  # vacío = respuesta de un solo mensaje
    missing_pages: tuple[int, ...] = ()  # huecos detectados (P1, P3 → falta 2)

    @property
    def paginated(self) -> bool:
        return bool(self.pages)


@dataclass(slots=True)
class _Buffer:
    first_at: datetime
    last_at: datetime
    pages: dict[int, str] = field(default_factory=dict)

    def assemble(self, node_id: str) -> AssembledResponse:
        numbers = tuple(sorted(self.pages))
        missing = tuple(n for n in range(1, numbers[-1] + 1) if n not in self.pages)
        return AssembledResponse(
            from_node_id=node_id,
            # SIN separador: el firmware trocea su propio string de salida a
            # ciegas (confirmado con captura real: una página puede terminar
            # a mitad de un ID de nodo y la siguiente empezar con el resto,
            # p. ej. "...!e5f720" + "35:N007:..." → "...!af000009:N007:...").
            # Unir con "\n" insertaría un salto de línea falso ahí.
            text="".join(self.pages[n] for n in numbers),
            first_at=self.first_at,
            last_at=self.last_at,
            pages=numbers,
            missing_pages=missing,
        )


@dataclass(slots=True)
class ResponseAssembler:
    quiet: timedelta = DEFAULT_QUIET
    dedupe_window: timedelta = DEFAULT_DEDUPE_WINDOW
    _buffers: dict[str, _Buffer] = field(default_factory=dict)
    _seen: dict[tuple[str, int | str], datetime] = field(default_factory=dict)
    # Avisos «Paging…» sin páginas todavía, por nodo: (mensaje, instante).
    _orphan_trailers: dict[str, IncomingText] = field(default_factory=dict)

    def _is_duplicate(self, msg: IncomingText) -> bool:
        horizon = msg.received_at - self.dedupe_window
        self._seen = {k: t for k, t in self._seen.items() if t >= horizon}
        keys: list[tuple[str, int | str]] = [(msg.from_node_id, msg.text)]
        if msg.packet_id is not None:
            keys.append((msg.from_node_id, msg.packet_id))
        duplicate = any(k in self._seen for k in keys)
        for k in keys:
            self._seen[k] = msg.received_at
        return duplicate

    def feed(self, msg: IncomingText) -> list[AssembledResponse]:
        """Procesa un texto entrante; devuelve las respuestas que queden completas."""
        if is_command_text(msg.text) or self._is_duplicate(msg):
            return []

        if PAGING_TRAILER.match(msg.text):
            # Con páginas ya abiertas se descarta (el contenido real está en
            # ellas); sin ellas se retiene por si las páginas llegan después.
            buffer = self._buffers.get(msg.from_node_id)
            if buffer is not None:
                buffer.last_at = msg.received_at
            else:
                self._orphan_trailers[msg.from_node_id] = msg
            return []

        match = PAGE_HEADER.match(msg.text)
        if match is None:
            return [
                AssembledResponse(msg.from_node_id, msg.text, msg.received_at, msg.received_at)
            ]

        number, body = int(match.group(1)), match.group(2)
        self._orphan_trailers.pop(msg.from_node_id, None)  # las páginas llegaron
        done: list[AssembledResponse] = []
        buffer = self._buffers.get(msg.from_node_id)
        # Cierra la anterior si la página ya estaba (una respuesta nueva vuelve
        # a empezar) o si el nodo llevaba en silencio más de `quiet`. Un `P1`
        # a secas NO basta: con saltos distintos puede llegar tras `P3`.
        if buffer is not None and (
            number in buffer.pages or msg.received_at - buffer.last_at >= self.quiet
        ):
            done.append(buffer.assemble(msg.from_node_id))
            buffer = None
        if buffer is None:
            buffer = self._buffers[msg.from_node_id] = _Buffer(msg.received_at, msg.received_at)
        buffer.pages[number] = body
        buffer.last_at = msg.received_at
        return done

    def flush_expired(self, now: datetime) -> list[AssembledResponse]:
        """Cierra las respuestas paginadas sin páginas nuevas desde hace `quiet`."""
        expired = [n for n, b in self._buffers.items() if now - b.last_at >= self.quiet]
        out = [self._buffers.pop(n).assemble(n) for n in expired]
        for node, trailer in list(self._orphan_trailers.items()):
            if now - trailer.received_at >= self.quiet:
                del self._orphan_trailers[node]
                out.append(AssembledResponse(node, trailer.text, trailer.received_at, trailer.received_at))
        return out
