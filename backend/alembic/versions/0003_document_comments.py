"""Add anchored document comment threads.

Revision ID: 0003_document_comments
Revises: 0002_auth_membership_invites
"""
from alembic import op
import sqlalchemy as sa

revision="0003_document_comments"
down_revision="0002_auth_membership_invites"
branch_labels=None
depends_on=None

def upgrade():
    tables=set(sa.inspect(op.get_bind()).get_table_names())
    if "comment_threads" not in tables:
        op.create_table("comment_threads",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("workspace_id",sa.Uuid(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),sa.Column("artifact_id",sa.Uuid(),sa.ForeignKey("artifacts.id",ondelete="CASCADE"),nullable=False),sa.Column("artifact_version_id",sa.Uuid(),sa.ForeignKey("artifact_versions.id")),sa.Column("anchor",sa.JSON(),nullable=False),sa.Column("selected_text",sa.Text(),nullable=False),sa.Column("created_by",sa.Uuid(),sa.ForeignKey("users.id"),nullable=False),sa.Column("resolved_at",sa.DateTime(timezone=True)))
        op.create_index("ix_comment_thread_artifact","comment_threads",["artifact_id","resolved_at"])
    if "comments" not in tables:
        op.create_table("comments",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("thread_id",sa.Uuid(),sa.ForeignKey("comment_threads.id",ondelete="CASCADE"),nullable=False),sa.Column("user_id",sa.Uuid(),sa.ForeignKey("users.id"),nullable=False),sa.Column("content",sa.Text(),nullable=False))
        op.create_index("ix_comment_thread_created","comments",["thread_id","created_at"])

def downgrade():
    op.drop_index("ix_comment_thread_created",table_name="comments");op.drop_table("comments");op.drop_index("ix_comment_thread_artifact",table_name="comment_threads");op.drop_table("comment_threads")
