"""Chat: monitor de TEXT_MESSAGE_APP sobre `chat_messages`.

Un paquete de texto genera, en la MISMA transacción de ingesta, su
`ActivityEvent` (ya cubierto en test_activity_events.py) Y su fila de chat —
aquí se prueba la persistencia y el repositorio (filtros de canal/DM/pasarela/
texto), no la narración (que no cambia).
"""

import uuid
from datetime import datetime, timezone

from noc.adapters.persistence.chat_repositories import SqlChatRepository
from noc.application.ingest import IngestService

NODE_A = "!a1b2c3d4"
NODE_B = "!deadbeef"


def make_event(event_type: str, payload: dict, gateway_id: str = "gw-test") -> dict:
    return {
        "schema_version": 1,
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "gateway_id": gateway_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


async def test_message_received_persists_chat_row(session_factory):
    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("node.seen", {"node_id": NODE_A, "short_name": "AAA"}))
    await ingest.handle_event(
        make_event(
            "message.received",
            {
                "from_node_id": NODE_A,
                "text": "hola malla",
                "channel_index": 2,
                "rssi": -80,
                "snr": 6.5,
                "hops_away": 1,
                "hop_limit": 2,
                "hop_start": 3,
                "packet_id": 42,
            },
        )
    )

    async with session_factory() as session:
        rows = await SqlChatRepository(session).list_messages(limit=10)
    assert len(rows) == 1
    msg = rows[0]
    assert msg.from_node_id == NODE_A
    assert msg.to_node_id is None  # broadcast
    assert msg.channel_index == 2
    assert msg.text == "hola malla"
    assert msg.gateway_id == "gw-test"
    assert msg.rssi == -80
    assert msg.snr == 6.5
    assert msg.hop_limit == 2
    assert msg.hop_start == 3
    assert msg.packet_id == 42
    assert msg.direction == "inbound"
    assert msg.id is not None
    assert msg.received_at is not None


async def test_direct_message_sets_to_node_id(session_factory):
    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("node.seen", {"node_id": NODE_A}))
    await ingest.handle_event(make_event("node.seen", {"node_id": NODE_B}))
    await ingest.handle_event(
        make_event(
            "message.received",
            {"from_node_id": NODE_A, "to_node_id": NODE_B, "text": "hola B", "channel_index": 0},
        )
    )

    async with session_factory() as session:
        repo = SqlChatRepository(session)
        all_msgs = await repo.list_messages(limit=10)
        dm_only = await repo.list_messages(limit=10, dm_only=True)
        broadcast_only = await repo.list_messages(limit=10, broadcast_only=True)
        channels = await repo.list_channels()
        dm_count = await repo.dm_count()

    assert len(all_msgs) == 1
    assert all_msgs[0].to_node_id == NODE_B
    assert len(dm_only) == 1
    assert len(broadcast_only) == 0
    # Un DM no cuenta como canal (no hay tráfico broadcast todavía)
    assert channels == []
    assert dm_count == 1


async def test_list_messages_filters_by_channel_gateway_and_text(session_factory):
    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("node.seen", {"node_id": NODE_A}))
    await ingest.handle_event(
        make_event(
            "message.received",
            {"from_node_id": NODE_A, "text": "primero", "channel_index": 0},
            gateway_id="gw-01",
        )
    )
    await ingest.handle_event(
        make_event(
            "message.received",
            {"from_node_id": NODE_A, "text": "segundo canal 1", "channel_index": 1},
            gateway_id="gw-02",
        )
    )

    async with session_factory() as session:
        repo = SqlChatRepository(session)
        by_channel = await repo.list_messages(limit=10, channel_index=1)
        by_gateway = await repo.list_messages(limit=10, gateway_id="gw-01")
        by_text = await repo.list_messages(limit=10, q="SEGUNDO")
        channels = await repo.list_channels()

    assert [m.text for m in by_channel] == ["segundo canal 1"]
    assert [m.text for m in by_gateway] == ["primero"]
    assert [m.text for m in by_text] == ["segundo canal 1"]
    assert {c["channel_index"] for c in channels} == {0, 1}


async def test_list_messages_pagination_before_id(session_factory):
    ingest = IngestService(session_factory)
    await ingest.handle_event(make_event("node.seen", {"node_id": NODE_A}))
    for i in range(3):
        await ingest.handle_event(
            make_event("message.received", {"from_node_id": NODE_A, "text": f"msg {i}"})
        )

    async with session_factory() as session:
        repo = SqlChatRepository(session)
        first_page = await repo.list_messages(limit=2)
        second_page = await repo.list_messages(limit=2, before_id=first_page[-1].id)

    assert [m.text for m in first_page] == ["msg 2", "msg 1"]
    assert [m.text for m in second_page] == ["msg 0"]
