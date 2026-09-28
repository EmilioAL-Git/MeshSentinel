"""Catálogo CERRADO de comandos JenTastic-Nexus.

Regla del usuario: nada que no esté documentado. Los argumentos viajan como
tokens libres (el firmware los valida); aquí solo se modela lo que las
fuentes afirman de forma explícita: alias, comandos destructivos, bloqueados
en difusión, tiempos de "nodo sordo" y persistencia con SAVE.

Fuente PRINCIPAL desde 2026-09-28: "Manual Nuevo JT.pdf" — manual de la
build pública Nexus-28006 (v2.8.006+), que se declara "verified directly
against the C++ source code" y prevalece sobre cualquier otra fuente en
conflicto (orden explícito del usuario). Fuentes previas (referencia
v2.8.005 y el "prompt de implementación") solo se conservan donde el manual
no dice lo contrario.

**Excluidos por confirmarse ausentes de la build pública** (el propio manual:
"private/tactical extension commands... intentionally omitted"): BURNER,
ROLEMASK, SETMULTIROLE (no aparecen ni en las tablas ni en el índice
alfabético — antes se habían catalogado a partir de una fuente menos
fiable). También ADDURL y USETCHNAME (el "prefijo U salta protección de
canales" no aparece en ningún sitio del manual — probablemente un error de
la fuente anterior). AIRTAG sigue excluido: el propio manual lo marca
"NOT IMPLEMENTED".

**Reemplazados** por la forma que confirma el manual: INVALID/UNINVALID →
INVALIDS (un único comando con `<RULE> [ON|OFF]`, no dos verbos separados);
REBROADCAST → SETREBROADCAST (el manual no documenta ningún "REBROADCAST" a
secas). PRALLOW/PRBLOCK pasan a ser ALIAS de PRWHITELIST/PRBLACKLIST, no
comandos aparte (el manual: "PRWHITELIST / PRALLOW" es una misma fila).

**Alias resueltos**: `RL` es alias real de RATELIMIT (no de RSSILOG, que
usa `PL`) — confirmado por el manual; ya no es ambiguo. `TA` es el nombre
canónico (no `TR_ALERT`, que no aparece en el manual). `DMF` es alias de
`DM-FORWARD`.

**FSIG** confirmado real (8 slots, `SET <1-8> <pattern>`/`OFF <1-8>`, auto-
detecta hex/base64/texto, máx 16 bytes) — sintaxis ya no pendiente.
**SECURITY** confirmado con solo 3 bits en la build pública: `REQ_SIG`,
`ALLOW_DM`, `SILENT_LOG` (+ contador `REP_Protection`); `AUTO_FAV_NEXUS`/
`AUTO_FAV_TRUSTED`/`BYPASS_RP` NO aparecen — confirmados ausentes, no solo
"no verificados".

**Pendiente de re-verificar con captura real** (firmware 2.8.006, el nodo de
prueba T1000 se ha actualizado): `NODES` — la captura contra firmware
2.7.268 devolvió un volcado paginado completo bajo cabecera "JT NodeDB:",
pero el manual v2.8.006 describe `NODES` como un resumen corto de una línea
("JT NODES: <total> total (<active> active in last 2h)"), sin paginar. El
comportamiento pudo cambiar entre versiones de firmware — `parse_nodes`
(parsers.py) se deja tal cual (sigue siendo el dato real capturado contra
2.7.268) hasta confirmar cuál es el formato en 2.8.006.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Category(StrEnum):
    SYSTEM = "system"  # §3.1
    STATS = "stats"  # §3.2 SIGINT / estadísticas
    SCAN = "scan"  # §3.3
    NODEDB = "nodedb"  # §3.4
    FIREWALL = "firewall"  # §3.5–3.7
    STEALTH = "stealth"  # §3.8
    INJECTION = "injection"  # §3.9 (testing)
    CONFIG = "config"  # §3.10
    SENSORS = "sensors"  # §3.11
    STORAGE = "storage"  # §3.12
    ALERTS = "alerts"  # §3.13
    PPING = "pping"  # §3.14
    SECURITY = "security"  # §2.3
    CRITICAL = "critical"  # §3.15


class Mutation(StrEnum):
    NEVER = "never"  # consulta pura
    ALWAYS = "always"
    WITH_ARGS = "with_args"  # sin argumentos = consulta (p. ej. `SECURITY`)


class Persistence(StrEnum):
    NONE = "none"  # no cambia nada persistible
    SAVE = "save"  # hace falta `/nexus SAVE` para sobrevivir a un reinicio
    AUTO = "auto"  # el firmware persiste solo (RATELIMIT, identidad que reinicia)


# Subverbos de solo lectura dentro de comandos que también mutan
# (`ZH LIST`, `WATCH STATS`, `GROUP LIST`, `ZH EXPORT`...).
READ_VERBS = frozenset({"LIST", "STATS", "EXPORT"})


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    category: Category
    aliases: tuple[str, ...] = ()
    mutation: Mutation = Mutation.NEVER
    # SAVE por defecto en todo lo que muta: §7.4 dice "casi ningún cambio de
    # configuración se guarda solo". Sobrestimar solo muestra un recordatorio
    # de más; subestimar perdería cambios al reiniciar.
    persistence: Persistence = Persistence.SAVE
    broadcast_forbidden: bool = False  # §2.2
    destructive: bool = False  # §7.3 (comando completo)
    destructive_verbs: frozenset[str] = field(default_factory=frozenset)  # ZH CLEAR/IMPORT...
    # Destructivo según el VALOR de un argumento, no el comando entero:
    # `TX OFF` sí, `TX ON` no; `SETSYNCWORD` distinto del valor por defecto sí.
    destructive_arg_equals: frozenset[str] = field(default_factory=frozenset)  # TX OFF
    destructive_unless_value: str | None = None  # SETSYNCWORD != 0x2B
    busy_seconds: float = 0.0  # §7.5: nodo sordo/ocupado tras recibirlo
    hardware_note: str | None = None


def _q(name: str, cat: Category, *aliases: str, busy: float = 0.0) -> CommandSpec:
    """Consulta (no muta)."""
    return CommandSpec(name, cat, aliases, Mutation.NEVER, Persistence.NONE, busy_seconds=busy)


def _m(name: str, cat: Category, *aliases: str, busy: float = 0.0, **kw: object) -> CommandSpec:
    """Muta siempre."""
    return CommandSpec(
        name, cat, aliases, Mutation.ALWAYS, busy_seconds=busy, **kw  # type: ignore[arg-type]
    )


def _a(name: str, cat: Category, *aliases: str, **kw: object) -> CommandSpec:
    """Consulta sin argumentos, mutación con argumentos."""
    return CommandSpec(name, cat, aliases, Mutation.WITH_ARGS, **kw)  # type: ignore[arg-type]


S, ST, SC, DB, FW, SH, INJ, CF, SE, STO, AL, PP, SEC, CR = (
    Category.SYSTEM, Category.STATS, Category.SCAN, Category.NODEDB, Category.FIREWALL,
    Category.STEALTH, Category.INJECTION, Category.CONFIG, Category.SENSORS,
    Category.STORAGE, Category.ALERTS, Category.PPING, Category.SECURITY, Category.CRITICAL,
)  # fmt: skip

_SPECS: tuple[CommandSpec, ...] = (
    # §2 Ayuda y build
    _q("HELP", S, "?"), _q("COMPILATION", S, "COMP"),
    # §3.1/§6/§11 Monitorización y sistema
    _q("INFO", S), _q("SYS", S), _q("HW", S), _q("ACC", S), _q("HEAP", S), _q("PSRAM", S),
    _q("RAM", S, "MEM"), _q("UPTIME", S, "UP"), _q("VERSION", S, "V"), _q("TIME", S),
    _m("SETTIME", S, persistence=Persistence.NONE), _q("FS", S), _q("PHONE", S),
    _a("GPIO", S, persistence=Persistence.NONE),
    # §3.2/§7 SIGINT / estadísticas. RL es alias real de RATELIMIT (no de
    # RSSILOG, que usa PL) — confirmado por el manual, ya no es ambiguo.
    _q("STATS", ST), _q("SIGSTATS", ST, "SS"), _q("RSSILOG", ST, "PL"),
    _q("HOPSTATS", ST, "HS"), _q("HOPMATRIX", ST, "HM"), _q("PACKETSTATS", ST, "PS"),
    _q("CHANNELSTATS", ST, "CHS"), _q("SORTEDCHANNELSTATS", ST, "SCHS"),
    _q("SORTEDPACKETSTATS", ST, "SPS"), _q("TRANSSTATS", ST, "TS"),
    _q("FIREWALLSTATS", ST, "FWS"), _q("FIREWALL", ST, "FW"),
    _q("RELAYS", ST, "RY"), _q("SORTEDRELAYSTATS", ST, "SRY"),
    _m("CLRSTATS", ST, "CS", persistence=Persistence.NONE), _q("MQTTSTATS", ST, "MQS"),
    _q("VERIFYSTATS", ST, "VS"), _q("CRSTATS", ST, "CRS"), _q("RATELIMITSTAT", ST),
    _q("RSSI", ST, "RS"), _q("SHORTRSSI", ST, "SR"), _q("RSSITEL", ST, "RT"),
    # §3.3/§7 Escaneo activo
    _q("NETSCAN", SC, busy=60), _q("CLIENTSCAN", SC), _q("NOISE", SC),
    _q("FREQSCAN", SC, busy=15), _a("WATCH", SC), _q("SEARCHKEY", SC),
    _q("SEARCHRELAY", SC, "SRELAY"),
    # §3.4/§6 Base de datos de nodos. NODES: PENDIENTE re-verificar formato en
    # firmware 2.8.006 (ver docstring del módulo).
    _q("NODES", DB), _q("NODES28", DB, "N28"), _q("FNODE", DB), _q("NODEDB", DB, "DB"),
    _q("DBINFO", DB), _q("INFRA", DB), _q("NEIGHBORS", DB, "DIRECT"), _q("FAVS", DB),
    _q("IGNORED", DB), _q("ADMINS", DB), _a("ALIAS", DB), _m("FAV", DB), _m("UNFAV", DB),
    _m("IGNORE", DB), _m("UNIGNORE", DB), _m("DELNODE", DB, destructive=True), _m("FFAV", DB),
    _m("FIGNORE", DB), _m("FUNFAV", DB), _m("FUNIGNORE", DB),
    _m("FIXMYINFO", DB, "FMI", persistence=Persistence.NONE),
    # §3.5–3.7 Firewall y filtros
    _m("DROP", FW), _m("UNDROP", FW), _q("DROPS", FW), _q("HEXDROPS", FW), _m("SETHEX", FW),
    _m("OUTDROP", FW), _m("UNOUTDROP", FW), _q("OUTDROPS", FW), _q("HEXOUTDROPS", FW),
    _m("SETHEXOUT", FW),
    # INVALIDS: un único comando `<RULE> [ON|OFF]` (bare = consulta), NO dos
    # verbos INVALID/UNINVALID como decía la fuente anterior.
    _a("INVALIDS", FW, "INV"),
    _a("RATELIMIT", FW, "RL", persistence=Persistence.AUTO),
    _m("RDROP", FW, destructive_verbs=frozenset({"CLEAR"})), _m("RUNDROP", FW),
    # IDR: bare = consulta de estado ("Displays current... status").
    _a("IDR", FW, "IGNORE-DUPERELAY"), _m("UNIDR", FW),
    # ZH IMPORT sobrescribe la máscara completa del nodo: tan destructivo como CLEAR.
    _a("ZH", FW, destructive_verbs=frozenset({"CLEAR", "IMPORT"})), _a("NIGN", FW),
    # PRWHITELIST/PRBLACKLIST son la forma real (manual §3.3); PRALLOW/PRBLOCK
    # son sus alias, no comandos aparte.
    _a("PRWHITELIST", FW, "PRALLOW"), _a("PRBLACKLIST", FW, "PRBLOCK"),
    _a("FSIG", FW),  # 8 slots, SET <1-8> <patrón> / OFF <1-8>, auto hex/b64/texto
    # §4 Hop-aware routing (antes catalogado como "stealth" sin serlo)
    _a("HOPMASK", SH), _a("CH-HOPMASK", SH, "CHM"), _a("PORT-HOPMASK", SH, "PHM"),
    _a("HOPSCALE", SH, "HSC"),
    # §5 Radio / RF (TRUSTED/CLIENTALWAYS/BASETEXTS/RELAYSPOOF confirmados en
    # build pública). BURNER/ROLEMASK/SETMULTIROLE EXCLUIDOS — ver docstring.
    _a("RELAYSPOOF", SH), _a("TRUSTED", SH), _a("CLIENTALWAYS", SH, "CA"),
    _a("BASETEXTS", SH, "BT"),
    # Identidad permanente: reinician el nodo (persisten solas) y el firmware
    # las bloquea en difusión. El manual no da su tiempo de reinicio; se
    # asume el de REBOOT (20 s) — PENDIENTE de verificar contra un nodo real.
    _m("NAME", SH, persistence=Persistence.AUTO, broadcast_forbidden=True,
       destructive=True, busy=20),
    _m("OWNER", SH, persistence=Persistence.AUTO, broadcast_forbidden=True,
       destructive=True, busy=20),
    _m("REVERT", SH, persistence=Persistence.AUTO, broadcast_forbidden=True,
       destructive=True, busy=20),
    # §3.9/§12 Mensajería e inyección de paquetes (testing)
    *(_m(n, INJ, persistence=Persistence.NONE) for n in (
        "TEXT", "TEXTC", "DM", "DMTEST", "FTEXT", "FTEXTM", "FTEXTH",
        "SMI", "FAKENODE", "FNH", "FNM", "INJECT")),
    _m("SENDNODE", INJ, "SENDMYNODE", persistence=Persistence.NONE),
    _m("SENDPOS", INJ, persistence=Persistence.NONE),
    _m("FAKEPOS", INJ, "FP", persistence=Persistence.NONE),
    _m("FAKERANDPOS", INJ, "FRP", persistence=Persistence.NONE),
    _m("REDIRECT", INJ, "R", persistence=Persistence.NONE),
    _a("DM-FORWARD", INJ, "DMF"),
    # §3.10 Configuración. SETCONFIG confirmado por captura real (2026-09-28,
    # nodo T1000-E, firmware 2.8.005): sin argumentos responde con su propio
    # mensaje de uso, "JT SETCONFIG: NI|TEL_D|TEL_E|TEL_P|POS|SMART|FIXED|GPS
    # <val> | LOC lat,lon" — un campo por comando, LOC como forma especial
    # "lat,lon" sin espacio. SETROLE y SETLORA (este último ya registrado
    # como destructivo por una fuente anterior) respondieron los dos "JT:
    # Unknown command" en esa misma captura — el nodo probado corre la build
    # PRIVADA (más comandos que la pública, confirmado por el usuario), así
    # que si ni siquiera esa build los reconoce es dudoso que existan de
    # verdad con ese nombre exacto en ninguna build; se mantienen en el
    # catálogo por si acaso (un "Unknown command" del firmware es inofensivo,
    # nunca aplica nada), pero sin usarlos en la plantilla de perfil de nodo
    # hasta confirmar de dónde salieron. Ver docs/design/nexus-control.md.
    _q("CONFIG", CF), _m("SETCONFIG", CF), _q("ROLE", CF), _m("SETROLE", CF),
    _q("LORA", CF, "LR"), _q("LORA-STATUS", CF, "LRS"), _q("PRESET", CF),
    _m("SETPRESET", CF), _m("SETLORA", CF, busy=5, destructive=True),
    _m("SETPREAMBLE", CF, "SETPRE", busy=5),
    _m("SETPOWER", CF, "SETPWR"), _q("GETTXPOWER", CF),
    # Destructivo salvo que se deje/restaure el valor por defecto 0x2B (manual §5).
    _m("SETSYNCWORD", CF, "SETSW", busy=5, destructive_unless_value="0x2B"),
    _a("LR2021_SF", CF, "MULTISF", hardware_note="Solo hardware LR2021; en SX1262 no tiene "
       "efecto. El SF lateral debe ser MAYOR que el principal."),
    _a("G3", CF, "FRONTEND"),
    _a("PMGT", CF), _a("WIFI", CF), _q("LNA", CF), _m("SETLNA", CF),
    _m("SETREBROADCAST", CF), _a("IGNOREMQTT", CF), _a("MQTT", CF),
    _a("TM", CF), _a("FEATURES", CF), _q("MODULES", CF, "MOD"), _q("FULLCONFIGDUMP", CF),
    _m("GOODPRACTICES", CF, "BUENASPRACTICAS", "GP", "BP"), _a("OKTOMQTT", CF),
    _m("ADDCH", CF), _m("SETCHNAME", CF), _m("SETCHPSK", CF), _m("DELCH", CF),
    _q("CHASH", CF, "CH"), _q("DECODEURL", CF, "DU"),
    _m("SHARE", CF, persistence=Persistence.NONE),
    # §2.3/§10 SECURITY: bits confirmados REQ_SIG/ALLOW_DM/SILENT_LOG (el
    # bitmask SÍ requiere SAVE explícito).
    _a("SECURITY", SEC, "SEC"),
    # SETTINGS: distinto de CONFIG (Role/Hops/CA/BT/DMF/Drops/PPing/SK/BD).
    _q("SETTINGS", SEC, "ST"),
    # §3.11 Telemetría y sensores
    _q("TELEMETRY", SE), _q("ENV", SE), _q("POWER", SE), _q("UTIL", SE), _q("POS", SE),
    _q("INALM", SE), _q("SENSORS", SE), _q("MCUINFO", SE, "MCU"), _q("WIFIOTA", SE, "OTA"),
    # §3.12/§9 Almacenamiento, vault y automatización
    _q("LS", STO), _q("CAT", STO), _m("RM", STO, persistence=Persistence.NONE),
    _m("SAVE", STO, persistence=Persistence.NONE), _m("LOAD", STO, persistence=Persistence.NONE),
    _a("GROUP", STO), _a("SKEY", STO), _a("CRON", STO), _a("MACRO", STO),
    _q("VAULT", STO, "VST"),
    # "VDF" expande a "VAULT DIFF" completo (alias de un comando de dos
    # palabras, no de "VAULT" a secas) — funciona porque el builder junta
    # prefijo + nombre canónico + argumentos, y el nombre canónico YA
    # contiene el espacio.
    _q("VAULT DIFF", STO, "VDF"),
    _a("FREEZE", STO),
    _m("DBFLUSH", STO, persistence=Persistence.NONE),
    _a("BSAVE", STO), _a("BLOAD", STO), _a("BD", STO),
    # §3.13/§11/§12 Alertas
    _a("TA", AL, "TR_ALERT"), _a("META_ALERT", AL, "MA"),
    _m("BELL", AL, persistence=Persistence.NONE), _m("PLAY", AL, persistence=Persistence.NONE),
    _m("STARWARS", AL, persistence=Persistence.NONE),
    # §3.14 PPING
    _a("PPING", PP),
    # §3.15/§5/§14 Críticos
    _m("REBOOT", CR, persistence=Persistence.NONE, busy=20, destructive=True),
    # TX OFF silencia el transmisor: destructivo. TX ON no.
    _m("TX", CR, persistence=Persistence.NONE, destructive_arg_equals=frozenset({"OFF"})),
)  # fmt: skip

# Confirmados ausentes de la build pública (ver docstring del módulo) o
# marcados "NOT IMPLEMENTED" por el propio manual.
EXCLUDED = frozenset({"AIRTAG", "BURNER", "ROLEMASK", "SETMULTIROLE", "ADDURL", "USETCHNAME"})

COMMANDS: dict[str, CommandSpec] = {spec.name: spec for spec in _SPECS}
ALIASES: dict[str, str] = {alias: spec.name for spec in _SPECS for alias in spec.aliases}


def resolve(name: str) -> CommandSpec | None:
    key = name.strip().upper()
    if key in EXCLUDED:
        return None
    return COMMANDS.get(key) or COMMANDS.get(ALIASES.get(key, ""))


def mutates(spec: CommandSpec, args: tuple[str, ...]) -> bool:
    if spec.mutation is Mutation.NEVER:
        return False
    if args and args[0].upper() in READ_VERBS:
        return False
    if spec.mutation is Mutation.WITH_ARGS:
        return bool(args)
    return True


def is_destructive(spec: CommandSpec, args: tuple[str, ...]) -> bool:
    if spec.destructive:
        return True
    if args and args[0].upper() in spec.destructive_verbs:
        return True
    upper_args = {a.upper() for a in args}
    if upper_args & spec.destructive_arg_equals:
        return True
    if spec.destructive_unless_value is not None and args:
        return upper_args.isdisjoint({spec.destructive_unless_value.upper()})
    return False


def requires_save(spec: CommandSpec, args: tuple[str, ...]) -> bool:
    return spec.persistence is Persistence.SAVE and mutates(spec, args)
