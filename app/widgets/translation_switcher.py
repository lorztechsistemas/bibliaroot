from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
from app.i18n import _


class TranslationSwitcher(Gtk.Box):
    def __init__(self, on_translation_changed: Callable[[str], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._on_translation_changed = on_translation_changed
        self._suspend_notify = False
        self._catalog: list[dict[str, str]] = []
        self._visible_catalog: list[dict[str, str]] = []
        self._language_filter_codes: list[str] = [""]

        label = Gtk.Label(label=_("Tradução"))
        label.set_xalign(0)
        self.append(label)

        self.language_dropdown = Gtk.DropDown.new_from_strings([_("Todos")])
        self.language_dropdown.set_tooltip_text(_("Filtrar traduções por idioma"))
        self.language_dropdown.connect("notify::selected", self._on_language_filter_changed)
        self.append(self.language_dropdown)

        self._items = ["ARA", "NVI", "ARC"]
        self._codes = list(self._items)
        self.dropdown = Gtk.DropDown.new_from_strings(self._items)
        self.dropdown.connect("notify::selected", self._on_selected_changed)
        self.append(self.dropdown)

    def set_translations(self, translations: list[str], selected: str | None = None) -> None:
        self._catalog = []
        self._visible_catalog = []
        self._language_filter_codes = [""]
        self._items = translations or []
        self._codes = list(self._items)
        self._suspend_notify = True
        try:
            self.language_dropdown.set_model(Gtk.StringList.new([_("Todos")]))
            self.language_dropdown.set_selected(0)
            self.language_dropdown.set_sensitive(False)
            self.dropdown.set_model(Gtk.StringList.new(self._items))
            if not self._items:
                return
            if selected in self._items:
                self.dropdown.set_selected(self._items.index(selected))
            else:
                self.dropdown.set_selected(0)
        finally:
            self._suspend_notify = False

    def set_translation_catalog(
        self, catalog: list[dict[str, str]], selected_code: str | None = None
    ) -> None:
        self._catalog = [
            {
                "code": str(item["code"]),
                "label": str(item["label"]),
                "language": str(item.get("language", "") or "").strip(),
            }
            for item in catalog
        ]
        self._suspend_notify = True
        try:
            self._rebuild_language_filter(selected_code=selected_code)
            self._apply_language_filter(selected_code=selected_code)
        finally:
            self._suspend_notify = False

    def select_translation(self, selected: str) -> None:
        self._suspend_notify = True
        try:
            if selected not in self._codes:
                # Se a tradução estiver fora do filtro atual, abre o filtro para "Todos".
                if self._catalog and any(item["code"] == selected for item in self._catalog):
                    self._set_language_filter("")
                    self._apply_language_filter(selected_code=selected)
            if selected in self._codes:
                self.dropdown.set_selected(self._codes.index(selected))
        finally:
            self._suspend_notify = False

    def _rebuild_language_filter(self, selected_code: str | None = None) -> None:
        languages = sorted({item["language"] for item in self._catalog if item["language"]})
        self._language_filter_codes = [""] + languages
        labels = [_("Todos")] + languages
        self.language_dropdown.set_model(Gtk.StringList.new(labels))
        self.language_dropdown.set_sensitive(len(labels) > 1)
        # Seleciona automaticamente o idioma da tradução atual, se existir.
        if selected_code:
            match = next((i for i in self._catalog if i["code"] == selected_code), None)
            selected_language = (match or {}).get("language", "")
            self._set_language_filter(str(selected_language or ""))
        else:
            self._set_language_filter("")

    def _set_language_filter(self, language_code: str) -> None:
        language_code = str(language_code or "")
        try:
            idx = self._language_filter_codes.index(language_code)
        except ValueError:
            idx = 0
        self.language_dropdown.set_selected(idx)

    def _current_language_filter(self) -> str:
        idx = int(self.language_dropdown.get_selected())
        if idx < 0 or idx >= len(self._language_filter_codes):
            return ""
        return self._language_filter_codes[idx]

    def _apply_language_filter(self, selected_code: str | None = None) -> None:
        previous_selected_code = None
        current_index = self.dropdown.get_selected()
        if current_index != Gtk.INVALID_LIST_POSITION and 0 <= current_index < len(self._codes):
            previous_selected_code = self._codes[current_index]

        language_filter = self._current_language_filter()
        if language_filter:
            visible = [item for item in self._catalog if item["language"] == language_filter]
        else:
            visible = list(self._catalog)
        self._visible_catalog = visible
        self._codes = [item["code"] for item in visible]
        self._items = [item["label"] for item in visible]
        self.dropdown.set_model(Gtk.StringList.new(self._items))
        if not self._codes:
            return
        if selected_code in self._codes:
            self.dropdown.set_selected(self._codes.index(selected_code))
            return
        if previous_selected_code in self._codes:
            self.dropdown.set_selected(self._codes.index(previous_selected_code))
        else:
            self.dropdown.set_selected(0)

    def _on_language_filter_changed(self, _dropdown: Gtk.DropDown, _pspec) -> None:
        if self._suspend_notify:
            return
        self._suspend_notify = True
        try:
            self._apply_language_filter()
        finally:
            self._suspend_notify = False

    def _on_selected_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._suspend_notify:
            return
        index = dropdown.get_selected()
        if index == Gtk.INVALID_LIST_POSITION:
            return
        self._on_translation_changed(self._codes[index])
