from typing import Annotated, AsyncIterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from noc.application.auth.service import AuthService
from noc.config import get_settings
from noc.domain.auth.entities import AuthUser


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _auth_service(request: Request) -> AuthService:
    return request.app.state.auth


async def get_current_user(request: Request) -> AuthUser | None:
    """Usuario autenticado a partir de la cookie de sesión, o None si no hay
    sesión válida — independiente de si el modo protegido está activo (así
    la atribución de autoría es exacta incluso en transiciones de modo)."""
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        return None
    return await _auth_service(request).resolve_session(token)


CurrentUserDep = Annotated[AuthUser | None, Depends(get_current_user)]


async def require_auth(request: Request, current_user: CurrentUserDep) -> AuthUser | None:
    """Exige sesión válida SOLO si el sistema está en modo protegido (CAMBIO 6:
    al menos un admin habilitado). En modo abierto deja pasar sin más — la
    monitorización y también las acciones de red siguen abiertas, tal como
    funcionaba antes de que existiera ningún usuario."""
    if not await _auth_service(request).is_protected_mode():
        return current_user
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return current_user


RequireAuthDep = Annotated[AuthUser | None, Depends(require_auth)]


async def require_manager(request: Request, current_user: RequireAuthDep) -> AuthUser | None:
    """Acciones sobre la red (ADR 0029): gestor o admin. Rol `user` = solo
    lectura + sus favoritos/grupo personal. Modo abierto: pasa todo (igual que
    antes de que existieran usuarios)."""
    if not await _auth_service(request).is_protected_mode():
        return current_user
    if current_user is None or not current_user.can_manage:
        raise HTTPException(status_code=403, detail="Requiere rol de gestor o administrador")
    return current_user


RequireManagerDep = Annotated[AuthUser | None, Depends(require_manager)]


async def require_user(current_user: CurrentUserDep) -> AuthUser:
    """Funciones personales (favoritos, grupo del usuario): exigen una cuenta
    real incluso en modo abierto — no hay a quién atribuirlas sin sesión."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return current_user


RequireUserDep = Annotated[AuthUser, Depends(require_user)]


async def require_admin(request: Request, current_user: RequireAuthDep) -> AuthUser | None:
    """Gestión de usuarios (CAMBIO 7): en modo protegido exige is_admin. En
    modo abierto deja pasar a TODO el mundo — es como se hace el bootstrap del
    primer usuario, y un usuario logueado no puede tener menos permisos que un
    anónimo (antes un no-admin con sesión recibía 403 que podía saltarse
    cerrando sesión: incoherente, no una barrera real)."""
    if not await _auth_service(request).is_protected_mode():
        return current_user
    if current_user is None or not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Requiere privilegio de administrador")
    return current_user


RequireAdminDep = Annotated[AuthUser | None, Depends(require_admin)]


async def can_see_secrets(request: Request, current_user: CurrentUserDep) -> bool:
    """Los secretos de integraciones/pasarelas solo se devuelven con sesión
    (o en modo abierto, donde no hay nadie a quien ocultárselos)."""
    return current_user is not None or not await _auth_service(request).is_protected_mode()


SecretsVisibleDep = Annotated[bool, Depends(can_see_secrets)]
