from __future__ import annotations


PREFIX_LANGUAGE_MAP = {
    "Por": "pt",
    "Spa": "es",
    "Fre": "fr",
    "Ger": "de",
    "Dut": "nl",
    "Swe": "sv",
    "Nor": "no",
    "Rus": "ru",
    "Ukr": "uk",
    "Pol": "pl",
    "Cze": "cs",
    "Cro": "hr",
    "Hun": "hu",
    "Jap": "ja",
    "Kor": "ko",
    "Chi": "zh",
    "Heb": "he",
    "Gre": "el",
    "Arm": "hy",
    "Alb": "sq",
    "Thai": "th",
    "Viet": "vi",
    "Tag": "tl",
    "Tpi": "tpi",
    "Mal": "ml",
    "Fin": "fi",
    "Est": "et",
    "Esperanto": "eo",
    "Maori": "mi",
    "Haitian": "ht",
    "Manx": "gv",
    "Wulfila": "got",
    "Peshitta": "syr",
    "TR": "grc",
    "WLC": "he",
    "JPS": "he",
    "CSl": "cu",
    "Cop": "cop",
}

EXACT_LANGUAGE_MAP = {
    "ACF": "pt",
    "ARA": "pt",
    "ARC": "pt",
    "AS21": "pt",
    "NAA": "pt",
    "NBV": "pt",
    "NTLH": "pt",
    "NVI": "pt",
    "NVT": "pt",
    "TB": "pt",
    "JFAA": "pt",
    "KJA": "pt",
    "KJF": "pt",
    "KJV": "en",
    "AKJV": "en",
    "ASV": "en",
    "BBE": "en",
    "BSB": "en",
    "Darby": "en",
    "Geneva1599": "en",
    "KJVA": "en",
    "KJVPCE": "en",
    "LEB": "en",
    "LITV": "en",
    "MKJV": "en",
    "NHEB": "en",
    "NHEBJE": "en",
    "NHEBME": "en",
    "OEB": "en",
    "OEBcth": "en",
    "RWebster": "en",
    "Rotherham": "en",
    "Tyndale": "en",
    "Twenty": "en",
    "UKJV": "en",
    "Webster": "en",
    "Wycliffe": "en",
    "YLT": "en",
    "Anderson": "en",
    "Haweis": "en",
    "Jubilee2000": "en",
    "Noyes": "en",
    "RLT": "en",
    "RNKJV": "en",
    "ACV": "en",
    "Byz": "grc",
    "CPDV": "en",
    "DRC": "en",
    "KLV": "en",
    "SP": "en",
    "StatResGNT": "en",
    "Vulgate": "la",
    "VulgClementine": "la",
    "VulgConte": "la",
    "VulgHetzenauer": "la",
    "VulgSistine": "la",
}

TITLE_KEYWORDS = {
    "albanian": "sq",
    "armenian": "hy",
    "english": "en",
    "king james": "en",
    "american standard": "en",
    "latin": "la",
    "vulgate": "la",
    "greek": "el",
    "hebrew": "he",
    "portuguese": "pt",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "russian": "ru",
    "ukrainian": "uk",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
}


def infer_language_code(translation_code: str, title: str | None = None) -> str:
    code = str(translation_code or "").strip()
    if not code:
        return ""
    if code in EXACT_LANGUAGE_MAP:
        return EXACT_LANGUAGE_MAP[code]
    for prefix, lang in PREFIX_LANGUAGE_MAP.items():
        if code.startswith(prefix):
            return lang
    low_title = (title or "").casefold()
    for keyword, lang in TITLE_KEYWORDS.items():
        if keyword in low_title:
            return lang
    return ""
