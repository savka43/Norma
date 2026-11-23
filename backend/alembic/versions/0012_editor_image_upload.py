"""Allow document images inserted directly from the editor."""

from alembic import op

revision: str = "0012_editor_image_upload"
down_revision: str | None = "0011_stage_chapters"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column("document_assets", "import_id", nullable=True)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM document_assets WHERE import_id IS NULL) THEN
            RAISE EXCEPTION 'Cannot downgrade while directly uploaded images exist';
        END IF;
    END $$""")
    op.alter_column("document_assets", "import_id", nullable=False)
