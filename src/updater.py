# Based on NeuraXmy/nightreign-overlay-helper v0.10.5.
# Added/modified 2026-10-02; see NOTICE.md and LICENSE (GNU AGPL v3).
from PyQt6.QtCore import QObject, pyqtSignal
import time
from enum import Enum
from PIL import Image

from src.common import GAME_WINDOW_TITLE
from src.config import Config
from src.logger import info, warning, error
from src.ui.input import InputWorker
from src.ui.overlay import OverlayWidget, OverlayUIState
from src.ui.map_overlay import MapOverlayWidget, MapOverlayUIState
from src.ui.hp_overlay import HpOverlayWidget, HpOverlayUIState
from src.detector import (
    DetectorManager, 
    DetectParam, 
    DayDetectParam,
    RainDetectParam,
    MapDetectParam,
    HpDetectParam,
    ArtDetectParam,
)
from src.detector.map_info import MapPattern
from src.ui.utils import is_window_in_foreground
from src.automation_runtime import AutomationRuntime
from src.window_tracking import map_signature
from src.automation import signature_distance

MAP_SCAN_TIMEOUT_SECONDS = 15


class DoMatchMapPatternFlag(Enum):
    FALSE = 0
    PREPARE = 1
    TRUE = 2


class Phase(Enum):
    FIRST_CIRCLE_STABLE = 0
    FIRST_CIRCLE_SHRINK = 1
    SECOND_CIRCLE_STABLE = 2
    SECOND_CIRCLE_SHRINK = 3
    NIGHT_BOSS = 4


def format_period(seconds: int) -> str:
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}:{secs:02d}"


class Updater(QObject, AutomationRuntime):
    update_overlay_ui_state_signal = pyqtSignal(OverlayUIState)
    update_map_overlay_ui_state_signal = pyqtSignal(MapOverlayUIState)
    hp_overlay_ui_state_signal = pyqtSignal(HpOverlayUIState)
    input_block_signals_signal = pyqtSignal(bool)
    notification_signal = pyqtSignal(str, str)
    diagnostics_signal = pyqtSignal(object)
    regions_changed_signal = pyqtSignal(object)
    options_changed_signal = pyqtSignal(object)
    colors_changed_signal = pyqtSignal(object)
    map_feedback_status_signal = pyqtSignal(str)

    def __init__(
        self, 
        input: InputWorker,
        overlay: OverlayWidget, 
        map_overlay: MapOverlayWidget,
        hp_overlay: HpOverlayWidget,
    ):
        super().__init__()
        self._running = False

        self.is_setting_opened = False
        self.is_menu_opened = False

        self.detector = DetectorManager()
        self.only_detect_when_game_foreground: bool = False
        self.detect_interval = 0.2

        self.input_block_signals_signal.connect(input.blockSignals)

        self.overlay = overlay
        self.update_overlay_ui_state_signal.connect(self.overlay.update_ui_state)
        self.day: int = None
        self.current_phase: Phase = None
        self.phase_start_time: float = None
        self.dayx_detect_enabled: bool = True
        self.day1_detect_region = None
        self.dayx_detect_lang: str = "chs"
        
        self.in_rain_start_time: float = None
        self.in_rain_detect_enabled: bool = True
        self.hpcolor_detect_region: tuple[int] = None
        self.in_rain_hls: tuple[int] = None
        self.not_in_rain_hls: tuple[int] = None
        self.in_rain_hls_hdr: tuple[int] = None
        self.not_in_rain_hls_hdr: tuple[int] = None

        self.map_overlay = map_overlay
        self.update_map_overlay_ui_state_signal.connect(self.map_overlay.update_ui_state)
        self.map_detect_enabled: bool = True
        self.map_region: tuple[int] = None
        self.current_is_full_map: bool = False
        self.do_match_map_pattern_flag: DoMatchMapPatternFlag = DoMatchMapPatternFlag.TRUE
        self.map_overlay_visible: bool = False
        self.last_map_pattern_match_time: float = 0.0
        self.map_pattern_return_topk: int = 5

        self.hp_overlay = hp_overlay
        self.hp_overlay_ui_state_signal.connect(self.hp_overlay.update_ui_state)
        self.hp_detect_enabled: bool = True
        self.hp_detect_keep_last_valid: bool = False
        self.hpbar_region: tuple[int] = None
        self.hp_length: int = None

        self.art_detect_enabled: bool = False
        self.to_detect_art_time: float = 0.0
        self.art_start_time: float = 0.0
        self.art_region: tuple[int] = None
        self.art_type: str = None

        # HDR图像处理设置
        self.hdr_processing_enabled: bool = False
        self.init_automation()


    def get_time(self) -> float:
        return time.time() * Config.get().time_scale

    # =============== Day and Phase Management =============== #

    def start_day1(self):
        self.reset_round_artifacts()
        self.day = 1
        self.current_phase = Phase.FIRST_CIRCLE_STABLE
        self.phase_start_time = self.get_time()
        info("Day 1 started.")
        self.set_to_detect_map_pattern_once()

    def start_day2(self):
        self.day = 2
        self.current_phase = Phase.FIRST_CIRCLE_STABLE
        self.phase_start_time = self.get_time()
        info("Day 2 started.")
        self.map_policy.request("第二天开始")

    def start_day3(self):
        self.day = 3
        self.current_phase = Phase.NIGHT_BOSS
        self.phase_start_time = self.get_time()
        info("Day 3 started.")
        self.hide_map_overlay()

    def start_day_by_shortcut(self):
        self.day_cue_latch.suppress(self.get_time())
        if self.day is None:
            self.start_day1()
            info("Day 1 started by shortcut.")
        elif self.day == 1:
            self.start_day2()
            info("Day 2 started by shortcut.")
        elif self.day in (2, 3):
            self.start_day1()
            info("Day 1 started by shortcut.")

    def foward_day_by_shortcut(self):
        if self.phase_start_time is not None:
            self.phase_start_time -= Config.get().foward_day_seconds

    def back_day_by_shortcut(self):
        if self.phase_start_time is not None:
            self.phase_start_time += Config.get().back_day_seconds

    def get_phase_progress_text(self) -> tuple[float, str]:
        if self.day is None:
            progress = 0.0
            text = None
        elif self.day == 3:
            progress = 4.0
            t = self.get_time() - self.phase_start_time
            text = f"{format_period(int(t))}"
        elif self.current_phase == Phase.NIGHT_BOSS:
            progress = 4.0
            t = self.get_time() - self.phase_start_time
            text = f"夜晚BOSS战 {format_period(int(t))}"
        else:
            index = self.current_phase.value
            t = self.get_time() - self.phase_start_time
            total = Config.get().day_period_seconds[index]
            progress = t / total + index
            circle_no = "一" if index < 2 else "二"
            action_text = "开始缩圈" if index % 2 == 0 else "缩圈结束"
            text = f"{format_period(int(total - t))} 后第{circle_no}圈{action_text}"
        if self.day is not None:
            text = f"DAY {'I' * self.day} - " + text
        return progress, text
    
    def update_phase_timer(self):
        config = Config.get()
        if self.current_phase is not None:
            index = self.current_phase.value
            phase_length = None if index >= 4 else config.day_period_seconds[index]
            while phase_length is not None and self.get_time() - self.phase_start_time >= phase_length:
                self.current_phase = Phase(self.current_phase.value + 1)
                self.phase_start_time += phase_length
                info(f"Phase progress to {self.current_phase.name}.")
                index = self.current_phase.value
                phase_length = None if index >= 4 else config.day_period_seconds[index]
            if self.get_time() < self.phase_start_time:
                if self.current_phase.value >= 1:
                    self.current_phase = Phase(self.current_phase.value - 1)
                    self.phase_start_time -= config.day_period_seconds[self.current_phase.value]
                    info(f"Phase back to {self.current_phase.name}.")
                else:
                    self.phase_start_time = self.get_time()

    def detect_and_update_dayx(self):
        if not self.dayx_detect_enabled:
            return
        param = DetectParam(
            day_detect_param=DayDetectParam(
                day1_region=self.day1_detect_region,
                lang=self.dayx_detect_lang,
                hdr_processing_enabled=self.hdr_processing_enabled,
            )
        )
        result = self.detector.detect(param)
        day_result = result.day_detect_result
        candidates = [(index, getattr(day_result, f"score_day{index}")) for index in (1, 2, 3)
                      if getattr(day_result, f"start_day{index}")]
        cue = min(candidates, key=lambda item: item[1] if item[1] is not None else float("inf"))[0] if candidates else None
        self._diagnostics["day"] = f"检测到 DAY {'I' * cue}" if cue else "等待当天开始的 DAY 提示（平时不会显示）"
        event = self.day_cue_latch.observe(cue, self.get_time())
        if event:
            getattr(self, f"start_day{event}")()

    # =============== In Rain Management =============== #

    def start_in_rain(self):
        self.in_rain_start_time = self.get_time()
        info("Started in rain.")

    def stop_in_rain(self):
        self.in_rain_start_time = None
        info("Stopped in rain.")

    def start_in_rain_by_shortcut(self):
        if self.in_rain_start_time is None:
            self.start_in_rain()
            info("Started in rain by shortcut.")
        else:
            self.stop_in_rain()
            info("Stopped in rain by shortcut.")

    def get_in_rain_progress_text(self) -> tuple[float, str]:
        if self.in_rain_start_time is None:
            return 0, ""
        t = self.get_time() - self.in_rain_start_time
        total = Config.get().deadly_nightrain_seconds
        progress = 1.0 - min(t / total, 1.0)
        percent = int(100 * (1.0 - progress))
        text = f"雨中冒险倒计时 {format_period(int(max(total - t, 0)))} - {percent}%"
        return progress, text

    def detect_and_update_in_rain(self):
        if not self.in_rain_detect_enabled:
            return
        param = DetectParam(
            rain_detect_param=RainDetectParam(
                in_rain_hls=self.in_rain_hls,
                not_in_rain_hls=self.not_in_rain_hls,
                in_rain_hls_hdr=self.in_rain_hls_hdr,
                not_in_rain_hls_hdr=self.not_in_rain_hls_hdr,
                hpcolor_region=self.hpcolor_detect_region,
                hdr_processing_enabled=self.hdr_processing_enabled,
            )
        )
        result = self.detector.detect(param)
        is_in_rain = result.rain_detect_result.is_in_rain
        self._diagnostics["rain"] = "雨中血条" if is_in_rain else "正常血条" if is_in_rain is False else "未取得有效血条颜色，等待画面"
        self._rain_count = self._rain_count + 1 if is_in_rain == self._rain_candidate else 1
        self._rain_candidate = is_in_rain
        if self._rain_count < 2:
            return
        if is_in_rain is not None:
            if is_in_rain and self.in_rain_start_time is None:
                self.start_in_rain()
            if not is_in_rain and self.in_rain_start_time is not None:
                self.stop_in_rain()

    # =============== Map Pattern Management =============== #

    def set_to_detect_map_pattern_once(self):
        self.do_match_map_pattern_flag = DoMatchMapPatternFlag.PREPARE
        self.map_policy.request("请求识别地图")
        info("Set to detect map pattern once.")

    def update_overlay_match_map_pattern_text(self):
        match_ready = self.do_match_map_pattern_flag != DoMatchMapPatternFlag.FALSE and self.map_detect_enabled
        if match_ready:
            self.update_overlay_ui_state_signal.emit(OverlayUIState(
                map_pattern_match_text=" - 地图识别就绪",
            ))
        else:
            self.update_overlay_ui_state_signal.emit(OverlayUIState(
                map_pattern_match_text="",
            ))

    def update_map_overlay_images(self, images: list[Image.Image] | None, earth_shifting: int | None = None):
        self._displayed_map_images = images
        if images is None:
            self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
                clear_image=True,
                map_pattern_match_time=0,
                map_pattern_matching=False,
                display_crystal_layout=False,
                automatic_status="等待地图自动更新",
            ))
            info("Clear map overlay image.")
        else:
            self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
                overlay_images=images,
                x=self.map_region[0],
                y=self.map_region[1],
                w=self.map_region[2],
                h=self.map_region[3],
                map_pattern_match_time=time.time(),
                map_pattern_matching=False,
                display_crystal_layout=(earth_shifting == 4),
            ))
            info("Update map overlay image.")

    def show_map_overlay(self):
        if not self.map_overlay_visible:
            self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
                opacity=1.0,
                x=self.map_region[0],
                y=self.map_region[1],
                w=self.map_region[2],
                h=self.map_region[3],
            ))
            self.map_overlay_visible = True
            info("Show map overlay.")

    def hide_map_overlay(self):
        if self.map_overlay_visible:
            self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
                opacity=0.0,
            ))
            self.map_overlay_visible = False
            info("Hide map overlay.")

    def show_or_hide_map_overlay_by_shortcut(self):
        if self.map_overlay_visible:
            self.hide_map_overlay()
        else:
            self.show_map_overlay()

    def has_map_cache(self):
        return bool(self._map_cache and self._map_cache["session"] == self.session_number and self._map_cache["images"])

    def restore_cached_map(self):
        if not self.has_map_cache():
            return False
        cache = self._map_cache
        if self._displayed_map_images is not cache["images"]:
            self.update_map_overlay_images(cache["images"], cache["terrain"])
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
            x=self.map_region[0], y=self.map_region[1], w=self.map_region[2], h=self.map_region[3],
        ))
        self.show_map_overlay()
        return True

    def publish_map_feedback(self, kind, message, *, clear=False, notify=False, started=0.0, result_time=None):
        """Publish one consistent state to diagnostics, HUD, and map overlay."""
        if clear:
            self.update_map_overlay_images(None)
        if self._map_feedback == (kind, message) and not clear:
            return
        self._map_feedback = (kind, message)
        self.map_feedback_status_signal.emit(kind)
        self._diagnostics["map"] = message
        stamp = (result_time if result_time is not None else time.time()) if kind in ("success", "uncertain", "cached", "cached_failed") else started if kind in ("scanning", "refreshing") else 0.0
        self.update_overlay_ui_state_signal.emit(OverlayUIState(
            map_status_text=message, map_status_kind=kind, map_status_time=stamp,
        ))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
            automatic_status=message, map_status_kind=kind, map_pattern_matching=kind in ("scanning", "refreshing"),
            scan_started_time=started if kind in ("scanning", "refreshing") else 0.0,
            map_pattern_match_time=(self._map_cache["updated_at"] if kind == "refreshing" and self.has_map_cache() else stamp if kind in ("success", "uncertain", "cached", "cached_failed") else 0.0),
        ))
        self.emit_diagnostics()
        key = (self.session_number, self._map_open_number, kind)
        if notify and self.automation_options.notifications and self._is_game_foreground and key not in self._map_notice_keys:
            self._map_notice_keys.add(key)
            titles = {"success": "地图扫描完成", "uncertain": "地图已更新：存在多个候选",
                      "failed": "地图扫描未成功", "interrupted": "本次地图结果未采用"}
            self.notification_signal.emit(titles.get(kind, "地图识别"), message)

    def reject_map_scan(self, signature, message, kind="failed", *, hide=False):
        self.map_policy.complete(signature, self.get_time(), False)
        if self.has_map_cache():
            self.restore_cached_map()
            self.publish_map_feedback("cached_failed", "地图：本次更新未采用，保留上次信息", result_time=self._map_cache["updated_at"])
        else:
            self.publish_map_feedback(kind, message, clear=True, notify=True)
        if hide:
            self.hide_map_overlay()
        else:
            self.show_map_overlay()

    def detect_and_update_map(self):
        if not self.map_detect_enabled or not self._is_game_foreground or self.map_region is None:
            self.hide_map_overlay()
            self.current_is_full_map = False
            self.map_policy.observe(False, None, self.get_time(), self.automation_options)
            message = "地图识别已关闭" if not self.map_detect_enabled else "地图：等待返回游戏" if not self._is_game_foreground else "地图：等待自动定位，请打开完整地图"
            self.publish_map_feedback("disabled" if not self.map_detect_enabled else "waiting", message)
            return
   
        param = DetectParam(
            map_detect_param=MapDetectParam(
                map_region=self.map_region,
                do_match_full_map=True,
                hdr_processing_enabled=self.hdr_processing_enabled,
            )
        )
        try:
            result = self.detector.detect(param)
        except Exception as exc:
            warning(f"Full-map capture failed: {exc}")
            self.reject_map_scan(None, "地图：当前画面无法检测，旧标注已隐藏，将自动重试", hide=True)
            return

        is_full_map = result.map_detect_result.is_full_map
        map_img = result.map_detect_result.img
        was_full_map = self.current_is_full_map
        self.current_is_full_map = bool(is_full_map)
        if is_full_map and not was_full_map:
            self._map_open_number += 1
            if self.has_map_cache():
                self.restore_cached_map()
                self.publish_map_feedback("cached", "地图：沿用上次已识别信息", result_time=self._map_cache["updated_at"])
        now = self.get_time()
        signature = map_signature(map_img) if is_full_map else None
        reason = self.map_policy.observe(bool(is_full_map), signature, now, self.automation_options)
        if not is_full_map:
            self.hide_map_overlay()
            self._pending_clean_map = None
            if not self._map_feedback or self._map_feedback[0] != "interrupted":
                self.publish_map_feedback("waiting", "地图：未显示完整地图，等待开图或缩放到最小")
            return
        if self._pending_clean_map:
            if now < self._pending_clean_map[1]:
                return
            reason = self._pending_clean_map[0]
            self._pending_clean_map = None
        elif reason and not self.map_overlay.capture_excluded:
            # On older Windows, explicitly hide only for the clean capture.
            self.hide_map_overlay()
            self._pending_clean_map = (reason, now + .3)
            return
        if not reason:
            if self.map_policy.matched_signature is not None and signature_distance(signature, self.map_policy.matched_signature) > 6:
                if self.has_map_cache():
                    self.restore_cached_map()
                    self.publish_map_feedback("cached", "地图：暂显示上次信息，等待后台核对", result_time=self._map_cache["updated_at"])
                else:
                    self.hide_map_overlay()
                    self.publish_map_feedback("waiting", "地图：画面已变化，等待重新扫描", clear=True)
            else:
                self.show_map_overlay()
                if (self.map_policy.matched_signature is None or self.map_policy.open_pending) and (
                        not self._map_feedback or self._map_feedback[0] not in ("failed", "interrupted", "cached", "cached_failed")):
                    self.publish_map_feedback("waiting", "地图：保持完整地图打开，等待画面稳定或下一次扫描")
            return
        scan_started = self.get_time()
        had_cache = self.has_map_cache()
        if had_cache:
            self.restore_cached_map()
            self.publish_map_feedback("refreshing", "地图：显示上次信息，后台更新中", started=time.time())
        else:
            self.publish_map_feedback("scanning", "地图：正在扫描，请保持完整地图打开", clear=True, started=time.time())
        self.show_map_overlay()
        try:
            result = self.detector.detect(DetectParam(map_detect_param=MapDetectParam(
                map_region=self.map_region, img=map_img, do_match_earth_shifting=True,
                hdr_processing_enabled=self.hdr_processing_enabled,
            )))
            earth_shifting = result.map_detect_result.earth_shifting
            if earth_shifting is None:
                self.reject_map_scan(signature, "地图：画面匹配不足，未显示预测，稍后自动重试")
                return
            if self.has_map_cache() and self._map_cache["terrain"] != earth_shifting:
                self._map_cache = None
                had_cache = False
                self.publish_map_feedback("scanning", "地图：已切换地形，正在重新识别", clear=True, started=time.time())
            self.do_match_map_pattern_flag = DoMatchMapPatternFlag.FALSE
            result = self.detector.detect(DetectParam(map_detect_param=MapDetectParam(
                map_region=self.map_region, img=map_img, earth_shifting=earth_shifting, do_match_pattern=True,
                hdr_processing_enabled=self.hdr_processing_enabled, return_pattern_topk=self.map_pattern_return_topk,
                consensus_when_ambiguous=self.automation_options.consensus_when_ambiguous,
            )))
            map_result = result.map_detect_result
            if not map_result.overlay_images:
                message = "地图：匹配不足，未显示预测，稍后自动重试" if map_result.low_quality else "地图：未生成可用标注，稍后自动重试"
                self.reject_map_scan(signature, message)
                return
            if self.get_time() - scan_started > MAP_SCAN_TIMEOUT_SECONDS:
                self.reject_map_scan(signature, "地图：扫描耗时过长，本次结果未采用，将自动重试")
                return
            self._is_game_foreground = self.check_game_foreground()
            if not self._is_game_foreground:
                self.reject_map_scan(signature, "地图：已切出游戏，本次结果未采用", "interrupted", hide=True)
                return
            # Publication must be validated against a fresh capture, not the old snapshot.
            latest = self.detector.detect(DetectParam(map_detect_param=MapDetectParam(
                map_region=self.map_region, do_match_full_map=True, hdr_processing_enabled=self.hdr_processing_enabled,
            ))).map_detect_result
            if not latest.is_full_map:
                self.reject_map_scan(signature, "地图：关图或缩放过早，本次结果未采用，开图后重试", "interrupted", hide=True)
                self.current_is_full_map = False
                self.map_policy.observe(False, None, self.get_time(), self.automation_options)
                return
            if signature_distance(signature, map_signature(latest.img)) > 6:
                self.reject_map_scan(signature, "地图：扫描期间画面已变化，本次结果未采用，将重试", "interrupted")
                return
            self.map_policy.complete(signature, self.get_time(), True)
            self.update_map_overlay_images(map_result.overlay_images, earth_shifting=earth_shifting)
            if map_result.plausible_count > 1:
                status = f"地图：{map_result.plausible_count} 个候选接近，显示共同信息" if self.automation_options.consensus_when_ambiguous else "地图：多个候选接近，当前为预测布局"
                kind = "uncertain"
            else:
                status, kind = "地图：扫描完成，结果已更新", "success"
            self._map_cache = {"session": self.session_number, "images": map_result.overlay_images, "terrain": earth_shifting,
                               "kind": kind, "message": status, "updated_at": time.time()}
            self.publish_map_feedback(kind, status, notify=not had_cache, result_time=self._map_cache["updated_at"])
            self.show_map_overlay()
            self.last_map_pattern_match_time = self.get_time()
        except Exception as exc:
            warning(f"Map scan failed and result was discarded: {exc}")
            self.reject_map_scan(signature, "地图：本次扫描出错，未显示预测，将自动重试")

    # =============== HP Management =============== #

    def update_hp_length(self, length: int | None):
        self._diagnostics["hp"] = f"已定位血条长度：{length} 像素" if length and length > 0 else "等待有效血条边界"
        if length is None or length <= 0:
            self.hp_overlay_ui_state_signal.emit(HpOverlayUIState(
                visible=False,
            ))
        else:
            self.hp_overlay_ui_state_signal.emit(HpOverlayUIState(
                visible=True,
                x=self.hpbar_region[0],
                y=self.hpbar_region[1],
                h=self.hpbar_region[3],
                w=length,
            ))

    def detect_and_update_hp(self):
        if not self.hp_detect_enabled:
            self.update_hp_length(None)
            return
        
        param = DetectParam(
            hp_detect_param=HpDetectParam(
                hpbar_region=self.hpbar_region,
                keep_last_valid=self.hp_detect_keep_last_valid,
            )
        )
        result = self.detector.detect(param)

        hp_length = result.hp_detect_result.hpbar_length
        if hp_length is not None:
            self.hp_length = hp_length
            self.update_hp_length(self.hp_length)

    # =============== Art Management =============== #

    def use_art_by_shortcut(self):
        config = Config.get()
        self.to_detect_art_time = self.get_time() + config.art_detect_delay_seconds
        info(f"Will detect art in {config.art_detect_delay_seconds} seconds.")
    
    def detect_and_update_art(self):
        if not self.art_detect_enabled or \
            self.to_detect_art_time is None or self.get_time() < self.to_detect_art_time:
            return
        
        param = DetectParam(
            art_detect_param=ArtDetectParam(
                art_region=self.art_region,
                hdr_processing_enabled=self.hdr_processing_enabled,
            )
        )
        result = self.detector.detect(param)
        self.to_detect_art_time = None
        
        if result.art_detect_result.art_type is None:
            self._diagnostics["art"] = "本次未识别到支持的绝招图标"
            info("No art detected.")
            return
        
        info(f"detected art: {result.art_detect_result.art_type}")
        self.art_type = result.art_detect_result.art_type
        self.art_start_time = self.get_time()
        self._diagnostics["art"] = "已识别绝招：" + self.art_type

    def get_art_progress_text_color(self) -> tuple[float, str, str]:
        if self.art_type is None or self.art_start_time is None:
            return 0.0, "", None
        
        config = Config.get()
        info = config.art_info[self.art_type]
        delay = info.get("delay", 0)
        duration = info.get("duration", 0)
        text = info.get("text", "")
        color = info.get("color", "#ffffff")

        t = max(0, self.get_time() - self.art_start_time - delay)
        if t > duration:
            self.art_type = None
            self.art_start_time = None
            return 0.0, "", None
        
        progress = 1.0 - t / duration
        text = f"{text} {format_period(int(max(duration - t, 0)))}"
        return progress, text, color
        
    # =============== Main Loop =============== #

    def detect_and_update_all(self):
        self.detect_and_update_dayx()
        self.detect_and_update_in_rain()
        self.detect_and_update_map()
        self.detect_and_update_hp()
        self.detect_and_update_art()

    def check_game_foreground(self) -> bool:
        is_foreground = is_window_in_foreground(GAME_WINDOW_TITLE)
        
        self.update_overlay_ui_state_signal.emit(OverlayUIState(
            is_game_foreground=is_foreground,
        ))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
            is_game_foreground=is_foreground,
        ))
        self.hp_overlay_ui_state_signal.emit(HpOverlayUIState(
            is_game_foreground=is_foreground,
        ))

        self.input_block_signals_signal.emit(self.only_detect_when_game_foreground and \
            not (is_foreground or self.is_setting_opened or self.is_menu_opened))
        
        return is_foreground

    def run(self):
        try:
            self._running = True
            info("Updater started.")

            last_detect_time = 0
            while self._running:
                start_time = self.get_time()
                self.process_automation_commands()

                is_game_foreground = self.check_game_foreground()
                try:
                    self.track_game_and_locate(is_game_foreground)
                except Exception as exc:
                    warning(f"Automatic capture unavailable, will retry: {exc}")
                    self._diagnostics["map"] = "当前画面暂不可截取，自动重试中"
                    self.emit_diagnostics()

                if self.get_time() - last_detect_time > self.detect_interval:
                    if not self.only_detect_when_game_foreground or is_game_foreground:
                        try:
                            self.detect_and_update_all()
                        except Exception as exc:
                            warning(f"Detection failed, will retry: {exc}")
                            self.hide_map_overlay()
                            self.map_policy.request("截图检测重试")
                            self.publish_map_feedback("failed", "地图：画面检测未完成，旧标注已隐藏，将自动重试", clear=True, notify=True)
                    last_detect_time = self.get_time()

                self.poll_alerts()
                self.update_phase_timer()
                day_progress, day_text = self.get_phase_progress_text()
                rain_progress, rain_text = self.get_in_rain_progress_text()
                art_progress, art_text, art_color = self.get_art_progress_text_color()

                self.update_overlay_ui_state_signal.emit(OverlayUIState(
                    day_progress=day_progress,
                    day_text=day_text,
                    rain_progress=rain_progress,
                    rain_text=rain_text,
                    rain_progress_visible=rain_progress > 0.0,
                    art_progress=art_progress,
                    art_text=art_text,
                    art_progress_visible=art_progress > 0.0,
                    art_color=art_color,
                ))

                elapsed = self.get_time() - start_time
                sleep_time = Config.get().update_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

            # Save a final option change even if Quit was clicked immediately.
            self.process_automation_commands()

        except Exception as e:
            error(f"Exception in updater run: {e}")
            raise e
        info("Updater stopped.")

    def stop(self):
        self._running = False
