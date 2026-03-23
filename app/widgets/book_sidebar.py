from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
from app.i18n import _


class BookSidebar(Gtk.Box):
    def __init__(self, on_book_selected: Callable[[str], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.set_vexpand(True)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self._on_book_selected = on_book_selected
        self._rows_by_book_id: dict[int, Gtk.ListBoxRow] = {}
        self._book_id_by_row: dict[Gtk.ListBoxRow, int] = {}
        self._suspend_select = False
        self._all_books: list[dict] = []

        self.title_label = Gtk.Label(label=_("Livros"))
        self.title_label.set_xalign(0)
        self.title_label.add_css_class("title-4")
        self.title_label.set_margin_start(8)
        self.title_label.set_margin_end(8)
        self.title_label.set_margin_top(4)
        self.append(self.title_label)

        self.search_entry = Gtk.SearchEntry(placeholder_text=_("Filtrar livros"))
        self.search_entry.set_margin_start(8)
        self.search_entry.set_margin_end(8)
        self.search_entry.set_margin_bottom(4)
        self.search_entry.connect("search-changed", self._on_filter_changed)
        self.append(self.search_entry)

        self.listbox = Gtk.ListBox()
        self.listbox.set_vexpand(True)
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.connect("row-selected", self._handle_selected)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_margin_start(4)
        scrolled.set_margin_end(4)
        scrolled.set_margin_bottom(4)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_child(self.listbox)
        self.append(scrolled)

    def set_books(self, books: list[dict]) -> None:
        self._all_books = list(books)
        self._apply_filter()

    def _apply_filter(self) -> None:
        self._rows_by_book_id.clear()
        self._book_id_by_row.clear()
        while (row := self.listbox.get_row_at_index(0)) is not None:
            self.listbox.remove(row)
        term = self.search_entry.get_text().strip().casefold()
        shown = 0
        for book in self._all_books:
            name = str(book["name"])
            if term and term not in name.casefold():
                continue
            action_row = Adw.ActionRow(title=book["name"])
            action_row.add_css_class("compact-row")
            action_row.set_subtitle(
                _("AT") if int(book.get("testament_reference_id", 0) or 0) == 1 else _("NT")
            )
            list_row = Gtk.ListBoxRow()
            list_row.add_css_class("sidebar-book-row")
            list_row.set_child(action_row)
            self.listbox.append(list_row)
            book_id = int(book["id"])
            self._rows_by_book_id[book_id] = list_row
            self._book_id_by_row[list_row] = book_id
            shown += 1
        total = len(self._all_books)
        self.title_label.set_text(
            f'{_("Livros")} ({shown}/{total})' if term else f'{_("Livros")} ({total})'
        )

    def select_book(self, book_id: int) -> None:
        row = self._rows_by_book_id.get(int(book_id))
        if row is not None:
            self._suspend_select = True
            try:
                self.listbox.select_row(row)
            finally:
                self._suspend_select = False

    def _handle_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if self._suspend_select:
            return
        if row is None:
            return
        book_id = self._book_id_by_row.get(row)
        if book_id is None:
            return
        self._on_book_selected(str(book_id))

    def _on_filter_changed(self, _entry: Gtk.SearchEntry) -> None:
        self._apply_filter()
