"""Pure Pillow rendering for the 400x300 monochrome display."""

from __future__ import annotations

import hashlib
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
    size: int,
    bold: bool = False,
    *,
    condensed: bool = False,
    font_file: Path | None = None,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        [font_file] if font_file is not None else _font_candidates(bold, condensed)
    )
    for candidate in candidates:
        if not candidate.exists():
            logger.debug("CLOCK_RENDER font candidate missing path=%s", candidate)
            continue
        try:
            return ImageFont.truetype(str(candidate), size=size)
        except (OSError, ValueError) as error:
            logger.debug(
                "CLOCK_RENDER font load failed path=%s error=%s",
                candidate,
                error,
            )
            continue
    raise RuntimeError(f"No usable system TrueType font found for clock at size {size}")


def _font_candidates(bold: bool, condensed: bool) -> list[Path]:
    if bold and condensed:
        font_names: tuple[str, ...] = (
            "DejaVuSansCondensed-Bold.ttf",
            "DejaVuSans-Bold.ttf",
            "DejaVuSansMono-Bold.ttf",
            "LiberationSansNarrow-Bold.ttf",
            "DejaVuSerifCondensed-Bold.ttf",
            "impact.ttf",
            "Arial Bold.ttf",
            "arialbd.ttf",
        )
    elif bold:
        font_names = ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf")
    else:
        font_names = ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf")

    font_directories = (
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/usr/share/fonts/truetype/liberation2"),
        Path("C:/Windows/Fonts"),
    )
    return [directory / name for name in font_names for directory in font_directories]


def _black_pixel_bounds(
    image: Image.Image, bounds: tuple[int, int, int, int]
) -> tuple[int, int, int, int] | None:
    left, top, _, _ = bounds
    ink = Image.eval(
        image.crop(bounds).convert("L"), lambda value: 255 - value
    ).getbbox()
    if ink is None:
        return None
    return left + ink[0], top + ink[1], left + ink[2], top + ink[3]


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

        time_bounds = (12, 10, 388, 190)
        self._draw_time(image, draw, time_text, time_bounds, 180, bold=True)
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
        clock_render = image.info["clock_render"]
        clock_render["pixel_bbox"] = _black_pixel_bounds(image, time_bounds)
        clock_render["frame_sha256"] = hashlib.sha256(image.tobytes()).hexdigest()
        logger.debug(
            "CLOCK_RENDER frame=%sx%s mode=%s text=%s pixel_bbox=%s sha256=%s",
            image.width,
            image.height,
            image.mode,
            time_text,
            clock_render["pixel_bbox"],
            clock_render["frame_sha256"],
        )
        return image

    @staticmethod
    def _draw_time(
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        text: str,
        bounds: tuple[int, int, int, int],
        maximum_size: int,
        bold: bool = True,
    ) -> int | None:
        left, top, right, bottom = bounds
        max_text_width = right - left
        max_text_height = bottom - top
        font_paths = _font_candidates(bold, condensed=True)
        loaded_font = False
        for font_path in font_paths:
            try:
                _load_font(maximum_size, bold=bold, font_file=font_path)
            except RuntimeError:
                continue
            loaded_font = True

            for size in range(maximum_size, 0, -1):
                try:
                    font = _load_font(size, bold=bold, font_file=font_path)
                except RuntimeError:
                    break
                if not isinstance(font, ImageFont.FreeTypeFont):
                    break
                text_bounds = tuple(
                    int(value) for value in draw.textbbox((0, 0), text, font=font)
                )
                text_width = text_bounds[2] - text_bounds[0]
                text_height = text_bounds[3] - text_bounds[1]
                if text_width > max_text_width or text_height > max_text_height:
                    continue

                x = left + (right - left - text_width) // 2 - text_bounds[0]
                y = top + (bottom - top - text_height) // 2 - text_bounds[1]
                draw.text((x, y), text, font=font, fill=0)
                pixel_bounds = _black_pixel_bounds(image, bounds)
                visible_width = pixel_bounds[2] - pixel_bounds[0] if pixel_bounds else 0
                visible_height = (
                    pixel_bounds[3] - pixel_bounds[1] if pixel_bounds else 0
                )
                font_size = int(font.size)
                font_file = Path(str(font.path)).resolve()
                renderer_name = (
                    f"{ClockRenderer.__module__}.{ClockRenderer.__qualname__}"
                )
                image.info["clock_render"] = {
                    "renderer": renderer_name,
                    "source": str(Path(__file__).resolve()),
                    "font_file": str(font_file),
                    "font_type": type(font).__name__,
                    "font_size": font_size,
                    "text": text,
                    "text_bbox": text_bounds,
                    "pixel_bbox": pixel_bounds,
                    "width": visible_width,
                    "height": visible_height,
                }
                logger.debug(
                    "CLOCK_RENDER renderer=%s source=%s font=%s "
                    "font_type=%s font_size=%s text=%s text_bbox=%s "
                    "pixel_bbox=%s",
                    image.info["clock_render"]["renderer"],
                    image.info["clock_render"]["source"],
                    font_file,
                    type(font).__name__,
                    font_size,
                    text,
                    text_bounds,
                    pixel_bounds,
                )
                return font_size

        if not loaded_font:
            logger.error(
                "CLOCK_RENDER no loadable TrueType font found; Pillow bitmap "
                "fallback is disabled"
            )
            raise RuntimeError("No installed system TrueType font can render the clock")
        return None

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
