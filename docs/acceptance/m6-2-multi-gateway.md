# Guía de aceptación — M6.2: Multi-Gateway funcional

> **Histórico**: "pestaña Nodos" corresponde a la tabla sustituida por
> **Flota**; "Operaciones → nueva operación" y "Crear batch" corresponden a
> vistas ya fusionadas en **Trabajos** (ver `docs/glossary.md`). El
> mecanismo de enrutado/reparto/estadísticas validado no cambió.

Objetivo: comprobar que el sistema trabaja de verdad con varias pasarelas a la
vez (observación, enrutado, reparto de lotes, estadísticas) y que con UNA sola
pasarela nada cambia. Referencias: ADR 0022, `docs/design/m6-multi-gateway.md`.

## 0. Preparación: dos pasarelas simuladas con nodos compartidos

Opción A — Docker (recomendada): en `docker-compose.yml` hay un servicio
`gateway-2` comentado. En `.env`:

```
GATEWAY_SIM_SHARED_SEED=7        # ≠0: activa nodos compartidos en gw-01
```

Descomentar `gateway-2` (ya trae `GATEWAY_SIM_SEED: 1042` y el mismo
`GATEWAY_SIM_SHARED_SEED`) y levantar:

```bash
docker compose up --build -d
```

Opción B — proceso nativo adicional (sin tocar compose):

```bash
GATEWAY_ID=gw-02 GATEWAY_TRANSPORT=simulated \
GATEWAY_SIM_SEED=1042 GATEWAY_SIM_SHARED_SEED=7 \
GATEWAY_REDIS_URL=redis://localhost:6379/0 \
.venv/bin/python -m gateway.main
```

Resultado esperado: cada pasarela emite sus nodos exclusivos (SIMxx, semillas
distintas ⇒ ids distintos) más 4 nodos compartidos (SHRxx) con los MISMOS
node_id en ambas.

También puede configurarse todo desde la app: pestaña Gateways → «+ Añadir
gateway» → elegir el candidato (con ≥2 sin configurar aparece un selector) →
transporte «Simulado» → semilla sugerida + semilla compartida → Probar →
Guardar.

## 1. Observación N:M

- [ ] Pestaña Nodos: los SHRxx muestran su pasarela primaria y un badge
      «🛰 2»; los SIMxx no llevan badge.
- [ ] Detalle de un SHRxx: tabla «Observaciones por pasarela» con las dos
      filas (SNR/RSSI/saltos/última escucha), la primaria marcada con ◆ y los
      enlaces sin escucha reciente atenuados.
- [ ] `GET /api/v1/nodes` incluye `gateway_links` con `active`/`primary`.
- [ ] Mapa: un ÚNICO marcador por SHRxx con badge numérico «2»; el popup
      lista ambas pasarelas con su señal.

## 2. Dashboard y estadísticas

- [ ] Con ≥2 pasarelas aparece el panel «Cobertura Multi-Gateway»: nodos
      observados, compartidos y % de redundancia, y por pasarela: visibles /
      exclusivos / compartidos / primaria de / última actividad.
- [ ] `GET /api/v1/gateways/stats` devuelve lo mismo por API.
- [ ] Con UNA sola pasarela el panel NO aparece (Dashboard idéntico a antes).
- [ ] Pestaña Gateways: cada tarjeta muestra visibles/exclusivos/compartidos/
      última actividad.

## 3. Enrutado de operaciones (fijado al encolar)

- [ ] Operaciones → nueva operación `metadata.get` sobre un SHRxx: la columna
      «Pasarela» muestra la elegida (la de mejor enlace activo; comparar con
      el detalle del nodo).
- [ ] Parar la pasarela elegida (docker stop / matar proceso), esperar ~2 min
      (heartbeat stale) y encolar OTRA operación sobre el mismo SHRxx: debe
      salir por la otra pasarela. Las operaciones antiguas NO cambian de
      pasarela (sin failover).
- [ ] Reintento manual de una operación fallida con la pasarela original
      caída: el retry re-evalúa y la reasigna a la pasarela viva.

## 4. Reparto de lotes

- [ ] Nodos → seleccionar nodos exclusivos de ambas pasarelas + compartidos →
      Crear batch (`metadata.get`) → CONFIRMAR.
- [ ] Monitor del batch: línea «Reparto por pasarela: gw-01: N ops · gw-02: M
      ops» y columna «Pasarela» por operación; cada nodo exclusivo sale por la
      suya.
- [ ] Ambas pasarelas despachan en paralelo (1 en vuelo por pasarela; el
      presupuesto global de ops/min sigue siendo compartido — M6.5 pendiente).

## 5. Consola de actividad

- [ ] Cada línea con origen de pasarela lleva su insignia (gw-01/gw-02).
- [ ] El filtro «— todas las pasarelas —» permite aislar una.

## 6. Regresión mono-pasarela

- [ ] Parar gw-02 y dejar solo gw-01 (o entorno previo sin tocar `.env`):
      Nodos/Mapa/Dashboard/Operaciones idénticos a antes de M6.2 (sin badges,
      sin panel Multi-Gateway); encolar operaciones y batches funciona igual,
      incluso con la pasarela momentáneamente caída (fallback a la primaria
      cacheada).
- [ ] `pytest backend/tests gateway/tests` en verde (226 tests).
