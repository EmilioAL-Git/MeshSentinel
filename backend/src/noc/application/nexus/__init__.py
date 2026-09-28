"""Control de nodos JenTastic-Nexus por comandos de texto (ADR 0027).

Núcleo PURO: sin red, sin BD, sin FastAPI, sin la librería meshtastic. Todo
lo que entra y sale son dataclasses y strings, para poder testear la
construcción de comandos y el parseo de respuestas de forma aislada. El
transporte real (comando `send_text` hacia el gateway) y la persistencia
llegan en iteraciones posteriores a través del puerto `NexusTransport`.

Referencia normativa del firmware: el documento de integración de
JenTastic-Nexus v2.8.005 (resumido en docs/design/nexus-control.md). Regla
del usuario: no se inventan comandos ni parámetros que no estén en él.
"""
