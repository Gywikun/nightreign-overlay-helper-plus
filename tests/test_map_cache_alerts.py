import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import test_runtime as runtime_fixture
from src.automation import AutomationOptions, MapRefreshPolicy


class CachePolicyTests(unittest.TestCase):
    def test_reopen_uses_existing_match_by_default(self):
        policy, options = MapRefreshPolicy(), AutomationOptions()
        signature = [50]*576
        policy.observe(True, signature, 0, options)
        policy.observe(True, signature, .7, options)
        policy.complete(signature, .8, True)
        policy.observe(False, None, 1, options)
        policy.observe(True, signature, 2, options)
        self.assertIsNone(policy.observe(True, signature, 6, options))

    def test_closed_time_does_not_force_periodic_refresh_on_reopen(self):
        policy, options = MapRefreshPolicy(), AutomationOptions()
        signature = [50]*576
        policy.observe(True, signature, 0, options)
        policy.observe(True, signature, .7, options)
        policy.complete(signature, .8, True)
        policy.observe(False, None, 1, options)
        policy.observe(True, signature, 200, options)
        self.assertIsNone(policy.observe(True, signature, 201, options))
        self.assertEqual(policy.observe(True, signature, 221, options), '定时更新')

    def test_old_defaults_migrate_once_but_custom_mute_and_volume_are_preserved(self):
        defaults = AutomationOptions.from_dict({'refresh_on_open': True, 'volume': 40})
        self.assertFalse(defaults.refresh_on_open)
        self.assertLessEqual(defaults.volume, 25)
        self.assertEqual(defaults.preferences_revision, 3)
        custom = AutomationOptions.from_dict({'refresh_on_open': True, 'volume': 8, 'sound': False})
        self.assertEqual(custom.volume, 8)
        self.assertFalse(custom.sound)
        opted_in = AutomationOptions.from_dict({'preferences_revision':3, 'refresh_on_open':True, 'volume':40})
        self.assertTrue(opted_in.refresh_on_open)
        self.assertEqual(opted_in.volume, 40)


class CacheRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.scenario = runtime_fixture.RuntimeTests('test_open_close_change_and_periodic_refresh_without_hotkeys')
        self.scenario.setUp()
        self.addCleanup(self.scenario.doCleanups)
        self.updater = self.scenario.updater
        self.updater.automation_options = AutomationOptions()

    def tick(self, value):
        self.scenario.tick_map(value)

    def scan_once(self):
        self.tick(100)
        self.tick(100.7)

    def visible_predictions(self):
        visible = False
        for state in self.scenario.maps.states:
            if state.overlay_images is not None:
                visible = bool(state.overlay_images)
            if state.clear_image:
                visible = False
        return visible

    def test_reopen_keeps_annotations_and_does_not_scan_again(self):
        self.scan_once()
        self.updater.detector.visible = False
        self.tick(101)
        self.updater.detector.visible = True
        self.tick(102)
        self.assertTrue(self.visible_predictions())
        self.tick(108)
        self.assertEqual(self.updater.detector.matches, 1)

    def test_periodic_background_refresh_keeps_old_annotations_during_work(self):
        self.scan_once()
        visible_during_work = []
        previous = self.updater.detector.detect
        def detector(params):
            if params.map_detect_param and params.map_detect_param.do_match_pattern:
                visible_during_work.append(self.visible_predictions())
            return previous(params)
        self.updater.detector.detect = detector
        self.tick(121)
        self.assertEqual(visible_during_work, [True])
        self.assertTrue(self.visible_predictions())

    def test_failed_same_map_refresh_preserves_cached_annotations(self):
        self.scan_once()
        previous = self.updater.detector.detect
        def detector(params):
            if params.map_detect_param and params.map_detect_param.do_match_earth_shifting:
                return SimpleNamespace(map_detect_result=SimpleNamespace(earth_shifting=None))
            return previous(params)
        self.updater.detector.detect = detector
        self.updater.map_policy.request('refresh')
        self.tick(106)
        self.assertTrue(self.visible_predictions())
        message = next(state.automatic_status for state in reversed(self.scenario.maps.states) if state.automatic_status)
        self.assertIn('上次', message)

    def test_new_round_invalidates_cached_predictions(self):
        self.scan_once()
        self.updater.start_day1()
        self.assertFalse(self.visible_predictions())
        self.tick(110)
        self.tick(110.7)
        self.assertEqual(self.updater.detector.matches, 2)


class SofterAlertTests(unittest.TestCase):
    def test_text_popup_duration_is_preserved_independently_of_short_sound(self):
        options = AutomationOptions()
        self.assertEqual(options.popup_seconds, 3.5)
        custom = AutomationOptions.from_dict({'preferences_revision':3,'popup_seconds':2.2})
        self.assertAlmostEqual(custom.popup_seconds, 2.2)

    def test_soft_waveform_is_short_lower_pitch_and_lower_amplitude(self):
        path = Path(__file__).resolve().parent.parent/'assets'/'sounds'/'soft_alert.wav'
        with wave.open(str(path),'rb') as sound:
            duration = sound.getnframes()/sound.getframerate()
            samples = np.frombuffer(sound.readframes(sound.getnframes()), dtype='<i2').astype(float)/32768
            rate = sound.getframerate()
        self.assertLessEqual(duration, .25)
        self.assertLess(np.max(np.abs(samples)), .16)
        spectrum = np.abs(np.fft.rfft(samples))
        frequency = np.fft.rfftfreq(len(samples),1/rate)[np.argmax(spectrum)]
        self.assertLessEqual(frequency, 550)
        self.assertLess(np.max(np.abs(samples[:10])), .005)
        self.assertLess(np.max(np.abs(samples[-10:])), .005)


if __name__ == '__main__':
    unittest.main()
