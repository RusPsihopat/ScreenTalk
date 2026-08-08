"""Перезапуск приложения с правами администратора при необходимости.

Горячие клавиши поверх игр, запущенных от администратора (а таких очень
много), надёжно работают только если наше приложение тоже с правами
администратора — иначе Windows (UIPI) просто не даёт перехватывать ввод.
Поэтому при обычном запуске без прав администратора сразу же предлагается
повышение через штатное окно UAC.
"""
import sys
import ctypes


def relaunch_as_admin() -> bool:
    """Пытается перезапустить процесс с правами администратора.

    Возвращает True, если перезапуск успешно запущен — тогда вызывающий код
    должен сразу завершить текущий (непривилегированный) процесс. Возвращает
    False, если не получилось (например, пользователь отклонил запрос UAC) —
    тогда стоит продолжить работу без прав администратора.
    """
    if sys.platform != "win32":
        return False
    try:
        if getattr(sys, "frozen", False):
            # собран в exe (например, PyInstaller) — исполняемый файл сам себе программа
            executable = sys.executable
            params = " ".join(f'"{a}"' for a in sys.argv[1:])
        else:
            executable = sys.executable
            params = " ".join(f'"{a}"' for a in sys.argv)

        # SW_SHOWNORMAL = 1; "runas" — вызывает штатное окно запроса UAC
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, params, None, 1)
        return result > 32  # > 32 означает успешный запуск, по документации WinAPI
    except Exception:
        return False
