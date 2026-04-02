from __future__ import annotations

import gettext
import locale as pylocale
import os
from pathlib import Path

from .constants import APP_SLUG, LEGACY_APP_SLUG

DOMAIN = "bibliaapp"
_TRANSLATOR = gettext.NullTranslations()


def _candidate_locale_dirs() -> list[Path]:
    here = Path(__file__).resolve()
    return [
        here.parents[1] / "locale",
        Path.cwd() / "locale",
        Path(f"/app/share/{APP_SLUG}/locale"),
        Path(f"/app/share/{LEGACY_APP_SLUG}/locale"),
    ]


def _normalize_language_code(value: str) -> str:
    code = str(value or "").strip()
    if not code:
        return ""
    code = code.split(".", 1)[0].split("@", 1)[0].replace("-", "_")
    return code


def system_language_preferences() -> list[str]:
    languages: list[str] = []

    lang_env = os.getenv("LANGUAGE")
    if lang_env:
        languages.extend(part.strip() for part in lang_env.split(":") if part.strip())

    for env_name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.getenv(env_name)
        if value:
            languages.append(value)

    try:
        sys_lang, _enc = pylocale.getlocale(pylocale.LC_MESSAGES)
        if sys_lang:
            languages.append(sys_lang)
    except Exception:
        pass

    try:
        sys_lang, _enc = pylocale.getlocale()
        if sys_lang:
            languages.append(sys_lang)
    except Exception:
        pass

    normalized: list[str] = []
    seen: set[str] = set()
    for value in languages:
        code = _normalize_language_code(value)
        if not code or code.lower() == "c":
            continue
        base = code.split("_", 1)[0]
        for candidate in (code, base):
            if candidate and candidate not in seen:
                normalized.append(candidate)
                seen.add(candidate)
    return normalized


def resolved_language(preferred_language: str | None = None) -> str | None:
    pref = (preferred_language or "").strip()
    if pref and pref.lower() != "system":
        return _normalize_language_code(pref) or None
    languages = system_language_preferences()
    return languages[0] if languages else None


def setup_i18n(domain: str = DOMAIN, preferred_language: str | None = None) -> gettext.NullTranslations:
    global _TRANSLATOR

    pref = (preferred_language or "").strip()
    if pref and pref.lower() != "system":
        resolved = _normalize_language_code(pref)
        languages = [resolved] if resolved else None
    else:
        languages = system_language_preferences() or None

    for loc_dir in _candidate_locale_dirs():
        if not loc_dir.exists():
            continue
        _TRANSLATOR = gettext.translation(
            domain,
            localedir=str(loc_dir),
            languages=languages,
            fallback=True,
        )
        _TRANSLATOR.install(names=None)
        return _TRANSLATOR

    _TRANSLATOR = gettext.NullTranslations()
    _TRANSLATOR.install(names=None)
    return _TRANSLATOR


def _(message: str) -> str:
    return _TRANSLATOR.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _TRANSLATOR.ngettext(singular, plural, n)
