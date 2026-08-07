"""Главное окно — минималистичный полупрозрачный чат с переводом."""
import re

from PySide6.QtCore import Qt, QThread, Signal, QPoint, QTimer
from PySide6.QtGui import QGuiApplication, QPainter, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QScrollArea, QFrame, QSizePolicy
)

from config import WINDOW_WIDTH, WINDOW_HEIGHT, VOICE_DEFAULT_LANG
from translator_engine import translate
from speech_engine import Recorder, transcribe, transcribe_auto
from win_focus import force_foreground, is_foreground_fullscreen
from settings_window import SettingsWindow
from settings_store import save_keys as save_settings_keys
from ui_kit import IconButton, SpinnerDots, fade_in_widget, show_animated, hide_animated
from confirm_dialog import ConfirmDialog


# ---------- фоновые потоки, чтобы UI не подвисал ----------

class TranslateThread(QThread):
    done = Signal(str, str, str, str)  # original, src, dst, translated

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):
        try:
            src, dst, translated = translate(self.text)
        except Exception:
            src, dst, translated = "", "", "⚠ Ошибка перевода — проверьте интернет"
        self.done.emit(self.text, src, dst, translated)


class TranscribeThread(QThread):
    done = Signal(str)

    def __init__(self, audio, language):
        super().__init__()
        self.audio = audio
        self.language = language

    def run(self):
        try:
            if self.language == "AUTO":
                text, _detected = transcribe_auto(self.audio)
            else:
                text = transcribe(self.audio, self.language)
        except Exception:
            text = ""
        self.done.emit(text)


# ---------- поле ввода: Enter — отправить, Shift+Enter — перенос строки ----------

class ChatInput(QTextEdit):
    send_requested = Signal()

    def keyPressEvent(self, event):
        is_enter = event.key() in (Qt.Key_Return, Qt.Key_Enter)
        if is_enter and not (event.modifiers() & Qt.ShiftModifier):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


# ---------- микрофон с удержанием (push-to-talk) ----------

class MicButton(IconButton):
    press_started = Signal()
    press_released = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.press_started.emit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.press_released.emit()
        super().mouseReleaseEvent(event)


# ---------- индикатор уровня голоса при записи (как волна в Telegram) ----------

class VoiceLevelWidget(QWidget):
    BAR_COUNT = 20

    def __init__(self):
        super().__init__()
        self.setFixedHeight(40)
        self._history = [0.02] * self.BAR_COUNT

    def push_level(self, level: float):
        self._history.pop(0)
        self._history.append(max(0.05, min(level, 1.0)))
        self.update()

    def reset(self):
        self._history = [0.02] * self.BAR_COUNT
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        w, h = self.width(), self.height()
        gap = 3
        bar_w = max(2.0, (w - gap * (self.BAR_COUNT - 1)) / self.BAR_COUNT)

        x = 0.0
        for lvl in self._history:
            bar_h = max(3.0, lvl * h)
            y = (h - bar_h) / 2
            painter.setBrush(QColor(255, 90, 90))
            painter.drawRoundedRect(x, y, bar_w, bar_h, 2, 2)
            x += bar_w + gap


# ---------- перенос длинных "слов" без пробелов (пути, ссылки, хэши) ----------

_LONG_RUN_RE = re.compile(r'\S{25,}')
_ZWSP = "\u200b"  # невидимый пробел — не меняет то, что видно на экране,
                  # но даёт Qt разрешение перенести строку в этом месте


def _make_wrappable(text: str) -> str:
    """Без этого QLabel с wordWrap(True) переносит строку только по
    обычным пробелам. Длинное "слово" без единого пробела — например,
    Windows-путь вроде C:\\Users\\...\\site-packages или длинная ссылка —
    Qt перенести не может и просто раздвигает пузырёк сообщения шире
    окна чата, из-за чего внизу появляется горизонтальный ползунок.

    Подставляем невидимый \u200b после привычных разделителей (\\, /, _,
    -, ., которые не влияют на пробелы, поэтому копирование текста в
    буфер обмена ими не испорчено — copy_btn копирует исходный
    translated_text, а не то, что показано на экране) внутри длинных
    "слов", а если внутри такого куска разделителей всё равно не
    нашлось (например, длинный хэш), режем его принудительно каждые 20
    символов, чтобы у Qt точно был выбор, где перенести строку.
    """
    def _break_long_run(match: "re.Match") -> str:
        run = match.group(0)
        run = re.sub(r'([\\/_\-.,;:])', r'\1' + _ZWSP, run)
        pieces = run.split(_ZWSP)
        pieces = [
            _ZWSP.join(p[i:i + 20] for i in range(0, len(p), 20)) if len(p) > 20 else p
            for p in pieces
        ]
        return _ZWSP.join(pieces)

    return _LONG_RUN_RE.sub(_break_long_run, text)


# ---------- один "пузырёк" сообщения (оригинал + перевод + копировать) ----------

class MessageBubble(QFrame):
    def __init__(self, original: str, translated: str, scale: float = 1.0):
        super().__init__()
        self.translated_text = translated
        self.setObjectName("bubble")
        layout = QVBoxLayout(self)
        m = round(10 * scale)
        layout.setContentsMargins(m, round(8 * scale), m, round(8 * scale))
        layout.setSpacing(round(4 * scale))

        # оригинал — приглушённый, мелкий, курсивом: явно вспомогательный текст
        orig_label = QLabel(_make_wrappable(original))
        orig_label.setWordWrap(True)
        orig_label.setStyleSheet(f"color: #75797f; font-size: {round(11*scale)}px; font-style: italic;")

        row = QHBoxLayout()
        # перевод — крупный, жирный, белый: это то, ради чего открыт чат
        tr_label = QLabel(_make_wrappable(translated))
        tr_label.setWordWrap(True)
        tr_label.setStyleSheet(f"color: #ffffff; font-size: {round(15*scale)}px; font-weight: 600;")
        tr_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.copy_btn = IconButton("copy", size=round(22 * scale))
        self.copy_btn.setToolTip("Скопировать перевод")
        self.copy_btn.clicked.connect(self._on_copy_clicked)

        self.copied_label = QLabel("Скопировано")
        self.copied_label.setStyleSheet(f"color: #3ddc84; font-size: {round(10*scale)}px;")
        self.copied_label.hide()

        row.addWidget(tr_label)
        row.addWidget(self.copied_label)
        row.addWidget(self.copy_btn)

        layout.addWidget(orig_label)
        layout.addLayout(row)

        self.setStyleSheet(f"#bubble {{background: rgba(255,255,255,18); border-radius: {round(10*scale)}px;}}")

    def _on_copy_clicked(self):
        QGuiApplication.clipboard().setText(self.translated_text)
        self.copy_btn.set_icon("check")
        self.copied_label.show()
        QTimer.singleShot(1500, self._revert_copy)

    def _revert_copy(self):
        self.copy_btn.set_icon("copy")
        self.copied_label.hide()


# ---------- главное окно ----------

class ChatWindow(QWidget):
    quit_requested = Signal()

    PIN_ORDER = ["always", "games", "normal"]
    PIN_ICON = {"always": "pin_always", "games": "pin_games", "normal": "pin_normal"}
    PIN_TOOLTIP = {
        "always": "Закрепление: всегда поверх окон (нажмите, чтобы сменить)",
        "games": "Закрепление: только поверх игр в полноэкранном режиме (нажмите, чтобы сменить)",
        "normal": "Закрепление: обычное окно, без поверх других (нажмите, чтобы сменить)",
    }

    def __init__(self, hotkeys, suspend_flag, settings: dict):
        super().__init__()
        self.hotkeys = hotkeys
        self.suspend_flag = suspend_flag
        self.settings = settings
        self.settings_window = None  # создаётся лениво при первом открытии
        self.history = []  # [(original, translated), ...] — для перестройки при смене масштаба

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(max(settings["opacity_percent"], 1) / 100)

        if settings.get("window_x") is not None and settings.get("window_y") is not None:
            self.move(settings["window_x"], settings["window_y"])

        self._drag_pos = QPoint()
        self._dragging = False
        self._recorder = Recorder()
        self._is_recording = False
        self._record_start_time = 0.0
        self._voice_lang = VOICE_DEFAULT_LANG  # "AUTO", "ru-RU" или "en-US"

        self._level_timer = QTimer(self)
        self._level_timer.setInterval(40)
        self._level_timer.timeout.connect(self._poll_level)

        self._pin_poll_timer = QTimer(self)
        self._pin_poll_timer.setInterval(700)
        self._pin_poll_timer.timeout.connect(self._poll_pin_games)

        self._build_ui()
        self.resize(self._scaled(WINDOW_WIDTH), self._scaled(WINDOW_HEIGHT))
        self._apply_pin_mode()

    def _scale_factor(self):
        return self.settings.get("ui_scale", 100) / 100.0

    def _scaled(self, px):
        return round(px * self._scale_factor())

    # ---- UI ----
    def _build_ui(self):
        s = self._scale_factor()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        container = QFrame()
        container.setObjectName("container")
        container.setStyleSheet(f"#container {{background-color: #1e1f22; border-radius: {round(14*s)}px;}}")
        outer.addWidget(container)

        main = QVBoxLayout(container)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # заголовок (перетаскивание окна + закрепление + настройки + закрытие)
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(round(12*s), round(8*s), round(8*s), round(4*s))
        title = QLabel("Переводчик")
        title.setStyleSheet(f"color: #9aa0a6; font-size: {round(12*s)}px; font-weight: 600;")

        self.pin_btn = IconButton(self.PIN_ICON[self.settings["pin_mode"]], size=round(22*s))
        self.pin_btn.setToolTip(self.PIN_TOOLTIP[self.settings["pin_mode"]])
        self.pin_btn.clicked.connect(self._cycle_pin_mode)

        self.settings_btn = IconButton("settings", size=round(22*s))
        self.settings_btn.setToolTip("Настройки")
        self.settings_btn.clicked.connect(self._open_settings)

        self.minimize_btn = IconButton("minimize", size=round(22*s))
        self.minimize_btn.setToolTip("Свернуть в трей")
        self.minimize_btn.clicked.connect(self.animate_hide)

        self.close_btn = IconButton("close", size=round(22*s))
        self.close_btn.setToolTip("Закрыть")
        self.close_btn.clicked.connect(self._on_close_clicked)

        title_bar.addWidget(title)
        title_bar.addStretch()
        title_bar.addWidget(self.pin_btn)
        title_bar.addWidget(self.settings_btn)
        title_bar.addWidget(self.minimize_btn)
        title_bar.addWidget(self.close_btn)
        main.addLayout(title_bar)

        # строка статуса OCR (спиннер + подпись), видна только во время распознавания
        ocr_row = QHBoxLayout()
        ocr_row.setContentsMargins(round(12*s), 0, round(12*s), 0)
        self.ocr_spinner = SpinnerDots()
        self.ocr_spinner.hide()
        self.ocr_label = QLabel("Распознаю экран…")
        self.ocr_label.setStyleSheet(f"color: #9aa0a6; font-size: {round(11*s)}px;")
        self.ocr_label.hide()
        ocr_row.addWidget(self.ocr_spinner)
        ocr_row.addWidget(self.ocr_label)
        ocr_row.addStretch()
        main.addLayout(ocr_row)

        # лента сообщений
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea {border: none; background: transparent;}")
        self.messages_container = QWidget()
        self.messages_container.setStyleSheet("background: transparent;")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.addStretch()
        self.messages_layout.setSpacing(round(8*s))
        self.messages_layout.setContentsMargins(round(10*s), round(4*s), round(10*s), round(4*s))
        self.scroll.setWidget(self.messages_container)
        # автоскролл вниз при любом изменении размера ленты (новое сообщение,
        # изменение масштаба и т.д.) — самый надёжный способ в Qt, не зависит
        # от таймингов пересчёта разметки
        self.scroll.verticalScrollBar().rangeChanged.connect(
            lambda _mn, mx: self.scroll.verticalScrollBar().setValue(mx)
        )
        main.addWidget(self.scroll, 1)

        # нижняя панель ввода
        bottom = QHBoxLayout()
        bottom.setContentsMargins(round(10*s), round(8*s), round(10*s), round(10*s))
        bottom.setSpacing(round(6*s))

        self.input = ChatInput()
        self.input.setFixedHeight(round(40*s))
        self.input.setPlaceholderText("Введите текст... (Enter — отправить, Shift+Enter — новая строка)")
        self.input.setStyleSheet(
            f"QTextEdit {{background: rgba(255,255,255,20); color: #f1f1f1;"
            f"border-radius: {round(8*s)}px; padding: {round(6*s)}px; font-size: {round(13*s)}px; border: none;}}"
        )
        self.input.send_requested.connect(self._send_text)

        self.voice_level = VoiceLevelWidget()
        self.voice_level.hide()

        self.lang_btn = QPushButton(self._lang_short())
        self.lang_btn.setFixedSize(round(44*s), round(36*s))
        self.lang_btn.setToolTip(
            "Язык голосового ввода: AUTO — определяет сам, "
            "RU/EN — принудительно. Нажмите, чтобы переключить"
        )
        self.lang_btn.setStyleSheet(
            f"QPushButton {{background: rgba(255,255,255,20); color: #f1f1f1;"
            f"border: none; border-radius: {round(8*s)}px; font-size: {round(10*s)}px; font-weight: 600;}}"
            f"QPushButton:hover {{background: rgba(255,255,255,35);}}"
        )
        self.lang_btn.clicked.connect(self._toggle_voice_lang)

        self.mic_btn = MicButton("mic", size=round(36*s), icon_color="white", hover_color="white", hover_bg=False)
        self.mic_btn.setStyleSheet("")  # фон рисуем сами через paintEvent ниже
        self.mic_btn.setToolTip("Голосовой ввод: удерживайте — говорите — отпустите")
        self.mic_btn.press_started.connect(self._start_recording)
        self.mic_btn.press_released.connect(self._stop_recording)
        self._style_round_button(self.mic_btn, "#5aa0ff", round(36*s))

        self.send_btn = IconButton("send", size=round(36*s), icon_color="white", hover_color="white", hover_bg=False)
        self.send_btn.clicked.connect(self._send_text)
        self._style_round_button(self.send_btn, "#5aa0ff", round(36*s))

        bottom.addWidget(self.input, 1)
        bottom.addWidget(self.voice_level, 1)
        bottom.addWidget(self.lang_btn)
        bottom.addWidget(self.mic_btn)
        bottom.addWidget(self.send_btn)
        main.addLayout(bottom)

    def _style_round_button(self, icon_btn, color, size):
        # IconButton рисует иконку сама, но круглый цветной фон удобнее
        # оставить как QSS-фон родителя — оборачиваем через простую заливку
        icon_btn.setStyleSheet(
            f"QPushButton {{background: {color}; border: none; border-radius: {size//2}px;}}"
            f"QPushButton:hover {{background: #6fb0ff;}}"
        )

    def _lang_short(self):
        return {"AUTO": "AUTO", "ru-RU": "RU", "en-US": "EN"}[self._voice_lang]

    def _toggle_voice_lang(self):
        order = ["AUTO", "ru-RU", "en-US"]
        idx = order.index(self._voice_lang)
        self._voice_lang = order[(idx + 1) % len(order)]
        self.lang_btn.setText(self._lang_short())

    # ---- закрепление окна ----
    def _cycle_pin_mode(self):
        idx = self.PIN_ORDER.index(self.settings["pin_mode"])
        new_mode = self.PIN_ORDER[(idx + 1) % len(self.PIN_ORDER)]
        self.settings["pin_mode"] = new_mode
        self.pin_btn.set_icon(self.PIN_ICON[new_mode])
        self.pin_btn.setToolTip(self.PIN_TOOLTIP[new_mode])
        self._apply_pin_mode()
        save_settings_keys(self.settings, ["pin_mode"])

    def _apply_pin_mode(self):
        mode = self.settings["pin_mode"]
        if mode == "games":
            self._pin_poll_timer.start()
        else:
            self._pin_poll_timer.stop()
            self._set_always_on_top(mode == "always")

    def _poll_pin_games(self):
        self._set_always_on_top(is_foreground_fullscreen())

    def _set_always_on_top(self, enabled: bool):
        flags = self.windowFlags()
        has_flag = bool(flags & Qt.WindowStaysOnTopHint)
        if has_flag == enabled:
            return
        was_visible = self.isVisible()
        if enabled:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        if was_visible:
            self.show()

    # ---- закрытие: спрашиваем, свернуть в трей или закрыть полностью ----
    def _on_close_clicked(self):
        dialog = ConfirmDialog(
            "Свернуть переводчик в трей или закрыть программу полностью?",
            opacity_percent=self.settings["opacity_percent"],
        )
        dialog.minimize_chosen.connect(self.animate_hide)
        dialog.quit_chosen.connect(self.quit_requested.emit)
        dialog.animate_show_centered_on(self)
        self._confirm_dialog = dialog  # держим ссылку, чтобы не удалило раньше времени

    # ---- настройки ----
    def _open_settings(self):
        if self.settings_window is None:
            self.settings_window = SettingsWindow(self.hotkeys, self.suspend_flag, self.settings)
            self.settings_window.opacity_changed.connect(self._on_opacity_changed)
            self.settings_window.scale_changed.connect(self._on_scale_changed)
        self.settings_window.animate_show()
        force_foreground(self.settings_window)

    def _on_opacity_changed(self, percent):
        self.setWindowOpacity(max(percent, 1) / 100)

    def _on_scale_changed(self, _value):
        self._rebuild_ui()

    def _rebuild_ui(self):
        old_layout = self.layout()
        if old_layout is not None:
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            QWidget().setLayout(old_layout)  # открепляем старый layout от self

        self._build_ui()
        self.resize(self._scaled(WINDOW_WIDTH), self._scaled(WINDOW_HEIGHT))
        for original, translated in self.history:
            self._append_bubble(original, translated, animate=False)

    # ---- перетаскивание окна без рамки + запоминание позиции ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragging = True

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.settings["window_x"] = self.x()
            self.settings["window_y"] = self.y()
            save_settings_keys(self.settings, ["window_x", "window_y"])

    def _persist_positions(self):
        """Сохраняет только позиции окон — вызывается при выходе из
        программы (main.py), чтобы точно не потерять положение окон.

        Намеренно НЕ трогает прозрачность/горячие клавиши/автокопирование/
        звук/масштаб — эти настройки сохраняются отдельно, только по
        нажатию кнопки "Сохранить" в окне настроек (settings_window.py).
        Если сохранять здесь весь self.settings целиком, то ещё не
        подтверждённые кнопкой "Сохранить" изменения из открытого окна
        настроек могли бы случайно попасть на диск просто из-за выхода
        из программы.
        """
        keys = ["window_x", "window_y"]
        if self.settings_window is not None:
            keys += ["settings_window_x", "settings_window_y"]
        save_settings_keys(self.settings, keys)

    # ---- появление/исчезновение окна ----
    def animate_show(self):
        target = max(self.settings["opacity_percent"], 1) / 100
        show_animated(self, target, slide="bottom")
        force_foreground(self)

    def animate_hide(self):
        hide_animated(self, slide="bottom")

    # ---- отправка текста ----
    def _send_text(self):
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.show_status("Выполняется перевод…")
        self._translate_thread = TranslateThread(text)
        self._translate_thread.done.connect(self._on_translated)
        self._translate_thread.start()

    def _on_translated(self, original, src, dst, translated):
        self.hide_status()
        self.add_translated_pair(original, translated)

    # ---- добавление пары "оригинал / перевод" (используется и OCR-переводом) ----
    def add_translated_pair(self, original, translated, play_sound=False):
        self.history.append((original, translated))
        self._append_bubble(original, translated, animate=True)

        if not self.isVisible():
            self.animate_show()
        else:
            self.show()
            force_foreground(self)

        if self.settings.get("auto_copy", True) and translated:
            QGuiApplication.clipboard().setText(translated)

        if play_sound and self.settings.get("sound_enabled", True):
            from sound import play_notification
            play_notification()

    def _append_bubble(self, original, translated, animate=True):
        bubble = MessageBubble(original, translated, scale=self._scale_factor())
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)
        if animate:
            fade_in_widget(bubble)

    # ---- индикатор фоновой работы (OCR, обычный перевод — общий спиннер) ----
    def show_status(self, text: str):
        self.ocr_label.setText(text)
        self.ocr_spinner.start()
        self.ocr_label.show()

    def hide_status(self):
        self.ocr_spinner.stop()
        self.ocr_label.hide()

    def show_ocr_spinner(self):
        self.show_status("Распознаю экран…")

    def hide_ocr_spinner(self):
        self.hide_status()

    # ---- голосовой ввод: push-to-talk — удерживать, чтобы записывать ----
    def _start_recording(self):
        if self._is_recording:
            return
        import time
        self._record_start_time = time.time()
        self._recorder.start()
        self._is_recording = True
        self.mic_btn.set_color("white")
        self._style_round_button(self.mic_btn, "#ff5a5a", self.mic_btn.width())
        self.mic_btn.start_pulse()
        self.voice_level.reset()
        self.input.hide()
        self.voice_level.show()
        self._level_timer.start()

    def _stop_recording(self):
        if not self._is_recording:
            return
        import time
        duration = time.time() - self._record_start_time
        self._level_timer.stop()
        audio = self._recorder.stop()
        self._is_recording = False
        self.mic_btn.stop_pulse()
        self._style_round_button(self.mic_btn, "#5aa0ff", self.mic_btn.width())
        self.voice_level.hide()
        self.input.show()

        if duration < 0.25:
            return  # случайный клик — слишком короткая запись, не отправляем

        self.input.setPlaceholderText("Распознаю речь...")
        self._transcribe_thread = TranscribeThread(audio, self._voice_lang)
        self._transcribe_thread.done.connect(self._on_transcribed)
        self._transcribe_thread.start()

    def _poll_level(self):
        self.voice_level.push_level(self._recorder.level)

    def _on_transcribed(self, text):
        self.input.setPlaceholderText("Введите текст... (Enter — отправить, Shift+Enter — новая строка)")
        if text:
            self.input.setPlainText(text)
            self._send_text()
