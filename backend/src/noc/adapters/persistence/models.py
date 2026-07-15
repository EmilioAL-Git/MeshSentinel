from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from noc.adapters.persistence.database import Base


class GatewayModel(Base):
    __tablename__ = "gateways"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # ── Estado runtime (heartbeat gateway.status) ──────────────────────────
    status: Mapped[str] = mapped_column(String(16))
    transport: Mapped[str] = mapped_column(String(16))
    local_node_id: Mapped[str | None] = mapped_column(String(16))
    detail: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Caché no durable del nodo local, refrescada en cada conexión (M5)
    local_short_name: Mapped[str | None] = mapped_column(String(8))
    local_long_name: Mapped[str | None] = mapped_column(String(64))
    local_hw_model: Mapped[str | None] = mapped_column(String(32))
    local_firmware_version: Mapped[str | None] = mapped_column(String(32))
    # ── Configuración gestionada desde la aplicación (M5, ADR 0021) ────────
    name: Mapped[str | None] = mapped_column(String(128))
    managed: Mapped[bool] = mapped_column(Boolean, default=False)
    transport_type: Mapped[str | None] = mapped_column(String(16))
    connection_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    desired_status: Mapped[str] = mapped_column(String(16), default="disconnected")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NodeModel(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    node_num: Mapped[int | None] = mapped_column(BigInteger)
    short_name: Mapped[str | None] = mapped_column(String(8))
    long_name: Mapped[str | None] = mapped_column(String(64))
    hw_model: Mapped[str | None] = mapped_column(String(32))
    firmware_version: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str | None] = mapped_column(String(32))
    snr: Mapped[float | None] = mapped_column(Float)
    rssi: Mapped[int | None] = mapped_column(Integer)
    hops_away: Mapped[int | None] = mapped_column(Integer)
    via_mqtt: Mapped[bool] = mapped_column(Boolean, default=False)
    public_key: Mapped[str | None] = mapped_column(Text)
    gateway_id: Mapped[str | None] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Metadatos del NOC (M1.2) — nunca provienen de la malla ni la modifican
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    is_ignored: Mapped[bool] = mapped_column(Boolean, default=False)
    # Selección inteligente de gateway (Nivel 2): sin FK, mismo criterio que
    # gateway_id de esta misma tabla (puede referenciar una pasarela sin fila propia aún).
    preferred_gateway_id: Mapped[str | None] = mapped_column(String(64))
    # Clasificación manual (Inspector, Organización): NULL = "Automático".
    node_type_override: Mapped[str | None] = mapped_column(String(16))


class NodeGatewayLinkModel(Base):
    """N:M nodo<->pasarela (M6.1): estado actual, no histórico.

    `gateway_id` no lleva ForeignKey a `gateways.id`, igual que `nodes.
    gateway_id` y `admin_operations.gateway_id`: un evento del gateway puede
    llegar antes de que exista fila en `gateways` (que solo se crea al
    recibir el primer `gateway.status`).
    """

    __tablename__ = "node_gateway_links"

    node_id: Mapped[str] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True
    )
    gateway_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    rssi: Mapped[int | None] = mapped_column(Integer)
    snr: Mapped[float | None] = mapped_column(Float)
    hops_away: Mapped[int | None] = mapped_column(Integer)
    via_mqtt: Mapped[bool] = mapped_column(Boolean, default=False)
    first_heard_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_heard_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TagModel(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    color: Mapped[str | None] = mapped_column(String(16))


class NodeTagModel(Base):
    __tablename__ = "node_tags"

    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class GroupModel(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="static")
    filter_expr: Mapped[str | None] = mapped_column(Text)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    # Selección inteligente de gateway (Nivel 3), sin FK (mismo criterio que nodes.gateway_id).
    preferred_gateway_id: Mapped[str | None] = mapped_column(String(64))


class GroupMemberModel(Base):
    __tablename__ = "group_members"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True)


class PositionModel(Base):
    __tablename__ = "node_positions"
    __table_args__ = (Index("ix_node_positions_node_received", "node_id", "received_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    altitude_m: Mapped[int | None] = mapped_column(Integer)
    precision_bits: Mapped[int | None] = mapped_column(Integer)
    sats_in_view: Mapped[int | None] = mapped_column(Integer)
    position_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gateway_id: Mapped[str | None] = mapped_column(String(64))


class NeighborModel(Base):
    """Enlace nodo<->nodo real (NEIGHBORINFO_APP), append-only.

    Mismo patrón que `PositionModel`/`TelemetryModel`: "lo último" por par
    (node_id, neighbor_id) se resuelve con row_number(), nunca se pisa.
    """

    __tablename__ = "node_neighbors"
    __table_args__ = (Index("ix_node_neighbors_node_received", "node_id", "received_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    neighbor_id: Mapped[str] = mapped_column(String(16), nullable=False)
    snr: Mapped[float | None] = mapped_column(Float)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gateway_id: Mapped[str | None] = mapped_column(String(64))


class AlertRuleModel(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    rule_type: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    threshold: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=0)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Reglas por grupo (§1.3 opción A): sin FK, mismo criterio que
    # nodes.preferred_gateway_id — un grupo borrado deja la regla sin
    # coincidencias (degradación segura), nunca un error de integridad.
    group_id: Mapped[int | None] = mapped_column(Integer)
    # Reglas por nodo individual: mutuamente excluyente con group_id (validado
    # en la API). Mismo criterio sin FK que group_id: un nodo borrado deja la
    # regla sin coincidencias, nunca un error de integridad.
    node_id: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AlertModel(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_status_fired", "status", "fired_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id"), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(128))
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    message: Mapped[str] = mapped_column(Text)
    correlation_key: Mapped[str | None] = mapped_column(String(128), index=True)
    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminBatchModel(Base):
    __tablename__ = "admin_batches"
    __table_args__ = (Index("ix_admin_batches_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    operation_type: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    node_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    scope_description: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    # Legado (auth): sustituido por actor_* para operaciones nuevas — se
    # conserva sin escritura significativa para no perder el histórico previo
    # a la fase de autenticación (resolve_actor_label cae aquí si no hay actor).
    created_by: Mapped[str] = mapped_column(String(64), default="admin")
    actor_type: Mapped[str] = mapped_column(String(16), default="system")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)
    actor_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminOperationModel(Base):
    __tablename__ = "admin_operations"
    __table_args__ = (
        Index("ix_admin_ops_status_next", "status", "next_attempt_at"),
        Index("ix_admin_ops_node_created", "target_node_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("admin_batches.id"), nullable=True, index=True
    )
    target_node_id: Mapped[str] = mapped_column(String(16))
    gateway_id: Mapped[str] = mapped_column(String(64))
    operation_type: Mapped[str] = mapped_column(String(32))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text)
    # Legado (auth): ver comentario equivalente en AdminBatchModel.
    created_by: Mapped[str] = mapped_column(String(64), default="admin")
    actor_type: Mapped[str] = mapped_column(String(16), default="system")
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)
    actor_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    gateway_note: Mapped[str | None] = mapped_column(Text)


class ConfigProfileModel(Base):
    __tablename__ = "config_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConfigProfileVersionModel(Base):
    __tablename__ = "config_profile_versions"
    __table_args__ = (
        UniqueConstraint("profile_id", "version", name="uq_profile_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("config_profiles.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    sections: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    comment: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NotificationProviderModel(Base):
    """Instancia de proveedor configurada (antes "notification_channels" /
    canal_type — renombrado al introducir el canal LÓGICO, ver
    NotificationChannelModel más abajo)."""

    __tablename__ = "notification_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    provider: Mapped[str] = mapped_column(String(32))
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NotificationChannelModel(Base):
    """Canal LÓGICO (p.ej. "Operadores", "Guardia") que las reglas conocen.
    Agrupa 1+ proveedores vía notification_channel_providers."""

    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NotificationChannelProviderModel(Base):
    __tablename__ = "notification_channel_providers"

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="CASCADE"), primary_key=True
    )
    provider_id: Mapped[int] = mapped_column(
        ForeignKey("notification_providers.id", ondelete="CASCADE"), primary_key=True
    )


class AlertRuleChannelModel(Base):
    __tablename__ = "alert_rule_channels"

    rule_id: Mapped[int] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), primary_key=True
    )
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="CASCADE"), primary_key=True
    )


class ActivityLogModel(Base):
    """Registro persistente del diario operativo (fase de hardening).

    Guarda el MISMO envelope `activity.event` que viaja por el WebSocket:
    `payload` es el `ActivityEvent.to_payload()` intacto, de forma que el
    frontend puede sembrar su buffer con `toEntry()` sin un parser aparte.
    Las columnas extraídas (node_id, source, severity, created_at) existen
    solo para filtrar/podar sin deserializar JSON.
    """

    __tablename__ = "activity_log"
    __table_args__ = (
        Index("ix_activity_log_node_created", "node_id", "created_at"),
        Index("ix_activity_log_internal_type_created", "internal_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36))
    gateway_id: Mapped[str | None] = mapped_column(String(64))
    node_id: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    severity: Mapped[str] = mapped_column(String(16))
    # Tipo de paquete decodificado (p.ej. "TRACEROUTE_APP"), extraído de
    # payload.internal_type al insertar — permite filtrar sin deserializar
    # JSON (p.ej. reconstruir rutas de traceroute para el mapa).
    internal_type: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TelemetryModel(Base):
    __tablename__ = "node_telemetry"
    __table_args__ = (Index("ix_node_telemetry_node_received", "node_id", "received_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16))
    battery_level: Mapped[int | None] = mapped_column(Integer)
    voltage: Mapped[float | None] = mapped_column(Float)
    channel_utilization: Mapped[float | None] = mapped_column(Float)
    air_util_tx: Mapped[float | None] = mapped_column(Float)
    uptime_seconds: Mapped[int | None] = mapped_column(BigInteger)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    relative_humidity: Mapped[float | None] = mapped_column(Float)
    barometric_pressure_hpa: Mapped[float | None] = mapped_column(Float)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    gateway_id: Mapped[str | None] = mapped_column(String(64))


class ChatMessageModel(Base):
    """Chat: monitor de TEXT_MESSAGE_APP (mismo paquete que narra
    `activity_log`, tabla propia por las columnas estructuradas que necesita
    el selector de canales/DM y por ser el punto de apoyo de una futura fase
    de envío — ver `domain/chat/entities.py:ChatMessage`)."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_channel_received", "channel_index", "received_at"),
        Index("ix_chat_messages_from_received", "from_node_id", "received_at"),
        Index("ix_chat_messages_to_received", "to_node_id", "received_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id"), nullable=False)
    to_node_id: Mapped[str | None] = mapped_column(String(16))
    channel_index: Mapped[int] = mapped_column(Integer, default=0)
    channel_name: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(String(512))
    gateway_id: Mapped[str | None] = mapped_column(String(64))
    rssi: Mapped[int | None] = mapped_column(Integer)
    snr: Mapped[float | None] = mapped_column(Float)
    hops_away: Mapped[int | None] = mapped_column(Integer)
    hop_limit: Mapped[int | None] = mapped_column(Integer)
    hop_start: Mapped[int | None] = mapped_column(Integer)
    encrypted: Mapped[bool | None] = mapped_column(Boolean)
    packet_id: Mapped[int | None] = mapped_column(BigInteger)
    direction: Mapped[str] = mapped_column(String(8), default="inbound")
    delivery_status: Mapped[str | None] = mapped_column(String(16))
    reply_to_id: Mapped[int | None] = mapped_column(ForeignKey("chat_messages.id", ondelete="SET NULL"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("auth_users.id", ondelete="SET NULL"))
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AuthUserModel(Base):
    """Usuario de MeshSentinel (auth). Sin RBAC: `is_admin` es el único
    privilegio especial y solo gatea la gestión de usuarios — todas las
    operaciones sobre la red están disponibles para cualquier usuario
    autenticado (ver diseño de autenticación)."""

    __tablename__ = "auth_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(128))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthSessionModel(Base):
    """Sesión opaca (cookie HTTPOnly): solo se guarda el hash del token, nunca
    el token en claro — un volcado de esta tabla no permite secuestrar
    sesiones. Expiración deslizante (`expires_at` se adelanta en cada request
    autenticada válida, hasta un tope absoluto aplicado en AuthService)."""

    __tablename__ = "auth_sessions"
    __table_args__ = (Index("ix_auth_sessions_user", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)


class AuthLoginLogModel(Base):
    """Auditoría de accesos (auth), independiente de `activity_log`: registra
    intentos de login (correctos y fallidos), logout, expiración de sesión,
    usuario deshabilitado y bloqueos por rate limit. No se poda automáticamente
    — es un registro de seguridad, no un diario operativo con memoria acotada."""

    __tablename__ = "auth_login_log"
    __table_args__ = (Index("ix_auth_login_log_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
