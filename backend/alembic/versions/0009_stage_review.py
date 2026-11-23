"""Pinned stage submissions, review history and anchored comments."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_stage_review"
down_revision: str | None = "0008_semantic_captions"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("thesis_stages", sa.Column("submitted_version_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_thesis_stages_submitted_version_id_document_versions"),
        "thesis_stages",
        "document_versions",
        ["submitted_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "stage_submissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "stage_id",
            sa.Uuid(),
            sa.ForeignKey("thesis_stages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("document_versions.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "submitted_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("thesis_revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("stage_id", "thesis_revision"),
        sa.CheckConstraint("thesis_revision > 0", name="revision_positive"),
    )
    op.create_index(op.f("ix_stage_submissions_stage_id"), "stage_submissions", ["stage_id"])
    op.add_column("stage_events", sa.Column("version_id", sa.Uuid(), nullable=True))
    op.add_column("stage_events", sa.Column("reason", sa.String(2000), nullable=True))
    op.create_foreign_key(
        op.f("fk_stage_events_version_id_document_versions"),
        "stage_events",
        "document_versions",
        ["version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    for name in ("kind_allowed", "before_matches_kind"):
        op.drop_constraint(op.f(f"ck_stage_events_{name}"), "stage_events", type_="check")
    op.create_check_constraint(
        op.f("ck_stage_events_kind_allowed"),
        "stage_events",
        "kind IN ('created', 'updated', 'submitted', 'changes_requested', 'confirmed', 'resumed')",
    )
    op.create_check_constraint(
        op.f("ck_stage_events_before_matches_kind"),
        "stage_events",
        "(kind = 'created' AND before IS NULL) OR (kind <> 'created' AND before IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_stage_events_workflow_version"),
        "stage_events",
        "kind IN ('created', 'updated') OR version_id IS NOT NULL",
    )
    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("document_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "author_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("body", sa.String(10000), nullable=False),
        sa.Column("quote", sa.String(10000), nullable=False),
        sa.Column("anchor", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(10), server_default="open", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="status_allowed"),
        sa.CheckConstraint("revision > 0", name="revision_positive"),
        sa.CheckConstraint("length(btrim(body)) > 0", name="body_nonempty"),
        sa.CheckConstraint("length(quote) > 0", name="quote_nonempty"),
    )
    op.create_index(op.f("ix_comments_version_id"), "comments", ["version_id"])
    op.create_table(
        "comment_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "comment_id",
            sa.Uuid(),
            sa.ForeignKey("comments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("comment_id", "revision"),
        sa.CheckConstraint("revision > 0", name="revision_positive"),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="status_allowed"),
    )
    op.create_index(op.f("ix_comment_events_comment_id"), "comment_events", ["comment_id"])
    for table in ("stage_submissions", "stage_events", "comment_events"):
        op.execute(
            f"CREATE TRIGGER immutable_snapshot BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_snapshot_update()"
        )
    op.execute("""CREATE FUNCTION protect_comment_source() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (to_jsonb(NEW) - 'status' - 'revision') IS DISTINCT FROM
               (to_jsonb(OLD) - 'status' - 'revision') THEN
                RAISE EXCEPTION 'Comment source is immutable' USING ERRCODE = '23514';
            END IF;
            IF NOT (OLD.status = 'open' AND NEW.status = 'resolved'
                    AND NEW.revision = OLD.revision + 1) THEN
                RAISE EXCEPTION 'Invalid comment transition' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
    $$""")
    op.execute(
        "CREATE TRIGGER immutable_comment_source BEFORE UPDATE ON comments "
        "FOR EACH ROW EXECUTE FUNCTION protect_comment_source()"
    )


def downgrade() -> None:
    # Never silently discard review decisions or comment history during rollback.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM stage_submissions) OR EXISTS (SELECT 1 FROM comments)
           OR EXISTS (SELECT 1 FROM stage_events WHERE kind NOT IN ('created', 'updated')) THEN
            RAISE EXCEPTION 'Cannot downgrade while review history exists';
        END IF;
    END $$""")
    op.drop_table("comment_events")
    op.drop_table("comments")
    op.execute("DROP FUNCTION protect_comment_source()")
    op.execute("DROP TRIGGER immutable_snapshot ON stage_events")
    for name in ("kind_allowed", "before_matches_kind", "workflow_version"):
        op.drop_constraint(op.f(f"ck_stage_events_{name}"), "stage_events", type_="check")
    op.create_check_constraint(
        op.f("ck_stage_events_kind_allowed"), "stage_events", "kind IN ('created', 'updated')"
    )
    op.create_check_constraint(
        op.f("ck_stage_events_before_matches_kind"),
        "stage_events",
        "(kind = 'created' AND before IS NULL) OR (kind = 'updated' AND before IS NOT NULL)",
    )
    op.drop_column("stage_events", "reason")
    op.drop_column("stage_events", "version_id")
    op.drop_table("stage_submissions")
    op.drop_column("thesis_stages", "submitted_version_id")
