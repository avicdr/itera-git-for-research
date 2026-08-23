"""Initial ResearchGit schema.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import researchgit.models
revision="0001_initial";down_revision=None;branch_labels=None;depends_on=None
def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    researchgit.models.Base.metadata.create_all(op.get_bind())
def downgrade(): researchgit.models.Base.metadata.drop_all(op.get_bind())
