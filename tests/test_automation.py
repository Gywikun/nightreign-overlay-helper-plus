import unittest
from dataclasses import replace
from types import SimpleNamespace

from src.automation import (AutomationOptions, MapRefreshPolicy, DayCueLatch, AlertEngine,
                            normalize_region, restore_region, restore_hud_region, plausible_matches, consensus_pattern)
from src.detector.map_info import MapPattern, Construct


class MapPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = MapRefreshPolicy()
        self.options = AutomationOptions()
        self.frame = [50] * 576

    def initial_match(self):
        self.assertIsNone(self.policy.observe(True, self.frame, 0, self.options))
        self.assertEqual(self.policy.observe(True, self.frame, .7, self.options), "首次开图")
        self.policy.complete(self.frame, .8, True)

    def test_open_requires_stable_frame(self):
        self.assertIsNone(self.policy.observe(True, self.frame, 0, self.options))
        self.assertIsNone(self.policy.observe(True, self.frame, .2, self.options))
        self.assertEqual(self.policy.observe(True, self.frame, .7, self.options), "首次开图")

    def test_animation_restarts_stability_wait(self):
        self.policy.observe(True, self.frame, 0, self.options)
        changed = [100] * 576
        self.assertIsNone(self.policy.observe(True, changed, .5, self.options))
        self.assertIsNone(self.policy.observe(True, changed, .9, self.options))
        self.assertEqual(self.policy.observe(True, changed, 1.2, self.options), "首次开图")

    def test_closed_map_does_not_match(self):
        for now in (0, 20, 60):
            self.assertIsNone(self.policy.observe(False, None, now, self.options))

    def test_reopen_respects_rate_limit_then_refreshes(self):
        self.options.refresh_on_open = True  # Explicit opt-in remains supported.
        self.initial_match()
        self.policy.observe(False, None, 1, self.options)
        self.policy.observe(True, self.frame, 2, self.options)
        self.assertIsNone(self.policy.observe(True, self.frame, 3, self.options))
        self.assertEqual(self.policy.observe(True, self.frame, 6, self.options), "重新开图")

    def test_periodic_refresh_while_map_stays_open(self):
        self.initial_match()
        self.assertIsNone(self.policy.observe(True, self.frame, 10, self.options))
        self.assertEqual(self.policy.observe(True, self.frame, 21, self.options), "定时更新")

    def test_cursor_noise_does_not_trigger_refresh(self):
        self.initial_match()
        changed = self.frame.copy()
        changed[0] = 255
        self.assertIsNone(self.policy.observe(True, changed, 6, self.options))

    def test_changed_map_refreshes_after_stability(self):
        self.initial_match()
        changed = [80] * 576
        self.assertIsNone(self.policy.observe(True, changed, 6, self.options))
        self.assertEqual(self.policy.observe(True, changed, 6.7, self.options), "地图画面变化")

    def test_failed_match_is_retried_with_backoff(self):
        self.initial_match()
        self.policy.request()
        self.assertEqual(self.policy.observe(True, self.frame, 6, self.options), "手动刷新")
        self.policy.complete(self.frame, 6.1, False)
        self.assertIsNone(self.policy.observe(True, self.frame, 7, self.options))
        self.assertEqual(self.policy.observe(True, self.frame, 11.1, self.options), "识别未完成，自动重试")

    def test_disabling_automatic_mode_preserves_manual_refresh(self):
        self.options.automatic_map = False
        self.policy.observe(True, self.frame, 0, self.options)
        self.assertIsNone(self.policy.observe(True, self.frame, 1, self.options))
        self.policy.request()
        self.assertEqual(self.policy.observe(True, self.frame, 2, self.options), "手动刷新")

    def test_new_round_does_not_reuse_old_signature(self):
        self.initial_match()
        self.policy.reset()
        self.assertIsNone(self.policy.matched_signature)
        self.policy.observe(True, self.frame, 20, self.options)
        self.assertEqual(self.policy.observe(True, self.frame, 21, self.options), "首次开图")


class TimerPolicyTests(unittest.TestCase):
    def test_day_banner_starts_once_for_many_frames(self):
        latch = DayCueLatch()
        events = [latch.observe(1, index * .2) for index in range(30)]
        self.assertEqual([event for event in events if event], [1])

    def test_short_occlusion_does_not_start_new_round(self):
        latch = DayCueLatch()
        latch.observe(1, 0)
        self.assertEqual(latch.observe(1, .2), 1)
        for now in (.4, .6, .8):
            latch.observe(None, now)
        self.assertIsNone(latch.observe(1, 1))
        self.assertIsNone(latch.observe(1, 1.2))

    def test_next_day_and_later_new_round_are_detected(self):
        latch = DayCueLatch()
        latch.observe(1, 0)
        latch.observe(1, .2)
        latch.observe(2, 20)
        self.assertEqual(latch.observe(2, 20.2), 2)
        for now in (30, 31, 32):
            latch.observe(None, now)
        latch.observe(1, 40)
        self.assertEqual(latch.observe(1, 40.2), 1)

    def test_manual_correction_is_not_immediately_overwritten(self):
        latch = DayCueLatch()
        latch.suppress(10)
        self.assertIsNone(latch.observe(2, 11))
        self.assertIsNone(latch.observe(2, 12))

    def test_alerts_cross_thresholds_once(self):
        engine = AlertEngine()
        actual = []
        for seconds in (35, 31, 29, 28, 11, 9, 8, 7):
            actual.extend(engine.observe("circle", "day1", seconds, [30, 10]))
        self.assertEqual(actual, [30, 10])

    def test_late_start_does_not_replay_past_alerts(self):
        engine = AlertEngine()
        self.assertEqual(engine.observe("circle", "day1", 8, [30, 10]), [])
        self.assertEqual(engine.observe("circle", "day1", 7, [30, 10]), [])

    def test_timer_correction_and_new_round_reset_alert_tokens(self):
        engine = AlertEngine()
        engine.observe("rain", "round1", 12, [10])
        self.assertEqual(engine.observe("rain", "round1", 9, [10]), [10])
        engine.observe("rain", "round2", 12, [10])
        self.assertEqual(engine.observe("rain", "round2", 9, [10]), [10])

    def test_disabled_alerts_do_not_fire(self):
        engine = AlertEngine()
        engine.observe("art", 1, 5, [])
        self.assertEqual(engine.observe("art", 1, 2, []), [])


class CalibrationAndConsensusTests(unittest.TestCase):
    def test_window_move_and_resolution_change(self):
        anchor = normalize_region([500, 250, 400, 400], [100, 50, 1000, 800])
        self.assertEqual(restore_region(anchor, [200, 100, 2000, 1600]), [1000, 500, 800, 800])

    def test_negative_monitor_coordinates_are_supported(self):
        anchor = normalize_region([-1700, 100, 300, 200], [-1920, 0, 1920, 1080])
        self.assertEqual(restore_region(anchor, [-1920, 0, 1920, 1080]), [-1700, 100, 300, 200])

    def test_ultrawide_change_preserves_map_square_and_right_anchor(self):
        original = [544, 85, 372, 372]
        anchor = normalize_region(original, [0, 0, 960, 540])
        self.assertEqual(restore_hud_region("map_region", anchor, [0, 0, 1260, 540], {"width": 960, "height": 540}),
                         [844, 85, 372, 372])

    def test_ultrawide_change_preserves_left_health_and_center_day(self):
        reference = {"width": 960, "height": 540}
        health = normalize_region([83, 22, 19, 2], [0, 0, 960, 540])
        day = normalize_region([417, 275, 128, 34], [0, 0, 960, 540])
        self.assertEqual(restore_hud_region("hpcolor_detect_region", health, [0, 0, 1260, 540], reference), [83, 22, 19, 2])
        self.assertEqual(restore_hud_region("day1_detect_region", day, [0, 0, 1260, 540], reference), [567, 275, 128, 34])

    def test_outside_window_and_invalid_options_are_rejected(self):
        self.assertIsNone(normalize_region([5, 5, 30, 30], [100, 100, 800, 600]))
        values = AutomationOptions.from_dict({"volume": 500, "automatic_map": "false", "map_refresh_seconds": -1,
                                              "map_min_interval": float("nan"), "anchors": {"map_region": [0, 0, 0, 0]}})
        self.assertEqual(values.volume, 100)
        self.assertTrue(values.automatic_map)
        self.assertEqual(values.map_refresh_seconds, 5)
        self.assertEqual(values.anchors, {})

    def pattern(self):
        return MapPattern(id=1, nightlord=0, earth_shifting=0, day1_boss=1, day1_extra_boss=-1,
                          day1_pos=(100, 100), day2_boss=2, day2_extra_boss=-1, day2_pos=(200, 200),
                          day2_pos_idx=123, treasure=8000, rot_rew=1, event_value=0, event_flag=0,
                          evpat_value=0, evpat_flag=0, pos_constructions={(10, 10): Construct(3000), (20, 20): Construct(3200)})

    def test_ambiguous_predictions_are_omitted_from_consensus(self):
        first = self.pattern()
        second = replace(first, id=2, nightlord=1, day1_boss=3, treasure=8001,
                         pos_constructions={(10, 10): Construct(3000), (20, 20): Construct(3400)})
        common = consensus_pattern([first, second])
        self.assertIsNone(common.day1_pos)
        self.assertEqual(common.day2_pos, (200, 200))
        self.assertEqual(common.nightlord, -1)
        self.assertEqual(common.treasure, 0)
        self.assertEqual(set(common.pos_constructions), {(10, 10)})
        self.assertEqual(len(first.pos_constructions), 2)

    def test_candidate_scores_are_not_treated_as_probabilities(self):
        matches = [SimpleNamespace(error=0, score=100), SimpleNamespace(error=2, score=95), SimpleNamespace(error=10, score=80)]
        self.assertEqual(plausible_matches(matches), matches[:2])


if __name__ == "__main__":
    unittest.main()
