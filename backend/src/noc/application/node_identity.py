"""Identidad de nodos y seguridad de claves (ADR 0034). Funciones PURAS.

Desde Meshtastic 2.8 el número de nodo es `crc32(clave pública)`: un nodo que
se actualiza (o regenera su clave) aparece como un nodo NUEVO con el mismo
nombre y el viejo se queda mudo. Verificado con datos reales de esta malla
(55 nodos con `node_num == crc32(base64decode(public_key))`).

Principios:
- El emparejamiento solo lo avala la CLAVE (nunca el nombre): veto duro si las
  claves difieren. La puerta de "el viejo se calló" de otros proyectos NO se
  usa: aquí `last_seen_at` del viejo se refresca con los snapshots de NodeDB y
  parecería vivo. El silencio del viejo se informa como dato, no se exige.
- Cada dato lleva su procedencia en `basis` (derived_num / same_key).
- Claves duplicadas = misma clave en ≥2 nodos NO explicados por un cambio de
  identidad; claves débiles = patrones estructurales + lista versionada.
"""

import base64
import binascii
import json
import zlib
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from noc.application.dashboard import ensure_utc
from noc.domain.nodes.entities import Node

KEY_LENGTH = 32
_WEAK_KEYS_FILE = Path(__file__).with_name("weak_keys.json")


def key_bytes(public_key: str | None) -> bytes | None:
    """Bytes de la clave si es base64 válido de 32 bytes; None si no hay
    clave o está truncada/corrupta (nunca se adivina)."""
    if not public_key:
        return None
    try:
        raw = base64.b64decode(public_key, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == KEY_LENGTH else None


def node_num_from_key(raw: bytes) -> int:
    """Número de nodo 2.8: CRC-32 (zlib, sin signo) de los 32 bytes de la clave."""
    return zlib.crc32(raw) & 0xFFFFFFFF


def node_num_of(node: Node) -> int | None:
    if node.node_num is not None:
        return node.node_num
    try:
        return int(node.node_id.lstrip("!"), 16)
    except ValueError:
        return None


@dataclass(slots=True, frozen=True)
class IdentityChange:
    """`predecessor_id` (número antiguo) → `successor_id` (número derivado de la clave)."""

    predecessor_id: str
    successor_id: str
    basis: str  # "derived_num" (CRC de la clave del viejo == número del nuevo) | "same_key"
    predecessor_last_seen_at: datetime | None
    successor_first_seen_at: datetime | None
    predecessor_quiet: bool | None  # ¿el viejo calló cuando apareció el nuevo? None = sin datos


def pair_identity_changes(nodes: list[Node]) -> list[IdentityChange]:
    """Empareja cada nodo "viejo" con su sucesor 2.8.

    Sucesor = nodo cuyo número es el CRC de una clave que otro nodo (más
    antiguo, con número distinto) lleva. Si el sucesor declara clave y es
    distinta, veto (no se empareja). Un viejo solo puede tener un sucesor
    (el CRC de su clave es único).
    """
    by_num: dict[int, Node] = {}
    for n in nodes:
        num = node_num_of(n)
        if num is not None:
            by_num[num] = n

    out: list[IdentityChange] = []
    for old in nodes:
        raw = key_bytes(old.public_key)
        if raw is None:
            continue
        derived = node_num_from_key(raw)
        if derived == node_num_of(old):
            continue  # ya es una identidad 2.8, no un predecesor
        new = by_num.get(derived)
        if new is None or new.node_id == old.node_id:
            continue
        new_raw = key_bytes(new.public_key)
        if new.public_key and new_raw != raw:
            continue  # veto duro: clave distinta
        basis = "same_key" if new_raw == raw else "derived_num"
        quiet: bool | None = None
        if old.last_seen_at is not None and new.first_seen_at is not None:
            quiet = ensure_utc(old.last_seen_at) <= ensure_utc(new.first_seen_at)
        out.append(
            IdentityChange(
                predecessor_id=old.node_id,
                successor_id=new.node_id,
                basis=basis,
                predecessor_last_seen_at=old.last_seen_at,
                successor_first_seen_at=new.first_seen_at,
                predecessor_quiet=quiet,
            )
        )
    return sorted(out, key=lambda c: c.successor_id)


def superseded_node_ids(changes: list[IdentityChange]) -> set[str]:
    """Nodos viejos ya reemplazados: no deben generar alertas de inactividad."""
    return {c.predecessor_id for c in changes}


# ── Seguridad de claves ──────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class DuplicateKeyGroup:
    key_fingerprint: str  # primeros 8 hex del CRC-32 de la clave: no se expone la clave entera
    node_ids: list[str]


@dataclass(slots=True, frozen=True)
class WeakKey:
    node_id: str
    reason: str


def key_fingerprint(raw: bytes) -> str:
    return f"{node_num_from_key(raw):08x}"


def find_duplicate_keys(nodes: list[Node], changes: list[IdentityChange]) -> list[DuplicateKeyGroup]:
    """Misma clave en ≥2 nodos que NO son un cambio de identidad (viejo→nuevo
    explicado por el CRC). Con 2.8 esos pares son legítimos; lo que queda es
    clonado o generación defectuosa de claves."""
    explained = superseded_node_ids(changes)
    groups: dict[bytes, list[str]] = {}
    for n in nodes:
        raw = key_bytes(n.public_key)
        if raw is None or n.node_id in explained:
            continue
        groups.setdefault(raw, []).append(n.node_id)
    return [
        DuplicateKeyGroup(key_fingerprint(raw), sorted(ids))
        for raw, ids in sorted(groups.items(), key=lambda kv: kv[1])
        if len(ids) >= 2
    ]


@lru_cache(maxsize=1)
def _known_weak_keys() -> dict[bytes, str]:
    """Lista versionada (weak_keys.json): claves base64 conocidas como débiles
    → motivo. Ampliable sin tocar código; si el fichero falta, lista vacía."""
    try:
        data = json.loads(_WEAK_KEYS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[bytes, str] = {}
    for entry in data.get("keys", []):
        raw = key_bytes(entry.get("key"))
        if raw is not None:
            out[raw] = str(entry.get("reason", "clave débil conocida"))
    return out


def weak_key_reason(raw: bytes) -> str | None:
    """Motivo por el que la clave parece de baja entropía, o None.

    Heurística estructural (no criptográfica): una clave Curve25519 aleatoria
    de 32 bytes tiene ≈ 28-32 bytes distintos; menos de 16 es inverosímil.
    """
    known = _known_weak_keys().get(raw)
    if known:
        return known
    distinct = len(set(raw))
    if distinct == 1:
        return f"todos los bytes iguales (0x{raw[0]:02x})"
    if distinct < 16:
        return f"solo {distinct} bytes distintos de 32 (entropía muy baja)"
    if all((raw[i + 1] - raw[i]) % 256 == 1 for i in range(len(raw) - 1)):
        return "bytes consecutivos (secuencia)"
    for period in (2, 4, 8):
        if raw == raw[:period] * (KEY_LENGTH // period):
            return f"patrón repetido de {period} bytes"
    return None


def find_weak_keys(nodes: list[Node]) -> list[WeakKey]:
    out: list[WeakKey] = []
    for n in nodes:
        raw = key_bytes(n.public_key)
        if raw is None:
            continue
        reason = weak_key_reason(raw)
        if reason:
            out.append(WeakKey(n.node_id, reason))
    return sorted(out, key=lambda w: w.node_id)
