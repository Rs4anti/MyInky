"""Photo library and processing settings routes."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.wrappers import Response

from inkdisplay.application.services.photo_service import (
    PhotoService,
    PhotoValidationError,
)

photos_blueprint = Blueprint("photos", __name__, template_folder="../templates")


def _service() -> PhotoService:
    return PhotoService(Path(current_app.config["DATA_DIR"]))


def _index_response(error: str | None = None, status: int = 200) -> tuple[str, int]:
    service = _service()
    photos = service.list_photos()
    settings = service.settings()
    last_photo_id = settings.get("last_photo_id")
    last_photo = (
        service.photo(last_photo_id) if isinstance(last_photo_id, int) else None
    )
    rows = []
    for photo in photos:
        try:
            file_size = service.source_path(photo).stat().st_size
        except OSError:
            file_size = 0
        rows.append((photo, file_size))
    return (
        render_template(
            "photos/index.html",
            photos=rows,
            settings=settings,
            last_photo=last_photo,
            total_count=len(photos),
            active_count=sum(photo.enabled for photo in photos),
            error=error,
        ),
        status,
    )


@photos_blueprint.route("/photos", methods=["GET", "POST"])
def index() -> tuple[str, int] | Response:
    if request.method == "POST":
        try:
            _service().save_settings(request.form)
        except PhotoValidationError as error:
            return _index_response(str(error), 400)
        flash("Impostazioni foto salvate.", "success")
        return redirect(url_for("photos.index"))
    return _index_response()


@photos_blueprint.route("/photos/upload", methods=["GET", "POST"])
def upload() -> tuple[str, int] | Response:
    service = _service()
    error = None
    if request.method == "POST":
        settings = service.settings()
        files = [item for item in request.files.getlist("photos") if item.filename]
        if not files:
            error = "Seleziona almeno una foto da caricare."
        else:
            failures = []
            uploaded_count = 0
            max_upload_mb = settings.get("max_upload_mb", 10)
            if not isinstance(max_upload_mb, int):
                max_upload_mb = 10
            for uploaded in files:
                try:
                    service.upload(
                        uploaded.stream,
                        original_name=uploaded.filename or "",
                        mime_type=uploaded.mimetype,
                        caption=request.form.get("caption"),
                        max_upload_mb=max_upload_mb,
                    )
                    uploaded_count += 1
                except PhotoValidationError as exception:
                    failures.append(str(exception))
            if uploaded_count:
                flash(f"Caricate {uploaded_count} foto.", "success")
                return redirect(url_for("photos.index"))
            error = " ".join(failures)
    return (
        render_template(
            "photos/upload.html",
            error=error,
            max_upload_mb=service.settings()["max_upload_mb"],
        ),
        400 if error else 200,
    )


@photos_blueprint.get("/photos/<int:photo_id>/thumbnail")
def thumbnail(photo_id: int) -> Response | tuple[str, int]:
    service = _service()
    photo = service.photo(photo_id)
    if photo is None:
        return "Foto non trovata.", 404
    try:
        image = service.processed_image(photo)
    except (OSError, PhotoValidationError):
        return "Impossibile leggere la foto.", 404
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png", max_age=0)


@photos_blueprint.post("/photos/<int:photo_id>/toggle")
def toggle(photo_id: int) -> Response | tuple[str, int]:
    enabled = request.form.get("enabled") == "1"
    if not _service().set_enabled(photo_id, enabled):
        return "Foto non trovata.", 404
    return redirect(url_for("photos.index"))


@photos_blueprint.post("/photos/<int:photo_id>/delete")
def delete(photo_id: int) -> Response | tuple[str, int]:
    if not _service().delete(photo_id):
        return "Foto non trovata.", 404
    flash("Foto eliminata.", "success")
    return redirect(url_for("photos.index"))


@photos_blueprint.post("/photos/<int:photo_id>/move")
def move(photo_id: int) -> Response | tuple[str, int]:
    direction = request.form.get("direction", "")
    if not _service().move(photo_id, direction):
        return "Impossibile spostare la foto.", 400
    return redirect(url_for("photos.index"))
