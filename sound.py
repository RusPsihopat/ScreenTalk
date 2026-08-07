"""Звуковой сигнал уведомления — например, когда перевод текста с экрана
готов, чтобы не приходилось постоянно поглядывать в окно чата."""
import sys


def play_notification():
    if sys.platform != "win32":
        return
    try:
        import winsound
        # "Notification.Default" — стандартный звук уведомлений современного
        # Windows (10/11), играется асинхронно, чтобы не задерживать поток
        winsound.PlaySound("Notification.Default", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        pass  # не критично, если звук не проигрался (например, нет звуковых устройств)
