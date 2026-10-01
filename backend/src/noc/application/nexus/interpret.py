"""Interpretación de respuestas Nexus a frases de operador (puro, sin SQL).

Dado el comando que se mandó y el texto crudo con que contestó un nodo,
produce una `Interpretation`: resultado (ok/error/info), efecto sobre las
listas conocidas del nodo (favoritos/ignorados) y una frase en español —
"Nodo X ignorado correctamente" en vez de "JT: Updated node ...".

Honestidad de formatos: solo `FAV`/`UNFAV` (captura real: "JT: Updated node
<hex8> (<shortname>)"), `ZH ADD/DEL`, `FAVS`/`IGNORED`/`ZH LIST` y el aviso
de comando desconocido tienen formato confirmado por hardware. `IGNORE`/
`UNIGNORE` (captura real 2026-10-01: «JT: Updated node !id (SN)», igual que
FAV; sin id conocido: «JT: Node '!id' not found») se aceptan además por
patrón tolerante ("ignor" en la respuesta) y NUNCA se da por bueno un texto
que no encaje — queda sin interpretar (None) y se muestra el crudo.
"""

import re
from dataclasses import dataclass
from typing import Any

from noc.application.nexus.parsers import parse_response

OK = "ok"
ERROR = "error"
INFO = "info"

# comando → (tipo de lista, presente tras el comando)
FLAG_COMMANDS: dict[str, tuple[str, bool]] = {
    "FAV": ("favorite", True),
    "UNFAV": ("favorite", False),
    "IGNORE": ("ignored", True),
    "UNIGNORE": ("ignored", False),
}

# Variantes forzadas: captura real (2026-10-01, firmware 2.8.005): FIGNORE
# responde «Updated node» pero IGNORED sigue VACÍO (no ignora, ni siquiera
# en un segundo intento); sobre un id desconocido responde «Node … not
# found»; FUNIGNORE responde «Forced node !id (SN)» y con un id desconocido
# CREA un nodo «UNK» en la NodeDB. Su confirmación NO prueba el efecto, así
# que nunca modifican las listas conocidas — se informa y se remite a leer.
# Lista de ignorados persistente (NIGN, vault) — distinta de la de IGNORE (RAM).
NIGN_FLAG = "nign"

FORCED_COMMANDS = frozenset({"FFAV", "FUNFAV", "FIGNORE", "FUNIGNORE"})

_NODE_ID_RE = re.compile(r"^!?([0-9a-fA-F]{8})$")
_ERROR_RE = re.compile(r"unknown|error|fail|invalid|usage|not found|no encontr|denied|unauthor|reject", re.I)
_MARKERS = "🟢🔴"


@dataclass(frozen=True, slots=True)
class Interpretation:
    command: str
    outcome: str  # ok | error | info
    summary: str
    # Efecto sobre la lista conocida del nodo que respondió (solo si outcome=ok)
    flag_type: str | None = None  # favorite | ignored
    flag_present: bool | None = None
    subject_node_id: str | None = None
    subject_short_name: str | None = None
    data: dict[str, Any] | None = None


def canonical_node_id(arg: str | None) -> str | None:
    if not arg:
        return None
    m = _NODE_ID_RE.match(arg.strip())
    return f"!{m.group(1).lower()}" if m else None


def _body(text: str) -> str:
    return text.strip().lstrip(_MARKERS).strip()


def _flag_summary(flag_type: str, present: bool, label: str) -> str:
    if flag_type == "favorite":
        return f"Nodo {label} {'añadido a favoritos' if present else 'quitado de favoritos'} correctamente"
    return f"Nodo {label} {'ignorado' if present else 'quitado de ignorados'} correctamente"


def interpret(
    command: str,
    args: tuple[str, ...] | list[str],
    text: str,
    *,
    subject_label: str | None = None,
    complete: bool = True,
) -> Interpretation | None:
    """`complete=False`: el texto es UNA página suelta de una respuesta que
    puede ser paginada — los resúmenes de listas (FAVS/IGNORED/ZH LIST) se
    omiten para no contar mal; los de confirmación corta no se ven afectados."""
    args = tuple(args)
    body = _body(text)

    parsed = parse_response(command, text, args)
    if parsed.kind == "unsupported":
        return Interpretation(
            command, ERROR, f"El nodo no reconoce el comando {parsed.data.get('command', command)}"
        )

    if command in FORCED_COMMANDS:
        if _ERROR_RE.search(body):
            return Interpretation(command, ERROR, f"El nodo rechazó {command}: {body[:120]}")
        if re.search(r"updated node|forced node", body, re.I):
            return Interpretation(
                command, INFO,
                f"El nodo respondió a {command}, pero esta variante no garantiza el cambio: "
                "comprueba con una lectura (FAVS/IGNORED)",
            )
        return None

    if command in FLAG_COMMANDS:
        flag_type, present = FLAG_COMMANDS[command]
        subject = canonical_node_id(args[0] if args else None)
        short_name: str | None = None
        ok = False
        if parsed.kind == "structured":  # FAV/UNFAV: "Updated node <id> (<sn>)"
            subject = canonical_node_id(parsed.data.get("node_id")) or subject
            short_name = parsed.data.get("short_name") or None
            ok = True
        elif body.upper().startswith(("JT:", "JT ", "NEXUS")):
            if _ERROR_RE.search(body):
                return Interpretation(command, ERROR, f"El nodo rechazó {command}: {body[:120]}")
            ok = bool(re.search(r"updated node|ignor|favor|\bfav", body, re.I))
        if not ok:
            return None
        label = subject_label or (f"{short_name} ({subject})" if short_name and subject else subject) or "indicado"
        return Interpretation(
            command, OK, _flag_summary(flag_type, present, label),
            flag_type=flag_type, flag_present=present,
            subject_node_id=subject, subject_short_name=short_name,
        )

    if parsed.kind != "structured":
        return None
    data = parsed.data
    if parsed.command in ("NIGN ADD", "NIGN REM"):
        action = data.get("action")
        present = action in ("ADDED", "ALREADY")  # ALREADY: ya estaba en la lista
        subject = canonical_node_id(data.get("node_id")) or canonical_node_id(args[1] if len(args) > 1 else None)
        label = subject_label or subject or "indicado"
        if action == "ALREADY":
            summary = f"Nodo {label} ya estaba en ignorados persistentes (NIGN)"
        elif action == "NOT_IN_LIST":
            summary = f"Nodo {label} no estaba en ignorados persistentes (NIGN)"
        else:
            summary = (
                f"Nodo {label} {'añadido a' if present else 'quitado de'} "
                "ignorados persistentes (NIGN) correctamente"
            )
        return Interpretation(
            command, OK, summary,
            flag_type=NIGN_FLAG, flag_present=present, subject_node_id=subject,
        )
    if parsed.command in ("ZH ADD", "ZH DEL"):
        added = str(data.get("action", "")).upper() == "ADDED"
        return Interpretation(
            command, OK, f"Zero Hop 0x{data.get('zh_id', '??')} {'añadido' if added else 'quitado'} correctamente",
            data=data,
        )
    paged = re.match(r"^\s*P\d+(/\d+)?:", text) is not None
    if paged and not complete:
        return None  # página suelta de una respuesta paginada: nada que resumir aún
    entries = data.get("entries")
    if isinstance(entries, list):
        n = len(entries)
        names = {"FAVS": "favoritos", "IGNORED": "ignorados", "ZH LIST": "entradas Zero Hop", "NIGN LIST": "ignorados persistentes"}
        what = names.get(parsed.command)
        if what:
            return Interpretation(command, INFO, f"{n} {what}" if n else f"Ningún elemento en {what}", data=data)
    return _generic(command, data)


def _generic(command: str, data: dict[str, Any]) -> Interpretation | None:
    """Respuesta con parser pero sin frase propia: «COMANDO — clave: valor ·
    …» con los primeros campos escalares (sin marcador), en vez de dejarla
    sin interpretar."""
    parts = [
        f"{k}: {v}"
        for k, v in data.items()
        if k != "marker" and isinstance(v, (str, int, float, bool)) and v != ""
    ][:6]
    if not parts:
        return None
    return Interpretation(command, INFO, f"{command} — " + " · ".join(parts), data=data)
