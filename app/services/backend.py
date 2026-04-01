from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import json
from typing import Any

from app.constants import APP_NAME, APP_SLUG, LEGACY_APP_SLUG
from app.models.bible_db import BibleDB
from app.models.favorites import FavoritesStore
from app.models.settings import SettingsStore, UserSettings
from app.models.study import StudyStore
from app.services.daily_content import DailyContent, DailyContentService


@dataclass
class BackendState:
    translation: str
    translations: list[str]
    settings: UserSettings


class BibleBackend:
    def __init__(
        self,
        *,
        bibles_dir: Path | None = None,
        favorites_db: Path | None = None,
        settings_file: Path | None = None,
        study_db: Path | None = None,
    ) -> None:
        resolved_bibles_dir = bibles_dir or self._default_bibles_dir()
        user_data_dir = self._user_data_dir()
        user_config_dir = self._user_config_dir()
        self.db = BibleDB(data_dir=resolved_bibles_dir)
        self.favorites = FavoritesStore(db_path=favorites_db or (user_data_dir / "favorites.db"))
        self.settings = SettingsStore(path=settings_file or (user_config_dir / "settings.json"))
        self.study = StudyStore(db_path=study_db or (user_data_dir / "study.db"))
        self.daily = DailyContentService(self.db)

    @staticmethod
    def _project_root() -> Path:
        return Path(__file__).resolve().parents[2]

    @classmethod
    def _default_bibles_dir(cls) -> Path:
        env_dir = os.getenv("BIBLIAROOT_BIBLES_DIR") or os.getenv("BIBLIAAPP_BIBLES_DIR")
        if env_dir:
            return Path(env_dir)

        local_dir = cls._project_root() / "data" / "bibles"
        if local_dir.exists():
            return local_dir

        for packaged_dir in (
            Path(f"/app/share/{APP_SLUG}/data/bibles"),
            Path(f"/app/share/{LEGACY_APP_SLUG}/data/bibles"),
        ):
            if packaged_dir.exists():
                return packaged_dir

        return local_dir

    @staticmethod
    def _user_data_dir() -> Path:
        xdg_data_home = os.getenv("XDG_DATA_HOME")
        base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
        preferred = base / APP_SLUG
        legacy = base / LEGACY_APP_SLUG
        if preferred.exists() or not legacy.exists():
            return preferred
        return legacy

    @staticmethod
    def _user_config_dir() -> Path:
        xdg_config_home = os.getenv("XDG_CONFIG_HOME")
        base = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
        preferred = base / APP_SLUG
        legacy = base / LEGACY_APP_SLUG
        if preferred.exists() or not legacy.exists():
            return preferred
        return legacy

    def initialize(self) -> BackendState:
        self.favorites.init()
        self.study.init()
        settings = self.settings.load()
        translations = self.db.available_translations()
        if not translations:
            return BackendState(
                translation=settings.translation,
                translations=[],
                settings=settings,
            )
        translation = settings.translation if settings.translation in translations else translations[0]
        self.db.set_translation(translation)
        if translation != settings.translation:
            settings = self.settings.update(translation=translation)
        return BackendState(translation=translation, translations=translations, settings=settings)

    def set_translation(self, translation: str) -> str:
        translations = self.db.available_translations()
        if translation not in translations:
            raise ValueError(f"Traducao indisponivel: {translation}")
        self.db.set_translation(translation)
        self.settings.update(translation=translation)
        return translation

    def list_translations(self) -> list[str]:
        return self.db.available_translations()

    def list_translation_catalog(self) -> list[dict[str, str]]:
        catalog: list[dict[str, str]] = []
        for code in self.db.available_translations():
            meta = self.db.get_translation_metadata(code)
            name = meta.get("copyright") or meta.get("name") or code
            language = (meta.get("language") or "").strip()
            if language:
                label = f"{code} [{language}] - {name}"
            else:
                label = f"{code} - {name}"
            catalog.append({"code": code, "label": label, "language": language})
        return catalog

    @staticmethod
    def _normalize_language(language: str) -> str:
        value = str(language or "").strip().replace("_", "-").lower()
        if not value:
            return ""
        return value.split("-", 1)[0]

    def active_translation_language(self) -> str:
        meta = self.db.get_translation_metadata(self.db.translation)
        return self._normalize_language(str(meta.get("language", "") or ""))

    def find_translation_for_language(self, language: str) -> str | None:
        target = self._normalize_language(language)
        if not target:
            return None
        current = self.db.translation
        catalog = self.list_translation_catalog()
        current_match = next((item for item in catalog if item["code"] == current), None)
        if current_match and self._normalize_language(current_match.get("language", "")) == target:
            return current
        for item in catalog:
            if self._normalize_language(item.get("language", "")) == target:
                return item["code"]
        return None

    def list_books(self) -> list[dict[str, Any]]:
        return self.db.get_books()

    def open_chapter(self, *, book_id: int, chapter: int) -> dict[str, Any] | None:
        payload = self.db.get_chapter(book_id, chapter)
        if not payload:
            return None
        book = payload["book"]
        self.settings.record_reading(
            translation=self.db.translation,
            book=str(book["name"]),
            chapter=int(chapter),
            book_id=int(book["id"]),
        )
        return payload

    def search(
        self,
        query: str,
        *,
        limit: int = 100,
        translation: str | None = None,
        book_id: int | None = None,
        testament_id: int | None = None,
        match_mode: str = "phrase",
    ) -> list[dict[str, Any]]:
        rows = self.db.search(
            query,
            limit=limit,
            translation=translation,
            book_id=book_id,
            testament_id=testament_id,
            match_mode=match_mode,
        )
        active_translation = translation or self.db.translation
        for row in rows:
            row["translation"] = active_translation
            row["is_favorite"] = self.favorites.is_favorite(
                translation=active_translation,
                book=str(row["book_name"]),
                chapter=int(row["chapter"]),
                verse=int(row["verse"]),
            )
            row["has_note"] = self.study.get_note(
                translation=active_translation,
                book=str(row["book_name"]),
                chapter=int(row["chapter"]),
                verse=int(row["verse"]),
            ) is not None
        return rows

    def search_study(
        self,
        query: str,
        *,
        limit: int = 100,
        match_mode: str = "phrase",
        testament_id: int | None = None,
        book_id: int | None = None,
        translation: str | None = None,
        notes_only: bool = False,
    ) -> list[dict[str, Any]]:
        rows = self.search(
            query,
            limit=limit,
            match_mode=match_mode,
            testament_id=testament_id,
            book_id=book_id,
            translation=translation,
        )
        if notes_only:
            rows = [row for row in rows if bool(row.get("has_note"))]
        return rows

    def toggle_favorite(
        self,
        *,
        translation: str,
        book: str,
        chapter: int,
        verse: int,
        text: str | None = None,
        book_id: int | None = None,
    ) -> bool:
        return self.favorites.toggle(
            translation=translation,
            book=book,
            chapter=chapter,
            verse=verse,
            text=text,
            book_id=book_id,
        )

    def list_favorites(
        self, *, translation: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        return self.favorites.list_favorites(translation=translation, limit=limit)

    def get_settings(self) -> UserSettings:
        return self.settings.load()

    def get_study_note(
        self, *, translation: str, book: str, chapter: int, verse: int
    ) -> dict[str, Any] | None:
        return self.study.get_note(
            translation=translation, book=book, chapter=chapter, verse=verse
        )

    def save_study_note(
        self,
        *,
        translation: str,
        book_id: int | None,
        book: str,
        chapter: int,
        verse: int,
        note_text: str,
        highlight_color: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.study.upsert_note(
            translation=translation,
            book_id=book_id,
            book=book,
            chapter=chapter,
            verse=verse,
            note_text=note_text,
            highlight_color=highlight_color,
            tags=tags,
        )

    def delete_study_note(
        self, *, translation: str, book: str, chapter: int, verse: int
    ) -> int:
        return self.study.delete_note(
            translation=translation, book=book, chapter=chapter, verse=verse
        )

    def list_study_notes(
        self,
        *,
        translation: str | None = None,
        book: str | None = None,
        chapter: int | None = None,
        tag: str | None = None,
        limit: int | None = 200,
    ) -> list[dict[str, Any]]:
        return self.study.list_notes(
            translation=translation, book=book, chapter=chapter, tag=tag, limit=limit
        )

    def list_cross_references(
        self, *, book_id: int, chapter: int, verse: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        refs = self.study.list_cross_references(
            source_book_id=book_id, source_chapter=chapter, source_verse=verse, limit=limit
        )
        enriched: list[dict[str, Any]] = []
        for ref in refs:
            target_verse = self.db.get_verse(
                int(ref["target_book_id"]),
                int(ref["target_chapter"]),
                int(ref["target_verse"]),
            )
            item = dict(ref)
            if target_verse:
                item["target_book_name"] = target_verse["book_name"]
                item["target_text"] = target_verse["text"]
            enriched.append(item)
        return enriched

    def add_cross_reference(self, **kwargs: Any) -> None:
        self.study.add_cross_reference(**kwargs)

    def count_cross_references(self) -> int:
        return self.study.count_cross_references()

    def compare_verse(
        self,
        *,
        book_id: int,
        chapter: int,
        verse: int,
        translations: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        requested = translations or self.db.available_translations()[:3]
        out: list[dict[str, Any]] = []
        previous = self.db.translation
        try:
            for code in requested:
                if code not in self.db.available_translations():
                    continue
                self.db.set_translation(code)
                row = self.db.get_verse(book_id, chapter, verse)
                if row:
                    row["translation"] = code
                    out.append(row)
        finally:
            self.db.set_translation(previous)
        return out

    def list_reading_plans(self) -> list[dict[str, Any]]:
        return self.study.list_reading_plans()

    def set_plan_day_completed(self, *, plan_slug: str, day_index: int, completed: bool) -> None:
        self.study.mark_plan_day(plan_slug=plan_slug, day_index=day_index, completed=completed)

    def list_plan_progress(self, *, plan_slug: str) -> list[int]:
        return self.study.list_plan_progress(plan_slug=plan_slug)

    def create_notebook(self, *, name: str, description: str = "") -> dict[str, Any]:
        return self.study.create_notebook(name=name, description=description)

    def list_notebooks(self) -> list[dict[str, Any]]:
        return self.study.list_notebooks()

    def add_notebook_entry(
        self,
        *,
        notebook_id: int,
        translation: str,
        book_id: int | None,
        book: str,
        chapter: int,
        verse: int,
        note_text: str = "",
    ) -> dict[str, Any]:
        return self.study.add_notebook_entry(
            notebook_id=notebook_id,
            translation=translation,
            book_id=book_id,
            book=book,
            chapter=chapter,
            verse=verse,
            note_text=note_text,
        )

    def list_notebook_entries(self, *, notebook_id: int, limit: int | None = 200) -> list[dict[str, Any]]:
        return self.study.list_notebook_entries(notebook_id=notebook_id, limit=limit)

    def list_recent_notebook_entries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.study.list_recent_notebook_entries(limit=limit)

    def delete_notebook_entry(self, *, entry_id: int) -> int:
        return self.study.delete_notebook_entry(entry_id=entry_id)

    def export_study_data(self, path: Path) -> Path:
        payload = self.study.export_json()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def import_study_data(self, path: Path, *, merge: bool = True) -> dict[str, int]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Arquivo de estudo inválido.")
        return self.study.import_json(raw, merge=merge)

    def export_full_backup(self, path: Path) -> Path:
        payload = {
            "settings": self.get_settings().__dict__,
            "favorites": self.favorites.export_json(),
            "study": self.study.export_json(),
            "meta": {
                "app": APP_SLUG,
                "app_name": APP_NAME,
                "backup_version": 1,
                "translation_count": len(self.db.available_translations()),
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def import_full_backup(self, path: Path, *, merge: bool = True) -> dict[str, Any]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Arquivo de backup inválido.")
        counts: dict[str, Any] = {"favorites": 0, "study": {}, "settings": False}
        if isinstance(raw.get("settings"), dict):
            if merge:
                self.settings.update(**raw["settings"])
            else:
                current = self.get_settings()
                for k, v in raw["settings"].items():
                    if hasattr(current, k):
                        setattr(current, k, v)
                self.settings.save(current)
            counts["settings"] = True
        if isinstance(raw.get("favorites"), list):
            counts["favorites"] = self.favorites.import_json(raw["favorites"], merge=merge)
        if isinstance(raw.get("study"), dict):
            counts["study"] = self.study.import_json(raw["study"], merge=merge)
        return counts

    def set_font_scale(self, value: float) -> UserSettings:
        return self.settings.update(font_scale=float(value))

    def set_theme_mode(self, mode: str) -> UserSettings:
        if mode not in {"system", "light", "dark"}:
            raise ValueError(f"Modo de tema invalido: {mode}")
        return self.settings.update(theme_mode=mode)

    def set_ui_language(self, language: str) -> UserSettings:
        value = (language or "system").strip()
        if value not in {"system", "pt_BR", "en", "es"}:
            raise ValueError(f"Idioma inválido: {value}")
        return self.settings.update(ui_language=value)

    def set_reading_layout(self, layout: str) -> UserSettings:
        value = (layout or "cards").strip()
        if value not in {"cards", "continuous"}:
            raise ValueError(f"Layout de leitura inválido: {value}")
        return self.settings.update(reading_layout=value)

    def set_tts_voice_language(self, language: str) -> UserSettings:
        value = (language or "auto").strip().lower()
        if value not in {
            "auto", "pt-br", "en", "es", "fr", "de", "it",
            "ru", "uk", "pl", "cs", "ro", "nl", "sv", "tr",
            "ja", "zh", "ko", "he", "ar", "hi", "la",
        }:
            raise ValueError(f"Idioma de voz inválido: {value}")
        return self.settings.update(tts_voice_language=value)

    def set_tts_engine(self, engine: str) -> UserSettings:
        value = (engine or "auto").strip().lower()
        if value not in {"auto", "piper", "rhvoice", "speechd", "espeak-ng", "espeak"}:
            raise ValueError(f"Motor TTS inválido: {value}")
        return self.settings.update(tts_engine=value)

    def set_daily_content_settings(
        self,
        *,
        enabled: bool | None = None,
        mode: str | None = None,
        time_str: str | None = None,
        end_time_str: str | None = None,
        messages_per_day: int | None = None,
        interval_minutes: int | None = None,
        persistent_notification: bool | None = None,
        delivery_mode: str | None = None,
        sound_enabled: bool | None = None,
        sound_name: str | None = None,
        translation: str | None = None,
    ) -> UserSettings:
        fields: dict[str, Any] = {}
        if enabled is not None:
            fields["daily_content_enabled"] = bool(enabled)
        if mode is not None:
            if mode not in {"verse", "study", "outline"}:
                raise ValueError(f"Modo diario invalido: {mode}")
            fields["daily_content_mode"] = mode
        if translation is not None:
            value = (translation or "").strip().upper()
            if value and value not in self.db.available_translations():
                raise ValueError(f"Tradução diária indisponível: {value}")
            fields["daily_content_translation"] = value
        if time_str is not None:
            if not self._is_valid_hhmm(time_str):
                raise ValueError("Horario invalido. Use HH:MM.")
            fields["daily_content_time"] = time_str
        if end_time_str is not None:
            if not self._is_valid_hhmm(end_time_str):
                raise ValueError("Horario final invalido. Use HH:MM.")
            fields["daily_content_end_time"] = end_time_str
        if messages_per_day is not None:
            value = int(messages_per_day)
            if value < 1 or value > 288:
                raise ValueError("Mensagens por dia deve estar entre 1 e 288.")
            fields["daily_messages_per_day"] = value
        if interval_minutes is not None:
            value = int(interval_minutes)
            if value < 5 or value > 1440:
                raise ValueError("Intervalo deve estar entre 5 e 1440 minutos.")
            fields["daily_interval_minutes"] = value
        if persistent_notification is not None:
            fields["daily_notification_persistent"] = bool(persistent_notification)
        if delivery_mode is not None:
            if delivery_mode not in {"native", "popup"}:
                raise ValueError("Modo de entrega inválido.")
            fields["daily_delivery_mode"] = delivery_mode
        if sound_enabled is not None:
            fields["daily_sound_enabled"] = bool(sound_enabled)
        if sound_name is not None:
            if sound_name not in {"soft", "bell", "alert"}:
                raise ValueError("Som inválido.")
            fields["daily_sound_name"] = sound_name
        return self.settings.update(**fields)

    def get_daily_content_preview(self, mode: str | None = None) -> DailyContent:
        settings = self.settings.load()
        chosen_mode = mode or settings.daily_content_mode or "verse"
        chosen_translation = (getattr(settings, "daily_content_translation", "") or "").strip()
        return self.daily.generate(mode=chosen_mode, translation=chosen_translation or None)

    def compute_daily_schedule_times(self, settings: UserSettings | None = None) -> list[str]:
        s = settings or self.settings.load()
        start = s.daily_content_time or "08:00"
        end = getattr(s, "daily_content_end_time", start) or start
        interval = max(5, int(getattr(s, "daily_interval_minutes", 180) or 180))
        return self._build_schedule_times(start, end, interval)

    @staticmethod
    def _hhmm_to_minutes(value: str) -> int:
        hh, mm = value.split(":", 1)
        return int(hh) * 60 + int(mm)

    @classmethod
    def _build_schedule_times(cls, start: str, end: str, interval: int) -> list[str]:
        if not (cls._is_valid_hhmm(start) and cls._is_valid_hhmm(end)):
            return [start]
        start_m = cls._hhmm_to_minutes(start)
        end_m = cls._hhmm_to_minutes(end)
        if interval < 5:
            interval = 5
        # Se fim < início, considera janela atravessando meia-noite.
        window = (end_m - start_m) % (24 * 60)
        if start_m == end_m:
            return [start]
        total_span = window
        times = [start]
        current = start_m
        seen = {start}
        while True:
            current = (current + interval) % (24 * 60)
            distance = (current - start_m) % (24 * 60)
            if distance > total_span or distance == 0:
                break
            hh = current // 60
            mm = current % 60
            hhmm = f"{hh:02d}:{mm:02d}"
            if hhmm in seen:
                break
            seen.add(hhmm)
            times.append(hhmm)
        return times

    @staticmethod
    def _is_valid_hhmm(value: str) -> bool:
        try:
            hh, mm = value.split(":", 1)
            h = int(hh)
            m = int(mm)
        except Exception:
            return False
        return 0 <= h <= 23 and 0 <= m <= 59 and len(value) == 5
