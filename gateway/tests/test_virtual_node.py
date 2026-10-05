"""Nodo virtual (ADR 0033): protocolo de stream, configuración servida desde la
caché de la librería, difusión de lo que emite el nodo y bloqueo de lo que no
debe pasar del cliente al nodo real."""

import asyncio
from types import SimpleNamespace

import pytest
from meshtastic.protobuf import admin_pb2, channel_pb2, xmodem_pb2, config_pb2, localonly_pb2, mesh_pb2, portnums_pb2

from gateway.virtual_node import START1, START2, FrameParser, VirtualNodeServer, frame


def test_frame_parser_resyncs_after_garbage_and_handles_partial_frames():
    parser = FrameParser()
    wake = bytes([START2] * 32)  # el cliente Python manda 32 bytes 0xC3 al conectar
    payload = b"hello"
    data = wake + frame(payload) + frame(b"second")
    out = parser.feed(data[:10]) + parser.feed(data[10:50]) + parser.feed(data[50:])
    assert out == [payload, b"second"]


def test_frame_parser_ignores_oversized_header():
    parser = FrameParser()
    bogus = bytes([START1, START2, 0xFF, 0xFF])  # longitud absurda
    assert parser.feed(bogus + frame(b"ok")) == [b"ok"]


def _iface():
    local_config = localonly_pb2.LocalConfig()
    local_config.lora.region = config_pb2.Config.LoRaConfig.EU_868
    local_config.device.role = config_pb2.Config.DeviceConfig.CLIENT
    channel = channel_pb2.Channel(index=0)
    return SimpleNamespace(
        myInfo=mesh_pb2.MyNodeInfo(my_node_num=0xAABBCCDD),
        metadata=mesh_pb2.DeviceMetadata(firmware_version="2.7.0"),
        nodesByNum={
            0xAABBCCDD: {"num": 0xAABBCCDD, "user": {"id": "!aabbccdd", "longName": "Local", "shortName": "LOC"}},
            0x11223344: {"num": 0x11223344, "user": {"id": "!11223344", "shortName": "OTH"}, "snr": 4.5,
                         "position": {"latitudeI": 389000000, "latitude": 38.9}},
        },
        localNode=SimpleNamespace(channels=[channel], localConfig=local_config,
                                  moduleConfig=localonly_pb2.LocalModuleConfig()),
    )


class _Harness:
    def __init__(self, allow_admin=False, iface="default"):
        self.sent: list = []
        self.iface = _iface() if iface == "default" else iface

        async def send(msg):
            self.sent.append(msg)

        self.server = VirtualNodeServer(
            port=0, host="127.0.0.1", allow_admin=allow_admin,
            get_iface=lambda: self.iface, send_to_radio=send,
        )

    async def __aenter__(self):
        await self.server.start()
        self.port = self.server._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *a):
        await self.server.stop()

    async def connect(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(bytes([START2] * 32))  # como hace la librería oficial
        await writer.drain()
        return reader, writer


async def _read_frames(reader, parser, until_variant=None, timeout=3.0):
    frames = []
    async def go():
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                return
            for payload in parser.feed(chunk):
                msg = mesh_pb2.FromRadio()
                msg.ParseFromString(payload)
                frames.append(msg)
                if until_variant and msg.WhichOneof("payload_variant") == until_variant:
                    return
    await asyncio.wait_for(go(), timeout)
    return frames


def _want_config(writer, config_id):
    writer.write(frame(mesh_pb2.ToRadio(want_config_id=config_id).SerializeToString()))


async def test_initial_config_is_served_from_library_state():
    async with _Harness() as h:
        reader, writer = await h.connect()
        _want_config(writer, 4242)
        frames = await _read_frames(reader, FrameParser(), until_variant="config_complete_id")
        kinds = [f.WhichOneof("payload_variant") for f in frames]
        assert kinds[0] == "my_info" and kinds[-1] == "config_complete_id"
        assert frames[-1].config_complete_id == 4242
        assert kinds.count("node_info") == 2
        assert "channel" in kinds and "metadata" in kinds
        cfg_kinds = {f.config.WhichOneof("payload_variant") for f in frames if f.WhichOneof("payload_variant") == "config"}
        assert {"lora", "device"} <= cfg_kinds
        nodes = {f.node_info.num: f.node_info for f in frames if f.WhichOneof("payload_variant") == "node_info"}
        assert nodes[0x11223344].user.short_name == "OTH" and nodes[0x11223344].position.latitude_i == 389000000
        # el nodo real no recibe nada por una petición de configuración
        assert h.sent == []
        writer.close()


async def test_duplicate_want_config_is_ignored_and_no_link_closes_client():
    async with _Harness() as h:
        reader, writer = await h.connect()
        _want_config(writer, 7)
        await _read_frames(reader, FrameParser(), until_variant="config_complete_id")
        _want_config(writer, 7)  # mismo id dentro del cooldown: sin respuesta
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.read(10), 0.4)
        writer.close()
    async with _Harness(iface=None) as h:  # sin enlace con el nodo: cierra para que reintente
        reader, writer = await h.connect()
        _want_config(writer, 1)
        assert await asyncio.wait_for(reader.read(10), 2) == b""
        writer.close()


async def test_heartbeat_is_answered_locally_and_not_forwarded():
    async with _Harness() as h:
        reader, writer = await h.connect()
        writer.write(frame(mesh_pb2.ToRadio(heartbeat=mesh_pb2.Heartbeat()).SerializeToString()))
        frames = await _read_frames(reader, FrameParser(), until_variant="queueStatus")
        assert frames[-1].queueStatus.free == 32
        assert h.sent == []
        writer.close()


def _packet(portnum, payload=b"hi", **kw):
    pkt = mesh_pb2.MeshPacket(to=0xFFFFFFFF, id=99, **kw)
    pkt.decoded.portnum = portnum
    pkt.decoded.payload = payload
    return mesh_pb2.ToRadio(packet=pkt)


async def _send_and_settle(h, to_radio):
    reader, writer = await h.connect()
    writer.write(frame(to_radio.SerializeToString()))
    await writer.drain()
    await asyncio.sleep(0.2)
    writer.close()


async def test_text_is_forwarded_admin_is_blocked_by_default():
    async with _Harness() as h:
        await _send_and_settle(h, _packet(portnums_pb2.PortNum.TEXT_MESSAGE_APP, b"hola"))
        await _send_and_settle(h, _packet(portnums_pb2.PortNum.ADMIN_APP, b"\x08\x01"))
        assert len(h.sent) == 1 and h.sent[0].packet.decoded.payload == b"hola"
        assert h.server.blocked == 1


async def test_admin_allowed_when_enabled_but_add_contact_and_garbage_never():
    async with _Harness(allow_admin=True) as h:
        get_owner = admin_pb2.AdminMessage(get_owner_request=True)
        await _send_and_settle(h, _packet(portnums_pb2.PortNum.ADMIN_APP, get_owner.SerializeToString()))
        add_contact = admin_pb2.AdminMessage(add_contact=admin_pb2.SharedContact(node_num=1))
        await _send_and_settle(h, _packet(portnums_pb2.PortNum.ADMIN_APP, add_contact.SerializeToString()))
        await _send_and_settle(h, _packet(portnums_pb2.PortNum.ADMIN_APP, b"\xff\xff\xff"))
        assert len(h.sent) == 1  # solo el get_owner
        assert h.server.blocked == 2


async def test_xmodem_is_blocked_and_encrypted_follows_admin_flag():
    async with _Harness() as h:
        await _send_and_settle(h, mesh_pb2.ToRadio(xmodemPacket=xmodem_pb2.XModem(seq=1)))
        enc = mesh_pb2.ToRadio(packet=mesh_pb2.MeshPacket(to=1, id=5, encrypted=b"\x01\x02"))
        await _send_and_settle(h, enc)
        assert h.sent == [] and h.server.blocked == 2


async def test_node_emissions_are_broadcast_only_to_configured_clients():
    async with _Harness() as h:
        r1, w1 = await h.connect()
        r2, w2 = await h.connect()  # conectado pero sin pedir configuración
        _want_config(w1, 1)
        await _read_frames(r1, FrameParser(), until_variant="config_complete_id")
        live = mesh_pb2.FromRadio(packet=mesh_pb2.MeshPacket(id=77))
        h.server.feed(live.SerializeToString())
        frames = await _read_frames(r1, FrameParser(), until_variant="packet")
        assert frames[-1].packet.id == 77
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(r2.read(10), 0.4)
        assert h.server.status()["clients"] == 2
        w1.close()
        w2.close()


async def test_client_count_changes_notify_the_owner():
    changes = []
    async with _Harness() as h:
        h.server._on_change = lambda: changes.append(h.server.status()["clients"])
        reader, writer = await h.connect()
        await asyncio.sleep(0.1)
        writer.close()
        await asyncio.sleep(0.2)
    assert changes[:1] == [1] and 0 in changes
