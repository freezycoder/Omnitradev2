from __future__ import annotations

import pytest

import config.settings as settings_module


def test_alert_settings_prefer_the_secrets_file(tmp_path, monkeypatch):
    secrets = tmp_path / "secrets.env"
    project = tmp_path / ".env"
    secrets.write_text(
        "\n".join(
            [
                "RESEND_API_KEY=from_secrets",
                "OMNITRADE_ALERT_FROM=OmniTrade research <alerts@example.com>",
                "OMNITRADE_ALERT_RECIPIENTS=a@example.com, b@example.com",
                "OMNITRADE_ALERT_DATABASE_URL=postgresql://db.example/omnitrade",
                "OMNITRADE_ALERT_TIMEZONE=Europe/Lisbon",
            ]
        ),
        encoding="utf-8",
    )
    project.write_text("RESEND_API_KEY=from_project\n", encoding="utf-8")
    monkeypatch.setattr(settings_module, "SECRETS_FILE", secrets)
    monkeypatch.setattr(settings_module, "ENV_FILE", project)
    monkeypatch.setenv("ENV", "production")
    for name in (
        "RESEND_API_KEY",
        "OMNITRADE_ALERT_FROM",
        "OMNITRADE_ALERT_RECIPIENTS",
        "OMNITRADE_ALERT_DATABASE_URL",
        "OMNITRADE_ALERT_TIMEZONE",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.warns(UserWarning, match="RESEND_API_KEY found in project .env"):
        loaded = settings_module._load_settings()

    assert loaded.resend_api_key == "from_secrets"
    assert loaded.alert_from == "OmniTrade research <alerts@example.com>"
    assert loaded.alert_recipients == ("a@example.com", "b@example.com")
    assert loaded.alert_database_url == "postgresql://db.example/omnitrade"
    assert loaded.alert_timezone == "Europe/Lisbon"


def test_alert_timezone_defaults_to_london(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_module, "SECRETS_FILE", tmp_path / "missing.env")
    monkeypatch.setattr(settings_module, "ENV_FILE", tmp_path / "missing-project.env")
    monkeypatch.delenv("OMNITRADE_ALERT_TIMEZONE", raising=False)
    monkeypatch.setenv("ENV", "production")

    loaded = settings_module._load_settings()

    assert loaded.alert_timezone == "Europe/London"
    assert loaded.alert_recipients == ()
