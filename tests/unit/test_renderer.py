import logging
from datetime import UTC, datetime

from PIL import Image, ImageDraw, ImageFont

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
        image.crop((12, 10, 388, 198)).convert("L"), lambda value: 255 - value
    )
    time_bounds = time_ink.getbbox()
    frame_bounds = ink.getbbox()

    assert image.crop((0, 0, 400, 35)).getextrema() == (255, 255)
    assert time_bounds is not None
    assert abs((time_bounds[0] + time_bounds[2]) / 2 - 188) <= 2
    assert (time_bounds[2] - time_bounds[0]) / 340 >= 0.80
    assert (time_bounds[3] - time_bounds[1]) / 188 >= 0.40
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


def test_clock_font_scales_to_bounds_and_selects_largest_fitting_size() -> None:
    image = Image.new("1", (400, 300), color=255)
    draw = ImageDraw.Draw(image)
    text = "21:58"
    font = ClockRenderer._fit_font(draw, text, (12, 10, 388, 198), 180, 8, True)
    widest_hour_size = ClockRenderer._draw_time(
        image, draw, text, (12, 10, 388, 198), 180, 8
    )
    short_hour_size = ClockRenderer._draw_time(
        image, draw, text, (12, 10, 388, 80), 180, 8
    )

    assert font is not None and getattr(font, "size", 0) > 100
    assert widest_hour_size is not None and widest_hour_size < 180
    assert short_hour_size is not None and short_hour_size < widest_hour_size


def test_clock_time_logs_unscaled_mask_metrics(caplog) -> None:
    image = Image.new("1", (400, 300), color=255)
    draw = ImageDraw.Draw(image)
    bounds = (30, 10, 370, 198)

    with caplog.at_level(logging.DEBUG, logger=renderer_module.__name__):
        font_size = ClockRenderer._draw_time(image, draw, "22:00", bounds, 180, 8)

    record = next(record for record in caplog.records if hasattr(record, "clock_text"))
    assert font_size == record.clock_font_size
    assert record.clock_text == "22:00"
    assert record.clock_text_width <= bounds[2] - bounds[0]
    assert record.clock_text_height <= bounds[3] - bounds[1]
    assert record.clock_target_width == record.clock_text_width
    assert record.clock_final_mask_size == (
        record.clock_text_width,
        record.clock_text_height,
    )
    assert "font_size=" in record.message and "final_mask=" in record.message


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


def test_clock_uses_font_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        renderer_module,
        "_load_font",
        lambda size, bold=False, condensed=False: ImageFont.load_default(),
    )

    image = ClockRenderer().render_clock(datetime(2026, 10, 1, 6, 5, tzinfo=UTC))

    assert image.size == (400, 300)
    assert image.mode == "1"
    ink = Image.eval(image.convert("L"), lambda value: 255 - value).getbbox()
    assert ink is not None and ink[0] >= 12 and ink[2] <= 388
