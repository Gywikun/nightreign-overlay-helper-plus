# Based on NeuraXmy/nightreign-overlay-helper v0.10.5.
# Added/modified 2026-10-02; see NOTICE.md and LICENSE (GNU AGPL v3).
"""Stateful automation policies, independent of capture and Qt widgets."""
from dataclasses import asdict, dataclass, field, replace
import math


@dataclass
class AutomationOptions:
    automatic_regions: bool = True
    follow_window: bool = True
    automatic_map: bool = True
    refresh_on_open: bool = False
    refresh_on_change: bool = True
    map_refresh_seconds: int = 20
    map_min_interval: float = 5.0
    map_stable_seconds: float = 0.6
    consensus_when_ambiguous: bool = True
    notifications: bool = True
    sound: bool = True
    volume: int = 20
    popup_seconds: float = 3.5
    preferences_revision: int = 3
    circle_alerts: bool = True
    circle_early_seconds: int = 30
    circle_late_seconds: int = 10
    rain_alerts: bool = True
    rain_seconds: int = 10
    art_alerts: bool = True
    art_seconds: int = 3
    anchors: dict = field(default_factory=dict)
    anchor_geometry: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, values):
        values = values if isinstance(values, dict) else {}
        values = dict(values)
        revision = values.get("preferences_revision", 0)
        if values and (not isinstance(revision, (int, float)) or revision < 3):
            # The user-requested r3 behavior must also take effect for r2 profiles.
            values["refresh_on_open"] = False
            if values.get("volume") == 40:
                values["volume"] = 20
        values["preferences_revision"] = 3
        defaults = cls()
        kwargs = {}
        for key, default in asdict(defaults).items():
            value = values.get(key, default)
            if isinstance(default, bool):
                kwargs[key] = value if isinstance(value, bool) else default
            elif isinstance(default, (int, float)):
                kwargs[key] = value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else default
            else:
                kwargs[key] = value if isinstance(value, dict) else {}
        result = cls(**kwargs)
        result.volume = max(0, min(100, int(result.volume)))
        result.popup_seconds = max(.5, min(5.0, float(result.popup_seconds)))
        result.map_refresh_seconds = max(5, min(300, int(result.map_refresh_seconds)))
        result.map_min_interval = max(2.0, min(30.0, result.map_min_interval))
        result.map_stable_seconds = max(0.3, min(3.0, result.map_stable_seconds))
        for key in ("circle_early_seconds", "circle_late_seconds", "rain_seconds", "art_seconds"):
            setattr(result, key, max(1, min(120, int(getattr(result, key)))))
        result.anchors = {key: list(value) for key, value in result.anchors.items() if valid_anchor(value)}
        if not all(isinstance(result.anchor_geometry.get(key), (int, float)) and not isinstance(result.anchor_geometry.get(key), bool)
                   and math.isfinite(result.anchor_geometry[key]) and 16 <= result.anchor_geometry[key] <= 100000 for key in ("width", "height")):
            result.anchor_geometry = {}
        return result


def valid_anchor(value):
    return (isinstance(value, (list, tuple)) and len(value) == 4
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in value)
            and 0 <= value[0] < 1 and 0 <= value[1] < 1
            and 0 < value[2] <= 1 and 0 < value[3] <= 1
            and value[0] + value[2] <= 1.01 and value[1] + value[3] <= 1.01)


def normalize_region(region, window):
    if not region or not window:
        return None
    x, y, w, h = region
    wx, wy, ww, wh = window
    if ww <= 0 or wh <= 0:
        return None
    result = [(x - wx) / ww, (y - wy) / wh, w / ww, h / wh]
    return result if valid_anchor(result) else None


def restore_region(anchor, window):
    if not valid_anchor(anchor) or not window:
        return None
    x, y, w, h = window
    if w <= 0 or h <= 0:
        return None
    return [x + round(anchor[0] * w), y + round(anchor[1] * h),
            max(1, round(anchor[2] * w)), max(1, round(anchor[3] * h))]


def restore_hud_region(name, anchor, window, reference):
    """HUD dimensions scale with client height; left/right/center anchors persist."""
    if not valid_anchor(anchor) or not window:
        return None
    bw, bh = reference.get("width"), reference.get("height")
    if not isinstance(bw, (int, float)) or not isinstance(bh, (int, float)) or bw <= 0 or bh <= 0:
        return restore_region(anchor, window)
    wx, wy, ww, wh = window
    scale = wh / bh
    width, height = max(1, round(anchor[2] * bw * scale)), max(1, round(anchor[3] * wh))
    if name == "map_region":
        x = wx + ww - round((1 - anchor[0]) * bw * scale)
    elif name in ("day1_detect_region", "art_region"):
        x = wx + round(ww / 2 + (anchor[0] * bw - bw / 2) * scale)
    else:
        x = wx + round(anchor[0] * bw * scale)
    return [x, wy + round(anchor[1] * wh), width, height]


class DayCueLatch:
    """A visible DAY cue starts a timer once, never every capture frame."""
    def __init__(self):
        self.candidate = None
        self.count = 0
        self.latched = None
        self.missing = 0
        self.suppressed_until = 0.0
        self.last_started = {}

    def observe(self, cue, now):
        if cue is None:
            self.missing += 1
            self.candidate, self.count = None, 0
            if self.missing >= 3:
                self.latched = None
            return None
        self.missing = 0
        self.count = self.count + 1 if cue == self.candidate else 1
        self.candidate = cue
        if now < self.suppressed_until or cue == self.latched or self.count < 2:
            return None
        self.latched = cue
        if now - self.last_started.get(cue, -math.inf) < 12:
            return None
        self.last_started[cue] = now
        return cue

    def suppress(self, now, seconds=5):
        self.suppressed_until = now + seconds
        self.latched = self.candidate


class MapRefreshPolicy:
    def __init__(self):
        self.reset()

    def reset(self):
        self.visible = False
        self.open_pending = False
        self.pending_reason = None
        self.last_attempt = -math.inf
        self.last_success = -math.inf
        self.signature = None
        self.stable_since = None
        self.matched_signature = None
        self.generation = 0
        self.opened_at = -math.inf

    def request(self, reason="手动刷新"):
        self.pending_reason = reason

    def observe(self, visible, signature, now, options):
        opened = visible and not self.visible
        self.visible = visible
        if not visible:
            self.signature = None
            self.stable_since = None
            return None
        if opened:
            self.open_pending = True
            self.opened_at = now
        difference = signature_distance(self.signature, signature)
        if self.signature is None or difference > 3.0:
            self.signature, self.stable_since = signature, now
        if self.stable_since is None or now - self.stable_since < options.map_stable_seconds:
            return None
        if now - self.last_attempt < options.map_min_interval:
            return None
        reason = self.pending_reason
        if not reason and options.automatic_map:
            if self.matched_signature is None:
                reason = "首次开图"
            elif self.open_pending and options.refresh_on_open:
                reason = "重新开图"
            elif options.refresh_on_change and signature_distance(self.matched_signature, signature) > 6.0:
                reason = "地图画面变化"
            elif now - max(self.last_success, self.opened_at) >= options.map_refresh_seconds:
                reason = "定时更新"
        if not options.refresh_on_open:
            self.open_pending = False
        if reason:
            self.last_attempt = now
            self.open_pending = False
            self.pending_reason = None
        return reason

    def complete(self, signature, now, success):
        if success:
            self.last_success = now
            self.matched_signature = signature
            self.generation += 1
        else:
            # Back off from failure completion, including slow scans.
            self.last_attempt = max(self.last_attempt, now)
            self.pending_reason = "识别未完成，自动重试"


def signature_distance(left, right):
    if left is None or right is None or len(left) != len(right):
        return math.inf
    return sum(abs(int(a) - int(b)) for a, b in zip(left, right)) / max(1, len(left))


class AlertEngine:
    def __init__(self):
        self.reset()

    def reset(self):
        self.previous = {}
        self.fired = set()

    def observe(self, channel, token, remaining, thresholds):
        if token is None or remaining is None:
            self.previous.pop(channel, None)
            return []
        previous = self.previous.get(channel)
        self.previous[channel] = (token, remaining)
        if previous is None or previous[0] != token:
            return []
        result = []
        for threshold in sorted(set(thresholds), reverse=True):
            key = (channel, token, threshold)
            if key not in self.fired and previous[1] > threshold >= remaining >= 0:
                self.fired.add(key)
                result.append(threshold)
        # Keep a long running app bounded while preserving active phase events.
        if len(self.fired) > 128:
            tokens = {value[0] for value in self.previous.values()}
            self.fired = {key for key in self.fired if key[1] in tokens}
        return result


def plausible_matches(results):
    """Keep comparable candidates; error weights are not probabilities."""
    if not results:
        return []
    best = results[0]
    return [item for item in results if item.error <= best.error + 3 and item.score >= best.score - 10]


def consensus_pattern(patterns):
    """Only display predictions on which the plausible layouts agree."""
    first = patterns[0]
    common = {}
    for pos, construct in first.pos_constructions.items():
        if all(pos in other.pos_constructions and other.pos_constructions[pos].type == construct.type
               and other.pos_constructions[pos].is_underground == construct.is_underground for other in patterns[1:]):
            common[pos] = construct
    updates = {"pos_constructions": common}
    if any(item.nightlord != first.nightlord for item in patterns[1:]):
        updates["nightlord"] = -1
    groups = [("day1_pos", "day1_boss", "day1_extra_boss"),
              ("day2_pos", "day2_boss", "day2_extra_boss", "day2_pos_idx"),
              ("treasure",), ("rot_rew",),
              ("event_flag", "event_value", "evpat_flag", "evpat_value")]
    for group in groups:
        if not all(all(getattr(item, key) == getattr(first, key) for key in group) for item in patterns[1:]):
            for key in group:
                updates[key] = None if key.endswith("_pos") else -1 if "boss" in key else 0
    return replace(first, **updates)
