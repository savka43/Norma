"""DOCX sources, assets and document schema v2.

Revision ID: 0007_docx_import
Revises: 0006_documents
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_docx_import"
down_revision: str | None = "0006_documents"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    for table in ("documents", "document_versions"):
        op.drop_constraint(op.f(f"ck_{table}_schema_supported"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_schema_supported"), table, "schema_version IN (1, 2)"
        )
    op.create_table(
        "document_imports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("document_versions.id", ondelete="RESTRICT"),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "previous_version_id",
            sa.Uuid(),
            sa.ForeignKey("document_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source", sa.LargeBinary(), nullable=False),
        sa.Column("source_size", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("source_size > 0 AND source_size <= 10485760", name="source_size_valid"),
        sa.CheckConstraint("octet_length(source) = source_size", name="source_size_matches"),
    )
    op.create_index(op.f("ix_document_imports_document_id"), "document_imports", ["document_id"])
    op.create_table(
        "document_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "import_id",
            sa.Uuid(),
            sa.ForeignKey("document_imports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("media_type = 'image/png'", name="media_type_supported"),
        sa.CheckConstraint("width > 0 AND height > 0", name="dimensions_positive"),
    )
    op.create_index(op.f("ix_document_assets_document_id"), "document_assets", ["document_id"])
    for table in ("document_imports", "document_assets"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER immutable_snapshot BEFORE UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_snapshot_update()"
            )
        )


def downgrade() -> None:
    # Never rewrite immutable v2 snapshots just to make a downgrade pass.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM documents WHERE schema_version = 2)
           OR EXISTS (SELECT 1 FROM document_versions WHERE schema_version = 2) THEN
            RAISE EXCEPTION 'Cannot downgrade while schema v2 documents or versions exist';
        END IF;
    END $$""")
    op.drop_table("document_assets")
    op.drop_table("document_imports")
    for table in ("documents", "document_versions"):
        op.drop_constraint(op.f(f"ck_{table}_schema_supported"), table, type_="check")
        op.create_check_constraint(
            op.f(f"ck_{table}_schema_supported"), table, "schema_version = 1"
        )
