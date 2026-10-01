"""Parsers de respuestas estructuradas → JSON.

Los siete parsers de la primera tanda (VERSION, INFO, STATS, CONFIG, LORA,
DROPS, NODES) están construidos sobre una captura REAL (2026-09-28, nodo X1
→ T1000-E, firmware 2.7.268.dd79d33) en `tools/captures/20260928-083710/`.
Los cuatro de la segunda tanda (SECURITY, SETTINGS, FSIG, LORA-STATUS) sobre
otra captura real posterior (2026-09-28, mismos nodos ya en firmware
2.8.005) en `tools/captures/20260928-123539/` (copiadas ambas en
`backend/tests/fixtures/nexus/`). Ninguno inventa: cada uno solo etiqueta lo
que el propio texto del firmware ya etiqueta (p. ej. `TX:15` → `tx: 15`);
donde el dato no tiene etiqueta y su significado no está confirmado (los dos
valores numéricos y las letras de `NODES`, o los pares compuestos
`<número>:<número>` de `FIREWALLSTATS`, ver más abajo) se deja SIN
estructurar.

Confirmado por la captura: las respuestas SÍ empiezan por `JT <COMANDO>:` o,
para avisos del sistema (comando no soportado, aviso de paginación en
curso), por `JT: <texto>`. `JT: Unknown command '<X>'` se detecta de forma
genérica ANTES de intentar cualquier parser (kind="unsupported"): confirma
que ese nodo/firmware no entiende el comando, en vez de mostrar un error de
parseo. `SECURITY` no existía en firmware 2.7.268 (anterior a su
introducción en 2.8.005); con 2.8.005 sí responde y su parser está
confirmado.

`FIREWALLSTATS` tiene parser COMPLETO (2026-09-29, segunda pasada tras la
inicial parcial): las primeras 6 líneas (`Processed`/`Bypass`/`Drop`/
`Accept`/`PKI`/`Relay`+`IDR`) se estructuran igual que `STATS` en el nivel
superior de `data`, sin repetir ninguna etiqueta. El resto del cuerpo
(`HOP`, `Port:` ×3, `RL Seen`/`RL Pass`/`RL Drop` ×2 cada uno, `Trace` ×2)
SÍ reutiliza el mismo rótulo para grupos de sub-campos distintos cada
vez — la solución NO es inventar un nombre desambiguador nuevo por
ocurrencia (eso sí sería inventar), sino no fusionar nada entre líneas:
`data["extra_sections"]` es una LISTA ordenada, una entrada por línea
(`label`/`fields`/`raw`), así que dos líneas `Port:` conviven como dos
entradas distintas sin pisarse nunca. Dentro de cada línea, un patrón
`Etiqueta: <número>` donde ese número sigue teniendo OTROS dos puntos
justo después (p. ej. el `6:0` de `HOP: 6:0 7:0`) se descarta a propósito
de los campos estructurados — no se puede saber si es un valor suelto o
el principio de un par compuesto sin adivinar — queda solo en `raw`, nunca
mal etiquetado. `data["extra_raw"]` se conserva íntegro además, por si
hace falta el texto tal cual. Verificado línea por línea a mano contra la
captura real completa antes de escribirse: no hizo falta una segunda
captura con valores distintos de cero, la ambigüedad era de ETIQUETAS
repetidas, no de valores — separar por línea la resuelve sin datos nuevos.

`FSIG` es un caso especial: el nodo manda primero un aviso suelto ("🟢 JT:
Paging signatures...", sin cabecera `JT FSIG:` — cae a texto crudo, no
rompe nada) y LUEGO una respuesta paginada (`P1: JT Signatures:\n...`) cuya
cabecera real, una vez reensamblada (reassembly.py quita el prefijo `P1: `),
es `JT Signatures:` — no `JT FSIG:`. El parser usa esa cabecera real, no la
del catálogo.

`WATCH STATS` necesita el node_id vigilado como ARGUMENTO
(`WATCH STATS <hex8>`) — sin él responde el mensaje de uso genérico, que
es lo único que se había probado antes (usuario probándolo en directo:
"Hice /nexus watch stats !af000001 y funciona, tras haber hecho watch add
!id"). Con el argumento responde una tabla real paginada con RF/Hops/
Relay/Timing/Ports; "Min:"/"Max:" aparecen dos veces en el texto (RF en
dB, Timing en segundos) — se distinguen por el sufijo de unidad en el
propio patrón, no por invención, cada sección en su grupo anidado.
`WATCH LIST`/`ADD`/`DEL` también confirmados por captura real; la
respuesta de `WATCH LIST` con entradas no lleva el prefijo `JT:` que sí
llevan las demás (confirmado real, no error de transcripción).

Para añadir un parser nuevo: función pura `str -> dict`, registrarla en
PARSERS con el nombre CANÓNICO del catálogo (y subverbo si aplica: "WATCH
STATS"), y un test con la captura real tal cual llegó.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Parser = Callable[[str], dict[str, Any]]

# Formatos de §C4 (prompt v2.8.006) que siguen sin parser estructurado.
# STATS, CONFIG, NODES, SECURITY, SETTINGS, FSIG, LORA-STATUS y FIREWALLSTATS
# (parcial, ver docstring del módulo) salen de esta lista: ya implementados
# con datos reales. WATCH STATS tiene captura real pero solo devolvió el
# mensaje de uso genérico — nada que estructurar todavía.
PENDING_FORMATS: tuple[str, ...] = (
    "SIGSTATS",
    "HOPSTATS",
    "PACKETSTATS",
    "CHANNELSTATS",
    "RELAYS",
)

PARSERS: dict[str, Parser] = {}

_UNKNOWN_COMMAND_RE = re.compile(r"^JT:\s*Unknown command '(?P<command>[^']*)'\s*$")

# Toda respuesta Nexus observada hasta ahora empieza por "JT " o "JT:"
# (alias viejo "Nexus ", ver `_first_line`), opcionalmente precedida del
# marcador 🟢/🔴 (confirmado por el usuario: validez de la firma
# criptográfica nueva de Meshtastic 2.8 — solo aparece en firmware ≥2.8,
# ausente en respuestas de firmware anterior; el parser nunca depende de la
# versión, solo de si el token está presente o no) — usado por la detección
# PASIVA (`nexus_gateway.py`): no requiere haber mandado ningún comando,
# solo que el TEXTO ya tenga la forma de una respuesta Nexus.
_SIGNATURE_RE = re.compile(r"^(?:[🟢🔴]\s*)?(?:JT|Nexus)[\s:]")


def looks_like_nexus_signature(text: str) -> bool:
    return bool(_SIGNATURE_RE.match(text.strip()))


@dataclass(frozen=True, slots=True)
class ParsedResponse:
    command: str
    kind: str  # "structured" | "raw" | "unsupported"
    text: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None  # el parser falló: se muestra el texto crudo


def parser_key(command: str, args: tuple[str, ...] = ()) -> str:
    if args and f"{command} {args[0].upper()}" in PARSERS:
        return f"{command} {args[0].upper()}"
    return command


def parse_response(command: str, text: str, args: tuple[str, ...] = ()) -> ParsedResponse:
    key = parser_key(command, args)
    unknown = _UNKNOWN_COMMAND_RE.match(text.strip())
    if unknown:
        return ParsedResponse(key, "unsupported", text, {"command": unknown.group("command")})
    parser = PARSERS.get(key)
    if parser is None:
        return ParsedResponse(key, "raw", text)
    try:
        return ParsedResponse(key, "structured", text, parser(text))
    except Exception as exc:  # noqa: BLE001 — un formato inesperado nunca rompe la UI
        return ParsedResponse(key, "raw", text, error=f"{type(exc).__name__}: {exc}")


# --- Helpers compartidos -------------------------------------------------


def _first_line(text: str, header: str) -> tuple[str | None, str]:
    """Valida la cabecera `JT <HEADER>`, devuelve (marcador, resto).

    Algunas respuestas llevan un marcador delante de `JT` (🟢/🔴 — confirmado
    por el usuario: validez de la firma criptográfica nueva de Meshtastic
    2.8, solo presente en firmware ≥2.8; visto en VERSION e INFO tanto en
    difusión como dirigidos). Se separa sin asumir qué valores concretos
    existen, para no perder la cabecera al validarla.

    Firmware viejo (2.7.265, confirmado por captura real del usuario) usa
    "Nexus <HEADER>" en vez de "JT <HEADER>" — mismo contenido, cabecera
    distinta; se acepta como alias en TODOS los comandos que pasan por aquí,
    no solo INFO (única evidencia directa, pero se asume nomenclatura vieja
    del firmware, no un caso especial de un comando).
    """
    headers = (header,)
    if header.startswith("JT "):
        headers = (header, "Nexus " + header[len("JT "):])
    lines = text.splitlines()
    if not lines:
        raise ValueError(f"no empieza por {header!r}")
    first = lines[0].strip()
    marker: str | None = None
    if not first.startswith(headers):
        token, _, rest = first.partition(" ")
        if rest.startswith(headers):
            marker, first = token, rest
    if not first.startswith(headers):
        raise ValueError(f"no empieza por {header!r}")
    return marker, "\n".join(lines[1:])


def _maybe_int(value: str) -> int | str:
    try:
        return int(value)
    except ValueError:
        return value


# --- VERSION ---------------------------------------------------------------
# "JT VERSION: 2.7.268.dd79d33" · visto también con un marcador delante en
# difusión propia: "🔴 JT VERSION: 2.8.005.b42309e" (confirmado por el
# usuario: semáforo de validez de la firma criptográfica de Meshtastic 2.8,
# solo en firmware ≥2.8 — se conserva tal cual, sin interpretar el valor).

_VERSION_RE = re.compile(r"^(?:(?P<marker>\S+)\s+)?(?:JT|Nexus) VERSION:\s*(?P<version>\S+)\s*$")


def parse_version(text: str) -> dict[str, Any]:
    match = _VERSION_RE.match(text.strip())
    if not match:
        raise ValueError("formato VERSION no reconocido")
    data: dict[str, Any] = {"version": match.group("version")}
    if match.group("marker"):
        data["marker"] = match.group("marker")
    return data


PARSERS["VERSION"] = parse_version


# --- INFO --------------------------------------------------------------
# "JT INFO:\n!af000018 [N019]\nVer: 2.7.268.dd79d33\nRole: MUTE\nMAC: c7:79:..."

_INFO_HEADER_RE = re.compile(r"^(?P<node_id>![0-9a-fA-F]{8})\s*(?:\[(?P<short_name>.*)\])?$")


def parse_info(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT INFO:")
    rest = body.splitlines()
    data: dict[str, Any] = {}
    if marker:
        data["marker"] = marker
    if rest:
        match = _INFO_HEADER_RE.match(rest[0].strip())
        if match:
            data["node_id"] = match.group("node_id")
            if match.group("short_name") is not None:
                data["short_name"] = match.group("short_name")
            rest = rest[1:]
    for line in rest:
        key, sep, value = line.partition(":")
        if not sep:
            continue
        data[key.strip().lower()] = value.strip()
    return data


PARSERS["INFO"] = parse_info


# --- STATS ---------------------------------------------------------------
# "JT STATS:\nTX:15 RX:117\nBad:30(25%) Dp:11(9%)\nRelay:0 Can:0\n
#  Drop:0 Noise:-109" — tokens "Clave:número" opcionalmente seguidos de
# "(N%)"; cada clave la pone el propio firmware, no se renombra.

_STATS_TOKEN_RE = re.compile(r"([A-Za-z][A-Za-z]*):(-?\d+)(?:\((\d+)%\))?")


def parse_stats(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT STATS:")
    data: dict[str, Any] = {}
    if marker:
        data["marker"] = marker
    for key, value, percent in _STATS_TOKEN_RE.findall(body):
        entry: dict[str, Any] = {"value": int(value)}
        if percent:
            entry["percent"] = int(percent)
        data[key.lower()] = entry
    return data


PARSERS["STATS"] = parse_stats


# --- CONFIG ----------------------------------------------------------------
# "JT CONFIG:\nRole: MUTE\nNI:10900s\nTEL: D:43200s E:3600s P:3600s\n
#  POS:14400s(264) Smart:1\nGPS:0 Fixed:0 HM:0 RM:0\nLoc: 0.00000,0.00000"
# Claves NI/TEL_D/TEL_E/TEL_P/POS/SMART/FIXED/GPS/LOC son las mismas que
# documenta SETCONFIG (§3.10/§F1); HM y RM no están documentadas en ninguna
# fuente — se devuelven igualmente (dato real presente en la captura) pero
# sin desarrollar su nombre, para no inventar qué significan.

_CONFIG_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("role", re.compile(r"Role:\s*(\S+)")),
    ("ni_seconds", re.compile(r"NI:(\d+)s")),
    ("tel_d_seconds", re.compile(r"TEL:\s*D:(\d+)s")),
    ("tel_e_seconds", re.compile(r"\bE:(\d+)s")),
    ("tel_p_seconds", re.compile(r"\bP:(\d+)s")),
    ("pos_seconds", re.compile(r"POS:(\d+)s")),
    ("pos_smart_meters", re.compile(r"POS:\d+s\((\d+)\)")),
    ("smart", re.compile(r"Smart:(\d+)")),
    ("gps", re.compile(r"GPS:(\d+)")),
    ("fixed", re.compile(r"Fixed:(\d+)")),
    ("hm", re.compile(r"\bHM:(\d+)")),  # abreviatura sin confirmar
    ("rm", re.compile(r"\bRM:(\d+)")),  # abreviatura sin confirmar
    ("loc", re.compile(r"Loc:\s*(-?\d+\.\d+,-?\d+\.\d+)")),
)


def parse_config(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT CONFIG:")
    data: dict[str, Any] = {}
    if marker:
        data["marker"] = marker
    for key, pattern in _CONFIG_PATTERNS:
        match = pattern.search(body)
        if match:
            data[key] = _maybe_int(match.group(1))
    return data


PARSERS["CONFIG"] = parse_config


# --- LORA ------------------------------------------------------------------
# "JT LORA:\nSF:7 BW:62 CR:5\nPreset:0 (OFF)\nFreq:869.6180MHz\n
#  Power:23dBm\nIgnoreMQTT:0\nRebroadcast:CORE_ONLY"
# Registrado con la clave "LORA" (el comando probado); "LORA-STATUS"/LRS
# sigue en PENDING_FORMATS: no se ha probado ese comando por separado y no
# se puede asumir que da el mismo formato sin verlo.

_LORA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sf", re.compile(r"SF:(\d+)")),
    ("bw", re.compile(r"BW:(\d+)")),
    ("cr", re.compile(r"CR:(\d+)")),
    ("freq_mhz", re.compile(r"Freq:([\d.]+)MHz")),
    ("power_dbm", re.compile(r"Power:(\d+)dBm")),
    ("ignore_mqtt", re.compile(r"IgnoreMQTT:(\d+)")),
    ("rebroadcast", re.compile(r"Rebroadcast:(\S+)")),
)
_LORA_PRESET_RE = re.compile(r"Preset:(\d+)\s*\(([^)]*)\)")


def parse_lora(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT LORA:")
    data: dict[str, Any] = {}
    if marker:
        data["marker"] = marker
    for key, pattern in _LORA_PATTERNS:
        match = pattern.search(body)
        if match:
            data[key] = _maybe_int(match.group(1))
    preset = _LORA_PRESET_RE.search(body)
    if preset:
        data["preset"] = int(preset.group(1))
        data["preset_label"] = preset.group(2)
    return data


PARSERS["LORA"] = parse_lora


# --- DROPS -------------------------------------------------------------
# "JT ACTIVE DROPS:\nP_OFF T_OFF "

def parse_drops(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT ACTIVE DROPS:")
    data: dict[str, Any] = {"active": body.split()}
    if marker:
        data["marker"] = marker
    return data


PARSERS["DROPS"] = parse_drops


# --- NODES -----------------------------------------------------------------
# "JT NodeDB:\n!af000018:N019:-1:0:KV !af000001:N001:0:14:K+ ..." — reconstruido
# de hasta 11 páginas de 200 car. cada una (el reensamblado de reassembly.py
# concatena sin separador: una entrada puede empezar en una página y acabar
# en la siguiente, p. ej. "!e5f720" + "35:N007:1:14:KV" → "!af000009:...").
# Los dos valores numéricos y las letras finales (K+/KV) no tienen
# significado confirmado en ninguna fuente: se devuelven como datos
# posicionales sin nombre inventado, no se interpretan.

_NODE_ENTRY_RE = re.compile(
    r"(?P<node_id>![0-9a-fA-F]{8}):(?P<short_name>[^:\s]*):"
    r"(?P<val1>-?\d+):(?P<val2>-?\d+):(?P<flags>[A-Za-z0-9+]+)"
)


def parse_nodes(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT NodeDB:")
    entries = [
        {
            "node_id": m.group("node_id"),
            "short_name": m.group("short_name"),
            "values": [int(m.group("val1")), int(m.group("val2"))],
            "flags": m.group("flags"),
        }
        for m in _NODE_ENTRY_RE.finditer(body)
    ]
    if not entries:
        raise ValueError("ninguna entrada de NodeDB reconocida")
    data: dict[str, Any] = {"nodes": entries}
    if marker:
        data["marker"] = marker
    return data


PARSERS["NODES"] = parse_nodes


# --- SECURITY ----------------------------------------------------------
# "JT SECURITY:\n REQ_SIG:off\n ALLOW_DM:off\n SILENT:off\n FAV_NX:off\n
#  FAV_TR:off\n BYPASS_RP:off (28/256)" — solo 3 bits documentados por el
# manual (REQ_SIG/ALLOW_DM/SILENT_LOG); FAV_NX/FAV_TR/BYPASS_RP aparecen
# igualmente en la captura real y se devuelven tal cual, sin inventar su
# significado. BYPASS_RP lleva un contador entre paréntesis aparte.

_SECURITY_LINE_RE = re.compile(r"^(?P<key>[A-Z_]+):(?P<value>\S+)(?:\s*\((?P<extra>[^)]*)\))?$")


def parse_security(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT SECURITY:")
    data: dict[str, Any] = {}
    if marker:
        data["marker"] = marker
    for line in body.splitlines():
        match = _SECURITY_LINE_RE.match(line.strip())
        if not match:
            continue
        key = match.group("key").lower()
        data[key] = match.group("value").lower()
        if match.group("extra"):
            data[f"{key}_extra"] = match.group("extra")
    return data


PARSERS["SECURITY"] = parse_security


# --- SETTINGS ------------------------------------------------------------
# "JT SETTINGS:\nRole:MUTE Msk:OFF\nHops:OFF CA:0 BT:0\nBurner:OFF\n
#  Drops:0x0000000000000000 DMF:0\nPPing:0x002 RS:0 SK:0/4\nBD:5s" —
# tokens "Clave:valor" (valores hex/duración/fracción, sin normalizar:
# se devuelven como texto tal cual los da el firmware, igual que STATS).

_SETTINGS_TOKEN_RE = re.compile(r"([A-Za-z]+):(\S+)")


def parse_settings(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT SETTINGS:")
    data: dict[str, Any] = {}
    if marker:
        data["marker"] = marker
    for key, value in _SETTINGS_TOKEN_RE.findall(body):
        data[key.lower()] = value
    return data


PARSERS["SETTINGS"] = parse_settings


# --- FSIG ------------------------------------------------------------------
# Respuesta paginada; una vez reensamblada (P1: quitado por reassembly.py)
# la cabecera real es "JT Signatures:" (no "JT FSIG:" — ver docstring del
# módulo): "JT Signatures:\nS1: OFF\nS2: OFF\n...\nS8: OFF\n" en reposo.
# Sintaxis de `SET`/`OFF` confirmada por captura real (2026-09-28,
# `FSIG SET 1 TEST` → `FSIG` → `FSIG OFF 1`, ver docs/design/nexus-
# control.md §0.7): un slot activo aparece como
# "S1: TEST (text) (4B)" — patrón tal cual, codificación detectada
# (`text` confirmado; `hex`/`base64` documentados por el catálogo, sin
# captura propia todavía pero mismo patrón) entre paréntesis, y el tamaño
# en bytes entre paréntesis. `FSIG SET <1-8> <patrón>` confirma con
# "JT: S<n> set (<encoding>, <N>B)."; `FSIG OFF <1-8>` con
# "JT: S<n> cleared." (ninguno de los dos lleva cabecera `JT Signatures:`
# — no tienen parser propio, se muestran como texto).

_FSIG_ACTIVE_RE = re.compile(r"^(?P<pattern>.+?)\s+\((?P<encoding>text|hex|base64)\)\s+\((?P<bytes>\d+)B\)$")


def parse_fsig(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT Signatures:")
    slots: dict[str, Any] = {}
    for line in body.splitlines():
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        value = value.strip()
        if value == "OFF":
            slots[key.strip()] = {"active": False}
            continue
        match = _FSIG_ACTIVE_RE.match(value)
        if match:
            slots[key.strip()] = {
                "active": True,
                "pattern": match.group("pattern"),
                "encoding": match.group("encoding"),
                "bytes": int(match.group("bytes")),
            }
        else:
            slots[key.strip()] = {"active": True, "raw": value}
    data: dict[str, Any] = {"slots": slots}
    if marker:
        data["marker"] = marker
    return data


PARSERS["FSIG"] = parse_fsig


# --- LORA-STATUS -------------------------------------------------------
# "JT LORA Status:\nFreq: 869.618MHz\nBW:62.50kHz SF:7 CR:5\nPre:16 (32ms)\n
#  Slot:12ms CW:3-8\nSW:0x2B\nChipPwr:22dBm\nSpeed:2734 b/s" — cabecera y
# formato distintos de "LORA" (§ arriba): comando/parser separados, no se
# ha confirmado que compartan estructura salvo SF/CR/Freq.

_LORA_STATUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("freq_mhz", re.compile(r"Freq:\s*([\d.]+)MHz")),
    ("bw_khz", re.compile(r"BW:([\d.]+)kHz")),
    ("sf", re.compile(r"SF:(\d+)")),
    ("cr", re.compile(r"CR:(\d+)")),
    ("preamble_symbols", re.compile(r"Pre:(\d+)")),
    ("slot_ms", re.compile(r"Slot:(\d+)ms")),
    ("cw", re.compile(r"CW:(\S+)")),
    ("sync_word", re.compile(r"SW:(0[xX][0-9A-Fa-f]+)")),
    ("chip_power_dbm", re.compile(r"ChipPwr:(\d+)dBm")),
    ("speed_bps", re.compile(r"Speed:(\d+)\s*b/s")),
)
_LORA_STATUS_PREAMBLE_MS_RE = re.compile(r"Pre:\d+\s*\((\d+)ms\)")


def parse_lora_status(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT LORA Status:")
    data: dict[str, Any] = {}
    if marker:
        data["marker"] = marker
    for key, pattern in _LORA_STATUS_PATTERNS:
        match = pattern.search(body)
        if match:
            data[key] = _maybe_int(match.group(1))
    preamble_ms = _LORA_STATUS_PREAMBLE_MS_RE.search(body)
    if preamble_ms:
        data["preamble_ms"] = int(preamble_ms.group(1))
    return data


PARSERS["LORA-STATUS"] = parse_lora_status


# --- FIREWALLSTATS --------------------------------------------------------
# "JT Firewall Stats:\nProcessed: 145\nBypass: 21 (14.5%)  NXS:21 FAV:0\n
#  Drop:   0 (0.0%)\nAccept: 124 (85.5%)\nPKI: 0 (L:0 R:0)  PRIV: 0  WL: 0
#  BL: 0\nRelay: 0  IDR: 0\nHOP: 6:0 7:0  PRE: 0  ACKS: 0\n..." — las 6
# primeras líneas (hasta "Relay/IDR") no repiten ninguna etiqueta: se
# estructuran con el mismo criterio que STATS, en el nivel superior de
# `data`. El resto del cuerpo ("HOP", "Port:" ×3, "RL Seen/Pass/Drop" ×2
# cada uno, "Trace" ×2...) SÍ reutiliza el mismo rótulo para grupos de
# sub-campos distintos cada vez — la clave para no colisionar sin inventar
# nombres NO es adivinar un desambiguador nuevo por ocurrencia (eso sí
# habría sido inventar), sino no fusionar nada entre líneas: cada línea se
# convierte en su PROPIA entrada de `extra_sections` (etiqueta + campos +
# texto crudo), en el mismo orden en que llegó — dos líneas "Port:"
# conviven como dos entradas distintas con su propio rótulo "Port", nunca
# se pisan. La etiqueta de cada línea es el texto anterior a sus dos
# puntos; los campos son únicamente pares "Clave:valor" con la clave
# pegada al valor (`NI:0`, `TX:0`...) — un patrón "Etiqueta: <número>"
# donde el número sigue teniendo MÁS dos puntos justo después (p. ej. el
# "6:0" de "HOP: 6:0 7:0") se descarta a propósito (no se puede saber si
# ese número es un valor suelto o el principio de un par compuesto sin
# adivinar): esos casos quedan solo en el texto crudo de la línea, nunca
# mal etiquetados. Verificado a mano línea por línea contra la captura
# real completa (2026-09-28, ambos nodos) antes de escribirlo — no hizo
# falta una segunda captura con valores distintos de cero: la ambigüedad
# era de ETIQUETAS repetidas, no de valores, y separar por línea la
# resuelve sin necesitar datos nuevos.

_FIREWALLSTATS_SAFE_LINES = 6
_FIREWALLSTATS_KV_RE = re.compile(r"([A-Za-z]+):\s*(-?\d+)(?:\s*\((\d+(?:\.\d+)?)%\))?")
_FIREWALLSTATS_FIELD_RE = re.compile(r"([A-Za-z][A-Za-z0-9-]*):\s*(-?\d+)(?!:)")


def _firewallstats_extra_sections(lines: list[str]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        colon = line.find(":")
        label = line[:colon].strip() if colon != -1 else line
        fields = {key.lower(): int(value) for key, value in _FIREWALLSTATS_FIELD_RE.findall(line)}
        sections.append({"label": label, "fields": fields, "raw": line})
    return sections


def parse_firewallstats(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT Firewall Stats:")
    lines = body.split("\n")
    safe_body = "\n".join(lines[:_FIREWALLSTATS_SAFE_LINES])
    extra_lines = lines[_FIREWALLSTATS_SAFE_LINES:]
    extra_raw = "\n".join(extra_lines).strip("\n")
    data: dict[str, Any] = {}
    if marker:
        data["marker"] = marker
    for key, value, percent in _FIREWALLSTATS_KV_RE.findall(safe_body):
        entry: dict[str, Any] = {"value": int(value)}
        if percent:
            entry["percent"] = float(percent)
        data[key.lower()] = entry
    if extra_raw:
        data["extra_raw"] = extra_raw
        data["extra_sections"] = _firewallstats_extra_sections(extra_lines)
    return data


PARSERS["FIREWALLSTATS"] = parse_firewallstats


# --- WATCH LIST/ADD/DEL (2026-09-28, captura real) --------------------
# Vacío: "JT: Watchlist empty." Con entradas: "Watchlist: af000001[N001]"
# — SIN el prefijo "JT:" que llevan el resto de respuestas de este
# subsistema (inconsistencia real del firmware, confirmada por captura, no
# un error de transcripción). "WATCH STATS" sigue sin parser: devolvió el
# mensaje de uso genérico incluso con una entrada real y tráfico real de
# ese nodo de por medio (ver docs/design/nexus-control.md §0.5) — no hay
# datos reales que estructurar todavía.

def _strip_marker(text: str, header: str) -> tuple[str | None, str]:
    """Como `_first_line` pero para respuestas de una sola línea sin el
    formato `JT <HEADER>:` (p. ej. `JT: Watchlist empty.` o, sin ni
    siquiera `JT:`, `Watchlist: af000001[N001]` — confirmado por captura
    real, inconsistencia propia del firmware)."""
    stripped = text.strip()
    if stripped.startswith(header):
        return None, stripped
    token, _, rest = stripped.partition(" ")
    if rest.startswith(header):
        return token, rest
    raise ValueError(f"no empieza por {header!r}")


_WATCH_LIST_ENTRY_RE = re.compile(r"([0-9a-fA-F]{8})\[([^\]]*)\]")


def parse_watch_list(text: str) -> dict[str, Any]:
    try:
        marker, body = _strip_marker(text, "JT: Watchlist empty.")
    except ValueError:
        marker, body = _strip_marker(text, "Watchlist:")
    data: dict[str, Any] = {
        "entries": [
            {"node_id": f"!{node_id.lower()}", "short_name": short_name}
            for node_id, short_name in _WATCH_LIST_ENTRY_RE.findall(body)
        ]
    }
    if marker:
        data["marker"] = marker
    return data


PARSERS["WATCH LIST"] = parse_watch_list

_WATCH_ADD_RE = re.compile(r"^JT:\s*Added\s+([0-9a-fA-F]{8})\s+to watchlist\.?\s*$")


def parse_watch_add(text: str) -> dict[str, Any]:
    marker, body = _strip_marker(text, "JT:")
    match = _WATCH_ADD_RE.match(body)
    if not match:
        raise ValueError("formato WATCH ADD no reconocido")
    data: dict[str, Any] = {"added": f"!{match.group(1).lower()}"}
    if marker:
        data["marker"] = marker
    return data


PARSERS["WATCH ADD"] = parse_watch_add

_WATCH_DEL_RE = re.compile(r"^JT:\s*Removed\s+([0-9a-fA-F]{8})\.?\s*$")


def parse_watch_del(text: str) -> dict[str, Any]:
    marker, body = _strip_marker(text, "JT:")
    match = _WATCH_DEL_RE.match(body)
    if not match:
        raise ValueError("formato WATCH DEL no reconocido")
    data: dict[str, Any] = {"removed": f"!{match.group(1).lower()}"}
    if marker:
        data["marker"] = marker
    return data


PARSERS["WATCH DEL"] = parse_watch_del


# --- WATCH STATS <hex8> (2026-09-28, captura real) ----------------------
# Confirmado por el usuario probando en directo (`/nexus watch stats
# !af000001`, tras un `WATCH ADD` previo): "STATS" SÍ funciona, pero exige
# el node_id como argumento — sin él responde el mensaje de uso genérico
# (§0.5, sin cambios, ese comportamiento ya estaba documentado). Registrado
# con clave "WATCH STATS" (mismo criterio que el resto: `parser_key()` solo
# compone "WATCH STATS" cuando el primer argumento es literalmente "STATS";
# el node_id que sigue no afecta a la clave). Respuesta paginada real:
# "JT Watch Stats:\nTarget: af000001\nPkts: 10 Bytes: 308\nRF (Direct
# Only):\nAvg:-4dB SNR:14.1 FE:0\nSD: 2.9 SNR:0.2 FE:0\nMin:-7dB SNR:13.8
# FE:0\nMax:0dB SNR:14.5 FE:0\nHops: h0:10 h1:0 h2:0 h3:0 h4:0\nRelay:
# Last:90 Primary:90 (10)\nTiming: Min:4s Max:130s Age:0s\nPorts: NI:0
# POS:0 TEL:0 TXT:10 ADM:0 RT:0 OTH:0\n". "Min:"/"Max:" aparecen DOS veces
# en el texto (RF, en dB, y Timing, en segundos) — se distinguen por el
# sufijo de unidad en el propio regex (dB vs. "s"), no por invención: cada
# sección queda en su propio grupo anidado, sin colisión posible.

_WATCH_STATS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("target", re.compile(r"Target:\s*([0-9a-fA-F]{8})")),
)
_WATCH_STATS_PKTS_RE = re.compile(r"Pkts:\s*(\d+)\s+Bytes:\s*(\d+)")
_WATCH_STATS_RF_RE = re.compile(r"(Avg|Min|Max):(-?\d+)dB\s+SNR:(-?\d+(?:\.\d+)?)\s+FE:(\d+)")
_WATCH_STATS_SD_RE = re.compile(r"SD:\s*(-?\d+(?:\.\d+)?)\s+SNR:(-?\d+(?:\.\d+)?)\s+FE:(\d+)")
_WATCH_STATS_HOPS_RE = re.compile(r"Hops:\s*h0:(\d+)\s+h1:(\d+)\s+h2:(\d+)\s+h3:(\d+)\s+h4:(\d+)")
_WATCH_STATS_RELAY_RE = re.compile(r"Relay:\s*Last:(\d+)\s+Primary:(\d+)\s*\((\d+)\)")
_WATCH_STATS_TIMING_RE = re.compile(r"Timing:\s*Min:(\d+)s\s+Max:(\d+)s\s+Age:(\d+)s")
_WATCH_STATS_PORTS_RE = re.compile(
    r"Ports:\s*NI:(\d+)\s+POS:(\d+)\s+TEL:(\d+)\s+TXT:(\d+)\s+ADM:(\d+)\s+RT:(\d+)\s+OTH:(\d+)"
)


def parse_watch_stats(text: str) -> dict[str, Any]:
    marker, body = _first_line(text, "JT Watch Stats:")
    data: dict[str, Any] = {}
    if marker:
        data["marker"] = marker
    target = _WATCH_STATS_PATTERNS[0][1].search(body)
    if target:
        data["target"] = f"!{target.group(1).lower()}"
    pkts = _WATCH_STATS_PKTS_RE.search(body)
    if pkts:
        data["pkts"] = int(pkts.group(1))
        data["bytes"] = int(pkts.group(2))
    rf: dict[str, Any] = {}
    for label, db, snr, fe in _WATCH_STATS_RF_RE.findall(body):
        rf[label.lower()] = {"db": int(db), "snr": float(snr), "fe": int(fe)}
    sd = _WATCH_STATS_SD_RE.search(body)
    if sd:
        rf["sd"] = {"value": float(sd.group(1)), "snr": float(sd.group(2)), "fe": int(sd.group(3))}
    if rf:
        data["rf"] = rf
    hops = _WATCH_STATS_HOPS_RE.search(body)
    if hops:
        data["hops"] = {f"h{i}": int(v) for i, v in enumerate(hops.groups())}
    relay = _WATCH_STATS_RELAY_RE.search(body)
    if relay:
        data["relay"] = {"last": int(relay.group(1)), "primary": int(relay.group(2)), "primary_extra": int(relay.group(3))}
    timing = _WATCH_STATS_TIMING_RE.search(body)
    if timing:
        data["timing"] = {
            "min_seconds": int(timing.group(1)),
            "max_seconds": int(timing.group(2)),
            "age_seconds": int(timing.group(3)),
        }
    ports = _WATCH_STATS_PORTS_RE.search(body)
    if ports:
        keys = ("ni", "pos", "tel", "txt", "adm", "rt", "oth")
        data["ports"] = {k: int(v) for k, v in zip(keys, ports.groups(), strict=True)}
    return data


PARSERS["WATCH STATS"] = parse_watch_stats


# --- FAVS / IGNORED / FAV / UNFAV (2026-09-28, captura real) --------------
# Confirmado el mismo día que se preguntó si la relación de favoritos/
# ignorados era "solicitable" desde Nexus: SÍ, categoría NodeDB del
# catálogo (`FAVS`/`IGNORED` consulta, `FAV`/`UNFAV`/`IGNORE`/`UNIGNORE`
# mutan). Sin relación con los favoritos/ignorados remotos nativos
# (M4.1/M4.2, AdminMessage — mecanismo totalmente distinto).
#
# "JT Favorites:\n!af000004:N002 !af000005:N003 !af000001:N001 ..." —
# paginada, mismo patrón "!<hex8>:<shortname>" que `NODES` pero sin
# sub-campos; `IGNORED` con la lista vacía respondió "JT Ignored:\n" (cero
# entradas, formato confirmado igualmente). `FAV`/`UNFAV` confirman los
# dos con el mismo texto genérico "JT: Updated node <hex8> (<shortname>)"
# — no distinguen en el propio mensaje si añadió o quitó, hay que fiarse
# del comando mandado (igual que ADR 0019 con los favoritos/ignorados
# remotos nativos: sin GET de verificación posible, solo el eco del ACK).

_FAVS_ENTRY_RE = re.compile(r"!([0-9a-fA-F]{8}):([^\s!]*)")


def _parse_node_list(text: str, header: str) -> dict[str, Any]:
    marker, body = _first_line(text, header)
    entries = [
        {"node_id": f"!{node_id.lower()}", "short_name": short_name}
        for node_id, short_name in _FAVS_ENTRY_RE.findall(body)
    ]
    data: dict[str, Any] = {"entries": entries}
    if marker:
        data["marker"] = marker
    return data


def parse_favs(text: str) -> dict[str, Any]:
    return _parse_node_list(text, "JT Favorites:")


PARSERS["FAVS"] = parse_favs


def parse_ignored(text: str) -> dict[str, Any]:
    return _parse_node_list(text, "JT Ignored:")


PARSERS["IGNORED"] = parse_ignored

_FAV_UPDATED_RE = re.compile(r"^JT:\s*Updated node\s+(![0-9a-fA-F]{8})\s+\(([^)]*)\)\s*$")


def parse_fav_updated(text: str) -> dict[str, Any]:
    marker, body = _strip_marker(text, "JT:")
    match = _FAV_UPDATED_RE.match(body)
    if not match:
        raise ValueError("formato 'Updated node' no reconocido")
    data: dict[str, Any] = {"node_id": match.group(1), "short_name": match.group(2)}
    if marker:
        data["marker"] = marker
    return data


PARSERS["FAV"] = parse_fav_updated
PARSERS["UNFAV"] = parse_fav_updated
# IGNORE/UNIGNORE: captura real 2026-10-01 (X1→T1000, fw 2.8.005): mismo
# "JT: Updated node !<id> (<SN>)" que FAV/UNFAV, y IGNORED refleja el cambio
# al instante; con un id que el destino no conoce responde "JT: Node
# '!<id>' not found" (cae a texto crudo, el parser lo rechaza).
# Las variantes forzadas (FFAV/FUNFAV/FIGNORE/FUNIGNORE) NO se registran: su
# respuesta ("Updated node"/"Forced node") no garantiza el efecto — FIGNORE
# confirmó sin ignorar nada. Ver interpret.FORCED_COMMANDS.
PARSERS["IGNORE"] = parse_fav_updated
PARSERS["UNIGNORE"] = parse_fav_updated


# --- ZH LIST / ADD / DEL (2026-09-28, captura real) ------------------------
# "Zero Hop" (categoría Firewall) — pedido explícito del usuario: destacarlo
# igual que favoritos/ignorados. `ZH ADD`/`ZH DEL` esperan SOLO los 2 últimos
# hex del id (`addressing.zero_hop_suffix`, §1.3) — confirmado con el
# argumento YA truncado (`ZH ADD 90`, no `ZH ADD !af000001`: una primera
# prueba con el id sin truncar, fuera del pipeline real de `build_command`,
# dio un resultado distinto y erróneo — 0x00 en vez de 0x90 — descartada).
#
# Vacío: "JT: ZH List is EMPTY". Con una entrada: "ZH List:\n[90]
# N001,N043\n" — SIN el prefijo "JT:" (misma inconsistencia ya vista en
# `WATCH LIST`/`FAVS`); el segundo campo tras la coma (`N043` aquí) no
# tiene significado confirmado, se devuelve tal cual sin interpretarlo.
# `ZH ADD`/`ZH DEL` confirman con "JT: ZH ID 0x<hex> ADDED"/"REMOVED".

_ZH_ENTRY_RE = re.compile(r"\[([0-9a-fA-F]{2})\]\s*([^,\n]*),([^\n]*)")


def parse_zh_list(text: str) -> dict[str, Any]:
    try:
        marker, body = _strip_marker(text, "JT: ZH List is EMPTY")
    except ValueError:
        marker, body = _strip_marker(text, "ZH List:")
    entries = [
        {"zh_id": zh_id.lower(), "short_name": short_name.strip(), "extra": extra.strip()}
        for zh_id, short_name, extra in _ZH_ENTRY_RE.findall(body)
    ]
    data: dict[str, Any] = {"entries": entries}
    if marker:
        data["marker"] = marker
    return data


PARSERS["ZH LIST"] = parse_zh_list

_ZH_ACTION_RE = re.compile(r"^JT:\s*ZH ID 0x([0-9a-fA-F]{2})\s+(ADDED|REMOVED)\s*$")


def parse_zh_action(text: str) -> dict[str, Any]:
    marker, body = _strip_marker(text, "JT:")
    match = _ZH_ACTION_RE.match(body)
    if not match:
        raise ValueError("formato 'ZH ID ... ADDED/REMOVED' no reconocido")
    data: dict[str, Any] = {"zh_id": match.group(1).lower(), "action": match.group(2)}
    if marker:
        data["marker"] = marker
    return data


PARSERS["ZH ADD"] = parse_zh_action
PARSERS["ZH DEL"] = parse_zh_action


# --- NIGN ADD / REM / LIST (2026-10-01, captura real X1→T1000, fw 2.8.005) --
# Lista de ignorados PERSISTENTE de Nexus (vault, hasta 64 nodos), distinta
# de IGNORE (solo RAM). Formatos reales:
#   ADD:  "🟢 JT: !e7ef4fb4 ADDED to ignores"
#   REM:  "🟢 JT: !e7ef4fb4 REMOVED"
#   LIST: "JT JT Ignores:\n[0] !e7ef4fb4 (CALP)\n" (cabecera con "JT" doble,
#         tal cual la emite el firmware) o "JT JT Ignores:\nList empty.\n".

# Además de ADDED/REMOVED (captura 2026-10-01): repetir ADD responde
# "already ignored" y quitar un id ausente responde "not in list".
_NIGN_ACTION_RE = re.compile(
    r"^JT:\s*(![0-9a-fA-F]{8})\s+(ADDED to ignores|REMOVED|already ignored|not in list)\s*$"
)
_NIGN_ACTIONS = {"ADDED": "ADDED", "REMOVED": "REMOVED", "already": "ALREADY", "not in": "NOT_IN_LIST"}
_NIGN_ENTRY_RE = re.compile(r"\[\d+\]\s*(![0-9a-fA-F]{8})(?:\s*\(([^)]*)\))?")


def parse_nign_action(text: str) -> dict[str, Any]:
    marker, body = _strip_marker(text, "JT:")
    match = _NIGN_ACTION_RE.match(body)
    if not match:
        raise ValueError("formato 'NIGN ADD/REM' no reconocido")
    data: dict[str, Any] = {
        "node_id": match.group(1).lower(),
        "action": next(v for k, v in _NIGN_ACTIONS.items() if match.group(2).startswith(k)),
    }
    if marker:
        data["marker"] = marker
    return data


def parse_nign_list(text: str) -> dict[str, Any]:
    marker, body = _strip_marker(text, "JT JT Ignores:")
    entries = [
        {"node_id": node_id.lower(), "short_name": short_name or ""}
        for node_id, short_name in _NIGN_ENTRY_RE.findall(body)
    ]
    data: dict[str, Any] = {"entries": entries}
    if marker:
        data["marker"] = marker
    return data


PARSERS["NIGN ADD"] = parse_nign_action
PARSERS["NIGN REM"] = parse_nign_action
PARSERS["NIGN LIST"] = parse_nign_list


# --- UPTIME (2026-10-01, respuesta real de campo) ---------------------------
# "🟢 JT UPTIME: 3d 0h 53m 14s" — una sola línea.

_UPTIME_RE = re.compile(
    r"^(?:(?P<marker>\S+)\s+)?(?:JT|Nexus) UPTIME:\s*"
    r"(?:(?P<d>\d+)d)?\s*(?:(?P<h>\d+)h)?\s*(?:(?P<m>\d+)m)?\s*(?:(?P<s>\d+)s)?\s*$"
)


def parse_uptime(text: str) -> dict[str, Any]:
    match = _UPTIME_RE.match(text.strip())
    if not match or not any(match.group(k) for k in "dhms"):
        raise ValueError("formato UPTIME no reconocido")
    d, h, m, sec = (int(match.group(k) or 0) for k in "dhms")
    value = text.strip().split("UPTIME:", 1)[1].strip()
    data: dict[str, Any] = {"uptime": value, "seconds": d * 86400 + h * 3600 + m * 60 + sec}
    if match.group("marker"):
        data["marker"] = match.group("marker")
    return data


PARSERS["UPTIME"] = parse_uptime
