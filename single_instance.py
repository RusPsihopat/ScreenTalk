"""Не позволяет запустить второй экземпляр приложения одновременно.

Использует именованный Windows-мьютекс: если он уже существует — значит,
где-то уже запущен другой экземпляр этого же приложения. Хэндл мьютекса
специально не закрывается — он живёт всё время работы процесса и
освобождается автоматически, когда процесс завершается (штатно или нет).
"""
import sys
import ctypes

_MUTEX_NAME = "Local\\GameTranslatorApp_SingleInstance_Mutex"

_mutex_handle = None  # держим ссылку, чтобы хэндл не был собран сборщиком мусора


def ensure_single_instance() -> bool:
    """Возвращает True, если это единственный запущенный экземпляр.

    Если уже запущен другой экземпляр — показывает предупреждение и
    возвращает False; вызывающий код должен в этом случае сразу завершить
    работу, не создавая окна и не занимая горячие клавиши.
    """
    global _mutex_handle

    if sys.platform != "win32":
        return True  # проверка реализована только для Windows

    kernel32 = ctypes.windll.kernel32
    ERROR_ALREADY_EXISTS = 183

    _mutex_handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    already_running = (kernel32.GetLastError() == ERROR_ALREADY_EXISTS)

    if already_running:
        MB_OK = 0x0
        MB_ICONINFORMATION = 0x40
        MB_TOPMOST = 0x40000
        ctypes.windll.user32.MessageBoxW(
            0,
            "Переводчик уже запущен — смотрите значок в системном трее.",
            "Переводчик",
            MB_OK | MB_ICONINFORMATION | MB_TOPMOST,
        )
        return False

    return True
