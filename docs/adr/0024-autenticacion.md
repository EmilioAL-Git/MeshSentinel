# ADR 0024 — Autenticación: modo abierto/protegido derivado, sesiones por cookie

- Estado: Aceptado (2026-07-14; documenta a posteriori la implementación del
  commit `c29fcde` más el hardening posterior)
- Relacionado con: ADR 0013 (autoría de operaciones admin), roadmap
  «seguridad antes que administración remota» de `docs/architecture.md`

## Contexto

Hasta la v0.9 MeshSentinel funcionaba completamente abierto: cualquier
persona con acceso de red podía tanto monitorizar como encolar operaciones
de administración remota. Con el sistema desplegado en LAN y varias personas
mirándolo, hacía falta autenticación para las acciones que tocan la red,
sin renunciar a dos principios del producto:

- **La monitorización es abierta**: todos los GET (nodos, mapa, dashboard,
  registro de actividad) siguen sin exigir sesión. Un NOC se mira; solo
  actuar requiere identidad.
- **Cero fricción hasta que se necesita**: una instalación de laboratorio o
  personal no debe obligar a crear usuarios.

## Decisión

1. **Modo abierto/protegido sin flag de entorno**: `is_protected_mode()` es
   verdadero si existe al menos un `auth_users` con `is_admin=True` y
   `enabled=True`. Sin admins habilitados el sistema entero se comporta como
   antes de existir usuarios. Si el único admin se deshabilita o borra, el
   sistema **vuelve a modo abierto entero**: es la válvula de seguridad
   contra quedarse fuera, no un error.
2. **Bootstrap abierto (riesgo asumido)**: en modo abierto, `POST
   /auth/users` no exige nada y el primer usuario creado es SIEMPRE admin.
   Consecuencia aceptada: cualquiera con acceso de red a una instancia aún
   abierta puede crear el primer admin y «cerrar» el sistema a los demás.
   MeshSentinel se despliega en LAN de confianza; si esto deja de ser cierto,
   el bootstrap deberá moverse a un canal privilegiado (CLI/env), no
   parchearse con heurísticas.
3. **Sin RBAC**: la única distinción es `is_admin`, que gatea exclusivamente
   la gestión de usuarios — nunca las operaciones sobre la red. En modo
   abierto la gestión de usuarios queda abierta para todos por coherencia
   (un usuario logueado no puede tener menos permisos que un anónimo).
4. **Qué exige sesión en modo protegido** (`RequireAuthDep`): todo lo que
   modifica la red o el comportamiento del sistema — operaciones admin,
   lotes, config, perfiles, favoritos/ignorados remotos, gestión de
   gateways, y reglas/canales de alertas (los canales además provocan POST
   del backend a URLs arbitrarias). Queda abierto a propósito: el ACK de
   alertas (triaje, no configuración) y la organización local de nodos
   (favoritos/etiquetas/grupos/tipo, incluida la asignación masiva) — no
   tocan la malla. `GET /auth/login-log` es la excepción entre los GET:
   contiene IPs/user-agents y exige sesión SIEMPRE, incluso en modo abierto.
5. **Sesiones**: cookie `HttpOnly` + `SameSite=Lax` (mitigación CSRF) con
   token aleatorio de 32 bytes guardado **hasheado** (SHA-256) en
   `auth_sessions`. Expiración deslizante (`NOC_SESSION_IDLE_HOURS`, 12 h)
   con tope absoluto (`NOC_SESSION_MAX_DAYS`, 7 d). La renovación deslizante
   se escribe como máximo una vez por minuto (throttle) para no convertir el
   polling del frontend en un flujo de escrituras en SQLite. Cada login poda
   las sesiones caducadas de todos los usuarios. Cambiar la contraseña o
   deshabilitar al usuario invalida sus sesiones.
6. **`NOC_COOKIE_SECURE=false` por defecto**: el stack sirve HTTP plano
   (nginx :80, sin TLS); una cookie `Secure` sería rechazada por el
   navegador desde cualquier host que no sea localhost y el login quedaría
   roto en silencio. Con TLS delante debe ponerse a `true` SIEMPRE.
7. **Contraseñas**: bcrypt (límite duro de 72 bytes: se rechaza al crear y
   al verificar, nunca se trunca), mínimo `NOC_PASSWORD_MIN_LENGTH` (10).
   El login verifica contra un hash de sacrificio cuando el username no
   existe (mismo coste bcrypt → sin oráculo de enumeración por timing).
8. **Rate limit de login en Redis**: contadores por username
   (`NOC_LOGIN_RATE_LIMIT_PER_USERNAME`, 5) y por IP
   (`NOC_LOGIN_RATE_LIMIT_PER_IP`, 20) con ventana de 15 min. La IP se toma
   de `X-Real-IP`, que **solo es fiable fijada por el nginx del stack**: por
   eso los puertos directos de dev (backend :8000, y de paso postgres/redis)
   se ligan a 127.0.0.1 en `docker-compose.dev.yml`.
9. **Auditoría**: `auth_login_log` registra login ok/fallido, rate limit,
   usuario deshabilitado, logout y expiración de sesión, con IP y
   user-agent. La autoría de operaciones/lotes se congela en
   `actor_username`/`actor_display_name` (borrar el usuario solo libera la
   FK `actor_id`, mismo patrón SQLite del resto del proyecto).

## Consecuencias

- El frontend no necesita saber nada por adelantado: un interceptor global
  de 401 abre el modal de login y `GET /auth/me` expone
  `protected_mode`/usuario actual.
- El mensaje «usuario deshabilitado» del login solo se muestra con
  credenciales correctas: no es un oráculo de enumeración explotable.
- La comparación de modo protegido se cachea en memoria por proceso y se
  invalida en cada mutación de usuarios; con un único proceso backend es
  suficiente.
