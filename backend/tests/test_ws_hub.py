import asyncio
import time

from noc.adapters.api import ws as ws_module
from noc.adapters.api.ws import ConnectionHub


class FakeWS:
    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.delay, self.fail, self.sent, self.closed = delay, fail, [], False

    async def send_text(self, data: str) -> None:
        if self.fail:
            raise RuntimeError("broken pipe")
        await asyncio.sleep(self.delay)
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True


async def test_hung_client_is_dropped_without_blocking_others(monkeypatch):
    monkeypatch.setattr(ws_module, "SEND_TIMEOUT_SECONDS", 0.2)
    hub = ConnectionHub()
    good, hung, broken = FakeWS(), FakeWS(delay=30), FakeWS(fail=True)
    for c in (good, hung, broken):
        await hub.register(c)  # type: ignore[arg-type]

    t0 = time.monotonic()
    await hub.broadcast({"event_type": "x"})
    assert time.monotonic() - t0 < 2  # no espera los 30 s del colgado

    assert len(good.sent) == 1
    assert hub.client_count == 1  # los dos malos fueron expulsados
    assert hub.dropped_clients == 2
    assert hung.closed and broken.closed


async def test_ws_requires_session_only_when_enabled_and_protected(monkeypatch):
    """Con ws_require_auth=1 y modo protegido, sin sesión se cierra con 4401
    ANTES de aceptar; con el ajuste a 0 o en modo abierto, se acepta."""
    from types import SimpleNamespace

    from noc.config import get_settings

    class Auth:
        def __init__(self, protected, user):
            self._p, self._u = protected, user

        async def is_protected_mode(self):
            return self._p

        async def resolve_session(self, token):
            return self._u if token == "good" else None

    class FakeConn(FakeWS):
        def __init__(self, auth, cookie):
            super().__init__()
            self.app = SimpleNamespace(state=SimpleNamespace(auth=auth))
            self.cookies = {get_settings().session_cookie_name: cookie} if cookie else {}
            self.accepted, self.close_code = False, None

        async def accept(self):
            self.accepted = True

        async def close(self, code=1000):
            self.closed, self.close_code = True, code

        async def receive_text(self):
            from fastapi import WebSocketDisconnect

            raise WebSocketDisconnect()

    settings = get_settings()
    monkeypatch.setattr(settings, "ws_require_auth", 1)
    denied = FakeConn(Auth(True, object()), None)
    await ws_module.events_ws(denied)  # type: ignore[arg-type]
    assert not denied.accepted and denied.close_code == 4401

    ok = FakeConn(Auth(True, object()), "good")
    await ws_module.events_ws(ok)  # type: ignore[arg-type]
    assert ok.accepted

    open_mode = FakeConn(Auth(False, None), None)
    await ws_module.events_ws(open_mode)  # type: ignore[arg-type]
    assert open_mode.accepted

    monkeypatch.setattr(settings, "ws_require_auth", 0)
    free = FakeConn(Auth(True, None), None)
    await ws_module.events_ws(free)  # type: ignore[arg-type]
    assert free.accepted
