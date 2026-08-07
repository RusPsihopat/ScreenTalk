"""Windows-специфичные помощники: принудительный захват фокуса, проверка
прав администратора, эвристика "активное окно похоже на игру в
полноэкранном режиме".
"""
import sys
import ctypes


def force_foreground(widget):
    """Windows по умолчанию не даёт фоновым процессам просто "забрать" фокус
    у активного окна (например, у игры) — это защита от программ, которые
    внезапно перехватывают клавиатуру/мышь. AttachThreadInput — штатный
    системный способ корректно обойти это ограничение.
    """
    widget.raise_()
    widget.activateWindow()

    if sys.platform != "win32":
        return

    try:
        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
        cur_thread = kernel32.GetCurrentThreadId()

        if fg_thread and fg_thread != cur_thread:
            user32.AttachThreadInput(fg_thread, cur_thread, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        if fg_thread and fg_thread != cur_thread:
            user32.AttachThreadInput(fg_thread, cur_thread, False)
    except Exception:
        pass  # если трюк не удался — окно всё равно уже показано штатно


def is_admin() -> bool:
    """Запущено ли приложение с правами администратора.

    Это важно для надёжности горячих клавиш: Windows использует UIPI (User
    Interface Privilege Isolation) и не позволяет процессу без прав
    администратора перехватывать ввод для окна, запущенного С правами
    администратора (а многие игры/античиты запускаются именно так). Если
    наше приложение не повышено, а игра — да, глобальный хук клавиатуры для
    этой игры работать не будет вообще, независимо от кода.
    """
    if sys.platform != "win32":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return True


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


def is_foreground_fullscreen() -> bool:
    """Грубая, но надёжная эвристика "окно переднего плана похоже на игру в
    полноэкранном режиме": занимает весь монитор целиком, без рамки.
    Используется для режима закрепления "поверх только игр".
    """
    if sys.platform != "win32":
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False

        rect = _RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False

        MONITOR_DEFAULTTONEAREST = 2
        monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)

        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False

        mon = info.rcMonitor
        return (rect.left <= mon.left and rect.top <= mon.top and
                rect.right >= mon.right and rect.bottom >= mon.bottom)
    except Exception:
        return False
