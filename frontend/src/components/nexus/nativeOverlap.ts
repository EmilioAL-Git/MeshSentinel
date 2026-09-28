/**
 * Operaciones nativas (AdminMessage/PKC, ADR 0013) que tienen un
 * equivalente COMPLETO confirmado en JenTastic-Nexus — decisión explícita
 * del usuario: "quitamos las opciones de la administración nativa que se
 * puedan hacer con Nexus". Deliberadamente CORTA: solo entran aquí
 * operaciones donde Nexus cubre el 100% de lo que hace la nativa, nunca
 * una donde Nexus solo toca una parte (p. ej. `config.set`/
 * `module_config.set` cubren decenas de secciones —LoRa, Bluetooth,
 * pantalla, red...— de las que `SETCONFIG` solo alcanza a NI/TEL_D/E/P/
 * POS/SMART/FIXED/GPS/LOC, así que esas se quedan SIEMPRE disponibles).
 *
 * - `owner.set` ↔ Nexus `NAME`/`OWNER` (catalog.py, categoría Stealth).
 * - `position.set_fixed` ↔ Nexus `SETCONFIG FIXED <0|1>` +
 *   `SETCONFIG LOC <lat>,<lon>` (confirmado por captura real, ver
 *   docs/design/nexus-control.md §0.4).
 */
export const NEXUS_SUPERSEDED_OPERATION_TYPES = new Set(["owner.set", "position.set_fixed"]);
