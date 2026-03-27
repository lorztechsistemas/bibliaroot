from __future__ import annotations

import json
import os
from pathlib import Path
import sys

from .constants import APP_ID, APP_SLUG, LEGACY_APP_SLUG
from .i18n import _, setup_i18n


def _preferred_ui_language() -> str | None:
    xdg_config_home = Path.home() / ".config"
    try:
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


def _is_flatpak_runtime() -> bool:
    return bool(os.getenv("FLATPAK_ID", "").strip())


def _request_flatpak_background_permission(
    *,
    reason: str,
    autostart: bool,
    commandline: list[str],
) -> tuple[bool | None, str]:
    try:
        import gi

        gi.require_version("Gio", "2.0")
        gi.require_version("GLib", "2.0")
        from gi.repository import Gio, GLib
    except Exception as exc:
        return None, _("Não foi possível preparar o envio automático de mensagens neste momento.")

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        sender = bus.get_unique_name().lstrip(":").replace(".", "_")
        token = f"bibliaroot{GLib.get_monotonic_time()}"
        request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        response_data: dict[str, object] = {"response": None, "results": {}}
        loop = GLib.MainLoop()

        def on_response(_conn, _sender_name, _object_path, _interface_name, _signal_name, parameters, _user_data):
            response, results = parameters.unpack()
            response_data["response"] = response
            response_data["results"] = results
            loop.quit()

        subscription_id = bus.signal_subscribe(
            "org.freedesktop.portal.Desktop",
            "org.freedesktop.portal.Request",
            "Response",
            request_path,
            None,
            Gio.DBusSignalFlags.NONE,
            on_response,
            None,
        )
        try:
            proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Background",
                None,
            )
            options = {
                "handle_token": GLib.Variant("s", token),
                "reason": GLib.Variant("s", reason),
                "autostart": GLib.Variant("b", autostart),
                "background": GLib.Variant("b", autostart),
                "commandline": GLib.Variant("as", commandline),
                "dbus-activatable": GLib.Variant("b", False),
            }
            proxy.call_sync(
                "RequestBackground",
                GLib.Variant("(sa{sv})", ("", options)),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            GLib.timeout_add_seconds(20, lambda: (loop.quit(), False)[1])
            loop.run()
        finally:
            bus.signal_unsubscribe(subscription_id)
    except Exception as exc:
        message = str(exc)
        if "No such interface" in message or "nenhuma interface" in message.lower():
            return (
                None,
                _(
                    "As mensagens automáticas continuarão funcionando enquanto este computador permanecer ligado e com sua sessão iniciada."
                ),
            )
        return None, _("Não foi possível ativar o envio automático neste momento.")

    response = response_data.get("response")
    if response == 0:
        return True, _("Mensagens automáticas ativadas com sucesso.")
    if response is None:
        return None, _("Configuração salva. As mensagens automáticas já podem ser usadas.")
    return False, _("Configuração salva. Para receber mensagens automáticas, mantenha esta opção permitida no sistema.")


def run(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv)
    setup_i18n(preferred_language=_preferred_ui_language())
    start_hidden = False
    filtered_argv = [argv[0]] if argv else [sys.argv[0]]
    for arg in argv[1:]:
        if arg == "--background":
            start_hidden = True
            continue
        filtered_argv.append(arg)
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, Gio, Gtk
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

    from .services.daily_scheduler import DailyScheduler
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
        def __init__(self, *, background_launch: bool) -> None:
            super().__init__(application_id=APP_ID)
            self._background_launch = background_launch
            self._background_launch_consumed = False
            self._window: MainWindow | None = None
            self._background_hold_active = False
            self._scheduler = DailyScheduler(self, Path.cwd())
            self.connect("activate", self._on_activate)
            self.connect("startup", self._on_startup)

        def _on_startup(self, _app: Adw.Application) -> None:
            self._sync_background_runtime()

        def _on_activate(self, app: Adw.Application) -> None:
            self._sync_background_runtime()
            if self._background_launch and not self._background_launch_consumed:
                self._background_launch_consumed = True
                return
            self.show_main_window(app)

        def show_main_window(self, app: Adw.Application | None = None) -> None:
            if self._window is None:
                self._window = MainWindow(application=app or self)
            self._window.present()

        def _sync_background_runtime(self) -> None:
            settings = self._scheduler.backend().get_settings()
            if _is_flatpak_runtime() and bool(getattr(settings, "daily_content_enabled", False)):
                self._scheduler.start()
                if not self._background_hold_active:
                    self.hold()
                    self._background_hold_active = True
            else:
                self._scheduler.stop()
                if self._background_hold_active:
                    self.release()
                    self._background_hold_active = False

        def configure_daily_background(self, *, interactive: bool) -> tuple[bool | None, str]:
            settings = self._scheduler.backend().get_settings()
            if not _is_flatpak_runtime():
                self._sync_background_runtime()
                return None, _("Mensagens automáticas configuradas com sucesso.")

            granted: bool | None = None
            message = _("Mensagens automáticas configuradas com sucesso.")
            if interactive:
                granted, message = _request_flatpak_background_permission(
                    reason=_("Permitir notificações diárias mesmo sem a janela aberta"),
                    autostart=bool(getattr(settings, "daily_content_enabled", False)),
                    commandline=["/app/bin/bibliaroot", "--background"],
                )
                if granted is not None:
                    self._scheduler.backend().settings.update(daily_background_enabled=bool(granted))
            self._sync_background_runtime()
            return granted, message

        def handle_window_close(self, window: MainWindow) -> bool:
            settings = self._scheduler.backend().get_settings()
            if _is_flatpak_runtime() and bool(getattr(settings, "daily_content_enabled", False)):
                window.hide()
                self._sync_background_runtime()
                return True
            return False

        def background_status_text(self) -> str:
            if _is_flatpak_runtime():
                return self._scheduler.status_text()
            return _("Mensagens automáticas ativas neste dispositivo.")

    Adw.init()
    app = BibliaApplication(background_launch=start_hidden)
    return app.run(filtered_argv)
