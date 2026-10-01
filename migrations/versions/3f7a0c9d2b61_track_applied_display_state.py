"""Track scheduled and successfully applied display state.

Revision ID: 3f7a0c9d2b61
Revises: 0d4e3deebfc4
Create Date: 2026-10-01 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3f7a0c9d2b61"
down_revision = "0d4e3deebfc4"
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("display_state")
    }
    additions = (
        ("current_plugin", sa.String(length=32)),
        ("next_plugin", sa.String(length=32)),
        ("current_plugin_started_at", sa.DateTime(timezone=True)),
        ("current_plugin_expires_at", sa.DateTime(timezone=True)),
        ("last_content_refresh_at", sa.JSON()),
        ("last_display_attempt_at", sa.DateTime(timezone=True)),
        ("last_display_attempt_plugin", sa.String(length=32)),
        ("last_display_success_at", sa.DateTime(timezone=True)),
        ("last_displayed_plugin", sa.String(length=32)),
        ("last_displayed_hash", sa.String(length=64)),
        ("last_display_result", sa.String(length=32)),
        ("last_display_error", sa.Text()),
        ("display_mode", sa.String(length=32)),
        ("refresh_mode", sa.String(length=16)),
    )
    for name, column_type in additions:
        if name in columns:
            continue
        if name == "last_content_refresh_at":
            op.add_column(
                "display_state",
                sa.Column(
                    name,
                    column_type,
                    nullable=False,
                    server_default=sa.text("'{}'"),
                ),
            )
        else:
            op.add_column("display_state", sa.Column(name, column_type, nullable=True))


def downgrade():
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("display_state")
    }
    for name in (
        "refresh_mode",
        "display_mode",
        "last_display_error",
        "last_display_result",
        "last_displayed_hash",
        "last_displayed_plugin",
        "last_display_success_at",
        "last_display_attempt_plugin",
        "last_display_attempt_at",
        "last_content_refresh_at",
        "current_plugin_expires_at",
        "current_plugin_started_at",
        "next_plugin",
        "current_plugin",
    ):
        if name in columns:
            op.drop_column("display_state", name)
