"""Автозапуск приложения при входе в Windows.

Через Планировщик задач (schtasks), а не через простой ключ реестра Run —
это единственный штатный способ запускать программу СРАЗУ с правами
администратора при входе в систему, без всплывающего окна UAC каждый раз.
Задача, созданная с флагом "/rl highest", получает повышенные права молча,
если пользователь — администратор.
"""
import sys
import os
import subprocess

_TASK_NAME = "GameTranslatorApp_Autostart"


def _startup_command() -> str:
    """Команда для запуска приложения при входе в систему."""
    if getattr(sys, "frozen", False):
        # собран в exe (например, PyInstaller) — исполняемый файл сам себе программа
        return f'"{sys.executable}"'

    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    # pythonw.exe — тот же Python, но без открывающегося окна консоли
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    exe = pythonw if os.path.exists(pythonw) else sys.executable
    return f'"{exe}" "{script_path}"'


def is_enabled() -> bool:
    """Зарегистрирован ли автозапуск в Планировщике задач прямо сейчас."""
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["schtasks", "/query", "/tn", _TASK_NAME],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def set_enabled(enabled: bool, run_as_admin: bool) -> bool:
    """Включает или выключает автозапуск. Возвращает True при успехе."""
    if sys.platform != "win32":
        return False
    try:
        if not enabled:
            subprocess.run(
                ["schtasks", "/delete", "/tn", _TASK_NAME, "/f"],
                capture_output=True, timeout=5,
            )
            return True

        args = [
            "schtasks", "/create", "/tn", _TASK_NAME,
            "/tr", _startup_command(), "/sc", "onlogon", "/f",
        ]
        if run_as_admin:
            args += ["/rl", "highest"]

        result = subprocess.run(args, capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False
