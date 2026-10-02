import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PIL import Image, ImageDraw, ImageFont

import inkdisplay.presentation.rendering.renderer as renderer_module
from inkdisplay.application.plugins.clock_plugin import ClockPlugin
from inkdisplay.presentation.rendering.renderer import ClockRenderer

TIME_BOUNDS = (12, 10, 388, 190)


def _time_pixel_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    ink = Image.eval(image.crop(TIME_BOUNDS).convert("L"), lambda value: 255 - value)
    return ink.getbbox()


def _assert_large_clock(image: Image.Image) -> tuple[int, int, int, int]:
    assert image.size == (400, 300)
    assert image.mode == "1"
    pixel_bbox = _time_pixel_bbox(image)
    assert pixel_bbox is not None
    visible_width = pixel_bbox[2] - pixel_bbox[0]
    visible_height = pixel_bbox[3] - pixel_bbox[1]
    assert 280 <= visible_width <= 360
    assert 90 <= visible_height <= 155
    assert abs((pixel_bbox[0] + pixel_bbox[2]) / 2 - 188) <= 12
    return pixel_bbox


def _fixed_clock_plugin(monkeypatch) -> ClockPlugin:
    renderer = ClockRenderer("Europe/Rome")
    render_clock = renderer.render_clock
    fixed_time = datetime(2026, 10, 2, 18, 54, tzinfo=ZoneInfo("Europe/Rome"))
    monkeypatch.setattr(
        renderer,
        "render_clock",
        lambda **kwargs: render_clock(fixed_time, **kwargs),
    )
    return ClockPlugin(renderer)


def test_clock_image_has_display_dimensions_and_mode() -> None:
    image = ClockRenderer().render_clock(datetime(2025, 3, 30, 10, 5, tzinfo=UTC))

    assert image.size == (400, 300)
    assert image.mode == "1"


def test_clock_handles_dst_timezone_and_long_names() -> None:
    renderer = ClockRenderer("Europe/Rome")
    winter = renderer.render_clock(datetime(2025, 1, 1, 12, tzinfo=UTC))
    summer = renderer.render_clock(datetime(2025, 7, 1, 12, tzinfo=UTC))

    assert winter.size == summer.size == (400, 300)
    assert winter.getbbox() is not None
    assert summer.getbbox() is not None


def test_clock_layout_has_large_centered_time_and_no_header_banner() -> None:
    image = ClockRenderer().render_clock(datetime(2026, 10, 1, 18, 8, tzinfo=UTC))
    ink = Image.eval(image.convert("L"), lambda value: 255 - value)
    time_ink = Image.eval(
        image.crop(TIME_BOUNDS).convert("L"), lambda value: 255 - value
    )
    time_bounds = time_ink.getbbox()
    frame_bounds = ink.getbbox()

    assert image.crop((0, 0, 400, 35)).getextrema() == (255, 255)
    assert time_bounds is not None
    assert abs((time_bounds[0] + time_bounds[2]) / 2 - 188) <= 12
    assert time_bounds[2] - time_bounds[0] >= 280
    assert time_bounds[3] - time_bounds[1] >= 90
    assert frame_bounds is not None
    assert frame_bounds[0] >= 10 and frame_bounds[2] <= 388
    assert frame_bounds[1] >= 10 and frame_bounds[3] <= 288
    date_bounds = Image.eval(
        image.crop((12, 203, 388, 247)).convert("L"), lambda value: 255 - value
    ).getbbox()
    timezone_bounds = Image.eval(
        image.crop((12, 264, 388, 288)).convert("L"), lambda value: 255 - value
    ).getbbox()
    assert date_bounds is not None and timezone_bounds is not None


def test_clock_plugin_final_png_has_large_fixed_time_pixels(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    plugin = _fixed_clock_plugin(monkeypatch)
    monkeypatch.setattr(
        Image.Image,
        "resize",
        lambda *args, **kwargs: pytest.fail("clock rendering must not resize pixels"),
    )
    with caplog.at_level(logging.DEBUG, logger=renderer_module.__name__):
        image = plugin.render()

    pixel_bbox = _assert_large_clock(image)
    render_info = image.info["clock_render"]
    assert render_info["text"] == "18:54"
    assert render_info["font_type"] == "FreeTypeFont"
    assert Path(render_info["font_file"]).is_file()
    assert render_info["text_bbox"][2] - render_info["text_bbox"][0] <= 376
    assert render_info["text_bbox"][3] - render_info["text_bbox"][1] <= 180
    assert render_info["pixel_bbox"] == (
        pixel_bbox[0] + TIME_BOUNDS[0],
        pixel_bbox[1] + TIME_BOUNDS[1],
        pixel_bbox[2] + TIME_BOUNDS[0],
        pixel_bbox[3] + TIME_BOUNDS[1],
    )
    assert render_info["frame_sha256"] == hashlib.sha256(image.tobytes()).hexdigest()
    assert "text_bbox=" in caplog.text and "pixel_bbox=" in caplog.text

    preview_path = tmp_path / "clock-preview.png"
    image.save(preview_path, format="PNG")
    with Image.open(preview_path) as saved_image:
        _assert_large_clock(saved_image)
        assert saved_image.mode == "1"


def test_clock_font_loading_skips_missing_condensed_and_uses_dejavu_bold(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    bold_font = next(
        (
            candidate
            for candidate in renderer_module._font_candidates(True, True)
            if candidate.name == "DejaVuSans-Bold.ttf" and candidate.exists()
        ),
        None,
    )
    if bold_font is None:
        pytest.skip("No system DejaVuSans-Bold TrueType font installed")
    missing_condensed = tmp_path / "DejaVuSansCondensed-Bold.ttf"
    monkeypatch.setattr(
        renderer_module,
        "_font_candidates",
        lambda bold, condensed: [missing_condensed, bold_font],
    )

    with caplog.at_level(logging.DEBUG, logger=renderer_module.__name__):
        font = renderer_module._load_font(150, bold=True, condensed=True)

    assert isinstance(font, ImageFont.FreeTypeFont)
    assert Path(str(font.path)).resolve() == bold_font.resolve()
    assert f"font candidate missing path={missing_condensed}" in caplog.text


def test_clock_fit_uses_only_maximum_bounds_and_selects_largest_size(
    monkeypatch,
) -> None:
    bold_font = next(
        (
            candidate
            for candidate in renderer_module._font_candidates(True, True)
            if candidate.name == "DejaVuSans-Bold.ttf" and candidate.exists()
        ),
        None,
    )
    if bold_font is None:
        pytest.skip("No system DejaVuSans-Bold TrueType font installed")
    monkeypatch.setattr(
        renderer_module,
        "_font_candidates",
        lambda bold, condensed: [bold_font],
    )

    image = Image.new("1", (400, 300), color=255)
    draw = ImageDraw.Draw(image)
    largest_fitting_size = next(
        size
        for size in range(180, 0, -1)
        if (
            (
                bbox := draw.textbbox(
                    (0, 0), "18:54", font=ImageFont.truetype(str(bold_font), size)
                )
            )[2]
            - bbox[0]
            <= 376
            and bbox[3] - bbox[1] <= 180
        )
    )
    selected_size = ClockRenderer._draw_time(
        image, draw, "18:54", (12, 10, 388, 190), 180
    )
    assert selected_size == largest_fitting_size

    small_image = Image.new("1", (400, 300), color=255)
    small_size = ClockRenderer._draw_time(
        small_image, ImageDraw.Draw(small_image), "18:54", (12, 10, 388, 190), 40
    )
    small_bbox = _time_pixel_bbox(small_image)
    assert small_size == 40
    assert small_bbox is not None
    assert small_bbox[2] - small_bbox[0] < 280
    assert small_bbox[3] - small_bbox[1] < 90


def test_clock_fits_long_date_and_timezone_without_clipping() -> None:
    image = ClockRenderer("America/Argentina/Buenos_Aires").render_clock(
        datetime(2026, 9, 30, 18, 8, tzinfo=UTC)
    )
    ink = Image.eval(image.convert("L"), lambda value: 255 - value).getbbox()
    date_ink = Image.eval(
        image.crop((12, 203, 388, 247)).convert("L"), lambda value: 255 - value
    ).getbbox()
    timezone_ink = Image.eval(
        image.crop((12, 264, 388, 288)).convert("L"), lambda value: 255 - value
    ).getbbox()

    assert image.size == (400, 300)
    assert image.mode == "1"
    assert ink is not None and ink[0] >= 10 and ink[1] >= 10
    assert ink[2] <= 388 and ink[3] <= 288
    assert date_ink is not None and timezone_ink is not None


def test_clock_supports_12_hour_format_and_optional_timezone() -> None:
    renderer = ClockRenderer("Europe/Rome")
    moment = datetime(2026, 10, 1, 18, 8, tzinfo=UTC)
    twenty_four_hour = renderer.render_clock(moment)
    twelve_hour = renderer.render_clock(moment, time_format="12h")
    no_timezone = renderer.render_clock(moment, show_timezone=False)

    assert twenty_four_hour.tobytes() != twelve_hour.tobytes()
    assert no_timezone.crop((0, 270, 400, 300)).getextrema() == (255, 255)


def test_clock_fails_clearly_without_system_truetype_font(monkeypatch, caplog) -> None:
    monkeypatch.setattr(renderer_module, "_font_candidates", lambda bold, condensed: [])

    with caplog.at_level(logging.ERROR, logger=renderer_module.__name__):
        with pytest.raises(RuntimeError, match="TrueType font"):
            ClockRenderer().render_clock(datetime(2026, 10, 1, 6, 5, tzinfo=UTC))

    assert "Pillow bitmap fallback is disabled" in caplog.text
