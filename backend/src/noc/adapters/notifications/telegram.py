from typing import Any

import httpx

from noc.application.alerting.message import NotificationMessage, test_message

_EMOJI_BY_SEVERITY = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨"}


def build_text(message: NotificationMessage) -> str:
    emoji = _EMOJI_BY_SEVERITY.get(message.severity, "ℹ️")
    return f"{emoji} *{message.title}*\n{message.body}\n_{message.subject_label}_"


class TelegramProvider:
    """Bot API (`POST https://api.telegram.org/bot{token}/sendMessage`).
    configuration: {"bot_token": str, "chat_id": str}"""

    def __init__(self, configuration: dict[str, Any]) -> None:
        self._configuration = configuration

    def validate(self) -> list[str]:
        errors = []
        if not self._configuration.get("bot_token"):
            errors.append("Falta 'bot_token'")
        if not self._configuration.get("chat_id"):
            errors.append("Falta 'chat_id'")
        return errors

    async def send(self, message: NotificationMessage) -> None:
        token = self._configuration["bot_token"]
        chat_id = self._configuration["chat_id"]
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": build_text(message), "parse_mode": "Markdown"}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()

    async def test(self) -> None:
        await self.send(test_message())
