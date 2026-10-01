from datetime import UTC, datetime
from pathlib import Path

import pytest
import requests
from PIL import Image, ImageDraw

from inkdisplay.application.services.weather_service import WeatherUnavailable
from inkdisplay.domain.weather import ForecastDay, WeatherSnapshot
from inkdisplay.infrastructure.persistence.models import WeatherCache
from inkdisplay.infrastructure.weather.common import (
    WeatherProviderError,
    get_json,
    openweather_to_wmo,
    weather_description,
)
from inkdisplay.infrastructure.weather.open_meteo import OpenMeteoProvider
from inkdisplay.infrastructure.weather.open_weather_map import OpenWeatherMapProvider
from inkdisplay.infrastructure.weather.request import WeatherRequest
from inkdisplay.presentation.rendering.weather_renderer import (
    WeatherDisplayOptions,
    WeatherRenderer,
)


def _ink_bbox(image: Image.Image) -> tuple[int, int, int, int] | None:
    return Image.eval(image.convert("L"), lambda value: 255 - value).getbbox()


def test_weather_renderer_returns_epaper_frame() -> None:
    snapshot = WeatherSnapshot(
        location="Roma",
        observed_at="2026-09-27T12:30:00+02:00",
        weather_code=61,
        description="Pioggia",
        temperature=21.5,
        humidity=68,
        wind_speed=12.0,
        pressure=1012,
        forecast=(
            ForecastDay("2026-09-28", 2, 16, 24),
            ForecastDay("2026-09-29", 0, 17, 26),
            ForecastDay("2026-09-30", 3, 18, 25),
        ),
        stale=True,
    )

    image = WeatherRenderer().render(snapshot)
    unavailable = WeatherRenderer().render_unavailable()

    assert image.size == unavailable.size == (400, 300)
    assert image.mode == unavailable.mode == "1"
    assert image.getbbox() is not None
    assert unavailable.crop((0, 0, 400, 60)).convert("L").getextrema() == (
        255,
        255,
    )
    assert len(snapshot.forecast) == 3


def test_weather_renderer_hides_disabled_details_and_forecast() -> None:
    snapshot = WeatherSnapshot(
        location="Brescia",
        observed_at="2026-09-27T10:25:00+02:00",
        weather_code=0,
        description="Sereno",
        temperature=21,
        humidity=63,
        wind_speed=12,
        pressure=1018,
        forecast=(ForecastDay("2026-09-28", 2, 16, 22),),
    )
    image = WeatherRenderer().render(
        snapshot,
        WeatherDisplayOptions(
            show_humidity=False,
            show_wind=False,
            show_pressure=False,
            show_forecast=False,
        ),
    )

    assert image.crop((0, 175, 400, 219)).convert("L").getextrema() == (255, 255)
    assert image.crop((0, 230, 400, 300)).convert("L").getextrema() == (255, 255)


def test_weather_temperature_uses_font_independent_degree_mark() -> None:
    with_degree = Image.new("1", (300, 70), color=255)
    without_degree = Image.new("1", (300, 70), color=255)

    WeatherRenderer._draw_temperature(
        ImageDraw.Draw(with_degree), 18, "°C", (0, 0, 290, 64)
    )
    WeatherRenderer._draw_temperature(
        ImageDraw.Draw(without_degree), 18, "C", (0, 0, 290, 64)
    )

    assert with_degree.tobytes() != without_degree.tobytes()


def test_weather_renderer_fits_long_city_names_and_optional_feels_like() -> None:
    snapshot = WeatherSnapshot(
        location="San Valentino in Abruzzo Citeriore",
        observed_at="2026-09-27T10:25:00+02:00",
        weather_code=2,
        description="Parzialmente nuvoloso",
        temperature=21,
        humidity=63,
        wind_speed=12,
        pressure=1018,
        forecast=(ForecastDay("2026-09-28", 2, 16, 22),),
        feels_like=19.5,
    )

    with_feels_like = WeatherRenderer().render(
        snapshot, WeatherDisplayOptions(show_feels_like=True)
    )
    without_feels_like = WeatherRenderer().render(snapshot)

    assert with_feels_like.size == (400, 300)
    assert with_feels_like.mode == "1"
    assert with_feels_like.crop((125, 150, 390, 171)).tobytes() != (
        without_feels_like.crop((125, 150, 390, 171)).tobytes()
    )


def test_current_temperature_occupies_a_large_readable_region() -> None:
    snapshot = WeatherSnapshot(
        location="Roma",
        observed_at="2026-10-01T22:16:00+02:00",
        weather_code=0,
        description="Sereno",
        temperature=18,
        humidity=50,
        wind_speed=5,
        pressure=1015,
        forecast=(),
    )
    image = WeatherRenderer().render(
        snapshot, WeatherDisplayOptions(show_forecast=False)
    )
    temperature_bounds = _ink_bbox(image.crop((132, 64, 388, 144)))

    assert temperature_bounds is not None
    assert temperature_bounds[3] - temperature_bounds[1] >= 55


def test_weather_layout_uses_three_forecast_columns_without_clipping() -> None:
    snapshot = WeatherSnapshot(
        location="San Valentino in Abruzzo Citeriore",
        observed_at="2026-10-01T20:08:00+02:00",
        weather_code=3,
        description="Nuvoloso",
        temperature=18,
        feels_like=17,
        humidity=69,
        wind_speed=13,
        pressure=1028,
        forecast=(
            ForecastDay("2026-10-02", 2, 13, 18),
            ForecastDay("2026-10-03", 61, 11, 17),
            ForecastDay("2026-10-04", 0, 12, 19),
        ),
    )
    image = WeatherRenderer().render(
        snapshot, WeatherDisplayOptions(show_feels_like=True)
    )
    ink = _ink_bbox(image)

    assert image.size == (400, 300)
    assert image.mode == "1"
    assert image.crop((0, 0, 400, 4)).convert("L").getextrema() == (255, 255)
    assert (
        ink is not None
        and ink[0] >= 12
        and ink[1] >= 12
        and ink[2] <= 388
        and ink[3] <= 288
    )
    for left, right in ((0, 126), (126, 252), (252, 400)):
        assert _ink_bbox(image.crop((left, 232, right, 300))) is not None


def test_weather_without_optional_rows_or_forecast_has_no_empty_labels() -> None:
    snapshot = WeatherSnapshot(
        location="Brescia",
        observed_at="2026-10-01T20:08:00+02:00",
        weather_code=0,
        description="Sereno",
        temperature=18,
        humidity=69,
        wind_speed=13,
        pressure=1028,
        forecast=(),
    )
    image = WeatherRenderer().render(
        snapshot,
        WeatherDisplayOptions(
            show_humidity=False,
            show_wind=False,
            show_pressure=False,
            show_feels_like=True,
            show_forecast=False,
        ),
    )

    assert _ink_bbox(image.crop((0, 180, 400, 299))) is None


@pytest.mark.parametrize(
    ("code", "is_day", "icon_name"),
    [
        (0, True, "sun"),
        (0, False, "moon"),
        (2, True, "partly_cloudy"),
        (3, True, "cloudy"),
        (2, False, "partly_cloudy_night"),
        (3, False, "cloudy_night"),
        (61, True, "rain"),
        (61, False, "rain_night"),
        (95, True, "thunderstorm"),
        (95, False, "storm_night"),
        (73, True, "snow"),
        (45, True, "fog"),
    ],
)
def test_weather_icon_mapping_and_one_bit_scaling(
    code: int, is_day: bool, icon_name: str
) -> None:
    renderer = WeatherRenderer()
    icon = renderer._draw_icon(renderer.icon_name(code, is_day))
    scaled = icon.resize((88, 88), Image.Resampling.LANCZOS).convert("1")

    assert renderer.icon_name(code, is_day) == icon_name
    assert scaled.size == (88, 88)
    assert scaled.mode == "1"
    assert scaled.getextrema() == (0, 255)


def test_2216_local_time_never_draws_sun_for_current_conditions(monkeypatch) -> None:
    snapshot = WeatherSnapshot(
        location="Roma",
        observed_at="2026-10-01T22:16:00+02:00",
        weather_code=0,
        description="Sereno",
        temperature=18,
        humidity=50,
        wind_speed=5,
        pressure=1015,
        forecast=(),
        is_day=True,
    )

    def unexpected_sun(*args) -> None:
        pytest.fail("Nighttime current conditions must not draw a sun")

    monkeypatch.setattr(WeatherRenderer, "_draw_sun", staticmethod(unexpected_sun))
    image = WeatherRenderer().render(
        snapshot, WeatherDisplayOptions(show_forecast=False)
    )

    assert WeatherRenderer._is_daylight(snapshot) is False
    assert image.size == (400, 300)
    assert image.mode == "1"


def test_local_noon_is_daylight_even_if_day_flag_disagrees() -> None:
    snapshot = WeatherSnapshot(
        location="Roma",
        observed_at="2026-10-01T12:00:00+02:00",
        weather_code=0,
        description="Sereno",
        temperature=18,
        humidity=50,
        wind_speed=5,
        pressure=1015,
        forecast=(),
        is_day=False,
    )

    assert WeatherRenderer._is_daylight(snapshot) is True


def test_sunrise_and_sunset_override_local_hour_fallback() -> None:
    snapshot = WeatherSnapshot(
        location="Roma",
        observed_at="2026-10-01T19:00:00+02:00",
        weather_code=0,
        description="Sereno",
        temperature=18,
        humidity=50,
        wind_speed=5,
        pressure=1015,
        forecast=(),
        is_day=False,
    )
    object.__setattr__(snapshot, "sunrise", "2026-10-01T06:30:00+02:00")
    object.__setattr__(snapshot, "sunset", "2026-10-01T20:30:00+02:00")
    assert WeatherRenderer._is_daylight(snapshot) is True

    object.__setattr__(snapshot, "observed_at", "2026-10-01T21:00:00+02:00")
    assert WeatherRenderer._is_daylight(snapshot) is False


def test_open_meteo_parser_maps_current_and_three_forecast_days() -> None:
    payload = {
        "current": {
            "time": "2026-09-27T12:00",
            "weather_code": 61,
            "temperature_2m": 20.5,
            "apparent_temperature": 19.5,
            "relative_humidity_2m": 70,
            "wind_speed_10m": 10.0,
            "pressure_msl": 1013.0,
        },
        "daily": {
            "time": ["2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30"],
            "weather_code": [61, 2, 0, 3],
            "temperature_2m_min": [15, 14, 16, 17],
            "temperature_2m_max": [21, 22, 24, 23],
        },
    }
    request = WeatherRequest(41.9, 12.5, "Roma", "Europe/Rome", "metric", "it")

    snapshot = OpenMeteoProvider._parse(payload, request, "Roma")

    assert snapshot.location == "Roma"
    assert snapshot.description == "Pioggia"
    assert snapshot.feels_like == 19.5
    assert len(snapshot.forecast) == 3
    assert snapshot.forecast[0].temperature_min == 14
    english_request = WeatherRequest(41.9, 12.5, "Rome", "Europe/Rome", "metric", "en")
    english_snapshot = OpenMeteoProvider._parse(payload, english_request, "Rome")
    assert english_snapshot.description == "Rain"
    assert weather_description(0, "en-US") == "Clear"


def test_openweathermap_parser_groups_forecast_and_normalizes_codes() -> None:
    current = {
        "dt": 1769572800,
        "name": "Roma",
        "main": {
            "temp": 18,
            "feels_like": 17.5,
            "humidity": 60,
            "pressure": 1011,
        },
        "weather": [{"id": 500, "description": "pioggia leggera"}],
        "wind": {"speed": 4.0},
    }
    forecast = {
        "list": [
            {
                "dt_txt": f"2026-01-{day:02d} 12:00:00",
                "main": {"temp_min": 10 + day, "temp_max": 20 + day},
                "weather": [{"id": 800, "description": "clear"}],
            }
            for day in (29, 30, 31)
        ]
    }
    request = WeatherRequest(41.9, 12.5, None, "UTC", "metric", "it", "secret")

    snapshot = OpenWeatherMapProvider._parse(current, forecast, request)

    assert snapshot.location == "Roma"
    assert snapshot.weather_code == 61
    assert snapshot.feels_like == 17.5
    assert len(snapshot.forecast) == 3
    assert snapshot.forecast[1].temperature_max == 50
    assert openweather_to_wmo(800) == 0


def test_http_provider_timeout_is_translated_without_leaking_details() -> None:
    class TimeoutResponse:
        def get(self, *args, **kwargs):
            assert kwargs["timeout"] == (3.05, 8.0)
            raise requests.Timeout("private transport detail")

    with pytest.raises(WeatherProviderError, match="request failed"):
        get_json(TimeoutResponse(), "https://example.invalid", params={})  # type: ignore[arg-type]


def test_weather_service_uses_persisted_snapshot_when_offline(
    tmp_path, monkeypatch
) -> None:
    from inkdisplay.app import create_app
    from inkdisplay.application.plugins.weather_plugin import WeatherPlugin
    from inkdisplay.domain.weather import WeatherSnapshot
    from inkdisplay.infrastructure.weather.common import WeatherProviderError

    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})
    snapshot = WeatherSnapshot(
        location="Roma",
        observed_at="2026-09-27T12:00:00+02:00",
        weather_code=0,
        description="Sereno",
        temperature=25,
        humidity=40,
        wind_speed=5,
        pressure=1015,
        forecast=(ForecastDay("2026-09-28", 0, 16, 27),),
    )

    class OfflineProvider:
        name = "open-meteo"
        calls = 0

        def fetch(self, request):
            self.calls += 1
            raise WeatherProviderError("offline")

    provider = OfflineProvider()
    with app.app_context():
        db = app.extensions["sqlalchemy"]
        db.session.add(
            WeatherCache(
                id=1,
                payload=snapshot.to_dict(),
                fetched_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            )
        )
        db.session.commit()
        service = app.extensions["inkdisplay.weather_service"]
        monkeypatch.setattr(service, "_providers", {"open-meteo": provider})

        stale = service.refresh(force=True)

        assert stale.location == "Roma"
        assert stale.stale is True
        assert provider.calls == 1
        displayed = WeatherPlugin._with_refresh_timestamp(stale)
        assert displayed.refreshed_at == "2026-09-27T14:00:00+02:00"
        status = WeatherRenderer.freshness_message(
            displayed, now=datetime(2026, 9, 27, 14, 0, tzinfo=UTC)
        )
        assert status == "OFFLINE · dati cache"


def test_weather_render_plugin_does_not_fetch_on_each_render(
    tmp_path, monkeypatch
) -> None:
    from inkdisplay.app import create_app
    from inkdisplay.application.plugins.weather_plugin import WeatherPlugin
    from inkdisplay.infrastructure.weather.common import WeatherProviderError

    app = create_app({"TESTING": True, "DATA_DIR": tmp_path, "SECRET_KEY": "test"})

    class OfflineProvider:
        name = "open-meteo"
        calls = 0

        def fetch(self, request):
            self.calls += 1
            raise WeatherProviderError("offline")

    provider = OfflineProvider()
    with app.app_context():
        service = app.extensions["inkdisplay.weather_service"]
        monkeypatch.setattr(service, "_providers", {"open-meteo": provider})
        with pytest.raises(WeatherUnavailable):
            service.refresh(force=True)
        plugin = WeatherPlugin(service, WeatherRenderer())
        plugin.render()
        plugin.render()
        assert provider.calls == 1
        preview_path = Path(tmp_path) / "previews" / "weather-preview.png"
        with Image.open(preview_path) as preview:
            assert preview.size == (400, 300)
            assert preview.mode == "1"
