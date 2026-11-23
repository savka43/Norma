"""Add chapter bindings to schema v4 and preserve the scope of each submission."""

import sqlalchemy as sa

from alembic import op

revision: str = "0011_stage_chapters"
down_revision: str | None = "0010_plagiarism_checks"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    for table in ("documents", "document_versions"):
        op.drop_constraint(op.f(f"ck_{table}_schema_supported"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_schema_supported"), table, "schema_version IN (1, 2, 3, 4)"
        )
    op.add_column(
        "stage_submissions",
        sa.Column("scope", sa.String(8), server_default="document", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_stage_submissions_scope_allowed"),
        "stage_submissions",
        "scope IN ('document', 'chapter')",
    )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM documents WHERE schema_version = 4)
           OR EXISTS (SELECT 1 FROM document_versions WHERE schema_version = 4)
           OR EXISTS (SELECT 1 FROM stage_submissions WHERE scope = 'chapter') THEN
            RAISE EXCEPTION 'Cannot downgrade while schema v4 or chapter submissions exist';
        END IF;
    END $$""")
    op.drop_constraint(
        op.f("ck_stage_submissions_scope_allowed"), "stage_submissions", type_="check"
    )
    op.drop_column("stage_submissions", "scope")
    for table in ("documents", "document_versions"):
        op.drop_constraint(op.f(f"ck_{table}_schema_supported"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_schema_supported"), table, "schema_version IN (1, 2, 3)"
        )
