"""Точка входа: системный трей + глобальные горячие клавиши.

По умолчанию:
ё (клавиша слева от "1")     — выделить область экрана и перевести
                                (работает всегда, даже если окно чата скрыто)
Ctrl+ё                        — показать/скрыть окно чата

Обе комбинации можно поменять прямо в приложении: кнопка ⚙ в окне чата.
Клавиши ловятся по физическому скан-коду, а не по имени — это надёжно
работает независимо от раскладки клавиатуры.
"""
import sys
import numpy as np

from PySide6.QtCore import QObject, Signal, QThread, QTimer
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PySide6.QtNetwork import QLocalServer, QLocalSocket

import keyboard  # глобальные хоткеи; на Windows поверх игр нужны права администратора

import settings_store
from hotkey_state import HotkeyState
from chat_window import ChatWindow
from overlay import SelectionOverlay
from ocr_engine import image_to_text
from translator_engine import translate
from win_focus import force_foreground, is_admin


class HotkeyBridge(QObject):
    """Мост между потоком библиотеки keyboard и главным Qt-потоком:
    keyboard дёргает хоткеи в своём потоке, а Qt-виджеты можно создавать
    только в главном, поэтому хоткей просто эмитит сигнал."""
    capture_requested = Signal()
    toggle_requested = Signal()


class OcrTranslateThread(QThread):
    """OCR + перевод выполняются в фоне, чтобы окно не подвисало на пару
    секунд во время запроса к OCR.space и переводчику."""
    done = Signal(str, str)  # original, translated

    def __init__(self, image: np.ndarray):
        super().__init__()
        self.image = image

    def run(self):
        try:
            text = image_to_text(self.image)
            if not text:
                self.done.emit("", "")
                return
            _, _, translated = translate(text)
        except Exception:
            self.done.emit(
                "⚠ Ошибка",
                "Не удалось распознать текст или перевести — проверьте интернет-соединение",
            )
            return
        self.done.emit(text, translated)


def _combo_matches(combo: dict, ctrl: bool, alt: bool, shift: bool) -> bool:
    return combo["ctrl"] == ctrl and combo["alt"] == alt and combo["shift"] == shift


_SINGLE_INSTANCE_KEY = "translator_app_single_instance_guard"


def _acquire_single_instance_lock():
    """Проверяет, не запущен ли уже другой экземпляр программы.

    Возвращает QLocalServer, который нужно держать живым до конца работы
    программы (иначе его удалит сборщик мусора и проверка перестанет
    действовать), либо None, если другой экземпляр уже запущен и работает.
    """
    probe = QLocalSocket()
    probe.connectToServer(_SINGLE_INSTANCE_KEY)
    already_running = probe.waitForConnected(200)
    probe.close()

    if already_running:
        return None

    # Если предыдущий процесс завершился аварийно, на Linux/macOS на диске
    # может остаться "зависший" файл сокета — раз подключиться выше не
    # удалось, значит другого живого экземпляра нет и файл точно можно
    # удалить перед тем, как начать слушать самим.
    QLocalServer.removeServer(_SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(_SINGLE_INSTANCE_KEY)
    return server


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    single_instance_server = _acquire_single_instance_lock()
    if single_instance_server is None:
        QMessageBox.warning(
            None,
            "Переводчик",
            "Программа уже запущена. Ищите её значок в системном трее.",
        )
        sys.exit(0)
    # держим ссылку на объект — иначе сборщик мусора его удалит и сервер
    # перестанет слушать, и проверка выше перестанет работать
    app._single_instance_server = single_instance_server

    settings = settings_store.load()
    hotkeys = HotkeyState(settings["capture_hotkey"], settings["toggle_hotkey"])
    # пока True — обработчик глобальных хоткеев ничего не делает (нужно на
    # время записи новой комбинации в окне настроек, чтобы старая комбинация
    # случайно не сработала прямо во время записи новой)
    suspend_flag = {"active": False}

    chat = ChatWindow(hotkeys, suspend_flag, settings)
    bridge = HotkeyBridge()
    chat._ocr_threads = []  # держим ссылки, чтобы фоновые потоки не удалило сборщиком мусора

    def start_capture():
        overlay = SelectionOverlay()

        def on_area(img: np.ndarray):
            chat.show_ocr_spinner()
            thread = OcrTranslateThread(img)

            def on_done(original, translated):
                chat.hide_ocr_spinner()
                if original:
                    chat.add_translated_pair(original, translated, play_sound=True)
                chat._ocr_threads.remove(thread)

            thread.done.connect(on_done)
            chat._ocr_threads.append(thread)
            thread.start()

        overlay.area_selected.connect(on_area)
        overlay.showFullScreen()
        force_foreground(overlay)
        # держим ссылку, чтобы объект не удалило сборщиком мусора раньше времени
        chat._active_overlay = overlay

    def toggle_chat():
        if chat.isVisible():
            chat.animate_hide()
        else:
            chat.animate_show()

    bridge.capture_requested.connect(start_capture)
    bridge.toggle_requested.connect(toggle_chat)
    chat.quit_requested.connect(app.quit)

    # Ловим целевые клавиши по скан-коду напрямую (не по имени), чтобы не
    # зависеть от раскладки и от того, как Windows называет эту клавишу.
    # hotkeys.capture / hotkeys.toggle читаются заново при каждом нажатии —
    # если пользователь поменяет комбинацию в настройках, новая начинает
    # действовать сразу, без перезапуска приложения.
    _held_scan_codes = set()

    def on_key_event(event):
        if suspend_flag["active"]:
            return  # идёт запись новой комбинации в окне настроек

        sc = event.scan_code
        if sc not in (hotkeys.capture["scan_code"], hotkeys.toggle["scan_code"]):
            return

        if event.event_type == keyboard.KEY_DOWN:
            if sc in _held_scan_codes:
                return  # игнорируем автоповтор при удержании клавиши
            _held_scan_codes.add(sc)

            ctrl = keyboard.is_pressed('ctrl')
            alt = keyboard.is_pressed('alt')
            shift = keyboard.is_pressed('shift')

            if sc == hotkeys.toggle["scan_code"] and _combo_matches(hotkeys.toggle, ctrl, alt, shift):
                bridge.toggle_requested.emit()
            elif sc == hotkeys.capture["scan_code"] and _combo_matches(hotkeys.capture, ctrl, alt, shift):
                bridge.capture_requested.emit()  # работает всегда, даже если окно чата скрыто

        elif event.event_type == keyboard.KEY_UP:
            _held_scan_codes.discard(sc)

    keyboard.hook(on_key_event)

    # Самовосстановление: в редких случаях системный хук может не доставить
    # событие KEY_UP (например, если фокус резко перехватила игра) — тогда
    # клавиша "залипает" в _held_scan_codes и хоткей перестаёт срабатывать
    # до перезапуска. Эта проверка раз в 2 секунды сама снимает залипание.
    def _cleanup_stuck_keys():
        for sc in list(_held_scan_codes):
            if not keyboard.is_pressed(sc):
                _held_scan_codes.discard(sc)

    cleanup_timer = QTimer()
    cleanup_timer.setInterval(2000)
    cleanup_timer.timeout.connect(_cleanup_stuck_keys)
    cleanup_timer.start()

    # значок в системном трее
    tray = QSystemTrayIcon()
    tray.setIcon(QIcon.fromTheme("accessories-dictionary"))
    tray.setToolTip("Переводчик")

    menu = QMenu()
    show_action = QAction("Показать/скрыть чат")
    show_action.triggered.connect(toggle_chat)
    capture_action = QAction("Выделить область экрана")
    capture_action.triggered.connect(start_capture)
    quit_action = QAction("Выход")
    quit_action.triggered.connect(app.quit)

    menu.addAction(show_action)
    menu.addAction(capture_action)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()

    # Предупреждаем, если приложение запущено без прав администратора: в
    # таком случае Windows (UIPI) не даст перехватывать клавиши поверх игр,
    # запущенных С правами администратора — а это многие игры и античиты.
    if not is_admin():
        tray.showMessage(
            "Переводчик",
            "Запущено без прав администратора. Если игра запущена от "
            "администратора (или с античитом), горячие клавиши поверх неё "
            "могут не работать. Для надёжности перезапустите main.py от "
            "имени администратора.",
            QSystemTrayIcon.MessageIcon.Warning,
            8000,
        )

    # Подстраховка: на случай, если окно было перемещено не через обычное
    # перетаскивание (например, программно), на выходе ещё раз сохраняем
    # текущие позиции обоих окон — так они точно не потеряются даже при
    # полном закрытии программы.
    def _save_positions_on_quit():
        chat.settings["window_x"] = chat.x()
        chat.settings["window_y"] = chat.y()
        if chat.settings_window is not None:
            chat.settings["settings_window_x"] = chat.settings_window.x()
            chat.settings["settings_window_y"] = chat.settings_window.y()
        chat._persist_positions()

    app.aboutToQuit.connect(_save_positions_on_quit)

    chat.animate_show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
