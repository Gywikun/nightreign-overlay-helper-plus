# Based on NeuraXmy/nightreign-overlay-helper v0.10.5.
# Added/modified 2026-10-02; see NOTICE.md and LICENSE (GNU AGPL v3).
from PyQt6.QtCore import Qt, QTimer, QUrl, QObject
from PyQt6.QtWidgets import QApplication, QLabel
from PyQt6.QtMultimedia import QSoundEffect
from src.common import get_asset_path
from src.ui.utils import exclude_widget_from_capture


class NotificationPresenter(QObject):
    def __init__(self, updater, parent=None):
        super().__init__(parent)
        self.updater = updater
        self._map_notification = False
        self.toast = QLabel()
        self.toast.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                                  | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.toast.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.toast.setStyleSheet("QLabel { background: rgba(28,31,43,230); color: #ffffff; padding: 14px 24px; border: 1px solid #9296cc; border-radius: 8px; font-size: 17px; }")
        exclude_widget_from_capture(self.toast)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.toast.hide)
        self.sound = QSoundEffect(self)
        self.sound.setSource(QUrl.fromLocalFile(get_asset_path("sounds/soft_alert.wav")))
        self.sound.setLoopCount(1)
        self.updater.notification_signal.connect(self.show_notification)
        self.updater.map_feedback_status_signal.connect(self.invalidate_map_notification)

    def show_notification(self, title, message):
        self._map_notification = title.startswith("地图") or title.startswith("本次地图")
        self.toast.setText(f"{title}\n{message}")
        self.toast.adjustSize()
        screen = QApplication.primaryScreen()
        if self.updater.game_window:
            from src.ui.utils import get_qt_screen_by_mss_region
            try:
                screen = get_qt_screen_by_mss_region(self.updater.game_window)
            except ValueError:
                pass
        geometry = screen.availableGeometry()
        self.toast.move(geometry.x() + (geometry.width() - self.toast.width()) // 2,
                        geometry.y() + max(24, geometry.height() // 6))
        self.toast.show()
        self.timer.start(round(self.updater.automation_options.popup_seconds * 1000))
        self.play_sound()

    def invalidate_map_notification(self, kind):
        if self._map_notification and kind not in ("success", "uncertain"):
            self.timer.stop()
            self.toast.hide()
            self.sound.stop()

    def play_sound(self):
        options = self.updater.automation_options
        if options.sound and options.volume > 0:
            self.sound.setVolume(options.volume / 100)
            self.sound.play()

    def close(self):
        self.timer.stop()
        self.sound.stop()
        self.toast.close()
