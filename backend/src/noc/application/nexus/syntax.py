"""Sintaxis de argumentos de los comandos Nexus, para el asistente de la UI.

El catálogo (`catalog.py`) deliberadamente NO modela argumentos: viajan como
tokens libres y el firmware los valida. Este módulo es una capa APARTE, solo
de ayuda a la interfaz: describe, para los comandos cuya sintaxis está
confirmada, qué variantes existen y qué campos pide cada una, de modo que la
ventana «Catálogo» pueda guiar al operador sin que tenga que recordarlos.

Reglas:
- Fuente: manual v2.8.006 ("Manual Nuevo JT.pdf", prevalece) y, cuando la
  captura real contradice al manual, GANA el hardware (se anota en `note`).
- Un comando sin entrada aquí NO es un error: la UI cae al campo de texto
  libre de siempre. Nunca se inventa una sintaxis para rellenar un hueco.
- No decide nada de seguridad: destructivo / difusión / persistencia siguen
  saliendo de `catalog.py` y de `build_command`, que es lo que valida de
  verdad. Esto solo ayuda a teclear.
- `SETLORA`/`SETROLE` NO se modelan: el manual los lista pero el firmware
  real respondió «Unknown command» en campo (ver `catalog.py`).
"""

from dataclasses import dataclass, replace
from enum import StrEnum


class ArgKind(StrEnum):
    CHOICE = "choice"  # una de `choices`
    NODE = "node"  # `!hex8` o nombre corto
    NUMBER = "number"  # entero (con min/max opcionales)
    ONOFF = "onoff"  # ON | OFF
    TEXT = "text"  # texto libre (puede llevar espacios)
    HEX = "hex"  # 0x.. / hex


@dataclass(frozen=True, slots=True)
class Arg:
    name: str
    label: str
    kind: ArgKind
    choices: tuple[str, ...] = ()
    min: int | None = None
    max: int | None = None
    optional: bool = False
    placeholder: str = ""
    hint: str = ""
    # Solo ONOFF: lo que viaja por el aire para «activar»/«desactivar»
    # (por defecto las palabras; ver `_onoff` y las pruebas de campo).
    on_value: str = "ON"
    off_value: str = "OFF"


@dataclass(frozen=True, slots=True)
class Variant:
    """Una forma de invocar el comando: tokens fijos + argumentos a rellenar."""

    label: str
    tokens: tuple[str, ...] = ()
    args: tuple[Arg, ...] = ()
    note: str = ""
    # Probada contra hardware real (fixtures/acceptance). Prevalece sobre el
    # manual: lo no verificado es «según el manual», nunca al revés.
    verified: bool = False


def _node(hint: str = "") -> Arg:
    return Arg("node", "Nodo", ArgKind.NODE, placeholder="!xxxxxxxx o nombre corto", hint=hint)


# Valor de los interruptores: PALABRAS ON/OFF. Pruebas de campo (2026-10-01,
# T1000-E fw 2.8.005, con lectura de estado tras cada cambio): `on`/`off`
# funcionan en SECURITY (ALLOW_DM, SILENT_LOG), TA, CLIENTALWAYS, BASETEXTS y
# SETCONFIG SMART; `1`/`0` NO surten efecto en SECURITY ni en TA (el firmware
# responde con el estado sin cambiarlo), aunque sí valen en CLIENTALWAYS,
# BASETEXTS y SETCONFIG. Por eso el valor por defecto son las palabras.
# `_onoff(..., bits=True)` queda para un comando que algún día lo exija.
BIT_ON, BIT_OFF = "1", "0"


def _onoff(label: str = "Estado", bits: bool = False) -> Arg:
    if bits:
        return Arg("state", label, ArgKind.ONOFF, on_value=BIT_ON, off_value=BIT_OFF)
    return Arg("state", label, ArgKind.ONOFF)


def _num(name: str, label: str, lo: int | None = None, hi: int | None = None,
         hint: str = "", optional: bool = False) -> Arg:
    return Arg(name, label, ArgKind.NUMBER, min=lo, max=hi, hint=hint, optional=optional)


def _choice(name: str, label: str, *choices: str, optional: bool = False) -> Arg:
    return Arg(name, label, ArgKind.CHOICE, choices=choices, optional=optional)


def _text(name: str, label: str, placeholder: str = "", hint: str = "") -> Arg:
    return Arg(name, label, ArgKind.TEXT, placeholder=placeholder, hint=hint)


_DROP_TAGS = (
    "NODEINFO", "POSITION", "TELEMETRY", "NEIGHBOR", "TRACEROUTE", "TRACEROUTE_REMOTE",
    "TRACEROUTE_LOCAL", "TRACEROUTE_DIRECT", "TRACEROUTE_DIRECT_REMOTE",
    "TRACEROUTE_DIRECT_LOCAL", "PRIVATE", "HOP6", "HOP7", "REQ_NODEINFO", "REQ_TELEMETRY",
    "REQ_POSITION", "BR_NODEINFO", "BR_TELEMETRY", "BR_POSITION", "ACKS", "PKI", "PKI_REMOTE",
    "PKI_LOCAL", "PREHOP", "STORE_FORWARD", "ADMIN", "TEXT", "KEYVER", "ALERT", "WAYPOINT",
    "NO_MQTT", "FAV_BYPASS", "SKIP_SKIP",
)
# OUTDROP solo admite estos (manual §3.1, que los da solo por su abreviatura).
_OUTDROP_TAGS = ("NI", "PO", "TL", "TR", "AD", "RO")
_RATE_BUCKETS = ("TEXT", "TRACE", "OTHER", "NODEINFO", "POSITION", "TELEMETRY", "PRIVATE")
_HOP_PORTS = ("NODEINFO", "TELEMETRY", "POSITION", "TRACEROUTE", "TEXT")
_PRESETS = (
    "SF", "LF", "MS", "MF", "SS", "ST", "LT", "SPM", "P1", "P7",
    "NAP-1", "NAP-2", "NAP-3", "NAP-4", "NAP-5", "NAPN-1", "NAPN-2", "NAPN-3", "NAPN-4", "NAPN-5",
)  # fmt: skip

_READ = "Solo consulta: no cambia nada."

SYNTAX: dict[str, tuple[Variant, ...]] = {
    # --- Favoritos / ignorados de la NodeDB (§3.5) ------------------------
    **{
        name: (Variant(label, args=(_node(),), note=note),)
        for name, label, note in (
            ("FAV", "Marcar como favorito", ""),
            ("UNFAV", "Quitar de favoritos", ""),
            ("FFAV", "Forzar favorito", "Aunque el nodo aún no esté en su NodeDB; confirmar no garantiza efecto."),
            ("FUNFAV", "Forzar quitar favorito", "Confirmar no garantiza efecto."),
            ("IGNORE", "Ignorar nodo", ""),
            ("UNIGNORE", "Dejar de ignorar", ""),
            ("FIGNORE", "Forzar ignorar", "Confirmar no garantiza efecto (comprobado en campo)."),
            ("FUNIGNORE", "Forzar dejar de ignorar", "Con un id desconocido crea un nodo UNK."),
        )
    },
    "DELNODE": (Variant("Borrar nodo de la NodeDB", args=(_node(),),
                        note="Elimina la entrada por completo."),),
    "NODEDB": (Variant("Ficha de un nodo", args=(_node(),), note=_READ),),
    # NIGN: el manual dice DEL/CLEAR; en campo (fw 2.8.005) funcionan ADD/REM/LIST → gana el hardware.
    "NIGN": (
        Variant("Ver lista", ("LIST",), note=_READ),
        Variant("Añadir", ("ADD",), (_node(),), note="Ignorados persistentes (vault, hasta 64)."),
        Variant("Quitar", ("REM",), (_node(),), note="En campo el verbo es REM; el manual dice DEL."),
        Variant("Vaciar lista", ("CLEAR",), note="Según el manual; no probado en campo."),
    ),
    # --- Zero Hop (§3.6) --------------------------------------------------
    "ZH": (
        Variant("Estado global", note=_READ),
        Variant("Activar / desactivar", args=(_onoff("Zero-Hop"),), note="Aplicado a todos los nodos."),
        Variant("Preservar posición", ("POS",), (_onoff("Posición"),)),
        Variant("Preservar telemetría", ("TELE",), (_onoff("Telemetría"),)),
        Variant("Añadir relay", ("ADD",), (_node("Solo se envían los 2 últimos dígitos hex."),)),
        Variant("Quitar relay", ("DEL",), (_node("Solo se envían los 2 últimos dígitos hex."),)),
        Variant("Autocompletar desde la NodeDB", ("SYNC",),
                note="Favoritos y routers/bases conocidos."),
        Variant("Listar (con nombres)", ("LIST",), note=_READ),
        Variant("Listar (compacto)", ("SHORT",), note=_READ),
        Variant("Exportar máscara", ("EXPORT",), note=_READ),
        Variant("Importar máscara", ("IMPORT",),
                (_text("b64", "Base64 (44 caracteres)"),),
                note="Sobrescribe la máscara completa."),
        Variant("Vaciar máscara", ("CLEAR",), note="Borra los 256 relays."),
    ),
    # --- WATCH (§8) -------------------------------------------------------
    "WATCH": (
        Variant("Ver lista", ("LIST",), note=_READ),
        Variant("Añadir objetivo", ("ADD",), (_node(),), note="Máximo 8; solo en RAM."),
        Variant("Quitar objetivo", ("DEL",), (_node(),)),
        Variant("Estadísticas de un objetivo", ("STATS",), (_node(),),
                note="Exige el id del nodo (comprobado en campo)."),
        Variant("Estadísticas de todos", ("ALL",), note=_READ),
        Variant("Reiniciar contadores", ("RESET",), note="Mantiene los nodos de la lista."),
        Variant("Vaciar lista", ("CLEAR",)),
    ),
    # --- Firewall (§3) ----------------------------------------------------
    "DROP": (Variant("Descartar tipo de paquete (entrada)",
                     args=(_choice("tag", "Tipo", *_DROP_TAGS),)),),
    "UNDROP": (Variant("Dejar de descartar (entrada)",
                       args=(_choice("tag", "Tipo", *_DROP_TAGS),)),),
    "OUTDROP": (Variant("Descartar tipo de paquete (salida)",
                        args=(_choice("tag", "Tipo", *_OUTDROP_TAGS),)),),
    "UNOUTDROP": (Variant("Dejar de descartar (salida)",
                          args=(_choice("tag", "Tipo", *_OUTDROP_TAGS),)),),
    "RDROP": (
        Variant("Ver relays descartados", note=_READ),
        Variant("Descartar relay", args=(Arg("relay", "Relay", ArgKind.HEX, placeholder="*A4 o A4",
                                             hint="Último byte del relay."),)),
        Variant("Vaciar", ("CLEAR",), note="Quita todos los relays descartados."),
    ),
    "RUNDROP": (Variant("Dejar de descartar relay",
                        args=(Arg("relay", "Relay", ArgKind.HEX, placeholder="*A4 o A4"),)),),
    "IDR": (
        Variant("Ver estado", note=_READ),
        Variant("Activar / desactivar", args=(_onoff("Supresión"),
                                              _num("window", "Ventana (s)", 1, optional=True)),
                note="Ignora relays duplicados de un mismo relay dentro de la ventana."),
    ),
    "INVALIDS": (
        Variant("Ver estado", note=_READ),
        Variant("Cambiar filtro", args=(
            _choice("rule", "Regla", "ZERONODES", "MAXNODE", "HOPSTART", "BADPAYLOAD", "ALL"),
            _onoff("Valor"))),
    ),
    "FSIG": (
        Variant("Ver ranuras", note=_READ),
        Variant("Fijar firma", ("SET",), (
            _num("slot", "Ranura", 1, 8),
            _text("pattern", "Patrón", "DEADBEEF, texto o base64",
                  "Se autodetecta hex/base64/texto; máx. 16 bytes."))),
        Variant("Borrar firma", ("OFF",), (_num("slot", "Ranura", 1, 8),)),
    ),
    "PRWHITELIST": (
        Variant("Ver lista", ("LIST",), note=_READ),
        Variant("Añadir canal", ("ADD",), (Arg("hash", "Hash de canal", ArgKind.HEX, placeholder="0xC3"),)),
        Variant("Quitar canal", ("REM",), (Arg("hash", "Hash de canal", ArgKind.HEX, placeholder="0xC3"),)),
    ),
    "PRBLACKLIST": (
        Variant("Ver lista", ("LIST",), note=_READ),
        Variant("Añadir canal", ("ADD",), (Arg("hash", "Hash de canal", ArgKind.HEX, placeholder="0xC3"),)),
        Variant("Quitar canal", ("REM",), (Arg("hash", "Hash de canal", ArgKind.HEX, placeholder="0xC3"),)),
    ),
    "RATELIMIT": (
        Variant("Ver estado", note=_READ),
        Variant("Configurar cubo", args=(
            _choice("bucket", "Tipo de tráfico", *_RATE_BUCKETS),
            _num("max", "Máx. paquetes", 0), _num("window", "Ventana (s)", 1))),
    ),
    # --- Saltos (§4) ------------------------------------------------------
    "HOPMASK": (
        Variant("Ver estado", note=_READ),
        Variant("Fijar saltos", args=(_num("start", "hop_start", 0, 7), _num("limit", "hop_limit", 0, 7))),
        Variant("Desactivar", ("OFF",)),
    ),
    "CH-HOPMASK": (
        Variant("Ver todos", note=_READ),
        Variant("Fijar por canal", args=(_num("ch", "Canal", 0, 7), _num("start", "hop_start", 0, 7),
                                         _num("limit", "hop_limit", 0, 7))),
        Variant("Desactivar canal", args=(_num("ch", "Canal", 0, 7), Arg("off", "OFF", ArgKind.CHOICE, choices=("OFF",)))),
    ),
    "PORT-HOPMASK": (
        Variant("Ver todos", note=_READ),
        Variant("Fijar por puerto", args=(_choice("port", "Puerto", *_HOP_PORTS),
                                          _num("start", "hop_start", 0, 7), _num("limit", "hop_limit", 0, 7))),
        Variant("Desactivar puerto", args=(_choice("port", "Puerto", *_HOP_PORTS),
                                           Arg("off", "OFF", ArgKind.CHOICE, choices=("OFF",)))),
    ),
    "HOPSCALE": (
        Variant("Ver factor", note=_READ),
        Variant("Fijar factor", args=(_num("val", "Factor"),)),
    ),
    # --- Radio (§5) -------------------------------------------------------
    "SETPOWER": (Variant("Potencia de transmisión", args=(_num("dbm", "dBm", 0, 30),)),),
    "SETPREAMBLE": (
        Variant("Ver preámbulo", note=_READ),
        Variant("Fijar preámbulo", args=(_num("len", "Símbolos", 6, 1024),)),
    ),
    "SETSYNCWORD": (
        Variant("Fijar sync word", args=(Arg("hex", "Valor", ArgKind.HEX, placeholder="0x12",
                                             hint="0x00–0xFF. Cambiarlo aísla el nodo de la malla."),)),
        Variant("Restaurar por defecto (0x2B)", args=(Arg("reset", "RESET", ArgKind.CHOICE, choices=("RESET",)),)),
    ),
    "PRESET": (Variant("Aplicar preset de LoRa", args=(_choice("preset", "Preset", *_PRESETS),),
                       note="Se aplica pasados unos segundos."),),
    "SETREBROADCAST": (Variant("Modo de rebroadcast", args=(
        _choice("mode", "Modo", "ALL", "ALL_SKIP", "LOCAL_ONLY", "KNOWN_ONLY"),)),),
    "TX": (Variant("Transmisor de radio", args=(_onoff("Transmisor"),),
                   note="OFF deja el nodo solo en escucha (apagar el transmisor es destructivo)."),),
    "CLIENTALWAYS": (
        Variant("Ver estado", note=_READ),
        Variant("Activar / desactivar", args=(_onoff("Client Always"),),
                note="Solo si el nodo debe repetir como un router sin poder serlo."),
    ),
    "BASETEXTS": (Variant("Activar / desactivar", args=(_onoff("Base Texts"),),
                          note="Como Client Always pero solo para mensajes de texto."),),
    # --- Configuración (§10) ----------------------------------------------
    "SETCONFIG": (
        Variant("Intervalo de NodeInfo", ("NI",), (_num("secs", "Segundos", 0),)),
        Variant("Intervalo de telemetría de dispositivo", ("TEL_D",), (_num("secs", "Segundos", 0),)),
        Variant("Intervalo de telemetría ambiental", ("TEL_E",), (_num("secs", "Segundos", 0),)),
        Variant("Intervalo de telemetría de energía", ("TEL_P",), (_num("secs", "Segundos", 0),)),
        Variant("Intervalo de posición", ("POS",), (_num("secs", "Segundos", 0),)),
        Variant("Posición inteligente", ("SMART",), (_onoff("Smart position"),)),
        Variant("Posición fija", ("FIXED",), (_onoff("Fixed position"),)),
        Variant("GPS", ("GPS",), (_onoff("GPS"),)),
        Variant("Coordenadas manuales", ("LOC",),
                (_text("loc", "lat,lon", "49.15163,9.25764", "Sin espacio tras la coma."),)),
    ),
    "SECURITY": (
        Variant("Ver estado", note=_READ),
        Variant("Cambiar regla", args=(_choice("rule", "Regla", "REQ_SIG", "ALLOW_DM", "SILENT_LOG"),
                                       _onoff("Valor")),
                note="Usa ON/OFF: con 1/0 el nodo ignora el cambio (comprobado en campo)."),
    ),
    "BD": (
        Variant("Ver retardo", note=_READ),
        Variant("Fijar retardo", ("SET",), (_num("secs", "Segundos", 1, 300),)),
    ),
    "FREEZE": (
        Variant("Ver estado", note=_READ),
        Variant("Congelar todo", ("ON",)),
        Variant("Descongelar todo", ("OFF",)),
        Variant("Un subsistema", args=(_choice("subsys", "Subsistema", "NODEDB", "WARM", "DEVICE", "CONFIG"),
                                       _onoff("Congelado"))),
    ),
    # --- Mensajería e inyección (§12) -------------------------------------
    "TEXT": (Variant("Texto por el canal principal", args=(_text("msg", "Mensaje"),)),),
    "TEXTC": (Variant("Texto por un canal", args=(_num("ch", "Canal", 0, 7), _text("msg", "Mensaje"))),),
    "DM": (Variant("Mensaje directo", args=(_node(), _text("msg", "Mensaje"))),),
    "PPING": (
        Variant("Ver estado", note=_READ),
        Variant("Activar / desactivar", args=(_onoff("Respuesta a ping"),)),
        Variant("Modo emoji", ("EMOJI",), (_choice("mode", "Modo", "OFF", "INDIRECT", "ALWAYS"),)),
        Variant("Cabecera de respuesta", ("HEADER",),
                (_text("text", "Texto (o OFF)", "OFF para quitarla"),)),
    ),
    "FREQSCAN": (Variant("Medir ruido en una frecuencia",
                         args=(Arg("freq", "Frecuencia (MHz)", ArgKind.TEXT, placeholder="868.0"),
                               _num("bw", "Ancho de banda (kHz)", 1)),
                         note="Deja el TX deshabilitado mientras mide."),),
    # --- Alertas / automatización (§11, §13) ------------------------------
    "TA": (
        Variant("Ver estado", note=_READ),
        Variant("Activar / desactivar", args=(_onoff("Trace Alert"),)),
        Variant("Modo", ("MODE",), (_choice("mode", "Modo", "0", "1", "2"),),
                note="0 = solo directos, 1 = solo relayados, 2 = todos."),
    ),
    "GROUP": (
        Variant("Listar grupos", ("LIST",), note=_READ),
        Variant("Añadir nodo a grupo", ("ADD",), (_text("grp", "Grupo"), _node())),
        Variant("Quitar nodo de grupo", ("DEL",), (_text("grp", "Grupo"), _node())),
    ),
    "ALIAS": (
        Variant("Listar alias", ("LIST",), note=_READ),
        Variant("Asignar alias", ("SET",), (_node(), _text("alias", "Alias (4 caracteres)"))),
        Variant("Borrar alias", ("DEL",), (_node(),)),
    ),
    "CRON": (
        Variant("Listar tareas", ("LIST",), note=_READ),
        Variant("Programar tarea", ("SET",), (_num("slot", "Ranura", 1, 8), _num("min", "Cada (min)", 1),
                                              _text("cmd", "Comando", "NOISE"))),
        Variant("Desactivar ranura", ("OFF",), (_num("slot", "Ranura", 1, 8),)),
    ),
    "REBOOT": (Variant("Reiniciar el dispositivo", note="Reinicia con 20 s de margen."),),
    # --- Tanda 2 (solo manual v2.8.006, sin probar en campo) ----------------
    "SKEY": (
        Variant("Fijar clave secundaria", args=(
            _choice("slot", "Ranura", "1", "2", "3", "4"),
            _text("key", "Clave", "Base64 o hex", "Clave pública de administración remota."))),
        Variant("Borrar clave", args=(_choice("slot", "Ranura", "1", "2", "3", "4"),
                                      Arg("off", "OFF", ArgKind.CHOICE, choices=("OFF",)))),
    ),
    "MACRO": (
        Variant("Listar macros", ("LIST",), note=_READ),
        Variant("Guardar macro", ("SET",), (_num("idx", "Ranura", 1, 4), _text("name", "Nombre"),
                                            _text("cmds", "Comandos", "RSSI; POS; UTIL",
                                                  "Separados por «;» dentro del propio macro."))),
        Variant("Ejecutar macro", ("RUN",), (_text("ref", "Ranura o nombre"),),
                note="Un paso cada 10 s."),
        Variant("Borrar macro", ("DEL",), (_num("idx", "Ranura", 1, 4),)),
    ),
    "DM-FORWARD": (
        Variant("Activar reenvío de DMs", args=(Arg("state", "Estado", ArgKind.CHOICE, choices=("ON",)),
                                                _node())),
        Variant("Desactivar reenvío", args=(Arg("state", "Estado", ArgKind.CHOICE, choices=("OFF",)),)),
    ),
    "DMTEST": (Variant("Medir latencia de DM", args=(_node(),)),),
    "MQTT": (
        Variant("Ver estado", note=_READ),
        Variant("Reconectar", args=(Arg("action", "Acción", ArgKind.CHOICE, choices=("STATUS", "CONNECT")),)),
    ),
    "OKTOMQTT": (
        Variant("Ver estado", note=_READ),
        Variant("Activar / desactivar", args=(_onoff("ok_to_mqtt"),)),
    ),
    "TM": (Variant("Módulo de gestión de tráfico", args=(_text("mod", "Módulo"), _onoff("Módulo")),
                   note="Sin el último campo solo consulta; aquí se envía siempre ON/OFF."),),
    "LNA": (Variant("Ver ganancia LNA", note=_READ + " Específico de Heltec V4.3."),),
    "SETLNA": (Variant("Fijar modo LNA", args=(_text("mode", "Modo"),),
                       note="Específico de Heltec V4.3."),),
    "G3": (
        Variant("Ver estado", note=_READ),
        Variant("LNA", ("LNA",), (_onoff("LNA"),)),
        Variant("PA", ("PA",), (_onoff("PA"),)),
    ),
    "LR2021_SF": (Variant("SF concurrentes", args=(_text("sfs", "SFs", "7 8 9",
                                                         "Solo hardware LR2021; el SF lateral debe ser MAYOR que el principal."),)),),
    "SETCHNAME": (Variant("Renombrar canal", args=(_num("idx", "Canal", 0, 7), _text("name", "Nombre"))),),
    "SETCHPSK": (Variant("Cambiar PSK de canal", args=(
        _num("idx", "Canal", 0, 7),
        _text("psk", "Clave", "default, none, base64 o hex"))),),
    "ADDCH": (Variant("Añadir canal", args=(_text("name", "Nombre"),
                                            Arg("psk", "PSK", ArgKind.TEXT, optional=True,
                                                placeholder="default, none, base64 o hex")),
                      note="Usa el primer slot libre."),),
    "DELCH": (Variant("Borrar canal", args=(_num("idx", "Canal", 1, 7),),
                      note="El canal 0 (principal) no se puede borrar."),),
    "SEARCHKEY": (Variant("Buscar nodo por clave pública", args=(_text("key", "Prefijo en Base64"),),
                          note=_READ),),
    "SEARCHRELAY": (Variant("Buscar nodos por relay", args=(
        Arg("relay", "Relay", ArgKind.HEX, placeholder="*A4 o A4"),), note=_READ),),
    "CLIENTSCAN": (Variant("Detectar clientes que repiten",
                           args=(_num("time", "Espera (s)", 1, optional=True),), note=_READ),),
    "RSSILOG": (Variant("Últimos paquetes recibidos", args=(_num("n", "Entradas", 1, optional=True),),
                        note=_READ),),
    "SHARE": (Variant("Compartir un nodo (URL)", args=(_node(),), note=_READ),),
    "DECODEURL": (Variant("Decodificar URL de canal", args=(_text("url", "URL"),), note=_READ),),
    "CAT": (Variant("Leer fichero", args=(_text("file", "Fichero", "/prefs/db.proto"),), note=_READ),),
    "RM": (Variant("Borrar fichero", args=(_text("file", "Fichero"),), note="Irreversible."),),
    "SETTIME": (Variant("Fijar reloj", args=(_num("epoch", "Epoch (s)", 0),),
                        note="Segundos Unix."),),
    "GPIO": (
        Variant("Ver máscara y pines", note=_READ),
        Variant("Leer pin", args=(_num("pin", "Pin", 0),), note=_READ),
        Variant("Fijar pin", args=(_num("pin", "Pin", 0), _choice("level", "Nivel", "H", "L"))),
        Variant("Vigilar pin", ("WATCH",), (_text("pin", "Pin u OFF"),)),
    ),
    "PLAY": (Variant("Melodía RTTTL", args=(_text("melody", "Melodía RTTTL"),)),),
    "FAKEPOS": (Variant("Inyectar posición fija", args=(
        Arg("lat", "Latitud", ArgKind.TEXT, placeholder="40.4168"),
        Arg("lon", "Longitud", ArgKind.TEXT, placeholder="-3.7038"),
        _num("alt", "Altitud (m)"),
        _num("ch", "Canal", 0, 7, optional=True)),
        note="El canal opcional se envía como «C <n>» en el manual; déjalo vacío salvo que lo necesites."),),
    "FAKERANDPOS": (Variant("Inyectar posición aleatoria", args=(
        Arg("lat_min", "Lat. mín.", ArgKind.TEXT), Arg("lat_max", "Lat. máx.", ArgKind.TEXT),
        Arg("lon_min", "Lon. mín.", ArgKind.TEXT), Arg("lon_max", "Lon. máx.", ArgKind.TEXT),
        _num("alt", "Altitud (m)"))),),
    "BSAVE": (Variant("Copia de seguridad en flash"),),
    "BLOAD": (Variant("Restaurar copia", note="Reinicia el nodo."),),
}

# (comando, etiqueta de variante) probadas con hardware real: fixtures
# `captura-20260928-*` y docs/acceptance/nexus-consola-campo.md.
_VERIFIED = frozenset((
        ("FAV", "Marcar como favorito"), ("UNFAV", "Quitar de favoritos"),
        ("FFAV", "Forzar favorito"), ("FUNFAV", "Forzar quitar favorito"),
        ("IGNORE", "Ignorar nodo"), ("UNIGNORE", "Dejar de ignorar"),
        ("FIGNORE", "Forzar ignorar"), ("FUNIGNORE", "Forzar dejar de ignorar"),
        ("DELNODE", "Borrar nodo de la NodeDB"),
        ("NIGN", "Ver lista"), ("NIGN", "Añadir"), ("NIGN", "Quitar"),
        ("ZH", "Listar (con nombres)"), ("ZH", "Añadir relay"), ("ZH", "Quitar relay"),
        ("WATCH", "Ver lista"), ("WATCH", "Añadir objetivo"), ("WATCH", "Quitar objetivo"),
        ("WATCH", "Estadísticas de un objetivo"),
        ("FSIG", "Ver ranuras"), ("FSIG", "Fijar firma"), ("FSIG", "Borrar firma"),
        ("SECURITY", "Ver estado"),
))
SYNTAX = {
    name: tuple(replace(v, verified=(name, v.label) in _VERIFIED) for v in variants)
    for name, variants in SYNTAX.items()
}

# Alias de comandos que comparten sintaxis con otro nombre canónico.
_SHARED = {"SETPRESET": "PRESET"}
SYNTAX.update({alias: SYNTAX[canon] for alias, canon in _SHARED.items()})


def syntax_for(name: str) -> tuple[Variant, ...]:
    """Variantes de `name` (ya canónico) o `()` si no hay sintaxis modelada."""
    return SYNTAX.get(name, ())
