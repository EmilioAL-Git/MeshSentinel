"""Estabilidad de la reconexión y del proceso (lecciones de MeshMonitor):
escalera tras pérdida a mitad de sincronización, snapshot de NodeDB no
reemitido en flaps rápidos y vigilancia de las tareas críticas."""

import asyncio


from gateway import main as gateway_main
from gateway.config import Settings
from gateway.transports import meshtastic_stream
from gateway.transports.meshtastic_stream import SYNC_LOSS_RETRY_LADDER, _is_sync_loss
from gateway.transports.tcp import MeshtasticTcpTransport


async def _noop_emit(*_a, **_k) -> None:
    return None


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, transport="tcp", tcp_host="10.0.0.1", **kw)


def test_sync_loss_classification():
    assert _is_sync_loss(Exception("Timed out waiting for connection completion"))
    assert not _is_sync_loss(ConnectionRefusedError(111, "refused"))
    assert not _is_sync_loss(TimeoutError("timed out"))
    assert not _is_sync_loss(OSError("host unreachable"))


class _ScriptedTransport(MeshtasticTcpTransport):
    """Falla según un guion y registra las esperas pedidas entre intentos."""

    def __init__(self, script, *a, **k):
        super().__init__(*a, **k)
        self.script = list(script)
        self.sleeps: list[float] = []

    def _connect_blocking(self):
        if not self.script:
            self._closed.set()  # fin de la prueba
            raise ConnectionRefusedError("done")
        raise self.script.pop(0)

    async def _sleep(self, base: float) -> None:
        self.sleeps.append(base)


async def test_ladder_used_for_mid_sync_loss_then_normal_backoff():
    sync = Exception("Timed out waiting for connection completion")
    t = _ScriptedTransport([sync] * 4, _noop_emit, _settings())
    await asyncio.wait_for(t.run(), timeout=5)
    # 3 peldaños de la escalera, y el 4º fallo pasa al backoff exponencial (5 s)
    assert t.sleeps[:3] == list(SYNC_LOSS_RETRY_LADDER)
    assert t.sleeps[3] == 5.0


async def test_unreachable_node_never_uses_ladder():
    t = _ScriptedTransport([ConnectionRefusedError(111, "x")] * 3, _noop_emit, _settings())
    await asyncio.wait_for(t.run(), timeout=5)
    assert t.sleeps[:3] == [5.0, 10.0, 20.0]


class _SnapshotTransport(MeshtasticTcpTransport):
    def _local_node_info(self):
        return ("!00000001", "A", "Node A", "TBEAM", "2.7.0", [], {"!00000002": {}, "!00000003": {}})


async def _published(t, monkeypatch) -> list:
    out: list = []

    async def pub(event_type, payload):
        out.append(event_type)

    t._emit = pub
    monkeypatch.setattr(
        meshtastic_stream, "decode_nodedb_entry", lambda nid, entry: ("node.seen", {"node_id": nid})
    )
    await t._on_connected()
    return [e for e in out if e == "node.seen"]


async def test_snapshot_published_first_time_and_skipped_on_quick_reconnect(monkeypatch):
    t = _SnapshotTransport(_noop_emit, _settings())
    assert len(await _published(t, monkeypatch)) == 2
    assert len(await _published(t, monkeypatch)) == 0  # flap rápido: no se reemite


async def test_snapshot_republished_after_interval_or_when_disabled(monkeypatch):
    t = _SnapshotTransport(_noop_emit, _settings(GATEWAY_SNAPSHOT_MIN_INTERVAL_SECONDS=0))
    assert len(await _published(t, monkeypatch)) == 2
    assert len(await _published(t, monkeypatch)) == 2  # 0 = siempre

    t2 = _SnapshotTransport(_noop_emit, _settings())
    await _published(t2, monkeypatch)
    t2._last_snapshot_at -= 601  # ventana vencida
    assert len(await _published(t2, monkeypatch)) == 2


# ── Vigilancia de tareas críticas ────────────────────────────────────────────


class _FakePublisher:
    def __init__(self, *a, **k):
        self.publish = _noop_emit

    async def close(self):
        pass


class _FakeManager:
    transport = None

    def __init__(self, *a, **k):
        pass

    async def start_from_env(self):
        pass

    async def teardown(self):
        pass


def _patch_main(monkeypatch, consumer_cls):
    monkeypatch.setattr(gateway_main, "EventPublisher", _FakePublisher)
    monkeypatch.setattr(gateway_main, "TransportManager", _FakeManager)
    monkeypatch.setattr(gateway_main, "CommandConsumer", consumer_cls)
    monkeypatch.setattr(gateway_main, "get_settings", lambda: _settings())


async def test_main_exits_nonzero_when_command_consumer_dies(monkeypatch):
    class DyingConsumer:
        def __init__(self, *a, **k):
            pass

        async def run(self):
            raise RuntimeError("boom")

        async def close(self):
            pass

    _patch_main(monkeypatch, DyingConsumer)
    assert await asyncio.wait_for(gateway_main.main(), timeout=5) == 1


async def test_main_exits_zero_on_clean_signal(monkeypatch):
    class IdleConsumer:
        def __init__(self, *a, **k):
            pass

        async def run(self):
            await asyncio.sleep(3600)

        async def close(self):
            pass

    _patch_main(monkeypatch, IdleConsumer)
    task = asyncio.create_task(gateway_main.main())
    await asyncio.sleep(0.2)
    import os
    import signal

    os.kill(os.getpid(), signal.SIGTERM)
    assert await asyncio.wait_for(task, timeout=5) == 0


async def test_cancelled_connect_closes_the_orphan_interface_and_aborts_pending():
    """Una conexión en un hilo no se puede cancelar: si el transporte se
    sustituye mientras conecta, la interfaz que acabe creándose debe cerrarse
    (si no, su hilo lector robaría tramas al nodo a la pasarela nueva)."""
    import threading

    release = threading.Event()
    closed = threading.Event()
    aborted: list[bool] = []

    class FakeIface:
        def close(self):
            closed.set()

    class Slow(MeshtasticTcpTransport):
        def _connect_blocking(self):
            release.wait(5)
            return FakeIface()

        def _abort_pending_connect(self):
            aborted.append(True)

    t = Slow(_noop_emit, _settings())
    task = asyncio.create_task(t.run())
    await asyncio.sleep(0.2)  # ya está dentro de _connect_blocking
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert aborted == [True]
    assert not closed.is_set()
    release.set()  # la conexión termina DESPUÉS de cancelar
    assert await asyncio.to_thread(closed.wait, 3), "la interfaz huérfana debe cerrarse"
