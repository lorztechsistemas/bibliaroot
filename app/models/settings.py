from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass
class UserSettings:
    translation: str = "ARA"
    font_scale: float = 1.0
    last_book: str = "Joao"
    last_chapter: int = 3
    last_book_id: int | None = None
    theme_mode: str = "system"  # system | light | dark
    ui_language: str = "system"  # system | pt_BR | en | es
    reading_layout: str = "cards"  # cards | continuous
    tts_voice_language: str = "auto"  # auto | pt-br | en | es | fr | de | it
    tts_engine: str = "piper"  # piper (mantido por compatibilidade de settings)
    daily_content_enabled: bool = False
    daily_content_mode: str = "verse"  # verse | study | outline
    daily_content_translation: str = ""  # vazio = usar tradução ativa
    daily_content_time: str = "08:00"
    daily_content_end_time: str = "08:00"
    daily_messages_per_day: int = 1
    daily_interval_minutes: int = 180
    daily_notification_persistent: bool = True
    daily_delivery_mode: str = "native"  # native | popup
    daily_sound_enabled: bool = False
    daily_sound_name: str = "soft"
    reading_history: list[dict[str, Any]] = field(default_factory=list)


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path("data/user/settings.json")

    def load(self) -> UserSettings:
        if not self.path.exists():
            return UserSettings()
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return UserSettings()
        if not isinstance(raw, dict):
            return UserSettings()

        defaults = asdict(UserSettings())
        defaults.update({k: v for k, v in raw.items() if k in defaults})
        history = defaults.get("reading_history")
        if not isinstance(history, list):
            defaults["reading_history"] = []
        return UserSettings(**defaults)

    def save(self, settings: UserSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(asdict(settings), fh, ensure_ascii=False, indent=2)

    def update(self, **fields: Any) -> UserSettings:
        current = self.load()
        for key, value in fields.items():
            if hasattr(current, key):
                setattr(current, key, value)
        self.save(current)
        return current

    def record_reading(
        self,
        *,
        translation: str,
        book: str,
        chapter: int,
        book_id: int | None = None,
        max_items: int = 30,
    ) -> UserSettings:
        settings = self.load()
        settings.translation = translation
        settings.last_book = book
        settings.last_chapter = chapter
        settings.last_book_id = book_id

        entry = {
            "translation": translation,
            "book": book,
            "chapter": int(chapter),
            "book_id": book_id,
        }
        settings.reading_history = [
            item
            for item in settings.reading_history
            if not (
                isinstance(item, dict)
                and item.get("translation") == entry["translation"]
                and item.get("book") == entry["book"]
                and int(item.get("chapter", -1)) == entry["chapter"]
            )
        ]
        settings.reading_history.insert(0, entry)
        settings.reading_history = settings.reading_history[: max(1, int(max_items))]
        self.save(settings)
        return settings
