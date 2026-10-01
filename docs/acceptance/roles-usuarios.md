# Guía de aceptación — Roles y espacio personal (ADR 0029)

Requiere rebuild del backend (migración 0028 se aplica sola).

1. Ajustes → Usuarios: crear un usuario de cada rol (Administrador, Gestor, Usuario). La columna «Rol» es un selector.
2. **Admin**: ve Usuarios y Gateways editables.
3. **Gestor**: puede crear lotes/operaciones/reglas/grupos; Ajustes sin pestaña «Usuarios»; Gateways en solo lectura (POST/PUT → 403).
4. **Usuario**: sin lotes/borrado/etiquetas/tipo en la barra de Flota, Inspector con pestañas bloqueadas (🔒 rol de gestor), sin 👁. Sí: ☆ favorito y ◇ «Mi Grupo del usuario».
5. Favoritos: marcar ☆ con un usuario; entrar con otro → no aparece marcado.
6. Grupo del usuario: selector de grupo → «Crear mi Grupo del usuario»; añadir nodos desde Flota («Grupo…») o el Inspector; el mapa/Flota/Centro se filtran como con cualquier grupo. Otra cuenta (incluso admin) no lo ve. Cerrar sesión → el filtro desaparece. Reabrir → no arranca en él.
7. Sin login (modo protegido): lectura como antes; ☆ pide login.
8. Ajustes → Grupo al arrancar: el Grupo del usuario no es elegible (422).
