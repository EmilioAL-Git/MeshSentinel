"""Resolución del autor de una operación — función única, reutilizada en toda
la aplicación (renderers de Actividad, esquemas de API, cualquier vista que
necesite mostrar "quién hizo esto"). No duplicar esta lógica en ningún otro
sitio (ni en backend ni en frontend: el frontend consume el resultado ya
resuelto, nunca reconstruye el nombre).
"""

from dataclasses import dataclass
from typing import Protocol

from noc.domain.auth.entities import AuthUser

ActorType = str  # "system" | "user" | "api"


@dataclass(slots=True, frozen=True)
class ActorContext:
    """Autoría congelada en el momento de crear una AdminOperation/AdminBatch
    (CAMBIO 3): username y display_name se copian tal cual eran entonces, sin
    depender de que el usuario siga existiendo o no haya cambiado su nombre."""

    actor_type: ActorType = "system"
    actor_id: int | None = None
    actor_username: str | None = None
    actor_display_name: str | None = None

    @staticmethod
    def for_user(user: AuthUser | None) -> "ActorContext":
        """Construye el contexto a partir del usuario autenticado de la
        request (None en modo abierto, o si nadie ha iniciado sesión)."""
        if user is None:
            return ActorContext(actor_type="system")
        return ActorContext(
            actor_type="user",
            actor_id=user.id,
            actor_username=user.username,
            actor_display_name=user.display_name,
        )


class _HasActorFields(Protocol):
    actor_type: str
    actor_display_name: str | None
    created_by: str


def resolve_actor_label(actor_type: str | None, actor_display_name: str | None, created_by: str | None) -> str:
    """Único resolver de autoría (CAMBIO 2/CAMBIO 9): actor_display_name si
    existe; si no, cae al created_by legado; si tampoco hay nada, una
    etiqueta genérica según actor_type. Reutilizado por los renderers de
    ActivityEvent y por los esquemas OperationOut/BatchOut — el frontend
    nunca debe reimplementar este fallback."""
    if actor_display_name:
        return actor_display_name
    if created_by:
        return created_by
    if actor_type == "api":
        return "API"
    return "Sistema"


def actor_label_for(obj: _HasActorFields) -> str:
    return resolve_actor_label(obj.actor_type, obj.actor_display_name, obj.created_by)
