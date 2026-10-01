from datetime import UTC, datetime

from PIL import Image, ImageFont

import inkdisplay.presentation.rendering.renderer as renderer_module
from inkdisplay.presentation.rendering.renderer import ClockRenderer


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
        image.crop((0, 36, 400, 190)).convert("L"), lambda value: 255 - value
    )
    time_bounds = time_ink.getbbox()
    frame_bounds = ink.getbbox()

    assert image.crop((0, 0, 400, 35)).getextrema() == (255, 255)
    assert time_bounds is not None
    assert abs((time_bounds[0] + time_bounds[2]) / 2 - 200) <= 3
    assert time_bounds[2] - time_bounds[0] >= 200
    assert frame_bounds is not None
    assert frame_bounds[0] >= 12 and frame_bounds[2] <= 388
    assert frame_bounds[1] >= 36 and frame_bounds[3] <= 288


def test_clock_supports_12_hour_format_and_optional_timezone() -> None:
    renderer = ClockRenderer("Europe/Rome")
    moment = datetime(2026, 10, 1, 18, 8, tzinfo=UTC)
    twenty_four_hour = renderer.render_clock(moment)
    twelve_hour = renderer.render_clock(moment, time_format="12h")
    no_timezone = renderer.render_clock(moment, show_timezone=False)

    assert twenty_four_hour.tobytes() != twelve_hour.tobytes()
    assert no_timezone.crop((0, 270, 400, 300)).getextrema() == (255, 255)


def test_clock_uses_font_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        renderer_module, "_load_font", lambda size, bold=False: ImageFont.load_default()
    )

    image = ClockRenderer().render_clock(datetime(2026, 10, 1, 6, 5, tzinfo=UTC))

    assert image.size == (400, 300)
    assert image.mode == "1"
    ink = Image.eval(image.convert("L"), lambda value: 255 - value).getbbox()
    assert ink is not None and ink[0] >= 12 and ink[2] <= 388
