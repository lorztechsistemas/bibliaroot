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


def setup_i18n(domain: str = DOMAIN, preferred_language: str | None = None) -> gettext.NullTranslations:
    global _TRANSLATOR

    pref = (preferred_language or "").strip()
    if pref and pref.lower() != "system":
        languages = [pref]
    else:
        lang_env = os.getenv("LANGUAGE")
        languages = [lang_env] if lang_env else None
    try:
        if not languages:
            sys_lang, _enc = pylocale.getdefaultlocale()
            if sys_lang:
                languages = [sys_lang]
    except Exception:
        languages = None

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
