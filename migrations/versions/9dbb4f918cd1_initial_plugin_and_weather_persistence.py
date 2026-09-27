"""Initial plugin and weather persistence

Revision ID: 9dbb4f918cd1
Revises:
Create Date: 2026-09-27 08:47:18.097761

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9dbb4f918cd1"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "display_state" not in existing:
        op.create_table(
            "display_state",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("last_plugin_shown", sa.String(length=32), nullable=True),
            sa.Column("last_shown_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_rotation_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "id = 1", name=op.f("ck_display_state_singleton_display_state")
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_display_state")),
        )
    if "plugin_settings" not in existing:
        op.create_table(
            "plugin_settings",
            sa.Column("plugin_key", sa.String(length=32), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("refresh_interval_minutes", sa.Integer(), nullable=False),
            sa.Column("parameters", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "refresh_interval_minutes >= 1",
                name=op.f("ck_plugin_settings_plugin_refresh_interval"),
            ),
            sa.CheckConstraint(
                "sort_order >= 0", name=op.f("ck_plugin_settings_plugin_sort_order")
            ),
            sa.PrimaryKeyConstraint("plugin_key", name=op.f("pk_plugin_settings")),
        )
    if "settings" not in existing:
        op.create_table(
            "settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("rotation_interval_minutes", sa.Integer(), nullable=False),
            sa.Column("weather_provider", sa.String(length=32), nullable=False),
            sa.Column("latitude", sa.Double(), nullable=True),
            sa.Column("longitude", sa.Double(), nullable=True),
            sa.Column("city", sa.String(length=120), nullable=True),
            sa.Column("weather_timezone", sa.String(length=80), nullable=False),
            sa.Column("units", sa.String(length=16), nullable=False),
            sa.Column("language", sa.String(length=16), nullable=False),
            sa.Column("openweather_api_key_encrypted", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "units IN ('metric', 'imperial', 'standard')",
                name=op.f("ck_settings_units"),
            ),
            sa.CheckConstraint("id = 1", name=op.f("ck_settings_singleton_settings")),
            sa.CheckConstraint(
                "rotation_interval_minutes >= 1",
                name=op.f("ck_settings_rotation_interval"),
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_settings")),
        )
    if "weather_cache" not in existing:
        op.create_table(
            "weather_cache",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "id = 1", name=op.f("ck_weather_cache_singleton_weather_cache")
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_weather_cache")),
        )


def downgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table_name in ("weather_cache", "settings", "plugin_settings", "display_state"):
        if table_name in existing:
            op.drop_table(table_name)
