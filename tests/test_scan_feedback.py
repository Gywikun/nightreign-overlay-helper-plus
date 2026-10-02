"""Regression cases for map result publication and player-visible feedback."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import test_runtime as runtime_fixture


class ScanFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.scenario = runtime_fixture.RuntimeTests('test_open_close_change_and_periodic_refresh_without_hotkeys')
        self.scenario.setUp()
        self.addCleanup(self.scenario.doCleanups)
        self.updater = self.scenario.updater
        self.foreground = patch('src.updater.is_window_in_foreground', return_value=True)
        self.foreground_mock = self.foreground.start()
        self.addCleanup(self.foreground.stop)
        self.notices = []
        self.updater.notification_signal.connect(lambda title, text: self.notices.append((title, text)))

    def tick(self, value):
        self.scenario.tick_map(value)

    def scan_once(self):
        self.tick(100)
        self.tick(100.7)

    def predictions_visible(self):
        visible = False
        for state in self.scenario.maps.states:
            if state.overlay_images is not None:
                visible = bool(state.overlay_images)
            if state.clear_image:
                visible = False
        return visible

    def map_message(self):
        return next((state.automatic_status for state in reversed(self.scenario.maps.states)
                     if state.automatic_status is not None), '')

    def main_kind(self):
        return next((getattr(state, 'map_status_kind', None) for state in reversed(self.scenario.surface.states)
                     if getattr(state, 'map_status_kind', None) is not None), None)

    def modify_detector(self, callback):
        previous = self.updater.detector.detect
        def wrapped(params):
            result = previous(params)
            if params.map_detect_param:
                return callback(params.map_detect_param, result)
            return result
        self.updater.detector.detect = wrapped

    def test_failed_refresh_keeps_cache_without_claiming_new_success(self):
        self.scan_once()
        self.assertTrue(self.predictions_visible())
        self.modify_detector(lambda request, result: SimpleNamespace(map_detect_result=SimpleNamespace(earth_shifting=None))
                             if request.do_match_earth_shifting else result)
        self.updater.map_policy.request('retry')
        self.tick(106)
        self.assertTrue(self.predictions_visible())
        self.assertNotIn('完成', self.map_message())
        self.assertEqual(self.main_kind(), 'cached_failed')
        self.assertIn('上次', self.map_message())

    def test_map_closed_during_scan_cannot_publish_a_success(self):
        def closes(request, result):
            if request.do_match_pattern:
                self.updater.detector.visible = False
            return result
        self.modify_detector(closes)
        self.scan_once()
        self.assertIsNone(self.updater.map_policy.matched_signature)
        self.assertFalse(self.predictions_visible())
        self.assertFalse(self.updater.map_overlay_visible)
        self.assertEqual(self.main_kind(), 'interrupted')

    def test_changed_map_during_scan_cannot_publish_old_capture(self):
        def changes(request, result):
            if request.do_match_pattern:
                self.updater.detector.frame[:] = 200
            return result
        self.modify_detector(changes)
        self.scan_once()
        self.assertIsNone(self.updater.map_policy.matched_signature)
        self.assertFalse(self.predictions_visible())
        self.assertEqual(self.main_kind(), 'interrupted')

    def test_lost_foreground_during_scan_discards_result(self):
        def changes(request, result):
            if request.do_match_pattern:
                self.foreground_mock.return_value = False
            return result
        self.modify_detector(changes)
        self.scan_once()
        self.assertFalse(self.predictions_visible())
        self.assertIsNone(self.updater.map_policy.matched_signature)
        self.assertFalse(self.updater.map_overlay_visible)

    def test_empty_render_never_announces_success(self):
        def empty(request, result):
            if request.do_match_pattern:
                result.map_detect_result.overlay_images = []
            return result
        self.modify_detector(empty)
        self.scan_once()
        self.assertNotIn('完成', self.map_message())
        self.assertEqual(self.main_kind(), 'failed')
        self.assertFalse(self.predictions_visible())

    def test_same_map_refresh_keeps_old_predictions_before_terrain_match(self):
        self.scan_once()
        recorded = []
        def records(request, result):
            if request.do_match_earth_shifting:
                recorded.append((self.predictions_visible(), self.main_kind()))
            return result
        self.modify_detector(records)
        self.updater.map_policy.request('retry')
        self.tick(106)
        self.assertEqual(recorded, [(True, 'refreshing')])

    def test_cached_reopen_does_not_repeat_completion_notice(self):
        self.scan_once()
        self.assertEqual(len(self.notices), 1)
        self.tick(121)
        self.assertEqual(len(self.notices), 1)
        self.updater.detector.visible = False
        self.tick(122)
        self.updater.detector.visible = True
        self.tick(123)
        self.tick(129)
        self.assertEqual(len(self.notices), 1)

    def test_repeated_identical_failure_does_not_spam_notifications(self):
        self.modify_detector(lambda request, result: SimpleNamespace(map_detect_result=SimpleNamespace(earth_shifting=None))
                             if request.do_match_earth_shifting else result)
        self.scan_once()
        self.assertEqual(len(self.notices), 1)
        self.tick(106)
        self.tick(112)
        self.assertEqual(len(self.notices), 1)

    def test_scan_exceeding_deadline_does_not_publish(self):
        def slow(request, result):
            if request.do_match_pattern:
                self.scenario.now = 119
            return result
        self.modify_detector(slow)
        self.scan_once()
        self.assertIsNone(self.updater.map_policy.matched_signature)
        self.assertEqual(self.main_kind(), 'failed')

    def test_ambiguous_candidates_keep_distinct_status(self):
        def ambiguous(request, result):
            if request.do_match_pattern:
                result.map_detect_result.plausible_count = 3
            return result
        self.modify_detector(ambiguous)
        self.scan_once()
        self.assertEqual(self.main_kind(), 'uncertain')
        self.assertIn('共同信息', self.map_message())

    def test_unconfigured_map_shows_actionable_waiting_status(self):
        self.updater.map_region = None
        self.tick(100)
        self.assertEqual(self.main_kind(), 'waiting')

    def test_disabled_notifications_still_publish_visual_status(self):
        self.updater.automation_options.notifications = False
        self.scan_once()
        self.assertEqual(self.main_kind(), 'success')
        self.assertEqual(self.notices, [])

    def test_capture_error_preserves_cache_but_replaces_success_status(self):
        self.scan_once()
        def capture_error(request, result):
            if request.do_match_full_map:
                raise RuntimeError('capture unavailable')
            return result
        self.modify_detector(capture_error)
        self.tick(106)
        self.assertTrue(self.predictions_visible())
        self.assertEqual(self.main_kind(), 'cached_failed')
        self.assertFalse(self.updater.map_overlay_visible)

    def test_failure_status_stays_visible_while_waiting_for_retry(self):
        self.modify_detector(lambda request, result: SimpleNamespace(map_detect_result=SimpleNamespace(earth_shifting=None))
                             if request.do_match_earth_shifting else result)
        self.scan_once()
        self.tick(101)
        self.assertEqual(self.main_kind(), 'failed')

    def test_long_failure_waits_after_completion_before_retrying(self):
        def slow(request, result):
            if request.do_match_pattern:
                self.scenario.now = 119
            return result
        self.modify_detector(slow)
        self.scan_once()
        self.tick(119.1)
        self.assertEqual(self.updater.detector.matches, 1)
        self.assertEqual(self.main_kind(), 'failed')

    def test_worker_capture_failure_replaces_previous_success_status(self):
        self.scan_once()
        self.updater.track_game_and_locate = lambda foreground: None
        def failing_detection():
            self.updater.stop()
            raise RuntimeError('screen capture pipeline unavailable')
        self.updater.detect_and_update_all = failing_detection
        with patch('src.updater.time.sleep'):
            self.updater.run()
        self.assertFalse(self.predictions_visible())
        self.assertEqual(self.main_kind(), 'failed')


if __name__ == '__main__':
    unittest.main()
