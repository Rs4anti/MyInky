"""Pure Pillow rendering for the 400x300 monochrome display."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

WIDTH = 400
HEIGHT = 300
WEEKDAYS_IT = (
    "lunedì",
    "martedì",
    "mercoledì",
    "giovedì",
    "venerdì",
    "sabato",
    "domenica",
)
MONTHS_IT = (
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
)


def _load_font(
    size: int, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_names = (
        ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf")
        if bold
        else ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf")
    )
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu") / name for name in font_names
    ]
    windows_dir = Path("C:/Windows/Fonts")
    candidates.extend(windows_dir / name for name in font_names)
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


class ClockRenderer:
    def __init__(self, timezone_name: str = "Europe/Rome") -> None:
        self.timezone = ZoneInfo(timezone_name)

    def render_clock(
        self,
        now: datetime | None = None,
        *,
        time_format: str = "24h",
        show_seconds: bool = False,
        show_timezone: bool = True,
        weather_summary: str | None = None,
    ) -> Image.Image:
        """Render a centered Italian clock as a 1-bit display image."""
        current = (now or datetime.now(self.timezone)).astimezone(self.timezone)
        image = Image.new("1", (WIDTH, HEIGHT), color=255)
        draw = ImageDraw.Draw(image)

        date_text = (
            f"{WEEKDAYS_IT[current.weekday()].capitalize()} "
            f"{current.day} {MONTHS_IT[current.month - 1]} {current.year}"
        )
        time_text = (
            current.strftime("%I:%M")
            if time_format == "12h"
            else current.strftime("%H:%M")
        )
        if time_format == "12h":
            time_text = time_text.lstrip("0")
        if show_seconds:
            time_text += current.strftime(":%S")
        self._draw_centered_fitted(
            draw, time_text, (14, 36, 386, 190), 140, 72, bold=True
        )
        self._draw_centered_fitted(
            draw, date_text, (14, 197, 386, 242), 29, 18, bold=True
        )
        if weather_summary:
            self._draw_centered_fitted(
                draw, weather_summary, (14, 243, 386, 265), 17, 12
            )
        if show_timezone:
            timezone_text = f"{self.timezone.key} · {current.strftime('%Z')}"
            self._draw_centered_fitted(draw, timezone_text, (14, 266, 386, 288), 17, 12)
        return image

    @staticmethod
    def _draw_centered_fitted(
        draw: ImageDraw.ImageDraw,
        text: str,
        bounds: tuple[int, int, int, int],
        maximum_size: int,
        minimum_size: int,
        bold: bool = False,
    ) -> None:
        left, top, right, bottom = bounds
        for size in range(maximum_size, minimum_size - 1, -1):
            font = _load_font(size, bold=bold)
            text_bounds = draw.textbbox((0, 0), text, font=font)
            text_width = text_bounds[2] - text_bounds[0]
            text_height = text_bounds[3] - text_bounds[1]
            if text_width <= right - left and text_height <= bottom - top:
                x = left + (right - left - text_width) // 2 - text_bounds[0]
                y = top + (bottom - top - text_height) // 2 - text_bounds[1]
                draw.text((x, y), text, font=font, fill=0)
                return
        font = _load_font(minimum_size, bold=bold)
        text_bounds = draw.textbbox((0, 0), text, font=font)
        x = left + (right - left - (text_bounds[2] - text_bounds[0])) // 2
        y = top + (bottom - top - (text_bounds[3] - text_bounds[1])) // 2
        draw.text((x - text_bounds[0], y - text_bounds[1]), text, font=font, fill=0)
