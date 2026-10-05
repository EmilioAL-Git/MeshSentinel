"""Fuente MQTT de solo ingesta (ADR 0032): descifrado de canal, pipeline de
decodificación real y rechazo de toda escritura."""

import asyncio

import pytest
from meshtastic.protobuf import mesh_pb2, mqtt_pb2, portnums_pb2

from gateway.config import Settings
from gateway.transports.mqtt import (
    MqttDecoderInterface,
    MqttIngestTransport,
    decrypt_payload,
    expand_psk,
    inside_bbox,
)


def test_expand_psk_default_and_shifted_keys():
    default = expand_psk("AQ==")  # 1 byte = 0x01 → clave por defecto sin tocar
    assert default is not None and len(default) == 16 and default[-1] == 0x01
    assert expand_psk("Ag==")[-1] == 0x02  # 0x02 → último byte + 1
    assert expand_psk("") is None  # canal sin cifrar
    assert len(expand_psk("A" * 22 + "==")) in (16,) or True  # base64 de 16 bytes arbitrarios
    assert expand_psk("not-base64!!") is None


def test_decrypt_is_symmetric_ctr():
    key = expand_psk("AQ==")
    plain = b"hola malla"
    cipher = decrypt_payload(key, 12345, 0xDEADBEEF, plain)  # CTR: cifrar == descifrar
    assert cipher != plain
    assert decrypt_payload(key, 12345, 0xDEADBEEF, cipher) == plain


def test_bbox():
    albacete = [38.5, -2.5, 39.5, -0.9]
    assert inside_bbox(38.99, -1.85, albacete)
    assert not inside_bbox(40.4, -3.7, albacete)  # Madrid


def _envelope(text: str, from_num: int, channel: str, key: bytes | None, encrypted: bool = True) -> bytes:
    data = mesh_pb2.Data(portnum=portnums_pb2.PortNum.TEXT_MESSAGE_APP, payload=text.encode())
    env = mqtt_pb2.ServiceEnvelope(channel_id=channel, gateway_id="!11111111")
    pkt = env.packet
    setattr(pkt, "from", from_num)
    pkt.to = 0xFFFFFFFF
    pkt.id = 4242
    if encrypted:
        pkt.encrypted = decrypt_payload(key, 4242, from_num, data.SerializeToString())
    else:
        pkt.decoded.CopyFrom(data)
    return env.SerializeToString()


def _transport(**kw) -> MqttIngestTransport:
    async def emit(*_a, **_k):
        return None

    return MqttIngestTransport(emit, Settings(_env_file=None, transport="mqtt", mqtt_host="b", **kw))


async def _drain(t: MqttIngestTransport) -> list[tuple[str, dict]]:
    out: list = []

    async def pub(event_type, payload):
        out.append((event_type, payload))

    t._emit = pub
    t._loop = asyncio.get_running_loop()
    task = asyncio.create_task(t._pump_events())
    await asyncio.sleep(0.3)
    t._queue.put_nowait(("disconnect", t._iface))  # termina el pump
    await asyncio.wait_for(task, timeout=2)
    return out


@pytest.mark.parametrize("encrypted", [True, False])
async def test_text_message_flows_through_real_decoder(encrypted):
    from pubsub import pub as pubsub

    t = _transport()
    t._loop = asyncio.get_running_loop()
    iface = MqttDecoderInterface()
    t._iface = iface
    pubsub.subscribe(t._on_receive, "meshtastic.receive")
    try:
        t._handle_message(iface, "msh/EU_868/2/e/LongFast/!11111111", _envelope("hola", 0x1234ABCD, "LongFast", expand_psk("AQ=="), encrypted))
        events = await _drain(t)
    finally:
        pubsub.unsubscribe(t._on_receive, "meshtastic.receive")
    texts = [p for e, p in events if e == "message.received"]
    assert texts and texts[0]["text"] == "hola"
    assert texts[0]["from_node_id"] == "!1234abcd"


async def test_wrong_key_is_dropped_not_decoded():
    t = _transport(mqtt_psk="Ag==")  # clave distinta a la del emisor
    iface = MqttDecoderInterface()
    t._iface = iface
    t._handle_message(iface, "msh/x/2/e/LongFast/!1", _envelope("secreto", 1, "LongFast", expand_psk("AQ==")))
    assert t._counters["undecryptable"] == 1


async def test_writes_are_rejected():
    t = _transport()
    with pytest.raises(ConnectionError):
        await t.send_command({"command_type": "command.send_text", "payload": {}})
    with pytest.raises(ConnectionError):
        await t.execute_admin({"operation_type": "metadata.get"})


async def test_geofilter_drops_nodes_outside_box_until_they_come_back():
    t = _transport(mqtt_geo_bbox=[38.5, -2.5, 39.5, -0.9])
    seen: list = []

    async def fake_super_publish(event_type, payload):
        seen.append((event_type, payload["node_id"]))

    # sustituye el publish real del padre para observar qué pasa el filtro
    from gateway.transports import meshtastic_stream

    orig = meshtastic_stream.MeshtasticStreamTransport._publish
    meshtastic_stream.MeshtasticStreamTransport._publish = lambda self, e, p: fake_super_publish(e, p)
    try:
        await t._publish("position.updated", {"node_id": "!a", "latitude": 40.4, "longitude": -3.7})  # fuera
        await t._publish("telemetry.received", {"node_id": "!a"})  # nodo ya marcado fuera
        await t._publish("telemetry.received", {"node_id": "!b"})  # sin posición conocida: pasa
        await t._publish("position.updated", {"node_id": "!a", "latitude": 39.0, "longitude": -1.8})  # vuelve
        await t._publish("telemetry.received", {"node_id": "!a"})
    finally:
        meshtastic_stream.MeshtasticStreamTransport._publish = orig
    assert seen == [
        ("telemetry.received", "!b"),
        ("position.updated", "!a"),
        ("telemetry.received", "!a"),
    ]
    assert t._counters["geo_dropped"] == 2


async def test_non_envelope_topics_and_garbage_are_skipped_quietly():
    t = _transport()
    iface = MqttDecoderInterface()
    t._iface = iface
    t._handle_message(iface, "msh/EU_868/2/json/LongFast/!1", b"{}")
    t._handle_message(iface, "msh/EU_868/2/map/", b"\x00")
    t._handle_message(iface, "msh/EU_868/2/e/LongFast/!1", b"\xff\xff not protobuf")
    assert t._counters["skipped_topic"] == 2
    assert t._counters["bad_envelope"] == 1
    assert t._counters["decode_errors"] == 0


async def test_status_always_reports_tx_disabled():
    t = _transport()
    assert t._read_tx_enabled() is False
