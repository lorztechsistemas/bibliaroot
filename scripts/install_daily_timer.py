from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.backend import BibleBackend
from app.constants import APP_NAME, DAILY_TIMER_NAME

SERVICE_NAME = DAILY_TIMER_NAME


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Instala/remove timer de conteúdo diário do {APP_NAME} (systemd user).")
    parser.add_argument("--disable", action="store_true", help="Desativa e remove o timer do usuário.")
    parser.add_argument("--time", help="Horário HH:MM para execução diária.")
    parser.add_argument("--end-time", help="Horário final HH:MM da janela diária.")
    parser.add_argument("--mode", choices=["verse", "study", "outline"], help="Modo do conteúdo diário.")
    parser.add_argument("--count", type=int, help="Quantidade de mensagens por dia.")
    parser.add_argument("--interval", type=int, help="Intervalo em minutos entre mensagens.")
    return parser.parse_args()


def systemd_user_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


def _is_flatpak_runtime() -> bool:
    return bool(os.getenv("FLATPAK_ID", "").strip())


def _build_daily_times(start_hhmm: str, count: int, interval_minutes: int) -> list[str]:
    # Compatibilidade: gera "count" horários a partir de um início e intervalo.
    hh, mm = [int(x) for x in start_hhmm.split(":", 1)]
    start_total = hh * 60 + mm
    times: list[str] = []
    for i in range(max(1, count)):
        minute_of_day = (start_total + i * max(1, interval_minutes)) % (24 * 60)
        h = minute_of_day // 60
        m = minute_of_day % 60
        times.append(f"{h:02d}:{m:02d}")
    return times


def _build_daily_times_window(start_hhmm: str, end_hhmm: str, interval_minutes: int) -> list[str]:
    return BibleBackend._build_schedule_times(start_hhmm, end_hhmm, interval_minutes)


def write_units(
    project_root: Path,
    time_hhmm: str,
    end_time_hhmm: str,
    count: int,
    interval_minutes: int,
) -> tuple[Path, Path]:
    exec_cmd, working_directory_line = _build_service_exec(project_root)
    service_filename = f"{SERVICE_NAME}.service"
    timer_filename = f"{SERVICE_NAME}.timer"

    service_content = f"""[Unit]
Description=BibliaRoot Conteudo Diario
After=graphical-session.target
Wants=graphical-session.target

[Service]
Type=oneshot
{working_directory_line}
ExecStart={exec_cmd}
"""

    times = _build_daily_times_window(time_hhmm, end_time_hhmm, interval_minutes)
    if not times:
        times = _build_daily_times(time_hhmm, count, interval_minutes)
    on_calendar_lines = "\n".join(f"OnCalendar=*-*-* {t}:00" for t in times)

    timer_content = f"""[Unit]
Description=Timer de Conteudo Diario do BibliaRoot

[Timer]
{on_calendar_lines}
Persistent=true
Unit={SERVICE_NAME}.service

[Install]
WantedBy=timers.target
"""

    if _is_flatpak_runtime():
        raise RuntimeError("Agendamento diário não é suportado na edição Flatpak sandboxed.")

    unit_dir = systemd_user_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    service_path = unit_dir / service_filename
    timer_path = unit_dir / timer_filename
    service_path.write_text(service_content, encoding="utf-8")
    timer_path.write_text(timer_content, encoding="utf-8")
    return service_path, timer_path


def _build_service_exec(project_root: Path) -> tuple[str, str]:
    flatpak_id = os.getenv("FLATPAK_ID", "").strip()
    if flatpak_id:
        raise RuntimeError("Agendamento diário não é suportado na edição Flatpak sandboxed.")

    script_path = project_root / "scripts" / "daily_notification.py"
    exec_cmd = f"/usr/bin/env python3 {shlex.quote(str(script_path))}"
    return exec_cmd, f"WorkingDirectory={project_root}"


def run_systemctl(*args: str) -> subprocess.CompletedProcess:
    base_cmd = _systemctl_user_command()
    return subprocess.run(
        [*base_cmd, *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path.home()),
    )


def _systemctl_user_command() -> list[str]:
    if shutil.which("systemctl"):
        return ["systemctl", "--user"]
    raise FileNotFoundError("systemctl")


def import_graphical_environment() -> None:
    # Importa variáveis da sessão atual para o user manager do systemd, necessárias para notify-send.
    vars_to_import = [
        "DISPLAY",
        "WAYLAND_DISPLAY",
        "XAUTHORITY",
        "DBUS_SESSION_BUS_ADDRESS",
        "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_TYPE",
    ]
    subprocess.run(
        [*_systemctl_user_command(), "import-environment", *vars_to_import],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path.home()),
    )


def main() -> int:
    args = parse_args()
    backend = BibleBackend()
    settings = backend.get_settings()

    if args.disable:
        if _is_flatpak_runtime():
            print("Agendamento diário não é suportado na edição Flatpak sandboxed.")
            return 1
        try:
            run_systemctl("disable", "--now", f"{SERVICE_NAME}.timer")
        except FileNotFoundError:
            print("systemctl não encontrado. Execute a versão local do app em um Linux com systemd --user.")
            return 1
        unit_dir = systemd_user_dir()
        for path in (unit_dir / f"{SERVICE_NAME}.service", unit_dir / f"{SERVICE_NAME}.timer"):
            if path.exists():
                path.unlink()
        run_systemctl("daemon-reload")
        backend.set_daily_content_settings(enabled=False)
        print("Timer diário desativado.")
        return 0

    chosen_mode = args.mode or settings.daily_content_mode or "verse"
    chosen_time = args.time or settings.daily_content_time or "08:00"
    chosen_end_time = args.end_time or getattr(settings, "daily_content_end_time", chosen_time) or chosen_time
    chosen_count = args.count or int(getattr(settings, "daily_messages_per_day", 1) or 1)
    chosen_interval = args.interval or int(getattr(settings, "daily_interval_minutes", 180) or 180)
    backend.set_daily_content_settings(
        enabled=True,
        mode=chosen_mode,
        time_str=chosen_time,
        end_time_str=chosen_end_time,
        messages_per_day=chosen_count,
        interval_minutes=chosen_interval,
    )

    project_root = Path(__file__).resolve().parents[1]
    write_units(project_root, chosen_time, chosen_end_time, chosen_count, chosen_interval)
    import_graphical_environment()

    try:
        commands = [
            ("daemon-reload",),
            ("enable", "--now", f"{SERVICE_NAME}.timer"),
        ]
        for command in commands:
            result = run_systemctl(*command)
            if result.returncode != 0:
                print("Falha em systemctl --user", " ".join(command))
                if result.stderr:
                    print(result.stderr.strip())
                return 1
    except FileNotFoundError:
        print(
            "systemctl não encontrado neste ambiente. "
            "Este recurso exige Linux com systemd --user fora do sandbox do Flatpak."
        )
        return 1
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(
        f"Timer diário ativado: {chosen_time} até {chosen_end_time} ({chosen_mode}) | "
        f"intervalo {chosen_interval} min."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
