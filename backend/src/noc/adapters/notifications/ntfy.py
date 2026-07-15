from typing import Any

import httpx

from noc.application.alerting.message import NotificationMessage, test_message

# Prioridades ntfy: 1 (min) .. 5 (max)
_PRIORITY_BY_SEVERITY = {"INFO": "2", "WARNING": "4", "CRITICAL": "5"}
_TAG_BY_KIND = {"fired": "rotating_light", "reminder": "repeat", "resolved": "white_check_mark", "test": "wrench"}


def build_headers(message: NotificationMessage) -> dict[str, str]:
    return {
        "Title": message.title,
        "Priority": "3" if message.kind == "resolved" else _PRIORITY_BY_SEVERITY.get(message.severity, "3"),
        "Tags": _TAG_BY_KIND.get(message.kind, "bell"),
    }


class NtfyProvider:
    """configuration: {"url": servidor (default https://ntfy.sh), "topic": str,
    "token": bearer opcional, "timeout": s?}"""

    def __init__(self, configuration: dict[str, Any]) -> None:
        self._configuration = configuration

    def validate(self) -> list[str]:
        errors = []
        if not self._configuration.get("topic"):
            errors.append("Falta 'topic'")
        return errors

    async def send(self, message: NotificationMessage) -> None:
        base = (self._configuration.get("url") or "https://ntfy.sh").rstrip("/")
        endpoint = f"{base}/{self._configuration['topic']}"
        timeout = float(self._configuration.get("timeout", 10))
        headers = build_headers(message)
        token = self._configuration.get("token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, content=message.body.encode(), headers=headers)
            response.raise_for_status()

    async def test(self) -> None:
        await self.send(test_message())
