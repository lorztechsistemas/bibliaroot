from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.models.bible_db import BibleDB
from app.i18n import _


@dataclass
class DailyContent:
    mode: str
    title: str
    body: str
    reference: str
    translation: str
    verse_text: str


class DailyContentService:
    def __init__(self, db: BibleDB) -> None:
        self.db = db

    def generate(
        self,
        *,
        mode: str = "verse",
        translation: str | None = None,
        on_date: date | None = None,
        at_datetime: datetime | None = None,
    ) -> DailyContent:
        previous_translation = self.db.translation
        if translation:
            self.db.set_translation(translation)
        try:
            target_date = on_date or (at_datetime.date() if at_datetime else date.today())
            verse = self._pick_daily_verse(target_date, at_datetime=at_datetime)
            if verse is None:
                raise RuntimeError(_("Nenhum versiculo disponivel no banco atual."))

            reference = f'{verse["book_name"]} {verse["chapter"]}:{verse["verse"]}'
            verse_text = str(verse["text"])
            translation = self.db.translation
            mode = mode if mode in {"verse", "study", "outline"} else "verse"

            if mode == "study":
                title = f'{_("Estudo diário")} • {reference}'
                body = (
                    f"{verse_text}\n\n"
                    f'{_("Reflexão")}: {_("Observe o contexto de")} {reference} '
                    + _("e destaque uma verdade central. ")
                    + _("Pergunte: o que este texto revela sobre Deus, sobre a pessoa humana e sobre a prática cristã hoje?")
                )
            elif mode == "outline":
                title = f'{_("Esboço diário")} • {reference}'
                body = (
                    f'{_("Tema")}: {self._theme_from_verse(verse_text)}\n'
                    f'{_("Texto-base")}: {reference}\n'
                    + _("Pontos:")
                    + "\n"
                    + _("1. Verdade principal do texto")
                    + "\n"
                    + _("2. Aplicação prática para hoje")
                    + "\n"
                    + _("3. Resposta de fé e oração")
                )
            else:
                title = _("Versículo do dia")
                body = f"{reference} ({translation})\n{verse_text}"

            return DailyContent(
                mode=mode,
                title=title,
                body=body,
                reference=reference,
                translation=translation,
                verse_text=verse_text,
            )
        finally:
            if translation and previous_translation != self.db.translation:
                self.db.set_translation(previous_translation)

    def _pick_daily_verse(self, target_date: date, *, at_datetime: datetime | None = None) -> dict | None:
        total = self.db.get_verse_count()
        if total <= 0:
            return None
        # Determinístico por dia e horário (quando houver múltiplos disparos diários).
        minute_bucket = 0
        if at_datetime is not None:
            minute_bucket = at_datetime.hour * 60 + at_datetime.minute
        index = (target_date.toordinal() * 97 + minute_bucket * 13) % total
        return self.db.get_verse_by_global_index(index)

    @staticmethod
    def _theme_from_verse(text: str) -> str:
        lowered = text.casefold()
        if "amor" in lowered:
            return _("O amor de Deus")
        if "fé" in lowered or "fe " in lowered or lowered.endswith("fe"):
            return _("Viver pela fé")
        if "esperança" in lowered or "esperanca" in lowered:
            return _("Esperança em Deus")
        if "salvação" in lowered or "salvacao" in lowered:
            return _("Salvação e graça")
        if "oração" in lowered or "oracao" in lowered:
            return _("Vida de oração")
        return _("Aplicação prática da Palavra")
