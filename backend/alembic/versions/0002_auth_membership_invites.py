"""Add production authentication and secure workspace invitations.

Revision ID: 0002_auth_membership_invites
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_auth_membership_invites"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    inspector=sa.inspect(op.get_bind()); user_columns={column["name"] for column in inspector.get_columns("users")}
    if "password_hash" not in user_columns or "avatar_url" not in user_columns:
        with op.batch_alter_table("users") as batch:
            if "password_hash" not in user_columns: batch.add_column(sa.Column("password_hash", sa.String(255), nullable=True))
            if "avatar_url" not in user_columns: batch.add_column(sa.Column("avatar_url", sa.String(600), nullable=True))
    tables=set(inspector.get_table_names())
    if "user_sessions" not in tables: op.create_table("user_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("token_hash", sa.String(64), nullable=False, unique=True), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    if "user_sessions" not in tables: op.create_index("ix_user_sessions_token", "user_sessions", ["token_hash"], unique=True)
    if "workspace_invites" not in tables: op.create_table("workspace_invites",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False), sa.Column("token_hash", sa.String(64), nullable=False, unique=True), sa.Column("role", sa.String(30), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("max_uses", sa.Integer()), sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    if "workspace_invites" not in tables: op.create_index("ix_workspace_invite_token", "workspace_invites", ["token_hash"], unique=True)

def downgrade():
    op.drop_index("ix_workspace_invite_token", table_name="workspace_invites"); op.drop_table("workspace_invites")
    op.drop_index("ix_user_sessions_token", table_name="user_sessions"); op.drop_table("user_sessions")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("avatar_url"); batch.drop_column("password_hash")
