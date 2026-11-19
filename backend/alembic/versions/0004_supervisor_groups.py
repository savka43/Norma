"""Create supervisor groups and unique student memberships.

Revision ID: 0004_supervisor_groups
Revises: 0003_auth_sessions
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0004_supervisor_groups"
down_revision: str | None = "0003_auth_sessions"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "supervisor_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supervisor_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0 AND name = btrim(name)",
            name=op.f("ck_supervisor_groups_name_trimmed"),
        ),
        sa.CheckConstraint(
            "academic_year BETWEEN 1 AND 9998",
            name=op.f("ck_supervisor_groups_academic_year_range"),
        ),
        sa.ForeignKeyConstraint(
            ["supervisor_id"],
            ["users.id"],
            name=op.f("fk_supervisor_groups_supervisor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supervisor_groups")),
    )
    op.create_index("ix_supervisor_groups_supervisor_id", "supervisor_groups", ["supervisor_id"])
    op.create_table(
        "group_memberships",
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["users.id"],
            name=op.f("fk_group_memberships_student_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["supervisor_groups.id"],
            name=op.f("fk_group_memberships_group_id_supervisor_groups"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("student_id", name=op.f("pk_group_memberships")),
    )
    op.create_index("ix_group_memberships_group_id", "group_memberships", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_group_memberships_group_id", table_name="group_memberships")
    op.drop_table("group_memberships")
    op.drop_index("ix_supervisor_groups_supervisor_id", table_name="supervisor_groups")
    op.drop_table("supervisor_groups")
