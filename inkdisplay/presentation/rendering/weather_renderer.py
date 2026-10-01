"""High-contrast 400x300 weather layout for monochrome e-paper."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from inkdisplay.domain.weather import ForecastDay, WeatherSnapshot

WIDTH = 400
HEIGHT = 300
ICON_SIZE = 96
WEEKDAY_LABELS = {
    "it": ("lun", "mar", "mer", "gio", "ven", "sab", "dom"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "es": ("lun", "mar", "mié", "jue", "vie", "sáb", "dom"),
    "fr": ("lun", "mar", "mer", "jeu", "ven", "sam", "dim"),
    "de": ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"),
}
UI_LABELS = {
    "it": ("DATI SCADUTI", "UMIDITÀ", "VENTO", "PRESSIONE", "PROSSIMI 3 GIORNI"),
    "en": ("STALE DATA", "HUMIDITY", "WIND", "PRESSURE", "NEXT 3 DAYS"),
    "es": ("DATOS ANTIGUOS", "HUMEDAD", "VIENTO", "PRESIÓN", "PRÓXIMOS 3 DÍAS"),
    "fr": ("DONNÉES ANCIENNES", "HUMIDITÉ", "VENT", "PRESSION", "3 JOURS À VENIR"),
    "de": ("DATEN VERALTET", "FEUCHTE", "WIND", "DRUCK", "NÄCHSTE 3 TAGE"),
}


def _font(
    size: int, bold: bool = False
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = (
        ("DejaVuSans-Bold.ttf", "arialbd.ttf")
        if bold
        else ("DejaVuSans.ttf", "arial.ttf")
    )
    candidates = [Path("/usr/share/fonts/truetype/dejavu") / name for name in names]
    candidates.extend(Path("C:/Windows/Fonts") / name for name in names)
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size=size)
        except OSError:
            continue
    return ImageFont.load_default()


@dataclass(frozen=True)
class WeatherDisplayOptions:
    show_humidity: bool = True
    show_wind: bool = True
    show_pressure: bool = True
    show_feels_like: bool = False
    show_forecast: bool = True


class WeatherRenderer:
    @staticmethod
    def icon_name(weather_code: int, is_day: bool = True) -> str:
        if weather_code == 0:
            return "sun" if is_day else "moon"
        if weather_code in {1, 2}:
            return "partly_cloudy"
        if weather_code == 3:
            return "cloudy"
        if weather_code in {45, 48}:
            return "fog"
        if weather_code in {71, 73, 75, 77, 85, 86}:
            return "snow"
        if weather_code in {95, 96, 99}:
            return "thunderstorm"
        if weather_code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
            return "rain"
        return "cloudy"

    def render_unavailable(self) -> Image.Image:
        image = Image.new("1", (WIDTH, HEIGHT), color=1)
        draw = ImageDraw.Draw(image)
        self._fit_text(
            draw, "METEO NON DISPONIBILE", (14, 96, 386, 136), 27, 19, True, 0
        )
        self._fit_text(
            draw,
            "Configura una località o attendi la rete",
            (14, 145, 386, 177),
            18,
            13,
            False,
            0,
        )
        return image

    def render(
        self,
        weather: WeatherSnapshot,
        options: WeatherDisplayOptions | None = None,
        *,
        now: datetime | None = None,
    ) -> Image.Image:
        options = options or WeatherDisplayOptions()
        image = Image.new("1", (WIDTH, HEIGHT), color=1)
        draw = ImageDraw.Draw(image)
        observed_at = self._observed_datetime(weather.observed_at)
        refreshed_at = self._observed_datetime(
            weather.refreshed_at or weather.observed_at
        )
        language = weather.language.lower().split("-", maxsplit=1)[0]
        labels = UI_LABELS.get(language, UI_LABELS["it"])
        self._fit_text(
            draw, weather.location.upper(), (12, 12, 295, 39), 24, 10, True, 0
        )
        self._fit_text(
            draw, refreshed_at.strftime("%H:%M"), (318, 12, 388, 39), 20, 13, True, 0
        )
        self._fit_text(
            draw,
            self.freshness_message(weather, now=now),
            (12, 42, 388, 61),
            14,
            10,
            True,
            0,
        )

        is_day = weather.is_day
        if is_day is None:
            is_day = 6 <= observed_at.hour < 18
        self._icon(image, weather.weather_code, 22, 69, 94, is_day=is_day)
        self._draw_temperature(
            draw, weather.temperature, weather.temperature_unit, (132, 64, 388, 128)
        )
        self._fit_text(
            draw,
            weather.description,
            (134, 129, 388, 155),
            22,
            12,
            True,
            0,
        )
        if options.show_feels_like and weather.feels_like is not None:
            self._fit_text(
                draw,
                f"Percepita {weather.feels_like:.0f}{weather.temperature_unit}",
                (135, 155, 388, 173),
                15,
                10,
                True,
                0,
            )

        metrics: list[tuple[str, str]] = []
        if options.show_humidity:
            metrics.append((labels[1], f"{weather.humidity}%"))
        if options.show_wind:
            metrics.append((labels[2], f"{weather.wind_speed:.0f} {weather.wind_unit}"))
        if options.show_pressure:
            metrics.append((labels[3], f"{weather.pressure:.0f} hPa"))
        if options.show_forecast:
            draw.line((12, 177, 387, 177), fill=0, width=1)
            self._draw_metrics(draw, metrics, top=180, height=34)
            draw.line((12, 216, 387, 216), fill=0, width=1)
        else:
            self._draw_metrics(draw, metrics, top=199, height=72)

        if options.show_forecast:
            draw.text((13, 218), labels[4], font=_font(13, True), fill=0)
            for index, forecast in enumerate(weather.forecast[:3]):
                self._forecast_day(image, draw, forecast, index, weather.language)
        return image

    @staticmethod
    def freshness_message(
        weather: WeatherSnapshot, *, now: datetime | None = None
    ) -> str:
        observed_at = WeatherRenderer._observed_datetime(
            weather.refreshed_at or weather.observed_at
        )
        current = now or datetime.now(observed_at.tzinfo or UTC)
        if current.tzinfo is None:
            current = current.replace(tzinfo=observed_at.tzinfo or UTC)
        age_minutes = max(0, int((current - observed_at).total_seconds() // 60))
        if weather.stale:
            return "OFFLINE · dati cache"
        return f"Aggiornato {age_minutes} min fa"

    @staticmethod
    def _observed_datetime(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(UTC)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _draw_metrics(
        draw: ImageDraw.ImageDraw,
        metrics: list[tuple[str, str]],
        *,
        top: int,
        height: int,
    ) -> None:
        if not metrics:
            return
        left = 18
        column_width = 364 / len(metrics)
        for index, (label, value) in enumerate(metrics):
            x = round(left + index * column_width)
            WeatherRenderer._fit_text(
                draw,
                label,
                (x, top, round(left + (index + 1) * column_width - 6), top + 18),
                14,
                9,
                True,
                0,
            )
            WeatherRenderer._fit_text(
                draw,
                value,
                (
                    x,
                    top + 19,
                    round(left + (index + 1) * column_width - 6),
                    top + height,
                ),
                20,
                12,
                True,
                0,
            )
            if index and index < len(metrics):
                draw.line((x - 8, top + 2, x - 8, top + height - 3), fill=0, width=1)

    @staticmethod
    def _draw_temperature(
        draw: ImageDraw.ImageDraw,
        temperature: float,
        unit: str,
        bounds: tuple[int, int, int, int],
    ) -> None:
        left, top, right, bottom = bounds
        number = f"{temperature:.0f}"
        has_degree = unit.startswith("°")
        unit_label = unit[-1] if has_degree else unit
        for size in range(62, 37, -1):
            number_font = _font(size, True)
            unit_font = _font(max(18, round(size * 0.58)), True)
            number_bounds = draw.textbbox((0, 0), number, font=number_font)
            unit_bounds = draw.textbbox((0, 0), unit_label, font=unit_font)
            degree_size = max(7, round(size * 0.13)) if has_degree else 0
            gap = max(5, round(size * 0.1))
            group_width = (
                number_bounds[2]
                - number_bounds[0]
                + gap
                + degree_size
                + (24 if has_degree else 0)
                + unit_bounds[2]
                - unit_bounds[0]
            )
            if group_width <= right - left:
                number_height = number_bounds[3] - number_bounds[1]
                unit_height = unit_bounds[3] - unit_bounds[1]
                number_y = top + (bottom - top - number_height) // 2
                number_x = left
                draw.text(
                    (number_x - number_bounds[0], number_y - number_bounds[1]),
                    number,
                    font=number_font,
                    fill=0,
                )
                unit_x = number_x + number_bounds[2] + gap
                unit_y = top + (bottom - top - unit_height) // 2
                if has_degree:
                    degree_y = unit_y - degree_size - 2
                    draw.ellipse(
                        (
                            unit_x,
                            degree_y,
                            unit_x + degree_size,
                            degree_y + degree_size,
                        ),
                        outline=0,
                        width=max(2, round(size * 0.04)),
                    )
                    unit_x += degree_size + 23
                draw.text(
                    (unit_x - unit_bounds[0], unit_y - unit_bounds[1]),
                    unit_label,
                    font=unit_font,
                    fill=0,
                )
                return

    @classmethod
    def _forecast_day(
        cls,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        forecast: ForecastDay,
        index: int,
        language: str,
    ) -> None:
        x = 12 + index * 125
        try:
            day = date.fromisoformat(forecast.date)
            weekday_labels = WEEKDAY_LABELS.get(
                language.lower().split("-", maxsplit=1)[0], WEEKDAY_LABELS["it"]
            )
            day_label = weekday_labels[day.weekday()] + f" {day.day:02d}"
        except ValueError:
            day_label = forecast.date[5:].replace("-", "/")
        cls._fit_text(
            draw, day_label, (x, 233, x + 125, 249), 14, 10, True, 0, center=True
        )
        cls._icon(image, forecast.weather_code, x + 51, 249, 23)
        cls._fit_text(
            draw,
            f"{forecast.temperature_min:.0f}° / {forecast.temperature_max:.0f}°",
            (x, 273, x + 125, 288),
            12,
            9,
            True,
            0,
            center=True,
        )

    @classmethod
    def _icon(
        cls,
        image: Image.Image,
        code: int,
        x: int,
        y: int,
        size: int,
        is_day: bool = True,
    ) -> None:
        icon = cls._draw_icon(cls.icon_name(code, is_day))
        icon = icon.resize((size, size), Image.Resampling.LANCZOS).convert(
            "1", dither=Image.Dither.NONE
        )
        image.paste(icon, (x, y))

    @staticmethod
    def _draw_icon(name: str) -> Image.Image:
        image = Image.new("L", (ICON_SIZE, ICON_SIZE), color=255)
        draw = ImageDraw.Draw(image)
        if name == "sun":
            WeatherRenderer._draw_sun(draw, 48, 47, 19, 0)
        elif name == "moon":
            draw.ellipse((18, 15, 78, 75), outline=0, width=5)
            draw.ellipse((39, 5, 91, 57), outline=0, width=3)
        elif name == "partly_cloudy":
            WeatherRenderer._draw_sun(draw, 36, 34, 15, 0)
            WeatherRenderer._draw_cloud(draw, 17, 32)
        elif name == "cloudy":
            WeatherRenderer._draw_cloud(draw, 8, 19)
        else:
            WeatherRenderer._draw_cloud(draw, 8, 12)
            if name == "rain":
                for x in (31, 49, 67):
                    draw.line((x, 71, x - 7, 87), fill=0, width=5)
            elif name == "thunderstorm":
                draw.polygon(
                    ((52, 62), (38, 81), (50, 81), (43, 97), (66, 73), (54, 73)),
                    fill=0,
                )
            elif name == "snow":
                for x in (32, 51, 70):
                    WeatherRenderer._draw_snowflake(draw, x, 82, 7)
            elif name == "fog":
                for y in (75, 84, 93):
                    draw.line((15, y, 80, y), fill=0, width=4)
        return image.convert("1", dither=Image.Dither.NONE)

    @staticmethod
    def _draw_sun(
        draw: ImageDraw.ImageDraw, x: int, y: int, radius: int, fill: int
    ) -> None:
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            start = radius + 5
            end = radius + 15
            draw.line(
                (
                    x + round(math.cos(radians) * start),
                    y + round(math.sin(radians) * start),
                    x + round(math.cos(radians) * end),
                    y + round(math.sin(radians) * end),
                ),
                fill=fill,
                width=4,
            )
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)

    @staticmethod
    def _draw_cloud(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
        points = (
            (x + 13, y + 57),
            (x + 9, y + 53),
            (x + 8, y + 47),
            (x + 10, y + 41),
            (x + 14, y + 37),
            (x + 20, y + 36),
            (x + 25, y + 38),
            (x + 27, y + 32),
            (x + 31, y + 27),
            (x + 37, y + 24),
            (x + 43, y + 25),
            (x + 49, y + 29),
            (x + 52, y + 35),
            (x + 52, y + 39),
            (x + 57, y + 37),
            (x + 63, y + 38),
            (x + 68, y + 42),
            (x + 70, y + 48),
            (x + 68, y + 53),
            (x + 64, y + 57),
            (x + 13, y + 57),
        )
        draw.line(points, fill=0, width=4, joint="curve")

    @staticmethod
    def _draw_snowflake(draw: ImageDraw.ImageDraw, x: int, y: int, radius: int) -> None:
        for angle in (0, 60, 120):
            radians = math.radians(angle)
            dx = round(math.cos(radians) * radius)
            dy = round(math.sin(radians) * radius)
            draw.line((x - dx, y - dy, x + dx, y + dy), fill=0, width=2)

    @staticmethod
    def _fit_text(
        draw: ImageDraw.ImageDraw,
        text: str,
        bounds: tuple[int, int, int, int],
        max_size: int,
        min_size: int,
        bold: bool,
        fill: int,
        center: bool = False,
    ) -> None:
        left, top, right, bottom = bounds
        for size in range(max_size, min_size - 1, -1):
            font = _font(size, bold)
            text_bounds = draw.textbbox((0, 0), text, font=font)
            width = text_bounds[2] - text_bounds[0]
            height = text_bounds[3] - text_bounds[1]
            if width <= right - left and height <= bottom - top:
                draw.text(
                    (
                        left
                        + ((right - left - width) // 2 if center else 0)
                        - text_bounds[0],
                        top - text_bounds[1],
                    ),
                    text,
                    font=font,
                    fill=fill,
                )
                return
        font = _font(min_size, bold)
        candidate = text
        while candidate:
            bounds_at_minimum = draw.textbbox((0, 0), candidate, font=font)
            if (
                bounds_at_minimum[2] - bounds_at_minimum[0] <= right - left
                and bounds_at_minimum[3] - bounds_at_minimum[1] <= bottom - top
            ):
                draw.text(
                    (left - bounds_at_minimum[0], top - bounds_at_minimum[1]),
                    candidate,
                    font=font,
                    fill=fill,
                )
                return
            candidate = candidate[:-2] + "…" if len(candidate) > 1 else ""
