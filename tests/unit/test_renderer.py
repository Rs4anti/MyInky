from datetime import UTC, datetime

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
