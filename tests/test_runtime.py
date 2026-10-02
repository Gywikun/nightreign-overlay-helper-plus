import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
from PyQt6.QtCore import QObject
from src.updater import Updater, Phase
from src.automation import normalize_region


class Surface(QObject):
    capture_excluded = True
    def __init__(self):
        super().__init__()
        self.states = []
    def update_ui_state(self, state):
        self.states.append(state)


class ScenarioDetector:
    def __init__(self):
        self.visible = True
        self.frame = np.full((750, 750, 3), 50, dtype=np.uint8)
        self.matches = 0
        self.hp_detector = SimpleNamespace(recent_lengths=[100], last_valid_length=100, stable_count=8)
    def detect(self, params):
        request = params.map_detect_param
        if request:
            if request.do_match_full_map:
                result = SimpleNamespace(is_full_map=self.visible, img=self.frame)
            elif request.do_match_earth_shifting:
                result = SimpleNamespace(earth_shifting=0)
            else:
                self.matches += 1
                result = SimpleNamespace(overlay_images=[Image.new("RGBA", (750,750))], low_quality=False, plausible_count=1)
            return SimpleNamespace(map_detect_result=result)
        return SimpleNamespace(day_detect_result=SimpleNamespace(start_day1=True, start_day2=False, start_day3=False,
                                                                 score_day1=.1, score_day2=.9, score_day3=.95))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        foreground = patch('src.updater.is_window_in_foreground', return_value=True)
        foreground.start()
        self.addCleanup(foreground.stop)
        self.input = QObject()
        self.surface, self.maps, self.hp = Surface(), Surface(), Surface()
        self.updater = Updater(self.input, self.surface, self.maps, self.hp)
        self.updater.detector = ScenarioDetector()
        self.now = 100.0
        self.updater.get_time = lambda: self.now
        self.updater._is_game_foreground = True
        self.updater.map_region = [0,0,750,750]

    def tick_map(self, now):
        self.now = now
        self.updater.detect_and_update_map()

    def test_open_close_change_and_periodic_refresh_without_hotkeys(self):
        self.updater.automation_options.refresh_on_open = True
        self.tick_map(100)
        self.tick_map(100.7)
        self.assertEqual(self.updater.detector.matches,1)
        self.assertTrue(self.updater.map_overlay_visible)
        self.updater.detector.visible=False
        self.tick_map(101)
        self.assertFalse(self.updater.map_overlay_visible)
        self.updater.detector.visible=True
        self.tick_map(102)
        self.tick_map(106)
        self.assertEqual(self.updater.detector.matches,2)
        self.updater.detector.frame[:] = 100
        self.tick_map(112)
        self.tick_map(112.7)
        self.assertEqual(self.updater.detector.matches,3)
        self.tick_map(133)
        self.assertEqual(self.updater.detector.matches,4)

    def test_map_stops_refreshing_outside_game(self):
        self.tick_map(100)
        self.tick_map(100.7)
        self.updater._is_game_foreground=False
        self.tick_map(150)
        self.assertEqual(self.updater.detector.matches,1)
        self.assertFalse(self.updater.map_overlay_visible)

    def test_continuous_day_banner_does_not_reset_elapsed_time(self):
        self.updater.day1_detect_region=[0,0,100,30]
        for index in range(25):
            self.now = 100 + index*.2
            self.updater.detect_and_update_dayx()
        self.assertEqual(self.updater.day,1)
        self.assertAlmostEqual(self.updater.phase_start_time,100.2)
        self.assertGreater(self.now-self.updater.phase_start_time,4)

    def test_new_round_clears_every_old_session_artifact(self):
        self.updater.in_rain_start_time=90
        self.updater.art_start_time=92
        self.updater.art_type="recluse"
        self.updater.map_policy.matched_signature=[50]*576
        self.updater.start_day1()
        self.assertIsNone(self.updater.in_rain_start_time)
        self.assertIsNone(self.updater.art_start_time)
        self.assertIsNone(self.updater.art_type)
        self.assertIsNone(self.updater.map_policy.matched_signature)
        self.assertEqual(self.updater.detector.hp_detector.recent_lengths,[])
        self.assertTrue(any(state.clear_image for state in self.maps.states))

    def test_correction_applies_on_worker_queue(self):
        self.updater.submit_command("correct_timer",{"day":2,"phase":2,"elapsed":35})
        self.assertIsNone(self.updater.day)
        self.updater.process_automation_commands()
        self.assertEqual(self.updater.day,2)
        self.assertEqual(self.updater.current_phase,Phase.SECOND_CIRCLE_STABLE)
        self.assertEqual(self.updater.phase_start_time,65)

    def test_invalid_correction_does_not_change_timer(self):
        self.updater.start_day1()
        self.updater.submit_command("correct_timer",{"day":2,"phase":0,"elapsed":300})
        self.updater.process_automation_commands()
        self.assertEqual(self.updater.day,1)

    def test_clock_jump_advances_all_elapsed_phases(self):
        self.updater.start_day1()
        self.now=800
        self.updater.update_phase_timer()
        self.assertEqual(self.updater.current_phase,Phase.SECOND_CIRCLE_SHRINK)
        self.assertEqual(self.updater.phase_start_time,760)

    def test_saved_anchor_moves_without_recalibrating_old_absolute_region(self):
        self.updater.game_window=(0,0,960,540)
        self.updater.map_region=[544,85,372,372]
        self.updater.automation_options.anchors={"map_region":normalize_region(self.updater.map_region,self.updater.game_window)}
        self.updater.automation_options.anchor_geometry={"width":960,"height":540}
        with patch('src.automation_runtime.game_client_rect',return_value=(100,50,1260,540)):
            self.updater.track_game_and_locate(False)
        self.assertEqual(self.updater.map_region,[944,135,372,372])


if __name__ == "__main__":
    unittest.main()
