"""Add photo library

Revision ID: 0d4e3deebfc4
Revises: 9dbb4f918cd1
Create Date: 2026-09-27 09:24:02.116205

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0d4e3deebfc4"
down_revision = "9dbb4f918cd1"
branch_labels = None
depends_on = None


def upgrade():
    if "photos" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "photos",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("filename", sa.String(length=48), nullable=False),
            sa.Column("original_name", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("caption", sa.String(length=240), nullable=True),
            sa.Column("width", sa.Integer(), nullable=False),
            sa.Column("height", sa.Integer(), nullable=False),
            sa.CheckConstraint("height > 0", name=op.f("ck_photos_photo_height")),
            sa.CheckConstraint(
                "sort_order >= 0", name=op.f("ck_photos_photo_sort_order")
            ),
            sa.CheckConstraint("width > 0", name=op.f("ck_photos_photo_width")),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_photos")),
            sa.UniqueConstraint("filename", name=op.f("uq_photos_filename")),
        )


def downgrade():
    if "photos" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("photos")
