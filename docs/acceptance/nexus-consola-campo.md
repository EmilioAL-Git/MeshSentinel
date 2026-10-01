# Consola Nexus — prueba de campo

Objetivo: confirmar con hardware real los formatos de respuesta que el
código SOLO acepta por patrón tolerante (`IGNORE`, `UNIGNORE`, `FIGNORE`,
`FUNIGNORE`, `FFAV`, `FUNFAV`) y validar la consola end-to-end.

Requisitos: modo Nexus ON, 2+ nodos JT marcados en el canal Nexus, una
pasarela con canal «Nexus»/«JenT», backend Docker reconstruido (migración
0029). Usar un nodo SUJETO que no importe (p. ej. uno ajeno a la malla).

## 1. Capturar el formato real (una vez, sin la consola)
`tools/nexus_capture.py` con el gateway nativo parado:
`--commands "IGNORE !<sujeto>" "IGNORED" "UNIGNORE !<sujeto>" "FIGNORE !<sujeto-nuevo>" "FUNIGNORE !<sujeto-nuevo>"`
Anotar el texto EXACTO de cada respuesta (con/sin `JT:`, con/sin marcador).
Si difiere de «ignor»/«Updated node», ajustar `interpret.py` y añadir parser.

## 2. Consola, un nodo (-node)
- [ ] `IGNORE !sujeto` → burbuja propia + respuesta con «✓ … ignorado correctamente».
- [ ] Inspector del nodo → Favoritos/Ignorados: aparece el sujeto (≤5 s).
- [ ] `IGNORED` (lectura) → la lista coincide con la del paso anterior.
- [ ] `UNIGNORE !sujeto` → desaparece de la lista; frase «quitado de ignorados».

## 3. Consola, difusión
- [ ] `IGNORE !sujeto` en difusión → una respuesta interpretada por nodo;
  resumen «N respuestas · N correctas» bajo la burbuja.
- [ ] Cada nodo que contestó tiene el sujeto en su Inspector; los que no, no.
- [ ] Deshacer con `UNIGNORE` en difusión: las listas se vacían igual.

## 4. Forzados
- [ ] `FIGNORE !nodo-nunca-visto` → ✓ y aparece en la lista conocida.
- [ ] `FUNIGNORE` del mismo → desaparece. Igual con `FFAV`/`FUNFAV`.
- [ ] Botón «Forzar» del Inspector precarga FIGNORE.

## 5. Casos de error
- [ ] Id mal escrito (`IGNORE !zzzz`) → error del nodo o respuesta sin
  interpretar (crudo); NO debe tocar ninguna lista.
- [ ] Comando que el firmware no tenga → «El nodo no reconoce el comando».
- [ ] Anotar si el firmware responde distinto en nodos 2.7 vs 2.8.

## Resultado de la prueba de campo (2026-10-01, X1 → T1000, fw 2.8.005)
Hecha con `tools/nexus_capture.py`, sender X1 (`-node 📟`), siempre canal 7.
- `IGNORE`/`UNIGNORE !id` → `JT: Updated node !id (SN)`; `IGNORED` lo refleja
  al instante. Id desconocido para el destino → `JT: Node '!id' not found`.
  Parsers registrados.
- `FIGNORE !id` (nodo conocido) → `Updated node …` pero `IGNORED` sigue VACÍO,
  también en un segundo intento (no es un toggle): confirma sin aplicar.
  Id desconocido → `Node '…' not found`. NO modifica listas conocidas.
- `FUNIGNORE !id` → `JT: Forced node !id (SN)`; con id desconocido CREA un
  nodo `UNK` en la NodeDB del destino. `DELNODE !id` lo borró (sin respuesta).
- `FFAV`/`FUNFAV` NO probados: tratados como `FIGNORE` por prudencia.
- Estado final: T1000 con ignorados vacío (como al empezar); `!0badc0de`
  borrado. Pendiente de campo: bloques 3 (difusión) y la consola en la UI.
- `NIGN` (ignorados persistentes, vault, hasta 64) — probado el mismo día:
  `NIGN ADD !id` → `JT: !id ADDED to ignores`; `NIGN REM !id` → `JT: !id
  REMOVED`; `NIGN LIST` → `JT JT Ignores:\n[0] !id (SN)` o `List empty.`.
  Lista conocida PROPIA (`flag_type=nign`), independiente de IGNORE (RAM).
  Estado final del T1000: lista NIGN vacía. (`NING` era una errata:
  «Unknown command».)

### Segunda tanda de campo (2026-10-01)
- **Difusión (bloque 3) OK**: `/nexus IGNORE !e7ef4fb4` por difusión → respondieron
  los DOS nodos: T1000 `🟢 JT: Updated node !e7ef4fb4 (CALP)` y X1 `🔴 JT: Node
  '!e7ef4fb4' not found` (no lo conocía). `UNIGNORE` por difusión lo deshizo.
  Es justo el caso «cada nodo responde por separado» de la consola.
- `NIGN`: id desconocido se acepta (aparece como `(???)` en LIST); repetir
  ADD → `JT: !id already ignored`; REM de un id ausente → `JT: !id not in
  list`. Parser/intérprete lo recogen (la lista conocida queda coherente).
- **Rarezas del firmware** (para el fabricante, no de MeshSentinel):
  `FUNFAV !e7ef4fb4` respondió `Forced node !07ef4fb4 (UNK)` — id ALTERADO
  (e7→07) — creó un nodo basura y NO quitó el favorito (FAVS intacto).
  `FFAV` sobre un favorito existente: `Forced node …` sin cambios.
  `FUNIGNORE`/`FIGNORE`: ver arriba. Conclusión: las variantes F* no son
  fiables en 2.8.005.
- Limpieza hecha: `NIGN REM !0badc0de`, `DELNODE !07ef4fb4` (y `!0badc0de`);
  T1000 final: IGNORED vacío, NIGN vacío, favoritos intactos.
