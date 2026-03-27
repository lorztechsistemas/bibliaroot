from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import time

from gi.repository import Gio, GLib

from app.constants import APP_NAME
from app.i18n import _
from app.services.backend import BibleBackend


class DailyScheduler:
    def __init__(self, application: Gio.Application, project_root: Path) -> None:
        self._application = application
        self._project_root = project_root
        self._backend = BibleBackend()
        self._source_id: int | None = None
        self._delivered_keys: set[str] = set()

    def backend(self) -> BibleBackend:
        return self._backend

    def start(self) -> None:
        if self._source_id is None:
            self._source_id = GLib.timeout_add_seconds(20, self._tick)
        self._tick()

    def stop(self) -> None:
        if self._source_id is not None:
            GLib.source_remove(self._source_id)
            self._source_id = None

    def is_running(self) -> bool:
        return self._source_id is not None

    def _tick(self) -> bool:
        settings = self._backend.get_settings()
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        self._delivered_keys = {key for key in self._delivered_keys if key.startswith(today_prefix)}
        if not bool(getattr(settings, "daily_content_enabled", False)):
            return True
        current_hhmm = datetime.now().strftime("%H:%M")
        for scheduled_hhmm in self._backend.compute_daily_schedule_times(settings):
            if scheduled_hhmm != current_hhmm:
                continue
            delivery_key = f"{today_prefix} {scheduled_hhmm}"
            if delivery_key in self._delivered_keys:
                continue
            self._delivered_keys.add(delivery_key)
            self._deliver_now()
        return True

    def _deliver_now(self) -> None:
        settings = self._backend.get_settings()
        if getattr(settings, "daily_delivery_mode", "native") == "popup":
            self._spawn_daily_notification_script()
            return

        chosen_translation = (getattr(settings, "daily_content_translation", "") or "").strip() or None
        content = self._backend.daily.generate(
            mode=settings.daily_content_mode or "verse",
            translation=chosen_translation,
            at_datetime=datetime.now(),
        )
        if bool(getattr(settings, "daily_sound_enabled", False)):
            self._play_sound_best_effort(getattr(settings, "daily_sound_name", "soft") or "soft")
        notification = Gio.Notification.new(content.title)
        notification.set_body(content.body)
        notification.set_priority(Gio.NotificationPriority.URGENT)
        self._application.send_notification(f"daily-{int(time.time())}", notification)

    def _spawn_daily_notification_script(self) -> None:
        script = self._project_root / "scripts" / "daily_notification.py"
        subprocess.Popen(
            [sys.executable, str(script)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(self._project_root),
        )

    def _play_sound_best_effort(self, sound_name: str) -> bool:
        sound_file = self._sound_file_path(sound_name)
        custom_candidates = []
        if sound_file is not None and sound_file.exists():
            custom_candidates = [
                ["paplay", str(sound_file)],
                ["aplay", str(sound_file)],
            ]
        candidates = [
            *custom_candidates,
            ["canberra-gtk-play", "-i", self._canberra_event_for_sound(sound_name)],
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

    def _canberra_event_for_sound(self, sound_name: str) -> str:
        return {
            "soft": "message-new-instant",
            "bell": "bell-window-system",
            "alert": "dialog-warning",
        }.get(sound_name, "dialog-warning")

    def _sound_file_path(self, sound_name: str) -> Path | None:
        filename_map = {
            "soft": "soft-beep.wav",
            "bell": "bell-beep.wav",
            "alert": "alert-beep.wav",
        }
        filename = filename_map.get(sound_name)
        if not filename:
            return None
        return self._project_root / "resources" / "sounds" / filename

    def status_text(self) -> str:
        settings = self._backend.get_settings()
        schedule_times = self._backend.compute_daily_schedule_times(settings)
        active = _("ativas") if settings.daily_content_enabled else _("desativadas")
        next_text = ", ".join(schedule_times[:6]) if schedule_times else _("nenhum horário definido")
        if len(schedule_times) > 6:
            next_text += ", ..."
        delivery_text = (
            _("abertura automática habilitada")
            if bool(getattr(settings, "daily_background_enabled", False))
            else _("abertura automática pode depender das permissões do sistema")
        )
        return f'{_("Mensagens automáticas")}: {active} | {_("Horários")}: {next_text} | {delivery_text}'
