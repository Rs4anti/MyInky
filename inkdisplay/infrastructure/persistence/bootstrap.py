"""Creation of required singleton rows and initial plugin settings."""

from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import (
    DisplayState,
    PluginSettings,
    Settings,
)

DEFAULT_PLUGINS = (
    ("clock", True, 0, 1),
    ("weather", False, 1, 30),
    ("photo", False, 2, 10),
)


def ensure_default_records() -> None:
    """Create defaults once without overwriting saved user configuration."""
    if db.session.get(Settings, 1) is None:
        db.session.add(Settings(id=1))
    if db.session.get(DisplayState, 1) is None:
        db.session.add(DisplayState(id=1))
    for plugin_key, enabled, sort_order, interval in DEFAULT_PLUGINS:
        if db.session.get(PluginSettings, plugin_key) is None:
            db.session.add(
                PluginSettings(
                    plugin_key=plugin_key,
                    enabled=enabled,
                    sort_order=sort_order,
                    refresh_interval_minutes=interval,
                )
            )
    db.session.commit()
