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
        draw.rectangle((0, 0, WIDTH, 37), fill=0)
        draw.text((14, 7), "METEO", font=_font(22, True), fill=1)
        draw.text((30, 112), "DATI METEO NON DISPONIBILI", font=_font(20, True), fill=0)
        draw.text(
            (58, 147),
            "Configura una località o attendi la rete",
            font=_font(14),
            fill=0,
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
        draw.rectangle((0, 0, WIDTH, 37), fill=0)
        self._fit_text(
            draw, weather.location.upper(), (12, 5, 285, 32), 24, 13, True, 1
        )
        draw.text(
            (322, 9), refreshed_at.strftime("%H:%M"), font=_font(20, True), fill=1
        )
        self._fit_text(
            draw,
            self.freshness_message(weather, now=now),
            (12, 41, 388, 58),
            12,
            9,
            True,
            0,
        )

        is_day = weather.is_day
        if is_day is None:
            is_day = 6 <= observed_at.hour < 18
        self._icon(image, weather.weather_code, 24, 66, 88, is_day=is_day)
        temperature = f"{weather.temperature:.0f}{weather.temperature_unit}"
        self._fit_text(draw, temperature, (130, 64, 390, 127), 58, 39, True, 0)
        self._fit_text(
            draw,
            weather.description,
            (134, 127, 389, 153),
            23,
            13,
            True,
            0,
        )
        if options.show_feels_like and weather.feels_like is not None:
            draw.text(
                (135, 151),
                f"Percepita {weather.feels_like:.0f}{weather.temperature_unit}",
                font=_font(12, True),
                fill=0,
            )

        draw.line((12, 174, 388, 174), fill=0, width=1)
        metrics: list[tuple[str, str]] = []
        if options.show_humidity:
            metrics.append((labels[1], f"{weather.humidity}%"))
        if options.show_wind:
            metrics.append((labels[2], f"{weather.wind_speed:.0f} {weather.wind_unit}"))
        if options.show_pressure:
            metrics.append((labels[3], f"{weather.pressure:.0f} hPa"))
        self._draw_metrics(draw, metrics)
        draw.line((12, 219, 388, 219), fill=0, width=1)

        if options.show_forecast:
            draw.text((13, 222), labels[4], font=_font(13, True), fill=0)
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
        age_text = f"Dati aggiornati {age_minutes} minuti fa"
        if weather.stale:
            return f"OFFLINE - dati da cache · {age_text}"
        return age_text

    @staticmethod
    def _observed_datetime(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(UTC)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _draw_metrics(
        draw: ImageDraw.ImageDraw, metrics: list[tuple[str, str]]
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
                (x, 179, round(left + (index + 1) * column_width - 6), 196),
                13,
                10,
                True,
                0,
            )
            WeatherRenderer._fit_text(
                draw,
                value,
                (x, 197, round(left + (index + 1) * column_width - 6), 216),
                18,
                11,
                True,
                0,
            )
            if index and index < len(metrics):
                draw.line((x - 8, 181, x - 8, 212), fill=0, width=1)

    @classmethod
    def _forecast_day(
        cls,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        forecast: ForecastDay,
        index: int,
        language: str,
    ) -> None:
        x = 12 + index * 126
        try:
            day = date.fromisoformat(forecast.date)
            weekday_labels = WEEKDAY_LABELS.get(
                language.lower().split("-", maxsplit=1)[0], WEEKDAY_LABELS["it"]
            )
            day_label = weekday_labels[day.weekday()] + f" {day.day:02d}"
        except ValueError:
            day_label = forecast.date[5:].replace("-", "/")
        cls._fit_text(draw, day_label, (x, 239, x + 70, 256), 14, 11, True, 0)
        cls._icon(image, forecast.weather_code, x + 78, 237, 25)
        draw.text(
            (x + 8, 278),
            f"{forecast.temperature_min:.0f}° / {forecast.temperature_max:.0f}°",
            font=_font(13, True),
            fill=0,
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
            draw.ellipse((18, 15, 78, 75), fill=0)
            draw.ellipse((39, 5, 91, 57), fill=255)
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
        draw.ellipse((x + 5, y + 24, x + 45, y + 65), fill=0)
        draw.ellipse((x + 25, y + 7, x + 66, y + 65), fill=0)
        draw.ellipse((x + 48, y + 25, x + 80, y + 65), fill=0)
        draw.rectangle((x + 17, y + 42, x + 68, y + 66), fill=0)

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
    ) -> None:
        left, top, right, _ = bounds
        for size in range(max_size, min_size - 1, -1):
            font = _font(size, bold)
            if draw.textbbox((0, 0), text, font=font)[2] <= right - left:
                draw.text((left, top), text, font=font, fill=fill)
                return
        draw.text((left, top), text[:30], font=_font(min_size, bold), fill=fill)
