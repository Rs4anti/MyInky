"""Flask application factory."""

from __future__ import annotations

import os
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path
from typing import Any

from flask import Flask, render_template, send_file

from inkdisplay.application.plugins.clock_plugin import ClockPlugin
from inkdisplay.application.plugins.photo_plugin import PhotoPlugin
from inkdisplay.application.plugins.weather_plugin import WeatherPlugin
from inkdisplay.application.services.display_service import DisplayControlService
from inkdisplay.application.services.plugin_service import PluginService
from inkdisplay.application.services.preview_service import PreviewService
from inkdisplay.application.services.settings_service import SettingsService
from inkdisplay.application.services.weather_service import WeatherService
from inkdisplay.config import AppSettings
from inkdisplay.extensions import csrf, db, migrate
from inkdisplay.infrastructure.display.factory import select_display

# Register model metadata before db.create_all() and Flask-Migrate inspection.
from inkdisplay.infrastructure.persistence import models as _models  # noqa: F401
from inkdisplay.infrastructure.persistence.bootstrap import ensure_default_records
from inkdisplay.infrastructure.scheduler.apscheduler_adapter import APSchedulerAdapter
from inkdisplay.infrastructure.security.secret_store import SecretStore
from inkdisplay.infrastructure.weather.open_meteo import OpenMeteoProvider
from inkdisplay.infrastructure.weather.open_weather_map import OpenWeatherMapProvider
from inkdisplay.presentation.rendering.renderer import ClockRenderer
from inkdisplay.presentation.rendering.weather_renderer import WeatherRenderer
from inkdisplay.presentation.web.blueprints.settings import settings_blueprint


def create_app(config_override: Mapping[str, Any] | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    settings = AppSettings.from_environment()
    app.config.from_mapping(settings.as_flask_config())
    if config_override:
        app.config.from_mapping(config_override)

    validated = AppSettings.from_mapping(app.config)
    app.config.update(validated.as_flask_config())

    data_dir = Path(app.config["DATA_DIR"]).resolve()
    preview_path = data_dir / "previews" / "current.png"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / "inkdisplay.sqlite3"
    app.config.setdefault(
        "SQLALCHEMY_DATABASE_URI", f"sqlite:///{database_path.as_posix()}"
    )
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    app.config.setdefault("WTF_CSRF_ENABLED", not bool(app.config.get("TESTING")))
    app.config.setdefault(
        "AUTO_CREATE_SCHEMA",
        os.getenv("INKDISPLAY_AUTO_CREATE_SCHEMA", "true").lower()
        not in {"0", "false", "no"},
    )

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    with app.app_context():
        if app.config["AUTO_CREATE_SCHEMA"]:
            db.create_all()
            ensure_default_records()

    selection = select_display(
        validated.display_mode,
        preview_path,
        data_dir / "display.lock",
    )
    display = selection.display
    app.config["DISPLAY_MODE"] = selection.mode
    renderer = ClockRenderer(timezone_name=str(app.config["TIMEZONE"]))
    secret_store = SecretStore(data_dir)
    settings_service = SettingsService(secret_store)
    weather_service = WeatherService(
        {
            "open-meteo": OpenMeteoProvider(),
            "openweathermap": OpenWeatherMapProvider(),
        },
        secret_store,
    )
    plugin_service = PluginService(
        {
            "clock": ClockPlugin(renderer),
            "weather": WeatherPlugin(weather_service, WeatherRenderer()),
            "photo": PhotoPlugin(),
        },
        display,
        preview_path,
    )
    preview_service = PreviewService(plugin_service)
    scheduler = APSchedulerAdapter(app, plugin_service, data_dir / "scheduler.lock")
    display_service = DisplayControlService(
        display, plugin_service, scheduler, str(app.config["TIMEZONE"])
    )

    @app.get("/")
    def dashboard() -> str:
        return render_template("dashboard.html", status=display_service.status())

    @app.get("/health")
    def health() -> tuple[dict[str, str], int]:
        return {"status": "ok", "display_mode": display.mode}, 200

    @app.get("/api/preview")
    def preview() -> Any:
        display_state = plugin_service.status()
        if (
            preview_path.is_file()
            and display_state["last_display_success_at"] is not None
        ):
            response = send_file(
                preview_path, mimetype="image/png", max_age=0, conditional=False
            )
        else:
            image = preview_service.render_current()
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            buffer.seek(0)
            response = send_file(
                buffer, mimetype="image/png", max_age=0, conditional=False
            )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

    app.extensions["inkdisplay.display"] = display
    app.extensions["inkdisplay.renderer"] = renderer
    app.extensions["inkdisplay.settings_service"] = settings_service
    app.extensions["inkdisplay.weather_service"] = weather_service
    app.extensions["inkdisplay.plugin_service"] = plugin_service
    app.extensions["inkdisplay.scheduler"] = scheduler
    app.extensions["inkdisplay.display_service"] = display_service
    app.register_blueprint(settings_blueprint)
    return app
