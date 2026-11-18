"""Create users with student and supervisor roles.

Revision ID: 0002_users
Revises: 0001_api_foundation
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0002_users"
down_revision: str | None = "0001_api_foundation"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Enum("student", "supervisor", name="user_role"), nullable=False),
        sa.Column("academic_group", sa.String(length=100), nullable=True),
        sa.Column("position", sa.String(length=255), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(btrim(email)) > 0 AND email = btrim(email)", name=op.f("ck_users_email_trimmed")
        ),
        sa.CheckConstraint(
            "length(btrim(full_name)) > 0", name=op.f("ck_users_full_name_not_blank")
        ),
        sa.CheckConstraint(
            "length(btrim(password_hash)) > 0", name=op.f("ck_users_password_hash_not_blank")
        ),
        sa.CheckConstraint(
            "(role = 'student' AND academic_group IS NOT NULL "
            "AND length(btrim(academic_group)) > 0 AND position IS NULL AND department IS NULL) "
            "OR (role = 'supervisor' AND academic_group IS NULL AND position IS NOT NULL "
            "AND length(btrim(position)) > 0 AND department IS NOT NULL "
            "AND length(btrim(department)) > 0)",
            name=op.f("ck_users_role_profile"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index("ix_users_email_lower", "users", [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email_lower", table_name="users")
    op.drop_table("users")
    sa.Enum(name="user_role").drop(op.get_bind())
