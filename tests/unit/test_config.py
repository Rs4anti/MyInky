import pytest

from inkdisplay.config import AppSettings, ConfigurationError


def test_defaults_use_rome_and_mock() -> None:
    settings = AppSettings(timezone="Europe/Rome", secret_key="test-key")

    settings.validate()

    assert settings.display_mode == "mock"
    assert settings.port == 5000


def test_waveshare_mode_is_a_valid_bootstrap_value() -> None:
    settings = AppSettings(display_mode="waveshare", secret_key="test-key")

    settings.validate()

    assert settings.display_mode == "waveshare"


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("port", 0, "between 1 and 65535"),
        ("port", 65536, "between 1 and 65535"),
        ("timezone", "Mars/Olympus", "Unknown timezone"),
        ("display_mode", "unknown", "must be 'mock' or 'waveshare'"),
    ],
)
def test_invalid_settings_are_rejected(
    attribute: str, value: object, message: str
) -> None:
    settings = AppSettings(secret_key="test-key", **{attribute: value})

    with pytest.raises(ConfigurationError, match=message):
        settings.validate()
