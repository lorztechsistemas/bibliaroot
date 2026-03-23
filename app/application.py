from __future__ import annotations

import json
from pathlib import Path

from .constants import APP_ID, APP_SLUG, LEGACY_APP_SLUG
from .i18n import _, setup_i18n


def _preferred_ui_language() -> str | None:
    xdg_config_home = Path.home() / ".config"
    try:
        import os
        env = os.getenv("XDG_CONFIG_HOME")
        if env:
            xdg_config_home = Path(env)
    except Exception:
        pass
    candidates = [
        xdg_config_home / APP_SLUG / "settings.json",
        xdg_config_home / LEGACY_APP_SLUG / "settings.json",
    ]
    settings_path = next((path for path in candidates if path.exists()), None)
    if settings_path is None:
        return None
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    value = str(raw.get("ui_language", "") or "").strip()
    return value or None


def run() -> int:
    setup_i18n(preferred_language=_preferred_ui_language())
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, Gtk
    except ImportError as exc:
        print(
            _("PyGObject/GTK4/libadwaita nao encontrados. ")
            + _("Instale as dependencias do sistema antes de rodar o app.")
        )
        print(f'{_("Detalhe")}: {exc}')
        return 1

    if not Gtk.init_check():
        print(
            _("Nao foi possivel iniciar a interface GTK (sem display grafico disponivel). ")
            + _("Execute em uma sessao grafica Linux.")
        )
        return 1

    from .window import MainWindow

    css_path = Path("resources/css/style.css")
    if css_path.exists():
        provider = Gtk.CssProvider()
        provider.load_from_path(str(css_path))
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    class BibliaApplication(Adw.Application):
        def __init__(self) -> None:
            super().__init__(application_id=APP_ID)
            self.connect("activate", self._on_activate)

        def _on_activate(self, app: Adw.Application) -> None:
            window = self.props.active_window
            if window is None:
                window = MainWindow(application=app)
            window.present()

    Adw.init()
    app = BibliaApplication()
    return app.run([])
