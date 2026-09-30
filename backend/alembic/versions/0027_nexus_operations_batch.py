"""JenTastic-Nexus: lotes de operaciones a varios nodos (-node c/u, espaciados)

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-30

Pedido explícito del usuario: controlar flota/grupo desde Flota, con tres
alcances — un nodo (-node), toda la flota Nexus (difusión, ya existía) o
varios nodos SELECCIONADOS (una operación `-node <shortname>` por nodo,
espaciadas en el tiempo, no un único envío). Las operaciones de un mismo
lote comparten `batch_key` (agrupación informal, sin tabla propia — a
diferencia de `admin_batches`, ADR 0016, no hace falta progreso agregado
aquí) y `batch_interval_seconds` (mínimo entre el envío de una y la
siguiente DENTRO del lote, aplicado por el scheduler en
`application/nexus_operations.py`, independiente del `CommandPacer` del
núcleo puro — es una cortesía de producto, no una restricción del
firmware).
"""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("nexus_operations", sa.Column("batch_key", sa.String(32), nullable=True))
    op.add_column("nexus_operations", sa.Column("batch_interval_seconds", sa.Float(), nullable=True))
    op.create_index("ix_nexus_ops_batch_key", "nexus_operations", ["batch_key"])


def downgrade() -> None:
    op.drop_index("ix_nexus_ops_batch_key", table_name="nexus_operations")
    op.drop_column("nexus_operations", "batch_interval_seconds")
    op.drop_column("nexus_operations", "batch_key")
