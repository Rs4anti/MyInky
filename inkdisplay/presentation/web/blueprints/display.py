"""Display diagnostics and manual controls."""

from __future__ import annotations

from typing import cast

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)
from werkzeug.wrappers import Response

from inkdisplay.application.services.display_service import DisplayControlService
from inkdisplay.infrastructure.display.managed_display import DisplayBusyError
from inkdisplay.infrastructure.display.waveshare_4in2_v2 import DisplayHardwareError

display_blueprint = Blueprint("display", __name__)


def _control_service() -> DisplayControlService:
    return cast(
        DisplayControlService,
        current_app.extensions["inkdisplay.display_service"],
    )


@display_blueprint.get("/display")
def index() -> str:
    return render_template("display.html", status=_control_service().status())


@display_blueprint.post("/display/refresh")
def refresh() -> Response:
    try:
        plugin_key = _control_service().refresh_current()
    except (DisplayBusyError, DisplayHardwareError, OSError, RuntimeError) as error:
        current_app.logger.warning("Manual display refresh failed: %s", error)
        flash("Aggiornamento display non riuscito.", "error")
    else:
        flash(f"Aggiornamento richiesto per {plugin_key}.", "success")
    return redirect(url_for("display.index"))


@display_blueprint.post("/display/clear")
def clear() -> Response:
    try:
        _control_service().clear()
    except (DisplayBusyError, DisplayHardwareError, OSError, RuntimeError) as error:
        current_app.logger.warning("Manual display clear failed: %s", error)
        flash("Pulizia display non riuscita.", "error")
    else:
        flash("Display pulito.", "success")
    return redirect(url_for("display.index"))


@display_blueprint.post("/display/sleep")
def sleep() -> Response:
    try:
        _control_service().sleep()
    except (DisplayBusyError, DisplayHardwareError, OSError, RuntimeError) as error:
        current_app.logger.warning("Manual display sleep failed: %s", error)
        flash("Sleep display non riuscito.", "error")
    else:
        flash("Display in sleep.", "success")
    return redirect(url_for("display.index"))
