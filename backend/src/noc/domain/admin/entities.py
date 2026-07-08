"""Entidades del pipeline de operaciones remotas (Módulo 1, diseño §4)."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

OperationStatus = Literal[
    "pending", "queued", "running", "succeeded", "failed", "timeout", "cancelled"
]

# M1.1 solo lectura; con los SET (M1.4) se añadirán succeeded_unconfirmed y verify_failed
TERMINAL_STATUSES: tuple[OperationStatus, ...] = ("succeeded", "failed", "timeout", "cancelled")
IN_FLIGHT_STATUSES: tuple[OperationStatus, ...] = ("queued", "running")


@dataclass(slots=True)
class AdminOperation:
    target_node_id: str
    gateway_id: str
    operation_type: str
    params: dict[str, Any] = field(default_factory=dict)
    status: OperationStatus = "pending"
    priority: int = 100
    attempts: int = 0
    max_attempts: int = 3
    timeout_seconds: int = 120
    next_attempt_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_by: str = "admin"
    id: int | None = None
    created_at: datetime | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES
