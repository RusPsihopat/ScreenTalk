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
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

import keyboard  # глобальные хоткеи; на Windows поверх игр нужны права администратора

import settings_store
from hotkey_state import HotkeyState
from chat_window import ChatWindow
from overlay import SelectionOverlay
from ocr_engine import image_to_text
from translator_engine import translate
from win_focus import force_foreground, is_admin
from single_instance import ensure_single_instance
from elevate import relaunch_as_admin


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


def main():
    # Повышение прав — до проверки "единственного экземпляра": если делать
    # наоборот, непривилегированный процесс успел бы создать мьютекс единственного
    # экземпляра и тут же завершиться при перезапуске с правами администратора,
    # создавая гонку, в которой новый (уже повышенный) процесс мог бы на долю
    # секунды увидеть чужой мьютекс ещё не освобождённым и ошибочно решить,
    # что программа уже запущена.
    if not is_admin():
        if relaunch_as_admin():
            sys.exit(0)
        # не получилось (или пользователь отклонил UAC) — продолжаем без
        # прав администратора, предупреждение об этом будет показано позже

    if not ensure_single_instance():
        sys.exit(0)  # уже запущен другой экземпляр — предупреждение уже показано

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

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
    # перетаскивание, на выходе ещё раз сохраняем текущие позиции обоих
    # окон. Важно: берём за основу ПОСЛЕДНИЕ СОХРАНЁННЫЕ настройки с диска
    # (а не текущие в памяти), иначе несохранённые кнопкой "Сохранить"
    # изменения в панели настроек тоже случайно записались бы на диск.
    def _save_positions_on_quit():
        saved = settings_store.load()
        saved["window_x"] = chat.x()
        saved["window_y"] = chat.y()
        if chat.settings_window is not None:
            saved["settings_window_x"] = chat.settings_window.x()
            saved["settings_window_y"] = chat.settings_window.y()
        settings_store.save(saved)

    app.aboutToQuit.connect(_save_positions_on_quit)

    chat.animate_show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
