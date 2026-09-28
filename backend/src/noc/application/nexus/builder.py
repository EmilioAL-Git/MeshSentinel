"""Constructor de comandos: catálogo + destino + argumentos → texto listo para enviar.

Aplica sin que el operador lo sepa las reglas del documento que tienen
consecuencias en el texto (truncado de `ZH ADD/DEL`, §1.3) y rechaza lo que el
firmware bloquearía igualmente (NAME/OWNER/REVERT en difusión, §2.2) para que
el error aparezca en la UI y no como silencio en la malla.

**`-device !id`**: deshabilitado por DEFECTO (decisión del usuario,
2026-09-28) tras dos tandas de pruebas de campo contra el T1000 real (20
comandos `-device` seguidos, 0 respuestas) frente a `-node`/difusión
(funcionaron siempre) — el `node_id` se regenera desde firmware 2.8 a
partir de la clave pública y puede cambiar al reflashear, así que es
frágil por diseño, no un fallo puntual. Reincorporado como OPCIÓN
consciente (2026-09-29, pedido explícito del usuario, que confirmó conocer
la causa: "eso falló porque al actualizar mi nodo se cambió el id") — el
propio `build_command` ya NO lo rechaza (es un target válido del protocolo,
`addressing.Device`); la decisión de si usarlo vive en la capa de ajustes
(`application/nexus_settings.py`, clave `addressing_mode`), que solo
controla qué opción viene PRESELECCIONADA en la UI — el operador siempre
puede elegir la otra a mano. `-node <shortname>` (`ShortName`) sigue siendo
la opción por defecto y la única sin este riesgo conocido.
"""

from dataclasses import dataclass

from noc.application.nexus import catalog
from noc.application.nexus.addressing import (
    DEFAULT_PREFIX,
    Broadcast,
    Target,
    is_multi_node,
    render_prefix,
    zero_hop_suffix,
)

# Límite explícito del prompt v2.8.006 (§B2): 200 caracteres, más estricto que
# el máximo de payload del protocolo (233 bytes) — caso real citado: una
# MACRO SET con 8 "ZH ADD" se truncó a mitad y dejó una entrada corrupta.
MAX_TEXT_CHARS = 200
_ZH_ID_VERBS = frozenset({"ADD", "DEL"})
_REDIRECT_NAMES = frozenset({"R", "REDIRECT"})
_REDIRECT_DESTINATIONS = frozenset({"CH", "DM"})
MAX_REDIRECT_DEPTH = 2  # §B1 prompt v2.8.006


class NexusCommandError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NexusCommand:
    text: str
    spec: catalog.CommandSpec
    args: tuple[str, ...]
    target: Target
    mutates: bool
    destructive: bool  # la UI debe pedir confirmación explícita (modal)
    requires_save: bool  # recordatorio "cambios sin guardar"
    busy_seconds: float  # estado "aplicando…" en vez de timeout prematuro


def _redirect_depth(args: tuple[str, ...]) -> int:
    """Profundidad de un `R`/`REDIRECT` cuyo comando envuelto es OTRO redirect.

    `R CH <id> STATS` tiene profundidad 1. `R CH <id> R DM <id> STATS` tiene
    profundidad 2 (el máximo permitido, §B1). Cuenta cuántas veces aparece un
    token `R`/`REDIRECT` seguido de un destino válido (`CH`/`DM`) dentro de
    los argumentos, más el nivel inicial.
    """
    depth = 1
    tokens = [a.upper() for a in args]
    for i, token in enumerate(tokens[:-1]):
        if token in _REDIRECT_NAMES and tokens[i + 1] in _REDIRECT_DESTINATIONS:
            depth += 1
    return depth


def _normalize_args(spec: catalog.CommandSpec, args: tuple[str, ...]) -> tuple[str, ...]:
    for arg in args:
        # `;` encadena comandos en el firmware: nunca dentro de un argumento.
        if not arg or ";" in arg or "\n" in arg:
            raise NexusCommandError(f"argumento no válido: {arg!r}")
    if spec.name == "ZH" and len(args) >= 2 and args[0].upper() in _ZH_ID_VERBS:
        return (args[0].upper(), zero_hop_suffix(args[1]), *args[2:])
    if spec.name in _REDIRECT_NAMES and _redirect_depth(args) > MAX_REDIRECT_DEPTH:
        raise NexusCommandError(
            f"REDIRECT anidado supera la profundidad máxima ({MAX_REDIRECT_DEPTH})"
        )
    return args


def build_command(
    command: str,
    args: tuple[str, ...] | list[str] = (),
    target: Target | None = None,
    prefix: str = DEFAULT_PREFIX,
) -> NexusCommand:
    spec = catalog.resolve(command)
    if spec is None:
        raise NexusCommandError(f"comando no soportado: {command!r}")
    target = target if target is not None else Broadcast()
    if spec.broadcast_forbidden and is_multi_node(target):
        raise NexusCommandError(
            f"{spec.name} está bloqueado en difusión por el firmware: elige un nodo concreto"
        )

    clean = _normalize_args(spec, tuple(a.strip() for a in args))
    text = " ".join((render_prefix(target, prefix), spec.name, *clean))
    if len(text) > MAX_TEXT_CHARS:
        raise NexusCommandError(f"el comando supera {MAX_TEXT_CHARS} caracteres")

    return NexusCommand(
        text=text,
        spec=spec,
        args=clean,
        target=target,
        mutates=catalog.mutates(spec, clean),
        destructive=catalog.is_destructive(spec, clean),
        requires_save=catalog.requires_save(spec, clean),
        busy_seconds=spec.busy_seconds,
    )
