from pathlib import Path

from inkdisplay.app import create_app
from inkdisplay.application.plugins.weather_plugin import WeatherPlugin
from inkdisplay.extensions import db
from inkdisplay.infrastructure.persistence.models import (
    PluginSettings,
    Settings,
)


def _test_app(data_dir: Path):
    return create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DATA_DIR": data_dir,
            "SECRET_KEY": "integration-test-secret",
        }
    )


def test_settings_pages_render(tmp_path: Path) -> None:
    app = _test_app(tmp_path)
    client = app.test_client()

    assert client.get("/settings/plugins").status_code == 200
    weather_page = client.get("/settings/weather")
    assert weather_page.status_code == 200
    for option in (
        b"show_humidity",
        b"show_wind",
        b"show_pressure",
        b"show_feels_like",
        b"show_forecast",
    ):
        assert option in weather_page.data


def test_plugin_intervals_are_validated_and_persisted(tmp_path: Path) -> None:
    app = _test_app(tmp_path)
    client = app.test_client()

    response = client.post(
        "/settings/plugins",
        data={
            "clock_enabled": "on",
            "clock_refresh_interval": "1",
            "weather_enabled": "on",
            "weather_refresh_interval": "30",
            "rotation_interval_minutes": "10",
        },
    )

    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(PluginSettings, "clock").refresh_interval_minutes == 1
        assert db.session.get(PluginSettings, "weather").refresh_interval_minutes == 30
        assert db.session.get(Settings, 1).rotation_interval_minutes == 10

    invalid = client.post(
        "/settings/plugins",
        data={
            "clock_refresh_interval": "0",
            "weather_refresh_interval": "30",
            "rotation_interval_minutes": "10",
        },
    )

    assert invalid.status_code == 400


def test_weather_configuration_persists_and_never_echoes_api_key(
    tmp_path: Path,
) -> None:
    app = _test_app(tmp_path)
    client = app.test_client()
    api_key = "owm-test-key-not-for-display"

    response = client.post(
        "/settings/weather",
        data={
            "provider": "openweathermap",
            "latitude": "41.9028",
            "longitude": "12.4964",
            "city": "Roma",
            "timezone": "Europe/Rome",
            "units": "metric",
            "language": "it",
            "openweather_api_key": api_key,
            "show_humidity": "on",
            "show_pressure": "on",
            "show_feels_like": "on",
            "show_forecast": "on",
        },
    )

    assert response.status_code == 200
    assert api_key.encode() not in response.data
    assert b"Chiave configurata" in response.data
    with app.app_context():
        settings = db.session.get(Settings, 1)
        assert settings.weather_provider == "openweathermap"
        assert settings.openweather_api_key_encrypted != api_key
        parameters = db.session.get(PluginSettings, "weather").parameters
        assert parameters == {
            "show_humidity": True,
            "show_wind": False,
            "show_pressure": True,
            "show_feels_like": True,
            "show_forecast": True,
        }
        display_options = WeatherPlugin._display_options()
        assert display_options.show_humidity is True
        assert display_options.show_wind is False
        assert display_options.show_pressure is True
        assert display_options.show_feels_like is True
        assert display_options.show_forecast is True

    restarted_app = _test_app(tmp_path)
    with restarted_app.app_context():
        settings = db.session.get(Settings, 1)
        assert settings.latitude == 41.9028
        assert settings.city == "Roma"
        assert settings.openweather_api_key_encrypted != api_key
