# ADR 0029 — Roles de usuario y espacio personal (favoritos + Grupo del usuario)

Fecha: 2026-10-01 · Estado: aceptado · Sustituye el «sin RBAC» de ADR 0024.

## Contexto
Hasta ahora todo usuario autenticado podía operar la red; `is_admin` solo
gateaba la gestión de usuarios. Se pide separar niveles de control y dar a
cada cuenta su propio espacio (favoritos y un grupo) sin afectar a los demás.

## Decisión
1. **Roles** (`auth_users.role`): `admin` (todo), `manager` (todo salvo gestión
   de usuarios y ajustes de gateways), `user` (solo lectura + espacio
   personal). Sin sesión: igual que antes (modo abierto = todo abierto; modo
   protegido = lectura). `is_admin` se conserva en BD derivada de `role` para
   no tocar `count_enabled_admins` ni la válvula anti-bloqueo (ADR 0024).
2. **Dependencias FastAPI**: `RequireManagerDep` (gestor/admin; sustituye a
   `RequireAuthDep` y a los `RequireAdminDep` que no eran de usuarios),
   `RequireAdminDep` solo para `/auth/users`, `/gateways/*` (mutaciones y
   descubrimiento) y backup/restauración de configuración, `RequireUserDep`
   (cuenta real incluso en modo abierto) para lo personal. El ACK de alertas
   también exige gestor (el rol `user` no actúa sobre la red).
3. **Favoritos personales** (`user_favorites`): sustituyen a `nodes.is_favorite`
   (la migración 0028 copia los globales a cada usuario existente y los
   limpia). `is_favorite` en `GET /nodes[/{id}]` se rellena por usuario; sin
   sesión nadie tiene favoritos. El filtro `favorite` de lotes se rechaza
   (ambiguo: ¿de quién?) — se selecciona por `node_ids`. **`is_ignored` sigue
   global** (excluye del Dashboard y del motor de alertas: no puede ser
   personal) y solo lo gestiona gestor/admin.
4. **Grupo del usuario** (`groups.owner_user_id`, único): uno por cuenta,
   creado bajo demanda (`POST /groups/mine`). Privado: solo su dueño lo ve
   (ni admin) y lo edita; los ajenos responden 404. Nunca predeterminado
   (rechazado como grupo de arranque y no se recuerda en el navegador). No
   admite pasarela preferida ni borrado. Nombre interno
   `Grupo del usuario (@username)` por el UNIQUE de `groups.name`; la API
   muestra «Grupo del usuario». Al borrar el usuario se borran favoritos y
   grupo (explícito, SQLite no cascada).

## Consecuencias / riesgos asumidos
- Usuarios existentes no admin → `manager` (conservan su poder previo).
- Visibilidad por id: `nodes?group_id=` con el id de un grupo personal ajeno
  funciona si se adivina (solo membresía de nodos, no hay secretos).
- Roles adicionales prometidos («luego añadiremos más») encajan en `ROLES` y
  en una nueva dependencia sin rediseño.
