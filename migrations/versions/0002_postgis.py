"""PostGIS geometry column for regions (PostgreSQL only).

Region boundaries are stored as simplified GeoJSON on every backend. On
PostgreSQL with PostGIS available, a geometry column and spatial index are
added and kept in sync by the seeding step.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("ALTER TABLE regions ADD COLUMN IF NOT EXISTS geom geometry(MultiPolygon, 4326)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_regions_geom ON regions USING GIST (geom)")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_regions_geom")
    op.execute("ALTER TABLE regions DROP COLUMN IF EXISTS geom")
