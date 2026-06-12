# ADR 0008 — Canales de notificación extensibles (webhook y ntfy primero)

- Estado: Aceptado (2026-06-12)

## Contexto

El motor de alertas debe notificar por canales que crecerán con el tiempo. Inicio
confirmado: webhooks genéricos y ntfy. Futuro: Telegram y correo electrónico.

## Decisión

- Puerto `NotificationChannel` en `application/ports` con una operación
  `send(notification)`.
- Implementaciones como adaptadores registrados en un registro de canales:
  `webhook` y `ntfy` en la primera iteración del Alert Engine (Fase 5).
- La configuración de canales se almacena en base de datos (no en variables de
  entorno), para gestionarlos desde la UI.

## Consecuencias

- Añadir Telegram/email = un adaptador nuevo + una migración de configuración;
  cero cambios en el motor de alertas.
