"""theses and stage planning

Revision ID: 0005_theses_stages
Revises: 0004_supervisor_groups
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_theses_stages"
down_revision: str | None = "0004_supervisor_groups"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "theses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("supervisor_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("due_date >= start_date", name=op.f("ck_theses_date_order")),
        sa.CheckConstraint(
            "length(btrim(title)) > 0 AND title = btrim(title)",
            name=op.f("ck_theses_title_trimmed"),
        ),
        sa.CheckConstraint("revision > 0", name=op.f("ck_theses_revision_positive")),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["group_memberships.student_id"],
            name=op.f("fk_theses_student_id_group_memberships"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supervisor_id"],
            ["users.id"],
            name=op.f("fk_theses_supervisor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_theses")),
        sa.UniqueConstraint("student_id", name=op.f("uq_theses_student_id")),
    )
    op.create_index(op.f("ix_theses_supervisor_id"), "theses", ["supervisor_id"], unique=False)
    op.create_table(
        "thesis_stages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thesis_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "in_progress", "in_review", "changes_requested", "completed", name="stage_status"
            ),
            server_default="in_progress",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0 AND name = btrim(name)",
            name=op.f("ck_thesis_stages_name_trimmed"),
        ),
        sa.CheckConstraint("position > 0", name=op.f("ck_thesis_stages_position_positive")),
        sa.ForeignKeyConstraint(
            ["thesis_id"],
            ["theses.id"],
            name=op.f("fk_thesis_stages_thesis_id_theses"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_thesis_stages")),
        sa.UniqueConstraint(
            "thesis_id",
            "position",
            deferrable=True,
            initially="DEFERRED",
            name=op.f("uq_thesis_stages_thesis_id"),
        ),
    )
    op.create_table(
        "stage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("stage_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("thesis_revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'created' AND before IS NULL) OR (kind = 'updated' AND before IS NOT NULL)",
            name=op.f("ck_stage_events_before_matches_kind"),
        ),
        sa.CheckConstraint(
            "kind IN ('created', 'updated')", name=op.f("ck_stage_events_kind_allowed")
        ),
        sa.CheckConstraint("thesis_revision > 0", name=op.f("ck_stage_events_revision_positive")),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_stage_events_actor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stage_id"],
            ["thesis_stages.id"],
            name=op.f("fk_stage_events_stage_id_thesis_stages"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stage_events")),
        sa.UniqueConstraint("stage_id", "thesis_revision", name=op.f("uq_stage_events_stage_id")),
    )
    op.create_index(op.f("ix_stage_events_stage_id"), "stage_events", ["stage_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_stage_events_stage_id"), table_name="stage_events")
    op.drop_table("stage_events")
    op.drop_table("thesis_stages")
    sa.Enum(name="stage_status").drop(op.get_bind())
    op.drop_index(op.f("ix_theses_supervisor_id"), table_name="theses")
    op.drop_table("theses")
