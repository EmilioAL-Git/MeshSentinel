"""M4.1 (ADR 0019): registro de operaciones ack-only y estado de sync remoto
derivado de admin_operations (sin tabla propia)."""

import pytest

from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.application.admin.registry import validate_operation
from noc.application.admin.remote_flag_sync import compute_resend_plan, compute_sync_plan
from noc.application.admin.remote_flags import AdminOperationRemoteFlagStateReader
from noc.domain.admin.entities import AdminOperation

TARGET = "!a1b2c3d4"
SUBJECT = "!11112222"
OTHER_SUBJECT = "!33334444"


# ── Registro ──────────────────────────────────────────────────────────────


def test_registry_validates_subject_node_id():
    assert validate_operation("favorite.set", {"subject_node_id": SUBJECT}) == {
        "subject_node_id": SUBJECT
    }
    assert validate_operation("ignored.remove", {"subject_node_id": SUBJECT}) == {
        "subject_node_id": SUBJECT
    }
    with pytest.raises(ValueError):
        validate_operation("favorite.set", {"subject_node_id": "not-canonical"})
    with pytest.raises(ValueError):
        validate_operation("favorite.set", {})


def test_registry_contact_add_keeps_only_known_fields():
    out = validate_operation(
        "contact.add",
        {
            "subject_node_id": SUBJECT,
            "long_name": "Repetidor Norte",
            "short_name": "RNOR",
            "hw_model": None,
            "public_key": None,
            "unexpected": "ignored by design (no whitelist check for custom validators)",
        },
    )
    assert out == {"subject_node_id": SUBJECT, "long_name": "Repetidor Norte", "short_name": "RNOR"}


def test_ack_only_operations_are_flagged_in_capabilities():
    from noc.application.admin.registry import OPERATIONS

    for op_type in ("favorite.set", "favorite.remove", "ignored.set", "ignored.remove", "contact.add"):
        assert OPERATIONS[op_type].ack_only is True
    assert OPERATIONS["owner.set"].ack_only is False


# ── Estado derivado (sin tabla propia) ──────────────────────────────────────


async def create_op(session_factory, operation_type: str, subject: str, status: str) -> None:
    async with session_factory() as session, session.begin():
        repo = SqlAdminOperationRepository(session)
        created = await repo.create(
            AdminOperation(
                target_node_id=TARGET,
                gateway_id="gw-test",
                operation_type=operation_type,
                params={"subject_node_id": subject},
            )
        )
        await repo.update_fields(created.id, {"status": status})


async def known_of(session_factory, flag_type: str):
    async with session_factory() as session:
        return await AdminOperationRemoteFlagStateReader(session).list_known(TARGET, flag_type)


async def test_no_known_subjects_when_no_operations_exist(session_factory):
    assert await known_of(session_factory, "favorite") == []
    assert await known_of(session_factory, "ignored") == []


@pytest.mark.parametrize(
    "op_status,expected_state",
    [
        ("pending", "pending"),
        ("queued", "pending"),
        ("running", "sent"),
        ("succeeded", "confirmed"),
        ("succeeded_unconfirmed", "confirmed"),  # nunca expuesto como tal (ADR 0019 §2)
        ("verify_failed", "error"),
        ("failed", "error"),
        ("timeout", "error"),
        ("cancelled", "error"),
    ],
)
async def test_status_maps_operation_status_to_sync_vocabulary(session_factory, op_status, expected_state):
    await create_op(session_factory, "favorite.set", SUBJECT, op_status)
    known = await known_of(session_factory, "favorite")
    assert len(known) == 1
    assert known[0].sync_state == expected_state
    assert known[0].latest_action == "set"
    assert known[0].subject_node_id == SUBJECT


async def test_remove_operation_reports_latest_action_remove(session_factory):
    await create_op(session_factory, "favorite.remove", SUBJECT, "succeeded")
    known = await known_of(session_factory, "favorite")
    assert known[0].latest_action == "remove"
    assert known[0].confirmed_action == "remove"


async def test_status_reflects_latest_operation_but_keeps_last_confirmed(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "succeeded")
    await create_op(session_factory, "favorite.remove", SUBJECT, "failed")
    known = await known_of(session_factory, "favorite")
    assert known[0].latest_action == "remove"
    assert known[0].sync_state == "error"
    assert known[0].confirmed_action == "set"  # el último confirmado sigue siendo el set anterior


async def test_status_tracks_every_known_subject(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "succeeded")
    await create_op(session_factory, "favorite.set", OTHER_SUBJECT, "failed")
    known = {k.subject_node_id: k for k in await known_of(session_factory, "favorite")}
    assert known[SUBJECT].sync_state == "confirmed"
    assert known[OTHER_SUBJECT].sync_state == "error"


async def test_favorite_and_ignored_are_tracked_independently(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "succeeded")
    await create_op(session_factory, "ignored.set", SUBJECT, "failed")
    favorite = await known_of(session_factory, "favorite")
    ignored = await known_of(session_factory, "ignored")
    assert favorite[0].sync_state == "confirmed"
    assert ignored[0].sync_state == "error"


# ── Planes de sincronización (M4.2, ADR 0020) ───────────────────────────────


async def test_sync_plan_skips_subjects_already_confirmed_as_desired(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "succeeded")
    async with session_factory() as session:
        reader = AdminOperationRemoteFlagStateReader(session)
        plan = await compute_sync_plan(reader, TARGET, "favorite")
    assert plan.items == []


async def test_sync_plan_generates_add_when_not_yet_confirmed(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "pending")
    async with session_factory() as session:
        reader = AdminOperationRemoteFlagStateReader(session)
        plan = await compute_sync_plan(reader, TARGET, "favorite")
    assert len(plan.items) == 1
    assert plan.items[0].kind == "ADD"
    assert plan.items[0].subject_node_id == SUBJECT
    assert plan.items[0].target_gateway_id is None


async def test_sync_plan_generates_remove_when_confirmed_state_disagrees(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "succeeded")
    await create_op(session_factory, "favorite.remove", SUBJECT, "pending")
    async with session_factory() as session:
        reader = AdminOperationRemoteFlagStateReader(session)
        plan = await compute_sync_plan(reader, TARGET, "favorite")
    assert len(plan.items) == 1
    assert plan.items[0].kind == "REMOVE"


async def test_sync_plan_with_contact_prepends_contact_add(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "pending")
    async with session_factory() as session:
        reader = AdminOperationRemoteFlagStateReader(session)
        plan = await compute_sync_plan(reader, TARGET, "favorite", send_contact=True)
    assert [item.kind for item in plan.items] == ["CONTACT_ADD", "ADD"]


async def test_resend_plan_only_targets_pending_and_error(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "succeeded")
    await create_op(session_factory, "favorite.set", OTHER_SUBJECT, "failed")
    async with session_factory() as session:
        reader = AdminOperationRemoteFlagStateReader(session)
        plan = await compute_resend_plan(reader, TARGET, "favorite")
    assert len(plan.items) == 1
    assert plan.items[0].subject_node_id == OTHER_SUBJECT
    assert plan.items[0].kind == "ADD"


async def test_resend_plan_never_touches_confirmed(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "succeeded")
    async with session_factory() as session:
        reader = AdminOperationRemoteFlagStateReader(session)
        plan = await compute_resend_plan(reader, TARGET, "favorite")
    assert plan.items == []
