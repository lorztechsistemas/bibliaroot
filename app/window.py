from __future__ import annotations

from html import escape
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
import signal
import threading
import time
import traceback
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from .constants import APP_NAME, APP_SLUG, APP_USER_AGENT, DAILY_TIMER_NAME
from .services.backend import BibleBackend
from .i18n import _
from .widgets.book_sidebar import BookSidebar
from .widgets.chapter_panel import ChapterPanel
from .widgets.translation_switcher import TranslationSwitcher


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.set_title(APP_NAME)
        self.set_default_size(1280, 820)

        self._backend = BibleBackend()
        self._selected_book_id: int | None = None
        self._selected_chapter: int = 1
        self._current_chapter_payload: dict | None = None
        self._reader_rows_by_verse: dict[int, Gtk.ListBoxRow] = {}
        self._highlight_verse: int | None = None
        self._selected_study_ref: dict | None = None
        self._font_scale: float = 1.0
        self._font_css_provider = Gtk.CssProvider()
        self._theme_mode: str = "system"
        self._reading_layout: str = "cards"
        self._focus_mode: bool = False
        self._focus_mode_saved_font_scale: float | None = None
        self._tts_process: subprocess.Popen | None = None
        self._tts_paused: bool = False
        self._tts_backend: str | None = None
        self._tts_media: Gtk.MediaFile | None = None
        self._tts_media_tempfile: str | None = None
        self._tts_job_id: int = 0
        self._last_tts_error_text: str = ""
        self._tts_chunk_queue: list[tuple[str, str | None]] = []
        self._tts_chunk_total: int = 0
        self._tts_last_requested_text: str = ""
        self._tts_last_requested_translation: str | None = None
        self._tts_prefetch_inflight: set[str] = set()
        self._daily_controls_syncing = False
        self._time_entry_mask_syncing = False
        self._last_daily_error_text: str = ""
        self._search_entry_syncing = False

        self._build_ui()
        self.connect("close-request", self._on_close_request)
        self._install_shortcuts()
        self._load_initial_state()

    def _build_ui(self) -> None:
        header = Adw.HeaderBar()
        self.stack = Gtk.Stack(hexpand=True, vexpand=True)
        self.stack_switcher = Gtk.StackSwitcher(stack=self.stack)
        header.set_title_widget(self.stack_switcher)

        self.toast_overlay = Adw.ToastOverlay()

        root = Adw.ToolbarView()
        root.add_top_bar(header)
        self.toast_overlay.set_child(root)

        paned = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        paned.set_wide_handle(True)
        root.set_content(paned)

        self.sidebar = BookSidebar(on_book_selected=self._on_book_selected)
        self.sidebar.add_css_class("card")
        self.sidebar.set_size_request(240, -1)
        paned.set_start_child(self.sidebar)
        paned.set_resize_start_child(False)
        paned.set_shrink_start_child(True)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        app_footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        app_footer.add_css_class("card")
        app_footer.add_css_class("app-header-footer")

        app_footer_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        app_footer_inner.set_margin_top(12)
        app_footer_inner.set_margin_bottom(12)
        app_footer_inner.set_margin_start(14)
        app_footer_inner.set_margin_end(14)
        app_footer.append(app_footer_inner)

        app_title = Gtk.Label(label=APP_NAME)
        app_title.add_css_class("title-4")
        app_title.set_xalign(0)
        app_footer_inner.append(app_title)

        app_subtitle = Gtk.Label(label=_("Leitura, busca e favoritos offline"))
        app_subtitle.add_css_class("dim-label")
        app_subtitle.set_xalign(0)
        app_footer_inner.append(app_subtitle)
        content.append(app_footer)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls.add_css_class("card")
        controls.add_css_class("toolbar-card")
        controls.set_margin_bottom(2)
        controls.set_margin_top(0)
        controls.set_margin_start(0)
        controls.set_margin_end(0)
        controls.set_hexpand(True)
        controls.set_valign(Gtk.Align.START)

        controls_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls_inner.set_margin_top(8)
        controls_inner.set_margin_bottom(8)
        controls_inner.set_margin_start(10)
        controls_inner.set_margin_end(10)
        controls.append(controls_inner)

        self.translation_switcher = TranslationSwitcher(
            on_translation_changed=self._on_translation_changed
        )
        controls_inner.append(self.translation_switcher)

        self.quick_search = Gtk.SearchEntry(placeholder_text=_("Buscar palavra/frase"))
        self.quick_search.add_css_class("control-field")
        self.quick_search.set_hexpand(True)
        self.quick_search.connect("activate", self._on_search_activated)
        self.quick_search.connect("changed", self._on_search_query_changed)
        controls_inner.append(self.quick_search)

        search_button = Gtk.Button(label=_("Buscar"))
        search_button.add_css_class("suggested-action")
        search_button.add_css_class("soft-button")
        search_button.connect("clicked", self._on_search_button_clicked)
        controls_inner.append(search_button)
        content.append(controls)

        self.status_line = Gtk.Label(label=_("Carregando dados..."), xalign=0)
        self.status_line.add_css_class("dim-label")
        self.status_line.add_css_class("status-line")
        content.append(self.status_line)

        self.stack.add_titled(self._build_reader_page(), "reader", _("Leitura"))
        self.stack.add_titled(self._build_search_page(), "search", _("Busca"))
        self.stack.add_titled(self._build_favorites_page(), "favorites", _("Favoritos"))
        self.stack.add_titled(self._build_study_page(), "study", _("Estudo"))
        self.stack.add_titled(self._build_settings_page(), "settings", _("Configurações"))
        content.append(self.stack)

        paned.set_end_child(content)
        self.set_content(self.toast_overlay)

    def _build_reader_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        header_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header_card.add_css_class("card")
        header_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        header_inner.set_margin_top(10)
        header_inner.set_margin_bottom(10)
        header_inner.set_margin_start(12)
        header_inner.set_margin_end(12)
        header_card.append(header_inner)

        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.reader_title = Gtk.Label(label=_("Leitura"), xalign=0)
        self.reader_title.add_css_class("title-3")
        self.reader_title.set_hexpand(True)
        title_row.append(self.reader_title)
        self.reader_chapter_meta_label = Gtk.Label(label="", xalign=1)
        self.reader_chapter_meta_label.add_css_class("dim-label")
        self.reader_chapter_meta_label.add_css_class("monospace")
        title_row.append(self.reader_chapter_meta_label)
        header_inner.append(title_row)

        nav_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        nav_main_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.prev_chapter_button = Gtk.Button(label=_("◀ Capítulo"))
        self.prev_chapter_button.add_css_class("soft-button")
        self.prev_chapter_button.connect("clicked", self._on_prev_chapter_clicked)
        nav_main_row.append(self.prev_chapter_button)

        self.chapter_panel = ChapterPanel(on_chapter_selected=self._on_chapter_selected)
        nav_main_row.append(self.chapter_panel)

        self.next_chapter_button = Gtk.Button(label=_("Capítulo ▶"))
        self.next_chapter_button.add_css_class("soft-button")
        self.next_chapter_button.connect("clicked", self._on_next_chapter_clicked)
        nav_main_row.append(self.next_chapter_button)

        self.focus_mode_button = Gtk.Button(label=_("Modo foco"))
        self.focus_mode_button.add_css_class("soft-button")
        self.focus_mode_button.connect("clicked", self._on_toggle_focus_mode_clicked)
        nav_main_row.append(self.focus_mode_button)

        self.reader_layout_toggle_button = Gtk.Button(label=_("Texto contínuo"))
        self.reader_layout_toggle_button.add_css_class("soft-button")
        self.reader_layout_toggle_button.connect("clicked", self._on_reader_layout_toggle_clicked)
        nav_main_row.append(self.reader_layout_toggle_button)

        spacer = Gtk.Box(hexpand=True)
        nav_main_row.append(spacer)

        font_label = Gtk.Label(label=_("Fonte"), xalign=0)
        font_label.add_css_class("dim-label")
        nav_main_row.append(font_label)

        font_minus = Gtk.Button(label="A-")
        font_minus.add_css_class("soft-button")
        font_minus.connect("clicked", self._on_font_minus_clicked)
        nav_main_row.append(font_minus)

        self.font_scale_label = Gtk.Label(label="100%", xalign=0)
        self.font_scale_label.add_css_class("monospace")
        nav_main_row.append(self.font_scale_label)

        font_plus = Gtk.Button(label="A+")
        font_plus.add_css_class("soft-button")
        font_plus.connect("clicked", self._on_font_plus_clicked)
        nav_main_row.append(font_plus)
        nav_row.append(nav_main_row)

        nav_actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.copy_chapter_button = Gtk.Button(label=_("Copiar capítulo"))
        self.copy_chapter_button.add_css_class("soft-button")
        self.copy_chapter_button.connect("clicked", self._on_copy_chapter_clicked)
        nav_actions_row.append(self.copy_chapter_button)

        self.speak_chapter_button = Gtk.Button(label=_("Ouvir capítulo"))
        self.speak_chapter_button.add_css_class("soft-button")
        self.speak_chapter_button.connect("clicked", self._on_speak_chapter_clicked)
        nav_actions_row.append(self.speak_chapter_button)

        self.pause_tts_button = Gtk.Button(label=_("Pausar áudio"))
        self.pause_tts_button.add_css_class("soft-button")
        self.pause_tts_button.connect("clicked", self._on_pause_resume_tts_clicked)
        nav_actions_row.append(self.pause_tts_button)

        self.stop_tts_button = Gtk.Button(label=_("Parar áudio"))
        self.stop_tts_button.add_css_class("soft-button")
        self.stop_tts_button.connect("clicked", self._on_stop_tts_clicked)
        nav_actions_row.append(self.stop_tts_button)
        self._sync_tts_buttons()
        nav_actions_row.append(Gtk.Box(hexpand=True))
        nav_row.append(nav_actions_row)
        header_inner.append(nav_row)

        page.append(header_card)

        self.verse_list = Gtk.ListBox()
        self.verse_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.verse_list.add_css_class("boxed-list")
        self.verse_list.add_css_class("verse-list")

        self.reader_continuous_buffer = Gtk.TextBuffer()
        self.reader_continuous_num_tag = self.reader_continuous_buffer.create_tag(
            "verse-number",
            weight=Pango.Weight.BOLD,
            foreground="#3A6EA5",
            scale=0.95,
        )
        self.reader_continuous_note_tag = self.reader_continuous_buffer.create_tag(
            "verse-note",
            weight=Pango.Weight.BOLD,
            foreground="#A06A00",
        )
        self.reader_continuous_highlight_tag = self.reader_continuous_buffer.create_tag(
            "verse-highlight",
            background="#FFF1A8",
        )
        self.reader_continuous_view = Gtk.TextView(buffer=self.reader_continuous_buffer)
        self.reader_continuous_view.set_editable(False)
        self.reader_continuous_view.set_cursor_visible(False)
        self.reader_continuous_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.reader_continuous_view.set_left_margin(18)
        self.reader_continuous_view.set_right_margin(18)
        self.reader_continuous_view.set_top_margin(14)
        self.reader_continuous_view.set_bottom_margin(14)
        self.reader_continuous_view.add_css_class("reader-continuous-text")
        self.reader_continuous_view.set_hexpand(True)
        self.reader_continuous_view.set_vexpand(True)

        self.reader_continuous_title = Gtk.Label(xalign=0, wrap=True)
        self.reader_continuous_title.add_css_class("reader-continuous-title")
        self.reader_continuous_title.set_margin_top(16)
        self.reader_continuous_title.set_margin_start(18)
        self.reader_continuous_title.set_margin_end(18)

        self.reader_continuous_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.reader_continuous_box.add_css_class("reader-paper")
        self.reader_continuous_box.set_halign(Gtk.Align.FILL)
        self.reader_continuous_box.set_hexpand(True)
        self.reader_continuous_box.append(self.reader_continuous_title)
        self.reader_continuous_box.append(self.reader_continuous_view)

        self.reader_content_stack = Gtk.Stack()
        self.reader_content_stack.add_titled(self.verse_list, "cards", "cards")
        self.reader_content_stack.add_titled(self.reader_continuous_box, "continuous", "continuous")

        self.reader_scrolled = Gtk.ScrolledWindow()
        self.reader_scrolled.set_vexpand(True)
        self.reader_scrolled.add_css_class("list-scroller")
        self.reader_scrolled.set_child(self.reader_content_stack)
        page.append(self.reader_scrolled)
        return page

    def _build_search_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        top_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top_card.add_css_class("card")
        top_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top_inner.set_margin_top(10)
        top_inner.set_margin_bottom(10)
        top_inner.set_margin_start(12)
        top_inner.set_margin_end(12)
        top_card.append(top_inner)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search_entry = Gtk.SearchEntry(placeholder_text=_("Ex.: amor, fé, Jesus"))
        self.search_entry.add_css_class("control-field")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("activate", self._on_search_activated)
        self.search_entry.connect("changed", self._on_search_query_changed)
        top.append(self.search_entry)

        limit_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        limit_box.append(Gtk.Label(label=_("Limite")))
        self.search_limit_spin = Gtk.SpinButton.new_with_range(10, 500, 10)
        self.search_limit_spin.set_value(100)
        limit_box.append(self.search_limit_spin)
        top.append(limit_box)

        search_button = Gtk.Button(label=_("Executar busca"))
        search_button.add_css_class("suggested-action")
        search_button.add_css_class("soft-button")
        search_button.connect("clicked", self._on_search_button_clicked)
        top.append(search_button)
        top_inner.append(top)

        self.search_info = Gtk.Label(label=_("Digite uma palavra ou frase para pesquisar."), xalign=0)
        self.search_info.add_css_class("dim-label")
        top_inner.append(self.search_info)

        page.append(top_card)

        self.search_results_list = Gtk.ListBox()
        self.search_results_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.search_results_list.add_css_class("boxed-list")
        self.search_results_list.add_css_class("search-list")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add_css_class("list-scroller")
        scrolled.set_child(self.search_results_list)
        page.append(scrolled)
        return page

    def _build_favorites_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        top_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top_card.add_css_class("card")
        top_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top_inner.set_margin_top(10)
        top_inner.set_margin_bottom(10)
        top_inner.set_margin_start(12)
        top_inner.set_margin_end(12)
        top_card.append(top_inner)

        title = Gtk.Label(label=_("Versículos favoritos"), xalign=0)
        title.add_css_class("title-4")
        title.set_hexpand(True)
        top_inner.append(title)

        refresh = Gtk.Button(label=_("Atualizar"))
        refresh.add_css_class("soft-button")
        refresh.connect("clicked", self._on_refresh_favorites_clicked)
        top_inner.append(refresh)
        page.append(top_card)

        self.favorites_info = Gtk.Label(label=_("Nenhum favorito ainda."), xalign=0)
        self.favorites_info.add_css_class("dim-label")
        page.append(self.favorites_info)

        self.favorites_list = Gtk.ListBox()
        self.favorites_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.favorites_list.add_css_class("boxed-list")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.add_css_class("list-scroller")
        scrolled.set_child(self.favorites_list)
        page.append(scrolled)
        return page

    def _build_study_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        top_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top_card.add_css_class("card")
        top_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        top_inner.set_margin_top(10)
        top_inner.set_margin_bottom(10)
        top_inner.set_margin_start(12)
        top_inner.set_margin_end(12)
        top_card.append(top_inner)

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label=_("Centro de estudo"), xalign=0)
        title.add_css_class("title-4")
        title.add_css_class("study-block-title")
        title.set_hexpand(True)
        top_row.append(title)
        self.study_use_current_button = Gtk.Button(label=_("Usar capítulo atual"))
        self.study_use_current_button.add_css_class("soft-button")
        self.study_use_current_button.connect("clicked", self._on_study_use_current_clicked)
        top_row.append(self.study_use_current_button)
        top_inner.append(top_row)

        self.study_context_label = Gtk.Label(
            label=_("Selecione um versículo na leitura e clique em “Estudar”."),
            xalign=0,
            wrap=True,
        )
        self.study_context_label.add_css_class("dim-label")
        top_inner.append(self.study_context_label)
        page.append(top_card)

        notebook_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        notebook_card.add_css_class("card")
        notebook_inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        notebook_inner.set_margin_top(10)
        notebook_inner.set_margin_bottom(10)
        notebook_inner.set_margin_start(12)
        notebook_inner.set_margin_end(12)
        notebook_card.append(notebook_inner)
        notebook_inner.append(Gtk.Label(label=_("Caderno"), xalign=0))
        self.study_notebook_dropdown = Gtk.DropDown.new_from_strings([_("Padrão")])
        self.study_notebook_dropdown.set_hexpand(True)
        self.study_notebook_dropdown.set_valign(Gtk.Align.CENTER)
        self.study_notebook_dropdown.connect(
            "notify::selected", self._on_study_notebook_changed
        )
        notebook_inner.append(self.study_notebook_dropdown)
        self.study_add_notebook_button = Gtk.Button(label=_("Criar caderno"))
        self.study_add_notebook_button.add_css_class("soft-button")
        self.study_add_notebook_button.connect("clicked", self._on_study_create_notebook_clicked)
        notebook_inner.append(self.study_add_notebook_button)
        self.study_add_to_notebook_button = Gtk.Button(label=_("Salvar referência"))
        self.study_add_to_notebook_button.add_css_class("soft-button")
        self.study_add_to_notebook_button.connect("clicked", self._on_study_add_to_notebook_clicked)
        notebook_inner.append(self.study_add_to_notebook_button)
        self.study_export_button = Gtk.Button(label=_("Exportar dados"))
        self.study_export_button.add_css_class("soft-button")
        self.study_export_button.connect("clicked", self._on_study_export_clicked)
        notebook_inner.append(self.study_export_button)
        self.study_export_full_button = Gtk.Button(label=_("Backup completo"))
        self.study_export_full_button.add_css_class("soft-button")
        self.study_export_full_button.connect("clicked", self._on_app_export_full_backup_clicked)
        notebook_inner.append(self.study_export_full_button)
        self.study_import_button = Gtk.Button(label=_("Importar backup"))
        self.study_import_button.add_css_class("soft-button")
        self.study_import_button.connect("clicked", self._on_study_import_clicked)
        notebook_inner.append(self.study_import_button)
        self.study_import_full_button = Gtk.Button(label=_("Restaurar completo"))
        self.study_import_full_button.add_css_class("soft-button")
        self.study_import_full_button.connect("clicked", self._on_app_import_full_backup_clicked)
        notebook_inner.append(self.study_import_full_button)
        page.append(notebook_card)

        notes_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        notes_card.add_css_class("card")
        notes_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        notes_inner.set_margin_top(10)
        notes_inner.set_margin_bottom(10)
        notes_inner.set_margin_start(12)
        notes_inner.set_margin_end(12)
        notes_card.append(notes_inner)
        notes_title = Gtk.Label(label=_("Notas e marcação"), xalign=0)
        notes_title.add_css_class("heading")
        notes_title.add_css_class("study-block-title")
        notes_inner.append(notes_title)

        tags_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.study_tags_entry = Gtk.Entry(placeholder_text=_("Tags (ex.: oração, fé, sermão)"))
        self.study_tags_entry.add_css_class("control-field")
        self.study_tags_entry.set_hexpand(True)
        tags_row.append(self.study_tags_entry)
        self.study_highlight_codes = ["", "yellow", "green", "blue", "pink"]
        self.study_highlight_dropdown = Gtk.DropDown.new_from_strings(
            [_("Sem cor"), _("Amarelo"), _("Verde"), _("Azul"), _("Rosa")]
        )
        self.study_highlight_dropdown.set_valign(Gtk.Align.CENTER)
        tags_row.append(self.study_highlight_dropdown)
        notes_inner.append(tags_row)

        self.study_note_view = Gtk.TextView()
        self.study_note_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.study_note_view.set_vexpand(False)
        self.study_note_view.set_size_request(-1, 110)
        note_scrolled = Gtk.ScrolledWindow()
        note_scrolled.set_min_content_height(120)
        note_scrolled.set_child(self.study_note_view)
        notes_inner.append(note_scrolled)

        note_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.study_save_note_button = Gtk.Button(label=_("Salvar nota"))
        self.study_save_note_button.add_css_class("suggested-action")
        self.study_save_note_button.add_css_class("soft-button")
        self.study_save_note_button.connect("clicked", self._on_study_save_note_clicked)
        note_actions.append(self.study_save_note_button)
        self.study_delete_note_button = Gtk.Button(label=_("Remover nota"))
        self.study_delete_note_button.add_css_class("soft-button")
        self.study_delete_note_button.connect("clicked", self._on_study_delete_note_clicked)
        note_actions.append(self.study_delete_note_button)
        self.study_open_notes_button = Gtk.Button(label=_("Listar notas do capítulo"))
        self.study_open_notes_button.add_css_class("soft-button")
        self.study_open_notes_button.connect("clicked", self._on_study_list_chapter_notes_clicked)
        note_actions.append(self.study_open_notes_button)
        notes_inner.append(note_actions)
        page.append(notes_card)

        compare_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        compare_card.add_css_class("card")
        compare_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        compare_inner.set_margin_top(10)
        compare_inner.set_margin_bottom(10)
        compare_inner.set_margin_start(12)
        compare_inner.set_margin_end(12)
        compare_card.append(compare_inner)
        compare_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        compare_title = Gtk.Label(label=_("Comparação de traduções"), xalign=0)
        compare_title.add_css_class("heading")
        compare_title.add_css_class("study-block-title")
        compare_title.set_hexpand(True)
        compare_header.append(compare_title)
        compare_copy_btn = Gtk.Button(label=_("Copiar comparação"))
        compare_copy_btn.add_css_class("soft-button")
        compare_copy_btn.connect("clicked", self._on_study_copy_comparison_clicked)
        compare_header.append(compare_copy_btn)
        compare_inner.append(compare_header)
        cmp_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        catalog = self._backend.list_translation_catalog()
        self.study_compare_codes = [item["code"] for item in catalog]
        self.study_compare_left = Gtk.DropDown.new_from_strings([item["code"] for item in catalog] or ["-"])
        self.study_compare_right = Gtk.DropDown.new_from_strings([item["code"] for item in catalog] or ["-"])
        self.study_compare_left.set_valign(Gtk.Align.CENTER)
        self.study_compare_right.set_valign(Gtk.Align.CENTER)
        cmp_controls.append(self.study_compare_left)
        cmp_controls.append(self.study_compare_right)
        cmp_button = Gtk.Button(label=_("Comparar"))
        cmp_button.add_css_class("soft-button")
        cmp_button.connect("clicked", self._on_study_compare_clicked)
        cmp_controls.append(cmp_button)
        compare_inner.append(cmp_controls)
        self.study_compare_list = Gtk.ListBox()
        self.study_compare_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.study_compare_list.add_css_class("boxed-list")
        compare_inner.append(self.study_compare_list)
        page.append(compare_card)

        refs_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        refs_card.add_css_class("card")
        refs_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        refs_inner.set_margin_top(10)
        refs_inner.set_margin_bottom(10)
        refs_inner.set_margin_start(12)
        refs_inner.set_margin_end(12)
        refs_card.append(refs_inner)
        refs_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        refs_title = Gtk.Label(label=_("Referências cruzadas"), xalign=0)
        refs_title.set_hexpand(True)
        refs_header.append(refs_title)
        refs_import = Gtk.Button(label=_("Importar"))
        refs_import.add_css_class("soft-button")
        refs_import.connect("clicked", self._on_study_import_crossrefs_clicked)
        refs_header.append(refs_import)
        refs_refresh = Gtk.Button(label=_("Atualizar"))
        refs_refresh.add_css_class("soft-button")
        refs_refresh.connect("clicked", self._on_study_refresh_refs_clicked)
        refs_header.append(refs_refresh)
        refs_inner.append(refs_header)
        self.study_refs_list = Gtk.ListBox()
        self.study_refs_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.study_refs_list.add_css_class("boxed-list")
        refs_inner.append(self.study_refs_list)
        page.append(refs_card)

        adv_search_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        adv_search_card.add_css_class("card")
        adv_search_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        adv_search_inner.set_margin_top(10)
        adv_search_inner.set_margin_bottom(10)
        adv_search_inner.set_margin_start(12)
        adv_search_inner.set_margin_end(12)
        adv_search_card.append(adv_search_inner)
        adv_title = Gtk.Label(label=_("Busca avançada de estudo"), xalign=0)
        adv_title.add_css_class("heading")
        adv_title.add_css_class("study-block-title")
        adv_search_inner.append(adv_title)

        adv_row_1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.study_adv_query = Gtk.SearchEntry(placeholder_text=_("Palavra, frase ou múltiplos termos"))
        self.study_adv_query.add_css_class("control-field")
        self.study_adv_query.set_hexpand(True)
        self.study_adv_query.connect("activate", self._on_study_advanced_search_clicked)
        adv_row_1.append(self.study_adv_query)
        self.study_adv_mode_codes = ["phrase", "any_terms", "all_terms"]
        self.study_adv_mode_dropdown = Gtk.DropDown.new_from_strings(
            [_("Frase"), _("Qualquer termo"), _("Todos os termos")]
        )
        self.study_adv_mode_dropdown.set_valign(Gtk.Align.CENTER)
        adv_row_1.append(self.study_adv_mode_dropdown)
        adv_search_inner.append(adv_row_1)

        adv_row_2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.study_adv_testament_codes = [0, 1, 2]
        self.study_adv_testament_dropdown = Gtk.DropDown.new_from_strings(
            [_("Toda a Bíblia"), _("Antigo Testamento"), _("Novo Testamento")]
        )
        self.study_adv_testament_dropdown.set_valign(Gtk.Align.CENTER)
        adv_row_2.append(self.study_adv_testament_dropdown)
        books_catalog = self._backend.list_books()
        self.study_adv_book_codes = [0] + [int(b["id"]) for b in books_catalog]
        self.study_adv_book_dropdown = Gtk.DropDown.new_from_strings(
            [_("Todos os livros")] + [str(b["name"]) for b in books_catalog]
        )
        self.study_adv_book_dropdown.set_valign(Gtk.Align.CENTER)
        self.study_adv_book_dropdown.set_hexpand(True)
        adv_row_2.append(self.study_adv_book_dropdown)
        self.study_adv_notes_only = Gtk.CheckButton(label=_("Somente com nota"))
        adv_row_2.append(self.study_adv_notes_only)
        adv_search_inner.append(adv_row_2)

        adv_row_3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        adv_row_3.append(Gtk.Label(label=_("Limite"), xalign=0))
        self.study_adv_limit_spin = Gtk.SpinButton.new_with_range(10, 500, 10)
        self.study_adv_limit_spin.set_value(80)
        adv_row_3.append(self.study_adv_limit_spin)
        adv_btn = Gtk.Button(label=_("Buscar no estudo"))
        adv_btn.add_css_class("soft-button")
        adv_btn.connect("clicked", self._on_study_advanced_search_clicked)
        adv_row_3.append(adv_btn)
        self.study_adv_info = Gtk.Label(label=_("Use filtros para localizar passagens de estudo."), xalign=0)
        self.study_adv_info.add_css_class("dim-label")
        self.study_adv_info.set_hexpand(True)
        adv_row_3.append(self.study_adv_info)
        adv_search_inner.append(adv_row_3)

        self.study_adv_results_list = Gtk.ListBox()
        self.study_adv_results_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.study_adv_results_list.add_css_class("boxed-list")
        adv_search_inner.append(self.study_adv_results_list)
        page.append(adv_search_card)

        plans_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        plans_card.add_css_class("card")
        plans_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        plans_inner.set_margin_top(10)
        plans_inner.set_margin_bottom(10)
        plans_inner.set_margin_start(12)
        plans_inner.set_margin_end(12)
        plans_card.append(plans_inner)
        plans_title = Gtk.Label(label=_("Planos de leitura"), xalign=0)
        plans_title.add_css_class("heading")
        plans_title.add_css_class("study-block-title")
        plans_inner.append(plans_title)
        self.study_plans_list = Gtk.ListBox()
        self.study_plans_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.study_plans_list.add_css_class("boxed-list")
        plans_inner.append(self.study_plans_list)
        page.append(plans_card)

        recent_entries_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        recent_entries_card.add_css_class("card")
        recent_entries_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        recent_entries_inner.set_margin_top(10)
        recent_entries_inner.set_margin_bottom(10)
        recent_entries_inner.set_margin_start(12)
        recent_entries_inner.set_margin_end(12)
        recent_entries_card.append(recent_entries_inner)
        recent_entries_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        recent_entries_title = Gtk.Label(label=_("Entradas recentes (todos cadernos)"), xalign=0)
        recent_entries_title.add_css_class("heading")
        recent_entries_title.add_css_class("study-block-title")
        recent_entries_title.set_hexpand(True)
        recent_entries_header.append(recent_entries_title)
        recent_entries_refresh = Gtk.Button(label=_("Atualizar"))
        recent_entries_refresh.add_css_class("soft-button")
        recent_entries_refresh.connect("clicked", self._on_study_refresh_recent_entries_clicked)
        recent_entries_header.append(recent_entries_refresh)
        recent_entries_inner.append(recent_entries_header)
        self.study_recent_entries_list = Gtk.ListBox()
        self.study_recent_entries_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.study_recent_entries_list.add_css_class("boxed-list")
        recent_entries_inner.append(self.study_recent_entries_list)
        page.append(recent_entries_card)

        notebook_entries_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        notebook_entries_card.add_css_class("card")
        notebook_entries_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        notebook_entries_inner.set_margin_top(10)
        notebook_entries_inner.set_margin_bottom(10)
        notebook_entries_inner.set_margin_start(12)
        notebook_entries_inner.set_margin_end(12)
        notebook_entries_card.append(notebook_entries_inner)
        entries_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        entries_title = Gtk.Label(label=_("Entradas do caderno"), xalign=0)
        entries_title.set_hexpand(True)
        entries_title.add_css_class("heading")
        entries_title.add_css_class("study-block-title")
        entries_header.append(entries_title)
        entries_refresh = Gtk.Button(label=_("Atualizar"))
        entries_refresh.add_css_class("soft-button")
        entries_refresh.connect("clicked", self._on_study_refresh_notebook_entries_clicked)
        entries_header.append(entries_refresh)
        notebook_entries_inner.append(entries_header)
        self.study_notebook_entries_list = Gtk.ListBox()
        self.study_notebook_entries_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.study_notebook_entries_list.add_css_class("boxed-list")
        notebook_entries_inner.append(self.study_notebook_entries_list)
        page.append(notebook_entries_card)

        notes_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        notes_card.add_css_class("card")
        notes_list_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        notes_list_inner.set_margin_top(10)
        notes_list_inner.set_margin_bottom(10)
        notes_list_inner.set_margin_start(12)
        notes_list_inner.set_margin_end(12)
        notes_card.append(notes_list_inner)
        notes_list_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        notes_list_title = Gtk.Label(label=_("Notas recentes"), xalign=0)
        notes_list_title.add_css_class("heading")
        notes_list_title.add_css_class("study-block-title")
        notes_list_title.set_hexpand(True)
        notes_list_header.append(notes_list_title)
        self.study_notes_filter_entry = Gtk.Entry(placeholder_text=_("Filtrar por tag (opcional)"))
        self.study_notes_filter_entry.add_css_class("control-field")
        self.study_notes_filter_entry.connect("activate", self._on_study_refresh_recent_notes_clicked)
        notes_list_header.append(self.study_notes_filter_entry)
        notes_list_refresh = Gtk.Button(label=_("Filtrar"))
        notes_list_refresh.add_css_class("soft-button")
        notes_list_refresh.connect("clicked", self._on_study_refresh_recent_notes_clicked)
        notes_list_header.append(notes_list_refresh)
        notes_list_inner.append(notes_list_header)
        self.study_recent_notes_list = Gtk.ListBox()
        self.study_recent_notes_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.study_recent_notes_list.add_css_class("boxed-list")
        notes_list_inner.append(self.study_recent_notes_list)
        page.append(notes_card)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_child(page)
        return scrolled

    def _build_settings_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        prefs = Adw.PreferencesPage()

        reading_group = Adw.PreferencesGroup(title=_("Leitura"))
        row_font = Adw.ActionRow(title=_("Tamanho da fonte"), subtitle=_("Ajuste da leitura dos versículos"))
        font_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.settings_font_minus = Gtk.Button(label="A-")
        self.settings_font_minus.add_css_class("soft-button")
        self.settings_font_minus.connect("clicked", self._on_font_minus_clicked)
        font_box.append(self.settings_font_minus)
        self.settings_font_label = Gtk.Label(label="100%")
        self.settings_font_label.add_css_class("monospace")
        font_box.append(self.settings_font_label)
        self.settings_font_plus = Gtk.Button(label="A+")
        self.settings_font_plus.add_css_class("soft-button")
        self.settings_font_plus.connect("clicked", self._on_font_plus_clicked)
        font_box.append(self.settings_font_plus)
        row_font.add_suffix(font_box)
        row_font.set_activatable(False)
        reading_group.add(row_font)

        row_reading_layout = Adw.ActionRow(
            title=_("Layout da leitura"),
            subtitle=_("Escolha entre cartões por versículo ou texto contínuo (estilo livro)"),
        )
        self.reading_layout_codes = ["cards", "continuous"]
        self.reading_layout_dropdown = Gtk.DropDown.new_from_strings(
            [_("Cards por versículo"), _("Texto contínuo")]
        )
        self.reading_layout_dropdown.set_valign(Gtk.Align.CENTER)
        self.reading_layout_dropdown.connect("notify::selected", self._on_reading_layout_changed)
        row_reading_layout.add_suffix(self.reading_layout_dropdown)
        row_reading_layout.set_activatable(False)
        reading_group.add(row_reading_layout)

        row_tts_voice = Adw.ActionRow(
            title=_("Idioma da voz (TTS)"),
            subtitle=_("Define o idioma da leitura em voz; use Manual se a detecção automática falhar"),
        )
        self.tts_voice_codes = [
            "auto", "pt-br", "en", "es", "fr", "de", "it",
            "ru", "uk", "pl", "cs", "ro", "nl", "sv", "tr",
            "ja", "zh", "ko", "he", "ar", "hi", "la",
        ]
        self.tts_voice_dropdown = Gtk.DropDown.new_from_strings(
            [
                _("Automático (pela tradução)"),
                "Português (Brasil)", "English", "Español", "Français", "Deutsch", "Italiano",
                "Русский", "Українська", "Polski", "Čeština", "Română", "Nederlands", "Svenska", "Türkçe",
                "日本語", "中文", "한국어", "עברית", "العربية", "हिन्दी", "Latina",
            ]
        )
        self.tts_voice_dropdown.set_valign(Gtk.Align.CENTER)
        self.tts_voice_dropdown.connect("notify::selected", self._on_tts_voice_changed)
        row_tts_voice.add_suffix(self.tts_voice_dropdown)
        row_tts_voice.set_activatable(False)
        reading_group.add(row_tts_voice)

        row_tts_engine_info = Adw.ActionRow(
            title=_("Motor da voz (TTS)"),
            subtitle=_("Piper (Neural) integrado ao app para melhor qualidade e funcionamento offline"),
        )
        engine_chip = Gtk.Label(label="Piper (Neural)")
        engine_chip.add_css_class("dim-label")
        row_tts_engine_info.add_suffix(engine_chip)
        row_tts_engine_info.set_activatable(False)
        reading_group.add(row_tts_engine_info)

        appearance_group = Adw.PreferencesGroup(title=_("Aparência"))
        row_theme = Adw.ActionRow(
            title=_("Tema"),
            subtitle=_("Escolha entre sistema, claro ou escuro para facilitar a leitura"),
        )
        self.theme_codes = ["system", "light", "dark"]
        self.theme_dropdown = Gtk.DropDown.new_from_strings(
            [_("Sistema"), _("Claro"), _("Escuro")]
        )
        self.theme_dropdown.connect("notify::selected", self._on_theme_changed)
        row_theme.add_suffix(self.theme_dropdown)
        row_theme.set_activatable(False)
        appearance_group.add(row_theme)

        row_language = Adw.ActionRow(
            title=_("Idioma da interface"),
            subtitle=_("Escolha o idioma do app (aplica após reiniciar)"),
        )
        self.ui_language_codes = ["system", "pt_BR", "en", "es"]
        self.ui_language_dropdown = Gtk.DropDown.new_from_strings(
            [_("Sistema"), "Português (Brasil)", "English", "Español"]
        )
        self.ui_language_dropdown.set_valign(Gtk.Align.CENTER)
        self.ui_language_dropdown.connect("notify::selected", self._on_ui_language_changed)
        row_language.add_suffix(self.ui_language_dropdown)
        row_language.set_activatable(False)
        appearance_group.add(row_language)

        shortcuts_group = Adw.PreferencesGroup(title=_("Atalhos"))
        shortcuts_text = (
            _("Ctrl+F: busca | Ctrl+L: leitura | Ctrl+D: favoritos | Ctrl+E: estudo | Ctrl+, : configurações | ")
            + _("Alt+←/Alt+→: capítulo anterior/próximo")
        )
        row_shortcuts = Adw.ActionRow(title=_("Atalhos disponíveis"), subtitle=shortcuts_text)
        row_shortcuts.set_activatable(False)
        shortcuts_group.add(row_shortcuts)

        prefs.add(reading_group)
        prefs.add(appearance_group)

        daily_group = Adw.PreferencesGroup(
            title=_("Conteúdo diário"),
            description=_("Configure o tipo de mensagem, agenda, entrega e diagnóstico das notificações."),
        )
        daily_schedule_group = Adw.PreferencesGroup(
            title=_("Agenda"),
            description=_("Defina quando as mensagens devem ser enviadas ao longo do dia."),
        )
        daily_delivery_group = Adw.PreferencesGroup(
            title=_("Entrega e alerta"),
            description=_("Escolha como receber as mensagens e como o alerta sonoro deve se comportar."),
        )
        daily_actions_group = Adw.PreferencesGroup(
            title=_("Ações"),
            description=_("Aplicar, testar e consultar o agendamento configurado no sistema."),
        )
        daily_status_group = Adw.PreferencesGroup(
            title=_("Resumo e diagnóstico"),
            description=_("Resumo atual da configuração e status do timer do sistema."),
        )

        row_enable = Adw.SwitchRow(
            title=_("Ativar conteúdo diário"),
            subtitle=_("Envia notificação do sistema com versículo/estudo/esboço no horário definido"),
        )
        row_enable.connect("notify::active", self._on_daily_enabled_changed)
        self.daily_enabled_switch = row_enable
        daily_group.add(row_enable)

        row_mode = Adw.ActionRow(title=_("Tipo de conteúdo"), subtitle=_("Escolha o formato da mensagem diária"))
        self.daily_mode_codes = ["verse", "study", "outline"]
        self.daily_mode_dropdown = Gtk.DropDown.new_from_strings(
            [_("Versículo do dia"), _("Estudo diário"), _("Esboço diário")]
        )
        self.daily_mode_dropdown.set_valign(Gtk.Align.CENTER)
        self.daily_mode_dropdown.connect("notify::selected", self._on_daily_mode_changed)
        row_mode.add_suffix(self.daily_mode_dropdown)
        row_mode.set_activatable(False)
        daily_group.add(row_mode)

        row_daily_translation = Adw.ActionRow(
            title=_("Tradução do conteúdo diário"),
            subtitle=_("Escolha uma tradução fixa ou use a tradução ativa da leitura"),
        )
        daily_catalog = self._backend.list_translation_catalog()
        self.daily_content_translation_codes = [""] + [item["code"] for item in daily_catalog]
        self.daily_content_translation_dropdown = Gtk.DropDown.new_from_strings(
            [_("Usar tradução ativa")] + [item["label"] for item in daily_catalog]
        )
        self.daily_content_translation_dropdown.set_valign(Gtk.Align.CENTER)
        self.daily_content_translation_dropdown.connect(
            "notify::selected", self._on_daily_content_translation_changed
        )
        row_daily_translation.add_suffix(self.daily_content_translation_dropdown)
        row_daily_translation.set_activatable(False)
        daily_group.add(row_daily_translation)

        row_time = Adw.ActionRow(title=_("Horário"), subtitle=_("Formato 24h (HH:MM)"))
        self.daily_time_entry = Gtk.Entry()
        self.daily_time_entry.add_css_class("control-field")
        self.daily_time_entry.set_width_chars(5)
        self.daily_time_entry.set_max_length(5)
        self.daily_time_entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        self.daily_time_entry.set_valign(Gtk.Align.CENTER)
        self.daily_time_entry.connect("changed", self._on_time_entry_changed)
        self.daily_time_entry.connect("activate", self._on_daily_apply_clicked)
        row_time.add_suffix(self.daily_time_entry)
        row_time.set_activatable(False)
        daily_schedule_group.add(row_time)

        row_end_time = Adw.ActionRow(title=_("Hora final"), subtitle=_("Fim da janela diária (HH:MM)"))
        self.daily_end_time_entry = Gtk.Entry()
        self.daily_end_time_entry.add_css_class("control-field")
        self.daily_end_time_entry.set_width_chars(5)
        self.daily_end_time_entry.set_max_length(5)
        self.daily_end_time_entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        self.daily_end_time_entry.set_valign(Gtk.Align.CENTER)
        self.daily_end_time_entry.connect("changed", self._on_time_entry_changed)
        self.daily_end_time_entry.connect("activate", self._on_daily_apply_clicked)
        row_end_time.add_suffix(self.daily_end_time_entry)
        row_end_time.set_activatable(False)
        self.daily_end_time_row = row_end_time
        daily_schedule_group.add(row_end_time)

        row_schedule_mode = Adw.ActionRow(
            title=_("Frequência"),
            subtitle=_("Escolha se envia uma vez ao dia ou repetido durante o dia"),
        )
        self.daily_schedule_mode_codes = ["once", "repeat"]
        self.daily_schedule_mode_dropdown = Gtk.DropDown.new_from_strings(
            [_("Uma vez ao dia"), _("Repetir no dia")]
        )
        self.daily_schedule_mode_dropdown.set_valign(Gtk.Align.CENTER)
        self.daily_schedule_mode_dropdown.connect(
            "notify::selected", self._on_daily_schedule_mode_changed
        )
        row_schedule_mode.add_suffix(self.daily_schedule_mode_dropdown)
        row_schedule_mode.set_activatable(False)
        daily_schedule_group.add(row_schedule_mode)

        row_count = Adw.ActionRow(title=_("Número de envios"), subtitle=_("Usado quando a frequência é repetida"))
        self.daily_count_spin = Gtk.SpinButton.new_with_range(1, 24, 1)
        self.daily_count_spin.set_valign(Gtk.Align.CENTER)
        self.daily_count_spin.connect("value-changed", self._on_daily_count_changed)
        row_count.add_suffix(self.daily_count_spin)
        row_count.set_activatable(False)
        self.daily_count_row = row_count
        row_count.set_visible(False)
        daily_schedule_group.add(row_count)

        row_interval = Adw.ActionRow(title=_("Intervalo (min)"), subtitle=_("Intervalo entre mensagens (quando repetido)"))
        self.daily_interval_spin = Gtk.SpinButton.new_with_range(5, 1440, 5)
        self.daily_interval_spin.set_increments(5, 30)
        self.daily_interval_spin.set_valign(Gtk.Align.CENTER)
        self.daily_interval_spin.connect("value-changed", self._on_daily_interval_changed)
        row_interval.add_suffix(self.daily_interval_spin)
        row_interval.set_activatable(False)
        self.daily_interval_row = row_interval
        daily_schedule_group.add(row_interval)

        row_persistent = Adw.SwitchRow(
            title=_("Notificação persistente"),
            subtitle=_("Tenta manter a notificação até interação (depende do daemon do sistema)"),
        )
        row_persistent.connect("notify::active", self._on_daily_persistent_changed)
        self.daily_persistent_switch = row_persistent
        daily_delivery_group.add(row_persistent)

        row_delivery = Adw.ActionRow(
            title=_("Entrega"),
            subtitle=_("Escolha entre notificação nativa ou popup do BíbliaRoot"),
        )
        self.daily_delivery_codes = ["native", "popup"]
        self.daily_delivery_dropdown = Gtk.DropDown.new_from_strings(
            [_("Nativa do sistema"), _("Popup do BíbliaRoot")]
        )
        self.daily_delivery_dropdown.set_valign(Gtk.Align.CENTER)
        self.daily_delivery_dropdown.connect("notify::selected", self._on_daily_delivery_changed)
        row_delivery.add_suffix(self.daily_delivery_dropdown)
        row_delivery.set_activatable(False)
        daily_delivery_group.add(row_delivery)

        row_sound = Adw.SwitchRow(
            title=_("Tocar som"),
            subtitle=_("Tenta tocar um som junto da mensagem (melhor esforço)"),
        )
        row_sound.connect("notify::active", self._on_daily_sound_changed)
        self.daily_sound_switch = row_sound
        daily_delivery_group.add(row_sound)

        row_sound_type = Adw.ActionRow(
            title=_("Som do alerta"),
            subtitle=_("Escolha o bipe usado quando 'Tocar som' estiver ativado"),
        )
        self.daily_sound_codes = ["soft", "bell", "alert"]
        self.daily_sound_dropdown = Gtk.DropDown.new_from_strings(
            [_("Suave"), _("Sino"), _("Alerta")]
        )
        self.daily_sound_dropdown.set_valign(Gtk.Align.CENTER)
        self.daily_sound_dropdown.connect("notify::selected", self._on_daily_sound_type_changed)
        row_sound_type.add_suffix(self.daily_sound_dropdown)
        row_sound_type.set_activatable(False)
        self.daily_sound_row = row_sound_type
        daily_delivery_group.add(row_sound_type)

        row_actions_preview = Adw.ActionRow(
            title=_("Pré-visualização"),
            subtitle=_("Veja a prévia e teste o envio imediatamente"),
        )
        btn_preview = Gtk.Button(label=_("Prévia"))
        btn_preview.add_css_class("soft-button")
        btn_preview.set_valign(Gtk.Align.CENTER)
        btn_preview.connect("clicked", self._on_daily_preview_clicked)
        row_actions_preview.add_suffix(btn_preview)

        btn_test = Gtk.Button(label=_("Testar agora"))
        btn_test.add_css_class("soft-button")
        btn_test.set_valign(Gtk.Align.CENTER)
        btn_test.connect("clicked", self._on_daily_test_now_clicked)
        row_actions_preview.add_suffix(btn_test)
        row_actions_preview.set_activatable(False)
        daily_actions_group.add(row_actions_preview)

        row_actions_apply = Adw.ActionRow(
            title=_("Agendamento do sistema"),
            subtitle=_("Usa systemd --user no Linux"),
        )
        btn_apply = Gtk.Button(label=_("Aplicar"))
        btn_apply.add_css_class("suggested-action")
        btn_apply.add_css_class("soft-button")
        btn_apply.set_valign(Gtk.Align.CENTER)
        btn_apply.connect("clicked", self._on_daily_apply_clicked)
        row_actions_apply.add_suffix(btn_apply)
        self.daily_apply_button = btn_apply

        btn_disable = Gtk.Button(label=_("Desativar"))
        btn_disable.add_css_class("destructive-action")
        btn_disable.add_css_class("soft-button")
        btn_disable.set_valign(Gtk.Align.CENTER)
        btn_disable.connect("clicked", self._on_daily_disable_clicked)
        row_actions_apply.add_suffix(btn_disable)
        row_actions_apply.set_activatable(False)
        daily_actions_group.add(row_actions_apply)

        row_status_actions = Adw.ActionRow(
            title=_("Diagnóstico"),
            subtitle=_("Consultar status do timer e último erro/sucesso"),
        )
        btn_status = Gtk.Button(label=_("Status do timer"))
        btn_status.add_css_class("soft-button")
        btn_status.set_valign(Gtk.Align.CENTER)
        btn_status.connect("clicked", self._on_daily_status_clicked)
        row_status_actions.add_suffix(btn_status)

        btn_copy_error = Gtk.Button(label=_("Copiar erro"))
        btn_copy_error.add_css_class("soft-button")
        btn_copy_error.set_valign(Gtk.Align.CENTER)
        btn_copy_error.connect("clicked", self._on_copy_daily_error_clicked)
        row_status_actions.add_suffix(btn_copy_error)
        self.daily_copy_error_button = btn_copy_error
        row_status_actions.set_activatable(False)
        daily_actions_group.add(row_status_actions)

        self.daily_preview_label = Gtk.Label(label=_("Prévia: desativado."), xalign=0, wrap=True)
        self.daily_preview_label.add_css_class("dim-label")
        self.daily_preview_label.set_selectable(True)
        daily_preview_row = self._wrap_in_preferences_row(self.daily_preview_label)
        daily_status_group.add(daily_preview_row)
        self.daily_timer_status_label = Gtk.Label(
            label=_("Timer: status não consultado."), xalign=0, wrap=True
        )
        self.daily_timer_status_label.add_css_class("dim-label")
        self.daily_timer_status_label.set_selectable(True)
        daily_status_row = self._wrap_in_preferences_row(self.daily_timer_status_label)
        daily_status_group.add(daily_status_row)

        prefs.add(daily_group)
        prefs.add(daily_schedule_group)
        prefs.add(daily_delivery_group)
        prefs.add(daily_actions_group)
        prefs.add(daily_status_group)
        prefs.add(shortcuts_group)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_child(prefs)
        page.append(scrolled)
        return page

    def _load_initial_state(self) -> None:
        state = self._backend.initialize()
        self._font_scale = float(state.settings.font_scale or 1.0)
        self._theme_mode = str(getattr(state.settings, "theme_mode", "system") or "system")
        self._reading_layout = str(getattr(state.settings, "reading_layout", "cards") or "cards")
        self._apply_font_scale(self._font_scale, persist=False)
        self._apply_theme_mode(self._theme_mode, persist=False)
        self._apply_reading_layout(self._reading_layout, persist=False)
        self._sync_settings_controls()

        if not state.translations:
            self.reader_title.set_text(_("Nenhum banco encontrado"))
            self.status_line.set_text(
                _("Rode scripts/setup_db.py ou copie os .sqlite para data/bibles/.")
            )
            self._set_status_row(self.verse_list, _("Nenhum banco SQLite encontrado em data/bibles/."))
            return

        self.translation_switcher.set_translation_catalog(
            self._backend.list_translation_catalog(),
            selected_code=state.translation,
        )
        if hasattr(self, "study_compare_codes") and state.translation in self.study_compare_codes:
            idx = self.study_compare_codes.index(state.translation)
            self.study_compare_left.set_selected(idx)
            self.study_compare_right.set_selected(min(idx + 1, max(0, len(self.study_compare_codes) - 1)))
        preferred_book_id = state.settings.last_book_id
        preferred_chapter = max(1, int(state.settings.last_chapter or 1))
        self._refresh_books(preferred_book_id=preferred_book_id, preferred_chapter=preferred_chapter)
        self._refresh_favorites()
        self._refresh_study_page()
        self.status_line.set_text(
            f'{_("Tradução ativa")}: {state.translation} | {len(state.translations)} {_("traduções disponíveis")}'
        )

    def _refresh_books(
        self, *, preferred_book_id: int | None = None, preferred_chapter: int = 1
    ) -> None:
        try:
            books = self._backend.list_books()
        except FileNotFoundError as exc:
            self.reader_title.set_text(_("Banco não encontrado"))
            self.status_line.set_text(str(exc))
            self._set_status_row(self.verse_list, str(exc))
            return

        self.sidebar.set_books(books)
        if not books:
            self._selected_book_id = None
            self._set_status_row(self.verse_list, _("Sem livros nesta tradução."))
            return

        book_ids = {int(book["id"]) for book in books}
        if preferred_book_id is not None and int(preferred_book_id) in book_ids:
            target_book_id = int(preferred_book_id)
        else:
            target_book_id = int(books[0]["id"])

        self._selected_book_id = target_book_id
        self.sidebar.select_book(target_book_id)
        total = self._backend.db.get_chapter_count(target_book_id)
        chapter = min(max(1, int(preferred_chapter)), max(1, total))
        self.chapter_panel.set_chapters(total, selected=chapter)
        self._load_chapter(chapter)

    def _on_book_selected(self, book_id_text: str) -> None:
        self._selected_book_id = int(book_id_text)
        total = self._backend.db.get_chapter_count(self._selected_book_id)
        self.chapter_panel.set_chapters(total, selected=1)
        self._load_chapter(1)

    def _on_chapter_selected(self, chapter: int) -> None:
        self._load_chapter(chapter)

    def _on_prev_chapter_clicked(self, _button: Gtk.Button) -> None:
        if self._selected_chapter > 1:
            self.chapter_panel.set_chapters(
                self._backend.db.get_chapter_count(self._selected_book_id or 0),
                selected=self._selected_chapter - 1,
            )
            self._load_chapter(self._selected_chapter - 1)

    def _on_next_chapter_clicked(self, _button: Gtk.Button) -> None:
        if self._selected_book_id is None:
            return
        max_ch = self._backend.db.get_chapter_count(self._selected_book_id)
        if self._selected_chapter < max_ch:
            self.chapter_panel.set_chapters(max_ch, selected=self._selected_chapter + 1)
            self._load_chapter(self._selected_chapter + 1)

    def _on_font_minus_clicked(self, _button: Gtk.Button) -> None:
        self._apply_font_scale(self._font_scale - 0.1)

    def _on_font_plus_clicked(self, _button: Gtk.Button) -> None:
        self._apply_font_scale(self._font_scale + 0.1)

    def _apply_font_scale(self, value: float, *, persist: bool = True) -> None:
        self._font_scale = min(2.0, max(0.8, round(float(value), 2)))
        percent = int(round(self._font_scale * 100))
        self.font_scale_label.set_text(f"{percent}%")
        if hasattr(self, "settings_font_label"):
            self.settings_font_label.set_text(f"{percent}%")
        font_px = int(round(15 * self._font_scale))
        css = f"""
        .verse-text, .search-text, .favorite-text, .reader-continuous-text {{
            font-size: {font_px}px;
            line-height: 1.45;
        }}
        .verse-row-highlight {{
            background-color: alpha(@accent_color, 0.16);
            border-radius: 10px;
        }}
        """
        self._font_css_provider.load_from_data(css)
        display = self.get_display()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                self._font_css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        if persist:
            self._backend.set_font_scale(self._font_scale)
            self._toast(f'{_("Fonte ajustada para")} {percent}%.')

    def _apply_theme_mode(self, mode: str, *, persist: bool = True) -> None:
        mode = mode if mode in {"system", "light", "dark"} else "system"
        self._theme_mode = mode
        manager = Adw.StyleManager.get_default()
        if mode == "dark":
            manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        elif mode == "light":
            manager.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        else:
            manager.set_color_scheme(Adw.ColorScheme.DEFAULT)
        if hasattr(self, "theme_dropdown"):
            try:
                idx = self.theme_codes.index(mode)
            except ValueError:
                idx = 0
            self.theme_dropdown.set_selected(idx)
        if persist:
            self._backend.set_theme_mode(mode)
            labels = {"system": _("Sistema"), "light": _("Claro"), "dark": _("Escuro")}
            self._toast(f'{_("Tema definido")}: {labels[mode]}.')

    def _apply_reading_layout(self, layout: str, *, persist: bool = True) -> None:
        layout = layout if layout in {"cards", "continuous"} else "cards"
        self._reading_layout = layout
        if hasattr(self, "reader_content_stack"):
            self.reader_content_stack.set_visible_child_name(layout)
        if hasattr(self, "reader_layout_toggle_button"):
            self.reader_layout_toggle_button.set_label(
                _("Cards por versículo") if layout == "continuous" else _("Texto contínuo")
            )
        if hasattr(self, "reading_layout_dropdown"):
            try:
                self.reading_layout_dropdown.set_selected(self.reading_layout_codes.index(layout))
            except ValueError:
                self.reading_layout_dropdown.set_selected(0)
        if persist:
            self._backend.set_reading_layout(layout)
            self._toast(
                _("Layout de leitura: cards por versículo.")
                if layout == "cards"
                else _("Layout de leitura: texto contínuo.")
            )
        if self._current_chapter_payload is not None:
            self._render_reader_verses(self._current_chapter_payload)

    def _sync_settings_controls(self) -> None:
        settings = self._backend.get_settings()
        self._daily_controls_syncing = True
        try:
            if hasattr(self, "settings_font_label"):
                self.settings_font_label.set_text(self.font_scale_label.get_text())
            if hasattr(self, "theme_dropdown"):
                try:
                    self.theme_dropdown.set_selected(self.theme_codes.index(self._theme_mode))
                except ValueError:
                    self.theme_dropdown.set_selected(0)
            if hasattr(self, "ui_language_dropdown"):
                ui_lang = str(getattr(settings, "ui_language", "system") or "system")
                try:
                    self.ui_language_dropdown.set_selected(self.ui_language_codes.index(ui_lang))
                except ValueError:
                    self.ui_language_dropdown.set_selected(0)
            if hasattr(self, "reading_layout_dropdown"):
                layout = str(getattr(settings, "reading_layout", "cards") or "cards")
                try:
                    self.reading_layout_dropdown.set_selected(self.reading_layout_codes.index(layout))
                except ValueError:
                    self.reading_layout_dropdown.set_selected(0)
            if hasattr(self, "tts_voice_dropdown"):
                voice_lang = str(getattr(settings, "tts_voice_language", "auto") or "auto").lower()
                try:
                    self.tts_voice_dropdown.set_selected(self.tts_voice_codes.index(voice_lang))
                except ValueError:
                    self.tts_voice_dropdown.set_selected(0)
            if hasattr(self, "daily_enabled_switch"):
                self.daily_enabled_switch.set_active(bool(settings.daily_content_enabled))
            if hasattr(self, "daily_mode_dropdown"):
                try:
                    idx = self.daily_mode_codes.index(settings.daily_content_mode)
                except ValueError:
                    idx = 0
                self.daily_mode_dropdown.set_selected(idx)
            if hasattr(self, "daily_content_translation_dropdown"):
                daily_tr = (getattr(settings, "daily_content_translation", "") or "").strip().upper()
                try:
                    idx = self.daily_content_translation_codes.index(daily_tr)
                except ValueError:
                    idx = 0
                self.daily_content_translation_dropdown.set_selected(idx)
            if hasattr(self, "daily_time_entry"):
                self.daily_time_entry.set_text(str(settings.daily_content_time or "08:00"))
            if hasattr(self, "daily_end_time_entry"):
                self.daily_end_time_entry.set_text(
                    str(getattr(settings, "daily_content_end_time", settings.daily_content_time) or "08:00")
                )
            count_value = int(getattr(settings, "daily_messages_per_day", 1) or 1)
            if hasattr(self, "daily_schedule_mode_dropdown"):
                same_window = (
                    getattr(settings, "daily_content_end_time", settings.daily_content_time)
                    == settings.daily_content_time
                )
                self.daily_schedule_mode_dropdown.set_selected(0 if same_window else 1)
            if hasattr(self, "daily_count_spin"):
                self.daily_count_spin.set_value(count_value)
            if hasattr(self, "daily_interval_spin"):
                self.daily_interval_spin.set_value(
                    int(getattr(settings, "daily_interval_minutes", 180) or 180)
                )
            if hasattr(self, "daily_persistent_switch"):
                self.daily_persistent_switch.set_active(
                    bool(getattr(settings, "daily_notification_persistent", True))
                )
            if hasattr(self, "daily_delivery_dropdown"):
                delivery = getattr(settings, "daily_delivery_mode", "native") or "native"
                self.daily_delivery_dropdown.set_selected(0 if delivery == "native" else 1)
            if hasattr(self, "daily_sound_switch"):
                self.daily_sound_switch.set_active(
                    bool(getattr(settings, "daily_sound_enabled", False))
                )
            if hasattr(self, "daily_sound_dropdown"):
                sound_name = getattr(settings, "daily_sound_name", "soft") or "soft"
                try:
                    self.daily_sound_dropdown.set_selected(self.daily_sound_codes.index(sound_name))
                except ValueError:
                    self.daily_sound_dropdown.set_selected(0)
        finally:
            self._daily_controls_syncing = False
        self._refresh_daily_schedule_controls()
        self._update_daily_preview_label()

    def _on_translation_changed(self, translation: str) -> None:
        self._backend.set_translation(translation)
        self.search_entry.set_text("")
        self.quick_search.set_text("")
        self.search_info.set_text(f'{_("Tradução ativa para busca/leitura")}: {translation}')
        self._clear_list(self.search_results_list)
        self._refresh_books(preferred_chapter=1)
        self._refresh_favorites()
        self._refresh_study_page()
        self.status_line.set_text(
            f'{_("Tradução ativa")}: {translation} | {len(self._backend.list_books())} {_("livros")}'
        )
        self._toast(f'{_("Tradução alterada para")} {translation}.')

    def _on_theme_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        index = int(dropdown.get_selected())
        if index < 0 or index >= len(self.theme_codes):
            return
        mode = self.theme_codes[index]
        if mode == self._theme_mode:
            return
        self._apply_theme_mode(mode, persist=True)

    def _on_ui_language_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._daily_controls_syncing:
            return
        idx = int(dropdown.get_selected())
        if idx < 0 or idx >= len(self.ui_language_codes):
            return
        code = self.ui_language_codes[idx]
        self._backend.set_ui_language(code)
        self.status_line.set_text(
            _("Idioma salvo. Reinicie o app para aplicar a tradução da interface.")
        )
        self._toast(_("Idioma salvo. Reinicie o app."))

    def _on_reading_layout_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._daily_controls_syncing:
            return
        idx = int(dropdown.get_selected())
        if idx < 0 or idx >= len(self.reading_layout_codes):
            return
        layout = self.reading_layout_codes[idx]
        if layout == self._reading_layout:
            return
        self._apply_reading_layout(layout, persist=True)

    def _on_tts_voice_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._daily_controls_syncing:
            return
        idx = int(dropdown.get_selected())
        if idx < 0 or idx >= len(self.tts_voice_codes):
            return
        code = self.tts_voice_codes[idx]
        self._backend.set_tts_voice_language(code)
        self._toast(_("Idioma da voz salvo."))

    def _load_chapter(self, chapter: int) -> None:
        if self._selected_book_id is None:
            return
        payload = self._backend.open_chapter(book_id=self._selected_book_id, chapter=chapter)
        if not payload:
            self._current_chapter_payload = None
            self.reader_title.set_text(_("Capítulo não encontrado"))
            self._set_status_row(self.verse_list, _("Nenhum versículo encontrado para este capítulo."))
            return

        self._selected_chapter = int(chapter)
        self._current_chapter_payload = payload
        book = payload["book"]
        verses = payload["verses"]
        self.reader_title.set_text(f'{book["name"]} {chapter} ({payload["translation"]})')
        self.reader_chapter_meta_label.set_text(
            f'{chapter}/{int(payload.get("chapter_count") or 0)} · {len(verses)}v'
        )
        self.status_line.set_text(
            f'{_("Lendo")} {book["name"]} {chapter} | {len(verses)} {_("versículos")} | {_("tradução")} {payload["translation"]}'
        )
        self.prev_chapter_button.set_sensitive(self._selected_chapter > 1)
        self.next_chapter_button.set_sensitive(
            self._selected_book_id is not None
            and self._selected_chapter < self._backend.db.get_chapter_count(self._selected_book_id)
        )
        self._render_reader_verses(payload)

    def _render_reader_verses(self, payload: dict) -> None:
        if self._reading_layout == "continuous":
            try:
                self._render_reader_continuous(payload)
                return
            except Exception as exc:
                # Fallback seguro: não deixa a tela branca caso algo do runtime GTK falhe.
                print("Falha no modo de leitura contínuo; revertendo para cards.")
                traceback.print_exc()
                self._reading_layout = "cards"
                if hasattr(self, "reader_content_stack"):
                    self.reader_content_stack.set_visible_child_name("cards")
                self.status_line.set_text(
                    _("Falha ao renderizar texto contínuo; voltando para cards.")
                    + f" ({exc})"
                )
                self._toast(_("Texto contínuo indisponível neste ambiente; usando cards."))
        self._clear_list(self.verse_list)
        self._reader_rows_by_verse.clear()
        book = payload["book"]
        translation = payload["translation"]
        chapter = int(payload["chapter"])
        chapter_notes = {
            int(item["verse"]): item
            for item in self._backend.list_study_notes(
                translation=translation,
                book=str(book["name"]),
                chapter=chapter,
                limit=500,
            )
        }

        for item in payload["verses"]:
            verse = int(item["verse"])
            text = str(item["text"])
            is_fav = self._backend.favorites.is_favorite(
                translation=translation,
                book=str(book["name"]),
                chapter=chapter,
                verse=verse,
            )
            row = self._build_verse_row(
                book_id=int(book["id"]),
                book_name=str(book["name"]),
                chapter=chapter,
                verse=verse,
                text=text,
                translation=translation,
                is_favorite=is_fav,
                study_note=chapter_notes.get(verse),
            )
            self.verse_list.append(row)
            self._reader_rows_by_verse[verse] = row

        if self._highlight_verse is not None and self._highlight_verse in self._reader_rows_by_verse:
            self._mark_row_highlight(self._reader_rows_by_verse[self._highlight_verse])

    def _render_reader_continuous(self, payload: dict) -> None:
        self._clear_list(self.verse_list)
        self._reader_rows_by_verse.clear()
        book = payload["book"]
        chapter = int(payload["chapter"])
        translation = str(payload["translation"])
        verses = list(payload.get("verses") or [])
        if not verses:
            self.reader_continuous_title.set_text("")
            self.reader_continuous_buffer.set_text(_("Nenhum versículo encontrado para este capítulo."))
            return
        self.reader_continuous_title.set_text(f'{book["name"]} {chapter} ({translation})')
        chapter_notes = {
            int(item["verse"]): item
            for item in self._backend.list_study_notes(
                translation=translation,
                book=str(book["name"]),
                chapter=chapter,
                limit=500,
            )
        }
        buf = self.reader_continuous_buffer
        buf.set_text("")
        for idx, item in enumerate(verses):
            verse_no = int(item["verse"])
            verse_text = str(item["text"])
            block_start_offset = buf.get_end_iter().get_offset()
            if idx > 0:
                # Espaço de fluxo contínuo entre versículos (sem quebrar como cards).
                buf.insert(buf.get_end_iter(), "  ")
            if verse_no == self._highlight_verse:
                buf.insert(buf.get_end_iter(), "►")
            num_start_offset = buf.get_end_iter().get_offset()
            buf.insert(buf.get_end_iter(), str(verse_no))
            num_end_offset = buf.get_end_iter().get_offset()
            buf.apply_tag(
                self.reader_continuous_num_tag,
                buf.get_iter_at_offset(num_start_offset),
                buf.get_iter_at_offset(num_end_offset),
            )
            if verse_no in chapter_notes:
                note_start_offset = buf.get_end_iter().get_offset()
                buf.insert(buf.get_end_iter(), "✎")
                note_end_offset = buf.get_end_iter().get_offset()
                buf.apply_tag(
                    self.reader_continuous_note_tag,
                    buf.get_iter_at_offset(note_start_offset),
                    buf.get_iter_at_offset(note_end_offset),
                )
            buf.insert(buf.get_end_iter(), " ")
            buf.insert(buf.get_end_iter(), verse_text)
            block_end_offset = buf.get_end_iter().get_offset()
            if verse_no == self._highlight_verse:
                buf.apply_tag(
                    self.reader_continuous_highlight_tag,
                    buf.get_iter_at_offset(block_start_offset),
                    buf.get_iter_at_offset(block_end_offset),
                )

    def _on_reader_layout_toggle_clicked(self, _button: Gtk.Button) -> None:
        target = "continuous" if self._reading_layout == "cards" else "cards"
        self._apply_reading_layout(target, persist=True)

    def _chapter_plain_text(self) -> tuple[str, str] | None:
        payload = self._current_chapter_payload
        if not payload:
            return None
        book_name = str(payload["book"]["name"])
        chapter = int(payload["chapter"])
        translation = str(payload["translation"])
        lines = [f"{book_name} {chapter} ({translation})", ""]
        for v in payload.get("verses", []):
            lines.append(f'{int(v["verse"])}. {str(v["text"])}')
        return "\n".join(lines), translation

    def _chapter_tts_text(self) -> tuple[str, str] | None:
        payload = self._current_chapter_payload
        if not payload:
            return None
        book_name = str(payload["book"]["name"])
        chapter = int(payload["chapter"])
        translation = str(payload["translation"])
        parts: list[str] = [f"{book_name} {chapter}."]
        # Leitura contínua natural: sem cabeçalho técnico e sem numeração de versículos a cada linha.
        for v in payload.get("verses", []):
            verse_text = self._sanitize_tts_text(str(v.get("text") or ""))
            if verse_text:
                parts.append(verse_text)
        return " ".join(parts), translation

    def _sanitize_tts_text(self, text: str) -> str:
        cleaned = str(text or "")
        # Remove marcadores visuais usados na UI e normaliza whitespace/pontuação para TTS.
        cleaned = cleaned.replace("►", " ").replace("✎", " ")
        cleaned = cleaned.replace("\u00a0", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        # Números de versículo inline (ex.: "12. ") podem deixar a fala truncada; remova no início de bloco.
        cleaned = re.sub(r"^\s*\d+\s*[\.\-:)]\s*", "", cleaned)
        return cleaned.strip()

    def _on_copy_chapter_clicked(self, _button: Gtk.Button) -> None:
        chapter_data = self._chapter_plain_text()
        if not chapter_data:
            self._toast(_("Nenhum capítulo carregado para copiar."))
            return
        text, _translation = chapter_data
        self._on_copy_verse_clicked(_button, text)

    def _on_speak_chapter_clicked(self, _button: Gtk.Button) -> None:
        payload = self._current_chapter_payload
        if not payload:
            self._toast(_("Nenhum capítulo carregado para ouvir."))
            return
        translation = str(payload.get("translation") or "")
        verses = payload.get("verses") or []
        sequence: list[str] = []
        for v in verses:
            verse_text = self._sanitize_tts_text(str(v.get("text") or ""))
            if verse_text:
                sequence.append(verse_text)
        if not sequence:
            self._toast(_("Nenhum capítulo carregado para ouvir."))
            return
        chapter_text = " ".join(sequence)
        # Agrupa em 3 versos por bloco para reduzir transições perceptíveis.
        grouped_sequence: list[str] = []
        chunk_size = 3
        for i in range(0, len(sequence), chunk_size):
            grouped_sequence.append(" ".join(sequence[i:i + chunk_size]).strip())

        self._tts_last_requested_text = chapter_text
        self._tts_last_requested_translation = translation
        self._stop_tts()
        if self._start_piper_tts_sequence(grouped_sequence, translation=translation):
            self.status_line.set_text(_("Preparando áudio (Piper)..."))
            self._toast(_("Preparando áudio..."))
        else:
            self._toast(_("Falha no áudio (Piper)."))

    def _build_verse_row(
        self,
        *,
        book_id: int,
        book_name: str,
        chapter: int,
        verse: int,
        text: str,
        translation: str,
        is_favorite: bool,
        study_note: dict | None = None,
    ) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("card")
        if study_note:
            row.add_css_class("study-annotated-row")

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_margin_top(8)
        outer.set_margin_bottom(8)
        outer.set_margin_start(12)
        outer.set_margin_end(12)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        num = Gtk.Label(label=str(verse), xalign=0)
        num.add_css_class("heading")
        num.add_css_class("accent")
        num.set_valign(Gtk.Align.START)
        top.append(num)

        ref = Gtk.Label(label=f"{book_name} {chapter}:{verse}", xalign=0)
        ref.add_css_class("dim-label")
        ref.set_hexpand(True)
        top.append(ref)

        if study_note:
            badges = []
            if study_note.get("highlight_color"):
                badges.append(str(study_note["highlight_color"]))
            if study_note.get("tags"):
                badges.append(f'{len(study_note.get("tags") or [])} {_("tag(s)")}')
            if study_note.get("note_text"):
                badges.append(_("nota"))
            note_badge = Gtk.Label(label=" · ".join(badges) or _("nota"), xalign=0)
            note_badge.add_css_class("accent")
            note_badge.add_css_class("caption")
            top.append(note_badge)

        fav_button = Gtk.Button(label=(_("Desfavoritar") if is_favorite else _("Favoritar")))
        fav_button.add_css_class("soft-button")
        fav_button.connect(
            "clicked",
            self._on_toggle_favorite_clicked,
            {
                "translation": translation,
                "book_id": book_id,
                "book_name": book_name,
                "chapter": chapter,
                "verse": verse,
                "text": text,
            },
        )
        top.append(fav_button)

        study_button = Gtk.Button(label=_("Estudar"))
        study_button.add_css_class("soft-button")
        study_button.connect(
            "clicked",
            self._on_open_study_for_reference_clicked,
            {
                "translation": translation,
                "book_id": book_id,
                "book_name": book_name,
                "chapter": chapter,
                "verse": verse,
                "text": text,
            },
        )
        top.append(study_button)

        copy_button = Gtk.Button(label=_("Copiar"))
        copy_button.add_css_class("soft-button")
        copy_button.connect(
            "clicked",
            self._on_copy_verse_clicked,
            f"{book_name} {chapter}:{verse} ({translation}) - {text}",
        )
        top.append(copy_button)

        speak_button = Gtk.Button(label=_("Ouvir"))
        speak_button.add_css_class("soft-button")
        speak_button.connect(
            "clicked",
            self._on_speak_text_clicked,
            f"{book_name} {chapter}:{verse}. {text}",
            translation,
        )
        top.append(speak_button)
        outer.append(top)

        body = Gtk.Label(label=text, wrap=True, xalign=0)
        body.set_selectable(True)
        body.add_css_class("verse-text")
        outer.append(body)

        if study_note and str(study_note.get("note_text") or "").strip():
            note_preview = Gtk.Label(
                label=f'{_("Nota")}: {str(study_note.get("note_text") or "")[:160]}',
                wrap=True,
                xalign=0,
            )
            note_preview.add_css_class("dim-label")
            note_preview.add_css_class("caption")
            outer.append(note_preview)

        row.set_child(outer)
        return row

    def _on_copy_verse_clicked(self, _button: Gtk.Button, text: str) -> None:
        display = self.get_display()
        if display is None:
            self.status_line.set_text(_("Sem display gráfico para acessar área de transferência."))
            return
        clipboard: Gdk.Clipboard = display.get_clipboard()
        clipboard.set_text(text)
        self.status_line.set_text(_("Versículo copiado para a área de transferência."))
        self._toast(_("Versículo copiado."))

    def _tts_lang_for_translation(self, translation: str | None = None) -> str:
        try:
            settings = self._backend.get_settings()
            forced = str(getattr(settings, "tts_voice_language", "auto") or "auto").lower()
            if forced and forced != "auto":
                return forced
        except Exception:
            pass
        code = translation or self._backend.db.translation
        try:
            meta = self._backend.db.get_translation_metadata(code)
        except Exception:
            meta = {}
        lang = str(meta.get("language") or "").strip().lower().replace("_", "-")
        code_upper = str(code or "").strip().upper()
        # Fallback por código de tradução (muitas bases não têm metadata de idioma confiável).
        if not lang:
            pt_codes = {
                "ARA", "ARC", "ACF", "NAA", "NVI", "NVT", "NTLH", "TB", "KJA", "JFAA", "AS21", "NBV",
            }
            es_codes = {"RVR", "RVA", "LBLA", "DHH", "NVIES"}
            if code_upper in pt_codes:
                return "pt-br"
            if code_upper in es_codes:
                return "es"
            if code_upper in {"KJV", "ASV", "AKJV", "WEB", "BBE"}:
                return "en"
        if not lang:
            # fallback forte para o público-alvo atual
            return "pt-br"
        if lang in {"pt", "pt-br", "pt_br"}:
            return "pt-br"
        if lang.startswith("en"):
            return "en"
        if lang.startswith("es"):
            return "es"
        if lang.startswith("fr"):
            return "fr"
        if lang.startswith("de"):
            return "de"
        if lang.startswith("it"):
            return "it"
        if lang.startswith("ru"):
            return "ru"
        if lang.startswith("uk"):
            return "uk"
        if lang.startswith("pl"):
            return "pl"
        if lang.startswith("cs"):
            return "cs"
        if lang.startswith("ro"):
            return "ro"
        if lang.startswith("nl"):
            return "nl"
        if lang.startswith("sv"):
            return "sv"
        if lang.startswith("tr"):
            return "tr"
        if lang.startswith("ja"):
            return "ja"
        if lang.startswith(("zh", "cmn")):
            return "zh"
        if lang.startswith("ko"):
            return "ko"
        if lang.startswith("he"):
            return "he"
        if lang.startswith("ar"):
            return "ar"
        if lang.startswith("hi"):
            return "hi"
        if lang.startswith("la"):
            return "la"
        return lang

    def _tts_has_manual_voice_override(self) -> bool:
        try:
            settings = self._backend.get_settings()
            forced = str(getattr(settings, "tts_voice_language", "auto") or "auto").strip().lower()
            return bool(forced and forced != "auto")
        except Exception:
            return False

    def _tts_engine_preference(self) -> str:
        # Produto simplificado: Piper é o único motor suportado na UI.
        return "piper"

    def _is_flatpak_runtime(self) -> bool:
        return bool(os.getenv("FLATPAK_ID"))

    def _tts_lang_aliases(self, lang: str, backend: str) -> list[str]:
        base = (lang or "pt-br").strip().lower()
        if backend == "speechd":
            alias_map = {
                "pt-br": ["pt-BR", "pt_BR", "pt", "pt-br"],
                "en": ["en-US", "en_GB", "en"],
                "es": ["es-ES", "es", "es-MX"],
                "fr": ["fr-FR", "fr"],
                "de": ["de-DE", "de"],
                "it": ["it-IT", "it"],
                "ru": ["ru-RU", "ru"],
                "uk": ["uk-UA", "uk"],
                "pl": ["pl-PL", "pl"],
                "cs": ["cs-CZ", "cs"],
                "ro": ["ro-RO", "ro"],
                "nl": ["nl-NL", "nl"],
                "sv": ["sv-SE", "sv"],
                "tr": ["tr-TR", "tr"],
                "ja": ["ja-JP", "ja"],
                "zh": ["zh-CN", "zh", "cmn"],
                "ko": ["ko-KR", "ko"],
                "he": ["he-IL", "he"],
                "ar": ["ar", "ar-SA"],
                "hi": ["hi-IN", "hi"],
                "la": ["la"],
            }
            return alias_map.get(base, [base])
        # espeak/espeak-ng costumam aceitar códigos em minúsculo.
        alias_map = {
            "pt-br": ["pt-br", "pt", "brazil"],
            "en": ["en-us", "en", "en-gb"],
            "es": ["es", "es-la", "es-mx"],
            "fr": ["fr", "fr-fr"],
            "de": ["de", "de-de"],
            "it": ["it", "it-it"],
            "ru": ["ru", "ru-ru"],
            "uk": ["uk", "uk-ua"],
            "pl": ["pl", "pl-pl"],
            "cs": ["cs", "cs-cz"],
            "ro": ["ro", "ro-ro"],
            "nl": ["nl", "nl-nl"],
            "sv": ["sv", "sv-se"],
            "tr": ["tr", "tr-tr"],
            "ja": ["ja", "ja-jp"],
            "zh": ["zh", "zh-yue", "cmn"],
            "ko": ["ko", "ko-kr"],
            "he": ["he", "iw"],
            "ar": ["ar", "ar-001"],
            "hi": ["hi", "hi-in"],
            "la": ["la"],
        }
        return alias_map.get(base, [base])

    def _tts_rhvoice_voice_aliases(self, lang: str) -> list[str]:
        base = (lang or "").strip().lower()
        if base.startswith("pt"):
            # Voz brasileira comum no RHVoice (pacote Arch disponível).
            return ["leticia-f123", "leticia"]
        if base.startswith("en"):
            return ["evgeniy-eng", "slt", "alan"]
        if base.startswith("es"):
            return ["mateo"]
        if base.startswith("ru"):
            return ["anna-rus", "elena-rus", "irina-rus"]
        if base.startswith("uk"):
            return ["anatol-ukr", "natalia-ukr"]
        if base.startswith("fr"):
            return ["bdl"]
        if base.startswith("de"):
            return ["klara"]
        return []

    def _tts_command_candidates(self, text: str, *, translation: str | None = None) -> list[tuple[str, list[str]]]:
        lang = self._tts_lang_for_translation(translation)
        strict_manual = self._tts_has_manual_voice_override()
        engine_pref = self._tts_engine_preference()
        commands: list[tuple[str, list[str]]] = []
        # RHVoice via speech-dispatcher costuma funcionar melhor em PT-BR quando instalado no sistema.
        # Em Flatpak (modo auto), preferimos motor interno para evitar dependência do host.
        if engine_pref in {"auto", "rhvoice"} and not (self._is_flatpak_runtime() and engine_pref == "auto"):
            for alias in self._tts_lang_aliases(lang, "speechd"):
                for voice in self._tts_rhvoice_voice_aliases(lang):
                    commands.append(("speechd-rhvoice", ["spd-say", "-o", "rhvoice", "-l", alias, "-y", voice, text]))
                commands.append(("speechd-rhvoice", ["spd-say", "-o", "rhvoice", "-l", alias, text]))
        # Se o usuário forçou idioma manualmente, evite fallback silencioso para inglês via speechd.
        if engine_pref != "auto":
            backend_order = [engine_pref]
        elif lang.startswith(("pt", "es", "fr", "de", "it", "ru", "uk", "pl", "cs", "ro", "nl", "sv", "tr", "ja", "zh", "ko", "he", "ar", "hi", "la")) or strict_manual:
            backend_order = ["espeak-ng", "espeak"] + ([] if strict_manual else ["speechd"])
        else:
            backend_order = ["speechd", "espeak-ng", "espeak"]
        for backend in backend_order:
            if backend in {"rhvoice", "piper"}:
                continue
            for alias in self._tts_lang_aliases(lang, backend):
                if backend == "speechd":
                    commands.append((backend, ["spd-say", "-l", alias, text]))
                elif backend == "espeak-ng":
                    commands.append((backend, ["espeak-ng", "-s", "155", "-g", "1", "-v", alias, text]))
                elif backend == "espeak":
                    commands.append((backend, ["espeak", "-s", "155", "-g", "1", "-v", alias, text]))
        return commands

    def _piper_voice_root(self) -> Path:
        xdg_data = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        root = xdg_data / APP_SLUG / "tts" / "piper"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _piper_voice_candidates(self, lang: str) -> list[dict[str, str]]:
        # Priorize modelos leves para reduzir latência e pico de CPU.
        # A lista é ordenada por preferência; tentamos em sequência.
        mapping: dict[str, list[tuple[str, str]]] = {
            "pt-br": [
                ("pt_BR-faber-low", "pt/pt_BR/faber/low"),
                ("pt_BR-faber-medium", "pt/pt_BR/faber/medium"),
            ],
            "en": [
                ("en_US-lessac-low", "en/en_US/lessac/low"),
                ("en_US-lessac-medium", "en/en_US/lessac/medium"),
            ],
            "es": [
                ("es_ES-sharvard-low", "es/es_ES/sharvard/low"),
                ("es_ES-sharvard-medium", "es/es_ES/sharvard/medium"),
            ],
            "fr": [
                ("fr_FR-siwis-low", "fr/fr_FR/siwis/low"),
                ("fr_FR-siwis-medium", "fr/fr_FR/siwis/medium"),
            ],
            "de": [
                ("de_DE-thorsten-low", "de/de_DE/thorsten/low"),
                ("de_DE-thorsten-medium", "de/de_DE/thorsten/medium"),
            ],
            "it": [
                ("it_IT-riccardo-x_low", "it/it_IT/riccardo/x_low"),
                ("it_IT-riccardo-low", "it/it_IT/riccardo/low"),
            ],
        }
        items = mapping.get(lang, [])
        out: list[dict[str, str]] = []
        for voice_name, rel in items:
            base = f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/{rel}/{voice_name}"
            out.append(
                {
                    "id": voice_name,
                    "onnx_url": f"{base}.onnx",
                    "json_url": f"{base}.onnx.json",
                }
            )
        return out

    def _ensure_piper_voice(self, lang: str) -> tuple[Path, Path] | None:
        voice_root = self._piper_voice_root()
        # 1) já existente local
        for onnx in voice_root.glob("*.onnx"):
            cfg = onnx.with_suffix(".onnx.json")
            if cfg.exists() and onnx.stem.startswith(lang.replace("-", "_")):
                return onnx, cfg
        candidates = self._piper_voice_candidates(lang)
        if not candidates:
            self._last_tts_error_text = f"Sem voz Piper mapeada para idioma: {lang}"
            return None
        for candidate in candidates:
            onnx_path = voice_root / f'{candidate["id"]}.onnx'
            json_path = voice_root / f'{candidate["id"]}.onnx.json'
            if onnx_path.exists() and json_path.exists():
                return onnx_path, json_path
            try:
                ok_model = self._download_file(candidate["onnx_url"], onnx_path)
                ok_json = self._download_file(candidate["json_url"], json_path)
                if not (ok_model and ok_json):
                    raise RuntimeError("download-failed")
                return onnx_path, json_path
            except Exception as exc:
                self._last_tts_error_text = (
                    f"Falha ao baixar voz Piper '{candidate['id']}': {exc}"
                )
                try:
                    onnx_path.unlink(missing_ok=True)
                    json_path.unlink(missing_ok=True)
                except Exception:
                    pass
                continue
        return None

    def _download_file(self, url: str, dst: Path) -> bool:
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(dst.suffix + ".part")
        # 1) urllib com User-Agent explícito
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"{APP_USER_AGENT} (Piper)"})
            with urllib.request.urlopen(req, timeout=90) as resp, tmp.open("wb") as fh:
                fh.write(resp.read())
            tmp.replace(dst)
            return True
        except Exception as exc:
            self._last_tts_error_text = f"urllib: {exc}"
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
        # 2) curl/wget local
        attempts: list[list[str]] = []
        if shutil.which("curl"):
            attempts.append(["curl", "-fL", "--retry", "2", "-o", str(tmp), url])
        if shutil.which("wget"):
            attempts.append(["wget", "-O", str(tmp), url])
        for cmd in attempts:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    cwd=str(Path.home()),
                )
                if result.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
                    tmp.replace(dst)
                    return True
                err = (result.stderr or result.stdout or "").strip()
                if err:
                    self._last_tts_error_text = f"{cmd[0]}: {err[:240]}"
            except Exception as exc:
                self._last_tts_error_text = f"{cmd[0]}: {exc}"
            finally:
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
        return False

    def _piper_binary(self) -> list[str] | None:
        if shutil.which("piper"):
            return ["piper"]
        # Flatpak com bundle padrão.
        app_piper = Path("/app/bin/piper")
        if app_piper.exists():
            return [str(app_piper)]
        return None

    def _cleanup_tts_media(self) -> None:
        media = self._tts_media
        if media is not None:
            try:
                media.pause()
            except Exception:
                pass
        self._tts_media = None
        if self._tts_media_tempfile:
            try:
                Path(self._tts_media_tempfile).unlink(missing_ok=True)
            except Exception:
                pass
        self._tts_media_tempfile = None

    def _piper_audio_cache_root(self) -> Path:
        root = self._piper_voice_root() / "cache"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _piper_cached_wav_path(self, *, model_path: Path, lang: str, text: str) -> Path:
        digest = hashlib.sha256(
            f"{model_path.name}|{lang}|{text}".encode("utf-8", errors="ignore")
        ).hexdigest()
        return self._piper_audio_cache_root() / f"{digest}.wav"

    def _synthesize_piper_to_cache(
        self,
        *,
        piper_cmd: list[str],
        model_path: Path,
        config_path: Path,
        lang: str,
        text: str,
    ) -> tuple[bool, Path, str]:
        cache_path = self._piper_cached_wav_path(model_path=model_path, lang=lang, text=text)
        if cache_path.exists():
            return True, cache_path, ""
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, wav_tmp = tempfile.mkstemp(
            prefix=f"{APP_SLUG}-tts-",
            suffix=".wav",
            dir=str(cache_path.parent),
        )
        os.close(fd)
        cmd = [
            *piper_cmd,
            "--model", str(model_path),
            "--config", str(config_path),
            "--output_file", wav_tmp,
            "--length_scale", "1.14",
            "--sentence_silence", "0.00",
        ]
        env = os.environ.copy()
        env.setdefault("OMP_NUM_THREADS", "2")
        env.setdefault("OMP_WAIT_POLICY", "PASSIVE")
        env.setdefault("OPENBLAS_NUM_THREADS", "1")
        proc = subprocess.run(
            cmd,
            input=text,
            text=True,
            capture_output=True,
            cwd=str(Path.home()),
            env=env,
        )
        if proc.returncode != 0:
            try:
                Path(wav_tmp).unlink(missing_ok=True)
            except Exception:
                pass
            err = (proc.stderr or proc.stdout or "").strip()
            return False, cache_path, f"Piper retornou erro ({proc.returncode}): {err[:300]}"
        try:
            Path(wav_tmp).replace(cache_path)
        except OSError:
            shutil.move(wav_tmp, str(cache_path))
        return True, cache_path, ""

    def _split_tts_chunks(self, text: str, max_chars: int = 420) -> list[str]:
        raw = (text or "").strip()
        if not raw:
            return []
        # Quebra por sentenças para reduzir latência inicial do Piper.
        parts = re.split(r"(?<=[\.\!\?\:\;])\s+", raw)
        chunks: list[str] = []
        cur = ""
        for part in parts:
            p = part.strip()
            if not p:
                continue
            if len(p) > max_chars:
                if cur:
                    chunks.append(cur.strip())
                    cur = ""
                for i in range(0, len(p), max_chars):
                    chunks.append(p[i:i + max_chars].strip())
                continue
            candidate = f"{cur} {p}".strip() if cur else p
            if len(candidate) > max_chars and cur:
                chunks.append(cur.strip())
                cur = p
            else:
                cur = candidate
        if cur:
            chunks.append(cur.strip())
        return chunks

    def _media_is_playing(self) -> bool:
        media = self._tts_media
        if media is None:
            return False
        try:
            return bool(media.get_playing())
        except Exception:
            return False

    def _start_piper_tts(self, text: str, *, translation: str | None = None) -> bool:
        return self._start_piper_tts_sequence([text], translation=translation)

    def _start_piper_tts_sequence(self, items: list[str], *, translation: str | None = None) -> bool:
        chunks: list[str] = []
        for item in items:
            chunks.extend(self._split_tts_chunks(item))
        if not chunks:
            self._last_tts_error_text = "Texto vazio para TTS."
            return False
        self._tts_chunk_queue = [(chunk, translation) for chunk in chunks]
        self._tts_chunk_total = len(self._tts_chunk_queue)
        self._prefetch_upcoming_piper_chunks(limit=2)
        return self._start_next_piper_chunk()

    def _start_next_piper_chunk(self) -> bool:
        if not self._tts_chunk_queue:
            return False
        text, translation = self._tts_chunk_queue.pop(0)
        piper_cmd = self._piper_binary()
        if not piper_cmd:
            self._last_tts_error_text = "Binário 'piper' não encontrado."
            return False
        lang = self._tts_lang_for_translation(translation)
        self._cleanup_tts_media()
        self._tts_job_id += 1
        job_id = self._tts_job_id
        self._tts_backend = "piper-pending"
        self._tts_process = None
        self._tts_paused = False
        self._sync_tts_buttons()
        idx = (self._tts_chunk_total - len(self._tts_chunk_queue))
        self.status_line.set_text(
            _("Preparando áudio (Piper)...") + f" {idx}/{max(1, self._tts_chunk_total)}"
        )

        def worker() -> None:
            try:
                voice_files = self._ensure_piper_voice(lang)
                if not voice_files:
                    GLib.idle_add(self._on_piper_tts_failed, job_id, self._last_tts_error_text or "")
                    return
                model_path, config_path = voice_files
                ok, cache_path, err = self._synthesize_piper_to_cache(
                    piper_cmd=piper_cmd,
                    model_path=model_path,
                    config_path=config_path,
                    lang=lang,
                    text=text,
                )
                if not ok:
                    self._last_tts_error_text = err
                    GLib.idle_add(self._on_piper_tts_failed, job_id, self._last_tts_error_text)
                    return
                GLib.idle_add(self._on_piper_tts_ready, job_id, str(cache_path))
            except Exception as exc:
                self._last_tts_error_text = f"Falha no Piper: {exc}"
                GLib.idle_add(self._on_piper_tts_failed, job_id, self._last_tts_error_text)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _on_piper_tts_ready(self, job_id: int, wav_path: str) -> bool:
        if job_id != self._tts_job_id:
            return False
        try:
            media = Gtk.MediaFile.new_for_file(Gio.File.new_for_path(wav_path))
            try:
                media.set_loop(False)
            except Exception:
                pass
            try:
                media.set_muted(False)
                media.set_volume(1.0)
            except Exception:
                pass
            self._tts_media = media
            self._tts_media_tempfile = None
            try:
                media.connect("notify::playing", self._on_tts_media_playing_changed)
            except Exception:
                pass
            media.play()
            # Fallback: em alguns ambientes o Gtk.MediaFile "toca" sem áudio real.
            GLib.timeout_add(450, self._ensure_piper_playback_started, job_id, wav_path)
            self._tts_backend = "piper"
            self._tts_process = None
            self._tts_paused = False
            self._sync_tts_buttons()
            self._prefetch_upcoming_piper_chunks(limit=2)
            chunk_idx = self._tts_chunk_total - len(self._tts_chunk_queue)
            if chunk_idx <= 1:
                self.status_line.set_text(_("Leitura em voz iniciada."))
                self._toast(_("Leitura em voz iniciada."))
            else:
                self.status_line.set_text(
                    _("Leitura em voz iniciada.") + f" {chunk_idx}/{max(1, self._tts_chunk_total)}"
                )
        except Exception as exc:
            self._last_tts_error_text = f"Falha ao reproduzir áudio Piper: {exc}"
            self._on_piper_tts_failed(job_id, self._last_tts_error_text)
        return False

    def _on_piper_tts_failed(self, job_id: int, message: str) -> bool:
        if job_id != self._tts_job_id:
            return False
        self._tts_backend = None
        self._tts_process = None
        self._tts_paused = False
        self._sync_tts_buttons()
        msg = (message or "").strip()
        self.status_line.set_text(_("Falha ao preparar áudio (Piper)."))
        if msg:
            self._toast(_("Falha no áudio (Piper)."))
            self.status_line.set_text(f'{_("Falha no áudio (Piper).")} {msg[:120]}')
            print("Piper TTS error:", msg)
        return False

    def _prefetch_upcoming_piper_chunks(self, limit: int = 2) -> None:
        if not self._tts_chunk_queue:
            return
        upcoming = self._tts_chunk_queue[: max(0, int(limit))]
        for text, translation in upcoming:
            lang = self._tts_lang_for_translation(translation)
            key = hashlib.sha256(f"{lang}|{text}".encode("utf-8", errors="ignore")).hexdigest()
            if key in self._tts_prefetch_inflight:
                continue
            self._tts_prefetch_inflight.add(key)

            def worker(text=text, lang=lang, key=key) -> None:
                try:
                    piper_cmd = self._piper_binary()
                    if not piper_cmd:
                        return
                    voice_files = self._ensure_piper_voice(lang)
                    if not voice_files:
                        return
                    model_path, config_path = voice_files
                    self._synthesize_piper_to_cache(
                        piper_cmd=piper_cmd,
                        model_path=model_path,
                        config_path=config_path,
                        lang=lang,
                        text=text,
                    )
                finally:
                    self._tts_prefetch_inflight.discard(key)

            threading.Thread(target=worker, daemon=True).start()

    def _ensure_piper_playback_started(self, job_id: int, wav_path: str) -> bool:
        if job_id != self._tts_job_id:
            return False
        media = self._tts_media
        is_playing = False
        if media is not None:
            try:
                is_playing = bool(media.get_playing())
            except Exception:
                is_playing = False
        if is_playing:
            return False
        self._last_tts_error_text = "Falha de reprodução: Gtk.MediaFile não iniciou playback do WAV."
        self._on_piper_tts_failed(job_id, self._last_tts_error_text)
        return False

    def _on_tts_media_playing_changed(self, _media, _pspec) -> None:
        # Atualiza botões quando a mídia terminar.
        if (
            self._tts_backend == "piper"
            and not self._tts_paused
            and not self._media_is_playing()
            and self._tts_chunk_queue
        ):
            self._start_next_piper_chunk()
        GLib.idle_add(self._sync_tts_buttons)

    def _spawn_host_or_local_command(self, cmd: list[str], *, allow_host: bool = True) -> subprocess.Popen | None:
        if not cmd:
            return None
        exe = cmd[0]
        attempts: list[list[str]] = []
        if shutil.which(exe):
            attempts.append(cmd)
        for attempt in attempts:
            try:
                proc = subprocess.Popen(
                    attempt,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(Path.home()),
                )
                return proc
            except Exception:
                continue
        return None

    def _kill_tts_backends_best_effort(self) -> None:
        # speech-dispatcher pode ser daemon de sessão; tente parar fala antes de matar.
        self._run_host_or_local_command(["spd-say", "--stop"])
        self._run_host_or_local_command(["spd-say", "--cancel"])
        for exe in ("espeak-ng", "espeak"):
            self._run_host_or_local_command(["pkill", "-x", exe])

    def _start_tts(self, text: str, *, translation: str | None = None) -> bool:
        self._stop_tts()
        ok = self._start_piper_tts(text, translation=translation)
        if not ok:
            self._tts_backend = None
            self._sync_tts_buttons()
        return ok

    def _start_command_tts(self, text: str, *, translation: str | None = None) -> bool:
        for backend, cmd in self._tts_command_candidates(
            text,
            translation=translation,
        ):
            proc = self._spawn_host_or_local_command(
                cmd,
                allow_host=backend.startswith("speechd") or backend in {"espeak-ng", "espeak"},
            )
            if proc is None:
                continue
            self._tts_process = proc
            self._tts_backend = backend
            self._tts_paused = False
            self._sync_tts_buttons()
            self.status_line.set_text(_("Leitura em voz iniciada."))
            self._toast(_("Leitura em voz iniciada."))
            return True
        return False

    def _sync_tts_buttons(self) -> None:
        proc_active = self._tts_process is not None and self._tts_process.poll() is None
        media_active = self._media_is_playing()
        pending = self._tts_backend == "piper-pending"
        paused_media = self._tts_backend == "piper" and self._tts_paused
        active = proc_active or media_active or pending or paused_media
        if hasattr(self, "pause_tts_button"):
            self.pause_tts_button.set_sensitive((active and not pending) or paused_media)
            self.pause_tts_button.set_label(_("Continuar áudio") if self._tts_paused else _("Pausar áudio"))
        if hasattr(self, "stop_tts_button"):
            self.stop_tts_button.set_sensitive(active)

    def _stop_tts(self) -> None:
        proc = self._tts_process
        if self._tts_backend in {"piper", "piper-pending"}:
            self._tts_job_id += 1
            self._tts_chunk_queue = []
            self._tts_chunk_total = 0
            self._tts_prefetch_inflight.clear()
            self._cleanup_tts_media()
            self._tts_process = None
            self._tts_paused = False
            self._tts_backend = None
            self._sync_tts_buttons()
            return
        if proc is None:
            self._tts_paused = False
            self._tts_backend = None
            self._cleanup_tts_media()
            self._kill_tts_backends_best_effort()
            self._sync_tts_buttons()
            return
        try:
            if proc.poll() is None:
                proc.terminate()
        except Exception:
            pass
        self._tts_process = None
        self._tts_paused = False
        self._tts_backend = None
        self._cleanup_tts_media()
        self._kill_tts_backends_best_effort()
        self._sync_tts_buttons()

    def _on_pause_resume_tts_clicked(self, _button: Gtk.Button) -> None:
        if self._tts_backend == "piper" and self._tts_media is not None:
            try:
                if self._tts_paused:
                    self._tts_paused = False
                    self._tts_media.play()
                else:
                    # Marque a pausa antes de chamar pause(); o Gtk pode emitir
                    # notify::playing imediatamente e isso não deve avançar o próximo chunk.
                    self._tts_paused = True
                    self._tts_media.pause()
                self._sync_tts_buttons()
                self._toast(_("Áudio retomado.") if not self._tts_paused else _("Áudio pausado."))
                return
            except Exception:
                self._toast(_("Não foi possível pausar/continuar este sintetizador."))
                return
        proc = self._tts_process
        if proc is None or proc.poll() is not None:
            self._tts_process = None
            self._tts_paused = False
            self._tts_backend = None
            self._sync_tts_buttons()
            self._toast(_("Nenhum áudio em reprodução."))
            return
        try:
            proc.send_signal(signal.SIGCONT if self._tts_paused else signal.SIGSTOP)
            self._tts_paused = not self._tts_paused
            self._sync_tts_buttons()
            self._toast(_("Áudio retomado.") if not self._tts_paused else _("Áudio pausado."))
        except Exception:
            self._toast(_("Não foi possível pausar/continuar este sintetizador."))

    def _on_stop_tts_clicked(self, _button: Gtk.Button) -> None:
        had_active = (
            (self._tts_process is not None and self._tts_process.poll() is None)
            or self._media_is_playing()
            or self._tts_backend == "piper-pending"
        )
        self._stop_tts()
        self._toast(_("Áudio interrompido.") if had_active else _("Nenhum áudio em reprodução."))

    def _on_close_request(self, *_args) -> bool:
        self._stop_tts()
        return False

    def _on_speak_text_clicked(self, _button: Gtk.Button, text: str, translation: str | None = None) -> None:
        speak_text = self._sanitize_tts_text(text)
        self._tts_last_requested_text = speak_text
        self._tts_last_requested_translation = translation
        self._last_tts_error_text = ""
        if self._start_tts(speak_text, translation=translation):
            if self._tts_backend == "piper-pending":
                self.status_line.set_text(_("Preparando áudio (Piper)..."))
                self._toast(_("Preparando áudio..."))
            else:
                self.status_line.set_text(_("Leitura em voz iniciada."))
                self._toast(_("Leitura em voz iniciada."))
            return

        error = self._last_tts_error_text.strip()
        if error:
            if self._tts_has_manual_voice_override():
                self._toast(_("{0} (idioma selecionado: {1}).").format(error, translation or _("auto")))
            else:
                self._toast(error)
            return

        if self._tts_has_manual_voice_override():
            self._toast(_("Não foi possível iniciar a voz no idioma selecionado."))
        else:
            self._toast(_("Não foi possível executar o áudio."))

    def _on_toggle_favorite_clicked(self, _button: Gtk.Button, data: dict) -> None:
        added = self._backend.toggle_favorite(
            translation=str(data["translation"]),
            book=str(data["book_name"]),
            chapter=int(data["chapter"]),
            verse=int(data["verse"]),
            text=str(data["text"]),
            book_id=int(data["book_id"]),
        )
        self.status_line.set_text(
            _("Versículo adicionado aos favoritos.") if added else _("Versículo removido dos favoritos.")
        )
        self._toast(
            _("Favorito salvo.") if added else _("Favorito removido.")
        )
        if self._current_chapter_payload is not None:
            self._render_reader_verses(self._current_chapter_payload)
        if self.search_entry.get_text().strip():
            self._run_search(self.search_entry.get_text().strip())
        self._refresh_favorites()

    def _on_search_button_clicked(self, _button: Gtk.Button) -> None:
        self._on_search_activated(None)

    def _clear_search_entries(self) -> None:
        if self._search_entry_syncing:
            return
        self._search_entry_syncing = True
        try:
            self.search_entry.set_text("")
            self.quick_search.set_text("")
        finally:
            self._search_entry_syncing = False

    def _exit_search_mode(self) -> None:
        self.search_info.set_text(_("Digite uma palavra ou frase para pesquisar."))
        self._clear_list(self.search_results_list)
        self._clear_search_entries()
        if self.stack is not None and self.stack.get_visible_child_name() == "search":
            self.stack.set_visible_child_name("reader")
            if self._current_chapter_payload is not None:
                self._render_reader_verses(self._current_chapter_payload)

    def _on_search_activated(self, _entry) -> None:
        visible = self.stack.get_visible_child_name() if self.stack is not None else "reader"
        if isinstance(_entry, Gtk.SearchEntry):
            query = _entry.get_text().strip()
        elif visible == "search":
            query = self.search_entry.get_text().strip()
        else:
            query = self.quick_search.get_text().strip()
        if not query:
            self._exit_search_mode()
            return
        self.search_entry.set_text(query)
        self.quick_search.set_text(query)
        self._run_search(query)
        self.stack.set_visible_child_name("search")

    def _on_search_query_changed(self, entry: Gtk.SearchEntry) -> None:
        if not entry.get_text().strip() and not self._search_entry_syncing:
            self._exit_search_mode()

    def _run_search(self, query: str) -> None:
        limit = int(self.search_limit_spin.get_value())
        results = self._backend.search(query, limit=limit)
        self.search_info.set_text(
            f"{len(results)} {(_('resultado(s)'))} {(_('para'))} '{query}' {(_('na tradução'))} {self._backend.db.translation}."
        )
        self._clear_list(self.search_results_list)

        if not results:
            self._set_status_row(self.search_results_list, _("Nenhum resultado encontrado."))
            return
        for item in results:
            self.search_results_list.append(self._build_search_result_row(item, query))

    def _build_search_result_row(self, item: dict, query: str) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("card")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ref = Gtk.Label(
            label=f'{item["book_name"]} {item["chapter"]}:{item["verse"]} ({item["translation"]})',
            xalign=0,
        )
        ref.add_css_class("heading")
        ref.set_hexpand(True)
        top.append(ref)

        open_button = Gtk.Button(label=_("Abrir"))
        open_button.add_css_class("soft-button")
        open_button.connect("clicked", self._on_open_reference_clicked, item)
        top.append(open_button)

        fav_button = Gtk.Button(label=(_("Desfavoritar") if item["is_favorite"] else _("Favoritar")))
        fav_button.add_css_class("soft-button")
        fav_button.connect(
            "clicked",
            self._on_toggle_favorite_clicked,
            {
                "translation": item["translation"],
                "book_id": int(item["book_id"]),
                "book_name": item["book_name"],
                "chapter": int(item["chapter"]),
                "verse": int(item["verse"]),
                "text": item["text"],
            },
        )
        top.append(fav_button)
        box.append(top)

        snippet = self._highlight_query_text(str(item["text"]), query)
        text = Gtk.Label(wrap=True, xalign=0)
        text.set_use_markup(True)
        text.set_markup(snippet)
        text.set_selectable(True)
        text.add_css_class("search-text")
        box.append(text)

        row.set_child(box)
        return row

    def _highlight_query_text(self, text: str, query: str) -> str:
        escaped_text = escape(text)
        if not query:
            return escaped_text
        start = text.casefold().find(query.casefold())
        if start < 0:
            return escaped_text
        end = start + len(query)
        return (
            f"{escape(text[:start])}<span background='yellow' foreground='black'>"
            f"{escape(text[start:end])}</span>{escape(text[end:])}"
        )

    def _on_open_reference_clicked(self, _button: Gtk.Button, item: dict) -> None:
        translation = str(item["translation"])
        if translation != self._backend.db.translation:
            self._backend.set_translation(translation)
            self.translation_switcher.select_translation(translation)

        book_id = int(item.get("book_id") or 0)
        if book_id <= 0:
            found = self._backend.db.find_book(str(item["book_name"]))
            if found:
                book_id = int(found["id"])
        self._highlight_verse = int(item.get("verse") or 0)
        self._refresh_books(preferred_book_id=book_id, preferred_chapter=int(item["chapter"]))
        self.stack.set_visible_child_name("reader")
        self.status_line.set_text(
            f'{_("Aberto em leitura")}: {item["book_name"]} {item["chapter"]}:{item["verse"]}'
        )
        self._toast(
            f'{_("Abrindo")} {item["book_name"]} {item["chapter"]}:{item["verse"]}.'
        )

    def _mark_row_highlight(self, target: Gtk.ListBoxRow) -> None:
        for row in self._reader_rows_by_verse.values():
            row.remove_css_class("verse-row-highlight")
        target.add_css_class("verse-row-highlight")
        target.grab_focus()

    def _ensure_default_notebook(self) -> None:
        notebooks = self._backend.list_notebooks()
        if not notebooks:
            self._backend.create_notebook(name=_("Padrão"), description=_("Anotações rápidas"))

    def _refresh_study_notebooks(self) -> None:
        self._ensure_default_notebook()
        notebooks = self._backend.list_notebooks()
        self._study_notebook_items = notebooks
        labels = [f'{n["name"]} ({int(n.get("entry_count") or 0)})' for n in notebooks] or [_("Padrão")]
        self.study_notebook_dropdown.set_model(Gtk.StringList.new(labels))
        self.study_notebook_dropdown.set_selected(0)
        self._refresh_study_notebook_entries()

    def _refresh_study_notebook_entries(self) -> None:
        if not hasattr(self, "study_notebook_entries_list"):
            return
        self._clear_list(self.study_notebook_entries_list)
        notebooks = getattr(self, "_study_notebook_items", [])
        idx = int(self.study_notebook_dropdown.get_selected()) if hasattr(self, "study_notebook_dropdown") else -1
        if idx < 0 or idx >= len(notebooks):
            self._set_status_row(self.study_notebook_entries_list, _("Selecione um caderno para ver entradas."))
            return
        notebook = notebooks[idx]
        entries = self._backend.list_notebook_entries(notebook_id=int(notebook["id"]), limit=100)
        if not entries:
            self._set_status_row(self.study_notebook_entries_list, _("Este caderno ainda não possui entradas."))
            return
        for item in entries:
            row = Gtk.ListBoxRow()
            row.add_css_class("card")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            ref = Gtk.Label(
                label=f'{item["book"]} {item["chapter"]}:{item["verse"]} ({item["translation"]})',
                xalign=0,
            )
            ref.add_css_class("heading")
            ref.set_hexpand(True)
            top.append(ref)
            open_btn = Gtk.Button(label=_("Abrir"))
            open_btn.add_css_class("soft-button")
            open_btn.connect(
                "clicked",
                self._on_open_reference_clicked,
                {
                    "translation": item["translation"],
                    "book_id": int(item.get("book_id") or 0),
                    "book_name": item["book"],
                    "chapter": int(item["chapter"]),
                    "verse": int(item["verse"]),
                    "text": "",
                },
            )
            top.append(open_btn)
            remove_btn = Gtk.Button(label=_("Remover"))
            remove_btn.add_css_class("soft-button")
            remove_btn.connect("clicked", self._on_study_remove_notebook_entry_clicked, int(item["id"]))
            top.append(remove_btn)
            box.append(top)
            if str(item.get("note_text") or "").strip():
                txt = Gtk.Label(label=str(item["note_text"]), xalign=0, wrap=True)
                txt.add_css_class("dim-label")
                box.append(txt)
            row.set_child(box)
            self.study_notebook_entries_list.append(row)

    def _refresh_study_recent_notes(self) -> None:
        if not hasattr(self, "study_recent_notes_list"):
            return
        self._clear_list(self.study_recent_notes_list)
        tag_filter = self.study_notes_filter_entry.get_text().strip() if hasattr(self, "study_notes_filter_entry") else ""
        items = self._backend.list_study_notes(tag=tag_filter or None, limit=80)
        if not items:
            self._set_status_row(
                self.study_recent_notes_list,
                _("Nenhuma nota encontrada.") if not tag_filter else _("Nenhuma nota encontrada para esta tag."),
            )
            return
        for item in items:
            row = Gtk.ListBoxRow()
            row.add_css_class("card")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            ref = Gtk.Label(
                label=f'{item["book"]} {item["chapter"]}:{item["verse"]} ({item["translation"]})',
                xalign=0,
            )
            ref.set_hexpand(True)
            ref.add_css_class("heading")
            top.append(ref)
            open_btn = Gtk.Button(label=_("Abrir"))
            open_btn.add_css_class("soft-button")
            open_btn.connect(
                "clicked",
                self._on_open_reference_clicked,
                {
                    "translation": item["translation"],
                    "book_id": int(item.get("book_id") or 0),
                    "book_name": item["book"],
                    "chapter": int(item["chapter"]),
                    "verse": int(item["verse"]),
                    "text": "",
                },
            )
            top.append(open_btn)
            study_btn = Gtk.Button(label=_("Estudar"))
            study_btn.add_css_class("soft-button")
            study_btn.connect(
                "clicked",
                self._on_open_study_for_reference_clicked,
                {
                    "translation": item["translation"],
                    "book_id": int(item.get("book_id") or 0),
                    "book_name": item["book"],
                    "chapter": int(item["chapter"]),
                    "verse": int(item["verse"]),
                    "text": "",
                },
            )
            top.append(study_btn)
            box.append(top)
            if item.get("tags"):
                tags = Gtk.Label(label=", ".join(item.get("tags") or []), xalign=0)
                tags.add_css_class("caption")
                tags.add_css_class("accent")
                box.append(tags)
            txt = Gtk.Label(label=str(item.get("note_text") or ""), xalign=0, wrap=True)
            txt.add_css_class("dim-label")
            box.append(txt)
            row.set_child(box)
            self.study_recent_notes_list.append(row)

    def _refresh_study_recent_entries(self) -> None:
        if not hasattr(self, "study_recent_entries_list"):
            return
        self._clear_list(self.study_recent_entries_list)
        items = self._backend.list_recent_notebook_entries(limit=60)
        if not items:
            self._set_status_row(self.study_recent_entries_list, _("Nenhuma entrada recente em cadernos."))
            return
        for item in items:
            row = Gtk.ListBoxRow()
            row.add_css_class("card")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            left = Gtk.Label(
                label=f'{item.get("notebook_name", _("Caderno"))} · {item["book"]} {item["chapter"]}:{item["verse"]}',
                xalign=0,
            )
            left.add_css_class("heading")
            left.set_hexpand(True)
            head.append(left)
            open_btn = Gtk.Button(label=_("Abrir"))
            open_btn.add_css_class("soft-button")
            open_btn.connect(
                "clicked",
                self._on_open_reference_clicked,
                {
                    "translation": item["translation"],
                    "book_id": int(item.get("book_id") or 0),
                    "book_name": item["book"],
                    "chapter": int(item["chapter"]),
                    "verse": int(item["verse"]),
                    "text": "",
                },
            )
            head.append(open_btn)
            box.append(head)
            if str(item.get("note_text") or "").strip():
                txt = Gtk.Label(label=str(item["note_text"]), xalign=0, wrap=True)
                txt.add_css_class("dim-label")
                box.append(txt)
            row.set_child(box)
            self.study_recent_entries_list.append(row)

    def _refresh_study_plans(self) -> None:
        self._clear_list(self.study_plans_list)
        for plan in self._backend.list_reading_plans():
            progress_set = set(self._backend.list_plan_progress(plan_slug=str(plan["slug"])))
            total_days = int(plan.get("total_days") or len(plan.get("days") or []))
            next_day = next((idx for idx in range(1, total_days + 1) if idx not in progress_set), None)
            row = Gtk.ListBoxRow()
            row.add_css_class("card")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = Gtk.Label(label=str(plan["title"]), xalign=0)
            title.add_css_class("heading")
            title.set_hexpand(True)
            top.append(title)
            progress = Gtk.Label(
                label=f'{int(plan.get("completed_days") or 0)}/{total_days}',
                xalign=1,
            )
            progress.add_css_class("monospace")
            top.append(progress)
            box.append(top)
            subtitle = Gtk.Label(label=str(plan.get("description") or ""), xalign=0, wrap=True)
            subtitle.add_css_class("dim-label")
            box.append(subtitle)
            if next_day is not None:
                refs = list(plan.get("days") or [])
                next_refs = refs[next_day - 1] if 1 <= next_day <= len(refs) else []
                preview = ", ".join(str(r) for r in (next_refs or [])[:2])
                if next_refs and len(next_refs) > 2:
                    preview += " ..."
                next_label = Gtk.Label(
                    label=f'{_("Próximo dia")} {next_day}: {preview or _("sem referência")}',
                    xalign=0,
                    wrap=True,
                )
                next_label.add_css_class("accent")
                next_label.add_css_class("caption")
                box.append(next_label)
            else:
                done_label = Gtk.Label(label=_("Plano concluído."), xalign=0)
                done_label.add_css_class("accent")
                done_label.add_css_class("caption")
                box.append(done_label)
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            btn_details = Gtk.Button(label=_("Ver dias"))
            btn_details.add_css_class("soft-button")
            btn_details.connect("clicked", self._on_study_open_plan_days_clicked, plan)
            actions.append(btn_details)
            btn_open_next = Gtk.Button(label=_("Abrir próximo dia"))
            btn_open_next.add_css_class("soft-button")
            btn_open_next.set_sensitive(next_day is not None)
            btn_open_next.connect("clicked", self._on_study_open_next_plan_day_clicked, plan)
            actions.append(btn_open_next)
            btn_mark = Gtk.Button(label=_("Concluir próximo dia"))
            btn_mark.add_css_class("soft-button")
            btn_mark.set_sensitive(next_day is not None)
            btn_mark.connect("clicked", self._on_study_complete_next_plan_day_clicked, plan)
            actions.append(btn_mark)
            btn_undo = Gtk.Button(label=_("Desfazer último dia"))
            btn_undo.add_css_class("soft-button")
            btn_undo.set_sensitive(bool(progress_set))
            btn_undo.connect("clicked", self._on_study_undo_plan_day_clicked, plan)
            actions.append(btn_undo)
            box.append(actions)
            row.set_child(box)
            self.study_plans_list.append(row)
        if self.study_plans_list.get_row_at_index(0) is None:
            self._set_status_row(self.study_plans_list, _("Nenhum plano disponível."))

    def _get_text_view_text(self, view: Gtk.TextView) -> str:
        buffer = view.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)

    def _set_text_view_text(self, view: Gtk.TextView, text: str) -> None:
        view.get_buffer().set_text(text or "")

    def _get_selected_study_ref(self) -> dict | None:
        return self._selected_study_ref

    def _select_study_reference(self, ref: dict) -> None:
        self._selected_study_ref = {
            "translation": str(ref["translation"]),
            "book_id": int(ref["book_id"]),
            "book_name": str(ref["book_name"]),
            "chapter": int(ref["chapter"]),
            "verse": int(ref["verse"]),
            "text": str(ref.get("text") or ""),
        }
        r = self._selected_study_ref
        self.study_context_label.set_text(
            f'{_("Estudando")}: {r["book_name"]} {r["chapter"]}:{r["verse"]} ({r["translation"]})'
        )
        self._load_study_note_for_selected_ref()
        self._refresh_study_compare()
        self._refresh_study_cross_refs()

    def _load_study_note_for_selected_ref(self) -> None:
        ref = self._get_selected_study_ref()
        if not ref:
            self._set_text_view_text(self.study_note_view, "")
            self.study_tags_entry.set_text("")
            self.study_highlight_dropdown.set_selected(0)
            return
        note = self._backend.get_study_note(
            translation=ref["translation"],
            book=ref["book_name"],
            chapter=ref["chapter"],
            verse=ref["verse"],
        )
        if not note:
            self._set_text_view_text(self.study_note_view, "")
            self.study_tags_entry.set_text("")
            self.study_highlight_dropdown.set_selected(0)
            return
        self._set_text_view_text(self.study_note_view, str(note.get("note_text") or ""))
        self.study_tags_entry.set_text(", ".join(note.get("tags") or []))
        color = str(note.get("highlight_color") or "")
        try:
            self.study_highlight_dropdown.set_selected(self.study_highlight_codes.index(color))
        except ValueError:
            self.study_highlight_dropdown.set_selected(0)

    def _refresh_study_compare(self) -> None:
        if not hasattr(self, "study_compare_list"):
            return
        self._clear_list(self.study_compare_list)
        ref = self._get_selected_study_ref()
        if not ref:
            self._set_status_row(self.study_compare_list, _("Selecione um versículo para comparar traduções."))
            return
        if not getattr(self, "study_compare_codes", None):
            self._set_status_row(self.study_compare_list, _("Nenhuma tradução disponível para comparação."))
            return
        left_idx = int(self.study_compare_left.get_selected())
        right_idx = int(self.study_compare_right.get_selected())
        codes: list[str] = []
        for idx in [left_idx, right_idx]:
            if 0 <= idx < len(self.study_compare_codes):
                code = self.study_compare_codes[idx]
                if code not in codes:
                    codes.append(code)
        if not codes:
            self._set_status_row(self.study_compare_list, _("Selecione traduções para comparar."))
            return
        rows = self._backend.compare_verse(
            book_id=ref["book_id"],
            chapter=ref["chapter"],
            verse=ref["verse"],
            translations=codes,
        )
        if not rows:
            self._set_status_row(self.study_compare_list, _("Versículo indisponível nas traduções selecionadas."))
            return
        for item in rows:
            row = Gtk.ListBoxRow()
            row.add_css_class("card")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)
            title = Gtk.Label(label=f'{item["translation"]} | {item["book_name"]} {item["chapter"]}:{item["verse"]}', xalign=0)
            title.add_css_class("heading")
            box.append(title)
            text = Gtk.Label(label=str(item.get("text") or ""), wrap=True, xalign=0)
            text.set_selectable(True)
            text.add_css_class("search-text")
            box.append(text)
            row.set_child(box)
            self.study_compare_list.append(row)

    def _refresh_study_cross_refs(self) -> None:
        self._clear_list(self.study_refs_list)
        ref = self._get_selected_study_ref()
        if not ref:
            self._set_status_row(self.study_refs_list, _("Selecione um versículo para ver referências cruzadas."))
            return
        refs = self._backend.list_cross_references(
            book_id=ref["book_id"], chapter=ref["chapter"], verse=ref["verse"], limit=20
        )
        if not refs:
            total_refs = self._backend.count_cross_references()
            if total_refs <= 0:
                self._set_status_row(
                    self.study_refs_list,
                    _("Nenhuma referência cruzada importada ainda. Use o botão “Importar”."),
                )
            else:
                self._set_status_row(self.study_refs_list, _("Nenhuma referência cruzada cadastrada para este versículo."))
            return
        for item in refs:
            row = Gtk.ListBoxRow()
            row.add_css_class("card")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)
            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            ref_text = f'{item.get("target_book_name", _("Livro"))} {item["target_chapter"]}:{item["target_verse"]}'
            label = Gtk.Label(label=ref_text, xalign=0)
            label.set_hexpand(True)
            label.add_css_class("heading")
            top.append(label)
            open_btn = Gtk.Button(label=_("Abrir"))
            open_btn.add_css_class("soft-button")
            open_btn.connect(
                "clicked",
                self._on_open_reference_clicked,
                {
                    "translation": self._backend.db.translation,
                    "book_id": int(item["target_book_id"]),
                    "book_name": str(item.get("target_book_name") or ""),
                    "chapter": int(item["target_chapter"]),
                    "verse": int(item["target_verse"]),
                    "text": str(item.get("target_text") or ""),
                    "is_favorite": False,
                },
            )
            top.append(open_btn)
            box.append(top)
            if item.get("target_text"):
                txt = Gtk.Label(label=str(item["target_text"]), xalign=0, wrap=True)
                txt.add_css_class("dim-label")
                box.append(txt)
            row.set_child(box)
            self.study_refs_list.append(row)

    def _refresh_study_page(self) -> None:
        if not hasattr(self, "study_plans_list"):
            return
        self._refresh_study_notebooks()
        self._refresh_study_plans()
        self._refresh_study_compare()
        self._refresh_study_cross_refs()
        self._refresh_study_recent_notes()
        self._refresh_study_recent_entries()
        self._refresh_study_advanced_search_context()

    def _refresh_study_advanced_search_context(self) -> None:
        if not hasattr(self, "study_adv_book_dropdown"):
            return
        books_catalog = self._backend.list_books()
        labels = [_("Todos os livros")] + [str(b["name"]) for b in books_catalog]
        previous_idx = int(self.study_adv_book_dropdown.get_selected()) if self.study_adv_book_dropdown.get_model() else 0
        self.study_adv_book_codes = [0] + [int(b["id"]) for b in books_catalog]
        self.study_adv_book_dropdown.set_model(Gtk.StringList.new(labels))
        self.study_adv_book_dropdown.set_selected(min(previous_idx, max(0, len(labels) - 1)))

    def _on_open_study_for_reference_clicked(self, _button: Gtk.Button, item: dict) -> None:
        self._select_study_reference(item)
        self._refresh_study_page()
        self.stack.set_visible_child_name("study")

    def _on_open_study_clicked(self, _button: Gtk.Button) -> None:
        self._refresh_study_page()
        self.stack.set_visible_child_name("study")

    def _on_study_use_current_clicked(self, _button: Gtk.Button) -> None:
        payload = self._current_chapter_payload
        if not payload or not payload.get("verses"):
            self._toast(_("Nenhum capítulo carregado para estudo."))
            return
        first = payload["verses"][0]
        self._select_study_reference(
            {
                "translation": payload["translation"],
                "book_id": int(payload["book"]["id"]),
                "book_name": str(payload["book"]["name"]),
                "chapter": int(payload["chapter"]),
                "verse": int(first["verse"]),
                "text": str(first["text"]),
            }
        )
        self._toast(_("Contexto de estudo carregado com o capítulo atual."))

    def _on_study_save_note_clicked(self, _button: Gtk.Button) -> None:
        ref = self._get_selected_study_ref()
        if not ref:
            self._toast(_("Selecione um versículo para salvar nota."))
            return
        tags = [t.strip() for t in self.study_tags_entry.get_text().split(",") if t.strip()]
        color_idx = int(self.study_highlight_dropdown.get_selected())
        color = self.study_highlight_codes[color_idx] if 0 <= color_idx < len(self.study_highlight_codes) else ""
        note_text = self._get_text_view_text(self.study_note_view).strip()
        self._backend.save_study_note(
            translation=ref["translation"],
            book_id=ref["book_id"],
            book=ref["book_name"],
            chapter=ref["chapter"],
            verse=ref["verse"],
            note_text=note_text,
            highlight_color=color,
            tags=tags,
        )
        self.status_line.set_text(_("Nota de estudo salva."))
        self._toast(_("Nota salva."))

    def _on_study_delete_note_clicked(self, _button: Gtk.Button) -> None:
        ref = self._get_selected_study_ref()
        if not ref:
            self._toast(_("Selecione um versículo para remover nota."))
            return
        removed = self._backend.delete_study_note(
            translation=ref["translation"],
            book=ref["book_name"],
            chapter=ref["chapter"],
            verse=ref["verse"],
        )
        if removed:
            self._set_text_view_text(self.study_note_view, "")
            self.study_tags_entry.set_text("")
            self.study_highlight_dropdown.set_selected(0)
            self._toast(_("Nota removida."))
        else:
            self._toast(_("Nenhuma nota para remover."))

    def _on_study_list_chapter_notes_clicked(self, _button: Gtk.Button) -> None:
        ref = self._get_selected_study_ref()
        if not ref:
            self._toast(_("Selecione um versículo para listar notas do capítulo."))
            return
        items = self._backend.list_study_notes(
            translation=ref["translation"], book=ref["book_name"], chapter=ref["chapter"], limit=200
        )
        if not items:
            self._toast(_("Nenhuma nota neste capítulo."))
            return
        preview = " | ".join(f'{i["verse"]}: {str(i.get("note_text") or "")[:30]}' for i in items[:4])
        self.status_line.set_text(f'{len(items)} {_("nota(s) no capítulo")}: {preview}')
        self._toast(f'{len(items)} {_("nota(s) encontradas no capítulo.")}')

    def _on_study_compare_clicked(self, _button: Gtk.Button) -> None:
        self._refresh_study_compare()

    def _on_study_copy_comparison_clicked(self, _button: Gtk.Button) -> None:
        ref = self._get_selected_study_ref()
        if not ref:
            self._toast(_("Selecione um versículo para copiar a comparação."))
            return
        left_idx = int(self.study_compare_left.get_selected())
        right_idx = int(self.study_compare_right.get_selected())
        codes: list[str] = []
        for idx in [left_idx, right_idx]:
            if 0 <= idx < len(self.study_compare_codes):
                code = self.study_compare_codes[idx]
                if code not in codes:
                    codes.append(code)
        rows = self._backend.compare_verse(
            book_id=ref["book_id"],
            chapter=ref["chapter"],
            verse=ref["verse"],
            translations=codes,
        )
        if not rows:
            self._toast(_("Nada para copiar na comparação."))
            return
        parts = [
            f'{item["book_name"]} {item["chapter"]}:{item["verse"]} ({item["translation"]})\n{item.get("text","")}'
            for item in rows
        ]
        self._on_copy_verse_clicked(_button, "\n\n".join(parts))

    def _on_study_refresh_refs_clicked(self, _button: Gtk.Button) -> None:
        self._refresh_study_cross_refs()
        self._toast(_("Referências cruzadas atualizadas."))

    def _on_study_refresh_notebook_entries_clicked(self, _button: Gtk.Button) -> None:
        self._refresh_study_notebook_entries()

    def _on_study_refresh_recent_notes_clicked(self, _widget) -> None:
        self._refresh_study_recent_notes()

    def _on_study_refresh_recent_entries_clicked(self, _button: Gtk.Button) -> None:
        self._refresh_study_recent_entries()

    def _on_study_advanced_search_clicked(self, _widget) -> None:
        query = self.study_adv_query.get_text().strip()
        if not query:
            self._clear_list(self.study_adv_results_list)
            self.study_adv_info.set_text(_("Digite um termo para buscar no estudo."))
            return
        mode_idx = int(self.study_adv_mode_dropdown.get_selected())
        mode = self.study_adv_mode_codes[mode_idx] if 0 <= mode_idx < len(self.study_adv_mode_codes) else "phrase"
        testament_idx = int(self.study_adv_testament_dropdown.get_selected())
        testament_code = (
            self.study_adv_testament_codes[testament_idx]
            if 0 <= testament_idx < len(self.study_adv_testament_codes)
            else 0
        )
        testament_id = int(testament_code) or None
        book_idx = int(self.study_adv_book_dropdown.get_selected())
        book_id = None
        if 0 <= book_idx < len(self.study_adv_book_codes):
            chosen = int(self.study_adv_book_codes[book_idx])
            book_id = chosen or None
        limit = int(self.study_adv_limit_spin.get_value())
        notes_only = self.study_adv_notes_only.get_active()
        results = self._backend.search_study(
            query,
            limit=limit,
            match_mode=mode,
            testament_id=testament_id,
            book_id=book_id,
            notes_only=notes_only,
        )
        self._clear_list(self.study_adv_results_list)
        if not results:
            self._set_status_row(self.study_adv_results_list, _("Nenhum resultado na busca avançada."))
            self.study_adv_info.set_text(_("Nenhum resultado encontrado com os filtros atuais."))
            return
        self.study_adv_info.set_text(
            f'{len(results)} {_("resultado(s)")} | {_("modo")}={mode} | {_("tradução")}={self._backend.db.translation}'
        )
        for item in results:
            row = self._build_search_result_row(item, query)
            if item.get("has_note"):
                row.add_css_class("study-annotated-row")
            self.study_adv_results_list.append(row)

    def _on_study_notebook_changed(self, _dropdown: Gtk.DropDown, _pspec) -> None:
        self._refresh_study_notebook_entries()

    def _on_study_remove_notebook_entry_clicked(self, _button: Gtk.Button, entry_id: int) -> None:
        removed = self._backend.delete_notebook_entry(entry_id=entry_id)
        if removed:
            self._refresh_study_notebook_entries()
            self._refresh_study_notebooks()
            self._toast(_("Entrada removida do caderno."))
        else:
            self._toast(_("Entrada não encontrada."))

    def _on_study_import_crossrefs_clicked(self, _button: Gtk.Button) -> None:
        project_root = Path(__file__).resolve().parents[1]
        importer = project_root / "scripts" / "import_scrollmapper_crossrefs.py"
        candidates = [
            Path("/tmp/scrollmapper-bible-databases/formats/sqlite/cross_references.db"),
            Path("/tmp/scrollmapper-bible-databases/cross_references.db"),
            Path("/tmp/scrollmapper-bible-databases/formats/sqlite/extras"),
            project_root / "data" / "cross_references.db",
        ]
        for base in [Path.home() / "Downloads", Path.home() / "Documentos"]:
            if base.exists():
                for pattern in ["*cross*ref*.db", "*cross*reference*.db", "*xref*.db", "*cross*.sqlite"]:
                    candidates.extend(sorted(base.rglob(pattern))[:10])
        source = next((p for p in candidates if p.exists()), None)
        if source is None:
            self.status_line.set_text(
                _("Arquivo de referências cruzadas não encontrado. Baixe o SQLite e use scripts/import_scrollmapper_crossrefs.py.")
            )
            self._toast(_("Referências cruzadas: arquivo de origem não encontrado."))
            return
        study_db = self._backend.study.db_path
        result = subprocess.run(
            [sys.executable, str(importer), "--source", str(source), "--study-db", str(study_db)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or _("Falha ao importar referências cruzadas.")).strip()
            self.status_line.set_text(f'{_("Falha ao importar referências cruzadas")}: {msg.splitlines()[-1]}')
            self._last_daily_error_text = msg
            self._toast(_("Falha ao importar referências cruzadas."))
            return
        out = (result.stdout or "").strip()
        self.status_line.set_text(out or _("Referências cruzadas importadas."))
        self._refresh_study_cross_refs()
        self._toast(_("Referências cruzadas importadas."))

    def _on_study_complete_next_plan_day_clicked(self, _button: Gtk.Button, plan: dict) -> None:
        progress = set(self._backend.list_plan_progress(plan_slug=str(plan["slug"])))
        total = int(plan.get("total_days") or len(plan.get("days") or []))
        next_day = next((idx for idx in range(1, total + 1) if idx not in progress), None)
        if next_day is None:
            self._toast(_("Plano já concluído."))
            return
        self._backend.set_plan_day_completed(plan_slug=str(plan["slug"]), day_index=next_day, completed=True)
        self._refresh_study_plans()
        self._toast(f'{_("Dia concluído")}: {next_day}')
        self._open_plan_day_reference(plan, next_day)

    def _on_study_open_next_plan_day_clicked(self, _button: Gtk.Button, plan: dict) -> None:
        progress = set(self._backend.list_plan_progress(plan_slug=str(plan["slug"])))
        total = int(plan.get("total_days") or len(plan.get("days") or []))
        next_day = next((idx for idx in range(1, total + 1) if idx not in progress), None)
        if next_day is None:
            self._toast(_("Plano já concluído."))
            return
        self._open_plan_day_reference(plan, next_day)
        self._toast(f'{_("Abrindo próximo dia")}: {next_day}')

    def _on_study_undo_plan_day_clicked(self, _button: Gtk.Button, plan: dict) -> None:
        progress = self._backend.list_plan_progress(plan_slug=str(plan["slug"]))
        if not progress:
            self._toast(_("Nenhum dia concluído para desfazer."))
            return
        last_day = max(progress)
        self._backend.set_plan_day_completed(plan_slug=str(plan["slug"]), day_index=last_day, completed=False)
        self._refresh_study_plans()
        self._toast(f'{_("Dia desfeito")}: {last_day}')

    def _on_study_open_plan_days_clicked(self, _button: Gtk.Button, plan: dict) -> None:
        dialog = Gtk.Window(transient_for=self, modal=True)
        dialog.set_title(f'{_("Plano")}: {plan.get("title", "")}')
        dialog.set_default_size(760, 540)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label=str(plan.get("title") or ""), xalign=0)
        title.add_css_class("title-4")
        title.set_hexpand(True)
        header.append(title)
        close_btn = Gtk.Button(label=_("Fechar"))
        close_btn.add_css_class("soft-button")
        close_btn.connect("clicked", lambda *_: dialog.close())
        header.append(close_btn)
        root.append(header)

        subtitle = Gtk.Label(label=str(plan.get("description") or ""), xalign=0, wrap=True)
        subtitle.add_css_class("dim-label")
        root.append(subtitle)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")

        progress = set(self._backend.list_plan_progress(plan_slug=str(plan["slug"])))
        days = list(plan.get("days") or [])
        for idx, refs in enumerate(days, start=1):
            row = Gtk.ListBoxRow()
            row.add_css_class("card")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)
            box.set_margin_end(12)

            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            done = idx in progress
            left = Gtk.Label(
                label=f'{_("Dia")} {idx} {"✓" if done else "•"}',
                xalign=0,
            )
            left.add_css_class("heading")
            left.set_hexpand(True)
            top.append(left)

            open_btn = Gtk.Button(label=_("Abrir"))
            open_btn.add_css_class("soft-button")
            open_btn.connect("clicked", self._on_study_open_specific_plan_day_clicked, plan, idx)
            top.append(open_btn)

            toggle_label = _("Desfazer") if done else _("Concluir")
            toggle_btn = Gtk.Button(label=toggle_label)
            toggle_btn.add_css_class("soft-button")
            toggle_btn.connect(
                "clicked",
                self._on_study_toggle_specific_plan_day_clicked,
                plan,
                idx,
                done,
                dialog,
            )
            top.append(toggle_btn)
            box.append(top)

            refs_text = ", ".join(str(r) for r in (refs or [])) or _("Sem referência")
            refs_label = Gtk.Label(label=refs_text, xalign=0, wrap=True)
            refs_label.add_css_class("dim-label")
            box.append(refs_label)
            row.set_child(box)
            listbox.append(row)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_child(listbox)
        root.append(scrolled)

        dialog.set_child(root)
        dialog.present()

    def _on_study_open_specific_plan_day_clicked(
        self, _button: Gtk.Button, plan: dict, day_index: int
    ) -> None:
        self._open_plan_day_reference(plan, day_index)
        self._toast(f'{_("Abrindo dia")} {day_index}.')

    def _on_study_toggle_specific_plan_day_clicked(
        self,
        _button: Gtk.Button,
        plan: dict,
        day_index: int,
        was_done: bool,
        dialog: Gtk.Window,
    ) -> None:
        self._backend.set_plan_day_completed(
            plan_slug=str(plan["slug"]),
            day_index=int(day_index),
            completed=not was_done,
        )
        self._refresh_study_plans()
        self._toast(
            (f'{_("Dia concluído")}: {day_index}') if not was_done else (f'{_("Dia desfeito")}: {day_index}')
        )
        dialog.close()
        self._on_study_open_plan_days_clicked(Gtk.Button(), plan)

    def _on_study_create_notebook_clicked(self, _button: Gtk.Button) -> None:
        base = _("Caderno")
        existing = self._backend.list_notebooks()
        name = f"{base} {len(existing) + 1}"
        self._backend.create_notebook(name=name)
        self._refresh_study_notebooks()
        self._toast(f'{_("Caderno criado")}: {name}')

    def _on_study_add_to_notebook_clicked(self, _button: Gtk.Button) -> None:
        ref = self._get_selected_study_ref()
        if not ref:
            self._toast(_("Selecione um versículo para salvar no caderno."))
            return
        notebooks = getattr(self, "_study_notebook_items", []) or self._backend.list_notebooks()
        idx = int(self.study_notebook_dropdown.get_selected())
        if idx < 0 or idx >= len(notebooks):
            self._toast(_("Selecione um caderno válido."))
            return
        note_text = self._get_text_view_text(self.study_note_view).strip()
        self._backend.add_notebook_entry(
            notebook_id=int(notebooks[idx]["id"]),
            translation=ref["translation"],
            book_id=ref["book_id"],
            book=ref["book_name"],
            chapter=ref["chapter"],
            verse=ref["verse"],
            note_text=note_text,
        )
        self._refresh_study_notebooks()
        self._toast(_("Referência salva no caderno."))

    def _on_study_export_clicked(self, _button: Gtk.Button) -> None:
        export_dir = Path.home() / "Documentos"
        if not export_dir.exists():
            export_dir = Path.home()
        target = export_dir / f'bibliaroot-estudo-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'
        try:
            self._backend.export_study_data(target)
        except Exception as exc:
            self.status_line.set_text(f'{_("Falha ao exportar dados de estudo")}: {exc}')
            self._toast(_("Falha ao exportar dados de estudo."))
            return
        self.status_line.set_text(f'{_("Dados de estudo exportados para")}: {target}')
        self._toast(_("Dados de estudo exportados."))

    def _on_study_import_clicked(self, _button: Gtk.Button) -> None:
        candidates = sorted(
            [
                p
                for pattern in ("bibliaroot-estudo-*.json", "bibliaapp-estudo-*.json")
                for p in (Path.home() / "Documentos").glob(pattern)
                if p.is_file()
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            self.status_line.set_text(_("Nenhum backup encontrado em Documentos (bibliaroot-estudo-*.json)."))
            self._toast(_("Nenhum backup de estudo encontrado."))
            return
        source = candidates[0]
        try:
            counts = self._backend.import_study_data(source, merge=True)
        except Exception as exc:
            self.status_line.set_text(f'{_("Falha ao importar dados de estudo")}: {exc}')
            self._toast(_("Falha ao importar dados de estudo."))
            return
        self._refresh_study_page()
        self.status_line.set_text(
            f'{_("Backup importado")}: {source.name} | {counts.get("notes", 0)} {_("notas")} | '
            f'{counts.get("cross_references", 0)} {_("refs")}'
        )
        self._toast(_("Backup de estudo importado."))

    def _on_app_export_full_backup_clicked(self, _button: Gtk.Button) -> None:
        export_dir = Path.home() / "Documentos"
        if not export_dir.exists():
            export_dir = Path.home()
        target = export_dir / f'bibliaroot-backup-completo-{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'
        try:
            self._backend.export_full_backup(target)
        except Exception as exc:
            self.status_line.set_text(f'{_("Falha ao exportar backup completo")}: {exc}')
            self._toast(_("Falha ao exportar backup completo."))
            return
        self.status_line.set_text(f'{_("Backup completo exportado para")}: {target}')
        self._toast(_("Backup completo exportado."))

    def _on_app_import_full_backup_clicked(self, _button: Gtk.Button) -> None:
        candidates = sorted(
            [
                p
                for pattern in ("bibliaroot-backup-completo-*.json", "bibliaapp-backup-completo-*.json")
                for p in (Path.home() / "Documentos").glob(pattern)
                if p.is_file()
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            self.status_line.set_text(_("Nenhum backup completo encontrado em Documentos."))
            self._toast(_("Nenhum backup completo encontrado."))
            return
        source = candidates[0]
        try:
            counts = self._backend.import_full_backup(source, merge=True)
        except Exception as exc:
            self.status_line.set_text(f'{_("Falha ao restaurar backup completo")}: {exc}')
            self._toast(_("Falha ao restaurar backup completo."))
            return
        self._sync_settings_controls()
        self._refresh_favorites()
        self._refresh_study_page()
        self.status_line.set_text(
            f'{_("Backup completo restaurado")}: {source.name} | {_("favoritos")}={counts.get("favorites", 0)}'
        )
        self._toast(_("Backup completo restaurado."))

    def _open_plan_day_reference(self, plan: dict, day_index: int) -> None:
        days = list(plan.get("days") or [])
        if day_index < 1 or day_index > len(days):
            return
        refs = days[day_index - 1]
        if not refs:
            return
        first_ref = str(refs[0])
        parsed = self._parse_reference_string(first_ref)
        if not parsed:
            return
        book = self._backend.db.find_book(parsed["book"])
        if not book:
            return
        item = {
            "translation": self._backend.db.translation,
            "book_id": int(book["id"]),
            "book_name": str(book["name"]),
            "chapter": int(parsed["chapter"]),
            "verse": int(parsed.get("verse") or 1),
            "text": "",
        }
        self._on_open_reference_clicked(Gtk.Button(), item)

    def _parse_reference_string(self, text: str) -> dict | None:
        value = " ".join(str(text).strip().split())
        if not value:
            return None
        parts = value.rsplit(" ", 1)
        if len(parts) != 2:
            return None
        book, last = parts
        chapter_part = last
        verse_part: int | None = None
        if ":" in chapter_part:
            ch, vs = chapter_part.split(":", 1)
            chapter_part = ch
            if vs.isdigit():
                verse_part = int(vs)
        elif "-" in chapter_part:
            chapter_part = chapter_part.split("-", 1)[0]
        if not str(chapter_part).isdigit():
            return None
        return {"book": book, "chapter": int(chapter_part), "verse": verse_part}

    def _on_open_favorites_clicked(self, _button: Gtk.Button) -> None:
        self._refresh_favorites()
        self.stack.set_visible_child_name("favorites")

    def _on_toggle_focus_mode_clicked(self, _button: Gtk.Button) -> None:
        self._focus_mode = not self._focus_mode
        self.sidebar.set_visible(not self._focus_mode)
        self.stack_switcher.set_visible(not self._focus_mode)
        self.focus_mode_button.set_label(_("Sair do foco") if self._focus_mode else _("Modo foco"))
        if self._focus_mode:
            self._focus_mode_saved_font_scale = self._font_scale
            self._apply_font_scale(min(2.0, self._font_scale + 0.2), persist=False)
        elif self._focus_mode_saved_font_scale is not None:
            self._apply_font_scale(self._focus_mode_saved_font_scale, persist=False)
            self._focus_mode_saved_font_scale = None
        self._toast(_("Modo foco ativado.") if self._focus_mode else _("Modo foco desativado."))

    def _on_open_settings_clicked(self, _button: Gtk.Button) -> None:
        self._sync_settings_controls()
        self._refresh_daily_timer_status()
        self.stack.set_visible_child_name("settings")

    def _on_daily_enabled_changed(self, switch: Adw.SwitchRow, _pspec) -> None:
        if self._daily_controls_syncing:
            return
        self._backend.set_daily_content_settings(enabled=switch.get_active())
        self._update_daily_preview_label()

    def _on_daily_mode_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._daily_controls_syncing:
            return
        idx = int(dropdown.get_selected())
        if idx < 0 or idx >= len(self.daily_mode_codes):
            return
        mode = self.daily_mode_codes[idx]
        self._backend.set_daily_content_settings(mode=mode)
        self._update_daily_preview_label()

    def _on_daily_content_translation_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._daily_controls_syncing:
            return
        idx = int(dropdown.get_selected())
        if idx < 0 or idx >= len(self.daily_content_translation_codes):
            return
        code = self.daily_content_translation_codes[idx]
        self._backend.set_daily_content_settings(translation=code)
        self._update_daily_preview_label()

    def _on_daily_schedule_mode_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._daily_controls_syncing:
            return
        self._refresh_daily_schedule_controls()
        if int(dropdown.get_selected()) == 0:
            # Modo "uma vez ao dia": força 1 envio e desliga a redundância.
            self._backend.set_daily_content_settings(messages_per_day=1)
            self.daily_count_spin.set_value(1)
            self.daily_end_time_entry.set_text(self.daily_time_entry.get_text().strip() or "08:00")
            self._backend.set_daily_content_settings(
                end_time_str=self.daily_end_time_entry.get_text().strip() or "08:00"
            )
        elif int(self.daily_count_spin.get_value()) < 2:
            self.daily_count_spin.set_value(2)
            self._backend.set_daily_content_settings(messages_per_day=2)
        self._update_daily_preview_label()

    def _on_daily_preview_clicked(self, _button: Gtk.Button) -> None:
        self._update_daily_preview_label(force_refresh=True)
        self._toast(_("Prévia diária atualizada."))

    def _on_daily_count_changed(self, spin: Gtk.SpinButton) -> None:
        if self._daily_controls_syncing:
            return
        self._backend.set_daily_content_settings(messages_per_day=int(spin.get_value()))
        self._refresh_daily_schedule_controls()
        self._update_daily_preview_label()

    def _on_daily_interval_changed(self, spin: Gtk.SpinButton) -> None:
        if self._daily_controls_syncing:
            return
        self._backend.set_daily_content_settings(interval_minutes=int(spin.get_value()))
        self._update_daily_preview_label()

    def _on_daily_persistent_changed(self, switch: Adw.SwitchRow, _pspec) -> None:
        if self._daily_controls_syncing:
            return
        self._backend.set_daily_content_settings(persistent_notification=switch.get_active())
        self._update_daily_preview_label()

    def _on_daily_delivery_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._daily_controls_syncing:
            return
        idx = int(dropdown.get_selected())
        mode = "popup" if idx == 1 else "native"
        self._backend.set_daily_content_settings(delivery_mode=mode)
        self._update_daily_preview_label()

    def _on_daily_sound_changed(self, switch: Adw.SwitchRow, _pspec) -> None:
        if self._daily_controls_syncing:
            return
        self._backend.set_daily_content_settings(sound_enabled=switch.get_active())
        if hasattr(self, "daily_sound_row"):
            self.daily_sound_row.set_sensitive(switch.get_active())
        self._update_daily_preview_label()

    def _on_daily_sound_type_changed(self, dropdown: Gtk.DropDown, _pspec) -> None:
        if self._daily_controls_syncing:
            return
        idx = int(dropdown.get_selected())
        if idx < 0 or idx >= len(self.daily_sound_codes):
            return
        self._backend.set_daily_content_settings(sound_name=self.daily_sound_codes[idx])
        self._update_daily_preview_label()

    def _on_daily_apply_clicked(self, _button) -> None:
        mode = self.daily_mode_codes[int(self.daily_mode_dropdown.get_selected())]
        try:
            time_str, end_time_str = self._read_daily_time_inputs()
        except ValueError as exc:
            self.status_line.set_text(str(exc))
            self._toast(str(exc))
            return
        enabled = self.daily_enabled_switch.get_active()
        schedule_mode = self.daily_schedule_mode_codes[int(self.daily_schedule_mode_dropdown.get_selected())]
        if schedule_mode == "once":
            end_time_str = time_str
        interval = int(self.daily_interval_spin.get_value())
        computed_times = [time_str]
        try:
            computed_times = self._backend._build_schedule_times(time_str, end_time_str, interval)
            count = len(computed_times) if schedule_mode == "repeat" else 1
            delivery_mode = self.daily_delivery_codes[int(self.daily_delivery_dropdown.get_selected())]
            sound_enabled = self.daily_sound_switch.get_active()
            sound_name = self.daily_sound_codes[int(self.daily_sound_dropdown.get_selected())]
            daily_translation = self.daily_content_translation_codes[
                int(self.daily_content_translation_dropdown.get_selected())
            ]
            self._backend.set_daily_content_settings(
                enabled=enabled,
                mode=mode,
                translation=daily_translation,
                time_str=time_str,
                end_time_str=end_time_str,
                messages_per_day=count,
                interval_minutes=interval,
                persistent_notification=self.daily_persistent_switch.get_active(),
                delivery_mode=delivery_mode,
                sound_enabled=sound_enabled,
                sound_name=sound_name,
            )
        except ValueError as exc:
            self.status_line.set_text(str(exc))
            self._toast(str(exc))
            return

        project_root = Path(__file__).resolve().parents[1]
        script = project_root / "scripts" / "install_daily_timer.py"
        cmd = [
            sys.executable,
            str(script),
            "--time",
            time_str,
            "--end-time",
            end_time_str,
            "--mode",
            mode,
            "--count",
            str(count),
            "--interval",
            str(interval),
        ]
        if not enabled:
            cmd = [sys.executable, str(script), "--disable"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or _("Falha ao configurar agendamento.")).strip()
            short_msg = msg.splitlines()[-1] if msg else _("Falha ao configurar agendamento.")
            self.status_line.set_text(f'{_("Falha no agendamento diário")}: {short_msg}')
            self.daily_timer_status_label.set_text(
                _("Erro ao aplicar agendamento (copiável):") + "\n" + msg
            )
            self._last_daily_error_text = msg
            self._toast(_("Falha no agendamento diário."))
            print(msg)
            return
        success_msg = (result.stdout or _("Agendamento diário atualizado.")).strip()
        self._last_daily_error_text = ""
        self.status_line.set_text(
            success_msg
            + f' {_("Resumo")}: {len(computed_times)} {_("envio(s)")}, {_("janela")} {time_str}→{end_time_str}, '
            + f'{_("intervalo")} {interval} {_("min")}.'
        )
        self._refresh_daily_timer_status()
        self._toast(_("Agendamento diário aplicado."))

    def _on_daily_disable_clicked(self, _button: Gtk.Button) -> None:
        if hasattr(self, "daily_enabled_switch"):
            self.daily_enabled_switch.set_active(False)
        self._on_daily_apply_clicked(_button)

    def _on_daily_test_now_clicked(self, _button: Gtk.Button) -> None:
        project_root = Path(__file__).resolve().parents[1]
        script = project_root / "scripts" / "daily_notification.py"
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or _("Falha ao testar notificação.")).strip()
            self.status_line.set_text(f'{_("Teste de notificação falhou")}: {msg.splitlines()[-1]}')
            self.daily_timer_status_label.set_text(f'{_("Teste manual")}: {msg}')
            self._last_daily_error_text = msg
            self._toast(_("Falha no teste de notificação."))
            return
        self.status_line.set_text(_("Notificação de teste enviada."))
        self.daily_timer_status_label.set_text(_("Teste manual executado com sucesso."))
        self._last_daily_error_text = ""
        self._toast(_("Notificação de teste enviada."))

    def _on_daily_status_clicked(self, _button: Gtk.Button) -> None:
        self._refresh_daily_timer_status()
        self._toast(_("Status do timer atualizado."))

    def _update_daily_preview_label(self, force_refresh: bool = False) -> None:
        if not hasattr(self, "daily_preview_label"):
            return
        settings = self._backend.get_settings()
        try:
            preview = self._backend.get_daily_content_preview(mode=settings.daily_content_mode)
            summary = f"{preview.title} | {preview.reference} ({preview.translation})"
        except Exception as exc:
            summary = f'{_("Prévia indisponível")}: {exc}'
        status = _("ativado") if settings.daily_content_enabled else _("desativado")
        schedule_times = self._backend.compute_daily_schedule_times(settings)
        frequency_text = (
            f'{len(schedule_times)} {_("envio(s)")}'
            + (f' {_("a cada")} {settings.daily_interval_minutes} {_("min")}' if len(schedule_times) > 1 else "")
        )
        delivery_label = _("popup do BíbliaRoot") if getattr(settings, "daily_delivery_mode", "native") == "popup" else _("nativa")
        sound_name = getattr(settings, "daily_sound_name", "soft")
        fixed_daily_translation = (getattr(settings, "daily_content_translation", "") or "").strip().upper()
        daily_translation_label = fixed_daily_translation or _("tradução ativa")
        self.daily_preview_label.set_text(
            f'{_("Status")}: {status} | {_("Janela")}: {settings.daily_content_time} → '
            f"{getattr(settings, 'daily_content_end_time', settings.daily_content_time)} | "
            f"{frequency_text} | "
            f"{delivery_label} | "
            f'{_("persistente") if settings.daily_notification_persistent else _("timeout padrão")} | '
            f'{(_("som") + " " + sound_name) if getattr(settings, "daily_sound_enabled", False) else _("som off")} | '
            f'{_("tradução diária")} {daily_translation_label} | '
            f"{summary}"
        )

    def _refresh_daily_schedule_controls(self) -> None:
        if not hasattr(self, "daily_schedule_mode_dropdown"):
            return
        mode_idx = int(self.daily_schedule_mode_dropdown.get_selected())
        is_repeat = mode_idx == 1
        if hasattr(self, "daily_count_spin"):
            self.daily_count_spin.set_sensitive(is_repeat)
        if hasattr(self, "daily_count_row"):
            self.daily_count_row.set_sensitive(False)
            self.daily_count_row.set_visible(False)
        if hasattr(self, "daily_end_time_entry"):
            self.daily_end_time_entry.set_sensitive(is_repeat)
        if hasattr(self, "daily_end_time_row"):
            self.daily_end_time_row.set_sensitive(is_repeat)
        if hasattr(self, "daily_interval_spin"):
            self.daily_interval_spin.set_sensitive(is_repeat)
        if hasattr(self, "daily_interval_row"):
            self.daily_interval_row.set_sensitive(is_repeat)
        if hasattr(self, "daily_sound_row") and hasattr(self, "daily_sound_switch"):
            self.daily_sound_row.set_sensitive(self.daily_sound_switch.get_active())

    def _refresh_daily_timer_status(self) -> None:
        if not hasattr(self, "daily_timer_status_label"):
            return
        timer_name = f"{DAILY_TIMER_NAME}.timer"
        try:
            cmd = self._systemctl_user_cmd()
        except FileNotFoundError:
            self.daily_timer_status_label.set_text(
                _("Timer: systemctl indisponível neste ambiente (ex.: Flatpak sem acesso ao host).")
            )
            return
        result = subprocess.run(
            [*cmd, "show", timer_name, "-p", "ActiveState", "-p", "NextElapseUSecRealtime"],
            capture_output=True,
            text=True,
            cwd=str(Path.home()),
        )
        if result.returncode != 0:
            msg = (result.stderr or result.stdout or _("systemd --user indisponível")).strip()
            self.daily_timer_status_label.set_text(f'{_("Timer: falha ao consultar status")} ({msg})')
            self._last_daily_error_text = msg
            return
        data: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                data[k] = v
        active = data.get("ActiveState", _("desconhecido"))
        next_elapse = data.get("NextElapseUSecRealtime", "")
        next_text = next_elapse if next_elapse else _("sem próximo disparo")
        self.daily_timer_status_label.set_text(f'{_("Timer")}: {active} | {_("Próximo")}: {next_text}')
        self._last_daily_error_text = ""

    def _on_copy_daily_error_clicked(self, _button: Gtk.Button) -> None:
        text = self._last_daily_error_text or self.daily_timer_status_label.get_text() or ""
        if not text.strip():
            self._toast(_("Nenhum erro/status para copiar."))
            return
        display = self.get_display()
        if display is None:
            self.status_line.set_text(_("Sem display gráfico para copiar texto."))
            return
        clipboard: Gdk.Clipboard = display.get_clipboard()
        clipboard.set_text(text)
        self._toast(_("Erro/status copiado."))

    def _systemctl_user_cmd(self) -> list[str]:
        if shutil.which("systemctl"):
            return ["systemctl", "--user"]
        raise FileNotFoundError("systemctl")

    def _run_host_or_local_command(self, cmd: list[str]) -> bool:
        if not cmd:
            return False
        exe = cmd[0]
        attempts: list[list[str]] = []
        if shutil.which(exe):
            attempts.append(cmd)
        for attempt in attempts:
            result = subprocess.run(
                attempt,
                capture_output=True,
                text=True,
                cwd=str(Path.home()),
            )
            if result.returncode == 0:
                return True
        return False

    def _on_time_entry_insert_text(
        self, editable: Gtk.Editable, text: str, _length: int, _position: int
    ) -> None:
        if all(ch.isdigit() or ch == ":" for ch in text):
            return
        editable.stop_emission_by_name("insert-text")

    def _on_time_entry_changed(self, entry: Gtk.Entry) -> None:
        if self._time_entry_mask_syncing:
            return
        raw = entry.get_text()
        digits = "".join(ch for ch in raw if ch.isdigit())[:4]
        if len(digits) <= 2:
            formatted = digits
        else:
            formatted = f"{digits[:2]}:{digits[2:]}"
        if formatted == raw:
            return
        pos = entry.get_position()
        self._time_entry_mask_syncing = True
        try:
            entry.set_text(formatted)
            entry.set_position(min(len(formatted), pos + (1 if len(digits) > 2 and ":" not in raw else 0)))
        finally:
            self._time_entry_mask_syncing = False

    def _normalize_hhmm(self, value: str) -> str:
        text = value.strip()
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) == 4 and ":" not in text:
            text = f"{digits[:2]}:{digits[2:]}"
        parts = text.split(":")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            raise ValueError(_("Horário inválido. Use o formato HH:MM (ex.: 08:00)."))
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(_("Horário inválido. A hora deve estar entre 00:00 e 23:59."))
        return f"{hour:02d}:{minute:02d}"

    def _read_daily_time_inputs(self) -> tuple[str, str]:
        time_str = self._normalize_hhmm(self.daily_time_entry.get_text())
        self.daily_time_entry.set_text(time_str)
        end_raw = self.daily_end_time_entry.get_text().strip() or time_str
        end_time_str = self._normalize_hhmm(end_raw)
        self.daily_end_time_entry.set_text(end_time_str)
        return time_str, end_time_str

    def _wrap_in_preferences_row(self, widget: Gtk.Widget) -> Adw.ActionRow:
        row = Adw.ActionRow()
        row.add_suffix(widget)
        row.set_activatable(False)
        return row

    def _on_refresh_favorites_clicked(self, _button: Gtk.Button) -> None:
        self._refresh_favorites()

    def _refresh_favorites(self) -> None:
        items = self._backend.list_favorites()
        self._clear_list(self.favorites_list)
        if not items:
            self.favorites_info.set_text(_("Nenhum favorito salvo ainda."))
            return
        self.favorites_info.set_text(f"{len(items)} {(_('favorito(s) salvos.'))}")
        for item in items:
            self.favorites_list.append(self._build_favorite_row(item))

    def _build_favorite_row(self, item: dict) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("card")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ref = Gtk.Label(
            label=f'{item["book"]} {item["chapter"]}:{item["verse"]} ({item["translation"]})',
            xalign=0,
        )
        ref.set_hexpand(True)
        ref.add_css_class("heading")
        top.append(ref)

        open_button = Gtk.Button(label=_("Abrir"))
        open_button.add_css_class("soft-button")
        open_button.connect(
            "clicked",
            self._on_open_reference_clicked,
            {
                "translation": item["translation"],
                "book_id": item["book_id"] or 0,
                "book_name": item["book"],
                "chapter": item["chapter"],
                "verse": item["verse"],
                "text": item.get("text") or "",
                "is_favorite": True,
            },
        )
        top.append(open_button)

        remove_button = Gtk.Button(label=_("Remover"))
        remove_button.add_css_class("soft-button")
        remove_button.add_css_class("destructive-action")
        remove_button.connect(
            "clicked",
            self._on_toggle_favorite_clicked,
            {
                "translation": item["translation"],
                "book_id": int(item["book_id"] or 0),
                "book_name": item["book"],
                "chapter": int(item["chapter"]),
                "verse": int(item["verse"]),
                "text": item.get("text") or "",
            },
        )
        top.append(remove_button)
        box.append(top)

        text = Gtk.Label(label=item.get("text") or "", wrap=True, xalign=0)
        text.set_selectable(True)
        text.add_css_class("favorite-text")
        box.append(text)

        row.set_child(box)
        return row

    def _clear_list(self, listbox: Gtk.ListBox) -> None:
        while (row := listbox.get_row_at_index(0)) is not None:
            listbox.remove(row)

    def _set_status_row(self, listbox: Gtk.ListBox, message: str) -> None:
        self._clear_list(listbox)
        row = Gtk.ListBoxRow()
        label = Gtk.Label(label=message, wrap=True, xalign=0)
        label.set_margin_top(12)
        label.set_margin_bottom(12)
        label.set_margin_start(12)
        label.set_margin_end(12)
        row.set_child(label)
        listbox.append(row)

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=2))

    def _install_shortcuts(self) -> None:
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _on_key_pressed(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(state & Gdk.ModifierType.ALT_MASK)

        if ctrl and keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.stack.set_visible_child_name("search")
            self.search_entry.grab_focus()
            return True
        if ctrl and keyval in (Gdk.KEY_l, Gdk.KEY_L):
            self.stack.set_visible_child_name("reader")
            return True
        if ctrl and keyval in (Gdk.KEY_d, Gdk.KEY_D):
            self._refresh_favorites()
            self.stack.set_visible_child_name("favorites")
            return True
        if ctrl and keyval in (Gdk.KEY_e, Gdk.KEY_E):
            self._on_open_study_clicked(Gtk.Button())
            return True
        if ctrl and keyval == Gdk.KEY_comma:
            self._on_open_settings_clicked(Gtk.Button())
            return True
        if alt and keyval == Gdk.KEY_Left:
            self._on_prev_chapter_clicked(Gtk.Button())
            return True
        if alt and keyval == Gdk.KEY_Right:
            self._on_next_chapter_clicked(Gtk.Button())
            return True
        return False
