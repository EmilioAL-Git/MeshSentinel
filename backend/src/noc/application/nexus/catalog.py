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

**Fuente de verdad desde 2026-10-13: el CÓDIGO FUENTE público**
(`github.com/derpyspike/jentastic`, firmware 2.8.103; el despachador es
`src/modules/NexusCommands.cpp`) y la validación en hardware del 2026-10-14
(`tools/nexus_validate_public.py`, `docs/design/nexus-firmware-publico-estudio.md`).
Donde el PDF 2.8.006 o la doc discrepan del fuente, manda el fuente.

**No existen en la build pública** (el árbol público se genera con
`bin/nexus_strip_tactical_to_public.py`; lo táctico vive en
`handlePrivateCommand`, fuera del repo): REVERT, RELAYSPOOF, FAKENODE, FNH,
FNM, FAKEPOS, FAKERANDPOS, FTEXT, FTEXTM, FTEXTH, INJECT. Se enviarían como
"Unknown command" y además son herramientas de suplantación o de borrado de
identidad: sin caso de uso en un NOC. Siguen excluidos BURNER, ROLEMASK y
SETMULTIROLE (cero coincidencias en el fuente).

**Existen en el fuente pero siguen EXCLUIDOS por decisión pendiente del
usuario**: ADDURL (añade un nodo a la NodeDB desde un enlace), AIRTAG (baliza
OpenHaystack) y las variantes que saltan la protección de canal de confianza
(USETCHNAME, USETCHPSK, UDELCH).

**Sintaxis verificada contra fuente y hardware** (no la del PDF): el firmware
NO tiene `INVALIDS <REGLA> [ON|OFF]`; `INVALIDS`/`INV`/`INVALID` a secas
consultan, `INVALID <R>`/`INV <R>` activan y `UNINVALID <R>`/`UNINV <R>`
desactivan (sin `[ON|OFF]`). `SETROLE` y `SETLORA` EXISTEN pero exigen
argumento: la sonda "sin argumentos" del 2026-09-29 dio "Unknown command"
por construcción (`strncasecmp(cmd, "SETROLE ", 8)`), no porque no existan.
`-mac` compara 4 hex (ver `addressing.py`).

**Alias**: `RL` es alias real de RATELIMIT; `TA` es el nombre canónico;
`DMF` alias de `DM-FORWARD`; PRALLOW/PRBLOCK alias de PRWHITELIST/PRBLACKLIST.
El firmware NO define `CA`, `BT`, `?` ni `IGNORE-DUPERELAY`: se retiraron.

**Versión del firmware**: hay diferencias entre 2.8.005 y 2.8.101 (p. ej.
`LCS`, `FEATURES` y la línea `FAV_XT` de SECURITY no existen en 2.8.005).
El catálogo describe la build pública actual; ante "Unknown command" en un
nodo viejo, comprobar su versión antes de dar el comando por inexistente.
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
    _q("HELP", S), _q("COMPILATION", S, "COMP"),
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
    _q("VERIFYSTATS", ST, "VS"), _q("CRSTATS", ST, "CRS"), _q("RATELIMITSTAT", ST, "RLS"),
    _q("RSSI", ST, "RS"), _q("SHORTRSSI", ST, "SR"), _q("RSSITEL", ST, "RT"),
    _q("LORACHIPSTATS", ST, "LCS"),  # no existe en 2.8.005; sí en 2.8.101
    # §3.3/§7 Escaneo activo
    _q("NETSCAN", SC, busy=60), _q("CLIENTSCAN", SC), _q("NOISE", SC),
    _q("FREQSCAN", SC, busy=15), _a("WATCH", SC), _q("SEARCHKEY", SC),
    _q("TRACE", SC, "TR"),  # traceroute desde el nodo remoto (resultado asíncrono)
    _q("METRICS", SC),  # métricas de OTRO nodo desde la NodeDB; exige argumento
    _q("CHECKSIG", SEC), _q("NODECRC", DB),
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
    # INVALIDS (y `INV`/`INVALID` a secas) CONSULTA; `INVALID <R>` activa y
    # `UNINVALID <R>` desactiva — no hay `[ON|OFF]` (fuente + hardware).
    _q("INVALIDS", FW),
    _a("INVALID", FW, "INV"), _m("UNINVALID", FW, "UNINV"),
    _a("RATELIMIT", FW, "RL", persistence=Persistence.AUTO),
    _m("RDROP", FW, destructive_verbs=frozenset({"CLEAR"})), _m("RUNDROP", FW),
    # IDR: bare = consulta de estado ("Displays current... status").
    _a("IDR", FW, "IGNORE-DUPE-RELAY"), _m("UNIDR", FW),
    # ZH IMPORT sobrescribe la máscara completa del nodo: tan destructivo como CLEAR.
    _a("ZH", FW, destructive_verbs=frozenset({"CLEAR", "IMPORT"})), _a("NIGN", FW),
    # PRWHITELIST/PRBLACKLIST son la forma real (manual §3.3); PRALLOW/PRBLOCK
    # son sus alias, no comandos aparte.
    _a("PRWHITELIST", FW, "PRALLOW"), _a("PRBLACKLIST", FW, "PRBLOCK"),
    _a("FSIG", FW),  # 8 slots, SET <1-8> <patrón> / OFF <1-8>, auto hex/b64/texto
    # §4 Hop-aware routing (antes catalogado como "stealth" sin serlo)
    _a("HOPMASK", SH), _a("CH-HOPMASK", SH, "CHM"), _a("PORT-HOPMASK", SH, "PHM"),
    _a("HOPSCALE", SH, "HSC"),
    # §5 Radio / RF. Sin alias `CA`/`BT`: el firmware no los define.
    _a("TRUSTED", SH), _a("CLIENTALWAYS", SH), _a("BASETEXTS", SH),
    # Identidad permanente: reinician el nodo (persisten solas) y el firmware
    # las bloquea en difusión. El manual no da su tiempo de reinicio; se
    # asume el de REBOOT (20 s) — PENDIENTE de verificar contra un nodo real.
    _m("NAME", SH, persistence=Persistence.AUTO, broadcast_forbidden=True,
       destructive=True, busy=20),
    _m("OWNER", SH, persistence=Persistence.AUTO, broadcast_forbidden=True,
       destructive=True, busy=20),
    # §3.9/§12 Mensajería e inyección de paquetes (testing)
    *(_m(n, INJ, persistence=Persistence.NONE) for n in ("TEXT", "TEXTC", "DM", "DMTEST")),
    _m("SENDMYNODE", INJ, "SMN", "SENDMYINFO", "SMI", persistence=Persistence.NONE),
    _m("SENDNODE", INJ, "SN", persistence=Persistence.NONE),
    _m("SENDPOS", INJ, persistence=Persistence.NONE),
    # Un `R` dentro de otro `R` NO se procesa (fuente + hardware 2026-10-14):
    # solo 1 nivel de redirección útil.
    _m("REDIRECT", INJ, "R", persistence=Persistence.NONE),
    _a("DM-FORWARD", INJ, "DMF", "DMFORWARD"),
    # SENDSTATUS/STATUSPS emiten un NODE_STATUS_APP en el canal 0 (aire).
    _m("SENDSTATUS", INJ, persistence=Persistence.NONE),
    _m("STATUSPS", INJ, persistence=Persistence.NONE),
    # §3.10 Configuración. SETCONFIG confirmado por captura real (2026-09-28):
    # sin argumentos responde con su uso, "JT SETCONFIG: NI|TEL_D|TEL_E|TEL_P|
    # POS|SMART|FIXED|GPS <val> | LOC lat,lon" — un campo por comando.
    # SETROLE <rol> y SETLORA <sf> <bw> <cr> <freq> EXISTEN (fuente +
    # hardware 2026-10-14) pero exigen argumento: bare dan "Unknown command".
    _q("CONFIG", CF), _m("SETCONFIG", CF), _q("ROLE", CF), _m("SETROLE", CF),
    _q("LORA", CF, "LR"), _q("LORA-STATUS", CF, "LRS"), _q("PRESET", CF),
    _m("SETPRESET", CF), _m("SETLORA", CF, busy=5, destructive=True),
    _m("SETPREAMBLE", CF, "SETPRE", busy=5),
    _m("SETPOWER", CF, "SETPWR", "SETTXPOWER"), _q("GETTXPOWER", CF),
    # Destructivo salvo que se deje/restaure el valor por defecto 0x2B (manual §5).
    _m("SETSYNCWORD", CF, "SETSW", busy=5, destructive_unless_value="0x2B"),
    _a("LR2021_SF", CF, "MULTISF", "MSF", hardware_note="Solo hardware LR2021; en SX1262 no tiene "
       "efecto. El SF lateral debe ser MAYOR que el principal."),
    _a("G3", CF, "FRONTEND"),
    _a("PMGT", CF), _a("WIFI", CF), _q("LNA", CF), _m("SETLNA", CF),
    _m("SETREBROADCAST", CF), _a("IGNOREMQTT", CF, "IGNORMQTT"), _a("MQTT", CF),
    _a("TM", CF), _a("FEATURES", CF), _q("MODULES", CF, "MOD"), _q("FULLCONFIGDUMP", CF, "FCD"),
    _m("GOODPRACTICES", CF, "BUENASPRACTICAS", "GP", "BP"), _a("OKTOMQTT", CF, "OKMQTT", "OMQ"),
    _m("ADDCH", CF), _m("SETCHNAME", CF), _m("SETCHPSK", CF), _m("DELCH", CF),
    _q("CHASH", CF, "CH", "CHANNELS", "CHHASHES"), _q("DECODEURL", CF, "DU"),
    _m("SHARE", CF, persistence=Persistence.NONE),
    # §2.3/§10 SECURITY: bits confirmados REQ_SIG/ALLOW_DM/SILENT_LOG (el
    # bitmask SÍ requiere SAVE explícito).
    _a("SECURITY", SEC, "SEC"),
    # SETTINGS: distinto de CONFIG (Role/Hops/CA/BT/DMF/Drops/PPing/SK/BD).
    _q("SETTINGS", SEC, "ST"),
    # §3.11 Telemetría y sensores
    _q("TELEMETRY", SE), _q("ENV", SE), _q("POWER", SE), _q("UTIL", SE), _q("POS", SE),
    _q("INALM", SE), _q("SENSORS", SE), _q("MCUINFO", SE, "MCU"), _q("WIFIOTA", SE, "OTA", "OTAINFO"),
    # §3.12/§9 Almacenamiento, vault y automatización
    _q("LS", STO), _q("CAT", STO), _m("RM", STO, persistence=Persistence.NONE),
    _m("SAVE", STO, persistence=Persistence.NONE), _m("LOAD", STO, persistence=Persistence.NONE),
    _a("GROUP", STO), _a("SKEY", STO), _a("CRON", STO), _a("MACRO", STO, "MC"),
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
    # "0" por si el firmware acepta 1/0 también aquí: nunca dejar sin marcar un TX apagado.
    _m("TX", CR, persistence=Persistence.NONE, destructive_arg_equals=frozenset({"OFF", "0"})),
)  # fmt: skip

# Ausentes de la build pública (fuente) o excluidos por decisión pendiente del
# usuario (ver docstring del módulo). `resolve()` devuelve None para todos.
PRIVATE_ONLY = frozenset({
    "REVERT", "RELAYSPOOF", "FAKENODE", "FNH", "FNM", "FAKEPOS", "FAKERANDPOS",
    "FTEXT", "FTEXTM", "FTEXTH", "INJECT", "FP", "FRP",
})
EXCLUDED = frozenset({
    "AIRTAG", "BURNER", "ROLEMASK", "SETMULTIROLE", "ADDURL",
    "USETCHNAME", "USETCHPSK", "UDELCH",
}) | PRIVATE_ONLY

COMMANDS: dict[str, CommandSpec] = {spec.name: spec for spec in _SPECS}
ALIASES: dict[str, str] = {alias: spec.name for spec in _SPECS for alias in spec.aliases}

# Descripción de una línea por comando, para el explorador de catálogo de la
# UI (pedido explícito del usuario: icono ⓘ con "qué hace"). Traducidas del
# manual v2.8.006 ("Manual Nuevo JT.pdf", "verified directly against the C++
# source code") — la misma fuente PRINCIPAL ya usada para el resto del
# catálogo (ver docstring del módulo). Separado de _SPECS a propósito: es
# texto largo sin relación con la lógica de construcción/validación de
# comandos, y así el diff de esta tabla no toca la tupla compacta de arriba.
# Cualquier comando sin entrada aquí simplemente no muestra ⓘ en la UI — no
# se inventa texto para rellenar huecos.
DESCRIPTIONS: dict[str, str] = {
    "LORACHIPSTATS": "Porcentaje de tiempo del chip LoRa en cada estado (TX/RX/STBY…), muestreado a 1 Hz. No existe en 2.8.005.",
    "TRACE": "Traceroute real desde ESTE nodo hacia otro; el resultado llega como segundo mensaje (ida, vuelta y SNR).",
    "METRICS": "Últimas métricas de dispositivo de OTRO nodo (batería, uso de canal) desde la NodeDB. Exige nodo.",
    "CHECKSIG": "Estado de firma del propio comando: ✅ upstream verificado y si el firmante es de confianza.",
    "NODECRC": "Calcula el node_num 2.8 (crc32 de la clave pública base64). Útil para validar identidades.",
    "SENDSTATUS": "Envía un texto libre (máx. 79) como mensaje de estado de nodo (NODE_STATUS_APP) por el canal 0.",
    "STATUSPS": "Envía como estado un resumen top-N de paquetes por puerto (por defecto 5).",
    "SENDMYNODE": "Emite AHORA el NodeInfo propio del nodo (opciones C <canal>, H <hl> <hs>, M).",
    # Ayuda y build
    "HELP": "Sistema de ayuda paginado por categorías.",
    "COMPILATION": "Placa de destino, fecha de build y flags de compilación activos.",
    # Sistema
    "INFO": "Resumen de identidad: id, nombre, versión de firmware, rol y MAC real.",
    "SYS": "Salud del núcleo: temperatura del chip, razón del último reinicio y memoria.",
    "HW": "Hardware del nodo: placa, MCU, radio y tipo de reloj.",
    "ACC": "Estado del acelerador criptográfico por hardware (AES/SHA/ECC).",
    "HEAP": "Detalle de memoria RAM: usado, libre, mayor bloque contiguo y fragmentación.",
    "PSRAM": "Estado de la PSRAM externa (igual que HEAP pero memoria externa).",
    "RAM": "Snapshot compacto de memoria y stack del proceso principal.",
    "UPTIME": "Tiempo encendido desde el último arranque.",
    "VERSION": "Versión del firmware.",
    "TIME": "Hora del reloj interno (RTC), calidad y fuente de sincronización.",
    "SETTIME": "Fija la hora manualmente desde un timestamp Unix.",
    "FS": "Espacio del sistema de ficheros: usado, total y libre.",
    "PHONE": "Estado de conexión con el móvil/app (Bluetooth, Serial, WiFi).",
    "GPIO": "Lee, escribe o vigila pines GPIO del chip desde la malla.",
    # Estadísticas / SIGINT
    "STATS": "Estadísticas de radio globales: TX/RX, corruptos, duplicados, ruido.",
    "SIGSTATS": "Estadísticas de descifrado del tráfico oído y suelo de ruido real.",
    "RSSILOG": "Últimos paquetes oídos con su RSSI, SNR, saltos y antigüedad.",
    "HOPSTATS": "Histograma de paquetes recibidos según los saltos que dieron.",
    "HOPMATRIX": "Matriz cruzada de saltos de inicio vs saltos usados.",
    "PACKETSTATS": "Desglose del tráfico por tipo de paquete, con % de paquetes y de bytes.",
    "CHANNELSTATS": "Tráfico desglosado por canal, con % de paquetes y de bytes.",
    "SORTEDCHANNELSTATS": "Igual que CHANNELSTATS pero ordenado de mayor a menor tráfico.",
    "SORTEDPACKETSTATS": "Igual que PACKETSTATS pero ordenado de mayor a menor tráfico.",
    "TRANSSTATS": "Tráfico desglosado por medio de transporte (LoRa, MQTT, UDP...).",
    "FIREWALLSTATS": "Cuántos paquetes ha procesado y bloqueado el firewall, por categoría.",
    "FIREWALL": "Vista agregada de toda la configuración estática del firewall.",
    "RELAYS": "Qué nodos están repitiendo tráfico (directos/repetidos/total).",
    "SORTEDRELAYSTATS": "Igual que RELAYS pero ordenado de mayor a menor tráfico.",
    "CLRSTATS": "Borra todas las estadísticas tácticas acumuladas.",
    "MQTTSTATS": "Estadísticas de la bandera OK_TO_MQTT en los paquetes.",
    "VERIFYSTATS": "Estadísticas de verificación de firmas (admin y canal).",
    "CRSTATS": "Distribución de Coding Rate de los paquetes recibidos.",
    "RATELIMITSTAT": "Contadores de aciertos y descartes de los limitadores de tasa.",
    "RSSI": "Métricas de señal (RSSI, SNR, error de frecuencia) del último paquete recibido.",
    "SHORTRSSI": "Versión mínima de 2 líneas del reporte de señal del último paquete.",
    "RSSITEL": "Reporte compacto combinado de señal + telemetría del último paquete.",
    # Escaneo activo
    "NETSCAN": "Mapea tus vecinos directos durante 60 segundos (traceroute de 0 saltos).",
    "CLIENTSCAN": "Mide cómo se propaga uno de tus propios mensajes por la red.",
    "NOISE": "Foto de alta resolución del suelo de ruido (100 muestras rápidas).",
    "FREQSCAN": "Mide el ruido en otra frecuencia temporalmente (el nodo queda sordo unos segundos).",
    "WATCH": "Vigilancia estadística continua de hasta 8 nodos objetivo (RF, saltos, relays, timing).",
    "SEARCHKEY": "Busca nodos en la base de datos que usen una clave pública concreta.",
    "SEARCHRELAY": "Busca nodos cuyo id de relay coincide con un sufijo hex dado.",
    # Base de datos de nodos
    "NODES": "Lista compacta de nodos: id, nombre, saltos, SNR y estado de clave.",
    "NODES28": "Lista los nodos detectados como firmware 2.8.x (por clave pública o firma vista).",
    "FNODE": "Detalle completo de un nodo (identidad, seguridad, posición, métricas, SIGINT).",
    "NODEDB": "Ficha individual de un nodo concreto de la base de datos.",
    "DBINFO": "Resumen de la base de datos: total de nodos, online, directos, favoritos.",
    "INFRA": "Lista solo los nodos de infraestructura (routers, repetidores).",
    "NEIGHBORS": "Nodos a 0 saltos (vecinos directos) con su SNR.",
    "FAVS": "Lista todos los nodos marcados como favoritos.",
    "IGNORED": "Lista todos los nodos ignorados.",
    "ADMINS": "Lista las claves públicas de administrador autorizadas.",
    "ALIAS": "Asocia un nombre corto personalizado (hasta 4 caracteres) a un id de nodo.",
    "FAV": "Marca un nodo como favorito (estricto: falla si el nodo no existe aún).",
    "UNFAV": "Quita la marca de favorito a un nodo.",
    "IGNORE": "Ignora un nodo (solo en memoria, se pierde al reiniciar).",
    "UNIGNORE": "Deja de ignorar un nodo.",
    "DELNODE": "Borra un nodo por completo de la base de datos.",
    "FFAV": "Marca favorito de forma forzada: crea el nodo si aún no existe.",
    "FIGNORE": "Ignora de forma forzada: crea el nodo si aún no existe.",
    "FUNFAV": "Quita el favorito de forma forzada (acepta nodos aún no vistos).",
    "FUNIGNORE": "Deja de ignorar de forma forzada (acepta nodos aún no vistos).",
    "FIXMYINFO": "Corrige tu propia entrada en la base de datos si se ha desincronizado.",
    # Firewall
    "DROP": "Activa un filtro de bloqueo de entrada para un tipo de paquete.",
    "UNDROP": "Desactiva un filtro de bloqueo de entrada.",
    "DROPS": "Lista los filtros de entrada activos ahora mismo.",
    "HEXDROPS": "Muestra todos los filtros de entrada como una máscara hexadecimal.",
    "SETHEX": "Fija todos los filtros de entrada de golpe desde una máscara hexadecimal.",
    "OUTDROP": "Activa un filtro de bloqueo de salida (lo que tú emites).",
    "UNOUTDROP": "Desactiva un filtro de bloqueo de salida.",
    "OUTDROPS": "Lista los filtros de salida activos ahora mismo.",
    "HEXOUTDROPS": "Muestra todos los filtros de salida como una máscara hexadecimal.",
    "SETHEXOUT": "Fija todos los filtros de salida de golpe desde una máscara hexadecimal.",
    "INVALIDS": "Consulta el estado y los contadores de las 5 reglas de validez (NULL, SPAIN, GERMANY, HW, ID).",
    "INVALID": "Activa una regla de validez (NULL, SPAIN, GERMANY, HW_UNSET, ID_MISMATCH). Sin argumento, consulta.",
    "UNINVALID": "Desactiva una regla de validez (sin [ON|OFF]: este verbo es el que la apaga).",
    "RATELIMIT": "Limita la tasa de paquetes por hora para un tipo concreto (requiere activar el DROP RL_* correspondiente).",
    "RDROP": "Bloquea paquetes repetidos por un relay concreto.",
    "RUNDROP": "Quita un relay del bloqueo de RDROP.",
    "IDR": "Ignora duplicados repetidos por un relay específico dentro de una ventana de tiempo.",
    "UNIDR": "Desactiva la supresión de duplicados por relay (IDR).",
    "ZH": "Sistema Zero-Hop: marca nodos como routers de confianza a \"0 saltos\".",
    "NIGN": "Lista de ignorados persistente propia de Nexus (hasta 64 nodos, sobrevive reinicios).",
    "PRWHITELIST": "Whitelist de canales privados/PSK desconocidos que se permiten.",
    "PRBLACKLIST": "Blacklist de canales privados/PSK desconocidos que se bloquean.",
    "FSIG": "Firewall de firmas: bloquea paquetes cuyo payload contiene una secuencia de bytes configurada (8 slots).",
    # Hop-aware routing
    "HOPMASK": "Fuerza saltos de inicio y límite fijos en los paquetes que retransmites.",
    "CH-HOPMASK": "Igual que HOPMASK pero solo para un canal concreto.",
    "PORT-HOPMASK": "Igual que HOPMASK pero solo para un tipo de paquete (puerto) concreto.",
    "HOPSCALE": "Factor de escalado dinámico de saltos.",
    # Stealth / RF
    "TRUSTED": "Gestiona los 2 slots dinámicos de canales de confianza adicionales (bypassean el firewall).",
    "CLIENTALWAYS": "Desactiva la cancelación de duplicados al repetir (úsalo solo si un nodo debe repetir sin ser router).",
    "BASETEXTS": "Como CLIENTALWAYS pero solo para mensajes de texto (útil en nodos base en tejado).",
    "NAME": "Cambia el nombre largo del nodo (provoca reinicio y nuevo NodeNum). Bloqueado en difusión.",
    "OWNER": "Cambia nombre largo y corto a la vez (provoca reinicio). Bloqueado en difusión.",
    # Inyección de paquetes (testing)
    "TEXT": "Envía un mensaje de texto al canal 0.",
    "TEXTC": "Envía un mensaje de texto a un canal concreto.",
    "DM": "Envía un mensaje directo cifrado a un nodo.",
    "DMTEST": "Manda un \"Hello World\" de prueba de vuelta a quien mandó el comando.",
    "SENDNODE": "Difunde de inmediato el NodeInfo del propio nodo.",
    "SENDPOS": "Difunde de inmediato la posición GPS del propio nodo.",
    "REDIRECT": "Meta-comando: ejecuta otro comando pero redirige su respuesta a un canal o nodo distinto.",
    "DM-FORWARD": "Reenvía al canal táctico los DMs cifrados que recibes, para auditarlos sin abrirlos.",
    # Configuración del nodo
    "CONFIG": "Resumen de la configuración activa (rol, intervalos de difusión, posición, GPS...).",
    "SETCONFIG": "Cambia un parámetro simple de configuración (NodeInfo/telemetría/posición/GPS).",
    "ROLE": "Consulta el rol real configurado del dispositivo.",
    "SETROLE": "Cambia el rol real del dispositivo.",
    "LORA": "Resumen compacto de la configuración LoRa (SF, BW, CR, frecuencia, potencia).",
    "LORA-STATUS": "Estado detallado en vivo del driver de radio (frecuencia real, preámbulo, syncword...).",
    "PRESET": "Carga un preset LoRa oficial o táctico.",
    "SETPRESET": "Igual que PRESET: cambia el preset LoRa.",
    "SETLORA": "Configura manualmente SF, BW, CR y frecuencia de la radio.",
    "SETPREAMBLE": "Ajusta la longitud del preámbulo LoRa.",
    "SETPOWER": "Fija la potencia de transmisión en dBm.",
    "GETTXPOWER": "Consulta la potencia de transmisión activa.",
    "SETSYNCWORD": "Cambia el sync word de la radio LoRa (un valor distinto al de Meshtastic te saca de la malla estándar).",
    "LR2021_SF": "Configura los detectores de Spreading Factor laterales del chip LR2021 (recepción multi-SF).",
    "G3": "Control del front-end de radio (LNA/PA) de estaciones con módulo G3.",
    "PMGT": "Diagnóstico de gestión de energía (ahorro, sleeps...).",
    "WIFI": "Configuración y estado de la interfaz WiFi.",
    "LNA": "Estado del amplificador de bajo ruido (LNA).",
    "SETLNA": "Activa o desactiva el amplificador de bajo ruido (LNA).",
    "SETREBROADCAST": "Cambia el modo de retransmisión del nodo (ALL, LOCAL, KNOWN, NONE, CORE...).",
    "IGNOREMQTT": "Ignora los paquetes que llegan vía MQTT.",
    "MQTT": "Estado de conexión MQTT, o cambia la política de privacidad de subida.",
    "TM": "Estadísticas y configuración del módulo de gestión de tráfico de Meshtastic (deduplicación, caché NodeInfo...).",
    "FEATURES": "Activa/consulta funciones adicionales de reenvío al móvil (paquetes opacos, DMs PKI ajenos).",
    "MODULES": "Lista los módulos de firmware compilados y activos.",
    "FULLCONFIGDUMP": "Volcado completo y paginado de toda la configuración del dispositivo.",
    "GOODPRACTICES": "Aplica las buenas prácticas de air-time recomendadas por la comunidad (intervalos de NodeInfo/posición, SmartPos...).",
    "OKTOMQTT": "Activa/desactiva si tus mensajes de texto salientes permiten subir a MQTT.",
    "ADDCH": "Añade un nuevo canal en el primer slot disponible.",
    "SETCHNAME": "Renombra un canal existente.",
    "SETCHPSK": "Cambia la clave de cifrado (PSK) de un canal.",
    "DELCH": "Borra un canal (el canal 0 no se puede borrar).",
    "CHASH": "Lista los canales configurados con su índice, rol y hash.",
    "DECODEURL": "Decodifica una URL de canal compartido de Meshtastic sin aplicarla.",
    "SHARE": "Exporta un nodo de la base de datos como contacto compartido (para importarlo en otro nodo).",
    "SECURITY": "Estado y ajustes de seguridad: exigir firma, permitir DM, registro silencioso, protección anti-replay.",
    "SETTINGS": "Resumen táctico de una sola pantalla: rol, máscara de saltos, firewall, ping público, claves secundarias.",
    # Telemetría y sensores
    "TELEMETRY": "Reporte completo de telemetría: batería, energía y ambiente.",
    "ENV": "Solo el sensor ambiental (temperatura, humedad, presión, luz, UV).",
    "POWER": "Solo energía (voltajes y corrientes por canal).",
    "UTIL": "Utilización del canal y del transmisor (air-time).",
    "POS": "Posición GPS actual y estado del fix.",
    "INALM": "Umbrales y alertas del sensor de corriente INA (solo firmware 2.7.23).",
    "SENSORS": "Lista los sensores I2C detectados en el bus con sus lecturas en vivo.",
    "MCUINFO": "Modelo de chip, núcleos, frecuencia de CPU, memoria y MAC.",
    "WIFIOTA": "Metadatos de la actualización OTA por WiFi (versión, SDK, fecha de build).",
    # Almacenamiento, vault y automatización
    "LS": "Lista los ficheros almacenados localmente.",
    "CAT": "Descarga el contenido de un fichero en Base64 (máx. 700 bytes).",
    "RM": "Borra un fichero del sistema de ficheros.",
    "SAVE": "Guarda la configuración actual de Nexus en flash.",
    "LOAD": "Recarga la configuración de Nexus desde flash, descartando cambios en memoria.",
    "GROUP": "Gestiona grupos de nodos para poder dirigirte a ellos con /nexus-group.",
    "SKEY": "Gestiona hasta 2 claves de administrador secundarias dinámicas.",
    "CRON": "Tareas programadas: ejecuta un comando periódicamente, a una hora fija o una sola vez.",
    "MACRO": "Guarda y ejecuta secuencias de comandos bajo un nombre corto (hasta 4 slots).",
    "VAULT": "Inspecciona el contenido del vault guardado en flash, sin aplicarlo a memoria.",
    "VAULT DIFF": "Compara la configuración en memoria contra la guardada en el vault, sin modificar nada.",
    "FREEZE": "Congela las escrituras a flash (protege el desgaste de la memoria NAND).",
    "DBFLUSH": "Fuerza un volcado inmediato de la base de nodos a disco, saltándose el freeze.",
    "BSAVE": "Copia de seguridad completa de la configuración de Meshtastic en flash.",
    "BLOAD": "Restaura la última copia de seguridad y reinicia el nodo.",
    "BD": "Techo del retardo aleatorio (jitter) aplicado a respuestas por difusión y paginación.",
    # Alertas
    "TA": "Te avisa cuando otro nodo te hace un traceroute.",
    "META_ALERT": "Te avisa cuando otro nodo pide tus metadatos.",
    "BELL": "Hace sonar el zumbador/buzzer una vez.",
    "PLAY": "Reproduce una melodía RTTTL en el zumbador.",
    "STARWARS": "Reproduce la Marcha Imperial en el zumbador.",
    # PPING
    "PPING": "Sistema de respuesta automática a /ping (estado y configuración).",
    # Críticos
    "REBOOT": "Reinicia el dispositivo (con 20 segundos de margen).",
    "TX": "Activa o desactiva físicamente el transmisor de radio (OFF = solo escucha).",
}


def describe(name: str) -> str:
    """Descripción de una línea para `name` (ya canónico), o cadena vacía si
    no hay entrada — nunca se inventa texto para un hueco."""
    return DESCRIPTIONS.get(name, "")


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
