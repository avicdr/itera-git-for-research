"""Add human discussions and notifications.

Revision ID: 0005_discussions_notifications
Revises: 0004_pdf_annotations
"""
from alembic import op
import sqlalchemy as sa

revision="0005_discussions_notifications"; down_revision="0004_pdf_annotations"; branch_labels=None; depends_on=None
def upgrade():
    tables=set(sa.inspect(op.get_bind()).get_table_names())
    if "discussion_threads" not in tables:
        op.create_table("discussion_threads",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("workspace_id",sa.Uuid(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),sa.Column("scope",sa.String(30),nullable=False),sa.Column("branch_id",sa.Uuid(),sa.ForeignKey("branches.id")),sa.Column("artifact_id",sa.Uuid(),sa.ForeignKey("artifacts.id")),sa.Column("title",sa.String(300)),sa.Column("created_by",sa.Uuid(),sa.ForeignKey("users.id"),nullable=False));op.create_index("ix_discussion_scope","discussion_threads",["workspace_id","scope"])
    if "discussion_messages" not in tables:
        op.create_table("discussion_messages",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("thread_id",sa.Uuid(),sa.ForeignKey("discussion_threads.id",ondelete="CASCADE"),nullable=False),sa.Column("user_id",sa.Uuid(),sa.ForeignKey("users.id"),nullable=False),sa.Column("content",sa.Text(),nullable=False),sa.Column("references",sa.JSON(),nullable=False));op.create_index("ix_discussion_message_thread","discussion_messages",["thread_id","created_at"])
    if "notifications" not in tables:
        op.create_table("notifications",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("user_id",sa.Uuid(),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),sa.Column("workspace_id",sa.Uuid(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),sa.Column("type",sa.String(60),nullable=False),sa.Column("actor_id",sa.Uuid(),sa.ForeignKey("users.id")),sa.Column("entity_type",sa.String(60),nullable=False),sa.Column("entity_id",sa.Uuid()),sa.Column("read_at",sa.DateTime(timezone=True)),sa.Column("metadata",sa.JSON(),nullable=False));op.create_index("ix_notification_user_unread","notifications",["user_id","read_at"])
def downgrade():
    op.drop_index("ix_notification_user_unread",table_name="notifications");op.drop_table("notifications");op.drop_index("ix_discussion_message_thread",table_name="discussion_messages");op.drop_table("discussion_messages");op.drop_index("ix_discussion_scope",table_name="discussion_threads");op.drop_table("discussion_threads")
