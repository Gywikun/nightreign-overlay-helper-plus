# Based on NeuraXmy/nightreign-overlay-helper v0.10.5.
# Added/modified 2026-10-02 and 2026-10-03; see NOTICE.md and LICENSE (GNU AGPL v3).
"""Worker-thread implementation of the automatic desktop workflow."""
from dataclasses import asdict, replace
from queue import SimpleQueue, Empty
import time
import math
import numpy as np
import cv2
from mss import mss

from src.automation import (AutomationOptions, MapRefreshPolicy, DayCueLatch,
                            AlertEngine, normalize_region, restore_hud_region)
from src.enhancement_store import load_options, save_options
from src.window_tracking import AutomaticLocator, REGION_NAMES, game_client_rect
from src.detector.utils import grab_region
from src.config import Config
from src.logger import info, warning


class AutomationRuntime:
    def init_automation(self):
        self.automation_options = load_options()
        self.commands = SimpleQueue()
        self.map_policy = MapRefreshPolicy()
        self.day_cue_latch = DayCueLatch()
        self.alert_engine = AlertEngine()
        self.locator = AutomaticLocator(self.detector)
        self.game_window = None
        self.session_number = 0
        self.timer_revision = 0
        self._last_window_check = -float("inf")
        self._last_auto_locate = -float("inf")
        self._last_diagnostics = -float("inf")
        self._is_game_foreground = False
        self._pending_clean_map = None
        self._diagnostics = {"day": "等待当天开始的 DAY 提示", "rain": "等待有效血条画面",
                             "map": "等待打开完整地图", "art": "按游戏绝招键后检测"}
        self._rain_candidate = None
        self._rain_count = 0
        self._map_feedback = None
        self._map_open_number = 0
        self._map_notice_keys = set()
        self._map_cache = None
        self._displayed_map_images = None

    def submit_command(self, action, payload=None):
        # The updater runs a loop; queued Qt slots would not run until it exits.
        self.commands.put((action, payload))

    def process_automation_commands(self):
        while True:
            try:
                action, payload = self.commands.get_nowait()
            except Empty:
                break
            try:
                if action == "options":
                    current = asdict(self.automation_options)
                    current.update({key: value for key, value in payload.items() if key != "anchors"})
                    self.automation_options = AutomationOptions.from_dict(current)
                    save_options(self.automation_options)
                    self.options_changed_signal.emit(self.automation_options)
                elif action == "anchor_regions":
                    self.remember_region_anchors()
                elif action == "refresh_map":
                    self.map_policy.request()
                    self._diagnostics['refresh_request'] = '重新识别请求已收到'
                    self.emit_diagnostics()
                elif action == "new_round":
                    self.day_cue_latch.suppress(self.get_time())
                    self.start_day1()
                elif action == "correct_timer":
                    self.apply_timer_correction(payload)
                elif action == "diagnostics":
                    self._last_diagnostics = -float("inf")
                    self._last_auto_locate = -float("inf")
                elif action in ("advance_day", "forward_day", "back_day", "toggle_rain", "use_art", "toggle_map"):
                    methods = {"advance_day": self.start_day_by_shortcut, "forward_day": self.foward_day_by_shortcut,
                               "back_day": self.back_day_by_shortcut, "toggle_rain": self.start_in_rain_by_shortcut,
                               "use_art": self.use_art_by_shortcut, "toggle_map": self.show_or_hide_map_overlay_by_shortcut}
                    methods[action]()
            except (TypeError, ValueError, KeyError) as exc:
                warning(f"Invalid automation command {action}: {exc}")
                self.notification_signal.emit("操作未应用", str(exc))

    def remember_region_anchors(self):
        window = game_client_rect()
        if not window:
            return
        anchors = dict(self.automation_options.anchors)
        for name in REGION_NAMES:
            anchor = normalize_region(getattr(self, name), window)
            if anchor:
                anchors[name] = anchor
        self.automation_options = replace(self.automation_options, anchors=anchors,
                                          anchor_geometry={"width": window[2], "height": window[3]})
        save_options(self.automation_options)

    def reset_round_artifacts(self):
        self.session_number += 1
        self.timer_revision += 1
        self.in_rain_start_time = None
        self.art_start_time = None
        self.art_type = None
        self.to_detect_art_time = None
        self.hp_length = None
        self._rain_candidate, self._rain_count = None, 0
        self.map_policy.reset()
        self.alert_engine.reset()
        self._pending_clean_map = None
        self._map_feedback = None
        self._diagnostics.pop('refresh_request', None)
        self._map_open_number = 0
        self._map_notice_keys.clear()
        self._map_cache = None
        self.last_map_pattern_match_time = 0.0
        self.detector.hp_detector.recent_lengths.clear()
        self.detector.hp_detector.last_valid_length = None
        self.detector.hp_detector.stable_count = 0
        self.update_map_overlay_images(None)
        self.hide_map_overlay()
        self.publish_map_feedback("waiting", "地图：新局已清理旧信息，等待开图")

    def apply_timer_correction(self, values):
        from src.updater import Phase
        day, phase, elapsed = int(values["day"]), int(values["phase"]), float(values["elapsed"])
        if day not in (1, 2, 3) or phase not in range(5) or not 0 <= elapsed <= 7200:
            raise ValueError("当天、阶段或已过时间无效")
        if day == 3:
            phase = 4
        if phase < 4 and elapsed >= Config.get().day_period_seconds[phase]:
            raise ValueError("已过时间应小于当前阶段长度")
        if day == 1 and (self.day != 1 or self.current_phase is None):
            self.reset_round_artifacts()
        self.day, self.current_phase = day, Phase(phase)
        self.phase_start_time = self.get_time() - elapsed
        self.timer_revision += 1
        self.alert_engine.reset()
        self.day_cue_latch.suppress(self.get_time())
        self.map_policy.request("计时状态修正")
        self.notification_signal.emit("计时已修正", f"第 {day} 天，已过 {int(elapsed)} 秒")

    def track_game_and_locate(self, foreground):
        self._is_game_foreground = foreground
        now = self.get_time()
        if now - self._last_window_check >= 1:
            self._last_window_check = now
            window = game_client_rect()
            old = self.game_window
            self.game_window = window
            if window and self.automation_options.follow_window:
                anchors = self.automation_options.anchors
                if not anchors:
                    self.remember_region_anchors()
                    anchors = self.automation_options.anchors
                changed = {}
                for name, anchor in anchors.items():
                    region = restore_hud_region(name, anchor, window, self.automation_options.anchor_geometry)
                    if name in REGION_NAMES and region and getattr(self, name) != region:
                        setattr(self, name, region)
                        changed[name] = region
                if changed:
                    self.regions_changed_signal.emit(changed)
                if old and old != window:
                    self.map_policy.request("游戏窗口尺寸或位置变化")
                    if self.has_map_cache():
                        self.restore_cached_map()
                        self.publish_map_feedback("cached", "地图：保留已识别信息，后台适配窗口", result_time=self._map_cache["updated_at"])
                    else:
                        self.update_map_overlay_images(None)
                        self.publish_map_feedback("waiting", "地图：窗口已变化，等待重新扫描")
            if old and not window:
                self.reset_round_artifacts()
                self.day = self.current_phase = self.phase_start_time = None
        if foreground and self.game_window and now - self._last_auto_locate >= 2:
            self._last_auto_locate = now
            if self.detector.sct is None:
                self.detector.sct = mss()
            frame = np.array(grab_region(self.detector.sct, self.game_window))
            changed = {}
            if self.automation_options.automatic_regions:
                if self.dayx_detect_enabled and self.day1_detect_region is None:
                    region = self.locator.find_day_region(frame, self.dayx_detect_lang, self.hdr_processing_enabled)
                    if region:
                        changed["day1_detect_region"] = region
                if (self.in_rain_detect_enabled and self.hpcolor_detect_region is None) or (self.hp_detect_enabled and self.hpbar_region is None):
                    for name, region in self.locator.find_health_regions(frame, self.hdr_processing_enabled).items():
                        if getattr(self, name) is None:
                            changed[name] = region
                if self.map_detect_enabled and self.map_region is None:
                    region = self.locator.find_map_region(frame)
                    if region:
                        changed["map_region"] = region
            if changed:
                wx, wy, _, _ = self.game_window
                for name, region in changed.items():
                    setattr(self, name, [region[0] + wx, region[1] + wy, region[2], region[3]])
                self.remember_region_anchors()
                self.regions_changed_signal.emit({name: getattr(self, name) for name in changed})
                info(f"Automatically located regions: {list(changed)}")
            self._diagnostics["previews"] = self.capture_previews(frame)
            self.sample_automatic_health_color(frame)
        if now - self._last_diagnostics >= 1:
            self._last_diagnostics = now
            self.emit_diagnostics()

    def capture_previews(self, frame):
        from PIL import Image
        previews = {}
        for name in REGION_NAMES:
            region = getattr(self, name)
            if not region or not self.game_window:
                continue
            x, y = region[0] - self.game_window[0], region[1] - self.game_window[1]
            w, h = region[2:]
            if x < 0 or y < 0 or x + w > frame.shape[1] or y + h > frame.shape[0]:
                continue
            image = Image.fromarray(frame[y:y+h, x:x+w]).convert("RGB")
            image.thumbnail((260, 110))
            previews[name] = (image.width, image.height, image.tobytes())
        return previews

    def sample_automatic_health_color(self, frame):
        if not self.automation_options.automatic_regions or not self.hpcolor_detect_region:
            return
        wx, wy, _, _ = self.game_window
        x, y, w, h = self.hpcolor_detect_region
        x, y = x - wx, y - wy
        if x < 0 or y < 0 or x+w > frame.shape[1] or y+h > frame.shape[0]:
            return
        pixels = cv2.cvtColor(frame[y:y+h, x:x+w], cv2.COLOR_RGB2HLS).reshape(-1, 3)
        valid = pixels[(pixels[:, 2] >= 65) & (pixels[:, 1] >= 35)]
        if len(valid) < len(pixels) * .6:
            return
        color = [int(value) for value in np.median(valid, axis=0)]
        if color[0] <= 22:
            name = "not_in_rain_hls"
        elif color[0] >= 140:
            name = "in_rain_hls"
        else:
            return
        if self.hdr_processing_enabled:
            name += "_hdr"
        if getattr(self, name) is None:
            setattr(self, name, color)
            self.colors_changed_signal.emit({name: color})

    def refresh_request_status(self):
        if 'refresh_request' not in self._diagnostics:
            return ''
        pending = self.map_policy.pending_reason == '手动刷新'
        clean_capture = self._pending_clean_map and self._pending_clean_map[0] == '手动刷新'
        if pending or clean_capture:
            if not self.map_detect_enabled:
                return '请求已收到：地图识别已关闭，请在主设置中开启“启用地图识别”。'
            if not self.game_window:
                return '请求已收到：等待游戏窗口，请启动 ELDEN RING NIGHTREIGN。'
            if not self._is_game_foreground:
                return '请求已收到：请关闭设置并切回游戏，展示完整地图。'
            if self.map_region is None:
                return '请求已收到：等待完整地图区域定位，必要时使用“检测自检”备用框选。'
            if not self.current_is_full_map:
                return '请求已收到：请打开完整地图并缩放到最小。'
            if clean_capture:
                return '请求已收到：正在准备不含旧标注的截图。'
            remaining = self.automation_options.map_min_interval - (self.get_time() - self.map_policy.last_attempt)
            if remaining > 0:
                return f'请求已收到：等待扫描间隔，还需约 {math.ceil(remaining)} 秒。'
            if self.map_policy.stable_since is None or self.get_time() - self.map_policy.stable_since < self.automation_options.map_stable_seconds:
                return '请求已收到：等待画面稳定，请保持完整地图打开。'
            return '请求已收到：条件已满足，等待开始识别。'
        return self._map_feedback[1] if self._map_feedback else self._diagnostics['refresh_request']

    def emit_diagnostics(self):
        snapshot = dict(self._diagnostics)
        snapshot["window"] = self.game_window
        snapshot["foreground"] = self._is_game_foreground
        snapshot['refresh_request'] = self.refresh_request_status()
        snapshot["regions"] = {name: getattr(self, name) for name in REGION_NAMES}
        snapshot["timer"] = (self.day, self.current_phase.value if self.current_phase is not None else None,
                             max(0, self.get_time() - self.phase_start_time) if self.phase_start_time is not None else 0)
        if not self._is_game_foreground:
            snapshot["previews"] = {}
        self.diagnostics_signal.emit(snapshot)

    def poll_alerts(self):
        options, config, now = self.automation_options, Config.get(), self.get_time()
        phase = self.current_phase.value if self.current_phase is not None else None
        remaining = config.day_period_seconds[phase] - (now - self.phase_start_time) if phase is not None and phase < 4 else None
        token = (self.session_number, self.timer_revision, self.day, phase)
        thresholds = [options.circle_early_seconds, options.circle_late_seconds] if options.circle_alerts and phase in (0, 2) else []
        for seconds in self.alert_engine.observe("circle", token if remaining is not None else None, remaining, thresholds):
            self.send_alert("缩圈提醒", f"距离下一次缩圈约 {max(0, round(remaining))} 秒")
        rain_remaining = config.deadly_nightrain_seconds - (now - self.in_rain_start_time) if self.in_rain_start_time is not None else None
        for seconds in self.alert_engine.observe("rain", self.in_rain_start_time, rain_remaining, [options.rain_seconds] if options.rain_alerts else []):
            self.send_alert("雨中冒险提醒", f"距离设定的雨中时限约 {max(0, round(rain_remaining))} 秒")
        art = config.art_info.get(self.art_type)
        art_remaining = art["duration"] - max(0, now - self.art_start_time - art.get("delay", 0)) if art and self.art_start_time is not None else None
        for seconds in self.alert_engine.observe("art", self.art_start_time if art else None, art_remaining, [options.art_seconds] if options.art_alerts else []):
            self.send_alert("绝招效果提醒", f"{art['text']}剩余约 {max(0, round(art_remaining))} 秒")

    def send_alert(self, title, message):
        if self.automation_options.notifications and self._is_game_foreground:
            self.notification_signal.emit(title, message)
