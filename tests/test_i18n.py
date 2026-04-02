from app.i18n import resolved_language, system_language_preferences


def test_system_language_preferences_respect_environment_precedence(monkeypatch) -> None:
    monkeypatch.setenv("LANGUAGE", "en_US:es_ES")
    monkeypatch.setenv("LC_ALL", "fr_FR.UTF-8")
    monkeypatch.setenv("LC_MESSAGES", "de_DE.UTF-8")
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")

    languages = system_language_preferences()

    assert languages[:6] == ["en_US", "en", "es_ES", "es", "fr_FR", "fr"]
    assert resolved_language("system") == "en_US"


def test_resolved_language_uses_explicit_preference_over_system(monkeypatch) -> None:
    monkeypatch.setenv("LANGUAGE", "pt_BR")
    assert resolved_language("en") == "en"
    assert resolved_language("es_ES.UTF-8") == "es_ES"
