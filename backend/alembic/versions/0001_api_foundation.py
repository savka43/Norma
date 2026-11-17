"""Establish a migration baseline before adding domain tables.

Revision ID: 0001_api_foundation
Revises:
"""

revision: str = "0001_api_foundation"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Domain tables are introduced with their corresponding API features.
    pass


def downgrade() -> None:
    pass
