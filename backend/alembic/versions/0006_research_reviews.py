"""Add research-review workflow.

Revision ID: 0006_research_reviews
Revises: 0005_discussions_notifications
"""
from alembic import op
import sqlalchemy as sa
revision="0006_research_reviews";down_revision="0005_discussions_notifications";branch_labels=None;depends_on=None
def upgrade():
    if "research_reviews" in set(sa.inspect(op.get_bind()).get_table_names()):return
    op.create_table("research_reviews",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("workspace_id",sa.Uuid(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),sa.Column("source_branch_id",sa.Uuid(),sa.ForeignKey("branches.id"),nullable=False),sa.Column("target_branch_id",sa.Uuid(),sa.ForeignKey("branches.id"),nullable=False),sa.Column("title",sa.String(300),nullable=False),sa.Column("description",sa.Text()),sa.Column("created_by",sa.Uuid(),sa.ForeignKey("users.id"),nullable=False),sa.Column("status",sa.String(40),nullable=False),sa.Column("merged_at",sa.DateTime(timezone=True)));op.create_index("ix_review_workspace_status","research_reviews",["workspace_id","status"])
    op.create_table("research_review_decisions",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("review_id",sa.Uuid(),sa.ForeignKey("research_reviews.id",ondelete="CASCADE"),nullable=False),sa.Column("reviewer_id",sa.Uuid(),sa.ForeignKey("users.id"),nullable=False),sa.Column("decision",sa.String(40),nullable=False),sa.Column("comment",sa.Text()),sa.UniqueConstraint("review_id","reviewer_id"))
def downgrade():
    op.drop_table("research_review_decisions");op.drop_index("ix_review_workspace_status",table_name="research_reviews");op.drop_table("research_reviews")
