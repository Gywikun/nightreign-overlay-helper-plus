"""One native UI check: request acknowledgment, current help and display name."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

root = Path(__file__).resolve().parent.parent
os.environ['NROH_DATA_DIR'] = str(root / '.work' / 'ui-check-config')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding='utf-8')
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication, QDialog, QTextBrowser, QMessageBox
from src.common import APP_FULLNAME, get_data_path
from src.ui.input import InputWorker
from src.ui.overlay import OverlayWidget
from src.ui.map_overlay import MapOverlayWidget
from src.ui.hp_overlay import HpOverlayWidget
from src.ui.settings import SettingsWindow
from src.updater import Updater

QApplication.setAttribute(Qt.ApplicationAttribute.AA_Use96Dpi)
app = QApplication([])
font_id = QFontDatabase.addApplicationFont(get_data_path('fonts/SourceHanSansSC-Normal.otf'))
app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
inputs = InputWorker()
hud, maps, hp = OverlayWidget(), MapOverlayWidget(), HpOverlayWidget()
updater = Updater(inputs, hud, maps, hp)
settings = SettingsWindow(hud, maps, updater, inputs)
dialog = settings.enhancement_dialog
out = root / 'docs' / 'images'
out.mkdir(exist_ok=True)
dialog.resize(840, 710)
dialog.show()
dialog.request_map_refresh()
assert '已提交' in dialog.refresh_request_label.text()
updater.process_automation_commands()
assert '等待游戏窗口' in dialog.refresh_request_label.text()
app.processEvents()
assert dialog.grab().save(str(out / '16-refresh-request-r4.png'))
assert APP_FULLNAME in settings.windowTitle() and APP_FULLNAME in dialog.windowTitle()

with patch.object(QDialog, 'exec', lambda self: 0):
    for callback, filename, expected in (
        (settings.show_capture_day1_hpcolor_region_tutorial, '17-timer-help-r4.png', '默认自动定位'),
        (settings.show_capture_map_region_tutorial, '18-map-help-r4.png', '后台刷新保留旧标注')):
        help_dialog = callback()
        help_dialog.show()
        app.processEvents()
        browser = help_dialog.findChild(QTextBrowser)
        assert expected in browser.toPlainText()
        assert '打开完整图文使用指南' in browser.toPlainText()
        assert APP_FULLNAME in help_dialog.windowTitle()
        assert help_dialog.grab().save(str(out / filename))
        help_dialog.close()

about = []
with patch.object(QMessageBox, 'exec', lambda self: about.append(self) or 0):
    task_cwd = os.getcwd()
    try:
        os.chdir(root / '.work')
        settings.open_about_dialog()
    finally:
        os.chdir(task_cwd)
assert APP_FULLNAME in about[0].windowTitle()
assert about[0].detailedText(), 'Original manual must remain accessible from arbitrary CWD'
print(json.dumps({'status': 'passed', 'name': APP_FULLNAME,
                  'refresh_status': dialog.refresh_request_label.text(),
                  'help_dialogs': 2, 'about_arbitrary_cwd': True}, ensure_ascii=False))
dialog.close()
settings.close()
hud.close()
maps.close()
hp.close()
