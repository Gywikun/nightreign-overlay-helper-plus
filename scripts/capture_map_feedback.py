"""Render real HUD/map widgets in controlled feedback states, without game capture."""
from pathlib import Path
import json
import sys
import time

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication
from src.common import get_data_path
from src.ui.input import InputWorker
from src.ui.overlay import OverlayWidget, OverlayUIState
from src.ui.map_overlay import MapOverlayWidget
from src.ui.hp_overlay import HpOverlayWidget
from src.updater import Updater
from src.ui.notifications import NotificationPresenter

app = QApplication([])
font_id = QFontDatabase.addApplicationFont(get_data_path('fonts/SourceHanSansSC-Normal.otf'))
app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0], 10))
input_worker = InputWorker()
hud, maps, health = OverlayWidget(), MapOverlayWidget(), HpOverlayWidget()
updater = Updater(input_worker, hud, maps, health)
updater.map_region = [0, 0, 750, 750]
hud.update_ui_state(OverlayUIState(scale=1.0, opacity=1.0, day_text='DAY I - 3:34 后第一次缩圈开始'))
maps.setStyleSheet('background: #252a35;')
output = root / '.work' / 'r2-feedback-ui'
output.mkdir(parents=True, exist_ok=True)
states = [
    ('waiting', '地图：保持完整地图打开，等待画面稳定'),
    ('scanning', '地图：正在扫描，请保持完整地图打开'),
    ('success', '地图：扫描完成，结果已更新'),
    ('uncertain', '地图：3 个候选接近，显示共同信息'),
    ('interrupted', '地图：关图或缩放过早，本次结果未采用，开图后重试'),
    ('failed', '地图：画面匹配不足，未显示预测，稍后自动重试'),
]
for kind, message in states:
    updater.publish_map_feedback(kind, message, started=time.time()-3)
    hud.show()
    maps.setGeometry(0,0,750,750)
    maps.show()
    hud.timerEvent(None)
    maps.timerEvent(None)
    app.processEvents()
    assert message in hud.map_status_label.text()
    assert message in maps.match_time_label.text()
    assert hud.map_status_kind == kind and maps.map_status_kind == kind
    hud.grab().save(str(output/(kind+'-hud.png')))
    maps.grab().save(str(output/(kind+'-map.png')))
updater.automation_options.sound = False
presenter = NotificationPresenter(updater)
presenter.show_notification('地图扫描完成', '地图：扫描完成，结果已更新')
assert presenter.toast.isVisible()
updater.publish_map_feedback('waiting', '地图：等待重新开图')
app.processEvents()
assert not presenter.toast.isVisible(), 'Old map completion popup must disappear after the map is invalidated.'
presenter.show_notification('缩圈提醒', '距离缩圈约 10 秒')
updater.publish_map_feedback('scanning', '地图：正在扫描，请保持完整地图打开', started=time.time())
app.processEvents()
assert presenter.toast.isVisible(), 'Map updates must preserve active timer alerts.'
presenter.close()
(output/'result.json').write_text(json.dumps({'status':'passed','states':[kind for kind,_ in states],
                                            'popup_invalidation':'passed',
                                            'context':'Controlled widget states, not a real game session'},indent=2),encoding='utf-8')
print('Six feedback states and map-popup invalidation checks passed.')
hud.close(); maps.close(); health.close()
