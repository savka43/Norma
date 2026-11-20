"""document storage leases versions and templates

Revision ID: 0006_documents
Revises: 0005_theses_stages
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_documents"
down_revision: str | None = "0005_theses_stages"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "formatting_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supervisor_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("latest_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "latest_version > 0", name=op.f("ck_formatting_templates_version_positive")
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0 AND name = btrim(name)",
            name=op.f("ck_formatting_templates_name_trimmed"),
        ),
        sa.ForeignKeyConstraint(
            ["supervisor_id"],
            ["users.id"],
            name=op.f("fk_formatting_templates_supervisor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_formatting_templates")),
    )
    op.create_index(
        op.f("ix_formatting_templates_supervisor_id"),
        "formatting_templates",
        ["supervisor_id"],
        unique=False,
    )
    op.create_table(
        "formatting_template_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "number > 0", name=op.f("ck_formatting_template_versions_number_positive")
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["formatting_templates.id"],
            name=op.f("fk_formatting_template_versions_template_id_formatting_templates"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_formatting_template_versions")),
        sa.UniqueConstraint(
            "template_id", "number", name=op.f("uq_formatting_template_versions_template_id")
        ),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("thesis_id", sa.Uuid(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_version_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("template_version_id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "last_version_number >= 0", name=op.f("ck_documents_version_number_nonnegative")
        ),
        sa.CheckConstraint("revision > 0", name=op.f("ck_documents_revision_positive")),
        sa.CheckConstraint("schema_version = 1", name=op.f("ck_documents_schema_supported")),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["formatting_template_versions.id"],
            name=op.f("fk_documents_template_version_id_formatting_template_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["thesis_id"],
            ["theses.id"],
            name=op.f("fk_documents_thesis_id_theses"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("thesis_id", name=op.f("uq_documents_thesis_id")),
    )
    op.create_table(
        "document_edit_leases",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("lease_id", sa.Uuid(), nullable=False),
        sa.Column("holder_id", sa.Uuid(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at > acquired_at", name=op.f("ck_document_edit_leases_positive_lifetime")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_edit_leases_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["holder_id"],
            ["users.id"],
            name=op.f("fk_document_edit_leases_holder_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("document_id", name=op.f("pk_document_edit_leases")),
        sa.UniqueConstraint("lease_id", name=op.f("uq_document_edit_leases_lease_id")),
    )
    op.create_table(
        "document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("document_revision", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("template_version_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("comment", sa.String(length=2000), nullable=True),
        sa.Column("restored_from_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "number > 0 AND document_revision > 0",
            name=op.f("ck_document_versions_numbers_positive"),
        ),
        sa.CheckConstraint(
            "schema_version = 1", name=op.f("ck_document_versions_schema_supported")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_document_versions_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_versions_document_id_documents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["restored_from_id"],
            ["document_versions.id"],
            name=op.f("fk_document_versions_restored_from_id_document_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["template_version_id"],
            ["formatting_template_versions.id"],
            name=op.f("fk_document_versions_template_version_id_formatting_template_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_versions")),
        sa.UniqueConstraint("document_id", "number", name=op.f("uq_document_versions_document_id")),
    )
    # Version snapshots are append-only through the API; PostgreSQL also rejects UPDATE.
    op.execute("""
        CREATE FUNCTION reject_snapshot_update() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Version snapshots are immutable' USING ERRCODE = '23514';
        END;
        $$
    """)
    for table in ("document_versions", "formatting_template_versions"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER immutable_snapshot BEFORE UPDATE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_snapshot_update()"
            )
        )


def downgrade() -> None:
    op.drop_table("document_versions")
    op.drop_table("document_edit_leases")
    op.drop_table("documents")
    op.drop_table("formatting_template_versions")
    op.drop_index(op.f("ix_formatting_templates_supervisor_id"), table_name="formatting_templates")
    op.drop_table("formatting_templates")
    op.execute("DROP FUNCTION reject_snapshot_update()")
