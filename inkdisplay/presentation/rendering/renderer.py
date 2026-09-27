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

    def render_clock(self, now: datetime | None = None) -> Image.Image:
        """Render an Italian 24-hour clock as a 1-bit display image."""
        current = (now or datetime.now(self.timezone)).astimezone(self.timezone)
        image = Image.new("1", (WIDTH, HEIGHT), color=255)
        draw = ImageDraw.Draw(image)

        draw.rectangle((0, 0, WIDTH, 48), fill=0)
        draw.text(
            (22, 13), "MYINKY  |  OROLOGIO", font=_load_font(17, bold=True), fill=1
        )

        date_text = (
            f"{WEEKDAYS_IT[current.weekday()].capitalize()} "
            f"{current.day} {MONTHS_IT[current.month - 1]} {current.year}"
        )
        self._draw_fitted(draw, date_text, (22, 81, 378, 118), 24, 16, bold=True)

        time_text = current.strftime("%H:%M")
        self._draw_fitted(draw, time_text, (18, 126, 382, 231), 92, 62, bold=True)

        timezone_text = current.strftime("%Z") or self.timezone.key
        draw.line((22, 253, 378, 253), fill=0, width=1)
        draw.text(
            (22, 268),
            f"FUSO ORARIO  {timezone_text}",
            font=_load_font(15),
            fill=0,
        )
        return image

    @staticmethod
    def _draw_fitted(
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
            if text_bounds[2] - text_bounds[0] <= right - left:
                draw.text((left, top), text, font=font, fill=0)
                return
        draw.text((left, top), text, font=_load_font(minimum_size, bold=bold), fill=0)
