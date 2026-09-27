"""Plugin and weather settings pages."""

from typing import Any, cast

from flask import Blueprint, current_app, render_template, request

from inkdisplay.application.services.settings_service import (
    SettingsService,
    SettingsValidationError,
)
from inkdisplay.infrastructure.scheduler.apscheduler_adapter import APSchedulerAdapter
from inkdisplay.presentation.web.blueprints.display import display_blueprint
from inkdisplay.presentation.web.blueprints.photos import photos_blueprint

settings_blueprint = Blueprint(
    "settings", __name__, url_prefix="/settings", template_folder="../templates"
)


@settings_blueprint.record_once
def _register_photos_blueprint(state: Any) -> None:
    state.app.register_blueprint(photos_blueprint)
    state.app.register_blueprint(display_blueprint)


def _settings_service() -> SettingsService:
    return cast(SettingsService, current_app.extensions["inkdisplay.settings_service"])


@settings_blueprint.route("/plugins", methods=["GET", "POST"])
def plugins() -> tuple[str, int] | str:
    service = _settings_service()
    error = None
    status = 200
    if request.method == "POST":
        try:
            service.update_plugins(request.form)
            scheduler: APSchedulerAdapter = current_app.extensions[
                "inkdisplay.scheduler"
            ]
            if scheduler.running:
                scheduler.reconfigure()
        except SettingsValidationError as exception:
            error = str(exception)
            status = 400
    values = service.plugin_values()
    return render_template("settings/plugins.html", values=values, error=error), status


@settings_blueprint.route("/weather", methods=["GET", "POST"])
def weather() -> tuple[str, int] | str:
    service = _settings_service()
    error = None
    status = 200
    if request.method == "POST":
        try:
            service.update_weather(request.form)
        except SettingsValidationError as exception:
            error = str(exception)
            status = 400
    values = service.weather_values()
    return render_template("settings/weather.html", values=values, error=error), status
