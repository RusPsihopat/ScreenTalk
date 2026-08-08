"""Окно настроек — в том же визуальном стиле, что и основное окно чата:
тёмное, скруглённое, полупрозрачное, с плавным появлением/исчезновением.
"""
from PySide6.QtCore import Qt, QPoint, QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QFrame
)

import keyboard

import settings_store
import autostart
from hotkey_state import combo_label
from ui_kit import IconButton, ToggleSwitch, show_animated, hide_animated, fade_in_widget


class HotkeyRecorder(QObject):
    """Слушает следующую "настоящую" клавишу (не сам модификатор Ctrl/Alt/
    Shift) один раз и сообщает её скан-код + зажатые модификаторы.

    Наследуется от QObject и общается через сигнал, потому что колбэк
    библиотеки keyboard вызывается в своём собственном потоке — трогать
    виджеты Qt напрямую оттуда нельзя.
    """
    captured = Signal(int, bool, bool, bool)  # scan_code, ctrl, alt, shift

    _MODIFIER_NAMES = {
        "ctrl", "left ctrl", "right ctrl",
        "alt", "left alt", "right alt",
        "shift", "left shift", "right shift",
    }

    def __init__(self):
        super().__init__()
        keyboard.hook(self._on_event)

    def _on_event(self, event):
        if event.event_type != keyboard.KEY_DOWN:
            return
        name = (event.name or "").lower()
        if name in self._MODIFIER_NAMES:
            return  # ждём "настоящую" клавишу, не сам модификатор
        ctrl = keyboard.is_pressed('ctrl')
        alt = keyboard.is_pressed('alt')
        shift = keyboard.is_pressed('shift')
        keyboard.unhook(self._on_event)
        self.captured.emit(event.scan_code, ctrl, alt, shift)


class SettingsWindow(QWidget):
    opacity_changed = Signal(int)  # процент 0..100
    scale_changed = Signal(int)    # 100 / 125 / 150

    def __init__(self, hotkeys, suspend_flag, settings: dict):
        super().__init__()
        self.hotkeys = hotkeys
        self.suspend_flag = suspend_flag
        self.settings = settings
        self._recorder = None  # активный HotkeyRecorder, пока идёт запись

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(320, 460)
        self._drag_pos = QPoint()
        self._dragging = False

        if settings.get("settings_window_x") is not None and settings.get("settings_window_y") is not None:
            self.move(settings["settings_window_x"], settings["settings_window_y"])

        self._build_ui()
        self.setWindowOpacity(max(self.settings["opacity_percent"], 1) / 100)

    # ---- UI ----
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame()
        container.setObjectName("container")
        container.setStyleSheet("#container {background-color: #1e1f22; border-radius: 14px;}")
        outer.addWidget(container)

        main = QVBoxLayout(container)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        # заголовок
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(12, 8, 8, 4)
        title = QLabel("Настройки")
        title.setStyleSheet("color: #9aa0a6; font-size: 12px; font-weight: 600;")
        close_btn = IconButton("close", size=22)
        close_btn.clicked.connect(self.animate_hide)
        title_bar.addWidget(title)
        title_bar.addStretch()
        title_bar.addWidget(close_btn)
        main.addLayout(title_bar)

        body = QVBoxLayout()
        body.setContentsMargins(16, 4, 16, 16)
        body.setSpacing(16)

        # --- прозрачность ---
        opacity_row = QHBoxLayout()
        opacity_title = QLabel("Прозрачность окна")
        opacity_title.setStyleSheet("color: #f1f1f1; font-size: 13px;")
        self.opacity_value_label = QLabel(f"{self.settings['opacity_percent']}%")
        self.opacity_value_label.setStyleSheet("color: #9aa0a6; font-size: 12px;")
        opacity_row.addWidget(opacity_title)
        opacity_row.addStretch()
        opacity_row.addWidget(self.opacity_value_label)
        body.addLayout(opacity_row)

        # диапазон 0..20 * шаг 5% = честные 0..100% с шагом ровно 5%
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 20)
        self.opacity_slider.setValue(round(self.settings["opacity_percent"] / 5))
        self.opacity_slider.setStyleSheet(
            "QSlider::groove:horizontal {height: 4px; background: rgba(255,255,255,35); border-radius: 2px;}"
            "QSlider::handle:horizontal {background: #5aa0ff; width: 14px; margin: -6px 0; border-radius: 7px;}"
            "QSlider::handle:horizontal:hover {background: #6fb0ff;}"
        )
        self.opacity_slider.valueChanged.connect(self._on_opacity_slider)
        body.addWidget(self.opacity_slider)

        # --- горячие клавиши ---
        hotkeys_title = QLabel("Горячие клавиши")
        hotkeys_title.setStyleSheet("color: #f1f1f1; font-size: 13px;")
        body.addWidget(hotkeys_title)

        self.capture_btn = self._add_hotkey_row(
            body, "Выделить область экрана", self.hotkeys.capture, self._record_capture
        )
        self.toggle_btn = self._add_hotkey_row(
            body, "Показать/скрыть чат", self.hotkeys.toggle, self._record_toggle
        )

        hint = QLabel("Нажмите на комбинацию и сразу нажмите нужную клавишу")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #7a7f87; font-size: 11px;")
        body.addWidget(hint)

        # --- переключатели ---
        self.auto_copy_switch = self._add_toggle_row(
            body, "Автокопирование перевода", self.settings["auto_copy"], self._on_auto_copy
        )
        self.sound_switch = self._add_toggle_row(
            body, "Звук после готовности OCR", self.settings["sound_enabled"], self._on_sound
        )

        # --- масштаб интерфейса ---
        scale_title = QLabel("Масштаб интерфейса")
        scale_title.setStyleSheet("color: #f1f1f1; font-size: 13px;")
        body.addWidget(scale_title)

        scale_row = QHBoxLayout()
        self.scale_buttons = {}
        for value in (100, 125, 150):
            btn = QPushButton(f"{value}%")
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda _checked, v=value: self._on_scale(v))
            scale_row.addWidget(btn)
            self.scale_buttons[value] = btn
        body.addLayout(scale_row)
        self._refresh_scale_buttons()

        # --- автозапуск ---
        self.autostart_switch = self._add_toggle_row(
            body, "Автозапуск при старте Windows", autostart.is_enabled(), self._on_autostart
        )
        self.autostart_admin_switch = self._add_toggle_row(
            body, "Автозапуск с правами администратора",
            self.settings.get("autostart_admin", False), self._on_autostart_admin
        )

        body.addStretch()

        hint = QLabel("Изменения применяются сразу. Чтобы они сохранились и\nпосле перезапуска — нажмите «Сохранить».")
        hint.setStyleSheet("color: #7a7f87; font-size: 11px;")
        body.addWidget(hint)

        # --- кнопка сохранить ---
        save_row = QHBoxLayout()
        save_row.setSpacing(10)
        self.save_btn = QPushButton("Сохранить")
        self.save_btn.setFixedHeight(36)
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setStyleSheet(
            "QPushButton {background: #5aa0ff; color: white; border: none;"
            "border-radius: 8px; font-size: 13px; font-weight: 600; padding: 0 18px;}"
            "QPushButton:hover {background: #6fb0ff;}"
        )
        self.save_btn.clicked.connect(self._on_save_clicked)

        self.saved_label = QLabel("✓ Сохранено")
        self.saved_label.setStyleSheet("color: #3ddc84; font-size: 12px; font-weight: 600;")
        self.saved_label.hide()

        save_row.addWidget(self.save_btn)
        save_row.addWidget(self.saved_label)
        save_row.addStretch()
        body.addLayout(save_row)

        main.addLayout(body)

    def _add_hotkey_row(self, parent_layout, label_text, combo, on_record):
        row = QHBoxLayout()
        label = QLabel(label_text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #c7cad1; font-size: 12px;")
        btn = QPushButton(combo_label(combo))
        btn.setFixedWidth(120)
        btn.setStyleSheet(
            "QPushButton {background: rgba(255,255,255,20); color: #f1f1f1;"
            "border: none; border-radius: 6px; padding: 5px; font-size: 12px;}"
            "QPushButton:hover {background: rgba(255,255,255,35);}"
        )
        btn.clicked.connect(on_record)
        row.addWidget(label, 1)
        row.addWidget(btn)
        parent_layout.addLayout(row)
        return btn

    def _add_toggle_row(self, parent_layout, label_text, checked, on_toggle):
        row = QHBoxLayout()
        label = QLabel(label_text)
        label.setStyleSheet("color: #c7cad1; font-size: 12px;")
        switch = ToggleSwitch(checked=checked)
        switch.toggled.connect(on_toggle)
        row.addWidget(label, 1)
        row.addWidget(switch)
        parent_layout.addLayout(row)
        return switch

    def _refresh_scale_buttons(self):
        active = self.settings["ui_scale"]
        for value, btn in self.scale_buttons.items():
            if value == active:
                btn.setStyleSheet(
                    "QPushButton {background: #5aa0ff; color: white; border: none;"
                    "border-radius: 6px; font-size: 12px; font-weight: 600;}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton {background: rgba(255,255,255,20); color: #f1f1f1;"
                    "border: none; border-radius: 6px; font-size: 12px;}"
                    "QPushButton:hover {background: rgba(255,255,255,35);}"
                )

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
            self.settings["settings_window_x"] = self.x()
            self.settings["settings_window_y"] = self.y()
            settings_store.save_fields(settings_window_x=self.x(), settings_window_y=self.y())

    # ---- появление/исчезновение ----
    def animate_show(self):
        target = max(self.settings["opacity_percent"], 1) / 100
        show_animated(self, target, slide="side")

    def animate_hide(self):
        hide_animated(self, slide="side")

    # ---- прозрачность (применяется сразу, но на диск пишется только по кнопке "Сохранить") ----
    def _on_opacity_slider(self, slider_value):
        percent = slider_value * 5
        self.settings["opacity_percent"] = percent
        self.opacity_value_label.setText(f"{percent}%")
        self.setWindowOpacity(max(percent, 1) / 100)
        self.opacity_changed.emit(percent)

    # ---- переключатели (тоже применяются сразу, сохраняются по кнопке) ----
    def _on_auto_copy(self, checked):
        self.settings["auto_copy"] = checked

    def _on_sound(self, checked):
        self.settings["sound_enabled"] = checked

    # ---- масштаб ----
    def _on_scale(self, value):
        self.settings["ui_scale"] = value
        self._refresh_scale_buttons()
        self.scale_changed.emit(value)

    # ---- автозапуск (применяется сразу — это прямое действие с Windows,
    # как и положение окна, а не просто внутренняя настройка приложения) ----
    def _on_autostart(self, checked):
        ok = autostart.set_enabled(checked, run_as_admin=self.settings.get("autostart_admin", False))
        if not ok:
            self.autostart_switch.setChecked(not checked, animate=False)
            return
        settings_store.save_fields(autostart_admin=self.settings.get("autostart_admin", False))

    def _on_autostart_admin(self, checked):
        self.settings["autostart_admin"] = checked
        settings_store.save_fields(autostart_admin=checked)
        if autostart.is_enabled():
            ok = autostart.set_enabled(True, run_as_admin=checked)
            if not ok:
                self.autostart_admin_switch.setChecked(not checked, animate=False)

    # ---- запись новой горячей клавиши ----
    def _record_capture(self):
        self._start_recording(self.capture_btn, self._apply_capture)

    def _record_toggle(self):
        self._start_recording(self.toggle_btn, self._apply_toggle)

    def _start_recording(self, btn, apply_fn):
        if self._recorder is not None:
            return  # уже что-то записываем — игнорируем повторный клик
        btn.setText("Нажмите клавишу…")
        self.suspend_flag["active"] = True
        self._recorder = HotkeyRecorder()
        self._recorder.captured.connect(
            lambda sc, c, a, s: self._on_recorded(apply_fn, sc, c, a, s)
        )

    def _on_recorded(self, apply_fn, scan_code, ctrl, alt, shift):
        self.suspend_flag["active"] = False
        self._recorder = None
        apply_fn(scan_code, ctrl, alt, shift)

    def _apply_capture(self, scan_code, ctrl, alt, shift):
        self.hotkeys.capture = {"scan_code": scan_code, "ctrl": ctrl, "alt": alt, "shift": shift}
        self.capture_btn.setText(combo_label(self.hotkeys.capture))

    def _apply_toggle(self, scan_code, ctrl, alt, shift):
        self.hotkeys.toggle = {"scan_code": scan_code, "ctrl": ctrl, "alt": alt, "shift": shift}
        self.toggle_btn.setText(combo_label(self.hotkeys.toggle))

    def _persist(self):
        self.settings["capture_hotkey"] = self.hotkeys.capture
        self.settings["toggle_hotkey"] = self.hotkeys.toggle
        settings_store.save(self.settings)

    def _on_save_clicked(self):
        self._persist()
        self.saved_label.show()
        fade_in_widget(self.saved_label, duration=150)
        QTimer.singleShot(1600, self.saved_label.hide)
