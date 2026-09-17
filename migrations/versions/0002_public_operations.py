"""Public service quotas and worker state."""
from alembic import op
import sqlalchemy as sa

revision = "0002_public_operations"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("operational_state",
                    sa.Column("key", sa.String(40), primary_key=True),
                    sa.Column("value", sa.JSON(), nullable=False),
                    sa.Column("updated_at", sa.Integer(), nullable=False))
    op.create_table("request_quotas",
                    sa.Column("key", sa.String(120), primary_key=True),
                    sa.Column("count", sa.Integer(), nullable=False),
                    sa.Column("expires_at", sa.Integer(), nullable=False))
    op.create_index("ix_request_quotas_expires_at", "request_quotas", ["expires_at"])


def downgrade():
    op.drop_table("request_quotas")
    op.drop_table("operational_state")
