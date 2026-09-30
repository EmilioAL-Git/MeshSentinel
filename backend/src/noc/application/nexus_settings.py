"""Ajustes configurables del módulo JenTastic-Nexus (ADR 0027 §13) — pedido
explícito del usuario: "en los ajustes, al pinchar en activar Nexus, quiero
ajustes debajo". Reutiliza `system_settings` (tabla clave/valor genérica,
migración 0020, sin migración propia), mismo patrón que `nexus_mode_enabled`
— cada clave se guarda con el prefijo `nexus.` para no chocar con las
claves de `settings_registry.py` (umbrales numéricos atados a
`noc.config.Settings`, un registro totalmente distinto: aquí los valores
son heterogéneos — texto, listas, booleanos — y no pertenecen a esa clase).

Puro por diseño (sin SQL aquí): valida y da los valores por defecto: quien
lee/escribe en BD es cada consumidor (`nexus.py` router, `nexus_gateway.py`,
`nexus_operations.py`) vía `SqlSystemSettingsRepository`, igual que ya hacía
`nexus_mode_enabled` — no se introduce un servicio nuevo solo para esto.
"""

from dataclasses import dataclass
from typing import Any, Callable

SETTING_PREFIX = "nexus."


class NexusSettingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NexusSettingSpec:
    key: str  # sin el prefijo "nexus."
    default: Any
    validate: Callable[[Any], Any]  # normaliza; lanza NexusSettingError si no vale


def _str(v: Any) -> str:
    if not isinstance(v, str) or not v.strip():
        raise NexusSettingError("debe ser texto no vacío")
    return v


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    return _str(v)


def _positive_float(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError) as exc:
        raise NexusSettingError("debe ser un número") from exc
    if f <= 0:
        raise NexusSettingError("debe ser mayor que 0")
    return f


def _bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise NexusSettingError("debe ser verdadero/falso")
    return v


def _addressing_mode(v: Any) -> str:
    if v not in ("shortname", "device_id"):
        raise NexusSettingError("debe ser 'shortname' o 'device_id'")
    return v


# broadcast/local/node/device/mac/group — mismo catálogo de destinos del
# módulo (ADR 0027 §1.2/§13); "device" ya no está deshabilitado, ver builder.py.
_TARGET_KINDS = ("broadcast", "local", "node", "device", "mac", "group")


def _target_kind(v: Any) -> str:
    if v not in _TARGET_KINDS:
        raise NexusSettingError(f"tipo de destino desconocido: {v!r}")
    return v


def _str_list(v: Any) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise NexusSettingError("debe ser una lista de texto")
    return list(v)


def _pinned_nodes(v: Any) -> list[dict[str, str]]:
    if not isinstance(v, list):
        raise NexusSettingError("debe ser una lista")
    out = []
    for item in v:
        if not isinstance(item, dict) or not item.get("short_name"):
            raise NexusSettingError("cada nodo fijado necesita short_name")
        short_name = str(item["short_name"])
        out.append({"short_name": short_name, "label": str(item.get("label") or short_name)})
    return out


def _templates(v: Any) -> list[dict[str, str]]:
    if not isinstance(v, list):
        raise NexusSettingError("debe ser una lista")
    out = []
    for item in v:
        if not isinstance(item, dict) or not item.get("command"):
            raise NexusSettingError("cada plantilla necesita command")
        command = str(item["command"])
        out.append(
            {
                "label": str(item.get("label") or command),
                "command": command,
                "args": str(item.get("args") or ""),
            }
        )
    return out


NEXUS_SETTINGS: tuple[NexusSettingSpec, ...] = (
    NexusSettingSpec("addressing_mode", "shortname", _addressing_mode),
    NexusSettingSpec("command_prefix", "/nexus", _str),
    # None = autodetección por nombre en el nodo local ("Nexus"/"JenT",
    # insensible a mayúsculas, ver meshtastic_stream.py); con valor, el
    # gateway busca EXACTAMENTE ese nombre de canal (mismo criterio: nunca
    # por índice fijo) y rechaza el envío si no existe, en vez de intentar
    # con los nombres por defecto.
    NexusSettingSpec("channel_name", None, _str_or_none),
    NexusSettingSpec("response_window_seconds", 30.0, _positive_float),
    NexusSettingSpec("scan_cooldown_seconds", 120.0, _positive_float),
    # Detección PASIVA (sin enviar nada): observa message.received en vivo y
    # sugiere cualquier nodo cuyo texto tenga forma de respuesta Nexus,
    # aparte del escaneo activo (POST /nexus/scan). Apagable por si en una
    # malla ruidosa se prefiere solo el escaneo explícito.
    NexusSettingSpec("passive_detection_enabled", True, _bool),
    NexusSettingSpec("default_target_kind", "broadcast", _target_kind),
    NexusSettingSpec("default_gateway_id", None, _str_or_none),
    NexusSettingSpec("catalog_collapsed_default", False, _bool),
    NexusSettingSpec("notify_on_broadcast_complete", True, _bool),
    NexusSettingSpec("hidden_commands", [], _str_list),
    NexusSettingSpec("pinned_nodes", [], _pinned_nodes),
    NexusSettingSpec("templates", [], _templates),
)

NEXUS_SETTINGS_BY_KEY = {s.key: s for s in NEXUS_SETTINGS}


def default_settings() -> dict[str, Any]:
    return {s.key: s.default for s in NEXUS_SETTINGS}


def merge_settings(overrides: dict[str, Any]) -> dict[str, Any]:
    """`overrides` = lo que devuelve `SqlSystemSettingsRepository.list_all()`
    (TODAS las claves de `system_settings`, no solo las de Nexus) — filtra
    por el prefijo `nexus.` y aplica sobre los valores por defecto."""
    result = default_settings()
    for spec in NEXUS_SETTINGS:
        full_key = SETTING_PREFIX + spec.key
        if full_key in overrides:
            result[spec.key] = overrides[full_key]
    return result


def validate_changes(changes: dict[str, Any]) -> dict[str, Any]:
    """Valida un parche parcial; devuelve {clave_completa: valor_validado}
    listo para `SqlSystemSettingsRepository.upsert`. Lanza NexusSettingError
    ante la primera clave desconocida o valor inválido (falla entero, nunca
    a medias)."""
    validated: dict[str, Any] = {}
    for key, value in changes.items():
        spec = NEXUS_SETTINGS_BY_KEY.get(key)
        if spec is None:
            raise NexusSettingError(f"ajuste desconocido: {key!r}")
        validated[SETTING_PREFIX + key] = spec.validate(value)
    return validated
