from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
from app.i18n import _


class ChapterPanel(Gtk.Box):
    def __init__(self, on_chapter_selected: Callable[[int], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._on_chapter_selected = on_chapter_selected
        self._suspend_notify = False
        self._total_chapters = 0

        label = Gtk.Label(label=_("Capítulo:"))
        self.append(label)

        self.spin = Gtk.SpinButton.new_with_range(1, 1, 1)
        self.spin.set_numeric(True)
        self.spin.set_width_chars(4)
        self.spin.connect("value-changed", self._on_value_changed)
        self.append(self.spin)

        self.total_label = Gtk.Label(label="/ 0")
        self.total_label.add_css_class("dim-label")
        self.append(self.total_label)

    def set_chapters(self, total_chapters: int, selected: int = 1) -> None:
        total_chapters = max(0, int(total_chapters))
        self._total_chapters = total_chapters
        self._suspend_notify = True
        try:
            self.total_label.set_text(f"/ {total_chapters}")
            if total_chapters <= 0:
                self.spin.set_range(1, 1)
                self.spin.set_value(1)
                self.spin.set_sensitive(False)
                return
            self.spin.set_sensitive(True)
            self.spin.set_range(1, total_chapters)
            self.spin.set_value(min(max(1, int(selected)), total_chapters))
        finally:
            self._suspend_notify = False

    def _on_value_changed(self, spin: Gtk.SpinButton) -> None:
        if self._suspend_notify:
            return
        chapter = int(spin.get_value())
        if chapter < 1 or chapter > max(1, self._total_chapters):
            return
        self._on_chapter_selected(chapter)
