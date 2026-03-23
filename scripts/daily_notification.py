from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.backend import BibleBackend
from app.constants import APP_ID, APP_NAME
from app.i18n import _, setup_i18n


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=_("Envia notificação de conteúdo diário do BíbliaRoot."))
    parser.add_argument(
        "--mode",
        choices=["verse", "study", "outline"],
        help=_("Sobrescreve o modo salvo nas configurações."),
    )
    parser.add_argument(
        "--print",
        action="store_true",
        dest="print_only",
        help=_("Apenas imprime o conteúdo no terminal (sem notify-send)."),
    )
    return parser.parse_args()


def main() -> int:
    setup_i18n()
    args = parse_args()
    backend = BibleBackend()
    settings = backend.get_settings()
    mode = args.mode or settings.daily_content_mode or "verse"
    chosen_translation = (getattr(settings, "daily_content_translation", "") or "").strip() or None

    if not args.print_only and not settings.daily_content_enabled:
        print(_("Conteúdo diário desativado nas configurações."))
        return 0

    content = backend.daily.generate(mode=mode, translation=chosen_translation, at_datetime=datetime.now())
    text = content.body.replace("\n", " ")
    delivery_mode = getattr(settings, "daily_delivery_mode", "native") or "native"

    if args.print_only:
        print(content.title)
        print(content.body)
        return 0

    sound_enabled = bool(getattr(settings, "daily_sound_enabled", False))
    sound_name = getattr(settings, "daily_sound_name", "soft") or "soft"
    try:
        if delivery_mode == "popup":
            _show_popup_window(
                title=content.title,
                body=content.body,
                persistent=bool(getattr(settings, "daily_notification_persistent", True)),
                sound_enabled=sound_enabled,
                sound_name=sound_name,
            )
        else:
            if sound_enabled:
                _play_sound_best_effort(sound_name)
            _send_native_notification(
                title=content.title,
                body=text,
                persistent=bool(getattr(settings, "daily_notification_persistent", True)),
            )
    except FileNotFoundError:
        print(_("notify-send não encontrado neste ambiente."))
        print(content.title)
        print(content.body)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f'{_("Falha ao enviar notificação")}: {exc}')
        print(content.title)
        print(content.body)
        return 1

    return 0


def _send_native_notification(*, title: str, body: str, persistent: bool) -> None:
    notify_base = _notify_send_command()
    cmd = [*notify_base, "-a", APP_NAME]
    if persistent:
        # Melhor esforço: alguns daemons ignoram -t 0 / hints.
        cmd.extend(["-u", "critical", "-t", "0"])
        cmd.extend(["-h", f"string:desktop-entry:{APP_ID}.desktop"])
        cmd.extend(["-h", "boolean:resident:true"])
        cmd.extend(["-h", "boolean:transient:false"])
    cmd.extend([title, body])
    subprocess.run(cmd, check=True, cwd=str(Path.home()))


def _show_popup_window(
    *,
    title: str,
    body: str,
    persistent: bool,
    sound_enabled: bool = False,
    sound_name: str = "soft",
) -> None:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk

    def estimate_popup_height(title_text: str, body_text: str) -> int:
        def count_lines(text: str, chars_per_line: int) -> int:
            total = 0
            for part in (text or "").splitlines() or [""]:
                length = max(1, len(part))
                total += max(1, (length + chars_per_line - 1) // chars_per_line)
            return total

        title_lines = count_lines(title_text, 42)
        body_lines = count_lines(body_text, 48)
        # Base + header + actions + line heights (mais compacto)
        height = 96 + (title_lines * 22) + (body_lines * 18)
        return max(180, min(620, height))

    class PopupApp(Adw.Application):
        def __init__(self) -> None:
            super().__init__(application_id=None)
            self._window: Adw.ApplicationWindow | None = None

        def do_activate(self) -> None:  # type: ignore[override]
            Adw.init()
            if self._window is None:
                popup_height = estimate_popup_height(title, body)
                self._window = Adw.ApplicationWindow(application=self)
                self._window.set_title(APP_NAME)
                self._window.set_default_size(420, popup_height)
                self._window.set_resizable(False)
                self._window.set_decorated(False)

                # Em Wayland/GTK4 o posicionamento absoluto é limitado; usamos um popup compacto
                # com visual de notificação. Em alguns ambientes ele abrirá próximo ao último foco.
                self._window.set_hide_on_close(True)

                css = Gtk.CssProvider()
                css.load_from_data(
                    """
                    window.popup-notice {
                      background: @window_bg_color;
                      border-radius: 16px;
                    }
                    .popup-shell {
                      border-radius: 16px;
                      border: 1px solid alpha(@accent_bg_color, 0.25);
                      background:
                        linear-gradient(180deg, alpha(@accent_bg_color, 0.08), alpha(@accent_bg_color, 0.03));
                    }
                    .popup-header {
                      padding: 8px 10px;
                      border-bottom: 1px solid alpha(@borders, 0.6);
                    }
                    .popup-title {
                      font-weight: 700;
                    }
                    .popup-body {
                      font-size: 14px;
                      line-height: 1.35;
                    }
                    .popup-meta {
                      opacity: 0.8;
                    }
                    """.encode("utf-8")
                )
                display = self._window.get_display()
                if display is not None:
                    Gtk.StyleContext.add_provider_for_display(
                        display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                    )
                self._window.add_css_class("popup-notice")

                outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                outer.add_css_class("popup-shell")

                header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                header.add_css_class("popup-header")
                header.set_margin_top(2)
                header.set_margin_start(2)
                header.set_margin_end(2)
                app_badge = Gtk.Label(label=APP_NAME, xalign=0)
                app_badge.add_css_class("popup-title")
                app_badge.add_css_class("accent")
                app_badge.set_hexpand(True)
                header.append(app_badge)

                header_meta = Gtk.Label(label=_("Conteúdo diário"), xalign=1)
                header_meta.add_css_class("dim-label")
                header_meta.add_css_class("popup-meta")
                header.append(header_meta)
                outer.append(header)

                content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
                content.set_margin_top(10)
                content.set_margin_bottom(10)
                content.set_margin_start(12)
                content.set_margin_end(12)

                title_label = Gtk.Label(label=title, xalign=0)
                title_label.add_css_class("heading")
                title_label.set_wrap(True)
                content.append(title_label)

                body_label = Gtk.Label(label=body, xalign=0)
                body_label.add_css_class("popup-body")
                body_label.set_wrap(True)
                body_label.set_selectable(True)
                body_label.set_hexpand(True)
                content.append(body_label)

                actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                actions.set_halign(Gtk.Align.END)
                actions.set_margin_top(2)
                copy_btn = Gtk.Button(label=_("Copiar"))
                close_btn = Gtk.Button(label=_("Fechar"))
                close_btn.add_css_class("suggested-action")

                def on_copy(*_args) -> None:
                    display = self._window.get_display() if self._window else None
                    if display is None:
                        return
                    display.get_clipboard().set_text(f"{title}\n{body}")

                def on_close(*_args) -> None:
                    self.quit()

                copy_btn.connect("clicked", on_copy)
                close_btn.connect("clicked", on_close)
                actions.append(copy_btn)
                actions.append(close_btn)
                content.append(actions)
                outer.append(content)

                self._window.set_content(outer)
                self._window.present()
                if sound_enabled:
                    played = _play_sound_best_effort(sound_name)
                    if not played:
                        try:
                            display = self._window.get_display()
                            if display is not None:
                                display.beep()
                        except Exception:
                            pass

                if not persistent:
                    GLib.timeout_add_seconds(8, self._timeout_close)
            else:
                self._window.present()

        def _timeout_close(self) -> bool:
            self.quit()
            return False

    PopupApp().run([])


def _play_sound_best_effort(sound_name: str) -> bool:
    sound_file = _sound_file_path(sound_name)
    custom_candidates = []
    if sound_file is not None and sound_file.exists():
        custom_candidates = [
            ["paplay", str(sound_file)],
            ["aplay", str(sound_file)],
        ]
    candidates = [
        *custom_candidates,
        ["canberra-gtk-play", "-i", _canberra_event_for_sound(sound_name)],
        ["paplay", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"],
        ["speaker-test", "-t", "sine", "-f", "880", "-l", "1"],
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            result = subprocess.run(
                cmd,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(Path.home()),
            )
            if result.returncode == 0:
                return True
        except Exception:
            continue
    return False


def _canberra_event_for_sound(sound_name: str) -> str:
    return {
        "soft": "message-new-instant",
        "bell": "bell-window-system",
        "alert": "dialog-warning",
    }.get(sound_name, "dialog-warning")


def _sound_file_path(sound_name: str) -> Path | None:
    filename_map = {
        "soft": "soft-beep.wav",
        "bell": "bell-beep.wav",
        "alert": "alert-beep.wav",
    }
    filename = filename_map.get(sound_name)
    if not filename:
        return None
    return ROOT / "resources" / "sounds" / filename


def _notify_send_command() -> list[str]:
    if shutil.which("notify-send"):
        return ["notify-send"]
    raise FileNotFoundError("notify-send")


if __name__ == "__main__":
    raise SystemExit(main())
