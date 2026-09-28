"""`command.send_text` (ADR 0027): detección automática del canal Nexus/JenT
por nombre, nunca por índice fijo — y su ausencia se registra en logs en vez
de mandar "casi acertar" por el canal principal."""

import asyncio
from dataclasses import dataclass
from typing import Any

from gateway.config import Settings
from gateway.transports.usb import MeshtasticUsbTransport


@dataclass
class FakeChannelSettings:
    name: str


@dataclass
class FakeChannel:
    index: int
    role: int  # 0=DISABLED, 1=PRIMARY, 2=SECONDARY
    settings: FakeChannelSettings


class FakeLocalNode:
    def __init__(self, channels: list[FakeChannel]) -> None:
        self.channels = channels


class FakeIface:
    def __init__(self, channels: list[FakeChannel]) -> None:
        self.localNode = FakeLocalNode(channels)
        self.sent: list[tuple[str, int]] = []

    def sendText(self, text: str, channelIndex: int = 0) -> None:  # noqa: N802 (API de la librería)
        self.sent.append((text, channelIndex))


def make_transport() -> MeshtasticUsbTransport:
    async def emit(event_type: str, payload: dict[str, Any]) -> None:  # noqa: ARG001
        pass

    t = MeshtasticUsbTransport(emit, Settings(_env_file=None, transport="usb"))
    t._loop = asyncio.get_event_loop()
    return t


def channels(*, nexus_name: str | None, nexus_role: int = 2) -> list[FakeChannel]:
    chans = [FakeChannel(0, 1, FakeChannelSettings("Primary"))]
    if nexus_name is not None:
        chans.append(FakeChannel(7, nexus_role, FakeChannelSettings(nexus_name)))
    return chans


async def test_finds_nexus_channel_by_name_case_insensitive():
    t = make_transport()
    t._iface = FakeIface(channels(nexus_name="Nexus"))
    assert t._find_nexus_channel() == 7

    t._iface = FakeIface(channels(nexus_name="JENT"))
    assert t._find_nexus_channel() == 7


async def test_ignores_disabled_channel_with_matching_name():
    t = make_transport()
    t._iface = FakeIface(channels(nexus_name="Nexus", nexus_role=0))
    assert t._find_nexus_channel() is None


async def test_no_nexus_channel_returns_none():
    t = make_transport()
    t._iface = FakeIface(channels(nexus_name=None))
    assert t._find_nexus_channel() is None


async def test_send_text_uses_detected_channel():
    t = make_transport()
    t.status = "connected"
    iface = FakeIface(channels(nexus_name="Nexus"))
    t._iface = iface
    await t._send_text({"text": "/nexus INFO"})
    assert iface.sent == [("/nexus INFO", 7)]


async def test_send_text_rejected_without_nexus_channel():
    t = make_transport()
    t.status = "connected"
    iface = FakeIface(channels(nexus_name=None))
    t._iface = iface
    await t._send_text({"text": "/nexus INFO"})
    assert iface.sent == []  # nunca "casi acertar" por el canal principal


async def test_send_text_rejected_when_not_connected():
    t = make_transport()
    t.status = "connecting"
    iface = FakeIface(channels(nexus_name="Nexus"))
    t._iface = iface
    await t._send_text({"text": "/nexus INFO"})
    assert iface.sent == []


async def test_send_text_rejected_when_empty():
    t = make_transport()
    t.status = "connected"
    iface = FakeIface(channels(nexus_name="Nexus"))
    t._iface = iface
    await t._send_text({"text": ""})
    assert iface.sent == []


async def test_send_command_dispatches_send_text():
    t = make_transport()
    t.status = "connected"
    iface = FakeIface(channels(nexus_name="Nexus"))
    t._iface = iface
    await t.send_command({"command_type": "command.send_text", "payload": {"text": "/nexus INFO"}})
    assert iface.sent == [("/nexus INFO", 7)]


async def test_send_command_unknown_type_is_noop():
    t = make_transport()
    t.status = "connected"
    iface = FakeIface(channels(nexus_name="Nexus"))
    t._iface = iface
    await t.send_command({"command_type": "command.something_else", "payload": {}})
    assert iface.sent == []
