"""M6.2: nodos compartidos deterministas entre pasarelas simuladas.

Dos procesos gateway con `sim_shared_seed` idéntico deben generar exactamente
los mismos nodos compartidos (mismos node_id), además de sus mallas exclusivas
disjuntas — es el mecanismo para poblar node_gateway_links con solape real.
"""

from gateway.config import Settings
from gateway.transports.simulated import SimulatedTransport


async def _noop_emit(event_type: str, payload: dict) -> None:  # pragma: no cover
    pass


def make_transport(gateway_id: str, seed: int, shared_seed: int = 0, shared_count: int = 4):
    settings = Settings(
        _env_file=None,
        gateway_id=gateway_id,
        transport="simulated",
        sim_node_count=5,
        sim_seed=seed,
        sim_shared_seed=shared_seed,
        sim_shared_node_count=shared_count,
    )
    return SimulatedTransport(_noop_emit, settings)


def test_default_mesh_unchanged_without_shared_seed():
    """shared_seed=0 (por defecto): misma malla que antes de M6.2."""
    legacy = make_transport("gw-01", seed=42)
    assert len(legacy._nodes) == 5
    assert all(n.short_name.startswith("SIM") for n in legacy._nodes)


def test_same_shared_seed_produces_identical_shared_nodes():
    t1 = make_transport("gw-01", seed=1, shared_seed=7)
    t2 = make_transport("gw-02", seed=2, shared_seed=7)

    shared1 = [n for n in t1._nodes if n.short_name.startswith("SHR")]
    shared2 = [n for n in t2._nodes if n.short_name.startswith("SHR")]
    assert len(shared1) == len(shared2) == 4
    assert [n.node_id for n in shared1] == [n.node_id for n in shared2]
    assert [(n.lat, n.lon, n.hw_model, n.role) for n in shared1] == [
        (n.lat, n.lon, n.hw_model, n.role) for n in shared2
    ]

    # Las mallas exclusivas siguen siendo disjuntas (semillas distintas)
    excl1 = {n.node_id for n in t1._nodes if not n.short_name.startswith("SHR")}
    excl2 = {n.node_id for n in t2._nodes if not n.short_name.startswith("SHR")}
    assert excl1.isdisjoint(excl2)


def test_local_node_is_always_exclusive():
    """El nodo local (self._nodes[0]) nunca puede ser un compartido: dos
    pasarelas no pueden reclamar el mismo nodo local."""
    t = make_transport("gw-01", seed=1, shared_seed=7)
    assert t._nodes[0].short_name.startswith("SIM")


def test_different_shared_seed_produces_different_shared_nodes():
    t1 = make_transport("gw-01", seed=1, shared_seed=7)
    t2 = make_transport("gw-02", seed=1, shared_seed=8)
    shared1 = {n.node_id for n in t1._nodes if n.short_name.startswith("SHR")}
    shared2 = {n.node_id for n in t2._nodes if n.short_name.startswith("SHR")}
    assert shared1.isdisjoint(shared2)
