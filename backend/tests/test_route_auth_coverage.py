"""Guardia de regresión: toda ruta que MODIFICA estado exige sesión en modo
protegido (RequireAuthDep/RequireAdminDep). Una ruta nueva sin dependencia
falla aquí en vez de quedar abierta sin que nadie se dé cuenta."""

from __future__ import annotations

from fastapi.routing import APIRoute

from noc.adapters.api.deps import require_admin, require_auth
from noc.main import create_app

# Excepciones deliberadas: (método, ruta).
OPEN_ON_PURPOSE = {
    ("POST", "/api/v1/auth/login"),  # es la propia autenticación
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/alerts/{alert_id}/ack"),  # triaje, no configuración (ADR 0024)
    ("POST", "/api/v1/admin/batches/preview"),  # simulación sin efectos
    ("POST", "/api/v1/admin/profiles/{profile_id}/sync/preview"),  # idem
}


def _deps(route: APIRoute) -> set:
    found, stack = set(), list(route.dependant.dependencies)
    while stack:
        d = stack.pop()
        found.add(d.call)
        stack.extend(d.dependencies)
    return found


def test_every_mutating_route_requires_auth():
    unprotected = []
    for route in create_app().routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods & {"POST", "PUT", "PATCH", "DELETE"}:
            if (method, route.path) in OPEN_ON_PURPOSE:
                continue
            if not ({require_auth, require_admin} & _deps(route)):
                unprotected.append(f"{method} {route.path}")
    assert not unprotected, "Rutas que escriben sin exigir sesión:\n" + "\n".join(sorted(unprotected))


def test_provider_secrets_masked_without_session():
    from noc.adapters.api.routers.alerts import _mask_secrets

    masked = _mask_secrets("telegram", {"bot_token": "123:abc", "chat_id": "42"})
    assert masked == {"bot_token": "••••", "chat_id": "42"}
    webhook = _mask_secrets("webhook", {"url": "https://x/secret", "headers": {"A": "b"}})
    assert webhook == {"url": "••••", "headers": "••••"}
    assert _mask_secrets("ntfy", {"url": "https://ntfy.sh", "topic": "t"})["url"] == "https://ntfy.sh"


def test_gateway_connection_params_masked_without_session():
    from noc.adapters.api.routers.gateways import GatewayOut, _masked

    out = GatewayOut.model_construct(connection_params={"host": "10.0.0.5", "port": 4403})
    assert _masked(out, False).connection_params == {"host": "••••", "port": "••••"}
    out2 = GatewayOut.model_construct(connection_params={"host": "10.0.0.5"})
    assert _masked(out2, True).connection_params == {"host": "10.0.0.5"}
