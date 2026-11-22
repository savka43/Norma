"""Semantic captions, document schema v3; existing snapshots stay unchanged."""

from alembic import op

revision: str = "0008_semantic_captions"
down_revision: str | None = "0007_docx_import"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    for table in ("documents", "document_versions"):
        op.drop_constraint(op.f(f"ck_{table}_schema_supported"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_schema_supported"), table, "schema_version IN (1, 2, 3)"
        )


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM documents WHERE schema_version = 3)
           OR EXISTS (SELECT 1 FROM document_versions WHERE schema_version = 3) THEN
            RAISE EXCEPTION 'Cannot downgrade while schema v3 documents or versions exist';
        END IF;
    END $$""")
    for table in ("documents", "document_versions"):
        op.drop_constraint(op.f(f"ck_{table}_schema_supported"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_schema_supported"), table, "schema_version IN (1, 2)"
        )
