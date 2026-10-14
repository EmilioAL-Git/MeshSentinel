# Guía de aceptación — JenTastic público (2.8.1) y correcciones del catálogo

Contexto: estudio `docs/design/nexus-firmware-publico-estudio.md` (§7 con los
resultados en hardware). Esta guía repite en tu entorno lo que se validó el
2026-10-14 con dos T1000 (X1 → T1000, ambos 2.8.101.08c204f).

## 0. Requisitos

- Dos nodos por USB **en la misma línea de firmware**. OJO: 2.8.0 y 2.8.1 **no se
  oyen** en tráfico firmado (commit upstream #11422); con uno en cada lado todo
  sale «sin respuesta».
- Ambos con el canal `Nexus` (o `JenT`).
- Nada más usando esos puertos (pasarela nativa, `meshtastic --info`…).

## 1. Batería automática

```bash
arch -arm64 .venv/bin/python tools/nexus_validate_public.py --self-test   # sin hardware
arch -arm64 .venv/bin/python tools/nexus_validate_public.py --list --phases read,addr,capture,mutate
arch -arm64 .venv/bin/python tools/nexus_validate_public.py               # read + addr
arch -arm64 .venv/bin/python tools/nexus_validate_public.py --phases capture,mutate
```

Esperado en 2.8.101: sin FAIL salvo **A6** (dos dirigidos a 1 s: solo responde uno;
es comportamiento del firmware) y **A7** (2.º nivel de `R`: «Unknown command»,
tampoco se procesa). El informe de `mutate` debe terminar con las 7 fotos de
estado «igual».

## 2. Comprobaciones en la UI (con el stack actualizado)

| Qué | Cómo | Esperado |
|---|---|---|
| `-mac` | Ajustes → JenTastic-Nexus → Operaciones, destino MAC, 4 hex | acepta 4 hex; con 6 da error |
| `INVALID` | Catálogo → INVALID → regla NULL | `/nexus INVALID NULL`; `UNINVALID NULL` lo apaga |
| «Local» | destino «Nodo local de la pasarela» + `UPTIME` | se envía como `-node <nombre corto>` y responde (🔴) |
| Homónimos | `-node` con un nombre corto repetido en Flota | aviso ⚠ en la simulación |
| Rechazo | nodo con `REQ_SIG` ON y la pasarela no autorizada | estado **Rechazada**, no «Confirmado» |
| TRACE | `TRACE !id` desde el Inspector | un único resultado con ida, vuelta y SNR |
| Truncado | `FAVS` en un nodo con muchos favoritos | la lista conocida **no se vacía** (aviso en log) |

## 3. Qué NO está en esta fase

- `USETCHNAME`/`USETCHPSK`/`UDELCH`/`ADDURL`: excluidos (decisión del usuario).
- Endurecer con `REQ_SIG`+`SKEY`: no por ahora (ver estudio §5 y CLAUDE.md).
- `METRICS` con datos y secciones BLUETOOTH/MQTT/SERIAL de `FULLCONFIGDUMP`: el
  firmware no las entrega (NodeDB sin métricas; buffer de paginación de 2 KB).
