from typing import Any

import httpx

from noc.domain.alerts.entities import Alert

# Prioridades ntfy: 1 (min) .. 5 (max)
_PRIORITY_BY_SEVERITY = {"INFO": "2", "WARNING": "4", "CRITICAL": "5"}
_TAG_BY_KIND = {"fired": "rotating_light", "reminder": "repeat", "resolved": "white_check_mark", "test": "wrench"}


def build_headers(alert: Alert, kind: str) -> dict[str, str]:
    prefix = {"fired": "ALERTA", "reminder": "RECORDATORIO", "resolved": "RESUELTA", "test": "TEST"}[kind]
    return {
        "Title": f"[{prefix}] {alert.severity}: {alert.rule_name}",
        "Priority": "3" if kind == "resolved" else _PRIORITY_BY_SEVERITY.get(alert.severity, "3"),
        "Tags": _TAG_BY_KIND.get(kind, "bell"),
    }


class NtfyChannel:
    """config: {"url": servidor (default https://ntfy.sh), "topic": str,
    "token": bearer opcional, "timeout": s?}"""

    def __init__(self, config: dict[str, Any]) -> None:
        base = (config.get("url") or "https://ntfy.sh").rstrip("/")
        self._endpoint = f"{base}/{config['topic']}"
        self._token = config.get("token")
        self._timeout = float(config.get("timeout", 10))

    async def send(self, alert: Alert, kind: str) -> None:
        headers = build_headers(alert, kind)
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._endpoint, content=alert.message.encode(), headers=headers)
            response.raise_for_status()
