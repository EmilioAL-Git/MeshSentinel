"""Prefijo, sufijos de direccionamiento e identificadores hex (§1 del documento).

Decisiones del usuario (2026-09-27): prefijo SIEMPRE `/nexus` (el único que
admite sufijos dirigidos también en firmware anterior a v267) y, para un nodo
concreto, `-device !id` (el único direccionamiento sin ambigüedad). Los demás
sufijos se soportan porque el documento los define, pero la UI debería
preferir `Device`.
"""

import re
from dataclasses import dataclass

DEFAULT_PREFIX = "/nexus"
# Equivalentes entre sí (§1.1). Solo se usan para RECONOCER texto de comando
# ajeno (otro operador mandando /jt ...), nunca para construir.
KNOWN_PREFIXES = ("/nexus", "/jt", "/jent", "/jentastic")

_HEX8 = re.compile(r"^[0-9a-f]{8}$")
# El manual v2.8.006 (verificado contra el código fuente) llama al parámetro
# "<mac6>" — 6 caracteres hex (3 bytes), no 4 (2 bytes) como se había dejado
# sin confirmar en la iteración anterior.
_MAC6 = re.compile(r"^[0-9a-f]{6}$")
_COMMAND_TEXT = re.compile(
    r"^(" + "|".join(re.escape(p) for p in KNOWN_PREFIXES) + r")(-[a-z]+)?(\s|$)",
    re.IGNORECASE,
)


class NexusAddressError(ValueError):
    pass


def normalize_node_id(raw: str) -> str:
    """Parser tolerante de §1.3 → forma canónica del proyecto `!xxxxxxxx`.

    Acepta `!e53626b0`, `0xe53626b0`, `xe53626b0` y `e53626b0`.
    """
    value = raw.strip().lower()
    for prefix in ("!", "0x", "x"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    if not _HEX8.match(value):
        raise NexusAddressError(f"identificador de nodo no válido: {raw!r}")
    return f"!{value}"


def zero_hop_suffix(raw: str) -> str:
    """`ZH ADD/DEL` esperan SOLO los 2 últimos caracteres hex del ID (§1.3).

    Decisión del usuario: se envían tal cual, sin `0x` (`!e53626b0` → `b0`).
    """
    return normalize_node_id(raw)[-2:]


# --- Destinos (§1.2) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Broadcast:
    """Todos los nodos Nexus del canal."""


@dataclass(frozen=True, slots=True)
class Local:
    """El propio nodo emisor (el nodo local del gateway)."""


@dataclass(frozen=True, slots=True)
class Device:
    node_id: str  # canónico, !xxxxxxxx

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", normalize_node_id(self.node_id))


@dataclass(frozen=True, slots=True)
class ShortName:
    name: str


@dataclass(frozen=True, slots=True)
class Mac:
    last_bytes: str  # 6 hex = últimos 3 bytes de la MAC (manual v2.8.006, "<mac6>")

    def __post_init__(self) -> None:
        value = self.last_bytes.strip().lower()
        if not _MAC6.match(value):
            raise NexusAddressError(f"MAC no válida (6 hex): {self.last_bytes!r}")
        object.__setattr__(self, "last_bytes", value)


@dataclass(frozen=True, slots=True)
class Group:
    name: str


Target = Broadcast | Local | Device | ShortName | Mac | Group


def _plain_token(value: str, what: str) -> str:
    value = value.strip()
    if not value or any(c.isspace() for c in value) or ";" in value:
        raise NexusAddressError(f"{what} no válido: {value!r}")
    return value


def render_prefix(target: Target, prefix: str = DEFAULT_PREFIX) -> str:
    """Cabeza del comando: prefijo + sufijo de direccionamiento."""
    match target:
        case Broadcast():
            return prefix
        case Local():
            return f"{prefix}-local"
        case Device(node_id=node_id):
            return f"{prefix}-device {node_id}"
        case ShortName(name=name):
            return f"{prefix}-node {_plain_token(name, 'nombre corto')}"
        case Mac(last_bytes=mac):
            return f"{prefix}-mac {mac}"
        case Group(name=name):
            return f"{prefix}-group {_plain_token(name, 'grupo')}"
    raise NexusAddressError(f"destino desconocido: {target!r}")


def is_multi_node(target: Target) -> bool:
    """Destinos que pueden alcanzar a varios nodos a la vez."""
    return isinstance(target, Broadcast | Group)


def is_directed(target: Target) -> bool:
    """¿Se salta el cooldown de difusión? Confirmado por el manual v2.8.006
    (§1, tabla de prefijos): `-device` y `-node` "Bypasses broadcast
    cooldown" explícitamente. `-mac` y `-local` no se mencionan ahí, pero por
    ser igualmente direccionamiento a un único destino se tratan igual —
    PENDIENTE de confirmar `-mac`/`-local` con una prueba real si hiciera
    falta afinarlo."""
    return isinstance(target, Device | ShortName | Mac | Local)


def is_command_text(text: str) -> bool:
    """¿Es este texto un comando Nexus (propio o de otro operador)?

    El ensamblador de respuestas lo usa para no confundir un comando que
    viaja por el canal con la respuesta de un nodo.
    """
    return bool(_COMMAND_TEXT.match(text.strip()))
