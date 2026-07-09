"""M4.1 (ADR 0019): registro de operaciones ack-only y estado de sync remoto
derivado de admin_operations (sin tabla propia)."""

import pytest

from noc.adapters.persistence.admin_repositories import SqlAdminOperationRepository
from noc.application.admin.registry import validate_operation
from noc.application.admin.remote_flags import get_favorite_status, get_ignored_status
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


async def test_no_status_when_no_operations_exist(session_factory):
    async with session_factory() as session:
        assert await get_favorite_status(session, TARGET) is None
        assert await get_ignored_status(session, TARGET) is None


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
    async with session_factory() as session:
        status = await get_favorite_status(session, TARGET)
    assert status is not None
    assert status.sync_state == expected_state
    assert status.desired is True  # favorite.set -> True
    assert status.subject_node_id == SUBJECT


async def test_remove_operation_reports_desired_false(session_factory):
    await create_op(session_factory, "favorite.remove", SUBJECT, "succeeded")
    async with session_factory() as session:
        status = await get_favorite_status(session, TARGET)
    assert status is not None
    assert status.desired is False


async def test_status_reflects_latest_operation_only(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "succeeded")
    await create_op(session_factory, "favorite.remove", SUBJECT, "failed")
    async with session_factory() as session:
        status = await get_favorite_status(session, TARGET)
    assert status is not None
    assert status.desired is False
    assert status.sync_state == "error"


async def test_status_can_be_scoped_to_a_specific_subject(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "succeeded")
    await create_op(session_factory, "favorite.set", OTHER_SUBJECT, "failed")
    async with session_factory() as session:
        for_subject = await get_favorite_status(session, TARGET, SUBJECT)
        for_other = await get_favorite_status(session, TARGET, OTHER_SUBJECT)
    assert for_subject is not None and for_subject.sync_state == "confirmed"
    assert for_other is not None and for_other.sync_state == "error"


async def test_favorite_and_ignored_are_tracked_independently(session_factory):
    await create_op(session_factory, "favorite.set", SUBJECT, "succeeded")
    await create_op(session_factory, "ignored.set", SUBJECT, "failed")
    async with session_factory() as session:
        favorite = await get_favorite_status(session, TARGET)
        ignored = await get_ignored_status(session, TARGET)
    assert favorite is not None and favorite.sync_state == "confirmed"
    assert ignored is not None and ignored.sync_state == "error"
