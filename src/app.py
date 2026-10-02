# Based on NeuraXmy/nightreign-overlay-helper v0.10.5.
# Added/modified 2026-10-02; see NOTICE.md and LICENSE (GNU AGPL v3).
import sys
import time
import os
from PyQt6.QtCore import QThread, Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QIcon, QAction, QCursor, QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu
)

from src.ui.input import InputWorker
from src.ui.overlay import OverlayWidget
from src.ui.map_overlay import MapOverlayWidget
from src.ui.hp_overlay import HpOverlayWidget
from src.ui.settings import SettingsWindow
from src.updater import Updater
from src.common import APP_FULLNAME, APP_VERSION, ICON_PATH, get_appdata_path, get_data_path
from src.ui.notifications import NotificationPresenter
from src.logger import info, warning, error


def log_system_and_screen_info(app: QApplication):
    try:
        import platform
        system = platform.system()
        release = platform.release()
        version = platform.version()
        info(f"Operating System: {system} {release} ({version})")
    except Exception as e:
        warning(f"Error getting OS info: {e}")

    try:
        import mss
        with mss.mss() as sct:
            monitors = sct.monitors
            info(f"MSS Detected {len(monitors)-1} monitor(s):")
            for i, monitor in enumerate(monitors[1:], start=1):
                info(f"    Monitor {i}: {monitor['width']}x{monitor['height']} at ({monitor['left']},{monitor['top']})")
    except Exception as e:
        warning(f"Error getting monitor info: {e}")

    try:
        screens = app.screens()
        info(f"QApplication detected {len(screens)} screen(s):")
        for i, screen in enumerate(screens, start=1):
            size = screen.size()
            pos = screen.geometry().topLeft()
            dpi = screen.logicalDotsPerInch()
            device_pixel_ratio = screen.devicePixelRatio()
            info(f"    Screen {i}: {size.width()}x{size.height()} at ({pos.x()},{pos.y()}), DPI: {dpi}, Device Pixel Ratio: {device_pixel_ratio}")
    except Exception as e:
        warning(f"Error getting screens from QApplication: {e}")


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--show-settings", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--smoke-output")
    parser.add_argument("--quit-after", type=int, default=0)
    args = parser.parse_args()
    first_run = not Path(get_appdata_path("settings.yaml")).exists()
    info("=" * 40)
    info(f"Starting app v{APP_VERSION}...")

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_Use96Dpi)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    font_id = QFontDatabase.addApplicationFont(get_data_path("fonts/SourceHanSansSC-Normal.otf"))
    families = QFontDatabase.applicationFontFamilies(font_id)
    if families:
        app.setFont(QFont(families[0], 10))

    log_system_and_screen_info(app)
    
    # 防止因没有窗口而导致程序退出
    app.setQuitOnLastWindowClosed(False)

    # 创建对象
    input = InputWorker()
    overlay = OverlayWidget()
    map_overlay = MapOverlayWidget()
    hp_overlay = HpOverlayWidget()

    updater = Updater(input, overlay, map_overlay, hp_overlay)
    settings_window = SettingsWindow(overlay, map_overlay, updater, input)
    notifications = NotificationPresenter(updater, app)
    settings_window.notification_presenter = notifications
    
    # 创建系统托盘图标和菜单
    tray_icon = QSystemTrayIcon()
    tray_icon.setIcon(QIcon(ICON_PATH))
    tray_icon.setToolTip(APP_FULLNAME)

    menu = QMenu()
    settings_action = QAction("设置")
    def show_settings():
        settings_window.show()
        settings_window.activateWindow()
        settings_window.raise_()
    settings_action.triggered.connect(show_settings)
    menu.addAction(settings_action)
    automatic_action = QAction("自动运行与检测自检")
    automatic_action.triggered.connect(lambda: settings_window.show_enhancements(0))
    menu.addAction(automatic_action)
    quit_action = QAction("退出")
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)
    menu.addSeparator()
    tray_icon.setContextMenu(menu)
    tray_icon.show()
    
    def show_menu_at_cursor_pos():
        cursor_pos = QCursor.pos()
        menu.move(cursor_pos)
        menu.show()
    def on_menu_show():
        overlay.is_menu_opened = True
        map_overlay.is_menu_opened = True
        updater.is_menu_opened = True
        # info("Menu opened")
    def on_menu_hide():
        overlay.is_menu_opened = False
        map_overlay.is_menu_opened = False
        updater.is_menu_opened = False
        # info("Menu closed")

    overlay.right_click_signal.connect(show_menu_at_cursor_pos)
    overlay.right_click_signal.connect(on_menu_show)
    menu.aboutToShow.connect(on_menu_show)
    menu.aboutToHide.connect(on_menu_hide)

    # 启动输入监听
    input_thread = QThread()
    input.moveToThread(input_thread)
    input_thread.started.connect(input.run)
    input_thread.start()
    
    # 设置并启动后台检测器
    updater_thread = QThread()
    updater.moveToThread(updater_thread)
    updater_thread.started.connect(updater.run)
    updater_thread.start()

    # 清理：程序退出时，停止worker并等待线程结束
    def on_quit():
        notifications.close()
        info("Stopping worker thread...")
        updater.stop()
        updater_thread.quit()
        if not updater_thread.wait(5000):
            print("Updater thread did not exit in time. Forcing termination.")
            updater_thread.terminate()
        else:
            info("Updater thread stopped.")
        input.stop()
        input_thread.quit()
        if not input_thread.wait(1000):
            print("Input thread did not exit in time. Forcing termination.")
            input_thread.terminate()
        else:
            info("Input thread stopped.")
        info("All Thread stopped.")

        tray_icon.deleteLater()

    app.aboutToQuit.connect(on_quit)
    
    overlay.show()
    if args.show_settings or (first_run and not args.smoke_test):
        settings_window.show()
        settings_window.show_enhancements(0)
    if args.smoke_test:
        settings_window.show()
        settings_window.show_enhancements(0)
        def smoke_capture():
            try:
                output = Path(args.smoke_output or get_appdata_path("smoke-test"))
                output.mkdir(parents=True, exist_ok=True)
                screens = []
                for index, name in enumerate(("automatic", "diagnostics", "alerts", "timer")):
                    settings_window.enhancement_dialog.tabs.setCurrentIndex(index)
                    app.processEvents()
                    settings_window.enhancement_dialog.grab().save(str(output / (name + ".png")))
                    screens.append(name)
                settings_window.grab().save(str(output / "settings.png"))
                (output / "result.json").write_text(json.dumps({"version": APP_VERSION, "status": "passed", "screens": screens,
                                                              "config_path": get_appdata_path("settings.yaml")}, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                error(f"Smoke test failed: {exc}")
            app.quit()
        QTimer.singleShot(1800, smoke_capture)
    elif args.quit_after > 0:
        QTimer.singleShot(args.quit_after * 1000, app.quit)

    try:
        exit_code = app.exec() 
        info(f"QApp event loop finished with exit code {exit_code}.")
    except Exception as e:
        exit_code = 1
        error(f"Exception in app exec: {e}")

    settings_window.save_settings()

    time.sleep(1)
    os._exit(exit_code)
