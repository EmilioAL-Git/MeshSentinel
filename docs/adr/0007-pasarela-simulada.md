# ADR 0007 — Pasarela simulada desde la Fase 0

- Estado: Aceptado (2026-06-12)

## Contexto

El desarrollo no puede depender de hardware LoRa disponible y conectado. Además,
los escenarios de error (nodos que desaparecen, batería baja, malla particionada)
son difíciles de reproducir con hardware real.

## Decisión

El gateway implementa los transportes detrás de una interfaz común
(`gateway/transports/base.py`). Uno de ellos es **`simulated`**: genera una malla
ficticia configurable (nº de nodos, intervalos de telemetría, movimiento GPS,
pérdida de nodos) y emite eventos por el contrato v1 igual que un transporte real.

Se selecciona con `GATEWAY_TRANSPORT=simulated` y es el transporte por defecto en
desarrollo.

## Consecuencias

- Frontend y backend se desarrollan y testean sin hardware.
- Los tests E2E usan el simulador con escenarios deterministas (seed).
- El simulador debe mantenerse fiel al contrato, no al comportamiento interno de
  la librería `meshtastic`.
