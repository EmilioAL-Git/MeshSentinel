"""M1.3: validación de SETs seguros y mapeo del veredicto de verificación."""

import pytest

from noc.application.admin.registry import OPERATIONS, validate_operation
from noc.application.admin.service import AdminOperationService

# ── Registro ─────────────────────────────────────────────────────────────────


def test_set_operations_registered_and_flagged():
    for op_type in ("owner.set", "position.set_fixed"):
        spec = OPERATIONS[op_type]
        assert spec.kind == "set"
        assert spec.requires_confirmation is True
        assert spec.destructive is False
    # M2: owner.set sigue siendo unitario (los nombres deben ser únicos);
    # el resto de SETs admiten ejecución masiva
    assert OPERATIONS["owner.set"].allow_bulk is False
    assert OPERATIONS["position.set_fixed"].allow_bulk is True
    assert OPERATIONS["config.set"].allow_bulk is True
    assert OPERATIONS["module_config.set"].allow_bulk is True
    # Los GET no exigen confirmación
    assert OPERATIONS["metadata.get"].requires_confirmation is False


def test_owner_set_validation():
    assert validate_operation("owner.set", {"short_name": "4IEN"}) == {"short_name": "4IEN"}
    assert validate_operation("owner.set", {"long_name": "Repetidor Norte "}) == {
        "long_name": "Repetidor Norte"
    }
    both = validate_operation("owner.set", {"short_name": "AB", "long_name": "Nodo AB"})
    assert both == {"short_name": "AB", "long_name": "Nodo AB"}
    with pytest.raises(ValueError):
        validate_operation("owner.set", {})  # al menos un campo
    with pytest.raises(ValueError):
        validate_operation("owner.set", {"short_name": "DEMASIADO"})  # >4
    with pytest.raises(ValueError):
        validate_operation("owner.set", {"long_name": "x" * 40})  # >39
    with pytest.raises(ValueError):
        validate_operation("owner.set", {"nombre": "x"})  # parámetro desconocido


def test_fixed_position_validation():
    ok = validate_operation("position.set_fixed", {"latitude": 40.4168, "longitude": -3.7038})
    assert ok == {"latitude": 40.4168, "longitude": -3.7038}
    with_alt = validate_operation(
        "position.set_fixed", {"latitude": "40.4", "longitude": "-3.7", "altitude": 657}
    )
    assert with_alt["altitude"] == 657
    with pytest.raises(ValueError):
        validate_operation("position.set_fixed", {"latitude": 91, "longitude": 0})
    with pytest.raises(ValueError):
        validate_operation("position.set_fixed", {"latitude": 0, "longitude": 181})
    with pytest.raises(ValueError):
        validate_operation("position.set_fixed", {"longitude": -3.7})  # falta latitude


# ── Mapeo del veredicto de verificación (ADR 0014) ───────────────────────────


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"verify": "confirmed", "previous": {}, "verified": {}}, "succeeded"),
        ({"verify": "unavailable", "previous": {}, "verified": None}, "succeeded_unconfirmed"),
        ({"verify": "mismatch", "previous": {}, "verified": {}}, "verify_failed"),
        ({"firmwareVersion": "2.7.0"}, "succeeded"),  # GET sin verify
        (None, "succeeded"),
    ],
)
def test_map_success_status(result, expected):
    assert AdminOperationService._map_success_status(result) == expected
