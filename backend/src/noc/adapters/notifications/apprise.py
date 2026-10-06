from typing import Any

import httpx

from noc.application.alerting.message import NotificationMessage, test_message

# Tipos de Apprise: info | success | warning | failure
_TYPE_BY_KIND_SEVERITY = {
    ("resolved", None): "success",
    ("test", None): "info",
}


def apprise_type(message: NotificationMessage) -> str:
    if message.kind in ("resolved", "test"):
        return _TYPE_BY_KIND_SEVERITY[(message.kind, None)]
    return {"INFO": "info", "WARNING": "warning", "CRITICAL": "failure"}.get(message.severity, "info")


class AppriseProvider:
    """Cliente de un servidor Apprise API (https://github.com/caronc/apprise-api)
    — da acceso a 100+ servicios (Discord, Slack, Matrix, Email, Pushover…) sin
    dependencias nuevas: MeshSentinel solo hace un POST HTTP.

    configuration: {"url": base del servidor, "key": clave de configuración
    persistente (modo /notify/{key}) y/o "urls": URLs Apprise separadas por
    coma (modo sin estado /notify), "tag": opcional, "token": Bearer opcional}"""

    def __init__(self, configuration: dict[str, Any]) -> None:
        self._configuration = configuration

    def validate(self) -> list[str]:
        errors = []
        if not self._configuration.get("url"):
            errors.append("Falta 'url' del servidor Apprise")
        if not self._configuration.get("key") and not self._configuration.get("urls"):
            errors.append("Falta 'key' (configuración guardada) o 'urls' (URLs Apprise)")
        return errors

    async def send(self, message: NotificationMessage) -> None:
        base = str(self._configuration["url"]).rstrip("/")
        key = self._configuration.get("key")
        endpoint = f"{base}/notify/{key}" if key else f"{base}/notify"
        payload: dict[str, Any] = {
            "title": message.title,
            "body": f"{message.body}\n{message.subject_label}",
            "type": apprise_type(message),
        }
        if not key:
            payload["urls"] = self._configuration["urls"]
        if self._configuration.get("tag"):
            payload["tag"] = self._configuration["tag"]
        headers = {}
        if self._configuration.get("token"):
            headers["Authorization"] = f"Bearer {self._configuration['token']}"
        async with httpx.AsyncClient(timeout=float(self._configuration.get("timeout", 10))) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()

    async def test(self) -> None:
        await self.send(test_message())
