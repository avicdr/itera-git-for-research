"""Add collaborative PDF annotations.

Revision ID: 0004_pdf_annotations
Revises: 0003_document_comments
"""
from alembic import op
import sqlalchemy as sa

revision="0004_pdf_annotations"
down_revision="0003_document_comments"
branch_labels=None
depends_on=None

def upgrade():
    if "pdf_annotations" in set(sa.inspect(op.get_bind()).get_table_names()): return
    op.create_table("pdf_annotations",sa.Column("id",sa.Uuid(),primary_key=True),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False),sa.Column("workspace_id",sa.Uuid(),sa.ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False),sa.Column("artifact_id",sa.Uuid(),sa.ForeignKey("artifacts.id",ondelete="CASCADE"),nullable=False),sa.Column("artifact_version_id",sa.Uuid(),sa.ForeignKey("artifact_versions.id"),nullable=False),sa.Column("page_number",sa.Integer(),nullable=False),sa.Column("selected_text",sa.Text(),nullable=False),sa.Column("anchor_data",sa.JSON(),nullable=False),sa.Column("note",sa.Text()),sa.Column("created_by",sa.Uuid(),sa.ForeignKey("users.id"),nullable=False),sa.Column("resolved_at",sa.DateTime(timezone=True)))
    op.create_index("ix_pdf_annotation_artifact_page","pdf_annotations",["artifact_id","page_number"])

def downgrade():
    op.drop_index("ix_pdf_annotation_artifact_page",table_name="pdf_annotations");op.drop_table("pdf_annotations")
