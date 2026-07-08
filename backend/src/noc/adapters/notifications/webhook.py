from datetime import datetime
from typing import Any

import httpx

from noc.domain.alerts.entities import Alert


def build_payload(alert: Alert, kind: str) -> dict[str, Any]:
    def iso(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    return {
        "event": f"alert.{kind}",
        "alert": {
            "id": alert.id,
            "rule": alert.rule_name,
            "severity": alert.severity,
            "status": alert.status,
            "subject_type": alert.subject_type,
            "subject_id": alert.subject_id,
            "message": alert.message,
            "correlation_key": alert.correlation_key,
            "fired_at": iso(alert.fired_at),
            "resolved_at": iso(alert.resolved_at),
        },
        "source": "meshtastic-noc",
    }


class WebhookChannel:
    """POST JSON genérico. config: {"url": str, "headers": {..}?, "timeout": s?}"""

    def __init__(self, config: dict[str, Any]) -> None:
        self._url = config["url"]
        self._headers = config.get("headers") or {}
        self._timeout = float(config.get("timeout", 10))

    async def send(self, alert: Alert, kind: str) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._url, json=build_payload(alert, kind), headers=self._headers)
            response.raise_for_status()
