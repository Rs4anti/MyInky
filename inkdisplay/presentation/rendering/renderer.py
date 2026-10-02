"""Pure Pillow rendering for the 400x300 monochrome display."""

from __future__ import annotations

import logging
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
logger = logging.getLogger(__name__)


def _load_font(
    size: int, bold: bool = False, *, condensed: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_names = (
        (
            "impact.ttf",
            "DejaVuSansCondensed-Bold.ttf",
            "DejaVuSans-Bold.ttf",
            "Arial Bold.ttf",
            "arialbd.ttf",
        )
        if bold and condensed
        else ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf")
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
        """Render a dominant Italian clock as a 1-bit display image."""
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

        self._draw_time(image, draw, time_text, (30, 10, 370, 198), 180, 8, bold=True)
        self._draw_centered_fitted(
            draw, date_text, (12, 203, 388, 247), 32, 10, bold=True
        )
        if weather_summary:
            self._draw_centered_fitted(
                draw, weather_summary, (12, 249, 388, 263), 16, 8
            )
        if show_timezone:
            timezone_text = f"{self.timezone.key} · {current.strftime('%Z')}"
            self._draw_centered_fitted(draw, timezone_text, (12, 264, 388, 288), 16, 8)
        return image

    @staticmethod
    def _draw_time(
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        text: str,
        bounds: tuple[int, int, int, int],
        maximum_size: int,
        minimum_size: int,
        bold: bool = True,
    ) -> int | None:
        left, top, right, bottom = bounds
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None
        text_bounds = (0, 0, 0, 0)
        for size in range(maximum_size, minimum_size - 1, -1):
            candidate = _load_font(size, bold=bold, condensed=True)
            measured_bounds = draw.textbbox((0, 0), text, font=candidate)
            candidate_bounds = (
                int(measured_bounds[0]),
                int(measured_bounds[1]),
                int(measured_bounds[2]),
                int(measured_bounds[3]),
            )
            candidate_width = candidate_bounds[2] - candidate_bounds[0]
            candidate_height = candidate_bounds[3] - candidate_bounds[1]
            if candidate_width <= right - left and candidate_height <= bottom - top:
                font = candidate
                text_bounds = candidate_bounds
                break
        if font is None:
            return None

        text_width = text_bounds[2] - text_bounds[0]
        text_height = text_bounds[3] - text_bounds[1]
        target_width = text_width
        mask = Image.new("L", (text_width, text_height), color=0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.text((-text_bounds[0], -text_bounds[1]), text, font=font, fill=255)
        logger.debug(
            "Clock time metrics: text=%r font_size=%s text_width=%s "
            "text_height=%s target_width=%s final_mask=%s",
            text,
            getattr(font, "size", None),
            text_width,
            text_height,
            target_width,
            mask.size,
            extra={
                "clock_text": text,
                "clock_font_size": getattr(font, "size", None),
                "clock_text_width": text_width,
                "clock_text_height": text_height,
                "clock_target_width": target_width,
                "clock_final_mask_size": mask.size,
            },
        )
        mask = mask.convert("1", dither=Image.Dither.NONE)
        x = left + (right - left - target_width) // 2
        y = top + (bottom - top - text_height) // 2
        image.paste(0, (x, y), mask)
        return getattr(font, "size", None)

    @staticmethod
    def _fit_font(
        draw: ImageDraw.ImageDraw,
        text: str,
        bounds: tuple[int, int, int, int],
        maximum_size: int,
        minimum_size: int,
        bold: bool = False,
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont | None:
        left, top, right, bottom = bounds
        for size in range(maximum_size, minimum_size - 1, -1):
            font = _load_font(size, bold=bold)
            text_bounds = draw.textbbox((0, 0), text, font=font)
            text_width = text_bounds[2] - text_bounds[0]
            text_height = text_bounds[3] - text_bounds[1]
            if text_width <= right - left and text_height <= bottom - top:
                return font
        return None

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
        fitted_text = text
        font = ClockRenderer._fit_font(
            draw, fitted_text, bounds, maximum_size, minimum_size, bold
        )
        while font is None and len(fitted_text) > 1:
            fitted_text = fitted_text[:-2] + "…"
            font = ClockRenderer._fit_font(
                draw, fitted_text, bounds, maximum_size, minimum_size, bold
            )
        if font is None:
            return

        text_bounds = draw.textbbox((0, 0), fitted_text, font=font)
        text_width = text_bounds[2] - text_bounds[0]
        text_height = text_bounds[3] - text_bounds[1]
        x = left + (right - left - text_width) // 2 - text_bounds[0]
        y = top + (bottom - top - text_height) // 2 - text_bounds[1]
        draw.text((x, y), fitted_text, font=font, fill=0)
