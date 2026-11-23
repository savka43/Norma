"""durable plagiarism checks

Revision ID: 0010_plagiarism_checks
Revises: 0009_stage_review
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_plagiarism_checks"
down_revision: str | Sequence[str] | None = "0009_stage_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plagiarism_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("external_id", sa.Integer(), nullable=True),
        sa.Column(
            "result", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("error_detail", sa.String(length=1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_id", sa.Uuid(), nullable=True),
        sa.Column("claim_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'completed') = (result IS NOT NULL)",
            name=op.f("ck_plagiarism_checks_result_matches"),
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name=op.f("ck_plagiarism_checks_error_matches"),
        ),
        sa.CheckConstraint(
            "(status IN ('completed', 'failed')) = (finished_at IS NOT NULL)",
            name=op.f("ck_plagiarism_checks_finished_matches"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'uploading', 'uploaded', 'starting', "
            "'checking', 'completed', 'failed')",
            name=op.f("ck_plagiarism_checks_status_allowed"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('uploaded', 'starting', 'checking', 'completed') "
            "OR (external_id IS NOT NULL AND external_id > 0)",
            name=op.f("ck_plagiarism_checks_external_id_required"),
        ),
        sa.CheckConstraint(
            "(claim_id IS NULL) = (claim_until IS NULL)",
            name=op.f("ck_plagiarism_checks_claim_pair"),
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            name=op.f("fk_plagiarism_checks_requested_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["document_versions.id"],
            name=op.f("fk_plagiarism_checks_version_id_document_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plagiarism_checks")),
    )
    op.create_index(
        "ix_plagiarism_checks_due",
        "plagiarism_checks",
        ["next_run_at", "id"],
        unique=False,
        postgresql_where=sa.text("status NOT IN ('completed', 'failed')"),
    )
    op.create_index(
        "ix_plagiarism_checks_version_created",
        "plagiarism_checks",
        ["version_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "uq_plagiarism_checks_active_version",
        "plagiarism_checks",
        ["version_id"],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('completed', 'failed')"),
    )
    op.execute("""CREATE FUNCTION protect_plagiarism_check() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status IN ('completed', 'failed') THEN
                RAISE EXCEPTION 'Finished plagiarism checks are immutable' USING ERRCODE = '23514';
            END IF;
            IF ROW(NEW.id, NEW.version_id, NEW.requested_by_id, NEW.created_at)
                IS DISTINCT FROM ROW(OLD.id, OLD.version_id, OLD.requested_by_id, OLD.created_at)
                OR (OLD.external_id IS NOT NULL
                    AND NEW.external_id IS DISTINCT FROM OLD.external_id)
            THEN
                RAISE EXCEPTION 'Plagiarism check source is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
    $$""")
    op.execute(
        "CREATE TRIGGER immutable_plagiarism_check BEFORE UPDATE ON plagiarism_checks "
        "FOR EACH ROW EXECUTE FUNCTION protect_plagiarism_check()"
    )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM plagiarism_checks) THEN
            RAISE EXCEPTION 'Cannot downgrade while plagiarism checks exist';
        END IF;
    END $$""")
    op.drop_table("plagiarism_checks")
    op.execute("DROP FUNCTION protect_plagiarism_check()")
