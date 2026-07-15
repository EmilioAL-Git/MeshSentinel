from typing import Any

import httpx

from noc.application.alerting.message import NotificationMessage, test_message


def build_payload(message: NotificationMessage) -> dict[str, Any]:
    return {
        "event": f"alert.{message.kind}",
        "alert": {
            "title": message.title,
            "severity": message.severity,
            "kind": message.kind,
            "subject": message.subject_label,
            "message": message.body,
            "occurred_at": message.occurred_at.isoformat(),
        },
        "source": "meshtastic-noc",
    }


class WebhookProvider:
    """POST JSON genérico. configuration: {"url": str, "headers": {..}?, "timeout": s?}"""

    def __init__(self, configuration: dict[str, Any]) -> None:
        self._configuration = configuration

    def validate(self) -> list[str]:
        errors = []
        if not self._configuration.get("url"):
            errors.append("Falta 'url'")
        return errors

    async def send(self, message: NotificationMessage) -> None:
        url = self._configuration["url"]
        headers = self._configuration.get("headers") or {}
        timeout = float(self._configuration.get("timeout", 10))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=build_payload(message), headers=headers)
            response.raise_for_status()

    async def test(self) -> None:
        await self.send(test_message())
