"""Check real map widgets retain their pixmap through reopen and refresh."""
from pathlib import Path
import json
import sys
from unittest.mock import patch

root=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(root),str(root/'tests')]
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont,QFontDatabase
from src.common import get_data_path
from src.ui.input import InputWorker
from src.ui.overlay import OverlayWidget
from src.ui.map_overlay import MapOverlayWidget
from src.ui.hp_overlay import HpOverlayWidget
from src.ui.notifications import NotificationPresenter
from src.updater import Updater
from src.detector.map_detector import MapPatternMatchResult
from test_runtime import ScenarioDetector

app=QApplication([])
font_id=QFontDatabase.addApplicationFont(get_data_path('fonts/SourceHanSansSC-Normal.otf'))
app.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0],10))
inputs=InputWorker(); hud=OverlayWidget(); maps=MapOverlayWidget(); hp=HpOverlayWidget()
updater=Updater(inputs,hud,maps,hp)
model=updater.detector.map_detector
pattern=next(item for item in model.info.patterns if item.earth_shifting==0)
annotation=model._draw_overlay_image(MapPatternMatchResult(pattern,pattern.nightlord,100,0),(750,750),0)
detector=ScenarioDetector(); raw_detect=detector.detect
now=[100.0]; captures=[]
output=root/'.work'/'r3-cache-ui'; output.mkdir(parents=True,exist_ok=True)
def detect(params):
    result=raw_detect(params)
    if params.map_detect_param and params.map_detect_param.do_match_pattern:
        if detector.matches>1:
            assert maps.overlay_images is not None and not maps.overlay_image_box.pixmap().isNull()
            captures.append('visible_during_refresh')
            maps.grab().save(str(output/'refresh-keeps-information.png'))
        result.map_detect_result.overlay_images=[annotation]
    return result
detector.detect=detect; updater.detector=detector
updater.get_time=lambda:now[0]; updater._is_game_foreground=True
updater.map_region=[0,0,750,750]; maps.capture_excluded=True
def tick(value):
    now[0]=value; updater.detect_and_update_map(); app.processEvents()
with patch('src.updater.is_window_in_foreground',return_value=True):
    tick(100); tick(100.7)
    assert maps.overlay_images is not None
    saved_images=maps.overlay_images
    detector.visible=False; tick(101)
    detector.visible=True; tick(102); tick(108)
    assert detector.matches==1 and maps.overlay_images is saved_images
    assert not maps.overlay_image_box.pixmap().isNull()
    maps.grab().save(str(output/'reopen-uses-cache.png'))
    tick(123)
    assert detector.matches==2 and captures==['visible_during_refresh']
updater.automation_options.sound=False
presenter=NotificationPresenter(updater)
presenter.show_notification('缩圈提醒','测试提示')
assert presenter.timer.interval()==3500
presenter.close()
(output/'result.json').write_text(json.dumps({'status':'passed','reopen_scans':1,
                                              'annotation_visible_during_refresh':True,'popup_ms':3500,
                                              'context':'Controlled GUI fixture, not a real game session'},indent=2),encoding='utf-8')
print('Real widgets reused cache on reopening, retained annotations during refresh, and kept text popup at 3500 ms.')
maps.close();hud.close();hp.close()
